import json
from pathlib import Path

from tradingagents.dataflows.integration_registry import (
    build_integration_registry_report,
    load_integration_registry,
)
from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV

DATAFLOW_ROUTE_BY_MODULE = {
    "alpha_vantage": "alpha_vantage",
    "alpha_vantage_common": "alpha_vantage",
    "alpha_vantage_fundamentals": "alpha_vantage",
    "alpha_vantage_indicator": "alpha_vantage",
    "alpha_vantage_news": "alpha_vantage",
    "alpha_vantage_stock": "alpha_vantage",
    "google_news": "google_news_rss",
    "sec": "sec_edgar",
    "stockstats_utils": "stockstats",
    "y_finance": "yfinance",
    "yfinance_options": "yfinance_options",
    "yfinance_earnings_calendar": "yfinance_earnings_calendar",
    "yfinance_short_interest": "yfinance_short_interest",
}

INTERNAL_DATAFLOW_MODULES = {
    "__init__",
    "_official_common",
    "config",
    "decision_vendor_adapters",
    "integration_registry",
    "interface",
    "utils",
}

MODEL_PROVIDER_REGISTRY_NAME = {
    "google": "gemini",
    "ollama": None,
}


def _default_registry_by_name():
    return {item["name"]: item for item in load_integration_registry()}


def test_integration_registry_reports_env_presence_without_secret_values(tmp_path):
    registry_path = tmp_path / "research_integrations.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "integrations": [
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
                        "fallback_behavior": "skip_source_and_use_fallbacks",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = build_integration_registry_report(
        registry_path,
        env={"ALPHA_VANTAGE_API_KEY": "secret-value"},
    )
    serialized = json.dumps(report)

    assert "secret-value" not in serialized
    assert report["integrations"][0]["env"]["ALPHA_VANTAGE_API_KEY"] == {
        "present": True,
        "length": len("secret-value"),
        "required": True,
    }
    assert report["integrations"][0]["status"] == "env_ready"
    assert report["secrets_redacted"] is True


def test_missing_optional_keys_skip_cleanly_without_errors():
    report = build_integration_registry_report(
        env={
            "ALPACA_PAPER_API_KEY": "paper",
            "ALPACA_PAPER_SECRET_KEY": "paper-secret",
            "SEC_USER_AGENT": "TradingAgents test contact@example.com",
        }
    )
    by_name = {item["name"]: item for item in report["integrations"]}

    assert by_name["marketaux"]["status"] == "skipped_missing_env"
    assert "MARKETAUX_API_KEY" in report["missing_required_env_vars"]
    assert "MARKETAUX_API_TOKEN" in report["missing_optional_env_vars"]
    assert report["error_count"] == 0
    assert report["can_submit_orders"] is False
    assert report["execution_authority"] == "none"


def test_only_alpaca_uses_broker_boundary_trading_authority():
    report = build_integration_registry_report(env={})

    broker_boundaries = [
        item["name"]
        for item in report["integrations"]
        if item["trading_authority"] == "broker_boundary_only"
    ]
    non_alpaca_with_trading = [
        item["name"]
        for item in report["integrations"]
        if item["trading_authority"] != "none"
        and item["trading_authority"] != "broker_boundary_only"
    ]

    assert broker_boundaries == ["alpaca_paper", "alpaca_live"]
    assert non_alpaca_with_trading == []


def test_binance_is_read_only_runtime_checked_context():
    registry = load_integration_registry()
    binance = next(item for item in registry if item["name"] == "binance_public")
    report = build_integration_registry_report(env={})
    by_name = {item["name"]: item for item in report["integrations"]}

    assert binance["read_authority"] == "read_only"
    assert binance["write_authority"] == "none"
    assert binance["trading_authority"] == "none"
    assert by_name["binance_public"]["status"] == "requires_runtime_check"


def test_default_registry_covers_dataflow_vendor_modules():
    registry = _default_registry_by_name()
    dataflows_dir = Path(__file__).resolve().parents[1] / "tradingagents" / "dataflows"
    modules = {
        path.stem
        for path in dataflows_dir.glob("*.py")
        if path.stem not in INTERNAL_DATAFLOW_MODULES
    }

    missing = []
    for module in sorted(modules):
        registry_name = DATAFLOW_ROUTE_BY_MODULE.get(module, module)
        item = registry.get(registry_name)
        if not item:
            missing.append(module)
            continue
        assert item["route"].startswith("dataflow:")
        assert item["write_authority"] == "none"
        assert item["trading_authority"] == "none"

    assert missing == []


def test_default_registry_covers_llm_provider_key_map():
    registry = _default_registry_by_name()

    missing = []
    for provider, env_var in PROVIDER_API_KEY_ENV.items():
        registry_name = MODEL_PROVIDER_REGISTRY_NAME.get(provider, provider)
        if registry_name is None:
            continue
        item = registry.get(registry_name)
        if not item:
            missing.append(provider)
            continue
        if env_var:
            assert env_var in item["env_vars"]
        assert item["category"] == "model"
        assert item["write_authority"] == "none"
        assert item["trading_authority"] == "none"

    assert missing == []


def test_example_registry_matches_default_integration_names():
    default_names = {item["name"] for item in load_integration_registry()}
    example_path = Path(__file__).resolve().parents[1] / "config" / "research_integrations.example.json"
    example_names = {item["name"] for item in load_integration_registry(example_path)}

    assert example_names == default_names
