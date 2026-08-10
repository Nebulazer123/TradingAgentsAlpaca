# Autonomous Control and Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give TradingAgents explicit machine authority over trading and ordinary recovery, ensure every freeze has an owner and bounded recovery path, and allow an independently verified repair to issue a short-lived live-control lease without ever placing an order from the recovery plane.

**Architecture:** Add a machine-readable authority charter, append-only incident ledger, deterministic policy-authority resolver, generic read-only Alpaca reconciliation, recovery-readiness verifier, and bounded re-arm service. Existing policy and broker code remain the only submit path. `self_heal.py` becomes an adapter into this recovery service instead of an advisory-only dead end.

**Tech Stack:** Python enums/dataclasses, JSON/JSONL packets, Typer CLI, existing atomic file writers, existing Alpaca read APIs, existing promotion sync/live gate/live control modules, and pytest.

## Global Constraints

- Recovery never calls submit, cancel, replace, or close-position broker APIs.
- Re-arm writes a lease of at most 90 minutes and does not submit a trade.
- The repairer and verifier must have different `run_id` values and roles.
- A preregistered policy exit remains authorized after advisory research refresh; advisory evidence cannot revoke deterministic policy authority.
- A broker mismatch, unknown open order, missing idempotency evidence, invalid credentials, or malformed control state remains fail-closed.
- Preserve every existing live-gate check. Do not add a bypass parameter.
- Keep `cli/main.py` thin; business logic belongs in importable modules.

---

### Task 1: Define The Machine Authority Charter

**Files:**
- Create: `tradingagents/orchestration/authority.py`
- Create: `config/autonomous_firm.json`
- Create: `tests/test_authority.py`
- Modify: `tradingagents/orchestration/__init__.py`

- [ ] **Step 1: Write the failing authority tests**

```python
import pytest

from tradingagents.orchestration.authority import ActionClass, authority_for


@pytest.mark.parametrize(
    ("action", "owner"),
    [
        (ActionClass.TRADE_DECISION, "portfolio_executive"),
        (ActionClass.STRATEGY_CHANGE, "strategy_learning"),
        (ActionClass.RISK_CHANGE, "portfolio_executive"),
        (ActionClass.PROMOTION_CHANGE, "strategy_learning"),
        (ActionClass.FREEZE, "integrity_controller"),
        (ActionClass.REPAIR, "reliability_controller"),
        (ActionClass.VERIFY, "integrity_verifier"),
        (ActionClass.REARM, "reliability_controller"),
        (ActionClass.ORDER_SUBMIT, "execution_operator"),
    ],
)
def test_machine_actions_have_internal_owners(action, owner):
    verdict = authority_for(action)
    assert verdict.allowed is True
    assert verdict.human_required is False
    assert verdict.owner_role == owner


@pytest.mark.parametrize(
    "action",
    [
        ActionClass.CAPITAL_CHANGE,
        ActionClass.ACCOUNT_IDENTITY_CHANGE,
        ActionClass.CREDENTIAL_CHANGE,
        ActionClass.CHARTER_CHANGE,
    ],
)
def test_external_authority_stays_with_user(action):
    verdict = authority_for(action)
    assert verdict.allowed is False
    assert verdict.human_required is True
    assert verdict.owner_role == "account_owner"
```

