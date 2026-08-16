from datetime import datetime
from pathlib import Path

from tradingagents.brokers.supervisor.loss_review import loss_exit_review_packet
from tradingagents.policy.exit_policy import apply_exit_policy_to_position
from tradingagents.research.loss_review_evidence import (
    build_loss_review_evidence_packet,
)
from tradingagents.research.provider_orchestrator import TickerProviderResearchResult


def _policy_review() -> dict:
    generated_at = "2026-07-17T18:31:27+00:00"
    position = {
        "symbol": "NFLX",
        "qty": "0.320946047",
        "avg_entry_price": "83.37",
        "current_price": "69.00",
        "unrealized_pl": "-4.52",
        "unrealized_plpc": "-0.1690",
    }
    now = datetime.fromisoformat(generated_at)
    enriched = apply_exit_policy_to_position(position, generated_at=now)
    return loss_exit_review_packet(
        enriched,
        generated_at=now,
        decision_id="loss-exit-NFLX-20260717183127",
        proposed_limit_price=enriched["exit_policy_limit_price"],
    )


def test_policy_stop_floor_approval_survives_advisory_refresh():
    review = _policy_review()
    hourly_packet = {
        "generated_at": "2026-07-17T18:31:27+00:00",
        "decision": "close",
        "actions": [],
        "submitted": [],
        "evidence": {"loss_exit_review": review},
        "portfolio": {
            "live": {
                "positions": [
                    {
                        "symbol": "NFLX",
                        "qty": "0.320946047",
                        "current_price": review["current_price"],
                        "avg_entry_price": review["average_entry_price"],
                        "unrealized_pl": "-4.52",
                        "unrealized_plpc": "-0.1690",
                    }
                ]
            }
        },
    }

    packet = build_loss_review_evidence_packet(
        hourly_packet_path=Path(
            "results/hourly_supervisor/hourly-supervisor-policy-stop.json"
        ),
        hourly_packet=hourly_packet,
        provider_result=TickerProviderResearchResult(symbol="NFLX"),
        entry_context={},
    )

    advisory = packet.payload["advisory_analysis"]
    candidate = advisory["loss_exit_candidate"]
    assert packet.payload["next_action"] == (
        "pre_registered_policy_approval_preserved"
    )
    assert advisory["review_allowed_after_refresh"] is True
    assert candidate["allowed_exit_reason_candidate"] == "policy_stop_floor"
    assert candidate["allowed_exit_reason_source"] == review[
        "allowed_exit_reason_source"
    ]
    assert candidate["approval_effect"] == "preserves_pre_registered_policy_approval"
    assert candidate["requires_board_decision"] is False
    assert candidate["can_submit_orders"] is False


def test_conflicting_policy_rule_stays_fail_closed_after_fresh_advisory_evidence():
    review = {
        **_policy_review(),
        "decision_id": "loss-exit-NFLX-conflict",
        "exit_policy_rule": "profit_target",
    }
    hourly_packet = {
        "generated_at": "2026-07-17T18:31:27+00:00",
        "decision": "loss-review",
        "actions": [],
        "submitted": [],
        "evidence": {"loss_exit_review": review},
        "portfolio": {"live": {"positions": []}},
    }

    packet = build_loss_review_evidence_packet(
        hourly_packet_path=Path("results/hourly_supervisor/hourly-supervisor-conflict.json"),
        hourly_packet=hourly_packet,
        provider_result=TickerProviderResearchResult(symbol="NFLX"),
        entry_context={},
    )

    loss_review = packet.payload["advisory_analysis"]
    assert loss_review["policy_rule_conflict"] is True
    assert loss_review["review_allowed_after_refresh"] is False
    assert packet.payload["next_action"] != "pre_registered_policy_approval_preserved"
    assert packet.payload["execution_authority"] == "none"
