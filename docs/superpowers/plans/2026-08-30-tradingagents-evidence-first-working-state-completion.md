# TradingAgents Evidence-First Working-State Completion Implementation Plan

> **Execution mode:** Use `superpowers:executing-plans` to continue this approved plan. The user's latest instruction is to finish the existing bounded workers and use no more subagents. Root continues solo after those assignments; do not dispatch or reactivate workers. Earlier delegation details remain historical and are superseded by this instruction.

**Goal:** Bring TradingAgents to a manually verified, evidence-first research and paper-trading working state, then stop with live control frozen and all ten TradingAgents automations paused. A reproducible null or negative economic result counts as a working system; profitability remains `NOT_ESTABLISHED` unless later evidence supports it.

**Architecture:** Preserve the accepted canonical safety and point-in-time foundations. Finish the economic study as a source-bound, phase-safe experiment; integrate complete LangGraph checkpoint identity only after the economic source candidate is accepted; reconcile the existing learning ledger through the same immutable evidence route; qualify the minimum deterministic/retrieval/model research stack; supersede stale readiness and promotion records without deleting history; freeze one final source candidate; and execute the existing one-day qualifier plus five clean market-day manual campaign. LangGraph, analysis packets, and evaluation receipts never carry approval, promotion, holdout-release, live-control, or execution authority.

**Tech Stack:** Python 3.13, Typer, LangGraph `StateGraph` and `SqliteSaver`, canonical JSON, SHA-256, immutable JSON/JSONL evidence, SQLite FTS5/BM25, pytest, Ruff, `uv`.

**Spec:** [Frozen economic protocol](../specs/2026-08-24-evidence-first-economic-evaluation-protocol.md), the phase requirements below, and the accepted source-task amendments recorded in the current checkpoint plan.

## Global Constraints

- The user authorized continuous execution of the full program on 2026-09-07, superseding the earlier Phase 3 stop. Complete each phase's technical acceptance before its dependents; do not pause for routine continuation approval.
- Finish only the already-running Sol assignments, then use no more subagents or follow-on assignments. Root becomes sole implementation/verification owner; use a distinct self-review pass without describing it as independent review. The existing verifier finishes the current Phase 3 gate. Preserve one writer per worktree and one owner of test execution per revision; no duplicate broad tests.
- Live control remains frozen; all ten TradingAgents automations remain `PAUSED` at the accepted hashes. Source work and tests make no broker, provider, vendor, or application-model calls.
- Holdout release and optional paper-only submission each require separate owner authorization. Historical GO, promotion, checkpoint, result, and readiness records confer no execution authority.
- Preserve every existing feature change and evidence file. Keep the temporary handoff until the final program stop and complete reconciliation; the Phase 3 stop does not retire it.
- Retain the functional requirements in Phases 1–12. This is the program map; the linked checkpoint plan supplies the executable steps for the current bounded outcome.

---

## Current continuation — verified 2026-09-07

**Latest source checkpoint — 2026-09-14, adjusted-price REST repair:** The first
full Phase 10 candidate `5771809` was deliberately stopped only after two new
regressions demonstrated a route/body mismatch in the adjusted-price parser.
Its final receipt records pytest exit -15 with unchanged source and protected
owners, not a passing full gate. The isolated repair accepts the actual
single-symbol REST list, binds its response symbol and rejects incomplete or
continuation-only pages; exact source/custody/economic guards remain. Eight
synthetic literals were corrected without changing their data or assertions.
The 13 new contract tests and seven-module 155-test affected gate pass. See
[the repair checkpoint](../checkpoints/2026-09-14-adjusted-price-rest-contract.md).
One corrected full source gate is still required before Phase 10 acceptance.
The retained broad multi-symbol capture is still not an accepted adjusted-window
input, and no actual learning, economic or operational qualification is claimed.

**Latest source checkpoint — 2026-09-13, Phase 8 runner:** Reviewed `0b38a8e`
is combined with canonical `3901c2c`. Two additional boundary defects are repaired:
completion/rollback evidence is checked before promotion replacement, and current
readiness rejects captured-contract mismatch or observed mid-read file changes.
The seven-module affected gate passed 560 tests; existing canonical definitions
and frozen owners are preserved. See
[the Phase 8 source checkpoint](../checkpoints/2026-09-13-phase8-readiness-source-integration.md).
The real historical artifacts pass offline schema/hash checks, but **no actual
supersession or readiness transition occurred**; the stale promotion state is
still unchanged. Complete the remaining evidence prerequisites and accepted-source
freeze/gate without inventing cohort/model results or expanding external authority.
All numbered phases and operational boundaries below remain in force.

**Latest source checkpoint — 2026-09-13, Phase 7 runner:** The retained-only
full-role benchmark is implemented on clean source `f59a40c`, with 341 passing
affected tests and an unmocked clean-Git proof of both actual twelve-role graph
variants using synthetic HTTP responses. See
[the Phase 7 source checkpoint](../checkpoints/2026-09-13-phase7-benchmark-source-preparation.md).
The real 500/300/400/200 corpus, model qualification and Phase 7 acceptance remain
open. The authorized Alpaca paper capture is preserved, but cannot establish
historical source availability. Do not replay that collection or earlier gates.
After local source integration, continue Phase 8's isolated readiness-source
review/integration; actual state transitions still require their evidence and
authority prerequisites. Keep Task 6.2, concurrency qualification, later economic
and operational gates open, and preserve the full program and frozen controls.

**Latest source checkpoint — 2026-09-13, Task 6.1:** Reviewed learning source
`c11a9c4` is combined with canonical `bc579d4`; 205 affected tests, scoped statics,
exact CLI merge preservation, and frozen-owner checks pass. See
[the Phase 6.1 source checkpoint](../checkpoints/2026-09-13-phase6-learning-source-integration.md).
Real Task 6.2 remains pending accepted PIT receipts and a legitimate forecast/event
mapping; the newly retained Alpaca account data does not establish historical
qualification. Continue independent Phase 7 source work without running the real
ledger workflow or inferring new external/model authority. The full program and
all operational acceptance requirements remain unfinished.

**Latest source checkpoint — 2026-09-13, Tasks 5.1–5.4:** The preserved LangGraph
amendment and repairs passed 333 focused tests at `b40683e`. Integration with
canonical `7c5b9a7` preserved both CLI definition sets and passed the corrected
285-test affected gate plus scoped statics. Exact-source safety inventory
locations were updated without relaxing classifications. See
[the Phase 5 source checkpoint](../checkpoints/2026-09-13-phase5-checkpoint-repairs.md).
Next is Phase 6 source integration and evidence reconciliation. Task 5.5 remains
conditional on a registered cohort and model-call authority; concurrency stays 1.
Phases 6–12, real qualification, and the operational campaign remain unfinished.
All protected controls, schedules, holdout and paper-submit boundaries remain.

**Earlier Phase 4 source checkpoint — 2026-09-13:** Phase 4 lifecycle is accepted
and integrated at `4fa91d3` after the one 17-module gate (393 passed plus all
static checks). Canonical then fast-forwarded through isolated Alpaca
bar-shape correction `8fc3296`, with its separate five-module PIT checkpoint
(124 passed) and scoped static proof. The exact revision boundaries and
preservation evidence are in
[the Phase 4 checkpoint](../checkpoints/2026-09-13-phase4-source-acceptance.md).
Do not replay these accepted checks. Next: Phase 5 in the existing LangGraph
worktree, whose sixteen original dirty paths remain intact. Phases 6–12 and
all actual qualification/operational gates below remain unfinished. The
older table and start instruction below are retained historical context.

