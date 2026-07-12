"""Shared pytest fixtures that prevent CI hangs when API keys are absent."""

import ipaddress
import socket
from unittest.mock import MagicMock, patch

import pytest


def pytest_configure(config):
    marker_descriptions = {
        "unit": "fast isolated unit tests",
        "integration": "tests requiring external services",
        "smoke": "quick sanity-check tests",
        "allow_network": "tests that intentionally use external network access",
    }
    for marker, description in marker_descriptions.items():
        config.addinivalue_line("markers", f"{marker}: {description}")


_API_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_CN_API_KEY",
    "ZHIPU_API_KEY",
    "ZHIPU_CN_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "ALPACA_PAPER_API_KEY",
    "ALPACA_PAPER_SECRET_KEY",
    "ALPACA_LIVE_API_KEY",
    "ALPACA_LIVE_SECRET_KEY",
    "BENZINGA_API_KEY",
    "BEA_API_KEY",
    "BLS_API_KEY",
    "COMPOSIO_API_KEY",
    "EODHD_API_KEY",
    "EODHD_API_TOKEN",
    "FINNHUB_API_KEY",
    "FMP_API_KEY",
    "FRED_API_KEY",
    "MARKETAUX_API_KEY",
    "MARKETAUX_API_TOKEN",
    "MASSIVE_API_KEY",
    "NEWSAPI_API_KEY",
    "POLYGON_API_KEY",
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "STOCKTWITS_ACCESS_TOKEN",
    "TIINGO_API_KEY",
)


@pytest.fixture(autouse=True)
def _dummy_api_keys(monkeypatch):
    for env_var in _API_KEY_ENV_VARS:
        monkeypatch.setenv(env_var, "placeholder")


_LOCAL_NETWORK_NAMES = {"localhost"}
_LOCAL_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)


def _is_local_network_host(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode("utf-8", errors="ignore")
    if not isinstance(host, str):
        return False
    normalized = host.strip("[]").lower()
    if normalized in _LOCAL_NETWORK_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return any(ip in network for network in _LOCAL_NETWORKS)


@pytest.fixture(autouse=True)
def _block_external_network(monkeypatch, request):
    if request.node.get_closest_marker("integration") or request.node.get_closest_marker(
        "allow_network"
    ):
        return

    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) and address else address
        if _is_local_network_host(host):
            return real_connect(self, address)
        raise RuntimeError(
            f"External network access is blocked in tests: {host!r}. "
            "Use mocks, localhost test servers, or mark the test integration/allow_network."
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest.fixture(autouse=True)
def _isolate_connector_health(monkeypatch, tmp_path):
    """Keep connector fault-injection telemetry out of real automation context."""
    from tradingagents.dataflows import _official_common as official_common

    official_common.reset_connector_health()
    monkeypatch.setattr(
        official_common,
        "CONNECTOR_HEALTH_PATH",
        tmp_path / "connector-health.json",
    )
    yield
    official_common.reset_connector_health()


@pytest.fixture()
def mock_llm_client():
    client = MagicMock()
    client.get_llm.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.factory.create_llm_client",
        return_value=client,
    ):
        yield client
