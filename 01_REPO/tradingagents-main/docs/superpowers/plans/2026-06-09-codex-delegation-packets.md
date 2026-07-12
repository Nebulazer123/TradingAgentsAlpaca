# Codex Delegation Packets — Learning-Loop Wiring (2026-06-09/10)

Origin: Fable frontier session (see `2026-06-09-fable-frontier-creation-plan.md`).
The kernel exists and is tested; these packets are the wiring chores. All packets are
analysis-only — none may add order authority, and every new packet/payload must carry
`analysis_only=true`, `can_submit_orders=false`, `execution_authority="none"`.

Shared verification baseline for every packet:

```powershell
cd "C:\Users\Corbin\Documents\Coding projects\TradingAgents-main"
uv run --no-sync python -m compileall -q cli tradingagents tests
uv run --no-sync --group static-analysis ruff check --select E9,F63,F7,F82 cli tradingagents tests
uv run --no-sync --with pytest python -m pytest tests/test_hypothesis_factory.py tests/test_agent_intelligence_ledger.py -q
```

---

## Packet A — Inject earned influence + research priors into overnight research context

**Objective.** Close the motor loop: the overnight graph should *see* earned agent influence
weights and supported hypothesis priors as advisory context. Today
`agent_influence_weights` / `render_agent_influence_context` (ledger) and
`research_priors` / `render_research_priors_context` (factory) are produced but consumed by nothing
in `tradingagents/graph/` or `tradingagents/agents/`.

**Files.**
- `tradingagents/research/overnight_context.py` — add an `include_agent_intelligence: bool = True`
  branch to `build_overnight_research_context_packets` / `write_overnight_research_context`
  (signature starts line ~622) that reads `results/agent_intelligence/summary.json` and
  `results/hypothesis_factory/priors.json` (tolerate absence) and emits one compact advisory
  packet: kind `agent_intelligence_context`, with `influence_context` and `priors_context`
  rendered strings plus raw weights for machine use.
- `cli/main.py` — overnight plan path already calls `write_overnight_research_context`; thread the
  flag through (default on, `--no-agent-ledger` style flag already exists for ledger writes — reuse
  naming conventions).
- Tests: extend `tests/test_overnight_context.py` (or nearest equivalent) — packet present when
  files exist, absent/quiet when missing, never raises on malformed JSON.

**Acceptance.**
- A no-latest overnight probe run shows the new packet in `research_context` with
  `execution_authority=none`.
- Missing/corrupt summary or priors files degrade to "no packet", never an exception.
- Prompt-injection string contains the literal "advisory only" sentence from the renderers.

**Failure modes to expect.** `summary.json` has Decimal-as-string fields — do not float-cast;
pass rendered strings through untouched. Do not import yfinance at module import time.

---

## Packet B — Expose `hypothesis_factory` as an n8n allowlisted observer job

**Objective.** Let the n8n control plane run the factory on its read-only cadence.

**Files.**
- `config/n8n_tradingagents_allowlist.json` — add `hypothesis_factory` job modeled on the
  existing `agent_ledger_update` entry (line ~213): command
  `python -m cli.main research hypothesis-factory --json-output`, `submit_capable=false`.
- `tradingagents/orchestration/n8n_policy.py` — if job kinds are enumerated, register the new job
  as observer-class.
- Tests: `tests/test_n8n_runner_policy.py` — discovery includes the job;
  `submit_capable_count` stays 0; runner executes it and parses JSON.

**Acceptance.** `python -m tradingagents.orchestration.n8n_runner --run-job hypothesis_factory --json`
returns `status=ok`, `submit_capable=false`, and the payload's `status_counts`.

---

## Packet C — Chain resolve → factory into the nightly automation plan

**Objective.** Resolution and hypothesis evaluation must happen automatically as forecasts mature,
not when a human remembers.

**Files.**
- `tradingagents/research/automation_orchestrator.py` — in the after-close/overnight sequence,
  after the existing `agent_ledger_update` step, add `agent-ledger-resolve` (if not already implied
  by update) followed by `research hypothesis-factory`.
- `tradingagents/evals/real_simulation_audit.py` — `test_real_simulation_audit.py` asserts
  `agent_ledger_update` is chained and `agent_ledger_resolve` is NOT (line ~64). Revisit that
  policy decision: resolution makes network calls (yfinance), so it may stay out of the simulation
  audit but must be in the real nightly chain. Document whichever way you land in the test.
- Tests: extend `tests/test_automation_orchestrator.py` equivalents for ordering
  (update → resolve → factory).

**Acceptance.** The orchestration plan packet lists the three steps in order with
`submit_capable=false`; focused tests pass.

**Failure modes.** yfinance rate limits on large due-cohorts — `_ledger_price_lookup` is now
lru_cached, but if a day's due cohort spans many windows, consider `--max-resolve` batching as a
follow-up rather than blocking this packet.

---

## Packet D — Surface resolution + hypothesis state in compact context

**Objective.** Future agents should see "resolved_count, harmful/useful, supported priors" in
`results/_context/latest-summary.json` without opening raw packets.

**Files.**
- `scripts/automation_context_snapshot.py` — read `results/agent_intelligence/summary.json`
  (`resolved_forecast_count`, `outcome_counts`) and `results/hypothesis_factory/summary.json`
  (`status_counts`, supported count); add a compact block plus a flag route that opens only when
  `supported` > 0 (new priors deserve attention) or resolution stalls (due forecasts but 0 newly
  resolved for >2 days).
- Tests: `tests/test_automation_context_snapshot.py` — block present, flag logic both ways.

**Acceptance.** `python scripts/automation_context_snapshot.py --write` shows the new block;
no new flags open on the current state except by the rules above.

---

## Packet E — Board + scoreboard bookkeeping

**Objective.** Record first resolution in the operational tracker so no future agent re-discovers it.

**Files.**
- `docs/superpowers/plans/2026-06-08-market-readiness-execution-board.md` — update the
  outcome-labeling row(s): first resolution happened 2026-06-10T00:08 UTC, 132 resolved,
  121 harmful / 11 useful, evidence paths
  `results/agent_intelligence/first-resolution-20260610.json` and
  `results/hypothesis_factory/first-run-20260610.json`, verification command
  `uv run --no-sync --with pytest python -m pytest tests/test_hypothesis_factory.py tests/test_agent_intelligence_ledger.py -q`.
- `CONTEXT_ROUTER.md` — move "outcome labeling as forecasts resolve" from In progress narrative to
  a dated checkpoint entry per the existing checkpoint format. Name the board ID you work, per
  AGENTS.md rules.

**Acceptance.** Board row carries date + evidence + command; no duplicate tracker created.
