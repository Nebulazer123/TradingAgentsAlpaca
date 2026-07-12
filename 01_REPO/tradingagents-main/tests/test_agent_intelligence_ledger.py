import datetime
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from typer.testing import CliRunner

import cli.main as cli_main
from cli.main import app
from tradingagents.evals.agent_intelligence_ledger import (
    agent_influence_weights,
    append_forecasts,
    calibrated_rating_probabilities_from_packet,
    forecasts_from_creator_workflow_packet,
    forecasts_from_mirofish_handoff_packet,
    forecasts_from_overnight_packet,
    load_calibrated_rating_probabilities,
    load_ledger,
    render_agent_influence_context,
    resolve_forecasts,
    summarize_agent_scores,
)
from tradingagents.evals.resolution_quality import (
    DEFER_TICKER_FINAL_BAR_MISSING,
    LABEL_QUALITY_HIGH,
    LABEL_QUALITY_SUSPECT,
    PriceWindow,
    expected_entry_session,
    expected_exit_session,
)
from tradingagents.research.original_workflow import write_creator_workflow_artifacts

runner = CliRunner()


def _aligned_sessions(start_date: str, end_date: str) -> list[str]:
    start = expected_entry_session(datetime.date.fromisoformat(start_date))
    end = expected_exit_session(datetime.date.fromisoformat(end_date))
    sessions = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            sessions.append(current.isoformat())
        current += datetime.timedelta(days=1)
    return sessions


def _aligned_window(
    symbol: str,
    start_date: str,
    end_date: str,
    entry_close: str,
    exit_close: str,
    *,
    drop_final: bool = False,
) -> PriceWindow:
    sessions = _aligned_sessions(start_date, end_date)
    if drop_final:
        sessions = sessions[:-1]
    return PriceWindow(
        symbol=symbol,
        requested_start=start_date,
        requested_end=end_date,
        entry_date=sessions[0],
        entry_close=str(entry_close),
        exit_date=sessions[-1],
        exit_close=str(exit_close),
        session_count=len(sessions),
    )


def _window_lookup_for(closes: dict, *, drop_final: frozenset = frozenset()):
    def lookup(symbol, start_date, end_date):
        if symbol not in closes:
            return None
        entry_close, exit_close = closes[symbol]
        return _aligned_window(
            symbol,
            start_date,
            end_date,
            entry_close,
            exit_close,
            drop_final=symbol in drop_final,
        )

    return lookup


def _overnight_packet():
    return {
        "generated_at": "2026-06-01T12:00:00+00:00",
        "ticker_results": [
            {
                "symbol": "NVDA",
                "status": "ok",
                "rating": "Buy",
                "investment_plan": "**Recommendation**: Buy\nAI demand remains strong.",
                "trader_investment_plan": "**Action**: Buy\nFINAL TRANSACTION PROPOSAL: **BUY**",
                "final_trade_decision": "**Rating**: Buy\n**Investment Thesis**: positive guidance",
                "reports": {
                    "market": "Bullish breakout and strong momentum.",
                    "sentiment": "Retail chatter is positive but not euphoric.",
                    "news": "Positive guidance and upside reactions dominate.",
                    "fundamentals": "Strong margins and upside growth.",
                },
            }
        ],
    }


def test_forecasts_from_overnight_packet_scores_each_agent_role():
    forecasts = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")

    agents = {forecast.agent for forecast in forecasts}
    assert {
        "market_analyst",
        "sentiment_analyst",
        "news_analyst",
        "fundamentals_analyst",
        "research_manager",
        "trader",
        "portfolio_manager",
    } <= agents
    assert all(forecast.ticker == "NVDA" for forecast in forecasts)
    assert all(forecast.benchmark == "QQQ" for forecast in forecasts)
    assert all(forecast.resolved is False for forecast in forecasts)
    assert any(forecast.direction == "bullish" for forecast in forecasts)


