"""Tamper-evidence for the two money-gating safety-state files.

Every write of ``live_control.json`` / ``promotion_state.json`` (and any other
control-plane state routed through here) also writes a ``*.integrity.json`` sidecar
(sha256 + monotonic seq + timestamp) and appends a hash-chained line to
``state_audit.jsonl`` in the same directory. Loaders can then verify state on read.

Verification is READ-ONLY and driven by ``TA_STATE_INTEGRITY``:

* ``off``     — never verify.
* ``warn``    — verify and log, but never block (the default; **zero** change to the
                go-live guard's behavior — burn-in mode).
* ``enforce`` — a mismatch or missing sidecar becomes a fail-closed issue that the
                go-live guard treats like any other blocking reason.

This only ever ADDS a gate; it never removes one. It cannot make a blocked order
pass. See ``docs/superpowers/specs/2026-07-15-resilience-opsec-edge-design.md``.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
from pathlib import Path

from tradingagents.policy.io import atomic_append_line, atomic_write_text

UTC = datetime.timezone.utc
_LOG = logging.getLogger("tradingagents.policy.integrity")

INTEGRITY_ENV = "TA_STATE_INTEGRITY"
_VALID_MODES = ("off", "warn", "enforce")
_DEFAULT_MODE = "warn"
_GENESIS = "GENESIS"


def resolve_mode(mode: str | None = None) -> str:
    """Return the effective integrity mode, defaulting safely to ``warn``."""

    raw = (mode if mode is not None else os.environ.get(INTEGRITY_ENV, _DEFAULT_MODE))
    normalized = str(raw or "").strip().lower()
    return normalized if normalized in _VALID_MODES else _DEFAULT_MODE


def hash_text(text: str, *, encoding: str = "utf-8") -> str:
    """sha256 hex digest of the exact bytes written to the state file."""

    return hashlib.sha256(text.encode(encoding)).hexdigest()


def sidecar_path(path: str | Path) -> Path:
    output = Path(path)
    return output.with_name(f"{output.name}.integrity.json")


def audit_path(path: str | Path) -> Path:
    return Path(path).parent / "state_audit.jsonl"


def read_integrity_sidecar(path: str | Path) -> dict | None:
    side = sidecar_path(path)
    if not side.exists():
        return None
    try:
        parsed = json.loads(side.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _now_iso(now: datetime.datetime | None) -> str:
    current = now or datetime.datetime.now(tz=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat(timespec="seconds")


def _entry_hash(fields: dict) -> str:
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _last_audit_hash(audit: Path) -> str:
    if not audit.exists():
        return _GENESIS
    try:
        lines = [ln for ln in audit.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return _GENESIS
    if not lines:
        return _GENESIS
    try:
        return str(json.loads(lines[-1]).get("entry_hash") or _GENESIS)
    except json.JSONDecodeError:
        return _GENESIS


def write_state_with_integrity(
    path: str | Path,
    text: str,
    *,
    actor: str,
    now: datetime.datetime | None = None,
) -> Path:
    """Write ``text`` to ``path`` atomically, then its sidecar and an audit line.

    The state file is written first (via the fsync-durable atomic writer). The
    sidecar and audit reflect exactly the bytes committed.
    """

    output = Path(path)
    atomic_write_text(output, text)

    sha = hash_text(text)
    prior = read_integrity_sidecar(output)
    seq = int(prior.get("seq", 0)) + 1 if isinstance(prior, dict) else 1
    written_at = _now_iso(now)

    atomic_write_text(
        sidecar_path(output),
        json.dumps(
            {"algo": "sha256", "sha256": sha, "seq": seq, "written_at": written_at},
            indent=2,
        ),
    )

    prev_hash = _last_audit_hash(audit_path(output))
    fields = {
        "ts": written_at,
        "actor": str(actor),
        "file": output.name,
        "sha256": sha,
        "seq": seq,
        "prev_hash": prev_hash,
    }
    entry = {**fields, "entry_hash": _entry_hash(fields)}
    atomic_append_line(audit_path(output), json.dumps(entry, separators=(",", ":")))
    return output


def verify_state_integrity(
    path: str | Path,
    text: str,
    *,
    mode: str | None = None,
) -> list[str]:
    """Read-only integrity check of already-loaded ``text`` against its sidecar.

    Returns blocking issues ONLY in ``enforce`` mode. In ``warn`` it logs and returns
    ``[]`` (no behavior change); in ``off`` it does nothing.
    """

    effective = resolve_mode(mode)
    if effective == "off":
        return []

    output = Path(path)
    sidecar = read_integrity_sidecar(output)
    if sidecar is None:
        message = f"integrity sidecar missing for {output.name}"
        if effective == "enforce":
            return [message]
        _LOG.debug("%s (warn mode, not blocking)", message)
        return []

    expected = str(sidecar.get("sha256") or "")
    actual = hash_text(text)
    if expected != actual:
        message = (
            f"integrity mismatch for {output.name}: "
            f"expected {expected[:12]}…, got {actual[:12]}… "
            "(state changed without going through the integrity writer)"
        )
        if effective == "enforce":
            return [message]
        _LOG.warning("%s (warn mode, not blocking)", message)
        return []

    return []


def verify_audit_chain(path: str | Path) -> list[str]:
    """Validate the hash chain of an audit log. Returns issues if the chain is broken."""

    audit = Path(path)
    if not audit.exists():
        return []
    try:
        raw_lines = [ln for ln in audit.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError as exc:
        return [f"audit log unreadable: {exc}"]

    issues: list[str] = []
    prev_hash = _GENESIS
    for index, line in enumerate(raw_lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            issues.append(f"audit line {index} is not valid JSON")
            return issues
        stored_hash = str(entry.get("entry_hash") or "")
        fields = {k: entry[k] for k in ("ts", "actor", "file", "sha256", "seq", "prev_hash") if k in entry}
        if _entry_hash(fields) != stored_hash:
            issues.append(f"audit line {index} entry_hash does not match its contents (edited?)")
        if str(entry.get("prev_hash")) != prev_hash:
            issues.append(f"audit line {index} prev_hash breaks the chain")
        prev_hash = stored_hash
    return issues
