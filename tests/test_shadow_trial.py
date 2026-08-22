import datetime as dt
import json
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.evals.shadow_trial import (
    adjudicate_shadow_day,
    build_shadow_streak_report,
    create_shadow_day_start_manifest,
)

UTC = dt.timezone.utc
runner = CliRunner()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _start(tmp_path: Path, *, market_date: str = "2026-08-21", phase: str = "qualification_pending") -> dict:
    control = tmp_path / "policy" / "live_control.json"
    automation = tmp_path / "automation.json"
    _write_json(control, {"frozen": True, "reason": "manual observer hold"})
    _write_json(
        automation,
        {
            "generated_at": f"{market_date}T13:00:00+00:00",
            "automations": [{"automation_id": "observer", "status": "PAUSED"}],
        },
    )
    return create_shadow_day_start_manifest(
        run_id=f"run-{market_date}",
        market_date=market_date,
        live_control_path=control,
        automation_evidence_path=automation,
        phase=phase,
        now=dt.datetime.fromisoformat(f"{market_date}T14:00:00+00:00"),
    )


def _artifacts(tmp_path: Path, *, run_id: str, market_date: str, sentinel_status: str = "HOLD") -> dict[str, Path]:
    sentinel = tmp_path / "sentinel.json"
    paper = tmp_path / "paper.json"
    generated_at = f"{market_date}T15:00:00+00:00"
    _write_json(
        sentinel,
        {
            "kind": "safety_sentinel_audit",
            "run_id": run_id,
            "market_date": market_date,
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
            "market_date": market_date,
            "generated_at": generated_at,
            "status": "HOLD",
            "dry_run": True,
            "submitted_count": 0,
            "submitted": [],
            "analysis_only": True,
            "execution_authority": "none",
            "can_submit_orders": False,
        },
    )
    return {"safety_sentinel": sentinel, "paper_tournament": paper}


def _adjudicate(tmp_path: Path, *, market_date: str = "2026-08-21", phase: str = "qualification_pending") -> dict:
    start = _start(tmp_path, market_date=market_date, phase=phase)
    return adjudicate_shadow_day(
        start,
        _artifacts(tmp_path, run_id=start["run_id"], market_date=market_date),
        now=dt.datetime.fromisoformat(f"{market_date}T16:00:00+00:00"),
    )


def test_valid_non_authorizing_hold_and_no_paper_signal_is_a_clean_qualification(tmp_path):
    result = _adjudicate(tmp_path)

    assert result["status"] == "clean"
    assert result["phase"] == "qualification_clean"
    assert result["analysis_only"] is True
    assert result["execution_authority"] == "none"
    assert result["can_submit_orders"] is False
    assert all(gate["status"] == "pass" for gate in result["gates"])
    assert result["artifacts"]["paper_tournament"]["sha256"]


def test_adjudication_rejects_unknown_missing_stale_cross_run_and_mutated_evidence(tmp_path):
    start = _start(tmp_path)
    artifacts = _artifacts(tmp_path, run_id=start["run_id"], market_date=start["market_date"])
    unknown = adjudicate_shadow_day(start, {**artifacts, "extra": tmp_path / "extra.json"})
    assert unknown["status"] == "incomplete"
    assert "unknown_artifact_keys" in unknown["reasons"]

    missing = adjudicate_shadow_day(start, {"safety_sentinel": artifacts["safety_sentinel"]})
    assert missing["status"] == "incomplete"
    assert "missing_artifact_keys" in missing["reasons"]

    paper_payload = json.loads(artifacts["paper_tournament"].read_text(encoding="utf-8"))
    paper_payload["run_id"] = "other-run"
    _write_json(artifacts["paper_tournament"], paper_payload)
    cross_run = adjudicate_shadow_day(start, artifacts)
    assert cross_run["status"] == "failed"
    assert "paper_tournament_cross_run" in cross_run["reasons"]

    stale = _artifacts(tmp_path / "stale", run_id=start["run_id"], market_date=start["market_date"])
    stale_payload = json.loads(stale["safety_sentinel"].read_text(encoding="utf-8"))
    stale_payload["generated_at"] = "2026-08-21T14:01:00+00:00"
    _write_json(stale["safety_sentinel"], stale_payload)
    stale_result = adjudicate_shadow_day(start, stale, now=dt.datetime(2026, 8, 21, 16, tzinfo=UTC))
    assert stale_result["status"] == "incomplete"
    assert "safety_sentinel_stale" in stale_result["reasons"]

    bound_start = _start(tmp_path / "bound")
    bound_artifacts = _artifacts(
        tmp_path / "bound",
        run_id=bound_start["run_id"],
        market_date=bound_start["market_date"],
    )
    bound_start["artifact_bindings"] = {
        key: {"path": str(path.resolve()), "sha256": "0" * 64, "size_bytes": path.stat().st_size}
        for key, path in bound_artifacts.items()
    }
    mutated = adjudicate_shadow_day(bound_start, bound_artifacts)
    assert mutated["status"] == "failed"
    assert "safety_sentinel_hash_changed" in mutated["reasons"]


