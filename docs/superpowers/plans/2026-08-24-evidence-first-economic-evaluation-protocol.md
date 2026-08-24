# Evidence-First Economic Evaluation Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a strict, deterministic, authority-free protocol that makes one market decision opportunity the primary evaluation unit and freezes point-in-time inputs, control arms, dependence disclosures, search budgets, and sealed cohorts before any experiment runs.

**Architecture:** Create one pure module under `tradingagents/evals` with three frozen value objects: `DecisionEvent`, `BitemporalInputManifest`, and `FrozenEvaluationProtocol`. Reuse the existing `StrategyEvaluationPolicy` only as a canonical cost/horizon input; do not modify the evaluator, replay engine, immutable store, genome families, CLI, runtime, or authority paths in this increment.

**Tech Stack:** Python 3.11+, frozen dataclasses, `hashlib`, canonical JSON, `datetime`, Pytest, Ruff

**Spec:** `docs/superpowers/specs/2026-08-24-evidence-first-economic-evaluation-protocol.md`

## Global Constraints

- Work only in `/Users/corbinfloyd/.codex/worktrees/tradingagents-economic-evaluation-protocol-20260824` on branch `codex/economic-evaluation-protocol-20260824` from `58d5337a898d64984b37b5b43866bd99001ea2a6`.
- Before every write or Ox fix round, require a clean expected Git state, no other writer in this worktree, frozen live-control SHA-256 `a3fc5ddb2b300596833c48c1554fad088ecb43d46bd70aeeac074531d6e9fb07`, and all ten `tradingagents-*` automation TOMLs `PAUSED`.
- Use exactly one implementation writer through OpenCode `build`, model `opencode/x-preview-f-free`, variant `max`, without `--auto`. Reuse that writer session for fixes.
- Terra/Luna or OpenCode helpers are read-only investigators or reviewers; they must not edit this worktree.
- Set `TA_LIVE_SUBMIT=0` for verification.
- Do not activate, install, rearm, schedule, trial, publish, fetch vendors, call models, deliver an outbox, read/write a broker, submit/cancel an order, or alter live/paper/promotion authority.
- Do not touch `README.md`, ignored runtime evidence, the current Agent Intelligence Ledger, or generated summaries.
- Do not add a database, ledger, CLI command, store kind, strategy family, evaluator, dependency, network client, or background process.
- All tests use synthetic in-memory fixtures and temporary directories only.
- The complete increment ends in one scoped commit: `feat(evals): freeze economic evaluation protocol`.

## File map

- Create `tradingagents/evals/economic_evaluation_protocol.py`: strict schemas, canonical IDs, frozen objects, and pure builders/validators.
- Create `tests/test_economic_evaluation_protocol.py`: RED/GREEN contract, tamper, bitemporal, cohort, dependence, and import-isolation coverage.
- Modify `docs/superpowers/plans/2026-08-24-evidence-first-economic-evaluation-protocol.md`: checkboxes and implementation/review record only after GREEN.
- Do not modify `tradingagents/evals/replay_ablation.py`, `tradingagents/strategy/promotion_evidence.py`, `tradingagents/strategy/_immutable_evidence_store.py`, `tradingagents/strategy/genome.py`, `cli/main.py`, or any runtime/authority module.

## Public interfaces

The new module must set `__all__` to exactly these public names:

- `EconomicEvaluationProtocolError`;
- `DecisionEvent`;
- `BitemporalInputManifest`;
- `EvaluationSearchBudget`;
- `FrozenEvaluationProtocol`;
- `canonical_universe_id`;
- `build_decision_event`;
- `validate_decision_event`;
- `build_bitemporal_input_manifest`;
- `validate_bitemporal_input_manifest`;
- `build_frozen_evaluation_protocol`;
- `validate_frozen_evaluation_protocol`.

