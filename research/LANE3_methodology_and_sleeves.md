# TradingAgents Methodology and Destructive Repo Redesign

This report uses the attached Lane 3 context pack for repo-specific facts and uses public primary sources for the methodological claims. I did **not** inspect the local modified repo itself, so the repo recommendations below are intentionally concrete on boundaries, schemas, and file layout, but cautious about any local implementation details not present in the context pack. Upstream TradingAgents now supports structured-output agents and a persistent decision log, but it still describes itself as a **research** framework and notes that same ticker/date runs can vary because of model sampling and changing inputs. That is exactly why the execution boundary in your repo should become more deterministic, not more agentic. citeturn21view0

## Executive diagnosis

**Brutal diagnosis**

The current system is most likely doing the wrong thing in the most common way these systems fail: it is probably converting “looks strong” into “deserves capital” too early. Your context pack already points at the issue: overnight planning answers “what looks strongest tomorrow?” better than it answers “what is temporarily mispriced, what should be skipped, and what evidence would kill the trade?” That means the stack is at risk of ranking narratives rather than proving entry quality. TradingAgents itself is explicit that it is research-oriented and non-deterministic; same input paths can still produce different outputs because of model sampling and live-data drift. If live or paper decisions are still materially downstream of those narratives, the methodology layer is underbuilt. citeturn21view0

The highest-risk method is `current-aggressive`. Medium-horizon momentum is real, and industry leadership clearly matters, but those facts do **not** justify a broad “buy the hot thing” supervisor. Classic momentum works over roughly three- to twelve-month horizons, industry momentum explains a large portion of individual-stock momentum, and nearness to the 52-week high improves on simple past-return signals. But momentum also has well-documented crash risk in panic and rebound regimes, and the gross profitability of momentum-style strategies is highly sensitive to trading frictions and implementation assumptions. So the current method should be treated as a **narrow continuation sleeve**, not as the default worldview of the repo. citeturn2view0turn4search0turn16view0turn2view2turn20view0turn20view1

`pullback-support` is the highest-upside rewrite. The reason is simple: it matches your long-only, stocks-only, limit-order, cash-valid constraints better than most institutional-sounding strategy lists do. Short-term reversals are much cleaner when the move being faded is **not** driven by fresh fundamental news; public-news moves are more likely to drift than snap back; and turnover matters because low-turnover stocks behave more like short-term reversal while high-turnover names can behave more like short-term momentum. So the right pullback sleeve is not “red day, buy dip.” It is “controlled retracement inside intact leadership, with no fresh negative information, inside a favorable regime, and with a clear invalidator.” citeturn16view1turn18view1turn16view2turn14view0

Chasing more signals before fixing the policy layer is a bad tradeoff. Alpaca’s paper environment does **not** route to live exchanges and does not model market impact, information leakage, latency-driven slippage, or queue position for non-marketable limit orders. Backtests are also notoriously easy to overfit: Bailey, Borwein, López de Prado, and Zhu formalize PBO precisely because in-sample winners frequently disappoint out of sample, and the Deflated Sharpe Ratio exists because strategy selection across many trials inflates apparent skill. So the next unit of work should be trade-intent schemas, deterministic gates, packetized audit logs, and sleeve promotion rules — not another round of signal collection. citeturn8view0turn8view2turn15view0turn15view1

**Highest-leverage methodology change**

Insert a typed **trade-intent + deterministic policy engine** between all research outputs and all broker actions. Candidate rank should only buy a symbol the right to be reviewed more deeply. It should **never** imply a trade. A trade exists only if a candidate becomes a typed intent, the intent passes hard gates, position size is computed from deterministic rules, dry-run succeeds, and an immutable packet is written.

**What should not be touched yet**

Do **not** loosen the Alpaca safety boundary. Do **not** broaden asset classes. Do **not** change the “limit-orders-only / stocks-only / fail-closed / dry-run-before-submit” guardrails. SEC guidance is clear that limit orders protect price but are not guaranteed to execute, and extended-hours order handling is materially different enough that many firms restrict orders there to limits only. That is a reason to harden the boundary, not to get creative around it. citeturn19view0turn19view1turn19view2turn19view3

**Current-method audit**

| Current method | Verdict | Reason |
|---|---|---|
| `current-aggressive` | **Preserve concept, rewrite hard, demote from default** | Keep only as a breakout/continuation sleeve with strict extension, regime, liquidity, and invalidator rules. |
| `pullback-support` | **Promote concept, rewrite fully** | Best alignment with “good dip” objective and long-only constraints; should become first-class in overnight packets and supervisor inputs. |
| `catalyst-relative-strength` | **Split, not merge** | One sleeve should handle catalyst continuation; a separate sleeve should handle underreaction/event drift. Those are different trades. |

## Methodology blueprint

The repo should be rebuilt as a **research-to-paper-to-live factory**, not as a smarter-looking opinion engine. The clean architecture is: deterministic universe screens first, typed feature packets second, optional agent hypotheses third, policy gating and sizing fourth, Alpaca execution boundary last. Upstream TradingAgents already gives you useful primitives — structured-output agents, persistence, checkpoints, and a decision log — but its own docs are clear that the framework is non-deterministic and research-first. That implies the correct role for agents is hypothesis generation, not order authorization. citeturn21view0