**Start with the [Phase 3 acceptance checkpoint](2026-09-07-tradingagents-phase-3-acceptance-and-stop.md), then continue through the remaining program.** That checkpoint supersedes the old starting-state instructions below and in the temporary handoff. The user's latest 2026-09-07 instruction removes the interim stop, not the technical gates or protected-operation boundaries. Accepted work must not be replayed.

| Surface | Current evidence | Disposition |
| --- | --- | --- |
| Canonical | `master` at `93854eb6d1f04bac5e8c36896b5a7252789b6cde`; the original completion plan was its only untracked file before this documentation update | Planning changes remain uncommitted until the Phase 4 integration boundary |
| Economic | `codex/economic-tournament-evidence-20260825` at `5f3aad295f87c24be3415875cf15f20d5bc24f04`, clean, fifteen commits ahead | Preserve history and the original eight economic paths already committed into it; source frozen during Phase 3 verification |
| Phase 1 | Accepted through `29e46d4b44b8be3aa63eccb7729c1657178cb408` | Tasks 1.1–1.3 below are retained requirements, not new work |
| Phase 2 | Accepted through `53a286acc9ba07da5b30022352e113dba1a02fd8` | Preserve complete feature/outcome custody and its accepted receipts |
| Phase 3 | Initial `43bf815` and later `8b528fd` required correction; `5f3aad` has focused F1/F2/F3/CLI proof and independent static closure | One affected/static gate is running; technical acceptance remains pending, then continue to Phase 4 |
| Learning source | Isolated `oai/tradingagents-learning-reconciliation-20260907` from Phase 2, clean `c11a9c49cf4f270120aadc41b6d1945d58128b05` | Producer baseline independently reviewed; root completed loader/CLI reachability, current ledger-bound summary and input preservation with self-review plus 149-test affected proof and 122-test final writer proof. No real ledger reconciliation or early phase acceptance |
| Benchmark source | Isolated `oai/tradingagents-research-benchmark-20260907` from Phase 2, clean `d467fd93b756ae801a963011cdb03dd5d72c62a1` | Root fixed paired-model identity with twelve tests passing; real-client metadata contract B9, FTS-before-provider path and full-graph/reviewer wiring remain open. No real model call or early phase acceptance |
| Readiness source | Isolated `oai/tradingagents-readiness-supersession-20260907` from Phase 2, clean `0b38a8ece291c3f0f54940bcdd8336043d116f59`; R1/R2 independently clear | Owner stopped; 52 promotion tests passed. Ordered integration, actual state transition and full Phase 8 acceptance remain pending |
| LangGraph | Still at `93854eb`, eleven modified and five untracked paths | Do not touch until economic Phases 1–4 are accepted and integrated |
| Control and automations | Frozen digest and ten paused hashes match the accepted runbook on 2026-09-07 | Reuse the compact fingerprint while its inputs remain unchanged; check again at the phase checkpoint |
| Learning and promotion owners | Ledger and promotion bytes retain hashes `10b3c228...c223` and `8b0e5d99...e196` | No learning reconciliation or promotion supersession has been performed |
| Temporary handoff | Still hashes to `d7440a09d358d37b4da531be9fe8c2ccd3c59b160438869a2e1f078aab4bd057` | Retain; its historical starting point and active-goal claim are not current authority |

Historically, the source task's last instruction was “stop at next chekoint”; its final response promised Phase 3 proof/review and stop. Its latest turn remains failed/inactive, not independently accepted. The 2026-08-31 reconciliation preserved that boundary and the Sol-only instruction. On 2026-09-07 the user first requested implementation and then explicitly accepted moving onward through the full program without routine stops. That latest instruction supersedes the interim stop. It does not convert unresolved source defects, missing verification, historical packets, or readiness claims into technical acceptance or execution authority.

The economic worktree has **no `.venv` directory**. Use the canonical interpreter and Ruff executables while the current directory and `PYTHONPATH` point to the feature worktree. The checkpoint plan contains exact commands and an import-origin check. In later worktree phases, interpret `.venv/bin/python` and `.venv/bin/ruff` below as the absolute canonical tool paths; do not copy credentials or create another environment just to make the old shorthand work.

The compact context files still summarize the 2026-08-24 snapshot. This documentation pass uses the current owner files directly and does not treat a regenerated index timestamp as fresh economic or operational evidence.

The bounded retained-custody audit is recorded in `.superpowers/sdd/2026-08-30-tradingagents-evidence-first-working-state-completion/task-9.1-retained-custody-inventory.md`. Audited canonical/default caches do not contain admissible PIT archive/raw/window receipts. Legacy caches remain exploratory, not historical admission or source-bound learning evidence; unaudited areas are explicitly identified. This does not block independent source completion or authorize a data/model/broker fetch.

## Execution amendment — natural proportional mode (2026-08-30)

This amendment supersedes the plan's earlier speed-first process guidance. Keep
the functional evidence and trading-safety requirements, but implement them with
the repository's normal defaults and the smallest complete design.

- Reuse existing types, stores, adapters, fixtures, and commands. Add a new
  abstraction only when the required behavior cannot be expressed cleanly in an
  existing boundary.
- Do not add speculative hardening, combinatorial failure matrices, generalized
  frameworks, or future-provider work that is not needed for the current
  acceptance criterion.
- Use one complete writer for a coherent slice, one focused proof when ready,
  one meaningful review at the phase boundary, one affected gate for the accepted
  phase, and the full repository gate once on the final source candidate.
- Rerun a check only when the diff changed or the prior result was invalid. Use a
  representative regression for each material failure mode rather than every
  syntactic variation.
- Prefer an honest `NOT_ESTABLISHED`, `unavailable`, or `readiness_no_go` result
  over building substitute data, model calls, or infrastructure merely to make a
  result look complete.
- Keep the six-session operational campaign because it measures real continuity;
  do not inflate the source phase while waiting for those calendar-bound sessions.

**Primary specifications and runbooks:**

- `docs/superpowers/specs/2026-08-24-evidence-first-economic-evaluation-protocol.md`
- `docs/superpowers/plans/2026-08-24-evidence-first-economic-evaluation-protocol.md`
- `docs/superpowers/plans/2026-08-17-clean-day-qualification-and-five-day-paper-trial.md`
- `docs/superpowers/plans/2026-08-22-task-4-5-source-frozen-shadow-protocol-hardening.md`
- `.superpowers/sdd/2026-08-17-clean-day-qualification-and-five-day-paper-trial/task-4-report.md`
- The active Evidence-First Working-State plan and LangGraph checkpoint amendment in task `01a035fd-9563-7ae0-a4b4-4074198fda82`.

## Historical starting checkpoint — 2026-08-30 (superseded above)