`DecisionEvent` is a frozen, slotted dataclass with the fields
`decision_event_id`, `universe_id`, `symbol`, `decision_at`, `market_date`,
`horizon_sessions`, `horizon`, `benchmark`, `created_at`,
`resolution_window`, `observation_start`, `observation_end`, `available_at`,
`recorded_at`, `source_packet_id`, `source_artifact_id`,
`source_artifact_sha256`, `packet_event_cluster_id`, and
`market_event_cluster_id`. Store `resolution_window` as a recursively frozen
JSON snapshot: mappings become `MappingProxyType`, arrays become tuples, and
only exact JSON scalars are retained. `to_dict()` recursively thaws it into new
plain mappings/lists, never caller-owned containers.

`BitemporalInputManifest` is a frozen, slotted dataclass with the fields
`manifest_id`, `manifest_sha256`, `dataset_id`, `as_of_cutoff`, `captured_at`,
`events: tuple[DecisionEvent, ...]`, and `ordered_event_payload_sha256`.

`EvaluationSearchBudget` is a frozen, slotted dataclass with the exact integer
fields `max_candidates_per_arm`, `max_parameterizations_per_family`, and
`max_total_evaluations`.

`FrozenEvaluationProtocol` is a frozen, slotted dataclass with the fields
`protocol_id`, the complete `input_manifest`, `input_manifest_id`,
`input_manifest_sha256`, the three ordered universe tuples and their digests,
an immutable `MappingProxyType` snapshot of the evaluation policy and its
digest, `search_budget`, and the three ordered partition-ID tuples. The full
nested manifest is required so standalone validation can re-prove cohort
membership and partition exhaustiveness without reading another file.

Each value object implements `to_dict() -> dict[str, object]` and
`canonical_json_bytes() -> bytes`. The six build/validate call signatures are
spelled out in the task that implements each interface, including every
keyword argument and return type.

Every serialized public object must include its exact schema string and the
three fixed authority fields from the spec. Validators return a new frozen
object after a canonical round trip; they never return or retain caller-owned
mutable mappings.

---

### Task 1: Canonical arm-neutral decision events

**Files:**
- Create: `tradingagents/evals/economic_evaluation_protocol.py`
- Create: `tests/test_economic_evaluation_protocol.py`

**Interfaces:**
- Consumes: canonical UTC timestamps and explicit point-in-time source identities.
- Produces: `DecisionEvent`, `build_decision_event`, and `validate_decision_event` for Tasks 2 and 3.

- [x] **Step 1: Write the focused RED tests**

Start `tests/test_economic_evaluation_protocol.py` with helpers and exact
acceptance cases:

```python
from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from tradingagents.evals.economic_evaluation_protocol import (
    EconomicEvaluationProtocolError,
    build_decision_event,
    canonical_universe_id,
    validate_decision_event,
)


def _event(**overrides: object):
    values: dict[str, object] = {
        "universe_id": canonical_universe_id(tuple(f"T{i:03d}" for i in range(75))),
        "symbol": "AAPL",
        "decision_at": "2026-01-09T20:55:00+00:00",
        "market_date": "2026-01-09",
        "horizon_sessions": 5,
        "horizon": "5_sessions",
        "benchmark": "SPY",
        "created_at": "2026-01-09T20:45:00+00:00",
        "resolution_window": {
            "start_at": "2026-01-09T20:55:00+00:00",
            "horizon": "5_sessions",
        },
        "observation_start": "2025-12-29T14:30:00+00:00",
        "observation_end": "2026-01-09T20:50:00+00:00",
        "available_at": "2026-01-09T20:50:00+00:00",
        "recorded_at": "2026-01-09T20:52:00+00:00",
        "source_packet_id": "packet-20260109-aapl",
        "source_artifact_id": "artifact-20260109-aapl",
        "source_artifact_sha256": hashlib.sha256(b"aapl-fixture").hexdigest(),
    }
    values.update(overrides)
    return build_decision_event(**values)


def test_decision_event_is_stable_and_arm_neutral():
    first = _event()
    second = validate_decision_event(dict(reversed(list(first.to_dict().items()))))
    assert second == first
    assert first.decision_event_id.startswith("decision-event-")
    assert "arm" not in first.to_dict()
    assert "outcome" not in first.to_dict()
    assert json.loads(first.canonical_json_bytes()) == first.to_dict()
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.symbol = "MSFT"  # type: ignore[misc]
```

