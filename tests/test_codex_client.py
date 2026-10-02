import json
import subprocess
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, ValidationError

from tradingagents.llm_clients.codex_client import (
    _DISABLED_HOST_NOTICE,
    CODEX_ROUTE,
    CodexChatModel,
    CodexRunnerError,
)
from tradingagents.llm_clients.factory import create_llm_client


@pytest.fixture(autouse=True)
def runner_version(monkeypatch):
    from tradingagents.llm_clients.codex_client import codex_runner_version

    monkeypatch.setattr("tradingagents.llm_clients.codex_client.codex_runner_version", lambda: "codex-cli 0.159.2")
    return codex_runner_version


@pytest.mark.parametrize("value", ["codex-cli 0.159.2", "codex-cli 0.159.2-beta.1"])
def test_installed_runner_version_is_recorded(runner_version, monkeypatch, value):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=value))
    assert runner_version() == value


@pytest.mark.parametrize("value", ["", "unexpected runner", "codex-cli 0.159.2\nextra"])
def test_unestablished_runner_version_fails(runner_version, monkeypatch, value):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=value))
    with pytest.raises(CodexRunnerError, match="version"):
        runner_version()


def events(reply, usage=None):
    return "\n".join(json.dumps(x) for x in [
        {"type": "thread.started", "thread_id": "fixture"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(reply)}},
        {"type": "turn.completed", "usage": usage or {"input_tokens": 10, "output_tokens": 4, "cached_input_tokens": 2}},
    ])


@pytest.fixture
def transport(monkeypatch):
    calls = []
    reply = {"content": "fixture answer", "tool_calls": []}

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=events(reply), stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    return calls, reply


def test_factory_and_subscription_transport(transport, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "never-pass-this")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://never-use.invalid")
    monkeypatch.setenv("ALPACA_API_KEY", "private-broker-key")
    model = create_llm_client("codex", "gpt-6-luna").get_llm()
    answer = model.invoke("A public arithmetic question")
    assert answer.content == "fixture answer"
    assert answer.response_metadata["billing_mode"] == "chatgpt_subscription"
    assert answer.response_metadata["api_cost_usd"] == 0
    assert answer.response_metadata["serving_revision"] is None
    assert answer.usage_metadata["total_tokens"] == 14
    command, args = transport[0][0]
    assert 'forced_login_method="chatgpt"' in command
    assert "--ignore-user-config" in command
    assert "--ephemeral" in command
    assert 'web_search="disabled"' in command
    for name in ["shell_tool", "apps", "plugins", "hooks", "multi_agent"]:
        assert command[command.index(name) - 1] == "--disable"
    assert "OPENAI_API_KEY" not in args["env"]
    assert "OPENAI_BASE_URL" not in args["env"]
    assert "ALPACA_API_KEY" not in args["env"]
    assert args["cwd"] != "./"
    assert "never-pass-this" not in args["input"]


@tool
def lookup_price(symbol: str) -> str:
    """Read a price already retained by the application."""
    raise AssertionError("Binding a tool must not execute it")


def test_bound_tool_and_history_roundtrip(transport):
    transport[1].update(content="", tool_calls=[{"name": "lookup_price", "arguments_json": '{"symbol":"AAPL"}'}])
    response = CodexChatModel().bind_tools([lookup_price]).invoke([
        HumanMessage(content="Use the saved price"),
        AIMessage(content="", tool_calls=[{"name": "lookup_price", "args": {"symbol": "AAPL"}, "id": "old"}]),
        ToolMessage(content="333.02", tool_call_id="old"),
    ])
    assert response.tool_calls[0]["args"] == {"symbol": "AAPL"}
    assert '"tool_call_id": "old"' in transport[0][0][1]["input"]
    assert len(transport[0]) == 1


class Decision(BaseModel):
    action: str
    confidence: float


def test_structured_output_uses_existing_pydantic_parser(transport):
    transport[1].update(content="", tool_calls=[{"name": "Decision", "arguments_json": '{"action":"HOLD","confidence":0.25}'}])
    result = CodexChatModel().with_structured_output(Decision).invoke("Public fixture")
    assert result == Decision(action="HOLD", confidence=0.25)


