"""Tests for TRADINGAGENTS_* env-var overlay onto DEFAULT_CONFIG."""

from __future__ import annotations

import importlib

import pytest

import tradingagents.default_config as default_config_module


def _reload_with_env(monkeypatch, **overrides):
    """Set/clear env vars then reload default_config to re-evaluate DEFAULT_CONFIG."""
    for key in list(default_config_module._ENV_OVERRIDES):
        monkeypatch.setenv(key, "")
    for key, val in overrides.items():
        monkeypatch.setenv(key, val)
    return importlib.reload(default_config_module)


def test_no_env_uses_built_in_defaults(monkeypatch):
    dc = _reload_with_env(monkeypatch)
    assert dc.DEFAULT_CONFIG["llm_provider"] == "openai"
    assert dc.DEFAULT_CONFIG["deep_think_llm"] == "gpt-5.4"
    assert dc.DEFAULT_CONFIG["quick_think_llm"] == "gpt-5.4-mini"
    assert dc.DEFAULT_CONFIG["backend_url"] is None
    assert dc.DEFAULT_CONFIG["llm_timeout_seconds"] == 120.0
    assert dc.DEFAULT_CONFIG["llm_max_retries"] == 2
    assert dc.DEFAULT_CONFIG["llm_max_output_tokens"] == 4096
    assert dc.DEFAULT_CONFIG["max_debate_rounds"] == 1
    assert dc.DEFAULT_CONFIG["checkpoint_enabled"] is False


def test_string_overrides(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_LLM_PROVIDER="google",
        TRADINGAGENTS_DEEP_THINK_LLM="gemini-3-pro-preview",
        TRADINGAGENTS_QUICK_THINK_LLM="gemini-3-flash-preview",
        TRADINGAGENTS_LLM_BACKEND_URL="https://example.invalid/v1",
        TRADINGAGENTS_OUTPUT_LANGUAGE="Chinese",
    )
    assert dc.DEFAULT_CONFIG["llm_provider"] == "google"
    assert dc.DEFAULT_CONFIG["deep_think_llm"] == "gemini-3-pro-preview"
    assert dc.DEFAULT_CONFIG["quick_think_llm"] == "gemini-3-flash-preview"
    assert dc.DEFAULT_CONFIG["backend_url"] == "https://example.invalid/v1"
    assert dc.DEFAULT_CONFIG["output_language"] == "Chinese"


def test_int_coercion(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_MAX_DEBATE_ROUNDS="3",
        TRADINGAGENTS_MAX_RISK_ROUNDS="2",
        TRADINGAGENTS_ANALYST_CONCURRENCY_LIMIT="2",
        TRADINGAGENTS_LLM_MAX_RETRIES="4",
        TRADINGAGENTS_LLM_MAX_OUTPUT_TOKENS="3072",
    )
    assert dc.DEFAULT_CONFIG["max_debate_rounds"] == 3
    assert isinstance(dc.DEFAULT_CONFIG["max_debate_rounds"], int)
    assert dc.DEFAULT_CONFIG["max_risk_discuss_rounds"] == 2
    assert isinstance(dc.DEFAULT_CONFIG["max_risk_discuss_rounds"], int)
    assert dc.DEFAULT_CONFIG["analyst_concurrency_limit"] == 2
    assert isinstance(dc.DEFAULT_CONFIG["analyst_concurrency_limit"], int)
    assert dc.DEFAULT_CONFIG["llm_max_retries"] == 4
    assert dc.DEFAULT_CONFIG["llm_max_output_tokens"] == 3072


def test_float_coercion(monkeypatch):
    dc = _reload_with_env(monkeypatch, TRADINGAGENTS_LLM_TIMEOUT_SECONDS="45.5")

    assert dc.DEFAULT_CONFIG["llm_timeout_seconds"] == 45.5


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("true", True), ("True", True), ("1", True), ("yes", True), ("on", True),
        ("false", False), ("False", False), ("0", False), ("no", False), ("off", False),
    ],
)
def test_bool_coercion(monkeypatch, raw, expected):
    dc = _reload_with_env(monkeypatch, TRADINGAGENTS_CHECKPOINT_ENABLED=raw)
    assert dc.DEFAULT_CONFIG["checkpoint_enabled"] is expected