- [ ] **Step 2: Run the tests and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_authority.py -q
```

Expected: FAIL because `tradingagents.orchestration.authority` does not exist.

- [ ] **Step 3: Implement the complete authority model**

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionClass(str, Enum):
    TRADE_DECISION = "trade_decision"
    STRATEGY_CHANGE = "strategy_change"
    RISK_CHANGE = "risk_change"
    PROMOTION_CHANGE = "promotion_change"
    FREEZE = "freeze"
    REPAIR = "repair"
    VERIFY = "verify"
    REARM = "rearm"
    ORDER_SUBMIT = "order_submit"
    CAPITAL_CHANGE = "capital_change"
    ACCOUNT_IDENTITY_CHANGE = "account_identity_change"
    CREDENTIAL_CHANGE = "credential_change"
    CHARTER_CHANGE = "charter_change"


@dataclass(frozen=True)
class AuthorityVerdict:
    action: ActionClass
    allowed: bool
    human_required: bool
    owner_role: str
    reason: str


_MACHINE_OWNERS = {
    ActionClass.TRADE_DECISION: "portfolio_executive",
    ActionClass.STRATEGY_CHANGE: "strategy_learning",
    ActionClass.RISK_CHANGE: "portfolio_executive",
    ActionClass.PROMOTION_CHANGE: "strategy_learning",
    ActionClass.FREEZE: "integrity_controller",
    ActionClass.REPAIR: "reliability_controller",
    ActionClass.VERIFY: "integrity_verifier",
    ActionClass.REARM: "reliability_controller",
    ActionClass.ORDER_SUBMIT: "execution_operator",
}
_HUMAN_ACTIONS = {
    ActionClass.CAPITAL_CHANGE,
    ActionClass.ACCOUNT_IDENTITY_CHANGE,
    ActionClass.CREDENTIAL_CHANGE,
    ActionClass.CHARTER_CHANGE,
}


def authority_for(action: ActionClass | str) -> AuthorityVerdict:
    normalized = action if isinstance(action, ActionClass) else ActionClass(action)
    owner = _MACHINE_OWNERS.get(normalized)
    if owner is not None:
        return AuthorityVerdict(
            action=normalized,
            allowed=True,
            human_required=False,
            owner_role=owner,
            reason="owned by the autonomous experiment charter",
        )
    if normalized in _HUMAN_ACTIONS:
        return AuthorityVerdict(
            action=normalized,
            allowed=False,
            human_required=True,
            owner_role="account_owner",
            reason="requires external account or charter authority",
        )
    raise ValueError(f"unclassified action: {normalized.value}")
```

- [ ] **Step 4: Add the machine-readable charter**

```json
{
  "schema_version": 1,
  "experiment": "autonomous_growth",
  "decision_owner": "machine",
  "machine_actions": [
    "trade_decision",
    "strategy_change",
    "risk_change",
    "promotion_change",
    "freeze",
    "repair",
    "verify",
    "rearm",
    "order_submit"
  ],
  "human_actions": [
    "capital_change",
    "account_identity_change",
    "credential_change",
    "charter_change"
  ],
  "recovery_may_submit_orders": false,
  "max_rearm_ttl_minutes": 90
}
```

- [ ] **Step 5: Run tests and commit**

```bash
uv run --with pytest python -m pytest tests/test_authority.py tests/test_autonomous_firm_charter.py -q
git add tradingagents/orchestration/authority.py tradingagents/orchestration/__init__.py config/autonomous_firm.json tests/test_authority.py tests/test_autonomous_firm_charter.py
git commit -m "feat: define autonomous firm authority"
```

Expected: PASS, then one focused commit.

---

### Task 2: Add An Owned Incident State Machine

**Files:**
- Create: `tradingagents/orchestration/incidents.py`
- Create: `tests/test_incidents.py`
- Modify: `scripts/automation_context_snapshot.py`

- [ ] **Step 1: Write failing transition and ownership tests**

```python
import datetime as dt

import pytest

from tradingagents.orchestration.incidents import (
    Incident,
    IncidentStage,
    IncidentStore,
    transition_incident,
)


def _incident() -> Incident:
    return Incident.open(
        incident_id="inc-nflx-rule-conflict",
        kind="policy_rule_conflict",
        subject="NFLX",
        owner_role="reliability_controller",
        now=dt.datetime(2026, 7, 18, tzinfo=dt.timezone.utc),
    )


def test_freeze_incident_is_owned_and_actionable():
    incident = _incident()
    assert incident.stage is IncidentStage.DETECTED
    assert incident.owner_role == "reliability_controller"
    assert incident.next_action
    assert incident.retry_budget == 3


def test_only_declared_transitions_are_allowed():
    incident = transition_incident(_incident(), IncidentStage.DIAGNOSING)
    incident = transition_incident(incident, IncidentStage.REPAIRING)
    with pytest.raises(ValueError, match="invalid incident transition"):
        transition_incident(incident, IncidentStage.CLOSED)


def test_store_writes_append_only_event_and_latest_snapshot(tmp_path):
    store = IncidentStore(tmp_path)
    incident = store.record(_incident(), event="opened")
    assert (tmp_path / "events.jsonl").read_text().count("\n") == 1
    assert (tmp_path / "incidents" / incident.incident_id / "latest.json").exists()
```

