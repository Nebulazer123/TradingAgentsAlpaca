"""Deterministic paper-only pullback-support sleeve."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal

from tradingagents.schemas.trading import (
    CandidatePacket,
    FeaturePacket,
    RiskGateDecision,
    RunPacket,
    SourceProvenance,
    TradeIntent,
)


@dataclass(frozen=True)
class PullbackFeatures:
    symbol: str
    current_price: Decimal
    support_level: Decimal
    atr: Decimal
    pullback_atr: Decimal
    above_rising_50d: bool
    above_rising_200d: bool
    sell_volume_state: str
    gap_state: str
    sector_relative_strength: Decimal
    regime_state: str
    earnings_blackout: bool = False
    fresh_negative_event: bool = False
    green_spike_atr: Decimal = Decimal("0")
    evidence_trend: str = "improving"
    reward_risk_ratio: Decimal = Decimal("2.0")
    notional_usd: Decimal = Decimal("100")


@dataclass(frozen=True)
class PullbackDecision:
    decision: str
    reasons: list[str] = field(default_factory=list)
    score: Decimal = Decimal("0")
    intent: TradeIntent | None = None


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _intent_key(features: PullbackFeatures) -> str:
    raw = "|".join(
        [
            "pullback-support",
            features.symbol.upper(),
            _money(features.support_level),
            _money(features.current_price),
            _money(features.notional_usd),
            "paper",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def evaluate_pullback_support(features: PullbackFeatures) -> PullbackDecision:
    reasons: list[str] = []
    falling_knife = False
    if not features.above_rising_200d or not features.above_rising_50d:
        reasons.append("falling_knife: trend anchors are broken")
        falling_knife = True
    if features.pullback_atr > Decimal("3.0"):
        reasons.append("falling_knife: pullback exceeds 3 ATR without reclaim")
        falling_knife = True
    if features.sell_volume_state.lower() in {"expanding", "distribution", "panic"}:
        reasons.append("falling_knife: down volume is expanding")
        falling_knife = True
    if features.gap_state.lower() in {"open_down", "large_open_down"}:
        reasons.append("falling_knife: downside gap remains open")
        falling_knife = True
    if features.regime_state.lower() in {"risk_off", "panic"}:
        reasons.append("falling_knife: regime blocks new risk")
        falling_knife = True
    if features.earnings_blackout or features.fresh_negative_event:
        reasons.append("falling_knife: event blackout or fresh negative event")
        falling_knife = True

    if falling_knife:
        return PullbackDecision(
            decision="HOLD_CASH",
            reasons=[*reasons, "falling_knife"],
        )

    near_support = features.support_level > 0 and (
        abs(features.current_price - features.support_level) / features.support_level
        <= Decimal("0.015")
    )
    controlled_depth = Decimal("0.75") <= features.pullback_atr <= Decimal("2.5")
    volume_ok = features.sell_volume_state.lower() in {"decelerating", "moderate", "normal"}
    gap_ok = features.gap_state.lower() in {"none", "small", "reclaimed"}
    sector_ok = features.sector_relative_strength >= Decimal("0.50")
    regime_ok = features.regime_state.lower() in {"neutral", "risk_on"}
    no_green_spike_chase = features.green_spike_atr <= Decimal("1.0")
    evidence_improving = features.evidence_trend.lower() in {
        "confirmed",
        "improving",
        "reclaiming",
        "stabilizing",
    }
    reward_risk_ok = features.reward_risk_ratio >= Decimal("1.80")

    checks = {
        "near_support": near_support,
        "controlled_depth": controlled_depth,
        "volume_ok": volume_ok,
        "gap_ok": gap_ok,
        "sector_ok": sector_ok,
        "regime_ok": regime_ok,
        "no_green_spike_chase": no_green_spike_chase,
        "evidence_improving": evidence_improving,
        "reward_risk_ok": reward_risk_ok,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        return PullbackDecision(
            decision="HOLD_CASH",
            reasons=[f"missing_good_dip_condition:{name}" for name in failed],
        )

    score = Decimal("0.75")
    intent = TradeIntent(
        intent_id=f"intent-{features.symbol.upper()}-pullback-support-paper",
        idempotency_key=_intent_key(features),
        symbol=features.symbol,
        sleeve="pullback-support",
        environment="paper",
        limit_price=_money(features.current_price),
        limit_low=_money(min(features.support_level, features.current_price)),
        limit_high=_money(max(features.support_level, features.current_price)),
        tif="day",
        size_usd=_money(features.notional_usd),
        size_context={
            "notional_usd": _money(features.notional_usd),
            "paper_only": True,
            "source": "deterministic_pullback_support",
        },
        entry_plan={
            "type": "support_hold_or_reclaim",
            "support_level": _money(features.support_level),
            "evidence_trend": features.evidence_trend,
            "reward_risk_ratio": _money(features.reward_risk_ratio),
        },
        exit_plan={
            "time_stop_days": 5,
            "invalidator": "support_failure_or_fresh_negative_event",
        },
        invalidator={
            "hard_block_conditions": [
                "fresh_negative_event",
                "earnings_blackout",
                "close_below_support",
            ]
        },
        gate_trace=[{"gate": name, "passed": True} for name in checks],
    )
    return PullbackDecision(
        decision="paper_enter",
        reasons=["good_dip"],
        score=score,
        intent=intent,
    )


def _feature_values(features: PullbackFeatures) -> dict:
    return {
        "current_price": str(features.current_price),
        "support_level": str(features.support_level),
        "atr": str(features.atr),
        "pullback_atr": str(features.pullback_atr),
        "above_rising_50d": features.above_rising_50d,
        "above_rising_200d": features.above_rising_200d,
        "sell_volume_state": features.sell_volume_state,
        "gap_state": features.gap_state,
        "sector_relative_strength": str(features.sector_relative_strength),
        "regime_state": features.regime_state,
        "earnings_blackout": features.earnings_blackout,
        "fresh_negative_event": features.fresh_negative_event,
        "green_spike_atr": str(features.green_spike_atr),
        "evidence_trend": features.evidence_trend,
        "reward_risk_ratio": str(features.reward_risk_ratio),
        "notional_usd": str(features.notional_usd),
    }


def build_pullback_support_run_packet(
    features: PullbackFeatures,
    *,
    decision: PullbackDecision | None = None,
    run_id: str,
    as_of: str,
    source_name: str = "pullback_support:deterministic",
    universe_bucket: str = "manual_cli",
) -> RunPacket:
    """Build the immutable decision packet for order and HOLD_CASH outcomes."""

    result = decision or evaluate_pullback_support(features)
    normalized_symbol = features.symbol.strip().upper()
    source = SourceProvenance(
        source=source_name,
        as_of=as_of,
        quality="medium",
    )
    candidate = CandidatePacket(
        symbol=normalized_symbol,
        as_of=as_of,
        universe_bucket=universe_bucket,
        eligibility={
            "stocks_only": True,
            "long_only": True,
            "paper_only": True,
            "deterministic": True,
        },
        event_flags={
            "earnings_blackout": features.earnings_blackout,
            "fresh_negative_event": features.fresh_negative_event,
        },
        freshness={"as_of": as_of, "stale": False},
        sources=[source],
    )
    feature_completeness = {
        "trend_anchors": features.above_rising_50d and features.above_rising_200d,
        "support_proximity": features.support_level > 0,
        "atr_depth": features.atr > 0,
        "volume_behavior": bool(features.sell_volume_state),
        "gap_state": bool(features.gap_state),
        "sector_confirmation": features.sector_relative_strength >= Decimal("0"),
        "blackout_flags": True,
    }
    feature_packet = FeaturePacket(
        symbol=normalized_symbol,
        as_of=as_of,
        features=_feature_values(features),
        completeness=(
            Decimal(sum(1 for passed in feature_completeness.values() if passed))
            / Decimal(len(feature_completeness))
        ),
        feature_completeness=feature_completeness,
        freshness={"as_of": as_of, "stale": False},
        sources=[source],
    )
    final_action = "paper_enter" if result.intent else "hold_cash"
    hard_gates = {
        "paper_only": True,
        "stocks_only": True,
        "long_only": True,
        "limit_only": True,
        "no_options": True,
        "no_crypto": True,
        "no_margin": True,
        "deterministic_pullback_support": True,
        "no_event_blackout": not (features.earnings_blackout or features.fresh_negative_event),
    }
    gate = RiskGateDecision(
        intent_id=result.intent.intent_id if result.intent else None,
        hard_gates=hard_gates,
        soft_gates={
            "sector_confirmation": features.sector_relative_strength >= Decimal("0.50"),
            "controlled_pullback_depth": Decimal("0.75") <= features.pullback_atr <= Decimal("2.5"),
        },
        final_action=final_action,
        rejection_reasons=[] if result.intent else result.reasons,
    )
    return RunPacket(
        run_id=run_id,
        run_type="pullback_support_policy",
        decision="order" if result.intent else "hold_cash",
        candidate=candidate,
        features=feature_packet,
        intent=result.intent,
        gate=gate,
        audit={
            "sleeve": "pullback-support",
            "environment": "paper",
            "score": str(result.score),
            "reasons": result.reasons,
            "live_submission": "not_allowed_from_pullback_support_paper_loop",
            "paper_submit_requires": ["alpaca_check", "dry_run", "paper_enabled"],
        },
    )
