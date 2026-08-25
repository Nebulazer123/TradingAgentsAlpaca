"""Pure, protocol-bound TA-Control arm allocation.

This module computes analysis-only target allocations.  It has no store,
broker, runtime, filesystem, scheduler, or network dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from tradingagents.evals.economic_evaluation_protocol import (
    CONTROL_ARM_IDS,
    DecisionEvent,
    FrozenEvaluationProtocol,
    validate_decision_event,
    validate_frozen_evaluation_protocol,
)
from tradingagents.sleeves.pullback_support import PullbackFeatures, evaluate_pullback_support

__all__ = [
    "EconomicTournamentError",
    "EconomicTournamentCandidate",
    "ControlArmAllocation",
    "build_ta_control_allocations",
]


class EconomicTournamentError(ValueError):
    """Raised when a TA-Control allocation is not protocol-bound."""


def _decimal(value: str | None, *, label: str, positive: bool) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not str:
        raise EconomicTournamentError(f"{label} must be a canonical decimal or null")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise EconomicTournamentError(f"{label} must be a canonical decimal or null") from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise EconomicTournamentError(f"{label} has an invalid value")
    return parsed


@dataclass(frozen=True, slots=True)
class EconomicTournamentCandidate:
    """One source-bound, cutoff-limited symbol input for a weekly decision."""

    symbol: str
    available_at: str
    close_t_21: str | None = None
    close_t_252: str | None = None
    trailing_operating_income: str | None = None
    average_total_assets: str | None = None
    pullback_features: PullbackFeatures | None = None

    def __post_init__(self) -> None:
        if type(self.symbol) is not str or not self.symbol.isupper():
            raise EconomicTournamentError("candidate symbol must be uppercase")
        if type(self.available_at) is not str or not self.available_at.endswith("+00:00"):
            raise EconomicTournamentError("candidate availability must be canonical UTC")
        _decimal(self.close_t_21, label="close_t_21", positive=True)
        _decimal(self.close_t_252, label="close_t_252", positive=True)
        _decimal(self.trailing_operating_income, label="trailing_operating_income", positive=False)
        _decimal(self.average_total_assets, label="average_total_assets", positive=True)
        if self.pullback_features is not None and self.pullback_features.symbol != self.symbol:
            raise EconomicTournamentError("pullback feature symbol does not match candidate")


@dataclass(frozen=True, slots=True)
class ControlArmAllocation:
    arm_id: str
    selected_symbols: tuple[str, ...]
    cash_weight: str

    def __post_init__(self) -> None:
        if self.arm_id not in CONTROL_ARM_IDS:
            raise EconomicTournamentError("control arm is not frozen")
        if self.selected_symbols != tuple(sorted(self.selected_symbols)):
            raise EconomicTournamentError("selected symbols must be canonical")
        if len(set(self.selected_symbols)) != len(self.selected_symbols):
            raise EconomicTournamentError("selected symbols must be unique")
        _decimal(self.cash_weight, label="cash_weight", positive=False)


def _cash_weight(selected_count: int, *, capacity: int) -> str:
    return format(Decimal(capacity - selected_count) / Decimal(capacity), "f")


def _rank_momentum_quality(candidates: tuple[EconomicTournamentCandidate, ...], cutoff: str) -> tuple[str, ...]:
    eligible: list[tuple[str, Decimal, Decimal]] = []
    for item in candidates:
        if item.available_at > cutoff:
            continue
        t21 = _decimal(item.close_t_21, label="close_t_21", positive=True)
        t252 = _decimal(item.close_t_252, label="close_t_252", positive=True)
        income = _decimal(item.trailing_operating_income, label="trailing_operating_income", positive=False)
        assets = _decimal(item.average_total_assets, label="average_total_assets", positive=True)
        if None not in (t21, t252, income, assets):
            eligible.append((item.symbol, t21 / t252, income / assets))  # type: ignore[operator]
    momentum_rank = {symbol: rank for rank, (symbol, _, _) in enumerate(sorted(eligible, key=lambda row: (-row[1], row[0])), 1)}
    quality_rank = {symbol: rank for rank, (symbol, _, _) in enumerate(sorted(eligible, key=lambda row: (-row[2], row[0])), 1)}
    ranked = sorted(
        eligible,
        key=lambda row: (momentum_rank[row[0]] + quality_rank[row[0]], row[0]),
    )
    return tuple(sorted(row[0] for row in ranked[:15]))


def _rank_pullback(candidates: tuple[EconomicTournamentCandidate, ...], cutoff: str) -> tuple[str, ...]:
    qualified: list[tuple[str, Decimal]] = []
    for item in candidates:
        if item.available_at > cutoff or item.pullback_features is None:
            continue
        decision = evaluate_pullback_support(item.pullback_features)
        if decision.decision == "paper_enter":
            qualified.append((item.symbol, item.pullback_features.reward_risk_ratio - Decimal("1.80")))
    return tuple(sorted(symbol for symbol, _ in sorted(qualified, key=lambda row: (-row[1], row[0]))[:15]))


def build_ta_control_allocations(
    *,
    protocol: FrozenEvaluationProtocol,
    decision_event: DecisionEvent,
    candidates: tuple[EconomicTournamentCandidate, ...],
) -> tuple[ControlArmAllocation, ...]:
    """Build the exact five TA-Control arms for one frozen decision event."""

    if type(protocol) is not FrozenEvaluationProtocol or type(decision_event) is not DecisionEvent:
        raise EconomicTournamentError("protocol and decision_event must be exact frozen values")
    frozen = validate_frozen_evaluation_protocol(protocol.to_dict())
    event = validate_decision_event(decision_event.to_dict())
    if event.decision_event_id not in {item.decision_event_id for item in frozen.input_manifest.events}:
        raise EconomicTournamentError("decision event is not in the frozen protocol manifest")
    if type(candidates) is not tuple or tuple(item.symbol for item in candidates) != frozen.primary_universe:
        raise EconomicTournamentError("candidates must exactly match the frozen primary universe")
    momentum = _rank_momentum_quality(candidates, event.decision_at)
    pullback = _rank_pullback(candidates, event.decision_at)
    return (
        ControlArmAllocation("cash", (), "1"),
        ControlArmAllocation("spy", ("SPY",), "0"),
        ControlArmAllocation("equal_weight", frozen.primary_universe, "0"),
        ControlArmAllocation("momentum_quality", momentum, _cash_weight(len(momentum), capacity=15)),
        ControlArmAllocation("pullback_support", pullback, _cash_weight(len(pullback), capacity=15)),
    )
