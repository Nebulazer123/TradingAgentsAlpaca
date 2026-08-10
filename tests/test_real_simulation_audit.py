import datetime as dt
import json
import subprocess
import sys

import pytest

from tradingagents.evals.real_simulation_audit import (
    build_department_commands,
    run_real_simulation_audit,
)


def _mac_available_probe() -> dict[str, object]:
    return {
        "endpoint_url": "http://macbook-pro.tail37edd7.ts.net:11434/v1",
        "tags_url": "http://macbook-pro.tail37edd7.ts.net:11434/api/tags",
        "reachable": True,
        "model": "deepseek-r1:14b",
        "models": ["deepseek-r1:14b"],
        "deepseek_available": True,
    }


def _mac_unavailable_probe() -> dict[str, object]:
    return {
        "endpoint_url": "http://macbook-pro.tail37edd7.ts.net:11434/v1",
        "tags_url": "http://macbook-pro.tail37edd7.ts.net:11434/api/tags",
        "reachable": False,
        "model": "deepseek-r1:14b",
        "models": [],
        "error": "timed out",
    }


def _fresh_process_review_payload() -> dict[str, object]:
    return {
        "generated_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
        "unchecked_step_count": 0,
        "can_submit_orders": False,
        "json_path": "results/process_reviews/process-review.json",
    }


def test_real_simulation_command_plan_covers_departments_without_live_submit():
    commands = build_department_commands(top_symbols=["NOW", "IBM"])
    departments = {command.department for command in commands}
    flat_commands = [" ".join(command.command) for command in commands]

    assert {
        "preflight",
        "integrations",
        "model",
        "research",
        "policy",
        "alpaca",
        "paper_strategy",
        "board",
    } <= departments
    assert any("automation-orchestration-plan" in command for command in flat_commands)
    assert any("automation-health-audit" in command for command in flat_commands)
    assert any("self-heal-plan" in command for command in flat_commands)
    assert any("n8n-evaluation-dataset" in command for command in flat_commands)
    assert any(command.name == "agent_ledger_update" for command in commands)
    assert not any(command.name == "agent_ledger_resolve" for command in commands)
    assert any(command.name == "mirofish_handoff_status" for command in commands)
    assert any("ticker-provider-bundle --symbol NOW" in command for command in flat_commands)
    assert any("paper-tournament run --all --dry-run" in command for command in flat_commands)
    assert not any("--sector-relative-strength strong" in command for command in flat_commands)
    assert any("--sector-relative-strength 1.10" in command for command in flat_commands)
    assert not any(" --submit-actions" in command for command in flat_commands)
    assert not any(" alpaca submit " in command for command in flat_commands)


