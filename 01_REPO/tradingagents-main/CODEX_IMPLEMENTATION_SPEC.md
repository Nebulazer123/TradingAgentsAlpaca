# Codex Implementation Spec — Court-Hardened Autonomous Trading System

**Repo:** `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main`
**Source of truth for intent:** `Court_of_Claude_Trading_Bot_Proposal_SECOND_AMENDED.pdf` (this folder)
**Companion:** `Court_of_Claude_Trading_Bot_Proposal_AMENDED.pdf`, `REPO_OVERVIEW.md`, `TRADING_METHODS_AND_AUTOMATIONS.md`

This is the build handoff. It translates each section of the hardened proposal into concrete modules, schemas, gate thresholds, and tests against the *actual* repo layout. Codex should implement in batch order; every batch ends with a passing test and a written packet. Nothing in here loosens the existing safety boundary (stocks-only, long-only, limit-only, dry-run-before-submit, fail-closed). It only adds gates on top of it.

---

## 0. First principles (do not violate)

1. **Agents propose, policy decides.** No agent output may size a position, trigger an order, or waive a gate. The deterministic policy engine consumes only *verified features*.
2. **Cash is a first-class output.** Every decision path must be able to terminate in `HOLD_CASH` with a written packet.
3. **Fail closed.** Stale data, clock skew, missing confirmation, API error, or any reconciliation mismatch → no action.
4. **Every decision writes an immutable packet** under `results/`, including "no trade", with input hashes, code/version stamps, and gate outcomes.
5. **Live path is physically separate** from research/paper. A research bug must not be able to reach the live account.

---

## 1. Module map — where each proposal section lands

| Proposal section | New / changed code | Notes |
|---|---|---|
| II. Edge thesis (sleeves) | `tradingagents/strategy/sleeves/` (new package) | One module per sleeve; deterministic trigger + feature contract. Rewrite logic currently in `paper_tournament.py`. |
| III. Benchmark bar | `tradingagents/validation/benchmark.py` (new) | Alpha + information ratio vs QQQ/SPY, beta-decomposed, after-tax/after-cost. |
| IV. Evidence pyramid / XII. Ladder | `tradingagents/policy/promotion.py` (new) | State machine; persisted per-sleeve stage. |
| V. Statistical honesty | `tradingagents/validation/walkforward.py`, `validation/stats.py` (new) | Purged k-fold + embargo, deflated Sharpe, power budget, alpha-spending, pre-registration store. |
| VI. LLM ablation gate | `tradingagents/validation/ablation.py` (new) + wrap `tradingagents/agents/` | Deterministic-only vs deterministic+LLM A/B. Claim verifier + Brier calibration store. |
| VII. Cost discipline | `tradingagents/execution/cost_model.py` (new) | Adversarial priors; one-way ratchet; capacity ceilings. |
| VIII. Regime overlay | `tradingagents/policy/regime.py` (new) | Vol-managed sizing, regime permission, bounded-lag loss. |
| IX. Portfolio truth | `tradingagents/policy/portfolio_risk.py` (new) | Cross-sleeve exposure decomposition + caps; drawdown breaker. |
| X. Operational survival | `tradingagents/brokers/alpaca.py`, `alpaca_supervisor.py` (extend) | Idempotency keys, reconcile-on-start, single-writer lock, dead-man switch. |
| XI. Failure taxonomy | enforced across the above; one test per row | See §13 test matrix. |

---

## 2. Schemas first (Batch 1)

Create `tradingagents/schemas/` with versioned Pydantic models. These are the contracts everything else depends on. All carry `schema_version`.

### 2.1 `Hypothesis` (agent output contract — advisory only)
```
hypothesis_id, symbol, sleeve_candidates[], thesis, counter_thesis,
evidence[] {type, summary, source_ref, freshness_minutes, confidence},
invalidators[], entry_trigger, exit_trigger, freshness_requirement_minutes,
data_confidence, risk_flags[]
```
Rule: every `evidence.source_ref` MUST resolve to a structured data point (filing URL+field, computed feature id, or quote timestamp). Unresolvable → claim dropped by the verifier (§7).

### 2.2 `CandidatePacket`
```
candidate_id, schema_version, symbol, as_of, universe_bucket,
eligibility {stocks_only, long_only, paper_ok, live_ok},
routing_hints[], freshness {market_data_age_s, news_data_age_s, stale_after},
event_flags {earnings_blackout, fresh_negative_news, trading_halt}
```

