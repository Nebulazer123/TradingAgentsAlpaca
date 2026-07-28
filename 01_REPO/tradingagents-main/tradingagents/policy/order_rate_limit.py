"""Rolling-window rate limit for live order submissions.

Config-gated and default-inert: the unified live gate only enforces this when
``max_live_orders_per_window`` and ``live_order_window_minutes`` are set in the
risk envelope. The ledger records *actual* live submissions so the limit counts
real money movement across runs, not just intent within a single decision cycle.
"""

from __future__ import annotations

import datetime
import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tradingagents.policy.io import atomic_write_text

UTC = datetime.timezone.utc


class LiveOrderRateLedgerError(ValueError):
    """The durable live-order rate ledger is unavailable or corrupt.

    A missing ledger is the sole safe initialization condition.  Any existing
    ledger that cannot be proved complete is retained untouched and blocks the
    submission path rather than silently reopening order capacity.
    """


def _rate_lock_path(path: str | Path) -> Path:
    state_path = Path(path)
    return state_path.with_name(f".{state_path.name}.rate.lock")


@contextmanager
def _rate_limit_lock(path: str | Path):
    """Serialize rate reservation/record transitions for one ledger."""

    lock_path = _rate_lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _as_utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_ts(value: object, *, label: str) -> datetime.datetime:
    if type(value) is not str:
        raise LiveOrderRateLedgerError(f"live order rate ledger {label} is invalid")
    raw = value.strip()
    if not raw:
        raise LiveOrderRateLedgerError(f"live order rate ledger {label} is invalid")
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError as exc:
        raise LiveOrderRateLedgerError(
            f"live order rate ledger {label} is invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.microsecond:
        raise LiveOrderRateLedgerError(f"live order rate ledger {label} is invalid")
    return parsed.astimezone(UTC)


def _validate_record(record: object) -> dict[str, Any]:
    if type(record) is not dict:
        raise LiveOrderRateLedgerError("live order rate ledger record is invalid")
    allowed = {"client_order_id", "state", "submitted_at"}
    if set(record) - allowed or {"client_order_id", "submitted_at"} - set(record):
        raise LiveOrderRateLedgerError("live order rate ledger record is invalid")
    if type(record["client_order_id"]) is not str or not record["client_order_id"]:
        raise LiveOrderRateLedgerError("live order rate ledger record is invalid")
    if "state" in record and record["state"] != "reserved":
        raise LiveOrderRateLedgerError("live order rate ledger record is invalid")
    _parse_ts(record["submitted_at"], label="submitted_at")
    return dict(record)


def _load_records(path: str | Path) -> list[dict[str, Any]]:
    state_path = Path(path)
    if not state_path.exists():
        return []
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveOrderRateLedgerError("live order rate ledger is unreadable") from exc
    if isinstance(data, dict):
        if set(data) != {"submissions"}:
            raise LiveOrderRateLedgerError("live order rate ledger schema is invalid")
        data = data["submissions"]
    if type(data) is not list:
        raise LiveOrderRateLedgerError("live order rate ledger submissions are invalid")
    return [_validate_record(record) for record in data]


def _write_records(path: str | Path, records: list[dict[str, Any]]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(state_path, json.dumps({"submissions": records}, indent=2))


def _records_in_window(
    records: list[dict[str, Any]],
    *,
    now: datetime.datetime,
    window_minutes: int,
) -> list[dict[str, Any]]:
    cutoff = _as_utc(now) - datetime.timedelta(minutes=window_minutes)
    return [
        record
        for record in records
        if _parse_ts(record.get("submitted_at"), label="submitted_at") > cutoff
    ]


def count_live_submissions_in_window(
    path: str | Path,
    *,
    now: datetime.datetime,
    window_minutes: int,
    exclude_client_order_id: str | None = None,
) -> int:
    records = _records_in_window(
        _load_records(path), now=now, window_minutes=window_minutes
    )
    if exclude_client_order_id is not None:
        records = [
            record
            for record in records
            if str(record.get("client_order_id", "")) != exclude_client_order_id
        ]
    return len(records)


def reserve_live_order_submission(
    path: str | Path,
    *,
    client_order_id: str,
    now: datetime.datetime,
    window_minutes: int,
    max_orders: int,
) -> None:
    """Durably reserve one live-order slot before broker I/O.

    A reservation is deliberately counted like a real submission.  It remains
    fail-closed across a crash until a read-only lookup resolves the exact
    idempotency key, when it is either promoted to a submission or released.
    """

    if type(window_minutes) is not int or window_minutes <= 0:
        raise ValueError("live order reservation requires a positive window")
    if type(max_orders) is not int or max_orders <= 0:
        raise ValueError("live order reservation requires a positive maximum")
    normalized_client_order_id = str(client_order_id)
    with _rate_limit_lock(path):
        records = _load_records(path)
        if any(
            str(record.get("client_order_id", "")) == normalized_client_order_id
            for record in records
        ):
            return
        existing = len(
            _records_in_window(records, now=now, window_minutes=window_minutes)
        )
        if existing + 1 > max_orders:
            raise ValueError(
                "order rate limit blocked submit: "
                f"{existing} live order(s) in the last {window_minutes} minute(s) "
                f"+ 1 new would exceed max_live_orders_per_window {max_orders}"
            )
        records.append(
            {
                "client_order_id": normalized_client_order_id,
                "state": "reserved",
                "submitted_at": _as_utc(now).isoformat(timespec="seconds"),
            }
        )
        # Do not truncate a blind tail here.  The configured rolling window is
        # evaluated at read time, and dropping a still-active record would
        # silently reopen live capacity after the 500th order.
        _write_records(path, records)


def record_live_order_submission(
    path: str | Path,
    *,
    client_order_id: str,
    now: datetime.datetime,
) -> None:
    normalized_client_order_id = str(client_order_id)
    with _rate_limit_lock(path):
        records = _load_records(path)
        for record in records:
            if str(record.get("client_order_id", "")) != normalized_client_order_id:
                continue
            # A reservation exists before broker I/O.  Once the broker confirms
            # acceptance, its acceptance moment—not the earlier reservation—is
            # the only correct rolling-window timestamp.
            confirmed_at = _as_utc(now)
            if confirmed_at.microsecond:
                raise ValueError("live order acceptance time must be whole-second UTC")
            reserved_at = _parse_ts(record["submitted_at"], label="submitted_at")
            if confirmed_at < reserved_at:
                # A proven idempotent recovery can find an order that predates
                # this process's fresh reservation.  Keep the newer durable
                # reservation timestamp instead of backdating this ledger and
                # reopening capacity.  A newly submitted POST is rejected
                # earlier, against its exact control commitment.
                confirmed_at = reserved_at
            record.pop("state", None)
            record["submitted_at"] = confirmed_at.isoformat(timespec="seconds")
            _write_records(path, records)
            return
        confirmed_at = _as_utc(now)
        if confirmed_at.microsecond:
            raise ValueError("live order acceptance time must be whole-second UTC")
        records.append(
            {
                "client_order_id": normalized_client_order_id,
                "submitted_at": confirmed_at.isoformat(timespec="seconds"),
            }
        )
        _write_records(path, records)


def release_live_order_reservation(path: str | Path, *, client_order_id: str) -> None:
    """Release only an unresolved reservation after read-only absence proof."""

    normalized_client_order_id = str(client_order_id)
    with _rate_limit_lock(path):
        records = _load_records(path)
        retained = [
            record
            for record in records
            if not (
                str(record.get("client_order_id", "")) == normalized_client_order_id
                and record.get("state") == "reserved"
            )
        ]
        if len(retained) != len(records):
            _write_records(path, retained)


def evaluate_order_rate_limit(
    *,
    path: str | Path,
    now: datetime.datetime,
    window_minutes: int,
    max_orders: int,
    new_order_count: int,
    exclude_client_order_id: str | None = None,
) -> list[str]:
    existing = count_live_submissions_in_window(
        path,
        now=now,
        window_minutes=window_minutes,
        exclude_client_order_id=exclude_client_order_id,
    )
    if existing + new_order_count > max_orders:
        return [
            "order rate limit blocked submit: "
            f"{existing} live order(s) in the last {window_minutes} minute(s) "
            f"+ {new_order_count} new would exceed max_live_orders_per_window "
            f"{max_orders}"
        ]
    return []
