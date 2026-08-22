from __future__ import annotations

import datetime as dt
import hashlib
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


def _calendar(date: str, *, observed_at: str | None = None, dates: list[str] | None = None) -> dict:
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
        (REPO_ROOT / "config" / "automation_schedule_contract.json").read_text(encoding="utf-8")
    )
    roles_payload = json.loads((REPO_ROOT / "config" / "automation_roles.json").read_text(encoding="utf-8"))
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


def _configure_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> Path:
    output_root = root / "results" / "manual_shadow"
    monkeypatch.setattr(shadow_trial, "_manual_shadow_root", lambda: output_root)
    return output_root


def _start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    date: str = "2026-08-21",
    phase: str = "qualification_pending",
    predecessor_path: Path | None = None,
    frozen: bool = True,
    malformed_control: bool = False,
    active_id: str | None = None,
    omit_id: str | None = None,
) -> tuple[dict, Path]:
    _set_clock(monkeypatch, date)
    contract, roles, automation_root = _write_schedule_fixture(
        tmp_path / "schedule", active_id=active_id, omit_id=omit_id
    )
    control = _control(
        tmp_path / "policy" / "live-control.json",
        frozen=frozen,
        malformed=malformed_control,
    )
    record = shadow_trial.create_shadow_day_start_manifest(
        run_id=f"run-{date}-{phase}",
        ledger_id="ledger-a",
        market_date=date,
        live_control_path=control,
        schedule_contract_path=contract,
        automation_root=automation_root,
        role_contract_path=roles,
        calendar_evidence=_calendar(date),
        phase=phase,
        predecessor_path=predecessor_path,
    )
    return record, shadow_trial.write_shadow_trial_packet(record)


def _artifacts(
    tmp_path: Path,
    *,
    run_id: str,
    date: str,
    submitted_count: object = 0,
    sentinel_status: str = "HOLD",
) -> dict[str, Path]:
    sentinel = tmp_path / "artifacts" / "sentinel.json"
    paper = tmp_path / "artifacts" / "paper.json"
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
            "submitted": [] if submitted_count == 0 else ["not-a-real-order"],
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        },
    )
    return {"safety_sentinel": sentinel, "paper_tournament": paper}


def _adjudicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    start_path: Path,
    start: dict,
    *,
    date: str,
) -> tuple[dict, Path]:
    _set_clock(monkeypatch, date, 16)
    record = shadow_trial.adjudicate_shadow_day(
        start_manifest_path=start_path,
        artifacts=_artifacts(tmp_path, run_id=start["run_id"], date=date),
        calendar_evidence=_calendar(date, observed_at=f"{date}T15:59:00+00:00"),
    )
    return record, shadow_trial.write_shadow_trial_packet(record)


