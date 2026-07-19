from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from tradingagents.dataflows._official_common import (
    DataUnavailableError,
    OfficialDataError,
    RecoverableDataflowError,
)
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


def test_yfinance_earnings_calendar_without_usable_dates_is_unavailable(monkeypatch):
    ticker = SimpleNamespace(calendar={}, get_earnings_dates=lambda **_kwargs: None)
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(Ticker=lambda _symbol: ticker),
    )

    with pytest.raises(DataUnavailableError, match="no earnings calendar data"):
        fetch_yfinance_earnings_calendar("CRM")


def test_yfinance_earnings_calendar_missing_symbol_remains_terminal(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(Ticker=lambda _symbol: pytest.fail("ticker must not be built")),
    )

    with pytest.raises(OfficialDataError, match="ticker symbol") as exc_info:
        fetch_yfinance_earnings_calendar("")

    assert not isinstance(exc_info.value, RecoverableDataflowError)


@pytest.mark.parametrize(
    "error",
    [
        TypeError("provider contract failure"),
        AssertionError("provider invariant failure"),
        OfficialDataError("malformed provider evidence"),
    ],
)
def test_yfinance_earnings_dates_failure_propagates_unchanged(monkeypatch, error):
    def fail_dates(**_kwargs):
        raise error

    ticker = SimpleNamespace(
        calendar={"Earnings Date": "2026-07-21"},
        get_earnings_dates=fail_dates,
    )
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(Ticker=lambda _symbol: ticker),
    )

    with pytest.raises(type(error)) as exc_info:
        fetch_yfinance_earnings_calendar("CRM")

    assert exc_info.value is error


def test_yfinance_calendar_object_serialization_failure_propagates(monkeypatch):
    error = AssertionError("calendar serialization invariant failure")

    class BrokenCalendar:
        def to_dict(self):
            raise error

    ticker = SimpleNamespace(calendar=BrokenCalendar())
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(Ticker=lambda _symbol: ticker),
    )

    with pytest.raises(AssertionError) as exc_info:
        fetch_yfinance_earnings_calendar("CRM")

    assert exc_info.value is error


def test_yfinance_calendar_scalar_normalization_failure_propagates(monkeypatch):
    error = OfficialDataError("calendar scalar contract failure")

    class BrokenScalar:
        def item(self):
            raise error

    ticker = SimpleNamespace(calendar={"Earnings Date": BrokenScalar()})
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(Ticker=lambda _symbol: ticker),
    )

    with pytest.raises(OfficialDataError) as exc_info:
        fetch_yfinance_earnings_calendar("CRM")

    assert exc_info.value is error
