from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli import main as cli_main
from cli.main import app
from tradingagents.evals import shadow_trial

UTC = dt.timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


class _CalendarFake:
    def __init__(self, dates: set[str]) -> None:
        self.dates = dates
        self.calls: list[tuple[str, str]] = []

    def list_calendar(self, *, start: str, end: str) -> list[dict[str, str]]:
        self.calls.append((start, end))
        return [{"date": start}] if start == end and start in self.dates else []

    def __getattr__(self, name: str):
        raise AssertionError(f"unexpected broker method: {name}")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _moment(date: str, hour: int = 14) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{date}T{hour:02d}:00:00+00:00")


def _set_clock(monkeypatch: pytest.MonkeyPatch, date: str, hour: int = 14) -> None:
    monkeypatch.setattr(shadow_trial, "_utc_now", lambda: _moment(date, hour))


def _calendar(
    date: str,
    *,
    observed_at: str | None = None,
    dates: list[str] | None = None,
) -> dict:
    return {
        "kind": "alpaca_regular_equities_calendar",
        "market_date": date,
        "observed_at": observed_at or f"{date}T13:59:00+00:00",
        "sessions": [{"date": item} for item in (dates if dates is not None else [date])],
    }


def _write_schedule_fixture(
    root: Path,
    *,
    active_id: str | None = None,
    omit_id: str | None = None,
) -> tuple[Path, Path, Path]:
    contract = root / "schedule-contract.json"
    roles = root / "automation-roles.json"
    automation_root = root / "automations"
    contract_payload = json.loads(
        (REPO_ROOT / "config" / "automation_schedule_contract.json").read_text(
            encoding="utf-8"
        )
    )
    roles_payload = json.loads(
        (REPO_ROOT / "config" / "automation_roles.json").read_text(encoding="utf-8")
    )
    for automation_id, record in contract_payload["automations"].items():
        if automation_id == omit_id:
            continue
        prompt = " ".join(record["required_prompt_phrases"])
        record["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        toml_path = automation_root / automation_id / "automation.toml"
        toml_path.parent.mkdir(parents=True, exist_ok=True)
        toml_path.write_text(
            "\n".join(
                [
                    f"name = {json.dumps(record['name'])}",
                    f"prompt = {json.dumps(prompt)}",
                    f"status = {json.dumps('ACTIVE' if automation_id == active_id else 'PAUSED')}",
                    (
                        "target = { "
                        f"type = {json.dumps(record['target']['type'])}, "
                        f"project_id = {json.dumps(record['target']['project_id'])} "
                        "}"
                    ),
                    f"cwds = {json.dumps(record['cwds'])}",
                    f"execution_environment = {json.dumps(record['execution_environment'])}",
                    f"rrule = {json.dumps(record['rrule'])}",
                    f"model = {json.dumps(record['model'])}",
                    f"reasoning_effort = {json.dumps(record['reasoning_effort'])}",
                    f"notification_policy = {json.dumps(record['notification_policy'])}",
                ]
            ),
            encoding="utf-8",
        )
    _write_json(contract, contract_payload)
    _write_json(roles, roles_payload)
    return contract, roles, automation_root


def _control(path: Path, *, frozen: bool = True, malformed: bool = False) -> Path:
    _write_json(
        path,
        ({"frozen": "true"} if malformed else {
            "frozen": frozen,
            "reason": "manual safety hold",
            "dead_man_expires_at": "2026-12-31T00:00:00+00:00",
        }),
    )
    return path


def _configure_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    frozen: bool = True,
    malformed_control: bool = False,
    active_id: str | None = None,
    omit_id: str | None = None,
) -> dict[str, Path]:
    manual_root = tmp_path / "results" / "manual_shadow"
    control = _control(
        tmp_path / "results" / "policy" / "live_control.json",
        frozen=frozen,
        malformed=malformed_control,
    )
    contract, roles, automation_root = _write_schedule_fixture(
        tmp_path / "schedule",
        active_id=active_id,
        omit_id=omit_id,
    )
    monkeypatch.setattr(shadow_trial, "_manual_shadow_root", lambda: manual_root)
    monkeypatch.setattr(shadow_trial, "_canonical_live_control_path", lambda: control)
    monkeypatch.setattr(shadow_trial, "_canonical_schedule_contract_path", lambda: contract)
    monkeypatch.setattr(shadow_trial, "_canonical_role_contract_path", lambda: roles)
    monkeypatch.setattr(shadow_trial, "_canonical_automation_root", lambda: automation_root)
    return {
        "manual_root": manual_root,
        "control": control,
        "contract": contract,
        "roles": roles,
        "automation_root": automation_root,
    }


def _payload(admission) -> dict:
    return dict(admission.envelope.payload)


