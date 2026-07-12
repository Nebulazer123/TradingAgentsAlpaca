import json
from pathlib import Path

from typer.testing import CliRunner

from cli import main as cli_main
from cli.main import app
from tradingagents.brokers.alpaca_reconciliation import (
    classify_orcl_old_sell_state,
    reconcile_orcl_sell_state,
)

runner = CliRunner()


class _FakeAlpacaLiveClient:
    def __init__(
        self,
        *,
        positions: list[dict],
        open_orders: list[dict],
        all_orders: list[dict],
        by_client_order_id: dict[str, dict],
    ):
        self._positions = positions
        self._open_orders = open_orders
        self._all_orders = all_orders
        self._by_client_order_id = by_client_order_id

    def get_account(self):
        return {"id": "fake-live"}

    def list_positions(self):
        return list(self._positions)

    def list_orders(self, status: str | None = None):
        if status == "open":
            return list(self._open_orders)
        if status == "all":
            return list(self._all_orders)
        return list(self._all_orders)

    def get_order_by_client_order_id(self, client_order_id: str):
        return self._by_client_order_id.get(client_order_id)


def test_classify_orcl_old_sell_state_prefers_filled_status():
    assert (
        classify_orcl_old_sell_state(
            [
                {"status": "new", "filled_qty": "0", "submitted_at": "2026-06-01T10:00:00Z"},
                {"status": "closed", "filled_qty": "0", "submitted_at": "2026-06-02T10:00:00Z"},
                {
                    "status": "partially_filled",
                    "filled_qty": "2",
                    "submitted_at": "2026-06-03T10:00:00Z",
                },
            ]
        )
        == "filled"
    )


def test_classify_orcl_old_sell_state_handles_closed_canceled_unknown():
    assert (
        classify_orcl_old_sell_state(
            [
                {"status": "canceled", "filled_qty": "0"},
            ]
        )
        == "canceled"
    )
    assert (
        classify_orcl_old_sell_state(
            [
                {"status": "closed", "filled_qty": "0"},
            ]
        )
        == "closed"
    )
    assert (
        classify_orcl_old_sell_state(
            [
                {"status": "accepted", "filled_qty": "0"},
            ]
        )
        == "unknown"
    )


