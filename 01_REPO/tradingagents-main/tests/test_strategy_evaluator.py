from __future__ import annotations

import ast
import dataclasses
import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import (
    ROUND_CEILING,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    getcontext,
)
from pathlib import Path
from typing import Any

import pytest

from tradingagents.strategy.compiler import StrategyObservation
from tradingagents.strategy.evaluator import (
    EVALUATOR_DECIMAL_PRECISION,
    EVALUATOR_VERSION,
    GENOME_WINDOW_RESULT_SCHEMA_VERSION,
    STRATEGY_EVALUATION_POLICY_SCHEMA_VERSION,
    EvaluatedTrade,
    EvaluationFrame,
    EvaluationMark,
    GenomeWindowResult,
    StrategyEvaluationPolicy,
    evaluate_genome_window,
    evaluation_frames_sha256,
    load_strategy_evaluation_policy,
)
from tradingagents.strategy.genome import (
    CatalystRelativeStrengthMutationBounds,
    CatalystRelativeStrengthParameters,
    CurrentAggressiveMutationBounds,
    CurrentAggressiveParameters,
    HoldCashParameters,
    PullbackSupportMutationBounds,
    PullbackSupportParameters,
    StrategyEvolutionPolicy,
    StrategyFamily,
    StrategyGenome,
    StrategyMutationBounds,
)

ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = ROOT / "tradingagents" / "strategy" / "evaluator.py"
POLICY_PATH = ROOT / "config" / "strategy_evaluation.json"


def _evolution_policy(
    *,
    starting_cash: str = "200",
    minimum_order: str = "10",
    enabled: bool = True,
) -> StrategyEvolutionPolicy:
    return StrategyEvolutionPolicy(
        enabled=enabled,
        experiment_starting_cash_usd=starting_cash,
        candidate_min_order_usd=minimum_order,
        max_active_candidates=4,
        mutations_per_cycle=2,
        minimum_tracked_days=5,
        minimum_closed_trades=10,
        minimum_walk_forward_windows=3,
        maximum_paper_drawdown_pct="-10",
        mutation_bounds=StrategyMutationBounds(
            current_aggressive=CurrentAggressiveMutationBounds("0.05"),
            pullback_support=PullbackSupportMutationBounds("0.005", "0.005", "0.5"),
            catalyst_relative_strength=(CatalystRelativeStrengthMutationBounds("0.05")),
        ),
    )


def _evaluation_policy(
    *,
    holding_sessions: int = 5,
    commission: str = "0",
    spread: str = "5",
    slippage: str = "5",
) -> StrategyEvaluationPolicy:
    return StrategyEvaluationPolicy(
        benchmark_symbol="SPY",
        holding_sessions=holding_sessions,
        commission_bps_per_side=commission,
        half_spread_bps_per_side=spread,
        slippage_bps_per_side=slippage,
        round_trip_sides=2,
    )


def _genome(
    family: StrategyFamily = StrategyFamily.CURRENT_AGGRESSIVE,
    *,
    generation: int = 0,
    parent_id: str = "builtin-baseline",
) -> StrategyGenome:
    parameters = {
        StrategyFamily.HOLD_CASH: HoldCashParameters(),
        StrategyFamily.CURRENT_AGGRESSIVE: CurrentAggressiveParameters("0.7"),
        StrategyFamily.PULLBACK_SUPPORT: PullbackSupportParameters("-0.025", "-0.003", "2.5"),
        StrategyFamily.CATALYST_RELATIVE_STRENGTH: (CatalystRelativeStrengthParameters("0.65")),
    }[family]
    return StrategyGenome.create(
        family=family,
        parameters=parameters,
        generation=generation,
        parent_id=parent_id,
    )


def _observation(
    price: Decimal,
    *,
    symbol: str = "NFLX",
    score: Decimal = Decimal("0.8"),
    daily_change: Decimal = Decimal("-0.01"),
    volume_ratio: Decimal = Decimal("1"),
    time_sensitive: bool = True,
) -> StrategyObservation:
    return StrategyObservation(
        symbol=symbol,
        score=score,
        current_price=price,
        daily_change_fraction=daily_change,
        volume_ratio=volume_ratio,
        time_sensitive=time_sensitive,
    )


