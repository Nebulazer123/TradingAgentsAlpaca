import datetime
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from cli import main as cli_main
from cli.main import app
from tradingagents.brokers import paper_tournament
from tradingagents.brokers.paper_tournament import (
    COMPACT_LEDGER_FILE,
    LEDGER_FILE,
    STRATEGY_CURRENT_AGGRESSIVE,
    STRATEGY_PULLBACK_SUPPORT,
    _parse_timestamp,
    _tournament_expired,
    build_alphainsider_paper_watch_plan,
    build_popular_strategy_scorecards,
    build_tournament_report,
    compact_tournament_ledger_payload,
    fingerprint_expired_tournament_ledger,
    initialize_tournament,
    load_live_strategy_selection,
    maybe_write_live_strategy_selection,
    write_tournament_ledger,
    write_tournament_packet,
)

runner = CliRunner()


def _market_calendar_entry(date_text, open_text="09:30", close_text="16:00"):
    return {"date": date_text, "open": open_text, "close": close_text}


REGULAR_WEEK_CALENDAR = [
    _market_calendar_entry(f"2026-06-0{day}") for day in range(1, 6)
]


class _FakePaperClient:
    def __init__(self):
        self.paper = True
        self.settings = SimpleNamespace(
            paper=True,
            base_url="https://paper-api.alpaca.markets",
        )
        self.submitted = []
        self.orders = []
        self.clock = {"is_open": True, "timestamp": "2026-06-02T18:00:00+00:00"}
        self.clock_calls = 0
        self.calendar = [dict(entry) for entry in REGULAR_WEEK_CALENDAR]
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
        if status == "open":
            return [
                order
                for order in self.orders
                if order.get("status", "").lower()
                not in {"filled", "canceled", "expired", "rejected"}
            ]
        return list(self.orders)

    def list_calendar(self, *, start, end):
        assert start <= end
        return [
            dict(entry) for entry in self.calendar if start <= entry["date"] <= end
        ]

    def get_clock(self):
        self.clock_calls += 1
        return self.clock

    def list_open_client_order_ids(self):
        return set()

    def submit_order(self, order):
        self.submitted.append(order)
        response = {"id": f"paper-{len(self.submitted)}", "status": "filled", **order}
        self.orders.append(response)
        return response


class _BlockingPaperClient(_FakePaperClient):
    def __init__(self):
        super().__init__()
        self.post_started = Event()
        self.release_post = Event()

    def submit_order(self, order):
        self.submitted.append(order)
        self.post_started.set()
        assert self.release_post.wait(timeout=5)
        response = {"id": f"paper-{len(self.submitted)}", "status": "filled", **order}
        self.orders.append(response)
        return response


class _MalformedSecondResponsePaperClient(_FakePaperClient):
    def __init__(self):
        super().__init__()
        self.submit_attempts = 0

    def submit_order(self, order):
        self.submit_attempts += 1
        response = super().submit_order(order)
        return response if self.submit_attempts == 1 else None


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
        now=datetime.datetime(2026, 6, 1, 18, 0, tzinfo=datetime.timezone.utc),
        max_submission_market_days=5,
        market_calendar=paper_client.calendar,
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
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 2, 18, 0, tzinfo=datetime.timezone.utc),
    )
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "NVDA": {
                "current_price": "218",
                "previous_close": "220",
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
            "--submit-actions",
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
    assert payload["report"]["live_strategy_candidate"]["status"] == "pending"


def _current_trial_ledger(paper_client, *, max_submission_market_days=5):
    return initialize_tournament(
        paper_account=paper_client.get_account(),
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 6, 1, 18, 0, tzinfo=datetime.timezone.utc),
        duration_days=31,
        max_submission_market_days=max_submission_market_days,
        market_calendar=paper_client.calendar,
    )


def _configure_current_submit(monkeypatch, paper_client):
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_clients",
        lambda: (_ for _ in ()).throw(AssertionError("live client should not be used")),
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 2, 18, 0, tzinfo=datetime.timezone.utc),
    )
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "NVDA": {
                "current_price": "218",
                "previous_close": "220",
                "volume_ratio": "2.0",
                "tradable": True,
            }
        },
    )


def _persist_interrupted_submission(paper_client, output_dir):
    ledger = _current_trial_ledger(paper_client)
    payload = {
        "strategy_id": STRATEGY_CURRENT_AGGRESSIVE,
        "symbol": "NVDA",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": "218.43",
        "notional": "1000.00",
        "extended_hours": False,
        "client_order_id": "ta-paperbot-current-aggressive-interrupted-20260602",
        "reason": "simulated accepted post before process loss",
    }
    now = datetime.datetime(2026, 6, 2, 18, 0, tzinfo=datetime.timezone.utc)
    paper_tournament.begin_submission_transaction(
        ledger,
        market_date="2026-06-02",
        payloads=[payload],
        now=now,
    )
    write_tournament_ledger(ledger, output_dir)
    response = paper_client.submit_order(
        {key: value for key, value in payload.items() if key not in {"strategy_id", "reason"}}
    )
    assert response["client_order_id"] == payload["client_order_id"]
    return json.loads((output_dir / LEDGER_FILE).read_text(encoding="utf-8"))


def test_initialize_tournament_records_bounded_submission_lease():
    ledger = _current_trial_ledger(_FakePaperClient(), max_submission_market_days=5)

    assert ledger["authorized_market_day_limit"] == 5
    assert ledger["authorized_market_dates"] == REGULAR_WEEK_CALENDAR
    assert ledger["submitted_market_dates"] == []
    assert ledger["submission_window_status"] == "open"
    assert ledger["ledger_type"] == "qualification_paper_trial"
    assert ledger["submission_lease_evidence"]


def _trial_ledger_with_calendar(paper_client, *, calendar=None, **overrides):
    arguments = {
        "paper_account": paper_client.get_account(),
        "paper_positions": [],
        "capital_per_strategy": Decimal("10000"),
        "now": datetime.datetime(2026, 6, 1, 18, 0, tzinfo=datetime.timezone.utc),
        "duration_days": 31,
        "max_submission_market_days": 5,
        "market_calendar": paper_client.calendar if calendar is None else calendar,
    }
    arguments.update(overrides)
    return initialize_tournament(**arguments)


def test_red_initialize_tournament_admits_authenticated_market_days_with_fifth_close_expiry():
    paper_client = _FakePaperClient()
    ledger = _trial_ledger_with_calendar(paper_client)

    assert ledger["authorized_market_dates"] == REGULAR_WEEK_CALENDAR
    assert ledger["ends_at"] == "2026-06-05T20:00:00+00:00"

    tampered = json.loads(json.dumps(ledger))
    tampered["authorized_market_dates"][2]["close"] = "16:30"
    assert (
        paper_tournament._submission_lease_evidence(tampered)
        != ledger["submission_lease_evidence"]
    )


@pytest.mark.parametrize(
    ("calendar", "duration_days", "max_days"),
    [
        ([], 31, 5),
        (REGULAR_WEEK_CALENDAR, 31, 31),
        ([dict(entry) for entry in REGULAR_WEEK_CALENDAR[:4]], 31, 5),
        ([_market_calendar_entry("2026-06-01"), {"date": "2026-06-02"}], 31, 5),
        ([_market_calendar_entry("2026-06-01"), _market_calendar_entry("2026-06-02", open_text="9:30")], 31, 5),
        ([_market_calendar_entry("2026-06-01", close_text="")], 31, 5),
        ([_market_calendar_entry("2026-06-01", open_text="16:00", close_text="09:30")], 31, 5),
        ([_market_calendar_entry("20260601")], 31, 5),
        ([_market_calendar_entry("2026-06-01"), _market_calendar_entry("2026-06-01")], 31, 5),
        (["2026-06-01"], 31, 5),
        (("not-a-sequence-of-mappings",), 31, 5),
    ],
    ids=[
        "missing",
        "capacity-exceeds-authenticated-evidence",
        "insufficient-market-days",
        "malformed-entry-fields",
        "malformed-open-time",
        "missing-close-time",
        "open-at-or-after-close",
        "malformed-date",
        "duplicated-date",
        "non-mapping-entry",
        "non-sequence-calendar",
    ],
)
def test_red_initialize_tournament_fails_closed_on_unauthenticated_calendar_evidence(
    calendar, duration_days, max_days
):
    paper_client = _FakePaperClient()

    with pytest.raises(ValueError, match="calendar evidence"):
        initialize_tournament(
            paper_account=paper_client.get_account(),
            paper_positions=[],
            capital_per_strategy=Decimal("10000"),
            now=datetime.datetime(2026, 6, 1, 18, 0, tzinfo=datetime.timezone.utc),
            duration_days=duration_days,
            max_submission_market_days=max_days,
            market_calendar=calendar,
        )


def test_red_legacy_ledger_without_calendar_evidence_cannot_admit_submissions():
    paper_client = _FakePaperClient()
    ledger = initialize_tournament(
        paper_account=paper_client.get_account(),
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 6, 1, 18, 0, tzinfo=datetime.timezone.utc),
    )
    assert ledger["authorized_market_dates"] == []
    now = datetime.datetime(2026, 6, 2, 18, 0, tzinfo=datetime.timezone.utc)
    paper_client.clock = {"is_open": True, "timestamp": now.isoformat()}

    with pytest.raises(ValueError, match="no admitted market-day calendar evidence"):
        paper_tournament.validate_submission_lease(
            ledger,
            paper_client=paper_client,
            now=now,
        )
    assert paper_client.clock_calls == 0
    assert paper_client.submitted == []


