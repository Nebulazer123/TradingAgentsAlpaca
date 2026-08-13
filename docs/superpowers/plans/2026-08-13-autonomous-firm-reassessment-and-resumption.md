# Autonomous Firm Reassessment and Resumption Implementation Plan

**Execution status (2026-08-13):** The root-correct autonomous-firm candidate was independently reviewed, repaired through RED-GREEN cycles, and fast-forwarded into canonical `master` at `e14a78a11960e07f5a720a158c26ca4fe02aa02a`. Final candidate verification was 3,562 passed, 1 intentionally skipped live-API test, 75 subtests passed, Ruff clean, compileall clean, and no test failures. Runtime rollout, read-only reconciliation of the owner-initiated NFLX sale, the five-market-day evidence window, and any separately authorized live rearm remain later tasks; integration itself did not alter live control, broker state, credentials, or schedules.

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the already-built autonomous-firm branch into the canonical TradingAgents repository, independently prove its safety boundaries, restart only non-trading autonomous work in Central Time, and accumulate the evidence required before any separate consideration of live trading.

**Architecture:** The canonical repository remains the only runtime source of truth. The historical autonomous-firm branch is treated as a candidate implementation, not as production: it is merged into a disposable integration worktree, tested, independently reviewed, and only then merged into canonical `master`. The runtime then progresses through read-only reconciliation, autonomous research/paper/shadow operation, and five observed regular market days. Live control remains frozen until all required external and local evidence is current; no implementation task itself can unfreeze or trade.

**Tech Stack:** Python 3.10+, existing `.venv`, pytest, Ruff, py_compile, Git worktrees, codebase-memory graph, JSON/JSONL evidence, Codex automations, `America/Chicago` scheduling, Alpaca read-only APIs, and the existing TradingAgents policy/execution/recovery modules.

## Reassessment Snapshot — 2026-08-13

| Fact | Current evidence | Consequence |
| --- | --- | --- |
| Canonical runtime checkout | `/Users/corbinfloyd/Documents/TradingAgents`, `master` at `ce2dd43` | All runtime reads, schedule work, and final merges happen here. |
| Autonomous-firm implementation | `codex/autonomous-trading-firm` is `6` commits behind and `128` commits ahead of `master`; head `6f8fa28` | It must be merged and re-proven; its worktree is not production. |
| Merge preview | A direct merge stopped at 67 unmerged paths because the candidate still nests the application under `01_REPO/tradingagents-main` | Re-root the candidate *diff* into a fresh disposable worktree; do not resolve that historical merge in place or merge directly into `master`. |
| Live state | `results/policy/live_control.json` has `frozen: true` | The NFLX evidence conflict remains a hard stop for all live submissions and re-arm. |
| Latest observer evidence | Overnight, preopen, and hourly packets are dated 2026-07-30; overnight graph had 2/3 failures | It is stale and cannot support an August decision or live gate. |
| Schedules | Ten TradingAgents automations are `PAUSED`; all already use `failed_runs_only` | Preserve pause until the code and observer chain pass. Verify Central Time through the automation API before any restart. |

## Global Constraints

- Keep `results/policy/live_control.json` frozen. Do not refresh, re-arm, edit a risk envelope, submit/cancel/replace an order, or alter broker credentials during this plan.
- The machine may choose research, paper, strategy, and recovery actions inside the charter. It may never invent missing broker history, external execution evidence, account authority, or credentials.
- All live-path changes require RED-GREEN tests, targeted verification, a fresh source review, and an exact caller inventory before integration.
- A test fake or a local packet never proves a broker action happened. Broker account/order truth is read-only evidence and must remain separately reconciled.
- The central schedule standard is `America/Chicago`: regular equities session is 8:30 AM–3:00 PM Central. Every automation notification setting is `failed_runs_only`.
- Use one integration worktree and one serial verification process for shared evidence tests. Do not run overlapping tests that mutate the same temporary evidence paths.
- Use compact packets and deterministic checks for routine monitoring. Escalate model reasoning only for new market synthesis, genuine incident diagnosis, design changes, or independent review.
- Git is the collaboration record for source, tests, plans, review reports, and small durable manifests. It is not a substitute for broker state, local credentials, or runtime evidence.

---

### Task 1: Create the canonical integration baseline

**Files:**
- Read: `/Users/corbinfloyd/Documents/TradingAgents/START_HERE.md`
- Read: `/Users/corbinfloyd/Documents/TradingAgents/results/policy/live_control.json`
- Create at execution time: `/Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm-integration`
- Read: `codex/autonomous-trading-firm`

