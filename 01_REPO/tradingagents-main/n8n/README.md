# Local n8n for TradingAgents (read-only observer)

This sets up a real, self-hosted n8n on your machine so you can **log in and see
the workflows visually**. n8n here is only an observer: it calls an allowlisted
local runner and can never place trades, move money, or read secrets.

## 1. Start n8n

```powershell
docker compose --profile n8n up -d n8n
```

Then open **http://localhost:5678**.

## 2. Create your login (first run only)

n8n shows a "Set up owner account" screen the first time. Enter **any email and a
password you choose**. This account is stored only on your machine, in the
`n8n_data` Docker volume. It is not an online account and not tied to this repo.
If you were ever asked to log in at `app.n8n.io`, that was n8n's cloud product,
which this setup does not use.

## 3. Start the runner bridge (so workflows can actually run)

The workflows call a small local HTTP bridge that runs only allowlisted,
non-submitting jobs:

```powershell
.\.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --host 127.0.0.1 --port 8765
```

Leave that running. From inside the n8n container the bridge is reachable at
`http://host.docker.internal:8765/run` (already set in the observer workflow
files). The full n8n evaluation dataset is available at
`http://host.docker.internal:8765/evaluation-dataset`.

## 4. Import the 12 observer/evaluation workflows

Either drag each file in `n8n/workflows/` into the n8n canvas
(**Workflows → Import from File**), or run the CLI import:

```powershell
docker cp n8n/workflows/. n8n:/tmp/ta-workflows
docker exec n8n n8n import:workflow --separate --input=/tmp/ta-workflows
docker restart n8n
```

Regenerate the workflow files anytime with:

```powershell
node n8n/generate-workflows.mjs
```

## What the workflows do

Each workflow is a manual trigger chained through one or more **read-only** jobs
(`POST /run` with `{"job": "<name>"}`). The jobs map to the allowlist in
`config/n8n_tradingagents_allowlist.json`; all are `submit_capable: false`.

| Workflow | Jobs called |
| --- | --- |
| Hourly Supervisor | context_snapshot, execution_board_review |
| Paper Tournament | context_snapshot, agent_ledger_summary |
| Overnight Planner | context_snapshot, creator_workflow_status, source_quality_review, agent_ledger_update, agent_ledger_summary |
| Pre-Open Supervisor | pre_open_context_refresh, source_quality_review |
| Post-Open Supervisor | context_snapshot, execution_board_review |
| Pre-Close Supervisor | context_snapshot, execution_board_review |
| After-Close Supervisor | context_snapshot, agent_ledger_update, agent_ledger_summary, outcome_labeling |
| Daily Report Preview | daily_report_preview |
| Health + Self-Heal | automation_health_audit, self_heal_plan |

## Built-in n8n evaluations

The repo produces a Data Table-ready dataset for n8n's built-in evaluations and
can sync that dataset into the local n8n Data Table through n8n's public API.

- Data Table name: `TradingAgents_Automation_Evaluations`, 23 columns.
- Dataset endpoint: `http://host.docker.internal:8765/evaluation-dataset`.
- Source-controlled observer workflows:
  - `TA · Sync Evaluation Dataset (observer)`
  - `TA · Automation Evaluations (observer)`
- Source-controlled built-in evaluation workflow:
  - `TA · Built-in Automation Evaluation`
  - Uses n8n's native `Evaluation Trigger`, `Evaluation` Set Outputs, and
    `Evaluation` Set Metrics nodes.
- API sync command:
  `research n8n-sync-evaluation-table --json-output`.
- Workflow sync command:
  `research n8n-sync-workflows --json-output`.

Generate the repo-side dataset anytime with:

```powershell
.\.venv\Scripts\tradingagents.exe research n8n-evaluation-dataset --json-output --compact-json-output
```

Sync the current dataset into n8n through the public API by setting
`N8N_API_KEY` or by passing a copied local n8n SQLite DB path. The key is never
printed; the proof packet records only the redacted source.

```powershell
.\.venv\Scripts\tradingagents.exe research n8n-sync-evaluation-table --json-output
```

Sync source-controlled observer workflows into the local n8n instance with:

```powershell
.\.venv\Scripts\tradingagents.exe research n8n-sync-workflows --json-output
```