Add parameterized tests that mutate one field at a time and require
`EconomicEvaluationProtocolError` for:

- a missing or extra field;
- uppercase/non-64-hex digests;
- a naïve, `Z`-suffixed, non-UTC, or fractional-second timestamp;
- `bool` for `horizon_sessions`;
- zero or negative horizon;
- lowercase, empty, or regex-invalid symbols and benchmarks;
- `market_date` different from the UTC date in `decision_at`;
- `observation_start > observation_end`;
- `observation_end > available_at`;
- `available_at > decision_at`;
- `recorded_at < available_at`;
- caller-supplied ID or cluster digest inconsistent with canonical material.

Add one test proving a source-packet change alters the packet cluster while the
arm-neutral `decision_event_id` stays fixed. Add a separate test proving a
source-artifact digest change alters the event bytes but not the decision or
dependence identities. Finally, prove a market-date, horizon, or benchmark
change alters the market cluster and decision ID.

Add a recursive-aliasing test that constructs an event from a window containing
a nested dict and list, captures the event bytes and cluster ID, mutates every
caller-owned nested container, and proves the stored event bytes, `to_dict()`
value, and cluster ID are unchanged. Mutating a dict/list returned by
`to_dict()` must likewise leave the event unchanged.

- [x] **Step 2: Run RED and capture the expected failure**

Run:

```zsh
TA_LIVE_SUBMIT=0 .venv/bin/python -m pytest -q \
  tests/test_economic_evaluation_protocol.py
```

Expected: collection fails with
`ModuleNotFoundError: No module named 'tradingagents.evals.economic_evaluation_protocol'`.

- [x] **Step 3: Implement canonical primitives and the event contract**

In `tradingagents/evals/economic_evaluation_protocol.py`:

```python
DECISION_EVENT_SCHEMA = "decision_event/v1"
AUTHORITY_FIELDS = {
    "analysis_only": True,
    "execution_authority": "none",
    "can_submit_orders": False,
}


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()
```

Implement exact-type helpers for strings, lower SHA-256, positive integers,
ISO dates, and canonical UTC seconds. Reject `bool` anywhere an integer is
required. Normalize symbols/benchmarks by requiring their already-normalized
uppercase form; do not silently rewrite caller data.

Implement `_freeze_json(value)` and `_thaw_json(value)` as inverse recursive
helpers. `_freeze_json` accepts only `None`, exact `bool`, exact `int`, finite
`float`, `str`, mappings with exact string keys, and list/tuple arrays; it
rejects duplicate/nonstring keys, nonfinite numbers, bytes, sets, and custom
containers. It returns mapping proxies, tuples, and scalars. `_thaw_json`
returns newly allocated plain dict/list trees for serialization and for calls
into the reconciliation key functions. Prove
`_canonical_json_bytes(_thaw_json(_freeze_json(value)))` is the captured
canonical round trip before storing the snapshot.

`canonical_universe_id` requires an exact nonempty tuple of unique,
lexicographically ordered normalized symbols and returns `universe-` plus the
SHA-256 of the canonical JSON symbol list. It rejects lists, sets, reordered
tuples, duplicates, and invalid symbols.

Implement these exact signatures:

```text
canonical_universe_id(symbols: tuple[str, ...]) -> str
build_decision_event(*, universe_id: str, symbol: str, decision_at: str,
    market_date: str, horizon_sessions: int, horizon: str, benchmark: str,
    created_at: str, resolution_window: Mapping[str, object],
    observation_start: str, observation_end: str,
    available_at: str, recorded_at: str, source_packet_id: str,
    source_artifact_id: str, source_artifact_sha256: str) -> DecisionEvent
validate_decision_event(value: object) -> DecisionEvent
```

