import datetime
import json
from decimal import Decimal

from typer.testing import CliRunner

from cli import main as cli_main
from cli.main import app
from tradingagents.brokers.paper_tournament import (
    COMPACT_LEDGER_FILE,
    LEDGER_FILE,
    STRATEGY_CURRENT_AGGRESSIVE,
    build_alphainsider_paper_watch_plan,
    build_popular_strategy_scorecards,
    build_tournament_report,
    compact_tournament_ledger_payload,
    initialize_tournament,
    maybe_write_live_strategy_selection,
    write_tournament_ledger,
    write_tournament_packet,
)

runner = CliRunner()


class _FakePaperClient:
    def __init__(self):
        self.paper = True
        self.submitted = []
        self.positions = [
            {
                "symbol": "GOOGL",
                "qty": "2",
                "avg_entry_price": "500",
                "market_value": "1060",
                "cost_basis": "1000",
                "unrealized_pl": "60",
                "unrealized_plpc": "0.06",
                "current_price": "530",
            }
        ]

    def assert_expected_mode(self, paper):
        assert paper is True

    def get_account(self):
        return {
            "status": "ACTIVE",
            "buying_power": "197000",
            "equity": "100060",
            "portfolio_value": "100060",
        }

    def list_positions(self):
        return self.positions

    def list_orders(self, status="open"):
        return []

    def list_open_client_order_ids(self):
        return set()

    def submit_order(self, order):
        self.submitted.append(order)
        return {"id": f"paper-{len(self.submitted)}", **order}


def test_initialize_tournament_marks_existing_bot_from_now():
    ledger = initialize_tournament(
        paper_account={"status": "ACTIVE", "equity": "100060"},
        paper_positions=[
            {
                "symbol": "GOOGL",
                "qty": "2",
                "avg_entry_price": "500",
                "market_value": "1060",
                "cost_basis": "1000",
                "unrealized_pl": "60",
                "current_price": "530",
            }
        ],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 5, 31, 18, 0, tzinfo=datetime.timezone.utc),
    )

    current = ledger["strategies"][STRATEGY_CURRENT_AGGRESSIVE]
    assert current["starting_capital"] == "10000.00"
    assert current["baseline_imported_value"] == "1060.00"
    assert current["cash"] == "8940.00"
    assert current["positions"]["GOOGL"]["avg_entry_price"] == "530.00"
    assert current["positions"]["GOOGL"]["cost_basis"] == "1060.00"
    assert current["positions"]["GOOGL"]["baseline_unrealized_pl"] == "0.00"
    assert ledger["strategies"]["pullback-support"]["cash"] == "10000.00"
    assert ledger["strategies"]["catalyst-relative-strength"]["cash"] == "10000.00"


def test_alphainsider_paper_watch_uses_only_remaining_paper_budget():
    plan = build_alphainsider_paper_watch_plan(
        paper_account={
            "status": "ACTIVE",
            "buying_power": "50000",
            "equity": "100000",
            "portfolio_value": "100000",
        },
        recommended_strategies=[
            {"strategy_id": "s1", "name": "Strategy One", "type": "stock"},
            {"strategy_id": "s2", "name": "Strategy Two", "type": "stock"},
            {"strategy_id": "s3", "name": "Strategy Three", "type": "stock"},
        ],
        reserved_budget=Decimal("30000"),
        max_allocation_per_strategy=Decimal("2000"),
        now=datetime.datetime(2026, 6, 2, 12, 0, tzinfo=datetime.timezone.utc),
    )

    assert plan["analysis_only"] is True
    assert plan["paper_only"] is True
    assert plan["execution_authority"] == "none"
    assert plan["reserved_tournament_budget_usd"] == "30000.00"
    assert plan["available_shadow_budget_usd"] == "20000.00"
    assert {item["proposed_paper_allocation_usd"] for item in plan["watch_items"]} == {"2000.00"}
    assert "submit_alphainsider_order" in plan["forbidden_effects"]