**Produces:** a clean, root-correct integration branch based on current canonical `master`, a recorded re-root decision, and no runtime changes.

- [ ] **Step 1: Capture the pre-integration authority snapshot**

Run:

```zsh
cd /Users/corbinfloyd/Documents/TradingAgents
git status --short --branch
.venv/bin/python scripts/automation_context_snapshot.py --write
sed -n '1,220p' results/policy/live_control.json
sed -n '1,220p' results/_context/latest-summary.json
```

Expected: clean `master`; `frozen: true`; context is refreshed without broker writes.

- [ ] **Step 2: Record the direct-merge rejection, then leave its evidence untouched**

Run:

```zsh
cd /Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm-integration
git diff --name-only --diff-filter=U
```

Expected: the historical direct merge remains unresolved for evidence. It is not an implementation workspace and must not be resolved, reset, deleted, or tested.

- [ ] **Step 3: Create a fresh re-root integration worktree**

Run:

```zsh
cd /Users/corbinfloyd/Documents/TradingAgents
git worktree add -b codex/autonomous-firm-reroot \
  /Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm-reroot master
cd /Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm-reroot
BASE=$(git merge-base ce477046e2185ea35bba06458b9eb7f6c6a8e23e codex/autonomous-trading-firm)
git diff --name-only "$BASE"..codex/autonomous-trading-firm | \
  rg -v '^01_REPO/tradingagents-main/' && exit 1 || true
```

Expected: every candidate code change is under exactly `01_REPO/tradingagents-main/`; the fresh re-root worktree begins clean at current `master`.

- [ ] **Step 4: Apply the candidate diff only after mechanically re-rooting its file headers**

Run:

```zsh
BASE=$(git merge-base ce477046e2185ea35bba06458b9eb7f6c6a8e23e codex/autonomous-trading-firm)
git diff --binary "$BASE"..codex/autonomous-trading-firm -- 01_REPO/tradingagents-main | \
  sed -E '/^(diff --git |--- |\+\+\+ )/ s#01_REPO/tradingagents-main/##g' | \
  git apply --3way --index
git diff --name-only --cached | rg '^01_REPO/' && exit 1 || true
git diff --name-only --cached
```

Expected: candidate changes are staged only at root-correct paths. If `git apply --3way` conflicts, keep this *fresh* worktree untouched, report the exact paths, and split root-migration repairs by subsystem; never force resolution or reset canonical `master`.

- [ ] **Step 5: Reject historical nested-runtime artifacts from the re-root tree**

Run:

```zsh
git diff --name-only --cached | rg '^01_REPO/' && exit 1 || true
rg -n '01_REPO/tradingagents-main' cli tradingagents config docs tests scripts || true
git diff --cached --check
```

Expected: executable source lives only at canonical-root paths (`cli/`, `tradingagents/`, `tests/`, `config/`). Existing archive references may remain only outside the executable paths.

- [ ] **Step 6: Commit only the inspected, root-correct re-root snapshot**

Run:

```zsh
git commit -m "feat: integrate autonomous firm safeguards"
git status --short
```

Expected: one integration commit and a clean re-root worktree. Tests and reviews occur in later tasks. If the snapshot cannot be root-correct without semantic conflict, create a subsystem repair plan; never reset canonical `master`.

---

### Task 2: Re-prove the autonomous live-intent boundary in the integrated tree

**Files:**
- Modify only when RED exposes a defect: `tradingagents/brokers/alpaca.py`, `tradingagents/brokers/alpaca_supervisor.py`, `tradingagents/execution/reconcile.py`, `tradingagents/policy/live_control.py`, `tradingagents/policy/live_gate.py`, `tradingagents/policy/order_rate_limit.py`, `tradingagents/policy/strategy_promotion_sync.py`
- Test: `tests/test_alpaca_execution.py`, `tests/test_alpaca_supervisor.py`, `tests/test_execution_safety.py`, `tests/test_authorized_normal_trade_intent.py`, `tests/test_strategy_promotion_sync.py`, `tests/test_authority_role_alignment.py`, `tests/test_order_rate_limit.py`

**Consumes:** the integrated branch from Task 1.

**Produces:** evidence that exactly one verified normal-live route exists and all other paths fail before any broker request.

- [ ] **Step 1: Re-index the integration checkout and map the write path**

Use codebase-memory on `/Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm-integration`; then trace callers of `AlpacaRestClient.submit_order` and the final private broker transport. Pair this with the authority-inventory test because code graphs do not prove dynamic call absence.

Expected: only the classified guarded route can reach a live order transport; paper routes remain distinct.

- [ ] **Step 2: Run the boundary suite serially**

Run:

