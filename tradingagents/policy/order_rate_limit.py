"""Rolling-window rate limit for live order submissions.

Config-gated and default-inert: the unified live gate only enforces this when
``max_live_orders_per_window`` and ``live_order_window_minutes`` are set in the
risk envelope. The ledger records *actual* live submissions so the limit counts
real money movement across runs, not just intent within a single decision cycle.
"""

from __future__ import annotations

import datetime
import fcntl
import hashlib
import json
import os
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingagents.policy.io import atomic_write_text

UTC = datetime.timezone.utc
_RATE_LEDGER_SCHEMA_VERSION = 1


class LiveOrderRateLedgerError(ValueError):
    """The durable live-order rate ledger is unavailable or corrupt.

    A missing ledger is the sole safe initialization condition.  Any existing
    ledger that cannot be proved complete is retained untouched and blocks the
    submission path rather than silently reopening order capacity.
    """


@dataclass(frozen=True, slots=True)
class _RateLedgerSnapshot:
    """One validated on-disk ledger observation while its lock is held."""

    path: Path
    device: int
    inode: int
    size: int
    mtime_ns: int
    raw_sha256: str
    schema_version: int | None
    integrity_sha256: str | None
    records: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class LiveOrderRateReservation:
    """Exact durable rate slot bound to one normal-live policy handoff.

    This is an opaque data binding, not authority by itself.  The final raw
    POST and outcome writer both re-read the ledger under its shared lock and
    require every field below to remain identical.  Any deletion, corruption,
    replacement, or rewrite is therefore a fail-closed recovery condition.
    """

    path: Path
    client_order_id: str
    schema_version: int
    integrity_sha256: str
    raw_sha256: str
    device: int
    inode: int
    reservation_record_sha256: str
    binding_sha256: str


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


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _records_integrity_sha256(records: list[dict[str, Any]]) -> str:
    return _sha256(
        _canonical_json_bytes(
            {"schema_version": _RATE_LEDGER_SCHEMA_VERSION, "submissions": records}
        )
    )


def _ledger_document(records: list[dict[str, Any]]) -> dict[str, object]:
    return {
        "schema_version": _RATE_LEDGER_SCHEMA_VERSION,
        "submissions": records,
        "integrity_sha256": _records_integrity_sha256(records),
    }


def _is_regular_file(metadata: os.stat_result) -> bool:
    return (metadata.st_mode & 0o170000) == 0o100000


