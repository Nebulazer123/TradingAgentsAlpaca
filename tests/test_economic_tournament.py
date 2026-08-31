"""TA-Control allocation contracts."""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import pytest

from tests.test_economic_evaluation_protocol import protocol_source as protocol_source
from tradingagents.dataflows.pit import (
    RawPointInTimeArtifactArchive,
    build_market_date_partitions,
    build_market_session_calendar,
)
from tradingagents.evals.economic_evaluation_partition_binding import (
    EconomicPartitionBindingError,
    ValidationPhaseEligibility,
    bind_validation_phase_eligibility,
)
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


def _event(symbol: str, market_date: str = "2026-01-09"):
    return build_decision_event(
        universe_id=canonical_universe_id(UNIVERSE), symbol=symbol,
        decision_at=f"{market_date}T20:55:00+00:00", market_date=market_date,
        horizon_sessions=5, horizon="5_sessions", benchmark="SPY",
        created_at=f"{market_date}T20:45:00+00:00",
        resolution_window={"start_at": f"{market_date}T20:55:00+00:00"},
        observation_start=f"{market_date}T19:00:00+00:00",
        observation_end=f"{market_date}T20:50:00+00:00",
        available_at=f"{market_date}T20:50:00+00:00",
        recorded_at=f"{market_date}T20:52:00+00:00",
        source_packet_id=f"packet-{market_date}-{symbol}",
        source_artifact_id=f"artifact-{market_date}-{symbol}",
        source_artifact_sha256=hashlib.sha256(
            f"{market_date}-{symbol}".encode()
        ).hexdigest(),
    )


def _protocol(protocol_source):
    cohort, partitions, manifest = protocol_source
    protocol = build_frozen_evaluation_protocol(
        cohort=cohort,
        market_date_partitions=partitions,
        input_manifest=manifest,
        primary_universe=cohort.primary_universe_75,
        sensitivity_universe_50=cohort.sensitivity_universe_50,
        sensitivity_universe_100=cohort.sensitivity_universe_100,
        evaluation_policy=StrategyEvaluationPolicy(
            benchmark_symbol="SPY", holding_sessions=5, commission_bps_per_side="0",
            half_spread_bps_per_side="5", slippage_bps_per_side="5", round_trip_sides=2,
        ),
        search_budget=EvaluationSearchBudget(5, 3, 25),
        development_event_ids=partitions.development_event_ids,
        validation_event_ids=partitions.validation_event_ids,
        holdout_event_ids=partitions.holdout_event_ids,
    )
    return protocol, partitions, {
        event.decision_event_id: event for event in manifest.events
    }


def _candidates(event, universe=UNIVERSE):
    return tuple(
        EconomicTournamentCandidate(
            symbol=symbol,
            available_at=event.available_at,
            close_t_21="110" if symbol == "T000" else None,
            close_t_252="100" if symbol == "T000" else None,
            trailing_operating_income="10" if symbol == "T000" else None,
            average_total_assets="100" if symbol == "T000" else None,
        )
        for symbol in universe
    )


def _outcome(event_id: str, universe=UNIVERSE):
    return EconomicTournamentOutcome(
        decision_event_id=event_id,
        realized_returns=tuple(
            sorted([(symbol, "0.01") for symbol in universe] + [("SPY", "0.02")])
        ),
    )


def test_ta_control_uses_frozen_universe_and_leaves_missing_inputs_in_cash(protocol_source):
    protocol, _partitions, events_by_id = _protocol(protocol_source)
    event = next(iter(events_by_id.values()))
    candidates = tuple(
        EconomicTournamentCandidate(
            symbol=symbol, available_at="2026-01-09T20:50:00+00:00",
            close_t_21="110" if symbol == "T000" else None,
            close_t_252="100" if symbol == "T000" else None,
            trailing_operating_income="10" if symbol == "T000" else None,
            average_total_assets="100" if symbol == "T000" else None,
        )
        for symbol in protocol.primary_universe
    )
    arms = {arm.arm_id: arm for arm in build_ta_control_allocations(
        protocol=protocol, decision_event=event, candidates=candidates
    )}

    assert tuple(arms) == ("cash", "spy", "equal_weight", "momentum_quality", "pullback_support")
    assert arms["equal_weight"].selected_symbols == tuple(sorted(protocol.primary_universe))
    assert arms["momentum_quality"].selected_symbols == ("T000",)
    assert arms["momentum_quality"].cash_weight == "0.9333333333333333333333333333"
    assert arms["pullback_support"].cash_weight == "1"


def test_ta_control_rejects_candidate_universe_or_event_outside_protocol(protocol_source):
    protocol, _partitions, events_by_id = _protocol(protocol_source)
    event = next(iter(events_by_id.values()))
    candidates = tuple(EconomicTournamentCandidate(symbol=symbol, available_at=event.available_at) for symbol in protocol.primary_universe)
    with pytest.raises(EconomicTournamentError):
        build_ta_control_allocations(protocol=protocol, decision_event=event, candidates=candidates[:-1])


def test_validation_tournament_uses_only_purged_pit_validation_events(protocol_source):
    protocol, partitions, events_by_id = _protocol(protocol_source)
    eligibility = bind_validation_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
    )
    result = evaluate_validation_ta_control(
        protocol=protocol,
        eligibility=eligibility,
        candidates_by_event={
            event_id: _candidates(events_by_id[event_id], protocol.primary_universe)
            for event_id in eligibility.event_ids
        },
        outcomes=tuple(_outcome(event_id, protocol.primary_universe) for event_id in eligibility.event_ids),
    )

    metrics = {row["arm_id"]: row["metrics"] for row in result.arm_metrics}
    assert result.protocol_id == protocol.protocol_id
    assert len(result.validation_event_ids) == len(eligibility.event_ids) == 75
    assert metrics["equal_weight"]["net_return_after_costs"] == "0.008"
    assert metrics["spy"]["benchmark_excess_after_costs"] == "0"
    assert metrics["equal_weight"]["turnover"] == "2"
    assert [row["cost_bps_per_side"] for row in result.cost_variants] == [
        "5",
        "10",
        "25",
        "50",
    ]
    assert result.registered_statistics["primary_unit"] == "weekly_market_date"
    assert result.registered_statistics["decision_event_count"] == 75
    assert "effective_sample_size" not in json.dumps(result.to_dict())


def test_validation_eligibility_rebuilds_the_complete_pit_partition_receipt(protocol_source):
    protocol, partitions, _ = _protocol(protocol_source)
    eligibility = bind_validation_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
    )

    assert eligibility.event_ids == partitions.validation_eligible_event_ids
    assert set(eligibility.event_ids).isdisjoint(
        partitions.development_validation_embargo_event_ids
        + partitions.validation_holdout_purge_event_ids
    )
    with pytest.raises(TypeError):
        ValidationPhaseEligibility()
    with pytest.raises(EconomicPartitionBindingError):
        bind_validation_phase_eligibility(protocol=protocol, partitions=partitions.to_dict())
