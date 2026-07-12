"""n8n built-in evaluation dataset generation for TradingAgents automations."""

from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any

from tradingagents.orchestration.n8n_policy import N8NJob, load_n8n_allowlist

N8N_EVALUATION_DOCS_URL = "https://docs.n8n.io/advanced-ai/evaluations/overview/"
N8N_LIGHT_EVAL_DOCS_URL = "https://docs.n8n.io/advanced-ai/evaluations/light-evaluations/"
N8N_METRIC_EVAL_DOCS_URL = (
    "https://docs.n8n.io/advanced-ai/evaluations/metric-based-evaluations/"
)

DATASET_COLUMNS: tuple[tuple[str, str], ...] = (
    ("case_id", "string"),
    ("automation", "string"),
    ("job", "string"),
    ("case_type", "string"),
    ("scenario", "string"),
    ("edge_tags", "string"),
    ("request_json", "string"),
    ("expected_json", "string"),
    ("expected_http_status", "number"),
    ("expected_status", "string"),
    ("expected_submit_capable", "boolean"),
    ("expected_compact_output_only", "boolean"),
    ("expected_can_submit_orders", "boolean"),
    ("expected_tools", "string"),
    ("metric_rule", "string"),
    ("min_quality_score", "number"),
    ("notes", "string"),
    ("actual_http_status", "number"),
    ("actual_status", "string"),
    ("actual_json", "string"),
    ("actual_quality_score", "number"),
    ("actual_checked_at", "string"),
    ("actual_error", "string"),
)

JOB_AUTOMATION_LABELS: dict[str, str] = {
    "agent_ledger_summary": "after-close supervisor / paper tournament",
    "agent_ledger_update": "after-close supervisor / overnight planner",
    "automation_health_audit": "status dashboard / health check",
    "compact_output_audit": "token efficiency audit",
    "context_snapshot": "all automations",
    "creator_workflow_status": "overnight planner",
    "daily_report_preview": "daily report",
    "execution_board_review": "BOARD department",
    "loss_review_evidence": "BOARD department / loss-review evidence",
    "hourly_supervisor_dry_run_preview": "hourly supervisor",
    "mirofish_handoff_status": "pre-open supervisor / MiroFish handoff",
    "n8n_evaluation_dataset": "n8n evaluation harness",
    "overnight_plan_compact_preview": "overnight planner",
    "outcome_labeling": "after-close supervisor",
    "premarket_brief_compact_preview": "pre-open supervisor / premarket brief preview",
    "pre_open_context_refresh": "pre-open supervisor",
    "process_review": "status dashboard / process eval",
    "self_heal_execute_safe": "self-heal safe executor",
    "self_heal_handoff": "self-heal monitor",
    "self_heal_plan": "self-heal planner",
    "source_quality_review": "research source-quality department",
}

SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "scenario": "nominal_current_state",
        "edge_tags": ("nominal", "no_live_submit"),
        "metric_rule": "runner_status_ok_and_safe_shape",
        "notes": "The allowlisted job returns a compact, parseable observer result.",
    },
    {
        "scenario": "compact_output_contract",
        "edge_tags": ("compact_output", "no_live_submit"),
        "metric_rule": "compact_output_only_true_and_stdout_bounded",
        "notes": "The runner output stays compact and points to repo artifacts instead of dumping raw packets.",
    },
    {
        "scenario": "blocked_packet_present",
        "edge_tags": ("blocked", "no_live_submit"),
        "metric_rule": "blocker_count_visible_without_submit_authority",
        "notes": "If a raw packet contains blockers, n8n should surface counts and links only.",
    },
    {
        "scenario": "stale_data_refresh_or_downrank",
        "edge_tags": ("stale_data", "source_quality", "no_live_submit"),
        "metric_rule": "stale_sources_are_refreshed_or_downranked",
        "notes": "Stale evidence should become a dashboard/eval signal, not trade authority.",
    },
    {
        "scenario": "duplicate_evidence_deduped_before_scoring",
        "edge_tags": ("duplicate_evidence", "source_quality", "no_live_submit"),
        "metric_rule": "duplicate_symbol_as_of_rows_are_skipped_before_calibration",
        "notes": (
            "Duplicate overnight symbol/as-of evidence should be counted as "
            "skipped provenance, not as extra scored calibration rows."
        ),
    },
    {
        "scenario": "missing_packet_or_latest_pointer",
        "edge_tags": ("missing_packet", "context_gap", "no_live_submit"),
        "metric_rule": "missing_packet_is_reported_not_silently_ignored",
        "notes": "Missing latest files must be explicit and bounded in the compact output.",
    },
    {
        "scenario": "changed_candidate_or_paper_leader",
        "edge_tags": ("changed_candidate", "changed_paper_leader", "no_live_submit"),
        "metric_rule": "changed_candidates_trigger_raw_packet_reason",
        "notes": "Changed candidates are dashboard reasons to inspect raw packets.",
    },
    {
        "scenario": "abnormal_pl_or_exposure",
        "edge_tags": ("abnormal_pl", "exposure_change", "no_live_submit"),
        "metric_rule": "abnormal_risk_state_is_visible_and_non_submitting",
        "notes": "P/L and exposure surprises should be obvious without allowing order submission.",
    },
    {
        "scenario": "self_heal_timeliness",
        "edge_tags": ("self_heal_late", "failure_bus", "no_live_submit"),
        "metric_rule": "self_heal_handoff_followed_by_plan_or_escalation",
        "notes": "Self-heal monitor cases check handoff -> plan -> execute-safe timing.",
    },
    {
        "scenario": "runner_timeout_or_slow_command",
        "edge_tags": ("timeout", "failure_bus", "no_live_submit"),
        "metric_rule": "timeout_is_bounded_and_classified",
        "notes": "Timeouts should fail closed with compact stderr, not hang the dashboard.",
    },
)

NEGATIVE_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "negative_unknown_job",
        "automation": "n8n runner policy",
        "job": "submit_live_now",
        "case_type": "negative_runner",
        "scenario": "unknown_or_forbidden_job",
        "edge_tags": "unknown_job,no_live_submit",
        "request_json": json.dumps({"job": "submit_live_now"}, sort_keys=True),
        "expected_http_status": 400,
        "expected_status": "not_allowlisted",
        "metric_rule": "forbidden_job_rejected",
        "notes": "n8n must not be able to request a broker-like job by name.",
    },
    {
        "case_id": "negative_empty_job",
        "automation": "n8n runner policy",
        "job": "",
        "case_type": "negative_runner",
        "scenario": "empty_job_request",
        "edge_tags": "unknown_job,malformed_json,no_live_submit",
        "request_json": json.dumps({"job": ""}, sort_keys=True),
        "expected_http_status": 400,
        "expected_status": "not_allowlisted",
        "metric_rule": "empty_job_rejected",
        "notes": "Blank requests must fail closed instead of running a default job.",
    },
    {
        "case_id": "negative_malformed_body",
        "automation": "n8n runner policy",
        "job": "__malformed_json__",
        "case_type": "negative_runner",
        "scenario": "malformed_json_body",
        "edge_tags": "malformed_json,no_live_submit",
        "request_json": json.dumps(
            {"job": "__malformed_json__", "request_mode": "invalid_json"},
            sort_keys=True,
        ),
        "expected_http_status": 400,
        "expected_status": "not_allowlisted",
        "metric_rule": "malformed_request_rejected_or_errored",
        "notes": "The workflow can use request_mode to test invalid request bodies in n8n.",
    },
)


def _expected_json(*, job: N8NJob, expected_status: str = "ok") -> str:
    expected = {
        "status": expected_status,
        "submit_capable": False,
        "compact_output_only": True,
        "can_submit_orders": False,
        "required_fields": [
            "schema_version",
            "job",
            "status",
            "submit_capable",
            "compact_output_only",
            "steps",
        ],
        "job_timeout_seconds": job.timeout_seconds,
    }
    return json.dumps(expected, sort_keys=True)


