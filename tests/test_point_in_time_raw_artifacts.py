"""Regression coverage for immutable point-in-time source artifacts."""

from __future__ import annotations

import json

import pytest

import tradingagents.dataflows.pit.raw_artifacts as raw_artifacts
from tradingagents.dataflows.pit import (
    PointInTimeDataError,
    RawPointInTimeArtifactArchive,
    validate_raw_point_in_time_artifact,
)


def test_raw_artifact_archive_preserves_exact_source_bytes_and_canonical_receipt(
    tmp_path,
):
    archive = RawPointInTimeArtifactArchive(tmp_path / "pit-artifacts")
    raw_bytes = b'{"filed":"2026-01-05","value":42}\n'
    artifact = archive.admit(
        raw_bytes=raw_bytes,
        source_uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        content_type="application/json",
        retrieved_at="2026-01-05T21:00:00+00:00",
    )

    assert archive.read_bytes(artifact) == raw_bytes
    assert archive.admit(
        raw_bytes=raw_bytes,
        source_uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        content_type="application/json",
        retrieved_at="2026-01-05T21:00:00+00:00",
    ) == artifact
    assert validate_raw_point_in_time_artifact(
        json.loads(artifact.canonical_json_bytes())
    ) == artifact
    assert artifact.raw_artifact_id.startswith("pit-raw-artifact-")
    assert artifact.raw_artifact_sha256


def test_raw_artifact_archive_rejects_unsafe_source_or_tampered_bytes(tmp_path):
    archive = RawPointInTimeArtifactArchive(tmp_path / "pit-artifacts")
    with pytest.raises(PointInTimeDataError):
        archive.admit(
            raw_bytes=b"{}",
            source_uri="http://data.sec.gov/companyfacts.json",
            content_type="application/json",
            retrieved_at="2026-01-05T21:00:00+00:00",
        )

    artifact = archive.admit(
        raw_bytes=b"<html>SEC filing</html>",
        source_uri="https://www.sec.gov/Archives/edgar/data/1/example.htm",
        content_type="text/html",
        retrieved_at="2026-01-05T21:00:00+00:00",
    )
    raw_path = tmp_path / "pit-artifacts" / "objects" / f"{artifact.raw_artifact_id}.raw"
    raw_path.write_bytes(b"tampered")

    with pytest.raises(PointInTimeDataError):
        archive.read_bytes(artifact)


def test_raw_artifact_admission_syncs_files_and_containing_directories(
    monkeypatch,
    tmp_path,
):
    sync_calls: list[int] = []
    original_fsync = raw_artifacts.os.fsync
    monkeypatch.setattr(
        raw_artifacts.os,
        "fsync",
        lambda descriptor: (sync_calls.append(descriptor), original_fsync(descriptor))[1],
    )
    artifact = RawPointInTimeArtifactArchive(tmp_path / "pit-artifacts").admit(
        raw_bytes=b"{}",
        source_uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        content_type="application/json",
        retrieved_at="2026-01-05T21:00:00+00:00",
    )

    assert artifact.raw_artifact_id.startswith("pit-raw-artifact-")
    assert len(sync_calls) >= 4