- [ ] **Step 2: Run and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_incidents.py -q
```

Expected: FAIL because the incident module does not exist.

- [ ] **Step 3: Implement the incident stages and legal transitions**

Use these exact stages:

```python
class IncidentStage(str, Enum):
    DETECTED = "detected"
    DIAGNOSING = "diagnosing"
    REPAIRING = "repairing"
    VERIFYING = "verifying"
    READY = "ready"
    REARMED = "rearmed"
    MONITORING = "monitoring"
    CLOSED = "closed"
    EXTERNAL_BLOCKED = "external_blocked"
```

Use this exact transition table:

```python
ALLOWED_TRANSITIONS = {
    IncidentStage.DETECTED: {
        IncidentStage.DIAGNOSING,
        IncidentStage.EXTERNAL_BLOCKED,
    },
    IncidentStage.DIAGNOSING: {
        IncidentStage.REPAIRING,
        IncidentStage.VERIFYING,
        IncidentStage.EXTERNAL_BLOCKED,
    },
    IncidentStage.REPAIRING: {
        IncidentStage.VERIFYING,
        IncidentStage.DIAGNOSING,
        IncidentStage.EXTERNAL_BLOCKED,
    },
    IncidentStage.VERIFYING: {
        IncidentStage.READY,
        IncidentStage.REPAIRING,
        IncidentStage.EXTERNAL_BLOCKED,
    },
    IncidentStage.READY: {
        IncidentStage.REARMED,
        IncidentStage.REPAIRING,
        IncidentStage.EXTERNAL_BLOCKED,
    },
    IncidentStage.REARMED: {
        IncidentStage.MONITORING,
        IncidentStage.REPAIRING,
    },
    IncidentStage.MONITORING: {
        IncidentStage.CLOSED,
        IncidentStage.REPAIRING,
    },
    IncidentStage.EXTERNAL_BLOCKED: {
        IncidentStage.DIAGNOSING,
    },
    IncidentStage.CLOSED: set(),
}
```

`Incident` must serialize these fields:

```text
schema_version
incident_id
kind
subject
stage
owner_role
created_at
updated_at
lease_expires_at
next_action
retry_budget
attempt_count
repairer_run_id
verifier_run_id
evidence_refs
external_blockers
history
```

`Incident.open()` must reject an empty owner, set `next_action="diagnose_root_cause"`, set `retry_budget=3`, and issue a 30-minute ownership lease. `transition_incident()` must append a history event and reject any transition not in `ALLOWED_TRANSITIONS`.

- [ ] **Step 4: Implement the store**

`IncidentStore.record()` must:

1. Atomically write `results/control_plane/incidents/<incident_id>/latest.json`.
2. Append one compact JSON line to `results/control_plane/incidents/events.jsonl`.
3. Atomically update `results/control_plane/incidents/latest.json`.
4. Never rewrite or truncate `events.jsonl`.

Use `tradingagents.policy.io.atomic_write_text` for mutable snapshots.

- [ ] **Step 5: Add compact incident status to the context snapshot**

Add only:

```json
{
  "active_incident_count": 1,
  "oldest_active_incident_minutes": 12,
  "unowned_incident_count": 0,
  "external_blocked_count": 0,
  "latest_incident_ref": "results/control_plane/incidents/inc-nflx-rule-conflict/latest.json"
}
```

Do not embed incident histories or raw evidence in compact context.

- [ ] **Step 6: Verify and commit**

```bash
uv run --with pytest python -m pytest tests/test_incidents.py tests/test_automation_context_snapshot.py -q
git add tradingagents/orchestration/incidents.py scripts/automation_context_snapshot.py tests/test_incidents.py tests/test_automation_context_snapshot.py
git commit -m "feat: add owned incident lifecycle"
```

Expected: PASS.

---

### Task 3: Resolve The NFLX Policy-Rule Authority Conflict

**Files:**
- Create: `tradingagents/policy/decision_authority.py`
- Add/preserve: `tests/test_policy_rule_approval_contract.py`
- Modify: `tradingagents/research/loss_review_evidence.py`
- Modify: `tradingagents/evals/execution_board.py`
- Modify: `tradingagents/brokers/supervisor/loss_review.py`

- [ ] **Step 1: Bring the existing NFLX regression into the worktree**

Copy the exact pre-existing test from the original checkout:

```text
tests/test_policy_rule_approval_contract.py
```

Do not rewrite its NFLX fixture or expected `pre_registered_policy_approval_preserved` result.

- [ ] **Step 2: Add deterministic authority tests**

```python
from tradingagents.policy.decision_authority import resolve_exit_authority


