# Autonomous Trading Firm Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn TradingAgents into a self-governing trading firm that researches, chooses and evolves strategies, manages risk, trades, detects failures, repairs ordinary machine-resolvable failures, independently verifies the repair, and safely re-arms without asking a person what to buy, sell, promote, or repair.

**Architecture:** Keep the existing TradingAgents analyst/debate graph, Alpaca execution path, paper tournament, unified live gate, and evidence packets. Add a machine authority charter, an owned incident state machine, compact agent handoffs, independent verification, bounded auto-rearm, a parameterized strategy-evolution loop, selected upstream v0.3.1 hardening, and Central Time production automations. LLM agents may make investment judgments inside the charter; deterministic code remains the only authority for integrity checks, broker reconciliation, idempotency, and order submission.

**Tech Stack:** Python 3.10+, LangGraph, Typer, dataclasses/TypedDict, JSON/JSONL evidence, Alpaca APIs, pytest, Codex automations, n8n observer workflows, Git worktrees, and the existing TradingAgents provider and model-routing layers.

## Global Constraints

- The experiment owns its trading decisions. No human approval is required for a ticker, trade, allocation, strategy change, risk-posture change, promotion, demotion, ordinary repair, or evidence-backed re-arm.
- Human action is reserved for external authority the machine cannot possess: adding or withdrawing capital, broker-account identity/legal changes, credential or OAuth completion, and changing the experiment charter itself.
- A freeze is a safe state, not a terminal state. Every freeze must create or update an incident with one owner, a next action, a retry budget, machine-readable evidence, and an expiry.
- Recovery may reconcile, repair, verify, and refresh live control. Recovery must never submit, cancel, replace, or duplicate an order. Re-arming only permits a later normal supervisor run to evaluate a fresh trade through the existing live gate.
- A verifier must have a different role and `run_id` from the repairer. The repairer cannot approve its own repair.
- Investment disagreement is not an integrity failure. The deterministic integrity gate blocks only broken, stale, contradictory, unreconciled, malformed, duplicate, or out-of-charter state.
- Broker state is the authority for actual positions and orders. Promotion state is the authority for sleeve eligibility. Live control is the authority for the short-lived execution lease. The incident ledger is the authority for recovery status.
- Keep raw evidence out of agent prompts unless a compact packet identifies a disagreement or low-confidence claim that requires inspection.
- A worker loads this program index plus only the active child plan and its directly referenced source files; it does not load all four child plans into one context.
- Use event-driven worker roles. Do not keep extra agents running merely to preserve an org chart.
- Preserve all pre-existing dirty work in the original checkout. Implementation starts in an isolated worktree and never resets, cleans, or overwrites the original tree.
- All production schedules are interpreted in `America/Chicago`. US equity regular hours are 8:30 AM-3:00 PM Central Time.
- Every automation uses `notification_policy = "failed_runs_only"`.
- No implementation phase may widen broker products beyond the current charter: stock-only, long-only, limit-only, no leverage, no options, no shorting, and no crypto in live execution unless a later charter change explicitly says otherwise.

---

## Plan Suite And Dependency Order

1. [Autonomous Control and Recovery](./2026-07-18-autonomous-control-and-recovery.md)
   - Machine authority charter.
   - Owned incident lifecycle.
   - Generic read-only broker reconciliation.
   - Independent repair verification.
   - Short-lived automatic live-control refresh.
   - First acceptance scenario: the NFLX policy-rule conflict.
2. [Agent Communication and Strategy Learning](./2026-07-18-agent-communication-and-strategy-learning.md)
   - Compact evidence handoffs.
   - Source ownership and staleness.
   - Outcome-scored agent influence.
   - Parameterized strategy creation, mutation, tournament entry, promotion, demotion, and rollback.
3. [Upstream Intelligence Hardening Sync](./2026-07-18-upstream-intelligence-hardening-sync.md)
   - Selectively port high-value fixes from `TauricResearch/TradingAgents` v0.3.1.
   - Preserve the local Alpaca, policy, connector, concurrency, research, and automation extensions.
4. [Production Automation Rollout](./2026-07-18-production-autonomous-firm-rollout.md)
   - Rewrite authority boundaries in the ten TradingAgents automations.
   - Set Central Time market schedules and failed-run-only notifications.
   - Shadow, canary, live, rollback, and five-trading-day proof.

The plans are separate because each subsystem can be implemented, tested, reviewed, and rolled back independently. Execute them in the order above.

---

### Task 1: Preserve The Existing Checkout And Establish A Clean Baseline

**Files:**
- Inspect: `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main`
- Create at execution time: `/Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm`
- Preserve without editing: all files shown by `git status --short` in the original checkout

