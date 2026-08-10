import json
import os
from collections.abc import Callable
from typing import Any

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_LLM_TIMEOUT_SECONDS":  "llm_timeout_seconds",
    "TRADINGAGENTS_LLM_MAX_RETRIES":      "llm_max_retries",
    "TRADINGAGENTS_LLM_MAX_OUTPUT_TOKENS": "llm_max_output_tokens",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_ANALYST_CONCURRENCY_LIMIT": "analyst_concurrency_limit",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_ALPACA_PAPER_ENABLED": "alpaca_paper_enabled",
    "TRADINGAGENTS_ALPACA_LIVE_MIRROR_ENABLED": "alpaca_live_mirror_enabled",
    "TRADINGAGENTS_PAPER_EXPOSURE_LIMIT": "paper_exposure_limit",
    "TRADINGAGENTS_LIVE_MIRROR_RATIO":    "live_mirror_ratio",
    "TRADINGAGENTS_LIVE_EXPOSURE_LIMIT":  "live_exposure_limit",
    "TRADINGAGENTS_RISK_POSTURE":         "risk_posture",
    "TRADINGAGENTS_OLLAMA_TEMPERATURE":   "ollama_temperature",
    "TRADINGAGENTS_OLLAMA_MAX_COMPLETION_TOKENS": "ollama_max_completion_tokens",
    "TRADINGAGENTS_OLLAMA_TOP_P":         "ollama_top_p",
    "TRADINGAGENTS_OLLAMA_PRESENCE_PENALTY": "ollama_presence_penalty",
    "TRADINGAGENTS_OLLAMA_EXTRA_BODY_JSON": "ollama_extra_body",
}


def _json_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("TRADINGAGENTS_OLLAMA_EXTRA_BODY_JSON must be a JSON object")
    return parsed


_ENV_COERCERS: dict[str, Callable[[str], Any]] = {
    "TRADINGAGENTS_LLM_TIMEOUT_SECONDS": float,
    "TRADINGAGENTS_LLM_MAX_RETRIES": int,
    "TRADINGAGENTS_LLM_MAX_OUTPUT_TOKENS": int,
    "TRADINGAGENTS_OLLAMA_TEMPERATURE": float,
    "TRADINGAGENTS_OLLAMA_MAX_COMPLETION_TOKENS": int,
    "TRADINGAGENTS_OLLAMA_TOP_P": float,
    "TRADINGAGENTS_OLLAMA_PRESENCE_PENALTY": float,
    "TRADINGAGENTS_OLLAMA_EXTRA_BODY_JSON": _json_object,
}


def _coerce(value: str, reference: object) -> object:
    """Coerce env-var string to the type of the existing default value."""
    if isinstance(reference, bool):
        return value.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _read_windows_user_env(name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg
        registry: Any = winreg

        with registry.OpenKey(registry.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = registry.QueryValueEx(key, name)
            return str(value)
    except OSError:
        return None


def _get_env_override(name: str) -> str | None:
    if name in os.environ:
        return os.environ.get(name)
    return _read_windows_user_env(name)


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = _get_env_override(env_var)
        if raw is None or raw == "":
            continue
        coercer = _ENV_COERCERS.get(env_var)
        config[key] = coercer(raw) if coercer else _coerce(raw, config.get(key))
    return config


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4-mini",
    "llm_timeout_seconds": 120.0,
    "llm_max_retries": 2,
    "llm_max_output_tokens": 4096,
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    "ollama_temperature": None,
    "ollama_max_completion_tokens": None,
    "ollama_top_p": None,
    "ollama_presence_penalty": None,
    "ollama_extra_body": None,
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    "analyst_concurrency_limit": 1,
    # News / data fetching parameters
    # Increase for longer lookback strategies or to broaden macro coverage;
    # decrease to reduce token usage in agent prompts.
    "news_article_limit": 20,             # max articles per ticker (ticker-news)
    "global_news_article_limit": 10,      # max articles for global/macro news
    "global_news_lookback_days": 7,       # macro news lookback window
    # Search queries used by get_global_news for macro headlines. Extend or
    # replace to broaden geographic / sector coverage.
    "global_news_queries": [
        "Federal Reserve interest rates inflation",
        "S&P 500 earnings GDP economic outlook",
        "geopolitical risk trade war sanctions",
        "ECB Bank of England BOJ central bank policy",
        "oil commodities supply chain energy",
    ],
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        # yfinance stays first for OHLCV because it returns the CSV shape the
        # market analyst and indicator tools already expect; Tiingo/Massive/AV
        # are fallback routes when available.
        "core_stock_apis": "yfinance,tiingo,massive,alpha_vantage",
        "technical_indicators": "yfinance,alpha_vantage",
        # Fundamentals/news prefer keyed, more authoritative sources first and
        # degrade to free/local fallbacks when optional keys are missing or
        # depleted.
        "fundamental_data": "fmp,eodhd,finnhub,sec,yfinance,alpha_vantage",
        "news_data": "marketaux,finnhub,newsapi,google_news,eodhd,tiingo,fmp,alpaca_news,yfinance,alpha_vantage",
        "macro_context": "fred,bls,bea,eia,treasury_fiscal",
        "sentiment_data": "stocktwits,reddit,eodhd",
        "event_microstructure_context": "local,fmp,yfinance_options,yfinance_short_interest,yfinance_earnings_calendar,official_release_calendar",
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    # Benchmark for alpha calculation in the reflection layer.
    # ``benchmark_ticker`` (when set) overrides the suffix map for all
    # tickers; leave it None to use ``benchmark_map`` for auto-detection
    # based on the ticker's exchange suffix. SPY remains the US default
    # so the reflection label keeps reading "Alpha vs SPY" for US tickers
    # while non-US tickers get their regional index automatically.
    "benchmark_ticker": None,
    "benchmark_map": {
        ".NS":  "^NSEI",    # NSE India (Nifty 50)
        ".BO":  "^BSESN",   # BSE India (Sensex)
        ".T":   "^N225",    # Tokyo (Nikkei 225)
        ".HK":  "^HSI",     # Hong Kong (Hang Seng)
        ".L":   "^FTSE",    # London (FTSE 100)
        ".TO":  "^GSPTSE",  # Toronto (TSX Composite)
        ".AX":  "^AXJO",    # Australia (ASX 200)
        "":     "SPY",      # default for US-listed tickers (no suffix)
    },
    # Alpaca paper/live mirror execution. Defaults are deliberately disabled:
    # submit commands must be opted in via env vars before any broker request is sent.
    "alpaca_paper_enabled": False,
    "alpaca_live_mirror_enabled": False,
    "paper_exposure_limit": 1000.0,
    "live_mirror_ratio": 0.10,
    "live_exposure_limit": 100.0,
    # Risk posture affects paper/research breadth only. It never relaxes
    # live-submit gates, risk envelopes, dry-run requirements, or live caps.
    "risk_posture": "balanced",
})
