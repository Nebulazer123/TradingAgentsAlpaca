"""Analysis-only inspection and exact-clear command coverage."""

import inspect
import json
from contextlib import nullcontext
from types import SimpleNamespace
from typing import TypedDict

import pytest
from langgraph.graph import END, StateGraph
from typer.testing import CliRunner

from cli import main as cli_main
from cli.main import app
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.checkpoint_identity import build_checkpoint_run_identity
from tradingagents.graph.checkpoint_runtime_identity import CheckpointRuntimeIdentityError
from tradingagents.graph.checkpointer import get_checkpointer, thread_id

runner = CliRunner()


class _CheckpointState(TypedDict, total=False):
    company_of_interest: str
    trade_date: str
    checkpoint_run_identity: dict[str, object]
    run_id: str
    run_started_at: str
    final_trade_decision: str
    market_report: str


def _identity():
    return build_checkpoint_run_identity(
        identity_schema_version=2,
        clean_source_revision="a" * 40,
        source_tree_dirty=False,
        uv_lock_sha256="b" * 64,
        selected_analysts=("market", "news"),
        asset_type="stock",
        max_debate_rounds=1,
        max_risk_discuss_rounds=1,
        max_analyst_tool_rounds=8,
        max_recur_limit=100,
        analyst_concurrency_limit=1,
        tool_free_analysts=(),
        requested_provider="openrouter",
        requested_quick_model="openai/gpt-5-mini",
        requested_deep_model="anthropic/claude-sonnet-4-5",
        backend_route_identity="https://router.example/v1?region=us",
        output_language="English",
        provider_reasoning_settings={"thinking": {"effort": "high"}},
        graph_topology_sha256="c" * 64,
        agent_prompt_surface_sha256="d" * 64,
        bound_tool_surface_sha256="e" * 64,
        data_route_surface_sha256="f" * 64,
        packet_handoff_schema_version=1,
        learning_context_policy_identity="learning-context-policy-v2",
        trade_date_cutoff_policy_identity="market-date-cutoff-v1",
        learning_evidence_predecessor="1" * 64,
        decision_ledger_predecessor="2" * 64,
    )


def _write_checkpoint(data_dir, identity):
    builder = StateGraph(_CheckpointState)
    builder.add_node("done", lambda _state: {})
    builder.set_entry_point("done")
    builder.add_edge("done", END)
    with get_checkpointer(data_dir, "TEST") as saver:
        builder.compile(checkpointer=saver).invoke(
            {
                "company_of_interest": "TEST",
                "trade_date": "2026-04-20",
                "checkpoint_run_identity": identity.to_dict(),
                "run_id": "checkpoint-cli-test",
                "run_started_at": "2026-04-20T13:30:00+00:00",
                "final_trade_decision": "HOLD",
                "market_report": "Authorization: Bearer checkpoint-cli-secret",
            },
            config={"configurable": {"thread_id": thread_id("TEST", "2026-04-20", identity.identity_sha256)}},
        )


def test_checkpoint_status_command_is_analysis_only_and_redacts_state(monkeypatch, tmp_path):
    identity = _identity()
    _write_checkpoint(tmp_path, identity)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "data_cache_dir", str(tmp_path))

    def prohibited(*_args, **_kwargs):
        raise AssertionError("checkpoint inspection reached a protected surface")

    monkeypatch.setattr(cli_main, "_alpaca_clients", prohibited)
    monkeypatch.setattr(cli_main, "execute_paper_orders", prohibited)
    monkeypatch.setattr(cli_main, "maybe_write_live_strategy_selection", prohibited)

    result = runner.invoke(
        app,
        [
            "checkpoint-status",
            "--ticker",
            "TEST",
            "--trade-date",
            "2026-04-20",
            "--identity-digest",
            identity.identity_sha256,
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["compatibility"] == "compatible"
    assert payload["execution_authority"] == "none"
    assert payload["analysis_only"] is True
    assert "checkpoint-cli-secret" not in result.output


def test_checkpoint_clear_command_requires_the_exact_identity(monkeypatch, tmp_path):
    identity = _identity()
    _write_checkpoint(tmp_path, identity)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "data_cache_dir", str(tmp_path))

    wrong = "f" * 64
    wrong_result = runner.invoke(
        app,
        [
            "checkpoint-clear",
            "--ticker",
            "TEST",
            "--trade-date",
            "2026-04-20",
            "--identity-digest",
            wrong,
        ],
    )
    retained_result = runner.invoke(
        app,
        [
            "checkpoint-status",
            "--ticker",
            "TEST",
            "--trade-date",
            "2026-04-20",
            "--identity-digest",
            identity.identity_sha256,
        ],
    )
    exact_result = runner.invoke(
        app,
        [
            "checkpoint-clear",
            "--ticker",
            "TEST",
            "--trade-date",
            "2026-04-20",
            "--identity-digest",
            identity.identity_sha256,
        ],
    )

    assert wrong_result.exit_code == 0, wrong_result.output
    assert json.loads(wrong_result.output)["cleared"] is False
    assert json.loads(retained_result.output)["compatibility"] == "compatible"
    assert exact_result.exit_code == 0, exact_result.output
    assert json.loads(exact_result.output)["cleared"] is True


def test_broad_checkpoint_maintenance_requires_explicit_confirmation(monkeypatch, tmp_path):
    identity = _identity()
    _write_checkpoint(tmp_path, identity)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "data_cache_dir", str(tmp_path))

    result = runner.invoke(app, ["checkpoint-maintenance-clear-all"])

    assert result.exit_code != 0
    assert "--confirm" in result.output


