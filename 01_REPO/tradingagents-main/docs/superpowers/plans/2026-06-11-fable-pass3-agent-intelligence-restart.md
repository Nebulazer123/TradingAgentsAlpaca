# Fable Pass 3 — Agent Intelligence Restart: Lifecycle + Brain + Variant Seed (2026-06-11)

## Restart finding: pass 2 finished; the interruption killed pass 3 at birth

Filesystem recovery (no git/process execution was permitted in this session —
see Validation) showed the "interrupted run" was **pass 3 itself**, which had
only gotten as far as running the harvest cadence before dying:

- Every pass-2 claim verified against code: `resolution_quality.py`,
  the audited ledger paths, `build_agent_intelligence_packet`, the factory's
  `require_audited_labels` gate, the `ledger-quality-audit` CLI — all real
  and coherent. No broken or half-written files were found.
- The last resolve run (after the pass-2 doc was written) produced
  `results/agent_intelligence/resolution_quality.json` with **981 deferred
  (`final_bar_missing`) / 3,671 not mature / 0 resolvable** — the price feed
  still lacked the final session bars, and the integrity engine deferred
  everything instead of contaminating. Ledger now holds **4,864 forecasts**
  (80 new since pass 2), 132 resolved (all `suspect`), 4,732 pending.
- None of the 2026-06-10 Codex wiring chores (n8n jobs, nightly chain,
  compact context, board rows) had been executed.

## The move: capture history before the first verdict lands

The preferred restart target (Resolution Integrity + Motor Bridge) was
already built, so this pass took the next-highest-leverage moves:

### Lane 1 — Hypothesis Lifecycle Ledger (Move C, built)

`hypotheses.jsonl` is current-state-only: every factory run rewrites every
row. The **first supported/refuted verdict in repo history is imminent**
(feed catch-up + 8 audited out-of-sample labels), and without this pass it
would have overwritten `preregistered` silently, leaving no trace of the
learning loop's most important transition.

`tradingagents/evals/hypothesis_lifecycle.py` (+21 tests in
`tests/test_hypothesis_lifecycle.py`, factory integration tests in
`tests/test_hypothesis_factory.py`):

- Append-only `results/hypothesis_factory/lifecycle.jsonl`; fixed event
  vocabulary: `hypothesis_registered`, `hypothesis_supported`,
  `hypothesis_refuted`, `hypothesis_evidence_insufficient`,
  `hypothesis_status_changed` (fallback), `prior_emitted`, `prior_retracted`.
- Events are derived by diffing store state before/after each factory run;
  unchanged hypotheses emit nothing, so the daily cadence is event-silent
  until something actually happens. Event ids are deterministic hashes of
  the transition; `append_lifecycle_events` dedupes, so replays never
  duplicate history.
- Registration events are **backfilled from store state** (dated at
  `preregistered_at`): the first operator run will seed the two real
  hypotheses (`hyp-434cc01a6433d705`, `hyp-319a01e819d1a54f`) into the
  ledger with their true 2026-06-10T00:14:48Z timestamps — no hand-written
  artifacts.
- `run_hypothesis_factory` now appends events every run (lifecycle file
  lives next to the store unless `--lifecycle-path` overrides) and reports
  `lifecycle_appended_event_count`, `lifecycle_total_event_count`,
  `lifecycle_event_type_counts`, `corrupt_lifecycle_line_count`.
- Transition events freeze the evidence snapshot (`out_of_sample_count`,
  `out_of_sample_delta`); `prior_emitted` records the bounded multiplier
  that actually flowed.

### Lane 2 — Agent Intelligence Brain (Move D, built)

`tradingagents/evals/agent_intelligence_brain.py` + CLI
`research agent-intelligence-brief` (+6 tests in
`tests/test_agent_intelligence_brain.py`):

- Fuses ledger truth, influence weights, resolution quality, hypothesis
  store, priors, and the lifecycle tail into one durable packet
  (`results/agent_intelligence/brain.json`, schema
  `agent_intelligence_brain_v1`) plus a compact rendered briefing — the
  thing a future agent reads first instead of re-crawling `results/`.
- **Maturity radar**: counts due-but-unresolved forecasts and buckets
  upcoming `resolve_after` dates over a configurable horizon —
  "when does the next out-of-sample evidence arrive" is now a field, not a
  spelunking exercise.
- Fixed-vocabulary `attention_flags` (`all_resolved_labels_suspect`,
  `no_trusted_labels_yet`, `deferrals_waiting_on_final_bars`,
  `due_forecasts_awaiting_resolution`, `supported_priors_active`,
  `context_sources_missing_or_malformed`, …) and ordered
  `recommended_actions` carrying the exact cadence commands.