Derive the arm-neutral identity from this exact material:

```python
decision_material = {
    "schema_version": DECISION_EVENT_SCHEMA,
    "universe_id": universe_id,
    "symbol": symbol,
    "decision_at": decision_at,
    "market_date": market_date,
    "horizon_sessions": horizon_sessions,
    "benchmark": benchmark,
}
```

Require `horizon == f"{horizon_sessions}_sessions"`, require `created_at <=
decision_at`, and require `market_date == created_at[:10]`. Call the existing pure
`packet_event_key()` and `market_event_key()` functions with a mapping whose
field names exactly match the reconciliation row contract. Reject `None` from
either function. Hash their returned tuples and prefix the hashes with
`packet-event-cluster-` and `market-event-cluster-`. Prefix the arm-neutral
identity with `decision-event-`. Make `validate_decision_event` enforce an
exact field set, rebuild through `build_decision_event`, and compare every
serialized byte.

- [x] **Step 4: Run GREEN for Task 1**

Run the focused file. Expected: all Task 1 tests pass.

---

### Task 2: Bitemporal input manifest

**Files:**
- Modify: `tradingagents/evals/economic_evaluation_protocol.py`
- Modify: `tests/test_economic_evaluation_protocol.py`

**Interfaces:**
- Consumes: exact `DecisionEvent` values from Task 1.
- Produces: `BitemporalInputManifest`, builder, and validator for Task 3.

- [x] **Step 1: Add manifest RED tests**

Add imports for the manifest API and tests equivalent to:

```python
def test_manifest_binds_canonical_event_order_and_payload_bytes():
    first = _event(symbol="AAPL")
    second = _event(
        symbol="MSFT",
        source_packet_id="packet-20260109-msft",
        source_artifact_id="artifact-20260109-msft",
        source_artifact_sha256=hashlib.sha256(b"msft-fixture").hexdigest(),
    )
    manifest = build_bitemporal_input_manifest(
        dataset_id="pit-fixture-v1",
        as_of_cutoff="2026-01-09T21:00:00+00:00",
        captured_at="2026-01-09T21:00:00+00:00",
        events=(first, second),
    )
    assert manifest.events == tuple(sorted((first, second), key=lambda row: row.decision_event_id))
    assert manifest.manifest_id.startswith("input-manifest-")
    assert validate_bitemporal_input_manifest(manifest.to_dict()) == manifest
```

Require rejection of empty events, duplicate decision IDs, unsorted serialized
events, cutoff before an event decision, capture before an event recording,
inconsistent reuse of a source-artifact ID, missing/extra fields, a changed
event body with retained IDs, and a changed ordered payload digest or manifest
digest. Prove that mapping insertion order does not change canonical bytes.

- [x] **Step 2: Run the new manifest selectors and observe RED**

Expected: import failure or missing-symbol failures for the manifest API.

- [x] **Step 3: Implement the frozen manifest**

Use schema `bitemporal_input_manifest/v1`. Sort events by
`decision_event_id`, reject duplicates before constructing the tuple, and hash
the ordered list of full event dictionaries. Compute `manifest_id` from all
payload material except `manifest_id`, `manifest_sha256`, and `recorded_at`-like
self-reference; set `manifest_sha256` to the SHA-256 of the complete serialized
payload with only `manifest_sha256` omitted. Document these two hash domains in
the module docstring and test them explicitly.

Implement these exact signatures:

```text
build_bitemporal_input_manifest(*, dataset_id: str, as_of_cutoff: str,
    captured_at: str, events: tuple[DecisionEvent, ...])
    -> BitemporalInputManifest
validate_bitemporal_input_manifest(value: object)
    -> BitemporalInputManifest
```

`validate_bitemporal_input_manifest` must parse every nested event through
`validate_decision_event`, rebuild the manifest, and require an exact canonical
byte match. Do not retain a caller list, dict, or nested event mapping.