def test_red_initialize_tournament_uses_calendar_early_close_for_the_final_market_close():
    paper_client = _FakePaperClient()
    early_close_calendar = [
        _market_calendar_entry(f"2026-06-0{day}") for day in range(1, 5)
    ] + [_market_calendar_entry("2026-06-05", close_text="13:00")]
    paper_client.calendar = [dict(entry) for entry in early_close_calendar]

    ledger = _trial_ledger_with_calendar(paper_client)

    assert ledger["authorized_market_dates"][4]["close"] == "13:00"
    assert ledger["ends_at"] == "2026-06-05T17:00:00+00:00"


def _weekday_market_calendar(start_date, count):
    sessions = []
    day = start_date
    while len(sessions) < count:
        if day.weekday() < 5:
            sessions.append(_market_calendar_entry(day.isoformat()))
        day += datetime.timedelta(days=1)
    return sessions


def test_red_default_limits_admit_full_session_count_with_ceiling_bound_ends_at():
    sessions = _weekday_market_calendar(datetime.date(2026, 6, 1), 40)

    ledger = initialize_tournament(
        paper_account={"status": "ACTIVE", "equity": "100000"},
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 6, 1, 18, 0, tzinfo=datetime.timezone.utc),
        market_calendar=sessions,
    )

    assert ledger["authorized_market_day_limit"] == 31
    assert len(ledger["authorized_market_dates"]) == 31
    assert ledger["authorized_market_dates"][0]["date"] == "2026-06-01"
    assert ledger["authorized_market_dates"][-1]["date"] == "2026-07-13"
    assert ledger["lease_window_days"] == 31
    assert ledger["ends_at"] == "2026-07-02T18:00:00+00:00"

    tampered = json.loads(json.dumps(ledger))
    tampered["ends_at"] = "2026-07-13T20:00:00+00:00"
    assert (
        paper_tournament._submission_lease_evidence(tampered)
        != ledger["submission_lease_evidence"]
    )
    paper_client = _FakePaperClient()
    with pytest.raises(ValueError, match="does not match ledger"):
        paper_tournament.validate_submission_lease(
            tampered,
            paper_client=paper_client,
            now=datetime.datetime(2026, 7, 13, 18, 0, tzinfo=datetime.timezone.utc),
        )
    assert paper_client.clock_calls == 0


def test_red_admission_rejects_session_beyond_wall_clock_ceiling():
    sessions = _weekday_market_calendar(datetime.date(2026, 6, 1), 40)
    paper_client = _FakePaperClient()
    paper_client.calendar = [dict(entry) for entry in sessions]
    ledger = initialize_tournament(
        paper_account=paper_client.get_account(),
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 6, 1, 18, 0, tzinfo=datetime.timezone.utc),
        market_calendar=sessions,
    )
    beyond_ceiling_day = datetime.datetime(
        2026, 7, 13, 18, 0, tzinfo=datetime.timezone.utc
    )
    paper_client.clock = {"is_open": True, "timestamp": beyond_ceiling_day.isoformat()}

    with pytest.raises(ValueError, match="beyond the lease wall-clock ceiling"):
        paper_tournament.validate_submission_lease(
            ledger,
            paper_client=paper_client,
            now=beyond_ceiling_day,
        )
    assert paper_client.clock_calls == 0


def test_red_forged_ends_at_with_rehashed_evidence_is_rejected():
    paper_client = _FakePaperClient()
    ledger = _current_trial_ledger(paper_client)
    forged = json.loads(json.dumps(ledger))
    forged["ends_at"] = "2026-07-01T18:00:00+00:00"

    with pytest.raises(ValueError, match="does not match ledger"):
        paper_tournament.validate_submission_lease(
            forged,
            paper_client=paper_client,
            now=datetime.datetime(2026, 6, 4, 18, 0, tzinfo=datetime.timezone.utc),
        )

    forged["submission_lease_evidence"] = paper_tournament._submission_lease_evidence(forged)
    with pytest.raises(ValueError, match="inconsistent with the admitted market-day evidence"):
        paper_tournament.validate_submission_lease(
            forged,
            paper_client=paper_client,
            now=datetime.datetime(2026, 6, 4, 18, 0, tzinfo=datetime.timezone.utc),
        )
    assert paper_client.clock_calls == 0

    intact_now = datetime.datetime(2026, 6, 4, 18, 0, tzinfo=datetime.timezone.utc)
    paper_client.clock = {"is_open": True, "timestamp": intact_now.isoformat()}
    assert paper_tournament.validate_submission_lease(
        json.loads(json.dumps(ledger)),
        paper_client=paper_client,
        now=intact_now,
    ) == "2026-06-04"


def test_red_submission_admission_uses_admitted_market_dates_not_elapsed_wall_clock():
    paper_client = _FakePaperClient()
    ledger = _trial_ledger_with_calendar(paper_client)
    third_market_day = datetime.datetime(2026, 6, 4, 18, 0, tzinfo=datetime.timezone.utc)
    paper_client.clock = {"is_open": True, "timestamp": third_market_day.isoformat()}

    assert paper_tournament.validate_submission_lease(
        ledger,
        paper_client=paper_client,
        now=third_market_day,
    ) == "2026-06-04"

    holiday_calendar = [
        _market_calendar_entry("2026-06-01"),
        _market_calendar_entry("2026-06-02"),
        _market_calendar_entry("2026-06-03"),
        _market_calendar_entry("2026-06-05"),
        _market_calendar_entry("2026-06-08"),
    ]
    paper_client.calendar = [dict(entry) for entry in holiday_calendar]
    holiday_ledger = _trial_ledger_with_calendar(paper_client, calendar=holiday_calendar)
    fifth_market_day = datetime.datetime(2026, 6, 8, 18, 0, tzinfo=datetime.timezone.utc)
    paper_client.clock = {"is_open": True, "timestamp": fifth_market_day.isoformat()}

    assert holiday_ledger["ends_at"] == "2026-06-08T20:00:00+00:00"
    assert paper_tournament.validate_submission_lease(
        holiday_ledger,
        paper_client=paper_client,
        now=fifth_market_day,
    ) == "2026-06-08"


@pytest.mark.parametrize(
    "now_text",
    ["2026-05-29T18:00:00+00:00", "2026-06-06T18:00:00+00:00", "2026-06-08T18:00:00+00:00"],
    ids=["before-first-admitted-day", "weekend-inside-window", "sixth-market-day"],
)
def test_red_submission_fails_closed_outside_admitted_market_day_calendar(now_text):
    paper_client = _FakePaperClient()
    ledger = _trial_ledger_with_calendar(paper_client)
    outside = datetime.datetime.fromisoformat(now_text)
    paper_client.clock = {"is_open": True, "timestamp": outside.isoformat()}

    with pytest.raises(ValueError, match="outside the admitted market-day calendar"):
        paper_tournament.validate_submission_lease(
            ledger,
            paper_client=paper_client,
            now=outside,
        )
    assert paper_client.clock_calls == 0


@pytest.mark.parametrize(
    ("live_calendar", "reason"),
    [
        ([], "missing"),
        ([{"date": "2026-06-02"}], "malformed"),
        ([_market_calendar_entry("2026-06-02", close_text="16:30")], "changed"),
        (
            [
                _market_calendar_entry("2026-06-02"),
                _market_calendar_entry("2026-06-02"),
            ],
            "duplicated",
        ),
    ],
    ids=["missing-today-entry", "malformed-entry", "changed-session-times", "duplicated-entry"],
)
def test_red_submission_fails_closed_on_broker_calendar_evidence_defects(live_calendar, reason):
    paper_client = _FakePaperClient()
    ledger = _current_trial_ledger(paper_client)
    paper_client.calendar = list(live_calendar)

    with pytest.raises(ValueError, match="broker calendar evidence"):
        paper_tournament.validate_submission_lease(
            ledger,
            paper_client=paper_client,
            now=datetime.datetime(2026, 6, 2, 18, 0, tzinfo=datetime.timezone.utc),
        )
    assert paper_client.clock_calls == 0


def test_red_submission_fails_closed_when_broker_calendar_transport_is_unavailable():
    paper_client = _FakePaperClient()
    ledger = _current_trial_ledger(paper_client)

    def broken_calendar(*, start, end):
        raise RuntimeError("calendar transport down")

    paper_client.list_calendar = broken_calendar

    with pytest.raises(ValueError, match="broker calendar check failed"):
        paper_tournament.validate_submission_lease(
            ledger,
            paper_client=paper_client,
            now=datetime.datetime(2026, 6, 2, 18, 0, tzinfo=datetime.timezone.utc),
        )
    assert paper_client.clock_calls == 0


def test_red_early_close_session_bounds_come_from_calendar_evidence():
    paper_client = _FakePaperClient()
    early_close_calendar = [
        _market_calendar_entry(f"2026-06-0{day}") for day in range(1, 5)
    ] + [_market_calendar_entry("2026-06-05", close_text="13:00")]
    paper_client.calendar = [dict(entry) for entry in early_close_calendar]
    ledger = _trial_ledger_with_calendar(paper_client)

    after_early_close = datetime.datetime(2026, 6, 5, 17, 59, tzinfo=datetime.timezone.utc)
    paper_client.clock = {"is_open": True, "timestamp": after_early_close.isoformat()}
    with pytest.raises(ValueError, match="outside the regular session"):
        paper_tournament.validate_submission_lease(
            ledger,
            paper_client=paper_client,
            now=after_early_close,
        )

    before_early_close = datetime.datetime(2026, 6, 5, 16, 59, tzinfo=datetime.timezone.utc)
    paper_client.clock = {"is_open": True, "timestamp": before_early_close.isoformat()}
    assert paper_tournament.validate_submission_lease(
        ledger,
        paper_client=paper_client,
        now=before_early_close,
    ) == "2026-06-05"


