# Evidence-First Economic Evaluation Protocol Specification

**Status:** Frozen design for the next source-only increment

**Canonical source baseline:** `58d5337a898d64984b37b5b43866bd99001ea2a6`

**Parent record:**
`docs/superpowers/plans/2026-07-18-agent-communication-and-strategy-learning.md`,
“Evidence-First Increment 1: Agent Ledger Reconciliation And Dependence Bounds”

## Problem

The current Agent Intelligence Ledger contains 4,944 resolved forecast rows,
but those rows collapse to 2,595 packet-event clusters and 354 conservative
market-event clusters. The raw row count therefore is not an independent
sample size and cannot support a claim of route skill or economic alpha.

TradingAgents already has useful pieces of an evaluation system:

- immutable strategy evidence;
- source- and runtime-bound preregistration;
- deterministic genome evaluation with a fixed cost policy;
- fixture-only replay and ablation scoring;
- explicit analysis-only authority fields.

What it does not have is a canonical, arm-neutral market decision identity or
a frozen protocol that binds cohorts, point-in-time input availability,
deterministic controls, dependence disclosures, search budgets, and sealed
holdout partitions before outcomes are scored.

## Decision

The next increment adds a pure, strict-schema protocol module. It freezes the
experiment before adding another evaluator, fetching data, invoking a model,
or running an experiment.

The increment will:

1. define an arm-neutral `decision_event_id` for one market decision
   opportunity;
2. bind each event to explicit point-in-time source evidence and both current
   dependence keys;
3. bind an ordered event cohort into a bitemporal input manifest;
4. freeze the deterministic TA-Control arm set, universe cohorts, cost-policy
   identity, search budgets, metrics, and development/validation/holdout
   partitions;
5. return immutable in-memory objects and canonical JSON bytes only.

The increment will not run a backtest, write a ledger, admit evidence to a
store, fetch market data, call a model or vendor, alter influence or promotion,
touch a schedule, start a trial, read or write a broker, or change live control.

## Contract boundaries

### 1. A decision event is arm-neutral

`decision_event_id` identifies the market opportunity shared by every
evaluation arm. It is the SHA-256 of canonical JSON containing exactly:

- `universe_id`, derived from the canonical ordered primary-universe bytes;
- normalized `symbol`;
- canonical UTC `decision_at`;
- `market_date`;
- positive integer `horizon_sessions`;
- normalized `benchmark`.

It deliberately excludes arm, model, agent, forecast, outcome, return, and
promotion material. A later evaluation-case identity may combine a protocol,
arm, and decision event; this increment does not define or emit that result
record.

Each event also carries:

- canonical UTC forecast `created_at`;
- an already-normalized `horizon` token consistent with `horizon_sessions`;
- an explicit JSON `resolution_window` mapping;
- `observation_start` and `observation_end`;
- `available_at`, which cannot follow `decision_at`;
- `recorded_at`, which cannot precede `available_at`;
- `source_packet_id`;
- `source_artifact_id` and its lowercase SHA-256;
- a packet-event cluster identity derived from the exact current
  reconciliation tuple `(source_packet_id, ticker, benchmark,
  canonical_json(resolution_window))`;
- a market-event cluster identity derived from the exact current
  reconciliation tuple `(ticker, created_at UTC date, normalized horizon,
  benchmark)`.

The new cluster IDs are the prefixed SHA-256 of canonical JSON for those exact
tuples. The builder must call the current pure `packet_event_key()` and
`market_event_key()` functions from
`tradingagents/evals/agent_intelligence_reconciliation.py`, reject an
unclusterable result, and hash the returned tuples. This keeps future protocol
events tied to the implemented dependence contract rather than a similar but
independent definition.

The resolution window is recursively snapshotted: mappings become immutable
mapping proxies, arrays become tuples, and only exact JSON scalar types are
accepted. Serialization recursively thaws that private snapshot into new plain
dict/list values. Mutating any caller-owned nested dict or list after event
construction cannot change the event bytes or any stored identity.

The decision ID stays stable when only arm selection or later capture time
changes. The source and cluster identities remain separately visible, so
revised evidence cannot masquerade as the same captured input.

`universe_id` is exactly `universe-` plus the SHA-256 of canonical JSON for the
ordered primary-universe symbols. The protocol recomputes this identity and
requires every nested event to carry it. An arbitrary caller label is invalid.

### 2. Bitemporal input is explicit

`BitemporalInputManifest` binds an ordered tuple of exact `DecisionEvent`
objects. It includes:

- `schema_version="bitemporal_input_manifest/v1"`;
- `manifest_id` and `manifest_sha256`;
- `dataset_id`;
- canonical UTC `as_of_cutoff` and `captured_at`;
- ordered decision-event IDs;
- ordered event payload digest;
- source-artifact IDs and hashes;
- fixed authority fields.

