"""Ticker-level provider orchestration for analysis-only research packets."""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd

from tradingagents.dataflows._official_common import (
    DataTransportError,
    DataUnavailableError,
    OfficialDataError,
    RecoverableDataflowError,
    cached_safe_fetch_evidence,
    evidence_packet,
    official_cache_key,
    request_hash,
)
from tradingagents.dataflows.alpaca_news import fetch_alpaca_news
from tradingagents.dataflows.alpha_vantage_news import get_news as fetch_alpha_vantage_news_raw
from tradingagents.dataflows.alpha_vantage_stock import get_stock as fetch_alpha_vantage_stock_raw
from tradingagents.dataflows.eodhd import (
    fetch_eodhd_fundamentals,
    fetch_eodhd_news,
    fetch_eodhd_sentiments,
)
from tradingagents.dataflows.finnhub import (
    fetch_finnhub_company_news,
    fetch_finnhub_profile2,
    fetch_finnhub_quote,
)
from tradingagents.dataflows.fmp import (
    fetch_fmp_company_profile,
    fetch_fmp_latest_earning_call_transcript,
    fetch_fmp_quote,
    fetch_fmp_stock_news,
)
from tradingagents.dataflows.google_news import fetch_google_news_rss
from tradingagents.dataflows.marketaux import fetch_marketaux_news
from tradingagents.dataflows.massive import (
    fetch_massive_previous_day_bar,
    fetch_massive_ticker_overview,
)
from tradingagents.dataflows.newsapi import fetch_newsapi_everything
from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.sec import fetch_sec_company_tickers, fetch_sec_submissions
from tradingagents.dataflows.stockstats_utils import validate_daily_ohlcv
from tradingagents.dataflows.tiingo import (
    fetch_tiingo_daily_prices,
    fetch_tiingo_news,
    fetch_tiingo_ticker_metadata,
)
from tradingagents.dataflows.yfinance_earnings_calendar import (
    fetch_yfinance_earnings_calendar,
)
from tradingagents.dataflows.yfinance_options import fetch_yfinance_options_iv_flow
from tradingagents.dataflows.yfinance_short_interest import fetch_yfinance_short_interest
from tradingagents.research.crawler_policy import CrawlerPolicy
from tradingagents.research.crawler_runner import run_crawlee_research_packet
from tradingagents.research.provider_fallbacks import (
    DEFAULT_PROVIDER_FALLBACK_PATH,
    ProviderFallbackCandidate,
    load_provider_fallback_config,
    select_available_fallbacks,
)
from tradingagents.research.reddit_watchlists import build_reddit_watchlist_packet
from tradingagents.research.source_quality import load_source_quality_strengths
from tradingagents.research.twitter_mcp import fetch_twitter_recent_search_packet
from tradingagents.research.youtube_transcript import fetch_youtube_earnings_transcript_packet
from tradingagents.schemas.research import CrawlerRunPacket, SourceEvidencePacket

DEFAULT_BROKER_SNAPSHOT_DIR = Path("results/hourly_supervisor")
DEFAULT_SOURCE_QUALITY_REVIEW_PATH = Path("results/source_quality/latest.json")