def test_reconcile_orcl_sell_state_builds_incident_evidence(tmp_path: Path):
    packet = {
        "submitted": [
            {
                "client_order_id": "orcl-old-1",
                "symbol": "ORCL",
                "side": "sell",
                "qty": "12",
                "notional": "1200",
                "status": "new",
                "submitted_at": "2026-06-01T09:00:00Z",
                "filled_qty": "0",
            }
        ],
        "reconciled_orders": [
            {
                "account": "live",
                "order": {
                    "client_order_id": "orcl-old-1",
                    "symbol": "ORCL",
                    "side": "sell",
                    "status": "canceled",
                    "submitted_at": "2026-06-01T09:15:00Z",
                    "filled_qty": "0",
                },
            }
        ],
    }
    packet_path = tmp_path / "orcl_incident.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    broker_order = {
        "client_order_id": "orcl-old-1",
        "symbol": "ORCL",
        "side": "sell",
        "status": "filled",
        "qty": "12",
        "filled_qty": "12",
        "filled_at": "2026-06-01T09:20:00Z",
        "filled_avg_price": "101.10",
        "submitted_at": "2026-06-01T09:00:00Z",
        "notional": "1213.20",
    }

    live_client = _FakeAlpacaLiveClient(
        positions=[
            {
                "symbol": "ORCL",
                "qty": "12",
                "notional": "1213.20",
                "market_value": "1213.20",
                "avg_entry_price": "101.10",
            }
        ],
        open_orders=[
            {
                "client_order_id": "orcl-open-1",
                "symbol": "ORCL",
                "side": "sell",
                "status": "new",
                "qty": "1",
                "notional": "100",
            },
            {
                "client_order_id": "amd-open-1",
                "symbol": "AMD",
                "side": "sell",
                "status": "new",
                "qty": "1",
                "notional": "100",
            },
        ],
        all_orders=[
            {
                "client_order_id": "fill-orcl-2",
                "symbol": "ORCL",
                "side": "sell",
                "status": "filled",
                "qty": "5",
                "filled_qty": "5",
                "filled_at": "2026-06-01T10:10:00Z",
                "submitted_at": "2026-06-01T10:00:00Z",
            },
            {
                "client_order_id": "fill-orcl-1",
                "symbol": "ORCL",
                "side": "sell",
                "status": "filled",
                "qty": "3",
                "filled_qty": "3",
                "filled_at": "2026-06-01T10:20:00Z",
                "submitted_at": "2026-06-01T10:15:00Z",
            },
            {
                "client_order_id": "fill-amd-1",
                "symbol": "AMD",
                "side": "sell",
                "status": "filled",
                "qty": "2",
                "filled_qty": "2",
            },
        ],
        by_client_order_id={"orcl-old-1": broker_order},
    )

    evidence = reconcile_orcl_sell_state(
        [packet_path],
        live_client=live_client,
        symbol="orcl",
        max_recent_fills=2,
    )

    assert evidence["order_packet_paths"] == [str(packet_path)]
    assert evidence["final_old_sell_state"] == "filled"
    assert evidence["current_orcl_position"]["symbol"] == "ORCL"
    assert evidence["current_orcl_position"]["qty"] == "12"
    assert evidence["current_orcl_position"]["notional"] == "1213.20"
    assert len(evidence["open_orcl_orders"]) == 1
    assert evidence["open_orcl_orders"][0]["client_order_id"] == "orcl-open-1"
    assert len(evidence["recent_orcl_fills"]) == 2
    assert evidence["recent_orcl_fills"][0]["client_order_id"] == "fill-orcl-1"
    assert evidence["recent_orcl_fills"][1]["client_order_id"] == "fill-orcl-2"
    assert evidence["old_sell_orders"][0]["client_order_id"] == "orcl-old-1"
    assert evidence["old_sell_orders"][0]["status"] == "filled"
    assert evidence["old_sell_orders"][0]["filled_qty"] == "12"


def test_alpaca_reconcile_orcl_incident_cli_command(monkeypatch, tmp_path: Path):
    packet = {
        "submitted": [
            {
                "client_order_id": "orcl-cli-1",
                "symbol": "ORCL",
                "side": "sell",
                "status": "new",
                "submitted_at": "2026-06-01T09:00:00Z",
                "filled_qty": "0",
            }
        ]
    }
    packet_path = tmp_path / "incident.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    live_client = _FakeAlpacaLiveClient(
        positions=[
            {
                "symbol": "ORCL",
                "qty": "-4",
                "notional": "402.40",
                "market_value": "-402.40",
            }
        ],
        open_orders=[
            {
                "client_order_id": "orcl-open-cli",
                "symbol": "ORCL",
                "status": "open",
                "side": "sell",
                "qty": "4",
            }
        ],
        all_orders=[
            {
                "client_order_id": "orcl-fill-cli",
                "symbol": "ORCL",
                "side": "sell",
                "status": "filled",
                "qty": "4",
                "filled_qty": "4",
                "filled_at": "2026-06-01T09:40:00Z",
            }
        ],
        by_client_order_id={"orcl-cli-1": {"client_order_id": "orcl-cli-1", "status": "closed"}},
    )

    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: live_client)
    result = runner.invoke(
        app,
        [
            "alpaca",
            "reconcile-orcl-incident",
            str(packet_path),
            "--json-output",
            "--output-dir",
            str(tmp_path / "orcl_reconciliation"),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["final_old_sell_state"] == "closed"
    assert payload["current_orcl_position"]["qty"] == "-4"
    assert payload["recent_orcl_fills"][0]["client_order_id"] == "orcl-fill-cli"
