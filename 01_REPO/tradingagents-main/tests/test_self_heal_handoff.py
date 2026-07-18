import datetime as dt
import json
from pathlib import Path

from tradingagents.orchestration.self_heal import (
    build_self_heal_handoff,
    build_self_heal_plan,
    execute_self_heal_plan,
    write_self_heal_handoff,
    write_self_heal_plan,
)


def _write_context(root: Path, *, flags: list[dict], latest_packets: list[dict] | None = None) -> None:
    context_dir = root / "results" / "_context"
    context_dir.mkdir(parents=True)
    (context_dir / "latest-flags.json").write_text(json.dumps({"flags": flags}), encoding="utf-8")
    (context_dir / "latest-summary.json").write_text(
        json.dumps({"generated_at": "2026-06-03T00:00:00Z", "latest_packets": latest_packets or []}),
        encoding="utf-8",
    )


def test_self_heal_handoff_starts_chat_for_supervisor_issue(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "hourly",
                "reason": "issues",
                "path": "results/hourly_supervisor/latest.json",
                "meaning": "Open the full packet when guardrail issues are present.",
            }
        ],
    )

    packet = build_self_heal_handoff(tmp_path)

    assert packet["analysis_only"] is True
    assert packet["can_submit_orders"] is False
    assert packet["execution_authority"] == "none"
    assert packet["should_start_new_chat"] is True
    assert packet["max_severity"] == "high"
    assert packet["triggers"][0]["label"] == "hourly"
    assert "results/hourly_supervisor/latest.json" in packet["new_chat_prompt"]
    assert "Do not submit live or paper orders" in packet["new_chat_prompt"]


def test_self_heal_handoff_stays_quiet_for_low_only_stale_flag(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "overnight_verification",
                "reason": "stale",
                "path": "results/overnight_system_verification/latest.json",
            }
        ],
    )

    packet = build_self_heal_handoff(tmp_path)

    assert packet["should_start_new_chat"] is False
    assert packet["max_severity"] == "low"
    assert packet["trigger_count"] == 1


def test_self_heal_handoff_writes_latest_json_markdown_and_prompt(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[{"label": "execution_board_review", "reason": "board_review", "path": "results/execution_board/latest.json"}],
        latest_packets=[
            {
                "label": "execution_board_review",
                "path": "results/execution_board/latest.json",
                "failed_checks": ["paired_live_sell_and_buy"],
            }
        ],
    )
    packet = build_self_heal_handoff(tmp_path)

    json_path, markdown_path, prompt_path = write_self_heal_handoff(packet, tmp_path / "results" / "self_heal")

    assert json_path.exists()
    assert markdown_path.exists()
    assert prompt_path.exists()
    assert (tmp_path / "results" / "self_heal" / "latest.json").exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["should_start_new_chat"] is True
    assert "paired_live_sell_and_buy" in prompt_path.read_text(encoding="utf-8")


def test_self_heal_handoff_ignores_its_own_prior_packet(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "self_heal_handoff",
                "reason": "issues",
                "path": "results/self_heal/latest.json",
            }
        ],
        latest_packets=[
            {
                "label": "self_heal_handoff",
                "path": "results/self_heal/latest.json",
                "drilldown_reasons": ["issues"],
            }
        ],
    )

    packet = build_self_heal_handoff(tmp_path)

    assert packet["trigger_count"] == 0
    assert packet["should_start_new_chat"] is False


def test_self_heal_handoff_ignores_prior_self_heal_plan(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "self_heal_plan",
                "reason": "issues",
                "path": "results/self_heal/plans/latest.json",
            }
        ],
        latest_packets=[
            {
                "label": "self_heal_plan",
                "path": "results/self_heal/plans/latest.json",
                "drilldown_reasons": ["issues"],
            }
        ],
    )

    packet = build_self_heal_handoff(tmp_path)
    plan = build_self_heal_plan(tmp_path)

    assert packet["trigger_count"] == 0
    assert packet["should_start_new_chat"] is False
    assert plan["signal_count"] == 0


