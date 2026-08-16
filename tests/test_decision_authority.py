import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tradingagents.brokers.supervisor.loss_review import loss_exit_review_packet
from tradingagents.policy.decision_authority import (
    capture_current_supervisor_review,
    resolve_exit_authority,
)
from tradingagents.policy.exit_policy import apply_exit_policy_to_position

NOW = datetime(2026, 7, 14, 15, 0, tzinfo=timezone.utc)


def test_unverified_board_input_cannot_resolve_a_discretionary_exit():
    verdict = resolve_exit_authority(
        supervisor_review={"allowed": False, "policy_rule_exit": False},
        advisory_analysis={"requires_board_decision": True},
        board_decision={"decision": "HOLD"},
    )

    assert verdict.exit_allowed is False
    assert verdict.trade_decision_resolved is False
    assert verdict.requires_additional_decision is True


@pytest.mark.parametrize(
    ("decision", "execution_eligible", "exit_allowed"),
    [("HOLD", False, False), ("SELL", False, False), ("SELL", True, True)],
)
def test_verified_board_decision_closes_the_trade_decision_only(
    monkeypatch, tmp_path, decision, execution_eligible, exit_allowed
):
    review = {
        "symbol": "TSM",
        "decision_id": "loss-review-tsm-1",
        "allowed": False,
        "policy_rule_exit": False,
    }
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    packet_path = evidence_root / "supervisor.json"
    packet_bytes = json.dumps({"evidence": {"loss_exit_review": review}}).encode()
    packet_path.write_bytes(packet_bytes)
    binding = capture_current_supervisor_review(
        packet_path=packet_path,
        packet_bytes=packet_bytes,
        evidence_root=evidence_root,
    )
    verified = SimpleNamespace(
        symbol="TSM",
        supervisor_decision_id="loss-review-tsm-1",
        decision=decision,
        exit_allowed=exit_allowed,
        execution_eligible=execution_eligible,
        execution_blockers=(
            () if execution_eligible else ("market session is not tradeable for a live loss exit",)
        ),
        trade_decision_resolved=True,
        analysis_only=True,
        execution_authority="none",
        can_submit_orders=False,
        supervisor_packet=SimpleNamespace(
            path="supervisor.json",
            sha256=hashlib.sha256(packet_bytes).hexdigest(),
            size_bytes=len(packet_bytes),
        ),
    )
    monkeypatch.setattr(
        "tradingagents.policy.loss_board_decision.verify_autonomous_loss_board_decision",
        lambda **_kwargs: verified,
    )

    verdict = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis={"requires_board_decision": True},
        board_decision={"ledger_packet_id": "portfolio-decision-1"},
        decision_ledger_root=tmp_path / "ledger",
        decision_evidence_root=evidence_root,
        current_supervisor_binding=binding,
    )

    assert verdict.exit_allowed is exit_allowed
    assert verdict.allowed is exit_allowed
    assert verdict.execution_eligible is execution_eligible
    assert verdict.trade_decision_resolved is True
    assert verdict.requires_additional_decision is False
    assert verdict.authority_source == "autonomous_portfolio_board"
    assert "execution intent" in verdict.reason if decision == "SELL" else "HOLD" in verdict.reason