def test_empty_env_value_is_passthrough(monkeypatch):
    """Empty TRADINGAGENTS_* values must not clobber the built-in default."""
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_LLM_PROVIDER="",
        TRADINGAGENTS_MAX_DEBATE_ROUNDS="",
    )
    assert dc.DEFAULT_CONFIG["llm_provider"] == "openai"
    assert dc.DEFAULT_CONFIG["max_debate_rounds"] == 1


def test_invalid_int_raises(monkeypatch):
    """Garbage int values should surface a ValueError at import, not silently misconfigure."""
    monkeypatch.setenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "not-a-number")
    with pytest.raises(ValueError):
        importlib.reload(default_config_module)
    # Restore module state for subsequent tests in this process
    monkeypatch.delenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", raising=False)
    importlib.reload(default_config_module)


def test_unknown_env_var_is_ignored(monkeypatch):
    """Env vars outside _ENV_OVERRIDES must not bleed into DEFAULT_CONFIG."""
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_NONEXISTENT_KEY="oops",
    )
    assert "nonexistent_key" not in dc.DEFAULT_CONFIG


def test_alpaca_execution_overrides(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_ALPACA_PAPER_ENABLED="true",
        TRADINGAGENTS_ALPACA_LIVE_MIRROR_ENABLED="true",
        TRADINGAGENTS_PAPER_EXPOSURE_LIMIT="1000",
        TRADINGAGENTS_LIVE_MIRROR_RATIO="0.10",
        TRADINGAGENTS_LIVE_EXPOSURE_LIMIT="100",
        TRADINGAGENTS_RISK_POSTURE="performance_seeking",
    )

    assert dc.DEFAULT_CONFIG["alpaca_paper_enabled"] is True
    assert dc.DEFAULT_CONFIG["alpaca_live_mirror_enabled"] is True
    assert dc.DEFAULT_CONFIG["paper_exposure_limit"] == 1000.0
    assert dc.DEFAULT_CONFIG["live_mirror_ratio"] == 0.10
    assert dc.DEFAULT_CONFIG["live_exposure_limit"] == 100.0
    assert dc.DEFAULT_CONFIG["risk_posture"] == "performance_seeking"


def test_ollama_profile_overrides(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_OLLAMA_TEMPERATURE="0",
        TRADINGAGENTS_OLLAMA_MAX_COMPLETION_TOKENS="350",
        TRADINGAGENTS_OLLAMA_TOP_P="0.9",
        TRADINGAGENTS_OLLAMA_PRESENCE_PENALTY="0.1",
        TRADINGAGENTS_OLLAMA_EXTRA_BODY_JSON=(
            '{"think": false, "options": {"num_ctx": 4096, "num_predict": 350}}'
        ),
    )

    assert dc.DEFAULT_CONFIG["ollama_temperature"] == 0.0
    assert dc.DEFAULT_CONFIG["ollama_max_completion_tokens"] == 350
    assert dc.DEFAULT_CONFIG["ollama_top_p"] == 0.9
    assert dc.DEFAULT_CONFIG["ollama_presence_penalty"] == 0.1
    assert dc.DEFAULT_CONFIG["ollama_extra_body"] == {
        "think": False,
        "options": {"num_ctx": 4096, "num_predict": 350},
    }


def test_invalid_ollama_extra_body_json_raises(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_OLLAMA_EXTRA_BODY_JSON", "[1, 2, 3]")
    with pytest.raises(ValueError):
        importlib.reload(default_config_module)
    monkeypatch.delenv("TRADINGAGENTS_OLLAMA_EXTRA_BODY_JSON", raising=False)
    importlib.reload(default_config_module)
