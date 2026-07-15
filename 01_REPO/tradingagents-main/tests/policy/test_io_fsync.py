"""C2 durability: atomic_write_text must fsync data and the parent directory.

A crash/power-loss between write and rename is the failure mode we close: without
fsync, os.replace can leave a zero-length safety-state file. We cannot simulate
power loss in a unit test, so we assert the durability *path runs* (fd + dir fsync)
and that content roundtrips unchanged.
"""

from __future__ import annotations

from pathlib import Path

from tradingagents.policy import io as policy_io


def test_atomic_write_text_roundtrips(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "state.json"
    policy_io.atomic_write_text(target, '{"a": 1}\n')
    assert target.read_text(encoding="utf-8") == '{"a": 1}\n'
    # no leftover temp files
    assert list(target.parent.glob(".*tmp")) == []


def test_atomic_write_text_fsyncs_fd_and_dir(tmp_path: Path, monkeypatch) -> None:
    fd_syncs: list[int] = []
    dir_syncs: list[str] = []

    real_fsync_fd = policy_io._fsync_fd
    real_fsync_dir = policy_io._fsync_dir

    def spy_fd(fd: int) -> None:
        fd_syncs.append(fd)
        real_fsync_fd(fd)

    def spy_dir(path) -> None:
        dir_syncs.append(str(path))
        real_fsync_dir(path)

    monkeypatch.setattr(policy_io, "_fsync_fd", spy_fd)
    monkeypatch.setattr(policy_io, "_fsync_dir", spy_dir)

    target = tmp_path / "state.json"
    policy_io.atomic_write_text(target, "durable")

    assert target.read_text(encoding="utf-8") == "durable"
    assert len(fd_syncs) >= 1, "temp file data was never fsynced before rename"
    assert str(tmp_path) in dir_syncs, "parent directory was never fsynced after rename"


def test_fsync_helpers_are_best_effort_and_never_raise(tmp_path: Path) -> None:
    # Directory fsync on a missing path must be a silent no-op, not an error.
    policy_io._fsync_dir(tmp_path / "does-not-exist")