| Surface | Authoritative state | Continuation rule |
| --- | --- | --- |
| Canonical repository | `/Users/corbinfloyd/Documents/TradingAgents`, clean `master` at `93854eb6d1f04bac5e8c36896b5a7252789b6cde` | Do not restart or general-repair canonical |
| Frozen control | `results/policy/live_control.json` SHA-256 `a3fc5ddb2b300596833c48c1554fad088ecb43d46bd70aeeac074531d6e9fb07` | Never refresh, rearm, unfreeze, or rewrite during this plan |
| Automations | All ten `/Users/corbinfloyd/.codex/automations/tradingagents-*/automation.toml` records are `PAUSED`; hashes match the accepted manual runbook inventory | Never change status in this plan |
| Economic protocol | Accepted on canonical; old protocol worktree is clean at `d610c350...`, has no feature-only commits, and is 18 commits behind master | Do not merge or cherry-pick the old worktree |
| Economic source-bound input work | `/Users/corbinfloyd/.codex/worktrees/tradingagents-economic-tournament-evidence-20260825`, branch `codex/economic-tournament-evidence-20260825`, HEAD `93854eb...`; five modified plus three untracked intended paths | Preserve all eight paths; continue here as the sole economic writer |
| LangGraph checkpoint work | `/Users/corbinfloyd/.codex/worktrees/tradingagents-langgraph-evidence-checkpoint-20260824`, branch `codex/langgraph-evidence-checkpoint-20260824`, HEAD `93854eb...`; 16 intended dirty paths | Preserve all 16 paths; repair after economic source is accepted |
| Learning ledger | `results/agent_intelligence/ledger.jsonl` SHA-256 `10b3c228...c223`; 6,244 rows, 4,944 resolved, 1,300 due pending, 4,732 high quality, 80 degraded, 132 suspect, 2,595 packet clusters, 354 provisional market clusters | Back up, audit, resolve to fixed point, and reconcile; never rewrite stored outcomes |
| Real economic evidence | `results/economic_evaluation` is absent | No cohort, admitted protocol, validation run, release, or readiness receipt exists yet |
| Research qualification | No registered parser/retrieval/workflow/injection benchmark exists | Build and run the minimum benchmark after deterministic source is green |
| Operational campaign | `results/manual_shadow` is absent; no qualifier or five-day trial root exists | Start only after final source freeze and readiness supersession |
| Stale policy evidence | `promotion_state.json` still marks `pullback-support` live-enabled; July `GO` and expired tournament are historical | Preserve exact bytes, then supersede through a bounded non-authorizing transition |
| Compact runtime context | `results/_context/latest-summary.json` and `latest-flags.json` were generated `2026-08-24T04:41:36Z` | Refresh after accepted source/runtime inputs change, not during ordinary source edits |

## Non-negotiable boundaries

- No live order, order cancellation, live-control mutation, capital/risk expansion, schedule activation, automation mutation, external message, outbox delivery, publishing, deployment, or autonomous promotion.
- Do not call a broker, provider, model, or vendor during source implementation or its tests. The user's explicit no-live/paper-broker-call boundary remains closed; a future manual campaign preflight does not by itself lift it. Use retained broker evidence or obtain explicit authorization for a required fresh broker read before that operation. Model calls begin only in the registered research benchmark after deterministic lanes are accepted.
- Keep `DEFAULT_CONFIG["checkpoint_enabled"] = False`. Enable checkpointing only at the two explicit analysis-only entry points.
- No new database service. Raw immutable JSON/JSONL remains canonical; per-ticker checkpoint SQLite and a reproducible local FTS5 index are allowed.
- Holdout release is an owner record, not execution or promotion authority. No checkpoint, resume, result, release, readiness packet, or graph state may authorize protected actions.
- Preserve existing dirty worktrees and ignored evidence. Do not reset, clean, rewrite, or delete them.
- Use the compact safety fingerprint while its inputs are unchanged. Recheck it at each phase checkpoint and immediately before any protected runtime operation.

## Default proportional implementation model

- Give one Sol subagent a complete coherent outcome and exact ownership.
  The user's 2026-09-07 request for more parallel implementation authorizes
  isolated Phase 6.1 learning-reporting, Phase 7.1 benchmark-source and Phase 8.1
  legacy-supersession source owners
  alongside the economic owner. These source slices start from accepted Phase 2
  (`53a286a`) in separate worktrees; they do not run evidence campaigns, accept
  dependent phases early, or change the ordered integration gates.
- Keep one writer per worktree. Move to the next writer only at a clean reviewed
  boundary.
- While behavior changes, run the smallest focused test group that proves the
  slice. Run the affected gate once after phase acceptance and the complete
  repository gate once on the final source candidate.
- Use one independent phase review by default. Add a second specialist review
  only for a genuinely distinct high-risk boundary, not as ceremony.
- A failed check that changes source requires the relevant focused rerun. Do not
  replay unchanged green suites without a concrete reason.
- Ox Alpha is optional and not planned. If explicitly substituted for one Codex implementation or one distinct checkpoint review, use the existing bounded high-variant workflow only once on that diff.

---

## Phase 1 — Seal the prospective cohort and weekly experiment identity

**Status:** accepted on the economic branch; retained here for requirements and provenance. Do not repeat Task 1.1.

### Task 1.1: Make raw capture time and source derivation trustworthy

**Owner worktree:** `tradingagents-economic-tournament-evidence-20260825`

**Files:**

- Modify `tradingagents/dataflows/pit/raw_artifacts.py`
- Modify `tradingagents/dataflows/pit/official_observations.py`
- Modify `tradingagents/dataflows/pit/records.py`
- Test `tests/test_point_in_time_raw_artifacts.py`
- Test `tests/test_point_in_time_official_observations.py`
- Test `tests/test_point_in_time_records.py`

**Interfaces and behavior:**

- Add a trusted capture timestamp to `RawPointInTimeArtifactArchive.admit(...)`. Production adapters supply an injected exact UTC clock; a caller-provided historical `retrieved_at` may be retained as source metadata but cannot become the trusted archive-recorded time.
- Persist and validate both source retrieval time and archive-recorded time. Reject noncanonical UTC, archive-recorded time before retrieval, collisions, backdating, symlinks, nonregular files, and changed bytes.
- Extend official SEC and Alpaca derivation so each `PointInTimeObservation` is rebuilt from the retained raw bytes and an exact source span or JSON/XBRL path. Do not accept a wrapper's predeclared value without re-derivation.
- Bind stable `security_id`, effective identity dates, actual Alpaca feed, adjustment mode, session, and source span to every market observation.
- Keep `.env` mode `0600`; `SEC_USER_AGENT` is already present. Do not print its value.

**Focused proof:**

```zsh
TA_LIVE_SUBMIT=0 .venv/bin/python -m pytest -q \
  tests/test_point_in_time_raw_artifacts.py \
  tests/test_point_in_time_official_observations.py \
  tests/test_point_in_time_records.py
```

### Task 1.2: Build a source-verifiable top-100/75/50 cohort

**Files:**

- Modify `tradingagents/dataflows/pit/cohort.py`
- Create `tradingagents/dataflows/pit/cohort_admission.py`
- Modify `cli/main.py`
- Test `tests/test_point_in_time_cohort.py`
- Test `tests/test_economic_cli.py`

**Required cohort receipt:**

