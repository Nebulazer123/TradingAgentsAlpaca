# Fable Pass 4 Prompt — Trusted Influence

You are continuing after Pass 3 (Lifecycle + Brain + Variant Seed,
2026-06-11). Start at altitude; do not re-crawl the repo.

## Compressed truth (filesystem-verified 2026-06-11, execution-denied session)

- **Pass 2 is real and complete**: resolution integrity
  (`tradingagents/evals/resolution_quality.py`), audited resolve/retro-audit
  paths in the ledger, motor bridge (`build_agent_intelligence_packet` in
  `tradingagents/research/overnight_context.py`), factory
  `require_audited_labels` gate. The interrupted run was pass 3 itself; it
  died after running the cadence, before creating anything.
- **Data state**: 4,864 forecasts; 132 resolved, all `suspect`
  (feed lacked 06-09/06-10 bars at audit time); last resolve deferred 981
  due forecasts (`final_bar_missing`), 3,671 not yet mature; 2 hypotheses
  preregistered since 2026-06-10T00:14:48Z with 0 audited out-of-sample
  forecasts. Influence weights (market_analyst 0.62, portfolio_manager
  0.56) were earned on suspect labels — see frontier 1.
- **Pass 3 built** (authored tests-first but **never executed** — the
  session denied all process execution):
  - `tradingagents/evals/hypothesis_lifecycle.py` — append-only
    `results/hypothesis_factory/lifecycle.jsonl`; deterministic event ids;
    registration backfill; wired into `run_hypothesis_factory`.
  - `tradingagents/evals/agent_intelligence_brain.py` + CLI
    `research agent-intelligence-brief` — durable brain packet
    (`results/agent_intelligence/brain.json`) with maturity radar,
    attention flags, recommended actions.
  - `tradingagents/evals/agent_variants.py` — variant naming convention +
    per-role scoreboard over the same audited ledger.

## First actions (in order)

1. Check whether Codex executed
   `2026-06-11-codex-agent-intelligence-packets.md` Packet 0 (validation)
   and Packet 1 (first cadence + lifecycle seed). If not, run them yourself:
   the pass-3 test suite has **never been executed** — treat any failure as
   yours to fix before building.
2. Read `results/agent_intelligence/brain.json` (or run
   `research agent-intelligence-brief`). It replaces raw results crawling.
3. Answer with evidence paths: how many of the 132 suspect labels healed vs
   flipped (`reaudit_outcome_mismatch`)? Did the bearish edge survive on
   trusted labels? Did the lifecycle ledger capture its first verdict
   events?

## Frontier targets, in leverage order

1. **Trusted-influence weights.** `agent_influence_weights` still earns
   weights from all resolved forecasts regardless of `label_quality`; the
   motor bridge ships weights earned on 132 suspect labels. Once healed
   labels exist, gate influence on `high`/`degraded` (mirror the factory's
   `minable_forecasts` gate), with explicit fallback states when the
   trusted subset is below `min_resolved`. This touches
   `summarize_agent_scores` consumers and many ledger tests — it is a
   semantics change; decide thresholds on healed-label evidence, not
   defaults.
2. **Judge the preregistered hypotheses on trusted evidence** — the
   lifecycle ledger will record the first supported/refuted verdict
   automatically; verify the prior reaches the overnight packet and the
   brain (`supported_priors_active` flag).
3. **Variant arena, live**: register the first real variant (e.g. a
   portfolio-manager prompt revision) via
   `variant_agent_name(...)`, feed its forecasts through the same pipeline,
   and surface `variant_scoreboard` in the brain packet once more than one
   variant has earned history.
4. **Claim-market layer** over preregistered hypotheses (ids, statuses,
   deltas, and now lifecycle events exist; pricing/stake abstraction is
   next once evidence volume supports it).

## Safety invariants (do not renegotiate)

- SAFE-01 fail-closed posture; the live-control dead-man stays lapsed
  unless the operator refreshes it.
- Everything in this lane is `analysis_only=true`,
  `execution_authority=none`, `can_submit_orders=false`.
- The worktree carries shared dirty submit-path edits: review hunk-by-hunk
  before any staging; no commits without explicit operator approval.
