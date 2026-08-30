"""Contract tests for immutable point-in-time evaluation records."""

from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from tradingagents.dataflows.pit import (
    CorporateAction,
    PointInTimeDataError,
    PointInTimeObservation,
    SecurityIdentity,
    validate_corporate_action,
    validate_point_in_time_observation,
    validate_security_identity,
)


def _security(**overrides: object) -> SecurityIdentity:
    values: dict[str, object] = {
        "security_id": "security-us-aapl-common-0001",
        "symbol": "AAPL",
        "cik": "0000320193",
        "figi": "BBG000B9XRY4",
        "exchange": "NASDAQ",
        "security_type": "common_stock",
        "effective_from": "1980-12-12",
        "effective_to": None,
        "status": "active",
        "successor_security_id": None,
        "terminal_proceeds_artifact_id": None,
        "source_hashes": {
            "security_master": hashlib.sha256(b"aapl-security-master").hexdigest(),
        },
    }
    values.update(overrides)
    return SecurityIdentity(**values)


def _observation(**overrides: object) -> PointInTimeObservation:
    raw_digest = hashlib.sha256(b"aapl-bar").hexdigest()
    calendar_digest = hashlib.sha256(b"xnys-calendar").hexdigest()
    calendar_raw_digest = hashlib.sha256(b"xnys-calendar-raw").hexdigest()
    values: dict[str, object] = {
        "security_id": "security-us-aapl-common-0001",
        "identity_effective_from": "1980-12-12",
        "identity_effective_to": None,
        "event_time": "2026-01-09T20:00:00+00:00",
        "publication_time": "2026-01-09T20:05:00+00:00",
        "availability_time": "2026-01-09T20:12:00+00:00",
        "retrieval_time": "2026-01-09T20:13:00+00:00",
        "raw_artifact_id": "raw-aapl-bar-20260109",
        "raw_artifact_sha256": raw_digest,
        "observed_value": "188.42",
        "market_data_feed": "sip",
        "adjustment_mode": "raw",
        "market_session": "regular",
        "session_date": "2026-01-09",
        "adjustment_status": "unadjusted",
        "source_span": {
            "source_kind": "alpaca_market_data",
            "span_type": "json_paths",
            "source_sha256": raw_digest,
            "market_calendar_id": "market-session-calendar-xnys-2026",
            "market_calendar_sha256": calendar_digest,
            "timeframe": "5Min",
            "publication_derivation": {
                "method": "bar_start_plus_timeframe",
                "completion_time": "2026-01-09T20:05:00+00:00",
                "market_timezone": "America/New_York",
                "regular_session_open": "09:30:00",
                "regular_session_close": "16:00:00",
                "bar_duration_seconds": 300,
                "calendar_raw_artifact_id": "pit-raw-artifact-" + "a" * 64,
                "calendar_raw_artifact_sha256": calendar_raw_digest,
                "calendar_date_path": [0, "date"],
                "calendar_open_path": [0, "open"],
                "calendar_close_path": [0, "close"],
            },
            "paths": {
                "event_time": ["bars", "AAPL", 0, "t"],
                "observed_value": ["bars", "AAPL", 0, "c"],
            },
        },
    }
    values.update(overrides)
    return PointInTimeObservation(**values)


def _sec_observation() -> PointInTimeObservation:
    raw_digest = hashlib.sha256(b"sec-fact").hexdigest()
    return _observation(
        raw_artifact_sha256=raw_digest,
        market_data_feed=None,
        adjustment_mode=None,
        market_session=None,
        session_date=None,
        source_span={
            "source_kind": "sec_json_xbrl",
            "span_type": "json_paths",
            "source_sha256": raw_digest,
            "paths": {
                "source_identity": ["cik"],
                "observed_value": ["facts", "value"],
                "event_time": ["facts", "event_time"],
                "publication_time": ["facts", "publication_time"],
            },
        },
    )


def _action(**overrides: object) -> CorporateAction:
    values: dict[str, object] = {
        "security_id": "security-us-aapl-common-0001",
        "action_type": "split",
        "effective_date": "2020-08-31",
        "terms": {"numerator": 4, "denominator": 1},
        "source_artifact_id": "raw-aapl-split-20200831",
        "source_artifact_sha256": hashlib.sha256(b"aapl-split").hexdigest(),
    }
    values.update(overrides)
    return CorporateAction(**values)


