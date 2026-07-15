"""A4: configurable anti-overfit promotion floor. Only raises the built-in floor."""

from __future__ import annotations

from pathlib import Path

from tradingagents.policy.promotion_sync import MIN_TRACKED_DAYS, _quality_gate_issues
from tradingagents.policy.risk_envelope import load_risk_envelope

_THIN = {"tracked_days": 11, "max_drawdown_pct": "-1.0", "win_rate_pct": "85.0"}


def test_thin_history_passes_builtin_floor_when_unconfigured() -> None:
    assert MIN_TRACKED_DAYS == 5
    assert _quality_gate_issues(_THIN) == []  # 11 >= 5


def test_raised_floor_blocks_thin_history() -> None:
    issues = _quality_gate_issues(_THIN, min_tracked_days=20)
    assert any("20-day floor" in i for i in issues)


def test_configured_floor_only_raises_never_lowers() -> None:
    # Below the built-in floor: still enforces the built-in 5-day floor.
    assert _quality_gate_issues(_THIN, min_tracked_days=3) == []
    thin4 = {**_THIN, "tracked_days": 4}
    issues = _quality_gate_issues(thin4, min_tracked_days=3)
    assert any("5-day floor" in i for i in issues)  # effective floor = max(5, 3)


def test_envelope_parses_min_promotion_tracked_days(tmp_path: Path) -> None:
    env = tmp_path / "risk_envelope.yaml"
    env.write_text("\n".join([
        "account_max_capital_at_risk_usd: 250.00",
        "per_name_cap_usd: 50.00",
        "per_sector_cap_pct: 0.20",
        "aggregate_beta_cap: 1.25",
        "daily_loss_halt_usd: 25.00",
        "max_drawdown_halt_pct: 0.05",
        "tiny_live_tranche_usd: 25.00",
        "tiny_live_max_loss_usd: 5.00",
        "new_sleeve_auto_promote: false",
        "alert_email: ops@example.com",
        "min_promotion_tracked_days: 20",
    ]))
    envelope, issues = load_risk_envelope(env)
    assert issues == []
    assert envelope.min_promotion_tracked_days == 20
