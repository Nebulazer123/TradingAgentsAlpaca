import pytest

from tradingagents.orchestration.authority import ActionClass, authority_for


@pytest.mark.parametrize(
    ("action", "owner"),
    [
        (ActionClass.TRADE_DECISION, "portfolio_executive"),
        (ActionClass.STRATEGY_CHANGE, "strategy_learning"),
        (ActionClass.RISK_CHANGE, "portfolio_executive"),
        (ActionClass.PROMOTION_CHANGE, "strategy_learning"),
        (ActionClass.FREEZE, "integrity_controller"),
        (ActionClass.REPAIR, "reliability_controller"),
        (ActionClass.VERIFY, "integrity_verifier"),
        (ActionClass.REARM, "reliability_controller"),
        (ActionClass.ORDER_SUBMIT, "execution_operator"),
    ],
)
def test_machine_actions_have_internal_owners(action, owner):
    verdict = authority_for(action)
    assert verdict.allowed is True
    assert verdict.human_required is False
    assert verdict.owner_role == owner


@pytest.mark.parametrize(
    "action",
    [
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
