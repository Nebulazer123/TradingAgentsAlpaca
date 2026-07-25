from __future__ import annotations

import ast
import dataclasses
import json
from decimal import (
    ROUND_UP,
    Decimal,
    Inexact,
    getcontext,
)
from pathlib import Path
from typing import Any

import pytest

from tradingagents.strategy.compiler import (
    PAPER_DECISION_SCHEMA_VERSION,
    GenomePaperDecision,
    PaperCandidateState,
    PaperDecisionAction,
    StrategyObservation,
    compile_genome_paper_decision,
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
COMPILER_PATH = ROOT / "tradingagents" / "strategy" / "compiler.py"
ALLOWED_REASON_CODES = {
    "genome_hold_cash",
    "market_closed",
    "policy_disabled",
    "insufficient_virtual_cash",
    "no_eligible_observation",
    "eligible_current_aggressive",
    "eligible_pullback_support",
    "eligible_catalyst_relative_strength",
}


def _policy(
    *,
    enabled: bool = True,
    starting_cash: str = "200",
    minimum_order: str = "10",
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
            pullback_support=PullbackSupportMutationBounds(
                "0.005",
                "0.005",
                "0.25",
            ),
            catalyst_relative_strength=(
                CatalystRelativeStrengthMutationBounds("0.05")
            ),
        ),
    )


def _genome(
    family: StrategyFamily = StrategyFamily.CURRENT_AGGRESSIVE,
) -> StrategyGenome:
    parameters = {
        StrategyFamily.HOLD_CASH: HoldCashParameters(),
        StrategyFamily.CURRENT_AGGRESSIVE: CurrentAggressiveParameters("0.7"),
        StrategyFamily.PULLBACK_SUPPORT: PullbackSupportParameters(
            "-0.025",
            "-0.003",
            "2.5",
        ),
        StrategyFamily.CATALYST_RELATIVE_STRENGTH: (
            CatalystRelativeStrengthParameters("0.65")
        ),
    }[family]
    return StrategyGenome.create(
        family=family,
        parameters=parameters,
        generation=0,
        parent_id="builtin-baseline",
    )


def _observation(
    symbol: str = "NFLX",
    *,
    score: Decimal = Decimal("0.8"),
    current_price: Decimal = Decimal("10"),
    daily_change: Decimal = Decimal("-0.01"),
    volume_ratio: Decimal = Decimal("1"),
    time_sensitive: bool = True,
) -> StrategyObservation:
    return StrategyObservation(
        symbol=symbol,
        score=score,
        current_price=current_price,
        daily_change_fraction=daily_change,
        volume_ratio=volume_ratio,
        time_sensitive=time_sensitive,
    )


def _state(
    *,
    cash: Decimal = Decimal("200.00"),
    reserved: Decimal = Decimal("0.00"),
    held: tuple[str, ...] = (),
    open_buys: tuple[str, ...] = (),
) -> PaperCandidateState:
    return PaperCandidateState(
        cash_usd=cash,
        reserved_buy_notional_usd=reserved,
        held_symbols=held,
        open_buy_symbols=open_buys,
    )


def _compile(
    family: StrategyFamily = StrategyFamily.CURRENT_AGGRESSIVE,
    *,
    policy: StrategyEvolutionPolicy | None = None,
    observations: list[StrategyObservation] | tuple[StrategyObservation, ...] | None = None,
    state: PaperCandidateState | None = None,
    market_session: str = "regular",
) -> GenomePaperDecision:
    return compile_genome_paper_decision(
        _genome(family),
        policy or _policy(),
        observations if observations is not None else [_observation()],
        state or _state(),
        market_session=market_session,
    )


def _assert_hold(
    decision: GenomePaperDecision,
    *,
    family: StrategyFamily,
    reason: str,
) -> None:
    assert decision.family is family
    assert decision.action is PaperDecisionAction.HOLD_CASH
    assert decision.symbol is None
    assert decision.notional_usd == "0.00"
    assert decision.limit_price is None
    assert decision.reason_code == reason
    assert decision.rejected_observation_count == 0
    assert decision.analysis_only is True
    assert decision.paper_only is True
    assert decision.execution_authority == "none"
    assert decision.can_submit_orders is False


