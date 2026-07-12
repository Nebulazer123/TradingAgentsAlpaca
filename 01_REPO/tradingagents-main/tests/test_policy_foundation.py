import json
from decimal import Decimal

from tradingagents.policy.packets import write_shadow_run_packet
from tradingagents.schemas.trading import (
    CandidatePacket,
    FeaturePacket,
    RiskGateDecision,
    RunPacket,
    SourceProvenance,
    TradeIntent,
)
from tradingagents.sleeves.pullback_support import PullbackFeatures, evaluate_pullback_support


def test_trading_schema_round_trip_and_shadow_packet(tmp_path):
    source = SourceProvenance(source="alpaca", as_of="2026-06-01T15:00:00+00:00")
    candidate = CandidatePacket(
        symbol="MSFT",
        as_of="2026-06-01T15:00:00+00:00",
        universe_bucket="liquid",
        sources=[source],
    )
    features = FeaturePacket(
        symbol="MSFT",
        as_of="2026-06-01T15:00:00+00:00",
        features={"atr_pullback_depth": {"value": "1.2", "complete": True}},
        sources=[source],
    )
    intent = TradeIntent(
        symbol="MSFT",
        sleeve="pullback-support",
        environment="paper",
        side="buy",
        order_type="limit",
        limit_price="410.00",
        size_usd="100.00",
        idempotency_key="intent-msft-paper-1",
    )
    gate = RiskGateDecision(
        intent_id=intent.intent_id,
        final_action="paper_enter",
        hard_gates={"stocks_only": True, "limit_only": True},
    )
    packet = RunPacket(
        run_id="run-test",
        run_type="shadow_policy",
        decision="order",
        candidate=candidate,
        features=features,
        intent=intent,
        gate=gate,
    )

    written = write_shadow_run_packet(packet, tmp_path)
    saved = json.loads(written.read_text(encoding="utf-8"))

    assert saved["schema_version"] == "1.0.0"
    assert saved["candidate"]["symbol"] == "MSFT"
    assert saved["intent"]["order_type"] == "limit"
    assert saved["gate"]["final_action"] == "paper_enter"


def test_pullback_support_good_dip_emits_paper_intent():
    result = evaluate_pullback_support(
        PullbackFeatures(
            symbol="MSFT",
            current_price=Decimal("410"),
            support_level=Decimal("408"),
            atr=Decimal("4"),
            pullback_atr=Decimal("1.1"),
            above_rising_50d=True,
            above_rising_200d=True,
            sell_volume_state="decelerating",
            gap_state="reclaimed",
            sector_relative_strength=Decimal("0.62"),
            regime_state="neutral",
            earnings_blackout=False,
            fresh_negative_event=False,
        )
    )

    assert result.decision == "paper_enter"
    assert result.intent is not None
    assert result.intent.sleeve == "pullback-support"
    assert result.intent.environment == "paper"
    assert result.intent.entry_plan["reward_risk_ratio"] == "2.00"


def test_pullback_support_rejects_green_spike_chase():
    result = evaluate_pullback_support(
        PullbackFeatures(
            symbol="MSFT",
            current_price=Decimal("423"),
            support_level=Decimal("408"),
            atr=Decimal("4"),
            pullback_atr=Decimal("1.1"),
            above_rising_50d=True,
            above_rising_200d=True,
            sell_volume_state="decelerating",
            gap_state="reclaimed",
            sector_relative_strength=Decimal("0.62"),
            regime_state="neutral",
            green_spike_atr=Decimal("1.25"),
        )
    )

    assert result.decision == "HOLD_CASH"
    assert result.intent is None
    assert "missing_good_dip_condition:no_green_spike_chase" in result.reasons


def test_pullback_support_requires_improving_evidence_and_reward_risk():
    result = evaluate_pullback_support(
        PullbackFeatures(
            symbol="MSFT",
            current_price=Decimal("410"),
            support_level=Decimal("408"),
            atr=Decimal("4"),
            pullback_atr=Decimal("1.1"),
            above_rising_50d=True,
            above_rising_200d=True,
            sell_volume_state="decelerating",
            gap_state="reclaimed",
            sector_relative_strength=Decimal("0.62"),
            regime_state="neutral",
            evidence_trend="deteriorating",
            reward_risk_ratio=Decimal("1.20"),
        )
    )

    assert result.decision == "HOLD_CASH"
    assert result.intent is None
    assert "missing_good_dip_condition:evidence_improving" in result.reasons
    assert "missing_good_dip_condition:reward_risk_ok" in result.reasons


def test_pullback_support_falling_knife_holds_cash():
    result = evaluate_pullback_support(
        PullbackFeatures(
            symbol="MSFT",
            current_price=Decimal("390"),
            support_level=Decimal("408"),
            atr=Decimal("4"),
            pullback_atr=Decimal("3.4"),
            above_rising_50d=False,
            above_rising_200d=False,
            sell_volume_state="expanding",
            gap_state="open_down",
            sector_relative_strength=Decimal("0.30"),
            regime_state="risk_off",
            earnings_blackout=True,
            fresh_negative_event=True,
        )
    )

    assert result.decision == "HOLD_CASH"
    assert result.intent is None
    assert "falling_knife" in result.reasons