| Layer | Job | Design rule |
|---|---|---|
| Research layer | Generate hypotheses from prefetched data | Agents output hypotheses only: thesis, counter-thesis, evidence, invalidators, entry trigger, exit trigger, freshness requirement, data confidence, risk flags. |
| Feature layer | Build typed, point-in-time features | All features must be freshness-stamped, source-stamped, and complete enough to fail closed. |
| Strategy sleeve layer | Route candidates into sleeve-specific scoring paths | Sleeves own their triggers, entry logic, exits, and invalidators. Macro/regime and sector confirmation are overlays, not standalone alpha sleeves. |
| Validation layer | Determine whether a sleeve deserves more capital or a harder environment | Walk-forward, OOS, event studies, costs, slippage, PBO, DSR, regime splits, exposure decomposition. |
| Paper tournament layer | Compare sleeves in a stateful, realistic promotion ladder | Paper remains paper-only and records sleeve health, drawdown, drift, packet integrity, and promotion status. |
| Policy engine layer | Accept, reject, size, or hold cash | Hard gates first, then scoring, then size. Cash is an explicit valid output. |
| Alpaca execution boundary | Submit only eligible, dry-run-approved intents | Stocks-only, long-only, limit-only, exposure-cap-aware, fail-closed. |
| Reporting and audit layer | Write immutable run packets for every decision | Every decision — including “no trade” — writes a packet with hashes, versions, and gate outcomes. |

The deterministic decision pipeline should be:

```text
universe_screen
-> candidate_packet
-> feature_packet
-> sleeve_routing
-> optional_llm_hypothesis
-> deterministic_sleeve_score
-> hard_gates
-> position_sizing
-> entry_plan / exit_plan / invalidator
-> dry_run
-> submit_or_hold_cash
-> immutable_run_packet
```

**How candidate rank becomes a deterministic order decision**

Rank should mean **review priority**, nothing more. The conversion rule should be binary:

```text
if candidate passes universe checks
and feature completeness >= minimum
and sleeve trigger is satisfied
and sleeve score >= threshold
and score margin >= uncertainty band
and no stale/missing/blocking data
and sleeve promotion stage allows this environment
and live caps allow size > 0
and dry-run passes
then create order intent
else HOLD_CASH
```

That “uncertainty band” matters. If the best sleeve barely beats the next sleeve, the system should not pretend confidence. It should log ambiguity and hold cash.

**Overnight planner as a batch research factory**

The planner should stop behaving like “LLM deep-think over a few names, shallow scores over the rest” and start behaving like a **batch research pipeline** with selective escalation:

| Cadence | Compute | Use case |
|---|---|---|
| Weekly | slow regime features, validation summaries, sleeve health, rolling support maps, exposure decomposition | heavy tasks that do not need nightly reruns |
| Overnight | all-candidate deterministic screens, sleeve routing, top-N escalation, next-session plans, support/trigger maps | main research batch |
| Hourly and session checkpoints | freshness refresh, spread/liquidity refresh, trigger validation, invalidator checks, exits/reductions, live cap checks | fast execution-adjacent control loop |

Within the context pack’s approximate overnight budget, the planner should reserve a small fixed budget for all-candidate screening, a capped fixed budget for LLM escalation, and a protected budget for packet writing. A practical design is: deterministic screen first, route to sleeves second, escalate only the top few symbols where the model can add value, and never spend model time on symbols whose feature hash, event hash, and thesis class are unchanged. If the LLM times out or fails, the planner should still emit a deterministic packet and default to analysis-only or hold-cash. That is slower-looking than “just ask the model again,” but far safer.

**Agent methodology**

Use agents where they help: interpreting mixed evidence, extracting explicit invalidators, summarizing public information, and proposing trigger logic. Do **not** use them to size, submit, or waive constraints. Critic/adversarial review should run only when it is worth the runtime: for live-eligible candidates, for symbols with contradictory data, or where the top-two sleeves are inside the uncertainty band. Everywhere else, structured single-pass hypotheses are enough.

**Position sizing**

Position size should be deterministic and multiplicative:

```text
base_risk_budget_by_sleeve
x regime_multiplier
x confidence_multiplier
x volatility_multiplier
x liquidity_multiplier
x sleeve_stage_multiplier
x live_cap_residual
= final_risk_budget
```

Use volatility to scale **down**, not to justify larger risk. Moreira and Muir show that taking less risk when volatility is high improves risk-adjusted results across multiple factors because volatility is forecastable while expected returns do not rise proportionally with it. That is exactly the right logic for a live-safe long-only system. citeturn15view2

Because Alpaca paper trading does not model queue position, slippage, impact, or information leakage well, live size should start far smaller than paper size, and initial live ADV caps should be materially tighter than paper ones. Paper is for environmental validation, not proof of executable size. citeturn8view0turn8view2

## Strategy sleeves

The sleeve set should be narrow and internally coherent. Continuation sleeves should exploit medium-horizon momentum, sector leadership, and 52-week-high behavior. Reversal sleeves should only buy retracements when the move looks non-fundamental rather than informational. Event sleeves should exploit underreaction and drift after public information. Regime and sector confirmation should be universal overlays, not separate alpha myths. citeturn2view0turn4search0turn16view0turn18view1turn16view1turn15view2

