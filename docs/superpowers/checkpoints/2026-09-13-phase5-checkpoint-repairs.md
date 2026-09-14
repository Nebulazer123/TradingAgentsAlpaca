# Phase 5 checkpoint repairs — source checkpoint

Status: Tasks 5.1–5.4 source acceptance passed on the combined candidate.
Source checkpoint `b40683e` was merged with accepted canonical `7c5b9a7` in the
existing LangGraph worktree. Git ancestry records its canonical integration.
Task 5.5, complete program, model, economic, and operational readiness remain open.

## Preserved work and authority

The sixteen original modified/untracked files at `93854eb6` were backed up
byte-for-byte before repairs. The unchanged original archive is in canonical
`.superpowers/sdd/2026-08-30-tradingagents-evidence-first-working-state-completion/phase5-original-20260913.zip`,
SHA-256 `06a1306b55da45729ec52c02ef1022e4019bf5cb6a58684cf8f75db7332d5633`.
All original identities, custody checks, exact status/clear/retention, packet
replay, analysis-only boundaries, and generic default-off behavior remain.
No dependency version changed; the warning-compatibility comment was corrected.

At `2026-09-14T01:04:21.908935+00:00`, the original archive and its sixteen source
members matched, four frozen owner hashes matched, ten automation hashes remained
PAUSED, live control remained frozen, `.env` remained private, and canonical
`master` remained clean at `7c5b9a7`. Three untouched original files also matched.
`phase5-premerge-preservation-20260913.json` binds all eighteen current source/test
file hashes. No broker, model, holdout, schedule, promotion, or live-control action
was performed. The original handoffs remain unchanged.

## Changes and review

- Task 5.1: inspect and validate saved state before pending-memory resolution.
  A valid resume skips resolution; a genuinely fresh run performs it once.
  Identity, run ID/time, ticker/date/asset, reports, messages, bounded-context
  fields, and debate shapes are checked without normalizing corrupted state.
  Real debate nodes may omit the judge field until the manager runs. Legacy
  `past_context` is not allowed back into a checkpointed production run.
- Stored packet references now reuse the existing durable packet validation:
  exact journal/packet/evidence digests and lineage must match before invocation.
  This preflight performs no packet publication or latest-pointer repair.
- Task 5.2: explicit interactive `--no-checkpoint` writes `checkpoint_receipt.json`
  beside automatic reports and the separately saved complete report. It says
  disabled, null identity/step, nonqualifying, analysis-only, no authority and no
  order capability. Generic reports without a receipt do not acquire one.
- Task 5.3: schema v2 replaces the ambiguous predecessor with two required
  destination-bound SHA-256 values: `learning_evidence_predecessor` and
  `decision_ledger_predecessor`. Old identities fail closed and are not deleted.
  Checkpoint discovery retains the exact pre-run identity when the only decision
  journal advances are authenticated events from that same logical `run_id`.
  Foreign advances, changed prefix, rollback, collisions and missing provenance
  reject. Learning events have no graph-run ownership and this graph does not
  append them, so any learning-head change rejects rather than being called an
  own-run write. A configured learning root is bound as well.
- A read-only DecisionLedger journal snapshot authenticates packet bindings and
  existing latest pointers. It neither creates a missing store nor repairs a
  pointer interrupted after journal fsync. Existing strict verification and the
  exact packet replay recovery retain their prior behavior. Present pointers
  that contradict a truncated journal reject.
- Constructor checks still bind source/configuration before client creation.
  Only decision-head comparison is deferred to the actual run, where both the
  predecessor and stored packet/state checks must pass before effects. Interactive
  and overnight analysis supply the ticker/date for retained-identity discovery;
  no checkpoint default was added to broker, approval, or scheduler commands.

Solo source/test review (no subagents) identified and closed two additional
acceptance gaps: syntactically valid but unbound saved packet references, and
present latest pointers contradicting journal rollback. This is not a claim of
independent reviewer sign-off. The executing-plans skill kept the existing
isolated branch and ordered, proportionate verification; no replacement plan
or additional tooling gate was introduced.

## Verification receipts

All receipts below are in the canonical SDD folder named above.