def test_self_heal_handoff_keeps_known_overnight_preopen_warning_low(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[],
        latest_packets=[
            {
                "label": "overnight_verification",
                "path": "results/overnight_system_verification/latest.json",
                "failed_checks": ["simulated_preopen_validation"],
            }
        ],
    )

    packet = build_self_heal_handoff(tmp_path)

    assert packet["trigger_count"] == 1
    assert packet["max_severity"] == "low"
    assert packet["should_start_new_chat"] is False


def test_self_heal_plan_keeps_known_overnight_preopen_warning_low(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[],
        latest_packets=[
            {
                "label": "overnight_verification",
                "path": "results/overnight_system_verification/latest.json",
                "failed_checks": ["simulated_preopen_validation"],
            }
        ],
    )

    packet = build_self_heal_plan(tmp_path)

    assert packet["signal_count"] == 1
    assert packet["max_severity"] == "low"
    assert packet["status"] == "quiet"
    signal = packet["signals"][0]
    assert signal["classification"] == "observe_only"
    assert signal["status"] == "observed"
    assert signal["escalation_required"] is False


def test_self_heal_handoff_treats_packet_counters_as_actionable(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[],
        latest_packets=[
            {
                "label": "hourly",
                "path": "results/hourly_supervisor/latest.json",
                "blocker_count": 1,
                "issue_count": 2,
            }
        ],
    )

    packet = build_self_heal_handoff(tmp_path)

    assert packet["should_start_new_chat"] is True
    assert packet["max_severity"] == "high"
    reasons = {trigger["reason"] for trigger in packet["triggers"]}
    assert {"blocker_count", "issue_count"}.issubset(reasons)


def test_self_heal_handoff_dedupes_repeated_signature_after_write(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "hourly",
                "reason": "issues",
                "path": "results/hourly_supervisor/latest.json",
                "meaning": "Same guardrail issue keeps showing up.",
            }
        ],
    )
    first = build_self_heal_handoff(tmp_path)
    write_self_heal_handoff(first, tmp_path / "results" / "self_heal")

    second = build_self_heal_handoff(tmp_path)

    assert first["should_start_new_chat"] is True
    assert first["active_trigger_count"] == 1
    assert second["trigger_count"] == 1
    assert second["active_trigger_count"] == 0
    assert second["deduped_prior_count"] == 1
    assert second["should_start_new_chat"] is False
    assert second["triggers"][0]["status"] == "already_recorded"
    assert second["triggers"][0]["deduped_prior"] is True


def test_self_heal_plan_records_safe_connector_fix_without_order_authority(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "connector_health",
                "reason": "connector_health",
                "path": "results/_context/connector-health.json",
                "meaning": "FRED fallback fired and one connector circuit is open.",
            }
        ],
    )

    packet = build_self_heal_plan(tmp_path)

    assert packet["analysis_only"] is True
    assert packet["can_submit_orders"] is False
    assert packet["execution_authority"] == "none"
    assert packet["active_plan_count"] == 1
    signal = packet["signals"][0]
    assert signal["classification"] == "safe_autofix"
    assert signal["status"] == "planned"
    assert signal["recommended_action"] == "refresh_connector_health_and_use_fallbacks"
    assert "scripts/automation_context_snapshot.py --write" in signal["verify_command"]
    assert signal["escalation_required"] is False
    assert "submit_order" in signal["forbidden_effects"]


def test_self_heal_plan_refreshes_stale_loss_review_evidence_safely(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "loss_review_evidence",
                "reason": "stale",
                "path": "results/loss_review_evidence/latest-compact.json",
                "meaning": "Loss-review evidence is older than the latest hourly packet.",
            }
        ],
    )

    packet = build_self_heal_plan(tmp_path)
    signal = packet["signals"][0]

    assert packet["active_plan_count"] == 1
    assert signal["classification"] == "safe_autofix"
    assert signal["recommended_action"] == "refresh_latest_loss_review_evidence_then_compact_context"
    assert signal["execute_commands"] == [
        "uv run --no-sync python -m cli.main research loss-review-evidence --json-output",
        "uv run --no-sync python scripts/automation_context_snapshot.py --write",
    ]
    assert signal["safe_effects"] == [
        "refresh_loss_review_evidence",
        "refresh_compact_context",
        "record_board_review_guidance",
    ]
    assert signal["escalation_required"] is False