| sleeve | edge hypothesis | candidate trigger | required features | entry logic | exit logic | invalidators | paper promotion requirement | live gate requirement | current repo integration point |
|---|---|---|---|---|---|---|---|---|---|
| breakout-continuation | Medium-horizon strength persists when stock leadership, industry leadership, and price-level context align. | Near 20D or 52W high after tight consolidation or orderly breakout retest. | 3–12M RS, 20D RS, 52W-high proximity, sector RS, turnover/liquidity, realized vol, spread, extension-from-anchor. | Buy limit only after trigger is **observable** and extension is still acceptable; prefer breakout retest or shallow pullback after confirmation, not first vertical spike. | Time stop plus technical failure: failed hold above breakout zone, loss of short-term trend, or target hit. | Failed breakout, fresh negative news, risk-off regime, excessive gap extension, spread blowout. | Positive expectancy net conservative slippage, stable drawdown, no packet violations, sufficient paper sample. | Sleeve must be promoted; regime must not be risk-off; size must fit live caps and ADV cap. | Rewrite and narrow `current-aggressive`. |
| pullback-support | Controlled retracement inside intact leadership mean-reverts when the move is non-fundamental and support-rich. | 1–3 ATR pullback into defined support in an intact uptrend with no fresh negative event. | Rising trend anchors, support map, ATR distance, RSI state, sell-volume profile, gap flags, sector RS, market regime, earnings/news blackout, optional filing/fundamental support. | Buy limit near support **after** hold/reclaim evidence, not while price is still slicing through support. | Scale out into rebound; full exit on support failure, time stop, or regime deterioration. | Close below support, heavy distribution, fresh negative filing or guidance, sector breakdown, earnings blackout breach. | Separate pullback scorecard, MAE/MFE tracking, gap-risk penalties, adverse-selection logging, stable behavior across regimes. | Initially tiny-live only after strong paper record and shadow-mode packet integrity. | Full rewrite of `pullback-support`; make first-class. |
| catalyst-continuation | Fresh positive catalyst can continue when event-day gains are retained and peers/sector confirm. | Positive event day or next-day consolidation with strong relative strength and volume retention. | Event recency, event type, gap retention, RVOL, intraday hold/reclaim metrics, peer/sector confirmation, spread/liquidity, regime. | Buy limit only after event-day zone holds or reclaims; avoid chasing first impulse. | Exit on event-gap failure, time decay, or target. | Event-day midpoint loss, negative follow-up news, sector contradiction, abnormal spread widening. | Show edge net costs on event buckets, not aggregate PnL camouflage. | Requires reliable event packets and paper/live drift within tolerance. | Split from `catalyst-relative-strength`. |
| underreaction-event-drift | Public information is often absorbed gradually; muted initial reaction can drift further. | Positive public information with incomplete initial repricing and no contradiction in subsequent headlines. | Event classification, surprise severity, first-day price response, post-event drift features, confirmation from sector/peers, freshness, optional analyst/filing support. | Buy limit on first controlled pause/reclaim if price has **not** already fully run. | Shorter holding window than breakout sleeve; exit on drift decay, contradiction, or target. | Contradictory follow-up filing, muted thesis confidence, negative market-regime shock, stale event packet. | Event-study evidence, conservative costs, and enough event count to matter. | Keep paper-only or tiny-live until event packet quality is proven. | New sleeve, carved out of `catalyst-relative-strength`. |
| cash-default | Preserving optionality is superior to forcing weak evidence into a trade. | No sleeve passes gates, or evidence is ambiguous, stale, contradictory, or unpromoted. | Gate outcomes, uncertainty band, stale-data flags, cap limits, promotion status. | No order. | Re-evaluate at next scheduled check. | A valid promoted intent later appears. | None. Cash is the policy fallback, not a strategy to “promote.” | Always allowed. | New default behavior inside policy engine. |

**Macro/regime-compatible trades**

Do **not** create a standalone “macro sleeve” yet. Use macro and regime as an overlay that decides which sleeves may act and at what size. Daniel and Moskowitz show momentum crashes cluster in panic states and rebounds, and Moreira–Muir show that lowering risk when volatility is high improves risk-adjusted outcomes. So regime should control **permission and size**, not become another vague story generator. citeturn2view2turn15view2

**Cross-stock and sector confirmation**

This should also be a universal overlay, not a separate sleeve. Industry momentum matters enough that a long stock thesis without sector or peer confirmation should be treated as lower quality by default. citeturn4search0turn16view0

## Pullback support redesign

`pullback-support` should become the repo’s first serious sleeve because it is the cleanest fit for the system you are actually building: long-only, limit-only, capital-constrained, and skeptical of chasing. The central question is not “did the stock go down a bit?” The real question is “did the stock retrace inside intact leadership, or did the market receive information that invalidates the old thesis?” That distinction matters because public-news moves often drift, while reversals are cleaner when the prior move is not driven by fundamental news. Stocks near 52-week highs also retain continuation properties, which means a pullback sleeve should look for dips in leaders, not random weakness in laggards. Turnover matters too: low-turnover names fit reversal better, high-turnover names often behave more like short-term momentum. citeturn16view1turn18view1turn16view0turn16view2

