"""Supervisor error self-heal handoff packets.

The handoff is deliberately advisory. It can tell Codex or n8n when a fresh
repair chat is warranted, but it cannot trade, approve, or edit anything by
itself.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

from tradingagents.orchestration.recovery import RecoveryEvidence, rearm_after_verified_recovery
from tradingagents.policy.io import atomic_write_text

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


def _read_recovery_state(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_recovery_state(path: Path, state: Mapping[str, Any]) -> None:
    atomic_write_text(path, json.dumps(state, indent=2, sort_keys=True))


def _recovery_lock(path: Path) -> int | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return None


def _release_recovery_lock(path: Path, descriptor: int) -> None:
    os.close(descriptor)
    with suppress(FileNotFoundError):
        path.unlink()


def _recovery_failure(kind: str, detail: str, *, external: bool = False) -> dict[str, Any]:
    return {"kind": kind, "detail": detail[:500], "external": external}


def _phase_path(run_root: Path, phase: str) -> Path:
    return run_root / "packets" / f"{phase}.json"


def _phase_record(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _recovery_digest(path)}


def _valid_phase_record(record: object) -> bool:
    if not isinstance(record, Mapping):
        return False
    path = record.get("path")
    digest = record.get("sha256")
    if not isinstance(path, str) or not isinstance(digest, str) or len(digest) != 64:
        return False
    try:
        return _recovery_digest(Path(path)) == digest
    except OSError:
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
    current = _recovery_now(now)
    root = Path(recovery_root).resolve()
    incident_root = root / incident_id
    run_root = incident_root / recovery_run_id
    state_path = incident_root / "state.json"
    lock_path = incident_root / ".owner.lock"
    descriptor = _recovery_lock(lock_path)
    if descriptor is None:
        return {"status": "owner_busy", "incident_id": incident_id, "phase": None}
    try:
        state = _read_recovery_state(state_path)
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
        if state.get("bindings") != canonical_bindings or state.get("recovery_run_id") != recovery_run_id:
            return {"status": "identity_mismatch_frozen", "incident_id": incident_id, "phase": state.get("phase")}
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
                if not _valid_phase_record(record):
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
                        "evidence_refs": [item["path"] for item in state["phase_outputs"].values()],
                        "repairer_run_id": owner_run_id,
                        "repairer_role_id": owner_role,
                        "root_cause_resolved": True,
                        "external_blockers": [],
                    }
                elif phase == "manifest":
                    source_names = {"incident": "ready_incident", "reconciliation": "reconcile", "promotion": "sync_promotion", "focused": "focused_verify"}
                    packet = {
                        "schema_version": "tradingagents.recovery_manifest.v1",
                        "kind": "verified_recovery_manifest",
                        "packet_sha256": {name: state["phase_outputs"][source]["sha256"] for name, source in source_names.items()},
                        "packet_paths": {name: state["phase_outputs"][source]["path"] for name, source in source_names.items()},
                    }
                elif phase == "rearm":
                    source_names = {"incident": "ready_incident", "reconciliation": "reconcile", "promotion": "sync_promotion", "focused": "focused_verify"}
                    paths = {name: state["phase_outputs"][source]["path"] for name, source in source_names.items()}
                    focused = json.loads(Path(paths["focused"]).read_text(encoding="utf-8"))
                    verifier_run_id = focused.get("verifier_run_id")
                    verifier_role_id = focused.get("verifier_role_id")
                    if not isinstance(verifier_run_id, str) or not isinstance(verifier_role_id, str) or verifier_run_id == owner_run_id or verifier_role_id == owner_role:
                        raise ValueError("focused verifier identity must be distinct")
                    state["verifier_run_id"] = verifier_run_id
                    evidence = RecoveryEvidence(
                        incident_id=incident_id,
                        repairer_run_id=owner_run_id,
                        verifier_run_id=verifier_run_id,
                        repairer_role_id=owner_role,
                        verifier_role_id=verifier_role_id,
                        root_cause_resolved=True,
                        focused_tests_passed=focused.get("focused_tests_passed") is True,
                        promotion_evidence_fresh=json.loads(Path(paths["promotion"]).read_text(encoding="utf-8")).get("promotion_evidence_fresh") is True,
                        promotion_issues=tuple(json.loads(Path(paths["promotion"]).read_text(encoding="utf-8")).get("issues", [])),
                        broker_reconciliation_matched=json.loads(Path(paths["reconciliation"]).read_text(encoding="utf-8")).get("matched") is True,
                        broker_reconciliation_issues=tuple(json.loads(Path(paths["reconciliation"]).read_text(encoding="utf-8")).get("issues", [])),
                        broker_write_calls=json.loads(Path(paths["reconciliation"]).read_text(encoding="utf-8")).get("broker_write_calls", -1),
                        external_blockers=(),
                        source_bindings=canonical_bindings,
                        source_packet_paths=paths,
                        source_packet_sha256={name: state["phase_outputs"][source]["sha256"] for name, source in source_names.items()},
                        recovery_manifest_path=state["phase_outputs"]["manifest"]["path"],
                        recovery_manifest_sha256=state["phase_outputs"]["manifest"]["sha256"],
                    )
                    result = rearm(evidence=evidence, control_path=control_path, receipt_dir=receipt_dir, ttl_minutes=90, now=current)
                    packet = {"kind": "verified_rearm_result", "receipt_path": result["receipt_path"], "receipt_sha256": result["receipt_sha256"], "can_submit_orders": False}
                else:
                    adapter = adapters.get(phase)
                    if not callable(adapter):
                        raise ValueError(f"missing recovery adapter for {phase}")
                    packet = _adapter_packet(adapter({"incident_id": incident_id, "bindings": dict(canonical_bindings), "owner_run_id": owner_run_id, "owner_role": owner_role, "recovery_run_id": recovery_run_id, "phase": phase, "phase_outputs": dict(state["phase_outputs"])}))
                packet = _canonical_packet(packet, canonical_bindings, current)
                record = _write_phase_packet(phase_path, packet)
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
                        state["next_retry_at"] = (current + dt.timedelta(seconds=RECOVERY_BACKOFF_SECONDS[-1])).isoformat()
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
        return {"status": "monitoring", "incident_id": incident_id, "phase": "monitoring", "recovery_run_id": recovery_run_id}
    finally:
        _release_recovery_lock(lock_path, descriptor)


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