```zsh
cd /Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm-integration
.venv/bin/python -m pytest -q \
  tests/test_authorized_normal_trade_intent.py \
  tests/test_strategy_promotion_sync.py \
  tests/test_alpaca_execution.py \
  tests/test_execution_safety.py \
  tests/test_alpaca_supervisor.py \
  tests/test_live_gate.py \
  tests/test_order_rate_limit.py \
  tests/test_authority_role_alignment.py
```

Expected: all pass. Any failure that permits a request after stale, forged, missing, rate-corrupt, frozen, mismatched, or expired proof is a stop-the-line defect.

- [ ] **Step 3: Add a focused RED test before every boundary repair**

Required assertions for a new test:

```python
with pytest.raises(ExpectedPolicyError):
    guarded_entrypoint(...)
assert fake_session.request_calls == []
assert live_control_before == live_control_after
```

Expected: the test first fails only because the specific bypass exists; the smallest production change makes it pass without widening a route or a lease.

- [ ] **Step 4: Run source-only authority and durability reviews**

Review independently for: raw HTTP escape hatches, caller-controlled clocks or payloads, forged capabilities, stale reconciliation/risk/lease state, control/rate lock races, ledger replacement, recovery duplication, and inventory blind spots.

Expected: both reviews explicitly return GO. Any P0/P1 returns the work to Step 3.

- [ ] **Step 5: Commit each repair and record its test evidence**

Run after a green repair:

```zsh
git add tradingagents tests
git commit -m "fix: harden autonomous live boundary"
git diff --check
.venv/bin/ruff check tradingagents/brokers tradingagents/execution tradingagents/policy tests/test_alpaca_execution.py tests/test_authority_role_alignment.py
```

Expected: focused lint and diff checks pass; no runtime state files are staged.

---

### Task 3: Prove the research, learning, and strategy-promotion chain in the integrated tree

**Files:**
- Read/modify if RED: `tradingagents/orchestration/work_packets.py`, `tradingagents/orchestration/decision_ledger.py`, `tradingagents/evals/learning_availability.py`, `tradingagents/evals/learning_context.py`, `tradingagents/strategy/`, `tradingagents/policy/strategy_promotion_sync.py`
- Test: `tests/test_work_packets.py`, `tests/test_decision_ledger.py`, `tests/test_learning_availability.py`, `tests/test_learning_context.py`, `tests/test_strategy_genome.py`, `tests/test_strategy_compiler.py`, `tests/test_strategy_evaluator.py`, `tests/test_strategy_evidence_store.py`, `tests/test_strategy_staged_intent.py`, `tests/test_strategy_paper_execution_authorization.py`, `tests/test_strategy_shadow_attestation.py`

**Consumes:** an accepted Task 2 boundary.

**Produces:** reproducible point-in-time research handoffs, outcome-bound learning, bounded strategy variants, paper-only order authorization, and independently attested promotion/demotion evidence.

- [ ] **Step 1: Run the deterministic research-to-paper suite**

Run:

```zsh
.venv/bin/python -m pytest -q \
  tests/test_work_packets.py tests/test_decision_ledger.py \
  tests/test_learning_availability.py tests/test_learning_context.py \
  tests/test_strategy_genome.py tests/test_strategy_compiler.py \
  tests/test_strategy_evaluator.py tests/test_strategy_evidence_store.py \
  tests/test_strategy_staged_intent.py tests/test_strategy_paper_execution_authorization.py \
  tests/test_strategy_shadow_attestation.py tests/test_strategy_promotion_sync.py
```

Expected: all pass with no live Alpaca write calls.

- [ ] **Step 2: Add negative evidence tests for every new repair**

Cover at minimum: future data used in a historical evaluation, mutated genome after preregistration, cross-run evidence replay, promotion without independent shadow attestation, stale source packet, failed evaluator, and a paper authorization reaching live submission.

Expected: each fails closed and writes no promotion selection or broker order.

- [ ] **Step 3: Independently review evidence lineage**

Trace packet → learning window → genome → evaluator → paper intent → shadow attestation → promotion state. Verify every immutable ID/hash is resolved from canonical disk evidence and every recovery path is GET-only.

Expected: no self-approval, no mutable-pointer promotion, and no live capability produced from a paper result.

---

### Task 4: Prove machine-owned recovery without actual order writes

