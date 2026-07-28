# Capped Live Intent Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every future real Alpaca order fail before network I/O unless it carries one current, immutable, single-use authorization that binds the approved strategy, capped risk, exact payload, and recovery evidence.

**Architecture:** First eliminate the contradictory `autonomous_uncapped` configuration path so all autonomous sizing is bounded by the existing account and per-name caps. Then add a narrow `AuthorizedNormalTradeIntent` value object and a durable activation receipt. The lowest real broker-write wrapper validates the entire chain independently; the supervisor and CLI may only pass the exact object through. Existing paper submission remains a separate capability, and the old paired paper/live mirror becomes a deterministic refusal.

**Tech Stack:** Python 3.13, frozen dataclasses, `Decimal`, canonical JSON, SHA-256, existing immutable strategy evidence store, pytest, Ruff, Alpaca Trading API client-order IDs.

## Research and current-state basis

- The current wrapper is only three lines: `AlpacaRestClient.submit_order()` accepts any mapping and immediately POSTs it. Graph discovery found six inbound paths: hourly supervisor, manual CLI submit, paired execution, paper tournament, pullback paper, and a paper-only CLI route.
- `client_order_id` is the correct retry identity: Alpaca documents that it can be retrieved through `GET /v2/orders:by_client_order_id`, and its current CLI documentation says duplicate IDs are rejected. The intent therefore binds one exact ID and a retry first performs a read-only lookup; it never blindly POSTs a second order. Sources: <https://docs.alpaca.markets/us/docs/working-with-orders> and <https://docs.alpaca.markets/us/reference/getorderbyclientorderid>.
- `config/risk_envelope.example.yaml` and `docs/policy/live-budget-mode.md` already say `autonomous_uncapped` is retired, but `risk_envelope.py` still accepts it and `live_gate.py` still contains its bypasses. That is a genuine contradictory authority surface, not merely old prose.
- Task 6D3 is accepted at `a4648db`; it keeps every sleeve `live_enabled=false`. This plan does not re-arm live control, submit an order, edit a real risk envelope, or turn a 6D eligibility record into live permission.

## Global Constraints

- All autonomous live sizing must remain inside `account_max_capital_at_risk_usd` and `per_name_cap_usd`; `autonomous_uncapped` is invalid input.
- No test may use live credentials, call an Alpaca endpoint, refresh `live_control.json`, or write an operator risk envelope.
- `AuthorizedNormalTradeIntent` is the only accepted live authorization type. Booleans, dictionaries, `TradeIntent`, paper authorizations, and reconstructed payloads reject before a request method is reached.
- An intent is owned by `portfolio_executive`, has a maximum 15-minute lifetime, binds exactly one logical order and exact client-order ID, and is single-use except for an idempotent read-only retry lookup.
- The future activation receipt, not the intent alone, is what permits `live_enabled=true`; activation remains under `promotion_state_lock` with a canonical preimage and current evidence revalidation.
- The existing broker, live gate, live-control, reconciliation, loss-review, rate-limit, and submit-moment checks remain required; this plan adds a layer and does not replace them.
- Make one focused commit per task. Do not broaden a task's tracked file list without recording the reason in this plan before editing.

## File Structure

| Path | Responsibility |
| --- | --- |
| `tradingagents/policy/risk_envelope.py` | One authoritative capped-mode parser; rejects retired mode before callers act. |
| `tradingagents/policy/live_gate.py` | Removes retired-mode bypasses and requires capped risk for every live action. |
| `tradingagents/execution/authorized_normal_trade_intent.py` | Immutable live authorization, canonical digest, activity/usage checks, payload binding, and receipt parser. |
| `tradingagents/policy/strategy_promotion_sync.py` | Atomic `live_enabled` activation and immutable activation receipt under the existing promotion lock. |
| `tradingagents/brokers/alpaca.py` | Lowest-boundary verification and idempotent retry lookup; disables paired live mirror. |
| `tradingagents/brokers/alpaca_supervisor.py` and `cli/main.py` | Carry one validated intent unchanged; cannot manufacture approval. |
| `config/automation_roles.json` | Declares intent issuance and submission ownership without giving schedule/report utilities trading authority. |
| `tests/test_*` named below | RED/GREEN proof of each boundary and literal live-write inventory. |

---

### Task 1: Retire the contradictory uncapped risk mode

**Files:**
- Modify: `tradingagents/policy/risk_envelope.py:45-157`
- Modify: `tradingagents/policy/live_gate.py:471-704`
- Modify: `cli/main.py:469-479, 11685-11710`
- Modify: `tests/test_live_gate.py`, `tests/test_alpaca_cli.py`
- Modify: `docs/policy/live-budget-mode.md`, `config/risk_envelope.example.yaml`

