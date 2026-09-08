"""Contract tests for the evidence-first economic evaluation protocol."""

from __future__ import annotations

import ast
import builtins
import dataclasses
import datetime as dt
import hashlib
import importlib
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_point_in_time_cohort import (
    _build_from_fixture,
    _source_cohort_fixture,
)
from tradingagents.dataflows.pit import (
    RawPointInTimeArtifactArchive,
    build_market_date_partitions,
    build_market_session_calendar,
    build_source_bound_adjusted_price_window,
)
from tradingagents.evals import economic_evaluation_protocol as economic_protocol
from tradingagents.evals.agent_intelligence_ledger import (
    AgentForecast,
    resolve_forecasts_with_quality,
)
from tradingagents.evals.agent_intelligence_reconciliation import (
    build_reconciliation_receipt,
    market_event_key,
    packet_event_key,
)
from tradingagents.evals.economic_evaluation_protocol import (
    BitemporalInputManifest,
    DecisionEvent,
    EconomicEvaluationProtocolError,
    EvaluationSearchBudget,
    FrozenEvaluationProtocol,
    build_bitemporal_input_manifest,
    build_decision_event,
    build_frozen_evaluation_protocol,
    canonical_universe_id,
    validate_bitemporal_input_manifest,
    validate_decision_event,
    validate_frozen_evaluation_protocol,
)
from tradingagents.evals.learning_availability import LearningObservation
from tradingagents.evals.source_bound_resolution import build_source_bound_window_lookup
from tradingagents.strategy.evaluator import StrategyEvaluationPolicy

PRIMARY_UNIVERSE = tuple(f"T{i:03d}" for i in range(75))
UNIVERSE_ID = canonical_universe_id(PRIMARY_UNIVERSE)


