from types import SimpleNamespace

import pytest

from tradingagents.dataflows._official_common import OfficialDataError
from tradingagents.dataflows.yfinance_short_interest import fetch_yfinance_short_interest


class _FakeTicker:
    def __init__(self, symbol: str):
        self.symbol = symbol

    def get_info(self):
        return {
            "sharesShort": 12000000,
            "sharesShortPriorMonth": 10000000,
            "dateShortInterest": 1780272000,
            "shortRatio": 2.4,
            "shortPercentOfFloat": 0.08,
            "sharesPercentSharesOut": 0.05,
            "floatShares": 150000000,
            "sharesOutstanding": 240000000,
        }


class _MetadataOnlyTicker:
    def __init__(self, symbol: str):
        self.symbol = symbol

    def get_info(self):
        return {
            "floatShares": 150000000,
            "sharesOutstanding": 240000000,
        }


def test_fetch_yfinance_short_interest_writes_analysis_only_packet(monkeypatch):
    fake_yfinance = SimpleNamespace(Ticker=_FakeTicker)
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yfinance)

    packet = fetch_yfinance_short_interest("nvda")

    assert packet.source_name == "yfinance_short_interest"
    assert packet.evidence_type == "short_interest"
    assert packet.symbol == "NVDA"
    assert packet.tool_route == "dataflow:yfinance_short_interest"
    assert packet.quality == "low"
    assert packet.analysis_only is True
    assert packet.payload["execution_authority"] == "none"
    assert packet.payload["shares_short"] == 12000000.0
    assert packet.payload["shares_short_delta"] == 2000000.0
    assert packet.payload["shares_short_delta_pct"] == 0.2
    assert packet.payload["short_percent_of_float"] == 0.08
    assert packet.freshness["downrank_evidence"] is True


def test_fetch_yfinance_short_interest_rejects_metadata_only_packet(monkeypatch):
    fake_yfinance = SimpleNamespace(Ticker=_MetadataOnlyTicker)
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yfinance)

    with pytest.raises(OfficialDataError, match="no short-interest fields"):
        fetch_yfinance_short_interest("qqq")
