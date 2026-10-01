# TradingAgents Agent Guide

## Canonical Workspace

The canonical repository and working directory is:

`/Users/corbinfloyd/Documents/TradingAgents`

Start every TradingAgents Codex chat from this directory. The Python application,
Git history, local environment, runtime evidence, documentation, and recovery
archives all live beneath this root.

## Session Start

1. Run `pwd` and `git status --short --branch`.
2. Read `START_HERE.md` for workspace identity, then the source or guidance relevant to the task.
3. For runtime, operational, or safety-sensitive work, read
   `results/_context/latest-summary.json` and `results/_context/latest-flags.json`.
   Open only the raw packet named by compact context when a flag calls for detail.
4. When the authorized task needs a context refresh, use
   `.venv/bin/python scripts/automation_context_snapshot.py --write` only if those
   files are missing or stale, or the task changes the runtime/generated-packet
   inputs they summarize; then reread them. A read-only audit does not require a write.
5. Consult only the relevant section of `CONTEXT_ROUTER.md` for historical
   operational context. Its dated status is not current authority.

`results/_context/` is the fast index to runtime state. Timestamped files under
`results/` support it. Source-only work retains the safety-fingerprint practice
below without loading unrelated operational history.

## Repository Map

| Area | Purpose |
| --- | --- |
| `cli/main.py` | Typer command surface for Alpaca, research, evaluation, and operations |
| `tradingagents/agents/` | Analyst, researcher, trader, and risk-role implementations |
| `tradingagents/graph/` | LangGraph workflow construction and propagation |
| `tradingagents/brokers/` | Alpaca integration, supervisor decisions, and paper tournament |
| `tradingagents/policy/` | Live control, approval records, risk posture, gates, and policy packets |
| `tradingagents/execution/` | Execution locks, clocks, reconciliation, and submit coordination |
| `tradingagents/research/` | Provider orchestration, evidence packets, crawlers, and research workflows |
| `tradingagents/orchestration/` | n8n runner, job policy, context control, and automation plumbing |
| `tradingagents/dataflows/` | Market, fundamentals, news, social, and vendor data routes |
| `tradingagents/evals/` | Decision quality, telemetry, calibration, and evaluation datasets |
| `tests/` | Unit and integration coverage organized by subsystem |
| `scripts/mac/` | Mac launchd jobs, runner wrappers, and outbox delivery |
| `config/` | Versioned examples, allowlists, schedules, and local runtime configuration |
| `results/` | Generated runtime packets, compact context, logs, locks, and evidence |
| `docs/` | Architecture, policy, orchestration, plans, and project history |
| `archive/` | Recovery manifests, inactive checkout archives, and Windows transfer history |

The detailed map and consolidation record live in
`docs/consolidation/REPOSITORY_MAP.md` and
`docs/consolidation/CONSOLIDATION_REPORT.md`.

## Task Routing

- CLI behavior starts at `cli/main.py`, then follows the called subsystem and
  its matching `tests/test_*_cli.py` coverage.
- Trading decisions start at `tradingagents/brokers/alpaca_supervisor.py` and
  continue through `tradingagents/policy/` and `tradingagents/execution/`.
- Research behavior starts at `tradingagents/research/provider_orchestrator.py`,
  `tradingagents/research/automation_orchestrator.py`, and the relevant dataflow.
- Agent workflow changes start at `tradingagents/graph/trading_graph.py` and the
  matching role implementation under `tradingagents/agents/`.
- n8n jobs start at `tradingagents/orchestration/n8n_runner.py` and
  `config/n8n_tradingagents_allowlist.json`.
- Runtime investigations start with compact context, then the named raw packet,
  broker history, active process state, and current configuration.

Use direct reads and `rg` for prose, configuration, logs, JSON packets, exact
strings, and small source questions. Structural tooling such as codebase-memory
is optional when it helps trace relationships; verify its indexed root and
coverage, then confirm behavior in source. Reuse a known index rather than
repeatedly listing the catalog. Consult architecture for service boundaries,
schema guidance for data changes, and release guidance for release work.

## Mac Commands