| Signal family | Good dip | Falling knife | Policy consequence |
|---|---|---|---|
| Trend context | Above rising 50D and 200D, or above rising 200D with recent breakout structure still intact | Below flat/falling 200D, or prior breakout fully broken | Good dip stays eligible; knife is blocked |
| Support proximity | Pullback lands within a precomputed support zone or prior breakout shelf | Price is between levels with no clean support map | No clean level means no trade |
| Pullback depth | Roughly 0.75–2.5 ATR or similar controlled retracement | Greater than about 3 ATR without reclaim, or multiple support levels lost | Route to block or watch-only |
| ATR and RSI role | ATR normalizes depth and stop distance; RSI used only as a bounded state variable, not as alpha | ATR expanding violently and RSI collapsing with fresh bad news | ATR/RSI become risk flags, not buy signals |
| Volume behavior | Selling volume decelerates, or weakness occurs on moderate trade | Down volume expands into distribution or repeated heavy red closes | Block or require stronger reclaim evidence |
| Gap behavior | Small gap or partial gap-down that is reclaimed quickly | Large downside gap that stays open or expands | Block until gap damage is repaired |
| Sector confirmation | Stock still outperforms peers or sector, and sector is not breaking down | Stock and sector both deteriorate versus market | Reject or sharply downsize |
| Market regime | Broad regime is risk-on or neutral | Broad regime is stress or panic | New pullback buys blocked or paper-only |
| News and earnings blackout | No scheduled earnings nearby and no fresh negative filing/headline cluster | Earnings inside blackout or fresh negative event unresolved | Block |
| Public filing and fundamental support | Optional positive support: insider buy, constructive filing, estimate support, clean quality trend | Negative filing, guidance reset, or thesis contradiction | Block |

The pullback sleeve should be **fast to prove itself**. In large U.S. stocks, the temporary component of idiosyncratic shocks that does reverse does so with a short half-life; Collin-Dufresne and Daniel estimate roughly 10% of shocks as temporary with a half-life around 2.5 days. That is a good reminder not to let “dip buys” linger indefinitely as philosophical positions. If the retracement is valid, it should usually show evidence quickly. citeturn14view0

**Exact overnight report section**

```yaml
pullback_support_section:
  as_of: "2026-06-01T03:00:00-05:00"
  market_regime: "risk_on | neutral | risk_off"
  candidates:
    - symbol: "AAPL"
      sleeve_score: 0.82
      trend_quality: 0.88
      support_zone:
        kind: "prior_breakout + 20d_ema"
        zone_low: 201.40
        zone_high: 203.10
      pullback_depth_atr: 1.35
      rsi_state: "reset_not_broken"
      sell_volume_state: "moderate"
      sector_relative_strength: 0.74
      blackout_flags:
        earnings: false
        fresh_negative_news: false
      thesis: "Orderly retracement inside intact leadership"
      counter_thesis: "Could be start of distribution if support fails on volume"
      entry_trigger: "hold_or_reclaim_support"
      entry_limit_zone: [202.10, 202.70]
      invalidator: "daily_close_below_201.20 OR fresh_negative_filing"
      initial_exit_plan: "trim_into_rebound_then_trail"
      stale_after: "2026-06-02T10:30:00-05:00"
```

The report section should answer four things plainly: **why this is a good dip, why it might be wrong, what level proves it wrong, and what freshness condition must still hold at the next supervisor run**.

**Exact supervisor input packet**

```json
{
  "packet_type": "pullback_support_watch",
  "schema_version": "1.0.0",
  "candidate_id": "cand_AAPL_2026-06-01_pullback",
  "symbol": "AAPL",
  "environment": "paper | tiny_live | full_live",
  "allowed_actions": ["watch", "paper_enter", "live_enter"],
  "as_of": "2026-06-01T03:00:00-05:00",
  "stale_after": "2026-06-02T10:30:00-05:00",
  "support_zone": {
    "zone_low": 201.40,
    "zone_high": 203.10,
    "anchor_types": ["prior_breakout", "20d_ema"]
  },
  "trigger": {
    "type": "support_hold_or_reclaim",
    "conditions": [
      "last_price >= 201.40",
      "spread_bps <= 15",
      "no_fresh_negative_news",
      "market_regime != risk_off"
    ]
  },
  "entry_plan": {
    "order_type": "limit",
    "entry_limit_low": 202.10,
    "entry_limit_high": 202.70,
    "time_in_force": "day"
  },
  "invalidator": {
    "type": "hard_block",
    "conditions": [
      "daily_close_below_201.20",
      "fresh_negative_filing",
      "earnings_blackout"
    ]
  },
  "exit_plan": {
    "first_trim_rule": "at_rebound_to_prior_range",
    "full_exit_rule": "support_failure_or_time_stop"
  },
  "size_context": {
    "regime_multiplier": 0.75,
    "volatility_multiplier": 0.80,
    "sleeve_stage_multiplier": 0.25
  }
}
```

**Paper tournament scoring for pullback-support**

Do not score this sleeve on raw paper PnL alone. Score it on whether it bought **good** dips and avoided bad ones. Alpaca’s own documentation says paper trading is a simulation and does not capture impact, queue position, or slippage realistically enough to treat paper outcomes as final truth. That means the tournament has to reward setup quality, not just outcome luck. citeturn8view0turn8view2

A practical scorecard is:

```text
setup_score
= trend_quality
+ support_confluence
+ sector_confirmation
+ regime_fit
- blackout_risk
- knife_risk

trade_score
= realized_R_multiple
+ favorable_excursion_bonus
- adverse_excursion_penalty
- gap_penalty
- invalidator_breach_penalty

promotion_score
= median(trade_score)
x packet_integrity
x drawdown_discipline
x environment_stability
```

That does two useful things. It stops the sleeve from getting promoted just because a few ugly names bounced, and it makes the tournament penalize exactly the behavior you want to eliminate: buying informational damage and calling it mean reversion.

## Schemas and deterministic policy

The repo should formalize the idea that **agents produce hypotheses, policy produces decisions**. Upstream TradingAgents already moved toward structured outputs, which is useful, but the framework also explicitly says its runs vary and that it is research-oriented. So the right next step is not “more debate rounds.” It is typed schemas and a deterministic acceptance layer. citeturn21view0

