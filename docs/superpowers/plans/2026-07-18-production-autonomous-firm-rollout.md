# Production Autonomous Firm Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the autonomous-firm code into production through ten coordinated Codex automations that operate on Central Time, notify only on failed runs, recover ordinary failures without user input, and preserve the single guarded broker-execution path.

**Architecture:** Assign each existing automation one business authority and one explicit non-authority. Overnight research produces evidence, the paper tournament evolves strategies, the execution BOARD acts as portfolio executive, the safety sentinel and preopen job independently verify integrity, the self-healer repairs, the market supervisor executes only through the existing wrapper, the daily report summarizes, and wake/sleep controllers manage status. Production rollout moves through shadow, recovery canary, short-lived live lease, and five-trading-day proof.

**Tech Stack:** Codex automation APIs, RRULE schedules, `America/Chicago`, current local project target, TradingAgents CLI/wrapper scripts, JSON evidence packets, pytest, and Alpaca read/write separation.

## Global Constraints

- Use the `automation_update` tool for automation changes. Do not edit automation TOML files directly.
- Read the automation tool schema before constructing updates and send every required field.
- Preserve automation IDs and project target.
- Set all notification policies to `failed_runs_only`.
- Treat schedule hours as Central Time and verify displayed next-run times in `America/Chicago`.
- Every weekday job must consult the Alpaca market calendar and no-op on market holidays.
- Only `tradingagents-market-supervisor` may invoke the submit-capable wrapper.
- Recovery, verification, research, tournament, BOARD, daily report, and controllers may not submit, cancel, replace, or duplicate orders.
- A short-lived re-arm enables a later market-supervisor run; it is not an order authorization.
- Keep the two controller automations ACTIVE at all times. They may change only managed automation statuses.
- Do not declare rollout complete from scheduler status alone. Require packets, tests, next-run verification, and broker-write audit evidence.

---

### Task 1: Version The Automation Role Contracts In The Repo

**Files:**
- Create: `docs/orchestration/automation-role-contracts.md`
- Create: `config/automation_roles.json`
- Create: `tests/test_automation_role_contracts.py`
- Modify: `scripts/automation_context_snapshot.py`

- [ ] **Step 1: Write the failing role-contract test**

```python
import json
from pathlib import Path


def test_every_production_automation_has_one_owner_role():
    config = json.loads(Path("config/automation_roles.json").read_text())
    assert set(config["automations"]) == {
        "tradingagents-automation-sleep-controller",
        "tradingagents-automation-wake-controller",
        "tradingagents-autonomous-execution-board",
        "tradingagents-autonomous-safety-sentinel",
        "tradingagents-autonomous-self-healer",
        "tradingagents-daily-report",
        "tradingagents-market-supervisor",
        "tradingagents-overnight-research",
        "tradingagents-paper-tournament",
        "tradingagents-preopen-validation",
    }
    for automation in config["automations"].values():
        assert automation["owner_role"]
        assert automation["allowed_effects"]
        assert automation["forbidden_effects"]
        assert "submit_order" in automation["forbidden_effects"] or (
            automation["owner_role"] == "execution_operator"
        )


def test_only_market_supervisor_can_trigger_orders():
    config = json.loads(Path("config/automation_roles.json").read_text())
    submit_capable = [
        automation_id
        for automation_id, record in config["automations"].items()
        if "submit_order" in record["allowed_effects"]
    ]
    assert submit_capable == ["tradingagents-market-supervisor"]
```

