from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients import azure_client, google_client, openai_client


def test_trading_graph_adds_provider_neutral_bounds_for_openai():
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {
        "llm_provider": "openai",
        "llm_timeout_seconds": 45.0,
        "llm_max_retries": 1,
        "llm_max_output_tokens": 1234,
        "openai_reasoning_effort": "low",
    }

    assert graph._get_provider_kwargs() == {
        "timeout": 45.0,
        "max_retries": 1,
        "max_tokens": 1234,
        "reasoning_effort": "low",
    }


def test_trading_graph_maps_google_output_bound_to_gemini_kwarg():
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {
        "llm_provider": "google",
        "llm_timeout_seconds": 60.0,
        "llm_max_retries": 2,
        "llm_max_output_tokens": 2048,
        "google_thinking_level": "minimal",
    }

    assert graph._get_provider_kwargs() == {
        "timeout": 60.0,
        "max_retries": 2,
        "max_output_tokens": 2048,
        "thinking_level": "minimal",
    }


def test_trading_graph_ollama_profile_overrides_generic_output_bound():
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {
        "llm_provider": "ollama",
        "llm_timeout_seconds": 90.0,
        "llm_max_retries": 0,
        "llm_max_output_tokens": 4096,
        "ollama_temperature": 0.0,
        "ollama_max_completion_tokens": 350,
        "ollama_top_p": None,
        "ollama_presence_penalty": None,
        "ollama_extra_body": None,
    }

    assert graph._get_provider_kwargs() == {
        "timeout": 90.0,
        "max_retries": 0,
        "max_tokens": 350,
        "temperature": 0.0,
    }


def test_openai_client_maps_timeout_to_request_timeout(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        openai_client,
        "NormalizedChatOpenAI",
        lambda **kwargs: captured.setdefault("kwargs", kwargs),
    )

    openai_client.OpenAIClient(
        model="gpt-5.4",
        provider="openai",
        api_key="placeholder",
        timeout=42,
        max_retries=1,
        max_tokens=1024,
    ).get_llm()

    assert captured["kwargs"]["request_timeout"] == 42
    assert "timeout" not in captured["kwargs"]
    assert captured["kwargs"]["max_retries"] == 1
    assert captured["kwargs"]["max_tokens"] == 1024
    assert captured["kwargs"]["use_responses_api"] is True


def test_azure_client_maps_timeout_and_output_bound(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        azure_client,
        "NormalizedAzureChatOpenAI",
        lambda **kwargs: captured.setdefault("kwargs", kwargs),
    )

    azure_client.AzureOpenAIClient(
        model="deployment",
        azure_endpoint="https://azure.example.invalid",
        api_version="2026-01-01",
        timeout=43,
        max_retries=2,
        max_tokens=2048,
    ).get_llm()

    assert captured["kwargs"]["request_timeout"] == 43
    assert "timeout" not in captured["kwargs"]
    assert captured["kwargs"]["max_retries"] == 2
    assert captured["kwargs"]["max_tokens"] == 2048


def test_google_client_forwards_gemini_output_bound(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        google_client,
        "NormalizedChatGoogleGenerativeAI",
        lambda **kwargs: captured.setdefault("kwargs", kwargs),
    )

    google_client.GoogleClient(
        model="gemini-2.5-flash-lite",
        google_api_key="placeholder",
        timeout=44,
        max_retries=1,
        max_output_tokens=1536,
    ).get_llm()

    assert captured["kwargs"]["timeout"] == 44
    assert captured["kwargs"]["max_retries"] == 1
    assert captured["kwargs"]["max_output_tokens"] == 1536