- U.S.-listed common stock only; exclude ETFs, ETNs, preferreds, warrants, OTC, inactive, ineffective, and nontradable assets.
- Require an exact prior complete close of at least `$5`.
- Rebuild median daily dollar volume from exactly the preceding 60 complete market sessions in retained Alpaca bytes; no caller-authored aggregate is qualification evidence.
- Preserve candidate input receipts, rejected securities, reasons, source bytes, ranking, cutoff, and selection time.
- Keep ranking order in the canonical universe. `sensitivity_100` is ranked top 100, `primary_75` is its literal first 75, and `sensitivity_50` is its literal first 50. Do not alphabetically resort each cohort.
- Emit one content-addressed cohort receipt with cohort ID/hash and all three universe IDs/hashes.
- `research economic-cohort-build` must open and verify the PIT archive. It remains analysis-only and has no submit option.

### Task 1.3: Enforce weekly dates, symbol events, and complete partitions

**Files:**

- Modify `tradingagents/dataflows/pit/partitions.py`
- Modify `tradingagents/evals/economic_evaluation_protocol.py`
- Modify `tradingagents/evals/economic_evaluation_admission.py`
- Test `tests/test_market_date_partitions.py`
- Test `tests/test_economic_evaluation_protocol.py`
- Test `tests/test_economic_evaluation_admission.py`

**Required model:**

- Register exact weekly decision market dates before outcomes. `cadence="weekly"` must be enforced, not descriptive.
- Require exactly 75 symbol-scoped `DecisionEvent` objects for every registered primary-universe weekly date. Each event remains arm-neutral and retains packet/market cluster identities.
- Assign every event from a market date to the same partition.
- Preserve chronological 60% development, 20% validation, 20% holdout with five-session purge/embargo at each boundary. Reject empty, overlapping, nonexhaustive, future-leaking, or unregistered dates.
- Bind the admitted protocol to the complete cohort ID/hash and complete `MarketDatePartitions` ID/hash, not only to symbol lists and event-ID tuples.
- Reject protocol reuse against a different cohort or partition receipt even when symbols happen to match.

**Phase checkpoint:** Commit the accepted slice as `feat(data): seal source-bound economic cohorts`. One verifier runs the focused files above plus targeted Ruff, compileall, `uv lock --check`, and `git diff --check`.

---

## Phase 2 — Finish durable source-bound tournament input custody

**Status:** accepted on the economic branch. The eight previously dirty paths are preserved in committed history; do not restart them.

### Task 2.1: Split pre-outcome feature evidence from post-outcome evidence

**Files:**

- Refine `tradingagents/evals/economic_tournament_evidence.py`
- Refine `tradingagents/evals/economic_tournament_evidence_admission.py`
- Modify `tradingagents/evals/economic_evaluation_admission.py`
- Modify `tradingagents/dataflows/pit/raw_artifacts.py`
- Modify `cli/main.py`
- Refactor fixtures in:
  - `tests/test_economic_tournament_evidence.py`
  - `tests/test_economic_evaluation_admission.py`
  - `tests/test_economic_cli.py`

**Required behavior:**

- Freeze candidate/security/field-source receipts before outcomes are available. A later outcome receipt may reference, but never rewrite, the feature receipt.
- Bind each candidate to its exact symbol `decision_event_id`, stable `security_id`, effective identity dates, cutoff-safe observation, and registered feature source.
- Bind SPY to an explicit benchmark `SecurityIdentity` and source receipt.
- Reopen every raw artifact and reconstruct its declared source span and value. Comparing only artifact digests is insufficient.
- Reject missing, future, stale, ineffective, mismatched, tampered, or conflicting receipts before evaluation.
- Replace private cross-test import `from tests.test_economic_tournament_evidence import _event_input` with a local/shared fixture module under `tests/fixtures` or duplicate small local builders. Clear both current Ruff `I001` findings.

### Task 2.2: Persist the complete canonical receipt without exceeding store limits

**Interface:** Add a content-addressed, write-once canonical receipt archive beneath the existing economic evidence root. The immutable strategy evidence event stores the receipt ID/hash and predecessor; it does not embed the large receipt.

**Required behavior:**

- Atomic create, owner-only permissions, regular nonsymlink path containment, collision rejection, exact reread, canonical byte comparison, and crash-safe idempotence.
- `admit_evaluation_run`, `frozen_validation_report`, `readiness_status`, and `release_holdout` must reopen and validate the complete receipt. Syntax-only `{input_id,input_sha256}` validation is not enough.
- Do not add a database service or a new strategy evidence kind.
- Add import-isolation/no-side-effect tests proving the pure builder has no filesystem, store, broker, scheduler, runtime, or network dependency.

**Focused proof:**

```zsh
TA_LIVE_SUBMIT=0 .venv/bin/python -m pytest -q \
  tests/test_economic_tournament_evidence.py \
  tests/test_economic_evaluation_admission.py \
  tests/test_economic_cli.py \
  tests/test_point_in_time_raw_artifacts.py
```

**Phase checkpoint:** Commit as `feat(evals): seal source-bound tournament inputs` only after one specification review and one quality/security review have no unresolved P0/P1.

---

## Phase 3 — Implement the real TA-Control counterfactual and statistics

**Status:** implemented but technically unaccepted at `8b528fd`. Use the [current checkpoint plan](2026-09-07-tradingagents-phase-3-acceptance-and-stop.md) to review/correct/verify this implementation, then continue. The original create/modify lists below describe the intended behavior; already-existing modules are not to be recreated.

### Task 3.1: Bind next-open entry, exact five-session holding, and corporate actions

**Files:**

- Create `tradingagents/dataflows/pit/execution_outcomes.py`
- Modify `tradingagents/dataflows/pit/adjusted_price_windows.py`
- Modify `tradingagents/dataflows/pit/records.py`
- Create `tests/test_economic_execution_outcomes.py`
- Expand `tests/test_pit_adjusted_price_windows.py`
- Expand `tests/test_point_in_time_records.py`

**Required outcome contract:**

- Entry is the exact next regular-session open after the decision cutoff.
- Hold exactly five regular sessions; bind entry/exit sessions to the admitted official calendar receipt.
- Include verified dividends, splits, symbol changes, mergers, acquisitions, and terminal proceeds.
- A delisting or acquisition without provable terminal proceeds invalidates the affected cohort; never guess a price.
- Keep stable security identity across candidate and outcome. Reject symbol-only aliasing.
- Produce source-bound mid-price, next-open, timestamped executable-quote, and observed-paper-fill twins when evidence exists. Emit an explicit unavailable state when it does not.

### Task 3.2: Evaluate symbol events once into weekly portfolios

**Files:**

- Refactor `tradingagents/evals/economic_tournament.py`
- Modify `tradingagents/evals/economic_evaluation_result.py`
- Expand `tests/test_economic_tournament.py`

**Required behavior:**

- Compute one arm decision/weight per symbol `decision_event_id`, then aggregate those 75 contributions exactly once per registered weekly date.
- Keep the five arms exactly `cash`, `spy`, `equal_weight`, `momentum_quality`, and `pullback_support`.
- Momentum-quality uses 12-to-1 momentum and latest PIT TTM operating-income/average-assets rank; top 15, equal weight, missing allocation in cash.
- Pullback-support reuses the frozen rule, ranks by threshold margin with symbol tie-breaker, top 15, unused capital in cash.
- Long-only, cash allowed, no leverage, no shorts, no options, no intraday or social-data arm.
- Measure actual position-to-position turnover; do not assume two-way turnover for every decision.
- Run separately admitted 5, 10, 25, and 50 bps-per-side variants, zero commission, equal split between half-spread and slippage.
- Use the same compounding basis for headline and benchmark-excess returns.