def test_real_simulation_audit_writes_packet_and_summarizes_department_results(tmp_path):
    calls = []

    def fake_runner(command, *, cwd, env, timeout):
        calls.append((command, env))
        joined = " ".join(command)
        if "source-quality-review" in joined:
            stdout = json.dumps(
                {
                    "analysis_only": True,
                    "can_submit_orders": False,
                    "source_count": 4,
                    "stale_count": 3,
                    "decisions": [
                        {
                            "source_name": "unknown_blog",
                            "path": "results/research_evidence/blog.json",
                            "freshness_status": "stale",
                            "quality": "low",
                            "blocked": True,
                            "allowed_effects": ["request_more_research"],
                            "reason": "blocked source should be sampled",
                        },
                        {
                            "source_name": "old_news",
                            "path": "results/research_evidence/news.json",
                            "freshness_status": "stale",
                            "quality": "low",
                            "blocked": False,
                            "allowed_effects": ["downrank", "request_more_research"],
                        },
                        {
                            "freshness_status": "stale",
                            "quality": "low",
                            "allowed_effects": ["downrank", "request_more_research"],
                        },
                    ],
                    "json_path": "results/source_quality/source-quality-review.json",
                    "quality_counts": {"low": 2, "medium": 2},
                }
            )
        elif "paper-tournament run" in joined:
            stdout = json.dumps(
                {
                    "submitted_count": 0,
                    "packet_path": "results/paper_strategy_tournament/paper-run.json",
                }
            )
        elif "process-review" in joined:
            stdout = json.dumps(_fresh_process_review_payload())
        else:
            stdout = json.dumps(
                {
                    "analysis_only": True,
                    "can_submit_orders": False,
                    "packet_path": "results/example.json",
                    "submitted": [],
                    "blockers": [],
                }
            )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    audit = run_real_simulation_audit(
        repo_root=tmp_path,
        output_dir=tmp_path / "audit",
        top_symbols=["NOW"],
        command_runner=fake_runner,
        now_id="20260603-050000",
        mac_probe_result=_mac_available_probe(),
    )

    assert audit["analysis_only"] is True
    assert audit["live_data_authority"] == "live_dry_run"
    assert audit["can_submit_orders"] is False
    assert audit["mac_ollama"]["model"] == "deepseek-r1:14b"
    assert audit["mac_ollama"]["endpoint_url"] == "http://macbook-pro.tail37edd7.ts.net:11434/v1"
    assert audit["department_count"] >= 8
    assert audit["failed_command_count"] == 0
    assert audit["total_submitted_order_count"] == 0
    assert audit["total_observed_submission_count"] == 0
    assert audit["unsafe_submission_evidence"] is False
    assert audit["commands_with_submission_evidence"] == []
    assert audit["commands_with_observed_submission_evidence"] == []
    assert audit["stale_source_count"] == 3
    assert audit["stale_downrank_count"] == 2
    assert audit["stale_safe_count"] == 3
    assert audit["acceptance"]["accepted"] is True
    assert audit["acceptance"]["no_orders_submitted"] is True
    assert audit["acceptance"]["unsafe_submission_evidence"] is False
    assert audit["acceptance"]["commands_with_submission_evidence"] == []
    assert audit["acceptance"]["commands_with_observed_submission_evidence"] == []
    assert audit["acceptance"]["stale_sources_refreshed_or_downranked"] is True
    source_quality = next(
        result for result in audit["commands"] if result["name"] == "source_quality_review"
    )
    assert source_quality["attention_samples"][0] == {
        "type": "source_decision",
        "source_name": "unknown_blog",
        "path": "results/research_evidence/blog.json",
        "quality": "low",
        "freshness_status": "stale",
        "blocked": True,
        "role": None,
        "reason": "blocked source should be sampled",
    }
    assert (tmp_path / "audit" / "real-simulation-audit-20260603-050000.json").exists()
    assert (tmp_path / "audit" / "real-simulation-audit-20260603-050000.md").exists()
    assert (tmp_path / "audit" / "latest.json").exists()
    saved = json.loads((tmp_path / "audit" / "latest.json").read_text(encoding="utf-8"))
    assert saved["json_path"].endswith("real-simulation-audit-20260603-050000.json")
    assert saved["markdown_path"].endswith("real-simulation-audit-20260603-050000.md")
    assert all(call_env["TRADINGAGENTS_MAC_RESEARCH_MODEL"] == "deepseek-r1:14b" for _, call_env in calls)
    assert all(call_env["TRADINGAGENTS_MAC_OLLAMA_URL"].endswith(":11434/v1") for _, call_env in calls)
    assert any(command[:2] == [sys.executable, "-m"] for command, _ in calls)


def test_real_simulation_audit_accepts_core_path_when_optional_mac_helper_is_down(tmp_path):
    def fake_runner(command, *, cwd, env, timeout):
        joined = " ".join(command)
        if "process-review" in joined:
            stdout = json.dumps(_fresh_process_review_payload())
        else:
            stdout = json.dumps(
                {
                    "analysis_only": True,
                    "can_submit_orders": False,
                    "submitted": [],
                    "blockers": [],
                    "packet_path": "results/example.json",
                }
            )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    audit = run_real_simulation_audit(
        repo_root=tmp_path,
        output_dir=tmp_path / "audit",
        top_symbols=["KO"],
        command_runner=fake_runner,
        now_id="20260603-051000",
        mac_probe_result=_mac_unavailable_probe(),
    )

    assert audit["acceptance"]["core_accepted"] is True
    assert audit["acceptance"]["accepted"] is True
    assert audit["acceptance"]["mac_deepseek_available"] is False
    assert audit["acceptance"]["optional_helper_degraded"] is True
    assert (
        audit["acceptance"]["optional_helper_degradation_reason"]
        == "mac_deepseek_helper_unreachable_or_missing"
    )
    assert audit["acceptance"]["strict_optional_model_accepted"] is False


