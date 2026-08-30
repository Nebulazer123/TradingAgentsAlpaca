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


def _archive(tmp_path, *, uri: str, payload: object):
    archive = RawPointInTimeArtifactArchive(
        tmp_path / "pit-artifacts",
        clock=lambda: dt.datetime(2026, 1, 5, 21, 0, 5, tzinfo=dt.UTC),
    )
    artifact = archive.admit(
        raw_bytes=json.dumps(payload, separators=(",", ":")).encode(),
        source_uri=uri,
        content_type="application/json",
        retrieved_at="2026-01-05T21:00:00+00:00",
    )
    return archive, artifact


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
                                    "val": "42.5",
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
            "https://data.alpaca.markets/v2/stocks/AAPL/bars?"
            "timeframe=1Day&feed=iex&adjustment=split"
        ),
        payload={"bars": {"AAPL": [{"t": "2026-01-05T05:00:00Z", "c": "102.25"}]}},
    )
    observation = build_alpaca_market_observation(
        security_identity=_security(),
        archive=archive,
        raw_artifact=artifact,
        bar_path=("bars", "AAPL", 0),
        value_field="c",
    )

    assert observation.observed_value == "102.25"
    assert observation.event_time == "2026-01-05T05:00:00+00:00"
    assert observation.adjustment_status == "split_adjusted"
    assert observation.market_data_feed == "iex"
    assert observation.adjustment_mode == "split"
    assert observation.market_session == "regular"
    assert observation.session_date == "2026-01-05"
    assert observation.source_span["paths"]["observed_value"] == (
        "bars",
        "AAPL",
        0,
        "c",
    )


def test_official_observations_reject_missing_raw_source_facts(tmp_path):
    archive, artifact = _archive(
        tmp_path,
        uri=(
            "https://data.alpaca.markets/v2/stocks/AAPL/bars?"
            "timeframe=1Day&feed=sip&adjustment=all"
        ),
        payload={"bars": {"AAPL": []}},
    )
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
            bar_path=("bars", "AAPL", 0),
            value_field="c",
        )


@pytest.mark.parametrize(
    ("uri", "payload", "bar_path", "identity"),
    [
        (
            "https://data.alpaca.markets/v2/stocks/MSFT/bars?timeframe=1Day&feed=iex&adjustment=raw",
            {"bars": {"MSFT": [{"t": "2026-01-05T05:00:00Z", "c": "10"}]}},
            ("bars", "MSFT", 0),
            _security(),
        ),
        (
            "https://data.alpaca.markets/v2/stocks/AAPL/bars?timeframe=1Day&feed=iex&adjustment=raw",
            {"bars": {"AAPL": [{"t": "2019-12-31T05:00:00Z", "c": "10"}]}},
            ("bars", "AAPL", 0),
            _security(),
        ),
        (
            "https://data.alpaca.markets/v2/stocks/AAPL/bars?timeframe=1Day&feed=iex&feed=sip&adjustment=raw",
            {"bars": {"AAPL": [{"t": "2026-01-05T05:00:00Z", "c": "10"}]}},
            ("bars", "AAPL", 0),
            _security(),
        ),
        (
            "https://data.alpaca.markets/v2/stocks/AAPL/bars?timeframe=Bogus&feed=iex&adjustment=raw",
            {"bars": {"AAPL": [{"t": "2026-01-05T15:00:00Z", "c": "10"}]}},
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

    with pytest.raises(PointInTimeDataError):
        build_alpaca_market_observation(
            security_identity=identity,
            archive=archive,
            raw_artifact=artifact,
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
            b'{"bars":{"AAPL":[{"t":"2026-01-05T05:00:00Z","c":"10"}]},'
            b'"bars":{"AAPL":[{"t":"2026-01-05T05:00:00Z","c":"999"}]}}'
        ),
        source_uri=(
            "https://data.alpaca.markets/v2/stocks/AAPL/bars?"
            "timeframe=1Day&feed=iex&adjustment=raw"
        ),
        content_type="application/json",
        retrieved_at="2026-01-05T21:00:00+00:00",
    )

    with pytest.raises(PointInTimeDataError, match="duplicate"):
        build_alpaca_market_observation(
            security_identity=_security(),
            archive=archive,
            raw_artifact=artifact,
            bar_path=("bars", "AAPL", 0),
            value_field="c",
        )


def test_sec_observation_rejects_source_identity_mismatch(tmp_path):
    archive, artifact = _archive(
        tmp_path,
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000002.json",
        payload={
            "cik": "0000000002",
            "value": "42.5",
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