### Task 3.3: Add dependence-aware registered statistics

**Files:**

- Create `tradingagents/evals/economic_tournament_statistics.py`
- Create `tests/test_economic_tournament_statistics.py`
- Modify `tradingagents/evals/economic_evaluation_result.py`

**Required result fields:**

- Raw source rows, decision events, packet clusters, market clusters, and unique decision dates.
- Weekly decision dates as primary units and deterministic market-date block-bootstrap confidence intervals.
- Turnover, drawdown, false-positive rate, cost drag, factor/sector exposure, year/event concentration, and position concentration.
- Purged/embargoed walk-forward folds and registered multiple-testing diagnostics.
- Never label the current market-cluster count an effective sample size.
- A null/negative result remains `completed`, analysis-only, and research-only.

**Phase checkpoint:** Commit as `feat(evals): evaluate source-bound ta-control counterfactuals` after focused tests for execution outcomes, tournament, and statistics.

---

## Phase 4 — Complete development, validation, release, and holdout lifecycle

**Accepted/integrated 2026-09-13:** See the revision-bound
[source acceptance checkpoint](../checkpoints/2026-09-13-phase4-source-acceptance.md).
The requirements below remain the contract, not instructions to restart
the completed verifier. This acceptance does not release a real holdout or
establish economic qualification.

**Begin after Phase 3 technical acceptance. Continued execution is authorized in the same program run.**

**2026-09-07 implementation update:** Task 4.1 is implemented on
`codex/economic-tournament-evidence-20260825` through
`2f91ccbf4ebd197f11ad57f28a3e2c74a8d5caf1`: one strict three-phase binding,
phase-bound v4 results/reports, retained-byte replay, a single evaluator, a
pre-read holdout seal, development/validation/holdout immutable admission, and
read-only lifecycle identities. Focused proof includes development admission
and synthetic released-holdout admission; the latter is test-only and does not
authorize or create a real release. Task 4.2 integration and the one affected
gate remain required before acceptance.

### Task 4.1: Admit every phase without leaking the holdout

**Files:**

- Modify `tradingagents/evals/economic_evaluation_admission.py`
- Modify `tradingagents/evals/economic_evaluation_result.py`
- Modify `tradingagents/evals/economic_evaluation_partition_binding.py`
- Modify `tradingagents/evals/economic_tournament.py` and `tradingagents/evals/economic_tournament_evidence.py` where their existing validation-only contracts must consume the selected phase
- Modify `tradingagents/evals/economic_tournament_evidence_admission.py` only where phase selection must flow through retained-byte verification
- Modify `cli/main.py`
- Create `tests/test_economic_evaluation_phases.py`
- Expand `tests/test_economic_evaluation_admission.py`
- Expand `tests/test_economic_cli.py`
- Reuse/extend the existing economic fixture and partition/tournament/receipt tests for changed phase-bound interfaces; do not duplicate the evaluator or evidence store

**Command surface:** Keep the five exact commands. Add `--phase development|validation|holdout` only to `research economic-tournament-run`.

**Existing interface seam:** `MarketDatePartitions` already supplies `development_eligible_event_ids`, `validation_eligible_event_ids`, and `holdout_eligible_event_ids`. The current `bind_validation_phase_eligibility`/`validate_validation_phase_eligibility` pair feeds the CLI, result, evaluator, pure source receipt, and admission/reopen boundary. Extend that shared binding coherently, preserving the existing validation call path and strict canonical reconstruction; a CLI-only phase switch is insufficient. Keep one evaluator and one receipt/admission implementation. Check the current accepted Phase 3 unavailable-result representation before changing consumers so unavailability never becomes release eligibility.

**Lifecycle:**

1. Development inputs are readable and its run is independently admitted.
2. Validation is admitted only against the frozen protocol, cost variant, search budget, diagnostics, and complete source receipts.
3. Holdout inputs cannot be opened through the normal adapter before release.
4. `research economic-holdout-release` binds exact protocol, current store head, releasing owner, release time, and frozen validation report. It grants no other authority.
5. Holdout evaluation becomes readable only after the exact release and is admitted as a distinct run.
6. Readiness reports: protocol admitted, development complete, validation complete, holdout sealed, holdout released, holdout complete, or invalidated.
7. No result writes promotion, influence, paper selection, live control, orders, or execution state.

### Task 4.2: Run one economic affected gate and integrate

Before the affected gate, reconcile current canonical state. At this later integration boundary, the canonical owner commits the exact current planning documents with explicit path staging; the economic owner merges current `master` into the economic branch without rewriting feature history. Then run one verifier on the complete integrated economic candidate, regardless of its scoped commit count. Use the canonical Python/Ruff executables from the economic working directory as described in the current checkpoint plan.

```zsh
TA_LIVE_SUBMIT=0 .venv/bin/python -m pytest -q \
  tests/test_economic_evaluation_protocol.py \
  tests/test_economic_evaluation_admission.py \
  tests/test_economic_evaluation_phases.py \
  tests/test_economic_cli.py \
  tests/test_economic_tournament.py \
  tests/test_economic_tournament_evidence.py \
  tests/test_economic_tournament_statistics.py \
  tests/test_economic_execution_outcomes.py \
  tests/test_market_date_partitions.py \
  tests/test_point_in_time_cohort.py \
  tests/test_point_in_time_official_observations.py \
  tests/test_point_in_time_raw_artifacts.py \
  tests/test_point_in_time_records.py \
  tests/test_pit_adjusted_price_windows.py \
  tests/test_source_bound_resolution.py \
  tests/test_agent_intelligence_reconciliation.py \
  tests/test_learning_availability.py
.venv/bin/ruff check cli/main.py tradingagents/dataflows/pit tradingagents/evals/economic_* tests/test_economic* tests/test_point_in_time* tests/test_pit_adjusted_price_windows.py
.venv/bin/python -m compileall -q cli tradingagents
uv lock --check
git diff --check
```

Fast-forward canonical only after this gate and review accept the exact integrated candidate. If canonical changes again in a way that affects source/configuration, merge and verify the changed candidate before integration. Do not run a full pre-merge economic gate followed by a duplicate unchanged-source gate solely for the planning-document commit. Do not run the full repository suite in this phase.

---

## Phase 5 — Repair and integrate LangGraph evidence-safe checkpointing

Begin only after Phase 4 is accepted on canonical. Preserve the 16 intended dirty paths in `tradingagents-langgraph-evidence-checkpoint-20260824`.

### Task 5.1: Validate stored state before any pending-resolution side effect

**Files:**

- Modify `tradingagents/graph/trading_graph.py`
- Modify `tests/test_checkpoint_resume.py`
- Modify `tests/test_learning_context.py`

**Required behavior:**

- When a checkpoint exists, load and completely validate identity, `run_id`, `run_started_at`, packet references, learning context, and canonical stored fields before `_resolve_pending_entries()` or any graph invocation.
- Skip pending-resolution work entirely on an accepted resume. Run it exactly once for a genuinely fresh run.
- Add tests for each malformed stored field proving zero market-data read, reflection-model call, memory write, packet write, or graph invocation before rejection.
- Preserve the mismatched checkpoint for inspection.

### Task 5.2: Record explicit `--no-checkpoint` opt-out

**Files:**

