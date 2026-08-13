"""Supervisor error self-heal handoff packets.

The handoff is deliberately advisory. It can tell Codex or n8n when a fresh
repair chat is warranted, but it cannot trade, approve, or edit anything by
itself.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from collections.abc import Mapping
from contextlib import suppress
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tradingagents.brokers.manual_action_attribution import (
    capture_owner_manual_action_attribution,
    capture_source_autonomous_order,
    replay_suppression_key,
)
from tradingagents.orchestration.authority import ActionClass, authority_for
from tradingagents.orchestration.incidents import is_safe_incident_id
from tradingagents.orchestration.recovery import (
    load_recovery_evidence,
    publish_rearm_receipt,
    rearm_after_verified_recovery,
)
from tradingagents.orchestration.work_packets import build_packet_id
from tradingagents.policy.decision_authority import resolve_exit_authority
from tradingagents.policy.io import atomic_write_text
from tradingagents.policy.live_control import (
    _write_live_control_state_locked,
    live_control_lock,
    load_live_control_state,
    write_live_control_state,
)
from tradingagents.policy.promotion_sync import (
    promotion_state_lock,
    sync_promotion_state_from_tournament,
)
from tradingagents.policy.risk_envelope import load_risk_envelope

UTC = dt.timezone.utc
DEFAULT_CONTEXT_DIR = Path("results/_context")
DEFAULT_OUTPUT_DIR = Path("results/self_heal")
DEFAULT_PLAN_OUTPUT_DIR = Path("results/self_heal/plans")
DEFAULT_SIGNATURE_STATE_NAME = "signature-state.json"
DEFAULT_SAFE_REVERIFY_MINUTES = 15

FORBIDDEN_EFFECTS = (
    "submit_order",
    "cancel_order",
    "replace_order",
    "close_position",
    "waive_live_gate",
    "expose_credentials",
    "change_experiment_charter",
)

RECOVERY_EFFECTS = (
    "resolve_policy_conflict",
    "regenerate_promotion_evidence",
    "sync_promotion_state_from_evidence",
    "read_only_broker_reconciliation",
    "run_focused_tests",
    "integrity_verification",
    "refresh_live_control_after_ready",
)


def _required_authority_owner(
    action: ActionClass,
    *,
    expected_owner: str,
) -> str:
    verdict = authority_for(action)
    if (
        verdict.allowed is not True
        or verdict.human_required is not False
        or verdict.owner_role != expected_owner
    ):
        raise ValueError(
            f"{action.value} authority contract is not available"
        )
    return verdict.owner_role


RECOVERY_RECIPE_NAME = "resolve_policy_sync_reconcile_verify_rearm"
RECOVERY_PHASES = (
    "resolve_authority",
    "regenerate_evidence",
    "reconcile",
    "focused_verify",
    "sync_promotion",
    "ready_incident",
    "manifest",
    "rearm",
)
RECOVERY_FOCUSED_TESTS = (
    "tests/test_recovery_coordinator.py",
    "tests/test_self_heal_recovery.py",
    "tests/test_promotion_sync.py",
    "tests/test_promotion_policy.py",
    "tests/test_live_gate.py",
    "tests/test_symbol_reconciliation.py",
)
RECOVERY_MAX_ATTEMPTS = 3
RECOVERY_BACKOFF_SECONDS = (0, 30, 120)
RECOVERY_LEASE_MINUTES = 30
BOARD_REVIEW_SIGNALS = frozenset(
    {
        ("hourly", "board_review"),
        ("execution_board_review", "board_review"),
    }
)
DEFAULT_BOARD_EVIDENCE_ROOT = Path("results")
DEFAULT_BOARD_LEDGER_ROOT = Path("state/decision_ledger")
DEFAULT_BOARD_REVIEW_PATH = Path("results/execution_board/latest.json")
_BOARD_TIMESTAMPED_PACKET = re.compile(r"^execution-board-review-[A-Za-z0-9._-]+\.json$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")


class _PromotionStalePreimage(RuntimeError):
    """A concurrent canonical promotion writer won the compare-and-swap."""

HIGH_REASONS = {"blocker", "issues", "schema", "graph_failure", "abnormal_pl", "unexplained_action"}
MEDIUM_REASONS = {"model_telemetry", "crawler", "quality", "automation_health"}
LOW_REASONS = {"stale", "notify", "submitted", "candidate_change", "changed_tournament_leader"}
SELF_HEAL_REASONS = HIGH_REASONS | MEDIUM_REASONS | LOW_REASONS
EXCLUDED_LABELS = {"self_heal_handoff", "self_heal_plan", "hook_event"}
PLAN_ONLY_REASONS = {"connector_health", "source_routing", "failed_checks", "board_review", "approval_conflict"}
PLAN_REASONS = SELF_HEAL_REASONS | PLAN_ONLY_REASONS
ORDER_ADJACENT_LABELS = {
    "hourly",
    "execution_board_review",
    "paper_tournament",
    "promotion_state",
    "alpaca",
    "live_supervisor",
}
MODEL_ROUTE_PROBE_COMMAND = (
    "uv run --no-sync python -m cli.main research automation-orchestration-plan "
    "--candidate-symbols XOM --no-research-context "
    "--output-dir results/research_batches/model_route_health "
    "--model-telemetry-dir results/model_telemetry --json-output"
)
MODEL_TELEMETRY_REPORT_COMMAND = (
    "uv run --no-sync python -m cli.main research model-telemetry-report --json-output"
)
AGENT_LEDGER_SUMMARY_COMMAND = (
    "uv run --no-sync python -m cli.main research agent-ledger-summary --json-output"
)
LOSS_REVIEW_EVIDENCE_COMMAND = (
    "uv run --no-sync python -m cli.main research loss-review-evidence --json-output"
)
PREOPEN_VALIDATION_COMMAND = (
    "uv run --no-sync python -m cli.main alpaca preopen-validation --json-output"
)
CONTEXT_SNAPSHOT_COMMAND = "uv run --no-sync python scripts/automation_context_snapshot.py --write"
SAFE_AUTOFIX_ACTIONS: dict[str, dict[str, Any]] = {
    "connector_health": {
        "recommended_action": "refresh_connector_health_and_use_fallbacks",
        "verify_command": CONTEXT_SNAPSHOT_COMMAND,
        "safe_effects": ["refresh_compact_context", "record_fallback_guidance"],
    },
    "source_routing": {
        "recommended_action": "refresh_source_routing_context",
        "verify_command": CONTEXT_SNAPSHOT_COMMAND,
        "safe_effects": ["refresh_compact_context", "record_source_gap_guidance"],
    },
    "quality": {
        "recommended_action": "refresh_or_downrank_stale_sources",
        "verify_command": CONTEXT_SNAPSHOT_COMMAND,
        "safe_effects": ["refresh_compact_context", "record_downrank_guidance"],
    },
    "stale": {
        "recommended_action": "refresh_stale_context_packet",
        "verify_command": CONTEXT_SNAPSHOT_COMMAND,
        "safe_effects": ["refresh_compact_context"],
    },
    "model_telemetry": {
        "recommended_action": "probe_model_routes_and_use_available_fallbacks",
        "execute_commands": [
            MODEL_ROUTE_PROBE_COMMAND,
            MODEL_TELEMETRY_REPORT_COMMAND,
            CONTEXT_SNAPSHOT_COMMAND,
        ],
        "verify_command": CONTEXT_SNAPSHOT_COMMAND,
        "safe_effects": ["refresh_compact_context", "record_model_route_guidance"],
    },
    "crawler": {
        "recommended_action": "run_crawler_runtime_doctor_or_repair_runtime",
        "verify_command": CONTEXT_SNAPSHOT_COMMAND,
        "safe_effects": ["refresh_compact_context", "record_runtime_guidance"],
    },
    "schema": {
        "recommended_action": "regenerate_compact_context_and_escalate_if_invalid",
        "verify_command": CONTEXT_SNAPSHOT_COMMAND,
        "safe_effects": ["refresh_compact_context", "record_schema_guidance"],
    },
    "graph_failure": {
        "recommended_action": "rerun_analysis_with_fallback_route_only_after_manual_review",
        "verify_command": None,
        "safe_effects": ["record_graph_failure_guidance"],
    },
    "automation_health": {
        "recommended_action": "write_night_shift_patrol_then_rerun_automation_health_audit",
        "execute_commands": [
            "uv run --no-sync python -m cli.main research night-shift-patrol --json-output",
            "uv run --no-sync python -m cli.main research automation-health-audit --json-output",
        ],
        "verify_command": "uv run --no-sync python -m cli.main research automation-health-audit --json-output",
        "safe_effects": [
            "write_night_shift_patrol_evidence",
            "refresh_automation_health_evidence",
            "record_schedule_gap_guidance",
        ],
    },
}
LABEL_SAFE_AUTOFIX_ACTIONS: dict[tuple[str, str], dict[str, Any]] = {
    ("agent_intelligence_summary", "schema"): {
        "recommended_action": "regenerate_agent_ledger_summary_then_compact_context",
        "execute_commands": [
            AGENT_LEDGER_SUMMARY_COMMAND,
            CONTEXT_SNAPSHOT_COMMAND,
        ],
        "verify_command": CONTEXT_SNAPSHOT_COMMAND,
        "safe_effects": [
            "refresh_agent_intelligence_summary",
            "refresh_compact_context",
            "record_schema_guidance",
        ],
    },
    ("loss_review_evidence", "stale"): {
        "recommended_action": "refresh_latest_loss_review_evidence_then_compact_context",
        "execute_commands": [
            LOSS_REVIEW_EVIDENCE_COMMAND,
            CONTEXT_SNAPSHOT_COMMAND,
        ],
        "verify_command": CONTEXT_SNAPSHOT_COMMAND,
        "safe_effects": [
            "refresh_loss_review_evidence",
            "refresh_compact_context",
            "record_board_review_guidance",
        ],
    },
    ("preopen_validation", "stale"): {
        "recommended_action": "refresh_preopen_validation_then_compact_context",
        "execute_commands": [
            PREOPEN_VALIDATION_COMMAND,
            CONTEXT_SNAPSHOT_COMMAND,
        ],
        "verify_command": CONTEXT_SNAPSHOT_COMMAND,
        "safe_effects": [
            "refresh_preopen_validation",
            "refresh_compact_context",
            "record_closed_market_or_live_control_guidance",
        ],
    },
}


def recovery_recipe(name: str = RECOVERY_RECIPE_NAME) -> dict[str, Any]:
    """Return the only recovery recipe self-heal is allowed to own.

    The recipe deliberately contains effects rather than commands.  Concrete
    integrations are injected adapters, so an incident value can never become
    shell syntax and the coordinator has no order-writing capability.
    """
    if name != RECOVERY_RECIPE_NAME:
        raise ValueError("unknown recovery recipe")
    return {
        "name": RECOVERY_RECIPE_NAME,
        "owner_role": "reliability_controller",
        "effects": list(RECOVERY_EFFECTS),
        "forbidden_effects": list(FORBIDDEN_EFFECTS),
        "phases": list(RECOVERY_PHASES),
        "retry_policy": {
            "max_attempts": RECOVERY_MAX_ATTEMPTS,
            "backoff_seconds": list(RECOVERY_BACKOFF_SECONDS),
            "lease_minutes": RECOVERY_LEASE_MINUTES,
            "on_exhaustion": "remain_owned_frozen_with_follow_on",
        },
    }


def classify_recovery_signal(trigger: Mapping[str, Any]) -> dict[str, Any]:
    """Classify by requested effect, never by a mere mention of an order.

    A read-only reconciliation can repair evidence without gaining trading
    authority.  Unknown order state is different: it needs a real external
    authority decision and therefore remains frozen and externally blocked.
    """
    label = str(trigger.get("label") or "")
    reason = str(trigger.get("reason") or "")
    effects = _trigger_effects(trigger)
    forbidden = sorted(set(effects).intersection(FORBIDDEN_EFFECTS))
    base: dict[str, Any] = {
        "label": label,
        "reason": reason,
        "symbol": trigger.get("symbol"),
        "observed_effects": effects,
        "forbidden_effects": list(FORBIDDEN_EFFECTS),
        "owner_role": "reliability_controller",
        "recipe": RECOVERY_RECIPE_NAME,
        "may_rearm": False,
    }
    if forbidden:
        return {
            **base,
            "classification": "forbidden_effect",
            "forbidden_effects_observed": forbidden,
            "status": "frozen",
        }
    if reason in {"unknown_open_order", "unknown_broker_state", "broker_authority_required"}:
        return {
            **base,
            "classification": "external_blocked",
            "status": "external_authority_required",
            "external_blocker": "broker_state_authority",
        }
    if (label, reason) in BOARD_REVIEW_SIGNALS:
        return {
            **base,
            "classification": "business_decision_pending",
            "status": "retryable",
            "owner_role": "portfolio_executive",
            "recipe": None,
            "allowed_effects": ["trade_decision"],
            "may_rearm": False,
        }
    recoverable_labels = {
        "policy_rule_conflict",
        "promotion_state",
        "broker_reconciliation",
    }
    recoverable_reasons = {
        "approval_conflict",
        "policy_conflict",
        "reconciliation_mismatch",
    }
    if (
        label in recoverable_labels
        or reason in recoverable_reasons
    ):
        return {
            **base,
            "classification": "recoverable_integrity",
            "status": "owned_recovery_ready",
            "may_rearm": True,
        }
    return {**base, "classification": "observe_only", "status": "observed"}


def _strict_board_projection(
    board: Mapping[str, Any],
    *,
    verified: Any,
    ledger_packet_id: str,
    evidence_root: Path,
) -> bool:
    """Require the BOARD projection to be one exact view of its evidence.

    The authenticated decision is necessary but not sufficient: it must be the
    decision for the exact loss-review subject the latest BOARD actually
    displays.  This rejects copied, cross-symbol, and cross-evidence BOARD
    projections before a decision can close a self-heal signal.
    """
    if (
        board.get("kind") != "execution_board_review"
        or board.get("schema_version") != 1
        or board.get("analysis_only") is not True
        or board.get("can_submit_orders") is not False
        or board.get("execution_authority") != "none"
    ):
        return False
    projected = board.get("autonomous_loss_decision")
    loss = board.get("loss_review_evidence")
    if not isinstance(projected, Mapping) or not isinstance(loss, Mapping):
        return False
    expected_projection = {
        "decision": verified.decision,
        "decision_id": verified.decision_id,
        "ledger_packet_id": ledger_packet_id,
        "symbol": verified.symbol,
        "supervisor_decision_id": verified.supervisor_decision_id,
        "source_revision": verified.source_revision,
        "trade_decision_resolved": verified.trade_decision_resolved,
        "execution_eligible": verified.execution_eligible,
        "execution_blockers": list(verified.execution_blockers),
        "execution_blockers_sha256": hashlib.sha256(
            json.dumps(
                list(verified.execution_blockers), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
        "exit_allowed": verified.exit_allowed,
        "analysis_only": verified.analysis_only,
        "execution_authority": verified.execution_authority,
        "can_submit_orders": verified.can_submit_orders,
        "recommendation": (
            "autonomous_hold"
            if verified.decision == "HOLD"
            else "autonomous_sell_authorized_pending_execution_intent"
        ),
    }
    if any(projected.get(key) != value for key, value in expected_projection.items()):
        return False
    try:
        from tradingagents.orchestration.decision_ledger import DecisionLedger

        ledger_packet = DecisionLedger(
            evidence_root.parent / DEFAULT_BOARD_LEDGER_ROOT
        ).read_authenticated_packet(ledger_packet_id, evidence_root=evidence_root)
    except (OSError, TypeError, ValueError):
        return False
    if len(ledger_packet.evidence_refs) != 3:
        return False
    decision_ref, supervisor_ref, loss_ref = ledger_packet.evidence_refs
    try:
        loss_path = (evidence_root / verified.loss_evidence_packet.path).resolve()
        loss_path.relative_to(evidence_root.resolve())
        loss_state = loss_path.lstat()
        if stat.S_ISLNK(loss_state.st_mode) or not stat.S_ISREG(loss_state.st_mode):
            return False
        loss_bytes = loss_path.read_bytes()
        loss_packet = json.loads(loss_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return False
    if (
        not isinstance(loss_packet, Mapping)
        or hashlib.sha256(loss_bytes).hexdigest()
        != verified.loss_evidence_packet.sha256
        or len(loss_bytes) != verified.loss_evidence_packet.size_bytes
        or loss_packet.get("symbol") != verified.symbol
        or not isinstance(loss_packet.get("packet_id"), str)
        or not loss_packet["packet_id"]
    ):
        return False
    source_digest = _accepted_sources_digest(verified.accepted_sources)
    expected_receipt = {
        "decision_evidence": {
            "path": decision_ref.path,
            "sha256": decision_ref.sha256,
            "size_bytes": decision_ref.size_bytes,
        },
        "supervisor_packet": {
            "path": supervisor_ref.path,
            "sha256": supervisor_ref.sha256,
            "size_bytes": supervisor_ref.size_bytes,
        },
        "loss_evidence_packet": {
            "path": loss_ref.path,
            "sha256": loss_ref.sha256,
            "size_bytes": loss_ref.size_bytes,
            "packet_id": loss_packet["packet_id"],
        },
        "accepted_sources_sha256": source_digest,
        "accepted_source_count": len(verified.accepted_sources),
    }
    if any(projected.get(key) != value for key, value in expected_receipt.items()):
        return False
    redundant_paths = {
        "ledger_packet_path": str(
            evidence_root.parent
            / DEFAULT_BOARD_LEDGER_ROOT
            / "packets"
            / f"{ledger_packet_id}.json"
        ),
        "decision_evidence_path": decision_ref.path,
    }
    if any(
        key in projected and projected.get(key) != value
        for key, value in redundant_paths.items()
    ):
        return False
    expected_loss = {
        "symbol": verified.symbol,
        "supervisor_packet_path": verified.supervisor_packet.path,
        "raw_packet_path": verified.loss_evidence_packet.path,
        "next_action": expected_projection["recommendation"],
    }
    if any(loss.get(key) != value for key, value in expected_loss.items()):
        return False
    source_binding = loss.get("source_binding")
    if not isinstance(source_binding, Mapping) or source_binding.get("matched") is not True:
        return False
    bindings = source_binding.get("bindings")
    if not isinstance(bindings, Mapping):
        return False
    supervisor = bindings.get("supervisor")
    raw_loss = bindings.get("raw_loss")
    if not isinstance(supervisor, Mapping) or not isinstance(raw_loss, Mapping):
        return False
    expected_supervisor = {
        "path": verified.supervisor_packet.path,
        "sha256": verified.supervisor_packet.sha256,
        "size_bytes": verified.supervisor_packet.size_bytes,
        "decision_id": verified.supervisor_decision_id,
        "symbol": verified.symbol,
    }
    projected_loss_packet = projected.get("loss_evidence_packet")
    if not isinstance(projected_loss_packet, Mapping) or projected_loss_packet.get(
        "packet_id"
    ) != loss_packet["packet_id"]:
        return False
    expected_loss_binding = {
        "path": verified.loss_evidence_packet.path,
        "sha256": verified.loss_evidence_packet.sha256,
        "size_bytes": verified.loss_evidence_packet.size_bytes,
        "symbol": verified.symbol,
        "source_revision": verified.source_revision,
        "packet_id": loss_packet["packet_id"],
    }
    return all(supervisor.get(key) == value for key, value in expected_supervisor.items()) and all(
        raw_loss.get(key) == value for key, value in expected_loss_binding.items()
    )


def _accepted_sources_digest(sources: Any) -> str:
    """Match the producer's canonical Unicode JSON digest for source receipts."""
    return hashlib.sha256(
        json.dumps(
            [source.compact() for source in sources],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _authenticated_latest_board_decision(
    repo_root: Path,
    *,
    now: dt.datetime | None = None,
) -> dict[str, Any] | None:
    """Read one fixed BOARD reference and authenticate it through the ledger.

    A self-heal signal is not allowed to nominate a decision file, ledger, or
    evidence root.  The installed paths below are the sole trust boundary.
    This helper never treats the BOARD's displayed fields as authority: those
    fields must agree with the independently replayed immutable decision.
    """
    board_path = repo_root / DEFAULT_BOARD_REVIEW_PATH
    captured = _capture_contained_json_file(board_path, root=repo_root)
    if captured is None:
        return None
    board_path, board_raw, board = captured
    if not isinstance(board, Mapping):
        return None
    displayed = board.get("autonomous_loss_decision")
    if not isinstance(displayed, Mapping):
        return None
    ledger_packet_id = displayed.get("ledger_packet_id")
    if not isinstance(ledger_packet_id, str) or not ledger_packet_id.strip():
        return None
    try:
        from tradingagents.policy.loss_board_decision import (
            verify_autonomous_loss_board_decision,
        )

        verified = verify_autonomous_loss_board_decision(
            ledger_root=repo_root / DEFAULT_BOARD_LEDGER_ROOT,
            ledger_packet_id=ledger_packet_id,
            evidence_root=repo_root / DEFAULT_BOARD_EVIDENCE_ROOT,
            now=now,
        )
    except (OSError, TypeError, ValueError):
        return None
    if not _strict_board_projection(
        board,
        verified=verified,
        ledger_packet_id=ledger_packet_id,
        evidence_root=repo_root / DEFAULT_BOARD_EVIDENCE_ROOT,
    ) or verified.producer_role != "portfolio_executive":
        return None
    return {
        "decision": verified.decision,
        "decision_id": verified.decision_id,
        "ledger_packet_id": ledger_packet_id,
        "symbol": verified.symbol,
        "board_path": str(board_path),
        "board_sha256": hashlib.sha256(board_raw).hexdigest(),
        "board_size_bytes": len(board_raw),
        "supervisor_packet": {
            "path": verified.supervisor_packet.path,
            "sha256": verified.supervisor_packet.sha256,
            "size_bytes": verified.supervisor_packet.size_bytes,
            "decision_id": verified.supervisor_decision_id,
            "symbol": verified.symbol,
        },
    }


def _captured_signal_packet(
    signal: Mapping[str, Any], *, root: Path
) -> tuple[Path, bytes, Mapping[str, Any]] | None:
    """Capture one declared signal packet without letting it escape the repo."""
    path = _safe_lexical_trigger_file(signal, root=root)
    if path is None:
        return None
    return _capture_contained_json_file(path, root=root)


def _safe_lexical_trigger_file(
    signal: Mapping[str, Any], *, root: Path
) -> Path | None:
    """Return a contained regular file only when no lexical component is a symlink."""
    raw_path = signal.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    return _safe_lexical_file_path(raw_path, root=root)


def _safe_lexical_file_path(raw_path: str, *, root: Path) -> Path | None:
    """Normalize a contained path without inspecting mutable parents.

    The returned pathname is deliberately *not* proof that it is safe to read.
    Callers must use ``_capture_contained_json_file`` below, which walks every
    parent from an already-open root descriptor.  Splitting lexical containment
    from the read avoids an inspect-then-open parent-symlink race.
    """
    root = root.resolve()
    candidate = Path(raw_path)
    supplied = candidate if candidate.is_absolute() else root / candidate
    # ``abspath`` normalizes dots but intentionally does not resolve symlinks.
    lexical = Path(os.path.abspath(str(supplied)))
    try:
        relative = lexical.relative_to(root)
    except ValueError:
        # macOS exposes the same temporary hierarchy through both ``/var``
        # and ``/private/var``.  Translate only that root alias while keeping
        # every untrusted child component lexical for descriptor traversal.
        root_text = str(root)
        if not root_text.startswith("/private/"):
            return None
        try:
            relative = lexical.relative_to(Path(root_text.removeprefix("/private")))
        except ValueError:
            return None
        lexical = root / relative
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    return lexical


def _capture_contained_json_file(
    path: str | Path, *, root: Path
) -> tuple[Path, bytes, Mapping[str, Any]] | None:
    """Capture a regular JSON file through no-follow descriptor traversal.

    Each directory is opened relative to the previous trusted descriptor with
    ``O_DIRECTORY | O_NOFOLLOW``.  The final file is also no-followed and
    fstat-checked before reading.  This is intentionally the only reader for
    trigger, compact-sidecar, and raw BOARD paths.
    """
    lexical = _safe_lexical_file_path(str(path), root=root)
    if lexical is None:
        return None
    canonical_root = root.resolve()
    try:
        relative = lexical.relative_to(canonical_root)
    except ValueError:
        return None
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd = -1
    parent_fd = -1
    descriptor = -1
    try:
        root_fd = os.open(canonical_root, directory_flags)
        if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
            return None
        parent_fd = root_fd
        for part in relative.parts[:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=parent_fd)
            if not stat.S_ISDIR(os.fstat(next_fd).st_mode):
                os.close(next_fd)
                return None
            if parent_fd != root_fd:
                os.close(parent_fd)
            parent_fd = next_fd
        descriptor = os.open(
            relative.parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            captured = handle.read()
        decoded = json.loads(captured)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    finally:
        if descriptor != -1:
            os.close(descriptor)
        if parent_fd != -1 and parent_fd != root_fd:
            os.close(parent_fd)
        if root_fd != -1:
            os.close(root_fd)
    return (lexical, captured, decoded) if isinstance(decoded, Mapping) else None


def _regular_non_symlink_trigger_path(trigger: Mapping[str, Any], *, root: Path) -> Path | None:
    return _safe_lexical_trigger_file(trigger, root=root)


def _is_execution_board_packet(
    *,
    captured_path: Path,
    packet: Mapping[str, Any],
    root: Path,
) -> bool:
    """Authenticate raw or compact BOARD origin before trusting signal labels."""
    latest = _capture_contained_json_file(root / DEFAULT_BOARD_REVIEW_PATH, root=root)
    if latest is None:
        return False
    _latest_path, latest_bytes, latest_packet = latest
    if (
        latest_packet.get("kind") != "execution_board_review"
        or latest_packet.get("schema_version") != 1
        or latest_packet.get("analysis_only") is not True
        or latest_packet.get("can_submit_orders") is not False
        or latest_packet.get("execution_authority") != "none"
    ):
        return False
    canonical = {
        "board_sha256": hashlib.sha256(latest_bytes).hexdigest(),
        "board_size_bytes": len(latest_bytes),
        # Decision validity and freshness are evaluated later by the business
        # path.  Recovery exclusion needs only immutable Board provenance.
        "decision_id": None,
    }
    # The packet's exact raw bytes are intentionally re-captured only here.
    # ``captured_path`` has already been descriptor-walked by the caller.
    captured = _capture_contained_json_file(captured_path, root=root)
    if captured is None:
        return False
    path, raw, captured_packet = captured
    if dict(captured_packet) != dict(packet):
        return False
    if _is_canonical_board_raw_packet(
        captured_path=path,
        captured_bytes=raw,
        packet=captured_packet,
        authenticated=canonical,
        root=root,
    ):
        return True
    # A byte-identical Board copied under a caller-selected recovery label is
    # still Board-origin evidence.  It cannot gain recovery authority merely
    # by being moved outside the canonical directory.
    if (
        hashlib.sha256(raw).hexdigest() == canonical["board_sha256"]
        and len(raw) == canonical["board_size_bytes"]
        and packet.get("kind") == "execution_board_review"
        and packet.get("schema_version") == 1
        and packet.get("analysis_only") is True
        and packet.get("can_submit_orders") is False
        and packet.get("execution_authority") == "none"
    ):
        return True
    return _is_canonical_board_compact_packet(
        captured_path=path,
        compact=captured_packet,
        authenticated=canonical,
        root=root,
    )


def _is_canonical_board_raw_packet(
    *,
    captured_path: Path,
    captured_bytes: bytes,
    packet: Mapping[str, Any],
    authenticated: Mapping[str, Any],
    root: Path,
) -> bool:
    """Require the canonical current Board bytes at an approved Board location."""
    board_root = _contained_canonical_path(root, DEFAULT_BOARD_EVIDENCE_ROOT / "execution_board")
    if board_root is None:
        return False
    try:
        captured_path.relative_to(board_root)
    except ValueError:
        return False
    if captured_path.name != "latest.json" and _BOARD_TIMESTAMPED_PACKET.fullmatch(captured_path.name) is None:
        return False
    return (
        len(captured_bytes) == authenticated.get("board_size_bytes")
        and hashlib.sha256(captured_bytes).hexdigest() == authenticated.get("board_sha256")
        and packet.get("kind") == "execution_board_review"
        and packet.get("schema_version") == 1
        and packet.get("analysis_only") is True
        and packet.get("can_submit_orders") is False
        and packet.get("execution_authority") == "none"
    )


def _is_canonical_board_compact_packet(
    *,
    captured_path: Path,
    compact: Mapping[str, Any],
    authenticated: Mapping[str, Any],
    root: Path,
) -> bool:
    """Authenticate a fixed compact Board sidecar against the canonical bytes."""
    board_root = _contained_canonical_path(root, DEFAULT_BOARD_EVIDENCE_ROOT / "execution_board")
    if board_root is None:
        return False
    try:
        captured_path.relative_to(board_root)
    except ValueError:
        return False
    if captured_path.name != "latest-compact.json" and not captured_path.name.endswith(".compact.json"):
        return False
    raw_path = _validated_autonomous_loss_board_sidecar_raw_path(
        compact, root=root
    )
    if raw_path is None:
        return False
    raw = _capture_contained_json_file(raw_path, root=root)
    if raw is None:
        return False
    raw_path, raw_bytes, raw_packet = raw
    return (
        _is_canonical_board_raw_packet(
            captured_path=raw_path,
            captured_bytes=raw_bytes,
            packet=raw_packet,
            authenticated=authenticated,
            root=root,
        )
    )


def _validated_autonomous_loss_board_sidecar_raw_path(
    compact: Mapping[str, Any], *, root: Path
) -> Path | None:
    """Validate the scalar-only Board sidecar before following its raw pointer."""
    required = {
        "schema",
        "generated_at",
        "raw_packet_path",
        "raw_packet_sha256",
        "symbol",
        "decision",
        "decision_id",
        "ledger_packet_id",
        "supervisor_decision_id",
        "source_revision",
        "trade_decision_resolved",
        "execution_eligible",
        "execution_blockers_sha256",
        "exit_allowed",
        "analysis_only",
        "execution_authority",
        "can_submit_orders",
        "accepted_source_count",
        "accepted_sources_sha256",
    }
    if set(compact) != required:
        return None
    symbol = compact.get("symbol")
    decision = compact.get("decision")
    decision_id = compact.get("decision_id")
    ledger_packet_id = compact.get("ledger_packet_id")
    if (
        compact.get("schema") != "autonomous_loss_board_sidecar_v1"
        or _parse_aware_recovery_time(compact.get("generated_at")) is None
        or not isinstance(symbol, str)
        or re.fullmatch(r"[A-Z][A-Z0-9.]{0,15}", symbol) is None
        or decision not in {"HOLD", "SELL"}
        or not isinstance(decision_id, str)
        or _SHA256_HEX.fullmatch(decision_id) is None
        or ledger_packet_id != build_packet_id(decision_id, "portfolio_decision")
        or not isinstance(compact.get("supervisor_decision_id"), str)
        or not compact["supervisor_decision_id"].strip()
        or not isinstance(compact.get("source_revision"), str)
        or _SOURCE_REVISION.fullmatch(compact["source_revision"]) is None
        or compact.get("trade_decision_resolved") is not True
        or not isinstance(compact.get("execution_eligible"), bool)
        or not isinstance(compact.get("execution_blockers_sha256"), str)
        or _SHA256_HEX.fullmatch(compact["execution_blockers_sha256"]) is None
        or not isinstance(compact.get("exit_allowed"), bool)
        or compact.get("execution_eligible") is not (decision == "SELL" and compact["exit_allowed"] is True)
        or (decision == "HOLD" and compact["exit_allowed"] is not False)
        or compact.get("analysis_only") is not True
        or compact.get("execution_authority") != "none"
        or compact.get("can_submit_orders") is not False
        or isinstance(compact.get("accepted_source_count"), bool)
        or not isinstance(compact.get("accepted_source_count"), int)
        or compact["accepted_source_count"] < 0
        or not isinstance(compact.get("accepted_sources_sha256"), str)
        or _SHA256_HEX.fullmatch(compact["accepted_sources_sha256"]) is None
        or not isinstance(compact.get("raw_packet_path"), str)
        or not isinstance(compact.get("raw_packet_sha256"), str)
        or _SHA256_HEX.fullmatch(compact["raw_packet_sha256"]) is None
    ):
        return None
    raw_path = _safe_lexical_file_path(compact["raw_packet_path"], root=root)
    if raw_path is None or _BOARD_TIMESTAMPED_PACKET.fullmatch(raw_path.name) is None:
        return None
    raw = _capture_contained_json_file(raw_path, root=root)
    if raw is None or hashlib.sha256(raw[1]).hexdigest() != compact["raw_packet_sha256"]:
        return None
    return raw_path


def _contained_canonical_path(root: Path, relative: Path) -> Path | None:
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _compact_trigger_raw_path(
    *,
    trigger: Mapping[str, Any],
    captured_path: Path,
    compact: Mapping[str, Any],
    root: Path,
) -> Path | None:
    """Validate one fixed compact sidecar and return its contained raw path."""
    root = root.resolve()
    label = trigger.get("label")
    if label == "hourly":
        compact_root = _contained_canonical_path(
            root, DEFAULT_BOARD_EVIDENCE_ROOT / "hourly_supervisor"
        )
        expected_schema = "compact_hourly_supervisor_v1"
        expected_kind = None
    elif label == "execution_board_review":
        compact_root = _contained_canonical_path(
            root, DEFAULT_BOARD_EVIDENCE_ROOT / "execution_board"
        )
        expected_schema = "autonomous_loss_board_sidecar_v1"
        expected_kind = None
    else:
        return None
    if compact_root is None:
        return None
    try:
        captured_path.relative_to(compact_root)
    except ValueError:
        return None
    if label == "execution_board_review":
        return _validated_autonomous_loss_board_sidecar_raw_path(compact, root=root)
    if (
        captured_path.name != "latest-compact.json"
        and not captured_path.name.endswith(".compact.json")
    ):
        return None
    if (
        compact.get("schema") != expected_schema
        or compact.get("analysis_only") is not True
        or compact.get("can_submit_orders") is not False
        or compact.get("execution_authority") != "none"
    ):
        return None
    if expected_kind is not None and compact.get("kind") != expected_kind:
        return None
    raw_value = compact.get("raw_packet_path")
    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    raw_path = _safe_lexical_file_path(raw_value, root=root)
    if raw_path is None:
        return None
    results_root = _contained_canonical_path(root, DEFAULT_BOARD_EVIDENCE_ROOT)
    if results_root is None:
        return None
    try:
        raw_path.relative_to(results_root)
    except ValueError:
        return None
    return raw_path


def _board_decision_matches_trigger(
    authenticated: Mapping[str, Any],
    trigger: Mapping[str, Any],
    *,
    root: Path,
) -> bool:
    """Bind a resolved BOARD decision to the exact signal that raised it."""
    root = root.resolve()
    symbol = trigger.get("symbol")
    if symbol is not None and (
        not isinstance(symbol, str)
        or not symbol.strip()
        or symbol.strip().upper() != authenticated.get("symbol")
    ):
        return False
    trigger_path = _regular_non_symlink_trigger_path(trigger, root=root)
    if trigger_path is None:
        return False
    label = trigger.get("label")
    if label not in {"hourly", "execution_board_review"}:
        return False
    # The canonical BOARD bytes were captured and parsed exactly once by
    # `_authenticated_latest_board_decision`; do not re-open that mutable file
    # merely to repeat the trigger check.
    if trigger_path == Path(str(authenticated.get("board_path"))).resolve():
        return label == "execution_board_review"
    captured = _captured_signal_packet(trigger, root=root)
    if captured is None:
        return False
    path, raw, packet = captured
    compact_raw_path = _compact_trigger_raw_path(
        trigger=trigger, captured_path=path, compact=packet, root=root
    )
    if compact_raw_path is not None:
        supervisor = authenticated.get("supervisor_packet")
        if not isinstance(supervisor, Mapping):
            return False
        expected_supervisor_path = _contained_canonical_path(
            root,
            DEFAULT_BOARD_EVIDENCE_ROOT / str(supervisor.get("path") or ""),
        )
        if label == "hourly" and compact_raw_path != expected_supervisor_path:
            return False
        raw_trigger = dict(trigger)
        raw_trigger["path"] = str(compact_raw_path)
        raw_captured = _captured_signal_packet(raw_trigger, root=root)
        if raw_captured is None:
            return False
        path, raw, packet = raw_captured
    elif path.name == "latest-compact.json" or path.name.endswith(".compact.json"):
        # A sidecar that failed strict schema/path validation must never fall
        # through as though it were a raw supervisor packet.
        return False
    if label == "execution_board_review":
        return _is_canonical_board_raw_packet(
            captured_path=path,
            captured_bytes=raw,
            packet=packet,
            authenticated=authenticated,
            root=root,
        )
    supervisor = authenticated.get("supervisor_packet")
    if not isinstance(supervisor, Mapping):
        return False
    expected_path = _contained_canonical_path(
        root, DEFAULT_BOARD_EVIDENCE_ROOT / str(supervisor.get("path") or "")
    )
    if expected_path is None:
        return False
    if label != "hourly":
        return False
    if path != expected_path:
        return False
    if (
        len(raw) != supervisor.get("size_bytes")
        or hashlib.sha256(raw).hexdigest() != supervisor.get("sha256")
    ):
        return False
    evidence = packet.get("evidence")
    review = evidence.get("loss_exit_review") if isinstance(evidence, Mapping) else None
    return (
        isinstance(review, Mapping)
        and review.get("symbol") == supervisor.get("symbol")
        and review.get("decision_id") == supervisor.get("decision_id")
    )


def _recovery_now(value: dt.datetime | None) -> dt.datetime:
    current = value or dt.datetime.now(tz=UTC)
    if current.tzinfo is None:
        raise ValueError("recovery time must be timezone-aware")
    return current.astimezone(UTC)


def _recovery_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8") + b"\n"


def _recovery_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _append_recovery_event(root: Path, payload: Mapping[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    line = _recovery_json(payload)
    descriptor = os.open(root / "events.jsonl", os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        if os.write(descriptor, line) != len(line):
            raise OSError("incomplete recovery event append")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _parse_aware_recovery_time(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _valid_recovery_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _canonical_absolute_path(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if not path.is_absolute() or str(path.resolve()) != value:
        return None
    return value


def _valid_recovery_record(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"path", "sha256"}
        and _canonical_absolute_path(value.get("path")) is not None
        and _valid_recovery_digest(value.get("sha256"))
    )


def _valid_persisted_recovery_state(value: Mapping[str, Any]) -> bool:
    required = {
        "schema_version",
        "incident_id",
        "bindings",
        "recovery_run_id",
        "owner_role",
        "owner_run_id",
        "attempt",
        "phase",
        "phase_outputs",
        "lease_expires_at",
        "idempotency_keys",
        "incident_history",
        "created_at",
        "last_failure",
        "last_artifact",
        "next_retry_at",
        "external_blockers",
        "incident_stage",
        "recovery_control_freeze",
    }
    canonical_binding_keys = {
        "incident_id",
        "symbol",
        "broker_account",
        "environment",
        "source_revision",
    }
    if (
        value.get("schema_version") != "tradingagents.self_heal_recovery.v2"
        or not required.issubset(value)
        or not isinstance(value.get("bindings"), Mapping)
        or set(value["bindings"]) != canonical_binding_keys
        or any(
            not isinstance(value["bindings"].get(key), str)
            or not value["bindings"][key].strip()
            for key in canonical_binding_keys
        )
        or value["bindings"].get("incident_id") != value.get("incident_id")
        or type(value.get("attempt")) is not int
        or value["attempt"] < 0
        or _parse_aware_recovery_time(value.get("lease_expires_at")) is None
        or _parse_aware_recovery_time(value.get("created_at")) is None
        or (
            value.get("next_retry_at") is not None
            and _parse_aware_recovery_time(value.get("next_retry_at")) is None
        )
        or value.get("owner_role") != "reliability_controller"
        or not isinstance(value.get("idempotency_keys"), list)
        or not isinstance(value.get("incident_history"), list)
        or not all(isinstance(item, Mapping) for item in value["incident_history"])
        or not isinstance(value.get("external_blockers"), list)
        or not all(
            isinstance(item, str) and bool(item.strip())
            for item in value["external_blockers"]
        )
        or value.get("last_failure") is not None
        and not isinstance(value.get("last_failure"), Mapping)
        or value.get("last_artifact") is not None
        and not _valid_recovery_record(value.get("last_artifact"))
        or value.get("incident_stage")
        not in {"diagnosing", "repairing", "external_blocked", "monitoring"}
    ):
        return False
    if not all(
        is_safe_incident_id(value.get(key))
        for key in ("incident_id", "recovery_run_id", "owner_run_id")
    ):
        return False
    control_freeze = value.get("recovery_control_freeze")
    if (
        not isinstance(control_freeze, Mapping)
        or set(control_freeze)
        != {
            "schema_version",
            "control_path",
            "incident_id",
            "recovery_run_id",
            "reason",
            "sha256",
        }
        or control_freeze.get("schema_version")
        != "tradingagents.recovery_control_freeze.v1"
        or _canonical_absolute_path(control_freeze.get("control_path")) is None
        or control_freeze.get("incident_id") != value.get("incident_id")
        or control_freeze.get("recovery_run_id")
        != value.get("recovery_run_id")
        or not _nonempty_recovery_string(control_freeze.get("reason"))
        or not _valid_recovery_digest(control_freeze.get("sha256"))
    ):
        return False
    if not all(
        isinstance(item, str) and is_safe_incident_id(item)
        for item in value["idempotency_keys"]
    ) or len(value["idempotency_keys"]) != len(set(value["idempotency_keys"])):
        return False
    persisted_verifier = value.get("verifier_run_id")
    if persisted_verifier is not None and not is_safe_incident_id(
        persisted_verifier
    ):
        return False
    last_failure = value.get("last_failure")
    if last_failure is not None and (
        set(last_failure) != {"kind", "detail", "external"}
        or last_failure.get("kind")
        not in {
            "transient",
            "transient_exhausted",
            "permanent_integrity",
            "forbidden_effect",
            "external_blocked",
        }
        or not isinstance(last_failure.get("detail"), str)
        or not last_failure["detail"].strip()
        or type(last_failure.get("external")) is not bool
    ):
        return False

    outputs = value.get("phase_outputs")
    if not isinstance(outputs, Mapping) or not all(
        isinstance(key, str) and _valid_recovery_record(record)
        for key, record in outputs.items()
    ):
        return False
    completed_count = len(outputs)
    if completed_count > len(RECOVERY_PHASES):
        return False
    completed_prefix = RECOVERY_PHASES[:completed_count]
    if set(outputs) != set(completed_prefix):
        return False
    phase = value.get("phase")
    if completed_count == len(RECOVERY_PHASES):
        if phase != "monitoring":
            return False
    elif phase != RECOVERY_PHASES[completed_count]:
        return False
    if completed_prefix:
        if value.get("last_artifact") != outputs[completed_prefix[-1]]:
            return False
    elif value.get("last_artifact") is not None:
        return False

    follow_on_count = value.get("follow_on_count", 0)
    follow_on_required = value.get("follow_on_required", False)
    follow_on_not_before = value.get("follow_on_not_before")
    parent_run = value.get("parent_recovery_run_id")
    if (
        type(follow_on_count) is not int
        or follow_on_count < 0
        or type(follow_on_required) is not bool
        or parent_run is not None
        and not is_safe_incident_id(parent_run)
    ):
        return False
    if follow_on_required:
        if (
            _parse_aware_recovery_time(follow_on_not_before) is None
            or not isinstance(value.get("last_failure"), Mapping)
            or value["last_failure"].get("kind") != "transient_exhausted"
        ):
            return False
    elif follow_on_not_before is not None:
        return False
    if parent_run is not None and "follow_on_count" not in value:
        return False

    legacy_path = value.get("legacy_v1_state_path")
    legacy_digest = value.get("legacy_v1_state_sha256")
    if (legacy_path is None) != (legacy_digest is None):
        return False
    if legacy_path is not None:
        canonical_legacy_path = _canonical_absolute_path(legacy_path)
        if (
            canonical_legacy_path is None
            or not _valid_recovery_digest(legacy_digest)
            or Path(canonical_legacy_path).name
            != f"state-v1-{legacy_digest}.json"
            or Path(canonical_legacy_path).parent.name
            != value.get("incident_id")
            or parent_run is None
            or follow_on_count < 1
            or not any(
                event.get("event") == "legacy_v1_migrated"
                and event.get("legacy_v1_state_path") == canonical_legacy_path
                and event.get("legacy_v1_state_sha256") == legacy_digest
                for event in value["incident_history"]
            )
        ):
            return False
        try:
            if _recovery_digest(Path(canonical_legacy_path)) != legacy_digest:
                return False
        except OSError:
            return False

    stage_request = value.get("promotion_stage_request")
    stage_request_keys = {
        "commit_id",
        "prepare_path",
        "prepare_sha256",
        "stage_path",
        "expected_raw_stage_sha256",
        "expected_stage_sha256",
        "generated_at",
        "canonical_path",
        "canonical_before_sha256",
        "report_sha256",
        "envelope_sha256",
        "focused_sha256",
        "reconciliation_sha256",
        "arm_live",
        "ci_green",
    }
    stage_request_digest_fields = {
        "commit_id",
        "prepare_sha256",
        "expected_raw_stage_sha256",
        "expected_stage_sha256",
        "canonical_before_sha256",
        "report_sha256",
        "envelope_sha256",
        "focused_sha256",
        "reconciliation_sha256",
    }
    if stage_request is not None and (
        not isinstance(stage_request, Mapping)
        or set(stage_request) != stage_request_keys
        or any(
            not _valid_recovery_digest(stage_request.get(field))
            for field in stage_request_digest_fields
        )
        or _canonical_absolute_path(stage_request.get("prepare_path")) is None
        or _canonical_absolute_path(stage_request.get("stage_path")) is None
        or _canonical_absolute_path(stage_request.get("canonical_path")) is None
        or _parse_aware_recovery_time(stage_request.get("generated_at")) is None
        or stage_request.get("arm_live") is not True
        or stage_request.get("ci_green") is not True
    ):
        return False

    promotion_intent = value.get("promotion_commit_intent")
    if promotion_intent is not None and (
        not isinstance(promotion_intent, Mapping)
        or set(promotion_intent)
        != {
            "commit_id",
            "prepare_path",
            "prepare_sha256",
            "staged_path",
            "staged_sha256",
            "canonical_path",
            "canonical_before_sha256",
        }
        or not _valid_recovery_digest(promotion_intent.get("commit_id"))
        or _canonical_absolute_path(promotion_intent.get("prepare_path")) is None
        or not _valid_recovery_digest(promotion_intent.get("prepare_sha256"))
        or _canonical_absolute_path(promotion_intent.get("staged_path")) is None
        or not _valid_recovery_digest(promotion_intent.get("staged_sha256"))
        or _canonical_absolute_path(promotion_intent.get("canonical_path")) is None
        or not _valid_recovery_digest(
            promotion_intent.get("canonical_before_sha256")
        )
    ):
        return False
    if "sync_promotion" in outputs and not isinstance(stage_request, Mapping):
        return False

    intent = value.get("rearm_intent")
    if intent is None:
        return True
    intent_keys = {
        "incident_id",
        "manifest_path",
        "manifest_sha256",
        "control_path",
        "idempotency_key",
        "source_packet_paths",
        "source_packet_sha256",
        "repairer_run_id",
        "verifier_run_id",
        "control_preimage_sha256",
    }
    proof_keys = {"incident", "reconciliation", "promotion", "focused"}
    if (
        not isinstance(intent, Mapping)
        or set(intent) != intent_keys
        or intent.get("incident_id") != value.get("incident_id")
        or _canonical_absolute_path(intent.get("manifest_path")) is None
        or _valid_recovery_digest(intent.get("manifest_sha256")) is False
        or _canonical_absolute_path(intent.get("control_path")) is None
        or intent.get("control_preimage_sha256")
        != control_freeze.get("sha256")
        or (
            intent.get("idempotency_key") is not None
            and not is_safe_incident_id(intent.get("idempotency_key"))
        )
        or not is_safe_incident_id(intent.get("repairer_run_id"))
        or not is_safe_incident_id(intent.get("verifier_run_id"))
        or intent.get("repairer_run_id").casefold()
        == intent.get("verifier_run_id").casefold()
        or (
            persisted_verifier is not None
            and intent.get("verifier_run_id") != persisted_verifier
        )
        or not isinstance(intent.get("source_packet_paths"), Mapping)
        or not isinstance(intent.get("source_packet_sha256"), Mapping)
        or set(intent["source_packet_paths"]) != proof_keys
        or set(intent["source_packet_sha256"]) != proof_keys
        or any(
            _canonical_absolute_path(intent["source_packet_paths"].get(key)) is None
            for key in proof_keys
        )
        or any(
            not _valid_recovery_digest(intent["source_packet_sha256"].get(key))
            for key in proof_keys
        )
    ):
        return False
    source_phases = {
        "incident": "ready_incident",
        "reconciliation": "reconcile",
        "promotion": "sync_promotion",
        "focused": "focused_verify",
    }
    if not all(phase_name in outputs for phase_name in (*source_phases.values(), "manifest")):
        return False
    return not (
        intent["manifest_path"] != outputs["manifest"]["path"]
        or intent["manifest_sha256"] != outputs["manifest"]["sha256"]
        or any(
            intent["source_packet_paths"][key] != outputs[phase_name]["path"]
            or intent["source_packet_sha256"][key] != outputs[phase_name]["sha256"]
            for key, phase_name in source_phases.items()
        )
    )


def _read_recovery_state(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "corrupt_state"
    if not isinstance(value, dict):
        return None, "corrupt_state"
    if (
        value.get("schema_version")
        == "tradingagents.self_heal_recovery.v1"
    ):
        return value, "legacy_v1"
    try:
        valid = _valid_persisted_recovery_state(value)
    except Exception:
        valid = False
    if not valid:
        return None, "corrupt_state"
    return value, None


def _write_recovery_state(path: Path, state: Mapping[str, Any]) -> None:
    atomic_write_text(path, json.dumps(state, indent=2, sort_keys=True))


def _write_immutable_recovery_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ValueError(
                "immutable legacy recovery archive already differs"
            ) from None
        return
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("incomplete legacy recovery archive write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent_descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)


def _recovery_lock(
    path: Path, *, incident_id: str, owner_run_id: str, lease_expires_at: str, now: dt.datetime
) -> tuple[int | None, str, str | None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    metadata = {"schema_version": "tradingagents.recovery_lock.v1", "incident_id": incident_id, "owner_run_id": owner_run_id, "lease_expires_at": lease_expires_at, "token": token}
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            return None, "owner_busy", None

        os.lseek(descriptor, 0, os.SEEK_SET)
        existing_raw = os.read(descriptor, 1_048_577)
        if len(existing_raw) > 1_048_576:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            return None, "corrupt_lock", None

        took_over = False
        if existing_raw:
            try:
                existing = json.loads(existing_raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
                return None, "corrupt_lock", None
            if (
                not isinstance(existing, dict)
                or existing.get("schema_version")
                != "tradingagents.recovery_lock.v1"
                or existing.get("incident_id") != incident_id
                or not is_safe_incident_id(existing.get("owner_run_id"))
                or not isinstance(existing.get("token"), str)
                or not existing["token"]
            ):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
                return None, "corrupt_lock", None
            expiry = _parse_datetime(existing.get("lease_expires_at"))
            if expiry is None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
                return None, "corrupt_lock", None
            if expiry > now:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
                return None, "owner_busy", None
            stale_path = path.with_name(
                ".owner.stale-"
                + hashlib.sha256(existing_raw).hexdigest()[:12]
            )
            _write_immutable_recovery_bytes(stale_path, existing_raw)
            took_over = True

        encoded = _recovery_json(metadata)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        offset = 0
        while offset < len(encoded):
            written = os.write(descriptor, encoded[offset:])
            if written <= 0:
                raise OSError("incomplete recovery lock write")
            offset += written
        os.fsync(descriptor)
        return descriptor, "stale_takeover" if took_over else "acquired", token
    except Exception:
        with suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        with suppress(OSError):
            os.close(descriptor)
        raise


def _release_recovery_lock(path: Path, descriptor: int, token: str | None) -> None:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw = os.read(descriptor, 1_048_577)
        try:
            current = json.loads(raw) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            current = None
        if isinstance(current, dict) and current.get("token") == token:
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.ftruncate(descriptor, 0)
            os.fsync(descriptor)
    finally:
        with suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _recovery_failure(kind: str, detail: str, *, external: bool = False) -> dict[str, Any]:
    return {"kind": kind, "detail": _redact_recovery_detail(detail)[:500], "external": external}


def _redact_recovery_detail(value: object) -> str:
    text = str(value)
    text = re.sub(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", text)
    text = re.sub(r"(?i)authorization:\s*bearer\s+[^\s,;]+", "Authorization: Bearer [REDACTED]", text)
    text = re.sub(r"(?i)\bbearer\s+[^\s,;]+", "Bearer [REDACTED]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]+", "sk-[REDACTED]", text)
    text = re.sub(r"(?i)(https?://[^\s/@:]+:)[^@\s]+@", r"\1[REDACTED]@", text)
    return re.sub(r"(?i)([?&](?:api[_-]?key|token|password|secret)=)[^&\s]+", r"\1[REDACTED]", text)


def _phase_path(run_root: Path, phase: str) -> Path:
    return run_root / "packets" / f"{phase}.json"


def _phase_record(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _recovery_digest(path)}


def _valid_phase_record(record: object) -> bool:
    if not _valid_recovery_record(record):
        return False
    try:
        assert isinstance(record, Mapping)
        return _recovery_digest(Path(str(record["path"]))) == record["sha256"]
    except OSError:
        return False


def _packet_string_list(value: object, *, nonempty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (not nonempty or bool(value))
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def _expected_source_records(
    phase_outputs: Mapping[str, object],
) -> dict[str, Mapping[str, Any]] | None:
    source_phases = {
        "incident": "ready_incident",
        "reconciliation": "reconcile",
        "promotion": "sync_promotion",
        "focused": "focused_verify",
    }
    records: dict[str, Mapping[str, Any]] = {}
    for name, phase_name in source_phases.items():
        record = phase_outputs.get(phase_name)
        if not _valid_recovery_record(record):
            return None
        assert isinstance(record, Mapping)
        records[name] = record
    return records


def _rearm_intent_matches_current(
    state: Mapping[str, Any],
    *,
    control_path: str | Path,
    idempotency_key: str | None,
) -> bool:
    intent = state.get("rearm_intent")
    if not isinstance(intent, Mapping):
        return False
    return (
        intent.get("incident_id") == state.get("incident_id")
        and intent.get("control_path") == str(Path(control_path).resolve())
        and intent.get("control_preimage_sha256")
        == state.get("recovery_control_freeze", {}).get("sha256")
        and intent.get("idempotency_key") == idempotency_key
        and intent.get("manifest_path")
        == state.get("phase_outputs", {}).get("manifest", {}).get("path")
        and intent.get("manifest_sha256")
        == state.get("phase_outputs", {}).get("manifest", {}).get("sha256")
    )


def _active_rearm_matches_intent(
    state: Mapping[str, Any],
    *,
    control_path: str | Path,
    now: dt.datetime,
    idempotency_key: str | None,
    packet: Mapping[str, Any] | None = None,
) -> bool:
    if not _rearm_intent_matches_current(
        state, control_path=control_path, idempotency_key=idempotency_key
    ):
        return False
    intent = state["rearm_intent"]
    assert isinstance(intent, Mapping)
    control_state, control_issues = load_live_control_state(control_path, now=now)
    if (
        control_state is None
        or control_issues
        or control_state.get("frozen") is not False
        or control_state.get("recovery_incident_id") != state.get("incident_id")
    ):
        return False
    receipt_path = control_state.get("recovery_receipt_path")
    receipt_digest = control_state.get("recovery_receipt_sha256")
    if (
        _canonical_absolute_path(receipt_path) is None
        or not _valid_recovery_digest(receipt_digest)
    ):
        return False
    if packet is not None and (
        packet.get("receipt_path") != receipt_path
        or packet.get("receipt_sha256") != receipt_digest
    ):
        return False
    try:
        receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(receipt, Mapping):
        return False
    focused_record = state.get("phase_outputs", {}).get("focused_verify")
    ready_record = state.get("phase_outputs", {}).get("ready_incident")
    if not _valid_recovery_record(focused_record) or not _valid_recovery_record(
        ready_record
    ):
        return False
    try:
        focused = json.loads(Path(str(focused_record["path"])).read_text(encoding="utf-8"))
        ready = json.loads(Path(str(ready_record["path"])).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return False
    if (
        not isinstance(focused, Mapping)
        or not isinstance(ready, Mapping)
        or intent.get("repairer_run_id") != ready.get("repairer_run_id")
        or intent.get("verifier_run_id") != focused.get("verifier_run_id")
    ):
        return False
    expected_receipt = {
        "incident_id": intent.get("incident_id"),
        "repairer_run_id": intent.get("repairer_run_id"),
        "verifier_run_id": intent.get("verifier_run_id"),
        "repairer_role_id": ready.get("repairer_role_id"),
        "verifier_role_id": focused.get("verifier_role_id"),
        "source_bindings": state.get("bindings"),
        "source_packet_paths": intent.get("source_packet_paths"),
        "source_packet_sha256": intent.get("source_packet_sha256"),
        "recovery_manifest_path": intent.get("manifest_path"),
        "recovery_manifest_sha256": intent.get("manifest_sha256"),
    }
    if any(receipt.get(key) != value for key, value in expected_receipt.items()):
        return False
    if (
        receipt.get("control_preimage_sha256")
        != intent.get("control_preimage_sha256")
    ):
        return False
    # Task 5 receipts predate coordinator idempotency. If a future receipt
    # carries the key, it must agree; otherwise the persisted intent remains
    # the authoritative binding to the current delivery.
    return (
        "idempotency_key" not in receipt
        or receipt.get("idempotency_key") == idempotency_key
    )


def _freeze_recovery_control(control_path: str | Path, *, reason: str) -> None:
    write_live_control_state(
        control_path,
        frozen=True,
        reason=f"verified recovery frozen: {_redact_recovery_detail(reason)[:180]}",
    )


def _preserve_frozen_or_close_recovery_control(
    control_path: str | Path,
    *,
    reason: str,
    now: dt.datetime,
    state: Mapping[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> str:
    """Preserve a safety freeze or close every non-exact recovery control."""

    control_absolute = Path(control_path).resolve()
    with live_control_lock(control_absolute):
        try:
            current = json.loads(control_absolute.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            current = None
        if isinstance(current, Mapping) and current.get("frozen") is True:
            return "preserved_frozen"
        if state is not None and _active_rearm_matches_intent(
            state,
            control_path=control_absolute,
            now=now,
            idempotency_key=idempotency_key,
        ):
            return "preserved_exact_active_rearm"
        _write_live_control_state_locked(
            control_absolute,
            frozen=True,
            reason=(
                "verified recovery frozen: "
                + _redact_recovery_detail(reason)[:180]
            ),
            dead_man_expires_at=now + dt.timedelta(hours=6),
            now=now,
        )
        return "closed"


def _establish_recovery_control_freeze(
    control_path: str | Path,
    *,
    incident_id: str,
    recovery_run_id: str,
    now: dt.datetime,
) -> dict[str, str]:
    control_absolute = Path(control_path).resolve()
    reason = (
        f"verified recovery {incident_id} run {recovery_run_id} "
        "is in progress"
    )
    with live_control_lock(control_absolute):
        written = _write_live_control_state_locked(
            control_absolute,
            frozen=True,
            reason=reason,
            dead_man_expires_at=now + dt.timedelta(hours=6),
            now=now,
        )
        digest = hashlib.sha256(written.read_bytes()).hexdigest()
    return {
        "schema_version": "tradingagents.recovery_control_freeze.v1",
        "control_path": str(control_absolute),
        "incident_id": incident_id,
        "recovery_run_id": recovery_run_id,
        "reason": reason,
        "sha256": digest,
    }


def _assert_recovery_control_frozen(
    state: Mapping[str, Any],
    *,
    control_path: str | Path,
    now: dt.datetime,
) -> None:
    binding = state.get("recovery_control_freeze")
    control_absolute = Path(control_path).resolve()
    if (
        not isinstance(binding, Mapping)
        or binding.get("control_path") != str(control_absolute)
        or binding.get("incident_id") != state.get("incident_id")
        or binding.get("recovery_run_id") != state.get("recovery_run_id")
        or not _valid_recovery_digest(binding.get("sha256"))
    ):
        raise ValueError("recovery control freeze binding is invalid")
    with live_control_lock(control_absolute):
        try:
            raw = control_absolute.read_bytes()
            control = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            control = None
            raw = b""
        digest = hashlib.sha256(raw).hexdigest()
        if (
            isinstance(control, Mapping)
            and control.get("frozen") is True
            and control.get("reason") == binding.get("reason")
            and digest == binding.get("sha256")
        ):
            return
        if not isinstance(control, Mapping) or control.get("frozen") is not True:
            _write_live_control_state_locked(
                control_absolute,
                frozen=True,
                reason=(
                    "verified recovery frozen: control changed outside the "
                    "recovery-owned safety boundary"
                ),
                dead_man_expires_at=now + dt.timedelta(hours=6),
                now=now,
            )
        raise ValueError(
            "recovery control changed after its frozen preimage was accepted"
        )


def _nonempty_recovery_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _finite_recovery_decimal(
    value: object, *, positive: bool = False, nonnegative: bool = False
) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    if positive and parsed <= 0:
        return None
    if nonnegative and parsed < 0:
        return None
    return parsed


def _valid_preserved_policy_authority(
    *,
    packet: Mapping[str, Any],
    payload: Mapping[str, Any],
    supervisor: Mapping[str, Any],
    advisory: Mapping[str, Any],
    symbol: str,
) -> bool:
    candidate = advisory.get("loss_exit_candidate")
    verdict = resolve_exit_authority(
        supervisor_review=supervisor,
        advisory_analysis=advisory,
    )
    forbidden_effects = [
        "create_trade_intent",
        "size_position",
        "submit_order",
        "promote_sleeve",
        "waive_live_gate",
        "mark_loss_exit_allowed",
    ]
    return (
        supervisor.get("symbol") == symbol
        and _nonempty_recovery_string(supervisor.get("decision_id"))
        and supervisor.get("allowed") is True
        and supervisor.get("policy_rule_exit") is True
        and _nonempty_recovery_string(supervisor.get("allowed_exit_reason"))
        and _nonempty_recovery_string(
            supervisor.get("allowed_exit_reason_source")
        )
        and _nonempty_recovery_string(supervisor.get("exit_policy_rule"))
        and _nonempty_recovery_string(supervisor.get("exit_policy_rationale"))
        and supervisor.get("blockers") == []
        and supervisor.get("blocked_reasons") == []
        and _packet_string_list(supervisor.get("source_packet_ids"))
        and supervisor.get("source_identity")
        == "hourly_supervisor.loss_exit_review"
        and supervisor.get("requires_additional_decision") in (None, False)
        and verdict.allowed is True
        and verdict.authority_source == "pre_registered_policy_rule"
        and verdict.requires_additional_decision is False
        and verdict.decision_owner == "execution_operator"
        and advisory.get("symbol") == symbol
        and advisory.get("review_allowed_after_refresh") is True
        and advisory.get("authority_source") == verdict.authority_source
        and advisory.get("requires_board_decision") is False
        and advisory.get("requires_additional_decision") in (None, False)
        and advisory.get("decision_owner") == verdict.decision_owner
        and advisory.get("forbidden_effects") == forbidden_effects
        and isinstance(candidate, Mapping)
        and candidate.get("allowed_exit_reason_candidate")
        == supervisor.get("allowed_exit_reason")
        and candidate.get("allowed_exit_reason_source")
        == supervisor.get("allowed_exit_reason_source")
        and candidate.get("confidence") is None
        and candidate.get("confidence_tier") == "pre_registered_policy"
        and _nonempty_recovery_string(candidate.get("reason_summary"))
        and _packet_string_list(candidate.get("drivers"), nonempty=True)
        and candidate.get("approval_effect")
        == "preserves_pre_registered_policy_approval"
        and candidate.get("requires_board_decision") is False
        and candidate.get("requires_tradeable_session") is True
        and candidate.get("can_submit_orders") is False
        and payload.get("review_allowed") is True
        and payload.get("next_action")
        == "pre_registered_policy_approval_preserved"
        and packet.get("review_allowed") is True
        and packet.get("next_action")
        == "pre_registered_policy_approval_preserved"
    )


def _valid_loss_review_phase_packet(
    packet: Mapping[str, Any], bindings: Mapping[str, str]
) -> bool:
    symbol = bindings["symbol"]
    payload = packet.get("payload")
    entry_context = payload.get("entry_context") if isinstance(payload, Mapping) else None
    supervisor = (
        payload.get("supervisor_review_authority")
        if isinstance(payload, Mapping)
        else None
    )
    advisory = (
        payload.get("advisory_analysis") if isinstance(payload, Mapping) else None
    )
    freshness = packet.get("freshness")
    sources = packet.get("sources")
    input_hashes = packet.get("input_hashes")
    source_packet_paths = packet.get("source_packet_paths")
    source_refs = packet.get("source_refs")
    summary_packet_path = packet.get("summary_packet_path")
    return (
        packet.get("schema_version") == "tradingagents.recovery_phase.v1"
        and packet.get("source_schema_version") == "1.0.0"
        and packet.get("kind") == "loss_review_evidence"
        and packet.get("source_identity") == "loss_review_evidence"
        and packet.get("source_name") == "loss_review_evidence"
        and packet.get("evidence_type") == "loss_review_evidence"
        and packet.get("subject") == symbol
        and packet.get("symbol") == symbol
        and _nonempty_recovery_string(packet.get("packet_id"))
        and packet.get("tool_route") == "local_loss_review_evidence"
        and packet.get("redaction_status") == "no_secrets_seen"
        and packet.get("analysis_only") is True
        and packet.get("can_submit_orders") is False
        and packet.get("execution_authority") == "none"
        and _nonempty_recovery_string(packet.get("packet_path"))
        and _nonempty_recovery_string(packet.get("hourly_packet_path"))
        and _packet_string_list(source_refs, nonempty=True)
        and len(source_refs) == 1
        and isinstance(sources, list)
        and len(sources) == 1
        and all(
            isinstance(source, Mapping)
            and source.get("schema_version") == "1.0.0"
            and source.get("source") == "loss_review_evidence"
            and _parse_aware_recovery_time(source.get("as_of")) is not None
            and _nonempty_recovery_string(source.get("path"))
            and source.get("path") in source_refs
            and source.get("quality") in {"high", "medium", "low", "unknown"}
            for source in sources
        )
        and isinstance(input_hashes, Mapping)
        and set(input_hashes) == {"request"}
        and _valid_recovery_digest(input_hashes.get("request"))
        and isinstance(freshness, Mapping)
        and _parse_aware_recovery_time(freshness.get("as_of")) is not None
        and freshness.get("stale") is False
        and freshness.get("read_only") is True
        and freshness.get("can_submit_orders") is False
        and type(freshness.get("source_packet_count")) is int
        and freshness.get("source_packet_count") >= 0
        and isinstance(source_packet_paths, Mapping)
        and all(
            _nonempty_recovery_string(key)
            and _nonempty_recovery_string(value)
            for key, value in source_packet_paths.items()
        )
        and type(packet.get("source_packet_count")) is int
        and packet.get("source_packet_count") == len(source_packet_paths)
        and freshness.get("source_packet_count")
        == packet.get("source_packet_count")
        + (1 if _nonempty_recovery_string(summary_packet_path) else 0)
        and (
            summary_packet_path is None
            or _nonempty_recovery_string(summary_packet_path)
        )
        and isinstance(payload, Mapping)
        and payload.get("symbol") == symbol
        and payload.get("analysis_only") is True
        and payload.get("execution_authority") == "none"
        and payload.get("forbidden_effects")
        == [
            "create_trade_intent",
            "size_position",
            "submit_order",
            "promote_sleeve",
            "waive_live_gate",
            "mark_loss_exit_allowed",
        ]
        and payload.get("hourly_packet_path") == packet.get("hourly_packet_path")
        and isinstance(entry_context, Mapping)
        and entry_context.get("symbol") == symbol
        and entry_context.get("account") == bindings["broker_account"]
        and isinstance(supervisor, Mapping)
        and supervisor.get("symbol") == symbol
        and isinstance(advisory, Mapping)
        and advisory.get("symbol") == symbol
        and packet.get("entry_context") == entry_context
        and _valid_preserved_policy_authority(
            packet=packet,
            payload=payload,
            supervisor=supervisor,
            advisory=advisory,
            symbol=symbol,
        )
    )


def _valid_promotion_phase_packet(
    path: Path,
    packet: Mapping[str, Any],
    bindings: Mapping[str, str],
    *,
    state: Mapping[str, Any],
    phase_outputs: Mapping[str, object],
) -> bool:
    issues_by_sleeve = packet.get("issues_by_sleeve")
    promotion_state = packet.get("state")
    source = (
        promotion_state.get("source")
        if isinstance(promotion_state, Mapping)
        else None
    )
    sleeves = (
        promotion_state.get("sleeves")
        if isinstance(promotion_state, Mapping)
        else None
    )
    promoted = packet.get("promoted")
    demoted = packet.get("demoted")
    focused_record = phase_outputs.get("focused_verify")
    reconciliation_record = phase_outputs.get("reconcile")
    prepare_record = packet.get("promotion_prepare")
    receipt_record = packet.get("promotion_commit")
    recovery_commit = packet.get("recovery_commit")
    intent = packet.get("promotion_commit_intent")
    stage_request = packet.get("promotion_stage_request")
    recovery_commit_keys = {
        "schema_version",
        "commit_id",
        "incident_id",
        "recovery_run_id",
        "source_revision",
        "focused_path",
        "focused_sha256",
        "verifier_run_id",
        "verifier_role_id",
        "reconciliation_path",
        "reconciliation_sha256",
        "report_path",
        "report_sha256",
        "envelope_path",
        "envelope_sha256",
        "canonical_path",
        "canonical_before_sha256",
        "candidate_payload_sha256",
    }
    if (
        not isinstance(recovery_commit, Mapping)
        or set(recovery_commit) != recovery_commit_keys
    ):
        return False
    try:
        if not all(
            _valid_phase_record(record)
            for record in (
                focused_record,
                reconciliation_record,
                prepare_record,
                receipt_record,
            )
        ):
            return False
        focused_path = Path(str(focused_record["path"])).resolve()
        reconciliation_path = Path(str(reconciliation_record["path"])).resolve()
        prepare_path = Path(str(prepare_record["path"])).resolve()
        receipt_path = Path(str(receipt_record["path"])).resolve()
        staged_path = Path(str(packet.get("staged_state_path"))).resolve()
        canonical_path = Path(str(packet.get("state_path"))).resolve()
        if (
            prepare_path != path.parent / "promotion_prepare.json"
            or receipt_path != path.parent / "promotion_commit.json"
            or staged_path != path.parent.parent / "staging" / "promotion_state.json"
            or any(
                _recovery_digest(record_path) != record["sha256"]
                for record_path, record in (
                    (focused_path, focused_record),
                    (reconciliation_path, reconciliation_record),
                    (prepare_path, prepare_record),
                    (receipt_path, receipt_record),
                )
            )
            or _recovery_digest(staged_path) != packet.get("staged_state_sha256")
            or _recovery_digest(canonical_path)
            != packet.get("canonical_after_sha256")
            or staged_path.read_bytes() != canonical_path.read_bytes()
        ):
            return False
        focused = json.loads(focused_path.read_text(encoding="utf-8"))
        reconciliation = json.loads(
            reconciliation_path.read_text(encoding="utf-8")
        )
        staged_state = json.loads(staged_path.read_text(encoding="utf-8"))
        prepare = json.loads(prepare_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        report_path = Path(str(recovery_commit.get("report_path"))).resolve()
        envelope_path = Path(str(recovery_commit.get("envelope_path"))).resolve()
        report_sha256 = _recovery_digest(report_path)
        envelope_sha256 = _recovery_digest(envelope_path)
        report_packet = json.loads(report_path.read_text(encoding="utf-8"))
        report_payload = (
            report_packet.get("latest_report")
            if isinstance(report_packet.get("latest_report"), Mapping)
            else report_packet
        )
        candidate = (
            report_payload.get("live_strategy_candidate")
            if isinstance(report_payload, Mapping)
            else {}
        )
        if not isinstance(candidate, Mapping):
            candidate = {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    commit_seed = dict(recovery_commit)
    commit_id = commit_seed.pop("commit_id")
    expected_intent = {
        "commit_id": commit_id,
        "prepare_path": prepare_record["path"],
        "prepare_sha256": prepare_record["sha256"],
        "staged_path": str(staged_path),
        "staged_sha256": packet.get("staged_state_sha256"),
        "canonical_path": str(canonical_path),
        "canonical_before_sha256": recovery_commit.get(
            "canonical_before_sha256"
        ),
    }
    expected_prepare = {
        "schema_version": "tradingagents.promotion_prepare.v1",
        "kind": "promotion_commit_prepare",
        "recovery_commit": dict(recovery_commit),
        "stage_path": str(staged_path),
        "generated_at": staged_state.get("generated_at"),
        "arm_live": True,
        "ci_green": True,
        "expected_raw_stage_sha256": prepare.get(
            "expected_raw_stage_sha256"
        ),
        "expected_stage_sha256": packet.get("staged_state_sha256"),
        "can_submit_orders": False,
        "execution_authority": "none",
    }
    expected_stage_request = {
        "commit_id": commit_id,
        "prepare_path": prepare_record["path"],
        "prepare_sha256": prepare_record["sha256"],
        "stage_path": str(staged_path),
        "expected_raw_stage_sha256": prepare.get(
            "expected_raw_stage_sha256"
        ),
        "expected_stage_sha256": packet.get("staged_state_sha256"),
        "generated_at": staged_state.get("generated_at"),
        "canonical_path": str(canonical_path),
        "canonical_before_sha256": recovery_commit.get(
            "canonical_before_sha256"
        ),
        "report_sha256": recovery_commit.get("report_sha256"),
        "envelope_sha256": recovery_commit.get("envelope_sha256"),
        "focused_sha256": recovery_commit.get("focused_sha256"),
        "reconciliation_sha256": recovery_commit.get(
            "reconciliation_sha256"
        ),
        "arm_live": True,
        "ci_green": True,
    }
    receipt_expected = {
        "schema_version": "tradingagents.promotion_commit.v1",
        "kind": "verified_promotion_commit",
        "recovery_commit": dict(recovery_commit),
        "prepare_path": prepare_record["path"],
        "prepare_sha256": prepare_record["sha256"],
        "staged_path": str(staged_path),
        "staged_sha256": packet.get("staged_state_sha256"),
        "canonical_path": str(canonical_path),
        "canonical_before_sha256": recovery_commit.get(
            "canonical_before_sha256"
        ),
        "canonical_after_sha256": packet.get("canonical_after_sha256"),
        "can_submit_orders": False,
        "execution_authority": "none",
    }
    return (
        packet.get("schema_version") == "tradingagents.recovery_phase.v1"
        and packet.get("source_schema_version") == "1.1.0"
        and packet.get("kind") == "promotion_state_sync"
        and packet.get("source_identity") == "paper_tournament_sync"
        and packet.get("symbol") == bindings["symbol"]
        and packet.get("promotion_evidence_fresh") is True
        and packet.get("issues") == []
        and isinstance(issues_by_sleeve, Mapping)
        and all(
            _nonempty_recovery_string(sleeve_id)
            and isinstance(issues, list)
            and not issues
            for sleeve_id, issues in issues_by_sleeve.items()
        )
        and _packet_string_list(promoted)
        and _packet_string_list(demoted)
        and not set(promoted).intersection(demoted)
        and _nonempty_recovery_string(packet.get("state_path"))
        and _nonempty_recovery_string(packet.get("report_path"))
        and packet.get("canonical_state_path") == packet.get("state_path")
        and packet.get("arm_live") is True
        and packet.get("ci_green") is True
        and packet.get("can_submit_orders") is False
        and packet.get("execution_authority") == "none"
        and isinstance(promotion_state, Mapping)
        and promotion_state == staged_state
        and promotion_state.get("schema_version")
        == packet.get("source_schema_version")
        and _parse_aware_recovery_time(promotion_state.get("generated_at"))
        is not None
        and isinstance(sleeves, Mapping)
        and all(
            _nonempty_recovery_string(sleeve_id)
            and isinstance(record, Mapping)
            and _valid_promotion_sleeve_record(
                record,
                symbol=bindings["symbol"],
            )
            for sleeve_id, record in sleeves.items()
        )
        and set(promoted).issubset(sleeves)
        and set(demoted).issubset(sleeves)
        and set(issues_by_sleeve).issubset(sleeves)
        and all(
            sleeves[sleeve_id].get("stage") == "tiny_live_eligible"
            and sleeves[sleeve_id].get("live_enabled") is True
            for sleeve_id in promoted
        )
        and all(
            sleeves[sleeve_id].get("stage") == "paper_only"
            and sleeves[sleeve_id].get("live_enabled") is False
            for sleeve_id in demoted
        )
        and isinstance(source, Mapping)
        and source.get("kind") == "paper_tournament_sync"
        and source.get("arm_live") is True
        and source.get("ci_green") is True
        and source.get("canonical_input_sha256")
        == recovery_commit.get("canonical_before_sha256")
        and source.get("recovery_commit") == recovery_commit
        and _nonempty_recovery_string(source.get("tournament_id"))
        and _parse_aware_recovery_time(source.get("report_generated_at")) is not None
        and commit_id == hashlib.sha256(_recovery_json(commit_seed)).hexdigest()
        and recovery_commit.get("schema_version")
        == "tradingagents.promotion_recovery_commit.v1"
        and recovery_commit.get("incident_id") == bindings["incident_id"]
        and recovery_commit.get("recovery_run_id") == state.get("recovery_run_id")
        and recovery_commit.get("source_revision") == bindings["source_revision"]
        and recovery_commit.get("focused_path") == str(focused_path)
        and recovery_commit.get("focused_sha256") == focused_record["sha256"]
        and _valid_phase_packet(
            focused_path,
            "focused_verify",
            bindings,
            state=state,
            phase_outputs=phase_outputs,
        )
        and recovery_commit.get("verifier_run_id")
        == focused.get("verifier_run_id")
        and recovery_commit.get("verifier_role_id")
        == focused.get("verifier_role_id")
        and focused.get("passing_tests") == list(RECOVERY_FOCUSED_TESTS)
        and recovery_commit.get("reconciliation_path")
        == str(reconciliation_path)
        and recovery_commit.get("reconciliation_sha256")
        == reconciliation_record["sha256"]
        and _valid_phase_packet(
            reconciliation_path,
            "reconcile",
            bindings,
            state=state,
            phase_outputs=phase_outputs,
        )
        and reconciliation.get("read_only") is True
        and reconciliation.get("broker_write_calls") == 0
        and recovery_commit.get("report_sha256")
        == report_sha256
        and recovery_commit.get("envelope_sha256")
        == envelope_sha256
        and recovery_commit.get("canonical_path") == str(canonical_path)
        and recovery_commit.get("candidate_payload_sha256")
        == hashlib.sha256(_recovery_json(dict(candidate))).hexdigest()
        and _valid_recovery_digest(
            prepare.get("expected_raw_stage_sha256")
        )
        and prepare == expected_prepare
        and receipt == receipt_expected
        and intent == expected_intent
        and state.get("promotion_commit_intent") == expected_intent
        and stage_request == expected_stage_request
        and state.get("promotion_stage_request")
        == expected_stage_request
    )


def _valid_immutable_strategy_promotion_sleeve_record(
    record: Mapping[str, Any],
) -> bool:
    """Validate the inert 6D immutable-evidence sleeve shape exactly."""
    source = record.get("source")
    metrics = record.get("metrics")
    evidence = record.get("evidence_metrics")
    if not isinstance(source, Mapping) or not isinstance(metrics, Mapping) or not isinstance(evidence, Mapping):
        return False
    source_keys = {
        "kind", "proposal_id", "proposal_sha256", "registration_id",
        "promotion_evidence_id", "promotion_evidence_sha256",
        "shadow_attestation_id", "shadow_attestation_sha256",
        "validation_attestation_sha256", "risk_attestation_sha256",
        "genome_id", "genome_canonical_sha256", "evaluation_code_commit",
        "evaluation_runtime_sha256", "promotion_runtime_commit",
        "risk_budget_mode", "account_hard_ceiling_usd",
        "new_sleeve_auto_promote", "proposal_effective_at",
        "proposal_recorded_at", "proposal_expires_at",
    }
    metric_keys = {
        "benchmark_excess_return", "cost_adjusted_alpha", "recent_alpha",
        "capacity_usd", "requested_tiny_live_tranche_usd",
    }
    evidence_decimal_keys = {
        "pooled_net_return_fraction", "pooled_benchmark_return_fraction",
        "pooled_benchmark_excess_fraction", "latest_window_net_return_fraction",
        "latest_window_benchmark_excess_fraction", "worst_max_drawdown_fraction",
    }
    evidence_count_keys = {
        "total_tracked_sessions", "total_closed_trades",
        "shadow_tracked_sessions", "shadow_reconciled_buy_intents",
    }
    effective = _parse_aware_recovery_time(source.get("proposal_effective_at"))
    recorded = _parse_aware_recovery_time(source.get("proposal_recorded_at"))
    expires = _parse_aware_recovery_time(source.get("proposal_expires_at"))
    transition_at = _parse_aware_recovery_time(
        record.get(
            "eligible_at"
            if record.get("stage") == "tiny_live_eligible"
            else "ineligible_at"
        )
    )
    if (
        set(source) != source_keys
        or set(metrics) != metric_keys
        or set(evidence) != evidence_decimal_keys | evidence_count_keys
        or source.get("kind") != "immutable_strategy_evidence"
        or record.get("live_enabled") is not False
        or source.get("risk_budget_mode") not in {"fixed_tranche", "autonomous_with_caps"}
        or type(source.get("new_sleeve_auto_promote")) is not bool
        or source.get("account_hard_ceiling_usd") is not None
        and _finite_recovery_decimal(source.get("account_hard_ceiling_usd"), positive=True) is None
        or effective is None
        or recorded is None
        or expires is None
        or transition_at is None
        or not effective <= recorded < expires
        or not recorded <= transition_at < expires
        or any(_finite_recovery_decimal(metrics.get(name)) is None for name in metric_keys)
        or any(_finite_recovery_decimal(evidence.get(name)) is None for name in evidence_decimal_keys)
        or any(type(evidence.get(name)) is not int or evidence.get(name) < 0 for name in evidence_count_keys)
    ):
        return False
    digest_keys = {
        "proposal_sha256", "promotion_evidence_sha256",
        "shadow_attestation_sha256", "validation_attestation_sha256",
        "risk_attestation_sha256", "genome_canonical_sha256",
        "evaluation_runtime_sha256",
    }
    if any(not _valid_recovery_digest(source.get(name)) for name in digest_keys):
        return False
    object_bindings = (
        ("proposal_id", "strategy-promotion-proposal-", "proposal_sha256"),
        ("registration_id", "evaluation-registration-", None),
        ("promotion_evidence_id", "promotion-evidence-", "promotion_evidence_sha256"),
        ("shadow_attestation_id", "paper-shadow-attestation-", "shadow_attestation_sha256"),
    )
    if any(
        type(source.get(name)) is not str
        or not source[name].startswith(prefix)
        or not _valid_recovery_digest(source[name].removeprefix(prefix))
        for name, prefix, _digest_name in object_bindings
    ) or (
        not _nonempty_recovery_string(source.get("genome_id"))
        or not str(source["genome_id"]).startswith("genome-")
        or not isinstance(source.get("evaluation_code_commit"), str)
        or not isinstance(source.get("promotion_runtime_commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}", source["evaluation_code_commit"]) is None
        or re.fullmatch(r"[0-9a-f]{40}", source["promotion_runtime_commit"]) is None
    ):
        return False
    benchmark_excess_return = _finite_recovery_decimal(
        metrics.get("benchmark_excess_return")
    )
    cost_adjusted_alpha = _finite_recovery_decimal(
        metrics.get("cost_adjusted_alpha")
    )
    recent_alpha = _finite_recovery_decimal(metrics.get("recent_alpha"))
    pooled_benchmark_excess = _finite_recovery_decimal(
        evidence.get("pooled_benchmark_excess_fraction")
    )
    latest_window_benchmark_excess = _finite_recovery_decimal(
        evidence.get("latest_window_benchmark_excess_fraction")
    )
    capacity_usd = _finite_recovery_decimal(metrics.get("capacity_usd"))
    requested_tranche_usd = _finite_recovery_decimal(
        metrics.get("requested_tiny_live_tranche_usd")
    )
    capacity_gate_passed = record.get("capacity_gate_passed")
    if (
        not all(
            record.get(name) is True
            for name in (
                "preregistered",
                "benchmark_gate_passed",
                "cost_gate_passed",
                "recent_alpha_gate_passed",
            )
        )
        or benchmark_excess_return != pooled_benchmark_excess
        or cost_adjusted_alpha != pooled_benchmark_excess
        or recent_alpha != latest_window_benchmark_excess
        or capacity_gate_passed is not (capacity_usd >= requested_tranche_usd)
    ):
        return False
    raw_shadow = record.get("shadow_sessions_sufficient")
    raw_reconciliation = record.get("reconciliation_confirmed")
    gate_projection = (
        ("ci_green", record.get("ci_green")),
        ("shadow_sessions_sufficient", raw_shadow),
        ("reconciliation_confirmed", raw_reconciliation),
        ("capacity_gate_passed", capacity_gate_passed),
        (
            "risk_budget_mode_capped",
            source.get("risk_budget_mode")
            in {"fixed_tranche", "autonomous_with_caps"},
        ),
        (
            "risk_auto_promotion_allowed",
            source.get("new_sleeve_auto_promote"),
        ),
    )
    expected_issues = [
        (
            "risk_budget_mode_not_capped"
            if name == "risk_budget_mode_capped"
            else "risk_auto_promotion_disabled"
            if name == "risk_auto_promotion_allowed"
            else name
        )
        for name, passed in gate_projection
        if passed is False
    ]
    return (
        type(raw_shadow) is bool
        and type(raw_reconciliation) is bool
        and record.get("shadow_confirmed") is (raw_shadow and raw_reconciliation)
        and source["proposal_id"].startswith("strategy-promotion-proposal-")
        and _valid_recovery_digest(
            source["proposal_id"].removeprefix("strategy-promotion-proposal-")
        )
        and record.get("issues") == expected_issues
        and (
            record.get("stage") != "paper_only"
            or not all(passed for _name, passed in gate_projection)
        )
        and (
            record.get("stage") != "tiny_live_eligible"
            or source.get("new_sleeve_auto_promote") is True
        )
    )


def _valid_promotion_sleeve_record(
    record: Mapping[str, Any], *, symbol: str
) -> bool:
    stage = record.get("stage")
    live_enabled = record.get("live_enabled")
    gates = (
        "preregistered",
        "ci_green",
        "shadow_confirmed",
        "benchmark_gate_passed",
        "cost_gate_passed",
        "recent_alpha_gate_passed",
        "capacity_gate_passed",
    )
    if (
        stage not in {"paper_only", "tiny_live_eligible"}
        or type(live_enabled) is not bool
        or any(type(record.get(name)) is not bool for name in gates)
        or not _nonempty_recovery_string(record.get("validation_report_ref"))
        or not _nonempty_recovery_string(record.get("risk_envelope_ref"))
    ):
        return False
    record_symbol = record.get("symbol")
    if record_symbol is not None and str(record_symbol).strip().upper() != symbol:
        return False
    issues = record.get("issues")
    if issues is not None and not _packet_string_list(issues):
        return False
    if stage == "paper_only" and live_enabled is not False:
        return False
    if stage == "tiny_live_eligible" and (
        not all(record.get(name) is True for name in gates)
        or issues not in (None, [])
    ):
        return False
    source = record.get("source")
    # A normal-live activation is repaired only by its proposal-aware local
    # transaction.  The legacy recovery path has no Task 2 intent or consumed
    # receipt, so treating this state as a generic promotion record would be an
    # authorization widening.  Keep it frozen and fail closed here.
    if (
        isinstance(source, Mapping)
        and source.get("kind") == "immutable_strategy_evidence"
        and live_enabled is True
    ):
        return False
    if isinstance(source, Mapping) and source.get("kind") == "immutable_strategy_evidence":
        timestamp = record.get("eligible_at" if stage == "tiny_live_eligible" else "ineligible_at")
        opposite = record.get("ineligible_at" if stage == "tiny_live_eligible" else "eligible_at")
        if _parse_aware_recovery_time(timestamp) is None or opposite is not None:
            return False
        return _valid_immutable_strategy_promotion_sleeve_record(record)
    for timestamp_name in ("promoted_at", "demoted_at"):
        timestamp = record.get(timestamp_name)
        if timestamp is not None and _parse_aware_recovery_time(timestamp) is None:
            return False
    if source is not None and (
        not isinstance(source, Mapping)
        or source.get("kind") != "paper_tournament"
        or not _nonempty_recovery_string(source.get("tournament_id"))
        or _parse_aware_recovery_time(source.get("report_generated_at")) is None
        or not _nonempty_recovery_string(source.get("candidate_reason"))
    ):
        return False
    metrics = record.get("metrics")
    metric_names = {
        "benchmark_excess_return",
        "cost_adjusted_alpha",
        "recent_alpha",
        "capacity_usd",
        "requested_tiny_live_tranche_usd",
    }
    if metrics is not None and (
        not isinstance(metrics, Mapping)
        or set(metrics) != metric_names
        or any(
            _finite_recovery_decimal(metrics.get(name)) is None
            for name in metric_names
        )
    ):
        return False
    evidence_metrics = record.get("evidence_metrics")
    evidence_decimal_names = {
        "total_return",
        "total_return_pct",
        "max_drawdown_pct",
        "win_rate_pct",
    }
    if evidence_metrics is not None and (
        not isinstance(evidence_metrics, Mapping)
        or set(evidence_metrics)
        != {*evidence_decimal_names, "tracked_days"}
        or any(
            _finite_recovery_decimal(evidence_metrics.get(name)) is None
            for name in evidence_decimal_names
        )
        or type(evidence_metrics.get("tracked_days")) is not int
        or evidence_metrics.get("tracked_days") < 0
    ):
        return False
    return all(
        not (
            ("digest" in str(name).casefold() or str(name).endswith("_sha256"))
            and not _valid_recovery_digest(value)
        )
        for name, value in record.items()
    )


def _valid_reconciliation_collection(
    value: object,
    *,
    symbol: str,
    checked_client_order_ids: set[str],
    collection: str,
) -> bool:
    if not isinstance(value, list):
        return False
    numeric_fields = (
        "qty",
        "notional",
        "limit_price",
        "filled_qty",
        "filled_avg_price",
    )
    for item in value:
        if (
            not isinstance(item, Mapping)
            or item.get("symbol") != symbol
            or not _nonempty_recovery_string(item.get("client_order_id"))
            or item.get("client_order_id") not in checked_client_order_ids
            or str(item.get("side") or "").strip().lower() not in {"buy", "sell"}
            or any(
                field in item
                and _finite_recovery_decimal(
                    item.get(field),
                    nonnegative=True,
                )
                is None
                for field in numeric_fields
            )
        ):
            return False
        status = str(item.get("status") or "").strip().lower()
        pending = status.startswith("pending_")
        if collection == "open_orders":
            if (
                status
                not in {"open", "new", "accepted", "partially_filled"}
                and not pending
            ):
                return False
            qty = _finite_recovery_decimal(item.get("qty"), positive=True)
            notional = _finite_recovery_decimal(
                item.get("notional"), positive=True
            )
            if qty is None and notional is None:
                return False
        elif collection == "recent_fills":
            if status in {"open", "new", "accepted"} or pending:
                return False
            filled_qty = _finite_recovery_decimal(
                item.get("filled_qty"), positive=True
            )
            if filled_qty is None:
                return False
            qty = (
                _finite_recovery_decimal(item.get("qty"), positive=True)
                if "qty" in item
                else None
            )
            if "qty" in item and (qty is None or filled_qty > qty):
                return False
            if (
                "filled_avg_price" in item
                and _finite_recovery_decimal(
                    item.get("filled_avg_price"), positive=True
                )
                is None
            ):
                return False
            if not any(
                _parse_aware_recovery_time(item.get(name)) is not None
                for name in ("filled_at", "updated_at", "submitted_at")
            ):
                return False
        else:
            return False
    return True


def _valid_reconciliation_phase_packet(
    packet: Mapping[str, Any], bindings: Mapping[str, str]
) -> bool:
    symbol = bindings["symbol"]
    position = packet.get("position")
    checked = packet.get("checked_client_order_ids")
    if not _packet_string_list(checked):
        return False
    checked_ids = set(checked)
    required_position_numbers = (
        "qty",
        "notional",
        "market_value",
        "avg_entry_price",
    )
    external_actions_valid = _valid_manual_exit_replay_suppressions(
        packet,
        symbol=symbol,
        checked_client_order_ids=checked_ids,
    )
    return (
        packet.get("schema_version") == "tradingagents.recovery_phase.v1"
        and packet.get("source_schema_version") == 1
        and packet.get("kind") == "symbol_broker_reconciliation"
        and packet.get("source_identity")
        == "alpaca_symbol_incident_reconciliation"
        and packet.get("symbol") == symbol
        and packet.get("read_only") is True
        and packet.get("analysis_only") is True
        and packet.get("execution_authority") == "none"
        and packet.get("can_submit_orders") is False
        and packet.get("matched") is True
        and packet.get("issues") == []
        and type(packet.get("broker_write_calls")) is int
        and packet.get("broker_write_calls") == 0
        and external_actions_valid
        and isinstance(position, Mapping)
        and position.get("symbol") == symbol
        and all(
            name in position
            and _finite_recovery_decimal(position.get(name)) is not None
            for name in required_position_numbers
        )
        and (
            "avg_entry_price_hint" not in position
            or position.get("avg_entry_price_hint") in {None, ""}
            or _finite_recovery_decimal(position.get("avg_entry_price_hint"))
            is not None
        )
        and _valid_reconciliation_collection(
            packet.get("open_orders"),
            symbol=symbol,
            checked_client_order_ids=checked_ids,
            collection="open_orders",
        )
        and _valid_reconciliation_collection(
            packet.get("recent_fills"),
            symbol=symbol,
            checked_client_order_ids=checked_ids,
            collection="recent_fills",
        )
    )


def _valid_manual_exit_replay_suppressions(
    packet: Mapping[str, Any],
    *,
    symbol: str,
    checked_client_order_ids: set[str],
) -> bool:
    resolved = packet.get("resolved_external_actions")
    suppressions = packet.get("replay_suppressions")
    if resolved is None and suppressions is None:
        return True
    if not isinstance(resolved, list) or not isinstance(suppressions, list):
        return False
    if not resolved and not suppressions:
        return True
    position = packet.get("position")
    if (
        len(resolved) != len(suppressions)
        or not isinstance(position, Mapping)
        or _finite_recovery_decimal(position.get("qty"), nonnegative=True)
        != Decimal("0")
        or packet.get("open_orders") != []
    ):
        return False
    recent_fills = packet.get("recent_fills")
    if not isinstance(recent_fills, list):
        return False
    seen: set[tuple[str, str]] = set()
    for action, suppression in zip(resolved, suppressions, strict=True):
        if not isinstance(action, Mapping) or not isinstance(suppression, Mapping):
            return False
        required_action = {
            "resolution_id", "attestation_path", "attestation_sha256",
            "source_packet_path", "source_packet_sha256", "symbol",
            "filled_qty", "originating_client_order_id",
            "resolved_by_client_order_id",
        }
        required_suppression = {
            "scope", "suppression_key", "resolution_id", "attestation_sha256",
            "source_packet_sha256", "symbol", "filled_qty",
            "originating_client_order_id", "resolved_by_client_order_id", "active",
        }
        if set(action) != required_action or set(suppression) != required_suppression:
            return False
        origin_id = action.get("originating_client_order_id")
        manual_id = action.get("resolved_by_client_order_id")
        pair = (str(origin_id), str(manual_id))
        if (
            pair in seen
            or not all(_nonempty_recovery_string(value) for value in pair)
            or origin_id == manual_id
            or origin_id not in checked_client_order_ids
            or manual_id not in checked_client_order_ids
            or action.get("symbol") != symbol
            or suppression.get("scope") != "exact_incident_exit_chain"
            or suppression.get("active") is not True
            or any(
                suppression.get(key) != action.get(key)
                for key in (
                    "resolution_id", "attestation_sha256",
                    "source_packet_sha256", "symbol", "filled_qty",
                    "originating_client_order_id", "resolved_by_client_order_id",
                )
            )
        ):
            return False
        seen.add(pair)
        filled_qty = _finite_recovery_decimal(action.get("filled_qty"), positive=True)
        if filled_qty is None:
            return False
        try:
            attribution, actual_attestation_digest = (
                capture_owner_manual_action_attribution(
                str(action["attestation_path"])
                )
            )
            attribution_origin = attribution["originating_order"]
            attribution_manual = attribution["manual_fill"]
            if not isinstance(attribution_origin, Mapping) or not isinstance(
                attribution_manual, Mapping
            ):
                return False
            source_order, actual_source_digest = capture_source_autonomous_order(
                str(action["source_packet_path"]),
                str(origin_id),
                symbol=symbol,
            )
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if (
            attribution.get("resolution_id") != action.get("resolution_id")
            or not Path(str(action["attestation_path"])).is_absolute()
            or str(Path(str(action["attestation_path"])).resolve())
            != action.get("attestation_path")
            or actual_attestation_digest != action.get("attestation_sha256")
            or not Path(str(action["source_packet_path"])).is_absolute()
            or str(Path(str(action["source_packet_path"])).resolve())
            != action.get("source_packet_path")
            or actual_source_digest != action.get("source_packet_sha256")
            or attribution.get("symbol") != symbol
            or attribution_origin.get("client_order_id") != origin_id
            or attribution_origin.get("source_packet_path")
            != action.get("source_packet_path")
            or attribution_origin.get("source_packet_sha256")
            != action.get("source_packet_sha256")
            or attribution_origin.get("filled_qty") != action.get("filled_qty")
            or attribution_origin.get("source_order") != source_order
            or attribution_manual.get("client_order_id") != manual_id
            or attribution_manual.get("filled_qty") != action.get("filled_qty")
            or source_order.get("side") != "buy"
        ):
            return False
        origin_fills = [
            fill for fill in recent_fills
            if isinstance(fill, Mapping) and fill.get("client_order_id") == origin_id
        ]
        manual_fills = [
            fill for fill in recent_fills
            if isinstance(fill, Mapping) and fill.get("client_order_id") == manual_id
        ]
        if len(origin_fills) != 1 or len(manual_fills) != 1:
            return False
        origin_fill, manual_fill = origin_fills[0], manual_fills[0]
        if (
            str(origin_fill.get("side") or "").lower() != "buy"
            or str(manual_fill.get("side") or "").lower() != "sell"
            or str(origin_fill.get("status") or "").lower() != "filled"
            or str(manual_fill.get("status") or "").lower() != "filled"
            or _finite_recovery_decimal(origin_fill.get("filled_qty"), positive=True)
            != filled_qty
            or _finite_recovery_decimal(manual_fill.get("filled_qty"), positive=True)
            != filled_qty
            or any(
                str(manual_fill.get(name) or "")
                != str(attribution_manual.get(name) or "")
                for name in (
                    "side", "status", "filled_qty", "filled_avg_price",
                    "submitted_at", "updated_at",
                )
            )
        ):
            return False
        expected_key = replay_suppression_key(
            attribution_sha256=str(action["attestation_sha256"]),
            resolution_id=str(action["resolution_id"]),
            symbol=symbol,
            originating_client_order_id=str(origin_id),
            resolved_by_client_order_id=str(manual_id),
            filled_qty=str(action["filled_qty"]),
            source_packet_sha256=str(action["source_packet_sha256"]),
        )
        if suppression.get("suppression_key") != expected_key:
            return False
    return True


def _valid_phase_packet(
    path: Path,
    phase: str,
    bindings: Mapping[str, str],
    *,
    state: Mapping[str, Any] | None = None,
    phase_outputs: Mapping[str, object] | None = None,
    control_path: str | Path | None = None,
    now: dt.datetime | None = None,
    idempotency_key: str | None = None,
) -> bool:
    try:
        packet = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if (
        phase not in RECOVERY_PHASES
        or not isinstance(packet, dict)
        or not isinstance(state, Mapping)
        or any(packet.get(key) != value for key, value in bindings.items())
    ):
        return False
    outputs = (
        phase_outputs
        if isinstance(phase_outputs, Mapping)
        else state.get("phase_outputs")
    )
    if not isinstance(outputs, Mapping):
        return False
    if (
        _parse_aware_recovery_time(packet.get("generated_at")) is None
        or packet.get("phase") != phase
        or packet.get("recovery_run_id") != state.get("recovery_run_id")
        or not is_safe_incident_id(packet.get("owner_run_id"))
        or not is_safe_incident_id(packet.get("owner_role"))
    ):
        return False
    if phase == "resolve_authority":
        return (
            packet.get("schema_version") == "tradingagents.recovery_phase.v1"
            and packet.get("kind") == "recovery_authority"
            and packet.get("allowed") is True
            and packet.get("requires_additional_decision") is False
            and isinstance(packet.get("authority_source"), str)
            and bool(packet["authority_source"].strip())
            and isinstance(packet.get("decision_owner"), str)
            and bool(packet["decision_owner"].strip())
        )
    if phase == "regenerate_evidence":
        return _valid_loss_review_phase_packet(packet, bindings)
    if phase == "sync_promotion":
        return _valid_promotion_phase_packet(
            path,
            packet,
            bindings,
            state=state,
            phase_outputs=outputs,
        )
    if phase == "reconcile":
        return _valid_reconciliation_phase_packet(packet, bindings)
    if phase == "focused_verify":
        return (
            packet.get("schema_version") == "tradingagents.recovery_phase.v1"
            and packet.get("focused_tests_passed") is True
            and packet.get("passing_tests") == list(RECOVERY_FOCUSED_TESTS)
            and is_safe_incident_id(packet.get("verifier_run_id"))
            and packet.get("verifier_role_id") == "integrity_verifier"
            and packet.get("owner_role") == "reliability_controller"
            and packet.get("verifier_run_id").casefold()
            != packet.get("owner_run_id").casefold()
        )
    if phase == "ready_incident":
        expected_phases = RECOVERY_PHASES[:5]
        if not all(_valid_recovery_record(outputs.get(name)) for name in expected_phases):
            return False
        root_cause_resolution = _ready_root_cause_resolution(
            outputs,
            bindings=bindings,
        )
        return (
            packet.get("schema_version") == "tradingagents.incident.v1"
            and packet.get("stage") == "ready"
            and isinstance(packet.get("history"), list)
            and any(
                isinstance(event, Mapping) and event.get("to_stage") == "ready"
                for event in packet["history"]
            )
            and packet.get("evidence_refs")
            == [outputs[name]["path"] for name in expected_phases]
            and packet.get("repairer_run_id") == packet.get("owner_run_id")
            and packet.get("repairer_role_id")
            == "reliability_controller"
            and packet.get("owner_role") == "reliability_controller"
            and packet.get("root_cause_resolved") is True
            and root_cause_resolution is not None
            and packet.get("root_cause_resolution") == root_cause_resolution
            and packet.get("external_blockers") == []
        )
    if phase == "manifest":
        source_records = _expected_source_records(outputs)
        focused_record = outputs.get("focused_verify")
        if source_records is None or not _valid_recovery_record(focused_record):
            return False
        try:
            focused = json.loads(
                Path(str(focused_record["path"])).read_text(encoding="utf-8")
            )
            ready = json.loads(
                Path(str(source_records["incident"]["path"])).read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return False
        return (
            isinstance(focused, Mapping)
            and isinstance(ready, Mapping)
            and packet.get("schema_version")
            == "tradingagents.recovery_manifest.v1"
            and packet.get("kind") == "verified_recovery_manifest"
            and packet.get("packet_paths")
            == {name: record["path"] for name, record in source_records.items()}
            and packet.get("packet_sha256")
            == {name: record["sha256"] for name, record in source_records.items()}
            and packet.get("repairer_run_id") == ready.get("repairer_run_id")
            and packet.get("repairer_role_id") == ready.get("repairer_role_id")
            and packet.get("verifier_run_id") == focused.get("verifier_run_id")
            and packet.get("verifier_role_id") == focused.get("verifier_role_id")
        )
    if phase == "rearm":
        return (
            packet.get("schema_version") == "tradingagents.recovery_phase.v1"
            and packet.get("kind") == "verified_rearm_result"
            and packet.get("can_submit_orders") is False
            and _canonical_absolute_path(packet.get("receipt_path")) is not None
            and _valid_recovery_digest(packet.get("receipt_sha256"))
            and control_path is not None
            and now is not None
            and _active_rearm_matches_intent(
                state,
                control_path=control_path,
                now=_recovery_now(now),
                idempotency_key=idempotency_key,
                packet=packet,
            )
        )
    return False


def _ready_root_cause_resolution(
    phase_outputs: Mapping[str, object],
    *,
    bindings: Mapping[str, str],
) -> dict[str, object] | None:
    record = phase_outputs.get("reconcile")
    if not _valid_recovery_record(record):
        return None
    path = Path(str(record["path"])).resolve()
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            return None
        packet = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(packet, Mapping) or not _valid_reconciliation_phase_packet(
        packet, bindings
    ):
        return None
    suppressions = packet.get("replay_suppressions")
    actions = packet.get("resolved_external_actions")
    if suppressions is None:
        suppressions = []
    if actions is None:
        actions = []
    if not isinstance(suppressions, list) or not isinstance(actions, list):
        return None
    return {
        "reconciliation_path": str(path),
        "reconciliation_sha256": record["sha256"],
        "resolved_external_action_count": len(actions),
        "replay_suppression_keys": [
            suppression["suppression_key"]
            for suppression in suppressions
            if isinstance(suppression, Mapping)
            and isinstance(suppression.get("suppression_key"), str)
        ],
    }


def _canonical_packet(packet: Mapping[str, Any], bindings: Mapping[str, str], now: dt.datetime) -> dict[str, Any]:
    payload = dict(packet)
    for key, value in bindings.items():
        existing = payload.get(key)
        if existing is not None and existing != value:
            raise ValueError(f"packet binding mismatch for {key}")
        payload[key] = value
    generated_at = payload.get("generated_at")
    if generated_at is not None and generated_at != now.isoformat():
        # Adapters may record their own timestamp, but it must be parseable and
        # cannot be an arbitrary object.
        if not isinstance(generated_at, str) or _parse_datetime(generated_at) is None:
            raise ValueError("adapter packet generated_at is invalid")
    else:
        payload["generated_at"] = now.isoformat()
    return payload


def _write_phase_packet(path: Path, packet: Mapping[str, Any]) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != packet:
            raise ValueError("immutable phase packet already exists with different content")
    else:
        encoded = _recovery_json(packet)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            if os.write(descriptor, encoded) != len(encoded):
                raise OSError("incomplete recovery phase write")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        parent_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    return _phase_record(path)


def _normalize_adapter_phase_packet(
    packet: Mapping[str, Any], *, phase: str
) -> dict[str, Any]:
    payload = dict(packet)
    raw_schema_version = payload.get("schema_version")
    if phase == "sync_promotion" and raw_schema_version is None:
        state = payload.get("state")
        if isinstance(state, Mapping):
            raw_schema_version = state.get("schema_version")
    if raw_schema_version is not None:
        existing_source_schema = payload.get("source_schema_version")
        if (
            existing_source_schema is not None
            and existing_source_schema != raw_schema_version
        ):
            raise ValueError("adapter source schema identity is inconsistent")
        payload["source_schema_version"] = raw_schema_version
    canonical_metadata = {
        "resolve_authority": ("recovery_authority", "recovery_authority"),
        "regenerate_evidence": (
            "loss_review_evidence",
            "loss_review_evidence",
        ),
        "sync_promotion": ("promotion_state_sync", "paper_tournament_sync"),
        "reconcile": (
            "symbol_broker_reconciliation",
            "alpaca_symbol_incident_reconciliation",
        ),
        "focused_verify": (
            "recovery_focused_proof",
            "recovery_focused_proof",
        ),
    }
    expected = canonical_metadata.get(phase)
    if expected is None:
        raise ValueError(f"unsupported adapter recovery phase: {phase}")
    payload.setdefault("kind", expected[0])
    payload.setdefault("source_identity", expected[1])
    payload["schema_version"] = "tradingagents.recovery_phase.v1"
    return payload


def _adapter_packet(result: object, *, phase: str) -> Mapping[str, Any]:
    if not isinstance(result, Mapping):
        raise ValueError("adapter result must be a packet record")
    if result.get("outcome", "success") != "success":
        failure_type = str(result.get("failure_type") or "permanent")
        detail = str(result.get("detail") or "adapter reported failure")
        raise RuntimeError(json.dumps({"failure_type": failure_type, "detail": detail}))
    packet = result.get("packet")
    if not isinstance(packet, Mapping):
        raise ValueError("adapter result packet must be an object")
    forbidden = set(_trigger_effects(packet)).intersection(FORBIDDEN_EFFECTS)
    if forbidden:
        raise PermissionError("forbidden recovery effects: " + ", ".join(sorted(forbidden)))
    return _normalize_adapter_phase_packet(packet, phase=phase)


def _failure_from_exception(error: Exception) -> dict[str, Any]:
    if isinstance(error, PermissionError):
        return _recovery_failure("forbidden_effect", str(error))
    if isinstance(error, RuntimeError):
        try:
            payload = json.loads(str(error))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict) and payload.get("failure_type") in {"transient", "external_blocked"}:
            return _recovery_failure(
                str(payload["failure_type"]), str(payload.get("detail") or "adapter failed"), external=payload["failure_type"] == "external_blocked"
            )
    return _recovery_failure("permanent_integrity", str(error))


def _record_recovery_incident(
    recovery_root: Path, state: Mapping[str, Any], *, now: dt.datetime
) -> None:
    """Expose compact, secret-free recovery state through the incident surface."""
    incident_root = recovery_root.parent / "incidents" / str(state["incident_id"])
    history = list(state.get("incident_history") or [])
    payload = {
        "schema_version": "tradingagents.incident.v1",
        "incident_id": state["incident_id"],
        "kind": "verified_internal_recovery",
        "subject": state["bindings"]["symbol"],
        "stage": state.get("incident_stage", "repairing"),
        "owner_role": state["owner_role"],
        "created_at": state["created_at"],
        "updated_at": now.isoformat(),
        "lease_expires_at": state.get("lease_expires_at"),
        "next_action": state.get("phase"),
        "retry_budget": RECOVERY_MAX_ATTEMPTS,
        "attempt_count": state.get("attempt", 0),
        "repairer_run_id": state["owner_run_id"],
        "verifier_run_id": state.get("verifier_run_id"),
        "evidence_refs": [value["path"] for value in state.get("phase_outputs", {}).values() if _valid_phase_record(value)],
        "external_blockers": list(state.get("external_blockers") or []),
        "history": history,
        "recovery": {
            "recovery_run_id": state["recovery_run_id"],
            "phase": state.get("phase"),
            "last_artifact": state.get("last_artifact"),
            "last_failure": state.get("last_failure"),
            "next_retry_at": state.get("next_retry_at"),
        },
    }
    atomic_write_text(incident_root / "latest.json", json.dumps(payload, indent=2, sort_keys=True))


def build_production_recovery_request(
    signal: Mapping[str, Any], *, repo_root: str | Path, command_runner: Any = subprocess.run
) -> dict[str, Any]:
    """Build the non-test dispatch contract for a recoverable plan signal.

    The adapters intentionally receive no command string. They consume only the
    fixed signal/context packet locations; missing proof is a durable transient
    recovery state, never a manual or silently skipped outcome. Real runtime
    integrations can replace the packet producers, not this authority boundary.
    """
    root = Path(repo_root).resolve()
    captured_signal = _captured_signal_packet(signal, root=root)
    if captured_signal is not None and _is_execution_board_packet(
        captured_path=captured_signal[0], packet=captured_signal[2], root=root
    ):
        return {
            "ready": False,
            "outcome": "not_recovery_work",
            "detail": "BOARD packet provenance cannot create an integrity recovery run",
        }
    recovery_classification = classify_recovery_signal(signal)
    if recovery_classification["classification"] != "recoverable_integrity":
        return {
            "ready": False,
            "outcome": "not_recovery_work",
            "detail": "signal is not an integrity recovery and cannot create a recovery run",
        }
    signature = _trigger_signature(signal)
    incident_id = f"self-heal-{hashlib.sha256(signature.encode()).hexdigest()[:20]}"
    context = signal.get("recovery_context")
    if not isinstance(context, Mapping):
        context = derive_production_recovery_context(signal, repo_root=root, command_runner=command_runner)
    required = {"symbol", "broker_account", "environment", "source_revision", "supervisor_path", "advisory_path", "hourly_dir", "report_path", "envelope_path", "promotion_state_path", "reconciliation_packet_paths"}
    if not isinstance(context, Mapping) or not required.issubset(context):
        return {"ready": False, "outcome": "transient", "detail": "canonical recovery context is incomplete"}
    symbol = str(context.get("symbol") or signal.get("symbol") or "").upper()
    signal_symbol = str(signal.get("symbol") or "").strip().upper()
    if (
        not symbol
        or bool(signal_symbol and symbol != signal_symbol)
        or any(
            not isinstance(context.get(key), str)
            or not str(context[key]).strip()
            for key in ("broker_account", "environment")
        )
        or not isinstance(context.get("source_revision"), str)
        or _SOURCE_REVISION.fullmatch(str(context["source_revision"])) is None
    ):
        return {"ready": False, "outcome": "transient", "detail": "canonical recovery bindings are incomplete"}
    bindings = {
        "incident_id": incident_id,
        "symbol": symbol,
        "broker_account": str(context["broker_account"]),
        "environment": str(context["environment"]),
        "source_revision": str(context["source_revision"]),
    }

    def unavailable(phase: str, detail: str) -> dict[str, Any]:
        return {"outcome": "failed", "failure_type": "transient", "detail": f"{phase}: {detail}"}

    def context_path(name: str) -> Path | None:
        raw = context.get(name)
        if not isinstance(raw, str) or not raw:
            return None
        candidate = Path(raw)
        path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        return path if _path_under(path, root) else None

    def run_json(phase: str, argv: list[str]) -> dict[str, Any]:
        try:
            result = command_runner(argv, cwd=str(root), capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as error:
            return unavailable(phase, _redact_recovery_detail(error))
        if int(getattr(result, "returncode", 1)) != 0:
            return unavailable(phase, _redact_recovery_detail(_compact_text(getattr(result, "stderr", "command failed"))))
        try:
            payload = json.loads(str(getattr(result, "stdout", "")))
        except json.JSONDecodeError:
            return unavailable(phase, "canonical command did not emit JSON")
        return {"packet": payload} if isinstance(payload, dict) else unavailable(phase, "canonical command emitted non-object JSON")

    def authority(_arguments: Mapping[str, Any]) -> dict[str, Any]:
        supervisor_path, advisory_path = context_path("supervisor_path"), context_path("advisory_path")
        supervisor = context.get("supervisor_record") if isinstance(context.get("supervisor_record"), Mapping) else (_read_json(supervisor_path) if supervisor_path else {})
        advisory = context.get("advisory_record") if isinstance(context.get("advisory_record"), Mapping) else (_read_json(advisory_path) if advisory_path else {})
        if not supervisor_path or not advisory_path or not supervisor or not advisory:
            return unavailable("resolve_authority", "canonical supervisor/advisory packets are unavailable")
        verdict = resolve_exit_authority(supervisor_review=supervisor, advisory_analysis=advisory)
        if verdict.allowed is not True or verdict.requires_additional_decision is True:
            return {"outcome": "failed", "failure_type": "permanent", "detail": "canonical exit authority is not internally allowed"}
        return {
            "packet": {
                "kind": "recovery_authority",
                "schema_version": "tradingagents.recovery_phase.v1",
                "allowed": True,
                "requires_additional_decision": False,
                "authority_source": verdict.authority_source,
                "decision_owner": verdict.decision_owner,
            }
        }

    def regenerate(_arguments: Mapping[str, Any]) -> dict[str, Any]:
        hourly_dir = context_path("hourly_dir")
        if hourly_dir is None:
            return unavailable("regenerate_evidence", "hourly evidence directory is unavailable")
        return run_json("regenerate_evidence", [sys.executable, "-m", "cli.main", "research", "loss-review-evidence", "--hourly-dir", str(hourly_dir), "--json-output"])

    def promotion(arguments: Mapping[str, Any]) -> dict[str, Any]:
        paths = [context_path(name) for name in ("report_path", "envelope_path", "promotion_state_path")]
        if any(path is None for path in paths):
            return unavailable("sync_promotion", "named promotion inputs are unavailable")
        report, envelope, canonical_state = paths
        phase_outputs = arguments.get("phase_outputs")
        run_root_raw = arguments.get("run_root")
        staging_dir_raw = arguments.get("staging_dir")
        if (
            not isinstance(phase_outputs, Mapping)
            or not isinstance(run_root_raw, str)
            or not isinstance(staging_dir_raw, str)
        ):
            return unavailable(
                "sync_promotion", "focused proof and deterministic staging are required"
            )
        run_root = Path(run_root_raw).resolve()
        staging_dir = Path(staging_dir_raw).resolve()
        if staging_dir != run_root / "staging":
            return {
                "outcome": "failed",
                "failure_type": "permanent",
                "detail": "sync_promotion: staging path is not canonical",
            }
        packet_dir = run_root / "packets"
        prepare_path = packet_dir / "promotion_prepare.json"
        receipt_path = packet_dir / "promotion_commit.json"
        stage_path = staging_dir / "promotion_state.json"
        if not all(
            _path_under(path, run_root)
            for path in (staging_dir, prepare_path, receipt_path, stage_path)
        ):
            return {
                "outcome": "failed",
                "failure_type": "permanent",
                "detail": "sync_promotion: transaction path escapes recovery run",
            }

        proof_state = {
            "recovery_run_id": arguments.get("recovery_run_id"),
            "owner_run_id": arguments.get("owner_run_id"),
            "owner_role": arguments.get("owner_role"),
            "phase_outputs": phase_outputs,
        }

        def bound_phase_packet(name: str) -> tuple[Mapping[str, Any], Mapping[str, str]]:
            record = phase_outputs.get(name)
            if not _valid_phase_record(record):
                raise ValueError(f"missing hash-bound {name} proof")
            record_path = Path(str(record["path"])).resolve()
            if (
                not _path_under(record_path, run_root)
                or _recovery_digest(record_path) != record["sha256"]
                or not _valid_phase_packet(
                    record_path,
                    name,
                    bindings,
                    state=proof_state,
                    phase_outputs=phase_outputs,
                )
            ):
                raise ValueError(f"invalid hash-bound {name} proof")
            packet = json.loads(record_path.read_text(encoding="utf-8"))
            return packet, record

        try:
            focused_packet, focused_record = bound_phase_packet("focused_verify")
            _reconciliation_packet, reconciliation_record = bound_phase_packet(
                "reconcile"
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return {
                "outcome": "failed",
                "failure_type": "permanent",
                "detail": f"sync_promotion: {_redact_recovery_detail(error)}",
            }
        if focused_packet.get("passing_tests") != list(RECOVERY_FOCUSED_TESTS):
            return {
                "outcome": "failed",
                "failure_type": "permanent",
                "detail": "sync_promotion: focused proof does not cover fixed policy suites",
            }
        if not all(path.exists() and path.is_file() for path in (report, envelope, canonical_state)):
            return unavailable("sync_promotion", "promotion input file is unavailable")
        try:
            report_bytes = report.read_bytes()
            envelope_bytes = envelope.read_bytes()
            report_packet = json.loads(report_bytes)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return unavailable("sync_promotion", "tournament report is invalid")
        report_payload = (
            report_packet.get("latest_report")
            if isinstance(report_packet.get("latest_report"), Mapping)
            else report_packet
        )
        candidate_payload = (
            report_payload.get("live_strategy_candidate")
            if isinstance(report_payload, Mapping)
            else {}
        )
        if not isinstance(candidate_payload, Mapping):
            candidate_payload = {}
        report_sha256 = hashlib.sha256(report_bytes).hexdigest()
        envelope_sha256 = hashlib.sha256(envelope_bytes).hexdigest()
        fault = arguments.get("_transaction_fault_hook")
        persist_intent = arguments.get("_persist_promotion_commit_intent")
        persist_stage_request = arguments.get(
            "_persist_promotion_stage_request"
        )
        assert_control_frozen = arguments.get(
            "_assert_recovery_control_frozen"
        )
        if (
            not callable(persist_intent)
            or not callable(persist_stage_request)
            or not callable(assert_control_frozen)
        ):
            return {
                "outcome": "failed",
                "failure_type": "permanent",
                "detail": (
                    "sync_promotion: durable stage, commit, and control "
                    "callbacks are required"
                ),
            }

        def emit_fault(boundary: str) -> None:
            if callable(fault):
                fault({"boundary": boundary, "phase": "sync_promotion"})

        def commit_seed(before_sha256: str) -> dict[str, Any]:
            return {
                "schema_version": "tradingagents.promotion_recovery_commit.v1",
                "incident_id": bindings["incident_id"],
                "recovery_run_id": str(arguments["recovery_run_id"]),
                "source_revision": bindings["source_revision"],
                "focused_path": str(Path(str(focused_record["path"])).resolve()),
                "focused_sha256": focused_record["sha256"],
                "verifier_run_id": focused_packet["verifier_run_id"],
                "verifier_role_id": focused_packet["verifier_role_id"],
                "reconciliation_path": str(
                    Path(str(reconciliation_record["path"])).resolve()
                ),
                "reconciliation_sha256": reconciliation_record["sha256"],
                "report_path": str(report),
                "report_sha256": report_sha256,
                "envelope_path": str(envelope),
                "envelope_sha256": envelope_sha256,
                "canonical_path": str(canonical_state),
                "canonical_before_sha256": before_sha256,
                "candidate_payload_sha256": hashlib.sha256(
                    _recovery_json(dict(candidate_payload))
                ).hexdigest(),
            }

        existing_stage_request = arguments.get("promotion_stage_request")
        requested_generated_at = (
            existing_stage_request.get("generated_at")
            if isinstance(existing_stage_request, Mapping)
            else arguments.get("generated_at")
        )
        generated_at = _parse_aware_recovery_time(requested_generated_at)
        if generated_at is None:
            return {
                "outcome": "failed",
                "failure_type": "permanent",
                "detail": "sync_promotion: deterministic generated_at is required",
            }
        deterministic_generated_at = generated_at.isoformat(timespec="seconds")
        envelope_config, envelope_issues = load_risk_envelope(envelope)
        if (
            envelope_config is None
            or report.read_bytes() != report_bytes
            or envelope.read_bytes() != envelope_bytes
        ):
            return {
                "outcome": "failed",
                "failure_type": (
                    "transient"
                    if envelope_config is not None
                    else "permanent"
                ),
                "detail": (
                    "sync_promotion: "
                    + (
                        "promotion inputs changed while anchoring"
                        if envelope_config is not None
                        else "risk envelope is invalid: "
                        + "; ".join(envelope_issues)
                    )
                ),
            }

        def expected_transaction(
            before_sha256: str,
            canonical_payload: Mapping[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
            seed = commit_seed(before_sha256)
            recovery_commit = {
                **seed,
                "commit_id": hashlib.sha256(_recovery_json(seed)).hexdigest(),
            }
            result = sync_promotion_state_from_tournament(
                report_payload,
                canonical_payload,
                tiny_live_tranche_usd=(
                    envelope_config.tiny_live_tranche_usd
                ),
                arm_live=True,
                ci_green=True,
                now=generated_at,
            )
            raw_state = dict(result.state)
            raw_source = raw_state.get("source")
            if not isinstance(raw_source, Mapping):
                raise ValueError("expected promotion source is malformed")
            raw_state["source"] = {
                **dict(raw_source),
                "canonical_input_sha256": before_sha256,
            }
            raw_bytes = json.dumps(raw_state, indent=2).encode("utf-8")
            enriched_state = dict(raw_state)
            enriched_state["source"] = {
                **dict(raw_state["source"]),
                "recovery_commit": recovery_commit,
            }
            enriched_bytes = json.dumps(
                enriched_state,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            return recovery_commit, raw_state, raw_bytes, enriched_bytes

        def stage_request_from_prepare(
            prepare: Mapping[str, Any],
            prepare_record: Mapping[str, str],
        ) -> dict[str, Any]:
            recovery_commit = prepare["recovery_commit"]
            return {
                "commit_id": recovery_commit["commit_id"],
                "prepare_path": prepare_record["path"],
                "prepare_sha256": prepare_record["sha256"],
                "stage_path": str(stage_path),
                "expected_raw_stage_sha256": prepare[
                    "expected_raw_stage_sha256"
                ],
                "expected_stage_sha256": prepare[
                    "expected_stage_sha256"
                ],
                "generated_at": prepare["generated_at"],
                "canonical_path": str(canonical_state),
                "canonical_before_sha256": recovery_commit[
                    "canonical_before_sha256"
                ],
                "report_sha256": recovery_commit["report_sha256"],
                "envelope_sha256": recovery_commit["envelope_sha256"],
                "focused_sha256": recovery_commit["focused_sha256"],
                "reconciliation_sha256": recovery_commit[
                    "reconciliation_sha256"
                ],
                "arm_live": True,
                "ci_green": True,
            }

        def read_prepare() -> tuple[
            dict[str, Any],
            dict[str, str],
            dict[str, Any],
        ]:
            # A legacy tournament transaction must never accept or replace an
            # immutable-strategy state.  Read and classify the canonical bytes
            # under the existing state lock so an old prepare cannot resume over
            # newer immutable provenance.
            with promotion_state_lock(canonical_state):
                canonical_preimage = canonical_state.read_bytes()
                canonical_preimage_sha256 = hashlib.sha256(
                    canonical_preimage
                ).hexdigest()
                canonical_payload = json.loads(canonical_preimage)
                canonical_source = (
                    canonical_payload.get("source")
                    if isinstance(canonical_payload, Mapping)
                    else None
                )
                if (
                    isinstance(canonical_source, Mapping)
                    and canonical_source.get("kind")
                    == "immutable_strategy_evidence_sync"
                ):
                    # Keep the captured digest local to this critical section:
                    # the refusal is tied to exactly the bytes inspected.
                    _ = canonical_preimage_sha256
                    raise ValueError(
                        "immutable strategy promotion requires proposal-aware recovery"
                    )
            if prepare_path.exists():
                prepare = json.loads(prepare_path.read_text(encoding="utf-8"))
                record = _phase_record(prepare_path)
                recovery_commit = prepare.get("recovery_commit")
                if (
                    prepare.get("schema_version")
                    != "tradingagents.promotion_prepare.v1"
                    or prepare.get("kind") != "promotion_commit_prepare"
                    or prepare.get("stage_path") != str(stage_path)
                    or not isinstance(recovery_commit, Mapping)
                    or prepare.get("generated_at")
                    != deterministic_generated_at
                    or prepare.get("arm_live") is not True
                    or prepare.get("ci_green") is not True
                    or not _valid_recovery_digest(
                        prepare.get("expected_raw_stage_sha256")
                    )
                    or not _valid_recovery_digest(
                        prepare.get("expected_stage_sha256")
                    )
                ):
                    raise ValueError("promotion prepare packet is malformed")
                if (
                    recovery_commit.get("report_sha256") != report_sha256
                    or recovery_commit.get("envelope_sha256")
                    != envelope_sha256
                ):
                    raise _PromotionStalePreimage(
                        "promotion inputs changed after prepare"
                    )
                seed = dict(recovery_commit)
                commit_id = seed.pop("commit_id", None)
                expected_seed = commit_seed(
                    str(recovery_commit.get("canonical_before_sha256") or "")
                )
                expected_commit_id = hashlib.sha256(
                    _recovery_json(expected_seed)
                ).hexdigest()
                if (
                    seed != expected_seed
                    or commit_id != expected_commit_id
                    or _recovery_digest(prepare_path) != record["sha256"]
                ):
                    raise ValueError("promotion prepare packet binding mismatch")
                request = stage_request_from_prepare(prepare, record)
                existing_request = arguments.get("promotion_stage_request")
                if (
                    not isinstance(existing_request, Mapping)
                    or dict(existing_request) != request
                ):
                    raise ValueError(
                        "promotion stage request binding mismatch"
                    )
                return prepare, record, request
            with promotion_state_lock(canonical_state):
                canonical_bytes = canonical_state.read_bytes()
                before_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
                existing_request = arguments.get(
                    "promotion_stage_request"
                )
                if isinstance(existing_request, Mapping) and (
                    existing_request.get("canonical_before_sha256")
                    != before_sha256
                    or existing_request.get("report_sha256")
                    != report_sha256
                    or existing_request.get("envelope_sha256")
                    != envelope_sha256
                ):
                    raise _PromotionStalePreimage(
                        "promotion inputs changed after stage request"
                    )
                canonical_payload = json.loads(canonical_bytes)
                if not isinstance(canonical_payload, Mapping):
                    raise ValueError("promotion canonical state is malformed")
                (
                    recovery_commit,
                    _raw_state,
                    raw_bytes,
                    enriched_bytes,
                ) = expected_transaction(
                    before_sha256,
                    canonical_payload,
                )
            prepare = {
                "schema_version": "tradingagents.promotion_prepare.v1",
                "kind": "promotion_commit_prepare",
                "recovery_commit": recovery_commit,
                "stage_path": str(stage_path),
                "generated_at": deterministic_generated_at,
                "arm_live": True,
                "ci_green": True,
                "expected_raw_stage_sha256": hashlib.sha256(
                    raw_bytes
                ).hexdigest(),
                "expected_stage_sha256": hashlib.sha256(
                    enriched_bytes
                ).hexdigest(),
                "can_submit_orders": False,
                "execution_authority": "none",
            }
            prepare_sha256 = hashlib.sha256(_recovery_json(prepare)).hexdigest()
            request = stage_request_from_prepare(
                prepare,
                {
                    "path": str(prepare_path.resolve()),
                    "sha256": prepare_sha256,
                },
            )
            existing_request = arguments.get("promotion_stage_request")
            if (
                existing_request is not None
                and (
                    not isinstance(existing_request, Mapping)
                    or dict(existing_request) != request
                )
            ):
                raise ValueError("persisted promotion stage request mismatch")
            persist_stage_request(request)
            emit_fault("after_promotion_stage_request_fsync")
            record = _write_phase_packet(prepare_path, prepare)
            if record["sha256"] != prepare_sha256:
                raise ValueError("promotion prepare digest mismatch")
            emit_fault("after_promotion_prepare_fsync")
            return prepare, record, request

        def reconstruct_packet(
            staged_state: Mapping[str, Any],
            recovery_commit: Mapping[str, Any],
        ) -> dict[str, Any]:
            sleeves = staged_state.get("sleeves")
            candidate_id = (
                str(candidate_payload.get("strategy_id"))
                if candidate_payload.get("status") == "candidate"
                and candidate_payload.get("strategy_id")
                else None
            )
            candidate_record = (
                sleeves.get(candidate_id)
                if isinstance(sleeves, Mapping) and candidate_id
                else None
            )
            candidate_issues = (
                list(candidate_record.get("issues") or [])
                if isinstance(candidate_record, Mapping)
                else []
            )
            promoted = (
                [candidate_id]
                if isinstance(candidate_record, Mapping)
                and candidate_record.get("stage") == "tiny_live_eligible"
                and candidate_record.get("live_enabled") is True
                else []
            )
            demoted = [
                str(sleeve_id)
                for sleeve_id, record in (sleeves.items() if isinstance(sleeves, Mapping) else ())
                if isinstance(record, Mapping)
                and record.get("stage") == "paper_only"
                and record.get("live_enabled") is False
                and _nonempty_recovery_string(record.get("demotion_reason"))
            ]
            issues_by_sleeve = {
                str(sleeve_id): list(record.get("issues") or [])
                for sleeve_id, record in (
                    sleeves.items() if isinstance(sleeves, Mapping) else ()
                )
                if isinstance(record, Mapping) and "issues" in record
            }
            if candidate_id and candidate_id not in issues_by_sleeve:
                issues_by_sleeve[candidate_id] = candidate_issues
            issues = [
                str(issue)
                for values in issues_by_sleeve.values()
                for issue in values
            ]
            return {
                "summary": "promotion state synchronized by verified recovery",
                "promoted": promoted,
                "demoted": demoted,
                "issues_by_sleeve": issues_by_sleeve,
                "state_path": str(canonical_state),
                "canonical_state_path": str(canonical_state),
                "report_path": str(report),
                "arm_live": True,
                "ci_green": True,
                "can_submit_orders": False,
                "execution_authority": "none",
                "state": dict(staged_state),
                "promotion_evidence_fresh": not issues,
                "issues": issues,
                "recovery_commit": dict(recovery_commit),
            }

        try:
            prepare, prepare_record, stage_request = read_prepare()
            recovery_commit = dict(prepare["recovery_commit"])

            def anchored_inputs_changed() -> bool:
                try:
                    return (
                        _recovery_digest(report)
                        != recovery_commit["report_sha256"]
                        or _recovery_digest(envelope)
                        != recovery_commit["envelope_sha256"]
                    )
                except OSError:
                    return True

            def canonical_moved_outside_transaction() -> bool:
                try:
                    current_digest = _recovery_digest(canonical_state)
                except OSError:
                    return True
                return current_digest not in {
                    recovery_commit["canonical_before_sha256"],
                    prepare["expected_stage_sha256"],
                }

            if stage_path.exists():
                stage_bytes = stage_path.read_bytes()
            else:
                result = run_json(
                    "sync_promotion",
                    [
                        sys.executable,
                        "-m",
                        "cli.main",
                        "policy",
                        "sync-promotion",
                        "--report-path",
                        str(report),
                        "--envelope-path",
                        str(envelope),
                        "--state-path",
                        str(canonical_state),
                        "--output-state-path",
                        str(stage_path),
                        "--arm-live",
                        "--ci-green",
                        "--generated-at",
                        deterministic_generated_at,
                        "--json-output",
                    ],
                )
                raw_packet = (
                    result.get("packet") if isinstance(result, Mapping) else None
                )
                if not isinstance(raw_packet, Mapping) or not stage_path.exists():
                    return unavailable(
                        "sync_promotion", "canonical promotion staging failed"
                    )
                stage_bytes = stage_path.read_bytes()
            stage_digest = hashlib.sha256(stage_bytes).hexdigest()
            expected_raw_sha256 = prepare["expected_raw_stage_sha256"]
            expected_stage_sha256 = prepare["expected_stage_sha256"]
            if stage_digest not in {
                expected_raw_sha256,
                expected_stage_sha256,
            }:
                if (
                    anchored_inputs_changed()
                    or canonical_moved_outside_transaction()
                ):
                    raise _PromotionStalePreimage(
                        "promotion inputs changed during staging"
                    )
                raise ValueError(
                    "staged promotion bytes do not match the pre-stage request"
                )
            staged_state = json.loads(stage_bytes)
            if not isinstance(staged_state, Mapping):
                raise ValueError("staged promotion state is malformed")
            source = staged_state.get("source")
            if not isinstance(source, Mapping):
                raise ValueError("staged promotion source is malformed")
            if (
                source.get("canonical_input_sha256")
                != recovery_commit["canonical_before_sha256"]
            ):
                raise _PromotionStalePreimage(
                    "promotion canonical changed during staging"
                )
            if stage_digest == expected_raw_sha256:
                if "recovery_commit" in source:
                    raise ValueError(
                        "raw promotion stage already carries recovery metadata"
                    )
                staged_state = dict(staged_state)
                staged_state["source"] = {
                    **dict(source),
                    "recovery_commit": recovery_commit,
                }
                atomic_write_text(
                    stage_path,
                    json.dumps(staged_state, indent=2, sort_keys=True),
                )
            elif source.get("recovery_commit") != recovery_commit:
                raise ValueError(
                    "enriched promotion stage has the wrong recovery commit"
                )
            staged_sha256 = _recovery_digest(stage_path)
            if staged_sha256 != expected_stage_sha256:
                raise ValueError(
                    "enriched promotion stage digest does not match prepare"
                )
            packet = reconstruct_packet(staged_state, recovery_commit)
            staged_source = staged_state.get("source")
            staged_sleeves = staged_state.get("sleeves")
            if (
                staged_state.get("schema_version") != "1.1.0"
                or _parse_aware_recovery_time(staged_state.get("generated_at"))
                is None
                or not isinstance(staged_source, Mapping)
                or staged_source.get("kind") != "paper_tournament_sync"
                or staged_source.get("arm_live") is not True
                or staged_source.get("ci_green") is not True
                or staged_source.get("canonical_input_sha256")
                != recovery_commit["canonical_before_sha256"]
                or staged_source.get("recovery_commit") != recovery_commit
                or not isinstance(staged_sleeves, Mapping)
                or not all(
                    _nonempty_recovery_string(sleeve_id)
                    and isinstance(record, Mapping)
                    and _valid_promotion_sleeve_record(
                        record,
                        symbol=bindings["symbol"],
                    )
                    for sleeve_id, record in staged_sleeves.items()
                )
                or packet.get("issues") != []
                or any(packet.get("issues_by_sleeve", {}).values())
                or any(
                    staged_sleeves[sleeve_id].get("stage")
                    != "tiny_live_eligible"
                    or staged_sleeves[sleeve_id].get("live_enabled") is not True
                    for sleeve_id in packet.get("promoted", [])
                )
            ):
                raise ValueError(
                    "staged promotion transaction failed semantic validation"
                )
            intent = {
                "commit_id": recovery_commit["commit_id"],
                "prepare_path": prepare_record["path"],
                "prepare_sha256": prepare_record["sha256"],
                "staged_path": str(stage_path),
                "staged_sha256": staged_sha256,
                "canonical_path": str(canonical_state),
                "canonical_before_sha256": recovery_commit[
                    "canonical_before_sha256"
                ],
            }
            with promotion_state_lock(canonical_state):
                current_sha256 = _recovery_digest(canonical_state)
                if anchored_inputs_changed():
                    raise _PromotionStalePreimage(
                        "promotion inputs changed after staging"
                    )
                if callable(persist_intent):
                    persist_intent(intent)
                emit_fault("after_promotion_intent_fsync")
                assert_control_frozen()
                if current_sha256 == recovery_commit["canonical_before_sha256"]:
                    atomic_write_text(
                        canonical_state,
                        stage_path.read_text(encoding="utf-8"),
                    )
                    current_sha256 = _recovery_digest(canonical_state)
                    if current_sha256 != staged_sha256:
                        raise ValueError("promotion canonical replace digest mismatch")
                    emit_fault("after_promotion_canonical_replace")
                elif current_sha256 == staged_sha256:
                    canonical = json.loads(
                        canonical_state.read_text(encoding="utf-8")
                    )
                    canonical_commit = (
                        canonical.get("source", {}).get("recovery_commit")
                        if isinstance(canonical, Mapping)
                        else None
                    )
                    if canonical_commit != recovery_commit:
                        raise ValueError("committed promotion identity mismatch")
                else:
                    raise _PromotionStalePreimage(
                        "promotion canonical state changed after prepare"
                    )
                receipt = {
                    "schema_version": "tradingagents.promotion_commit.v1",
                    "kind": "verified_promotion_commit",
                    "recovery_commit": recovery_commit,
                    "prepare_path": prepare_record["path"],
                    "prepare_sha256": prepare_record["sha256"],
                    "staged_path": str(stage_path),
                    "staged_sha256": staged_sha256,
                    "canonical_path": str(canonical_state),
                    "canonical_before_sha256": recovery_commit[
                        "canonical_before_sha256"
                    ],
                    "canonical_after_sha256": staged_sha256,
                    "can_submit_orders": False,
                    "execution_authority": "none",
                }
                receipt_record = _write_phase_packet(receipt_path, receipt)
                emit_fault("after_promotion_commit_receipt_fsync")
            packet.update(
                {
                    "staged_state_path": str(stage_path),
                    "staged_state_sha256": staged_sha256,
                    "canonical_after_sha256": staged_sha256,
                    "promotion_prepare": prepare_record,
                    "promotion_commit": receipt_record,
                    "promotion_commit_intent": intent,
                    "promotion_stage_request": stage_request,
                }
            )
            return {"packet": packet}
        except _PromotionStalePreimage as error:
            return {
                "outcome": "failed",
                "failure_type": "transient",
                "detail": f"sync_promotion: {_redact_recovery_detail(error)}",
            }
        except (OSError, ValueError, json.JSONDecodeError, KeyError) as error:
            return {
                "outcome": "failed",
                "failure_type": "permanent",
                "detail": f"sync_promotion: {_redact_recovery_detail(error)}",
            }

    def reconcile(_arguments: Mapping[str, Any]) -> dict[str, Any]:
        raw_paths = context.get("reconciliation_packet_paths")
        if not isinstance(raw_paths, list) or not raw_paths:
            return unavailable("reconcile", "canonical reconciliation packet paths are unavailable")
        paths = [context_path_value(value) for value in raw_paths]
        if any(path is None for path in paths):
            return unavailable("reconcile", "reconciliation path escapes the repo")
        argv = [sys.executable, "-m", "cli.main", "alpaca", "reconcile-symbol-incident", "--symbol", symbol]
        for path in paths:
            argv.extend(["--packet-path", str(path)])
        raw_attributions = context.get("owner_action_attestation_paths", [])
        if not isinstance(raw_attributions, list):
            return unavailable(
                "reconcile", "owner action attribution paths are malformed"
            )
        attribution_paths = [
            context_path_value(value) for value in raw_attributions
        ]
        if any(path is None or not path.is_file() for path in attribution_paths):
            return unavailable(
                "reconcile", "owner action attribution path is unavailable"
            )
        for path in attribution_paths:
            argv.extend(["--owner-action-attestation", str(path)])
        result = run_json("reconcile", [*argv, "--json-output"])
        packet = result.get("packet") if isinstance(result, Mapping) else None
        required_reconciliation = {"read_only", "execution_authority", "can_submit_orders", "matched", "issues", "broker_write_calls"}
        if not isinstance(packet, dict) or not required_reconciliation.issubset(packet):
            return unavailable("reconcile", "canonical reconciliation result is incomplete")
        return result

    def context_path_value(raw: object) -> Path | None:
        if not isinstance(raw, str):
            return None
        candidate = Path(raw)
        path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        return path if _path_under(path, root) else None

    def focused(_arguments: Mapping[str, Any]) -> dict[str, Any]:
        try:
            revision = command_runner(["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as error:
            return unavailable("focused_verify", _redact_recovery_detail(error))
        if int(getattr(revision, "returncode", 1)) != 0 or str(getattr(revision, "stdout", "")).strip() != bindings["source_revision"]:
            return unavailable("focused_verify", "checkout source revision does not match recovery binding")
        try:
            result = command_runner([sys.executable, "-m", "pytest", *RECOVERY_FOCUSED_TESTS, "-q"], cwd=str(root), capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as error:
            return unavailable("focused_verify", _redact_recovery_detail(error))
        if int(getattr(result, "returncode", 1)) != 0:
            return unavailable("focused_verify", "fixed focused verification failed")
        verifier_role_id = _required_authority_owner(
            ActionClass.VERIFY,
            expected_owner="integrity_verifier",
        )
        return {
            "packet": {
                "kind": "recovery_focused_proof",
                "schema_version": "tradingagents.recovery_phase.v1",
                "focused_tests_passed": True,
                "passing_tests": list(RECOVERY_FOCUSED_TESTS),
                "verifier_run_id": f"self-heal-verifier-{secrets.token_hex(8)}",
                "verifier_role_id": verifier_role_id,
            }
        }

    return {
        "ready": True,
        "incident_id": incident_id,
        "bindings": bindings,
        "owner_run_id": f"self-heal-owner-{hashlib.sha256((signature + ':owner').encode()).hexdigest()[:16]}",
        "recovery_run_id": f"self-heal-run-{hashlib.sha256((signature + ':run').encode()).hexdigest()[:16]}",
        "idempotency_key": f"self-heal-delivery-{hashlib.sha256(signature.encode()).hexdigest()[:16]}",
        "adapters": {"resolve_authority": authority, "regenerate_evidence": regenerate, "sync_promotion": promotion, "reconcile": reconcile, "focused_verify": focused},
    }


def derive_production_recovery_context(
    signal: Mapping[str, Any], *, repo_root: str | Path, command_runner: Any = subprocess.run
) -> dict[str, Any] | None:
    """Resolve only canonical, repo-contained recovery evidence for a signal."""
    root = Path(repo_root).resolve()
    flagged = signal.get("path")
    candidates = [root / "results" / "loss_review_evidence" / "latest.json"]
    if isinstance(flagged, str) and flagged:
        flagged_path = Path(flagged)
        candidates.insert(
            0,
            flagged_path.resolve()
            if flagged_path.is_absolute()
            else (root / flagged_path).resolve(),
        )
    signal_symbol = str(signal.get("symbol") or "").strip().upper()
    signal_account = str(
        signal.get("broker_account") or signal.get("account") or ""
    ).strip()
    selected: dict[str, Any] | None = None
    seen_candidates: set[Path] = set()
    for candidate in candidates:
        evidence_path = candidate.resolve()
        if (
            evidence_path in seen_candidates
            or not _path_under(evidence_path, root)
            or not evidence_path.is_file()
        ):
            continue
        seen_candidates.add(evidence_path)
        envelope = _read_json(evidence_path)
        payload = envelope.get("payload")
        if (
            envelope.get("schema_version") != "1.0.0"
            or envelope.get("source_name") != "loss_review_evidence"
            or envelope.get("evidence_type") != "loss_review_evidence"
            or not isinstance(payload, Mapping)
        ):
            continue
        supervisor = payload.get("supervisor_review_authority")
        advisory = payload.get("advisory_analysis")
        entry_context = payload.get("entry_context")
        hourly_ref = payload.get("hourly_packet_path")
        if (
            not isinstance(supervisor, Mapping)
            or not isinstance(advisory, Mapping)
            or not isinstance(entry_context, Mapping)
            or not _nonempty_recovery_string(hourly_ref)
        ):
            continue
        hourly_candidate = Path(hourly_ref)
        hourly_packet = (
            hourly_candidate.resolve()
            if hourly_candidate.is_absolute()
            else (root / hourly_candidate).resolve()
        )
        if not _path_under(hourly_packet, root) or not hourly_packet.is_file():
            continue
        hourly = _read_json(hourly_packet)
        hourly_evidence = (
            hourly.get("evidence")
            if isinstance(hourly.get("evidence"), Mapping)
            else {}
        )
        hourly_review = (
            hourly_evidence.get("loss_exit_review")
            if isinstance(hourly_evidence.get("loss_exit_review"), Mapping)
            else {}
        )
        evidence_symbols = [
            envelope.get("subject"),
            envelope.get("symbol"),
            payload.get("symbol"),
            supervisor.get("symbol"),
            advisory.get("symbol"),
            hourly_review.get("symbol"),
        ]
        normalized_symbols = [
            str(value or "").strip().upper() for value in evidence_symbols
        ]
        if any(not value for value in normalized_symbols) or len(
            set(normalized_symbols)
        ) != 1:
            continue
        symbol = normalized_symbols[0]
        if signal_symbol and signal_symbol != symbol:
            return None
        entry_symbol = str(entry_context.get("symbol") or "").strip().upper()
        if entry_symbol and entry_symbol != symbol:
            continue
        expected_account = "live"
        account_values = [
            str(entry_context.get("account") or "").strip(),
            *[
                str(value).strip()
                for value in (
                    envelope.get("broker_account"),
                    envelope.get("account"),
                    payload.get("broker_account"),
                    payload.get("account"),
                )
                if value is not None and str(value).strip()
            ],
        ]
        if signal_account and signal_account != expected_account:
            return None
        if not account_values[0] or any(
            account != expected_account for account in account_values
        ):
            continue
        selected = {
            "evidence_path": evidence_path,
            "envelope": envelope,
            "payload": payload,
            "supervisor": supervisor,
            "advisory": advisory,
            "hourly_packet": hourly_packet,
            "symbol": symbol,
            "account": expected_account,
        }
        break
    if selected is None:
        return None
    evidence_path = selected["evidence_path"]
    supervisor = selected["supervisor"]
    advisory = selected["advisory"]
    hourly_packet = selected["hourly_packet"]
    symbol = selected["symbol"]
    account = selected["account"]

    required_paths = {
        "hourly_dir": hourly_packet.parent,
        "report_path": root / "results" / "paper_strategy_tournament" / "latest.json",
        "envelope_path": root / "config" / "risk_envelope.yaml",
        "promotion_state_path": root / "results" / "policy" / "promotion_state.json",
    }
    if not all(
        _path_under(path, root) and path.exists() for path in required_paths.values()
    ):
        return None
    try:
        revision = command_runner(["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    source_revision = str(getattr(revision, "stdout", "")).strip()
    if int(getattr(revision, "returncode", 1)) != 0 or not source_revision:
        return None
    return {
        "symbol": symbol,
        "broker_account": account,
        "environment": "production",
        "source_revision": source_revision,
        "supervisor_path": str(evidence_path),
        "advisory_path": str(evidence_path),
        "supervisor_record": dict(supervisor),
        "advisory_record": dict(advisory),
        "hourly_dir": str(required_paths["hourly_dir"]),
        "report_path": str(required_paths["report_path"]),
        "envelope_path": str(required_paths["envelope_path"]),
        "promotion_state_path": str(required_paths["promotion_state_path"]),
        "reconciliation_packet_paths": [str(hourly_packet)],
        "owner_action_attestation_paths": [
            str(path.resolve())
            for path in sorted(
                (
                    root
                    / "results"
                    / "control_plane"
                    / "owner_manual_actions"
                    / symbol
                ).glob("*.json")
            )
            if path.is_file()
        ],
    }


def coordinate_verified_recovery(
    *,
    incident_id: str,
    bindings: Mapping[str, str],
    adapters: Mapping[str, Any],
    owner_run_id: str,
    recovery_run_id: str,
    control_path: str | Path,
    receipt_dir: str | Path,
    recovery_root: str | Path = "results/control_plane/recovery",
    owner_role: str = "reliability_controller",
    idempotency_key: str | None = None,
    now: dt.datetime | None = None,
    rearm: Any = rearm_after_verified_recovery,
    fault_hook: Any = None,
) -> dict[str, Any]:
    """Own a resumable internal recovery without acquiring broker authority.

    Each adapter receives structured data only and returns ``{"packet": {...}}``.
    The coordinator writes immutable packets itself, binds them to the canonical
    incident identity, and can only unfreeze through the injected Task 5 rearm
    function (which defaults to :func:`rearm_after_verified_recovery`).
    """
    try:
        current = _recovery_now(now)
    except ValueError:
        _preserve_frozen_or_close_recovery_control(
            control_path,
            reason="recovery time is invalid",
            now=dt.datetime.now(tz=UTC),
        )
        raise

    def fail_closed(
        reason: str,
        *,
        persisted_state: Mapping[str, Any] | None = None,
    ) -> None:
        _preserve_frozen_or_close_recovery_control(
            control_path,
            reason=reason,
            now=current,
            state=persisted_state,
            idempotency_key=idempotency_key,
        )

    try:
        rearm_request_owner = _required_authority_owner(
            ActionClass.REARM_REQUEST,
            expected_owner="reliability_controller",
        )
        rearm_issue_owner = _required_authority_owner(
            ActionClass.REARM_ISSUE,
            expected_owner="integrity_verifier",
        )
    except ValueError:
        fail_closed("rearm authority contract is unavailable")
        raise

    required_bindings = {"incident_id", "symbol", "broker_account", "environment", "source_revision"}
    try:
        canonical_bindings = dict(bindings)
        canonical_bindings["incident_id"] = incident_id
        bindings_valid = set(canonical_bindings) == required_bindings and all(
            isinstance(value, str) and value.strip()
            for value in canonical_bindings.values()
        )
    except Exception:
        fail_closed("canonical recovery bindings are unreadable")
        raise ValueError("canonical recovery bindings are required") from None
    if not bindings_valid:
        fail_closed("canonical recovery bindings are invalid")
        raise ValueError("canonical recovery bindings are required")
    if not isinstance(owner_run_id, str) or not owner_run_id.strip() or not isinstance(recovery_run_id, str) or not recovery_run_id.strip():
        fail_closed("recovery or owner run identifier is blank")
        raise ValueError("recovery and owner run IDs are required")
    if not all(
        is_safe_incident_id(value)
        for value in (incident_id, owner_run_id, recovery_run_id, owner_role)
    ):
        fail_closed("unsafe recovery identifier")
        return {"status": "corrupt_state", "incident_id": incident_id, "phase": None, "failure": _recovery_failure("permanent_integrity", "unsafe recovery identifier")}
    if owner_role != rearm_request_owner:
        fail_closed("recovery owner lacks rearm request authority")
        raise ValueError("recovery owner authority is invalid")
    if idempotency_key is not None and (not isinstance(idempotency_key, str) or not is_safe_incident_id(idempotency_key)):
        fail_closed("unsafe idempotency key")
        return {"status": "corrupt_state", "incident_id": incident_id, "phase": None, "failure": _recovery_failure("permanent_integrity", "unsafe idempotency key")}
    root = Path(recovery_root).resolve()
    incident_root = root / incident_id
    run_root = incident_root / recovery_run_id
    state_path = incident_root / "state.json"
    lock_path = incident_root / ".owner.lock"
    if not all(_path_under(path, root) for path in (incident_root, run_root, state_path, lock_path)):
        fail_closed("recovery path escapes root")
        return {"status": "corrupt_state", "incident_id": incident_id, "phase": None, "failure": _recovery_failure("permanent_integrity", "recovery path escapes root")}
    try:
        descriptor, lock_status, lock_token = _recovery_lock(
            lock_path,
            incident_id=incident_id,
            owner_run_id=owner_run_id,
            lease_expires_at=(
                current + dt.timedelta(minutes=RECOVERY_LEASE_MINUTES)
            ).isoformat(),
            now=current,
        )
    except Exception:
        fail_closed("recovery lock acquisition failed")
        raise
    if descriptor is None:
        busy_state: Mapping[str, Any] | None = None
        if lock_status == "owner_busy":
            candidate_state, candidate_error = _read_recovery_state(state_path)
            if candidate_error is None:
                busy_state = candidate_state
        fail_closed(
            (
                "recovery lock is malformed"
                if lock_status == "corrupt_lock"
                else "recovery owner is busy"
            ),
            persisted_state=busy_state,
        )
        if lock_status == "corrupt_lock":
            return {"status": "corrupt_state", "incident_id": incident_id, "phase": None, "failure": _recovery_failure("permanent_integrity", "recovery lock is malformed")}
        return {"status": "owner_busy", "incident_id": incident_id, "phase": None}
    try:
        state, state_error = _read_recovery_state(state_path)
        if state_error == "legacy_v1":
            assert isinstance(state, dict)
            fail_closed("legacy v1 recovery requires a frozen migration")
            if (
                state.get("incident_id") != incident_id
                or state.get("bindings") != canonical_bindings
                or state.get("recovery_run_id") != recovery_run_id
            ):
                _append_recovery_event(
                    incident_root,
                    {
                        "event": "corrupt_state",
                        "incident_id": incident_id,
                        "at": current.isoformat(),
                    },
                )
                return {
                    "status": "corrupt_state",
                    "incident_id": incident_id,
                    "phase": None,
                    "failure": _recovery_failure(
                        "permanent_integrity",
                        "legacy v1 recovery identity is malformed",
                    ),
                }
            legacy_bytes = state_path.read_bytes()
            legacy_sha256 = hashlib.sha256(legacy_bytes).hexdigest()
            legacy_path = (
                incident_root / f"state-v1-{legacy_sha256}.json"
            )
            _write_immutable_recovery_bytes(legacy_path, legacy_bytes)
            next_run = f"{recovery_run_id}-v2-follow-1"
            if not is_safe_incident_id(next_run):
                fail_closed("unsafe v2 recovery follow-on identifier")
                return {
                    "status": "corrupt_state",
                    "incident_id": incident_id,
                    "phase": None,
                    "failure": _recovery_failure(
                        "permanent_integrity",
                        "unsafe v2 recovery follow-on identifier",
                    ),
                }
            migration_event = {
                "event": "legacy_v1_migrated",
                "at": current.isoformat(),
                "legacy_v1_state_path": str(legacy_path.resolve()),
                "legacy_v1_state_sha256": legacy_sha256,
                "recovery_run_id": next_run,
            }
            recovery_control_freeze = _establish_recovery_control_freeze(
                control_path,
                incident_id=incident_id,
                recovery_run_id=next_run,
                now=current,
            )
            state = {
                "schema_version": "tradingagents.self_heal_recovery.v2",
                "incident_id": incident_id,
                "bindings": canonical_bindings,
                "recovery_run_id": next_run,
                "parent_recovery_run_id": recovery_run_id,
                "follow_on_count": 1,
                "follow_on_required": False,
                "owner_role": owner_role,
                "owner_run_id": owner_run_id,
                "attempt": 0,
                "phase": RECOVERY_PHASES[0],
                "phase_outputs": {},
                "lease_expires_at": (
                    current
                    + dt.timedelta(minutes=RECOVERY_LEASE_MINUTES)
                ).isoformat(),
                "next_retry_at": None,
                "last_failure": None,
                "last_artifact": None,
                "external_blockers": [],
                "incident_stage": "repairing",
                "incident_history": [migration_event],
                "idempotency_keys": [],
                "created_at": current.isoformat(),
                "legacy_v1_state_path": str(legacy_path.resolve()),
                "legacy_v1_state_sha256": legacy_sha256,
                "recovery_control_freeze": recovery_control_freeze,
            }
            run_root = incident_root / next_run
            _write_recovery_state(state_path, state)
            _append_recovery_event(
                incident_root,
                {
                    **migration_event,
                    "incident_id": incident_id,
                },
            )
        elif state_error is not None:
            fail_closed("persisted recovery state is malformed")
            _append_recovery_event(incident_root, {"event": "corrupt_state", "incident_id": incident_id, "at": current.isoformat()})
            return {"status": "corrupt_state", "incident_id": incident_id, "phase": None, "failure": _recovery_failure("permanent_integrity", "persisted recovery state is malformed")}
        if state is None:
            recovery_control_freeze = _establish_recovery_control_freeze(
                control_path,
                incident_id=incident_id,
                recovery_run_id=recovery_run_id,
                now=current,
            )
            state = {
                "schema_version": "tradingagents.self_heal_recovery.v2",
                "incident_id": incident_id,
                "bindings": canonical_bindings,
                "recovery_run_id": recovery_run_id,
                "owner_role": owner_role,
                "owner_run_id": owner_run_id,
                "attempt": 0,
                "phase": RECOVERY_PHASES[0],
                "phase_outputs": {},
                "lease_expires_at": (current + dt.timedelta(minutes=RECOVERY_LEASE_MINUTES)).isoformat(),
                "next_retry_at": None,
                "last_failure": None,
                "last_artifact": None,
                "external_blockers": [],
                "incident_stage": "repairing",
                "incident_history": [{"event": "recovery_opened", "at": current.isoformat()}],
                "idempotency_keys": [],
                "created_at": current.isoformat(),
                "recovery_control_freeze": recovery_control_freeze,
            }
            _append_recovery_event(incident_root, {"event": "recovery_opened", "incident_id": incident_id, "owner_run_id": owner_run_id, "at": current.isoformat()})
        if lock_status == "stale_takeover":
            state["incident_history"].append({"event": "lock_stale_takeover", "at": current.isoformat(), "owner_run_id": owner_run_id})
            _append_recovery_event(incident_root, {"event": "lock_stale_takeover", "incident_id": incident_id, "owner_run_id": owner_run_id, "at": current.isoformat()})
        if state.get("bindings") != canonical_bindings or (state.get("recovery_run_id") != recovery_run_id and state.get("parent_recovery_run_id") != recovery_run_id):
            fail_closed("persisted recovery identity mismatch")
            return {"status": "identity_mismatch_frozen", "incident_id": incident_id, "phase": state.get("phase")}
        run_root = incident_root / str(state["recovery_run_id"])
        if not _path_under(run_root, root):
            fail_closed("persisted recovery run path escapes root")
            return {
                "status": "corrupt_state",
                "incident_id": incident_id,
                "phase": None,
                "failure": _recovery_failure(
                    "permanent_integrity",
                    "persisted recovery run path escapes root",
                ),
            }
        prior_failure = state.get("last_failure") or {}
        if prior_failure.get("kind") == "transient_exhausted" and state.get("follow_on_required") is True:
            not_before = _parse_datetime(state.get("follow_on_not_before"))
            if not_before is not None and not_before > current:
                fail_closed(
                    "recovery follow-on is not ready",
                    persisted_state=state,
                )
                return {"status": "frozen", "incident_id": incident_id, "phase": state.get("phase"), "failure": prior_failure}
            parent_run = str(state.get("parent_recovery_run_id") or recovery_run_id)
            follow_count = int(state.get("follow_on_count") or 0) + 1
            next_run = f"{parent_run}-follow-{follow_count}"
            if not is_safe_incident_id(next_run):
                fail_closed("unsafe follow-on recovery run")
                return {"status": "corrupt_state", "incident_id": incident_id, "phase": None, "failure": _recovery_failure("permanent_integrity", "unsafe follow-on recovery run")}
            state.update(
                {
                    "parent_recovery_run_id": parent_run,
                    "recovery_run_id": next_run,
                    "follow_on_count": follow_count,
                    "follow_on_required": False,
                    "follow_on_not_before": None,
                    "attempt": 0,
                    "phase": RECOVERY_PHASES[0],
                    "phase_outputs": {},
                    "last_failure": None,
                    "last_artifact": None,
                    "next_retry_at": None,
                }
            )
            state.pop("rearm_intent", None)
            state.pop("verifier_run_id", None)
            state.pop("promotion_commit_intent", None)
            state.pop("promotion_stage_request", None)
            state["recovery_control_freeze"] = (
                _establish_recovery_control_freeze(
                    control_path,
                    incident_id=incident_id,
                    recovery_run_id=next_run,
                    now=current,
                )
            )
            run_root = incident_root / next_run
            state["incident_history"].append({"event": "follow_on_opened", "at": current.isoformat(), "recovery_run_id": next_run})
            _append_recovery_event(incident_root, {"event": "follow_on_opened", "incident_id": incident_id, "recovery_run_id": next_run, "at": current.isoformat()})
        completed_keys = set(state.get("idempotency_keys") or [])
        if idempotency_key and idempotency_key in completed_keys:
            fail_closed(
                "duplicate recovery delivery",
                persisted_state=state,
            )
            return {"status": "duplicate", "incident_id": incident_id, "phase": state.get("phase")}
        if (
            state.get("phase") == "monitoring"
            and set(state.get("phase_outputs", {})) == set(RECOVERY_PHASES)
        ):
            fail_closed(
                "completed recovery monitoring",
                persisted_state=state,
            )
            return {
                "status": "monitoring",
                "incident_id": incident_id,
                "phase": "monitoring",
                "recovery_run_id": state["recovery_run_id"],
            }
        lease = _parse_datetime(state.get("lease_expires_at"))
        existing_owner = state.get("owner_run_id")
        if existing_owner != owner_run_id and lease is not None and lease > current:
            fail_closed(
                "different recovery owner remains active",
                persisted_state=state,
            )
            return {"status": "owner_active", "incident_id": incident_id, "phase": state.get("phase"), "owner_run_id": existing_owner}
        if existing_owner != owner_run_id:
            state["owner_run_id"] = owner_run_id
            state["owner_role"] = owner_role
            state["incident_history"].append({"event": "lease_taken_over", "at": current.isoformat(), "from_owner_run_id": existing_owner, "to_owner_run_id": owner_run_id})
            _append_recovery_event(incident_root, {"event": "lease_taken_over", "incident_id": incident_id, "at": current.isoformat(), "owner_run_id": owner_run_id})
        state["lease_expires_at"] = (current + dt.timedelta(minutes=RECOVERY_LEASE_MINUTES)).isoformat()

        def active_task5_rearm() -> bool:
            return _active_rearm_matches_intent(
                state,
                control_path=control_path,
                now=current,
                idempotency_key=idempotency_key,
            )

        def adopt_active_task5_rearm(phase_path: Path) -> dict[str, str]:
            control_state, control_issues = load_live_control_state(
                control_path,
                now=current,
            )
            if (
                control_state is None
                or control_issues
                or not active_task5_rearm()
            ):
                raise ValueError(
                    "rearm exception has no exact active Task 5 receipt"
                )
            receipt_ref = {
                "receipt_path": control_state["recovery_receipt_path"],
                "receipt_sha256": control_state["recovery_receipt_sha256"],
            }
            publish_rearm_receipt(
                receipt_ref,
                receipt_dir,
                now=current,
            )
            if phase_path.exists():
                record = _phase_record(phase_path)
            else:
                recovered_packet = _canonical_packet(
                    {
                        "kind": "verified_rearm_result",
                        **receipt_ref,
                        "can_submit_orders": False,
                        "recovered_after_exception": True,
                    },
                    canonical_bindings,
                    current,
                )
                recovered_packet.update(
                    {
                        "phase": "rearm",
                        "recovery_run_id": state["recovery_run_id"],
                        "owner_run_id": state["owner_run_id"],
                        "owner_role": state["owner_role"],
                        "schema_version": (
                            "tradingagents.recovery_phase.v1"
                        ),
                    }
                )
                record = _write_phase_packet(
                    phase_path,
                    recovered_packet,
                )
            candidate_outputs = {
                **state["phase_outputs"],
                "rearm": record,
            }
            if (
                not _valid_phase_record(record)
                or not _valid_phase_packet(
                    phase_path,
                    "rearm",
                    canonical_bindings,
                    state=state,
                    phase_outputs=candidate_outputs,
                    control_path=control_path,
                    now=current,
                    idempotency_key=idempotency_key,
                )
            ):
                raise ValueError(
                    "exact active rearm result packet is invalid"
                )
            return record

        def require_recovery_freeze() -> None:
            if not active_task5_rearm():
                _assert_recovery_control_frozen(
                    state,
                    control_path=control_path,
                    now=current,
                )

        try:
            require_recovery_freeze()
        except (OSError, ValueError) as error:
            state["last_failure"] = _recovery_failure(
                "permanent_integrity",
                str(error),
            )
            state["incident_stage"] = "repairing"
            _write_recovery_state(state_path, state)
            _record_recovery_incident(root, state, now=current)
            return {
                "status": "frozen",
                "incident_id": incident_id,
                "phase": state.get("phase"),
                "failure": state["last_failure"],
            }
        retry_at = _parse_datetime(state.get("next_retry_at"))
        if retry_at is not None and retry_at > current:
            _write_recovery_state(state_path, state)
            _record_recovery_incident(root, state, now=current)
            return {"status": "retry_scheduled", "incident_id": incident_id, "phase": state.get("phase"), "next_retry_at": state["next_retry_at"]}
        prior_failure = state.get("last_failure") or {}
        if prior_failure.get("kind") in {"permanent_integrity", "forbidden_effect", "external_blocked", "transient_exhausted"}:
            if state.get("phase") == "rearm" and active_task5_rearm():
                state["last_failure"] = None
                state["next_retry_at"] = None
                state["external_blockers"] = []
                state["incident_history"].append(
                    {
                        "event": (
                            "terminal_failure_cleared_for_exact_rearm"
                        ),
                        "phase": "rearm",
                        "at": current.isoformat(),
                    }
                )
                _append_recovery_event(
                    incident_root,
                    {
                        "event": (
                            "terminal_failure_cleared_for_exact_rearm"
                        ),
                        "incident_id": incident_id,
                        "phase": "rearm",
                        "at": current.isoformat(),
                    },
                )
            else:
                return {
                    "status": "external_blocked" if prior_failure.get("kind") == "external_blocked" else "frozen",
                    "incident_id": incident_id,
                    "phase": state.get("phase"),
                    "failure": state.get("last_failure"),
                }
        state["attempt"] = int(state.get("attempt", 0)) + 1
        state["next_retry_at"] = None
        _append_recovery_event(incident_root, {"event": "attempt_started", "incident_id": incident_id, "attempt": state["attempt"], "phase": state.get("phase"), "at": current.isoformat()})

        for phase in RECOVERY_PHASES:
            try:
                require_recovery_freeze()
            except (OSError, ValueError) as error:
                state["last_failure"] = _recovery_failure(
                    "permanent_integrity",
                    str(error),
                )
                state["incident_stage"] = "repairing"
                _write_recovery_state(state_path, state)
                _record_recovery_incident(root, state, now=current)
                return {
                    "status": "frozen",
                    "incident_id": incident_id,
                    "phase": phase,
                    "failure": state["last_failure"],
                }
            record = state["phase_outputs"].get(phase)
            if record is not None:
                if (
                    not _path_under(Path(record["path"]), run_root)
                    or not _valid_phase_record(record)
                    or not _valid_phase_packet(
                        Path(record["path"]),
                        phase,
                        canonical_bindings,
                        state=state,
                        phase_outputs=state["phase_outputs"],
                        control_path=control_path,
                        now=current,
                        idempotency_key=idempotency_key,
                    )
                ):
                    if phase == "rearm":
                        _freeze_recovery_control(
                            control_path,
                            reason="tampered completed rearm artifact",
                        )
                    state["last_failure"] = _recovery_failure("permanent_integrity", f"tampered completed artifact for {phase}")
                    state["incident_stage"] = "repairing"
                    _write_recovery_state(state_path, state)
                    _append_recovery_event(incident_root, {"event": "artifact_tampered", "incident_id": incident_id, "phase": phase, "at": current.isoformat()})
                    _record_recovery_incident(root, state, now=current)
                    return {"status": "frozen", "incident_id": incident_id, "phase": phase, "failure": state["last_failure"]}
                continue
            phase_path = _phase_path(run_root, phase)
            # A crash after fsync but before state replacement leaves a valid,
            # deterministic orphan packet. Recover it rather than rerunning the
            # external adapter and duplicating a broker read or verifier pass.
            if phase_path.exists():
                if not _valid_phase_packet(
                    phase_path,
                    phase,
                    canonical_bindings,
                    state=state,
                    phase_outputs=state["phase_outputs"],
                    control_path=control_path,
                    now=current,
                    idempotency_key=idempotency_key,
                ):
                    if phase == "rearm":
                        _freeze_recovery_control(
                            control_path,
                            reason="malformed orphan rearm artifact",
                        )
                    state["last_failure"] = _recovery_failure("permanent_integrity", f"malformed orphan artifact for {phase}")
                    _write_recovery_state(state_path, state)
                    _append_recovery_event(incident_root, {"event": "orphan_artifact_invalid", "incident_id": incident_id, "phase": phase, "at": current.isoformat()})
                    _record_recovery_incident(root, state, now=current)
                    return {"status": "frozen", "incident_id": incident_id, "phase": phase, "failure": state["last_failure"]}
                state["phase_outputs"][phase] = _phase_record(phase_path)
                state["last_artifact"] = state["phase_outputs"][phase]
                state["phase"] = RECOVERY_PHASES[min(RECOVERY_PHASES.index(phase) + 1, len(RECOVERY_PHASES) - 1)]
                _write_recovery_state(state_path, state)
                continue
            state["phase"] = phase
            state["incident_history"].append({"event": "phase_started", "phase": phase, "at": current.isoformat()})
            _write_recovery_state(state_path, state)
            _append_recovery_event(incident_root, {"event": "phase_started", "incident_id": incident_id, "phase": phase, "attempt": state["attempt"], "at": current.isoformat()})
            try:
                if phase == "ready_incident":
                    root_cause_resolution = _ready_root_cause_resolution(
                        state["phase_outputs"],
                        bindings=canonical_bindings,
                    )
                    if root_cause_resolution is None:
                        raise ValueError(
                            "ready incident lacks verified reconciliation resolution"
                        )
                    packet: Mapping[str, Any] = {
                        "schema_version": "tradingagents.incident.v1",
                        "stage": "ready",
                        "history": [{"event": "transitioned", "to_stage": "ready", "at": current.isoformat()}],
                        "evidence_refs": [
                            state["phase_outputs"][name]["path"]
                            for name in RECOVERY_PHASES[:5]
                        ],
                        "repairer_run_id": owner_run_id,
                        "repairer_role_id": rearm_request_owner,
                        "root_cause_resolved": True,
                        "root_cause_resolution": root_cause_resolution,
                        "external_blockers": [],
                    }
                elif phase == "manifest":
                    source_names = {"incident": "ready_incident", "reconciliation": "reconcile", "promotion": "sync_promotion", "focused": "focused_verify"}
                    focused_packet = json.loads(Path(state["phase_outputs"]["focused_verify"]["path"]).read_text(encoding="utf-8"))
                    ready_packet = json.loads(
                        Path(
                            state["phase_outputs"]["ready_incident"]["path"]
                        ).read_text(encoding="utf-8")
                    )
                    packet = {
                        "schema_version": "tradingagents.recovery_manifest.v1",
                        "kind": "verified_recovery_manifest",
                        "packet_sha256": {name: state["phase_outputs"][source]["sha256"] for name, source in source_names.items()},
                        "packet_paths": {name: state["phase_outputs"][source]["path"] for name, source in source_names.items()},
                        "repairer_run_id": ready_packet.get("repairer_run_id"),
                        "repairer_role_id": ready_packet.get("repairer_role_id"),
                        "verifier_run_id": focused_packet.get("verifier_run_id"),
                        "verifier_role_id": focused_packet.get("verifier_role_id"),
                    }
                elif phase == "rearm":
                    source_names = {"incident": "ready_incident", "reconciliation": "reconcile", "promotion": "sync_promotion", "focused": "focused_verify"}
                    paths = {name: state["phase_outputs"][source]["path"] for name, source in source_names.items()}
                    prior_intent = state.get("rearm_intent")
                    if isinstance(prior_intent, Mapping):
                        control_state, _control_issues = load_live_control_state(
                            control_path, now=current
                        )
                        if (
                            control_state is not None
                            and control_state.get("frozen") is False
                        ):
                            if not _active_rearm_matches_intent(
                                state,
                                control_path=control_path,
                                now=current,
                                idempotency_key=idempotency_key,
                            ):
                                _freeze_recovery_control(
                                    control_path,
                                    reason="active receipt does not match persisted intent",
                                )
                                raise ValueError("rearm intent does not match active receipt")
                            publish_rearm_receipt(
                                {
                                    "receipt_path": control_state[
                                        "recovery_receipt_path"
                                    ],
                                    "receipt_sha256": control_state[
                                        "recovery_receipt_sha256"
                                    ],
                                },
                                receipt_dir,
                                now=current,
                            )
                            packet = {"kind": "verified_rearm_result", "receipt_path": control_state["recovery_receipt_path"], "receipt_sha256": control_state["recovery_receipt_sha256"], "can_submit_orders": False, "recovered_after_crash": True}
                            packet = _canonical_packet(packet, canonical_bindings, current)
                            packet.update({"phase": phase, "recovery_run_id": state["recovery_run_id"], "owner_run_id": state["owner_run_id"], "owner_role": state["owner_role"], "schema_version": "tradingagents.recovery_phase.v1"})
                            record = _write_phase_packet(phase_path, packet)
                            state["phase_outputs"][phase] = record
                            state["last_artifact"] = record
                            state["phase"] = "monitoring"
                            _write_recovery_state(state_path, state)
                            continue
                        if (
                            control_state is None
                            or control_state.get("frozen") is not True
                            or not _rearm_intent_matches_current(
                                state,
                                control_path=control_path,
                                idempotency_key=idempotency_key,
                            )
                        ):
                            raise ValueError(
                                "rearm intent conflicts with current recovery"
                            )
                    focused = json.loads(Path(paths["focused"]).read_text(encoding="utf-8"))
                    ready = json.loads(Path(paths["incident"]).read_text(encoding="utf-8"))
                    verifier_run_id = focused.get("verifier_run_id")
                    verifier_role_id = focused.get("verifier_role_id")
                    repairer_run_id = ready.get("repairer_run_id")
                    repairer_role_id = ready.get("repairer_role_id")
                    if (
                        not is_safe_incident_id(verifier_run_id)
                        or not is_safe_incident_id(verifier_role_id)
                        or not is_safe_incident_id(repairer_run_id)
                        or not is_safe_incident_id(repairer_role_id)
                        or verifier_run_id.casefold() == repairer_run_id.casefold()
                        or verifier_role_id != rearm_issue_owner
                        or repairer_role_id != rearm_request_owner
                    ):
                        raise ValueError(
                            "recovery roles do not match rearm authority"
                        )
                    state["verifier_run_id"] = verifier_run_id
                    evidence, evidence_issues = load_recovery_evidence(
                        incident_path=paths["incident"],
                        reconciliation_path=paths["reconciliation"],
                        promotion_sync_path=paths["promotion"],
                        focused_proof_path=paths["focused"],
                        recovery_manifest_path=state["phase_outputs"]["manifest"]["path"],
                        repairer_run_id=repairer_run_id,
                        verifier_run_id=verifier_run_id,
                        now=current,
                    )
                    if evidence is None or evidence_issues:
                        raise ValueError("Task 5 evidence rejected: " + "; ".join(evidence_issues))
                    state["rearm_intent"] = {
                        "incident_id": incident_id,
                        "manifest_path": state["phase_outputs"]["manifest"]["path"],
                        "manifest_sha256": state["phase_outputs"]["manifest"]["sha256"],
                        "control_path": str(Path(control_path).resolve()),
                        "idempotency_key": idempotency_key,
                        "source_packet_paths": dict(evidence.source_packet_paths),
                        "source_packet_sha256": dict(evidence.source_packet_sha256),
                        "repairer_run_id": evidence.repairer_run_id,
                        "verifier_run_id": evidence.verifier_run_id,
                        "control_preimage_sha256": state[
                            "recovery_control_freeze"
                        ]["sha256"],
                    }
                    _write_recovery_state(state_path, state)
                    if callable(fault_hook):
                        fault_hook({"boundary": "before_rearm_call", "phase": phase})
                    result = rearm(
                        evidence=evidence,
                        control_path=control_path,
                        receipt_dir=receipt_dir,
                        ttl_minutes=90,
                        now=current,
                        expected_control_preimage_sha256=state[
                            "recovery_control_freeze"
                        ]["sha256"],
                    )
                    if callable(fault_hook):
                        fault_hook({"boundary": "after_rearm_return", "phase": phase})
                    packet = {"kind": "verified_rearm_result", "receipt_path": result["receipt_path"], "receipt_sha256": result["receipt_sha256"], "can_submit_orders": False}
                else:
                    adapter = adapters.get(phase)
                    if not callable(adapter):
                        raise ValueError(f"missing recovery adapter for {phase}")
                    adapter_arguments: dict[str, Any] = {
                        "incident_id": incident_id,
                        "bindings": dict(canonical_bindings),
                        "owner_run_id": owner_run_id,
                        "owner_role": owner_role,
                        "recovery_run_id": state["recovery_run_id"],
                        "phase": phase,
                        "phase_outputs": dict(state["phase_outputs"]),
                        "generated_at": current.isoformat(),
                    }
                    if phase == "sync_promotion":
                        staging_dir = run_root / "staging"

                        def persist_promotion_stage_request(
                            request: Mapping[str, Any],
                        ) -> None:
                            existing_request = state.get(
                                "promotion_stage_request"
                            )
                            if (
                                existing_request is not None
                                and existing_request != request
                            ):
                                raise ValueError(
                                    "persisted promotion stage request mismatch"
                                )
                            state["promotion_stage_request"] = dict(request)
                            _write_recovery_state(state_path, state)

                        def persist_promotion_commit_intent(
                            intent: Mapping[str, Any],
                        ) -> None:
                            existing_intent = state.get("promotion_commit_intent")
                            if (
                                existing_intent is not None
                                and existing_intent != intent
                            ):
                                raise ValueError(
                                    "persisted promotion commit intent mismatch"
                                )
                            state["promotion_commit_intent"] = dict(intent)
                            _write_recovery_state(state_path, state)

                        def assert_promotion_control_frozen() -> None:
                            _assert_recovery_control_frozen(
                                state,
                                control_path=control_path,
                                now=current,
                            )

                        adapter_arguments.update(
                            {
                                "run_root": str(run_root),
                                "staging_dir": str(staging_dir),
                                "promotion_stage_request": state.get(
                                    "promotion_stage_request"
                                ),
                                "_persist_promotion_stage_request": persist_promotion_stage_request,
                                "_persist_promotion_commit_intent": persist_promotion_commit_intent,
                                "_assert_recovery_control_frozen": assert_promotion_control_frozen,
                                "_transaction_fault_hook": fault_hook,
                            }
                        )
                        if callable(fault_hook):
                            fault_hook(
                                {
                                    "boundary": "before_promotion_adapter",
                                    "phase": phase,
                                }
                            )
                    packet = _adapter_packet(
                        adapter(adapter_arguments),
                        phase=phase,
                    )
                    if phase == "sync_promotion" and callable(fault_hook):
                        fault_hook(
                            {
                                "boundary": "after_promotion_adapter_return",
                                "phase": phase,
                            }
                        )
                packet = _canonical_packet(packet, canonical_bindings, current)
                packet.update(
                    {
                        "phase": phase,
                        "recovery_run_id": state["recovery_run_id"],
                        "owner_run_id": state["owner_run_id"],
                        "owner_role": state["owner_role"],
                        "schema_version": packet.get("schema_version", "tradingagents.recovery_phase.v1"),
                    }
                )
                record = _write_phase_packet(phase_path, packet)
                candidate_outputs = {
                    **state["phase_outputs"],
                    phase: record,
                }
                if not _valid_phase_packet(
                    phase_path,
                    phase,
                    canonical_bindings,
                    state=state,
                    phase_outputs=candidate_outputs,
                    control_path=control_path,
                    now=current,
                    idempotency_key=idempotency_key,
                ):
                    raise ValueError(f"semantic validation failed for {phase}")
                if callable(fault_hook):
                    fault_hook({"boundary": "after_phase_fsync", "phase": phase, "path": str(phase_path)})
            except Exception as error:
                failure_error = error
                if phase == "rearm":
                    try:
                        record = adopt_active_task5_rearm(phase_path)
                    except Exception as adoption_error:
                        fail_closed(
                            "rearm phase failed without an exact active receipt"
                        )
                        failure_error = adoption_error
                    else:
                        state["phase_outputs"][phase] = record
                        state["last_artifact"] = record
                        state["phase"] = "monitoring"
                        state["last_failure"] = None
                        state["next_retry_at"] = None
                        state["external_blockers"] = []
                        state["incident_history"].append(
                            {
                                "event": "active_rearm_adopted",
                                "phase": phase,
                                "at": current.isoformat(),
                                **record,
                            }
                        )
                        continue
                failure = _failure_from_exception(failure_error)
                state["last_failure"] = failure
                state["incident_history"].append({"event": "phase_failed", "phase": phase, "failure": failure, "at": current.isoformat()})
                if failure["external"]:
                    state["incident_stage"] = "external_blocked"
                    state["external_blockers"] = [failure["detail"]]
                elif failure["kind"] == "transient" and state["attempt"] < RECOVERY_MAX_ATTEMPTS:
                    state["next_retry_at"] = (current + dt.timedelta(seconds=RECOVERY_BACKOFF_SECONDS[state["attempt"]])).isoformat()
                else:
                    state["incident_stage"] = "repairing"
                    if failure["kind"] == "transient":
                        state["last_failure"] = _recovery_failure("transient_exhausted", failure["detail"])
                        state["next_retry_at"] = None
                        state["follow_on_required"] = True
                        state["follow_on_not_before"] = (current + dt.timedelta(seconds=RECOVERY_BACKOFF_SECONDS[-1])).isoformat()
                _write_recovery_state(state_path, state)
                _append_recovery_event(incident_root, {"event": "phase_failed", "incident_id": incident_id, "phase": phase, "attempt": state["attempt"], "failure": state["last_failure"], "at": current.isoformat()})
                _record_recovery_incident(root, state, now=current)
                return {"status": "external_blocked" if failure["external"] else "frozen", "incident_id": incident_id, "phase": phase, "failure": state["last_failure"], "next_retry_at": state.get("next_retry_at")}
            state["phase_outputs"][phase] = record
            state["last_artifact"] = record
            state["incident_history"].append({"event": "phase_completed", "phase": phase, "at": current.isoformat(), **record})
            next_index = RECOVERY_PHASES.index(phase) + 1
            state["phase"] = RECOVERY_PHASES[next_index] if next_index < len(RECOVERY_PHASES) else "monitoring"
            _write_recovery_state(state_path, state)
            _append_recovery_event(incident_root, {"event": "phase_completed", "incident_id": incident_id, "phase": phase, "attempt": state["attempt"], "at": current.isoformat(), **record})

        state["incident_stage"] = "monitoring"
        state["incident_history"].append({"event": "transitioned", "from_stage": "rearmed", "to_stage": "monitoring", "at": current.isoformat()})
        state["phase"] = "monitoring"
        state["last_failure"] = None
        if idempotency_key:
            state["idempotency_keys"] = sorted(set(state.get("idempotency_keys") or []) | {idempotency_key})
        _write_recovery_state(state_path, state)
        _append_recovery_event(incident_root, {"event": "recovery_monitoring", "incident_id": incident_id, "at": current.isoformat()})
        _record_recovery_incident(root, state, now=current)
        return {"status": "monitoring", "incident_id": incident_id, "phase": "monitoring", "recovery_run_id": state["recovery_run_id"]}
    finally:
        _release_recovery_lock(lock_path, descriptor, lock_token)


# Clear aliases make the coordinator discoverable to callers that describe the
# same operation in operational rather than implementation language.
run_owned_recovery = coordinate_verified_recovery
execute_verified_recovery = coordinate_verified_recovery
ALLOWED_SELF_HEAL_VERIFY_COMMANDS = {
    CONTEXT_SNAPSHOT_COMMAND: [
        "uv",
        "run",
        "--no-sync",
        "python",
        "scripts/automation_context_snapshot.py",
        "--write",
    ],
    MODEL_ROUTE_PROBE_COMMAND: [
        "uv",
        "run",
        "--no-sync",
        "python",
        "-m",
        "cli.main",
        "research",
        "automation-orchestration-plan",
        "--candidate-symbols",
        "XOM",
        "--no-research-context",
        "--output-dir",
        "results/research_batches/model_route_health",
        "--model-telemetry-dir",
        "results/model_telemetry",
        "--json-output",
    ],
    MODEL_TELEMETRY_REPORT_COMMAND: [
        "uv",
        "run",
        "--no-sync",
        "python",
        "-m",
        "cli.main",
        "research",
        "model-telemetry-report",
        "--json-output",
    ],
    AGENT_LEDGER_SUMMARY_COMMAND: [
        "uv",
        "run",
        "--no-sync",
        "python",
        "-m",
        "cli.main",
        "research",
        "agent-ledger-summary",
        "--json-output",
    ],
    LOSS_REVIEW_EVIDENCE_COMMAND: [
        "uv",
        "run",
        "--no-sync",
        "python",
        "-m",
        "cli.main",
        "research",
        "loss-review-evidence",
        "--json-output",
    ],
    PREOPEN_VALIDATION_COMMAND: [
        "uv",
        "run",
        "--no-sync",
        "python",
        "-m",
        "cli.main",
        "alpaca",
        "preopen-validation",
        "--json-output",
    ],
    "uv run --no-sync python -m cli.main research automation-health-audit --json-output": [
        "uv",
        "run",
        "--no-sync",
        "python",
        "-m",
        "cli.main",
        "research",
        "automation-health-audit",
        "--json-output",
    ],
    "uv run --no-sync python -m cli.main research night-shift-patrol --json-output": [
        "uv",
        "run",
        "--no-sync",
        "python",
        "-m",
        "cli.main",
        "research",
        "night-shift-patrol",
        "--json-output",
    ],
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _coerce_utc_datetime(value: dt.datetime | None = None) -> dt.datetime:
    if value is None:
        return dt.datetime.now(tz=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_datetime(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return _coerce_utc_datetime(parsed)


def _severity(reason: str) -> str:
    if reason in HIGH_REASONS:
        return "high"
    if reason in MEDIUM_REASONS:
        return "medium"
    if reason in LOW_REASONS:
        return "low"
    return "info"


def _max_severity(triggers: list[dict[str, Any]]) -> str:
    order = {"none": 0, "info": 1, "low": 2, "medium": 3, "high": 4}
    severity = "none"
    for trigger in triggers:
        candidate = str(trigger.get("severity") or "info")
        if order.get(candidate, 0) > order.get(severity, 0):
            severity = candidate
    return severity


def _signature(parts: list[str]) -> str:
    material = "|".join(parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _trigger_signature(trigger: Mapping[str, Any]) -> str:
    return _signature(
        [
            str(trigger.get("label") or ""),
            str(trigger.get("reason") or ""),
            str(trigger.get("path") or ""),
            str(trigger.get("summary") or trigger.get("meaning") or ""),
            ",".join(_trigger_effects(trigger)),
        ]
    )


def _compact_text(value: Any, *, limit: int = 220) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _flag_triggers(flags_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    triggers: list[dict[str, Any]] = []
    for item in flags_payload.get("flags") or []:
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("label") or "")
        if label in EXCLUDED_LABELS:
            continue
        reason = str(item.get("reason") or "")
        if reason not in SELF_HEAL_REASONS:
            continue
        triggers.append(
            {
                "source": "compact_context_flag",
                "label": label,
                "reason": reason,
                "severity": _severity(reason),
                "path": item.get("path"),
                "meaning": item.get("meaning"),
            }
        )
    return triggers


def _plan_flag_signals(flags_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for item in flags_payload.get("flags") or []:
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("label") or "")
        if label in EXCLUDED_LABELS:
            continue
        reason = str(item.get("reason") or "")
        if reason not in PLAN_REASONS:
            continue
        signals.append(
            {
                "source": "compact_context_flag",
                "label": label,
                "reason": reason,
                "severity": _severity(reason),
                "path": item.get("path"),
                "meaning": item.get("meaning"),
                "symbol": item.get("symbol"),
                "broker_account": item.get("broker_account"),
                "environment": item.get("environment"),
                "source_revision": item.get("source_revision"),
                "recovery_context": item.get("recovery_context"),
                "requested_effects": list(item.get("requested_effects") or []),
                "forbidden_effects": list(item.get("forbidden_effects") or []),
            }
        )
    return signals


def _packet_triggers(summary_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    triggers: list[dict[str, Any]] = []
    for packet in summary_payload.get("latest_packets") or []:
        if not isinstance(packet, Mapping):
            continue
        label = str(packet.get("label") or "")
        if label in EXCLUDED_LABELS:
            continue
        path = packet.get("path")
        drilldown = packet.get("drilldown_reasons") or []
        if isinstance(drilldown, list):
            for reason in drilldown:
                reason_text = str(reason)
                if reason_text in SELF_HEAL_REASONS:
                    triggers.append(
                        {
                            "source": "latest_packet_drilldown",
                            "label": label,
                            "reason": reason_text,
                            "severity": _severity(reason_text),
                            "path": path,
                            "generated_at": packet.get("generated_at"),
                            "summary": _compact_text(packet.get("next_open")),
                        }
                    )
        failed_checks = packet.get("failed_checks")
        if isinstance(failed_checks, list) and failed_checks:
            failed_summary = ", ".join(str(item) for item in failed_checks[:5])
            severity = "medium"
            if label in {"hourly", "execution_board_review"}:
                severity = "high"
            if label == "overnight_verification" and set(map(str, failed_checks)) <= {"simulated_preopen_validation"}:
                severity = "low"
            triggers.append(
                {
                    "source": "latest_packet_failed_checks",
                    "label": label,
                    "reason": "failed_checks",
                    "severity": severity,
                    "path": path,
                    "summary": failed_summary,
                }
            )
        for key in ("issue_count", "blocker_count", "unresolved_blockers", "error_count", "failed_command_count"):
            value = packet.get(key)
            if isinstance(value, int) and value > 0:
                triggers.append(
                    {
                        "source": "latest_packet_counter",
                        "label": label,
                        "reason": key,
                        "severity": "high" if "blocker" in key or "failed" in key else "medium",
                        "path": path,
                        "count": value,
                    }
                )
    return triggers


def _plan_packet_signals(summary_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for packet in summary_payload.get("latest_packets") or []:
        if not isinstance(packet, Mapping):
            continue
        label = str(packet.get("label") or "")
        if label in EXCLUDED_LABELS:
            continue
        path = packet.get("path")
        for reason in packet.get("drilldown_reasons") or []:
            reason_text = str(reason)
            if reason_text in PLAN_REASONS:
                signals.append(
                    {
                        "source": "latest_packet_drilldown",
                        "label": label,
                        "reason": reason_text,
                        "severity": _severity(reason_text),
                        "path": path,
                        "generated_at": packet.get("generated_at"),
                        "summary": _compact_text(packet.get("next_open")),
                    }
                )
        failed_checks = packet.get("failed_checks")
        if isinstance(failed_checks, list) and failed_checks:
            failed_summary = ", ".join(str(item) for item in failed_checks[:5])
            severity = "high" if label in ORDER_ADJACENT_LABELS else "medium"
            if label == "overnight_verification" and set(map(str, failed_checks)) <= {"simulated_preopen_validation"}:
                severity = "low"
            signals.append(
                {
                    "source": "latest_packet_failed_checks",
                    "label": label,
                    "reason": "failed_checks",
                    "severity": severity,
                    "path": path,
                    "summary": failed_summary,
                }
            )
        for key in ("issue_count", "blocker_count", "unresolved_blockers", "error_count", "failed_command_count"):
            value = packet.get(key)
            if isinstance(value, int) and value > 0:
                signals.append(
                    {
                        "source": "latest_packet_counter",
                        "label": label,
                        "reason": key,
                        "severity": "high" if "blocker" in key or "failed" in key else "medium",
                        "path": path,
                        "count": value,
                    }
                )
    return signals


def _dedupe_triggers(triggers: list[dict[str, Any]], *, max_triggers: int) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for trigger in triggers:
        key = (
            str(trigger.get("label") or ""),
            str(trigger.get("reason") or ""),
            str(trigger.get("path") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(trigger)
        if len(unique) >= max_triggers:
            break
    return unique


def _signature_state_path_from_output_dir(output_dir: str | Path) -> Path:
    out_dir = Path(output_dir)
    if out_dir.name == "plans":
        out_dir = out_dir.parent
    return out_dir / DEFAULT_SIGNATURE_STATE_NAME


def _default_signature_state_path(repo_root: Path) -> Path:
    return repo_root / DEFAULT_OUTPUT_DIR / DEFAULT_SIGNATURE_STATE_NAME


def _load_signature_state(path: str | Path) -> dict[str, Any]:
    payload = _read_json(Path(path))
    signatures = payload.get("signatures")
    if not isinstance(signatures, dict):
        signatures = {}
    return {
        "schema_version": 1,
        "updated_at": payload.get("updated_at"),
        "signatures": signatures,
    }


def _state_record_for_signature(state: Mapping[str, Any], signature: str) -> dict[str, Any] | None:
    signatures = state.get("signatures")
    if not isinstance(signatures, Mapping):
        return None
    record = signatures.get(signature)
    return dict(record) if isinstance(record, Mapping) else None


def _update_signature_state(
    *,
    state_path: str | Path,
    items: list[Mapping[str, Any]],
    event: str,
    now: dt.datetime | None = None,
) -> Path:
    path = Path(state_path)
    state = _load_signature_state(path)
    signatures = dict(state.get("signatures") or {})
    now_text = _coerce_utc_datetime(now).isoformat()
    for item in items:
        signature = str(item.get("root_cause_signature") or "")
        if not signature:
            continue
        record = dict(signatures.get(signature) or {})
        record.setdefault("first_seen_at", now_text)
        record["last_seen_at"] = now_text
        record["last_event"] = event
        record["last_status"] = str(item.get("status") or event)
        record["label"] = item.get("label")
        record["reason"] = item.get("reason")
        record["path"] = item.get("path")
        record["severity"] = item.get("severity")
        if event == "handoff_written":
            record["handoff_count"] = int(record.get("handoff_count") or 0) + 1
        if event == "plan_written":
            record["plan_count"] = int(record.get("plan_count") or 0) + 1
            record["classification"] = item.get("classification")
            record["escalation_required"] = item.get("escalation_required")
        signatures[signature] = record
    state["updated_at"] = now_text
    state["signatures"] = signatures
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _prior_state_records(
    repo_root: Path,
    *,
    state_path: str | Path | None = None,
    statuses: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    resolved_statuses = statuses or {"verified", "escalated", "already_recorded"}
    path = Path(state_path) if state_path is not None else _default_signature_state_path(repo_root)
    state = _load_signature_state(path)
    records: dict[str, dict[str, Any]] = {}
    for signature, record in (state.get("signatures") or {}).items():
        if not isinstance(record, Mapping):
            continue
        if str(record.get("last_status") or "") in resolved_statuses:
            records[str(signature)] = dict(record)
    return records


def _prior_state_signatures(
    repo_root: Path,
    *,
    state_path: str | Path | None = None,
    statuses: set[str] | None = None,
) -> set[str]:
    return set(
        _prior_state_records(
            repo_root,
            state_path=state_path,
            statuses=statuses,
        )
    )


def _annotate_handoff_triggers_with_state(
    triggers: list[dict[str, Any]],
    *,
    state_path: str | Path,
) -> list[dict[str, Any]]:
    state = _load_signature_state(state_path)
    annotated: list[dict[str, Any]] = []
    for trigger in triggers:
        item = dict(trigger)
        signature = _trigger_signature(item)
        prior_record = _state_record_for_signature(state, signature)
        item["root_cause_signature"] = signature
        if prior_record:
            item["prior_state"] = {
                "last_status": prior_record.get("last_status"),
                "last_event": prior_record.get("last_event"),
                "last_seen_at": prior_record.get("last_seen_at"),
                "handoff_count": prior_record.get("handoff_count"),
                "plan_count": prior_record.get("plan_count"),
            }
            item["status"] = "already_recorded"
            item["deduped_prior"] = True
        else:
            item["status"] = "new"
            item["deduped_prior"] = False
        annotated.append(item)
    return annotated


def _trigger_effects(trigger: Mapping[str, Any]) -> list[str]:
    effects: list[str] = []
    for key in ("requested_effects", "forbidden_effects"):
        value = trigger.get(key)
        if isinstance(value, list):
            effects.extend(str(item) for item in value)
        elif isinstance(value, str):
            effects.append(value)
    haystack = " ".join(
        str(trigger.get(key) or "")
        for key in ("label", "reason", "meaning", "summary", "path")
    ).lower()
    effects.extend(effect for effect in FORBIDDEN_EFFECTS if effect.lower() in haystack)
    return sorted(set(effects))


def _is_order_adjacent(trigger: Mapping[str, Any]) -> bool:
    label = str(trigger.get("label") or "")
    reason = str(trigger.get("reason") or "")
    return label in ORDER_ADJACENT_LABELS and reason in {
        "actions",
        "submitted",
        "issues",
        "blocker",
        "blocker_count",
        "issue_count",
        "failed_checks",
        "board_review",
        "candidate_change",
        "abnormal_pl",
        "unexplained_action",
    }


def _prior_plan_signatures(repo_root: Path, output_dir: str | Path | None = None) -> set[str]:
    plan_dir = Path(output_dir) if output_dir is not None else repo_root / DEFAULT_PLAN_OUTPUT_DIR
    latest_path = plan_dir / "latest.json"
    payload = _read_json(latest_path)
    signatures: set[str] = set()
    for item in payload.get("signals") or []:
        if not isinstance(item, Mapping):
            continue
        status = str(item.get("status") or "")
        signature = str(item.get("root_cause_signature") or "")
        if signature and status in {"verified", "escalated"}:
            signatures.add(signature)
    return signatures


def _classify_self_heal_signal(
    trigger: Mapping[str, Any],
    *,
    prior_signatures: set[str],
    prior_state_records: Mapping[str, Mapping[str, Any]] | None = None,
    repo_root: Path | None = None,
    now: dt.datetime | None = None,
    safe_reverify_minutes: int = DEFAULT_SAFE_REVERIFY_MINUTES,
) -> dict[str, Any]:
    label = str(trigger.get("label") or "")
    reason = str(trigger.get("reason") or "")
    signature = _trigger_signature(trigger)
    effects = _trigger_effects(trigger)
    forbidden = [effect for effect in effects if effect in FORBIDDEN_EFFECTS]
    signal: dict[str, Any] = {
        "source": trigger.get("source"),
        "label": label,
        "reason": reason,
        "severity": trigger.get("severity") or _severity(reason),
        "path": trigger.get("path"),
        "summary": _compact_text(trigger.get("summary") or trigger.get("meaning")),
        "symbol": trigger.get("symbol"),
        "broker_account": trigger.get("broker_account"),
        "environment": trigger.get("environment"),
        "source_revision": trigger.get("source_revision"),
        "recovery_context": dict(trigger.get("recovery_context") or {}) if isinstance(trigger.get("recovery_context"), Mapping) else None,
        "count": trigger.get("count"),
        "root_cause_signature": signature,
        "forbidden_effects": list(FORBIDDEN_EFFECTS),
        "observed_effects": effects,
    }
    if forbidden:
        signal.update(
            {
                "classification": "escalate_forbidden_effect",
                "status": "escalated",
                "recommended_action": "manual_codex_review_required",
                "verify_command": None,
                "safe_effects": [],
                "escalation_required": True,
            }
        )
        return signal
    recovery_signal = classify_recovery_signal(trigger)
    if recovery_signal["classification"] == "business_decision_pending":
        decision_root = repo_root or Path(".")
        authenticated = _authenticated_latest_board_decision(
            decision_root, now=now
        )
        if authenticated is not None and not _board_decision_matches_trigger(
            authenticated, trigger, root=decision_root
        ):
            authenticated = None
        common = {
            "owner_role": "portfolio_executive",
            "recipe": None,
            "allowed_effects": ["trade_decision"],
            "safe_effects": [],
            "may_rearm": False,
            "escalation_required": False,
            "decision_reference": authenticated,
        }
        if authenticated is None:
            signal.update(
                {
                    **common,
                    "classification": "business_decision_pending",
                    "status": "retryable",
                    "recommended_action": "await_current_autonomous_portfolio_decision",
                    "verify_command": None,
                }
            )
        elif authenticated["decision"] == "HOLD":
            signal.update(
                {
                    **common,
                    "classification": "resolved_no_action",
                    "status": "resolved_no_action",
                    "recommended_action": "autonomous_hold_recorded_no_execution_action",
                    "verify_command": None,
                }
            )
        elif authenticated["decision"] == "SELL":
            signal.update(
                {
                    **common,
                    "classification": "decision_resolved_execution_pending",
                    "status": "decision_resolved_execution_pending",
                    "recommended_action": "separate_execution_intent_required",
                    "verify_command": None,
                }
            )
        else:
            signal.update(
                {
                    **common,
                    "classification": "business_decision_pending",
                    "status": "retryable",
                    "recommended_action": "await_current_autonomous_portfolio_decision",
                    "verify_command": None,
                }
            )
        return signal
    if recovery_signal["classification"] == "external_blocked":
        signal.update(
            {
                "classification": "external_blocked",
                "status": "external_blocked",
                "recommended_action": "preserve_freeze_and_record_external_authority_dependency",
                "verify_command": None,
                "safe_effects": [],
                "escalation_required": True,
                "owner_role": recovery_signal["owner_role"],
                "recipe": recovery_signal["recipe"],
            }
        )
        return signal
    if recovery_signal["classification"] == "recoverable_integrity":
        signal.update(
            {
                "classification": "recoverable_integrity",
                "status": "owned_recovery_ready",
                "recommended_action": "coordinate_verified_recovery",
                "verify_command": None,
                "safe_effects": list(RECOVERY_EFFECTS),
                "escalation_required": False,
                "owner_role": recovery_signal["owner_role"],
                "recipe": recovery_signal["recipe"],
                "may_rearm": True,
            }
        )
        return signal
    if _is_order_adjacent(trigger):
        signal.update(
            {
                "classification": "escalate_order_adjacent",
                "status": "escalated",
                "recommended_action": "manual_codex_review_required",
                "verify_command": None,
                "safe_effects": [],
                "escalation_required": True,
            }
        )
        return signal
    safe_action = LABEL_SAFE_AUTOFIX_ACTIONS.get((label, reason)) or SAFE_AUTOFIX_ACTIONS.get(reason)
    if safe_action is None:
        signal.update(
            {
                "classification": "observe_only",
                "status": "observed",
                "recommended_action": "write_handoff_if_repeats",
                "verify_command": None,
                "safe_effects": [],
                "escalation_required": False,
            }
        )
        return signal
    prior_record = dict((prior_state_records or {}).get(signature) or {})
    status = "already_recorded" if signature in prior_signatures else "planned"
    reverify_required = False
    if status == "already_recorded" and prior_record:
        last_seen_at = _parse_datetime(prior_record.get("last_seen_at"))
        if last_seen_at is not None:
            reverify_after = dt.timedelta(minutes=max(0, safe_reverify_minutes))
            current_time = _coerce_utc_datetime(now)
            if current_time >= last_seen_at and current_time - last_seen_at >= reverify_after:
                status = "planned"
                reverify_required = True
    signal.update(
        {
            "classification": "safe_autofix",
            "status": status,
            "recommended_action": safe_action["recommended_action"],
            "verify_command": safe_action["verify_command"],
            "safe_effects": safe_action["safe_effects"],
            "escalation_required": False,
        }
    )
    if safe_action.get("execute_commands"):
        signal["execute_commands"] = list(safe_action["execute_commands"])
    if prior_record:
        signal["prior_state"] = {
            "last_status": prior_record.get("last_status"),
            "last_event": prior_record.get("last_event"),
            "last_seen_at": prior_record.get("last_seen_at"),
            "handoff_count": prior_record.get("handoff_count"),
            "plan_count": prior_record.get("plan_count"),
            "classification": prior_record.get("classification"),
        }
    if reverify_required:
        signal["reverify_required"] = True
        signal["reverify_reason"] = "persistent_safe_autofix_after_sla"
        signal["safe_reverify_minutes"] = safe_reverify_minutes
    return signal


def _build_prompt(packet: Mapping[str, Any]) -> str:
    trigger_lines = []
    for trigger in packet.get("triggers") or []:
        if not isinstance(trigger, Mapping):
            continue
        trigger_lines.append(
            "- "
            + "; ".join(
                part
                for part in (
                    f"label={trigger.get('label')}",
                    f"reason={trigger.get('reason')}",
                    f"severity={trigger.get('severity')}",
                    f"path={trigger.get('path')}",
                    f"summary={trigger.get('summary')}",
                    f"count={trigger.get('count')}",
                )
                if not part.endswith("=None")
            )
        )
    if not trigger_lines:
        trigger_lines.append("- none")
    return "\n".join(
        [
            "TradingAgents self-heal monitor triggered.",
            "",
            "Start from compact context, then inspect only the exact paths below unless the packet proves a broader read is needed.",
            "",
            "Triggers:",
            *trigger_lines,
            "",
            "Rules:",
            "- Do not submit live or paper orders.",
            "- Do not send email.",
            "- Do not change automation statuses unless the triggering packet specifically proves a controller config bug.",
            "- Diagnose root cause before editing.",
            "- Patch repo code/docs only when the evidence shows a repo bug.",
            "- If this is stale external data or a market-window timing issue, write that conclusion and leave code unchanged.",
            "- After any edit, run the smallest focused tests plus `python scripts/automation_context_snapshot.py --write`.",
            "- Keep the final note short: packet path, root cause, files changed, tests run, remaining blocker.",
        ]
    )


def build_self_heal_handoff(
    repo_root: str | Path = ".",
    *,
    max_triggers: int = 12,
    state_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root)
    context_dir = root / DEFAULT_CONTEXT_DIR
    summary_path = context_dir / "latest-summary.json"
    flags_path = context_dir / "latest-flags.json"
    summary = _read_json(summary_path)
    flags = _read_json(flags_path)
    raw_triggers = _dedupe_triggers(
        [*_flag_triggers(flags), *_packet_triggers(summary)],
        max_triggers=max_triggers,
    )
    resolved_state_path = Path(state_path) if state_path is not None else _default_signature_state_path(root)
    triggers = _annotate_handoff_triggers_with_state(
        raw_triggers,
        state_path=resolved_state_path,
    )
    active_triggers = [trigger for trigger in triggers if trigger.get("deduped_prior") is not True]
    max_severity = _max_severity(triggers)
    active_max_severity = _max_severity(active_triggers)
    deduped_prior_count = len(triggers) - len(active_triggers)
    should_start = active_max_severity in {"medium", "high"}
    packet: dict[str, Any] = {
        "schema_version": 1,
        "kind": "tradingagents_self_heal_handoff",
        "generated_at": dt.datetime.now(tz=UTC).isoformat(),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "forbidden_effects": list(FORBIDDEN_EFFECTS),
        "context_summary_path": str(summary_path),
        "context_flags_path": str(flags_path),
        "trigger_count": len(triggers),
        "active_trigger_count": len(active_triggers),
        "deduped_prior_count": deduped_prior_count,
        "max_severity": max_severity,
        "active_max_severity": active_max_severity,
        "should_start_new_chat": should_start,
        "start_condition": "medium_or_high_trigger" if should_start else "no_new_medium_or_high_trigger",
        "signature_state_path": str(resolved_state_path),
        "triggers": triggers,
        "recommended_destination": {
            "type": "codex_background_thread",
            "workspace": str(root),
            "reasoning_effort": "high" if max_severity == "high" else "medium",
        },
    }
    packet["new_chat_prompt"] = _build_prompt(packet)
    return packet


def build_self_heal_plan(
    repo_root: str | Path = ".",
    *,
    max_signals: int = 20,
    output_dir: str | Path | None = None,
    state_path: str | Path | None = None,
    now: dt.datetime | None = None,
    safe_reverify_minutes: int = DEFAULT_SAFE_REVERIFY_MINUTES,
) -> dict[str, Any]:
    """Build a bounded PA self-heal plan from compact failure signals.

    This is an audited plan/ledger packet, not an executor. Safe items get a
    deterministic verification command; order-adjacent or forbidden-effect
    signals are escalated and never auto-acted.
    """
    root = Path(repo_root)
    context_dir = root / DEFAULT_CONTEXT_DIR
    summary_path = context_dir / "latest-summary.json"
    flags_path = context_dir / "latest-flags.json"
    summary = _read_json(summary_path)
    flags = _read_json(flags_path)
    raw_signals = _dedupe_triggers(
        [*_plan_flag_signals(flags), *_plan_packet_signals(summary)],
        max_triggers=max_signals,
    )
    resolved_state_path = Path(state_path) if state_path is not None else _default_signature_state_path(root)
    prior_state_records = _prior_state_records(
        root,
        state_path=resolved_state_path,
    )
    prior_signatures = _prior_plan_signatures(root, output_dir) | set(prior_state_records)
    signals = [
        _classify_self_heal_signal(
            signal,
            prior_signatures=prior_signatures,
            prior_state_records=prior_state_records,
            repo_root=root,
            now=now,
            safe_reverify_minutes=safe_reverify_minutes,
        )
        for signal in raw_signals
    ]
    active_plan_count = sum(1 for signal in signals if signal.get("status") == "planned")
    escalation_count = sum(1 for signal in signals if signal.get("escalation_required") is True)
    deduped_prior_count = sum(1 for signal in signals if signal.get("status") == "already_recorded")
    max_severity = _max_severity(signals)
    status = "quiet"
    business_decision_pending_count = sum(
        1
        for signal in signals
        if signal.get("classification") == "business_decision_pending"
    )
    if escalation_count:
        status = "escalation_required"
    elif active_plan_count:
        status = "safe_plan_ready"
    elif business_decision_pending_count:
        status = "business_decision_pending"
    elif deduped_prior_count:
        status = "deduped"
    packet: dict[str, Any] = {
        "schema_version": 1,
        "kind": "tradingagents_self_heal_plan",
        "generated_at": _coerce_utc_datetime(now).isoformat(),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "forbidden_effects": list(FORBIDDEN_EFFECTS),
        "context_summary_path": str(summary_path),
        "context_flags_path": str(flags_path),
        "signature_state_path": str(resolved_state_path),
        "signal_count": len(signals),
        "active_plan_count": active_plan_count,
        "escalation_count": escalation_count,
        "deduped_prior_count": deduped_prior_count,
        "business_decision_pending_count": business_decision_pending_count,
        "max_severity": max_severity,
        "status": status,
        "signals": signals,
        "retry_policy": {
            "max_attempts": 2,
            "bounded_backoff_seconds": [0, 30],
            "on_exhaustion": "write_self_heal_handoff_and_escalate",
            "safe_reverify_minutes": safe_reverify_minutes,
        },
        "executor_boundary": {
            "safe_plane_only": True,
            "may_refresh_compact_context": True,
            "may_record_guidance": True,
            "may_submit_orders": False,
            "may_send_email": False,
            "may_modify_automation_status": False,
            "may_read_secrets": False,
        },
    }
    return packet


def execute_self_heal_plan(
    packet: Mapping[str, Any],
    *,
    repo_root: str | Path = ".",
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Execute allowlisted safe-plane verification actions from a plan packet."""
    root = Path(repo_root)
    updated: dict[str, Any] = json.loads(json.dumps(dict(packet)))
    executed_count = 0
    verified_count = 0
    verify_failed_count = 0
    skipped_escalated_count = 0
    skipped_unallowed_count = 0
    owned_recovery_count = 0
    for signal in updated.get("signals") or []:
        if not isinstance(signal, dict):
            continue
        if signal.get("escalation_required") is True:
            skipped_escalated_count += 1
            continue
        if signal.get("classification") == "recoverable_integrity" and signal.get("status") == "owned_recovery_ready":
            request = build_production_recovery_request(signal, repo_root=root)
            if request.get("ready") is not True:
                recovery = {"status": "transient_context_unavailable", "detail": request.get("detail")}
            else:
                request.pop("ready", None)
                recovery = coordinate_verified_recovery(
                    **request,
                    control_path=root / "results" / "policy" / "live_control.json",
                    receipt_dir=root / "results" / "control_plane" / "rearm_receipts",
                    recovery_root=root / "results" / "control_plane" / "recovery",
                )
            signal["recovery_result"] = recovery
            signal["status"] = "owned_recovery_dispatched"
            signal["recovery_status"] = recovery.get("status")
            owned_recovery_count += 1
            continue
        if signal.get("status") != "planned" or signal.get("classification") != "safe_autofix":
            continue
        command_keys = signal.get("execute_commands")
        if not isinstance(command_keys, list) or not command_keys:
            command_keys = [signal.get("verify_command")]
        verify_results: list[dict[str, Any]] = []
        executed_signal = False
        unallowed = False
        failed = False
        for command_key in command_keys:
            command = ALLOWED_SELF_HEAL_VERIFY_COMMANDS.get(str(command_key))
            if command is None:
                unallowed = True
                break
            result = runner(command, cwd=str(root), capture_output=True, text=True, timeout=90)
            executed_signal = True
            exit_code = int(getattr(result, "returncode", 1))
            verify_results.append(
                {
                    "command": str(command_key),
                    "exit_code": exit_code,
                    "stdout": _compact_text(getattr(result, "stdout", None), limit=500),
                    "stderr": _compact_text(getattr(result, "stderr", None), limit=500),
                }
            )
            if exit_code != 0:
                failed = True
                break
        if executed_signal:
            executed_count += 1
        signal["verify_results"] = verify_results
        if verify_results:
            last_result = verify_results[-1]
            signal["verify_exit_code"] = last_result["exit_code"]
            signal["verify_stdout"] = last_result["stdout"]
            signal["verify_stderr"] = last_result["stderr"]
        if unallowed:
            skipped_unallowed_count += 1
            signal["status"] = "verify_not_allowed"
            continue
        if failed:
            verify_failed_count += 1
            signal["status"] = "verify_failed"
            signal["escalation_required"] = True
        elif executed_signal:
            verified_count += 1
            signal["status"] = "verified"
    updated["executed_at"] = dt.datetime.now(tz=UTC).isoformat()
    updated["executed_count"] = executed_count
    updated["verified_count"] = verified_count
    updated["verify_failed_count"] = verify_failed_count
    updated["skipped_escalated_count"] = skipped_escalated_count
    updated["skipped_unallowed_count"] = skipped_unallowed_count
    updated["owned_recovery_count"] = owned_recovery_count
    updated["active_plan_count"] = sum(1 for signal in updated.get("signals") or [] if signal.get("status") == "planned")
    updated["escalation_count"] = sum(
        1 for signal in updated.get("signals") or [] if signal.get("escalation_required") is True
    )
    if verify_failed_count:
        updated["status"] = "safe_plan_failed"
    elif updated["escalation_count"]:
        updated["status"] = "escalation_required"
    elif updated["active_plan_count"]:
        updated["status"] = "safe_plan_ready"
    elif verified_count:
        updated["status"] = "verified"
    return updated


def render_self_heal_markdown(packet: Mapping[str, Any]) -> str:
    lines = [
        "# TradingAgents Self-Heal Handoff",
        "",
        f"- Generated: {packet.get('generated_at')}",
        f"- Should start new chat: {str(packet.get('should_start_new_chat')).lower()}",
        f"- Max severity: {packet.get('max_severity')}",
        f"- Trigger count: {packet.get('trigger_count')}",
        f"- Can submit orders: {str(packet.get('can_submit_orders')).lower()}",
        "",
        "## Triggers",
        "",
    ]
    for trigger in packet.get("triggers") or []:
        if not isinstance(trigger, Mapping):
            continue
        lines.append(
            f"- `{trigger.get('label')}` {trigger.get('reason')} "
            f"severity={trigger.get('severity')} path={trigger.get('path')}"
        )
    if not packet.get("triggers"):
        lines.append("- none")
    lines.extend(["", "## New Chat Prompt", "", "```text", str(packet.get("new_chat_prompt") or ""), "```", ""])
    return "\n".join(lines)


def render_self_heal_plan_markdown(packet: Mapping[str, Any]) -> str:
    lines = [
        "# TradingAgents Self-Heal Plan",
        "",
        f"- Generated: {packet.get('generated_at')}",
        f"- Status: {packet.get('status')}",
        f"- Max severity: {packet.get('max_severity')}",
        f"- Signal count: {packet.get('signal_count')}",
        f"- Active safe plan count: {packet.get('active_plan_count')}",
        f"- Escalation count: {packet.get('escalation_count')}",
        f"- Deduped prior count: {packet.get('deduped_prior_count')}",
        f"- Can submit orders: {str(packet.get('can_submit_orders')).lower()}",
        "",
        "## Signals",
        "",
    ]
    for signal in packet.get("signals") or []:
        if not isinstance(signal, Mapping):
            continue
        lines.append(
            f"- `{signal.get('label')}` reason={signal.get('reason')} "
            f"classification={signal.get('classification')} status={signal.get('status')} "
            f"action={signal.get('recommended_action')} path={signal.get('path')}"
        )
    if not packet.get("signals"):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_self_heal_handoff(
    packet: Mapping[str, Any],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    now: dt.datetime | None = None,
) -> tuple[Path, Path, Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"self-heal-handoff-{stamp}.json"
    markdown_path = out_dir / f"self-heal-handoff-{stamp}.md"
    prompt_path = out_dir / f"self-heal-prompt-{stamp}.txt"
    payload = dict(packet)
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(markdown_path)
    payload["prompt_path"] = str(prompt_path)
    json_text = json.dumps(payload, indent=2, sort_keys=True)
    markdown_text = render_self_heal_markdown(payload)
    prompt_text = str(payload.get("new_chat_prompt") or "")
    json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    prompt_path.write_text(prompt_text, encoding="utf-8")
    (out_dir / "latest.json").write_text(json_text, encoding="utf-8")
    (out_dir / "latest.md").write_text(markdown_text, encoding="utf-8")
    (out_dir / "latest-prompt.txt").write_text(prompt_text, encoding="utf-8")
    state_path = str(payload.get("signature_state_path") or _signature_state_path_from_output_dir(out_dir))
    _update_signature_state(
        state_path=state_path,
        items=[
            trigger
            for trigger in payload.get("triggers") or []
            if isinstance(trigger, Mapping)
        ],
        event="handoff_written",
        now=now,
    )
    return json_path, markdown_path, prompt_path


def write_self_heal_plan(
    packet: Mapping[str, Any],
    output_dir: str | Path = DEFAULT_PLAN_OUTPUT_DIR,
    *,
    now: dt.datetime | None = None,
) -> tuple[Path, Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"self-heal-plan-{stamp}.json"
    markdown_path = out_dir / f"self-heal-plan-{stamp}.md"
    payload = dict(packet)
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(markdown_path)
    json_text = json.dumps(payload, indent=2, sort_keys=True)
    markdown_text = render_self_heal_plan_markdown(payload)
    json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    (out_dir / "latest.json").write_text(json_text, encoding="utf-8")
    (out_dir / "latest.md").write_text(markdown_text, encoding="utf-8")
    state_path = str(payload.get("signature_state_path") or _signature_state_path_from_output_dir(out_dir))
    _update_signature_state(
        state_path=state_path,
        items=[
            signal
            for signal in payload.get("signals") or []
            if isinstance(signal, Mapping)
        ],
        event="plan_written",
        now=now,
    )
    return json_path, markdown_path