def test_red_cli_init_persists_admitted_market_days_that_bind_later_submissions(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 1, 18, 0, tzinfo=datetime.timezone.utc),
    )

    initialized = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "init",
            "--max-submission-market-days", "5",
            "--json-output",
            "--log-dir", str(tmp_path),
        ],
    )

    assert initialized.exit_code == 0, initialized.output
    persisted = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert persisted["authorized_market_dates"] == REGULAR_WEEK_CALENDAR
    assert persisted["ends_at"] == "2026-06-05T20:00:00+00:00"
    assert persisted["authorized_market_day_limit"] == 5

    _configure_current_submit(monkeypatch, paper_client)
    submitted = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert submitted.exit_code == 0, submitted.output
    assert len(paper_client.submitted) == 1


def test_paper_tournament_init_bounds_submission_window_options(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)

    result = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "init", "--duration-days", "0",
            "--max-submission-market-days", "32", "--log-dir", str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert not (tmp_path / LEDGER_FILE).exists()


def test_paper_tournament_run_defaults_to_dry_run(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)

    result = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE, "--json-output", "--log-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["submitted_count"] == 0
    assert paper_client.submitted == []


def test_trial_dry_run_removes_a_preexisting_live_strategy_selection(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    selection_path = tmp_path / "live-strategy-selection.json"
    selection_path.write_text('{"status": "active"}', encoding="utf-8")
    _configure_current_submit(monkeypatch, paper_client)

    result = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert not selection_path.exists()
    assert paper_client.submitted == []


def test_paper_tournament_submit_requires_exact_paper_mode_and_endpoint(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    paper_client.settings = SimpleNamespace(paper=False, base_url="https://api.alpaca.markets")
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)

    result = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert paper_client.submitted == []
    assert "paper" in result.output.lower()


def test_paper_tournament_submit_rejects_unsafe_broker_clock_before_transaction_or_post(
    monkeypatch, tmp_path
):
    paper_client = _FakePaperClient()
    paper_client.clock = {"is_open": False, "timestamp": "2026-06-02T18:00:00+00:00"}
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)

    result = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert paper_client.clock_calls == 1
    assert paper_client.submitted == []
    updated = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert "submission_transaction" not in updated
    assert "clock" in result.output.lower()


@pytest.mark.parametrize(
    ("clock", "now"),
    [
        (None, "2026-06-02T18:00:00+00:00"),
        ({"is_open": False, "timestamp": "2026-06-02T13:00:00+00:00"}, "2026-06-02T18:00:00+00:00"),
        ({"is_open": False, "timestamp": "2026-06-02T21:00:00+00:00"}, "2026-06-02T18:00:00+00:00"),
        ({"is_open": True, "timestamp": "2026-06-02T17:44:00+00:00"}, "2026-06-02T18:00:00+00:00"),
        ({"is_open": True, "timestamp": "2026-06-02T18:00:01+00:00"}, "2026-06-02T18:00:00+00:00"),
        ({"is_open": True, "timestamp": "2026-06-02T18:16:00+00:00"}, "2026-06-02T18:00:00+00:00"),
        ({"is_open": True, "timestamp": "2026-06-02T13:00:00"}, "2026-06-02T18:00:00+00:00"),
        ({"is_open": True, "timestamp": "2026-06-03T06:01:00+00:00"}, "2026-06-03T05:59:00+00:00"),
    ],
    ids=["unavailable", "preopen", "afterhours", "stale", "slightly-future", "future", "malformed", "wrong-central-date"],
)
def test_paper_tournament_submit_never_posts_for_an_invalid_broker_clock(
    monkeypatch, tmp_path, clock, now
):
    paper_client = _FakePaperClient()
    paper_client.clock = clock
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)
    monkeypatch.setattr(cli_main, "_alpaca_policy_now", lambda: datetime.datetime.fromisoformat(now))

    result = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert paper_client.clock_calls == 1
    assert paper_client.submitted == []
    updated = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert "submission_transaction" not in updated


def test_paper_tournament_submit_records_current_regular_central_date_and_suppresses_selection(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    close_boundary = datetime.datetime(2026, 6, 2, 19, 59, 59, tzinfo=datetime.timezone.utc)
    paper_client.clock = {"is_open": True, "timestamp": close_boundary.isoformat()}
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)
    policy_times = iter([close_boundary] * 8)
    monkeypatch.setattr(cli_main, "_alpaca_policy_now", lambda: next(policy_times))

    result = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    updated = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert updated["submitted_market_dates"] == ["2026-06-02"]
    assert not (tmp_path / "live-strategy-selection.json").exists()
    assert paper_client.clock_calls == 3


def test_paper_tournament_submit_rechecks_clock_before_transaction_after_delayed_preparation(
    monkeypatch, tmp_path
):
    paper_client = _FakePaperClient()
    before_close = datetime.datetime(2026, 6, 2, 19, 59, 50, tzinfo=datetime.timezone.utc)
    after_close = datetime.datetime(2026, 6, 2, 20, 0, 1, tzinfo=datetime.timezone.utc)
    paper_client.clock = {"is_open": True, "timestamp": before_close.isoformat()}
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)
    policy_times = iter([before_close, before_close, before_close, after_close])
    monkeypatch.setattr(cli_main, "_alpaca_policy_now", lambda: next(policy_times))

    result = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert paper_client.clock_calls == 2
    assert paper_client.submitted == []
    updated = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert "submission_transaction" not in updated


def test_paper_tournament_submit_rechecks_clock_immediately_before_each_post(
    monkeypatch, tmp_path
):
    paper_client = _FakePaperClient()
    before_close = datetime.datetime(2026, 6, 2, 19, 59, 50, tzinfo=datetime.timezone.utc)
    after_close = datetime.datetime(2026, 6, 2, 20, 0, 1, tzinfo=datetime.timezone.utc)
    paper_client.clock = {"is_open": True, "timestamp": before_close.isoformat()}
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)
    policy_times = iter(
        [
            before_close, before_close,  # initial lease and post-clock sample
            before_close, before_close,  # transaction boundary and post-clock sample
            before_close, after_close, after_close,  # post boundary, clock, recovery
        ]
    )
    monkeypatch.setattr(cli_main, "_alpaca_policy_now", lambda: next(policy_times))

    result = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert paper_client.clock_calls == 3
    assert paper_client.submitted == []
    updated = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert updated["submission_window_status"] == "recovery_required"
    assert updated["submission_transaction"]["status"] == "recovery_required"


def test_paper_tournament_calendar_delay_rechecks_final_clock_before_any_post(
    monkeypatch, tmp_path
):
    paper_client = _FakePaperClient()
    before_close = datetime.datetime(2026, 6, 2, 19, 59, 50, tzinfo=datetime.timezone.utc)
    after_close = datetime.datetime(2026, 6, 2, 20, 0, 1, tzinfo=datetime.timezone.utc)
    paper_client.clock = {"is_open": True, "timestamp": before_close.isoformat()}
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)
    policy_time = {"value": before_close}
    original_list_calendar = paper_client.list_calendar
    calendar_calls = {"count": 0}

    def delayed_calendar(*, start, end):
        calendar_calls["count"] += 1
        if calendar_calls["count"] == 3:
            policy_time["value"] = after_close
        return original_list_calendar(start=start, end=end)

    monkeypatch.setattr(paper_client, "list_calendar", delayed_calendar)
    monkeypatch.setattr(cli_main, "_alpaca_policy_now", lambda: policy_time["value"])

    result = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert calendar_calls["count"] == 3
    assert paper_client.clock_calls == 3
    assert paper_client.submitted == []
    updated = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert updated["submission_window_status"] == "recovery_required"
    assert updated["submission_transaction"]["successful_submissions"] == []


def test_submission_lease_rejects_after_close_or_naive_policy_time():
    paper_client = _FakePaperClient()
    before_close = datetime.datetime(2026, 6, 2, 19, 59, 50, tzinfo=datetime.timezone.utc)
    paper_client.clock = {"is_open": True, "timestamp": before_close.isoformat()}
    ledger = _current_trial_ledger(paper_client)

    with pytest.raises(ValueError, match="regular session"):
        paper_tournament.validate_submission_lease(
            ledger,
            paper_client=paper_client,
            now=datetime.datetime(2026, 6, 2, 20, 0, 1, tzinfo=datetime.timezone.utc),
        )
    with pytest.raises(ValueError, match="malformed"):
        paper_tournament.validate_submission_lease(
            ledger,
            paper_client=paper_client,
            now=datetime.datetime(2026, 6, 2, 19, 59, 50),
        )


