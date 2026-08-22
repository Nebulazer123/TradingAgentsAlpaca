import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app
from tradingagents.evals.execution_board import (
    build_execution_board_review,
    compact_execution_board_review,
    load_hourly_packets,
    write_execution_board_review,
)
from tradingagents.policy.decision_authority import bounded_exit_authority_record

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_tests_from_repository_cwd(tmp_path, monkeypatch):
    """Resolve every production-relative default inside the test's tmp_path."""
    monkeypatch.chdir(tmp_path)


def _write_packet(directory, name, payload):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_exact_incomplete_loss_evidence(tmp_path):
    """Write a Task-1-compatible raw packet that must resolve to HOLD."""
    hourly = tmp_path / "hourly"
    evidence_dir = tmp_path / "loss_review_evidence"
    review = {
        "symbol": "TSM",
        "decision_id": "loss-review-tsm-1",
        "allowed": False,
        "policy_rule_exit": False,
        "allowed_exit_reason": "",
        "allowed_exit_reason_source": "",
        "blockers": ["company evidence is incomplete"],
        "blocked_reasons": ["company evidence is incomplete"],
        "confidence": "0.00",
        "evidence_generated_at": "2026-08-13T15:00:00+00:00",
    }
    hourly_path = _write_packet(
        hourly,
        "hourly-supervisor-20260813-150000.json",
        {
            "generated_at": "2026-08-13T15:00:00+00:00",
            "decision": "loss-review",
            "actions": [],
            "submitted": [],
            "evidence": {"loss_exit_review": review},
            "portfolio": {"live": {"unrealized_pl": "-1.11"}},
        },
    )
    loss_path = _write_packet(
        evidence_dir,
        "loss.json",
        {
            "packet_id": "loss-evidence-tsm-1",
            "generated_at": "2026-08-13T15:00:00+00:00",
            "source_name": "loss_review_evidence",
            "evidence_type": "loss_review_evidence",
            "subject": "TSM",
            "symbol": "TSM",
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
            "payload": {
                "symbol": "TSM",
                "hourly_packet_path": str(hourly_path),
                "supervisor_packet_path": "hourly/hourly-supervisor-20260813-150000.json",
                "supervisor_decision_id": "loss-review-tsm-1",
                "supervisor_review_authority": bounded_exit_authority_record(review),
                "remaining_blockers": ["company evidence is incomplete"],
                "resolved_blockers_by_refresh": [],
                "advisory_analysis": {"requires_board_decision": True},
                "accepted_sources": [],
                "next_action": "autonomous_hold",
            },
        },
    )
    return hourly, evidence_dir, hourly_path, loss_path


def _add_unicode_bound_source(tmp_path, loss_path):
    source_path = _write_packet(
        tmp_path / "sources",
        "unicode.json",
        {
            "packet_id": "source-unicode-1",
            "source_name": "notícias_東京",
            "evidence_type": "company_context_advisory",
            "subject": "TSM",
            "symbol": "TSM",
            "as_of": "2026-08-13T15:00:00+00:00",
            "quality": "medium",
            "payload": {
                "symbol": "TSM",
                "as_of": "2026-08-13T15:00:00+00:00",
            },
        },
    )
    source_bytes = source_path.read_bytes()
    descriptor = {
        "path": source_path.relative_to(tmp_path).as_posix(),
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
        "size_bytes": len(source_bytes),
        "packet_id": "source-unicode-1",
        "source_name": "notícias_東京",
        "evidence_type": "company_context_advisory",
        "as_of": "2026-08-13T15:00:00+00:00",
        "quality": "medium",
    }
    loss = json.loads(loss_path.read_text(encoding="utf-8"))
    loss["payload"]["accepted_sources"] = [descriptor]
    loss_path.write_text(json.dumps(loss), encoding="utf-8")
    compact = {
        "packet": {
            key: descriptor[key] for key in ("path", "sha256", "size_bytes")
        },
        **{
            key: descriptor[key]
            for key in (
                "packet_id",
                "source_name",
                "evidence_type",
                "as_of",
                "quality",
            )
        },
    }
    return compact