def test_alphainsider_paper_watch_builds_shadow_orders_from_strategy_tickers():
    plan = build_alphainsider_paper_watch_plan(
        paper_account={
            "status": "ACTIVE",
            "buying_power": "35000",
            "equity": "100000",
            "portfolio_value": "100000",
        },
        recommended_strategies=[
            {
                "strategy_id": "ai-growth",
                "name": "Popular Growth Basket",
                "type": "stock",
                "symbols": ["NVDA", "MSFT"],
            },
            {
                "strategy_id": "ai-defense",
                "name": "Popular Defensive Basket",
                "type": "stock",
                "holdings": [{"symbol": "COST"}],
            },
        ],
        reserved_budget=Decimal("30000"),
        max_allocation_per_strategy=Decimal("2000"),
        now=datetime.datetime(2026, 6, 2, 12, 0, tzinfo=datetime.timezone.utc),
    )

    assert plan["paper_shadow_mode"] == "paper_strategy_emulation"
    assert plan["shadow_order_count"] == 3
    assert plan["paper_shadow_spend_usd"] == "4000.00"
    assert plan["watch_items"][0]["shadow_status"] == "shadow_orders_ready"
    assert {order["symbol"] for order in plan["paper_shadow_orders"]} == {"NVDA", "MSFT", "COST"}
    assert {order["execution_authority"] for order in plan["paper_shadow_orders"]} == {"none"}
    assert {order["broker_submission_ready"] for order in plan["paper_shadow_orders"]} == {False}
    assert [order["notional"] for order in plan["paper_shadow_orders"][:2]] == ["1000.00", "1000.00"]


def test_tournament_packet_writer_keeps_fast_runs_unique(tmp_path):
    first = write_tournament_packet({"kind": "run", "sequence": 1}, tmp_path, prefix="paper-tournament-run")
    second = write_tournament_packet({"kind": "run", "sequence": 2}, tmp_path, prefix="paper-tournament-run")

    assert first != second
    assert first.exists()
    assert second.exists()


def test_tournament_ledger_writer_writes_compact_context_sidecars(tmp_path):
    paper_client = _FakePaperClient()
    ledger = initialize_tournament(
        paper_account=paper_client.get_account(),
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 6, 2, 12, 0, tzinfo=datetime.timezone.utc),
    )
    ledger["latest_report"] = {
        "generated_at": "2026-06-06T21:08:42+00:00",
        "rankings": [
            {
                "strategy_id": "pullback-support",
                "name": "Pullback Support Buyer",
                "equity": "10011.02",
                "total_return": "11.02",
                "total_return_pct": "0.11",
                "max_drawdown_pct": "-1.34",
                "win_rate_pct": "71.42",
                "tracked_days": 7,
                "positions": {"NOPE": "raw position details should not be copied"},
            }
        ],
        "live_strategy_candidate": {
            "status": "candidate",
            "strategy_id": "pullback-support",
            "reason": "best positive paper strategy after 7 tracked day(s)",
        },
    }

    ledger_path = write_tournament_ledger(ledger, tmp_path)
    compact = json.loads((tmp_path / "latest-compact.json").read_text(encoding="utf-8"))

    assert ledger_path == tmp_path / LEDGER_FILE
    assert (tmp_path / COMPACT_LEDGER_FILE).exists()
    assert compact["schema"] == "compact_paper_tournament_ledger_v1"
    assert compact["raw_packet_path"] == str(tmp_path / LEDGER_FILE)
    assert compact["can_submit_orders"] is False
    assert compact["execution_authority"] == "none"
    assert compact["strategy_count"] == 3
    assert compact["latest_report"]["rankings"][0]["strategy_id"] == "pullback-support"
    assert "positions" not in compact["latest_report"]["rankings"][0]


def test_compact_tournament_ledger_payload_falls_back_to_live_selection_candidate():
    compact = compact_tournament_ledger_payload(
        {
            "tournament_id": "paper-tournament-1",
            "strategies": {},
            "live_strategy_selection": {
                "status": "candidate",
                "strategy_id": "pullback-support",
                "reason": "candidate from previous report",
            },
        },
        raw_packet_path="results/paper_strategy_tournament/paper-tournament-ledger.json",
    )

    assert compact["latest_report"]["live_strategy_candidate"] == {
        "status": "candidate",
        "strategy_id": "pullback-support",
        "reason": "candidate from previous report",
    }