def test_advisory_refresh_cannot_revoke_preregistered_policy_exit():
    verdict = resolve_exit_authority(
        supervisor_review={
            "allowed": True,
            "policy_rule_exit": True,
            "allowed_exit_reason": "policy_stop_floor",
            "exit_policy_rule": "catastrophic_stop",
        },
        advisory_analysis={
            "requires_board_decision": True,
            "approval_effect": "board_review_input_not_loss_exit_approval",
        },
    )
    assert verdict.allowed is True
    assert verdict.authority_source == "pre_registered_policy_rule"
    assert verdict.requires_additional_decision is False


def test_discretionary_loss_exit_still_requires_machine_board_decision():
    verdict = resolve_exit_authority(
        supervisor_review={"allowed": False, "policy_rule_exit": False},
        advisory_analysis={"requires_board_decision": True},
    )
    assert verdict.allowed is False
    assert verdict.requires_additional_decision is True
    assert verdict.decision_owner == "portfolio_executive"
```

- [ ] **Step 3: Run and confirm RED**

```bash
uv run --with pytest python -m pytest \
  tests/test_policy_rule_approval_contract.py \
  tests/test_decision_authority.py -q
```

Expected: FAIL before the resolver exists or while the refresh downgrades policy authority.

- [ ] **Step 4: Implement the resolver**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


POLICY_EXIT_REASONS = frozenset({"policy_stop_floor", "policy_time_stop"})


@dataclass(frozen=True)
class ExitAuthorityVerdict:
    allowed: bool
    authority_source: str
    requires_additional_decision: bool
    decision_owner: str
    reason: str


def resolve_exit_authority(
    *,
    supervisor_review: Mapping[str, Any],
    advisory_analysis: Mapping[str, Any] | None,
) -> ExitAuthorityVerdict:
    reason = str(supervisor_review.get("allowed_exit_reason") or "")
    policy_exit = (
        supervisor_review.get("allowed") is True
        and supervisor_review.get("policy_rule_exit") is True
        and reason in POLICY_EXIT_REASONS
    )
    if policy_exit:
        return ExitAuthorityVerdict(
            allowed=True,
            authority_source="pre_registered_policy_rule",
            requires_additional_decision=False,
            decision_owner="execution_operator",
            reason=f"pre-registered exit rule remains authoritative: {reason}",
        )
    advisory = advisory_analysis or {}
    if advisory.get("requires_board_decision") is True:
        return ExitAuthorityVerdict(
            allowed=False,
            authority_source="advisory_research",
            requires_additional_decision=True,
            decision_owner="portfolio_executive",
            reason="discretionary loss exit requires an internal portfolio decision",
        )
    return ExitAuthorityVerdict(
        allowed=bool(supervisor_review.get("allowed")),
        authority_source="supervisor_review",
        requires_additional_decision=False,
        decision_owner="portfolio_executive",
        reason=str(supervisor_review.get("allowed_exit_reason_source") or "supervisor review"),
    )
```

- [ ] **Step 5: Make all consumers call the resolver**

