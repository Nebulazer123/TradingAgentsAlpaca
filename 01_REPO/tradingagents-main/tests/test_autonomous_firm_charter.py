from tradingagents.orchestration.authority import ActionClass, authority_for


def test_machine_owns_trading_and_ordinary_recovery():
    machine_actions = {
        ActionClass.TRADE_DECISION,
        ActionClass.STRATEGY_CHANGE,
        ActionClass.RISK_CHANGE,
        ActionClass.PROMOTION_CHANGE,
        ActionClass.FREEZE,
        ActionClass.REPAIR,
        ActionClass.VERIFY,
        ActionClass.REARM,
        ActionClass.ORDER_SUBMIT,
    }
    assert all(authority_for(action).human_required is False for action in machine_actions)


def test_only_external_account_authority_requires_the_user():
    human_actions = {
        ActionClass.CAPITAL_CHANGE,
        ActionClass.ACCOUNT_IDENTITY_CHANGE,
        ActionClass.CREDENTIAL_CHANGE,
        ActionClass.CHARTER_CHANGE,
    }
    assert all(authority_for(action).human_required is True for action in human_actions)
