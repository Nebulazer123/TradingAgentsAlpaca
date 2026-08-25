import datetime
import hashlib
import inspect
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from typer.testing import CliRunner

import cli.main as cli_main
from cli.main import app
from tradingagents.dataflows.pit import (
    RawPointInTimeArtifactArchive,
    build_source_bound_adjusted_price_window,
)
from tradingagents.evals.agent_intelligence_ledger import (
    DEFER_INVALID_FORECAST_TIMESTAMPS,
    AgentForecast,
    agent_influence_weights,
    append_forecasts,
    audit_resolved_forecasts,
    calibrated_rating_probabilities_from_packet,
    downgrade_nonqualifying_resolution_labels,
    forecasts_from_creator_workflow_packet,
    forecasts_from_mirofish_handoff_packet,
    forecasts_from_overnight_packet,
    load_calibrated_rating_probabilities,
    load_ledger,
    render_agent_influence_context,
    resolve_forecasts,
    resolve_forecasts_with_quality,
    summarize_agent_scores,
)
from tradingagents.evals.learning_availability import LearningAvailabilityLedger
from tradingagents.evals.resolution_quality import (
    DEFER_TICKER_FINAL_BAR_MISSING,
    LABEL_QUALITY_HIGH,
    LABEL_QUALITY_SUSPECT,
    PriceWindow,
    expected_entry_session,
    expected_exit_session,
)
from tradingagents.evals.source_bound_resolution import load_source_bound_window_lookup
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


def _source_bound_window_lookup_for(
    closes: dict,
    *,
    drop_final: frozenset = frozenset(),
):
    legacy_lookup = _window_lookup_for(closes, drop_final=drop_final)

    class SourceBoundLookup:
        def __call__(self, symbol, start_date, end_date):
            window = legacy_lookup(symbol, start_date, end_date)
            if window is None:
                return None
            digest = hashlib.sha256(symbol.encode("ascii")).hexdigest()
            return replace(
                window,
                source_evidence={
                    "schema_version": "source_bound_price_window_evidence/v1",
                    "window_id": f"spw-{symbol.lower()}",
                    "window_sha256": digest,
                    "security_id": f"security-{symbol.lower()}",
                    "raw_artifact_id": f"pit-{symbol.lower()}",
                    "raw_artifact_sha256": digest,
                    "decision_cutoff": "2026-06-12T00:00:00+00:00",
                    "retrieved_at": "2026-06-11T00:00:00+00:00",
                    "feed": "iex",
                    "adjustment_mode": "all",
                    "adjustment_status": "total_return_adjusted",
                },
            )

        def verify_forecast(self, forecast):
            window = forecast.resolution_window
            if not isinstance(window, dict):
                return False
            ticker = self(
                forecast.ticker,
                window["intended_start"],
                window["intended_end"],
            )
            benchmark = self(
                forecast.benchmark,
                window["intended_start"],
                window["intended_end"],
            )
            return (
                ticker is not None
                and benchmark is not None
                and forecast.resolution_evidence
                == {
                    "schema_version": "source_bound_resolution_evidence/v1",
                    "ticker": ticker.source_evidence,
                    "benchmark": benchmark.source_evidence,
                }
            )

    return SourceBoundLookup()


def _with_source_bound_learning_evidence(
    forecast: AgentForecast,
    *,
    label_quality: str = LABEL_QUALITY_HIGH,
    lookup=None,
) -> AgentForecast:
    if lookup is None:
        lookup = _source_bound_window_lookup_for(
            {forecast.ticker: ("100", "110"), forecast.benchmark: ("100", "102")}
        )
    start_date = forecast.created_at[:10]
    end_date = forecast.resolve_after[:10]
    ticker = lookup(forecast.ticker, start_date, end_date)
    benchmark = lookup(forecast.benchmark, start_date, end_date)
    assert ticker is not None and benchmark is not None
    return replace(
        forecast,
        label_quality=label_quality,
        resolution_window=forecast.resolution_window
        or {
            "intended_start": start_date,
            "intended_end": end_date,
        },
        resolution_evidence={
            "schema_version": "source_bound_resolution_evidence/v1",
            "ticker": ticker.source_evidence,
            "benchmark": benchmark.source_evidence,
        },
    )


