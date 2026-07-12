"""Small process lock helpers for repo-local orchestration commands."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunLock:
    path: Path
    acquired: bool
    stale_recovered: bool = False
    owner: dict[str, Any] | None = None


ORPHAN_LOCK_STALE_SECONDS = 60.0


def _owner_path(lock_path: Path) -> Path:
    return lock_path / "owner.json"


def _read_owner(lock_path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(_owner_path(lock_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _lock_age_seconds(lock_path: Path) -> float | None:
    try:
        return max(0.0, time.time() - lock_path.stat().st_mtime)
    except OSError:
        return None


def _remove_stale_lock(lock_path: Path) -> bool:
    try:
        owner = _owner_path(lock_path)
        owner.unlink(missing_ok=True)
        lock_path.chmod(0o700)
        lock_path.rmdir()
        return True
    except OSError:
        return False


def try_acquire_run_lock(
    lock_path: str | Path,
    *,
    owner: dict[str, Any],
    stale_after_seconds: float = 60 * 60 * 3,
    wait_seconds: float = 0.0,
    poll_seconds: float = 0.25,
) -> RunLock:
    """Try to acquire a mkdir-based lock, recovering stale locks when safe."""

    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, wait_seconds)
    stale_recovered = False
    while True:
        try:
            path.mkdir()
            _owner_path(path).write_text(json.dumps(owner, indent=2, sort_keys=True), encoding="utf-8")
            return RunLock(path=path, acquired=True, stale_recovered=stale_recovered, owner=owner)
        except FileExistsError:
            age = _lock_age_seconds(path)
            current_owner = _read_owner(path)
            orphan_stale_after = min(stale_after_seconds, ORPHAN_LOCK_STALE_SECONDS)
            if (
                current_owner is None
                and age is not None
                and age > orphan_stale_after
                and _remove_stale_lock(path)
            ):
                stale_recovered = True
                continue
            if age is not None and age > stale_after_seconds and _remove_stale_lock(path):
                stale_recovered = True
                continue
            if time.monotonic() >= deadline:
                return RunLock(path=path, acquired=False, owner=current_owner)
            time.sleep(max(0.01, poll_seconds))


def release_run_lock(lock: RunLock) -> None:
    """Release a lock acquired by try_acquire_run_lock."""

    if not lock.acquired:
        return
    try:
        _owner_path(lock.path).unlink(missing_ok=True)
        lock.path.chmod(0o700)
        lock.path.rmdir()
    except OSError:
        # Best-effort cleanup; a future stale-lock recovery can clear this.
        pass


def process_owner(**extra: Any) -> dict[str, Any]:
    """Build a compact, redacted lock owner payload."""

    payload: dict[str, Any] = {
        "pid": os.getpid(),
        "created_at_epoch": time.time(),
    }
    payload.update(extra)
    return payload
