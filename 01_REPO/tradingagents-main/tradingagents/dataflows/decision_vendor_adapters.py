"""Decision-path adapters for supplemental evidence vendors.

The original TradingAgents analyst tools expect strings/CSV-like blocks. The
optional vendor modules in this repo return structured SourceEvidencePacket
objects. These adapters bridge that shape without changing analyst prompts or
granting any source execution authority.
"""

from __future__ import annotations

import csv
import io
import json
import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from tradingagents.research.release_calendar import build_release_calendar_packet
from tradingagents.schemas.research import SourceEvidencePacket

from ._official_common import SECRET_PARAM_NAMES, DataUnavailableError, OfficialDataError
from .alpaca_news import fetch_alpaca_news
from .bea import fetch_bea_data
from .bls import fetch_bls_timeseries
from .eia import fetch_eia_route
from .eodhd import fetch_eodhd_fundamentals, fetch_eodhd_news, fetch_eodhd_sentiments
from .finnhub import (
    fetch_finnhub_basic_financials,
    fetch_finnhub_company_news,
    fetch_finnhub_profile2,
)
from .fmp import (
    fetch_fmp_company_profile,
    fetch_fmp_latest_earning_call_transcript,
    fetch_fmp_route,
    fetch_fmp_stock_news,
)
from .fred import fetch_fred_series_observations
from .google_news import fetch_google_news_rss
from .marketaux import fetch_marketaux_news
from .massive import fetch_massive_daily_prices
from .newsapi import fetch_newsapi_everything
from .reddit import fetch_reddit_posts
from .sec import fetch_sec_company_tickers, fetch_sec_companyfacts, fetch_sec_submissions
from .stocktwits import fetch_stocktwits_messages
from .tiingo import fetch_tiingo_daily_prices, fetch_tiingo_news
from .treasury_fiscal import fetch_treasury_fiscal
from .yfinance_earnings_calendar import fetch_yfinance_earnings_calendar
from .yfinance_options import fetch_yfinance_options_iv_flow
from .yfinance_short_interest import fetch_yfinance_short_interest


def _packet_payload_preview(packet: SourceEvidencePacket, *, max_chars: int = 4_000) -> str:
    text = json.dumps(packet.payload, indent=2, sort_keys=True, default=str)
    if len(text) > max_chars:
        return text[: max_chars - 30] + "\n...<truncated for analyst context>"
    return text


def _render_packet(packet: SourceEvidencePacket, *, title: str | None = None) -> str:
    refs = "\n".join(f"- {ref}" for ref in packet.source_refs[:5]) or "- <none>"
    return (
        f"## {title or packet.source_name} ({packet.evidence_type})\n"
        f"Source: {packet.source_name}\n"
        f"Subject: {packet.subject}\n"
        f"Symbol: {packet.symbol or 'n/a'}\n"
        f"Quality: {packet.quality}\n"
        f"As of: {packet.as_of or packet.generated_at}\n"
        f"Execution authority: none (research evidence only)\n"
        f"Source refs:\n{refs}\n\n"
        f"Payload preview:\n{_packet_payload_preview(packet)}"
    )


AS_OF_DATE_FIELDS = (
    "date",
    "filingDate",
    "reportDate",
    "accepted",
    "acceptanceDateTime",
    "end",
    "fiscalDateEnding",
    "publishedDate",
)


def _parse_payload_date(value: Any) -> datetime.date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def _row_after_as_of(row: dict[str, Any], as_of_date: datetime.date) -> bool:
    for field in AS_OF_DATE_FIELDS:
        parsed = _parse_payload_date(row.get(field))
        if parsed and parsed > as_of_date:
            return True
    return False


def _filter_payload_as_of(value: Any, as_of_date: datetime.date) -> Any:
    if isinstance(value, list):
        filtered = []
        for item in value:
            if isinstance(item, dict) and _row_after_as_of(item, as_of_date):
                continue
            filtered.append(_filter_payload_as_of(item, as_of_date))
        return filtered
    if isinstance(value, dict):
        filtered_dict: dict[str, Any] = {}
        for key, item in value.items():
            key_date = _parse_payload_date(str(key))
            if key_date and key_date > as_of_date:
                continue
            if isinstance(item, dict) and _row_after_as_of(item, as_of_date):
                continue
            filtered_dict[str(key)] = _filter_payload_as_of(item, as_of_date)
        return filtered_dict
    return value