- [ ] **Step 2: Run and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_automation_role_contracts.py -q
```

Expected: FAIL because the role registry does not exist.

- [ ] **Step 3: Add the complete role map**

Use:

```json
{
  "schema_version": 1,
  "timezone": "America/Chicago",
  "notification_policy": "failed_runs_only",
  "automations": {
    "tradingagents-automation-sleep-controller": {
      "owner_role": "schedule_controller",
      "allowed_effects": ["pause_managed_market_jobs"],
      "forbidden_effects": ["submit_order", "edit_repo", "repair_incident", "rearm_live_control"]
    },
    "tradingagents-automation-wake-controller": {
      "owner_role": "schedule_controller",
      "allowed_effects": ["activate_managed_market_jobs"],
      "forbidden_effects": ["submit_order", "edit_repo", "repair_incident", "rearm_live_control"]
    },
    "tradingagents-autonomous-execution-board": {
      "owner_role": "portfolio_executive",
      "allowed_effects": ["resolve_investment_conflict", "approve_internal_decision", "freeze_new_buys", "demote_strategy"],
      "forbidden_effects": ["submit_order", "cancel_order", "replace_order", "rearm_live_control"]
    },
    "tradingagents-autonomous-safety-sentinel": {
      "owner_role": "integrity_verifier",
      "allowed_effects": ["freeze_live_control", "verify_repair", "rearm_verified_recovery", "open_incident"],
      "forbidden_effects": ["submit_order", "cancel_order", "replace_order", "repair_own_finding"]
    },
    "tradingagents-autonomous-self-healer": {
      "owner_role": "reliability_controller",
      "allowed_effects": ["diagnose_incident", "repair_incident", "run_tests", "regenerate_evidence", "request_independent_verification"],
      "forbidden_effects": ["submit_order", "cancel_order", "replace_order", "verify_own_repair"]
    },
    "tradingagents-daily-report": {
      "owner_role": "reporter",
      "allowed_effects": ["read_packets", "render_report"],
      "forbidden_effects": ["submit_order", "edit_policy", "repair_incident", "rearm_live_control"]
    },
    "tradingagents-market-supervisor": {
      "owner_role": "execution_operator",
      "allowed_effects": ["run_guarded_wrapper", "submit_order"],
      "forbidden_effects": ["edit_repo", "change_strategy", "repair_incident", "rearm_live_control", "bypass_live_gate"]
    },
    "tradingagents-overnight-research": {
      "owner_role": "research_division",
      "allowed_effects": ["gather_evidence", "debate", "propose_strategy_genome", "write_research_packets"],
      "forbidden_effects": ["submit_order", "promote_without_evidence", "rearm_live_control"]
    },
    "tradingagents-paper-tournament": {
      "owner_role": "strategy_learning",
      "allowed_effects": ["mutate_strategy_genomes", "preregister_candidates", "paper_trade", "promote_evidence_backed_candidate", "demote_failed_candidate"],
      "forbidden_effects": ["submit_live_order", "bypass_promotion_gate", "rearm_live_control"]
    },
    "tradingagents-preopen-validation": {
      "owner_role": "integrity_verifier",
      "allowed_effects": ["read_only_reconciliation", "verify_repair", "rearm_verified_recovery", "freeze_live_control"],
      "forbidden_effects": ["submit_order", "cancel_order", "replace_order", "repair_own_finding"]
    }
  }
}
```

- [ ] **Step 4: Add contract drift to compact context**

Report:

```json
{
  "automation_role_contract_status": "pass",
  "unknown_automation_count": 0,
  "multiple_submit_capable_count": 0,
  "notification_mismatch_count": 0,
  "timezone_mismatch_count": 0
}
```

- [ ] **Step 5: Verify and commit**

```bash
uv run --with pytest python -m pytest tests/test_automation_role_contracts.py tests/test_automation_context_snapshot.py -q
git add docs/orchestration/automation-role-contracts.md config/automation_roles.json scripts/automation_context_snapshot.py tests/test_automation_role_contracts.py tests/test_automation_context_snapshot.py
git commit -m "docs: define automation chain of command"
```

Expected: PASS.

---

### Task 2: Set Central Time Schedules And Cost-Aware Models

**Files:**
- External authority: the ten Codex automations
- Update proof: `results/control_plane/proofs/automation-schedule.json`

- [ ] **Step 1: Load automation tools and read all ten records**

Search for `automation_update`, read its schema, then read the current ten automations. Confirm IDs, names, project target, current status, RRULE, model, reasoning effort, notification policy, execution environment, and working directory.

- [ ] **Step 2: Apply this schedule matrix**

All times are `America/Chicago`:

| Automation | RRULE | Model | Effort |
|---|---|---|---|
| Overnight research | `RRULE:FREQ=WEEKLY;BYHOUR=3;BYMINUTE=30;BYDAY=MO,TU,WE,TH,FR` | `gpt-5.6-sol` | `high` |
| Wake controller | `RRULE:FREQ=WEEKLY;BYHOUR=6;BYMINUTE=45;BYDAY=MO,TU,WE,TH,FR` | `gpt-5.6-luna` | `medium` |
| Self-healer | `RRULE:FREQ=WEEKLY;BYHOUR=7,9,11,13,15;BYMINUTE=3;BYDAY=MO,TU,WE,TH,FR` | `gpt-5.6-terra` | `high` |
| Preopen validation | `RRULE:FREQ=WEEKLY;BYHOUR=8;BYMINUTE=10;BYDAY=MO,TU,WE,TH,FR` | `gpt-5.6-terra` | `high` |
| Safety sentinel | `RRULE:FREQ=WEEKLY;BYHOUR=8,9,10,11,12,13,14;BYMINUTE=20;BYDAY=MO,TU,WE,TH,FR` | `gpt-5.6-luna` | `medium` |
| Market supervisor | `RRULE:FREQ=WEEKLY;BYHOUR=8,9,10,11,12,13,14;BYMINUTE=35;BYDAY=MO,TU,WE,TH,FR` | `gpt-5.6-terra` | `high` |
| Execution BOARD | `RRULE:FREQ=WEEKLY;BYHOUR=8,9,10,11,12,13,14;BYMINUTE=50;BYDAY=MO,TU,WE,TH,FR` | `gpt-5.6-terra` | `high` |
| Paper tournament | `RRULE:FREQ=WEEKLY;BYHOUR=9;BYMINUTE=10;BYDAY=MO,TU,WE,TH,FR` | `gpt-5.6-terra` | `high` |
| Daily report | `RRULE:FREQ=WEEKLY;BYHOUR=15;BYMINUTE=30;BYDAY=MO,TU,WE,TH,FR` | `gpt-5.6-luna` | `medium` |
| Sleep controller | `RRULE:FREQ=WEEKLY;BYHOUR=16;BYMINUTE=45;BYDAY=MO,TU,WE,TH,FR` | `gpt-5.6-luna` | `medium` |

For each update:

```text
notification_policy = failed_runs_only
execution_environment = local
target = existing local TradingAgents project
cwds = ["/Users/corbinfloyd/Documents/TradingAgents"]
```

If the automation API exposes a timezone field, set `America/Chicago`. If it does not, verify the Codex scheduler/account timezone is Central before accepting the RRULE.

- [ ] **Step 3: Preserve controller status behavior**

- Wake and sleep controllers remain `ACTIVE`.
- Managed jobs may be ACTIVE or PAUSED according to controller phase.
- `ACTIVE` means scheduled, not completed.
- Controllers never pause each other.

- [ ] **Step 4: Verify next runs**

The proof packet must include each automation's next run rendered in both Central and UTC. Reject the update if any market job appears one hour off or if market supervisor runs before 8:30 AM Central.

- [ ] **Step 5: Verify notifications**

Read all ten records again and assert:

```text
failed_runs_only = 10
all_runs = 0
missing = 0
```

Do not rely on the local TOML grep alone; use the automation API response as current authority.

---

### Task 3: Replace Advisory-Only Automation Prompts With The Chain Of Command

**Files:**
- External authority: the ten Codex automations
- Source copy: `docs/orchestration/automation-role-contracts.md`

- [ ] **Step 1: Update the self-healer prompt**

The full prompt must include these exact operational rules:

```text
You are TradingAgents Reliability Controller. Own every ordinary machine-resolvable incident through diagnosis, repair, focused tests, evidence regeneration, and a request for independent verification. Do not wait for the account owner for trade, strategy, promotion, risk, local-code, local-service, stale-evidence, rule-conflict, or scheduler repairs.

