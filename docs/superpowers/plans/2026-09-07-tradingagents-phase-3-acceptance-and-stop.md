# TradingAgents Phase 3 Acceptance Checkpoint Implementation Plan

> **Execution mode:** Use `superpowers:executing-plans`. The latest user instruction permits the existing workers to finish their current bounded assignments, then requires solo continuation with no more subagents. The current Phase 3 verifier finishes its gate; no new worker or follow-on assignment is authorized.

**Goal:** Independently accept the existing Phase 3 correction, repair only demonstrated acceptance failures if necessary, record a verified checkpoint, and continue to Phase 4 of the full program.

> **Superseding checkpoint update (2026-09-07):** Phase 3 was accepted at
> `63cc7e2983f61b5689c85b96b8d5d1ded2c10e33`. Root then completed the
> Phase 4 source lifecycle on the economic branch through `2f91ccb`; focused
> development and synthetic released-holdout custody proofs passed. This
> historical checkpoint does not authorize a real holdout release, paper
> submission, campaign, or LangGraph work. Phase 4 remains pending its single
> integrated affected gate and canonical fast-forward.

**Architecture:** Continue the existing retained-bytes → verified tournament receipt → pure evaluator → canonical result → admission path. Keep one Sol writer when a correction is required and one independent Sol reviewer/verifier per candidate. Use existing source, fixtures, evidence stores, and worktrees; introduce no service, fetcher, parallel evaluator, or speculative framework.

**Tech Stack:** Existing Python 3.13 environment, Python dataclasses/Decimal, canonical JSON and SHA-256, Typer, pytest, Ruff, and the checked-in `uv.lock`; no dependency changes.

