"""C5: optional promotion evidence max-age gate. Inert unless configured."""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from pathlib import Path

from tradingagents.brokers.supervisor.types import HourlySupervisorAction
from tradingagents.policy.live_gate import evaluate_go_live_guard

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


def _write_envelope(path: Path, *, promotion_max_age_days: int | None = None) -> None:
    lines = [
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
    ]
    if promotion_max_age_days is not None:
        lines.append(f"promotion_max_age_days: {promotion_max_age_days}")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_control(path: Path) -> None:
    path.write_text(json.dumps({
        "frozen": False, "reason": "t", "dead_man_expires_at": "2026-07-17T12:00:00+00:00",
    }), encoding="utf-8")


def _write_promotion(path: Path, *, promoted_at: str) -> None:
    path.write_text(json.dumps({"generated_at": promoted_at, "sleeves": {"pullback-support": {
        "stage": "tiny_live_eligible", "live_enabled": True, "preregistered": True,
        "ci_green": True, "shadow_confirmed": True, "benchmark_gate_passed": True,
        "cost_gate_passed": True, "recent_alpha_gate_passed": True,
        "capacity_gate_passed": True,
        "validation_report_ref": "r.json", "risk_envelope_ref": "config/risk_envelope.yaml",
        "promoted_at": promoted_at,
    }}}), encoding="utf-8")


def _buy_action() -> HourlySupervisorAction:
    return HourlySupervisorAction(
        action="buy", symbol="MSFT", notional=Decimal("20.00"), limit_price=Decimal("410.00"),
        side="buy", order_type="limit", account="live", execution_mode="tiny_live",
        sleeve="pullback-support",
    )


def _guard(tmp_path: Path, *, promoted_at: str, max_age: int | None):
    env = tmp_path / "risk_envelope.yaml"
    promo = tmp_path / "promotion_state.json"
    control = tmp_path / "live_control.json"
    _write_envelope(env, promotion_max_age_days=max_age)
    _write_promotion(promo, promoted_at=promoted_at)
    _write_control(control)
    return evaluate_go_live_guard(
        [_buy_action()],
        risk_envelope_path=env, promotion_state_path=promo, control_state_path=control,
        live_buying_power=Decimal("1000"), now=NOW,
    )


def test_fresh_promotion_passes_with_gate(tmp_path: Path) -> None:
    result = _guard(tmp_path, promoted_at="2026-07-10T12:00:00+00:00", max_age=30)
    assert result.allowed, [i.reason for i in result.issues]


def test_stale_promotion_blocks_when_gate_set(tmp_path: Path) -> None:
    result = _guard(tmp_path, promoted_at="2026-05-01T12:00:00+00:00", max_age=30)
    assert not result.allowed
    assert any("stale" in i.reason for i in result.issues)


def test_stale_promotion_passes_when_gate_unset(tmp_path: Path) -> None:
    # No promotion_max_age_days -> byte-for-byte previous behavior (inert).
    result = _guard(tmp_path, promoted_at="2025-01-01T12:00:00+00:00", max_age=None)
    assert result.allowed, [i.reason for i in result.issues]