### 2.3 `FeaturePacket` (point-in-time, fail-closed)
Every feature carries `value, as_of, source, freshness_s, complete(bool)`. Any feature with `complete=false` or `freshness_s > sleeve_threshold` blocks the trade.

### 2.4 `TradeIntent`
```
intent_id, idempotency_key, symbol, sleeve, environment{paper|tiny_live|full_live},
side=buy, order_type=limit, limit_low, limit_high, tif=day,
size_usd, size_shares, entry_plan, exit_plan, invalidator,
size_context {regime_mult, vol_mult, confidence_mult, liquidity_mult, sleeve_stage_mult, live_cap_residual},
gate_trace[], data_integrity_ref
```
`idempotency_key = sha256(sleeve|symbol|as_of_bucket|limit_low|limit_high|size_shares|environment)`.

### 2.5 `RunPacket` (immutable audit)
```
packet_id, decision{order|hold_cash|watch}, intent_ref?, gate_trace[],
input_hashes{}, code_version, config_version, data_integrity{}, timestamp
```

**DoD Batch 1:** `tests/test_schemas.py` — round-trip + invariant tests (e.g. `live_ok=true` impossible unless promotion stage ≥ tiny-live; intent with missing idempotency_key rejected).

---

## 3. Point-in-time data layer (Batch 2)

`tradingagents/dataflows/pit/`. Goal: no look-ahead, survivorship-aware universe.

- `universe.py` — historical universe builder that **includes delisted/acquired names** with as-was membership. Free-data reality: SEC EDGAR gives clean PIT *filings*; delisted *price history* from free sources is weak → mark those names `price_history_quality=low` and **exclude from sizing**, keep for bias auditing. Emit a **bias audit packet** per backtest (universe construction, PIT compliance %, staleness rates).
- `edgar.py` — SEC EDGAR client: submissions feed, daily index, 8-K, Form 4, companyfacts/companyconcept XBRL. Respect ≤10 req/s and a descriptive User-Agent. This is the data spine of the `underreaction-event-drift` sleeve.
- `macro.py` — FRED/ALFRED vintages for point-in-time regime features (risk-on/off). Keyed, cached.
- `freshness.py` — stamps every feature; `source_conflict()` flags when two free sources disagree beyond tolerance → feature excluded from sizing.

**DoD Batch 2:** `tests/test_pit_data.py` — assert no future-dated rows enter any feature for a given `as_of`; assert delisted names present in historical universe; assert source-conflict exclusion fires.

---

## 4. Cost & capacity model (Batch 3) — *adversarial by default*

`tradingagents/execution/cost_model.py`.

```
modeled_cost(symbol, size, spread, adv) =
    full_half_spread          # pay the whole half-spread, no price improvement assumed
  + impact_coef * (size/adv)  # non-trivial participation impact
  + borrow_if_any
```
- Priors are pessimistic until live fills exist. `update_from_fills()` may only **lower** the assumed cost, and only after `min_fill_sample`. Never raises edge by assuming better fills than demonstrated.
- `capacity_ceiling(sleeve)` → max participation rate + max $ size where modeled edge is assumed to vanish. Early-live size capped well under it.

**DoD Batch 3:** `tests/test_cost_model.py` — ratchet is one-way; a sleeve that passes only under optimistic costs fails under priors.

---

## 5. Walk-forward + statistical gates (Batch 4)

`tradingagents/validation/walkforward.py` + `validation/stats.py` + `validation/registry.py`.

- **Pre-registration store** (`registry.py`): freeze `{hypothesis, entry/exit rules, target_metric, benchmark, min_sample, power_target}` with a hash before any test. Changing any field starts a new registration id (restarts the clock). Persist under `results/preregistration/`.
- **Walk-forward**: purged k-fold with embargo so train/test cannot leak.
- **Deflated Sharpe Ratio**: adjust for number of variants tried (`stats.deflated_sharpe`).
- **Power budget**: `stats.required_n(effect_size, power=0.8, alpha)` → minimum independent trades; record expected calendar time to reach it given sleeve bet-rate. Shelve sleeves whose power is unreachable before a plausible decay horizon.
- **Sequential testing**: alpha-spending schedule (`stats.alpha_spend`) so a sleeve can be confirmed/killed early without inflating false positives.
- **Family-wise budget** (`stats.family_budget`): caps FDR across *all* sleeves/variants ever tested; evaluations on a fixed cadence, logged.

