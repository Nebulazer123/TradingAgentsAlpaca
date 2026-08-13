# Autonomous Firm Root-Migration Implementation Plan

**Execution status (2026-08-13):** Completed. The eight semantic conflicts were resolved in the isolated re-root worktree, accepted as commit `02ea6b8878fcf076fcdbab3c93847ccd51eba9fa`, then repaired and independently reviewed through `e14a78a11960e07f5a720a158c26ca4fe02aa02a`. The parent resumption plan subsequently authorized and performed the fast-forward into canonical `master`; the historical 67-conflict worktree remains untouched as recovery evidence.

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the eight semantic conflicts produced when the historical autonomous-firm implementation is mechanically re-rooted into the current canonical TradingAgents layout, preserving both current canonical safeguards and the candidate’s new autonomous-firm contracts.

**Architecture:** Work only in `/Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm-reroot`, where the header-rewritten patch already applied and left exactly eight unmerged files. For each conflict, compare stage 1 (common ancestor), stage 2 (current canonical master), and stage 3 (historical autonomous-firm candidate); compose the smallest root-correct result that satisfies both sets of tests. The unresolved direct-merge worktree and canonical `master` are evidence only and must not be edited.

**Tech Stack:** Python 3.10+, pytest, Ruff, Git three-way index stages, codebase-memory for current canonical code relationships, JSON evidence packets, and existing TradingAgents policy/research modules.

## Global Constraints

- Do not reset, clean, delete, abort, or resolve `/Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm-integration`; it preserves the failed 67-path historical merge.
- Do not touch `/Users/corbinfloyd/Documents/TradingAgents/results/`, `.env`, schedules, automation records, broker state, credentials, or `live_control.json`.
- Do not merge to canonical `master`. This plan may create exactly one root-correct integration commit in the re-root worktree after all eight conflicts and tests are clean.
- Preserve the canonical runtime’s existing fail-closed live gates and append only candidate checks that make denial stricter or add isolated autonomous-firm evidence; never weaken existing gates to make a test pass.
- All implementation changes use RED-GREEN-REFACTOR. A conflict is not resolved by choosing “ours” or “theirs” wholesale unless a test and a source comparison prove the omitted side has no semantic requirement.
- Run tests serially because the test suite uses shared evidence fixtures. Tests use fakes only; no live broker I/O is allowed.

---

### Task 1: Resolve compact-context contract migration

**Files:**
- Modify: `scripts/automation_context_snapshot.py`
- Modify: `tests/test_automation_context_snapshot.py`
- Inspect conflict stages: `:1:scripts/automation_context_snapshot.py`, `:2:scripts/automation_context_snapshot.py`, `:3:scripts/automation_context_snapshot.py`

**Consumes:** the existing re-root worktree with an unmerged index.

**Produces:** a compact-context writer that preserves canonical packet compaction and adds the candidate autonomous-role/authority summaries without reading credentials or changing runtime evidence.

- [ ] **Step 1: Write a failing behavior test from the candidate-only assertion**

Extract the candidate assertions that are absent from stage 2 into the canonical test file. The test must create only temporary packet/config files, invoke the compact-context builder, and assert both the existing canonical summary fields and the new autonomous-firm fields appear.

Example required shape:

```python
summary = build_compact_context(...)
assert summary["latest_packets"]
assert summary["automation_role_contract_status"] in {"pass", "warn", "fail"}
assert summary["execution_authority"] in {"none", "paper", "normal_live"}
```

- [ ] **Step 2: Run the targeted test and confirm RED**

Run:

```zsh
cd /Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm-reroot
.venv/bin/python -m pytest -q tests/test_automation_context_snapshot.py
```

Expected: failure identifies the missing candidate contract, not a filesystem or credential error.

- [ ] **Step 3: Compose the implementation from stages 2 and 3**

