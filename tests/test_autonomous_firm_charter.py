import json
from pathlib import Path

from tradingagents.orchestration.authority import ActionClass, authority_for


def test_machine_owns_research_paper_and_safe_recovery():
    machine_actions = {
        ActionClass.TRADE_DECISION,
        ActionClass.STRATEGY_CHANGE,
        ActionClass.RISK_CHANGE,
        ActionClass.PROMOTION_CHANGE,
        ActionClass.FREEZE,
        ActionClass.REPAIR,
        ActionClass.VERIFY,
        ActionClass.REARM_REQUEST,
        ActionClass.REARM_ISSUE,
        ActionClass.ORDER_SUBMIT,
    }
    assert all(authority_for(action).human_required is False for action in machine_actions)


def test_live_promotion_and_envelope_expansion_require_the_owner():
    owner_approval_actions = {
        ActionClass.LIVE_PROMOTION,
        ActionClass.RISK_ENVELOPE_EXPANSION,
    }
    assert all(authority_for(action).human_required is True for action in owner_approval_actions)


def test_only_external_account_authority_requires_the_user():
    human_actions = {
        ActionClass.CAPITAL_CHANGE,
        ActionClass.ACCOUNT_IDENTITY_CHANGE,
        ActionClass.CREDENTIAL_CHANGE,
        ActionClass.CHARTER_CHANGE,
    }
    assert all(authority_for(action).human_required is True for action in human_actions)


def test_autonomous_firm_config_v3_exactly_partitions_the_action_enum():
    path = Path(__file__).parents[1] / "config" / "autonomous_firm.json"
    config = json.loads(path.read_text(encoding="utf-8"))

    assert config["schema_version"] == 3
    for key in ("machine_actions", "owner_approval_actions", "human_actions"):
        actions = config[key]
        assert isinstance(actions, list)
        assert all(isinstance(action, str) and action for action in actions)
        assert len(actions) == len(set(actions))
    machine_actions = set(config["machine_actions"])
    owner_approval_actions = set(config["owner_approval_actions"])
    human_actions = set(config["human_actions"])
    assert machine_actions.isdisjoint(owner_approval_actions)
    assert machine_actions.isdisjoint(human_actions)
    assert owner_approval_actions.isdisjoint(human_actions)
    assert (
        machine_actions | owner_approval_actions | human_actions
        == {action.value for action in ActionClass}
    )
    assert "rearm" not in machine_actions
    assert "integrity_controller" not in json.dumps(config)