def _base_row(
    *,
    job: N8NJob,
    case_index: int,
    scenario: dict[str, Any],
) -> dict[str, str | int | float | bool]:
    slug = str(scenario["scenario"])
    edge_tags = ",".join(str(tag) for tag in scenario["edge_tags"])
    request = {
        "job": job.name,
        "case_id": f"{job.name}_{case_index:02d}_{slug}",
        "scenario": slug,
        "edge_tags": edge_tags,
    }
    return {
        "case_id": request["case_id"],
        "automation": JOB_AUTOMATION_LABELS.get(job.name, job.name.replace("_", " ")),
        "job": job.name,
        "case_type": "live_runner",
        "scenario": slug,
        "edge_tags": edge_tags,
        "request_json": json.dumps(request, sort_keys=True),
        "expected_json": _expected_json(job=job),
        "expected_http_status": 200,
        "expected_status": "ok",
        "expected_submit_capable": False,
        "expected_compact_output_only": True,
        "expected_can_submit_orders": False,
        "expected_tools": "n8n_evaluation_trigger,n8n_evaluation_node,http_runner",
        "metric_rule": str(scenario["metric_rule"]),
        "min_quality_score": 1.0,
        "notes": str(scenario["notes"]),
        "actual_http_status": "",
        "actual_status": "",
        "actual_json": "",
        "actual_quality_score": "",
        "actual_checked_at": "",
        "actual_error": "",
    }


def _negative_row(raw: dict[str, Any]) -> dict[str, str | int | float | bool]:
    expected = {
        "status": raw["expected_status"],
        "submit_capable": False,
        "compact_output_only": True,
        "can_submit_orders": False,
    }
    return {
        "case_id": str(raw["case_id"]),
        "automation": str(raw["automation"]),
        "job": str(raw["job"]),
        "case_type": str(raw["case_type"]),
        "scenario": str(raw["scenario"]),
        "edge_tags": str(raw["edge_tags"]),
        "request_json": str(raw["request_json"]),
        "expected_json": json.dumps(expected, sort_keys=True),
        "expected_http_status": int(raw["expected_http_status"]),
        "expected_status": str(raw["expected_status"]),
        "expected_submit_capable": False,
        "expected_compact_output_only": True,
        "expected_can_submit_orders": False,
        "expected_tools": "n8n_evaluation_trigger,n8n_evaluation_node,http_runner",
        "metric_rule": str(raw["metric_rule"]),
        "min_quality_score": 1.0,
        "notes": str(raw["notes"]),
        "actual_http_status": "",
        "actual_status": "",
        "actual_json": "",
        "actual_quality_score": "",
        "actual_checked_at": "",
        "actual_error": "",
    }


def build_n8n_evaluation_dataset(
    jobs: dict[str, N8NJob] | None = None,
) -> dict[str, Any]:
    """Build a Data Table-ready dataset for n8n built-in evaluations."""
    allowlisted = jobs if jobs is not None else load_n8n_allowlist()
    rows: list[dict[str, str | int | float | bool]] = []
    for job in sorted(allowlisted.values(), key=lambda item: item.name):
        for index, scenario in enumerate(SCENARIOS, start=1):
            rows.append(_base_row(job=job, case_index=index, scenario=scenario))
    rows.extend(_negative_row(raw) for raw in NEGATIVE_CASES)

    edge_tags = sorted(
        {
            tag
            for row in rows
            for tag in str(row["edge_tags"]).split(",")
            if tag
        }
    )
    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="seconds"),
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "evaluation_target": "TradingAgents allowlisted n8n automation wrappers",
        "n8n_docs": {
            "overview": N8N_EVALUATION_DOCS_URL,
            "light_evaluations": N8N_LIGHT_EVAL_DOCS_URL,
            "metric_based_evaluations": N8N_METRIC_EVAL_DOCS_URL,
        },
        "column_count": len(DATASET_COLUMNS),
        "columns": [{"name": name, "type": column_type} for name, column_type in DATASET_COLUMNS],
        "row_count": len(rows),
        "automation_count": len({row["automation"] for row in rows}),
        "allowlisted_job_count": len(allowlisted),
        "edge_tag_count": len(edge_tags),
        "edge_tags": edge_tags,
        "data_table_name": "TradingAgents_Automation_Evaluations",
        "rows": rows,
    }