def _frames(
    prices: list[str],
    *,
    symbol: str = "NFLX",
    benchmark_prices: list[str] | None = None,
    eligible: bool = True,
    start: datetime = datetime(2026, 7, 1, 14, 30, tzinfo=UTC),
) -> tuple[EvaluationFrame, ...]:
    benchmarks = benchmark_prices or ["100"] * len(prices)
    result = []
    for index, (price_text, benchmark_text) in enumerate(zip(prices, benchmarks, strict=True)):
        effective_at = start + timedelta(days=index)
        price = Decimal(price_text)
        observation = _observation(
            price,
            symbol=symbol,
            score=Decimal("0.8") if eligible else Decimal("0.6"),
        )
        result.append(
            EvaluationFrame(
                session_date=effective_at.date(),
                effective_at=effective_at,
                recorded_at=effective_at + timedelta(minutes=1),
                market_session="regular",
                observations=(observation,),
                marks=(EvaluationMark(symbol, price),),
                benchmark_price=Decimal(benchmark_text),
            )
        )
    return tuple(result)


def _evaluate(
    prices: list[str],
    *,
    genome: StrategyGenome | None = None,
    policy: StrategyEvaluationPolicy | None = None,
    evolution_policy: StrategyEvolutionPolicy | None = None,
    eligible: bool = True,
    benchmark_prices: list[str] | None = None,
) -> GenomeWindowResult:
    frames = _frames(
        prices,
        eligible=eligible,
        benchmark_prices=benchmark_prices,
    )
    return evaluate_genome_window(
        genome or _genome(),
        evolution_policy or _evolution_policy(),
        policy or _evaluation_policy(),
        frames,
        evaluation_as_of=frames[-1].recorded_at,
    )


def _payload() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _write_payload(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "strategy-evaluation.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_exact_config_and_cost_conversion() -> None:
    policy = load_strategy_evaluation_policy(POLICY_PATH)

    assert policy == _evaluation_policy()
    assert policy.schema_version == STRATEGY_EVALUATION_POLICY_SCHEMA_VERSION == 1
    assert EVALUATOR_DECIMAL_PRECISION == 50
    assert GENOME_WINDOW_RESULT_SCHEMA_VERSION == 1
    assert policy.per_side_cost_fraction == Decimal("0.001")
    assert policy.round_trip_cost_fraction == Decimal("0.002")
    assert policy.to_dict() == _payload()
    assert json.loads(policy.canonical_json_bytes()) == _payload()


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("schema_version", True, (TypeError, ValueError)),
        ("benchmark_symbol", "spy", ValueError),
        ("benchmark_symbol", True, TypeError),
        ("holding_sessions", True, TypeError),
        ("holding_sessions", 0, ValueError),
        ("holding_sessions", 253, ValueError),
        ("commission_bps_per_side", 0, TypeError),
        ("commission_bps_per_side", "1e1", ValueError),
        ("commission_bps_per_side", "-0", ValueError),
        ("half_spread_bps_per_side", "-1", ValueError),
        ("slippage_bps_per_side", "1000.1", ValueError),
        ("round_trip_sides", True, TypeError),
        ("round_trip_sides", 1, ValueError),
        ("analysis_only", False, ValueError),
        ("execution_authority", "broker", ValueError),
        ("can_submit_orders", True, ValueError),
    ],
)
def test_config_rejects_invalid_types_bounds_and_authority(
    tmp_path: Path,
    field: str,
    value: object,
    error: type[BaseException] | tuple[type[BaseException], ...],
) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(error):
        load_strategy_evaluation_policy(_write_payload(tmp_path, payload))