The manifest rejects:

- naïve or noncanonical timestamps;
- observation or availability after the event decision time;
- recording before availability;
- capture before any row was recorded;
- event decisions after the manifest cutoff;
- duplicate decision IDs;
- inconsistent duplicate source-artifact IDs;
- noncanonical event order;
- missing, extra, or malformed fields.

It contains source identities and hashes, not source contents, credentials,
endpoints, account data, or control payloads.

### 3. Evaluation controls are not strategy families

The protocol defines evaluation arms independently of
`tradingagents.strategy.genome.StrategyFamily`. This avoids making cash, SPY,
or equal weight look like executable genome families.

The exact arm IDs are:

- `cash`;
- `spy`;
- `equal_weight`;
- `momentum_quality`;
- `pullback_support`.

The protocol route is `ta-control/v1`. No arm may name or configure an agent,
model, vendor, broker, or execution surface.

### 4. Universe and cadence are frozen

The primary universe contains exactly 75 unique normalized U.S. equity
symbols. The 50-symbol sensitivity cohort must be a strict subset of the
primary universe. The 100-symbol sensitivity cohort must be a strict superset
of the primary universe. Their ordered symbol lists and SHA-256 digests are
part of the protocol.

The fixed trading assumptions are:

- weekly decision cadence;
- long-only;
- cash allowed;
- no leverage;
- benchmark `SPY`;
- no shorting, options, intraday, or social-data arm.

### 5. Costs reuse the existing strategy policy

The builder accepts an exact `StrategyEvaluationPolicy` from
`tradingagents/strategy/evaluator.py` and binds its canonical JSON and SHA-256.
It does not introduce a second commission, spread, slippage, latency, or
holding-period implementation. Economic scoring remains outside this increment.

### 6. Search and success rules are preregistered

The protocol carries exact positive integer limits for:

- `max_candidates_per_arm`;
- `max_parameterizations_per_family`;
- `max_total_evaluations`.

It binds the following required metrics in canonical order:

- `net_return_after_costs`;
- `benchmark_excess_after_costs`;
- `max_drawdown`;
- `turnover`;
- `false_positive_rate`;
- `decision_event_count`;
- `packet_event_cluster_count`;
- `market_event_cluster_count`;
- `cost_per_useful_decision`.

The provisional dependence method is named
`market_event_cluster_count_provisional_bound`. The protocol does not carry an
`effective_sample_size` or alpha/promotion claim because no preregistered
dependence-aware estimator exists yet.

### 7. Partitions are sealed and disjoint

Every admitted decision event belongs to exactly one of:

- `development`;
- `validation`;
- `holdout`.

The three event-ID tuples must be nonempty, pairwise disjoint, collectively
exhaustive for the bound manifest, and canonically ordered. The holdout status
is exactly `sealed`. No arm selection, parameter search, or success claim may
be encoded in a holdout record.

This increment proves structural separation only. A later store-admission
increment must bind when and by whom a holdout is released before any real
holdout outcomes are inspected.

### 8. Authority is permanently absent

Every public object exposes exactly:

```json
{
  "analysis_only": true,
  "execution_authority": "none",
  "can_submit_orders": false
}
```

No public function imports or calls broker, Alpaca, execution, scheduler,
automation, runtime-trial, outbox, submission, cancellation, live-control, or
promotion-mutation code.

## Existing seams to reuse

- Reuse canonical serialization and strict validation patterns from
  `tradingagents/evals/runtime_identity.py` and
  `tradingagents/evals/agent_intelligence_reconciliation.py`.
- Accept `StrategyEvaluationPolicy` from
  `tradingagents/strategy/evaluator.py` for cost and horizon identity.
- Keep `tradingagents/evals/replay_ablation.py` unchanged in this increment; a
  later adapter may require a frozen protocol rather than free-form rows.
- Keep `tradingagents/strategy/_immutable_evidence_store.py` unchanged; a later
  increment may add a new admitted kind to that existing store after the
  contract is accepted.
- Do not extend `StrategyFamily` for control arms.

## Acceptance

The increment is accepted only when focused RED/GREEN evidence proves:

- stable canonical IDs independent of mapping insertion order;
- exact schema and type rejection, including Python `bool` rejected as `int`;
- bitemporal no-future-leakage rules;
- exact universe-set relationships and exact control-arm membership;
- decision-event, packet-event, and market-event identities remain distinct;
- no raw row count is labeled an effective sample;
- sealed partitions are exhaustive and disjoint;
- policy/source/event tampering changes or invalidates the correct digest;
- import isolation from every authority or runtime surface;
- no file, network, process, schedule, trial, broker, or production side effect.

Synthetic fixtures are the only verification input. No economic conclusion is
produced by this increment.