def test_self_heal_plan_executes_loss_review_evidence_refresh_safely(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "loss_review_evidence",
                "reason": "stale",
                "path": "results/loss_review_evidence/latest-compact.json",
            }
        ],
    )
    packet = build_self_heal_plan(tmp_path)
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))

        class Result:
            returncode = 0
            stdout = '{"kind":"source_evidence","execution_authority":"none"}'
            stderr = ""

        return Result()

    updated = execute_self_heal_plan(packet, repo_root=tmp_path, runner=fake_runner)

    assert calls == [
        (
            [
                "uv",
                "run",
                "--no-sync",
                "python",
                "-m",
                "cli.main",
                "research",
                "loss-review-evidence",
                "--json-output",
            ],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 90},
        ),
        (
            [
                "uv",
                "run",
                "--no-sync",
                "python",
                "scripts/automation_context_snapshot.py",
                "--write",
            ],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 90},
        ),
    ]
    signal = updated["signals"][0]
    assert updated["verified_count"] == 1
    assert updated["executed_count"] == 1
    assert signal["status"] == "verified"
    assert signal["escalation_required"] is False
    assert [item["exit_code"] for item in signal["verify_results"]] == [0, 0]


def test_self_heal_plan_refreshes_stale_preopen_validation_safely(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "preopen_validation",
                "reason": "stale",
                "path": "results/preopen_validation/latest-compact.json",
                "meaning": "Preopen validation is older than the latest premarket context.",
            }
        ],
    )

    packet = build_self_heal_plan(tmp_path)
    signal = packet["signals"][0]

    assert packet["active_plan_count"] == 1
    assert signal["classification"] == "safe_autofix"
    assert signal["recommended_action"] == "refresh_preopen_validation_then_compact_context"
    assert signal["execute_commands"] == [
        "uv run --no-sync python -m cli.main alpaca preopen-validation --json-output",
        "uv run --no-sync python scripts/automation_context_snapshot.py --write",
    ]
    assert signal["safe_effects"] == [
        "refresh_preopen_validation",
        "refresh_compact_context",
        "record_closed_market_or_live_control_guidance",
    ]
    assert signal["escalation_required"] is False


def test_self_heal_plan_executes_preopen_validation_refresh_safely(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "preopen_validation",
                "reason": "stale",
                "path": "results/preopen_validation/latest-compact.json",
            }
        ],
    )
    packet = build_self_heal_plan(tmp_path)
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))

        class Result:
            returncode = 0
            stdout = '{"kind":"tradingagents_preopen_validation","can_submit_orders":false}'
            stderr = ""

        return Result()

    updated = execute_self_heal_plan(packet, repo_root=tmp_path, runner=fake_runner)

    assert calls == [
        (
            [
                "uv",
                "run",
                "--no-sync",
                "python",
                "-m",
                "cli.main",
                "alpaca",
                "preopen-validation",
                "--json-output",
            ],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 90},
        ),
        (
            [
                "uv",
                "run",
                "--no-sync",
                "python",
                "scripts/automation_context_snapshot.py",
                "--write",
            ],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 90},
        ),
    ]
    signal = updated["signals"][0]
    assert updated["verified_count"] == 1
    assert updated["executed_count"] == 1
    assert signal["status"] == "verified"
    assert signal["escalation_required"] is False
    assert [item["exit_code"] for item in signal["verify_results"]] == [0, 0]


def test_self_heal_handoff_starts_for_automation_health_gap(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "automation_health_audit",
                "reason": "automation_health",
                "path": "results/automation_health/latest.json",
                "meaning": "Night-shift controller and wake controller memories are stale.",
            }
        ],
    )

    packet = build_self_heal_handoff(tmp_path)

    assert packet["should_start_new_chat"] is True
    assert packet["max_severity"] == "medium"
    assert packet["triggers"][0]["reason"] == "automation_health"
    assert "results/automation_health/latest.json" in packet["new_chat_prompt"]
    assert packet["can_submit_orders"] is False


