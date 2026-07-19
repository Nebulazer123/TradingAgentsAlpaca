from __future__ import annotations

import pandas as pd
import pytest

from tradingagents.dataflows import stockstats_utils, y_finance
from tradingagents.dataflows._official_common import (
    DataUnavailableError,
    OfficialDataError,
    RecoverableDataflowError,
)


@pytest.mark.parametrize(
    ("latest_date", "as_of"),
    [
        ("2026-07-03", "2026-07-06"),
        ("2026-07-02", "2026-07-06"),
        ("2026-06-26", "2026-07-06"),
    ],
)
def test_validate_daily_ohlcv_accepts_daily_market_gaps_within_ten_days(latest_date, as_of):
    frame = pd.DataFrame({"Date": [latest_date], "Close": [100.0]})

    latest = stockstats_utils.validate_daily_ohlcv(frame, "yfinance", "MSFT", as_of)

    assert latest == pd.Timestamp(latest_date, tz="UTC")


@pytest.mark.parametrize(
    ("latest_date", "as_of", "expected_age"),
    [
        ("2026-06-25", "2026-07-06", "11 calendar days"),
        ("2025-07-06", "2026-07-06", "365 calendar days"),
    ],
)
def test_validate_daily_ohlcv_rejects_stale_observations(latest_date, as_of, expected_age):
    frame = pd.DataFrame({"Date": [latest_date], "Close": [100.0]})

    with pytest.raises(DataUnavailableError) as exc_info:
        stockstats_utils.validate_daily_ohlcv(frame, "yfinance", "MSFT", as_of)

    message = str(exc_info.value)
    assert "yfinance" in message
    assert "MSFT" in message
    assert f"requested as-of {as_of}" in message
    assert f"actual latest {latest_date}" in message
    assert expected_age in message


def test_validate_daily_ohlcv_rejects_future_observation():
    frame = pd.DataFrame({"Date": ["2026-07-07"], "Close": [100.0]})

    with pytest.raises(DataUnavailableError) as exc_info:
        stockstats_utils.validate_daily_ohlcv(frame, "yfinance", "MSFT", "2026-07-06")

    message = str(exc_info.value)
    assert "yfinance" in message
    assert "MSFT" in message
    assert "requested as-of 2026-07-06" in message
    assert "actual latest 2026-07-07" in message
    assert "after the requested as-of" in message


@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        (pd.DataFrame(), "empty OHLCV frame"),
        (pd.DataFrame({"Close": [100.0]}), "no parseable observation dates"),
        (
            pd.DataFrame({"Date": ["not-a-date"], "Close": [100.0]}),
            "no parseable observation dates",
        ),
    ],
)
def test_validate_daily_ohlcv_rejects_empty_or_dateless_frames(frame, reason):
    with pytest.raises(DataUnavailableError) as exc_info:
        stockstats_utils.validate_daily_ohlcv(frame, "yfinance", "MSFT", "2026-07-06")

    message = str(exc_info.value)
    assert "yfinance" in message
    assert "MSFT" in message
    assert "requested as-of 2026-07-06" in message
    assert reason in message


def test_validate_daily_ohlcv_uses_historical_as_of_instead_of_today():
    frame = pd.DataFrame({"Date": ["2016-06-03"], "Close": [100.0]})

    latest = stockstats_utils.validate_daily_ohlcv(frame, "yfinance", "MSFT", "2016-06-06")

    assert latest == pd.Timestamp("2016-06-03", tz="UTC")


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame(
            {"Close": [100.0]},
            index=pd.DatetimeIndex(["2026-07-03T20:00:00-04:00"], name="Datetime"),
        ),
        pd.DataFrame({"datetime": [pd.Timestamp("2026-07-03 20:00:00")], "Close": [100.0]}),
    ],
)
def test_validate_daily_ohlcv_compares_timezone_aware_and_naive_dates(frame):
    latest = stockstats_utils.validate_daily_ohlcv(frame, "yfinance", "MSFT", "2026-07-06")

    assert latest.tzinfo is not None
    assert latest.date().isoformat() in {"2026-07-03", "2026-07-04"}


def test_validate_daily_ohlcv_reads_datetime_column_exposed_by_reset_index():
    frame = pd.DataFrame({"index": [pd.Timestamp("2026-07-03")], "Close": [100.0]})

    latest = stockstats_utils.validate_daily_ohlcv(frame, "yfinance", "MSFT", "2026-07-06")

    assert latest == pd.Timestamp("2026-07-03", tz="UTC")


def test_validate_daily_ohlcv_rejects_invalid_requested_as_of():
    frame = pd.DataFrame({"Date": ["2026-07-03"], "Close": [100.0]})

    with pytest.raises(OfficialDataError) as exc_info:
        stockstats_utils.validate_daily_ohlcv(frame, "yfinance", "MSFT", "not-a-date")

    assert not isinstance(exc_info.value, RecoverableDataflowError)
    message = str(exc_info.value)
    assert "yfinance" in message
    assert "MSFT" in message
    assert "requested as-of not-a-date" in message
    assert "invalid requested as-of" in message