@pytest.mark.parametrize(
    ("evidence_payload", "no_orders_expected"),
    [
        ({"submitted_count": 1}, False),
        ({"submitted": [{"symbol": "ORCL", "side": "sell"}]}, False),
        ({"live_order_submitted": True}, True),
        ({"submit_capable": True}, True),
        ({"checks": [{"name": "broker_order_probe", "status": "warn", "message": "live order submitted unexpectedly"}]}, True),
        (
            {
                "decision": "loss-review",
                "actions": [
                    {
                        "action": "sell",
                        "side": "sell",
                        "account": "live",
                        "symbol": "AMZN",
                        "reason": "loss review triggered by moving average breach",
                    }
                ],
                "evidence": {"loss_exit_review": {"allowed": False}},
            },
            True,
        ),
    ],
)
def test_real_simulation_audit_rejects_submission_evidence(tmp_path, evidence_payload, no_orders_expected):
    def fake_runner(command, *, cwd, env, timeout):
        joined = " ".join(command)
        if "source-quality-review" in joined:
            stdout = json.dumps({**{"analysis_only": True, "can_submit_orders": False}, **evidence_payload})
        else:
            stdout = json.dumps(
                {
                    "analysis_only": True,
                    "can_submit_orders": False,
                    "submitted": [],
                    "packet_path": "results/example.json",
                }
            )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    audit = run_real_simulation_audit(
        repo_root=tmp_path,
        output_dir=tmp_path / "audit",
        top_symbols=["ORCL"],
        command_runner=fake_runner,
        now_id="20260603-051500",
        mac_probe_result=_mac_available_probe(),
    )

    assert audit["unsafe_submission_evidence"] is True
    assert "source_quality_review" in audit["commands_with_submission_evidence"]
    evidence_command = next(
        result for result in audit["commands"] if result["name"] == "source_quality_review"
    )
    assert audit["acceptance"]["unsafe_submission_evidence"] is True
    assert audit["acceptance"]["commands_with_submission_evidence"] == ["source_quality_review"]
    assert audit["acceptance"]["accepted"] is False
    assert evidence_command["unsafe_submission_evidence"] is True
    assert audit["acceptance"]["no_orders_submitted"] is no_orders_expected


def test_real_simulation_audit_does_not_treat_stale_check_warning_as_submission(tmp_path):
    def fake_runner(command, *, cwd, env, timeout):
        joined = " ".join(command)
        if "verify-overnight-system" in joined:
            stdout = json.dumps(
                {
                    "analysis_only": True,
                    "can_submit_orders": False,
                    "checks": [
                        {
                            "name": "simulated_preopen_validation",
                            "status": "warn",
                            "summary": "Latest overnight packet is stale; rerun validation.",
                        }
                    ],
                    "submitted": [],
                    "packet_path": "results/overnight_system_verification/example.json",
                }
            )
        else:
            stdout = json.dumps(
                {
                    "analysis_only": True,
                    "can_submit_orders": False,
                    "submitted": [],
                    "packet_path": "results/example.json",
                }
            )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    audit = run_real_simulation_audit(
        repo_root=tmp_path,
        output_dir=tmp_path / "audit",
        top_symbols=["ORCL"],
        command_runner=fake_runner,
        now_id="20260603-051700",
        mac_probe_result=_mac_available_probe(),
    )

    overnight = next(
        result for result in audit["commands"] if result["name"] == "overnight_system_verification"
    )

    assert overnight["submission_evidence"] == []
    assert overnight["unsafe_submission_evidence"] is False
    assert audit["unsafe_submission_evidence"] is False
    assert audit["commands_with_submission_evidence"] == []


def test_real_simulation_audit_allows_hold_loss_review_without_sell_action(tmp_path):
    def fake_runner(command, *, cwd, env, timeout):
        joined = " ".join(command)
        if "supervise-hourly" in joined:
            stdout = json.dumps(
                {
                    "analysis_only": True,
                    "can_submit_orders": False,
                    "decision": "loss-review",
                    "actions": [],
                    "submitted": [],
                    "evidence": {
                        "loss_exit_review": {
                            "allowed": False,
                            "blocked_reasons": ["missing thesis evidence"],
                        }
                    },
                    "packet_path": "results/hourly_supervisor/example.json",
                }
            )
        else:
            stdout = json.dumps(
                {
                    "analysis_only": True,
                    "can_submit_orders": False,
                    "submitted": [],
                    "packet_path": "results/example.json",
                }
            )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    audit = run_real_simulation_audit(
        repo_root=tmp_path,
        output_dir=tmp_path / "audit",
        top_symbols=["ORCL"],
        command_runner=fake_runner,
        now_id="20260603-052000",
        mac_probe_result=_mac_available_probe(),
    )

    hourly = next(
        result for result in audit["commands"] if result["name"] == "hourly_supervisor_live_data_dry_run"
    )
    assert hourly["submission_evidence"] == []
    assert hourly["unsafe_submission_evidence"] is False
    assert audit["unsafe_submission_evidence"] is False
    assert audit["commands_with_submission_evidence"] == []


