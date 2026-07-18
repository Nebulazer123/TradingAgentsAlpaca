from tradingagents.policy.decision_authority import resolve_exit_authority


def test_advisory_refresh_cannot_revoke_preregistered_policy_exit():
    verdict = resolve_exit_authority(
        supervisor_review={
            "allowed": True,
            "policy_rule_exit": True,
            "allowed_exit_reason": "policy_stop_floor",
            "symbol": "NFLX",
            "decision_id": "loss-exit-NFLX-20260717183127",
            "allowed_exit_reason_source": "pre-registered exit policy rule",
            "exit_policy_rule": "catastrophic_stop",
            "exit_policy_rationale": "The pre-registered rule fired.",
            "blockers": [],
            "blocked_reasons": [],
        },
        advisory_analysis={
            "requires_board_decision": True,
            "approval_effect": "board_review_input_not_loss_exit_approval",
        },
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


def _valid_policy_review(*, reason="policy_stop_floor", rule="catastrophic_stop"):
    return {
        "symbol": "NFLX",
        "decision_id": "loss-exit-NFLX-20260717183127",
        "allowed": True,
        "policy_rule_exit": True,
        "allowed_exit_reason": reason,
        "allowed_exit_reason_source": "pre-registered exit policy rule",
        "exit_policy_rule": rule,
        "exit_policy_rationale": "The pre-registered rule fired.",
        "blockers": [],
        "blocked_reasons": [],
        "source_packet_ids": ["supervisor-nflx"],
    }


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
        supervisor_review=_valid_policy_review(rule="time_stop"),
        advisory_analysis=None,
    )

    assert verdict.allowed is False
    assert "does not match" in verdict.reason


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
