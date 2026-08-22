"""Deterministic, read-only safety-sentinel evidence packets.

The sentinel is an observer.  Its result can block or describe a condition, but
it never changes live control, schedules, broker orders, promotions, or any
other authority surface.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tradingagents.evals.automation_health_audit import (
    PREDEPLOYMENT_PAUSED_PHASE,
    evaluate_schedule_contract,
)

UTC = dt.timezone.utc
SCHEMA_VERSION = "safety_sentinel_v1"
DEFAULT_MAX_EVIDENCE_AGE_MINUTES = 90.0
FORBIDDEN_EFFECTS = (
    "submit_order",
    "cancel_order",
    "replace_order",
    "freeze_live_control",
    "rearm_live_control",
    "update_automation",
    "promote_strategy",
    "send_email",
)


def _as_utc(value: dt.datetime | None) -> dt.datetime:
    if value is None:
        return dt.datetime.now(tz=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _capture_json_evidence(path_value: str | Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Capture exact source bytes and parse one JSON input without mutation."""

    path = Path(path_value)
    evidence: dict[str, Any] = {"path": str(path), "sha256": None, "size_bytes": None}
    try:
        raw = path.read_bytes()
    except OSError:
        evidence["status"] = "missing"
        return evidence, None
    evidence["sha256"] = hashlib.sha256(raw).hexdigest()
    evidence["size_bytes"] = len(raw)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        evidence["status"] = "corrupt"
        return evidence, None
    if not isinstance(payload, dict):
        evidence["status"] = "corrupt"
        return evidence, None
    evidence["status"] = "captured"
    return evidence, payload


def _capture_file_evidence(path_value: str | Path) -> dict[str, Any]:
    """Capture an exact digest for a non-JSON schedule input."""

    path = Path(path_value)
    evidence: dict[str, Any] = {"path": str(path), "sha256": None, "size_bytes": None}
    try:
        raw = path.read_bytes()
    except OSError:
        evidence["status"] = "missing"
        return evidence
    evidence.update(
        {
            "status": "captured",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }
    )
    return evidence


def capture_read_only_broker_snapshot(client: Any) -> dict[str, Any]:
    """Read the four permitted Alpaca resources and retain failures as evidence."""

    snapshot: dict[str, Any] = {
        "account": {},
        "positions": [],
        "open_orders": [],
        "clock": {},
        "errors": {},
        "read_methods": ["get_account", "list_positions", "list_orders", "get_clock"],
    }
    readers = (
        ("account", "get_account", {}, lambda method: method()),
        ("positions", "list_positions", [], lambda method: method()),
        ("open_orders", "list_orders", [], lambda method: method(status="open")),
        ("clock", "get_clock", {}, lambda method: method()),
    )
    for key, method_name, default, invoke in readers:
        try:
            snapshot[key] = invoke(getattr(client, method_name))
        except Exception as exc:  # noqa: BLE001 - a failed observer read must be visible.
            snapshot[key] = default
            snapshot["errors"][key] = f"{method_name} failed: {exc}"
    return snapshot


def _preopen_reasons(
    evidence: Mapping[str, Any],
    payload: Mapping[str, Any] | None,
    *,
    now: dt.datetime,
    max_evidence_age_minutes: float,
) -> list[str]:
    if evidence.get("status") == "missing":
        return ["preopen_validation_missing"]
    if evidence.get("status") != "captured" or payload is None:
        return ["preopen_validation_corrupt"]
    reasons: list[str] = []
    generated_at = _parse_timestamp(payload.get("generated_at"))
    if generated_at is None:
        reasons.append("preopen_validation_generated_at_invalid")
    elif now - generated_at > dt.timedelta(minutes=max_evidence_age_minutes):
        reasons.append("preopen_validation_stale")
    elif generated_at > now + dt.timedelta(minutes=5):
        reasons.append("preopen_validation_timestamp_in_future")
    if payload.get("analysis_only") is not True:
        reasons.append("preopen_validation_not_analysis_only")
    if payload.get("execution_authority") != "none":
        reasons.append("preopen_validation_execution_authority_invalid")
    if payload.get("can_submit_orders") is not False:
        reasons.append("preopen_validation_can_submit_invalid")
    if str(payload.get("overall_status") or "").lower() != "pass":
        reasons.append("preopen_validation_not_pass")
    return reasons