@pytest.mark.parametrize("calls", [
    [{"name": "unbound", "arguments_json": "{}"}],
    [{"name": "lookup_price", "arguments_json": "[]"}],
    [{"name": "lookup_price", "arguments_json": "{}"}],
    [{"name": "lookup_price", "arguments_json": '{"symbol":7}'}],
    [{"name": "lookup_price", "arguments_json": '{"symbol":"A","symbol":"B"}'}],
    [{"name": "lookup_price", "arguments_json": '{"symbol":NaN}'}],
    [{"name": "lookup_price", "arguments_json": {}, "extra": True}],
])
def test_malformed_or_unbound_tools_reject(transport, calls):
    transport[1]["tool_calls"] = calls
    with pytest.raises((CodexRunnerError, ValidationError)):
        CodexChatModel().bind_tools([lookup_price]).invoke("Public fixture")


@pytest.mark.parametrize("choice,calls", [("required", []), ("none", [{"name": "lookup_price", "arguments_json": '{"symbol":"AAPL"}'}])])
def test_tool_choice_is_enforced(transport, choice, calls):
    transport[1]["tool_calls"] = calls
    with pytest.raises(CodexRunnerError):
        CodexChatModel().bind_tools([lookup_price], tool_choice=choice).invoke("Public fixture")


@pytest.mark.parametrize("raw", [
    '{"type":"turn.failed"}',
    '{"type":"error"}',
    '[]',
    '{"type":"item.completed","item":{"type":"command_execution"}}',
    '{"type":"turn.completed","usage":{"input_tokens":true,"output_tokens":4}}',
    '{"type":"turn.completed"}',
    '{"type":"thread.started","type":"turn.completed"}',
])
def test_partial_failed_or_native_tool_events_reject(monkeypatch, raw):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=raw, stderr=""))
    with pytest.raises(CodexRunnerError):
        CodexChatModel().invoke("Public fixture")


@pytest.mark.parametrize("injected", [
    {"type": "unknown.protocol.event"},
    {"type": []},
    {"type": "item.updated", "item": {"type": "command_execution"}},
    {"type": "item.updated", "item": {"type": []}},
    {"type": "item.completed", "item": {"type": "agent_message", "text": '{"content":"second","tool_calls":[]}'}},
    {"type": "item.completed", "item": {"type": "agent_message", "text": None}},
])
def test_event_drift_and_repeated_final_messages_cannot_hide_in_a_valid_reply(monkeypatch, injected):
    lines = events({"content": "fixture answer", "tool_calls": []}).splitlines()
    lines.insert(2, json.dumps(injected))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="\n".join(lines), stderr=""))
    with pytest.raises(CodexRunnerError):
        CodexChatModel().invoke("Public fixture")


def test_after_completion_and_repeated_turn_start_are_rejected(monkeypatch):
    lines = events({"content": "fixture answer", "tool_calls": []}).splitlines()
    for stream in [lines + [json.dumps({"type": "item.started", "item": {"type": "reasoning"}})],
                   [lines[0], json.dumps({"type": "turn.started"}), json.dumps({"type": "turn.started"}), *lines[1:]]]:
        monkeypatch.setattr(subprocess, "run", lambda *a, value=stream, **k: SimpleNamespace(returncode=0, stdout="\n".join(value), stderr=""))
        with pytest.raises(CodexRunnerError):
            CodexChatModel().invoke("Public fixture")


def test_disabled_native_host_startup_notice(monkeypatch):
    notice = json.dumps({"type": "item.completed", "item": {"type": "error", "message": _DISABLED_HOST_NOTICE}})
    raw = notice + "\n" + events({"content": "4", "tool_calls": []})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=raw, stderr=""))
    assert CodexChatModel().invoke("2+2").content == "4"


@pytest.mark.parametrize("item", [None, {"type": "error", "message": "Unexpected startup failure"}, {"type": "command_execution"}])
def test_unexpected_startup_items_fail(monkeypatch, item):
    raw = json.dumps({"type": "item.started", "item": item}) + "\n" + events({"content": "4", "tool_calls": []})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=raw, stderr=""))
    with pytest.raises(CodexRunnerError):
        CodexChatModel().invoke("2+2")