- [x] **Step 4: Run Task 1 and Task 2 GREEN**

Run the full new test file. Expected: all event and manifest tests pass.

---

### Task 3: Frozen TA-Control protocol and sealed cohorts

**Files:**
- Modify: `tradingagents/evals/economic_evaluation_protocol.py`
- Modify: `tests/test_economic_evaluation_protocol.py`

**Interfaces:**
- Consumes: `BitemporalInputManifest` and exact
  `tradingagents.strategy.evaluator.StrategyEvaluationPolicy`.
- Produces: `EvaluationSearchBudget`, `FrozenEvaluationProtocol`, builder, and validator.

- [x] **Step 1: Add protocol RED tests**

Use deterministic synthetic universes:

```python
from tradingagents.strategy.evaluator import StrategyEvaluationPolicy


def _universe(size: int) -> tuple[str, ...]:
    return tuple(f"T{i:03d}" for i in range(size))


def _policy():
    return StrategyEvaluationPolicy(
        benchmark_symbol="SPY",
        holding_sessions=5,
        commission_bps_per_side="0",
        half_spread_bps_per_side="5",
        slippage_bps_per_side="5",
        round_trip_sides=2,
    )
```

Build at least three distinct events using primary-universe symbols `T000`,
`T001`, and `T002`, then bind them into one manifest. Require the protocol to
serialize these exact constants:

```python
CONTROL_ARM_IDS = (
    "cash",
    "spy",
    "equal_weight",
    "momentum_quality",
    "pullback_support",
)
REQUIRED_METRICS = (
    "net_return_after_costs",
    "benchmark_excess_after_costs",
    "max_drawdown",
    "turnover",
    "false_positive_rate",
    "decision_event_count",
    "packet_event_cluster_count",
    "market_event_cluster_count",
    "cost_per_useful_decision",
)
```

Assert `route_id == "ta-control/v1"`, `cadence == "weekly"`, `long_only is
True`, `cash_allowed is True`, `max_leverage == "1"`, `holdout_status ==
"sealed"`, and `dependence_method ==
"market_event_cluster_count_provisional_bound"`. Assert there is no
`effective_sample_size`, alpha claim, model, agent, vendor, broker, execution,
promotion, or order field anywhere in canonical JSON.

Add rejection tests for:

- any missing/extra/duplicate control arm;
- reordered or duplicate universes;
- primary universe not exactly 75;
- sensitivity-50 not exactly 50 or not a strict subset;
- sensitivity-100 not exactly 100 or not a strict superset;
- benchmark or horizon inconsistent with the bound evaluation policy;
- any event whose `universe_id` differs from
  `canonical_universe_id(primary_universe)`;
- zero, negative, or `bool` search budgets;
- total budget less than candidates-per-arm times arm count;
- empty, overlapping, duplicate, unsorted, nonexhaustive, or unknown partition IDs;
- a nonsealed holdout;
- a changed manifest/policy/universe digest;
- missing/extra fields or obsolete schema.

- [x] **Step 2: Run protocol selectors and observe RED**

Expected: the new protocol imports or assertions fail because the API is not
implemented yet.

- [x] **Step 3: Implement the strict protocol**

Use schema `frozen_economic_evaluation_protocol/v1`. Require the protocol
builder to receive the exact signature below:

```text
def build_frozen_evaluation_protocol(
    *,
    input_manifest: BitemporalInputManifest,
    primary_universe: tuple[str, ...],
    sensitivity_universe_50: tuple[str, ...],
    sensitivity_universe_100: tuple[str, ...],
    evaluation_policy: StrategyEvaluationPolicy,
    search_budget: EvaluationSearchBudget,
    development_event_ids: tuple[str, ...],
    validation_event_ids: tuple[str, ...],
    holdout_event_ids: tuple[str, ...],
) -> FrozenEvaluationProtocol
validate_frozen_evaluation_protocol(value: object)
    -> FrozenEvaluationProtocol
```

