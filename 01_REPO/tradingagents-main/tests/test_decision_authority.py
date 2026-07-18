from tradingagents.policy.decision_authority import resolve_exit_authority


def test_advisory_refresh_cannot_revoke_preregistered_policy_exit():
    verdict = resolve_exit_authority(
        supervisor_review={
            "allowed": True,
            "policy_rule_exit": True,
            "allowed_exit_reason": "policy_stop_floor",
            "exit_policy_rule": "catastrophic_stop",
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