| Receipt | Evidence |
| --- | --- |
| `phase5-ordering-red-semantic-20260913.xml` | 13 expected failures demonstrating resolver ordering and missing saved-field rejection |
| `phase5-ordering-green-20260913.xml` | 191 checkpoint/learning tests passed |
| `phase5-optout-red-20260913.xml` / `phase5-optout-green-20260913.xml` | 2 missing-receipt failures, then 17 affected tests passed |
| `phase5-ledger-read-red-20260913.xml` / `phase5-ledger-read-green-20260913.xml` | 6 missing-reader failures, then 52 ledger tests passed |
| `phase5-split-identity-red-20260913.xml` / `phase5-split-identity-green-20260913.xml` | required contract absent, then 48 identity tests passed |
| `phase5-runtime-predecessor-green-20260913.xml` | 12 runtime cases passed, 134.21s including host delay |
| `phase5-predecessor-wiring-20260913.xml` | 213 graph/learning/CLI/workflow tests passed |
| `phase5-packet-preflight-red-20260913.xml` / `phase5-packet-preflight-green-20260913.xml` | 3 unbound-reference failures and valid control, then 172 affected tests passed |
| `phase5-ledger-pointer-red-20260913.xml` / `phase5-ledger-pointer-green-20260913.xml` | 2 rollback/pointer failures, then 66 ledger/runtime tests passed |
| `phase5-canonical-state-red-20260913.xml` / `phase5-canonical-state-green-20260913.xml` | 28 malformed-field failures and valid mid-debate control, then 229 affected tests passed |
| `phase5-sqlite-integration-20260913.xml` | real SQLite crash after real packet publication, rebuilt identity unchanged, successful resume without duplicate resolution or evidence rewrite |
| `phase5-focused-checkpoint-20260913.xml` | required seven-module checkpoint: **333 passed in 2.26s** |

The required seven modules are checkpoint identity, runtime identity, resume,
CLI, graph packet handoffs, decision ledger, and original workflow. The full
eighteen-path scoped Ruff check, CLI/application compileall, offline `uv lock
--check` using canonical Python 3.13.14, and `git diff --check` passed.

Verification accounting: the first ordering receipt is a test-helper syntax
collection failure, not semantic RED. Also, the delayed run named
`phase5-runtime-predecessor-red-20260913.xml` loaded after a source edit and passed
one case; it is not before-fix evidence. Its overlap is excluded from acceptance;
the separate runtime gate and final frozen-source seven-module gate provide the
current proof. All those sessions are terminal; do not restart them.

## Combined-candidate acceptance

The automatic merge had no conflicts. A read-only AST comparison verified exact
preservation of all nine checkpoint-changed and seven canonical-changed CLI
definitions, all new imports, and no duplicate definitions. Helper:
`check_phase5_cli_merge_20260913.py` in canonical SDD.

The first six-module affected gate passed 284 tests and found one stale inventory
mapping: the same two local result/error `queue.put` calls moved from 6298/6310
to 6504/6516. Exact source inspection confirmed unchanged operations and existing
non-trading classifications. Only those two expected locations changed; unknown,
missing and duplicate mutation detection remain strict. The original test bytes
remain in the preservation archive.

The corrected required affected gate passed **285 tests in 20.65s**:
`phase5-merged-affected-corrected-20260913.xml`. Modules: learning context, analyst
execution, analyst concurrency, graph tool routing, Alpaca CLI, and authority-role
alignment. It reported two non-fatal AST-source `SyntaxWarning` messages about
an existing invalid escape sequence. Eighteen-path Ruff, CLI/application
compileall, offline lock check, and staged/working-tree whitespace checks passed;
the inventory-only correction also passed its focused static check.

The 333-test checkpoint proof belongs to `b40683e`; the merged-candidate gate and
exact-definition comparison cover integration with `7c5b9a7`. Unchanged Phase 4
and unchanged checkpoint modules were not broadly retested just for the merge.
This preserves revision-specific evidence rather than claiming every prior test
was rerun on the combined candidate. Phase 10's final complete gate remains due.

Next: Phase 6 source integration and legitimate source-bound learning evidence.
Concurrency stays at 1 until a registered real cohort and model-call authority
permit Task 5.5. No model, broker, holdout, or scheduler authority follows from
source acceptance.