def test_real_simulation_audit_flags_exit0_without_structured_output_as_unaccepted(tmp_path):
    """A --json-output department that exits 0 but prints non-JSON must not pass as clean.

    Regression for the fake-success blind spot: status was derived solely from the
    exit code, so a department printing a human sentence and returning 0 was counted
    as clean structured evidence and the whole audit was 'accepted'.
    """

    def fake_runner(command, *, cwd, env, timeout):
        joined = " ".join(command)
        if "source-quality-review" in joined:
            # Exits 0 but emits a human sentence instead of the requested JSON packet.
            return subprocess.CompletedProcess(command, 0, stdout="All good. No issues found.\n", stderr="")
        stdout = json.dumps(
            {
                "analysis_only": True,
                "can_submit_orders": False,
                "submitted": [],
                "packet_path": "results/example.json",
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    audit = run_real_simulation_audit(
        repo_root=tmp_path,
        output_dir=tmp_path / "audit",
        top_symbols=["NOW"],
        command_runner=fake_runner,
        now_id="20260604-090000",
        mac_probe_result=_mac_available_probe(),
    )

    sqr = next(result for result in audit["commands"] if result["name"] == "source_quality_review")
    assert sqr["exit_code"] == 0
    assert sqr["expected_structured_output"] is True
    assert sqr["structured_output_ok"] is False
    assert "source_quality_review" in audit["commands_missing_structured_output"]
    assert audit["acceptance"]["all_structured_output_present"] is False
    # The blind spot is closed: exit-0-without-JSON is no longer silently accepted.
    assert audit["acceptance"]["accepted"] is False
    # A clean JSON department in the same run still reports structured output ok.
    other = next(result for result in audit["commands"] if result["name"] == "process_review")
    assert other["structured_output_ok"] is True


def test_real_simulation_audit_rejects_stale_process_review_packet(tmp_path):
    def fake_runner(command, *, cwd, env, timeout):
        joined = " ".join(command)
        if "process-review" in joined:
            stdout = json.dumps(
                {
                    "generated_at": "2000-01-01T00:00:00+00:00",
                    "unchecked_step_count": 0,
                    "can_submit_orders": False,
                    "json_path": "results/process_reviews/process-review-old.json",
                }
            )
        else:
            stdout = json.dumps(
                {
                    "analysis_only": True,
                    "can_submit_orders": False,
                    "submitted": [],
                    "packet_path": "results/example.json",
                }
            )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    audit = run_real_simulation_audit(
        repo_root=tmp_path,
        output_dir=tmp_path / "audit",
        top_symbols=["ORCL"],
        command_runner=fake_runner,
        now_id="20260603-052300",
        mac_probe_result=_mac_available_probe(),
    )

    process_review = next(result for result in audit["commands"] if result["name"] == "process_review")
    assert process_review["process_review_freshness"]["required"] is True
    assert process_review["process_review_freshness"]["ok"] is False
    assert process_review["process_review_freshness"]["reason"] == "process_review older than 900s"
    assert audit["stale_process_review_commands"] == ["process_review"]
    assert audit["acceptance"]["process_review_fresh"] is False
    assert audit["acceptance"]["stale_process_review_commands"] == ["process_review"]
    assert audit["acceptance"]["accepted"] is False


def test_real_simulation_audit_separates_observer_historical_submissions(tmp_path):
    def fake_runner(command, *, cwd, env, timeout):
        joined = " ".join(command)
        if "automation-health-audit" in joined:
            stdout = json.dumps(
                {
                    "kind": "tradingagents_automation_health_audit",
                    "analysis_only": True,
                    "can_submit_orders": False,
                    "submitted_order_count": 1,
                    "summary": {
                        "missing_count": 0,
                        "partial_count": 0,
                        "late_count": 0,
                        "duplicate_count": 0,
                        "stale_count": 0,
                        "warning_count": 1,
                        "timeliness_issue_count": 0,
                    },
                    "json_path": "results/automation_health/latest.json",
                }
            )
        elif "process-review" in joined:
            stdout = json.dumps(_fresh_process_review_payload())
        else:
            stdout = json.dumps(
                {
                    "analysis_only": True,
                    "can_submit_orders": False,
                    "submitted": [],
                    "packet_path": "results/example.json",
                }
            )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    audit = run_real_simulation_audit(
        repo_root=tmp_path,
        output_dir=tmp_path / "audit",
        top_symbols=["ORCL"],
        command_runner=fake_runner,
        now_id="20260603-052500",
        mac_probe_result=_mac_available_probe(),
    )

    automation_health = next(
        result for result in audit["commands"] if result["name"] == "automation_health_audit"
    )
    assert automation_health["submitted_order_count"] == 0
    assert automation_health["observed_submission_count"] == 1
    assert automation_health["unsafe_submission_evidence"] is False
    assert audit["total_submitted_order_count"] == 0
    assert audit["total_observed_submission_count"] == 1
    assert audit["commands_with_submission_evidence"] == []
    assert audit["commands_with_observed_submission_evidence"] == ["automation_health_audit"]
    assert audit["acceptance"]["no_orders_submitted"] is True
    assert audit["acceptance"]["unsafe_submission_evidence"] is False
    assert audit["acceptance"]["accepted"] is True