def test_submission_lease_brackets_broker_clock_with_post_response_policy_time():
    paper_client = _FakePaperClient()
    before_clock = datetime.datetime(2026, 6, 2, 18, 0, tzinfo=datetime.timezone.utc)
    paper_client.clock = {
        "is_open": True,
        "timestamp": (before_clock + datetime.timedelta(milliseconds=1)).isoformat(),
    }
    ledger = _current_trial_ledger(paper_client)

    assert paper_tournament.validate_submission_lease(
        ledger,
        paper_client=paper_client,
        now=before_clock,
        post_clock_now=lambda: before_clock + datetime.timedelta(milliseconds=2),
    ) == "2026-06-02"

    paper_client.clock["timestamp"] = (
        before_clock + datetime.timedelta(milliseconds=3)
    ).isoformat()
    with pytest.raises(ValueError, match="future"):
        paper_tournament.validate_submission_lease(
            ledger,
            paper_client=paper_client,
            now=before_clock,
            post_clock_now=lambda: before_clock + datetime.timedelta(milliseconds=2),
        )


def test_submission_lease_post_response_policy_time_governs_session_boundary_and_order():
    paper_client = _FakePaperClient()
    before_close = datetime.datetime(2026, 6, 1, 19, 59, 59, tzinfo=datetime.timezone.utc)
    after_close = datetime.datetime(2026, 6, 1, 20, 0, 1, tzinfo=datetime.timezone.utc)
    paper_client.clock = {"is_open": True, "timestamp": before_close.isoformat()}
    ledger = initialize_tournament(
        paper_account=paper_client.get_account(),
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=datetime.datetime(2026, 6, 1, 18, 0, tzinfo=datetime.timezone.utc),
        duration_days=1,
        max_submission_market_days=1,
        market_calendar=paper_client.calendar[:1],
    )
    assert ledger["ends_at"] == "2026-06-01T20:00:00+00:00"

    with pytest.raises(ValueError, match="outside the regular session"):
        paper_tournament.validate_submission_lease(
            ledger,
            paper_client=paper_client,
            now=before_close,
            post_clock_now=lambda: after_close,
        )
    with pytest.raises(ValueError, match="moved backwards"):
        paper_tournament.validate_submission_lease(
            _current_trial_ledger(paper_client),
            paper_client=paper_client,
            now=before_close,
            post_clock_now=lambda: before_close - datetime.timedelta(milliseconds=1),
        )


def test_submission_response_and_persisted_ledger_reject_reversed_record_times():
    paper_client = _FakePaperClient()
    ledger = _current_trial_ledger(paper_client)
    started_at = datetime.datetime(2026, 6, 2, 18, 0, tzinfo=datetime.timezone.utc)
    first_payload = {
        "strategy_id": STRATEGY_CURRENT_AGGRESSIVE,
        "symbol": "NVDA",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": "218.43",
        "notional": "1000.00",
        "extended_hours": False,
        "client_order_id": "ta-paperbot-current-aggressive-ordering-one",
        "reason": "test",
    }
    second_payload = {
        **first_payload,
        "strategy_id": STRATEGY_PULLBACK_SUPPORT,
        "client_order_id": "ta-paperbot-pullback-support-ordering-two",
    }
    paper_tournament.begin_submission_transaction(
        ledger,
        market_date="2026-06-02",
        payloads=[first_payload, second_payload],
        now=started_at,
    )
    paper_tournament.record_submission_response(
        ledger,
        payload=first_payload,
        response={
            "id": "paper-ordering-one",
            "status": "filled",
            **{key: value for key, value in first_payload.items() if key not in {"strategy_id", "reason"}},
        },
        market_date="2026-06-02",
        now=started_at + datetime.timedelta(minutes=2),
    )
    with pytest.raises(ValueError, match="monotonic"):
        paper_tournament.record_submission_response(
            ledger,
            payload=second_payload,
            response={
                "id": "paper-ordering-two",
                "status": "filled",
                **{key: value for key, value in second_payload.items() if key not in {"strategy_id", "reason"}},
            },
            market_date="2026-06-02",
            now=started_at + datetime.timedelta(minutes=1),
        )

    completed = json.loads(json.dumps(ledger))
    completed["submission_transaction"]["pending_client_order_ids"] = []
    completed["submission_transaction"]["successful_submissions"].append(
        {
            "client_order_id": "ta-paperbot-pullback-support-ordering-two",
            "market_date": "2026-06-02",
            "recorded_at": (started_at + datetime.timedelta(minutes=1)).isoformat(),
            "response": {"id": "paper-ordering-two", "status": "filled"},
        }
    )
    completed["submission_transaction"]["status"] = "completed"
    completed["submission_transaction"]["completed_at"] = (
        started_at + datetime.timedelta(minutes=3)
    ).isoformat()
    with pytest.raises(ValueError, match="recovery is required"):
        paper_tournament.validate_submission_transaction_state(completed)
    submitting = json.loads(json.dumps(completed))
    submitting["submission_transaction"]["status"] = "submitting"
    submitting["submission_transaction"].pop("completed_at")
    with pytest.raises(ValueError, match="monotonic"):
        paper_tournament.complete_submission_transaction(
            submitting,
            now=started_at + datetime.timedelta(minutes=3),
        )
    with pytest.raises(ValueError, match="monotonic"):
        paper_tournament.mark_submission_recovery_required(
            submitting,
            reason="test",
            now=started_at + datetime.timedelta(minutes=3),
        )


def test_submission_response_timestamps_allow_equal_values_across_all_validators():
    paper_client = _FakePaperClient()
    ledger = _current_trial_ledger(paper_client)
    timestamp = datetime.datetime(2026, 6, 2, 18, 0, tzinfo=datetime.timezone.utc)
    first_payload = {
        "strategy_id": STRATEGY_CURRENT_AGGRESSIVE,
        "symbol": "NVDA",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": "218.43",
        "notional": "1000.00",
        "extended_hours": False,
        "client_order_id": "ta-paperbot-current-aggressive-equal-one",
        "reason": "test",
    }
    second_payload = {
        **first_payload,
        "strategy_id": STRATEGY_PULLBACK_SUPPORT,
        "client_order_id": "ta-paperbot-pullback-support-equal-two",
    }
    paper_tournament.begin_submission_transaction(
        ledger,
        market_date="2026-06-02",
        payloads=[first_payload, second_payload],
        now=timestamp,
    )
    for index, payload in enumerate((first_payload, second_payload), start=1):
        paper_tournament.record_submission_response(
            ledger,
            payload=payload,
            response={
                "id": f"paper-equal-{index}",
                "status": "filled",
                **{key: value for key, value in payload.items() if key not in {"strategy_id", "reason"}},
            },
            market_date="2026-06-02",
            now=timestamp,
        )
    paper_tournament.complete_submission_transaction(ledger, now=timestamp)
    paper_tournament.validate_submission_transaction_state(ledger)

    recovery_ledger = json.loads(json.dumps(ledger))
    recovery_ledger["submission_transaction"]["status"] = "submitting"
    recovery_ledger["submission_transaction"].pop("completed_at")
    paper_tournament.mark_submission_recovery_required(
        recovery_ledger,
        reason="test",
        now=timestamp,
    )
    assert recovery_ledger["submission_transaction"]["failed_at"] == timestamp.isoformat()


def test_paper_tournament_submission_event_timestamps_are_monotonic(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    base = datetime.datetime(2026, 6, 2, 18, 0, tzinfo=datetime.timezone.utc)
    paper_client.clock = {"is_open": True, "timestamp": base.isoformat()}
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)
    policy_times = iter(
        [
            base,
            base,
            base + datetime.timedelta(minutes=1),
            base + datetime.timedelta(minutes=1),
            base + datetime.timedelta(minutes=2),
            base + datetime.timedelta(minutes=2),
            base + datetime.timedelta(minutes=3),
            base + datetime.timedelta(minutes=4),
        ]
    )
    monkeypatch.setattr(cli_main, "_alpaca_policy_now", lambda: next(policy_times))

    result = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    transaction = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))["submission_transaction"]
    assert transaction["started_at"] < transaction["successful_submissions"][0]["recorded_at"]
    assert transaction["successful_submissions"][0]["recorded_at"] < transaction["completed_at"]
    completed_ledger = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    paper_tournament.validate_submission_transaction_state(completed_ledger)
    completed_ledger["submission_transaction"]["completed_at"] = transaction["started_at"]
    with pytest.raises(ValueError, match="recovery is required"):
        paper_tournament.validate_submission_transaction_state(completed_ledger)


