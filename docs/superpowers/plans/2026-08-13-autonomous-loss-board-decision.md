# Autonomous Loss BOARD Decision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the machine-owned Portfolio Executive close every discretionary loss review with an immutable autonomous `HOLD` or evidence-qualified `SELL` decision, while keeping execution, live-control rearm, and broker writes behind their existing independent gates.

**Architecture:** The existing loss-research packet stays advisory. A new strict loss-BOARD module captures the exact supervisor packet, loss-evidence packet, and accepted source files as hash-bound evidence, deterministically chooses `HOLD` or `SELL`, and records the decision as a `portfolio_decision` `WorkPacket` in the existing `DecisionLedger`. `resolve_exit_authority` may consume only a freshly verified exact decision record. Execution BOARD surfaces the result; self-heal classifies unresolved BOARD work as a portfolio business decision and never as an integrity recovery or rearm event.

**Tech Stack:** Python 3.11+, frozen dataclasses, canonical JSON/SHA-256, existing `WorkPacket` and `DecisionLedger`, Typer CLI, pytest, Ruff.

## Global Constraints

- The Portfolio Executive owns `trade_decision`; it does not own `order_submit`, broker writes, live-control rearm, promotion, or risk-policy mutation.
- Every output remains `analysis_only=true`, `execution_authority=none`, and `can_submit_orders=false`.
- `HOLD` is the fail-closed autonomous outcome for missing, stale, malformed, contradictory, or insufficient evidence. It is a resolved trade decision, not a request for a human decision.
- `SELL` requires exact current bindings, complete benchmark/company/filing evidence, a recognized reason, and a configured minimum confidence. A BOARD `SELL` is decision authority only and cannot create or submit an order.
- Advisory research alone never authorizes a discretionary exit.
- No task may unfreeze live control, issue a rearm receipt, submit/cancel/replace an order, change schedules, or call the broker.
- Current TSM evidence is expected to resolve to autonomous `HOLD`; tests must not manufacture a `SELL` by weakening evidence rules.
- Use RED-GREEN-REFACTOR and commit each independently reviewable task.

---

### Task 1: Strict autonomous loss decision and immutable ledger recording

**Files:**
- Create: `tradingagents/policy/loss_board_decision.py`
- Modify: `tradingagents/orchestration/work_packets.py`
- Test: `tests/test_loss_board_decision.py`

**Interfaces:**
- Consumes: `WorkPacket`, `EvidenceRef`, `DecisionLedger`, exact supervisor packet path, exact raw loss-evidence path, source revision, and a UTC clock.
- Produces: `AutonomousLossBoardDecision`, `record_autonomous_loss_board_decision(...) -> RecordedLossBoardDecision`, and `verify_autonomous_loss_board_decision(...) -> AutonomousLossBoardDecision`.

- [ ] **Step 1: Write RED tests for the data contract.**

  Add fixtures that write canonical supervisor/loss/source JSON files under a temporary evidence root. Assert:

  ```python
  recorded = record_autonomous_loss_board_decision(
      supervisor_packet_path=supervisor_path,
      loss_evidence_packet_path=loss_path,
      source_revision="1" * 40,
      ledger_root=tmp_path / "ledger",
      evidence_root=tmp_path / "evidence",
      now=NOW,
  )
  assert recorded.decision.decision == "HOLD"
  assert recorded.decision.trade_decision_resolved is True
  assert recorded.decision.exit_allowed is False
  assert recorded.decision.execution_authority == "none"
  assert recorded.decision.can_submit_orders is False
  assert DecisionLedger(tmp_path / "ledger").verify(
      evidence_root=tmp_path / "evidence"
  )[-1].kind == "portfolio_decision"
  ```

  Parameterize malformed/string booleans, symbol/decision mismatches, stale timestamps, mutated bytes, missing SPY/QQQ/sector values, stale cached news, SEC-index-only evidence, and transcript/config gaps. Each must either produce a valid `HOLD` or fail before recording; none may produce `SELL`.