@pytest.mark.parametrize(
    ("family", "policy", "observations", "state", "session", "reason"),
    [
        (
            StrategyFamily.HOLD_CASH,
            _policy(),
            [_observation()],
            _state(),
            "regular",
            "genome_hold_cash",
        ),
        (
            StrategyFamily.CURRENT_AGGRESSIVE,
            _policy(),
            [_observation()],
            _state(),
            "closed",
            "market_closed",
        ),
        (
            StrategyFamily.CURRENT_AGGRESSIVE,
            _policy(enabled=False),
            [_observation()],
            _state(),
            "regular",
            "policy_disabled",
        ),
        (
            StrategyFamily.CURRENT_AGGRESSIVE,
            _policy(),
            [_observation()],
            _state(cash=Decimal("9.99")),
            "regular",
            "insufficient_virtual_cash",
        ),
        (
            StrategyFamily.CURRENT_AGGRESSIVE,
            _policy(),
            [_observation(score=Decimal("0.69"))],
            _state(),
            "regular",
            "no_eligible_observation",
        ),
    ],
)
def test_exact_hold_cash_decisions(
    family: StrategyFamily,
    policy: StrategyEvolutionPolicy,
    observations: list[StrategyObservation],
    state: PaperCandidateState,
    session: str,
    reason: str,
) -> None:
    decision = compile_genome_paper_decision(
        _genome(family),
        policy,
        observations,
        state,
        market_session=session,
    )

    _assert_hold(decision, family=family, reason=reason)
    assert decision.market_session == session
    assert decision.extended_hours is False