def _canonical_text(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _event(**overrides: object):
    values: dict[str, object] = {
        "universe_id": canonical_universe_id(tuple(f"T{i:03d}" for i in range(75))),
        "symbol": "AAPL",
        "decision_at": "2026-01-09T20:55:00+00:00",
        "market_date": "2026-01-09",
        "horizon_sessions": 5,
        "horizon": "5_sessions",
        "benchmark": "SPY",
        "created_at": "2026-01-09T20:45:00+00:00",
        "resolution_window": {
            "start_at": "2026-01-09T20:55:00+00:00",
            "horizon": "5_sessions",
        },
        "observation_start": "2025-12-29T14:30:00+00:00",
        "observation_end": "2026-01-09T20:50:00+00:00",
        "available_at": "2026-01-09T20:50:00+00:00",
        "recorded_at": "2026-01-09T20:52:00+00:00",
        "source_packet_id": "packet-20260109-aapl",
        "source_artifact_id": "artifact-20260109-aapl",
        "source_artifact_sha256": hashlib.sha256(b"aapl-fixture").hexdigest(),
    }
    values.update(overrides)
    return build_decision_event(**values)


def test_decision_event_is_stable_and_arm_neutral():
    first = _event()
    second = validate_decision_event(dict(reversed(list(first.to_dict().items()))))
    assert second == first
    assert first.decision_event_id.startswith("decision-event-")
    assert "arm" not in first.to_dict()
    assert "outcome" not in first.to_dict()
    assert json.loads(first.canonical_json_bytes()) == first.to_dict()
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.symbol = "MSFT"  # type: ignore[misc]


def test_decision_event_validates_a_decoded_canonical_json_round_trip():
    event = _event()

    assert validate_decision_event(json.loads(event.canonical_json_bytes())) == event


def _mutation(name: str, mutate):
    def case():
        serialized = _event().to_dict()
        mutate(serialized)
        return serialized

    case.__name__ = f"mutate_{name}"
    return (name, case)


_EVENT_MUTATIONS = [
    _mutation("missing_field", lambda d: d.pop("source_packet_id")),
    _mutation("extra_field", lambda d: d.update({"forecast_return": 0.01})),
    _mutation(
        "uppercase_digest",
        lambda d: d.update({"source_artifact_sha256": d["source_artifact_sha256"].upper()}),
    ),
    _mutation("short_digest", lambda d: d.update({"source_artifact_sha256": "abc123"})),
    _mutation("naive_timestamp", lambda d: d.update({"decision_at": "2026-01-09T20:55:00"})),
    _mutation("z_suffix_timestamp", lambda d: d.update({"created_at": "2026-01-09T20:45:00Z"})),
    _mutation(
        "non_utc_offset",
        lambda d: d.update({"available_at": "2026-01-09T15:50:00+05:00"}),
    ),
    _mutation(
        "fractional_second",
        lambda d: d.update({"recorded_at": "2026-01-09T20:52:00.000000+00:00"}),
    ),
    _mutation("bool_horizon_sessions", lambda d: d.update({"horizon_sessions": True})),
    _mutation(
        "zero_horizon",
        lambda d: d.update({"horizon_sessions": 0, "horizon": "0_sessions"}),
    ),
    _mutation(
        "negative_horizon",
        lambda d: d.update({"horizon_sessions": -5, "horizon": "-5_sessions"}),
    ),
    _mutation("lowercase_symbol", lambda d: d.update({"symbol": "aapl"})),
    _mutation("empty_symbol", lambda d: d.update({"symbol": ""})),
    _mutation("invalid_symbol", lambda d: d.update({"symbol": "AAPL$"})),
    _mutation("lowercase_benchmark", lambda d: d.update({"benchmark": "spy"})),
    _mutation("empty_benchmark", lambda d: d.update({"benchmark": ""})),
    _mutation("market_date_mismatch", lambda d: d.update({"market_date": "2026-01-10"})),
    _mutation("bad_market_date_format", lambda d: d.update({"market_date": "20260109"})),
    _mutation(
        "observation_start_after_end",
        lambda d: d.update({"observation_start": "2026-01-09T20:50:30+00:00"}),
    ),
    _mutation(
        "observation_end_after_available",
        lambda d: d.update({"observation_end": "2026-01-09T20:50:01+00:00"}),
    ),
    _mutation(
        "available_after_decision",
        lambda d: d.update({"available_at": "2026-01-09T20:56:00+00:00"}),
    ),
    _mutation(
        "recorded_before_available",
        lambda d: d.update({"recorded_at": "2026-01-09T20:49:59+00:00"}),
    ),
    _mutation("created_after_decision", lambda d: d.update({"created_at": "2026-01-09T20:55:30+00:00"})),
    _mutation("horizon_token_mismatch", lambda d: d.update({"horizon": "4_sessions"})),
    _mutation(
        "tampered_decision_id",
        lambda d: d.update({"decision_event_id": "decision-event-" + "0" * 64}),
    ),
    _mutation(
        "tampered_packet_cluster",
        lambda d: d.update({"packet_event_cluster_id": "packet-event-cluster-" + "1" * 64}),
    ),
    _mutation(
        "tampered_market_cluster",
        lambda d: d.update({"market_event_cluster_id": "market-event-cluster-" + "2" * 64}),
    ),
    _mutation("tampered_universe_id", lambda d: d.update({"universe_id": "universe-" + "3" * 64})),
    _mutation(
        "obsolete_schema",
        lambda d: d.update({"schema_version": "decision_event/v0"}),
    ),
    _mutation("analysis_only_false", lambda d: d.update({"analysis_only": False})),
    _mutation(
        "execution_authority_granted",
        lambda d: d.update({"execution_authority": "submit"}),
    ),
    _mutation("can_submit_orders_true", lambda d: d.update({"can_submit_orders": True})),
]


@pytest.mark.parametrize("name,mutate", _EVENT_MUTATIONS, ids=[m[0] for m in _EVENT_MUTATIONS])
def test_decision_event_rejects_mutations(name, mutate):
    with pytest.raises(EconomicEvaluationProtocolError):
        validate_decision_event(mutate())


def test_universe_id_is_hand_derived_and_strict():
    symbols = ("AAPL", "MSFT")
    expected = "universe-" + hashlib.sha256(
        _canonical_text(list(symbols)).encode("utf-8")
    ).hexdigest()
    assert canonical_universe_id(symbols) == expected
    assert canonical_universe_id(tuple(reversed(symbols))) != expected
    assert "universe-" + hashlib.sha256(
        _canonical_text([f"T{i:03d}" for i in range(75)]).encode("utf-8")
    ).hexdigest() == UNIVERSE_ID
    for bad in (
        ["AAPL", "MSFT"],
        {"AAPL", "MSFT"},
        ("AAPL", "AAPL"),
        ("aapl",),
        (),
        ("AA PL",),
    ):
        with pytest.raises(EconomicEvaluationProtocolError):
            canonical_universe_id(bad)  # type: ignore[arg-type]


def test_decision_identity_matches_hand_derived_material():
    event = _event()
    material = {
        "schema_version": "decision_event/v1",
        "universe_id": UNIVERSE_ID,
        "symbol": "AAPL",
        "decision_at": "2026-01-09T20:55:00+00:00",
        "market_date": "2026-01-09",
        "horizon_sessions": 5,
        "benchmark": "SPY",
    }
    expected_id = "decision-event-" + hashlib.sha256(
        _canonical_text(material).encode("utf-8")
    ).hexdigest()
    assert event.decision_event_id == expected_id

    window = {"start_at": "2026-01-09T20:55:00+00:00", "horizon": "5_sessions"}
    packet_key = packet_event_key(
        {
            "source_packet_id": "packet-20260109-aapl",
            "ticker": "AAPL",
            "benchmark": "SPY",
            "resolution_window": window,
        }
    )
    market_key = market_event_key(
        {
            "ticker": "AAPL",
            "benchmark": "SPY",
            "horizon": "5_sessions",
            "created_at": "2026-01-09T20:45:00+00:00",
        }
    )
    assert packet_key is not None and market_key is not None
    assert event.packet_event_cluster_id == (
        "packet-event-cluster-"
        + hashlib.sha256(_canonical_text(list(packet_key)).encode("utf-8")).hexdigest()
    )
    assert event.market_event_cluster_id == (
        "market-event-cluster-"
        + hashlib.sha256(_canonical_text(list(market_key)).encode("utf-8")).hexdigest()
    )
    assert event.decision_event_id != event.packet_event_cluster_id
    assert event.packet_event_cluster_id != event.market_event_cluster_id


def test_source_packet_change_moves_packet_cluster_only():
    base = _event()
    changed = _event(source_packet_id="packet-20260109-aapl-v2")
    assert changed.packet_event_cluster_id != base.packet_event_cluster_id
    assert changed.decision_event_id == base.decision_event_id
    assert changed.market_event_cluster_id == base.market_event_cluster_id


def test_artifact_digest_change_changes_bytes_not_identities():
    base = _event()
    changed = _event(source_artifact_sha256=hashlib.sha256(b"aapl-fixture-v2").hexdigest())
    assert changed.canonical_json_bytes() != base.canonical_json_bytes()
    assert changed.decision_event_id == base.decision_event_id
    assert changed.packet_event_cluster_id == base.packet_event_cluster_id
    assert changed.market_event_cluster_id == base.market_event_cluster_id


@pytest.mark.parametrize(
    "overrides",
    [
        {"created_at": "2026-01-08T20:45:00+00:00", "market_date": "2026-01-08"},
        {"horizon_sessions": 10, "horizon": "10_sessions"},
        {"benchmark": "QQQ"},
    ],
)
def test_market_identity_and_decision_move_together(overrides):
    base = _event()
    changed = _event(**overrides)
    assert changed.market_event_cluster_id != base.market_event_cluster_id
    assert changed.decision_event_id != base.decision_event_id


def test_market_date_follows_created_at_not_decision_at():
    event = _event(
        created_at="2026-01-08T21:00:00+00:00",
        market_date="2026-01-08",
        decision_at="2026-01-09T14:30:00+00:00",
        observation_end="2026-01-08T21:45:00+00:00",
        available_at="2026-01-08T22:00:00+00:00",
        recorded_at="2026-01-08T22:30:00+00:00",
    )
    assert event.market_date == "2026-01-08"


def test_resolution_window_aliasing_is_frozen_recursively():
    inner = {"gate": ["a", "b"]}
    window = {
        "start_at": "2026-01-09T20:55:00+00:00",
        "notes": inner,
        "levels": [1, 2, {"deep": True}],
    }
    event = _event(resolution_window=window)
    captured_bytes = event.canonical_json_bytes()
    captured_cluster = event.packet_event_cluster_id
    captured_dict = event.to_dict()

    window["start_at"] = "tampered"
    window["added"] = "x"
    inner["gate"].append("c")
    inner["added"] = 1
    window["levels"][2]["deep"] = False
    window["levels"].append(99)

    assert event.canonical_json_bytes() == captured_bytes
    assert event.packet_event_cluster_id == captured_cluster
    assert event.to_dict() == captured_dict
    assert isinstance(event.resolution_window["notes"]["gate"], tuple)

    thawed = event.to_dict()
    thawed["resolution_window"]["start_at"] = "mutated"
    thawed["resolution_window"]["notes"]["gate"].append("z")
    thawed["resolution_window"]["levels"].append(7)
    thawed["symbol"] = "MSFT"
    thawed["horizon_sessions"] = 99
    assert event.canonical_json_bytes() == captured_bytes
    assert event.to_dict() == captured_dict


def _manifest_events():
    return (
        _event(
            symbol="T000",
            source_packet_id="packet-20260109-t000",
            source_artifact_id="artifact-20260109-t000",
            source_artifact_sha256=hashlib.sha256(b"t000-fixture").hexdigest(),
        ),
        _event(
            symbol="T001",
            source_packet_id="packet-20260109-t001",
            source_artifact_id="artifact-20260109-t001",
            source_artifact_sha256=hashlib.sha256(b"t001-fixture").hexdigest(),
        ),
        _event(
            symbol="T002",
            source_packet_id="packet-20260109-t002",
            source_artifact_id="artifact-20260109-t002",
            source_artifact_sha256=hashlib.sha256(b"t002-fixture").hexdigest(),
        ),
    )


def _manifest(*, events=None):
    return build_bitemporal_input_manifest(
        dataset_id="pit-fixture-v1",
        as_of_cutoff="2026-01-09T21:00:00+00:00",
        captured_at="2026-01-09T21:00:00+00:00",
        events=_manifest_events() if events is None else events,
    )


def test_manifest_binds_canonical_event_order_and_payload_bytes():
    events = _manifest_events()
    manifest = _manifest(events=(events[2], events[0], events[1]))

    assert isinstance(manifest, BitemporalInputManifest)
    assert manifest.events == tuple(sorted(events, key=lambda row: row.decision_event_id))
    assert manifest.manifest_id.startswith("input-manifest-")
    assert manifest.ordered_event_payload_sha256 == hashlib.sha256(
        _canonical_text([event.to_dict() for event in manifest.events]).encode("utf-8")
    ).hexdigest()
    assert validate_bitemporal_input_manifest(manifest.to_dict()) == manifest
    assert validate_bitemporal_input_manifest(
        dict(reversed(list(manifest.to_dict().items())))
    ) == manifest
    assert _manifest(events=tuple(reversed(events))).canonical_json_bytes() == (
        manifest.canonical_json_bytes()
    )


def test_manifest_validates_a_decoded_canonical_json_round_trip():
    manifest = _manifest()

    assert validate_bitemporal_input_manifest(
        json.loads(manifest.canonical_json_bytes())
    ) == manifest


@pytest.mark.parametrize(
    "name,make_value",
    [
        ("empty_events", lambda manifest: _manifest(events=())),
        (
            "duplicate_decision_event",
            lambda manifest: _manifest(events=(manifest.events[0], manifest.events[0])),
        ),
        (
            "cutoff_before_decision",
            lambda manifest: build_bitemporal_input_manifest(
                dataset_id="pit-fixture-v1",
                as_of_cutoff="2026-01-09T20:54:59+00:00",
                captured_at="2026-01-09T21:00:00+00:00",
                events=manifest.events,
            ),
        ),
        (
            "capture_before_recording",
            lambda manifest: build_bitemporal_input_manifest(
                dataset_id="pit-fixture-v1",
                as_of_cutoff="2026-01-09T21:00:00+00:00",
                captured_at="2026-01-09T20:51:59+00:00",
                events=manifest.events,
            ),
        ),
        (
            "inconsistent_artifact_reuse",
            lambda manifest: _manifest(
                events=(
                    manifest.events[0],
                    _event(
                        symbol="T003",
                        source_packet_id="packet-20260109-t003",
                        source_artifact_id=manifest.events[0].source_artifact_id,
                        source_artifact_sha256=hashlib.sha256(b"other-artifact").hexdigest(),
                    ),
                )
            ),
        ),
    ],
)
def test_manifest_builder_rejects_invalid_bitemporal_inputs(name, make_value):
    with pytest.raises(EconomicEvaluationProtocolError):
        make_value(_manifest())


def _manifest_mutation(name, mutate):
    def case():
        serialized = _manifest().to_dict()
        mutate(serialized)
        return serialized

    case.__name__ = f"manifest_mutate_{name}"
    return (name, case)


_MANIFEST_MUTATIONS = [
    _manifest_mutation("missing_field", lambda d: d.pop("dataset_id")),
    _manifest_mutation("extra_field", lambda d: d.update({"outcome": "positive"})),
    _manifest_mutation("obsolete_schema", lambda d: d.update({"schema_version": "bitemporal_input_manifest/v0"})),
    _manifest_mutation("analysis_only_false", lambda d: d.update({"analysis_only": False})),
    _manifest_mutation(
        "unsorted_events",
        lambda d: d.update({"events": list(reversed(d["events"]))}),
    ),
    _manifest_mutation(
        "changed_nested_event_body",
        lambda d: d["events"][0].update({"source_packet_id": "tampered-packet"}),
    ),
    _manifest_mutation(
        "changed_ordered_payload_digest",
        lambda d: d.update({"ordered_event_payload_sha256": "0" * 64}),
    ),
    _manifest_mutation(
        "changed_manifest_digest",
        lambda d: d.update({"manifest_sha256": "1" * 64}),
    ),
]


@pytest.mark.parametrize(
    "name,mutate", _MANIFEST_MUTATIONS, ids=[mutation[0] for mutation in _MANIFEST_MUTATIONS]
)
def test_manifest_validator_rejects_tampering(name, mutate):
    with pytest.raises(EconomicEvaluationProtocolError):
        validate_bitemporal_input_manifest(mutate())


PRIMARY_UNIVERSE_75 = tuple(f"T{i:03d}" for i in range(75))
SENSITIVITY_UNIVERSE_50 = PRIMARY_UNIVERSE_75[:50]
SENSITIVITY_UNIVERSE_100 = tuple(f"T{i:03d}" for i in range(100))
CONTROL_ARM_IDS = (
    "cash",
    "spy",
    "equal_weight",
    "momentum_quality",
    "pullback_support",
)
REQUIRED_METRICS = (
    "net_return_after_costs",
    "benchmark_excess_after_costs",
    "max_drawdown",
    "turnover",
    "false_positive_rate",
    "decision_event_count",
    "packet_event_cluster_count",
    "market_event_cluster_count",
    "cost_per_useful_decision",
)


@pytest.fixture(scope="module")
def protocol_source(tmp_path_factory):
    root = tmp_path_factory.mktemp("economic-protocol")
    ranked_primary = tuple(
        f"T{index:03d}"
        for index in (*range(74, -1, -2), *range(73, -1, -2))
    )
    ranked_symbols = (*ranked_primary, *(f"T{index:03d}" for index in range(75, 100)))
    symbol_overrides = {
        99 - position: symbol for position, symbol in enumerate(ranked_symbols)
    }
    archive, cohort_calendar, payload = _source_cohort_fixture(
        root / "cohort",
        symbol_overrides=symbol_overrides,
    )
    cohort = _build_from_fixture(archive, cohort_calendar, payload)
    primary = cohort.primary_universe_75

    monday = dt.date(2026, 4, 6)
    market_dates = tuple(
        (monday + dt.timedelta(weeks=week, days=weekday)).isoformat()
        for week in range(55)
        for weekday in range(5)
        if not (week in {7, 23, 41} and weekday == 4)
    )
    by_week: dict[tuple[int, int], list[str]] = {}
    for market_date in market_dates:
        parsed = dt.date.fromisoformat(market_date)
        iso = parsed.isocalendar()
        by_week.setdefault((iso.year, iso.week), []).append(market_date)
    decision_dates = tuple(rows[-1] for rows in by_week.values())
    calendar_archive = RawPointInTimeArtifactArchive(
        root / "calendar",
        clock=lambda: dt.datetime(2026, 4, 1, 12, 0, tzinfo=dt.UTC),
    )
    calendar_artifact = calendar_archive.admit(
        raw_bytes=json.dumps(
            [{"date": day, "open": "09:30", "close": "16:00"} for day in market_dates],
            separators=(",", ":"),
        ).encode(),
        source_uri="https://paper-api.alpaca.markets/v2/calendar",
        content_type="application/json",
        retrieved_at="2026-04-01T12:00:00+00:00",
    )
    calendar = build_market_session_calendar(
        archive=calendar_archive,
        raw_artifact=calendar_artifact,
    )
    events = tuple(
        _event(
            universe_id=canonical_universe_id(primary),
            symbol=symbol,
            decision_at=f"{market_date}T20:55:00+00:00",
            market_date=market_date,
            created_at=f"{market_date}T20:45:00+00:00",
            observation_start=f"{market_date}T19:00:00+00:00",
            observation_end=f"{market_date}T20:50:00+00:00",
            available_at=f"{market_date}T20:50:00+00:00",
            recorded_at=f"{market_date}T20:52:00+00:00",
            resolution_window={"start_at": f"{market_date}T20:55:00+00:00"},
            source_packet_id=f"packet-{market_date}-{symbol}",
            source_artifact_id=f"artifact-{market_date}-{symbol}",
            source_artifact_sha256=hashlib.sha256(
                f"{market_date}-{symbol}".encode()
            ).hexdigest(),
        )
        for market_date in decision_dates
        for symbol in primary
    )
    partitions = build_market_date_partitions(
        market_calendar=calendar,
        cadence="weekly",
        registered_at="2026-04-01T12:01:00+00:00",
        primary_universe=primary,
        decision_market_dates=decision_dates,
        events=events,
    )
    manifest = build_bitemporal_input_manifest(
        dataset_id="pit-ranked-weekly-fixture",
        as_of_cutoff="2027-05-01T21:00:00+00:00",
        captured_at="2027-05-01T21:00:00+00:00",
        events=events,
    )
    return cohort, partitions, manifest


def _policy(**overrides: object) -> StrategyEvaluationPolicy:
    values: dict[str, object] = {
        "benchmark_symbol": "SPY",
        "holding_sessions": 5,
        "commission_bps_per_side": "0",
        "half_spread_bps_per_side": "5",
        "slippage_bps_per_side": "5",
        "round_trip_sides": 2,
    }
    values.update(overrides)
    return StrategyEvaluationPolicy(**values)


def _budget(**overrides: object) -> EvaluationSearchBudget:
    values: dict[str, object] = {
        "max_candidates_per_arm": 5,
        "max_parameterizations_per_family": 3,
        "max_total_evaluations": 25,
    }
    values.update(overrides)
    return EvaluationSearchBudget(**values)


def _protocol(protocol_source, **overrides: object) -> FrozenEvaluationProtocol:
    cohort, partitions, manifest = protocol_source
    values: dict[str, object] = {
        "cohort": cohort,
        "market_date_partitions": partitions,
        "input_manifest": manifest,
        "primary_universe": cohort.primary_universe_75,
        "sensitivity_universe_50": cohort.sensitivity_universe_50,
        "sensitivity_universe_100": cohort.sensitivity_universe_100,
        "evaluation_policy": _policy(),
        "search_budget": _budget(),
        "development_event_ids": partitions.development_event_ids,
        "validation_event_ids": partitions.validation_event_ids,
        "holdout_event_ids": partitions.holdout_event_ids,
    }
    values.update(overrides)
    return build_frozen_evaluation_protocol(**values)


def test_protocol_freezes_ta_control_constants_and_sealed_partitions(protocol_source):
    protocol = _protocol(protocol_source)
    serialized = protocol.to_dict()

    assert protocol.protocol_id.startswith("economic-evaluation-protocol-")
    assert serialized["control_arm_ids"] == list(CONTROL_ARM_IDS)
    assert serialized["required_metrics"] == list(REQUIRED_METRICS)
    assert serialized["route_id"] == "ta-control/v1"
    assert serialized["cadence"] == "weekly"
    assert protocol.primary_universe == protocol.sensitivity_universe_100[:75]
    assert protocol.sensitivity_universe_50 == protocol.sensitivity_universe_100[:50]
    assert protocol.primary_universe != tuple(sorted(protocol.primary_universe))
    assert protocol.cohort_id == protocol.cohort.cohort_id
    assert protocol.partition_id == protocol.market_date_partitions.partition_id
    assert serialized["long_only"] is True
    assert serialized["cash_allowed"] is True
    assert serialized["max_leverage"] == "1"
    assert serialized["holdout_status"] == "sealed"
    assert serialized["dependence_method"] == "market_event_cluster_count_provisional_bound"
    assert "effective_sample_size" not in serialized
    assert all(
        forbidden not in serialized
        for forbidden in (
            "alpha_claim",
            "agent_id",
            "model_id",
            "vendor_id",
            "broker_id",
            "promotion_id",
            "order_id",
        )
    )
    assert validate_frozen_evaluation_protocol(protocol.to_dict()) == protocol
    assert validate_frozen_evaluation_protocol(
        dict(reversed(list(protocol.to_dict().items())))
    ) == protocol
    with pytest.raises(TypeError):
        protocol.evaluation_policy["benchmark_symbol"] = "QQQ"  # type: ignore[index]


def test_frozen_protocol_binding_survives_resolution_and_drives_verified_counts(
    protocol_source,
    tmp_path,
):
    protocol = _protocol(protocol_source)
    event = protocol.input_manifest.events[0]
    start = dt.date.fromisoformat(event.market_date)
    from tradingagents.evals.agent_intelligence_ledger import _add_trading_days

    end = _add_trading_days(
        dt.datetime.fromisoformat(event.created_at), event.horizon_sessions
    ).date()
    recorded = dt.datetime.combine(
        end + dt.timedelta(days=1),
        dt.time(21),
        tzinfo=dt.UTC,
    )
    archive = RawPointInTimeArtifactArchive(
        tmp_path / "learning-pit",
        clock=lambda: recorded,
    )
    artifacts = {}
    receipts = []
    for symbol, final_close in ((event.symbol, "12"), (event.benchmark, "11")):
        bars = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                bars.append(
                    {
                        "t": f"{current.isoformat()}T05:00:00Z",
                        "c": "10" if not bars else final_close,
                    }
                )
            current += dt.timedelta(days=1)
        artifact = archive.admit(
            raw_bytes=json.dumps({"bars": {symbol: bars}}).encode(),
            source_uri=(
                f"https://data.alpaca.markets/v2/stocks/{symbol}/bars?"
                "timeframe=1Day&feed=iex&adjustment=all"
                f"&start={start.isoformat()}T00:00:00Z"
                f"&end={(end + dt.timedelta(days=1)).isoformat()}T00:00:00Z"
            ),
            content_type="application/json",
            retrieved_at=recorded.isoformat(timespec="seconds"),
        )
        artifacts[artifact.raw_artifact_id] = artifact
        receipts.append(
            build_source_bound_adjusted_price_window(
                archive=archive,
                raw_artifact=artifact,
                security_id=f"security-{symbol.lower()}",
                symbol=symbol,
                requested_start=start.isoformat(),
                requested_end=end.isoformat(),
                decision_cutoff=recorded.isoformat(timespec="seconds"),
            )
        )
    forecast = AgentForecast(
        forecast_id="af-economic-binding",
        agent="market_analyst",
        ticker=event.symbol,
        claim="source-bound economic identity",
        forecast_type="market_report_direction",
        horizon=event.horizon,
        probability="0.60",
        expected_outcome="outperform",
        direction="bullish",
        benchmark=event.benchmark,
        created_at=event.created_at,
        resolve_after=f"{end.isoformat()}T20:45:00+00:00",
        source_packet_id=event.source_packet_id,
    )
    lookup = build_source_bound_window_lookup(
        archive=archive,
        raw_artifacts=artifacts,
        receipts=tuple(receipts),
        economic_protocol=protocol,
        forecast_event_bindings={forecast.forecast_id: event.decision_event_id},
    )

    resolved, reports = resolve_forecasts_with_quality(
        [forecast],
        window_lookup=lookup,
        now=recorded,
    )

    assert reports[0].status == "resolvable"
    assert resolved[0].resolution_evidence["schema_version"] == (
        "source_bound_resolution_evidence/v3"
    )
    assert lookup.verify_forecast(resolved[0]) is True
    observation = LearningObservation.from_source_bound_forecast(
        resolved[0],
        recorded_at=recorded,
        verifier=lookup,
    )
    assert observation.payload["resolution_evidence"]["economic_decision"] == {
        "protocol_id": protocol.protocol_id,
        "input_manifest_id": protocol.input_manifest_id,
        "input_manifest_sha256": protocol.input_manifest_sha256,
        "decision_event_id": event.decision_event_id,
        "decision_at": event.decision_at,
        "market_date": event.market_date,
        "source_packet_id": event.source_packet_id,
    }
    ledger_bytes = (json.dumps(resolved[0].as_dict(), sort_keys=True) + "\n").encode()
    receipt = build_reconciliation_receipt(
        ledger_bytes,
        source_bound_verifier=lookup,
    )
    assert receipt["unique_economic_decision_event_id_count"] == 1
    assert receipt["unique_economic_decision_market_date_count"] == 1
    assert receipt["economic_decision_verified_resolved_row_count"] == 1
    assert receipt["economic_decision_unbound_resolved_row_count"] == 0
    assert receipt["economic_decision_identity_status"] == "verified"

    unrelated_window = dataclasses.replace(
        resolved[0], resolve_after="2099-01-01T00:00:00+00:00"
    )
    assert lookup.verify_forecast(unrelated_window) is False
    unrelated_receipt = build_reconciliation_receipt(
        (json.dumps(unrelated_window.as_dict(), sort_keys=True) + "\n").encode(),
        source_bound_verifier=lookup,
    )
    assert unrelated_receipt["unique_economic_decision_event_id_count"] == 0
    assert unrelated_receipt["economic_decision_verified_resolved_row_count"] == 0
    assert unrelated_receipt["economic_decision_unbound_resolved_row_count"] == 1

    forged = resolved[0].as_dict()
    forged["resolution_evidence"]["economic_decision"]["market_date"] = "2026-01-01"
    forged_receipt = build_reconciliation_receipt(
        (json.dumps(forged, sort_keys=True) + "\n").encode(),
        source_bound_verifier=lookup,
    )
    assert forged_receipt["unique_economic_decision_event_id_count"] == 0
    assert forged_receipt["unique_economic_decision_market_date_count"] == 0
    assert forged_receipt["economic_decision_verified_resolved_row_count"] == 0
    assert forged_receipt["economic_decision_unbound_resolved_row_count"] == 1
    assert forged_receipt["economic_decision_identity_status"] == (
        "verified_with_unbound_rows"
    )

    legacy_v2 = resolved[0].as_dict()
    legacy_v2["forecast_id"] = "af-legacy-v2"
    legacy_v2["resolution_evidence"].pop("economic_decision")
    legacy_v2["resolution_evidence"]["schema_version"] = (
        "source_bound_resolution_evidence/v2"
    )
    mixed_receipt = build_reconciliation_receipt(
        (
            json.dumps(resolved[0].as_dict(), sort_keys=True)
            + "\n"
            + json.dumps(legacy_v2, sort_keys=True)
            + "\n"
        ).encode(),
        source_bound_verifier=lookup,
    )
    assert mixed_receipt["unique_economic_decision_event_id_count"] == 1
    assert mixed_receipt["unique_economic_decision_market_date_count"] == 1
    assert mixed_receipt["economic_decision_verified_resolved_row_count"] == 1
    assert mixed_receipt["economic_decision_unbound_resolved_row_count"] == 1
    assert mixed_receipt["economic_decision_identity_status"] == (
        "verified_with_unbound_rows"
    )


def test_public_frozen_dataclasses_cannot_bypass_their_builders_or_alias_state(
    protocol_source,
):
    event = _event()
    manifest = _manifest()
    protocol = _protocol(protocol_source)
    mutable_window = {"tampered": ["value"]}

    for value in (DecisionEvent, BitemporalInputManifest, FrozenEvaluationProtocol):
        with pytest.raises(TypeError):
            value()
    with pytest.raises(TypeError):
        dataclasses.replace(event, resolution_window=mutable_window)
    with pytest.raises(TypeError):
        dataclasses.replace(manifest, events=manifest.events)
    with pytest.raises(TypeError):
        dataclasses.replace(protocol, input_manifest=manifest)

    mutable_window["tampered"].append("changed")
    assert event.to_dict()["resolution_window"] != mutable_window


@pytest.mark.parametrize(
    "name,overrides",
    [
        ("primary_wrong_size", {"primary_universe": PRIMARY_UNIVERSE_75[:-1]}),
        (
            "primary_reordered",
            {"primary_universe": tuple(reversed(PRIMARY_UNIVERSE_75))},
        ),
        ("sensitivity_50_wrong_size", {"sensitivity_universe_50": SENSITIVITY_UNIVERSE_50[:-1]}),
        (
            "sensitivity_50_not_subset",
            {"sensitivity_universe_50": tuple(f"T{i:03d}" for i in range(50, 100))},
        ),
        ("sensitivity_100_wrong_size", {"sensitivity_universe_100": SENSITIVITY_UNIVERSE_100[:-1]}),
        (
            "sensitivity_100_not_superset",
            {"sensitivity_universe_100": tuple(f"T{i:03d}" for i in range(1, 101))},
        ),
        ("benchmark_mismatch", {"evaluation_policy": _policy(benchmark_symbol="QQQ")}),
        ("horizon_mismatch", {"evaluation_policy": _policy(holding_sessions=10)}),
        ("total_budget_too_small", {"search_budget": _budget(max_total_evaluations=24)}),
        ("empty_partition", {"holdout_event_ids": ()}),
        (
            "overlapping_partition",
            {"validation_event_ids": (_manifest().events[0].decision_event_id,)},
        ),
        (
            "unsorted_partition",
            {
                "development_event_ids": tuple(
                    reversed(
                        tuple(event.decision_event_id for event in _manifest().events[:2])
                    )
                ),
                "validation_event_ids": (_manifest().events[2].decision_event_id,),
                "holdout_event_ids": (_manifest().events[0].decision_event_id,),
            },
        ),
        (
            "unknown_partition_id",
            {"development_event_ids": ("decision-event-" + "0" * 64,)},
        ),
    ],
)
def test_protocol_builder_rejects_invalid_cohorts_policies_budgets_and_partitions(
    protocol_source,
    name,
    overrides,
):
    with pytest.raises(EconomicEvaluationProtocolError):
        _protocol(protocol_source, **overrides)


@pytest.mark.parametrize("invalid", [0, -1, True])
def test_search_budget_rejects_nonpositive_and_boolean_values(invalid):
    with pytest.raises(EconomicEvaluationProtocolError):
        _budget(max_candidates_per_arm=invalid)


def test_protocol_rejects_event_from_another_primary_universe(protocol_source):
    _cohort, _partitions, manifest = protocol_source
    base = manifest.events[0]
    foreign_event = _event(
        universe_id=canonical_universe_id(tuple(f"X{i:03d}" for i in range(75))),
        symbol=base.symbol,
        decision_at=base.decision_at,
        market_date=base.market_date,
        created_at=base.created_at,
        resolution_window=base.to_dict()["resolution_window"],
        observation_start=base.observation_start,
        observation_end=base.observation_end,
        available_at=base.available_at,
        recorded_at=base.recorded_at,
        source_packet_id="packet-ranked-foreign",
        source_artifact_id="artifact-ranked-foreign",
        source_artifact_sha256=hashlib.sha256(b"foreign-fixture").hexdigest(),
    )
    foreign_manifest = build_bitemporal_input_manifest(
        dataset_id=manifest.dataset_id,
        as_of_cutoff=manifest.as_of_cutoff,
        captured_at=manifest.captured_at,
        events=(foreign_event, *manifest.events[1:]),
    )
    with pytest.raises(EconomicEvaluationProtocolError):
        _protocol(protocol_source, input_manifest=foreign_manifest)


def _protocol_mutation(name, mutate):
    def case(protocol_source):
        serialized = _protocol(protocol_source).to_dict()
        mutate(serialized)
        return serialized

    case.__name__ = f"protocol_mutate_{name}"
    return (name, case)


_PROTOCOL_MUTATIONS = [
    _protocol_mutation("missing_field", lambda d: d.pop("route_id")),
    _protocol_mutation("extra_field", lambda d: d.update({"alpha_claim": "winning"})),
    _protocol_mutation("obsolete_schema", lambda d: d.update({"schema_version": "frozen_economic_evaluation_protocol/v0"})),
    _protocol_mutation("control_arm_removed", lambda d: d.update({"control_arm_ids": d["control_arm_ids"][:-1]})),
    _protocol_mutation("control_arm_reordered", lambda d: d.update({"control_arm_ids": list(reversed(d["control_arm_ids"]))})),
    _protocol_mutation("holdout_unsealed", lambda d: d.update({"holdout_status": "released"})),
    _protocol_mutation("manifest_digest_changed", lambda d: d.update({"input_manifest_sha256": "0" * 64})),
    _protocol_mutation("cohort_digest_changed", lambda d: d.update({"cohort_sha256": "4" * 64})),
    _protocol_mutation("partition_digest_changed", lambda d: d.update({"partition_sha256": "5" * 64})),
    _protocol_mutation(
        "nested_partition_changed",
        lambda d: d["market_date_partitions"].update(
            {"registered_at": "2026-04-01T12:02:00+00:00"}
        ),
    ),
    _protocol_mutation("policy_digest_changed", lambda d: d.update({"evaluation_policy_sha256": "1" * 64})),
    _protocol_mutation("universe_digest_changed", lambda d: d.update({"primary_universe_sha256": "2" * 64})),
    _protocol_mutation("protocol_id_changed", lambda d: d.update({"protocol_id": "economic-evaluation-protocol-" + "3" * 64})),
]


@pytest.mark.parametrize(
    "name,mutate", _PROTOCOL_MUTATIONS, ids=[mutation[0] for mutation in _PROTOCOL_MUTATIONS]
)
def test_protocol_validator_rejects_tampering(protocol_source, name, mutate):
    with pytest.raises(EconomicEvaluationProtocolError):
        validate_frozen_evaluation_protocol(mutate(protocol_source))


FORBIDDEN_IMPORT_PREFIXES = (
    "cli",
    "tradingagents.brokers",
    "tradingagents.execution",
    "tradingagents.orchestration",
    "tradingagents.policy.live_control",
    "tradingagents.policy.promotion",
    "tradingagents.policy.promotion_execution",
    "tradingagents.strategy.mutation_registry",
    "tradingagents.strategy.promotion_evidence",
)


def test_protocol_imports_and_construction_have_no_authority_side_effects(
    protocol_source,
    monkeypatch,
):
    module_path = Path(economic_protocol.__file__)
    syntax = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    imported_paths = []
    for node in ast.walk(syntax):
        if isinstance(node, ast.Import):
            imported_paths.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_paths.append(node.module)
    assert all(
        not imported.startswith(FORBIDDEN_IMPORT_PREFIXES) for imported in imported_paths
    )

    def side_effect(*args, **kwargs):
        raise AssertionError("protocol construction attempted a forbidden side effect")

    monkeypatch.setattr(socket, "socket", side_effect)
    monkeypatch.setattr(subprocess, "run", side_effect)
    monkeypatch.setattr(subprocess, "Popen", side_effect)
    monkeypatch.setattr(Path, "write_bytes", side_effect)
    monkeypatch.setattr(Path, "write_text", side_effect)
    monkeypatch.setattr(builtins, "open", side_effect)

    monkeypatch.delitem(sys.modules, economic_protocol.__name__)
    fresh_module = importlib.import_module(economic_protocol.__name__)
    assert fresh_module is not economic_protocol

    event = _event()
    manifest = _manifest()
    protocol = _protocol(protocol_source)
    assert validate_decision_event(event.to_dict()) == event
    assert validate_bitemporal_input_manifest(manifest.to_dict()) == manifest
    assert validate_frozen_evaluation_protocol(protocol.to_dict()) == protocol