- [ ] **Step 2: Run the new test module and confirm the missing-module/interface RED.**

  Run: `.venv/bin/python -m pytest -q tests/test_loss_board_decision.py`

  Expected: collection/import failure for `tradingagents.policy.loss_board_decision`.

- [ ] **Step 3: Implement the exact decision schema.**

  Define a frozen dataclass with exact fields:

  ```python
  @dataclass(frozen=True)
  class AutonomousLossBoardDecision:
      schema_version: str
      decision_id: str
      decision: Literal["HOLD", "SELL"]
      symbol: str
      supervisor_decision_id: str
      supervisor_packet: BoundEvidence
      loss_evidence_packet: BoundEvidence
      accepted_sources: tuple[BoundSourceEvidence, ...]
      source_revision: str
      generated_at: str
      expires_at: str
      thesis_verdict: str
      reason_code: str
      confidence: str
      evidence_complete: bool
      evidence_gaps: tuple[str, ...]
      trade_decision_resolved: bool
      exit_allowed: bool
      producer_role: str = field(init=False, default="portfolio_executive")
      analysis_only: bool = field(init=False, default=True)
      execution_authority: str = field(init=False, default="none")
      can_submit_orders: bool = field(init=False, default=False)
  ```

  `decision_id` must be the SHA-256 of canonical material excluding itself. Require exact booleans, uppercase ticker, lowercase 40-hex revision, whole-second UTC times, `generated_at < expires_at <= generated_at + 15 minutes`, canonical decimals, unique exact source bindings, and `SELL == exit_allowed == evidence_complete`. `HOLD` must have `exit_allowed=false` and a nonempty reason/gap when evidence is incomplete.

- [ ] **Step 4: Implement deterministic evidence qualification and decision selection.**

  Capture each file once as bytes; use the same captured bytes for hashing and parsing. Require exact symbol and supervisor decision linkage. A `SELL` requires all of:

  - source-bound supervisor and raw loss-evidence packets;
  - actual SPY, QQQ, and sector-relative values, not a generic symbol quote;
  - current company-specific news with accepted quality and freshness;
  - current earnings/guidance/filing substance, not a submissions index or connector-gap marker;
  - a recognized loss-exit reason and reason source;
  - a nonempty current-thesis verdict explaining why `HOLD` is worse;
  - confidence at or above `0.75`;
  - no remaining blocker except a closed/non-tradeable session.

  Otherwise return `HOLD` with `reason_code="evidence_incomplete"` or `reason_code="hold_preferred"`, preserving all structural gaps.

- [ ] **Step 5: Record the decision through the existing ledger.**

  Publish the canonical decision JSON as content-addressed evidence beneath the supplied evidence root without overwriting conflicting bytes. Create a `portfolio_decision` `WorkPacket` whose producer is `portfolio_executive`, whose evidence refs bind the decision, supervisor, and loss-evidence artifacts, whose recommendation is `autonomous_hold` or `autonomous_sell_authorized_pending_execution_intent`, and whose only added advisory effect is `record_trade_decision`. Record and immediately verify it through `DecisionLedger`.

  Extend `ADVISORY_ALLOWED_EFFECTS` only with `record_trade_decision`; do not add an order, control, promotion, sizing, or risk effect.

- [ ] **Step 6: Run Task 1 tests and commit.**

  Run:

  ```bash
  .venv/bin/python -m pytest -q tests/test_loss_board_decision.py tests/test_work_packets.py tests/test_decision_ledger.py
  .venv/bin/ruff check tradingagents/policy/loss_board_decision.py tradingagents/orchestration/work_packets.py tests/test_loss_board_decision.py
  git diff --check
  ```

  Expected: all pass.

  Commit: `feat: record autonomous loss board decisions`

---

### Task 2: Authority resolver and execution BOARD consume the exact decision