Gate thresholds live in config (`tradingagents/validation/thresholds.py`), not in code branches, so they are auditable and frozen per registration. Suggested starting values (tune, don't treat as gospel): `DSR_min=0.0 at 95%`, `power=0.80`, `family_alpha=0.10`, `embargo=5d`, `min_independent_trades` per sleeve from power calc.

**DoD Batch 4:** `tests/test_walkforward.py` — leakage test (shuffled-label edge must vanish), DSR penalizes added variants, pre-reg change creates new id.

---

## 6. Strategy sleeves (Batch 5a)

`tradingagents/strategy/sleeves/` — one module each, all deterministic given features:
`pullback_support.py`, `breakout_continuation.py`, `catalyst_continuation.py`, `underreaction_event_drift.py`, plus `cash_default` as policy fallback.

Each sleeve exposes: `required_features`, `trigger(features) -> bool`, `score(features) -> float`, `entry_plan`, `exit_plan`, `invalidators`. Use the `pullback-support` "good dip vs falling knife" decision table from `3deep-research-report.md` as the reference implementation (trend context, support proximity, pullback depth in ATR, volume behavior, sector confirmation, regime, earnings/news blackout). Score setup quality, not raw PnL.

**DoD Batch 5a:** `tests/test_sleeves.py` — golden cases: a clean pullback passes, a falling knife (below falling 200D, gap stays open, fresh negative filing) is blocked.

---

## 7. LLM ablation + verification (Batch 5b)

`tradingagents/validation/ablation.py`, `tradingagents/agents/verifier.py`, `tradingagents/agents/calibration.py`.

- **Claim verifier**: re-checks each `Hypothesis.evidence.source_ref` against its source; drops+logs unverifiable/contradicted claims.
- **Calibration store**: Brier-score each agent's directional forecasts over time; persistently miscalibrated agents auto-muted.
- **Ablation harness**: for each sleeve, run walk-forward **twice** — deterministic features only vs deterministic + LLM hypothesis layer. The LLM layer is allowed into the live path **only** where it shows statistically significant incremental alpha (same DSR/benchmark bar). Otherwise `llm_enabled[sleeve]=false`.
- **Disagreement flag**: material model disagreement → intent demoted to `watch`.
- Sizing never reads model confidence (enforced by a lint test that greps the sizing function for any agent-confidence import).

**DoD Batch 5b:** `tests/test_ablation.py` — a sleeve where LLM adds noise gets the layer muted; verifier drops an unsourced claim; miscalibrated agent muted.

---

## 8. Live-shadow channel (Batch 6)

`tradingagents/execution/shadow.py`. Live-eligible intents are stamped against live quotes and **never filled**; record modeled fill vs achievable fill, queue position, and fill-rate. Compare over `min_sample`. Feeds the adverse-selection kill condition.

**DoD Batch 6:** `tests/test_shadow.py` — shadow never submits; fill-rate divergence beyond threshold flips the sleeve to `paused`.

---

## 9. Deterministic policy engine (Batch 7)

`tradingagents/policy/engine.py`. The single chokepoint. Binary conversion rule (from `3deep`):

```
if candidate passes universe checks
 and feature_completeness >= min
 and sleeve trigger satisfied
 and sleeve score >= threshold
 and score margin >= uncertainty band
 and no stale/missing/blocking data
 and promotion stage allows this environment
 and benchmark + friction + ablation gates passed for this sleeve
 and portfolio caps allow size > 0 (regime + concentration)
 and dry_run passes
then create TradeIntent
else HOLD_CASH (write packet)
```

Deterministic multiplicative sizing (vol scales **down** only):
```
size = base_risk_by_sleeve * regime_mult * confidence_mult(features only)
       * vol_mult * liquidity_mult * sleeve_stage_mult * live_cap_residual
```
Run the policy engine in **shadow mode first**, diffed against current supervisor behavior, before it can submit (Batch 7 gate).

**DoD Batch 7:** `tests/test_policy_engine.py` — ambiguous top-two sleeves (inside uncertainty band) → HOLD_CASH; unpromoted sleeve cannot produce a live intent.

---

## 10. Regime + portfolio risk overlays (Batch 7b)

- `policy/regime.py`: vol-managed multiplier (down-only), regime permission table (momentum sleeves throttled/paused in risk-off), pre-computed bounded-lag max loss per sleeve, overnight gap budget.
- `policy/portfolio_risk.py`: decompose aggregate exposure by name/sector/beta across **all** sleeves before any order; net duplicate names; enforce per-name/sector/aggregate-beta caps and a portfolio drawdown circuit breaker that halts all live submission on breach.

**DoD Batch 7b:** `tests/test_portfolio_risk.py` — two sleeves long the same name net into one capped position; breaching aggregate beta blocks new live intents; drawdown breach halts submission.

---

## 11. Operational hardening (Batch 8) — extend the Alpaca layer

In `tradingagents/brokers/alpaca.py` / `alpaca_supervisor.py`:

- **Idempotency**: pass `idempotency_key` as the Alpaca `client_order_id`; a retry with the same key must not double-submit.
- **Reconcile-on-start**: before any action, pull broker positions + open orders, diff against local packet state, **fail closed** on mismatch.
- **Single-writer lock**: file/OS lock so overlapping scheduled runs (hourly + market-window jobs) cannot race into the account.
- **Clock-skew guard**: compare local clock to broker/server time; abort if beyond tolerance.
- **Dead-man switch**: heartbeat file written each supervisor tick; if stale, disable new live submission. Document a one-command manual kill (`tradingagents alpaca flatten --confirm` or freeze).
- Keep the existing `alpaca check → dry-run → submit-if-clean` flow; these are added gates, not replacements.

**DoD Batch 8:** `tests/test_operational.py` — duplicate idempotency key submits once; injected position mismatch blocks all actions; stale heartbeat disables live.

---

## 12. Tiny-live gate + scale-up (Batch 9)

- Tiny-live tranche sized so max loss over the test window is a pre-set small fraction of total capital, while still statistically informative.
- Promotion tiny→scaled requires: live hit-rate and Sharpe inside the backtest confidence interval AND live slippage within modeled tolerance, over the pre-registered live sample.
- Continuous drift monitor pauses any sleeve diverging past threshold.

**DoD Batch 9:** `tests/test_tiny_live_gate.py` — promotion blocked until live CI condition met; drift breach auto-pauses.

---

## 13. Failure-mode → test matrix (must all pass before any live capital)

| # | Failure mode | Test file | Kill condition under test |
|---|---|---|---|
| 1 | No real edge | test_benchmark.py | no alpha vs benchmark → never promoted |
| 2 | Overfitting | test_walkforward.py | low DSR rejects sleeve |
| 3 | Insufficient power / decay | test_stats_power.py | unreachable power → shelved |
| 4 | Cross-sleeve selection bias | test_family_budget.py | FDR breach freezes promotions |
| 5 | Slippage / impact | test_cost_model.py | live slippage > tolerance pauses |
| 6 | Adverse selection | test_shadow.py | fill-rate divergence pauses |
| 7 | LLM hallucination / no lift | test_ablation.py | no incremental alpha → muted |
| 8 | Regime change | test_regime.py | classifier flip pauses momentum sleeves |
| 9 | Correlated concentration | test_portfolio_risk.py | aggregate cap / drawdown halts submission |
| 10 | Survivorship bias | test_pit_data.py | non-PIT universe fails integrity gate |
| 11 | Staleness / look-ahead | test_freshness.py | stale/future feature blocks trade |
| 12 | Operational fault | test_operational.py | reconciliation/heartbeat failure disables live |

---

## 14. Build order & "no live capital until" checklist

Implement Batches 1→9 in order. **Do not enable any live submission** until:

- [ ] All §13 tests green in CI.
- [ ] At least one sleeve has cleared the full ladder through **Shadow-confirmed** on real shadow data.
- [ ] Pre-registration entries exist and are frozen for every sleeve that will touch live.
- [ ] Reconcile-on-start, idempotency, single-writer lock, and dead-man switch verified against the paper account end-to-end.
- [ ] Portfolio caps + drawdown breaker verified to halt submission in a forced-breach test.
- [ ] Tiny-live tranche size and max-loss budget written into config and reviewed by you.

Tiny-live is the irreducible test. Everything before it is there to make sure tiny-live is the *first* time real money is ever at risk, and that it fails loudly if the edge is not real.

---

## 15. Suggested CLI surface (extend `cli/main.py`)

```
tradingagents validate prereg <sleeve>        # freeze a hypothesis
tradingagents validate walkforward <sleeve>   # OOS + DSR + power report
tradingagents validate ablation <sleeve>      # deterministic vs +LLM
tradingagents validate benchmark <sleeve>     # alpha vs QQQ/SPY, after cost/tax
tradingagents shadow run <sleeve>             # live-shadow, never fills
tradingagents policy promote <sleeve>         # advance one ladder state if gate met
tradingagents alpaca flatten --confirm        # documented manual kill
```

Keep all of these analysis-only except the existing guarded submit path.