def _filter_sec_recent_columnar(payload: dict[str, Any], as_of_date: datetime.date) -> dict[str, Any]:
    recent = (
        payload.get("filings", {}).get("recent")
        if isinstance(payload.get("filings"), dict)
        else None
    )
    if not isinstance(recent, dict):
        return payload
    date_column = None
    for field in ("filingDate", "reportDate", "acceptanceDateTime"):
        values = recent.get(field)
        if isinstance(values, list):
            date_column = values
            break
    if not date_column:
        return payload
    keep_indices = [
        index
        for index, value in enumerate(date_column)
        if (parsed := _parse_payload_date(value)) is None or parsed <= as_of_date
    ]
    row_count = len(date_column)
    for key, values in list(recent.items()):
        if isinstance(values, list) and len(values) == row_count:
            recent[key] = [values[index] for index in keep_indices]
    return payload


def _packet_filtered_as_of(packet: SourceEvidencePacket, curr_date: str | None) -> SourceEvidencePacket:
    if not curr_date:
        return packet
    as_of_date = datetime.fromisoformat(curr_date.replace("Z", "+00:00")).date()
    payload = _filter_payload_as_of(deepcopy(packet.payload), as_of_date)
    if isinstance(payload, dict):
        payload = _filter_sec_recent_columnar(payload, as_of_date)
        payload["as_of_filter"] = {
            "curr_date": curr_date,
            "policy": "drop rows or date-keyed sections after curr_date for analyst rendering",
        }
    freshness = {
        **packet.freshness,
        "as_of_filter": {"curr_date": curr_date},
    }
    return packet.model_copy(update={"payload": payload, "as_of": curr_date, "freshness": freshness})


def _date_window(curr_date: str, look_back_days: int | None) -> tuple[str, str]:
    days = 7 if look_back_days is None else max(1, int(look_back_days))
    end = datetime.strptime(curr_date, "%Y-%m-%d")
    start = end - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _year_window(curr_date: str, look_back_days: int | None) -> tuple[int, int]:
    start_date, end_date = _date_window(curr_date, look_back_days or 365)
    return datetime.strptime(start_date, "%Y-%m-%d").year, datetime.strptime(end_date, "%Y-%m-%d").year


def _symbol(value: str) -> str:
    return value.strip().upper()


def get_marketaux_news(ticker: str, start_date: str, end_date: str) -> str:
    packet = fetch_marketaux_news(symbols=[_symbol(ticker)], published_after=start_date, published_before=end_date)
    return _render_packet(packet, title=f"Marketaux news for {_symbol(ticker)}")


def get_marketaux_global_news(curr_date: str, look_back_days: int | None = None, limit: int | None = None) -> str:
    start_date, end_date = _date_window(curr_date, look_back_days)
    packet = fetch_marketaux_news(
        search="stock market OR economy OR Federal Reserve OR earnings",
        published_after=start_date,
        published_before=end_date,
        limit=limit or 50,
    )
    return _render_packet(packet, title="Marketaux global market news")


def get_finnhub_news(ticker: str, start_date: str, end_date: str) -> str:
    packet = fetch_finnhub_company_news(_symbol(ticker), from_date=start_date, to_date=end_date)
    return _render_packet(packet, title=f"Finnhub company news for {_symbol(ticker)}")


def get_finnhub_fundamentals(ticker: str, curr_date: str | None = None) -> str:
    profile = fetch_finnhub_profile2(_symbol(ticker))
    metrics = fetch_finnhub_basic_financials(_symbol(ticker))
    return "\n\n".join(
        [
            _render_packet(profile, title=f"Finnhub profile for {_symbol(ticker)}"),
            _render_packet(metrics, title=f"Finnhub basic financials for {_symbol(ticker)}"),
        ]
    )


