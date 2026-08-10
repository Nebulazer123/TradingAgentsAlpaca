# Codex Packet — Agent Intelligence Wiring Chores (2026-06-10)

Origin: Fable Pass 2 (`2026-06-10-fable-pass2-agent-intelligence-brainstem.md`).
The brainstem is built and tested; these are the routine wiring chores around
it. Everything here is analysis-only: no packet may add order authority, and
every new payload must carry `analysis_only=true`, `can_submit_orders=false`,
`execution_authority="none"`.

Supersedes from `2026-06-09-codex-delegation-packets.md`: **Packet A is done**
(agent-intelligence context now flows into overnight research context —
`build_agent_intelligence_packet` in `tradingagents/research/overnight_context.py`).
Packets B–E below are restated against the new surface.

Shared verification baseline for every chore:

```powershell
cd "C:\Users\Corbin\Documents\Coding projects\TradingAgents-main"
uv run --no-sync python -m compileall -q cli tradingagents tests
uv run --no-sync --group static-analysis ruff check --select E9,F63,F7,F82 cli tradingagents tests
uv run --no-sync --with pytest python -m pytest tests/test_resolution_quality.py tests/test_agent_intelligence_ledger.py tests/test_hypothesis_factory.py tests/test_overnight_context.py -q
```

## Chore 1 — n8n allowlisted observer jobs

`config/n8n_tradingagents_allowlist.json`: add two jobs modeled on the
existing `agent_ledger_update` entry (~line 213), both `submit_capable=false`:

- `hypothesis_factory`: `python -m cli.main research hypothesis-factory --json-output`
- `ledger_quality_audit`: `python -m cli.main research ledger-quality-audit --json-output`

If `tradingagents/orchestration/n8n_policy.py` enumerates job kinds, register
both as observer-class. Tests in `tests/test_n8n_runner_policy.py`: discovery
includes the jobs; `submit_capable_count` stays 0; runner parses each payload.

Acceptance: `python -m tradingagents.orchestration.n8n_runner --run-job
hypothesis_factory --json` returns `status=ok`, `submit_capable=false`, and
`status_counts`; same for `ledger_quality_audit` with
`resolution_quality.label_quality_counts`.

## Chore 2 — Nightly chain: quality-audit → resolve → factory

`tradingagents/research/automation_orchestrator.py`: in the after-close
sequence, after `agent_ledger_update`, chain
`research ledger-quality-audit` → `research agent-ledger-resolve` →
`research hypothesis-factory`. Order matters: the audit heals
`window_unverifiable` labels as the price feed catches up, which is what
unlocks minable evidence for the factory the same night.

Note: `tests/test_real_simulation_audit.py` (~line 64) asserts
`agent_ledger_resolve` is NOT chained in the simulation audit (network calls).
Keep that exclusion for the simulation audit; the real nightly chain gets all
three steps. Document the decision in the test. Extend the orchestrator
ordering tests.

Acceptance: orchestration plan packet lists the steps in order with
`submit_capable=false`; focused tests pass.

## Chore 3 — Compact context surfacing

`scripts/automation_context_snapshot.py`: read
`results/agent_intelligence/resolution_quality.json`
(`label_quality_counts`, `defer_reason_counts`, `trusted_label_count`) and
`results/hypothesis_factory/summary.json` (`status_counts`, supported count);
add a compact block. Flag routes (open only when):

- `trusted_label_count` > 0 for the first time (mining just unlocked), or
- `supported` > 0 (a prior now exists and flows into overnight context), or
- due forecasts exist but newly-resolved has been 0 for >2 consecutive days
  AND `defer_reason_counts` is empty (a true stall, not a healthy deferral).

Tests: `tests/test_automation_context_snapshot.py` — block present, flag
logic both ways. Acceptance: `python scripts/automation_context_snapshot.py
--write` shows the block; no new flags open on today's state (132 suspect /
12 deferred is a healthy waiting state, not a stall).

## Chore 4 — Board + scoreboard bookkeeping

- `docs/superpowers/plans/2026-06-08-market-readiness-execution-board.md`:
  update the outcome-labeling rows — 2026-06-10: resolution-integrity layer
  shipped; retro-audit proved all 132 first-light labels were measured 1–2
  sessions short (all `suspect`/`final_bar_missing` pending feed catch-up);
  12 newly-due forecasts deferred instead of contaminated. Evidence:
  `results/agent_intelligence/quality-audit-20260610.json`,
  `results/agent_intelligence/second-resolution-20260610.json`,
  `results/hypothesis_factory/second-run-20260610.json`. Verification:
  the shared baseline above.
- `CONTEXT_ROUTER.md`: add a dated checkpoint entry per the existing format
  (outcome labeling now runs through the audited window path; quality-audit
  joins the daily cadence ahead of resolve+factory). Name the board ID per
  AGENTS.md rules.

## Chore 5 — CLI help + docs polish (low priority)

- `research ledger-quality-audit` / `agent-ledger-resolve` help text: mention
  the suspect→high healing behavior once bars land.
- `TRADING_METHODS_AND_AUTOMATIONS.md`: extend the agent-intelligence section
  with the three-command cadence and the label-quality tiers
  (`high`/`degraded`/`suspect`/unaudited; mining uses high+degraded only).

Out of scope for Codex (Fable-lane, do not attempt): changing audit rules,
grace periods, label-quality semantics, hypothesis epistemics, or anything
under `tradingagents/evals/resolution_quality.py` beyond what is listed.