def _start(
    monkeypatch: pytest.MonkeyPatch,
    *,
    date: str,
    predecessor_object_id: str | None = None,
) -> object:
    _set_clock(monkeypatch, date)
    return shadow_trial.create_shadow_day_start_manifest(
        run_id=f"run-{date}",
        market_date=date,
        calendar_evidence=_calendar(date),
        predecessor_object_id=predecessor_object_id,
    )


def _artifacts(
    root: Path,
    *,
    run_id: str,
    date: str,
    submitted_count: object = 0,
    sentinel_status: str = "HOLD",
) -> dict[str, Path]:
    sentinel = root / "artifacts" / f"sentinel-{date}.json"
    paper = root / "artifacts" / f"paper-{date}.json"
    generated_at = f"{date}T15:00:00+00:00"
    _write_json(
        sentinel,
        {
            "kind": "safety_sentinel_audit",
            "run_id": run_id,
            "market_date": date,
            "generated_at": generated_at,
            "status": sentinel_status,
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
            "actions_taken": [],
        },
    )
    _write_json(
        paper,
        {
            "kind": "paper_tournament_run",
            "run_id": run_id,
            "market_date": date,
            "generated_at": generated_at,
            "status": "HOLD",
            "dry_run": True,
            "submitted_count": submitted_count,
            "submitted": [] if submitted_count == 0 else ["not-an-order"],
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        },
    )
    return {"safety_sentinel": sentinel, "paper_tournament": paper}


def _day(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    start,
    *,
    date: str,
    artifacts: dict[str, Path] | None = None,
) -> object:
    _set_clock(monkeypatch, date, 16)
    start_payload = _payload(start)
    return shadow_trial.adjudicate_shadow_day(
        start_object_id=start.envelope.object_id,
        artifacts=artifacts or _artifacts(root, run_id=start_payload["run_id"], date=date),
        calendar_evidence=_calendar(date, observed_at=f"{date}T15:59:00+00:00"),
    )


