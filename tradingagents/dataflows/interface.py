
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from tradingagents.dataflows._official_common import OfficialDataError

# Import from vendor-specific modules
from .alpha_vantage import (
    get_balance_sheet as get_alpha_vantage_balance_sheet,
)
from .alpha_vantage import (
    get_cashflow as get_alpha_vantage_cashflow,
)
from .alpha_vantage import (
    get_fundamentals as get_alpha_vantage_fundamentals,
)
from .alpha_vantage import (
    get_global_news as get_alpha_vantage_global_news,
)
from .alpha_vantage import (
    get_income_statement as get_alpha_vantage_income_statement,
)
from .alpha_vantage import (
    get_indicator as get_alpha_vantage_indicator,
)
from .alpha_vantage import (
    get_insider_transactions as get_alpha_vantage_insider_transactions,
)
from .alpha_vantage import (
    get_news as get_alpha_vantage_news,
)
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
)
from .alpha_vantage_common import AlphaVantageRateLimitError

# Configuration and routing logic
from .config import get_config
from .decision_vendor_adapters import (
    get_alpaca_news_adapter,
    get_alpaca_reference_context,
    get_bea_macro_context,
    get_bls_macro_context,
    get_eia_energy_macro_context,
    get_eodhd_fundamentals,
    get_eodhd_news,
    get_eodhd_sentiment_context,
    get_finnhub_fundamentals,
    get_finnhub_news,
    get_fmp_balance_sheet,
    get_fmp_cashflow,
    get_fmp_fundamentals,
    get_fmp_income_statement,
    get_fmp_latest_earnings_transcript_context,
    get_fmp_news,
    get_fred_macro_context,
    get_google_global_news,
    get_google_news,
    get_marketaux_global_news,
    get_marketaux_news,
    get_massive_stock_data,
    get_newsapi_news,
    get_reddit_sentiment_context,
    get_release_calendar_context,
    get_sec_fundamentals,
    get_stocktwits_sentiment_context,
    get_supplemental_market_context,
    get_tiingo_news_adapter,
    get_tiingo_stock_data,
    get_treasury_macro_context,
    get_yfinance_earnings_calendar_context,
    get_yfinance_options_context,
    get_yfinance_short_interest_context,
)
from .y_finance import (
    get_balance_sheet as get_yfinance_balance_sheet,
)
from .y_finance import (
    get_cashflow as get_yfinance_cashflow,
)
from .y_finance import (
    get_fundamentals as get_yfinance_fundamentals,
)
from .y_finance import (
    get_income_statement as get_yfinance_income_statement,
)
from .y_finance import (
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .y_finance import (
    get_stock_stats_indicators_window,
    get_YFin_data_online,
)
from .yfinance_news import get_global_news_yfinance, get_news_yfinance

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    },
    "macro_context": {
        "description": "Official macroeconomic and rates context",
        "tools": [
            "get_macro_context",
        ],
    },
    "sentiment_data": {
        "description": "Read-only social and vendor sentiment context",
        "tools": [
            "get_sentiment_context",
        ],
    },
    "event_microstructure_context": {
        "description": "Earnings, options, short-interest, and release-calendar context",
        "tools": [
            "get_earnings_transcript_context",
            "get_options_iv_flow_context",
            "get_short_interest_context",
            "get_earnings_calendar_context",
            "get_release_calendar_context",
            "get_supplemental_market_context",
            "get_alpaca_reference_context",
        ],
    },
}

VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
    "tiingo",
    "massive",
    "marketaux",
    "finnhub",
    "newsapi",
    "google_news",
    "fmp",
    "eodhd",
    "sec",
    "alpaca_news",
    "alpaca_reference",
    "fred",
    "bls",
    "bea",
    "eia",
    "treasury_fiscal",
    "stocktwits",
    "reddit",
    "yfinance_options",
    "yfinance_short_interest",
    "yfinance_earnings_calendar",
    "official_release_calendar",
    "local",
]

