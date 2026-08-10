import datetime
import json
import os
from decimal import Decimal

from tradingagents.execution.clock import evaluate_clock_guard
from tradingagents.execution.lock import acquire_execution_lock, release_execution_lock
from tradingagents.execution.reconcile import (
    reconcile_latest_packet_live_orders,
    reconcile_live_state,
)
from tradingagents.execution.tiny_live import acquire_tiny_live_operational_guard

UTC = datetime.timezone.utc


def test_execution_lock_allows_single_writer_and_release(tmp_path):
    lock_path = tmp_path / "live.lock"

    first = acquire_execution_lock(lock_path, owner="run-1")
    second = acquire_execution_lock(lock_path, owner="run-2")
    release_execution_lock(lock_path, owner="run-1")
    third = acquire_execution_lock(lock_path, owner="run-3")

    assert first.acquired is True
    assert second.acquired is False
    assert "already exists" in second.reason
    assert third.acquired is True


def test_execution_lock_reclaims_stale_lock(tmp_path):
    lock_path = tmp_path / "live.lock"
    lock_path.write_text("{}", encoding="utf-8")
    old_time = datetime.datetime.now(tz=UTC).timestamp() - 3600
    os.utime(lock_path, (old_time, old_time))

    result = acquire_execution_lock(lock_path, owner="run-2", stale_after_seconds=1)

    assert result.acquired is True


def test_reconcile_live_state_matches_expected_broker_state():
    result = reconcile_live_state(
        expected_positions={"MSFT": Decimal("1.5")},
        broker_positions=[{"symbol": "MSFT", "qty": "1.5"}],
        expected_open_client_order_ids={"order-1"},
        broker_open_orders=[{"client_order_id": "order-1"}],
    )

    assert result.matched is True
    assert result.issues == []


def test_reconcile_live_state_tolerates_fractional_share_rounding_dust():
    result = reconcile_live_state(
        expected_positions={"MSFT": Decimal("0.11778674")},
        broker_positions=[
            {"symbol": "MSFT", "qty": "0.117787"},
            {"symbol": "AAPL", "qty": "0.0000004"},
        ],
        expected_open_client_order_ids=set(),
        broker_open_orders=[],
    )

    assert result.matched is True
    assert result.issues == []


def test_reconcile_live_state_reports_position_and_order_mismatch():
    result = reconcile_live_state(
        expected_positions={"MSFT": Decimal("1.5")},
        broker_positions=[
            {"symbol": "MSFT", "qty": "1.0"},
            {"symbol": "AAPL", "qty": "2"},
        ],
        expected_open_client_order_ids={"order-1"},
        broker_open_orders=[{"client_order_id": "order-2"}],
    )

    assert result.matched is False
    reasons = "\n".join(result.issues)
    assert "position mismatch for MSFT" in reasons
    assert "unexpected live position for AAPL" in reasons
    assert "expected open order missing" in reasons
    assert "unexpected open order" in reasons


def test_reconcile_latest_packet_live_orders_matches_prior_submitted_order():
    packet = {
        "actions": [
            {
                "symbol": "AMZN",
                "side": "buy",
                "account": "live",
                "idempotency_key": "ta-tiny-prior",
            }
        ],
        "submitted": [
            {
                "client_order_id": "ta-tiny-prior",
                "symbol": "AMZN",
                "side": "buy",
                "type": "limit",
                "notional": "50.00",
                "limit_price": "208.41",
                "status": "new",
            }
        ],
    }

    result = reconcile_latest_packet_live_orders(
        packet,
        order_lookup=lambda _: {
            "client_order_id": "ta-tiny-prior",
            "symbol": "AMZN",
            "side": "buy",
            "type": "limit",
            "notional": "50.00",
            "limit_price": "208.41",
            "status": "accepted",
        },
    )

    assert result.matched is True
    assert result.issues == []
    assert result.checked_client_order_ids == ["ta-tiny-prior"]