def test_paper_tournament_run_submits_strategy_prefixed_paper_orders(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    ledger = initialize_tournament(
        paper_account=paper_client.get_account(),
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 5, 31, 18, 0, tzinfo=datetime.timezone.utc),
    )
    write_tournament_ledger(ledger, tmp_path)

    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_clients",
        lambda: (_ for _ in ()).throw(AssertionError("live client should not be used")),
    )
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "NVDA": {
                "current_price": "220",
                "previous_close": "214",
                "volume_ratio": "2.0",
                "tradable": True,
            },
            "MSFT": {
                "current_price": "490",
                "previous_close": "495",
                "volume_ratio": "1.0",
                "tradable": True,
            },
        },
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "paper-tournament",
            "run",
            "--all",
            "--json-output",
            "--log-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["submitted_count"] == 3
    assert len(paper_client.submitted) == 3
    assert {order["type"] for order in paper_client.submitted} == {"limit"}
    client_ids = [order["client_order_id"] for order in paper_client.submitted]
    assert any(item.startswith("ta-paperbot-current-aggressive") for item in client_ids)
    assert any(item.startswith("ta-paperbot-pullback-support") for item in client_ids)
    assert any(item.startswith("ta-paperbot-catalyst") for item in client_ids)
    assert payload["report"]["live_strategy_candidate"]["status"] == "expired"


def test_paper_tournament_alphainsider_watch_writes_paper_only_packet(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    ledger = initialize_tournament(
        paper_account=paper_client.get_account(),
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 5, 31, 18, 0, tzinfo=datetime.timezone.utc),
    )
    write_tournament_ledger(ledger, tmp_path)
    monkeypatch.setenv("ALPHAINSIDER_API_KEY", "alpha-secret-value")
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_clients",
        lambda: (_ for _ in ()).throw(AssertionError("live client should not be used")),
    )
    monkeypatch.setattr(cli_main, "verify_alphainsider_token", lambda **kwargs: {"valid": True})
    monkeypatch.setattr(
        cli_main,
        "fetch_recommended_strategies",
        lambda **kwargs: [
            {"strategy_id": "ai-1", "name": "Popular One", "type": "stock"},
            {"strategy_id": "ai-2", "name": "Popular Two", "type": "stock"},
        ],
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "paper-tournament",
            "alphainsider-watch",
            "--json-output",
            "--log-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "alpha-secret-value" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["paper_only"] is True
    assert payload["fetch_status"] == "success"
    assert payload["fetch_reason"] == "token verified; fetched 2 recommended AlphaInsider strategies"
    assert payload["available_shadow_budget_usd"] == "167000.00"
    assert payload["watch_items"][0]["strategy_id"] == "ai-1"
    assert payload["watch_items"][0]["proposed_paper_allocation_usd"] == "2000.00"
    assert payload["alphainsider_env_status"]["api_key_present"] is True
    updated_ledger = json.loads((tmp_path / "paper-tournament-ledger.json").read_text(encoding="utf-8"))
    assert updated_ledger["alphainsider_paper_watch_plan"]["strategy_count"] == 2


def test_paper_tournament_alphainsider_watch_reports_redacted_fetch_reason(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    ledger = initialize_tournament(
        paper_account=paper_client.get_account(),
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 5, 31, 18, 0, tzinfo=datetime.timezone.utc),
    )
    write_tournament_ledger(ledger, tmp_path)
    monkeypatch.setenv("ALPHAINSIDER_API_KEY", "raw-jwt-secret")
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_clients",
        lambda: (_ for _ in ()).throw(AssertionError("live client should not be used")),
    )
    monkeypatch.setattr(cli_main, "verify_alphainsider_token", lambda **kwargs: {"valid": True})
    monkeypatch.setattr(
        cli_main,
        "fetch_recommended_strategies",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("token=raw-jwt-secret plan lacks recommended-strategy access")
        ),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "paper-tournament",
            "alphainsider-watch",
            "--json-output",
            "--log-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["fetch_status"] == "blocked"
    assert "token verified" in payload["fetch_reason"]
    assert "plan lacks recommended-strategy access" in payload["fetch_reason"]
    assert "raw-jwt-secret" not in payload["fetch_reason"]
    assert payload["strategy_count"] == 0
    assert payload["paper_only"] is True


def test_paper_tournament_alphainsider_watch_stops_after_token_verify_failure(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    ledger = initialize_tournament(
        paper_account=paper_client.get_account(),
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 5, 31, 18, 0, tzinfo=datetime.timezone.utc),
    )
    write_tournament_ledger(ledger, tmp_path)
    monkeypatch.setenv("ALPHAINSIDER_API_KEY", "raw-jwt-secret")
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_clients",
        lambda: (_ for _ in ()).throw(AssertionError("live client should not be used")),
    )
    monkeypatch.setattr(
        cli_main,
        "verify_alphainsider_token",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("token=raw-jwt-secret invalid")),
    )
    monkeypatch.setattr(
        cli_main,
        "fetch_recommended_strategies",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("recommended fetch should not run")),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "paper-tournament",
            "alphainsider-watch",
            "--json-output",
            "--log-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["fetch_status"] == "blocked"
    assert "invalid" in payload["fetch_reason"]
    assert "raw-jwt-secret" not in payload["fetch_reason"]
    assert payload["strategy_count"] == 0
    assert payload["paper_only"] is True


