"""TA-Control allocation contracts."""

from __future__ import annotations

import hashlib

import pytest

from tradingagents.evals.economic_evaluation_protocol import (
    EvaluationSearchBudget,
    build_bitemporal_input_manifest,
    build_decision_event,
    build_frozen_evaluation_protocol,
    canonical_universe_id,
)
from tradingagents.evals.economic_tournament import (
    EconomicTournamentCandidate,
    EconomicTournamentError,
    EconomicTournamentOutcome,
    build_ta_control_allocations,
    evaluate_validation_ta_control,
)
from tradingagents.strategy.evaluator import StrategyEvaluationPolicy

UNIVERSE = tuple(f"T{index:03d}" for index in range(75))


def _event(symbol: str):
    return build_decision_event(
        universe_id=canonical_universe_id(UNIVERSE), symbol=symbol,
        decision_at="2026-01-09T20:55:00+00:00", market_date="2026-01-09",
        horizon_sessions=5, horizon="5_sessions", benchmark="SPY",
        created_at="2026-01-09T20:45:00+00:00",
        resolution_window={"start_at": "2026-01-09T20:55:00+00:00"},
        observation_start="2026-01-09T19:00:00+00:00",
        observation_end="2026-01-09T20:50:00+00:00",
        available_at="2026-01-09T20:50:00+00:00",
        recorded_at="2026-01-09T20:52:00+00:00",
        source_packet_id=f"packet-{symbol}", source_artifact_id=f"artifact-{symbol}",
        source_artifact_sha256=hashlib.sha256(symbol.encode()).hexdigest(),
    )


def _protocol():
    events = (_event("T000"), _event("T001"), _event("T002"))
    manifest = build_bitemporal_input_manifest(
        dataset_id="pit-fixture-v1", as_of_cutoff="2026-01-09T21:00:00+00:00",
        captured_at="2026-01-09T21:00:00+00:00", events=events,
    )
    return build_frozen_evaluation_protocol(
        input_manifest=manifest, primary_universe=UNIVERSE,
        sensitivity_universe_50=UNIVERSE[:50],
        sensitivity_universe_100=tuple(f"T{index:03d}" for index in range(100)),
        evaluation_policy=StrategyEvaluationPolicy(
            benchmark_symbol="SPY", holding_sessions=5, commission_bps_per_side="0",
            half_spread_bps_per_side="5", slippage_bps_per_side="5", round_trip_sides=2,
        ),
        search_budget=EvaluationSearchBudget(5, 3, 25),
        development_event_ids=(events[0].decision_event_id,),
        validation_event_ids=(events[1].decision_event_id,),
        holdout_event_ids=(events[2].decision_event_id,),
    ), events


def test_ta_control_uses_frozen_universe_and_leaves_missing_inputs_in_cash():
    protocol, events = _protocol()
    event = events[0]
    candidates = tuple(
        EconomicTournamentCandidate(
            symbol=symbol, available_at="2026-01-09T20:50:00+00:00",
            close_t_21="110" if symbol == "T000" else None,
            close_t_252="100" if symbol == "T000" else None,
            trailing_operating_income="10" if symbol == "T000" else None,
            average_total_assets="100" if symbol == "T000" else None,
        )
        for symbol in UNIVERSE
    )
    arms = {arm.arm_id: arm for arm in build_ta_control_allocations(
        protocol=protocol, decision_event=event, candidates=candidates
    )}

    assert tuple(arms) == ("cash", "spy", "equal_weight", "momentum_quality", "pullback_support")
    assert arms["equal_weight"].selected_symbols == UNIVERSE
    assert arms["momentum_quality"].selected_symbols == ("T000",)
    assert arms["momentum_quality"].cash_weight == "0.9333333333333333333333333333"
    assert arms["pullback_support"].cash_weight == "1"


def test_ta_control_rejects_candidate_universe_or_event_outside_protocol():
    protocol, events = _protocol()
    event = events[0]
    candidates = tuple(EconomicTournamentCandidate(symbol=symbol, available_at="2026-01-09T20:50:00+00:00") for symbol in UNIVERSE)
    with pytest.raises(EconomicTournamentError):
        build_ta_control_allocations(protocol=protocol, decision_event=event, candidates=candidates[:-1])


def test_validation_tournament_builds_canonical_complete_result():
    protocol, events = _protocol()
    event = events[1]
    candidates = tuple(
        EconomicTournamentCandidate(
            symbol=symbol, available_at="2026-01-09T20:50:00+00:00",
            close_t_21="110" if symbol == "T000" else None,
            close_t_252="100" if symbol == "T000" else None,
            trailing_operating_income="10" if symbol == "T000" else None,
            average_total_assets="100" if symbol == "T000" else None,
        ) for symbol in UNIVERSE
    )
    outcome = EconomicTournamentOutcome(
        decision_event_id=event.decision_event_id,
        realized_returns=tuple(sorted(
            [(symbol, "0.01") for symbol in UNIVERSE] + [("SPY", "0.02")]
        )),
    )
    result = evaluate_validation_ta_control(
        protocol=protocol,
        candidates_by_event={event.decision_event_id: candidates},
        outcomes=(outcome,),
    )

    metrics = {row["arm_id"]: row["metrics"] for row in result.arm_metrics}
    assert result.protocol_id == protocol.protocol_id
    assert metrics["equal_weight"]["net_return_after_costs"] == "0.008"
    assert metrics["spy"]["benchmark_excess_after_costs"] == "0"