def test_reconcile_latest_packet_live_orders_blocks_missing_prior_live_order():
    packet = {
        "actions": [
            {
                "symbol": "AMZN",
                "side": "buy",
                "account": "live",
                "idempotency_key": "ta-tiny-missing",
            }
        ],
        "submitted": [
            {
                "client_order_id": "ta-tiny-missing",
                "symbol": "AMZN",
                "side": "buy",
                "type": "limit",
                "notional": "50.00",
                "limit_price": "208.41",
                "status": "new",
            }
        ],
    }

    result = reconcile_latest_packet_live_orders(packet, order_lookup=lambda _: None)

    assert result.matched is False
    assert result.checked_client_order_ids == ["ta-tiny-missing"]
    assert result.issues == ["previous live order missing at broker: ta-tiny-missing"]


def test_reconcile_latest_packet_live_orders_reads_nested_live_response():
    packet = {
        "submitted": [
            {
                "paper_response": {
                    "client_order_id": "ta-hourly-paper-amzn",
                    "symbol": "AMZN",
                    "side": "buy",
                },
                "live_response": {
                    "client_order_id": "ta-tiny-nested-live",
                    "symbol": "AMZN",
                    "side": "buy",
                    "type": "limit",
                    "notional": "50.00",
                    "limit_price": "208.41",
                },
            }
        ],
    }

    result = reconcile_latest_packet_live_orders(
        packet,
        order_lookup=lambda _: {
            "client_order_id": "ta-tiny-nested-live",
            "symbol": "AMZN",
            "side": "buy",
            "type": "limit",
            "notional": "50.00",
            "limit_price": "208.41",
            "status": "accepted",
        },
    )

    assert result.matched is True
    assert result.issues == []
    assert result.checked_client_order_ids == ["ta-tiny-nested-live"]


def test_reconcile_latest_packet_live_orders_blocks_count_only_submission_evidence():
    packet = {
        "decision": "buy",
        "submitted_order_count": 1,
        "submitted": [],
    }

    result = reconcile_latest_packet_live_orders(packet, order_lookup=lambda _: None)

    assert result.matched is False
    assert result.checked_client_order_ids == []
    assert result.issues == [
        "previous packet recorded live submission evidence without client_order_id; manual reconciliation required"
    ]


def test_clock_guard_blocks_large_skew():
    ok = evaluate_clock_guard(
        local_time=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
        reference_time=datetime.datetime(2026, 6, 1, 15, 1, tzinfo=UTC),
        max_skew_seconds=120,
    )
    blocked = evaluate_clock_guard(
        local_time=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
        reference_time=datetime.datetime(2026, 6, 1, 15, 5, tzinfo=UTC),
        max_skew_seconds=120,
    )

    assert ok.allowed is True
    assert blocked.allowed is False
    assert "exceeds" in blocked.reason


def test_tiny_live_operational_guard_blocks_mismatched_broker_state(tmp_path):
    class _LiveClient:
        def get_clock(self):
            return {
                "timestamp": datetime.datetime(2026, 6, 1, 15, 0, tzinfo=UTC).isoformat(),
                "is_open": True,
            }

        def list_positions(self):
            return [{"symbol": "AAPL", "qty": "1"}]

        def list_orders(self, status="open"):
            return []

    result = acquire_tiny_live_operational_guard(
        live_actions=[{"symbol": "MSFT"}],
        live_client=_LiveClient(),
        expected_live_positions=[],
        expected_live_open_orders=[],
        owner="test-run",
        lock_path=tmp_path / "tiny-live.lock",
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
    )

    assert result.allowed is False
    assert result.checks["single_writer_lock"] is True
    assert result.checks["broker_clock"] is True
    assert result.checks["broker_session"] is True
    assert result.checks["reconciliation"] is False
    assert any("unexpected live position for AAPL" in issue.reason for issue in result.issues)


def test_tiny_live_operational_guard_blocks_regular_order_when_broker_clock_closed(tmp_path):
    class _LiveClient:
        def get_clock(self):
            return {
                "timestamp": datetime.datetime(2026, 6, 1, 15, 0, tzinfo=UTC).isoformat(),
                "is_open": False,
            }

        def list_positions(self):
            return []

        def list_orders(self, status="open"):
            return []

    result = acquire_tiny_live_operational_guard(
        live_actions=[{"symbol": "MSFT"}],
        live_client=_LiveClient(),
        expected_live_positions=[],
        expected_live_open_orders=[],
        owner="test-run",
        lock_path=tmp_path / "tiny-live.lock",
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
    )

    assert result.allowed is False
    assert result.checks["broker_clock"] is True
    assert result.checks["broker_session"] is False
    assert any("broker clock reports market is closed" in issue.reason for issue in result.issues)