Snapshot and validate every tuple before hashing. Include the policy dictionary
inside an immutable `MappingProxyType` and include its SHA-256, not a live
policy object reference. Store the complete nested manifest plus its redundant
ID and hash, and cross-check all three. Derive universe digests from the ordered
exact lists. Require every event symbol to belong to the primary universe and
require partitions to equal the manifest event-ID set. Compute `protocol_id` as
`economic-evaluation-protocol-` plus the SHA-256 of all serialized protocol
material except the ID itself.

`validate_frozen_evaluation_protocol` must enforce the exact nested field sets,
validate the embedded budget types, rebuild from parsed immutable inputs, and
require exact canonical equality. It must not accept aliases for schema, arms,
metrics, route, cadence, authority, or dependence method.

- [x] **Step 4: Run the complete new test file GREEN**

Expected: all event, manifest, protocol, tamper, and partition tests pass.

---

### Task 4: Prove isolation, run the gate, review, and commit

**Files:**
- Modify: `tests/test_economic_evaluation_protocol.py`
- Modify: `docs/superpowers/plans/2026-08-24-evidence-first-economic-evaluation-protocol.md`

**Interfaces:**
- Consumes: the completed pure module from Tasks 1–3.
- Produces: accepted verification/review evidence and one scoped commit.

- [x] **Step 1: Add the import and side-effect isolation test**

Parse the new module with `ast` and fail if an import path begins with any of:

```python
FORBIDDEN_IMPORT_PREFIXES = (
    "cli",
    "tradingagents.brokers",
    "tradingagents.execution",
    "tradingagents.orchestration",
    "tradingagents.policy.live_control",
    "tradingagents.policy.promotion",
    "tradingagents.policy.promotion_execution",
    "tradingagents.strategy.mutation_registry",
    "tradingagents.strategy.promotion_evidence",
)
```

Monkeypatch `socket.socket`, `subprocess.run`, `subprocess.Popen`, `Path.write_bytes`,
`Path.write_text`, and `open` in a focused construction test so an attempted
network, subprocess, or filesystem effect fails immediately. Construct and
validate all three public objects successfully under those sentinels.

- [x] **Step 2: Run the focused and adjacent GREEN gate**

Run:

```zsh
TA_LIVE_SUBMIT=0 .venv/bin/python -m pytest -q \
  tests/test_economic_evaluation_protocol.py \
  tests/test_strategy_genome.py \
  tests/test_strategy_evaluator.py \
  tests/test_strategy_evidence_store.py \
  tests/test_strategy_promotion_evidence.py \
  tests/test_strategy_mutation_registry.py \
  tests/test_replay_ablation_plan.py \
  tests/test_agent_intelligence_reconciliation.py

.venv/bin/ruff check \
  tradingagents/evals/economic_evaluation_protocol.py \
  tests/test_economic_evaluation_protocol.py

PYTHONPYCACHEPREFIX="$(mktemp -d)" \
  .venv/bin/python -m compileall -q \
  tradingagents/evals/economic_evaluation_protocol.py

uv lock --check
git diff --check
```

Expected: all tests and static checks pass; Git lists only the new module, new
test, spec, and plan.

- [x] **Step 3: Stop the sole writer and run three fresh no-edit gates**

Run sequentially:

1. a fresh verifier for the exact commands above;
2. a fresh specification reviewer against the spec and complete diff;
3. a separate fresh quality/security reviewer focused on canonical hashing,
   bitemporal leakage, aliasing/mutability, path/import isolation, and authority.

Any unresolved P0/P1 blocks the commit. Fixes return to the original Ox writer
session. P2 findings are fixed or recorded with a concrete justification in
this plan before acceptance. Confirm each no-edit session leaves Git hashes
unchanged.

- [x] **Step 4: Update the implementation record**

Append exact RED output, GREEN counts, Ruff/compile/lock/diff results, reviewer
verdicts, changed-path hashes, safety posture, and the final commit hash to this
plan. Do not claim an economic experiment, independent sample size, route
skill, or alpha result.