**Interfaces:**
- Produces: `load_risk_envelope()` accepts only `fixed_tranche` and `autonomous_with_caps`.
- Produces: every live action applies account and per-name caps regardless of old configuration text.

- [ ] **Step 1: Write failing retired-mode tests**

```python
def test_risk_loader_rejects_retired_uncapped_mode(tmp_path):
    path = _write_envelope(tmp_path / "risk.yaml", live_budget_mode="autonomous_uncapped")
    envelope, issues = load_risk_envelope(path)
    assert envelope is None
    assert issues == ["live_budget_mode must be one of: autonomous_with_caps, fixed_tranche"]

def test_live_gate_never_treats_uncapped_as_live_budget(tmp_path):
    result = evaluate_go_live_guard([_tiny_live_buy()], risk_envelope_path=_uncapped_envelope(tmp_path))
    assert result.allowed is False
    assert any("live_budget_mode" in issue.reason for issue in result.issues)
```

- [ ] **Step 2: Run the RED tests**

Run: `uv run --no-sync pytest tests/test_live_gate.py tests/test_alpaca_cli.py -q -k 'uncapped or live_budget_mode'`

Expected: failure because the loader currently accepts `autonomous_uncapped` and callers report it as a live budget.

- [ ] **Step 3: Implement one capped-mode allowlist**

```python
_LIVE_BUDGET_MODES = {"fixed_tranche", "autonomous_with_caps"}

if envelope.live_budget_mode not in {"fixed_tranche", "autonomous_with_caps"}:
    issues.append(OrderIssue(symbol, "live_budget_mode is not capped"))
```

Delete retired-mode branches that skip `_risk_cap_issues()` or account exposure checks. Preserve existing `fixed_tranche` and `autonomous_with_caps` semantics.

- [ ] **Step 4: Update all current command/report branches**

Replace explicit `autonomous_uncapped` output branches with a fail-closed `invalid_or_retired` result. Preserve historical-document wording only when clearly labeled historical; active docs and the example must list only the two valid modes.

- [ ] **Step 5: Verify the risk slice**

Run:

```bash
uv run --no-sync pytest tests/test_live_gate.py tests/test_alpaca_cli.py -q
uv run --no-sync ruff check tradingagents/policy/risk_envelope.py tradingagents/policy/live_gate.py cli/main.py tests/test_live_gate.py tests/test_alpaca_cli.py
git diff --check
```

Expected: all selected tests and lint pass; `rg` finds no active-code acceptance of `autonomous_uncapped`.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/policy/risk_envelope.py tradingagents/policy/live_gate.py cli/main.py tests/test_live_gate.py tests/test_alpaca_cli.py docs/policy/live-budget-mode.md config/risk_envelope.example.yaml
git commit -m "fix: retire uncapped autonomous risk mode"
```

### Task 2: Define the immutable normal-live intent

**Files:**
- Create: `tradingagents/execution/authorized_normal_trade_intent.py`
- Create: `tests/test_authorized_normal_trade_intent.py`
- Modify: `tradingagents/execution/__init__.py` only if that package exposes public execution types.

**Interfaces:**
- Produces: `AuthorizedNormalTradeIntent.from_dict(payload) -> AuthorizedNormalTradeIntent`.
- Produces: `intent.to_dict() -> dict[str, object]`, `intent.canonical_json_bytes() -> bytes`, and `intent.is_active(at=...) -> bool`.
- Produces: `intent.verify_order_payload(order, at=...) -> None`, which raises `ValueError` before any broker call.

- [ ] **Step 1: Write failing construction and forgery tests**

```python
def test_normal_live_intent_binds_one_exact_payload_and_id():
    intent = _make_intent()
    intent.verify_order_payload(_bound_order(intent), at=_at("2026-07-28T12:00:01Z"))
    assert intent.owner_role == "portfolio_executive"

@pytest.mark.parametrize("mutator", [_wrong_owner, _wrong_digest, _wrong_notional, _wrong_client_id])
def test_normal_live_intent_rejects_forged_or_changed_binding(mutator):
    with pytest.raises(ValueError):
        AuthorizedNormalTradeIntent.from_dict(mutator(_make_intent().to_dict()))
