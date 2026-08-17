"""Source-only checks for the ten TradingAgents Codex automation records.

The records themselves remain external, paused operational configuration.  This
test suite reads them as evidence; it never mutates them or treats a paused
record as deployment proof.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from tradingagents.evals.automation_health_audit import evaluate_schedule_contract

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "config" / "automation_schedule_contract.json"
AUTOMATION_ROOT = Path.home() / ".codex" / "automations"
FROZEN_OBSERVER_ACTIVE_IDS = frozenset(
    {
        "tradingagents-overnight-research",
        "tradingagents-preopen-validation",
        "tradingagents-autonomous-self-healer",
        "tradingagents-autonomous-safety-sentinel",
        "tradingagents-autonomous-execution-board",
        "tradingagents-paper-tournament",
        "tradingagents-daily-report",
    }
)
FROZEN_OBSERVER_PAUSED_IDS = frozenset(
    {
        "tradingagents-market-supervisor",
        "tradingagents-automation-wake-controller",
        "tradingagents-automation-sleep-controller",
    }
)


def _copy_automation_records(destination: Path) -> Path:
    root = destination / "automations"
    shutil.copytree(AUTOMATION_ROOT, root)
    return root


def _set_automation_status(root: Path, automation_id: str, status: str) -> None:
    path = root / automation_id / "automation.toml"
    updated = re.sub(
        r'^status = ".*"$',
        f'status = "{status}"',
        path.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    path.write_text(updated, encoding="utf-8")


def _replace_automation_toml_line(
    root: Path,
    automation_id: str,
    field: str,
    replacement: str,
) -> None:
    path = root / automation_id / "automation.toml"
    updated, replacement_count = re.subn(
        rf"^{re.escape(field)} = .*$",
        replacement,
        path.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    assert replacement_count == 1
    path.write_text(updated, encoding="utf-8")


def test_current_external_records_are_checked_against_the_versioned_contract():
    """Known predeployment drift is explicit rather than a false green."""

    result = evaluate_schedule_contract(
        contract_path=CONTRACT_PATH,
        automation_root=AUTOMATION_ROOT,
    )

    assert result["status"] == "not_deployed"
    assert result["contract_status"] == "pass"
    assert result["automation_count"] == 10
    assert result["configured_count"] == 10
    assert result["paused_count"] == 10
    assert result["safe_predeployment"] is True
    assert result["deployment_proven"] is False

    by_id = {row["automation_id"]: row for row in result["automations"]}
    assert set(by_id) == {
        "tradingagents-automation-sleep-controller",
        "tradingagents-automation-wake-controller",
        "tradingagents-autonomous-execution-board",
        "tradingagents-autonomous-safety-sentinel",
        "tradingagents-autonomous-self-healer",
        "tradingagents-daily-report",
        "tradingagents-market-supervisor",
        "tradingagents-overnight-research",
        "tradingagents-paper-tournament",
        "tradingagents-preopen-validation",
    }
    assert all(
        "role" not in {item["field"] for item in row["mismatches"]}
        for row in by_id.values()
    )
    assert {
        row["automation_id"]: {item["field"] for item in row["mismatches"]}
        for row in by_id.values()
    } == {
        "tradingagents-automation-sleep-controller": {"rrule"},
        "tradingagents-automation-wake-controller": {"rrule"},
        "tradingagents-autonomous-execution-board": {"rrule"},
        "tradingagents-autonomous-safety-sentinel": {"rrule"},
        "tradingagents-autonomous-self-healer": {"rrule", "prompt_sha256", "prompt_semantic"},
        "tradingagents-daily-report": {"rrule"},
        "tradingagents-market-supervisor": {"rrule"},
        "tradingagents-overnight-research": {"rrule"},
        "tradingagents-paper-tournament": {"rrule"},
        "tradingagents-preopen-validation": {"rrule"},
    }

    overnight = by_id["tradingagents-overnight-research"]
    assert overnight["status"] == "mismatch"
    assert overnight["deployment_status"] == "not_deployed"
    assert {
        item["field"] for item in overnight["mismatches"]
    } == {"rrule"}
    assert overnight["mismatches"][0]["expected"].startswith(
        "RRULE:FREQ=WEEKLY;BYHOUR=3;BYMINUTE=30"
    )
    assert overnight["mismatches"][0]["actual"].startswith(
        "RRULE:FREQ=WEEKLY;BYHOUR=4;BYMINUTE=30"
    )

    self_healer = by_id["tradingagents-autonomous-self-healer"]
    assert self_healer["status"] == "mismatch"
    assert "prompt_semantic" in {
        item["field"] for item in self_healer["mismatches"]
    }


def test_contract_rejects_model_effort_notification_and_prompt_drift(tmp_path):
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    record = contract["automations"]["tradingagents-overnight-research"]
    record["model"] = "wrong-model"
    record["reasoning_effort"] = "wrong-effort"
    record["notification_policy"] = "always"
    record["prompt_sha256"] = "0" * 64
    path = tmp_path / "automation_schedule_contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")

    result = evaluate_schedule_contract(
        contract_path=path,
        automation_root=AUTOMATION_ROOT,
    )

    row = next(
        item
        for item in result["automations"]
        if item["automation_id"] == "tradingagents-overnight-research"
    )
    assert row["status"] == "mismatch"
    assert {item["field"] for item in row["mismatches"]} >= {
        "model",
        "reasoning_effort",
        "notification_policy",
        "prompt_sha256",
        "rrule",
    }


def test_missing_contract_fails_closed_without_claiming_deployment(tmp_path):
    result = evaluate_schedule_contract(
        contract_path=tmp_path / "missing.json",
        automation_root=AUTOMATION_ROOT,
    )

    assert result == {
        "status": "invalid_contract",
        "contract_status": "fail",
        "automation_count": 0,
        "configured_count": 0,
        "paused_count": 0,
        "safe_predeployment": False,
        "deployment_proven": False,
        "issues": ["contract_unreadable"],
        "automations": [],
    }


def test_contract_requires_no_submit_for_active_observers_and_dependencies(tmp_path):
    def write_contract(name, mutate):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        mutate(contract)
        path = tmp_path / name
        path.write_text(json.dumps(contract), encoding="utf-8")
        return evaluate_schedule_contract(
            contract_path=path,
            automation_root=AUTOMATION_ROOT,
            role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
        )

    paused_order_capable_supervisor = write_contract(
        "paused-order-capable-supervisor.json",
        lambda contract: contract["automations"]["tradingagents-market-supervisor"].update(
            no_submit=False
        ),
    )
    assert paused_order_capable_supervisor["contract_status"] == "pass"
    assert next(
        row
        for row in paused_order_capable_supervisor["automations"]
        if row["automation_id"] == "tradingagents-market-supervisor"
    )["no_submit"] is False

    active_no_submit = write_contract(
        "active-no-submit.json",
        lambda contract: contract["automations"]["tradingagents-overnight-research"].update(
            no_submit=False
        ),
    )
    assert active_no_submit["issues"] == ["contract_frozen_observer_active_no_submit"]

    weakened_policy = write_contract(
        "policy.json",
        lambda contract: contract["deployment_policy"].update(safe_statuses=[]),
    )
    assert weakened_policy["issues"] == ["contract_deployment_policy"]

    missing_sentinel = write_contract(
        "dependencies.json",
        lambda contract: contract["automations"]["tradingagents-market-supervisor"].update(
            depends_on=[]
        ),
    )
    assert missing_sentinel["issues"] == ["contract_required_dependencies"]

    reversed_dependency = write_contract(
        "dependency-order.json",
        lambda contract: contract["automations"]["tradingagents-autonomous-safety-sentinel"].update(
            rrule="RRULE:FREQ=WEEKLY;BYHOUR=9,10,11,12,13,14,15;BYMINUTE=20;BYDAY=MO,TU,WE,TH,FR"
        ),
    )
    assert reversed_dependency["issues"] == ["contract_dependency_order"]

    late_sentinel_occurrence = write_contract(
        "late-sentinel-occurrence.json",
        lambda contract: contract["automations"]["tradingagents-autonomous-safety-sentinel"].update(
            rrule="RRULE:FREQ=WEEKLY;BYHOUR=8,15;BYMINUTE=20;BYDAY=MO,TU,WE,TH,FR"
        ),
    )
    assert late_sentinel_occurrence["issues"] == ["contract_dependency_order"]

    missing_sentinel_cycle = write_contract(
        "missing-sentinel-cycle.json",
        lambda contract: contract["automations"]["tradingagents-autonomous-safety-sentinel"].update(
            rrule="RRULE:FREQ=WEEKLY;BYHOUR=8,14;BYMINUTE=20;BYDAY=MO,TU,WE,TH,FR"
        ),
    )
    assert missing_sentinel_cycle["issues"] == ["contract_dependency_order"]

    missing_sentinel_weekdays = write_contract(
        "missing-sentinel-weekdays.json",
        lambda contract: contract["automations"]["tradingagents-autonomous-safety-sentinel"].update(
            rrule="RRULE:FREQ=WEEKLY;BYHOUR=8,9,10,11,12,13,14;BYMINUTE=20;BYDAY=MO"
        ),
    )
    assert missing_sentinel_weekdays["issues"] == ["contract_dependency_order"]

    unknown_dependency = write_contract(
        "unknown-dependency.json",
        lambda contract: contract["automations"]["tradingagents-paper-tournament"].update(
            depends_on=["tradingagents-not-real"]
        ),
    )
    assert unknown_dependency["issues"] == ["contract_unknown_dependency"]

    dependency_cycle = write_contract(
        "dependency-cycle.json",
        lambda contract: contract["automations"]["tradingagents-overnight-research"].update(
            depends_on=["tradingagents-paper-tournament"]
        ),
    )
    assert dependency_cycle["issues"] == ["contract_dependency_cycle"]


def test_schedule_contract_supports_predeployment_and_frozen_observer_phases(tmp_path):
    automation_root = _copy_automation_records(tmp_path)

    predeployment = evaluate_schedule_contract(
        contract_path=CONTRACT_PATH,
        automation_root=automation_root,
        role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
    )

    assert predeployment["safe_predeployment"] is True
    assert {row["automation_id"] for row in predeployment["automations"]} == (
        FROZEN_OBSERVER_ACTIVE_IDS | FROZEN_OBSERVER_PAUSED_IDS
    )
    assert {
        row["automation_id"]
        for row in predeployment["automations"]
        if any(item["field"] == "deployment_phase_status" for item in row["mismatches"])
    } == set()

    for automation_id in FROZEN_OBSERVER_ACTIVE_IDS:
        _set_automation_status(automation_root, automation_id, "ACTIVE")

    frozen_observer = evaluate_schedule_contract(
        contract_path=CONTRACT_PATH,
        automation_root=automation_root,
        role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
        deployment_phase="frozen_observer",
    )

    assert frozen_observer["safe_predeployment"] is False
    assert {
        row["automation_id"]
        for row in frozen_observer["automations"]
        if any(item["field"] == "deployment_phase_status" for item in row["mismatches"])
    } == set()


def test_schedule_contract_rejects_each_protected_frozen_observer_activation(tmp_path):
    for automation_id in FROZEN_OBSERVER_PAUSED_IDS:
        automation_root = _copy_automation_records(tmp_path / automation_id)
        _set_automation_status(automation_root, automation_id, "ACTIVE")

        result = evaluate_schedule_contract(
            contract_path=CONTRACT_PATH,
            automation_root=automation_root,
            role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
            deployment_phase="frozen_observer",
        )

        row = next(
            item for item in result["automations"] if item["automation_id"] == automation_id
        )
        assert {
            item["field"]: item for item in row["mismatches"]
        }["deployment_phase_status"] == {
            "field": "deployment_phase_status",
            "expected": "PAUSED",
            "actual": "ACTIVE",
        }

        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        phase = contract["deployment_policy"]["deployment_phases"]["frozen_observer"]
        phase["active_automation_ids"].remove("tradingagents-overnight-research")
        phase["active_automation_ids"].append(automation_id)
        phase["paused_automation_ids"].remove(automation_id)
        phase["paused_automation_ids"].append("tradingagents-overnight-research")
        contract_path = tmp_path / f"{automation_id}-active.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")

        contract_result = evaluate_schedule_contract(
            contract_path=contract_path,
            automation_root=automation_root,
            role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
            deployment_phase="frozen_observer",
        )
        assert contract_result["issues"] == ["contract_deployment_phases"]


def test_schedule_contract_rejects_invalid_frozen_observer_phase_and_contract(tmp_path):
    automation_root = _copy_automation_records(tmp_path)

    invalid_phase = evaluate_schedule_contract(
        contract_path=CONTRACT_PATH,
        automation_root=automation_root,
        role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
        deployment_phase="not-a-real-phase",
    )
    assert invalid_phase["issues"] == ["deployment_phase_invalid"]

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    del contract["deployment_policy"]["deployment_phases"]["frozen_observer"]
    path = tmp_path / "missing-phase-contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")

    missing_phase = evaluate_schedule_contract(
        contract_path=path,
        automation_root=automation_root,
        role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
    )
    assert missing_phase["issues"] == ["contract_deployment_phases"]


def test_schedule_contract_rejects_identity_drift_in_both_deployment_phases(tmp_path):
    automation_id = "tradingagents-overnight-research"
    identity_drift = {
        "name": 'name = "Incorrect automation name"',
        "target": 'target = { type = "project", project_id = "wrong-project" }',
        "cwds": 'cwds = ["/tmp/not-tradingagents"]',
        "execution_environment": 'execution_environment = "remote"',
    }

    for deployment_phase in ("predeployment_paused", "frozen_observer"):
        for field, replacement in identity_drift.items():
            automation_root = _copy_automation_records(
                tmp_path / deployment_phase / field
            )
            if deployment_phase == "frozen_observer":
                for active_id in FROZEN_OBSERVER_ACTIVE_IDS:
                    _set_automation_status(automation_root, active_id, "ACTIVE")
            _replace_automation_toml_line(
                automation_root,
                automation_id,
                field,
                replacement,
            )

            result = evaluate_schedule_contract(
                contract_path=CONTRACT_PATH,
                automation_root=automation_root,
                role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
                deployment_phase=deployment_phase,
            )

            row = next(
                item
                for item in result["automations"]
                if item["automation_id"] == automation_id
            )
            assert field in {item["field"] for item in row["mismatches"]}
