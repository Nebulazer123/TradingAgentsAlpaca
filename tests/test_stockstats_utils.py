import pandas as pd

from tradingagents.dataflows import stockstats_utils


def test_load_ohlcv_uses_documented_fifteen_year_cache_window(tmp_path, monkeypatch):
    calls = []

    def fake_download(symbol, **kwargs):
        calls.append({"symbol": symbol, **kwargs})
        frame = pd.DataFrame(
            {
                "Open": [10.0, 11.0, 12.0],
                "High": [10.5, 11.5, 12.5],
                "Low": [9.5, 10.5, 11.5],
                "Close": [10.25, 11.25, 12.25],
                "Volume": [1000, 2000, 3000],
            },
            index=pd.to_datetime(
                ["2016-06-03", "2016-06-06", pd.Timestamp.today().strftime("%Y-%m-%d")]
            ),
        )
        return frame.rename_axis("Date")

    monkeypatch.setattr(stockstats_utils, "get_config", lambda: {"data_cache_dir": str(tmp_path)})
    monkeypatch.setattr(stockstats_utils, "yf_retry", lambda func, **_kwargs: func())
    monkeypatch.setattr(stockstats_utils.yf, "download", fake_download)

    data = stockstats_utils.load_ohlcv("MSFT", "2016-06-03")

    expected_start = (
        pd.Timestamp.today() - pd.DateOffset(years=stockstats_utils.OHLCV_CACHE_HISTORY_YEARS)
    ).strftime("%Y-%m-%d")
    assert calls[0]["start"] == expected_start
    assert pd.Timestamp(calls[0]["start"]) <= pd.Timestamp("2016-06-03")
    assert calls[0]["end"] == (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    assert list(data["Date"].dt.strftime("%Y-%m-%d")) == ["2016-06-03"]
