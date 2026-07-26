import json
from pathlib import Path

import pytest

from tradingagents.orchestration.authority import ActionClass, authority_for

ROOT = Path(__file__).parents[1]
EXPECTED_AUTOMATIONS = {
    "tradingagents-automation-sleep-controller": "schedule_controller",
    "tradingagents-automation-wake-controller": "schedule_controller",
    "tradingagents-autonomous-execution-board": "portfolio_executive",
    "tradingagents-autonomous-safety-sentinel": "integrity_verifier",
    "tradingagents-autonomous-self-healer": "reliability_controller",
    "tradingagents-daily-report": "reporting_utility",
    "tradingagents-market-supervisor": "execution_operator",
    "tradingagents-overnight-research": "strategy_learning",
    "tradingagents-paper-tournament": "strategy_learning",
    "tradingagents-preopen-validation": "integrity_verifier",
}
MACHINE_ROLE_ACTIONS = {
    "strategy_learning": {"strategy_change", "promotion_change"},
    "portfolio_executive": {"trade_decision", "risk_change"},
    "reliability_controller": {"repair", "rearm_request"},
    "integrity_verifier": {"freeze", "verify", "rearm_issue"},
    "execution_operator": {"order_submit"},
}
UTILITY_ROLES = {"schedule_controller", "reporting_utility"}
BROKER_WRITE_EFFECTS = {
    "broker_order_write",
    "submit_order",
    "cancel_order",
    "replace_order",
}
EXPECTED_COMMAND_FAMILIES = {
    "strategy_learning": [
        "alpaca plan-overnight --json-output",
        "alpaca paper-tournament run --all --dry-run --json-output",
        "policy sync-promotion",
    ],
    "portfolio_executive": [
        "research execution-board-review --json-output",
    ],
    "reliability_controller": [
        "research self-heal-handoff --json-output",
        "research self-heal-plan --execute-safe --json-output",
    ],
    "integrity_verifier": [
        "alpaca check",
        "alpaca reconcile-symbol-incident",
        "policy freeze-live",
        "policy recover-incident",
    ],
    "execution_operator": [
        "scripts/mac/ta_job.sh hourly",
    ],
    "schedule_controller": [
        "automation status",
        "research controller-patrol --json-output",
    ],
    "reporting_utility": [
        "scripts/mac/ta_job.sh daily-report",
        "scripts/mac/ta_job.sh deliver-outbox",
    ],
}


def _registry():
    path = ROOT / "config" / "automation_roles.json"
    assert path.exists(), "automation role registry must be versioned in config"
    return json.loads(path.read_text(encoding="utf-8"))


def test_role_registry_matches_the_exact_charter_owners_and_ten_automations():
    registry = _registry()

    assert registry["schema_version"] == 1
    assert registry["automations"] == EXPECTED_AUTOMATIONS
    assert set(registry["roles"]) == set(MACHINE_ROLE_ACTIONS) | UTILITY_ROLES
    all_machine_actions = set().union(*MACHINE_ROLE_ACTIONS.values())
    for role, actions in MACHINE_ROLE_ACTIONS.items():
        record = registry["roles"][role]
        assert set(record["allowed_actions"]) == actions
        assert record["kind"] == "business"
        assert record["command_family"] == EXPECTED_COMMAND_FAMILIES[role]
        expected_forbidden = all_machine_actions - actions
        if role == "execution_operator":
            expected_forbidden |= {"recovery_order_submit"}
        else:
            expected_forbidden |= BROKER_WRITE_EFFECTS
        assert set(record["forbidden_effects"]) == expected_forbidden
    assert (
        registry["roles"]["strategy_learning"]["display_name"]
        == "Research & Strategy Council"
    )


def test_utility_roles_have_zero_business_authority():
    registry = _registry()

    for role in UTILITY_ROLES:
        record = registry["roles"][role]
        assert record["kind"] == "utility"
        assert record["allowed_actions"] == []
        assert record["command_family"] == EXPECTED_COMMAND_FAMILIES[role]
        assert set(record["forbidden_effects"]) == (
            set().union(*MACHINE_ROLE_ACTIONS.values())
            | BROKER_WRITE_EFFECTS
        )


def test_each_business_action_has_exactly_one_registry_owner():
    registry = _registry()
    machine_actions = {
        action.value
        for action in ActionClass
        if authority_for(action).human_required is False
    }
    owners = {
        action: [
            role
            for role, record in registry["roles"].items()
            if action in record["allowed_actions"]
        ]
        for action in machine_actions
    }

    assert all(len(action_owners) == 1 for action_owners in owners.values())
    assert {
        action: action_owners[0] for action, action_owners in owners.items()
    } == {
        action: authority_for(action).owner_role for action in machine_actions
    }


@pytest.mark.parametrize(
    ("role", "forbidden"),
    [
        (
            "reliability_controller",
            {"verify", "rearm_issue", "order_submit"},
        ),
        (
            "integrity_verifier",
            {"repair", "rearm_request", "order_submit"},
        ),
        (
            "strategy_learning",
            {
                "freeze",
                "repair",
                "verify",
                "rearm_request",
                "rearm_issue",
                "order_submit",
            },
        ),
    ],
)
def test_role_contract_does_not_cross_the_chain_of_command(role, forbidden):
    allowed = set(_registry()["roles"][role]["allowed_actions"])

    assert allowed.isdisjoint(forbidden)


def test_execution_requires_bounded_paper_and_separate_normal_trade_inputs():
    execution = _registry()["roles"]["execution_operator"]

    assert execution["allowed_actions"] == ["order_submit"]
    assert execution["required_inputs"] == [
        "authorized_paper_order_request",
        "authorized_normal_trade_intent",
    ]


def test_strategy_tournament_command_is_intent_only_and_cannot_write_orders():
    strategy = _registry()["roles"]["strategy_learning"]

    tournament_commands = [
        command
        for command in strategy["command_family"]
        if "paper-tournament" in command
    ]
    assert tournament_commands == [
        "alpaca paper-tournament run --all --dry-run --json-output"
    ]
    assert "broker_order_write" in strategy["forbidden_effects"]
    assert "order_submit" in strategy["forbidden_effects"]


def test_role_contract_does_not_claim_human_or_separate_process_approval():
    registry_text = json.dumps(_registry()).casefold()
    source_text = "\n".join(
        (ROOT / path).read_text(encoding="utf-8").casefold()
        for path in (
            "tradingagents/orchestration/recovery.py",
            "tradingagents/orchestration/self_heal.py",
            "cli/main.py",
        )
    )

    assert "human_approval" not in registry_text
    for unsupported_claim in (
        "independent_verifier",
        "independent_verification",
        "durable independent evidence",
        "independently verified packets",
    ):
        assert unsupported_claim not in source_text