```

- [ ] **Step 2: Run the RED tests**

Run: `uv run --no-sync pytest tests/test_authorized_normal_trade_intent.py -q`

Expected: collection failure until the module exists.

- [ ] **Step 3: Implement the strict value object**

Define an immutable dataclass modeled on `AuthorizedPaperOrderRequest`, but do not inherit it. Require exact schema fields for:

```python
promotion_proposal_id: str
promotion_proposal_sha256: str
promotion_state_sha256: str
promotion_sync_receipt_id: str
promotion_sync_receipt_sha256: str
staged_intent_id: str
staged_intent_sha256: str
shadow_attestation_sha256: str
genome_id: str
genome_canonical_sha256: str
evaluation_code_commit: str
evaluation_runtime_sha256: str
market_observation_sha256: str
portfolio_snapshot_sha256: str
risk_snapshot_sha256: str
symbol: str
side: str
order_type: str
tif: str
notional_usd: str
limit_price: str
logical_order_sha256: str
client_order_id: str
effective_at: str
expires_at: str
recorded_at: str
```

Fix `owner_role="portfolio_executive"`, `authorization_scope="single_alpaca_live_order"`, `live_submit_authorized=True`, and `paper_submit_authorized=False`. Derive `authorization_id` and `client_order_id` from canonical material; enforce `recorded_at <= at < expires_at` and a 900-second maximum lifetime.

- [ ] **Step 4: Add payload, type, and expiry coverage**

Add tests for mappings, booleans, generic `TradeIntent`, paper authorization, changed symbol/side/type/TIF/notional/price, future-effective, expiry boundary, reused logical digest, and noncanonical decimals. Each must reject locally.

- [ ] **Step 5: Verify and commit**

```bash
uv run --no-sync pytest tests/test_authorized_normal_trade_intent.py -q
uv run --no-sync ruff check tradingagents/execution/authorized_normal_trade_intent.py tests/test_authorized_normal_trade_intent.py
git add tradingagents/execution/authorized_normal_trade_intent.py tests/test_authorized_normal_trade_intent.py
git commit -m "feat: define immutable normal live intent"
```

### Task 3: Add atomic live-sleeve activation and consumption evidence

**Files:**
- Modify: `tradingagents/policy/strategy_promotion_sync.py`
- Modify: `tradingagents/strategy/_immutable_evidence_store.py`
- Modify: `tradingagents/orchestration/self_heal.py`
- Modify: `tests/test_strategy_promotion_sync.py`, `tests/test_self_heal_recovery.py`, `tests/test_authorized_normal_trade_intent.py`

**Interfaces:**
- Consumes: one current `AuthorizedNormalTradeIntent`, Task 6D proposal/receipt, capped risk snapshot, clean runtime commit, and canonical state preimage.
- Produces: `activate_normal_live_intent(...) -> NormalLiveActivationReceipt` and a `live_enabled=true` sleeve only for that bound intent.
- Produces: immutable consumed-order evidence; a second activation or a changed preimage fails closed.

- [ ] **Step 1: Write RED activation tests**

```python
def test_activation_requires_exact_current_intent_and_state_preimage(tmp_path):
    with pytest.raises(ValueError, match="promotion state preimage"):
        activate_normal_live_intent(_proposal(), _intent(), state_path=tmp_path / "state.json")

def test_activation_never_promotes_an_expired_or_uncapped_intent(tmp_path):
    with pytest.raises(ValueError, match="active capped intent"):
        activate_normal_live_intent(_proposal(), _expired_or_uncapped_intent(), state_path=tmp_path / "state.json")