@pytest.mark.parametrize(
    ("family", "observation", "reason"),
    [
        (
            StrategyFamily.CURRENT_AGGRESSIVE,
            _observation(score=Decimal("0.7")),
            "eligible_current_aggressive",
        ),
        (
            StrategyFamily.PULLBACK_SUPPORT,
            _observation(
                daily_change=Decimal("-0.025"),
                volume_ratio=Decimal("2.5"),
            ),
            "eligible_pullback_support",
        ),
        (
            StrategyFamily.CATALYST_RELATIVE_STRENGTH,
            _observation(score=Decimal("0.65"), time_sensitive=True),
            "eligible_catalyst_relative_strength",
        ),
    ],
)
def test_exact_buy_decision_and_canonical_serialization(
    family: StrategyFamily,
    observation: StrategyObservation,
    reason: str,
) -> None:
    genome = _genome(family)
    decision = compile_genome_paper_decision(
        genome,
        _policy(),
        [observation],
        _state(),
        market_session="regular",
    )
    expected = {
        "schema_version": PAPER_DECISION_SCHEMA_VERSION,
        "genome_id": genome.genome_id,
        "family": family.value,
        "action": "buy",
        "symbol": "NFLX",
        "notional_usd": "200.00",
        "limit_price": "10.02",
        "market_session": "regular",
        "extended_hours": False,
        "reason_code": reason,
        "rejected_observation_count": 0,
        "analysis_only": True,
        "paper_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }

    assert decision.to_dict() == expected
    assert decision.canonical_json_bytes() == json.dumps(
        expected,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert not decision.canonical_json_bytes().endswith(b"\n")


@pytest.mark.parametrize(
    ("score", "expected_action"),
    [
        (Decimal("0.699999"), PaperDecisionAction.HOLD_CASH),
        (Decimal("0.7"), PaperDecisionAction.BUY),
        (Decimal("0.700001"), PaperDecisionAction.BUY),
    ],
)
def test_current_aggressive_score_threshold(
    score: Decimal,
    expected_action: PaperDecisionAction,
) -> None:
    assert _compile(
        observations=[_observation(score=score)]
    ).action is expected_action


@pytest.mark.parametrize(
    ("score", "expected_action"),
    [
        (Decimal("0.649999"), PaperDecisionAction.HOLD_CASH),
        (Decimal("0.65"), PaperDecisionAction.BUY),
        (Decimal("0.650001"), PaperDecisionAction.BUY),
    ],
)
def test_catalyst_score_threshold(
    score: Decimal,
    expected_action: PaperDecisionAction,
) -> None:
    assert _compile(
        StrategyFamily.CATALYST_RELATIVE_STRENGTH,
        observations=[_observation(score=score, time_sensitive=True)],
    ).action is expected_action


@pytest.mark.parametrize(
    ("daily_change", "volume_ratio", "expected_action"),
    [
        (Decimal("-0.025001"), Decimal("2.5"), PaperDecisionAction.HOLD_CASH),
        (Decimal("-0.025"), Decimal("2.5"), PaperDecisionAction.BUY),
        (Decimal("-0.024999"), Decimal("2.5"), PaperDecisionAction.BUY),
        (Decimal("-0.003001"), Decimal("2.5"), PaperDecisionAction.BUY),
        (Decimal("-0.003"), Decimal("2.5"), PaperDecisionAction.BUY),
        (Decimal("-0.002999"), Decimal("2.5"), PaperDecisionAction.HOLD_CASH),
        (Decimal("-0.01"), Decimal("2.499999"), PaperDecisionAction.BUY),
        (Decimal("-0.01"), Decimal("2.5"), PaperDecisionAction.BUY),
        (Decimal("-0.01"), Decimal("2.500001"), PaperDecisionAction.HOLD_CASH),
    ],
)
def test_pullback_thresholds(
    daily_change: Decimal,
    volume_ratio: Decimal,
    expected_action: PaperDecisionAction,
) -> None:
    assert _compile(
        StrategyFamily.PULLBACK_SUPPORT,
        observations=[
            _observation(
                daily_change=daily_change,
                volume_ratio=volume_ratio,
            )
        ],
    ).action is expected_action


def test_catalyst_requires_time_sensitive_observation() -> None:
    _assert_hold(
        _compile(
            StrategyFamily.CATALYST_RELATIVE_STRENGTH,
            observations=[
                _observation(score=Decimal("1"), time_sensitive=False)
            ],
        ),
        family=StrategyFamily.CATALYST_RELATIVE_STRENGTH,
        reason="no_eligible_observation",
    )


def test_daily_change_is_a_raw_fraction() -> None:
    decision = _compile(
        StrategyFamily.PULLBACK_SUPPORT,
        observations=[_observation(daily_change=Decimal("-0.025"))],
    )
    assert decision.action is PaperDecisionAction.BUY
    assert _compile(
        StrategyFamily.PULLBACK_SUPPORT,
        observations=[_observation(daily_change=Decimal("-0.25"))],
    ).action is PaperDecisionAction.HOLD_CASH


@pytest.mark.parametrize(
    ("family", "observations", "expected_symbol"),
    [
        (
            StrategyFamily.CURRENT_AGGRESSIVE,
            [
                _observation("MSFT", score=Decimal("0.8")),
                _observation("AAPL", score=Decimal("0.8")),
                _observation("NVDA", score=Decimal("0.9")),
            ],
            "NVDA",
        ),
        (
            StrategyFamily.CATALYST_RELATIVE_STRENGTH,
            [
                _observation("MSFT", score=Decimal("0.8")),
                _observation("AAPL", score=Decimal("0.8")),
            ],
            "AAPL",
        ),
        (
            StrategyFamily.PULLBACK_SUPPORT,
            [
                _observation(
                    "MSFT",
                    daily_change=Decimal("-0.02"),
                    volume_ratio=Decimal("2"),
                ),
                _observation(
                    "AAPL",
                    daily_change=Decimal("-0.01"),
                    volume_ratio=Decimal("2"),
                ),
                _observation(
                    "GOOG",
                    daily_change=Decimal("-0.01"),
                    volume_ratio=Decimal("2"),
                ),
                _observation(
                    "NFLX",
                    daily_change=Decimal("-0.005"),
                    volume_ratio=Decimal("1"),
                ),
            ],
            "AAPL",
        ),
    ],
)
def test_ordering_is_deterministic_and_input_order_independent(
    family: StrategyFamily,
    observations: list[StrategyObservation],
    expected_symbol: str,
) -> None:
    forward = _compile(family, observations=observations)
    reverse = _compile(family, observations=list(reversed(observations)))

    assert forward.symbol == expected_symbol
    assert reverse == forward


def test_held_and_open_buy_symbols_are_excluded_once() -> None:
    decision = _compile(
        observations=[
            _observation("AAPL", score=Decimal("1")),
            _observation("MSFT", score=Decimal("0.9")),
            _observation("NFLX", score=Decimal("0.8")),
        ],
        state=_state(
            held=("AAPL", "MSFT"),
            open_buys=("MSFT",),
        ),
    )
    assert decision.symbol == "NFLX"


@pytest.mark.parametrize(
    ("cash", "reserved", "expected_action", "expected_notional"),
    [
        (Decimal("200.00"), Decimal("0.00"), PaperDecisionAction.BUY, "200.00"),
        (Decimal("500.00"), Decimal("0.00"), PaperDecisionAction.BUY, "500.00"),
        (Decimal("10.00"), Decimal("0.00"), PaperDecisionAction.BUY, "10.00"),
        (
            Decimal("200.00"),
            Decimal("190.00"),
            PaperDecisionAction.BUY,
            "10.00",
        ),
        (
            Decimal("9.99"),
            Decimal("0.00"),
            PaperDecisionAction.HOLD_CASH,
            "0.00",
        ),
        (
            Decimal("100.00"),
            Decimal("101.00"),
            PaperDecisionAction.HOLD_CASH,
            "0.00",
        ),
    ],
)
def test_isolated_candidate_cash_sizing(
    cash: Decimal,
    reserved: Decimal,
    expected_action: PaperDecisionAction,
    expected_notional: str,
) -> None:
    decision = _compile(state=_state(cash=cash, reserved=reserved))
    assert decision.action is expected_action
    assert decision.notional_usd == expected_notional


@pytest.mark.parametrize("field_name", ["cash_usd", "reserved_buy_notional_usd"])
def test_sub_cent_candidate_state_is_rejected(field_name: str) -> None:
    values: dict[str, Any] = {
        "cash_usd": Decimal("200.00"),
        "reserved_buy_notional_usd": Decimal("0.00"),
        "held_symbols": (),
        "open_buy_symbols": (),
    }
    values[field_name] = Decimal("0.001")
    with pytest.raises(ValueError, match=field_name):
        PaperCandidateState(**values)


@pytest.mark.parametrize(
    ("session", "expected_price", "extended_hours"),
    [
        ("pre_open", "10.04", True),
        ("open_window", "10.03", False),
        ("regular", "10.03", False),
        ("pre_close", "10.03", False),
    ],
)
def test_limit_price_buffers_round_down(
    session: str,
    expected_price: str,
    extended_hours: bool,
) -> None:
    decision = _compile(
        observations=[_observation(current_price=Decimal("10.019"))],
        market_session=session,
    )
    assert decision.limit_price == expected_price
    assert decision.extended_hours is extended_hours


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("score", True),
        ("score", 1),
        ("score", 0.7),
        ("score", "0.7"),
        ("score", Decimal("NaN")),
        ("score", Decimal("Infinity")),
        ("score", Decimal("-Infinity")),
        ("current_price", True),
        ("current_price", 10),
        ("current_price", 10.0),
        ("current_price", "10"),
        ("current_price", Decimal("NaN")),
        ("daily_change_fraction", True),
        ("daily_change_fraction", 0),
        ("daily_change_fraction", 0.1),
        ("daily_change_fraction", "-0.01"),
        ("daily_change_fraction", Decimal("Infinity")),
        ("volume_ratio", True),
        ("volume_ratio", 1),
        ("volume_ratio", 1.0),
        ("volume_ratio", "1"),
        ("volume_ratio", Decimal("-Infinity")),
        ("time_sensitive", 1),
        ("time_sensitive", "true"),
    ],
)
def test_observation_rejects_non_exact_numeric_and_boolean_types(
    field_name: str,
    bad_value: object,
) -> None:
    values: dict[str, Any] = {
        "symbol": "NFLX",
        "score": Decimal("0.8"),
        "current_price": Decimal("10"),
        "daily_change_fraction": Decimal("-0.01"),
        "volume_ratio": Decimal("1"),
        "time_sensitive": True,
    }
    values[field_name] = bad_value
    with pytest.raises((TypeError, ValueError)):
        StrategyObservation(**values)


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("cash_usd", True),
        ("cash_usd", 200),
        ("cash_usd", 200.0),
        ("cash_usd", "200"),
        ("cash_usd", Decimal("NaN")),
        ("cash_usd", Decimal("Infinity")),
        ("cash_usd", Decimal("-0.01")),
        ("reserved_buy_notional_usd", True),
        ("reserved_buy_notional_usd", 0),
        ("reserved_buy_notional_usd", 0.0),
        ("reserved_buy_notional_usd", "0"),
        ("reserved_buy_notional_usd", Decimal("-Infinity")),
        ("reserved_buy_notional_usd", Decimal("-0.01")),
    ],
)
def test_state_rejects_non_exact_money_types_and_values(
    field_name: str,
    bad_value: object,
) -> None:
    values: dict[str, Any] = {
        "cash_usd": Decimal("200.00"),
        "reserved_buy_notional_usd": Decimal("0.00"),
        "held_symbols": (),
        "open_buy_symbols": (),
    }
    values[field_name] = bad_value
    with pytest.raises((TypeError, ValueError)):
        PaperCandidateState(**values)


