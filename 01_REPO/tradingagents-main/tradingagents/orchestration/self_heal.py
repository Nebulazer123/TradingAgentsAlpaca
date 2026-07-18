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
import subprocess
import sys
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

from tradingagents.orchestration.incidents import is_safe_incident_id
from tradingagents.orchestration.recovery import (
    load_recovery_evidence,
    rearm_after_verified_recovery,
)
from tradingagents.policy.decision_authority import resolve_exit_authority
from tradingagents.policy.io import atomic_write_text
from tradingagents.policy.live_control import (
    load_live_control_state,
    write_live_control_state,
)

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
    "independent_verification",
    "refresh_live_control_after_ready",
)
RECOVERY_RECIPE_NAME = "resolve_policy_sync_reconcile_verify_rearm"
RECOVERY_PHASES = (
    "resolve_authority",
    "regenerate_evidence",
    "sync_promotion",
    "reconcile",
    "focused_verify",
    "ready_incident",
    "manifest",
    "rearm",
)
RECOVERY_MAX_ATTEMPTS = 3
RECOVERY_BACKOFF_SECONDS = (0, 30, 120)
RECOVERY_LEASE_MINUTES = 30

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
    if label in recoverable_labels or reason in recoverable_reasons:
        return {
            **base,
            "classification": "recoverable_integrity",
            "status": "owned_recovery_ready",
            "may_rearm": True,
        }
    return {**base, "classification": "observe_only", "status": "observed"}


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
    }
    canonical_binding_keys = {
        "incident_id",
        "symbol",
        "broker_account",
        "environment",
        "source_revision",
    }
    if (
        value.get("schema_version") != "tradingagents.self_heal_recovery.v1"
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
        or not isinstance(value.get("owner_role"), str)
        or not is_safe_incident_id(value.get("owner_role"))
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
    }
    proof_keys = {"incident", "reconciliation", "promotion", "focused"}
    if (
        not isinstance(intent, Mapping)
        or set(intent) != intent_keys
        or intent.get("incident_id") != value.get("incident_id")
        or _canonical_absolute_path(intent.get("manifest_path")) is None
        or _valid_recovery_digest(intent.get("manifest_sha256")) is False
        or _canonical_absolute_path(intent.get("control_path")) is None
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
    try:
        valid = _valid_persisted_recovery_state(value)
    except Exception:
        valid = False
    if not valid:
        return None, "corrupt_state"
    return value, None


def _write_recovery_state(path: Path, state: Mapping[str, Any]) -> None:
    atomic_write_text(path, json.dumps(state, indent=2, sort_keys=True))


def _recovery_lock(
    path: Path, *, incident_id: str, owner_run_id: str, lease_expires_at: str, now: dt.datetime
) -> tuple[int | None, str, str | None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    metadata = {"schema_version": "tradingagents.recovery_lock.v1", "incident_id": incident_id, "owner_run_id": owner_run_id, "lease_expires_at": lease_expires_at, "token": token}
    took_over = False
    for _ in range(3):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                probe = os.open(path, os.O_RDONLY)
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(probe)
                    return None, "owner_busy", None
                fcntl.flock(probe, fcntl.LOCK_UN)
                os.close(probe)
            except OSError:
                return None, "owner_busy", None
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None, "corrupt_lock", None
            if not isinstance(existing, dict) or existing.get("schema_version") != "tradingagents.recovery_lock.v1" or existing.get("incident_id") != incident_id or not is_safe_incident_id(existing.get("owner_run_id")) or not isinstance(existing.get("token"), str):
                return None, "corrupt_lock", None
            expiry = _parse_datetime(existing.get("lease_expires_at"))
            if expiry is None:
                return None, "corrupt_lock", None
            if expiry > now:
                return None, "owner_busy", None
            # A rename quarantines a stale lock atomically; exactly one
            # contender can win and retry O_EXCL.
            try:
                os.replace(path, path.with_name(f".owner.stale-{hashlib.sha256(path.read_bytes()).hexdigest()[:12]}"))
                took_over = True
            except FileNotFoundError:
                pass
            continue
        encoded = _recovery_json(metadata)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if os.write(descriptor, encoded) != len(encoded):
                raise OSError("incomplete recovery lock write")
            os.fsync(descriptor)
        except Exception:
            os.close(descriptor)
            with suppress(FileNotFoundError):
                path.unlink()
            raise
        return descriptor, "stale_takeover" if took_over else "acquired", token
    return None, "owner_busy", None


def _release_recovery_lock(path: Path, descriptor: int, token: str | None) -> None:
    with suppress(OSError):
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(current, dict) and current.get("token") == token:
        with suppress(FileNotFoundError):
            path.unlink()


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
        return (
            packet.get("schema_version") == "tradingagents.recovery_phase.v1"
            and packet.get("analysis_only") is True
            and packet.get("can_submit_orders") is False
            and packet.get("execution_authority") == "none"
            and isinstance(packet.get("packet_path"), str)
            and bool(packet["packet_path"].strip())
            and isinstance(packet.get("hourly_packet_path"), str)
            and bool(packet["hourly_packet_path"].strip())
        )
    if phase == "sync_promotion":
        return (
            packet.get("schema_version") == "tradingagents.recovery_phase.v1"
            and packet.get("promotion_evidence_fresh") is True
            and packet.get("issues") == []
            and packet.get("arm_live") is False
            and packet.get("ci_green") is False
            and packet.get("can_submit_orders") is False
            and packet.get("execution_authority") == "none"
        )
    if phase == "reconcile":
        return (
            packet.get("schema_version") == "tradingagents.recovery_phase.v1"
            and packet.get("read_only") is True
            and packet.get("execution_authority") == "none"
            and packet.get("can_submit_orders") is False
            and packet.get("matched") is True
            and packet.get("issues") == []
            and type(packet.get("broker_write_calls")) is int
            and packet.get("broker_write_calls") == 0
        )
    if phase == "focused_verify":
        return (
            packet.get("schema_version") == "tradingagents.recovery_phase.v1"
            and packet.get("focused_tests_passed") is True
            and _packet_string_list(packet.get("passing_tests"), nonempty=True)
            and is_safe_incident_id(packet.get("verifier_run_id"))
            and is_safe_incident_id(packet.get("verifier_role_id"))
            and packet.get("verifier_run_id").casefold()
            != packet.get("owner_run_id").casefold()
            and packet.get("verifier_role_id").casefold()
            != packet.get("owner_role").casefold()
        )
    if phase == "ready_incident":
        expected_phases = RECOVERY_PHASES[:5]
        if not all(_valid_recovery_record(outputs.get(name)) for name in expected_phases):
            return False
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
            and packet.get("repairer_role_id") == packet.get("owner_role")
            and packet.get("root_cause_resolved") is True
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
    return _phase_record(path)


def _adapter_packet(result: object) -> Mapping[str, Any]:
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
    return packet


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
        or not signal_symbol
        or symbol != signal_symbol
        or any(
            not isinstance(context.get(key), str)
            or not str(context[key]).strip()
            for key in ("broker_account", "environment", "source_revision")
        )
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

    def promotion(_arguments: Mapping[str, Any]) -> dict[str, Any]:
        paths = [context_path(name) for name in ("report_path", "envelope_path", "promotion_state_path")]
        if any(path is None for path in paths):
            return unavailable("sync_promotion", "named promotion inputs are unavailable")
        report, envelope, state = paths
        result = run_json("sync_promotion", [sys.executable, "-m", "cli.main", "policy", "sync-promotion", "--report-path", str(report), "--envelope-path", str(envelope), "--state-path", str(state), "--no-arm-live", "--no-ci-green", "--json-output"])
        packet = result.get("packet") if isinstance(result, Mapping) else None
        if not isinstance(packet, dict) or not isinstance(packet.get("issues_by_sleeve"), Mapping):
            return unavailable("sync_promotion", "canonical promotion result is incomplete")
        issues = [str(issue) for values in packet["issues_by_sleeve"].values() if isinstance(values, list) for issue in values]
        return {"packet": {**packet, "promotion_evidence_fresh": not issues, "issues": issues}}

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
            result = command_runner([sys.executable, "-m", "pytest", "tests/test_recovery_coordinator.py", "tests/test_self_heal_recovery.py", "-q"], cwd=str(root), capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as error:
            return unavailable("focused_verify", _redact_recovery_detail(error))
        if int(getattr(result, "returncode", 1)) != 0:
            return unavailable("focused_verify", "fixed focused verification failed")
        return {
            "packet": {
                "kind": "recovery_focused_proof",
                "schema_version": "tradingagents.recovery_phase.v1",
                "focused_tests_passed": True,
                "passing_tests": ["tests/test_recovery_coordinator.py", "tests/test_self_heal_recovery.py"],
                "verifier_run_id": f"self-heal-verifier-{secrets.token_hex(8)}",
                "verifier_role_id": "independent_verifier",
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
    evidence_path = next(
        (
            path.resolve()
            for path in candidates
            if _path_under(path, root) and path.is_file()
        ),
        None,
    )
    if evidence_path is None:
        return None
    envelope = _read_json(evidence_path)
    payload = (
        envelope.get("payload")
        if isinstance(envelope.get("payload"), Mapping)
        else envelope
    )
    if not isinstance(payload, Mapping):
        return None
    supervisor = payload.get("supervisor_review_authority")
    advisory = payload.get("advisory_analysis")
    entry_context = payload.get("entry_context")
    hourly_ref = payload.get("hourly_packet_path")
    if (
        not isinstance(supervisor, Mapping)
        or not isinstance(advisory, Mapping)
        or not isinstance(entry_context, Mapping)
        or not isinstance(hourly_ref, str)
        or not hourly_ref
    ):
        return None
    hourly_candidate = Path(hourly_ref)
    hourly_packet = (
        hourly_candidate.resolve()
        if hourly_candidate.is_absolute()
        else (root / hourly_candidate).resolve()
    )
    if not _path_under(hourly_packet, root) or not hourly_packet.is_file():
        return None
    hourly = _read_json(hourly_packet)
    hourly_evidence = (
        hourly.get("evidence") if isinstance(hourly.get("evidence"), Mapping) else {}
    )
    hourly_review = (
        hourly_evidence.get("loss_exit_review")
        if isinstance(hourly_evidence.get("loss_exit_review"), Mapping)
        else {}
    )
    symbol_values = {
        "signal": signal.get("symbol"),
        "envelope": envelope.get("symbol"),
        "payload": payload.get("symbol"),
        "supervisor": supervisor.get("symbol"),
        "advisory": advisory.get("symbol"),
        "hourly": hourly_review.get("symbol"),
    }
    normalized_symbols = {
        name: str(value or "").strip().upper()
        for name, value in symbol_values.items()
    }
    if any(not value for value in normalized_symbols.values()) or len(
        set(normalized_symbols.values())
    ) != 1:
        return None
    symbol = normalized_symbols["signal"]
    entry_symbol = str(entry_context.get("symbol") or "").strip().upper()
    if entry_symbol and entry_symbol != symbol:
        return None

    signal_account = str(
        signal.get("broker_account") or signal.get("account") or ""
    ).strip()
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
    if (
        signal_account
        and signal_account != expected_account
        or not account_values[0]
        or any(
        account != expected_account for account in account_values
        )
    ):
        return None
    account = expected_account

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
    required_bindings = {"incident_id", "symbol", "broker_account", "environment", "source_revision"}
    canonical_bindings = dict(bindings)
    canonical_bindings["incident_id"] = incident_id
    if set(canonical_bindings) != required_bindings or not all(isinstance(value, str) and value.strip() for value in canonical_bindings.values()):
        raise ValueError("canonical recovery bindings are required")
    if not isinstance(owner_run_id, str) or not owner_run_id.strip() or not isinstance(recovery_run_id, str) or not recovery_run_id.strip():
        raise ValueError("recovery and owner run IDs are required")
    if not all(
        is_safe_incident_id(value)
        for value in (incident_id, owner_run_id, recovery_run_id, owner_role)
    ):
        return {"status": "corrupt_state", "incident_id": incident_id, "phase": None, "failure": _recovery_failure("permanent_integrity", "unsafe recovery identifier")}
    if idempotency_key is not None and (not isinstance(idempotency_key, str) or not is_safe_incident_id(idempotency_key)):
        return {"status": "corrupt_state", "incident_id": incident_id, "phase": None, "failure": _recovery_failure("permanent_integrity", "unsafe idempotency key")}
    current = _recovery_now(now)
    root = Path(recovery_root).resolve()
    incident_root = root / incident_id
    run_root = incident_root / recovery_run_id
    state_path = incident_root / "state.json"
    lock_path = incident_root / ".owner.lock"
    if not all(_path_under(path, root) for path in (incident_root, run_root, state_path, lock_path)):
        return {"status": "corrupt_state", "incident_id": incident_id, "phase": None, "failure": _recovery_failure("permanent_integrity", "recovery path escapes root")}
    descriptor, lock_status, lock_token = _recovery_lock(
        lock_path,
        incident_id=incident_id,
        owner_run_id=owner_run_id,
        lease_expires_at=(current + dt.timedelta(minutes=RECOVERY_LEASE_MINUTES)).isoformat(),
        now=current,
    )
    if descriptor is None:
        if lock_status == "corrupt_lock":
            return {"status": "corrupt_state", "incident_id": incident_id, "phase": None, "failure": _recovery_failure("permanent_integrity", "recovery lock is malformed")}
        return {"status": "owner_busy", "incident_id": incident_id, "phase": None}
    try:
        state, state_error = _read_recovery_state(state_path)
        if state_error is not None:
            _append_recovery_event(incident_root, {"event": "corrupt_state", "incident_id": incident_id, "at": current.isoformat()})
            return {"status": "corrupt_state", "incident_id": incident_id, "phase": None, "failure": _recovery_failure("permanent_integrity", "persisted recovery state is malformed")}
        if state is None:
            state = {
                "schema_version": "tradingagents.self_heal_recovery.v1",
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
            }
            _append_recovery_event(incident_root, {"event": "recovery_opened", "incident_id": incident_id, "owner_run_id": owner_run_id, "at": current.isoformat()})
        if lock_status == "stale_takeover":
            state["incident_history"].append({"event": "lock_stale_takeover", "at": current.isoformat(), "owner_run_id": owner_run_id})
            _append_recovery_event(incident_root, {"event": "lock_stale_takeover", "incident_id": incident_id, "owner_run_id": owner_run_id, "at": current.isoformat()})
        if state.get("bindings") != canonical_bindings or (state.get("recovery_run_id") != recovery_run_id and state.get("parent_recovery_run_id") != recovery_run_id):
            return {"status": "identity_mismatch_frozen", "incident_id": incident_id, "phase": state.get("phase")}
        prior_failure = state.get("last_failure") or {}
        if prior_failure.get("kind") == "transient_exhausted" and state.get("follow_on_required") is True:
            not_before = _parse_datetime(state.get("follow_on_not_before"))
            if not_before is not None and not_before > current:
                return {"status": "frozen", "incident_id": incident_id, "phase": state.get("phase"), "failure": prior_failure}
            parent_run = str(state.get("parent_recovery_run_id") or recovery_run_id)
            follow_count = int(state.get("follow_on_count") or 0) + 1
            next_run = f"{parent_run}-follow-{follow_count}"
            if not is_safe_incident_id(next_run):
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
            run_root = incident_root / next_run
            state["incident_history"].append({"event": "follow_on_opened", "at": current.isoformat(), "recovery_run_id": next_run})
            _append_recovery_event(incident_root, {"event": "follow_on_opened", "incident_id": incident_id, "recovery_run_id": next_run, "at": current.isoformat()})
        completed_keys = set(state.get("idempotency_keys") or [])
        if idempotency_key and idempotency_key in completed_keys:
            return {"status": "duplicate", "incident_id": incident_id, "phase": state.get("phase")}
        lease = _parse_datetime(state.get("lease_expires_at"))
        existing_owner = state.get("owner_run_id")
        if existing_owner != owner_run_id and lease is not None and lease > current:
            return {"status": "owner_active", "incident_id": incident_id, "phase": state.get("phase"), "owner_run_id": existing_owner}
        if existing_owner != owner_run_id:
            state["owner_run_id"] = owner_run_id
            state["owner_role"] = owner_role
            state["incident_history"].append({"event": "lease_taken_over", "at": current.isoformat(), "from_owner_run_id": existing_owner, "to_owner_run_id": owner_run_id})
            _append_recovery_event(incident_root, {"event": "lease_taken_over", "incident_id": incident_id, "at": current.isoformat(), "owner_run_id": owner_run_id})
        state["lease_expires_at"] = (current + dt.timedelta(minutes=RECOVERY_LEASE_MINUTES)).isoformat()
        retry_at = _parse_datetime(state.get("next_retry_at"))
        if retry_at is not None and retry_at > current:
            _write_recovery_state(state_path, state)
            _record_recovery_incident(root, state, now=current)
            return {"status": "retry_scheduled", "incident_id": incident_id, "phase": state.get("phase"), "next_retry_at": state["next_retry_at"]}
        prior_failure = state.get("last_failure") or {}
        if prior_failure.get("kind") in {"permanent_integrity", "forbidden_effect", "external_blocked", "transient_exhausted"}:
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
                    packet: Mapping[str, Any] = {
                        "schema_version": "tradingagents.incident.v1",
                        "stage": "ready",
                        "history": [{"event": "transitioned", "to_stage": "ready", "at": current.isoformat()}],
                        "evidence_refs": [
                            state["phase_outputs"][name]["path"]
                            for name in RECOVERY_PHASES[:5]
                        ],
                        "repairer_run_id": owner_run_id,
                        "repairer_role_id": owner_role,
                        "root_cause_resolved": True,
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
                        or verifier_role_id.casefold() == repairer_role_id.casefold()
                    ):
                        raise ValueError("focused verifier identity must be distinct")
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
                    }
                    _write_recovery_state(state_path, state)
                    if callable(fault_hook):
                        fault_hook({"boundary": "before_rearm_call", "phase": phase})
                    result = rearm(evidence=evidence, control_path=control_path, receipt_dir=receipt_dir, ttl_minutes=90, now=current)
                    if callable(fault_hook):
                        fault_hook({"boundary": "after_rearm_return", "phase": phase})
                    packet = {"kind": "verified_rearm_result", "receipt_path": result["receipt_path"], "receipt_sha256": result["receipt_sha256"], "can_submit_orders": False}
                else:
                    adapter = adapters.get(phase)
                    if not callable(adapter):
                        raise ValueError(f"missing recovery adapter for {phase}")
                    packet = _adapter_packet(adapter({"incident_id": incident_id, "bindings": dict(canonical_bindings), "owner_run_id": owner_run_id, "owner_role": owner_role, "recovery_run_id": recovery_run_id, "phase": phase, "phase_outputs": dict(state["phase_outputs"])}))
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
                failure = _failure_from_exception(error)
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
