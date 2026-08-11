from __future__ import annotations

import json

import pytest

from tradingagents.dataflows.alpaca_market_data import fetch_alpaca_latest_trades
from tradingagents.dataflows.alpaca_reference import (
    AlpacaReferenceError,
    collect_alpaca_reference_bundle,
    collect_alpaca_reference_stream,
    fetch_alpaca_reference,
    load_alpaca_reference_catalog,
    summarize_alpaca_reference_catalog,
)


class FakeResponse:
    def __init__(self, payload, *, status_code: int = 200, lines=()):
        self._payload = payload
        self.status_code = status_code
        self._lines = list(lines)
        self.text = json.dumps(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=False):
        del decode_unicode
        return iter(self._lines)

    def close(self):
        return None


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_catalog_is_complete_and_new_runtime_is_read_only():
    catalog = load_alpaca_reference_catalog()
    summary = summarize_alpaca_reference_catalog(catalog)

    assert summary["path_count"] == 83
    assert summary["operation_count"] == 99
    assert summary["method_counts"] == {
        "DELETE": 8,
        "GET": 77,
        "PATCH": 2,
        "POST": 10,
        "PUT": 2,
    }
    assert summary["api_counts"] == {
        "authentication": 1,
        "market_data": 44,
        "trading": 54,
    }
    assert all(
        endpoint["runtime_class"] in {"documented_mutation", "auth_only"}
        for endpoint in catalog["endpoints"]
        if endpoint["method"] != "GET"
    )


def test_fetch_rejects_mutation_and_unknown_route_before_network():
    session = FakeSession(FakeResponse({"unexpected": True}))

    with pytest.raises(AlpacaReferenceError, match="not callable"):
        fetch_alpaca_reference(
            "trading.patch.v2_orders_order_id",
            {"order_id": "abc"},
            session=session,
            api_key="paper-key",
            secret_key="paper-secret",
        )
    with pytest.raises(AlpacaReferenceError, match="Unknown Alpaca reference route"):
        fetch_alpaca_reference(
            "trading.get.arbitrary",
            session=session,
            api_key="paper-key",
            secret_key="paper-secret",
        )

    assert session.calls == []


def test_catalog_rejects_arbitrary_host_before_network(tmp_path):
    catalog = load_alpaca_reference_catalog()
    catalog["endpoints"][0]["host"] = "https://attacker.example"
    path = tmp_path / "malicious-catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    session = FakeSession(FakeResponse({"unexpected": True}))

    with pytest.raises(AlpacaReferenceError, match="host is not allowlisted"):
        fetch_alpaca_reference(
            "trading.get.v2_clock",
            catalog_path=path,
            session=session,
            api_key="paper-key",
            secret_key="paper-secret",
        )

    assert session.calls == []


def test_fetch_get_route_expands_path_and_records_feed_caveat():
    session = FakeSession(
        FakeResponse({"trade": {"S": "AAPL", "p": 220.5, "t": "2026-08-11T14:00:00Z"}})
    )

    packet = fetch_alpaca_reference(
        "market_data.get.v2_stocks_symbol_trades_latest",
        {"symbol": "AAPL", "feed": "iex"},
        session=session,
        api_key="paper-key",
        secret_key="paper-secret",
    )

    assert session.calls[0][0].endswith("/v2/stocks/AAPL/trades/latest")
    assert session.calls[0][1]["params"] == {"feed": "iex"}
    assert packet.analysis_only is True
    assert packet.freshness["execution_authority"] == "none"
    assert packet.payload["request_context"]["feed"] == "iex"
    assert packet.payload["semantic_caveats"][0].startswith("Latest-trade results")
    assert "submit_order" in packet.freshness["forbidden_effects"]


def test_bundle_does_not_poll_on_demand_or_stream_routes_by_default():
    session = FakeSession(FakeResponse({"timestamp": "2026-08-11T14:00:00Z"}))

    packets = collect_alpaca_reference_bundle(
        families=("trading", "market_data"),
        route_params={
            "trading.get.v2_clock": {},
            "market_data.get.v1beta1_news": {},
            "trading.get.v2beta1_events_activities": {},
        },
        session=session,
        api_key="paper-key",
        secret_key="paper-secret",
    )

    assert [packet.subject for packet in packets] == ["trading.get.v2_clock"]
    assert len(session.calls) == 1


def test_latest_trade_adapter_uses_explicit_feed_and_filtered_tape_caveat():
    session = FakeSession(FakeResponse({"trades": {"AAPL": {"p": 220.5}}}))

    packet = fetch_alpaca_latest_trades(
        ["AAPL"],
        feed="iex",
        session=session,
        api_key="paper-key",
        secret_key="paper-secret",
    )

    assert session.calls[0][1]["params"] == {"symbols": "AAPL", "feed": "iex"}
    assert packet.freshness["feed"] == "iex"
    assert "not a complete tape" in packet.payload["semantic_caveat"]


def test_streams_are_disabled_by_default_and_bounded_when_enabled():
    session = FakeSession(
        FakeResponse(
            {},
            lines=(
                b'data: {"event": 1}',
                b'data: {"event": 2}',
                b'data: {"event": 3}',
            ),
        )
    )

    with pytest.raises(AlpacaReferenceError, match="disabled by default"):
        collect_alpaca_reference_stream(
            "trading.get.v2beta1_events_activities",
            session=session,
            api_key="paper-key",
            secret_key="paper-secret",
        )
    assert session.calls == []

    packet = collect_alpaca_reference_stream(
        "trading.get.v2beta1_events_activities",
        enabled=True,
        max_events=2,
        timeout_seconds=2,
        session=session,
        api_key="paper-key",
        secret_key="paper-secret",
    )

    assert packet.payload["event_count"] == 2
    assert packet.freshness["bounded_stream"] is True
    assert packet.freshness["execution_authority"] == "none"
