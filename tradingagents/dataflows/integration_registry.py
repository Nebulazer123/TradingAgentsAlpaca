"""No-secret registry for research and connector capabilities.

The registry describes what each integration is allowed to do. It reports
environment-variable presence and route metadata, but never serializes secret
values and never grants trading authority.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DEFAULT_REGISTRY_PATH = Path("config/research_integrations.json")

DEFAULT_INTEGRATIONS: list[dict[str, Any]] = [
    {
        "name": "alpaca_paper",
        "category": "broker",
        "env_vars": ["ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY"],
        "required_env_vars": ["ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY"],
        "cost_tier": "connected_account",
        "route": "broker:alpaca_paper",
        "read_authority": "account_and_market_read",
        "write_authority": "paper_orders_only",
        "trading_authority": "broker_boundary_only",
        "fallback_behavior": "block_order_path_if_missing",
    },
    {
        "name": "alpaca_live",
        "category": "broker",
        "env_vars": ["ALPACA_LIVE_API_KEY", "ALPACA_LIVE_SECRET_KEY"],
        "required_env_vars": ["ALPACA_LIVE_API_KEY", "ALPACA_LIVE_SECRET_KEY"],
        "cost_tier": "connected_account",
        "route": "broker:alpaca_live",
        "read_authority": "account_and_market_read",
        "write_authority": "live_orders_only_after_python_policy_gate",
        "trading_authority": "broker_boundary_only",
        "fallback_behavior": "block_live_path_if_missing",
    },
    {
        "name": "sec_edgar",
        "category": "official_filings",
        "env_vars": ["SEC_USER_AGENT"],
        "required_env_vars": ["SEC_USER_AGENT"],
        "cost_tier": "free_unmetered",
        "route": "dataflow:sec_edgar",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_source_and_use_fallbacks",
    },
    {
        "name": "fred",
        "category": "official_macro",
        "env_vars": ["FRED_API_KEY"],
        "required_env_vars": ["FRED_API_KEY"],
        "cost_tier": "free_limited",
        "route": "dataflow:fred",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_source_and_use_fallbacks",
    },
    {
        "name": "bls",
        "category": "official_macro",
        "env_vars": ["BLS_API_KEY"],
        "required_env_vars": [],
        "cost_tier": "free_limited",
        "route": "dataflow:bls",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "continue_without_key_at_lower_rate",
    },
    {
        "name": "bea",
        "category": "official_macro",
        "env_vars": ["BEA_API_KEY"],
        "required_env_vars": ["BEA_API_KEY"],
        "cost_tier": "free_limited",
        "route": "dataflow:bea",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_source_and_use_fallbacks",
    },
    {
        "name": "eia",
        "category": "official_macro",
        "env_vars": ["EIA_API_KEY"],
        "required_env_vars": ["EIA_API_KEY"],
        "cost_tier": "free_limited",
        "route": "dataflow:eia",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_source_and_use_fallbacks",
    },
    {
        "name": "alpha_vantage",
        "category": "market_data",
        "env_vars": ["ALPHA_VANTAGE_API_KEY"],
        "required_env_vars": ["ALPHA_VANTAGE_API_KEY"],
        "cost_tier": "free_limited",
        "route": "dataflow:alpha_vantage",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "top_n_enrichment_only_skip_when_depleted",
    },
    {
        "name": "eodhd",
        "category": "market_data",
        "env_vars": ["EODHD_API_TOKEN", "EODHD_API_KEY"],
        "required_env_vars": ["EODHD_API_TOKEN"],
        "cost_tier": "free_limited",
        "route": "dataflow:eodhd",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_source_and_use_fallbacks",
    },
    {
        "name": "yfinance",
        "category": "market_data",
        "env_vars": [],
        "required_env_vars": [],
        "cost_tier": "free_public_unmetered",
        "route": "dataflow:yfinance",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_keyed_sources_first_then_yfinance",
    },
    {
        "name": "yfinance_options",
        "category": "options_market_context",
        "env_vars": [],
        "required_env_vars": [],
        "cost_tier": "free_public_unmetered",
        "route": "dataflow:yfinance_options",
        "read_authority": "read_only_options_iv_open_interest_context",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "supplement_options_iv_flow_before_gap_packet",
    },
    {
        "name": "yfinance_short_interest",
        "category": "short_interest_context",
        "env_vars": [],
        "required_env_vars": [],
        "cost_tier": "free_public_unmetered",
        "route": "dataflow:yfinance_short_interest",
        "read_authority": "read_only_short_interest_metadata_context",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "supplement_short_interest_before_gap_packet",
    },
    {
        "name": "yfinance_earnings_calendar",
        "category": "earnings_calendar_context",
        "env_vars": [],
        "required_env_vars": [],
        "cost_tier": "free_public_unmetered",
        "route": "dataflow:yfinance_earnings_calendar",
        "read_authority": "read_only_earnings_calendar_context",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "supplement_earnings_calendar_before_release_calendar_fallback",
    },
    {
        "name": "alpaca_market_data",
        "category": "market_data",
        "env_vars": ["ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY"],
        "required_env_vars": ["ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY"],
        "cost_tier": "connected_account",
        "route": "dataflow:alpaca_market_data",
        "read_authority": "read_only_market_data",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_yfinance_intraday_when_missing_or_stale",
    },
    {
        "name": "alpaca_reference",
        "category": "market_and_account_reference",
        "env_vars": ["ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY"],
        "required_env_vars": ["ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY"],
        "cost_tier": "connected_account",
        "route": "dataflow:alpaca_reference",
        "read_authority": "allowlisted_get_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_route_and_preserve_current_account_restrictions",
    },
    {
        "name": "stockstats",
        "category": "technical_indicators",
        "env_vars": [],
        "required_env_vars": [],
        "cost_tier": "local_compute",
        "route": "dataflow:stockstats",
        "read_authority": "derived_local_indicator_read",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_indicator_when_price_data_missing",
    },
    {
        "name": "alphainsider",
        "category": "strategy_marketplace",
        "env_vars": ["ALPHAINSIDER_API_KEY", "ALPHAINSIDER_STRATEGY_ID", "ALPHAINSIDER_BOT_ID"],
        "required_env_vars": ["ALPHAINSIDER_API_KEY"],
        "cost_tier": "free_or_unknown_limited",
        "route": "dataflow:alphainsider",
        "read_authority": "read_only_strategy_metadata",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "paper_shadow_skips_when_missing",
    },
    {
        "name": "google_news_rss",
        "category": "news",
        "env_vars": [],
        "required_env_vars": [],
        "cost_tier": "free_unmetered",
        "route": "dataflow:google_news_rss",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_as_broad_news_fallback",
    },
    {
        "name": "yfinance_news",
        "category": "news",
        "env_vars": [],
        "required_env_vars": [],
        "cost_tier": "free_public_unmetered",
        "route": "dataflow:yfinance_news",
        "read_authority": "read_only_news",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_source_and_use_fallbacks",
    },
    {
        "name": "alpaca_news",
        "category": "news",
        "env_vars": ["ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY"],
        "required_env_vars": ["ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY"],
        "cost_tier": "connected_account",
        "route": "dataflow:alpaca_news",
        "read_authority": "read_only_news",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_source_and_use_fallbacks",
    },
    {
        "name": "reddit",
        "category": "social_sentiment",
        "env_vars": [],
        "required_env_vars": [],
        "cost_tier": "free_public_limited",
        "route": "dataflow:reddit",
        "read_authority": "read_only_public_posts",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_or_rate_limit_public_social_source",
    },
    {
        "name": "stocktwits",
        "category": "social_sentiment",
        "env_vars": [],
        "required_env_vars": [],
        "cost_tier": "free_public_limited",
        "route": "dataflow:stocktwits",
        "read_authority": "read_only_public_messages",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_or_rate_limit_public_social_source",
    },
    {
        "name": "finnhub",
        "category": "market_data",
        "env_vars": ["FINNHUB_API_KEY"],
        "required_env_vars": ["FINNHUB_API_KEY"],
        "cost_tier": "free_limited",
        "route": "dataflow:finnhub",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_source_and_use_fallbacks",
    },
    {
        "name": "fmp",
        "category": "market_data",
        "env_vars": ["FMP_API_KEY"],
        "required_env_vars": ["FMP_API_KEY"],
        "cost_tier": "free_limited",
        "route": "dataflow:fmp",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_source_and_use_fallbacks",
    },
    {
        "name": "massive",
        "category": "market_data",
        "env_vars": ["MASSIVE_API_KEY", "POLYGON_API_KEY"],
        "required_env_vars": ["MASSIVE_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "dataflow:massive",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_source_and_use_fallbacks",
    },
    {
        "name": "tiingo",
        "category": "market_data",
        "env_vars": ["TIINGO_API_KEY"],
        "required_env_vars": ["TIINGO_API_KEY"],
        "cost_tier": "free_limited",
        "route": "dataflow:tiingo",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_source_and_use_fallbacks",
    },
    {
        "name": "newsapi",
        "category": "news",
        "env_vars": ["NEWSAPI_API_KEY"],
        "required_env_vars": ["NEWSAPI_API_KEY"],
        "cost_tier": "free_limited",
        "route": "dataflow:newsapi",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_source_and_use_fallbacks",
    },
    {
        "name": "marketaux",
        "category": "news",
        "env_vars": ["MARKETAUX_API_KEY", "MARKETAUX_API_TOKEN"],
        "required_env_vars": ["MARKETAUX_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "dataflow:marketaux",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_source_and_use_fallbacks",
    },
    {
        "name": "scrapingbee",
        "category": "crawler",
        "env_vars": ["SCRAPINGBEE_API_KEY"],
        "required_env_vars": ["SCRAPINGBEE_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "dataflow:scrapingbee",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_crawlee_or_fetch_first",
    },
    {
        "name": "treasury_fiscal",
        "category": "official_macro",
        "env_vars": [],
        "required_env_vars": [],
        "cost_tier": "free_unmetered",
        "route": "dataflow:treasury_fiscal",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "skip_source_and_use_fallbacks",
    },
    {
        "name": "composio",
        "category": "connector_control_plane",
        "env_vars": ["COMPOSIO_API_KEY"],
        "required_env_vars": ["COMPOSIO_API_KEY"],
        "cost_tier": "connected_mcp_read",
        "route": "mcp:composio",
        "read_authority": "connected_read_only_by_default",
        "write_authority": "operator_explicit_only",
        "trading_authority": "none",
        "fallback_behavior": "skip_connected_tool_if_missing",
    },
    {
        "name": "binance_public",
        "category": "crypto_market_context",
        "env_vars": [],
        "required_env_vars": [],
        "cost_tier": "plugin_public_read",
        "route": "plugin:binance/public_read",
        "read_authority": "read_only",
        "write_authority": "none",
        "trading_authority": "none",
        "runtime_check_required": True,
        "fallback_behavior": "route_unavailable_if_plugin_missing",
    },
    {
        "name": "gemini",
        "category": "model",
        "env_vars": ["GOOGLE_API_KEY"],
        "required_env_vars": ["GOOGLE_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "model:gemini",
        "read_authority": "model_research",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_local_or_deterministic_fallback",
    },
    {
        "name": "anthropic",
        "category": "model",
        "env_vars": ["ANTHROPIC_API_KEY"],
        "required_env_vars": ["ANTHROPIC_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "model:anthropic",
        "read_authority": "model_research",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_local_or_deterministic_fallback",
    },
    {
        "name": "xai",
        "category": "model",
        "env_vars": ["XAI_API_KEY"],
        "required_env_vars": ["XAI_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "model:xai",
        "read_authority": "model_research",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_local_or_deterministic_fallback",
    },
    {
        "name": "deepseek",
        "category": "model",
        "env_vars": ["DEEPSEEK_API_KEY"],
        "required_env_vars": ["DEEPSEEK_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "model:deepseek",
        "read_authority": "model_research",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_local_or_deterministic_fallback",
    },
    {
        "name": "qwen",
        "category": "model",
        "env_vars": ["DASHSCOPE_API_KEY"],
        "required_env_vars": ["DASHSCOPE_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "model:qwen",
        "read_authority": "model_research",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_local_or_deterministic_fallback",
    },
    {
        "name": "qwen-cn",
        "category": "model",
        "env_vars": ["DASHSCOPE_CN_API_KEY"],
        "required_env_vars": ["DASHSCOPE_CN_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "model:qwen-cn",
        "read_authority": "model_research",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_local_or_deterministic_fallback",
    },
    {
        "name": "glm",
        "category": "model",
        "env_vars": ["ZHIPU_API_KEY"],
        "required_env_vars": ["ZHIPU_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "model:glm",
        "read_authority": "model_research",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_local_or_deterministic_fallback",
    },
    {
        "name": "glm-cn",
        "category": "model",
        "env_vars": ["ZHIPU_CN_API_KEY"],
        "required_env_vars": ["ZHIPU_CN_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "model:glm-cn",
        "read_authority": "model_research",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_local_or_deterministic_fallback",
    },
    {
        "name": "minimax",
        "category": "model",
        "env_vars": ["MINIMAX_API_KEY"],
        "required_env_vars": ["MINIMAX_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "model:minimax",
        "read_authority": "model_research",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_local_or_deterministic_fallback",
    },
    {
        "name": "minimax-cn",
        "category": "model",
        "env_vars": ["MINIMAX_CN_API_KEY"],
        "required_env_vars": ["MINIMAX_CN_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "model:minimax-cn",
        "read_authority": "model_research",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_local_or_deterministic_fallback",
    },
    {
        "name": "azure",
        "category": "model",
        "env_vars": [
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_DEPLOYMENT_NAME",
            "OPENAI_API_VERSION",
        ],
        "required_env_vars": [
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_DEPLOYMENT_NAME",
        ],
        "cost_tier": "paid_limited",
        "route": "model:azure",
        "read_authority": "model_research",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_local_or_deterministic_fallback",
    },
    {
        "name": "openai",
        "category": "model",
        "env_vars": ["OPENAI_API_KEY"],
        "required_env_vars": ["OPENAI_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "model:openai",
        "read_authority": "model_research",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "disabled_for_scheduled_runtime_unless_armed",
    },
    {
        "name": "openrouter",
        "category": "model",
        "env_vars": ["OPENROUTER_API_KEY"],
        "required_env_vars": ["OPENROUTER_API_KEY"],
        "cost_tier": "paid_limited",
        "route": "model:openrouter",
        "read_authority": "model_research",
        "write_authority": "none",
        "trading_authority": "none",
        "fallback_behavior": "use_local_or_deterministic_fallback",
    },
    {
        "name": "zep",
        "category": "memory",
        "env_vars": ["ZEP_API_KEY"],
        "required_env_vars": ["ZEP_API_KEY"],
        "cost_tier": "free_limited",
        "route": "memory:zep",
        "read_authority": "research_memory",
        "write_authority": "research_memory_only",
        "trading_authority": "none",
        "fallback_behavior": "use_local_jsonl_memory",
    },
]


def load_integration_registry(path: str | Path | None = None) -> list[dict[str, Any]]:
    registry_path = Path(path) if path else DEFAULT_REGISTRY_PATH
    if not registry_path.exists():
        return [dict(item) for item in DEFAULT_INTEGRATIONS]
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    integrations = data.get("integrations")
    if not isinstance(integrations, list):
        raise ValueError("research integration registry must contain an integrations list")
    return [dict(item) for item in integrations if isinstance(item, Mapping)]


def _env_presence(env: Mapping[str, str], name: str, required: bool) -> dict[str, Any]:
    value = str(env.get(name) or "")
    return {
        "present": bool(value.strip()),
        "length": len(value) if value else 0,
        "required": required,
    }


def _integration_status(item: Mapping[str, Any], env_status: Mapping[str, Mapping[str, Any]]) -> str:
    if item.get("runtime_check_required"):
        return "requires_runtime_check"
    missing_required = [
        name
        for name, status in env_status.items()
        if status.get("required") and not status.get("present")
    ]
    if missing_required:
        return "skipped_missing_env"
    if not env_status:
        return "available_without_env"
    return "env_ready"


def build_integration_registry_report(
    path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    active_env = env or os.environ
    integrations = []
    all_missing_optional: list[str] = []
    all_missing_required: list[str] = []
    authority_counts: dict[str, int] = {}
    for raw in load_integration_registry(path):
        env_vars = [str(name) for name in raw.get("env_vars", [])]
        required_env_vars = {str(name) for name in raw.get("required_env_vars", [])}
        env_status = {
            name: _env_presence(active_env, name, name in required_env_vars)
            for name in env_vars
        }
        missing_optional = [
            name
            for name, status in env_status.items()
            if not status["present"] and not status["required"]
        ]
        missing_required = [
            name
            for name, status in env_status.items()
            if not status["present"] and status["required"]
        ]
        all_missing_optional.extend(name for name in missing_optional if name not in all_missing_optional)
        all_missing_required.extend(name for name in missing_required if name not in all_missing_required)
        trading_authority = str(raw.get("trading_authority") or "none")
        authority_counts[trading_authority] = authority_counts.get(trading_authority, 0) + 1
        integrations.append(
            {
                "name": str(raw.get("name") or "unknown"),
                "category": str(raw.get("category") or "unknown"),
                "route": str(raw.get("route") or ""),
                "cost_tier": str(raw.get("cost_tier") or "unknown"),
                "read_authority": str(raw.get("read_authority") or "read_only"),
                "write_authority": str(raw.get("write_authority") or "none"),
                "trading_authority": trading_authority,
                "fallback_behavior": str(raw.get("fallback_behavior") or "skip_source_and_use_fallbacks"),
                "runtime_check_required": bool(raw.get("runtime_check_required", False)),
                "status": _integration_status(raw, env_status),
                "env": env_status,
            }
        )

    return {
        "schema_version": 1,
        "kind": "research_integration_registry",
        "secrets_redacted": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "integration_count": len(integrations),
        "env_var_count": len(
            {
                name
                for item in integrations
                for name in (
                    item["env"].keys()
                    if isinstance(item.get("env"), dict)
                    else ()
                )
            }
        ),
        "missing_optional_env_vars": sorted(all_missing_optional),
        "missing_required_env_vars": sorted(all_missing_required),
        "authority_counts": authority_counts,
        "error_count": 0,
        "integrations": integrations,
    }
