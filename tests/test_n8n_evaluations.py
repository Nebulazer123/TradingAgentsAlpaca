import csv
import json
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.orchestration.n8n_api_sync import (
    load_n8n_api_key_from_sqlite,
    sync_n8n_evaluation_data_table,
)
from tradingagents.orchestration.n8n_evaluation_run_probe import (
    probe_n8n_builtin_evaluation_run,
)
from tradingagents.orchestration.n8n_evaluations import (
    build_compact_n8n_evaluation_dataset,
    build_n8n_evaluation_dataset,
    write_n8n_evaluation_dataset,
)
from tradingagents.orchestration.n8n_policy import load_n8n_allowlist
from tradingagents.orchestration.n8n_workflow_sync import sync_n8n_workflows

runner = CliRunner()


def test_n8n_evaluation_dataset_covers_all_allowlisted_jobs_with_edge_cases():
    jobs = load_n8n_allowlist()
    dataset = build_n8n_evaluation_dataset(jobs)

    rows = dataset["rows"]
    by_job = {row["job"] for row in rows if row["case_type"] == "live_runner"}
    edge_tags = {
        tag
        for row in rows
        for tag in row["edge_tags"].split(",")
        if tag
    }

    assert dataset["schema_version"] == 1
    assert dataset["row_count"] >= 120
    assert set(jobs) <= by_job
    assert dataset["automation_count"] >= len(jobs)
    assert all(row["expected_submit_capable"] is False for row in rows)
    assert all(row["expected_can_submit_orders"] is False for row in rows)
    assert all(row["expected_compact_output_only"] is True for row in rows)
    assert all(json.loads(row["request_json"]) for row in rows)
    assert {
        "blocked",
        "changed_candidate",
        "duplicate_evidence",
        "malformed_json",
        "missing_packet",
        "no_live_submit",
        "self_heal_late",
        "stale_data",
        "timeout",
        "unknown_job",
    } <= edge_tags
    assert any(
        row["job"] == "overnight_calibration_guard"
        and row["scenario"] == "duplicate_evidence_deduped_before_scoring"
        and row["metric_rule"] == "duplicate_symbol_as_of_rows_are_skipped_before_calibration"
        for row in rows
    )


def test_n8n_evaluation_dataset_rows_are_data_table_friendly(tmp_path: Path):
    packet = write_n8n_evaluation_dataset(output_dir=tmp_path)

    json_path = Path(packet["json_path"])
    csv_path = Path(packet["csv_path"])
    markdown_path = Path(packet["markdown_path"])
    compact_path = json_path.with_suffix(".compact.json")

    assert json_path.exists()
    assert csv_path.exists()
    assert markdown_path.exists()
    assert compact_path.exists()
    assert (tmp_path / "latest-compact.json").exists()

    saved = json.loads(json_path.read_text(encoding="utf-8"))
    compact = json.loads(compact_path.read_text(encoding="utf-8"))
    latest_compact = json.loads((tmp_path / "latest-compact.json").read_text(encoding="utf-8"))
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert saved["row_count"] == len(rows)
    assert compact == latest_compact
    assert compact["raw_packet_path"] == packet["json_path"]
    assert compact["row_count"] == packet["row_count"]
    assert "rows" not in compact
    assert "actual_status" in compact["column_names"]
    assert "case_id" in rows[0]
    assert "expected_status" in rows[0]
    assert "metric_rule" in rows[0]
    assert rows[0]["request_json"].startswith("{")
    assert rows[0]["expected_json"].startswith("{")


def test_n8n_evaluation_dataset_has_actual_output_columns_for_set_outputs():
    packet = build_n8n_evaluation_dataset()
    columns = {column["name"] for column in packet["columns"]}

    assert {
        "actual_http_status",
        "actual_status",
        "actual_json",
        "actual_quality_score",
        "actual_checked_at",
        "actual_error",
    } <= columns
    assert all(row["actual_http_status"] == "" for row in packet["rows"])
    assert all(row["actual_status"] == "" for row in packet["rows"])
    assert all(row["actual_json"] == "" for row in packet["rows"])
    assert all(row["actual_quality_score"] == "" for row in packet["rows"])
    assert all(row["actual_checked_at"] == "" for row in packet["rows"])
    assert all(row["actual_error"] == "" for row in packet["rows"])


