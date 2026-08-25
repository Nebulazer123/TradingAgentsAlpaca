"""Resolution-quality bridge contracts for archived PIT price evidence."""

from __future__ import annotations

import json

import pytest

from tradingagents.dataflows.pit import (
    PointInTimeDataError,
    RawPointInTimeArtifactArchive,
    build_source_bound_adjusted_price_window,
)
from tradingagents.evals.source_bound_resolution import (
    build_source_bound_window_lookup,
    source_bound_price_window,
)


def _window(tmp_path, *, symbol: str = "T000"):
    archive = RawPointInTimeArtifactArchive(tmp_path / "pit-artifacts")
    artifact = archive.admit(
        raw_bytes=json.dumps(
            {
                "bars": {
                    symbol: [
                        {"t": "2026-01-05T05:00:00Z", "c": "10"},
                        {"t": "2026-01-06T05:00:00Z", "c": "11"},
                        {"t": "2026-01-07T05:00:00Z", "c": "12"},
                    ]
                }
            }
        ).encode(),
        source_uri=(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/bars?"
            "timeframe=1Day&feed=iex&adjustment=all"
            "&start=2026-01-05T00:00:00Z&end=2026-01-08T00:00:00Z"
        ),
        content_type="application/json",
        retrieved_at="2026-01-09T21:00:00+00:00",
    )
    return archive, artifact, build_source_bound_adjusted_price_window(
        archive=archive,
        raw_artifact=artifact,
        security_id=f"security-{symbol.lower()}",
        symbol=symbol,
        requested_start="2026-01-05",
        requested_end="2026-01-07",
        decision_cutoff="2026-01-09T21:00:00+00:00",
    )


def test_source_bound_price_window_reverifies_archived_bytes(tmp_path):
    archive, artifact, receipt = _window(tmp_path)

    window = source_bound_price_window(
        archive=archive,
        raw_artifact=artifact,
        receipt=receipt,
    )

    assert window.symbol == "T000"
    assert window.entry_close == "10"
    assert window.exit_close == "12"
    assert window.session_count == 3


def test_source_bound_window_lookup_has_no_fallback_and_rejects_wrong_artifact(tmp_path):
    archive, artifact, receipt = _window(tmp_path)
    _archive, wrong_artifact, _receipt = _window(tmp_path / "wrong", symbol="SPY")

    with pytest.raises(PointInTimeDataError):
        source_bound_price_window(
            archive=archive,
            raw_artifact=wrong_artifact,
            receipt=receipt,
        )

    lookup = build_source_bound_window_lookup(
        archive=archive,
        raw_artifacts={artifact.raw_artifact_id: artifact},
        receipts=(receipt,),
    )
    assert lookup("T000", "2026-01-05", "2026-01-07") is not None
    assert lookup("SPY", "2026-01-05", "2026-01-07") is None

    raw_path = archive.root / "objects" / f"{artifact.raw_artifact_id}.raw"
    raw_path.write_bytes(b"corrupted")
    with pytest.raises(PointInTimeDataError):
        source_bound_price_window(
            archive=archive,
            raw_artifact=artifact,
            receipt=receipt,
        )
    with pytest.raises(PointInTimeDataError):
        lookup("T000", "2026-01-05", "2026-01-07")


def test_source_bound_window_lookup_rejects_malformed_outer_containers(tmp_path):
    archive, artifact, receipt = _window(tmp_path)

    with pytest.raises(PointInTimeDataError):
        build_source_bound_window_lookup(
            archive=archive,
            raw_artifacts=None,
            receipts=(receipt,),
        )
    with pytest.raises(PointInTimeDataError):
        build_source_bound_window_lookup(
            archive=archive,
            raw_artifacts={artifact.raw_artifact_id: artifact},
            receipts=None,
        )