**Files:**
- Modify: `tradingagents/policy/decision_authority.py`
- Modify: `tradingagents/evals/execution_board.py`
- Modify: `cli/main.py`
- Modify: `tradingagents/research/loss_review_evidence.py`
- Test: `tests/test_decision_authority.py`
- Test: `tests/test_execution_board.py`
- Test: `tests/test_loss_review_evidence.py`

**Interfaces:**
- Consumes: `verify_autonomous_loss_board_decision(...)` and the current source-bound loss-review summary.
- Produces: `ExitAuthorityVerdict.exit_allowed`, `trade_decision_resolved`, and a BOARD report field `autonomous_loss_decision` with the immutable decision reference.

- [ ] **Step 1: Write RED authority tests.**

  Add an optional `board_decision` input to `resolve_exit_authority`. Assert a verified HOLD returns:

  ```python
  assert verdict.exit_allowed is False
  assert verdict.trade_decision_resolved is True
  assert verdict.requires_additional_decision is False
  assert verdict.authority_source == "autonomous_portfolio_board"
  ```

  A verified SELL returns `exit_allowed=true` but no execution authority. Advisory-only, stale, mismatched, mutated, and malformed decision inputs must remain unresolved/fail closed. Preserve existing pre-registered policy behavior.

- [ ] **Step 2: Run the focused authority tests and confirm RED.**

  Run: `.venv/bin/python -m pytest -q tests/test_decision_authority.py`

  Expected: failures because `board_decision` and the new verdict fields do not exist.

- [ ] **Step 3: Extend `ExitAuthorityVerdict` without overloading `allowed`.**

  Keep `allowed` as a compatibility alias for `exit_allowed`, and add exact fields `exit_allowed: bool` and `trade_decision_resolved: bool`. Pre-registered policy exits are resolved and allowed. A valid BOARD HOLD is resolved and disallowed. A valid BOARD SELL is resolved and allowed. Invalid decision evidence is unresolved and disallowed.

- [ ] **Step 4: Write RED execution-BOARD tests.**

  Assert `build_execution_board_review(...)` records/attaches a machine decision when the latest raw evidence matches the current hourly window. Incomplete evidence must produce:

  ```python
  assert review["autonomous_loss_decision"]["decision"] == "HOLD"
  assert review["autonomous_loss_decision"]["trade_decision_resolved"] is True
  assert review["autonomous_loss_decision"]["can_submit_orders"] is False
  assert review["loss_review_evidence"]["next_action"] == "autonomous_hold"
  assert not any("manual" in item["message"].lower() for item in review["warnings"])
  ```

  Complete evidence may produce `SELL` and `autonomous_sell_authorized_pending_execution_intent`; it must still have zero order capability.

- [ ] **Step 5: Implement BOARD decision recording and CLI wiring.**

  Add explicit `decision_ledger_root` and `decision_evidence_root` parameters with repo-local defaults to the BOARD builder/CLI. Record only after exact source binding succeeds. Replace `manual_board_review_*` output with `autonomous_hold` or `autonomous_sell_authorized_pending_execution_intent`. Keep `analysis_only`, no-submit, and existing new-buy caution rules.

- [ ] **Step 6: Correct evidence semantics that falsely clear blockers.**

  Update loss-review evidence qualification so a generic ticker quote cannot satisfy benchmark context, watchlist/config cache cannot satisfy current company news, and SEC submissions metadata or a connector gap cannot satisfy earnings/guidance/filing substance. Preserve exact accepted source path/hash/as-of/quality in the advisory packet for the BOARD recorder.

- [ ] **Step 7: Run Task 2 tests and commit.**

  Run:

  ```bash
  .venv/bin/python -m pytest -q tests/test_loss_board_decision.py tests/test_decision_authority.py tests/test_execution_board.py tests/test_loss_review_evidence.py tests/test_policy_rule_approval_contract.py
  .venv/bin/ruff check tradingagents/policy/loss_board_decision.py tradingagents/policy/decision_authority.py tradingagents/evals/execution_board.py tradingagents/research/loss_review_evidence.py cli/main.py tests/test_decision_authority.py tests/test_execution_board.py tests/test_loss_review_evidence.py
  git diff --check
  ```

  Expected: all pass.

  Commit: `feat: let execution board close loss decisions`