def test_source_controlled_n8n_builtin_evaluation_workflow_uses_native_eval_nodes():
    workflow_path = Path("n8n/workflows/ta-built-in-automation-evaluation.json")

    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    nodes = workflow["nodes"]
    node_types = {node["type"] for node in nodes}
    evaluation_nodes = [
        node for node in nodes if node["type"] == "n8n-nodes-base.evaluation"
    ]

    assert workflow["id"] == "taBuiltInAutomationEvaluation"
    assert workflow["active"] is False
    assert "n8n-nodes-base.evaluationTrigger" in node_types
    assert "n8n-nodes-base.httpRequest" in node_types
    assert "n8n-nodes-base.code" in node_types
    assert len(evaluation_nodes) == 2
    assert {node["parameters"]["operation"] for node in evaluation_nodes} == {
        "setOutputs",
        "setMetrics",
    }

    set_outputs = next(
        node for node in evaluation_nodes if node["parameters"]["operation"] == "setOutputs"
    )
    output_names = {
        item["outputName"]
        for item in set_outputs["parameters"]["outputs"]["values"]
    }
    assert {
        "actual_http_status",
        "actual_status",
        "actual_json",
        "actual_quality_score",
        "actual_checked_at",
        "actual_error",
    } <= output_names

    set_metrics = next(
        node for node in evaluation_nodes if node["parameters"]["operation"] == "setMetrics"
    )
    metric_names = {
        item["name"]
        for item in set_metrics["parameters"]["metrics"]["assignments"]
    }
    assert {
        "http_status_match",
        "status_match",
        "compact_contract_match",
        "no_submit_contract_match",
        "safety_contract_score",
    } <= metric_names
    assert "--submit-actions" not in json.dumps(workflow)


def test_source_controlled_n8n_builtin_evaluation_workflow_runs_full_dataset():
    workflow_path = Path("n8n/workflows/ta-built-in-automation-evaluation.json")
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))

    trigger = next(
        node
        for node in workflow["nodes"]
        if node["type"] == "n8n-nodes-base.evaluationTrigger"
    )

    assert trigger["parameters"]["source"] == "dataTable"
    assert trigger["parameters"].get("limitRows") is False
    assert "maxRows" not in trigger["parameters"]


def test_source_controlled_observer_workflows_run_ledger_update_before_labels():
    overnight_path = Path("n8n/workflows/ta-overnight-planner-observer.json")
    after_close_path = Path("n8n/workflows/ta-after-close-supervisor-observer.json")
    overnight = json.loads(overnight_path.read_text(encoding="utf-8"))
    after_close = json.loads(after_close_path.read_text(encoding="utf-8"))

    overnight_names = [node["name"] for node in overnight["nodes"]]
    after_close_names = [node["name"] for node in after_close["nodes"]]

    assert "agent_ledger_update" in overnight_names
    assert "agent_ledger_summary" in overnight_names
    assert overnight_names.index("agent_ledger_update") < overnight_names.index(
        "agent_ledger_summary"
    )
    assert "agent_ledger_update" in after_close_names
    assert "agent_ledger_summary" in after_close_names
    assert "outcome_labeling" in after_close_names
    assert after_close_names.index("agent_ledger_update") < after_close_names.index(
        "agent_ledger_summary"
    )
    assert after_close_names.index("agent_ledger_summary") < after_close_names.index(
        "outcome_labeling"
    )
    assert "--submit-actions" not in json.dumps(overnight)
    assert "--submit-actions" not in json.dumps(after_close)


def test_compact_n8n_evaluation_dataset_points_to_full_artifacts(tmp_path: Path):
    packet = write_n8n_evaluation_dataset(output_dir=tmp_path)
    compact = build_compact_n8n_evaluation_dataset(packet)

    assert compact["schema"] == "compact_n8n_evaluation_dataset_v1"
    assert compact["analysis_only"] is True
    assert compact["can_submit_orders"] is False
    assert compact["execution_authority"] == "none"
    assert compact["raw_packet_path"] == packet["json_path"]
    assert compact["csv_path"] == packet["csv_path"]
    assert compact["markdown_path"] == packet["markdown_path"]
    assert compact["row_count"] == packet["row_count"]
    assert compact["allowlisted_job_count"] == packet["allowlisted_job_count"]
    assert "stale_data" in compact["edge_tags"]
    assert "rows" not in compact
    assert compact["raw_field_groups"]["full_rows"] == "rows"