def _sec_cik_for_symbol(ticker: str) -> str:
    symbol = _symbol(ticker)
    if not symbol or re.fullmatch(r"[A-Z0-9][A-Z0-9.-]*", symbol) is None:
        raise ValueError("ticker must be a non-empty SEC symbol")
    packet = fetch_sec_company_tickers()
    payload = packet.payload
    if not isinstance(payload, dict):
        raise OfficialDataError("SEC company-ticker payload must be a dictionary")
    entries = payload.values()
    for entry in entries:
        if not isinstance(entry, dict):
            raise OfficialDataError(
                "SEC company-ticker payload contains a malformed entry"
            )
        entry_symbol = str(entry.get("ticker") or "").strip().upper()
        cik = str(entry.get("cik_str") or "").strip()
        if not entry_symbol or not cik.isdigit():
            raise OfficialDataError(
                "SEC company-ticker payload contains an invalid ticker or CIK entry"
            )
        if entry_symbol == symbol:
            return cik
    raise DataUnavailableError(f"SEC CIK not found for ticker {symbol}")


def get_sec_fundamentals(ticker: str, curr_date: str | None = None) -> str:
    symbol = _symbol(ticker)
    cik = _sec_cik_for_symbol(symbol)
    facts = _packet_filtered_as_of(fetch_sec_companyfacts(cik, symbol=symbol, as_of=curr_date), curr_date)
    submissions = _packet_filtered_as_of(fetch_sec_submissions(cik, symbol=symbol, as_of=curr_date), curr_date)
    return "\n\n".join(
        [
            _render_packet(facts, title=f"SEC company facts for {symbol}"),
            _render_packet(submissions, title=f"SEC submissions for {symbol}"),
        ]
    )


def get_fmp_fundamentals(ticker: str, curr_date: str | None = None) -> str:
    packet = _packet_filtered_as_of(fetch_fmp_company_profile(_symbol(ticker)), curr_date)
    return _render_packet(packet, title=f"FMP company profile for {_symbol(ticker)}")


def _fmp_statement(ticker: str, endpoint: str, freq: str, curr_date: str | None, title: str) -> str:
    period = "quarter" if str(freq or "").lower().startswith("q") else "annual"
    packet = fetch_fmp_route(
        endpoint,
        params={"symbol": _symbol(ticker), "period": period, "limit": 8},
        evidence_type=endpoint.replace("-", "_"),
        subject=_symbol(ticker),
        symbol=_symbol(ticker),
    )
    packet = _packet_filtered_as_of(packet, curr_date)
    return _render_packet(packet, title=f"FMP {title} for {_symbol(ticker)}")


def get_fmp_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    return _fmp_statement(ticker, "balance-sheet-statement", freq, curr_date, "balance sheet")


