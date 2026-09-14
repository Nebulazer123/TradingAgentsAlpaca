import json
from pathlib import Path

import pytest

import cli.main as cli_main
from tradingagents.graph.checkpoint_runtime_identity import CheckpointRuntimeIdentityError
from tradingagents.research.original_workflow import (
    build_creator_workflow_status,
    write_creator_workflow_artifacts,
)


def _creator_final_state():
    return {
        "market_report": "Market analyst says controlled dip with support.",
        "sentiment_report": "Sentiment analyst says crowd is cautious.",
        "news_report": "News analyst says positive guidance is underpriced.",
        "fundamentals_report": "Fundamentals analyst says margins are improving.",
        "investment_debate_state": {
            "bull_history": "Bull researcher argues upside.",
            "bear_history": "Bear researcher argues valuation risk.",
            "judge_decision": "Research manager favors a watchlist entry.",
        },
        "trader_investment_plan": "Trader proposes wait for pullback support.",
        "risk_debate_state": {
            "aggressive_history": "Aggressive risk analyst accepts small paper risk.",
            "neutral_history": "Neutral risk analyst wants confirmation.",
            "conservative_history": "Conservative risk analyst wants cash default.",
            "judge_decision": "**Rating**: Overweight\nPortfolio manager approves analysis-only watch.",
        },
        "final_trade_decision": "**Rating**: Overweight\nPortfolio manager approves analysis-only watch.",
    }


def test_creator_workflow_writer_preserves_full_role_artifacts(tmp_path):
    packet = write_creator_workflow_artifacts(
        _creator_final_state(),
        symbol="NVDA",
        trade_date="2026-06-03",
        output_root=tmp_path,
        rating="Overweight",
        signal="Overweight",
    )

    symbol_root = tmp_path / "NVDA"
    assert packet["analysis_only"] is True
    assert packet["execution_authority"] == "none"
    assert "submit_order" in packet["forbidden_effects"]
    assert packet["symbol"] == "NVDA"
    assert packet["trade_date"] == "2026-06-03"
    assert packet["role_count"] == 12
    assert (symbol_root / "1_analysts" / "market.md").exists()
    assert (symbol_root / "1_analysts" / "sentiment.md").exists()
    assert (symbol_root / "2_research" / "bull.md").exists()
    assert (symbol_root / "3_trading" / "trader.md").exists()
    assert (symbol_root / "4_risk" / "aggressive.md").exists()
    assert (symbol_root / "5_portfolio" / "decision.md").exists()
    assert Path(packet["complete_report_path"]).exists()
    assert Path(packet["packet_path"]).exists()

    saved = json.loads(Path(packet["packet_path"]).read_text(encoding="utf-8"))
    assert saved["role_count"] == 12
    assert saved["execution_authority"] == "none"
    assert {item["role"] for item in saved["role_artifacts"]} >= {
        "market_analyst",
        "bull_researcher",
        "trader",
        "portfolio_manager",
    }


def test_saved_report_preserves_supplied_checkpoint_receipt_without_inventing_one(tmp_path):
    state = _creator_final_state()
    cli_main.save_report_to_disk(state, "TEST", tmp_path / "generic")
    assert not (tmp_path / "generic/checkpoint_receipt.json").exists()

    receipt = {
        "mode": "fresh", "identity_digest": "a" * 64, "checkpoint_step": None,
        "analysis_only": True, "execution_authority": "none", "can_submit_orders": False,
    }
    cli_main.save_report_to_disk({**state, "checkpoint_receipt": receipt}, "TEST", tmp_path / "checkpointed")
    assert json.loads((tmp_path / "checkpointed/checkpoint_receipt.json").read_text()) == receipt


def test_overnight_graph_result_includes_creator_workflow_artifact_refs(monkeypatch, tmp_path):
    class FakeGraph:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def propagate(self, symbol, trade_date, asset_type="stock"):
            assert symbol == "NVDA"
            assert trade_date == "2026-06-03"
            assert asset_type == "stock"
            state = _creator_final_state()
            state["checkpoint_receipt"] = {
                "mode": "fresh",
                "identity_digest": "a" * 64,
                "checkpoint_step": None,
                "analysis_only": True,
                "execution_authority": "none",
                "can_submit_orders": False,
            }
            return state, "Overweight"

    monkeypatch.setattr(cli_main, "TradingAgentsGraph", FakeGraph)
    monkeypatch.setattr(
        cli_main,
        "build_analysis_checkpoint_identity",
        lambda **_kwargs: object(),
    )

    result = cli_main._run_overnight_ticker_analysis(
        "NVDA",
        "2026-06-03",
        tmp_path,
        graph_config_overrides={
            "_selected_analysts": ["market", "social", "news", "fundamentals"],
            "llm_provider": "ollama",
        },
    )

    workflow = result["creator_workflow"]
    assert result["status"] == "ok"
    assert workflow["execution_authority"] == "none"
    assert workflow["role_count"] == 12
    assert Path(workflow["packet_path"]).exists()
    assert Path(workflow["complete_report_path"]).exists()
    assert Path(workflow["packet_path"]).parent == tmp_path / "agent_runs" / "NVDA"
    assert result["checkpoint_receipt"] == {
        "mode": "fresh",
        "identity_digest": "a" * 64,
        "checkpoint_step": None,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
    }


