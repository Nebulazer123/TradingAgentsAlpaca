# Codex Handoff Prompt — Court-Conditioned Build

> Paste this whole file to Codex as the governing prompt. It supersedes any looser instruction.
> Reference docs in this repo: `Court_of_Claude_Trading_Bot_Proposal_SECOND_AMENDED.pdf` (intent),
> `CODEX_IMPLEMENTATION_SPEC.md` (module/schema detail), `REPO_OVERVIEW.md`, `TRADING_METHODS_AND_AUTOMATIONS.md`.
> **Primary research (read these — they hold the methodologies, sleeve specs, data sources, and papers):**
> `research/LANE3_methodology_and_sleeves.md`, `research/LANE2_free_alpha_data_sources.md`.
> Section 8 of this file distills them, but the full reports are authoritative for trigger/feature/exit detail.

---

## 0. Mandate

You are implementing a court-approved autonomous equity trading system in this repo
(`TradingAgents-main`, Alpaca-connected). The Court of Claude granted **conditional passage**:
the system passed all five stages, each by the narrowest margin, **not because edge is proven but
because it is a correctly built machine for discovering whether edge exists.** Your job is to build
that machine — and nothing more than that machine — in the order that reaches a first real, tiny,
measured trade with the least operational surface area.

The verdict's own words are the spec: *"Plans are not edge."* *"The most thoroughly documented
zero-trade system ever submitted."* Do not add documentation, sleeves, or cleverness. Reach a
measurable live result on the shortest safe path.

---

## 1. Binding conditions (from the verdict — non-negotiable)

Each Court objection is now a hard rule. Violating any of these fails the build.

1. **Anti-complexity (Prosecution/Tribunal: "solo-operator complexity is the live threat").**
   Build the **deterministic core loop first and alone.** Do NOT build idempotent order systems,
   claim-level LLM verification, family-wise FDR budgets, and live-shadow execution *simultaneously*.
   They are phased (Section 3). Each phase must be independently shippable, independently safe, and
   leave the system in a valid state if you stop there.

2. **LLM is optional and last (Prosecution/Tribunal: "ablation gate may never clear").**
   The deterministic system must be fully functional, testable, and live-capable with the **LLM layer
   entirely disabled.** The LLM layer is a Phase-D add-on that must *earn* its place via ablation or
   stay muted forever. The system's viability must never depend on it clearing.

3. **Quantify capacity in dollars (Analysts: "capacity ceiling declared but no dollar figure").**
   Every sleeve must declare a **numeric** dollar capacity ceiling and max participation rate in
   config, with the reasoning. "Small size is a moat" is not allowed as a sentence; it must be a number.

4. **Measure surviving alpha after decay (Analysts: "PEAD/pullback decay post-publication").**
   You may not assume published anomaly magnitudes. Each sleeve's walk-forward must estimate the alpha
   that **survives in recent data** (most recent ~3 years weighted heaviest) net of the conservative
   cost model. If recent surviving alpha is not positive vs benchmark, the sleeve does not promote.

5. **The system governs itself (Tribunal: "integrity depends entirely on solo-operator discipline").**
   The operator will NOT be in the loop for trades, promotions, or daily operation. All discipline is
   enforced by code and CI, never by the operator remembering. A sleeve physically cannot reach an
   environment it has not earned. The system promotes sleeves, sizes, trades live, pauses, and kills
   itself autonomously within a fixed risk envelope (Section 5A). The operator is contacted by email
   ONLY on exception (Section 5A) — never for routine approval.

6. **Cash-default is sacred (Executioner: "the system's most honest feature").**
   Every decision path can terminate in `HOLD_CASH` with a written packet. Preserve this everywhere.

7. **Free-data honesty (Prosecution: "free data weakness understated").**
   Treat free data as the weakest link. Delisted-name price history is flagged low-quality and excluded
   from sizing. Source-conflict between free feeds excludes the feature. Never present free data as
   institutional grade.

---

## 2. Prime directive

**Reach one real, tiny, measured trade on a single sleeve, through the full gate stack, as fast as
safely possible.** A system that has placed one honest tiny-live trade and measured it beats a system
with ten perfect unbuilt subsystems. Bias every decision toward shrinking time-to-first-measured-trade
without skipping a gate.

---

## 3. Re-sequenced critical path