DEFAULT_TICKER_EVIDENCE_NEEDS = (
    "market_news",
    "quote_price_context",
    "fundamentals_profile",
    "earnings_transcripts",
    "short_interest",
    "options_iv_flow",
    "crawler_research",
)
NO_STALE_CACHE_SOURCES = {"broker_snapshot", "crawlee", "twitter", "yfinance_short_interest"}
_LOSS_REVIEW_EVENT_SOURCES = frozenset({"alpaca_news", "finnhub", "fmp"})
_LOSS_REVIEW_NATIVE_NEWS_TYPES = {
    "alpaca_news": "market_news",
    "finnhub": "company_news",
    "fmp": "stock_news",
}
_LOSS_REVIEW_EVENT_MAX_AGE = datetime.timedelta(minutes=15)
_LOSS_REVIEW_SUBSTANCE_EVENT_MAX_AGE = datetime.timedelta(days=7)
_LOSS_REVIEW_POSITIVE_WORDS = frozenset(
    {"raise", "raises", "raised", "beat", "beats", "growth", "wins", "won", "approval", "approved", "partnership", "expands", "expansion"}
)
_LOSS_REVIEW_GUIDANCE_CUT = re.compile(
    r"\b(cut|cuts|lower(?:ed|s)?|reduces?|revised?\s+down|withdraws?)\b.{0,80}\b(guidance|outlook|forecast|revenue)\b|\b(guidance|outlook|forecast|revenue)\b.{0,80}\b(cut|lower(?:ed|s)?|reduc(?:ed|es)|down)\b",
    re.I,
)
_LOSS_REVIEW_CONTRACT_LOSS = re.compile(
    r"\b(lost|loss|terminated|termination|cancel(?:led|ed)?|canceled)\b.{0,80}\b(contract|customer|client|agreement)\b",
    re.I,
)
_LOSS_REVIEW_THESIS_INVALIDATOR = re.compile(
    r"\b(bankruptcy|fraud|restatement|going concern|delist(?:ing)?|material weakness)\b",
    re.I,
)
_LOSS_REVIEW_ADVERSE_CHANGE_PERCENT = re.compile(
    r"\b(?:cut|cuts|lowered|lowers|lower|reduced|reduces|reduce)\b.{0,80}?\b(?:by|of)\s+(\d{1,3}(?:\.\d+)?)\s*%"
    r"|\b(?:down|fell|fall)\b\s+(\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)

RESEARCH_GAP_EVIDENCE_NEEDS = {
    "earnings_transcripts": {
        "why_it_matters": "Guidance tone and Q&A can validate event-underreaction theses.",
        "suggested_routes": ["quartr_or_transcript_vendor", "company_ir_transcript_crawler"],
    },
    "short_interest": {
        "why_it_matters": "Crowded-short and squeeze risk can change position timing and risk review.",
        "suggested_routes": ["exchange_short_interest", "market_data_vendor_short_interest"],
    },
    "options_iv_flow": {
        "why_it_matters": "0DTE/gamma/IV context can affect intraday dip-buy and spike-sell behavior.",
        "suggested_routes": ["massive_options_or_polygon_options", "dedicated_options_vendor"],
    },
    "earnings_calendar": {
        "why_it_matters": "Upcoming earnings can materially change event risk and trade timing.",
        "suggested_routes": ["issuer_ir_calendar", "exchange_or_vendor_earnings_calendar"],
    },
}


@dataclass(frozen=True)
class TickerProviderResearchResult:
    symbol: str
    packets: list[SourceEvidencePacket] = field(default_factory=list)
    summary_packet: SourceEvidencePacket | None = None
    route_attempts: list[dict[str, Any]] = field(default_factory=list)


def _symbol(value: str) -> str:
    clean = value.strip().upper()
    if not clean:
        raise ValueError("ticker symbol is required")
    return clean


def _today(now: datetime.datetime | None = None) -> datetime.date:
    current = now or datetime.datetime.now(tz=datetime.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.timezone.utc)
    return current.astimezone(datetime.timezone.utc).date()


def _news_dates(now: datetime.datetime | None = None, *, lookback_days: int = 3) -> tuple[str, str]:
    end = _today(now)
    start = end - datetime.timedelta(days=max(1, int(lookback_days)))
    return start.isoformat(), end.isoformat()


def canonical_provider_timestamp(value: Any) -> str | None:
    """Return one vendor observation in the authority-safe UTC-second form.

    Provider payloads retain their original timestamps and bytes.  This helper
    only normalizes the wrapper/descriptor representation: RFC3339 ``Z`` and
    fractional forms, Finnhub epoch seconds, and FMP date-only values all map
    to the same canonical UTC whole-second string.  Unparseable or naive
    timestamp values have no authority representation.
    """
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            parsed = datetime.datetime.fromtimestamp(float(value), tz=datetime.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw):
                parsed = datetime.datetime.fromtimestamp(float(raw), tz=datetime.timezone.utc)
            elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                # FMP commonly supplies a date without a clock.  It is an
                # explicit UTC date, not an invitation to use local time.
                parsed = datetime.datetime.combine(
                    datetime.date.fromisoformat(raw), datetime.time(), tzinfo=datetime.timezone.utc
                )
            else:
                parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (OverflowError, OSError, ValueError):
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat(timespec="seconds")


def _loss_review_news_items(payload: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    for key in ("data", "articles", "news", "results"):
        value = payload.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def strict_loss_review_news_event(
    *,
    source_name: str,
    evidence_type: str,
    payload: Mapping[str, Any],
    as_of: Any,
    quality: str,
    freshness: Mapping[str, Any] | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, str] | None:
    """Return the one strict, current issuer-news fact a loss BOARD may use.

    This is intentionally shared by the fallback counter and the downstream
    normalizer.  A route therefore cannot satisfy collection merely by
    returning a cache envelope, RSS headline, blocked response, or a keyword
    without an explicit adverse magnitude.
    """
    source = str(source_name).strip().lower()
    if (
        source not in _LOSS_REVIEW_EVENT_SOURCES
        or evidence_type != _LOSS_REVIEW_NATIVE_NEWS_TYPES.get(source)
        or quality not in {"high", "medium"}
    ):
        return None
    info = freshness if isinstance(freshness, Mapping) else {}
    cache = info.get("cache")
    if (
        info.get("blocked") is True
        or info.get("stale") is True
        or (isinstance(cache, Mapping) and cache.get("state") in {"hit", "stale_fallback"})
    ):
        return None
    observed_text = canonical_provider_timestamp(as_of)
    if observed_text is None:
        return None
    observed = datetime.datetime.fromisoformat(observed_text)
    current = now or datetime.datetime.now(tz=datetime.timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        return None
    current = current.astimezone(datetime.timezone.utc).replace(microsecond=0)
    if observed > current or current - observed > _LOSS_REVIEW_EVENT_MAX_AGE:
        return None
    for item in _loss_review_news_items(payload):
        raw_time = (
            item.get("datetime")
            if source == "finnhub"
            else next(
                (item.get(key) for key in ("created_at", "published_at", "publishedDate", "date", "timestamp") if item.get(key) not in (None, "")),
                None,
            )
        )
        published_text = canonical_provider_timestamp(raw_time)
        if published_text is None:
            continue
        published = datetime.datetime.fromisoformat(published_text)
        if published > current or current - published > _LOSS_REVIEW_EVENT_MAX_AGE:
            continue
        if abs((observed - published).total_seconds()) > _LOSS_REVIEW_EVENT_MAX_AGE.total_seconds():
            continue
        url = item.get("url") or item.get("link")
        if not isinstance(url, str) or not url.strip():
            continue
        text = " ".join(
            str(item.get(key) or "")
            for key in ("category", "headline", "title", "summary", "text", "content")
        ).lower()
        if not text or any(token in text for token in _LOSS_REVIEW_POSITIVE_WORDS):
            continue
        magnitude = _LOSS_REVIEW_ADVERSE_CHANGE_PERCENT.search(text)
        if magnitude is None:
            continue
        raw_percent = next((value for value in magnitude.groups() if value is not None), None)
        try:
            percent = float(raw_percent)
        except (TypeError, ValueError):
            continue
        if not 1 <= percent <= 100:
            continue
        if _LOSS_REVIEW_THESIS_INVALIDATOR.search(text):
            category = "thesis_invalidator"
        elif _LOSS_REVIEW_GUIDANCE_CUT.search(text):
            category = "guidance_cut"
        elif _LOSS_REVIEW_CONTRACT_LOSS.search(text):
            category = "material_contract_loss"
        else:
            continue
        change = format(-percent / 100.0, ".8f").rstrip("0").rstrip(".")
        return {
            "event_category": category,
            "direction": "adverse",
            "impact_fraction": change,
            "as_of": published_text,
        }
    return None


def loss_review_news_packet_is_admissible(
    packet: SourceEvidencePacket, *, now: datetime.datetime | None = None
) -> bool:
    return strict_loss_review_news_event(
        source_name=packet.source_name,
        evidence_type=packet.evidence_type,
        payload=packet.payload,
        as_of=packet.as_of,
        quality=packet.quality,
        freshness=packet.freshness,
        now=now,
    ) is not None


def loss_review_substance_packet_is_admissible(
    packet: SourceEvidencePacket, *, now: datetime.datetime | None = None
) -> bool:
    """Accept only a fresh FMP transcript with an authenticated event time.

    Transcript publication is a real event whose validity can extend beyond a
    quote/news observation.  Packet capture, however, is a separate fact and
    must be current.  A cache, YouTube transcript text, or a wrapper timestamp
    invented from local collection time cannot satisfy this loss-BOARD slot.
    """
    if (
        packet.source_name != "fmp"
        or packet.evidence_type != "earnings_transcripts"
        or packet.quality not in {"high", "medium"}
        or not isinstance(packet.payload, Mapping)
        or str(packet.payload.get("symbol") or "").upper() != str(packet.symbol or "").upper()
    ):
        return False
    freshness = packet.freshness if isinstance(packet.freshness, Mapping) else {}
    cache = freshness.get("cache")
    if (
        freshness.get("blocked") is True
        or freshness.get("stale") is True
        or (isinstance(cache, Mapping) and cache.get("state") in {"hit", "stale_fallback"})
    ):
        return False
    published_text = canonical_provider_timestamp(packet.payload.get("published_at"))
    captured_text = canonical_provider_timestamp(packet.generated_at)
    if published_text is None or captured_text is None:
        return False
    items = packet.payload.get("transcript_items")
    if (
        not isinstance(items, Sequence)
        or isinstance(items, (str, bytes, bytearray))
        or not any(
            isinstance(item, Mapping)
            and isinstance(item.get("content") or item.get("text"), str)
            and (item.get("content") or item.get("text")).strip()
            for item in items
        )
    ):
        return False
    current = now or datetime.datetime.now(tz=datetime.timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        return False
    current = current.astimezone(datetime.timezone.utc).replace(microsecond=0)
    published = datetime.datetime.fromisoformat(published_text)
    captured = datetime.datetime.fromisoformat(captured_text)
    return (
        published <= current
        and current - published <= _LOSS_REVIEW_SUBSTANCE_EVENT_MAX_AGE
        and captured <= current
        and current - captured <= _LOSS_REVIEW_EVENT_MAX_AGE
    )


def _canonicalize_provider_packet_timestamp(packet: SourceEvidencePacket) -> SourceEvidencePacket:
    """Canonicalize wrapper timestamps while preserving the vendor payload verbatim."""
    canonical = canonical_provider_timestamp(packet.as_of)
    if canonical is None or canonical == packet.as_of:
        return packet
    data = packet.model_dump()
    freshness = dict(data.get("freshness") or {})
    freshness["raw_vendor_as_of"] = packet.as_of
    freshness["as_of"] = canonical
    data["as_of"] = canonical
    data["freshness"] = freshness
    data["sources"] = [
        {**dict(source), "as_of": canonical}
        if isinstance(source, Mapping)
        else source
        for source in data.get("sources") or []
    ]
    return SourceEvidencePacket.model_validate(data)


def _payload_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"raw_text": value, "format": "text"}
        return parsed if isinstance(parsed, dict) else {"data": parsed}
    return {"data": value}


def _alpha_vantage_packet(
    *,
    symbol: str,
    evidence_type: str,
    payload: Any,
    source_ref: str,
) -> Any:
    return evidence_packet(
        source_name="alpha_vantage",
        evidence_type=evidence_type,
        subject=symbol,
        symbol=symbol,
        source_ref=source_ref,
        payload=_payload_dict(payload),
        quality="medium",
        request_fingerprint=request_hash(
            "GET",
            source_ref,
            {"symbol": symbol, "evidence_type": evidence_type},
            None,
        ),
        tool_route="alpha_vantage_api",
    )


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        if hasattr(value, "item"):
            return _json_safe(value.item())
    except Exception:  # noqa: BLE001 - best-effort data normalization.
        pass
    return str(value)


def configured_quote_components(
    *,
    source_name: str,
    evidence_type: str,
    raw_payload: Any,
    expected_symbol: str,
) -> tuple[dict[str, float], ...]:
    """Return quote/previous-close facts from explicitly supported route shapes.

    This is the one admissibility contract used by both the provider fallback
    loop and the loss BOARD normalizer.  A packet only consumes a quote slot
    when it can also be consumed downstream.  In particular, a generic
    ``price`` label, a previous-day-only bar, or a cache/error envelope is not
    a quote fact.
    """
    if not isinstance(raw_payload, Mapping):
        return ()
    expected = str(expected_symbol).strip().upper()
    source = str(source_name).strip().lower()
    kind = str(evidence_type).strip()
    if not expected:
        return ()

    def numeric(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    def pair(value: Any) -> tuple[float, float] | None:
        if not isinstance(value, Mapping):
            return None
        # These are real configured vendor field names, not a loose scan of
        # arbitrary JSON labels.
        if source in {"finnhub", "fmp"} and kind == "quote":
            current, previous = value.get("c"), value.get("pc")
        elif kind == "quote_price_context":
            current = next((value.get(key) for key in ("p", "c") if value.get(key) not in (None, "")), None)
            previous = value.get("pc")
        else:
            return None
        current_value, previous_value = numeric(current), numeric(previous)
        if current_value is None or previous_value is None:
            return None
        return current_value, previous_value

    def item(symbol: str, value: Any) -> dict[str, float] | None:
        parsed = pair(value)
        if parsed is None:
            return None
        current, previous = parsed
        return {"symbol": symbol, "current": current, "previous": previous}

    # Finnhub and FMP quote endpoints are a single configured symbol.  FMP
    # deployments can return either the object or a one-item list.
    if source in {"finnhub", "fmp"} and kind == "quote":
        candidate: Any = raw_payload
        if isinstance(raw_payload.get("data"), Mapping):
            candidate = raw_payload["data"]
        elif isinstance(raw_payload.get("data"), list) and raw_payload["data"]:
            candidate = raw_payload["data"][0]
        elif isinstance(raw_payload.get("results"), list) and raw_payload["results"]:
            candidate = raw_payload["results"][0]
        value = item(expected, candidate)
        return (value,) if value is not None else ()

    if kind != "quote_price_context":
        return ()
    data = raw_payload.get("data")
    trades = data.get("trades") if isinstance(data, Mapping) else None
    if isinstance(trades, Mapping):
        found = [
            component
            for name, quote in trades.items()
            if (component := item(str(name).strip().upper(), quote)) is not None
        ]
        if found:
            return tuple(found)

    # Explicit quote-context one-symbol packets used by configured research
    # routes (including read-only broker snapshots) preserve c/pc or p/pc.
    candidate = data if isinstance(data, Mapping) else raw_payload
    value = item(expected, candidate)
    if value is not None:
        return (value,)

    # Actual yfinance context: final daily close plus the preceding bar.
    latest, bars = raw_payload.get("latest_bar"), raw_payload.get("recent_bars")
    if isinstance(latest, Mapping) and isinstance(bars, Sequence) and not isinstance(bars, (str, bytes, bytearray)) and len(bars) >= 2 and isinstance(bars[-2], Mapping):
        current = numeric(latest.get("Close", latest.get("close")))
        previous = numeric(bars[-2].get("Close", bars[-2].get("close")))
        if current is not None and previous is not None:
            return ({"symbol": expected, "current": current, "previous": previous},)

    # Actual latest-trade/previous-day packet shape.
    latest_trade = raw_payload.get("latest_trade") or raw_payload.get("latestTrade")
    previous_day = raw_payload.get("previous_day_bar") or raw_payload.get("previousDay")
    if isinstance(latest_trade, Mapping) and isinstance(previous_day, Mapping):
        current = numeric(latest_trade.get("p", latest_trade.get("c")))
        previous = numeric(previous_day.get("c", previous_day.get("close")))
        if current is not None and previous is not None:
            return ({"symbol": expected, "current": current, "previous": previous},)
    return ()


def _dataframe_records(frame: Any, *, max_rows: int = 20) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", False):
        return []
    limited = frame.tail(max(1, int(max_rows))).reset_index()
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in limited.to_dict(orient="records")
    ]


def _fetch_yfinance_quote_price_context(
    symbol: str,
    *,
    now: datetime.datetime | None = None,
) -> SourceEvidencePacket:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    history = ticker.history(period="1mo", interval="1d", auto_adjust=False)
    requested_as_of = _today(now)
    actual_latest = validate_daily_ohlcv(
        history,
        "yfinance",
        symbol,
        requested_as_of,
    )
    actual_latest_date = actual_latest.date().isoformat()
    fast_info = getattr(ticker, "fast_info", None)
    if fast_info is not None:
        try:
            fast_info_payload = dict(fast_info)
        except Exception:  # noqa: BLE001 - yfinance lazy objects vary by version.
            fast_info_payload = {"raw": str(fast_info)}
    else:
        fast_info_payload = {}
    payload = {
        "symbol": symbol,
        "period": "1mo",
        "interval": "1d",
        "latest_bar": _dataframe_records(history, max_rows=1)[-1],
        "recent_bars": _dataframe_records(history, max_rows=10),
        "fast_info": {str(key): _json_safe(value) for key, value in fast_info_payload.items()},
        "analysis_only": True,
        "execution_authority": "none",
    }
    source_ref = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    return evidence_packet(
        source_name="yfinance",
        evidence_type="quote_price_context",
        subject=f"yfinance quote and recent bars for {symbol}",
        symbol=symbol,
        source_ref=source_ref,
        payload=payload,
        quality="low",
        request_fingerprint=request_hash(
            "GET",
            source_ref,
            {"symbol": symbol, "period": "1mo", "interval": "1d"},
            None,
        ),
        tool_route="dataflow:yfinance",
        redaction_status="no_secrets_seen",
        as_of=actual_latest_date,
        freshness_extra={
            "read_only": True,
            "requested_as_of": requested_as_of.isoformat(),
            "actual_latest_bar": actual_latest_date,
        },
    )


_ACCOUNT_SUMMARY_FIELDS = (
    "status",
    "buying_power",
    "equity",
    "portfolio_value",
    "cash",
    "exposure",
    "dynamic_cap",
    "unused_cap",
    "unrealized_pl",
)

_POSITION_FIELDS = (
    "symbol",
    "qty",
    "market_value",
    "cost_basis",
    "unrealized_pl",
    "unrealized_plpc",
    "unrealized_intraday_pl",
    "unrealized_intraday_plpc",
    "current_price",
    "avg_entry_price",
)

_ORDER_FIELDS = (
    "symbol",
    "side",
    "qty",
    "notional",
    "type",
    "time_in_force",
    "limit_price",
    "stop_price",
    "status",
    "submitted_at",
    "filled_at",
    "filled_qty",
    "filled_avg_price",
    "account",
    "execution_mode",
    "action",
)

_CANDIDATE_FIELDS = (
    "symbol",
    "score",
    "current_price",
    "day_change_pct",
    "volume_ratio",
    "time_sensitive",
    "source",
    "reason",
)


def _json_object_from_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DataTransportError(
            f"broker supervisor packet could not be read: {type(exc).__name__}"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OfficialDataError(f"broker supervisor packet could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise OfficialDataError("broker supervisor packet is not a JSON object")
    return payload


def _latest_broker_snapshot_path(snapshot_dir: str | Path) -> Path:
    root = Path(snapshot_dir)
    if root.is_file():
        return root
    if not root.exists():
        raise DataUnavailableError(
            f"no supervisor snapshot directory found at {root}"
        )
    latest = root / "latest.json"
    if latest.exists():
        return latest
    candidates = [
        path
        for path in root.glob("hourly-supervisor-*.json")
        if _is_raw_json_packet_path(path)
    ]
    if not candidates:
        raise DataUnavailableError(
            f"no supervisor snapshot packet found at {root}"
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _is_raw_json_packet_path(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".json":
        return False
    name = path.name.lower()
    return not (name.endswith(".compact.json") or name == "latest-compact.json")


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        if all(isinstance(item, dict) for item in value.values()):
            return [item for item in value.values() if isinstance(item, dict)]
        return [value]
    return []


def _safe_subset(item: Any, fields: Sequence[str]) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {
        field: _json_safe(item.get(field))
        for field in fields
        if field in item and item.get(field) is not None
    }


def _matching_symbol_items(value: Any, symbol: str) -> list[dict[str, Any]]:
    target = symbol.upper()
    return [
        item
        for item in _dict_items(value)
        if str(item.get("symbol") or "").upper() == target
    ]


def _first_matching_symbol_item(value: Any, symbol: str) -> dict[str, Any] | None:
    matches = _matching_symbol_items(value, symbol)
    return matches[0] if matches else None


def _account_summary(account: Any) -> dict[str, Any]:
    if not isinstance(account, dict):
        return {"position_count": 0, "open_order_count": 0, "position_symbols": []}
    positions = _dict_items(account.get("positions"))
    open_orders = _dict_items(account.get("open_orders"))
    summary = _safe_subset(account, _ACCOUNT_SUMMARY_FIELDS)
    summary.update(
        {
            "position_count": len(positions),
            "open_order_count": len(open_orders),
            "position_symbols": sorted(
                {
                    str(item.get("symbol") or "").upper()
                    for item in positions
                    if item.get("symbol")
                }
            ),
        }
    )
    return summary


def _sanitized_orders(value: Any, symbol: str) -> list[dict[str, Any]]:
    return [_safe_subset(item, _ORDER_FIELDS) for item in _matching_symbol_items(value, symbol)]


def _fetch_broker_snapshot_quote_price_context(
    symbol: str,
    *,
    snapshot_dir: str | Path = DEFAULT_BROKER_SNAPSHOT_DIR,
) -> SourceEvidencePacket:
    snapshot_path = _latest_broker_snapshot_path(snapshot_dir)
    snapshot = _json_object_from_file(snapshot_path)
    portfolio = snapshot.get("portfolio") if isinstance(snapshot.get("portfolio"), dict) else {}
    live_account = portfolio.get("live") if isinstance(portfolio, dict) else {}
    paper_account = portfolio.get("paper") if isinstance(portfolio, dict) else {}
    live_position = _first_matching_symbol_item(
        live_account.get("positions") if isinstance(live_account, dict) else None,
        symbol,
    )
    paper_position = _first_matching_symbol_item(
        paper_account.get("positions") if isinstance(paper_account, dict) else None,
        symbol,
    )
    ranked_candidate = _first_matching_symbol_item(
        portfolio.get("ranked_candidates") if isinstance(portfolio, dict) else None,
        symbol,
    )
    payload = {
        "symbol": symbol,
        "source_packet_path": str(snapshot_path),
        "source_generated_at": snapshot.get("generated_at"),
        "supervisor_decision": snapshot.get("decision"),
        "market_session": portfolio.get("market_session") if isinstance(portfolio, dict) else None,
        "live_exposure": _json_safe(snapshot.get("live_exposure")),
        "live_account": _account_summary(live_account),
        "paper_account": _account_summary(paper_account),
        "portfolio_counts": {
            "live_positions": len(_dict_items(live_account.get("positions") if isinstance(live_account, dict) else None)),
            "paper_positions": len(_dict_items(paper_account.get("positions") if isinstance(paper_account, dict) else None)),
            "live_open_orders": len(_dict_items(live_account.get("open_orders") if isinstance(live_account, dict) else None)),
            "paper_open_orders": len(_dict_items(paper_account.get("open_orders") if isinstance(paper_account, dict) else None)),
        },
        "symbol_context": {
            "live_position": _safe_subset(live_position, _POSITION_FIELDS) if live_position else None,
            "paper_position": _safe_subset(paper_position, _POSITION_FIELDS) if paper_position else None,
            "live_open_orders": _sanitized_orders(
                live_account.get("open_orders") if isinstance(live_account, dict) else None,
                symbol,
            ),
            "paper_open_orders": _sanitized_orders(
                paper_account.get("open_orders") if isinstance(paper_account, dict) else None,
                symbol,
            ),
            "ranked_candidate": _safe_subset(ranked_candidate, _CANDIDATE_FIELDS)
            if ranked_candidate
            else None,
        },
        "recent_submissions": _sanitized_orders(snapshot.get("submitted"), symbol),
        "recent_reconciled_orders": _sanitized_orders(snapshot.get("reconciled_orders"), symbol),
        "issue_count": len(_dict_items(snapshot.get("issues"))),
        "submitted_order_count": len(_dict_items(snapshot.get("submitted"))),
        "read_only": True,
        "analysis_only": True,
        "execution_authority": "none",
        "forbidden_effects": [
            "create_trade_intent",
            "size_position",
            "submit_order",
            "promote_sleeve",
            "waive_live_gate",
        ],
    }
    source_ref = f"local://{snapshot_path.as_posix()}#broker_snapshot/{symbol}"
    return evidence_packet(
        source_name="broker_snapshot",
        evidence_type="quote_price_context",
        subject=f"sanitized broker supervisor snapshot for {symbol}",
        symbol=symbol,
        source_ref=source_ref,
        payload=payload,
        quality="medium",
        request_fingerprint=request_hash(
            "READ",
            source_ref,
            {"symbol": symbol},
            None,
        ),
        tool_route="local:hourly_supervisor_snapshot",
        redaction_status="redacted",
        freshness_extra={
            "read_only": True,
            "blocked": False,
            "source_generated_at": snapshot.get("generated_at"),
            "source_packet_path": str(snapshot_path),
            "market_session": payload["market_session"],
        },
    )


def _fetch_reddit_social_context(
    symbol: str,
    *,
    evidence_need: str,
    now: datetime.datetime | None = None,
) -> SourceEvidencePacket:
    start, end = _news_dates(now)
    reddit_context = fetch_reddit_posts(symbol, start_date=start, end_date=end)
    source_ref = f"https://www.reddit.com/search/?q={quote(symbol)}&sort=new&t=week"
    payload = {
        "symbol": symbol,
        "evidence_need": evidence_need,
        "window": {"start_date": start, "end_date": end},
        "reddit_context": reddit_context,
        "read_only": True,
        "analysis_only": True,
        "execution_authority": "none",
        "forbidden_effects": [
            "post",
            "comment",
            "vote",
            "message",
            "create_trade_intent",
            "size_position",
            "submit_order",
            "promote_sleeve",
            "waive_live_gate",
        ],
    }
    return evidence_packet(
        source_name="reddit",
        evidence_type=evidence_need,
        subject=f"public Reddit social context for {symbol}",
        symbol=symbol,
        source_ref=source_ref,
        payload=payload,
        quality="low",
        request_fingerprint=request_hash(
            "GET",
            source_ref,
            {"symbol": symbol, "start_date": start, "end_date": end},
            None,
        ),
        tool_route="dataflow:reddit_public",
        redaction_status="redacted",
        freshness_extra={"read_only": True, "route": "dataflow:reddit_public"},
    )


def _fetch_twitter_social_context(symbol: str, *, evidence_need: str) -> SourceEvidencePacket:
    return fetch_twitter_recent_search_packet(
        symbol,
        evidence_need=evidence_need,
    )


def _fetch_research_gap_packet(symbol: str, *, evidence_need: str) -> SourceEvidencePacket:
    gap = RESEARCH_GAP_EVIDENCE_NEEDS[evidence_need]
    source_ref = f"local://{DEFAULT_PROVIDER_FALLBACK_PATH.as_posix()}#{evidence_need}/research_gap"
    payload = {
        "symbol": symbol,
        "evidence_need": evidence_need,
        "status": "connector_not_configured",
        "gap_category": evidence_need,
        "why_it_matters": gap["why_it_matters"],
        "suggested_routes": gap["suggested_routes"],
        "research_action": "downrank confidence and require independent confirmation until a real connector is configured",
        "read_only": True,
        "analysis_only": True,
        "execution_authority": "none",
        "forbidden_effects": [
            "create_trade_intent",
            "size_position",
            "submit_order",
            "promote_sleeve",
            "waive_live_gate",
        ],
    }
    return evidence_packet(
        source_name=f"{evidence_need}_gap",
        evidence_type=evidence_need,
        subject=f"{evidence_need} connector gap for {symbol}",
        symbol=symbol,
        source_ref=source_ref,
        payload=payload,
        quality="unknown",
        request_fingerprint=request_hash(
            "READ",
            source_ref,
            None,
            {"symbol": symbol, "evidence_need": evidence_need, "status": "connector_not_configured"},
        ),
        tool_route="local:research_gap",
        redaction_status="no_secrets_seen",
        freshness_extra={
            "read_only": True,
            "blocked": True,
            "gap_category": evidence_need,
            "connector_status": "not_configured",
            "downrank_evidence": True,
        },
    )


def _cik_for_symbol(company_tickers_payload: dict[str, Any], symbol: str) -> str:
    target = symbol.upper()
    for item in company_tickers_payload.values():
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").upper()
        if ticker == target:
            cik = item.get("cik_str")
            if cik is not None:
                return str(cik)
    raise DataUnavailableError(f"SEC CIK not found for ticker {target}")


def _fetch_sec_submissions_by_symbol(symbol: str) -> SourceEvidencePacket:
    company_tickers = fetch_sec_company_tickers()
    cik = _cik_for_symbol(company_tickers.payload, symbol)
    return fetch_sec_submissions(cik, symbol=symbol)


@dataclass(frozen=True)
class TickerCrawlerTarget:
    target: str
    allowed_domains: tuple[str, ...]
    max_pages: int
    quality: str
    purpose: str


def _crawler_target_for_symbol(symbol: str, evidence_need: str) -> TickerCrawlerTarget | None:
    encoded = quote(symbol.upper(), safe="")
    if evidence_need == "market_news":
        return TickerCrawlerTarget(
            target=f"https://finance.yahoo.com/quote/{encoded}/news/",
            allowed_domains=("finance.yahoo.com",),
            max_pages=2,
            quality="low",
            purpose="ticker_news_page",
        )
    if evidence_need in {"crawler_research", "fundamentals_profile"}:
        return TickerCrawlerTarget(
            target=(
                "https://www.sec.gov/cgi-bin/browse-edgar"
                f"?CIK={encoded}&owner=exclude&action=getcompany"
            ),
            allowed_domains=("sec.gov",),
            max_pages=2,
            quality="medium",
            purpose="official_company_filings_page",
        )
    return None


def _crawler_source_packet(
    crawler_packet: CrawlerRunPacket,
    *,
    symbol: str,
    evidence_need: str,
    target: TickerCrawlerTarget,
) -> SourceEvidencePacket:
    blocked = crawler_packet.status in {"blocked", "failed"}
    payload = {
        "symbol": symbol,
        "evidence_need": evidence_need,
        "crawler_packet_id": crawler_packet.packet_id,
        "crawler_status": crawler_packet.status,
        "target": crawler_packet.target,
        "target_purpose": target.purpose,
        "fetched_urls": crawler_packet.fetched_urls[:10],
        "blocked_urls": crawler_packet.blocked_urls[:10],
        "max_pages": crawler_packet.max_pages,
        "robots_policy": crawler_packet.robots_policy,
        "target_policy": crawler_packet.freshness.get("target_policy"),
        "runtime": crawler_packet.freshness.get("runtime"),
        "metrics": crawler_packet.freshness.get("metrics"),
        "page_titles": crawler_packet.freshness.get("page_titles", {}),
        "blocked_reason": crawler_packet.freshness.get("blocked_reason"),
        "error_summary": crawler_packet.freshness.get("error_summary"),
        "read_only": True,
        "analysis_only": True,
        "execution_authority": "none",
    }
    return evidence_packet(
        source_name="crawlee",
        evidence_type=evidence_need,
        subject=f"allowlisted crawler research for {symbol}",
        symbol=symbol,
        source_ref=crawler_packet.target,
        payload=payload,
        quality=target.quality if not blocked else "unknown",
        request_fingerprint=request_hash(
            "CRAWL",
            crawler_packet.target,
            {"symbol": symbol, "evidence_need": evidence_need},
            None,
        ),
        tool_route="crawler:crawlee_playwright",
        redaction_status="redacted",
        freshness_extra={
            "read_only": True,
            "blocked": blocked,
            "crawler_status": crawler_packet.status,
            "crawler_packet_id": crawler_packet.packet_id,
            "target_policy": crawler_packet.freshness.get("target_policy"),
        },
    )


def _fetch_crawlee_ticker_research(symbol: str, evidence_need: str) -> SourceEvidencePacket:
    target = _crawler_target_for_symbol(symbol, evidence_need)
    if target is None:
        raise OfficialDataError(f"no crawler target policy for {symbol} {evidence_need}")
    crawler_packet = run_crawlee_research_packet(
        run_id=f"ticker-provider-{symbol.lower()}-{evidence_need}",
        target=target.target,
        policy=CrawlerPolicy(
            allowed_domains=target.allowed_domains,
            max_pages=target.max_pages,
            max_bytes=1_000_000,
            rate_limit_per_minute=12,
        ),
    )
    return _crawler_source_packet(
        crawler_packet,
        symbol=symbol,
        evidence_need=evidence_need,
        target=target,
    )


def _cache_file_for_source(
    cache_dir: str | Path,
    *,
    symbol: str,
    evidence_need: str,
    source_name: str,
) -> Path:
    cache_key = _provider_cache_key(
        symbol=symbol,
        evidence_need=evidence_need,
        source_name=source_name,
    )
    return Path(cache_dir) / f"{cache_key}.json"


def _provider_cache_key(*, symbol: str, evidence_need: str, source_name: str) -> str:
    parts: list[Any] = [
        "ticker_provider_orchestrator",
        symbol,
        evidence_need,
        source_name,
    ]
    if source_name == "crawlee":
        target = _crawler_target_for_symbol(symbol, evidence_need)
        if target is not None:
            parts.extend([target.target, target.purpose])
    if source_name == "yfinance_short_interest":
        parts.append("requires_short_interest_fields_v2")
    return official_cache_key(*parts)


def _yfinance_quote_cache_is_usable(
    packet: SourceEvidencePacket,
    *,
    symbol: str,
    now: datetime.datetime | None,
) -> bool:
    cache = packet.freshness.get("cache")
    if packet.freshness.get("stale"):
        return False
    if isinstance(cache, dict) and cache.get("state") == "stale_fallback":
        return False
    actual_latest_bar = packet.freshness.get("actual_latest_bar")
    if not actual_latest_bar:
        return False
    try:
        validate_daily_ohlcv(
            pd.DataFrame({"Date": [actual_latest_bar]}),
            "yfinance provider cache",
            symbol,
            _today(now),
        )
    except DataUnavailableError:
        return False
    return True


def _read_source_cache_packet(
    cache_dir: str | Path,
    *,
    symbol: str,
    evidence_need: str,
    candidate_sources: Sequence[str],
    now: datetime.datetime | None = None,
) -> SourceEvidencePacket:
    for source_name in candidate_sources:
        if source_name == "official_cache":
            continue
        path = _cache_file_for_source(
            cache_dir,
            symbol=symbol,
            evidence_need=evidence_need,
            source_name=source_name,
        )
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DataTransportError(
                f"cached {evidence_need} evidence could not be read: {type(exc).__name__}"
            ) from exc
        cached = SourceEvidencePacket.model_validate_json(text)
        if cached.tool_route == "local:research_gap" or cached.freshness.get("gap_category"):
            continue
        if evidence_need == "quote_price_context":
            cache = cached.freshness.get("cache")
            if cached.freshness.get("stale"):
                continue
            if isinstance(cache, dict) and cache.get("state") == "stale_fallback":
                continue
            current = now or datetime.datetime.now(tz=datetime.timezone.utc)
            if current.tzinfo is None:
                current = current.replace(tzinfo=datetime.timezone.utc)
            try:
                modified_at = path.stat().st_mtime
            except OSError as exc:
                raise DataTransportError(
                    f"cached {evidence_need} evidence could not be inspected: "
                    f"{type(exc).__name__}"
                ) from exc
            age_seconds = max(current.timestamp() - modified_at, 0.0)
            if age_seconds > _cache_ttl_seconds(evidence_need):
                continue
            if cached.source_name == "yfinance" and not _yfinance_quote_cache_is_usable(
                cached,
                symbol=symbol,
                now=now,
            ):
                continue
        source_ref = f"local://{path.as_posix()}"
        return evidence_packet(
            source_name="official_cache",
            evidence_type=evidence_need,
            subject=f"cached {evidence_need} evidence for {symbol}",
            symbol=symbol,
            source_ref=source_ref,
            payload={
                "symbol": symbol,
                "evidence_need": evidence_need,
                "cached_source_name": cached.source_name,
                "cached_packet_id": cached.packet_id,
                "cached_quality": cached.quality,
                "cached_as_of": cached.as_of or cached.generated_at,
                "cached_source_refs": cached.source_refs[:5],
                "read_only": True,
                "execution_authority": "none",
            },
            quality=cached.quality,
            request_fingerprint=request_hash(
                "READ",
                source_ref,
                None,
                {
                    "symbol": symbol,
                    "evidence_need": evidence_need,
                    "cached_source_name": cached.source_name,
                    "cached_packet_id": cached.packet_id,
                },
            ),
            tool_route="local:official_cache",
            redaction_status="no_secrets_seen",
            freshness_extra={"read_only": True, "cache": {"state": "hit", "source": cached.source_name}},
        )
    raise DataUnavailableError(
        f"no cached {evidence_need} evidence for {symbol}"
    )


def _unsupported_attempt(candidate: ProviderFallbackCandidate, *, evidence_need: str) -> dict[str, Any]:
    return {
        "evidence_need": evidence_need,
        "source_name": candidate.source_name,
        "route": candidate.route,
        "cost_tier": candidate.cost_tier,
        "source_quality_score": candidate.source_quality_score,
        "source_quality_reason": candidate.source_quality_reason,
        "status": "unsupported_in_local_orchestrator",
    }


def _cache_miss_attempt(
    candidate: ProviderFallbackCandidate,
    *,
    evidence_need: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "evidence_need": evidence_need,
        "source_name": candidate.source_name,
        "route": candidate.route,
        "cost_tier": candidate.cost_tier,
        "source_quality_score": candidate.source_quality_score,
        "source_quality_reason": candidate.source_quality_reason,
        "status": "cache_miss",
        "reason": str(reason)[:300],
    }


def _cache_ttl_seconds(evidence_need: str) -> int:
    if evidence_need == "quote_price_context":
        return 5 * 60
    if evidence_need in {"market_news", "social_sentiment"}:
        return 30 * 60
    return 24 * 60 * 60


def _fetcher_for_candidate(
    candidate: ProviderFallbackCandidate,
    *,
    evidence_need: str,
    symbol: str,
    now: datetime.datetime | None,
    cache_dir: str | Path,
    candidate_sources: Sequence[str],
    broker_snapshot_dir: str | Path,
):
    source = candidate.source_name
    if source == "google_news_rss" and evidence_need == "market_news":
        return lambda: fetch_google_news_rss(query=f"{symbol} stock", limit=25)
    if source == "alpaca_news" and evidence_need == "market_news":
        start, end = _news_dates(now)
        return lambda: fetch_alpaca_news(symbols=[symbol], start=start, end=end, limit=50)
    if source == "reddit_watchlist" and evidence_need in {"market_news", "social_sentiment"}:
        return lambda: build_reddit_watchlist_packet()
    if source == "reddit" and evidence_need == "social_sentiment":
        return lambda: _fetch_reddit_social_context(
            symbol,
            evidence_need=evidence_need,
            now=now,
        )
    if source == "twitter" and evidence_need == "social_sentiment":
        return lambda: _fetch_twitter_social_context(symbol, evidence_need=evidence_need)
    if source == "youtube_transcript" and evidence_need == "earnings_transcripts":
        return lambda: fetch_youtube_earnings_transcript_packet(symbol, now=now)
    if candidate.route == "local:research_gap" and evidence_need in RESEARCH_GAP_EVIDENCE_NEEDS:
        return lambda: _fetch_research_gap_packet(symbol, evidence_need=evidence_need)
    if source == "broker_snapshot" and evidence_need == "quote_price_context":
        return lambda: _fetch_broker_snapshot_quote_price_context(
            symbol,
            snapshot_dir=broker_snapshot_dir,
        )
    if source == "yfinance" and evidence_need == "quote_price_context":
        return lambda: _fetch_yfinance_quote_price_context(symbol, now=now)
    if source == "yfinance_options" and evidence_need == "options_iv_flow":
        return lambda: fetch_yfinance_options_iv_flow(symbol)
    if source == "yfinance_earnings_calendar" and evidence_need == "earnings_calendar":
        return lambda: fetch_yfinance_earnings_calendar(symbol)
    if source == "yfinance_short_interest" and evidence_need == "short_interest":
        return lambda: fetch_yfinance_short_interest(symbol)
    if source == "sec_edgar" and evidence_need == "fundamentals_profile":
        return lambda: _fetch_sec_submissions_by_symbol(symbol)
    if source == "crawlee" and evidence_need in {
        "crawler_research",
        "market_news",
        "fundamentals_profile",
    }:
        return lambda: _fetch_crawlee_ticker_research(symbol, evidence_need)
    if source == "newsapi" and evidence_need == "market_news":
        start, end = _news_dates(now)
        return lambda: fetch_newsapi_everything(
            f"{symbol} stock",
            from_date=start,
            to_date=end,
            page_size=50,
            symbol=symbol,
        )
    if source == "tiingo":
        if evidence_need == "market_news":
            start, end = _news_dates(now)
            return lambda: fetch_tiingo_news(tickers=[symbol], start_date=start, end_date=end, limit=50)
        if evidence_need == "quote_price_context":
            start, end = _news_dates(now, lookback_days=30)
            return lambda: fetch_tiingo_daily_prices(symbol, start_date=start, end_date=end)
        if evidence_need == "fundamentals_profile":
            return lambda: fetch_tiingo_ticker_metadata(symbol)
    if source == "marketaux" and evidence_need == "market_news":
        start, end = _news_dates(now)
        return lambda: fetch_marketaux_news(
            symbols=[symbol],
            search=f"{symbol} stock",
            published_after=start,
            published_before=end,
            limit=50,
        )
    if source == "eodhd":
        if evidence_need == "market_news":
            start, end = _news_dates(now)
            return lambda: fetch_eodhd_news(symbol=symbol, from_date=start, to_date=end, limit=50)
        if evidence_need == "fundamentals_profile":
            return lambda: fetch_eodhd_fundamentals(symbol)
        if evidence_need == "social_sentiment":
            start, end = _news_dates(now)
            return lambda: fetch_eodhd_sentiments([symbol], from_date=start, to_date=end)
    if source == "massive":
        if evidence_need == "quote_price_context":
            return lambda: fetch_massive_previous_day_bar(symbol)
        if evidence_need == "fundamentals_profile":
            return lambda: fetch_massive_ticker_overview(symbol)
    if source == "alpha_vantage":
        if evidence_need == "quote_price_context":
            start, end = _news_dates(now, lookback_days=30)
            return lambda: _alpha_vantage_packet(
                symbol=symbol,
                evidence_type="daily_adjusted",
                payload=fetch_alpha_vantage_stock_raw(symbol, start, end),
                source_ref=(
                    "https://www.alphavantage.co/query?"
                    f"function=TIME_SERIES_DAILY_ADJUSTED&symbol={symbol}"
                ),
            )
        if evidence_need == "market_news":
            start, end = _news_dates(now)
            return lambda: _alpha_vantage_packet(
                symbol=symbol,
                evidence_type="news_sentiment",
                payload=fetch_alpha_vantage_news_raw(symbol, start, end),
                source_ref=(
                    "https://www.alphavantage.co/query?"
                    f"function=NEWS_SENTIMENT&tickers={symbol}"
                ),
            )
    if source == "finnhub":
        if evidence_need == "quote_price_context":
            return lambda: fetch_finnhub_quote(symbol)
        if evidence_need == "market_news":
            start, end = _news_dates(now)
            return lambda: fetch_finnhub_company_news(symbol, from_date=start, to_date=end)
        if evidence_need == "fundamentals_profile":
            return lambda: fetch_finnhub_profile2(symbol)
    if source == "fmp":
        if evidence_need == "quote_price_context":
            return lambda: fetch_fmp_quote(symbol)
        if evidence_need == "market_news":
            start, end = _news_dates(now)
            return lambda: fetch_fmp_stock_news([symbol], from_date=start, to_date=end, limit=25)
        if evidence_need == "fundamentals_profile":
            return lambda: fetch_fmp_company_profile(symbol)
        if evidence_need == "earnings_transcripts":
            return lambda: fetch_fmp_latest_earning_call_transcript(symbol)
    return None


def _packet_attempt(
    packet: SourceEvidencePacket,
    candidate: ProviderFallbackCandidate,
    *,
    evidence_need: str,
) -> dict[str, Any]:
    cache = packet.freshness.get("cache") if isinstance(packet.freshness, dict) else None
    return {
        "evidence_need": evidence_need,
        "source_name": candidate.source_name,
        "route": candidate.route,
        "cost_tier": candidate.cost_tier,
        "source_quality_score": candidate.source_quality_score,
        "source_quality_reason": candidate.source_quality_reason,
        "status": "packet_written",
        "packet_id": packet.packet_id,
        "quality": packet.quality,
        "blocked": bool(packet.freshness.get("blocked")) if isinstance(packet.freshness, dict) else False,
        "cache_state": cache.get("state") if isinstance(cache, dict) else None,
    }


def _blocked_packet_counts_as_evidence(
    packet: SourceEvidencePacket,
    candidate: ProviderFallbackCandidate,
) -> bool:
    if not packet.freshness.get("blocked"):
        return True
    return candidate.route == "local:research_gap" or candidate.cost_tier == "connected_mcp_read"


def _packet_is_gap(packet: SourceEvidencePacket) -> bool:
    return (
        packet.tool_route == "local:research_gap"
        or str(packet.source_name).endswith("_gap")
        or bool(packet.freshness.get("gap_category"))
    )


def _quote_packet_has_current_previous(packet: SourceEvidencePacket) -> bool:
    """Recognise real configured quote shapes before consuming a quote slot.

    This is deliberately a small, local admissibility check.  It does not
    change a source's quality or discard the packet; it only prevents a
    previous-day-only/cache placeholder from making the fallback loop stop
    before a route supplies both values needed by the loss BOARD.
    """
    return bool(
        configured_quote_components(
            source_name=packet.source_name,
            evidence_type=packet.evidence_type,
            raw_payload=packet.payload,
            expected_symbol=packet.symbol or packet.subject,
        )
    )


def _route_status_counts(attempts: Sequence[dict[str, Any]]) -> dict[str, int]:
    statuses = sorted({str(attempt.get("status") or "unknown") for attempt in attempts})
    return {
        status: sum(1 for attempt in attempts if str(attempt.get("status") or "unknown") == status)
        for status in statuses
    }


def build_ticker_provider_research_packets(
    symbol: str,
    *,
    evidence_needs: Sequence[str] = DEFAULT_TICKER_EVIDENCE_NEEDS,
    provider_config_path: str | Path = DEFAULT_PROVIDER_FALLBACK_PATH,
    depleted_sources: set[str] | None = None,
    disabled_sources: set[str] | None = None,
    max_packets_per_need: int = 1,
    cache_dir: str | Path = "results/research_provider_cache",
    broker_snapshot_dir: str | Path = DEFAULT_BROKER_SNAPSHOT_DIR,
    source_quality_review_path: str | Path | None = None,
    now: datetime.datetime | None = None,
    authority_now: datetime.datetime | None = None,
    require_admissible_quote: bool = False,
    require_admissible_loss_news: bool = False,
    require_admissible_loss_substance: bool = False,
) -> TickerProviderResearchResult:
    ticker = _symbol(symbol)
    config = load_provider_fallback_config(provider_config_path)
    source_quality_strengths = (
        load_source_quality_strengths(source_quality_review_path)
        if source_quality_review_path is not None
        else {}
    )
    packets: list[SourceEvidencePacket] = []
    attempts: list[dict[str, Any]] = []
    requested_needs = [need.strip() for need in evidence_needs if need and need.strip()]
    for evidence_need in requested_needs:
        written_for_need = 0
        candidates = select_available_fallbacks(
            evidence_need,
            config=config,
            depleted_sources=depleted_sources,
            disabled_sources=disabled_sources,
            source_quality_strengths=(
                source_quality_strengths if source_quality_review_path is not None else None
            ),
        )
        candidate_sources = [candidate.source_name for candidate in candidates]
        for candidate in candidates:
            if candidate.source_name == "official_cache":
                try:
                    packet = _read_source_cache_packet(
                        cache_dir,
                        symbol=ticker,
                        evidence_need=evidence_need,
                        candidate_sources=candidate_sources,
                        now=now,
                    )
                except RecoverableDataflowError as exc:
                    attempts.append(
                        _cache_miss_attempt(candidate, evidence_need=evidence_need, reason=str(exc))
                    )
                    continue
                packet = _canonicalize_provider_packet_timestamp(packet)
                packets.append(packet)
                attempts.append(_packet_attempt(packet, candidate, evidence_need=evidence_need))
                if (
                    not require_admissible_quote
                    or evidence_need != "quote_price_context"
                    or _quote_packet_has_current_previous(packet)
                ) and (
                    not require_admissible_loss_news
                    or evidence_need != "market_news"
                    # Collection begins before all network reads finish.  Do
                    # not reject an observation simply because it crossed a
                    # second boundary after the run began; with no authority
                    # instant yet, retain it diagnostically and keep routing.
                    or (
                        authority_now is not None
                        and loss_review_news_packet_is_admissible(packet, now=authority_now)
                    )
                ) and (
                    not require_admissible_loss_substance
                    or evidence_need != "earnings_transcripts"
                    or (
                        authority_now is not None
                        and loss_review_substance_packet_is_admissible(
                            packet, now=authority_now
                        )
                    )
                ):
                    written_for_need += 1
                if written_for_need >= max(1, int(max_packets_per_need)):
                    break
                continue
            fetcher = _fetcher_for_candidate(
                candidate,
                evidence_need=evidence_need,
                symbol=ticker,
                now=now,
                cache_dir=cache_dir,
                candidate_sources=candidate_sources,
                broker_snapshot_dir=broker_snapshot_dir,
            )
            if fetcher is None:
                attempts.append(_unsupported_attempt(candidate, evidence_need=evidence_need))
                continue
            cache_key = _provider_cache_key(
                symbol=ticker,
                evidence_need=evidence_need,
                source_name=candidate.source_name,
            )
            packet = cached_safe_fetch_evidence(
                fetcher,
                cache_key=cache_key,
                ttl_seconds=0
                if (
                    candidate.source_name in NO_STALE_CACHE_SOURCES
                    or (
                        require_admissible_loss_substance
                        and evidence_need == "earnings_transcripts"
                    )
                )
                else _cache_ttl_seconds(evidence_need),
                source_name=candidate.source_name,
                evidence_type=evidence_need,
                subject=ticker,
                symbol=ticker,
                source_ref=f"{candidate.route}:{ticker}",
                cache_dir=cache_dir,
                now=now,
                allow_stale_on_error=(
                    candidate.source_name not in NO_STALE_CACHE_SOURCES
                    and not (
                        require_admissible_loss_substance
                        and evidence_need == "earnings_transcripts"
                    )
                    and not (
                        candidate.source_name == "yfinance"
                        and evidence_need == "quote_price_context"
                    )
                ),
                cached_packet_validator=(
                    (
                        lambda cached: _yfinance_quote_cache_is_usable(
                            cached,
                            symbol=ticker,
                            now=now,
                        )
                    )
                    if candidate.source_name == "yfinance"
                    and evidence_need == "quote_price_context"
                    else None
                ),
            )
            packet = _canonicalize_provider_packet_timestamp(packet)
            if not _blocked_packet_counts_as_evidence(packet, candidate):
                attempts.append(_packet_attempt(packet, candidate, evidence_need=evidence_need))
                continue
            packets.append(packet)
            attempts.append(_packet_attempt(packet, candidate, evidence_need=evidence_need))
            # Keep searching configured quote routes until there is a usable
            # current/previous component.  This is independent of the normal
            # max-packet cap, so two unusable packets cannot starve the third.
            if (
                not require_admissible_quote
                or evidence_need != "quote_price_context"
                or _quote_packet_has_current_previous(packet)
            ) and (
                not require_admissible_loss_news
                or evidence_need != "market_news"
                or (
                    authority_now is not None
                    and loss_review_news_packet_is_admissible(packet, now=authority_now)
                    )
            ) and (
                not require_admissible_loss_substance
                or evidence_need != "earnings_transcripts"
                or (
                    authority_now is not None
                    and loss_review_substance_packet_is_admissible(
                        packet, now=authority_now
                    )
                )
            ):
                written_for_need += 1
            if written_for_need >= max(1, int(max_packets_per_need)):
                break
    source_ref = f"local://{Path(provider_config_path).as_posix()}#ticker_provider_orchestrator/{ticker}"
    cost_tier_by_source = {
        str(attempt.get("source_name")): str(attempt.get("cost_tier"))
        for attempt in attempts
        if attempt.get("source_name") and attempt.get("cost_tier")
    }
    gap_packets = [packet for packet in packets if _packet_is_gap(packet)]
    non_gap_evidence_needs = {
        packet.evidence_type
        for packet in packets
        if not _packet_is_gap(packet) and not packet.freshness.get("blocked")
    }
    gap_evidence_needs = {packet.evidence_type for packet in gap_packets}
    summary_packet = evidence_packet(
        source_name="ticker_provider_orchestrator",
        evidence_type="ticker_research_provider_bundle",
        subject=ticker,
        symbol=ticker,
        source_ref=source_ref,
        payload={
            "symbol": ticker,
            "evidence_needs": requested_needs,
            "depleted_sources": sorted(depleted_sources or set()),
            "disabled_sources": sorted(disabled_sources or set()),
            "max_packets_per_need": max_packets_per_need,
            "source_quality_ordering": {
                "enabled": source_quality_review_path is not None,
                "review_path": str(source_quality_review_path) if source_quality_review_path else None,
                "scored_source_count": len(source_quality_strengths),
            },
            "source_packet_ids": [packet.packet_id for packet in packets],
            "route_attempts": attempts,
            "packet_counts_by_source": {
                source_name: sum(1 for packet in packets if packet.source_name == source_name)
                for source_name in sorted({packet.source_name for packet in packets})
            },
            "route_status_counts": _route_status_counts(attempts),
            "unsupported_route_count": sum(
                1
                for attempt in attempts
                if attempt.get("status") == "unsupported_in_local_orchestrator"
            ),
            "blocked_packet_attempt_count": sum(
                1
                for attempt in attempts
                if attempt.get("status") == "packet_written" and attempt.get("blocked") is True
            ),
            "gap_packet_count": len(gap_packets),
            "evidence_needs_with_gap_packets": sorted(gap_evidence_needs),
            "evidence_needs_without_non_gap_packets": sorted(
                set(requested_needs) - non_gap_evidence_needs
            ),
            "limited_source_packet_count": sum(
                1
                for packet in packets
                if cost_tier_by_source.get(packet.source_name) in {"free_limited", "paid_limited"}
            ),
            "analysis_only": True,
            "execution_authority": "none",
            "forbidden_effects": config.get("policy", {}).get("forbidden_effects", []),
        },
        quality="medium" if packets else "unknown",
        request_fingerprint=request_hash(
            "LOCAL",
            source_ref,
            None,
            {
                "symbol": ticker,
                "evidence_needs": requested_needs,
                "depleted_sources": sorted(depleted_sources or set()),
                "disabled_sources": sorted(disabled_sources or set()),
            },
        ),
        tool_route="local_ticker_provider_orchestrator",
        redaction_status="no_secrets_seen",
        freshness_extra={
            "packet_count": len(packets),
            "attempt_count": len(attempts),
            "read_only": True,
        },
    )
    return TickerProviderResearchResult(
        symbol=ticker,
        packets=packets,
        summary_packet=summary_packet,
        route_attempts=attempts,
    )


def packet_ids(packets: Iterable[SourceEvidencePacket]) -> list[str]:
    return [packet.packet_id for packet in packets]