def test_config_rejects_duplicate_missing_extra_and_zero_cost(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        POLICY_PATH.read_text(encoding="utf-8").replace(
            '"holding_sessions": 5,',
            '"holding_sessions": 5, "holding_sessions": 5,',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_strategy_evaluation_policy(duplicate)

    for payload in (
        {key: value for key, value in _payload().items() if key != "benchmark_symbol"},
        {**_payload(), "extra": True},
        {
            **_payload(),
            "half_spread_bps_per_side": "0",
            "slippage_bps_per_side": "0",
        },
    ):
        with pytest.raises(ValueError):
            load_strategy_evaluation_policy(_write_payload(tmp_path, payload))


@pytest.mark.parametrize(
    "family",
    [
        StrategyFamily.CURRENT_AGGRESSIVE,
        StrategyFamily.PULLBACK_SUPPORT,
        StrategyFamily.CATALYST_RELATIVE_STRENGTH,
    ],
)
@pytest.mark.parametrize(("exit_price", "won"), [("110", True), ("90", False)])
def test_exact_profit_and_loss_for_every_executable_family(family: StrategyFamily, exit_price: str, won: bool) -> None:
    result = _evaluate(
        ["100", "100", "100", "100", "100", exit_price],
        genome=_genome(family),
    )

    assert result.closed_trade_count == 1
    assert result.winning_trade_count == int(won)
    assert result.false_positive_count == int(not won)
    trade = result.trades[0]
    assert trade.won is won
    assert trade.false_positive is (not won)
    assert trade.entry_session == "2026-07-01"
    assert trade.exit_session == "2026-07-06"
    assert trade.holding_sessions == 5


def test_exact_200_plus_ten_percent_cost_arithmetic_and_units() -> None:
    result = _evaluate(
        ["100", "100", "100", "100", "100", "110"],
        benchmark_prices=["100"] * 6,
    )
    trade = result.trades[0]

    assert trade.entry_budget_usd == "200"
    assert trade.entry_cost_usd == "0.2"
    assert trade.entry_exposure_usd == "199.8"
    assert trade.gross_exit_value_usd == "219.78"
    assert trade.exit_cost_usd == "0.21978"
    assert trade.net_exit_proceeds_usd == "219.56022"
    assert trade.gross_return_fraction == "0.1"
    assert trade.modeled_round_trip_cost_fraction == "0.002"
    assert trade.net_return_fraction == "0.0978011"
    assert trade.realized_cost_drag_fraction == "0.0021989"
    assert trade.gross_pnl_usd == "20"
    assert trade.pnl_usd == "19.56022"
    assert trade.benchmark_return_fraction == "0"
    assert trade.excess_return_fraction == "0.0978011"
    assert result.starting_cash_usd == "200"
    assert result.gross_ending_equity_usd == "220"
    assert result.ending_equity_usd == "219.56022"
    assert result.gross_return_fraction == "0.1"
    assert result.net_return_fraction == "0.0978011"
    assert Decimal("0.10") == Decimal(trade.gross_return_fraction)
    assert _evaluation_policy().round_trip_cost_fraction == Decimal("0.002")


def test_hold_cash_and_no_eligible_windows() -> None:
    hold = _evaluate(["100"] * 6, genome=_genome(StrategyFamily.HOLD_CASH))
    ineligible = _evaluate(["100"] * 6, eligible=False)

    for result in (hold, ineligible):
        assert result.closed_trade_count == 0
        assert result.ending_equity_usd == "200"
        assert result.gross_return_fraction == "0"
        assert result.net_return_fraction == "0"
        assert result.benchmark_excess_return_fraction == "0"
        assert result.positive_after_costs is False


def test_close_before_open_fixed_horizon_compounds_profit_above_200() -> None:
    result = _evaluate(["100", "100", "100", "100", "100", "110", "110", "110", "110", "110", "121"])

    assert result.closed_trade_count == 2
    first, second = result.trades
    assert first.exit_session == second.entry_session
    assert first.holding_sessions == second.holding_sessions == 5
    assert second.entry_budget_usd == "219.56"
    assert Decimal(second.entry_budget_usd) > Decimal("200")
    assert Decimal(result.ending_equity_usd) > Decimal(first.net_exit_proceeds_usd)
    assert result.equity_curve_usd[-1] == result.ending_equity_usd


def test_minimum_order_no_orphan_and_fractional_high_price() -> None:
    too_small = _evaluate(
        ["500"] * 6,
        evolution_policy=_evolution_policy(starting_cash="9", minimum_order="9"),
    )
    high_price = _evaluate(["500", "500", "500", "500", "500", "550"])

    assert too_small.closed_trade_count == 1
    assert too_small.trades[0].entry_budget_usd == "9"
    assert high_price.closed_trade_count == 1
    assert high_price.trades[0].gross_return_fraction == "0.1"
    assert high_price.trades[0].gross_exit_value_usd == "219.78"

    exact_minimum = _evaluate(
        ["100"] * 6,
        evolution_policy=_evolution_policy(starting_cash="10", minimum_order="10"),
    )
    assert exact_minimum.closed_trade_count == 1
    assert exact_minimum.trades[0].entry_budget_usd == "10"


def test_entry_cost_affects_equity_immediately_and_drawdown_recomputes() -> None:
    result = _evaluate(["100"] * 6)
    curve = tuple(map(Decimal, result.equity_curve_usd))

    assert curve[0] == Decimal("200")
    assert curve[1] == Decimal("199.6002")
    peak = curve[0]
    drawdowns = []
    for value in curve:
        peak = max(peak, value)
        drawdowns.append(value / peak - 1)
    assert Decimal(result.max_drawdown_fraction) == min(drawdowns)
    assert result.max_drawdown_fraction == "-0.001999"


def test_subcent_values_survive_and_flat_near_zero_never_go_negative() -> None:
    subcent = _evaluate(
        [
            "10.000000000001",
            "10.000000000001",
            "10.000000000001",
            "10.000000000001",
            "10.000000000001",
            "11.000000000001",
        ]
    )
    near_zero = _evaluate(["100", "100", "100", "100", "100", "0.000000000001"])

    assert subcent.trades[0].entry_reference_price == "10.000000000001"
    assert json.loads(_frames(["10.000000000001"])[0].canonical_json_bytes())["marks"][0]["price"] == "10.000000000001"
    assert Decimal(near_zero.ending_equity_usd) >= 0
    assert Decimal(near_zero.trades[0].net_exit_proceeds_usd) >= 0


def test_flat_and_worst_configured_costs_never_make_cash_negative() -> None:
    flat = _evaluate(["100"] * 6)
    worst_cost = _evaluate(
        ["100"] * 6,
        policy=_evaluation_policy(
            commission="1000",
            spread="1000",
            slippage="1000",
        ),
    )

    assert flat.trades[0].gross_return_fraction == "0"
    assert Decimal(flat.ending_equity_usd) >= 0
    assert worst_cost.trades[0].modeled_round_trip_cost_fraction == "0.6"
    assert worst_cost.trades[0].entry_exposure_usd == "140"
    assert worst_cost.trades[0].net_exit_proceeds_usd == "98"
    assert Decimal(worst_cost.ending_equity_usd) >= 0


def test_benchmark_and_excess_are_fractional() -> None:
    result = _evaluate(
        ["100", "100", "100", "100", "100", "110"],
        benchmark_prices=["100", "100", "100", "100", "100", "105"],
    )
    trade = result.trades[0]

    assert trade.benchmark_return_fraction == "0.05"
    assert trade.excess_return_fraction == "0.0478011"
    assert result.benchmark_return_fraction == "0.05"
    assert result.benchmark_excess_return_fraction == "0.0478011"


def test_frame_canonicalization_and_data_changes_bind_hashes() -> None:
    frames = _frames(["100"] * 6)
    changed = list(frames)
    changed[2] = dataclasses.replace(
        changed[2],
        benchmark_price=Decimal("100.000000000001"),
    )
    baseline = evaluate_genome_window(
        _genome(),
        _evolution_policy(),
        _evaluation_policy(),
        frames,
        evaluation_as_of=frames[-1].recorded_at,
    )
    modified = evaluate_genome_window(
        _genome(),
        _evolution_policy(),
        _evaluation_policy(),
        tuple(changed),
        evaluation_as_of=frames[-1].recorded_at,
    )

    assert baseline.input_frames_sha256 != modified.input_frames_sha256
    assert baseline.window_id != modified.window_id
    assert evaluation_frames_sha256(frames) == baseline.input_frames_sha256
    assert evaluation_frames_sha256(tuple(changed)) == modified.input_frames_sha256
    assert json.loads(frames[0].canonical_json_bytes()) == frames[0].to_dict()


def test_lineage_policy_and_decisions_bind_window_id() -> None:
    frames = _frames(["100"] * 6)
    first = evaluate_genome_window(
        _genome(generation=0, parent_id="root"),
        _evolution_policy(),
        _evaluation_policy(),
        frames,
        evaluation_as_of=frames[-1].recorded_at,
    )
    lineage = evaluate_genome_window(
        _genome(generation=1, parent_id="descendant"),
        _evolution_policy(),
        _evaluation_policy(),
        frames,
        evaluation_as_of=frames[-1].recorded_at,
    )
    policy = evaluate_genome_window(
        _genome(generation=0, parent_id="root"),
        _evolution_policy(),
        _evaluation_policy(spread="6"),
        frames,
        evaluation_as_of=frames[-1].recorded_at,
    )

    assert first.genome_id == lineage.genome_id
    assert first.genome_canonical_sha256 != lineage.genome_canonical_sha256
    assert first.window_id != lineage.window_id
    assert first.evaluation_policy_sha256 != policy.evaluation_policy_sha256
    assert first.window_id != policy.window_id
    assert len(first.ordered_decision_sha256s) == 1


def test_result_rejects_digest_tampering() -> None:
    result = _evaluate(["100"] * 6)
    with pytest.raises(ValueError, match="window_id"):
        dataclasses.replace(result, input_frames_sha256="0" * 64)


def test_strict_result_and_trade_round_trip_and_tamper_rejection() -> None:
    result = _evaluate(["100", "100", "100", "100", "100", "110"])
    trade = result.trades[0]

    restored_trade = EvaluatedTrade.from_dict(trade.to_dict())
    restored_result = GenomeWindowResult.from_dict(result.to_dict())
    restored_json_result = GenomeWindowResult.from_dict(json.loads(result.canonical_json_bytes()))
    assert restored_trade.canonical_json_bytes() == trade.canonical_json_bytes()
    assert restored_result.canonical_json_bytes() == result.canonical_json_bytes()
    assert restored_json_result.canonical_json_bytes() == result.canonical_json_bytes()

    trade_payload = trade.to_dict()
    trade_payload["entry_cost_usd"] = "0.21"
    with pytest.raises(ValueError):
        EvaluatedTrade.from_dict(trade_payload)
    result_payload = result.to_dict()
    result_payload["ending_equity_usd"] = "1"
    with pytest.raises(ValueError):
        GenomeWindowResult.from_dict(result_payload)
    for payload in (
        {key: value for key, value in result.to_dict().items() if key != "window_id"},
        {**result.to_dict(), "extra": True},
        {**result.to_dict(), "analysis_only": False},
        {**result.to_dict(), "schema_version": True},
        {**result.to_dict(), "trades": {}},
        {**result.to_dict(), "equity_curve_usd": "200"},
        {**result.to_dict(), "ordered_decision_sha256s": {}},
        {**result.to_dict(), "window_id": "0" * 64},
        {**result.to_dict(), "net_return_fraction": "0.10"},
        {**result.to_dict(), "input_frames_sha256": "0" * 64},
        {**result.to_dict(), "genome_canonical_sha256": "0" * 64},
        {**result.to_dict(), "evolution_policy_sha256": "0" * 64},
        {**result.to_dict(), "evaluation_policy_sha256": "0" * 64},
        {**result.to_dict(), "ordered_decision_sha256s": ["0" * 64]},
    ):
        with pytest.raises((TypeError, ValueError)):
            GenomeWindowResult.from_dict(payload)

    for payload in (
        {key: value for key, value in trade.to_dict().items() if key != "symbol"},
        {**trade.to_dict(), "extra": True},
        {**trade.to_dict(), "execution_authority": "live"},
        {**trade.to_dict(), "decision_sha256": "A" * 64},
        {**trade.to_dict(), "entry_cost_usd": "0.200"},
    ):
        with pytest.raises((TypeError, ValueError)):
            EvaluatedTrade.from_dict(payload)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda frames, as_of: (tuple(reversed(frames)), as_of),
        lambda frames, as_of: (frames[:-1], as_of),
        lambda frames, as_of: (
            (frames[0], dataclasses.replace(frames[1], session_date=frames[0].session_date)) + frames[2:],
            as_of,
        ),
        lambda frames, as_of: (
            (
                dataclasses.replace(
                    frames[0],
                    effective_at=frames[0].effective_at + timedelta(days=1),
                ),
            )
            + frames[1:],
            as_of,
        ),
        lambda frames, as_of: (
            (
                dataclasses.replace(
                    frames[0],
                    recorded_at=frames[0].effective_at - timedelta(seconds=1),
                ),
            )
            + frames[1:],
            as_of,
        ),
        lambda frames, as_of: (frames, frames[-1].recorded_at - timedelta(seconds=1)),
    ],
)
def test_frame_order_horizon_and_time_boundaries_fail_closed(mutator: Any) -> None:
    frames = _frames(["100"] * 6)
    with pytest.raises((TypeError, ValueError)):
        changed, as_of = mutator(frames, frames[-1].recorded_at)
        evaluate_genome_window(
            _genome(),
            _evolution_policy(),
            _evaluation_policy(),
            changed,
            evaluation_as_of=as_of,
        )