def test_paper_tournament_report_identifies_live_candidate_after_enough_days():
    ledger = initialize_tournament(
        paper_account={"status": "ACTIVE", "equity": "100000"},
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 5, 31, 18, 0, tzinfo=datetime.timezone.utc),
    )
    days = [
        "2026-06-01T20:05:00+00:00",
        "2026-06-02T20:05:00+00:00",
        "2026-06-03T20:05:00+00:00",
        "2026-06-04T20:05:00+00:00",
        "2026-06-05T20:05:00+00:00",
    ]
    for strategy_id, final_equity in {
        STRATEGY_CURRENT_AGGRESSIVE: Decimal("10050"),
        "pullback-support": Decimal("10080"),
        "catalyst-relative-strength": Decimal("10125"),
    }.items():
        ledger["strategies"][strategy_id]["equity_history"] = [
            {"generated_at": day, "equity": str(Decimal("10000") + Decimal(index * 5))}
            for index, day in enumerate(days[:-1])
        ] + [{"generated_at": days[-1], "equity": str(final_equity)}]

    report = build_tournament_report(
        ledger,
        market_data={},
        now=datetime.datetime(2026, 6, 5, 20, 10, tzinfo=datetime.timezone.utc),
        min_promotion_days=5,
    )

    assert report["rankings"][0]["strategy_id"] == "catalyst-relative-strength"
    assert report["rankings"][0]["total_return"] == "125.00"
    assert "win_rate_pct" in report["rankings"][0]
    assert "turnover" in report["rankings"][0]
    assert "cash_usage_pct" in report["rankings"][0]
    assert report["live_strategy_candidate"] == {
        "status": "candidate",
        "strategy_id": "catalyst-relative-strength",
        "reason": "best positive paper strategy after 5 tracked day(s)",
    }


def test_expired_tournament_report_is_ineligible_and_cannot_write_live_selection(tmp_path):
    ledger = initialize_tournament(
        paper_account={"status": "ACTIVE", "equity": "100000"},
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 5, 31, 18, 0, tzinfo=datetime.timezone.utc),
        duration_days=5,
    )
    ledger["strategies"][STRATEGY_CURRENT_AGGRESSIVE]["equity_history"] = [
        {
            "generated_at": f"2026-06-0{day}T20:05:00+00:00",
            "equity": str(Decimal("10000") + Decimal(day * 25)),
        }
        for day in range(1, 6)
    ]

    report = build_tournament_report(
        ledger,
        market_data={},
        now=datetime.datetime(2026, 6, 6, 20, 10, tzinfo=datetime.timezone.utc),
        min_promotion_days=5,
    )

    assert report["live_strategy_candidate"] == {
        "status": "expired",
        "strategy_id": STRATEGY_CURRENT_AGGRESSIVE,
        "reason": "tournament ended before this report; strategy is not eligible for selection",
    }
    forged_candidate_report = {
        **report,
        "live_strategy_candidate": {
            "status": "candidate",
            "strategy_id": STRATEGY_CURRENT_AGGRESSIVE,
        },
    }
    assert maybe_write_live_strategy_selection(forged_candidate_report, tmp_path) is None
    assert not (tmp_path / "live-strategy-selection.json").exists()