- Modify `cli/main.py`
- Modify `tests/test_checkpoint_cli.py`
- Modify `tests/test_original_tradingagents_workflow.py`

**Receipt fields:**

```json
{
  "mode": "disabled",
  "identity_digest": null,
  "checkpoint_step": null,
  "qualifying": false,
  "analysis_only": true,
  "execution_authority": "none",
  "can_submit_orders": false
}
```

Persist the receipt beside the saved interactive analysis report. Do not propagate it or the checkpoint default to generic programmatic, broker, execution, paper-submit, promotion, owner-approval, or scheduler paths.

### Task 5.3: Name and bind the predecessor contract precisely

**Files:**

- Modify `tradingagents/graph/checkpoint_identity.py`
- Modify `tradingagents/graph/checkpoint_runtime_identity.py`
- Modify `tradingagents/graph/trading_graph.py`
- Modify `tradingagents/orchestration/decision_ledger.py` only if needed
- Modify identity/resume/packet tests

**Decision:** Bind two separate stable inputs:

- `learning_evidence_predecessor`: the pre-run `results/learning_availability/events.jsonl` head.
- `decision_ledger_predecessor`: the authenticated pre-run DecisionLedger head under `results/control_plane/decisions`.

Capture both before graph execution. On resume, accept the exact pre-run head plus only authenticated events belonging to the same `run_id`; reject unrelated head advance, rollback, collision, or missing provenance. Do not recalculate the predecessor as if the current run's own idempotent packet events were external drift.

### Task 5.4: Accept the existing checkpoint amendment

Preserve the already implemented identity, custody, exact-clear/status/retention, replay-idempotence, analysis-only defaults, and generic default-off behavior. Do not upgrade LangGraph, add subgraphs, or add interrupts.

Run one focused verifier after the P1 repairs:

```zsh
TA_LIVE_SUBMIT=0 .venv/bin/python -m pytest -q \
  tests/test_checkpoint_identity.py \
  tests/test_checkpoint_runtime_identity.py \
  tests/test_checkpoint_resume.py \
  tests/test_checkpoint_cli.py \
  tests/test_graph_packet_handoffs.py \
  tests/test_decision_ledger.py \
  tests/test_original_tradingagents_workflow.py
```

After merging updated canonical into the LangGraph branch, run one affected gate:

```zsh
TA_LIVE_SUBMIT=0 .venv/bin/python -m pytest -q \
  tests/test_learning_context.py \
  tests/test_analyst_execution.py \
  tests/test_graph_analyst_concurrency.py \
  tests/test_graph_tool_routing.py \
  tests/test_alpaca_cli.py \
  tests/test_authority_role_alignment.py
```

Then targeted Ruff, compileall, `uv lock --check`, and `git diff --check`. Commit and integrate before any operational campaign. Update the stale compatibility comment in `tradingagents/__init__.py` only as a nonblocking documentation cleanup; do not change dependency versions.

### Task 5.5: Measure analyst concurrency separately

After the registered research cohort exists and model calls are permitted, compare the same cohort at concurrency `1` and `2`. Bind concurrency in checkpoint identity; record wall time, retries/rate limits, tokens, cost, completion, packet/evidence integrity, and registered quality. Keep `1` unless `2` improves time without worse evidence, completion, rate limiting, or quality. Generated benchmark receipts stay in the established ignored results location.

---

## Phase 6 — Reconcile the existing learning ledger to a source-bound fixed point

### Task 6.1: Complete dependence reporting

**Files:**

- Modify `tradingagents/evals/agent_intelligence_reconciliation.py`
- Modify `tradingagents/evals/learning_availability.py`
- Modify `tradingagents/evals/source_bound_resolution.py` and `tradingagents/evals/agent_intelligence_ledger.py` for the verified economic-identity producer, canonical local loader, and exact ledger-bound summary
- Modify `cli/main.py`
- Test `tests/test_agent_intelligence_reconciliation.py`
- Test `tests/test_learning_availability.py`
- Extend `tests/test_source_bound_resolution.py`, `tests/test_agent_intelligence_ledger.py`, and the existing retained-protocol fixture in `tests/test_economic_evaluation_protocol.py` where those producer/CLI contracts change

Add unique economic `decision_event_id` count and unique decision-market-date count to the reconciliation receipt. Continue reporting raw rows, resolved/pending, packet clusters, provisional market clusters, suspect/degraded/high-quality counts, and explicit estimator status. Never call 354 clusters an effective sample size.

**Source accepted 2026-09-13:** The merged 205-test source checkpoint above covers
this reporting contract and real CLI wiring. This does not complete Task 6.2 or
accept the actual learning ledger as source-bound evidence.

The source path now accepts paired `--pit-economic-protocol` and `--pit-forecast-event-bindings` with the existing archive/raw/window options on resolve, quality-audit, and reconciliation. These are explicit validated inputs, not an inferred historical crosswalk or a grant of economic admission. Before real Task 6.2 execution, supply accepted receipts and a legitimate mapping; absent inputs remain unavailable. Source proof is recorded in `.superpowers/sdd/2026-08-30-tradingagents-evidence-first-working-state-completion/task-6.1-cli-bridge-c11a9c4.md`.

### Task 6.2: Execute the fixed-point reconciliation after PIT receipts exist

1. Record the current ledger hash and create a timestamped backup through the existing backup path.
2. Run `research ledger-quality-audit --backup` with the accepted PIT archive, raw receipts, and adjusted-price-window receipts.
3. Run `research agent-ledger-resolve` repeatedly against the same source-bound inputs until `newly_resolved_count=0`.
4. Leave genuinely missing, stale, action-ambiguous, or nonmatching rows pending with exact deterministic reasons.
5. Never rewrite stored outcomes; mark unverifiable/inconsistent labels `suspect`.
6. Exclude suspect rows from learning/economic claims. Disclose degraded rows separately and use only where existing quality policy permits.
7. Regenerate summary, resolution-quality packet, learning-availability events, and reconciliation receipt.
8. Require summary freshness `current` rather than `unverifiable_legacy_summary`.

No replacement ledger or database is authorized.

---

## Phase 7 — Qualify the minimum research stack

### Task 7.1: Add a registered analysis-only benchmark runner

**Files:**

- Create `tradingagents/research/qualification_benchmark.py`
- Modify `tradingagents/research/model_routing.py`
- Modify `tradingagents/research/model_telemetry.py`
- Modify `tradingagents/research/source_quality.py`
- Modify `tradingagents/research/memory.py`
- Modify `cli/main.py`
- Create `tests/test_research_qualification_benchmark.py`
- Expand routing, telemetry, source-quality, retrieval, and authority/import-isolation tests

**Command:** `research research-stack-benchmark`

**Lanes:** deterministic SEC/XBRL extraction; metadata plus SQLite FTS5/BM25; one source-bound existing OpenRouter model; full TradingAgents graph; different-model reviewer only for registered ambiguous cases; no-text twin for every text/model lane.

**Receipt:** requested and actual provider/model/revision, route, prompt hash, fallback, tokens, latency, cost, privacy mode, source spans, outcome IDs, checkpoint identity, and authority-free fields. No silent fallback.

**Registered minimum cohort:** 500 filing/document pages; 300 temporal/restatement/contradiction/cutoff questions; 400 workflow-grounded cases; 200 injection cases spanning text, tables, PDFs/images, repository documents, and tool output.