SOURCE_ROUTING_HEALTH_PATH = Path("results/_context/source-routing.json")
SOURCE_CATEGORY_GAPS = []
SOURCE_CATEGORY_COVERAGE = [
    {
        "category": "earnings_transcripts",
        "status": "covered_by_optional_connector",
        "provider_evidence_need": "earnings_transcripts",
        "promotion_state": "fmp_transcripts_before_gap_packet",
        "why_it_matters": "Guidance tone and Q&A can validate event-underreaction theses.",
        "active_routes": [
            "local:official_cache",
            "docker:youtube_transcript",
            "dataflow:fmp",
            "composio:benzinga",
            "local:research_gap",
        ],
        "limitations": [
            "FMP transcript data requires FMP_API_KEY and may be plan-limited",
            "YouTube/Benzinga transcript routes are external connector hooks and may be unavailable",
            "use transcripts for advisory confirmation/downrank only, never direct execution",
        ],
    },
    {
        "category": "options_iv_flow",
        "status": "covered_by_supplemental_connector",
        "provider_evidence_need": "options_iv_flow",
        "promotion_state": "yfinance_options_before_gap_packet",
        "why_it_matters": "0DTE/gamma/IV context can affect intraday dip-buy and spike-sell behavior.",
        "active_routes": ["dataflow:yfinance_options", "local:research_gap"],
        "limitations": [
            "public yfinance options data is supplemental and lower-authority",
            "use for advisory confirmation/downrank only, never direct execution",
        ],
    },
    {
        "category": "short_interest",
        "status": "covered_by_supplemental_connector",
        "provider_evidence_need": "short_interest",
        "promotion_state": "yfinance_short_interest_before_gap_packet",
        "why_it_matters": "Crowded-short and squeeze risk can change position timing and risk review.",
        "active_routes": ["dataflow:yfinance_short_interest", "local:research_gap"],
        "limitations": [
            "public yfinance short-interest metadata is supplemental and lower-authority",
            "short-interest values can lag official exchange publications",
            "use for advisory confirmation/downrank only, never direct execution",
        ],
    },
    {
        "category": "earnings_calendar",
        "status": "covered_by_supplemental_connector",
        "provider_evidence_need": "earnings_calendar",
        "promotion_state": "yfinance_earnings_calendar_before_release_calendar_fallback",
        "why_it_matters": "Company earnings dates can require blackout, spread, and post-event validation before dip-buy decisions.",
        "active_routes": ["dataflow:yfinance_earnings_calendar", "local:release_calendar_watchlist"],
        "limitations": [
            "public yfinance calendar data is supplemental and can revise",
            "use release-calendar watchlist fallback when ticker-specific earnings date is unavailable",
            "use for advisory event-risk/downrank context only, never direct execution",
        ],
    },
    {
        "category": "macro_release_calendar",
        "status": "covered_by_official_watchlist",
        "provider_evidence_need": "macro_release_calendar",
        "promotion_state": "official_release_calendar_context_available",
        "why_it_matters": "Macro release windows can alter liquidity, spreads, and the reliability of intraday AI-bot crowd signals.",
        "active_routes": ["config:release_calendar_watchlist", "local:official_release_calendar"],
        "limitations": [
            "static config must be refreshed when official calendars change",
            "release windows require fresh quote/spread validation before any action",
            "use for advisory event-risk/downrank context only, never direct execution",
        ],
    },
]

TRANSIENT_VENDOR_EXCEPTIONS = (
    AlphaVantageRateLimitError,
    OfficialDataError,
    requests.RequestException,
    TimeoutError,
    ConnectionError,
)