def _write_source_bound_receipts(
    tmp_path: Path,
    *,
    forecast: AgentForecast,
) -> tuple[Path, tuple[Path, ...], tuple[Path, ...]]:
    archive = RawPointInTimeArtifactArchive(tmp_path / "pit-artifacts")
    requested_start = datetime.date.fromisoformat(forecast.created_at[:10])
    requested_end = datetime.date.fromisoformat(forecast.resolve_after[:10])
    source_end = requested_end + datetime.timedelta(days=1)
    raw_receipt_paths = []
    price_receipt_paths = []
    for index, (symbol, first_close, last_close) in enumerate(
        ((forecast.ticker, "100", "110"), (forecast.benchmark, "100", "102"))
    ):
        market_dates = []
        current = requested_start
        while current <= requested_end:
            if current.weekday() < 5:
                market_dates.append(current)
            current += datetime.timedelta(days=1)
        raw_bytes = json.dumps(
            {
                "bars": {
                    symbol: [
                        {
                            "t": f"{market_date.isoformat()}T05:00:00Z",
                            "c": first_close if position == 0 else last_close,
                        }
                        for position, market_date in enumerate(market_dates)
                    ]
                }
            }
        ).encode("utf-8")
        artifact = archive.admit(
            raw_bytes=raw_bytes,
            source_uri=(
                f"https://data.alpaca.markets/v2/stocks/{symbol}/bars?"
                "timeframe=1Day&feed=iex&adjustment=all"
                f"&start={requested_start.isoformat()}T00:00:00Z"
                f"&end={source_end.isoformat()}T00:00:00Z"
            ),
            content_type="application/json",
            retrieved_at="2026-06-11T00:00:00+00:00",
        )
        receipt = build_source_bound_adjusted_price_window(
            archive=archive,
            raw_artifact=artifact,
            security_id=f"security-{symbol.lower()}",
            symbol=symbol,
            requested_start=requested_start.isoformat(),
            requested_end=requested_end.isoformat(),
            decision_cutoff="2026-06-12T00:00:00+00:00",
        )
        raw_path = tmp_path / f"raw-{index}.json"
        price_path = tmp_path / f"price-{index}.json"
        raw_path.write_bytes(artifact.canonical_json_bytes())
        price_path.write_bytes(receipt.canonical_json_bytes())
        raw_receipt_paths.append(raw_path)
        price_receipt_paths.append(price_path)
    return archive.root, tuple(raw_receipt_paths), tuple(price_receipt_paths)


def _source_bound_verifier(tmp_path: Path, forecast: AgentForecast):
    archive_root, raw_receipt_paths, price_receipt_paths = _write_source_bound_receipts(
        tmp_path,
        forecast=forecast,
    )
    return load_source_bound_window_lookup(
        raw_artifact_archive=archive_root,
        raw_artifact_receipts=raw_receipt_paths,
        price_window_receipts=price_receipt_paths,
    )


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


def test_agent_influence_weights_reward_useful_agents_and_downrank_noisy_agents(tmp_path: Path):
    forecasts = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")
    verifier = _source_bound_verifier(tmp_path, forecasts[0])
    resolved = []
    for forecast in forecasts:
        if forecast.agent == "market_analyst":
            resolved.append(
                _with_source_bound_learning_evidence(
                    replace(
                        forecast,
                        resolved=True,
                        outcome=True,
                        brier_score="0.1156",
                        agent_score_delta="0.16",
                        relative_return="8.00",
                    ),
                    lookup=verifier,
                )
            )
        elif forecast.agent == "news_analyst":
            resolved.append(
                _with_source_bound_learning_evidence(
                    replace(
                        forecast,
                        resolved=True,
                        outcome=False,
                        brier_score="0.4356",
                        agent_score_delta="-0.16",
                        relative_return="-2.00",
                    ),
                    lookup=verifier,
                )
            )
        else:
            resolved.append(forecast)

    weights = agent_influence_weights(
        resolved,
        source_bound_verifier=verifier,
        min_resolved=1,
    )
    context = render_agent_influence_context(weights)

    assert Decimal(weights["agents"]["market_analyst"]["weight"]) > Decimal("1.00")
    assert Decimal(weights["agents"]["news_analyst"]["weight"]) < Decimal("1.00")
    assert Decimal("0.50") <= Decimal(weights["agents"]["news_analyst"]["weight"]) <= Decimal("1.50")
    assert weights["execution_authority"] == "none"
    assert "waive_live_gate" in weights["forbidden_effects"]
    assert "market_analyst" in context
    assert "cannot bypass live gates" in context