**Agent output contract**

```json
{
  "hypothesis_id": "hyp_2026-06-01_AAPL_news",
  "symbol": "AAPL",
  "sleeve_candidates": ["pullback-support", "underreaction-event-drift"],
  "thesis": "Positive public information remains partially underpriced",
  "counter_thesis": "Recent weakness may reflect new information not yet fully assimilated",
  "evidence": [
    {"type": "news", "summary": "constructive guidance", "freshness_minutes": 55, "confidence": 0.83},
    {"type": "price_structure", "summary": "holding prior breakout zone", "freshness_minutes": 10, "confidence": 0.79}
  ],
  "invalidators": [
    "fresh_negative_filing",
    "close_below_support"
  ],
  "entry_trigger": "support_hold_or_reclaim",
  "exit_trigger": "rebound_to_prior_range_or_time_stop",
  "freshness_requirement_minutes": 120,
  "data_confidence": 0.81,
  "risk_flags": ["earnings_within_4_days? false", "spread_widening? false"]
}
```

**Candidate schema**

```json
{
  "candidate_id": "cand_AAPL_2026-06-01",
  "schema_version": "1.0.0",
  "symbol": "AAPL",
  "as_of": "2026-06-01T03:00:00-05:00",
  "universe_bucket": "large_cap_liquid",
  "eligibility": {
    "stocks_only": true,
    "long_only": true,
    "paper_ok": true,
    "live_ok": false
  },
  "routing_hints": ["pullback-support", "breakout-continuation"],
  "freshness": {
    "market_data_age_seconds": 0,
    "news_data_age_seconds": 1800,
    "stale_after": "2026-06-02T10:30:00-05:00"
  },
  "event_flags": {
    "earnings_blackout": false,
    "fresh_negative_news": false,
    "trading_halt": false
  }
}
```

**Feature schema**

```json
{
  "feature_id": "feat_AAPL_2026-06-01",
  "candidate_id": "cand_AAPL_2026-06-01",
  "price_features": {
    "dist_to_20d_ema_atr": -0.40,
    "dist_to_50d_ema_atr": 0.55,
    "dist_to_200d_ema_atr": 2.10,
    "dist_to_52w_high_pct": -3.2
  },
  "trend_features": {
    "trend_state": "uptrend_intact",
    "breakout_level": 206.40,
    "support_levels": [203.10, 201.40]
  },
  "flow_features": {
    "rvol_20d": 1.12,
    "sell_volume_state": "moderate",
    "turnover_bucket": "medium"
  },
  "relative_strength": {
    "vs_sector_20d": 0.71,
    "vs_market_20d": 0.64
  },
  "event_features": {
    "event_type": null,
    "event_recency_hours": null,
    "fresh_negative_news": false,
    "earnings_blackout": false
  },
  "regime_features": {
    "market_regime": "neutral",
    "volatility_state": "elevated_not_extreme"
  },
  "quality": {
    "feature_completeness": 0.96,
    "feature_hash": "sha256:..."
  }
}
```

**Trade intent schema**

```json
{
  "intent_id": "intent_AAPL_pullback_2026-06-01",
  "schema_version": "1.0.0",
  "symbol": "AAPL",
  "sleeve": "pullback-support",
  "environment": "paper | tiny_live | full_live",
  "policy_version": "2026.06.01",
  "candidate_id": "cand_AAPL_2026-06-01",
  "feature_id": "feat_AAPL_2026-06-01",
  "hypothesis_ids": ["hyp_2026-06-01_AAPL_news"],
  "decision_state": "proposed | approved | rejected | hold_cash",
  "thesis_summary": "Controlled pullback inside intact leadership",
  "entry_trigger": {
    "type": "support_hold_or_reclaim",
    "observable_conditions": [
      "last_price >= 201.40",
      "spread_bps <= 15",
      "no_fresh_negative_news"
    ]
  },
  "entry_order": {
    "order_type": "limit",
    "limit_price_low": 202.10,
    "limit_price_high": 202.70,
    "time_in_force": "day"
  },
  "exit_plan": {
    "time_stop_days": 5,
    "first_trim_rule": "prior_range_retest",
    "final_exit_rule": "support_failure_or_target"
  },
  "invalidator": {
    "hard_block_conditions": [
      "earnings_blackout",
      "fresh_negative_filing",
      "close_below_201.20"
    ]
  },
  "sizing": {
    "base_risk_budget_bps": 30,
    "regime_multiplier": 0.75,
    "confidence_multiplier": 0.80,
    "volatility_multiplier": 0.80,
    "liquidity_multiplier": 0.90,
    "sleeve_stage_multiplier": 0.25,
    "computed_notional_cap": 0
  }
}
```

**Risk gate schema**

```json
{
  "gate_id": "gate_AAPL_2026-06-01",
  "intent_id": "intent_AAPL_pullback_2026-06-01",
  "hard_gates": {
    "stocks_only": true,
    "long_only": true,
    "limit_only": true,
    "dry_run_passed": true,
    "data_fresh": true,
    "data_complete": true,
    "no_blocking_event": true,
    "sleeve_promoted_for_environment": false,
    "live_cap_available": false
  },
  "soft_gates": {
    "score_above_threshold": true,
    "score_margin_above_uncertainty_band": true,
    "spread_ok": true,
    "adv_cap_ok": true
  },
  "final_action": "paper_only",
  "rejection_reasons": []
}
```

**Validation report schema**