@pytest.mark.parametrize(
    "symbol",
    [
        "",
        " nflx",
        "NFLX ",
        "nflx",
        "1NFLX",
        ".NFLX",
        "-NFLX",
        "BRK/B",
        "A_B",
        "É",
        "A" * 16,
    ],
)
def test_invalid_observation_symbols_are_rejected(symbol: str) -> None:
    with pytest.raises(ValueError, match="symbol"):
        _observation(symbol)


@pytest.mark.parametrize(
    "symbols",
    [
        ["AAPL"],
        ("AAPL", "AAPL"),
        ("aapl",),
        (" AAPL",),
        ("1AAPL",),
    ],
)
def test_state_symbol_collections_are_exact_valid_unique_tuples(
    symbols: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        PaperCandidateState(
            cash_usd=Decimal("200.00"),
            reserved_buy_notional_usd=Decimal("0.00"),
            held_symbols=symbols,  # type: ignore[arg-type]
            open_buy_symbols=(),
        )


@pytest.mark.parametrize(
    "session",
    [None, True, 1, "", "open", "PRE_OPEN", " regular", "regular "],
)
def test_unknown_or_non_string_market_session_is_rejected(
    session: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        compile_genome_paper_decision(
            _genome(),
            _policy(),
            [_observation()],
            _state(),
            market_session=session,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("genome", "policy", "observations", "state"),
    [
        ({}, _policy(), [_observation()], _state()),
        (_genome(), {}, [_observation()], _state()),
        (_genome(), _policy(), {"NFLX": _observation()}, _state()),
        (_genome(), _policy(), [_observation(), {}], _state()),
        (_genome(), _policy(), [_observation()], {}),
    ],
)
def test_compiler_rejects_wrong_object_types(
    genome: object,
    policy: object,
    observations: object,
    state: object,
) -> None:
    with pytest.raises(TypeError):
        compile_genome_paper_decision(
            genome,  # type: ignore[arg-type]
            policy,  # type: ignore[arg-type]
            observations,  # type: ignore[arg-type]
            state,  # type: ignore[arg-type]
            market_session="regular",
        )


def test_direct_decision_authority_fields_cannot_be_overridden() -> None:
    genome = _genome()
    values: dict[str, Any] = {
        "genome_id": genome.genome_id,
        "family": genome.family,
        "action": PaperDecisionAction.BUY,
        "symbol": "NFLX",
        "notional_usd": "200.00",
        "limit_price": "10.02",
        "market_session": "regular",
        "extended_hours": False,
        "reason_code": "eligible_current_aggressive",
        "rejected_observation_count": 0,
    }
    for field_name, bad_value in [
        ("schema_version", 999),
        ("analysis_only", False),
        ("paper_only", False),
        ("execution_authority", "broker"),
        ("can_submit_orders", True),
    ]:
        with pytest.raises(TypeError):
            GenomePaperDecision(**values, **{field_name: bad_value})


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("genome_id", "genome-current-aggressive-" + "0" * 63),
        ("genome_id", "genome-pullback-support-" + "0" * 64),
        ("family", "current-aggressive"),
        ("action", "buy"),
        ("notional_usd", "200"),
        ("limit_price", "10.020"),
        ("market_session", "closed"),
        ("extended_hours", True),
        ("reason_code", "source said buy"),
        ("rejected_observation_count", True),
        ("rejected_observation_count", 1),
    ],
)
def test_direct_decision_rejects_invalid_identity_or_semantics(
    field_name: str,
    bad_value: object,
) -> None:
    genome = _genome()
    values: dict[str, Any] = {
        "genome_id": genome.genome_id,
        "family": genome.family,
        "action": PaperDecisionAction.BUY,
        "symbol": "NFLX",
        "notional_usd": "200.00",
        "limit_price": "10.02",
        "market_session": "regular",
        "extended_hours": False,
        "reason_code": "eligible_current_aggressive",
        "rejected_observation_count": 0,
    }
    values[field_name] = bad_value
    with pytest.raises((TypeError, ValueError)):
        GenomePaperDecision(**values)


