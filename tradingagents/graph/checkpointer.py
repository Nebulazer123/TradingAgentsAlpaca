"""LangGraph checkpoint support for resumable analysis runs.

Per-ticker SQLite databases so concurrent tickers don't contend.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from tradingagents.dataflows.utils import safe_ticker_component


def _db_path(data_dir: str | Path, ticker: str) -> Path:
    """Return the SQLite checkpoint DB path for a ticker."""
    # Reject ticker values that would escape the checkpoints directory.
    safe = safe_ticker_component(ticker).upper()
    p = Path(data_dir) / "checkpoints"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{safe}.db"


def _validated_signature(
    signature: str | None,
    *,
    allow_legacy_empty_signature: bool,
) -> str:
    """Return a canonical non-empty signature or an explicitly allowed legacy one."""
    if signature is None or signature == "":
        if allow_legacy_empty_signature:
            return ""
        raise ValueError(
            "checkpoint signature is required; set "
            "allow_legacy_empty_signature=True only for explicit legacy access"
        )
    if not isinstance(signature, str):
        raise TypeError("checkpoint signature must be a non-empty string")
    if signature != signature.strip():
        raise ValueError("checkpoint signature must not contain surrounding whitespace")
    return signature


def thread_id(
    ticker: str,
    date: str,
    signature: str | None = None,
    *,
    allow_legacy_empty_signature: bool = False,
) -> str:
    """Return a deterministic ID for one ticker, date, and decision-graph shape."""
    validated = _validated_signature(
        signature,
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
    conn = sqlite3.connect(str(db), check_same_thread=False)
    try:
        saver = SqliteSaver(conn)
        saver.setup()
        yield saver
    finally:
        conn.close()


def has_checkpoint(
    data_dir: str | Path,
    ticker: str,
    date: str,
    signature: str | None = None,
    *,
    allow_legacy_empty_signature: bool = False,
) -> bool:
    """Check whether a resumable checkpoint exists for one signed graph shape."""
    return (
        checkpoint_step(
            data_dir,
            ticker,
            date,
            signature,
            allow_legacy_empty_signature=allow_legacy_empty_signature,
        )
        is not None
    )


def checkpoint_step(
    data_dir: str | Path,
    ticker: str,
    date: str,
    signature: str | None = None,
    *,
    allow_legacy_empty_signature: bool = False,
) -> int | None:
    """Return the step number of the latest checkpoint, or None if none exists."""
    tid = thread_id(
        ticker,
        date,
        signature,
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


def clear_all_checkpoints(data_dir: str | Path) -> int:
    """Remove all checkpoint DBs. Returns number of files deleted."""
    cp_dir = Path(data_dir) / "checkpoints"
    if not cp_dir.exists():
        return 0
    dbs = list(cp_dir.glob("*.db"))
    for db in dbs:
        db.unlink()
    return len(dbs)


def clear_checkpoint(
    data_dir: str | Path,
    ticker: str,
    date: str,
    signature: str | None = None,
    *,
    allow_legacy_empty_signature: bool = False,
) -> None:
    """Remove a specific signed checkpoint by deleting only that thread's rows."""
    tid = thread_id(
        ticker,
        date,
        signature,
        allow_legacy_empty_signature=allow_legacy_empty_signature,
    )
    db = _db_path(data_dir, ticker)
    if not db.exists():
        return
    conn = sqlite3.connect(str(db))
    try:
        for table in ("writes", "checkpoints"):
            conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (tid,))
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