def test_security_identity_is_immutable_canonical_and_round_trips():
    identity = _security()

    assert identity.schema_version == "security_identity/v1"
    assert identity.analysis_only is True
    assert identity.execution_authority == "none"
    assert identity.can_submit_orders is False
    assert validate_security_identity(
        json.loads(identity.canonical_json_bytes())
    ) == identity
    with pytest.raises(dataclasses.FrozenInstanceError):
        identity.symbol = "MSFT"  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"security_id": ""},
        {"symbol": "aapl"},
        {"cik": "320193"},
        {"figi": "bad figi"},
        {"security_type": "etf"},
        {"effective_to": "1980-12-11"},
        {"status": "delisted"},
        {"status": "active", "successor_security_id": "security-us-new"},
        {"source_hashes": {"security_master": "not-a-digest"}},
    ],
)
def test_security_identity_rejects_noncanonical_or_inconsistent_values(overrides):
    with pytest.raises(PointInTimeDataError):
        _security(**overrides)


def test_security_identity_deep_freezes_source_hashes():
    source_hashes = {"security_master": hashlib.sha256(b"source").hexdigest()}
    identity = _security(source_hashes=source_hashes)
    expected = identity.canonical_json_bytes()

    source_hashes["security_master"] = hashlib.sha256(b"tampered").hexdigest()
    source_hashes["new"] = hashlib.sha256(b"new").hexdigest()

    assert identity.canonical_json_bytes() == expected
    thawed = identity.to_dict()
    thawed["source_hashes"]["security_master"] = hashlib.sha256(b"changed").hexdigest()
    assert identity.canonical_json_bytes() == expected


def test_observation_binds_all_bitemporal_times_and_raw_provenance():
    observation = _observation()

    assert observation.schema_version == "point_in_time_observation/v2"
    assert validate_point_in_time_observation(
        json.loads(observation.canonical_json_bytes())
    ) == observation
    assert observation.to_dict()["source_span"] == {
        "source_kind": "alpaca_market_data",
        "span_type": "json_paths",
        "source_sha256": hashlib.sha256(b"aapl-bar").hexdigest(),
        "market_calendar_id": "market-session-calendar-xnys-2026",
        "market_calendar_sha256": hashlib.sha256(b"xnys-calendar").hexdigest(),
        "timeframe": "5Min",
        "publication_derivation": {
            "method": "bar_start_plus_timeframe",
            "completion_time": "2026-01-09T20:05:00+00:00",
            "market_timezone": "America/New_York",
            "regular_session_open": "09:30:00",
            "regular_session_close": "16:00:00",
            "bar_duration_seconds": 300,
            "calendar_raw_artifact_id": "pit-raw-artifact-" + "a" * 64,
            "calendar_raw_artifact_sha256": hashlib.sha256(
                b"xnys-calendar-raw"
            ).hexdigest(),
            "calendar_date_path": [0, "date"],
            "calendar_open_path": [0, "open"],
            "calendar_close_path": [0, "close"],
        },
        "paths": {
            "event_time": ["bars", "AAPL", 0, "t"],
            "observed_value": ["bars", "AAPL", 0, "c"],
        },
    }
    assert observation.observed_value == "188.42"
    assert observation.identity_effective_from == "1980-12-12"
    assert observation.market_session == "regular"


@pytest.mark.parametrize(
    "overrides",
    [
        {"event_time": "2026-01-09T20:00:00Z"},
        {"publication_time": "2026-01-09T19:59:59+00:00"},
        {"availability_time": "2026-01-09T20:04:59+00:00"},
        {"retrieval_time": "2026-01-09T20:11:59+00:00"},
        {"identity_effective_from": "2026-01-10"},
        {"identity_effective_to": "1980-12-11"},
        {"raw_artifact_id": ""},
        {"raw_artifact_sha256": "ABC"},
        {"market_data_feed": "unknown"},
        {"adjustment_mode": "split"},
        {"market_session": "extended"},
        {"session_date": "2026-01-10"},
        {"adjustment_status": "adjusted"},
        {"source_span": []},
        {
            "source_span": {
                "source_kind": "alpaca_market_data",
                "span_type": "json_paths",
                "source_sha256": hashlib.sha256(b"different").hexdigest(),
                "paths": {"observed_value": ["bars", "AAPL", 0, "c"]},
            }
        },
    ],
)
def test_observation_rejects_future_leakage_and_invalid_provenance(overrides):
    with pytest.raises(PointInTimeDataError):
        _observation(**overrides)


