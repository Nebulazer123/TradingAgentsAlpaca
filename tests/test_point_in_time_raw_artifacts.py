"""Regression coverage for immutable point-in-time source artifacts."""

from __future__ import annotations

import datetime as dt
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
    archive = RawPointInTimeArtifactArchive(
        tmp_path / "pit-artifacts",
        clock=lambda: dt.datetime(2026, 1, 5, 21, 0, 5, tzinfo=dt.UTC),
    )
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
    assert artifact.retrieved_at == "2026-01-05T21:00:00+00:00"
    assert artifact.archive_recorded_at == "2026-01-05T21:00:05+00:00"
    assert artifact.to_dict()["schema_version"] == "raw_point_in_time_artifact/v2"


def test_raw_artifact_archive_rejects_unsafe_source_or_tampered_bytes(tmp_path):
    archive = RawPointInTimeArtifactArchive(
        tmp_path / "pit-artifacts",
        clock=lambda: dt.datetime(2026, 1, 5, 21, 0, 5, tzinfo=dt.UTC),
    )
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


@pytest.mark.parametrize(
    "clock_value",
    [
        dt.datetime(2026, 1, 5, 21, 0, 5),
        dt.datetime(2026, 1, 5, 21, 0, 5, 1, tzinfo=dt.UTC),
        "2026-01-05T21:00:05+00:00",
    ],
)
def test_raw_artifact_archive_rejects_nonexact_nonutc_clock_values(
    tmp_path,
    clock_value,
):
    archive = RawPointInTimeArtifactArchive(
        tmp_path / "pit-artifacts",
        clock=lambda: clock_value,
    )

    with pytest.raises(PointInTimeDataError, match="clock"):
        archive.admit(
            raw_bytes=b"{}",
            source_uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
            content_type="application/json",
            retrieved_at="2026-01-05T21:00:00+00:00",
        )


def test_raw_artifact_archive_rejects_archive_time_before_source_retrieval(tmp_path):
    archive = RawPointInTimeArtifactArchive(
        tmp_path / "pit-artifacts",
        clock=lambda: dt.datetime(2026, 1, 5, 20, 59, 59, tzinfo=dt.UTC),
    )

    with pytest.raises(PointInTimeDataError, match="before source retrieval"):
        archive.admit(
            raw_bytes=b"{}",
            source_uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
            content_type="application/json",
            retrieved_at="2026-01-05T21:00:00+00:00",
        )


def test_raw_artifact_archive_rejects_tampered_trusted_time_and_unsafe_paths(tmp_path):
    archive = RawPointInTimeArtifactArchive(
        tmp_path / "pit-artifacts",
        clock=lambda: dt.datetime(2026, 1, 5, 21, 0, 5, tzinfo=dt.UTC),
    )
    artifact = archive.admit(
        raw_bytes=b'{"value":42}',
        source_uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        content_type="application/json",
        retrieved_at="2026-01-05T21:00:00+00:00",
    )
    objects = tmp_path / "pit-artifacts" / "objects"
    receipt_path = objects / f"{artifact.raw_artifact_id}.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["archive_recorded_at"] = "2026-01-05T20:59:59+00:00"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(PointInTimeDataError):
        archive.read_artifact(artifact.raw_artifact_id)

    receipt_path.unlink()
    receipt_path.symlink_to(objects / "missing-receipt.json")
    with pytest.raises(PointInTimeDataError, match="regular file"):
        archive.read_artifact(artifact.raw_artifact_id)


@pytest.mark.parametrize("reader", ["by_object", "by_id"])
@pytest.mark.parametrize("tamper", ["whitespace", "key_order", "duplicate_key"])
def test_raw_artifact_archive_rejects_noncanonical_or_ambiguous_receipt_bytes(
    tmp_path,
    reader,
    tamper,
):
    archive = RawPointInTimeArtifactArchive(
        tmp_path / "pit-artifacts",
        clock=lambda: dt.datetime(2026, 1, 5, 21, 0, 5, tzinfo=dt.UTC),
    )
    artifact = archive.admit(
        raw_bytes=b'{"value":42}',
        source_uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        content_type="application/json",
        retrieved_at="2026-01-05T21:00:00+00:00",
    )
    receipt_path = (
        tmp_path
        / "pit-artifacts"
        / "objects"
        / f"{artifact.raw_artifact_id}.json"
    )
    canonical = artifact.canonical_json_bytes()
    if tamper == "whitespace":
        receipt_path.write_bytes(b" " + canonical)
    elif tamper == "key_order":
        payload = json.loads(canonical)
        receipt_path.write_bytes(
            json.dumps(
                dict(reversed(tuple(payload.items()))),
                separators=(",", ":"),
            ).encode("utf-8")
        )
        assert receipt_path.read_bytes() != canonical
    else:
        receipt_path.write_bytes(
            canonical[:-1]
            + b',"raw_artifact_id":"'
            + artifact.raw_artifact_id.encode("ascii")
            + b'"}'
        )

    with pytest.raises(PointInTimeDataError):
        if reader == "by_object":
            archive.read_receipt(artifact)
        else:
            archive.read_artifact(artifact.raw_artifact_id)


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
    artifact = RawPointInTimeArtifactArchive(
        tmp_path / "pit-artifacts",
        clock=lambda: dt.datetime(2026, 1, 5, 21, 0, 5, tzinfo=dt.UTC),
    ).admit(
        raw_bytes=b"{}",
        source_uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        content_type="application/json",
        retrieved_at="2026-01-05T21:00:00+00:00",
    )

    assert artifact.raw_artifact_id.startswith("pit-raw-artifact-")
    assert len(sync_calls) >= 4
