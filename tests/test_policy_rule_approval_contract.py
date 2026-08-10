from pathlib import Path

from tradingagents.research.loss_review_evidence import (
    build_loss_review_evidence_packet,
)
from tradingagents.research.provider_orchestrator import TickerProviderResearchResult


def test_policy_stop_floor_approval_survives_advisory_refresh():
    review = {
        "symbol": "NFLX",
        "side": "sell",
        "decision_id": "loss-exit-NFLX-20260717183127",
        "current_price": "69.28",
        "average_entry_price": "83.37",
        "unrealized_pl": "-4.52",
        "unrealized_pnl_percent": "-16.90",
        "allowed_exit_reason": "policy_stop_floor",
        "allowed_exit_reason_source": (
            "pre-registered exit policy rule 'catastrophic_stop'"
        ),
        "policy_rule_exit": True,
        "exit_policy_rule": "catastrophic_stop",
        "exit_policy_rationale": (
            "Position is beyond the pre-registered catastrophic floor."
        ),
        "evidence_generated_at": "2026-07-17T18:31:27+00:00",
        "allowed": True,
        "blocked_reasons": [],
        "blockers": [],
    }
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
                        "current_price": "69.28",
                        "avg_entry_price": "83.37",
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
