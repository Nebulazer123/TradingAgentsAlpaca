import sys
from types import SimpleNamespace

from tradingagents.dataflows.yfinance_options import fetch_yfinance_options_iv_flow


class _FakeFrame:
    empty = False

    def __init__(self, rows):
        self._rows = rows

    def to_dict(self, orient):
        assert orient == "records"
        return list(self._rows)


class _FakeTicker:
    options = ["2026-06-05"]

    def __init__(self, symbol):
        self.symbol = symbol

    def option_chain(self, expiration):
        assert expiration == "2026-06-05"
        return SimpleNamespace(
            calls=_FakeFrame(
                [
                    {
                        "contractSymbol": f"{self.symbol}260605C00100000",
                        "strike": 100,
                        "bid": 1.0,
                        "ask": 1.2,
                        "volume": 20,
                        "openInterest": 100,
                        "impliedVolatility": 0.42,
                    }
                ]
            ),
            puts=_FakeFrame(
                [
                    {
                        "contractSymbol": f"{self.symbol}260605P00095000",
                        "strike": 95,
                        "bid": 0.8,
                        "ask": 1.0,
                        "volume": 10,
                        "openInterest": 50,
                        "impliedVolatility": 0.50,
                    }
                ]
            ),
        )


def test_fetch_yfinance_options_iv_flow_writes_analysis_only_packet(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(Ticker=lambda symbol: _FakeTicker(symbol)),
    )

    packet = fetch_yfinance_options_iv_flow("nvda")

    assert packet.source_name == "yfinance_options"
    assert packet.evidence_type == "options_iv_flow"
    assert packet.symbol == "NVDA"
    assert packet.quality == "low"
    assert packet.tool_route == "dataflow:yfinance_options"
    assert packet.analysis_only is True
    assert packet.payload["execution_authority"] == "none"
    assert packet.payload["put_call_volume_ratio_sample"] == 0.5
    assert packet.payload["put_call_open_interest_ratio_sample"] == 0.5
    assert packet.payload["call_iv_weighted_by_open_interest_sample"] == 0.42
    assert packet.payload["put_iv_weighted_by_open_interest_sample"] == 0.5
    assert packet.freshness["downrank_evidence"] is True
    assert packet.freshness["connector_status"] == "configured_public_supplemental"