def get_fmp_cashflow(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    return _fmp_statement(ticker, "cash-flow-statement", freq, curr_date, "cash flow")


def get_fmp_income_statement(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    return _fmp_statement(ticker, "income-statement", freq, curr_date, "income statement")


def get_fmp_news(ticker: str, start_date: str, end_date: str) -> str:
    packet = fetch_fmp_stock_news([_symbol(ticker)], from_date=start_date, to_date=end_date)
    return _render_packet(packet, title=f"FMP stock news for {_symbol(ticker)}")


def get_eodhd_fundamentals(ticker: str, curr_date: str | None = None) -> str:
    packet = _packet_filtered_as_of(fetch_eodhd_fundamentals(_symbol(ticker)), curr_date)
    return _render_packet(packet, title=f"EODHD fundamentals for {_symbol(ticker)}")


def get_eodhd_news(ticker: str, start_date: str, end_date: str) -> str:
    packet = fetch_eodhd_news(symbol=_symbol(ticker), from_date=start_date, to_date=end_date)
    return _render_packet(packet, title=f"EODHD news for {_symbol(ticker)}")


def get_newsapi_news(ticker: str, start_date: str, end_date: str) -> str:
    packet = fetch_newsapi_everything(
        f'"{_symbol(ticker)}" stock OR earnings OR guidance',
        from_date=start_date,
        to_date=end_date,
        symbol=_symbol(ticker),
    )
    return _render_packet(packet, title=f"NewsAPI news for {_symbol(ticker)}")


def get_google_news(ticker: str, start_date: str, end_date: str) -> str:
    packet = fetch_google_news_rss(
        query=f"{_symbol(ticker)} stock earnings guidance",
        limit=25,
        start_date=start_date,
        end_date=end_date,
    )
    return _render_packet(packet, title=f"Google News RSS for {_symbol(ticker)}")


def get_google_global_news(curr_date: str, look_back_days: int | None = None, limit: int | None = None) -> str:
    start_date = None
    if look_back_days is not None:
        current = datetime.fromisoformat(curr_date.replace("Z", "+00:00"))
        start_date = (current.date() - timedelta(days=max(0, int(look_back_days)))).isoformat()
    packet = fetch_google_news_rss(
        query="stock market economy Federal Reserve earnings",
        limit=limit or 25,
        start_date=start_date,
        end_date=curr_date,
    )
    return _render_packet(packet, title="Google News RSS global market news")


def get_alpaca_news_adapter(ticker: str, start_date: str, end_date: str) -> str:
    packet = fetch_alpaca_news(symbols=[_symbol(ticker)], start=start_date, end=end_date)
    return _render_packet(packet, title=f"Alpaca read-only news for {_symbol(ticker)}")


def get_tiingo_news_adapter(ticker: str, start_date: str, end_date: str) -> str:
    packet = fetch_tiingo_news(tickers=[_symbol(ticker)], start_date=start_date, end_date=end_date)
    return _render_packet(packet, title=f"Tiingo news for {_symbol(ticker)}")


def get_tiingo_stock_data(ticker: str, start_date: str, end_date: str) -> str:
    packet = fetch_tiingo_daily_prices(_symbol(ticker), start_date=start_date, end_date=end_date)
    rows = packet.payload.get("data")
    if not isinstance(rows, list) or not rows:
        return ""
    csv_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        csv_rows.append(
            {
                "Date": row.get("date"),
                "Open": row.get("open"),
                "High": row.get("high"),
                "Low": row.get("low"),
                "Close": row.get("close"),
                "Adj Close": row.get("adjClose") or row.get("adj_close"),
                "Volume": row.get("volume"),
            }
        )
    if not csv_rows:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(csv_rows[0].keys()))
    writer.writeheader()
    writer.writerows(csv_rows)
    return f"# Tiingo daily prices for {_symbol(ticker)} from {start_date} to {end_date}\n{output.getvalue()}"


def get_massive_stock_data(ticker: str, start_date: str, end_date: str) -> str:
    packet = fetch_massive_daily_prices(_symbol(ticker), start_date=start_date, end_date=end_date)
    rows = packet.payload.get("results")
    if not isinstance(rows, list) or not rows:
        return ""
    csv_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp = row.get("t")
        date = ""
        if isinstance(timestamp, (int, float)):
            date = datetime.fromtimestamp(timestamp / 1000, tz=UTC).date().isoformat()
        csv_rows.append(
            {
                "Date": date or row.get("date") or row.get("from"),
                "Open": row.get("o"),
                "High": row.get("h"),
                "Low": row.get("l"),
                "Close": row.get("c"),
                "Adj Close": row.get("c"),
                "Volume": row.get("v"),
            }
        )
    if not csv_rows:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(csv_rows[0].keys()))
    writer.writeheader()
    writer.writerows(csv_rows)
    return f"# Massive daily prices for {_symbol(ticker)} from {start_date} to {end_date}\n{output.getvalue()}"


def get_fred_macro_context(curr_date: str, look_back_days: int | None = None, limit: int | None = None) -> str:
    start_date, end_date = _date_window(curr_date, look_back_days or 365)
    series_ids = ("FEDFUNDS", "DGS10", "CPIAUCSL", "UNRATE")
    packets = [
        fetch_fred_series_observations(
            series_id,
            observation_start=start_date,
            observation_end=end_date,
            sort_order="desc",
            limit=limit or 5,
        )
        for series_id in series_ids
    ]
    return "\n\n".join(
        _render_packet(packet, title=f"FRED macro context: {packet.subject}") for packet in packets
    )


def get_bls_macro_context(curr_date: str, look_back_days: int | None = None, limit: int | None = None) -> str:
    del limit
    start_year, end_year = _year_window(curr_date, look_back_days)
    packet = fetch_bls_timeseries(
        ["CUUR0000SA0", "LNS14000000"],
        start_year=start_year,
        end_year=end_year,
    )
    return _render_packet(packet, title="BLS macro context: CPI and unemployment")


