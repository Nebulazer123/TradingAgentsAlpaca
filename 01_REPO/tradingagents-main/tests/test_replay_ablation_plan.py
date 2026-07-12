import json
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.evals.agent_intelligence_ledger import AgentForecast, write_ledger
from tradingagents.evals.replay_ablation import (
    build_decision_quality_report_packet,
    build_replay_ablation_plan_packet,
    build_walk_forward_fixture_from_overnight_packets,
    build_walk_forward_replay_packet,
    build_walk_forward_return_rows_from_overnight_packets,
    calibrate_rating_probabilities,
    point_in_time_audit_table,
)

runner = CliRunner()


def test_replay_ablation_plan_has_deterministic_baseline_and_bounded_overlays():
    packet = build_replay_ablation_plan_packet(
        candidate_symbols="nvda, msft",
        sleeve="pullback-support",
    )

    lanes = {lane["lane_id"]: lane for lane in packet.orchestration_lanes}

    assert packet.analysis_only is True
    assert packet.execution_authority == "none"
    assert "submit_order" in packet.forbidden_effects
    assert packet.candidate_symbols == ["NVDA", "MSFT"]
    assert "deterministic_sleeve_only" in lanes
    assert lanes["deterministic_sleeve_only"]["authority"] == "baseline_only"
    assert lanes["tradingagents_advisory_overlay"]["authority"] == "advisory_only"
    assert lanes["deep_research_methodology_overlay"]["authority"] == "advisory_only"
    assert packet.quality_gates["minimum_decisions_per_arm"] == 30
    assert packet.quality_gates["required_metrics"] == [
        "directional_accuracy",
        "relative_return_vs_benchmark",
        "max_drawdown",
        "false_positive_rate",
        "token_or_api_cost_per_useful_signal",
    ]
    assert "waive_live_gate" in packet.quality_gates["forbidden_success_criteria"]