def test_exact_utc_and_wrong_frame_objects_fail_closed() -> None:
    frame = _frames(["100"] * 6)[0]
    with pytest.raises(ValueError):
        dataclasses.replace(
            frame,
            effective_at=frame.effective_at.astimezone(timezone(timedelta(hours=1))),
        )
    with pytest.raises(TypeError):
        evaluate_genome_window(
            _genome(),
            _evolution_policy(),
            _evaluation_policy(),
            [{"legacy_return_pct": "10.00"}] * 6,  # type: ignore[arg-type]
            evaluation_as_of=datetime(2026, 7, 7, tzinfo=UTC),
        )


def test_duplicate_symbols_mark_mismatch_and_missing_open_mark_fail_closed() -> None:
    frame = _frames(["100"] * 6)[0]
    with pytest.raises(ValueError, match="duplicate"):
        dataclasses.replace(frame, observations=frame.observations * 2)
    with pytest.raises(ValueError, match="duplicate"):
        dataclasses.replace(frame, marks=frame.marks * 2)
    with pytest.raises(ValueError, match="mark"):
        dataclasses.replace(
            frame,
            marks=(EvaluationMark("NFLX", Decimal("101")),),
        )

    frames = list(_frames(["100"] * 6))
    frames[3] = dataclasses.replace(
        frames[3],
        observations=(),
        marks=(),
    )
    with pytest.raises(ValueError, match="mark"):
        evaluate_genome_window(
            _genome(),
            _evolution_policy(),
            _evaluation_policy(),
            frames,
            evaluation_as_of=frames[-1].recorded_at,
        )