def test_tournament_report_includes_popular_strategy_scorecards_with_authority_boundaries():
    ledger = initialize_tournament(
        paper_account={"status": "ACTIVE", "equity": "100000"},
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 5, 31, 18, 0, tzinfo=datetime.timezone.utc),
    )
    ledger["alphainsider_paper_watch_plan"] = {
        "strategy_count": 2,
        "available_shadow_budget_usd": "12000.00",
        "paper_shadow_spend_usd": "4000.00",
        "shadow_order_count": 3,
        "paper_only": True,
        "execution_authority": "none",
    }
    ledger["strategies"]["pullback-support"]["equity_history"].append(
        {"generated_at": "2026-06-02T20:05:00+00:00", "equity": "10120.00"}
    )
    report = build_tournament_report(
        ledger,
        market_data={},
        now=datetime.datetime(2026, 6, 2, 20, 10, tzinfo=datetime.timezone.utc),
    )

    scorecards = report["popular_strategy_scorecards"]
    ids = {scorecard["strategy_id"] for scorecard in scorecards}
    assert {
        "pullback-support",
        "earnings-drift-estimate-revision",
        "event-underreaction",
        "pairs-comovement-residuals",
        "news-sentiment-swing",
        "macro-regime-overlay",
        "alphainsider-popular-paper",
    }.issubset(ids)
    assert {scorecard["paper_only"] for scorecard in scorecards} == {True}
    assert {scorecard["execution_authority"] for scorecard in scorecards} == {"none"}
    assert all("submit_live_order" in scorecard["forbidden_effects"] for scorecard in scorecards)

    by_id = {scorecard["strategy_id"]: scorecard for scorecard in scorecards}
    assert by_id["pullback-support"]["status"] == "active_paper_sleeve"
    assert by_id["pullback-support"]["paper_metrics"]["total_return"] == "120.00"
    assert by_id["pullback-support"]["setup_type"] == "buy_the_dip_support"
    assert by_id["earnings-drift-estimate-revision"]["status"] == "planned_paper_sleeve"
    assert by_id["alphainsider-popular-paper"]["status"] == "paper_shadow_watch"
    assert by_id["alphainsider-popular-paper"]["paper_metrics"]["shadow_order_count"] == 3
    assert "RRULE:FREQ=WEEKLY" in by_id["alphainsider-popular-paper"]["rotation_schedule"]
    assert report["popular_strategy_scorecards"] == build_popular_strategy_scorecards(ledger, report=report)


