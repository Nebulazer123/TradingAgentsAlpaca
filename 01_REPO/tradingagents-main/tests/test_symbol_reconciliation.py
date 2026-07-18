import json
from decimal import Decimal

import pytest

from tradingagents.brokers import alpaca_reconciliation


class ReadOnlyBrokerSpy:
    def __init__(self, positions, orders):
        self.positions = positions
        self.orders = orders
        self.write_calls = []
        self.read_calls = []

    def list_positions(self):
        self.read_calls.append(("list_positions",))
        return self.positions

    def list_orders(self, status="all"):
        self.read_calls.append(("list_orders", status))
        return self.orders

    def get_order_by_client_order_id(self, client_order_id):
        self.read_calls.append(("get_order_by_client_order_id", client_order_id))
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

    def replace_order(self, *args, **kwargs):
        self.write_calls.append(("replace", args, kwargs))
        raise AssertionError("reconciliation attempted a broker write")

    def close_position(self, *args, **kwargs):
        self.write_calls.append(("close_position", args, kwargs))
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


def test_reconcile_symbol_incident_reports_duplicate_symbol_positions(tmp_path):
    packet_path = _packet(tmp_path / "nflx.json")
    spy = ReadOnlyBrokerSpy(
        positions=[{"symbol": "NFLX", "qty": "1"}, {"symbol": "nflx", "qty": "1"}],
        orders=[_order()],
    )

    result = _reconcile_symbol_incident(
        symbol="NFLX",
        packet_paths=[packet_path],
        live_client=spy,
        expected_qty="1",
    )

    assert result.matched is False
    assert result.position["duplicate_count"] == 2
    assert "duplicate broker positions for NFLX: 2" in result.issues
    assert spy.write_calls == []


@pytest.mark.parametrize(
    ("attribute", "value", "issue"),
    [
        ("list_positions", None, "broker positions read unavailable"),
        ("list_positions", RuntimeError("positions down"), "broker positions read failed"),
        ("list_orders", None, "broker open orders read unavailable"),
        ("list_orders", RuntimeError("orders down"), "broker open orders read failed"),
    ],
)
def test_reconcile_symbol_incident_fails_closed_for_missing_or_failing_broker_reads(
    tmp_path, attribute, value, issue
):
    packet_path = _packet(tmp_path / "nflx.json")
    spy = ReadOnlyBrokerSpy(positions=[{"symbol": "NFLX", "qty": "1"}], orders=[_order()])
    if isinstance(value, Exception):
        setattr(spy, attribute, lambda *args, **kwargs: (_ for _ in ()).throw(value))
    else:
        setattr(spy, attribute, value)

    result = _reconcile_symbol_incident(
        symbol="NFLX",
        packet_paths=[packet_path],
        live_client=spy,
        expected_qty="1",
    )

    assert result.matched is False
    assert any(issue in item for item in result.issues)
    assert spy.write_calls == []


def test_reconcile_symbol_incident_fails_closed_for_non_sequence_order_read(tmp_path):
    packet_path = _packet(tmp_path / "nflx.json")
    spy = ReadOnlyBrokerSpy(positions=[{"symbol": "NFLX", "qty": "1"}], orders=[_order()])
    spy.list_orders = lambda status="all": {"not": "a sequence"}

    result = _reconcile_symbol_incident(
        symbol="NFLX",
        packet_paths=[packet_path],
        live_client=spy,
        expected_qty="1",
    )

    assert result.matched is False
    assert any("broker open orders read returned non-sequence" in item for item in result.issues)
    assert any("broker all orders read returned non-sequence" in item for item in result.issues)
    assert spy.write_calls == []


@pytest.mark.parametrize("expected_qty", ["NaN", "Infinity", "-1", "not-a-number"])
def test_reconcile_symbol_incident_rejects_invalid_expected_quantity_before_broker_reads(
    expected_qty,
):
    spy = ReadOnlyBrokerSpy(positions=[], orders=[])

    result = _reconcile_symbol_incident(
        symbol="NFLX",
        packet_paths=[],
        live_client=spy,
        expected_qty=expected_qty,
    )

    assert result.matched is False
    assert result.issues == [f"invalid expected quantity: {expected_qty}"]
    assert spy.read_calls == []
    assert spy.write_calls == []


