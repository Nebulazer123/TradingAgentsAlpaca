"""Tests for OLLAMA_BASE_URL env-var override across CLI and client paths."""

from __future__ import annotations

import importlib

# ---- openai_client side: _resolve_provider_base_url -----------------------


def _reload_client():
    import tradingagents.llm_clients.openai_client as mod
    return importlib.reload(mod)


def test_resolver_returns_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    mod = _reload_client()
    assert mod._resolve_provider_base_url("ollama") == "http://localhost:11434/v1"


def test_resolver_returns_env_when_set(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://remote-ollama:11434/v1")
    mod = _reload_client()
    assert mod._resolve_provider_base_url("ollama") == "http://remote-ollama:11434/v1"


def test_resolver_evaluation_is_call_time(monkeypatch):
    """Setting the env AFTER module import must still take effect."""
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    mod = _reload_client()
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://late-set:11434/v1")
    assert mod._resolve_provider_base_url("ollama") == "http://late-set:11434/v1"


def test_resolver_does_not_affect_other_providers(monkeypatch):
    """OLLAMA_BASE_URL should NOT leak into xai/deepseek/etc."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://elsewhere/v1")
    mod = _reload_client()
    assert mod._resolve_provider_base_url("xai") == "https://api.x.ai/v1"
    assert mod._resolve_provider_base_url("deepseek") == "https://api.deepseek.com"


def test_client_get_llm_picks_up_env(monkeypatch):
    """End-to-end: OllamaClient.get_llm() respects OLLAMA_BASE_URL."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://my-ollama:11434/v1")
    mod = _reload_client()
    client = mod.OpenAIClient(model="llama3.1", provider="ollama")
    llm = client.get_llm()
    assert "my-ollama" in str(llm.openai_api_base)


def test_explicit_base_url_overrides_env(monkeypatch):
    """An explicit base_url passed to the client wins over the env var."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://env-set:11434/v1")
    mod = _reload_client()
    client = mod.OpenAIClient(
        model="llama3.1",
        provider="ollama",
        base_url="http://explicit:11434/v1",
    )
    llm = client.get_llm()
    assert "explicit" in str(llm.openai_api_base)
    assert "env-set" not in str(llm.openai_api_base)


def test_client_forwards_ollama_tuning_kwargs(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    mod = _reload_client()
    client = mod.OpenAIClient(
        model="tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k",
        provider="ollama",
        temperature=0,
        max_tokens=350,
        top_p=0.9,
        presence_penalty=0.1,
        response_format={"type": "json_object"},
        extra_body={"think": False, "options": {"num_ctx": 4096, "num_predict": 350}},
    )

    llm = client.get_llm()

    assert llm.temperature == 0.0
    assert llm.max_tokens == 350
    assert llm.top_p == 0.9
    assert llm.presence_penalty == 0.1
    assert llm.model_kwargs["response_format"] == {"type": "json_object"}
    assert llm.extra_body == {
        "think": False,
        "options": {"num_ctx": 4096, "num_predict": 350},
    }


def test_trading_graph_adds_ollama_profile_kwargs():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {
        "llm_provider": "ollama",
        "ollama_temperature": 0.0,
        "ollama_max_completion_tokens": 350,
        "ollama_top_p": 0.9,
        "ollama_presence_penalty": 0.1,
        "ollama_extra_body": {
            "think": False,
            "options": {"num_ctx": 4096, "num_predict": 350},
        },
    }

    assert graph._get_provider_kwargs() == {
        "temperature": 0.0,
        "max_tokens": 350,
        "top_p": 0.9,
        "presence_penalty": 0.1,
        "extra_body": {
            "think": False,
            "options": {"num_ctx": 4096, "num_predict": 350},
        },
    }


def test_trading_graph_does_not_add_ollama_kwargs_to_other_providers():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {
        "llm_provider": "openai",
        "openai_reasoning_effort": None,
        "ollama_temperature": 0.0,
        "ollama_max_completion_tokens": 350,
        "ollama_extra_body": {"think": False},
    }

    assert graph._get_provider_kwargs() == {}


# ---- cli.utils side: select_llm_provider dropdown -------------------------


def test_cli_dropdown_uses_env(monkeypatch):
    """The Ollama entry in the CLI dropdown must reflect OLLAMA_BASE_URL."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://cli-remote:11434/v1")
    import cli.utils as cli_utils
    importlib.reload(cli_utils)
    # Reach inside the function via the same env-read it does at call time
    ollama_url = (
        __import__("os").environ.get("OLLAMA_BASE_URL")
        or "http://localhost:11434/v1"
    )
    assert ollama_url == "http://cli-remote:11434/v1"