def test_all_inputs_and_output_are_frozen_and_not_mutated() -> None:
    genome = _genome()
    policy = _policy()
    observation = _observation()
    observations = [observation]
    state = _state(held=("AAPL",), open_buys=("MSFT",))
    snapshots = (
        genome.canonical_json_bytes(),
        policy.canonical_json_bytes(),
        tuple(observations),
        state,
    )

    decision = compile_genome_paper_decision(
        genome,
        policy,
        observations,
        state,
        market_session="regular",
    )

    assert snapshots == (
        genome.canonical_json_bytes(),
        policy.canonical_json_bytes(),
        tuple(observations),
        state,
    )
    for instance, field_name, value in [
        (observation, "symbol", "AAPL"),
        (state, "cash_usd", Decimal("0")),
        (decision, "symbol", "AAPL"),
    ]:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(instance, field_name, value)


def test_compiler_imports_only_the_approved_inert_dependency_layer() -> None:
    tree = ast.parse(COMPILER_PATH.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")

    assert imports <= {
        "__future__",
        "collections.abc",
        "dataclasses",
        "decimal",
        "enum",
        "typing",
        "tradingagents.strategy.genome",
    }


def test_compiler_contains_no_runtime_or_external_operation_literals() -> None:
    source = COMPILER_PATH.read_text(encoding="utf-8").lower()
    forbidden = {
        "alpaca",
        "broker",
        "submit_order",
        "cancel_order",
        "replace_order",
        "order_client",
        "live_control",
        "paper_tournament",
        "results/",
        "http://",
        "https://",
        "api_key",
        "secret",
        "openai",
        "anthropic",
        "prompt",
        "datetime",
        "time.time",
        "random",
        "uuid",
    }

    assert forbidden.isdisjoint(source)
    assert all(reason_code in source for reason_code in ALLOWED_REASON_CODES)


def _decimal_context_signature() -> tuple[object, ...]:
    context = getcontext()
    return (
        context.prec,
        context.rounding,
        context.Emin,
        context.Emax,
        context.capitals,
        context.clamp,
        dict(context.traps),
        dict(context.flags),
    )


@pytest.mark.parametrize(
    ("family", "observations", "expected_symbol"),
    [
        (
            StrategyFamily.CURRENT_AGGRESSIVE,
            [
                _observation(
                    "AAPL",
                    score=Decimal("0.8000000"),
                    current_price=Decimal("100.005"),
                ),
                _observation(
                    "MSFT",
                    score=Decimal("0.8000001"),
                    current_price=Decimal("100.005"),
                ),
            ],
            "MSFT",
        ),
        (
            StrategyFamily.PULLBACK_SUPPORT,
            [
                _observation(
                    "AAPL",
                    current_price=Decimal("100.005"),
                    daily_change=Decimal("-0.0100001"),
                    volume_ratio=Decimal("2.0000000"),
                ),
                _observation(
                    "MSFT",
                    current_price=Decimal("100.005"),
                    daily_change=Decimal("-0.0100000"),
                    volume_ratio=Decimal("2.0000001"),
                ),
            ],
            "MSFT",
        ),
        (
            StrategyFamily.CATALYST_RELATIVE_STRENGTH,
            [
                _observation(
                    "AAPL",
                    score=Decimal("0.8000000"),
                    current_price=Decimal("100.005"),
                ),
                _observation(
                    "MSFT",
                    score=Decimal("0.8000001"),
                    current_price=Decimal("100.005"),
                ),
            ],
            "MSFT",
        ),
    ],
)
@pytest.mark.parametrize(
    ("market_session", "expected_limit_price"),
    [("pre_open", "100.30"), ("regular", "100.20")],
)
def test_compiler_is_independent_of_hostile_caller_decimal_context(
    family: StrategyFamily,
    observations: list[StrategyObservation],
    expected_symbol: str,
    market_session: str,
    expected_limit_price: str,
) -> None:
    genome = _genome(family)
    policy = _policy()
    state = _state(cash=Decimal("500.00"), reserved=Decimal("1.23"))
    expected = compile_genome_paper_decision(
        genome,
        policy,
        observations,
        state,
        market_session=market_session,
    ).canonical_json_bytes()
    caller = getcontext()
    original = caller.copy()
    try:
        caller.prec = 2
        caller.rounding = ROUND_UP
        caller.Emin = -2
        caller.Emax = 2
        caller.traps[Inexact] = True
        caller.clear_flags()
        caller.flags[Inexact] = True
        before = _decimal_context_signature()

        actual = compile_genome_paper_decision(
            genome,
            policy,
            tuple(reversed(observations)),
            state,
            market_session=market_session,
        )

        assert actual.canonical_json_bytes() == expected
        assert actual.symbol == expected_symbol
        assert actual.notional_usd == "498.77"
        assert actual.limit_price == expected_limit_price
        assert _decimal_context_signature() == before
    finally:
        getcontext().prec = original.prec
        getcontext().rounding = original.rounding
        getcontext().Emin = original.Emin
        getcontext().Emax = original.Emax
        getcontext().capitals = original.capitals
        getcontext().clamp = original.clamp
        getcontext().traps = original.traps
        getcontext().flags = original.flags


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("score", Decimal("0." + "1" * 35)),
        ("current_price", Decimal("1.0000000000001")),
        ("current_price", Decimal("1E+47")),
        ("daily_change_fraction", Decimal("-0.0000000000001")),
        ("volume_ratio", Decimal("1.0000000000001")),
    ],
)
def test_observation_rejects_excessive_digits_scale_or_magnitude(
    field_name: str,
    bad_value: Decimal,
) -> None:
    values: dict[str, object] = {
        "symbol": "NFLX",
        "score": Decimal("0.8"),
        "current_price": Decimal("10"),
        "daily_change_fraction": Decimal("-0.01"),
        "volume_ratio": Decimal("1"),
        "time_sensitive": True,
    }
    values[field_name] = bad_value

    with pytest.raises(ValueError, match=field_name):
        StrategyObservation(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("price", "expected_limit_price"),
    [
        (
            Decimal("1234567890123456789012345678901234"),
            "1237037025903703702590370370259036.46",
        ),
        (
            Decimal("1E+34"),
            "10020000000000000000000000000000000.00",
        ),
    ],
)
def test_observation_accepts_bounded_large_price(
    price: Decimal,
    expected_limit_price: str,
) -> None:
    decision = _compile(observations=[_observation(current_price=price)])

    assert decision.limit_price == expected_limit_price