MERGEABLE_METHODS = {
    "get_news": {
        "max_sources": 4,
        "max_chars": 12_000,
    },
    "get_global_news": {
        "max_sources": 3,
        "max_chars": 10_000,
    },
}

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "yfinance": get_YFin_data_online,
        "tiingo": get_tiingo_stock_data,
        "massive": get_massive_stock_data,
        "alpha_vantage": get_alpha_vantage_stock,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
    },
    # fundamental_data
    "get_fundamentals": {
        "fmp": get_fmp_fundamentals,
        "eodhd": get_eodhd_fundamentals,
        "finnhub": get_finnhub_fundamentals,
        "sec": get_sec_fundamentals,
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
    },
    "get_balance_sheet": {
        "fmp": get_fmp_balance_sheet,
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
    },
    "get_cashflow": {
        "fmp": get_fmp_cashflow,
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
    },
    "get_income_statement": {
        "fmp": get_fmp_income_statement,
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
    },
    # news_data
    "get_news": {
        "marketaux": get_marketaux_news,
        "finnhub": get_finnhub_news,
        "newsapi": get_newsapi_news,
        "google_news": get_google_news,
        "eodhd": get_eodhd_news,
        "tiingo": get_tiingo_news_adapter,
        "fmp": get_fmp_news,
        "alpaca_news": get_alpaca_news_adapter,
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
    },
    "get_global_news": {
        "marketaux": get_marketaux_global_news,
        "google_news": get_google_global_news,
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
    # macro_context
    "get_macro_context": {
        "fred": get_fred_macro_context,
        "bls": get_bls_macro_context,
        "bea": get_bea_macro_context,
        "eia": get_eia_energy_macro_context,
        "treasury_fiscal": get_treasury_macro_context,
    },
    # sentiment_data
    "get_sentiment_context": {
        "stocktwits": get_stocktwits_sentiment_context,
        "reddit": get_reddit_sentiment_context,
        "eodhd": get_eodhd_sentiment_context,
    },
    # event_microstructure_context
    "get_earnings_transcript_context": {
        "fmp": get_fmp_latest_earnings_transcript_context,
    },
    "get_options_iv_flow_context": {
        "yfinance_options": get_yfinance_options_context,
    },
    "get_short_interest_context": {
        "yfinance_short_interest": get_yfinance_short_interest_context,
    },
    "get_earnings_calendar_context": {
        "yfinance_earnings_calendar": get_yfinance_earnings_calendar_context,
    },
    "get_release_calendar_context": {
        "official_release_calendar": get_release_calendar_context,
    },
    "get_supplemental_market_context": {
        "local": get_supplemental_market_context,
    },
    "get_alpaca_reference_context": {
        "alpaca_reference": get_alpaca_reference_context,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str | None = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")


def _vendor_chain(method: str, vendor_config: str) -> list[str]:
    configured = [
        vendor.strip()
        for vendor in str(vendor_config or "").split(",")
        if vendor.strip() and vendor.strip() != "default"
    ]
    chain: list[str] = []
    for vendor in configured + list(VENDOR_METHODS[method].keys()):
        if vendor not in chain:
            chain.append(vendor)
    return chain


def _resolve_vendor_callable(vendor_impl: Any) -> Callable[..., Any]:
    return vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl


def _is_empty_vendor_result(result: Any) -> bool:
    if result is None:
        return True
    if isinstance(result, str):
        text = result.strip()
        if not text:
            return True
        lowered = " ".join(text.lower().split())
        failure_prefixes = (
            "error ",
            "error:",
            "no data found",
            "no fundamentals data found",
            "no balance sheet data found",
            "no cash flow data found",
            "no income statement data found",
            "no insider transactions data found",
            "no news found",
            "no global news found",
        )
        return lowered.startswith(failure_prefixes)
    if isinstance(result, (list, tuple, set, dict)):
        return len(result) == 0
    empty_attr = getattr(result, "empty", None)
    return bool(empty_attr) if isinstance(empty_attr, bool) else False


def _fallback_error_summary(vendor: str, exc: BaseException | str) -> str:
    message = str(exc).strip()
    if len(message) > 180:
        message = message[:177] + "..."
    return f"{vendor}: {type(exc).__name__ if isinstance(exc, BaseException) else 'empty'} {message}".strip()


def _dedupe_text_lines(text: str, seen: set[str]) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        key = " ".join(line.strip().lower().split())
        if key:
            if key in seen:
                continue
            seen.add(key)
        lines.append(line)
    return "\n".join(lines).strip()


def _merge_vendor_results(
    method: str,
    vendor_results: list[tuple[str, Any]],
    *,
    max_chars: int,
) -> str:
    seen: set[str] = set()
    sections: list[str] = []
    for vendor, result in vendor_results:
        deduped = _dedupe_text_lines(str(result), seen)
        if not deduped:
            continue
        sections.append(f"## {vendor}\n{deduped}")
    sources = ", ".join(vendor for vendor, _result in vendor_results)
    merged = (
        f"# Merged {method} evidence\n"
        "Execution authority: none (research evidence only)\n"
        f"Sources merged: {sources}\n\n"
        + "\n\n".join(sections)
    ).strip()
    if len(merged) <= max_chars:
        return merged
    return merged[: max_chars - 48].rstrip() + "\n<snipped for bounded analyst context>"


def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    merge_policy = MERGEABLE_METHODS.get(method)
    if merge_policy:
        fallback_errors: list[str] = []
        vendor_results: list[tuple[str, Any]] = []
        for vendor in _vendor_chain(method, vendor_config):
            if vendor not in VENDOR_METHODS[method]:
                continue

            impl_func = _resolve_vendor_callable(VENDOR_METHODS[method][vendor])

            try:
                result = impl_func(*args, **kwargs)
                if _is_empty_vendor_result(result):
                    fallback_errors.append(_fallback_error_summary(vendor, "returned empty data"))
                    continue
                vendor_results.append((vendor, result))
                if len(vendor_results) >= int(merge_policy["max_sources"]):
                    break
            except TRANSIENT_VENDOR_EXCEPTIONS as exc:
                fallback_errors.append(_fallback_error_summary(vendor, exc))
                continue

        if vendor_results:
            return _merge_vendor_results(
                method,
                vendor_results,
                max_chars=int(merge_policy["max_chars"]),
            )

        detail = "; ".join(fallback_errors) if fallback_errors else "no configured vendor matched"
        raise RuntimeError(f"No available vendor for '{method}' after fallback chain: {detail}")

    fallback_errors: list[str] = []
    for vendor in _vendor_chain(method, vendor_config):
        if vendor not in VENDOR_METHODS[method]:
            continue

        impl_func = _resolve_vendor_callable(VENDOR_METHODS[method][vendor])

        try:
            result = impl_func(*args, **kwargs)
            if _is_empty_vendor_result(result):
                fallback_errors.append(_fallback_error_summary(vendor, "returned empty data"))
                continue
            return result
        except TRANSIENT_VENDOR_EXCEPTIONS as exc:
            fallback_errors.append(_fallback_error_summary(vendor, exc))
            continue

    detail = "; ".join(fallback_errors) if fallback_errors else "no configured vendor matched"
    raise RuntimeError(f"No available vendor for '{method}' after fallback chain: {detail}")


def decision_source_routing_summary() -> dict[str, Any]:
    config = get_config()
    methods: dict[str, Any] = {}
    categories: dict[str, Any] = {}
    for category, info in TOOLS_CATEGORIES.items():
        category_config = str(config.get("data_vendors", {}).get(category, "default"))
        method_names = list(info.get("tools") or [])
        categories[category] = {
            "configured_chain": category_config,
            "methods": method_names,
        }
        for method in method_names:
            vendor_config = get_vendor(category, method)
            available = list(VENDOR_METHODS.get(method, {}))
            methods[method] = {
                "category": category,
                "configured_chain": vendor_config,
                "available_vendors": available,
                "effective_fallback_chain": [
                    vendor
                    for vendor in _vendor_chain(method, vendor_config)
                    if vendor in VENDOR_METHODS.get(method, {})
                ],
                "routing_mode": "merge_dedup" if method in MERGEABLE_METHODS else "first_success",
            }
            if method in MERGEABLE_METHODS:
                methods[method]["merge_max_sources"] = MERGEABLE_METHODS[method]["max_sources"]
                methods[method]["merge_max_chars"] = MERGEABLE_METHODS[method]["max_chars"]
    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "analysis_only": True,
        "can_submit_orders": False,
        "categories": categories,
        "methods": methods,
        "source_category_gaps": SOURCE_CATEGORY_GAPS,
        "source_category_coverage": SOURCE_CATEGORY_COVERAGE,
        "next_open": "Open when routing chains change, a category has no usable source, or a missing source category becomes relevant.",
    }


def compact_decision_source_routing_summary(
    summary: dict[str, Any] | None = None,
    *,
    raw_packet_path: str | Path | None = None,
) -> dict[str, Any]:
    routing = summary or decision_source_routing_summary()
    methods = routing.get("methods") if isinstance(routing.get("methods"), dict) else {}
    categories = routing.get("categories") if isinstance(routing.get("categories"), dict) else {}
    compact_methods: dict[str, Any] = {}
    for name, details in methods.items():
        if not isinstance(details, dict):
            continue
        chain = details.get("effective_fallback_chain") or []
        compact_methods[str(name)] = {
            "category": details.get("category"),
            "routing_mode": details.get("routing_mode"),
            "effective_fallback_chain": chain,
            "effective_fallback_count": len(chain) if isinstance(chain, list) else 0,
        }
        if details.get("merge_max_sources") is not None:
            compact_methods[str(name)]["merge_max_sources"] = details.get("merge_max_sources")
    gaps = routing.get("source_category_gaps") or []
    coverage = routing.get("source_category_coverage") or []
    return {
        "schema": "compact_source_routing_v1",
        "generated_at": routing.get("generated_at"),
        "analysis_only": routing.get("analysis_only") is True,
        "can_submit_orders": False,
        "category_count": len(categories),
        "method_count": len(methods),
        "methods": compact_methods,
        "gap_count": len(gaps),
        "gap_categories": [
            item.get("category")
            for item in gaps
            if isinstance(item, dict) and item.get("category")
        ],
        "coverage_count": len(coverage),
        "coverage_categories": [
            item.get("category")
            for item in coverage
            if isinstance(item, dict) and item.get("category")
        ],
        "raw_packet_path": str(raw_packet_path) if raw_packet_path is not None else None,
        "next_open": routing.get("next_open"),
    }


def write_decision_source_routing(path: str | Path | None = None) -> Path:
    output_path = Path(path or SOURCE_ROUTING_HEALTH_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary = decision_source_routing_summary()
    output_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    compact = compact_decision_source_routing_summary(
        summary,
        raw_packet_path=output_path,
    )
    output_path.with_name("source-routing-compact.json").write_text(
        json.dumps(compact, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return output_path
