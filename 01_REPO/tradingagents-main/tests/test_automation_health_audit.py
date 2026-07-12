import datetime as dt
import json
import os
from pathlib import Path

from tradingagents.evals.automation_health_audit import (
    _collect_run_ids,
    _run_id_for_path,
    build_automation_health_audit,
    build_compact_automation_health_audit,
    write_automation_health_audit,
)

UTC = dt.timezone.utc


def _write_automation(
    root: Path,
    automation_id: str,
    *,
    rrule: str,
    status: str = "ACTIVE",
    updated_at: int | str | None = None,
) -> None:
    path = root / automation_id
    path.mkdir(parents=True)
    lines = [
        "version = 1",
        f'id = "{automation_id}"',
        'kind = "cron"',
        f'name = "{automation_id}"',
        'prompt = "TradingAgents test automation"',
        f'status = "{status}"',
        f'rrule = "{rrule}"',
        'cwds = ["C:\\\\Users\\\\Corbin\\\\Documents\\\\Coding projects\\\\TradingAgents-main"]',
    ]
    if isinstance(updated_at, int):
        lines.append(f"updated_at = {updated_at}")
    elif isinstance(updated_at, str):
        lines.append(f'updated_at = "{updated_at}"')
    (path / "automation.toml").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _write_packet(path: Path, generated_at: str, **payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"generated_at": generated_at, **payload}
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_memory(root: Path, automation_id: str, text: str) -> None:
    path = root / automation_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "memory.md").write_text(text, encoding="utf-8")


def test_automation_health_run_id_inference_preserves_microsecond_packets():
    assert (
        _run_id_for_path(Path("results/hourly_supervisor/hourly-supervisor-20260601-010550-274605.json"))
        == "20260601-010550-274605"
    )
    assert (
        _run_id_for_path(Path("results/capability_audits/capability-audit-20260604-124807-557636.json"))
        == "20260604-124807-557636"
    )
    assert _run_id_for_path(Path("results/hourly_supervisor/latest.json")) is None
    assert _run_id_for_path(Path("results/example/custom-artifact-name.json")) == "custom-artifact-name"

    run_ids = _collect_run_ids(
        [
            {"path": "results/hourly_supervisor/latest.json"},
            {"path": "results/hourly_supervisor/hourly-supervisor-20260601-010550-274605.json"},
            {"path": "results/hourly_supervisor/hourly-supervisor-20260601-010550-999999.json"},
            {"run_id": "explicit-packet-id", "path": "results/hourly_supervisor/latest.json"},
        ]
    )

    assert run_ids == [
        "20260601-010550-274605",
        "20260601-010550-999999",
        "explicit-packet-id",
    ]


