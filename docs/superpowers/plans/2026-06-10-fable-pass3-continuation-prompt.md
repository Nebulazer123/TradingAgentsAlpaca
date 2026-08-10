# Fable Pass 3 Prompt — First Trusted Evidence

You are continuing after Pass 2 (Agent Intelligence Brainstem,
2026-06-10). Start at altitude; do not re-crawl the repo.

## Compressed truth (verified 2026-06-10T05:45Z)

- **Resolution integrity is live.** `tradingagents/evals/resolution_quality.py`
  mechanically audits every resolution window (benchmark = trading-calendar
  oracle; defer-don't-contaminate; label tiers high/degraded/suspect;
  fixed-vocabulary quality flags). The resolve CLI and `agent-ledger-update`
  run through it; `research ledger-quality-audit` retro-audits stored labels
  idempotently with automatic backup.
- **The first 132 labels were all premature.** Retro-audit proved every
  first-light label was measured 1–2 sessions short (feed had bars only
  through 06-08; windows intended 06-09/06-10). All 132 are `suspect`
  (`window_unverifiable`/`final_bar_missing`), trusted_label_count = 0.
  This state is self-healing: re-run the quality audit once the 06-09/06-10
  bars land and each label becomes `high`/`degraded` (outcome stable) or
  stays `suspect` with `reaudit_outcome_mismatch` (outcome flipped).
- **The factory now refuses untrusted evidence.** `require_audited_labels`
  defaults on; suspect labels are never minable. Current run: minable 0 of
  132. The two preregistered hypotheses (`hyp-434cc01a6433d705`
  portfolio_manager+bearish, `hyp-319a01e819d1a54f` bearish) keep their
  2026-06-10T00:14:48Z clocks; OOS judgment now requires audited labels.
- **The motor bridge is closed.** Overnight research context carries an
  `agent_intelligence_advisory` packet (counts, label-quality tiers, earned
  influence weights, supported priors machine+rendered, advisory-only
  language, analysis-only authority) — `build_agent_intelligence_packet` in
  `tradingagents/research/overnight_context.py`, surfaced in the summary and
  the compact `overnight_prior_feed_v1`. When a hypothesis becomes supported,
  the next research run sees the prior automatically.
- 12 newly-due forecasts deferred cleanly on 06-10 (`final_bar_missing`);
  ~4,640 still pending, maturing daily through ~2026-06-16.

## Read first (only these)

1. `docs/superpowers/plans/2026-06-10-fable-pass2-agent-intelligence-brainstem.md`
2. `results/agent_intelligence/resolution_quality.json` and
   `results/agent_intelligence/summary.json` (label_quality_counts)
3. `results/hypothesis_factory/summary.json`

## First action: harvest the first trusted labels

Run, in order (idempotent, analysis-only):

```powershell
uv run --no-sync python -m cli.main research ledger-quality-audit --json-output
uv run --no-sync python -m cli.main research agent-ledger-resolve --json-output
uv run --no-sync python -m cli.main research hypothesis-factory --json-output
```

Then answer, with evidence paths:

1. How many of the original 132 labels survived re-measurement
   (high/degraded) and how many flipped (`reaudit_outcome_mismatch`)? The
   flip count is the measured size of the early-bar bias — report it as the
   repo's first data-quality result.
2. Did the bearish edge survive on trusted labels only? (Re-run influence
   weights / cell accuracies on the high+degraded subset.)
3. How much minable evidence does the factory now have, and did either
   preregistered hypothesis accumulate its first audited out-of-sample
   forecasts?

## Then, frontier targets in leverage order

1. **Judge the preregistered hypotheses on trusted evidence** — first
   supported/refuted verdict; if supported, verify the prior reaches the
   overnight packet (it will — assert it in results, not code).
2. **Agent Evolution arena** — the ledger keys by `agent` string; variant
   registration + replay/paper harness so prompt/model variants earn
   influence through the same audited pipeline.
3. **Claim-market layer** over preregistered hypotheses (ids, statuses,
   deltas exist; pricing/stake abstraction is next once evidence volume
   supports it).

Delegated wiring chores (n8n jobs, nightly chain, compact context, board
rows) live in `2026-06-10-codex-packet-agent-intelligence-wiring.md` — check
whether Codex executed them before redoing anything.

## Safety invariants (do not renegotiate)

- SAFE-01 fail-closed posture; the live-control dead-man stays lapsed unless
  the operator refreshes it.
- Everything in this lane is `analysis_only=true`, `execution_authority=none`,
  `can_submit_orders=false`.
- The worktree carries shared dirty submit-path edits: review hunk-by-hunk
  before any staging; no commits without explicit operator approval.
