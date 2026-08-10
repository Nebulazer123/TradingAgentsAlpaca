# Fable Continuation Prompt — Next Frontier Session

You are continuing the learning-loop work started 2026-06-09/10. Start at altitude; do not
re-crawl the repo.

## Compressed truth (verified 2026-06-10T00:20 UTC)

- The Agent Intelligence Ledger (`tradingagents/evals/agent_intelligence_ledger.py`) resolved its
  **first 132 forecasts ever** on 2026-06-10: 121 harmful / 11 useful, baseline accuracy 0.0833
  against the ±1.5%-vs-SPY 5-day bar. Influence weights left neutral for the first time
  (market_analyst 0.62, portfolio_manager 0.56, research_manager/trader at 0.50 floor).
  Evidence: `results/agent_intelligence/first-resolution-20260610.json`. Pre-resolution backup:
  `results/agent_intelligence/ledger.backup-20260610-first-resolution.jsonl`.
- **4,652 forecasts are still pending** and mature daily through ~2026-06-16. Each maturation day
  is new out-of-sample evidence.
- The new **Hypothesis Factory** (`tradingagents/evals/hypothesis_factory.py`,
  `research hypothesis-factory` CLI, `tests/test_hypothesis_factory.py`) preregistered two real
  hypotheses at 2026-06-10T00:14:48Z, both `outperforms_baseline`, n=9, +0.25 delta:
  - `hyp-434cc01a6433d705` — portfolio_manager + bearish
  - `hyp-319a01e819d1a54f` — bearish direction overall
  They need ≥8 matching resolved forecasts created after preregistration to be judged.
- Daily cadence (idempotent, analysis-only):
  `research agent-ledger-resolve --json-output` then `research hypothesis-factory --json-output`.
- Wiring chores are delegated, not done: see `2026-06-09-codex-delegation-packets.md`
  (A: overnight-context injection of influence+priors, B: n8n job, C: nightly chain,
  D: compact context, E: board bookkeeping). If Codex has not executed them, they are still open.

## Read first (only these)

1. `docs/superpowers/plans/2026-06-09-fable-frontier-creation-plan.md`
2. `results/hypothesis_factory/summary.json` and `results/agent_intelligence/summary.json`
3. `results/_context/latest-summary.json` (refresh via `python scripts/automation_context_snapshot.py --write`)

Ignore: raw `results/` packets unless a flag opens them; `uv.lock`; old handoff prose.

## Next frontier targets, in leverage order

1. **Judge the preregistered hypotheses.** Once ≥8 out-of-sample bearish forecasts resolve, the
   factory will emit its first supported-or-refuted verdict. If supported, the first real prior
   flows; make sure Packet A wiring exists so it actually reaches the overnight graph.
2. **Resolution-quality audit.** Current resolution uses `iloc[-1]` close, which can score a
   forecast 1 day early when the final bar hasn't printed. Quantify the bias; consider deferring
   resolution until the window's last trading day has a bar.
3. **Agent Evolution arena.** The ledger keys everything by `agent` string — a prompt/model/role
   variant is just a new agent name. Build the variant-registration convention + a paper/replay
   harness that feeds variant forecasts into the same ledger so variants earn influence the same
   way roles do.
4. **Claim-market layer.** Preregistered hypotheses now have ids, statuses, and deltas — a
   scoring/ledger abstraction over them (stake, price, hedge) is the next central primitive if
   evidence volume supports it.

## Safety invariants (do not renegotiate)

- SAFE-01 fail-closed posture; dead-man stays lapsed unless the operator refreshes it.
- Everything in this lane is `analysis_only=true`, `execution_authority=none`.
- Worktree carries shared dirty submit-path edits: review hunk-by-hunk before any staging; do not
  commit without explicit operator approval.