def test_automation_health_audit_flags_missing_partial_duplicate_and_stale_runs(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 14, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "hourly-market-supervisor",
        rrule="RRULE:FREQ=HOURLY;INTERVAL=1;BYMINUTE=0;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_automation(
        automation_root,
        "paper-strategy-tournament-runner",
        rrule="RRULE:FREQ=HOURLY;INTERVAL=1;BYMINUTE=5;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_automation(
        automation_root,
        "tradingagents-automation-wake-controller",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=6;BYMINUTE=45;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_automation(
        automation_root,
        "tradingagents-self-heal-monitor",
        rrule="RRULE:FREQ=HOURLY;INTERVAL=1;BYMINUTE=30;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )

    _write_packet(
        repo / "results/hourly_supervisor/hourly-supervisor-20260603-130000.json",
        "2026-06-03T13:00:00+00:00",
        decision="hold",
        submitted=[],
        issues=[],
    )
    _write_packet(
        repo / "results/self_heal/self-heal-handoff-20260603-123000.json",
        "2026-06-03T12:30:00+00:00",
        should_start_new_chat=False,
    )
    _write_packet(
        repo / "results/self_heal/self-heal-handoff-20260603-123001.json",
        "2026-06-03T12:30:01+00:00",
        should_start_new_chat=False,
    )
    (automation_root / "tradingagents-automation-wake-controller" / "memory.md").write_text(
        "2026-06-02 wake controller toggled jobs.\n",
        encoding="utf-8",
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )

    by_id = {item["automation_id"]: item for item in audit["automations"]}
    assert audit["can_submit_orders"] is False
    assert audit["submitted_order_count"] == 0
    assert by_id["hourly-market-supervisor"]["status"] == "partial"
    assert "missed_run" in by_id["hourly-market-supervisor"]["issue_types"]
    assert by_id["hourly-market-supervisor"]["problem_jobs"]
    assert by_id["hourly-market-supervisor"]["problem_jobs"][0]["job"] == "partial run"
    assert "runs observed" in by_id["hourly-market-supervisor"]["problem_jobs"][0]["actual_status"]

    assert by_id["paper-strategy-tournament-runner"]["status"] == "missing"
    assert by_id["paper-strategy-tournament-runner"]["problem_jobs"][0]["job"] == "missed run"
    assert by_id["paper-strategy-tournament-runner"]["problem_jobs"][0]["expected_time"] != "-"
    assert by_id["tradingagents-automation-wake-controller"]["status"] == "stale"
    assert by_id["tradingagents-self-heal-monitor"]["status"] == "duplicate"
    assert by_id["tradingagents-self-heal-monitor"]["problem_jobs"][0]["job"] == "duplicate run"
    assert audit["summary"]["missing_count"] >= 1
    assert audit["summary"]["partial_count"] >= 1
    assert audit["summary"]["duplicate_count"] >= 1


def test_paused_automation_does_not_flag_manual_packets_as_duplicate_runs(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 14, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "hourly-market-supervisor",
        rrule="RRULE:FREQ=HOURLY;INTERVAL=1;BYMINUTE=0;BYDAY=SU,MO,TU,WE,TH,FR,SA",
        status="PAUSED",
    )
    _write_packet(
        repo / "results/hourly_supervisor/hourly-supervisor-20260603-130000.json",
        "2026-06-03T13:00:00+00:00",
        decision="hold",
        submitted=[],
        issues=[],
    )
    _write_packet(
        repo / "results/hourly_supervisor/hourly-supervisor-20260603-130030.json",
        "2026-06-03T13:00:30+00:00",
        decision="hold",
        submitted=[],
        issues=[],
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["hourly-market-supervisor"]

    assert row["config_status"] == "PAUSED"
    assert row["expected_run_count"] == 0
    assert row["actual_artifact_count"] == 2
    assert row["duplicate_count"] == 0
    assert row["overlap_count"] == 0
    assert row["status"] == "ok"
    assert row["status_reason"] == "automation_paused"
    assert "duplicate_run" not in row["issue_types"]


def test_automation_health_tracks_wake_verification_patrol_packet(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 13, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-wake-verification",
        rrule="FREQ=DAILY;COUNT=1;BYHOUR=6;BYMINUTE=55",
    )
    _write_packet(
        repo / "results/control_plane_patrol/wake-verification-patrol-20260603-115500.json",
        "2026-06-03T11:55:00+00:00",
        kind="tradingagents_control_plane_patrol",
        automation_id="tradingagents-wake-verification",
        analysis_only=True,
        can_submit_orders=False,
        submitted_count=0,
        issue_count=0,
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )

    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-wake-verification"]

    assert row["status"] == "ok"
    assert row["actual_artifact_count"] == 1
    assert row["submitted_order_count"] == 0
    assert row["issue_count"] == 0
    assert row["packet_paths"] == [
        str(repo / "results/control_plane_patrol/wake-verification-patrol-20260603-115500.json")
    ]


def test_real_simulation_artifacts_do_not_count_as_scheduler_duplicates(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 14, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "paper-strategy-tournament-runner",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=13;BYMINUTE=5;BYDAY=WE",
    )
    scheduled_packet = repo / "results/paper_strategy_tournament/paper-tournament-run-20260603-130500.json"
    audit_packet = repo / "results/paper_strategy_tournament/paper-tournament-run-20260603-130530.json"
    _write_packet(
        scheduled_packet,
        "2026-06-03T13:05:00+00:00",
        dry_run=True,
        submitted=[],
        issues=[],
    )
    _write_packet(
        audit_packet,
        "2026-06-03T13:05:30+00:00",
        dry_run=True,
        submitted=[],
        issues=[],
    )
    _write_packet(
        repo / "results/real_simulation_audits/real-simulation-audit-20260603-131000.json",
        "2026-06-03T13:10:00+00:00",
        commands=[
            {
                "name": "paper_tournament_dry_run",
                "packet_paths": [
                    "results/paper_strategy_tournament/paper-tournament-run-20260603-130530.json"
                ],
            }
        ],
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["paper-strategy-tournament-runner"]

    assert row["actual_artifact_count"] == 1
    assert row["observer_artifact_count"] == 1
    assert row["duplicate_count"] == 0
    assert row["status"] == "ok"
    assert "duplicate_run" not in row["issue_types"]


def test_hourly_no_action_duplicate_is_de_noised_when_memory_covers_latest_packet(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 14, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "hourly-market-supervisor",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=13;BYMINUTE=0;BYDAY=WE",
    )
    _write_memory(
        automation_root,
        "hourly-market-supervisor",
        "2026-06-03T13:02:00 hourly supervisor completed and emailed no critical alert.\n",
    )
    _write_packet(
        repo / "results/hourly_supervisor/hourly-supervisor-20260603-130000-100000.json",
        "2026-06-03T13:00:00+00:00",
        decision="loss-review",
        submitted=[],
        issues=[],
    )
    _write_packet(
        repo / "results/hourly_supervisor/hourly-supervisor-20260603-130041-200000.json",
        "2026-06-03T13:00:41+00:00",
        decision="loss-review",
        submitted=[],
        issues=[],
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["hourly-market-supervisor"]

    assert row["duplicate_count"] == 1
    assert row["status"] == "ok"
    assert row["status_reason"] == "hourly_no_action_duplicate_artifacts_de_noised"
    assert "duplicate_run" not in row["issue_types"]


def test_hourly_duplicate_with_submission_stays_degraded(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 14, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "hourly-market-supervisor",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=13;BYMINUTE=0;BYDAY=WE",
    )
    _write_memory(
        automation_root,
        "hourly-market-supervisor",
        "2026-06-03T13:02:00 hourly supervisor completed.\n",
    )
    _write_packet(
        repo / "results/hourly_supervisor/hourly-supervisor-20260603-130000-100000.json",
        "2026-06-03T13:00:00+00:00",
        decision="hold",
        submitted=[{"symbol": "MSFT"}],
        issues=[],
    )
    _write_packet(
        repo / "results/hourly_supervisor/hourly-supervisor-20260603-130041-200000.json",
        "2026-06-03T13:00:41+00:00",
        decision="hold",
        submitted=[],
        issues=[],
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["hourly-market-supervisor"]

    assert row["duplicate_count"] == 1
    assert row["status"] == "duplicate"
    assert "duplicate_run" in row["issue_types"]


def test_paper_strategy_watch_and_run_pair_is_one_expected_automation_pass(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 14, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "paper-strategy-tournament-runner",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=13;BYMINUTE=5;BYDAY=WE",
    )
    _write_packet(
        repo / "results/paper_strategy_tournament/alphainsider-paper-watch-20260603-130501.json",
        "2026-06-03T13:05:01+00:00",
        strategy_count=0,
    )
    _write_packet(
        repo / "results/paper_strategy_tournament/paper-tournament-run-20260603-130530.json",
        "2026-06-03T13:05:30+00:00",
        dry_run=True,
        submitted=[],
        issues=[],
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["paper-strategy-tournament-runner"]

    assert row["actual_artifact_count"] == 2
    assert row["duplicate_count"] == 0
    assert row["overlap_count"] == 0
    assert row["status"] == "ok"
    assert "duplicate_run" not in row["issue_types"]


def test_paper_strategy_extra_paper_only_runs_are_visible_but_not_health_duplicates(
    tmp_path,
):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 4, 13, 30, tzinfo=UTC)

    _write_automation(
        automation_root,
        "paper-strategy-tournament-runner",
        rrule="RRULE:FREQ=HOURLY;INTERVAL=1;BYMINUTE=5;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_packet(
        repo / "results/paper_strategy_tournament/alphainsider-paper-watch-20260604-125017.json",
        "2026-06-04T12:50:17+00:00",
        paper_only=True,
        analysis_only=True,
        execution_authority="none",
    )
    _write_packet(
        repo / "results/paper_strategy_tournament/paper-tournament-run-20260604-125025.json",
        "2026-06-04T12:50:25+00:00",
        submitted=[],
        issues=[],
        submitted_count=0,
    )
    _write_packet(
        repo / "results/paper_strategy_tournament/alphainsider-paper-watch-20260604-130905.json",
        "2026-06-04T13:09:05+00:00",
        paper_only=True,
        analysis_only=True,
        execution_authority="none",
    )
    _write_packet(
        repo / "results/paper_strategy_tournament/paper-tournament-run-20260604-130914.json",
        "2026-06-04T13:09:14+00:00",
        submitted=[],
        issues=[],
        submitted_count=0,
    )
    _write_memory(
        automation_root,
        "paper-strategy-tournament-runner",
        "## 2026-06-04T13:09:39+00:00\n\nCompleted paper-only run.\n",
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=1,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["paper-strategy-tournament-runner"]

    assert row["expected_run_count"] == 1
    assert row["actual_artifact_count"] == 4
    assert row["status"] == "ok"
    assert row["status_reason"] == "paper_only_duplicate_artifacts_de_noised"
    assert "duplicate_run" not in row["issue_types"]
    assert row["problem_jobs"] == []
    assert audit["summary"]["duplicate_count"] == 0


def test_overnight_analysis_only_complete_reruns_are_visible_but_not_health_duplicates(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 7, 11, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-overnight-planning",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=2;BYMINUTE=30;BYDAY=SU",
        updated_at=int(dt.datetime(2026, 6, 7, 0, 0, tzinfo=UTC).timestamp() * 1000),
    )
    quality = {
        "completion_status": "complete",
        "graph_failure_count": 0,
        "full_graph_success_count": 3,
    }
    for stamp in ("073500", "094509", "101157"):
        _write_packet(
            repo / f"results/overnight_plans/overnight-plan-20260607-{stamp}-000000.json",
            f"2026-06-07T{stamp[:2]}:{stamp[2:4]}:{stamp[4:]}+00:00",
            analysis_only=True,
            trade_date="2026-06-08",
            submitted=[],
            submitted_count=0,
            issue_count=0,
            overnight_quality=quality,
        )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-overnight-planning"]

    assert row["expected_run_count"] == 1
    assert row["actual_artifact_count"] == 3
    assert row["status"] == "ok"
    assert row["status_reason"] == "overnight_analysis_only_duplicate_artifacts_de_noised"
    assert "duplicate_run" not in row["issue_types"]
    assert row["problem_jobs"] == []
    assert audit["summary"]["duplicate_count"] == 0


def test_overnight_superseded_stale_trade_date_repair_reruns_are_de_noised(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 7, 11, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-overnight-planning",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=2;BYMINUTE=30;BYDAY=SU",
        updated_at=int(dt.datetime(2026, 6, 7, 0, 0, tzinfo=UTC).timestamp() * 1000),
    )
    quality = {
        "completion_status": "complete",
        "graph_failure_count": 0,
        "full_graph_success_count": 3,
    }
    for stamp, trade_date in (
        ("074858", "2026-06-05"),
        ("094509", "2026-06-08"),
        ("101157", "2026-06-08"),
    ):
        _write_packet(
            repo / f"results/overnight_plans/overnight-plan-20260607-{stamp}-000000.json",
            f"2026-06-07T{stamp[:2]}:{stamp[2:4]}:{stamp[4:]}+00:00",
            analysis_only=True,
            trade_date=trade_date,
            submitted=[],
            overnight_quality=quality,
        )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-overnight-planning"]

    assert row["expected_run_count"] == 1
    assert row["actual_artifact_count"] == 3
    assert row["status"] == "ok"
    assert row["status_reason"] == "overnight_superseded_stale_repair_reruns_de_noised"
    assert "duplicate_run" not in row["issue_types"]
    assert row["problem_jobs"] == []
    assert audit["summary"]["duplicate_count"] == 0


def test_wake_sleep_controller_window_limits_expected_dependent_runs(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 4, 12, 1, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-automation-sleep-controller",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=16;BYMINUTE=45;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_automation(
        automation_root,
        "tradingagents-automation-wake-controller",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=6;BYMINUTE=45;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_automation(
        automation_root,
        "paper-strategy-tournament-runner",
        rrule="RRULE:FREQ=HOURLY;INTERVAL=1;BYMINUTE=5;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_memory(
        automation_root,
        "tradingagents-automation-sleep-controller",
        "2026-06-03 16:50:52 -05:00 paused hourly and paper runners.\n",
    )
    _write_memory(
        automation_root,
        "tradingagents-automation-wake-controller",
        "Run time: 2026-06-04\nUpdated paper-strategy-tournament-runner to ACTIVE.\n",
    )
    _write_packet(
        repo / "results/paper_strategy_tournament/paper-tournament-run-20260603-181222.json",
        "2026-06-03T18:12:22+00:00",
        dry_run=True,
        submitted=[],
        issues=[],
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["paper-strategy-tournament-runner"]

    assert row["expected_run_count"] == 0
    assert row["actual_artifact_count"] == 0
    assert row["status"] == "ok"
    assert "missed_run" not in row["issue_types"]


def test_overnight_planner_due_is_not_suppressed_by_daytime_wake_sleep_window(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 5, 9, 57, tzinfo=UTC)  # 04:57 America/Chicago.

    _write_automation(
        automation_root,
        "tradingagents-automation-sleep-controller",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=16;BYMINUTE=45;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_automation(
        automation_root,
        "tradingagents-automation-wake-controller",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=6;BYMINUTE=45;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_automation(
        automation_root,
        "tradingagents-overnight-planning",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=2;BYMINUTE=30;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_memory(
        automation_root,
        "tradingagents-automation-sleep-controller",
        "2026-06-04 16:50:52 -05:00 paused hourly and paper runners.\n",
    )
    _write_memory(
        automation_root,
        "tradingagents-automation-wake-controller",
        "Run time: 2026-06-04\nUpdated paper-strategy-tournament-runner to ACTIVE.\n",
    )
    _write_memory(
        automation_root,
        "tradingagents-overnight-planning",
        "2026-06-04T23:44:07 overnight manual verification passed before the scheduled 02:30 run.\n",
    )
    _write_packet(
        repo / "results/overnight_plans/overnight-plan-20260605-040719-000000.json",
        "2026-06-05T04:07:19+00:00",
        analysis_only=True,
        submitted=[],
        overnight_quality={"full_graph_success_count": 3},
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-overnight-planning"]

    assert row["expected_run_count"] == 1
    assert row["actual_artifact_count"] == 0
    assert row["status"] == "missing"
    assert "missed_run" in row["issue_types"]
    assert row["problem_jobs"][0]["expected_time"] == "2026-06-05T07:30:00+00:00"


def test_paused_overnight_planner_does_not_flag_saturday_without_market_morning(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 6, 18, 56, tzinfo=UTC)  # Saturday.

    _write_automation(
        automation_root,
        "tradingagents-overnight-planning",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=2;BYMINUTE=30;BYDAY=SU,MO,TU,WE,TH,FR,SA",
        status="PAUSED",
    )
    _write_memory(
        automation_root,
        "tradingagents-overnight-planning",
        "2026-06-04T23:44:07 overnight verification passed before the prior market session.\n",
    )
    _write_packet(
        repo / "results/overnight_plans/overnight-plan-20260605-101740-000000.json",
        "2026-06-05T10:17:40+00:00",
        analysis_only=True,
        submitted=[],
        overnight_quality={
            "completion_status": "complete",
            "full_graph_success_count": 3,
            "graph_failure_count": 0,
        },
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-overnight-planning"]

    assert row["expected_run_count"] == 0
    assert row["actual_artifact_count"] == 0
    assert row["status"] == "ok"
    assert row["status_reason"] == "automation_paused"
    assert "missed_run" not in row["issue_types"]
    assert row["problem_jobs"] == []


def test_date_only_controller_memory_uses_file_write_time_as_run_evidence(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 5, 10, 30, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-automation-wake-controller",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=6;BYMINUTE=45;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_memory(
        automation_root,
        "tradingagents-automation-wake-controller",
        "Run time: 2026-06-04\nUpdated market-day jobs.\n",
    )
    memory_path = automation_root / "tradingagents-automation-wake-controller" / "memory.md"
    write_time = dt.datetime(2026, 6, 4, 11, 50, tzinfo=UTC).timestamp()
    os.utime(memory_path, (write_time, write_time))

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-automation-wake-controller"]

    assert row["expected_run_count"] == 1
    assert row["status"] == "ok"
    assert "stale_memory" not in row["issue_types"]
    assert row["latest_memory_at"] == "2026-06-04T11:50:00+00:00"


def test_wake_controller_patrol_packet_counts_as_schedule_evidence(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 5, 13, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-automation-wake-controller",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=6;BYMINUTE=45;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_memory(
        automation_root,
        "tradingagents-automation-wake-controller",
        "Run time: 2026-06-03\nUpdated market-day jobs.\n",
    )
    _write_packet(
        repo / "results/control_plane_patrol/wake-controller-patrol-20260605-115500.json",
        "2026-06-05T11:55:00+00:00",
        kind="tradingagents_control_plane_patrol",
        automation_id="tradingagents-automation-wake-controller",
        analysis_only=True,
        can_submit_orders=False,
        execution_authority="none",
        submitted_count=0,
        issue_count=0,
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-automation-wake-controller"]

    assert row["expected_run_count"] == 1
    assert row["actual_artifact_count"] == 1
    assert row["status"] == "ok"
    assert "stale_memory" not in row["issue_types"]
    assert row["packet_paths"] == [
        str(repo / "results/control_plane_patrol/wake-controller-patrol-20260605-115500.json")
    ]


def test_self_heal_monitor_requires_timely_plan_after_actionable_handoff(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 14, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-self-heal-monitor",
        rrule="RRULE:FREQ=HOURLY;INTERVAL=1;BYMINUTE=30;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_packet(
        repo / "results/self_heal/self-heal-handoff-20260603-130000.json",
        "2026-06-03T13:00:00+00:00",
        should_start_new_chat=True,
        trigger_count=1,
        max_severity="high",
    )

    stale_audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
        self_heal_plan_sla_minutes=20,
    )
    stale_row = {
        item["automation_id"]: item for item in stale_audit["automations"]
    }["tradingagents-self-heal-monitor"]

    assert stale_row["status"] == "late"
    assert "self_heal_plan_late" in stale_row["issue_types"]
    assert stale_row["self_heal_timeliness"]["latest_actionable_handoff_at"] == "2026-06-03T13:00:00+00:00"
    assert stale_row["self_heal_timeliness"]["latest_followup_plan_at"] is None
    assert stale_audit["summary"]["late_count"] >= 1
    assert stale_row["problem_jobs"][0]["job"] == "late run"
    assert stale_row["problem_jobs"][0]["expected_time"] == "2026-06-03T13:00:00+00:00"
    assert "follow-up plan status: pending" in stale_row["problem_jobs"][0]["actual_status"]
    assert stale_row["problem_jobs"][0]["evidence_path"]
    assert "Execute or schedule the self-heal follow-up" in stale_row["problem_jobs"][0]["user_action"]

    _write_packet(
        repo / "results/self_heal/plans/self-heal-plan-20260603-131500.json",
        "2026-06-03T13:15:00+00:00",
        status="verified",
        active_plan_count=0,
        executed_count=1,
        verified_count=1,
    )

    timely_audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
        self_heal_plan_sla_minutes=20,
    )
    timely_row = {
        item["automation_id"]: item for item in timely_audit["automations"]
    }["tradingagents-self-heal-monitor"]

    assert timely_row["status"] == "ok"
    assert "self_heal_plan_late" not in timely_row["issue_types"]
    assert timely_row["self_heal_timeliness"]["latest_followup_plan_at"] == "2026-06-03T13:15:00+00:00"
    assert timely_row["self_heal_timeliness"]["followup_lag_seconds"] == 900


def test_self_heal_timeliness_uses_first_followup_plan_not_latest_dedupe(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 16, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-self-heal-monitor",
        rrule="RRULE:FREQ=HOURLY;INTERVAL=1;BYMINUTE=0;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_packet(
        repo / "results/self_heal/self-heal-handoff-20260603-130000.json",
        "2026-06-03T13:00:00+00:00",
        should_start_new_chat=True,
        trigger_count=1,
        max_severity="high",
    )
    _write_packet(
        repo / "results/self_heal/plans/self-heal-plan-20260603-130500.json",
        "2026-06-03T13:05:00+00:00",
        status="verified",
        executed_count=1,
        verified_count=1,
    )
    _write_packet(
        repo / "results/self_heal/plans/self-heal-plan-20260603-154500.json",
        "2026-06-03T15:45:00+00:00",
        status="deduped",
        active_plan_count=0,
        executed_count=0,
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
        self_heal_plan_sla_minutes=30,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-self-heal-monitor"]

    assert row["status"] == "ok"
    assert "self_heal_plan_late" not in row["issue_types"]
    assert "missed_run" not in row["issue_types"]
    assert row["status_reason"] == "self_heal_timely_followup_artifacts_de_noised"
    assert row["self_heal_timeliness"]["latest_followup_plan_at"] == "2026-06-03T13:05:00+00:00"
    assert row["self_heal_timeliness"]["latest_observed_plan_at"] == "2026-06-03T15:45:00+00:00"
    assert row["self_heal_timeliness"]["followup_lag_seconds"] == 300


def test_self_heal_handoff_plan_pair_is_not_counted_as_duplicate(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 14, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-self-heal-monitor",
        rrule="RRULE:FREQ=HOURLY;INTERVAL=1;BYMINUTE=0;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_packet(
        repo / "results/self_heal/self-heal-handoff-20260603-130000.json",
        "2026-06-03T13:00:00+00:00",
        should_start_new_chat=True,
        trigger_count=1,
    )
    _write_packet(
        repo / "results/self_heal/plans/self-heal-plan-20260603-130001.json",
        "2026-06-03T13:00:01+00:00",
        status="verified",
        executed_count=1,
        verified_count=1,
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-self-heal-monitor"]

    assert row["status"] == "ok"
    assert "duplicate_run" not in row["issue_types"]
    assert row["self_heal_timeliness"]["timely"] is True


def test_self_heal_duplicate_history_is_ok_when_latest_actionable_plan_is_timely(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 14, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-self-heal-monitor",
        rrule="RRULE:FREQ=WEEKLY;BYDAY=SU,MO,TU,WE,TH,FR,SA;BYHOUR=0,1,2,3,4,5,6,7,8,9,10,11,12,13;BYMINUTE=0,15,30,45",
    )
    _write_packet(
        repo / "results/self_heal/self-heal-handoff-20260603-081530.json",
        "2026-06-03T08:15:30+00:00",
        should_start_new_chat=True,
        trigger_count=2,
    )
    _write_packet(
        repo / "results/self_heal/self-heal-handoff-20260603-081535.json",
        "2026-06-03T08:15:35+00:00",
        should_start_new_chat=True,
        trigger_count=3,
    )
    _write_packet(
        repo / "results/self_heal/self-heal-handoff-20260603-130000.json",
        "2026-06-03T13:00:00+00:00",
        should_start_new_chat=True,
        trigger_count=1,
    )
    _write_packet(
        repo / "results/self_heal/plans/self-heal-plan-20260603-130030.json",
        "2026-06-03T13:00:30+00:00",
        status="verified",
        executed_count=1,
        verified_count=1,
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-self-heal-monitor"]

    assert row["duplicate_count"] == 1
    assert row["status"] == "ok"
    assert row["status_reason"] == "self_heal_timely_duplicate_artifacts_de_noised"
    assert "duplicate_run" not in row["issue_types"]
    assert row["self_heal_timeliness"]["followup_lag_seconds"] == 30


def test_self_heal_overlap_history_is_ok_when_latest_actionable_plan_is_timely(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 14, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-self-heal-monitor",
        rrule="RRULE:FREQ=HOURLY;INTERVAL=1;BYMINUTE=15;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_packet(
        repo / "results/self_heal/self-heal-handoff-20260603-130900.json",
        "2026-06-03T13:09:00+00:00",
        should_start_new_chat=False,
    )
    _write_packet(
        repo / "results/self_heal/self-heal-handoff-20260603-131200.json",
        "2026-06-03T13:12:00+00:00",
        should_start_new_chat=True,
        trigger_count=1,
    )
    _write_packet(
        repo / "results/self_heal/plans/self-heal-plan-20260603-131230.json",
        "2026-06-03T13:12:30+00:00",
        status="verified",
        executed_count=1,
        verified_count=1,
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-self-heal-monitor"]

    assert row["overlap_count"] == 1
    assert row["status"] == "ok"
    assert row["status_reason"] == "self_heal_timely_followup_artifacts_de_noised"
    assert "overlap_run" not in row["issue_types"]
    assert row["problem_jobs"] == []
    assert row["self_heal_timeliness"]["followup_lag_seconds"] == 30


def test_automation_health_counts_unique_submitted_packets_once_across_shared_rows(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 14, 0, tzinfo=UTC)

    for automation_id in (
        "hourly-market-supervisor",
        "market-supervisor-15-min-before-open",
        "market-supervisor-30-min-after-open",
    ):
        _write_automation(
            automation_root,
            automation_id,
            rrule="RRULE:FREQ=HOURLY;INTERVAL=1;BYMINUTE=0;BYDAY=SU,MO,TU,WE,TH,FR,SA",
        )
    _write_packet(
        repo / "results/hourly_supervisor/hourly-supervisor-20260603-130000.json",
        "2026-06-03T13:00:00+00:00",
        submitted=[{"symbol": "MSFT", "side": "buy"}],
        issues=[],
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )

    assert audit["submitted_order_count"] == 1
    assert audit["issue_count"] == 0


def test_hourly_market_supervisor_ignores_shared_folder_packets_from_market_window_runs(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 15, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "hourly-market-supervisor",
        rrule="RRULE:FREQ=HOURLY;INTERVAL=1;BYMINUTE=0;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_automation(
        automation_root,
        "market-supervisor-15-min-before-open",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=8;BYMINUTE=15;BYDAY=MO,TU,WE,TH,FR",
    )
    _write_memory(
        automation_root,
        "market-supervisor-15-min-before-open",
        "2026-06-03T13:25:00 pre-open supervisor completed.\n",
    )
    _write_packet(
        repo / "results/hourly_supervisor/hourly-supervisor-20260603-132227.json",
        "2026-06-03T13:22:27+00:00",
        decision="blocked",
        submitted=[],
        issues=[{"ticket_id": "live-submit-guard", "reason": "dead-man expired"}],
    )
    _write_packet(
        repo / "results/hourly_supervisor/hourly-supervisor-20260603-140814.json",
        "2026-06-03T14:08:14+00:00",
        decision="loss-review",
        submitted=[],
        issues=[],
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["hourly-market-supervisor"]

    assert row["issue_count"] == 0
    assert row["packet_paths"] == [
        str(repo / "results/hourly_supervisor/hourly-supervisor-20260603-140814.json")
    ]
    assert audit["issue_count"] == 0


def test_market_window_automation_uses_memory_instead_of_all_hourly_packets(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 14, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "market-supervisor-15-min-before-open",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=8;BYMINUTE=15;BYDAY=MO,TU,WE,TH,FR",
    )
    _write_memory(
        automation_root,
        "market-supervisor-15-min-before-open",
        "2026-06-03T13:20:00 pre-open supervisor completed.\n",
    )
    for minute in range(5):
        _write_packet(
            repo / f"results/hourly_supervisor/hourly-supervisor-20260603-13{minute}000.json",
            f"2026-06-03T13:{minute}0:00+00:00",
            submitted=[{"symbol": "MSFT"}],
            issues=[],
        )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["market-supervisor-15-min-before-open"]

    assert row["status"] == "ok"
    assert row["actual_artifact_count"] == 0
    assert "duplicate_run" not in row["issue_types"]


def test_overnight_planning_ignores_rolling_premarket_brief_artifacts(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 3, 19, 0, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-overnight-planning",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=2;BYMINUTE=30;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_packet(
        repo / "results/overnight_plans/overnight-plan-20260603-173402.json",
        "2026-06-03T17:34:02+00:00",
        analysis_only=True,
        submitted=[],
        issues=[],
    )
    for index in range(5):
        _write_packet(
            repo / f"results/premarket_briefs/premarket-brief-20260603-18{index}000.json",
            f"2026-06-03T18:{index}0:00+00:00",
            analysis_only=True,
            blockers=[],
        )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-overnight-planning"]

    assert row["actual_artifact_count"] == 1
    assert row["duplicate_count"] == 0
    assert row["status"] == "ok"
    assert "duplicate_run" not in row["issue_types"]
    assert row["packet_paths"] == [
        str(repo / "results/overnight_plans/overnight-plan-20260603-173402.json")
    ]


def test_night_shift_schedule_warns_when_four_hour_cadence_is_missing(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 5, 18, 30, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-night-shift-supervisor",
        rrule="RRULE:FREQ=WEEKLY;BYHOUR=0,4,20;BYMINUTE=15;BYDAY=SU,MO,TU,WE,TH,FR,SA",
    )
    _write_memory(
        automation_root,
        "tradingagents-night-shift-supervisor",
        "2026-06-05 13:20:00 -05:00\nNight-shift patrol ran.\n",
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-night-shift-supervisor"]

    assert row["status"] == "warning"
    assert row["status_reason"] == "config_policy_warning:night_shift_cadence_mismatch"
    assert "night_shift_cadence_mismatch" in row["issue_types"]


def test_night_shift_schedule_accepts_intended_four_hour_cadence(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 5, 18, 30, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-night-shift-supervisor",
        rrule=(
            "RRULE:FREQ=WEEKLY;BYHOUR=0,4,8,12,16,20;"
            "BYMINUTE=15;BYDAY=SU,MO,TU,WE,TH,FR,SA"
        ),
    )
    _write_memory(
        automation_root,
        "tradingagents-night-shift-supervisor",
        "2026-06-05 13:20:00 -05:00\nNight-shift patrol ran.\n",
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-night-shift-supervisor"]

    assert row["status"] == "ok"
    assert "night_shift_cadence_mismatch" not in row["issue_types"]


def test_night_shift_patrol_packet_counts_as_schedule_evidence(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 5, 18, 30, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-night-shift-supervisor",
        rrule=(
            "RRULE:FREQ=WEEKLY;BYHOUR=0,4,8,12,16,20;"
            "BYMINUTE=15;BYDAY=SU,MO,TU,WE,TH,FR,SA"
        ),
    )
    _write_memory(
        automation_root,
        "tradingagents-night-shift-supervisor",
        "2026-06-03 00:42:53 -05:00\nOld native memory.\n",
    )
    _write_packet(
        repo / "results/night_shift_patrol/night-shift-patrol-20260605-171800.json",
        "2026-06-05T17:18:00+00:00",
        automation_id="tradingagents-night-shift-supervisor",
        analysis_only=True,
        can_submit_orders=False,
        execution_authority="none",
        submitted_count=0,
        issue_count=0,
    )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=2,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-night-shift-supervisor"]

    assert row["expected_run_count"] == 1
    assert row["actual_artifact_count"] == 1
    assert row["status"] == "ok"
    assert row["packet_paths"] == [
        str(repo / "results/night_shift_patrol/night-shift-patrol-20260605-171800.json")
    ]
    assert "stale_memory" not in row["issue_types"]


def test_night_shift_partial_history_is_ok_when_latest_due_is_covered(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 6, 22, 40, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-night-shift-supervisor",
        rrule=(
            "RRULE:FREQ=WEEKLY;BYHOUR=0,4,8,12,16,20;"
            "BYMINUTE=15;BYDAY=SU,MO,TU,WE,TH,FR,SA"
        ),
    )
    for timestamp in (
        "2026-06-06T18:56:09+00:00",
        "2026-06-06T20:28:43+00:00",
        "2026-06-06T21:31:12+00:00",
    ):
        run_id = timestamp.replace("-", "").replace(":", "").split("+", 1)[0]
        _write_packet(
            repo / f"results/night_shift_patrol/night-shift-patrol-{run_id}.json",
            timestamp,
            automation_id="tradingagents-night-shift-supervisor",
            analysis_only=True,
            can_submit_orders=False,
            execution_authority="none",
            submitted_count=0,
            issue_count=0,
        )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-night-shift-supervisor"]

    assert row["expected_run_count"] == 6
    assert row["actual_artifact_count"] == 3
    assert row["history_gap_count"] == 3
    assert row["status"] == "ok"
    assert row["status_reason"] == "night_shift_latest_due_covered_history_ramp_up"
    assert "missed_run" not in row["issue_types"]


def test_night_shift_ignores_due_windows_before_schedule_update(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 6, 22, 51, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-night-shift-supervisor",
        rrule=(
            "RRULE:FREQ=WEEKLY;BYHOUR=0,4,8,12,16,20;"
            "BYMINUTE=15;BYDAY=SU,MO,TU,WE,TH,FR,SA"
        ),
        updated_at="2026-06-06T13:54:18+00:00",
    )
    _write_memory(
        automation_root,
        "tradingagents-night-shift-supervisor",
        "2026-06-04 00:19:18 -05:00\nOld native memory.\n",
    )
    for timestamp in (
        "2026-06-06T18:56:09+00:00",
        "2026-06-06T20:28:43+00:00",
        "2026-06-06T21:31:12+00:00",
        "2026-06-06T22:50:22+00:00",
    ):
        run_id = timestamp.replace("-", "").replace(":", "").split("+", 1)[0]
        _write_packet(
            repo / f"results/night_shift_patrol/night-shift-patrol-{run_id}.json",
            timestamp,
            automation_id="tradingagents-night-shift-supervisor",
            analysis_only=True,
            can_submit_orders=False,
            execution_authority="none",
            submitted_count=0,
            issue_count=0,
        )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-night-shift-supervisor"]

    assert row["config_effective_at"] == "2026-06-06T13:54:18+00:00"
    assert row["expected_run_count"] == 2
    assert row["actual_artifact_count"] == 4
    assert row["status"] == "ok"
    assert row["status_reason"] is None
    assert "missed_run" not in row["issue_types"]
    assert "duplicate_run" not in row["issue_types"]


def test_night_shift_stays_partial_when_latest_due_is_not_covered(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    now = dt.datetime(2026, 6, 6, 22, 40, tzinfo=UTC)

    _write_automation(
        automation_root,
        "tradingagents-night-shift-supervisor",
        rrule=(
            "RRULE:FREQ=WEEKLY;BYHOUR=0,4,8,12,16,20;"
            "BYMINUTE=15;BYDAY=SU,MO,TU,WE,TH,FR,SA"
        ),
    )
    for timestamp in (
        "2026-06-06T18:56:09+00:00",
        "2026-06-06T20:28:43+00:00",
    ):
        run_id = timestamp.replace("-", "").replace(":", "").split("+", 1)[0]
        _write_packet(
            repo / f"results/night_shift_patrol/night-shift-patrol-{run_id}.json",
            timestamp,
            automation_id="tradingagents-night-shift-supervisor",
            analysis_only=True,
            can_submit_orders=False,
            execution_authority="none",
            submitted_count=0,
            issue_count=0,
        )

    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=now,
        window_hours=24,
    )
    row = {
        item["automation_id"]: item for item in audit["automations"]
    }["tradingagents-night-shift-supervisor"]

    assert row["expected_run_count"] == 6
    assert row["actual_artifact_count"] == 2
    assert row["status"] == "partial"
    assert row["status_reason"] == "observed_runs_less_than_expected:2/6"
    assert "missed_run" in row["issue_types"]


def test_automation_health_audit_writes_latest_json_and_markdown(tmp_path):
    automation_root = tmp_path / "automations"
    repo = tmp_path / "repo"
    _write_automation(
        automation_root,
        "fetch-tradingagents-deep-research-report",
        rrule="FREQ=DAILY;COUNT=1;BYHOUR=4;BYMINUTE=30",
    )
    _write_packet(
        repo / "reports/research_merge/deep-research-report.json",
        "2026-06-02T10:00:00+00:00",
        status="complete",
    )
    audit = build_automation_health_audit(
        repo_root=repo,
        automation_root=automation_root,
        now=dt.datetime(2026, 6, 3, 14, 0, tzinfo=UTC),
        window_hours=24,
    )

    json_path, md_path = write_automation_health_audit(audit, tmp_path / "out")

    assert json_path.exists()
    assert md_path.exists()
    assert (tmp_path / "out" / "latest.json").exists()
    assert (tmp_path / "out" / "latest.md").exists()
    assert json_path.with_suffix(".compact.json").exists()
    assert (tmp_path / "out" / "latest-compact.json").exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    compact = json.loads(json_path.with_suffix(".compact.json").read_text(encoding="utf-8"))
    latest_compact = json.loads(
        (tmp_path / "out" / "latest-compact.json").read_text(encoding="utf-8")
    )
    assert payload["kind"] == "tradingagents_automation_health_audit"
    assert payload["can_submit_orders"] is False
    assert compact == latest_compact
    assert compact["schema"] == "compact_automation_health_audit_v1"
    assert compact["raw_packet_path"] == str(json_path)
    assert compact["markdown_path"] == str(md_path)
    assert compact["can_submit_orders"] is False


def test_compact_automation_health_preserves_benign_night_shift_partial():
    audit = {
        "generated_at": "2026-06-06T23:40:00+00:00",
        "analysis_only": True,
        "can_submit_orders": False,
        "automation_count": 1,
        "submitted_order_count": 0,
        "issue_count": 0,
        "summary": {
            "ok_count": 0,
            "partial_count": 1,
            "missing_count": 0,
            "late_count": 0,
            "duplicate_count": 0,
            "stale_count": 0,
            "warning_count": 0,
            "timeliness_issue_count": 0,
        },
        "automations": [
            {
                "automation_id": "tradingagents-night-shift-supervisor",
                "status": "partial",
                "status_reason": "observed_runs_less_than_expected:3<4",
                "actual_artifact_count": 3,
                "issue_types": [],
            }
        ],
        "json_path": "results/automation_health/raw.json",
        "markdown_path": "results/automation_health/raw.md",
    }

    compact = build_compact_automation_health_audit(audit)

    assert compact["partial_count"] == 1
    assert compact["actionable_partial_count"] == 0
    assert compact["benign_partial_automation_ids"] == ["tradingagents-night-shift-supervisor"]
    assert compact["problem_automation_ids"] == []


def test_compact_automation_health_keeps_timely_self_heal_overlap_out_of_problems():
    audit = {
        "generated_at": "2026-06-07T02:18:40+00:00",
        "analysis_only": True,
        "can_submit_orders": False,
        "automation_count": 1,
        "submitted_order_count": 0,
        "issue_count": 0,
        "summary": {
            "ok_count": 1,
            "partial_count": 0,
            "missing_count": 0,
            "late_count": 0,
            "duplicate_count": 0,
            "stale_count": 0,
            "warning_count": 0,
            "timeliness_issue_count": 0,
        },
        "automations": [
            {
                "automation_id": "tradingagents-self-heal-monitor",
                "status": "ok",
                "issue_types": ["overlap_run"],
                "problem_jobs": [],
                "self_heal_timeliness": {
                    "latest_actionable_handoff_at": "2026-06-06T22:18:47+00:00",
                    "latest_followup_plan_at": "2026-06-06T22:19:21+00:00",
                    "followup_lag_seconds": 34,
                    "sla_minutes": 30,
                    "timely": True,
                    "issue": None,
                },
            }
        ],
        "json_path": "results/automation_health/raw.json",
        "markdown_path": "results/automation_health/raw.md",
    }

    compact = build_compact_automation_health_audit(audit)

    assert compact["problem_automation_ids"] == []
    assert compact["attention_automation_ids"] == ["tradingagents-self-heal-monitor"]
    assert compact["self_heal_timeliness"]["timely"] is True