@pytest.mark.parametrize("alteration", ["same_id_new_bytes", "wrong_path"])
def test_board_decision_rejects_replaced_or_wrong_current_supervisor_binding(
    monkeypatch, tmp_path, alteration
):
    original_review = {
        "symbol": "TSM",
        "decision_id": "loss-review-tsm-1",
        "allowed": False,
        "policy_rule_exit": False,
    }
    root = tmp_path / "evidence"
    root.mkdir()
    path = root / "supervisor.json"
    original_bytes = json.dumps({"evidence": {"loss_exit_review": original_review}}).encode()
    path.write_bytes(original_bytes)
    binding = capture_current_supervisor_review(
        packet_path=path, packet_bytes=original_bytes, evidence_root=root
    )
    if alteration == "same_id_new_bytes":
        replacement_bytes = json.dumps(
            {"evidence": {"loss_exit_review": {**original_review, "allowed": True}}}
        ).encode()
        binding = capture_current_supervisor_review(
            packet_path=path, packet_bytes=replacement_bytes, evidence_root=root
        )
    verified = SimpleNamespace(
        symbol="TSM",
        supervisor_decision_id="loss-review-tsm-1",
        decision="HOLD",
        exit_allowed=False,
        execution_eligible=False,
        execution_blockers=("decision evidence is incomplete",),
        trade_decision_resolved=True,
        analysis_only=True,
        execution_authority="none",
        can_submit_orders=False,
        supervisor_packet=SimpleNamespace(
            path="other.json" if alteration == "wrong_path" else "supervisor.json",
            sha256=hashlib.sha256(original_bytes).hexdigest(),
            size_bytes=len(original_bytes),
        ),
    )
    monkeypatch.setattr(
        "tradingagents.policy.loss_board_decision.verify_autonomous_loss_board_decision",
        lambda **_kwargs: verified,
    )

    verdict = resolve_exit_authority(
        supervisor_review=binding.review,
        advisory_analysis={"requires_board_decision": True},
        board_decision={"ledger_packet_id": "portfolio-decision-1"},
        decision_ledger_root=tmp_path / "ledger",
        decision_evidence_root=root,
        current_supervisor_binding=binding,
    )

    assert verdict.trade_decision_resolved is False
    assert verdict.exit_allowed is False


def test_advisory_refresh_cannot_revoke_preregistered_policy_exit():
    verdict = resolve_exit_authority(
        supervisor_review=_valid_policy_review(),
        advisory_analysis={
            "requires_board_decision": True,
            "approval_effect": "board_review_input_not_loss_exit_approval",
        },
        current_position=_current_position_for_review(_valid_policy_review()),
        now=NOW,
    )

    assert verdict.allowed is True
    assert verdict.authority_source == "pre_registered_policy_rule"
    assert verdict.requires_additional_decision is False


def test_discretionary_loss_exit_still_requires_machine_board_decision():
    verdict = resolve_exit_authority(
        supervisor_review={"allowed": False, "policy_rule_exit": False},
        advisory_analysis={"requires_board_decision": True},
    )

    assert verdict.allowed is False
    assert verdict.requires_additional_decision is True
    assert verdict.decision_owner == "portfolio_executive"


def _valid_policy_review():
    position = {
        "symbol": "NFLX",
        "qty": "0.5",
        "avg_entry_price": "100.00",
        "current_price": "91.00",
        "market_value": "45.50",
        "unrealized_pl": "-4.50",
        "unrealized_plpc": "-0.09",
        "opened_at": "2026-07-01T15:00:00+00:00",
    }
    enriched = apply_exit_policy_to_position(position, generated_at=NOW)
    return loss_exit_review_packet(
        enriched,
        generated_at=NOW,
        proposed_limit_price=enriched["exit_policy_limit_price"],
    )


def _current_position_for_review(review):
    current = {
        "symbol": review["symbol"],
        "qty": review["quantity"],
        "avg_entry_price": review["average_entry_price"],
        "current_price": review["current_price"],
        "unrealized_plpc": "-0.09",
        "opened_at": review["opened_at"],
    }
    if review.get("holding_period_trading_days") is not None:
        current["holding_period_trading_days"] = review["holding_period_trading_days"]
    return current


def test_public_policy_resolver_requires_current_position_and_current_clock():
    review = _valid_policy_review()
    current = _current_position_for_review(review)

    for kwargs in ({}, {"current_position": current}, {"now": NOW}):
        verdict = resolve_exit_authority(
            supervisor_review=review,
            advisory_analysis=None,
            **kwargs,
        )

        assert verdict.allowed is False
        assert verdict.authority_source == "invalid_pre_registered_policy_rule"

    verified = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis=None,
        current_position=current,
        now=NOW,
    )
    assert verified.allowed is True


def test_public_policy_resolver_rejects_mismatched_live_broker_return():
    review = _valid_policy_review()
    current = _current_position_for_review(review)
    current["unrealized_plpc"] = "-0.08"

    verdict = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis=None,
        current_position=current,
        now=NOW,
    )

    assert verdict.allowed is False


