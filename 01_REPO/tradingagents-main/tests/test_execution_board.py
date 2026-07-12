import json

from typer.testing import CliRunner

from cli.main import app
from tradingagents.evals.execution_board import (
    build_execution_board_review,
    compact_execution_board_review,
    load_hourly_packets,
    write_execution_board_review,
)

runner = CliRunner()


def _write_packet(directory, name, payload):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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

    review = build_execution_board_review(hourly)

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
    assert "loss_exit" in warning_types
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


def test_execution_board_merges_matching_loss_review_evidence(tmp_path):
    hourly = tmp_path / "hourly"
    evidence_dir = tmp_path / "loss_review_evidence"
    hourly_packet = _write_packet(
        hourly,
        "hourly-supervisor-20260606-210521-309775.json",
        {
            "generated_at": "2026-06-06T21:05:21+00:00",
            "decision": "loss-review",
            "actions": [],
            "submitted": [],
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
        "matches_review_window": True,
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


def test_execution_board_names_tradeable_session_when_loss_exit_candidate_ready(tmp_path):
    hourly = tmp_path / "hourly"
    evidence_dir = tmp_path / "loss_review_evidence"
    hourly_packet = _write_packet(
        hourly,
        "hourly-supervisor-20260607-065131-399090.json",
        {
            "generated_at": "2026-06-07T06:51:31+00:00",
            "decision": "loss-review",
            "actions": [],
            "submitted": [],
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
    assert "BOARD-only" in pending_warning["message"]
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
    review = build_execution_board_review(hourly)
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