def test_adjudication_rejects_unpaused_automation_and_live_control_hash_change(tmp_path):
    initially_unpaused_start = _start(tmp_path / "initially-unpaused")
    initially_unpaused_path = Path(
        initially_unpaused_start["start_state"]["automation_evidence"]["path"]
    )
    _write_json(
        initially_unpaused_path,
        {"automations": [{"automation_id": "observer", "status": "ACTIVE"}]},
    )
    initially_unpaused = adjudicate_shadow_day(
        initially_unpaused_start,
        _artifacts(
            tmp_path / "initially-unpaused",
            run_id=initially_unpaused_start["run_id"],
            market_date=initially_unpaused_start["market_date"],
        ),
    )
    assert "automation_unpaused" in initially_unpaused["reasons"]

    start = _start(tmp_path)
    automation_path = Path(start["start_state"]["automation_evidence"]["path"])
    _write_json(automation_path, {"automations": [{"automation_id": "observer", "status": "ACTIVE"}]})
    unpaused = adjudicate_shadow_day(
        start,
        _artifacts(tmp_path, run_id=start["run_id"], market_date=start["market_date"]),
    )
    assert unpaused["status"] == "failed"
    assert "automation_evidence_hash_changed" in unpaused["reasons"]

    control_start = _start(tmp_path / "control")
    control_path = Path(control_start["start_state"]["live_control"]["path"])
    _write_json(control_path, {"frozen": False})
    changed = adjudicate_shadow_day(
        control_start,
        _artifacts(tmp_path / "control", run_id=control_start["run_id"], market_date=control_start["market_date"]),
    )
    assert changed["status"] == "failed"
    assert "live_control_hash_changed" in changed["reasons"]


def test_streak_rejects_duplicate_nonmarket_and_resets_after_failed_day(tmp_path):
    qualification = _adjudicate(tmp_path / "q")
    duplicate = {**qualification, "role": "trial", "market_date": qualification["market_date"]}
    duplicate_report = build_shadow_streak_report([qualification, duplicate], now=dt.datetime(2026, 8, 21, 20, tzinfo=UTC))
    assert duplicate_report["phase"] == "readiness_no_go"
    assert "duplicate_market_date" in duplicate_report["reasons"]

    weekend = {**qualification, "market_date": "2026-08-22", "generated_at": "2026-08-22T16:00:00+00:00"}
    nonmarket_report = build_shadow_streak_report([weekend], now=dt.datetime(2026, 8, 22, 20, tzinfo=UTC))
    assert "nonmarket_date" in nonmarket_report["reasons"]

    failed = {**qualification, "role": "trial", "market_date": "2026-08-24", "status": "failed"}
    reset = build_shadow_streak_report([qualification, failed], now=dt.datetime(2026, 8, 24, 20, tzinfo=UTC))
    assert reset["clean_trial_streak"] == 0
    assert reset["phase"] == "readiness_no_go"


def test_five_distinct_clean_market_days_after_qualification_are_a_candidate(tmp_path):
    days = ["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24"]
    qualification = _adjudicate(tmp_path / "q", market_date=days[0])
    records = [qualification]
    for index, market_date in enumerate(days[1:], start=1):
        trial = _adjudicate(tmp_path / f"trial-{index}", market_date=market_date, phase="five_day_trial")
        trial["role"] = "trial"
        records.append(trial)

    report = build_shadow_streak_report(records, now=dt.datetime(2026, 8, 24, 20, tzinfo=UTC))

    assert report["clean_trial_streak"] == 5
    assert report["phase"] == "readiness_candidate"
    assert "trial_complete" in report["phase_history"]
    assert report["can_submit_orders"] is False


def test_cli_commands_use_tmp_output_only_and_never_invoke_runtime_clients(tmp_path):
    control = tmp_path / "live-control.json"
    automation = tmp_path / "automation.json"
    _write_json(control, {"frozen": True})
    _write_json(automation, {"automations": [{"automation_id": "observer", "status": "PAUSED"}]})
    output = tmp_path / "manual-shadow"

    started = runner.invoke(
        app,
        [
            "research", "shadow-day-start", "--run-id", "cli-run", "--market-date", "2026-08-21",
            "--live-control-path", str(control), "--automation-evidence-path", str(automation),
            "--output-dir", str(output), "--now", "2026-08-21T14:00:00+00:00", "--json-output",
        ],
    )
    assert started.exit_code == 0, started.output
    manifest_path = Path(json.loads(started.stdout)["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["analysis_only"] is True
    artifacts = _artifacts(tmp_path, run_id="cli-run", market_date="2026-08-21")
    adjudicated = runner.invoke(
        app,
        [
            "research", "shadow-day-adjudicate", "--start-manifest", str(manifest_path),
            "--safety-sentinel", str(artifacts["safety_sentinel"]),
            "--paper-tournament", str(artifacts["paper_tournament"]), "--output-dir", str(output),
            "--now", "2026-08-21T16:00:00+00:00", "--json-output",
        ],
    )
    assert adjudicated.exit_code == 0, adjudicated.output
    assert json.loads(adjudicated.stdout)["status"] == "clean"
    assert all(path.parent == output for path in output.glob("*.json"))