def test_legacy_suspect_wins_cannot_change_agent_influence_weight():
    forecast = next(
        item
        for item in forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")
        if item.agent == "market_analyst"
    )
    legacy_wins = [
        replace(
            forecast,
            forecast_id=f"af-legacy-win-{index}",
            resolved=True,
            outcome=True,
            brier_score="0.0100",
            agent_score_delta="0.49",
            relative_return="20.00",
            label_quality=LABEL_QUALITY_SUSPECT,
            quality_flags=["legacy_yfinance_nonqualifying"],
            resolution_evidence=None,
        )
        for index in range(3)
    ]

    weights = agent_influence_weights(legacy_wins, min_resolved=1)

    assert weights["qualifying_resolved_count"] == 0
    assert weights["agents"]["market_analyst"] == {
        "weight": "1.00",
        "state": "insufficient_history",
        "resolved_count": 0,
        "reason": "no source-bound qualifying resolved forecasts",
    }


def test_forged_source_bound_metadata_cannot_change_agent_influence_weight():
    forecast = next(
        item
        for item in forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")
        if item.agent == "market_analyst"
    )
    forged_highs = [
        _with_source_bound_learning_evidence(
            replace(
                forecast,
                forecast_id=f"af-forged-source-bound-{index}",
                resolved=True,
                outcome=True,
                brier_score="0.0100",
                agent_score_delta="0.49",
                relative_return="20.00",
            )
        )
        for index in range(3)
    ]

    weights = agent_influence_weights(forged_highs, min_resolved=1)

    assert "_admitted_source_bound_forecasts" not in inspect.signature(
        agent_influence_weights
    ).parameters
    assert "_admission_proof" not in inspect.signature(agent_influence_weights).parameters
    assert weights["qualifying_resolved_count"] == 0
    assert weights["agents"]["market_analyst"]["weight"] == "1.00"
    assert weights["agents"]["market_analyst"]["state"] == "insufficient_history"