def test_execution_board_records_an_immutable_autonomous_hold(tmp_path):
    hourly, evidence_dir, hourly_path, loss_path = _write_exact_incomplete_loss_evidence(tmp_path)
    ledger_root = tmp_path.parent / "installed-decision-ledger"

    review = build_execution_board_review(
        hourly,
        loss_review_evidence_dir=evidence_dir,
        decision_evidence_root=tmp_path,
        decision_ledger_root=ledger_root,
        source_revision="1" * 40,
        now=datetime(2026, 8, 13, 15, 1, tzinfo=UTC),
    )

    decision = review["autonomous_loss_decision"]
    assert review["kind"] == "execution_board_review"
    assert review["schema_version"] == 1
    assert review["analysis_only"] is True
    assert review["execution_authority"] == "none"
    assert review["can_submit_orders"] is False
    assert decision["decision"] == "HOLD"
    assert decision["trade_decision_resolved"] is True
    assert decision["exit_allowed"] is False
    assert decision["execution_authority"] == "none"
    assert decision["can_submit_orders"] is False
    assert decision["ledger_packet_id"]
    assert decision["decision_id"]
    assert decision["symbol"] == "TSM"
    assert decision["supervisor_decision_id"] == "loss-review-tsm-1"
    assert decision["source_revision"] == "1" * 40
    assert decision["accepted_source_count"] == 0
    assert decision["accepted_sources_sha256"] == hashlib.sha256(b"[]").hexdigest()
    assert "ledger_packet_path" not in decision
    assert "decision_evidence_path" not in decision
    assert decision["decision_evidence"]["path"].endswith(
        f"autonomous_loss_board_decisions/{decision['decision_id']}.json"
    )
    assert len(decision["decision_evidence"]["sha256"]) == 64
    assert decision["supervisor_packet"]["path"] == str(hourly_path)
    assert decision["loss_evidence_packet"]["path"] == str(loss_path)
    assert decision["loss_evidence_packet"]["packet_id"] == "loss-evidence-tsm-1"
    assert review["loss_review_evidence"]["next_action"] == "autonomous_hold"
    assert review["loss_review_evidence"]["source_binding"] == {
        "matched": True,
        "issue": None,
        "bindings": {
            "supervisor": {
                "path": "hourly/hourly-supervisor-20260813-150000.json",
                "sha256": decision["supervisor_packet"]["sha256"],
                "size_bytes": decision["supervisor_packet"]["size_bytes"],
                "decision_id": "loss-review-tsm-1",
                "symbol": "TSM",
            },
            "raw_loss": {
                "path": "loss_review_evidence/loss.json",
                "sha256": decision["loss_evidence_packet"]["sha256"],
                "size_bytes": decision["loss_evidence_packet"]["size_bytes"],
                "packet_id": "loss-evidence-tsm-1",
                "symbol": "TSM",
                "source_revision": "1" * 40,
            },
        },
    }
    assert not any("manual" in item["message"].lower() for item in review["warnings"])
    assert loss_path.exists()

    compact = compact_execution_board_review(
        review,
        raw_packet_path=tmp_path / "board.json",
    )
    assert compact["kind"] == "execution_board_review"
    assert compact["schema"] == "compact_execution_board_review_v1"
    assert compact["analysis_only"] is True
    assert compact["can_submit_orders"] is False
    assert compact["execution_authority"] == "none"
    assert compact["autonomous_loss_decision"] == {
        key: decision[key]
        for key in ("decision_id", "ledger_packet_id", "symbol", "decision", "trade_decision_resolved", "execution_eligible", "exit_allowed")
    }
    assert compact["loss_review_evidence"] == {
        key: review["loss_review_evidence"][key]
        for key in ("symbol", "review_allowed", "remaining_blocker_count", "resolved_blocker_count", "next_action")
    }


def test_compact_board_is_a_fixed_scalar_projection_and_never_leaks_nested_material(tmp_path):
    review = {
        "kind": "execution_board_review", "generated_at": "2026-08-13T15:00:00+00:00",
        "analysis_only": True, "recommendation": "autonomous_hold",
        "new_buy_policy": {"state": "allowed", "secret": "DO-NOT-LEAK"},
        "metrics": {"packet_count": 1, "submitted_order_count": 0, "live_buy_count": 0, "live_sell_count": 0, "loss_exit_count": 0, "secret": "DO-NOT-LEAK"},
        "loss_review_evidence": {"symbol": "TSM", "review_allowed": False, "remaining_blocker_count": 1, "resolved_blocker_count": 0, "next_action": "autonomous_hold", "source_binding": {"secret": "DO-NOT-LEAK"}},
        "autonomous_loss_decision": {"decision_id": "d", "ledger_packet_id": "l", "symbol": "TSM", "decision": "HOLD", "trade_decision_resolved": True, "exit_allowed": False, "decision_evidence": {"secret": "DO-NOT-LEAK"}},
        "violations": [], "warnings": [], "packet_reviews": [],
    }
    compact = compact_execution_board_review(review, raw_packet_path=tmp_path / "board.json", raw_packet_sha256="a" * 64)
    serialized = json.dumps(compact)
    assert "DO-NOT-LEAK" not in serialized
    assert compact["raw_packet_sha256"] == "a" * 64
    assert compact["autonomous_loss_decision"] == {"decision_id": "d", "ledger_packet_id": "l", "symbol": "TSM", "decision": "HOLD", "trade_decision_resolved": True, "execution_eligible": None, "exit_allowed": False}


def test_autonomous_loss_board_compact_sidecar_is_exact_scalar_contract(tmp_path):
    decision_id = "d" * 64
    review = {
        "generated_at": "2026-08-13T15:00:00+00:00", "analysis_only": True,
        "autonomous_loss_decision": {
            "decision_id": decision_id,
            "ledger_packet_id": f"wp-{decision_id}-portfolio_decision",
            "symbol": "TSM", "decision": "HOLD", "supervisor_decision_id": "loss-review-1",
            "source_revision": "1" * 40, "trade_decision_resolved": True,
            "execution_eligible": False, "execution_blockers_sha256": "c" * 64,
            "exit_allowed": False, "analysis_only": True, "execution_authority": "none",
            "can_submit_orders": False, "accepted_source_count": 3,
            "accepted_sources_sha256": "a" * 64,
        },
    }
    compact = compact_execution_board_review(
        review, raw_packet_path=tmp_path / "execution-board-review-20260813-150000.json",
        raw_packet_sha256="b" * 64,
    )
    assert set(compact) == {
        "schema", "generated_at", "raw_packet_path", "raw_packet_sha256", "symbol",
        "decision", "decision_id", "ledger_packet_id", "supervisor_decision_id", "source_revision",
        "trade_decision_resolved", "execution_eligible", "execution_blockers_sha256", "exit_allowed", "analysis_only", "execution_authority",
        "can_submit_orders", "accepted_source_count", "accepted_sources_sha256",
    }
    assert all(not isinstance(value, (dict, list)) for value in compact.values())


