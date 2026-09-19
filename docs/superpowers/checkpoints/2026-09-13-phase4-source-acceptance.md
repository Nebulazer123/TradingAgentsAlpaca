# Phase 4 source acceptance and isolated PIT follow-up

Phase 4 lifecycle source is accepted at
`4fa91d3e2b7fe0be29952b141ebba7aa2ed3090a`, integrated into canonical `master`
by fast-forward on 2026-09-13. The independently isolated bar-shape follow-up
was then accepted through its affected PIT checkpoint and fast-forwarded to
`8fc3296099a0f91baaf97e20b3359567c7968d64`.

## Exact evidence and scope

The existing 17-module Phase 4 run completed once, exit 0, on unchanged
`4fa91d3`: **393 passed in 6502.17 seconds**. The runner's monotonic elapsed
time was 6503.459 seconds. Wall-clock start/end were
`2026-09-13T19:23:39.976488+00:00` and
`2026-09-13T23:19:19.126990+00:00`; do not conflate the clock difference with
active test duration or infer a cache speedup from it.

Ruff over the prescribed economic/PIT/CLI owners, compilation of CLI and
application source, offline `uv lock --check` using canonical Python 3.13.14,
and whitespace checking all returned exit 0. The final receipt and exact log
hash were reread and verified before integration. The log SHA-256 is
`538d27731af3c4d86eb5e7b9a8f976807758fab3e5d7286d1bbbf88247a23d3b`.

Durable local receipt:
`.superpowers/sdd/2026-08-30-tradingagents-evidence-first-working-state-completion/phase4-gate-20260913-4fa91d3/receipt.json`.
The same directory retains pytest and static-check logs. The original tool
session 22690 completed with exit 0; it must not be polled or restarted.

The solo Phase 4 review closed development-readiness custody reopening and
report-phase dispatch findings. Its detailed receipt is
`phase4-review-20260913.md` in the same SDD root. The previously completed
cache review was reused. Reviews were solo, not independent.

## Separate bar-shape follow-up

The 393-test receipt belongs to `4fa91d3`, **not** the later bar correction.
The later diff changes only `official_observations.py`, its corresponding
test module, and a documentation report. No other source, configuration,
dependency or Phase 4 lifecycle code changed between those revisions.

At exact clean `8fc3296`, the follow-up checkpoint ran the five affected
modules: `test_point_in_time_official_observations.py`,
`test_point_in_time_raw_artifacts.py`, `test_point_in_time_records.py`,
`test_pit_adjusted_price_windows.py`, and `test_source_bound_resolution.py`.
**124 tests passed in 5.40 seconds** with network/integration markers excluded,
feature `PYTHONPATH`, and `TA_LIVE_SUBMIT=0`. Changed-source Ruff, compilation
and range whitespace checks passed. The XML receipt is
`alpaca-bar-shapes-pit-checkpoint-20260913.xml` in the SDD root.

This uses the plan's proportional verification rule: preserve the accepted
lifecycle gate and verify the distinct, later PIT correction in its affected
scope. It is not a claim that all 393 tests reran on the combined revision.
The complete repository gate on the final program source remains required
in Phase 10. Parser review, RED/GREEN regressions and the retained-byte
diagnostic are in [the bar-shape report](../../alpaca/2026-09-13-bar-shape-compatibility.md).

## Preservation and remaining requirements

At `2026-09-13T23:21:29.229144+00:00`, all four frozen owners, all ten PAUSED
automation hashes, and the exact LangGraph HEAD/status/sixteen file hashes
matched `task-3-preservation-2026-09-07.json`. Both integration sources were
clean and canonical was clean before each fast-forward. No history was
rewritten and all isolated branches/worktrees remain retained.

The next implementation is Phase 5 in the existing preserved LangGraph
worktree. No Phase 5 edits or acceptance are claimed here. Full graph benchmark
wiring, real source-bound reconciliation, evidence qualification, readiness
supersession, the final source gate and the qualifier/five-day campaign remain
open. All real release/trading/provider boundaries continue to apply.

The Alpaca raw captures are current-retention evidence, not proof of past
availability or a registered historical cohort. No real holdout was released,
no orders placed, no schedule activated, and no profitability established.