def test_agent_influence_weights_use_setup_sector_regime_and_evidence_context(tmp_path: Path):
    base = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")
    market_forecast = next(forecast for forecast in base if forecast.agent == "market_analyst")
    news_forecast = next(forecast for forecast in base if forecast.agent == "news_analyst")
    verifier = _source_bound_verifier(tmp_path, market_forecast)
    forecasts = []
    for index in range(3):
        forecasts.append(
            _with_source_bound_learning_evidence(
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
                ),
                lookup=verifier,
            )
        )
        forecasts.append(
            _with_source_bound_learning_evidence(
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
                ),
                lookup=verifier,
            )
        )
        forecasts.append(
            _with_source_bound_learning_evidence(
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
                ),
                lookup=verifier,
            )
        )

    weights = agent_influence_weights(
        forecasts,
        source_bound_verifier=verifier,
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
            _with_source_bound_learning_evidence(
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
        )
        forecasts.append(
            _with_source_bound_learning_evidence(
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
    assert payload["influence_weights"]["context"]["matched_resolved_count"] == 0
    assert payload["influence_weights"]["agents"]["market_analyst"]["state"] == "insufficient_history"
    assert payload["influence_weights"]["agents"]["market_analyst"]["weight"] == "1.00"
    assert payload["influence_weights"]["agents"]["news_analyst"]["weight"] == "1.00"
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
    availability_root = tmp_path / "learning_availability"
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
        "--learning-availability-root",
        str(availability_root),
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
    assert payload["learning_availability_root"] == str(availability_root)
    assert payload["learning_observed_count"] == 0
    assert payload["learning_newly_recorded_count"] == 0
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
    availability_root = tmp_path / "learning_availability"
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
    assert payload["resolution_quality"]["label_quality_counts"] == {
        LABEL_QUALITY_SUSPECT: 2
    }
    assert payload["resolution_quality"]["deferred_count"] == 0
    assert payload["learning_availability_root"] == str(availability_root)
    assert payload["learning_observed_count"] == 0
    assert payload["learning_newly_recorded_count"] == 0
    assert summary_path.exists()
    assert quality_path.exists()
    rows = load_ledger(ledger_path)
    assert all(row.label_quality == LABEL_QUALITY_SUSPECT for row in rows)
    assert all("legacy_yfinance_nonqualifying" in row.quality_flags for row in rows)
    assert all(row.resolution_window["final_bar_available"] is True for row in rows)
    assert not availability_root.exists()


def test_agent_ledger_resolve_cli_loads_and_reverifies_real_source_receipts(tmp_path: Path):
    ledger_path = tmp_path / "ledger.jsonl"
    summary_path = tmp_path / "summary.json"
    quality_path = tmp_path / "resolution-quality.json"
    availability_root = tmp_path / "learning-availability"
    forecast = replace(
        forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")[0],
        forecast_id="af-cli-real-source-bound",
        ticker="NVDA",
    )
    append_forecasts([forecast], path=ledger_path)
    archive_root, raw_receipts, price_receipts = _write_source_bound_receipts(
        tmp_path,
        forecast=forecast,
    )
    args = [
        "research",
        "agent-ledger-resolve",
        "--ledger-path",
        str(ledger_path),
        "--summary-path",
        str(summary_path),
        "--resolution-quality-path",
        str(quality_path),
        "--learning-availability-root",
        str(availability_root),
        "--pit-raw-artifact-archive",
        str(archive_root),
    ]
    for receipt in raw_receipts:
        args.extend(("--pit-raw-artifact-receipt", str(receipt)))
    for receipt in price_receipts:
        args.extend(("--pit-price-window-receipt", str(receipt)))
    args.append("--json-output")

    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["price_window_route"] == "source_bound_adjusted_pit_receipts"
    assert payload["learning_newly_recorded_count"] == 1
    observation = LearningAvailabilityLedger(availability_root).verify()[0]
    evidence = observation.payload["resolution_evidence"]
    assert evidence["ticker"]["security_id"] == "security-nvda"
    assert evidence["benchmark"]["security_id"] == "security-qqq"
    assert evidence["ticker"]["raw_artifact_sha256"] != evidence["benchmark"]["raw_artifact_sha256"]


def test_legacy_downgrade_preserves_existing_source_bound_resolution_evidence():
    forecast = replace(
        forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")[0],
        forecast_id="af-source-bound-preserved",
        ticker="NVDA",
    )
    resolved, _reports = resolve_forecasts_with_quality(
        [forecast],
        window_lookup=_source_bound_window_lookup_for(
            {"NVDA": ("100", "110"), "QQQ": ("100", "102")}
        ),
        now=datetime.datetime(2026, 6, 12, tzinfo=datetime.timezone.utc),
    )

    retained, retained_reports = downgrade_nonqualifying_resolution_labels(
        resolved,
        (),
    )

    assert retained[0].label_quality == LABEL_QUALITY_HIGH
    assert retained[0].resolution_evidence is not None
    assert retained_reports == []


def test_agent_ledger_resolve_rejects_invalid_source_receipts_before_writing(tmp_path: Path):
    ledger_path = tmp_path / "ledger.jsonl"
    raw_archive = tmp_path / "pit-artifacts"
    raw_receipt = tmp_path / "raw-artifact.json"
    price_receipt = tmp_path / "price-window.json"
    raw_receipt.write_text("{}", encoding="utf-8")
    price_receipt.write_text("{}", encoding="utf-8")
    forecast = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")[0]
    append_forecasts([forecast], path=ledger_path)

    result = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-resolve",
            "--ledger-path",
            str(ledger_path),
            "--pit-raw-artifact-archive",
            str(raw_archive),
            "--pit-raw-artifact-receipt",
            str(raw_receipt),
            "--pit-price-window-receipt",
            str(price_receipt),
        ],
    )

    assert result.exit_code != 0
    assert "source-bound PIT resolution inputs are invalid" in result.output
    row = load_ledger(ledger_path)[0]
    assert row.resolved is False
    assert row.resolution_evidence is None


def test_agent_ledger_resolve_rejects_partial_source_inputs_before_writing(tmp_path: Path):
    ledger_path = tmp_path / "ledger.jsonl"
    append_forecasts(
        [forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")[0]],
        path=ledger_path,
    )

    result = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-resolve",
            "--ledger-path",
            str(ledger_path),
            "--pit-raw-artifact-archive",
            str(tmp_path / "pit-artifacts"),
        ],
    )

    assert result.exit_code != 0
    assert "source-bound resolution requires" in result.output
    assert load_ledger(ledger_path)[0].resolved is False


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