- [ ] **Step 1: Record the original checkout state**

Run:

```bash
cd /Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main
git status --short
git diff --stat
git diff --binary > /tmp/tradingagents-preexisting-20260718.patch
```

Expected: the existing modified and untracked files remain visible; `/tmp/tradingagents-preexisting-20260718.patch` is a backup reference, not an artifact to commit.

- [ ] **Step 2: Create an isolated worktree**

Invoke `superpowers:using-git-worktrees`, then create branch `codex/autonomous-trading-firm` at:

```text
/Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm
```

Expected: the original checkout remains unchanged and dirty; the new worktree is clean.

- [ ] **Step 3: Inventory relevant pre-existing changes before touching an overlapping file**

Run from the original checkout:

```bash
git diff -- cli/main.py \
  scripts/automation_context_snapshot.py \
  tradingagents/orchestration/self_heal.py \
  tradingagents/policy/live_control.py \
  tradingagents/policy/live_gate.py \
  tradingagents/policy/promotion_sync.py \
  tradingagents/evals/execution_board.py \
  tradingagents/research/loss_review_evidence.py \
  tests/test_alpaca_cli.py \
  tests/test_live_gate.py \
  tests/test_execution_board.py \
  tests/test_loss_review_evidence.py
```

Expected: the executor records which hunks must be preserved or deliberately superseded. In particular, preserve the untracked NFLX policy-rule regression in `tests/test_policy_rule_approval_contract.py`.

- [ ] **Step 4: Run the focused starting baseline in the worktree**

Run:

```bash
uv run --with pytest python -m pytest \
  tests/test_live_gate.py \
  tests/test_promotion_sync.py \
  tests/test_self_heal_handoff.py \
  tests/test_alpaca_reconciliation.py \
  tests/test_execution_board.py \
  tests/test_agent_intelligence_ledger.py \
  tests/test_hypothesis_factory.py \
  tests/test_hypothesis_lifecycle.py \
  tests/test_paper_tournament.py -q
```

Expected: PASS. If it fails, record the exact pre-existing failure and fix only failures required by the first subsystem before continuing.

- [ ] **Step 5: Commit the clean planning baseline**

```bash
git add docs/superpowers/plans/2026-07-18-*.md
git commit -m "docs: plan autonomous trading firm"
```

Expected: one documentation-only commit on `codex/autonomous-trading-firm`.

---

### Task 2: Apply The Program-Wide Authority Test

**Files:**
- Create: `tests/test_autonomous_firm_charter.py`
- Reference: `config/autonomous_firm.json`

- [ ] **Step 1: Write the cross-plan charter test before subsystem code**

```python
from tradingagents.orchestration.authority import ActionClass, authority_for


def test_machine_owns_trading_and_ordinary_recovery():
    machine_actions = {
        ActionClass.TRADE_DECISION,
        ActionClass.STRATEGY_CHANGE,
        ActionClass.RISK_CHANGE,
        ActionClass.PROMOTION_CHANGE,
        ActionClass.FREEZE,
        ActionClass.REPAIR,
        ActionClass.VERIFY,
        ActionClass.REARM,
        ActionClass.ORDER_SUBMIT,
    }
    assert all(authority_for(action).human_required is False for action in machine_actions)


def test_only_external_account_authority_requires_the_user():
    human_actions = {
        ActionClass.CAPITAL_CHANGE,
        ActionClass.ACCOUNT_IDENTITY_CHANGE,
        ActionClass.CREDENTIAL_CHANGE,
        ActionClass.CHARTER_CHANGE,
    }
    assert all(authority_for(action).human_required is True for action in human_actions)
```

- [ ] **Step 2: Run it and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_autonomous_firm_charter.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `tradingagents.orchestration.authority`.

- [ ] **Step 3: Implement through Plan 1**

Complete every task in `2026-07-18-autonomous-control-and-recovery.md`.

- [ ] **Step 4: Re-run and confirm GREEN**

```bash
uv run --with pytest python -m pytest tests/test_autonomous_firm_charter.py -q
```

Expected: 2 passed.

---

### Task 3: Prove The End-To-End Autonomous Recovery Contract

**Files:**
- Create: `tests/integration/test_autonomous_recovery_contract.py`
- Read: `results/control_plane/incidents/latest.json`
- Read: `results/control_plane/rearm/latest.json`

- [ ] **Step 1: Build a synthetic frozen NFLX fixture**

The fixture must contain:

```json
{
  "symbol": "NFLX",
  "freeze_reason": "policy_rule_conflict",
  "policy_rule": "catastrophic_stop",
  "advisory_effect": "preserves_pre_registered_policy_approval",
  "broker_position_qty": "0.320946047",
  "broker_open_orders": [],
  "promotion_evidence_fresh": false
}
```

