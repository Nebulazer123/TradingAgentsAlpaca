"""Contracts for source-bound adjusted Alpaca price windows."""

from __future__ import annotations

import json

import pytest

from tradingagents.dataflows.pit import (
    PointInTimeDataError,
    RawPointInTimeArtifactArchive,
    build_market_session_calendar,
    build_source_bound_adjusted_price_window,
    validate_five_session_adjusted_price_window,
    validate_source_bound_adjusted_price_window,
    verify_source_bound_adjusted_price_window,
)


def _artifact(
    tmp_path,
    *,
    adjustment: str = "all",
    retrieved_at: str = "2026-01-09T21:00:00+00:00",
    symbol: str = "T000",
    include_bounds: bool = True,
    request_end: str = "2026-01-08T00:00:00Z",
    extra_query: str = "",
):
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
            f"timeframe=1Day&feed=iex&adjustment={adjustment}"
            + (
                "&start=2026-01-05T00:00:00Z"
                f"&end={request_end}"
                if include_bounds
                else ""
            )
            + extra_query
        ),
        content_type="application/json",
        retrieved_at=retrieved_at,
    )
    return archive, artifact


def test_adjusted_window_is_derived_from_exact_alpaca_bytes_and_cutoff(tmp_path):
    archive, artifact = _artifact(tmp_path)

    window = build_source_bound_adjusted_price_window(
        archive=archive,
        raw_artifact=artifact,
        security_id="security-t000",
        symbol="T000",
        requested_start="2026-01-05",
        requested_end="2026-01-07",
        decision_cutoff="2026-01-09T21:00:00+00:00",
    )

    assert window.symbol == "T000"
    assert window.entry_date == "2026-01-05"
    assert window.entry_close == "10"
    assert window.exit_date == "2026-01-07"
    assert window.exit_close == "12"
    assert window.session_count == 3
    assert window.daily_closes == (
        ("2026-01-05", "10"),
        ("2026-01-06", "11"),
        ("2026-01-07", "12"),
    )
    assert window.feed == "iex"
    assert window.adjustment_mode == "all"
    assert window.adjustment_status == "total_return_adjusted"
    assert window.raw_artifact_id == artifact.raw_artifact_id
    assert window.raw_artifact_sha256 == artifact.raw_artifact_sha256
    rebuilt = validate_source_bound_adjusted_price_window(window.to_dict())
    assert rebuilt.canonical_json_bytes() == window.canonical_json_bytes()
    verified = verify_source_bound_adjusted_price_window(
        archive=archive,
        raw_artifact=artifact,
        value=window.to_dict(),
    )
    assert verified.canonical_json_bytes() == window.canonical_json_bytes()

    tampered = window.to_dict()
    tampered["daily_closes"][1]["close"] = "9"
    with pytest.raises(PointInTimeDataError):
        validate_source_bound_adjusted_price_window(tampered)


def test_adjusted_window_rejects_unadjusted_or_future_available_source_bytes(tmp_path):
    archive, unadjusted = _artifact(tmp_path, adjustment="raw")
    with pytest.raises(PointInTimeDataError):
        build_source_bound_adjusted_price_window(
            archive=archive,
            raw_artifact=unadjusted,
            security_id="security-t000",
            symbol="T000",
            requested_start="2026-01-05",
            requested_end="2026-01-07",
            decision_cutoff="2026-01-09T21:00:00+00:00",
        )

def test_adjusted_window_binds_request_range_and_pit_identity_contract(tmp_path):
    archive, missing_bounds = _artifact(tmp_path / "missing", include_bounds=False)
    with pytest.raises(PointInTimeDataError):
        build_source_bound_adjusted_price_window(
            archive=archive,
            raw_artifact=missing_bounds,
            security_id="security-t000",
            symbol="T000",
            requested_start="2026-01-05",
            requested_end="2026-01-07",
            decision_cutoff="2026-01-09T21:00:00+00:00",
        )