@pytest.mark.parametrize(
    ("field", "value", "missing_label"),
    [
        ("market_report", "", "market"),
        (
            "news_report",
            "Status: INCOMPLETE_TOOL_CALL_LOOP",
            "news",
        ),
        (
            "fundamentals_report",
            "Status: EMPTY_ANALYST_RESPONSE",
            "fundamentals",
        ),
        ("final_trade_decision", "", "portfolio_decision"),
    ],
)
def test_overnight_graph_rejects_incomplete_analysis_before_writing_artifacts(
    monkeypatch,
    tmp_path,
    field,
    value,
    missing_label,
):
    state = _creator_final_state()
    state[field] = value

    class FakeGraph:
        def __init__(self, *args, **kwargs):
            pass

        def propagate(self, symbol, trade_date, asset_type="stock"):
            return state, "Hold"

    monkeypatch.setattr(cli_main, "TradingAgentsGraph", FakeGraph)
    monkeypatch.setattr(
        cli_main,
        "build_analysis_checkpoint_identity",
        lambda **_kwargs: object(),
    )

    with pytest.raises(
        cli_main.OvernightGraphIncompleteAnalysis,
        match=rf"missing=.*{missing_label}",
    ):
        cli_main._run_overnight_ticker_analysis(
            "NVDA",
            "2026-06-03",
            tmp_path,
            graph_config_overrides={
                "_selected_analysts": [
                    "market",
                    "social",
                    "news",
                    "fundamentals",
                ],
                "llm_provider": "ollama",
            },
        )

    assert not (tmp_path / "agent_runs" / "NVDA").exists()


def test_overnight_checkpoint_identity_failure_blocks_graph_and_artifact_writes(
    monkeypatch,
    tmp_path,
):
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
        cli_main._run_overnight_ticker_analysis(
            "NVDA",
            "2026-06-03",
            tmp_path,
            graph_config_overrides={
                "_selected_analysts": ["market", "social", "news", "fundamentals"],
                "llm_provider": "openrouter",
                "quick_think_llm": "openai/gpt-5-mini",
                "deep_think_llm": "anthropic/claude-sonnet-4-5",
                "backend_url": "https://router.example/v1?region=us",
            },
        )

    assert not (tmp_path / "agent_runs" / "NVDA").exists()


def test_overnight_analysis_rejects_an_explicit_no_checkpoint_override(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        cli_main,
        "TradingAgentsGraph",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("no-checkpoint override must block graph construction")
        ),
    )

    with pytest.raises(CheckpointRuntimeIdentityError, match="requires evidence-safe"):
        cli_main._run_overnight_ticker_analysis(
            "NVDA",
            "2026-06-03",
            tmp_path,
            graph_config_overrides={"checkpoint_enabled": False},
        )

    assert not (tmp_path / "agent_runs" / "NVDA").exists()


def test_creator_workflow_status_is_dashboard_only():
    status = build_creator_workflow_status(
        {
            "ticker_results": [
                {
                    "symbol": "NVDA",
                    "creator_workflow": {
                        "packet_path": "results/overnight_plans/agent_runs/NVDA/creator_workflow_packet.json",
                        "complete_report_path": "results/overnight_plans/agent_runs/NVDA/complete_report.md",
                        "role_count": 12,
                        "execution_authority": "none",
                    },
                }
            ]
        }
    )

    assert status["analysis_only"] is True
    assert status["can_submit_orders"] is False
    assert status["execution_authority"] == "none"
    assert status["workflow_count"] == 1
    assert status["symbols"] == ["NVDA"]
    assert status["role_count_min"] == 12
    assert status["missing_role_count"] == 0
    assert "submit_order" in status["forbidden_effects"]