Build in this order. **Do not start a phase until the prior phase's Definition of Done is green.**
This ordering deliberately front-loads the cheap, safe, high-information work and defers the
complexity the Court flagged.

### Phase A — Deterministic core loop, paper only (no LLM, no heavy stats)

Goal: one sleeve produces typed intents and trades on paper, end to end, deterministically.

- Schemas (`Hypothesis` optional/unused for now, `CandidatePacket`, `FeaturePacket`, `TradeIntent`,
  `RunPacket`) — spec §2.
- Point-in-time feature layer with freshness gating — spec §3 (start with price/volume/ATR/trend/
  support features only; defer SEC/macro).
- One sleeve: **`pullback-support`** (best fit for long-only/limit-only; reaches sample fastest).
  Implement the "good dip vs falling knife" table.
- Deterministic policy engine with the binary conversion rule and `HOLD_CASH` default — spec §9.
- Run through existing `alpaca check → dry-run → submit` on the **paper** account.
- **DoD A:** paper trade placed via the new pipeline; every decision (incl. no-trade) writes a packet;
  golden tests pass (clean dip trades, falling knife blocked).

### Phase B — The gates that decide live-eligibility

Goal: make "is this sleeve allowed near real money?" a computed, frozen answer.

- Pre-registration store (freeze hypothesis/rules/benchmark/min-sample/power) — spec §5.
- Walk-forward OOS with purged folds + embargo + deflated Sharpe — spec §5.
- **Recent-decay alpha estimate** (Condition 4) and **benchmark survival** vs QQQ/SPY after tax + the
  **adversarial cost model** (spec §4). Beta subtracted.
- Numeric **dollar capacity ceiling** per sleeve in config (Condition 3).
- **DoD B:** `pullback-support` has a frozen pre-registration, a walk-forward report showing
  recent-data surviving alpha vs benchmark net of conservative cost, and a stated dollar capacity.
  If alpha does not survive, STOP and report — that is a valid, honest outcome.

### Phase C — Tiny-live, one sleeve

Goal: the first real fills, bounded and measured.

- Operational hardening that *gates live*: idempotency key as `client_order_id`, reconcile-on-start
  (fail closed on mismatch), single-writer lock, clock-skew guard, dead-man switch, documented manual
  kill — spec §11. Build only what's needed to submit one live order safely.
- Live-shadow channel for the sleeve first (never fills), compare modeled vs achievable — spec §8.
- Tiny-live tranche sized so max loss over the test window is a pre-set small fraction of capital and
  is written in config and confirmed by the operator — spec §12.
- **DoD C:** sleeve cleared ladder through shadow-confirmed; tiny-live gate armed; the §13 operational
  tests green; one tiny-live order placed and its packet written.

### Phase D — DEFERRED until A–C are proven (optional, may never happen)

Only after a sleeve has traded tiny-live and been measured:

- LLM advisory layer + claim verifier + Brier calibration + **ablation gate** — spec §6/§7. Muted
  unless it shows significant incremental alpha. The system must keep working if it never clears.
- Additional sleeves (`breakout-continuation`, `underreaction-event-drift` with SEC EDGAR, etc.), each
  re-running Phases B–C independently.
- Family-wise FDR budget across sleeves, regime overlay refinements, portfolio cross-sleeve caps
  (spec §10) — these matter only once more than one sleeve exists.

---

## 4. Quantification requirements (make the Analysts' objection impossible)

For every sleeve, config must contain explicit numbers, not adjectives:

- `capacity_ceiling_usd` and `max_participation_rate` (% of ADV) with a one-line justification.
- `tiny_live_max_loss_usd` and `tiny_live_tranche_usd`.
- `min_independent_trades` derived from a power calculation, plus expected calendar time to reach it.
- `recent_alpha_window` and the measured surviving alpha vs benchmark net of conservative cost.
  A sleeve missing any of these cannot be promoted by the policy engine (enforce in code).

---

## 5. Autonomous self-governance (the operator is not in the loop)

The operator wants the system to **run live on its own, intelligently, 24/7**, and to be emailed **only
when it breaks its own rules and judges the breach important enough to surface.** Build for that.

- Promotion state is persisted per sleeve; the policy engine reads it and **physically cannot** emit a
  live intent for a sleeve below `tiny-live` stage. Promotion happens **automatically** when gates pass —
  no human approval.
