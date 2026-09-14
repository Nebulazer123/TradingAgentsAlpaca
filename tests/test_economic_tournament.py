"""TA-Control allocation contracts."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal

import pytest

from tests.fixtures.economic_tournament import build_tournament_receipt
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
from tradingagents.evals.economic_evaluation_result import (
    EconomicEvaluationResultError,
    validate_economic_validation_result,
)
from tradingagents.evals.economic_tournament import (
    EconomicTournamentCandidate,
    EconomicTournamentError,
    _post_return_holdings,
    _traded_notional,
    build_ta_control_allocations,
    evaluate_validation_ta_control,
)
from tradingagents.strategy.evaluator import StrategyEvaluationPolicy

UNIVERSE = tuple(f"T{index:03d}" for index in range(75))


def _event(
    symbol: str,
    market_date: str = "2026-01-09",
    universe: tuple[str, ...] = UNIVERSE,
):
    return build_decision_event(
        universe_id=canonical_universe_id(universe), symbol=symbol,
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


def test_validation_tournament_uses_only_purged_pit_validation_events(
    tmp_path, protocol_source
):
    protocol, partitions, events_by_id = _protocol(protocol_source)
    eligibility = bind_validation_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
    )
    receipt, _archive = build_tournament_receipt(
        tmp_path / "pit",
        protocol=protocol,
        eligibility=eligibility,
    )
    result = evaluate_validation_ta_control(
        protocol=protocol,
        eligibility=eligibility,
        candidates_by_event=dict(receipt.candidates_by_event),
        execution_outcomes=receipt.outcomes,
        tournament_input_id=receipt.input_id,
        tournament_input_sha256=receipt.input_sha256,
    )

    metrics = {row["arm_id"]: row["metrics"] for row in result.arm_metrics}
    assert result.protocol_id == protocol.protocol_id
    assert len(result.validation_event_ids) == len(eligibility.event_ids) == 75
    assert metrics["equal_weight"]["net_return_after_costs"] == "0.498"
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
    assert result.to_dict()["tournament_input"]["input_id"] == receipt.input_id
    assert len(result.to_dict()["execution_outcomes"]) == 76
    assert "effective_sample_size" not in json.dumps(result.to_dict())
    assert (
        validate_economic_validation_result(
            json.loads(result.canonical_json_bytes())
        ).canonical_json_bytes()
        == result.canonical_json_bytes()
    )


def test_validation_tournament_completes_unavailable_without_fabricated_metrics(
    tmp_path, protocol_source
):
    protocol, partitions, _events_by_id = _protocol(protocol_source)
    eligibility = bind_validation_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
    )
    market_date = next(
        event.market_date
        for event in protocol.input_manifest.events
        if event.decision_event_id in set(eligibility.event_ids)
    )
    receipt, _archive = build_tournament_receipt(
        tmp_path / "unavailable-pit",
        protocol=protocol,
        eligibility=eligibility,
        unavailable_next_open=frozenset({(market_date, "T001")}),
    )

    result = evaluate_validation_ta_control(
        protocol=protocol,
        eligibility=eligibility,
        candidates_by_event=dict(receipt.candidates_by_event),
        execution_outcomes=receipt.outcomes,
        tournament_input_id=receipt.input_id,
        tournament_input_sha256=receipt.input_sha256,
    )
    payload = result.to_dict()
    parsed = validate_economic_validation_result(json.loads(result.canonical_json_bytes()))

    assert payload["schema_version"] == "economic_validation_result/v3"
    assert payload["status"] == "completed"
    assert payload["availability_status"] == "unavailable"
    assert payload["qualification_status"] == (
        "nonqualifying_unavailable_execution_evidence"
    )
    assert payload["unavailable_outcomes"] == [
        {
            "market_date": market_date,
            "symbol": "T001",
            "decision_event_id": next(
                event.decision_event_id
                for event in protocol.input_manifest.events
                if event.market_date == market_date and event.symbol == "T001"
            ),
            "outcome_id": next(
                outcome.outcome_id
                for outcome in receipt.outcomes
                if outcome.decision_market_date == market_date
                and outcome.symbol == "T001"
            ),
            "outcome_sha256": next(
                outcome.outcome_sha256
                for outcome in receipt.outcomes
                if outcome.decision_market_date == market_date
                and outcome.symbol == "T001"
            ),
            "unavailable_reason": "required_next_open_unproven",
        }
    ]
    assert all(
        value is None
        for arm in payload["arm_metrics"]
        for value in arm["metrics"].values()
    )
    assert payload["registered_statistics"] is None
    assert parsed.canonical_json_bytes() == result.canonical_json_bytes()
    assert parsed.tournament_input_id == receipt.input_id
    assert len(parsed.execution_outcome_refs) == 76
    assert payload["analysis_only"] is True
    assert payload["execution_authority"] == "none"
    assert payload["can_submit_orders"] is False
    tampered = json.loads(result.canonical_json_bytes())
    tampered["arm_metrics"][0]["metrics"]["turnover"] = "0"
    with pytest.raises(EconomicEvaluationResultError):
        validate_economic_validation_result(tampered)


def test_non_anchor_retained_outcome_contributes_once_to_weekly_portfolio(
    tmp_path, protocol_source
):
    protocol, partitions, _events_by_id = _protocol(protocol_source)
    eligibility = bind_validation_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
    )
    market_date = next(
        event.market_date
        for event in protocol.input_manifest.events
        if event.decision_event_id in set(eligibility.event_ids)
    )
    baseline, _ = build_tournament_receipt(
        tmp_path / "baseline-pit",
        protocol=protocol,
        eligibility=eligibility,
    )
    changed, _ = build_tournament_receipt(
        tmp_path / "changed-pit",
        protocol=protocol,
        eligibility=eligibility,
        gross_return_overrides={(market_date, "T074"): "0.6"},
    )

    def evaluate(receipt):
        return evaluate_validation_ta_control(
            protocol=protocol,
            eligibility=eligibility,
            candidates_by_event=dict(receipt.candidates_by_event),
            execution_outcomes=receipt.outcomes,
            tournament_input_id=receipt.input_id,
            tournament_input_sha256=receipt.input_sha256,
        )

    baseline_result = evaluate(baseline)
    changed_result = evaluate(changed)
    baseline_metrics = {
        row["arm_id"]: row["metrics"] for row in baseline_result.arm_metrics
    }
    changed_metrics = {
        row["arm_id"]: row["metrics"] for row in changed_result.arm_metrics
    }

    assert (
        Decimal(changed_metrics["equal_weight"]["net_return_after_costs"])
        - Decimal(baseline_metrics["equal_weight"]["net_return_after_costs"])
        == Decimal("0.001333333333333333333333")
    )
    assert changed_metrics["equal_weight"]["decision_event_count"] == "75"
    assert all(
        changed_metrics[arm] == baseline_metrics[arm]
        for arm in ("cash", "spy", "momentum_quality", "pullback_support")
    )


def _two_date_validation_protocol(tmp_path, protocol_source):
    cohort, _old_partitions, _old_manifest = protocol_source
    primary = cohort.primary_universe_75
    decision_dates = tuple(
        (dt.date(2026, 4, 10) + dt.timedelta(weeks=index)).isoformat()
        for index in range(60)
    )
    events = tuple(
        _event(symbol, market_date, primary)
        for market_date in decision_dates
        for symbol in primary
    )
    calendar_dates = tuple(
        (
            dt.date.fromisoformat(decision_dates[0])
            + dt.timedelta(days=index)
        ).isoformat()
        for index in range(
            (dt.date.fromisoformat(decision_dates[-1]) - dt.date.fromisoformat(decision_dates[0])).days
            + 1
        )
        if (
            dt.date.fromisoformat(decision_dates[0]) + dt.timedelta(days=index)
        ).weekday()
        < 5
    )
    archive = RawPointInTimeArtifactArchive(
        tmp_path / "partition-calendar",
        clock=lambda: dt.datetime(2026, 4, 1, 12, 0, tzinfo=dt.UTC),
    )
    artifact = archive.admit(
        raw_bytes=json.dumps(
            [{"date": day, "open": "09:30", "close": "16:00"} for day in calendar_dates],
            separators=(",", ":"),
        ).encode(),
        source_uri="https://paper-api.alpaca.markets/v2/calendar",
        content_type="application/json",
        retrieved_at="2026-04-01T12:00:00+00:00",
    )
    calendar = build_market_session_calendar(archive=archive, raw_artifact=artifact)
    partitions = build_market_date_partitions(
        market_calendar=calendar,
        cadence="weekly",
        registered_at="2026-04-01T12:01:00+00:00",
        primary_universe=primary,
        decision_market_dates=decision_dates,
        events=events,
    )
    manifest = build_bitemporal_input_manifest(
        dataset_id="two-date-validation-fixture",
        as_of_cutoff="2027-06-01T21:00:00+00:00",
        captured_at="2027-06-01T21:00:00+00:00",
        events=events,
    )
    protocol = build_frozen_evaluation_protocol(
        cohort=cohort,
        market_date_partitions=partitions,
        input_manifest=manifest,
        primary_universe=primary,
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
    eligibility = bind_validation_phase_eligibility(
        protocol=protocol,
        partitions=partitions,
    )
    assert len(eligibility.event_ids) == 150
    return protocol, eligibility


def test_two_date_partial_overlap_uses_production_drift_and_all_cost_variants(
    tmp_path, protocol_source
):
    protocol, eligibility = _two_date_validation_protocol(tmp_path, protocol_source)
    validation_dates = tuple(
        sorted(
            {
                event.market_date
                for event in protocol.input_manifest.events
                if event.decision_event_id in set(eligibility.event_ids)
            }
        )
    )
    first_date, second_date = validation_dates
    first_selected = frozenset(f"T{index:03d}" for index in range(15))
    second_selected = frozenset(f"T{index:03d}" for index in range(1, 16))
    return_overrides = {
        (market_date, symbol): "0"
        for market_date in validation_dates
        for symbol in (*protocol.primary_universe, "SPY")
    }
    return_overrides[(first_date, "T000")] = "0.1"
    return_overrides.update(
        {(second_date, symbol): "0.2" for symbol in second_selected}
    )
    receipt, _archive = build_tournament_receipt(
        tmp_path / "two-date-pit",
        protocol=protocol,
        eligibility=eligibility,
        gross_return_overrides=return_overrides,
        momentum_symbols_by_date={
            first_date: first_selected,
            second_date: second_selected,
        },
    )

    result = evaluate_validation_ta_control(
        protocol=protocol,
        eligibility=eligibility,
        candidates_by_event=dict(receipt.candidates_by_event),
        execution_outcomes=receipt.outcomes,
        tournament_input_id=receipt.input_id,
        tournament_input_sha256=receipt.input_sha256,
    )
    variants = {
        row["cost_bps_per_side"]: {
            arm["arm_id"]: arm["metrics"] for arm in row["arm_metrics"]
        }
        for row in result.cost_variants
    }

    assert variants["10"]["momentum_quality"]["turnover"] == "2.14569536423841059602649"
    headline_diagnostics = {
        row["arm_id"]: row for row in result.registered_statistics["arm_diagnostics"]
    }
    assert headline_diagnostics["momentum_quality"]["buy_notional"] == (
        "1.072847682119205298013245"
    )
    assert headline_diagnostics["momentum_quality"]["sell_notional"] == (
        "1.072847682119205298013245"
    )
    for bps in ("5", "10", "25", "50"):
        c = Decimal(bps) / Decimal("10000")
        expected = (
            (Decimal("1") + Decimal(1) / Decimal(150) - c)
            * (
                Decimal("1.2")
                - (Decimal("1") + Decimal(22) / Decimal(151)) * c
            )
            - Decimal("1")
        )
        expected_text = format(expected.quantize(Decimal("1e-24")).normalize(), "f")
        assert (
            variants[bps]["momentum_quality"]["net_return_after_costs"]
            == expected_text
        )
        assert Decimal(
            variants[bps]["momentum_quality"]["benchmark_excess_after_costs"]
        ) == Decimal(expected_text) - Decimal(
            variants[bps]["spy"]["net_return_after_costs"]
        )


def test_two_date_drift_rotation_uses_full_buy_and_sell_notional():
    first_target = {
        "CASH": Decimal("0"),
        "T000": Decimal("0.5"),
        "T001": Decimal("0.5"),
    }
    initial_buys, initial_sells = _traded_notional(
        {"CASH": Decimal("1")}, first_target
    )
    drifted = _post_return_holdings(
        first_target,
        {"T000": Decimal("0.1"), "T001": Decimal("-0.1")},
    )
    second_target = {"CASH": Decimal("0"), "T001": Decimal("1")}
    rotation_buys, rotation_sells = _traded_notional(drifted, second_target)
    final_buys, final_sells = _traded_notional(
        _post_return_holdings(second_target, {"T001": Decimal("0.2")}),
        {"CASH": Decimal("1")},
    )

    assert (initial_buys, initial_sells) == (Decimal("1"), Decimal("0"))
    assert drifted["T000"] == Decimal("0.55")
    assert drifted["T001"] == Decimal("0.45")
    assert (rotation_buys, rotation_sells) == (Decimal("0.55"), Decimal("0.55"))
    assert (final_buys, final_sells) == (Decimal("0"), Decimal("1"))
    assert sum(
        (
            initial_buys,
            initial_sells,
            rotation_buys,
            rotation_sells,
            final_buys,
            final_sells,
        ),
        Decimal("0"),
    ) == Decimal("3.1")


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