def test_agent_ledger_resolve_recovers_write_to_availability_crash_gap(
    monkeypatch,
    tmp_path: Path,
):
    ledger_path = tmp_path / "ledger.jsonl"
    availability_root = tmp_path / "learning_availability"
    base = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")
    forecast = replace(base[0], forecast_id="af-crash-gap", ticker="NFLX")
    append_forecasts([forecast], path=ledger_path)
    archive_root, raw_receipts, price_receipts = _write_source_bound_receipts(
        tmp_path,
        forecast=forecast,
    )
    real_observe = cli_main.observe_forecasts

    def crash_before_availability(*args, **kwargs):
        raise RuntimeError("crash after forecast write")

    monkeypatch.setattr(cli_main, "observe_forecasts", crash_before_availability)
    args = [
        "research",
        "agent-ledger-resolve",
        "--ledger-path",
        str(ledger_path),
        "--summary-path",
        str(tmp_path / "summary.json"),
        "--resolution-quality-path",
        str(tmp_path / "quality.json"),
        "--learning-availability-root",
        str(availability_root),
        "--pit-raw-artifact-archive",
        str(archive_root),
    ]
    for receipt in raw_receipts:
        args.extend(("--pit-raw-artifact-receipt", str(receipt)))
    for receipt in price_receipts:
        args.extend(("--pit-price-window-receipt", str(receipt)))
    args.extend(("--json-output",))
    crashed = runner.invoke(app, args)
    assert crashed.exit_code == 1
    assert load_ledger(ledger_path)[0].resolved is True
    assert not availability_root.exists()

    monkeypatch.setattr(cli_main, "observe_forecasts", real_observe)
    recovered = runner.invoke(app, args)
    assert recovered.exit_code == 0, recovered.output
    payload = json.loads(recovered.stdout)
    assert payload["newly_resolved_count"] == 0
    assert payload["learning_observed_count"] == 1
    assert payload["learning_newly_recorded_count"] == 1
    assert len(LearningAvailabilityLedger(availability_root).verify()) == 1


def test_ledger_quality_audit_cli_annotates_resolved_rows_and_backs_up(
    monkeypatch, tmp_path: Path
):
    ledger_path = tmp_path / "ledger.jsonl"
    summary_path = tmp_path / "summary.json"
    quality_path = tmp_path / "resolution_quality.json"
    availability_root = tmp_path / "learning_availability"
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
            "--learning-availability-root",
            str(availability_root),
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
        LABEL_QUALITY_SUSPECT: 2
    }
    assert payload["suspect_forecast_ids"] == ["af-audit-nvda", "af-audit-msft"]
    assert payload["learning_availability_root"] == str(availability_root)
    assert payload["learning_observed_count"] == 0
    assert payload["learning_newly_recorded_count"] == 0
    assert quality_path.exists()
    backups = list(tmp_path.glob("ledger.backup-quality-audit-*.jsonl"))
    assert len(backups) == 1
    by_ticker = {row.ticker: row for row in load_ledger(ledger_path)}
    assert by_ticker["NVDA"].label_quality == LABEL_QUALITY_SUSPECT
    assert by_ticker["MSFT"].label_quality == LABEL_QUALITY_SUSPECT
    assert "legacy_yfinance_nonqualifying" in by_ticker["NVDA"].quality_flags
    assert "reaudit_outcome_mismatch" in by_ticker["MSFT"].quality_flags
    assert by_ticker["MSFT"].outcome is True  # annotated, never rewritten
    assert not availability_root.exists()


def _drifted_timestamp_forecast(**overrides):
    base = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")[0]
    return replace(
        base,
        forecast_id="af-drifted-timestamps",
        created_at="",
        resolve_after="",
        **overrides,
    )


def test_resolve_with_quality_defers_unparseable_forecast_timestamps():
    drifted = _drifted_timestamp_forecast()
    healthy = replace(
        forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")[-1],
        forecast_id="af-healthy",
    )

    def window_lookup(symbol, start_date, end_date):
        raise AssertionError("window lookup must not run for drifted timestamps")

    resolved, reports = resolve_forecasts_with_quality(
        [drifted, healthy],
        window_lookup=window_lookup,
        now=datetime.datetime(2026, 6, 5, tzinfo=datetime.timezone.utc),
    )

    by_id = {forecast.forecast_id: forecast for forecast in resolved}
    assert by_id["af-drifted-timestamps"].resolved is False
    assert by_id["af-drifted-timestamps"].resolution_note.startswith("deferred: ")
    assert by_id["af-healthy"].resolved is False
    drifted_report = next(report for report in reports if report.forecast_id == "af-drifted-timestamps")
    assert drifted_report.status == "deferred"
    assert drifted_report.defer_reason == DEFER_INVALID_FORECAST_TIMESTAMPS
    healthy_report = next(report for report in reports if report.forecast_id == "af-healthy")
    assert healthy_report.status == "not_mature"


