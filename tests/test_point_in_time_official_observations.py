"""PIT observations must derive material facts from archived source bytes."""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import pytest

from tradingagents.dataflows.pit import (
    PointInTimeDataError,
    RawPointInTimeArtifactArchive,
    SecurityIdentity,
    build_alpaca_market_observation,
    build_market_session_calendar,
    build_sec_fundamental_observation,
)


def _security(**overrides: object) -> SecurityIdentity:
    values: dict[str, object] = {
        "security_id": "security-us-aapl-common-0001",
        "symbol": "AAPL",
        "cik": "0000000001",
        "figi": "BBG000B9XRY4",
        "exchange": "NASDAQ",
        "security_type": "common_stock",
        "effective_from": "2020-01-01",
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


def _archive(
    tmp_path,
    *,
    uri: str,
    payload: object | None = None,
    raw_bytes: bytes | None = None,
    retrieved_at: str = "2026-01-05T21:00:00+00:00",
    archive_recorded_at: str = "2026-01-05T21:00:05+00:00",
):
    archive = RawPointInTimeArtifactArchive(
        tmp_path / "pit-artifacts",
        clock=lambda: dt.datetime.fromisoformat(archive_recorded_at),
    )
    assert (payload is None) != (raw_bytes is None)
    artifact = archive.admit(
        raw_bytes=(
            json.dumps(payload, separators=(",", ":")).encode()
            if raw_bytes is None
            else raw_bytes
        ),
        source_uri=uri,
        content_type="application/json",
        retrieved_at=retrieved_at,
    )
    return archive, artifact


def _calendar(
    archive,
    *market_dates: str,
    open_time: str = "09:30",
    close_time: str = "16:00",
):
    artifact = archive.admit(
        raw_bytes=json.dumps(
            [
                {
                    "date": market_date,
                    "open": open_time,
                    "close": close_time,
                }
                for market_date in market_dates
            ],
            separators=(",", ":"),
        ).encode(),
        source_uri="https://paper-api.alpaca.markets/v2/calendar",
        content_type="application/json",
        retrieved_at="2020-01-01T00:00:00+00:00",
    )
    return build_market_session_calendar(archive=archive, raw_artifact=artifact)


def test_sec_observation_derives_value_times_and_exact_json_paths_from_bytes(tmp_path):
    archive, artifact = _archive(
        tmp_path,
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        payload={
            "cik": "0000000001",
            "summary": {"value": "wrapper-is-not-truth"},
            "facts": {
                "us-gaap": {
                    "OperatingIncomeLoss": {
                        "units": {
                            "USD": [
                                {
                                    "event_time": "2026-01-04T21:00:00+00:00",
                                    "publication_time": "2026-01-05T20:00:00+00:00",
                                    "val": 42.5,
                                }
                            ]
                        }
                    }
                }
            },
        },
    )
    observation = build_sec_fundamental_observation(
        security_identity=_security(),
        archive=archive,
        raw_artifact=artifact,
        source_identity_path=("cik",),
        value_path=(
            "facts",
            "us-gaap",
            "OperatingIncomeLoss",
            "units",
            "USD",
            0,
            "val",
        ),
        event_time_path=(
            "facts",
            "us-gaap",
            "OperatingIncomeLoss",
            "units",
            "USD",
            0,
            "event_time",
        ),
        publication_time_path=(
            "facts",
            "us-gaap",
            "OperatingIncomeLoss",
            "units",
            "USD",
            0,
            "publication_time",
        ),
    )

    assert observation.observed_value == "42.5"
    assert observation.event_time == "2026-01-04T21:00:00+00:00"
    assert observation.publication_time == "2026-01-05T20:00:00+00:00"
    assert observation.availability_time == artifact.retrieved_at
    assert observation.retrieval_time == artifact.archive_recorded_at
    assert observation.identity_effective_from == "2020-01-01"
    assert observation.source_span["span_type"] == "json_paths"
    assert observation.source_span["paths"]["observed_value"][-1] == "val"


def test_alpaca_observation_binds_exact_bar_identity_feed_adjustment_and_session(
    tmp_path,
):
    archive, artifact = _archive(
        tmp_path,
        uri=(
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&"
            "timeframe=1Day&feed=iex&adjustment=split"
        ),
        payload={"bars": {"AAPL": [{"t": "2026-01-05T05:00:00Z", "c": 102.25}]}},
    )
    calendar = _calendar(archive, "2026-01-05")
    observation = build_alpaca_market_observation(
        security_identity=_security(),
        archive=archive,
        raw_artifact=artifact,
        market_calendar=calendar,
        bar_path=("bars", "AAPL", 0),
        value_field="c",
    )

    assert observation.observed_value == "102.25"
    assert observation.event_time == "2026-01-05T05:00:00+00:00"
    assert observation.publication_time == "2026-01-05T21:00:00+00:00"
    assert observation.adjustment_status == "split_adjusted"
    assert observation.market_data_feed == "iex"
    assert observation.adjustment_mode == "split"
    assert observation.market_session == "regular"
    assert observation.session_date == "2026-01-05"
    assert observation.source_span["market_calendar_id"] == calendar.calendar_id
    assert observation.source_span["market_calendar_sha256"] == calendar.calendar_sha256
    assert observation.source_span["timeframe"] == "1Day"
    assert observation.source_span["publication_derivation"]["method"] == (
        "registered_regular_session_close"
    )
    assert observation.source_span["paths"]["observed_value"] == (
        "bars",
        "AAPL",
        0,
        "c",
    )


@pytest.mark.parametrize("single_symbol", [True, False], ids=["single", "multi"])
def test_alpaca_observation_accepts_documented_endpoint_response_pair(
    tmp_path, single_symbol,
):
    # Synthetic values in the documented wire shapes, not a captured account receipt.
    bar = {"t": "2026-01-05T05:00:00Z", "o": 101, "h": 103, "l": 100,
           "c": 102.25, "v": 1000, "n": 100, "vw": 102}
    if single_symbol:
        route = "AAPL/bars?"
        payload = {"bars": [bar], "symbol": "AAPL", "next_page_token": None}
        bar_path = ("bars", 0)
    else:
        route = "bars?symbols=MSFT%2CAAPL&"
        payload = {"bars": {"MSFT": [{**bar, "c": 999}], "AAPL": [bar]},
                   "next_page_token": None}
        bar_path = ("bars", "AAPL", 0)
    archive, artifact = _archive(
        tmp_path,
        uri=f"https://data.alpaca.markets/v2/stocks/{route}timeframe=1Day&feed=sip&adjustment=raw",
        payload=payload,
    )
    observation = build_alpaca_market_observation(
        security_identity=_security(), archive=archive, raw_artifact=artifact,
        market_calendar=_calendar(archive, "2026-01-05"),
        bar_path=bar_path, value_field="c",
    )
    assert observation.observed_value == "102.25"
    assert observation.source_span["paths"]["observed_value"] == (*bar_path, "c")
    assert observation.source_span["paths"]["event_time"] == (*bar_path, "t")
    assert observation.raw_artifact_sha256 == artifact.raw_artifact_sha256
    assert observation.availability_time == artifact.retrieved_at
    assert observation.retrieval_time == artifact.archive_recorded_at


@pytest.mark.parametrize(
    ("route", "shape", "response_symbol", "bar_path"),
    [
        ("AAPL/bars?", "single", "MSFT", ("bars", 0)),
        ("AAPL/bars?", "single", None, ("bars", 0)),
        ("AAPL/bars?", "multi", "AAPL", ("bars", "AAPL", 0)),
        ("AAPL/bars?", "multi", "AAPL", ("bars", 0)),
        ("bars?symbols=AAPL&", "single", "AAPL", ("bars", "AAPL", 0)),
        ("bars?symbols=MSFT&", "multi", None, ("bars", "AAPL", 0)),
        ("bars?symbols=AAPL,AAPL&", "multi", None, ("bars", "AAPL", 0)),
        ("bars?symbols=AAPL&symbols=MSFT&", "multi", None, ("bars", "AAPL", 0)),
        ("bars?", "multi", None, ("bars", "AAPL", 0)),
        ("bars?symbols=AAPL,&", "multi", None, ("bars", "AAPL", 0)),
        ("bars?symbols=AAPL,MSFT&", "multi", None, ("bars", "MSFT", 0)),
        ("AAPL/bars/extra?", "single", "AAPL", ("bars", 0)),
        ("../stocks/AAPL/bars?", "single", "AAPL", ("bars", 0)),
        ("AAPL/bars?", "single", "AAPL", ("bars", True)),
        ("AAPL/bars?", "single", "AAPL", ("bars", -1)),
    ],
)
def test_alpaca_observation_rejects_crossed_endpoint_identity_or_selector(
    tmp_path, route, shape, response_symbol, bar_path,
):
    bar = {"t": "2026-01-05T05:00:00Z", "c": 102.25}
    payload = {"bars": [bar] if shape == "single" else {"AAPL": [bar], "MSFT": [bar]}}
    if response_symbol is not None:
        payload["symbol"] = response_symbol
    archive, artifact = _archive(
        tmp_path,
        uri=f"https://data.alpaca.markets/v2/stocks/{route}timeframe=1Day&feed=sip&adjustment=raw",
        payload=payload,
    )
    with pytest.raises(PointInTimeDataError):
        build_alpaca_market_observation(
            security_identity=_security(), archive=archive, raw_artifact=artifact,
            market_calendar=_calendar(archive, "2026-01-05"),
            bar_path=bar_path, value_field="c",
        )


def test_official_observations_reject_missing_raw_source_facts(tmp_path):
    archive, artifact = _archive(
        tmp_path,
        uri=(
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&"
            "timeframe=1Day&feed=sip&adjustment=all"
        ),
        payload={"bars": {"AAPL": []}},
    )
    calendar = _calendar(archive, "2026-01-05")
    with pytest.raises(PointInTimeDataError):
        build_sec_fundamental_observation(
            security_identity=_security(),
            archive=archive,
            raw_artifact=artifact,
            source_identity_path=("cik",),
            value_path=("value",),
            event_time_path=("event_time",),
            publication_time_path=("publication_time",),
        )
    with pytest.raises(PointInTimeDataError):
        build_alpaca_market_observation(
            security_identity=_security(),
            archive=archive,
            raw_artifact=artifact,
            market_calendar=calendar,
            bar_path=("bars", "AAPL", 0),
            value_field="c",
        )


@pytest.mark.parametrize(
    ("uri", "payload", "bar_path", "identity"),
    [
        (
            "https://data.alpaca.markets/v2/stocks/bars?symbols=MSFT&timeframe=1Day&feed=iex&adjustment=raw",
            {"bars": {"MSFT": [{"t": "2026-01-05T05:00:00Z", "c": 10}]}},
            ("bars", "MSFT", 0),
            _security(),
        ),
        (
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&timeframe=1Day&feed=iex&adjustment=raw",
            {"bars": {"AAPL": [{"t": "2019-12-31T05:00:00Z", "c": 10}]}},
            ("bars", "AAPL", 0),
            _security(),
        ),
        (
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&timeframe=1Day&feed=iex&feed=sip&adjustment=raw",
            {"bars": {"AAPL": [{"t": "2026-01-05T05:00:00Z", "c": 10}]}},
            ("bars", "AAPL", 0),
            _security(),
        ),
        (
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&timeframe=Bogus&feed=iex&adjustment=raw",
            {"bars": {"AAPL": [{"t": "2026-01-05T15:00:00Z", "c": 10}]}},
            ("bars", "AAPL", 0),
            _security(),
        ),
    ],
)
def test_alpaca_observation_rejects_identity_date_and_feed_ambiguity(
    tmp_path,
    uri,
    payload,
    bar_path,
    identity,
):
    archive, artifact = _archive(tmp_path, uri=uri, payload=payload)
    calendar = _calendar(archive, "2026-01-05")

    with pytest.raises(PointInTimeDataError):
        build_alpaca_market_observation(
            security_identity=identity,
            archive=archive,
            raw_artifact=artifact,
            market_calendar=calendar,
            bar_path=bar_path,
            value_field="c",
        )


def test_alpaca_observation_rejects_duplicate_json_keys_as_ambiguous(tmp_path):
    archive = RawPointInTimeArtifactArchive(
        tmp_path / "pit-artifacts",
        clock=lambda: dt.datetime(2026, 1, 5, 21, 0, 5, tzinfo=dt.UTC),
    )
    artifact = archive.admit(
        raw_bytes=(
            b'{"bars":{"AAPL":[{"t":"2026-01-05T05:00:00Z","c":10}]},'
            b'"bars":{"AAPL":[{"t":"2026-01-05T05:00:00Z","c":999}]}}'
        ),
        source_uri=(
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&"
            "timeframe=1Day&feed=iex&adjustment=raw"
        ),
        content_type="application/json",
        retrieved_at="2026-01-05T21:00:00+00:00",
    )
    calendar = _calendar(archive, "2026-01-05")

    with pytest.raises(PointInTimeDataError, match="duplicate"):
        build_alpaca_market_observation(
            security_identity=_security(),
            archive=archive,
            raw_artifact=artifact,
            market_calendar=calendar,
            bar_path=("bars", "AAPL", 0),
            value_field="c",
        )


def test_alpaca_intraday_observation_uses_proven_interval_completion(tmp_path):
    archive, artifact = _archive(
        tmp_path,
        uri=(
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&"
            "timeframe=1Hour&feed=sip&adjustment=raw"
        ),
        payload={"bars": {"AAPL": [{"t": "2026-01-05T19:30:00Z", "v": 0}]}},
    )
    calendar = _calendar(archive, "2026-01-05")

    observation = build_alpaca_market_observation(
        security_identity=_security(),
        archive=archive,
        raw_artifact=artifact,
        market_calendar=calendar,
        bar_path=("bars", "AAPL", 0),
        value_field="v",
    )

    assert observation.observed_value == 0
    assert observation.publication_time == "2026-01-05T20:30:00+00:00"
    assert observation.source_span["publication_derivation"] == {
        "method": "bar_start_plus_timeframe",
        "completion_time": "2026-01-05T20:30:00+00:00",
        "market_timezone": "America/New_York",
        "regular_session_open": "09:30:00",
        "regular_session_close": "16:00:00",
        "bar_duration_seconds": 3600,
        "calendar_raw_artifact_id": calendar.raw_artifact_id,
        "calendar_raw_artifact_sha256": calendar.raw_artifact_sha256,
        "calendar_date_path": (0, "date"),
        "calendar_open_path": (0, "open"),
        "calendar_close_path": (0, "close"),
    }


def test_alpaca_daily_completion_uses_new_york_dst_offset(tmp_path):
    archive, artifact = _archive(
        tmp_path,
        uri=(
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&"
            "timeframe=1Day&feed=iex&adjustment=raw"
        ),
        payload={"bars": {"AAPL": [{"t": "2026-07-06T04:00:00Z", "c": 10}]}},
        retrieved_at="2026-07-06T20:00:00+00:00",
        archive_recorded_at="2026-07-06T20:00:05+00:00",
    )
    calendar = _calendar(archive, "2026-07-06")

    observation = build_alpaca_market_observation(
        security_identity=_security(),
        archive=archive,
        raw_artifact=artifact,
        market_calendar=calendar,
        bar_path=("bars", "AAPL", 0),
        value_field="c",
    )

    assert observation.publication_time == "2026-07-06T20:00:00+00:00"


def test_alpaca_observation_uses_source_early_close_and_rejects_post_close_bar(
    tmp_path,
):
    daily_archive, daily_artifact = _archive(
        tmp_path / "daily",
        uri=(
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&"
            "timeframe=1Day&feed=iex&adjustment=raw"
        ),
        payload={"bars": {"AAPL": [{"t": "2026-11-27T05:00:00Z", "c": 10}]}},
        retrieved_at="2026-11-27T18:00:00+00:00",
        archive_recorded_at="2026-11-27T18:00:05+00:00",
    )
    daily_calendar = _calendar(
        daily_archive,
        "2026-11-27",
        close_time="13:00",
    )

    observation = build_alpaca_market_observation(
        security_identity=_security(),
        archive=daily_archive,
        raw_artifact=daily_artifact,
        market_calendar=daily_calendar,
        bar_path=("bars", "AAPL", 0),
        value_field="c",
    )

    derivation = observation.source_span["publication_derivation"]
    assert observation.publication_time == "2026-11-27T18:00:00+00:00"
    assert derivation["regular_session_close"] == "13:00:00"
    assert derivation["calendar_raw_artifact_id"] == daily_calendar.raw_artifact_id
    assert derivation["calendar_raw_artifact_sha256"] == (
        daily_calendar.raw_artifact_sha256
    )
    assert derivation["calendar_close_path"] == (0, "close")

    late_archive, late_artifact = _archive(
        tmp_path / "post-close",
        uri=(
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&"
            "timeframe=5Min&feed=iex&adjustment=raw"
        ),
        payload={"bars": {"AAPL": [{"t": "2026-11-27T18:00:00Z", "c": 10}]}},
        retrieved_at="2026-11-27T20:00:00+00:00",
        archive_recorded_at="2026-11-27T20:00:05+00:00",
    )
    late_calendar = _calendar(
        late_archive,
        "2026-11-27",
        close_time="13:00",
    )

    with pytest.raises(PointInTimeDataError, match="outside"):
        build_alpaca_market_observation(
            security_identity=_security(),
            archive=late_archive,
            raw_artifact=late_artifact,
            market_calendar=late_calendar,
            bar_path=("bars", "AAPL", 0),
            value_field="c",
        )


@pytest.mark.parametrize(
    "row",
    [
        {"date": "2026-01-05", "open": "09:30"},
        {"date": "2026-01-05", "open": "9:30", "close": "16:00"},
        {"date": "2026-01-05", "open": "16:00", "close": "16:00"},
    ],
)
def test_alpaca_observation_rejects_absent_or_malformed_source_session_hours(
    tmp_path,
    row,
):
    archive, artifact = _archive(
        tmp_path,
        uri=(
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&"
            "timeframe=1Day&feed=iex&adjustment=raw"
        ),
        payload={"bars": {"AAPL": [{"t": "2026-01-05T05:00:00Z", "c": 10}]}},
    )
    calendar_artifact = archive.admit(
        raw_bytes=json.dumps([row], separators=(",", ":")).encode(),
        source_uri="https://paper-api.alpaca.markets/v2/calendar",
        content_type="application/json",
        retrieved_at="2020-01-01T00:00:00+00:00",
    )
    calendar = build_market_session_calendar(
        archive=archive,
        raw_artifact=calendar_artifact,
    )

    with pytest.raises(PointInTimeDataError):
        build_alpaca_market_observation(
            security_identity=_security(),
            archive=archive,
            raw_artifact=artifact,
            market_calendar=calendar,
            bar_path=("bars", "AAPL", 0),
            value_field="c",
        )


@pytest.mark.parametrize(
    "calendar_bytes",
    [
        b'[{"date":"2026-01-04","date":"2026-01-05","open":"09:30","close":"16:00"}]',
        b'[{"date":"2026-01-05","open":"09:30","close":"16:00","extra":NaN}]',
    ],
)
def test_market_calendar_rejects_ambiguous_or_nonfinite_json(
    tmp_path,
    calendar_bytes,
):
    archive = RawPointInTimeArtifactArchive(
        tmp_path / "pit-artifacts",
        clock=lambda: dt.datetime(2026, 1, 5, 21, 0, 5, tzinfo=dt.UTC),
    )
    calendar_artifact = archive.admit(
        raw_bytes=calendar_bytes,
        source_uri="https://paper-api.alpaca.markets/v2/calendar",
        content_type="application/json",
        retrieved_at="2026-01-05T21:00:00+00:00",
    )

    with pytest.raises(PointInTimeDataError):
        build_market_session_calendar(
            archive=archive,
            raw_artifact=calendar_artifact,
        )


@pytest.mark.parametrize(
    ("timeframe", "event_time", "market_dates", "retrieved_at"),
    [
        ("1Day", "2026-01-10T05:00:00Z", ("2026-01-09",), "2026-01-10T21:00:00+00:00"),
        ("1Day", "2026-01-01T05:00:00Z", ("2026-01-02",), "2026-01-01T21:00:00+00:00"),
        ("1Day", "2026-07-06T05:00:00Z", ("2026-07-06",), "2026-07-06T21:00:00+00:00"),
        ("1Hour", "2026-01-05T20:30:00Z", ("2026-01-05",), "2026-01-05T22:00:00+00:00"),
        ("2Min", "2026-01-05T14:30:00Z", ("2026-01-05",), "2026-01-05T21:00:00+00:00"),
    ],
)
def test_alpaca_observation_rejects_unproven_session_or_interval(
    tmp_path,
    timeframe,
    event_time,
    market_dates,
    retrieved_at,
):
    archive_recorded_at = (
        dt.datetime.fromisoformat(retrieved_at) + dt.timedelta(seconds=5)
    ).isoformat(timespec="seconds")
    archive, artifact = _archive(
        tmp_path,
        uri=(
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&"
            f"timeframe={timeframe}&feed=iex&adjustment=raw"
        ),
        payload={"bars": {"AAPL": [{"t": event_time, "c": 10}]}},
        retrieved_at=retrieved_at,
        archive_recorded_at=archive_recorded_at,
    )
    calendar = _calendar(archive, *market_dates)

    with pytest.raises(PointInTimeDataError):
        build_alpaca_market_observation(
            security_identity=_security(),
            archive=archive,
            raw_artifact=artifact,
            market_calendar=calendar,
            bar_path=("bars", "AAPL", 0),
            value_field="c",
        )


def test_alpaca_observation_rejects_retrieval_before_bar_completion(tmp_path):
    archive, artifact = _archive(
        tmp_path,
        uri=(
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&"
            "timeframe=1Day&feed=iex&adjustment=raw"
        ),
        payload={"bars": {"AAPL": [{"t": "2026-01-05T05:00:00Z", "c": 10}]}},
        retrieved_at="2026-01-05T20:59:59+00:00",
    )
    calendar = _calendar(archive, "2026-01-05")

    with pytest.raises(PointInTimeDataError, match="completion"):
        build_alpaca_market_observation(
            security_identity=_security(),
            archive=archive,
            raw_artifact=artifact,
            market_calendar=calendar,
            bar_path=("bars", "AAPL", 0),
            value_field="c",
        )


@pytest.mark.parametrize(
    ("number_literal", "expected"),
    [
        ("1.234567890123456789e2", "123.4567890123456789"),
        (
            "1.23456789012345678901234567890123456789e2",
            "123.456789012345678901234567890123456789",
        ),
        ("1e-7", "0.0000001"),
    ],
)
def test_alpaca_observation_preserves_decimal_source_numbers_losslessly(
    tmp_path,
    number_literal,
    expected,
):
    archive, artifact = _archive(
        tmp_path,
        uri=(
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&"
            "timeframe=1Day&feed=iex&adjustment=raw"
        ),
        raw_bytes=(
            '{"bars":{"AAPL":[{"t":"2026-01-05T05:00:00Z","c":'
            + number_literal
            + "}]}}"
        ).encode(),
    )
    calendar = _calendar(archive, "2026-01-05")

    observation = build_alpaca_market_observation(
        security_identity=_security(),
        archive=archive,
        raw_artifact=artifact,
        market_calendar=calendar,
        bar_path=("bars", "AAPL", 0),
        value_field="c",
    )

    assert observation.observed_value == expected


def test_official_observations_reject_compact_extreme_decimal_exponents(tmp_path):
    archive, artifact = _archive(
        tmp_path / "alpaca",
        uri=(
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&"
            "timeframe=1Day&feed=iex&adjustment=raw"
        ),
        raw_bytes=(
            b'{"bars":{"AAPL":[{"t":"2026-01-05T05:00:00Z",'
            b'"c":1e999999999}]}}'
        ),
    )
    calendar = _calendar(archive, "2026-01-05")

    with pytest.raises(PointInTimeDataError, match="resource limits"):
        build_alpaca_market_observation(
            security_identity=_security(),
            archive=archive,
            raw_artifact=artifact,
            market_calendar=calendar,
            bar_path=("bars", "AAPL", 0),
            value_field="c",
        )

    sec_archive, sec_artifact = _archive(
        tmp_path / "sec",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        raw_bytes=(
            b'{"cik":"0000000001","fact":{"nested":1e999999999},'
            b'"event_time":"2026-01-04T21:00:00Z",'
            b'"publication_time":"2026-01-05T20:00:00Z"}'
        ),
    )

    with pytest.raises(PointInTimeDataError, match="resource limits"):
        build_sec_fundamental_observation(
            security_identity=_security(),
            archive=sec_archive,
            raw_artifact=sec_artifact,
            source_identity_path=("cik",),
            value_path=("fact",),
            event_time_path=("event_time",),
            publication_time_path=("publication_time",),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("c", None),
        ("c", True),
        ("c", "10"),
        ("c", {}),
        ("c", []),
        ("c", 0),
        ("c", -1),
        ("v", -1),
        ("v", 1.5),
        ("v", True),
        ("v", "1"),
        ("n", None),
    ],
)
def test_alpaca_observation_rejects_wrong_numeric_type_or_domain(
    tmp_path,
    field,
    value,
):
    archive, artifact = _archive(
        tmp_path,
        uri=(
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&"
            "timeframe=1Day&feed=iex&adjustment=raw"
        ),
        payload={"bars": {"AAPL": [{"t": "2026-01-05T05:00:00Z", field: value}]}},
    )
    calendar = _calendar(archive, "2026-01-05")

    with pytest.raises(PointInTimeDataError):
        build_alpaca_market_observation(
            security_identity=_security(),
            archive=archive,
            raw_artifact=artifact,
            market_calendar=calendar,
            bar_path=("bars", "AAPL", 0),
            value_field=field,
        )


