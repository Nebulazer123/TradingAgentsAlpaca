import json
from pathlib import Path

import cli.main as cli_main
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


def test_overnight_graph_result_includes_creator_workflow_artifact_refs(monkeypatch, tmp_path):
    class FakeGraph:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def propagate(self, symbol, trade_date, asset_type="stock"):
            assert symbol == "NVDA"
            assert trade_date == "2026-06-03"
            assert asset_type == "stock"
            return _creator_final_state(), "Overweight"

    monkeypatch.setattr(cli_main, "TradingAgentsGraph", FakeGraph)

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