def test_written_compact_board_points_to_the_exact_timestamped_raw_artifact(tmp_path):
    review = build_execution_board_review(tmp_path / "hourly")
    raw_path, _ = write_execution_board_review(review, tmp_path / "board")
    compact = json.loads(raw_path.with_name(f"{raw_path.stem}.compact.json").read_text(encoding="utf-8"))
    assert compact["raw_packet_path"] == str(raw_path)
    assert compact["raw_packet_sha256"] == hashlib.sha256(raw_path.read_bytes()).hexdigest()


def test_board_does_not_write_ledger_when_source_revision_is_unavailable(tmp_path, monkeypatch):
    hourly, evidence_dir, _hourly_path, _loss_path = _write_exact_incomplete_loss_evidence(tmp_path)
    monkeypatch.setattr("tradingagents.evals.execution_board._source_revision", lambda: None)
    review = build_execution_board_review(hourly, loss_review_evidence_dir=evidence_dir, decision_evidence_root=tmp_path, decision_ledger_root=tmp_path / "ledger", now=datetime(2026, 8, 13, 15, 1, tzinfo=UTC))
    assert "autonomous_loss_decision" not in review
    assert not (tmp_path / "ledger" / "events.jsonl").exists()


def test_board_does_not_write_ledger_before_mismatched_review_binding_is_rejected(tmp_path):
    hourly, evidence_dir, _hourly_path, loss_path = _write_exact_incomplete_loss_evidence(tmp_path)
    loss = json.loads(loss_path.read_text(encoding="utf-8"))
    loss["payload"]["supervisor_review_authority"]["symbol"] = "ORCL"
    loss_path.write_text(json.dumps(loss), encoding="utf-8")
    review = build_execution_board_review(
        hourly, loss_review_evidence_dir=evidence_dir, decision_evidence_root=tmp_path,
        decision_ledger_root=tmp_path / "ledger", source_revision="1" * 40,
        now=datetime(2026, 8, 13, 15, 1, tzinfo=UTC),
    )
    assert "autonomous_loss_decision" not in review
    assert review["loss_review_evidence"]["matches_review_window"] is False
    assert not (tmp_path / "ledger" / "events.jsonl").exists()


