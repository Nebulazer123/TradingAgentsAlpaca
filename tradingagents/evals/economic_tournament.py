"""Pure, protocol-bound TA-Control arm allocation.

This module computes analysis-only target allocations.  It has no store,
broker, runtime, filesystem, scheduler, or network dependency.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from tradingagents.evals.economic_evaluation_partition_binding import (
    ValidationPhaseEligibility,
    validate_validation_phase_eligibility,
)
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
from tradingagents.evals.economic_tournament_statistics import (
    WeeklyArmObservation,
    build_economic_tournament_statistics,
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
        ControlArmAllocation("equal_weight", tuple(sorted(frozen.primary_universe)), "0"),
        ControlArmAllocation("momentum_quality", momentum, _cash_weight(len(momentum), capacity=15)),
        ControlArmAllocation("pullback_support", pullback, _cash_weight(len(pullback), capacity=15)),
    )


def _text(value: Decimal) -> str:
    integral = value.to_integral_value()
    if abs(value - integral) < Decimal("1e-24"):
        value = integral
    return "0" if value.is_zero() else format(value.normalize(), "f")


def _target_weights(allocation: ControlArmAllocation) -> dict[str, Decimal]:
    invested = Decimal("1") - Decimal(allocation.cash_weight)
    result = {"CASH": Decimal(allocation.cash_weight)}
    if allocation.selected_symbols:
        weight = invested / Decimal(len(allocation.selected_symbols))
        result.update({symbol: weight for symbol in allocation.selected_symbols})
    return result


def _turnover(
    previous: dict[str, Decimal],
    target: dict[str, Decimal],
) -> Decimal:
    names = set(previous) | set(target)
    return sum(
        (abs(target.get(name, Decimal("0")) - previous.get(name, Decimal("0"))) for name in names),
        Decimal("0"),
    ) / Decimal("2")


def _compound(values: list[Decimal]) -> Decimal:
    capital = Decimal("1")
    for value in values:
        capital *= Decimal("1") + value
    return capital - Decimal("1")


def _variant_metrics(
    *,
    weekly: dict[str, list[tuple[str, Decimal, Decimal, dict[str, Decimal]]]],
    cost_bps_per_side: Decimal,
    decision_event_count: int,
    packet_clusters: int,
    market_clusters: int,
) -> tuple[
    dict[str, dict[str, str]],
    dict[str, tuple[WeeklyArmObservation, ...]],
]:
    per_side_cost = cost_bps_per_side / Decimal("10000")
    metrics: dict[str, dict[str, str]] = {}
    observations: dict[str, tuple[WeeklyArmObservation, ...]] = {}
    spy_net = [
        gross - turnover * per_side_cost
        for _date, gross, turnover, _positions in weekly["spy"]
    ]
    benchmark_compound = _compound(spy_net)
    for arm in CONTROL_ARM_IDS:
        capital = Decimal("1")
        peak = capital
        drawdown = Decimal("0")
        total_turnover = Decimal("0")
        total_cost = Decimal("0")
        false_positives = 0
        useful = 0
        net_returns: list[Decimal] = []
        rows: list[WeeklyArmObservation] = []
        for index, (market_date, gross, turnover, positions) in enumerate(weekly[arm]):
            cost = turnover * per_side_cost
            net = gross - cost
            net_returns.append(net)
            total_turnover += turnover
            total_cost += cost
            capital *= Decimal("1") + net
            peak = max(peak, capital)
            drawdown = min(drawdown, capital / peak - Decimal("1"))
            invested = Decimal("1") - positions.get("CASH", Decimal("0"))
            if net > 0:
                useful += 1
            elif invested > 0:
                false_positives += 1
            rows.append(
                WeeklyArmObservation(
                    market_date=market_date,
                    gross_return=_text(gross),
                    net_return=_text(net),
                    benchmark_net_return=_text(spy_net[index]),
                    turnover=_text(turnover),
                    cost_drag=_text(cost),
                    false_positive=net <= 0 and invested > 0,
                    positions=tuple(
                        sorted((symbol, _text(weight)) for symbol, weight in positions.items())
                    ),
                )
            )
        metrics[arm] = {
            "net_return_after_costs": _text(capital - Decimal("1")),
            "benchmark_excess_after_costs": _text(
                capital - Decimal("1") - benchmark_compound
            ),
            "max_drawdown": _text(drawdown),
            "turnover": _text(total_turnover),
            "false_positive_rate": _text(
                Decimal(false_positives) / Decimal(len(rows))
            ),
            "decision_event_count": str(decision_event_count),
            "packet_event_cluster_count": str(packet_clusters),
            "market_event_cluster_count": str(market_clusters),
            "cost_per_useful_decision": _text(
                total_cost / Decimal(useful) if useful else total_cost
            ),
        }
        observations[arm] = tuple(rows)
    return metrics, observations


def evaluate_validation_ta_control(
    *,
    protocol: FrozenEvaluationProtocol,
    eligibility: ValidationPhaseEligibility,
    candidates_by_event: dict[str, tuple[EconomicTournamentCandidate, ...]],
    outcomes: tuple[EconomicTournamentOutcome, ...],
) -> EconomicValidationResult:
    """Evaluate every symbol event once into registered weekly portfolios."""

    if type(protocol) is not FrozenEvaluationProtocol:
        raise EconomicTournamentError("protocol must be an exact frozen value")
    frozen = validate_frozen_evaluation_protocol(protocol.to_dict())
    try:
        bound = validate_validation_phase_eligibility(
            protocol=frozen,
            eligibility=eligibility,
        )
    except ValueError as exc:
        raise EconomicTournamentError(str(exc)) from exc
    expected_ids = bound.event_ids
    if type(candidates_by_event) is not dict or set(candidates_by_event) != set(expected_ids):
        raise EconomicTournamentError("candidate inputs must exactly cover validation events")
    if type(outcomes) is not tuple or tuple(item.decision_event_id for item in outcomes) != expected_ids:
        raise EconomicTournamentError("outcomes must be canonically ordered validation events")
    events = {event.decision_event_id: event for event in frozen.input_manifest.events}
    outcomes_by_id = {item.decision_event_id: item for item in outcomes}
    grouped_by_date: dict[str, list[object]] = {}
    for event_id in expected_ids:
        event = events[event_id]
        grouped_by_date.setdefault(event.market_date, []).append(event)
    grouped = OrderedDict(
        (market_date, grouped_by_date[market_date])
        for market_date in sorted(grouped_by_date)
    )
    required_symbols = tuple(sorted((*frozen.primary_universe, "SPY")))
    weekly: dict[str, list[tuple[str, Decimal, Decimal, dict[str, Decimal]]]] = {
        arm: [] for arm in CONTROL_ARM_IDS
    }
    previous = {arm: {"CASH": Decimal("1")} for arm in CONTROL_ARM_IDS}
    raw_source_rows = 0
    for market_date, date_events in grouped.items():
        event_symbols = tuple(item.symbol for item in date_events)
        if tuple(sorted(event_symbols)) != tuple(sorted(frozen.primary_universe)):
            raise EconomicTournamentError(
                "each weekly market date must use every primary symbol event exactly once"
            )
        if len({item.decision_event_id for item in date_events}) != len(date_events):
            raise EconomicTournamentError("weekly decision events must be unique")
        first_event = date_events[0]
        first_candidates = candidates_by_event[first_event.decision_event_id]
        if any(
            candidates_by_event[item.decision_event_id] != first_candidates
            for item in date_events
        ):
            raise EconomicTournamentError(
                "weekly symbol events must share one immutable candidate cross-section"
            )
        first_outcome = outcomes_by_id[first_event.decision_event_id]
        if tuple(symbol for symbol, _value in first_outcome.realized_returns) != required_symbols:
            raise EconomicTournamentError(
                "outcome must cover primary universe and SPY exactly"
            )
        if any(
            outcomes_by_id[item.decision_event_id].realized_returns
            != first_outcome.realized_returns
            for item in date_events
        ):
            raise EconomicTournamentError(
                "weekly symbol events must share one immutable outcome cross-section"
            )
        allocations = build_ta_control_allocations(
            protocol=frozen,
            decision_event=first_event,
            candidates=first_candidates,
        )
        for allocation in allocations:
            target = _target_weights(allocation)
            turnover = _turnover(previous[allocation.arm_id], target)
            gross = sum(
                (
                    weight * first_outcome.return_for(symbol)
                    for symbol, weight in target.items()
                    if symbol != "CASH"
                ),
                Decimal("0"),
            )
            weekly[allocation.arm_id].append(
                (market_date, gross, turnover, target)
            )
            previous[allocation.arm_id] = target
        raw_source_rows += len(first_candidates) + len(first_outcome.realized_returns)

    for arm in CONTROL_ARM_IDS:
        final_turnover = _turnover(previous[arm], {"CASH": Decimal("1")})
        market_date, gross, turnover, positions = weekly[arm][-1]
        weekly[arm][-1] = (
            market_date,
            gross,
            turnover + final_turnover,
            positions,
        )

    packet_clusters = len({events[event_id].packet_event_cluster_id for event_id in expected_ids})
    market_clusters = len({events[event_id].market_event_cluster_id for event_id in expected_ids})
    variants: dict[str, dict[str, dict[str, str]]] = {}
    headline_observations: dict[str, tuple[WeeklyArmObservation, ...]] | None = None
    for cost in ("5", "10", "25", "50"):
        variant, observations = _variant_metrics(
            weekly=weekly,
            cost_bps_per_side=Decimal(cost),
            decision_event_count=len(expected_ids),
            packet_clusters=packet_clusters,
            market_clusters=market_clusters,
        )
        variants[cost] = variant
        if cost == "10":
            headline_observations = observations
    assert headline_observations is not None
    statistics = build_economic_tournament_statistics(
        raw_source_row_count=raw_source_rows,
        decision_event_count=len(expected_ids),
        packet_event_cluster_count=packet_clusters,
        market_event_cluster_count=market_clusters,
        observations_by_arm=headline_observations,
    )
    return build_validation_evaluation_result(
        frozen,
        arm_metrics=variants["10"],
        eligibility=bound,
        cost_variant_metrics=variants,
        registered_statistics=statistics,
    )