```zsh
cd /Users/corbinfloyd/Documents/TradingAgents
.venv/bin/python -m cli.main --help
.venv/bin/python -m cli.main alpaca --help
.venv/bin/python scripts/automation_context_snapshot.py --write
.venv/bin/python -m pytest -q
.venv/bin/ruff check cli tradingagents scripts tests
```

The complete pytest and Ruff commands are broad checkpoint gates, not per-edit
defaults. Use the smallest affected test group while a behavior slice is changing.

The local n8n runner listens on `127.0.0.1:8765`. Its launchd configuration and
wrapper point to this repository root. The ten Codex schedules are the canonical
timetable, defined by
`config/automation_schedule_contract.json`. All remain paused during readiness
work. `scripts/mac/ta_job.sh` supplies the bounded job commands; the legacy
`scripts/mac/install_launchd.sh` is retired and cannot install a second timetable.

## Configuration and Evidence

Keep research memory in local redacted packets. Zep remains disabled by the
settled project decision; re-enable it only if the user explicitly changes that
decision. This does not require a new memory service for ordinary work.

Local credentials live in `.env` with mode `0600`. Local risk configuration may
live in ignored configuration files. Versioned example files describe expected
shape. Current operational state comes from the live files on disk, active
process state, broker order history, and newest result packets.

`results/policy/live_control.json` records the current live-control posture.
Submission authority is established by the complete current policy and execution
path at call time. Analysis packets, historical statuses, and documentation
provide context for that evaluation.

For source-only work that cannot invoke a runtime, automation, or broker action,
capture one compact safety fingerprint for the candidate revision and reuse it
while the relevant control files, automation state, processes, and diff are
unchanged. Recheck after a relevant change, immediately before any protected
operation, and at the checkpoint. Reuse never substitutes for the complete
call-time submission-authority path.

## Change and Verification Practice

Continue authorized local implementation through inspection, relevant checks,
and repairs until its acceptance criteria are met. Pause only dependent work
for missing evidence, access, a consequential unresolved decision, or separate
protected-operation authority; complete useful independent work.

Use representative tests for changed behavior and demonstrated failures. For
prose and simple configuration, read back the result and review the diff. Reuse
passing evidence on unchanged inputs. Run affected checks after relevant source
changes and one complete repository gate on the final integrated candidate;
diagnose failures and rerun the checks needed by the repair. Root is the sole
implementer and verifier for the current readiness program and performs a
separate self-review pass.

Keep durable test output and exit receipts independent of the client output
pipe. Preserve failed receipts. Use hashes for immutable source custody,
checkpoint identity, recovery integrity, and required protected-operation checks;
avoid adding hash manifests for ordinary prose, successful logs, or repeated
unchanged-state observations. Report concise outcomes and failures. Refresh
compact context when summarized runtime/generated-packet inputs change; a new
index timestamp does not make stale runtime evidence current. Refresh a useful
structural index after substantial source changes when subsequent work needs it.

## Optional Ox Alpha Help

Use Ox only when the user explicitly requests it. Read
`/Users/corbinfloyd/.codex/references/opencode-ox.md` for the current route,
compatibility preflight, and safety boundaries. Keep one writer per worktree and
one owner of affected tests for a revision; inspect the resulting diff and
focused evidence.

Keep source, tests, and durable documentation in Git. Keep generated results,
credentials, environments, caches, and recovery archives in their established
ignored locations. Record important verification commands and outcomes in the
relevant report or plan.

## History and Recovery

The canonical `master` branch contains the consolidated active implementation.
Former development lines remain available as Git branches. Complete recovery
archives for retired checkouts and the imported public clone live under
`archive/inactive-checkouts/`. Windows transfer material lives under
`archive/windows-transfer-2026-07-11/`.

## Completion Handoff

Report the result, changed paths, verification evidence, current runtime posture,
and the next useful starting file. Use exact absolute paths for workspace handoff
and relative paths for files inside this repository.

## Current readiness work

Follow the current missing-work table in
`docs/superpowers/plans/2026-08-30-tradingagents-evidence-first-working-state-completion.md`.
Keep its research, economic, learning, and six-session acceptance requirements.
Live control stays frozen, all ten automations stay paused, concurrency stays at
1, and paper submission defaults to off. Holdout release, optional submission,
model execution, and additional external operations retain their own established
authority scope. The completed SEC/Alpaca collection needs no renewed approval.