def get_bea_macro_context(curr_date: str, look_back_days: int | None = None, limit: int | None = None) -> str:
    del limit
    start_year, end_year = _year_window(curr_date, look_back_days)
    packets = [
        fetch_bea_data(
            "NIPA",
            TableName="T10101",
            Frequency="Q",
            Year=str(year),
            LineNumber="1",
        )
        for year in range(start_year, end_year + 1)
    ]
    return "\n\n".join(
        _render_packet(packet, title=f"BEA macro context: GDP {packet.payload.get('year', '')}".strip())
        for packet in packets
    )


def _as_of_date_window(curr_date: str, look_back_days: int | None) -> tuple[str | None, str]:
    current = datetime.fromisoformat(curr_date.replace("Z", "+00:00")).date()
    if look_back_days is None:
        return None, current.isoformat()
    start = current - timedelta(days=max(0, int(look_back_days)))
    return start.isoformat(), current.isoformat()


def get_eia_energy_macro_context(curr_date: str, look_back_days: int | None = None, limit: int | None = None) -> str:
    start_date, end_date = _as_of_date_window(curr_date, look_back_days)
    eia_params = {
        "data[0]": "value",
        "facets[seriesId][]": "WTIPUUS",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": limit or 12,
        "end": end_date[:7],
        "as_of": end_date,
    }
    if start_date:
        eia_params["start"] = start_date[:7]
    packet = fetch_eia_route(
        "steo/data/",
        frequency="monthly",
        **eia_params,
    )
    return _render_packet(packet, title="EIA macro context: WTI crude oil STEO")


