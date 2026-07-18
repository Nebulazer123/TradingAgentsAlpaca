import datetime
import json
from decimal import Decimal

import pytest

from tradingagents.brokers.alpaca_supervisor import (
    HourlySupervisorAction,
    validate_supervisor_live_submit_allowed,
)
from tradingagents.policy.live_gate import evaluate_go_live_guard
from tradingagents.policy.order_rate_limit import record_live_order_submission
from tradingagents.policy.risk_envelope import load_risk_envelope


def _write_envelope(
    path,
    *,
    live_budget_mode=None,
    account_hard_ceiling_usd=None,
    max_live_orders_per_window=None,
    live_order_window_minutes=None,
):
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
    if live_budget_mode:
        lines.append(f"live_budget_mode: {live_budget_mode}")
    if account_hard_ceiling_usd is not None:
        lines.append(f"account_hard_ceiling_usd: {account_hard_ceiling_usd}")
    if max_live_orders_per_window is not None:
        lines.append(f"max_live_orders_per_window: {max_live_orders_per_window}")
    if live_order_window_minutes is not None:
        lines.append(f"live_order_window_minutes: {live_order_window_minutes}")
    path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _write_live_control(path, *, frozen=False, expires_at="2026-06-01T16:00:00+00:00"):
    path.write_text(
        json.dumps(
            {
                "frozen": frozen,
                "reason": "test control state",
                "dead_man_expires_at": expires_at,
            }
        ),
        encoding="utf-8",
    )


def _promotion_record(**overrides):
    record = {
        "stage": "tiny_live_eligible",
        "live_enabled": True,
        "preregistered": True,
        "ci_green": True,
        "shadow_confirmed": True,
        "benchmark_gate_passed": True,
        "cost_gate_passed": True,
        "recent_alpha_gate_passed": True,
        "capacity_gate_passed": True,
        "validation_report_ref": "results/validation/pullback-support.json",
        "risk_envelope_ref": "config/risk_envelope.yaml",
    }
    record.update(overrides)
    return record


def _tiny_live_action(**overrides):
    values = {
        "action": "buy",
        "symbol": "MSFT",
        "notional": Decimal("20.00"),
        "limit_price": Decimal("410.00"),
        "side": "buy",
        "order_type": "limit",
        "reason": "promoted tiny-live sleeve",
        "account": "live",
        "execution_mode": "tiny_live",
        "sleeve": "pullback-support",
    }
    values.update(overrides)
    return HourlySupervisorAction(**values)


def _approved_loss_review(**overrides):
    review = {
        "symbol": "ORCL",
        "side": "sell",
        "decision_id": "decision-current",
        "client_order_id": "ta-tiny-current-orcl-sell",
        "current_price": "233.37",
        "proposed_limit_price": "233.37",
        "average_entry_price": "243.85",
        "estimated_realized_loss": "-4.34",
        "unrealized_pnl_percent": "-0.0434",
        "holding_period_trading_days": 5,
        "opened_at": "2026-05-28T14:30:00+00:00",
        "recent_same_symbol_fills": [
            {
                "side": "buy",
                "filled_at": "2026-05-28T14:30:00+00:00",
                "filled_avg_price": "243.85",
            }
        ],
        "original_entry_thesis": "Support should hold unless the cloud guidance thesis breaks.",
        "current_thesis_status": "Thesis invalidated by company-specific guidance break.",
        "allowed_exit_reason": "thesis_invalidated",
        "allowed_exit_reason_source": "earnings_guidance_packet",
        "broad_market_context": {"spy": "flat", "qqq": "+0.2%"},
        "relative_performance_vs_SPY": "-3.1%",
        "relative_performance_vs_QQQ": "-3.3%",
        "sector_or_peer_context": "software peers flat to slightly positive",
        "company_specific_negative_news_check": "Company-specific guidance cut confirmed.",
        "earnings_guidance_or_filing_check": "Guidance cut broke the support thesis.",
        "why_hold_is_worse_than_sell": "The original catalyst broke and recovery odds are worse than cash.",
        "why_this_is_not_broad_market_red_day_noise": "SPY/QQQ are not driving the loss; company guidance is.",
        "confidence": "0.82",
        "evidence_generated_at": "2026-06-03T15:00:00+00:00",
        "source_packet_ids": ["earnings-guidance-packet"],
        "allowed": True,
        "blocked_reasons": [],
    }
    review.update(overrides)
    return review


def _loss_position(**overrides):
    position = {
        "symbol": "ORCL",
        "qty": "0.4101",
        "avg_entry_price": "243.85",
        "current_price": "233.37",
        "market_value": "95.66",
        "cost_basis": "100.00",
        "unrealized_pl": "-4.34",
        "unrealized_plpc": "-0.0434",
    }
    position.update(overrides)
    return position


