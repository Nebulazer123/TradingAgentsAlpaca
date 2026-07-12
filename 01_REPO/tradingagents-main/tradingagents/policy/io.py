"""Small filesystem helpers for policy/control-plane state files."""

from __future__ import annotations

import os
import time
from pathlib import Path

_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS: tuple[float, ...] = (
    0.05,
    0.1,
    0.2,
    0.5,
    1.0,
)


def atomic_write_text(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """Write text through a sibling temp file, then atomically replace target."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output.with_name(f".{output.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp_path.write_text(text, encoding=encoding)
        for delay in (*_ATOMIC_REPLACE_RETRY_DELAYS_SECONDS, None):
            try:
                os.replace(tmp_path, output)
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
