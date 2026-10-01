---
name: ta-runtime-diagnosis
description: Diagnose TradingAgents runtime, job, scheduler, broker-evidence, or recovery failures using current controls and compact packet references.
---

# Runtime diagnosis

Read existing `results/_context/latest-summary.json` and `latest-flags.json`.
Follow the specific packet or failure needed by the task; check its source time.
Refresh the index only when missing/stale or when summarized inputs changed.

Trace the affected command from `cli/main.py` into its subsystem. For jobs, use
`tradingagents/orchestration/n8n_runner.py`, `scripts/mac/ta_job.sh`, and
`config/n8n_tradingagents_allowlist.json`. For schedules, compare actual records
with `config/automation_schedule_contract.json` using the existing health audit.
The contract evaluates deployment evidence; the scheduler's status controls
execution. An audit pass does not activate a schedule.

Reproduce defects with local fixtures or retained evidence. Apply in-scope
observer repairs and verify the changed behavior. Lock cleanup needs evidence
that the owning process is gone; inspect `tradingagents/orchestration/self_heal.py`
for existing recovery recipes. New broker/provider reads, service changes, and
control writes require the task's applicable authority.

When a consequential boundary is involved, read `docs/harness/BOUNDARIES.md`
and trace the current call path. Report the causal finding, repair, direct check,
and exact unresolved dependency. Link packets when they support that finding;
unchanged global state needs no recital.