- The system trades, sizes, promotes, demotes, pauses, and kills sleeves on its own, continuously,
  within the fixed risk envelope below. Routine activity is silent (local packets only).
- The "no live capital until" checklist (spec §14) is encoded as `tests/test_go_live_guard.py` that
  **fails** (and disables live submission) until every condition is met — this is the machine gating
  itself, not the operator gating it.
- CI runs the full §13 failure-mode → test matrix. Red CI ⇒ live submission auto-disabled.

### 5A. The risk envelope + exception escalation

**One-time arming, then hands-off.** The operator sets the *outer bounds* once in
`config/risk_envelope.yaml` and then steps away. This is configuration, not 24/7 control. Required keys:

```
account_max_capital_at_risk_usd      # hard ceiling the system may never exceed, ever
per_name_cap_usd / per_sector_cap_pct / aggregate_beta_cap
daily_loss_halt_usd / max_drawdown_halt_pct   # auto-halt-all thresholds
tiny_live_tranche_usd / tiny_live_max_loss_usd
new_sleeve_auto_promote: true        # promote without asking
alert_email: nebulazer2003@gmail.com
```

The system operates with full autonomy **inside** this envelope and can never act outside it. If a
config value is absent, fail closed (no live trading) rather than guessing.

**Exception-based alerting — email only when it matters.** Extend the existing supervisor email path
(`notify:true` already exists). The system writes packets for everything but **emails the operator only
when it trips a rule it judges important.** Implement a severity router:

- **CRITICAL (always email):** drawdown/daily-loss halt fired; kill-switch / dead-man switch triggered;
  reconciliation mismatch; broker rejected/again; risk-envelope breach attempt blocked; live submission
  auto-disabled by CI/guard.
- **NOTABLE (email, batched):** a sleeve auto-paused or demoted; a sleeve auto-promoted to tiny-live or
  scaled; capacity ceiling hit; anomalous slippage vs model beyond tolerance.
- **ROUTINE (never email, packet only):** normal trades, holds, cash decisions, quiet ticks.
  The LLM layer — even if muted for *alpha* — MAY be used here as an **ops triage brain**: summarize the
  day, judge whether a borderline event is "important enough" to surface, and write the email body. This
  is allowed because it never sizes or authorizes a trade; it only decides what to tell the human.
- A self-throttle prevents alert storms (e.g. collapse repeated same-cause alerts into one digest).
- Keep the existing daily report as an optional low-noise heartbeat the operator can ignore.

---

## 6. Working rules

- Work in **small batches**; each batch ends with a passing test and, where relevant, a written packet.
- Never weaken the existing safety boundary: stocks-only, long-only, limit-only, dry-run-before-submit,
  fail-closed. You are adding gates, not removing guards.
- **No human-in-the-loop for operation.** The only human touchpoint is the one-time `risk_envelope.yaml`
  arming (Section 5A) and reading exception emails. Do not build per-trade or per-promotion approval
  prompts. Once armed, the system runs, promotes, and trades autonomously inside the envelope.
- If a sleeve's edge does not survive recent-data testing, the system **auto-shelves it and moves on**
  (and logs why). A truthful "no edge here" is a successful outcome of this machine; it should not stop
  the whole system, just that sleeve.
- Prefer deleting scope over adding it. If a feature isn't on the critical path to the next DoD, defer it.

---

## 7. Definition of done (whole project, Phase C)

The build is "done" for its first milestone when ALL hold:

- [ ] `pullback-support` cleared Hypothesis-registered → Backtest-validated → Benchmark-cleared →
  
      Friction-survived → Shadow-confirmed, with recent-data surviving alpha vs benchmark documented.
- [ ] Dollar capacity ceiling, tiny-live tranche, and max-loss are read from `config/risk_envelope.yaml`.
- [ ] Operational hardening verified end-to-end on the paper account (idempotency, reconcile,
  
      single-writer, dead-man switch, manual kill).
- [ ] `tests/test_go_live_guard.py` and the §13 matrix are green.
- [ ] The system **autonomously** promotes a sleeve through the ladder and places tiny-live orders under
  
      the gate stack, with reconstructable packets — no human approval in the path.
- [ ] Exception-email routing works: a forced drawdown-halt and a forced reconciliation-mismatch each
  
      send a CRITICAL email; routine trades send nothing.
