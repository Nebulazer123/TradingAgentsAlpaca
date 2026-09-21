import pytest

from tradingagents.orchestration.authority import ActionClass, authority_for


@pytest.mark.parametrize(
    ("action_value", "owner"),
    [
        ("trade_decision", "portfolio_executive"),
        ("strategy_change", "strategy_learning"),
        ("risk_change", "portfolio_executive"),
        ("promotion_change", "strategy_learning"),
        ("freeze", "integrity_verifier"),
        ("repair", "reliability_controller"),
        ("verify", "integrity_verifier"),
        ("rearm_request", "reliability_controller"),
        ("rearm_issue", "integrity_verifier"),
        ("order_submit", "execution_operator"),
    ],
)
def test_machine_actions_have_internal_owners(action_value, owner):
    verdict = authority_for(action_value)
    assert verdict.allowed is True
    assert verdict.human_required is False
    assert verdict.owner_role == owner


def test_ambiguous_legacy_rearm_action_fails_closed():
    with pytest.raises(ValueError, match="rearm"):
        authority_for("rearm")


def test_action_enum_contains_only_the_explicit_authority_partition():
    assert {action.value for action in ActionClass} == {
        "trade_decision",
        "strategy_change",
        "risk_change",
        "promotion_change",
        "live_promotion",
        "risk_envelope_expansion",
        "freeze",
        "repair",
        "verify",
        "rearm_request",
        "rearm_issue",
        "order_submit",
        "capital_change",
        "account_identity_change",
        "credential_change",
        "charter_change",
    }


def test_action_enum_has_exact_member_names_and_no_legacy_rearm_alias():
    assert set(ActionClass.__members__) == {
        "TRADE_DECISION",
        "STRATEGY_CHANGE",
        "RISK_CHANGE",
        "PROMOTION_CHANGE",
        "LIVE_PROMOTION",
        "RISK_ENVELOPE_EXPANSION",
        "FREEZE",
        "REPAIR",
        "VERIFY",
        "REARM_REQUEST",
        "REARM_ISSUE",
        "ORDER_SUBMIT",
        "CAPITAL_CHANGE",
        "ACCOUNT_IDENTITY_CHANGE",
        "CREDENTIAL_CHANGE",
        "CHARTER_CHANGE",
    }
    assert "REARM" not in ActionClass.__members__


@pytest.mark.parametrize(
    "action",
    [
        ActionClass.LIVE_PROMOTION,
        ActionClass.RISK_ENVELOPE_EXPANSION,
        ActionClass.CAPITAL_CHANGE,
        ActionClass.ACCOUNT_IDENTITY_CHANGE,
        ActionClass.CREDENTIAL_CHANGE,
        ActionClass.CHARTER_CHANGE,
    ],
)
def test_external_authority_stays_with_user(action):
    verdict = authority_for(action)
    assert verdict.allowed is False
    assert verdict.human_required is True
    assert verdict.owner_role == "account_owner"


def test_machine_risk_promotion_and_submit_reasons_scope_out_privilege():
    """Generic machine classes must name the owner-approval boundary so a
    broad risk/promotion classification can never read as authorizing
    envelope expansion or live promotion."""

    for action in (
        ActionClass.RISK_CHANGE,
        ActionClass.PROMOTION_CHANGE,
        ActionClass.ORDER_SUBMIT,
    ):
        assert "account_owner approval" in authority_for(action).reason