def test_analyze_defaults_to_checkpointing_with_an_explicit_opt_out(monkeypatch):
    observed = []
    monkeypatch.setattr(
        cli_main,
        "run_analysis",
        lambda *, checkpoint: observed.append(checkpoint),
    )

    default = runner.invoke(app, ["analyze"])
    opt_out = runner.invoke(app, ["analyze", "--no-checkpoint"])

    assert default.exit_code == 0, default.output
    assert opt_out.exit_code == 0, opt_out.output
    assert observed == [True, False]


def test_checkpoint_enabled_interactive_analysis_blocks_before_graph_construction(
    monkeypatch,
):
    selections = {
        "ticker": "TEST",
        "analysis_date": "2026-04-20",
        "asset_type": "stock",
        "analysts": [SimpleNamespace(value="market")],
        "research_depth": 1,
        "shallow_thinker": "openai/gpt-5-mini",
        "deep_thinker": "anthropic/claude-sonnet-4-5",
        "backend_url": "https://router.example/v1?region=us",
        "llm_provider": "openrouter",
        "output_language": "English",
    }
    monkeypatch.setattr(cli_main, "get_user_selections", lambda: selections)
    monkeypatch.setattr(
        cli_main,
        "build_analysis_checkpoint_identity",
        lambda **_kwargs: (_ for _ in ()).throw(
            CheckpointRuntimeIdentityError("source tree is dirty")
        ),
    )
    monkeypatch.setattr(
        cli_main,
        "TradingAgentsGraph",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("identity failure must block graph construction")
        ),
    )

    with pytest.raises(CheckpointRuntimeIdentityError, match="dirty"):
        cli_main.run_analysis(checkpoint=True)


def test_checkpoint_defaults_remain_isolated_from_protected_surfaces():
    """The analysis-only default cannot propagate into broker or approval commands."""

    assert DEFAULT_CONFIG["checkpoint_enabled"] is False
    protected_commands = (
        cli_main.alpaca_submit,
        cli_main.alpaca_paper_tournament_run,
        cli_main.policy_sync_promotion,
        cli_main.alpaca_supervise_hourly,
    )
    for command in protected_commands:
        source = inspect.getsource(command)
        assert "checkpoint_run_identity" not in source
        assert "build_analysis_checkpoint_identity" not in source


def test_no_checkpoint_interactive_analysis_saves_an_explicit_nonqualifying_receipt(
    monkeypatch, tmp_path,
):
    from tradingagents.graph.propagation import Propagator

    selections = {
        "ticker": "TEST", "analysis_date": "2026-04-20", "asset_type": "stock",
        "analysts": [SimpleNamespace(value="market")], "research_depth": 1,
        "shallow_thinker": "test-quick", "deep_thinker": "test-deep",
        "backend_url": "https://router.example/v1", "llm_provider": "openrouter",
    }
    final_state = {"messages": [], "market_report": "Saved analysis", "final_trade_decision": "HOLD"}
    configs = []

    class FakeGraph:
        def __init__(self, _analysts, *, config, **_kwargs):
            configs.append(dict(config))
            self.propagator = Propagator()
            self.graph = SimpleNamespace(stream=lambda *_args, **_kwargs: iter([final_state]))

        def process_signal(self, signal):
            return signal

    def prohibited(*_args, **_kwargs):
        raise AssertionError("opt-out reached identity, model, or protected operations")

    monkeypatch.setattr(cli_main, "get_user_selections", lambda: selections)
    monkeypatch.setattr(cli_main, "TradingAgentsGraph", FakeGraph)
    monkeypatch.setattr(cli_main, "build_analysis_checkpoint_identity", prohibited)
    monkeypatch.setattr(cli_main, "_alpaca_clients", prohibited)
    monkeypatch.setattr(cli_main, "execute_paper_orders", prohibited)
    monkeypatch.setattr(cli_main, "maybe_write_live_strategy_selection", prohibited)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", str(tmp_path / "results"))
    monkeypatch.setattr(cli_main, "message_buffer", cli_main.MessageBuffer())
    monkeypatch.setattr(cli_main, "Live", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(cli_main, "update_display", lambda *_args, **_kwargs: None)
    prompts = iter(["Y", str(tmp_path / "saved"), "N"])
    monkeypatch.setattr(cli_main.typer, "prompt", lambda *_args, **_kwargs: next(prompts))

    result = runner.invoke(app, ["analyze", "--no-checkpoint"])

    assert result.exit_code == 0, (result.output, result.exception)
    expected = {
        "mode": "disabled", "identity_digest": None, "checkpoint_step": None,
        "qualifying": False, "analysis_only": True,
        "execution_authority": "none", "can_submit_orders": False,
    }
    for root in (tmp_path / "saved", tmp_path / "results/TEST/2026-04-20/reports"):
        assert json.loads((root / "checkpoint_receipt.json").read_text()) == expected
    assert "Saved analysis" in (tmp_path / "saved/complete_report.md").read_text()
    assert configs[0]["checkpoint_enabled"] is False
    assert "checkpoint_run_identity" not in configs[0]
    assert "checkpoint_receipt" not in final_state
