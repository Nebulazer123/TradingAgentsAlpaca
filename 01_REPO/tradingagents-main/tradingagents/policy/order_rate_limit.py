"""Rolling-window rate limit for live order submissions.

Config-gated and default-inert: the unified live gate only enforces this when
``max_live_orders_per_window`` and ``live_order_window_minutes`` are set in the
risk envelope. The ledger records *actual* live submissions so the limit counts
real money movement across runs, not just intent within a single decision cycle.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from tradingagents.policy.io import atomic_write_text

UTC = datetime.timezone.utc

_MAX_RETAINED_RECORDS = 500


def _as_utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_ts(value: str) -> datetime.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    return _as_utc(parsed)


def _load_records(path: str | Path) -> list[dict[str, Any]]:
    state_path = Path(path)
    if not state_path.exists():
        return []
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("submissions", [])
    if not isinstance(data, list):
        return []
    return [record for record in data if isinstance(record, dict)]


def count_live_submissions_in_window(
    path: str | Path,
    *,
    now: datetime.datetime,
    window_minutes: int,
) -> int:
    cutoff = _as_utc(now) - datetime.timedelta(minutes=window_minutes)
    count = 0
    for record in _load_records(path):
        submitted_at = _parse_ts(str(record.get("submitted_at", "")))
        if submitted_at is not None and submitted_at > cutoff:
            count += 1
    return count


def record_live_order_submission(
    path: str | Path,
    *,
    client_order_id: str,
    now: datetime.datetime,
) -> None:
    records = _load_records(path)
    normalized_client_order_id = str(client_order_id)
    if any(
        str(record.get("client_order_id", "")) == normalized_client_order_id
        for record in records
    ):
        return
    records.append(
        {
            "client_order_id": normalized_client_order_id,
            "submitted_at": _as_utc(now).isoformat(timespec="seconds"),
        }
    )
    records = records[-_MAX_RETAINED_RECORDS:]
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(state_path, json.dumps({"submissions": records}, indent=2))


def evaluate_order_rate_limit(
    *,
    path: str | Path,
    now: datetime.datetime,
    window_minutes: int,
    max_orders: int,
    new_order_count: int,
) -> list[str]:
    existing = count_live_submissions_in_window(
        path, now=now, window_minutes=window_minutes
    )
    if existing + new_order_count > max_orders:
        return [
            "order rate limit blocked submit: "
            f"{existing} live order(s) in the last {window_minutes} minute(s) "
            f"+ {new_order_count} new would exceed max_live_orders_per_window "
            f"{max_orders}"
        ]
    return []
