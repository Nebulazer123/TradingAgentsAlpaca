"""C1/C8: tamper-evident integrity sidecars + hash-chained audit for safety state.

Contract:
- Writing state also writes a sha256+seq sidecar and appends a hash-chained audit line.
- verify_state_integrity is READ-ONLY and mode-driven:
    off     -> never reports issues
    warn    -> never reports issues (log only) => zero production behavior change
    enforce -> reports issues on mismatch / missing sidecar (fail-closed)
- A retroactive edit to state (without re-writing the sidecar) is detected in enforce.
- Editing an audit line breaks verify_audit_chain.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from tradingagents.policy import integrity

UTC = datetime.timezone.utc


def _fixed(seq: int) -> datetime.datetime:
    return datetime.datetime(2026, 7, 15, 12, seq, 0, tzinfo=UTC)


def test_resolve_mode_defaults_to_warn(monkeypatch) -> None:
    monkeypatch.delenv(integrity.INTEGRITY_ENV, raising=False)
    assert integrity.resolve_mode() == "warn"
    monkeypatch.setenv(integrity.INTEGRITY_ENV, "ENFORCE")
    assert integrity.resolve_mode() == "enforce"
    monkeypatch.setenv(integrity.INTEGRITY_ENV, "nonsense")
    assert integrity.resolve_mode() == "warn"  # invalid falls back to safe default


def test_write_creates_sidecar_and_audit(tmp_path: Path) -> None:
    state = tmp_path / "live_control.json"
    integrity.write_state_with_integrity(state, '{"frozen": false}', actor="test", now=_fixed(1))
    assert json.loads(state.read_text()) == {"frozen": False}
    side = json.loads(integrity.sidecar_path(state).read_text())
    assert side["seq"] == 1
    assert side["sha256"] == integrity.hash_text('{"frozen": false}')
    audit_lines = integrity.audit_path(state).read_text().strip().splitlines()
    assert len(audit_lines) == 1
    assert json.loads(audit_lines[0])["prev_hash"] == "GENESIS"


def test_seq_increments_and_audit_chains(tmp_path: Path) -> None:
    state = tmp_path / "promotion_state.json"
    integrity.write_state_with_integrity(state, "v1", actor="a", now=_fixed(1))
    integrity.write_state_with_integrity(state, "v2", actor="a", now=_fixed(2))
    integrity.write_state_with_integrity(state, "v3", actor="a", now=_fixed(3))
    assert json.loads(integrity.sidecar_path(state).read_text())["seq"] == 3
    assert integrity.verify_audit_chain(integrity.audit_path(state)) == []


def test_verify_clean_state_passes_all_modes(tmp_path: Path) -> None:
    state = tmp_path / "live_control.json"
    integrity.write_state_with_integrity(state, "clean", actor="t", now=_fixed(1))
    text = state.read_text()
    for mode in ("off", "warn", "enforce"):
        assert integrity.verify_state_integrity(state, text, mode=mode) == []


def test_tampered_state_blocks_only_in_enforce(tmp_path: Path) -> None:
    state = tmp_path / "live_control.json"
    integrity.write_state_with_integrity(state, "original", actor="t", now=_fixed(1))
    tampered = "tampered-by-hand"  # sidecar still holds the hash of "original"
    assert integrity.verify_state_integrity(state, tampered, mode="off") == []
    assert integrity.verify_state_integrity(state, tampered, mode="warn") == []
    enforced = integrity.verify_state_integrity(state, tampered, mode="enforce")
    assert enforced and any("integrity" in i for i in enforced)


def test_missing_sidecar_blocks_only_in_enforce(tmp_path: Path) -> None:
    state = tmp_path / "live_control.json"
    state.write_text("no-sidecar-here")  # written outside the integrity path
    assert integrity.verify_state_integrity(state, "no-sidecar-here", mode="warn") == []
    enforced = integrity.verify_state_integrity(state, "no-sidecar-here", mode="enforce")
    assert enforced and any("sidecar" in i for i in enforced)


def test_broken_audit_chain_detected(tmp_path: Path) -> None:
    state = tmp_path / "promotion_state.json"
    integrity.write_state_with_integrity(state, "v1", actor="a", now=_fixed(1))
    integrity.write_state_with_integrity(state, "v2", actor="a", now=_fixed(2))
    audit = integrity.audit_path(state)
    lines = audit.read_text().strip().splitlines()
    entry = json.loads(lines[0])
    entry["sha256"] = "0" * 64  # retroactively edit the first record
    lines[0] = json.dumps(entry)
    audit.write_text("\n".join(lines) + "\n")
    assert integrity.verify_audit_chain(audit) != []