In loss-review evidence:

```python
authority = resolve_exit_authority(
    supervisor_review=review,
    advisory_analysis=advisory_analysis,
)
advisory_analysis["review_allowed_after_refresh"] = authority.allowed
advisory_analysis["authority_source"] = authority.authority_source
advisory_analysis["requires_board_decision"] = authority.requires_additional_decision
```

In the execution BOARD, replace string heuristics for policy-rule approval with `resolve_exit_authority()`. Keep discretionary BOARD decisions internal; never emit a prompt asking the account owner to approve a trade.

- [ ] **Step 6: Verify and commit**

```bash
uv run --with pytest python -m pytest \
  tests/test_policy_rule_approval_contract.py \
  tests/test_decision_authority.py \
  tests/test_loss_review_evidence.py \
  tests/test_execution_board.py \
  tests/test_exit_policy.py -q
git add tradingagents/policy/decision_authority.py tradingagents/research/loss_review_evidence.py tradingagents/evals/execution_board.py tradingagents/brokers/supervisor/loss_review.py tests/test_policy_rule_approval_contract.py tests/test_decision_authority.py tests/test_loss_review_evidence.py tests/test_execution_board.py tests/test_exit_policy.py
git commit -m "fix: preserve preregistered exit authority"
```

Expected: PASS; NFLX is no longer blocked by advisory/manual-approval wording.

---

### Task 4: Generalize Read-Only Broker Reconciliation

**Files:**
- Modify: `tradingagents/brokers/alpaca_reconciliation.py`
- Modify: `tradingagents/execution/reconcile.py`
- Modify: `cli/main.py`
- Create: `tests/test_symbol_reconciliation.py`
- Modify: `tests/test_alpaca_cli.py`

- [ ] **Step 1: Write a broker spy and failing generic tests**

```python
class ReadOnlyBrokerSpy:
    def __init__(self, positions, orders):
        self.positions = positions
        self.orders = orders
        self.write_calls = []

    def list_positions(self):
        return self.positions

    def list_orders(self, status="all"):
        return self.orders

    def get_order_by_client_order_id(self, client_order_id):
        return next(
            (item for item in self.orders if item.get("client_order_id") == client_order_id),
            None,
        )

    def submit_order(self, *args, **kwargs):
        self.write_calls.append(("submit", args, kwargs))
        raise AssertionError("reconciliation attempted a broker write")
```

Test `NFLX`, `ORCL`, an empty symbol, an unexpected open order, a position mismatch, and a prior packet whose submission count exceeds its recorded client-order IDs.

- [ ] **Step 2: Run and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_symbol_reconciliation.py -q
```

Expected: FAIL because reconciliation is still ORCL-specific.

- [ ] **Step 3: Add the generic result**

```python
@dataclass(frozen=True)
class SymbolReconciliationResult:
    symbol: str
    matched: bool
    position: dict
    open_orders: list[dict]
    recent_fills: list[dict]
    checked_client_order_ids: list[str]
    issues: list[str]
    read_only: bool = True
    broker_write_calls: int = 0
```

Implement:

```python
def reconcile_symbol_incident(
    *,
    symbol: str,
    packet_paths: Sequence[str | Path],
    live_client,
    expected_qty: Decimal | str | None = None,
) -> SymbolReconciliationResult:
```

Requirements:

- Normalize `symbol` using the repo's shared symbol helper.
- Read positions and orders only.
- Reuse `reconcile_latest_packet_live_orders()` for client-order-id checks.
- Filter all output to the requested symbol.
- Treat an unknown symbol order as an issue, not as permission to cancel it.
- Return `broker_write_calls=0`.
- Preserve `reconcile_orcl_sell_state()` as a compatibility wrapper that calls the generic implementation.

- [ ] **Step 4: Add a generic CLI adapter**

Add:

```text
alpaca reconcile-symbol-incident
  --symbol NFLX
  --packet-path <repeatable>
  --expected-qty 0.320946047
  --output-dir results/control_plane/reconciliation
  --json-output