- Every source is read with explicit `ok|missing|malformed` status; the
  builder never raises; the packet always carries `analysis_only=true`,
  `can_submit_orders=false`, `execution_authority=none`.

### Lane 3 — Agent Evolution seed (Move E, built small)

`tradingagents/evals/agent_variants.py` (+5 tests in
`tests/test_agent_variants.py`):

- Canonical variant naming
  `role::prompt_version+model_route+toolset+context_policy`
  (e.g. `market_analyst::pv2+sonnet45+default+lean_ctx`); malformed names
  degrade to plain agents, so foreign ledger rows never break anything.
- `variant_scoreboard` groups ledger agents by base role and ranks variants
  by earned bounded influence (earned states ahead of unproven; a role only
  gets a `leader` that actually earned its weight). Variants compete through
  the same audited resolution pipeline as the base roles — no new authority.

## Evidence-packet lenses applied (AI-PKT-TRADING-001)

- **Episodic logs → append-only ledgers** (lens 2): lifecycle events.
- **Evidence artifacts over claims** (lens 6): `lifecycle.jsonl`,
  `brain.json`, per-run lifecycle counts in factory payloads.
- **Durable state + explicit handoff** (lenses 1, 8): the brain packet is
  the state packet; this doc + the continuation prompt carry objective,
  state, sources checked, risks, next actions.
- **Workflow evals and negative cases** (lens 7): corrupt lines counted not
  eaten; missing/malformed sources degrade to statuses; dedupe on replay;
  suspect labels never raise hypothesis support (pass-2 gate retested).
- **Schedules are radar, artifacts are truth** (lens 10): the maturity radar
  tells the operator when running the cadence will matter.
- **Compression preserves trading facts** (lens 11): events and the brain
  keep exact timestamps, counts, multipliers, and source paths.

## Validation — NOT RUN (read before trusting)

This session's permission mode denied all process execution (Bash and MCP
process tools), so **no test, compile, or CLI command was executed**. All
code was authored tests-first against the verified real APIs, but the
red-green loop could not run. First action for the next session/operator:

```powershell
cd "C:\Users\Corbin\Documents\Coding projects\TradingAgents-main"
uv run --no-sync --with pytest python -m pytest tests/test_hypothesis_lifecycle.py tests/test_hypothesis_factory.py tests/test_agent_intelligence_brain.py tests/test_agent_variants.py tests/test_agent_intelligence_ledger.py tests/test_resolution_quality.py tests/test_overnight_context.py -q
uv run --no-sync python -m compileall -q cli tradingagents tests
uv run --no-sync --group static-analysis ruff check --select E9,F63,F7,F82 cli tradingagents tests
```

Then the cadence (now four commands, brief last):

```powershell
uv run --no-sync python -m cli.main research ledger-quality-audit --json-output
uv run --no-sync python -m cli.main research agent-ledger-resolve --json-output
uv run --no-sync python -m cli.main research hypothesis-factory --json-output
uv run --no-sync python -m cli.main research agent-intelligence-brief
```

Safety boundary held: no orders, no emails, no dead-man refresh, no staging
or commits, no live-authority changes; every new payload carries
`analysis_only=true`, `can_submit_orders=false`, `execution_authority=none`.

## Files changed

- new `tradingagents/evals/hypothesis_lifecycle.py`
- new `tradingagents/evals/agent_intelligence_brain.py`
- new `tradingagents/evals/agent_variants.py`
- new `tests/test_hypothesis_lifecycle.py`, `tests/test_agent_intelligence_brain.py`,
  `tests/test_agent_variants.py`
- edited `tradingagents/evals/hypothesis_factory.py` (lifecycle integration),
  `tests/test_hypothesis_factory.py` (+2 tests), `cli/main.py`
  (`--lifecycle-path`, new `research agent-intelligence-brief`)

## Known gap promoted to next frontier

`agent_influence_weights` still earns weights from **all** resolved
forecasts regardless of `label_quality` — the 0.62/0.56 weights flowing
through the motor bridge today were earned on 132 suspect labels. The brain
packet makes this visible (`trusted_label_count` vs `influence weights`),
but gating influence on trusted labels is a semantics change with wide test
impact and belongs to the next Fable pass, decided on healed-label evidence.

## What remains (delegated)

`2026-06-11-codex-agent-intelligence-packets.md` — validation run, harvest
cadence, plus the still-open 06-10 chores (n8n jobs, nightly chain, compact
context, board/CONTEXT_ROUTER bookkeeping) restated against the new surface.