def _capture_ledger_snapshot(
    path: str | Path,
    *,
    require_integrity: bool,
) -> _RateLedgerSnapshot | None:
    """Read one stable ledger file and validate its exact durable contents."""

    state_path = Path(path).resolve(strict=False)
    try:
        before = os.lstat(state_path)
    except FileNotFoundError:
        return None
    if not _is_regular_file(before):
        raise LiveOrderRateLedgerError("live order rate ledger is unavailable")
    try:
        raw = state_path.read_bytes()
        after = os.lstat(state_path)
    except OSError as exc:
        raise LiveOrderRateLedgerError("live order rate ledger is unreadable") from exc
    if (
        not _is_regular_file(after)
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise LiveOrderRateLedgerError("live order rate ledger changed while reading")
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveOrderRateLedgerError("live order rate ledger is unreadable") from exc
    schema_version: int | None = None
    integrity_sha256: str | None = None
    if isinstance(data, dict) and set(data) == {
        "schema_version",
        "submissions",
        "integrity_sha256",
    }:
        if (
            type(data["schema_version"]) is not int
            or data["schema_version"] != _RATE_LEDGER_SCHEMA_VERSION
        ):
            raise LiveOrderRateLedgerError("live order rate ledger schema is invalid")
        if (
            type(data["integrity_sha256"]) is not str
            or len(data["integrity_sha256"]) != 64
            or not all(
                character in "0123456789abcdef"
                for character in data["integrity_sha256"]
            )
        ):
            raise LiveOrderRateLedgerError("live order rate ledger integrity is invalid")
        raw_records = data["submissions"]
        if type(raw_records) is not list:
            raise LiveOrderRateLedgerError("live order rate ledger submissions are invalid")
        records = [_validate_record(record) for record in raw_records]
        if data["integrity_sha256"] != _records_integrity_sha256(records):
            raise LiveOrderRateLedgerError("live order rate ledger integrity is invalid")
        schema_version = data["schema_version"]
        integrity_sha256 = data["integrity_sha256"]
    elif isinstance(data, dict) and set(data) == {"submissions"}:
        if require_integrity:
            raise LiveOrderRateLedgerError("live order rate ledger integrity is unavailable")
        raw_records = data["submissions"]
        if type(raw_records) is not list:
            raise LiveOrderRateLedgerError("live order rate ledger submissions are invalid")
        records = [_validate_record(record) for record in raw_records]
    elif type(data) is list:
        if require_integrity:
            raise LiveOrderRateLedgerError("live order rate ledger integrity is unavailable")
        records = [_validate_record(record) for record in data]
    else:
        raise LiveOrderRateLedgerError("live order rate ledger schema is invalid")
    return _RateLedgerSnapshot(
        path=state_path,
        device=after.st_dev,
        inode=after.st_ino,
        size=after.st_size,
        mtime_ns=after.st_mtime_ns,
        raw_sha256=_sha256(raw),
        schema_version=schema_version,
        integrity_sha256=integrity_sha256,
        records=tuple(records),
    )


def _load_records(path: str | Path) -> list[dict[str, Any]]:
    snapshot = _capture_ledger_snapshot(path, require_integrity=False)
    if snapshot is None:
        return []
    return [dict(record) for record in snapshot.records]


def _reservation_record_sha256(record: Mapping[str, object]) -> str:
    return _sha256(_canonical_json_bytes(dict(record)))


def _reservation_binding_sha256(
    *,
    snapshot: _RateLedgerSnapshot,
    client_order_id: str,
    reservation_record_sha256: str,
) -> str:
    return _sha256(
        _canonical_json_bytes(
            {
                "path": str(snapshot.path),
                "device": snapshot.device,
                "inode": snapshot.inode,
                "raw_sha256": snapshot.raw_sha256,
                "schema_version": snapshot.schema_version,
                "integrity_sha256": snapshot.integrity_sha256,
                "client_order_id": client_order_id,
                "reservation_record_sha256": reservation_record_sha256,
            }
        )
    )


def _reservation_from_snapshot(
    snapshot: _RateLedgerSnapshot,
    *,
    client_order_id: str,
) -> LiveOrderRateReservation:
    if (
        snapshot.schema_version != _RATE_LEDGER_SCHEMA_VERSION
        or snapshot.integrity_sha256 is None
    ):
        raise LiveOrderRateLedgerError("live order rate ledger integrity is unavailable")
    matches = [
        record
        for record in snapshot.records
        if str(record.get("client_order_id", "")) == client_order_id
    ]
    if len(matches) != 1:
        raise LiveOrderRateLedgerError("live order rate reservation is unavailable")
    record_sha256 = _reservation_record_sha256(matches[0])
    return LiveOrderRateReservation(
        path=snapshot.path,
        client_order_id=client_order_id,
        schema_version=snapshot.schema_version,
        integrity_sha256=snapshot.integrity_sha256,
        raw_sha256=snapshot.raw_sha256,
        device=snapshot.device,
        inode=snapshot.inode,
        reservation_record_sha256=record_sha256,
        binding_sha256=_reservation_binding_sha256(
            snapshot=snapshot,
            client_order_id=client_order_id,
            reservation_record_sha256=record_sha256,
        ),
    )


def _require_reservation_current_locked(
    reservation: object,
) -> _RateLedgerSnapshot:
    if type(reservation) is not LiveOrderRateReservation:
        raise LiveOrderRateLedgerError("live order rate reservation is unavailable")
    snapshot = _capture_ledger_snapshot(reservation.path, require_integrity=True)
    if snapshot is None:
        raise LiveOrderRateLedgerError("live order rate ledger is unavailable")
    if (
        _reservation_from_snapshot(snapshot, client_order_id=reservation.client_order_id)
        != reservation
    ):
        raise LiveOrderRateLedgerError("live order rate ledger changed after reservation")
    return snapshot


@contextmanager
def normal_live_order_rate_reservation_lock(reservation: object):
    """Hold the rate lock while proving one normal-live reservation is exact."""

    if type(reservation) is not LiveOrderRateReservation:
        raise LiveOrderRateLedgerError("live order rate reservation is unavailable")
    with _rate_limit_lock(reservation.path):
        _require_reservation_current_locked(reservation)
        yield


def _write_records(path: str | Path, records: list[dict[str, Any]]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(state_path, json.dumps(_ledger_document(records), indent=2))


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
    require_existing_ledger: bool = False,
) -> LiveOrderRateReservation | None:
    """Durably reserve one live-order slot before broker I/O.

    A reservation is deliberately counted like a real submission.  It remains
    fail-closed across a crash until a read-only lookup resolves the exact
    idempotency key, when it is either promoted to a submission or released.
    """

    if type(window_minutes) is not int or window_minutes <= 0:
        raise ValueError("live order reservation requires a positive window")
    if type(max_orders) is not int or max_orders <= 0:
        raise ValueError("live order reservation requires a positive maximum")
    if type(require_existing_ledger) is not bool:
        raise ValueError("live order reservation requires an exact existing-ledger flag")
    normalized_client_order_id = str(client_order_id)
    with _rate_limit_lock(path):
        # Paper/bootstrap paths may create their first ledger, but a normal-live
        # handoff has already completed its full policy work.  It must prove the
        # same ledger still exists while holding the reservation lock; otherwise
        # a deletion race would silently recreate fresh live-order capacity.
        if require_existing_ledger and not Path(path).is_file():
            raise LiveOrderRateLedgerError("live order rate ledger is unavailable")
        snapshot = _capture_ledger_snapshot(
            path, require_integrity=require_existing_ledger
        )
        if snapshot is None:
            records: list[dict[str, Any]] = []
        else:
            records = [dict(record) for record in snapshot.records]
        if any(
            str(record.get("client_order_id", "")) == normalized_client_order_id
            for record in records
        ):
            current = _capture_ledger_snapshot(path, require_integrity=True)
            if current is None:
                raise LiveOrderRateLedgerError("live order rate ledger is unavailable")
            return _reservation_from_snapshot(
                current, client_order_id=normalized_client_order_id
            )
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
        if not require_existing_ledger:
            return None
        current = _capture_ledger_snapshot(path, require_integrity=True)
        if current is None:
            raise LiveOrderRateLedgerError("live order rate ledger is unavailable")
        return _reservation_from_snapshot(
            current, client_order_id=normalized_client_order_id
        )


def record_live_order_submission(
    path: str | Path,
    *,
    client_order_id: str,
    now: datetime.datetime,
    reservation: LiveOrderRateReservation | None = None,
) -> None:
    normalized_client_order_id = str(client_order_id)
    if reservation is not None and (
        type(reservation) is not LiveOrderRateReservation
        or reservation.client_order_id != normalized_client_order_id
    ):
        raise LiveOrderRateLedgerError("live order rate reservation is unavailable")
    with _rate_limit_lock(path):
        if reservation is not None:
            snapshot = _require_reservation_current_locked(reservation)
            if snapshot.path != Path(path).resolve(strict=False):
                raise LiveOrderRateLedgerError("live order rate reservation is unavailable")
            records = [dict(record) for record in snapshot.records]
        else:
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


def release_live_order_reservation(
    path: str | Path,
    *,
    client_order_id: str,
    reservation: LiveOrderRateReservation | None = None,
) -> None:
    """Release only an unresolved reservation after read-only absence proof."""

    normalized_client_order_id = str(client_order_id)
    if reservation is not None and (
        type(reservation) is not LiveOrderRateReservation
        or reservation.client_order_id != normalized_client_order_id
    ):
        raise LiveOrderRateLedgerError("live order rate reservation is unavailable")
    with _rate_limit_lock(path):
        if reservation is not None:
            snapshot = _require_reservation_current_locked(reservation)
            if snapshot.path != Path(path).resolve(strict=False):
                raise LiveOrderRateLedgerError("live order rate reservation is unavailable")
            records = [dict(record) for record in snapshot.records]
        else:
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