def get_treasury_macro_context(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    start_date, end_date = _as_of_date_window(curr_date, look_back_days)
    filters = [f"record_date:lte:{end_date}"]
    if start_date:
        filters.insert(0, f"record_date:gte:{start_date}")
    packet = fetch_treasury_fiscal(
        "v2/accounting/od/avg_interest_rates",
        filter=",".join(filters),
        sort="-record_date",
        as_of=end_date,
        **{"page[size]": limit or 5},
    )
    return _render_packet(packet, title="Treasury FiscalData macro context")


def _render_text_context(*, title: str, source: str, subject: str, body: str) -> str:
    return (
        f"## {title}\n"
        f"Source: {source}\n"
        f"Subject: {subject}\n"
        f"Quality: supplemental\n"
        f"Execution authority: none (research evidence only)\n\n"
        f"{body.strip() or '<no usable data returned>'}"
    )


def get_stocktwits_sentiment_context(ticker: str, start_date: str, end_date: str) -> str:
    symbol = _symbol(ticker)
    return _render_text_context(
        title=f"StockTwits sentiment context for {symbol}",
        source="stocktwits",
        subject=symbol,
        body=fetch_stocktwits_messages(symbol, limit=30, start_date=start_date, end_date=end_date),
    )


def get_reddit_sentiment_context(ticker: str, start_date: str, end_date: str) -> str:
    symbol = _symbol(ticker)
    return _render_text_context(
        title=f"Reddit sentiment context for {symbol}",
        source="reddit",
        subject=symbol,
        body=fetch_reddit_posts(symbol, start_date=start_date, end_date=end_date),
    )


def get_eodhd_sentiment_context(ticker: str, start_date: str, end_date: str) -> str:
    symbol = _symbol(ticker)
    packet = fetch_eodhd_sentiments([symbol], from_date=start_date, to_date=end_date)
    return _render_packet(packet, title=f"EODHD sentiment context for {symbol}")


def get_social_sentiment_context(ticker: str, start_date: str, end_date: str) -> str:
    symbol = _symbol(ticker)
    blocks = [
        f"## Social sentiment context for {symbol}\n"
        "Execution authority: none (research evidence only)",
        get_stocktwits_sentiment_context(symbol, start_date, end_date),
        get_reddit_sentiment_context(symbol, start_date, end_date),
    ]
    return "\n\n".join(blocks)


def get_fmp_latest_earnings_transcript_context(ticker: str, curr_date: str | None = None) -> str:
    del curr_date
    packet = fetch_fmp_latest_earning_call_transcript(_symbol(ticker))
    return _render_packet(packet, title=f"FMP latest earnings transcript for {_symbol(ticker)}")


def get_yfinance_options_context(ticker: str, curr_date: str | None = None) -> str:
    del curr_date
    packet = fetch_yfinance_options_iv_flow(_symbol(ticker))
    return _render_packet(packet, title=f"YFinance options IV/open-interest context for {_symbol(ticker)}")


def get_yfinance_short_interest_context(ticker: str, curr_date: str | None = None) -> str:
    del curr_date
    packet = fetch_yfinance_short_interest(_symbol(ticker))
    return _render_packet(packet, title=f"YFinance short-interest context for {_symbol(ticker)}")


def get_yfinance_earnings_calendar_context(ticker: str, curr_date: str | None = None) -> str:
    del curr_date
    packet = fetch_yfinance_earnings_calendar(_symbol(ticker))
    return _render_packet(packet, title=f"YFinance earnings-calendar context for {_symbol(ticker)}")


def get_release_calendar_context(
    ticker: str | None = None,
    curr_date: str | None = None,
    lookahead_days: int | None = None,
) -> str:
    del ticker
    now = None
    if curr_date:
        now = datetime.fromisoformat(curr_date.replace("Z", "+00:00"))
    packet = build_release_calendar_packet(now=now, lookahead_days=lookahead_days)
    return _render_packet(packet, title="Official macro release-calendar context")


def _render_gap_context(
    *,
    evidence_need: str,
    source_name: str,
    ticker: str,
    exc: BaseException,
    fallback_source: str,
    quality: str = "low",
) -> str:
    message = str(exc).strip()
    for name in SECRET_PARAM_NAMES:
        message = re.sub(rf"({re.escape(name)}\s*[=:]\s*)[^\s&]+", r"\1[redacted]", message, flags=re.I)
    message = re.sub(r"eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}", "[redacted-jwt]", message)
    if len(message) > 220:
        message = message[:217] + "..."
    return (
        f"## {evidence_need} gap/downrank for {ticker}\n"
        f"Source: {source_name}\n"
        f"Quality: {quality}\n"
        f"Execution authority: none (research evidence only)\n"
        "Downrank evidence: true\n"
        f"Fallback source: {fallback_source}\n"
        f"Reason: {type(exc).__name__}: {message or 'source unavailable'}\n"
    )


def get_supplemental_market_context(
    ticker: str,
    curr_date: str,
    lookahead_days: int | None = None,
) -> str:
    """Best-effort advisory event and microstructure context for analysts.

    This combines evidence types that are useful for avoiding crowded green
    spikes and risky event windows. Source failures become explicit downrank/gap
    sections so missing optional feeds do not silently become neutral evidence.
    """

    symbol = _symbol(ticker)
    sections = [
        f"# Supplemental event and microstructure context for {symbol}",
        "Execution authority: none (research evidence only)",
        "Use as advisory confirmation/downrank context; refresh price, quote, spread, and broker state before any action.",
    ]
    sources = [
        (
            "earnings_transcripts",
            "fmp",
            "local:research_gap",
            lambda: get_fmp_latest_earnings_transcript_context(symbol, curr_date),
        ),
        (
            "options_iv_flow",
            "yfinance_options",
            "local:research_gap",
            lambda: get_yfinance_options_context(symbol, curr_date),
        ),
        (
            "short_interest",
            "yfinance_short_interest",
            "local:research_gap",
            lambda: get_yfinance_short_interest_context(symbol, curr_date),
        ),
        (
            "earnings_calendar",
            "yfinance_earnings_calendar",
            "local:release_calendar_watchlist",
            lambda: get_yfinance_earnings_calendar_context(symbol, curr_date),
        ),
        (
            "macro_release_calendar",
            "official_release_calendar",
            "config:release_calendar_watchlist",
            lambda: get_release_calendar_context(symbol, curr_date, lookahead_days),
        ),
    ]
    for evidence_need, source_name, fallback_source, factory in sources:
        try:
            sections.append(factory())
        except Exception as exc:  # noqa: BLE001 - optional advisory source; emit an explicit gap/downrank section.
            sections.append(
                _render_gap_context(
                    evidence_need=evidence_need,
                    source_name=source_name,
                    ticker=symbol,
                    exc=exc,
                    fallback_source=fallback_source,
                )
            )
    return "\n\n".join(section.strip() for section in sections if section and section.strip())