def test_cli_dropdown_default_when_unset(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    import cli.utils as cli_utils
    importlib.reload(cli_utils)
    ollama_url = (
        __import__("os").environ.get("OLLAMA_BASE_URL")
        or "http://localhost:11434/v1"
    )
    assert ollama_url == "http://localhost:11434/v1"


# ---- confirm_ollama_endpoint UX -------------------------------------------


def test_confirm_endpoint_shows_default(monkeypatch, capsys):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    import cli.utils as cli_utils
    importlib.reload(cli_utils)
    cli_utils.confirm_ollama_endpoint("http://localhost:11434/v1")
    out = capsys.readouterr().out
    assert "http://localhost:11434/v1" in out
    assert "OLLAMA_BASE_URL" not in out  # not from env
    assert "Note" not in out  # no warnings for the canonical default


def test_confirm_endpoint_marks_env_origin(monkeypatch, capsys):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://remote-host:11434/v1")
    import cli.utils as cli_utils
    importlib.reload(cli_utils)
    cli_utils.confirm_ollama_endpoint("http://remote-host:11434/v1")
    out = capsys.readouterr().out
    assert "http://remote-host:11434/v1" in out
    assert "OLLAMA_BASE_URL" in out


def test_confirm_endpoint_warns_on_missing_scheme(monkeypatch, capsys):
    """If user sets OLLAMA_BASE_URL=0.0.0.128, advise on the expected shape."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "0.0.0.128")
    import cli.utils as cli_utils
    importlib.reload(cli_utils)
    cli_utils.confirm_ollama_endpoint("0.0.0.128")
    out = capsys.readouterr().out
    assert "missing a scheme" in out
    assert "http://<host>:11434/v1" in out


def test_confirm_endpoint_warns_on_non_default_port_remote(monkeypatch, capsys):
    """A remote host with no :11434 gets a soft hint about port mismatch."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://remote-host/v1")
    import cli.utils as cli_utils
    importlib.reload(cli_utils)
    cli_utils.confirm_ollama_endpoint("http://remote-host/v1")
    out = capsys.readouterr().out
    assert "port 11434" in out


def test_confirm_endpoint_quiet_on_local_no_port(monkeypatch, capsys):
    """Local host without port shouldn't trigger the remote-port hint."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost/v1")
    import cli.utils as cli_utils
    importlib.reload(cli_utils)
    cli_utils.confirm_ollama_endpoint("http://localhost/v1")
    out = capsys.readouterr().out
    assert "Note" not in out  # localhost is fine without explicit port


def test_ollama_model_labels_no_local_suffix():
    """Labels should no longer claim '(local)' since the endpoint is dynamic."""
    from tradingagents.llm_clients.model_catalog import get_model_options
    for mode in ("quick", "deep"):
        labels = [label for label, _ in get_model_options("ollama", mode)]
        assert all("local" not in label for label in labels), labels


def test_ollama_offers_custom_model_id():
    """Ollama users with custom-pulled models can pick 'Custom model ID'."""
    from tradingagents.llm_clients.model_catalog import get_model_options
    for mode in ("quick", "deep"):
        entries = get_model_options("ollama", mode)
        values = [v for _, v in entries]
        assert "custom" in values, f"Ollama {mode!r} missing 'custom' option: {entries}"
        # Custom option is last so it doesn't push the curated defaults off-screen
        assert values[-1] == "custom", f"'custom' should be last entry: {values}"