**Spec:** [Program requirements, especially Phase 3](2026-08-30-tradingagents-evidence-first-working-state-completion.md#phase-3--implement-the-real-ta-control-counterfactual-and-statistics) and [frozen economic protocol](../specs/2026-08-24-evidence-first-economic-evaluation-protocol.md). Read both. The original protocol's increment-only exclusions are historical scope; preserve its canonical identity and authority contracts while implementing the later program requirements.

## Global Constraints

- The latest 2026-09-07 user instruction authorizes continuing the full program and supersedes the former Phase 3 stop. Finish this checkpoint before Phase 4 or canonical integration; touch LangGraph only after economic Phases 1–4 are accepted and integrated. Holdout release and optional paper submission still require separate authorization; the campaign still waits for all prerequisite phases.
- The later no-more-subagents instruction supersedes delegated execution wording below. Existing bounded workers finish and stop; root performs subsequent source work, focused proof, a separate self-review pass and the one affected gate. Do not describe solo review as independent or duplicate already-owned gates.
- Every delegated owner, reviewer, and verifier uses `gpt-5.6-sol`. Use the platform's role/context inheritance where compatible with that explicit model. When the parent is not Sol, use a bounded-context fork with the explicit Sol model and a complete lane brief; do not use an incompatible full-history model override or silently substitute a model.
- One writer per worktree. The parent owns canonical planning/checkpoint documentation; the correction owner alone writes economic source/tests. The reviewer returns its receipt to the parent and does not edit source or another owner's report.
- Exactly `cash`, `spy`, `equal_weight`, `momentum_quality`, and `pullback_support`; weekly decisions, 75 primary symbol events per date, benchmark `SPY`, five regular holding sessions, long-only, cash allowed, no leverage, shorts, options, intraday, or social-data arm.
- Retain separately registered 5/10/25/50-bps-per-side costs, zero commission, equal half-spread/slippage split, stable security identity, and exact retained-source custody. No outcomes or memberships may be guessed.
- Every public result remains `analysis_only=true`, `execution_authority="none"`, `can_submit_orders=false`. Negative or statistically null findings are valid completed research results. Missing execution evidence is explicit unavailability, never a fabricated zero return.
- Live control remains byte-identical and all ten automations remain `PAUSED`. No broker/provider/vendor/application-model call, order, cancellation, schedule activation, rearm, outbox delivery, publishing, deployment, purchase, or unrelated-worktree change.
- Use synthetic local fixtures only. Do not copy `.env`, invoke live CLI workflows, install dependencies, or treat `TA_LIVE_SUBMIT=0` alone as permission to contact a broker.
- Focused proof during a correction, one combined review in specification-then-quality order, one affected gate on the reviewed candidate, and no full repository gate until the later final source freeze.
- Preserve both planning documents and the temporary handoff. Source acceptance is not canonical integration, economic qualification, or overall program completion.

---

## Current evidence and file ownership

Verified on 2026-09-07; these are observations, not a future permission token.

| Item | Current state |
| --- | --- |
| Canonical root | `/Users/corbinfloyd/Documents/TradingAgents`, `master`, `93854eb6d1f04bac5e8c36896b5a7252789b6cde` |
| Economic root | `/Users/corbinfloyd/.codex/worktrees/tradingagents-economic-tournament-evidence-20260825` |
| Economic branch/HEAD | `codex/economic-tournament-evidence-20260825`, clean at accepted `63cc7e2983f61b5689c85b96b8d5d1ded2c10e33`; sixteen commits ahead of canonical. Root's one corrected-revision affected gate passed 107 tests in 3884.45s, scoped Ruff/compile/offline lock/diff checks passed, and preservation recheck passed |
| Accepted predecessors | Phase 1 `29e46d4b44b8be3aa63eccb7729c1657178cb408`; Phase 2 `53a286acc9ba07da5b30022352e113dba1a02fd8` |
| Review ranges | Original resumed review: `53a286a..8b528fd`; current correction: `8b528fd..5f3aad`; complete current Phase 3: `53a286a..5f3aad` |
| Available tools | `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python` and `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/ruff`; the economic worktree has no `.venv` |
| Existing proof | Current `5f3aad` owner: F1/F2/F3 plus real CLI 4 passed in 426.77s; strengthened two-date oracle 1 passed in 53.39s; available-v3 compatibility 1 passed in 45.27s; scoped Ruff/diff passed. Earlier owner receipts remain preserved |
| Current acceptance | Root solo acceptance is recorded in `.superpowers/sdd/2026-08-30-tradingagents-evidence-first-working-state-completion/task-3-phase-verifier-report.md`. Phase 3 is technically accepted; Phase 4 may begin, but canonical integration and LangGraph remain closed until Phase 4 acceptance |
| Other feature work | LangGraph retains eleven modified and five untracked paths at `93854eb`; no changes to it in this checkpoint |
| Source task | `01a035fd-9563-7ae0-a4b4-4074198fda82`, latest turn failed/inactive; final message promises Phase 3 proof/review and stop |

The eight original economic feature files are preserved in committed history. Do not attempt to recreate their old dirty status. The canonical plan was untracked before this documentation pass; both planning documents stay uncommitted until the Phase 4 canonical integration boundary. The source task's historical stop instruction in the table is superseded by the current user's full-program continuation, not by a historical acceptance claim.

**Read-only canonical evidence** (absolute root above):

- `.superpowers/sdd/2026-08-30-tradingagents-evidence-first-working-state-completion/progress.md`: accepted predecessor receipts and a stale Phase 3 row.
- `.superpowers/sdd/2026-08-30-tradingagents-evidence-first-working-state-completion/task-3-combined-review.md`: original four P1 findings and ten acceptance questions.
- `.superpowers/sdd/2026-08-30-tradingagents-evidence-first-working-state-completion/task-3-implementer-report.md`: correction commit, self-checks, and honest limitations.
- `.superpowers/sdd/2026-08-17-clean-day-qualification-and-five-day-paper-trial/task-4-report.md`: accepted ten-record automation hash inventory.

**Economic owner boundaries** (paths relative to the economic root):

| Responsibility | Existing files that own it | Existing tests/fixtures |
| --- | --- | --- |
| Official session/open, price window, stable/terminal identity | `tradingagents/dataflows/pit/execution_outcomes.py`, `tradingagents/dataflows/pit/market_calendar.py`, `tradingagents/dataflows/pit/adjusted_price_windows.py`, `tradingagents/dataflows/pit/records.py`, `tradingagents/dataflows/pit/__init__.py` | `tests/test_economic_execution_outcomes.py`, `tests/test_pit_adjusted_price_windows.py`, `tests/test_point_in_time_records.py` |
| Feature/outcome bytes and durable custody | `tradingagents/evals/economic_tournament_evidence.py`, `tradingagents/evals/economic_tournament_evidence_admission.py` | `tests/test_economic_tournament_evidence.py`, `tests/fixtures/economic_tournament.py` |
| Weekly contributions and traded-notional accounting | `tradingagents/evals/economic_tournament.py` | `tests/test_economic_tournament.py` |
| Canonical result and registered statistics | `tradingagents/evals/economic_evaluation_result.py`, `tradingagents/evals/economic_tournament_statistics.py` | `tests/test_economic_tournament_statistics.py`, result/admission assertions in the economic tests |
| Actual CLI/admission route | `cli/main.py`, `tradingagents/evals/economic_evaluation_admission.py` | `tests/test_economic_cli.py`, `tests/test_economic_evaluation_admission.py` |

No new production file is planned. Modify these owners only for a demonstrated Phase 3 acceptance failure. Keep the accepted protocol/cohort design, dependency files, runtime stores, and other worktrees outside the correction.

## Task 1: Establish the candidate and deliver one actionable review

**Files:** Read the canonical evidence above and the full Phase 3 range in the economic worktree. The parent records the returned review in canonical `.superpowers/sdd/2026-08-30-tradingagents-evidence-first-working-state-completion/task-3-acceptance-review.md`, leaving the original blocked review intact.

**Interfaces consumed:**

```text
verify_source_bound_tournament_input(
    *, archive: RawPointInTimeArtifactArchive, value: object,
    protocol: FrozenEvaluationProtocol, eligibility: ValidationPhaseEligibility,
) -> SourceBoundTournamentInput

evaluate_validation_ta_control(
    *, protocol: FrozenEvaluationProtocol, eligibility: ValidationPhaseEligibility,
    candidates_by_event: dict[str, tuple[EconomicTournamentCandidate, ...]],
    execution_outcomes: tuple[SourceBoundExecutionOutcome, ...],
    tournament_input_id: str, tournament_input_sha256: str,
) -> EconomicValidationResult

validate_economic_validation_result(
    value: object,
) -> EconomicValidationResult | LegacyEconomicValidationResult
```

These are existing signatures, not replacement stubs. `SourceBoundTournamentInput` produces `input_id`, `input_sha256`, `candidates_by_event`, and `outcomes`; the CLI must pass that verified view to the evaluator, then use the result in `EconomicEvaluationAdmissionAdapter.admit_evaluation_run`.

**Produces:** One review tied to exact base/HEAD, with a `PASS`, `FAIL`, or `UNPROVEN` row for every criterion below, precise source evidence and test receipt/node IDs, and one deduplicated list of material findings. A material failure must include a concrete input/expected/actual case, the smallest complete regression code or executable reproduction, the exact affected owner files, and required observable repair. No speculative findings, duplicated review roles, or unsupported acceptance.

- [x] **Step 1: Check custody and tool origin.** Run from the economic root:

```zsh
cd /Users/corbinfloyd/.codex/worktrees/tradingagents-economic-tournament-evidence-20260825
git branch --show-current
git rev-parse HEAD
git status --short --branch
git rev-list --left-right --count master...HEAD
git diff --check
git diff --check 53a286acc9ba07da5b30022352e113dba1a02fd8..HEAD
PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python - <<'PY'
import importlib.util
from pathlib import Path
import sys

root = Path.cwd().resolve()
for name in ("tradingagents", "cli", "tests"):
    spec = importlib.util.find_spec(name)
    assert spec is not None and spec.origin is not None, name
    assert Path(spec.origin).resolve().is_relative_to(root), (name, spec.origin)
assert Path(sys.prefix) == Path("/Users/corbinfloyd/Documents/TradingAgents/.venv")
print("Feature source and canonical interpreter identities match")
PY
```

Expected: branch and HEAD match the table, status is clean, current divergence is `0 15`, whitespace checks exit 0, and the origin assertion passes. The initial completed Task 1 preflight was `0 14` at `8b528fd`; the correction advances it without rewriting that history. If HEAD, status, active owner, or control inputs changed, reconcile the new evidence before dispatch; never restore the old snapshot. Use a compact task-status/owner check, not full task history or a machine-wide process dump.

- [x] **Step 2: Check the frozen owners once.** Run the following read-only check; it is also the exact control check used at the final phase checkpoint:

```zsh
/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python - <<'PY'
import hashlib
from pathlib import Path
import re
import stat
import tomllib

root = Path("/Users/corbinfloyd/Documents/TradingAgents")
control = root / "results/policy/live_control.json"
mode = control.lstat().st_mode
assert stat.S_ISREG(mode) and stat.S_IMODE(mode) == 0o600
assert hashlib.sha256(control.read_bytes()).hexdigest() == (
    "a3fc5ddb2b300596833c48c1554fad088ecb43d46bd70aeeac074531d6e9fb07"
)
runbook = root / ".superpowers/sdd/2026-08-17-clean-day-qualification-and-five-day-paper-trial/task-4-report.md"
section = runbook.read_text().split("## Current paused-automation inventory", 1)[1].split("\n## ", 1)[0]
expected = dict(re.findall(r"\| `(tradingagents-[^`]+)` \| `([0-9a-f]{64})` \|", section))
assert len(expected) == 10
automation_root = Path("/Users/corbinfloyd/.codex/automations")
actual = {p.name for p in automation_root.glob("tradingagents-*") if p.is_dir()}
assert actual == set(expected), (actual - set(expected), set(expected) - actual)
for name, digest in sorted(expected.items()):
    path = automation_root / name / "automation.toml"
    assert stat.S_ISREG(path.lstat().st_mode), name
    raw = path.read_bytes()
    assert tomllib.loads(raw.decode())["status"] == "PAUSED", name
    assert hashlib.sha256(raw).hexdigest() == digest, name
print("Frozen control and all 10 paused automation hashes match")
PY
```

Expected: one success line and exit 0. Reuse this result during unchanged source work; do not repeat it before each ordinary read or patch. The stale compact runtime index is navigation only and cannot override these owners.

- [x] **Step 3: Give one Sol reviewer the candidate, contracts, and proof map.** Supply both plan/spec paths, all four evidence paths, the ownership table, the signatures above, exact Git ranges, existing test outcomes and durations, and the protected-operation/no-network boundaries. The reviewer first checks specification compliance and then quality/security in the same pass. It owns later independent verification, but does not run the affected gate while a known blocker remains.

| Criterion | Required observable proof | Existing starting evidence |
| --- | --- | --- |
| Verified production consumption | Retained bytes are reopened before use; exact outcome IDs/digests reach the evaluator, result, report, and run admission, including SPY; free-form legacy returns cannot qualify as v3 | `cli/main.py` route and `tests/test_economic_cli.py::test_economic_tournament_run_binds_only_purged_validation_results` |
| Official observation derivation | The actual custody boundary reconstructs values, timestamps, identities, and exact source spans; source digest equality alone is insufficient | Accepted PIT builders plus `verify_source_bound_tournament_input`; trace the current branch directly |
| All 75 event contributions | A non-anchor symbol's outcome changes its arm-weighted contribution; swapped, missing, or duplicate event/security identity rejects; one weekly aggregation, no multiplication by 75 | `tests/test_economic_tournament.py::test_validation_tournament_uses_only_purged_pit_validation_events` and each feature/outcome event binding |
| Entry/holding/terminal custody | Exact official next-session open and five regular sessions; effective/successor identity, complete dividend/split/symbol-change/merger/acquisition action set, and terminal artifact linkage. Preserve all four named twins (`mid_price`, `next_open`, `executable_quote`, `observed_paper_fill`) with their evidence or explicit unavailable reasons; unproven terminal proceeds invalidate the affected cohort | `tests/test_economic_execution_outcomes.py`, calendar raw replay, adjusted window and records tests |
| Unavailable versus completed findings | Statistical null/negative results complete; missing required open/terminal evidence remains explicit with null return and exact reason through the public path. An isolated unavailable outcome plus a top-level argument error does not satisfy a promised completed-unavailable research result | Current `economic_tournament.py` null branch and `tests/test_economic_execution_outcomes.py::test_missing_next_open_completes_as_unavailable_and_open_must_match` |
| Actual holdings and costs | A two-date production evaluation carries post-return holdings into rebalance and liquidation, charges buys plus sells for all four rates, and preserves compounding. Helper arithmetic alone is insufficient | `tests/test_economic_tournament.py::test_two_date_drift_rotation_uses_full_buy_and_sell_notional` is currently helper-level proof |
| Frozen arm behavior | Exactly five arms; 12-to-1 momentum and PIT TTM operating-income/average-assets ranking; frozen pullback threshold-margin ranking; top-15/symbol-tie/cash policy; no change to search budget or phase isolation | Allocation tests and registered policy/cost identities |
| Computed statistics | Separately count raw source rows, decision events, packet/market clusters, and unique dates without claiming effective sample size. Weekly dates are the primary unit; deterministic registered bootstrap and SPY/cash contrasts; actual Holm ordering/adjustments; drawdown, false-positive rate, cost drag, year/event and per-date position concentration; factor/sector status across all rows; purged/embargoed folds and honest small-sample limitations | `tests/test_economic_tournament_statistics.py` and the existing 256-replicate calculation |
| Canonical validation | Strict nested types, decimals, dates, folds, outcome identities, and statistics identities are rebuilt; rehashed malformed input still rejects. Preserve economically meaningful decimal precision and the accepted narrow integer-cleanup behavior | Existing tampering and nested-identity tests in statistics, result, and custody owners |
| Authority and claims | Zero runtime/broker/model/schedule/control/outbox effects; legacy results stay nonqualifying; source tests produce no profitability, holdout release, or readiness authority | Existing import-isolation/custody tests and authority fields across the actual CLI route |

The graph index is canonical `tradingagents-canonical-master-final-20260822`, ready at `93854eb`, not the economic candidate. Use graph health/search/trace for orientation, then direct branch source. Lack of a graph caller is not a defect by itself. Require the retained-byte invariant at the production owner boundary; do not add redundant calls to a particular builder merely to create a graph edge.

On `8b528fd`, the reviewer must explicitly resolve the `first_event` candidate-cross-section logic, the evaluator's exception on null returns, and helper-only turnover coverage. These are concrete review targets, not claims that a replacement design is already accepted.

- [x] **Step 4: Record the review outcome.** The parent saves the returned evidence to `task-3-acceptance-review.md`. `FAIL` or material `UNPROVEN` proceeds to Task 2. A complete source review with no material blocker proceeds directly to Task 3; it does not itself mark Phase 3 accepted.

Execution receipt: `/root/phase3_verifier` (`gpt-5.6-sol`) reviewed `53a286a..8b528fd` on 2026-09-07. Verdict: one completed-unavailable public-result defect, plus non-anchor and two-date production-proof gaps. Canonical `task-3-acceptance-review.md` records all ten criteria and the corrected partial-overlap top15 accounting oracle. No acceptance gate ran while blocked.

## Task 2: Close only demonstrated Phase 3 failures, if any

**Files:** Only the economic owner paths identified in the actionable Task 1 review, with regressions in their listed test modules or existing shared fixture. The canonical parent appends the correction receipt to the existing `task-3-implementer-report.md`; preserve earlier candidate history.

**Interfaces consumed:** Task 1's exact reproducer/regression code and observed result, existing public signatures above, immutable feature/outcome receipts, and fixed program requirements.

**Produces:** One coherent correction commit, focused before/after proof for its reported failures, a clean worktree, and an exact changed-path receipt. Public interfaces remain as currently defined unless an existing owner's canonical result contract must represent the already-required unavailable state; any such wire change must include its validator, CLI/admission consumer, and legacy-read compatibility in the same slice.

- [x] **Step 1: Transfer sole economic write custody to one Sol worker.** Give it the complete Task 1 review and regression code. It is not alone in the repository: preserve the parent's documentation, the original eight committed economic paths, and every LangGraph dirty file. Recheck the candidate has not moved. No second writer or unsolicited preparation lane.
- [x] **Step 2: Install and run the review's smallest complete regression.** Use the exact failing node IDs supplied in that review, with the canonical interpreter and feature `PYTHONPATH`. A failure must demonstrate the named requirement, not merely missing scaffolding. Reuse existing passing tests when they already prove the case; do not delete correct code to manufacture a RED result.
- [x] **Step 3: Apply the bounded correction at the owning boundary.** For event aggregation, preserve individually bound symbol/event contributions while computing the weekly cross-section once. For unavailable evidence, preserve nulls/reasons and nonqualifying cohort state throughout result/report/admission; never fill returns with zero or label a CLI error a completed record. For cost/statistics gaps, repair the existing production calculation and canonical validation together. The worker supplies actual changed code and its focused receipt; broad redesign is outside this task.
- [x] **Step 4: Run one focused proof covering all changed behavior.** Reuse the Task 1 node IDs and add only the exact production-path regression needed for that correction. A changed source revision justifies the rerun; an unchanged green receipt does not. The first complete receipt must include both code and integration assertions, not just helper-unit results.
- [x] **Step 5: Inspect, stage only owned files, and commit.** Use `git diff --name-only`, `git diff --check`, and the relevant hunks to verify the review's allowlist. Stage explicit filenames from that inspected list; do not use `git add .`, `git add -A`, or broad directory staging. Commit with subject `fix(evals): close phase three acceptance gaps` and a descriptive bullet-point body explaining each actual correction and its observable effect, then record the full commit SHA and clean status.
- [x] **Step 6: Return the changed candidate to the same independent reviewer.** Review the correction against its concrete findings and inspect any touched consumer. Reopen another correction only for a demonstrated material failure. Do not repeat independent specialist reviews or the affected gate while a blocker is known. The parent records which exact findings closed; none are closed by assertion alone.

The corrective code is deliberately supplied by the actionable review rather than invented in advance of its verdict. That is an explicit conditional work boundary: the reviewer must deliver executable reproduction code and exact owner scope before the writer starts. If a necessary repair exceeds Phase 3 or requires closed authority, record that precise blocker and stop without accepting the phase.

## Task 3: Run one affected acceptance gate on the reviewed candidate

**Files:** The eight test modules in the command below, changed economic source/tests for Ruff, and canonical SDD `task-3-phase-verifier-report.md` for the parent's recorded receipt. No application-source writes by the verifier.

**Interfaces consumed:** The reviewed candidate SHA, closed finding list, complete correction/focused receipts, and the unchanged frozen-owner fingerprint.

**Produces:** One revision-bound receipt with commands, exit codes, test totals, test-source origin, static outcomes, and start/end Git state. Phase 3 is accepted only when the source review and this receipt both pass on that exact candidate.

- [ ] **Step 1: Check test selection before running it.** The listed modules use existing hermetic fixtures; exclude any `integration`/`allow_network` marked test and report unexpected deselection. Those markers are not a waiver to contact local broker services. Check synthetic receipt roots and the feature import origin from Task 1. Do not run CLI examples against canonical `results/`.
- [ ] **Step 2: Run this affected test group once.** The receipt-custody test is included because the correction changed that production boundary; it was omitted from the earlier chat gate.

```zsh
cd /Users/corbinfloyd/.codex/worktrees/tradingagents-economic-tournament-evidence-20260825
TA_LIVE_SUBMIT=0 PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q \
  -m 'not integration and not allow_network' \
  tests/test_economic_execution_outcomes.py \
  tests/test_pit_adjusted_price_windows.py \
  tests/test_point_in_time_records.py \
  tests/test_economic_tournament.py \
  tests/test_economic_tournament_evidence.py \
  tests/test_economic_tournament_statistics.py \
  tests/test_economic_evaluation_admission.py \
  tests/test_economic_cli.py
```

Expected: exit 0, all selected tests pass, no external or broker calls, and no unexplained skip/deselection. Read the result; do not predict a passing count. The existing real CLI test took about twenty minutes, so a quiet interval is not evidence of a hang. Retain one running process handle and let the tool yield; never restart or run a duplicate suite because output is quiet.

- [ ] **Step 3: Run the static gate once, sequentially.** Read each exit code before continuing; use raw focused output when RTK filtering would hide a failure.

```zsh
cd /Users/corbinfloyd/.codex/worktrees/tradingagents-economic-tournament-evidence-20260825
/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/ruff check \
  cli/main.py tradingagents/dataflows/pit tradingagents/evals/economic_* \
  tests/test_economic* tests/test_point_in_time* tests/test_pit_adjusted_price_windows.py
/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m compileall -q cli tradingagents
uv lock --check --offline --no-progress
git diff --check
git diff --check 53a286acc9ba07da5b30022352e113dba1a02fd8..HEAD
git status --short --branch
git rev-parse HEAD
```

Expected: every command exits 0 and source status is clean at the reviewed SHA. Offline lock-check failure is an unavailable check, never permission for a dependency upgrade or network call. If a failure requires source changes, return the exact failure to the one writer, then verify the corrected revision; do not accept a candidate whose gate was incomplete.

- [ ] **Step 4: Return one verdict.** Include which existing tests were reused, which regressions were added, source-review closure for every original P1, and the precise command outcomes. No full repository suite, benchmark, cohort run, holdout action, or second broad verification on the same unchanged candidate.

## Task 4: Reconcile the Phase 3 checkpoint and continue

**Files:** Parent-only canonical writes to the existing SDD `progress.md`, `task-3-acceptance-review.md`, `task-3-phase-verifier-report.md`, and this plan's checkpoint checklist. These are planning/acceptance records, not runtime economic results. The original review and temporary handoff remain intact.

**Interfaces consumed:** Exact accepted or blocked SHA, returned combined review, independent verifier receipt, focused receipts, current Git status, and frozen-owner check.

**Produces:** An auditable Phase 3 acceptance record that distinguishes implemented, reviewed, tested, accepted, integrated, and economically qualified states, followed by continuation to Phase 4. Do not mark the overall program complete.

- [ ] **Step 1: Re-run the exact Task 1 frozen-owner check at this phase boundary.** Also compare the live-control, learning-ledger, promotion, and temporary-handoff hashes with the values below. No runtime owner may have changed during this source checkpoint.

```zsh
cd /Users/corbinfloyd/Documents/TradingAgents
shasum -a 256 results/policy/live_control.json \
  results/agent_intelligence/ledger.jsonl results/policy/promotion_state.json \
  /Users/corbinfloyd/.codex/handoffs/2026-08-30-tradingagents-evidence-first-working-state-completion-resume.md
git status --short --branch
```

| Owner | Required unchanged SHA-256 |
| --- | --- |
| Live control | `a3fc5ddb2b300596833c48c1554fad088ecb43d46bd70aeeac074531d6e9fb07` |
| Learning ledger | `10b3c228c1de2ecc91242083df90aac7a47f7cdd870f7e75eca657bd0d28c223` |
| Promotion state | `8b0e5d99cde2db1b59b1c522c458b1ddbde2770be38e18cf27d4b68bda45e196` |
| Temporary handoff | `d7440a09d358d37b4da531be9fe8c2ccd3c59b160438869a2e1f078aab4bd057` |

- [ ] **Step 2: Reconcile the stale progress row without erasing history.** Preserve `43bf815` and its blocked verdict; record `8b528fd` and any later correction SHA with their actual review/proof state. Link the independent receipts. Never describe the old five-modified/three-untracked economic state as current.
- [ ] **Step 3: Complete the checklist below from receipts only.** Record an accepted source checkpoint only if every acceptance item passes. Otherwise leave failed/unproven rows open and identify the exact remaining blocker. Keep the handoff because final program reconciliation, terminal readiness, and unique conversation/request facts are still outstanding.
- [ ] **Step 4: Record the checkpoint and continue.** Record the candidate SHA, acceptance verdict, changed paths, focused/affected/static results, controls, and handoff-retention reason. Once technically accepted, proceed to Phase 4 in the program plan without a routine approval pause. Canonical planning commits/integration belong to Phase 4; LangGraph still waits for accepted economic integration. A real protected-operation or owner-authorization blocker is not waived by the continuation instruction.

### Checkpoint acceptance checklist

- [ ] All ten Task 1 review criteria have affirmative current evidence; every original material finding is closed or explicitly remains blocking.
- [ ] Any correction has a scoped commit and a real focused regression receipt.
- [ ] The single independent affected/static gate passed on the exact reviewed candidate; no result is inferred from prior receipts.
- [ ] Economic worktree is clean; canonical has only the intended planning/checkpoint changes; preserved LangGraph work is untouched.
- [ ] Frozen control and all ten paused automations match the accepted inventory; learning, promotion, and handoff owners are unchanged.
- [ ] The SDD row, combined review, verifier receipt, and this checklist name the same candidate and make no integration/economic-readiness claim.
- [ ] The Phase 3 acceptance checkpoint is recorded; execution continues into Phases 4–12 under the program's ordered gates and the handoff is retained until final reconciliation.

### Documentation validation receipt — 2026-09-07

This plan was prepared from current Git state, the full program/specification, direct Phase 3 source and test inspection, retained owner reports, and the source task's stop instruction. Validation passed for eleven shell blocks, two embedded Python blocks, five local document links, all eight affected test-module paths, and the four cited test names. All twelve program phases remain present. The two read-only preflight snippets ran successfully: feature import origins resolve correctly, frozen control matches, and all ten automation statuses/hashes match. Both untracked planning files produced no whitespace-check diagnostics.

These are documentation/preflight checks, not application-test or source-acceptance receipts. No application suite or runtime workflow ran; economic source remained clean and unchanged. The current review targets remain open until Tasks 1–4 are carried out.
