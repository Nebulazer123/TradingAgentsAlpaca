"""Tiny-live control state helpers for freeze/kill and dead-man checks."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from tradingagents.policy.integrity import (
    verify_state_integrity,
    write_state_with_integrity,
)

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
    raw_text = control_path.read_text(encoding="utf-8")
    try:
        state = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return None, [f"live control state is invalid JSON: {exc}"]
    if not isinstance(state, dict):
        return None, ["live control state must be a JSON object"]

    issues: list[str] = list(verify_state_integrity(control_path, raw_text))
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

    return state, issues


def write_live_control_state(
    path: str | Path,
    *,
    frozen: bool,
    reason: str,
    dead_man_expires_at: datetime.datetime | None = None,
) -> Path:
    control_path = Path(path)
    control_path.parent.mkdir(parents=True, exist_ok=True)
    expires_at = dead_man_expires_at or (
        datetime.datetime.now(tz=UTC) + datetime.timedelta(hours=6)
    )
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    payload = {
        "frozen": bool(frozen),
        "reason": reason,
        "dead_man_expires_at": expires_at.astimezone(UTC).isoformat(timespec="seconds"),
        "updated_at": datetime.datetime.now(tz=UTC).isoformat(timespec="seconds"),
    }
    write_state_with_integrity(
        control_path, json.dumps(payload, indent=2), actor="live_control"
    )
    return control_path