def test_n8n_allowlist_exposes_evaluation_and_compact_audit_jobs():
    jobs = load_n8n_allowlist()

    evaluation = jobs["n8n_evaluation_dataset"]
    compact_audit = jobs["compact_output_audit"]
    daily = jobs["daily_report_preview"]
    overnight = jobs["overnight_plan_compact_preview"]
    orchestration = jobs["research_automation_orchestration_plan"]
    premarket = jobs["premarket_brief_compact_preview"]
    hourly = jobs["hourly_supervisor_dry_run_preview"]
    automation_health = jobs["automation_health_audit"]

    assert evaluation.submit_capable is False
    assert evaluation.compact_output_only is True
    assert "n8n-evaluation-dataset" in evaluation.commands[0]
    assert "--json-output" in evaluation.commands[0]
    assert "--compact-json-output" in evaluation.commands[0]

    assert compact_audit.submit_capable is False
    assert compact_audit.compact_output_only is True
    assert "compact-output-audit" in compact_audit.commands[0]
    assert "--json-output" in compact_audit.commands[0]

    assert "--compact-json-output" in daily.commands[0]
    assert "source-quality-review" in overnight.commands[0]
    assert "--compact-json-output" in overnight.commands[0]
    assert "plan-overnight" in overnight.commands[1]
    assert "--compact-json-output" in overnight.commands[1]
    assert "--no-write-latest" in overnight.commands[1]
    assert "--no-agent-ledger" in overnight.commands[1]
    # The observer preview now runs with research context enabled (read-only);
    # write-latest and agent-ledger stay disabled so it cannot mutate state.
    assert "--full-graph-tickers" in overnight.commands[1]
    assert orchestration.submit_capable is False
    assert orchestration.compact_output_only is True
    assert "automation-orchestration-plan" in orchestration.commands[0]
    assert "--no-research-context" in orchestration.commands[0]
    assert "--json-output" in orchestration.commands[0]
    assert "--submit-actions" not in orchestration.commands[0]
    assert "--compact-json-output" in premarket.commands[0]
    assert "--no-write-latest" in premarket.commands[0]
    assert "--compact-json-output" in hourly.commands[0]
    assert "--dry-run" in hourly.commands[0]
    assert "--submit-actions" not in hourly.commands[0]
    assert "--compact-json-output" in automation_health.commands[0]


def test_n8n_list_jobs_cli_exposes_allowlisted_jobs():
    result = runner.invoke(app, ["research", "n8n-list-jobs", "--json-output"])

    assert result.exit_code == 0
    packet = json.loads(result.output)
    by_name = {job["name"]: job for job in packet["jobs"]}
    assert packet["schema_version"] == 1
    assert packet["submit_capable_count"] == 0
    assert "context_snapshot" in by_name
    assert "n8n_evaluation_dataset" in by_name
    assert "preopen_validation_preview" in by_name
    assert by_name["context_snapshot"]["submit_capable"] is False
    assert by_name["context_snapshot"]["compact_output_only"] is True


class FakeN8NDataTableClient:
    def __init__(self):
        self.tables: list[dict] = []
        self.columns: list[dict] = []
        self.rows: list[dict] = [{"case_id": "old_case"}]
        self.deleted = False
        self.insert_calls: list[list[dict]] = []

    def list_data_tables(self, *, name: str | None = None):
        return [table for table in self.tables if table["name"] == name]

    def create_data_table(self, *, name: str, columns: list[dict[str, str]]):
        self.tables.append({"id": "table-1", "name": name})
        self.columns.extend(
            {"id": f"col-{index}", "name": column["name"], "type": column["type"]}
            for index, column in enumerate(columns)
        )
        return self.tables[0]

    def list_columns(self, table_id: str):
        assert table_id == "table-1"
        return self.columns

    def create_column(self, table_id: str, *, name: str, column_type: str, index: int | None = None):
        assert table_id == "table-1"
        column = {"id": f"col-{len(self.columns)}", "name": name, "type": column_type, "index": index}
        self.columns.append(column)
        return column

    def list_rows(self, table_id: str, *, limit: int = 250):
        assert table_id == "table-1"
        return self.rows

    def delete_all_rows(self, table_id: str):
        assert table_id == "table-1"
        self.deleted = True
        self.rows = []
        return True

    def insert_rows(self, table_id: str, rows: list[dict], *, return_type: str = "count"):
        assert table_id == "table-1"
        assert return_type == "count"
        self.insert_calls.append(rows)
        self.rows.extend(rows)
        return {"count": len(rows)}