---

### Task 3: Remove BOARD decisions from integrity recovery and rearm

**Files:**
- Modify: `tradingagents/orchestration/self_heal.py`
- Test: `tests/test_self_heal_handoff.py`
- Test: `tests/test_self_heal_recovery.py`

**Interfaces:**
- Consumes: a verified autonomous loss decision reference from the latest BOARD packet.
- Produces: self-heal classifications `business_decision_pending` and `resolved_no_action`; neither can rearm or write to the broker.

- [ ] **Step 1: Write RED classification and side-effect tests.**

  Assert exact `hourly + board_review` and `execution_board_review + board_review` signals are owned by `portfolio_executive`, have `may_rearm=false`, and are never `recoverable_integrity`. A valid HOLD must terminate `resolved_no_action` with frozen control bytes unchanged, no recovery run, no rearm receipt, no promotion/reconciliation/focused-test phase, and no broker calls. A valid SELL decision must also preserve the freeze and end `decision_resolved_execution_pending`.

- [ ] **Step 2: Run focused self-heal tests and confirm RED.**

  Run:

  ```bash
  .venv/bin/python -m pytest -q \
    tests/test_self_heal_handoff.py \
    tests/test_self_heal_recovery.py \
    -k 'board or loss_review'
  ```

  Expected: failures showing the current `recoverable_integrity`/`may_rearm=true` classification.

- [ ] **Step 3: Add the business-decision classification.**

  Classify BOARD review as `business_decision_pending`, owner `portfolio_executive`, allowed effect `trade_decision`, and forbidden execution/control effects. Do not route it into `coordinate_verified_recovery`. If the exact latest BOARD packet contains a verified HOLD, resolve with no action. If it contains a verified SELL, resolve the decision but report that a separate execution intent is required. Missing/invalid decision evidence remains retryable portfolio work, not a permanent integrity error.

- [ ] **Step 4: Remove misleading rearm semantics.**

  Ensure BOARD-only signals cannot set `may_rearm`, cannot select the recovery recipe, cannot invoke `resolve_authority` as a recovery phase, and cannot create a recovery incident. Retain integrity recovery behavior for actual policy conflicts and reconciliation failures.

- [ ] **Step 5: Run Task 3 tests and commit.**

  Run:

  ```bash
  .venv/bin/python -m pytest -q tests/test_self_heal_handoff.py tests/test_self_heal_recovery.py tests/test_recovery_coordinator.py
  .venv/bin/ruff check tradingagents/orchestration/self_heal.py tests/test_self_heal_handoff.py tests/test_self_heal_recovery.py
  git diff --check
  ```

  Expected: all pass.

  Commit: `fix: keep board decisions out of live recovery`

---

### Task 4: Align role contract, compact language, and installed BOARD automation

**Files:**
- Modify: `config/automation_roles.json`
- Modify: `config/autonomous_firm.json` only if the role/output contract requires it
- Modify: `scripts/automation_context_snapshot.py`
- Modify: `/Users/corbinfloyd/.codex/automations/tradingagents-autonomous-execution-board/automation.toml`
- Test: `tests/test_automation_roles.py` or the existing role-contract test module
- Test: `tests/test_automation_context_snapshot.py`

**Interfaces:**
- Consumes: BOARD report `autonomous_loss_decision` and its immutable decision reference.
- Produces: plain-language compact state that says autonomous HOLD/SELL, and an automation prompt that owns the decision but explicitly lacks execution authority.

- [ ] **Step 1: Write RED contract tests.**

  Assert the Portfolio Executive/BOARD assignment allows `trade_decision`, forbids all order and control effects, and requires a `portfolio_decision` output. Assert compact context never emits `manual_board_review` for a valid autonomous HOLD. Assert the installed automation prompt says it has trade-decision authority and no execution/order authority.