@pytest.mark.parametrize(
    "price",
    [
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("0"),
        Decimal("-1"),
        Decimal("1.0000000000001"),
        Decimal("12345678901234567890123456789012345"),
        Decimal("1000000000000.1"),
    ],
)
def test_price_bounds_fail_before_arithmetic(price: Decimal) -> None:
    with pytest.raises((TypeError, ValueError)):
        EvaluationMark("NFLX", price)


def test_deterministic_under_hostile_decimal_context_and_input_immutable() -> None:
    frames = _frames(["100", "100", "100", "100", "100", "110"])
    before = tuple(frame.canonical_json_bytes() for frame in frames)
    context = getcontext()
    saved = context.copy()
    try:
        baseline = evaluate_genome_window(
            _genome(),
            _evolution_policy(),
            _evaluation_policy(),
            frames,
            evaluation_as_of=frames[-1].recorded_at,
        )
        context.prec = 4
        context.rounding = ROUND_CEILING
        context.Emin = -9
        context.Emax = 9
        context.traps[InvalidOperation] = True
        context.traps[DivisionByZero] = True
        context.traps[Overflow] = True
        context.flags[InvalidOperation] = True
        hostile_context_before = context.copy()
        hostile = evaluate_genome_window(
            _genome(),
            _evolution_policy(),
            _evaluation_policy(),
            frames,
            evaluation_as_of=frames[-1].recorded_at,
        )
        assert hostile.canonical_json_bytes() == baseline.canonical_json_bytes()
        assert hostile.window_id == baseline.window_id
        assert tuple(frame.canonical_json_bytes() for frame in frames) == before
        assert context.prec == hostile_context_before.prec
        assert context.rounding == hostile_context_before.rounding
        assert context.Emin == hostile_context_before.Emin
        assert context.Emax == hostile_context_before.Emax
        assert context.traps == hostile_context_before.traps
        assert context.flags == hostile_context_before.flags
    finally:
        getcontext().prec = saved.prec
        getcontext().rounding = saved.rounding
        getcontext().Emin = saved.Emin
        getcontext().Emax = saved.Emax
        getcontext().traps = saved.traps.copy()
        getcontext().flags = saved.flags.copy()