class FakeN8NWorkflowClient:
    def __init__(self):
        self.workflows: list[dict] = [
            {
                "id": "old-sync-1",
                "name": "TA · Sync Evaluation Dataset",
                "active": False,
            },
            {
                "id": "old-sync-2",
                "name": "TA · Sync Evaluation Dataset",
                "active": False,
            },
            {
                "id": "builtin",
                "name": "TA · Built-in Automation Evaluation",
                "active": False,
            },
        ]
        self.created: list[dict] = []
        self.updated: list[dict] = []

    def list_workflows(self):
        return list(self.workflows)

    def create_workflow(self, payload: dict):
        created = dict(payload)
        created["id"] = f"created-{len(self.created) + 1}"
        self.created.append(created)
        self.workflows.append(
            {
                "id": created["id"],
                "name": created["name"],
                "active": created.get("active", False),
            }
        )
        return created

    def update_workflow(self, workflow_id: str, payload: dict):
        updated = dict(payload)
        updated["id"] = workflow_id
        self.updated.append(updated)
        return updated


class FakeN8NEvaluationRunProbeClient:
    def __init__(self, workflows: list[dict] | None = None, statuses: list[int] | None = None):
        self.workflows = workflows or [
            {
                "id": "wf-builtin",
                "name": "TA · Built-in Automation Evaluation",
                "active": False,
            }
        ]
        self.statuses = statuses or [404, 404, 401]
        self.probed_paths: list[str] = []

    def list_workflows(self):
        return list(self.workflows)

    def probe(self, method: str, path: str, payload: dict | None = None):
        self.probed_paths.append(path)
        index = len(self.probed_paths) - 1
        status = self.statuses[min(index, len(self.statuses) - 1)]
        return {
            "method": method,
            "path": path,
            "http_status": status,
            "response_preview": f"HTTP {status}",
            "supported": 200 <= status < 300,
        }


def test_n8n_evaluation_run_probe_records_editor_required_when_public_routes_absent(tmp_path: Path):
    client = FakeN8NEvaluationRunProbeClient(statuses=[404, 404, 401])

    result = probe_n8n_builtin_evaluation_run(
        client=client,
        api_key_source="unit-test:redacted",
        output_dir=tmp_path,
    )

    assert result["status"] == "editor_required"
    assert result["analysis_only"] is True
    assert result["can_submit_orders"] is False
    assert result["execution_authority"] == "none"
    assert result["api_key_redacted"] is True
    assert result["workflow_id"] == "wf-builtin"
    assert result["editor_run_required"] is True
    assert result["supported_endpoint_count"] == 0
    assert result["probe_count"] >= 3
    assert {
        "/workflows/wf-builtin/test-runs",
        "/workflows/wf-builtin/test-runs/new",
    } <= set(client.probed_paths)
    proof = json.loads((tmp_path / "latest-run-probe.json").read_text(encoding="utf-8"))
    assert proof["status"] == "editor_required"
    assert "apiKey" not in json.dumps(proof)


def test_n8n_evaluation_run_probe_marks_editor_required_as_accepted_gate(tmp_path: Path):
    client = FakeN8NEvaluationRunProbeClient(statuses=[404, 405, 404, 405])

    result = probe_n8n_builtin_evaluation_run(
        client=client,
        api_key_source="unit-test:redacted",
        output_dir=tmp_path,
    )

    assert result["status"] == "editor_required"
    assert result["accepted_as_current_gate"] is True
    assert result["sanctioned_run_surface"] == "n8n_editor_evaluations_ui"
    assert result["acceptance"]["accepted"] is True
    assert result["acceptance"]["editor_required_accepted"] is True
    assert result["acceptance"]["api_trigger_supported"] is False
    assert "editor/evaluations UI" in result["acceptance_reason"]
    assert result["analysis_only"] is True
    assert result["can_submit_orders"] is False
    assert result["execution_authority"] == "none"
    assert result["api_key_redacted"] is True