def test_failure_has_no_retry_or_secret_error_echo(monkeypatch):
    calls = []

    def failed(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1, stdout="", stderr="private-token-in-error")

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(CodexRunnerError) as caught:
        CodexChatModel().invoke("Public fixture")
    assert "private-token" not in str(caught.value)
    assert len(calls) == 1


def test_timeout_has_no_retry(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("codex", 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(CodexRunnerError, match="timed out"):
        CodexChatModel().invoke("Public fixture")


def test_input_output_bounds_and_invalid_model(transport):
    with pytest.raises(ValueError, match="byte limit"):
        CodexChatModel(max_input_bytes=5).invoke("Public fixture")
    assert transport[0] == []
    with pytest.raises(ValueError, match="model"):
        CodexChatModel(model_name="unexpected-model").invoke("Public fixture")
    with pytest.raises(CodexRunnerError, match="output limit"):
        CodexChatModel(max_output_chars=3).invoke("Public fixture")


@pytest.mark.parametrize("url", ["https://api.openai.com/v1", "http://localhost:8047", "codex://remote/exec"])
def test_api_endpoint_is_not_accepted(url):
    with pytest.raises(ValueError, match="API endpoint"):
        create_llm_client("codex", "gpt-6-luna", base_url=url).get_llm()


def test_subscription_key_prompt_is_noop(monkeypatch):
    from cli import utils
    from tradingagents.llm_clients.api_key_env import get_api_key_env

    monkeypatch.setattr(utils.questionary, "password", lambda *a, **k: pytest.fail("No API key prompt"))
    assert get_api_key_env("codex") is None
    assert utils.ensure_api_key("codex") is None
    assert create_llm_client("codex", "gpt-6-luna", CODEX_ROUTE).get_llm().model_name == "gpt-6-luna"


def test_overnight_default_uses_subscription_without_ollama_probe(monkeypatch):
    from cli import main

    for name in ("TRADINGAGENTS_OVERNIGHT_LLM_PROVIDER", "TRADINGAGENTS_OVERNIGHT_LLM_BACKEND_URL", "TRADINGAGENTS_OVERNIGHT_QUICK_THINK_LLM", "TRADINGAGENTS_OVERNIGHT_DEEP_THINK_LLM"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(main.DEFAULT_CONFIG, "llm_provider", "codex")
    monkeypatch.setattr(main, "_ollama_endpoint_healthy", lambda _: pytest.fail("Subscription route must not probe Ollama"))
    config = main._build_overnight_graph_config_overrides(
        graph_profile="compact", llm_provider=None, quick_think_llm=None,
        deep_think_llm=None, backend_url=None, max_completion_tokens=220,
    )
    assert config["llm_provider"] == "codex"
    assert config["backend_url"] == CODEX_ROUTE
    assert "overnight_graph_disabled_reason" not in config


def test_runner_preserves_returned_outcome_and_reports_unknown_serving_identity(monkeypatch):
    rows = [{"type": "thread.started", "thread_id": "observed-thread"},
            {"type": "item.completed", "item": {"id": "observed-item", "type": "agent_message", "text": json.dumps({"content": "4", "tool_calls": []})}},
            {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 4}}]
    raw = "\n".join(json.dumps(row) for row in rows)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=raw, stderr=""))
    result = CodexChatModel().invoke("2+2")
    meta = result.response_metadata
    assert meta["id"] == "codex:observed-thread:observed-item"
    assert meta["returned_model_name"] is None and meta["returned_provider_identity"] is None
    assert meta["subscription_cost_usd"] is None
    assert meta["model_identity_source"] == "requested_cli_argument_only"
    assert meta["runner_outcome"] == {"thread_id": "observed-thread", "item_id": "observed-item"}


def test_missing_runner_outcome_is_not_synthesized(transport):
    result = CodexChatModel().invoke("Public fixture")
    assert result.response_metadata["id"] is None
    assert result.response_metadata["runner_outcome"]["item_id"] is None