def test_red_production_cli_has_no_time_or_output_override_and_uses_only_calendar_fake(
    tmp_path,
    monkeypatch,
):
    output_root = _configure_root(monkeypatch, tmp_path)
    _set_clock(monkeypatch, "2026-08-21")
    contract, roles, automation_root = _write_schedule_fixture(tmp_path / "schedule")
    control = _control(tmp_path / "policy" / "live-control.json")
    calendar = _CalendarFake({"2026-08-21"})
    monkeypatch.setattr(cli_main, "_alpaca_live_client", lambda: calendar)
    monkeypatch.setattr(shadow_trial, "_default_schedule_contract_path", lambda: contract)
    monkeypatch.setattr(shadow_trial, "_default_role_contract_path", lambda: roles)
    monkeypatch.setattr(shadow_trial, "default_automation_root", lambda: automation_root)

    help_result = runner.invoke(app, ["research", "shadow-day-start", "--help"])
    assert help_result.exit_code == 0
    assert "--now" not in help_result.output
    assert "--output-dir" not in help_result.output

    result = runner.invoke(
        app,
        [
            "research", "shadow-day-start", "--run-id", "cli-run", "--ledger-id", "ledger-a",
            "--market-date", "2026-08-21", "--live-control-path", str(control), "--json-output",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calendar.calls == [("2026-08-21", "2026-08-21")]
    assert Path(json.loads(result.stdout)["manifest_path"]).parent == output_root


def test_red_rejects_forged_replayed_missing_digest_cross_parent_and_root_escape(tmp_path, monkeypatch):
    output_root = _configure_root(monkeypatch, tmp_path)
    start, start_path = _start(tmp_path, monkeypatch)
    raw = json.loads(start_path.read_text(encoding="utf-8"))
    raw.pop("payload_sha256")
    forged = output_root / "shadow-day-start-forged.json"
    _write_json(forged, raw)
    with pytest.raises(ValueError, match="sealed"):
        shadow_trial.load_shadow_record(forged, expected_kind="shadow_day_start")

    external = tmp_path / "outside.json"
    _write_json(external, start)
    with pytest.raises(ValueError, match="root"):
        shadow_trial.load_shadow_record(external, expected_kind="shadow_day_start")

    decision, decision_path = _adjudicate(tmp_path, monkeypatch, start_path, start, date="2026-08-21")
    replay = dict(decision)
    replay["start_manifest_sha256"] = "0" * 64
    replay["payload_sha256"] = shadow_trial.canonical_json_sha256(
        {key: value for key, value in replay.items() if key != "payload_sha256"}
    )
    replay_path = output_root / f"shadow-day-adjudication-{replay['record_id']}.json"
    _write_json(replay_path, replay)
    with pytest.raises(ValueError, match="immutable"):
        shadow_trial.load_shadow_record(replay_path, expected_kind="shadow_day_adjudication")
    assert decision_path.exists()


@pytest.mark.parametrize("frozen,malformed", [(False, False), (True, True)])
def test_red_unfrozen_or_malformed_control_can_never_be_clean(tmp_path, monkeypatch, frozen, malformed):
    _configure_root(monkeypatch, tmp_path)
    start, start_path = _start(tmp_path, monkeypatch, frozen=frozen, malformed_control=malformed)
    decision, _ = _adjudicate(tmp_path, monkeypatch, start_path, start, date="2026-08-21")
    assert decision["status"] != "clean"
    assert "live_control" in " ".join(decision["reasons"])


@pytest.mark.parametrize(
    "active_id,omit_id",
    [("tradingagents-market-supervisor", None), (None, "tradingagents-market-supervisor")],
)
def test_red_automation_roster_requires_exact_ten_paused_contract_rows(
    tmp_path,
    monkeypatch,
    active_id,
    omit_id,
):
    _configure_root(monkeypatch, tmp_path)
    start, start_path = _start(tmp_path, monkeypatch, active_id=active_id, omit_id=omit_id)
    decision, _ = _adjudicate(tmp_path, monkeypatch, start_path, start, date="2026-08-21")
    assert decision["status"] != "clean"
    assert "schedule" in " ".join(decision["reasons"])


def test_red_calendar_is_mandatory_and_rejects_holiday_future_and_old_date(tmp_path, monkeypatch):
    _configure_root(monkeypatch, tmp_path)
    _set_clock(monkeypatch, "2026-08-21")
    contract, roles, automation_root = _write_schedule_fixture(tmp_path / "schedule")
    control = _control(tmp_path / "policy" / "live-control.json")
    unavailable = shadow_trial.create_shadow_day_start_manifest(
        run_id="run-unavailable", ledger_id="ledger-a", market_date="2026-08-21", live_control_path=control,
        schedule_contract_path=contract, automation_root=automation_root, role_contract_path=roles,
        calendar_evidence={"kind": "alpaca_regular_equities_calendar", "market_date": "2026-08-21", "observed_at": "2026-08-21T13:59:00+00:00", "sessions": []},
    )
    unavailable_path = shadow_trial.write_shadow_trial_packet(unavailable)
    decision, _ = _adjudicate(tmp_path / "unavailable", monkeypatch, unavailable_path, unavailable, date="2026-08-21")
    assert decision["status"] != "clean"
    assert "calendar" in " ".join(decision["reasons"])

    with pytest.raises(ValueError, match="current Central date"):
        shadow_trial.create_shadow_day_start_manifest(
            run_id="run-old", ledger_id="ledger-a", market_date="2026-08-20", live_control_path=control,
            schedule_contract_path=contract, automation_root=automation_root, role_contract_path=roles,
            calendar_evidence=_calendar("2026-08-20"),
        )

    _set_clock(monkeypatch, "2026-08-21")
    future = _calendar("2026-08-21", observed_at="2026-08-21T14:00:01+00:00")
    future_record = shadow_trial.create_shadow_day_start_manifest(
        run_id="run-future", ledger_id="ledger-a", market_date="2026-08-21", live_control_path=control,
        schedule_contract_path=contract, automation_root=automation_root, role_contract_path=roles,
        calendar_evidence=future,
    )
    assert future_record["start_gates"]["calendar"] == "fail"


def test_red_regular_file_root_and_bool_submission_count_are_fail_closed(tmp_path, monkeypatch):
    output_root = _configure_root(monkeypatch, tmp_path)
    start, start_path = _start(tmp_path, monkeypatch)
    artifacts = _artifacts(tmp_path, run_id=start["run_id"], date="2026-08-21", submitted_count=False)
    _set_clock(monkeypatch, "2026-08-21", 16)
    decision = shadow_trial.adjudicate_shadow_day(
        start_manifest_path=start_path,
        artifacts=artifacts,
        calendar_evidence=_calendar("2026-08-21", observed_at="2026-08-21T15:59:00+00:00"),
    )
    assert decision["status"] != "clean"
    assert "submission_count" in " ".join(decision["reasons"])

    output_root = _configure_root(monkeypatch, tmp_path / "symlink-root")
    escaped = tmp_path / "escaped"
    escaped.mkdir()
    output_root.parent.mkdir(parents=True, exist_ok=True)
    output_root.symlink_to(escaped, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        shadow_trial.write_shadow_trial_packet(start)


def test_red_repair_requires_fresh_qualification_then_exactly_five_chained_trial_days(tmp_path, monkeypatch):
    _configure_root(monkeypatch, tmp_path)
    qualification, qualification_start = _start(tmp_path / "q1", monkeypatch, date="2026-08-14")
    _, qualification_path = _adjudicate(tmp_path / "q1", monkeypatch, qualification_start, qualification, date="2026-08-14")

    failed_start, failed_start_path = _start(
        tmp_path / "failed", monkeypatch, date="2026-08-17", phase="five_day_trial", predecessor_path=qualification_path
    )
    _set_clock(monkeypatch, "2026-08-17", 16)
    failed = shadow_trial.adjudicate_shadow_day(
        start_manifest_path=failed_start_path,
        artifacts={"safety_sentinel": tmp_path / "missing.json", "paper_tournament": tmp_path / "missing-paper.json"},
        calendar_evidence=_calendar("2026-08-17", observed_at="2026-08-17T15:59:00+00:00"),
    )
    failed_path = shadow_trial.write_shadow_trial_packet(failed)
    assert failed["phase"] == "repair_required"

    repair_start, repair_start_path = _start(
        tmp_path / "repair", monkeypatch, date="2026-08-18", phase="repair_in_progress", predecessor_path=failed_path
    )
    _, repair_path = _adjudicate(tmp_path / "repair", monkeypatch, repair_start_path, repair_start, date="2026-08-18")

    requalification, requalification_start = _start(
        tmp_path / "q2", monkeypatch, date="2026-08-19", predecessor_path=repair_path
    )
    requalification_day, requalification_path = _adjudicate(
        tmp_path / "q2", monkeypatch, requalification_start, requalification, date="2026-08-19"
    )
    day_paths = [qualification_path, failed_path, repair_path, requalification_path]
    predecessor = requalification_path
    for index, date in enumerate(["2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25", "2026-08-26"], start=1):
        start, start_path = _start(tmp_path / f"trial-{index}", monkeypatch, date=date, phase="five_day_trial", predecessor_path=predecessor)
        _, predecessor = _adjudicate(tmp_path / f"trial-{index}", monkeypatch, start_path, start, date=date)
        day_paths.append(predecessor)

    report = shadow_trial.build_shadow_streak_report(day_paths)
    assert report["phase"] == "readiness_candidate"
    assert report["clean_trial_streak"] == 5
    assert requalification_day["phase"] == "qualification_clean"


def test_red_forged_trial_history_and_failed_trial_reset_stay_no_go(tmp_path, monkeypatch):
    _configure_root(monkeypatch, tmp_path)
    qualification, qualification_start = _start(tmp_path / "q", monkeypatch, date="2026-08-17")
    _, qualification_path = _adjudicate(tmp_path / "q", monkeypatch, qualification_start, qualification, date="2026-08-17")
    start, start_path = _start(tmp_path / "trial", monkeypatch, date="2026-08-18", phase="five_day_trial", predecessor_path=qualification_path)
    _set_clock(monkeypatch, "2026-08-18", 16)
    failed = shadow_trial.adjudicate_shadow_day(
        start_manifest_path=start_path,
        artifacts={"safety_sentinel": tmp_path / "missing", "paper_tournament": tmp_path / "missing-paper"},
        calendar_evidence=_calendar("2026-08-18", observed_at="2026-08-18T15:59:00+00:00"),
    )
    failed_path = shadow_trial.write_shadow_trial_packet(failed)
    report = shadow_trial.build_shadow_streak_report([qualification_path, failed_path])
    assert report["phase"] == "readiness_no_go"
    assert report["clean_trial_streak"] == 0
