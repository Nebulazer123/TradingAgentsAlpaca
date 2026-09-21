# Phase 8 readiness source checkpoint — 2026-09-13

This is verified source and offline input compatibility, **not an executed
supersession or completed Phase 8**. The existing isolated readiness worktree
at reviewed `0b38a8e` was combined with canonical `3901c2c`, without conflicts.
No subagent was dispatched, no real promotion state was replaced, and no
readiness packet, compact-context refresh or TSM/BOARD review was executed.

## Preserved behavior and scope

The existing source adds exact-hash legacy GO/promotion/expired-ledger binding,
an immutable prepared/completed receipt pair, paper-only/live-disabled decisions
through the existing locked trusted promotion writer, an expired-ledger
fingerprint, and the read-only `policy readiness-status` CLI. Historical bytes
are retained; no tournament ledger is overwritten, renewed or granted authority.
The prepared before-image must rederive the exact expected after-image on retry.
The readiness builder requires the exact expected control/schedule/role hashes,
reopens historical artifacts, verifies ten paused schedules, and reports
profitability/readiness `NOT_ESTABLISHED` with economic qualification pending.

Earlier independent R1/R2 correction receipts at `70de894` and `0b38a8e` are
reused as historical source review. Current merge and changes received a distinct
solo review, not an independent-review claim. All pre-existing canonical
top-level definitions remain exact: **274 CLI, 18 promotion-sync, 79 paper
tournament**. The original feature additions remain exact except the two
deliberately repaired supersession/readiness functions. The source compatibility
check also confirms no duplicate top-level definitions. Existing CLI queue
inventory entries moved from 6651/6663 to 6716/6728 without reclassification.

## R3 — Validate completion evidence before any replacement

Three regressions reproduced a remaining ordering defect: a foreign completed
receipt, with or without valid prepared evidence, was rejected only after the
promotion writer ran; an authentic completed receipt could also reapply a
transition after the promotion state rolled back to its before-image.

The completed receipt is now checked against the rederived operation before
the writer runs. Completed evidence without retained preparation fails before
creating preparation. A completed operation requires its exact current
after-image; foreign completion or rollback is not permission to repair state.
Prepared bytes are bound before the write and rechecked before completion.
Interrupted genuine preparation still resumes using the original timestamp.
Foreign files and rolled-back state are preserved, never overwritten to hide
the mismatch. RED: three intended failures; focused GREEN: fifteen passed.

## R4 — Bind the captured bytes and reject observed mid-read drift

Four regressions proved that the builder could report an old control, promotion
or automation hash after a change during schedule capture, or label a different
captured schedule contract with the expected preflight hash.

The manifest's captured schedule and role hashes now must equal the expected
identities. One final readback checks every actual input used by the packet:
completion/preparation, historical GO/expired ledger, current promotion/control,
schedule/role contracts and all ten automation files. Observed changes or missing
files reject; the builder never repairs another writer's changes. This bounded
readback is not an atomic multi-file snapshot, continuous monitoring, or proof
that files cannot change after the function returns. RED: four intended failures;
the complete promotion-sync module then passed **59 tests in 1.35s**.

## Affected gate and statics

One combined gate on the corrected merged candidate passed **560 tests in
18.66s**, exit 0 (JUnit suite time 18.629s), with two existing AST invalid-escape
warnings. It covered:

- `tests/test_promotion_sync.py`
- `tests/test_promotion_policy.py`
- `tests/test_paper_tournament.py`
- `tests/test_live_gate.py`
- `tests/test_authority_role_alignment.py`
- `tests/test_automation_role_contracts.py`
- `tests/test_alpaca_cli.py`

Command used canonical Python 3.13.14 from the feature directory with feature
`PYTHONPATH`, `TA_LIVE_SUBMIT=0`, `-m 'not integration and not network'`, `-q`,
`--tb=short` and the named JUnit destination. Receipt under canonical SDD:
`phase8-readiness-source-gate-20260913.xml`, SHA-256
`b9dcfb05abd6c1d1e436c09a80623248c29da26be9d775b9945b890c493ab8fe`.
Six affected source/test paths passed Ruff; the three production paths passed
compileall; offline `uv lock --check` and both diff checks passed. No dependency
or global configuration changed. No full repository gate ran in this phase.
All test sessions are terminal; no delayed test was restarted.

## Real-input compatibility, no transition

At `2026-09-14T02:38:12.565140Z`, read-only checks found the exact intended
historical artifacts and validated their existing contracts:

- `results/unfreeze_readiness/unfreeze-readiness-20260717-191740.json`:
  SHA-256 `e50777022bf243270926ffcf9f67d9a2ba374ff25b68f2b2d4a5916d042482af`,
  established `decision=GO`, historical only.
- `results/policy/promotion_state.json`:
  SHA-256 `8b0e5d99cde2db1b59b1c522c458b1ddbde2770be38e18cf27d4b68bda45e196`,
  two schema-valid sleeves; **pullback-support is still live-enabled in this
  stale file**, because no actual supersession has been performed.
- `results/paper_strategy_tournament/paper-tournament-ledger.json`:
  SHA-256 `a511ab7a13a73b894879017c3083fca0622f1250f322a05d40bb81dd0721d7a1`,
  tournament `paper-tournament-20260531-080741`, expired July 1 at 08:07:41 UTC.

The actual current schedule snapshot passed its paused predeployment contract:
ten configured, ten paused, no capture issues. All four frozen owners, all ten
automation hashes, all 24 original Alpaca response hashes/private permissions and
the original Phase 5 ZIP remain unchanged. Receipt and helper in canonical SDD:
`phase8-source-inputs-preintegration-20260913.json` and
`phase8_source_checkpoint_20260913.py`. The helper's exclusive destination must
not be replayed. Compatibility is not permission or proof of a completed
transition, fresh readiness, profitability, model qualification or trading.

## Remaining work

Preserve the full existing plan. Real Phase 8 supersession, readiness emission,
compact-context refresh and the analysis-only TSM/BOARD evidence remain open
behind ordered acceptance and operational boundaries. Real PIT/economic/learning
and research-corpus qualification, the single final source gate, and the future
qualifier plus five-day campaign are still required. Keep live control frozen,
all ten automations paused and every preserved worktree/branch/handoff retained.
No new collection, model, holdout, submission, deployment or cleanup authority
is implied by this source checkpoint.
