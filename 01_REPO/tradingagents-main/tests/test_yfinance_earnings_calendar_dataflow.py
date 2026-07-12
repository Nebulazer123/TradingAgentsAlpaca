from __future__ import annotations

import sys
from types import SimpleNamespace

from tradingagents.dataflows.yfinance_earnings_calendar import fetch_yfinance_earnings_calendar


class FakeEarningsDatesFrame:
    empty = False

    def to_dict(self, orient: str):
        assert orient == "records"
        return [
            {
                "Earnings Date": "2026-07-21T20:00:00Z",
                "EPS Estimate": 1.23,
                "Reported EPS": None,
            }
        ]


class FakeTicker:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.calendar = {
            "Earnings Date": "2026-07-21",
            "Ex-Dividend Date": "2026-08-01",
        }

    def get_earnings_dates(self, limit: int):
        assert self.symbol == "CRM"
        assert limit == 2
        return FakeEarningsDatesFrame()


def test_yfinance_earnings_calendar_packet_is_read_only_and_downranked(monkeypatch):
    fake_yfinance = SimpleNamespace(Ticker=lambda symbol: FakeTicker(symbol))
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    packet = fetch_yfinance_earnings_calendar("crm", max_rows=2)

    assert packet.source_name == "yfinance_earnings_calendar"
    assert packet.evidence_type == "earnings_calendar"
    assert packet.symbol == "CRM"
    assert packet.analysis_only is True
    assert packet.payload["execution_authority"] == "none"
    assert packet.payload["earnings_date_count"] == 1
    assert packet.payload["calendar"]["Earnings Date"] == "2026-07-21"
    assert packet.freshness["downrank_evidence"] is True
    assert packet.tool_route == "dataflow:yfinance_earnings_calendar"