Keep stage 2’s current compact-context packet discovery, field provenance, and existing flags. Add only stage 3’s autonomous role/authority calculation where it has a current canonical input; absent/malformed contract data must yield a compact failure/warning field, not an exception or a permissive default.

- [ ] **Step 4: Resolve, stage, and verify**

Run:

```zsh
git add scripts/automation_context_snapshot.py tests/test_automation_context_snapshot.py
.venv/bin/python -m pytest -q tests/test_automation_context_snapshot.py
.venv/bin/ruff check scripts/automation_context_snapshot.py tests/test_automation_context_snapshot.py
git diff --cached --check
```

Expected: no conflict marker remains in either file, all tests pass, and no `results/` path is staged.

---

### Task 2: Resolve policy and live-gate contract migration

**Files:**
- Modify: `tradingagents/policy/live_gate.py`
- Modify: `tradingagents/policy/promotion_sync.py`
- Modify: `tests/test_live_gate.py`
- Inspect: `tradingagents/policy/live_control.py`, `tradingagents/policy/order_rate_limit.py`, `tradingagents/policy/strategy_promotion_sync.py`, `tradingagents/execution/authorized_normal_trade_intent.py`

**Consumes:** Task 1’s resolved context conflict; the same re-root worktree.

**Produces:** a fail-closed gate that retains every canonical check and accepts autonomous-firm promotion/normal-intent evidence only through strict typed inputs.

- [ ] **Step 1: Create focused RED cases from candidate-only policy assertions**

Add tests that keep current canonical denial behavior while proving the candidate additions cannot relax it:

```python
with pytest.raises(LiveGateError):
    evaluate_go_live_guard(..., promotion_evidence=None)

with pytest.raises(LiveGateError):
    evaluate_go_live_guard(..., normal_intent=forged_intent)
```

Also preserve the current tests for frozen control, stale account/reconciliation evidence, budget/rate failure, and mismatched promotion evidence.

- [ ] **Step 2: Run focused policy tests and confirm RED**

Run:

```zsh
.venv/bin/python -m pytest -q tests/test_live_gate.py tests/test_policy_rule_approval_contract.py
```

Expected: failure is limited to the absent migrated contract behavior. Any test that reaches a real session/request is a stop-the-line defect.

- [ ] **Step 3: Compose the gate and promotion sync implementations**

Retain stage 2’s live-control, budget, rate, loss/drawdown, product, and canonical promotion conditions. Add stage 3’s autonomous-firm authority/promotion state only as additional required proof. Inputs that are missing, stale, malformed, different-run, unbound, or inconsistent must reject before any broker client call.

- [ ] **Step 4: Resolve, stage, and verify serially**

Run:

```zsh
git add tradingagents/policy/live_gate.py tradingagents/policy/promotion_sync.py tests/test_live_gate.py
.venv/bin/python -m pytest -q \
  tests/test_live_gate.py tests/test_policy_rule_approval_contract.py \
  tests/test_policy_authority_binding.py tests/test_execution_safety.py
.venv/bin/ruff check tradingagents/policy/live_gate.py tradingagents/policy/promotion_sync.py tests/test_live_gate.py
git diff --cached --check
```

Expected: all policy tests pass; no conflict marker remains; all invalid authority combinations fail before broker I/O.

---

### Task 3: Resolve research, BOARD, and loss-evidence migration

**Files:**
- Modify: `tradingagents/dataflows/decision_vendor_adapters.py`
- Modify: `tradingagents/evals/execution_board.py`
- Modify: `tradingagents/research/loss_review_evidence.py`
- Inspect tests: `tests/test_execution_board.py`, `tests/test_dataflow_error_taxonomy.py`, `tests/test_loss_review_evidence.py`, `tests/test_policy_rule_approval_contract.py`

**Consumes:** Tasks 1–2 resolved conflicts; the same re-root worktree.

**Produces:** research/BOARD decisions that preserve canonical vendor failure typing and loss-review evidence while emitting candidate autonomous decision-authority evidence without issuing broker writes.