**Files:**
- Read/modify if RED: `tradingagents/orchestration/authority.py`, `tradingagents/orchestration/incidents.py`, `tradingagents/orchestration/recovery.py`, `tradingagents/orchestration/self_heal.py`, `tradingagents/brokers/alpaca_reconciliation.py`, `tradingagents/policy/live_control.py`
- Test: `tests/test_autonomous_firm_charter.py`, `tests/test_incidents.py`, `tests/test_recovery_coordinator.py`, `tests/test_self_heal_recovery.py`, `tests/test_symbol_reconciliation.py`, `tests/test_policy_authority_binding.py`, `tests/test_policy_rule_approval_contract.py`

**Consumes:** accepted Tasks 2–3.

**Produces:** ordinary internal failures are diagnosed, repaired, independently verified, and either auto-rearmed within a bounded lease or retained as an evidence-rich external block—with zero broker writes during recovery.

- [ ] **Step 1: Run recovery and reconciliation tests**

Run:

```zsh
.venv/bin/python -m pytest -q \
  tests/test_autonomous_firm_charter.py tests/test_incidents.py \
  tests/test_recovery_coordinator.py tests/test_self_heal_recovery.py \
  tests/test_symbol_reconciliation.py tests/test_policy_authority_binding.py \
  tests/test_policy_rule_approval_contract.py
```

Expected: repairer and verifier use different run IDs; read-only reconciliation never calls submit/cancel/replace; malformed or unavailable evidence remains frozen.

- [ ] **Step 2: Run a fresh read-only broker reconciliation**

Use only the existing read-only CLI/API path. Capture account, positions, orders, client-order identifiers, and evidence linkage for NFLX and all current positions.

Expected: an immutable reconciliation packet. Do not infer missing execution history from dashboard-only data.

- [ ] **Step 3: Run the autonomous incident recipe against the current freeze**

The recipe may regenerate promotion/loss evidence, classify the NFLX conflict, and verify local code/evidence. It must never fabricate the missing external-action history or refresh live control merely because a test passes.

Expected: either a fully evidenced `READY_FOR_REARM` result with a distinct verifier or an explicit `EXTERNAL_BLOCKED`/`REPAIRING` incident with owner, next attempt, and exact missing proof.

- [ ] **Step 4: Review the result before any re-arm**

Required proofs: clean read-only reconciliation; no unmatched order/fill; current promotion selection; valid rate and risk state; incident repair and verifier IDs differ; source and account evidence are current; no recovery broker write.

Expected: only the verifier is allowed to create a short lease, and only after the separate live-readiness phase below. This task itself leaves `live_control.json` frozen.

---

### Task 5: Integrate accepted code into canonical master and publish durable collaboration evidence

**Files:**
- Modify: canonical Git history only after Tasks 2–4 are GO
- Create/update: `docs/orchestration/autonomous-firm-resumption.md`
- Update: `docs/superpowers/plans/2026-08-13-autonomous-firm-reassessment-and-resumption.md`

**Consumes:** integration worktree commits and explicit GO reports.

**Produces:** one canonical code history with an auditable local collaboration record.

- [ ] **Step 1: Run the canonical acceptance suite from the integration worktree**

Run:

```zsh
.venv/bin/python -m pytest -q
.venv/bin/ruff check cli tradingagents scripts tests
```

Expected: capture the exact terminal counts. Existing unrelated warnings may be recorded but not silently dismissed.

- [ ] **Step 2: Merge only the reviewed integration commits into `master`**

Run from canonical root only after the exact suite and reviews are GO:

```zsh
git merge --ff-only codex/autonomous-firm-integration
git status --short --branch
```

Expected: a clean canonical tree. If fast-forward is unavailable, create a new integration review rather than forcing a merge.

- [ ] **Step 3: Keep collaboration lean**

Use Git commits and small Markdown review reports locally for now. If a private remote is later configured, publish branch-per-task pull requests and review comments for code only; keep `.env`, runtime results, broker state, and immutable local evidence out of the remote.

Expected: no overlapping agents edit the same files; a task owns a bounded file set and has one implementation commit plus review evidence.

---

### Task 6: Activate only safe autonomous schedules in Central Time

**Files:**
- External authority: the ten existing Codex automations
- Read/modify: `config/automation_roles.json`, `docs/orchestration/automation-role-contracts.md`, automation records through `automation_update`
- Runtime proof: `results/control_plane/proofs/automation-schedule-YYYYMMDD.json`

**Consumes:** canonical code from Task 5 and a current no-write runtime snapshot.

**Produces:** an autonomous observer/research/paper/shadow schedule that is time-zone correct and does not gain live trading authority.

- [ ] **Step 1: Inspect every automation through the automation API**

Record ID, name, status, model, reasoning effort, notification policy, next run, project target, and timezone semantics. Preserve all fields not deliberately changed.

Expected: ten TradingAgents records, all `failed_runs_only`; no status change yet.

