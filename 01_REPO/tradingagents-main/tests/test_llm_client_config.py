import pytest

from tradingagents.llm_clients import azure_client as azure_mod
from tradingagents.llm_clients import google_client as google_mod


def test_google_gemini_25_minimal_uses_small_positive_thinking_budget(monkeypatch):
    captured = {}

    def fake_google(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(google_mod, "NormalizedChatGoogleGenerativeAI", fake_google)

    google_mod.GoogleClient(
        "gemini-2.5-flash",
        thinking_level="minimal",
        api_key="test-key",
    ).get_llm()

    assert captured["thinking_budget"] == google_mod.GEMINI_25_MINIMAL_THINKING_BUDGET
    assert captured["thinking_budget"] > 0


def test_google_gemini_3_pro_minimal_maps_to_low(monkeypatch):
    captured = {}

    def fake_google(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(google_mod, "NormalizedChatGoogleGenerativeAI", fake_google)

    google_mod.GoogleClient(
        "gemini-3-pro-preview",
        thinking_level="minimal",
        api_key="test-key",
    ).get_llm()

    assert captured["thinking_level"] == "low"
    assert "thinking_budget" not in captured


def test_azure_client_requires_endpoint_and_api_version(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENAI_API_VERSION", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "trade-deployment")

    with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
        azure_mod.AzureOpenAIClient("gpt-5.4", api_key="test-key").get_llm()


def test_azure_client_passes_explicit_required_config(monkeypatch):
    captured = {}

    def fake_azure(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(azure_mod, "NormalizedAzureChatOpenAI", fake_azure)

    azure_mod.AzureOpenAIClient(
        "gpt-5.4",
        base_url="https://example-resource.openai.azure.com/",
        api_key="test-key",
        api_version="2025-03-01-preview",
        azure_deployment="trade-deployment",
    ).get_llm()

    assert captured["azure_endpoint"] == "https://example-resource.openai.azure.com/"
    assert captured["api_version"] == "2025-03-01-preview"
    assert captured["azure_deployment"] == "trade-deployment"
