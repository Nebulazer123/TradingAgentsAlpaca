import datetime
from decimal import Decimal

from tradingagents.brokers.supervisor.hourly import build_loss_review_decision
from tradingagents.brokers.supervisor.loss_review import loss_exit_review_packet
from tradingagents.policy.exit_policy import (
    DEFAULT_EXIT_POLICY,
    ExitPolicy,
    apply_exit_policy_to_position,
    evaluate_exit_policy,
    load_exit_policy,
)

NOW = datetime.datetime(2026, 7, 14, 15, 0, tzinfo=datetime.timezone.utc)


def _position(plpc="-0.09", **extra):
    base = {
        "symbol": "NFLX",
        "qty": "0.5",
        "avg_entry_price": "100.00",
        "current_price": "91.00",
        "market_value": "45.50",
        "unrealized_pl": "-4.50",
        "unrealized_plpc": plpc,
    }
    base.update(extra)
    return base


def test_hard_stop_triggers_at_eight_percent():
    decision = evaluate_exit_policy(_position("-0.09"), generated_at=NOW)
    assert decision.triggered
    assert decision.reason_code == "policy_stop_floor"
    assert decision.rule_id == "hard_stop"
    # limit priced 0.3% below current for a realistic fill
    assert decision.proposed_limit_price == Decimal("90.72")


def test_catastrophic_stop_takes_priority():
    decision = evaluate_exit_policy(
        _position("-0.15", current_price="85.00"), generated_at=NOW
    )
    assert decision.triggered
    assert decision.rule_id == "catastrophic_stop"


def test_small_loss_does_not_trigger():
    decision = evaluate_exit_policy(_position("-0.04"), generated_at=NOW)
    assert decision.triggered is False


def test_time_stop_requires_holding_evidence():
    stale = _position("-0.06", holding_period_trading_days=20)
    decision = evaluate_exit_policy(stale, generated_at=NOW)
    assert decision.triggered
    assert decision.reason_code == "policy_time_stop"

    no_evidence = _position("-0.06")
    assert evaluate_exit_policy(no_evidence, generated_at=NOW).triggered is False


def test_profit_never_triggers():
    assert (
        evaluate_exit_policy(_position("0.05"), generated_at=NOW).triggered is False
    )


def test_apply_does_not_overwrite_narrative_evidence():
    narrative = _position("-0.20", allowed_exit_reason="thesis_invalidated")
    enriched = apply_exit_policy_to_position(narrative, generated_at=NOW)
    assert enriched["allowed_exit_reason"] == "thesis_invalidated"
    assert "exit_policy_rule" not in enriched


def test_policy_exit_review_packet_is_allowed_without_narrative():
    enriched = apply_exit_policy_to_position(_position("-0.09"), generated_at=NOW)
    packet = loss_exit_review_packet(
        enriched,
        generated_at=NOW,
        proposed_limit_price=enriched.get("exit_policy_limit_price"),
    )
    assert packet["allowed"] is True, packet["blockers"]
    assert packet["allowed_exit_reason"] == "policy_stop_floor"
    assert packet["policy_rule_exit"] is True
    assert packet["exit_policy_rule"] == "hard_stop"


def test_narrative_exit_contract_unchanged():
    packet = loss_exit_review_packet(_position("-0.09"), generated_at=NOW)
    assert packet["allowed"] is False
    assert "allowed loss-exit reason is missing" in packet["blockers"]
    assert "original buy thesis is missing" in packet["blockers"]


def test_hourly_decision_emits_close_action_for_stop_floor():
    decision = build_loss_review_decision(
        worst_position=_position("-0.09"),
        loss_review_plpc=Decimal("-0.05"),
        market_session="regular",
        live_exposure=Decimal("100"),
        generated_at=NOW,
        can_trade_session=lambda session: session == "regular",
        positive_decimal_or_none=lambda v: (
            Decimal(str(v)) if v not in (None, "") and Decimal(str(v)) > 0 else None
        ),
        live_sleeve="pullback-support",
    )
    assert decision is not None
    assert decision.decision == "close"
    close = decision.actions[0]
    assert close.action == "close"
    assert close.side == "sell"
    assert close.limit_price == Decimal("90.72")
    assert "policy_stop_floor" in close.reason


def test_hourly_decision_holds_when_market_closed():
    decision = build_loss_review_decision(
        worst_position=_position("-0.09"),
        loss_review_plpc=Decimal("-0.05"),
        market_session="closed",
        live_exposure=Decimal("100"),
        generated_at=NOW,
        can_trade_session=lambda session: session == "regular",
        positive_decimal_or_none=lambda v: (
            Decimal(str(v)) if v not in (None, "") and Decimal(str(v)) > 0 else None
        ),
        live_sleeve="pullback-support",
    )
    assert decision is not None
    assert decision.decision == "loss-review"
    assert decision.actions == []


def test_load_exit_policy_overrides_from_envelope(tmp_path):
    envelope = tmp_path / "risk_envelope.yaml"
    envelope.write_text(
        "hard_stop_loss_pct: 6\ntime_stop_trading_days: 10\n", encoding="utf-8"
    )
    policy = load_exit_policy(envelope)
    assert policy.hard_stop_loss_pct == Decimal("6")
    assert policy.time_stop_trading_days == 10
    assert (
        policy.catastrophic_stop_loss_pct
        == DEFAULT_EXIT_POLICY.catastrophic_stop_loss_pct
    )
    assert load_exit_policy(tmp_path / "missing.yaml") == DEFAULT_EXIT_POLICY
    assert isinstance(policy, ExitPolicy)