The latest dataset has 243 rows across 24 allowlisted jobs, 18 edge tags, and
23 columns, including writable actual-output fields for n8n Set Outputs:
`actual_http_status`, `actual_status`, `actual_json`, `actual_quality_score`,
`actual_checked_at`, and `actual_error`. It covers stale data, blocked packets,
missing packets, abnormal P/L, self-heal timing, timeouts, and forbidden-job
negative cases, plus the overnight calibration guard, loss-review evidence,
MiroFish handoff, safe self-heal, and Agent Intelligence ledger observers. The compact CLI
proof points to
`results\n8n_evaluations\n8n-evaluation-dataset-20260607-165419-208322.json`.
The sync proof is written to `results\n8n_evaluations\latest-sync.json` when an
API key is available; the latest local Data Table API sync proof is
`results\n8n_evaluations\n8n-api-sync-20260607-165753-318068.json` with
`expected_row_count=243`, `final_row_count=243`, `row_count_matches=true`,
`column_count=23`, and `api_key_redacted=true`; it used a temporary copied n8n
SQLite database only to read the existing API key, then deleted that copy. The
latest local workflow sync
proof is `results\n8n_evaluations\n8n-workflow-sync-20260607-165802-734061.json`;
it updated 12 inactive source-controlled workflows in the local dashboard.
`results\_context\latest-summary.json` summarizes
the dataset, Data Table sync, workflow sync proof, and native run-probe proof under
`n8n_evaluation_dataset`, so agents should open raw n8n packets only when
compact context reports missing actual-output columns, failed sync, row
mismatch, missing workflow sync proof, failed key redaction, or a broken native
run probe.
If `N8N_API_KEY` is missing, the sync command returns a redacted
`blocked_missing_api_key` JSON packet and fresh dataset paths instead of a
traceback. To use the local SQLite key source, copy the n8n container database
to a temporary folder, pass that copy with `--api-key-sqlite-db`, and delete the
temporary copy after the proof packet is written.

n8n's Data Table and Evaluation Trigger nodes are editor/runtime dependent. The
source-controlled built-in workflow imports into the local container; proof:
`n8n list:workflow` returned
`taBuiltInAutomationEvaluation|TA · Built-in Automation Evaluation`. CLI
execution is still not the acceptance gate for this workflow: `n8n execute`
while the dashboard is running can hit the task-broker port, and even with a
separate broker port n8n reports `Missing node to start execution` because an
Evaluation Trigger is not an Execute Workflow Trigger. After logging into
`http://localhost:5678`, run `TA · Built-in Automation Evaluation` from the n8n
editor/evaluations UI.

The repo can record that boundary with:

```powershell
.\.venv\Scripts\tradingagents.exe research n8n-evaluation-run-probe --json-output
```

An authenticated public-API probe using a temporary copied SQLite API key wrote
`results\n8n_evaluations\n8n-evaluation-run-probe-20260607-165811-433546.json`.
It found workflow `taBuiltInAutomationEvaluation`, but every public run route
was unsupported: `/test-runs` returned `405`, `/test-runs/new` returned `404`,
`/run` returned `405`, and `/execute` returned `405`. The packet status is
`editor_required`, `supported_endpoint_count=0`, `can_submit_orders=false`, and
`api_key_redacted=true`. This means the remaining native n8n evaluation run is
an editor/evaluations UI action, not a repo runner, public API, or CLI action.
The run probe is intentionally a direct CLI/context proof rather than an
allowlisted n8n runner job, because it needs an API-key source and n8n should
not be forced to own or pass that secret.

The latest local dashboard sync verification was run on 2026-06-07 while the
Docker container `tradingagents-main-n8n-1` was up on `localhost:5678` and the
allowlisted runner bridge was reachable on `127.0.0.1:8765`.

The observer workflows remain inactive by default because they are dashboard and
test/evaluation helpers, not production schedules.

## Safety

The n8n policy layer (`tradingagents/orchestration/n8n_policy.py`) rejects any job
that is not on the allowlist or that looks broker-capable. n8n never receives
Alpaca credentials. Stopping n8n is safe: `docker compose --profile n8n stop n8n`.