def test_five_session_window_uses_exact_next_calendar_sessions(tmp_path):
    dates = [
        "2026-01-09",
        "2026-01-12",
        "2026-01-13",
        "2026-01-14",
        "2026-01-15",
        "2026-01-16",
    ]
    archive = RawPointInTimeArtifactArchive(tmp_path / "five" / "pit-artifacts")
    calendar_artifact = archive.admit(
        raw_bytes=json.dumps([{"date": date} for date in dates]).encode(),
        source_uri="https://paper-api.alpaca.markets/v2/calendar",
        content_type="application/json",
        retrieved_at="2026-01-20T21:00:00+00:00",
    )
    calendar = build_market_session_calendar(
        archive=archive,
        raw_artifact=calendar_artifact,
    )
    price_artifact = archive.admit(
        raw_bytes=json.dumps(
            {
                "bars": {
                    "T000": [
                        {"t": f"{date}T05:00:00Z", "c": str(10 + index)}
                        for index, date in enumerate(dates[1:])
                    ]
                }
            }
        ).encode(),
        source_uri=(
            "https://data.alpaca.markets/v2/stocks/T000/bars?"
            "timeframe=1Day&feed=iex&adjustment=all&"
            "start=2026-01-12T00:00:00Z&end=2026-01-17T00:00:00Z"
        ),
        content_type="application/json",
        retrieved_at="2026-01-20T21:00:00+00:00",
    )
    window = build_source_bound_adjusted_price_window(
        archive=archive,
        raw_artifact=price_artifact,
        security_id="security-t000",
        symbol="T000",
        requested_start="2026-01-12",
        requested_end="2026-01-16",
        decision_cutoff="2026-01-20T21:00:00+00:00",
    )

    validated = validate_five_session_adjusted_price_window(
        value=window.to_dict(),
        market_calendar=calendar,
        decision_market_date="2026-01-09",
    )
    assert tuple(date for date, _close in validated.daily_closes) == tuple(dates[1:])

    tampered = window.to_dict()
    tampered["daily_closes"] = tampered["daily_closes"][1:]
    tampered["session_count"] = 4
    tampered["entry_date"] = "2026-01-13"
    tampered["entry_close"] = "11"
    with pytest.raises(PointInTimeDataError):
        validate_five_session_adjusted_price_window(
            value=tampered,
            market_calendar=calendar,
            decision_market_date="2026-01-09",
        )

    archive, wrong_end = _artifact(
        tmp_path / "wrong-end", request_end="2026-01-09T00:00:00Z"
    )
    with pytest.raises(PointInTimeDataError):
        build_source_bound_adjusted_price_window(
            archive=archive,
            raw_artifact=wrong_end,
            security_id="security-t000",
            symbol="T000",
            requested_start="2026-01-05",
            requested_end="2026-01-07",
            decision_cutoff="2026-01-09T21:00:00+00:00",
        )

    archive, duplicated_start = _artifact(
        tmp_path / "duplicate",
        extra_query="&start=2026-01-05T00:00:00Z",
    )
    with pytest.raises(PointInTimeDataError):
        build_source_bound_adjusted_price_window(
            archive=archive,
            raw_artifact=duplicated_start,
            security_id="security-t000",
            symbol="T000",
            requested_start="2026-01-05",
            requested_end="2026-01-07",
            decision_cutoff="2026-01-09T21:00:00+00:00",
        )

    archive, brk_b = _artifact(tmp_path / "brk-b", symbol="BRK-B")
    window = build_source_bound_adjusted_price_window(
        archive=archive,
        raw_artifact=brk_b,
        security_id="security-brk-b",
        symbol="BRK-B",
        requested_start="2026-01-05",
        requested_end="2026-01-07",
        decision_cutoff="2026-01-09T21:00:00+00:00",
    )
    assert window.symbol == "BRK-B"
    with pytest.raises(PointInTimeDataError):
        build_source_bound_adjusted_price_window(
            archive=archive,
            raw_artifact=brk_b,
            security_id="security-brk-b",
            symbol="BRK-B",
            requested_start="2026-01-05",
            requested_end="9999-12-31",
            decision_cutoff="2026-01-09T21:00:00+00:00",
        )
    with pytest.raises(PointInTimeDataError):
        build_source_bound_adjusted_price_window(
            archive=archive,
            raw_artifact=brk_b,
            security_id="x",
            symbol="BRK-B",
            requested_start="2026-01-05",
            requested_end="2026-01-07",
            decision_cutoff="2026-01-09T21:00:00+00:00",
        )

    archive, future = _artifact(tmp_path / "future", retrieved_at="2026-01-09T21:01:00+00:00")
    with pytest.raises(PointInTimeDataError):
        build_source_bound_adjusted_price_window(
            archive=archive,
            raw_artifact=future,
            security_id="security-t000",
            symbol="T000",
            requested_start="2026-01-05",
            requested_end="2026-01-07",
            decision_cutoff="2026-01-09T21:00:00+00:00",
        )