You may resolve policy-rule conflicts, regenerate loss-review and promotion evidence, sync promotion state from earned evidence, run generic read-only broker reconciliation, repair verified repo or local-service defects, and create/update the canonical incident record.

You may not submit, cancel, replace, or duplicate broker orders; waive the live gate; expose credentials; change capital/account identity; verify your own repair; or directly refresh live control. A different integrity-verifier run performs the final readiness check and short-lived re-arm.

Every nonterminal incident must end this run with an owner, stage, next action, evidence refs, attempt count, retry budget, and lease. On retry exhaustion, mark external_blocked with the exact unavailable authority; never leave an ownerless manual handoff.
```

Then list the exact recovery commands added by the control/recovery plan.

- [ ] **Step 2: Update safety sentinel and preopen prompts**

Both verifier prompts must say:

```text
You are an independent Integrity Verifier. Do not repair the state you are evaluating. Read the incident, repair proof, promotion sync, focused tests, and generic read-only broker reconciliation. Require a different repairer_run_id and verifier_run_id. If all deterministic readiness checks pass, call policy recover-incident to issue a live-control lease of at most 90 minutes. This does not submit an order. If any state is ambiguous, keep or create the freeze and return the incident to REPAIRING or EXTERNAL_BLOCKED with exact evidence.
```

Sentinel runs during market hours. Preopen performs the same verification before the first market-supervisor cycle.

- [ ] **Step 3: Update execution BOARD prompt**

The BOARD prompt must say:

```text
You are the Portfolio Executive. Resolve investment disagreements, strategy/risk conflicts, promotion/demotion recommendations, and discretionary loss exits without asking the account owner which trade to make. Preserve preregistered policy exits. Write a compact portfolio_decision packet with evidence refs and confidence. You may freeze new buys or demote a strategy. You may not call broker write APIs or refresh live control.
```

- [ ] **Step 4: Update market supervisor prompt**

The execution prompt must say:

```text
You are the Execution Operator. Make exactly one normal wrapper invocation for this scheduled cycle. The wrapper is the only order trigger. Do not edit code/config, repair incidents, refresh live control, change strategy, or bypass a guard. Read the newest decision, promotion, live-control, and reconciliation packets; let the command fail closed when any guard fails. Report the newest packet and broker-confirmed status. Never retry an uncertain submission.
```

- [ ] **Step 5: Update research and tournament prompts**

Overnight research:

```text
Research autonomously, use parallel specialist lanes only when independent, run bull/bear challenge, produce compact evidence packets, update forecasts/hypotheses, and propose validated strategy genomes. Do not choose a strategy by prose alone and do not call broker write APIs.
```

Paper tournament:

```text
Resolve prior outcomes, update contextual agent influence, mutate bounded strategy genomes, preregister before evaluation, run walk-forward and paper evaluation, sync earned promotion/demotion evidence, and roll back failed strategies to HOLD_CASH. Do not submit live orders or bypass promotion gates.
```

- [ ] **Step 6: Update daily report and controllers**

Daily report reports:

```text
portfolio result, current strategy, active incident owner/stage, latest recovery action, current live-control expiry, any external blocker, and no-action-needed when the machine owns the next step.
```

Wake/sleep controllers remain status-only and may edit only automation `status`.

- [ ] **Step 7: Re-read every updated automation**

Compare the live prompt digest against `docs/orchestration/automation-role-contracts.md`. Any mismatch is rollout-blocking.

---

### Task 4: Prove The Failure Chain In Shadow Mode

**Files:**
- Create: `tests/integration/test_automation_chain_of_command.py`
- Create runtime proof: `results/control_plane/proofs/automation-shadow.json`

- [ ] **Step 1: Create four synthetic incidents**

Fixtures:

```text
NFLX preregistered policy-rule conflict
stale promotion evidence
missing client_order_id after recorded submission
credential/OAuth failure
```

- [ ] **Step 2: Assert routing**

Expected:

```text
policy conflict -> self-healer repairs -> sentinel verifies -> re-arm eligible
stale promotion -> self-healer regenerates/syncs -> sentinel verifies -> re-arm eligible
missing client_order_id -> read-only reconcile -> remains frozen/external_blocked
credential/OAuth failure -> account_owner external blocker, no repeated repair loop
```

- [ ] **Step 3: Assert role separation**

The test must reject:

```text
self-healer verifying its own run
sentinel editing the repair
BOARD calling broker writes
market supervisor refreshing live control
controller editing repo files
research promoting without preregistration
```

- [ ] **Step 4: Run three complete shadow cycles**

For each cycle:

1. Activate jobs in a copied fixture environment.
2. Run in schedule order.
3. Keep `TA_LIVE_SUBMIT` unset.
4. Record packet paths and role/run IDs.
5. Assert zero broker write calls.

- [ ] **Step 5: Verify**

```bash
uv run --with pytest python -m pytest \
  tests/test_automation_role_contracts.py \
  tests/integration/test_automation_chain_of_command.py \
  tests/integration/test_autonomous_recovery_contract.py -q