def test_rating_calibration_overrides_safe_resolved_rating_priors(tmp_path):
    calibration_path = tmp_path / "rating_calibration.json"
    calibration_path.write_text(
        json.dumps(
            {
                "execution_authority": "none",
                "rating_probabilities": {
                    "Buy": {
                        "state": "calibrated_with_shrinkage",
                        "resolved_count": 5,
                        "average_brier_before": "0.2500",
                        "average_brier_after": "0.2000",
                        "calibrated_probability": "0.7200",
                    },
                    "Sell": {
                        "state": "calibrated_with_shrinkage",
                        "resolved_count": 2,
                        "average_brier_before": "0.2500",
                        "average_brier_after": "0.1800",
                        "calibrated_probability": "0.2400",
                    },
                    "Overweight": {
                        "state": "calibrated_with_shrinkage",
                        "resolved_count": 5,
                        "average_brier_before": "0.2000",
                        "average_brier_after": "0.2600",
                        "calibrated_probability": "0.6400",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    overrides = load_calibrated_rating_probabilities(calibration_path)
    forecasts = forecasts_from_overnight_packet(
        _overnight_packet(),
        benchmark="QQQ",
        rating_probabilities=overrides,
    )
    by_agent = {forecast.agent: forecast for forecast in forecasts}

    assert overrides == {"Buy": Decimal("0.7200")}
    assert by_agent["portfolio_manager"].probability == "0.72"
    assert by_agent["research_manager"].probability == "0.72"


def test_rating_calibration_rejects_non_advisory_packets():
    overrides = calibrated_rating_probabilities_from_packet(
        {
            "execution_authority": "submit_orders",
            "rating_probabilities": {
                "Buy": {
                    "state": "calibrated_with_shrinkage",
                    "resolved_count": 99,
                    "average_brier_before": "0.2500",
                    "average_brier_after": "0.1000",
                    "calibrated_probability": "0.9000",
                }
            },
        }
    )

    assert overrides == {}


def test_forecasts_from_mirofish_handoff_packet_scores_advisory_attention_symbols():
    packet = {
        "packet_id": "mirofish-status-test",
        "generated_at": "2026-06-03T12:00:00+00:00",
        "signals": [
            {
                "type": "mirofish_final_advisory",
                "execution_authority": "none",
                "source_path": "reports/mirofish/MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md",
                "attention_symbols": ["SPY", "QQQ", "TSLA", "AAPL"],
                "forecast_symbols": ["QQQ", "TSLA", "AAPL"],
                "primary_hypotheses": [
                    "PDT-related narratives can raise retail attention but do not prove executable flow."
                ],
                "validation_tasks": ["Confirm broker/account evidence before using PDT chatter."],
                "false_signal_filters": [
                    "Social heat without broker/account evidence is narrative, not flow."
                ],
                "scenario_branches": [
                    {"description": "Narrative-only / limited flow effect."}
                ],
                "source_artifacts": {"stage04_report": "C:\\stage04\\full_report.md"},
            }
        ],
    }

    forecasts = forecasts_from_mirofish_handoff_packet(packet, benchmark="SPY")

    assert {forecast.ticker for forecast in forecasts} == {"QQQ", "TSLA", "AAPL"}
    assert {forecast.agent for forecast in forecasts} == {"mirofish_market_mirror"}
    assert all(forecast.direction == "neutral" for forecast in forecasts)
    assert all(forecast.setup == "mirofish_advisory_market_mirror" for forecast in forecasts)
    assert all(forecast.pm_action == "validate_before_trade" for forecast in forecasts)
    assert all("submit_order" not in forecast.action_thresholds for forecast in forecasts)


def test_forecasts_from_creator_workflow_packet_scores_all_original_roles(tmp_path):
    creator_packet = write_creator_workflow_artifacts(
        {
            "market_report": "Bullish support retest with improving breadth.",
            "sentiment_report": "Sentiment is constructive but not euphoric.",
            "news_report": "Positive guidance is underreacted to by the market.",
            "fundamentals_report": "Margins and cash flow are improving.",
            "investment_debate_state": {
                "bull_history": "Bull researcher expects upside.",
                "bear_history": "Bear researcher warns valuation downside.",
                "judge_decision": "Research manager says overweight on confirmation.",
            },
            "trader_investment_plan": "Trader waits for a controlled dip before entry.",
            "risk_debate_state": {
                "aggressive_history": "Aggressive risk analyst accepts small paper risk.",
                "neutral_history": "Neutral risk analyst wants volume confirmation.",
                "conservative_history": "Conservative risk analyst prefers cash default.",
                "judge_decision": "**Rating**: Overweight\nPortfolio manager says analysis-only watch.",
            },
        },
        symbol="NVDA",
        trade_date="2026-06-03",
        output_root=tmp_path,
        rating="Overweight",
        signal="Overweight",
    )

    forecasts = forecasts_from_creator_workflow_packet(creator_packet, benchmark="QQQ")

    agents = {forecast.agent for forecast in forecasts}
    assert {
        "market_analyst",
        "sentiment_analyst",
        "news_analyst",
        "fundamentals_analyst",
        "bull_researcher",
        "bear_researcher",
        "research_manager",
        "trader",
        "aggressive_risk_analyst",
        "neutral_risk_analyst",
        "conservative_risk_analyst",
        "portfolio_manager",
    } <= agents
    assert all(forecast.setup == "creator_tradingagents_workflow" for forecast in forecasts)
    assert all(forecast.benchmark == "QQQ" for forecast in forecasts)
    assert all(forecast.evidence_refs for forecast in forecasts)
    assert all(forecast.source_packet_id == creator_packet["packet_id"] for forecast in forecasts)
    assert all(forecast.thesis_pillars for forecast in forecasts)
    assert all(forecast.scenario_skew in {"bullish", "bearish", "neutral"} for forecast in forecasts)
    assert all(forecast.pm_action for forecast in forecasts)
    assert any("valuation" in " ".join(forecast.invalidators).lower() for forecast in forecasts)


def test_forecasts_from_overnight_packet_follows_creator_workflow_refs(tmp_path):
    creator_packet = write_creator_workflow_artifacts(
        {
            "market_report": "Bullish support retest with improving breadth.",
            "risk_debate_state": {
                "judge_decision": "**Rating**: Overweight\nPortfolio manager says analysis-only watch.",
            },
        },
        symbol="NVDA",
        trade_date="2026-06-03",
        output_root=tmp_path,
        rating="Overweight",
        signal="Overweight",
    )
    packet = {
        "generated_at": "2026-06-03T12:00:00+00:00",
        "ticker_results": [
            {
                "symbol": "NVDA",
                "status": "ok",
                "rating": "Overweight",
                "creator_workflow": {"packet_path": creator_packet["packet_path"]},
            }
        ],
    }

    forecasts = forecasts_from_overnight_packet(packet, benchmark="QQQ")

    assert {forecast.agent for forecast in forecasts} >= {"market_analyst", "portfolio_manager"}
    assert any(forecast.setup == "creator_tradingagents_workflow" for forecast in forecasts)


def test_ledger_append_is_idempotent(tmp_path):
    forecasts = forecasts_from_overnight_packet(_overnight_packet())
    ledger_path = tmp_path / "ledger.jsonl"

    first = append_forecasts(forecasts, path=ledger_path)
    second = append_forecasts(forecasts, path=ledger_path)

    assert first == len(forecasts)
    assert second == 0
    assert len(load_ledger(ledger_path)) == len(forecasts)


def test_resolve_forecasts_scores_relative_return_and_brier():
    forecasts = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")

    def price_lookup(symbol, start_date, end_date):
        if symbol == "NVDA":
            return Decimal("100"), Decimal("110")
        if symbol == "QQQ":
            return Decimal("100"), Decimal("102")
        return None

    resolved = resolve_forecasts(
        forecasts,
        price_lookup=price_lookup,
        now=datetime.datetime(2026, 6, 12, tzinfo=datetime.timezone.utc),
    )
    summary = summarize_agent_scores(resolved)

    assert all(forecast.resolved for forecast in resolved)
    assert all(forecast.actual_return == "10.00" for forecast in resolved)
    assert all(forecast.benchmark_return == "2.00" for forecast in resolved)
    assert all(forecast.relative_return == "8.00" for forecast in resolved)
    assert summary["agents"]["portfolio_manager"]["resolved_count"] == 1
    assert summary["agents"]["portfolio_manager"]["accuracy"] == "1.00"
    assert summary["agents"]["portfolio_manager"]["directional_accuracy"] == "1.00"
    assert summary["agents"]["portfolio_manager"]["relative_accuracy"] == "1.00"
    assert summary["agents"]["portfolio_manager"]["confidence_calibration_error"] == "0.3400"
    assert summary["agents"]["portfolio_manager"]["false_positive_rate"] == "0.0000"
    assert summary["agents"]["portfolio_manager"]["thesis_survival_rate"] == "1.0000"
    assert summary["agents"]["portfolio_manager"]["cost_per_useful_insight_usd"] == "0.0000"


def test_resolve_forecasts_sweeps_due_forecasts_across_all_tickers():
    base = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")
    forecasts = [
        replace(base[0], forecast_id="af-cross-nvda", ticker="NVDA"),
        replace(base[1], forecast_id="af-cross-aapl", ticker="AAPL"),
    ]

    def price_lookup(symbol, start_date, end_date):
        del start_date, end_date
        rows = {
            "NVDA": (Decimal("100"), Decimal("110")),
            "AAPL": (Decimal("200"), Decimal("214")),
            "QQQ": (Decimal("100"), Decimal("102")),
        }
        return rows.get(symbol)

    resolved = resolve_forecasts(
        forecasts,
        price_lookup=price_lookup,
        now=datetime.datetime(2026, 6, 12, tzinfo=datetime.timezone.utc),
    )

    assert {forecast.ticker for forecast in resolved if forecast.resolved} == {"NVDA", "AAPL"}
    assert all(forecast.resolution_note == "resolved against relative return window" for forecast in resolved)


def test_agent_influence_weights_reward_useful_agents_and_downrank_noisy_agents():
    forecasts = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")
    resolved = []
    for forecast in forecasts:
        if forecast.agent == "market_analyst":
            resolved.append(
                replace(
                    forecast,
                    resolved=True,
                    outcome=True,
                    brier_score="0.1156",
                    agent_score_delta="0.16",
                    relative_return="8.00",
                )
            )
        elif forecast.agent == "news_analyst":
            resolved.append(
                replace(
                    forecast,
                    resolved=True,
                    outcome=False,
                    brier_score="0.4356",
                    agent_score_delta="-0.16",
                    relative_return="-2.00",
                )
            )
        else:
            resolved.append(forecast)

    weights = agent_influence_weights(resolved, min_resolved=1)
    context = render_agent_influence_context(weights)

    assert Decimal(weights["agents"]["market_analyst"]["weight"]) > Decimal("1.00")
    assert Decimal(weights["agents"]["news_analyst"]["weight"]) < Decimal("1.00")
    assert Decimal("0.50") <= Decimal(weights["agents"]["news_analyst"]["weight"]) <= Decimal("1.50")
    assert weights["execution_authority"] == "none"
    assert "waive_live_gate" in weights["forbidden_effects"]
    assert "market_analyst" in context
    assert "cannot bypass live gates" in context


def test_agent_influence_weights_use_setup_sector_regime_and_evidence_context():
    base = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")
    market_forecast = next(forecast for forecast in base if forecast.agent == "market_analyst")
    news_forecast = next(forecast for forecast in base if forecast.agent == "news_analyst")
    forecasts = []
    for index in range(3):
        forecasts.append(
            replace(
                market_forecast,
                forecast_id=f"af-market-good-{index}",
                setup="pullback_support",
                sector="semiconductors",
                regime="risk_on",
                evidence_sources=["market_report", "news_report"],
                resolved=True,
                outcome=True,
                brier_score="0.1000",
                agent_score_delta="0.18",
                relative_return="3.00",
            )
        )
        forecasts.append(
            replace(
                market_forecast,
                forecast_id=f"af-market-bad-{index}",
                setup="breakout_chase",
                sector="banks",
                regime="risk_off",
                evidence_sources=["market_report", "news_report"],
                resolved=True,
                outcome=False,
                brier_score="0.4900",
                agent_score_delta="-0.18",
                relative_return="-2.00",
            )
        )
        forecasts.append(
            replace(
                news_forecast,
                forecast_id=f"af-news-bad-{index}",
                setup="pullback_support",
                sector="semiconductors",
                regime="risk_on",
                evidence_sources=["news_report"],
                resolved=True,
                outcome=False,
                brier_score="0.4900",
                agent_score_delta="-0.16",
                relative_return="-1.00",
            )
        )

    weights = agent_influence_weights(
        forecasts,
        min_resolved=2,
        setup="pullback_support",
        sector="semiconductors",
        regime="risk_on",
        evidence_type="news",
    )
    context = render_agent_influence_context(weights)

    assert weights["context"]["setup"] == "pullback_support"
    assert weights["context"]["sector"] == "semiconductors"
    assert weights["context"]["regime"] == "risk_on"
    assert weights["context"]["evidence_type"] == "news"
    assert weights["context"]["matched_resolved_count"] == 6
    assert weights["agents"]["market_analyst"]["state"] == "contextual_earned_weight"
    assert weights["agents"]["market_analyst"]["context"]["resolved_count"] == 3
    assert Decimal(weights["agents"]["market_analyst"]["weight"]) > Decimal("1.00")
    assert Decimal(weights["agents"]["news_analyst"]["weight"]) < Decimal("1.00")
    assert "context setup=pullback_support" in context


def test_agent_ledger_summary_cli_accepts_context_filters(tmp_path: Path):
    base = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")
    market_forecast = next(forecast for forecast in base if forecast.agent == "market_analyst")
    news_forecast = next(forecast for forecast in base if forecast.agent == "news_analyst")
    forecasts = []
    for index in range(3):
        forecasts.append(
            replace(
                market_forecast,
                forecast_id=f"af-cli-market-good-{index}",
                setup="pullback_support",
                sector="semiconductors",
                regime="risk_on",
                evidence_sources=["market_report", "news_report"],
                resolved=True,
                outcome=True,
                brier_score="0.1000",
                agent_score_delta="0.18",
                relative_return="3.00",
            )
        )
        forecasts.append(
            replace(
                news_forecast,
                forecast_id=f"af-cli-news-bad-{index}",
                setup="pullback_support",
                sector="semiconductors",
                regime="risk_on",
                evidence_sources=["news_report"],
                resolved=True,
                outcome=False,
                brier_score="0.4900",
                agent_score_delta="-0.16",
                relative_return="-1.00",
            )
        )
    ledger_path = tmp_path / "ledger.jsonl"
    summary_path = tmp_path / "summary.json"
    append_forecasts(forecasts, path=ledger_path)

    result = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-summary",
            "--ledger-path",
            str(ledger_path),
            "--summary-path",
            str(summary_path),
            "--context-setup",
            "pullback_support",
            "--context-sector",
            "semiconductors",
            "--context-regime",
            "risk_on",
            "--context-evidence-type",
            "news",
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["influence_weights"]["context"]["matched_resolved_count"] == 6
    assert payload["influence_weights"]["agents"]["market_analyst"]["state"] == "contextual_earned_weight"
    assert Decimal(payload["influence_weights"]["agents"]["market_analyst"]["weight"]) > Decimal("1.00")
    assert Decimal(payload["influence_weights"]["agents"]["news_analyst"]["weight"]) < Decimal("1.00")
    assert summary_path.exists()


def test_summary_labels_forecast_outcomes_for_compact_context():
    forecasts = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")
    resolved = [
        replace(
            forecasts[0],
            resolved=True,
            outcome=True,
            brier_score="0.1156",
            agent_score_delta="0.16",
            relative_return="8.00",
        ),
        replace(
            forecasts[1],
            resolved=True,
            outcome=False,
            brier_score="0.4356",
            agent_score_delta="-0.16",
            relative_return="-2.00",
        ),
        forecasts[2],
    ]

    summary = summarize_agent_scores(resolved)

    assert summary["resolved_forecast_count"] == 2
    assert summary["outcome_counts"] == {"useful": 1, "harmful": 1, "pending": 1}
    assert summary["agents"][resolved[0].agent]["useful_forecast_count"] == 1
    assert summary["agents"][resolved[1].agent]["harmful_forecast_count"] == 1


def test_agent_ledger_update_cli_appends_and_resolves_idempotently(tmp_path: Path):
    overnight_path = tmp_path / "overnight.json"
    ledger_path = tmp_path / "ledger.jsonl"
    summary_path = tmp_path / "summary.json"
    packet = _overnight_packet()
    packet["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )
    overnight_path.write_text(json.dumps(packet), encoding="utf-8")

    args = [
        "research",
        "agent-ledger-update",
        "--overnight-packet",
        str(overnight_path),
        "--ledger-path",
        str(ledger_path),
        "--summary-path",
        str(summary_path),
        "--benchmark",
        "QQQ",
        "--no-include-mirofish",
        "--json-output",
    ]
    first = runner.invoke(app, args)

    assert first.exit_code == 0, first.output
    payload = json.loads(first.stdout)
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["execution_authority"] == "none"
    assert payload["overnight_forecast_count"] == 7
    assert payload["mirofish_forecast_count"] == 0
    assert payload["appended_count"] == 7
    assert payload["resolved_forecast_count"] == 0
    assert summary_path.exists()

    second = runner.invoke(app, args)

    assert second.exit_code == 0, second.output
    payload = json.loads(second.stdout)
    assert payload["appended_count"] == 0
    assert payload["forecast_count"] == 7


def test_agent_ledger_resolve_cli_sweeps_existing_ledger_across_tickers(monkeypatch, tmp_path: Path):
    ledger_path = tmp_path / "ledger.jsonl"
    summary_path = tmp_path / "summary.json"
    quality_path = tmp_path / "resolution_quality.json"
    base = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")
    append_forecasts(
        [
            replace(base[0], forecast_id="af-cli-nvda", ticker="NVDA"),
            replace(base[1], forecast_id="af-cli-aapl", ticker="AAPL"),
        ],
        path=ledger_path,
    )
    monkeypatch.setattr(
        cli_main,
        "_ledger_window_lookup",
        _window_lookup_for(
            {
                "NVDA": ("100", "110"),
                "AAPL": ("200", "214"),
                "QQQ": ("100", "102"),
            }
        ),
    )

    result = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-resolve",
            "--ledger-path",
            str(ledger_path),
            "--summary-path",
            str(summary_path),
            "--resolution-quality-path",
            str(quality_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["newly_resolved_count"] == 2
    assert payload["resolved_forecast_count"] == 2
    assert payload["resolution_quality"]["label_quality_counts"][LABEL_QUALITY_HIGH] == 2
    assert payload["resolution_quality"]["deferred_count"] == 0
    assert summary_path.exists()
    assert quality_path.exists()
    rows = load_ledger(ledger_path)
    assert all(row.label_quality == LABEL_QUALITY_HIGH for row in rows)
    assert all(row.resolution_window["final_bar_available"] is True for row in rows)


def test_agent_ledger_resolve_cli_defers_stale_ticker_windows_with_reason(
    monkeypatch, tmp_path: Path
):
    ledger_path = tmp_path / "ledger.jsonl"
    summary_path = tmp_path / "summary.json"
    quality_path = tmp_path / "resolution_quality.json"
    base = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")
    append_forecasts(
        [replace(base[0], forecast_id="af-cli-stale-nvda", ticker="NVDA")],
        path=ledger_path,
    )
    monkeypatch.setattr(
        cli_main,
        "_ledger_window_lookup",
        _window_lookup_for(
            {"NVDA": ("100", "110"), "QQQ": ("100", "102")},
            drop_final=frozenset({"NVDA"}),
        ),
    )

    result = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-resolve",
            "--ledger-path",
            str(ledger_path),
            "--summary-path",
            str(summary_path),
            "--resolution-quality-path",
            str(quality_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["newly_resolved_count"] == 0
    assert payload["resolution_quality"]["deferred_count"] == 1
    assert (
        payload["resolution_quality"]["defer_reason_counts"][DEFER_TICKER_FINAL_BAR_MISSING] == 1
    )
    row = load_ledger(ledger_path)[0]
    assert row.resolved is False
    assert row.defer_reason == DEFER_TICKER_FINAL_BAR_MISSING
    assert row.resolution_note.startswith("deferred:")


def test_ledger_quality_audit_cli_annotates_resolved_rows_and_backs_up(
    monkeypatch, tmp_path: Path
):
    ledger_path = tmp_path / "ledger.jsonl"
    summary_path = tmp_path / "summary.json"
    quality_path = tmp_path / "resolution_quality.json"
    base = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")
    resolved_fields = {
        "resolved": True,
        "outcome": True,
        "actual_return": "10.00",
        "benchmark_return": "2.00",
        "relative_return": "8.00",
        "brier_score": "0.1156",
        "agent_score_delta": "0.16",
        "resolved_at": "2026-06-08T22:00:00+00:00",
        "resolution_note": "resolved against relative return window",
    }
    append_forecasts(
        [
            replace(base[0], forecast_id="af-audit-nvda", ticker="NVDA", **resolved_fields),
            replace(base[1], forecast_id="af-audit-msft", ticker="MSFT", **resolved_fields),
        ],
        path=ledger_path,
    )
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write("{not valid json\n")
    monkeypatch.setattr(
        cli_main,
        "_ledger_window_lookup",
        _window_lookup_for(
            {
                "NVDA": ("100", "110"),
                # MSFT recomputes to a losing relative return -> suspect label.
                "MSFT": ("100", "101"),
                "QQQ": ("100", "102"),
            }
        ),
    )

    result = runner.invoke(
        app,
        [
            "research",
            "ledger-quality-audit",
            "--ledger-path",
            str(ledger_path),
            "--summary-path",
            str(summary_path),
            "--quality-path",
            str(quality_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["resolved_forecast_count"] == 2
    assert payload["corrupt_ledger_line_count"] == 1
    assert payload["resolution_quality"]["label_quality_counts"] == {
        LABEL_QUALITY_HIGH: 1,
        LABEL_QUALITY_SUSPECT: 1,
    }
    assert payload["suspect_forecast_ids"] == ["af-audit-msft"]
    assert quality_path.exists()
    backups = list(tmp_path.glob("ledger.backup-quality-audit-*.jsonl"))
    assert len(backups) == 1
    by_ticker = {row.ticker: row for row in load_ledger(ledger_path)}
    assert by_ticker["NVDA"].label_quality == LABEL_QUALITY_HIGH
    assert by_ticker["MSFT"].label_quality == LABEL_QUALITY_SUSPECT
    assert "reaudit_outcome_mismatch" in by_ticker["MSFT"].quality_flags
    assert by_ticker["MSFT"].outcome is True  # annotated, never rewritten
