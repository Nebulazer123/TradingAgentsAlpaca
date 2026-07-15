"""Small filesystem helpers for policy/control-plane state files."""

from __future__ import annotations

import os
import time
from pathlib import Path

try:  # POSIX only; absent on Windows.
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]

_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS: tuple[float, ...] = (
    0.05,
    0.1,
    0.2,
    0.5,
    1.0,
)


def _fsync_fd(fd: int) -> None:
    """Force a file descriptor's data to physical storage; best-effort.

    On macOS ``os.fsync`` only pushes to the drive cache, so a real power loss can
    still lose the write. ``F_FULLFSYNC`` asks the drive to flush its cache and is
    what makes an atomic-replace durable. Fall back to ``os.fsync`` elsewhere.
    """

    if fcntl is not None and hasattr(fcntl, "F_FULLFSYNC"):
        try:
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
            return
        except OSError:
            pass
    try:
        os.fsync(fd)
    except OSError:  # pragma: no cover - platform/filesystem dependent
        pass


def _fsync_dir(path: str | Path) -> None:
    """Fsync a directory so a rename into it survives a crash; silent no-op if unsupported."""

    try:
        dir_fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        _fsync_fd(dir_fd)
    finally:
        os.close(dir_fd)


def atomic_write_text(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """Write text through a sibling temp file, then atomically replace target.

    The temp file's data is fsynced before the rename and the parent directory is
    fsynced after, so a crash/power-loss cannot leave a truncated or zero-length
    control-plane file (which would fail closed and strand protective orders).
    """

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output.with_name(f".{output.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        data = text.encode(encoding)
        # Mode 0o666 & umask matches Path.write_text semantics (no behavior change).
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
        try:
            os.write(fd, data)
            _fsync_fd(fd)
        finally:
            os.close(fd)
        for delay in (*_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS, None):
            try:
                os.replace(tmp_path, output)
                _fsync_dir(output.parent)
                return output
            except PermissionError:
                if delay is None:
                    raise
                time.sleep(delay)
        return output
    finally:
        tmp_path.unlink(missing_ok=True)


def atomic_append_line(
    path: str | Path,
    line: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """Append one line by atomically rewriting the small policy log file."""

    output = Path(path)
    existing = output.read_text(encoding=encoding) if output.exists() else ""
    separator = "" if not existing or existing.endswith("\n") else "\n"
    return atomic_write_text(output, f"{existing}{separator}{line}\n", encoding=encoding)


def unique_packet_path(output_dir: str | Path, stem: str, suffix: str = ".json") -> Path:
    """Return an unused packet path in output_dir without creating the file."""

    output = Path(output_dir)
    candidate = output / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    for index in range(1, 1000):
        candidate = output / f"{stem}-{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate unique packet path for {stem}{suffix}")
