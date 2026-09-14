"""Single-symbol REST shape, symbol identity and complete-page contracts."""

from __future__ import annotations

import copy
import json

import pytest

from tradingagents.dataflows.pit import (
    PointInTimeDataError,
    RawPointInTimeArtifactArchive,
    build_source_bound_adjusted_price_window,
    verify_source_bound_adjusted_price_window,
)


def _payload():
    # Alpaca BarsResponse, not the SDK's symbol-indexed BarSet conversion.
    return {
        "symbol": "T000",
        "next_page_token": None,
        "bars": [
            {"t": "2026-01-05T05:00:00Z", "o": 10, "h": 10, "l": 10, "c": 10, "v": 100},
            {"t": "2026-01-06T05:00:00Z", "o": 11, "h": 11, "l": 11, "c": 11, "v": 100},
            {"t": "2026-01-07T05:00:00Z", "o": 12, "h": 12, "l": 12, "c": 12, "v": 100},
        ],
    }


def _build(tmp_path, payload, *, extra_query=""):
    archive = RawPointInTimeArtifactArchive(tmp_path / "raw")
    body = json.dumps(payload).encode()
    artifact = archive.admit(
        raw_bytes=body,
        source_uri=(
            "https://data.alpaca.markets/v2/stocks/T000/bars?"
            "timeframe=1Day&feed=iex&adjustment=all&"
            "start=2026-01-05T00:00:00Z&end=2026-01-08T00:00:00Z"
            + extra_query
        ),
        content_type="application/json",
        retrieved_at="2026-01-09T21:00:00+00:00",
    )
    window = build_source_bound_adjusted_price_window(
        archive=archive,
        raw_artifact=artifact,
        security_id="security-t000",
        symbol="T000",
        requested_start="2026-01-05",
        requested_end="2026-01-07",
        decision_cutoff="2026-01-09T21:00:00+00:00",
    )
    assert archive.read_bytes(artifact) == body
    return archive, artifact, window


def test_adjusted_window_accepts_single_symbol_rest_response(tmp_path):
    archive, artifact, window = _build(tmp_path, _payload())
    assert window.daily_closes == (
        ("2026-01-05", "10"),
        ("2026-01-06", "11"),
        ("2026-01-07", "12"),
    )
    assert verify_source_bound_adjusted_price_window(
        archive=archive, raw_artifact=artifact, value=window.to_dict()
    ).canonical_json_bytes() == window.canonical_json_bytes()


def test_adjusted_window_rejects_multi_shape_on_single_symbol_route(tmp_path):
    payload = _payload()
    payload["bars"] = {"T000": payload["bars"]}
    with pytest.raises(PointInTimeDataError):
        _build(tmp_path, payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("symbol", "OTHER"),
        ("symbol", None),
        ("next_page_token", "remaining-page"),
        ("next_page_token", ""),
        ("next_page_token", False),
        ("bars", None),
        ("bars", []),
    ],
)
def test_adjusted_window_rejects_mismatched_or_incomplete_rest_payload(tmp_path, field, value):
    payload = _payload()
    payload[field] = copy.deepcopy(value)
    with pytest.raises(PointInTimeDataError):
        _build(tmp_path, payload)


@pytest.mark.parametrize("field", ["symbol", "next_page_token", "bars"])
def test_adjusted_window_requires_rest_identity_and_page_fields(tmp_path, field):
    payload = _payload()
    del payload[field]
    with pytest.raises(PointInTimeDataError):
        _build(tmp_path, payload)


def test_adjusted_window_rejects_final_page_without_predecessor_pages(tmp_path):
    with pytest.raises(PointInTimeDataError):
        _build(tmp_path, _payload(), extra_query="&page_token=previous-page")