def test_self_heal_plan_runs_real_automation_health_audit_safely(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "automation_health_audit",
                "reason": "automation_health",
                "path": "results/automation_health/latest.json",
                "meaning": "Overnight planner missed the settled 2:30 AM due window.",
            }
        ],
    )
    packet = build_self_heal_plan(tmp_path)
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))

        class Result:
            returncode = 0
            stdout = '{"kind":"tradingagents_automation_health_audit","summary":{"missing_count":0}}'
            stderr = ""

        return Result()

    updated = execute_self_heal_plan(packet, repo_root=tmp_path, runner=fake_runner)

    signal = updated["signals"][0]
    assert packet["active_plan_count"] == 1
    assert signal["classification"] == "safe_autofix"
    assert signal["recommended_action"] == "write_night_shift_patrol_then_rerun_automation_health_audit"
    assert calls == [
        (
            [
                "uv",
                "run",
                "--no-sync",
                "python",
                "-m",
                "cli.main",
                "research",
                "night-shift-patrol",
                "--json-output",
            ],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 90},
        ),
        (
            [
                "uv",
                "run",
                "--no-sync",
                "python",
                "-m",
                "cli.main",
                "research",
                "automation-health-audit",
                "--json-output",
            ],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 90},
        )
    ]
    assert updated["verified_count"] == 1
    assert signal["status"] == "verified"
    assert signal["escalation_required"] is False
    assert [item["exit_code"] for item in signal["verify_results"]] == [0, 0]


def test_self_heal_plan_runs_real_model_route_probe_safely(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "model_telemetry_report",
                "reason": "model_telemetry",
                "path": "results/model_telemetry_reports/latest.json",
                "meaning": "All local helper model lanes are blocked; run a safe route probe and use fallbacks.",
            }
        ],
    )
    packet = build_self_heal_plan(tmp_path)
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))

        class Result:
            returncode = 0
            stdout = '{"kind":"model_route_probe","status":"success"}'
            stderr = ""

        return Result()

    updated = execute_self_heal_plan(packet, repo_root=tmp_path, runner=fake_runner)

    signal = updated["signals"][0]
    assert packet["active_plan_count"] == 1
    assert signal["classification"] == "safe_autofix"
    assert signal["recommended_action"] == "probe_model_routes_and_use_available_fallbacks"
    assert calls == [
        (
            [
                "uv",
                "run",
                "--no-sync",
                "python",
                "-m",
                "cli.main",
                "research",
                "automation-orchestration-plan",
                "--candidate-symbols",
                "XOM",
                "--no-research-context",
                "--output-dir",
                "results/research_batches/model_route_health",
                "--model-telemetry-dir",
                "results/model_telemetry",
                "--json-output",
            ],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 90},
        ),
        (
            [
                "uv",
                "run",
                "--no-sync",
                "python",
                "-m",
                "cli.main",
                "research",
                "model-telemetry-report",
                "--json-output",
            ],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 90},
        ),
        (
            ["uv", "run", "--no-sync", "python", "scripts/automation_context_snapshot.py", "--write"],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 90},
        ),
    ]
    assert updated["verified_count"] == 1
    assert signal["status"] == "verified"
    assert signal["escalation_required"] is False
    assert [item["exit_code"] for item in signal["verify_results"]] == [0, 0, 0]


def test_self_heal_plan_escalates_forbidden_effects_without_active_fix(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "hourly",
                "reason": "issues",
                "path": "results/hourly_supervisor/latest.json",
                "meaning": "A broker submit path failed and must not self-repair itself.",
                "requested_effects": ["submit_order"],
            }
        ],
    )

    packet = build_self_heal_plan(tmp_path)

    assert packet["active_plan_count"] == 0
    assert packet["escalation_count"] == 1
    signal = packet["signals"][0]
    assert signal["classification"] == "escalate_forbidden_effect"
    assert signal["status"] == "escalated"
    assert signal["escalation_required"] is True
    assert signal["recommended_action"] == "manual_codex_review_required"
    assert signal["verify_command"] is None


def test_self_heal_plan_routes_policy_conflict_to_owned_verified_recovery(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "policy_rule_conflict",
                "reason": "approval_conflict",
                "symbol": "NFLX",
                "path": "results/policy/latest.json",
            }
        ],
    )

    packet = build_self_heal_plan(tmp_path)

    signal = packet["signals"][0]
    assert signal["classification"] == "recoverable_integrity"
    assert signal["status"] == "owned_recovery_ready"
    assert signal["recommended_action"] == "coordinate_verified_recovery"
    assert signal["owner_role"] == "reliability_controller"