def test_paper_tournament_multi_order_close_between_posts_sends_zero_additional_posts(
    monkeypatch, tmp_path
):
    paper_client = _FakePaperClient()
    before_close = datetime.datetime(2026, 6, 2, 19, 59, 50, tzinfo=datetime.timezone.utc)
    after_close = datetime.datetime(2026, 6, 2, 20, 0, 1, tzinfo=datetime.timezone.utc)
    paper_client.clock = {"is_open": True, "timestamp": before_close.isoformat()}
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "NVDA": {
                "current_price": "218",
                "previous_close": "220",
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
    policy_times = iter(
        [
            before_close, before_close,  # initial lease and post-clock sample
            before_close, before_close,  # transaction boundary and post-clock sample
            before_close, before_close, before_close,  # first post, clock, response record
            before_close, after_close, after_close,  # second post, clock, recovery
        ]
    )
    monkeypatch.setattr(cli_main, "_alpaca_policy_now", lambda: next(policy_times))

    result = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--all",
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert paper_client.clock_calls == 4
    assert len(paper_client.submitted) == 1
    updated = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    transaction = updated["submission_transaction"]
    assert updated["submission_window_status"] == "recovery_required"
    assert transaction["status"] == "recovery_required"
    assert len(transaction["successful_submissions"]) == 1
    assert transaction["failed_at"] >= transaction["successful_submissions"][0]["recorded_at"]


def test_paper_tournament_submit_rejects_reused_or_exhausted_market_day(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    ledger = _current_trial_ledger(paper_client, max_submission_market_days=5)
    ledger["submitted_market_dates"] = ["2026-06-02"]
    write_tournament_ledger(ledger, tmp_path)
    _configure_current_submit(monkeypatch, paper_client)

    duplicate = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert duplicate.exit_code != 0
    assert paper_client.submitted == []
    assert "already" in duplicate.output.lower()

    ledger["submitted_market_dates"] = [
        "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29", "2026-06-01",
    ]
    write_tournament_ledger(ledger, tmp_path)
    exhausted = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert exhausted.exit_code != 0
    assert paper_client.submitted == []
    assert "capacity" in exhausted.output.lower()


def test_paper_tournament_submit_rejects_stale_or_future_lease_before_transport(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    _configure_current_submit(monkeypatch, paper_client)
    ledger = _current_trial_ledger(paper_client)
    ledger["ends_at"] = "2026-06-02T17:59:59+00:00"
    write_tournament_ledger(ledger, tmp_path)

    expired = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert expired.exit_code != 0
    assert paper_client.submitted == []

    ledger = _current_trial_ledger(paper_client)
    ledger["started_at"] = "2026-06-03T18:00:00+00:00"
    write_tournament_ledger(ledger, tmp_path)
    future = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert future.exit_code != 0
    assert paper_client.submitted == []


def test_paper_tournament_finalize_closes_lease_and_rejects_future_submission(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)
    submitted = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )
    assert submitted.exit_code == 0, submitted.output

    finalized = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "finalize", "--json-output", "--log-dir", str(tmp_path)],
    )

    assert finalized.exit_code == 0, finalized.output
    assert json.loads(finalized.stdout)["submission_window_status"] == "finalized"
    assert len(paper_client.submitted) == 1

    rejected = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert rejected.exit_code != 0
    assert len(paper_client.submitted) == 1


def test_paper_tournament_finalize_rejects_open_tournament_orders(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)
    submitted = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )
    assert submitted.exit_code == 0, submitted.output
    paper_client.orders[0]["status"] = "new"

    finalized = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "finalize", "--json-output", "--log-dir", str(tmp_path)],
    )

    assert finalized.exit_code != 0
    assert "open" in finalized.output.lower()
    updated = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert updated["submission_window_status"] == "open"


def test_paper_tournament_concurrent_submits_post_once_and_consume_one_date(monkeypatch, tmp_path):
    paper_client = _BlockingPaperClient()
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)
    errors = []

    def submit_once():
        try:
            cli_main.alpaca_paper_tournament_run(
                strategy=STRATEGY_CURRENT_AGGRESSIVE,
                all_strategies=False,
                dry_run=False,
                json_output=False,
                log_dir=tmp_path,
                min_promotion_days=5,
            )
        except Exception as exc:  # The rejected concurrent request is expected.
            errors.append(exc)

    first = Thread(target=submit_once)
    first.start()
    assert paper_client.post_started.wait(timeout=5)
    second = Thread(target=submit_once)
    second.start()
    second.join(timeout=0.2)
    assert len(paper_client.submitted) == 1

    paper_client.release_post.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(paper_client.submitted) == 1
    assert len(errors) == 1
    updated = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert updated["submitted_market_dates"] == ["2026-06-02"]


def test_paper_tournament_submit_persists_partial_post_evidence_and_blocks_retry(monkeypatch, tmp_path):
    paper_client = _MalformedSecondResponsePaperClient()
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "NVDA": {
                "current_price": "218",
                "previous_close": "220",
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

    failed = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "run", "--all", "--submit-actions", "--json-output", "--log-dir", str(tmp_path)],
    )

    assert failed.exit_code != 0
    updated = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert updated["submission_window_status"] == "recovery_required"
    assert updated["submitted_market_dates"] == ["2026-06-02"]
    recorded = updated["strategies"][STRATEGY_CURRENT_AGGRESSIVE]["orders"]
    assert recorded[0]["client_order_id"] == paper_client.submitted[0]["client_order_id"]
    assert updated["submission_transaction"]["successful_submissions"][0]["client_order_id"] == recorded[0]["client_order_id"]

    retry = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert retry.exit_code != 0
    assert paper_client.submit_attempts == 2


def test_interrupted_submission_transaction_blocks_retry_before_transport(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    persisted = _persist_interrupted_submission(paper_client, tmp_path)
    selection_path = tmp_path / "live-strategy-selection.json"
    selection_path.write_text('{"status": "active"}', encoding="utf-8")
    _configure_current_submit(monkeypatch, paper_client)

    retry = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert retry.exit_code != 0
    assert len(paper_client.submitted) == 1
    assert not selection_path.exists()
    updated = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert updated["submission_window_status"] == "open"
    assert updated["submission_transaction"] == persisted["submission_transaction"]


def test_interrupted_submission_transaction_blocks_finalization(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    persisted = _persist_interrupted_submission(paper_client, tmp_path)
    paper_client.orders.clear()
    paper_client.list_order_calls = 0
    original_list_orders = paper_client.list_orders

    def tracked_list_orders(*args, **kwargs):
        paper_client.list_order_calls += 1
        return original_list_orders(*args, **kwargs)

    paper_client.list_orders = tracked_list_orders
    _configure_current_submit(monkeypatch, paper_client)

    finalized = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "finalize", "--json-output", "--log-dir", str(tmp_path)],
    )

    assert finalized.exit_code != 0
    assert paper_client.list_order_calls == 0
    updated = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert updated["submission_window_status"] == "open"
    assert updated["submission_transaction"] == persisted["submission_transaction"]


def test_trial_report_removes_and_never_writes_live_strategy_selection(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    ledger = _current_trial_ledger(paper_client)
    days = [f"2026-06-0{day}T20:05:00+00:00" for day in range(1, 6)]
    for strategy_id, equity in {
        STRATEGY_CURRENT_AGGRESSIVE: Decimal("10125"),
        "pullback-support": Decimal("10080"),
        "catalyst-relative-strength": Decimal("10060"),
    }.items():
        ledger["strategies"][strategy_id]["equity_history"] = [
            {"generated_at": day, "equity": str(Decimal("10000") + Decimal(index * 5))}
            for index, day in enumerate(days[:-1])
        ] + [{"generated_at": days[-1], "equity": str(equity)}]
    write_tournament_ledger(ledger, tmp_path)
    (tmp_path / "live-strategy-selection.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 5, 20, 10, tzinfo=datetime.timezone.utc),
    )
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {})

    result = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "report", "--json-output", "--log-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "live-strategy-selection.json").exists()
    updated = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert updated["live_strategy_selection"]["status"] == "pending"


def test_paper_tournament_finalize_preflight_rejects_bad_endpoint_before_broker_read(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    paper_client.settings = SimpleNamespace(paper=False, base_url="https://api.alpaca.markets")
    paper_client.list_order_calls = 0
    original_list_orders = paper_client.list_orders

    def tracked_list_orders(*args, **kwargs):
        paper_client.list_order_calls += 1
        return original_list_orders(*args, **kwargs)

    paper_client.list_orders = tracked_list_orders
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)

    result = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "finalize", "--json-output", "--log-dir", str(tmp_path)],
    )

    assert result.exit_code != 0
    assert paper_client.list_order_calls == 0


def test_paper_tournament_finalize_rejects_duplicate_or_missing_order_evidence(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)
    submitted = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )
    assert submitted.exit_code == 0, submitted.output
    ledger = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    orders = ledger["strategies"][STRATEGY_CURRENT_AGGRESSIVE]["orders"]
    orders.append(dict(orders[0]))
    write_tournament_ledger(ledger, tmp_path)

    duplicate = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "finalize", "--json-output", "--log-dir", str(tmp_path)],
    )

    assert duplicate.exit_code != 0
    assert json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))["submission_window_status"] == "open"

    orders.pop()
    paper_client.orders.clear()
    write_tournament_ledger(ledger, tmp_path)
    missing = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "finalize", "--json-output", "--log-dir", str(tmp_path)],
    )

    assert missing.exit_code != 0
    assert json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))["submission_window_status"] == "open"


class _RecordingPaperClient(_FakePaperClient):
    """Fake client that records every broker read so tests can prove zero transport."""

    def __init__(self):
        super().__init__()
        self.read_calls = []

    def get_account(self):
        self.read_calls.append("get_account")
        return super().get_account()

    def list_positions(self):
        self.read_calls.append("list_positions")
        return super().list_positions()

    def list_orders(self, status="open", **kwargs):
        self.read_calls.append(f"list_orders:{status}")
        return super().list_orders(status=status)

    def list_calendar(self, *, start, end):
        self.read_calls.append("list_calendar")
        return super().list_calendar(start=start, end=end)

    def get_clock(self):
        self.read_calls.append("get_clock")
        return super().get_clock()


def _loaded_ledger(output_dir):
    return json.loads((Path(output_dir) / LEDGER_FILE).read_text(encoding="utf-8"))