def test_risk_envelope_requires_all_operational_limits(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    envelope_path.write_text("tiny_live_tranche_usd: 25\n", encoding="utf-8")

    envelope, issues = load_risk_envelope(envelope_path)

    assert envelope is None
    assert any("account_max_capital_at_risk_usd" in issue for issue in issues)


def test_live_gate_blocks_missing_risk_envelope(tmp_path):
    result = evaluate_go_live_guard(
        actions=[_tiny_live_action()],
        risk_envelope_path=tmp_path / "missing.yaml",
        promotion_state_path=tmp_path / "promotion.json",
    )

    assert result.allowed is False
    assert any("risk envelope" in issue.reason.lower() for issue in result.issues)


def test_live_gate_blocks_unpromoted_sleeve_even_with_envelope(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    _write_envelope(envelope_path)

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action()],
        risk_envelope_path=envelope_path,
        promotion_state_path=tmp_path / "missing-promotion.json",
    )

    assert result.allowed is False
    assert any("promotion" in issue.reason.lower() for issue in result.issues)


def test_live_gate_allows_only_promoted_tiny_live_sleeve(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path)
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps(
            {
                "sleeves": {
                    "pullback-support": _promotion_record()
                }
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action()],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        live_buying_power=Decimal("100.00"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True
    assert result.issues == []


def test_live_gate_autonomous_budget_allows_size_above_fixed_tranche(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("45.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        live_buying_power=Decimal("100.00"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True
    assert result.checks["autonomous_live_budget"] is True


def test_live_gate_fixed_tranche_still_blocks_larger_size(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path)
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("45.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert any("tiny_live_tranche_usd" in issue.reason for issue in result.issues)


def test_live_gate_autonomous_budget_still_blocks_over_per_name_cap(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("55.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert any("per_name_cap_usd" in issue.reason for issue in result.issues)


def test_live_gate_autonomous_budget_counts_existing_live_exposure_for_new_buys(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_with_caps")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("40.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        current_live_exposure=Decimal("225.00"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert result.checks["current_live_exposure_considered"] is True
    assert any("projected live exposure" in issue.reason for issue in result.issues)


def test_live_gate_uncapped_budget_removes_repo_dollar_caps(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("275.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        live_buying_power=Decimal("500.00"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True
    assert result.checks["autonomous_live_budget"] is True
    assert result.checks["autonomous_live_budget_uncapped"] is True


def test_live_gate_blocks_live_buy_when_broker_buying_power_missing_even_uncapped(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("275.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert result.checks["broker_buying_power"] is False
    assert any("broker buying_power" in issue.reason for issue in result.issues)


def test_live_gate_blocks_live_buy_above_broker_buying_power(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("275.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        live_buying_power=Decimal("150.00"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert result.checks["broker_buying_power"] is False
    assert any("exceeds broker buying_power" in issue.reason for issue in result.issues)


def test_supervisor_submit_guard_uses_live_account_buying_power(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    issues = validate_supervisor_live_submit_allowed(
        actions=[_tiny_live_action(notional=Decimal("275.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        live_account={"buying_power": "150.00"},
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert any("exceeds broker buying_power" in issue.reason for issue in issues)


def test_live_gate_circuit_breaker_blocks_new_buys_even_when_uncapped(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("275.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        current_daily_loss_usd=Decimal("25.00"),
        current_drawdown_pct=Decimal("0.0500"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert result.checks["autonomous_live_budget_uncapped"] is True
    assert result.checks["portfolio_circuit_breakers"] is False
    assert result.checks["daily_loss_considered"] is True
    assert result.checks["drawdown_considered"] is True
    reasons = "\n".join(issue.reason for issue in result.issues)
    assert "daily_loss_halt_usd" in reasons
    assert "max_drawdown_halt_pct" in reasons


def test_live_gate_circuit_breaker_allows_profit_taking_sells(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("105.00"),
                limit_price=Decimal("255.00"),
                decision_id="profit-decision",
            )
        ],
        live_positions=[_loss_position(current_price="255.00")],
        decision_evidence={},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        current_daily_loss_usd=Decimal("25.00"),
        current_drawdown_pct=Decimal("0.0500"),
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True
    assert result.checks["portfolio_circuit_breakers"] is True
    assert result.checks["daily_loss_considered"] is True
    assert result.checks["drawdown_considered"] is True


def test_live_gate_does_not_count_close_sell_as_new_budget(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path)
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                notional=Decimal("300.00"),
            )
        ],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        current_live_exposure=Decimal("250.00"),
        live_positions=[
            {
                "symbol": "MSFT",
                "avg_entry_price": "390.00",
                "current_price": "410.00",
            }
        ],
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True


def test_live_gate_blocks_sell_when_avg_entry_is_nonpositive_without_review(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("95.66"),
                limit_price=Decimal("233.37"),
                decision_id="decision-current",
            )
        ],
        live_positions=[
            {
                "symbol": "ORCL",
                "avg_entry_price": "0",
                "current_price": "233.37",
            }
        ],
        decision_evidence={},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    reasons = "\n".join(issue.reason for issue in result.issues)
    assert "final_submit_loss_gate_blocked" in reasons
    assert "loss_exit_review is missing" in reasons


def test_live_gate_blocks_loss_sell_without_structured_loss_exit_review(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("95.66"),
                limit_price=Decimal("233.37"),
                decision_id="decision-current",
            )
        ],
        live_positions=[_loss_position()],
        decision_evidence={},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    reasons = "\n".join(issue.reason for issue in result.issues)
    assert "final_submit_loss_gate_blocked" in reasons
    assert "loss_exit_review is missing" in reasons


def test_live_gate_blocks_sell_when_position_snapshot_missing(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(
        control_path,
        expires_at="2026-06-03T16:00:00+00:00",
    )
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("95.66"),
                limit_price=Decimal("233.37"),
                decision_id="decision-current",
            )
        ],
        live_positions=[],
        decision_evidence={"loss_exit_review": _approved_loss_review()},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert any(
        "current live position snapshot is missing" in issue.reason
        for issue in result.issues
    )


def test_live_gate_blocks_stale_loss_exit_review_decision_id(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("95.66"),
                limit_price=Decimal("233.37"),
                decision_id="decision-current",
            )
        ],
        live_positions=[_loss_position()],
        decision_evidence={
            "loss_exit_review": _approved_loss_review(decision_id="old-decision")
        },
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert any("decision_id does not match current action" in issue.reason for issue in result.issues)


def test_live_gate_blocks_loss_exit_review_allowed_false(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("95.66"),
                limit_price=Decimal("233.37"),
                decision_id="decision-current",
            )
        ],
        live_positions=[_loss_position()],
        decision_evidence={
            "loss_exit_review": _approved_loss_review(
                allowed=False,
                blocked_reasons=["broad market weakness alone is insufficient"],
            )
        },
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert any("loss_exit_review.allowed is not true" in issue.reason for issue in result.issues)


def test_live_gate_allows_strict_current_approved_loss_exit_review(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("95.66"),
                limit_price=Decimal("233.37"),
                decision_id="decision-current",
            )
        ],
        live_positions=[_loss_position()],
        decision_evidence={"loss_exit_review": _approved_loss_review()},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True


def test_live_gate_allows_current_pre_registered_policy_stop_review(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )
    review = {
        "symbol": "NFLX",
        "side": "sell",
        "decision_id": "decision-current",
        "current_price": "69.28",
        "proposed_limit_price": "69.07",
        "average_entry_price": "83.37",
        "estimated_realized_loss": "-4.52",
        "unrealized_pnl_percent": "-16.90",
        "allowed_exit_reason": "policy_stop_floor",
        "allowed_exit_reason_source": (
            "pre-registered exit policy rule 'catastrophic_stop'"
        ),
        "policy_rule_exit": True,
        "exit_policy_rule": "catastrophic_stop",
        "exit_policy_rationale": (
            "Position is beyond the pre-registered catastrophic floor."
        ),
        "evidence_generated_at": "2026-06-03T15:00:00+00:00",
        "allowed": True,
        "blocked_reasons": [],
    }

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="NFLX",
                notional=Decimal("22.23"),
                limit_price=Decimal("69.07"),
                decision_id="decision-current",
            )
        ],
        live_positions=[_loss_position(
            symbol="NFLX",
            avg_entry_price="83.37",
            current_price="69.28",
            market_value="22.23",
            cost_basis="26.76",
            unrealized_pl="-4.52",
            unrealized_plpc="-0.1690",
        )],
        decision_evidence={"loss_exit_review": review},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True


def _policy_exit_review(**overrides):
    review = {
        "symbol": "NFLX",
        "side": "sell",
        "decision_id": "decision-current",
        "current_price": "69.28",
        "average_entry_price": "83.37",
        "estimated_realized_loss": "-4.52",
        "unrealized_pnl_percent": "-16.90",
        "allowed_exit_reason": "policy_stop_floor",
        "allowed_exit_reason_source": "pre-registered exit policy rule",
        "policy_rule_exit": True,
        "exit_policy_rule": "catastrophic_stop",
        "exit_policy_rationale": "Position is beyond the pre-registered floor.",
        "evidence_generated_at": "2026-06-03T15:00:00+00:00",
        "allowed": True,
        "blockers": [],
        "blocked_reasons": [],
    }
    review.update(overrides)
    return review


def _policy_exit_gate_result(
    tmp_path,
    review,
    *,
    action_overrides=None,
    now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )
    action_values = {
        "action": "close",
        "side": "sell",
        "symbol": "NFLX",
        "notional": Decimal("22.23"),
        "limit_price": Decimal("69.07"),
        "decision_id": "decision-current",
    }
    action_values.update(action_overrides or {})
    action = _tiny_live_action(**action_values)
    return evaluate_go_live_guard(
        actions=[action],
        live_positions=[_loss_position(
            symbol=action.symbol,
            avg_entry_price="83.37",
            current_price="69.28",
            market_value="22.23",
            cost_basis="26.76",
            unrealized_pl="-4.52",
            unrealized_plpc="-0.1690",
        )],
        decision_evidence={"loss_exit_review": review},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=now,
    )


def test_live_gate_allows_current_pre_registered_policy_time_stop_review(tmp_path):
    result = _policy_exit_gate_result(
        tmp_path,
        _policy_exit_review(
            allowed_exit_reason="policy_time_stop",
            exit_policy_rule="time_stop",
        ),
    )

    assert result.allowed is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("allowed", "true"),
        ("allowed", "false"),
        ("policy_rule_exit", "true"),
        ("policy_rule_exit", "false"),
    ],
)
def test_live_gate_rejects_string_policy_booleans(tmp_path, field, value):
    result = _policy_exit_gate_result(tmp_path, _policy_exit_review(**{field: value}))

    assert result.allowed is False
    assert any("final_submit_loss_gate_blocked" in issue.reason for issue in result.issues)


@pytest.mark.parametrize(
    "field",
    [
        "symbol",
        "decision_id",
        "allowed_exit_reason_source",
        "exit_policy_rule",
        "exit_policy_rationale",
    ],
)
def test_live_gate_rejects_policy_review_missing_required_field(tmp_path, field):
    review = _policy_exit_review()
    review.pop(field)

    result = _policy_exit_gate_result(tmp_path, review)

    assert result.allowed is False
    assert any("final_submit_loss_gate_blocked" in issue.reason for issue in result.issues)


@pytest.mark.parametrize(
    "field,value",
    [
        ("blockers", ["blocked"]),
        ("blocked_reasons", ["blocked"]),
        ("blockers", "blocked"),
        ("blocked_reasons", "blocked"),
    ],
)
def test_live_gate_rejects_policy_review_with_blockers(tmp_path, field, value):
    result = _policy_exit_gate_result(tmp_path, _policy_exit_review(**{field: value}))

    assert result.allowed is False
    assert any("final_submit_loss_gate_blocked" in issue.reason for issue in result.issues)


def test_live_gate_fails_closed_without_raising_for_malformed_policy_review(tmp_path):
    result = _policy_exit_gate_result(
        tmp_path,
        {"policy_rule_exit": True},
    )

    assert result.allowed is False
    assert any("final_submit_loss_gate_blocked" in issue.reason for issue in result.issues)


@pytest.mark.parametrize(
    "review,action_overrides",
    [
        (_policy_exit_review(allowed_exit_reason="unknown_policy_reason"), {}),
        (_policy_exit_review(exit_policy_rule="unknown_policy_rule"), {}),
        (_policy_exit_review(symbol="TSM"), {}),
        (_policy_exit_review(decision_id="other-decision"), {}),
        (_policy_exit_review(side="buy"), {}),
        (_policy_exit_review(), {"symbol": "TSM"}),
        (_policy_exit_review(), {"decision_id": "other-decision"}),
    ],
)
def test_live_gate_rejects_policy_review_with_conflicting_authority_or_identity(
    tmp_path, review, action_overrides
):
    result = _policy_exit_gate_result(
        tmp_path,
        review,
        action_overrides=action_overrides,
    )

    assert result.allowed is False
    assert any("final_submit_loss_gate_blocked" in issue.reason for issue in result.issues)


@pytest.mark.parametrize(
    "timestamp",
    ["2026-06-03T08:59:59+00:00", "2026-06-03T15:00:01+00:00"],
)
def test_live_gate_rejects_stale_or_future_policy_review(tmp_path, timestamp):
    result = _policy_exit_gate_result(
        tmp_path,
        _policy_exit_review(evidence_generated_at=timestamp),
    )

    assert result.allowed is False
    assert any("stale for current submit" in issue.reason for issue in result.issues)


def test_live_gate_does_not_require_loss_review_for_profit_taking_sell(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[
            _tiny_live_action(
                action="close",
                side="sell",
                symbol="ORCL",
                notional=Decimal("105.00"),
                limit_price=Decimal("255.00"),
                decision_id="profit-decision",
            )
        ],
        live_positions=[_loss_position(current_price="255.00")],
        decision_evidence={},
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True


def test_live_gate_blocks_frozen_control_state(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path)
    _write_live_control(control_path, frozen=True)
    promotion_path.write_text(
        json.dumps(
            {
                "sleeves": {
                    "pullback-support": _promotion_record()
                }
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action()],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert any("frozen" in issue.reason.lower() for issue in result.issues)


def test_supervisor_guard_rejects_legacy_live_now_even_when_files_exist(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    _write_envelope(envelope_path)
    promotion_path.write_text(
        json.dumps(
            {
                "sleeves": {
                    "legacy-supervisor": _promotion_record()
                }
            }
        ),
        encoding="utf-8",
    )

    issues = validate_supervisor_live_submit_allowed(
        actions=[
            _tiny_live_action(
                execution_mode="live_now",
                sleeve="legacy-supervisor",
            )
        ],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
    )

    assert any("tiny_live" in issue.reason for issue in issues)


def test_live_gate_rejects_incomplete_promotion_record(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(envelope_path)
    _write_live_control(control_path)
    promotion_path.write_text(
        json.dumps(
            {
                "sleeves": {
                    "pullback-support": {
                        "stage": "tiny_live_eligible",
                        "live_enabled": True,
                        "ci_green": True,
                        "shadow_confirmed": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action()],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    reasons = "\n".join(issue.reason for issue in result.issues)
    assert "preregistered" in reasons
    assert "benchmark_gate_passed" in reasons
    assert "validation_report_ref" in reasons


def test_live_gate_account_hard_ceiling_blocks_even_uncapped(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(
        envelope_path,
        live_budget_mode="autonomous_uncapped",
        account_hard_ceiling_usd="50.00",
    )
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("20.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        current_live_exposure=Decimal("40.00"),
        live_buying_power=Decimal("500.00"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is False
    assert result.checks["account_hard_ceiling"] is False
    assert any("account_hard_ceiling_usd" in issue.reason for issue in result.issues)


def test_live_gate_account_hard_ceiling_allows_when_projected_under(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    _write_envelope(
        envelope_path,
        live_budget_mode="autonomous_uncapped",
        account_hard_ceiling_usd="100.00",
    )
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("20.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        current_live_exposure=Decimal("40.00"),
        live_buying_power=Decimal("500.00"),
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=datetime.timezone.utc),
    )

    assert result.allowed is True
    assert result.checks["account_hard_ceiling"] is True


def test_live_gate_order_rate_limit_blocks_when_window_exceeded(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    rate_path = tmp_path / "rate.json"
    _write_envelope(
        envelope_path,
        live_budget_mode="autonomous_uncapped",
        max_live_orders_per_window=2,
        live_order_window_minutes=60,
    )
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )
    now = datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc)
    record_live_order_submission(rate_path, client_order_id="ta-1", now=now)
    record_live_order_submission(rate_path, client_order_id="ta-2", now=now)

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("20.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        order_rate_state_path=rate_path,
        live_buying_power=Decimal("500.00"),
        now=now,
    )

    assert result.allowed is False
    assert result.checks["order_rate_limit"] is False
    assert any("max_live_orders_per_window" in issue.reason for issue in result.issues)


def test_live_gate_order_rate_limit_inert_when_unconfigured(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    promotion_path = tmp_path / "promotion.json"
    control_path = tmp_path / "live_control.json"
    rate_path = tmp_path / "rate.json"
    _write_envelope(envelope_path, live_budget_mode="autonomous_uncapped")
    _write_live_control(control_path, expires_at="2026-06-03T16:00:00+00:00")
    promotion_path.write_text(
        json.dumps({"sleeves": {"pullback-support": _promotion_record()}}),
        encoding="utf-8",
    )
    now = datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc)
    for index in range(5):
        record_live_order_submission(rate_path, client_order_id=f"ta-{index}", now=now)

    result = evaluate_go_live_guard(
        actions=[_tiny_live_action(notional=Decimal("20.00"))],
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        order_rate_state_path=rate_path,
        live_buying_power=Decimal("500.00"),
        now=now,
    )

    assert result.allowed is True
    assert result.checks["order_rate_limit"] is True