def test_self_heal_plan_dedupes_already_recorded_safe_signals(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "connector_health",
                "reason": "connector_health",
                "path": "results/_context/connector-health.json",
            }
        ],
    )
    first = build_self_heal_plan(tmp_path)
    executed = execute_self_heal_plan(
        first,
        repo_root=tmp_path,
        runner=lambda command, **kwargs: type(
            "Result",
            (),
            {"returncode": 0, "stdout": "verified", "stderr": ""},
        )(),
    )
    write_self_heal_plan(executed, tmp_path / "results" / "self_heal" / "plans")

    second = build_self_heal_plan(tmp_path)

    assert second["signal_count"] == 1
    assert second["active_plan_count"] == 0
    assert second["deduped_prior_count"] == 1
    assert second["signals"][0]["status"] == "already_recorded"


def test_self_heal_plan_reads_durable_signature_state_when_latest_plan_missing(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "connector_health",
                "reason": "connector_health",
                "path": "results/_context/connector-health.json",
            }
        ],
    )
    first = build_self_heal_plan(tmp_path)
    executed = execute_self_heal_plan(
        first,
        repo_root=tmp_path,
        runner=lambda command, **kwargs: type(
            "Result",
            (),
            {"returncode": 0, "stdout": "verified", "stderr": ""},
        )(),
    )
    plan_dir = tmp_path / "results" / "self_heal" / "plans"
    write_self_heal_plan(executed, plan_dir)
    (plan_dir / "latest.json").unlink()

    second = build_self_heal_plan(tmp_path)

    assert second["signal_count"] == 1
    assert second["active_plan_count"] == 0
    assert second["deduped_prior_count"] == 1
    assert second["signals"][0]["status"] == "already_recorded"


def test_self_heal_plan_reverifies_persistent_safe_signal_after_sla(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "automation_health_audit",
                "reason": "automation_health",
                "path": "results/automation_health/latest.json",
            }
        ],
    )
    now = dt.datetime(2026, 6, 6, 12, 30, tzinfo=dt.timezone.utc)
    first = build_self_heal_plan(tmp_path, now=now)
    executed = execute_self_heal_plan(
        first,
        repo_root=tmp_path,
        runner=lambda command, **kwargs: type(
            "Result",
            (),
            {"returncode": 0, "stdout": "verified", "stderr": ""},
        )(),
    )
    write_self_heal_plan(executed, tmp_path / "results" / "self_heal" / "plans", now=now)

    second = build_self_heal_plan(
        tmp_path,
        now=now + dt.timedelta(minutes=16),
        safe_reverify_minutes=15,
    )

    assert second["signal_count"] == 1
    assert second["active_plan_count"] == 1
    assert second["deduped_prior_count"] == 0
    signal = second["signals"][0]
    assert signal["status"] == "planned"
    assert signal["reverify_required"] is True
    assert signal["reverify_reason"] == "persistent_safe_autofix_after_sla"
    assert signal["prior_state"]["last_status"] == "verified"


def test_self_heal_plan_executes_reverification_of_persistent_safe_signal(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "automation_health_audit",
                "reason": "automation_health",
                "path": "results/automation_health/latest.json",
            }
        ],
    )
    now = dt.datetime(2026, 6, 6, 12, 30, tzinfo=dt.timezone.utc)
    first = build_self_heal_plan(tmp_path, now=now)
    write_self_heal_plan(
        execute_self_heal_plan(
            first,
            repo_root=tmp_path,
            runner=lambda command, **kwargs: type(
                "Result",
                (),
                {"returncode": 0, "stdout": "verified", "stderr": ""},
            )(),
        ),
        tmp_path / "results" / "self_heal" / "plans",
        now=now,
    )
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))

        class Result:
            returncode = 0
            stdout = '{"kind":"tradingagents_automation_health_audit","summary":{"partial_count":1}}'
            stderr = ""

        return Result()

    stale = build_self_heal_plan(
        tmp_path,
        now=now + dt.timedelta(minutes=16),
        safe_reverify_minutes=15,
    )
    updated = execute_self_heal_plan(stale, repo_root=tmp_path, runner=fake_runner)

    assert calls == [
        (
            [
                "uv",
                "run",
                "--no-sync",
                "python",
                "-m",
                "cli.main",
                "research",
                "night-shift-patrol",
                "--json-output",
            ],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 90},
        ),
        (
            [
                "uv",
                "run",
                "--no-sync",
                "python",
                "-m",
                "cli.main",
                "research",
                "automation-health-audit",
                "--json-output",
            ],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 90},
        )
    ]
    assert updated["executed_count"] == 1
    assert updated["verified_count"] == 1
    assert updated["signals"][0]["status"] == "verified"