def build_compact_n8n_evaluation_dataset(packet: dict[str, Any]) -> dict[str, Any]:
    """Build a compact stdout-safe summary for the n8n evaluation dataset."""

    scenario_counts: dict[str, int] = {}
    job_counts: dict[str, int] = {}
    for row in packet.get("rows") or []:
        if not isinstance(row, dict):
            continue
        scenario = str(row.get("scenario") or "unknown")
        job = str(row.get("job") or "unknown")
        scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1
        job_counts[job] = job_counts.get(job, 0) + 1

    column_names = [
        str(column.get("name"))
        for column in packet.get("columns") or []
        if isinstance(column, dict) and column.get("name")
    ]

    return {
        "schema": "compact_n8n_evaluation_dataset_v1",
        "schema_version": packet.get("schema_version"),
        "generated_at": packet.get("generated_at"),
        "analysis_only": bool(packet.get("analysis_only")),
        "can_submit_orders": bool(packet.get("can_submit_orders")),
        "execution_authority": packet.get("execution_authority"),
        "evaluation_target": packet.get("evaluation_target"),
        "raw_packet_path": packet.get("json_path"),
        "json_path": packet.get("json_path"),
        "csv_path": packet.get("csv_path"),
        "markdown_path": packet.get("markdown_path"),
        "data_table_name": packet.get("data_table_name"),
        "row_count": int(packet.get("row_count") or 0),
        "column_count": int(packet.get("column_count") or 0),
        "column_names": column_names,
        "automation_count": int(packet.get("automation_count") or 0),
        "allowlisted_job_count": int(packet.get("allowlisted_job_count") or 0),
        "edge_tag_count": int(packet.get("edge_tag_count") or 0),
        "edge_tags": list(packet.get("edge_tags") or []),
        "scenario_counts": scenario_counts,
        "job_case_counts": job_counts,
        "n8n_docs": dict(packet.get("n8n_docs") or {}),
        "raw_field_groups": {
            "full_rows": "rows",
            "columns": "columns",
        },
    }


def _render_dataset_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# TradingAgents n8n Evaluation Dataset",
        "",
        f"Generated: {packet['generated_at']}",
        "",
        f"- Rows: {packet['row_count']}",
        f"- Allowlisted jobs: {packet['allowlisted_job_count']}",
        f"- Automations: {packet['automation_count']}",
        f"- Edge tags: {', '.join(packet['edge_tags'])}",
        "",
        "This dataset is designed for n8n's built-in Evaluation Trigger and Evaluation nodes. "
        "It covers observer jobs, negative runner-policy cases, compact-output contracts, "
        "source-quality/stale-data signals, self-heal timing, and timeout/failure-bus cases.",
        "",
        "| Scenario | Cases |",
        "| --- | ---: |",
    ]
    scenario_counts: dict[str, int] = {}
    for row in packet["rows"]:
        scenario = str(row["scenario"])
        scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1
    for scenario, count in sorted(scenario_counts.items()):
        lines.append(f"| {scenario} | {count} |")
    return "\n".join(lines) + "\n"


def write_n8n_evaluation_dataset(
    *,
    output_dir: Path = Path("results/n8n_evaluations"),
    jobs: dict[str, N8NJob] | None = None,
) -> dict[str, Any]:
    """Write the n8n evaluation dataset as JSON, CSV, and Markdown."""
    packet = build_n8n_evaluation_dataset(jobs)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    stem = f"n8n-evaluation-dataset-{generated_at}"
    json_path = output_dir / f"{stem}.json"
    csv_path = output_dir / f"{stem}.csv"
    markdown_path = output_dir / f"{stem}.md"

    packet["json_path"] = str(json_path)
    packet["csv_path"] = str(csv_path)
    packet["markdown_path"] = str(markdown_path)

    json_text = json.dumps(packet, indent=2)
    json_path.write_text(json_text, encoding="utf-8")
    (output_dir / "latest.json").write_text(json_text, encoding="utf-8")

    compact = build_compact_n8n_evaluation_dataset(packet)
    compact_text = json.dumps(compact, indent=2)
    compact_path = output_dir / f"{stem}.compact.json"
    compact_path.write_text(compact_text, encoding="utf-8")
    (output_dir / "latest-compact.json").write_text(compact_text, encoding="utf-8")

    fieldnames = [name for name, _column_type in DATASET_COLUMNS]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(packet["rows"])
    (output_dir / "latest.csv").write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")

    markdown = _render_dataset_markdown(packet)
    markdown_path.write_text(markdown, encoding="utf-8")
    (output_dir / "latest.md").write_text(markdown, encoding="utf-8")
    return packet