```

The command payload must include:

```json
{
  "kind": "symbol_broker_reconciliation",
  "read_only": true,
  "can_submit_orders": false,
  "execution_authority": "none",
  "broker_write_calls": 0
}
```

- [ ] **Step 5: Verify and commit**

```bash
uv run --with pytest python -m pytest \
  tests/test_symbol_reconciliation.py \
  tests/test_alpaca_reconciliation.py \
  tests/test_alpaca_cli.py -q
git add tradingagents/brokers/alpaca_reconciliation.py tradingagents/execution/reconcile.py cli/main.py tests/test_symbol_reconciliation.py tests/test_alpaca_reconciliation.py tests/test_alpaca_cli.py
git commit -m "feat: add generic read-only broker reconciliation"
```

Expected: PASS; all spies report zero broker writes.

---

### Task 5: Add Independent Recovery Verification And Short-Lived Re-Arm

**Files:**
- Create: `tradingagents/orchestration/recovery.py`
- Create: `tests/test_recovery_coordinator.py`
- Modify: `tradingagents/policy/live_control.py`
- Modify: `cli/main.py`

- [ ] **Step 1: Write failing readiness tests**

```python
import pytest

from tradingagents.orchestration.recovery import (
    RecoveryEvidence,
    evaluate_rearm_readiness,
)


def _evidence(**overrides):
    values = {
        "incident_id": "inc-nflx-rule-conflict",
        "repairer_run_id": "repair-1",
        "verifier_run_id": "verify-1",
        "root_cause_resolved": True,
        "focused_tests_passed": True,
        "promotion_evidence_fresh": True,
        "promotion_issues": (),
        "broker_reconciliation_matched": True,
        "broker_reconciliation_issues": (),
        "broker_write_calls": 0,
        "external_blockers": (),
    }
    values.update(overrides)
    return RecoveryEvidence(**values)


def test_clean_independent_evidence_is_ready():
    verdict = evaluate_rearm_readiness(_evidence())
    assert verdict.ready is True
    assert verdict.issues == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"verifier_run_id": "repair-1"},
        {"root_cause_resolved": False},
        {"focused_tests_passed": False},
        {"promotion_evidence_fresh": False},
        {"promotion_issues": ("rule conflict",)},
        {"broker_reconciliation_matched": False},
        {"broker_reconciliation_issues": ("unknown open order",)},
        {"broker_write_calls": 1},
        {"external_blockers": ("credentials",)},
    ],
)
def test_any_unresolved_integrity_condition_blocks_rearm(overrides):
    assert evaluate_rearm_readiness(_evidence(**overrides)).ready is False
```

- [ ] **Step 2: Run and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_recovery_coordinator.py -q
```

Expected: FAIL because the recovery module does not exist.

- [ ] **Step 3: Implement evidence and verdict types**

```python
@dataclass(frozen=True)
class RecoveryEvidence:
    incident_id: str
    repairer_run_id: str
    verifier_run_id: str
    root_cause_resolved: bool
    focused_tests_passed: bool
    promotion_evidence_fresh: bool
    promotion_issues: tuple[str, ...]
    broker_reconciliation_matched: bool
    broker_reconciliation_issues: tuple[str, ...]
    broker_write_calls: int
    external_blockers: tuple[str, ...]


@dataclass(frozen=True)
class RecoveryVerdict:
    ready: bool
    issues: tuple[str, ...]
```

`evaluate_rearm_readiness()` must add a specific issue for every failed field and must reject matching repair/verifier run IDs.

- [ ] **Step 4: Implement the bounded re-arm operation**

