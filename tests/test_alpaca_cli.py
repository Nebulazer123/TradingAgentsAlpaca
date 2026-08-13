import datetime
import inspect
import json
import sys
import threading
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from cli import main as cli_main
from cli.main import app
from tradingagents.brokers.alpaca import AlpacaExecutionConfig
from tradingagents.brokers.supervisor import daily_report as supervisor_daily_report
from tradingagents.policy.risk_envelope import load_risk_envelope
from tradingagents.research.crawler_runner import CrawlerRuntimeStatus

_AGENT_LEDGER_FLAGS = {
    "--agent-ledger-path",
    "--write-agent-ledger",
    "--no-agent-ledger",
}
_TOP_PROVIDER_BUNDLE_FLAGS = {
    "--top-provider-bundle-count",
    "--top-provider-bundle-output-dir",
    "--top-provider-bundle-cache-dir",
}


class _HermeticCliRunner(CliRunner):
    def invoke(self, app, args=None, *positional, **kwargs):
        patched_args = list(args) if isinstance(args, (tuple, list)) else args
        if (
            isinstance(patched_args, list)
            and patched_args[:2] == ["alpaca", "plan-overnight"]
            and not any(str(arg).split("=", 1)[0] in _AGENT_LEDGER_FLAGS for arg in patched_args)
        ):
            patched_args.append("--no-agent-ledger")
        if (
            isinstance(patched_args, list)
            and patched_args[:2] == ["alpaca", "plan-overnight"]
            and not any(str(arg).split("=", 1)[0] in _TOP_PROVIDER_BUNDLE_FLAGS for arg in patched_args)
        ):
            patched_args.extend(["--top-provider-bundle-count", "0"])
        return super().invoke(app, patched_args, *positional, **kwargs)


runner = _HermeticCliRunner()

PREMARKET_FRESH_VALIDATION_ITEMS = [
    "premarket quotes and spreads",
    "overnight and morning news/social deltas",
    "open live and paper orders",
    "current positions and P/L",
    "live sizing room and buying power",
]


def _order_for_reconciliation(symbol: str, client_order_id: str) -> dict:
    return {
        "client_order_id": client_order_id,
        "symbol": symbol,
        "side": "buy",
        "type": "limit",
        "qty": "1",
        "limit_price": "10.00",
        "status": "accepted",
    }


def _premarket_instructions(symbol: str = "ORCL") -> dict:
    return {
        "summary": "Validate fresh state before any live action.",
        "top_symbol": symbol,
        "latest_research_context": {
            "packet_count": 13,
            "blocked_count": 0,
            "execution_authority": "none",
        },
        "must_validate_fresh": list(PREMARKET_FRESH_VALIDATION_ITEMS),
    }


def _write_verify_premarket_fixture(brief_dir: Path, brief_packet: dict) -> None:
    raw_path = brief_dir / "premarket-brief-20260601-010500.json"
    raw_text = json.dumps(brief_packet)
    raw_path.write_text(raw_text, encoding="utf-8")
    (brief_dir / "latest.json").write_text(raw_text, encoding="utf-8")
    compact = {
        "schema": "compact_premarket_brief_v1",
        "analysis_only": True,
        "raw_packet_path": str(raw_path),
        "generated_at": brief_packet.get("generated_at"),
        "execution_authority": "none",
        "premarket_instructions": dict(brief_packet.get("premarket_instructions") or {}),
    }
    (brief_dir / "latest-compact.json").write_text(json.dumps(compact), encoding="utf-8")


def test_latest_json_packet_path_prefers_newer_generated_at_raw_over_stale_latest(tmp_path):
    latest_packet = {
        "generated_at": "2026-06-01T01:00:00+00:00",
        "latest_alias_written": True,
        "ranked_candidates": [{"symbol": "OLD"}],
    }
    raw_path = tmp_path / "overnight-plan-20260602-010000.json"
    raw_packet = {
        "generated_at": "2026-06-02T01:00:00+00:00",
        "latest_alias_written": True,
        "ranked_candidates": [{"symbol": "NEW"}],
    }
    (tmp_path / "latest.json").write_text(json.dumps(latest_packet), encoding="utf-8")
    raw_path.write_text(json.dumps(raw_packet), encoding="utf-8")

    assert cli_main._latest_json_packet_path(tmp_path, "overnight-plan-*.json") == raw_path


def test_latest_json_packet_path_skips_no_latest_probe_raw(tmp_path):
    latest_packet = {
        "generated_at": "2026-06-01T01:00:00+00:00",
        "latest_alias_written": True,
        "ranked_candidates": [{"symbol": "PRODUCTION"}],
    }
    probe_path = tmp_path / "overnight-plan-20260602-010000.json"
    probe_packet = {
        "generated_at": "2026-06-02T01:00:00+00:00",
        "latest_alias_written": False,
        "ranked_candidates": [{"symbol": "PROBE"}],
    }
    (tmp_path / "latest.json").write_text(json.dumps(latest_packet), encoding="utf-8")
    probe_path.write_text(json.dumps(probe_packet), encoding="utf-8")

    assert cli_main._latest_json_packet_path(tmp_path, "overnight-plan-*.json") == tmp_path / "latest.json"


def _write_compact_preopen_validation(
    validation_dir: Path,
    *,
    overall_status: str = "pass",
    market_session: str = "pre_open",
    generated_at: str = "2026-06-01T12:00:00+00:00",
    failed_check_ids: list[str] | None = None,
    warned_check_ids: list[str] | None = None,
    skipped_check_ids: list[str] | None = None,
) -> None:
    validation_dir.mkdir(parents=True, exist_ok=True)
    raw_path = validation_dir / "preopen-validation-test.json"
    packet = {
        "schema": "compact_preopen_validation_v1",
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "raw_packet_path": str(raw_path),
        "generated_at": generated_at,
        "overall_status": overall_status,
        "market_session": market_session,
        "failed_check_ids": failed_check_ids or [],
        "warned_check_ids": warned_check_ids or [],
        "skipped_check_ids": skipped_check_ids or [],
    }
    raw_path.write_text(json.dumps(packet), encoding="utf-8")
    (validation_dir / "latest-compact.json").write_text(json.dumps(packet), encoding="utf-8")


def _write_test_risk_envelope(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "account_max_capital_at_risk_usd: 250.00",
                "per_name_cap_usd: 50.00",
                "per_sector_cap_pct: 0.35",
                "aggregate_beta_cap: 1.20",
                "daily_loss_halt_usd: 25.00",
                "max_drawdown_halt_pct: 0.10",
                "tiny_live_tranche_usd: 25.00",
                "tiny_live_max_loss_usd: 5.00",
                "new_sleeve_auto_promote: false",
                "alert_email: test@example.com",
                "live_budget_mode: autonomous_with_caps",
            ]
        ),
        encoding="utf-8",
    )