- [ ] The system runs correctly with the LLM layer fully disabled (LLM optional for ops triage only).

After this milestone the system continues on its own: it adds and tests further sleeves (Phase D),
promotes what survives, retires what doesn't, and only emails the operator on exception. The Court
granted permission to *learn whether it works* — let it learn, continuously and unattended, inside the
envelope.

---

## 8. Research methodology appendix (distilled from `research/`)

This section makes the handoff self-contained. The full reports
(`research/LANE3_methodology_and_sleeves.md`, `research/LANE2_free_alpha_data_sources.md`) are
authoritative; read them for exact thresholds and edge-case logic. Build sleeves from this, not from
your own invented signals.

### 8.1 Architectural principle (Lane 3)

Rebuild the repo as a **research → paper → live factory**, not a smarter opinion engine. Fixed pipeline:

```
universe_screen -> candidate_packet -> feature_packet -> sleeve_routing
-> optional_llm_hypothesis -> deterministic_sleeve_score -> hard_gates
-> position_sizing -> entry_plan/exit_plan/invalidator -> dry_run
-> submit_or_hold_cash -> immutable_run_packet
```

Candidate rank = **review priority only**, never an order. Agents generate hypotheses; policy authorizes.
If the top-two sleeves are inside the uncertainty band, **hold cash**.

### 8.2 The sleeves (build order: pullback-support first)

| sleeve                             | edge hypothesis                                                                                | trigger                                                                                         | key features                                                                                                                                                       | exit / invalidator                                                                                                                                                                                                |
| ---------------------------------- | ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **pullback-support** (build first) | Controlled retracement inside intact leadership mean-reverts when the move is non-fundamental. | 0.75–2.5 ATR pullback into defined support, intact uptrend, no fresh negative event.            | trend anchors (rising 50/200D), support map, ATR depth, RSI state (bounded, not alpha), sell-volume profile, gap flags, sector RS, regime, earnings/news blackout. | scale out into rebound; full exit on support failure / time stop / regime deterioration. Invalidators: daily close below support, heavy distribution, fresh negative filing, sector breakdown, earnings blackout. |
| breakout-continuation              | Medium-horizon strength persists when stock, industry & 52W-high context align.                | near 20D/52W high after tight consolidation or orderly retest.                                  | 3–12M RS, 20D RS, 52W-high proximity, sector RS, turnover, realized vol, spread, extension-from-anchor.                                                            | time stop + technical failure; exit on failed breakout, fresh negative news, risk-off, gap extension, spread blowout.                                                                                             |
| catalyst-continuation              | Fresh positive catalyst continues when event-day gains are retained and peers confirm.         | positive event day / next-day consolidation with RS + volume retention.                         | event recency/type, gap retention, RVOL, intraday hold/reclaim, peer/sector confirm, spread, regime.                                                               | exit on event-gap failure, time decay, target; invalidate on event-day midpoint loss, negative follow-up, sector contradiction.                                                                                   |
| underreaction-event-drift          | Public info absorbed gradually; muted initial reaction can drift further.                      | positive public info (8-K, Form-4 insider cluster) with incomplete repricing, no contradiction. | event classification, surprise severity, first-day response, post-event drift, sector/peer confirm, freshness.                                                     | shorter holding window; exit on drift decay, contradiction, stale event packet.                                                                                                                                   |
| cash-default                       | Optionality beats forcing weak evidence.                                                       | no sleeve passes / ambiguous / stale / unpromoted.                                              | gate outcomes, uncertainty band, stale flags, caps.                                                                                                                | n/a — policy fallback, never "promoted".                                                                                                                                                                          |

**Pullback "good dip vs falling knife" filter (reference logic):** good dip = above rising 50/200D, lands
in a precomputed support zone, 0.75–2.5 ATR depth, decelerating sell volume, small/reclaimed gap, stock
still outperforms sector, regime risk-on/neutral, no earnings/negative filing. Falling knife (BLOCK) =
below falling 200D or broken breakout, no clean support level, >3 ATR without reclaim, expanding down
volume, large open gap, sector breaking down, earnings blackout, or fresh negative filing. Note
(Collin-Dufresne & Daniel): temporary shocks reverse with a ~2.5-day half-life — a valid dip should show
evidence quickly; do not let dip-buys linger as philosophical positions.

### 8.3 Overlays (NOT standalone sleeves)

