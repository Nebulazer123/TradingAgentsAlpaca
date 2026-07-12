"""Real CLI department simulation audit for TradingAgents.

The audit runs real repo commands with live-data dry-run authority. It does not
submit live orders; paper paths are forced to dry-run when a dry-run option
exists.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

UTC = dt.timezone.utc
DEFAULT_MAC_OLLAMA_URL = "http://macbook-pro.tail37edd7.ts.net:11434/v1"
DEFAULT_MAC_MODEL = "deepseek-r1:14b"
PROCESS_REVIEW_MAX_AGE_SECONDS = 15 * 60


@dataclass(frozen=True)
class DepartmentCommand:
    department: str
    name: str
    command: list[str]
    timeout_seconds: int = 120


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _python_module_command(*parts: str) -> list[str]:
    return [sys.executable, "-m", "cli.main", *parts]


def _symbols(values: Sequence[str] | str | None) -> list[str]:
    if values is None:
        return ["NOW", "IBM", "CRM"]
    if isinstance(values, str):
        pieces = values.replace(";", ",").split(",")
    else:
        pieces = list(values)
    symbols = [piece.strip().upper() for piece in pieces if piece and piece.strip()]
    return symbols or ["NOW", "IBM", "CRM"]


def build_department_commands(top_symbols: Sequence[str] | str | None = None) -> list[DepartmentCommand]:
    symbols = _symbols(top_symbols)[:3]
    joined_symbols = ",".join(symbols)
    commands = [
        DepartmentCommand(
            "preflight",
            "compact_context_snapshot",
            [sys.executable, "scripts/automation_context_snapshot.py", "--write"],
            90,
        ),
        DepartmentCommand(
            "preflight",
            "process_review",
            _python_module_command("research", "process-review", "--json-output"),
            120,
        ),
        DepartmentCommand(
            "preflight",
            "automation_health_audit",
            _python_module_command("research", "automation-health-audit", "--json-output"),
            120,
        ),
        DepartmentCommand(
            "preflight",
            "self_heal_plan",
            _python_module_command("research", "self-heal-plan", "--json-output"),
            120,
        ),
        DepartmentCommand(
            "preflight",
            "n8n_evaluation_dataset",
            _python_module_command("research", "n8n-evaluation-dataset", "--json-output"),
            90,
        ),
        DepartmentCommand(
            "integrations",
            "capability_doctor",
            _python_module_command(
                "integrations",
                "doctor",
                "--write-packet",
                "--json-output",
            ),
            120,
        ),
        DepartmentCommand(
            "model",
            "automation_orchestration_plan",
            _python_module_command(
                "research",
                "automation-orchestration-plan",
                "--candidate-symbols",
                joined_symbols,
                "--json-output",
            ),
            180,
        ),
        DepartmentCommand(
            "research",
            "source_quality_review",
            _python_module_command("research", "source-quality-review", "--json-output"),
            120,
        ),
        DepartmentCommand(
            "research",
            "provider_fallbacks_market_news",
            _python_module_command(
                "research",
                "provider-fallbacks",
                "--evidence-need",
                "market_news",
                "--json-output",
            ),
            120,
        ),
        DepartmentCommand(
            "research",
            "agent_ledger_update",
            _python_module_command("research", "agent-ledger-update", "--json-output"),
            120,
        ),
        DepartmentCommand(
            "research",
            "agent_ledger_summary",
            _python_module_command("research", "agent-ledger-summary", "--json-output"),
            90,
        ),
        DepartmentCommand(
            "research",
            "creator_workflow_status",
            _python_module_command("research", "creator-workflow-status", "--json-output"),
            90,
        ),
        DepartmentCommand(
            "research",
            "outcome_labeling",
            _python_module_command("research", "outcome-labeling", "--json-output"),
            120,
        ),
        DepartmentCommand(
            "research",
            "model_telemetry_report",
            _python_module_command("research", "model-telemetry-report", "--json-output"),
            90,
        ),
        DepartmentCommand(
            "research",
            "mirofish_handoff_status",
            _python_module_command("research", "mirofish-handoff-status", "--json-output"),
            90,
        ),
        DepartmentCommand(
            "policy",
            "pullback_support_representative_dip",
            _python_module_command(
                "policy",
                "pullback-support",
                "--symbol",
                symbols[0],
                "--current-price",
                "99.20",
                "--support-level",
                "100.00",
                "--atr",
                "2.00",
                "--pullback-atr",
                "0.40",
                "--above-rising-50d",
                "--above-rising-200d",
                "--sell-volume-state",
                "normal",
                "--gap-state",
                "none",
                "--sector-relative-strength",
                "1.10",
                "--regime-state",
                "risk_on",
                "--json-output",
            ),
            90,
        ),
        DepartmentCommand("alpaca", "account_check", _python_module_command("alpaca", "check"), 120),
        DepartmentCommand(
            "alpaca",
            "hourly_supervisor_live_data_dry_run",
            _python_module_command("alpaca", "supervise-hourly", "--dry-run", "--json-output"),
            180,
        ),
        DepartmentCommand(
            "alpaca",
            "premarket_brief",
            _python_module_command("alpaca", "premarket-brief", "--json-output"),
            120,
        ),
        DepartmentCommand(
            "alpaca",
            "daily_report_preview",
            _python_module_command("alpaca", "supervisor-daily-report", "--json-output"),
            120,
        ),
        DepartmentCommand(
            "alpaca",
            "overnight_system_verification",
            _python_module_command("alpaca", "verify-overnight-system", "--json-output"),
            120,
        ),
        DepartmentCommand(
            "paper_strategy",
            "paper_tournament_report",
            _python_module_command("alpaca", "paper-tournament", "report", "--json-output"),
            90,
        ),
        DepartmentCommand(
            "paper_strategy",
            "alphainsider_paper_watch",
            _python_module_command(
                "alpaca",
                "paper-tournament",
                "alphainsider-watch",
                "--json-output",
            ),
            120,
        ),
        DepartmentCommand(
            "paper_strategy",
            "paper_tournament_dry_run",
            _python_module_command(
                "alpaca",
                "paper-tournament",
                "run",
                "--all",
                "--dry-run",
                "--json-output",
            ),
            180,
        ),
        DepartmentCommand(
            "board",
            "execution_board_review",
            _python_module_command("research", "execution-board-review", "--json-output"),
            120,
        ),
    ]
    for symbol in symbols:
        commands.append(
            DepartmentCommand(
                "research",
                f"ticker_provider_bundle_{symbol.lower()}",
                _python_module_command(
                    "research",
                    "ticker-provider-bundle",
                    "--symbol",
                    symbol,
                    "--json-output",
                ),
                180,
            )
        )
    return commands


def _mac_api_tags_url(endpoint_url: str) -> str:
    base = endpoint_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3].rstrip("/")
    return f"{base}/api/tags"


def probe_mac_ollama(endpoint_url: str = DEFAULT_MAC_OLLAMA_URL, *, timeout_seconds: float = 4.0) -> dict[str, Any]:
    tags_url = _mac_api_tags_url(endpoint_url)
    try:
        with urlopen(tags_url, timeout=timeout_seconds) as response:  # nosec B310 - operator-provided local/Tailscale URL
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return {
            "endpoint_url": endpoint_url,
            "tags_url": tags_url,
            "reachable": False,
            "model": DEFAULT_MAC_MODEL,
            "models": [],
            "error": str(exc),
        }
    models = [
        str(item.get("name") or item.get("model"))
        for item in payload.get("models", [])
        if isinstance(item, dict) and (item.get("name") or item.get("model"))
    ]
    return {
        "endpoint_url": endpoint_url,
        "tags_url": tags_url,
        "reachable": True,
        "model": DEFAULT_MAC_MODEL,
        "models": models,
        "deepseek_available": DEFAULT_MAC_MODEL in models,
    }


def _json_from_stdout(stdout: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _process_review_freshness(
    command_name: str,
    payload: Mapping[str, Any] | None,
    *,
    audit_started_at: dt.datetime,
    max_age_seconds: int = PROCESS_REVIEW_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    if command_name != "process_review":
        return {
            "required": False,
            "ok": True,
            "age_seconds": None,
            "generated_at": None,
            "reason": "",
        }
    generated_at = payload.get("generated_at") if payload else None
    parsed = _parse_timestamp(generated_at)
    if parsed is None:
        return {
            "required": True,
            "ok": False,
            "age_seconds": None,
            "generated_at": generated_at,
            "reason": "process_review missing parseable generated_at",
        }
    age_seconds = max(0, int((audit_started_at - parsed).total_seconds()))
    ok = age_seconds <= max_age_seconds
    return {
        "required": True,
        "ok": ok,
        "age_seconds": age_seconds,
        "generated_at": parsed.isoformat(),
        "reason": "" if ok else f"process_review older than {max_age_seconds}s",
    }


def _metric_value(payload: Mapping[str, Any] | None, keys: Sequence[str]) -> int:
    if not payload:
        return 0
    total = 0
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            total += int(value)
        elif isinstance(value, int):
            total += value
        elif isinstance(value, list):
            total += len(value)
    return total


def _to_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _contains_loss_keywords(value: Any) -> bool:
    text = str(value or "").lower()
    return any(token in text for token in ("loss", "breach", "drawdown", "stop"))


def _iter_actions(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    actions = payload.get("actions")
    if not isinstance(actions, list):
        return []
    return [action for action in actions if isinstance(action, dict)]


def _action_side(action: Mapping[str, Any]) -> str:
    return str(action.get("side") or action.get("action") or "").lower()


def _action_account(action: Mapping[str, Any]) -> str:
    return str(action.get("account") or "").lower()


def _action_reason(action: Mapping[str, Any]) -> str:
    return str(action.get("reason") or action.get("reasoning") or "")


def _is_live_sell_action(action: Mapping[str, Any]) -> bool:
    side = _action_side(action)
    action_name = str(action.get("action") or "").lower()
    account = _action_account(action)
    is_sell = side in {"sell", "close", "reduce"} or action_name in {"sell", "close", "reduce"}
    return is_sell and (not account or account == "live")


def _is_loss_sell_requiring_review(action: Mapping[str, Any], packet_decision: str) -> bool:
    if packet_decision == "loss-review":
        return _is_live_sell_action(action)
    return _is_live_sell_action(action) and _contains_loss_keywords(_action_reason(action))


def _loss_exit_review_from_packet(payload: Mapping[str, Any], action: Mapping[str, Any] | None = None) -> Mapping[str, Any] | None:
    if action is not None:
        evidence = action.get("evidence")
        if isinstance(evidence, Mapping):
            review = evidence.get("loss_exit_review")
            if isinstance(review, Mapping):
                return review
    evidence = payload.get("evidence")
    if isinstance(evidence, Mapping):
        review = evidence.get("loss_exit_review")
        if isinstance(review, Mapping):
            return review
    return None


def _is_valid_loss_exit_review(review: Mapping[str, Any] | None) -> bool:
    if not isinstance(review, Mapping):
        return False
    return review.get("allowed") is True


def _collect_submission_evidence(payload: Mapping[str, Any] | None) -> list[str]:
    if payload is None:
        return []
    reasons: list[str] = []
    submitted_items = payload.get("submitted")
    submitted_count = _metric_value(payload, ("submitted_order_count", "submitted_count", "submitted_orders"))
    if submitted_count > 0:
        reasons.append("submitted_count>0")
    if isinstance(submitted_items, list) and len(submitted_items) > 0:
        reasons.append("submitted list non-empty")
    if _to_int(payload.get("live_order_submitted")) > 0:
        reasons.append("live_order_submitted true")
    if payload.get("submit_capable") is True:
        reasons.append("unexpected submit_capable true")
    submitted_markers = (
        payload.get("submit_capable"),
        _to_int(payload.get("live_order_submitted")),
    )
    if any(_to_int(marker) for marker in submitted_markers):
        reasons.append("submission marker set")
    checks = payload.get("checks")
    if isinstance(checks, list):
        for item in checks:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name") or "").lower()
            message = str(item.get("message") or item.get("summary") or "").lower()
            status = str(item.get("status") or "").lower()
            if status in {"warn", "fail"} and any(
                token in name or token in message
                for token in (
                    "submitted order",
                    "order submitted",
                    "live order",
                    "paper order",
                    "submit order",
                    "trade submitted",
                    "execution submitted",
                )
            ):
                reasons.append(f"{name}:{status}")
    decisions = str(payload.get("decision") or "").lower()
    for action in _iter_actions(payload):
        if _is_loss_sell_requiring_review(action, decisions):
            review = _loss_exit_review_from_packet(payload, action)
            if not _is_valid_loss_exit_review(review):
                reasons.append(
                    f"loss-sell action requires valid loss_exit_review (symbol={action.get('symbol', 'unknown')})"
                )
                break
    # suppress duplicate reasons while preserving order
    deduplicated: list[str] = []
    for reason in reasons:
        if reason not in deduplicated:
            deduplicated.append(reason)
    return deduplicated


def _is_observer_submission_summary(command_name: str, payload: Mapping[str, Any] | None) -> bool:
    if not payload:
        return False
    kind = str(payload.get("kind") or "")
    return command_name in {"automation_health_audit"} or kind in {
        "tradingagents_automation_health_audit",
    }


def _packet_paths(payload: Mapping[str, Any] | None) -> list[str]:
    if not payload:
        return []
    paths: list[str] = []
    for key in (
        "packet_path",
        "json_path",
        "markdown_path",
        "summary_path",
        "ledger_path",
        "latest_path",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    for key in ("model_telemetry_paths", "output_packet_refs", "graph_memory_refs", "mirror_packet_refs"):
        value = payload.get(key)
        if isinstance(value, dict):
            paths.extend(str(item) for item in value.values())
        elif isinstance(value, list):
            paths.extend(str(item) for item in value)
    return sorted(set(paths))


def _stale_downrank_count(payload: Mapping[str, Any] | None) -> int:
    if not payload:
        return 0
    count = 0
    for decision in payload.get("decisions") or []:
        if not isinstance(decision, Mapping):
            continue
        effects = decision.get("allowed_effects") or []
        if decision.get("freshness_status") == "stale" and "downrank" in effects:
            count += 1
    return count


def _stale_safe_count(payload: Mapping[str, Any] | None) -> int:
    if not payload:
        return 0
    count = 0
    for decision in payload.get("decisions") or []:
        if not isinstance(decision, Mapping):
            continue
        if decision.get("freshness_status") != "stale":
            continue
        effects = decision.get("allowed_effects") or []
        quality = str(decision.get("quality") or "").lower()
        if "downrank" in effects or quality in {"low", "unknown"}:
            count += 1
    return count


def _attention_samples(payload: Mapping[str, Any] | None, *, limit: int = 8) -> list[dict[str, Any]]:
    """Return a bounded human-facing sample of blockers/stale/blocked evidence."""

    if not payload:
        return []
    samples: list[dict[str, Any]] = []
    for decision in payload.get("decisions") or []:
        if not isinstance(decision, Mapping):
            continue
        freshness = str(decision.get("freshness_status") or "")
        blocked = bool(decision.get("blocked"))
        if not blocked and freshness not in {"stale", "missing_or_invalid"}:
            continue
        samples.append(
            {
                "type": "source_decision",
                "source_name": decision.get("source_name"),
                "path": decision.get("path"),
                "quality": decision.get("quality"),
                "freshness_status": freshness,
                "blocked": blocked,
                "role": decision.get("role"),
                "reason": decision.get("reason"),
            }
        )
        if len(samples) >= limit:
            return samples
    for key in ("blockers", "issues", "warnings"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, Mapping):
                sample = {
                    "type": key.rstrip("s"),
                    "id": value.get("id") or value.get("name") or value.get("code"),
                    "status": value.get("status"),
                    "message": value.get("message") or value.get("summary") or value.get("reason"),
                }
            else:
                sample = {"type": key.rstrip("s"), "message": str(value)}
            samples.append(sample)
            if len(samples) >= limit:
                return samples
    return samples


def _next_action(payload: Mapping[str, Any] | None, exit_code: int) -> str:
    if exit_code != 0:
        return "patch failing command before trusting this department"
    if not payload:
        return "command exited cleanly; inspect stdout tail if this department needs detail"
    if payload.get("recommended_next_step"):
        return str(payload["recommended_next_step"])
    fallback = payload.get("fallback_actions")
    if isinstance(fallback, list) and fallback:
        return "; ".join(str(item) for item in fallback[:3])
    next_open = payload.get("next_open")
    if isinstance(next_open, list) and next_open:
        return "; ".join(str(item) for item in next_open[:3])
    if payload.get("stale_count"):
        return "refresh or downrank stale sources before market use"
    return "no immediate action"


def _run_command(
    command: DepartmentCommand,
    *,
    repo_root: Path,
    env: Mapping[str, str],
    audit_started_at: dt.datetime,
    command_runner: CommandRunner | None,
) -> dict[str, Any]:
    try:
        if command_runner is not None:
            completed = command_runner(
                command.command,
                cwd=repo_root,
                env=dict(env),
                timeout=command.timeout_seconds,
            )
        else:
            completed = subprocess.run(
                command.command,
                cwd=repo_root,
                env=dict(env),
                timeout=command.timeout_seconds,
                text=True,
                capture_output=True,
                check=False,
            )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        exit_code = int(completed.returncode)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = f"timeout after {command.timeout_seconds}s"
        exit_code = 124
    payload = _json_from_stdout(stdout)
    # Fake-success guard: a department invoked with --json-output that exits 0 but
    # prints no parseable JSON (e.g. a human sentence or empty stdout) must not be
    # silently counted as clean structured evidence.
    expected_structured_output = "--json-output" in command.command
    structured_output_ok = payload is not None
    raw_submitted_count = _metric_value(
        payload,
        ("submitted_order_count", "submitted_count", "submitted", "submitted_orders"),
    )
    blocker_count = _metric_value(payload, ("blocker_count", "blocked_count", "unresolved_blockers", "blockers", "issues"))
    stale_count = _metric_value(payload, ("stale_count", "stale_warnings"))
    stale_downrank_count = _stale_downrank_count(payload)
    stale_safe_count = _stale_safe_count(payload)
    process_review_freshness = _process_review_freshness(
        command.name,
        payload,
        audit_started_at=audit_started_at,
    )
    submission_evidence = _collect_submission_evidence(payload)
    observed_submission_count = 0
    observed_submission_evidence: list[str] = []
    submitted_count = raw_submitted_count
    if _is_observer_submission_summary(command.name, payload):
        observed_submission_count = raw_submitted_count
        if raw_submitted_count:
            observed_submission_evidence.append("observer_reported_historical_submitted_count")
        submitted_count = 0
        submission_evidence = [
            reason for reason in submission_evidence if reason != "submitted_count>0"
        ]
    return {
        "department": command.department,
        "name": command.name,
        "command": command.command,
        "exit_code": exit_code,
        "status": "ok" if exit_code == 0 else "failed",
        "expected_structured_output": expected_structured_output,
        "structured_output_ok": structured_output_ok,
        "submitted_order_count": submitted_count,
        "submission_evidence": submission_evidence,
        "unsafe_submission_evidence": len(submission_evidence) > 0,
        "observed_submission_count": observed_submission_count,
        "observed_submission_evidence": observed_submission_evidence,
        "blocker_count": blocker_count,
        "stale_count": stale_count,
        "stale_downrank_count": stale_downrank_count,
        "stale_safe_count": stale_safe_count,
        "process_review_freshness": process_review_freshness,
        "attention_samples": _attention_samples(payload),
        "packet_paths": _packet_paths(payload),
        "next_action": _next_action(payload, exit_code),
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
    }


def _render_markdown(audit: Mapping[str, Any]) -> str:
    lines = [
        "# TradingAgents Real Simulation Audit",
        "",
        f"- Generated: {audit['generated_at']}",
        f"- Authority: {audit['live_data_authority']}",
        f"- Can submit orders: {str(audit['can_submit_orders']).lower()}",
        f"- Mac Ollama: {audit['mac_ollama']['model']} reachable={audit['mac_ollama'].get('reachable')}",
        f"- Failed commands: {audit['failed_command_count']}",
        f"- Commands missing structured output: {', '.join(audit.get('commands_missing_structured_output', [])) or 'none'}",
        f"- Submitted order count: {audit['total_submitted_order_count']}",
        f"- Observed historical submission count: {audit.get('total_observed_submission_count', 0)}",
        f"- Unsafe submission evidence: {', '.join(audit['commands_with_submission_evidence']) or 'none'}",
        f"- Stale source count: {audit['stale_source_count']}",
        f"- Stale sources downranked: {audit['stale_downrank_count']}",
        f"- Stale sources safe for use: {audit.get('stale_safe_count', 0)}",
        "",
        "| Department | Command | Exit | Submitted | Observed | Submission evidence | Blockers | Stale | Downranked | Next action |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in audit["commands"]:
        command_text = " ".join(result["command"]).replace("|", "\\|")
        next_action = str(result["next_action"]).replace("|", "\\|")
        lines.append(
            f"| {result['department']} | `{command_text}` | {result['exit_code']} | "
            f"{result['submitted_order_count']} | "
            f"{result.get('observed_submission_count', 0)} | "
            f"{len(result['submission_evidence'])} | {result['blocker_count']} | "
            f"{result['stale_count']} | {result['stale_downrank_count']} | {next_action} |"
        )
    lines.append("")
    return "\n".join(lines)


def _write_outputs(audit: dict[str, Any], output_dir: Path, now_id: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"real-simulation-audit-{now_id}.json"
    markdown_path = output_dir / f"real-simulation-audit-{now_id}.md"
    json_text = json.dumps(audit, indent=2, sort_keys=True)
    markdown_text = _render_markdown(audit)
    json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    (output_dir / "latest.json").write_text(json_text, encoding="utf-8")
    (output_dir / "latest.md").write_text(markdown_text, encoding="utf-8")
    return json_path, markdown_path


def run_real_simulation_audit(
    *,
    repo_root: str | Path = ".",
    output_dir: str | Path = "results/real_simulation_audits",
    top_symbols: Sequence[str] | str | None = None,
    command_runner: CommandRunner | None = None,
    env: Mapping[str, str] | None = None,
    now_id: str | None = None,
    mac_ollama_url: str = DEFAULT_MAC_OLLAMA_URL,
    mac_probe_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root)
    run_id = now_id or dt.datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    active_env = dict(os.environ if env is None else env)
    active_env.setdefault("TRADINGAGENTS_MAC_OLLAMA_URL", mac_ollama_url)
    active_env.setdefault("TRADINGAGENTS_MAC_RESEARCH_MODEL", DEFAULT_MAC_MODEL)
    audit_started_at = dt.datetime.now(tz=UTC)
    commands = build_department_commands(top_symbols=top_symbols)
    mac_probe = (
        dict(mac_probe_result)
        if mac_probe_result is not None
        else probe_mac_ollama(active_env["TRADINGAGENTS_MAC_OLLAMA_URL"])
    )
    results = [
        _run_command(
            command,
            repo_root=root,
            env=active_env,
            audit_started_at=audit_started_at,
            command_runner=command_runner,
        )
        for command in commands
    ]
    commands_with_submission_evidence = [
        result["name"] for result in results if result["unsafe_submission_evidence"]
    ]
    commands_with_observed_submission_evidence = [
        result["name"] for result in results if int(result.get("observed_submission_count") or 0) > 0
    ]
    unsafe_submission_evidence = len(commands_with_submission_evidence) > 0
    total_submitted_order_count = sum(
        result["submitted_order_count"] for result in results
    )
    total_observed_submission_count = sum(
        int(result.get("observed_submission_count") or 0) for result in results
    )
    commands_missing_structured_output = [
        result["name"]
        for result in results
        if result["expected_structured_output"] and not result["structured_output_ok"]
    ]
    stale_process_review_commands = [
        result["name"]
        for result in results
        if result.get("process_review_freshness", {}).get("required")
        and not result.get("process_review_freshness", {}).get("ok")
    ]
    audit: dict[str, Any] = {
        "schema_version": 1,
        "kind": "tradingagents_real_simulation_audit",
        "generated_at": dt.datetime.now(tz=UTC).isoformat(),
        "run_id": run_id,
        "analysis_only": True,
        "live_data_authority": "live_dry_run",
        "can_submit_orders": False,
        "mac_ollama": mac_probe,
        "department_count": len({result["department"] for result in results}),
        "command_count": len(results),
        "failed_command_count": sum(1 for result in results if result["exit_code"] != 0),
        "commands_missing_structured_output": commands_missing_structured_output,
        "stale_process_review_commands": stale_process_review_commands,
        "total_submitted_order_count": total_submitted_order_count,
        "total_observed_submission_count": total_observed_submission_count,
        "unsafe_submission_evidence": unsafe_submission_evidence,
        "commands_with_submission_evidence": commands_with_submission_evidence,
        "commands_with_observed_submission_evidence": commands_with_observed_submission_evidence,
        "total_blocker_count": sum(result["blocker_count"] for result in results),
        "stale_source_count": sum(result["stale_count"] for result in results),
        "stale_downrank_count": sum(result["stale_downrank_count"] for result in results),
        "stale_safe_count": sum(result["stale_safe_count"] for result in results),
        "commands": results,
        "acceptance": {
            "accepted": True,
            "no_live_submit_command": not any(
                " --submit-actions" in " ".join(result["command"])
                or " alpaca submit " in " ".join(result["command"])
                for result in results
            ),
            "no_orders_submitted": total_submitted_order_count == 0,
            "unsafe_submission_evidence": unsafe_submission_evidence,
            "commands_with_submission_evidence": commands_with_submission_evidence,
            "observed_submission_evidence": total_observed_submission_count > 0,
            "commands_with_observed_submission_evidence": commands_with_observed_submission_evidence,
            "mac_deepseek_available": bool(mac_probe.get("deepseek_available")),
            "all_commands_clean": all(result["exit_code"] == 0 for result in results),
            "all_structured_output_present": len(commands_missing_structured_output) == 0,
            "commands_missing_structured_output": commands_missing_structured_output,
            "process_review_fresh": len(stale_process_review_commands) == 0,
            "stale_process_review_commands": stale_process_review_commands,
            "stale_sources_refreshed_or_downranked": (
                sum(result["stale_count"] for result in results) == 0
                or sum(result["stale_safe_count"] for result in results)
                >= sum(result["stale_count"] for result in results)
            ),
        },
    }
    acceptance = audit["acceptance"]
    acceptance["optional_helper_degraded"] = not acceptance["mac_deepseek_available"]
    acceptance["optional_helper_degradation_reason"] = (
        "mac_deepseek_helper_unreachable_or_missing"
        if acceptance["optional_helper_degraded"]
        else None
    )
    acceptance["core_accepted"] = (
        acceptance["no_live_submit_command"]
        and acceptance["no_orders_submitted"]
        and not acceptance["unsafe_submission_evidence"]
        and acceptance["all_commands_clean"]
        and acceptance["all_structured_output_present"]
        and acceptance["process_review_fresh"]
        and acceptance["stale_sources_refreshed_or_downranked"]
    )
    acceptance["strict_optional_model_accepted"] = (
        acceptance["core_accepted"] and acceptance["mac_deepseek_available"]
    )
    acceptance["accepted"] = acceptance["core_accepted"]
    resolved_output_dir = Path(output_dir)
    json_path = resolved_output_dir / f"real-simulation-audit-{run_id}.json"
    markdown_path = resolved_output_dir / f"real-simulation-audit-{run_id}.md"
    audit["json_path"] = str(json_path)
    audit["markdown_path"] = str(markdown_path)
    _write_outputs(audit, resolved_output_dir, run_id)
    return audit