**Acceptance:** 99.5% critical-field accuracy and 100% high-severity accuracy; zero authority changes, secret disclosure, or source-contract bypass; no model/retriever/reviewer/full-graph lane retained unless it improves registered source accuracy or resolved forecast quality after cost. Otherwise keep deterministic/BM25 or the simplest winning lane.

Do not purchase data, install a managed graph/vector database, add agents, fine-tune, or revive Zep/MiroFish. OpenRouter is the only planned model route and is used only after deterministic lanes pass.

---

## Phase 8 — Supersede stale readiness and promotion state

### Task 8.1: Add bounded legacy supersession

**Files:**

- Modify `tradingagents/policy/promotion.py`
- Modify `tradingagents/policy/promotion_sync.py`
- Modify `tradingagents/brokers/paper_tournament.py`
- Modify `cli/main.py`
- Expand promotion, paper-tournament, readiness, and authority tests

**Preserve exact historical evidence:**

- July `GO` packet SHA-256 `e5077702...82af`
- Current promotion state SHA-256 `8b0e5d99...e196`
- Expired paper tournament ledger SHA-256 `a511ab7a...d7a1`

Add a fail-closed immutable legacy-root retirement/supersession receipt. Do not overwrite or delete the expired ledger. Atomically replace current promotion state through the existing trusted writer so every sleeve is `paper_only`, `live_enabled=false`, with reason `economic qualification pending` or the accepted null/negative verdict. `live_control.json` remains byte-identical.

### Task 8.2: Emit a current non-authorizing readiness packet

Record:

- July `GO` superseded as historical;
- profitability `NOT_ESTABLISHED` unless accepted evidence says otherwise;
- economic qualification pending or exact accepted verdict;
- all sleeves paper-only and live-disabled;
- shadow phase `qualification_pending`;
- frozen live-control digest;
- all ten paused automation IDs/hashes;
- analysis-only/no-authority fields.

Refresh compact context after this accepted evidence transition. Run a fresh analysis-only TSM loss review and BOARD decision containing allowed exit reason, supporting source, thesis status, and confidence. Preserve HOLD or unresolved; execute nothing.

---

## Phase 9 — Produce real economic and research evidence

### Task 9.1: Decide historical versus prospective cohort honestly

- Audit whether free retained SEC/Alpaca evidence can prove historical membership, source availability, corporate actions, and terminal proceeds.
- If yes, admit the audited historical route under the same protocol.
- If not, label it exploratory and freeze a prospective cohort before outcomes.
- Never backfill membership or fabricate terminal outcomes.

Run, in order:

1. `research economic-cohort-build`
2. `research economic-protocol-admit`
3. development `research economic-tournament-run`
4. validation `research economic-tournament-run`
5. `research economic-readiness-status`
6. owner-reviewed `research economic-holdout-release`
7. holdout `research economic-tournament-run`
8. final `research economic-readiness-status`

Each command writes one canonical analysis-only receipt and exposes no submit flag. A prospective route may require an outcome wait longer than the later six-session operations program. During that wait, the correct state is `economic qualification pending`.

### Task 9.2: Run the registered research benchmark

Run deterministic and FTS/BM25 lanes first. Only then use the existing OpenRouter route for the registered single-model/full-graph/reviewer lanes. Record the simplest accepted stack or a no-model verdict. Do not make provider/model calls outside the registered cohort.

---

## Phase 10 — Freeze the final source candidate once

At the accepted source boundary:

1. Require clean canonical Git status and record the exact revision.
2. Reconfirm dependency/model/config/runtime identities.
3. Run the complete repository gate exactly once:

```zsh
TA_LIVE_SUBMIT=0 .venv/bin/python -m pytest -q
.venv/bin/ruff check cli tradingagents scripts tests
.venv/bin/python -m compileall -q cli tradingagents scripts
uv lock --check
zsh -n scripts/mac/ta_job.sh
git diff --check
```

4. Re-index canonical TradingAgents and verify coverage for every changed source path.
5. Record changed paths/hashes, focused and affected results, the full gate, protocol/store/receipt IDs, ledger counts, benchmark verdict, live-control digest, and ten automation statuses.
6. Do not rerun the full suite on ordinary runtime evidence days unless source changes.

---

## Phase 11 — Execute the one-day qualifier plus five clean market days

Use the exact future-only command order in `.superpowers/sdd/2026-08-17-clean-day-qualification-and-five-day-paper-trial/task-4-report.md`. Do not improvise the stage order.

Before starting, reconcile each stage against the current explicit boundaries. In particular, source acceptance, the calendar arriving, and this runbook do not override the user's no-live/paper-broker-call instruction. If a required stage needs a fresh broker call rather than retained evidence, pause that operation for explicit authorization; do not substitute a fabricated stage receipt.

### Task 11.1: Qualifier

On the first authenticated regular U.S. equities session after source freeze:

1. Create a fresh qualifier start before other stages.
2. Immediately prove all ten automations retain the frozen paused hashes.
3. Run one capped one-ticker overnight graph pass, premarket brief, preopen validation, hourly dry run, bound sentinel, read-only reconciliation, loss review, BOARD, no-execute self-heal handoff/plan, and local-only daily report.
4. Initialize a distinct one-day qualifier paper root and run the paper tournament dry-run.
5. Default to no paper submission. One paper-only submit requires separate owner authorization and every endpoint/clock/calendar/lease/reconciliation gate; never submit on a repair day.
6. Bind exactly twelve stages into one manifest and adjudicate once.
7. If failed/incomplete, preserve evidence, close/expire the pending day through the accepted fail-closed facade, use the next session for repair, review any source change, and require a new qualifier.

### Task 11.2: Five-day trial

After one clean qualifier, initialize a separate five-market-day root. Repeat the same chain for five distinct clean regular sessions. The qualifier is not Day 1. Any failed/incomplete day resets the streak to zero and forces repair plus a new qualifier.

After clean Day 5:

- finalize the paper lease;
- prove further submissions reject;
- prove all ten automations remain paused;
- emit exactly one terminal `readiness_candidate` or `readiness_no_go` record.

The campaign proves operational continuity, not profitability or live readiness.

---

## Phase 12 — Native UI stop checkpoint

Do not change automation status. Prepare, but do not execute, the future activation card:

- Future owner-eligible only: overnight research, execution BOARD, daily report, self-healer, paper tournament, preopen validation, safety sentinel.
- Keep paused even in a future observer phase: market supervisor, wake controller, sleep controller.
- Show the exact seven records, paused hashes, Central and UTC next-run times, frozen-control digest, current no-submit evidence, and rollback steps before any future status change.
- Daily reporting stays local-only unless outbox delivery is separately authorized.
- Any future activation must first pass a no-submit shadow-equivalence window.
- Live-control rearm, live orders, capital/risk expansion, and autonomous promotion remain separate owner-approved projects.

## Final acceptance checklist