def _persist_recovery_required_root(paper_client, tmp_path) -> None:
    """Submit one real order through the durable transaction, then seal recovery."""

    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    payload = {
        "strategy_id": STRATEGY_CURRENT_AGGRESSIVE,
        "symbol": "NVDA",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": "218.43",
        "notional": "1000.00",
        "extended_hours": False,
        "client_order_id": "ta-paperbot-current-aggressive-recovery-20260602",
        "reason": "simulated accepted post before process loss",
    }
    submit_now = datetime.datetime(2026, 6, 2, 18, 0, tzinfo=datetime.timezone.utc)
    ledger = _loaded_ledger(tmp_path)
    paper_tournament.begin_submission_transaction(
        ledger,
        market_date="2026-06-02",
        payloads=[payload],
        now=submit_now,
    )
    response = paper_client.submit_order(
        {key: value for key, value in payload.items() if key not in {"strategy_id", "reason"}}
    )
    paper_tournament.record_submission_response(
        ledger,
        payload=payload,
        response=response,
        market_date="2026-06-02",
        now=submit_now,
    )
    paper_tournament.complete_submission_transaction(
        ledger,
        now=submit_now + datetime.timedelta(minutes=1),
    )
    paper_tournament.mark_submission_recovery_required(
        ledger,
        reason="simulated uncertain re-post before process loss",
        now=submit_now + datetime.timedelta(minutes=2),
    )
    write_tournament_ledger(ledger, tmp_path)


def test_red_abort_submission_lease_permanently_retires_recovery_required_root(monkeypatch, tmp_path):
    paper_client = _RecordingPaperClient()
    _persist_recovery_required_root(paper_client, tmp_path)
    _configure_current_submit(monkeypatch, paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 2, 18, 5, tzinfo=datetime.timezone.utc),
    )

    reads_after_submit = list(paper_client.read_calls)

    aborted = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "abort-submission-lease",
            "--reason", "operator retired the uncertain root",
            "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert aborted.exit_code == 0, aborted.output
    packet = json.loads(aborted.stdout)
    assert packet["kind"] == "paper_tournament_abort"
    assert packet["submission_window_status"] == "aborted"
    updated = _loaded_ledger(tmp_path)
    assert updated["submission_window_status"] == "aborted"
    assert updated["submission_transaction"]["status"] == "aborted"
    assert updated["submission_abortion"]["reason"] == "operator retired the uncertain root"
    assert updated["submitted_market_dates"] == ["2026-06-02"]

    retry = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert retry.exit_code != 0
    finalized = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "finalize", "--json-output", "--log-dir", str(tmp_path)],
    )

    assert finalized.exit_code != 0
    repeated_abort = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "abort-submission-lease",
            "--reason", "second attempt must refuse",
            "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert repeated_abort.exit_code != 0
    final_ledger = _loaded_ledger(tmp_path)
    assert final_ledger["submission_window_status"] == "aborted"
    # Retirement made no broker call: reads are exactly the original submission path.
    assert paper_client.read_calls == reads_after_submit
    assert len(paper_client.submitted) == 1


def test_red_abort_submission_lease_refuses_open_and_finalized_roots(monkeypatch, tmp_path):
    paper_client = _RecordingPaperClient()
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    monkeypatch.setattr(cli_main, "_alpaca_policy_now", lambda: datetime.datetime(2026, 6, 2, 18, 10, tzinfo=datetime.timezone.utc))

    refused_open = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "abort-submission-lease",
            "--reason", "must refuse healthy roots",
            "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert refused_open.exit_code != 0
    unchanged = _loaded_ledger(tmp_path)
    assert unchanged["submission_window_status"] == "open"
    assert "submission_abortion" not in unchanged

    _configure_current_submit(monkeypatch, paper_client)
    submitted = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "run", "--strategy", STRATEGY_CURRENT_AGGRESSIVE,
            "--submit-actions", "--json-output", "--log-dir", str(tmp_path),
        ],
    )
    assert submitted.exit_code == 0, submitted.output
    finalized = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "finalize", "--json-output", "--log-dir", str(tmp_path)],
    )
    assert finalized.exit_code == 0, finalized.output

    refused_finalized = runner.invoke(
        app,
        [
            "alpaca", "paper-tournament", "abort-submission-lease",
            "--reason", "must refuse finalized roots",
            "--json-output", "--log-dir", str(tmp_path),
        ],
    )

    assert refused_finalized.exit_code != 0
    assert _loaded_ledger(tmp_path)["submission_window_status"] == "finalized"

    missing_reason = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "abort-submission-lease", "--json-output", "--log-dir", str(tmp_path)],
    )

    assert missing_reason.exit_code != 0


def test_red_abort_submission_lease_unit_guards_fail_closed():
    paper_client = _FakePaperClient()
    ledger = _current_trial_ledger(paper_client)
    now = datetime.datetime(2026, 6, 2, 18, 0, tzinfo=datetime.timezone.utc)

    with pytest.raises(ValueError, match="recovery"):
        paper_tournament.abort_submission_lease(ledger, reason="healthy root", now=now)

    paper_tournament.begin_submission_transaction(
        ledger,
        market_date="2026-06-02",
        payloads=[
            {
                "strategy_id": STRATEGY_CURRENT_AGGRESSIVE,
                "symbol": "NVDA",
                "side": "buy",
                "type": "limit",
                "time_in_force": "day",
                "limit_price": "218.43",
                "notional": "1000.00",
                "extended_hours": False,
                "client_order_id": "ta-paperbot-current-aggressive-unitguard-20260602",
                "reason": "unit guard",
            }
        ],
        now=now,
    )
    paper_tournament.mark_submission_recovery_required(
        ledger,
        reason="simulated uncertainty",
        now=now + datetime.timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="monotonic"):
        paper_tournament.abort_submission_lease(
            ledger,
            reason="backwards clock",
            now=now,
        )

    with pytest.raises(ValueError, match="reason"):
        paper_tournament.abort_submission_lease(
            ledger,
            reason="   ",
            now=now + datetime.timedelta(minutes=2),
        )

    abortion = paper_tournament.abort_submission_lease(
        ledger,
        reason="retire root",
        now=now + datetime.timedelta(minutes=2),
    )

    assert abortion["status"] == "aborted"
    assert ledger["submission_window_status"] == "aborted"
    assert ledger["submission_transaction"]["status"] == "aborted"
    with pytest.raises(ValueError, match="recovery|aborted"):
        paper_tournament.abort_submission_lease(ledger, reason="again", now=now + datetime.timedelta(minutes=3))


def test_red_mark_recovery_required_cannot_revive_an_aborted_root(monkeypatch):
    import copy

    paper_client = _FakePaperClient()
    ledger = _current_trial_ledger(paper_client)
    now = datetime.datetime(2026, 6, 2, 18, 0, tzinfo=datetime.timezone.utc)
    paper_tournament.begin_submission_transaction(
        ledger,
        market_date="2026-06-02",
        payloads=[
            {
                "strategy_id": STRATEGY_CURRENT_AGGRESSIVE,
                "symbol": "NVDA",
                "side": "buy",
                "type": "limit",
                "time_in_force": "day",
                "limit_price": "218.43",
                "notional": "1000.00",
                "extended_hours": False,
                "client_order_id": "ta-paperbot-current-aggressive-revival-20260602",
                "reason": "revival guard",
            }
        ],
        now=now,
    )
    paper_tournament.mark_submission_recovery_required(
        ledger,
        reason="simulated uncertainty",
        now=now + datetime.timedelta(minutes=1),
    )
    abortion = paper_tournament.abort_submission_lease(
        ledger,
        reason="retire root",
        now=now + datetime.timedelta(minutes=2),
    )
    assert abortion["status"] == "aborted"
    snapshot = copy.deepcopy(ledger)

    with pytest.raises(ValueError, match="aborted"):
        paper_tournament.mark_submission_recovery_required(
            ledger,
            reason="direct revival attempt",
            now=now + datetime.timedelta(minutes=3),
        )

    assert ledger == snapshot
    with pytest.raises(ValueError, match="aborted"):
        paper_tournament.abort_submission_lease(
            ledger,
            reason="second retirement attempt",
            now=now + datetime.timedelta(minutes=3),
        )
    assert ledger == snapshot


def test_red_write_refuses_replacing_an_aborted_root_ledger(tmp_path):
    paper_client = _FakePaperClient()
    now = datetime.datetime(2026, 6, 2, 18, 0, tzinfo=datetime.timezone.utc)
    ledger = _current_trial_ledger(paper_client)
    paper_tournament.begin_submission_transaction(
        ledger,
        market_date="2026-06-02",
        payloads=[
            {
                "strategy_id": STRATEGY_CURRENT_AGGRESSIVE,
                "symbol": "NVDA",
                "side": "buy",
                "type": "limit",
                "time_in_force": "day",
                "limit_price": "218.43",
                "notional": "1000.00",
                "extended_hours": False,
                "client_order_id": "ta-paperbot-current-aggressive-overwrite-20260602",
                "reason": "overwrite guard",
            }
        ],
        now=now,
    )
    paper_tournament.mark_submission_recovery_required(
        ledger,
        reason="simulated uncertainty",
        now=now + datetime.timedelta(minutes=1),
    )
    # Writing the actual abort is allowed.
    paper_tournament.abort_submission_lease(
        ledger,
        reason="retire the uncertain root",
        now=now + datetime.timedelta(minutes=2),
    )
    written = write_tournament_ledger(ledger, tmp_path)
    assert json.loads(written.read_text(encoding="utf-8"))["submission_window_status"] == "aborted"

    # Later same-ledger records keep the retirement and stay writable.
    ledger["strategies"][STRATEGY_CURRENT_AGGRESSIVE]["cash"] = "9999.99"
    write_tournament_ledger(ledger, tmp_path)

    # A fresh or record-less ledger may never replace the retired root.
    replacement = _current_trial_ledger(_FakePaperClient())
    with pytest.raises(ValueError, match="permanently retired"):
        write_tournament_ledger(replacement, tmp_path)

    # Keeping the record but flipping the window back open is also revival.
    revival = json.loads(json.dumps(ledger))
    revival["submission_window_status"] = "open"
    with pytest.raises(ValueError, match="permanently retired"):
        write_tournament_ledger(revival, tmp_path)

    on_disk = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert on_disk["submission_abortion"]["reason"] == "retire the uncertain root"
    assert on_disk["submission_window_status"] == "aborted"
    assert on_disk["strategies"][STRATEGY_CURRENT_AGGRESSIVE]["cash"] == "9999.99"


