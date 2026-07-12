# TradingAgents Improvement Program

Generated: 2026-06-03

Six prioritized, handoff-ready Codex workstreams (P0–P5) for raising the
performance ceiling of TradingAgents. Each workstream is self-contained: dispatch
one per Codex chat, **prepend the Shared Preamble** below to whichever you run.

## Baseline (verified by repo sweep 2026-06-03)

This is a healthy, mature system - ceiling-raising, not repair:

- 662 tests pass, 1 live-key test is skipped when the key is absent, 75 subtests pass, and there are **zero import errors** in the latest full regression (~5 min on this machine).
- Deterministic signal extraction (`graph/signal_processing.py` + `agents/utils/rating.py`); the fragile LLM-parse was already removed.
- Strong safety posture: `policy/` gates, `LEDGER_FORBIDDEN_EFFECTS`, advisory-only self-heal, `alpaca check -> dry-run -> submit` discipline.
- Working forward feedback loop: `evals/agent_intelligence_ledger.py` + `graph/reflection.py`.

2026-06-03 late audit update: a submit-capable hourly supervisor run closed the
live ORCL position during the real simulation audit before the loss-exit rule was
tightened. The order filled, so future audits must not rely on "market closed" as
safety. The patched supervisor no longer turns a drawdown threshold into a live
sell by default: it emits `decision="loss-review"` with `actions=[]` unless the
position carries explicit thesis-break / invalidator / capital-reuse evidence.
The execution BOARD recommendation `review_underperformers_before_new_buys` now
pauses new live buys while keeping paper/research lanes active. The proof audit
after the loss-review, MiroFish, self-heal-timeliness, and BOARD patches is
`results\real_simulation_audits\real-simulation-audit-20260603-192427.json`:
25 department commands, failed 0, submitted 0, blocker count 0, Mac Ollama
`deepseek-r1:14b` reachable, 115 stale sources all safely downranked/low-quality
flagged. The paired automation-health proof
`results\automation_health\automation-health-audit-20260603-191840.json` shows
`timeliness_issue_count=0`, `late_count=0`, `missing_count=0`, and
`partial_count=0`; self-heal handoff plus safe execution proved that safe fixes
can run in the ordered handoff -> plan -> execute-safe -> verify path without
waiting for a human or relying on a fake hook.

2026-06-05 overnight/self-heal update: the real overnight gap was a scheduler
evidence problem plus a missed run. `automation_health_audit` had incorrectly
treated `tradingagents-overnight-planning` as wake-controller-dependent, so a
scheduled 2:30 AM Central miss was masked by older controller/memory evidence.
Overnight planning is now due-aligned and filtered to artifacts generated after
the settled due window. A real catch-up produced
`results\overnight_plans\overnight-plan-20260605-101740-000000.json` with
3/3 Google full-graph successes, top five `KO`, `IBM`, `HD`, `CVX`, `XOM`, and
zero submissions; `results\overnight_system_verification\overnight-system-verification-20260605-051922.json`
passes. Self-heal now treats compact `reason=automation_health` as a medium safe
signal, runs the real allowlisted `automation-health-audit` verification command,
writes verified plan
`results\self_heal\plans\self-heal-plan-20260605-102632.json`, and dedupes the
same signature on the next monitor cycle. Remaining watch item: wake-controller
and night-shift memories are stale, but overnight planning itself is `ok`.

2026-06-06 compact overnight-quality update: the raw overnight packet already
proved a complete Google-routed original-graph run, but compact context did not
surface enough of that nested `overnight_quality` contract. The snapshot now
publishes `completion_status`, `completion_reasons`, graph limit/attempt/success
counts, fallback/failure counts, research-context packet/block counts, and graph
model-route/provider/model fields directly in `results\_context\latest-summary.json`,
with provenance in `results\_context\field-provenance.json` back to
`overnight_quality.*`. Real refreshed context shows `completion_status=complete`,
3/3 graph successes, 13 research-context packets, 0 blocked research-context
packets, Google route `explicit_google_overnight_graph`, and no overnight
drilldown flag. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py -q`
passed with 33 tests, targeted Ruff passed, and
`python scripts\automation_context_snapshot.py --write` refreshed the real
context artifacts.

2026-06-06 automation-health Saturday/no-market update: the health audit was
treating Saturday 02:30 local overnight-planning as a missed run even though the
 slot does not prepare a useful U.S. regular-session market morning. The audit now
 filters that Saturday-only overnight due while preserving Sunday and Monday-
 Friday due checks. `tradingagents-overnight-planning` was also reactivated after
 app/disk state showed it was paused. Real observer packets refreshed wake, sleep,
 night-shift, self-heal handoff, and self-heal plan evidence; latest health proof
 `results\automation_health\automation-health-audit-20260606-192741.json` shows
 wake/sleep/self-heal/overnight `ok`, overnight `config_status=ACTIVE`,
 self-heal follow-up lag `37s`, no missing/stale/late jobs, no self-heal
 timeliness issue, and zero submitted orders. The remaining `partial` is
 `tradingagents-night-shift-supervisor`, because only one patrol packet exists in
 the six-window lookback; that is continuity history filling in, not an overnight
planning blocker. Fresh overnight verifier
`results\overnight_system_verification\overnight-system-verification-20260606-141132.json`
is `overall_status=pass` and records `validation_skipped=true` plus
`skip_reason=saturday_no_regular_market_morning`; Sunday/Monday-Friday overnight
checks still count. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py::test_verify_overnight_system_audits_full_chain tests/test_automation_health_audit.py tests/test_automation_context_snapshot.py -q`
passed with 59 tests and targeted Ruff passed.

2026-06-06 current BOARD/Saturday overnight-evidence refresh: the latest BOARD
packet is now
`results\execution_board\execution-board-review-20260606-193832.json`, not the
older June 5 proof. It reviewed through the current hourly loss-review packet
`results\hourly_supervisor\hourly-supervisor-20260606-193752-094749.json`;
BOARD remains analysis-only with zero submitted orders, zero hard violations,
one negative-live-P/L warning, and `new_buy_state=caution`. This is a current
manual-review signal, not a stale BOARD artifact. The same real hourly dry-run
now records `evidence.overnight_plan.status=not_required`,
`validation_skipped=true`, and
`skip_reason=saturday_no_regular_market_morning` on Saturday instead of a false
stale overnight warning; Sunday and weekday freshness checks still enforce
staleness. Compact context now carries the human-readable BOARD/self-heal proof
needed to avoid raw-packet reads:
`board_hard_issue=false`, `latest_packet_decision=loss-review`,
`latest_packet_needs_review=true`, `negative_live_pl_packets=24`,
`warning_types=["negative_live_unrealized_pl"]`, independent buy/sell policy
text, and self-heal classifications showing automation-health as `safe_autofix`
while hourly/BOARD review remain `escalate_order_adjacent`. The real dry-run
loss-review email now scores 100 in `email_clarity_eval` with 24 lines, no
issues/warnings, and no pasted blocker checklist in the inbox. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py::test_overnight_validation_confirms_amends_invalidates_and_ignores_stale tests/test_alpaca_supervisor.py::test_overnight_validation_retains_recent_plan_on_saturday_no_market tests/test_alpaca_supervisor.py::test_overnight_validation_enforces_sunday_freshness -q`
passed, targeted Ruff passed, real hourly dry-run submitted zero orders, BOARD
refreshed with zero hard violations, and
 `results\process_reviews\process-review-20260606-195734.json` has
`unchecked_step_count=0`.

2026-06-06 loss-review evidence/n8n observer update: the current TSM
loss-review now has its own analysis-only evidence packet instead of forcing
BOARD/humans to reason from a raw hourly blocker checklist. `research
loss-review-evidence --json-output` refreshes quote/news/fundamentals/earnings
provider evidence for the latest loss-review, writes
`results\loss_review_evidence\latest.json`, preserves `review_allowed=false`,
and keeps `can_submit_orders=false` / `execution_authority="none"`. The packet
now separates `remaining_blockers_before_refresh`,
`resolved_blockers_by_refresh`, and post-refresh `remaining_blockers`, so
refreshed evidence clears stale "missing evidence" blockers without pretending
the sell is approved. Current real proof for `TSM` shows
`remaining_blockers_before_refresh_count=13`, `resolved_blocker_count=3`, and
`remaining_blocker_count=10`; the resolved items are source IDs,
company-specific news, and earnings/guidance/filing evidence. The remaining
items are true BOARD/session blockers around thesis status, HOLD-vs-SELL
reasoning, loss-exit confidence, and the closed market. The n8n
allowlist now exposes the same path as `loss_review_evidence` with
`submit_capable=false`; the real runner returned `status=ok`,
`review_allowed=false`, the same blocker deltas, and 7 source packet paths.
Compact context flags the packet for `board_review`, and the n8n built-in eval
dataset now covers 20 allowlisted jobs, 183 rows, and 17 edge tags with
`submit_capable_count=0`.

2026-06-06 overnight calibration guard update: the weak real walk-forward cohort
now drives an explicit analysis-only guard. `research
overnight-calibration-guard --json-output` writes
`results\overnight_calibration\latest.json`; the latest n8n bridge proof is
`results\overnight_calibration\overnight-calibration-guard-20260606-214537.json`.
Current decision is `guard_decision=tighten`,
`can_increase_live_influence=false`, `can_submit_orders=false`, and
`execution_authority=none`. Treat this as the durable P2 instruction: overnight
research may select and explain candidates, but it must not gain additional
live influence until later resolved cohorts improve. Keep controlled-dip/support
or reclaim confirmation, reject green-spike chase entries, downrank crowded
AI-bot/broker-friction names without independent confirmation, and keep paper
exploration collecting mature samples. n8n now exposes this as the
`overnight_calibration_guard` observer job; the synced built-in evaluation table
has 192 rows across 21 allowlisted jobs with proof
`results\n8n_evaluations\n8n-api-sync-20260606-214513-899863.json`.

2026-06-06 self-heal reverify update: durable self-heal signature dedupe now has
a time-bound reverify path. Immediate repeats still dedupe, but a persistent
safe-plane signal after the default 15-minute SLA becomes a planned verification
again with `reverify_reason=persistent_safe_autofix_after_sla`. The CLI exposes
`--safe-reverify-minutes` for automation policy and real tests. Forced proof
`research self-heal-plan --execute-safe --safe-reverify-minutes 0 --json-output`
wrote `results\self_heal\plans\self-heal-plan-20260606-221514.json`, ran the
allowlisted automation-health audit, and recorded `executed_count=1`,
`verified_count=1`, `verify_failed_count=0`, `can_submit_orders=false`, and
`execution_authority=none`. Hourly and execution BOARD signals stayed
`escalate_order_adjacent`, so the repair does not create order, email, goal, or
automation-status authority. Current health remains a real night-shift continuity
watch item at `3/6` observed patrols, not a hidden self-heal failure.
Verification passed with focused self-heal/context tests, CLI packet-coverage
regressions, Ruff, `py_compile`, process review
`results\process_reviews\process-review-20260606-222118.json` with
`unchecked_step_count=0`, and full pytest `937 passed, 1 skipped, 9 warnings,
75 subtests passed`.

2026-06-06 night-shift self-heal repair update: the previous watch item is no
longer just a rechecked audit. `orchestration/self_heal.py` now treats the
`automation_health` safe action as a two-step allowlisted repair: write an
analysis-only `research night-shift-patrol --json-output` packet, then rerun
`research automation-health-audit --json-output`. The audit also de-noises
night-shift lookback history when the latest due slot is covered, while still
leaving a true `partial` if the latest due slot has no packet. Real forced proof
`research self-heal-plan --execute-safe --safe-reverify-minutes 0 --json-output`
wrote `results\self_heal\plans\self-heal-plan-20260606-225530.json`,
`results\night_shift_patrol\night-shift-patrol-20260606-225524.json`, and
`results\automation_health\automation-health-audit-20260606-225529.json`; the
latest audit has `ok_count=13`, `partial_count=0`,
`submitted_order_count=0`, and night-shift
`status_reason=night_shift_latest_due_covered_history_ramp_up`. Compact context
now opens only BOARD/loss-review flags, not automation health. Focused proof:
`tests/test_self_heal_handoff.py` plus `tests/test_automation_health_audit.py`
passed with 46 tests, targeted Ruff passed, process review
`results\process_reviews\process-review-20260606-225623.json` has
`unchecked_step_count=0`, and context artifacts were refreshed.

2026-06-07 n8n overnight source-quality preview update: the n8n
`overnight_plan_compact_preview` wrapper no longer refreshes source quality and
then disables the research-context path that proves source-quality routing. It
still cannot submit or mutate latest pointers: the allowlisted plan step uses
`--no-write-latest`, `--no-agent-ledger`, zero full-graph tickers, zero model
time budget, and `--top-provider-bundle-count 0`, while keeping
`--source-quality-review-path results/source_quality/latest.json` and
`--source-quality-ordering`. Real proof
`results\overnight_plans\n8n\overnight-plan-20260607-231000-000000.json` has
`analysis_only=true`, `submitted=[]`, 40 ranked candidates, top `XOM`, 14
research-context packets, and
`research_context.watchlists.source_quality.source_quality_ordering_enabled=true`
with 250 sources reviewed, 25 stale downranked, and 0 stale requiring refresh.
n8n job discovery still reports 24 allowlisted jobs and
`submit_capable_count=0`. Focused proof: n8n/provider/source-quality tests
passed with 85 tests, Alpaca overnight CLI slice passed with 19 tests, JSON
allowlist parse passed, targeted Ruff passed, and process review
`results\process_reviews\process-review-20260607-231502.json` has
`unchecked_step_count=0`.

2026-06-05 MiroFish/report-33 scoring update: the report-33 event-sensitive
broker/fintech watch names `HOOD`, `BULL`, `IBKR`, and `SCHW` are now in the
candidate universe, but MiroFish `suppress` gates penalize unconfirmed broker-
friction/social-flow setups until broker/flow or institutional confirmation
appears. Ranked fallback rows now expose human-readable market `reason` plus a
separate `fallback_reason`. Real no-latest/no-submit proof:
`results\overnight_plans\mirofish_score_probe\overnight-plan-20260605-103822-000000.json`
ranked `KO`, `IBM`, `HD`, `CVX`, and `XOM` as controlled-dip quality/energy/
defensive relative-bias ideas while downranking `SCHW`, `IBKR`, `AMD`, `HOOD`,
and `BULL` under MiroFish/report-33 false-signal controls.

Historical gaps the program targeted (with evidence): no static analysis on
~24K LOC; data connectors had **0 retry/backoff, 0 429-handling, timeouts on
only ~6 sites**; no offline backtest (the `backtrader` dep was unused);
`RATING_PROBABILITY` is hardcoded; `brokers/alpaca_supervisor.py` is a
2657-LOC monolith; result-packet/doc token sprawl; the analyst **decision** path
wired only 2 of ~20 connectors (`dataflows/interface.py`); and self-heal only
*advised* fixes. Static analysis, connector transport/routing, MiroFish status
ingestion, and bounded safe self-heal now have checkpoints below; offline
walk-forward/calibration, supervisor decomposition, token compression, and
remaining pipeline roadmap items still need continued work. See the **Connector
Leverage Audit** and workstream **PA** below.

## Connector Leverage Audit (2026-06-03)

Connectors mostly **work**, and the original audit gap has been reduced but not
fully retired: strong, paid-for sources now reach more of the decision/research
surface, while a few specialized paths remain advisory or gap-tracked.

- **Original gap, now partially closed:** `dataflows/interface.py`
  originally wired only **yfinance** (default) + **alpha_vantage** (fallback).
  The current decision price chain is `yfinance -> tiingo -> massive ->
  alpha_vantage`, and fundamentals/news/macro/social enrichment routes now feed
  the research and analyst context where bounded and appropriate.
- **Still not "everything into every analyst":** finnhub, fmp, eodhd,
  marketaux, newsapi, google_news, sec_edgar, fred, bls, bea, eia, treasury,
  reddit, stocktwits, options/IV, transcripts, and short-interest evidence are
  routed by authority and quality. Some remain analysis-only or
  confirmation/downrank-only by design.
- **Fallback bug fixed at the router boundary:** known vendor error/no-data
  strings and transient failures now advance fallback instead of pretending a
  failed payload is useful evidence.
- **Macro is visible to research and context packets:** FRED/BLS/BEA/EIA/
  Treasury remain analysis/context inputs rather than direct order authority,
  which fits the June 4-13 macro thesis without over-wiring macro data into
  trade submission.

**Target routing — route each category to its strongest already-keyed source, only where that source is the right authority (not every source on every analyst):**

| Category | Today (decision path) | Best-path target (already keyed) |
| --- | --- | --- |
| Price/OHLCV + indicators | yfinance / AV | keep yfinance; add tiingo + massive as fallbacks |
| Fundamentals / estimates | yfinance fundamentals (weak) | SEC EDGAR + FMP/EODHD (real filings, estimate revisions) |
| News | yfinance news | marketaux + finnhub + newsapi + google_news (merge/dedup) |
| Macro context | none (research only) | FRED + BLS + BEA + Treasury → new macro tool for market/news analysts |
| Sentiment / social | none (research only) | reddit + stocktwits → sentiment/social analyst |
| Insider / institutional | AV/yfinance insider | SEC Form 4 / 13F enrichment |

**Missing connectors / recommended new paths:**
- **Options / IV / flow** (0DTE, gamma, expiry) — no dedicated connector; directly relevant to the MiroFish options-microstructure thesis. Add via Massive/Polygon options (or a dedicated options vendor) → new options-context tool for market/risk analysts.
- **Earnings calendar + transcripts** — partial in finnhub/fmp; wire into fundamentals/news analysts.
- **Short interest / borrow** — via SEC/FMP; relevant to squeeze/meme branches.

Workstream **P1** below now covers BOTH transport resilience AND this re-routing/leverage fix.

## How to use

- One workstream per Codex chat. Prepend the Shared Preamble.
- Independent except: P0 should land first (de-risks edits); P4 is **gated** on the real MiroFish run completing.
- Suggested dispatch order: **P0 → P1 → PA → (P3 ∥ P2) → P5 ongoing → P4 when MiroFish lands.**
- Nothing here submits, sizes, or promotes orders. MiroFish output stays advisory-only and is never order-wired.

---

## Shared Preamble (paste at the top of each prompt)

```
Repo: C:\Users\Corbin\Documents\Coding projects\TradingAgents-main
Read CONTEXT_ROUTER.md and AGENTS.md first. Honor repo rules:
- Targeted tests via: uv run --with pytest python -m pytest <files> -q  (latest full suite is 662 tests / ~5 min)
- Do NOT read .venv/, uv.lock, or results/ packets wholesale; start from results/_context/latest-summary.json.
- Order-affecting paths keep the gate: alpaca check -> dry-run -> submit only if clean. This task does NOT submit orders.
- No secrets in files. Keep chat report compact (what changed, paths, status, verify cmd, next step); put detail in repo files/result packets.
- Write your own concise execution goal (<2,500 chars) at the top of your response, then follow it. Don't overbuild; patch existing structures.
```

---

## P0 — Foundation hygiene (do first; de-risks P1/P2)

```
MISSION: Add static analysis + reconcile connector reality + kill dead deps. No behavior change.

1. Static analysis (repo-local baseline now exists on ~24K LOC touching a brokerage):
   - Add [tool.ruff] and [tool.mypy] to pyproject.toml.
   - mypy: broad broker/policy/execution/dataflow baseline must pass; strict mode is enforced on the current typed frontier and should expand one legacy module at a time.
   - ruff: enable E,F,I,B,UP,SIM; line-length matching current style; fix only safe autofixes this pass.
   - Add a make/uv target and document in CONTEXT_ROUTER.md testing section.

2. Reconcile dataflows/integration_registry.py DEFAULT_INTEGRATIONS with actual code + .env.example:
   - MISSING data connectors that exist as modules: eodhd (has EODHD_API_TOKEN in .env.example), reddit, stocktwits, treasury_fiscal.
   - MISSING model providers that exist in llm_clients + .env.example: anthropic, deepseek, qwen(dashscope/DASHSCOPE_API_KEY), glm(zhipu/ZHIPU_API_KEY), minimax, xai.
   - Add each with correct category/cost_tier/route/authority/fallback_behavior following existing entries. Keep secrets-redacted, execution_authority="none".
   - Add a test asserting every dataflows/*.py vendor module and every llm_clients provider has a registry entry (prevents future drift).

3. Dead-weight:
   - Remove backtrader from pyproject.toml dependencies (0 imports) UNLESS P2 will use it (it won't; P2 replays the live graph).
   - Fix requirements.txt (currently the single char "."): either generate from uv.lock or delete and point docs at pyproject + uv.lock.

VERIFY: ruff check + broad mypy baseline + strict typed-frontier mypy; new registry-coverage test passes; full suite still green; `tradingagents` CLI still imports/launches. The first naive strict-all run exposed 335 legacy annotation errors, so strictness is intentionally phased instead of hidden.
DELIVER: files changed, ruff/mypy result counts, registry entries added, dep changes, verify output.
```

2026-06-03 checkpoint: P0 foundation hygiene is implemented. `pyproject.toml`
now declares the `static-analysis` dependency group, Ruff is configured for
`E,F,I,B,UP,SIM`, broad mypy is an enforceable broker/policy/execution/dataflow
baseline, and strict mypy covers the typed frontier
(`integration_registry`, execution clock/lock, live control, compact policy
packets, risk posture, default config, crawler policy). `requirements.txt` is no
longer the stale single-character file; it points legacy pip users at editable
install while documenting the uv/static-analysis commands. `backtrader` is
removed from project dependencies because P2 replays the live graph instead of
introducing a separate backtrader engine. Integration registry coverage tests
now require every dataflow vendor module and every keyed LLM provider to have a
no-secret registry entry with `write_authority="none"` and
`trading_authority="none"`. Fresh proof after the cleanup:
`uv run --no-sync --group static-analysis ruff check` passed;
`uv run --no-sync --group static-analysis mypy tradingagents/brokers
tradingagents/policy tradingagents/execution tradingagents/dataflows` passed
with 52 source files; strict frontier mypy passed with 8 source files; focused
registry/live-gate/n8n/simulation tests passed with 63 tests.

---

## P1 — Connector resilience, correct routing & health telemetry ⭐ (highest leverage on data quality)

```
MISSION: Make every external data connector resilient and observable. Today errors drop a source for the whole run with no retry, silently degrading analyst decisions.

EVIDENCE (grep across tradingagents/dataflows): retry/backoff = 0, 429/rate-limit handling = 0, timeout= on only 6 sites. A shared layer already exists in dataflows/_official_common.py (get_json :167, post_json :189: Session + timeout, but no retry/limit), used by the official macro/filings sources only. Vendor modules (finnhub, fmp, eodhd, marketaux, newsapi, tiingo, massive, alpaca_news, google_news, alpha_vantage*) call requests directly and bypass it. A provider fallback policy exists but only switches sources; it never retries the failed one.

TASK (smallest reliable, reuse the existing layer):
1. Harden the shared client in _official_common.py (or factor a dataflows/http.py the official funcs delegate to):
   - per-call timeout (already present) + connect/read split
   - exponential backoff w/ jitter on transient errors (connection, 5xx)
   - 429-aware: honor Retry-After; token-bucket/min-interval per host
   - per-source circuit breaker (open after N consecutive failures, half-open probe) so a depleted free-tier source fast-fails to fallback instead of stalling the run
   - keep existing caching (official_cache_key/_cache_path) and redaction
2. Migrate the direct-requests vendor modules onto the shared client. Do it incrementally; one module per commit; keep each module's public function signatures unchanged.
3. Per-connector health telemetry: record calls, errors, 429s, p50/p95 latency, fallback rate, last_success, cache_hit_rate -> compact JSON under results/_context/ (one row per connector, secrets-redacted). This is the observable "connector usage & strength" view.
4. Strength-aware routing: have analyst data tools (tradingagents/agents/utils/agent_utils.py + core_stock_tools / news_data_tools / fundamental_data_tools) pick the strongest AVAILABLE source using evals/source_quality.py scoring, and degrade gracefully (never fail the analyst because one vendor 429'd).
5. Fix routing/leverage (see Connector Leverage Audit): the decision path only uses yfinance+alpha_vantage. Promote the best already-keyed source per category INTO dataflows/interface.py VENDOR_METHODS + config data_vendors/tool_vendors: fundamentals -> SEC EDGAR + FMP/EODHD; news -> marketaux+finnhub+newsapi+google_news (merge/dedup); price/indicators -> keep yfinance, add tiingo/massive fallbacks. Add a macro-context tool (FRED/BLS/BEA/Treasury) and a sentiment tool (reddit/stocktwits) to the market/news/sentiment analysts. Wire each source ONLY where it is the right authority for that category; do not bolt every source onto every analyst.
6. Broaden fallback: route_to_vendor (interface.py:159) only fails over on AlphaVantageRateLimitError. Make the fallback chain trigger on ALL transient errors (timeout/connection/5xx/429/empty), in measured-strength order, behind the P1 circuit breaker — one vendor error must never kill a tool call.
7. Surface gaps: have the telemetry packet flag categories with no strong source (options/IV, earnings transcripts, short interest) so missing paths are visible, not silent.

DO NOT: add a new HTTP framework; rewrite analyst prompt logic; alter the order path. (Adding best-source tools/vendors to existing analysts and widening the vendor map IS in scope.)
VERIFY: a fault-injection test (mock 429 + timeout + 5xx) proving backoff -> success, breaker open -> fallback, Retry-After honored; telemetry packet renders for a sample run; full suite green.
DELIVER: files changed, list of migrated vendors, telemetry packet path + sample, fault-injection test results.
```

2026-06-03 checkpoint: the P1 transport/telemetry slice is implemented and
verified. `tradingagents.dataflows._official_common` now provides shared
retry/backoff, 429 `Retry-After` handling, circuit-breaker accounting, and
compact connector-health output under `results/_context/connector-health.json`.
Direct research/data HTTP bypasses were migrated: Google News RSS,
ScrapingBee, Alpha Vantage common, AlphaInsider, Reddit public search, and
Stocktwits public streams now use the shared helper. A fresh bypass scan over
`tradingagents/dataflows` and `tradingagents/research` only found the shared
client itself. The Alpaca broker transport remains separate by design because
it is account/order infrastructure, not a research-source connector. Verified
with `tests/test_alphainsider.py tests/test_reddit_dataflow.py
tests/test_official_dataflows.py`, targeted Ruff, and dataflows/AlphaInsider
mypy. The decision-path leverage/routing slice also now promotes the already
available authority sources into the analyst graph: fundamentals route through
FMP/EODHD/Finnhub fallbacks, news routes through Marketaux/Finnhub/NewsAPI/
Google News/etc., price routes through yfinance/Tiingo/Alpha Vantage, and new
read-only `get_macro_context` plus `get_sentiment_context` tools expose FRED/
BLS/BEA/Treasury and StockTwits/Reddit/EODHD to market, news, and social
analyst tool nodes. The source-routing context packet now includes
`macro_context` and `sentiment_data`, is marked `analysis_only=true`, and
`can_submit_orders=false`. Verification after this slice:
`tests/test_decision_vendor_adapters.py tests/test_dataflows_interface.py
tests/test_dataflows_config.py tests/test_graph_tool_routing.py
tests/test_integration_registry.py
tests/test_automation_context_snapshot.py::test_snapshot_summarizes_source_routing_gaps_without_flagging_healthy_routes`
passed with 26 tests, Ruff passed on changed routing/tool files, dataflow mypy
passed, context refresh wrote `results/_context/source-routing.json`, and
`research process-review` wrote
`results\process_reviews\process-review-20260603-165211.json` with
`unchecked_step_count=0`. Follow-up proof: `get_news` and `get_global_news`
now use bounded `merge_dedup` routing instead of first-success-only, preserving
fallback behavior for empty/transient-broken vendors while collecting multiple
usable news blocks and deduping repeated lines before analyst injection. The
source-routing packet exposes `routing_mode`, `merge_max_sources`, and
`merge_max_chars` for these methods. Verification:
`tests/test_decision_vendor_adapters.py tests/test_dataflows_interface.py
tests/test_dataflows_config.py tests/test_graph_tool_routing.py
tests/test_integration_registry.py
tests/test_automation_context_snapshot.py::test_snapshot_summarizes_source_routing_gaps_without_flagging_healthy_routes
tests/test_source_quality.py` passed with 34 tests, Ruff passed, dataflow mypy
passed, and compact context refresh wrote merge metadata to
`results/_context/source-routing.json`. Follow-up proof also promotes the
previously silent missing categories into analysis-only ticker-provider packets:
`earnings_transcripts`, `short_interest`, and `options_iv_flow` are default
provider-bundle needs. `options_iv_flow` now tries supplemental public
`dataflow:yfinance_options` evidence before the gap packet, with low source
authority and advisory-only `execution_authority=none`. `short_interest` now
tries supplemental public `dataflow:yfinance_short_interest` metadata before
the gap packet; metadata-only responses with no real short-interest fields are
rejected and fall through to `short_interest_gap`. `earnings_transcripts` now
tries optional FMP transcript evidence before the gap packet; missing keys, plan
limits, or missing transcript text fall through to `earnings_transcripts_gap`
with `blocked=true`, `downrank_evidence=true`, and
`execution_authority=none`. Remaining P1 lift: improve dedicated transcript
connectors when available.

2026-06-06 fallback verification refresh: Claude's older note that
`route_to_vendor` only failed over on `AlphaVantageRateLimitError` is stale for
the current working tree. `tradingagents/dataflows/interface.py` now treats
`AlphaVantageRateLimitError`, official-data errors, request/connection errors,
timeouts, empty payloads, and vendor error strings as fallbackable while
preserving non-transient programming errors. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_dataflows_interface.py -q`
passed with 10 tests, including timeout fallback, empty-result fallback,
vendor-error-string fallback, merge/dedup news routing, macro/social fallback,
and non-transient error preservation.

2026-06-05 source-strength ordering checkpoint: ticker provider bundles now
optionally read `results/source_quality/latest.json` and route candidate
providers by measured source strength before cost tier. Source-quality reviews
record `blocked_count`, and blocked sources are penalized so a provider that
returns fresh-looking blocked packets no longer looks healthy. The CLI enables
this by default when the review file exists and exposes
`source_quality_ordering` plus per-attempt `source_quality_score` /
`source_quality_reason` in bundle summaries. Real proof:
`results\source_quality\source-quality-review-20260605-080800.json` reported
`source_count=250`, `stale_count=96`, `blocked_count=65`, and
`stale_needs_refresh_count=0`; `research ticker-provider-bundle --symbol KO
--evidence-needs market_news --max-packets-per-need 2 --json-output` wrote
`results\research_evidence\source-evidence-source-evidence-73f035b4ea7d47af86fd34ce55c9be7f.json`
with `source_quality_ordering.enabled=true` and selected cache plus fresh local
`reddit_watchlist` before burning blocked limited APIs. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q tests/test_source_quality.py
tests/test_research_provider_orchestrator.py` passed with 35 tests; targeted
Ruff passed.

2026-06-06 blocked-provider quota checkpoint: ticker provider bundles now record
blocked limited/paid provider packets as route attempts without letting them
consume the usable packet quota. Connected-MCP/broker diagnostic blocked packets
and explicit local research-gap packets are still allowed to satisfy a need
because the blocked status is itself the useful evidence. Real KO proof:
`results\research_evidence\source-evidence-source-evidence-b868493be1c74f63bce96e877d13f19c.json`
shows blocked `tiingo` logged as an attempt, but the actual market-news packet
counts are `google_news_rss`, `official_cache`, and `reddit_watchlist`, with
`limited_source_packet_count=0`. Fresh source-quality review
`results\source_quality\source-quality-review-20260606-195554.json` reports
`source_count=250`, `stale_count=174`, `blocked_count=69`, and
`stale_needs_refresh_count=0`. Regression proof:
`uv run --no-sync --with pytest python -m pytest tests/test_research_provider_orchestrator.py tests/test_source_quality.py -q`
passed with 37 tests, and targeted Ruff passed.

2026-06-04 follow-up checkpoint: the social sentiment decision path no longer
pretends recent public social feeds are unbounded point-in-time evidence.
`get_current_date()` now normalizes to UTC to avoid local-clock look-ahead, and
StockTwits/Reddit sentiment adapters pass `start_date` / `end_date` into their
public fetchers. Returned messages/posts are filtered by timestamp before
analyst rendering, while the sources remain advisory/recent-only and
execution-authority `none`. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_safe_ticker_component.py tests/test_reddit_dataflow.py
tests/test_decision_vendor_adapters.py` passed with 24 tests; targeted Ruff
passed.

2026-06-04 Alpha Vantage data-integrity checkpoint: CSV date-filter failures
now fail closed instead of returning unfiltered Alpha Vantage stock rows. The
helper returns a clear `Error filtering Alpha Vantage CSV data by date range:`
string, which the decision router treats as failed vendor evidence so configured
fallbacks can run. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_official_dataflows.py::test_alpha_vantage_common_filters_csv_by_date_range
tests/test_official_dataflows.py::test_alpha_vantage_common_date_filter_failure_does_not_return_unfiltered_csv
tests/test_official_dataflows.py::test_alpha_vantage_common_uses_shared_text_client
tests/test_dataflows_interface.py::test_route_to_vendor_falls_back_on_vendor_error_string`
passed with 4 tests; targeted Ruff and
`mypy tradingagents/dataflows/alpha_vantage_common.py` passed.

2026-06-04 stockstats history-window checkpoint: `load_ohlcv()` now uses the
documented 15-year cache window instead of fetching only 5 years. This preserves
older fixed-as-of replay and long-horizon indicator coverage while still
filtering rows after `curr_date` before stockstats sees them. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_stockstats_utils.py tests/test_safe_ticker_component.py
tests/test_dataflows_interface.py::test_default_config_routes_macro_and_sentiment_decision_tools`
passed with 11 tests; targeted Ruff and
`mypy tradingagents/dataflows/stockstats_utils.py` passed.

2026-06-04 reconciliation tolerance checkpoint: live-position reconciliation
now tolerates fractional-share rounding dust up to `0.000001`, matching the
broker order-comparison tolerance while still blocking real mismatches and
unexpected positions. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_execution_safety.py tests/test_alpaca_execution.py tests/test_live_gate.py`
passed with 53 tests; targeted Ruff and
`mypy tradingagents/execution/reconcile.py` passed.

2026-06-04 atomic policy-state write checkpoint: live-control state,
preregistration latest/log files, and promotion state now write through
`tradingagents.policy.io` using sibling temp files and atomic replacement.
Failed replacements preserve prior state and clean temp files, reducing noisy
fail-closed lockouts from partial JSON/JSONL writes. Focused proof:
`uv run --with pytest python -m pytest -q tests/test_policy_io.py
tests/test_preregistration_policy.py tests/test_promotion_policy.py
tests/test_live_gate.py tests/test_policy_foundation.py` passed with 32 tests;
targeted Ruff passed; strict mypy passed for `tradingagents/policy/io.py`,
`live_control.py`, `preregistration.py`, and `promotion.py`.

2026-06-04 bull/bear memory checkpoint: prior decision and outcome lessons in
`past_context` now reach both debate researchers, not just the Portfolio
Manager. The section is omitted when empty, preserving first-run prompt shape.
Focused proof: `uv run --with pytest python -m pytest -q
tests/test_structured_agents.py tests/test_memory_log.py::TestPortfolioManagerInjection`
passed with 25 tests; targeted Ruff and py_compile passed for both researcher
modules.

2026-06-04 interactive model-budget halt checkpoint: explicit env caps for
`TRADINGAGENTS_MODEL_MAX_CALLS_PER_RUN`,
`TRADINGAGENTS_MODEL_MAX_INPUT_TOKENS_PER_RUN`, and
`TRADINGAGENTS_MODEL_MAX_OUTPUT_TOKENS_PER_RUN` now halt the interactive graph
through `cli.stats_handler.ModelBudgetExceededError`. Empty/missing caps remain
non-halting, avoiding accidental default 8-call breakage in normal manual graph
runs. Focused proof: `uv run --with pytest python -m pytest -q
tests/test_stats_handler.py tests/test_model_routing.py` passed with 25 tests;
targeted Ruff and py_compile passed; strict mypy passed for
`cli/stats_handler.py`.

2026-06-04 BEA macro window checkpoint: `get_bea_macro_context()` now fetches
each BEA NIPA year in the requested lookback window instead of only
`curr_date.year`, matching the BLS macro window behavior without assuming BEA
multi-year query syntax. Focused proof: `uv run --no-sync --with pytest python -m pytest -q tests/test_decision_vendor_adapters.py tests/test_official_dataflows.py tests/test_dataflows_interface.py` passed with 56 tests; targeted Ruff and py_compile passed.

2026-06-04 real-simulation output checkpoint: `run_real_simulation_audit()`
now precomputes its JSON/Markdown output paths, embeds those paths in the audit
payload, and writes the files once. This removes the duplicate `_write_outputs`
call while keeping `latest.json` self-describing. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q tests/test_real_simulation_audit.py`
passed with 12 tests; targeted Ruff and py_compile passed.

2026-06-04 follow-up checkpoint: the original TradingAgents news tool path now
exposes insider transactions to the model. `create_news_analyst` binds
`get_insider_transactions` alongside ticker news, global news, and macro
context, and the prompt explicitly tells the analyst to use it when insider
buying/selling would confirm or contradict a stock-specific news thesis.
Focused proof: `tests/test_agent_asset_context.py`, `tests/test_graph_tool_routing.py`,
and the promoted-source vendor-map test passed with 7 tests; targeted Ruff
passed.

2026-06-04 supervisor safety checkpoint: the hourly supervisor no longer uses a
synthetic `$1` close price when live position `current_price` is missing.
Approved loss exits now fall back to `loss-review` with `actions=[]` if positive
current-price evidence is absent, and profit-taking falls back to
`profit-review` with `actions=[]` under the same condition. This preserves the
buy-dip/sell-spike intent while preventing stale broker position data from
creating wildly bad sell limits. Focused proof: 73 supervisor/live-gate tests,
2 compact-hourly CLI tests, targeted Ruff, `mypy tradingagents/brokers/alpaca_supervisor.py`,
and py_compile all passed.

---

## PA — Autonomous self-improvement & auto-fix loop ⭐ (anytime something fails, it fixes it — safely)

```
MISSION: Close the loop from "detect failure" to "apply fix and verify" autonomously for the SAFE class, and ESCALATE the dangerous class. Never any trading/order autonomy.

EVIDENCE: self-heal is advisory-only today. orchestration/self_heal.py builds handoff packets guarded by FORBIDDEN_EFFECTS (:20-28: create_trade_intent, size_position, submit_order, promote_sleeve, waive_live_gate, send_email, modify_automation_status) with severity tiers HIGH/MEDIUM/LOW. Subsystems already EMIT suggested fixes but nothing applies them: research/model_routing.py + research/model_telemetry.py expose self_heal_actions per route; research/crawler_runner.py emits self_heal_actions; brokers/alpaca_supervisor.py says "Codex next step: self-heal safe setup problems, then rerun checks". cli/main.py `research self-heal-handoff` + n8n job self_heal_handoff only WRITE a handoff for a human/Codex chat.

TASK:
1. Failure bus: one collector for non-order failure signals — failed non-order CLI commands, connector health breaches (P1 telemetry), stale/downranked sources, model-route errors (model_telemetry), crawler failures, JSON/schema validation errors, graph failures, and pytest failures.
2. Classifier: AUTO-FIX (safe) vs ESCALATE (owner). ESCALATE = anything matching FORBIDDEN_EFFECTS or needing a credential, risk-envelope arming, kill/freeze, promotion, or live-gate waiver. The entire order/broker plane stays fail-closed + human-gated.
3. Auto-fix executor (safe plane only; each fix deterministic + verified by re-running the failed check):
   - connector failure -> apply P1 retry/failover/circuit-breaker, re-route the category to next-best vendor, refresh cache; verify by re-fetch.
   - model-route error -> apply that route's existing self_heal_actions (switch lane/model); verify with a cheap probe.
   - stale source -> downrank + refresh; crawler failure -> run crawler-runtime-doctor self_heal_actions and re-run read-only.
   - schema/packet error -> regenerate the packet; re-validate against schema.
   - code/test failure -> open a fix BRANCH/PR with the diff + failing-test repro and re-run the targeted tests in the branch. NEVER auto-merge anything touching brokers/policy/execution.
4. Bounded retry + escalation: N attempts with exponential backoff; on exhaustion, write the existing self-heal handoff with full evidence and set results/_context/latest-flags.json.
5. Idempotent + audited: every auto-fix writes a compact record (signal, root-cause signature, fix applied, verify result) under results/self_heal/; dedupe by signature so an already-applied fix never repeats.

DO NOT: submit/size/promote/cancel orders; waive live gates; send email; flip automation status; auto-merge code touching brokers/policy/execution. Those ALWAYS escalate.
VERIFY: inject each safe failure class -> auto-fix applies + verifies + records; inject an order-class/FORBIDDEN_EFFECTS failure -> it ESCALATES and never auto-acts; full suite green; a dry-run supervise-hourly shows fewer unresolved blockers after one heal cycle.
DELIVER: failure-bus + classifier + executor modules, per-class fix proof, escalation proof for the forbidden class, audit packet path.
```

2026-06-03 checkpoint: PA now has a bounded safe-plane failure bus/classifier
and executor in `tradingagents/orchestration/self_heal.py`. `research
self-heal-plan --json-output` writes audited plan packets under
`results/self_heal/plans/`; `research self-heal-plan --execute-safe
--json-output` runs only allowlisted verification/refresh commands, then marks
safe signals `verified` or leaves dangerous/order-adjacent signals `escalated`.
The first real safe execution packet is
`results\self_heal\plans\self-heal-plan-20260603-191016.json`: it verified two
safe compact-context refresh actions, skipped/escalated the BOARD/order-adjacent
signal, submitted no orders, sent no email, and changed no automation status.
n8n now has separate compact jobs `self_heal_plan` and
`self_heal_execute_safe`, both `submit_capable=false`; `self_heal_handoff`
excludes self-heal packets so PA cannot create a feedback loop. The
automation-health audit now checks timeliness: if an actionable self-heal
handoff is not followed by a plan/execution packet within the SLA, it raises a
`self_heal_plan_late` timing issue. Real proof:
`results\automation_health\automation-health-audit-20260603-191840.json` has
`timeliness_issue_count=0`, `late_count=0`, `missing_count=0`, and
`partial_count=0`. Focused department proof passed with 152 tests covering model
routing, orchestration, n8n policy, source quality, supervisors, paper
tournament, execution BOARD, automation health, real simulation audit, and
compact context. Full repo regression then passed with 662 tests, 1 skipped
live-key test, 8 warnings, and 75 subtests.

---

## P2 — Decision-quality loop: offline backtest + calibration ⭐

```
MISSION: Make decision-quality changes measurable BEFORE risking capital, and replace hardcoded probabilities with calibrated ones.

EVIDENCE: No offline validation exists (backtrader is a dead dep; only the forward eval ledger resolves outcomes, which is slow). evals/replay_ablation.py already has a "fixed_as_of_dataset" concept (:130). evals/agent_intelligence_ledger.py maps ratings->probabilities with HARDCODED constants (RATING_PROBABILITY, :42-48: Buy=0.66, Hold=0.50, ...) while it already resolves real outcomes and tracks earned influence weights. graph/reflection.py reflects on alpha vs SPY.

TASK:
1. Point-in-time audit FIRST (look-ahead is the #1 silent inflator):
   - Trace whether an as-of/trade_date cutoff threads from the graph through tradingagents/dataflows/* and agents/utils/agent_utils.py, or whether tools fetch "latest". Document every site that ignores as-of. Fix the data tools to respect an as-of bound when one is supplied (live runs pass None = latest, which is correct).
2. Offline walk-forward harness (extend replay_ablation, do not add backtrader):
   - Replay the real TradingAgentsGraph over a list of historical (ticker, trade_date) with data pinned to as-of.
   - Score per decision and aggregate: directional hit-rate, alpha vs benchmark, Brier score (using the rating->probability map), coverage.
   - Emit a compact report packet; add a CLI subcommand (e.g. `tradingagents evals walk-forward`) consistent with existing eval commands.
3. Calibrate from resolved history:
   - Recompute RATING_PROBABILITY and per-agent weights from the ledger's resolved outcomes (overall + by setup/regime/sector where sample size allows; fall back to global with shrinkage when sparse).
   - Keep the LEDGER_FORBIDDEN_EFFECTS guard intact; calibration is read-only w.r.t. orders.

DO NOT: wire backtest output to order submission; overfit (use shrinkage + min-sample floors).
VERIFY: walk-forward report on >=10 historical names; before/after Brier from calibration; point-in-time test proving no future data leaks at a historical as-of; full suite green.
DELIVER: point-in-time audit table, harness + CLI, calibration deltas (old vs new probabilities/weights), report packet path.
```

2026-06-03 checkpoint: P2 now has a first analysis-only decision-quality report
slice. `tradingagents.evals.replay_ablation` exposes a static point-in-time
audit table for analyst data routes and a shrinkage-based rating-probability
calibrator that reads resolved Agent Intelligence Ledger forecasts without
touching orders. New CLI:
`tradingagents research decision-quality-report --candidate-symbols NVDA,MSFT
--json-output`. The latest real packet is
`results\research_batches\research-batch-research-batch-4b94859e548b4221ac1b974fc8b27560.json`;
it reports `status="success"`, `execution_authority="none"`,
`point_in_time_gap_count=0`, `point_in_time_mixed_count=0`, and no resolved
live ledger calibration rows yet, so hardcoded priors remain unchanged. Google News RSS now filters items by
`pubDate` inside the requested `start_date`/`end_date` window before rendering
or replay scoring; EIA now uses monthly `start`/`end` windows and Treasury uses
`record_date` filters keyed to `curr_date`; SEC/FMP/EODHD rendered fundamentals
now drop rows/date-keyed sections after `curr_date` while preserving raw vendor
packets as archived evidence; public Reddit/StockTwits stay live-only advisory
and are explicitly unscored in historical replay unless a timestamped archive is
added. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_official_dataflows.py tests/test_decision_vendor_adapters.py
tests/test_dataflows_interface.py tests/test_replay_ablation_plan.py` passed
with 59 tests; `uv run --no-sync --group static-analysis ruff check` passed;
broad mypy passed on 52 source files; compile checks passed. Remaining P2 work:
build the >=10-name walk-forward graph replay harness.

2026-06-04 checkpoint: P2 now has the first fixed-as-of walk-forward replay
CLI. `tradingagents research walk-forward-replay --fixture-path <json>` reads
explicit fixture rows, filters an optional same-universe ticker set, scores the
deterministic sleeve plus any timestamped advisory overlay decisions, and keeps
all missing overlays unavailable rather than guessed. The packet reports
directional accuracy, false-positive rate, action-relative return,
benchmark-relative return, Brier score, sample-floor status, and the current
point-in-time audit status table; it is analysis-only with
`execution_authority="none"`. Repeatable fixture proof:
`tests\fixtures\walk_forward_replay_sample.json` with 10 rows wrote
`results\research_batches\research-batch-research-batch-8691b073a65b4372ac1da19341f2e563.json`;
`walk_forward_row_count=10`, `sample_floor_met=true`, baseline accuracy `0.7000`,
TradingAgents advisory overlay accuracy `0.9000`, and social/crawler plus Deep
Research overlays were marked unavailable because the fixture has no timestamped
captured decisions for those lanes. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q tests/test_replay_ablation_plan.py`
passed with 9 tests; file-local mypy with skipped imports passed; Ruff passed
for the touched files. Remaining P2 work: build the captured historical graph
decision dataset/generator so the harness scores real TradingAgents pipeline
outputs rather than only explicit replay fixtures.

2026-06-04 follow-up: P2 now also has a captured overnight-to-fixture
generator. `tradingagents research walk-forward-fixture-from-overnight
--overnight-packet <packet.json> --returns-path <returns.json>` converts
captured overnight `ticker_results` into the same replay fixture schema when
later return rows are supplied. It reuses the Agent Intelligence Ledger
rating-probability table, tags full-graph/`status=ok` decisions as
`tradingagents_advisory_overlay`, leaves fallback-only rows as baseline, and
skips missing return rows with an explicit reason instead of fabricating
outcomes. Proof inputs:
`tests\fixtures\overnight_packet_sample.json` and
`tests\fixtures\overnight_returns_sample.json`; generator output:
`results\research_batches\walk_forward_fixture_from_overnight_sample.json`
with `row_count=2`, `skipped_count=1`, and `execution_authority="none"`.
Replay proof from that generated fixture:
`results\research_batches\research-batch-research-batch-e09e0e205e8e4f72a915ed0bfe939996.json`;
`walk_forward_row_count=2`, `sample_floor_met=true` for the requested
2-decision proof, baseline accuracy `1.0000`, and TradingAgents advisory
overlay scored only for the captured full-graph row. Remaining P2 work: automate
collection of real later return rows for captured overnight packets and expand
the proof set beyond small fixtures before any influence promotion.

2026-06-04 second follow-up: P2 now has the return-row collection step before
fixture generation. `tradingagents research walk-forward-returns-from-overnight
--overnight-packet <packet.json>` uses the same yfinance lookup pattern as
Agent Intelligence Ledger resolution by default, or deterministic
`--price-rows-path <json>` for tests/proofs, to write later ticker and benchmark
returns for captured overnight decisions. It skips missing price windows with
explicit reasons and carries `execution_authority="none"`. Deterministic proof:
`tests\fixtures\overnight_price_rows_sample.json` plus
`tests\fixtures\overnight_packet_sample.json` wrote
`results\research_batches\walk_forward_returns_from_overnight_sample.json`
(`row_count=2`, `skipped_count=1`, `price_route="static_price_rows"`). Feeding
that into `walk-forward-fixture-from-overnight` wrote
`results\research_batches\walk_forward_fixture_from_collected_returns_sample.json`;
replaying it wrote
`results\research_batches\research-batch-research-batch-58e875ebe0b74df28c5b1349f886ecda.json`
with `walk_forward_row_count=2`, `sample_floor_met=true` for the 2-row proof,
and no execution authority. Remaining P2 work: run the yfinance route on real
captured historical packets as data matures, expand sample size, then use the
calibration results only after sample floors are met.

2026-06-04 real-replay follow-up: P2 now has a real yfinance later-return
cohort from six captured June 1 overnight packets. The collector wrote
`results\research_batches\walk_forward_returns_real_20260601_h3.json`
(`row_count=70`, `skipped_count=0`, `price_route="yfinance"`,
`horizon_days=3`, benchmark `SPY`). The generated fixture
`results\research_batches\walk_forward_fixture_real_20260601_h3.json` produced
`row_count=210`, and replay wrote
`results\research_batches\research-batch-research-batch-ee09089c106b4902a776046dd1bfd87a.json`
with `sample_floor_met=true`, `execution_authority="none"`, deterministic
baseline directional accuracy `0.4048`, false-positive rate `0.1667`,
average Brier `0.2555`, average relative return vs benchmark `0.2481`, and
average action-relative return `0.0409`. Remaining P2 work: automate the real
cohort refresh as more packets mature, then promote influence only after the
agent/intelligence overlays have enough timestamped rows.

2026-06-05 cohort-refresh follow-up: P2 now has an automation-ready command:
`tradingagents research walk-forward-refresh-overnight-cohort --overnight-log-dir
results/overnight_plans --horizon-days 3`. It discovers mature
`overnight-plan-*.json` packets, skips immature/unreadable packets with reasons,
collects later returns, generates the overnight fixture, runs the walk-forward
replay, and writes a compact analysis-only summary in one step. It remains
`execution_authority="none"` and explicitly forbids order effects. The first
real yfinance proof wrote
`results\research_batches\walk_forward_cohort_refresh_20260605-084740_h3.json`:
8 mature packets selected, 6 skipped as not mature, 101 return rows, 4 skipped
price windows, 280 fixture rows, `sample_floor_met=true`, replay packet
`results\research_batches\research-batch-research-batch-23c8eeb48db94068a11d0c8936b76afa.json`.
The deterministic sleeve scored 280 rows with directional accuracy `0.3821` and
average action-relative return `-0.0751`; the full TradingAgents advisory
overlay scored 11 rows with directional accuracy `0.5455` and average
action-relative return `2.9918`. Treat this as early calibration evidence only:
keep collecting rows before changing influence weights. A real-run bug was also
fixed: non-finite yfinance price windows such as `NaN` now skip with
`invalid_price_window` instead of entering replay metrics. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_replay_ablation_plan.py` passed with 15 tests; targeted Ruff passed.

---

## P3 — Automations / supervisors / self-heal / overnight (reliability spine)

```
MISSION: Deep-quality + reliability pass on the live automation spine. No live orders; analysis/paper/dry-run only.

EVIDENCE: brokers/alpaca_supervisor.py is a 2657-LOC monolith (hourly + overnight + premarket + daily-report + candidate ranking + dynamic cap all in one file) — hard to test in isolation. orchestration/self_heal.py is advisory-only (FORBIDDEN_EFFECTS guard, severity tiers HIGH/MEDIUM/LOW). research/automation_orchestrator.py (358 LOC) + deep_research_protocol.py (205) drive overnight research.

TASK:
1. Decompose alpaca_supervisor.py by responsibility (hourly / overnight / premarket / daily_report / candidate_ranking / dynamic_cap) into a brokers/supervisor/ package. Pure refactor: preserve public entry points and CLI behavior; move logic, don't rewrite it. This unlocks isolated unit tests per concern.
2. Self-heal loop closure (orchestration/self_heal.py):
   - Confirm it is actually invoked on supervisor blockers/schema/graph_failure/abnormal_pl (trace the call sites).
   - Add dedupe: collapse repeat triggers with the same root-cause signature so the same issue doesn't generate a fresh handoff every tick.
   - Track "heal applied?" state so resolved issues stop re-firing; expose unresolved count to results/_context/latest-flags.json.
3. Overnight research -> priors:
   - Ensure automation_orchestrator dedupes research, scores sources via evals/source_quality.py, and feeds surviving findings as PRIORS into the next graph run (watchlist + context), instead of regenerating cold each night.

DO NOT: change exposure caps / live-gate semantics; submit orders; alter packet schemas that operators depend on (extend, don't break).
VERIFY: per-concern supervisor unit tests pass post-split; self-heal dedupe + applied-state tests; prior-injection visible in a dry-run overnight plan; these commands still clean:
  tradingagents alpaca supervise-hourly --dry-run --json-output
  tradingagents alpaca plan-overnight --json-output
  tradingagents alpaca premarket-brief --json-output
  tradingagents alpaca verify-overnight-system
DELIVER: new module map, self-heal dedupe/applied evidence, prior-feed proof, verify outputs.
```

2026-06-03 checkpoint: the reliability spine now has a loss-exit safety slice
ahead of the planned supervisor decomposition. `build_hourly_decision` treats a
losing live position as BOARD-review work, not an automatic sell, unless explicit
thesis-break/time-value/capital-reuse evidence is present. `classify_supervisor_alert`
and hourly emails render this as a short human-readable `loss-review` problem,
and the CLI honors execution BOARD underperformer-review recommendations by
pausing new live buys only. Verified with:
`tests/test_alpaca_supervisor.py`, the focused BOARD CLI test,
`tests/test_execution_board.py`, targeted Ruff, and a live-data dry run packet
`results\hourly_supervisor\hourly-supervisor-20260603-142301-935239.json`
showing `decision=loss-review`, `actions=[]`, `submitted=[]`.
The BOARD review now also treats historical live loss sells without structured
`evidence.loss_exit_review` as hard violations, so loss exits must carry explicit
allowed evidence instead of being inferred from drawdown alone. Latest BOARD
proof: `results\execution_board\execution-board-review-20260603-192427.json`.

2026-06-03 follow-up checkpoint: self-heal now has a durable signature-state
ledger at `results\self_heal\signature-state.json`. Handoffs and plans share
the same root-cause signatures, so repeated medium/high triggers are still
audited but do not request a fresh repair chat once the same signature is
already recorded. Plans also dedupe from durable state, not only
`plans/latest.json`, so a missing latest pointer does not cause repeat safe
fixes. Real safe execution proof:
`results\self_heal\plans\self-heal-plan-20260604-005437.json` verified one
safe compact-context refresh, submitted no orders, sent no email, changed no
automation statuses, and reported `deduped_prior_count=1`. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_self_heal_handoff.py tests/test_automation_health_audit.py
tests/test_n8n_runner_policy.py` passed with 45 tests; Ruff, broad mypy, and
strict typed-frontier mypy passed. Remaining P3 work: supervisor decomposition.

2026-06-04 prior-feed follow-up: overnight research context now writes an
explicit compact `overnight_prior_feed_v1` artifact beside the raw source
packets. The feed is analysis-only, `execution_authority=none`, and gives
automation/n8n a cheap pointer to provider fallbacks, watchlists, MiroFish/report
33 priors, deep-research route policy, blocked counts, and raw packet refs.
Compact overnight stdout now includes `research_context_summary.prior_feed`.
Real no-latest/no-graph proof:
`results\overnight_plans\prior_feed_probe\research_context\overnight-prior-feed-20260604-221007.json`
was emitted by `alpaca plan-overnight --json-output --compact-json-output
--full-graph-tickers 0 --no-agent-ledger --no-write-latest`, with
`submitted_count=0`, `research_context_packet_count=13`, `blocked_count=0`,
and no automation latest pointer update. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_research_crawler_social.py::test_overnight_research_context_writes_provider_and_watchlist_packets
tests/test_alpaca_cli.py::test_compact_overnight_plan_payload_points_to_raw_packet
tests/test_alpaca_cli.py::test_plan_overnight_compact_json_output_points_to_raw_packet`
passed with 3 tests; Ruff and compile checks passed on touched files.
Verifier follow-up: `alpaca verify-overnight-system` now includes an
`overnight_prior_feed` check. Old packets without a prior-feed pointer warn;
new packets with an unreadable or unsafe prior-feed artifact fail. Focused proof
`tests/test_alpaca_cli.py::test_verify_overnight_system_audits_full_chain`
requires a passing prior-feed check. The transitional warning was cleared by the
new full overnight packet and latest real verification
`results\overnight_system_verification\overnight-system-verification-20260604-180544.json`
has `overall_status=pass`.

2026-06-04 live rerun checkpoint: the updated full overnight run now clears the
prior-feed warning. Latest plan
`results\overnight_plans\overnight-plan-20260604-223730-000000.json` has top
candidates `TXN`, `QCOM`, `KO`, `IBM`, `INTC`, three successful original graph
runs, 32 fallback tickers, no graph failures, no submissions, and prior-feed
`results\overnight_plans\research_context\overnight-prior-feed-20260604-222820.json`.
Latest verifier
`results\overnight_system_verification\overnight-system-verification-20260604-180544.json`
is `overall_status=pass`. Fresh premarket brief
`results\premarket_briefs\premarket-brief-20260604-230506-000000.json` carries
`premarket_instructions.latest_research_context.prior_feed` with
`analysis_only=true`, `execution_authority=none`, and forbidden effects including
`submit_order`; skinny old prior-feed pointers are enriched from the referenced
JSON artifact. Pre-open hourly validation now carries this compact
`latest_research_context.prior_feed` forward into hourly evidence. Focused proof
included `tests/test_alpaca_cli.py::test_preopen_supervisor_includes_premarket_brief_validation`;
closed-session real dry-run
`results\hourly_supervisor\hourly-supervisor-20260604-232011-923105.json`
stayed `decision=hold`, `submitted_count=0`, and `issue_count=0`.
The Crawlee runner now uses per-run storage and
restores `CRAWLEE_STORAGE_DIR`, fixing the stale QCOM request queue reuse seen
during top-candidate provider bundles. Fresh compact context has `flags=[]`.

2026-06-04 follow-up checkpoint: automation-health now de-noises scheduler
evidence instead of turning intended controller behavior into blockers. Paused
automations get `expected_run_count=0`, so manual/test packets for the paused
hourly supervisor or paper tournament remain visible without becoming duplicate
scheduled-run failures. Overnight planning now counts primary overnight-plan
artifacts only; rolling premarket briefs are no longer treated as overnight
duplicates. Self-heal duplicate history stays visible, but when the latest
actionable handoff is followed by a verified plan inside the SLA, the monitor
stays `ok` with `status_reason=self_heal_timely_duplicate_artifacts_de_noised`.
Real proof:
`results\automation_health\automation-health-audit-20260604-061458.json` has
`duplicate_count=0`, `timeliness_issue_count=0`, self-heal follow-up lag `33s`,
and paper tournament `status=ok` while paused. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_automation_health_audit.py tests/test_automation_context_snapshot.py
tests/test_n8n_runner_policy.py` passed with 60 tests; Ruff passed for the
touched automation-health files.

2026-06-04 morning follow-up: active paper-only tournament catch-up/manual
passes are now de-noised the same way when they are harmless. The audit keeps
the extra AlphaInsider watch plus paper-tournament packet evidence visible, but
does not mark automation health `duplicate` when the lane submitted no orders,
had no packet issues, and the automation memory proves completion at or after
the latest artifact. Real proof:
`results\automation_health\automation-health-audit-20260604-132938.json` has
13/13 automations `ok`, `duplicate_count=0`, `issue_count=0`,
`timeliness_issue_count=0`, and n8n `automation_health_audit` returns empty
`attention_automation_ids` and `problem_automation_ids`. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_automation_health_audit.py tests/test_automation_context_snapshot.py
tests/test_n8n_runner_policy.py tests/test_n8n_evaluations.py` passed with
80 tests; Ruff passed on the touched automation-health files.

2026-06-04 compact-flag cleanup: optional paper-only AlphaInsider endpoint
limitations and non-actionable BOARD caution no longer become global blockers.
AlphaInsider `verifyToken` is checked before `getRecommendedStrategies`; when
the token verifies but the optional recommended-strategy endpoint returns HTTP
400, the paper-shadow packet reports `fetch_status=blocked` with
`token verified`, while compact connector health keeps it visible under
`optional_endpoint_error_connectors` without raising `connector_health`. BOARD
reviews with `state=caution`, enough clean packets, no violations, and only
historical negative-unrealized-P/L warnings now summarize as
`caution_guardrails_only=true` without a `board_review` flag. Real compact
context now leaves only expected `paper_tournament` candidate-change and
`mirofish_handoff_status` final-handoff drilldown flags. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_mirofish_handoff.py tests/test_alphainsider.py
tests/test_paper_tournament.py tests/test_automation_context_snapshot.py
tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_mirofish_handoff_json
tests/test_research_crawler_social.py::test_overnight_summary_carries_structured_mirofish_attention_priors`
passed with 49 tests; Ruff passed.

2026-06-03 real simulation checkpoint: `research real-simulation-audit` now
counts stale evidence as safe when it is refreshed, downrankable, or already
low/unknown quality, and the latest audit packet
`results\real_simulation_audits\real-simulation-audit-20260603-192427.json`
meets all acceptance checks: no live-submit command, Mac DeepSeek available,
all commands clean, stale sources safe/downranked, zero submissions, zero
blockers. Optional Windows-local Ollama remains advisory-only when unreachable;
Mac `deepseek-r1:14b` is the selected cheap helper lane.

2026-06-04 overnight-original-graph checkpoint: overnight planning had not
"failed to complete"; an earlier real overnight packet completed fallback-only
with `requested_full_graph_limit=3`, `full_graph_count=0`, and
`fallback_count=35`. Root cause was runtime routing, not a missing packet:
Windows Ollama was unavailable, while Mac `deepseek-r1:14b` is intentionally
reserved for cheap helper work (source triage, stale-source summaries,
contradiction hunting, draft cleanup, compression) instead of full original
TradingAgents graph reasoning. `alpaca verify-overnight-system` now includes
the explicit `overnight_original_graph_execution` check and warns when the
automation contract requests full graph but the current packet is fallback-only.
Follow-up patch: explicit non-Ollama overnight routes now bypass the local
Ollama auto-disable path, clear inherited Ollama backend URLs, and record a
provider-specific `overnight_model_route`. Overnight quality packets now
separate `full_graph_attempt_count` from `full_graph_success_count`;
verification requires a successful graph run, not merely an attempted one.
The active overnight automation command now requests the credentialed Google
route (`--overnight-llm-provider google`, quick `gemini-2.5-flash-lite`, deep
`gemini-2.5-flash`) so the original TradingAgents graph can run even while
Windows Ollama is unavailable. Negative no-write OpenAI probe:
`results\overnight_plans\openai_graph_probe\overnight-plan-20260604-182040-000000.json`
attempted one OpenAI graph lane, submitted zero orders, and correctly reported
`full_graph_attempt_count=1`, `full_graph_success_count=0`,
`graph_failure_count=1` because this shell is missing `OPENAI_API_KEY` /
`OPENAI_ADMIN_KEY`. Positive no-write Google probe:
`results\overnight_plans\google_graph_probe\overnight-plan-20260604-182923-000000.json`
reported `full_graph_attempt_count=1`, `full_graph_success_count=1`,
`graph_failure_count=0`, submitted zero orders, and produced top candidate AMD
from `method=full_graph`.

2026-06-04 model telemetry follow-up: the Mac helper route is no longer treated
as blocked just because older packets failed before the 32 GB Mac DeepSeek lane
was wired. `research model-telemetry-report` now exposes
`current_route_statuses`, current-only `blocked_route_summaries`, and
`historical_blocked_route_summaries`. The latest real report
`results\model_telemetry_reports\model-telemetry-report-20260604-210104-955683.json`
shows current Mac `mac_ollama_research_mule` success on `deepseek-r1:14b`, while
Windows local Ollama remains the only current local-model blocker. Compact
context now exposes `selected_helper_routes`, so morning agents can discover Mac
DeepSeek helper availability without opening raw telemetry.

2026-06-04 compact MiroFish follow-up: a clean final MiroFish handoff no longer
creates a permanent raw-packet drilldown flag. Compact context still carries
the MiroFish full-report false-signal filter and Deep Research report-33
macro-first overlay, with `missing_piece_count=0`,
`final_advisory_available=true`, and `execution_authority=none`. Real refresh
left `results\_context\latest-flags.json` empty; future agents should open raw
MiroFish only for missing advisory pieces, stale/missing scaffold, or
clean-room/execution-authority violations.

2026-06-04 qualitative-gate follow-up: the MiroFish handoff parser no longer
lets qualitative report warnings collapse to all-zero telemetry. It canonicalizes
index names such as `AI_bot_copycat_index` and treats observed-but-nonnumeric
telemetry indices as elevated conservative advisory evidence. Fresh status packet
`results\mirofish_handoff\latest.json` shows
`mirofish_advisory_gate_action=suppress` with triggered gates
`broker_friction`, `macro_override`, and `attribution_error`, while preserving
`execution_authority=none` and `can_submit_orders=false`. This makes the
AI-bot-copycat / institutional-liquidity adaptation warning usable as a
pre-action caution filter without wiring it to orders. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_mirofish_handoff.py
tests/test_research_crawler_social.py::test_overnight_summary_carries_structured_mirofish_attention_priors
tests/test_mirofish_gates.py`
passed with 17 tests.

Full Google route proof: the real overnight automation command completed at
`results\overnight_plans\overnight-plan-20260604-184407-000000.json` with
zero submitted orders, top candidates `KO`, `HD`, `AMD`, `TXN`, `PEP`,
`full_graph_attempt_count=3`, `full_graph_success_count=3`,
`fallback_count=32`, and `graph_failure_count=0`. The refreshed premarket
brief `results\premarket_briefs\premarket-brief-20260604-185159-000000.json`
links to the same overnight packet with top symbol `KO`, no stale warnings, and
no unresolved blockers. Final verification
`results\overnight_system_verification\overnight-system-verification-20260604-140301.json`
has `overall_status=pass`.

2026-06-04/05 final overnight rerun proof: the latest production-style explicit
Google run completed at
`results\overnight_plans\overnight-plan-20260605-040719-000000.json` with zero
submitted orders, top candidates `KO`, `IBM`, `HD`, `CRM`, `QCOM`,
`full_graph_attempt_count=3`, `full_graph_success_count=3`,
`fallback_count=32`, and `graph_failure_count=0`. Provider bundles were
refreshed sequentially for the top three candidates:
`results\research_evidence\source-evidence-source-evidence-26dedb9a401f4268b66e104f020a20d9.json`
for `KO`,
`results\research_evidence\source-evidence-source-evidence-6097ce36839744abb71f34fdb4d1186f.json`
for `IBM`, and
`results\research_evidence\source-evidence-source-evidence-0f438c6a9c8f47e2bbf124831c59b53e.json`
for `HD`. Fresh premarket brief
`results\premarket_briefs\premarket-brief-20260605-040926-000000.json` has top
symbol `KO`, no stale warnings, and no unresolved blockers. Fresh verifier
`results\overnight_system_verification\overnight-system-verification-20260604-231510.json`
is `overall_status=pass`. Fresh source-quality review
`results\source_quality\source-quality-review-20260605-063725.json` has
`source_count=250`, `stale_count=73`, `stale_safe_count=73`,
`stale_needs_refresh_count=0`, and `missing_or_invalid_count=0`. The old
walk-forward returns artifact was regenerated after
`walk-forward-returns-from-overnight` gained `generated_at`, `analysis_only`,
and `can_submit_orders=false` metadata, so compact context now has `flags=[]`
and `next_open=[]`.

2026-06-04 late automation-status proof: the current overnight packet is good
and the scheduler is armed again for the next 2:30 AM America/Chicago run.
`tradingagents-overnight-planning` was found `PAUSED` during the afternoon
controller window and was updated through the Codex automation API to `ACTIVE`.
Fresh automation health
`results\automation_health\automation-health-audit-20260604-212831.json` reports
all 13 automations `ok`, `issue_count=0`, `submitted_order_count=0`, and
overnight planning `config_status=ACTIVE`. Fresh overnight verifier
`results\overnight_system_verification\overnight-system-verification-20260604-162641.json`
also passes with 3/3 full graph successes, 32 fallback-scored tickers, no graph
failures, no stale premarket warnings, and no submitted orders.

2026-06-04 verifier hardening follow-up: `alpaca verify-overnight-system` now
audits the automation config status directly with
`automation_status:tradingagents-overnight-planning`. A future accidental
`PAUSED` scheduler is therefore a failing verifier check instead of a vague
"overnight research did not complete" mystery. The latest real verifier after
this patch is
`results\overnight_system_verification\overnight-system-verification-20260604-192530.json`
with `overall_status=pass`, expected and actual automation status `ACTIVE`,
3/3 graph successes, 32 fallback-scored tickers, no graph failures, and no
submitted orders. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_alpaca_cli.py::test_verify_overnight_system_audits_full_chain
tests/test_alpaca_cli.py::test_verify_overnight_system_warns_when_original_graph_requested_but_disabled
tests/test_alpaca_cli.py::test_verify_overnight_system_rejects_probe_latest_against_automation_contract`
passed with 3 tests.

2026-06-05 overnight-completion-status follow-up: `alpaca plan-overnight` now
writes `overnight_quality.completion_status` and `completion_reasons` so
automation consumers can distinguish `complete`, `failed`, `incomplete`,
`disabled`, `not_requested`, and `no_tradable_symbols` without opening raw
reports or inferring from stale `latest.json`. Compact overnight stdout now
carries the same completion fields. `alpaca verify-overnight-system` fails a
production packet that requested original graph runs but attempted none without
an explicit disable reason, while still allowing intentional no-graph previews
and helper-only disabled packets to be classified correctly. Real no-latest
compact preview proof:
`results\overnight_plans\completion_status_probe\overnight-plan-20260605-082412-000000.json`
returned `completion_status=not_requested`, `submitted_count=0`, and did not
update production `latest.json`; real verifier proof still reports
`overall_status=pass` for the production Google packet. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q tests/test_alpaca_cli.py
-k "plan_overnight or verify_overnight_system or
overnight_graph_completion_status or compact_overnight_plan_payload"` passed
with 15 tests; targeted Ruff passed.

2026-06-04 prior-feed integrity follow-up: the overnight verifier now treats a
modern prior-feed pointer as a contract instead of a loose hint. The pointed
file must live under the overnight packet's sibling `research_context`
directory, and its loaded JSON must agree with the reference on schema,
packet/block counts, analysis-only status, and execution authority. A corrupted
prior-feed packet with a mismatched `packet_count` now makes
`alpaca verify-overnight-system` fail instead of passing with stale or foreign
context. Focused proof:
`tests/test_alpaca_cli.py::test_verify_overnight_system_audits_full_chain`
covers the red/green mismatch case.

Provider-route follow-up proof: local ticker bundles now support the highest-
leverage previously missing free/local routes. `official_cache` can replay
cached packets, `yfinance` writes quote/price context, `sec_edgar` resolves
ticker-to-CIK and writes fundamentals/submissions context, and
`reddit_watchlist` writes read-only social attention context. Real KO/HD/AMD
bundles each wrote 12 analysis-only packets with the source mix
`official_cache`, `reddit_watchlist`, `alpaca_news`, `google_news_rss`,
`yfinance`, `sec_edgar`, `finnhub`, `tiingo`, and `fmp`:
`results\research_evidence\source-evidence-source-evidence-32051257a7b14911a6be98bdb6f1fdf0.json`,
`results\research_evidence\source-evidence-source-evidence-61eacab2639b45c7ac2cf08043168f7a.json`,
and
`results\research_evidence\source-evidence-source-evidence-060370eae0f843579b45cc4e6e47ce17.json`.
Follow-up crawler proof: default ticker bundles now include a separate
`crawler_research` need so Crawlee does not crowd out Google/Alpaca market-news
packets. `crawlee` uses deterministic ticker-to-target policies only; the
current target is the static SEC company endpoint, allowlisted to `sec.gov`.
The real default KO proof
`results\research_evidence\source-evidence-source-evidence-936ac99338724c81ace3517511764085.json`
shows the default bundle needs
`market_news,quote_price_context,fundamentals_profile,crawler_research` and
summarizes the successful crawler source packet
`results\research_evidence\source-evidence-source-evidence-090551d446f04343b05a16cc96028bac.json`
with `crawler_status=success`, `quality=medium`, one fetched SEC URL, and
`execution_authority=none`. During the repair, the venv's `greenlet`
dependency was found half-installed; `uv pip install --python
.\.venv\Scripts\python.exe --reinstall greenlet==3.2.3` restored the compiled
package, and `crawler-runtime-doctor` now checks `greenlet_available` so this
failure becomes a self-healable dependency issue before the first crawl.
The latest source-quality review
`results\source_quality\source-quality-review-20260604-200123.json` found
`source_count=250`, `stale_count=43`, `stale_downrank_count=43`, and
`stale_needs_refresh_count=0`. Remaining provider lift is now narrower and
intentional: broker snapshot needs an explicit prebuilt read-only account packet
instead of a ticker-only fetcher, and account-backed reddit/twitter should stay
skipped until authenticated connectors are present.

2026-06-04 broker-snapshot follow-up: `broker_snapshot` is now implemented as a
local, sanitized hourly-supervisor packet reader for `quote_price_context`, not
as a direct broker API fetch. The CLI exposes `--broker-snapshot-dir`, defaults
to `results/hourly_supervisor`, uses zero cache TTL, and disables stale fallback
so account context is refreshed from the latest supervisor artifact every run.
The real KO proof
`results\research_evidence\source-evidence-source-evidence-f5c7d62d87ca4be0901db1a13d67c0cb.json`
read `results\hourly_supervisor\hourly-supervisor-20260604-201930-941804.json`,
reported `submitted_order_count=0`, `execution_authority=none`, no live/paper
KO position, no KO open orders, and KO's controlled-dip ranked-candidate
context. Source-quality profiles now classify `broker_snapshot`,
`ticker_provider_orchestrator`, `official_cache`, and `crawlee`; the refreshed
review
`results\source_quality\source-quality-review-20260604-202541.json` found
`source_count=250`, `stale_count=42`, `stale_downrank_count=42`,
`stale_needs_refresh_count=0`, and only `unknown=5`. Remaining provider lift is
now account-backed `reddit`/`twitter`, still skipped until authenticated
connectors are present and their packets remain analysis-only.

2026-06-04 social-provider follow-up: `reddit` provider fallback now uses the
repo-local public JSON dataflow route (`dataflow:reddit_public`) for
`social_sentiment` only. It intentionally does not emit `market_news` packets,
so public Reddit cannot crowd out Google/Alpaca/news-provider evidence. Real
NVDA proof
`results\research_evidence\source-evidence-source-evidence-068230c2d7054c3b9d6d8569d719d566.json`
is low-authority, read-only, `execution_authority=none`, and records public
Reddit context even when one subreddit returns HTTP 403. `twitter` is now a
repo-callable Docker MCP bridge for `social_sentiment` only; it was removed
from `market_news` routing so social attention cannot masquerade as news.
`tradingagents.research.twitter_mcp` calls
`twitter-research__twitter_recent_search` through `docker mcp tools call` with
a bounded timeout, redacted payloads, and no execution authority. Real proof
`results\research_evidence\source-evidence-source-evidence-93ac9af1591c4a54a5d10d377e59afa7.json`
shows the bridge is reachable and read-only, while current X recent-search
access is blocked by 401/API tier and therefore downranked as a source-gap
signal rather than used as market evidence. The refreshed source-quality review
`results\source_quality\source-quality-review-20260604-220425.json` reported
`source_count=250`, `stale_count=43`, `stale_safe_count=43`,
`stale_needs_refresh_count=0`, and `unknown=5`.

2026-06-04 connector-health noise follow-up: public Reddit HTTP 403 from
`reddit_public` is now treated as an optional endpoint block when there is no
open circuit, no rate limit, and no fallback. It remains visible in
`results/_context/connector-health.json`, but it no longer wakes the workflow
as a hard `connector_health` flag. Real compact-context refresh after the patch
left only the paper-tournament candidate-change and MiroFish drilldown flags.
Focused proof: `uv run --no-sync --with pytest python -m pytest -q
tests/test_automation_context_snapshot.py` passed with 27 tests; targeted Ruff
and py_compile passed.

2026-06-04 live-circuit-breaker checkpoint: the live gate now enforces the
already-loaded `daily_loss_halt_usd` and `max_drawdown_halt_pct` fields for
new live buys, including `autonomous_uncapped` mode. This preserves the user's
uncapped live-budget posture while preventing fresh risk after the configured
portfolio loss/drawdown breakers trip. Profit-taking sells remain allowed, and
loss-taking sells still require the structured loss-exit review. Proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_live_gate.py tests/test_execution_safety.py` passed with 33 tests;
full `tests/test_alpaca_cli.py` passed with 72 tests.

2026-06-04 final broker-friction follow-up: live buys now require current broker
`buying_power` in the final submit guard. This preserves `autonomous_uncapped`
as "no repo dollar cap" while still enforcing the broker's actual spendable
cash/margin state. Missing broker buying power blocks new live buys; proposed
live buys above broker buying power also block. Sells remain independent:
profit-taking sells are not blocked by buying power, and losing sells still
require the structured loss-exit review. The CLI submit-capable live paths pass
the live account snapshot into `validate_supervisor_live_submit_allowed(...)`.
Focused proof:
`uv run --no-sync --with pytest python -m pytest -q tests/test_live_gate.py`
passed with 25 tests, and
`tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_live_buy_requires_submit_guard`
passed, proving the guard receives the live account buying-power payload.

2026-06-04 library-boundary submit follow-up: `execute_order_pairs(...)`, the
low-level paper/live mirror execution helper, now fails closed unless the caller
passes `live_guard_approved=True`. The legacy CLI passes that flag only after
`validate_supervisor_live_submit_allowed(...)` succeeds, so direct imports of
the helper cannot bypass the unified live gate by accident. Focused proof:
`tests/test_alpaca_execution.py::test_execute_order_pairs_requires_prior_live_guard_approval`
and `tests/test_alpaca_cli.py::test_live_submit_call_sites_stay_behind_unified_gate`.

2026-06-04 broker-clock/session follow-up: the tiny-live operational guard now
uses Alpaca broker clock state as a submit precondition, not just the local
`market_session_label()`. Regular-hours live tiny orders require broker
`clock.is_open=true`. Extended-hours live actions are allowed only when the
broker calendar confirms the current date is a trading day, preventing a local
pre-open/after-close label from allowing holiday submits. This is market-session
safety only; it does not restore PDT day-count or fixed dollar caps. Focused
proof:
`uv run --no-sync --with pytest python -m pytest -q tests/test_execution_safety.py
tests/test_live_gate.py
tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_live_buy_requires_submit_guard
tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_live_submit_uses_tiny_live_idempotency_key
tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_tiny_live_guard_blocks_reconciliation_mismatch
tests/test_alpaca_cli.py::test_live_submit_call_sites_stay_behind_unified_gate`
passed with 43 tests.

2026-06-04 stale-quote candidate follow-up: the aggressive-candidate yfinance
fetcher now labels its `5d/1d` daily-bar rows with quote freshness metadata.
During tradeable sessions it sets `quote_fresh=false`, `stale_quote=true`, the
session label, and a stale reason; `build_candidate_signals(...)` skips rows
explicitly marked stale/not fresh. This preserves daily closes for closed-market
overnight context but prevents stale daily bars from becoming in-session
paper/live buy candidates. Focused proof:
`tests/test_alpaca_supervisor.py::test_build_candidate_signals_excludes_explicitly_stale_quote_rows`
and
`tests/test_alpaca_cli.py::test_fetch_aggressive_candidate_market_data_marks_daily_bars_stale_during_tradeable_session`
passed, and targeted Ruff passed.

2026-06-04 intraday quote replacement follow-up: the stale-quote guard now has
a fresh-price path. During tradeable sessions `_fetch_aggressive_candidate_market_data()`
requests yfinance `1d/5m` with `prepost=true`; if the latest intraday bar has a
parseable timestamp within 30 minutes, the row uses that current price, source
`yfinance:1d-5m-prepost`, `bar_interval=5m`, and `quote_fresh=true`. If the
intraday fetch fails, has no close, has no timestamp, or is older than the
freshness window, the row remains `stale_quote=true` and is refused by
`build_candidate_signals(...)`. Focused proof:
`tests/test_alpaca_cli.py::test_fetch_aggressive_candidate_market_data_uses_fresh_intraday_bar_during_tradeable_session`
plus the stale daily-bar/scorer regressions passed; broader
`tests/test_alpaca_cli.py tests/test_alpaca_supervisor.py` passed with 133
tests.

2026-06-04 Alpaca market-data quote follow-up: `tradingagents.dataflows.alpaca_market_data`
now provides a read-only `fetch_alpaca_latest_trades(...)` adapter against
Alpaca's stock latest-trades data endpoint. It emits analysis-only evidence with
`execution_authority=none` and forbidden order effects. During tradeable sessions
the aggressive-candidate feed now prefers a fresh Alpaca latest-trade row,
falls back to yfinance `1d/5m` when Alpaca is missing or stale, and leaves the
row stale when no fresh provider is available. Focused proof:
`tests/test_alpaca_cli.py::test_fetch_aggressive_candidate_market_data_prefers_fresh_alpaca_latest_trade`
and
`tests/test_alpaca_cli.py::test_fetch_aggressive_candidate_market_data_falls_back_when_alpaca_latest_trade_is_stale`
passed; broader
`tests/test_alpaca_cli.py tests/test_alpaca_supervisor.py tests/test_research_provider_orchestrator.py`
passed with 154 tests. A real read-only simulated-regular probe produced 35
rows and marked after-hours yfinance `5m` bars stale instead of rankable.

---

## P4 — MiroFish ingestion (GATED: execute only when the real run completes) 🔗

```
MISSION: Turn the completed MiroFish run into advisory research priors for TradingAgents. Grow research/mirofish_handoff.py from a status-reader into an ingester. ADVISORY ONLY — never order-wired.

EVIDENCE: research/mirofish_handoff.py (161 LOC) currently only reads reports/mirofish/MIROFISH_PENDING_LEARNING_SCAFFOLD.md and returns status (build_mirofish_handoff_status -> "pending_final_handoff" until _final_handoff_available). The scaffold defines the exact final-handoff contents (scenario branches, ticker/category attention map, false-positive patterns, daily validation checklist June 4-13, machine-readable advisory packet) and a HARD BOUNDARY: advisory only, fail-closed, stocks/long/limit-only, never create/size/submit/promote orders from it. Existing refs: research/market_mirror.py, market_structure.py, evals/real_simulation_audit.py, orchestration/n8n_*.py, cli/main.py.

PRECONDITION (do not proceed until true): the real MiroFish Stage 03 + ReportAgent + interviews are done and a final handoff file exists (build_mirofish_handoff_status returns ready, not pending_final_handoff / blocked_missing_scaffold).

TASK (when precondition met):
1. Extend mirofish_handoff.py to parse the final handoff into structured advisory objects: scenario branches + probabilities, ticker/category attention map, false-signal filters, retail-flow hypotheses, daily validation tasks.
2. Route them, advisory-only:
   - research priors -> research/memory.py (same lane as market-mirror/social overlays)
   - scoreable forecasts -> evals/agent_intelligence_ledger.py so MiroFish's June 4-13 calls get RESOLVED vs actual outcomes like any agent (treat "MiroFish" as a forecasting source)
   - watchlist + daily validation tasks -> consumed by overnight planning (P3 prior-feed)
3. Fill the scaffold's "Current Missing Pieces"; flip its status to final/ingested; keep the source artifact paths.

DO NOT: connect any MiroFish output to order creation/sizing/submission/promotion; bypass live gates; treat the scaffold as trade truth.
VERIFY: ingestion test with a sample final handoff fixture; MiroFish forecasts appear in the ledger and later resolve; a dry-run overnight plan shows MiroFish-derived watch/validate items tagged advisory; full suite green.
DELIVER: parser + routing code, ledger entries created, advisory packet path, explicit "no execution authority" confirmation.
```

2026-06-04 final-handoff checkpoint: the accepted MiroFish advisory handoff is
now `report_9c77ca2557ae` at
`reports/mirofish/MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md`. It is normalized
into advisory scenario branches, validation tasks, false-signal filters, ticker
attention, and source-artifact pointers for the June 4-13 window. The parser
also reads the full Stage 04 `full_report.md` and exposes a compact
AI-bot-copycat / institutional-liquidity filter: treat social and prompt-bot
momentum as false-signal risk until independent volume, broker/API execution,
options liquidity, and institutional participation confirm durable flow. The
Stage 04 prose section `AI-Bot Correlation and Institutional Liquidity
Adaptation` is now preserved in compact context as
`full_report_ai_bot_liquidity_summary`; reports for the June 4-13 window should
assume market makers may fade, absorb, or briefly amplify obvious bot-crowded
novice flow to manage order-flow toxicity. n8n `mirofish_handoff_status` returns
`submit_capable=false`, final handoff true, the review packet zip path,
acceptance decision path, the full-report core filter, and the prose-section
summary. The parser now also records all discovered `full_report.md` candidates
with hashes in `full_report_candidate_reports`: the selected canonical backend
report is `f118ff9a38464f1687e205be426395c0b0867ae7e26f3972c1f5d3f78061e5df`,
and the explicit Downloads copy is
`d24e9841b5f0533eab680b7eb8a33851b0ea01e99a245f7cd7d49fd8621af7af`.
Execution authority remains `none`; MiroFish output never creates,
sizes, submits, or promotes orders. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_mirofish_handoff.py tests/test_alphainsider.py
tests/test_paper_tournament.py tests/test_automation_context_snapshot.py
tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_mirofish_handoff_json
tests/test_research_crawler_social.py::test_overnight_summary_carries_structured_mirofish_attention_priors`
passed with 49 tests; Ruff passed; real status packet
`results\mirofish_handoff\latest.json` shows `final_handoff_available=true`,
`advisory_valid_window=2026-06-04 through 2026-06-13`, and
`full_report_highlight_available=true`.

2026-06-04 Deep Research report-33 overlay checkpoint: the MiroFish handoff
ingester now also discovers and reads
`C:\Users\Corbin\Downloads\deep-research-report (33).md`. The compact advisory
payload carries `deep_research_report_33` with a macro-first stock-selection
overlay for the next 7-10 days: prefer validated relative strength and risk
control over heroic directional bets; treat the June 4 rule/PDT change as
secondary until broker behavior, flow, options interest/IV/spreads, and price
response confirm it. The overlay adds stock-selection biases (positive:
Dow/quality/energy/defensives; negative/cautious: QQQ/Nasdaq, semis/SOXX/SMH,
crowded AI beta; event-sensitive watch: `HOOD`, `BULL`, `IBKR`, `SCHW`),
selection rules, risk controls, validation requirements, limitations, and any
parsed directional/practical decision tables. It is threaded into
`build_mirofish_handoff_status`, `build_mirofish_source_context_packet`,
overnight research context summaries, compact context snapshots, CLI JSON, and
n8n `mirofish_handoff_status`. Execution authority remains `none`.
Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_mirofish_handoff.py
tests/test_research_crawler_social.py::test_overnight_summary_carries_structured_mirofish_attention_priors
tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_mirofish_handoff_json
tests/test_alpaca_cli.py::test_verify_overnight_system_warns_when_original_graph_requested_but_disabled`
passed as part of a 12-test focused batch, and the later department sweep
passed with 156 tests.

2026-06-04 ranking-overlay follow-up: report-33 and MiroFish priors are now
applied before overnight candidate scoring, not only displayed in status
packets. The helper tags market rows with `macro_event_risk`,
`mirofish_bot_correlation`, and `deep_research_crowded_ai_beta` when the
handoff/report evidence calls for it. `build_candidate_signals(...)` then
downranks unconfirmed prompt-bot/social copycat attention and crowded AI-beta
names during macro-event risk, while preserving controlled-dip preference and
green-spike anti-chase behavior. This is advisory ranking only:
`execution_authority=none`, no action creation, no sizing, no submission, and
no promotion bypass. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_alpaca_cli.py::test_mirofish_market_priors_tag_bot_attention_and_crowded_ai_beta
tests/test_alpaca_supervisor.py::test_build_candidate_signals_prefers_controlled_dip_over_green_spike
tests/test_alpaca_supervisor.py::test_build_candidate_signals_downranks_bot_copycat_ai_beta_without_confirmation`
passed with 3 tests; the overnight-planning regression slice passed with 5
tests after the planner was reordered to apply priors before scoring.

2026-06-05 positive-relative-bias follow-up: report-33's constructive side is
now part of the same advisory ranking path. When the Deep Research review says
the next few days favor Dow/quality/energy/defensive relative setups, market
rows in those buckets receive `deep_research_positive_relative_bias`.
`build_candidate_signals(...)` gives that flag a small score boost only when the
row is not a green spike and not a falling knife, so it supports controlled dips
and steady relative-strength candidates without rewarding chase behavior. `CVX`
was added to the liquid stock universe alongside `XOM` for selective energy
coverage. Fresh proof: `research mirofish-handoff-status --json-output` wrote
`results\mirofish_handoff\research-intel-research-intel-670b65db8e334d2ebf2ad8edb1e04d4a.json`
with report-33 positive and negative bias maps; `alpaca verify-overnight-system
--json-output` wrote
`results\overnight_system_verification\overnight-system-verification-20260605-040252.json`
with `overall_status=pass`; `research source-quality-review --json-output`
wrote `results\source_quality\source-quality-review-20260605-090250.json` with
`source_count=250`, `blocked_count=62`, and `stale_needs_refresh_count=0`;
`research walk-forward-refresh-overnight-cohort ...` wrote
`results\research_batches\walk_forward_cohort_refresh_20260605-090325_h3.json`.
Focused scorer/MiroFish tests passed with 19 tests, targeted Ruff passed, and
full pytest passed with 883 tests, 1 skipped live-key test, 9 warnings, and 75
subtests.

2026-06-04 qualitative-index follow-up: qualitative MiroFish report warnings
are now first-class advisory evidence. `research/mirofish_handoff.py`
canonicalizes telemetry names from the handoff/full report and maps
observed-but-nonnumeric indices to an elevated advisory value instead of
dropping them as zero. This closes the failure mode where `AI_bot_copycat_index`
and `false_signal_risk_index` were present in the report but the advisory gate
still returned `allow`. Latest real status now returns
`mirofish_advisory_gate_action=suppress` and triggered gates
`broker_friction`, `macro_override`, and `attribution_error`; this remains
advisory-only with no order, size, promotion, or live-gate authority.

2026-06-07 future-report guard follow-up: the MiroFish handoff required-report
guard is no longer code-stuck on the June 4 report. The current accepted report
id remains `report_9c77ca2557ae`, but automations can now advance to a newer
MiroFish handoff by setting `TRADINGAGENTS_MIROFISH_REQUIRED_REPORT_ID` or by
passing `research mirofish-handoff-status --required-report-id ...`. Empty
values intentionally disable the report-id guard only for explicit repair/debug
runs. This keeps tomorrow's overnight/premarket bots able to read the current
final handoff while preventing the next final MiroFish run from being silently
ignored until a code edit lands. Real proof:
`research mirofish-handoff-status --json-output` wrote
`results\mirofish_handoff\research-intel-research-intel-9d3206b3149e42fa96319e315fe8d6c6.json`
with `final_handoff_available=true`,
`required_report_id=report_9c77ca2557ae`, `scenario_branch_count=7`,
`validation_task_count=12`, and `execution_authority=none`. Focused proof:
`uv run --isolated --with pytest pytest -q tests/test_mirofish_handoff.py`
passed with 12 tests; targeted Ruff and compile checks passed for the touched
MiroFish/CLI files.

---

## P5 — Global lossless token compression (compounding, ongoing)

```
MISSION: Cut context/token weight repo-wide with ZERO information loss — only de-duplication + indirection. Extends the existing TOKEN_EFFICIENCY_AUDIT.md.

EVIDENCE (their own audit): result packets are the big sink (results/overnight_plans/latest.json ~228KB; premarket ~58KB), automation memories grow unbounded (hourly ~111KB), and 14 overlapping root .md docs are the #1 rebuild cost. AGENTS.md/CONTEXT_ROUTER.md + the snapshot helper already started this.

TASK (lossless only — every change must be reversible / no field dropped):
1. Reference, don't restate: large result packets store IDs + compact deltas + source pointers instead of repeated payloads (audit "next pass" items 2-3, esp. premarket_brief.source_packets). Keep raw archives; summaries point to them.
2. Memory rollup/pruning policy for automation memory files: periodic compaction to a rolled-up digest + retained raw archive; readers take tails/summaries. No history deleted, just relocated.
3. Consolidate root-doc sprawl into CONTEXT_ROUTER.md as the single hub: fold the THREE TOKEN_EFFICIENCY_* docs into one; archive dated evidence packets/checklists (GOOGL_*, TUESDAY_*) under docs/. Do NOT create new root docs.
4. Add --compact-json-output to high-traffic CLI commands (supervise-hourly, plan-overnight, premarket-brief, supervisor-daily-report) so automations emit compact machine summaries directly instead of agents re-summarizing fat packets.

DO NOT: drop operational evidence fields; change packet semantics; touch broker/strategy logic.
VERIFY: measured byte reduction per packet family with a ROUND-TRIP test proving the compact form reconstructs/points to every original field (lossless); CONTEXT_ROUTER remains the only orientation doc needed; full suite green.
DELIVER: before/after byte table per family, round-trip test, doc-consolidation map, new --compact-json-output flags.
```

Checkpoint 2026-06-04: first lossless-proof slice landed. `scripts/automation_context_snapshot.py`
now writes `results/_context/field-provenance.json` and lists it in
`context-manifest.json`. The provenance artifact maps every compact
`latest-summary.json.latest_packets[*]` field to either a raw packet field,
raw file metric, drilldown rule derivation, or explicit missing-packet marker.
This does not compact or mutate raw result packets; it makes the existing
summary-first path auditable. Proof: `uv run --no-sync --with pytest python -m
pytest -q tests/test_automation_context_snapshot.py tests/test_token_context_hooks.py
tests/test_n8n_runner_policy.py` passed with 58 tests; Ruff, broad mypy, and
`py_compile scripts/automation_context_snapshot.py` passed. Full-suite baseline
before this slice passed with 703 tests, 1 skipped live-key test, 9 warnings,
and 75 subtests.

Checkpoint 2026-06-04: the first high-traffic compact CLI output flag landed for
`alpaca plan-overnight`. `--compact-json-output` works with `--json-output` and
prints `compact_overnight_plan_v1` instead of the full overnight packet. The
compact form includes raw packet path, counts, top candidate, ticker status
counts, selected overnight-quality fields, research-context counts, and
`raw_field_groups`; raw packet writing is unchanged, so the compact output is
lossless by reference. Real analysis-only probe:
`tradingagents alpaca plan-overnight --json-output --compact-json-output
--full-graph-tickers 0 --no-research-context --no-agent-ledger --no-write-latest
--log-dir results\overnight_plans\compact_probe` wrote compact stdout pointing
to `results\overnight_plans\compact_probe\overnight-plan-20260604-033601-000000.json`;
`submitted_count=0`, `ticker_results=35`, `fallback_count=35`, and
`execution_authority="none"`. Focused proof: compact helper/CLI tests and the
broader `plan_overnight` test slice passed; Ruff and compile checks passed.
Remaining P5 work: add the same compact flag pattern to `supervisor-daily-report`,
plus byte-reduction tables.

Checkpoint 2026-06-04: `alpaca premarket-brief` also supports
`--compact-json-output`. The compact form prints `compact_premarket_brief_v1`
with raw packet path, source/timeline/blocker/material-change counts, compact
premarket instruction fields, stale warnings, and raw-field group pointers while
leaving the raw brief packet unchanged. Real file-only probe:
`tradingagents alpaca premarket-brief --json-output --compact-json-output
--no-write-latest --log-dir results\premarket_briefs\compact_probe
--hourly-log-dir results\hourly_supervisor --overnight-log-dir
results\overnight_plans --paper-tournament-log-dir
results\paper_strategy_tournament` wrote compact stdout pointing to
`results\premarket_briefs\compact_probe\premarket-brief-20260604-034911-000000.json`;
`source_packets=54`, `unresolved_blockers=0`, `stale_warnings=0`, and
`execution_authority="none"`. Focused proof: compact helper/CLI premarket tests
passed with 5 selected tests; Ruff and compile checks passed.

Checkpoint 2026-06-04: `alpaca supervise-hourly` also supports
`--compact-json-output`. The compact form prints
`compact_hourly_supervisor_v1` with raw packet path, decision, materiality,
submission/issue/action counts, compact live/paper portfolio counts, top
candidate, overnight/premarket/tournament/BOARD context refs, live-budget mode,
risk posture, and alert state while leaving the raw hourly packet unchanged.
Real dry-run probe:
`tradingagents alpaca supervise-hourly --dry-run --json-output
--compact-json-output --log-dir results\hourly_supervisor\compact_probe
--overnight-log-dir results\overnight_plans --paper-tournament-log-dir
results\paper_strategy_tournament --premarket-brief-log-dir
results\premarket_briefs --execution-board-dir results\execution_board` wrote
compact stdout pointing to
`results\hourly_supervisor\compact_probe\hourly-supervisor-20260604-040457-404346.json`;
`decision="hold"`, `submitted_count=0`, `issue_count=0`,
`market_session="closed"`, and live budget `mode="autonomous_uncapped"`.
Focused proof: compact helper/CLI hourly tests passed with 2 selected tests,
the broader `supervise_hourly` test slice passed with 11 tests, Ruff and compile
checks passed.

Checkpoint 2026-06-04: `alpaca supervisor-daily-report` also supports
`--compact-json-output`. Because the prior daily-report command did not write a
raw packet, compact mode now writes the full report JSON under
`results\daily_reports` (or `--daily-report-log-dir`) and prints
`compact_supervisor_daily_report_v1` with raw packet path, subject, body
length/ref, hourly packet counts, compact live/paper portfolio counts, top
candidate, paper tournament, premarket brief, model telemetry, and BOARD refs.
Existing non-compact `--json-output` and plain-text behavior remain unchanged.
Real account-read-only probe:
`tradingagents alpaca supervisor-daily-report --json-output
--compact-json-output --daily-report-log-dir
results\daily_reports\compact_probe --log-dir results\hourly_supervisor
--paper-tournament-log-dir results\paper_strategy_tournament
--premarket-brief-log-dir results\premarket_briefs
--model-telemetry-report-dir results\model_telemetry_reports
--execution-board-dir results\execution_board` wrote compact stdout pointing to
`results\daily_reports\compact_probe\supervisor-daily-report-20260603-231950-817954.json`;
`body_summary.char_count=1998`, `ranked_candidates=35`,
`top_candidate=GOOGL`, and `execution_board.can_submit_orders=false`. Focused
proof: compact helper/CLI daily tests passed with 3 selected tests, the broader
daily-report test slice passed with 4 tests, Ruff and compile checks passed.
Remaining P5 work: byte-reduction tables and follow-on automation/n8n adoption
of the compact flags.

Checkpoint 2026-06-04: the compact-output byte-reduction table is now generated
by `alpaca compact-output-audit`, not hand-maintained. Real audit:
`results\token_efficiency\compact-output-audit-20260603-233723-460063.json`
and `.md` measured four compact families against their raw packets:
hourly supervisor `26,105 -> 2,423` bytes (`90.72%` reduction), overnight plan
`300,962 -> 1,366` bytes (`99.55%`), premarket brief `74,980 -> 946` bytes
(`98.74%`), and daily report `133,415 -> 2,111` bytes (`98.42%`). Total:
`535,462 -> 6,846` bytes, `528,616` bytes saved, every row
`lossless_by_reference=true`. Focused proof: compact-output audit/helper tests
passed with 5 selected tests; Ruff and compile checks passed. Remaining P5
work: follow-on automation/n8n adoption of compact flags and n8n evaluation
datasets for all automation wrappers.

Checkpoint 2026-06-05: the source-quality review joined the compact-output
contract used by automations and n8n. `research source-quality-review
--json-output --compact-json-output` now writes the full raw review under
`results\source_quality\` while stdout emits `compact_source_quality_review_v1`
with raw packet path, counts, quality/freshness maps, a small flagged-source
sample, and raw-field group pointers. The n8n allowlisted
`source_quality_review` job now calls the compact flag and preserves the compact
schema plus raw packet path in `parsed_summary`. Real CLI proof:
`results\source_quality\source-quality-review-20260605-092148.json`; real n8n
bridge proof: `results\source_quality\source-quality-review-20260605-092211.json`
with `source_count=250`, `stale_count=88`, `stale_needs_refresh_count=0`,
and `submit_capable=false`. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q tests/test_source_quality.py
tests/test_n8n_runner_policy.py` passed with 46 tests, and Ruff passed on the
touched CLI/eval/n8n/test files. Full-suite proof after the slice:
`885 passed, 1 skipped, 9 warnings, 75 subtests passed`. Remaining P5 work:
run the editor-side n8n Evaluation Trigger workflow after login when a visible
quality-score run is needed, and keep adopting compact flags for any newly added
high-volume automation command.

Checkpoint 2026-06-06: automation-health joined the compact-output/n8n contract.
`research automation-health-audit --json-output --compact-json-output` now
prints `compact_automation_health_audit_v1` with raw packet path, summary
counts, problem/attention automation IDs, self-heal timeliness, and
`raw_field_groups`; the full raw audit and Markdown are still written unchanged.
The n8n allowlist now calls the compact flag for `automation_health_audit`, and
the n8n bridge accepts both the old full packet and the new compact schema.
Real bridge proof:
`python -m tradingagents.orchestration.n8n_runner --run-job automation_health_audit`
returned parsed schema `compact_automation_health_audit_v1`, `submit_capable=false`,
`submitted_order_count=0`, and only `tradingagents-night-shift-supervisor` as
the attention/problem automation. The real compact-output audit now measures 5
families at
`results\token_efficiency\compact-output-audit-20260606-154240-507832.json`:
total `8729059 -> 9568` bytes, `8719491` bytes saved, and
`automation_health_audit` alone `14662 -> 1140` bytes (`92.22%` reduction),
all `lossless_by_reference=true`. Focused proof:
`tests/test_alpaca_cli.py::test_compact_output_audit_measures_packet_families`
plus n8n runner/evaluation tests passed with 48 tests, and targeted Ruff passed.

Checkpoint 2026-06-04: automation-health run-id inference is hardened.
`tradingagents\evals\automation_health_audit.py` now preserves
microsecond-suffixed packet filenames such as `20260601-010550-274605`, ignores
generic `latest/current` pointer filenames, keeps explicit payload `run_id`
values authoritative, and supports Python 3.10 via the `tomli` fallback declared
in `pyproject.toml`. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_automation_health_audit.py` passed with 18 tests; Ruff, compile, and
strict mypy on `tradingagents/evals/automation_health_audit.py` passed. Real
automation-health proof
`results\automation_health\automation-health-audit-20260604-165711.json`
reported `ok_count=13`, `duplicate_count=0`, `submitted_order_count=0`, and
`issue_count=0`; harmless hourly no-action/no-issue duplicates are de-noised only
when the automation memory covers the latest packet, while duplicates with
submissions or issues stay degraded.

Checkpoint 2026-06-04/05: n8n evaluation datasets are now wired into the local
dashboard/control plane with a reproducible API sync path. `research
n8n-evaluation-dataset --json-output --compact-json-output` writes full
JSON/CSV/Markdown artifacts under `results\n8n_evaluations\` and prints
`compact_n8n_evaluation_dataset_v1` instead of all rows. The current dataset
has 183 Data Table-ready rows across 20 allowlisted jobs, 17 edge tags, 23
columns, and negative runner-policy cases. The six writable actual-output
columns for n8n Set Outputs are `actual_http_status`, `actual_status`,
`actual_json`, `actual_quality_score`, `actual_checked_at`, and `actual_error`.
The source-controlled workflow `TA · Built-in Automation Evaluation` uses n8n's
native Evaluation Trigger, HTTP Request, Code, Evaluation Set Outputs, and
Evaluation Set Metrics nodes; it imports cleanly into local n8n and stays
inactive until an explicit editor/evaluations run. The n8n runner exposes the full
row packet at `/evaluation-dataset`, while `/run` remains compact by default.
`research n8n-sync-evaluation-table --json-output` creates or refreshes the
local n8n Data Table `TradingAgents_Automation_Evaluations` through n8n's public
API and writes a redacted proof packet to `results\n8n_evaluations\latest-sync.json`.
The allowlist now includes compact observer previews for the high-traffic
broker commands: `hourly_supervisor_dry_run_preview`, which is forced to
`--dry-run`; `overnight_plan_compact_preview`, which is forced to zero graph
tickers, no latest pointer, no ledger writes, and no research context; and
`premarket_brief_compact_preview`, which is forced to no latest pointer. n8n
built-in Evaluation Trigger workflows still need to be run from the editor
after login; CLI/MCP execution is not the acceptance gate for those nodes. Real
CLI probes found the expected limitation: `n8n execute` conflicts with the
running task-broker port, and with a separate broker port reports `Missing node
to start execution` because an Evaluation Trigger is not an Execute Workflow
Trigger. Focused proof updated 2026-06-05: `uv run --no-sync --with pytest python
-m pytest -q tests/test_n8n_evaluations.py tests/test_n8n_runner_policy.py
tests/test_real_simulation_audit.py` passed with 58 tests. Real compact CLI proof
wrote `results\n8n_evaluations\n8n-evaluation-dataset-20260605-123501-987045.json`.
The local n8n Data Table has since been refreshed through the public API using
a temporary SQLite-key copy without printing or storing the key; current
redacted proof
`results\n8n_evaluations\n8n-api-sync-20260606-205308-805632.json` reports
`expected_row_count=183`, `final_row_count=183`, `row_count_matches=true`,
`column_count=23`, and `api_key_redacted=true`. Workflow sync proof
`results\n8n_evaluations\n8n-workflow-sync-20260606-210202-886336.json`
created inactive source-controlled observer workflows for the local dashboard.
Compact context now summarizes that proof under `n8n_evaluation_dataset`:
`row_count=183`, `column_count=23`, `has_actual_output_columns=true`,
`sync_status=ok`, `sync_current_row_count_matches=true`,
`workflow_sync_status=ok`, and redacted API-key fields.
Future agents should inspect `results\_context\latest-summary.json` first and
open raw n8n packets only when the compact n8n fields flag a schema, sync,
row-count, or redaction problem. Focused context/n8n proof passed with 76 tests,
and the full post-change suite passed with 896 tests, 1 skipped live-key test,
9 warnings, and 75 subtests.
Native n8n test-run start is still editor-session-bound: a redacted public API
probe with the local SQLite API key returned `404` for the public `/api/v1`
test-run routes and `401` for the internal `/rest` test-run routes, so the next
real built-in evaluation execution must be started from the n8n
editor/evaluations UI unless n8n exposes a public API or CLI command later.

Checkpoint 2026-06-05: the morning overnight/controller gap was repaired and
verified against real packets. Root cause was twofold: the overnight schedule
missed its 2:30 AM run, and automation-health treated a date-only wake-controller
memory as midnight instead of using the memory file write time. The catch-up ran
the Google compact original-graph route and wrote
`results\overnight_plans\overnight-plan-20260605-101740-000000.json`; top
candidates were `KO`, `IBM`, `HD`, `CVX`, and `XOM`, with `3` full graph
successes, `33` fallback rankings, `graph_failure_count=0`, and `submitted=[]`.
The verifier now accepts `tradingagents-overnight-planning=PAUSED` after a
complete analysis-only packet exists; real proof:
`results\overnight_system_verification\overnight-system-verification-20260605-061215.json`.
The native automation tool set `hourly-market-supervisor` and
`paper-strategy-tournament-runner` ACTIVE for the market day, set
`tradingagents-overnight-planning` PAUSED after the catch-up, and simplified
`tradingagents-self-heal-monitor` to `RRULE:FREQ=HOURLY;INTERVAL=1;BYMINUTE=15;BYDAY=SU,MO,TU,WE,TH,FR,SA`.
Focused proof: `tests/test_automation_health_audit.py` passed with `20` tests,
`tests/test_alpaca_cli.py::test_verify_overnight_system_audits_full_chain`
passed, and real self-heal wrote
`results\self_heal\plans\self-heal-plan-20260605-111239.json` with no order,
email, secret, or automation-status authority.

Remaining controller risk after the checkpoint: `tradingagents-night-shift-supervisor`
still reports stale memory from `2026-06-04T05:19:18+00:00`. Treat it as a real
missed patrol signal until the native scheduler creates a fresh night-shift
thread or a future controller-health repair adds direct app-run evidence. Do not
manually edit the night-shift memory file just to clear the flag.

2026-06-05 night-shift schedule repair: the existing Codex automation was
updated through the automation app so the night-shift patrol runs on the intended
four-hour cadence instead of only at three daily hours. Verification:
`C:\cm\automations\tradingagents-night-shift-supervisor\automation.toml` now
shows the expanded cadence, and
`results\automation_health\automation-health-audit-20260605-113550.json`
correctly still reports `stale_memory` until a genuine native night-shift run
writes fresh evidence. This is a timeliness repair, not a fake clearance.

2026-06-05 night-shift cadence guard: automation health now detects a recurring
config drift where the night-shift schedule skips part of the intended
four-hour cadence. A bad `0,4,20` schedule produces
`night_shift_cadence_mismatch`; the corrected `0,4,8,12,16,20` schedule stays
clean. Focused proof: `uv run --no-sync --with pytest python -m pytest -q
tests/test_automation_health_audit.py` passed with 22 tests, and real proof
`results\automation_health\automation-health-audit-20260605-114237.json` shows
the live automation has no cadence warning while still preserving the real stale
memory signal.

2026-06-05 night-shift evidence repair: the controller-health repair now has the
direct evidence bridge that the prior checkpoint called out. The active
`tradingagents-night-shift-supervisor` prompt runs
`.venv\Scripts\tradingagents.exe research night-shift-patrol --json-output`
after compact context refresh. The command writes an analysis-only packet under
`results\night_shift_patrol\` with `can_submit_orders=false`,
`execution_authority=none`, and `submitted_count=0`; automation health consumes
that packet as native schedule evidence. Focused proof:
`tests/test_automation_health_audit.py` plus
`tests/test_alpaca_cli.py::test_research_night_shift_patrol_writes_analysis_only_packet`
passed with 24 tests, Ruff passed on touched files, real packet
`results\night_shift_patrol\night-shift-patrol-20260605-135243.json` wrote
successfully, and
`results\automation_health\automation-health-audit-20260605-135301.json` moved
night-shift from stale to partial with `actual_artifact_count=1`. Full-suite
proof passed with `899 passed, 1 skipped, 9 warnings, 75 subtests passed`. Do not
backfill old missed patrols; let future native scheduler runs create fresh
packets.

2026-06-05 wake/sleep controller evidence repair: controller evidence is no
longer memory-only. `research controller-patrol --automation-id
tradingagents-automation-wake-controller --json-output` and the matching sleep
controller id write analysis-only packets under `results\control_plane_patrol\`
with `can_submit_orders=false`, `execution_authority=none`, and
`submitted_count=0`. Automation health now consumes
`wake-controller-patrol-*.json` and `sleep-controller-patrol-*.json` while still
accepting legitimate controller memory. The active wake and sleep controller
prompts were updated through the automation app to write these packets after
status-only controller work. Focused proof passed with 26 tests and Ruff passed.
Real proof: `results\control_plane_patrol\wake-controller-patrol-20260605-143624.json`
and `results\automation_health\automation-health-audit-20260605-143645.json`,
where the wake controller is `ok` with `actual_artifact_count=1`, global
`stale_count=0`, and only night-shift remains partial because old missed patrols
were not backfilled. Full-suite proof after this slice passed with `901 passed,
1 skipped, 9 warnings, 75 subtests passed`.

2026-06-05 real-simulation follow-up: after the cadence guard and uncapped
live-budget repair, `research real-simulation-audit --top-symbols KO,IBM,HD,CVX,XOM`
wrote `results\real_simulation_audits\real-simulation-audit-20260605-115602.json`.
It covered 8 departments and 28 commands with zero failed commands, zero
submitted orders, no unsafe submission evidence, all required structured output,
and stale sources safe/downranked. The packet now separates core acceptance from
optional helper availability: `acceptance.accepted=true`,
`core_accepted=true`, `optional_helper_degraded=true`, and
`strict_optional_model_accepted=false` because the Mac DeepSeek helper timed out
over Tailscale. This keeps the market workflow usable while making the lost
cheap-helper lane visible.

2026-06-05 final verification checkpoint: process review
`results\process_reviews\process-review-20260605-153745.json` reports
`unchecked_step_count=0`; compact context refresh opens the current hourly
`loss-review`, `results\execution_board\latest.json`, and
`results\automation_health\latest.json`. Full pytest passed with
`903 passed, 1 skipped, 9 warnings, 75 subtests passed`. The latest hourly packet
`results\hourly_supervisor\hourly-supervisor-20260605-115730-204920.json` is a
loss-review hold with zero actions, zero issues, and zero submissions, so the
system did not sell a loser without BOARD/manual thesis-break evidence.

2026-06-05 compact BOARD drilldown repair: compact context now treats an active
hourly `decision="loss-review"` as a `board_review` drilldown instead of a quiet
no-action packet. The execution-board compact summary also exposes
`latest_packet_decision` and `latest_packet_needs_review`, so automation/hook/n8n
readers know to open `results\execution_board\latest.json` when the latest
reviewed hourly packet needs BOARD/manual review. Real proof:
`results\execution_board\execution-board-review-20260605-152357.json` remained
`analysis_only=true`, `can_submit_orders=false`, and submitted 0 orders; fresh
`results\_context\latest-flags.json` opens both the hourly loss-review packet
and the BOARD packet for `board_review`. This is evidence routing only and does
not loosen loss-exit policy or grant order authority.

2026-06-06 SAFE-01 fail-closed checkpoint: Claude's submit-path handoff was
verified against current disk state and reconciled. The real local
`config/risk_envelope.yaml` now parses as `live_budget_mode="autonomous_with_caps"`,
account max `$250`, per-name `$50`, and `issues=[]`; it is ignored and must not
be committed. `results\policy\live_control.json` still has a lapsed dead-man
(`dead_man_expires_at=2026-06-04T19:57:06+00:00`), so live money is doubly
fail-closed unless the operator intentionally refreshes live control. The
standalone submit-path rate-limit module is committed on
`wip/submit-path-hardening-2026-06-05` as unsigned commit `3970998`; the shared
hardening edits remain uncommitted and verified by the targeted submit-path
slice (`159 passed`), Ruff, broad mypy, and full pytest (`903 passed, 1 skipped,
9 warnings, 75 subtests passed`). Git ignore hygiene now covers
`config/risk_envelope.yaml`, `.claude/`, `setup_n8n.py`, and
`analysis_mypy.txt`; `.codex/hooks` intentionally remains visible because it is
the repo-local compact-context hook deliverable.

2026-06-06 Claude-handoff prep refresh: the submit-path slice was rerun after
the latest dirty-tree reconciliation and now passes with `160` tests. Python
Ruff passed on the submit-path Python files/tests; `config/risk_envelope.example.yaml`
was checked through the repo loader instead of Ruff and parses as
`fixed_tranche` with `issues=[]`. Broad mypy still reports no issues across 57
broker/policy/execution/dataflow source files. Fresh verifier
`results\overnight_system_verification\overnight-system-verification-20260606-143651.json`
is `overall_status=pass`, confirms 3/3 original TradingAgents graph successes,
and records 0 submissions. Fresh n8n discovery now reports 20 allowlisted jobs and
`submit_capable_count=0`; fresh evaluation dataset
`results\n8n_evaluations\n8n-evaluation-dataset-20260606-204956-806412.json`
has 183 rows, 20 jobs, 17 edge tags, and 23 columns. Fresh automation health
`results\automation_health\automation-health-audit-20260606-193723.json` has no
missing/stale/late/timeliness issues, with only night-shift partial while patrol
history fills in. Fresh self-heal
`results\self_heal\plans\self-heal-plan-20260606-193726.json` stayed safe-plane
only and escalated order-adjacent BOARD/hourly signals. Fresh BOARD
`results\execution_board\execution-board-review-20260606-193725.json` found no
hard execution violations and 0 submitted orders, but still warns about 24
negative-live-P/L packets. Fresh source-quality review
`results\source_quality\source-quality-review-20260606-193732.json` reviewed 250
sources and found 238 stale, 75 stale-downranked, 65 blocked, and 0 invalid;
next-session research should refresh or downrank stale evidence before using it
for trade decisions.

Follow-up top-symbol refresh: analysis-only `research ticker-provider-bundle
--json-output` was run for current top overnight symbols `KO`, `IBM`, and `HD`.
Each wrote 17 source packets and a medium-quality summary packet:
`results\research_evidence\source-evidence-source-evidence-ec8d000296f048f2b8f30ddaa4c3a276.json`
for `KO`,
`results\research_evidence\source-evidence-source-evidence-955ee8e83ad144ce88eedd64ead3bbc6.json`
for `IBM`, and
`results\research_evidence\source-evidence-source-evidence-ead7e6ab12294983bc2e236a5cf16540.json`
for `HD`. IBM's crawler leg hit SEC 403 after retries and was captured as
blocked evidence rather than silent success. Fresh source-quality review after
the refresh, `results\source_quality\source-quality-review-20260606-194532.json`,
reduced stale sources from 238 to 186, increased fresh sources to 64, recorded
60 stale-downranked and 71 blocked packets, and still has 0 invalid packets.

2026-06-06 P2 walk-forward reality check: the real captured overnight cohort is
now large enough to be useful as a warning signal, not as a promotion signal.
`tradingagents research walk-forward-refresh-overnight-cohort --json-output`
wrote
`results\research_batches\walk_forward_cohort_refresh_20260606-195033_h3.json`.
It selected 12 mature overnight packets, skipped 5 not-yet-mature June 4/5
packets, collected 140 later-return rows, generated 420 fixture rows, and met
the replay sample floor. `deterministic_sleeve_only` scored 420 rows with
directional accuracy `0.3905`, false-positive rate `0.1690`, average Brier
`0.2577`, and average action-relative return `-0.3781`. The
`tradingagents_advisory_overlay` scored only 11 rows with directional accuracy
`0.4545`, false-positive rate `0.5455`, average Brier `0.2901`, and average
action-relative return `-0.2109`. Official, news/social/crawler, and Deep
Research overlays remain unavailable in this cohort. Treat this as a
decision-quality gap: keep collecting mature packets, improve calibration and
anti-crowding filters, and do not increase live influence until the resolved
evidence improves.

2026-06-06 agent-ledger/model-route checkpoint: `research agent-ledger-resolve`,
`research agent-ledger-summary`, `research model-telemetry-report`, and
`research outcome-labeling` were refreshed after the walk-forward cohort. The
ledger has 2,740 pending forecasts and 0 resolved forecasts, so every agent
influence weight remains `insufficient_history` at `1.00`. Model telemetry
`results\model_telemetry_reports\model-telemetry-report-20260606-195125-804423.json`
shows current Mac helper success on `deepseek-r1:14b`, deterministic helpers
success, Codex/thread judgment fallback, Windows local Ollama blocked because
no Windows Ollama URL is configured, and 0 resolved model usefulness outcomes.
The routing rule remains: Codex/OpenAI owns judgment, Mac DeepSeek does cheap
helper work, and paid/model route promotion waits for resolved usefulness.

2026-06-06 Claude submit-path handoff prep refresh: the handoff at
`reports\handoff\CODEX_SUBMIT_PATH_HARDENING_HANDOFF_2026-06-05.md` has been
re-read against the current branch. Standalone commit `3970998` still contains
only `tradingagents/policy/order_rate_limit.py` and
`tests/test_order_rate_limit.py`. The local fail-closed live envelope was
rechecked with the current `(envelope, issues)` loader API:
`live_budget_mode=autonomous_with_caps`, account max `$250`, per-name `$50`,
optional hard ceiling/rate-limit knobs unset, and `issues=[]`; the live-control
dead-man remains expired. Fresh focused proof: submit-path tests `160 passed`,
submit-path Ruff passed, and process review
`results\process_reviews\process-review-20260606-201150.json` reports
`unchecked_step_count=0` and `can_submit_orders=false`.

2026-06-06 P1-10 overnight-throughput checkpoint: analyst concurrency is no
longer just a threaded config flag. `tradingagents\graph\analyst_execution.py`
builds bounded analyst batches from `analyst_concurrency_limit`, and
`tradingagents\graph\setup.py` uses LangGraph `Send` fan-out with explicit join
nodes whenever the limit is greater than 1. The default/full graph remains
sequential unless the operator overrides it, while compact and market-news
overnight profiles now request `analyst_concurrency_limit=2` to overlap
independent analyst work during overnight research. Verification: 38 focused
analyst/graph/env/overnight CLI tests passed, targeted Ruff passed, and
`py_compile` passed over touched source/tests. Real no-latest overnight probe:
`results\overnight_plans\concurrency_probe\overnight-plan-20260606-201918-000000.json`
has `execution_authority=none`, `submitted_count=0`, graph profile `compact`,
and `overnight_quality.graph_config.analyst_concurrency_limit=2`. The attempted
broad graph mypy sweep found pre-existing typed-frontier issues in
graph/agent/LLM modules; it is documented as debt rather than this slice's
regression gate.

2026-06-06 n8n sync-drift checkpoint: compact context now verifies that the
latest n8n Data Table sync proof matches the **current** evaluation dataset row
count, not just the sync proof's own internal `row_count_matches=true`. This
prevents a stale green dashboard proof from hiding a regenerated evaluation
dataset. Real proof: `research n8n-sync-evaluation-table --json-output`
refreshed `results\n8n_evaluations\latest-sync.json` through the local n8n API
using the SQLite-key path with `api_key_redacted=true`, replaced the old 174-row
table with 183 current rows, and wrote
`results\n8n_evaluations\n8n-api-sync-20260606-205308-805632.json`. Refreshed
compact context now reports `row_count=183`, `sync_final_row_count=183`,
`sync_expected_row_count=183`, and `sync_current_row_count_matches=true` with no
n8n drilldown flag. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py -q`
passed with 35 tests, targeted Ruff passed, and `py_compile` passed for the
snapshot script/test.

2026-06-06 n8n workflow-sync checkpoint: source-controlled observer workflows
are now syncable into the local dashboard through n8n's public API with
`research n8n-sync-workflows --json-output`, and compact context consumes
`results\n8n_evaluations\latest-workflow-sync.json` alongside the Data Table
proof. Real proof
`results\n8n_evaluations\n8n-workflow-sync-20260606-210202-886336.json`
recorded 12 source-controlled workflows, 10 existing matches, and 2 newly
created inactive workflows: `TA · Automation Evaluations (observer)` and
`TA · Sync Evaluation Dataset (observer)`. The two legacy duplicate
`TA · Sync Evaluation Dataset` workflows are preserved as visible drift instead
of deleted silently. Compact context now flags n8n if workflow-sync proof is
missing, unsafe, non-redacted, or not `status=ok`/`dry_run`.

2026-06-06 automation-health de-noise checkpoint: compact context now separates
raw `partial_count` from `actionable_partial_count`. The known night-shift case
where real patrol packets exist but the six-window history is still filling in
is summarized as `benign_partial_automation_ids=["tradingagents-night-shift-supervisor"]`
instead of raising an automation-health drilldown every run. True missing,
late, stale, duplicate, cadence, warning, submission, issue, or self-heal SLA
signals still open the raw automation-health packet. Real refreshed context now
shows `partial_count=1`, `actionable_partial_count=0`,
`problem_automation_ids=[]`, and no automation-health flag. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py -q`
passed with 36 tests, and targeted Ruff passed.

2026-06-06 self-heal duplicate-flag de-noise checkpoint: compact context now
distinguishes self-heal escalations that are already covered by richer primary
review packets. If the self-heal plan has no active safe fixes and its only
escalations are order-adjacent `board_review` signals for `hourly` and
`execution_board_review`, the summary keeps `status=escalation_required` and
the covered labels, but sets `actionable_escalation_count=0` and does not raise
a separate `issues` drilldown. This keeps morning agents pointed at the hourly,
BOARD, and loss-review evidence packets instead of opening a duplicative
self-heal wrapper. Active safe plans, failed verification, schema violations,
or non-covered high-severity escalations still flag. Real refreshed context now
shows self-heal `escalation_count=2`, `actionable_escalation_count=0`,
`self_heal_covered_escalated_labels=["hourly","execution_board_review"]`, and
no self-heal drilldown; the actual BOARD/loss-review flags remain. Focused
proof: `uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py -q`
passed with 37 tests, and targeted Ruff passed.

2026-06-06 loss-review evidence freshness checkpoint: the current hourly
loss-review packet advanced from `hourly-supervisor-20260606-200633-594158.json`
to `hourly-supervisor-20260606-210521-309775.json`, while the existing
loss-review evidence packet still referenced the older hourly packet. The real
analysis-only refresh command, `research loss-review-evidence --json-output`,
wrote `results\loss_review_evidence\source-evidence-source-evidence-3b63e2d1943b43e6badf40a133ee361b.json`
for the latest hourly packet, kept `execution_authority=none`, and submitted no
orders. Compact context now publishes `hourly_packet_path`,
`latest_hourly_packet_path`, and `evidence_matches_latest_hourly`; a mismatch
raises a `stale` drilldown so BOARD cannot accidentally review stale evidence for
a newer hourly decision. Real refreshed context shows
`evidence_matches_latest_hourly=true` and only the intended `board_review`
drilldown for loss-review evidence. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_loss_review_evidence.py tests/test_n8n_runner_policy.py -q`
passed with 81 tests, targeted Ruff passed, `py_compile` passed, and process
review `results\process_reviews\process-review-20260606-211550.json` has
`unchecked_step_count=0`.

2026-06-06 loss-review blocker-resolution checkpoint: the evidence bridge now
distinguishes stale evidence blockers from true BOARD judgment blockers.
`tradingagents/research/loss_review_evidence.py` resolves only blocker text that
the read-only refresh actually covers: source packet IDs, company-specific news,
and earnings/guidance/filing evidence. It writes
`remaining_blockers_before_refresh`, `resolved_blockers_by_refresh`, and the
filtered `remaining_blockers`; `cli/main.py`, compact context, and the n8n
wrapper all expose the counts so dashboards do not need to open the full packet.
Real proof: `research loss-review-evidence --json-output` and
`python -m tradingagents.orchestration.n8n_runner --run-job loss_review_evidence
--json` both kept `can_submit_orders=false`, `execution_authority=none`, and
`review_allowed=false`, while showing `13 -> 10` blockers with
`resolved_blocker_count=3`. Compact context now shows
`evidence_matches_latest_hourly=true` and only the expected `board_review`
drilldown for the loss-review packet. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_loss_review_evidence.py tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py -q`
passed with 90 tests, and targeted Ruff passed.

2026-06-06 raw-packet sidecar hardening checkpoint: the submit-path regression
suite exposed a real follow-on bug from durable compact sidecars. Broad raw
packet globs such as `hourly-supervisor-*.json` could pick
`hourly-supervisor-*.compact.json`, and same-timestamp raw packets could be
ordered incorrectly by filename. The raw packet discovery helpers now skip
`.compact.json` / `latest-compact.json` sidecars for full-packet workflows and
`find_latest_hourly_packet(...)` selects by file mtime. This protects hourly
supervisor reports, reconciliation discovery, compact-output audit,
loss-review evidence lookup, provider snapshot lookup, and automation-health
artifact accounting. Real proof: the submit-path hardening suite passed with
160 tests; the compact/loss/n8n/health focused suite passed with 125 tests;
`alpaca compact-output-audit --json-output` measured four available packet
families with `can_submit_orders=false` and `execution_authority=none`; and
process review `results\process_reviews\process-review-20260606-235921.json`
has `unchecked_step_count=0`. Full regression gate also passed:
`uv run --no-sync --with pytest python -m pytest -q` -> 952 passed, 1 skipped,
9 warnings, 75 subtests; repo Ruff passed; mypy passed across 57
broker/policy/execution/dataflow files.

2026-06-06 execution BOARD freshness checkpoint: Claude's fail-closed handoff
was re-read and the current BOARD review was found stale relative to the newest
hourly loss-review packet. The old BOARD packet reviewed
`hourly-supervisor-20260606-200633-594158.json`, while the latest hourly packet
was `hourly-supervisor-20260606-210521-309775.json`. The real analysis-only
refresh command, `research execution-board-review --json-output`, wrote
`results\execution_board\execution-board-review-20260606-212113.json` with
`can_submit_orders=false`, 0 submitted orders, 0 hard violations, and the latest
hourly packet included in `review_window.newest_packet`. Compact context now
publishes `board_latest_reviewed_packet_path`, `latest_hourly_packet_path`, and
`board_matches_latest_hourly`; a mismatch raises a `stale` drilldown so n8n,
hooks, and morning agents cannot treat an old BOARD review as current. Focused
 proof: `uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py -q`
 passed with 42 tests.

2026-06-06 night-shift/self-heal timeliness checkpoint: the overnight verifier
still passes on a no-market Saturday and confirms the latest production
overnight packet is complete, Google-routed, 3/3 full-graph successful, and
analysis-only. A real automation-health audit then exposed that
`tradingagents-night-shift-supervisor` had only 2 of 5 expected patrol windows
in the last 24 hours. Compact context was too permissive here, so the night
shift partial de-noise rule now allows only a one-window history fill-in
(`observed_runs_less_than_expected:5/6` style). Multi-window gaps such as `2/6`
or the real refreshed `3/6` stay actionable and raise `automation_health`.
Real commands run: `research night-shift-patrol --json-output` wrote
`results\night_shift_patrol\night-shift-patrol-20260606-213112.json` with
`analysis_only=true`, `can_submit_orders=false`, and `submitted_count=0`;
`research automation-health-audit --json-output` wrote
`results\automation_health\automation-health-audit-20260606-213134.json` with
night-shift `status=partial`, `actual_artifact_count=3`, `expected_run_count=6`;
and `research self-heal-plan --execute-safe --json-output` classified the
automation-health signal as safe-plane evidence recording while preserving
`may_modify_automation_status=false` and `may_submit_orders=false`. Focused
proof: `uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_automation_health_audit.py tests/test_self_heal_handoff.py -q`
passed with 85 tests, targeted Ruff passed, and `py_compile` passed.

2026-06-06 overnight compact sidecar checkpoint: raw overnight packets remain
the evidence archive, but every new `write_overnight_plan_packet(...)` now also
writes a durable compact sidecar next to the raw packet plus
`results\overnight_plans\latest-compact.json` when `latest.json` is updated.
The compact payload uses the same builder as `alpaca plan-overnight
--compact-json-output`, so stdout, n8n previews, and sidecars cannot drift. The
current real overnight packet was backfilled from
`results\overnight_plans\latest.json` to
`results\overnight_plans\latest-compact.json` and
`results\overnight_plans\overnight-plan-20260605-101740-000000.compact.json`:
raw size `8,445,004` bytes, compact sidecar `2,927` bytes. Compact context now
uses the compact sidecar for the `overnight` latest-packet summary while keeping
`raw_packet_path` pointed at the full archive; it still exposes top candidate
`KO`, Google model route `explicit_google_overnight_graph`, 3/3 full-graph
successes, and zero graph failures. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py::test_overnight_packet_writer_marks_analysis_only_and_loads_latest tests/test_alpaca_supervisor.py::test_overnight_packet_writer_can_skip_latest_for_probe tests/test_alpaca_cli.py::test_compact_overnight_plan_payload_points_to_raw_packet tests/test_alpaca_cli.py::test_plan_overnight_compact_json_output_points_to_raw_packet tests/test_automation_context_snapshot.py::test_snapshot_summarizes_creator_workflow_refs_inside_overnight_packet tests/test_automation_context_snapshot.py::test_snapshot_prefers_compact_overnight_sidecar_when_present -q`
passed with 6 tests; targeted Ruff and `py_compile` passed.

2026-06-06 overnight calibration/n8n checkpoint: the current real cohort warning
is now enforced as a read-only control-plane artifact. The guard packet
`results\overnight_calibration\overnight-calibration-guard-20260606-214537.json`
summarizes the 12-packet/420-row cohort and returns `guard_decision=tighten`
because the deterministic sleeve and TradingAgents advisory overlay both have
negative action-relative returns, and the advisory overlay false-positive rate
is `0.5455`. Compact context reads `results\overnight_calibration\latest.json`,
n8n can call the allowlisted `overnight_calibration_guard` job, and the local
n8n Data Table was synced to 192 rows / 21 jobs. This is analysis-only and has
no execution authority; it prevents future agents from misreading "walk-forward
harness exists" as "increase live influence now."

2026-06-06 n8n evaluation compact sidecar checkpoint: the full n8n built-in
evaluation dataset stays available for Data Table import, but the writer now
also emits `n8n-evaluation-dataset-*.compact.json` and
`results\n8n_evaluations\latest-compact.json`. Compact context prefers that
sidecar for `n8n_evaluation_dataset`, preserving row/job/edge counts,
actual-output-column proof, Data Table sync proof, and workflow-sync proof while
pointing `raw_packet_path` at the full 192-row JSON archive. Real proof:
`research n8n-evaluation-dataset --json-output --compact-json-output` wrote
`results\n8n_evaluations\n8n-evaluation-dataset-20260606-215520-738622.json`;
`latest.json` is 290,235 bytes while `latest-compact.json` is 3,482 bytes.
Refreshed compact context reports the n8n summary from `latest-compact.json`
with `approx_tokens=871`, `has_actual_output_columns=true`,
`sync_current_row_count_matches=true`, and `workflow_sync_status=ok`. Process
review `results\process_reviews\process-review-20260606-215955.json` reports
`unchecked_step_count=0`, `can_submit_orders=false`, and no findings; the raw
n8n dataset is no longer a token hotspot. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_n8n_evaluations.py tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py -q`
passed with 94 tests; targeted Ruff and `py_compile` passed.

2026-06-06 source-quality compact sidecar checkpoint: the source-quality review
already had a compact stdout schema for n8n, but the durable latest packet still
forced Codex/process review to read the full decisions table. The writer now
emits `source-quality-review-*.compact.json` plus
`results\source_quality\latest-compact.json`, while keeping `latest.json` as the
raw evidence archive used by provider ordering. Compact context now prefers the
sidecar for `source_quality_review` and preserves the safety-critical counts
needed by overnight/morning agents. Real proof: `research source-quality-review
--json-output --compact-json-output` wrote
`results\source_quality\source-quality-review-20260606-220642.json`; raw latest
is 162,387 bytes and `latest-compact.json` is 5,259 bytes. Refreshed compact
context reads `results\source_quality\latest-compact.json` with
`source_count=250`, `fresh=141`, `stale=109`,
`stale_needs_refresh_count=0`, `blocked_count=50`, `missing_or_invalid_count=0`,
`can_submit_orders=false`, and `execution_authority=none`. Process review
`results\process_reviews\process-review-20260606-220722.json` reports
`unchecked_step_count=0`, `can_submit_orders=false`, and no findings; the raw
source-quality packet is no longer a token hotspot. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_source_quality.py tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py -q`
passed with 94 tests; targeted Ruff and `py_compile` passed.

2026-06-06 MiroFish compact sidecar checkpoint: MiroFish final handoff status is
now durable in compact context without forcing morning bots to open the full
research-intelligence packet. The CLI still writes the raw
`results\mirofish_handoff\latest.json`, but now also writes
`research-intel-*.compact.json` and `results\mirofish_handoff\latest-compact.json`.
Compact context prefers the sidecar for `mirofish_handoff_status`, preserving
final-handoff status, report id, advisory-valid window, attention/forecast
symbols, source artifact pointers, Deep Research report-33 overlay, false-signal
filters, clean-room flags, and execution authority. Real proof:
`research mirofish-handoff-status --json-output` wrote
`results\mirofish_handoff\research-intel-research-intel-f91f6680824c40bbb5d3a4388e8a2c3e.json`;
raw latest is 123,711 bytes and `latest-compact.json` is 6,926 bytes. Refreshed
compact context reads `results\mirofish_handoff\latest-compact.json` with
`final_handoff_available=true`, `missing_piece_count=0`,
`mirofish_advisory_gate_action=suppress`, triggered gates
`broker_friction`, `macro_override`, and `attribution_error`,
`deep_research_review_available=true`, `can_submit_orders=false`, and
`execution_authority=none`. Process review
`results\process_reviews\process-review-20260606-221918.json` reports
`unchecked_step_count=0`, `can_submit_orders=false`, and no findings; raw
MiroFish is no longer a token hotspot. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_mirofish_handoff.py tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py -q`
passed with 93 tests; targeted Ruff and `py_compile` passed.

2026-06-06 premarket compact sidecar checkpoint: rolling premarket briefs now
write durable compact sidecars at the packet writer, not just compact stdout.
`write_premarket_brief_packet(...)` writes `premarket-brief-*.compact.json` for
every packet and `results\premarket_briefs\latest-compact.json` only when
`latest.json` is updated; `--no-write-latest` probes leave the latest pointer
alone. Compact context prefers the sidecar for `premarket_brief`, preserving top
symbol, latest hourly decision, paper leader, source count, blocker count, and
stale-warning count while pointing to the raw packet. Real proof:
`alpaca premarket-brief --json-output --compact-json-output` wrote
`results\premarket_briefs\premarket-brief-20260606-223009-000000.json`; raw
latest is 103,292 bytes and `latest-compact.json` is 961 bytes. Refreshed
compact context reads `results\premarket_briefs\latest-compact.json` with
`top_symbol=KO`, `latest_hourly_decision=loss-review`,
`paper_tournament_leader=pullback-support`, `source_packet_count=54`,
`blockers=0`, and `stale_warnings=0`. Process review
`results\process_reviews\process-review-20260606-223113.json` reports
`unchecked_step_count=0`, `can_submit_orders=false`, and no findings; raw
premarket is no longer a token hotspot. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py::test_compact_premarket_brief_payload_points_to_raw_packet tests/test_alpaca_cli.py::test_premarket_brief_compact_json_output_is_file_only tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_premarket_brief_compact_preview_json -q`
passed with 111 tests; targeted Ruff and `py_compile` passed.

---

2026-06-06 paper tournament compact sidecar checkpoint: the paper strategy
tournament ledger now has durable compact context sidecars. `write_tournament_ledger(...)`
writes `paper-tournament-ledger.compact.json` and
`results\paper_strategy_tournament\latest-compact.json` beside the full
`paper-tournament-ledger.json` / `latest.json` evidence archive. Compact context
now prefers the sidecar for `paper_tournament`, preserving tournament id,
generated time, strategy count, paper-account baseline, top rankings, live
strategy candidate, AlphaInsider paper-watch summary, raw packet path, and
explicit `can_submit_orders=false` / `execution_authority=none`. Real proof:
`alpaca paper-tournament report --json-output --log-dir results\paper_strategy_tournament`
refreshed the ledger with `leader=pullback-support`,
`candidate_status=candidate`, `candidate_strategy=pullback-support`,
`ranking_count=3`, and `submitted_count=0`. Raw `latest.json` is 69,101 bytes;
`latest-compact.json` is 2,510 bytes; refreshed compact context reports
`approx_tokens=628`. Process review
`results\process_reviews\process-review-20260606-224426.json` reports
`unchecked_step_count=0`, `can_submit_orders=false`, and no findings, and raw
paper tournament is no longer a token hotspot. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_paper_tournament.py tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py -q`
passed with 100 tests; targeted Ruff and `py_compile` passed.

2026-06-06 night-shift health repair: automation-health now treats a changed
automation TOML as judgeable only after its `updated_at`/`created_at` effective
time. This prevents false missed-run alarms when the night-shift supervisor's
four-hour cadence was updated after earlier due windows in the 24-hour audit
window. The same pass ran the real analysis-only patrol command
`research night-shift-patrol --json-output`, producing
`results\night_shift_patrol\night-shift-patrol-20260606-225022.json` with
`can_submit_orders=false`, `execution_authority=none`, and no issues. Real
automation-health proof:
`results\automation_health\automation-health-audit-20260606-225956.json` reports
13/13 automations OK, `partial_count=0`, `missing_count=0`, `late_count=0`,
`timeliness_issue_count=0`, `submitted_order_count=0`, and night-shift
`status_reason=night_shift_latest_due_covered_history_ramp_up`. Refreshed
compact context no longer flags `automation_health_audit`; only the expected
BOARD/loss-review flags remain. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_automation_health_audit.py tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py -q`
passed with 114 tests; targeted Ruff and `py_compile` passed.

2026-06-06 capability-audit compact sidecar checkpoint: integration capability
audits now write durable compact sidecars for source/model/tool availability.
`integrations doctor --write-packet --json-output` still writes the full
redacted raw audit to `results\capability_audits\latest.json`, but now also
writes `capability-audit-*.compact.json` and
`results\capability_audits\latest-compact.json`. Compact context prefers the
sidecar for `capability_audit`, keeping env-present/missing counts, missing env
preview, integration count, MCP/Composio/Alpaca server configuration, authority
counts, `can_submit_orders=false`, `execution_authority=none`, and a raw packet
pointer. Real proof: raw latest is 39,574 bytes and `latest-compact.json` is
2,113 bytes; refreshed compact context reports `approx_tokens=529`,
`env_present_count=14`, `missing_env_count=12`, `integration_count=44`,
`docker_mcp_configured=true`, `composio_configured=true`, and
`secrets_redacted=true`. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py::test_integrations_doctor_redacts_env_and_writes_packet tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py -q`
passed with 88 tests; targeted Ruff and `py_compile` passed.

2026-06-06 research-batch compact sidecar checkpoint: generic research batch
packets now write durable compact sidecars through the shared research packet
writer. `write_research_packet(...)` keeps the raw
`ResearchBatchRunPacket` archive intact and also writes
`research-batch-*.compact.json` plus `results\research_batches\latest-compact.json`.
Compact context now prefers that sidecar for `research_batch`, preserving top
candidates, lane/source/crawler/model/fallback counts, quality-gate status,
advisory missing gates, `can_submit_orders=false`, `execution_authority=none`,
and `raw_packet_path`; raw walk-forward rows stay behind the pointer. Real
proof: regenerating the current latest research batch wrote raw
`results\research_batches\research-batch-research-batch-2c3c2a444f904e3c8fab73cb47d98d95-001.json`
at 18,281 bytes and compact
`results\research_batches\research-batch-research-batch-2c3c2a444f904e3c8fab73cb47d98d95-001.compact.json`
at 2,778 bytes. Refreshed compact context reads
`results\research_batches\latest-compact.json` with `approx_tokens=695`,
`status=success`, `fallback_actions=3`, `failed_quality_gates=[]`, and no
research-quality drilldown flag. Process review
`results\process_reviews\process-review-20260606-231826.json` reports
`unchecked_step_count=0`, `can_submit_orders=false`, and no findings; raw
research batches are no longer a token hotspot. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_research_schemas.py tests/test_automation_context_snapshot.py -q`
passed with 56 tests; targeted Ruff and `py_compile` passed.

2026-06-06 hourly compact sidecar checkpoint: hourly supervisor packets now
write durable compact sidecars through `write_hourly_decision_packet(...)`.
Future hourly runs keep the raw `hourly-supervisor-*.json` archive, write
`hourly-supervisor-*.compact.json`, and update
`results\hourly_supervisor\latest.json` plus
`results\hourly_supervisor\latest-compact.json`. The CLI compact stdout path
now delegates to the same broker helper, so there is one compact hourly schema.
Compact context now prefers `results\hourly_supervisor\latest-compact.json` for
`hourly`, preserving decision/reason/action/issue/submitted counts, alert notify
state, raw packet path, live/paper portfolio counts, context pointers,
`can_submit_orders=false`, and `execution_authority=none`. Real proof:
backfilling the current latest hourly packet wrote raw
`results\hourly_supervisor\hourly-supervisor-20260606-210521-309775.json` at
34,277 bytes and compact
`results\hourly_supervisor\hourly-supervisor-20260606-210521-309775.compact.json`
at 3,481 bytes. Refreshed compact context reads
`results\hourly_supervisor\latest-compact.json` with `approx_tokens=871`,
`decision=loss-review`, `action_count=0`, `issues=0`, `submitted=0`, and
`notify=false`; the expected BOARD-review flag remains, but the raw hourly
packet is no longer a process-review token hotspot. Process review
`results\process_reviews\process-review-20260606-233050.json` reports
`unchecked_step_count=0`, `can_submit_orders=false`, and no findings. Focused
proof:
`uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py::test_packet_writers_keep_same_second_packets_unique tests/test_alpaca_cli.py::test_compact_hourly_supervisor_payload_points_to_raw_packet tests/test_automation_context_snapshot.py::test_snapshot_prefers_compact_hourly_sidecar_but_keeps_board_flag tests/test_automation_context_snapshot.py -q`
passed with 53 tests; targeted Ruff and `py_compile` passed.

2026-06-06 automation-health compact sidecar checkpoint: automation health now
writes durable compact sidecars from the audit writer, not only compact stdout.
`write_automation_health_audit(...)` writes the full raw JSON/Markdown audit,
`automation-health-audit-*.compact.json`, and
`results\automation_health\latest-compact.json`; the CLI compact stdout path
delegates to the same builder. Compact context now prefers the sidecar for
`automation_health_audit`, preserving counts, problem/attention IDs, safe
self-heal timeliness, benign night-shift ramp-up IDs, raw packet path,
`can_submit_orders=false`, and `analysis_only=true`. Real proof:
`research automation-health-audit --json-output` wrote
`results\automation_health\automation-health-audit-20260606-233958.json` plus
compact sidecars; the real audit is 13/13 OK, `partial_count=0`,
`missing_count=0`, `late_count=0`, `timeliness_issue_count=0`, and
`submitted_order_count=0`. Refreshed compact context reads
`results\automation_health\latest-compact.json` with `approx_tokens=306` and no
automation-health drilldown flag. Process review
`results\process_reviews\process-review-20260606-234021.json` reports
`unchecked_step_count=0`, `can_submit_orders=false`, and no findings; raw
automation health is no longer a token hotspot. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_automation_health_audit.py tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py -q`
passed with 119 tests; targeted Ruff and `py_compile` passed.

2026-06-06 BOARD compact-sidecar freshness repair: after hourly compact
sidecars landed, the execution BOARD loader was accidentally eligible to read
`hourly-supervisor-*.compact.json` as if it were a raw hourly packet. The loader
now only reads raw `hourly-supervisor-*.json` packets and explicitly excludes
`.compact.json` and latest pointers. Compact context freshness checks now compare
BOARD/loss-review evidence against the raw packet referenced by
`hourly/latest-compact.json`, not against the compact file itself. Real proof:
`research execution-board-review --json-output` wrote
`results\execution_board\execution-board-review-20260606-234450.json`, reviewed
24 raw hourly packets, and ignored compact/latest sidecars; it submitted zero
orders and found zero hard violations. `research loss-review-evidence
--json-output` wrote
`results\loss_review_evidence\source-evidence-source-evidence-6cec5ab4ac894773a657c46fce716db8.json`
with refreshed source evidence, 3 blockers resolved, and
`can_submit_orders=false`. Refreshed compact context now reports
`board_matches_latest_hourly=true` and `evidence_matches_latest_hourly=true`;
the stale flags are gone, leaving only the intended BOARD-review flags. Process
review `results\process_reviews\process-review-20260606-235250.json` reports
`unchecked_step_count=0`, `can_submit_orders=false`, and no findings. Focused
proof:
`uv run --no-sync --with pytest python -m pytest tests/test_execution_board.py tests/test_automation_context_snapshot.py -q`
passed with 62 tests; targeted Ruff and `py_compile` passed.

2026-06-07 BOARD/loss-review durable compact sidecar checkpoint: the current
BOARD review and loss-review evidence drilldowns now have durable compact
sidecars, not just raw JSON packets. `write_execution_board_review(...)` writes
`execution-board-review-*.compact.json` and
`results\execution_board\latest-compact.json`, preserving the recommendation,
new-buy policy, next-hour buy/sell rules, metrics, issue counts, compact issue
summaries, recent packet reviews, and raw packet path. The generic
`write_research_packet(...)` now writes
`compact_loss_review_evidence_v1` sidecars only for
`SourceEvidencePacket.evidence_type == "loss_review_evidence"`, preserving the
loss-review blocker deltas, evidence coverage, source packet IDs, review
snapshot, `execution_authority=none`, `can_submit_orders=false`, and raw packet
path. Compact context now prefers both sidecars. Real proof:
`research execution-board-review --json-output` wrote
`results\execution_board\execution-board-review-20260607-000920.json` plus
compact sidecars; it reviewed 24 raw hourly packets, found zero hard violations,
submitted zero orders, and kept the expected negative-live-P/L warning.
`research loss-review-evidence --json-output` wrote
`results\loss_review_evidence\source-evidence-source-evidence-d0a196cbc6a741a39f674b72236b3892.json`
plus compact sidecars; it remained analysis-only, resolved 3 evidence blockers,
and preserved 10 true BOARD/session blockers. Refreshed compact context now reads
`results\execution_board\latest-compact.json` at `approx_tokens=832` and
`results\loss_review_evidence\latest-compact.json` at `approx_tokens=1044`, both
matching the latest hourly raw packet, with only the intended BOARD-review flags
remaining. Process review
`results\process_reviews\process-review-20260607-001833.json` reports
`unchecked_step_count=0`, `can_submit_orders=false`, and no findings. Focused
proof:
`uv run --no-sync --with pytest python -m pytest tests/test_execution_board.py tests/test_loss_review_evidence.py tests/test_research_schemas.py tests/test_automation_context_snapshot.py -q`
passed with 74 tests; targeted Ruff and `py_compile` passed.

2026-06-07 source-routing compact context checkpoint: the source routing map
still writes the full `results\_context\source-routing.json` evidence file, but
now also writes `results\_context\source-routing-compact.json` from
`compact_source_routing_v1`. Compact context reads the compact file by default,
preserving method/category counts, per-method effective fallback chains,
gap/coverage counts, the three optional coverage categories
`earnings_transcripts`, `options_iv_flow`, and `short_interest`,
`can_submit_orders=false`, and a raw packet pointer. Real proof:
`python scripts\automation_context_snapshot.py --write` regenerated both files;
the full source-routing map is 8,659 bytes and the compact map is 3,785 bytes.
Refreshed context reads `results\_context\source-routing-compact.json` with
`approx_tokens=947`, `gap_count=0`, `coverage_count=3`,
`empty_method_count=0`, and no drilldown flags. Process review
`results\process_reviews\process-review-20260607-002938.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_dataflows_interface.py tests/test_automation_context_snapshot.py -q`
passed with 66 tests; targeted Ruff and `py_compile` passed.

2026-06-07 overnight graph readiness repair: Claude's SAFE-01 review was
re-read and the fail-closed posture preserved; no live-control dead-man refresh
or order authority change was made. The overnight verifier had two actionable
readiness problems: weekend/no-market freshness could create a false stale
warning, and the latest production overnight packet recorded three original
TradingAgents graph failures from a LangGraph message-cleanup race. The
freshness check now accepts the same calendar skip reason used by simulated
pre-open validation, so stale weekend packets remain visible in evidence but do
not masquerade as broken overnight research when there is no useful regular
market morning. The graph cleanup path now deduplicates concrete message IDs,
skips empty IDs, and strips shared parent messages from concurrent analyst
fan-out branches to avoid duplicate `RemoveMessage` operations.

Real proof: two bounded no-latest overnight probes completed one full original
TradingAgents graph each with `graph_failure_count=0` and `submitted_count=0`.
Then the production-shaped overnight command completed with three original
TradingAgents graph successes and refreshed `results\overnight_plans\latest.json`
from raw packet
`results\overnight_plans\overnight-plan-20260607-010716-000000.json`; the
compact output reported `full_graph_success_count=3`, `graph_failure_count=0`,
`fallback_count=37`, `completion_status=complete`, top candidate `XOM`, and
`submitted_count=0`. `alpaca premarket-brief --json-output --compact-json-output`
then wrote `results\premarket_briefs\premarket-brief-20260607-010742-000000.json`
with latest overnight generated at `2026-06-07T01:07:16+00:00`, top symbol
`XOM`, no stale warnings, no blockers, and `execution_authority=none`.
Final verification:
`.\.venv\Scripts\tradingagents.exe alpaca verify-overnight-system --json-output`
wrote
`results\overnight_system_verification\overnight-system-verification-20260606-200816.json`
with `overall_status=pass`, original graph execution `pass`, complete packet
ready `true`, and zero submissions. Process review
`results\process_reviews\process-review-20260607-010847.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_graph_tool_routing.py tests/test_analyst_execution.py tests/test_alpaca_cli.py -k "graph_setup or message_cleanup or verify_overnight_system or simulated_preopen_validation or concurrency" -q`
passed with 10 tests; targeted Ruff and `py_compile` passed.

2026-06-07 loss-review advisory context repair: the TSM loss-review evidence
bridge now preserves a bounded `advisory_analysis` frame in both raw and compact
loss-review packets. The frame gives BOARD position context, current candidate
context, source references, route attempts, HOLD-vs-SELL framing, and broad
market noise framing while explicitly keeping `review_allowed=false`,
`execution_authority=none`, `can_submit_orders=false`, and
`mark_loss_exit_allowed` forbidden. Refreshed evidence now clears only the
context blockers it actually supports: SPY/QQQ/sector context, company-specific
news, earnings/guidance/filing coverage, HOLD-vs-SELL framing, broad-market
noise framing, and source packet IDs. It leaves true manual/session blockers in
place: allowed loss-exit reason/source, holding-period evidence, original buy
thesis, current thesis status, loss-exit confidence, and non-tradeable session.

Real proof: `research loss-review-evidence --json-output` wrote
`results\loss_review_evidence\source-evidence-source-evidence-4a9532a98f0c44a9bd37649042ee3b9d.json`
for `TSM`, with blocker deltas `13 -> 7`, `resolved_blocker_count=6`,
`review_allowed=false`, and zero order authority. Refreshed compact context was
written with `python scripts\automation_context_snapshot.py --write`. Process
review `results\process_reviews\process-review-20260607-012324.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
The n8n wrapper proof
`python -m tradingagents.orchestration.n8n_runner --run-job loss_review_evidence --json`
returned `status=ok`, `submit_capable=false`, `execution_authority=none`,
`review_allowed=false`, and the same blocker deltas `13 -> 7` with
`resolved_blocker_count=6`. `--list-jobs --json` still reports 21 allowlisted
jobs and `submit_capable_count=0`.
BOARD was then refreshed after the improved evidence packet:
`research execution-board-review --json-output` wrote
`results\execution_board\execution-board-review-20260607-012705.json` with zero
hard violations, zero submitted orders, `new_buy_state=caution`, independent
sell/buy policy preserved, and no green-spike chase allowance. Final compact
context refresh points `results\execution_board\latest-compact.json` to that
packet. Final process review
`results\process_reviews\process-review-20260607-012738.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_loss_review_evidence.py tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py -q`
passed with 98 tests; `tests/test_execution_board.py tests/test_loss_review_evidence.py`
passed with 12 tests; targeted Ruff and `py_compile` passed.

2026-06-07 overnight calibration policy contract: the overnight calibration
guard now exposes machine-readable tightening policy, not just prose guardrails.
When the mature walk-forward cohort is weak, the packet writes
`live_influence_policy.mode=tighten`,
`live_influence_action=tighten_or_hold_reduced_weight`,
`new_buy_permission=controlled_dip_support_reclaim_only`,
`replacement_buy_permission=disabled_unless_fresh_independent_setup`, and
`sell_permission=independent_profit_or_board_approved_exit_only`. It also writes
explicit required entry validation ids:
`controlled_dip_or_support_reclaim`, `no_green_spike_chase`,
`buy_sell_independence`, `source_freshness_and_quality`, and
`anti_crowding_confirmation`. Promotion blockers now include
`weak_or_negative_walk_forward_cohort`, `false_positive_rate_too_high`,
`action_relative_return_negative`, and `directional_accuracy_below_floor`.
Paper exploration remains `continue` and still does not bypass live gates.

Real proof: `research overnight-calibration-guard --json-output` wrote
`results\overnight_calibration\overnight-calibration-guard-20260607-013640.json`
with `guard_decision=tighten`, `can_increase_live_influence=false`,
`can_submit_orders=false`, and `execution_authority=none`. Refreshed compact
context shows the same policy fields without adding a drilldown flag; the only
current flags remain the intended hourly/BOARD/loss-review review trio. The n8n
wrapper proof
`python -m tradingagents.orchestration.n8n_runner --run-job overnight_calibration_guard --json`
returned `status=ok`, `submit_capable=false`, the same required entry validation
ids, `new_buy_permission=controlled_dip_support_reclaim_only`, and the same
promotion blockers. Process review
`results\process_reviews\process-review-20260607-013709.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_overnight_calibration_guard.py tests/test_automation_context_snapshot.py::test_snapshot_summarizes_overnight_calibration_guard_without_raw_drilldown tests/test_automation_context_snapshot.py::test_snapshot_flags_unsafe_overnight_calibration_guard tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_overnight_calibration_policy_json -q`
passed with 6 tests; targeted Ruff and `py_compile` passed.

2026-06-07 n8n runner overlap-control checkpoint: the allowlisted n8n wrapper
now has a repo-local process lock at `results\_context\n8n-runner.lock`, so
dashboard clicks, built-in n8n evaluations, or nearby schedules cannot run two
TradingAgents wrapper jobs at once and race shared compact context/latest
pointers. A live lock returns compact `status=busy` with the lock owner and
does not spawn a subprocess; stale locks recover automatically. This is an
observer/control-plane guard only: it does not submit orders, refresh the
dead-man, change automation status, or alter broker execution. Real proof:
`python -m tradingagents.orchestration.n8n_runner --run-job context_snapshot
--json` returned `status=ok`, `submit_capable=false`, wrote compact context, and
reported `lock_stale_recovered=false`; `python -m
tradingagents.orchestration.n8n_runner --list-jobs --json` still reports 21
allowlisted jobs and `submit_capable_count=0`. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_n8n_runner_policy.py
-q` passed with 41 tests; targeted Ruff and `py_compile` passed.

2026-06-07 loss-review entry-history bridge checkpoint: the active TSM
loss-review evidence bridge now finds the original local live-buy context from
hourly supervisor history and carries it into raw packets, compact sidecars, CLI
JSON, and n8n parsed summaries. The current packet
`results\loss_review_evidence\source-evidence-source-evidence-2594f15673fe4fe5825f31325f00df88.json`
has `entry_context_found=true` from
`results\hourly_supervisor\hourly-supervisor-20260601-170250-428127.json`,
client order id `ta-hourly-20260601-170250-1-tsm-buy`, the original entry
reason, and 4 trading days of holding-period evidence. This resolves only the
supported historical-context blockers, moving the real blocker delta from
`13 -> 7` to `13 -> 5` with `resolved_blocker_count=8`; it still leaves
allowed loss-exit reason/source, current thesis status, loss-exit confidence,
and closed-market session as true BOARD/manual/session blockers. The packet
remains advisory-only: `review_allowed=false`, `can_submit_orders=false`,
`execution_authority=none`, and `mark_loss_exit_allowed` remains forbidden.
Real n8n proof:
`python -m tradingagents.orchestration.n8n_runner --run-job loss_review_evidence --json`
returned `status=ok`, `submit_capable=false`, `entry_context_found=true`,
`resolved_blocker_count=8`, and `remaining_blocker_count=5`. BOARD was refreshed
after the improved evidence packet at
`results\execution_board\execution-board-review-20260607-015047.json`: zero hard
violations, zero submitted orders, `new_buy_policy.state=caution`, independent
sell/buy policy preserved, and no green-spike chase allowance. Compact context
was refreshed; current flags remain the intended hourly/BOARD/loss-review
review routes only. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_loss_review_evidence.py tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_loss_review_evidence_json tests/test_automation_context_snapshot.py -q`
passed with 62 tests; targeted Ruff over the touched loss-review/n8n files
passed.

2026-06-07 rating-calibration bridge checkpoint: the existing shrinkage
calibration engine is now connected to future Agent Intelligence forecast
generation instead of remaining a report-only artifact. `research
decision-quality-report` writes a small standalone advisory calibration file at
`results\agent_intelligence\rating_calibration.json`; the ledger forecast
builders read it and override the static five-tier rating priors only per
rating when the row is advisory-only, has at least three resolved samples, and
does not worsen Brier score. Sparse, unsafe, unreadable, or Brier-worse
calibration rows are ignored and the prior probabilities remain active. Real
proof: `.\.venv\Scripts\tradingagents.exe research decision-quality-report
--json-output` wrote
`results\research_batches\research-batch-research-batch-95c1d9f0411f46669e5810566b415ebf.json`
and `results\agent_intelligence\rating_calibration.json`; current
`resolved_rating_forecast_count=0`, so
`load_calibrated_rating_probabilities()` correctly returns `{}` and no live
forecast behavior changes yet. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_agent_intelligence_ledger.py tests/test_replay_ablation_plan.py -q`
passed with 25 tests; targeted Ruff and `py_compile` passed. Process review
`results\process_reviews\process-review-20260607-015815.json` reports
`unchecked_step_count=0`.

2026-06-07 Claude submit-path handoff prep checkpoint: the Claude deep-review
handoff at `reports\handoff\CODEX_SUBMIT_PATH_HARDENING_HANDOFF_2026-06-05.md`
has been re-read and prepared as a current operating constraint. SAFE-01 remains
fail-closed: `config\risk_envelope.yaml` parses as
`live_budget_mode=autonomous_with_caps`, account max `$250`, per-name `$50`,
optional hard-ceiling/rate-limit knobs unset, and `issues=[]`; live control
still has the lapsed dead-man, so live submission remains blocked unless the
operator intentionally refreshes it. The standalone unsigned commit `3970998`
still contains only `tradingagents\policy\order_rate_limit.py` and
`tests\test_order_rate_limit.py`; broader submit-path hardening work must use
selective staging and must never use `git add -A`. Local/sensitive paths
`config\risk_envelope.yaml`, `.claude/`, `setup_n8n.py`, and `analysis_mypy.txt`
remain gitignored, while `.codex\hooks` remains visible for hook review. Fresh
proof: `git show --stat --oneline 3970998` confirmed the two-file commit;
`git check-ignore -v ...` confirmed the local ignore set; direct envelope load
returned `autonomous_with_caps`, `$250`, `$50`, and `[]`; process review
`results\process_reviews\process-review-20260607-020133.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 router/roadmap freshness checkpoint: `CONTEXT_ROUTER.md` now exposes
a current `Current nearest checks` row above the older historical proof row so
new agents start from the repaired June 7 XOM overnight packet, the latest
source-quality/n8n/BOARD/loss-review/process-review proof, and the live
`13 -> 5` TSM loss-review blocker delta instead of stale June 5 KO evidence.
The dispatch footer now states that P4's MiroFish handoff availability gate has
landed and should be treated as advisory validation/outcome-labeling work, not
a waiting gate. `docs\PIPELINE_ARCHITECTURE_AUDIT.md` mirrors that P4 status so
the two durable planning surfaces no longer disagree. Verification:
`git diff --check -- CONTEXT_ROUTER.md docs/IMPROVEMENT_PROGRAM.md docs/PIPELINE_ARCHITECTURE_AUDIT.md`
returned no whitespace errors beyond the expected CRLF warning, and
`research process-review --json-output` wrote
`results\process_reviews\process-review-20260607-020521.json` with
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 Agent Intelligence learning-loop automation checkpoint: the ledger
feedback loop now has one automation-safe update command instead of requiring a
human or n8n workflow to remember separate append, MiroFish append, resolve, and
summary steps. `research agent-ledger-update --json-output` reads the latest
overnight packet plus the latest MiroFish advisory packet, appends idempotent
scoreable forecasts, resolves any due forecasts against the existing price
lookup path, and writes `results\agent_intelligence\summary.json`. The command
is advisory-only and writes no broker/order/control state:
`analysis_only=true`, `can_submit_orders=false`, and `execution_authority=none`.
n8n now exposes this as `agent_ledger_update`; the allowlist still has
`submit_capable_count=0`, and the parsed wrapper summary exposes only bounded
forecast/append/resolve counters plus ledger/summary paths. Real proof:
`.\.venv\Scripts\tradingagents.exe research agent-ledger-update --json-output`
completed with `discovered_forecast_count=130`,
`overnight_forecast_count=122`, `mirofish_forecast_count=8`,
`forecast_count=3548`, `resolved_forecast_count=0`, and `appended_count=0` on
the already-populated local ledger. The n8n wrapper
`python -m tradingagents.orchestration.n8n_runner --run-job agent_ledger_update --json`
returned the same counters with `submit_capable=false`. The built-in n8n
evaluation dataset was regenerated at
`results\n8n_evaluations\n8n-evaluation-dataset-20260607-021220-925007.json`
with 22 allowlisted jobs, 201 rows, and 9 cases for `agent_ledger_update`.
Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_agent_intelligence_ledger.py tests/test_n8n_runner_policy.py -q`
passed with 53 tests; targeted Ruff and `py_compile` passed.

2026-06-07 n8n workflow learning-loop sequencing checkpoint: the source-controlled
n8n observer workflows now actually call the new `agent_ledger_update` job at
the right moments instead of only showing `agent_ledger_summary`. The overnight
observer chain is now `context_snapshot -> creator_workflow_status ->
source_quality_review -> agent_ledger_update -> agent_ledger_summary`, so fresh
overnight/MiroFish forecasts are captured before the dashboard displays ledger
influence. The after-close observer chain is now `context_snapshot ->
agent_ledger_update -> agent_ledger_summary -> outcome_labeling`, so due
forecast resolution happens before model/market-mirror outcome labels are
applied. Regenerated workflow proof shows
`n8n\workflows\ta-overnight-planner-observer.json` and
`n8n\workflows\ta-after-close-supervisor-observer.json` with that sequence and
no `--submit-actions`. The n8n README and workflow map now document the same
contract. The evaluation dataset was refreshed at
`results\n8n_evaluations\n8n-evaluation-dataset-20260607-022039-066294.json`
with 22 jobs, 201 rows, and 9 `agent_ledger_update` cases. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_n8n_evaluations.py tests/test_n8n_runner_policy.py -q`
passed with 53 tests; targeted Ruff and `py_compile` passed.

2026-06-07 n8n Data Table drift repair checkpoint: the n8n evaluation dataset
had advanced to 201 rows after `agent_ledger_update` landed, while the local n8n
Data Table proof was still synced at 192 rows. A direct sync without
`N8N_API_KEY` failed closed with redacted `blocked_missing_api_key` packets, then
Codex copied the running container's `/home/node/.n8n/database.sqlite` to a
temporary `%TEMP%` directory, passed that copy with `--api-key-sqlite-db`, and
deleted the temp copy after both syncs completed. Real proof:
`research n8n-sync-evaluation-table --api-key-sqlite-db <temp-copy> --json-output`
wrote `results\n8n_evaluations\n8n-api-sync-20260607-022929-127780.json` with
`status=ok`, `expected_row_count=201`, `final_row_count=201`,
`row_count_matches=true`, `api_key_redacted=true`, and
`can_submit_orders=false`. `research n8n-sync-workflows --api-key-sqlite-db
<temp-copy> --json-output` wrote
`results\n8n_evaluations\n8n-workflow-sync-20260607-022936-100872.json` with
`status=ok`, 12/12 source-controlled observer workflows present, `created_count=0`,
`would_create_count=0`, and `api_key_redacted=true`. Refreshed compact context
removed the `n8n_evaluation_dataset` audit flag; current flags are only the
intended hourly/BOARD/loss-review review routes. Process review
`results\process_reviews\process-review-20260607-023015.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 hourly/loss-review context-merge checkpoint: compact context now
bridges the refreshed loss-review evidence back into the hourly supervisor
summary when, and only when, the evidence packet references the same raw hourly
packet. This prevents morning agents from reading the stale original hourly
reason as if all 13 loss-review blockers were still unresolved after the
evidence bridge has already resolved several categories. Real proof after
regenerating `results\_context\latest-summary.json`: the `hourly` summary for
TSM has `loss_review_evidence_matches_latest=true`,
`loss_review_entry_context_found=true`,
`loss_review_remaining_blockers_before_refresh_count=13`,
`loss_review_resolved_blocker_count=8`, and
`loss_review_remaining_blocker_count=5`. It still keeps
`drilldown_reasons=["board_review"]`, so no sell authorization or live authority
is introduced. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py::test_snapshot_merges_matching_loss_review_evidence_into_hourly_summary tests/test_automation_context_snapshot.py::test_snapshot_summarizes_loss_review_evidence_packet tests/test_automation_context_snapshot.py::test_snapshot_prefers_compact_loss_review_evidence_sidecar tests/test_automation_context_snapshot.py::test_snapshot_accepts_loss_review_evidence_for_compact_latest_hourly_raw_path tests/test_automation_context_snapshot.py::test_snapshot_prefers_compact_hourly_sidecar_but_keeps_board_flag -q`
 passed with 5 tests; targeted Ruff and `py_compile` passed.

2026-06-07 self-heal overlap de-noise checkpoint: the automation-health compact
summary no longer reports `tradingagents-self-heal-monitor` as a problem when
the row is otherwise `ok`, the only issue type is `overlap_run`, and the latest
actionable self-heal handoff received a timely follow-up plan. This keeps real
self-heal SLA misses loud while preventing harmless observer overlap from
looking like a broken repair loop. Real proof:
`results\automation_health\automation-health-audit-20260607-024653.json`
shows self-heal `status=ok`, `issue_types=["overlap_run"]`,
`followup_lag_seconds=34`, `timely=true`, and `problem_jobs=[]`; its compact
sidecar now has `problem_automation_ids=[]`, while still retaining self-heal
under `attention_automation_ids`. Refreshed context opens only the intended
hourly/BOARD/loss-review flags. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_automation_health_audit.py tests/test_automation_context_snapshot.py -q`
passed with 88 tests; targeted Ruff passed; process review
`results\process_reviews\process-review-20260607-024743.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 agent-ledger summary integrity checkpoint: compact context now checks
`results\agent_intelligence\summary.json` against the sibling
`results\agent_intelligence\ledger.jsonl` record count when both are present.
This catches stale or test-sized summary overwrites before morning agents trust
the Agent Intelligence Ledger. The live summary was regenerated with
`research agent-ledger-summary --json-output`, restoring 3,586 forecasts across
10 agents from the real ledger. Refreshed compact context now exposes
`forecast_count=3586`, `ledger_record_count=3586`, and
`summary_ledger_count_matches=true` without adding a drilldown flag. A new
regression test writes a deliberately mismatched summary/ledger pair and proves
the snapshot raises a `schema` drilldown. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py -q`
passed with 59 tests; targeted Ruff passed; process review
`results\process_reviews\process-review-20260607-025901.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 premarket compact validation-checklist checkpoint: the raw
premarket brief already told agents to validate fresh quotes/spreads,
morning news/social deltas, open orders, positions/P&L, and live sizing room
before any market action, but `latest-compact.json` dropped that checklist.
Morning agents could therefore read the compact packet and see `top_symbol=XOM`
without the explicit fresh-validation contract. The compact premarket payload
now preserves `premarket_instructions.summary` and bounded
`must_validate_fresh` entries, and `scripts\automation_context_snapshot.py`
surfaces the same list in `results\_context\latest-summary.json` without
opening the raw packet or adding a drilldown flag. This is context preservation
only: `analysis_only=true`, `execution_authority=none`, and no submit path is
changed.

Real proof: `alpaca premarket-brief --json-output --compact-json-output`
wrote `results\premarket_briefs\premarket-brief-20260607-030938-000000.json`
and `latest-compact.json` with `must_validate_fresh` carrying the five required
fresh checks. Refreshed compact context now shows `premarket_brief` with
`top_symbol=XOM`, zero blockers, zero stale warnings, and the same validation
checklist. Process review
`results\process_reviews\process-review-20260607-031011.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py::test_premarket_brief_aggregates_timestamped_packets_and_writes_latest tests/test_alpaca_supervisor.py::test_premarket_brief_writer_can_skip_latest_compact_for_probe tests/test_alpaca_cli.py::test_compact_premarket_brief_payload_points_to_raw_packet tests/test_automation_context_snapshot.py::test_snapshot_prefers_compact_premarket_brief_sidecar_when_present -q`
passed with 4 tests; a wider premarket/overnight/context slice passed with 14
tests; targeted Ruff passed.

2026-06-07 overnight calibration compact guard checkpoint: the overnight
calibration guard is now a first-class compact-context packet instead of forcing
future supervisors/n8n jobs to read `results\overnight_calibration\latest.json`.
`write_overnight_calibration_guard(...)` writes timestamped `.compact.json` and
`latest-compact.json` sidecars with the guard decision, red flags, promotion
blockers, anti-crowding/controlled-dip validation requirements, key cohort
metrics, raw packet pointer, and the advisory-only authority fields. The context
snapshot compact-label allowlist now includes `overnight_calibration_guard`, and
the summarizer handles both legacy raw packets and the new compact packet shape.

Real proof: `research overnight-calibration-guard --json-output` wrote
`results\overnight_calibration\overnight-calibration-guard-20260607-030916.json`
and `results\overnight_calibration\latest-compact.json`. Refreshed compact
context now reads `results\overnight_calibration\latest-compact.json` at about
766 tokens, with `guard_decision=tighten`,
`can_increase_live_influence=false`, `can_submit_orders=false`,
`execution_authority=none`, and required validations for controlled
dip/support reclaim, no green-spike chase, buy/sell independence, source
freshness, and anti-crowding confirmation. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_overnight_calibration_guard.py -q`
passed with 62 tests; targeted Ruff passed; process review
`results\process_reviews\process-review-20260607-030943.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 premarket checklist verifier checkpoint: after the compact
premarket sidecar started preserving `must_validate_fresh`, the overnight
system verifier was hardened so a future raw/compact regression cannot pass
silently. `alpaca verify-overnight-system` now emits
`premarket_fresh_validation_checklist` and requires both the raw premarket
packet and `results\premarket_briefs\latest-compact.json` to carry the five
fresh checks: quotes/spreads, morning news/social deltas, open orders,
positions/P&L, and live sizing room/buying power. The compact packet must also
be `compact_premarket_brief_v1` and point back to either `latest.json` or the
timestamped raw premarket brief in the same directory. This is still
analysis-only verification; it adds no submit authority and does not refresh
the dead-man.

Real proof: `.\.venv\Scripts\tradingagents.exe alpaca verify-overnight-system
--json-output` wrote
`results\overnight_system_verification\overnight-system-verification-20260606-222604.json`
with `overall_status=pass`, `premarket_fresh_validation_checklist=pass`,
`raw_item_count=5`, `compact_item_count=5`, no missing items, and zero order
submissions. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py::test_verify_overnight_system_audits_full_chain -q`
passed; the broader verifier/premarket CLI slice passed with 9 tests; targeted
Ruff passed.

2026-06-07 loss-review compact payload trimming checkpoint: the active
BOARD/loss-review compact packet no longer copies the full raw
`advisory_analysis` block into compact context. `compact_loss_review_evidence_payload(...)`
now keeps blocker counts/lists, resolved blocker list, evidence coverage, source
packet IDs, route/source counts, a bounded entry-context summary, current review
snapshot, and an `advisory_summary`; full source refs, provider route details,
and submit IDs remain behind `raw_packet_path`. Real proof:
`research loss-review-evidence --json-output` refreshed
`results\loss_review_evidence\source-evidence-source-evidence-bae59d8683014d51812d06f14c595cc0.json`
and `results\loss_review_evidence\latest-compact.json`. The compact sidecar is
now `6,393` bytes / about `1,599` tokens, down from `12,144` bytes / about
`3,036` tokens, while refreshed compact context still shows TSM
`remaining_blockers_before_refresh_count=13`, `resolved_blocker_count=8`,
`remaining_blocker_count=5`, `review_allowed=false`, `can_submit_orders=false`,
and `execution_authority=none`. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_loss_review_evidence.py tests/test_automation_context_snapshot.py -q`
passed with 63 tests; targeted Ruff passed; process review
`results\process_reviews\process-review-20260607-032651.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 overnight verification compact sidecar checkpoint: the
overnight-system verifier now writes a compact sidecar so morning agents, n8n,
and compact context can verify the overnight pipeline without reading the full
raw verifier evidence by default. `alpaca verify-overnight-system` writes both
timestamped `.compact.json` and `latest-compact.json` with the pass/warn/fail
counts, raw packet pointer, top overnight symbol, freshness state, original
TradingAgents graph success count, premarket fresh-validation checklist status,
hourly/paper tournament zero-submit checks, and explicit
`can_submit_orders=false` / `execution_authority=none`. The context snapshot
now prefers that sidecar for `overnight_verification`, and warning checks force
a drilldown just like failures.

This slice also fixed a compact-context regression from the loss-review payload
trim: hourly summaries now read `advisory_summary` as a fallback to the old raw
`advisory_analysis`, restoring
`loss_review_current_thesis_status_candidate` in
`results\_context\latest-summary.json` without reopening the full raw evidence
packet.

Real proof: `.\.venv\Scripts\tradingagents.exe alpaca verify-overnight-system
--json-output` wrote
`results\overnight_system_verification\overnight-system-verification-20260606-224410.json`
and `results\overnight_system_verification\latest-compact.json`.
The compact sidecar is `3,680` bytes versus `10,346` bytes for raw
`latest.json`, reports `overall_status=pass`, `check_count=15`,
`failed_checks=[]`, `warned_checks=[]`, `top_symbol=XOM`,
`full_graph_success_count=3`, `premarket_compact_item_count=5`,
`can_submit_orders=false`, and `execution_authority=none`. Refreshed compact
context reads `overnight_verification` from `latest-compact.json` at about
`920` tokens with no drilldown flag. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_alpaca_cli.py::test_verify_overnight_system_audits_full_chain -q`
passed with 62 tests; targeted Ruff passed; process review
`results\process_reviews\process-review-20260607-034618.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 compact-output daily-report discovery checkpoint: the daily-report
compact writer was already present, but the byte-reduction audit looked only in
the root `results\daily_reports` directory. Current real daily-report packets
are under namespaced subdirectories such as `results\daily_reports\n8n`, so the
audit marked `supervisor_daily_report` as missing even though a valid raw packet
existed. `_latest_packet_path(...)` now supports opt-in recursive discovery,
and `alpaca compact-output-audit` uses that only for the daily-report family.
This preserves probe isolation for other packet families while letting the
audit measure the actual n8n daily-report layout.

Real proof: `.\.venv\Scripts\tradingagents.exe alpaca compact-output-audit
--json-output` wrote
`results\token_efficiency\compact-output-audit-20260606-225850-079574.json`
with `row_count=5`, `measured_count=5`, and all rows
`lossless_by_reference=true`. The daily-report row now measures
`results\daily_reports\n8n\supervisor-daily-report-20260604-000811-878577.json`,
reducing `133,407` raw bytes to `2,141` compact bytes (`98.4%` reduction).
Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py::test_compact_output_audit_measures_packet_families tests/test_alpaca_cli.py::test_compact_output_audit_finds_nested_daily_report_packets -q`
passed with 2 tests; targeted Ruff passed; process review
`results\process_reviews\process-review-20260607-035916.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 pre-open validation packet checkpoint: the premarket brief's
`must_validate_fresh` checklist now has a concrete analysis-only command that
reads current broker/context state and writes a compact packet before any
submit-capable supervisor path can treat the brief as fresh. `alpaca
preopen-validation` checks premarket quotes/spreads, overnight and morning
news/social deltas, open live and paper orders, current live and paper
positions/P&L, and live sizing room/buying power. It writes
`results\preopen_validation\latest.json` and `latest-compact.json` with
`analysis_only=true`, `can_submit_orders=false`, `execution_authority=none`,
and `submitted_count=0`.

The command intentionally does not refresh live control, submit orders, send
email, or rely on market-closed status as a safety control. Closed sessions are
reported as a skipped quote/spread check; expired live control is reported as a
warning while the packet still preserves broker buying power and current
positions for the morning agent.

Real proof: `.\.venv\Scripts\tradingagents.exe alpaca preopen-validation
--json-output` wrote
`results\preopen_validation\preopen-validation-20260607-035809.json` with
`overall_status=pass_with_warnings`, `failed_check_ids=[]`,
`warned_check_ids=["live_sizing_room_and_buying_power"]`,
`skipped_check_ids=["premarket_quotes_and_spreads"]`,
`market_session=closed`, `top_symbol=XOM`, live buying power `$86.38`,
4 live positions, 14 paper positions, and 0 open live/paper orders. The warning
is the expected fail-closed dead-man state:
`dead-man expired at 2026-06-04T19:57:06+00:00`.

n8n has a read-only wrapper job,
`preopen_validation_preview`, which runs the same command with
`--json-output`, `--compact-json-output`, `--no-write-latest`, and a namespaced
`results\preopen_validation\n8n` log directory. Real proof:
`.\.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner
--run-job preopen_validation_preview --json` returned `status=ok`,
`submit_capable=false`, `compact_output_only=true`, and parsed the compact
summary from
`results\preopen_validation\n8n\preopen-validation-20260607-035839.json`.

Refreshed compact context now includes `preopen_validation` from
`results\preopen_validation\latest-compact.json`, suppresses the expected
closed-session/dead-man warning from the drilldown list, and keeps the raw
packet behind the pointer.
Process review
`results\process_reviews\process-review-20260607-035910.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 pre-open closed-market de-noise checkpoint: compact context no
longer treats an off-hours `preopen_validation` packet as stale when the only
skip is `premarket_quotes_and_spreads` for `market_session=closed` and the only
warning is `live_sizing_room_and_buying_power` from intentional fail-closed live
control. The raw packet still preserves both check IDs and summaries; the
compact summary now adds `deferred_for_closed_market=true` and
`fail_closed_live_control_warning_only=true`, while leaving
`drilldown_required=false`.

Real proof: after `python scripts\automation_context_snapshot.py --write`,
`results\_context\latest-summary.json` shows `preopen_validation` with
`overall_status=pass_with_warnings`, `market_session=closed`,
`warned_check_ids=["live_sizing_room_and_buying_power"]`,
`skipped_check_ids=["premarket_quotes_and_spreads"]`,
`deferred_for_closed_market=true`, and no drilldown reasons. The refreshed
`results\_context\latest-flags.json` now contains only the intended
hourly/BOARD/loss-review review flags. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py::test_snapshot_summarizes_compact_preopen_validation tests/test_automation_context_snapshot.py::test_snapshot_flags_preopen_validation_warnings tests/test_automation_context_snapshot.py::test_snapshot_defers_closed_market_preopen_validation_warning -q`
passed with 3 tests; targeted Ruff passed; process review
`results\process_reviews\process-review-20260607-040621.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 n8n evaluation Data Table refresh checkpoint: adding the
`preopen_validation_preview` job increased the allowlisted n8n evaluation
dataset from 201 rows / 22 jobs to 210 rows / 23 jobs. Compact context correctly
raised an `n8n_evaluation_dataset` audit drilldown because the last Data Table
sync proof still had `expected_row_count=201` and
`sync_current_row_count_matches=false`. A direct sync without `N8N_API_KEY`
failed closed with a redacted `blocked_missing_api_key` packet, so Codex used
the established safe fallback: copy the running n8n container's
`/home/node/.n8n/database.sqlite` to `%TEMP%`, pass that copy with
`--api-key-sqlite-db`, and delete the copy immediately after sync.

Real proof: `research n8n-sync-evaluation-table --api-key-sqlite-db <temp-copy>
--json-output` wrote
`results\n8n_evaluations\n8n-api-sync-20260607-041459-118935.json` with
`status=ok`, `expected_row_count=210`, `inserted_count=210`,
`final_row_count=210`, `row_count_matches=true`, `api_key_redacted=true`,
`can_submit_orders=false`, and `execution_authority=none`. The temp DB copy was
deleted (`Test-Path` returned `False`). Refreshed compact context now shows
`n8n_evaluation_dataset` with `row_count=210`,
`sync_expected_row_count=210`, `sync_final_row_count=210`,
`sync_current_row_count_matches=true`, `sync_api_key_redacted=true`, and no
n8n drilldown flag. Process review
`results\process_reviews\process-review-20260607-041528.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 automation prompt live-posture alignment checkpoint: the app-level
TradingAgents market/report automations no longer carry stale no-cap live
budget assumptions in their prompts. Updated through the Codex automation tool,
not raw TOML edits, while preserving each automation's existing status,
schedule, model, reasoning effort, execution environment, and cwd. The updated
jobs are `hourly-market-supervisor`,
`market-supervisor-15-min-before-open`,
`market-supervisor-30-min-after-open`,
`market-supervisor-30-min-before-close`,
`market-supervisor-15-min-after-close`, and
`tradingagents-daily-market-report`.

The pre-open supervisor prompt now requires:
`alpaca check`, refreshed `alpaca premarket-brief --json-output`,
`alpaca preopen-validation --json-output`, inspection of
`results/preopen_validation/latest-compact.json`, then the normal hourly
dry-run and guarded submit flow. Every market/report prompt now says to read the
current live posture from `config/risk_envelope.yaml`,
`results/policy/live_control.json`, broker buying power, and the unified live
gate; it must not assume a no-cap mode or stale fixed cap from memory.

Real proof: searching all `C:\cm\automations\*\automation.toml` files after the
updates found the new `preopen-validation` requirement and no remaining stale
no-cap keyword. `.\.venv\Scripts\tradingagents.exe research
automation-health-audit --json-output` wrote
`results\automation_health\automation-health-audit-20260607-042251.json` with
`automation_count=13`, `ok_count=13`, `issue_count=0`,
`submitted_order_count=0`, and self-heal follow-up still timely within the
30-minute SLA.

2026-06-07 Agent Intelligence Ledger freshness checkpoint: compact context
correctly raised an `agent_intelligence_summary` schema drilldown because
`results\agent_intelligence\summary.json` had drifted to a stale one-forecast
summary while the sibling `ledger.jsonl` contained 3606 records. Codex ran the
automation-safe one-shot ledger path instead of hand-editing packets:
`research agent-ledger-update --json-output`. The command kept
`analysis_only=true`, `can_submit_orders=false`, `execution_authority=none`,
discovered 122 overnight forecasts plus 8 MiroFish advisory forecasts,
appended 0 duplicates, and rewrote the summary from the full 3606-record ledger.
All forecasts remain pending, so influence weights correctly stay at
`insufficient_history` and cannot bypass risk gates.

Refreshed compact context now has no agent-ledger schema drilldown; the only
remaining flags are the intentional hourly/BOARD/loss-review review routes.
Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_agent_intelligence_ledger.py tests/test_automation_context_snapshot.py::test_snapshot_flags_agent_summary_when_ledger_count_disagrees tests/test_automation_context_snapshot.py::test_snapshot_exposes_agent_outcome_labels_without_drilldown_flag tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_agent_ledger_summary_json tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_agent_ledger_update_json -q`
passed with 15 tests; targeted Ruff passed. This supports the P2 goal that
agents earn influence from resolved outcomes, while leaving live authority
unchanged.

2026-06-07 original TradingAgents workflow compact repair: the latest raw
overnight packet already preserved creator workflow artifacts for `XOM`,
`ADBE`, and `CVX`, but `latest-compact.json` dropped those refs. Compact context
therefore underreported `creator_workflow_count=0` even though
`research creator-workflow-status --json-output` proved 3 workflows with 9 roles
each and `execution_authority=none`. Codex patched
`compact_overnight_plan_payload(...)` to carry a bounded
`creator_workflow_summary` instead of raw `ticker_results`, and taught compact
context to read that summary. The current compact overnight packet was
regenerated from the existing raw packet, not by creating a new overnight run.

Real proof: refreshed compact context now shows
`creator_workflow_count=3`, symbols `XOM`, `ADBE`, `CVX`,
`creator_workflow_role_count_min=9`, and no overnight drilldown. The n8n
allowlisted `creator_workflow_status` wrapper returns `status=ok`,
`submit_capable=false`, `workflow_count=3`, `missing_role_count=0`, and
`bad_authority_count=0`. Focused proof:
`uv run --no-sync --with pytest python -m pytest tests/test_original_tradingagents_workflow.py tests/test_alpaca_supervisor.py::test_overnight_packet_writer_marks_analysis_only_and_loads_latest tests/test_automation_context_snapshot.py::test_snapshot_prefers_compact_overnight_sidecar_when_present tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_creator_workflow_status_json -q`
passed with 6 tests; targeted Ruff passed. This closes the P3/P4 evidence gap
where the original creator workflow ran but was invisible to token-efficient
overnight context.

2026-06-07 overnight source-quality routing checkpoint: source-quality review
was fresh in compact context but not carried into the overnight provider path.
Codex patched `tradingagents/research/overnight_context.py`,
`cli/main.py`, `tradingagents/orchestration/n8n_runner.py`,
`config/n8n_tradingagents_allowlist.json`, and focused tests so overnight
research context now loads `results/source_quality/latest.json`, passes
source-quality strengths into provider fallback ordering, and writes a compact
`research_context.watchlists.source_quality` advisory plus prior-feed entry.
The n8n overnight preview now refreshes source-quality first; the runner ignores
non-overnight JSON for the overnight parsed summary so dashboards do not show a
false parsed overnight packet from the source-quality step.

The active `tradingagents-overnight-planning` automation prompt was updated
through the Codex automation tool, preserving status, 2:30 AM daily schedule,
model, reasoning effort, execution environment, and cwd. The prompt now
requires `research source-quality-review --json-output --compact-json-output`
before ranking and passes `--source-quality-review-path
results/source_quality/latest.json --source-quality-ordering` into both
`alpaca plan-overnight` and post-ranking `research ticker-provider-bundle`.

Real proof: focused tests passed with 15 tests covering source-quality packets,
provider ordering, overnight CLI context, and n8n preview behavior. Targeted
Ruff passed. A real no-latest/no-ledger/zero-full-graph overnight probe wrote
`results\overnight_plans\source_quality_probe\overnight-plan-20260607-044822-000000.json`
with `submitted_count=0`, 40 ranked candidates, 14 research context packets,
0 blocked packets, source-quality ordering enabled, 16 scored sources,
`source_count=250`, `stale_count=43`, `stale_downrank_count=23`, and
`stale_needs_refresh_count=0`. The allowlisted n8n job
`overnight_plan_compact_preview` ran two non-submit steps successfully:
source-quality review first, overnight preview second. Automation health wrote
`results\automation_health\automation-health-audit-20260607-045136.json` with
13/13 automations OK, no issues, and no submitted orders. Process review wrote
`results\process_reviews\process-review-20260607-045136.json` with
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
After fixing one stale n8n evaluation-test expectation for the new two-command
overnight preview, the full repo gate passed:
`uv run --no-sync --with pytest python -m pytest -q` -> `980 passed`,
`1 skipped` (live DeepSeek API key not set), `9 warnings`, and `75 subtests
passed`.

2026-06-07 P2 walk-forward calibration checkpoint: the overnight cohort refresh
worked, but it exposed a packet-discovery hygiene bug where
`walk-forward-refresh-overnight-cohort` considered `*.compact.json` sidecars as
overnight packets and listed them as skipped not-mature rows. Codex patched
`_discover_mature_overnight_packets(...)` to reuse the repo's raw JSON packet
predicate and added a replay regression that writes a newer compact sidecar next
to a raw overnight packet. Focused replay tests passed with 15 tests and targeted
Ruff passed.

Real proof after the patch:
`research walk-forward-refresh-overnight-cohort --json-output` wrote
`results\research_batches\walk_forward_cohort_refresh_20260607-045358_h3.json`
with 12 selected raw packets, 4 skipped raw packets, 0 compact sidecars in the
skipped set, 175 return rows, 420 replay fixture rows, and
`sample_floor_met=true`. The cohort still argues against expanding live
influence: deterministic sleeve action-relative return was `-1.2219` and
TradingAgents overlay action-relative return was `-0.1140` with a `0.5000`
false-positive rate. `research overnight-calibration-guard
--cohort-summary-path
results\research_batches\walk_forward_cohort_refresh_20260607-045358_h3.json
--json-output` therefore wrote
`results\overnight_calibration\overnight-calibration-guard-20260607-045504.json`
with `guard_decision=tighten`, `can_increase_live_influence=false`,
controlled-dip/support-only buy permission, buy/sell independence, no
green-spike chasing, and required anti-crowding confirmation. Agent ledger was
refreshed afterward to 3,629 pending forecasts, and compact context now has only
the expected hourly/BOARD/loss-review flags, no agent-ledger schema flag.

2026-06-07 Claude deep-review current-state prep refresh: the Claude submit-path
handoff response was re-read and verified against current disk state on
`wip/submit-path-hardening-2026-06-05`. Commit `3970998` still contains only
`tradingagents/policy/order_rate_limit.py` and
`tests/test_order_rate_limit.py`; the rest of the submit-path hardening work
still requires selective staging, not `git add -A`. The current local live
envelope remains fail-closed by normal caps:
`live_budget_mode=autonomous_with_caps`,
`account_max_capital_at_risk_usd=250.0`, and `per_name_cap_usd=50.0`; optional
`account_hard_ceiling_usd`, `max_live_orders_per_window`, and
`live_order_window_minutes` are still unset and must not be armed without
operator approval. `results/policy/live_control.json` remains unrefreshed with
the dead-man expired at `2026-06-04T19:57:06+00:00`.

Current prep proof: `git check-ignore -v` confirms `config/risk_envelope.yaml`,
`.claude/`, `setup_n8n.py`, and `analysis_mypy.txt` are ignored while
`.codex/hooks` remains reviewable. Code search confirms the submit-path hooks
are present in the working tree: `account_hard_ceiling` and live-order window
checks in `tradingagents/policy/live_gate.py`, submit-time
`control_state_path` live-control re-check wiring in
`tradingagents/execution/tiny_live.py` and `cli/main.py`, and paper/live rollback
manual-reconciliation handling in `tradingagents/brokers/alpaca.py`. The current
tracked hardening diff for the shared files is still concentrated in
`cli/main.py`, `config/risk_envelope.example.yaml`, `tests/test_alpaca_cli.py`,
`tests/test_alpaca_execution.py`, `tests/test_live_gate.py`,
`tradingagents/brokers/alpaca.py`, `tradingagents/policy/live_gate.py`, and
`tradingagents/policy/risk_envelope.py`. Compact context now has only the
expected hourly/BOARD/loss-review flags; the earlier
`agent_intelligence_summary` schema flag is cleared, with 3,648 ledger records
matching the summary and all forecasts still pending/advisory.

2026-06-07 n8n model-route health and orphan-lock repair checkpoint:
`research_automation_orchestration_plan` is now a read-only n8n wrapper around
`research automation-orchestration-plan --candidate-symbols XOM,ADBE,CVX
--no-research-context --json-output`. The policy allowlist keeps it
`submit_capable=false` and the runner stores only a compact parsed summary:
candidate symbols, route statuses, degraded helper lanes, Mac Ollama
reachability/model fields, quality gates, blocker count, telemetry ref count,
and packet path.

Real proof exposed and fixed an operational issue: an ownerless
`results\_context\n8n-runner.lock` directory blocked runner jobs even though no
owner payload existed. `tradingagents/orchestration/run_lock.py` now recovers
ownerless lock directories after a short grace period and chmods stale lock
directories before removal on Windows. The real n8n runner recovered the orphan
lock (`lock_stale_recovered=true`) and returned `status=ok` with
`research_quality_high_enough=true`, `optional_helper_degraded=true`,
`degraded_helper_lanes=["windows_local","mac_ollama"]`,
`mac_ollama_reachable=false`, `fallback_required=false`, `blocker_count=0`, and
`execution_authority=none`.

The n8n built-in evaluation dataset was regenerated and synced to the local
n8n Data Table: `results\n8n_evaluations\n8n-evaluation-dataset-20260607-054313-903039.json`
has 219 rows, 24 allowlisted jobs, and 17 edge tags; sync proof
`results\n8n_evaluations\n8n-api-sync-20260607-054521-434145.json` reports
219 inserted/final rows, `row_count_matches=true`, API key redacted, and the
temporary SQLite copy deleted. Refreshed compact context cleared the n8n audit
flag; remaining flags are the intended hourly/BOARD/loss-review review routes
plus model telemetry because both local helper lanes are currently down.
Focused proof passed with 84 n8n/model tests, targeted Ruff passed, and process
review `results\process_reviews\process-review-20260607-054548.json` reports
`unchecked_step_count=0` and no findings.

## Dispatch order

**P0 → P1 → PA → (P3 ∥ P2) → P5 ongoing; P4 is landed and now in validation/outcome-labeling mode.**

- **P0** is the cheap de-risker (lint/type + registry truth) — land it before editing P1/P2 code.
- **P1** fixes connector transport + routing/leverage; **PA** (auto-fix) consumes P1's health telemetry as failure signals, so it follows P1.
- **P3** and **P2** are independent and parallelizable.
- **P2** depends on nothing but benefits from P1's cleaner data.
- **P5** is continuous and partly underway.
- **P4** is no longer gated on handoff availability: the final MiroFish handoff
  is parsed as advisory-only context. Keep validating its forecasts and
  refreshing the June 4-13 priors instead of treating it as a direct trade
  trigger.

If "best" means max P&L/signal → P1+P2 first. If live-trading reliability → promote P3 above P2. If cost/latency → P5 + LLM routing in `llm_clients/`.

2026-06-07 model-helper self-heal timing checkpoint:
The model telemetry observer now distinguishes an advisory single-helper
degradation from an all-local-helper outage. When both local helper lanes are
blocked and no local helper route is selected, compact context records
`local_helper_repair_signal=true`,
`blocked_local_helper_routes=["mac_ollama_research_mule","windows_local_ollama"]`,
and raises a `model_telemetry` safe-plane repair flag. This is not a trade
blocker: deterministic packet helpers and the Codex/ChatGPT judgment route can
still carry overnight research, but the self-heal monitor now has a timely,
machine-readable reason to re-probe the local lanes instead of silently waiting.

The self-heal model-telemetry action is now a real allowlisted command chain:
`research automation-orchestration-plan --candidate-symbols XOM
--no-research-context --output-dir results/research_batches/model_route_health
--model-telemetry-dir results/model_telemetry --json-output`, then
`research model-telemetry-report --json-output`, then
`scripts/automation_context_snapshot.py --write`. It remains safe-plane only:
`can_submit_orders=false`, `execution_authority=none`, and the executor still
skips/escalates order-adjacent BOARD signals.

Fresh proof: the direct route-health probe wrote
`results\research_batches\model_route_health\research-batch-research-batch-594482b4004044e69a433fa3ebdb6bd0.json`
and confirmed the Mac default model is `deepseek-r1:14b` but the Tailnet
Ollama tags endpoint is currently unreachable (`<urlopen error timed out>`).
Windows local Ollama is still unconfigured. The real self-heal execution wrote
`results\self_heal\plans\self-heal-plan-20260607-055123.json` with
`executed_count=1`, `verified_count=1`, `verify_failed_count=0`, and
`skipped_escalated_count=2`. Automation health then wrote
`results\automation_health\automation-health-audit-20260607-055213.json` with
13/13 automations OK, no issues, and timely self-heal follow-up. Process review
`results\process_reviews\process-review-20260607-055212.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
Focused self-heal, automation-health, and model-routing regression proof passed
with 74 tests.

2026-06-07 Windows local helper auto-discovery checkpoint: the model-helper
warning above was narrowed from "both local helpers down" to "Mac helper
degraded, Windows helper usable." Codex started the installed Windows Ollama
binary hidden, verified `http://127.0.0.1:11434/api/version` and `/api/tags`,
and found the installed model
`tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest`. The CLI now
auto-detects a healthy default Windows Ollama endpoint when no Windows/local
Ollama env var is set; if the default `gpt-oss:20b` is not installed and no
operator model override exists, it uses the first installed tag for that run.
The pure route selector still blocks missing endpoints by default, while
configured endpoints can now be blocked by an explicit health probe when
unreachable or missing the required model.

Real proof: `research automation-orchestration-plan --candidate-symbols
XOM,ADBE,CVX --no-research-context --output-dir
results/research_batches/model_route_health --model-telemetry-dir
results/model_telemetry --json-output` wrote
`results\research_batches\model_route_health\research-batch-research-batch-755c029fae34412182397d8d835817c9.json`.
The packet selected `windows_local_ollama` with the installed qwen model,
reported the Mac `deepseek-r1:14b` lane as optional/degraded due to Tailnet
timeout, kept `research_quality_high_enough=true`, `fallback_required=false`,
`blockers=[]`, `execution_authority=none`, and `can_submit_orders=false`.
`research model-telemetry-report --json-output` wrote
`results\model_telemetry_reports\model-telemetry-report-20260607-060331-009792.json`
with current Windows status `success` and only Mac currently blocked.
`research source-quality-review --json-output --compact-json-output` wrote
`results\source_quality\source-quality-review-20260607-060400.json` with
250 sources, 209 fresh, 41 stale, 21 stale-downranked, and
`stale_needs_refresh_count=0`. The real n8n
`overnight_plan_compact_preview` then ran source quality plus compact overnight
preview successfully and wrote
`results\overnight_plans\n8n\overnight-plan-20260607-060418-000000.json` with
40 ranked candidates, `top_candidate_symbol=MSFT`, `full_graph_count=0`,
`graph_failure_count=0`, and `submitted_count=0`.

Verification: focused model/orchestration tests passed with 31 tests, targeted
Ruff passed, automation health
`results\automation_health\automation-health-audit-20260607-060332.json`
reports 13/13 automations OK with timely self-heal follow-up, and process review
`results\process_reviews\process-review-20260607-060331.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 overnight verifier and stale-BOARD cleanup checkpoint: Codex
refreshed the default `results\research_batches\latest-compact.json` after the
Windows helper auto-discovery fix, so compact context no longer reports
`at_least_one_local_worker_ready` as missing. The refreshed research batch
`results\research_batches\research-batch-research-batch-48f1b423849540d08cf301935617614d.json`
selects `windows_local_ollama`, keeps the Mac helper optional/degraded, has
`advisory_missing_gates=[]`, `blocker_count=0`,
`research_quality_high_enough=true`, and `execution_authority=none`.

The real overnight verifier then passed:
`results\overnight_system_verification\overnight-system-verification-20260607-010942.json`
reports `overall_status=pass`, latest overnight age `5.04` hours inside the
30-hour freshness window, active automation status `ACTIVE`, 40 ranked
candidates, `top_symbol=XOM`, `full_graph_success_count=3`,
`graph_failure_count=0`, and `submitted_count=0`. This proves the original
TradingAgents graph lane is completing through the current automation contract,
while the n8n preview remains compact/dashboard-only.

The stale BOARD/loss-review drilldowns were refreshed against the newest hourly
packet. Loss-review evidence
`results\loss_review_evidence\source-evidence-source-evidence-9343e9daa75949868f6caa9a6140a4a3.json`
now points to
`results\hourly_supervisor\hourly-supervisor-20260607-060828-521016.json`,
resolves 8 of 13 evidence gaps, and leaves 5 true blockers: missing allowed
loss-exit reason, missing allowed-loss-exit source, unresolved current thesis
status, missing loss-exit confidence, and closed market. BOARD review
`results\execution_board\execution-board-review-20260607-061102.json` now
matches that same latest hourly packet, records 0 hard violations and 0
submitted orders, and preserves buy/sell independence: profit sells are
independent, loss exits require proof, and new buys stay limited to separate
controlled dip/support setups with no green-spike chase.

Final context proof: `results\_context\latest-flags.json` now has only the
intentional BOARD/loss-review caution flags. The stale flags and model telemetry
repair flag are gone. Focused regression passed with 111 tests across model
routing, research orchestration, compact context, execution BOARD,
loss-review evidence, and overnight verification; targeted Ruff passed; process
review `results\process_reviews\process-review-20260607-061158.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 P5 n8n compact-output adoption checkpoint: Codex verified the
dashboard/control-plane jobs with real runner calls. `daily_report_preview`
returned `status=ok`, `compact_output_only=true`, `submit_capable=false`, and a
compact `compact_supervisor_daily_report_v1` summary while writing the raw daily
packet to
`results\daily_reports\n8n\supervisor-daily-report-20260607-011853-293175.json`.
Running `compact_output_audit` concurrently first returned `status=busy`, which
confirmed the n8n runner lock serializes jobs instead of overlapping work. A
single retry returned `status=ok`, `submit_capable=false`,
`execution_authority=none`, and wrote
`results\token_efficiency\compact-output-audit-20260607-011933-987395.json` plus
the markdown companion. The audit measured 5 packet families and reduced
6,798,235 raw bytes to 11,516 compact bytes by reference. Focused proof passed:
15 tests covering daily compact output, compact-output audit, n8n daily parsing,
and n8n evaluation datasets.

2026-06-07 P2/P5 follow-up: Codex refreshed the real mature overnight
walk-forward cohort and proved the n8n observer chain can consume the current
calibration/ledger state without overlapping jobs. `research
walk-forward-refresh-overnight-cohort --json-output` wrote
`results\research_batches\walk_forward_cohort_refresh_20260607-062755_h3.json`
from 12 mature overnight packets, 175 return rows, and 420 fixture rows. The
cohort is weak and must keep overnight influence tight: deterministic sleeve
directional accuracy `0.3119`, action-relative return `-1.2219`, and
TradingAgents advisory overlay directional accuracy `0.5000` with false-positive
rate `0.5000`. The refreshed calibration guard
`results\overnight_calibration\overnight-calibration-guard-20260607-062907.json`
therefore returns `guard_decision=tighten`,
`can_increase_live_influence=false`, new buys
`controlled_dip_support_reclaim_only`, replacement buys disabled unless there is
a fresh independent setup, and sells independent/profit-or-BOARD-approved only.

During the n8n proof, back-to-back observer jobs exposed an ownerless
`results\_context\n8n-runner.lock` directory after a successful runner pass.
`tradingagents\orchestration\run_lock.py` now chmods the lock directory before
release cleanup, and a regression proves a read-only lock directory is removed
after a successful job. Real proof: `overnight_calibration_guard` returned
`status=ok`; the parallel `agent_ledger_update`/`outcome_labeling` attempts were
properly refused as `status=busy`; the serial retry of `agent_ledger_update`
recovered the stale lock (`lock_stale_recovered=true`) and returned
`forecast_count=3670`, `resolved_forecast_count=0`,
`execution_authority=none`; the serial `outcome_labeling` run then returned
`status=ok`, `model_outcomes={"unresolved": 156}`, and left no
`n8n-runner.lock` behind. Focused proof passed with 35 P2/n8n/ledger tests, and
targeted Ruff passed.

2026-06-07 real department simulation follow-up: Codex ran the live-data dry-run
department audit after the n8n lock repair. The full default audit
`results\real_simulation_audits\real-simulation-audit-20260607-064030.json`
covered 8 departments and 28 commands with `failed_command_count=0`,
`commands_missing_structured_output=[]`, `total_submitted_order_count=0`,
`unsafe_submission_evidence=false`, and `core_accepted=true`; the only strict
optional failure remains the Mac DeepSeek helper timeout. A smaller one-symbol
real proof after the audit summarizer patch wrote
`results\real_simulation_audits\real-simulation-audit-20260607-064912.json`
with 8 departments, 26 commands, 0 failed commands, 0 submitted orders, and
all structured output present.

The real simulation command summary now includes bounded `attention_samples`
for blocker/stale-heavy commands, so future audits no longer report opaque
counts like "20 blockers" without examples. The real one-symbol audit samples
show the source-quality blockers are fresh research-gap packets such as
`options_iv_flow_gap`, `short_interest_gap`, and `earnings_transcripts_gap`,
plus low-quality stale `yfinance_options`; stale sources remain safe because
all stale rows are downranked or low/unknown quality
(`stale_sources_refreshed_or_downranked=true`). Focused proof passed with 14
real-simulation/source-quality tests and targeted Ruff passed.

The audit also exposed a stale loss-review evidence flag from an older compact
packet. Codex refreshed `research loss-review-evidence --json-output` against
the newest hourly packet and then refreshed BOARD. New evidence packet
`results\loss_review_evidence\source-evidence-source-evidence-6cd6b53f19814032bc847dcd51dac467.json`
matches `results\hourly_supervisor\hourly-supervisor-20260607-065131-399090.json`,
has `entry_context_found=true`, `resolved_blocker_count=8`, and leaves 5 true
manual/session blockers. BOARD
`results\execution_board\execution-board-review-20260607-065350.json` reports
0 hard violations, 0 submitted orders, and the same independent sell/buy policy.
Safe self-heal was rerun; it had no safe-plane actions left and only escalated
order-adjacent BOARD review. Refreshed compact context now has exactly 3
intentional BOARD/loss-review flags and no n8n/source/model/process/self-heal
repair flags.

2026-06-07 BOARD loss-review and email clarity follow-up:
The BOARD review path now reads the latest matching
`results/loss_review_evidence` packet instead of reviewing hourly packets in
isolation. `execution-board-review` attaches `loss_review_evidence`, flags a
`loss_review_evidence_pending` warning when the refreshed packet still lacks
thesis-break confidence, and keeps new buys limited to separate
controlled-dip/support setups. Its Risk Chair language now says HOLD/default
cash remains the posture until BOARD can prove selling is better than holding.

The hourly supervisor now carries that BOARD `loss_review_evidence` summary
into `decision.evidence`, so loss-review alert emails use refreshed counts
instead of the stale immediate `loss_exit_review` blocker count. The latest real
dry-run email says 5 evidence items still open after refresh, 8 resolved, HOLD
remains default, and no live loss sell was submitted. Email clarity proof
`results\email_clarity\email-clarity-20260607-061818.json` passed with score
100, 24 lines, max line length 176, and no issues.

Fresh real audit proof:

- `alpaca check` passed for both paper and live read-only accounts.
- `alpaca supervise-hourly --dry-run --json-output --compact-json-output`
  wrote `results\hourly_supervisor\hourly-supervisor-20260607-061747-678303.json`
  with `submitted_count=0`, `can_submit_orders=false`,
  `execution_authority=none`, and a loss-review HOLD decision.
- `research loss-review-evidence --json-output` wrote
  `results\loss_review_evidence\source-evidence-source-evidence-dd9b26c629cc4b27924cbd505fe826a0.json`
  targeting that latest hourly packet, with 8 blockers resolved and 5 remaining.
- `research execution-board-review --json-output` wrote
  `results\execution_board\execution-board-review-20260607-062012.json`, matched
  the latest hourly packet, found 0 hard issues and 2 warnings, and preserved
  independent sell/buy policy: profit sells are independent, loss exits do not
  force replacement buys, and buys require controlled dip/support evidence.
- `research automation-health-audit --json-output --compact-json-output` wrote
  `results\automation_health\automation-health-audit-20260607-061947.json` with
  13/13 automations OK and timely self-heal follow-up.
- Focused regression passed: 113 tests across model telemetry, self-heal,
  execution BOARD, supervisor, and CLI slices; targeted Ruff passed; process
  review `results\process_reviews\process-review-20260607-062041.json` reports
  `unchecked_step_count=0` and no findings.

Current compact context still flags hourly/BOARD/loss-review because TSM remains
a true pending loss-review, not because an order was submitted or the email is
stale. It no longer flags model telemetry: Windows local Ollama is selected
successfully with `tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest`,
while the Mac `deepseek-r1:14b` helper remains degraded by Tailnet timeout.

2026-06-07 n8n native evaluation run-probe checkpoint:
Codex added a redacted, analysis-only n8n built-in evaluation run probe so the
repo no longer treats "dataset synced" as equivalent to "native evaluation run
triggered." New command:
`research n8n-evaluation-run-probe --json-output`. It resolves the n8n API key
from the normal environment or a temporary copied SQLite database, lists local
workflows, probes the public run/test-run routes for
`TA · Built-in Automation Evaluation`, and writes
`results\n8n_evaluations\latest-run-probe.json`.

Fresh real proof against the running local container wrote
`results\n8n_evaluations\n8n-evaluation-run-probe-20260607-065656-414493.json`.
It found workflow `taBuiltInAutomationEvaluation`, but every public route was
unsupported (`405`, `404`, `405`, `405`), so `status=editor_required`,
`editor_run_required=true`, `supported_endpoint_count=0`,
`can_submit_orders=false`, `execution_authority=none`, and
`api_key_redacted=true`. The temporary SQLite copy was deleted.

Compact context now exposes the same proof under `n8n_evaluation_dataset` as
`run_probe_status`, `run_probe_editor_required`,
`run_probe_supported_endpoint_count`, and `run_probe_path`. Expected
`editor_required` is quiet; broken/missing authority, unredacted key state, or
unexpected run-probe status opens an audit drilldown. Focused proof passed with
17 n8n/context tests, 14 n8n evaluation tests, and targeted Ruff.

2026-06-07 Claude submit-path prep refresh:
Codex re-read the Claude deep-review response and the durable submit-path
handoff before continuing the improvement program. The branch remains
`wip/submit-path-hardening-2026-06-05`; `HEAD` remains unsigned commit
`3970998`, containing only `tradingagents/policy/order_rate_limit.py` and
`tests/test_order_rate_limit.py`. The local live envelope is still fail-closed
and uncommitted: `config/risk_envelope.yaml` parses with `issues=[]`,
`live_budget_mode="autonomous_with_caps"`, account cap `$250`, and per-name cap
`$50`. `results/policy/live_control.json` is not frozen, but the dead-man is
expired at `2026-06-04T19:57:06+00:00`, so live submission remains blocked
unless the operator explicitly refreshes it.

Hygiene remains prepared: `.gitignore` covers `config/risk_envelope.yaml`,
`.claude/`, `setup_n8n.py`, and `analysis_mypy.txt`, while `.codex/` remains
visible for hook review. Fresh proof passed:

- Targeted Ruff over the submit-path files and tests -> passed.
- `uv run --no-sync --with pytest python -m pytest tests/test_order_rate_limit.py tests/test_live_gate.py tests/test_execution_safety.py tests/test_alpaca_execution.py tests/test_alpaca_cli.py -q`
  -> `163 passed in 118.49s`.

2026-06-07 Claude handoff current-prep checkpoint:
Codex re-read the Claude deep-review response and the durable submit-path
handoff again before continuing implementation. The branch remains
`wip/submit-path-hardening-2026-06-05`; `HEAD` remains unsigned commit
`3970998`, and `git show --stat --oneline 3970998` confirms that commit still
contains only `tradingagents/policy/order_rate_limit.py` and
`tests/test_order_rate_limit.py`. The broader submit-path hardening files
remain dirty/shared worktree edits and must be staged only with hunk-level
review; never use `git add -A` here.

SAFE-01 remains prepared fail-closed: `config/risk_envelope.yaml` parses with
`issues=[]`, `live_budget_mode="autonomous_with_caps"`, account cap `$250`,
per-name cap `$50`, and optional hard-ceiling/rate-limit knobs unset.
`results/policy/live_control.json` is not frozen, but its dead-man remains
expired at `2026-06-04T19:57:06+00:00`, so live submission should remain blocked
unless the operator explicitly refreshes live control. `git check-ignore -v`
still protects `config/risk_envelope.yaml`, `.claude/`, `setup_n8n.py`, and
`analysis_mypy.txt`; `.codex/hooks` remains visible for review.

Fresh focused proof from this prep pass:
`uv run --no-sync --with pytest python -m pytest tests/test_order_rate_limit.py -q`
-> `5 passed`. Safety boundary held: no orders, no emails, no dead-man refresh,
no credential changes, no automation status changes, no staging/commit, and no
live-authority changes.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 self-heal timeliness and agent-ledger schema checkpoint:

- Repaired the current `agent_intelligence_summary` schema drilldown by running
  `research agent-ledger-summary --json-output`. The regenerated
  `results\agent_intelligence\summary.json` now reports 4,491 forecasts,
  matching 4,491 records in `results\agent_intelligence\ledger.jsonl`.
- Refreshed compact context now reports
  `summary_ledger_count_matches=true`; the agent-intelligence schema flag is
  gone.
- Ran the real self-heal monitor loop:
  `automation_context_snapshot.py --write`,
  `research self-heal-handoff --json-output`,
  `research self-heal-plan --execute-safe --json-output`, and
  `research automation-health-audit --json-output`.
- Handoff `results\self_heal\self-heal-handoff-20260607-162425.json` was
  followed by plan
  `results\self_heal\plans\self-heal-plan-20260607-162437.json` in 12 seconds.
- Automation health
  `results\automation_health\automation-health-audit-20260607-162446.json`
  reports 13/13 automations OK, `timeliness_issue_count=0`, and
  `self_heal_timeliness.timely=true`.
- Focused self-heal/automation-health tests passed: `6 passed`.
- Process review
  `results\process_reviews\process-review-20260607-162700.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Next action: leave BOARD/order-adjacent review signals as deliberate manual
review/escalation inputs; do not let the safe self-heal loop mutate trading
authority, live gates, emails, or automation statuses.



Tail pointer, latest self-heal timeliness checkpoint, 2026-06-07 16:22 UTC:

Codex refreshed the Agent Intelligence Ledger summary after compact context
showed a schema/count mismatch. `results\agent_intelligence\summary.json` now
matches the ledger at `forecast_count=4491`, `ledger_record_count=4491`,
`agent_count=10`, and `influence_weight_count=10`; compact context no longer
opens `agent_intelligence_summary`.

The subsequent automation-health flag was real: the self-heal monitor had an
actionable handoff and needed a timely follow-up plan. Codex ran the actual
safe-plane executor:

`.\.venv\Scripts\tradingagents.exe research self-heal-plan --execute-safe --json-output`

The executor wrote `results\self_heal\plans\self-heal-plan-20260607-162219.json`,
ran real night-shift patrol evidence plus automation-health audit commands, and
verified the repair. Latest automation health now reports 13/13 OK,
`problem_automation_ids=[]`, no duplicates/stale/late jobs, no submissions, and
`self_heal_timeliness.timely=true` with 51-second follow-up lag. Final compact
flags are back to the expected hourly/BOARD/loss-review review flags only.

Process review proof:
`results\process_reviews\process-review-20260607-162248.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, latest P0/P3 CLI static-audit checkpoint, 2026-06-07 16:16 UTC:

Codex removed the lingering `from cli.utils import *` wildcard from
`cli/main.py`. Explicit imports now cover only the provider/selection helpers
the CLI actually uses. The cleanup exposed two hidden undefined-name defects:
stale unreachable `decision.*` references after `_rank_overnight_results(...)`,
and the plain `alpaca supervisor-daily-report` output branch echoing undefined
`body` instead of the rendered report payload. Both are fixed.

Proof:

- `.\.venv\Scripts\python.exe -m ruff check cli\main.py` -> `All checks passed!`.
- `.\.venv\Scripts\python.exe -m compileall cli\main.py` -> passed.
- `uv run --isolated --with pytest pytest -q tests\test_alpaca_cli.py -k "plan_overnight or verify_overnight or preopen or n8n or research_provider_fallbacks"`
  -> `24 passed, 68 deselected`.
- `uv run --isolated --with pytest pytest -q tests\test_alpaca_cli.py -k "daily_report or supervisor_daily_report"`
  -> `5 passed, 87 deselected`.
- Compact context refreshed.
- `results\process_reviews\process-review-20260607-161652.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 overnight model route refresh checkpoint:

- SAFE-01 remains fail-closed. `config/risk_envelope.yaml` is
  `autonomous_with_caps` with account cap 250.00, per-name cap 50.00, and
  tiny-live tranche 25.00. Commit `3970998` still contains only the standalone
  submit-path rate-limit module and its test.
- Overnight research should use Windows local Ollama plus deterministic packet
  helpers as the current local/free worker set.
- Mac Ollama should stay in the design as a cheap helper lane, but it is
  currently degraded: `http://macbook-pro.tail37edd7.ts.net:11434/api/tags`
  timed out, so `deepseek-r1:14b` must not be treated as required for
  overnight readiness.
- Codex/ChatGPT remains the intelligent judgment route.
- Latest orchestration packet reports `research_quality_high_enough=true`,
  `fallback_required=false`, `at_least_one_local_worker_ready=true`,
  `source_packet_count=14`, and `blocked_source_packet_count=0`.

Fresh proof:

- `results\model_telemetry_reports\model-telemetry-report-20260607-160148-958256.json`
- `results\research_batches\research-batch-research-batch-1d4818323dc949bfb7f4526233280ccb.json`
- Focused route/context tests -> `23 passed, 83 deselected`
- `results\process_reviews\process-review-20260607-160321.json` ->
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`

Next action: keep the Mac lane optional and self-healing, but do not let its
timeout block overnight research while Windows local, deterministic helpers, and
the judgment route are available.

Tail pointer, latest P1/source-routing checkpoint, 2026-06-07 16:04 UTC:

The core OHLCV price decision path now includes the keyed Massive/Polygon
replacement route. `get_stock_data` resolves through
`yfinance -> tiingo -> massive -> alpha_vantage`, and
`core_stock_apis` defaults to `yfinance,tiingo,massive,alpha_vantage`.
Massive daily aggregate bars are adapted into the same CSV-like shape expected
by the original TradingAgents market analyst, preserving prompt/tool
compatibility while adding a higher-authority fallback source.

Proof:

- `uv run --isolated --with pytest pytest -q tests\test_dataflows_interface.py tests\test_dataflows_config.py tests\test_official_dataflows.py`
  -> `53 passed`.
- Targeted Ruff over touched dataflow/config/test files -> `All checks passed!`.
- Targeted compileall over touched dataflow/config modules -> passed.
- `results\_context\source-routing-compact.json` now reports
  `gap_count=0` and `get_stock_data.effective_fallback_chain=["yfinance",
  "tiingo", "massive", "alpha_vantage"]`.
- `results\overnight_system_verification\overnight-system-verification-20260607-110413.json`
  reports `overall_status=pass`, `analysis_only=true`,
  `can_submit_orders=false`, and `execution_authority=none`.
- `results\process_reviews\process-review-20260607-160435.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly branch decomposition completion checkpoint:

The P3 branch-by-branch hourly supervisor decomposition is now complete. The
facade in `tradingagents/brokers/alpaca_supervisor.py` routes through pure
helpers in `tradingagents/brokers/supervisor/hourly.py` for open-order review,
loss-review, profit-taking, buy/no-chase/paper-first, and final trailing hold.
This preserves branch precedence and the current methodology: inspect existing
orders first, never force a replacement buy after a sell/loss review, sell
profitable spikes independently, buy only controlled dips that qualify, and
hold/no-chase after green spikes.

Fresh proof:

- Final branch helper/precedence tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "open_orders_review or trailing_hold or profit_take_still_outranks_trailing or reviews_open_orders_before_loss_or_buy or branch"`
  -> `5 passed, 75 deselected`.
- Targeted Ruff passed over `tradingagents/brokers/supervisor/hourly.py`,
  `tradingagents/brokers/alpaca_supervisor.py`, and
  `tests/test_alpaca_supervisor.py`.
- Compileall passed over the same Python files.
- Real hourly no-submit probe:
  `results\hourly_supervisor\hourly_branch_completion_probe\hourly-supervisor-20260607-155220-678827.json`
  with compact `decision=loss-review`, `submitted_count=0`,
  `issue_count=0`, `can_submit_orders=false`, `execution_authority=none`, and
  `action_count=0`.
- Process review:
  `results\process_reviews\process-review-20260607-155211.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly trailing-hold branch extraction checkpoint:

The no-action fallback tail of `build_hourly_decision(...)` is now isolated in
`tradingagents/brokers/supervisor/hourly.py` as
`build_trailing_hold_decision(...)`. It returns either a material
`profit-review` with no action when a profitable position needs review but the
profit-take branch did not fire, or a quiet `hold` when there is no trigger.

This completes the small branch-by-branch hourly decomposition sequence without
changing submit authority. The decision order remains: open orders first,
loss-review before profit-taking, profit-taking before new buys, new buys before
the trailing review/hold fallback.

Fresh proof:

- Trailing-hold/profit/facade tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "trailing_hold or profit_take_still_outranks or quiet_hourly_hold or profit_review or facade"`
  -> `7 passed, 73 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `80 passed`.
- Hourly/daily CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_supervisor_daily_report_payload_points_to_raw_packet or compact_output_audit_finds_nested_daily_report_packets"`
  -> `17 passed, 75 deselected`.
- Targeted Ruff and compileall passed.
- Real hourly dry-run no-submit probe:
  `results\hourly_supervisor\hourly_trailing_hold_extraction_probe\hourly-supervisor-20260607-154338-781974.json`
  with `decision=loss-review`, `actions=[]`, `submitted=[]`, `issues=[]`.
- Process review:
  `results\process_reviews\process-review-20260607-154406.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

The Agent Intelligence Ledger was normalized after the latest probe; ledger and
summary now match at 4,469 forecasts. Compact context has only the intentional
hourly/BOARD/loss-review flags.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly buy-candidate branch extraction checkpoint:

`build_buy_candidate_decision(...)` now lives in
`tradingagents/brokers/supervisor/hourly.py` and remains available through the
legacy `tradingagents.brokers.alpaca_supervisor` facade. This moves the
paper-first/tiny-live buy branch out of the large supervisor file while keeping
the exact same order: open orders, loss-review, and profit-taking still outrank
new buy candidates.

The extraction hardens the intended trading behavior:

- clean controlled dips can qualify for tiny-live buy sizing inside the supplied
  cap;
- green-spike candidates are explicitly held with "do not chase";
- BOARD pause creates no buy action and remains material;
- non-urgent candidates remain paper-first;
- profitable sell/profit-take branches stay independent and can win before any
  buy candidate.

Fresh proof:

- Buy-branch/facade/precedence tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "buy_candidate or aggressive_decision_can_live_buy or refuses_green_spike or board_pause or paper_first or profit_take_still_outranks or facade"`
  -> `11 passed, 66 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `77 passed`.
- Hourly/daily CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_supervisor_daily_report_payload_points_to_raw_packet or compact_output_audit_finds_nested_daily_report_packets"`
  -> `17 passed, 75 deselected`.
- Targeted Ruff and compileall passed.
- Real hourly dry-run no-submit probe:
  `results\hourly_supervisor\hourly_buy_branch_extraction_probe\hourly-supervisor-20260607-153203-899772.json`
  with `decision=loss-review`, `actions=[]`, `submitted=[]`, `issues=[]`.
- Process review:
  `results\process_reviews\process-review-20260607-153657.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

The Mac helper lane was re-probed and remains genuinely unreachable from
Windows right now: SSH to `macbook-codex` timed out and the Mac Ollama tags
endpoint timed out. Keep the Mac `deepseek-r1:14b` lane optional/degraded until
host/Tailnet reachability returns; do not block overnight research on it while
the explicit Google route and Windows local Ollama fallback are healthy.

Self-heal timeliness was also tested for real, not faked. `research
self-heal-plan --execute-safe --json-output` executed the allowlisted
night-shift patrol and automation-health refresh, then verified automation
health cleanly. The Agent Intelligence Ledger was normalized with
`research agent-ledger-resolve --json-output`; compact context now has only the
intentional hourly/BOARD/loss-review drilldowns.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly profit-take branch extraction checkpoint:

The hourly supervisor now has a tested extracted helper for the profitable
position close/sell path. `build_profit_take_decision(...)` lives in
`tradingagents/brokers/supervisor/hourly.py` and remains available through
`tradingagents.brokers.alpaca_supervisor`. This is the first order-adjacent
branch moved out of the facade, and it was intentionally scoped to preserve
precedence: open-order review still outranks profit-taking, loss-review still
outranks profit-taking, and the helper cannot create any buy action.

This directly supports the current methodology direction: sells and buys are
independent, profitable spikes get reviewed for sale, missing current-price data
forces review instead of blind close, and green-spike buying remains out of this
branch.

Fresh proof:

- Profit/facade/precedence tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "profit or open_orders_still_outrank or loss_review_still_outrank or extracted or facade"`
  -> `8 passed, 62 deselected`.
- Wider focused slice after the Windows daily-report path-format fix:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "daily_report_payload_builder_collects_context_lines or profit or open_orders_still_outrank or loss_review_still_outrank or extracted or facade"`
  -> `9 passed, 62 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `71 passed`.
- Hourly/daily CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_supervisor_daily_report_payload_points_to_raw_packet or compact_output_audit_finds_nested_daily_report_packets"`
  -> `17 passed, 75 deselected`.
- Targeted Ruff and compileall passed.
- Real hourly dry-run no-submit probe:
  `results\hourly_supervisor\hourly_profit_branch_extraction_probe\hourly-supervisor-20260607-150833-590490.json`
  with `decision=loss-review`, `actions=[]`, `submitted=[]`, `issues=[]`.
- Process review:
  `results\process_reviews\process-review-20260607-150907.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

The Agent Intelligence Ledger summary was refreshed with
`research agent-ledger-summary --json-output`; compact context was then
regenerated and the previous `agent_intelligence_summary` schema flag cleared.
The ledger currently has 4,443 forecasts, 0 resolved forecasts, and neutral
agent weights until outcomes mature.

Claude submit-path handoff remains prepared for later review. SAFE-01 is still
fail-closed with capped live budget and lapsed dead-man, and commit `3970998`
still contains only the standalone order-rate-limit module/test.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 daily-report payload boundary checkpoint:

Codex re-read the Claude submit-path handoff before this slice. SAFE-01 remains
fail-closed (`autonomous_with_caps`, account max `$250`, per-name `$50`,
optional hard-ceiling/rate-limit knobs unset, and the live-control dead-man
expired at `2026-06-04T19:57:06+00:00`). Commit `3970998` still contains only
`tradingagents/policy/order_rate_limit.py` and
`tests/test_order_rate_limit.py`.

P3 daily-report decomposition advanced. The report packet/context assembly now
lives beside the renderer in
`tradingagents/brokers/supervisor/daily_report.py` as
`build_supervisor_daily_report_payload(...)`, with the model-telemetry and BOARD
context-line helpers moved there too. `cli/main.py` still owns broker/account
reads, current candidate generation, CLI options, and premarket validation, but
it no longer hand-builds the report body/payload inline.

Fresh proof:

- Focused daily-report builder/CLI tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py::test_daily_report_payload_builder_collects_context_lines tests/test_alpaca_cli.py::test_alpaca_supervisor_daily_report_includes_balances_and_positions tests/test_alpaca_cli.py::test_alpaca_supervisor_daily_report_compact_json_writes_raw_packet tests/test_alpaca_cli.py::test_daily_report_includes_latest_premarket_brief tests/test_alpaca_cli.py::test_compact_supervisor_daily_report_payload_points_to_raw_packet -q`
  -> `5 passed`.
- Daily digest family:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "daily_digest or daily_report_payload or portfolio_snapshot"`
  -> `7 passed, 64 deselected`.
- Daily-report CLI family:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_supervisor_daily_report_payload_points_to_raw_packet or compact_output_audit_finds_nested_daily_report_packets"`
  -> `5 passed, 87 deselected`.
- n8n daily-report summarizer:
  `uv run --no-sync --with pytest python -m pytest tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_compact_daily_report_json tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_daily_report_json -q`
  -> `2 passed`.
- Full supervisor plus CLI files:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py -q`
  -> `163 passed`.
- Targeted Ruff passed over `cli/main.py`,
  `tradingagents/brokers/supervisor/daily_report.py`,
  `tests/test_alpaca_supervisor.py`, and `tests/test_alpaca_cli.py`;
  compileall passed over the edited Python files.
- Real no-submit daily-report probe:
  `results\daily_reports\daily_report_payload_builder_probe\supervisor-daily-report-20260607-150720-246270.json`
  with compact stdout `schema=compact_supervisor_daily_report_v1`,
  `raw_packet_path` pointing at the same raw packet, 7 hourly packets, 40
  ranked candidates, top candidate `MSFT`, BOARD
  `can_submit_orders=false`, and no email/send/submit flag used.
- Process review:
  `results\process_reviews\process-review-20260607-150756.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Remaining P3 decomposition work: continue branch-by-branch hourly decision
decomposition and any remaining premarket/report responsibility splits only
where branch precedence and packet shape can be proven with focused tests plus
real no-submit probes.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly loss-review branch checkpoint:

P3 branch-by-branch hourly decomposition continued. The loss-review branch now
lives in `tradingagents/brokers/supervisor/hourly.py` as
`build_loss_review_decision(...)`, using the existing pure
`loss_exit_review_packet(...)` evidence builder. The facade still supplies the
session/current-price dependencies and public `build_hourly_decision(...)`
remains stable.

Behavior preserved and directly tested: open-order review still outranks
loss-review, loss-review still outranks profit-taking/buy logic, missing
thesis-break evidence returns `loss-review` with no actions, missing current
price blocks an approved loss exit, and an approved loss exit creates an
independent sell plus `hold_cash` rather than a forced replacement buy.

Fresh proof:

- Focused loss-review/precedence tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "loss_review or loss_exit or open_orders_still_outrank_profit_take or loss_review_still_outranks_profit_take or extracted"`
  -> `13 passed, 60 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `73 passed`.
- Hourly CLI guard/submit slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or loss_review or submit or guard"`
  -> `24 passed, 68 deselected`.
- Targeted Ruff and compileall passed over the edited hourly/facade/test files.
- Real hourly no-submit probe:
  `results\hourly_supervisor\hourly_loss_review_branch_probe\hourly-supervisor-20260607-152407-546573.json`
  with compact sidecar `latest-compact.json`, `decision=loss-review`,
  `submitted_count=0`, `issue_count=0`, `can_submit_orders=false`,
  `execution_authority=none`, and `action_count=0`.
- Process review:
  `results\process_reviews\process-review-20260607-152504.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Remaining P3 decomposition work: continue branch-by-branch extraction of the
buy/paper-first/no-chase/hold tail of `build_hourly_decision(...)`, preserving
branch precedence with direct tests and real no-submit probes.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly buy/no-chase tail checkpoint:

The candidate-entry tail of `build_hourly_decision(...)` is confirmed extracted
and wired through `tradingagents/brokers/supervisor/hourly.py` as
`build_buy_candidate_decision(...)`. This helper owns the controlled-dip live
buy, green-spike no-chase hold, BOARD new-buy pause, and paper-first fallback
decisions after open-order, loss-review, and profit-taking branches have already
had priority.

Fresh proof:

- Focused buy/no-chase/paper-first tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "buy_candidate or live_buy_time_sensitive_controlled_dip or green_spike_chase or board_pause or paper_first or loss_review_does_not_pair or loss_review_does_not_rotate"`
  -> `10 passed, 67 deselected`.
- Combined hourly/supervisor/CLI tail slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py -q -k "buy_candidate or live_buy_time_sensitive_controlled_dip or green_spike_chase or board_pause or paper_first or loss_review_does_not_pair or loss_review_does_not_rotate or supervise_hourly or compact_hourly"`
  -> `22 passed, 147 deselected`.
- Targeted Ruff passed over the edited hourly/facade/test files.
- Real hourly no-submit probe:
  `results\hourly_supervisor\hourly_buy_tail_probe\hourly-supervisor-20260607-153130-530914.json`
  with compact sidecar `latest-compact.json`, `decision=loss-review`,
  `submitted_count=0`, `issue_count=0`, `can_submit_orders=false`,
  `execution_authority=none`, and `action_count=0`.
- Process review:
  `results\process_reviews\process-review-20260607-153207.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

The direct tests prove controlled dips can buy, green spikes do not get chased,
BOARD pause blocks new buys, paper-first remains the nonurgent path, and
loss-review cannot pair itself with a replacement buy.

Remaining P3 decomposition work: the main hourly decision tree is now mostly a
branch router. Continue extracting any remaining final hold/profit-review tail
only if it removes meaningful duplication or makes branch precedence easier to
prove; otherwise shift to the next higher-leverage plan item.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 daily-report packet IO extraction checkpoint:

P3 decomposition moved supervisor daily-report packet writing and compact packet
shaping out of `cli/main.py` and into
`tradingagents/brokers/supervisor/daily_report.py` as
`write_supervisor_daily_report_packet(...)` and
`compact_supervisor_daily_report_payload(...)`. The CLI keeps private
compatibility wrappers, so existing tests and call sites keep their current
names while daily report packet IO is owned by the supervisor daily-report
module.

The extracted helpers are reporting-only. They write JSON report packets and
compact summaries; they do not submit/cancel orders, refresh dead-man state,
read secrets, or send email.

Fresh proof:

- Daily-report CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervisor_daily_report or daily_report or compact_output_audit_finds_nested_daily_report_packets"`
  -> `5 passed, 87 deselected`.
- Targeted Ruff and compileall over the daily-report module, CLI, and focused
tests passed.
- Real compact daily-report probe:
  `results\daily_reports\daily_packet_io_extraction_probe\supervisor-daily-report-20260607-145656-470308.json`
  with compact `schema=compact_supervisor_daily_report_v1`, `hourly_packets=7`,
  `material_hourly_packets=7`, `ranked_candidates=40`, live equity `$198.69`,
  paper equity `$98298.21`, and execution-board `can_submit_orders=false`.
- Process review:
  `results\process_reviews\process-review-20260607-145724.json`,
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

The latest context flags remain the intentional hourly notify / BOARD
loss-review routes. Remaining P3 decomposition work should continue
branch-by-branch through hourly decision logic only where precedence can be
proven with focused tests and real no-submit probes.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly packet IO boundary checkpoint:

The remaining hourly packet IO boundary is now explicitly covered. The extracted
module `tradingagents/brokers/supervisor/hourly.py` owns
`build_hourly_evidence(...)`, `serialize_hourly_decision(...)`, and
`write_hourly_decision_packet(...)`. The facade still supplies production
callbacks for alert classification, throttling, email rendering,
client-order-id generation, and order-action detection, but the extracted module
accepts those as injected callbacks and has no direct broker submission
authority.

This checkpoint added direct module-level coverage for that callback-injected
API and kept the legacy wrapper API stable. It intentionally does not move
`build_hourly_decision(...)`; the order-adjacent branch tree should move only
branch-by-branch with precedence tests and real no-submit probes.

Fresh proof:

- Direct hourly packet IO / facade slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "extracted_hourly_packet_io or hourly or packet_writers or facade"`
  -> `12 passed, 55 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `67 passed`.
- Hourly plus daily-report CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_supervisor_daily_report_payload_points_to_raw_packet or compact_output_audit_finds_nested_daily_report_packets"`
  -> `17 passed, 75 deselected`.
- Targeted Ruff and compileall over the supervisor modules, facade, and focused
tests passed.
- Real no-submit hourly probe:
  `results\hourly_supervisor\hourly_packet_io_boundary_probe\hourly-supervisor-20260607-144620-165773.json`
  with `decision=loss-review`, no actions, no issues, no submitted orders, and
  compact `execution_authority=none`.
- Process review:
  `results\process_reviews\process-review-20260607-144649.json`,
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

The latest context flags remain the intentional hourly notify / BOARD
loss-review routes. Remaining P3 decomposition work should move to daily-report
responsibility extraction from `cli/main.py`, then branch-by-branch hourly
decision decomposition only where branch precedence can be proven.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly shared packet IO and router refresh checkpoint:

P3/P5 cleanup continued with a small shared-IO slice. The extracted hourly
packet writer in `tradingagents/brokers/supervisor/hourly.py` now uses
`tradingagents.policy.io.unique_packet_path(...)` instead of keeping a private
duplicate allocator. This keeps hourly packet writes aligned with the shared
policy/control-plane filesystem helper used elsewhere, while preserving the
facade wrapper in `tradingagents.brokers.alpaca_supervisor` that injects
alert/email/client-order dependencies.

`CONTEXT_ROUTER.md` was refreshed at the first-screen current-nearest checks:
future agents now see the latest production overnight packet
`results\overnight_plans\overnight-plan-20260607-101157-000000.json`, latest
overnight verifier
`results\overnight_system_verification\overnight-system-verification-20260607-094459.json`,
latest source-quality review
`results\source_quality\source-quality-review-20260607-111430.json`, and latest
process review `results\process_reviews\process-review-20260607-144636.json`
instead of older 10:00 UTC proof.

Fresh proof:

- `uv run --no-sync --with pytest python -m pytest tests/test_policy_io.py tests/test_alpaca_supervisor.py -q`
  -> `71 passed`.
- `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_supervisor_daily_report_payload_points_to_raw_packet or compact_output_audit_finds_nested_daily_report_packets or verify_overnight_system"`
  -> `21 passed, 71 deselected`.
- Targeted Ruff and compileall over the touched Python files passed.
- Real hourly dry-run probe wrote
  `results\hourly_supervisor\shared_packet_io_probe\hourly-supervisor-20260607-144555-943520.json`
  and compact sidecar with `schema=compact_hourly_supervisor_v1`,
  `submitted_count=0`, `issue_count=0`, `execution_authority=none`, and
  `can_submit_orders=false`.
- Real overnight verifier wrote
  `results\overnight_system_verification\overnight-system-verification-20260607-094459.json`
  with `overall_status=pass`, 16/16 checks passed, no warnings/failures, and no
  submitted orders.
- Final process review wrote
  `results\process_reviews\process-review-20260607-144636.json` with
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly loss-review packet helper extraction checkpoint:

P3 decomposition moved loss-exit review evidence packet construction into
`tradingagents/brokers/supervisor/loss_review.py`. The legacy supervisor facade
now imports and re-exports `loss_exit_review_packet(...)`, while the previous
private `_loss_exit_review_packet(...)` stays as a compatibility wrapper. This
keeps existing CLI/tests/automation imports stable and isolates the BOARD
loss-review evidence contract in a module with no broker submission authority.

The extracted module owns the loss-exit reason taxonomy, recent-position churn
guard, broad-market weakness filter, required SPY/QQQ/sector context checks,
holding-period parsing, confidence/source-packet requirements, and blocker list.
It only returns evidence and blocker data; it does not approve, size, submit, or
cancel orders.

Fresh proof:

- Focused loss-review/facade/hourly tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "loss or review or extracted or facade or hourly"`
  -> `18 passed, 48 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `66 passed`.
- Hourly plus daily-report CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_supervisor_daily_report_payload_points_to_raw_packet or compact_output_audit_finds_nested_daily_report_packets"`
  -> `17 passed, 75 deselected`.
- Targeted Ruff and compileall over the supervisor modules/facade/tests passed.
- Real no-submit hourly probe:
  `results\hourly_supervisor\hourly_loss_review_extraction_probe\hourly-supervisor-20260607-143752-856089.json`
  with `decision=loss-review`, no actions, no issues, no submitted orders, and
  compact `execution_authority=none`.
- Process review:
  `results\process_reviews\process-review-20260607-143822.json`,
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

The latest context flags remain the intentional hourly notify / BOARD
loss-review routes. SAFE-01 remains fail-closed with local caps armed under
`autonomous_with_caps` and the dead-man still lapsed.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly order/notification helper extraction checkpoint:

P3 decomposition continued by moving hourly order/notification formatting
helpers into `tradingagents/brokers/supervisor/orders.py`:

- `should_notify_supervisor(...)`
- `is_order_action(...)`
- `build_supervisor_order_payload(...)`

The legacy `tradingagents.brokers.alpaca_supervisor` facade re-exports the same
names, preserving existing CLI/test/automation imports. The new module is
formatting/classification only and does not validate live authority, refresh the
dead-man, call Alpaca, or submit orders.

Codex inspected the remaining hourly decision engine and found adjacent
decomposition already present (`HourlyDecisionContext` and
`build_open_orders_review_decision(...)`). To avoid a risky bulk move on top of
that changing boundary, this checkpoint intentionally stops at the
order/notification helper layer.

Fresh proof:

- Focused supervisor order/facade/hourly slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "extracted or facade or notify or order_payload or order_action or hourly"`
  -> `10 passed, 56 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `66 passed`.
- Hourly plus daily-report CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_supervisor_daily_report_payload_points_to_raw_packet or compact_output_audit_finds_nested_daily_report_packets"`
  -> `17 passed, 75 deselected`.
- Targeted Ruff and compileall over the extracted order module, supervisor
  package, facade, and focused tests passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\hourly_orders_extraction_probe\hourly-supervisor-20260607-142308-275624.json`
  with `decision=loss-review`, no actions, no issues, no submitted orders, and
  compact `execution_authority=none`.
- Automation health refreshed cleanly at
  `results\automation_health\automation-health-audit-20260607-142426.json`:
  13 OK automations, no problem jobs, self-heal follow-up lag 52 seconds.
- Agent Intelligence summary refreshed to match the ledger:
  `forecast_count=4422`, `ledger_record_count=4422`,
  `summary_ledger_count_matches=true`.
- Compact context still only carries intentional hourly/loss-review/BOARD
  review flags.
- Process review:
  `results\process_reviews\process-review-20260607-142453.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Remaining P3 decomposition work: isolate loss-exit review helpers, then move
`build_hourly_decision(...)` in its own test-backed slice; daily-report packet
IO stays later.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Latest P3 checkpoint, 2026-06-07 14:09 UTC:

The next `build_hourly_decision(...)` slice followed the code-mapper
recommendation: extract only the pure pre-decision context scan first.
`tradingagents/brokers/supervisor/hourly.py` now owns
`HourlyDecisionContext` and `build_hourly_decision_context(...)`; the facade
re-exports it and `build_hourly_decision(...)` uses it to get held symbols,
unused live capacity, best unheld candidate, worst position, and best position.

This deliberately avoids moving branch semantics yet. Loss-review, live-buy,
BOARD pause, chase suppression, profit-review, and downstream live-submit action
shape stay in the facade until each can move with branch-specific coverage.

Fresh proof:

- Focused hourly/facade/context tests -> `10 passed, 54 deselected`.
- Full supervisor tests -> `64 passed`.
- CLI submit-shape/hourly/report slice -> `32 passed, 60 deselected`.
- Policy IO regression -> `5 passed`.
- Targeted Ruff and compileall passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\hourly_decision_context_probe\hourly-supervisor-20260607-140918-597923.json`
  with `decision=loss-review`, `submitted=0`, `actions=0`, `issues=0`,
  `execution_authority=none`, and `can_submit_orders=false`.
- Process review:
  `results\process_reviews\process-review-20260607-140953.json` with
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Next P3 move: add direct coverage for `review-open-orders`, then extract one
low-risk branch at a time. Avoid a broad move of the whole decision tree.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly data-contract extraction checkpoint:

P3 decomposition continued by moving the pure hourly data contracts into
`tradingagents/brokers/supervisor/types.py`:

- `HourlySupervisorConfig`
- `HourlySupervisorAction`
- `HourlySupervisorDecision`

The legacy `tradingagents.brokers.alpaca_supervisor` facade re-exports the same
names, so existing CLI callers, automations, and tests keep the old import
surface while the next `build_hourly_decision(...)` extraction has a stable
contract module to target.

Fresh proof:

- Focused supervisor type/facade/hourly slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "extracted or facade or hourly or action or decision"`
  -> `13 passed, 50 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `64 passed`.
- Hourly plus daily-report CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_supervisor_daily_report_payload_points_to_raw_packet or compact_output_audit_finds_nested_daily_report_packets"`
  -> `17 passed, 75 deselected`.
- Targeted Ruff and compileall over the extracted type module, supervisor
  package, facade, and focused tests passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\hourly_types_extraction_probe\hourly-supervisor-20260607-140838-048532.json`
  with `decision=loss-review`, no actions, no issues, no submitted orders, and
  compact `execution_authority=none`.
- Agent Intelligence summary was refreshed after compact context caught a
  ledger drift. It now reports `forecast_count=4417`,
  `ledger_record_count=4417`, and `summary_ledger_count_matches=true`.
- Compact context still only carries intentional hourly/loss-review/BOARD
  review flags.
- Process review:
  `results\process_reviews\process-review-20260607-141028.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Remaining P3 decomposition work: isolate and move `build_hourly_decision(...)`
in its own test-backed slice, then move daily-report packet IO later.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly alert and email contract extraction checkpoint:

Claude submit-path hardening prep was re-read before continuing. SAFE-01 stays
fail-closed (`autonomous_with_caps`, local `$250` account cap, `$50` per-name
cap), the live-control dead-man remains expired, and the standalone rate-limit
commit `3970998` remains the only committed submit-path artifact from the
Claude handoff.

P3 decomposition continued by moving the hourly alert contract out of the large
supervisor facade. `SupervisorAlert`, alert fingerprinting/throttling,
classification, and the hourly alert email renderer now live in
`tradingagents/brokers/supervisor/alert.py`, while
`tradingagents.brokers.alpaca_supervisor` keeps the same public helper names
for existing CLI, tests, and automations.

Fresh proof:

- `uv run --no-sync --with pytest python -m pytest tests/test_email_clarity_eval.py -q`
  -> `4 passed`.
- `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py -q -k "alert or email or throttle or hourly or extracted or facade or compact_hourly"`
  -> `27 passed, 128 deselected`.
- `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `63 passed`.
- Targeted Ruff and compileall over the extracted alert/hourly modules,
  supervisor facade, and focused tests passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\hourly_alert_extraction_probe\hourly-supervisor-20260607-135351-891610.json`
  with `decision=loss-review`, no actions, no issues, no submitted orders,
  `alert.severity=NOTABLE`, and a short plain-English loss-review email body.
- Compact context still only carries intentional hourly/loss-review/BOARD
  review flags.
- Process review:
  `results\process_reviews\process-review-20260607-135731.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Remaining P3 decomposition work: extract hourly decision dataclasses and the
state machine only after dedicated tests, then move daily-report packet IO in a
later slice.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 generic packet IO checkpoint:

The CLI no longer imports generic packet-writing helpers from
`tradingagents.brokers.alpaca_supervisor`. `tradingagents/policy/io.py` now
owns `unique_packet_path(...)` beside `atomic_write_text(...)`, and
`cli/main.py` imports both from policy IO. The supervisor facade no longer needs
to re-export `_atomic_write_text` or `_unique_packet_path`; keep it focused on
supervisor behavior before moving `build_hourly_decision(...)`.

Fresh proof:

- `tests/test_policy_io.py` -> `5 passed`.
- `tests/test_alpaca_supervisor.py` -> `63 passed`.
- `tests/test_alpaca_cli.py -k "supervise_hourly or compact_hourly or preopen_validation or supervisor_daily_report or compact_output_audit"` -> `22 passed, 70 deselected`.
- Targeted Ruff and compileall passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\policy_io_cli_probe\hourly-supervisor-20260607-135402-987759.json`
  with `decision=loss-review`, `submitted=0`, `actions=0`, `issues=0`,
  `execution_authority=none`, and `can_submit_orders=false`.
- Process review:
  `results\process_reviews\process-review-20260607-135909.json` with
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 work: use the `build_hourly_decision(...)` dependency map before
moving any live-gate/BOARD/loss-review branches.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly packet IO isolation checkpoint:

Codex re-read the Claude submit-path hardening handoff and verified the active
fail-closed posture before editing: `config/risk_envelope.yaml` still loads as
`autonomous_with_caps`, account max `$250`, per-name `$50`, optional
hard-ceiling/rate-limit knobs unset, and `issues=[]`; the live-control dead-man
is still expired. Commit `3970998` still contains only
`tradingagents/policy/order_rate_limit.py` and `tests/test_order_rate_limit.py`.

P3 decomposition continued by making the hourly supervisor facade delegate
`build_hourly_evidence(...)`, `serialize_hourly_decision(...)`, and
`write_hourly_decision_packet(...)` to
`tradingagents/brokers/supervisor/hourly.py`. The duplicate end-of-file helper
cluster in `tradingagents/brokers/alpaca_supervisor.py` was removed. The only
remaining private compatibility exports are `_atomic_write_text` and
`_unique_packet_path`, because `cli/main.py` still imports them for generic
report packet writers; extract those CLI packet writers later instead of
breaking the current CLI surface.

Fresh proof:

- `tests/test_alpaca_supervisor.py -k "hourly or extracted or facade or packet_writers"` -> `9 passed, 54 deselected`.
- `tests/test_alpaca_supervisor.py` -> `63 passed`.
- `tests/test_alpaca_cli.py -k "supervise_hourly or compact_hourly"` -> `12 passed, 80 deselected`.
- Targeted Ruff and compileall passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\hourly_io_extraction_probe\hourly-supervisor-20260607-134457-819380.json`
  with `decision=loss-review`, `submitted=0`, `actions=0`, `issues=0`,
  compact `schema=compact_hourly_supervisor_v1`, `submitted_count=0`,
  `execution_authority=none`, and `can_submit_orders=false`.
- Process review:
  `results\process_reviews\process-review-20260607-134532.json` with
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 work: move `build_hourly_decision(...)` only after a bounded
decision-tree slice is mapped and test-backed, then move the generic CLI packet
IO helpers out of the supervisor facade.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly evidence and packet writer extraction checkpoint:

P3 decomposition continued by moving the hourly evidence builder and packet IO
contract into `tradingagents/brokers/supervisor/hourly.py`. The legacy
`tradingagents.brokers.alpaca_supervisor` facade keeps the public names
`build_hourly_evidence(...)`, `serialize_hourly_decision(...)`, and
`write_hourly_decision_packet(...)`, but the facade now delegates to the
extracted module and injects the existing alert classifier, alert throttler,
alert email renderer, stable client-order-id builder, and order-action
predicate. This keeps alert/noise/idempotency behavior unchanged while making
the hourly packet boundary independently auditable.

Fresh proof:

- Focused hourly/facade tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "hourly or extracted or facade or packet_writers"`
  -> `9 passed, 54 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `63 passed`.
- Hourly plus daily-report CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_supervisor_daily_report_payload_points_to_raw_packet or compact_output_audit_finds_nested_daily_report_packets"`
  -> `17 passed, 75 deselected`.
- Targeted Ruff and compileall over the extracted module/facade/tests passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\hourly_contract_extraction_probe\hourly-supervisor-20260607-133557-140742.json`
  with `decision=loss-review`, `submitted=[]`, `actions=[]`, and `issues=[]`.
  Its compact sidecar reports `submitted_count=0`,
  `can_submit_orders=false`, `execution_authority=none`,
  `market_session=closed`, and top candidate `MSFT`.

Remaining P3 decomposition work: extract the alert/email contract only after a
dedicated alert-contract test slice; move the actual hourly decision state
machine last.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 daily report renderer extraction checkpoint:

P3 supervisor decomposition advanced again. The daily digest renderer now lives
in `tradingagents/brokers/supervisor/daily_report.py`, and the legacy
`tradingagents.brokers.alpaca_supervisor` facade imports and re-exports
`render_daily_supervisor_report` for compatibility with CLI, tests, and
automations.

This is reporting-only: no order-submission, live-gate, risk-envelope,
packet-schema, compact-output, email-route, credential, automation-status,
dead-man, or live-authority behavior changed. The new module keeps private
formatting helpers local for now so the later hourly-decision extraction can
decide whether to share or move alert formatting without a circular import.

Fresh proof:

- Full `tests/test_alpaca_supervisor.py`: `63 passed`.
- Daily-report CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py::test_alpaca_supervisor_daily_report_includes_balances_and_positions tests/test_alpaca_cli.py::test_alpaca_supervisor_daily_report_compact_json_writes_raw_packet tests/test_alpaca_cli.py::test_daily_report_includes_latest_premarket_brief tests/test_alpaca_cli.py::test_compact_supervisor_daily_report_payload_points_to_raw_packet -q`
  -> `4 passed`.
- Targeted Ruff over the supervisor facade, extracted daily-report module, and
  focused tests passed; compileall over the supervisor package and facade
  passed.
- Real compact daily-report preview:
  `results\daily_reports\daily_report_extraction_probe\supervisor-daily-report-20260607-081540-459683.json`
  with compact stdout `schema=compact_supervisor_daily_report_v1`,
  `hourly_packets=7`, `material_hourly_packets=7`, `ranked_candidates=40`,
  `top_candidate=MSFT`, premarket context `top_symbol=XOM`, execution-board
  `can_submit_orders=false`, and a raw body reference only.

Remaining P3 decomposition work: extract hourly decision assembly and any
shared alert/report formatting in small, test-backed slices while preserving the
public facade.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 premarket builder extraction checkpoint:

P3 supervisor decomposition advanced again. `build_premarket_brief_packet(...)`
and its private packet-record/timeline/material-change helpers now live in
`tradingagents/brokers/supervisor/premarket.py`, beside the already-extracted
premarket validation, render, compact, write, and load helpers. The legacy
`tradingagents.brokers.alpaca_supervisor` facade imports and re-exports
`build_premarket_brief_packet`, preserving CLI, tests, and automation imports.

This is a pure refactor slice: no live-gate, cap, order-submission,
packet-schema, automation-status, email, credential, dead-man, or
latest/no-latest behavior changed.

Fresh proof:

- Full `tests/test_alpaca_supervisor.py`: `63 passed`.
- Premarket CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py::test_premarket_brief_command_is_file_only tests/test_alpaca_cli.py::test_compact_premarket_brief_payload_points_to_raw_packet tests/test_alpaca_cli.py::test_premarket_brief_compact_json_output_is_file_only tests/test_alpaca_cli.py::test_preopen_supervisor_includes_premarket_brief_validation -q`
  -> `4 passed`.
- Targeted Ruff over the supervisor facade, extracted premarket module, and
  focused tests passed; compileall over the supervisor package and facade
  passed.
- Real analysis-only no-latest premarket probe:
  `results\premarket_briefs\premarket_builder_extraction_probe\premarket-brief-20260607-130409-000000.json`
  with compact stdout `schema=compact_premarket_brief_v1`,
  `source_packets=54`, `timeline=54`, `top_symbol=XOM`,
  `latest_hourly_decision=loss-review`,
  `paper_tournament_leader=pullback-support`, `unresolved_blockers=0`,
  `stale_warnings=0`, and `execution_authority=none`.

Remaining P3 decomposition work: continue extracting hourly decision assembly
and daily-report responsibilities in small, test-backed slices while preserving
the public facade.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 P3 supervisor candidate/sizing/session/premarket decomposition checkpoint:
Codex continued the remaining supervisor decomposition work with four pure
slices.
The buy-dip/sell-spike-adjacent ranking helpers, MiroFish/report-33
false-signal scoring, `CandidateSignal`,
`choose_autonomous_live_buy_notional(...)`, and `aggressive_limit_price(...)`
now live in `tradingagents/brokers/supervisor/candidates.py`. Exposure and
dynamic-cap helpers (`BASE_LIVE_CAP`, `MAX_DYNAMIC_LIVE_CAP`,
`live_exposure_from_positions(...)`, `total_unrealized_pl(...)`, and
`calculate_dynamic_live_cap(...)`) now live in
`tradingagents/brokers/supervisor/sizing.py`. Market-session helpers
(`market_session_label(...)` and `can_trade_session(...)`) now live in
`tradingagents/brokers/supervisor/session.py`. Premarket validation,
research-context compaction, expected hourly safety-lock classification, and
premarket blocker splitting now live in
`tradingagents/brokers/supervisor/premarket.py`. The legacy
`tradingagents.brokers.alpaca_supervisor` module explicitly re-exports those
symbols through `__all__`, so existing CLI, paper tournament, and tests keep
their old imports while new work can depend on narrower responsibility modules.

Fresh proof:

- Focused candidate/no-chase/sizing tests: `9 passed`, followed by focused
  sizing/candidate regression `4 passed`, and focused session/facade regression
  `2 passed`.
- Focused premarket extraction regression: `6 passed`.
- Full supervisor unit file: `63 passed`.
- Import-adjacent CLI/paper tournament slice: `3 passed`.
- CLI premarket slice: `4 passed`.
- Targeted Ruff over `alpaca_supervisor.py`, the new supervisor package, and
  `tests/test_alpaca_supervisor.py` passed.
- Compile check over `tradingagents/brokers/supervisor` and
  `tradingagents/brokers/alpaca_supervisor.py` passed.
- Real no-submit hourly dry-run probe:
  `results\hourly_supervisor\premarket_module_probe\hourly-supervisor-20260607-124208-635006.json`
  with `schema=compact_hourly_supervisor_v1`, `decision=loss-review`,
  `submitted_count=0`, and `can_submit_orders=false`.
- Real file-only premarket brief probe:
  `results\premarket_briefs\premarket_module_probe\premarket-brief-20260607-124159-000000.json`
  with `schema=compact_premarket_brief_v1`, `source_packets=54`,
  `unresolved_blockers=0`, `stale_warnings=0`,
  `execution_authority=none`, and no latest pointer update.
- Real no-latest overnight probe:
  `results\overnight_plans\premarket_module_probe\overnight-plan-20260607-124210-000000.json`
  with `schema=compact_overnight_plan_v1`, `trade_date=2026-06-08`,
  `ranked_candidates=40`, `fallback_count=40`, `submitted_count=0`, and
  `execution_authority=none`.
- Compact context refresh left only the expected hourly/BOARD/loss-review
  review flags; process review
  `results\process_reviews\process-review-20260607-122005.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 decomposition work: continue extracting larger responsibilities
from `alpaca_supervisor.py` (`hourly`, the remaining premarket packet
construction/rendering/writing layer, and `daily_report`) in small
compatibility-preserving slices.
This checkpoint does not change live authority, order policy, automation
statuses, dead-man state, credentials, emails, or packet schemas.

2026-06-07 n8n duplicate-evidence evaluation checkpoint:
The n8n built-in evaluation dataset now covers the overnight calibration
duplicate-row failure mode directly. `tradingagents/orchestration/n8n_evaluations.py`
adds scenario `duplicate_evidence_deduped_before_scoring`, edge tag
`duplicate_evidence`, and metric rule
`duplicate_symbol_as_of_rows_are_skipped_before_calibration`; every allowlisted
job gets the case, including `overnight_calibration_guard`.

Fresh proof:

- `tests/test_n8n_evaluations.py` -> `16 passed`.
- `tests/test_n8n_runner_policy.py -k "evaluation_dataset or overnight_calibration"`
  -> `3 passed`.
- Targeted Ruff over the n8n evaluation files passed.
- `research n8n-evaluation-dataset --json-output --compact-json-output` wrote
  `results\n8n_evaluations\n8n-evaluation-dataset-20260607-120614-394063.json`
  with `row_count=243`, `edge_tag_count=18`, and
  `duplicate_evidence` present.
- Real local n8n Data Table sync wrote
  `results\n8n_evaluations\n8n-api-sync-20260607-120733-909721.json`, replacing
  the prior 219 rows with 243 rows and `row_count_matches=true`.
- Built-in eval run probe wrote
  `results\n8n_evaluations\n8n-evaluation-run-probe-20260607-120833-367542.json`:
  workflow found, but `status=editor_required` because this n8n API surface does
  not expose a supported remote test-run endpoint. The table is ready; run the
  evaluation from the n8n editor/evaluations UI at `http://localhost:5678` when
  a manual built-in eval run is needed.
- Compact context refreshed and process review
  `results\process_reviews\process-review-20260607-120903.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 compact-context cleanup checkpoint:

Codex refreshed `research agent-ledger-summary --json-output` after the ledger
advanced during the n8n evaluation proof work. Compact context now treats the
Agent Intelligence Ledger summary as current, not as a schema drilldown.

Fresh proof:

- `results\_context\latest-summary.json` reports
  `agent_intelligence_summary/forecast_count=4389`,
  `ledger_record_count=4389`, `summary_ledger_count_matches=true`,
  `agent_count=10`, `influence_weight_count=10`, and
  `drilldown_required=false`.
- `results\_context\latest-flags.json` contains only the intentional hourly
  notify, hourly BOARD review, execution BOARD review, and loss-review evidence
  BOARD review routes.
- Process review
  `results\process_reviews\process-review-20260607-122207.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 n8n built-in evaluation full-dataset checkpoint:
Codex closed a real n8n evaluation coverage gap. The source-controlled native
Evaluation Trigger workflow `n8n/workflows/ta-built-in-automation-evaluation.json`
was connected to the 219-row `TradingAgents_Automation_Evaluations` Data Table,
but it still had `limitRows=true` / `maxRows=25`. That meant an editor-run
n8n evaluation could silently sample only the first 25 cases instead of covering
all allowlisted automation wrappers and edge cases.

Changed:

- The native Evaluation Trigger now has `limitRows=false` and no `maxRows`,
  so editor-side n8n evaluations can run the full synced Data Table.
- `tradingagents/orchestration/n8n_workflow_sync.py` now updates existing
  source-controlled workflows through the public n8n API instead of only
  creating missing workflows. Workflows stay inactive, analysis-only, and
  non-trading.
- Compact context now exposes `workflow_sync_updated_count` and updated workflow
  names, so dashboards/Codex can prove local n8n picked up source changes.

Fresh proof:

- Focused tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_n8n_evaluations.py tests/test_automation_context_snapshot.py::test_snapshot_summarizes_n8n_evaluation_dataset_and_sync_proof tests/test_automation_context_snapshot.py::test_snapshot_flags_n8n_workflow_sync_when_missing -q`
  -> `18 passed`.
- Targeted Ruff over n8n workflow sync, evaluation tests, and compact context
  passed.
- Real Docker n8n workflow sync used a temporary SQLite-key copy and deleted it
  afterward. It wrote
  `results\n8n_evaluations\n8n-workflow-sync-20260607-115951-020420.json` with
  `status=ok`, `source_workflow_count=12`, `existing_count=12`,
  `updated_count=12`, `created_count=0`, `api_key_redacted=true`, and all
  updated workflows inactive.
- Real native run-probe wrote
  `results\n8n_evaluations\n8n-evaluation-run-probe-20260607-120018-912286.json`.
  It still reports `status=editor_required`, `workflow_found=true`,
  `supported_endpoint_count=0`, and `api_key_redacted=true`, confirming local
  n8n requires the editor/evaluations UI to start native Evaluation Trigger
  runs.
- Refreshed compact context reports `row_count=219`, `allowlisted_job_count=24`,
  `edge_tag_count=17`, Data Table sync current, workflow sync current with
  `workflow_sync_updated_count=12`, and no n8n drilldown flag.
- Process review
  `results\process_reviews\process-review-20260607-120048.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 n8n evaluation sync consistency repair:
Compact context surfaced a real n8n evaluation audit flag after the Data Table
sync: `latest-sync.json` had synced a newly generated dataset while
`latest.json` / `latest-compact.json` still pointed to the previous dataset.
Row counts matched, but `sync_current_dataset_generated_at_matches=false`, so
morning agents could not prove the n8n Data Table represented the current
evaluation dataset.

Codex patched `tradingagents/orchestration/n8n_api_sync.py` so successful syncs
that build their own dataset write the exact dataset artifacts they sync. This
keeps `latest.json`, `latest-compact.json`, `latest.csv`, and
`latest-sync.json` aligned by `dataset_generated_at`.

Real proof:

- Regression test added:
  `test_n8n_api_sync_writes_same_dataset_that_it_syncs`.
- Focused tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_n8n_evaluations.py tests/test_automation_context_snapshot.py::test_snapshot_summarizes_n8n_evaluation_dataset_and_sync_proof tests/test_automation_context_snapshot.py::test_snapshot_flags_n8n_sync_proof_when_dataset_row_count_drifted tests/test_automation_context_snapshot.py::test_snapshot_flags_n8n_sync_proof_when_same_row_count_but_older_dataset tests/test_automation_context_snapshot.py::test_snapshot_flags_n8n_workflow_sync_when_missing -q`
  -> `19 passed`.
- Targeted Ruff over n8n sync/eval/context files passed.
- Real n8n Data Table sync used a temporary copied Docker SQLite database only
  to read the existing local API key, wrote redacted proof, and the temporary DB
  copy was deleted afterward. `latest-sync.json` now reports `status=ok`,
  `final_row_count=219`, `expected_row_count=219`, `row_count_matches=true`,
  `column_count=23`, `api_key_redacted=true`, and
  `dataset_generated_at=2026-06-07T11:33:58+00:00`.
- Refreshed compact context now reports for `n8n_evaluation_dataset`:
  `sync_current_dataset_generated_at_matches=true`,
  `sync_current_row_count_matches=true`, `workflow_sync_status=ok`,
  `run_probe_status=editor_required`, and `drilldown_reasons=[]`.
- Process review
  `results\process_reviews\process-review-20260607-113527.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

The n8n built-in evaluation workflow still requires editor/UI execution when
the local public API reports `editor_required`; the Data Table dataset and sync
proof are now current and redacted for that UI run.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 current overnight-system verifier and n8n preview checkpoint:
Codex ran the current no-submit verification path for the real overnight
pipeline plus the n8n dashboard wrapper. The production overnight packet is
fresh and complete for the next market date, while n8n remains a wrapper only.

Real proof:

- `alpaca verify-overnight-system --json-output` wrote
  `results\overnight_system_verification\overnight-system-verification-20260607-061428.json`
  and compact sidecar `results\overnight_system_verification\latest-compact.json`.
  `overall_status=pass`, 16/16 checks passed, latest overnight age `1.04h`,
  expected/actual trade date `2026-06-08`, and automation status `ACTIVE`.
- Latest production overnight compact packet:
  `results\overnight_plans\latest-compact.json` points to
  `results\overnight_plans\overnight-plan-20260607-101157-000000.json`, top
  candidate `XOM`, 40 ranked candidates, 3/3 original TradingAgents graph
  successes, 37 fallback-ranked symbols, `graph_failure_count=0`,
  `research_context_packet_count=14`, `research_context_blocked_count=0`,
  and `submitted_count=0`.
- The production graph route remains explicit Google:
  `gemini-2.5-flash-lite` quick and `gemini-2.5-flash` deep, with the
  million-token context-window metadata carried in the packet.
- Source-quality refreshed through n8n first:
  `results\source_quality\source-quality-review-20260607-111430.json` /
  `latest-compact.json` show 250 sources, 224 fresh, 26 stale, 18
  stale-downranked, `stale_needs_refresh_count=0`, 31 blocked gap packets, and
  `missing_or_invalid_count=0`.
- `python -m tradingagents.orchestration.n8n_runner --run-job
  overnight_plan_compact_preview --json` returned `status=ok`,
  `submit_capable=false`, two successful steps, and a parsed compact preview at
  `results\overnight_plans\n8n\overnight-plan-20260607-111445-000000.json`.
  The preview top candidate was `MSFT`, but this is expected because the n8n job
  is a zero-full-graph/no-latest/no-ledger dashboard preview and is not the
  production overnight authority.
- `research automation-health-audit --json-output --compact-json-output` wrote
  `results\automation_health\automation-health-audit-20260607-111431.json` with
  13/13 automations OK, no stale/late/duplicate/missing/warning issues, no
  submissions, and timely self-heal follow-up.
- Compact context refreshed at `2026-06-07T11:09:56+00:00`; latest flags only
  open intentional hourly notify, hourly BOARD review, execution BOARD review,
  and loss-review evidence review routes.
- Process review
  `results\process_reviews\process-review-20260607-111600.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
- Focused tests:
  `tests/test_alpaca_cli.py::test_verify_overnight_system_audits_full_chain`
  plus `tests/test_source_quality.py` -> `11 passed`;
  `tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_overnight_plan_compact_preview_json`
  -> `1 passed`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 submit-path and overnight calibration checkpoint:
Codex re-read the Claude submit-path hardening review and re-verified the
current local safety posture before continuing overnight-readiness work.
SAFE-01 remains fail-closed: `config/risk_envelope.yaml` parses as
`live_budget_mode=autonomous_with_caps`, account max `$250.00`, per-name
`$50.00`, optional hard-ceiling/rate-limit knobs unset, and `issues=[]`.
`results/policy/live_control.json` remains expired at
`2026-06-04T19:57:06+00:00`; no live authority was refreshed.

The Agent Intelligence summary was stale again after tests and was repaired
with the existing analysis-only command `research agent-ledger-summary
--json-output`, not by hand-editing results. Compact context now shows
`forecast_count=4342`, `ledger_record_count=4342`,
`summary_ledger_count_matches=true`, 10 advisory influence-weighted agents, and
no resolved forecasts yet. The `agent_intelligence_summary` schema drilldown is
cleared.

The current overnight walk-forward cohort and calibration guard were refreshed
analysis-only:

- Cohort packet:
  `results\research_batches\walk_forward_cohort_refresh_20260607-110407_h3.json`.
- Guard packet:
  `results\overnight_calibration\overnight-calibration-guard-20260607-110523.json`.
- Guard decision: `tighten`; `can_increase_live_influence=false`.
- Required live-side posture from the guard: controlled dip/support-reclaim
  entries only, no green-spike chasing, buy/sell independence, fresh
  source-quality checks, and anti-crowding confirmation for bot-copycat or
  broker-friction names.
- Deterministic sleeve metrics remain weak:
  `directional_accuracy=0.3119`, `false_positive_rate=0.2286`,
  `average_action_relative_return=-1.2219`.
- TradingAgents advisory overlay metrics remain too noisy for live influence:
  `directional_accuracy=0.5000`, `false_positive_rate=0.5000`,
  `average_action_relative_return=-0.1140`.
- Newer June 7 overnight packets were explicitly skipped as `not_mature_yet`
  for the 3-day horizon, so the next after-close/overnight cycle should resolve
  them before changing influence.

Fresh proof:

- Submit-path focused regression:
  `uv run --no-sync --with pytest python -m pytest tests/test_order_rate_limit.py tests/test_live_gate.py tests/test_execution_safety.py tests/test_alpaca_execution.py tests/test_alpaca_cli.py -q`
  -> `168 passed`.
- Submit-path targeted Ruff passed.
- Ledger/context/n8n focused regression:
  `uv run --no-sync --with pytest python -m pytest tests/test_agent_intelligence_ledger.py tests/test_automation_context_snapshot.py::test_snapshot_flags_agent_summary_when_ledger_count_disagrees tests/test_automation_context_snapshot.py::test_snapshot_exposes_agent_outcome_labels_without_drilldown_flag tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_agent_ledger_summary_json tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_agent_ledger_update_json -q`
  -> `15 passed`.
- Overnight replay/calibration/n8n focused regression:
  `uv run --no-sync --with pytest python -m pytest tests/test_replay_ablation_plan.py tests/test_overnight_calibration_guard.py tests/test_n8n_runner_policy.py -q`
  -> `64 passed`.
- Targeted Ruff over replay/calibration/n8n files passed.
- `python -m tradingagents.orchestration.n8n_runner --list-jobs --json` reports
  24 allowlisted jobs and `submit_capable_count=0`.
- Process review
  `results\process_reviews\process-review-20260607-110647.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
- Compact context refreshed at `2026-06-07T11:06:43+00:00`; latest flags only
  open the intentional hourly notify, hourly BOARD review, execution BOARD
  review, and loss-review evidence review routes.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly compact sidecar reconciliation checkpoint:
Codex closed the remaining loss-review readability leak. The context summary
already translated the TSM loss-review blocker wall into plain English, but
`results/hourly_supervisor/latest-compact.json` could still be read directly by
dashboards or email paths and show stale missing-evidence text. The compact
context writer now reconciles the hourly sidecar reason when the latest
loss-review evidence explicitly targets the same raw hourly packet.

Current real hourly compact reason:
`TSM is in loss review. No live sell was submitted. Refreshed evidence resolved
12 of 13 checks. Remaining blocker: market session is not tradeable for a live
loss exit. BOARD-only candidate: thesis_invalidated at confidence 0.78; this is
not approval to sell.`

Fresh proof:

- Focused context/loss-review/BOARD tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_loss_review_evidence.py tests/test_execution_board.py -q`
  -> `88 passed`.
- Targeted Ruff:
  `uv run --no-sync --group static-analysis ruff check scripts/automation_context_snapshot.py tests/test_automation_context_snapshot.py`
  -> passed.
- Real compact context refresh wrote the clean reason into
  `results/hourly_supervisor/latest-compact.json` and left compact flags limited
  to the intentional hourly notify, hourly BOARD review, execution BOARD review,
  and loss-review evidence review routes.
- Real self-heal follow-up was tested, not assumed:
  `research self-heal-plan --execute-safe --json-output` wrote
  `results/self_heal/plans/self-heal-plan-20260607-110344.json`, and
  `research automation-health-audit --json-output --compact-json-output` wrote
  `results/automation_health/automation-health-audit-20260607-110418.json` with
  `ok_count=13`, `issue_count=0`, `duplicate_count=0`, and
  `self_heal_timeliness.timely=true` after a 33 second follow-up lag.
- Process review
  `results/process_reviews/process-review-20260607-110450.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 timely self-heal and overnight health de-noise checkpoint:
Codex followed the current compact-context flags after the automation-memory
rollup. The agent-ledger summary had been overwritten by a tiny fixture-like
summary, so `research agent-ledger-summary --json-output` regenerated the real
summary from `results\agent_intelligence\ledger.jsonl`: `forecast_count=4320`,
10 advisory agents, 0 resolved forecasts, and all influence weights still
`insufficient_history`. This cleared the compact `agent_intelligence_summary`
schema flag after context refresh.

Automation health also flagged `tradingagents-overnight-planning` as a duplicate
because three complete analysis-only overnight packets existed in one expected
window. This is useful visibility, but it should not wake self-heal when every
packet is analysis-only, has zero submitted orders, zero packet issues, the same
trade date, complete graph status, and no graph failures. The health audit now
de-noises that exact benign overnight rerun pattern while preserving packet
counts and paths.

Fresh proof:

- Real automation health:
  `results\automation_health\automation-health-audit-20260607-104415.json`
  reports `ok_count=13`, `duplicate_count=0`, `issue_count=0`,
  `submitted_order_count=0`, and overnight
  `status_reason=overnight_superseded_stale_repair_reruns_de_noised`.
- Real self-heal handoff:
  `results\self_heal\self-heal-handoff-20260607-104557.json` reports
  `should_start_new_chat=false`, `active_trigger_count=0`,
  `active_max_severity=none`, and only the deduped low hourly notify trigger.
- Compact context refresh removed the automation-health, self-heal, and
  agent-ledger schema flags. The remaining flags are only the intentional
  hourly notify/BOARD, execution BOARD, and loss-review evidence review routes.
- Focused tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_automation_health_audit.py -q`
  -> `33 passed`.
- Context self-heal/health tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py::test_snapshot_summarizes_automation_health_and_flags_timeliness tests/test_automation_context_snapshot.py::test_snapshot_keeps_low_severity_self_heal_escalation_quiet tests/test_automation_context_snapshot.py::test_snapshot_keeps_covered_order_adjacent_self_heal_escalations_quiet -q`
  -> `3 passed`.
- Targeted Ruff over `tradingagents/evals/automation_health_audit.py` and
  `tests/test_automation_health_audit.py` -> passed.
- Process review
  `results\process_reviews\process-review-20260607-104653.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 overnight automation-health de-noise and self-heal timing follow-up:
Codex fixed the automation-health false positive that kept flagging
`tradingagents-overnight-planning` as a duplicate after the overnight
latest-pointer repair. The audit already intended to de-noise complete
analysis-only overnight reruns, but the extractor was not carrying
`overnight_quality`, `analysis_only`, `trade_date`, or `submitted` from the
real overnight packet shape into the classifier. That made the de-noise rule
dead against real packets and its own test fixture.

The repaired behavior is conservative:

- Complete same-trade-date analysis-only reruns with no submissions, no packet
  issues, and 0 graph failures are visible but not health problems.
- A stale trade-date packet remains visible as evidence, but after a later
  complete analysis-only rerun for the newer trade date supersedes it, the
  health audit records
  `overnight_superseded_stale_repair_reruns_de_noised` instead of keeping a
  scheduler-overlap blocker alive.
- Any submitted order, packet issue, non-analysis-only packet, incomplete
  overnight run, or graph failure still prevents de-noising.

Fresh proof:

- Red regression first:
  `test_overnight_analysis_only_complete_reruns_are_visible_but_not_health_duplicates`
  failed before the extractor patch because the row stayed `duplicate`.
- Focused gate:
  `uv run --no-sync --with pytest python -m pytest tests/test_automation_health_audit.py tests/test_automation_context_snapshot.py tests/test_self_heal_handoff.py -q`
  -> `126 passed`.
- Targeted Ruff over the automation-health/context/self-heal files and tests
  passed.
- Real automation-health audit wrote
  `results\automation_health\automation-health-audit-20260607-104423.json` and
  compact latest now reports 13 OK, `duplicate_count=0`,
  `problem_automation_ids=[]`, `attention_automation_ids=[]`, and
  `submitted_order_count=0`.
- Real self-heal safe-plan wrote
  `results\self_heal\plans\self-heal-plan-20260607-104423.json`; it
  reverified automation health after the SLA, wrote night-shift patrol
  evidence, got verify exit code 0, and kept order-adjacent BOARD paths
  escalated.
- Fresh self-heal handoff wrote
  `results\self_heal\self-heal-handoff-20260607-104502.json` with
  `should_start_new_chat=false`, `active_trigger_count=0`, and
  `active_max_severity=none`.
- Final compact context has no automation-health flag and no self-heal handoff
  issue flag. Remaining flags are intentional order-adjacent review paths:
  hourly notify/BOARD, execution BOARD, and loss-review evidence.
- Process review
  `results\process_reviews\process-review-20260607-104544.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 Claude handoff and overnight latest-guard prep:
Codex re-read the Claude submit-path hardening handoff and verified the
current machine state before continuing market-readiness work. The key Claude
decisions are prepared and still active:

- SAFE-01 remains fail-closed. `config/risk_envelope.yaml` parses as
  `live_budget_mode=autonomous_with_caps`, account max `$250.00`, per-name
  `$50.00`, optional hard ceiling/rate-limit knobs unset, and `issues=[]`.
- `results/policy/live_control.json` is not frozen, but its dead-man remains
  expired at `2026-06-04T19:57:06+00:00`; live submission remains blocked
  unless the operator intentionally refreshes it.
- Commit `3970998` on `wip/submit-path-hardening-2026-06-05` still contains
  only `tradingagents/policy/order_rate_limit.py` and
  `tests/test_order_rate_limit.py`. The broader submit-path hardening edits
  remain shared dirty-tree work that should be staged only with hunk-level
  control if/when committing.

Overnight freshness is now guarded both by code and by real packet proof:

- `cli/main.py` refuses an explicit stale `--trade-date` when writing
  automation-facing overnight `latest.json`; historical probes must use
  `--no-write-latest`.
- Focused overnight CLI tests around stale explicit trade dates and historical
  `--no-write-latest` behavior passed as part of the current focused gate.
- Real overnight rerun wrote
  `results\overnight_plans\overnight-plan-20260607-101157-000000.json` with
  `trade_date=2026-06-08`, `analysis_only=true`, top symbol `XOM`, 3/3
  original graph successes, 0 graph failures, 37 fallback candidates, and
  `submitted=[]`.
- Premarket brief wrote
  `results\premarket_briefs\premarket-brief-20260607-101228-000000.json` with
  top symbol `XOM`, no stale warnings, and `execution_authority=none`.
- Overnight verifier wrote
  `results\overnight_system_verification\overnight-system-verification-20260607-051231.json`
  with `overall_status=pass`, expected/actual trade date `2026-06-08`, and
  no failed checks.

Self-heal and ledger cleanup were verified after the tests, not before them:

- `research self-heal-plan --execute-safe --json-output` ran the real
  safe-plane path, wrote a night-shift patrol packet, reran automation health,
  verified exit code 0, and kept order-adjacent BOARD items escalated instead
  of modifying trade authority.
- Automation health compact evidence reports self-heal follow-up within SLA
  (`timely=true`, follow-up lag about two minutes).
- `research agent-ledger-summary --json-output` was rerun after tests so
  `results\agent_intelligence\summary.json` matches the append-only ledger:
  4,320 forecasts in summary and 4,320 JSONL records.
- Final compact context has no overnight stale, preopen stale, source-quality
  schema, model-telemetry schema, or agent-intelligence schema flag. Remaining
  flags are intentional operational review paths: hourly notify/BOARD,
  automation-health attention, self-heal handoff record, execution BOARD, and
  loss-review evidence.

Fresh proof:

- Focused test gate:
  `uv run --no-sync --with pytest python -m pytest tests/test_order_rate_limit.py tests/test_live_gate.py tests/test_execution_safety.py tests/test_alpaca_execution.py tests/test_alpaca_cli.py tests/test_model_catalog.py tests/test_model_routing.py tests/test_self_heal_handoff.py tests/test_automation_context_snapshot.py -q`
  -> `292 passed`.
- Targeted Ruff over the touched Python and test files passed.
- Process review
  `results\process_reviews\process-review-20260607-103209.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 Claude submit-path prep plus automation-memory rollup:
Codex re-read `reports/handoff/CODEX_SUBMIT_PATH_HARDENING_HANDOFF_2026-06-05.md`
and the Claude deep-review recap before continuing. SAFE-01 remains fail-closed:
`config/risk_envelope.yaml` parses through the repo loader as
`live_budget_mode=autonomous_with_caps`, account max `$250.00`, per-name
`$50.00`, optional hard ceiling/rate-limit knobs unset, and `issues=[]`.
Commit `3970998` still contains only the standalone rate-limit module and test;
the broader submit-path hardening edits remain dirty shared work and must be
staged only with hunk-level review.

The token-efficiency workstream applied the safe automation-memory rollup using
the repo CLI's hash-protected apply path. The original full memories were
archived before replacement, and the live memories now contain a digest plus
retained tail:

- `hourly-market-supervisor`: `47,319 -> 3,356` approximate tokens; archive at
  `results\token_efficiency\automation_memory_archives\hourly-market-supervisor\memory-archive-20260607.md`.
- `paper-strategy-tournament-runner`: `24,339 -> 3,726` approximate tokens;
  archive at
  `results\token_efficiency\automation_memory_archives\paper-strategy-tournament-runner\memory-archive-20260607.md`.
- Post-apply dry run:
  `results\token_efficiency\automation-memory-rollup-20260607-101454.json`
  reports `rollup_candidate_count=0`, total automation-memory footprint about
  `33,324` tokens, and `candidate_approx_tokens=0`.

Fresh proof:

- Apply packet:
  `results\token_efficiency\automation-memory-rollup-apply-20260607-101407.json`
  with `compacted_count=2`, `skipped_count=0`, `can_submit_orders=false`, and
  `execution_authority=none`.
- `scripts\automation_context_snapshot.py --write` refreshed compact context
  after the rollup.
- `uv run --no-sync --with pytest python -m pytest tests/test_automation_memory_rollup.py tests/test_automation_context_snapshot.py::test_write_context_files_exposes_automation_memory_rollup_summary -q`
  -> `8 passed`.
- `uv run --no-sync --group static-analysis ruff check tradingagents/evals/automation_memory_rollup.py tests/test_automation_memory_rollup.py scripts/automation_context_snapshot.py tests/test_automation_context_snapshot.py`
  -> passed.
- `research process-review --json-output` wrote
  `results\process_reviews\process-review-20260607-101535.json` with
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
- Fresh submit-path handoff regression initially caught a stale test fixture:
  `test_verify_overnight_system_warns_when_original_graph_requested_but_disabled`
  expected a graph-disabled warning but omitted the now-required overnight
  `trade_date`. The verifier was correct: only
  `overnight_packet_trade_date` failed while `overnight_original_graph_execution`
  was `warn`. The fixture now includes `trade_date=2026-06-01`.
- Focused proof:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py::test_verify_overnight_system_warns_when_original_graph_requested_but_disabled -q`
  -> `1 passed`; `ruff check tests/test_alpaca_cli.py` -> passed.
- Full submit-path slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_order_rate_limit.py tests/test_live_gate.py tests/test_execution_safety.py tests/test_alpaca_execution.py tests/test_alpaca_cli.py -q`
  -> `168 passed`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 self-heal overlap health de-noise checkpoint:
Automation-health now treats a timely self-heal follow-up as healthy even when
multiple self-heal artifacts exist in the same schedule bucket. The raw row
preserves `overlap_count` for forensics, but `issue_types` no longer includes
`overlap_run` when `self_heal_timeliness.timely=true`. This keeps the monitor
truthful without waking the operator over a successful hook/monitor handoff.

Fresh proof:

- Real automation-health packet:
  `results\automation_health\automation-health-audit-20260607-092414.json`.
- `tradingagents-self-heal-monitor` row: `status=ok`, `issue_types=[]`,
  `overlap_count=1`, `status_reason=self_heal_timely_overlap_artifacts_de_noised`,
  `self_heal_timeliness.followup_lag_seconds=26`, and `timely=true`.
- Compact context has `ok_count=13`, no problem or attention automation IDs,
  and the same timely self-heal lag.
- Focused test:
  `uv run --no-sync --with pytest python -m pytest tests/test_automation_health_audit.py -q`
  -> `31 passed`.
- Targeted Ruff:
  `uv run --no-sync --group static-analysis ruff check tradingagents\evals\automation_health_audit.py tests\test_automation_health_audit.py`
  -> passed.
- Process review:
  `results\process_reviews\process-review-20260607-092443.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 Claude submit-path prep checkpoint:
Codex re-read the Claude deep-review response and the submit-path handoff, then
verified the active machine state before continuing the broader improvement
program. Treat Claude's response as a prepared safety/commit handoff, not as a
claim that the whole repo goal is complete.

Current prepared constraints:

- SAFE-01 remains fail-closed. `config/risk_envelope.yaml` parses as
  `live_budget_mode=autonomous_with_caps`, account max `$250.00`, per-name
  `$50.00`, optional hard-ceiling/rate-limit knobs unset, and `issues=[]`.
- `results/policy/live_control.json` still has the expired dead-man at
  `2026-06-04T19:57:06+00:00`; do not refresh it without explicit operator
  approval.
- Commit `3970998` still contains only the standalone
  `tradingagents/policy/order_rate_limit.py` and
  `tests/test_order_rate_limit.py` files. The broader submit-path hardening
  edits remain shared dirty-tree work and must be staged only with hunk-level
  review.
- `CONTEXT_ROUTER.md` now labels the older 2026-06-05/06 packet table as
  historical/superseded, so future agents should use `Current nearest checks`
  first.

Fresh proof:

- `git show --stat --oneline 3970998` -> exactly two files in the standalone
  rate-limit commit.
- Envelope loader sanity -> `{'mode': 'autonomous_with_caps',
  'account_max': '250.00', 'per_name': '50.00', 'hard_ceiling': None,
  'max_orders': None, 'window_minutes': None, 'issues': []}`.
- `scripts/automation_context_snapshot.py --write` refreshed compact context.
- `research process-review --json-output` wrote
  `results\process_reviews\process-review-20260607-091259.json` with
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
- `results\_context\latest-flags.json` now opens only the intended
  hourly/BOARD/loss-review review routes.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 Mac helper host-unreachable telemetry checkpoint:
Codex re-read the Claude submit-path handoff and verified the current operating
constraint before touching model routing: SAFE-01 remains fail-closed
(`autonomous_with_caps`, `$250.00` account cap, `$50.00` per-name cap,
`issues=[]`), the dead-man is still expired at
`2026-06-04T19:57:06+00:00`, and commit `3970998` still contains only the
standalone order-rate-limit module plus test. No live authority was changed.

The model helper route now distinguishes a Mac host/Tailnet timeout from a
generic missing-model or missing-endpoint problem. `model_telemetry` classifies
`Mac Ollama health probe failed: <urlopen error timed out>` as
`error_kind=mac_host_unreachable`, writes plain English that the Mac DeepSeek
lane is skipped while Windows local/deterministic/Codex fallback stays active,
and exposes self-heal actions:
`verify_mac_tailscale_or_host_is_online`,
`verify_mac_ssh_macbook_codex`,
`restart_or_expose_mac_ollama_after_host_reachable`,
`verify_mac_ollama_tags_endpoint`, and
`use_windows_or_deterministic_fallback_until_ready`.

Compact context now preserves capped `blocked_route_summaries` from the model
telemetry compact sidecar, so n8n/self-heal/Codex readers can see the Mac
recovery checklist without opening the full raw report. A real route probe wrote
`results\research_batches\model_route_health\research-batch-research-batch-dfd3019cbd994b43b145db01de7c3c0e.json`:
Windows local Ollama was reachable and selected, the Mac helper used the correct
`deepseek-r1:14b` model but timed out at the host/tags path, and fallback was
not required. The telemetry rollup wrote
`results\model_telemetry_reports\model-telemetry-report-20260607-090501-858574.json`
with `blocked_route_summaries[0].error_kind=mac_host_unreachable`,
`hard_model_issue=false`, `local_helper_repair_signal=false`, and spend `$0.0000`.
`results\_context\latest-summary.json` now carries the same blocked-route
summary, while `latest-flags.json` remains limited to the intentional
hourly/BOARD/loss-review review flags.

Verification passed: model-routing/context tests `97 passed`, targeted Ruff
passed, compact context was refreshed, and process review
`results\process_reviews\process-review-20260607-091004.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 model-helper/overnight readiness refresh:
Codex re-probed the current helper routes and overnight verifier. The overnight
pipeline itself is healthy: `alpaca verify-overnight-system --json-output` wrote
`results\overnight_system_verification\overnight-system-verification-20260607-040319.json`
with `overall_status=pass`, latest overnight age `1.24h`, 3/3 full original
graph successes, 40 ranked candidates, top `CVX`, fresh premarket checklist,
and the active `tradingagents-overnight-planning` automation `ACTIVE`.

Model-helper state is safe but asymmetric:

- Windows local Ollama is reachable at `http://127.0.0.1:11434/api/tags` and
  has `tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest`.
- Mac helper is currently host-unreachable from Windows: direct Ollama tags
  request to `http://macbook-pro.tail37edd7.ts.net:11434/api/tags` timed out,
  and `ssh macbook-codex` also timed out on port 22.
- The fresh route probe
  `results\research_batches\model_route_health\research-batch-research-batch-d3eaf44d8cae40ea984671bb77e760e6.json`
  selected deterministic helpers plus Windows local Ollama, marked Mac
  `deepseek-r1:14b` as optional/degraded, kept
  `research_quality_high_enough=true`, and required no fallback beyond skipping
  the Mac lane.
- Fresh model telemetry
  `results\model_telemetry_reports\model-telemetry-report-20260607-090430-196143.json`
  records current route statuses at `2026-06-07T09:03:57+00:00`: deterministic
  success, Windows local success, Mac blocked, Codex/ChatGPT fallback. Current
  estimated spend remains `$0.0000`, and model telemetry remains analysis-only.

Operational interpretation: do not wait on the Mac for morning readiness. The
best overnight research path currently uses the Google original graph,
deterministic helpers, Windows local Ollama for cheap summaries, and Codex for
judgment; the Mac lane can rejoin automatically once the Tailscale/host/Ollama
endpoint responds.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 Agent Intelligence safe-heal checkpoint:
Compact context flagged `agent_intelligence_summary` for `schema` because
`results/agent_intelligence/summary.json` was stale relative to
`results/agent_intelligence/ledger.jsonl` after new forecasts were appended.
Codex ran the existing read-only `research agent-ledger-summary --json-output`,
which regenerated the summary at 3,867 forecasts, 10 advisory influence-weight
agents, and 0 resolved forecasts. A context refresh cleared the schema flag.

Codex also patched the safe-plane self-heal path so this does not require manual
repair next time. A schema flag on `agent_intelligence_summary` now runs the
allowlisted sequence:

1. `research agent-ledger-summary --json-output`
2. `scripts/automation_context_snapshot.py --write`

The action is analysis-only and cannot submit orders, send email, change
automation status, refresh live control, or read secrets. Order-adjacent BOARD
signals still escalate instead of executing.

Fresh proof:

- Focused tests:
  `tests/test_self_heal_handoff.py::test_self_heal_plan_repairs_stale_agent_intelligence_summary_schema`,
  `tests/test_self_heal_handoff.py::test_execute_self_heal_plan_runs_agent_summary_before_context_refresh`,
  and
  `tests/test_automation_context_snapshot.py::test_snapshot_flags_agent_summary_when_ledger_count_disagrees`
  -> 3 passed.
- Targeted Ruff over `tradingagents/orchestration/self_heal.py` and
  `tests/test_self_heal_handoff.py` passed.
- Real `research self-heal-plan --execute-safe --json-output` wrote
  `results\self_heal\plans\self-heal-plan-20260607-085848.json`; after the
  manual ledger-summary refresh there was no remaining safe schema action, and
  the plan skipped the two order-adjacent BOARD escalations.
- Compact context refresh removed the `agent_intelligence_summary` schema flag.
- Process review
  `results\process_reviews\process-review-20260607-085917.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 Claude submit-path/n8n readiness sweep:
Codex ran the Claude-requested guard surface after the provider readiness check.
The submit path remains fail-closed and tested, while n8n remains an observer
wrapper with no submit-capable jobs.

Fresh proof:

- Submit-path focused regression:
  `uv run --no-sync --with pytest python -m pytest tests/test_order_rate_limit.py tests/test_live_gate.py tests/test_execution_safety.py tests/test_alpaca_execution.py tests/test_alpaca_cli.py -q`
  -> 165 passed.
- n8n allowlist discovery:
  `python -m tradingagents.orchestration.n8n_runner --list-jobs --json`
  -> 24 jobs, `submit_capable_count=0`, compact outputs only.
- Automation health:
  `results\automation_health\automation-health-audit-20260607-084830.json`
  -> 13/13 automations OK, no issues, no stale/late/duplicate/missing jobs,
  no submitted orders, and self-heal follow-up timely at 45 seconds.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 Claude-review provider gap readiness checkpoint:
Codex re-read the Claude submit-path handoff and verified the active operating
constraint before touching the research lane: SAFE-01 remains fail-closed
(`autonomous_with_caps`, `$250.00` account cap, `$50.00` per-name cap,
`issues=[]`), and the live-control dead-man is still expired at
`2026-06-04T19:57:06+00:00`. The rate-limit commit `3970998` still contains
only the standalone module/test pair; broader submit-path hardening remains
shared dirty-tree work requiring hunk-level staging.

The remaining P1 source gap was checked against live current research names
instead of only fixture tests. `research ticker-provider-bundle` ran for
overnight top `CVX` and preopen rank `MSFT` with evidence needs
`earnings_transcripts,short_interest,options_iv_flow`. Both runs were
analysis-only and wrote explicit evidence/gap packets:

- `CVX` summary:
  `results\research_evidence\source-evidence-source-evidence-f64c4d5e9bde40128a57c589af76d4b0.json`.
  Short-interest and options evidence came from low-authority public
  yfinance/official-cache routes; transcript absence was captured as a blocked
  `earnings_transcripts_gap`.
- `MSFT` summary:
  `results\research_evidence\source-evidence-source-evidence-83b72d4f141e4f79b029a834ade79d18.json`.
  yfinance supplied supplemental short-interest and options packets, and the
  route also wrote blocked gap packets to preserve the conservative conclusion:
  weak public supplemental evidence is useful for downranking/confirmation, not
  a substitute for authoritative transcript/options/short-interest vendors.
- Fresh source-quality review after those bundles wrote
  `results\source_quality\source-quality-review-20260607-084521.json` with
  250 sources reviewed, 241 fresh, 9 stale, 6 stale-downranked,
  32 blocked, 0 missing/invalid, and `stale_needs_refresh_count=0`.
- Focused provider/source tests passed:
  `tests/test_research_provider_orchestrator.py tests/test_source_quality.py`
  -> 37 passed; targeted Ruff passed; compact context refreshed; process review
  `results\process_reviews\process-review-20260607-084555.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 loss-review reason clarity checkpoint:
Codex fixed the compact context translator so refreshed loss-review evidence
also updates the hourly `reason` field future emails/agents read. Before this
checkpoint, the machine fields correctly said TSM had 12 of 13 checks resolved,
but `results\_context\latest-summary.json` still carried the original long
blocker list in `hourly.reason`. That made emails and summaries look like all
13 blockers were still open.

When latest loss-review evidence explicitly targets the same raw hourly packet,
`scripts/automation_context_snapshot.py` now rewrites the hourly reason into a
short plain-English summary. Current real output:
`TSM is in loss review. No live sell was submitted. Refreshed evidence resolved
12 of 13 checks. Remaining blocker: market session is not tradeable for a live
loss exit. BOARD-only candidate: thesis_invalidated at confidence 0.78; this is
not approval to sell.`

Proof: the new regression test first failed against the stale blocker-list
behavior, then passed after the translator patch. Focused verification:
`tests/test_automation_context_snapshot.py tests/test_loss_review_evidence.py
tests/test_execution_board.py` -> `85 passed`; targeted Ruff passed; real
context refresh wrote `results\_context\latest-summary.json` with the shorter
reason; process review
`results\process_reviews\process-review-20260607-084432.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 P2 overnight calibration refresh checkpoint:
Codex refreshed the real mature overnight walk-forward cohort and regenerated
the overnight calibration guard from the current data. The newest June 7
overnight packets were correctly skipped as `not_mature_yet` with resolution
date `2026-06-08`, so the calibration layer did not pretend weekend packets
had resolved.

Fresh proof:

- `research walk-forward-refresh-overnight-cohort --json-output` wrote
  `results\research_batches\walk_forward_cohort_refresh_20260607-083610_h3.json`
  with `selected_packet_count=12`, `skipped_packet_count=5`,
  `returns_row_count=175`, `fixture_row_count=420`, and
  `sample_floor_met=true`.
- The replay packet
  `results\research_batches\research-batch-research-batch-7f751ce2a64a43aeb82ff1097b69b158.json`
  scored 420 deterministic rows and 20 TradingAgents advisory-overlay rows.
- `research overnight-calibration-guard --json-output` wrote
  `results\overnight_calibration\overnight-calibration-guard-20260607-083704.json`
  with `guard_decision=tighten`, `can_increase_live_influence=false`,
  deterministic action-relative return `-1.2219`, TradingAgents
  action-relative return `-0.1140`, and TradingAgents false-positive rate
  `0.5000`.
- The live influence policy remains: controlled dip/support/reclaim entries
  only, no green-spike chasing, sell/buy independence, no same-run replacement
  buy forcing, and anti-crowding confirmation required.
- Compact context was refreshed, and process review
  `results\process_reviews\process-review-20260607-083743.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 P2 overnight calibration de-duplication checkpoint:
Codex found and fixed the evidence-quality issue in the prior checkpoint above:
`fixture_row_count=420` was inflated because multiple mature overnight packets
could repeat the same `symbol/as_of` decision, while the later return rows were
already unique. `build_walk_forward_fixture_from_overnight_packets(...)` now
keeps the first row for each `symbol/as_of` and records later copies as
`duplicate_symbol_as_of` skips with `duplicate_skipped_count`, so calibration
does not overweight duplicate decisions.

Fresh proof:

- Red/green regression:
  `test_walk_forward_fixture_generator_dedupes_duplicate_symbol_as_of_rows`
  failed before the patch and passed after it.
- `research walk-forward-refresh-overnight-cohort --json-output` wrote
  `results\research_batches\walk_forward_cohort_refresh_20260607-115316_h3.json`
  with `selected_packet_count=12`, `returns_row_count=175`,
  `fixture_row_count=175`, and `fixture_skipped_count=245`.
- `research overnight-calibration-guard --json-output` wrote
  `results\overnight_calibration\overnight-calibration-guard-20260607-115425.json`
  with `guard_decision=tighten`, `can_increase_live_influence=false`,
  deterministic action-relative return `-1.9117`, TradingAgents
  action-relative return `-1.3117`, and TradingAgents false-positive rate
  `0.5833`.
- Verification: replay-ablation test file `16 passed`; focused
  walk-forward/calibration/schema tests `14 passed`; targeted Ruff passed;
  compact context refreshed with only expected hourly/BOARD/loss-review review
  flags; process review
  `results\process_reviews\process-review-20260607-115525.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 compact next-open de-duplication checkpoint:
Compact flags can legitimately carry multiple reasons for one packet, for
example hourly `notify` plus `board_review`. The generated `next_open` worklist
now de-duplicates paths while preserving every flag reason, so future agents and
automations do not waste context opening the same compact packet twice.

Fresh proof:

- Added a regression where one hourly loss-review packet has both `notify=true`
  and `board_review`; `flags` keeps both reasons while `next_open` contains one
  path.
- Focused tests:
  `tests/test_automation_context_snapshot.py::test_snapshot_deduplicates_next_open_paths_when_packet_has_multiple_reasons`
  and
  `tests/test_automation_context_snapshot.py::test_snapshot_flags_hourly_loss_review_for_board_drilldown`
  -> `2 passed`.
- Targeted Ruff over `scripts/automation_context_snapshot.py` and
  `tests/test_automation_context_snapshot.py` -> passed.
- Real context refresh wrote `results\_context\latest-flags.json` with four
  flags but only three `next_open` paths:
  `results\hourly_supervisor\latest-compact.json`,
  `results\execution_board\latest-compact.json`, and
  `results\loss_review_evidence\latest-compact.json`.
- Process review
  `results\process_reviews\process-review-20260607-083215.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 loss-exit candidate BOARD checkpoint:
Codex re-read the Claude submit-path handoff and verified the fail-closed
operating posture again before extending the current TSM loss-review path:
`config/risk_envelope.yaml` still parses as `autonomous_with_caps`, `$250.00`
account cap, `$50.00` per-name cap, and `issues=[]`; the live-control dead-man
remains lapsed at `2026-06-04T19:57:06+00:00`; commit `3970998` still contains
only the standalone live-order rate-limit module and test.

The loss-review evidence bridge now resolves the remaining semantic evidence
gaps when refreshed evidence supports a BOARD-only loss-exit candidate. For the
current TSM packet, `research loss-review-evidence --json-output` wrote
`results\loss_review_evidence\source-evidence-source-evidence-a2b1faa05e0a4ee5bb6b50e99c175f8d.json`
against hourly packet
`results\hourly_supervisor\hourly-supervisor-20260607-082307-913209.json`.
The compact packet stores actionable fields under `payload.advisory_summary`.
It now includes a `loss_exit_candidate` with
`allowed_exit_reason_candidate=thesis_invalidated`,
`allowed_exit_reason_source=refreshed_loss_review_evidence`,
`confidence=0.78`, `confidence_tier=medium`, and
`approval_effect=board_review_input_not_loss_exit_approval`.

Safety invariant: this is still not permission to sell. The packet remains
`review_allowed=false`, `execution_authority=none`, `can_submit_orders=false`,
and the only remaining blocker is
`market session is not tradeable for a live loss exit`.
`research execution-board-review --json-output` then wrote
`results\execution_board\execution-board-review-20260607-082625.json`, matched
the same hourly/evidence window, found zero hard violations, and warned that
live exit remains blocked until a tradeable session and the normal live gates
pass. Compact context now has only intentional hourly/BOARD/loss-review review
signals, not stale preopen or stale BOARD flags.

2026-06-07 automation memory rollup plan:
Codex added an analysis-only automation memory rollup planner so token-heavy
automation memories are no longer only a process-review warning. New command:
`research automation-memory-rollup --json-output`. It discovers
`C:\cm\automations\*/memory.md`, scores rollup candidates, and writes JSON/MD
evidence under `results\token_efficiency` without editing automation files.

Fresh real proof wrote
`results\token_efficiency\automation-memory-rollup-20260607-071207.json` and
`results\token_efficiency\latest-automation-memory-rollup.json`. It inspected
12 memories, found 2 rollup candidates (`hourly-market-supervisor` and
`paper-strategy-tournament-runner`), and identified about 71,658 candidate
tokens for future approved archive+tail compaction. The packet is
`analysis_only=true`, `can_submit_orders=false`, `execution_authority=none`,
`mutation_mode=dry_run_only`, and explicitly forbids hooks/n8n from mutating
automation memory without operator approval.

Compact context now exposes the latest rollup under
`results/_context/context-manifest.json` as `automation_memory_rollup`, so
future automations can find the packet without opening raw memories. Focused
proof passed: automation memory rollup/context tests `69 passed`, new rollup
unit tests `3 passed`, targeted Ruff passed, and process review
`results\process_reviews\process-review-20260607-071504.json` reports
`unchecked_step_count=0` and no findings.

2026-06-07 automation memory rollup apply-gate checkpoint:
The rollup planner now has an explicit archive+digest+tail apply path, but it
is locked behind both `--apply` and `--confirm-apply`. Without both flags the
command stays dry-run only. When applied, it verifies the source hash, archives
the full original memory, then replaces only rollup-candidate live memories
with a digest and retained tail. The apply result packet remains
`analysis_only=true`, `can_submit_orders=false`, and `execution_authority=none`;
it cannot trade, refresh dead-man, change live authority, edit credentials, or
change automation status.

Codex did not apply compaction to real `C:\cm\automations` memories in this
checkpoint. A fresh dry-run wrote
`results\token_efficiency\automation-memory-rollup-20260607-072153.json`, still
showing 12 memories, 2 rollup candidates, and about 71,658 candidate tokens.
Compact context points to that latest packet, and process review
`results\process_reviews\process-review-20260607-072224.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
Verification passed: rollup unit tests `7 passed`, rollup/context tests
`73 passed`, and targeted Ruff passed.

2026-06-07 model catalog context-window checkpoint:
The shared model catalog now exposes machine-readable model metadata instead of
requiring callers to parse dropdown labels. New APIs:
`get_model_metadata(...)` and `get_model_context_window_tokens(...)`.
Known context windows are recorded for the repo's explicitly listed OpenAI
1M-context models, Gemini 2.5 models, GLM 204K models, and MiniMax M2 204.8K
models. Unknown/custom/local-build-dependent models intentionally return
`None` rather than guessed capacity.

Model routes now carry `context_window_tokens` in `ModelRoute.model_dump()`.
Overnight graph config now carries `quick_context_window_tokens`,
`deep_context_window_tokens`, and `helper_context_window_tokens`, so overnight
packets and verifiers can see routing capacity without label parsing. Direct
sanity proof showed Gemini 2.5 Flash Lite / Flash graph config with
`1048576` tokens for quick/deep, and a capped Gemini judgment route with
`context_window_tokens=1048576`.

Verification passed: model catalog/routing/overnight graph-config slice
`33 passed`, the narrower catalog/routing/Ollama-label slice `31 passed`, and
targeted Ruff passed.

2026-06-07 loss-review thesis-status checkpoint:
The TSM loss-review evidence bridge now classifies an obvious current-thesis
state instead of leaving that field generically unresolved. When the refreshed
candidate evidence says `falling-knife` or `sharp drop`, the prior entry thesis
was momentum/time-sensitive, and the position is below average entry, the packet
sets `current_thesis_status_candidate` to
`thesis_under_pressure_falling_knife_watch` and records the three drivers in
`thesis_status_evidence`. This resolves only the "current thesis status is
missing" evidence gap; it does **not** approve a live loss exit.

Real proof: `research loss-review-evidence --json-output` wrote
`results\loss_review_evidence\source-evidence-source-evidence-f1d9dc5e8a8045ddb2120b4396d5dc35.json`
with `review_allowed=false`, `execution_authority=none`, 9 blockers resolved,
and 4 remaining blockers: allowed loss-exit reason, reason source, confidence,
and market session. `research execution-board-review --json-output` wrote
`results\execution_board\execution-board-review-20260607-073717.json`, matched
that compact evidence, and kept BOARD pending with no submitted orders.
Verification passed: loss-review/execution-board/context tests `81 passed`,
targeted Ruff passed, and process review
`results\process_reviews\process-review-20260607-073804.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 pre-open submit gate checkpoint:
Prompt-level automation ordering was not enough for a submit-capable path, so
`alpaca supervise-hourly` now has a default-on code gate for pre-open live
submission. New option: `--preopen-validation-dir` (default
`results/preopen_validation`). During `market_session=pre_open`, a
`--submit-actions` run must find a fresh latest pre-open validation packet with
`overall_status=pass`, `market_session=pre_open`, and no failed/warned/skipped
checks before it can proceed to live-submit validation or tiny-live guard work.
Missing, stale, warning, skipped, failed, or wrong-session validation produces a
`preopen-validation` `OrderIssue`, blocks the run, and records the summary in
hourly evidence. Dry runs stay analysis-only and are not converted into submits.

Verification passed:
- New TDD tests proved missing validation blocks before the tiny-live guard and
  clean validation permits the pre-open submit path to continue.
- Focused pre-open/hourly submit tests: `12 passed`.
- n8n/preopen/overnight policy slice: `5 passed`.
- Targeted Ruff over `cli\main.py` and `tests\test_alpaca_cli.py`: passed.
- Real dry-run probe wrote
  `results\hourly_supervisor\preopen_gate_probe\hourly-supervisor-20260607-075610-009451.json`
  with `submitted_count=0`.
- Process review
  `results\process_reviews\process-review-20260607-075731.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 model telemetry context-window checkpoint:
Codex propagated the model catalog metadata into model telemetry packets,
rollups, and compact reports. `ModelRunTelemetryPacket` now records
`context_window_tokens`, `model_route_telemetry_packet(...)` copies it from the
selected route, and compact `current_route_statuses` keeps a stable
`context_window_tokens` key even when a local/custom route has unknown capacity.
This gives n8n/dashboard/context consumers a predictable schema and removes
another reason to parse model labels.

Fresh proof passed:

- `uv run --no-sync --with pytest python -m pytest tests/test_model_catalog.py tests/test_model_routing.py -q`
  -> `29 passed`.
- Targeted Ruff over the changed telemetry/schema/model tests -> passed.
- Real analysis-only orchestration probe wrote
  `results\research_batches\model_catalog_context_probe\research-batch-research-batch-29a3904622ac46279b1334ad61fc502d.json`.
- Real model telemetry report wrote
  `results\model_telemetry_reports\model-telemetry-report-20260607-074452-543468.json`;
  `results\model_telemetry_reports\latest-compact.json` now shows
  stable `context_window_tokens` keys for every current route status. Known
  catalog/helper routes carry a numeric value; deterministic helpers and
  unknown/custom external lanes may stay `null`. Windows local Ollama is
  currently selected/successful, Mac DeepSeek is degraded by a tags-endpoint
  timeout, Codex/ChatGPT remains the external judgment fallback, and no route
  can trade.

2026-06-07 local-helper context-window inference follow-up:
The previous telemetry checkpoint preserved the schema but still left the two
known local helper lanes with `context_window_tokens=null` when the latest
telemetry packet was created before route metadata existed. That weakened the
actual automation-facing model summary even though route selection knew the
models.

The model catalog now includes conservative operational context windows for the
repo-local Ollama helper aliases:

- `tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k[:latest]` -> `4096`,
  matching `scripts\ollama\tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k.Modelfile`.
- `deepseek-r1:14b` -> `4096`, used as the conservative Mac 32 GB helper lane
  budget unless a route packet supplies a stronger value.

`summarize_model_telemetry(...)` now enriches current-route status rows from
the catalog when historical packets have a missing context window. It does not
mutate raw telemetry packets and does not guess capacity for `custom`,
deterministic, or unknown external lanes.

Fresh proof:

- `uv run --no-sync --with pytest python -m pytest tests/test_model_catalog.py tests/test_model_routing.py -q`
  -> `31 passed`.
- Targeted Ruff over `tradingagents\llm_clients\model_catalog.py`,
  `tradingagents\research\model_telemetry.py`, and the focused tests -> passed.
- Real analysis-only telemetry report:
  `results\model_telemetry_reports\model-telemetry-report-20260607-093720-965799.json`.
- `results\model_telemetry_reports\latest-compact.json` and
  `results\_context\latest-summary.json` now show
  `mac_ollama_research_mule/deepseek-r1:14b/context_window_tokens=4096` and
  `windows_local_ollama/tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest/context_window_tokens=4096`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 Claude submit-path review prep:
Codex re-read `reports/handoff/CODEX_SUBMIT_PATH_HARDENING_HANDOFF_2026-06-05.md`
and the Claude deep-review recap. SAFE-01 remains fail-closed:
`config/risk_envelope.yaml` parses as `autonomous_with_caps`, `$250.00`
account cap, `$50.00` per-name cap, and `issues=[]`; the dead-man remains
lapsed at `2026-06-04T19:57:06+00:00`. Commit `3970998` still contains only
the standalone rate-limit module and test. The rest of submit-path hardening
remains dirty shared worktree state and must be staged only with hunk-level
review. Safety boundary held: no orders, emails, dead-man refresh, credential
changes, automation status changes, staging/commit, or live-authority changes.

2026-06-07 overnight next-market-date checkpoint:
Codex fixed the overnight default trade-date helper so weekend overnight runs
target the next weekday instead of the previous Friday. This matters because
the active overnight automation explicitly runs on weekend nights when the next
market open needs a fresh premarket-readable report. Weekday runs still use the
local Central date.

Fresh proof:

- Direct helper sanity for Sunday `2026-06-07` returned `2026-06-08`.
- Real analysis-only probe:
  `alpaca plan-overnight --json-output --compact-json-output --log-dir results/overnight_plans/date_probe --full-graph-tickers 0 --no-research-context --no-write-latest --no-agent-ledger`
  wrote `results\overnight_plans\date_probe\overnight-plan-20260607-080010-000000.json`
  with `trade_date=2026-06-08`, 40 fallback-ranked candidates,
  `submitted_count=0`, and no update to automation-facing latest pointers.
- Real overnight system verification wrote
  `results\overnight_system_verification\overnight-system-verification-20260607-025548.json`
  with `overall_status=pass`, latest packet age `0.11h`, 3/3 full graph
  successes, top candidate `CVX`, and graph config matching the active Gemini
  automation contract including `quick_context_window_tokens=1048576` and
  `deep_context_window_tokens=1048576`.
- Creator workflow status reports 3 workflows (`XOM`, `ADBE`, `CVX`), each
  with 9 roles and `execution_authority=none`.
- Automation health reports 13/13 OK and timely self-heal follow-up.
- Focused overnight CLI tests `4 passed`, connector/ledger context tests
  `2 passed`, and targeted Ruff passed.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 preopen validation freshness checkpoint:
Compact context now detects when `results/preopen_validation/latest-compact.json`
is older than the latest overnight or premarket brief packet. Closed-market
preopen validation warnings remain quiet only when the validation packet is
current relative to the latest context. If overnight or premarket refreshes
after preopen validation, `latest-flags.json` now raises a `preopen_validation`
`stale` drilldown so the morning controller knows to rerun fresh validation
before any pre-open submit-capable path.

Fresh proof:

- Real context refresh now shows `preopen_validation` with
  `stale_after_latest_context=true`,
  `latest_overnight_generated_at=2026-06-07T07:48:58+00:00`, and
  `latest_premarket_generated_at=2026-06-07T07:53:22+00:00`; the stale flag is
  expected because the latest preopen validation was generated at
  `2026-06-07T03:58:09+00:00`.
- Focused preopen/context tests `3 passed`.
- Targeted Ruff passed.
- Process review
  `results\process_reviews\process-review-20260607-081243.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

This is context-only. It creates no trade intent, submits no orders, and does
not change live authority.

2026-06-07 preopen/BOARD freshness repair checkpoint:
Codex ran the real analysis-only preopen validation after the latest overnight
and premarket packets, then refreshed execution BOARD review against the newest
hourly loss-review packet. This cleared the stale preopen and stale BOARD
drilldowns from compact context. The remaining flags are intentional review
signals, not freshness failures: hourly notify/BOARD review, execution BOARD
review, and loss-review evidence for `TSM`.

Fresh proof:

- `alpaca preopen-validation --json-output` wrote
  `results\preopen_validation\preopen-validation-20260607-082431.json` with
  `analysis_only=true`, `can_submit_orders=false`, `submitted_count=0`,
  `top_symbol=CVX`, `stale_after_latest_context=false`, and only the expected
  closed-market quote skip plus expired-dead-man warning.
- `research execution-board-review --json-output` wrote
  `results\execution_board\execution-board-review-20260607-082625.json` with
  `board_matches_latest_hourly=true`, `violation_count=0`,
  `submitted_order_count=0`, and explicit next-hour policy: sells are
  independent from buys, loss exits do not force replacement buys, and new buys
  require separate controlled dip/support setups with no green-spike chasing.
- Compact context refresh now has no `preopen_validation` stale flag and no
  execution BOARD stale flag.
- Automation health
  `results\automation_health\automation-health-audit-20260607-082521.json`
  reports 13/13 automations OK, no issues, no submitted orders, and timely
  self-heal follow-up.
- Process review
  `results\process_reviews\process-review-20260607-082704.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 n8n duplicate-evidence evaluation checkpoint:

The n8n evaluation dataset now covers the overnight calibration dedupe repair
directly. Every allowlisted n8n job receives the
`duplicate_evidence_deduped_before_scoring` scenario, tagged with
`duplicate_evidence`, `source_quality`, and `no_live_submit`. This protects the
calibration guard from a fake-quality failure mode where repeated symbol/as-of
evidence rows make an overnight signal look better tested than it is.

Fresh proof:

- Real dataset packet:
  `results\n8n_evaluations\n8n-evaluation-dataset-20260607-120614-394063.json`
  with `row_count=243`, `allowlisted_job_count=24`,
  `edge_tag_count=18`, and `duplicate_evidence` present.
- Local n8n Data Table sync packet:
  `results\n8n_evaluations\n8n-api-sync-20260607-120733-909721.json` with
  `table=TradingAgents_Automation_Evaluations`,
  `inserted_count=24`, `final_row_count=243`,
  and `row_count_matches=true`.
- n8n built-in evaluation run probe:
  `results\n8n_evaluations\n8n-evaluation-run-probe-20260607-120833-367542.json`
  found workflow `TA * Built-in Automation Evaluation`
  (`taBuiltInAutomationEvaluation`) but returned `status=editor_required`;
  open `http://localhost:5678` and run the evaluation from the n8n editor/UI.
- Focused tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_n8n_evaluations.py -q`
  -> `16 passed`.
- Focused n8n policy slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_n8n_runner_policy.py -q -k "evaluation_dataset or overnight_calibration"`
  -> `3 passed, 43 deselected`.
- Targeted Ruff over `tradingagents\orchestration\n8n_evaluations.py` and
  `tests\test_n8n_evaluations.py` passed.
- Process review
  `results\process_reviews\process-review-20260607-120903.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 compact-context cleanup checkpoint:

Codex refreshed `research agent-ledger-summary --json-output` after the ledger
advanced during the n8n evaluation proof work. Compact context now treats the
Agent Intelligence Ledger summary as current, not as a schema drilldown.

Fresh proof:

- `results\_context\latest-summary.json` reports
  `agent_intelligence_summary/forecast_count=4389`,
  `ledger_record_count=4389`, `summary_ledger_count_matches=true`,
  `agent_count=10`, `influence_weight_count=10`, and
  `drilldown_required=false`.
- `results\_context\latest-flags.json` contains only the intentional hourly
  notify, hourly BOARD review, execution BOARD review, and loss-review evidence
  BOARD review routes.
- Process review
  `results\process_reviews\process-review-20260607-122342.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 overnight packet IO extraction checkpoint:

P3 supervisor decomposition advanced: overnight packet writing, compacting,
markdown rendering, latest loading, and candidate validation now live in
`tradingagents/brokers/supervisor/overnight.py`. The legacy
`tradingagents.brokers.alpaca_supervisor` facade re-exports the same helpers,
so the CLI and automations keep their public surface while the overnight
research path becomes easier to audit in isolation.

Fresh proof:

- Focused facade/overnight tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "overnight or extracted or facade"`
  -> `9 passed, 54 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `63 passed`.
- Overnight CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "plan_overnight or compact_overnight or overnight_packet or overnight_validation or verify_overnight"`
  -> `18 passed, 74 deselected`.
- Targeted Ruff over the extracted overnight module, supervisor facade, and
  focused test passed; compileall over the supervisor package and facade
  passed.
- Real analysis-only no-latest probe:
  `results\overnight_plans\overnight_packet_extraction_probe\overnight-plan-20260607-124445-000000.json`
  with `analysis_only=true`, `trade_date=2026-06-08`,
  `ranked_candidates=40`, `submitted=[]`, and `execution_authority=none`.
  No probe `latest.*` files were written.
- Real automation-facing verifier:
  `results\overnight_system_verification\overnight-system-verification-20260607-074606.json`
  reports `overall_status=pass`, latest overnight packet age `2.57h`, Monday
  trade date `2026-06-08`, 3/3 original graph successes, and no submitted
  orders.
- Process review
  `results\process_reviews\process-review-20260607-124635.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 decomposition work: continue extracting hourly decision assembly,
premarket packet IO, and daily-report responsibilities in small, test-backed
slices while preserving the public facade.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 premarket packet IO extraction checkpoint:

P3 decomposition continued by moving premarket brief packet IO out of the large
supervisor facade. Premarket markdown rendering, compacting, packet writing,
latest loading, expected hourly safety-lock classification, and candidate
validation now live in `tradingagents/brokers/supervisor/premarket.py`, while
`tradingagents.brokers.alpaca_supervisor` keeps the same re-exported public
helper names for existing CLI and automation callers.

Fresh proof:

- Focused facade/premarket tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "premarket or extracted or facade"`
  -> `6 passed, 57 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `63 passed`.
- Premarket CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "premarket_brief or preopen_supervisor_includes_premarket or compact_premarket"`
  -> `5 passed, 87 deselected`.
- Targeted Ruff and compileall over the extracted premarket module, supervisor
  facade, and focused test passed.
- Real analysis-only no-latest probe:
  `results\premarket_briefs\premarket_packet_extraction_probe\premarket-brief-20260607-125905-000000.json`
  with `analysis_only=true`, `execution_authority=none`, `source_packets=54`,
  `top_symbol=XOM`, `unresolved_blockers=0`, and `stale_warnings=0`. No probe
  `latest.*` files were written.
- Compact context still only carries intentional hourly/loss-review/BOARD review
  flags.
- Process review
  `results\process_reviews\process-review-20260607-130803.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 decomposition work: extract hourly decision assembly and
daily-report responsibilities in the same small, test-backed style.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 hourly compact packet extraction checkpoint:

P3 decomposition continued into the hourly supervisor path. The compact hourly
sidecar builder and latest raw-hourly packet finder now live in
`tradingagents/brokers/supervisor/hourly.py`, while
`tradingagents.brokers.alpaca_supervisor` re-exports
`compact_hourly_supervisor_payload` and `find_latest_hourly_packet` for the CLI,
tests, compact-context readers, and existing automation imports.

This intentionally does not move the hourly decision tree yet. The next hourly
slice should isolate `build_hourly_evidence(...)`,
`serialize_hourly_decision(...)`, and `write_hourly_decision_packet(...)` before
attempting to move `build_hourly_decision(...)`.

The duplicated hourly/daily `_email_reason_text(...)` formatter was also moved
to `tradingagents/brokers/supervisor/formatting.py`, so daily digest rendering
and hourly alert email rendering share the same pure reason-text cleanup.

Fresh proof:

- Focused hourly/facade tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "hourly or extracted or facade or packet_writers"`
  -> `9 passed, 54 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `63 passed`.
- Hourly plus daily-report CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_supervisor_daily_report_payload_points_to_raw_packet or compact_output_audit_finds_nested_daily_report_packets"`
  -> `17 passed, 75 deselected`.
- Targeted Ruff and compileall over the new modules and facade passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\hourly_packet_extraction_probe\hourly-supervisor-20260607-132214-836105.json`
  with `decision=loss-review`, `submitted=0`, `actions=0`, `issues=0`,
  compact `schema=compact_hourly_supervisor_v1`, `submitted_count=0`, and
  `execution_authority=none`.
- Process review
  `results\process_reviews\process-review-20260607-132832.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 decomposition work: isolate the rest of hourly packet IO, then
consider extracting CLI daily-report packet IO from `cli/main.py`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, latest P3 checkpoint, 2026-06-07 14:12 UTC:

The latest P3 work is the mapper-backed hourly decision context extraction:
`HourlyDecisionContext` and `build_hourly_decision_context(...)` now live in
`tradingagents/brokers/supervisor/hourly.py`, and the supervisor facade uses
that pure context helper without moving branch semantics. Checkpoint process
review: `results\process_reviews\process-review-20260607-141222.json` with
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Tail pointer, latest P3 checkpoint, 2026-06-07 14:22 UTC:

The latest P3 work moved the no-action `review-open-orders` early return into
`tradingagents/brokers/supervisor/hourly.py` as
`build_open_orders_review_decision(...)`. Direct helper coverage now proves the
inspection packet has no actions/submissions, and branch precedence coverage
proves open orders are reviewed before loss-review or buy logic. Current process
review: `results\process_reviews\process-review-20260607-142241.json` with
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 Claude handoff and overnight readiness checkpoint:

Codex re-read the Claude submit-path hardening response and durable handoff,
then re-verified the current machine state before continuing. SAFE-01 remains
fail-closed: `config/risk_envelope.yaml` parses with
`live_budget_mode=autonomous_with_caps`,
`account_max_capital_at_risk_usd=250.00`, `per_name_cap_usd=50.00`,
`tiny_live_tranche_usd=25.00`, optional hard-ceiling/rate-limit knobs unset,
and `issues=[]`. `results/policy/live_control.json` still has the lapsed
dead-man at `2026-06-04T19:57:06+00:00`. Commit `3970998` still contains only
`tradingagents/policy/order_rate_limit.py` and
`tests/test_order_rate_limit.py`; the broader submit-path hardening edits stay
dirty/shared and require hunk-level review before any commit.

The apparent overnight-research outage is currently resolved, not open. Real
verification wrote
`results\overnight_system_verification\overnight-system-verification-20260607-092939.json`
and compact sidecar `results\overnight_system_verification\latest-compact.json`
with `overall_status=pass`, 16/16 checks passed, `execution_authority=none`,
and `can_submit_orders=false`. The production overnight packet
`results\overnight_plans\overnight-plan-20260607-101157-000000.json` targets
trade date `2026-06-08`, top candidate `XOM`, 40 ranked candidates, 3/3
original TradingAgents graph successes on the explicit Google compact route,
37 fallback-ranked symbols, 0 graph failures, and `submitted=[]`. The matching
premarket brief has top symbol `XOM`, 54 source packets, 0 stale warnings, and
0 unresolved blockers.

`research automation-health-audit --json-output` wrote
`results\automation_health\automation-health-audit-20260607-142940.json` with
13/13 automations ok, 0 stale/late/missing/timeliness issues, and
`submitted_order_count=0`. The overnight automation is `PAUSED` only because a
current complete analysis-only packet exists; the verifier accepts that state
under `ACTIVE_OR_PAUSED_AFTER_COMPLETE_PACKET`. Source quality remains
decision-usable through downranking: latest compact review has 250 sources,
224 fresh, 26 stale, 18 stale-downranked, 31 blocked gap packets, and 0 invalid
or unreadable packets.

Fresh proof:

- `python scripts/automation_context_snapshot.py --write` refreshed compact
  context artifacts.
- `alpaca verify-overnight-system --json-output` -> pass packet above.
- `research automation-health-audit --json-output` -> ok packet above.
- `research process-review --json-output` ->
  `results\process_reviews\process-review-20260607-143611.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 self-heal timeliness and agent-ledger schema checkpoint:

- Repaired the current `agent_intelligence_summary` schema drilldown by running
  `research agent-ledger-summary --json-output`. The regenerated
  `results\agent_intelligence\summary.json` now reports 4,491 forecasts,
  matching 4,491 records in `results\agent_intelligence\ledger.jsonl`.
- Refreshed compact context now reports
  `summary_ledger_count_matches=true`; the agent-intelligence schema flag is
  gone.
- Ran the real self-heal monitor loop:
  `automation_context_snapshot.py --write`,
  `research self-heal-handoff --json-output`,
  `research self-heal-plan --execute-safe --json-output`, and
  `research automation-health-audit --json-output`.
- Handoff `results\self_heal\self-heal-handoff-20260607-162425.json` was
  followed by plan
  `results\self_heal\plans\self-heal-plan-20260607-162437.json` in 12 seconds.
- Automation health
  `results\automation_health\automation-health-audit-20260607-162446.json`
  reports 13/13 automations OK, `timeliness_issue_count=0`, and
  `self_heal_timeliness.timely=true`.
- Focused self-heal/automation-health tests passed: `6 passed`.
- Process review
  `results\process_reviews\process-review-20260607-162700.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Next action: leave BOARD/order-adjacent review signals as deliberate manual
review/escalation inputs; do not let the safe self-heal loop mutate trading
authority, live gates, emails, or automation statuses.

2026-06-07 Claude handoff and BOARD/loss-review refresh checkpoint:

- Claude submit-path hardening handoff remains the active cold-start reference.
  SAFE-01 stays fail-closed locally, and commit `3970998` is still only the
  standalone order-rate-limit commit. Shared dirty hardening edits still need
  hunk-level review before any future commit.
- Refreshed TSM loss-review evidence:
  `results\loss_review_evidence\source-evidence-source-evidence-5aaad830f6e244ada344c4ff0bd1b4b9.json`.
  It resolved 12/13 stale blockers; the only remaining blocker is the closed
  market session. The packet is advisory-only with no execution authority.
- Refreshed BOARD:
  `results\execution_board\execution-board-review-20260607-163834.json`.
  It has zero violations and zero submitted orders. It preserves the intended
  behavior: sell decisions are independent, loss exits do not force same-run
  replacement buys, and new buys require controlled dip/support evidence with
  no green-spike chasing.
- Refreshed compact context points hourly, BOARD, and loss-review flags at the
  fresh packets instead of stale missing-evidence blockers.
- Verification passed:
  `tests/test_execution_board.py tests/test_loss_review_evidence.py` -> 16
  passed; compact BOARD/loss-review context slice -> 13 passed; process review
  `results\process_reviews\process-review-20260607-164046.json` reports
  `unchecked_step_count=0` and `findings=[]`.

Next action: keep the remaining loss-review flag as intentional BOARD/manual
context until the next tradeable session and normal live gates can evaluate it.
Do not let self-heal, hooks, or n8n turn the advisory thesis-invalidated
candidate into an order.

2026-06-07 n8n built-in evaluation/dashboard sync checkpoint:

- Local Docker n8n is running at `http://localhost:5678`, and the allowlisted
  runner bridge is reachable on `127.0.0.1:8765`.
- `python -m tradingagents.orchestration.n8n_runner --list-jobs --json`
  reports 24 allowlisted jobs and `submit_capable_count=0`.
- The n8n built-in evaluation dataset was regenerated with 243 rows across 24
  allowlisted jobs, 18 edge tags, 23 columns, and writable actual-output
  columns for n8n Evaluation Set Outputs:
  `results\n8n_evaluations\n8n-evaluation-dataset-20260607-165419-208322.json`.
- The local n8n Data Table was refreshed through the public API using a
  temporary copied SQLite key source that was deleted after use. Proof:
  `results\n8n_evaluations\n8n-api-sync-20260607-165753-318068.json` with
  `expected_row_count=243`, `final_row_count=243`, `row_count_matches=true`,
  and `api_key_redacted=true`.
- Source-controlled observer/evaluation workflows were synced into the local
  dashboard. Proof:
  `results\n8n_evaluations\n8n-workflow-sync-20260607-165802-734061.json`
  with 12 source workflows updated, 0 created, and all inactive.
- Native Evaluation Trigger execution is still an n8n editor/evaluations UI
  action, not a public API or CLI action. Probe:
  `results\n8n_evaluations\n8n-evaluation-run-probe-20260607-165811-433546.json`
  found `taBuiltInAutomationEvaluation`, but all public run routes were
  unsupported and status is `editor_required`.
- Verification passed:
  `tests/test_n8n_evaluations.py tests/test_n8n_runner_policy.py` -> 62
  passed. The official n8n docs align with this setup: evaluations use a
  dataset, Evaluation Trigger, Set Outputs, Set Metrics, and the Run Test flow
  in the Evaluations tab.

Next action: when you want the visual/native proof, open
`http://localhost:5678`, open `TA · Built-in Automation Evaluation`, and run it
from the n8n editor/evaluations UI. Keep n8n as dashboard/evaluation/control
wrapper only; Python remains the automation owner.

2026-06-07 real-simulation freshness hardening checkpoint:

- `tradingagents.evals.real_simulation_audit` now requires the `process_review`
  department command to carry a parseable fresh `generated_at` timestamp. A
  clean-but-old process review no longer satisfies audit acceptance.
- Regression added:
  `tests/test_real_simulation_audit.py::test_real_simulation_audit_rejects_stale_process_review_packet`.
- Verification passed:
  - `tests/test_real_simulation_audit.py` -> 14 passed;
  - `tests/test_real_simulation_audit.py tests/test_process_review.py tests/test_n8n_evaluations.py tests/test_n8n_runner_policy.py` -> 78 passed;
  - targeted Ruff and compileall passed.
- Real live-data dry-run department sweep:
  `results\real_simulation_audits\real-simulation-audit-20260607-170922.json`.
  It ran 28 commands across 8 departments with `failed_command_count=0`,
  `commands_missing_structured_output=[]`, `stale_process_review_commands=[]`,
  `total_submitted_order_count=0`, `unsafe_submission_evidence=false`, and
  `acceptance.core_accepted=true`.
- The audit found `stale_source_count=44`, `stale_safe_count=44`, and
  `stale_downrank_count=30`, so stale evidence is decision-safe by downranking
  or low/unknown quality treatment rather than silently trusted.
- Mac DeepSeek helper remains optional/degraded:
  `optional_helper_degradation_reason=mac_deepseek_helper_unreachable_or_missing`.

Next action: keep Mac DeepSeek as a helper lane only until `/api/tags` responds;
continue using Windows local/deterministic/Codex routes for overnight quality.

2026-06-07 hourly decision router extraction checkpoint:

- P3 supervisor decomposition advanced again. The hourly decision state-machine
  router now lives in `tradingagents/brokers/supervisor/hourly.py` as
  `build_hourly_decision(...)`.
- The legacy `tradingagents.brokers.alpaca_supervisor.build_hourly_decision(...)`
  API remains intact and delegates to the extracted module, injecting
  session/tradeability checks, positive-price parsing, and the live sleeve.
- This preserves branch precedence: review open orders first, then loss review,
  then profit-taking/sell-the-spike, then buy candidate/no-chase, then trailing
  hold.
- Verification passed:
  - extracted-router/facade/branch slice -> `12 passed, 69 deselected`;
  - full supervisor tests -> `81 passed`;
  - hourly/daily CLI slice -> `16 passed, 76 deselected`;
  - targeted Ruff and compileall passed.
- Real hourly dry-run probe:
  `results\hourly_supervisor\hourly_router_extraction_probe\hourly-supervisor-20260607-164738-252488.json`;
  compact sidecar has `decision=loss-review`, `submitted_count=0`,
  `issue_count=0`, `can_submit_orders=false`, `execution_authority=none`, and
  `action_count=0`.
- Process review
  `results\process_reviews\process-review-20260607-164809.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Next action: treat the old P3 "move hourly decision assembly" item as complete
unless new current evidence shows branch duplication or packet-IO drift. Shift
future slices to overnight research quality, source freshness, n8n evaluation
operations, or another current compact flag.

2026-06-07 n8n archived-duplicate sync repair checkpoint:

- Re-read the live n8n Docker database and public API state for
  `TA · Sync Evaluation Dataset`. The apparent duplicate was one current
  workflow plus one archived historical copy, not two runnable/current
  workflows.
- `tradingagents.orchestration.n8n_workflow_sync` now selects update targets
  from non-archived workflows only. It reports current duplicate names in
  `duplicate_name_counts` and archived/history duplicates separately in
  `archived_duplicate_name_counts`.
- `scripts/automation_context_snapshot.py` now carries
  `workflow_sync_archived_duplicate_name_counts` in compact context for
  observability, while only current `duplicate_name_counts` can trigger the
  n8n audit drilldown.
- Real n8n backend proof:
  `results\n8n_evaluations\n8n-workflow-sync-20260607-174046-570170.json`
  reports 12 source workflows, 12 updated, 0 created,
  `duplicate_name_counts={}`, and
  `archived_duplicate_name_counts={"TA · Sync Evaluation Dataset": 2}`.
- Data Table proof:
  `results\n8n_evaluations\n8n-api-sync-20260607-174052-514756.json`
  reports 243/243 rows, 23 columns, `row_count_matches=true`, and
  `api_key_redacted=true`.
- Built-in evaluation run probe:
  `results\n8n_evaluations\n8n-evaluation-run-probe-20260607-174058-485932.json`
  still reports `workflow_found=true`, `status=editor_required`, and
  `supported_endpoint_count=0`; use the n8n editor/evaluations UI for native
  Run Test proof.
- Refreshed compact context no longer raises an n8n evaluation audit flag.
  The n8n compact packet is drilldown-clean with
  `workflow_sync_duplicate_name_counts={}` and
  `workflow_sync_archived_duplicate_name_counts` visible as archived history.

Fresh proof:

- Focused n8n/context tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_n8n_evaluations.py tests/test_automation_context_snapshot.py -q -k "n8n_workflow_sync or n8n_evaluation_dataset"`
  -> `9 passed, 83 deselected`.
- Targeted Ruff passed over
  `tradingagents/orchestration/n8n_workflow_sync.py`,
  `scripts/automation_context_snapshot.py`,
  `tests/test_n8n_evaluations.py`, and
  `tests/test_automation_context_snapshot.py`.
- Process review:
  `results\process_reviews\process-review-20260607-174215.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 verifier tail pointer:

`alpaca verify-overnight-system` now directly verifies source-quality context
and top-provider-bundle coverage. Latest real proof:
`results\overnight_system_verification\overnight-system-verification-20260607-184746.json`
is `overall_status=pass`, with source-quality ordering/downrank evidence
present and top symbols `XOM`, `CVX`, `ADBE` covered by compact
source-routing provider bundles. Focused verifier/provider tests passed
(`9 passed, 167 deselected`) and targeted Ruff passed.

2026-06-07 overnight verifier source-quality/provider-bundle hardening:

- `alpaca verify-overnight-system` now emits explicit checks for
  `overnight_source_quality_context` and `overnight_top_provider_bundles`.
  This closes the blind spot where the verifier could pass an overnight packet
  without proving stale-source downranking or broad provider-bundle coverage.
- The source-quality check requires the overnight packet to carry
  `research_context.watchlists.source_quality` with ordering enabled, status
  available, no stale sources needing refresh, no missing/invalid packets, no
  unreadable packets, and no blocked source-quality packet.
- The provider-bundle check prefers embedded `top_provider_bundles` from the
  overnight packet. For already-produced packets that predate embedded bundle
  fields, it uses `results/_context/source-routing-compact.json` as the
  backward-compatible proof surface for top-candidate bundle coverage.
- Real proof:
  `results\overnight_system_verification\overnight-system-verification-20260607-184746.json`
  reports `overall_status=pass`, no failed/warned checks,
  `overnight_source_quality_context=pass`, and
  `overnight_top_provider_bundles=pass`.
- The current source-quality proof has 250 reviewed sources, 21 stale, 13
  stale-downranked, 0 stale needing refresh, 0 missing/invalid, and 0
  unreadable. Current top provider coverage uses compact source-routing for
  `XOM`, `CVX`, and `ADBE`, with `missing_symbols=[]`.
- Verification passed:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py tests/test_automation_context_snapshot.py -q -k "verify_overnight or provider_bundle"`
  -> `9 passed, 167 deselected`; targeted Ruff over `cli/main.py` and
  `tests/test_alpaca_cli.py` passed.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 ledger/calibration/source-routing refresh:

- Claude's submit-path hardening handoff was re-read and prepared for follow-on
  agents. SAFE-01 remains fail-closed locally, and the standalone unsigned
  commit `3970998` still contains only `tradingagents/policy/order_rate_limit.py`
  and `tests/test_order_rate_limit.py`.
- The source-routing gap for current overnight targets is now clear in compact
  context. `tradingagents/research/youtube_transcript.py` calls the Docker MCP
  `youtube_transcript__get_transcript` route, validates real earnings-call-like
  transcript text, and emits read-only `youtube_transcript` evidence before FMP
  or the explicit gap packet. Refreshed XOM/CVX/ADBE provider bundles no longer
  leave overnight target evidence needs without non-gap packets, and
  `results\_context\latest-flags.json` has no `source_routing` flag.
- `research agent-ledger-update --json-output` confirmed
  `forecast_count=4582`, `discovered_forecast_count=130`, `appended_count=0`,
  and `resolved_forecast_count=0`; all influence weights remain neutral because
  there is not enough resolved history yet.
- `research outcome-labeling --json-output` refreshed model telemetry at
  `results\model_telemetry_reports\model-telemetry-report-20260607-220600-406582.json`.
  Windows local Ollama is selected/successful; the Mac `deepseek-r1:14b` helper
  remains optional/degraded because the Mac host/Ollama probe timed out.
- `research overnight-calibration-guard --json-output` wrote
  `results\overnight_calibration\overnight-calibration-guard-20260607-220624.json`
  with `guard_decision=tighten`, `can_increase_live_influence=false`, controlled
  dip/support-reclaim entry requirements, no green-spike chase, independent
  sell/buy behavior, source freshness requirements, and anti-crowding
  confirmation for bot-copycat/crowded-AI setups.
- Compact context was refreshed and process review
  `results\process_reviews\process-review-20260607-220707.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Next action: keep overnight research live influence tight until resolved
forecast/outcome history improves. Morning workflows should use the clean
XOM/CVX/ADBE provider bundles, fresh quotes/news/account validation, and the
calibration guard before any buy-side escalation.

2026-06-07 overnight/control-plane fresh proof:

- Fresh overnight verification
  `results\overnight_system_verification\overnight-system-verification-20260607-172054.json`
  is `overall_status=pass`, analysis-only, 16/16 checks passed, expected/actual
  trade date `2026-06-08`, top symbol `XOM`, 3/3 original graph successes,
  0 graph failures, and no submitted orders. The overnight automation is ACTIVE
  for the next useful due window.
- Fresh source-quality review
  `results\source_quality\source-quality-review-20260607-222048.json` reviewed
  250 sources: 205 fresh, 45 stale, 45 stale-safe, 25 stale-downranked,
  38 blocked gap packets, 0 unreadable, 0 missing/invalid, and
  `stale_needs_refresh_count=0`.
- Fresh automation health
  `results\automation_health\automation-health-audit-20260607-222049.json`
  reports 13/13 automations OK, no missing/partial/late/stale/warning jobs,
  no submitted orders, and self-heal follow-up timely at 30 seconds.
- n8n job discovery now reports 24 allowlisted jobs and
  `submit_capable_count=0`.
- Compact context was refreshed at 22:24 UTC; `latest-flags.json` contains only
  the intentional hourly/BOARD/loss-review review routes. Process review
  `results\process_reviews\process-review-20260607-222354.json` has
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Next action: at pre-open, rerun fresh quote/news/account validation and keep
new-buy influence tight unless the live gates plus the calibration guard agree.

Tail pointer, YouTube transcript provider route, 2026-06-07 21:45 UTC:

- Claude's submit-path handoff remains prepared and SAFE-01 remains fail-closed.
  This slice did not change live authority, refresh the dead-man, send email,
  submit orders, or touch automation status.
- The remaining P1 transcript lift is now materially improved:
  `tradingagents/research/youtube_transcript.py` adds a read-only Docker MCP
  bridge for `youtube_transcript__get_transcript`. The provider orchestrator now
  attempts `youtube_transcript` before FMP for `earnings_transcripts`, then
  still falls through to the explicit `earnings_transcripts_gap` when discovery,
  transcript relevance, Docker MCP, or FMP is unavailable.
- Real proof:
  `results\research_evidence\youtube_transcript_probe\source-evidence-source-evidence-107cb2c1d5bf4cf9b6c71c1e3af1cd78.json`
  is a non-gap `youtube_transcript` earnings transcript packet for `XOM`, and
  summary
  `results\research_evidence\youtube_transcript_probe\source-evidence-source-evidence-e4c80ea7e67e457cb29e5fb2be8ab63a.json`
  reports `unsupported_route_count=0`, `blocked_packet_attempt_count=0`,
  `gap_packet_count=0`, and no missing non-gap transcript evidence.
- Real overnight proof:
  `results\overnight_plans\youtube_transcript_probe\overnight-plan-20260607-214130-000000.json`
  produced top candidate `XOM`, `submitted_count=0`,
  `execution_authority=none`, `top_provider_bundle_error_count=0`, and
  `top_provider_bundle_missing_non_gap_needs=[]`.
- Verification: `tests/test_youtube_transcript_bridge.py` and
  `tests/test_research_provider_orchestrator.py` -> `34 passed`; overnight CLI
  plan slice -> `14 passed, 82 deselected`; targeted Ruff passed.

Follow-up, 2026-06-07 21:55 UTC:

- `scripts/automation_context_snapshot.py` now evaluates overnight target
  provider coverage from the latest provider bundle per symbol. Older stale
  bundles remain visible in history, but they no longer keep a refreshed target
  falsely flagged.
- Fresh CVX and ADBE bundles wrote non-gap `youtube_transcript` packets and
  cached short-interest/options evidence:
  `results\research_evidence\source-evidence-source-evidence-43183b7d0f874a08bf384074a682e438.json`
  for CVX and
  `results\research_evidence\source-evidence-source-evidence-fd80a8881c8c4e309cff9f6855424eb3.json`
  for ADBE.
- Refreshed compact context now has top target provider coverage for
  `["XOM","CVX","ADBE"]`, no missing target bundles, no target symbols with
  missing non-gap evidence, and no target missing non-gap evidence needs.
  `latest-flags.json` no longer includes `source_routing`.
- Verification: source-routing overlay tests -> `3 passed, 75 deselected`;
  Ruff over the context snapshot/test files passed; process review
  `results\process_reviews\process-review-20260607-215353.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

## Tail Pointer: P1 Overnight Source Routing Automation, 2026-06-07 21:13 UTC

- Implemented the P1 connector-routing objective for overnight top candidates:
  `alpaca plan-overnight` now refreshes top-ranked candidate provider bundles by
  default and writes compact `top_provider_bundles` metadata into the overnight
  packet.
- The production default is bounded (`--top-provider-bundle-count 3`) and
  analysis-only; tests and manual probes can disable it with count `0`.
- Real no-latest proof packet:
  `results\overnight_plans\top_provider_bundle_probe\overnight-plan-20260607-210455-000000.json`
  had top candidate `XOM`, one provider bundle, 7 source packets, no submitted
  orders, and `execution_authority=none`.
- Context snapshot now persists fresh provider-bundle overlay data into
  `results\_context\source-routing-compact.json`, keeping n8n/backend readers
  synchronized with `latest-summary.json`.
- Current target source-routing state: `XOM`, `CVX`, and `ADBE` have provider
  bundles; no current top target is missing a bundle. Remaining target
  weakness is transcript coverage (`earnings_transcripts`), which should be
  downranked or refreshed before event-underreaction claims.
- Verification: overnight CLI slice `14 passed`, provider/context slice
  `104 passed`, source-routing overlay slice `2 passed`, targeted Ruff passed,
  and process review
  `results\process_reviews\process-review-20260607-211322.json` was clean.

2026-06-07 overnight latest-alias hardening checkpoint:

- The overnight packet loader and generic CLI packet verifier now select the
  freshest readable production packet across `latest.json` and timestamped raw
  packets by `generated_at`, falling back to file mtime only when a packet has
  no parseable timestamp.
- `write_overnight_plan_packet(...)` now records `latest_alias_written`. Raw
  packets written with `write_latest=False` remain probe/observer artifacts and
  cannot supersede the production latest alias.
- This closes the documented risk where `latest.json` could lag a fresher
  timestamped overnight packet and make morning agents falsely report stale or
  wrong overnight state.
- Regression coverage:
  - stale `latest.json` plus newer production raw selects the newer raw packet;
  - no-latest probes are skipped by the production loader/verifier;
  - compact sidecars are ignored by the raw overnight loader.
- Verification passed:
  - `tests/test_alpaca_supervisor.py -k "overnight_packet_writer or load_latest_overnight_plan or overnight_validation or overnight_markdown"` -> 7 passed;
  - `tests/test_alpaca_cli.py -k "latest_json_packet_path or verify_overnight_system"` -> 6 passed;
  - targeted Ruff and compileall passed.
- Real no-submit proof:
  `results\overnight_system_verification\overnight-system-verification-20260607-125346.json`
  reports `overall_status=pass`, current production top `XOM`, trade date
  `2026-06-08`, 3/3 graph successes, 0 graph failures, and 0 submitted orders.
- Process review:
  `results\process_reviews\process-review-20260607-175343.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Next action: when overnight reports look stale, trust this selection path before
manual packet spelunking. If both latest and timestamped packets disagree, use
the freshest production packet and treat explicit no-latest probes as evidence
only.

2026-06-07 safe self-heal stale-evidence refresh checkpoint:

- Claude's submit-path hardening handoff was re-read and verified against disk.
  SAFE-01 remains fail-closed: local `config/risk_envelope.yaml` parses as
  `live_budget_mode=autonomous_with_caps`, account max `$250`, per-name `$50`,
  optional hard-ceiling/rate-limit knobs unset, and `issues=[]`. Live control is
  not frozen, but the dead-man is expired at `2026-06-04T19:57:06+00:00`.
- `tradingagents/orchestration/self_heal.py` now treats stale
  `loss_review_evidence` and stale `preopen_validation` compact flags as
  safe-plane refresh work. The allowlisted commands refresh the exact evidence
  packet and compact context only. They cannot submit orders, send email, change
  automation status, refresh live control, read secrets, or turn BOARD evidence
  into trading authority.
- Order-adjacent BOARD/hourly signals still escalate instead of auto-fixing.
  Real proof after the stale flags were cleared:
  `results\self_heal\plans\self-heal-plan-20260607-181507.json` executed 0 safe
  actions, skipped 2 order-adjacent escalations, and kept
  `can_submit_orders=false`.
- Fresh preopen proof:
  `results\preopen_validation\preopen-validation-20260607-181534.json` has
  `overall_status=pass_with_warnings`, 0 submitted orders, 0 open live orders,
  0 open paper orders, 4 live positions, 14 paper positions, and only warns
  because live control is expired while the market is closed.
- Fresh TSM loss-review proof:
  `results\loss_review_evidence\source-evidence-source-evidence-e23335b8bedd4bf6a91277c8a355aeda.json`
  is fresh, analysis-only, resolves 12/13 evidence blockers, and leaves only
  `market session is not tradeable for a live loss exit`.
- Fresh BOARD proof:
  `results\execution_board\execution-board-review-20260607-181725.json` has
  `violation_count=0`, `submitted_order_count=0`, and 2 warnings: negative live
  unrealized P/L history plus BOARD-only TSM thesis-invalidated candidate.
  New buys remain limited to separate controlled dip/support setups with no
  green-spike chase; sells remain independent and do not force replacement buys.
- Automation health:
  `results\automation_health\automation-health-audit-20260607-181654.json`
  reports 13/13 automations OK, no missing/late/stale/duplicate problem jobs,
  0 submitted orders, and self-heal follow-up `timely=true` with 30 second
  lag.
- Process review:
  `results\process_reviews\process-review-20260607-181651.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
- Verification passed:
  - `tests/test_self_heal_handoff.py -k "preopen_validation or loss_review_evidence or safe_connector or automation_health or model_route or agent_ledger"` -> 8 passed;
  - `tests/test_self_heal_handoff.py tests/test_automation_context_snapshot.py -k "loss_review_evidence or preopen_validation or self_heal or automation_health"` -> 42 passed;
  - targeted Ruff and compileall passed.

Next action: keep stale evidence refreshes in the safe self-heal lane, but keep
BOARD/order-adjacent trading judgment manual/escalated until a tradeable session
and the normal live gates re-evaluate it.

Post-check: full pytest also passed after this checkpoint:
`uv run --no-sync --with pytest python -m pytest -q` -> 1067 passed, 1
skipped, 9 warnings, 75 subtests passed in 395.36s. Final process review
`results\process_reviews\process-review-20260607-183102.json` still reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-07 agent-ledger hermetic full-suite checkpoint:

- Claude's submit-path hardening handoff was re-read and prepared again. SAFE-01
  remains fail-closed in local machine state: `config/risk_envelope.yaml` parses
  as `live_budget_mode=autonomous_with_caps`, account max `$250`, per-name
  `$50`, optional hard-ceiling/rate-limit knobs unset, and `issues=[]`.
  `results/policy/live_control.json` is not frozen but the dead-man is expired
  at `2026-06-04T19:57:06+00:00`, so live submit remains blocked unless the
  operator explicitly refreshes live control.
- Full pytest exposed a second shared-state leak: `alpaca plan-overnight` tests
  used the production default Agent Intelligence Ledger path and appended 23
  overnight forecasts to `results/agent_intelligence/ledger.jsonl`, making
  `summary.json` lag the ledger.
- `tests/test_alpaca_cli.py` now uses a hermetic test runner for `alpaca
  plan-overnight`: when a test does not explicitly pass an agent-ledger flag, it
  appends `--no-agent-ledger`. The main write path remains covered by
  `test_plan_overnight_writes_analysis_packet_without_submitting`, which passes
  a temp `--agent-ledger-path` and asserts the packet ledger metadata.
- The production ledger summary was regenerated to match the current ledger:
  `forecast_count=4582`, `ledger_record_count=4582`, `agent_count=10`.
- Verification passed:
  - `tests/test_alpaca_cli.py -k "plan_overnight"` -> `12 passed, 83 deselected`;
  - focused CLI/self-heal regressions -> `2 passed` and `5 passed, 21 deselected`;
  - targeted Ruff over the touched test/self-heal files -> passed;
  - full pytest -> `1067 passed, 1 skipped, 9 warnings, 75 subtests passed`;
  - post-suite ledger check still matched `4582/4582`;
  - process review `results\process_reviews\process-review-20260607-191506.json`
    reports `unchecked_step_count=0`, `findings=[]`, and
    `can_submit_orders=false`.
- Refreshed compact context contains only the intentional hourly/BOARD/loss
  review drilldowns; there is no `agent_intelligence_summary` schema flag.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

2026-06-07 overnight verifier tail pointer:

`alpaca verify-overnight-system` now directly verifies source-quality context
and top-provider-bundle coverage. Latest real proof:
`results\overnight_system_verification\overnight-system-verification-20260607-184746.json`
is `overall_status=pass`, with source-quality ordering/downrank evidence
present and top symbols `XOM`, `CVX`, `ADBE` covered by compact source-routing
provider bundles. Focused verifier/provider tests passed (`9 passed, 167
deselected`) and targeted Ruff passed.

2026-06-08 self-heal/BOARD/connector-health compaction checkpoint:

- Real safe self-heal command:
  `research self-heal-plan --execute-safe --safe-reverify-minutes 0 --json-output`
  wrote `results\self_heal\plans\self-heal-plan-20260608-000706.json`.
  It executed one allowlisted safe-plane action, ran night-shift patrol plus
  automation-health audit, and verified both with `verify_failed_count=0`.
- Automation health:
  `results\automation_health\automation-health-audit-20260608-000705.json`
  reports 14/14 automations OK, no duplicate/stale/late/warning jobs, 0
  submitted orders, and self-heal follow-up `timely=true` with 74 second lag.
- Loss-review/BOARD:
  `results\loss_review_evidence\source-evidence-source-evidence-c263d6f15eca4685ab471abb8cf276ed.json`
  and `results\execution_board\execution-board-review-20260608-001151.json`
  remain analysis-only with 0 submitted orders, 0 hard violations, and TSM
  blocker delta `13 -> 1`; the remaining blocker is market session not
  tradeable.
- Connector-health compaction:
  `scripts/automation_context_snapshot.py` now keeps `youtube_transcript` MCP
  timeout errors visible in `results\_context\connector-health.json` but quiet
  in top-level compact flags when no circuit/rate-limit/fallback failure is
  present and the provider orchestrator already fell through to an
  earnings-transcript gap packet. This keeps optional transcript failures from
  stealing the morning first-screen context.
- Verification:
  `uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py -q -k "connector_health or youtube_transcript"`
  -> `2 passed, 77 deselected`; targeted Ruff passed; process review
  `results\process_reviews\process-review-20260608-001637.json` has
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

2026-06-08 real walk-forward/calibration checkpoint:

- `research walk-forward-refresh-overnight-cohort --json-output` wrote
  `results\research_batches\walk_forward_cohort_refresh_20260608-002404_h3.json`
  from 12 mature overnight packets. Two `2026-06-08` packets were skipped as
  not mature. The run collected 105 later-return rows, generated 140 replay
  fixture rows, and remained analysis-only with no execution authority.
- The cohort argues for tightening, not expanding live influence:
  deterministic sleeve directional accuracy `0.3143`, false-positive rate
  `0.2786`, average action-relative return `-1.6585`; TradingAgents advisory
  overlay only scored 8 rows, below sample floor, with directional accuracy
  `0.3750`, false-positive rate `0.6250`, and average action-relative return
  `-1.3762`.
- `research overnight-calibration-guard --json-output` wrote
  `results\overnight_calibration\overnight-calibration-guard-20260608-002515.json`
  with `guard_decision=tighten`, `can_increase_live_influence=false`, and
  live influence policy `tighten_or_hold_reduced_weight`. Morning buys should
  require controlled dip/support reclaim, no green-spike chase, buy/sell
  independence, fresh source-quality evidence, and anti-crowding confirmation.
- `research outcome-labeling --json-output` refreshed model telemetry and
  market-mirror labels, but current forecasts remain unresolved.
- Verification:
  `uv run --no-sync --with pytest python -m pytest tests/test_replay_ablation_plan.py tests/test_overnight_calibration_guard.py tests/test_automation_context_snapshot.py -q -k "walk_forward or overnight_calibration or model_telemetry or source_routing or connector_health"`
  -> `18 passed, 80 deselected`; process review
  `results\process_reviews\process-review-20260608-002613.json` has
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
