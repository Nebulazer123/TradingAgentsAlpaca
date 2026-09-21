"""Source-only checks for the ten TradingAgents Codex automation records.

The records themselves remain external, paused operational configuration.  This
test suite reads them as evidence; it never mutates them or treats a paused
record as deployment proof.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from tradingagents.evals.automation_health_audit import (
    _contract_local_occurrences,
    evaluate_schedule_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "config" / "automation_schedule_contract.json"
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


def _fixture_contract_and_automation_records(destination: Path) -> tuple[Path, Path]:
    """Materialize deterministic external records from the versioned contract."""

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    root = destination / "automations"
    for automation_id, record in contract["automations"].items():
        prompt = "\n".join(("fixture TradingAgents automation", *record["required_prompt_phrases"]))
        record["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        target = record["target"]
        lines = (
            'version = 1',
            f'id = {json.dumps(automation_id)}',
            'kind = "cron"',
            f'name = {json.dumps(record["name"])}',
            f'prompt = {json.dumps(prompt)}',
            'status = "PAUSED"',
            f'rrule = {json.dumps(record["rrule"])}',
            f'model = {json.dumps(record["model"])}',
            f'reasoning_effort = {json.dumps(record["reasoning_effort"])}',
            f'notification_policy = {json.dumps(record["notification_policy"])}',
            f'cwds = {json.dumps(record["cwds"])}',
            f'execution_environment = {json.dumps(record["execution_environment"])}',
            "target = { "
            f'type = {json.dumps(target["type"])}, '
            f'project_id = {json.dumps(target["project_id"])} '
            "}",
        )
        path = root / automation_id
        path.mkdir(parents=True)
        (path / "automation.toml").write_text("\n".join(lines), encoding="utf-8")
    contract_path = destination / "automation_schedule_contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    return contract_path, root


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


def test_fixture_records_are_checked_against_the_versioned_contract(tmp_path):
    """The normal contract test is deterministic and does not inspect a workstation."""

    contract_path, automation_root = _fixture_contract_and_automation_records(tmp_path)

    result = evaluate_schedule_contract(
        contract_path=contract_path,
        automation_root=automation_root,
        role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
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
    assert all(row["mismatches"] == [] for row in by_id.values())
    assert all(row["status"] == "match" for row in by_id.values())
    assert all(row["deployment_status"] == "not_deployed" for row in by_id.values())


def test_contract_rejects_model_effort_notification_and_prompt_drift(tmp_path):
    contract_path, automation_root = _fixture_contract_and_automation_records(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    record = contract["automations"]["tradingagents-overnight-research"]
    record["model"] = "wrong-model"
    record["reasoning_effort"] = "wrong-effort"
    record["notification_policy"] = "always"
    record["prompt_sha256"] = "0" * 64
    path = tmp_path / "automation_schedule_contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")

    result = evaluate_schedule_contract(
        contract_path=path,
        automation_root=automation_root,
        role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
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
    }


def test_missing_contract_fails_closed_without_claiming_deployment(tmp_path):
    _contract_path, automation_root = _fixture_contract_and_automation_records(tmp_path)
    result = evaluate_schedule_contract(
        contract_path=tmp_path / "missing.json",
        automation_root=automation_root,
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
    contract_path, automation_root = _fixture_contract_and_automation_records(tmp_path)

    def write_contract(name, mutate):
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        mutate(contract)
        path = tmp_path / name
        path.write_text(json.dumps(contract), encoding="utf-8")
        return evaluate_schedule_contract(
            contract_path=path,
            automation_root=automation_root,
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
    contract_path, automation_root = _fixture_contract_and_automation_records(tmp_path)

    predeployment = evaluate_schedule_contract(
        contract_path=contract_path,
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
        contract_path=contract_path,
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
        contract_path, automation_root = _fixture_contract_and_automation_records(
            tmp_path / automation_id
        )
        _set_automation_status(automation_root, automation_id, "ACTIVE")

        result = evaluate_schedule_contract(
            contract_path=contract_path,
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

        contract = json.loads(contract_path.read_text(encoding="utf-8"))
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
    contract_path, automation_root = _fixture_contract_and_automation_records(tmp_path)

    invalid_phase = evaluate_schedule_contract(
        contract_path=contract_path,
        automation_root=automation_root,
        role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
        deployment_phase="not-a-real-phase",
    )
    assert invalid_phase["issues"] == ["deployment_phase_invalid"]

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    del contract["deployment_policy"]["deployment_phases"]["frozen_observer"]
    path = tmp_path / "missing-phase-contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")

    missing_phase = evaluate_schedule_contract(
        contract_path=path,
        automation_root=automation_root,
        role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
    )
    assert missing_phase["issues"] == ["contract_deployment_phases"]


def _evaluate_mutated_contract(tmp_path: Path, name: str, mutate) -> dict:
    contract_path, automation_root = _fixture_contract_and_automation_records(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    mutate(contract)
    mutated_path = tmp_path / name
    mutated_path.write_text(json.dumps(contract), encoding="utf-8")
    return evaluate_schedule_contract(
        contract_path=mutated_path,
        automation_root=automation_root,
        role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
    )


def test_expected_central_schedules_encode_current_contract_rrules_in_central_time():
    """The explicit Central schedule section matches every captured rrule occurrence."""

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    expected_schedules = contract["expected_central_schedules"]

    assert set(expected_schedules) == set(contract["automations"])
    for automation_id, record in contract["automations"].items():
        entry = expected_schedules[automation_id]
        assert entry["timezone"] == "America/Chicago"
        occurrences = {
            (item["weekday"], item["hour"], item["minute"])
            for item in entry["occurrences"]
        }
        assert len(occurrences) == len(entry["occurrences"])
        weekday_index_to_token = dict(enumerate(("MO", "TU", "WE", "TH", "FR", "SA", "SU")))
        expected_set = {
            (weekday_index_to_token[weekday], minute_of_day // 60, minute_of_day % 60)
            for weekday, minute_of_day in _contract_local_occurrences(record["rrule"])
        }
        assert occurrences == expected_set


def test_current_paused_tomls_pass_with_expected_central_schedules_enforced(tmp_path):
    contract_path, automation_root = _fixture_contract_and_automation_records(tmp_path)

    result = evaluate_schedule_contract(
        contract_path=contract_path,
        automation_root=automation_root,
        role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
    )

    assert result["status"] == "not_deployed"
    assert result["contract_status"] == "pass"
    assert result["safe_predeployment"] is True
    assert result["deployment_proven"] is False
    assert all(row["mismatches"] == [] and row["status"] == "match" for row in result["automations"])

    for automation_id in FROZEN_OBSERVER_ACTIVE_IDS:
        _set_automation_status(automation_root, automation_id, "ACTIVE")

    frozen_observer = evaluate_schedule_contract(
        contract_path=contract_path,
        automation_root=automation_root,
        role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
        deployment_phase="frozen_observer",
    )
    assert frozen_observer["contract_status"] == "pass"


def test_missing_or_malformed_expected_central_schedules_fail_closed(tmp_path):
    def delete_section(contract):
        del contract["expected_central_schedules"]

    def non_mapping_section(contract):
        contract["expected_central_schedules"] = []

    def unexpected_key(contract):
        contract["expected_central_schedules"]["tradingagents-not-managed"] = (
            contract["expected_central_schedules"]["tradingagents-daily-report"]
        )

    def missing_entry(contract):
        del contract["expected_central_schedules"]["tradingagents-daily-report"]

    def malformed_hour(contract):
        contract["expected_central_schedules"]["tradingagents-daily-report"]["occurrences"][0][
            "hour"
        ] = 24

    def malformed_minute(contract):
        contract["expected_central_schedules"]["tradingagents-daily-report"]["occurrences"][0][
            "minute"
        ] = 60

    def malformed_weekday(contract):
        contract["expected_central_schedules"]["tradingagents-daily-report"]["occurrences"][0][
            "weekday"
        ] = "XX"

    def empty_occurrences(contract):
        contract["expected_central_schedules"]["tradingagents-daily-report"]["occurrences"] = []

    def entry_extra_field(contract):
        contract["expected_central_schedules"]["tradingagents-daily-report"]["extra"] = True

    def duplicate_occurrence(contract):
        entry = contract["expected_central_schedules"]["tradingagents-daily-report"]
        entry["occurrences"].append(dict(entry["occurrences"][0]))

    cases = [
        ("deleted-section", delete_section, ["contract_expected_central_schedules"]),
        ("non-mapping-section", non_mapping_section, ["contract_expected_central_schedules"]),
        ("unexpected-key", unexpected_key, ["contract_expected_central_schedules"]),
        (
            "missing-entry",
            missing_entry,
            ["contract_expected_central_schedule_missing_entry"],
        ),
        ("malformed-hour", malformed_hour, ["contract_expected_central_schedules"]),
        ("malformed-minute", malformed_minute, ["contract_expected_central_schedules"]),
        ("malformed-weekday", malformed_weekday, ["contract_expected_central_schedules"]),
        ("empty-occurrences", empty_occurrences, ["contract_expected_central_schedules"]),
        ("entry-extra-field", entry_extra_field, ["contract_expected_central_schedules"]),
        (
            "duplicate-occurrence",
            duplicate_occurrence,
            ["contract_expected_central_schedules"],
        ),
    ]
    for name, mutate, expected_issues in cases:
        result = _evaluate_mutated_contract(tmp_path / name, f"{name}.json", mutate)

        assert result["status"] == "invalid_contract", name
        assert result["contract_status"] == "fail", name
        assert result["issues"] == expected_issues, name
        assert result["deployment_proven"] is False, name
        assert result["safe_predeployment"] is False, name
        assert result["automations"] == [], name


def test_eastern_stored_one_hour_signature_is_flagged(tmp_path):
    def shift_wake_one_hour(contract):
        contract["automations"]["tradingagents-automation-wake-controller"]["rrule"] = (
            "RRULE:FREQ=WEEKLY;BYHOUR=7;BYMINUTE=45;BYDAY=MO,TU,WE,TH,FR"
        )

    def shift_self_healer_hours_one_hour(contract):
        contract["automations"]["tradingagents-autonomous-self-healer"]["rrule"] = (
            "RRULE:FREQ=WEEKLY;BYHOUR=8,10,12,14,16;BYMINUTE=03;BYDAY=MO,TU,WE,TH,FR"
        )

    wake_shifted = _evaluate_mutated_contract(
        tmp_path / "wake", "wake-eastern.json", shift_wake_one_hour
    )
    healer_shifted = _evaluate_mutated_contract(
        tmp_path / "healer", "healer-eastern.json", shift_self_healer_hours_one_hour
    )

    assert wake_shifted["status"] == "invalid_contract"
    assert wake_shifted["issues"] == ["contract_expected_central_schedule_eastern_stored"]
    assert healer_shifted["issues"] == ["contract_expected_central_schedule_eastern_stored"]


def test_arbitrary_central_schedule_drift_is_flagged_as_mismatch(tmp_path):
    def drift_daily_report_minute(contract):
        contract["automations"]["tradingagents-daily-report"]["rrule"] = (
            "RRULE:FREQ=WEEKLY;BYHOUR=15;BYMINUTE=31;BYDAY=MO,TU,WE,TH,FR"
        )

    def drop_friday_from_overnight(contract):
        contract["automations"]["tradingagents-overnight-research"]["rrule"] = (
            "RRULE:FREQ=WEEKLY;BYHOUR=3;BYMINUTE=30;BYDAY=MO,TU,WE,TH"
        )

    def partial_one_hour_shift_on_self_healer(contract):
        contract["automations"]["tradingagents-autonomous-self-healer"]["rrule"] = (
            "RRULE:FREQ=WEEKLY;BYHOUR=8,9,11,13,15;BYMINUTE=03;BYDAY=MO,TU,WE,TH,FR"
        )

    minute_drift = _evaluate_mutated_contract(
        tmp_path / "minute", "minute-drift.json", drift_daily_report_minute
    )
    weekday_drift = _evaluate_mutated_contract(
        tmp_path / "weekday", "weekday-drift.json", drop_friday_from_overnight
    )
    partial_shift = _evaluate_mutated_contract(
        tmp_path / "partial", "partial-shift.json", partial_one_hour_shift_on_self_healer
    )

    assert minute_drift["status"] == "invalid_contract"
    assert minute_drift["issues"] == ["contract_expected_central_schedule_mismatch"]
    assert weekday_drift["issues"] == ["contract_dependency_order"]
    assert partial_shift["issues"] == ["contract_expected_central_schedule_mismatch"]


def _evaluate_mutated_actual_toml(
    tmp_path: Path,
    automation_id: str,
    rrule_value: str,
) -> dict:
    contract_path, automation_root = _fixture_contract_and_automation_records(tmp_path)
    _replace_automation_toml_line(
        automation_root,
        automation_id,
        "rrule",
        f"rrule = {json.dumps(rrule_value)}",
    )
    return evaluate_schedule_contract(
        contract_path=contract_path,
        automation_root=automation_root,
        role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
    )


def test_actual_toml_plus_one_hour_storage_fails_closed_with_eastern_issue(tmp_path):
    """Actual +1h drift fails closed even while the versioned contract is unchanged."""

    eastern_wake = _evaluate_mutated_actual_toml(
        tmp_path / "wake",
        "tradingagents-automation-wake-controller",
        "RRULE:FREQ=WEEKLY;BYHOUR=7;BYMINUTE=45;BYDAY=MO,TU,WE,TH,FR",
    )
    eastern_healer = _evaluate_mutated_actual_toml(
        tmp_path / "healer",
        "tradingagents-autonomous-self-healer",
        "RRULE:FREQ=WEEKLY;BYHOUR=8,10,12,14,16;BYMINUTE=03;BYDAY=MO,TU,WE,TH,FR",
    )

    for name, result in (("wake", eastern_wake), ("healer", eastern_healer)):
        assert result["status"] == "invalid_contract", name
        assert result["contract_status"] == "fail", name
        assert result["issues"] == [
            "contract_expected_central_schedule_eastern_stored"
        ], name
        assert result["safe_predeployment"] is False, name
        assert result["deployment_proven"] is False, name


def test_actual_toml_arbitrary_rrule_drift_fails_closed_with_mismatch_issue(tmp_path):
    minute_drift = _evaluate_mutated_actual_toml(
        tmp_path / "minute",
        "tradingagents-daily-report",
        "RRULE:FREQ=WEEKLY;BYHOUR=15;BYMINUTE=31;BYDAY=MO,TU,WE,TH,FR",
    )
    weekday_drift = _evaluate_mutated_actual_toml(
        tmp_path / "weekday",
        "tradingagents-overnight-research",
        "RRULE:FREQ=WEEKLY;BYHOUR=3;BYMINUTE=30;BYDAY=MO,TU,WE,TH",
    )
    partial_shift = _evaluate_mutated_actual_toml(
        tmp_path / "partial",
        "tradingagents-autonomous-self-healer",
        "RRULE:FREQ=WEEKLY;BYHOUR=7,10,11,13,15;BYMINUTE=03;BYDAY=MO,TU,WE,TH,FR",
    )

    for name, result in (
        ("minute", minute_drift),
        ("weekday", weekday_drift),
        ("partial", partial_shift),
    ):
        assert result["status"] == "invalid_contract", name
        assert result["contract_status"] == "fail", name
        assert result["issues"] == [
            "contract_expected_central_schedule_mismatch"
        ], name
        assert result["safe_predeployment"] is False, name
        assert result["deployment_proven"] is False, name


def test_schedule_contract_requires_a_same_day_predecessor_for_each_dependent_run(tmp_path):
    """A Monday-only prerequisite cannot satisfy Tuesday through Friday work."""

    def restrict_overnight_research_to_monday(contract):
        contract["automations"]["tradingagents-overnight-research"]["rrule"] = (
            "RRULE:FREQ=WEEKLY;BYHOUR=3;BYMINUTE=30;BYDAY=MO"
        )
        contract["expected_central_schedules"]["tradingagents-overnight-research"] = {
            "timezone": "America/Chicago",
            "occurrences": [{"weekday": "MO", "hour": 3, "minute": 30}],
        }

    result = _evaluate_mutated_contract(
        tmp_path,
        "monday-only-overnight-research.json",
        restrict_overnight_research_to_monday,
    )

    assert result["issues"] == ["contract_dependency_order"]


def test_unexpected_automation_fails_safe_predeployment(tmp_path):
    contract_path, automation_root = _fixture_contract_and_automation_records(tmp_path)
    unexpected = automation_root / "tradingagents-unexpected"
    unexpected.mkdir()
    (unexpected / "automation.toml").write_text(
        'id = "tradingagents-unexpected"\nstatus = "PAUSED"\n', encoding="utf-8"
    )

    result = evaluate_schedule_contract(
        contract_path=contract_path,
        automation_root=automation_root,
        role_contract_path=REPO_ROOT / "config" / "automation_roles.json",
    )

    assert result["issues"] == ["unexpected_automation_ids"]
    assert result["unexpected_automation_ids"] == ["tradingagents-unexpected"]
    assert result["safe_predeployment"] is False


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
            contract_path, automation_root = _fixture_contract_and_automation_records(
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
                contract_path=contract_path,
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
