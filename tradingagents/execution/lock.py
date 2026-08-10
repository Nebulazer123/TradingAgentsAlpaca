"""Single-writer lock for submit-capable execution paths."""

from __future__ import annotations

import datetime
import json
import os
from dataclasses import dataclass
from pathlib import Path

UTC = datetime.timezone.utc


@dataclass(frozen=True)
class ExecutionLockResult:
    acquired: bool
    path: Path
    reason: str = ""


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def acquire_execution_lock(
    path: str | Path,
    *,
    owner: str,
    stale_after_seconds: int = 900,
) -> ExecutionLockResult:
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "owner": owner,
        "pid": os.getpid(),
        "created_at": _now_iso(),
    }
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags)
    except FileExistsError:
        try:
            age_seconds = datetime.datetime.now(tz=UTC).timestamp() - lock_path.stat().st_mtime
        except OSError:
            age_seconds = 0
        if age_seconds > stale_after_seconds:
            try:
                lock_path.unlink()
            except OSError as exc:
                return ExecutionLockResult(False, lock_path, f"stale lock could not be removed: {exc}")
            return acquire_execution_lock(
                lock_path,
                owner=owner,
                stale_after_seconds=stale_after_seconds,
            )
        return ExecutionLockResult(False, lock_path, "execution lock already exists")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return ExecutionLockResult(True, lock_path)


def release_execution_lock(path: str | Path, *, owner: str | None = None) -> None:
    lock_path = Path(path)
    if not lock_path.exists():
        return
    if owner:
        try:
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if payload.get("owner") not in {owner, None}:
            return
    lock_path.unlink()