```

- [ ] **Step 2: Run the RED tests**

Run: `uv run --no-sync pytest tests/test_strategy_promotion_sync.py tests/test_authorized_normal_trade_intent.py -q -k 'activation or normal_live'`

Expected: failure because 6D state remains ineligible for live enablement.

- [ ] **Step 3: Implement a separate atomic activation transaction**

Under `promotion_state_lock`, rebuild and verify all Task 6D evidence, re-read the capped risk envelope and runtime ancestry, verify the intent's complete digest chain and payload, compare the canonical preimage, then atomically replace state and append an immutable receipt. The receipt must include the intent full digest, state pre/post digests, risk/runtime digests, exact transition tuple, and `live_enabled=true` only for the one sleeve. Never reuse the 6D eligibility receipt as activation permission.

- [ ] **Step 4: Implement one-use semantics and recovery**

Before any live POST, record a durable `prepared` consumption record. A duplicate caller with the same logical digest must return a read-only-retry state, not a second activation; a different payload using the same digest must reject. Crash-after-prepare and crash-after-replace tests must repair receipt/pointer state without widening the authorization.

- [ ] **Step 5: Verify and commit**

```bash
uv run --no-sync pytest tests/test_strategy_promotion_sync.py tests/test_self_heal_recovery.py tests/test_authorized_normal_trade_intent.py -q
uv run --no-sync ruff check tradingagents/policy/strategy_promotion_sync.py tradingagents/strategy/_immutable_evidence_store.py tradingagents/orchestration/self_heal.py tests/test_strategy_promotion_sync.py tests/test_self_heal_recovery.py tests/test_authorized_normal_trade_intent.py
git diff --check
```

Commit: `feat: activate verified normal live intent atomically`

### Task 4: Enforce the intent at the lowest live broker-write boundary

**Files:**
- Modify: `tradingagents/brokers/alpaca.py:677-809`
- Modify: `tests/test_alpaca_execution.py`, `tests/test_execution_safety.py`, `tests/test_authorized_normal_trade_intent.py`

**Interfaces:**
- Changes: `AlpacaRestClient.submit_order(order, *, authorized_normal_trade_intent=None, activation_receipt=None, now=None)`.
- Rule: `self.settings.paper is True` preserves existing bounded paper behavior; `paper is False` accepts only the two exact typed objects.

- [ ] **Step 1: Write RED no-network tests**

```python
def test_live_client_rejects_mapping_without_intent_before_request(fake_live_client):
    with pytest.raises(ValueError, match="AuthorizedNormalTradeIntent"):
        fake_live_client.submit_order(_order())
    assert fake_live_client.session.requests == []

def test_live_retry_looks_up_client_id_instead_of_posting_again(fake_live_client):
    fake_live_client.session.add_existing_order(_intent().client_order_id)
    response = fake_live_client.submit_order(_bound_order(), authorized_normal_trade_intent=_intent(), activation_receipt=_receipt())
    assert response["client_order_id"] == _intent().client_order_id
    assert fake_live_client.session.post_calls == 0
```

- [ ] **Step 2: Run the RED tests**

Run: `uv run --no-sync pytest tests/test_alpaca_execution.py tests/test_execution_safety.py -q -k 'normal_trade_intent or live_retry'`

Expected: failure because the current wrapper immediately POSTs a mapping.

- [ ] **Step 3: Implement boundary validation and idempotent lookup**

For a real client, assert live mode, strict types, intent activity, receipt linkage, payload equality, currentness, one-use record, and client order ID before using `_request`. Lookup `GET /v2/orders:by_client_order_id` first only for a prepared/retry record; return it only if immutable order facts match the intent. A missing lookup result permits one POST; a mismatch or ambiguous broker response fails closed and writes no second POST.

- [ ] **Step 4: Hard-disable paired live mirror**

Replace `live_guard_approved` with a deterministic failure for any nonempty `pairs` call. Do not submit its paper leg first. Keep `execute_paper_orders` unchanged and paper-only.

- [ ] **Step 5: Verify and commit**

```bash
uv run --no-sync pytest tests/test_alpaca_execution.py tests/test_execution_safety.py tests/test_authorized_normal_trade_intent.py -q
uv run --no-sync ruff check tradingagents/brokers/alpaca.py tests/test_alpaca_execution.py tests/test_execution_safety.py tests/test_authorized_normal_trade_intent.py
git add tradingagents/brokers/alpaca.py tests/test_alpaca_execution.py tests/test_execution_safety.py tests/test_authorized_normal_trade_intent.py
git commit -m "fix: require normal intent for live broker writes"
```

### Task 5: Make supervisor, CLI, and role registry pass-through only

**Files:**
- Modify: `tradingagents/brokers/alpaca_supervisor.py`
- Modify: `cli/main.py`
- Modify: `config/automation_roles.json`
- Modify: `tests/test_alpaca_supervisor.py`, `tests/test_alpaca_cli.py`, `tests/test_live_gate.py`, `tests/test_authority_role_alignment.py`

**Interfaces:**
- Consumes: the exact intent and activation receipt emitted by Task 3.
- Produces: a no-submit error when a live supervisor or manual CLI path lacks the pair; no caller rebuilds one from action fields.

- [ ] **Step 1: Write RED byte-identity tests**

```python
def test_hourly_supervisor_forwards_the_identical_intent_to_live_client(mocker):
    intent = _intent()
    submit = mocker.patch.object(_live_client(), "submit_order")
    _run_supervisor(intent=intent, activation_receipt=_receipt())
    assert submit.call_args.kwargs["authorized_normal_trade_intent"] is intent

def test_manual_live_submit_refuses_to_construct_an_intent_from_flags(cli_runner):
    result = cli_runner.invoke(app, ["alpaca", "submit", "--live", "AAPL"])
    assert result.exit_code != 0
    assert "authorized normal live intent" in result.output.lower()