```json
{
  "validation_report_id": "val_pullback_support_v3",
  "sleeve": "pullback-support",
  "rule_version": "v3",
  "sample_summary": {
    "backtest_trades": 84,
    "paper_trades": 36,
    "tiny_live_trades": 0
  },
  "performance": {
    "expectancy_R": 0.18,
    "max_drawdown_R": -4.2,
    "profit_factor": 1.24,
    "regime_split": {
      "risk_on": 0.31,
      "neutral": 0.08,
      "risk_off": -0.22
    }
  },
  "robustness": {
    "walk_forward_pass": true,
    "event_study_pass": true,
    "cost_model_pass": true,
    "pbo_estimate": 0.14,
    "deflated_sharpe_positive": true
  },
  "promotion_recommendation": "paper_promoted"
}
```

**Paper tournament state schema**

```json
{
  "tournament_state_id": "paper_tournament_2026-06-01",
  "schema_version": "1.0.0",
  "sleeves": {
    "breakout-continuation": {
      "status": "paper_candidate",
      "paper_trades": 48,
      "drawdown_R": -3.8,
      "packet_integrity": 1.0,
      "promotion_eligible": false
    },
    "pullback-support": {
      "status": "paper_promoted",
      "paper_trades": 36,
      "drawdown_R": -2.6,
      "packet_integrity": 1.0,
      "promotion_eligible": true
    }
  },
  "last_updated": "2026-06-01T10:05:00-05:00"
}
```

**Run packet schema**

```json
{
  "run_id": "run_2026-06-01_overnight_001",
  "schema_version": "1.0.0",
  "run_type": "overnight | supervisor | paper_tournament | daily_report",
  "code_version": "git:abc123",
  "policy_version": "2026.06.01",
  "as_of": "2026-06-01T03:00:00-05:00",
  "inputs": {
    "universe_hash": "sha256:...",
    "feature_hashes": ["sha256:..."],
    "hypothesis_hashes": ["sha256:..."]
  },
  "decisions": [
    {
      "symbol": "AAPL",
      "intent_id": "intent_AAPL_pullback_2026-06-01",
      "final_action": "hold_cash | paper_enter | live_enter | reduce | exit",
      "why": "string",
      "gate_id": "gate_AAPL_2026-06-01"
    }
  ],
  "audit": {
    "dry_run_performed": true,
    "order_submit_attempted": false,
    "safety_invariants_passed": true
  }
}
```

**Deterministic sizing rule**

The sizing rule should use the schema fields above, not hidden judgment:

```text
risk_budget_dollars
= equity
* base_risk_budget_bps
* regime_multiplier
* confidence_multiplier
* volatility_multiplier
* liquidity_multiplier
* sleeve_stage_multiplier

share_count
= floor(
    min(
      risk_budget_dollars / stop_distance_dollars,
      name_cap_dollars / limit_price,
      adv_cap_dollars / limit_price
    )
  )
```

Because paper trading ignores queue-position realism and several execution frictions, `sleeve_stage_multiplier` should be small for initial live use, and `adv_cap_dollars` should start conservative. citeturn8view0turn8view2

## Repo architecture and destructive refactor

A destructive refactor is warranted. The present naming alone hints at an architectural smell: `alpaca_supervisor.py` is not really a broker concern, and `paper_tournament.py` is not really a broker concern either. Broker modules should know about credentials, account state, dry-runs, and order IO. They should not own research methodology, strategy ranking, or sleeve promotion logic. The repo should be reorganized so that the **broker is a boundary**, not a brain. That fits both the system context pack and upstream TradingAgents’ research-first design. citeturn21view0turn8view0

| Existing area | Action | Why | Target shape |
|---|---|---|---|
| `cli/main.py` | **Preserve, thin further** | CLI should orchestrate services, not own policy. | Keep command entry points; move logic into services. |
| `tradingagents/dataflows/` | **Preserve core, rewrite boundaries** | Keep adapters and snapshots only; move scoring logic out. | `dataflows/` becomes typed ingestion + normalization only. |
| `tradingagents/brokers/alpaca.py` | **Preserve and harden** | This should remain the execution boundary. | Keep account checks, dry-run, submit, and order schema validation only. |
| `tradingagents/brokers/alpaca_supervisor.py` | **Rewrite and relocate** | Supervisor is orchestration + policy, not brokerage. | New `tradingagents/supervisors/market_supervisor.py`; old file becomes a shim or compatibility wrapper. |
| `tradingagents/brokers/paper_tournament.py` | **Rewrite and relocate** | Tournament is sleeve validation logic, not brokerage. | New `tradingagents/tournament/paper_engine.py`; old file becomes shim. |
| `tradingagents/agents/` | **Preserve some prompts, rewrite outputs** | Agents are useful, but they must emit typed hypotheses only. | Structured-output analyst and critic contracts. |
| `tradingagents/graph/` | **Preserve orchestration, strip authority** | Graph can still sequence research flow. It should not authorize orders. | Graph writes research packets and hypotheses only. |
| `results/` | **Rewrite layout** | Ad hoc result folders make audit and promotion messy. | Immutable run packets with schema versions and manifests. |
| `tests/` | **Expand aggressively before live-sensitive changes** | Safety invariants must predate refactor. | Separate safety, policy, packet, tournament, and supervisor suites. |

**Preserve**

Keep the Alpaca execution boundary, dry-run requirement, limit-order-only constraint, and the existing automation schedule surfaces. Preserve any stable data adapter code and any useful prompt scaffolding from `agents/` that can be upgraded to structured outputs.