def test_n8n_evaluation_run_probe_detects_supported_api_trigger(tmp_path: Path):
    client = FakeN8NEvaluationRunProbeClient(statuses=[404, 200, 404])

    result = probe_n8n_builtin_evaluation_run(
        client=client,
        api_key_source="unit-test:redacted",
        output_dir=tmp_path,
    )

    assert result["status"] == "api_trigger_available"
    assert result["editor_run_required"] is False
    assert result["supported_endpoint_count"] == 1
    assert any(probe["supported"] for probe in result["probes"])


def test_n8n_evaluation_run_probe_reports_missing_workflow_without_probing(tmp_path: Path):
    client = FakeN8NEvaluationRunProbeClient(workflows=[{"id": "other", "name": "Other"}])

    result = probe_n8n_builtin_evaluation_run(
        client=client,
        api_key_source="unit-test:redacted",
        output_dir=tmp_path,
    )

    assert result["status"] == "missing_workflow"
    assert result["editor_run_required"] is True
    assert result["workflow_id"] is None
    assert result["probe_count"] == 0
    assert client.probed_paths == []


def test_n8n_api_sync_replaces_rows_and_writes_redacted_proof(tmp_path: Path):
    client = FakeN8NDataTableClient()
    packet = build_n8n_evaluation_dataset()

    result = sync_n8n_evaluation_data_table(
        client=client,
        api_key_source="unit-test:redacted",
        packet=packet,
        output_dir=tmp_path,
        insert_chunk_size=25,
    )

    assert result["status"] == "ok"
    assert result["analysis_only"] is True
    assert result["can_submit_orders"] is False
    assert result["execution_authority"] == "none"
    assert result["api_key_redacted"] is True
    assert result["api_key_source"] == "unit-test:redacted"
    assert result["expected_row_count"] == packet["row_count"]
    assert result["final_row_count"] == packet["row_count"]
    assert result["row_count_matches"] is True
    assert client.deleted is True
    assert len(client.insert_calls) > 1
    proof = json.loads((tmp_path / "latest-sync.json").read_text(encoding="utf-8"))
    assert proof["api_key_redacted"] is True
    assert "apiKey" not in json.dumps(proof)


def test_n8n_api_sync_writes_same_dataset_that_it_syncs(tmp_path: Path):
    client = FakeN8NDataTableClient()

    result = sync_n8n_evaluation_data_table(
        client=client,
        api_key_source="unit-test:redacted",
        output_dir=tmp_path,
        insert_chunk_size=25,
    )

    dataset = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    compact = json.loads((tmp_path / "latest-compact.json").read_text(encoding="utf-8"))
    proof = json.loads((tmp_path / "latest-sync.json").read_text(encoding="utf-8"))

    assert result["dataset_generated_at"] == dataset["generated_at"]
    assert proof["dataset_generated_at"] == dataset["generated_at"]
    assert compact["generated_at"] == dataset["generated_at"]
    assert proof["expected_row_count"] == dataset["row_count"]
    assert proof["final_row_count"] == dataset["row_count"]
    assert proof["api_key_redacted"] is True
    assert "apiKey" not in json.dumps(proof)