@pytest.mark.parametrize(
    "field_name",
    ["cash_usd", "reserved_buy_notional_usd"],
)
def test_candidate_state_rejects_excessive_money_magnitude(
    field_name: str,
) -> None:
    values: dict[str, object] = {
        "cash_usd": Decimal("200.00"),
        "reserved_buy_notional_usd": Decimal("0.00"),
        "held_symbols": (),
        "open_buy_symbols": (),
    }
    values[field_name] = Decimal("1000000000000000000.01")

    with pytest.raises(ValueError, match=field_name):
        PaperCandidateState(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("family", "policy", "state", "session"),
    [
        (StrategyFamily.HOLD_CASH, _policy(), _state(), "regular"),
        (StrategyFamily.CURRENT_AGGRESSIVE, _policy(), _state(), "closed"),
        (
            StrategyFamily.PULLBACK_SUPPORT,
            _policy(enabled=False),
            _state(),
            "regular",
        ),
        (
            StrategyFamily.CATALYST_RELATIVE_STRENGTH,
            _policy(),
            _state(cash=Decimal("9.99")),
            "regular",
        ),
    ],
)
def test_duplicate_observation_symbols_fail_closed_before_selection(
    family: StrategyFamily,
    policy: StrategyEvolutionPolicy,
    state: PaperCandidateState,
    session: str,
) -> None:
    duplicates = [
        _observation("NFLX", current_price=Decimal("10")),
        _observation("NFLX", current_price=Decimal("20")),
    ]

    with pytest.raises(ValueError, match="duplicate observation symbol"):
        compile_genome_paper_decision(
            _genome(family),
            policy,
            duplicates,
            state,
            market_session=session,
        )
