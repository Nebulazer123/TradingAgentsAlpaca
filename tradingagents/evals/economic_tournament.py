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
from tradingagents.evals.economic_evaluation_result import (
    EconomicValidationResult,
    build_validation_evaluation_result,
)
from tradingagents.sleeves.pullback_support import PullbackFeatures, evaluate_pullback_support

__all__ = [
    "EconomicTournamentError",
    "EconomicTournamentCandidate",
    "ControlArmAllocation",
    "EconomicTournamentOutcome",
    "build_ta_control_allocations",
    "evaluate_validation_ta_control",
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


@dataclass(frozen=True, slots=True)
class EconomicTournamentOutcome:
    """One realized, source-bound outcome vector for a frozen decision event."""

    decision_event_id: str
    realized_returns: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.decision_event_id.startswith("decision-event-"):
            raise EconomicTournamentError("outcome decision event identity is invalid")
        if type(self.realized_returns) is not tuple or not self.realized_returns:
            raise EconomicTournamentError("realized_returns must be a nonempty exact tuple")
        symbols = []
        for symbol, value in self.realized_returns:
            if type(symbol) is not str or not symbol.isupper():
                raise EconomicTournamentError("outcome return symbol is invalid")
            parsed = _decimal(value, label="realized_return", positive=False)
            if parsed is None or parsed < Decimal("-1"):
                raise EconomicTournamentError("realized_return is invalid")
            symbols.append(symbol)
        if tuple(symbols) != tuple(sorted(symbols)) or len(set(symbols)) != len(symbols):
            raise EconomicTournamentError("outcome return symbols must be canonical")

    def return_for(self, symbol: str) -> Decimal:
        for known_symbol, value in self.realized_returns:
            if known_symbol == symbol:
                parsed = _decimal(value, label="realized_return", positive=False)
                assert parsed is not None
                return parsed
        raise EconomicTournamentError(f"outcome is missing realized return for {symbol}")


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


def _text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _arm_return(allocation: ControlArmAllocation, outcome: EconomicTournamentOutcome) -> tuple[Decimal, Decimal, Decimal]:
    selected = allocation.selected_symbols
    invested = Decimal("1") - Decimal(allocation.cash_weight)
    if not selected:
        return Decimal("0"), Decimal("0"), Decimal("0")
    gross = sum((outcome.return_for(symbol) for symbol in selected), Decimal("0")) / Decimal(len(selected))
    turnover = invested * Decimal("2")
    return gross, turnover, invested


def evaluate_validation_ta_control(
    *,
    protocol: FrozenEvaluationProtocol,
    candidates_by_event: dict[str, tuple[EconomicTournamentCandidate, ...]],
    outcomes: tuple[EconomicTournamentOutcome, ...],
) -> EconomicValidationResult:
    """Evaluate the sealed validation events and build canonical arm metrics."""

    if type(protocol) is not FrozenEvaluationProtocol:
        raise EconomicTournamentError("protocol must be an exact frozen value")
    frozen = validate_frozen_evaluation_protocol(protocol.to_dict())
    expected_ids = frozen.validation_event_ids
    if type(candidates_by_event) is not dict or set(candidates_by_event) != set(expected_ids):
        raise EconomicTournamentError("candidate inputs must exactly cover validation events")
    if type(outcomes) is not tuple or tuple(item.decision_event_id for item in outcomes) != expected_ids:
        raise EconomicTournamentError("outcomes must be canonically ordered validation events")
    events = {event.decision_event_id: event for event in frozen.input_manifest.events}
    metrics: dict[str, dict[str, str]] = {}
    per_arm: dict[str, list[tuple[Decimal, Decimal, Decimal]]] = {arm: [] for arm in CONTROL_ARM_IDS}
    for outcome in outcomes:
        event = events[outcome.decision_event_id]
        required_symbols = tuple(sorted((*frozen.primary_universe, "SPY")))
        if tuple(symbol for symbol, _value in outcome.realized_returns) != required_symbols:
            raise EconomicTournamentError("outcome must cover primary universe and SPY exactly")
        for allocation in build_ta_control_allocations(
            protocol=frozen,
            decision_event=event,
            candidates=candidates_by_event[event.decision_event_id],
        ):
            per_arm[allocation.arm_id].append(_arm_return(allocation, outcome))
    policy_cost = Decimal(frozen.evaluation_policy["commission_bps_per_side"]) + Decimal(frozen.evaluation_policy["half_spread_bps_per_side"]) + Decimal(frozen.evaluation_policy["slippage_bps_per_side"])
    per_side_cost = policy_cost / Decimal("10000")
    benchmark_returns = per_arm["spy"]
    packet_clusters = len({events[event_id].packet_event_cluster_id for event_id in expected_ids})
    market_clusters = len({events[event_id].market_event_cluster_id for event_id in expected_ids})
    for arm in CONTROL_ARM_IDS:
        capital = Decimal("1")
        peak = capital
        drawdown = Decimal("0")
        total_turnover = Decimal("0")
        total_cost = Decimal("0")
        false_positives = 0
        useful = 0
        net_returns: list[Decimal] = []
        for gross, turnover, invested in per_arm[arm]:
            cost = turnover * per_side_cost
            net = gross - cost
            net_returns.append(net)
            total_turnover += turnover
            total_cost += cost
            capital *= Decimal("1") + net
            peak = max(peak, capital)
            drawdown = min(drawdown, capital / peak - Decimal("1"))
            if net > 0:
                useful += 1
            elif invested > 0:
                false_positives += 1
        benchmark_net = [gross - turnover * per_side_cost for gross, turnover, _ in benchmark_returns]
        metrics[arm] = {
            "net_return_after_costs": _text(capital - Decimal("1")),
            "benchmark_excess_after_costs": _text(sum(net_returns, Decimal("0")) - sum(benchmark_net, Decimal("0"))),
            "max_drawdown": _text(drawdown),
            "turnover": _text(total_turnover),
            "false_positive_rate": _text(Decimal(false_positives) / Decimal(len(expected_ids))),
            "decision_event_count": str(len(expected_ids)),
            "packet_event_cluster_count": str(packet_clusters),
            "market_event_cluster_count": str(market_clusters),
            "cost_per_useful_decision": _text(total_cost / Decimal(useful) if useful else total_cost),
        }
    return build_validation_evaluation_result(frozen, arm_metrics=metrics)