def test_get_yfin_data_online_uses_inclusive_end_and_preserves_symbol_and_header(
    monkeypatch,
):
    calls = []

    class FakeTicker:
        def __init__(self, symbol):
            calls.append({"symbol": symbol})

        def history(self, **kwargs):
            calls[-1].update(kwargs)
            return pd.DataFrame(
                {"Open": [10.0], "High": [11.0], "Low": [9.0], "Close": [10.5]},
                index=pd.DatetimeIndex(["2026-07-02T00:00:00-04:00"], name="Date"),
            )

    monkeypatch.setattr(y_finance.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(y_finance, "yf_retry", lambda func, **_kwargs: func())

    result = y_finance.get_YFin_data_online("XAUUSD", "2026-06-01", "2026-07-06")

    assert calls == [{"symbol": "XAUUSD", "start": "2026-06-01", "end": "2026-07-07"}]
    assert "# Stock data for XAUUSD from 2026-06-01 to 2026-07-06" in result
    assert "2026-07-02" in result


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame(
            {"Close": [10.5]},
            index=pd.DatetimeIndex(["2025-07-06"], name="Date"),
        ),
        pd.DataFrame(),
    ],
)
def test_get_yfin_data_online_raises_when_history_is_unusable(monkeypatch, frame):
    class FakeTicker:
        def __init__(self, _symbol):
            pass

        def history(self, **_kwargs):
            return frame

    monkeypatch.setattr(y_finance.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(y_finance, "yf_retry", lambda func, **_kwargs: func())

    with pytest.raises(OfficialDataError):
        y_finance.get_YFin_data_online("MSFT", "2026-06-01", "2026-07-06")


@pytest.mark.parametrize(
    ("start_date", "end_date", "reason"),
    [
        ("bad-start", "2026-07-06", "invalid start_date bad-start"),
        ("2026-06-01", "bad-end", "invalid end_date bad-end"),
        ("2026-07-07", "2026-07-06", "start_date must be on or before end_date"),
    ],
)
def test_get_yfin_data_online_rejects_invalid_date_range(monkeypatch, start_date, end_date, reason):
    monkeypatch.setattr(
        y_finance.yf,
        "Ticker",
        lambda _symbol: pytest.fail("invalid dates must fail before yfinance is called"),
    )

    with pytest.raises(OfficialDataError) as exc_info:
        y_finance.get_YFin_data_online("MSFT", start_date, end_date)

    message = str(exc_info.value)
    assert "yfinance" in message
    assert "MSFT" in message
    assert f"requested as-of {end_date}" in message
    assert reason in message


def test_load_ohlcv_rejects_stale_download_before_cache_write(tmp_path, monkeypatch):
    stale = pd.DataFrame(
        {"Open": [10.0], "High": [11.0], "Low": [9.0], "Close": [10.5], "Volume": [100]},
        index=pd.DatetimeIndex([pd.Timestamp.today() - pd.Timedelta(days=365)], name="Date"),
    )
    monkeypatch.setattr(stockstats_utils, "get_config", lambda: {"data_cache_dir": str(tmp_path)})
    monkeypatch.setattr(stockstats_utils, "yf_retry", lambda func, **_kwargs: func())
    monkeypatch.setattr(stockstats_utils.yf, "download", lambda *_args, **_kwargs: stale)

    with pytest.raises(OfficialDataError, match="yfinance.*actual latest"):
        stockstats_utils.load_ohlcv("MSFT", pd.Timestamp.today().strftime("%Y-%m-%d"))

    assert list(tmp_path.glob("*.csv")) == []


def test_load_ohlcv_rejects_stale_cached_frame(tmp_path, monkeypatch):
    stale = pd.DataFrame(
        {
            "Date": [(pd.Timestamp.today() - pd.Timedelta(days=365)).strftime("%Y-%m-%d")],
            "Open": [10.0],
            "High": [11.0],
            "Low": [9.0],
            "Close": [10.5],
            "Volume": [100],
        }
    )
    monkeypatch.setattr(stockstats_utils, "get_config", lambda: {"data_cache_dir": str(tmp_path)})
    monkeypatch.setattr(stockstats_utils.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(stockstats_utils.pd, "read_csv", lambda *_args, **_kwargs: stale)
    monkeypatch.setattr(
        stockstats_utils.yf,
        "download",
        lambda *_args, **_kwargs: pytest.fail("cache hit must not download"),
    )

    with pytest.raises(OfficialDataError, match="yfinance cache.*actual latest"):
        stockstats_utils.load_ohlcv("MSFT", pd.Timestamp.today().strftime("%Y-%m-%d"))


def test_load_ohlcv_rejects_empty_cached_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(stockstats_utils, "get_config", lambda: {"data_cache_dir": str(tmp_path)})
    monkeypatch.setattr(stockstats_utils.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(
        stockstats_utils.pd,
        "read_csv",
        lambda *_args, **_kwargs: pd.DataFrame(columns=["Date", "Close"]),
    )
    monkeypatch.setattr(
        stockstats_utils.yf,
        "download",
        lambda *_args, **_kwargs: pytest.fail("cache hit must not download"),
    )

    with pytest.raises(OfficialDataError, match="yfinance cache.*empty OHLCV frame"):
        stockstats_utils.load_ohlcv("MSFT", pd.Timestamp.today().strftime("%Y-%m-%d"))