def test_resolve_with_quality_defers_extreme_timestamp_overflow():
    base = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")[0]
    extreme = replace(
        base,
        forecast_id="af-extreme-overflow",
        resolve_after="9999-12-31T23:59:59-14:00",
    )

    def window_lookup(symbol, start_date, end_date):
        raise AssertionError("window lookup must not run for overflow timestamps")

    resolved, reports = resolve_forecasts_with_quality(
        [extreme],
        window_lookup=window_lookup,
        now=datetime.datetime(2026, 6, 5, tzinfo=datetime.timezone.utc),
    )

    assert resolved[0].forecast_id == "af-extreme-overflow"
    assert resolved[0].resolved is False
    assert resolved[0].resolution_note.startswith("deferred: ")
    assert len(reports) == 1
    assert reports[0].status == "deferred"
    assert reports[0].defer_reason == DEFER_INVALID_FORECAST_TIMESTAMPS


def test_summarize_agent_scores_skips_extreme_resolved_at_overflow_and_keeps_labels():
    base = forecasts_from_overnight_packet(_overnight_packet(), benchmark="QQQ")[0]
    healthy = replace(
        base,
        forecast_id="af-summary-ttr-healthy",
        agent="trader",
        resolved=True,
        outcome=True,
        brier_score="0.1156",
        agent_score_delta="0.16",
        relative_return="8.00",
        label_quality=LABEL_QUALITY_HIGH,
        created_at="2026-06-01T00:00:00+00:00",
        resolve_after="2026-06-08T00:00:00+00:00",
        resolved_at="2026-06-09T00:00:00+00:00",
    )
    extreme = replace(
        healthy,
        forecast_id="af-summary-ttr-extreme-overflow",
        agent="market_analyst",
        resolved_at="9999-12-31T23:59:59-14:00",
    )

    summary = summarize_agent_scores([healthy, extreme])

    assert summary["outcome_counts"] == {"useful": 2}
    assert summary["label_quality_counts"] == {"high": 2}
    assert summary["agents"]["trader"]["average_time_to_resolution_days"] == "8.00"
    extreme_stats = summary["agents"]["market_analyst"]
    assert extreme_stats["average_time_to_resolution_days"] == "0.00"
    assert extreme_stats["score_delta_total"] == "0.16"


def test_audit_resolved_forecasts_flags_unparseable_timestamps_as_suspect():
    forecast = _drifted_timestamp_forecast(
        resolved=True,
        outcome=True,
        relative_return="8.00",
        label_quality=LABEL_QUALITY_HIGH,
    )

    def window_lookup(symbol, start_date, end_date):
        raise AssertionError("window lookup must not run for drifted timestamps")

    audited, reports = audit_resolved_forecasts(
        [forecast],
        window_lookup=window_lookup,
        now=datetime.datetime(2026, 6, 12, tzinfo=datetime.timezone.utc),
    )

    assert audited[0].outcome is True  # stored labels are never rewritten
    assert audited[0].label_quality == LABEL_QUALITY_SUSPECT
    assert "window_unverifiable" in audited[0].quality_flags
    assert audited[0].resolution_window is None
    assert reports[0].label_quality == LABEL_QUALITY_SUSPECT
    assert "unparseable" in reports[0].note


def test_resolve_forecasts_legacy_path_leaves_unparseable_timestamps_unresolved():
    forecast = _drifted_timestamp_forecast()

    def price_lookup(symbol, start_date, end_date):
        raise AssertionError("price lookup must not run for drifted timestamps")

    resolved = resolve_forecasts(
        [forecast],
        price_lookup=price_lookup,
        now=datetime.datetime(2026, 6, 12, tzinfo=datetime.timezone.utc),
    )

    assert resolved[0].resolved is False
    assert "unparseable" in (resolved[0].resolution_note or "")