```python
MAX_REARM_TTL_MINUTES = 90


def rearm_after_verified_recovery(
    *,
    evidence: RecoveryEvidence,
    control_path: str | Path,
    receipt_dir: str | Path,
    ttl_minutes: int = MAX_REARM_TTL_MINUTES,
    now: datetime.datetime | None = None,
) -> dict:
    verdict = evaluate_rearm_readiness(evidence)
    if not verdict.ready:
        raise ValueError("rearm blocked: " + "; ".join(verdict.issues))
    bounded_ttl = min(max(1, int(ttl_minutes)), MAX_REARM_TTL_MINUTES)
    current = now or datetime.datetime.now(tz=datetime.timezone.utc)
    expires_at = current + datetime.timedelta(minutes=bounded_ttl)
    write_live_control_state(
        control_path,
        frozen=False,
        reason=f"verified recovery {evidence.incident_id}",
        dead_man_expires_at=expires_at,
    )
    receipt = {
        "schema_version": 1,
        "kind": "verified_rearm_receipt",
        "incident_id": evidence.incident_id,
        "repairer_run_id": evidence.repairer_run_id,
        "verifier_run_id": evidence.verifier_run_id,
        "issued_at": current.isoformat(),
        "expires_at": expires_at.isoformat(),
        "ttl_minutes": bounded_ttl,
        "broker_write_calls": evidence.broker_write_calls,
        "can_submit_orders": False,
    }
    return write_rearm_receipt(receipt, receipt_dir)
```

`write_rearm_receipt()` must write a timestamped immutable receipt plus `latest.json` under `results/control_plane/rearm/`.

- [ ] **Step 5: Add a thin recovery CLI**

Add:

```text
policy recover-incident
  --incident-path
  --reconciliation-path
  --promotion-sync-path
  --focused-proof-path
  --repairer-run-id
  --verifier-run-id
  --ttl-minutes 90
  --json-output
```

The command reads evidence packets, calls `evaluate_rearm_readiness()`, and calls `rearm_after_verified_recovery()` only on READY. It has no broker client and therefore cannot place an order.

- [ ] **Step 6: Verify and commit**

```bash
uv run --with pytest python -m pytest \
  tests/test_recovery_coordinator.py \
  tests/test_live_gate.py \
  tests/test_alpaca_cli.py -q
git add tradingagents/orchestration/recovery.py tradingagents/policy/live_control.py cli/main.py tests/test_recovery_coordinator.py tests/test_live_gate.py tests/test_alpaca_cli.py
git commit -m "feat: verify and rearm recovered incidents"
```

Expected: PASS.

---

### Task 6: Convert Self-Heal From Advisory Dead End To Recovery Owner

**Files:**
- Modify: `tradingagents/orchestration/self_heal.py`
- Modify: `tests/test_self_heal_handoff.py`
- Create: `tests/test_self_heal_recovery.py`
- Modify: `scripts/automation_context_snapshot.py`

- [ ] **Step 1: Write failing classification tests**

```python
def test_policy_conflict_is_recoverable_not_manual_escalation():
    signal = classify_recovery_signal(
        {"label": "policy_rule_conflict", "reason": "approval_conflict", "symbol": "NFLX"}
    )
    assert signal["classification"] == "recoverable_integrity"
    assert signal["owner_role"] == "reliability_controller"
    assert signal["recipe"] == "resolve_policy_sync_reconcile_verify_rearm"


def test_unknown_broker_order_is_external_blocked():
    signal = classify_recovery_signal(
        {"label": "broker_reconciliation", "reason": "unknown_open_order"}
    )
    assert signal["classification"] == "external_blocked"
    assert signal["may_rearm"] is False


def test_recovery_recipe_cannot_submit_or_cancel_orders():
    recipe = recovery_recipe("resolve_policy_sync_reconcile_verify_rearm")
    assert "submit_order" in recipe["forbidden_effects"]
    assert "cancel_order" in recipe["forbidden_effects"]
    assert "replace_order" in recipe["forbidden_effects"]
```

- [ ] **Step 2: Run and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_self_heal_recovery.py -q
```

Expected: FAIL because all order-adjacent state is currently escalated to manual review.

- [ ] **Step 3: Replace the forbidden-effect boundary**

Use:

```python
FORBIDDEN_EFFECTS = (
    "submit_order",
    "cancel_order",
    "replace_order",
    "close_position",
    "waive_live_gate",
    "expose_credentials",
    "change_experiment_charter",
)

