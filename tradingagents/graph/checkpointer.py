"""LangGraph checkpoint support for resumable analysis runs.

Per-ticker SQLite databases so concurrent tickers don't contend.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import os
import re
import sqlite3
import stat
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, message_to_dict
from langgraph.checkpoint.sqlite import SqliteSaver

from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.graph.checkpoint_identity import (
    CheckpointRunIdentity,
    CheckpointRunIdentityError,
    validate_checkpoint_run_identity,
)

_IDENTITY_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def _json_checkpoint_metadata(value: Any) -> Any:
    """Encode message-bearing write metadata without changing typed state.

    The locked SQLite saver JSON-encodes metadata separately from its typed
    checkpoint serializer. LangGraph can include BaseMessage values in writes.
    Keep their complete standard message envelope there; do not stringify
    arbitrary objects, discard writes, or alter the serialized channel values.
    """
    if isinstance(value, BaseMessage):
        return _json_checkpoint_metadata(message_to_dict(value))
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("checkpoint metadata keys must be strings")
        return {key: _json_checkpoint_metadata(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_checkpoint_metadata(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("checkpoint metadata contains an unsupported value")


class _MessageMetadataSqliteSaver(SqliteSaver):
    def put(self, config, checkpoint, metadata, new_versions):
        return super().put(config, checkpoint, _json_checkpoint_metadata(metadata), new_versions)


class CheckpointCustodyError(RuntimeError):
    """Raised when checkpoint storage fails its local custody checks."""


@dataclass(frozen=True)
class CheckpointStatus:
    """The deliberately small, secret-safe inspection view of one checkpoint."""

    ticker: str
    trade_date: str
    identity_digest: str
    latest_step: int | None
    recorded_at: str | None
    source_revision: str | None
    compatibility: str

    def to_dict(self) -> dict[str, object]:
        """Return a receipt that does not expose graph state or model inputs."""
        return {
            "ticker": self.ticker,
            "trade_date": self.trade_date,
            "identity_digest": self.identity_digest,
            "latest_step": self.latest_step,
            "recorded_at": self.recorded_at,
            "source_revision": self.source_revision,
            "compatibility": self.compatibility,
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }


@dataclass(frozen=True)
class CheckpointRetentionCandidate:
    """A stale checkpoint that needs an exact, separate recovery decision."""

    ticker: str
    trade_date: str
    identity_digest: str
    latest_step: int | None
    recorded_at: str
    category: str
    requires_exact_clear: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "trade_date": self.trade_date,
            "identity_digest": self.identity_digest,
            "latest_step": self.latest_step,
            "recorded_at": self.recorded_at,
            "category": self.category,
            "requires_exact_clear": self.requires_exact_clear,
        }


@dataclass(frozen=True)
class CheckpointRetentionReport:
    """Read-only retention evidence; this report never removes storage."""

    max_age_days: int
    generated_at: str
    candidates: tuple[CheckpointRetentionCandidate, ...]
    deleted_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "max_age_days": self.max_age_days,
            "generated_at": self.generated_at,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "deleted_count": self.deleted_count,
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        }


def _checkpoint_root(data_dir: str | Path, *, create: bool) -> Path | None:
    """Return a private, non-symlink checkpoint root below ``data_dir``."""
    data_path = Path(data_dir).expanduser()
    if create:
        data_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not data_path.exists():
        return None
    try:
        base = data_path.resolve(strict=True)
    except OSError as exc:
        raise CheckpointCustodyError("could not resolve checkpoint data directory") from exc
    if not base.is_dir():
        raise CheckpointCustodyError("checkpoint data directory must be a directory")

    root = base / "checkpoints"
    if root.is_symlink():
        raise CheckpointCustodyError("checkpoint root must not be a symlink")
    if create:
        root.mkdir(parents=False, exist_ok=True, mode=0o700)
    if not root.exists():
        return None
    _verify_private_directory(root)
    resolved_root = root.resolve(strict=True)
    try:
        resolved_root.relative_to(base)
    except ValueError as exc:
        raise CheckpointCustodyError(
            "checkpoint root escaped the configured data directory"
        ) from exc
    return resolved_root


def _verify_private_directory(path: Path) -> None:
    """Require a current-user owned directory with no group/world permissions."""
    try:
        details = path.lstat()
    except OSError as exc:
        raise CheckpointCustodyError("could not inspect checkpoint directory") from exc
    if stat.S_ISLNK(details.st_mode):
        raise CheckpointCustodyError("checkpoint root must not be a symlink")
    if not stat.S_ISDIR(details.st_mode):
        raise CheckpointCustodyError("checkpoint root must be a directory")
    if details.st_uid != os.geteuid():
        raise CheckpointCustodyError("checkpoint root must be owned by the current user")
    if details.st_mode & 0o077:
        os.chmod(path, 0o700)
        details = path.lstat()
    if details.st_mode & 0o077:
        raise CheckpointCustodyError("checkpoint root must be owner-only")


def _verify_private_regular_file(path: Path, root: Path, *, allow_missing: bool) -> bool:
    """Verify a checkpoint SQLite file is private, regular, and stays in ``root``."""
    if path.is_symlink():
        raise CheckpointCustodyError("checkpoint database must not be a symlink")
    if not path.exists():
        if allow_missing:
            return False
        raise CheckpointCustodyError("checkpoint database is missing")
    try:
        details = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise CheckpointCustodyError("could not inspect checkpoint database") from exc
    if stat.S_ISLNK(details.st_mode):
        raise CheckpointCustodyError("checkpoint database must not be a symlink")
    if not stat.S_ISREG(details.st_mode):
        raise CheckpointCustodyError("checkpoint database must be a regular file")
    if details.st_uid != os.geteuid():
        raise CheckpointCustodyError(
            "checkpoint database must be owned by the current user"
        )
    if details.st_nlink != 1:
        raise CheckpointCustodyError("checkpoint database must not be hard-linked")
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CheckpointCustodyError(
            "checkpoint database escaped the configured checkpoint root"
        ) from exc
    if details.st_mode & 0o077:
        os.chmod(path, 0o600)
        details = path.lstat()
    if details.st_mode & 0o077:
        raise CheckpointCustodyError("checkpoint database must be owner-only")
    return True


def _secure_sqlite_files(database: Path, root: Path) -> None:
    """Verify the database and any SQLite sidecars after use."""
    _verify_private_regular_file(database, root, allow_missing=False)
    for suffix in _SQLITE_SIDECAR_SUFFIXES:
        _verify_private_regular_file(
            database.with_name(f"{database.name}{suffix}"),
            root,
            allow_missing=True,
        )


def _open_sqlite_connection(database: Path, root: Path, *, check_same_thread: bool) -> sqlite3.Connection:
    """Create the database through a no-follow descriptor before SQLite opens it."""
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open(database, flags, 0o600)
    except OSError as exc:
        raise CheckpointCustodyError("could not open checkpoint database safely") from exc
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode):
            raise CheckpointCustodyError("checkpoint database must be a regular file")
        if details.st_uid != os.geteuid() or details.st_nlink != 1:
            raise CheckpointCustodyError("checkpoint database custody validation failed")
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    _secure_sqlite_files(database, root)
    try:
        connection = sqlite3.connect(str(database), check_same_thread=check_same_thread)
    except sqlite3.Error as exc:
        raise CheckpointCustodyError("could not open checkpoint SQLite database") from exc
    _secure_sqlite_files(database, root)
    return connection


def _db_path(data_dir: str | Path, ticker: str) -> Path:
    """Return the SQLite checkpoint DB path for a ticker."""
    # Reject ticker values that would escape the checkpoints directory.
    safe = safe_ticker_component(ticker).upper()
    root = _checkpoint_root(data_dir, create=True)
    assert root is not None
    database = root / f"{safe}.db"
    if database.parent != root:
        raise CheckpointCustodyError("checkpoint database escaped its root")
    _verify_private_regular_file(database, root, allow_missing=True)
    return database


def _validated_identity_digest(
    identity_digest: str | None,
    *,
    allow_legacy_empty_signature: bool,
) -> str:
    """Return a complete identity digest or an explicitly allowed legacy empty one."""
    if identity_digest is None or identity_digest == "":
        if allow_legacy_empty_signature:
            return ""
        raise ValueError(
            "checkpoint identity digest is required; set "
            "allow_legacy_empty_signature=True only for explicit legacy access"
        )
    if type(identity_digest) is not str:
        raise TypeError("checkpoint identity digest must be a lowercase SHA-256 string")
    if _IDENTITY_SHA256.fullmatch(identity_digest) is None:
        raise ValueError("checkpoint identity digest must be a lowercase SHA-256 string")
    return identity_digest


def thread_id(
    ticker: str,
    date: str,
    identity_digest: str | None = None,
    *,
    allow_legacy_empty_signature: bool = False,
) -> str:
    """Return a deterministic ID for one ticker, date, and complete identity."""
    validated = _validated_identity_digest(
        identity_digest,
        allow_legacy_empty_signature=allow_legacy_empty_signature,
    )
    base = f"{ticker.upper()}:{date}"
    if validated:
        base = f"{base}:{validated}"
    return hashlib.sha256(base.encode()).hexdigest()[:16]


@contextmanager
def get_checkpointer(data_dir: str | Path, ticker: str) -> Generator[SqliteSaver, None, None]:
    """Context manager yielding a SqliteSaver backed by a per-ticker DB."""
    db = _db_path(data_dir, ticker)
    conn = _open_sqlite_connection(db, db.parent, check_same_thread=False)
    try:
        saver = _MessageMetadataSqliteSaver(conn)
        saver.setup()
        _secure_sqlite_files(db, db.parent)
        yield saver
    finally:
        conn.close()
        _secure_sqlite_files(db, db.parent)


def has_checkpoint(
    data_dir: str | Path,
    ticker: str,
    date: str,
    identity_digest: str | None = None,
    *,
    allow_legacy_empty_signature: bool = False,
) -> bool:
    """Check whether a resumable checkpoint exists for one complete identity."""
    return (
        checkpoint_step(
            data_dir,
            ticker,
            date,
            identity_digest,
            allow_legacy_empty_signature=allow_legacy_empty_signature,
        )
        is not None
    )


def checkpoint_step(
    data_dir: str | Path,
    ticker: str,
    date: str,
    identity_digest: str | None = None,
    *,
    allow_legacy_empty_signature: bool = False,
) -> int | None:
    """Return the step number of the latest checkpoint, or None if none exists."""
    tid = thread_id(
        ticker,
        date,
        identity_digest,
        allow_legacy_empty_signature=allow_legacy_empty_signature,
    )
    db = _db_path(data_dir, ticker)
    if not db.exists():
        return None
    with get_checkpointer(data_dir, ticker) as saver:
        config = {"configurable": {"thread_id": tid}}
        cp = saver.get_tuple(config)
        if cp is None:
            return None
        return cp.metadata.get("step")


def _checkpoint_values(checkpoint: Any) -> Mapping[str, object] | None:
    """Return saved channel values only when the LangGraph record has a mapping."""
    raw_checkpoint = getattr(checkpoint, "checkpoint", None)
    if not isinstance(raw_checkpoint, Mapping):
        return None
    values = raw_checkpoint.get("channel_values")
    return values if isinstance(values, Mapping) else None


def _recorded_at(values: Mapping[str, object], checkpoint: Any) -> str | None:
    """Return a validated public timestamp, never arbitrary serialized state."""
    candidates = (
        values.get("run_started_at"),
        getattr(checkpoint, "metadata", {}).get("created_at"),
    )
    for candidate in candidates:
        if type(candidate) is not str:
            continue
        try:
            parsed = dt.datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            continue
        return parsed.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")
    return None


def checkpoint_status(
    data_dir: str | Path,
    ticker: str,
    date: str,
    identity_digest: str | None,
) -> CheckpointStatus:
    """Return a secret-safe inspection view for one exact checkpoint identity."""
    digest = _validated_identity_digest(
        identity_digest,
        allow_legacy_empty_signature=False,
    )
    canonical_ticker = safe_ticker_component(ticker).upper()
    canonical_date = str(date)
    database = _db_path(data_dir, canonical_ticker)
    if not database.exists():
        return CheckpointStatus(
            ticker=canonical_ticker,
            trade_date=canonical_date,
            identity_digest=digest,
            latest_step=None,
            recorded_at=None,
            source_revision=None,
            compatibility="not_found",
        )

    try:
        with get_checkpointer(data_dir, canonical_ticker) as saver:
            checkpoint = saver.get_tuple(
                {
                    "configurable": {
                        "thread_id": thread_id(
                            canonical_ticker,
                            canonical_date,
                            digest,
                        )
                    }
                }
            )
    except sqlite3.Error:
        return CheckpointStatus(
            ticker=canonical_ticker,
            trade_date=canonical_date,
            identity_digest=digest,
            latest_step=None,
            recorded_at=None,
            source_revision=None,
            compatibility="corrupt",
        )
    if checkpoint is None:
        return CheckpointStatus(
            ticker=canonical_ticker,
            trade_date=canonical_date,
            identity_digest=digest,
            latest_step=None,
            recorded_at=None,
            source_revision=None,
            compatibility="not_found",
        )
    values = _checkpoint_values(checkpoint)
    if values is None:
        return CheckpointStatus(
            ticker=canonical_ticker,
            trade_date=canonical_date,
            identity_digest=digest,
            latest_step=None,
            recorded_at=None,
            source_revision=None,
            compatibility="corrupt",
        )
    try:
        identity = validate_checkpoint_run_identity(values.get("checkpoint_run_identity"))
    except CheckpointRunIdentityError:
        return CheckpointStatus(
            ticker=canonical_ticker,
            trade_date=canonical_date,
            identity_digest=digest,
            latest_step=None,
            recorded_at=None,
            source_revision=None,
            compatibility="corrupt",
        )
    stored_ticker = values.get("company_of_interest")
    compatibility = "compatible"
    if (
        identity.identity_sha256 != digest
        or stored_ticker != canonical_ticker
        or values.get("trade_date") != canonical_date
    ):
        compatibility = "identity_mismatch"
    step = getattr(checkpoint, "metadata", {}).get("step")
    return CheckpointStatus(
        ticker=canonical_ticker,
        trade_date=canonical_date,
        identity_digest=digest,
        latest_step=step if type(step) is int else None,
        recorded_at=_recorded_at(values, checkpoint),
        source_revision=identity.clean_source_revision,
        compatibility=compatibility,
    )


def _parse_report_time(value: str | dt.datetime | None) -> dt.datetime:
    """Return an aware UTC time for bounded, read-only retention reporting."""
    if value is None:
        return dt.datetime.now(dt.UTC)
    if isinstance(value, dt.datetime):
        parsed = value
    elif type(value) is str:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("retention report time must be ISO-8601") from exc
    else:
        raise TypeError("retention report time must be datetime, ISO-8601, or None")
    if parsed.tzinfo is None:
        raise ValueError("retention report time must include a timezone")
    return parsed.astimezone(dt.UTC)


def checkpoint_retention_report(
    data_dir: str | Path,
    *,
    max_age_days: int,
    now: str | dt.datetime | None = None,
) -> CheckpointRetentionReport:
    """Report stale completed/orphaned checkpoints without deleting any rows."""
    if type(max_age_days) is not int or max_age_days < 1:
        raise ValueError("max_age_days must be a positive integer")
    report_time = _parse_report_time(now)
    root = _checkpoint_root(data_dir, create=False)
    if root is None:
        return CheckpointRetentionReport(
            max_age_days=max_age_days,
            generated_at=report_time.isoformat().replace("+00:00", "Z"),
            candidates=(),
        )

    threshold = report_time - dt.timedelta(days=max_age_days)
    candidates: list[CheckpointRetentionCandidate] = []
    for database in sorted(root.glob("*.db")):
        _verify_private_regular_file(database, root, allow_missing=False)
        ticker = database.stem
        with get_checkpointer(root.parent, ticker) as saver:
            seen_threads: set[str] = set()
            for checkpoint in saver.list(None):
                configuration = getattr(checkpoint, "config", {})
                thread = ""
                if isinstance(configuration, Mapping):
                    configurable = configuration.get("configurable", {})
                    if isinstance(configurable, Mapping):
                        candidate_thread = configurable.get("thread_id")
                        if type(candidate_thread) is str:
                            thread = candidate_thread
                if not thread or thread in seen_threads:
                    continue
                seen_threads.add(thread)
                values = _checkpoint_values(checkpoint)
                if values is None:
                    continue
                try:
                    identity = validate_checkpoint_run_identity(
                        values.get("checkpoint_run_identity")
                    )
                except CheckpointRunIdentityError:
                    # Corrupt records remain available for inspection and are never pruned here.
                    continue
                trade_date = values.get("trade_date")
                recorded_at = _recorded_at(values, checkpoint)
                if type(trade_date) is not str or recorded_at is None:
                    continue
                recorded = _parse_report_time(recorded_at)
                if recorded > threshold:
                    continue
                step = getattr(checkpoint, "metadata", {}).get("step")
                category = (
                    "stale_completed"
                    if type(values.get("final_trade_decision")) is str
                    else "stale_orphaned"
                )
                candidates.append(
                    CheckpointRetentionCandidate(
                        ticker=ticker,
                        trade_date=trade_date,
                        identity_digest=identity.identity_sha256,
                        latest_step=step if type(step) is int else None,
                        recorded_at=recorded_at,
                        category=category,
                    )
                )
    return CheckpointRetentionReport(
        max_age_days=max_age_days,
        generated_at=report_time.isoformat().replace("+00:00", "Z"),
        candidates=tuple(candidates),
    )


def clear_all_checkpoints(data_dir: str | Path, *, confirm: bool = False) -> int:
    """Explicit maintenance-only broad deletion beneath the bounded checkpoint root."""
    if confirm is not True:
        raise ValueError("broad checkpoint maintenance requires confirm=True")
    cp_dir = _checkpoint_root(data_dir, create=False)
    if cp_dir is None:
        return 0
    dbs = list(cp_dir.glob("*.db"))
    for db in dbs:
        _verify_private_regular_file(db, cp_dir, allow_missing=False)
        db.unlink()
        for suffix in _SQLITE_SIDECAR_SUFFIXES:
            sidecar = db.with_name(f"{db.name}{suffix}")
            if _verify_private_regular_file(sidecar, cp_dir, allow_missing=True):
                sidecar.unlink()
    return len(dbs)


def clear_checkpoint(
    data_dir: str | Path,
    ticker: str,
    date: str,
    identity_digest: str | None = None,
    *,
    allow_legacy_empty_signature: bool = False,
) -> bool:
    """Remove one identity checkpoint and report whether its rows existed."""
    tid = thread_id(
        ticker,
        date,
        identity_digest,
        allow_legacy_empty_signature=allow_legacy_empty_signature,
    )
    db = _db_path(data_dir, ticker)
    if not db.exists():
        return False
    conn = _open_sqlite_connection(db, db.parent, check_same_thread=True)
    try:
        deleted_rows = 0
        for table in ("writes", "checkpoints"):
            cursor = conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (tid,))
            deleted_rows += cursor.rowcount
        conn.commit()
        return deleted_rows > 0
    except sqlite3.OperationalError as exc:
        raise CheckpointCustodyError("could not clear the exact checkpoint") from exc
    finally:
        conn.close()
        _secure_sqlite_files(db, db.parent)


def _identity_mismatch_field(
    expected: CheckpointRunIdentity,
    stored: CheckpointRunIdentity,
) -> str | None:
    """Return the first behavior field that differs without exposing its value."""

    for field, expected_value in expected.to_dict().items():
        if field == "identity_sha256":
            continue
        if stored.to_dict()[field] != expected_value:
            return field
    return None


def find_incompatible_checkpoint(
    data_dir: str | Path,
    ticker: str,
    date: str,
    identity: CheckpointRunIdentity,
) -> str | None:
    """Find an incompatible saved identity for a ticker/date without altering it.

    Per-identity thread IDs keep equal identities isolated. This bounded scan gives
    callers a fail-closed answer when a prior checkpoint for the same logical run
    exists under a different complete identity.
    """

    if not isinstance(identity, CheckpointRunIdentity):
        raise TypeError("identity must be a CheckpointRunIdentity")
    db = _db_path(data_dir, ticker)
    if not db.exists():
        return None
    canonical_ticker = safe_ticker_component(ticker).upper()
    canonical_date = str(date)
    with get_checkpointer(data_dir, ticker) as saver:
        for checkpoint in saver.list(None):
            values = checkpoint.checkpoint.get("channel_values")
            if not isinstance(values, Mapping):
                continue
            stored_ticker = values.get("company_of_interest")
            if type(stored_ticker) is not str:
                continue
            try:
                normalized_stored_ticker = safe_ticker_component(stored_ticker).upper()
            except ValueError:
                continue
            if (
                normalized_stored_ticker != canonical_ticker
                or values.get("trade_date") != canonical_date
            ):
                continue
            raw_identity = values.get("checkpoint_run_identity")
            try:
                stored_identity = validate_checkpoint_run_identity(raw_identity)
            except CheckpointRunIdentityError:
                return "checkpoint_run_identity"
            mismatch = _identity_mismatch_field(identity, stored_identity)
            if mismatch is not None:
                return mismatch
    return None


def saved_checkpoint_identities(
    data_dir: str | Path, ticker: str, date: str,
) -> tuple[CheckpointRunIdentity, ...]:
    """Discover retained identities without clearing or selecting a fresh namespace.

    Earlier checkpoints also identify a run whose latest saved state is corrupt;
    full latest-state validation still happens before graph execution.
    """
    root = _checkpoint_root(data_dir, create=False)
    if root is None:
        return ()
    canonical_ticker = safe_ticker_component(ticker).upper()
    database = root / f"{canonical_ticker}.db"
    if not _verify_private_regular_file(database, root, allow_missing=True):
        return ()
    identities = {}
    with get_checkpointer(data_dir, ticker) as saver:
        for checkpoint in saver.list(None):
            values = _checkpoint_values(checkpoint)
            if values is None:
                continue
            stored_ticker = values.get("company_of_interest")
            if type(stored_ticker) is not str or stored_ticker.upper() != canonical_ticker or values.get("trade_date") != str(date):
                continue
            try:
                identity = validate_checkpoint_run_identity(values.get("checkpoint_run_identity"))
            except CheckpointRunIdentityError as exc:
                raise ValueError("checkpoint stored identity is invalid") from exc
            saved_thread = checkpoint.config.get("configurable", {}).get("thread_id")
            if saved_thread != thread_id(ticker, str(date), identity.identity_sha256):
                raise ValueError("checkpoint stored identity does not match its thread")
            identities[identity.identity_sha256] = identity
    return tuple(identities.values())
