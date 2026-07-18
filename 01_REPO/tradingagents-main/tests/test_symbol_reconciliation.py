import json
from decimal import Decimal

import pytest

from tradingagents.brokers import alpaca_reconciliation


class ReadOnlyBrokerSpy:
    def __init__(self, positions, orders):
        self.positions = positions
        self.orders = orders
        self.write_calls = []

    def list_positions(self):
        return self.positions

    def list_orders(self, status="all"):
        return self.orders

    def get_order_by_client_order_id(self, client_order_id):
        return next(
            (item for item in self.orders if item.get("client_order_id") == client_order_id),
            None,
        )

    def submit_order(self, *args, **kwargs):
        self.write_calls.append(("submit", args, kwargs))
        raise AssertionError("reconciliation attempted a broker write")

    def cancel_order(self, *args, **kwargs):
        self.write_calls.append(("cancel", args, kwargs))
        raise AssertionError("reconciliation attempted a broker write")


def _reconcile_symbol_incident(**kwargs):
    return alpaca_reconciliation.reconcile_symbol_incident(**kwargs)


def _packet(path, *, symbol="NFLX", client_order_id="ta-tiny-nflx-1", count=None):
    packet = {
        "actions": [
            {
                "symbol": symbol,
                "side": "buy",
                "account": "live",
                "idempotency_key": client_order_id,
            }
        ],
        "submitted": [
            {
                "client_order_id": client_order_id,
                "symbol": symbol,
                "side": "buy",
                "type": "limit",
                "qty": "1",
                "limit_price": "10.00",
                "status": "accepted",
            }
        ],
    }
    if count is not None:
        packet["submitted_order_count"] = count
    path.write_text(json.dumps(packet), encoding="utf-8")
    return path


def _order(symbol="NFLX", client_order_id="ta-tiny-nflx-1", **overrides):
    return {
        "client_order_id": client_order_id,
        "symbol": symbol,
        "side": "buy",
        "type": "limit",
        "qty": "1",
        "limit_price": "10.00",
        "status": "accepted",
        **overrides,
    }


def test_reconcile_symbol_incident_matches_nflx_without_broker_writes(tmp_path):
    packet_path = _packet(tmp_path / "nflx.json")
    spy = ReadOnlyBrokerSpy(
        positions=[{"symbol": "NFLX", "qty": "1"}],
        orders=[_order()],
    )

    result = _reconcile_symbol_incident(
        symbol=" nflx ",
        packet_paths=[packet_path],
        live_client=spy,
        expected_qty=Decimal("1"),
    )

    assert result.symbol == "NFLX"
    assert result.matched is True
    assert result.position["qty"] == "1"
    assert result.checked_client_order_ids == ["ta-tiny-nflx-1"]
    assert result.read_only is True
    assert result.broker_write_calls == 0
    assert spy.write_calls == []


def test_reconcile_symbol_incident_matches_orcl_and_filters_state_to_symbol(tmp_path):
    packet_path = _packet(tmp_path / "orcl.json", symbol="ORCL", client_order_id="ta-tiny-orcl-1")
    spy = ReadOnlyBrokerSpy(
        positions=[{"symbol": "ORCL", "qty": "0.320946047"}, {"symbol": "AMD", "qty": "3"}],
        orders=[
            _order("ORCL", "ta-tiny-orcl-1", filled_qty="0", status="accepted"),
            _order("AMD", "amd-unrelated", filled_qty="2", status="filled"),
        ],
    )

    result = _reconcile_symbol_incident(
        symbol="orcl",
        packet_paths=[packet_path],
        live_client=spy,
        expected_qty="0.320946047",
    )

    assert result.matched is True
    assert result.position["symbol"] == "ORCL"
    assert all(order["symbol"] == "ORCL" for order in result.open_orders)
    assert result.recent_fills == []
    assert result.broker_write_calls == 0
    assert spy.write_calls == []


@pytest.mark.parametrize("symbol", ["", "   ", "NFLX/ORCL", "$$$"])
def test_reconcile_symbol_incident_rejects_empty_or_invalid_symbols_deterministically(symbol):
    spy = ReadOnlyBrokerSpy(positions=[], orders=[])

    with pytest.raises(ValueError, match="invalid symbol"):
        _reconcile_symbol_incident(symbol=symbol, packet_paths=[], live_client=spy)

    assert spy.write_calls == []


def test_reconcile_symbol_incident_reports_unexpected_open_order_without_cleanup(tmp_path):
    packet_path = _packet(tmp_path / "nflx.json")
    spy = ReadOnlyBrokerSpy(
        positions=[{"symbol": "NFLX", "qty": "0"}],
        orders=[
            _order("NFLX", "unexpected-nflx", status="open"),
            _order(
                "NFLX",
                "unexpected-filled-nflx",
                status="filled",
                filled_qty="1",
            ),
        ],
    )

    result = _reconcile_symbol_incident(
        symbol="NFLX",
        packet_paths=[packet_path],
        live_client=spy,
        expected_qty="0",
    )

    assert result.matched is False
    assert "previous live order missing at broker: ta-tiny-nflx-1" in result.issues
    assert "unexpected open order at broker: unexpected-nflx" in result.issues
    assert "unexpected recent fill at broker: unexpected-filled-nflx" in result.issues
    assert result.broker_write_calls == 0
    assert spy.write_calls == []


def test_reconcile_symbol_incident_treats_malformed_packet_evidence_as_issue(tmp_path):
    packet_path = tmp_path / "malformed.json"
    packet_path.write_text("{not-json", encoding="utf-8")
    spy = ReadOnlyBrokerSpy(positions=[{"symbol": "NFLX", "qty": "0"}], orders=[])

    result = _reconcile_symbol_incident(
        symbol="NFLX",
        packet_paths=[packet_path],
        live_client=spy,
        expected_qty="0",
    )

    assert result.matched is False
    assert result.issues == [f"packet read issue for {packet_path}: invalid_json"]
    assert result.broker_write_calls == 0
    assert spy.write_calls == []


def test_reconcile_symbol_incident_reports_position_mismatch_and_cross_symbol_packet_order(tmp_path):
    packet_path = _packet(tmp_path / "nflx.json")
    spy = ReadOnlyBrokerSpy(
        positions=[{"symbol": "NFLX", "qty": "0.5"}],
        orders=[_order("AMD", "ta-tiny-nflx-1")],
    )

    result = _reconcile_symbol_incident(
        symbol="NFLX",
        packet_paths=[packet_path],
        live_client=spy,
        expected_qty="1",
    )

    assert result.matched is False
    assert "position mismatch for NFLX: expected 1 got 0.5" in result.issues
    assert any("symbol mismatch" in issue for issue in result.issues)
    assert result.open_orders == []
    assert result.broker_write_calls == 0
    assert spy.write_calls == []


def test_reconcile_symbol_incident_reports_count_without_client_order_id(tmp_path):
    packet_path = _packet(tmp_path / "nflx.json", count=2)
    spy = ReadOnlyBrokerSpy(
        positions=[{"symbol": "NFLX", "qty": "1"}],
        orders=[_order()],
    )

    result = _reconcile_symbol_incident(
        symbol="NFLX",
        packet_paths=[packet_path],
        live_client=spy,
        expected_qty="1",
    )

    assert result.matched is False
    assert result.issues == [
        "previous packet recorded live submission evidence without client_order_id; "
        "manual reconciliation required"
    ]
    assert result.broker_write_calls == 0
    assert spy.write_calls == []