def test_red_production_cli_exposes_only_pinned_non_authorizing_inputs(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    _set_clock(monkeypatch, "2026-08-21")
    calendar = _CalendarFake({"2026-08-21"})
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: calendar)

    help_result = runner.invoke(app, ["research", "shadow-day-start", "--help"])
    assert help_result.exit_code == 0
    for forbidden in (
        "--now", "--output-dir", "--live-control-path", "--schedule-contract-path",
        "--role-contract-path", "--automation-root", "--ledger-id", "--phase",
    ):
        assert forbidden not in help_result.output
    streak_help = runner.invoke(app, ["research", "shadow-streak-report", "--help"])
    assert streak_help.exit_code == 0
    assert "--day-record" not in streak_help.output
    assert not inspect.signature(shadow_trial.build_shadow_streak_report).parameters

    result = runner.invoke(
        app,
        ["research", "shadow-day-start", "--run-id", "cli-run", "--market-date", "2026-08-21", "--json-output"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert calendar.calls == [("2026-08-21", "2026-08-21")]
    assert Path(payload["record_path"]).is_relative_to(environment["manual_root"])
    assert payload["execution_authority"] == "none"
    assert payload["can_submit_orders"] is False


def test_red_generic_self_sealed_files_never_load_or_become_candidate(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    environment["manual_root"].mkdir(parents=True)
    forged = environment["manual_root"] / "shadow-day-start-forged.json"
    _write_json(forged, {"kind": "shadow-day-start", "object_id": "shadow-day-start-" + "0" * 64, "recorded_at": "2026-08-21T14:00:00+00:00", "payload_sha256": "0" * 64, "payload": {}})
    assert not hasattr(shadow_trial, "_seal")
    assert not hasattr(shadow_trial, "write_shadow_trial_packet")
    with pytest.raises(ValueError, match="ledger|admitted|record"):
        shadow_trial.load_shadow_record(forged.name, expected_kind="manual-shadow-day-start")
    with pytest.raises(ValueError, match="ledger|candidate|record"):
        shadow_trial.build_shadow_streak_report()


def test_red_store_owns_envelope_identity_and_recorded_time(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    payload = _payload(start)
    assert start.envelope.kind == "manual-shadow-day-start"
    assert start.envelope.recorded_at == "2026-08-21T14:00:00+00:00"
    assert start.envelope.object_id.startswith("manual-shadow-day-start-")
    assert {"object_id", "recorded_at", "schema_version", "kind"}.isdisjoint(payload)
    loaded = shadow_trial.load_shadow_record(start.envelope.object_id, expected_kind="manual-shadow-day-start")
    assert loaded.object_id == start.envelope.object_id


def test_red_start_api_has_no_caller_controlled_authority_paths_or_phase(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    signature = inspect.signature(shadow_trial.create_shadow_day_start_manifest)
    for forbidden in ("ledger_id", "phase", "live_control_path", "schedule_contract_path", "role_contract_path", "automation_root"):
        assert forbidden not in signature.parameters
    with pytest.raises(TypeError):
        shadow_trial.create_shadow_day_start_manifest(  # type: ignore[call-arg]
            run_id="bad", market_date="2026-08-21", calendar_evidence=_calendar("2026-08-21"),
            live_control_path=tmp_path / "substitute.json",
        )


def test_red_live_control_validation_uses_the_exact_captured_bytes(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    _set_clock(monkeypatch, "2026-08-21")
    capture = shadow_trial._read_regular_json

    def capture_then_replace(path):
        result = capture(path)
        if Path(path) == environment["control"]:
            _control(environment["control"], frozen=False)
        return result

    monkeypatch.setattr(shadow_trial, "_read_regular_json", capture_then_replace)
    start = shadow_trial.create_shadow_day_start_manifest(run_id="race-safe", market_date="2026-08-21", calendar_evidence=_calendar("2026-08-21"))
    assert _payload(start)["live_control"]["frozen"] is True
    assert json.loads(environment["control"].read_text(encoding="utf-8"))["frozen"] is False


@pytest.mark.parametrize("frozen,malformed", [(False, False), (True, True)])
def test_red_nonfrozen_or_malformed_canonical_control_cannot_start(tmp_path, monkeypatch, frozen, malformed):
    _configure_environment(monkeypatch, tmp_path, frozen=frozen, malformed_control=malformed)
    with pytest.raises(ValueError, match="live.control"):
        _start(monkeypatch, date="2026-08-21")


@pytest.mark.parametrize("active_id,omit_id", [("tradingagents-market-supervisor", None), (None, "tradingagents-market-supervisor")])
def test_red_exact_ten_paused_canonical_schedule_is_required(tmp_path, monkeypatch, active_id, omit_id):
    _configure_environment(monkeypatch, tmp_path, active_id=active_id, omit_id=omit_id)
    with pytest.raises(ValueError, match="schedule"):
        _start(monkeypatch, date="2026-08-21")


def test_red_calendar_is_mandatory_current_and_regular(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    _set_clock(monkeypatch, "2026-08-21")
    for evidence in (None, _calendar("2026-08-21", dates=[]), _calendar("2026-08-21", observed_at="2026-08-21T14:00:01+00:00")):
        with pytest.raises(ValueError, match="calendar"):
            shadow_trial.create_shadow_day_start_manifest(run_id="calendar-fail", market_date="2026-08-21", calendar_evidence=evidence)
    with pytest.raises(ValueError, match="current Central date"):
        shadow_trial.create_shadow_day_start_manifest(run_id="holiday", market_date="2026-08-20", calendar_evidence=_calendar("2026-08-20"))


def test_red_repeated_adjudication_and_corrupt_or_deleted_ledger_fail_closed(tmp_path, monkeypatch):
    environment = _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    _day(tmp_path, monkeypatch, start, date="2026-08-21")
    with pytest.raises(ValueError, match="already has|successor|transition"):
        _day(tmp_path, monkeypatch, start, date="2026-08-21")
    journal = environment["manual_root"] / "events.jsonl"
    journal.write_text("{bad journal}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ledger|evidence|journal"):
        shadow_trial.build_shadow_streak_report()


def test_red_deleted_admitted_object_fails_pinned_ledger_replay(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    start.path.unlink()
    with pytest.raises(ValueError, match="ledger|evidence|object"):
        shadow_trial.load_shadow_record(start.envelope.object_id)


def test_red_artifact_bindings_reject_bool_submission_unknown_and_missing_proof(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    bad_artifacts = _artifacts(tmp_path, run_id=_payload(start)["run_id"], date="2026-08-21", submitted_count=False)
    decision = _day(tmp_path, monkeypatch, start, date="2026-08-21", artifacts=bad_artifacts)
    decision_payload = _payload(decision)
    assert decision_payload["status"] == "failed"
    assert "paper_tournament_submission_count_invalid" in decision_payload["reasons"]
    assert set(decision_payload["artifacts"]) == {"safety_sentinel", "paper_tournament"}
    assert all("sha256" in binding for binding in decision_payload["artifacts"].values())
    report = shadow_trial.build_shadow_streak_report()
    assert report["phase"] == "readiness_no_go"


def test_red_clean_hold_and_zero_submission_are_valid_only_with_complete_bound_evidence(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    start = _start(monkeypatch, date="2026-08-21")
    decision = _day(tmp_path, monkeypatch, start, date="2026-08-21")
    payload = _payload(decision)
    assert payload["status"] == "clean"
    assert payload["phase"] == "qualification_clean"
    assert payload["artifacts"]["paper_tournament"]["payload"]["submitted_count"] == 0


def test_red_full_ledger_replay_requires_repair_then_fresh_qualification_and_five_days(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    qualification_start = _start(monkeypatch, date="2026-08-14")
    qualification = _day(tmp_path, monkeypatch, qualification_start, date="2026-08-14")
    failed_start = _start(monkeypatch, date="2026-08-17", predecessor_object_id=qualification.envelope.object_id)
    failed = _day(tmp_path, monkeypatch, failed_start, date="2026-08-17", artifacts={"safety_sentinel": tmp_path / "missing", "paper_tournament": tmp_path / "missing-paper"})
    assert _payload(failed)["phase"] == "repair_required"
    repair_start = _start(monkeypatch, date="2026-08-18", predecessor_object_id=failed.envelope.object_id)
    repair = _day(tmp_path, monkeypatch, repair_start, date="2026-08-18")
    assert _payload(repair)["phase"] == "repair_in_progress"
    requalification_start = _start(monkeypatch, date="2026-08-19", predecessor_object_id=repair.envelope.object_id)
    previous = _day(tmp_path, monkeypatch, requalification_start, date="2026-08-19")
    assert _payload(previous)["phase"] == "qualification_clean"
    for date in ("2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25", "2026-08-26"):
        start = _start(monkeypatch, date=date, predecessor_object_id=previous.envelope.object_id)
        previous = _day(tmp_path, monkeypatch, start, date=date)
    report = shadow_trial.build_shadow_streak_report()
    assert report["phase"] == "readiness_candidate"
    assert report["clean_trial_streak"] == 5
    assert report["record_path"].startswith(str(tmp_path / "results" / "manual_shadow"))


def test_red_cli_predecessor_transitions_allow_trial_repair_and_fresh_qualification(tmp_path, monkeypatch):
    _configure_environment(monkeypatch, tmp_path)
    calendar = _CalendarFake({"2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20"})
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: calendar)
    _set_clock(monkeypatch, "2026-08-17")
    first = runner.invoke(app, ["research", "shadow-day-start", "--run-id", "q", "--market-date", "2026-08-17", "--json-output"])
    assert first.exit_code == 0, first.output
    first_id = json.loads(first.stdout)["object_id"]
    first_start = shadow_trial.load_shadow_record(first_id, expected_kind="manual-shadow-day-start")
    first_day = _day(tmp_path, monkeypatch, type("Admission", (), {"envelope": first_start})(), date="2026-08-17")
    _set_clock(monkeypatch, "2026-08-18")
    missing = runner.invoke(app, ["research", "shadow-day-start", "--run-id", "missing", "--market-date", "2026-08-18"])
    assert missing.exit_code != 0
    invalid = runner.invoke(app, ["research", "shadow-day-start", "--run-id", "bad", "--market-date", "2026-08-18", "--predecessor-object-id", "manual-shadow-day-result-" + "0" * 64])
    assert invalid.exit_code != 0
    trial = runner.invoke(app, ["research", "shadow-day-start", "--run-id", "trial", "--market-date", "2026-08-18", "--predecessor-object-id", first_day.envelope.object_id, "--json-output"])
    assert trial.exit_code == 0, trial.output
    failed_start = shadow_trial.load_shadow_record(json.loads(trial.stdout)["object_id"], expected_kind="manual-shadow-day-start")
    failed = _day(tmp_path, monkeypatch, type("Admission", (), {"envelope": failed_start})(), date="2026-08-18", artifacts={"safety_sentinel": tmp_path / "missing", "paper_tournament": tmp_path / "missing-paper"})
    _set_clock(monkeypatch, "2026-08-19")
    repair = runner.invoke(app, ["research", "shadow-day-start", "--run-id", "repair", "--market-date", "2026-08-19", "--predecessor-object-id", failed.envelope.object_id, "--json-output"])
    assert repair.exit_code == 0, repair.output
    repair_start = shadow_trial.load_shadow_record(json.loads(repair.stdout)["object_id"], expected_kind="manual-shadow-day-start")
    repair_day = _day(tmp_path, monkeypatch, type("Admission", (), {"envelope": repair_start})(), date="2026-08-19")
    _set_clock(monkeypatch, "2026-08-20")
    requalification = runner.invoke(app, ["research", "shadow-day-start", "--run-id", "q2", "--market-date", "2026-08-20", "--predecessor-object-id", repair_day.envelope.object_id, "--json-output"])
    assert requalification.exit_code == 0, requalification.output
    assert json.loads(requalification.stdout)["role"] == "qualification"