- **Regime/macro = permission + size, not alpha.** Throttle/pause momentum sleeves in risk-off/panic
  (Daniel & Moskowitz: crashes cluster there).
- **Sector/peer confirmation = universal overlay.** A long thesis without sector confirmation is lower
  quality by default (Moskowitz & Grinblatt industry momentum).

### 8.4 Deterministic position sizing (multiplicative; vol scales DOWN only)

```
final_risk = base_risk_by_sleeve * regime_mult * confidence_mult(features only)
           * volatility_mult * liquidity_mult * sleeve_stage_mult * live_cap_residual
```

Moreira & Muir: cut risk when volatility is high (vol is forecastable, returns are not). Live size starts
far smaller than paper size; initial live ADV caps materially tighter (Alpaca paper does not model queue
position, impact, or slippage).

### 8.5 Paper-tournament scoring (score setup quality, not luck)

```
setup_score = trend_quality + support_confluence + sector_confirmation + regime_fit - blackout_risk - knife_risk
trade_score = realized_R + favorable_excursion_bonus - adverse_excursion_penalty - gap_penalty - invalidator_breach_penalty
promotion_score = median(trade_score) * packet_integrity * drawdown_discipline * environment_stability
```

This stops a sleeve from getting promoted because a few ugly names happened to bounce.

### 8.6 Free data sources (Lane 2) — official, legal, testable; SEC-first

| Source                                                                                                  | Use                                                        | Priority / constraint                               |
| ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | --------------------------------------------------- |
| SEC EDGAR submissions + daily index + RSS                                                               | 8-K / 13D-G / ownership event scanner, filing freshness    | P1; ≤10 req/s, descriptive User-Agent               |
| SEC XBRL companyfacts/companyconcept                                                                    | structured fundamentals, quality gates, post-filing deltas | P1                                                  |
| SEC Form 4 (insider)                                                                                    | insider-buy / cluster-buy support for event-drift sleeve   | P1; raw filings timely, flattened dataset quarterly |
| Alpaca Basic + calendar + corporate actions                                                             | execution context, trading-day alignment, splits/divs      | P1; IEX-only real-time, not full SIP                |
| FRED + ALFRED (vintages)                                                                                | point-in-time macro regime features                        | P1; free key                                        |
| ETF issuer holdings (SSGA/iShares/Invesco)                                                              | sector/peer context, rebalance awareness                   | P1; no uniform API, brittle                         |
| 13F datasets                                                                                            | slow sponsorship context only                              | P2; 45-day lag — never an entry trigger             |
| Reddit API (narrow) / Alpha Vantage (25 req/day)                                                        | thin supplemental flags only                               | P3                                                  |
| yfinance / Stooq                                                                                        | prototype/backfill only — unofficial, weak legally         | P4; not a production backbone                       |
| **Avoid as core feeds:** copying third-party strategies via marketplaces (hands over broker creds),     |                                                            |                                                     |
| Stocktwits sentiment (enterprise-gated), 13F as timing. **Free-data honesty (Condition 7):** delisted   |                                                            |                                                     |
| price history from free sources is the weak link — flag low-quality, exclude from sizing, keep for bias |                                                            |                                                     |
| audit.                                                                                                  |                                                            |                                                     |

### 8.7 Academic basis (cite in pre-registration persistence arguments)

Jegadeesh & Titman (3–12M momentum); Moskowitz & Grinblatt (industry momentum); George & Hwang
(52-week-high anchoring); Daniel & Moskowitz (momentum crashes cluster in panic/rebound); Moreira & Muir
(volatility-managed portfolios); Collin-Dufresne & Daniel (~10% temporary shocks, ~2.5-day half-life);
Bailey & López de Prado (PBO, Deflated Sharpe Ratio). **Decay caveat (Analysts):** PEAD and short-term
reversal are heavily documented and have decayed since publication — measure surviving recent-data alpha
net of conservative cost (Condition 4); do not assume the original effect sizes.

### 8.8 Reference packet schemas

Exact JSON/YAML for `pullback_support_section`, `pullback_support_watch`, the agent `Hypothesis` contract,
and `CandidatePacket` are in `research/LANE3_methodology_and_sleeves.md` ("Pullback support redesign" and
"Schemas and deterministic policy"). Use them verbatim as the v1 schema shapes.

your honor. 