```

- [ ] **Step 2: Run the RED tests**

Run: `uv run --no-sync pytest tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py tests/test_live_gate.py tests/test_authority_role_alignment.py -q -k 'normal_intent or live_submit'`

- [ ] **Step 3: Implement pass-through and fixed refusals**

Thread the exact object through the hourly path after all existing gates. The manual live mirror CLI becomes an explicit no-submit command that explains it requires an independently issued intent; it never creates a live client. Add `portfolio_executive` issuance and `execution_operator` submission roles to the registry, while schedule/report roles remain utility-only.

- [ ] **Step 4: Add live-write inventory acceptance test**

Create a literal/AST test that inventories every production `submit_order`, `.submit_order`, `execute_order_pairs`, `_alpaca_live_client`, and `paper=False` occurrence. The test must classify each result as paper-only, hard-disabled, or exact-intent boundary; a newly discovered unclassified live caller fails the test.

- [ ] **Step 5: Verify and commit**

```bash
uv run --no-sync pytest tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py tests/test_live_gate.py tests/test_execution_safety.py tests/test_authority_role_alignment.py -q
uv run --no-sync ruff check tradingagents/brokers/alpaca_supervisor.py cli/main.py tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py tests/test_live_gate.py tests/test_execution_safety.py tests/test_authority_role_alignment.py
git diff --check
```

Commit: `fix: route live submission through verified intent`

### Task 6: Independent review and whole-system proof

**Files:**
- Modify: `docs/superpowers/plans/2026-07-28-capped-live-intent-boundary.md` to record actual commits and evidence.
- Create: `.superpowers/sdd/strategy-task-6e-normal-live-intent-report.md` outside the repository only if the established SDD reporting convention remains in use.

- [ ] **Step 1: Re-index and re-run the exact caller inventory**

Run graph discovery for `AlpacaRestClient.submit_order` inbound callers, then run the literal inventory test from Task 5. Reconcile differences in the report before review.

- [ ] **Step 2: Run focused and preservation suites serially**

```bash
uv run --no-sync pytest tests/test_authorized_normal_trade_intent.py tests/test_strategy_promotion_sync.py tests/test_alpaca_execution.py tests/test_execution_safety.py tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py tests/test_live_gate.py tests/test_authority_role_alignment.py -q
```

- [ ] **Step 3: Run two independent source reviews**

First review authority/specification: intent cannot widen risk, bypass control, or create itself from CLI/supervisor input. Second review durability: activation/consumption is one-use, crash-safe, retry-safe, and cannot POST twice. Both reviewers inspect the exact final commit and run no concurrent test process.

- [ ] **Step 4: Run full verification serially**

```bash
uv run --no-sync pytest -q
uv run --no-sync ruff check tradingagents/execution/authorized_normal_trade_intent.py tradingagents/policy/risk_envelope.py tradingagents/policy/live_gate.py tradingagents/policy/strategy_promotion_sync.py tradingagents/brokers/alpaca.py tradingagents/brokers/alpaca_supervisor.py cli/main.py
uv run --no-sync python -m compileall -q tradingagents/execution/authorized_normal_trade_intent.py tradingagents/policy/risk_envelope.py tradingagents/policy/live_gate.py tradingagents/policy/strategy_promotion_sync.py tradingagents/brokers/alpaca.py tradingagents/brokers/alpaca_supervisor.py cli/main.py
git diff --check
git status --short
```

- [ ] **Step 5: Record the boundary honestly**

Record commits, test counts, source-review outcomes, and the current frozen live-control state. The result proves enforcement code only. It does **not** authorize broker reconciliation, re-arm, order submission, or claim profitability.

## Self-Review

- Spec coverage: Task 1 resolves the risk contradiction that explicitly blocks 6E. Tasks 2–3 cover durable, capped, short-lived, single-order authorization and atomic live enablement. Tasks 4–5 cover every known broker, supervisor, CLI, and legacy paired path. Task 6 requires full evidence and independent reviews.
- Placeholder scan: each task names exact files, interfaces, RED tests, commands, and expected behavior; no generic error-handling placeholder remains.
- Type consistency: the only live type is `AuthorizedNormalTradeIntent`; Task 3 adds its matching activation receipt; Tasks 4–5 require those exact names and never accept a boolean or mapping substitute.

## Execution Boundary

Implementation begins with Task 1 only. It remains fully fail-closed until every task, review, broker reconciliation, Central-Time observer schedule, shadow/paper proof, and five-market-day observation gate is independently complete.