def test_supervisor_keeps_paper_tournament_live_strategy_selection_advisory(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    live_client = _FakePaperClient()
    live_client.paper = False
    live_client.positions = []
    tournament_dir = tmp_path / "tournament"
    tournament_dir.mkdir()
    (tournament_dir / "live-strategy-selection.json").write_text(
        json.dumps(
            {
                "status": "active",
                "strategy_id": "pullback-support",
                "selected_at": "2026-06-05T20:10:00+00:00",
                "reason": "best positive paper strategy after 5 tracked day(s)",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "MSFT": {
                "current_price": "490",
                "previous_close": "495",
                "volume_ratio": "1.0",
                "tradable": True,
            }
        },
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--dry-run",
            "--json-output",
            "--log-dir",
            str(tmp_path / "hourly"),
            "--paper-tournament-log-dir",
            str(tournament_dir),
            "--execution-board-dir",
            str(tmp_path / "execution_board"),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "buy"
    assert payload["submitted"] == []
    assert payload["actions"][0]["symbol"] == "MSFT"
    assert payload["actions"][0]["account"] == "live"
    assert payload["actions"][0]["execution_mode"] == "tiny_live"
    assert "controlled dip" in payload["actions"][0]["reason"]
    assert payload["evidence"]["live_strategy_selection"]["strategy_id"] == "pullback-support"
    assert payload["evidence"]["live_strategy_selection"]["advisory_only"] is True
    assert "advisory" in payload["evidence"]["live_strategy_selection"]["reason"]


def test_daily_report_includes_paper_tournament_leader(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    live_client = _FakePaperClient()
    live_client.paper = False
    tournament_dir = tmp_path / "tournament"
    brief_dir = tmp_path / "briefs"
    model_telemetry_report_dir = tmp_path / "model_telemetry_reports"
    board_dir = tmp_path / "execution_board"
    brief_dir.mkdir()
    model_telemetry_report_dir.mkdir()
    board_dir.mkdir()
    (brief_dir / "latest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T10:00:00+00:00",
                "analysis_only": True,
                "source_packets": [{"kind": "overnight_plan", "path": "overnight.json"}],
                "premarket_instructions": {"top_symbol": "ORCL"},
            }
        ),
        encoding="utf-8",
    )
    (model_telemetry_report_dir / "latest.json").write_text(
        json.dumps(
            {
                "kind": "model_telemetry_report",
                "analysis_only": True,
                "packet_count": 3,
                "usefulness_counts": {"pending": 2, "useful": 1},
                "outcome_counts": {"unresolved": 2, "helped": 1},
                "resolved_model_run_count": 1,
                "estimated_cost_total_usd": "0.0700",
                "operator_summary": "Model routes are safe but not fully ready: one local route is blocked. Keep deterministic fallback.",
            }
        ),
        encoding="utf-8",
    )
    (board_dir / "latest.json").write_text(
        json.dumps(
            {
                "kind": "execution_board_review",
                "analysis_only": True,
                "can_submit_orders": False,
                "recommendation": "pause_new_buys_and_review",
                "metrics": {
                    "submitted_order_count": 3,
                },
                "violations": [{"reason": "chase buy"}],
                "warnings": [{"reason": "loss exit"}],
            }
        ),
        encoding="utf-8",
    )
    ledger = initialize_tournament(
        paper_account=paper_client.get_account(),
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 5, 31, 18, 0, tzinfo=datetime.timezone.utc),
    )
    ledger["latest_report"] = {
        "rankings": [
            {
                "strategy_id": "catalyst-relative-strength",
                "equity": "10125.00",
                "total_return": "125.00",
                "total_return_pct": "1.25",
            }
        ],
        "live_strategy_candidate": {
            "status": "candidate",
            "strategy_id": "catalyst-relative-strength",
            "reason": "best positive paper strategy after 5 tracked day(s)",
        },
    }
    write_tournament_ledger(ledger, tournament_dir)
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {})

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervisor-daily-report",
            "--json-output",
            "--log-dir",
            str(tmp_path / "hourly"),
            "--paper-tournament-log-dir",
            str(tournament_dir),
            "--premarket-brief-log-dir",
            str(brief_dir),
            "--model-telemetry-report-dir",
            str(model_telemetry_report_dir),
            "--execution-board-dir",
            str(board_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "Practice-strategy race: the momentum strategy is leading" in payload["body"]
    assert "Tomorrow's top stock to watch: ORCL." in payload["body"]
    assert "Model telemetry" not in payload["body"]
    assert "BOARD review" not in payload["body"]
    assert "sleeve" not in payload["body"].lower()
    assert "Practice-strategy race:" in payload["body"]
    assert payload["paper_tournament"]["live_strategy_candidate"]["strategy_id"] == "catalyst-relative-strength"
    assert payload["premarket_brief"]["premarket_instructions"]["top_symbol"] == "ORCL"
    assert payload["model_telemetry_report"]["resolved_model_run_count"] == 1
    assert payload["execution_board_review"]["recommendation"] == "pause_new_buys_and_review"


def test_supervisor_binds_selection_with_live_enabled_promotion_record(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    live_client = _FakePaperClient()
    live_client.paper = False
    live_client.positions = []
    tournament_dir = tmp_path / "tournament"
    tournament_dir.mkdir()
    (tournament_dir / "live-strategy-selection.json").write_text(
        json.dumps(
            {
                "status": "active",
                "strategy_id": "pullback-support",
                "selected_at": "2026-06-05T20:10:00+00:00",
                "reason": "best positive paper strategy after 11 tracked day(s)",
            }
        ),
        encoding="utf-8",
    )
    promotion_path = tmp_path / "promotion_state.json"
    promotion_path.write_text(
        json.dumps(
            {
                "schema_version": "1.1.0",
                "sleeves": {
                    "pullback-support": {
                        "stage": "tiny_live_eligible",
                        "live_enabled": True,
                        "preregistered": True,
                        "ci_green": True,
                        "shadow_confirmed": True,
                        "benchmark_gate_passed": True,
                        "cost_gate_passed": True,
                        "recent_alpha_gate_passed": True,
                        "capacity_gate_passed": True,
                        "validation_report_ref": "results/paper_strategy_tournament/latest.json",
                        "risk_envelope_ref": "config/risk_envelope.yaml",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADINGAGENTS_PROMOTION_STATE_PATH", str(promotion_path))
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "MSFT": {
                "current_price": "490",
                "previous_close": "495",
                "volume_ratio": "1.0",
                "tradable": True,
            }
        },
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--dry-run",
            "--json-output",
            "--log-dir",
            str(tmp_path / "hourly"),
            "--paper-tournament-log-dir",
            str(tournament_dir),
            "--execution-board-dir",
            str(tmp_path / "execution_board"),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    resolution = payload["evidence"]["live_sleeve_resolution"]
    assert resolution["live_sleeve"] == "pullback-support"
    assert resolution["signals_adapted"] is True
    assert payload["evidence"]["live_strategy_selection"]["advisory_only"] is False
    assert "binding" in payload["evidence"]["live_strategy_selection"]["reason"]
    for action in payload["actions"]:
        if action.get("account") == "live" and action.get("action") == "buy":
            assert action["sleeve"] == "pullback-support"