def _write_test_live_control(path: Path, expires_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "frozen": False,
                "reason": "test",
                "dead_man_expires_at": expires_at,
                "updated_at": "2026-06-01T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )


def test_simulated_preopen_validation_skip_is_saturday_only():
    saturday_afternoon = datetime.datetime(2026, 6, 6, 19, 8, tzinfo=datetime.timezone.utc)
    sunday_overnight = datetime.datetime(2026, 6, 7, 7, 30, tzinfo=datetime.timezone.utc)

    assert (
        cli_main._skip_simulated_preopen_validation_for_calendar(saturday_afternoon)
        == "saturday_no_regular_market_morning"
    )
    assert cli_main._skip_simulated_preopen_validation_for_calendar(sunday_overnight) is None


def test_alpaca_preview_prints_paper_and_live_orders_without_submit():
    result = runner.invoke(
        app,
        [
            "alpaca",
            "preview",
            "--run-id",
            "20260526-preopen",
            "--third-symbol",
            "MSFT",
            "--third-limit-price",
            "500",
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload["accepted"]) == 3
    first = payload["accepted"][0]
    assert first["paper"]["notional"] == "450.00"
    assert first["live"]["notional"] == "45.00"
    assert "paper-googl-starter" in first["paper"]["client_order_id"]
    assert "live-googl-starter" in first["live"]["client_order_id"]


def test_fetch_aggressive_candidate_market_data_marks_daily_bars_stale_during_tradeable_session(
    monkeypatch,
):
    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame(
        {
            "Close": [100.0, 99.0],
            "Volume": [1000.0, 1200.0],
        }
    )

    def fake_download(*args, **kwargs):
        if kwargs.get("interval") == "5m":
            raise RuntimeError("intraday unavailable")
        return frame

    fake_yfinance = SimpleNamespace(download=fake_download)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(cli_main, "_fetch_alpaca_latest_trade_rows", lambda symbols, *, now_utc: {})

    market_data = cli_main._fetch_aggressive_candidate_market_data()

    assert market_data
    sample = next(iter(market_data.values()))
    assert sample["quote_fresh"] is False
    assert sample["stale_quote"] is True
    assert sample["quote_session_label"] == "regular"
    assert "not a fresh intraday quote" in sample["quote_stale_reason"]


def test_fetch_aggressive_candidate_market_data_uses_fresh_intraday_bar_during_tradeable_session(
    monkeypatch,
):
    pd = pytest.importorskip("pandas")
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    daily = pd.DataFrame(
        {
            "Close": [100.0, 98.0],
            "Volume": [1000.0, 1200.0],
        },
        index=[
            now - datetime.timedelta(days=2),
            now - datetime.timedelta(days=1),
        ],
    )
    intraday = pd.DataFrame(
        {
            "Close": [97.25, 97.50],
            "Volume": [300.0, 450.0],
        },
        index=[
            now - datetime.timedelta(minutes=10),
            now - datetime.timedelta(minutes=5),
        ],
    )

    def fake_download(*args, **kwargs):
        return intraday if kwargs.get("interval") == "5m" else daily

    fake_yfinance = SimpleNamespace(download=fake_download)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(cli_main, "_fetch_alpaca_latest_trade_rows", lambda symbols, *, now_utc: {})

    market_data = cli_main._fetch_aggressive_candidate_market_data()

    assert market_data
    sample = next(iter(market_data.values()))
    assert sample["current_price"] == Decimal("97.5")
    assert sample["quote_fresh"] is True
    assert sample["stale_quote"] is False
    assert sample["bar_interval"] == "5m"
    assert sample["source"] == "yfinance:1d-5m-prepost"
    assert sample["quote_stale_reason"] is None


def test_fetch_aggressive_candidate_market_data_prefers_fresh_alpaca_latest_trade(
    monkeypatch,
):
    pd = pytest.importorskip("pandas")
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    daily = pd.DataFrame(
        {"Close": [100.0, 98.0], "Volume": [1000.0, 1200.0]},
        index=[now - datetime.timedelta(days=2), now - datetime.timedelta(days=1)],
    )
    intraday = pd.DataFrame(
        {"Close": [97.25, 97.50], "Volume": [300.0, 450.0]},
        index=[now - datetime.timedelta(minutes=10), now - datetime.timedelta(minutes=5)],
    )

    fake_yfinance = SimpleNamespace(
        download=lambda *args, **kwargs: intraday if kwargs.get("interval") == "5m" else daily
    )

    def fake_alpaca_rows(symbols, *, now_utc):
        timestamp = now_utc - datetime.timedelta(minutes=2)
        return {
            symbol.upper(): {
                "current_price": Decimal("101.25"),
                "quote_timestamp": timestamp,
                "quote_fresh": True,
                "stale_quote": False,
                "quote_stale_reason": None,
                "source": "alpaca_market_data:latest_trade",
                "bar_interval": "latest_trade",
            }
            for symbol in symbols
        }

    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(cli_main, "_fetch_alpaca_latest_trade_rows", fake_alpaca_rows)

    market_data = cli_main._fetch_aggressive_candidate_market_data()

    assert market_data
    sample = next(iter(market_data.values()))
    assert sample["current_price"] == Decimal("101.25")
    assert sample["quote_fresh"] is True
    assert sample["stale_quote"] is False
    assert sample["bar_interval"] == "latest_trade"
    assert sample["source"] == "alpaca_market_data:latest_trade"


def test_fetch_aggressive_candidate_market_data_falls_back_when_alpaca_latest_trade_is_stale(
    monkeypatch,
):
    pd = pytest.importorskip("pandas")
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    daily = pd.DataFrame(
        {"Close": [100.0, 98.0], "Volume": [1000.0, 1200.0]},
        index=[now - datetime.timedelta(days=2), now - datetime.timedelta(days=1)],
    )
    intraday = pd.DataFrame(
        {"Close": [97.25, 97.50], "Volume": [300.0, 450.0]},
        index=[now - datetime.timedelta(minutes=10), now - datetime.timedelta(minutes=5)],
    )

    fake_yfinance = SimpleNamespace(
        download=lambda *args, **kwargs: intraday if kwargs.get("interval") == "5m" else daily
    )

    def fake_alpaca_rows(symbols, *, now_utc):
        timestamp = now_utc - datetime.timedelta(hours=2)
        return {
            symbol.upper(): {
                "current_price": Decimal("90.00"),
                "quote_timestamp": timestamp,
                "quote_fresh": False,
                "stale_quote": True,
                "quote_stale_reason": "latest Alpaca latest trade quote is stale",
                "source": "alpaca_market_data:latest_trade",
                "bar_interval": "latest_trade",
            }
            for symbol in symbols
        }

    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(cli_main, "_fetch_alpaca_latest_trade_rows", fake_alpaca_rows)

    market_data = cli_main._fetch_aggressive_candidate_market_data()

    assert market_data
    sample = next(iter(market_data.values()))
    assert sample["current_price"] == Decimal("97.5")
    assert sample["quote_fresh"] is True
    assert sample["stale_quote"] is False
    assert sample["bar_interval"] == "5m"
    assert sample["source"] == "yfinance:1d-5m-prepost"


def test_alpaca_reconcile_orcl_incident_writes_read_only_packet(monkeypatch, tmp_path):
    packet_path = tmp_path / "hourly-orcl.json"
    packet_path.write_text(
        json.dumps(
            {
                "submitted": [
                    {
                        "client_order_id": "ta-tiny-old-orcl-sell",
                        "symbol": "ORCL",
                        "side": "sell",
                        "status": "filled",
                        "filled_qty": "0.41",
                        "filled_avg_price": "233.37",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class _LiveReadOnlyClient:
        def __init__(self):
            self.submitted = []
            self.positions = [
                {
                    "symbol": "ORCL",
                    "qty": "0",
                    "market_value": "0",
                    "avg_entry_price": "0",
                }
            ]

        def list_orders(self, status="open"):
            return [
                {
                    "client_order_id": "ta-tiny-old-orcl-sell",
                    "symbol": "ORCL",
                    "side": "sell",
                    "status": "filled",
                    "filled_qty": "0.41",
                    "filled_avg_price": "233.37",
                    "submitted_at": "2026-06-02T18:00:00+00:00",
                }
            ]

    live_client = _LiveReadOnlyClient()
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: live_client)

    result = runner.invoke(
        app,
        [
            "alpaca",
            "reconcile-orcl-incident",
            str(packet_path),
            "--output-dir",
            str(tmp_path / "orcl"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["can_submit_orders"] is False
    assert payload["read_only"] is True
    assert payload["execution_authority"] == "none"
    assert payload["broker_write_calls"] == 0
    assert payload["final_old_sell_state"] == "filled"
    assert payload["old_sell_orders"][0]["client_order_id"] == "ta-tiny-old-orcl-sell"
    assert live_client.submitted == []
    assert (tmp_path / "orcl" / "latest.json").exists()


def test_alpaca_reconcile_symbol_incident_writes_generic_zero_write_packet(monkeypatch, tmp_path):
    packet_path = tmp_path / "nflx.json"
    packet_path.write_text(
        json.dumps(
            {
                "actions": [
                    {
                        "symbol": "NFLX",
                        "side": "buy",
                        "account": "live",
                        "idempotency_key": "ta-tiny-nflx-1",
                    }
                ],
                "submitted": [
                    {
                        "client_order_id": "ta-tiny-nflx-1",
                        "symbol": "NFLX",
                        "side": "buy",
                        "type": "limit",
                        "qty": "1",
                        "limit_price": "10.00",
                        "status": "accepted",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class _ReadOnlyClient:
        def __init__(self):
            self.write_calls = []

        def list_positions(self):
            return [{"symbol": "NFLX", "qty": "1"}]

        def list_orders(self, status="all"):
            return [
                {
                    "client_order_id": "ta-tiny-nflx-1",
                    "symbol": "NFLX",
                    "side": "buy",
                    "type": "limit",
                    "qty": "1",
                    "limit_price": "10.00",
                    "status": "accepted",
                }
            ]

        def get_order_by_client_order_id(self, client_order_id):
            return self.list_orders()[0] if client_order_id == "ta-tiny-nflx-1" else None

        def submit_order(self, *args, **kwargs):
            self.write_calls.append(("submit", args, kwargs))
            raise AssertionError("reconciliation attempted a broker write")

    live_client = _ReadOnlyClient()
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: live_client)

    result = runner.invoke(
        app,
        [
            "alpaca",
            "reconcile-symbol-incident",
            "--symbol",
            "NFLX",
            "--packet-path",
            str(packet_path),
            "--expected-qty",
            "1",
            "--output-dir",
            str(tmp_path / "reconciliation"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["kind"] == "symbol_broker_reconciliation"
    assert payload["symbol"] == "NFLX"
    assert payload["read_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["execution_authority"] == "none"
    assert payload["broker_write_calls"] == 0
    assert payload["matched"] is True
    assert live_client.write_calls == []
    assert (tmp_path / "reconciliation" / "latest.json").exists()


def test_alpaca_reconcile_symbol_incident_forwards_exact_owner_attribution(monkeypatch, tmp_path):
    attribution = tmp_path / "owner.json"
    attribution.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_reconcile(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            symbol="NFLX", matched=False,
            position={"symbol": "NFLX", "qty": "0"}, open_orders=[],
            recent_fills=[], checked_client_order_ids=[], issues=["still frozen"],
            resolved_external_actions=[], replay_suppressions=[],
            read_only=True, broker_write_calls=0,
        )

    monkeypatch.setattr(cli_main, "reconcile_symbol_incident", fake_reconcile)
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: object())
    monkeypatch.setattr(cli_main, "asdict", lambda value: vars(value))
    result = runner.invoke(
        app,
        [
            "alpaca", "reconcile-symbol-incident", "--symbol", "NFLX",
            "--owner-action-attestation", str(attribution),
            "--output-dir", str(tmp_path / "out"), "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["owner_action_attestation_paths"] == [attribution]


def test_record_owner_manual_action_is_local_immutable_and_never_builds_broker(
    monkeypatch, tmp_path
):
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps({
            "actions": [{"idempotency_key": "autonomous-buy", "symbol": "NFLX"}],
            "submitted": [{"client_order_id": "autonomous-buy", "symbol": "NFLX"}],
        }),
        encoding="utf-8",
    )
    buy = {
        "client_order_id": "autonomous-buy", "symbol": "NFLX", "side": "buy",
        "status": "filled", "filled_qty": "1", "filled_avg_price": "10",
        "submitted_at": "2026-06-02T20:29:44+00:00",
        "updated_at": "2026-06-02T20:29:45+00:00",
    }
    sell = {
        "client_order_id": "owner-sell", "symbol": "NFLX", "side": "sell",
        "status": "filled", "filled_qty": "1", "filled_avg_price": "9.5",
        "submitted_at": "2026-07-27T18:46:48+00:00",
        "updated_at": "2026-07-27T18:46:49+00:00",
    }
    reconciliation = tmp_path / "reconciliation.json"
    reconciliation.write_text(
        json.dumps({"symbol": "NFLX", "recent_fills": [sell, buy]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_live_client",
        lambda: (_ for _ in ()).throw(AssertionError("must not construct broker")),
    )
    output = tmp_path / "owner-action.json"
    args = [
        "alpaca", "record-owner-manual-action",
        "--source-packet", str(source),
        "--reconciliation-packet", str(reconciliation),
        "--originating-client-order-id", "autonomous-buy",
        "--manual-fill-client-order-id", "owner-sell",
        "--attested-at", "2026-08-13T09:10:00+00:00",
        "--output", str(output), "--json-output",
    ]
    first = runner.invoke(app, args)
    second = runner.invoke(app, args)

    assert first.exit_code == 0, first.output
    payload = json.loads(first.stdout)
    assert payload["schema_version"] == "tradingagents.owner_manual_broker_action.v1"
    assert payload["can_submit_orders"] is False
    assert output.exists()
    assert second.exit_code != 0


def test_alpaca_reconcile_symbol_incident_invalid_expected_quantity_writes_fail_closed_packet(
    monkeypatch, tmp_path
):
    class _NoReadClient:
        def __init__(self):
            self.read_calls = []
            self.write_calls = []

        def list_positions(self):
            self.read_calls.append("list_positions")
            raise AssertionError("invalid expected quantity must prevent broker reads")

        def submit_order(self, *args, **kwargs):
            self.write_calls.append(("submit", args, kwargs))
            raise AssertionError("reconciliation attempted a broker write")

        def cancel_order(self, *args, **kwargs):
            self.write_calls.append(("cancel", args, kwargs))
            raise AssertionError("reconciliation attempted a broker write")

        def replace_order(self, *args, **kwargs):
            self.write_calls.append(("replace", args, kwargs))
            raise AssertionError("reconciliation attempted a broker write")

        def close_position(self, *args, **kwargs):
            self.write_calls.append(("close", args, kwargs))
            raise AssertionError("reconciliation attempted a broker write")

    live_client = _NoReadClient()
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: live_client)

    result = runner.invoke(
        app,
        [
            "alpaca",
            "reconcile-symbol-incident",
            "--symbol",
            "NFLX",
            "--expected-qty",
            "NaN",
            "--output-dir",
            str(tmp_path / "reconciliation"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["matched"] is False
    assert payload["issues"] == ["invalid expected quantity: NaN"]
    assert payload["broker_write_calls"] == 0
    assert live_client.read_calls == []
    assert live_client.write_calls == []


def test_alpaca_reconcile_symbol_incident_uses_unique_atomic_packet_paths(monkeypatch, tmp_path):
    packet_path = tmp_path / "nflx.json"
    packet_path.write_text(
        json.dumps(
            {
                "actions": [{"symbol": "NFLX", "account": "live", "idempotency_key": "nflx-1"}],
                "submitted": [_order_for_reconciliation("NFLX", "nflx-1")],
            }
        ),
        encoding="utf-8",
    )

    class _Client:
        def list_positions(self):
            return [{"symbol": "NFLX", "qty": "1"}]

        def list_orders(self, status="all"):
            return [_order_for_reconciliation("NFLX", "nflx-1")]

        def get_order_by_client_order_id(self, _client_order_id):
            return _order_for_reconciliation("NFLX", "nflx-1")

    class _FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 1, 12, 0, tzinfo=tz)

    monkeypatch.setattr(cli_main, "_alpaca_live_client", _Client)
    monkeypatch.setattr(cli_main.datetime, "datetime", _FixedDateTime)
    output_dir = tmp_path / "reconciliation"
    args = [
        "alpaca",
        "reconcile-symbol-incident",
        "--symbol",
        "NFLX",
        "--packet-path",
        str(packet_path),
        "--expected-qty",
        "1",
        "--output-dir",
        str(output_dir),
        "--json-output",
    ]

    first = runner.invoke(app, args)
    second = runner.invoke(app, args)

    assert first.exit_code == second.exit_code == 0
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first_payload["json_path"] != second_payload["json_path"]
    assert Path(first_payload["json_path"]).read_text(encoding="utf-8").endswith("\n")
    assert json.loads((output_dir / "latest.json").read_text(encoding="utf-8")) == second_payload


def test_reconciliation_packet_atomic_write_failure_leaves_complete_files(monkeypatch, tmp_path):
    output_dir = tmp_path / "reconciliation"
    output_dir.mkdir()
    latest_path = output_dir / "latest.json"
    latest_path.write_text('{"previous": true}\n', encoding="utf-8")
    original_writer = cli_main._atomic_write_text

    def fail_latest(path, text, **kwargs):
        if Path(path) == latest_path:
            raise OSError("injected latest write failure")
        return original_writer(path, text, **kwargs)

    monkeypatch.setattr(cli_main, "_atomic_write_text", fail_latest)
    with pytest.raises(OSError, match="injected latest write failure"):
        cli_main._write_reconciliation_packet(
            output_dir,
            stem="symbol-reconciliation-test",
            packet={"kind": "symbol_broker_reconciliation"},
        )

    immutable_paths = list(output_dir.glob("symbol-reconciliation-test*.json"))
    assert len(immutable_paths) == 1
    assert immutable_paths[0].read_text(encoding="utf-8").endswith("\n")
    assert json.loads(immutable_paths[0].read_text(encoding="utf-8"))["kind"] == (
        "symbol_broker_reconciliation"
    )
    assert latest_path.read_text(encoding="utf-8") == '{"previous": true}\n'


def test_reconciliation_packet_target_write_failure_leaves_no_truncated_packet(monkeypatch, tmp_path):
    output_dir = tmp_path / "reconciliation"
    output_dir.mkdir()
    latest_path = output_dir / "latest.json"
    latest_path.write_text('{"previous": true}\n', encoding="utf-8")

    def fail_target(path, text, **kwargs):
        raise OSError("injected target write failure")

    monkeypatch.setattr(cli_main, "_atomic_write_text", fail_target)
    with pytest.raises(OSError, match="injected target write failure"):
        cli_main._write_reconciliation_packet(
            output_dir,
            stem="symbol-reconciliation-target-failure",
            packet={"kind": "symbol_broker_reconciliation"},
        )

    assert list(output_dir.glob("symbol-reconciliation-target-failure*.json")) == []
    assert latest_path.read_text(encoding="utf-8") == '{"previous": true}\n'


def test_reconciliation_packet_concurrent_same_stem_preserves_two_immutable_packets(
    monkeypatch, tmp_path
):
    output_dir = tmp_path / "reconciliation"
    barrier = threading.Barrier(2)
    errors = []
    paths = []

    def force_same_initial_candidate(output_dir_arg, stem, suffix=".json"):
        barrier.wait(timeout=3)
        return Path(output_dir_arg) / f"{stem}{suffix}"

    monkeypatch.setattr(cli_main, "_unique_packet_path", force_same_initial_candidate)

    def write_packet(run_id):
        try:
            path, _text = cli_main._write_reconciliation_packet(
                output_dir,
                stem="race",
                packet={"kind": "symbol_broker_reconciliation", "run_id": run_id},
            )
            paths.append(path)
        except Exception as exc:  # pragma: no cover - asserted below.
            errors.append(exc)

    writers = [threading.Thread(target=write_packet, args=(run_id,)) for run_id in ("a", "b")]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(timeout=5)

    assert errors == []
    assert len(paths) == 2
    assert paths[0] != paths[1]
    immutable_packets = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    assert {packet["run_id"] for packet in immutable_packets} == {"a", "b"}
    assert all(path.read_text(encoding="utf-8").endswith("\n") for path in paths)
    latest = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] in {"a", "b"}


def test_alpaca_reconcile_orcl_incident_discovers_symbol_sell_packet(monkeypatch, tmp_path):
    hourly_dir = tmp_path / "hourly"
    hourly_dir.mkdir()
    (hourly_dir / "latest.json").write_text(
        json.dumps({"submitted": [{"symbol": "MSFT", "side": "buy"}]}),
        encoding="utf-8",
    )
    (hourly_dir / "hourly-supervisor-20260603-130000.json").write_text(
        json.dumps(
            {
                "submitted": [
                    {
                        "live_order": {
                            "client_order_id": "ta-tiny-old-orcl-sell",
                            "symbol": "ORCL",
                            "side": "sell",
                            "status": "filled",
                            "filled_qty": "0.41",
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class _LiveReadOnlyClient:
        def list_positions(self):
            return []

        def list_orders(self, status="open"):
            return []

    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: _LiveReadOnlyClient())

    result = runner.invoke(
        app,
        [
            "alpaca",
            "reconcile-orcl-incident",
            "--hourly-log-dir",
            str(hourly_dir),
            "--output-dir",
            str(tmp_path / "orcl"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["order_packet_paths"] == [
        str(hourly_dir / "hourly-supervisor-20260603-130000.json")
    ]
    assert payload["packet_discovery_issues"] == []
    assert payload["packet_read_issues"] == []
    assert payload["old_sell_orders"][0]["client_order_id"] == "ta-tiny-old-orcl-sell"


def test_alpaca_reconcile_orcl_incident_reports_bad_default_packets(monkeypatch, tmp_path):
    hourly_dir = tmp_path / "hourly"
    hourly_dir.mkdir()
    (hourly_dir / "latest.json").write_text("{not-json", encoding="utf-8")

    class _LiveReadOnlyClient:
        def list_positions(self):
            return []

        def list_orders(self, status="open"):
            return []

    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: _LiveReadOnlyClient())

    result = runner.invoke(
        app,
        [
            "alpaca",
            "reconcile-orcl-incident",
            "--hourly-log-dir",
            str(hourly_dir),
            "--output-dir",
            str(tmp_path / "orcl"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["order_packet_paths"] == []
    assert payload["packet_discovery_issues"]
    assert payload["packet_discovery_issues"][0]["issue"] == "invalid_or_unreadable_json"
    assert payload["packet_discovery_issues"][-1]["issue"] == "no_valid_hourly_packets_found"


def test_alpaca_submit_refuses_when_execution_flags_are_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "paper-secret")
    monkeypatch.setenv("ALPACA_LIVE_API_KEY", "live-key")
    monkeypatch.setenv("ALPACA_LIVE_SECRET_KEY", "live-secret")
    monkeypatch.delenv("TRADINGAGENTS_ALPACA_PAPER_ENABLED", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_ALPACA_LIVE_MIRROR_ENABLED", raising=False)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_execution_config",
        lambda: AlpacaExecutionConfig(
            paper_enabled=False,
            live_mirror_enabled=False,
        ),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "submit",
            "--run-id",
            "20260526-preopen",
            "--third-symbol",
            "MSFT",
            "--third-limit-price",
            "500",
            "--log-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert "authorized normal live intent" in result.stdout.lower()
    packet = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert packet["status"] == "refused"
    assert packet["account_scope"] == ["live"]


def test_ticket_orders_auto_adds_ranked_third_candidate(monkeypatch):
    monkeypatch.setattr(cli_main, "_rank_third_candidate", lambda: ("MSFT", Decimal("500")))

    orders = cli_main._ticket_orders(
        premarket=True,
        third_symbol=None,
        third_limit_price=None,
    )

    assert [order.symbol for order in orders] == ["GOOGL", "NVDA", "MSFT"]
    assert orders[-1].notional == Decimal("300")
    assert orders[-1].limit_price == Decimal("500")


def test_default_overnight_trade_date_uses_next_weekday_for_weekends():
    assert cli_main._default_overnight_trade_date(
        datetime.datetime(2026, 5, 31, 20, 0, tzinfo=datetime.timezone.utc),
    ) == "2026-06-01"
    assert cli_main._default_overnight_trade_date(
        datetime.datetime(2026, 6, 6, 20, 0, tzinfo=datetime.timezone.utc),
    ) == "2026-06-08"
    assert cli_main._default_overnight_trade_date(
        datetime.datetime(2026, 6, 1, 20, 0, tzinfo=datetime.timezone.utc),
    ) == "2026-06-01"


def test_extract_cli_option_value_cleans_markdown_command_punctuation():
    command_text = (
        "`tradingagents alpaca plan-overnight "
        "--overnight-graph-profile compact "
        "--overnight-max-completion-tokens 220`."
    )

    assert cli_main._extract_cli_option_value(command_text, "--overnight-graph-profile") == "compact"
    assert cli_main._extract_cli_option_value(command_text, "--overnight-max-completion-tokens") == "220"


def test_parse_overnight_automation_contract_handles_toml_escaped_prompt_newlines(tmp_path):
    automation_dir = tmp_path
    folder = automation_dir / "tradingagents-overnight-planning"
    folder.mkdir()
    (folder / "automation.toml").write_text(
        'prompt = "Run `tradingagents alpaca plan-overnight '
        '--overnight-graph-profile compact '
        '--full-graph-tickers 3 '
        '--per-ticker-timeout-minutes 25 '
        '--time-budget-minutes 90 '
        '--overnight-max-completion-tokens 220`.\\n3. Next step"\n',
        encoding="utf-8",
    )

    contract = cli_main._parse_overnight_automation_contract(automation_dir)

    assert contract["graph_profile"] == "compact"
    assert contract["full_graph_limit"] == 3
    assert contract["per_ticker_timeout_minutes"] == 25
    assert contract["time_budget_minutes"] == 90
    assert contract["max_completion_tokens"] == 220


def test_overnight_worker_wait_reads_result_before_process_exit():
    class _FakeProcess:
        exitcode = None

        def __init__(self):
            self.alive = True
            self.terminated = False

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            self.alive = False

        def terminate(self):
            self.terminated = True
            self.alive = False

    class _FakeQueue:
        def get(self, timeout=None):
            return {
                "ok": True,
                "result": {"symbol": "ADBE", "status": "ok", "rating": "Buy"},
            }

    process = _FakeProcess()

    result = cli_main._wait_for_overnight_worker_result(
        symbol="ADBE",
        process=process,
        queue=_FakeQueue(),
        timeout_seconds=5,
    )

    assert result["status"] == "ok"
    assert result["rating"] == "Buy"
    assert process.terminated is False


def test_overnight_worker_wait_times_out_live_process():
    class _FakeProcess:
        exitcode = None

        def __init__(self):
            self.terminated = False

        def is_alive(self):
            return not self.terminated

        def join(self, timeout=None):
            return None

        def terminate(self):
            self.terminated = True

    class _EmptyQueue:
        def get(self, timeout=None):
            raise cli_main.queue_module.Empty()

    process = _FakeProcess()

    result = cli_main._wait_for_overnight_worker_result(
        symbol="ADBE",
        process=process,
        queue=_EmptyQueue(),
        timeout_seconds=0.01,
    )

    assert result["status"] == "failed"
    assert "Timed out" in result["error"]
    assert process.terminated is True


def test_overnight_timeout_terminates_windows_process_tree(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_main.os, "name", "nt")
    monkeypatch.setattr(
        cli_main.subprocess,
        "run",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )

    class _FakeProcess:
        pid = 1234

        def __init__(self):
            self.alive = True
            self.terminated = False

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.terminated = True
            self.alive = False

        def join(self, timeout=None):
            return None

    process = _FakeProcess()

    cli_main._terminate_overnight_process_tree(process)

    assert calls[0][0] == ["taskkill", "/PID", "1234", "/T", "/F"]
    assert process.terminated is True


class _FakeCliClient:
    def __init__(self, paper):
        self.paper = paper
        self.submitted = []
        self.account_equity = "200"
        self.positions = [
            {
                "symbol": "GOOGL",
                "qty": "0.117",
                "avg_entry_price": "383.50",
                "market_value": "45.30",
                "cost_basis": "45",
                "unrealized_pl": "0.30",
                "unrealized_plpc": "0.006",
                "current_price": "386",
            }
        ]

    def assert_expected_mode(self, paper):
        assert self.paper is paper

    def list_open_client_order_ids(self):
        return set()

    def submit_order(self, order):
        self.submitted.append(order)
        return {"id": f"{'paper' if self.paper else 'live'}-id"}

    def get_account(self):
        return {
            "status": "ACTIVE",
            "buying_power": "100",
            "equity": self.account_equity,
            "portfolio_value": self.account_equity,
        }

    def list_orders(self, status="open"):
        return []

    def list_positions(self):
        return self.positions

    def get_asset(self, symbol):
        return {
            "symbol": symbol.upper(),
            "tradable": True,
            "class": "us_equity",
            "status": "active",
        }

    def get_clock(self):
        return {
            "timestamp": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds"),
            "is_open": True,
        }


def test_retired_live_budget_mode_is_reported_as_invalid(tmp_path):
    envelope_path = tmp_path / "risk_envelope.yaml"
    envelope_path.write_text(
        "\n".join(
            [
                "account_max_capital_at_risk_usd: 250.00",
                "per_name_cap_usd: 50.00",
                "per_sector_cap_pct: 0.20",
                "aggregate_beta_cap: 1.25",
                "daily_loss_halt_usd: 25.00",
                "max_drawdown_halt_pct: 0.05",
                "tiny_live_tranche_usd: 25.00",
                "tiny_live_max_loss_usd: 5.00",
                "new_sleeve_auto_promote: false",
                "alert_email: nebulazer2003@gmail.com",
                "live_budget_mode: autonomous_uncapped",
            ]
        ),
        encoding="utf-8",
    )

    dynamic_cap, mode, issues, _ = cli_main._dynamic_live_cap_for_budget_mode(
        live_account={"buying_power": "152.44"},
        live_positions=[{"symbol": "TSM", "cost_basis": "45.00"}],
        recent_packets=[{"issues": [{"reason": "old cap packet"}]}],
        config=AlpacaExecutionConfig(live_exposure_limit=Decimal("100")),
        risk_envelope_path=envelope_path,
    )

    assert mode == "invalid_or_retired"
    assert issues == [
        "live_budget_mode must be one of: autonomous_with_caps, fixed_tranche"
    ]
    assert dynamic_cap == Decimal("100.00")


def test_mirofish_market_priors_tag_bot_attention_and_crowded_ai_beta():
    market_data = {
        "AMD": {"current_price": "120", "previous_close": "121"},
        "KO": {"current_price": "65", "previous_close": "66"},
        "HOOD": {"current_price": "22", "previous_close": "22.2"},
    }
    enriched = cli_main._apply_mirofish_market_priors_to_market_data(
        market_data,
        {
            "mirofish_handoff": {
                "mirofish_advisory_gate_action": "suppress",
                "mirofish_advisory_triggered_gates": [
                    "broker_friction",
                    "macro_override",
                    "attribution_error",
                ],
                "ticker_attention_map": {
                    "AMD": {"category": "bot_correlation"},
                },
                "deep_research_review_market_regime": {
                    "primary_driver": "macro_dominant_dispersion_heavy",
                },
                "deep_research_review_stock_selection_biases": {
                    "positive_bias": ["DIA_or_Dow_quality", "energy", "defensives"],
                    "negative_bias": ["SMH_or_SOXX_semiconductors", "crowded_AI_beta"],
                    "event_sensitive_watch": ["HOOD", "BULL", "IBKR", "SCHW"],
                },
            },
            "watchlists": {
                "release_calendar": {
                    "planner_flags": {"macro_event_risk": True},
                }
            },
        },
    )

    assert enriched["AMD"]["bot_copycat_attention"] is True
    assert enriched["AMD"]["ai_beta_crowding_risk"] is True
    assert enriched["AMD"]["macro_event_risk"] is True
    assert enriched["AMD"]["mirofish_false_signal_suppression"] is True
    assert enriched["AMD"]["mirofish_advisory_gate_action"] == "suppress"
    assert enriched["AMD"]["mirofish_triggered_advisory_gates"] == [
        "attribution_error",
        "broker_friction",
        "macro_override",
    ]
    assert "mirofish_bot_correlation" in enriched["AMD"]["mirofish_prior_tags"]
    assert enriched["KO"].get("bot_copycat_attention") is not True
    assert enriched["KO"].get("ai_beta_crowding_risk") is not True
    assert enriched["KO"].get("mirofish_false_signal_suppression") is not True
    assert enriched["KO"]["macro_event_risk"] is True
    assert enriched["KO"]["deep_research_positive_relative_bias"] is True
    assert "deep_research_positive_relative_bias" in enriched["KO"]["mirofish_prior_tags"]
    assert enriched["HOOD"]["deep_research_event_sensitive_watch"] is True
    assert enriched["HOOD"]["mirofish_false_signal_suppression"] is True
    assert "deep_research_event_sensitive_watch" in enriched["HOOD"]["mirofish_prior_tags"]


def test_rank_overnight_results_keeps_fallback_reason_visible():
    ranked = cli_main._rank_overnight_results(
        [
            {
                "symbol": "KO",
                "status": "fallback",
                "score": "0.89",
                "rating": "Buy",
                "method": "market_snapshot_fallback",
                "fallback_reason": "controlled dip with report-33 positive relative bias",
                "reports": {"market": "fallback market summary"},
            }
        ]
    )

    assert ranked == [
        {
            "symbol": "KO",
            "score": "0.89",
            "rating": "Buy",
            "signal": "",
            "status": "fallback",
            "method": "market_snapshot_fallback",
            "reason": "fallback market summary",
            "fallback_reason": "controlled dip with report-33 positive relative bias",
        }
    ]


def test_alpaca_submit_live_mirror_is_hard_disabled_before_any_broker_client(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(
            2026, 5, 26, 13, 5, tzinfo=datetime.timezone.utc
        ),
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_execution_config",
        lambda: AlpacaExecutionConfig(
            paper_enabled=True,
            live_mirror_enabled=True,
        ),
    )
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))

    result = runner.invoke(
        app,
        [
            "alpaca",
            "submit",
            "--run-id",
            "20260526-tuesday",
            "--third-symbol",
            "MSFT",
            "--third-limit-price",
            "500",
            "--log-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert paper_client.submitted == []
    assert live_client.submitted == []
    assert "authorized normal live intent" in result.stdout.lower()
    packet = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert packet["status"] == "refused"
    assert "authorized normal live intent" in packet["reason"]
    assert packet["submitted_count"] == 0
    assert packet["account_scope"] == ["live"]


def test_alpaca_submit_live_refuses_without_constructing_a_live_client(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cli_main,
        "_alpaca_execution_config",
        lambda: AlpacaExecutionConfig(
            paper_enabled=True,
            live_mirror_enabled=True,
        ),
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_clients",
        lambda: (_ for _ in ()).throw(
            AssertionError("manual live submit must not construct a live client")
        ),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "submit",
            "--run-id",
            "20260526-tuesday",
            "--third-symbol",
            "MSFT",
            "--third-limit-price",
            "500",
            "--log-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert "authorized normal live intent" in result.stdout.lower()
    packet = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert packet["status"] == "refused"
    assert packet["submitted_count"] == 0


def test_alpaca_submit_live_path_is_disabled_even_after_legacy_window(monkeypatch):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(
            2026, 5, 27, 9, 5, tzinfo=datetime.timezone.utc
        ),
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_execution_config",
        lambda: AlpacaExecutionConfig(
            paper_enabled=True,
            live_mirror_enabled=True,
        ),
    )
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))

    result = runner.invoke(
        app,
        [
            "alpaca",
            "submit",
            "--run-id",
            "20260526-tuesday",
            "--third-symbol",
            "MSFT",
            "--third-limit-price",
            "500",
        ],
    )

    assert result.exit_code != 0
    assert "authorized normal live intent" in result.stdout.lower()
    assert paper_client.submitted == []
    assert live_client.submitted == []


def test_alpaca_submit_paper_only_does_not_create_live_client(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_execution_config",
        lambda: AlpacaExecutionConfig(
            paper_enabled=True,
            live_mirror_enabled=False,
        ),
    )
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_clients",
        lambda: (_ for _ in ()).throw(AssertionError("live client should not be used")),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "submit",
            "--paper-only",
            "--run-id",
            "20260527-paper",
            "--third-symbol",
            "MSFT",
            "--third-limit-price",
            "500",
            "--log-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert len(paper_client.submitted) == 3
    assert all(order["client_order_id"].startswith("ta-20260527-paper-paper") for order in paper_client.submitted)
    packet = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert packet["status"] == "submitted"
    assert packet["account_scope"] == ["paper"]
    assert packet["submitted_count"] == 3
    assert packet["estimated_spent_this_run_by_account"] == {"paper": "1000.00", "live": "0.00"}
    assert "paper $1000.00" in packet["plain_english_summary"]
    assert "live $0.00" in packet["plain_english_summary"]


def test_alpaca_supervise_hourly_dry_run_logs_without_submitting(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {})

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--dry-run",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--execution-board-dir",
            str(tmp_path / "empty-board"),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "hold"
    assert payload["submitted"] == []
    assert payload["portfolio"]["live"]["equity"] == "200.00"
    assert payload["portfolio"]["live"]["unrealized_pl"] == "0.30"
    assert payload["portfolio"]["live"]["positions"][0]["symbol"] == "GOOGL"
    assert payload["evidence"]["risk_posture"]["name"] == "balanced"
    assert payload["evidence"]["risk_posture"]["live_gate_relaxation_allowed"] is False
    assert live_client.submitted == []
    assert list(tmp_path.glob("hourly-supervisor-*.json"))


def test_alpaca_supervise_hourly_compact_json_output_points_to_raw_packet(monkeypatch, tmp_path):
    envelope_path = tmp_path / "config" / "risk_envelope.yaml"
    envelope_path.parent.mkdir()
    _write_test_risk_envelope(envelope_path)
    monkeypatch.chdir(tmp_path)
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {})

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--dry-run",
            "--json-output",
            "--compact-json-output",
            "--log-dir",
            str(tmp_path),
            "--execution-board-dir",
            str(tmp_path / "empty-board"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema"] == "compact_hourly_supervisor_v1"
    assert payload["decision"] == "hold"
    assert payload["submitted_count"] == 0
    assert payload["portfolio_summary"]["live"]["position_count"] == 1
    assert payload["portfolio_summary"]["live"]["equity"] == "200.00"
    envelope, envelope_issues = load_risk_envelope(envelope_path)
    assert envelope is not None, envelope_issues
    assert payload["live_budget"]["mode"] == envelope.live_budget_mode
    assert Path(payload["raw_packet_path"]).exists()
    assert "portfolio" not in payload
    assert "evidence" not in payload
    assert "actions" not in payload
    assert live_client.submitted == []


def test_alpaca_supervise_hourly_paper_first_submits_to_paper(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {
        "AMZN": {
            "current_price": "200",
            "previous_close": "200",
            "volume_ratio": "1.5",
            "tradable": True,
        }
    })
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--submit-actions",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--execution-board-dir",
            str(tmp_path / "empty-board"),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "paper-first"
    assert len(paper_client.submitted) == 1
    assert paper_client.submitted[0]["symbol"] == "AMZN"
    assert paper_client.submitted[0]["client_order_id"].startswith("ta-hourly-")
    assert not paper_client.submitted[0]["client_order_id"].startswith("ta-tiny-")
    assert live_client.submitted == []


def test_alpaca_supervise_hourly_live_buy_requires_submit_guard(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    live_client.positions = []
    captured_guard_kwargs = {}
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {
        "AMZN": {
            "current_price": "196",
            "previous_close": "200",
            "volume_ratio": "2.0",
            "tradable": True,
        }
    })
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(
        cli_main,
        "validate_supervisor_live_submit_allowed",
        lambda **kwargs: (
            captured_guard_kwargs.update(kwargs)
            or [cli_main.OrderIssue("live-submit-guard", "risk envelope missing")]
        ),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--submit-actions",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--execution-board-dir",
            str(tmp_path / "empty_board"),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "blocked"
    assert payload["alert"]["severity"] == "CRITICAL"
    assert payload["issues"][0]["ticket_id"] == "live-submit-guard"
    assert captured_guard_kwargs["live_account"]["buying_power"] == "100"
    assert live_client.submitted == []


def test_alpaca_supervise_hourly_tiny_live_guard_blocks_reconciliation_mismatch(monkeypatch, tmp_path):
    class _DriftingLiveClient(_FakeCliClient):
        def __init__(self):
            super().__init__(paper=False)
            self.positions = []
            self.position_reads = 0

        def list_positions(self):
            self.position_reads += 1
            if self.position_reads == 1:
                return []
            return [{"symbol": "AAPL", "qty": "1"}]

    paper_client = _FakeCliClient(paper=True)
    live_client = _DriftingLiveClient()
    real_guard = cli_main.acquire_tiny_live_operational_guard
    fresh_control_path = tmp_path / "live_control.json"
    fresh_control_path.write_text(
        json.dumps(
            {
                "frozen": False,
                "reason": "test control",
                "dead_man_expires_at": "2099-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    def _guard_with_test_lock(**kwargs):
        kwargs.pop("control_state_path", None)
        return real_guard(
            **kwargs,
            lock_path=tmp_path / "tiny-live-submit.lock",
            control_state_path=fresh_control_path,
        )

    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {
        "AMZN": {
            "current_price": "196",
            "previous_close": "200",
            "volume_ratio": "2.0",
            "tradable": True,
        }
    })
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(cli_main, "validate_supervisor_live_submit_allowed", lambda **_: [])
    monkeypatch.setattr(cli_main, "acquire_tiny_live_operational_guard", _guard_with_test_lock)

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--submit-actions",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--execution-board-dir",
            str(tmp_path / "empty_board"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["decision"] == "blocked"
    assert "authorized normal live intent" in payload["reason"]
    assert live_client.submitted == []
    assert paper_client.submitted == []
    assert not (tmp_path / "tiny-live-submit.lock").exists()


def test_alpaca_supervise_hourly_live_submit_refuses_without_issued_intent(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    live_client.positions = []
    paper_client.positions = []

    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {
        "AMZN": {
            "current_price": "196",
            "previous_close": "200",
            "volume_ratio": "2.0",
            "tradable": True,
        }
    })
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(cli_main, "validate_supervisor_live_submit_allowed", lambda **_: [])
    monkeypatch.setattr(
        cli_main,
        "acquire_tiny_live_operational_guard",
        lambda **_: type(
            "Guard",
            (),
            {"allowed": True, "issues": [], "lock": None},
        )(),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--submit-actions",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--execution-board-dir",
            str(tmp_path / "empty_board"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["decision"] == "blocked"
    assert "authorized normal live intent" in payload["reason"]
    assert live_client.submitted == []
    assert paper_client.submitted == []


def test_alpaca_supervise_hourly_honors_board_underperformer_review_for_new_live_buys(
    monkeypatch, tmp_path
):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    live_client.positions = []
    paper_client.positions = []
    board_dir = tmp_path / "execution_board"
    board_dir.mkdir()
    (board_dir / "latest.json").write_text(
        json.dumps(
            {
                "kind": "execution_board_review",
                "generated_at": "2026-06-02T18:00:00+00:00",
                "analysis_only": True,
                "can_submit_orders": False,
                "recommendation": "review_underperformers_before_new_buys",
                "metrics": {"packet_count": 24},
                "violations": [],
                "warnings": [{"type": "loss_exit"}],
                "loss_review_evidence": {
                    "symbol": "TSM",
                    "review_allowed": False,
                    "remaining_blocker_count": 5,
                    "resolved_blocker_count": 8,
                    "next_action": "manual_board_review_with_refreshed_evidence_required",
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {
        "AMZN": {
            "current_price": "196",
            "previous_close": "200",
            "volume_ratio": "2.0",
            "tradable": True,
        }
    })
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(cli_main, "validate_supervisor_live_submit_allowed", lambda **_: [])

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--submit-actions",
            "--json-output",
            "--log-dir",
            str(tmp_path / "hourly"),
            "--execution-board-dir",
            str(board_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["decision"] == "hold"
    assert "new live buys paused by BOARD review" in payload["reason"]
    assert live_client.submitted == []
    assert paper_client.submitted == []
    assert payload["evidence"]["execution_board_review"]["new_buys_suspended"] is True
    assert payload["evidence"]["execution_board_review"]["loss_review_evidence"] == {
        "symbol": "TSM",
        "review_allowed": False,
        "remaining_blocker_count": 5,
        "resolved_blocker_count": 8,
        "next_action": "manual_board_review_with_refreshed_evidence_required",
    }


def test_alpaca_supervise_hourly_duplicate_tiny_live_id_blocks_for_reconcile(
    monkeypatch, tmp_path
):
    class _DuplicateLiveClient(_FakeCliClient):
        def __init__(self, paper):
            super().__init__(paper=paper)
            self.lookup_client_order_ids = []

        def submit_order(self, order):
            self.submitted.append(order)
            raise RuntimeError(
                'Alpaca POST /v2/orders failed with 422: '
                '{"code":40310000,"message":"client_order_id already exists"}'
            )

        def get_order_by_client_order_id(self, client_order_id):
            self.lookup_client_order_ids.append(client_order_id)
            submitted = self.submitted[0]
            return {
                "id": "alpaca-existing-order",
                "client_order_id": client_order_id,
                "symbol": submitted["symbol"],
                "side": submitted["side"],
                "type": submitted["type"],
                "notional": submitted["notional"],
                "limit_price": submitted["limit_price"],
                "status": "new",
            }

    paper_client = _FakeCliClient(paper=True)
    live_client = _DuplicateLiveClient(paper=False)
    live_client.positions = []
    paper_client.positions = []

    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {
        "AMZN": {
            "current_price": "196",
            "previous_close": "200",
            "volume_ratio": "2.0",
            "tradable": True,
        }
    })
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(cli_main, "validate_supervisor_live_submit_allowed", lambda **_: [])
    monkeypatch.setattr(
        cli_main,
        "acquire_tiny_live_operational_guard",
        lambda **_: type(
            "Guard",
            (),
            {"allowed": True, "issues": [], "lock": None},
        )(),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--submit-actions",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--execution-board-dir",
            str(tmp_path / "empty_board"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["decision"] == "blocked"
    assert "authorized normal live intent" in payload["reason"]
    assert paper_client.submitted == []
    assert live_client.submitted == []
    assert live_client.lookup_client_order_ids == []
    assert payload["submitted"] == []
    assert payload["reconciled_orders"] == []


def test_alpaca_supervise_hourly_blocks_when_latest_live_packet_order_is_missing(
    monkeypatch, tmp_path
):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    live_client.positions = []
    paper_client.positions = []
    prior_generated_at = datetime.datetime.now(
        tz=datetime.timezone.utc
    ) - datetime.timedelta(hours=1)
    prior_packet = {
        "generated_at": prior_generated_at.isoformat(timespec="seconds"),
        "decision": "buy",
        "material": True,
        "reason": "prior live order submitted",
        "live_exposure": "0.00",
        "actions": [
            {
                "action": "buy",
                "symbol": "AMZN",
                "side": "buy",
                "notional": "50.00",
                "limit_price": "196.39",
                "account": "live",
                "execution_mode": "tiny_live",
                "sleeve": "current-aggressive",
                "idempotency_key": "ta-tiny-prior",
            }
        ],
        "issues": [],
        "submitted": [
            {
                "client_order_id": "ta-tiny-prior",
                "symbol": "AMZN",
                "side": "buy",
                "type": "limit",
                "notional": "50.00",
                "limit_price": "196.39",
                "status": "new",
            }
        ],
    }
    (tmp_path / f"hourly-supervisor-{prior_generated_at:%Y%m%d-%H%M%S}.json").write_text(
        json.dumps(prior_packet),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {
        "AMZN": {
            "current_price": "196",
            "previous_close": "200",
            "volume_ratio": "2.0",
            "tradable": True,
        }
    })
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(cli_main, "validate_supervisor_live_submit_allowed", lambda **_: [])

    def _guard_after_latest_packet_block(**kwargs):
        assert kwargs["live_actions"] == []
        return type(
            "Guard",
            (),
            {"allowed": True, "issues": [], "lock": None},
        )()

    monkeypatch.setattr(
        cli_main,
        "acquire_tiny_live_operational_guard",
        _guard_after_latest_packet_block,
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--submit-actions",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--execution-board-dir",
            str(tmp_path / "empty_board"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["decision"] == "blocked"
    assert payload["reason"] == "hourly supervisor latest-packet reconciliation blocked submit"
    assert live_client.submitted == []
    assert paper_client.submitted == []
    issue_text = payload["issues"][0]["reason"]
    assert "previous live order missing at broker: ta-tiny-prior" in issue_text
    latest_reconciliation = payload["evidence"]["latest_packet_reconciliation"]
    assert latest_reconciliation["matched"] is False
    assert latest_reconciliation["checked_client_order_ids"] == ["ta-tiny-prior"]
    assert latest_reconciliation["issues"] == [
        "previous live order missing at broker: ta-tiny-prior"
    ]


def test_alpaca_supervise_hourly_suppresses_duplicate_alert_email(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    live_client.positions = []
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
                "AMZN": {
                    "current_price": "196",
                    "previous_close": "200",
                    "volume_ratio": "2.0",
                    "tradable": True,
            }
        },
    )
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")
    monkeypatch.setattr(
        cli_main,
        "validate_supervisor_live_submit_allowed",
        lambda **_: [
            cli_main.OrderIssue("live-submit-guard", "risk envelope missing")
        ],
    )
    prior_generated_at = (
        datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(hours=1)
    )
    prior_packet = {
        "generated_at": prior_generated_at.isoformat(timespec="seconds"),
        "decision": "blocked",
        "material": True,
        "reason": "hourly supervisor live submit failed guard validation",
        "live_exposure": "0.00",
        "actions": [
            {
                "action": "buy",
                "symbol": "AMZN",
                "side": "buy",
                "notional": "25.00",
                "limit_price": "208.41",
                "account": "live",
                "execution_mode": "tiny_live",
                "sleeve": "current-aggressive",
                "extended_hours": False,
            }
        ],
        "issues": [
            {"ticket_id": "live-submit-guard", "reason": "risk envelope missing"}
        ],
        "submitted": [],
        "alert": {
            "severity": "CRITICAL",
            "notify": True,
            "base_notify": True,
            "reason": "hourly supervisor live submit failed guard validation",
            "problem": "A safety control or the broker stopped this run before money moved.",
            "approval_prompt": "Question: OK to let the system repair its own setup if it can do so safely? Until then it stays stopped and will not spend real money.",
            "email_suppressed": False,
        },
    }
    (tmp_path / f"hourly-supervisor-{prior_generated_at:%Y%m%d-%H%M%S}.json").write_text(
        json.dumps(prior_packet),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--submit-actions",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--execution-board-dir",
            str(tmp_path / "empty_board"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["decision"] == "blocked"
    assert payload["alert"]["severity"] == "CRITICAL"
    assert payload["alert"]["email_suppressed"] is True
    assert payload["alert"]["notify"] is False
    assert payload["notification_policy_notify"] is True
    assert payload["notify"] is False
    assert "alert_email" not in payload
    written_packets = sorted(tmp_path.glob("hourly-supervisor-*.json"))
    saved = json.loads(written_packets[-1].read_text(encoding="utf-8"))
    assert saved["alert"]["email_suppressed"] is True
    assert "alert_email" not in saved


def test_live_submit_call_sites_are_hard_disabled_or_exact_intent_boundaries():
    submit_source = inspect.getsource(cli_main.alpaca_submit)
    assert "execute_order_pairs(" not in submit_source
    assert "authorized normal live intent" in submit_source.lower()
    assert "_alpaca_clients(" not in submit_source

    supervisor_source = inspect.getsource(cli_main.alpaca_supervise_hourly)
    assert "live_client.submit_order" not in supervisor_source
    assert "authorized normal live intent" in supervisor_source.lower()


def test_alpaca_supervise_hourly_records_submit_failure_packet(monkeypatch, tmp_path):
    class _FailingSubmitClient(_FakeCliClient):
        def submit_order(self, order):
            raise RuntimeError("paper endpoint timed out")

    paper_client = _FailingSubmitClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {
        "AMZN": {
            "current_price": "200",
            "previous_close": "200",
            "volume_ratio": "1.5",
            "tradable": True,
        }
    })
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "regular")

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--submit-actions",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--execution-board-dir",
            str(tmp_path / "empty_board"),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "blocked"
    assert payload["submitted"] == []
    assert "paper endpoint timed out" in payload["issues"][0]["reason"]
    packet_paths = [
        path
        for path in tmp_path.glob("hourly-supervisor-*.json")
        if not path.name.endswith(".compact.json")
    ]
    assert packet_paths
    packet = json.loads(packet_paths[0].read_text(encoding="utf-8"))
    assert packet["decision"] == "blocked"
    assert "paper endpoint timed out" in packet["issues"][0]["reason"]


def test_alpaca_supervisor_daily_report_includes_balances_and_positions(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    live_client.account_equity = "1200"
    paper_client.account_equity = "100200"
    paper_client.positions = [
        {
            "symbol": "GOOGL",
            "qty": "2.7",
            "avg_entry_price": "383.50",
            "market_value": "1045.30",
            "cost_basis": "45",
            "unrealized_pl": "1000.30",
            "unrealized_plpc": "22.228",
            "current_price": "386",
        }
    ]
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {})
    packet = tmp_path / "hourly-supervisor-20260529-200000.json"
    packet.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-29T20:00:00+00:00",
                "decision": "hold",
                "material": False,
                "reason": "no trigger",
                "submitted": [],
                "issues": [],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervisor-daily-report",
            "--json-output",
            "--log-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["subject"].startswith("Your trading update for ")
    assert "Real-money account: $1,200.00 total" in payload["body"]
    assert "position P/L $0.30 (0.66%)" in payload["body"]
    assert "Practice account P/L: $1,000.30" in payload["body"]
    assert "Live buying power:" not in payload["body"]
    assert "Live exposure:" not in payload["body"]
    assert "Paper equity:" not in payload["body"]
    assert "GOOGL" in payload["body"]


def test_alpaca_supervisor_daily_report_compact_json_writes_raw_packet(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    live_client.account_equity = "1200"
    paper_client.account_equity = "100200"
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {})
    current_packet_date = datetime.datetime.now(tz=datetime.timezone.utc).date().isoformat()
    (tmp_path / "hourly-supervisor-current.json").write_text(
        json.dumps(
            {
                "generated_at": f"{current_packet_date}T20:00:00+00:00",
                "decision": "hold",
                "material": False,
                "reason": "no trigger",
                "submitted": [],
                "issues": [],
            }
        ),
        encoding="utf-8",
    )
    report_dir = tmp_path / "daily_reports"

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervisor-daily-report",
            "--json-output",
            "--compact-json-output",
            "--log-dir",
            str(tmp_path),
            "--daily-report-log-dir",
            str(report_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema"] == "compact_supervisor_daily_report_v1"
    assert payload["subject"].startswith("Your trading update for ")
    assert payload["counts"]["hourly_packets"] == 1
    assert payload["portfolio_summary"]["live"]["equity"] == "1200.00"
    assert payload["body_summary"]["char_count"] > 0
    assert Path(payload["raw_packet_path"]).exists()
    assert (report_dir / "latest.json").exists()
    raw_packet = json.loads(Path(payload["raw_packet_path"]).read_text(encoding="utf-8"))
    assert "Real-money account: $1,200.00 total" in raw_packet["body"]
    assert raw_packet["packet_path"] == payload["raw_packet_path"]
    assert "body" not in payload
    assert "portfolio" not in payload


def test_daily_report_includes_latest_premarket_brief(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    brief_dir = tmp_path / "briefs"
    brief_dir.mkdir()
    (brief_dir / "latest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T10:00:00+00:00",
                "analysis_only": True,
                "source_packets": [{"kind": "hourly_supervisor"}],
                "premarket_instructions": {
                    "top_symbol": "ORCL",
                    "latest_research_context": {
                        "packet_count": 8,
                        "blocked_count": 0,
                        "prior_feed": {
                            "schema": "overnight_prior_feed_v1",
                            "path": "results/overnight_plans/research_context/overnight-prior-feed-20260601-003000.json",
                            "packet_count": 8,
                            "blocked_count": 0,
                            "analysis_only": True,
                            "execution_authority": "none",
                            "forbidden_effects": ["submit_order"],
                        },
                        "provider_fallback_needs": ["market_news"],
                        "watchlists": ["reddit"],
                        "execution_authority": "none",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
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
            "--premarket-brief-log-dir",
            str(brief_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["premarket_brief"]["premarket_instructions"]["top_symbol"] == "ORCL"
    assert "Tomorrow's top stock to watch: ORCL." in payload["body"]


def test_plan_overnight_writes_analysis_packet_without_submitting(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_load_recent_market_packet_paths", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_default_watchlist_paths", lambda: [])
    monkeypatch.setattr(
        cli_main,
        "build_overnight_candidate_universe",
        lambda **_kwargs: [
            {"symbol": "GOOGL", "sources": ["live_positions"], "owned": True, "research_weight": "equal"},
            {"symbol": "ORCL", "sources": ["base_universe"], "owned": False, "research_weight": "equal"},
        ],
    )
    monkeypatch.setattr(
        cli_main,
        "_run_overnight_ticker_analysis_guarded",
        lambda **kwargs: {
            "symbol": kwargs["symbol"],
            "rating": "Buy" if kwargs["symbol"] == "ORCL" else "Hold",
            "score": "0.90" if kwargs["symbol"] == "ORCL" else "0.50",
            "final_trade_decision": f"Rating: {'Buy' if kwargs['symbol'] == 'ORCL' else 'Hold'}",
            "reports": {"market": "ok"},
            "signal": "BUY" if kwargs["symbol"] == "ORCL" else "HOLD",
            "status": "ok",
        },
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "plan-overnight",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--per-ticker-timeout-minutes",
            "0",
            "--overnight-backend-url",
            "https://example.test/v1",
            "--no-research-context",
            "--agent-ledger-path",
            str(tmp_path / "agent-ledger.jsonl"),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert [item["symbol"] for item in payload["ranked_candidates"]] == ["ORCL", "GOOGL"]
    assert payload["overnight_quality"]["completion_status"] == "complete"
    assert payload["packet_path"].endswith(".json")
    assert payload["agent_intelligence_ledger"]["ledger_path"] == str(tmp_path / "agent-ledger.jsonl")
    assert payload["agent_intelligence_ledger"]["forecast_count"] > 0
    assert list(tmp_path.glob("overnight-plan-*.json"))
    assert (tmp_path / "latest.json").exists()
    assert paper_client.submitted == []
    assert live_client.submitted == []


def test_plan_overnight_refreshes_top_provider_bundles(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_load_recent_market_packet_paths", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_default_watchlist_paths", lambda: [])
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {})
    monkeypatch.setattr(
        cli_main,
        "build_overnight_candidate_universe",
        lambda **_kwargs: [
            {"symbol": "GOOGL", "sources": ["live_positions"], "owned": True, "research_weight": "equal"},
            {"symbol": "ORCL", "sources": ["base_universe"], "owned": False, "research_weight": "equal"},
        ],
    )
    monkeypatch.setattr(
        cli_main,
        "_run_overnight_ticker_analysis_guarded",
        lambda **kwargs: {
            "symbol": kwargs["symbol"],
            "rating": "Buy" if kwargs["symbol"] == "ORCL" else "Hold",
            "score": "0.90" if kwargs["symbol"] == "ORCL" else "0.50",
            "final_trade_decision": f"Rating: {'Buy' if kwargs['symbol'] == 'ORCL' else 'Hold'}",
            "reports": {"market": "ok"},
            "signal": "BUY" if kwargs["symbol"] == "ORCL" else "HOLD",
            "status": "ok",
        },
    )

    provider_calls = []

    def fake_provider_bundle(symbol, **kwargs):
        provider_calls.append((symbol, tuple(kwargs["evidence_needs"])))
        return SimpleNamespace(
            symbol=symbol,
            packets=[SimpleNamespace(packet_id=f"{symbol}-source")],
            summary_packet=SimpleNamespace(
                packet_id=f"{symbol}-summary",
                payload={
                    "gap_packet_count": 1,
                    "unsupported_route_count": 2,
                    "blocked_packet_attempt_count": 3,
                    "evidence_needs_without_non_gap_packets": ["earnings_transcripts"],
                },
            ),
            route_attempts=[],
        )

    def fake_write_research_packet(packet, output_dir):
        path = Path(output_dir) / f"{packet.packet_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(cli_main, "build_ticker_provider_research_packets", fake_provider_bundle)
    monkeypatch.setattr(cli_main, "write_research_packet", fake_write_research_packet)

    result = runner.invoke(
        app,
        [
            "alpaca",
            "plan-overnight",
            "--json-output",
            "--log-dir",
            str(tmp_path / "overnight"),
            "--per-ticker-timeout-minutes",
            "0",
            "--overnight-backend-url",
            "https://example.test/v1",
            "--no-research-context",
            "--top-provider-bundle-count",
            "2",
            "--top-provider-bundle-output-dir",
            str(tmp_path / "evidence"),
            "--top-provider-bundle-cache-dir",
            str(tmp_path / "cache"),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert provider_calls == [
        ("ORCL", cli_main.OVERNIGHT_TOP_PROVIDER_EVIDENCE_NEEDS),
        ("GOOGL", cli_main.OVERNIGHT_TOP_PROVIDER_EVIDENCE_NEEDS),
    ]
    assert payload["top_provider_bundles"]["analysis_only"] is True
    assert payload["top_provider_bundles"]["execution_authority"] == "none"
    assert payload["top_provider_bundles"]["symbols"] == ["ORCL", "GOOGL"]
    assert payload["top_provider_bundles"]["bundle_count"] == 2
    assert payload["top_provider_bundles"]["source_packet_count"] == 2
    assert payload["top_provider_bundles"]["gap_packet_count"] == 2
    assert payload["top_provider_bundles"]["unsupported_route_count"] == 4
    assert payload["top_provider_bundles"]["blocked_packet_attempt_count"] == 6
    assert payload["top_provider_bundles"]["symbols_with_missing_non_gap"] == ["GOOGL", "ORCL"]
    assert payload["top_provider_bundles"]["evidence_needs_without_non_gap_packets"] == [
        "earnings_transcripts"
    ]
    assert set(payload["top_provider_bundles"]["summary_packet_paths"]) == {"ORCL", "GOOGL"}
    assert payload["overnight_quality"]["top_provider_bundle_count"] == 2
    assert payload["overnight_quality"]["top_provider_bundle_gap_count"] == 2
    assert payload["overnight_quality"]["top_provider_bundle_error_count"] == 0
    assert payload["overnight_quality"]["top_provider_bundle_missing_non_gap_needs"] == [
        "earnings_transcripts"
    ]
    compact_path = Path(payload["packet_path"]).with_suffix(".compact.json")
    compact = json.loads(compact_path.read_text(encoding="utf-8"))
    assert compact["top_provider_bundle_summary"]["symbols"] == ["ORCL", "GOOGL"]
    assert compact["top_provider_bundle_summary"]["bundle_count"] == 2
    assert "top_provider_bundles" in compact["raw_field_groups"]
    assert paper_client.submitted == []
    assert live_client.submitted == []


def test_plan_overnight_refuses_stale_trade_date_when_writing_latest(monkeypatch, tmp_path):
    monkeypatch.setattr(cli_main, "_default_overnight_trade_date", lambda: "2026-06-08")

    result = runner.invoke(
        app,
        [
            "alpaca",
            "plan-overnight",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--trade-date",
            "2026-06-05",
        ],
    )

    assert result.exit_code != 0
    assert "2026-06-08" in result.output
    assert "--no-write-latest" in result.output
    assert not (tmp_path / "latest.json").exists()


def test_plan_overnight_allows_historical_trade_date_without_latest(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    monkeypatch.setattr(cli_main, "_default_overnight_trade_date", lambda: "2026-06-08")
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_load_recent_market_packet_paths", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_default_watchlist_paths", lambda: [])
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {})
    monkeypatch.setattr(
        cli_main,
        "build_overnight_candidate_universe",
        lambda **_kwargs: [
            {"symbol": "ORCL", "sources": ["base_universe"], "owned": False, "research_weight": "equal"},
        ],
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "plan-overnight",
            "--json-output",
            "--compact-json-output",
            "--log-dir",
            str(tmp_path),
            "--trade-date",
            "2026-06-05",
            "--no-write-latest",
            "--no-research-context",
            "--full-graph-tickers",
            "0",
            "--time-budget-minutes",
            "0",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["trade_date"] == "2026-06-05"
    assert payload["raw_packet_path"]
    assert not (tmp_path / "latest.json").exists()
    assert not (tmp_path / "latest-compact.json").exists()
    assert paper_client.submitted == []
    assert live_client.submitted == []


def test_plan_overnight_includes_research_context_and_depleted_source_fallbacks(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    source_quality_review_path = tmp_path / "source-quality-latest.json"
    source_quality_review_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-07T04:28:05+00:00",
                "source_count": 2,
                "stale_count": 1,
                "stale_downrank_count": 1,
                "stale_safe_count": 1,
                "stale_needs_refresh_count": 0,
                "blocked_count": 0,
                "missing_or_invalid_count": 0,
                "unreadable_count": 0,
                "quality_counts": {"medium": 2},
                "freshness_counts": {"fresh": 1, "stale": 1},
                "decisions": [
                    {
                        "source_name": "google_news_rss",
                        "quality": "medium",
                        "freshness_status": "fresh",
                        "blocked": False,
                        "allowed_effects": ["downrank", "request_more_research"],
                    },
                    {
                        "source_name": "alpaca_news",
                        "quality": "medium",
                        "freshness_status": "stale",
                        "blocked": False,
                        "allowed_effects": ["downrank", "request_more_research"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_latest_supervisor_packets", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_load_recent_market_packet_paths", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_default_watchlist_paths", lambda: [])
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "ORCL": {
                "current_price": "225",
                "previous_close": "220",
                "volume_ratio": "2.0",
                "tradable": True,
            }
        },
    )
    monkeypatch.setattr(
        cli_main,
        "build_overnight_candidate_universe",
        lambda **_kwargs: [
            {"symbol": "ORCL", "sources": ["base_universe"], "owned": False, "research_weight": "equal"},
        ],
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "plan-overnight",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--full-graph-tickers",
            "0",
            "--depleted-research-sources",
            "marketaux,finnhub",
            "--source-quality-review-path",
            str(source_quality_review_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    context = payload["research_context"]
    market_news = context["provider_fallbacks"]["market_news"]
    assert context["analysis_only"] is True
    assert context["execution_authority"] == "none"
    assert "submit_order" in context["forbidden_effects"]
    assert "google_news_rss" in market_news["active_source_names"]
    assert "reddit_watchlist" in market_news["active_source_names"]
    assert market_news["source_quality_ordering_enabled"] is True
    assert market_news["scored_active_source_count"] >= 2
    assert "marketaux" in market_news["skipped_source_names"]
    assert "finnhub" in market_news["skipped_source_names"]
    assert context["watchlists"]["source_quality"]["review_path"] == str(source_quality_review_path)
    assert context["watchlists"]["source_quality"]["source_quality_ordering_enabled"] is True
    assert context["watchlists"]["source_quality"]["stale_needs_refresh_count"] == 0
    assert context["watchlists"]["reddit"]["raw_comment_threads_by_default"] is False
    assert context["consumer"]["tradable_symbols"] == ["ORCL"]
    assert payload["overnight_quality"]["research_context_packet_count"] == context["packet_count"]
    assert (tmp_path / "research_context").exists()


def test_plan_overnight_adds_current_ranked_candidates_to_universe(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    captured_packets = {}

    def fake_universe(**kwargs):
        captured_packets["recent_supervisor_packets"] = kwargs["recent_supervisor_packets"]
        return [
            {"symbol": "ORCL", "sources": ["current_ranked_candidates"], "owned": False, "research_weight": "equal"},
        ]

    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_latest_supervisor_packets", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_load_recent_market_packet_paths", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_default_watchlist_paths", lambda: [])
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "ORCL": {
                "current_price": "225",
                "previous_close": "220",
                "volume_ratio": "2.0",
                "tradable": True,
            }
        },
    )
    monkeypatch.setattr(cli_main, "build_overnight_candidate_universe", fake_universe)
    monkeypatch.setattr(
        cli_main,
        "_run_overnight_ticker_analysis_guarded",
        lambda **kwargs: {
            "symbol": kwargs["symbol"],
            "rating": "Buy",
            "score": "0.90",
            "final_trade_decision": "Rating: Buy",
            "reports": {},
            "signal": "BUY",
            "status": "ok",
        },
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "plan-overnight",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--per-ticker-timeout-minutes",
            "0",
            "--overnight-backend-url",
            "https://example.test/v1",
            "--no-research-context",
        ],
    )

    assert result.exit_code == 0
    assert captured_packets["recent_supervisor_packets"][0]["ranked_candidates"][0]["symbol"] == "ORCL"


def test_plan_overnight_writes_fallback_rankings_when_graph_fails(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_load_recent_market_packet_paths", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_default_watchlist_paths", lambda: [])
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "ORCL": {
                "current_price": "225",
                "previous_close": "220",
                "volume_ratio": "2.0",
                "tradable": True,
            }
        },
    )
    monkeypatch.setattr(
        cli_main,
        "build_overnight_candidate_universe",
        lambda **_kwargs: [
            {"symbol": "ORCL", "sources": ["base_universe"], "owned": False, "research_weight": "equal"},
        ],
    )
    monkeypatch.setattr(
        cli_main,
        "_run_overnight_ticker_analysis_guarded",
        lambda **_kwargs: {
            "symbol": "ORCL",
            "status": "failed",
            "error": "Recursion limit of 100 reached",
            "score": "0.00",
            "rating": "Hold",
        },
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "plan-overnight",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--full-graph-tickers",
            "1",
            "--per-ticker-timeout-minutes",
            "0",
            "--overnight-backend-url",
            "https://example.test/v1",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["ticker_results"][0]["status"] == "fallback"
    assert payload["ticker_results"][0]["graph_status"] == "failed"
    assert "Recursion limit" in payload["ticker_results"][0]["graph_error"]
    assert payload["ranked_candidates"][0]["symbol"] == "ORCL"
    assert payload["ranked_candidates"][0]["status"] == "fallback"
    assert payload["overnight_quality"]["fallback_count"] == 1
    assert payload["overnight_quality"]["full_graph_count"] == 1
    assert payload["overnight_quality"]["full_graph_attempt_count"] == 1
    assert payload["overnight_quality"]["full_graph_success_count"] == 0
    assert payload["overnight_quality"]["graph_failure_count"] == 1
    assert payload["overnight_quality"]["original_graph_selected_tickers"] == ["ORCL"]
    assert payload["overnight_quality"]["original_graph_failed_tickers"] == ["ORCL"]
    assert payload["original_tradingagents_graph"]["selected_tickers"] == ["ORCL"]
    assert payload["original_tradingagents_graph"]["successful_tickers"] == []
    assert payload["original_tradingagents_graph"]["failed_tickers"] == ["ORCL"]
    assert payload["original_tradingagents_graph"]["bounds"]["full_graph_limit"] == 1
    assert payload["overnight_quality"]["completion_status"] == "failed"
    assert payload["submitted"] == []
    assert (tmp_path / "latest.json").exists()


def test_plan_overnight_limits_full_graph_and_scores_remaining_candidates(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    calls = []
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_load_recent_market_packet_paths", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_default_watchlist_paths", lambda: [])
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "ORCL": {"current_price": "225", "previous_close": "220", "volume_ratio": "2.0", "tradable": True},
            "MSFT": {"current_price": "450", "previous_close": "430", "volume_ratio": "1.8", "tradable": True},
            "AAPL": {"current_price": "200", "previous_close": "200", "volume_ratio": "1.0", "tradable": True},
        },
    )
    monkeypatch.setattr(
        cli_main,
        "build_overnight_candidate_universe",
        lambda **_kwargs: [
            {"symbol": "ORCL", "sources": ["base_universe"], "owned": False, "research_weight": "equal"},
            {"symbol": "MSFT", "sources": ["base_universe"], "owned": False, "research_weight": "equal"},
            {"symbol": "AAPL", "sources": ["base_universe"], "owned": False, "research_weight": "equal"},
        ],
    )

    def fake_guarded(**kwargs):
        calls.append(kwargs["symbol"])
        return {
            "symbol": kwargs["symbol"],
            "status": "ok",
            "rating": "Buy",
            "score": "0.90",
            "signal": "BUY",
            "final_trade_decision": "Rating: Buy",
            "reports": {},
        }

    monkeypatch.setattr(cli_main, "_run_overnight_ticker_analysis_guarded", fake_guarded)

    result = runner.invoke(
        app,
        [
            "alpaca",
            "plan-overnight",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--full-graph-tickers",
            "1",
            "--per-ticker-timeout-minutes",
            "0",
            "--overnight-backend-url",
            "https://example.test/v1",
            "--no-research-context",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert calls == ["AAPL"]
    assert len(payload["ticker_results"]) == 3
    assert {item["status"] for item in payload["ticker_results"]} == {"ok", "fallback"}
    assert payload["overnight_quality"]["full_graph_count"] == 1
    assert payload["overnight_quality"]["fallback_count"] == 2
    assert payload["ticker_results"][0]["method"] == "original_tradingagents_graph"
    assert payload["overnight_quality"]["original_graph_selected_tickers"] == ["AAPL"]
    assert payload["overnight_quality"]["original_graph_successful_tickers"] == ["AAPL"]
    assert payload["original_tradingagents_graph"]["analysis_only"] is True
    assert payload["original_tradingagents_graph"]["execution_authority"] == "none"
    assert payload["original_tradingagents_graph"]["selected_tickers"] == ["AAPL"]
    assert payload["original_tradingagents_graph"]["successful_tickers"] == ["AAPL"]
    assert payload["original_tradingagents_graph"]["bounds"]["full_graph_limit"] == 1
    assert payload["original_tradingagents_graph"]["bounds"]["per_ticker_timeout_minutes"] == 0


def test_compact_overnight_plan_payload_points_to_raw_packet():
    raw_path = Path("results/overnight_plans/example.json")
    compact = cli_main._compact_overnight_plan_payload(
        {
            "generated_at": "2026-06-04T02:30:00+00:00",
            "trade_date": "2026-06-04",
            "candidate_universe": [{"symbol": "NVDA"}],
            "tradable_universe": [{"symbol": "NVDA"}],
            "rejected_symbols": [],
            "ranked_candidates": [{"symbol": "NVDA", "rating": "Buy", "score": "0.90", "method": "full_graph"}],
            "ticker_results": [{"symbol": "NVDA", "status": "ok", "reports": {"market": "large"}}],
            "research_context": {
                "packet_count": 3,
                "blocked_packets": [{}],
                "stale_warnings": [{}, {}],
                "prior_feed": {
                    "schema": "overnight_prior_feed_v1",
                    "path": "results/overnight_plans/research_context/overnight-prior-feed.json",
                    "execution_authority": "none",
                },
            },
            "overnight_quality": {
                "full_graph_count": 1,
                "fallback_count": 0,
                "graph_failure_count": 0,
                "completion_status": "complete",
                "completion_reasons": ["1 full graph run(s) completed"],
                "tradable_count": 1,
                "ranked_count": 1,
                "graph_config": {
                    "graph_profile": "compact",
                    "model_route": "explicit_google_overnight_graph",
                    "llm_provider": "google",
                },
            },
            "submitted": [],
        },
        raw_path,
    )

    assert compact["schema"] == "compact_overnight_plan_v1"
    assert compact["raw_packet_path"] == str(raw_path)
    assert compact["counts"]["ticker_results"] == 1
    assert compact["top_candidate"]["symbol"] == "NVDA"
    assert compact["overnight_quality"]["completion_status"] == "complete"
    assert compact["overnight_quality"]["tradable_count"] == 1
    assert compact["overnight_quality"]["graph_config"]["model_route"] == (
        "explicit_google_overnight_graph"
    )
    assert compact["research_context_summary"]["stale_warning_count"] == 2
    assert compact["research_context_summary"]["prior_feed"]["schema"] == "overnight_prior_feed_v1"
    assert "ticker_results" not in compact
    assert "research_context" not in compact
    assert "ticker_results" in compact["raw_field_groups"]


def test_overnight_graph_completion_status_marks_requested_unattempted_incomplete():
    status, reasons = cli_main._overnight_graph_completion_status(
        requested_full_graph_tickers=3,
        effective_full_graph_tickers=3,
        tradable_count=5,
        full_graph_count=0,
        full_graph_success_count=0,
        graph_failure_count=0,
        graph_disabled_reason=None,
    )

    assert status == "incomplete"
    assert "requested but no graph run was attempted" in reasons[0]


def test_plan_overnight_compact_json_output_points_to_raw_packet(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_load_recent_market_packet_paths", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_default_watchlist_paths", lambda: [])
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "ORCL": {"current_price": "225", "previous_close": "220", "volume_ratio": "2.0", "tradable": True},
        },
    )
    monkeypatch.setattr(
        cli_main,
        "build_overnight_candidate_universe",
        lambda **_kwargs: [
            {"symbol": "ORCL", "sources": ["base_universe"], "owned": False, "research_weight": "equal"},
        ],
    )

    monkeypatch.setattr(
        cli_main,
        "_run_overnight_ticker_analysis_guarded",
        lambda **kwargs: {
            "symbol": kwargs["symbol"],
            "status": "ok",
            "rating": "Buy",
            "score": "0.90",
            "signal": "BUY",
            "final_trade_decision": "Rating: Buy",
            "reports": {"market": "large report omitted from compact stdout"},
        },
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "plan-overnight",
            "--json-output",
            "--compact-json-output",
            "--log-dir",
            str(tmp_path),
            "--full-graph-tickers",
            "1",
            "--per-ticker-timeout-minutes",
            "0",
            "--overnight-backend-url",
            "https://example.test/v1",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema"] == "compact_overnight_plan_v1"
    assert payload["counts"]["ticker_results"] == 1
    assert payload["ticker_status_counts"] == {"ok": 1}
    raw_packet_path = Path(payload["raw_packet_path"])
    assert raw_packet_path.exists()
    compact_sidecar = raw_packet_path.with_name(f"{raw_packet_path.stem}.compact.json")
    assert compact_sidecar.exists()
    assert json.loads(compact_sidecar.read_text(encoding="utf-8")) == payload
    assert json.loads((tmp_path / "latest-compact.json").read_text(encoding="utf-8")) == payload
    prior_feed = payload["research_context_summary"]["prior_feed"]
    assert prior_feed["schema"] == "overnight_prior_feed_v1"
    assert Path(prior_feed["path"]).exists()
    assert "ticker_results" not in payload
    assert "research_context" not in payload


def test_plan_overnight_full_graph_attempt_uses_rank_tie_breaker(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    calls = []
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {"ADBE": {}, "ORCL": {}})
    monkeypatch.setattr(cli_main, "_latest_supervisor_packets", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_load_recent_market_packet_paths", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_default_watchlist_paths", lambda: [])
    monkeypatch.setattr(
        cli_main,
        "build_candidate_signals",
        lambda _market_data: [
            cli_main.CandidateSignal(symbol="ADBE", score=Decimal("0.95"), current_price=Decimal("1")),
            cli_main.CandidateSignal(symbol="ORCL", score=Decimal("0.95"), current_price=Decimal("1")),
        ],
    )
    monkeypatch.setattr(
        cli_main,
        "build_overnight_candidate_universe",
        lambda **_kwargs: [
            {"symbol": "ADBE", "sources": ["base_universe"], "owned": False, "research_weight": "equal"},
            {"symbol": "ORCL", "sources": ["base_universe"], "owned": False, "research_weight": "equal"},
        ],
    )

    def fake_guarded(**kwargs):
        calls.append(kwargs["symbol"])
        return {
            "symbol": kwargs["symbol"],
            "status": "ok",
            "rating": "Buy",
            "score": "0.90",
            "signal": "BUY",
            "final_trade_decision": "Rating: Buy",
            "reports": {},
        }

    monkeypatch.setattr(cli_main, "_run_overnight_ticker_analysis_guarded", fake_guarded)

    result = runner.invoke(
        app,
        [
            "alpaca",
            "plan-overnight",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--full-graph-tickers",
            "1",
            "--per-ticker-timeout-minutes",
            "0",
            "--overnight-backend-url",
            "https://example.test/v1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == ["ORCL"]


def test_plan_overnight_passes_overnight_graph_config_to_guarded(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    captured = {}
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {})
    monkeypatch.setattr(cli_main, "_latest_supervisor_packets", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_load_recent_market_packet_paths", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_default_watchlist_paths", lambda: [])
    monkeypatch.setattr(
        cli_main,
        "build_overnight_candidate_universe",
        lambda **_kwargs: [
            {"symbol": "MSFT", "sources": ["base_universe"], "owned": False, "research_weight": "equal"},
        ],
    )

    def fake_guarded(**kwargs):
        captured.update(kwargs)
        return {
            "symbol": kwargs["symbol"],
            "status": "ok",
            "rating": "Buy",
            "score": "0.90",
            "signal": "BUY",
            "final_trade_decision": "Rating: Buy",
            "reports": {},
        }

    monkeypatch.setattr(cli_main, "_run_overnight_ticker_analysis_guarded", fake_guarded)

    result = runner.invoke(
        app,
        [
            "alpaca",
            "plan-overnight",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--full-graph-tickers",
            "1",
            "--per-ticker-timeout-minutes",
            "0",
            "--overnight-graph-profile",
            "compact",
            "--overnight-llm-provider",
            "openai",
            "--overnight-quick-think-llm",
            "gpt-5.4-mini",
            "--overnight-deep-think-llm",
            "gpt-5.4",
            "--overnight-backend-url",
            "https://example.test/v1",
            "--overnight-max-completion-tokens",
            "220",
            "--overnight-llm-timeout-seconds",
            "45",
            "--overnight-llm-max-retries",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["graph_config_overrides"] == {
        "overnight_graph_profile": "compact",
        "_selected_analysts": ["market", "social", "news", "fundamentals"],
        "tool_free_analysts": ["market", "social", "news", "fundamentals"],
        "analyst_concurrency_limit": 2,
        "max_debate_rounds": 0,
        "max_risk_discuss_rounds": 0,
        "max_recur_limit": 100,
        "news_article_limit": 5,
        "global_news_article_limit": 3,
        "global_news_lookback_days": 3,
        "global_news_queries": [
            "Federal Reserve interest rates inflation",
            "S&P 500 Nasdaq earnings AI stocks",
            "geopolitical risk oil commodities",
        ],
        "overnight_model_route": "explicit_openai_overnight_graph",
        "llm_provider": "openai",
        "quick_think_llm": "gpt-5.4-mini",
        "deep_think_llm": "gpt-5.4",
        "backend_url": "https://example.test/v1",
        "llm_max_output_tokens": 220,
        "ollama_max_completion_tokens": 220,
        "llm_timeout_seconds": 45.0,
        "llm_max_retries": 1,
    }
    payload = json.loads(result.stdout)
    assert payload["overnight_quality"]["graph_config"]["graph_profile"] == "compact"
    assert payload["overnight_quality"]["graph_config"]["tool_free_analysts"] == [
        "market",
        "social",
        "news",
        "fundamentals",
    ]
    assert payload["overnight_quality"]["graph_config"]["max_debate_rounds"] == 0
    assert payload["overnight_quality"]["graph_config"]["analyst_concurrency_limit"] == 2
    assert payload["overnight_quality"]["graph_config"]["llm_provider"] == "openai"
    assert payload["overnight_quality"]["graph_config"]["max_completion_tokens"] == 220
    assert payload["overnight_quality"]["graph_config"]["max_output_tokens"] == 220
    assert payload["overnight_quality"]["graph_config"]["llm_timeout_seconds"] == 45.0
    assert payload["overnight_quality"]["graph_config"]["llm_max_retries"] == 1
    assert payload["overnight_quality"]["graph_config"]["quick_context_window_tokens"] == 1_000_000
    assert payload["overnight_quality"]["graph_config"]["deep_context_window_tokens"] == 1_000_000
    assert payload["original_tradingagents_graph"]["bounds"]["graph_profile"] == "compact"
    assert payload["original_tradingagents_graph"]["bounds"]["max_completion_tokens"] == 220
    assert payload["original_tradingagents_graph"]["bounds"]["max_output_tokens"] == 220
    assert payload["original_tradingagents_graph"]["bounds"]["llm_timeout_seconds"] == 45.0
    assert payload["original_tradingagents_graph"]["bounds"]["llm_max_retries"] == 1


def test_overnight_graph_config_uses_mac_helper_metadata_when_windows_is_down(monkeypatch):
    for env_name in (
        "TRADINGAGENTS_OVERNIGHT_LLM_PROVIDER",
        "TRADINGAGENTS_OVERNIGHT_QUICK_THINK_LLM",
        "TRADINGAGENTS_OVERNIGHT_DEEP_THINK_LLM",
        "TRADINGAGENTS_OVERNIGHT_LLM_BACKEND_URL",
        "TRADINGAGENTS_WINDOWS_OLLAMA_URL",
        "TRADINGAGENTS_LOCAL_OLLAMA_URL",
        "TRADINGAGENTS_LOCAL_MODEL_URL",
        "OLLAMA_BASE_URL",
        "OLLAMA_HOST",
        "TRADINGAGENTS_MAC_RESEARCH_MODEL",
    ):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(
        cli_main,
        "_ollama_endpoint_healthy",
        lambda endpoint: "macbook-pro.tail37edd7.ts.net" in endpoint,
    )

    overrides = cli_main._build_overnight_graph_config_overrides(
        graph_profile="compact",
        llm_provider=None,
        quick_think_llm=None,
        deep_think_llm=None,
        backend_url=None,
        max_completion_tokens=220,
    )

    assert "llm_provider" not in overrides
    assert "quick_think_llm" not in overrides
    assert "deep_think_llm" not in overrides
    assert "backend_url" not in overrides
    assert overrides["overnight_model_route"] == "deterministic_fallback_with_mac_helper"
    assert overrides["overnight_helper_route"] == "mac_ollama_research_mule"
    assert overrides["overnight_helper_model"] == "deepseek-r1:14b"
    assert overrides["overnight_helper_backend_url"] == "http://macbook-pro.tail37edd7.ts.net:11434/v1"
    assert "Full graph is skipped" in overrides["overnight_graph_disabled_reason"]


def test_overnight_graph_config_keeps_explicit_backend_over_auto_route(monkeypatch):
    monkeypatch.setattr(
        cli_main,
        "_ollama_endpoint_healthy",
        lambda _endpoint: (_ for _ in ()).throw(AssertionError("explicit config should not probe")),
    )

    overrides = cli_main._build_overnight_graph_config_overrides(
        graph_profile="compact",
        llm_provider="openai",
        quick_think_llm="gpt-5.4-mini",
        deep_think_llm="gpt-5.4",
        backend_url="https://example.test/v1",
        max_completion_tokens=220,
    )

    assert overrides["llm_provider"] == "openai"
    assert overrides["quick_think_llm"] == "gpt-5.4-mini"
    assert overrides["deep_think_llm"] == "gpt-5.4"
    assert overrides["backend_url"] == "https://example.test/v1"


def test_overnight_graph_config_honors_explicit_openai_without_backend(monkeypatch):
    monkeypatch.setattr(
        cli_main,
        "_ollama_endpoint_healthy",
        lambda _endpoint: (_ for _ in ()).throw(
            AssertionError("non-Ollama provider should not probe local Ollama")
        ),
    )

    overrides = cli_main._build_overnight_graph_config_overrides(
        graph_profile="compact",
        llm_provider="openai",
        quick_think_llm="gpt-5.4-mini",
        deep_think_llm="gpt-5.4",
        backend_url=None,
        max_completion_tokens=220,
    )

    assert overrides["llm_provider"] == "openai"
    assert overrides["quick_think_llm"] == "gpt-5.4-mini"
    assert overrides["deep_think_llm"] == "gpt-5.4"
    assert overrides["backend_url"] is None
    assert "overnight_graph_disabled_reason" not in overrides
    assert overrides["overnight_model_route"] == "explicit_openai_overnight_graph"


def test_plan_overnight_runs_explicit_openai_graph_without_backend(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    captured = {}
    monkeypatch.setattr(
        cli_main,
        "_ollama_endpoint_healthy",
        lambda _endpoint: (_ for _ in ()).throw(
            AssertionError("non-Ollama provider should not probe local Ollama")
        ),
    )
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "_fetch_aggressive_candidate_market_data", lambda: {})
    monkeypatch.setattr(cli_main, "_latest_supervisor_packets", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_load_recent_market_packet_paths", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_default_watchlist_paths", lambda: [])
    monkeypatch.setattr(
        cli_main,
        "build_overnight_candidate_universe",
        lambda **_kwargs: [
            {"symbol": "MSFT", "sources": ["base_universe"], "owned": False, "research_weight": "equal"},
        ],
    )

    def fake_guarded(**kwargs):
        captured.update(kwargs)
        return {
            "symbol": kwargs["symbol"],
            "status": "ok",
            "rating": "Buy",
            "score": "0.90",
            "signal": "BUY",
            "final_trade_decision": "Rating: Buy",
            "reports": {},
        }

    monkeypatch.setattr(cli_main, "_run_overnight_ticker_analysis_guarded", fake_guarded)

    result = runner.invoke(
        app,
        [
            "alpaca",
            "plan-overnight",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--full-graph-tickers",
            "1",
            "--per-ticker-timeout-minutes",
            "0",
            "--overnight-graph-profile",
            "compact",
            "--overnight-llm-provider",
            "openai",
            "--overnight-quick-think-llm",
            "gpt-5.4-mini",
            "--overnight-deep-think-llm",
            "gpt-5.4",
            "--overnight-max-completion-tokens",
            "220",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["symbol"] == "MSFT"
    payload = json.loads(result.stdout)
    quality = payload["overnight_quality"]
    assert quality["full_graph_limit"] == 1
    assert quality["full_graph_count"] == 1
    assert quality["full_graph_attempt_count"] == 1
    assert quality["full_graph_success_count"] == 1
    assert quality["graph_disabled_reason"] is None
    assert quality["graph_config"]["llm_provider"] == "openai"
    assert quality["graph_config"]["backend_url"] is None
    assert quality["graph_config"]["model_route"] == "explicit_openai_overnight_graph"
    assert quality["graph_config"]["analyst_concurrency_limit"] == 2


def test_plan_overnight_disables_full_graph_when_only_mac_helper_is_healthy(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    for env_name in (
        "TRADINGAGENTS_OVERNIGHT_LLM_PROVIDER",
        "TRADINGAGENTS_OVERNIGHT_QUICK_THINK_LLM",
        "TRADINGAGENTS_OVERNIGHT_DEEP_THINK_LLM",
        "TRADINGAGENTS_OVERNIGHT_LLM_BACKEND_URL",
        "TRADINGAGENTS_WINDOWS_OLLAMA_URL",
        "TRADINGAGENTS_LOCAL_OLLAMA_URL",
        "TRADINGAGENTS_LOCAL_MODEL_URL",
        "OLLAMA_BASE_URL",
        "OLLAMA_HOST",
        "TRADINGAGENTS_MAC_RESEARCH_MODEL",
    ):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(
        cli_main,
        "_ollama_endpoint_healthy",
        lambda endpoint: "macbook-pro.tail37edd7.ts.net" in endpoint,
    )
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {"ORCL": {"current_price": "225", "previous_close": "220", "volume_ratio": "2.0", "tradable": True}},
    )
    monkeypatch.setattr(cli_main, "_latest_supervisor_packets", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_load_recent_market_packet_paths", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cli_main, "_default_watchlist_paths", lambda: [])
    monkeypatch.setattr(
        cli_main,
        "build_overnight_candidate_universe",
        lambda **_kwargs: [
            {"symbol": "ORCL", "sources": ["base_universe"], "owned": False, "research_weight": "equal"},
        ],
    )
    monkeypatch.setattr(
        cli_main,
        "_run_overnight_ticker_analysis_guarded",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("graph worker should be skipped")),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "plan-overnight",
            "--json-output",
            "--log-dir",
            str(tmp_path),
            "--full-graph-tickers",
            "3",
            "--per-ticker-timeout-minutes",
            "0",
            "--overnight-graph-profile",
            "compact",
            "--overnight-max-completion-tokens",
            "220",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    quality = payload["overnight_quality"]
    assert quality["requested_full_graph_limit"] == 3
    assert quality["full_graph_limit"] == 0
    assert quality["full_graph_count"] == 0
    assert quality["full_graph_success_count"] == 0
    assert quality["graph_failure_count"] == 0
    assert quality["completion_status"] == "disabled"
    assert "Full graph is skipped" in quality["graph_disabled_reason"]
    assert quality["graph_config"]["model_route"] == "deterministic_fallback_with_mac_helper"
    assert quality["graph_config"]["llm_provider"] == "none"
    assert quality["graph_config"]["backend_url"] is None
    assert quality["graph_config"]["helper_model"] == "deepseek-r1:14b"
    assert quality["graph_config"]["analyst_concurrency_limit"] == 2


def test_preopen_supervisor_includes_overnight_validation(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    overnight_dir = tmp_path / "overnight"
    overnight_dir.mkdir()
    (overnight_dir / "overnight-plan-20260530-003000.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-30T00:30:00+00:00",
                "analysis_only": True,
                "ranked_candidates": [{"symbol": "ORCL", "score": "0.90"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "pre_open")
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {"ORCL": {"current_price": "225", "previous_close": "220", "volume_ratio": "2.0", "tradable": True}},
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 5, 30, 12, 0, tzinfo=datetime.timezone.utc),
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
            "--execution-board-dir",
            str(tmp_path / "empty_board"),
            "--overnight-log-dir",
            str(overnight_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["evidence"]["overnight_plan"]["status"] == "confirmed"
    assert payload["evidence"]["overnight_plan"]["overnight_top_symbol"] == "ORCL"


def test_premarket_brief_command_is_file_only(monkeypatch, tmp_path):
    hourly_dir = tmp_path / "hourly"
    overnight_dir = tmp_path / "overnight"
    tournament_dir = tmp_path / "tournament"
    brief_dir = tmp_path / "briefs"
    hourly_dir.mkdir()
    overnight_dir.mkdir()
    tournament_dir.mkdir()
    (hourly_dir / "hourly-supervisor-20260601-010000.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T01:00:00+00:00",
                "decision": "hold",
                "reason": "quiet check",
                "submitted": [],
                "issues": [],
                "portfolio": {"ranked_candidates": [{"symbol": "ORCL", "score": "0.90"}]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_clients",
        lambda: (_ for _ in ()).throw(AssertionError("premarket brief must not create Alpaca clients")),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "premarket-brief",
            "--json-output",
            "--log-dir",
            str(brief_dir),
            "--hourly-log-dir",
            str(hourly_dir),
            "--overnight-log-dir",
            str(overnight_dir),
            "--paper-tournament-log-dir",
            str(tournament_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["packet_path"].endswith(".json")
    assert payload["source_packets"][0]["kind"] == "hourly_supervisor"
    assert (brief_dir / "latest.json").exists()


def test_compact_premarket_brief_payload_points_to_raw_packet():
    raw_path = Path("results/premarket_briefs/example.json")
    compact = cli_main._compact_premarket_brief_payload(
        {
            "generated_at": "2026-06-04T10:00:00+00:00",
            "analysis_only": True,
            "source_packets": [{"kind": "hourly_supervisor"}],
            "timeline": [{"kind": "hourly_supervisor"}],
            "unresolved_blockers": [],
            "control_plane_locks": [{"summary": "expected live lock"}],
            "historical_blockers": [],
            "stale_warnings": ["No overnight plan packet was found for the rolling premarket brief."],
            "material_changes": [{"field": "top_symbol"}],
            "premarket_instructions": {
                "summary": "Use this rolling brief as context only; validate fresh quotes, news, orders, and account state before any live action.",
                "top_symbol": "ORCL",
                "latest_hourly_decision": "hold",
                "latest_overnight_generated_at": None,
                "paper_tournament_leader": "pullback_support",
                "current_control_lock": "expected live lock",
                "must_validate_fresh": [
                    "premarket quotes and spreads",
                    "overnight and morning news/social deltas",
                    "open live and paper orders",
                ],
            },
        },
        raw_path,
    )

    assert compact["schema"] == "compact_premarket_brief_v1"
    assert compact["raw_packet_path"] == str(raw_path)
    assert compact["counts"]["source_packets"] == 1
    assert compact["counts"]["control_plane_locks"] == 1
    assert compact["premarket_instructions"]["top_symbol"] == "ORCL"
    assert compact["premarket_instructions"]["summary"].startswith(
        "Use this rolling brief as context only"
    )
    assert compact["premarket_instructions"]["must_validate_fresh"] == [
        "premarket quotes and spreads",
        "overnight and morning news/social deltas",
        "open live and paper orders",
    ]
    assert "source_packets" not in compact
    assert "timeline" not in compact
    assert "source_packets" in compact["raw_field_groups"]


def test_compact_hourly_supervisor_payload_points_to_raw_packet():
    raw_path = Path("results/hourly_supervisor/example.json")
    compact = cli_main._compact_hourly_supervisor_payload(
        {
            "generated_at": "2026-06-04T14:30:00+00:00",
            "decision": "paper-first",
            "material": True,
            "reason": "strong dip candidate, paper-first gate",
            "actions": [
                {
                    "action": "buy",
                    "symbol": "NVDA",
                    "side": "buy",
                    "account": "paper",
                    "execution_mode": "paper_first",
                    "sleeve": "pullback_support",
                }
            ],
            "issues": [{"ticket_id": "stale-source", "reason": "refresh required"}],
            "submitted": [],
            "alert": {"severity": "NOTABLE", "notify": False, "email_suppressed": True},
            "evidence": {
                "live_budget": {
                    "mode": "invalid_or_retired",
                    "repo_dollar_cap_active": False,
                    "plain_english": "broker gates apply",
                },
                "risk_posture": {
                    "name": "balanced",
                    "paper_first_threshold": "0.75",
                    "live_gate_relaxation_allowed": False,
                },
                "overnight_plan": {
                    "status": "confirmed",
                    "overnight_top_symbol": "NVDA",
                    "json_path": "results/overnight_plans/latest.json",
                },
                "execution_board_review": {
                    "recommendation": "continue",
                    "new_buys_suspended": False,
                    "json_path": "results/execution_board/latest.json",
                },
            },
            "portfolio": {
                "market_session": "regular",
                "live": {
                    "status": "ACTIVE",
                    "equity": "1000.00",
                    "buying_power": "500.00",
                    "cash": "500.00",
                    "exposure": "200.00",
                    "dynamic_cap": "1000.00",
                    "unrealized_pl": "12.50",
                    "positions": [{"symbol": "GOOGL"}],
                    "open_orders": [],
                },
                "paper": {
                    "status": "ACTIVE",
                    "equity": "100000.00",
                    "buying_power": "50000.00",
                    "unrealized_pl": "120.00",
                    "positions": [],
                    "open_orders": [{"symbol": "NVDA"}],
                },
                "ranked_candidates": [
                    {
                        "symbol": "NVDA",
                        "score": "0.87",
                        "day_change_pct": "-1.50",
                        "time_sensitive": True,
                        "source": "aggressive",
                    }
                ],
            },
        },
        raw_path,
    )

    assert compact["schema"] == "compact_hourly_supervisor_v1"
    assert compact["raw_packet_path"] == str(raw_path)
    assert compact["submitted_count"] == 0
    assert compact["issue_count"] == 1
    assert compact["action_summary"]["order_action_count"] == 1
    assert compact["portfolio_summary"]["live"]["position_count"] == 1
    assert compact["portfolio_summary"]["paper"]["open_order_count"] == 1
    assert compact["top_candidate"]["symbol"] == "NVDA"
    assert compact["context_summary"]["overnight_plan"]["status"] == "confirmed"
    assert compact["live_budget"]["mode"] == "invalid_or_retired"
    assert "portfolio" not in compact
    assert "evidence" not in compact
    assert "portfolio" in compact["raw_field_groups"]


def test_compact_supervisor_daily_report_payload_points_to_raw_packet():
    raw_path = Path("results/daily_reports/example.json")
    packet = {
        "generated_at": "2026-06-04T22:00:00+00:00",
        "email_to": "nebulazer2003@gmail.com",
        "subject": "TradingAgents Daily Market Supervisor Report",
        "body": "Daily report\nLive equity: $1,000.00\nNo blockers.",
        "packet_count": 3,
        "material_count": 1,
        "portfolio": {
            "live": {
                "status": "ACTIVE",
                "equity": "1000.00",
                "buying_power": "500.00",
                "cash": "500.00",
                "exposure": "200.00",
                "unrealized_pl": "12.50",
                "positions": [{"symbol": "GOOGL"}],
                "open_orders": [],
            },
            "paper": {
                "status": "ACTIVE",
                "equity": "100000.00",
                "buying_power": "50000.00",
                "unrealized_pl": "120.00",
                "positions": [],
                "open_orders": [{"symbol": "NVDA"}],
            },
            "ranked_candidates": [{"symbol": "NVDA", "score": "0.87", "day_change_pct": "-1.50"}],
        },
        "paper_tournament": {
            "rankings": [{"strategy_id": "pullback_support", "total_return": "12.00"}],
            "live_strategy_candidate": {"status": "candidate", "strategy_id": "pullback_support"},
        },
        "premarket_brief": {
            "generated_at": "2026-06-04T10:00:00+00:00",
            "premarket_instructions": {"top_symbol": "NVDA"},
            "source_packets": [{}, {}],
        },
        "premarket_brief_status": {"status": "confirmed"},
        "premarket_brief_path": "results/premarket_briefs/latest.json",
        "model_telemetry_report": {
            "status": "ok",
            "packet_count": 2,
            "pending_count": 1,
            "auto_upgrade_allowed": False,
        },
        "execution_board_review": {
            "recommendation": "continue",
            "generated_at": "2026-06-04T20:00:00+00:00",
            "can_submit_orders": False,
        },
    }
    compact = cli_main._compact_supervisor_daily_report_payload(packet, raw_path)

    assert compact == supervisor_daily_report.compact_supervisor_daily_report_payload(packet, raw_path)
    assert compact["schema"] == "compact_supervisor_daily_report_v1"
    assert compact["raw_packet_path"] == str(raw_path)
    assert compact["body_summary"]["line_count"] == 3
    assert compact["counts"]["hourly_packets"] == 3
    assert compact["portfolio_summary"]["live"]["position_count"] == 1
    assert compact["top_candidate"]["symbol"] == "NVDA"
    assert compact["context_summary"]["paper_tournament"]["leader"] == "pullback_support"
    assert compact["context_summary"]["premarket_brief"]["source_packet_count"] == 2
    assert compact["context_summary"]["model_telemetry"]["status"] == "ok"
    assert compact["context_summary"]["execution_board"]["recommendation"] == "continue"
    assert "body" not in compact
    assert "portfolio" not in compact
    assert "body" in compact["raw_field_groups"]


def test_compact_output_audit_measures_packet_families(tmp_path):
    hourly_dir = tmp_path / "hourly"
    overnight_dir = tmp_path / "overnight"
    premarket_dir = tmp_path / "premarket"
    daily_dir = tmp_path / "daily"
    automation_health_dir = tmp_path / "automation_health"
    output_dir = tmp_path / "audit"
    for directory in (hourly_dir, overnight_dir, premarket_dir, daily_dir, automation_health_dir):
        directory.mkdir()
    bulky_text = "full raw field retained in packet only " * 80
    (hourly_dir / "hourly-supervisor-20260604-200000.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-04T20:00:00+00:00",
                "decision": "hold",
                "material": False,
                "reason": "quiet",
                "actions": [],
                "issues": [],
                "submitted": [],
                "alert": {"severity": "ROUTINE", "notify": False},
                "alert_email": bulky_text,
                "evidence": {
                    "live_budget": {"mode": "invalid_or_retired"},
                    "risk_posture": {"name": "balanced"},
                },
                "portfolio": {
                    "market_session": "regular",
                    "live": {"positions": [{"symbol": "GOOGL"}], "open_orders": []},
                    "paper": {"positions": [], "open_orders": []},
                    "ranked_candidates": [{"symbol": "NVDA", "score": "0.90"}],
                },
            }
        ),
        encoding="utf-8",
    )
    (overnight_dir / "latest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-04T02:30:00+00:00",
                "candidate_universe": [{"symbol": "NVDA"}],
                "tradable_universe": [{"symbol": "NVDA"}],
                "ranked_candidates": [{"symbol": "NVDA", "rating": "Buy", "score": "0.90"}],
                "ticker_results": [{"symbol": "NVDA", "status": "ok", "reports": {"market": bulky_text}}],
                "research_context": {"packet_count": 1, "blocked_packets": [], "stale_warnings": []},
                "overnight_quality": {"full_graph_count": 1},
                "submitted": [],
            }
        ),
        encoding="utf-8",
    )
    (premarket_dir / "latest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-04T10:00:00+00:00",
                "source_packets": [{"kind": "hourly_supervisor", "body": bulky_text}],
                "timeline": [{"kind": "hourly_supervisor", "body": bulky_text}],
                "unresolved_blockers": [],
                "control_plane_locks": [],
                "historical_blockers": [],
                "stale_warnings": [],
                "material_changes": [],
                "premarket_instructions": {"top_symbol": "NVDA"},
            }
        ),
        encoding="utf-8",
    )
    (daily_dir / "latest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-04T22:00:00+00:00",
                "email_to": "nebulazer2003@gmail.com",
                "subject": "TradingAgents Daily Market Supervisor Report",
                "body": bulky_text,
                "packet_count": 1,
                "material_count": 0,
                "portfolio": {
                    "live": {"positions": [{"symbol": "GOOGL"}], "open_orders": []},
                    "paper": {"positions": [], "open_orders": []},
                    "ranked_candidates": [{"symbol": "NVDA", "score": "0.90"}],
                },
            }
        ),
        encoding="utf-8",
    )
    (automation_health_dir / "latest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-04T22:15:00+00:00",
                "analysis_only": True,
                "can_submit_orders": False,
                "automation_count": 2,
                "submitted_order_count": 0,
                "issue_count": 0,
                "summary": {
                    "ok_count": 1,
                    "missing_count": 0,
                    "partial_count": 1,
                    "late_count": 0,
                    "duplicate_count": 0,
                    "stale_count": 0,
                    "warning_count": 0,
                    "timeliness_issue_count": 0,
                },
                "automations": [
                    {"automation_id": "hourly-market-supervisor", "status": "ok"},
                    {"automation_id": "tradingagents-night-shift-supervisor", "status": "partial"},
                ],
                "recommended_next_step": bulky_text,
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "compact-output-audit",
            "--json-output",
            "--output-dir",
            str(output_dir),
            "--hourly-log-dir",
            str(hourly_dir),
            "--overnight-log-dir",
            str(overnight_dir),
            "--premarket-brief-log-dir",
            str(premarket_dir),
            "--daily-report-log-dir",
            str(daily_dir),
            "--automation-health-dir",
            str(automation_health_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["measured_count"] == 5
    assert payload["row_count"] == 5
    assert payload["total_byte_reduction"] > 0
    assert all(row["lossless_by_reference"] for row in payload["rows"])
    assert {row["label"] for row in payload["rows"]} >= {"automation_health_audit"}
    assert (output_dir / "latest.json").exists()
    assert (output_dir / "latest.md").exists()


def test_compact_output_audit_finds_nested_daily_report_packets(tmp_path):
    daily_dir = tmp_path / "daily_reports"
    nested_daily_dir = daily_dir / "n8n"
    output_dir = tmp_path / "token_efficiency"
    nested_daily_dir.mkdir(parents=True)
    packet_path = nested_daily_dir / "supervisor-daily-report-20260604-000811.json"
    packet_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-04T22:00:00+00:00",
                "email_to": "nebulazer2003@gmail.com",
                "subject": "TradingAgents Daily Market Supervisor Report",
                "body": "Line 1\nLine 2\n" + ("daily report detail\n" * 200),
                "packet_count": 2,
                "material_count": 1,
                "portfolio": {
                    "live": {
                        "status": "ok",
                        "positions": [{"symbol": "GOOGL"}],
                        "open_orders": [],
                    },
                    "paper": {"positions": [], "open_orders": []},
                    "ranked_candidates": [{"symbol": "NVDA", "score": "0.90"}],
                },
                "execution_board_review": {
                    "recommendation": "hold",
                    "can_submit_orders": False,
                },
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "compact-output-audit",
            "--json-output",
            "--output-dir",
            str(output_dir),
            "--hourly-log-dir",
            str(tmp_path / "missing_hourly"),
            "--overnight-log-dir",
            str(tmp_path / "missing_overnight"),
            "--premarket-brief-log-dir",
            str(tmp_path / "missing_premarket"),
            "--daily-report-log-dir",
            str(daily_dir),
            "--automation-health-dir",
            str(tmp_path / "missing_automation_health"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    daily_row = next(
        row for row in payload["rows"] if row["label"] == "supervisor_daily_report"
    )

    assert payload["measured_count"] == 1
    assert daily_row["status"] == "measured"
    assert daily_row["raw_packet_path"] == str(packet_path)
    assert daily_row["schema"] == "compact_supervisor_daily_report_v1"
    assert daily_row["lossless_by_reference"] is True
    assert daily_row["byte_reduction"] > 0


def test_premarket_brief_compact_json_output_is_file_only(monkeypatch, tmp_path):
    hourly_dir = tmp_path / "hourly"
    overnight_dir = tmp_path / "overnight"
    tournament_dir = tmp_path / "tournament"
    brief_dir = tmp_path / "briefs"
    hourly_dir.mkdir()
    overnight_dir.mkdir()
    tournament_dir.mkdir()
    (hourly_dir / "hourly-supervisor-20260601-010000.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T01:00:00+00:00",
                "decision": "hold",
                "reason": "quiet check",
                "submitted": [],
                "issues": [],
                "portfolio": {"ranked_candidates": [{"symbol": "ORCL", "score": "0.90"}]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_clients",
        lambda: (_ for _ in ()).throw(AssertionError("premarket brief must not create Alpaca clients")),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "premarket-brief",
            "--json-output",
            "--compact-json-output",
            "--log-dir",
            str(brief_dir),
            "--hourly-log-dir",
            str(hourly_dir),
            "--overnight-log-dir",
            str(overnight_dir),
            "--paper-tournament-log-dir",
            str(tournament_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema"] == "compact_premarket_brief_v1"
    assert payload["raw_packet_path"].endswith(".json")
    assert payload["counts"]["source_packets"] == 1
    assert payload["premarket_instructions"]["top_symbol"] == "ORCL"
    assert Path(payload["raw_packet_path"]).exists()
    assert "source_packets" not in payload
    assert "timeline" not in payload


def test_preopen_validation_writes_fresh_analysis_only_packet(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    brief_dir = tmp_path / "briefs"
    overnight_dir = tmp_path / "overnight"
    output_dir = tmp_path / "preopen"
    brief_dir.mkdir()
    overnight_dir.mkdir()
    generated_at = "2026-06-01T13:00:00+00:00"
    premarket_packet = {
        "generated_at": generated_at,
        "analysis_only": True,
        "source_packets": [{"kind": "overnight_plan", "path": str(overnight_dir / "latest.json")}],
        "timeline": [],
        "unresolved_blockers": [],
        "stale_warnings": [],
        "premarket_instructions": _premarket_instructions("ORCL"),
    }
    _write_verify_premarket_fixture(brief_dir, premarket_packet)
    (overnight_dir / "latest.json").write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                "analysis_only": True,
                "ranked_candidates": [{"symbol": "ORCL", "score": "0.90"}],
                "ticker_results": [{"symbol": "ORCL", "status": "ok"}],
                "submitted": [],
            }
        ),
        encoding="utf-8",
    )
    live_control_path = tmp_path / "policy" / "live_control.json"
    risk_envelope_path = tmp_path / "risk_envelope.yaml"
    _write_test_live_control(live_control_path, "2026-06-01T20:00:00+00:00")
    _write_test_risk_envelope(risk_envelope_path)
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 1, 13, 10, tzinfo=datetime.timezone.utc),
    )
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "ORCL": {
                "current_price": "100.00",
                "previous_close": "101.00",
                "volume_ratio": "1.4",
                "tradable": True,
                "quote_fresh": True,
                "stale_quote": False,
                "source": "alpaca_market_data:latest_trade",
            }
        },
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "preopen-validation",
            "--json-output",
            "--compact-json-output",
            "--log-dir",
            str(output_dir),
            "--premarket-brief-log-dir",
            str(brief_dir),
            "--overnight-log-dir",
            str(overnight_dir),
            "--live-control-path",
            str(live_control_path),
            "--risk-envelope-path",
            str(risk_envelope_path),
        ],
    )

    assert result.exit_code == 0, result.output
    compact = json.loads(result.stdout)
    assert compact["schema"] == "compact_preopen_validation_v1"
    assert compact["analysis_only"] is True
    assert compact["can_submit_orders"] is False
    assert compact["execution_authority"] == "none"
    assert compact["overall_status"] == "pass"
    assert compact["top_symbol"] == "ORCL"
    assert compact["failed_check_ids"] == []
    assert compact["warned_check_ids"] == []
    assert compact["account_summary"]["live"]["buying_power"] == "100"
    assert Path(compact["raw_packet_path"]).exists()
    raw = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))
    assert raw["submitted_count"] == 0
    assert {check["id"]: check["status"] for check in raw["checks"]} == {
        "premarket_quotes_and_spreads": "pass",
        "overnight_and_morning_news_social_deltas": "pass",
        "open_live_and_paper_orders": "pass",
        "current_positions_and_pl": "pass",
        "live_sizing_room_and_buying_power": "pass",
    }


def test_preopen_validation_warns_when_live_control_expired(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    brief_dir = tmp_path / "briefs"
    overnight_dir = tmp_path / "overnight"
    output_dir = tmp_path / "preopen"
    brief_dir.mkdir()
    overnight_dir.mkdir()
    generated_at = "2026-06-01T13:00:00+00:00"
    _write_verify_premarket_fixture(
        brief_dir,
        {
            "generated_at": generated_at,
            "analysis_only": True,
            "source_packets": [{"kind": "overnight_plan"}],
            "timeline": [],
            "unresolved_blockers": [],
            "stale_warnings": [],
            "premarket_instructions": _premarket_instructions("ORCL"),
        },
    )
    (overnight_dir / "latest.json").write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                "analysis_only": True,
                "ranked_candidates": [{"symbol": "ORCL", "score": "0.90"}],
                "ticker_results": [{"symbol": "ORCL", "status": "ok"}],
                "submitted": [],
            }
        ),
        encoding="utf-8",
    )
    live_control_path = tmp_path / "policy" / "live_control.json"
    risk_envelope_path = tmp_path / "risk_envelope.yaml"
    _write_test_live_control(live_control_path, "2026-06-01T12:00:00+00:00")
    _write_test_risk_envelope(risk_envelope_path)
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 1, 13, 10, tzinfo=datetime.timezone.utc),
    )
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "ORCL": {
                "current_price": "100.00",
                "previous_close": "101.00",
                "volume_ratio": "1.4",
                "tradable": True,
                "quote_fresh": True,
                "stale_quote": False,
                "source": "alpaca_market_data:latest_trade",
            }
        },
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "preopen-validation",
            "--json-output",
            "--log-dir",
            str(output_dir),
            "--premarket-brief-log-dir",
            str(brief_dir),
            "--overnight-log-dir",
            str(overnight_dir),
            "--live-control-path",
            str(live_control_path),
            "--risk-envelope-path",
            str(risk_envelope_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "pass_with_warnings"
    sizing_check = next(
        check
        for check in payload["checks"]
        if check["id"] == "live_sizing_room_and_buying_power"
    )
    assert sizing_check["status"] == "warn"
    assert "dead-man expired" in sizing_check["evidence"]["live_control_issues"][0]
    assert payload["failed_check_ids"] == []
    assert payload["warned_check_ids"] == ["live_sizing_room_and_buying_power"]


def test_preopen_supervisor_includes_premarket_brief_validation(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    brief_dir = tmp_path / "briefs"
    brief_dir.mkdir()
    (brief_dir / "latest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T10:00:00+00:00",
                "analysis_only": True,
                "source_packets": [{"kind": "hourly_supervisor"}],
                "premarket_instructions": {
                    "top_symbol": "ORCL",
                    "latest_research_context": {
                        "packet_count": 8,
                        "blocked_count": 0,
                        "prior_feed": {
                            "schema": "overnight_prior_feed_v1",
                            "path": "results/overnight_plans/research_context/overnight-prior-feed-20260601-003000.json",
                            "packet_count": 8,
                            "blocked_count": 0,
                            "analysis_only": True,
                            "execution_authority": "none",
                            "forbidden_effects": ["submit_order"],
                        },
                        "provider_fallback_needs": ["market_news"],
                        "watchlists": ["reddit"],
                        "execution_authority": "none",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "pre_open")
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {"ORCL": {"current_price": "225", "previous_close": "220", "volume_ratio": "2.0", "tradable": True}},
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.timezone.utc),
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
            "--execution-board-dir",
            str(tmp_path / "empty_board"),
            "--premarket-brief-log-dir",
            str(brief_dir),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["evidence"]["premarket_brief"]["status"] == "confirmed"
    assert payload["evidence"]["premarket_brief"]["brief_top_symbol"] == "ORCL"
    prior_feed = payload["evidence"]["premarket_brief"]["latest_research_context"]["prior_feed"]
    assert prior_feed["schema"] == "overnight_prior_feed_v1"
    assert "submit_order" in prior_feed["forbidden_effects"]


def test_preopen_submit_blocks_without_clean_preopen_validation(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    live_client.positions = []
    paper_client.positions = []
    validation_dir = tmp_path / "preopen_validation"
    guard_called = False

    def _guard_should_not_run(**_kwargs):
        nonlocal guard_called
        guard_called = True
        raise AssertionError("tiny-live guard should not run before pre-open validation")

    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "AMZN": {
                "current_price": "196",
                "previous_close": "200",
                "volume_ratio": "2.0",
                "tradable": True,
            }
        },
    )
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "pre_open")
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 1, 12, 5, tzinfo=datetime.timezone.utc),
    )
    monkeypatch.setattr(cli_main, "validate_supervisor_live_submit_allowed", lambda **_: [])
    monkeypatch.setattr(cli_main, "acquire_tiny_live_operational_guard", _guard_should_not_run)

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--submit-actions",
            "--json-output",
            "--log-dir",
            str(tmp_path / "hourly"),
            "--execution-board-dir",
            str(tmp_path / "empty_board"),
            "--preopen-validation-dir",
            str(validation_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["decision"] == "blocked"
    assert payload["reason"] == "hourly supervisor pre-open validation blocked submit"
    assert payload["issues"][0]["ticket_id"] == "preopen-validation"
    assert "missing latest pre-open validation packet" in payload["issues"][0]["reason"]
    assert payload["evidence"]["preopen_validation"]["status"] == "missing"
    assert live_client.submitted == []
    assert paper_client.submitted == []
    assert guard_called is False


def test_preopen_submit_allows_clean_preopen_validation(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    live_client = _FakeCliClient(paper=False)
    live_client.positions = []
    paper_client.positions = []
    validation_dir = tmp_path / "preopen_validation"
    _write_compact_preopen_validation(validation_dir)

    monkeypatch.setattr(cli_main, "_alpaca_clients", lambda: (paper_client, live_client))
    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {
            "AMZN": {
                "current_price": "196",
                "previous_close": "200",
                "volume_ratio": "2.0",
                "tradable": True,
            }
        },
    )
    monkeypatch.setattr(cli_main, "market_session_label", lambda: "pre_open")
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 1, 12, 5, tzinfo=datetime.timezone.utc),
    )
    monkeypatch.setattr(cli_main, "validate_supervisor_live_submit_allowed", lambda **_: [])
    monkeypatch.setattr(
        cli_main,
        "acquire_tiny_live_operational_guard",
        lambda **_: type(
            "Guard",
            (),
            {"allowed": True, "issues": [], "lock": None},
        )(),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "supervise-hourly",
            "--submit-actions",
            "--json-output",
            "--log-dir",
            str(tmp_path / "hourly"),
            "--execution-board-dir",
            str(tmp_path / "empty_board"),
            "--preopen-validation-dir",
            str(validation_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["decision"] == "blocked"
    assert "authorized normal live intent" in payload["reason"]
    assert payload["evidence"]["preopen_validation"]["status"] == "pass"
    assert live_client.submitted == []
    assert paper_client.submitted == []


def test_verify_overnight_system_audits_full_chain(monkeypatch, tmp_path):
    overnight_dir = tmp_path / "overnight"
    brief_dir = tmp_path / "briefs"
    hourly_dir = tmp_path / "hourly"
    tournament_dir = tmp_path / "tournament"
    automation_dir = tmp_path / "automations"
    context_dir = tmp_path / "context"
    verify_dir = tmp_path / "verify"
    for path in (overnight_dir, brief_dir, hourly_dir, tournament_dir, automation_dir, context_dir):
        path.mkdir()

    overnight_path = overnight_dir / "overnight-plan-20260601-010000.json"
    prior_feed_path = overnight_dir / "research_context" / "overnight-prior-feed-20260601-010000.json"
    prior_feed_path.parent.mkdir()
    prior_feed_path.write_text(
        json.dumps(
            {
                "schema": "overnight_prior_feed_v1",
                "generated_at": "2026-06-01T01:00:00+00:00",
                "analysis_only": True,
                "execution_authority": "none",
                "forbidden_effects": ["submit_order", "cancel_order", "promote_strategy"],
                "packet_count": 13,
                "blocked_count": 0,
                "packet_refs": [],
            }
        ),
        encoding="utf-8",
    )
    overnight_packet = {
        "generated_at": "2026-06-01T01:00:00+00:00",
        "analysis_only": True,
        "trade_date": "2026-06-01",
        "packet_path": str(overnight_path),
        "research_context": {
            "packet_count": 13,
            "blocked_count": 0,
            "watchlists": {
                "source_quality": {
                    "status": "available",
                    "review_path": "results/source_quality/latest.json",
                    "source_quality_ordering_enabled": True,
                    "scored_source_count": 3,
                    "source_count": 12,
                    "stale_count": 2,
                    "stale_downrank_count": 2,
                    "stale_needs_refresh_count": 0,
                    "blocked_count": 0,
                    "missing_or_invalid_count": 0,
                    "unreadable_count": 0,
                    "next_action": "use_review_for_downranking",
                    "blocked": False,
                }
            },
            "prior_feed": {
                "schema": "overnight_prior_feed_v1",
                "path": str(prior_feed_path),
                "packet_count": 13,
                "blocked_count": 0,
                "execution_authority": "none",
            },
        },
        "overnight_quality": {
            "full_graph_limit": 3,
            "full_graph_count": 1,
            "fallback_count": 1,
            "graph_failure_count": 0,
            "completion_status": "complete",
            "per_ticker_timeout_minutes": 25,
            "time_budget_minutes": 90,
            "top_provider_bundle_count": 1,
            "top_provider_bundle_symbols": ["ORCL"],
            "top_provider_bundle_gap_count": 0,
            "top_provider_bundle_error_count": 0,
            "top_provider_bundle_missing_non_gap_needs": [],
            "graph_config": {
                "graph_profile": "compact",
                "llm_provider": "ollama",
                "quick_think_llm": "local",
                "deep_think_llm": "local",
                "backend_url": "http://localhost:11434/v1",
                "max_completion_tokens": 220,
            },
        },
        "ranked_candidates": [{"symbol": "ORCL", "score": "0.90"}],
        "ticker_results": [{"symbol": "ORCL", "status": "ok"}],
        "top_provider_bundles": {
            "enabled": True,
            "analysis_only": True,
            "execution_authority": "none",
            "symbols": ["ORCL"],
            "bundle_count": 1,
            "source_packet_count": 7,
            "gap_packet_count": 0,
            "error_count": 0,
            "evidence_needs_without_non_gap_packets": [],
            "symbols_with_missing_non_gap": [],
            "summary_packet_paths": {"ORCL": "results/research_evidence/orcl-summary.json"},
        },
        "submitted": [],
    }
    overnight_path.write_text(json.dumps(overnight_packet), encoding="utf-8")
    (overnight_dir / "latest.json").write_text(json.dumps(overnight_packet), encoding="utf-8")

    brief_packet = {
        "generated_at": "2026-06-01T01:05:00+00:00",
        "analysis_only": True,
        "source_packets": [
            {"kind": "overnight_plan", "path": str(overnight_path), "generated_at": "2026-06-01T01:00:00+00:00"}
        ],
        "timeline": [],
        "unresolved_blockers": [],
        "stale_warnings": [],
        "premarket_instructions": _premarket_instructions("ORCL"),
    }
    _write_verify_premarket_fixture(brief_dir, brief_packet)

    hourly_packet = {
        "generated_at": "2026-06-01T01:06:00+00:00",
        "decision": "blocked",
        "reason": "hourly supervisor live submit failed guard validation",
        "issues": [
            {"ticket_id": "live-submit-guard", "reason": "risk envelope missing"},
            {"ticket_id": "live-submit-guard", "reason": "promotion state missing"},
            {"ticket_id": "live-submit-guard", "reason": "live control state missing"},
            {"ticket_id": "live-submit-guard", "reason": "live action must use tiny_live execution_mode"},
        ],
        "submitted": [],
        "portfolio": {"live": {"open_orders": []}},
        "evidence": {"overnight_plan": {"status": "confirmed", "overnight_top_symbol": "ORCL"}},
    }
    (hourly_dir / "hourly-supervisor-20260601-010600.json").write_text(json.dumps(hourly_packet), encoding="utf-8")

    tournament_packet = {
        "generated_at": "2026-06-01T01:07:00+00:00",
        "submitted_count": 0,
        "report": {
            "rankings": [
                {"strategy_id": "current-aggressive"},
                {"strategy_id": "pullback-support"},
                {"strategy_id": "catalyst-relative-strength"},
            ],
            "live_strategy_candidate": {"status": "pending", "strategy_id": "current-aggressive"},
        },
    }
    (tournament_dir / "latest.json").write_text(json.dumps(tournament_packet), encoding="utf-8")

    automation_specs = {
        "tradingagents-overnight-planning": [
            'status = "ACTIVE"',
            ".venv\\Scripts\\tradingagents.exe",
            "alpaca check",
            "alpaca plan-overnight",
            "--overnight-graph-profile compact",
            "--per-ticker-timeout-minutes 25",
            "--overnight-max-completion-tokens 220",
            "alpaca premarket-brief",
            "must never place live or paper orders",
        ],
        "hourly-market-supervisor": [
            ".venv\\Scripts\\tradingagents.exe",
            "alpaca check",
            "alpaca supervise-hourly --dry-run",
            "--overnight-log-dir results/overnight_plans",
            "--paper-tournament-log-dir results/paper_strategy_tournament",
            "--premarket-brief-log-dir results/premarket_briefs",
        ],
        "paper-strategy-tournament-runner": [
            "paper-tournament run --all",
            "This automation is paper-only",
            "must never place live orders",
        ],
        "tradingagents-daily-market-report": [
            "supervisor-daily-report",
            "--paper-tournament-log-dir results/paper_strategy_tournament",
            "--premarket-brief-log-dir results/premarket_briefs",
            "must never place trades",
        ],
    }
    for automation_id, fragments in automation_specs.items():
        folder = automation_dir / automation_id
        folder.mkdir()
        (folder / "automation.toml").write_text("\n".join(fragments), encoding="utf-8")

    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {"ORCL": {"current_price": "225", "previous_close": "220", "volume_ratio": "2.0", "tradable": True}},
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.timezone.utc),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "verify-overnight-system",
            "--json-output",
            "--log-dir",
            str(verify_dir),
            "--overnight-log-dir",
            str(overnight_dir),
            "--premarket-brief-log-dir",
            str(brief_dir),
            "--hourly-log-dir",
            str(hourly_dir),
            "--paper-tournament-log-dir",
            str(tournament_dir),
            "--automation-dir",
            str(automation_dir),
            "--context-dir",
            str(context_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "pass"
    assert {check["name"] for check in payload["checks"]} >= {
        "latest_overnight_packet",
        "overnight_packet_freshness",
        "latest_premarket_brief",
        "latest_hourly_supervisor_packet",
        "latest_paper_tournament_packet",
        "simulated_preopen_validation",
        "automation:tradingagents-overnight-planning",
        "automation:hourly-market-supervisor",
        "automation:paper-strategy-tournament-runner",
        "automation:tradingagents-daily-market-report",
        "overnight_prior_feed",
        "overnight_source_quality_context",
        "overnight_top_provider_bundles",
        "premarket_fresh_validation_checklist",
    }
    prior_feed_check = next(check for check in payload["checks"] if check["name"] == "overnight_prior_feed")
    assert prior_feed_check["status"] == "pass"
    assert prior_feed_check["evidence"]["execution_authority"] == "none"
    premarket_check = next(
        check for check in payload["checks"] if check["name"] == "premarket_fresh_validation_checklist"
    )
    assert premarket_check["status"] == "pass"
    assert premarket_check["evidence"]["compact_item_count"] == 5
    assert premarket_check["evidence"]["raw_missing"] == []
    assert premarket_check["evidence"]["compact_missing"] == []
    assert premarket_check["evidence"]["compact_points_to_latest_raw"] is True
    freshness_check = next(
        check for check in payload["checks"] if check["name"] == "overnight_packet_freshness"
    )
    assert freshness_check["status"] == "pass"
    assert freshness_check["evidence"]["stale"] is False
    source_quality_check = next(
        check for check in payload["checks"] if check["name"] == "overnight_source_quality_context"
    )
    assert source_quality_check["status"] == "pass"
    assert source_quality_check["evidence"]["source_quality_ordering_enabled"] is True
    assert source_quality_check["evidence"]["stale_downrank_count"] == 2
    provider_bundle_check = next(
        check for check in payload["checks"] if check["name"] == "overnight_top_provider_bundles"
    )
    assert provider_bundle_check["status"] == "pass"
    assert provider_bundle_check["evidence"]["coverage_source"] == "overnight_packet"
    assert provider_bundle_check["evidence"]["missing_symbols"] == []
    hourly_check = next(
        check for check in payload["checks"] if check["name"] == "latest_hourly_supervisor_packet"
    )
    assert hourly_check["status"] == "pass"
    assert hourly_check["evidence"]["expected_safety_lock"] is True
    assert (verify_dir / "latest.json").exists()
    assert (verify_dir / "latest-compact.json").exists()
    assert (verify_dir / "latest.md").exists()
    compact_payload = json.loads((verify_dir / "latest-compact.json").read_text(encoding="utf-8"))
    assert compact_payload["schema"] == "compact_overnight_system_verification_v1"
    assert compact_payload["raw_packet_path"] == payload["packet_path"]
    assert compact_payload["can_submit_orders"] is False
    assert compact_payload["execution_authority"] == "none"
    assert compact_payload["overall_status"] == "pass"
    assert compact_payload["overnight"]["top_symbol"] == "ORCL"
    assert compact_payload["source_quality"]["stale_downrank_count"] == 2
    assert compact_payload["top_provider_bundles"]["coverage_source"] == "overnight_packet"
    assert compact_payload["top_provider_bundles"]["missing_symbols"] == []
    assert compact_payload["premarket_fresh_validation"]["compact_item_count"] == 5
    assert compact_payload["hourly"]["expected_safety_lock"] is True
    assert compact_payload["failed_checks"] == []

    bad_compact = {
        "schema": "compact_premarket_brief_v1",
        "analysis_only": True,
        "raw_packet_path": str(brief_dir / "premarket-brief-20260601-010500.json"),
        "generated_at": brief_packet["generated_at"],
        "execution_authority": "none",
        "premarket_instructions": {"top_symbol": "ORCL"},
    }
    (brief_dir / "latest-compact.json").write_text(json.dumps(bad_compact), encoding="utf-8")
    bad_compact_result = runner.invoke(
        app,
        [
            "alpaca",
            "verify-overnight-system",
            "--json-output",
            "--log-dir",
            str(verify_dir / "bad-premarket-compact"),
            "--overnight-log-dir",
            str(overnight_dir),
            "--premarket-brief-log-dir",
            str(brief_dir),
            "--hourly-log-dir",
            str(hourly_dir),
            "--paper-tournament-log-dir",
            str(tournament_dir),
            "--automation-dir",
            str(automation_dir),
        ],
    )
    assert bad_compact_result.exit_code == 0, bad_compact_result.output
    bad_compact_payload = json.loads(bad_compact_result.stdout)
    bad_compact_check = next(
        check
        for check in bad_compact_payload["checks"]
        if check["name"] == "premarket_fresh_validation_checklist"
    )
    assert bad_compact_payload["overall_status"] == "fail"
    assert bad_compact_check["status"] == "fail"
    assert bad_compact_check["evidence"]["raw_missing"] == []
    assert bad_compact_check["evidence"]["compact_missing"] == PREMARKET_FRESH_VALIDATION_ITEMS
    _write_verify_premarket_fixture(brief_dir, brief_packet)

    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 6, 19, 0, tzinfo=datetime.timezone.utc),
    )
    saturday_result = runner.invoke(
        app,
        [
            "alpaca",
            "verify-overnight-system",
            "--json-output",
            "--log-dir",
            str(verify_dir / "saturday"),
            "--overnight-log-dir",
            str(overnight_dir),
            "--premarket-brief-log-dir",
            str(brief_dir),
            "--hourly-log-dir",
            str(hourly_dir),
            "--paper-tournament-log-dir",
            str(tournament_dir),
            "--automation-dir",
            str(automation_dir),
        ],
    )

    assert saturday_result.exit_code == 0, saturday_result.output
    saturday_payload = json.loads(saturday_result.stdout)
    assert saturday_payload["overall_status"] == "fail"
    saturday_freshness_check = next(
        check
        for check in saturday_payload["checks"]
        if check["name"] == "overnight_packet_freshness"
    )
    assert saturday_freshness_check["status"] == "pass"
    assert saturday_freshness_check["evidence"]["stale"] is True
    assert saturday_freshness_check["evidence"]["freshness_deferred_for_calendar"] is True
    assert saturday_freshness_check["evidence"]["calendar_skip_reason"] == "saturday_no_regular_market_morning"
    saturday_trade_date_check = next(
        check
        for check in saturday_payload["checks"]
        if check["name"] == "overnight_packet_trade_date"
    )
    assert saturday_trade_date_check["status"] == "fail"
    assert saturday_trade_date_check["evidence"]["actual_trade_date"] == "2026-06-01"
    assert saturday_trade_date_check["evidence"]["expected_trade_date"] == "2026-06-08"
    saturday_preopen_check = next(
        check for check in saturday_payload["checks"] if check["name"] == "simulated_preopen_validation"
    )
    assert saturday_preopen_check["status"] == "pass"
    assert saturday_preopen_check["evidence"]["validation_skipped"] is True
    assert saturday_preopen_check["evidence"]["skip_reason"] == "saturday_no_regular_market_morning"

    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.timezone.utc),
    )

    corrupted_prior_feed = {
        "schema": "overnight_prior_feed_v1",
        "generated_at": "2026-06-01T01:00:00+00:00",
        "analysis_only": True,
        "execution_authority": "none",
        "forbidden_effects": ["submit_order"],
        "packet_count": 99,
        "blocked_count": 0,
        "packet_refs": [],
    }
    prior_feed_path.write_text(json.dumps(corrupted_prior_feed), encoding="utf-8")
    bad_prior_result = runner.invoke(
        app,
        [
            "alpaca",
            "verify-overnight-system",
            "--json-output",
            "--log-dir",
            str(verify_dir / "bad-prior-feed"),
            "--overnight-log-dir",
            str(overnight_dir),
            "--premarket-brief-log-dir",
            str(brief_dir),
            "--hourly-log-dir",
            str(hourly_dir),
            "--paper-tournament-log-dir",
            str(tournament_dir),
            "--automation-dir",
            str(automation_dir),
        ],
    )
    assert bad_prior_result.exit_code == 0, bad_prior_result.output
    bad_prior_payload = json.loads(bad_prior_result.stdout)
    bad_prior_check = next(
        check for check in bad_prior_payload["checks"] if check["name"] == "overnight_prior_feed"
    )
    assert bad_prior_payload["overall_status"] == "fail"
    assert bad_prior_check["status"] == "fail"
    assert "packet_count" in bad_prior_check["evidence"]["mismatches"]

    prior_feed_path.write_text(
        json.dumps(
            {
                "schema": "overnight_prior_feed_v1",
                "generated_at": "2026-06-01T01:00:00+00:00",
                "analysis_only": True,
                "execution_authority": "none",
                "forbidden_effects": ["submit_order", "cancel_order", "promote_strategy"],
                "packet_count": 13,
                "blocked_count": 0,
                "packet_refs": [],
            }
        ),
        encoding="utf-8",
    )

    overnight_automation = automation_dir / "tradingagents-overnight-planning" / "automation.toml"
    overnight_automation.write_text(
        overnight_automation.read_text(encoding="utf-8").replace(
            'status = "ACTIVE"',
            'status = "PAUSED"',
        ),
        encoding="utf-8",
    )
    paused_result = runner.invoke(
        app,
        [
            "alpaca",
            "verify-overnight-system",
            "--json-output",
            "--log-dir",
            str(verify_dir / "paused"),
            "--overnight-log-dir",
            str(overnight_dir),
            "--premarket-brief-log-dir",
            str(brief_dir),
            "--hourly-log-dir",
            str(hourly_dir),
            "--paper-tournament-log-dir",
            str(tournament_dir),
            "--automation-dir",
            str(automation_dir),
        ],
    )
    assert paused_result.exit_code == 0, paused_result.output
    paused_payload = json.loads(paused_result.stdout)
    status_check = next(
        check
        for check in paused_payload["checks"]
        if check["name"] == "automation_status:tradingagents-overnight-planning"
    )
    assert paused_payload["overall_status"] == "pass"
    assert status_check["status"] == "pass"
    assert status_check["evidence"]["actual_status"] == "PAUSED"
    assert status_check["evidence"]["complete_packet_ready"] is True

    incomplete_packet = {**overnight_packet, "overnight_quality": {**overnight_packet["overnight_quality"], "completion_status": "timeout"}}
    overnight_path.write_text(json.dumps(incomplete_packet), encoding="utf-8")
    (overnight_dir / "latest.json").write_text(json.dumps(incomplete_packet), encoding="utf-8")
    paused_incomplete_result = runner.invoke(
        app,
        [
            "alpaca",
            "verify-overnight-system",
            "--json-output",
            "--log-dir",
            str(verify_dir / "paused-incomplete"),
            "--overnight-log-dir",
            str(overnight_dir),
            "--premarket-brief-log-dir",
            str(brief_dir),
            "--hourly-log-dir",
            str(hourly_dir),
            "--paper-tournament-log-dir",
            str(tournament_dir),
            "--automation-dir",
            str(automation_dir),
        ],
    )
    assert paused_incomplete_result.exit_code == 0, paused_incomplete_result.output
    paused_incomplete_payload = json.loads(paused_incomplete_result.stdout)
    incomplete_status_check = next(
        check
        for check in paused_incomplete_payload["checks"]
        if check["name"] == "automation_status:tradingagents-overnight-planning"
    )
    assert paused_incomplete_payload["overall_status"] == "fail"
    assert incomplete_status_check["status"] == "fail"
    assert incomplete_status_check["evidence"]["actual_status"] == "PAUSED"
    assert incomplete_status_check["evidence"]["complete_packet_ready"] is False


def test_verify_overnight_top_provider_bundle_uses_source_routing_overlay(tmp_path):
    source_routing_path = tmp_path / "source-routing-compact.json"
    source_routing_path.write_text(
        json.dumps(
            {
                "recent_provider_bundle_count": 3,
                "latest_provider_bundle_summary_path": "results/research_evidence/latest.json",
                "latest_provider_bundle_generated_at": "2026-06-07T21:53:26+00:00",
                "recent_provider_target_symbols_with_bundle": ["XOM", "CVX", "ADBE"],
                "recent_provider_target_symbols_missing_bundle": [],
                "recent_provider_bundle_gap_count": 1,
                "recent_provider_target_bundle_gap_count": 1,
            }
        ),
        encoding="utf-8",
    )
    checks: list[dict] = []

    cli_main._audit_overnight_top_provider_bundles(
        checks,
        {
            "ranked_candidates": [
                {"symbol": "XOM"},
                {"symbol": "CVX"},
                {"symbol": "ADBE"},
            ]
        },
        source_routing_compact_path=source_routing_path,
    )

    assert checks == [
        {
            "name": "overnight_top_provider_bundles",
            "status": "pass",
            "summary": "Top overnight candidates have recent provider-bundle coverage in compact source-routing context.",
            "evidence": {
                "coverage_source": "source_routing_overlay",
                "source_routing_compact_path": str(source_routing_path),
                "top_symbols": ["XOM", "CVX", "ADBE"],
                "recent_provider_bundle_count": 3,
                "latest_provider_bundle_summary_path": "results/research_evidence/latest.json",
                "latest_provider_bundle_generated_at": "2026-06-07T21:53:26+00:00",
                "bundled_target_symbols": ["ADBE", "CVX", "XOM"],
                "missing_symbols": [],
                "recent_provider_bundle_gap_count": 1,
                "recent_provider_target_bundle_gap_count": 1,
            },
        }
    ]


def test_verify_overnight_status_requires_reactivation_inside_next_due_window(tmp_path):
    automation_dir = tmp_path / "automations"
    overnight_automation = automation_dir / "tradingagents-overnight-planning"
    overnight_automation.mkdir(parents=True)
    overnight_automation.joinpath("automation.toml").write_text(
        "\n".join(
            [
                'status = "PAUSED"',
                'rrule = "RRULE:FREQ=WEEKLY;BYHOUR=2;BYMINUTE=30;BYDAY=SU,MO,TU,WE,TH,FR,SA"',
            ]
        ),
        encoding="utf-8",
    )
    complete_packet = {
        "analysis_only": True,
        "ranked_candidates": [{"symbol": "XOM"}],
        "submitted": [],
        "overnight_quality": {"completion_status": "complete"},
    }

    checks: list[dict] = []
    cli_main._verify_overnight_planning_status(
        checks,
        automation_dir=automation_dir,
        overnight_packet=complete_packet,
        now=datetime.datetime(2026, 6, 7, 17, 49, tzinfo=datetime.timezone.utc),
    )

    early_check = checks[-1]
    assert early_check["status"] == "pass"
    assert early_check["evidence"]["actual_status"] == "PAUSED"
    assert early_check["evidence"]["complete_packet_ready"] is True
    assert early_check["evidence"]["reactivation_required"] is False
    assert early_check["evidence"]["hours_until_next_useful_due"] > 12

    checks = []
    cli_main._verify_overnight_planning_status(
        checks,
        automation_dir=automation_dir,
        overnight_packet=complete_packet,
        now=datetime.datetime(2026, 6, 7, 21, 50, tzinfo=datetime.timezone.utc),
    )

    due_check = checks[-1]
    assert due_check["status"] == "fail"
    assert due_check["summary"].startswith("Overnight automation is PAUSED inside")
    assert due_check["evidence"]["actual_status"] == "PAUSED"
    assert due_check["evidence"]["complete_packet_ready"] is True
    assert due_check["evidence"]["reactivation_required"] is True
    assert due_check["evidence"]["next_useful_due_at"] == "2026-06-08T07:30:00+00:00"
    assert due_check["evidence"]["hours_until_next_useful_due"] < 10


def test_verify_overnight_system_rejects_fresh_packet_for_wrong_trade_date(monkeypatch, tmp_path):
    overnight_dir = tmp_path / "overnight"
    brief_dir = tmp_path / "briefs"
    hourly_dir = tmp_path / "hourly"
    tournament_dir = tmp_path / "tournament"
    automation_dir = tmp_path / "automations"
    verify_dir = tmp_path / "verify"
    for path in (overnight_dir, brief_dir, hourly_dir, tournament_dir, automation_dir):
        path.mkdir()

    generated_at = "2026-06-07T07:48:58+00:00"
    overnight_path = overnight_dir / "overnight-plan-20260607-074858.json"
    overnight_packet = {
        "generated_at": generated_at,
        "analysis_only": True,
        "trade_date": "2026-06-05",
        "packet_path": str(overnight_path),
        "research_context": {
            "packet_count": 13,
            "blocked_count": 0,
            "prior_feed": {
                "schema": "overnight_prior_feed_v1",
                "path": str(overnight_dir / "research_context" / "overnight-prior-feed.json"),
                "packet_count": 13,
                "blocked_count": 0,
                "execution_authority": "none",
            },
        },
        "overnight_quality": {
            "full_graph_limit": 3,
            "requested_full_graph_limit": 3,
            "full_graph_count": 3,
            "full_graph_attempt_count": 3,
            "full_graph_success_count": 3,
            "fallback_count": 37,
            "graph_failure_count": 0,
            "completion_status": "complete",
            "per_ticker_timeout_minutes": 25,
            "time_budget_minutes": 90,
            "graph_config": {
                "graph_profile": "compact",
                "llm_provider": "google",
                "quick_think_llm": "gemini-2.5-flash-lite",
                "deep_think_llm": "gemini-2.5-flash",
                "max_completion_tokens": 220,
            },
        },
        "ranked_candidates": [{"symbol": "CVX", "score": "0.90"}],
        "ticker_results": [{"symbol": "CVX", "status": "ok"}],
        "submitted": [],
    }
    overnight_path.write_text(json.dumps(overnight_packet), encoding="utf-8")
    (overnight_dir / "latest.json").write_text(json.dumps(overnight_packet), encoding="utf-8")
    prior_feed_path = overnight_dir / "research_context" / "overnight-prior-feed.json"
    prior_feed_path.parent.mkdir()
    prior_feed_path.write_text(
        json.dumps(
            {
                "schema": "overnight_prior_feed_v1",
                "generated_at": generated_at,
                "analysis_only": True,
                "execution_authority": "none",
                "forbidden_effects": ["submit_order", "cancel_order", "promote_strategy"],
                "packet_count": 13,
                "blocked_count": 0,
                "packet_refs": [],
            }
        ),
        encoding="utf-8",
    )

    brief_packet = {
        "generated_at": "2026-06-07T07:53:22+00:00",
        "analysis_only": True,
        "source_packets": [{"kind": "overnight_plan", "path": str(overnight_path), "generated_at": generated_at}],
        "timeline": [],
        "unresolved_blockers": [],
        "stale_warnings": [],
        "premarket_instructions": _premarket_instructions("CVX"),
    }
    _write_verify_premarket_fixture(brief_dir, brief_packet)
    (hourly_dir / "hourly-supervisor-20260607-080000.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-07T08:00:00+00:00",
                "decision": "hold",
                "issues": [],
                "submitted": [],
                "evidence": {"overnight_plan": {"status": "confirmed", "overnight_top_symbol": "CVX"}},
            }
        ),
        encoding="utf-8",
    )
    (tournament_dir / "latest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-07T08:01:00+00:00",
                "submitted_count": 0,
                "report": {"rankings": [{"strategy_id": "pullback-support"}]},
            }
        ),
        encoding="utf-8",
    )
    overnight_automation_dir = automation_dir / "tradingagents-overnight-planning"
    overnight_automation_dir.mkdir()
    (overnight_automation_dir / "automation.toml").write_text(
        "\n".join(
            [
                'status = "ACTIVE"',
                "alpaca plan-overnight",
                "--overnight-graph-profile compact",
                "--overnight-llm-provider google",
                "--overnight-quick-think-llm gemini-2.5-flash-lite",
                "--overnight-deep-think-llm gemini-2.5-flash",
                "--full-graph-tickers 3",
                "--per-ticker-timeout-minutes 25",
                "--time-budget-minutes 90",
                "--overnight-max-completion-tokens 220",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 7, 12, 0, tzinfo=datetime.timezone.utc),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "verify-overnight-system",
            "--json-output",
            "--log-dir",
            str(verify_dir),
            "--overnight-log-dir",
            str(overnight_dir),
            "--premarket-brief-log-dir",
            str(brief_dir),
            "--hourly-log-dir",
            str(hourly_dir),
            "--paper-tournament-log-dir",
            str(tournament_dir),
            "--automation-dir",
            str(automation_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "fail"
    trade_date_check = next(
        check for check in payload["checks"] if check["name"] == "overnight_packet_trade_date"
    )
    assert trade_date_check["status"] == "fail"
    assert trade_date_check["evidence"]["actual_trade_date"] == "2026-06-05"
    assert trade_date_check["evidence"]["expected_trade_date"] == "2026-06-08"


def test_verify_overnight_system_warns_when_original_graph_requested_but_disabled(monkeypatch, tmp_path):
    overnight_dir = tmp_path / "overnight"
    brief_dir = tmp_path / "briefs"
    hourly_dir = tmp_path / "hourly"
    tournament_dir = tmp_path / "tournament"
    automation_dir = tmp_path / "automations"
    verify_dir = tmp_path / "verify"
    for path in (overnight_dir, brief_dir, hourly_dir, tournament_dir, automation_dir):
        path.mkdir()

    overnight_path = overnight_dir / "overnight-plan-20260601-010000.json"
    overnight_packet = {
        "generated_at": "2026-06-01T01:00:00+00:00",
        "trade_date": "2026-06-01",
        "analysis_only": True,
        "packet_path": str(overnight_path),
        "research_context": {
            "packet_count": 13,
            "blocked_count": 0,
            "watchlists": {
                "source_quality": {
                    "status": "available",
                    "review_path": "results/source_quality/latest.json",
                    "source_quality_ordering_enabled": True,
                    "scored_source_count": 3,
                    "source_count": 12,
                    "stale_count": 2,
                    "stale_downrank_count": 2,
                    "stale_needs_refresh_count": 0,
                    "blocked_count": 0,
                    "missing_or_invalid_count": 0,
                    "unreadable_count": 0,
                    "next_action": "use_review_for_downranking",
                    "blocked": False,
                }
            },
        },
        "overnight_quality": {
            "requested_full_graph_limit": 3,
            "full_graph_limit": 0,
            "full_graph_count": 0,
            "fallback_count": 35,
            "graph_failure_count": 0,
            "graph_disabled_reason": "Windows Ollama graph backend is unavailable.",
            "completion_status": "disabled",
            "completion_reasons": ["Windows Ollama graph backend is unavailable."],
            "per_ticker_timeout_minutes": 25,
            "time_budget_minutes": 90,
            "graph_config": {
                "graph_profile": "compact",
                "llm_provider": "ollama",
                "quick_think_llm": "local",
                "deep_think_llm": "local",
                "backend_url": "http://localhost:11434/v1",
                "max_completion_tokens": 220,
            },
        },
        "ranked_candidates": [{"symbol": "ORCL", "score": "0.90"}],
        "ticker_results": [{"symbol": "ORCL", "status": "fallback"}],
        "top_provider_bundles": {
            "enabled": True,
            "analysis_only": True,
            "execution_authority": "none",
            "symbols": ["ORCL"],
            "bundle_count": 1,
            "source_packet_count": 7,
            "gap_packet_count": 0,
            "error_count": 0,
            "evidence_needs_without_non_gap_packets": [],
            "symbols_with_missing_non_gap": [],
            "summary_packet_paths": {"ORCL": "results/research_evidence/orcl-summary.json"},
        },
        "submitted": [],
    }
    overnight_path.write_text(json.dumps(overnight_packet), encoding="utf-8")
    (overnight_dir / "latest.json").write_text(json.dumps(overnight_packet), encoding="utf-8")

    brief_packet = {
        "generated_at": "2026-06-01T01:05:00+00:00",
        "analysis_only": True,
        "source_packets": [
            {"kind": "overnight_plan", "path": str(overnight_path), "generated_at": "2026-06-01T01:00:00+00:00"}
        ],
        "timeline": [],
        "unresolved_blockers": [],
        "stale_warnings": [],
        "premarket_instructions": _premarket_instructions("ORCL"),
    }
    _write_verify_premarket_fixture(brief_dir, brief_packet)

    hourly_packet = {
        "generated_at": "2026-06-01T01:06:00+00:00",
        "decision": "hold",
        "reason": "no clean dip setup",
        "issues": [],
        "submitted": [],
        "portfolio": {"live": {"open_orders": []}},
        "evidence": {"overnight_plan": {"status": "confirmed", "overnight_top_symbol": "ORCL"}},
    }
    (hourly_dir / "hourly-supervisor-20260601-010600.json").write_text(json.dumps(hourly_packet), encoding="utf-8")

    tournament_packet = {
        "generated_at": "2026-06-01T01:07:00+00:00",
        "submitted_count": 0,
        "report": {
            "rankings": [
                {"strategy_id": "current-aggressive"},
                {"strategy_id": "pullback-support"},
                {"strategy_id": "catalyst-relative-strength"},
            ],
            "live_strategy_candidate": {"status": "pending", "strategy_id": "current-aggressive"},
        },
    }
    (tournament_dir / "latest.json").write_text(json.dumps(tournament_packet), encoding="utf-8")

    automation_specs = {
        "tradingagents-overnight-planning": [
            'status = "ACTIVE"',
            ".venv\\Scripts\\tradingagents.exe",
            "alpaca check",
            "alpaca plan-overnight",
            "--overnight-graph-profile compact",
            "--full-graph-tickers 3",
            "--per-ticker-timeout-minutes 25",
            "--time-budget-minutes 90",
            "--overnight-max-completion-tokens 220",
            "alpaca premarket-brief",
            "must never place live or paper orders",
        ],
        "hourly-market-supervisor": [
            ".venv\\Scripts\\tradingagents.exe",
            "alpaca check",
            "alpaca supervise-hourly --dry-run",
            "--overnight-log-dir results/overnight_plans",
            "--paper-tournament-log-dir results/paper_strategy_tournament",
            "--premarket-brief-log-dir results/premarket_briefs",
        ],
        "paper-strategy-tournament-runner": [
            "paper-tournament run --all",
            "This automation is paper-only",
            "must never place live orders",
        ],
        "tradingagents-daily-market-report": [
            "supervisor-daily-report",
            "--paper-tournament-log-dir results/paper_strategy_tournament",
            "--premarket-brief-log-dir results/premarket_briefs",
            "must never place trades",
        ],
    }
    for automation_id, fragments in automation_specs.items():
        folder = automation_dir / automation_id
        folder.mkdir()
        (folder / "automation.toml").write_text("\n".join(fragments), encoding="utf-8")

    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {"ORCL": {"current_price": "225", "previous_close": "220", "volume_ratio": "2.0", "tradable": True}},
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.timezone.utc),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "verify-overnight-system",
            "--json-output",
            "--log-dir",
            str(verify_dir),
            "--overnight-log-dir",
            str(overnight_dir),
            "--premarket-brief-log-dir",
            str(brief_dir),
            "--hourly-log-dir",
            str(hourly_dir),
            "--paper-tournament-log-dir",
            str(tournament_dir),
            "--automation-dir",
            str(automation_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    contract_check = next(check for check in payload["checks"] if check["name"] == "overnight_matches_automation_contract")
    graph_check = next(check for check in payload["checks"] if check["name"] == "overnight_original_graph_execution")
    assert payload["overall_status"] == "pass_with_warnings"
    assert contract_check["status"] == "pass"
    assert graph_check["status"] == "warn"
    assert graph_check["evidence"]["expected_full_graph_limit"] == 3
    assert graph_check["evidence"]["requested_full_graph_limit"] == 3
    assert graph_check["evidence"]["actual_full_graph_limit"] == 0
    assert graph_check["evidence"]["full_graph_count"] == 0
    assert graph_check["evidence"]["full_graph_success_count"] == 0
    assert graph_check["evidence"]["fallback_count"] == 35
    assert "Ollama" in graph_check["evidence"]["graph_disabled_reason"]

    incomplete_packet = dict(overnight_packet)
    incomplete_quality = dict(overnight_packet["overnight_quality"])
    incomplete_quality.update(
        {
            "full_graph_limit": 3,
            "requested_full_graph_limit": 3,
            "graph_disabled_reason": None,
            "completion_status": "incomplete",
            "completion_reasons": ["full graph was requested but no graph run was attempted"],
        }
    )
    incomplete_packet["overnight_quality"] = incomplete_quality
    overnight_path.write_text(json.dumps(incomplete_packet), encoding="utf-8")
    (overnight_dir / "latest.json").write_text(json.dumps(incomplete_packet), encoding="utf-8")

    incomplete_result = runner.invoke(
        app,
        [
            "alpaca",
            "verify-overnight-system",
            "--json-output",
            "--log-dir",
            str(verify_dir),
            "--overnight-log-dir",
            str(overnight_dir),
            "--premarket-brief-log-dir",
            str(brief_dir),
            "--hourly-log-dir",
            str(hourly_dir),
            "--paper-tournament-log-dir",
            str(tournament_dir),
            "--automation-dir",
            str(automation_dir),
        ],
    )

    assert incomplete_result.exit_code == 0, incomplete_result.output
    incomplete_payload = json.loads(incomplete_result.stdout)
    incomplete_graph_check = next(
        check
        for check in incomplete_payload["checks"]
        if check["name"] == "overnight_original_graph_execution"
    )
    assert incomplete_payload["overall_status"] == "fail"
    assert incomplete_graph_check["status"] == "fail"
    assert incomplete_graph_check["evidence"]["completion_status"] == "incomplete"


def test_verify_overnight_system_rejects_probe_latest_against_automation_contract(monkeypatch, tmp_path):
    overnight_dir = tmp_path / "overnight"
    brief_dir = tmp_path / "briefs"
    hourly_dir = tmp_path / "hourly"
    tournament_dir = tmp_path / "tournament"
    automation_dir = tmp_path / "automations"
    verify_dir = tmp_path / "verify"
    for path in (overnight_dir, brief_dir, hourly_dir, tournament_dir, automation_dir):
        path.mkdir()

    probe_path = overnight_dir / "overnight-plan-20260601-010000.json"
    probe_packet = {
        "generated_at": "2026-06-01T01:00:00+00:00",
        "analysis_only": True,
        "trade_date": "2026-06-01",
        "packet_path": str(probe_path),
        "overnight_quality": {
            "full_graph_limit": 0,
            "full_graph_count": 0,
            "fallback_count": 35,
            "graph_failure_count": 0,
            "per_ticker_timeout_minutes": 0,
            "time_budget_minutes": 2,
            "graph_config": {
                "graph_profile": "full",
                "llm_provider": "ollama",
                "quick_think_llm": "local",
                "deep_think_llm": "local",
                "backend_url": "http://localhost:11434/v1",
                "max_completion_tokens": 220,
            },
        },
        "ranked_candidates": [{"symbol": "ORCL", "score": "0.90"}],
        "ticker_results": [{"symbol": "ORCL", "status": "fallback"}],
        "submitted": [],
    }
    probe_path.write_text(json.dumps(probe_packet), encoding="utf-8")
    (overnight_dir / "latest.json").write_text(json.dumps(probe_packet), encoding="utf-8")

    brief_packet = {
        "generated_at": "2026-06-01T01:05:00+00:00",
        "analysis_only": True,
        "source_packets": [
            {"kind": "overnight_plan", "path": str(probe_path), "generated_at": "2026-06-01T01:00:00+00:00"}
        ],
        "timeline": [],
        "unresolved_blockers": [],
        "stale_warnings": [],
        "premarket_instructions": _premarket_instructions("ORCL"),
    }
    _write_verify_premarket_fixture(brief_dir, brief_packet)
    (hourly_dir / "hourly-supervisor-20260601-010600.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T01:06:00+00:00",
                "decision": "hold",
                "issues": [],
                "submitted": [],
                "evidence": {"overnight_plan": {"status": "confirmed", "overnight_top_symbol": "ORCL"}},
            }
        ),
        encoding="utf-8",
    )
    (tournament_dir / "latest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T01:07:00+00:00",
                "submitted_count": 0,
                "report": {
                    "rankings": [
                        {"strategy_id": "current-aggressive"},
                        {"strategy_id": "pullback-support"},
                        {"strategy_id": "catalyst-relative-strength"},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    folder = automation_dir / "tradingagents-overnight-planning"
    folder.mkdir()
    (folder / "automation.toml").write_text(
        "\n".join(
            [
                'status = "ACTIVE"',
                ".venv\\Scripts\\tradingagents.exe",
                "alpaca check",
                "alpaca plan-overnight",
                "--overnight-graph-profile compact",
                "--full-graph-tickers 3",
                "--per-ticker-timeout-minutes 25",
                "--time-budget-minutes 90",
                "--overnight-max-completion-tokens 220",
                "alpaca premarket-brief",
                "must never place live or paper orders",
            ]
        ),
        encoding="utf-8",
    )
    for automation_id, fragments in {
        "hourly-market-supervisor": [
            ".venv\\Scripts\\tradingagents.exe",
            "alpaca check",
            "alpaca supervise-hourly --dry-run",
            "--overnight-log-dir results/overnight_plans",
            "--paper-tournament-log-dir results/paper_strategy_tournament",
            "--premarket-brief-log-dir results/premarket_briefs",
        ],
        "paper-strategy-tournament-runner": [
            "paper-tournament run --all",
            "This automation is paper-only",
            "must never place live orders",
        ],
        "tradingagents-daily-market-report": [
            "supervisor-daily-report",
            "--paper-tournament-log-dir results/paper_strategy_tournament",
            "--premarket-brief-log-dir results/premarket_briefs",
            "must never place trades",
        ],
    }.items():
        other_folder = automation_dir / automation_id
        other_folder.mkdir()
        (other_folder / "automation.toml").write_text("\n".join(fragments), encoding="utf-8")

    monkeypatch.setattr(
        cli_main,
        "_fetch_aggressive_candidate_market_data",
        lambda: {"ORCL": {"current_price": "225", "previous_close": "220", "volume_ratio": "2.0", "tradable": True}},
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_policy_now",
        lambda: datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.timezone.utc),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "verify-overnight-system",
            "--json-output",
            "--log-dir",
            str(verify_dir),
            "--overnight-log-dir",
            str(overnight_dir),
            "--premarket-brief-log-dir",
            str(brief_dir),
            "--hourly-log-dir",
            str(hourly_dir),
            "--paper-tournament-log-dir",
            str(tournament_dir),
            "--automation-dir",
            str(automation_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    contract_check = next(check for check in payload["checks"] if check["name"] == "overnight_matches_automation_contract")
    assert payload["overall_status"] == "fail"
    assert contract_check["status"] == "fail"
    assert contract_check["evidence"]["expected"]["graph_profile"] == "compact"
    assert contract_check["evidence"]["actual"]["graph_profile"] == "full"
    assert contract_check["evidence"]["expected"]["full_graph_limit"] == 3
    assert contract_check["evidence"]["actual"]["full_graph_limit"] == 0


def test_policy_pullback_support_writes_shadow_packet(tmp_path):
    packet_dir = tmp_path / "shadow"

    result = runner.invoke(
        app,
        [
            "policy",
            "pullback-support",
            "--symbol",
            "msft",
            "--current-price",
            "410",
            "--support-level",
            "408",
            "--atr",
            "4",
            "--pullback-atr",
            "1.1",
            "--above-rising-50d",
            "--above-rising-200d",
            "--sell-volume-state",
            "decelerating",
            "--gap-state",
            "reclaimed",
            "--sector-relative-strength",
            "0.62",
            "--regime-state",
            "neutral",
            "--notional-usd",
            "100",
            "--output-dir",
            str(packet_dir),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["decision"] == "paper_enter"
    assert payload["intent"]["environment"] == "paper"
    assert payload["packet_path"]
    packet = json.loads((packet_dir / "latest.json").read_text(encoding="utf-8"))
    assert packet["decision"] == "order"
    assert packet["candidate"]["symbol"] == "MSFT"
    assert packet["intent"]["sleeve"] == "pullback-support"


def test_alpaca_pullback_support_paper_dry_run_does_not_submit_or_create_live_client(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    packet_dir = tmp_path / "pullback-paper"
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_clients",
        lambda: (_ for _ in ()).throw(AssertionError("live client should not be used")),
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_execution_config",
        lambda: AlpacaExecutionConfig(paper_enabled=False, live_mirror_enabled=True),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "pullback-support-paper",
            "--symbol",
            "msft",
            "--current-price",
            "410",
            "--support-level",
            "408",
            "--atr",
            "4",
            "--pullback-atr",
            "1.1",
            "--above-rising-50d",
            "--above-rising-200d",
            "--sell-volume-state",
            "decelerating",
            "--gap-state",
            "reclaimed",
            "--sector-relative-strength",
            "0.62",
            "--regime-state",
            "neutral",
            "--output-dir",
            str(packet_dir),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["decision"] == "paper_enter"
    assert payload["paper_account_check"]["status"] == "ok"
    assert len(payload["planned_orders"]["accepted"]) == 1
    assert payload["submitted"] == []
    assert paper_client.submitted == []
    packet = json.loads((packet_dir / "latest.json").read_text(encoding="utf-8"))
    assert packet["decision"] == "order"
    assert packet["audit"]["dry_run"] is True
    assert packet["audit"]["paper_submit_requires"] == [
        "alpaca_check",
        "dry_run",
        "paper_enabled",
    ]


def test_alpaca_pullback_support_paper_submit_is_paper_only(monkeypatch, tmp_path):
    paper_client = _FakeCliClient(paper=True)
    packet_dir = tmp_path / "pullback-paper"
    monkeypatch.setattr(cli_main, "_alpaca_paper_client", lambda: paper_client)
    monkeypatch.setattr(
        cli_main,
        "_alpaca_clients",
        lambda: (_ for _ in ()).throw(AssertionError("live client should not be used")),
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_execution_config",
        lambda: AlpacaExecutionConfig(paper_enabled=True, live_mirror_enabled=True),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "pullback-support-paper",
            "--symbol",
            "msft",
            "--current-price",
            "410",
            "--support-level",
            "408",
            "--atr",
            "4",
            "--pullback-atr",
            "1.1",
            "--above-rising-50d",
            "--above-rising-200d",
            "--sell-volume-state",
            "decelerating",
            "--gap-state",
            "reclaimed",
            "--sector-relative-strength",
            "0.62",
            "--regime-state",
            "neutral",
            "--submit-actions",
            "--output-dir",
            str(packet_dir),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload["submitted"]) == 1
    assert len(paper_client.submitted) == 1
    assert paper_client.submitted[0]["symbol"] == "MSFT"
    assert paper_client.submitted[0]["type"] == "limit"
    assert paper_client.submitted[0]["side"] == "buy"
    assert "live" not in paper_client.submitted[0]["client_order_id"]
    packet = json.loads((packet_dir / "latest.json").read_text(encoding="utf-8"))
    assert packet["audit"]["dry_run"] is False
    assert packet["audit"]["submitted_count"] == 1


def test_alpaca_pullback_support_falling_knife_writes_hold_cash_without_broker(monkeypatch, tmp_path):
    packet_dir = tmp_path / "pullback-paper"
    monkeypatch.setattr(
        cli_main,
        "_alpaca_paper_client",
        lambda: (_ for _ in ()).throw(AssertionError("broker should not be used")),
    )
    monkeypatch.setattr(
        cli_main,
        "_alpaca_clients",
        lambda: (_ for _ in ()).throw(AssertionError("live client should not be used")),
    )

    result = runner.invoke(
        app,
        [
            "alpaca",
            "pullback-support-paper",
            "--symbol",
            "msft",
            "--current-price",
            "390",
            "--support-level",
            "408",
            "--atr",
            "4",
            "--pullback-atr",
            "3.4",
            "--below-rising-50d",
            "--below-rising-200d",
            "--sell-volume-state",
            "expanding",
            "--gap-state",
            "open_down",
            "--sector-relative-strength",
            "0.30",
            "--regime-state",
            "risk_off",
            "--earnings-blackout",
            "--fresh-negative-event",
            "--output-dir",
            str(packet_dir),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["decision"] == "HOLD_CASH"
    assert payload["paper_account_check"]["status"] == "not_needed_no_order_intent"
    packet = json.loads((packet_dir / "latest.json").read_text(encoding="utf-8"))
    assert packet["decision"] == "hold_cash"
    assert packet["gate"]["final_action"] == "hold_cash"
    assert "falling_knife" in packet["audit"]["reasons"]


def test_policy_freeze_live_writes_control_state(tmp_path):
    control_path = tmp_path / "live_control.json"

    result = runner.invoke(
        app,
        [
            "policy",
            "freeze-live",
            "--reason",
            "operator requested halt",
            "--control-path",
            str(control_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    state = json.loads(control_path.read_text(encoding="utf-8"))
    assert payload["frozen"] is True
    assert state["frozen"] is True
    assert state["reason"] == "operator requested halt"


def test_policy_refresh_live_control_writes_dead_man(tmp_path):
    control_path = tmp_path / "live_control.json"
    cli_main.write_live_control_state(
        control_path,
        frozen=False,
        reason="existing healthy lease",
        dead_man_expires_at=datetime.datetime.now(tz=datetime.timezone.utc)
        + datetime.timedelta(hours=1),
    )

    result = runner.invoke(
        app,
        [
            "policy",
            "refresh-live-control",
            "--reason",
            "ops window active",
            "--ttl-hours",
            "2",
            "--control-path",
            str(control_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    state = json.loads(control_path.read_text(encoding="utf-8"))
    assert payload["frozen"] is False
    assert state["frozen"] is False
    assert state["reason"] == "ops window active"
    assert state["dead_man_expires_at"]


def test_policy_refresh_live_control_cas_preserves_newer_freeze(
    tmp_path,
    monkeypatch,
):
    control_path = tmp_path / "live_control.json"
    cli_main.write_live_control_state(
        control_path,
        frozen=False,
        reason="existing healthy lease",
        dead_man_expires_at=datetime.datetime.now(tz=datetime.timezone.utc)
        + datetime.timedelta(hours=1),
    )
    original_write = cli_main._write_live_control_state_locked

    def newer_freeze_before_refresh(*args, **kwargs):
        control_path.write_text(
            json.dumps(
                {
                    "frozen": True,
                    "reason": "newer independent safety freeze",
                    "dead_man_expires_at": (
                        datetime.datetime.now(tz=datetime.timezone.utc)
                        + datetime.timedelta(days=1)
                    ).isoformat(timespec="seconds"),
                    "updated_at": datetime.datetime.now(
                        tz=datetime.timezone.utc
                    ).isoformat(timespec="seconds"),
                }
            ),
            encoding="utf-8",
        )
        return original_write(*args, **kwargs)

    monkeypatch.setattr(
        cli_main,
        "_write_live_control_state_locked",
        newer_freeze_before_refresh,
    )
    result = runner.invoke(
        app,
        [
            "policy",
            "refresh-live-control",
            "--reason",
            "ops window active",
            "--ttl-hours",
            "2",
            "--control-path",
            str(control_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 1
    state = json.loads(control_path.read_text(encoding="utf-8"))
    assert state["frozen"] is True
    assert state["reason"] == "newer independent safety freeze"


def test_research_crawl_target_writes_blocked_packet(tmp_path):
    result = runner.invoke(
        app,
        [
            "research",
            "crawl-target",
            "--target",
            "https://example.com/thread",
            "--allowed-domains",
            "sec.gov",
            "--output-dir",
            str(tmp_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["status"] == "blocked"
    assert payload["blocked_urls"] == ["https://example.com/thread"]
    assert payload["freshness"]["target_policy"]["reason"] == "target domain is not allowlisted"
    assert (tmp_path / "latest.json").exists()


def test_research_crawler_runtime_doctor_reports_self_heal_guidance(monkeypatch):
    monkeypatch.setattr(
        cli_main,
        "crawler_runtime_status",
        lambda: CrawlerRuntimeStatus(crawlee_available=False, playwright_available=True),
    )

    result = runner.invoke(app, ["research", "crawler-runtime-doctor", "--json-output"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ready"] is False
    assert "uv pip install" in payload["install_commands"]["python_dependencies"]
    assert "install_crawlee_playwright_python_extra" in payload["self_heal_actions"]


def test_research_night_shift_patrol_writes_analysis_only_packet(tmp_path):
    output_dir = tmp_path / "night_shift_patrol"

    result = runner.invoke(
        app,
        [
            "research",
            "night-shift-patrol",
            "--json-output",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)

    assert payload["kind"] == "tradingagents_night_shift_patrol"
    assert payload["automation_id"] == "tradingagents-night-shift-supervisor"
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["execution_authority"] == "none"
    assert payload["submitted_count"] == 0
    assert payload["issue_count"] == 0
    assert payload["forbidden_effects"] == [
        "submit_order",
        "send_email",
        "modify_automation_status",
        "edit_repo_files",
        "mutate_goals",
    ]
    assert payload["context_summary_path"] == "results/_context/latest-summary.json"
    assert payload["context_flags_path"] == "results/_context/latest-flags.json"
    packet_path = Path(payload["json_path"])
    assert packet_path.exists()
    assert packet_path.parent == output_dir
    assert json.loads(packet_path.read_text(encoding="utf-8"))["kind"] == payload["kind"]


def test_research_controller_patrol_writes_analysis_only_packet(tmp_path):
    output_dir = tmp_path / "control_plane_patrol"
    automation_root = tmp_path / "automations"

    result = runner.invoke(
        app,
        [
            "research",
            "controller-patrol",
            "--automation-id",
            "tradingagents-automation-wake-controller",
            "--automation-root",
            str(automation_root),
            "--output-dir",
            str(output_dir),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)

    assert payload["kind"] == "tradingagents_control_plane_patrol"
    assert payload["automation_id"] == "tradingagents-automation-wake-controller"
    assert payload["controller_role"] == "wake_controller"
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["execution_authority"] == "none"
    assert payload["submitted_count"] == 0
    assert payload["issue_count"] == 0
    assert payload["context_summary_path"] == "results/_context/latest-summary.json"
    assert payload["context_flags_path"] == "results/_context/latest-flags.json"
    assert payload["managed_automation_count"] == 0
    packet_path = Path(payload["json_path"])
    assert packet_path.exists()
    assert packet_path.parent == output_dir
    assert packet_path.name.startswith("wake-controller-patrol-")
    assert json.loads(packet_path.read_text(encoding="utf-8"))["kind"] == payload["kind"]


def test_automation_control_commands_default_to_platform_codex_home():
    expected_root = cli_main.default_automation_root()

    controller_default = inspect.signature(
        cli_main.research_controller_patrol
    ).parameters["automation_root"].default.default
    memory_rollup_default = inspect.signature(
        cli_main.research_automation_memory_rollup
    ).parameters["automation_root"].default.default

    assert controller_default == expected_root
    assert memory_rollup_default == expected_root


def test_research_controller_patrol_supports_wake_verification_packet(tmp_path):
    output_dir = tmp_path / "control_plane_patrol"
    automation_root = tmp_path / "automations"

    result = runner.invoke(
        app,
        [
            "research",
            "controller-patrol",
            "--automation-id",
            "tradingagents-wake-verification",
            "--automation-root",
            str(automation_root),
            "--output-dir",
            str(output_dir),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)

    assert payload["kind"] == "tradingagents_control_plane_patrol"
    assert payload["automation_id"] == "tradingagents-wake-verification"
    assert payload["controller_role"] == "wake_verification"
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["execution_authority"] == "none"
    packet_path = Path(payload["json_path"])
    assert packet_path.exists()
    assert packet_path.name.startswith("wake-verification-patrol-")


def test_research_self_heal_plan_writes_analysis_only_packet(monkeypatch, tmp_path):
    def fake_build(repo_root, *, max_signals, output_dir, safe_reverify_minutes=15):
        return {
            "schema_version": 1,
            "kind": "tradingagents_self_heal_plan",
            "generated_at": "2026-06-03T00:00:00+00:00",
            "analysis_only": True,
            "can_submit_orders": False,
            "execution_authority": "none",
            "signal_count": 1,
            "active_plan_count": 1,
            "escalation_count": 0,
            "deduped_prior_count": 0,
            "max_severity": "medium",
            "status": "safe_plan_ready",
            "signals": [],
        }

    monkeypatch.setattr(cli_main, "build_self_heal_plan", fake_build)

    result = runner.invoke(
        app,
        [
            "research",
            "self-heal-plan",
            "--output-dir",
            str(tmp_path),
            "--no-refresh-context",
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["active_plan_count"] == 1
    assert payload["json_path"].endswith(".json")
    assert (tmp_path / "latest.json").exists()


def test_research_self_heal_plan_can_execute_allowlisted_safe_refresh(monkeypatch, tmp_path):
    def fake_build(repo_root, *, max_signals, output_dir, safe_reverify_minutes=15):
        return {
            "schema_version": 1,
            "kind": "tradingagents_self_heal_plan",
            "generated_at": "2026-06-03T00:00:00+00:00",
            "analysis_only": True,
            "can_submit_orders": False,
            "execution_authority": "none",
            "signal_count": 1,
            "active_plan_count": 1,
            "escalation_count": 0,
            "deduped_prior_count": 0,
            "max_severity": "medium",
            "status": "safe_plan_ready",
            "signals": [],
        }

    def fake_execute(packet, *, repo_root):
        executed = dict(packet)
        executed["active_plan_count"] = 0
        executed["executed_count"] = 1
        executed["verified_count"] = 1
        executed["status"] = "verified"
        return executed

    monkeypatch.setattr(cli_main, "build_self_heal_plan", fake_build)
    monkeypatch.setattr(cli_main, "execute_self_heal_plan", fake_execute)

    result = runner.invoke(
        app,
        [
            "research",
            "self-heal-plan",
            "--execute-safe",
            "--output-dir",
            str(tmp_path),
            "--no-refresh-context",
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "verified"
    assert payload["executed_count"] == 1
    assert payload["verified_count"] == 1


def test_research_self_heal_plan_dispatches_owned_recovery_without_execute_safe(monkeypatch, tmp_path):
    def fake_build(repo_root, *, max_signals, output_dir, safe_reverify_minutes=15):
        return {
            "schema_version": 1,
            "kind": "tradingagents_self_heal_plan",
            "generated_at": "2026-06-03T00:00:00+00:00",
            "analysis_only": True,
            "can_submit_orders": False,
            "execution_authority": "none",
            "signal_count": 1,
            "active_plan_count": 0,
            "escalation_count": 0,
            "deduped_prior_count": 0,
            "max_severity": "high",
            "status": "owned_recovery_ready",
            "signals": [{"classification": "recoverable_integrity", "status": "owned_recovery_ready"}],
        }

    called = []
    monkeypatch.setattr(cli_main, "build_self_heal_plan", fake_build)
    monkeypatch.setattr(cli_main, "execute_self_heal_plan", lambda packet, *, repo_root: called.append(repo_root) or {**packet, "owned_recovery_count": 1})

    result = runner.invoke(app, ["research", "self-heal-plan", "--output-dir", str(tmp_path), "--no-refresh-context", "--json-output"])

    assert result.exit_code == 0, result.output
    assert called
    assert json.loads(result.stdout)["owned_recovery_count"] == 1


def test_research_reddit_watchlist_packet_writes_compact_policy(tmp_path):
    result = runner.invoke(
        app,
        [
            "research",
            "reddit-watchlist-packet",
            "--output-dir",
            str(tmp_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["source_name"] == "reddit_watchlist"
    assert payload["payload"]["policy"]["default_recent_only"] is True
    assert payload["payload"]["policy"]["raw_comment_threads_by_default"] is False
    assert "retail_panic" in payload["payload"]["allowed_context_flags"]
    assert "submit_order" in payload["payload"]["policy"]["forbidden_effects"]
    assert (tmp_path / "latest.json").exists()


def test_research_provider_fallbacks_skips_depleted_limited_sources(tmp_path):
    result = runner.invoke(
        app,
        [
            "research",
            "provider-fallbacks",
            "--evidence-need",
            "market_news",
            "--depleted-sources",
            "marketaux,finnhub,fmp,eodhd",
            "--output-dir",
            str(tmp_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    active_names = payload["payload"]["active_source_names"]
    skipped_names = {
        route["source_name"] for route in payload["payload"]["skipped_routes"]
    }
    assert payload["analysis_only"] is True
    assert payload["source_name"] == "provider_fallback_policy"
    assert payload["payload"]["depletion_safe"] is True
    assert "google_news_rss" in active_names
    assert "reddit_watchlist" in active_names
    assert "twitter" not in active_names
    assert "marketaux" not in active_names
    assert skipped_names >= {"marketaux", "finnhub", "fmp", "eodhd"}
    assert "submit_order" in payload["payload"]["policy"]["forbidden_effects"]
    assert (tmp_path / "latest.json").exists()


def test_research_agent_ledger_from_overnight_writes_forecasts(tmp_path):
    overnight_packet = tmp_path / "overnight.json"
    ledger_path = tmp_path / "ledger.jsonl"
    overnight_packet.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T12:00:00+00:00",
                "ticker_results": [
                    {
                        "symbol": "NVDA",
                        "status": "ok",
                        "rating": "Buy",
                        "investment_plan": "**Recommendation**: Buy",
                        "trader_investment_plan": "**Action**: Buy",
                        "final_trade_decision": "**Rating**: Buy",
                        "reports": {
                            "market": "Bullish breakout and strong momentum.",
                            "sentiment": "Positive retail chatter.",
                            "news": "Positive guidance.",
                            "fundamentals": "Strong margins.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-from-overnight",
            "--overnight-packet",
            str(overnight_packet),
            "--ledger-path",
            str(ledger_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["forecast_count"] >= 7
    assert payload["appended_count"] == payload["forecast_count"]
    records = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {record["agent"] for record in records} >= {
        "market_analyst",
        "news_analyst",
        "portfolio_manager",
    }


def test_research_agent_ledger_summary_includes_influence_weights(tmp_path):
    overnight_packet = tmp_path / "overnight.json"
    ledger_path = tmp_path / "ledger.jsonl"
    summary_path = tmp_path / "summary.json"
    overnight_packet.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T12:00:00+00:00",
                "ticker_results": [
                    {
                        "symbol": "NVDA",
                        "status": "ok",
                        "rating": "Buy",
                        "investment_plan": "**Recommendation**: Buy",
                        "trader_investment_plan": "**Action**: Buy",
                        "final_trade_decision": "**Rating**: Buy",
                        "reports": {
                            "market": "Bullish breakout and strong momentum.",
                            "sentiment": "Positive retail chatter.",
                            "news": "Positive guidance.",
                            "fundamentals": "Strong margins.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    add_result = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-from-overnight",
            "--overnight-packet",
            str(overnight_packet),
            "--ledger-path",
            str(ledger_path),
            "--json-output",
        ],
    )
    assert add_result.exit_code == 0, add_result.output

    summary_result = runner.invoke(
        app,
        [
            "research",
            "agent-ledger-summary",
            "--ledger-path",
            str(ledger_path),
            "--summary-path",
            str(summary_path),
            "--json-output",
        ],
    )

    assert summary_result.exit_code == 0, summary_result.output
    payload = json.loads(summary_result.stdout)
    assert payload["influence_weights"]["execution_authority"] == "none"
    assert "waive_live_gate" in payload["influence_weights"]["forbidden_effects"]
    assert "market_analyst" in payload["influence_context"]
    saved = json.loads(summary_path.read_text(encoding="utf-8"))
    assert "influence_weights" in saved


def test_research_release_calendar_packet_writes_macro_context(tmp_path):
    result = runner.invoke(
        app,
        [
            "research",
            "release-calendar-packet",
            "--lookahead-days",
            "7",
            "--output-dir",
            str(tmp_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["source_name"] == "official_release_calendar"
    assert payload["payload"]["policy"]["execution_authority"] == "none"
    assert "submit_order" in payload["payload"]["policy"]["forbidden_effects"]
    assert (tmp_path / "latest.json").exists()


def test_research_model_telemetry_report_writes_budget_summary(tmp_path):
    input_dir = tmp_path / "model_telemetry"
    input_dir.mkdir()
    packet = {
        "schema_version": "1.0.0",
        "packet_id": "model-telemetry-test",
        "analysis_only": True,
        "generated_at": "2026-06-01T15:00:00+00:00",
        "source_refs": [],
        "freshness": {},
        "tool_route": "model_routing",
        "redaction_status": "redacted",
        "run_id": "run-1",
        "provider": "gemini",
        "model": "gemini-test",
        "route": "paid_capped_gemini",
        "status": "success",
        "input_tokens": 100,
        "output_tokens": 50,
        "estimated_cost_usd": "0.10",
        "latency_seconds": 2.0,
    }
    (input_dir / "model-telemetry-test.json").write_text(json.dumps(packet), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "research",
            "model-telemetry-report",
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(tmp_path / "reports"),
            "--budget-limit-usd",
            "0.25",
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["packet_count"] == 1
    assert payload["estimated_cost_total_usd"] == "0.1000"
    assert payload["budget_remaining_usd"] == "0.1500"
    assert (tmp_path / "reports" / "latest.json").exists()


def test_research_outcome_labeling_writes_model_and_mirror_labels(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    summary_path = tmp_path / "summary.json"
    forecast = {
        "forecast_id": "forecast-helped",
        "agent": "market_analyst",
        "ticker": "NVDA",
        "claim": "market analyst expects NVDA to outperform",
        "forecast_type": "market_report_direction",
        "horizon": "5 trading days",
        "probability": "0.66",
        "expected_outcome": "NVDA outperforms QQQ by >1.5%",
        "direction": "bullish",
        "benchmark": "QQQ",
        "evidence_sources": ["market_report"],
        "evidence_refs": [],
        "setup": "overnight_tradingagents",
        "regime": "unknown",
        "confidence": "0.32",
        "created_at": "2026-06-01T12:00:00+00:00",
        "resolve_after": "2026-06-08T12:00:00+00:00",
        "source_packet_id": "overnight-test",
        "resolved": True,
        "outcome": True,
        "actual_return": "10.00",
        "benchmark_return": "2.00",
        "relative_return": "8.00",
        "brier_score": "0.1156",
        "agent_score_delta": "0.16",
        "resolved_at": "2026-06-08T12:00:00+00:00",
        "resolution_note": "resolved against relative return window",
    }
    ledger_path.write_text(json.dumps(forecast) + "\n", encoding="utf-8")
    telemetry_dir = tmp_path / "model_telemetry"
    telemetry_dir.mkdir()
    (telemetry_dir / "model-telemetry-test.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "packet_id": "model-telemetry-test",
                "analysis_only": True,
                "generated_at": "2026-06-01T15:00:00+00:00",
                "source_refs": ["forecast-helped"],
                "freshness": {},
                "tool_route": "model_routing",
                "redaction_status": "redacted",
                "run_id": "model-helped",
                "provider": "codex",
                "model": "chatgpt-codex",
                "route": "codex_or_chatgpt_thread_judgment",
                "status": "fallback",
                "estimated_cost_usd": "0",
            }
        ),
        encoding="utf-8",
    )
    mirror_dir = tmp_path / "research_simulations"
    mirror_dir.mkdir()
    (mirror_dir / "latest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "packet_id": "market-mirror-test",
                "analysis_only": True,
                "generated_at": "2026-06-01T15:00:00+00:00",
                "source_refs": [],
                "freshness": {"execution_authority": "none", "forbidden_effects": ["submit_order"]},
                "tool_route": "market_mirror_clean_room",
                "redaction_status": "no_secrets_seen",
                "scenario_id": "mirror-nvda",
                "symbol": "NVDA",
                "actor_profile_refs": [],
                "consensus": "advisory only",
                "disagreements": [],
                "watch_items": [],
                "confidence": "medium",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "research",
            "outcome-labeling",
            "--ledger-path",
            str(ledger_path),
            "--summary-path",
            str(summary_path),
            "--model-telemetry-dir",
            str(telemetry_dir),
            "--model-telemetry-report-dir",
            str(tmp_path / "model_reports"),
            "--market-mirror-dir",
            str(mirror_dir),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["forecast_count"] == 1
    assert payload["model_telemetry_report"]["resolved_model_run_count"] == 1
    assert payload["model_telemetry_report"]["outcome_counts"]["helped"] == 1
    assert payload["market_mirror"]["outcome_label"] == "hurt"
    assert payload["market_mirror"]["execution_authority"] == "none"
    assert payload["summary_path"] == str(summary_path)
    assert summary_path.exists()
    assert (tmp_path / "model_reports" / "latest.json").exists()


def test_integrations_doctor_redacts_env_and_writes_packet(monkeypatch, tmp_path):
    monkeypatch.setenv("COMPOSIO_API_KEY", "ak_fake_secret_value")
    monkeypatch.setenv("GOOGLE_API_KEY", "AQ.fake-gemini-secret")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mcp_servers.MCP_DOCKER]",
                'command = "docker"',
                'args = ["mcp", "gateway", "run", "--profile", "profile"]',
                "[mcp_servers.MCP_DOCKER.env]",
                'CODEX_HOME = "C:\\cm"',
                "[mcp_servers.composio]",
                'url = "https://mcp.composio.dev/example"',
                "[mcp_servers.alpaca_paper]",
                'command = "python"',
                "[mcp_servers.alpaca_paper.env]",
                'ALPACA_ENV = "paper"',
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "capability_audits"

    result = runner.invoke(
        app,
        [
            "integrations",
            "doctor",
            "--config-path",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--write-packet",
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "ak_fake_secret_value" not in result.stdout
    assert "AQ.fake-gemini-secret" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["secrets_redacted"] is True
    assert payload["env"]["COMPOSIO_API_KEY"]["present"] is True
    assert payload["env"]["COMPOSIO_API_KEY"]["length"] == len("ak_fake_secret_value")
    assert payload["env"]["COMPOSIO_API_KEY"]["source"] == "process"
    assert payload["env"]["COMPOSIO_API_KEY"]["scopes"]["process"] == {
        "present": True,
        "length": len("ak_fake_secret_value"),
    }
    assert payload["env"]["GOOGLE_API_KEY"]["present"] is True
    assert "EODHD_API_TOKEN" in payload["env"]
    assert "FINNHUB_API_KEY" in payload["env"]
    assert "MASSIVE_API_KEY" in payload["env"]
    assert "FMP_API_KEY" in payload["env"]
    assert "SCRAPINGBEE_API_KEY" in payload["env"]
    assert "MARKETAUX_API_KEY" in payload["env"]
    assert "MCP_DOCKER" in payload["codex_config"]["mcp_servers_configured"]
    assert "MCP_DOCKER.env" not in payload["codex_config"]["mcp_servers_configured"]
    assert "alpaca_paper.env" not in payload["codex_config"]["mcp_servers_configured"]
    assert payload["docker_mcp"]["configured"] is True
    assert payload["composio"]["configured"] is True
    assert payload["alpaca_mcp"]["configured_servers"] == ["alpaca_paper"]
    assert payload["integration_registry"]["can_submit_orders"] is False
    assert payload["integration_registry"]["execution_authority"] == "none"
    registry_items = {
        item["name"]: item
        for item in payload["integration_registry"]["integrations"]
    }
    assert registry_items["alphainsider"]["trading_authority"] == "none"
    assert registry_items["binance_public"]["status"] == "requires_runtime_check"
    assert registry_items["binance_public"]["write_authority"] == "none"
    packet_path = Path(payload["packet_path"])
    packet_text = packet_path.read_text(encoding="utf-8")
    latest_text = (output_dir / "latest.json").read_text(encoding="utf-8")
    compact_text = (output_dir / "latest-compact.json").read_text(encoding="utf-8")
    compact_payload = json.loads(compact_text)
    assert "ak_fake_secret_value" not in packet_text
    assert "AQ.fake-gemini-secret" not in packet_text
    assert "ak_fake_secret_value" not in compact_text
    assert "AQ.fake-gemini-secret" not in compact_text
    assert json.loads(latest_text)["kind"] == "integration_capability_audit"
    assert compact_payload["schema"] == "compact_integration_capability_audit_v1"
    assert compact_payload["raw_packet_path"] == str(packet_path)
    assert compact_payload["secrets_redacted"] is True
    assert compact_payload["env_present_count"] >= 2
    assert compact_payload["docker_mcp_configured"] is True
    assert compact_payload["composio_configured"] is True
    assert compact_payload["can_submit_orders"] is False
    assert compact_payload["execution_authority"] == "none"