```

Expected: PASS.

---

### Task 5: Run A Recovery Canary Against Copied Control State

**Files:**
- Copy at runtime: `results/policy/live_control.json`
- Use: `/tmp/tradingagents-recovery-canary/live_control.json`
- Create runtime proof: `results/control_plane/proofs/recovery-canary.json`

- [ ] **Step 1: Copy production inputs to a canary directory**

Copy only the live-control, promotion, risk-envelope, latest tournament, and relevant hourly evidence. Do not copy broker credentials.

- [ ] **Step 2: Freeze the canary control file**

Use:

```text
reason = synthetic_policy_rule_conflict
dead_man_expires_at = now
```

- [ ] **Step 3: Run self-healer logic**

Expected:

```text
incident stage = VERIFYING
repairer_run_id set
policy conflict resolved
promotion evidence fresh
broker reconciliation fixture matched
production live_control unchanged
```

- [ ] **Step 4: Run independent verifier logic**

Expected:

```text
verifier_run_id differs
recovery verdict = READY
canary lease <= 90 minutes
broker_write_calls = 0
incident stage = MONITORING
```

- [ ] **Step 5: Reject false canaries**

Repeat with a broker mismatch and prove the canary stays frozen.

---

### Task 6: Authorize One Short-Lived Production Live-Control Refresh

**Files:**
- Read: `results/control_plane/incidents/latest.json`
- Read: newest promotion sync packet
- Read: newest generic broker reconciliation packet
- Read: newest focused test proof
- Write: `results/control_plane/rearm/`

- [ ] **Step 1: Build the production go/no-go input**

Require:

```text
root cause resolved
NFLX preregistered policy authority preserved
promotion evidence current and internally consistent
generic reconciliation matched
no unknown open order
all recorded submissions have client_order_id
focused tests passed
repairer and verifier are different
no external blocker
recovery broker writes = 0
```

- [ ] **Step 2: Run `policy recover-incident`**

Use a TTL of 90 minutes or less.

Expected: a re-arm receipt; no wrapper or order command in this step.

- [ ] **Step 3: Run one normal market-supervisor cycle**

During an open market session only:

```bash
TA_LIVE_SUBMIT=1 /bin/zsh scripts/mac/ta_job.sh hourly
```

Invoke exactly once. Do not run another supervisor command concurrently.

- [ ] **Step 4: Read the newest hourly packet and broker status**

Confirm:

```text
decision
guard verdict
client_order_id when submitted
broker status
no duplicate
reconciliation result
packet path
```

No trade is also a valid result when the portfolio executive chooses `HOLD_CASH`.

- [ ] **Step 5: Move the incident to monitoring**

The incident closes only after the next clean market-supervisor reconciliation, not immediately after re-arm.

---

### Task 7: Run Five Trading Days Of Production Proof

**Files:**
- Create runtime proof: `results/control_plane/proofs/five-day-autonomy.json`
- Update: `docs/orchestration/autonomous-firm.md`
- Update: `AGENTS.md`
- Update: `CLAUDE.md`

- [ ] **Step 1: Collect daily metrics**

For each trading day:

```text
scheduled run count
failed run count
notification count
decision packet count
active incident count
oldest incident age
repairs attempted/succeeded
independent verifications
re-arms issued
re-arm TTL
unknown broker orders
duplicate order attempts
recovery broker write calls
strategy candidates created/promoted/demoted
agent forecast outcomes resolved
token/model route summary
```

- [ ] **Step 2: Enforce automatic rollback triggers**

Immediately freeze and open an incident on:

```text
broker mismatch
unknown order
duplicate idempotency key with mismatched intent
promotion digest mismatch
invalid live-control state
strategy drawdown breach
automation role-contract drift
more than one submit-capable automation
```

- [ ] **Step 3: Require production acceptance thresholds**

```json
{
  "unowned_incidents": 0,
  "recovery_broker_write_calls": 0,
  "duplicate_order_attempts": 0,
  "unknown_open_orders": 0,
  "manual_trade_approvals_requested": 0,
  "manual_repair_approvals_requested": 0,
  "notification_policy_mismatches": 0,
  "timezone_mismatches": 0,
  "max_rearm_ttl_minutes": 90,
  "focused_test_failures": 0
}
```

- [ ] **Step 4: Distinguish external blockers**

A credential/OAuth/account-identity/capital/charter blocker is allowed to remain `external_blocked`, but the packet must say exactly what external authority is missing and must not repeatedly spend tokens attempting an impossible repair.

- [ ] **Step 5: Write final operating documentation**

Document:

- Decision chain.
- Failure chain.
- Canonical state owners.
- Human-reserved actions.
- Central Time schedule.
- Automatic rollback.
- How to read one incident and one decision without loading raw history.

- [ ] **Step 6: Run final verification**

```bash
uv run --with pytest python -m pytest \
  tests/test_automation_role_contracts.py \
  tests/test_automation_health_audit.py \
  tests/test_automation_context_snapshot.py \
  tests/test_control_plane_patrol.py \
  tests/integration/test_automation_chain_of_command.py \
  tests/integration/test_autonomous_recovery_contract.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit documentation and tests**

```bash
git add docs/orchestration/autonomous-firm.md AGENTS.md CLAUDE.md tests
git commit -m "docs: hand off autonomous firm operations"
```

Expected: clean implementation worktree except ignored runtime evidence.