@pytest.mark.parametrize("broker_qty", ["NaN", "Infinity", "-1", "not-a-number"])
def test_reconcile_symbol_incident_rejects_invalid_broker_position_quantity(tmp_path, broker_qty):
    packet_path = _packet(tmp_path / "nflx.json")
    spy = ReadOnlyBrokerSpy(
        positions=[{"symbol": "NFLX", "qty": broker_qty}],
        orders=[_order()],
    )

    result = _reconcile_symbol_incident(
        symbol="NFLX",
        packet_paths=[packet_path],
        live_client=spy,
        expected_qty="1",
    )

    assert result.matched is False
    assert "invalid broker position quantity for NFLX" in result.issues
    assert spy.write_calls == []


def test_reconcile_symbol_incident_scopes_submission_count_to_symbol(tmp_path):
    packet_path = tmp_path / "mixed.json"
    packet_path.write_text(
        json.dumps(
            {
                "submitted_order_count": 2,
                "actions": [
                    {"symbol": "NFLX", "account": "live", "idempotency_key": "nflx-1"},
                    {"symbol": "AMD", "account": "live", "idempotency_key": "amd-1"},
                ],
                "submitted": [
                    _order("NFLX", "nflx-1"),
                    _order("AMD", "amd-1"),
                ],
            }
        ),
        encoding="utf-8",
    )
    spy = ReadOnlyBrokerSpy(
        positions=[{"symbol": "NFLX", "qty": "1"}],
        orders=[_order("NFLX", "nflx-1"), _order("AMD", "amd-1")],
    )

    result = _reconcile_symbol_incident(
        symbol="NFLX",
        packet_paths=[packet_path],
        live_client=spy,
        expected_qty="1",
    )

    assert result.matched is True
    assert result.checked_client_order_ids == ["nflx-1"]
    assert spy.write_calls == []


def test_reconcile_symbol_incident_deduplicates_repeated_ids_and_reports_conflicts(tmp_path):
    first = _packet(tmp_path / "first.json", client_order_id="nflx-1")
    second = _packet(tmp_path / "second.json", client_order_id="nflx-1")
    conflicting = _packet(tmp_path / "conflicting.json", client_order_id="nflx-1")
    conflicting_payload = json.loads(conflicting.read_text(encoding="utf-8"))
    conflicting_payload["submitted"][0]["side"] = "sell"
    conflicting.write_text(json.dumps(conflicting_payload), encoding="utf-8")
    spy = ReadOnlyBrokerSpy(
        positions=[{"symbol": "NFLX", "qty": "1"}],
        orders=[_order("NFLX", "nflx-1")],
    )

    clean = _reconcile_symbol_incident(
        symbol="NFLX",
        packet_paths=[first, second],
        live_client=spy,
        expected_qty="1",
    )
    conflict = _reconcile_symbol_incident(
        symbol="NFLX",
        packet_paths=[first, conflicting],
        live_client=spy,
        expected_qty="1",
    )

    assert clean.matched is True
    assert clean.checked_client_order_ids == ["nflx-1"]
    assert conflict.matched is False
    assert any("conflicting packet evidence for nflx-1" in item for item in conflict.issues)
    assert spy.write_calls == []


def test_reconcile_symbol_incident_rejects_explicit_broker_account_conflict(tmp_path):
    packet_path = _packet(tmp_path / "nflx.json")
    spy = ReadOnlyBrokerSpy(
        positions=[{"symbol": "NFLX", "qty": "1"}],
        orders=[_order(account="paper")],
    )

    result = _reconcile_symbol_incident(
        symbol="NFLX",
        packet_paths=[packet_path],
        live_client=spy,
        expected_qty="1",
    )

    assert result.matched is False
    assert "previous live order account mismatch for ta-tiny-nflx-1: expected live got paper" in result.issues
    assert spy.write_calls == []
