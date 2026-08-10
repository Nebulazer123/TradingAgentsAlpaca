# Fable Frontier Creation Plan — Closing the Learning Loop (2026-06-09/10)

## The move that was made

TradingAgents already had a forecast nervous system (`tradingagents/evals/agent_intelligence_ledger.py`),
a scoring cortex (Brier, calibration, bounded influence weights), a replay harness, and a calibration
guard. What it did not have:

1. **Any resolved forecast.** 4,784 ledger forecasts, 0 resolved — the first cohort's
   `resolve_after` matured on 2026-06-09/10 and nothing had ever scored against outcomes.
2. **A generative organ.** Nothing converted resolution evidence into new, preregistered,
   out-of-sample-testable research. Failures produced prose, not future work.
3. **A motor bridge.** `agent_influence_weights` is produced by the ledger/CLI but consumed by
   nothing in `tradingagents/graph/` or `tradingagents/agents/`. Forecasts → scores → weights → nowhere.

This session closed (1), built (2), and packetized (3) for delegation.

## First Light — the first resolution in repo history (2026-06-10T00:08 UTC)

`research agent-ledger-resolve --json-output` resolved **132 forecasts** (backup at
`results/agent_intelligence/ledger.backup-20260610-first-resolution.jsonl`, payload at
`results/agent_intelligence/first-resolution-20260610.json`):

| Agent | Resolved | Accuracy | Avg Brier | Earned weight |
| --- | --- | --- | --- | --- |
| market_analyst | 51 | 0.04 | 0.2558 | 0.62 |
| portfolio_manager | 63 | 0.10 | 0.3210 | 0.56 |
| fundamentals_analyst | 3 | 0.33 | 0.2675 | 0.83 |
| news_analyst | 3 | 0.33 | 0.2675 | 0.83 |
| sentiment_analyst | 3 | 0.33 | 0.2788 | 0.81 |
| research_manager | 3 | 0.00 | 0.4356 | 0.50 (floor) |
| trader | 3 | 0.00 | 0.4356 | 0.50 (floor) |
| mirofish_market_mirror | 3 | 0.00 | 0.3025 | 0.51 |

Outcome counts: **121 harmful / 11 useful / 4,652 pending.** Accuracy is against the strict
preregistered bar (±1.5% vs SPY over ~5 trading days), so low absolute numbers are partly the bar —
but the *relative* structure is signal:

- **Bearish calls were the only systematically useful cohort**: `direction=bearish` n=9,
  accuracy 0.3333 vs 0.0833 baseline (+0.25). All nine are portfolio_manager forecasts.
- Influence weights left neutral for the first time ever. This empirically confirms the
  calibration guard's standing `tighten` decision with resolved outcomes instead of replay proxies.

Interpretation guardrail: one week, one regime, overlapping symbols — treat as a hypothesis
generator, not a verdict. Which is exactly what the new kernel does.

## The new kernel — Hypothesis Factory

`tradingagents/evals/hypothesis_factory.py` (+ `research hypothesis-factory` CLI,
`tests/test_hypothesis_factory.py`, 7 tests).

Epistemic contract (the part that matters):

- **Mining proposes, never confirms.** `mine_hypotheses` scans resolved forecasts for context
  cells (agent / direction / setup / regime / sector combos in `CELL_SPECS`) whose accuracy
  deviates from the global baseline by ≥ `edge_threshold`. Every finding is *preregistered* with
  its in-sample evidence frozen.
- **No peeking.** `evaluate_hypotheses` judges each hypothesis only on resolved forecasts with
  `created_at > preregistered_at`. The same data that suggested a pattern can never support it.
  Re-mining an existing pattern never resets its clock (`merge_hypotheses` preserves the original
  `preregistered_at` — tested).
- **Support is expensive.** ≥ `min_out_of_sample` (default 8) matching resolved forecasts, with
  the effect persisting at ≥ half the edge threshold against the out-of-sample baseline.
  Statuses: `preregistered → supported | refuted | insufficient_out_of_sample`, recomputed as
  evidence accumulates.
- **Supported hypotheses become bounded advisory priors** (`research_priors`, multiplier clamped
  to [0.70, 1.30], `execution_authority=none`, forbidden effects listed). Priors may steer research
  attention; they can never touch live gates, sizing, or order paths.

First real run (`results/hypothesis_factory/first-run-20260610.json`):

- Default thresholds → honest null (no cell with n≥12 deviates ≥0.15 — day-one evidence is thin).
- Exploratory preregistration (`--min-sample 9 --edge-threshold 0.15`) preregistered two real
  hypotheses whose out-of-sample clocks started 2026-06-10T00:14:48Z:
  - `hyp-434cc01a6433d705` — portfolio_manager bearish calls outperform baseline (+0.25, n=9)
  - `hyp-319a01e819d1a54f` — bearish direction outperforms baseline (+0.25, n=9)
- Store: `results/hypothesis_factory/hypotheses.jsonl`; priors: `priors.json`; summary: `summary.json`.

As the 4,652 pending forecasts resolve over the coming days, these hypotheses will be judged
automatically by re-running the factory after each `agent-ledger-resolve`.

## Why this is the compounding move

Every future capability in the mandate's search space sits downstream of resolution evidence:

- **Strategy Ecology / sleeve tournaments** need scoreable per-context performance → now produced.
- **Agent Evolution** (role variants, prompt variants, model routes) needs an arena where variants
  earn influence → the ledger + factory is that arena; a variant is just a new `agent` value.
- **Internal Claim Market** is a pricing layer over preregistered hypotheses → schema now exists.
- **Calibration guard / live influence** decisions now have resolved outcomes instead of proxies.

The factory turns observed failure into preregistered future work — the self-improvement loop the
mandate asked for, in its smallest real form.

## Operating cadence (daily, analysis-only)

```powershell
uv run --no-sync python -m cli.main research agent-ledger-resolve --json-output
uv run --no-sync python -m cli.main research hypothesis-factory --json-output
```

Both are idempotent, write under `results/`, and carry `can_submit_orders=false`,
`execution_authority=none`.

## Also fixed this session

- `cli/main.py` `_ledger_price_lookup` now has `lru_cache(maxsize=4096)` — resolution previously
  made 2 uncached yfinance calls per forecast (264 for the first batch alone); cohorts share
  (symbol, start, end) windows. Tests monkeypatch the attribute, so caching does not affect them.

## Validation (2026-06-10)

- `uv run --no-sync python -m compileall -q cli tradingagents tests` — pass
- `uv run --no-sync --group static-analysis ruff check --select E9,F63,F7,F82 cli tradingagents tests` — pass
- `uv run --no-sync --group static-analysis ruff check` over touched files — clean
- `uv run --no-sync --with pytest python -m pytest tests/test_hypothesis_factory.py tests/test_agent_intelligence_ledger.py -q` — **22 passed**

Safety boundary held: no orders, no emails, no dead-man refresh, no live-authority change, no
staging/commits. Ledger resolution and hypothesis preregistration are the intended analysis-only
outcome-labeling path already tracked as in-progress in `CONTEXT_ROUTER.md`.

## What remains (delegated)

See `2026-06-09-codex-delegation-packets.md`:

- A: inject influence weights + research priors into overnight research context (the motor bridge)
- B: expose `hypothesis_factory` as an n8n allowlisted observer job
- C: chain resolve → factory into the nightly automation plan
- D: surface resolution/hypothesis counts in compact context (`automation_context_snapshot`)
- E: board row + scoreboard updates recording first resolution