RECOVERY_EFFECTS = (
    "resolve_policy_conflict",
    "regenerate_promotion_evidence",
    "sync_promotion_state_from_evidence",
    "read_only_broker_reconciliation",
    "run_focused_tests",
    "independent_verification",
    "refresh_live_control_after_ready",
)
```

Do not classify a repair as forbidden merely because it reads order state. Classify by effect:

- Broker read: recoverable.
- Broker write: forbidden in recovery.
- Promotion recomputation from existing evidence: recoverable.
- Inventing or waiving promotion evidence: forbidden.
- Live-control freeze: allowed.
- Live-control refresh: allowed only through `rearm_after_verified_recovery()`.

- [ ] **Step 4: Add the NFLX recovery recipe**

The deterministic recipe is:

```text
1. Resolve exit authority with decision_authority.resolve_exit_authority.
2. Regenerate current loss-review/promotion evidence.
3. Run policy sync-promotion with --arm-live only when the strategy evidence passes.
4. Run alpaca reconcile-symbol-incident --symbol NFLX read-only.
5. Run the focused policy/reconciliation tests.
6. Have a distinct verifier run evaluate the packet set.
7. Refresh live control for at most 90 minutes.
8. Move the incident to MONITORING.
```

The recipe must stop at the first failed step and record the exact evidence path.

- [ ] **Step 5: Keep bounded retries**

Use:

```json
{
  "max_attempts": 3,
  "backoff_seconds": [0, 30, 120],
  "on_exhaustion": "external_blocked",
  "lease_minutes": 30
}
```

Exhaustion means the incident remains frozen and owned; it does not become an ownerless manual handoff.

- [ ] **Step 6: Verify and commit**

```bash
uv run --with pytest python -m pytest \
  tests/test_self_heal_handoff.py \
  tests/test_self_heal_recovery.py \
  tests/test_recovery_coordinator.py \
  tests/test_automation_context_snapshot.py -q
git add tradingagents/orchestration/self_heal.py scripts/automation_context_snapshot.py tests/test_self_heal_handoff.py tests/test_self_heal_recovery.py tests/test_automation_context_snapshot.py
git commit -m "feat: make self-heal own verified recovery"
```

Expected: PASS.

---

### Task 7: Run The Clean NFLX Recovery Acceptance Packet

**Files:**
- Create runtime evidence: `results/control_plane/incidents/`
- Create runtime evidence: `results/control_plane/reconciliation/`
- Create runtime evidence: `results/control_plane/rearm/`
- Create: `tests/integration/test_autonomous_recovery_contract.py`

- [ ] **Step 1: Run the policy-rule regression**

```bash
uv run --with pytest python -m pytest \
  tests/test_policy_rule_approval_contract.py \
  tests/test_decision_authority.py \
  tests/test_loss_review_evidence.py \
  tests/test_execution_board.py -q
```

Expected: PASS.

- [ ] **Step 2: Regenerate and sync current promotion evidence in a fixture directory**

Run the real command against copied fixture inputs, never the production live-control file:

```bash
uv run --no-sync python -m cli.main policy sync-promotion \
  --report-path tests/fixtures/autonomous_recovery/paper_tournament_latest.json \
  --state-path /tmp/tradingagents-nflx-recovery/promotion_state.json \
  --envelope-path config/risk_envelope.yaml \
  --arm-live \
  --ci-green \
  --json-output
```

Expected: no unresolved sleeve issues.

- [ ] **Step 3: Run clean read-only broker reconciliation with a fake client**

```bash
uv run --with pytest python -m pytest tests/test_symbol_reconciliation.py -q
```

Expected: matched reconciliation and zero broker write calls.

- [ ] **Step 4: Run independent verification and fixture re-arm**

```bash
uv run --with pytest python -m pytest tests/integration/test_autonomous_recovery_contract.py -q
```

Expected: the copied control file becomes unfrozen with a lease no longer than 90 minutes; the production control file is untouched.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_autonomous_recovery_contract.py tests/fixtures/autonomous_recovery
git commit -m "test: prove autonomous NFLX recovery"
```

Expected: PASS and one test-only commit.
