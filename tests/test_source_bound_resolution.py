"""Resolution-quality bridge contracts for archived PIT price evidence."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tradingagents.dataflows.pit import (
    PointInTimeDataError,
    RawPointInTimeArtifactArchive,
    build_source_bound_adjusted_price_window,
)
from tradingagents.evals.source_bound_resolution import (
    build_source_bound_window_lookup,
    load_source_bound_window_lookup,
    source_bound_price_window,
)


def _window(tmp_path, *, symbol: str = "T000", last_close: str = "12"):
    archive = RawPointInTimeArtifactArchive(tmp_path / "pit-artifacts")
    artifact = archive.admit(
        raw_bytes=json.dumps(
            {
                "symbol": symbol,
                "next_page_token": None,
                "bars": [
                    {"t": "2026-01-05T05:00:00Z", "c": "10"},
                    {"t": "2026-01-06T05:00:00Z", "c": "11"},
                    {"t": "2026-01-07T05:00:00Z", "c": last_close},
                ],
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
    assert window.source_evidence == {
        "schema_version": "source_bound_price_window_evidence/v1",
        "window_id": receipt.window_id,
        "window_sha256": receipt.window_sha256,
        "security_id": "security-t000",
        "raw_artifact_id": artifact.raw_artifact_id,
        "raw_artifact_sha256": artifact.raw_artifact_sha256,
        "decision_cutoff": "2026-01-09T21:00:00+00:00",
        "retrieved_at": "2026-01-09T21:00:00+00:00",
        "feed": "iex",
        "adjustment_mode": "all",
        "adjustment_status": "total_return_adjusted",
    }


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


def test_source_bound_lookup_reverifies_both_retained_forecast_legs(tmp_path):
    archive, ticker_artifact, ticker_receipt = _window(tmp_path, symbol="T000")
    _archive, benchmark_artifact, benchmark_receipt = _window(tmp_path, symbol="SPY")
    lookup = build_source_bound_window_lookup(
        archive=archive,
        raw_artifacts={
            ticker_artifact.raw_artifact_id: ticker_artifact,
            benchmark_artifact.raw_artifact_id: benchmark_artifact,
        },
        receipts=(ticker_receipt, benchmark_receipt),
    )
    ticker = lookup("T000", "2026-01-05", "2026-01-07")
    benchmark = lookup("SPY", "2026-01-05", "2026-01-07")
    assert ticker is not None and benchmark is not None
    forecast = SimpleNamespace(
        ticker="T000",
        benchmark="SPY",
        direction="bullish",
        probability="0.60",
        resolved=True,
        outcome=False,
        actual_return="20.00",
        benchmark_return="20.00",
        relative_return="0.00",
        brier_score="0.36",
        agent_score_delta="-0.10",
        resolution_window={
            "intended_start": "2026-01-05",
            "intended_end": "2026-01-07",
        },
        resolution_evidence={
            "schema_version": "source_bound_resolution_evidence/v2",
            "ticker": ticker.source_evidence,
            "benchmark": benchmark.source_evidence,
            "alpha_threshold_pct": "1.5",
        },
    )

    assert lookup.verify_forecast(forecast) is True
    forecast.probability = "1.01"
    forecast.brier_score = "1.0201"
    forecast.agent_score_delta = "-0.51"
    assert lookup.verify_forecast(forecast) is False
    forecast.probability = "0.60"
    forecast.brier_score = "0.36"
    forecast.agent_score_delta = "-0.10"
    forecast.outcome = True
    assert lookup.verify_forecast(forecast) is False


def test_source_bound_lookup_uses_the_retained_alpha_threshold(tmp_path):
    archive, ticker_artifact, ticker_receipt = _window(tmp_path, symbol="T000")
    _archive, benchmark_artifact, benchmark_receipt = _window(
        tmp_path,
        symbol="SPY",
        last_close="10.1",
    )
    lookup = build_source_bound_window_lookup(
        archive=archive,
        raw_artifacts={
            ticker_artifact.raw_artifact_id: ticker_artifact,
            benchmark_artifact.raw_artifact_id: benchmark_artifact,
        },
        receipts=(ticker_receipt, benchmark_receipt),
    )
    ticker = lookup("T000", "2026-01-05", "2026-01-07")
    benchmark = lookup("SPY", "2026-01-05", "2026-01-07")
    assert ticker is not None and benchmark is not None
    forecast = SimpleNamespace(
        ticker="T000",
        benchmark="SPY",
        direction="bullish",
        probability="0.60",
        resolved=True,
        outcome=False,
        actual_return="20.00",
        benchmark_return="1.00",
        relative_return="19.00",
        brier_score="0.36",
        agent_score_delta="-0.10",
        resolution_window={
            "intended_start": "2026-01-05",
            "intended_end": "2026-01-07",
        },
        resolution_evidence={
            "schema_version": "source_bound_resolution_evidence/v2",
            "ticker": ticker.source_evidence,
            "benchmark": benchmark.source_evidence,
            "alpha_threshold_pct": "20",
        },
    )

    assert lookup.verify_forecast(forecast) is True
    forecast.resolution_evidence["alpha_threshold_pct"] = "1.5"
    assert lookup.verify_forecast(forecast) is False
    forecast.outcome = False
    forecast.resolution_evidence["ticker"]["security_id"] = "security-tampered"
    assert lookup.verify_forecast(forecast) is False


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
    with pytest.raises(
        PointInTimeDataError,
        match="economic protocol and forecast-event bindings must be supplied together",
    ):
        build_source_bound_window_lookup(
            archive=archive,
            raw_artifacts={artifact.raw_artifact_id: artifact},
            receipts=(receipt,),
            forecast_event_bindings={"af-1": "decision-event-" + "a" * 64},
        )
    with pytest.raises(
        PointInTimeDataError,
        match="economic protocol and forecast-event bindings must be supplied together",
    ):
        build_source_bound_window_lookup(
            archive=archive,
            raw_artifacts={artifact.raw_artifact_id: artifact},
            receipts=(receipt,),
            economic_protocol=object(),
        )


def test_source_bound_window_lookup_loads_only_canonical_receipts(tmp_path):
    archive, artifact, receipt = _window(tmp_path)
    raw_receipt_path = tmp_path / "raw-artifact.json"
    price_receipt_path = tmp_path / "price-window.json"
    raw_receipt_path.write_bytes(artifact.canonical_json_bytes())
    price_receipt_path.write_bytes(receipt.canonical_json_bytes())

    lookup = load_source_bound_window_lookup(
        raw_artifact_archive=archive.root,
        raw_artifact_receipts=(raw_receipt_path,),
        price_window_receipts=(price_receipt_path,),
    )

    window = lookup("T000", "2026-01-05", "2026-01-07")
    assert window is not None
    assert window.entry_close == "10"