def test_replay_ablation_plan_cli_writes_packet(tmp_path):
    result = runner.invoke(
        app,
        [
            "research",
            "replay-ablation-plan",
            "--candidate-symbols",
            "nvda,msft",
            "--sleeve",
            "pullback-support",
            "--output-dir",
            str(tmp_path / "batches"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["execution_authority"] == "none"
    assert payload["candidate_symbols"] == ["NVDA", "MSFT"]
    assert Path(payload["packet_path"]).exists()
    assert any(
        lane["lane_id"] == "deterministic_sleeve_only"
        for lane in payload["orchestration_lanes"]
    )


def _resolved_rating_forecast(
    forecast_id: str,
    *,
    probability: str,
    outcome: bool,
) -> AgentForecast:
    return AgentForecast(
        forecast_id=forecast_id,
        agent="portfolio_manager",
        ticker="NVDA",
        claim="rating forecast",
        forecast_type="portfolio_rating_direction",
        horizon="5 trading days",
        probability=probability,
        expected_outcome="outperform benchmark",
        direction="bullish",
        created_at="2026-06-01T12:00:00+00:00",
        resolve_after="2026-06-08T12:00:00+00:00",
        resolved=True,
        outcome=outcome,
    )


def test_point_in_time_audit_marks_latest_only_gaps():
    rows = point_in_time_audit_table()
    by_area = {row["area"]: row for row in rows}

    assert by_area["price_ohlcv"]["status"] == "bounded"
    assert by_area["google_news_rss"]["status"] == "bounded"
    assert by_area["social_sentiment"]["status"] == "live_only_unscored_in_replay"
    assert all(row["next_action"] for row in rows)


def test_rating_calibration_uses_shrinkage_and_reports_brier_delta():
    forecasts = [
        _resolved_rating_forecast("buy-1", probability="0.66", outcome=True),
        _resolved_rating_forecast("buy-2", probability="0.66", outcome=True),
        _resolved_rating_forecast("sell-1", probability="0.34", outcome=False),
    ]

    calibration = calibrate_rating_probabilities(forecasts, prior_weight=2, min_resolved=1)

    assert calibration["resolved_rating_forecast_count"] == 3
    assert calibration["rating_probabilities"]["Buy"]["calibrated_probability"] == "0.8300"
    assert calibration["rating_probabilities"]["Buy"]["empirical_win_rate"] == "1.0000"
    assert calibration["rating_probabilities"]["Sell"]["calibrated_probability"] == "0.2267"
    assert calibration["average_brier_after"] < calibration["average_brier_before"]
    assert calibration["execution_authority"] == "none"


def test_decision_quality_report_packet_is_analysis_only_and_surfaces_p2_gates():
    forecasts = [
        _resolved_rating_forecast("buy-1", probability="0.66", outcome=True),
        _resolved_rating_forecast("hold-1", probability="0.50", outcome=False),
    ]

    packet = build_decision_quality_report_packet(
        forecasts,
        candidate_symbols="nvda, msft",
        sleeve="pullback-support",
        prior_weight=2,
    )

    assert packet.analysis_only is True
    assert packet.execution_authority == "none"
    assert "submit_order" in packet.forbidden_effects
    assert packet.status == "success"
    assert packet.candidate_symbols == ["NVDA", "MSFT"]
    assert packet.quality_gates["point_in_time_gap_count"] == 0
    assert packet.quality_gates["point_in_time_mixed_count"] == 0
    assert packet.quality_gates["rating_calibration"]["resolved_rating_forecast_count"] == 2
    assert "walk_forward_harness_next" in {lane["lane_id"] for lane in packet.orchestration_lanes}


def test_decision_quality_report_cli_writes_packet(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    calibration_path = tmp_path / "rating_calibration.json"
    write_ledger(
        [
            _resolved_rating_forecast("buy-1", probability="0.66", outcome=True),
            _resolved_rating_forecast("buy-2", probability="0.66", outcome=True),
        ],
        path=ledger_path,
    )

    result = runner.invoke(
        app,
        [
            "research",
            "decision-quality-report",
            "--candidate-symbols",
            "nvda,msft",
            "--ledger-path",
            str(ledger_path),
            "--output-dir",
            str(tmp_path / "batches"),
            "--rating-calibration-path",
            str(calibration_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["execution_authority"] == "none"
    assert payload["candidate_symbols"] == ["NVDA", "MSFT"]
    assert payload["quality_gates"]["rating_calibration"]["resolved_rating_forecast_count"] == 2
    assert payload["rating_calibration_path"] == str(calibration_path)
    assert Path(payload["packet_path"]).exists()
    written_calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    assert written_calibration["source_packet_path"] == payload["packet_path"]
    assert written_calibration["ledger_path"] == str(ledger_path)
    assert written_calibration["can_submit_orders"] is False
    assert written_calibration["execution_authority"] == "none"


def _walk_forward_rows() -> list[dict[str, object]]:
    return [
        {
            "symbol": "NVDA",
            "as_of": "2026-05-01",
            "baseline_action": "buy",
            "baseline_probability": "0.70",
            "actual_return": "0.0400",
            "benchmark_return": "0.0100",
            "overlays": {
                "official_context_overlay": {"action": "buy", "probability": "0.68"},
                "tradingagents_advisory_overlay": {"action": "hold", "probability": "0.55"},
            },
        },
        {
            "symbol": "MSFT",
            "as_of": "2026-05-02",
            "baseline_action": "buy",
            "baseline_probability": "0.65",
            "actual_return": "-0.0200",
            "benchmark_return": "0.0050",
            "overlays": {
                "official_context_overlay": {"action": "hold", "probability": "0.54"},
                "tradingagents_advisory_overlay": {"action": "sell", "probability": "0.61"},
            },
        },
        {
            "symbol": "AAPL",
            "as_of": "2026-05-03",
            "baseline_action": "sell",
            "baseline_probability": "0.60",
            "actual_return": "-0.0150",
            "benchmark_return": "0.0100",
            "overlays": {
                "official_context_overlay": {"action": "sell", "probability": "0.62"},
                "tradingagents_advisory_overlay": {"action": "sell", "probability": "0.64"},
            },
        },
    ]


def test_walk_forward_replay_packet_scores_fixed_as_of_fixture_rows():
    packet = build_walk_forward_replay_packet(
        _walk_forward_rows(),
        candidate_symbols="nvda,msft,aapl",
        minimum_decisions_per_arm=3,
    )

    metrics = {
        row["arm_id"]: row
        for row in packet.quality_gates["walk_forward_metrics"]
    }

    assert packet.analysis_only is True
    assert packet.execution_authority == "none"
    assert packet.status == "success"
    assert packet.quality_gates["walk_forward_row_count"] == 3
    assert packet.quality_gates["sample_floor_met"] is True
    assert metrics["deterministic_sleeve_only"]["scored_count"] == 3
    assert metrics["deterministic_sleeve_only"]["directional_accuracy"] == "0.6667"
    assert metrics["official_context_overlay"]["scored_count"] == 3
    assert metrics["news_social_crawler_overlay"]["unavailable_count"] == 3
    assert metrics["news_social_crawler_overlay"]["status"] == "unavailable"
    assert packet.quality_gates["scored_row_sample"][0]["as_of"] == "2026-05-01"
    assert "submit_order" in packet.forbidden_effects


def test_walk_forward_replay_packet_scores_net_costs_latency_and_baseline_edge():
    rows = [dict(row, latency_seconds="4") for row in _walk_forward_rows()]

    packet = build_walk_forward_replay_packet(
        rows,
        candidate_symbols="nvda,msft,aapl",
        minimum_decisions_per_arm=3,
        commission_bps="1",
        half_spread_bps="2",
        slippage_bps="3",
        latency_bps_per_second="1",
    )
    metrics = {
        row["arm_id"]: row
        for row in packet.quality_gates["walk_forward_metrics"]
    }
    baseline = metrics["deterministic_sleeve_only"]
    overlay = metrics["tradingagents_advisory_overlay"]

    assert packet.quality_gates["cost_model"] == {
        "commission_bps": "1.0000",
        "half_spread_bps": "2.0000",
        "slippage_bps": "3.0000",
        "latency_bps_per_second": "1.0000",
        "round_trip_sides": 2,
    }
    assert baseline["average_gross_action_relative_return"] == "0.0100"
    assert baseline["average_transaction_cost"] == "0.0020"
    assert baseline["average_action_relative_return"] == "0.0080"
    assert overlay["baseline_arm_id"] == "deterministic_sleeve_only"
    assert overlay["net_edge_vs_baseline"] == "-0.0027"
    assert overlay["beats_baseline_after_costs"] is False
    assert packet.quality_gates["scored_row_sample"][0]["transaction_cost"] == "0.0020"
    assert packet.quality_gates["scored_row_sample"][0]["net_action_relative_return"] == "0.0280"


def test_walk_forward_replay_packet_marks_low_sample_partial_and_filters_symbols():
    packet = build_walk_forward_replay_packet(
        _walk_forward_rows(),
        candidate_symbols="nvda,msft",
        minimum_decisions_per_arm=3,
    )

    assert packet.status == "partial"
    assert packet.candidate_symbols == ["NVDA", "MSFT"]
    assert packet.quality_gates["walk_forward_row_count"] == 2
    assert packet.quality_gates["sample_floor_met"] is False
    assert "minimum_decisions_per_arm not met" in packet.blockers[0]


def test_walk_forward_replay_cli_writes_packet_from_fixture(tmp_path):
    fixture_path = tmp_path / "walk-forward-fixture.json"
    fixture_path.write_text(json.dumps({"rows": _walk_forward_rows()}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "research",
            "walk-forward-replay",
            "--fixture-path",
            str(fixture_path),
            "--candidate-symbols",
            "nvda,msft,aapl",
            "--minimum-decisions-per-arm",
            "3",
            "--commission-bps",
            "1",
            "--half-spread-bps",
            "2",
            "--slippage-bps",
            "3",
            "--latency-bps-per-second",
            "1",
            "--output-dir",
            str(tmp_path / "batches"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["execution_authority"] == "none"
    assert payload["status"] == "success"
    assert payload["quality_gates"]["walk_forward_row_count"] == 3
    assert payload["quality_gates"]["cost_model"]["slippage_bps"] == "3.0000"
    assert Path(payload["packet_path"]).exists()


def _overnight_packet_for_fixture() -> dict[str, object]:
    return {
        "packet_id": "overnight-test",
        "generated_at": "2026-05-01T02:30:00+00:00",
        "ticker_results": [
            {
                "symbol": "NVDA",
                "status": "ok",
                "method": "full_graph",
                "rating": "Buy",
                "final_trade_decision": "Rating: Buy",
            },
            {
                "symbol": "MSFT",
                "status": "fallback",
                "method": "market_snapshot_fallback",
                "rating": "Hold",
                "final_trade_decision": "Fallback rating: Hold",
            },
            {
                "symbol": "AAPL",
                "status": "ok",
                "method": "full_graph",
                "rating": "Sell",
                "final_trade_decision": "Rating: Sell",
            },
        ],
    }


def test_walk_forward_fixture_generator_maps_overnight_results_to_replay_rows():
    fixture = build_walk_forward_fixture_from_overnight_packets(
        [_overnight_packet_for_fixture()],
        [
            {
                "symbol": "NVDA",
                "as_of": "2026-05-01",
                "actual_return": "0.0400",
                "benchmark_return": "0.0100",
            },
            {
                "symbol": "MSFT",
                "as_of": "2026-05-01",
                "actual_return": "0.0010",
                "benchmark_return": "0.0020",
            },
        ],
    )

    rows = fixture["rows"]
    by_symbol = {row["symbol"]: row for row in rows}

    assert fixture["row_count"] == 2
    assert fixture["skipped_count"] == 1
    assert by_symbol["NVDA"]["baseline_action"] == "buy"
    assert by_symbol["NVDA"]["baseline_probability"] == "0.6600"
    assert by_symbol["NVDA"]["overlays"]["tradingagents_advisory_overlay"]["action"] == "buy"
    assert by_symbol["MSFT"]["baseline_action"] == "hold"
    assert "tradingagents_advisory_overlay" not in by_symbol["MSFT"]["overlays"]
    assert fixture["skipped"][0]["symbol"] == "AAPL"
    assert fixture["execution_authority"] == "none"


def test_walk_forward_fixture_generator_dedupes_duplicate_symbol_as_of_rows():
    duplicate_packet = _overnight_packet_for_fixture()
    duplicate_packet["packet_id"] = "overnight-duplicate"
    duplicate_packet["ticker_results"] = [
        {
            "symbol": "NVDA",
            "status": "ok",
            "method": "full_graph",
            "rating": "Sell",
            "final_trade_decision": "Rating: Sell",
        }
    ]

    fixture = build_walk_forward_fixture_from_overnight_packets(
        [_overnight_packet_for_fixture(), duplicate_packet],
        [
            {
                "symbol": "NVDA",
                "as_of": "2026-05-01",
                "actual_return": "0.0400",
                "benchmark_return": "0.0100",
            },
        ],
    )

    duplicate_skips = [
        row for row in fixture["skipped"] if row["reason"] == "duplicate_symbol_as_of"
    ]

    assert fixture["row_count"] == 1
    assert fixture["duplicate_skipped_count"] == 1
    assert len(duplicate_skips) == 1
    assert duplicate_skips[0]["symbol"] == "NVDA"
    assert duplicate_skips[0]["as_of"] == "2026-05-01"
    assert duplicate_skips[0]["first_packet_ref"] == "overnight-test"
    assert fixture["rows"][0]["baseline_action"] == "buy"


def test_walk_forward_fixture_from_overnight_cli_writes_json(tmp_path):
    overnight_path = tmp_path / "overnight.json"
    returns_path = tmp_path / "returns.json"
    output_path = tmp_path / "fixture.json"
    overnight_path.write_text(json.dumps(_overnight_packet_for_fixture()), encoding="utf-8")
    returns_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "symbol": "NVDA",
                        "as_of": "2026-05-01",
                        "actual_return": "0.0400",
                        "benchmark_return": "0.0100",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "research",
            "walk-forward-fixture-from-overnight",
            "--overnight-packet",
            str(overnight_path),
            "--returns-path",
            str(returns_path),
            "--output-path",
            str(output_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["row_count"] == 1
    assert payload["skipped_count"] == 2
    assert payload["execution_authority"] == "none"
    assert payload["output_path"] == str(output_path)
    assert output_path.exists()


def test_walk_forward_return_collector_resolves_later_returns_with_price_lookup():
    def price_lookup(symbol: str, start_date: str, end_date: str):
        prices = {
            ("NVDA", "2026-05-01", "2026-05-06"): ("100", "110"),
            ("MSFT", "2026-05-01", "2026-05-06"): ("200", "198"),
            ("SPY", "2026-05-01", "2026-05-06"): ("500", "505"),
        }
        return prices.get((symbol, start_date, end_date))

    payload = build_walk_forward_return_rows_from_overnight_packets(
        [_overnight_packet_for_fixture()],
        price_lookup=price_lookup,
        horizon_days=5,
    )

    rows = {row["symbol"]: row for row in payload["rows"]}

    assert payload["row_count"] == 2
    assert payload["skipped_count"] == 1
    assert rows["NVDA"]["actual_return"] == "10.00"
    assert rows["NVDA"]["benchmark_return"] == "1.00"
    assert rows["MSFT"]["actual_return"] == "-1.00"
    assert rows["MSFT"]["benchmark_return"] == "1.00"
    assert payload["execution_authority"] == "none"


def test_walk_forward_return_collector_skips_non_finite_price_windows():
    def price_lookup(symbol: str, start_date: str, end_date: str):
        prices = {
            ("NVDA", "2026-05-01", "2026-05-06"): ("100", "NaN"),
            ("SPY", "2026-05-01", "2026-05-06"): ("500", "505"),
        }
        return prices.get((symbol, start_date, end_date))

    packet = _overnight_packet_for_fixture()
    packet["ticker_results"] = [packet["ticker_results"][0]]
    payload = build_walk_forward_return_rows_from_overnight_packets(
        [packet],
        price_lookup=price_lookup,
        horizon_days=5,
    )

    assert payload["row_count"] == 0
    assert payload["skipped_count"] == 1
    assert payload["skipped"][0]["reason"] == "invalid_price_window"


def test_walk_forward_returns_from_overnight_cli_writes_json_with_static_prices(tmp_path):
    overnight_path = tmp_path / "overnight.json"
    prices_path = tmp_path / "prices.json"
    output_path = tmp_path / "returns.json"
    overnight_path.write_text(json.dumps(_overnight_packet_for_fixture()), encoding="utf-8")
    prices_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "symbol": "NVDA",
                        "start_date": "2026-05-01",
                        "end_date": "2026-05-06",
                        "start_price": "100",
                        "end_price": "110",
                    },
                    {
                        "symbol": "SPY",
                        "start_date": "2026-05-01",
                        "end_date": "2026-05-06",
                        "start_price": "500",
                        "end_price": "505",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "research",
            "walk-forward-returns-from-overnight",
            "--overnight-packet",
            str(overnight_path),
            "--price-rows-path",
            str(prices_path),
            "--horizon-days",
            "5",
            "--output-path",
            str(output_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["row_count"] == 1
    assert payload["skipped_count"] == 2
    assert payload["kind"] == "walk_forward_return_rows"
    assert payload["schema_version"] == "1.0.0"
    assert payload["generated_at"]
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["execution_authority"] == "none"
    assert payload["output_path"] == str(output_path)
    assert output_path.exists()
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["generated_at"] == payload["generated_at"]
    assert written["analysis_only"] is True
    assert written["can_submit_orders"] is False


def test_walk_forward_refresh_overnight_cohort_cli_chains_returns_fixture_and_replay(tmp_path):
    overnight_dir = tmp_path / "overnight"
    overnight_dir.mkdir()
    mature_packet = _overnight_packet_for_fixture()
    immature_packet = _overnight_packet_for_fixture()
    immature_packet["packet_id"] = "overnight-immature"
    immature_packet["generated_at"] = "2026-05-05T02:30:00+00:00"
    mature_path = overnight_dir / "overnight-plan-20260501-023000.json"
    immature_path = overnight_dir / "overnight-plan-20260505-023000.json"
    mature_path.write_text(json.dumps(mature_packet), encoding="utf-8")
    immature_path.write_text(json.dumps(immature_packet), encoding="utf-8")
    compact_sidecar_path = overnight_dir / "overnight-plan-20260501-023000.compact.json"
    compact_sidecar_path.write_text(
        json.dumps(
            {
                "schema": "compact_overnight_plan_v1",
                "raw_packet_path": str(mature_path),
                "generated_at": mature_packet["generated_at"],
            }
        ),
        encoding="utf-8",
    )
    prices_path = tmp_path / "prices.json"
    prices_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "symbol": "NVDA",
                        "start_date": "2026-05-01",
                        "end_date": "2026-05-06",
                        "start_price": "100",
                        "end_price": "110",
                    },
                    {
                        "symbol": "MSFT",
                        "start_date": "2026-05-01",
                        "end_date": "2026-05-06",
                        "start_price": "200",
                        "end_price": "198",
                    },
                    {
                        "symbol": "AAPL",
                        "start_date": "2026-05-01",
                        "end_date": "2026-05-06",
                        "start_price": "300",
                        "end_price": "290",
                    },
                    {
                        "symbol": "SPY",
                        "start_date": "2026-05-01",
                        "end_date": "2026-05-06",
                        "start_price": "500",
                        "end_price": "505",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "research_batches"

    result = runner.invoke(
        app,
        [
            "research",
            "walk-forward-refresh-overnight-cohort",
            "--overnight-log-dir",
            str(overnight_dir),
            "--price-rows-path",
            str(prices_path),
            "--through-date",
            "2026-05-06",
            "--horizon-days",
            "5",
            "--minimum-decisions-per-arm",
            "2",
            "--output-dir",
            str(output_dir),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["execution_authority"] == "none"
    assert "submit_order" in payload["forbidden_effects"]
    assert payload["selected_packet_count"] == 1
    assert payload["selected_packet_paths"] == [str(mature_path)]
    assert payload["skipped_packet_count"] == 1
    assert all(".compact.json" not in row["path"] for row in payload["skipped_packets"])
    assert payload["skipped_packets"][0]["reason"] == "not_mature_yet"
    assert payload["returns_row_count"] == 3
    assert payload["fixture_row_count"] == 3
    assert payload["sample_floor_met"] is True
    assert Path(payload["returns_path"]).exists()
    assert Path(payload["fixture_path"]).exists()
    assert Path(payload["replay_packet_path"]).exists()
    assert Path(payload["summary_path"]).exists()