**Rewrite**

Rewrite the supervisor, tournament, and all ranking-to-order paths. Rewrite packet layout. Rewrite any code that mixes research, policy, and execution in the same path.

**Delete or quarantine**

Quarantine all legacy ranking heuristics that can trigger action without full typed evidence. Quarantine any code path where overnight research or paper tournament can even indirectly call live submission. Quarantine method-name flags that encapsulate opaque behavior instead of typed sleeves. Put that code in `tradingagents/legacy/` and make it unavailable to live environments.

**New module structure**

```text
tradingagents/
  domain/
    candidate.py
    features.py
    hypotheses.py
    intents.py
    gates.py
    packets.py
    validation.py
  research/
    universe.py
    feature_builders.py
    cache.py
    planner.py
    escalation.py
    freshness.py
  sleeves/
    breakout_continuation.py
    pullback_support.py
    catalyst_continuation.py
    event_drift.py
    overlays.py
  policy/
    engine.py
    scoring.py
    sizing.py
    entries.py
    exits.py
    hold_cash.py
    live_gate.py
  supervisors/
    market_supervisor.py
    overnight_planner.py
    premarket_brief.py
    daily_report.py
  tournament/
    paper_engine.py
    sleeve_state.py
    promotion.py
  execution/
    alpaca_gateway.py
    order_models.py
    account_checks.py
  reporting/
    packet_writer.py
    report_renderers.py
    audit.py
  validation/
    walk_forward.py
    event_studies.py
    bootstrap.py
    costs.py
    regime_analysis.py
    pbo.py
    dsr.py
  legacy/
    legacy_rankers.py
    legacy_supervisor_paths.py
```

**Results packet structure**

```text
results/
  runs/
    2026-06-01/
      run_overnight_001/
        manifest.json
        universe_snapshot.parquet
        candidate_packets/
        feature_packets/
        hypothesis_packets/
        intent_packets/
        gate_decisions/
        dry_runs/
        final_report.md
  tournament/
    state/
    ledgers/
    promotions/
  validation/
    sleeve_name/
      rule_version/
        report.json
        figures/
        summaries/
```

**Migration path**

Stage the migration so live behavior cannot drift accidentally:

1. Add schemas, invariants, and packet writers first.
2. Shadow-write the new packets alongside the old outputs with **no order-behavior changes**.
3. Build the new policy engine in shadow mode and compare old decisions vs. new decisions.
4. Move `pullback-support` to the new framework first, but keep it paper-only.
5. Only after packet parity and safety test coverage should the new supervisor read new intents for live-eligible sleeves.
6. Delete legacy ranking paths only after a full paper period with packet integrity and no safety regressions.

## Validation promotion and implementation roadmap

Paper trading is useful, but Alpaca is explicit that it is only a simulation and that live trading introduces things paper does not model well: market impact, information leakage, latency slippage, and queue position. That is why a promotion ladder needs more than paper PnL. It needs staged evidence, strict no-trade defaults, conservative costs, and a **tiny-live bridge** before full live capital. Backtest validation also needs genuine anti-self-delusion tools: PBO for backtest overfitting, DSR for shrinkage after multiple testing, conservative transaction-cost assumptions, and regime-split analysis. citeturn8view0turn8view2turn15view0turn15view1turn20view0turn20view1

| Stage | Minimum evidence | Allowed action | Pause or kill trigger |
|---|---|---|---|
| research-only | Idea exists; schema valid; no deterministic rule complete yet | Analysis packets only | Any attempt to create executable order path |
| backtest-ready | Deterministic rules encoded, point-in-time discipline checked, cost model attached, run packets valid | Offline validation only | Look-ahead leak, schema drift, missing cost assumptions |
| paper-test-ready | Walk-forward harness passes, event-study logic passes, packet integrity 100%, dry-run mocks pass | Paper only | Missing packets, stale-data tolerance too loose, environment mismatch |
| paper candidate | Sleeve has enough paper trades to be non-trivial and behaves within risk budget | Paper only | Drawdown breach, packet violations, broken invalidators |
| paper promoted | Positive expectancy net conservative slippage, acceptable drawdown, regime splits not pathological, PBO and DSR not disqualifying | Paper plus shadow-live monitoring | Material degradation versus backtest assumptions |
| tiny-live-eligible | Sufficient paper sample and stable shadow-live behavior; sleeve-size multiplier starts tiny | One small live position at a time, strict name/ADV limits | Live-paper drift beyond threshold, any invariant failure, repeated missed exits |
| full live eligibility | Tiny-live record proves packet integrity, fill realism, and stable drawdown | Normal live sizing within sleeve caps | Regime-specific drawdown breach, drift, stale data, or gate failure |
| live-paused or kill-switch | Automatic state after threshold breach | No new live entries; exits and reductions only | Resume only after explicit review and fresh validation |

**Starting thresholds**

These should be starting defaults, not holy scripture:

- `paper promoted`: at least **30 closed paper trades** or an equivalent event count for a low-frequency sleeve, plus at least **8 weeks** of observation, positive expectancy after conservative slippage, and no invariant failures.
- `tiny live`: at least **60 paper trades** or equivalent event count, at least **12 weeks**, healthy regime splits, stable packet integrity, and shadow-mode decisions matching real supervisor conditions.
- `full live`: at least **20 tiny-live trades** with acceptable paper/live drift, no safety violations, and live drawdown inside sleeve budget.

