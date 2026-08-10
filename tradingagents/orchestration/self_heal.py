"""Supervisor error self-heal handoff packets.

The handoff is deliberately advisory. It can tell Codex or n8n when a fresh
repair chat is warranted, but it cannot trade, approve, or edit anything by
itself.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

UTC = dt.timezone.utc
DEFAULT_CONTEXT_DIR = Path("results/_context")
DEFAULT_OUTPUT_DIR = Path("results/self_heal")
DEFAULT_PLAN_OUTPUT_DIR = Path("results/self_heal/plans")
DEFAULT_SIGNATURE_STATE_NAME = "signature-state.json"
DEFAULT_SAFE_REVERIFY_MINUTES = 15

FORBIDDEN_EFFECTS = (
    "create_trade_intent",
    "size_position",
    "submit_order",
    "promote_sleeve",
    "waive_live_gate",
    "send_email",
    "modify_automation_status",
)

HIGH_REASONS = {"blocker", "issues", "schema", "graph_failure", "abnormal_pl", "unexplained_action"}
MEDIUM_REASONS = {"model_telemetry", "crawler", "quality", "automation_health"}
LOW_REASONS = {"stale", "notify", "submitted", "candidate_change", "changed_tournament_leader"}
SELF_HEAL_REASONS = HIGH_REASONS | MEDIUM_REASONS | LOW_REASONS
EXCLUDED_LABELS = {"self_heal_handoff", "self_heal_plan", "hook_event"}
PLAN_ONLY_REASONS = {"connector_health", "source_routing", "failed_checks", "board_review"}
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
    if escalation_count:
        status = "escalation_required"
    elif active_plan_count:
        status = "safe_plan_ready"
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
    for signal in updated.get("signals") or []:
        if not isinstance(signal, dict):
            continue
        if signal.get("escalation_required") is True:
            skipped_escalated_count += 1
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
