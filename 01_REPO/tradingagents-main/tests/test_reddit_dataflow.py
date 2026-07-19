import json
import time

import pytest

from tradingagents.dataflows import reddit, stocktwits
from tradingagents.dataflows._official_common import (
    DataTransportError,
    OfficialDataError,
)


def test_reddit_fetch_stops_after_public_endpoint_403(monkeypatch):
    calls = []

    def fake_get_text_response(url, **kwargs):
        calls.append((url, kwargs))
        raise DataTransportError("HTTP 403: blocked")

    monkeypatch.setattr(reddit, "get_text_response", fake_get_text_response)

    with pytest.raises(DataTransportError, match="HTTP 403"):
        reddit.fetch_reddit_posts(
            "CRM",
            subreddits=("wallstreetbets", "stocks", "investing"),
            timeout=0.01,
            inter_request_delay=0,
        )

    assert len(calls) == 1
    assert calls[0][1]["connector_name"] == "reddit_public"


def test_reddit_invalid_external_json_is_transport_failure(monkeypatch):
    class InvalidJsonResponse:
        text = "not JSON"

    monkeypatch.setattr(
        reddit,
        "get_text_response",
        lambda *_args, **_kwargs: InvalidJsonResponse(),
    )

    with pytest.raises(DataTransportError, match="invalid JSON"):
        reddit.fetch_reddit_posts(
            "CRM",
            subreddits=("stocks",),
            inter_request_delay=0,
        )


def test_reddit_terminal_dataflow_failure_propagates(monkeypatch):
    terminal_error = OfficialDataError("internal dataflow contract failure")

    def fail_terminal(*_args, **_kwargs):
        raise terminal_error

    monkeypatch.setattr(reddit, "get_text_response", fail_terminal)

    with pytest.raises(OfficialDataError) as exc_info:
        reddit.fetch_reddit_posts(
            "CRM",
            subreddits=("stocks",),
            inter_request_delay=0,
        )

    assert exc_info.value is terminal_error


def test_stocktwits_fetch_uses_shared_resilient_client(monkeypatch):
    calls = []
    payload = {
        "messages": [
            {
                "created_at": "2026-06-03T14:30:00Z",
                "user": {"username": "alpha"},
                "entities": {"sentiment": {"basic": "Bullish"}},
                "body": "CRM bounce setup",
            },
            {
                "created_at": "2026-06-03T14:31:00Z",
                "user": {"username": "beta"},
                "entities": {"sentiment": {"basic": "Bearish"}},
                "body": "CRM looks extended",
            },
        ]
    }

    def fake_get_text(url, **kwargs):
        calls.append((url, kwargs))
        return json.dumps(payload)

    monkeypatch.setattr(stocktwits, "get_text", fake_get_text)

    block = stocktwits.fetch_stocktwits_messages("CRM", limit=10, timeout=0.01)

    assert len(calls) == 1
    assert calls[0][1]["connector_name"] == "stocktwits_public"
    assert "Bullish: 1 (50%)" in block
    assert "Bearish: 1 (50%)" in block
    assert "@alpha" in block


def test_stocktwits_fetch_filters_to_requested_date_window(monkeypatch):
    payload = {
        "messages": [
            {
                "created_at": "2026-06-01T14:30:00Z",
                "user": {"username": "old"},
                "entities": {"sentiment": {"basic": "Bearish"}},
                "body": "CRM stale sell signal",
            },
            {
                "created_at": "2026-06-03T14:30:00Z",
                "user": {"username": "fresh"},
                "entities": {"sentiment": {"basic": "Bullish"}},
                "body": "CRM fresh dip buyer",
            },
        ]
    }

    monkeypatch.setattr(stocktwits, "get_text", lambda *_args, **_kwargs: json.dumps(payload))

    block = stocktwits.fetch_stocktwits_messages(
        "CRM",
        start_date="2026-06-03",
        end_date="2026-06-03",
    )

    assert "@fresh" in block
    assert "@old" not in block
    assert "2026-06-03 to 2026-06-03" in block


def test_stocktwits_fetch_degrades_on_shared_client_error(monkeypatch):
    def fake_get_text(_url, **_kwargs):
        raise OfficialDataError("HTTP 429: rate limited")

    monkeypatch.setattr(stocktwits, "get_text", fake_get_text)

    block = stocktwits.fetch_stocktwits_messages("CRM")

    assert block == "<stocktwits unavailable: OfficialDataError>"


def test_reddit_fetch_filters_posts_to_requested_date_window(monkeypatch):
    old_ts = int(time.mktime(time.strptime("2026-06-01", "%Y-%m-%d")))
    fresh_ts = int(time.mktime(time.strptime("2026-06-03", "%Y-%m-%d")))
    payload = {
        "data": {
            "children": [
                {"data": {"title": "CRM old chatter", "created_utc": old_ts, "score": 1}},
                {"data": {"title": "CRM fresh chatter", "created_utc": fresh_ts, "score": 2}},
            ]
        }
    }

    class FakeResponse:
        text = json.dumps(payload)

    calls = []

    def fake_get_text_response(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(reddit, "get_text_response", fake_get_text_response)

    block = reddit.fetch_reddit_posts(
        "CRM",
        subreddits=("stocks",),
        start_date="2026-06-03",
        end_date="2026-06-03",
        inter_request_delay=0,
    )

    assert "t=day" in calls[0][0]
    assert "CRM fresh chatter" in block
    assert "CRM old chatter" not in block
    assert "2026-06-03 to 2026-06-03" in block