If trade frequency is much lower, use **event count and calendar breadth** instead of forcing a trade-count fetish. The point is not round numbers. The point is “enough observations to stop fooling yourself.”

**Test and invariant strategy**

Before touching live-sensitive code, add these tests:

| Pytest target | What it must prove |
|---|---|
| `tests/safety/test_research_never_submits_orders.py` | overnight planner, premarket briefs, and research-only runs cannot submit orders |
| `tests/safety/test_paper_tournament_never_hits_live.py` | paper tournament cannot reach live Alpaca credentials or endpoints |
| `tests/safety/test_order_boundary_accepts_stocks_limit_only.py` | live orders are buy/sell stock orders only, limit-only, long-only |
| `tests/safety/test_no_margin_no_short_no_options_no_crypto.py` | forbidden assets and margin-expanding behavior fail immediately |
| `tests/safety/test_dry_run_required.py` | submit path is impossible unless dry-run succeeded |
| `tests/policy/test_fail_closed_on_stale_or_missing_data.py` | stale, incomplete, or blocked data yields hold-cash or reject |
| `tests/policy/test_unpromoted_sleeves_blocked_from_live.py` | sleeve stage governs environment eligibility |
| `tests/policy/test_live_caps_respected.py` | single-name, sleeve, and portfolio live caps are enforced |
| `tests/packets/test_run_packet_written_for_every_decision.py` | every decision, including hold-cash, writes packets |
| `tests/pullback/test_good_dip_vs_falling_knife.py` | pullback sleeve routes support holds and rejects informational damage |
| `tests/integration/test_shadow_supervisor_no_behavior_change.py` | new shadow mode emits packets without changing current live behavior |
| `tests/integration/test_supervisor_dry_run_to_submit_path.py` | submit path remains gated end to end |

Also add smoke tests for each automation surface in the context pack so Batch 1 can prove the refactor has not changed live behavior.

**Batch implementation roadmap for Codex**

| Batch | Goal | Likely files touched | Runtime and memory impact | Failure risk | Safety checks and tests | Handoff |
|---|---|---|---|---|---|---|
| Freeze invariants and schemas | Lock safety boundary before any behavior change | `alpaca.py`, tests, new schema files, packet writer stubs | negligible runtime impact | low | add all safety tests; no live behavior changes allowed | invariants report + schema draft |
| Structured trade-intent layer | Add candidate, feature, hypothesis, intent, gate, and packet models | new `domain/`, `reporting/`, wrappers in CLI/supervisor | negligible | medium if schema too vague | schema round-trip tests, packet-write smoke tests | schema contract report |
| Deterministic policy engine | Build scoring, gating, hold-cash, and sizing engine in shadow mode | new `policy/`, supervisor adapters | low | medium-high if legacy logic leaks through | fail-closed tests, live-block tests, cap tests | shadow-decision comparison |
| Improved paper tournament promotion | Replace fast scorekeeper with sleeve state machine | new `tournament/`, legacy shim | low | medium | paper-only isolation tests, promotion-state tests | tournament state report |
| Pullback-support rewrite | Make pullback a first-class sleeve with explicit classifier | `sleeves/pullback_support.py`, planner, tournament | low-moderate | medium | good-dip/falling-knife tests, packet integrity tests | pullback sleeve evaluation report |
| Overnight batch planner redesign | Add deterministic screen, cache, staleness, top-N escalation | `research/planner.py`, cache, feature builders, supervisors | moderate, but should reduce repeated work | medium-high | timeout/fallback tests, stale-cache tests, no-submit tests | runtime budget report |
| Validation and backtest reports | Add walk-forward, costs, regime splits, PBO, DSR, event studies | new `validation/` | offline-heavy; no live impact | medium | validation artifact tests, no-lookahead harness tests | validation dossier |
| Supervisor and live gate integration | Switch supervisor from legacy ranking to policy intents | supervisors, policy, execution boundary shims | low runtime if packets are cached | high | end-to-end dry-run tests, cap tests, promoted-sleeve tests | cutover readiness report |
| Daily report and packet upgrades | Upgrade overnight, premarket, and daily reports to consume new packets | `reporting/`, supervisors, CLI | low | low | reporting smoke tests, packet render tests | final operator report |

**First Codex prompt for Lane 3 Batch 1**

```text
Inspect the local TradingAgents repo and prepare Batch 1 only: freeze safety invariants and introduce typed schema scaffolding without changing live behavior. Your job is to (1) map current live-sensitive code paths, especially anything that can reach Alpaca submit paths; (2) add pytest coverage for the hard invariants: research/overnight cannot submit orders, paper tournament cannot submit live orders, live orders must be stocks-only and limit-only, no shorts/options/crypto/margin/market orders, dry-run required before submit, stale/missing data fails closed, unpromoted sleeves cannot live trade, live cap respected, and a run packet must be written for every decision; (3) add schema stubs for candidate, feature, hypothesis, trade intent, risk gate, validation report, paper tournament state, and run packet; (4) wire packet writing in shadow mode only; and (5) produce a handoff report listing files inspected, files changed, uncovered risks, any ambiguous legacy paths, and confirmation that no live behavior changed. Prefer thin wrappers and shims over invasive refactors in this batch. If you find any code path where research or paper logic can reach live submission, stop and flag it explicitly.
```

The short version is blunt: fix methodology before collecting more shiny signals. Right now the repo is at risk of being a very articulate random-trade generator. The redesign above turns it into something far more boring and far more useful: a system that earns the right to trade.