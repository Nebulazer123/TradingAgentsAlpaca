"""Resolved local inputs for analysis-only LangGraph checkpoint identities.

The pure ``checkpoint_identity`` module deliberately does not inspect Git,
files, environment, providers, or stores.  This adapter owns that local
discovery and supplies one complete, secret-safe identity before a qualifying
analysis graph is constructed.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tradingagents.graph.checkpoint_identity import (
    CHECKPOINT_RUN_IDENTITY_SCHEMA_VERSION,
    CheckpointRunIdentity,
    CheckpointRunIdentityError,
    build_checkpoint_run_identity,
)
from tradingagents.graph.checkpointer import saved_checkpoint_identities
from tradingagents.graph.packet_nodes import PACKET_HANDOFF_SCHEMA_VERSION, build_graph_run_id
from tradingagents.orchestration.decision_ledger import DecisionLedger, DecisionLedgerError, LedgerEvent


class CheckpointRuntimeIdentityError(ValueError):
    """Raised when analysis-only checkpoint identity discovery cannot prove safety."""


_GRAPH_TOPOLOGY_FILES = (
    "tradingagents/graph/setup.py",
    "tradingagents/graph/conditional_logic.py",
    "tradingagents/graph/analyst_execution.py",
    "tradingagents/graph/packet_nodes.py",
    "tradingagents/agents/utils/agent_states.py",
)
_BOUND_TOOL_FILES = (
    "tradingagents/graph/trading_graph.py",
    "tradingagents/agents/utils/agent_utils.py",
    "tradingagents/dataflows/config.py",
    "tradingagents/dataflows/interface.py",
)
_DATA_ROUTE_FILES = (
    "tradingagents/dataflows/config.py",
    "tradingagents/dataflows/interface.py",
    "tradingagents/dataflows/utils.py",
)
_LEARNING_POLICY_FILES = ("tradingagents/evals/learning_context.py",)
_CUTOFF_POLICY_FILES = ("tradingagents/graph/propagation.py",)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CheckpointRuntimeIdentityError(
            "checkpoint runtime inputs must be canonical JSON values"
        ) from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _clean_source_revision(project_root: Path) -> str:
    """Return the exact clean Git revision or fail before any graph construction."""
    git_environment = dict(os.environ)
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
    ):
        git_environment.pop(key, None)
    try:
        top_level = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            env=git_environment,
        )
        revision = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            env=git_environment,
        )
        status = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=git_environment,
        )
    except OSError as exc:
        raise CheckpointRuntimeIdentityError(
            "Git source identity is unavailable; start an uncheckpointed nonqualifying run"
        ) from exc
    if (
        top_level.returncode != 0
        or revision.returncode != 0
        or status.returncode != 0
    ):
        raise CheckpointRuntimeIdentityError(
            "Git source identity is unavailable; start an uncheckpointed nonqualifying run"
        )
    try:
        resolved_top_level = Path(top_level.stdout.strip()).resolve(strict=True)
    except OSError as exc:
        raise CheckpointRuntimeIdentityError(
            "Git source identity is unavailable; start an uncheckpointed nonqualifying run"
        ) from exc
    if resolved_top_level != project_root.resolve(strict=True):
        raise CheckpointRuntimeIdentityError(
            "Git source identity does not match the configured project root"
        )
    value = revision.stdout.strip()
    if status.stdout.strip():
        raise CheckpointRuntimeIdentityError(
            "source tree is dirty; commit or discard local changes before checkpointed analysis"
        )
    if len(value) not in {40, 64} or any(character not in "0123456789abcdef" for character in value):
        raise CheckpointRuntimeIdentityError("Git source revision is not canonical")
    return value


def _file_digest(project_root: Path, relative_path: str) -> tuple[str, str]:
    path = project_root / relative_path
    try:
        details = path.lstat()
    except OSError as exc:
        raise CheckpointRuntimeIdentityError(
            f"checkpoint source surface is unavailable: {relative_path}"
        ) from exc
    if path.is_symlink() or not path.is_file():
        raise CheckpointRuntimeIdentityError(
            f"checkpoint source surface must be a regular file: {relative_path}"
        )
    try:
        contents = path.read_bytes()
    except OSError as exc:
        raise CheckpointRuntimeIdentityError(
            f"checkpoint source surface is unreadable: {relative_path}"
        ) from exc
    del details
    return relative_path, hashlib.sha256(contents).hexdigest()


def _surface_digest(project_root: Path, relative_paths: Sequence[str]) -> str:
    return _sha256([_file_digest(project_root, path) for path in relative_paths])


def _prompt_surface_digest(project_root: Path) -> str:
    """Hash every agent implementation that can render a model prompt."""
    root = project_root / "tradingagents" / "agents"
    if root.is_symlink() or not root.is_dir():
        raise CheckpointRuntimeIdentityError("agent prompt surface is unavailable")
    paths = sorted(
        file.relative_to(project_root).as_posix()
        for file in root.rglob("*.py")
        if not file.is_symlink() and file.is_file()
    )
    if not paths:
        raise CheckpointRuntimeIdentityError("agent prompt surface is empty")
    return _surface_digest(project_root, paths)


def checkpoint_provider_reasoning_settings(
    config: Mapping[str, Any],
) -> dict[str, object]:
    provider = config.get("llm_provider")
    if type(provider) is not str:
        raise CheckpointRuntimeIdentityError("llm_provider must be a canonical string")
    settings: dict[str, object] = {
        "max_output_tokens": config.get("llm_max_output_tokens"),
        "max_retries": config.get("llm_max_retries"),
        "timeout_seconds": config.get("llm_timeout_seconds"),
    }
    normalized = provider.lower()
    if normalized == "google":
        settings["thinking"] = config.get("google_thinking_level")
    elif normalized == "openai":
        settings["reasoning_effort"] = config.get("openai_reasoning_effort")
    elif normalized == "anthropic":
        settings["effort"] = config.get("anthropic_effort")
    elif normalized == "ollama":
        if config.get("ollama_extra_body") is not None:
            raise CheckpointRuntimeIdentityError(
                "ollama_extra_body must be absent for checkpointed analysis"
            )
        settings.update(
            {
                "temperature": config.get("ollama_temperature"),
                "max_tokens": config.get("ollama_max_completion_tokens"),
                "top_p": config.get("ollama_top_p"),
                "presence_penalty": config.get("ollama_presence_penalty"),
            }
        )
    return {key: value for key, value in settings.items() if value is not None}


def _learning_policy_identity(config: Mapping[str, Any], project_root: Path) -> str:
    policy = {
        "source": _surface_digest(project_root, _LEARNING_POLICY_FILES),
        "root": str(
            Path(
                config.get("learning_context_root")
                or (Path(str(config["results_dir"])) / "learning_availability")
            ).expanduser().resolve(strict=False)
        ),
        "setup": config.get("learning_context_setup"),
        "sector": config.get("learning_context_sector"),
        "regime": config.get("learning_context_regime"),
        "evidence_type": config.get("learning_context_evidence_type"),
        "horizon": config.get("learning_context_horizon"),
        "max_chars": config.get("learning_context_max_chars", 4_000),
        "min_resolved": config.get("learning_context_min_resolved", 3),
    }
    return _sha256(policy)


def _head_hasher(root: Path, contract: str):
    return hashlib.sha256(_canonical_bytes({
        "contract": contract,
        "root_sha256": hashlib.sha256(str(root).encode()).hexdigest(),
    }))


def _learning_evidence_predecessor(config: Mapping[str, Any]) -> str:
    root = Path(config.get("learning_context_root") or (Path(str(config["results_dir"])) / "learning_availability")).expanduser()
    if root.is_symlink():
        raise CheckpointRuntimeIdentityError("checkpoint learning evidence root must not be a symlink")
    root = root.resolve(strict=False)
    hasher = _head_hasher(root, "learning-evidence-predecessor-v1")
    events = root / "events.jsonl"
    try:
        descriptor = os.open(events, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return hasher.hexdigest()
    except OSError as exc:
        raise CheckpointRuntimeIdentityError("checkpoint learning evidence predecessor is unreadable") from exc
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise CheckpointRuntimeIdentityError("checkpoint learning evidence predecessor must be a regular file")
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise CheckpointRuntimeIdentityError("checkpoint learning evidence changed during inspection")
    return hasher.hexdigest()


def _decision_head_snapshot(config: Mapping[str, Any]):
    ledger = DecisionLedger(Path(str(config["results_dir"])) / "control_plane/decisions")
    try:
        events = ledger.read_authenticated_events()
    except (DecisionLedgerError, OSError) as exc:
        raise CheckpointRuntimeIdentityError("checkpoint decision ledger provenance is invalid") from exc
    hasher = _head_hasher(ledger.root, "decision-ledger-predecessor-v1")
    prefixes = [hasher.hexdigest()]
    for event in events:
        hasher.update(event.canonical_json_bytes() + b"\n")
        prefixes.append(hasher.hexdigest())
    return events, tuple(prefixes)


def capture_checkpoint_predecessors(config: Mapping[str, Any]) -> dict[str, str]:
    """Capture distinct, destination-bound pre-run heads without creating stores."""
    learning = _learning_evidence_predecessor(config)
    _, decision_prefixes = _decision_head_snapshot(config)
    return {"learning_evidence_predecessor": learning, "decision_ledger_predecessor": decision_prefixes[-1]}


def validate_checkpoint_predecessors(
    config: Mapping[str, Any], identity: CheckpointRunIdentity, *, run_id: str, resuming: bool,
) -> tuple[LedgerEvent, ...]:
    """Accept only the exact pre-run history plus authenticated same-run events."""
    # Learning observations have no graph-run ownership; this graph does not
    # append them. No learning-head change can be classified as its own write.
    if _learning_evidence_predecessor(config) != identity.learning_evidence_predecessor:
        raise CheckpointRuntimeIdentityError("checkpoint learning_evidence_predecessor changed")
    events, prefixes = _decision_head_snapshot(config)
    if identity.decision_ledger_predecessor == prefixes[-1]:
        return events
    if not resuming or identity.decision_ledger_predecessor not in prefixes:
        raise CheckpointRuntimeIdentityError("checkpoint decision_ledger_predecessor changed or rolled back")
    first_own_event = prefixes.index(identity.decision_ledger_predecessor)
    if any(event.run_id != run_id for event in events[first_own_event:]):
        raise CheckpointRuntimeIdentityError("checkpoint decision_ledger_predecessor has unrelated advances")
    return events


def build_analysis_checkpoint_identity(
    *,
    config: Mapping[str, Any],
    selected_analysts: Sequence[str],
    asset_type: str,
    project_root: str | Path | None = None,
    ticker: str | None = None,
    trade_date: str | None = None,
) -> CheckpointRunIdentity:
    """Resolve one complete identity for a qualifying analysis-only entrypoint."""
    root = Path(project_root or Path(__file__).resolve().parents[2]).resolve(strict=True)
    backend_url = config.get("backend_url")
    if type(backend_url) is not str or not backend_url.strip():
        raise CheckpointRuntimeIdentityError(
            "backend_url must be explicitly resolved for checkpointed analysis"
        )
    try:
        lock_digest = hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest()
    except OSError as exc:
        raise CheckpointRuntimeIdentityError("uv.lock is required for checkpointed analysis") from exc
    data_route_payload = {
        "source": _surface_digest(root, _DATA_ROUTE_FILES),
        "data_vendors": config.get("data_vendors"),
        "tool_vendors": config.get("tool_vendors"),
        "news_article_limit": config.get("news_article_limit"),
        "global_news_article_limit": config.get("global_news_article_limit"),
        "global_news_lookback_days": config.get("global_news_lookback_days"),
        "global_news_queries": config.get("global_news_queries"),
        "benchmark_ticker": config.get("benchmark_ticker"),
        "benchmark_map": config.get("benchmark_map"),
    }
    bound_tool_payload = {
        "source": _surface_digest(root, _BOUND_TOOL_FILES),
        "selected_analysts": list(selected_analysts),
        "tool_free_analysts": config.get("tool_free_analysts", []),
    }
    try:
        identity = build_checkpoint_run_identity(
            identity_schema_version=CHECKPOINT_RUN_IDENTITY_SCHEMA_VERSION,
            clean_source_revision=_clean_source_revision(root),
            source_tree_dirty=False,
            uv_lock_sha256=lock_digest,
            selected_analysts=selected_analysts,
            asset_type=asset_type,
            max_debate_rounds=config["max_debate_rounds"],
            max_risk_discuss_rounds=config["max_risk_discuss_rounds"],
            max_analyst_tool_rounds=config.get("max_analyst_tool_rounds", 8),
            max_recur_limit=config.get("max_recur_limit", 100),
            analyst_concurrency_limit=config.get("analyst_concurrency_limit", 1),
            tool_free_analysts=config.get("tool_free_analysts", []),
            requested_provider=config["llm_provider"],
            requested_quick_model=config["quick_think_llm"],
            requested_deep_model=config["deep_think_llm"],
            backend_route_identity=backend_url,
            output_language=config.get("output_language", "English"),
            provider_reasoning_settings=checkpoint_provider_reasoning_settings(config),
            graph_topology_sha256=_surface_digest(root, _GRAPH_TOPOLOGY_FILES),
            agent_prompt_surface_sha256=_prompt_surface_digest(root),
            bound_tool_surface_sha256=_sha256(bound_tool_payload),
            data_route_surface_sha256=_sha256(data_route_payload),
            packet_handoff_schema_version=PACKET_HANDOFF_SCHEMA_VERSION,
            learning_context_policy_identity=_learning_policy_identity(config, root),
            trade_date_cutoff_policy_identity=_sha256(
                {
                    "contract": "market-date-cutoff-v1",
                    "source": _surface_digest(root, _CUTOFF_POLICY_FILES),
                }
            ),
            **capture_checkpoint_predecessors(config),
        )
    except CheckpointRunIdentityError as exc:
        raise CheckpointRuntimeIdentityError(
            "checkpoint runtime identity is incomplete or noncanonical"
        ) from exc
    if (ticker is None) != (trade_date is None):
        raise CheckpointRuntimeIdentityError("checkpoint resume discovery requires ticker and trade_date together")
    if ticker is None:
        return identity
    try:
        saved = saved_checkpoint_identities(config["data_cache_dir"], ticker, trade_date)
    except ValueError as exc:
        raise CheckpointRuntimeIdentityError("checkpoint retained identity is invalid") from exc
    if not saved:
        return identity
    if len(saved) != 1:
        raise CheckpointRuntimeIdentityError("checkpoint has multiple retained identities; explicitly clear the exact unwanted run")
    stored = saved[0]
    for field, expected in identity.to_dict().items():
        if field not in {"identity_sha256", "decision_ledger_predecessor"} and stored.to_dict()[field] != expected:
            raise CheckpointRuntimeIdentityError(f"checkpoint identity mismatch at {field}")
    validate_checkpoint_predecessors(
        config, stored, run_id=build_graph_run_id(ticker, trade_date, asset_type, stored.identity_sha256), resuming=True,
    )
    return stored