- [x] **Step 5: Commit the accepted increment**

```zsh
git add \
  tradingagents/evals/economic_evaluation_protocol.py \
  tests/test_economic_evaluation_protocol.py \
  docs/superpowers/specs/2026-08-24-evidence-first-economic-evaluation-protocol.md \
  docs/superpowers/plans/2026-08-24-evidence-first-economic-evaluation-protocol.md
git commit -m "feat(evals): freeze economic evaluation protocol"
```

- [x] **Step 6: Verify committed HEAD and stop**

Rerun the new test file, Ruff, compileall, `uv lock --check`, and
`git diff --check` against committed HEAD. Require a clean feature worktree.
Reindex canonical TradingAgents only after a separately reviewed integration;
verify graph coverage for the new source/test paths and inspect the docs
directly because `docs/` is intentionally excluded from the graph.

Stop after the clean accepted feature commit. Do not run the protocol against
real data, implement the evaluator adapter, admit the protocol to the immutable
store, alter promotion/influence, start an automation/trial, or touch a broker.

## Implementation record — 2026-08-24

- RED evidence: the preserved Task 1 test file initially reported `27 failed, 15 passed` because the validator forwarded derived IDs into the source-material builder. The accepted repair yielded `42 passed`. Task 2/3 RED then failed at collection with `ImportError: cannot import name 'BitemporalInputManifest'`. The post-review regression RED reported three failures: decoded canonical JSON rejected the value-equal `execution_authority="none"`, and `dataclasses.replace()` could bypass frozen-object invariants.
- GREEN evidence: the complete protocol contract and isolation suite passed `88 passed in 0.54s` after the final repair.
- Independent affected gate: `TA_LIVE_SUBMIT=0 /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q` over the protocol, strategy/genome/evaluator/store/promotion/mutation, replay, and reconciliation files passed `656 passed in 20.02s` on the accepted uncommitted revision.
- Static gates: targeted Ruff passed; compileall with a temporary `PYTHONPYCACHEPREFIX` exited 0; `uv lock --check` passed (124 packages resolved); `git diff --check` passed.
- Review: initial independent specification and quality/security reviews found the decoded-string identity P1 and public-constructor/aliasing P1. Both were regression-tested and fixed. Follow-up specification and quality/security reviews reported no P0, P1, or P2 findings.
- Candidate source SHA-256: `tradingagents/evals/economic_evaluation_protocol.py` `78f057b0839ca5d440a59749a28e920c7a0d846b1aa7338907f2102e2fe4b127`; `tests/test_economic_evaluation_protocol.py` `3c67ff852d697369d27c83bbf26587af9a2e5f12f2b1a64590974afdca6b7182`.
- Safety posture: `results/policy/live_control.json` remains frozen at SHA-256 `a3fc5ddb2b300596833c48c1554fad088ecb43d46bd70aeeac074531d6e9fb07`; all ten TradingAgents native automations remained `PAUSED`; no broker, model, vendor, scheduler, paper-trial, or other runtime action was performed.
- Commit: `feat(evals): freeze economic evaluation protocol`; its final object ID is recorded in the receiving checkpoint and final handoff, because a commit cannot contain its own final object ID.

## Later increments, explicitly not authorized by this plan

1. Admit the accepted protocol to the existing immutable strategy evidence
   store; do not create another ledger or database.
2. Make replay/ablation scoring require an admitted protocol and exact
   decision-event cohort instead of free-form fixture rows.
3. Implement deterministic cash/SPY/equal-weight/momentum-quality evaluators
   and pair them by `decision_event_id` under the existing cost policy.
4. Add a preregistered dependence-aware estimator and block all effective-sample
   claims until it passes synthetic dependence tests.
5. Build a point-in-time data audit and sealed prospective holdout only after
   owner-reviewed vendor/source evidence exists.

None of those later increments authorizes a model call, paper campaign,
promotion, schedule, live-control change, broker action, or production run.