def test_execution_board_uses_unicode_safe_canonical_accepted_source_digest(tmp_path):
    hourly, evidence_dir, _hourly_path, loss_path = _write_exact_incomplete_loss_evidence(
        tmp_path
    )
    compact_source = _add_unicode_bound_source(tmp_path, loss_path)

    review = build_execution_board_review(
        hourly,
        loss_review_evidence_dir=evidence_dir,
        decision_evidence_root=tmp_path,
        decision_ledger_root=tmp_path.parent / "unicode-decision-ledger",
        source_revision="2" * 40,
        now=datetime(2026, 8, 13, 15, 1, tzinfo=UTC),
    )

    decision = review["autonomous_loss_decision"]
    expected = hashlib.sha256(
        json.dumps(
            [compact_source],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert decision["decision"] == "HOLD"
    assert decision["accepted_source_count"] == 1
    assert decision["accepted_sources_sha256"] == expected


def test_execution_board_cli_does_not_expose_mutable_decision_roots():
    result = runner.invoke(app, ["research", "execution-board-review", "--help"])

    assert result.exit_code == 0, result.output
    assert "--decision-ledger-root" not in result.output
    assert "--decision-evidence-root" not in result.output


def test_loss_review_evidence_cli_does_not_expose_mutable_decision_root():
    result = runner.invoke(app, ["research", "loss-review-evidence", "--help"])

    assert result.exit_code == 0, result.output
    assert "--decision-evidence-root" not in result.output


def test_execution_board_loader_ignores_compact_and_latest_sidecars(tmp_path):
    hourly = tmp_path / "hourly"
    raw = {
        "generated_at": "2026-06-02T14:00:00+00:00",
        "decision": "hold",
        "actions": [],
        "submitted": [],
        "portfolio": {"live": {"unrealized_pl": "0.00"}},
    }
    _write_packet(hourly, "hourly-supervisor-20260602-140000.json", raw)
    _write_packet(
        hourly,
        "hourly-supervisor-20260602-140000.compact.json",
        {
            "schema": "compact_hourly_supervisor_v1",
            "generated_at": "2026-06-02T14:00:00+00:00",
            "decision": "loss-review",
        },
    )
    _write_packet(hourly, "latest.json", {**raw, "decision": "latest-raw"})
    _write_packet(
        hourly,
        "latest-compact.json",
        {
            "schema": "compact_hourly_supervisor_v1",
            "generated_at": "2026-06-02T14:00:00+00:00",
            "decision": "latest-compact",
        },
    )

    packets = load_hourly_packets(hourly)

    assert [packet["_source_path"] for packet in packets] == [
        str(hourly / "hourly-supervisor-20260602-140000.json")
    ]
    assert packets[0]["decision"] == "hold"


def test_execution_board_allows_clean_separate_profit_and_dip_packets(tmp_path):
    hourly = tmp_path / "hourly"
    empty_evidence_dir = tmp_path / "empty_loss_review_evidence"
    empty_evidence_dir.mkdir()
    _write_packet(
        hourly,
        "hourly-supervisor-20260602-140000.json",
        {
            "generated_at": "2026-06-02T14:00:00+00:00",
            "decision": "profit-take",
            "actions": [
                {
                    "action": "close",
                    "side": "sell",
                    "symbol": "NVDA",
                    "account": "live",
                    "reason": "Sell the spike: NVDA reached profit review threshold",
                }
            ],
            "submitted": [{"symbol": "NVDA", "side": "sell", "status": "filled"}],
            "portfolio": {"live": {"unrealized_pl": "2.50"}},
        },
    )
    _write_packet(
        hourly,
        "hourly-supervisor-20260602-150000.json",
        {
            "generated_at": "2026-06-02T15:00:00+00:00",
            "decision": "buy",
            "actions": [
                {
                    "action": "buy",
                    "side": "buy",
                    "symbol": "MA",
                    "account": "live",
                    "reason": "Time-sensitive high-conviction candidate: controlled dip; buy-the-dip candidate near support",
                }
            ],
            "submitted": [{"symbol": "MA", "side": "buy", "status": "filled"}],
            "portfolio": {"live": {"unrealized_pl": "1.25"}},
        },
    )

    review = build_execution_board_review(
        hourly,
        loss_review_evidence_dir=empty_evidence_dir,
    )

    assert review["analysis_only"] is True
    assert review["can_submit_orders"] is False
    assert review["recommendation"] == "continue_with_guardrails"
    assert review["violations"] == []
    assert review["metrics"]["profit_sell_count"] == 1
    assert review["metrics"]["live_buy_count"] == 1
    assert review["metrics"]["live_sell_count"] == 1


def test_execution_board_flags_paired_live_sell_and_buy_and_chase_buy(tmp_path):
    hourly = tmp_path / "hourly"
    _write_packet(
        hourly,
        "hourly-supervisor-20260602-160000.json",
        {
            "generated_at": "2026-06-02T16:00:00+00:00",
            "decision": "rotate",
            "actions": [
                {
                    "action": "close",
                    "side": "sell",
                    "symbol": "GOOGL",
                    "account": "live",
                    "reason": "GOOGL breached loss review threshold",
                },
                {
                    "action": "buy",
                    "side": "buy",
                    "symbol": "AMZN",
                    "account": "live",
                    "reason": "green spike; do not chase after the move",
                },
            ],
            "submitted": [{"symbol": "AMZN", "side": "buy", "status": "filled"}],
            "portfolio": {"live": {"unrealized_pl": "-1.00"}},
        },
    )

    review = build_execution_board_review(hourly)
    violation_types = {item["type"] for item in review["violations"]}
    warning_types = {item["type"] for item in review["warnings"]}

    assert review["recommendation"] == "pause_new_buys_and_review"
    assert "paired_live_sell_and_buy" in violation_types
    assert "chase_buy" in violation_types
    assert "loss_exit_without_approval_evidence" in violation_types
    assert "loss_exit" not in warning_types
    assert "negative_live_unrealized_pl" in warning_types


def test_execution_board_requires_loss_exit_review_evidence_for_live_loss_sell(tmp_path):
    hourly = tmp_path / "hourly"
    _write_packet(
        hourly,
        "hourly-supervisor-20260603-150000.json",
        {
            "generated_at": "2026-06-03T15:00:00+00:00",
            "decision": "close",
            "actions": [
                {
                    "action": "close",
                    "side": "sell",
                    "symbol": "ORCL",
                    "account": "live",
                    "reason": "ORCL breached loss review threshold",
                }
            ],
            "submitted": [{"symbol": "ORCL", "side": "sell", "status": "filled"}],
            "portfolio": {"live": {"unrealized_pl": "-2.00"}},
        },
    )

    review = build_execution_board_review(hourly)
    violation_types = {item["type"] for item in review["violations"]}

    assert "loss_exit_without_approval_evidence" in violation_types
    assert review["recommendation"] == "pause_new_buys_and_review"


def test_execution_board_accepts_approved_loss_exit_review_evidence(tmp_path):
    hourly = tmp_path / "hourly"
    _write_packet(
        hourly,
        "hourly-supervisor-20260603-151500.json",
        {
            "generated_at": "2026-06-03T15:15:00+00:00",
            "decision": "close",
            "actions": [
                {
                    "action": "close",
                    "side": "sell",
                    "symbol": "ORCL",
                    "account": "live",
                    "reason": "Exit approved loss: thesis_invalidated",
                }
            ],
            "submitted": [{"symbol": "ORCL", "side": "sell", "status": "filled"}],
            "evidence": {
                "loss_exit_review": {
                    "symbol": "ORCL",
                    "allowed": True,
                    "normalized_reason": "thesis_invalidated",
                    "holding_period_trading_days": 4,
                    "blocked_reasons": [],
                }
            },
            "portfolio": {"live": {"unrealized_pl": "-2.00"}},
        },
    )

    review = build_execution_board_review(hourly)
    violation_types = {item["type"] for item in review["violations"]}
    warning_types = {item["type"] for item in review["warnings"]}

    assert "loss_exit_without_approval_evidence" not in violation_types
    assert "loss_exit_disallowed_by_review" not in violation_types
    assert "loss_exit" in warning_types


def test_execution_board_does_not_count_unsubmitted_loss_exit_intent_as_execution(tmp_path):
    hourly = tmp_path / "hourly"
    _write_packet(
        hourly,
        "hourly-supervisor-20260715-163554.json",
        {
            "generated_at": "2026-07-15T16:35:54+00:00",
            "decision": "blocked",
            "actions": [
                {
                    "action": "close",
                    "side": "sell",
                    "symbol": "NFLX",
                    "account": "live",
                    "reason": "Exit approved loss: NFLX crossed loss review",
                }
            ],
            "submitted": [],
            "evidence": {
                "loss_exit_review": {
                    "symbol": "NFLX",
                    "allowed": True,
                    "normalized_reason": "hard_stop_defined_before_entry",
                    "blocked_reasons": [],
                }
            },
            "portfolio": {"live": {"unrealized_pl": "-3.08"}},
        },
    )

    review = build_execution_board_review(hourly)

    assert review["metrics"]["submitted_order_count"] == 0
    assert review["metrics"]["live_sell_count"] == 0
    assert review["metrics"]["loss_exit_count"] == 0
    assert "loss_exit" not in {item["type"] for item in review["warnings"]}


def test_execution_board_does_not_count_rejected_loss_exit_order(tmp_path):
    hourly = tmp_path / "hourly"
    _write_packet(
        hourly,
        "hourly-supervisor-20260715-163600.json",
        {
            "generated_at": "2026-07-15T16:36:00+00:00",
            "decision": "blocked",
            "actions": [
                {
                    "action": "close",
                    "side": "sell",
                    "symbol": "NFLX",
                    "account": "live",
                    "reason": "Exit approved loss: NFLX crossed loss review",
                    "idempotency_key": "ta-tiny-nflx-sell-expected",
                }
            ],
            "submitted": [
                {
                    "symbol": "NFLX",
                    "side": "sell",
                    "status": "rejected",
                    "client_order_id": "ta-tiny-nflx-sell-expected",
                }
            ],
            "evidence": {"loss_exit_review": {"symbol": "NFLX", "allowed": True}},
            "portfolio": {"live": {"unrealized_pl": "-3.08"}},
        },
    )

    review = build_execution_board_review(hourly)

    assert review["metrics"]["live_sell_count"] == 0
    assert review["metrics"]["loss_exit_count"] == 0
    assert "unsafe_order_status" in {item["type"] for item in review["violations"]}


def test_execution_board_does_not_attribute_ambiguous_legacy_submission(tmp_path):
    hourly = tmp_path / "hourly"
    _write_packet(
        hourly,
        "hourly-supervisor-20260715-163700.json",
        {
            "generated_at": "2026-07-15T16:37:00+00:00",
            "decision": "close",
            "actions": [
                {
                    "action": "close",
                    "side": "sell",
                    "symbol": "NFLX",
                    "account": "live",
                    "reason": "Exit approved loss: first intent",
                },
                {
                    "action": "close",
                    "side": "sell",
                    "symbol": "NFLX",
                    "account": "live",
                    "reason": "Exit approved loss: duplicate intent",
                },
            ],
            "submitted": [{"symbol": "NFLX", "side": "sell", "status": "filled"}],
            "evidence": {"loss_exit_review": {"symbol": "NFLX", "allowed": True}},
            "portfolio": {"live": {"unrealized_pl": "-3.08"}},
        },
    )

    review = build_execution_board_review(hourly)

    assert review["metrics"]["live_sell_count"] == 0
    assert review["metrics"]["loss_exit_count"] == 0


def test_execution_board_does_not_match_paper_submission_to_live_intent(tmp_path):
    hourly = tmp_path / "hourly"
    _write_packet(
        hourly,
        "hourly-supervisor-20260715-163800.json",
        {
            "generated_at": "2026-07-15T16:38:00+00:00",
            "decision": "blocked",
            "actions": [
                {
                    "action": "close",
                    "side": "sell",
                    "symbol": "NFLX",
                    "account": "live",
                    "reason": "Exit approved loss: NFLX crossed loss review",
                    "idempotency_key": "ta-tiny-nflx-sell-live",
                }
            ],
            "submitted": [
                {
                    "symbol": "NFLX",
                    "side": "sell",
                    "status": "filled",
                    "account": "paper",
                    "client_order_id": "ta-hourly-paper-nflx-sell",
                }
            ],
            "evidence": {"loss_exit_review": {"symbol": "NFLX", "allowed": True}},
            "portfolio": {"live": {"unrealized_pl": "-3.08"}},
        },
    )

    review = build_execution_board_review(hourly)

    assert review["metrics"]["live_sell_count"] == 0
    assert review["metrics"]["loss_exit_count"] == 0


def test_execution_board_merges_matching_loss_review_evidence(tmp_path):
    hourly = tmp_path / "hourly"
    evidence_dir = tmp_path / "loss_review_evidence"
    loss_exit_review = {
        "symbol": "TSM",
        "decision_id": "loss-exit-TSM-20260606210521",
        "allowed": False,
        "policy_rule_exit": False,
        "allowed_exit_reason": "",
        "allowed_exit_reason_source": "",
        "exit_policy_rule": "",
        "exit_policy_rationale": "",
        "blockers": ["allowed loss-exit reason is missing"],
        "blocked_reasons": ["allowed loss-exit reason is missing"],
        "source_packet_ids": [],
    }
    hourly_packet = _write_packet(
        hourly,
        "hourly-supervisor-20260606-210521-309775.json",
        {
            "generated_at": "2026-06-06T21:05:21+00:00",
            "decision": "loss-review",
            "actions": [],
            "submitted": [],
            "evidence": {"loss_exit_review": loss_exit_review},
            "portfolio": {"live": {"unrealized_pl": "-1.88"}},
        },
    )
    _write_packet(
        evidence_dir,
        "latest-compact.json",
        {
            "schema": "compact_loss_review_evidence_v1",
            "raw_packet_path": str(evidence_dir / "source-evidence-tsm.json"),
            "payload": {
                "symbol": "TSM",
                "hourly_packet_path": str(hourly_packet),
                "review_allowed": False,
                "supervisor_review_authority": bounded_exit_authority_record(
                    loss_exit_review
                ),
                "next_action": "manual_board_review_with_refreshed_evidence_required",
                "remaining_blockers": [
                    "allowed loss-exit reason is missing",
                    "loss-exit confidence is missing",
                ],
                "resolved_blockers_by_refresh": [
                    "original buy thesis is missing",
                    "company-specific news check is missing",
                ],
            },
        },
    )

    review = build_execution_board_review(
        hourly,
        loss_review_evidence_dir=evidence_dir,
    )
    warning_types = {item["type"] for item in review["warnings"]}

    assert "loss_review_evidence_pending" in warning_types
    assert review["loss_review_evidence"] == {
        "evidence_path": str(evidence_dir / "latest-compact.json"),
        "raw_packet_path": str(evidence_dir / "source-evidence-tsm.json"),
        "hourly_packet_path": str(hourly_packet),
        "supervisor_packet_path": "",
        "matches_review_window": True,
        "source_binding": {"matched": True, "issue": None},
        "symbol": "TSM",
        "review_allowed": False,
        "next_action": "manual_board_review_with_refreshed_evidence_required",
        "remaining_blocker_count": 2,
        "remaining_blockers": [
            "allowed loss-exit reason is missing",
            "loss-exit confidence is missing",
        ],
        "resolved_blocker_count": 2,
        "resolved_blockers_by_refresh": [
            "original buy thesis is missing",
            "company-specific news check is missing",
        ],
    }
    assert review["packet_reviews"][0]["loss_review_evidence_remaining_blocker_count"] == 2
    assert "loss-review evidence" in review["new_buy_policy"]["plain_english"].lower()
    assert "loss-review evidence" in review["board_roles"][0]["view"].lower()


def test_execution_board_uses_refreshed_advisory_approval_over_supervisor_snapshot(tmp_path):
    hourly = tmp_path / "hourly"
    evidence_dir = tmp_path / "loss_review_evidence"
    hourly_packet = _write_packet(
        hourly,
        "hourly-supervisor-20260715-173629.json",
        {
            "generated_at": "2026-07-15T17:36:29+00:00",
            "decision": "blocked",
            "actions": [],
            "submitted": [],
            "portfolio": {"live": {"unrealized_pl": "-3.02"}},
        },
    )
    _write_packet(
        evidence_dir,
        "latest-compact.json",
        {
            "schema": "compact_loss_review_evidence_v1",
            "payload": {
                "symbol": "NFLX",
                "hourly_packet_path": str(hourly_packet),
                "review_allowed": True,
                "remaining_blockers": [],
                "resolved_blockers_by_refresh": [],
                "advisory_summary": {
                    "review_allowed_after_refresh": False,
                    "loss_exit_candidate": {
                        "approval_effect": "board_review_input_not_loss_exit_approval",
                    },
                },
            },
        },
    )

    review = build_execution_board_review(
        hourly,
        loss_review_evidence_dir=evidence_dir,
    )

    evidence = review["loss_review_evidence"]
    assert evidence["supervisor_review_allowed"] is True
    assert evidence["review_allowed_after_refresh"] is False
    assert evidence["review_allowed"] is False
    assert "loss_review_evidence_pending" in {
        item["type"] for item in review["warnings"]
    }


def test_execution_board_names_tradeable_session_when_loss_exit_candidate_ready(tmp_path):
    hourly = tmp_path / "hourly"
    evidence_dir = tmp_path / "loss_review_evidence"
    loss_exit_review = {
        "symbol": "TSM",
        "decision_id": "loss-exit-TSM-20260607065131",
        "allowed": False,
        "policy_rule_exit": False,
        "allowed_exit_reason": "",
        "allowed_exit_reason_source": "",
        "exit_policy_rule": "",
        "exit_policy_rationale": "",
        "blockers": ["market session is not tradeable for a live loss exit"],
        "blocked_reasons": ["market session is not tradeable for a live loss exit"],
        "source_packet_ids": [],
    }
    hourly_packet = _write_packet(
        hourly,
        "hourly-supervisor-20260607-065131-399090.json",
        {
            "generated_at": "2026-06-07T06:51:31+00:00",
            "decision": "loss-review",
            "actions": [],
            "submitted": [],
            "evidence": {"loss_exit_review": loss_exit_review},
            "portfolio": {"live": {"unrealized_pl": "-1.88"}},
        },
    )
    _write_packet(
        evidence_dir,
        "latest-compact.json",
        {
            "schema": "compact_loss_review_evidence_v1",
            "raw_packet_path": str(evidence_dir / "source-evidence-tsm.json"),
            "payload": {
                "symbol": "TSM",
                "hourly_packet_path": str(hourly_packet),
                "review_allowed": False,
                "supervisor_review_authority": bounded_exit_authority_record(
                    loss_exit_review
                ),
                "next_action": "manual_board_review_with_refreshed_evidence_required",
                "remaining_blockers": [
                    "market session is not tradeable for a live loss exit",
                ],
                "resolved_blockers_by_refresh": [
                    "allowed loss-exit reason is missing",
                    "allowed loss-exit reason source is missing",
                    "loss-exit confidence is missing",
                ],
                "advisory_summary": {
                    "loss_exit_candidate": {
                        "allowed_exit_reason_candidate": "thesis_invalidated",
                        "allowed_exit_reason_source": "refreshed_loss_review_evidence",
                        "confidence": "0.78",
                        "confidence_tier": "medium",
                        "can_submit_orders": False,
                    }
                },
            },
        },
    )

    review = build_execution_board_review(
        hourly,
        loss_review_evidence_dir=evidence_dir,
    )

    pending_warning = next(
        item
        for item in review["warnings"]
        if item["type"] == "loss_review_evidence_pending"
    )
    assert review["loss_review_evidence"]["remaining_blocker_count"] == 1
    assert review["loss_review_evidence"]["loss_exit_candidate"] == {
        "allowed_exit_reason_candidate": "thesis_invalidated",
        "allowed_exit_reason_source": "refreshed_loss_review_evidence",
        "confidence": "0.78",
        "confidence_tier": "medium",
        "can_submit_orders": False,
    }
    assert "manual" not in pending_warning["message"].lower()
    assert "tradeable market session" in pending_warning["message"]
    assert "normal live gates" in pending_warning["message"]


def test_execution_board_flags_live_buy_without_dip_evidence(tmp_path):
    hourly = tmp_path / "hourly"
    _write_packet(
        hourly,
        "hourly-supervisor-20260602-170000.json",
        {
            "generated_at": "2026-06-02T17:00:00+00:00",
            "decision": "buy",
            "actions": [
                {
                    "action": "buy",
                    "side": "buy",
                    "symbol": "AMZN",
                    "account": "live",
                    "reason": "strong breakout",
                }
            ],
            "submitted": [],
            "portfolio": {"live": {"unrealized_pl": "0.00"}},
        },
    )

    review = build_execution_board_review(hourly)

    assert review["recommendation"] == "pause_new_buys_and_review"
    assert {item["type"] for item in review["violations"]} == {"buy_without_dip_evidence"}


def test_execution_board_allows_probation_after_clean_streak(tmp_path):
    hourly = tmp_path / "hourly"
    _write_packet(
        hourly,
        "hourly-supervisor-20260602-160000.json",
        {
            "generated_at": "2026-06-02T16:00:00+00:00",
            "decision": "rotate",
            "actions": [
                {
                    "action": "close",
                    "side": "sell",
                    "symbol": "GOOGL",
                    "account": "live",
                    "reason": "GOOGL breached loss review threshold",
                },
                {
                    "action": "buy",
                    "side": "buy",
                    "symbol": "AMZN",
                    "account": "live",
                    "reason": "green spike; do not chase after the move",
                },
            ],
            "submitted": [{"symbol": "AMZN", "side": "buy", "status": "filled"}],
            "portfolio": {"live": {"unrealized_pl": "-1.00"}},
        },
    )
    _write_packet(
        hourly,
        "hourly-supervisor-20260602-170000.json",
        {
            "generated_at": "2026-06-02T17:00:00+00:00",
            "decision": "hold",
            "actions": [],
            "submitted": [],
            "portfolio": {"live": {"unrealized_pl": "0.00"}},
        },
    )
    _write_packet(
        hourly,
        "hourly-supervisor-20260602-180000.json",
        {
            "generated_at": "2026-06-02T18:00:00+00:00",
            "decision": "buy",
            "actions": [
                {
                    "action": "buy",
                    "side": "buy",
                    "symbol": "MA",
                    "account": "live",
                    "reason": "controlled dip; buy-the-dip candidate near support",
                }
            ],
            "submitted": [{"symbol": "MA", "side": "buy", "status": "filled"}],
            "portfolio": {"live": {"unrealized_pl": "1.25"}},
        },
    )

    review = build_execution_board_review(hourly)

    assert review["recommendation"] == "continue_with_guardrails_after_clean_streak"
    assert review["new_buy_policy"]["state"] == "probation_allowed"
    assert review["new_buy_policy"]["clean_packets_since_last_violation"] == 2
    assert review["metrics"]["clean_packets_since_last_violation"] == 2
    assert review["violations"]
    assert "newer packets are clean enough" in review["new_buy_policy"]["plain_english"]


def test_execution_board_writer_and_cli_write_compact_artifacts(tmp_path):
    hourly = tmp_path / "hourly"
    empty_evidence_dir = tmp_path / "empty_loss_review_evidence"
    empty_evidence_dir.mkdir()
    _write_packet(
        hourly,
        "hourly-supervisor-20260602-180000.json",
        {
            "generated_at": "2026-06-02T18:00:00+00:00",
            "decision": "hold",
            "actions": [],
            "submitted": [],
            "portfolio": {"live": {"unrealized_pl": "0.00"}},
        },
    )
    review = build_execution_board_review(hourly, loss_review_evidence_dir=empty_evidence_dir)
    json_path, md_path = write_execution_board_review(review, tmp_path / "board")

    assert json_path.exists()
    assert md_path.exists()
    assert (tmp_path / "board" / "latest.json").exists()
    compact_path = json_path.with_name(f"{json_path.stem}.compact.json")
    assert compact_path.exists()
    latest_compact = json.loads(
        (tmp_path / "board" / "latest-compact.json").read_text(encoding="utf-8")
    )
    assert latest_compact["schema"] == "compact_execution_board_review_v1"
    assert latest_compact["raw_packet_path"] == str(json_path)
    assert latest_compact["can_submit_orders"] is False
    assert latest_compact["execution_authority"] == "none"
    assert latest_compact["metrics"]["packet_count"] == 1

    result = runner.invoke(
        app,
        [
            "research",
            "execution-board-review",
            "--hourly-dir",
            str(hourly),
            "--loss-review-evidence-dir",
            str(empty_evidence_dir),
            "--output-dir",
            str(tmp_path / "cli-board"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["kind"] == "execution_board_review"
    assert payload["can_submit_orders"] is False
    assert payload["recommendation"] == "no_action_needed"
    assert payload["json_path"].endswith(".json")
    assert (tmp_path / "cli-board" / "latest-compact.json").exists()


def test_execution_board_cli_reads_custom_nonempty_evidence_dir_without_autonomous_decision(tmp_path):
    hourly, evidence_dir, _hourly_path, loss_path = _write_exact_incomplete_loss_evidence(tmp_path)
    loss = json.loads(loss_path.read_text(encoding="utf-8"))
    loss["payload"]["supervisor_review_authority"]["symbol"] = "ORCL"
    loss_path.write_text(json.dumps(loss), encoding="utf-8")
    ledger_events = Path(__file__).resolve().parents[1] / "state" / "decision_ledger" / "events.jsonl"
    ledger_before = ledger_events.read_bytes() if ledger_events.exists() else None

    result = runner.invoke(
        app,
        [
            "research",
            "execution-board-review",
            "--hourly-dir",
            str(hourly),
            "--loss-review-evidence-dir",
            str(evidence_dir),
            "--output-dir",
            str(tmp_path / "cli-board"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["kind"] == "execution_board_review"
    assert payload["analysis_only"] is True
    assert payload["execution_authority"] == "none"
    assert payload["can_submit_orders"] is False
    evidence = payload["loss_review_evidence"]
    assert evidence["evidence_path"] == str(evidence_dir / "loss.json")
    assert evidence["matches_review_window"] is False
    assert evidence["source_binding"]["matched"] is False
    assert evidence["review_allowed"] is False
    assert "autonomous_loss_decision" not in payload
    assert "loss_review_evidence_pending" in {item["type"] for item in payload["warnings"]}
    ledger_after = ledger_events.read_bytes() if ledger_events.exists() else None
    assert ledger_after == ledger_before


def test_compact_execution_board_review_keeps_latest_review_and_counts(tmp_path):
    raw_path = tmp_path / "execution-board-review.json"
    review = {
        "kind": "execution_board_review",
        "generated_at": "2026-06-06T21:05:00+00:00",
        "analysis_only": True,
        "can_submit_orders": False,
        "recommendation": "review_underperformers_before_new_buys",
        "new_buy_policy": {"state": "caution", "required_clean_packets": 2},
        "next_hour_policy": {
            "buy_side": "New buys require controlled-dip evidence.",
            "sell_side": "Sells are independent.",
        },
        "metrics": {"packet_count": 24, "negative_live_pl_packets": 24},
        "violations": [{"type": "chase_buy", "message": "green spike chase"}],
        "warnings": [{"type": "negative_live_unrealized_pl", "message": "TSM down"}],
        "packet_reviews": [
            {"packet": "old.json", "decision": "hold"},
            {
                "packet": "hourly-supervisor-20260606-210521-309775.json",
                "generated_at": "2026-06-06T21:05:21+00:00",
                "decision": "loss-review",
                "submitted_order_count": 0,
                "violation_count": 0,
                "warning_count": 1,
            },
        ],
    }

    compact = compact_execution_board_review(review, raw_packet_path=raw_path)

    assert compact["schema"] == "compact_execution_board_review_v1"
    assert compact["raw_packet_path"] == str(raw_path)
    assert compact["recommendation"] == "review_underperformers_before_new_buys"
    assert compact["violation_count"] == 1
    assert compact["warning_count"] == 1
    assert compact["packet_reviews"][-1]["decision"] == "loss-review"
    assert compact["packet_reviews"][-1]["submitted_order_count"] == 0
    assert compact["can_submit_orders"] is False
