"""Tiny-live control state helpers for freeze/kill and dead-man checks."""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from tradingagents.policy.io import atomic_write_text

UTC = datetime.timezone.utc


def parse_control_time(value: str) -> datetime.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_live_control_state(
    path: str | Path,
    *,
    now: datetime.datetime | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    control_path = Path(path)
    if not control_path.exists():
        return None, [f"live control state missing at {control_path}"]
    try:
        state = json.loads(control_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, [f"live control state is invalid JSON: {exc}"]
    if not isinstance(state, dict):
        return None, ["live control state must be a JSON object"]

    issues: list[str] = []
    if type(state.get("frozen")) is not bool:
        issues.append("live control state frozen must be a literal boolean")
    if state.get("frozen") is True:
        reason = str(state.get("reason") or "no reason recorded")
        issues.append(f"live control state is frozen: {reason}")

    current = now or datetime.datetime.now(tz=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    expires_at = parse_control_time(str(state.get("dead_man_expires_at", "")))
    if expires_at is None:
        issues.append("live control state missing valid dead_man_expires_at")
    elif expires_at <= current:
        issues.append(f"dead-man expired at {expires_at.isoformat()}")

    recovery_fields = {"recovery_receipt_path", "recovery_receipt_sha256", "recovery_incident_id", "recovery_mode"}
    has_recovery_marker = any(key in state for key in recovery_fields)
    if has_recovery_marker and (set(key for key in recovery_fields if key in state) != recovery_fields or state.get("recovery_mode") != "verified_recovery" or state.get("frozen") is not False or not isinstance(state.get("recovery_incident_id"), str) or not state["recovery_incident_id"].strip()):
        issues.append("verified recovery control has incomplete or unsafe markers")
    receipt_path = state.get("recovery_receipt_path")
    receipt_digest = state.get("recovery_receipt_sha256")
    if has_recovery_marker:
        if not isinstance(receipt_path, str) or not receipt_path.strip():
            issues.append("verified recovery control missing receipt path")
        elif not isinstance(receipt_digest, str) or len(receipt_digest) != 64 or any(char not in "0123456789abcdef" for char in receipt_digest):
            issues.append("verified recovery control missing receipt digest")
        elif not Path(receipt_path).is_absolute() or str(Path(receipt_path).resolve()) != receipt_path:
            issues.append("verified recovery receipt path must be absolute")
        else:
            candidate = Path(receipt_path)
            try:
                raw_receipt = candidate.read_bytes()
                actual_digest = hashlib.sha256(raw_receipt).hexdigest()
                receipt = json.loads(raw_receipt)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                issues.append("verified recovery receipt is missing or corrupt")
            else:
                if actual_digest != receipt_digest:
                    issues.append("verified recovery receipt digest mismatch")
                if not isinstance(receipt, dict):
                    issues.append("verified recovery receipt must be a JSON object")
                elif receipt.get("schema_version") != 1:
                    issues.append("verified recovery receipt has wrong schema")
                elif receipt.get("kind") != "verified_rearm_receipt":
                    issues.append("verified recovery receipt has wrong kind")
                elif receipt.get("effective_only_when_control_matches_receipt_digest") is not True:
                    issues.append("verified recovery receipt lacks effective binding")
                elif receipt.get("can_submit_orders") is not False or type(receipt.get("broker_write_calls")) is not int or receipt.get("broker_write_calls") != 0:
                    issues.append("verified recovery receipt has unsafe authority fields")
                elif (
                    not isinstance(receipt.get("source_bindings"), dict)
                    or set(receipt["source_bindings"]) != {"incident_id", "symbol", "broker_account", "environment", "source_revision"}
                    or not isinstance(receipt.get("source_packet_sha256"), dict)
                    or not isinstance(receipt.get("source_packet_paths"), dict)
                    or set(receipt["source_packet_sha256"]) != {"incident", "reconciliation", "promotion", "focused"}
                    or set(receipt["source_packet_paths"]) != {"incident", "reconciliation", "promotion", "focused"}
                ):
                    issues.append("verified recovery receipt lacks source proof")
                else:
                    source_bindings = receipt["source_bindings"]
                    source_hashes = receipt["source_packet_sha256"]
                    source_paths = receipt["source_packet_paths"]
                    if (
                        any(not isinstance(source_bindings[key], str) or not source_bindings[key].strip() for key in source_bindings)
                        or source_bindings.get("incident_id") != state.get("recovery_incident_id")
                        or any(not isinstance(source_hashes[key], str) or len(source_hashes[key]) != 64 or any(char not in "0123456789abcdef" for char in source_hashes[key]) for key in source_hashes)
                        or any(not isinstance(source_paths[key], str) or not source_paths[key] or not Path(source_paths[key]).is_absolute() or str(Path(source_paths[key]).resolve()) != source_paths[key] for key in source_paths)
                    ):
                        issues.append("verified recovery receipt has invalid source proof")
                    receipt_expires_raw = receipt.get("expires_at")
                    receipt_issued_raw = receipt.get("issued_at")
                    receipt_expires_at = parse_control_time(str(receipt_expires_raw or ""))
                    receipt_issued_at = parse_control_time(str(receipt_issued_raw or ""))
                    ttl_minutes = receipt.get("ttl_minutes")
                    if (
                        not isinstance(receipt_expires_raw, str)
                        or not isinstance(receipt_issued_raw, str)
                        or not (receipt_expires_raw.endswith("Z") or "+" in receipt_expires_raw[10:])
                        or not (receipt_issued_raw.endswith("Z") or "+" in receipt_issued_raw[10:])
                        or receipt_expires_at is None
                        or receipt_issued_at is None
                        or type(ttl_minutes) is not int
                        or receipt_issued_at + datetime.timedelta(minutes=ttl_minutes) != receipt_expires_at
                        or receipt_expires_at <= current
                    ):
                        issues.append("verified recovery receipt is expired or invalid")
                    binding = receipt.get("control_binding")
                    if not isinstance(binding, dict) or binding != {
                        "control_path": str(control_path.resolve()),
                        "incident_id": state.get("recovery_incident_id"),
                        "reason": state.get("reason"),
                        "dead_man_expires_at": state.get("dead_man_expires_at"),
                        "frozen": False,
                        "mode": state.get("recovery_mode"),
                        "receipt_path": receipt_path,
                    }:
                        issues.append("verified recovery receipt control binding mismatch")

    return state, issues


def write_live_control_state(
    path: str | Path,
    *,
    frozen: bool,
    reason: str,
    dead_man_expires_at: datetime.datetime | None = None,
    recovery_receipt_path: str | None = None,
    recovery_receipt_sha256: str | None = None,
    recovery_incident_id: str | None = None,
    recovery_mode: str | None = None,
) -> Path:
    control_path = Path(path)
    control_path.parent.mkdir(parents=True, exist_ok=True)
    expires_at = dead_man_expires_at or (datetime.datetime.now(tz=UTC) + datetime.timedelta(hours=6))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    payload = {
        "frozen": bool(frozen),
        "reason": reason,
        "dead_man_expires_at": expires_at.astimezone(UTC).isoformat(timespec="seconds"),
        "updated_at": datetime.datetime.now(tz=UTC).isoformat(timespec="seconds"),
    }
    if recovery_receipt_path is not None or recovery_receipt_sha256 is not None:
        if not isinstance(recovery_receipt_path, str) or not recovery_receipt_path.strip():
            raise ValueError("recovery_receipt_path must be a nonblank string")
        if not isinstance(recovery_receipt_sha256, str) or len(recovery_receipt_sha256) != 64:
            raise ValueError("recovery_receipt_sha256 must be a SHA-256 digest")
        payload["recovery_receipt_path"] = recovery_receipt_path
        payload["recovery_receipt_sha256"] = recovery_receipt_sha256
        if not isinstance(recovery_incident_id, str) or not recovery_incident_id.strip() or recovery_mode != "verified_recovery":
            raise ValueError("verified recovery control requires incident and mode")
        payload["recovery_incident_id"] = recovery_incident_id.strip()
        payload["recovery_mode"] = recovery_mode
    atomic_write_text(control_path, json.dumps(payload, indent=2))
    return control_path