def test_execute_self_heal_plan_runs_only_allowlisted_safe_verify_command(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "connector_health",
                "reason": "connector_health",
                "path": "results/_context/connector-health.json",
            }
        ],
    )
    packet = build_self_heal_plan(tmp_path)
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))

        class Result:
            returncode = 0
            stdout = "context refreshed"
            stderr = ""

        return Result()

    updated = execute_self_heal_plan(packet, repo_root=tmp_path, runner=fake_runner)

    assert calls == [
        (
            ["uv", "run", "--no-sync", "python", "scripts/automation_context_snapshot.py", "--write"],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 90},
        )
    ]
    assert updated["verified_count"] == 1
    assert updated["signals"][0]["status"] == "verified"
    assert updated["signals"][0]["verify_exit_code"] == 0


def test_self_heal_plan_repairs_stale_agent_intelligence_summary_schema(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "agent_intelligence_summary",
                "reason": "schema",
                "path": "results/agent_intelligence/summary.json",
            }
        ],
    )
    packet = build_self_heal_plan(tmp_path)
    signal = packet["signals"][0]

    assert signal["classification"] == "safe_autofix"
    assert signal["recommended_action"] == "regenerate_agent_ledger_summary_then_compact_context"
    assert signal["execute_commands"] == [
        "uv run --no-sync python -m cli.main research agent-ledger-summary --json-output",
        "uv run --no-sync python scripts/automation_context_snapshot.py --write",
    ]
    assert signal["safe_effects"] == [
        "refresh_agent_intelligence_summary",
        "refresh_compact_context",
        "record_schema_guidance",
    ]


def test_execute_self_heal_plan_runs_agent_summary_before_context_refresh(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "agent_intelligence_summary",
                "reason": "schema",
                "path": "results/agent_intelligence/summary.json",
            }
        ],
    )
    packet = build_self_heal_plan(tmp_path)
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))

        class Result:
            returncode = 0
            stdout = "verified"
            stderr = ""

        return Result()

    updated = execute_self_heal_plan(packet, repo_root=tmp_path, runner=fake_runner)

    assert calls == [
        (
            [
                "uv",
                "run",
                "--no-sync",
                "python",
                "-m",
                "cli.main",
                "research",
                "agent-ledger-summary",
                "--json-output",
            ],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 90},
        ),
        (
            ["uv", "run", "--no-sync", "python", "scripts/automation_context_snapshot.py", "--write"],
            {"cwd": str(tmp_path), "capture_output": True, "text": True, "timeout": 90},
        ),
    ]
    assert updated["executed_count"] == 1
    assert updated["verified_count"] == 1
    assert updated["signals"][0]["status"] == "verified"


def test_execute_self_heal_plan_never_runs_escalated_order_adjacent_signal(tmp_path: Path):
    _write_context(
        tmp_path,
        flags=[
            {
                "label": "hourly",
                "reason": "issues",
                "path": "results/hourly_supervisor/latest.json",
                "requested_effects": ["submit_order"],
            }
        ],
    )
    packet = build_self_heal_plan(tmp_path)
    calls = []

    updated = execute_self_heal_plan(
        packet,
        repo_root=tmp_path,
        runner=lambda command, **kwargs: calls.append((command, kwargs)),
    )

    assert calls == []
    assert updated["verified_count"] == 0
    assert updated["skipped_escalated_count"] == 1
    assert updated["signals"][0]["status"] == "escalated"