def test_red_cli_init_cannot_replace_an_aborted_root(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 1, 18, 0, tzinfo=datetime.timezone.utc),
    )
    initialized = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "init", "--max-submission-market-days", "5",
         "--json-output", "--log-dir", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output

    _persist_recovery_required_root(paper_client, tmp_path)
    ledger = _loaded_ledger(tmp_path)
    paper_tournament.abort_submission_lease(
        ledger,
        reason="operator retired the uncertain root",
        now=datetime.datetime(2026, 6, 2, 18, 5, tzinfo=datetime.timezone.utc),
    )
    write_tournament_ledger(ledger, tmp_path)
    retired = _loaded_ledger(tmp_path)

    reinitialized = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "init", "--max-submission-market-days", "5",
         "--json-output", "--log-dir", str(tmp_path)],
    )

    assert reinitialized.exit_code != 0
    on_disk = _loaded_ledger(tmp_path)
    assert on_disk == retired
    assert on_disk["submission_window_status"] == "aborted"

    # A genuinely fresh directory still initializes normally.
    fresh_dir = tmp_path / "fresh-root"
    fresh_init = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "init", "--max-submission-market-days", "5",
         "--json-output", "--log-dir", str(fresh_dir)],
    )
    assert fresh_init.exit_code == 0, fresh_init.output
    fresh_ledger = _loaded_ledger(fresh_dir)
    assert fresh_ledger["submission_window_status"] == "open"
    assert "submission_abortion" not in fresh_ledger


def test_red_write_refuses_invalid_existing_ledger_before_any_overwrite(tmp_path):
    replacement = _current_trial_ledger(_FakePaperClient())

    corrupt_dir = tmp_path / "corrupt-root"
    corrupt_dir.mkdir(parents=True)
    (corrupt_dir / LEDGER_FILE).write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="unreadable or invalid"):
        write_tournament_ledger(replacement, corrupt_dir)
    assert (corrupt_dir / LEDGER_FILE).read_text(encoding="utf-8") == "{not-json"

    nonmapping_dir = tmp_path / "nonmapping-root"
    nonmapping_dir.mkdir(parents=True)
    (nonmapping_dir / LEDGER_FILE).write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="unreadable or invalid"):
        write_tournament_ledger(replacement, nonmapping_dir)
    assert (nonmapping_dir / LEDGER_FILE).read_text(encoding="utf-8") == "[]"


def test_red_cli_init_cannot_replace_a_malformed_existing_ledger(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 1, 18, 0, tzinfo=datetime.timezone.utc),
    )
    (tmp_path / LEDGER_FILE).write_text("{not-json", encoding="utf-8")

    refused = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "init", "--max-submission-market-days", "5",
         "--json-output", "--log-dir", str(tmp_path)],
    )

    assert refused.exit_code != 0
    assert (tmp_path / LEDGER_FILE).read_text(encoding="utf-8") == "{not-json"

    fresh_dir = tmp_path / "fresh-root"
    fresh_init = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "init", "--max-submission-market-days", "5",
         "--json-output", "--log-dir", str(fresh_dir)],
    )
    assert fresh_init.exit_code == 0, fresh_init.output
    fresh_ledger = _loaded_ledger(fresh_dir)
    assert fresh_ledger["submission_window_status"] == "open"
    assert "submission_abortion" not in fresh_ledger


def _install_lock_order_probe(monkeypatch):
    """Record acquire/guard/ledger-write/release ordering for one test."""

    import contextlib

    events = []
    real_lock = paper_tournament.tournament_submission_lock
    real_guard = paper_tournament._refuse_replacing_retired_root
    real_atomic = paper_tournament._atomic_write_text

    @contextlib.contextmanager
    def tracking_lock(output_dir):
        events.append("acquire")
        try:
            with real_lock(output_dir):
                yield
        finally:
            events.append("release")

    def tracking_guard(ledger_path, ledger):
        events.append("guard")
        real_guard(ledger_path, ledger)

    def tracking_atomic(path, text):
        events.append(f"write:{Path(path).name}")
        real_atomic(path, text)

    monkeypatch.setattr(paper_tournament, "tournament_submission_lock", tracking_lock)
    monkeypatch.setattr(paper_tournament, "_refuse_replacing_retired_root", tracking_guard)
    monkeypatch.setattr(paper_tournament, "_atomic_write_text", tracking_atomic)
    return events


def test_red_init_and_watch_hold_the_per_root_lock_across_guard_and_ledger_write(
    monkeypatch, tmp_path
):
    paper_client = _FakePaperClient()
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 1, 18, 0, tzinfo=datetime.timezone.utc),
    )

    init_events = _install_lock_order_probe(monkeypatch)
    initialized = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "init", "--max-submission-market-days", "5",
         "--json-output", "--log-dir", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    assert ["acquire", "guard", f"write:{LEDGER_FILE}"] == init_events[:3]
    assert init_events.index("release") > init_events.index(f"write:{LEDGER_FILE}")

    init_events.clear()
    watched = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "alphainsider-watch", "--json-output",
         "--log-dir", str(tmp_path)],
    )
    assert watched.exit_code == 0, watched.output
    assert ["acquire", "guard", f"write:{LEDGER_FILE}"] == init_events[:3]
    assert init_events.index("release") > init_events.index(f"write:{LEDGER_FILE}")


def test_red_alphainsider_watch_update_respects_an_aborted_root_under_lock(
    monkeypatch, tmp_path
):
    """Watch persists its plan without ever dropping a root's retirement."""

    paper_client = _FakePaperClient()
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 2, 18, 40, tzinfo=datetime.timezone.utc),
    )
    _persist_recovery_required_root(paper_client, tmp_path)
    ledger = _loaded_ledger(tmp_path)
    paper_tournament.abort_submission_lease(
        ledger,
        reason="operator retired the uncertain root",
        now=datetime.datetime(2026, 6, 2, 18, 41, tzinfo=datetime.timezone.utc),
    )
    write_tournament_ledger(ledger, tmp_path)
    retired = _loaded_ledger(tmp_path)
    events = _install_lock_order_probe(monkeypatch)

    watched = runner.invoke(
        app,
        ["alpaca", "paper-tournament", "alphainsider-watch", "--json-output",
         "--log-dir", str(tmp_path)],
    )

    assert watched.exit_code == 0, watched.output
    assert events[:3] == ["acquire", "guard", f"write:{LEDGER_FILE}"]
    assert events.index("release") > events.index(f"write:{LEDGER_FILE}")
    on_disk = _loaded_ledger(tmp_path)
    # Retirement survives the update under structural JSON equality: window and record
    # are exactly the persisted ones, only the plan section was added.
    assert on_disk["submission_window_status"] == "aborted"
    assert on_disk["submission_abortion"] == retired["submission_abortion"]
    assert "alphainsider_paper_watch_plan" in on_disk


def test_submit_finalize_interleaving_preserves_finalized_lease(monkeypatch, tmp_path):
    paper_client = _BlockingPaperClient()
    write_tournament_ledger(_current_trial_ledger(paper_client), tmp_path)
    _configure_current_submit(monkeypatch, paper_client)
    errors = []

    def submit_once():
        try:
            cli_main.alpaca_paper_tournament_run(
                strategy=STRATEGY_CURRENT_AGGRESSIVE,
                all_strategies=False,
                dry_run=False,
                json_output=False,
                log_dir=tmp_path,
                min_promotion_days=5,
            )
        except Exception as exc:
            errors.append(exc)

    def finalize_once():
        try:
            cli_main.alpaca_paper_tournament_finalize(json_output=False, log_dir=tmp_path)
        except Exception as exc:
            errors.append(exc)

    submit_thread = Thread(target=submit_once)
    submit_thread.start()
    assert paper_client.post_started.wait(timeout=5)
    finalize_thread = Thread(target=finalize_once)
    finalize_thread.start()
    finalize_thread.join(timeout=0.2)

    paper_client.release_post.set()
    submit_thread.join(timeout=5)
    finalize_thread.join(timeout=5)

    assert not submit_thread.is_alive()
    assert not finalize_thread.is_alive()
    assert errors == []
    updated = json.loads((tmp_path / LEDGER_FILE).read_text(encoding="utf-8"))
    assert updated["submission_window_status"] == "finalized"
    assert updated["submitted_market_dates"] == ["2026-06-02"]


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


def test_tournament_timestamp_parsing_and_expiry_boundaries_fail_closed():
    equality = datetime.datetime(2026, 6, 5, 20, 10, tzinfo=datetime.timezone.utc)

    assert _tournament_expired("2026-06-05T20:10:00+00:00", now=equality)
    assert not _tournament_expired(None, now=equality)
    assert _parse_timestamp("not-a-timestamp") is None
    assert _tournament_expired("2026-06-05T15:10:00-05:00", now=equality)
    assert _parse_timestamp("2026-06-05T20:10:00") == equality
    assert _parse_timestamp("9999-12-31T23:59:59-23:59") is None


