"""PIT observations must derive material facts from archived source bytes."""

from __future__ import annotations

import json

import pytest

from tradingagents.dataflows.pit import (
    PointInTimeDataError,
    RawPointInTimeArtifactArchive,
    build_alpaca_market_observation,
    build_sec_fundamental_observation,
)


def _archive(tmp_path, *, uri: str, payload: object):
    archive = RawPointInTimeArtifactArchive(tmp_path / "pit-artifacts")
    artifact = archive.admit(
        raw_bytes=json.dumps(payload, separators=(",", ":")).encode(),
        source_uri=uri,
        content_type="application/json",
        retrieved_at="2026-01-05T21:00:00+00:00",
    )
    return archive, artifact


def test_sec_observation_derives_times_and_full_source_span_from_bytes(tmp_path):
    archive, artifact = _archive(
        tmp_path,
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        payload={
            "event_time": "2026-01-04T21:00:00+00:00",
            "publication_time": "2026-01-05T20:00:00+00:00",
        },
    )
    observation = build_sec_fundamental_observation(
        security_id="security-0001", archive=archive, raw_artifact=artifact
    )

    assert observation.event_time == "2026-01-04T21:00:00+00:00"
    assert observation.publication_time == "2026-01-05T20:00:00+00:00"
    assert observation.availability_time == artifact.retrieved_at
    assert observation.source_span["end_byte"] == artifact.byte_count


def test_alpaca_observation_derives_feed_adjustment_and_bar_time_from_bytes(tmp_path):
    archive, artifact = _archive(
        tmp_path,
        uri="https://data.alpaca.markets/v2/stocks/bars?feed=iex&adjustment=split",
        payload={"bars": [{"t": "2026-01-05T20:00:00Z"}]},
    )
    observation = build_alpaca_market_observation(
        security_id="security-0001", archive=archive, raw_artifact=artifact
    )

    assert observation.event_time == "2026-01-05T20:00:00+00:00"
    assert observation.adjustment_status == "split_adjusted"
    assert observation.source_span["feed"] == "iex"


def test_official_observations_reject_missing_raw_source_facts(tmp_path):
    archive, artifact = _archive(
        tmp_path,
        uri="https://data.alpaca.markets/v2/stocks/bars?feed=sip&adjustment=all",
        payload={"bars": []},
    )
    with pytest.raises(PointInTimeDataError):
        build_sec_fundamental_observation(
            security_id="security-0001", archive=archive, raw_artifact=artifact
        )
    with pytest.raises(PointInTimeDataError):
        build_alpaca_market_observation(
            security_id="security-0001", archive=archive, raw_artifact=artifact
        )