- [ ] **Step 2: Assert the required flow**

The integration test must prove this exact order:

```text
freeze detected
-> incident owned by reliability_controller
-> policy conflict resolved without changing the preregistered stop rule
-> promotion evidence regenerated
-> broker reconciliation performed read-only
-> independent verifier returns READY
-> live control refreshed for at most 90 minutes
-> no broker write method called
-> incident enters MONITORING
```

- [ ] **Step 3: Add false-green traps**

Parametrize the same test so re-arm is rejected when any one condition is present:

```text
repairer_run_id == verifier_run_id
broker position mismatch
unknown open order
missing client_order_id after recorded submission
stale promotion evidence
conflicting policy rule remains
invalid live_control JSON
credential or OAuth action required
retry budget exhausted
```

- [ ] **Step 4: Run the integration test**

```bash
uv run --with pytest python -m pytest tests/integration/test_autonomous_recovery_contract.py -q
```

Expected: PASS; the broker fake records zero submit/cancel/replace calls.

---

### Task 4: Run The Program Done Proof

**Files:**
- Update: `AGENTS.md`
- Update: `CLAUDE.md`
- Create: `docs/orchestration/autonomous-firm.md`
- Create: `results/control_plane/proofs/autonomous-firm-go-no-go.json`

- [ ] **Step 1: Re-index the implementation worktree**

Use codebase-memory on the worktree root, then verify coverage for every changed Python path before making architecture or completeness claims.

- [ ] **Step 2: Run focused safety and autonomy tests**

```bash
uv run --with pytest python -m pytest \
  tests/test_autonomous_firm_charter.py \
  tests/test_authority.py \
  tests/test_incidents.py \
  tests/test_recovery_coordinator.py \
  tests/test_work_packets.py \
  tests/test_learning_context.py \
  tests/test_strategy_genome.py \
  tests/test_strategy_selection.py \
  tests/integration/test_autonomous_recovery_contract.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the existing live-sensitive regression suite**

```bash
uv run --with pytest python -m pytest \
  tests/test_live_gate.py \
  tests/test_alpaca_execution.py \
  tests/test_alpaca_reconciliation.py \
  tests/test_alpaca_supervisor.py \
  tests/test_alpaca_cli.py \
  tests/test_promotion_policy.py \
  tests/test_promotion_sync.py \
  tests/test_self_heal_handoff.py \
  tests/test_execution_board.py \
  tests/test_automation_context_snapshot.py -q
```

Expected: PASS.

- [ ] **Step 4: Run the full suite**

```bash
uv run --with pytest python -m pytest -q
```

Expected: PASS with no test collection failures.

- [ ] **Step 5: Write the go/no-go packet**

The packet must contain:

```json
{
  "decision": "GO",
  "machine_trade_authority": true,
  "ordinary_recovery_is_autonomous": true,
  "recovery_can_submit_orders": false,
  "independent_verification_required": true,
  "max_rearm_ttl_minutes": 90,
  "central_timezone": "America/Chicago",
  "notifications": "failed_runs_only",
  "focused_tests": "pass",
  "live_sensitive_tests": "pass",
  "full_suite": "pass",
  "shadow_cycles": 3,
  "canary_recovery": "pass",
  "broker_write_calls_during_recovery": 0,
  "open_external_blockers": []
}
```

If any field cannot be supported by fresh evidence, write `"decision": "NO_GO"` and list the exact blocker. Mixed evidence is not converted into a pass.

- [ ] **Step 6: Commit the completed program**

```bash
git add tradingagents tests config docs AGENTS.md CLAUDE.md
git commit -m "feat: make TradingAgents a self-recovering autonomous firm"
```

Expected: clean worktree after excluding runtime `results/` evidence from the commit unless the repo's existing artifact policy explicitly tracks that packet.

---

## Acceptance Criteria

- No ordinary freeze can remain ownerless.
- An evidence-backed machine repair can re-arm without user authorization.
- Re-arm never occurs on unresolved or ambiguous broker state.
- Recovery cannot submit or mutate broker orders.
- Every live order still passes the same unified live gate and idempotency checks.
- Strategy and risk decisions are autonomous, outcome-scored, and reversible.
- The system can generate new parameterized strategies without editing executable trading code during a market session.
- The existing original analyst, bull/bear, trader, risk debate, and portfolio manager flow remains present.
- Selected upstream fixes land without removing local Alpaca, policy, connector, research, concurrency, and automation capabilities.
- All ten production automations use Central Time market windows and failed-run-only notifications.
- User involvement is requested only for external account authority or a charter change.
