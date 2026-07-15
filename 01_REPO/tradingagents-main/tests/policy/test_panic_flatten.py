"""C3: panic-flatten kill switch. Uses a fake broker client; touches no real broker.

Verifies: dry-run is the default; a winner passes the full guard; a loss position
with no evidence is BLOCKED (the guard is not bypassed); a confirmed run submits the
guard-passing sells, cancels opens, freezes live after, and queues an email; and the
confirm/env gating truly gates submission.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from pathlib import Path

from tradingagents.policy import panic_flatten
from tradingagents.policy.live_control import load_live_control_state

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


def _write_envelope(path: Path) -> None:
    path.write_text(
        "\n".join([
            "account_max_capital_at_risk_usd: 250.00",
            "per_name_cap_usd: 50.00",
            "per_sector_cap_pct: 0.20",
            "aggregate_beta_cap: 1.25",
            "daily_loss_halt_usd: 25.00",
            "max_drawdown_halt_pct: 0.05",
            "tiny_live_tranche_usd: 25.00",
            "tiny_live_max_loss_usd: 5.00",
            "new_sleeve_auto_promote: false",
            "alert_email: ops@example.com",
        ]),
        encoding="utf-8",
    )


def _write_promotion(path: Path) -> None:
    path.write_text(json.dumps({"sleeves": {"pullback-support": {
        "stage": "tiny_live_eligible", "live_enabled": True, "preregistered": True,
        "ci_green": True, "shadow_confirmed": True, "benchmark_gate_passed": True,
        "cost_gate_passed": True, "recent_alpha_gate_passed": True,
        "capacity_gate_passed": True,
        "validation_report_ref": "results/validation/pullback-support.json",
        "risk_envelope_ref": "config/risk_envelope.yaml",
    }}}), encoding="utf-8")


def _write_control(path: Path, *, frozen: bool = False) -> None:
    path.write_text(json.dumps({
        "frozen": frozen, "reason": "test",
        "dead_man_expires_at": "2026-07-17T12:00:00+00:00",
    }), encoding="utf-8")


class FakeLiveClient:
    def __init__(self, positions, open_orders):
        self._positions = positions
        self._open_orders = open_orders
        self.submitted: list[dict] = []
        self.canceled: list[str] = []

    def list_positions(self):
        return list(self._positions)

    def list_orders(self, status="open"):
        return list(self._open_orders)

    def get_account(self):
        return {"buying_power": "1000.00"}

    def get_clock(self):
        return {"timestamp": NOW.isoformat(), "is_open": True}

    def list_calendar(self, *, start, end):
        return [{"date": start}]

    def cancel_order(self, order_id):
        self.canceled.append(str(order_id))
        return {"id": order_id, "status": "canceled"}

    def submit_order(self, order):
        response = {"id": f"srv-{len(self.submitted)}", "status": "accepted", **dict(order)}
        self.submitted.append(response)
        return response


WINNER = {"symbol": "MSFT", "qty": "0.05", "avg_entry_price": "400.00", "current_price": "500.00"}
LOSER = {"symbol": "NFLX", "qty": "0.10", "avg_entry_price": "100.00", "current_price": "88.00"}


def _paths(tmp_path: Path):
    env = tmp_path / "risk_envelope.yaml"
    promo = tmp_path / "promotion_state.json"
    control = tmp_path / "live_control.json"
    _write_envelope(env)
    _write_promotion(promo)
    _write_control(control)
    return {
        "risk_envelope_path": env,
        "promotion_state_path": promo,
        "control_state_path": control,
        "lock_path": tmp_path / "submit.lock",
        "outbox_dir": tmp_path / "outbox",
    }


def test_dry_run_is_default_and_changes_nothing(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    client = FakeLiveClient([WINNER], [])
    result = panic_flatten.run_panic_flatten(
        live_client=client, now=NOW, discount_pct=Decimal("0.3"), **paths
    )
    assert result.dry_run is True
    assert result.submitted == []
    assert result.froze_live is False
    assert client.submitted == []
    # Control file is untouched (still not frozen).
    state, _ = load_live_control_state(paths["control_state_path"], now=NOW)
    assert state["frozen"] is False
    assert "MSFT" in result.plan.submittable_symbols


def test_loss_position_without_evidence_is_blocked(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    client = FakeLiveClient([LOSER], [])
    result = panic_flatten.run_panic_flatten(
        live_client=client, now=NOW, discount_pct=Decimal("0.3"), **paths
    )
    assert "NFLX" in result.plan.blocked_symbols
    assert "NFLX" not in result.plan.submittable_symbols
    blocked_line = next(ln for ln in result.plan.lines if ln.symbol == "NFLX")
    assert blocked_line.block_reasons  # the guard explained why


def test_confirmed_run_submits_winner_cancels_freezes_emails(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    open_order = {"id": "o1", "client_order_id": "open-1", "symbol": "MSFT"}
    client = FakeLiveClient([WINNER], [open_order])
    result = panic_flatten.run_panic_flatten(
        live_client=client, confirm="FLATTEN", submit_enabled=True,
        now=NOW, discount_pct=Decimal("0.3"), email=True, **paths
    )
    assert result.dry_run is False
    assert result.operational_guard_ok is True
    assert len(result.submitted) == 1
    assert result.submitted[0]["symbol"] == "MSFT"
    assert result.submitted[0]["side"] == "sell"
    assert result.canceled == ["o1"]
    assert result.froze_live is True
    assert result.email_queued is True
    # Live is frozen AFTER selling.
    state, issues = load_live_control_state(paths["control_state_path"], now=NOW)
    assert state["frozen"] is True
    assert any("frozen" in i for i in issues)
    # An email landed in the outbox.
    assert list((paths["outbox_dir"]).glob("outbox-*.json"))


def test_confirmed_run_does_not_submit_blocked_loss(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    client = FakeLiveClient([LOSER], [])
    result = panic_flatten.run_panic_flatten(
        live_client=client, confirm="FLATTEN", submit_enabled=True,
        now=NOW, discount_pct=Decimal("0.3"), **paths
    )
    assert client.submitted == []           # loss gate held; nothing force-sold
    assert result.froze_live is True         # but the system still stood down
    assert "NFLX" in result.plan.blocked_symbols


def test_confirm_word_and_env_both_required(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    # Right word, submit disabled -> dry run.
    c1 = FakeLiveClient([WINNER], [])
    r1 = panic_flatten.run_panic_flatten(
        live_client=c1, confirm="FLATTEN", submit_enabled=False, now=NOW,
        discount_pct=Decimal("0.3"), **paths
    )
    assert r1.dry_run is True and c1.submitted == []
    # Env enabled, wrong word -> dry run.
    c2 = FakeLiveClient([WINNER], [])
    r2 = panic_flatten.run_panic_flatten(
        live_client=c2, confirm="yes", submit_enabled=True, now=NOW,
        discount_pct=Decimal("0.3"), **paths
    )
    assert r2.dry_run is True and c2.submitted == []


def test_already_frozen_blocks_all_submits(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_control(paths["control_state_path"], frozen=True)
    client = FakeLiveClient([WINNER], [])
    result = panic_flatten.run_panic_flatten(
        live_client=client, confirm="FLATTEN", submit_enabled=True, now=NOW,
        discount_pct=Decimal("0.3"), **paths
    )
    assert client.submitted == []            # frozen blocks even the winner
    assert "MSFT" in result.plan.blocked_symbols
