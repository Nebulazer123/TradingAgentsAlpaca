"""C1 wiring: the real loaders surface integrity issues in enforce mode only.

Proves the fail-closed path end-to-end without touching production state files.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from tradingagents.policy import integrity
from tradingagents.policy.live_control import (
    load_live_control_state,
    write_live_control_state,
)
from tradingagents.policy.live_gate import _read_promotion_state

UTC = datetime.timezone.utc


def _future() -> datetime.datetime:
    return datetime.datetime.now(tz=UTC) + datetime.timedelta(hours=6)


def test_live_control_tamper_blocks_only_in_enforce(tmp_path: Path, monkeypatch) -> None:
    control = tmp_path / "live_control.json"
    write_live_control_state(control, frozen=False, reason="armed", dead_man_expires_at=_future())

    # Clean read: no integrity issue in any mode.
    for mode in ("off", "warn", "enforce"):
        monkeypatch.setenv(integrity.INTEGRITY_ENV, mode)
        _state, issues = load_live_control_state(control)
        assert not any("integrity" in i for i in issues), (mode, issues)

    # Tamper: extend the dead-man by hand without going through the writer.
    payload = json.loads(control.read_text())
    payload["dead_man_expires_at"] = "2099-01-01T00:00:00+00:00"
    control.write_text(json.dumps(payload, indent=2))

    monkeypatch.setenv(integrity.INTEGRITY_ENV, "warn")
    _state, warn_issues = load_live_control_state(control)
    assert not any("integrity" in i for i in warn_issues)

    monkeypatch.setenv(integrity.INTEGRITY_ENV, "enforce")
    _state, enforce_issues = load_live_control_state(control)
    assert any("integrity" in i for i in enforce_issues), enforce_issues


def test_promotion_state_tamper_blocks_only_in_enforce(tmp_path: Path, monkeypatch) -> None:
    promo = tmp_path / "promotion_state.json"
    integrity.write_state_with_integrity(
        promo, json.dumps({"sleeves": {}}), actor="test"
    )

    monkeypatch.setenv(integrity.INTEGRITY_ENV, "warn")
    _state, warn_issues = _read_promotion_state(promo)
    assert not any("integrity" in i for i in warn_issues)

    promo.write_text(json.dumps({"sleeves": {"x": {"live_enabled": True}}}))

    monkeypatch.setenv(integrity.INTEGRITY_ENV, "enforce")
    _state, enforce_issues = _read_promotion_state(promo)
    assert any("integrity" in i for i in enforce_issues), enforce_issues