def test_frozen_outputs_exact_serialization_and_authority() -> None:
    result = _evaluate(["100"] * 6)
    trade = result.trades[0]

    for value in (result, trade, _evaluation_policy(), *_frames(["100"] * 6)[:1]):
        assert dataclasses.is_dataclass(value)
        with pytest.raises(dataclasses.FrozenInstanceError):
            value.analysis_only = False  # type: ignore[misc]
    assert result.evaluator_version == EVALUATOR_VERSION
    assert result.analysis_only is True
    assert result.paper_only is True
    assert result.execution_authority == "none"
    assert result.can_submit_orders is False
    assert trade.analysis_only is True
    assert trade.execution_authority == "none"
    assert trade.can_submit_orders is False
    assert json.loads(result.canonical_json_bytes()) == result.to_dict()


def test_dependency_and_literal_isolation() -> None:
    tree = ast.parse(EVALUATOR_PATH.read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports.update(node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None)
    assert all(
        name.startswith(
            (
                "__future__",
                "collections",
                "dataclasses",
                "datetime",
                "decimal",
                "hashlib",
                "json",
                "pathlib",
                "re",
                "typing",
                "tradingagents.strategy.compiler",
                "tradingagents.strategy.genome",
            )
        )
        for name in imports
    )
    source = EVALUATOR_PATH.read_text(encoding="utf-8").lower()
    forbidden = (
        "alpaca",
        "broker",
        "promotion",
        "live_control",
        "submit_order(",
        "_return_pct",
        "_transaction_cost_return",
        "_action_notional",
        "build_walk_forward_return_rows_from_overnight_packets",
    )
    assert all(token not in source for token in forbidden)
    assert source.count("[frame.to_dict() for frame in frames_snapshot]") == 1
    evaluate_source = ast.get_source_segment(
        EVALUATOR_PATH.read_text(encoding="utf-8"),
        next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "evaluate_genome_window"),
    )
    assert evaluate_source is not None
    assert "evaluation_frames_sha256(frames_snapshot)" in evaluate_source