def test_alpaca_observation_requires_exact_source_bound_calendar(tmp_path):
    archive, artifact = _archive(
        tmp_path,
        uri=(
            "https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&"
            "timeframe=1Day&feed=iex&adjustment=raw"
        ),
        payload={"bars": {"AAPL": [{"t": "2026-01-05T05:00:00Z", "c": 10}]}},
    )

    with pytest.raises(PointInTimeDataError, match="MarketSessionCalendar"):
        build_alpaca_market_observation(
            security_identity=_security(),
            archive=archive,
            raw_artifact=artifact,
            market_calendar=None,
            bar_path=("bars", "AAPL", 0),
            value_field="c",
        )


def test_sec_observation_rejects_source_identity_mismatch(tmp_path):
    archive, artifact = _archive(
        tmp_path,
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000002.json",
        payload={
            "cik": "0000000002",
            "value": 42.5,
            "event_time": "2026-01-04T21:00:00+00:00",
            "publication_time": "2026-01-05T20:00:00+00:00",
        },
    )

    with pytest.raises(PointInTimeDataError, match="identity"):
        build_sec_fundamental_observation(
            security_identity=_security(),
            archive=archive,
            raw_artifact=artifact,
            source_identity_path=("cik",),
            value_path=("value",),
            event_time_path=("event_time",),
            publication_time_path=("publication_time",),
        )