def test_public_policy_resolver_recomputes_opened_at_holding_days():
    review = _valid_policy_review()
    review.update(
        {
            "opened_at": "2026-07-10T15:00:00+00:00",
            "holding_period_trading_days": 20,
        }
    )
    current = _current_position_for_review(review)

    verdict = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis=None,
        current_position=current,
        now=NOW,
    )

    assert verdict.allowed is False


def test_string_booleans_cannot_authorize_policy_exit():
    review = _valid_policy_review()
    review.update({"allowed": "true", "policy_rule_exit": "true"})

    verdict = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis=None,
    )

    assert verdict.allowed is False
    assert verdict.authority_source == "invalid_pre_registered_policy_rule"
    assert "literal True" in verdict.reason


def test_incomplete_policy_claim_fails_closed_with_specific_reason():
    review = _valid_policy_review()
    review.pop("decision_id")

    verdict = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis=None,
    )

    assert verdict.allowed is False
    assert verdict.authority_source == "invalid_pre_registered_policy_rule"
    assert "decision_id" in verdict.reason


def test_policy_claim_with_blockers_fails_closed():
    review = _valid_policy_review()
    review["blockers"] = ["market session is not tradeable"]

    verdict = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis=None,
    )

    assert verdict.allowed is False
    assert "blockers" in verdict.reason


def test_policy_reason_and_rule_must_be_a_valid_pair():
    verdict = resolve_exit_authority(
        supervisor_review={**_valid_policy_review(), "exit_policy_rule": "time_stop"},
        advisory_analysis=None,
    )

    assert verdict.allowed is False
    assert "does not match" in verdict.reason


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("allowed_exit_reason", "policy_time_stop"),
        ("allowed_exit_reason_source", "arbitrary policy source"),
        ("exit_policy_rule", "catastrophic_stop"),
        ("exit_policy_rationale", "arbitrary policy rationale"),
        ("proposed_limit_price", "90.73"),
    ],
)
def test_resolver_rejects_forged_pre_registered_policy_review(field, value):
    review = {**_valid_policy_review(), field: value}

    verdict = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis=None,
    )

    assert verdict.allowed is False
    assert verdict.authority_source == "invalid_pre_registered_policy_rule"


def test_nested_discretionary_candidate_requires_internal_board_decision():
    verdict = resolve_exit_authority(
        supervisor_review={"allowed": True, "policy_rule_exit": False},
        advisory_analysis={
            "loss_exit_candidate": {"requires_board_decision": True},
        },
    )

    assert verdict.allowed is False
    assert verdict.requires_additional_decision is True
    assert verdict.decision_owner == "portfolio_executive"


def test_policy_claim_requires_both_blocker_keys():
    review = _valid_policy_review()
    review.pop("blockers")
    review.pop("blocked_reasons")

    verdict = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis=None,
    )

    assert verdict.allowed is False
    assert "blockers" in verdict.reason


@pytest.mark.parametrize("missing_key", ["blockers", "blocked_reasons"])
def test_policy_claim_fails_closed_when_one_blocker_key_is_missing(missing_key):
    review = _valid_policy_review()
    review.pop(missing_key)

    verdict = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis=None,
    )

    assert verdict.allowed is False
    assert missing_key in verdict.reason


@pytest.mark.parametrize("field", ["blockers", "blocked_reasons"])
@pytest.mark.parametrize("value", [None, "blocked", 1, {"blocked": True}, ["blocked"]])
def test_policy_claim_rejects_malformed_or_nonempty_blocker_fields(field, value):
    review = _valid_policy_review()
    review[field] = value

    verdict = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis=None,
    )

    assert verdict.allowed is False
    assert field in verdict.reason


@pytest.mark.parametrize("value", [1, "supervisor-nflx", {"id": "supervisor-nflx"}])
def test_policy_claim_rejects_malformed_present_source_packet_ids(value):
    review = _valid_policy_review()
    review["source_packet_ids"] = value

    verdict = resolve_exit_authority(
        supervisor_review=review,
        advisory_analysis=None,
    )

    assert verdict.allowed is False
    assert "source_packet_ids" in verdict.reason