- [ ] **Step 2: Run the focused contract tests and confirm RED.**

  Run the exact discovered role-contract tests plus `tests/test_automation_context_snapshot.py`.

- [ ] **Step 3: Update prompt and compact language.**

  Replace “no trading authority” with “you own HOLD-versus-SELL trade decisions; you do not own execution or order submission.” Require exact immutable evidence binding, deterministic HOLD on incomplete evidence, and no human-decision request. Preserve notification policy `failed_runs_only` and the current schedule.

- [ ] **Step 4: Run Task 4 tests and commit tracked changes.**

  Run:

  ```bash
  .venv/bin/python -m pytest -q tests/test_automation_context_snapshot.py tests/test_authority.py tests/test_authority_role_alignment.py
  .venv/bin/ruff check scripts/automation_context_snapshot.py tests/test_automation_context_snapshot.py tests/test_authority.py tests/test_authority_role_alignment.py
  git diff --check
  ```

  Verify the external automation file separately and record its exact diff in the task report; do not add it to the repository commit.

  Commit: `docs: align autonomous board decision contract`

---

### Task 5: Independent review, integration, and read-only runtime proof

**Files:**
- Modify: `.superpowers/sdd/2026-08-13-autonomous-firm-reassessment-and-resumption/progress.md` (ignored runtime progress ledger)
- No live-control, schedule-time, broker, risk-envelope, or order changes.

**Interfaces:**
- Consumes: all prior commits and the current TSM runtime evidence.
- Produces: reviewed integrated code plus a fresh TSM autonomous decision packet and refreshed compact/self-heal evidence.

- [ ] **Step 1: Run independent source-only spec and quality reviews.**

  Reviewers must specifically test/inspect exact evidence binding, HOLD fail-closed behavior, SELL completeness, DecisionLedger durability, no execution authority, self-heal no-rearm semantics, and automation-role alignment. Any P0/P1 is NO-GO and must be repaired before integration.

- [ ] **Step 2: Run focused and adjacent verification.**

  Run:

  ```bash
  .venv/bin/python -m pytest -q \
    tests/test_loss_board_decision.py \
    tests/test_decision_authority.py \
    tests/test_loss_review_evidence.py \
    tests/test_execution_board.py \
    tests/test_self_heal_handoff.py \
    tests/test_self_heal_recovery.py \
    tests/test_recovery_coordinator.py \
    tests/test_live_gate.py \
    tests/test_execution_safety.py \
    tests/test_alpaca_supervisor.py
  .venv/bin/ruff check cli tradingagents scripts tests
  .venv/bin/python -m compileall -q cli tradingagents scripts
  git diff --check
  ```

- [ ] **Step 3: Integrate only after GO and refresh the code graph.**

  Fast-forward the reviewed branch into canonical `master`, confirm a clean tracked tree, and re-index `/Users/corbinfloyd/Documents/TradingAgents`.

- [ ] **Step 4: Generate fresh read-only TSM evidence and BOARD output.**

  Run with `TA_LIVE_SUBMIT=0`:

  ```bash
  .venv/bin/python -m cli.main research loss-review-evidence --json-output
  .venv/bin/python -m cli.main research execution-board-review --json-output
  .venv/bin/python -m cli.main research self-heal-handoff --json-output
  .venv/bin/python -m cli.main research self-heal-plan --execute-safe --json-output
  .venv/bin/python scripts/automation_context_snapshot.py --write
  ```

  Expected current-state proof: TSM decision is autonomous `HOLD`; no human decision is requested; self-heal does not start integrity recovery or rearm; order/submission count stays zero; `results/policy/live_control.json` remains frozen and byte-identical across these commands.

- [ ] **Step 5: Update the progress ledger and continue readiness.**

  Record exact commits, test counts, review verdicts, runtime packet paths, zero-submit proof, and the still-frozen live posture. Continue the five successful market-evidence-day requirement and rerun preopen only in the real tradeable preopen window. Do not rearm without the previously required separate explicit live-control authorization after every readiness gate passes.