def build_safety_sentinel_packet(
    *,
    live_control_path: str | Path,
    preopen_validation_path: str | Path,
    schedule_contract_path: str | Path,
    automation_root: str | Path,
    role_contract_path: str | Path,
    broker_snapshot: Mapping[str, Any] | None,
    now: dt.datetime | None = None,
    max_evidence_age_minutes: float = DEFAULT_MAX_EVIDENCE_AGE_MINUTES,
) -> dict[str, Any]:
    """Build a non-authorizing observer packet from immutable read evidence."""

    generated_at = _as_utc(now)
    live_control_evidence, live_control = _capture_json_evidence(live_control_path)
    preopen_evidence, preopen = _capture_json_evidence(preopen_validation_path)
    schedule_evidence = _capture_file_evidence(schedule_contract_path)
    role_evidence = _capture_file_evidence(role_contract_path)
    evidence = {
        "live_control": live_control_evidence,
        "preopen_validation": preopen_evidence,
        "schedule_contract": schedule_evidence,
        "role_contract": role_evidence,
    }

    reasons: list[str] = []
    frozen_control = False
    if live_control_evidence["status"] == "missing":
        reasons.append("live_control_missing")
    elif live_control_evidence["status"] != "captured" or live_control is None:
        reasons.append("live_control_corrupt")
    elif live_control.get("frozen") is True:
        frozen_control = True
        reasons.append("frozen_control")
    elif live_control.get("frozen") is not False:
        reasons.append("live_control_frozen_flag_invalid")

    if max_evidence_age_minutes <= 0:
        reasons.append("max_evidence_age_minutes_invalid")
    else:
        reasons.extend(
            _preopen_reasons(
                preopen_evidence,
                preopen,
                now=generated_at,
                max_evidence_age_minutes=max_evidence_age_minutes,
            )
        )

    schedule_check = evaluate_schedule_contract(
        contract_path=schedule_contract_path,
        automation_root=automation_root,
        role_contract_path=role_contract_path,
        deployment_phase=PREDEPLOYMENT_PAUSED_PHASE,
    )
    schedule_check = dict(schedule_check)
    schedule_check["deployment_phase"] = PREDEPLOYMENT_PAUSED_PHASE
    if schedule_evidence["status"] != "captured":
        reasons.append("schedule_contract_missing")
    if role_evidence["status"] != "captured":
        reasons.append("role_contract_missing")
    if (
        schedule_check.get("contract_status") != "pass"
        or schedule_check.get("safe_predeployment") is not True
        or bool(schedule_check.get("issues"))
        or any(
            row.get("status") != "match"
            for row in schedule_check.get("automations", [])
            if isinstance(row, Mapping)
        )
    ):
        reasons.append("schedule_contract_unsafe")

    snapshot = dict(broker_snapshot or {})
    broker_errors = snapshot.get("errors")
    if not isinstance(broker_errors, Mapping):
        reasons.append("broker_snapshot_errors_invalid")
        broker_errors = {"errors": "invalid"}
    if broker_errors:
        reasons.append("broker_read_failed")
    for key in ("account", "positions", "open_orders", "clock"):
        if key not in snapshot:
            reasons.append(f"broker_snapshot_{key}_missing")

    status = "FROZEN" if frozen_control else ("HOLD" if reasons else "CLEAR")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "safety_sentinel_audit",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "status": status,
        "reasons": sorted(set(reasons)),
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "forbidden_effects": list(FORBIDDEN_EFFECTS),
        "actions_taken": [],
        "evidence": evidence,
        "schedule_check": schedule_check,
        "broker_snapshot": {
            "account": snapshot.get("account", {}),
            "positions": snapshot.get("positions", []),
            "open_orders": snapshot.get("open_orders", []),
            "clock": snapshot.get("clock", {}),
            "errors": dict(broker_errors),
            "read_methods": snapshot.get("read_methods", []),
        },
    }


def write_safety_sentinel_packet(
    packet: Mapping[str, Any],
    *,
    output_dir: str | Path = Path("results/safety_sentinel"),
) -> Path:
    """Write one immutable observer packet; no aliases or authority state change."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    generated_at = _parse_timestamp(packet.get("generated_at")) or dt.datetime.now(tz=UTC)
    stem = generated_at.strftime("safety-sentinel-%Y%m%d-%H%M%S-%f")
    output_path = root / f"{stem}.json"
    for index in range(1, 1000):
        if not output_path.exists():
            break
        output_path = root / f"{stem}-{index:03d}.json"
    else:
        raise RuntimeError("could not allocate a safety-sentinel packet path")
    payload = dict(packet)
    payload["packet_path"] = str(output_path)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path