def test_observation_deep_freezes_source_span():
    calendar_digest = hashlib.sha256(b"xnys-calendar").hexdigest()
    calendar_raw_digest = hashlib.sha256(b"xnys-calendar-raw").hexdigest()
    span = {
        "source_kind": "alpaca_market_data",
        "span_type": "json_paths",
        "source_sha256": hashlib.sha256(b"aapl-bar").hexdigest(),
        "market_calendar_id": "market-session-calendar-xnys-2026",
        "market_calendar_sha256": calendar_digest,
        "timeframe": "5Min",
        "publication_derivation": {
            "method": "bar_start_plus_timeframe",
            "completion_time": "2026-01-09T20:05:00+00:00",
            "market_timezone": "America/New_York",
            "regular_session_open": "09:30:00",
            "regular_session_close": "16:00:00",
            "bar_duration_seconds": 300,
            "calendar_raw_artifact_id": "pit-raw-artifact-" + "a" * 64,
            "calendar_raw_artifact_sha256": calendar_raw_digest,
            "calendar_date_path": [0, "date"],
            "calendar_open_path": [0, "open"],
            "calendar_close_path": [0, "close"],
        },
        "paths": {
            "event_time": ["bars", "AAPL", 0, "t"],
            "observed_value": ["bars", "AAPL", 0, "c"],
        },
    }
    observation = _observation(source_span=span)
    expected = observation.canonical_json_bytes()

    span["paths"]["observed_value"][-1] = "o"
    span["paths"]["event_time"].append("tampered")
    span["publication_derivation"]["completion_time"] = "2026-01-09T20:04:00+00:00"
    span["publication_derivation"]["calendar_close_path"][1] = "open"

    assert observation.canonical_json_bytes() == expected


@pytest.mark.parametrize(
    ("source_kind", "paths"),
    [
        (
            "sec_json_xbrl",
            {
                "source_identity": ["cik"],
                "observed_value": ["facts", "value"],
                "event_time": ["facts", "event_time"],
            },
        ),
        (
            "sec_json_xbrl",
            {
                "source_identity": ["cik"],
                "observed_value": ["facts", "value"],
                "event_time": ["facts", "event_time"],
                "publication_time": ["facts", "publication_time"],
                "summary": ["summary"],
            },
        ),
        (
            "alpaca_market_data",
            {"observed_value": ["bars", "AAPL", 0, "c"]},
        ),
        (
            "alpaca_market_data",
            {
                "observed_value": ["bars", "AAPL", 0, "c"],
                "event_time": ["bars", "AAPL", 0, "t"],
                "summary": ["summary"],
            },
        ),
    ],
)
def test_observation_rejects_missing_or_extra_source_path_roles(
    source_kind,
    paths,
):
    observation = _sec_observation() if source_kind == "sec_json_xbrl" else _observation()
    payload = observation.to_dict()
    payload["source_span"]["paths"] = paths

    with pytest.raises(PointInTimeDataError):
        validate_point_in_time_observation(payload)


@pytest.mark.parametrize("field", ["market_calendar_id", "timeframe", "publication_derivation"])
def test_observation_rejects_missing_alpaca_derivation_material(field):
    payload = _observation().to_dict()
    del payload["source_span"][field]

    with pytest.raises(PointInTimeDataError):
        validate_point_in_time_observation(payload)


def test_observation_deep_freezes_selected_source_value():
    observed_value = {"amount": "188.42", "dimensions": ["USD", {"period": "FY"}]}
    observation = _observation(observed_value=observed_value)
    expected = observation.canonical_json_bytes()

    observed_value["amount"] = "0"
    observed_value["dimensions"][1]["period"] = "Q1"

    assert observation.canonical_json_bytes() == expected


def test_corporate_action_binds_source_and_terms_without_aliasing():
    terms = {"numerator": 4, "denominator": 1, "notes": ["official"]}
    action = _action(terms=terms)
    expected = action.canonical_json_bytes()

    assert action.schema_version == "corporate_action/v1"
    assert validate_corporate_action(json.loads(action.canonical_json_bytes())) == action
    terms["notes"].append("tampered")
    terms["numerator"] = 100
    assert action.canonical_json_bytes() == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"action_type": "unknown"},
        {"effective_date": "20200831"},
        {"terms": []},
        {"source_artifact_id": ""},
        {"source_artifact_sha256": "0" * 63},
    ],
)
def test_corporate_action_rejects_invalid_terms_and_provenance(overrides):
    with pytest.raises(PointInTimeDataError):
        _action(**overrides)
