"""TA-Control allocation contracts."""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import pytest

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


def _market_dates() -> tuple[str, ...]:
    day = dt.date(2026, 1, 5)
    dates: list[str] = []
    while len(dates) < 60:
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    return tuple(dates)


def _partitioned_protocol(tmp_path):
    market_dates = _market_dates()
    archive = RawPointInTimeArtifactArchive(tmp_path / "pit-artifacts")
    artifact = archive.admit(
        raw_bytes=json.dumps([{"date": day} for day in market_dates]).encode(),
        source_uri="https://paper-api.alpaca.markets/v2/calendar",
        content_type="application/json",
        retrieved_at="2026-12-31T21:00:00+00:00",
    )
    calendar = build_market_session_calendar(archive=archive, raw_artifact=artifact)
    events = tuple(
        _event(UNIVERSE[index % len(UNIVERSE)], market_date)
        for index, market_date in enumerate(market_dates)
    )
    partitions = build_market_date_partitions(
        market_calendar=calendar,
        events=events,
    )
    manifest = build_bitemporal_input_manifest(
        dataset_id="pit-fixture-v2",
        as_of_cutoff="2026-12-31T21:00:00+00:00",
        captured_at="2026-12-31T21:00:00+00:00",
        events=events,
    )
    protocol = build_frozen_evaluation_protocol(
        input_manifest=manifest,
        primary_universe=UNIVERSE,
        sensitivity_universe_50=UNIVERSE[:50],
        sensitivity_universe_100=tuple(f"T{index:03d}" for index in range(100)),
        evaluation_policy=StrategyEvaluationPolicy(
            benchmark_symbol="SPY",
            holding_sessions=5,
            commission_bps_per_side="0",
            half_spread_bps_per_side="5",
            slippage_bps_per_side="5",
            round_trip_sides=2,
        ),
        search_budget=EvaluationSearchBudget(5, 3, 25),
        development_event_ids=partitions.development_event_ids,
        validation_event_ids=partitions.validation_event_ids,
        holdout_event_ids=partitions.holdout_event_ids,
    )
    return protocol, partitions, {event.decision_event_id: event for event in events}


def _candidates(event):
    return tuple(
        EconomicTournamentCandidate(
            symbol=symbol,
            available_at=event.available_at,
            close_t_21="110" if symbol == "T000" else None,
            close_t_252="100" if symbol == "T000" else None,
            trailing_operating_income="10" if symbol == "T000" else None,
            average_total_assets="100" if symbol == "T000" else None,
        )
        for symbol in UNIVERSE
    )


def _outcome(event_id: str):
    return EconomicTournamentOutcome(
        decision_event_id=event_id,
        realized_returns=tuple(
            sorted([(symbol, "0.01") for symbol in UNIVERSE] + [("SPY", "0.02")])
        ),
    )


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


def test_validation_tournament_uses_only_purged_pit_validation_events(tmp_path):
    protocol, partitions, events_by_id = _partitioned_protocol(tmp_path)
    eligibility = bind_validation_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
    )
    result = evaluate_validation_ta_control(
        protocol=protocol,
        eligibility=eligibility,
        candidates_by_event={
            event_id: _candidates(events_by_id[event_id])
            for event_id in eligibility.event_ids
        },
        outcomes=tuple(_outcome(event_id) for event_id in eligibility.event_ids),
    )

    metrics = {row["arm_id"]: row["metrics"] for row in result.arm_metrics}
    assert result.protocol_id == protocol.protocol_id
    assert len(result.validation_event_ids) == len(eligibility.event_ids) == 2
    assert metrics["equal_weight"]["net_return_after_costs"] == "0.016064"
    assert metrics["spy"]["benchmark_excess_after_costs"] == "0"


def test_validation_eligibility_rebuilds_the_complete_pit_partition_receipt(tmp_path):
    protocol, partitions, _ = _partitioned_protocol(tmp_path)
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
        bind_validation_phase_eligibility(protocol=_protocol()[0], partitions=partitions)