def test_expired_tournament_fingerprint_is_read_only_and_fail_closed():
    now = datetime.datetime(2026, 6, 5, 20, 10, tzinfo=datetime.timezone.utc)
    ledger_bytes = json.dumps(
        {
            "tournament_id": "retired-paper-root",
            "ends_at": "2026-06-05T20:10:00+00:00",
        },
        sort_keys=True,
    ).encode("utf-8")

    identity = fingerprint_expired_tournament_ledger(ledger_bytes, now=now)

    assert identity["tournament_id"] == "retired-paper-root"
    assert identity["ledger_sha256"] == hashlib.sha256(ledger_bytes).hexdigest()
    with pytest.raises(ValueError, match="not verifiably expired"):
        fingerprint_expired_tournament_ledger(
            json.dumps(
                {
                    "tournament_id": "current-root",
                    "ends_at": "2026-06-05T20:10:01+00:00",
                }
            ).encode("utf-8"),
            now=now,
        )
    with pytest.raises(ValueError, match="valid UTF-8 JSON"):
        fingerprint_expired_tournament_ledger(b"not-json", now=now)


def _write_bound_active_selection(tournament_dir, *, strategy_id="pullback-support"):
    start = datetime.datetime(2026, 6, 1, 18, 0, tzinfo=datetime.timezone.utc)
    ledger = initialize_tournament(
        paper_account={"status": "ACTIVE", "equity": "100000"},
        paper_positions=[],
        capital_per_strategy=Decimal("10000"),
        now=start,
    )
    ledger["ledger_type"] = "legacy_paper_tournament"
    ledger["submission_lease_evidence"] = paper_tournament._submission_lease_evidence(ledger)
    days = [f"2026-06-0{day}T20:05:00+00:00" for day in range(1, 6)]
    final_equity = {
        STRATEGY_CURRENT_AGGRESSIVE: Decimal("10050"),
        "pullback-support": Decimal("10080"),
        "catalyst-relative-strength": Decimal("10060"),
    }
    final_equity[strategy_id] = Decimal("10125")
    for sleeve_id, equity in final_equity.items():
        ledger["strategies"][sleeve_id]["equity_history"] = [
            {"generated_at": day, "equity": str(Decimal("10000") + Decimal(index * 5))}
            for index, day in enumerate(days[:-1])
        ] + [{"generated_at": days[-1], "equity": str(equity)}]
    report_now = datetime.datetime(2026, 6, 5, 20, 10, tzinfo=datetime.timezone.utc)
    report = build_tournament_report(ledger, market_data={}, now=report_now, min_promotion_days=5)
    assert report["live_strategy_candidate"]["strategy_id"] == strategy_id
    ledger["latest_report"] = report
    write_tournament_ledger(ledger, tournament_dir)
    selection_path = maybe_write_live_strategy_selection(
        report,
        tournament_dir,
        now=report_now + datetime.timedelta(minutes=1),
    )
    assert selection_path is not None
    return report


def test_nontrial_tournament_selection_behavior_remains_compatible(tmp_path):
    report = _write_bound_active_selection(tmp_path)

    selection = load_live_strategy_selection(
        tmp_path,
        now=datetime.datetime(2026, 6, 5, 20, 11, tzinfo=datetime.timezone.utc),
    )

    assert selection is not None
    assert selection["strategy_id"] == report["live_strategy_candidate"]["strategy_id"]


def test_bound_preexpiry_selection_is_rejected_after_tournament_window(tmp_path):
    report = _write_bound_active_selection(tmp_path)

    preexpiry_selection = load_live_strategy_selection(
        tmp_path,
        now=datetime.datetime(2026, 6, 6, 20, 10, tzinfo=datetime.timezone.utc),
    )
    expired_selection = load_live_strategy_selection(
        tmp_path,
        now=datetime.datetime(2026, 7, 2, 18, 0, tzinfo=datetime.timezone.utc),
    )
    future_selection = load_live_strategy_selection(
        tmp_path,
        now=datetime.datetime(2026, 6, 5, 20, 10, tzinfo=datetime.timezone.utc),
    )

    assert preexpiry_selection is not None
    assert preexpiry_selection["strategy_id"] == report["live_strategy_candidate"]["strategy_id"]
    assert preexpiry_selection["source_report"]["tournament_id"] == report["tournament_id"]
    assert expired_selection is None
    assert future_selection is None


def test_loader_rejects_missing_or_mismatched_selection_source_metadata(tmp_path):
    missing_dir = tmp_path / "missing"
    missing_dir.mkdir()
    _write_bound_active_selection(missing_dir)
    missing_path = missing_dir / "live-strategy-selection.json"
    missing_selection = json.loads(missing_path.read_text(encoding="utf-8"))
    missing_selection.pop("source_report")
    missing_path.write_text(json.dumps(missing_selection), encoding="utf-8")

    mismatched_dir = tmp_path / "mismatched"
    mismatched_dir.mkdir()
    _write_bound_active_selection(mismatched_dir)
    mismatched_path = mismatched_dir / "live-strategy-selection.json"
    mismatched_selection = json.loads(mismatched_path.read_text(encoding="utf-8"))
    mismatched_selection["source_report"]["candidate_strategy_id"] = STRATEGY_CURRENT_AGGRESSIVE
    mismatched_path.write_text(json.dumps(mismatched_selection), encoding="utf-8")

    top_level_mismatch_dir = tmp_path / "top_level_mismatch"
    top_level_mismatch_dir.mkdir()
    _write_bound_active_selection(top_level_mismatch_dir)
    top_level_mismatch_path = top_level_mismatch_dir / "live-strategy-selection.json"
    top_level_mismatch_selection = json.loads(top_level_mismatch_path.read_text(encoding="utf-8"))
    top_level_mismatch_selection["strategy_id"] = STRATEGY_CURRENT_AGGRESSIVE
    top_level_mismatch_path.write_text(json.dumps(top_level_mismatch_selection), encoding="utf-8")

    assert load_live_strategy_selection(missing_dir) is None
    assert load_live_strategy_selection(mismatched_dir) is None
    assert load_live_strategy_selection(top_level_mismatch_dir) is None


def test_loader_rejects_ledger_top_level_identity_or_expiry_mismatch(tmp_path):
    id_mismatch_dir = tmp_path / "ledger_id_mismatch"
    id_mismatch_dir.mkdir()
    _write_bound_active_selection(id_mismatch_dir)
    id_ledger_path = id_mismatch_dir / LEDGER_FILE
    id_ledger = json.loads(id_ledger_path.read_text(encoding="utf-8"))
    id_ledger["tournament_id"] = "paper-tournament-forged"
    id_ledger_path.write_text(json.dumps(id_ledger), encoding="utf-8")

    expiry_mismatch_dir = tmp_path / "ledger_expiry_mismatch"
    expiry_mismatch_dir.mkdir()
    _write_bound_active_selection(expiry_mismatch_dir)
    expiry_ledger_path = expiry_mismatch_dir / LEDGER_FILE
    expiry_ledger = json.loads(expiry_ledger_path.read_text(encoding="utf-8"))
    expiry_ledger["ends_at"] = "2026-07-03T18:00:00+00:00"
    expiry_ledger_path.write_text(json.dumps(expiry_ledger), encoding="utf-8")

    before_expiry = datetime.datetime(2026, 6, 6, 20, 10, tzinfo=datetime.timezone.utc)
    assert load_live_strategy_selection(id_mismatch_dir, now=before_expiry) is None
    assert load_live_strategy_selection(expiry_mismatch_dir, now=before_expiry) is None


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


def test_supervisor_ignores_top_level_mismatched_live_strategy_selection(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    live_client = _FakePaperClient()
    live_client.paper = False
    live_client.positions = []
    tournament_dir = tmp_path / "tournament"
    tournament_dir.mkdir()
    _write_bound_active_selection(tournament_dir)
    selection_path = tournament_dir / "live-strategy-selection.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection["strategy_id"] = STRATEGY_CURRENT_AGGRESSIVE
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    monkeypatch.setattr(
        paper_tournament,
        "_now",
        lambda: datetime.datetime(2026, 6, 6, 20, 10, tzinfo=datetime.timezone.utc),
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
    assert "live_strategy_selection" not in payload["evidence"]
    assert payload["evidence"]["live_sleeve_resolution"]["signals_adapted"] is False


def test_supervisor_ignores_expired_live_strategy_selection(monkeypatch, tmp_path):
    paper_client = _FakePaperClient()
    live_client = _FakePaperClient()
    live_client.paper = False
    live_client.positions = []
    tournament_dir = tmp_path / "tournament"
    tournament_dir.mkdir()
    _write_bound_active_selection(tournament_dir)
    monkeypatch.setattr(
        paper_tournament,
        "_now",
        lambda: datetime.datetime(2026, 7, 2, 18, 0, tzinfo=datetime.timezone.utc),
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
    assert "live_strategy_selection" not in payload["evidence"]
    assert payload["evidence"]["live_sleeve_resolution"]["signals_adapted"] is False


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
    _write_bound_active_selection(tournament_dir)
    monkeypatch.setattr(
        paper_tournament,
        "_now",
        lambda: datetime.datetime(2026, 6, 6, 20, 10, tzinfo=datetime.timezone.utc),
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