- [ ] **Step 2: Apply the Central-Time, token-aware role matrix**

| Role | Central schedule | Model / effort | Why |
| --- | --- | --- | --- |
| Overnight research | 3:30 AM weekdays | Terra high | One long synthesis; full graph only for the top three symbols. |
| Wake controller | 6:45 AM weekdays | Luna medium | Deterministic status-only work. |
| Self-healer | 7:03, 9:03, 11:03, 1:03, 3:03 CT | Terra high | Incident diagnosis and bounded local repair. |
| Preopen validation | 8:10 AM weekdays | Terra high | Fresh read-only market/account/evidence checks. |
| Safety sentinel | 8:20 AM then hourly through 2:20 PM | Luna medium | Deterministic verification; escalate only on evidence conflict. |
| Market supervisor | 8:35 AM then hourly through 2:35 PM | Terra high | Guarded decision/execution operator; stays no-submit while frozen. |
| Execution BOARD | 8:50 AM then hourly through 2:50 PM | Terra high | Resolve strategy/risk disagreements. |
| Paper tournament | 9:10 AM weekdays | Terra high | Bounded evaluation and mutation. |
| Daily report | 3:30 PM weekdays | Luna medium | Compact reporting only. |
| Sleep controller | 4:45 PM weekdays | Luna medium | Status-only shutdown. |

Expected: model tier drops for controllers/reporting preserve error detection because those jobs are deterministic and evidence-backed. Do not run routine Sol/ultra schedules.

- [ ] **Step 3: Start in observer/shadow mode, not live mode**

Activate controllers, research, paper, validation, sentinel, BOARD, self-healer, and report only after their role contracts pass. Keep market supervisor scheduled only if its prompt and wrapper are explicitly no-submit under frozen live control.

Expected: every first run emits `execution_authority: none`, `can_submit_orders: false`, and a current packet.

- [ ] **Step 4: Verify Central Time and failed-only notifications from the API response**

Reject any update whose displayed next market run is outside 8:30 AM–3:00 PM Central or one hour shifted. Record the API-returned next run in both CT and UTC.

---

### Task 7: Complete the production evidence ladder before considering a live-control refresh

**Files:**
- Runtime packets under `results/`
- Read: `results/policy/live_control.json`, current broker reconciliation, incident ledger, promotion state, shadow attestations, and automation health
- Test: the accepted suites from Tasks 2–4 plus automation role/schedule tests

**Consumes:** a current canonical build and Task 6 observer/shadow runs.

**Produces:** a go/no-go packet—not an automatic live trade.

- [ ] **Step 1: Collect five distinct regular-market-day packets**

For each day require: point-in-time research, outcome/learning update, paper tournament, current read-only reconciliation, preopen validation, safety sentinel, and a supervisor packet with zero live submissions.

Expected: all five days are current, traceable, and not weekend/holiday no-ops.

- [ ] **Step 2: Validate shadow and paper outcomes**

Require independently attested strategy evidence, no unexplained paper-order duplicates, no unresolved source staleness, bounded losses/drawdown, and no recovery integrity violation.

Expected: promotion/demotion/rollback decisions are evidence-derived, not prose approval.

- [ ] **Step 3: Produce a final live-readiness go/no-go**

The packet must check: live control remains frozen before decision; current clean broker reconciliation; NFLX or successor incident is either fully reconciled with durable evidence or explicitly blocks; current caps/rate ledger/risk metrics; no raw broker write paths; all schedules and role contracts; five-day proof; separate verifier identity; and no external authority gap.

Expected: `NO_GO` keeps the system operating autonomously in observer/paper/shadow mode and schedules its own next safe repair/recheck. `GO` authorizes only a short-lived live-control refresh by the verifier; it does not authorize an order or claim profitability.

---

## Plan Self-Review

**Objective coverage:** The tasks cover point-in-time research, learned outcomes, bounded strategy variants, paper testing, immutable evidence, promotion/demotion/rollback, capped risk, self-repair, Central-Time automations, broker reconciliation, protected execution, model-cost tuning, Git collaboration, and five-market-day validation. The only intentionally deferred action is live re-arm/order submission, because it requires current external evidence and an explicit go/no-go result rather than a coding assertion.

**Failure containment:** Every phase keeps runtime live control frozen until the final evidence ladder. A merge, passing test, scheduled job, or paper result cannot substitute for clean broker reconciliation or the missing NFLX execution history.

**No-placeholder check:** Each task has an exact scope, owner boundary, command or decision procedure, expected result, and verification outcome. New defects use RED-GREEN tests and a source-only reviewer before integration.