def test_n8n_workflow_sync_creates_missing_source_workflows_inactive(tmp_path: Path):
    workflow_a = tmp_path / "sync-observer.json"
    workflow_a.write_text(
        json.dumps(
            {
                "name": "TA · Sync Evaluation Dataset (observer)",
                "active": True,
                "nodes": [],
                "connections": {},
                "settings": {"executionOrder": "v1"},
            }
        ),
        encoding="utf-8",
    )
    workflow_b = tmp_path / "builtin.json"
    workflow_b.write_text(
        json.dumps(
            {
                "id": "taBuiltInAutomationEvaluation",
                "name": "TA · Built-in Automation Evaluation",
                "active": True,
                "nodes": [],
                "connections": {},
                "settings": {"executionOrder": "v1"},
            }
        ),
        encoding="utf-8",
    )
    client = FakeN8NWorkflowClient()

    result = sync_n8n_workflows(
        client=client,
        workflow_paths=[workflow_a, workflow_b],
        api_key_source="unit-test:redacted",
        output_dir=tmp_path,
    )

    assert result["status"] == "ok"
    assert result["analysis_only"] is True
    assert result["can_submit_orders"] is False
    assert result["execution_authority"] == "none"
    assert result["api_key_redacted"] is True
    assert result["source_workflow_count"] == 2
    assert result["source_workflow_names"] == [
        "TA · Sync Evaluation Dataset (observer)",
        "TA · Built-in Automation Evaluation",
    ]
    assert result["created_count"] == 1
    assert result["existing_count"] == 1
    assert result["updated_count"] == 1
    assert result["duplicate_name_counts"] == {"TA · Sync Evaluation Dataset": 2}
    assert client.created[0]["name"] == "TA · Sync Evaluation Dataset (observer)"
    assert client.created[0].get("active", False) is False
    assert client.updated[0]["id"] == "builtin"
    assert client.updated[0]["name"] == "TA · Built-in Automation Evaluation"
    assert client.updated[0].get("active", False) is False
    proof = json.loads((tmp_path / "latest-workflow-sync.json").read_text(encoding="utf-8"))
    assert proof["created_count"] == 1
    assert proof["updated_count"] == 1
    assert "apiKey" not in json.dumps(proof)


def test_n8n_workflow_sync_ignores_archived_duplicate_names_for_current_audit(
    tmp_path: Path,
):
    workflow_path = tmp_path / "sync-dataset.json"
    workflow_path.write_text(
        json.dumps(
            {
                "name": "TA · Sync Evaluation Dataset",
                "active": True,
                "nodes": [],
                "connections": {},
                "settings": {"executionOrder": "v1"},
            }
        ),
        encoding="utf-8",
    )
    client = FakeN8NWorkflowClient()
    client.workflows = [
        {
            "id": "current-sync",
            "name": "TA · Sync Evaluation Dataset",
            "active": False,
            "isArchived": False,
        },
        {
            "id": "archived-sync",
            "name": "TA · Sync Evaluation Dataset",
            "active": False,
            "isArchived": True,
        },
    ]

    result = sync_n8n_workflows(
        client=client,
        workflow_paths=[workflow_path],
        api_key_source="unit-test:redacted",
        output_dir=tmp_path,
    )

    assert result["status"] == "ok"
    assert result["existing_count"] == 1
    assert result["updated_count"] == 1
    assert result["current_workflow_count"] == 1
    assert result["archived_workflow_count"] == 1
    assert result["duplicate_name_counts"] == {}
    assert result["archived_duplicate_name_counts"] == {
        "TA · Sync Evaluation Dataset": 2
    }
    assert client.updated[0]["id"] == "current-sync"


def test_load_n8n_api_key_from_sqlite_reports_source_without_printing_key(tmp_path: Path):
    db_path = tmp_path / "database.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            'CREATE TABLE user_api_keys ("label" varchar, "apiKey" varchar, "scopes" text)'
        )
        conn.execute(
            'INSERT INTO user_api_keys ("label", "apiKey", "scopes") VALUES (?, ?, ?)',
            ("Docker", "n8n-secret-key", "[]"),
        )

    key, source = load_n8n_api_key_from_sqlite(db_path)

    assert key == "n8n-secret-key"
    assert source == "sqlite:database.sqlite:label:Docker"
    assert "n8n-secret-key" not in source


def test_n8n_sync_cli_missing_api_key_returns_redacted_blocker(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "research",
            "n8n-sync-evaluation-table",
            "--api-key-env",
            "TRADINGAGENTS_TEST_MISSING_N8N_API_KEY",
            "--output-dir",
            str(tmp_path),
            "--json-output",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked_missing_api_key"
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["execution_authority"] == "none"
    assert payload["api_key_redacted"] is True
    assert payload["expected_row_count"] >= 120
    assert payload["json_path"]
    assert payload["csv_path"]
    assert payload["markdown_path"]
    assert "missing n8n API key" in payload["error"]
    assert "TRADINGAGENTS_TEST_MISSING_N8N_API_KEY" in payload["remediation"]
    assert "apiKey" not in result.stdout
