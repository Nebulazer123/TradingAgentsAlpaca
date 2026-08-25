"""Source-bound PIT observation builders for official SEC and market data."""

from __future__ import annotations

import hashlib

import pytest

from tradingagents.dataflows.pit import (
    PointInTimeDataError,
    RawPointInTimeArtifactArchive,
    build_alpaca_market_observation,
    build_sec_fundamental_observation,
)


def _archive(tmp_path, *, uri: str, raw_bytes: bytes):
    archive = RawPointInTimeArtifactArchive(tmp_path / "pit-artifacts")
    artifact = archive.admit(
        raw_bytes=raw_bytes,
        source_uri=uri,
        content_type="application/json",
        retrieved_at="2026-01-05T21:00:00+00:00",
    )
    return archive, artifact


def test_sec_observation_binds_exact_archived_bytes_and_source_span(tmp_path):
    raw_bytes = b'{"facts":{"OperatingIncomeLoss":42}}'
    archive, artifact = _archive(
        tmp_path,
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        raw_bytes=raw_bytes,
    )
    observation = build_sec_fundamental_observation(
        security_id="security-0001",
        archive=archive,
        raw_artifact=artifact,
        event_time="2026-01-04T21:00:00+00:00",
        publication_time="2026-01-05T20:00:00+00:00",
        availability_time="2026-01-05T20:30:00+00:00",
        source_span={
            "span_type": "byte_range",
            "start_byte": 0,
            "end_byte": len(raw_bytes),
            "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        },
    )

    assert observation.raw_artifact_id == artifact.raw_artifact_id
    assert observation.raw_artifact_sha256 == artifact.raw_artifact_sha256
    assert observation.adjustment_status == "unadjusted"
    assert observation.source_span["source_kind"] == "sec_html_xbrl"


def test_official_observations_reject_wrong_origin_or_unverifiable_source_span(tmp_path):
    raw_bytes = b'{"bars":[]}'
    sec_archive, sec_artifact = _archive(
        tmp_path,
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        raw_bytes=raw_bytes,
    )
    with pytest.raises(PointInTimeDataError):
        build_sec_fundamental_observation(
            security_id="security-0001",
            archive=sec_archive,
            raw_artifact=sec_artifact,
            event_time="2026-01-04T21:00:00+00:00",
            publication_time="2026-01-05T20:00:00+00:00",
            availability_time="2026-01-05T20:30:00+00:00",
            source_span={
                "span_type": "byte_range",
                "start_byte": 0,
                "end_byte": len(raw_bytes) + 1,
                "source_sha256": sec_artifact.raw_artifact_sha256,
            },
        )

    alpaca_archive, alpaca_artifact = _archive(
        tmp_path,
        uri="https://data.alpaca.markets/v2/stocks/bars",
        raw_bytes=raw_bytes,
    )
    with pytest.raises(PointInTimeDataError):
        build_sec_fundamental_observation(
            security_id="security-0001",
            archive=alpaca_archive,
            raw_artifact=alpaca_artifact,
            event_time="2026-01-05T20:00:00+00:00",
            publication_time="2026-01-05T20:00:00+00:00",
            availability_time="2026-01-05T20:00:00+00:00",
            source_span={
                "span_type": "byte_range",
                "start_byte": 0,
                "end_byte": len(raw_bytes),
                "source_sha256": alpaca_artifact.raw_artifact_sha256,
            },
        )
    observation = build_alpaca_market_observation(
        security_id="security-0001",
        archive=alpaca_archive,
        raw_artifact=alpaca_artifact,
        event_time="2026-01-05T20:00:00+00:00",
        publication_time="2026-01-05T20:00:00+00:00",
        availability_time="2026-01-05T20:00:00+00:00",
        feed="iex",
        adjustment_mode="split",
        source_span={
            "span_type": "byte_range",
            "start_byte": 0,
            "end_byte": len(raw_bytes),
            "source_sha256": alpaca_artifact.raw_artifact_sha256,
        },
    )
    assert observation.source_span["feed"] == "iex"
    assert observation.adjustment_status == "split_adjusted"