def test_tiny_live_operational_guard_blocks_extended_order_without_calendar_day(tmp_path):
    class _LiveClient:
        def get_clock(self):
            return {
                "timestamp": datetime.datetime(2026, 6, 1, 12, 0, tzinfo=UTC).isoformat(),
                "is_open": False,
            }

        def list_calendar(self, *, start, end):
            return []

        def list_positions(self):
            return []

        def list_orders(self, status="open"):
            return []

    result = acquire_tiny_live_operational_guard(
        live_actions=[{"symbol": "MSFT", "extended_hours": True}],
        live_client=_LiveClient(),
        expected_live_positions=[],
        expected_live_open_orders=[],
        owner="test-run",
        lock_path=tmp_path / "tiny-live.lock",
        now=datetime.datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )

    assert result.allowed is False
    assert result.checks["broker_clock"] is True
    assert result.checks["broker_session"] is False
    assert any("broker calendar blocked extended-hours submit" in issue.reason for issue in result.issues)


def test_tiny_live_operational_guard_allows_extended_order_on_confirmed_trading_day(tmp_path):
    class _LiveClient:
        def get_clock(self):
            return {
                "timestamp": datetime.datetime(2026, 6, 1, 12, 0, tzinfo=UTC).isoformat(),
                "is_open": False,
            }

        def list_calendar(self, *, start, end):
            return [{"date": start, "open": "09:30", "close": "16:00"}]

        def list_positions(self):
            return []

        def list_orders(self, status="open"):
            return []

    result = acquire_tiny_live_operational_guard(
        live_actions=[{"symbol": "MSFT", "extended_hours": True}],
        live_client=_LiveClient(),
        expected_live_positions=[],
        expected_live_open_orders=[],
        owner="test-run",
        lock_path=tmp_path / "tiny-live.lock",
        now=datetime.datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )

    assert result.allowed is True
    assert result.checks["broker_clock"] is True
    assert result.checks["broker_session"] is True
    assert result.checks["reconciliation"] is True


class _OpenMarketLiveClient:
    def get_clock(self):
        return {
            "timestamp": datetime.datetime(2026, 6, 1, 15, 0, tzinfo=UTC).isoformat(),
            "is_open": True,
        }

    def list_positions(self):
        return []

    def list_orders(self, status="open"):
        return []


def _write_control(path, *, frozen, expires_at):
    path.write_text(
        json.dumps(
            {
                "frozen": frozen,
                "reason": "test control",
                "dead_man_expires_at": expires_at,
            }
        ),
        encoding="utf-8",
    )


def test_tiny_live_operational_guard_blocks_when_dead_man_expired_at_submit(tmp_path):
    control_path = tmp_path / "live_control.json"
    _write_control(
        control_path, frozen=False, expires_at="2026-06-01T14:00:00+00:00"
    )

    result = acquire_tiny_live_operational_guard(
        live_actions=[{"symbol": "MSFT"}],
        live_client=_OpenMarketLiveClient(),
        expected_live_positions=[],
        expected_live_open_orders=[],
        owner="test-run",
        lock_path=tmp_path / "tiny-live.lock",
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
    )

    assert result.allowed is False
    assert result.checks["live_control_recheck"] is False
    assert any("dead-man" in issue.reason for issue in result.issues)


def test_tiny_live_operational_guard_passes_live_control_recheck_when_fresh(tmp_path):
    control_path = tmp_path / "live_control.json"
    _write_control(
        control_path, frozen=False, expires_at="2026-06-01T16:00:00+00:00"
    )

    result = acquire_tiny_live_operational_guard(
        live_actions=[{"symbol": "MSFT"}],
        live_client=_OpenMarketLiveClient(),
        expected_live_positions=[],
        expected_live_open_orders=[],
        owner="test-run",
        lock_path=tmp_path / "tiny-live.lock",
        control_state_path=control_path,
        now=datetime.datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
    )

    assert result.allowed is True
    assert result.checks["live_control_recheck"] is True