- [ ] Economic protocol binds source-verifiable cohort, complete partitions, weekly dates, symbol events, and phase lifecycle.
- [ ] Development, validation, and released holdout run from durable source receipts; null/negative is accepted without promotion.
- [ ] LangGraph resumes by default only at analysis-only entry points and rejects every complete-identity or saved-state mismatch before side effects.
- [ ] Packet/evidence/ledger replay remains idempotent at registered crash boundaries.
- [ ] Existing learning ledger reaches a deterministic source-bound fixed point with suspect/degraded/dependence disclosures.
- [ ] Minimum research-stack benchmark selects the simplest registered winning lane or records a valid no-model result.
- [ ] July `GO`, old promotion state, and expired tournament are preserved and superseded; every sleeve is paper-only/live-disabled.
- [ ] Final source candidate passes the single complete repository gate and is re-indexed.
- [ ] One clean qualifier and five clean trial sessions produce exactly one terminal non-authorizing readiness record.
- [ ] `results/policy/live_control.json` still hashes to `a3fc5ddb...fb07`.
- [ ] All ten TradingAgents automations are still `PAUSED` with the accepted hashes.
- [ ] No schedule activation, live order, cancellation, control rearm, outbox delivery, publication, deployment, paid vendor, or autonomous promotion occurred.

## Handoff and retirement rule

### Canonical ingestion record — 2026-09-07

The temporary handoff was read end to end again during execution and still hashes to `d7440a09d358d37b4da531be9fe8c2ccd3c59b160438869a2e1f078aab4bd057`. The following reconciles its request/unfinished-work tables against current receipts; it is not permission to delete it before the final program checkpoint.

**Historical provenance retained:** the handoff was created `2026-08-30T19:49:52Z` for source task `01a035fd-9563-7ae0-a4b4-4074198fda82`. Its prior user-request audit covered `2026-08-24T22:56:47Z` through creation using the 47 MB rollout `/Users/corbinfloyd/.codex/sessions/2026/08/24/rollout-2026-08-24T17-56-46-01a035fd-9563-7ae0-a4b4-4074198fda82.jsonl`. That prior audit reported no material missing user requests; this ingestion does not claim to have repeated a full 47 MB history audit. Its source-task active-goal claim and original resume-at-Task-1.1 instruction are historical, superseded by current verified progress and this task's full-program goal.

| Handoff request or unfinished item | Current disposition and canonical destination |
| --- | --- |
| Preserve/finish old protocol Task 1; derived-ID forwarding repair; reported 42 then 88 focused passes | Historically accepted/integrated, protocol commit `aac2953`; old worktree `d610c350` is not a merge source. Preserve canonical protocol and the Phase 1 accepted receipts; do not rerun the old task. |
| Native UI steps and goal | Current full-program goal is active. Phase 12 remains a future preparation-only activation card, not schedule authority. |
| Audit old conversation and define a working system | This program's ordered requirements and current-continuation table supersede the old starting snapshot; technical proof and real evidence remain separate. |
| Implement full evidence-first plan; hurry without redundant tests; complete v2 ownership | Active. One Sol phase owner per worktree, focused proof, one independent verifier/revision, one affected phase gate, one final source gate. The latest user request explicitly removes the interim Phase 3 stop. |
| Add LangGraph checkpoint amendment before campaign | Active, untouched sixteen-file work preserved by exact SHA-256 in canonical SDD `task-3-preservation-2026-09-07.json`. Phase 5 remains after economic integration. Historical `300 + 81` tests are not current acceptance. |
| Write plan and create handoff | Completed as planning/transport artifacts; source implementation and final retirement remain distinct. Commit the current canonical plans at the Phase 4 integration boundary. |
| Trusted capture, official spans/values, effective top100/75/50 cohort, complete partitions/weekly events | Phase 1 accepted through `29e46d4b44b8be3aa63eccb7729c1657178cb408`; canonical SDD `progress.md` records scoped commits, reviews, and 130-test phase gate. |
| Durable complete source-input custody instead of ID-only syntax | Phase 2 accepted through `53a286acc9ba07da5b30022352e113dba1a02fd8`; canonical SDD Task 2 reports/review/verifier preserve proof. |
| Next-open/five-session/action outcomes, exact weekly aggregation, cost variants/twins/turnover/statistics | Phase 3 correction at `8b528fd` has independent review, not acceptance. Canonical `task-3-acceptance-review.md` requires completed-unavailable public results plus non-anchor and partial-overlap two-date production proof. Earlier economic `33` tests and two import-order findings are historical intermediate evidence, not a restart point. |
| Development and released holdout lifecycle | Pending Phase 4, after Phase 3 technical acceptance. Actual holdout release remains separately owner-authorized. |
| Resume validation before pending-resolution effects; explicit no-checkpoint receipt; two predecessor heads | Pending Phase 5 Tasks 5.1–5.4. Existing dirty identity/runtime/graph files are retained, not re-created. |
| Resolve due forecasts and reconcile learning dependence/freshness | Pending Phase 6. Existing ledger remains unchanged at `10b3c228...c223`, with the handoff's 6,244 total / 4,944 resolved / 1,300 due-pending counts retained as the baseline. Do not claim counts changed without new evidence. |
| Registered deterministic/retrieval/model research benchmark | Pending Phases 7 and 9.2; exact cohort, accuracy/security thresholds, registered model route and no-model fallback remain specified above. |
| July GO, live-enabled promotion, expired paper ledger | Pending Phase 8 non-authorizing supersession. Preserve historical bytes before the trusted transition; current `live_control.json` is never rewritten. |
| Real economic receipts and manual-shadow qualifier/five-day campaign | Pending Phases 9–11 and their explicit prerequisites. Audit historical source sufficiency first; prospective outcomes may require a real calendar wait. No fabricated membership, prices, terminal proceeds, or readiness. |
| Concurrency 2 | Pending registered comparison in Task 5.5; keep 1 unless measured evidence supports 2. No new LangGraph version, subgraphs, interrupts, managed database, or replacement ledger is authorized. |

The original eight economic dirty files now live in preserved feature history; the sixteen LangGraph dirty files remain dirty and untouched. Old protocol/PIT worktree cleanliness and long-lived n8n/Alpaca MCP process presence were historical observations, not instructions to merge, call, kill, or modify them. Current source-work preflight found no competing economic writer/test/runtime invocation and reverified the authoritative frozen control plus ten paused automation records.

**Retirement remains pending:** the final program checkpoint, real evidence/readiness reconciliation, owner-gated decisions, and final no-unique-information comparison have not been completed. Do not claim that no unique information remains in the handoff yet.

Retain `/Users/corbinfloyd/.codex/handoffs/2026-08-30-tradingagents-evidence-first-working-state-completion-resume.md` until every still-live unique fact in it is reconciled into accepted canonical source/evidence and the final program stop checkpoint is recorded. The Phase 3 acceptance checkpoint is not this retirement boundary.

- [ ] Re-read the entire handoff and reconcile every unfinished-request row, owner-file reference, branch/HEAD assertion, and unique conversation instruction to an exact canonical destination or an explicitly superseded historical disposition.
- [ ] Compare current canonical Git state, immutable evidence IDs, terminal readiness, frozen-control digest, and all ten paused automation records. Record the final stop checkpoint and explicitly confirm that no unique information remains in the temporary handoff.
- [ ] Re-read the applicable project instructions. Delete only the exact temporary handoff path, and only if those instructions permit deletion and both preceding checks pass; preserve all other evidence, dirty feature files, and unrelated user changes.
- [ ] Verify the exact handoff path is absent after deletion and report its removal and recoverability. If any prerequisite or deletion verification fails, retain the handoff and report the specific reason; never imply it was retired successfully.
