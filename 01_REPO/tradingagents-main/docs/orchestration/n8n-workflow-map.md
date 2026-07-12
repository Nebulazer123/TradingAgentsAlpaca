# n8n Workflow Map For TradingAgents

Use n8n as a wrapper, dashboard, notification, manual-trigger, and evaluation
control plane around this Python repo. Do not use n8n as the owner of strategy
logic, Alpaca execution, paper tournament scoring, Agent Intelligence Ledger
resolution, BOARD decisions, live-control state, or live-submit gates.

## Execution Bridge

n8n may call only the repo-local allowlisted runner:

```powershell
.\.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job <job_name> --json
```

For a local HTTP bridge:

```powershell
.\.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --serve --host 127.0.0.1 --port 8765
```

If n8n runs in Docker, its Execute Command node runs inside the container, not
on the Windows host. Docker n8n should call the host runner through
`host.docker.internal:8765`; host n8n may invoke the module directly. n8n does
not receive Alpaca credentials or arbitrary shell access.

## Compact Context Rule

Workflows read `results/_context/latest-summary.json` and
`results/_context/latest-flags.json` first. Full packets are opened only when
compact flags identify a reason:

- submitted actions
- blockers or policy issues
- stale data or stale source-quality flags
- changed candidates or paper tournament leader
- failed graph/model runs
- abnormal P/L, exposure, or drawdown
- changed MiroFish handoff status
- self-heal or automation-health failure
- schema mismatch or packet parse failure

## Workflow Map

| Workflow | Trigger | n8n jobs | n8n owns | Python repo owns |
| --- | --- | --- | --- | --- |
| Status dashboard | Frequent light heartbeat/manual | `context_snapshot`, `process_review`, `automation_health_audit` | Display compact status, packet links, stale flags, unchecked plan count | Context writer, process review, automation evidence |
| Hourly supervisor observer | Hourly/manual | `context_snapshot`, `hourly_supervisor_dry_run_preview`, `execution_board_review` | Show dry-run decision, issues, BOARD status | Real supervisor, broker checks, submit gates |
| Paper tournament observer | Hourly/manual | `context_snapshot`, `agent_ledger_summary` | Show paper leaders, strategy scorecards, AlphaInsider shadow status | Paper execution, tournament scoring, promotion candidates |
| Overnight dashboard preview | Night/manual | `context_snapshot`, `overnight_plan_compact_preview`, `source_quality_review`, `creator_workflow_status`, `agent_ledger_summary` | Show source freshness, bounded preview, original workflow status | Real overnight planner, original TradingAgents graph, ledger writes |
| Pre-open observer | Market morning | `pre_open_context_refresh`, `premarket_brief_compact_preview`, `preopen_validation_preview` | Show MiroFish readiness, stale checks, account/context summaries | Broker validation, premarket brief, safety decisions |
| Post-open/pre-close/after-close observer | Market checkpoints | `context_snapshot`, `execution_board_review`, optional `outcome_labeling` | Surface actionability, P/L changes, unresolved issues | Buy/sell decisions, loss review, exposure/risk logic |
| Daily report preview | After close/manual | `daily_report_preview` | Preview short human-readable report | Report rendering, account summaries, blocker wording |
| Self-heal monitor | Flag-driven/manual | `self_heal_handoff`, `self_heal_plan`, optional `self_heal_execute_safe` | Expose safe-plane plan and verified/escalated counts | Code edits, tests, credentials, orders, schedules |
| n8n evaluation dataset | Manual/editor | `n8n_evaluation_dataset` | Sync or display dataset rows for n8n native evals | Dataset generation, policy rules, acceptance packets |
| Emergency inspection | Manual only | `context_snapshot`, `process_review`, `execution_board_review` | Show current state and inspection points | Any freeze, order, or remediation decision |

## Phased Path

Phase 0: n8n observes through the allowlisted runner and compact context only.
This is the current mainline posture.

Phase 1: n8n dashboard/manual workflows may be imported, kept inactive by
default, and wired to the runner. All allowlisted jobs stay
`submit_capable=false`.

Phase 2: read-only connector/MCP enrichment can be added only as curated repo
jobs that activate when compact flags say enrichment is needed. Do not expose a
broad all-tools MCP surface to n8n.

Phase 3: selected schedules may move to n8n only after observation has been
stable and explicitly approved. Even then, n8n calls existing repo commands; it
does not replace Python automations.

Do not move live submission logic, live-control state, risk gates, paper scoring,
Agent Intelligence resolution, or BOARD decisions into n8n.

## Smallest Proof Of Concept

Build the status dashboard first:

1. Manual Trigger.
2. HTTP Request to `/run` with `{"job":"context_snapshot"}`.
3. HTTP Request to `/run` with `{"job":"process_review"}`.
4. HTTP Request to `/run` with `{"job":"automation_health_audit"}`.
5. Render compact status, latest packet paths, stale flags, unchecked plan count,
   and next inspection point.
6. Notify only for blockers, submitted actions, changed candidates, abnormal
   P/L/exposure, failed graph/model runs, or source-quality failures.

Success means n8n can observe the repo clearly without direct broker authority,
arbitrary shell access, or full-packet token bloat.

