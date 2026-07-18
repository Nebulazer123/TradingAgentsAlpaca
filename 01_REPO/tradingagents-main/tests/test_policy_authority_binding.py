import json
from pathlib import Path

import pytest

from tradingagents.evals.execution_board import build_execution_board_review
from tradingagents.policy.packets import write_research_packet
from tradingagents.research.loss_review_evidence import build_loss_review_evidence_packet
from tradingagents.research.provider_orchestrator import TickerProviderResearchResult


def _review(*, reason="policy_stop_floor", rule="catastrophic_stop") -> dict:
    return {
        "symbol": "NFLX",
        "side": "sell",
        "decision_id": "loss-exit-NFLX-20260717183127",
        "current_price": "69.28",
        "average_entry_price": "83.37",
        "unrealized_pl": "-4.52",
        "unrealized_pnl_percent": "-16.90",
        "allowed_exit_reason": reason,
        "allowed_exit_reason_source": "pre-registered exit policy rule",
        "policy_rule_exit": True,
        "exit_policy_rule": rule,
        "exit_policy_rationale": "The pre-registered rule fired.",
        "evidence_generated_at": "2026-07-17T18:31:27+00:00",
        "allowed": True,
        "blocked_reasons": [],
        "blockers": [],
        "source_packet_ids": ["supervisor-nflx"],
    }


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
                        "current_price": "69.28",
                        "avg_entry_price": "83.37",
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
def test_valid_policy_authority_survives_full_compact_and_board(
    tmp_path, reason, rule
):
    hourly_dir, evidence_dir = _write_valid_evidence(
        tmp_path,
        _review(reason=reason, rule=rule),
    )

    board = build_execution_board_review(hourly_dir, loss_review_evidence_dir=evidence_dir)

    assert board["loss_review_evidence"]["matches_review_window"] is True
    assert board["loss_review_evidence"]["source_binding"]["matched"] is True
    assert board["loss_review_evidence"]["review_allowed"] is True
    assert not any(item["type"] == "loss_review_evidence_pending" for item in board["warnings"])


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
