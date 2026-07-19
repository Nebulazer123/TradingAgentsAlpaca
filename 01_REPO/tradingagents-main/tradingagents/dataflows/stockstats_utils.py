import logging
import os
import time
from typing import Annotated

import pandas as pd
import yfinance as yf
from stockstats import wrap
from yfinance.exceptions import YFRateLimitError

from ._official_common import OfficialDataError
from .config import get_config
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)
OHLCV_CACHE_HISTORY_YEARS = 15


def _daily_timestamp(value) -> pd.Timestamp | None:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_localize(None)
    return timestamp.normalize().tz_localize("UTC")


def validate_daily_ohlcv(
    frame: pd.DataFrame,
    vendor: str,
    symbol: str,
    requested_as_of,
    max_stale_days: int = 10,
) -> pd.Timestamp:
    """Return the latest usable daily observation or raise a typed data error."""
    as_of = _daily_timestamp(requested_as_of)
    requested_label = (
        as_of.date().isoformat() if as_of is not None else str(requested_as_of)
    )
    context = f"{vendor} daily OHLCV for {symbol} requested as-of {requested_label}"
    if as_of is None:
        raise OfficialDataError(f"{context}: invalid requested as-of date")
    if frame is None or frame.empty:
        raise OfficialDataError(f"{context}: empty OHLCV frame")

    date_columns = {
        column
        for column in frame.columns
        if str(column).strip().casefold()
        in {"date", "datetime", "timestamp", "index"}
    }
    values = []
    for column in date_columns:
        values.extend(frame[column].tolist())
    if isinstance(frame.index, pd.DatetimeIndex):
        values.extend(frame.index.tolist())

    observations = []
    for value in values:
        timestamp = _daily_timestamp(value)
        if timestamp is not None:
            observations.append(timestamp)
    if not observations:
        raise OfficialDataError(f"{context}: no parseable observation dates")

    latest = max(observations)
    latest_label = latest.date().isoformat()
    if latest > as_of:
        raise OfficialDataError(
            f"{context}; actual latest {latest_label}: latest observation is "
            "after the requested as-of date"
        )
    age_days = (as_of - latest).days
    if age_days > max_stale_days:
        raise OfficialDataError(
            f"{context}; actual latest {latest_label}: latest observation is "
            f"{age_days} calendar days before requested as-of; maximum is "
            f"{max_stale_days}"
        )
    return latest


def yf_retry(func, max_retries=3, base_delay=2.0):
    """Execute a yfinance call with exponential backoff on rate limits.

    yfinance raises YFRateLimitError on HTTP 429 responses but does not
    retry them internally. This wrapper adds retry logic specifically
    for rate limits. Other exceptions propagate immediately.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Yahoo Finance rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize a stock DataFrame for stockstats: parse dates, drop invalid rows, fill price gaps."""
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["Close"])
    data[price_cols] = data[price_cols].ffill().bfill()

    return data


def load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV data with caching, filtered to prevent look-ahead bias.

    Downloads 15 years of data up to today and caches per symbol. On
    subsequent calls the cache is reused. Rows after curr_date are
    filtered out so backtests never see future prices.
    """
    # Reject ticker values that would escape the cache directory when
    # interpolated into the cache filename (e.g. ``../../tmp/x``).
    safe_symbol = safe_ticker_component(symbol)

    config = get_config()
    curr_date_dt = _daily_timestamp(curr_date)
    if curr_date_dt is None:
        raise OfficialDataError(
            f"yfinance daily OHLCV for {symbol} requested as-of {curr_date}: "
            "invalid requested as-of date"
        )

    # Cache uses a fixed window (15y to today) so one file per symbol
    today_date = pd.Timestamp.today().normalize()
    start_date = today_date - pd.DateOffset(years=OHLCV_CACHE_HISTORY_YEARS)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = (today_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{safe_symbol}-YFin-data-{start_str}-{end_str}.csv",
    )

    if os.path.exists(data_file):
        data = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
        vendor = "yfinance cache"
    else:
        data = yf_retry(lambda: yf.download(
            symbol,
            start=start_str,
            end=end_str,
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        ))
        data = data.reset_index()
        validate_daily_ohlcv(data, "yfinance", symbol, today_date)
        data.to_csv(data_file, index=False, encoding="utf-8")
        vendor = "yfinance"

    if "Date" not in data.columns:
        date_column = next(
            (
                column
                for column in data.columns
                if str(column).strip().casefold()
                in {"date", "datetime", "timestamp", "index"}
            ),
            None,
        )
        if date_column is None:
            validate_daily_ohlcv(data, vendor, symbol, curr_date_dt)
        data = data.rename(columns={date_column: "Date"})
    data = _clean_dataframe(data)
    if data.empty:
        validate_daily_ohlcv(data, vendor, symbol, curr_date_dt)

    # Filter to curr_date to prevent look-ahead bias in backtesting
    observation_dates = data["Date"].map(_daily_timestamp)
    data = data[observation_dates <= curr_date_dt]
    validate_daily_ohlcv(data, vendor, symbol, curr_date_dt)

    return data


def filter_financials_by_date(data: pd.DataFrame, curr_date: str) -> pd.DataFrame:
    """Drop financial statement columns (fiscal period timestamps) after curr_date.

    yfinance financial statements use fiscal period end dates as columns.
    Columns after curr_date represent future data and are removed to
    prevent look-ahead bias.
    """
    if not curr_date or data.empty:
        return data
    cutoff = pd.Timestamp(curr_date)
    mask = pd.to_datetime(data.columns, errors="coerce") <= cutoff
    return data.loc[:, mask]


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "ticker symbol for the company"],
        indicator: Annotated[
            str, "quantitative indicators based off of the stock data for the company"
        ],
        curr_date: Annotated[
            str, "curr date for retrieving stock price data, YYYY-mm-dd"
        ],
    ):
        data = load_ohlcv(symbol, curr_date)
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")

        df[indicator]  # trigger stockstats to calculate the indicator
        matching_rows = df[df["Date"].str.startswith(curr_date_str)]

        if not matching_rows.empty:
            indicator_value = matching_rows[indicator].values[0]
            return indicator_value
        else:
            return "N/A: Not a trading day (weekend or holiday)"