- [ ] **Step 1: Add RED contract tests for the candidate-only paths**

Tests must prove that provider failure stays typed, a BOARD recommendation remains non-executing, and loss-review evidence cannot approve a conflicting policy rule merely because it is fresh:

```python
assert result.kind == "recoverable_provider_failure"
assert board_packet["execution_authority"] == "none"
assert loss_review["policy_rule_conflict"] is True
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```zsh
.venv/bin/python -m pytest -q \
  tests/test_dataflow_error_taxonomy.py tests/test_execution_board.py \
  tests/test_loss_review_evidence.py tests/test_policy_rule_approval_contract.py
```

Expected: failure is a missing composition behavior, never an external provider/broker call.

- [ ] **Step 3: Compose the three implementations**

Keep stage 2’s current typed dataflow errors, BOARD risk posture/new-buy suspension, and loss-review source/evidence validation. Add stage 3’s decision-authority/policy bindings as immutable packet fields or stricter validation. Do not give BOARD, research, or loss-review a submit capability.

- [ ] **Step 4: Resolve, stage, and verify**

Run:

```zsh
git add tradingagents/dataflows/decision_vendor_adapters.py \
  tradingagents/evals/execution_board.py \
  tradingagents/research/loss_review_evidence.py
.venv/bin/python -m pytest -q \
  tests/test_dataflow_error_taxonomy.py tests/test_execution_board.py \
  tests/test_loss_review_evidence.py tests/test_policy_rule_approval_contract.py
.venv/bin/ruff check tradingagents/dataflows/decision_vendor_adapters.py \
  tradingagents/evals/execution_board.py tradingagents/research/loss_review_evidence.py
git diff --cached --check
```

Expected: all targeted tests pass; no research/BOARD path can emit a broker write.

---

### Task 4: Create the root-correct integration commit and prove no unresolved state remains

**Files:**
- Inspect/stage: the re-root worktree’s remaining candidate additions and all eight resolved paths
- Report: `.superpowers/sdd/2026-08-13-autonomous-firm-root-migration/`

**Consumes:** Tasks 1–3.

**Produces:** a single reviewable re-root integration commit, still separate from canonical `master`.

- [ ] **Step 1: Verify the merge index and root layout**

Run:

```zsh
git diff --name-only --diff-filter=U
git diff --name-only --cached | rg '^01_REPO/' && exit 1 || true
rg -n '^(<<<<<<<|=======|>>>>>>>)' cli tradingagents tests config scripts || true
git status --short
```

Expected: no unmerged paths, no conflict markers, no staged generated `results/` files, and no executable `01_REPO/` paths.

- [ ] **Step 2: Run the combined migration acceptance set**

Run:

```zsh
.venv/bin/python -m pytest -q \
  tests/test_automation_context_snapshot.py tests/test_live_gate.py \
  tests/test_policy_rule_approval_contract.py tests/test_policy_authority_binding.py \
  tests/test_dataflow_error_taxonomy.py tests/test_execution_board.py \
  tests/test_loss_review_evidence.py tests/test_execution_safety.py
```

Expected: all pass serially with no external broker write.

- [ ] **Step 3: Commit the inspected migration snapshot**

Run:

```zsh
git add cli tradingagents tests config docs scripts
git commit -m "feat: integrate autonomous firm safeguards"
git status --short
```

Expected: exactly one clean re-root integration commit. This commit is a candidate for Task 2 boundary verification in the parent resumption plan, not permission to merge or unfreeze.

---

## Plan Self-Review

**Coverage:** The plan resolves every one of the eight header-re-root conflicts and keeps their dependencies grouped by responsibility. It preserves canonical runtime safeguards and imports candidate contracts only as stricter evidence requirements.

**Safety:** No task alters runtime evidence, broker state, schedules, `master`, or live control. Tests are serial and fake-only.

**No-placeholder check:** Every task identifies exact files, merge intent, RED behavior, verification commands, and commit condition.
