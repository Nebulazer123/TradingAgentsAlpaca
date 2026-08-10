# Codex Packets — Agent Intelligence Validation + Wiring (2026-06-11)

Origin: Fable Pass 3 (`2026-06-11-fable-pass3-agent-intelligence-restart.md`).
Pass 3 was authored in a session with **all process execution denied**, so
Packet 0 (validation) is mandatory and comes first. Everything here is
analysis-only: no packet may add order authority, and every new payload must
carry `analysis_only=true`, `can_submit_orders=false`,
`execution_authority="none"`.

Supersedes `2026-06-10-codex-packet-agent-intelligence-wiring.md` (its
chores 1–5 were never executed; they are restated below as Packets 2–5).

## Packet 0 — Validate pass 3 (MANDATORY FIRST)

```powershell
cd "C:\Users\Corbin\Documents\Coding projects\TradingAgents-main"
uv run --no-sync --with pytest python -m pytest tests/test_hypothesis_lifecycle.py tests/test_hypothesis_factory.py tests/test_agent_intelligence_brain.py tests/test_agent_variants.py tests/test_agent_intelligence_ledger.py tests/test_resolution_quality.py tests/test_overnight_context.py -q
uv run --no-sync python -m compileall -q cli tradingagents tests
uv run --no-sync --group static-analysis ruff check --select E9,F63,F7,F82 cli tradingagents tests
uv run --no-sync --group static-analysis ruff check tradingagents/evals/hypothesis_lifecycle.py tradingagents/evals/agent_intelligence_brain.py tradingagents/evals/agent_variants.py tests/test_hypothesis_lifecycle.py tests/test_agent_intelligence_brain.py tests/test_agent_variants.py
```

Fix small mechanical failures (imports, typos, exact-string assertion
drift) in place; if a failure looks semantic (event diffing, radar math,
flag logic), stop and report instead of redesigning. Acceptance: all listed
suites pass; compileall and ruff E9/F-class clean.

## Packet 1 — First lifecycle seed + brain artifact (run, don't code)

After Packet 0, run the cadence in this order and archive payloads:

```powershell
uv run --no-sync python -m cli.main research ledger-quality-audit --json-output
uv run --no-sync python -m cli.main research agent-ledger-resolve --json-output
uv run --no-sync python -m cli.main research hypothesis-factory --json-output
uv run --no-sync python -m cli.main research agent-intelligence-brief --json-output
```

Expected on first factory run: `lifecycle_appended_event_count >= 2` (the
two real hypotheses backfill `hypothesis_registered` events dated
2026-06-10T00:14:48+00:00) and `results/hypothesis_factory/lifecycle.jsonl`
exists. Expected from the brief: `results/agent_intelligence/brain.json`
with populated `maturity_radar` and `attention_flags`. Re-running the
factory must append 0 new events when nothing changed. Report: how many of
the 132 suspect labels healed (`high`/`degraded`) vs flipped
(`reaudit_outcome_mismatch`), and whether either preregistered hypothesis
gained audited out-of-sample forecasts.

## Packet 2 — n8n allowlisted observer jobs

`config/n8n_tradingagents_allowlist.json`: add jobs modeled on the existing
`agent_ledger_update` entry (~line 213), all `submit_capable=false`:

- `hypothesis_factory`: `python -m cli.main research hypothesis-factory --json-output`
- `ledger_quality_audit`: `python -m cli.main research ledger-quality-audit --json-output`
- `agent_intelligence_brief`: `python -m cli.main research agent-intelligence-brief --json-output`

If `tradingagents/orchestration/n8n_policy.py` enumerates job kinds,
register all three as observer-class. Tests in
`tests/test_n8n_runner_policy.py`: discovery includes the jobs;
`submit_capable_count` stays 0; runner parses each payload.

## Packet 3 — Nightly chain: quality-audit → resolve → factory → brief

`tradingagents/research/automation_orchestrator.py`: in the after-close
sequence, after `agent_ledger_update`, chain `ledger-quality-audit` →
`agent-ledger-resolve` → `hypothesis-factory` → `agent-intelligence-brief`.
Order matters: the audit heals `window_unverifiable` labels as the feed
catches up, which unlocks minable evidence the same night; the brief runs
last so `brain.json` reflects the night's final state. Keep
`tests/test_real_simulation_audit.py` (~line 64) excluding
`agent_ledger_resolve` from the simulation audit (network calls); document
the decision there. Extend the orchestrator ordering tests.

## Packet 4 — Compact context surfacing

`scripts/automation_context_snapshot.py`: prefer reading
`results/agent_intelligence/brain.json` (it already fuses
`trusted_label_count`, `label_quality_counts`, `defer_reason_counts`,
hypothesis `status_counts`, lifecycle counts, and the maturity radar) and
add a compact block. Flag routes (open only when):

- `ledger.trusted_label_count > 0` for the first time (mining unlocked), or
- `hypotheses.prior_count > 0` (a prior now flows into overnight context), or
- `maturity_radar.due_unresolved_count > 0` for >2 consecutive days with
  empty `resolution_quality.defer_reason_counts` (true stall, not a healthy
  deferral).

Tests: `tests/test_automation_context_snapshot.py` — block present, flag
logic both ways, missing/malformed `brain.json` degrades cleanly.

## Packet 5 — Board + router bookkeeping

- `docs/superpowers/plans/2026-06-08-market-readiness-execution-board.md`:
  add the 2026-06-11 row — pass 3 shipped the hypothesis lifecycle ledger,
  brain packet, and variant scoreboard; validation per Packet 0; evidence
  paths `results/hypothesis_factory/lifecycle.jsonl`,
  `results/agent_intelligence/brain.json`.
- `CONTEXT_ROUTER.md`: dated checkpoint per the existing format (hypothesis
  history is now append-only; the brain brief joins the daily cadence as
  step 4). Name the board ID per AGENTS.md rules.

Out of scope for Codex (Fable-lane, do not attempt): changing lifecycle
event semantics or vocabulary, brain flag/action logic, audit rules, grace
periods, label-quality semantics, hypothesis epistemics, or gating
`agent_influence_weights` on label quality (next Fable pass decides that on
healed-label evidence).
