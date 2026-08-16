import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradingagents.brokers.supervisor.loss_review import loss_exit_review_packet
from tradingagents.evals.execution_board import build_execution_board_review
from tradingagents.policy.exit_policy import apply_exit_policy_to_position
from tradingagents.policy.packets import write_research_packet
from tradingagents.research.loss_review_evidence import build_loss_review_evidence_packet
from tradingagents.research.provider_orchestrator import TickerProviderResearchResult


def _review(*, reason="policy_stop_floor", rule="catastrophic_stop") -> dict:
    position = {
        "symbol": "NFLX",
        "qty": "0.320946047",
        "avg_entry_price": "83.37",
        "current_price": "69.00",
        "unrealized_pl": "-4.52",
        "unrealized_plpc": "-0.1690",
    }
    if reason == "policy_time_stop" and rule == "time_stop":
        position.update(
            {
                "avg_entry_price": "100.00",
                "current_price": "94.00",
                "unrealized_plpc": "-0.06",
                "holding_period_trading_days": 20,
            }
        )
    generated_at = datetime(2026, 7, 17, 18, 31, 27, tzinfo=timezone.utc)
    enriched = apply_exit_policy_to_position(position, generated_at=generated_at)
    return loss_exit_review_packet(
        enriched,
        generated_at=generated_at,
        decision_id="loss-exit-NFLX-20260717183127",
        proposed_limit_price=enriched["exit_policy_limit_price"],
    )


def _hourly_packet(review: dict) -> dict:
    return {
        "generated_at": "2026-07-17T18:31:27+00:00",
        "decision": "close",
        "actions": [],
        "submitted": [],
        "evidence": {"loss_exit_review": review},
        "portfolio": {
            "live": {
                "positions": [
                    {
                        "symbol": review["symbol"],
                        "qty": "1",
                        "current_price": review["current_price"],
                        "avg_entry_price": review["average_entry_price"],
                    }
                ]
            }
        },
    }


def _write_valid_evidence(tmp_path: Path, review: dict) -> tuple[Path, Path]:
    hourly_dir = tmp_path / "hourly"
    hourly_dir.mkdir()
    hourly_path = hourly_dir / "hourly-supervisor-policy-stop.json"
    hourly_packet = _hourly_packet(review)
    hourly_path.write_text(json.dumps(hourly_packet), encoding="utf-8")
    packet = build_loss_review_evidence_packet(
        hourly_packet_path=hourly_path,
        hourly_packet=hourly_packet,
        provider_result=TickerProviderResearchResult(symbol=review["symbol"]),
        entry_context={},
    )
    evidence_dir = tmp_path / "evidence"
    write_research_packet(packet, evidence_dir)
    return hourly_dir, evidence_dir


@pytest.mark.parametrize(
    ("reason", "rule"),
    [
        ("policy_stop_floor", "catastrophic_stop"),
        ("policy_time_stop", "time_stop"),
    ],
)
def test_compact_policy_review_remains_non_authorizing_without_current_broker_facts(
    tmp_path, reason, rule
):
    hourly_dir, evidence_dir = _write_valid_evidence(
        tmp_path,
        _review(reason=reason, rule=rule),
    )

    board = build_execution_board_review(hourly_dir, loss_review_evidence_dir=evidence_dir)

    assert board["loss_review_evidence"]["matches_review_window"] is True
    assert board["loss_review_evidence"]["source_binding"]["matched"] is True
    assert board["loss_review_evidence"]["review_allowed"] is False
    assert any(item["type"] == "loss_review_evidence_pending" for item in board["warnings"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("symbol", "TSLA"),
        ("decision_id", "loss-exit-NFLX-other"),
        ("allowed_exit_reason_source", "other-source"),
        ("exit_policy_rationale", "other rationale"),
    ],
)
def test_board_fails_closed_on_compact_authority_mismatch(tmp_path, field, value):
    hourly_dir, evidence_dir = _write_valid_evidence(tmp_path, _review())
    compact_path = evidence_dir / "latest-compact.json"
    compact = json.loads(compact_path.read_text(encoding="utf-8"))
    compact["payload"]["supervisor_review_authority"][field] = value
    compact_path.write_text(json.dumps(compact), encoding="utf-8")

    board = build_execution_board_review(hourly_dir, loss_review_evidence_dir=evidence_dir)

    evidence = board["loss_review_evidence"]
    assert evidence["matches_review_window"] is False
    assert evidence["source_binding"]["matched"] is False
    assert field in evidence["source_binding"]["issue"]
    assert evidence["review_allowed"] is False


def test_board_fails_closed_without_raising_on_malformed_compact_authority(tmp_path):
    hourly_dir, evidence_dir = _write_valid_evidence(tmp_path, _review())
    compact_path = evidence_dir / "latest-compact.json"
    compact = json.loads(compact_path.read_text(encoding="utf-8"))
    compact["payload"]["supervisor_review_authority"] = "not-a-record"
    compact["payload"]["remaining_blockers"] = 1
    compact_path.write_text(json.dumps(compact), encoding="utf-8")

    board = build_execution_board_review(hourly_dir, loss_review_evidence_dir=evidence_dir)

    evidence = board["loss_review_evidence"]
    assert evidence["matches_review_window"] is False
    assert evidence["review_allowed"] is False
    assert evidence["source_binding"]["issue"] == "missing compact authority record"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("blockers", None),
        ("blocked_reasons", None),
        ("blockers", "blocked"),
        ("blocked_reasons", 1),
        ("blockers", {"blocked": True}),
        ("blocked_reasons", ["blocked"]),
        ("source_packet_ids", "supervisor-nflx"),
        ("source_packet_ids", 1),
        ("source_packet_ids", {"id": "supervisor-nflx"}),
    ],
)
def test_board_uses_raw_hourly_authority_for_malformed_fields(tmp_path, field, value):
    review = _review()
    review[field] = value
    hourly_dir, evidence_dir = _write_valid_evidence(tmp_path, review)

    board = build_execution_board_review(hourly_dir, loss_review_evidence_dir=evidence_dir)

    evidence = board["loss_review_evidence"]
    assert evidence["source_binding"]["matched"] is True
    assert evidence["review_allowed"] is False


@pytest.mark.parametrize(
    "missing_fields",
    [
        ("blockers", "blocked_reasons"),
        ("blockers",),
        ("blocked_reasons",),
    ],
)
def test_board_uses_raw_hourly_authority_for_missing_blocker_fields(
    tmp_path, missing_fields
):
    review = _review()
    for field in missing_fields:
        review.pop(field)
    hourly_dir, evidence_dir = _write_valid_evidence(tmp_path, review)

    board = build_execution_board_review(hourly_dir, loss_review_evidence_dir=evidence_dir)

    evidence = board["loss_review_evidence"]
    assert evidence["source_binding"]["matched"] is True
    assert evidence["review_allowed"] is False
