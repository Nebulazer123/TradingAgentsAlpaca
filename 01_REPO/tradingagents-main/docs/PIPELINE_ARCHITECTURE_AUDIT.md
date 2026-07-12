# TradingAgents — Pipeline Architecture Audit

**Date:** 2026-06-03
**Method:** 6 parallel subagents (one per subsystem, read-only) → verified against source by the lead model. Every P0/P1 below was re-read in the actual code; subagent line/severity claims that did not survive verification are listed in §7 so they are not chased.
**Scope:** entire `tradingagents/` tree + `cli/` + `config/` + `scripts/`.

---

## 1. Executive summary

The repo is the canonical **TauricResearch TradingAgents** multi-agent framework (arXiv 2412.20138) wrapped in a large, **safety-first automation overlay** the user added (deterministic live gates, risk envelope, idempotency, reconciliation, n8n observer, self-heal, graph memory, agent-intelligence ledger).

**Verdict:** the *decision pipeline* (the 7 canonical stages) is fully present and correctly ordered, and the *safety contract* (analysis-only automation, fail-closed gates) is largely airtight. The gaps are not architectural holes — they are **edge-case fail-opens, dead/unwired code, and fragile defaults**, plus the usual prompt/wiring bugs.

| Subsystem | Pipeline alignment | Real defects found | Top risk |
|---|---|---|---|
| Agent roles | ✅ all 11 roles present, debate math correct | analyst batching now wired for compact/full-graph profiles | keep concurrency conservative for tool-heavy runs |
| Graph orchestration | ✅ 7 stages correctly wired | exports/comments; **2 "P0"s were false** | none critical |
| Dataflows | ✅ 4 analyst categories covered | Massive is now a price/OHLCV decision fallback; ScrapingBee remains research/enrichment only | transcript/options/short-interest are optional or supplemental advisory routes with gap fallback |
| Execution & safety | ✅ fail-closed on missing state | P0 loss-review/example-default issues fixed | none critical in this audit |
| Automation/research/evals | ✅ analysis-only boundary holds | P1 n8n/self-heal cases pinned by tests | none critical in this audit |
| LLM / CLI / config | ✅ 4 provider families dispatch | Azure/Gemini config bugs fixed | provider docs should stay current |

**2026-06-05 current-status addendum:** the overnight pipeline itself is healthy
after catch-up, but the control-plane evidence layer had been too forgiving.
`automation_health_audit` now treats `tradingagents-overnight-planning` as a
due-aligned scheduled job, not a wake-controller-dependent daytime job, so a
missed 2:30 AM Central packet is no longer hidden by stale memory. Real proof:
`results\overnight_plans\overnight-plan-20260605-101740-000000.json` completed
3/3 Google full-graph tickers with zero submissions, and
`results\overnight_system_verification\overnight-system-verification-20260605-051922.json`
passes. Self-heal now plans and verifies on `automation_health` compact flags
without order authority. Separately, MiroFish/report-33 false-signal gates now
reach candidate scoring: broker/fintech watch names are visible, but
unconfirmed broker-friction/social-flow or crowded-AI-beta setups are
downranked until independent confirmation appears. Real no-submit proof:
`results\overnight_plans\mirofish_score_probe\overnight-plan-20260605-103822-000000.json`.

**2026-06-06 loss-review evidence addendum:** the execution/BOARD overlay now
has a dedicated evidence bridge for losing live positions. `research
loss-review-evidence --json-output` finds the latest hourly
`decision=loss-review`, refreshes analysis-only quote/news/fundamentals/
earnings evidence, and writes `results\loss_review_evidence\latest.json` with
`review_allowed=false`, `can_submit_orders=false`, and
`execution_authority="none"`. The bridge now records the before/after blocker
state: current real proof for `TSM` shows 13 blockers before refresh, 3 resolved
by refreshed evidence, and 10 remaining judgment/session blockers. Resolved
blockers are limited to source IDs, company-specific news, and
earnings/guidance/filing evidence; it does not approve a loss exit or create a
trade intent. This closes the pipeline gap where BOARD could pause new buys but
lacked a compact, source-backed packet for deciding whether holding a loser or
exiting at a loss has better expected value. n8n can trigger the same observer
through the `loss_review_evidence` allowlisted job; job discovery reports 21
allowlisted jobs and zero submit-capable jobs.

**2026-06-07 loss-review entry-history addendum:** the bridge now also searches
local hourly supervisor history for the prior same-symbol live buy, so BOARD no
longer treats known local entry context as missing. Current TSM proof:
`results\loss_review_evidence\source-evidence-source-evidence-2594f15673fe4fe5825f31325f00df88.json`
has `entry_context_found=true` from
`results\hourly_supervisor\hourly-supervisor-20260601-170250-428127.json`,
client order id `ta-hourly-20260601-170250-1-tsm-buy`, the original entry
reason, and 4 trading days of holding-period evidence. The blocker delta is now
13 before refresh, 8 resolved, 5 remaining. Remaining blockers are still
manual/session gates: allowed loss-exit reason/source, current thesis status,
loss-exit confidence, and non-tradeable session. n8n preserves this fact in its
parsed summary with `entry_context_found=true` and `submit_capable=false`.
Refreshed BOARD proof:
`results\execution_board\execution-board-review-20260607-015047.json` has zero
hard violations, zero submitted orders, `new_buy_policy.state=caution`, and
independent sell/buy policy intact.

**2026-06-06 raw-packet sidecar hardening addendum:** durable compact sidecars
created a subtle packet-discovery risk: broad raw globs could match
`*.compact.json` files, and same-timestamp raw packet names could sort in the
wrong order. Raw-packet readers now skip `.compact.json` and
`latest-compact.json` sidecars unless they explicitly ask for compact context;
`find_latest_hourly_packet(...)` uses file mtime. The protection covers hourly
supervisor reports, ORCL reconciliation discovery, compact-output audit,
loss-review evidence lookup, provider snapshot lookup, and automation-health
artifact accounting. Verification: submit-path suite 160 passed,
compact/loss/n8n/health suite 125 passed, targeted Ruff passed, and process
review `results\process_reviews\process-review-20260606-235921.json` has
`unchecked_step_count=0`. Full regression gate also passed: full pytest
`952 passed, 1 skipped, 9 warnings, 75 subtests`; repo Ruff clean; mypy clean
across 57 broker/policy/execution/dataflow files.

**2026-06-06 overnight calibration guard addendum:** the outcome/eval layer now
turns the real walk-forward cohort warning into a compact, analysis-only control
packet. `research overnight-calibration-guard --json-output` reads the latest
captured overnight cohort and writes `results\overnight_calibration\latest.json`.
The current packet
`results\overnight_calibration\overnight-calibration-guard-20260606-214537.json`
returns `guard_decision=tighten`, `can_increase_live_influence=false`,
`can_submit_orders=false`, and `execution_authority=none`. This keeps the
original TradingAgents overnight pipeline useful for research while preventing a
weak underperforming cohort from being mistaken for permission to increase live
influence. n8n observes the same packet through the read-only
`overnight_calibration_guard` job; the latest local Data Table sync covers 192
rows across 21 allowlisted jobs and still has `submit_capable_count=0`.

**2026-06-06 self-heal reverify addendum:** safe-plane dedupe is now
time-bound. A still-active safe signal that was previously recorded becomes a
planned verification again after the default 15-minute SLA; immediate repeats
still dedupe. Real forced proof
`research self-heal-plan --execute-safe --safe-reverify-minutes 0 --json-output`
wrote `results\self_heal\plans\self-heal-plan-20260606-221514.json`,
`executed_count=1`, `verified_count=1`, `verify_failed_count=0`,
`can_submit_orders=false`, and `execution_authority=none`. The command ran the
allowlisted automation-health audit only; hourly/BOARD signals remained
`escalate_order_adjacent`, so no order path, email path, goal mutation, or
automation-status mutation was created. Verification passed with focused
self-heal/context tests, CLI packet-coverage regression, Ruff, `py_compile`,
process review `unchecked_step_count=0`, and full pytest `937 passed, 1 skipped,
9 warnings, 75 subtests passed`.

**2026-06-06 night-shift self-heal repair addendum:** the safe-plane
automation-health action now repairs the missing observer evidence before
verifying it. The allowlisted sequence is: `research night-shift-patrol
--json-output`, then `research automation-health-audit --json-output`; both
remain analysis-only, cannot submit orders, cannot send email, cannot mutate
automation status, and cannot refresh live control. The automation-health audit
also treats night-shift as current when the latest due slot is covered, while
still reporting a true `partial` if the latest due slot is missing. Real proof:
`results\self_heal\plans\self-heal-plan-20260606-225530.json` has
`executed_count=1`, `verified_count=1`, `verify_failed_count=0`, and two
allowlisted command results; it wrote
`results\night_shift_patrol\night-shift-patrol-20260606-225524.json` and
`results\automation_health\automation-health-audit-20260606-225529.json`.
That latest audit reports `ok_count=13`, `partial_count=0`,
`submitted_order_count=0`, and night-shift
`status_reason=night_shift_latest_due_covered_history_ramp_up`. Compact context
no longer flags automation health. Focused proof: 46 self-heal/automation-health
tests passed, targeted Ruff passed, process review
`results\process_reviews\process-review-20260606-225623.json` has
`unchecked_step_count=0`, and compact context was refreshed.

---

## 2. The ideal pipeline vs. this repo

**Canonical TradingAgents pipeline (what "ideal" means here):**

```
Data → 4 Analysts (Market · Sentiment · News · Fundamentals)
     → Bull ⇄ Bear researcher debate → Research Manager (investment plan)
     → Trader (proposal)
     → Aggressive ⇄ Neutral ⇄ Conservative risk debate → Portfolio Manager (decision)
     → Execution (broker, behind gates)   + reflection/memory loop
```

**This repo's actual graph (traced through `graph/setup.py`):** matches the canonical sequence exactly — 4 analysts (each with a tool-call loop + message-clear), a `2×max_debate_rounds` bull/bear loop, Research Manager, Trader, a `3×max_risk_rounds` Aggressive→Conservative→Neutral loop, Portfolio Manager, END. Reflection is deferred (Phase B): a decision is logged, then scored at the start of the next same-ticker run.

**Two deliberate divergences (by design, not bugs):**
- **Execution is out-of-band.** The graph ends at the Portfolio Manager; the Alpaca broker + deterministic gates live outside the graph. This is the right call for safety (the LLM graph can never directly place an order), but it means the "execution" box in any diagram is a separate deterministic system, not a graph node.
- **Reflection is deferred, not in-run.** The graph cannot learn within a single run; lessons only reach the *next* run for that ticker.

---

## 3. P0 — verified, high-value (fixing in this pass)

| # | File:line | Defect | Fix direction |
|---|---|---|---|
| P0-1 | `agents/analysts/fundamentals_analyst.py:30` | Trailing comma makes `system_message` a **1-tuple, not a string** → prompt template gets `"('You are…',)"`. Active bug in the tool-calling fundamentals analyst. | ✅ FIXED — removed trailing comma. |
| ~~P0-2~~ | ~~`brokers/alpaca.py:507`~~ | ~~Missing `live_exposure_limit` check in `build_order_pairs`.~~ **WITHDRAWN** — `test_build_order_pairs_does_not_apply_old_live_exposure_cap` proves the live cap is *intentionally* not enforced here (live sizing is governed by the risk envelope / live gate under `autonomous_uncapped`). Adding the check broke that test. See §7. | Reverted. |
| P0-3 | `policy/live_gate.py:290` | Loss-exit gate did `continue` (skips review) when `avg_entry_price` is `None`. A losing live **sell on a position whose broker payload omits avg entry price bypassed loss-review** — a fail-open edge. | ✅ FIXED — only skip on *confirmed* non-loss (both prices known and proposed ≥ entry); otherwise require review. Tests green. |
| P0-4 | `config/risk_envelope.example.yaml:17` | Example file shipped `live_budget_mode: autonomous_uncapped` → anyone copying it verbatim arms **uncapped live exposure** with no dollar guardrail. | ✅ FIXED — example now defaults to `fixed_tranche`; real `risk_envelope.yaml` untouched. |

---

## 4. P1 — verified or high-confidence (fixing the safe ones this pass)

| # | File:line | Defect | Status |
|---|---|---|---|
| P1-1 | `dataflows/interface.py:197` (`VENDOR_METHODS`) | `sec.py`, `eia.py`, `massive.py`, `scrapingbee.py` are fully implemented but not all belong in the decision graph. SEC EDGAR and EIA were the right decision-path promotions. Massive now also belongs in the bounded price/OHLCV fallback path. | ✅ FIXED — SEC fundamentals, EIA energy/macro, and Massive price/OHLCV are wired into the vendor chain; ScrapingBee stays enrichment-only. |
| P1-2 | `dataflows/y_finance.py:303,335,365,397,431` + `yfinance_news.py:105,199` | Return **error strings instead of raising** → `interface.py` treated the error string as a successful non-empty result and the **fallback chain never advanced**. | ✅ FIXED — router now treats known vendor error/no-data strings as fallback failures. |
| P1-3 | `dataflows/alpha_vantage_indicator.py:208` | Bare `except` can return an `"Error retrieving..."` string so `interface.py` may not see a transient exception. | ✅ FIXED at router boundary — Alpha Vantage error strings now advance fallback while true non-transient raised errors remain preserved. |
| P1-4 | `pyproject.toml` `[project.dependencies]` | `python-dotenv` used by `cli/utils.py` but **not a declared dependency** (only transitive). | ✅ FIXED — added `python-dotenv>=1.0.1`. |
| P1-5 | `evals/automation_health_audit.py:418` | `_has_near_duplicate_artifacts` **defined twice**; first is dead/shadowed. | ✅ FIXED — dead copy removed. |
| P1-6 | `evals/agent_intelligence_ledger.py:626` | `AgentForecast(**json.loads(line))` unguarded → one schema-drifted JSONL line aborts the **entire** ledger load. | ✅ FIXED — malformed/schema-drifted lines are skipped. |
| P1-7 | `orchestration/n8n_policy.py:13` | `supervise-hourly` was suspected safe without requiring `--dry-run`. | ✅ FIXED/VERIFIED — current `SAFE_ALPACA_SUBCOMMANDS` excludes `supervise-hourly`; tests reject non-submit-capable broker wording and submit actions. |
| P1-8 | `orchestration/self_heal.py:246` | Counter triggers (`blocker_count`, etc.) could under-trigger if treated as unknown reasons. | ✅ FIXED/VERIFIED — counter triggers compute severity directly; test pins blocker/issue counters as actionable. |
| P1-9 | `agents/managers/research_manager.py:21`, `managers/portfolio_manager.py:28`, `analysts/sentiment_analyst.py` | `build_instrument_context()` called **without `asset_type`** → crypto runs silently get the stock prompt hint. | ✅ FIXED — asset type is threaded through research manager, portfolio manager, fundamentals, and sentiment paths. |
| P1-10 | `graph/setup.py` | `analyst_concurrency_limit` was threaded through the whole API but **never wired to a fan-out** — analysts always ran sequentially despite the advertised concurrency. | ✅ FIXED — LangGraph `Send` fan-out now runs analysts in bounded batches when the limit is greater than 1; compact/market-news overnight profiles default to 2 while default/full remains conservative. |
| P1-11 | `graph/analyst_execution.py` + `graph/setup.py` + `conditional_logic.py` | The `tools_social` ToolNode + `should_continue_social` edge were **dead**: the sentiment analyst is prefetch-only and never emits tool calls. | ✅ FIXED — social/sentiment is declared tool-free, graph setup skips `tools_social`, and direct analyst → cleanup routing is pinned by tests. |
| P1-12 | `llm_clients/google_client.py:57` | Gemini-2.5 `thinking_budget` maps `minimal`→`0`, which **disables thinking entirely** instead of using a small budget. | ✅ FIXED — Gemini 2.5 minimal now maps to a small positive thinking budget; Gemini 3 Pro minimal still maps to low. |
| P1-13 | `llm_clients/azure_client.py` + `.env.example` | No pre-call validation of `AZURE_OPENAI_ENDPOINT`/`OPENAI_API_VERSION`, and those vars are **absent from `.env.example`**. | ✅ FIXED — Azure validates endpoint/version/deployment before SDK construction and `.env.example` documents the vars. |

---

## 5. P2/P3 — agent-reported, lower priority (roadmap, not this pass)

- ✅ **FIXED follow-up** `dataflows/utils.py:50` — `get_current_date()` now normalizes to the UTC date, preventing non-US/local-clock look-ahead during U.S. market windows.
- ✅ **FIXED follow-up** `dataflows/alpha_vantage_common.py:122` — date-filter failures now fail closed with an Alpha Vantage error string instead of returning unfiltered CSV rows; the router treats that string as failed evidence and can advance to fallbacks.
- ✅ **FIXED follow-up** `dataflows/decision_vendor_adapters.py` / `reddit.py` / `stocktwits.py` — StockTwits and Reddit sentiment now receive the requested date window and filter returned public/recent messages by timestamp. These sources remain advisory/recent-only, but the analyst prompt no longer receives out-of-window social messages as if they were scoped evidence.
- ✅ **FIXED follow-up** `dataflows/stockstats_utils.py:64` — the OHLCV cache now actually fetches the documented 15-year window, preventing older historical indicator replays from filtering a too-recent 5-year cache down to empty data.
- ✅ **FIXED follow-up** `dataflows/alpaca_market_data.py` / `cli/main.py` — Alpaca latest-trade market data is now a read-only quote provider for the aggressive-candidate feed. During tradeable sessions fresh Alpaca latest-trade rows outrank yfinance, stale/missing Alpaca falls back to yfinance `1d/5m`, and stale provider rows remain unrankable.
- ✅ **FIXED follow-up** `execution/reconcile.py:45` — live-position reconciliation now tolerates fractional-share rounding dust up to `0.000001`, matching the order-comparison tolerance while still blocking real mismatches.
- ✅ **FIXED follow-up** `research/twitter_mcp.py` / `research/provider_orchestrator.py` / `config/research_provider_fallbacks.json` — Docker MCP `twitter-research` is now a repo-callable, read-only social-sentiment bridge. Twitter/X was removed from `market_news` routing, and current recent-search API permission failures produce explicit blocked/downrankable evidence packets instead of a misleading missing-bridge packet.
- ✅ **FIXED follow-up** `brokers/alpaca_supervisor.py` — approved loss exits and profit-taking now require positive current-price evidence before building a close order. Missing/blank/non-positive prices force `loss-review` or `profit-review` with `actions=[]` instead of a synthetic `$1` limit sell.
- ✅ **FIXED follow-up** `cli/main.py` / `brokers/alpaca_supervisor.py` — the yfinance `5d/1d` aggressive-candidate fetcher now marks daily-bar rows stale during tradeable sessions, then attempts yfinance `1d/5m` `prepost=true` as the fresh current-price path. Candidate scoring skips rows with `stale_quote=true` or `quote_fresh=false`, so stale daily closes cannot rank live/paper candidates unless replaced by a parseable intraday bar no older than 30 minutes. This closes the stale daily-close → ranked live/paper candidate gap while preserving closed-market overnight planning context.
- ✅ **FIXED follow-up** `policy/live_control.py`, `policy/preregistration.py`, `policy/promotion.py` — policy/control-plane state now writes through `tradingagents.policy.io.atomic_write_text`; preregistration JSONL appends use `atomic_append_line`. Failed replacement preserves prior state and cleans temp files instead of risking partial lockout-causing state.
- ✅ **FIXED follow-up** `cli/stats_handler.py`, `cli/main.py` — explicit env call/token caps now halt the interactive graph mid-run through `ModelBudgetExceededError`. Caps remain opt-in for manual runs: no env cap means no default 8-call surprise halt.
- ✅ **FIXED follow-up** `agents/researchers/bull_researcher.py`, `agents/researchers/bear_researcher.py` — prior decision/outcome lessons in `past_context` now reach the bull/bear debate when available, while empty first-run prompts remain unchanged.
- ✅ **FIXED follow-up** `agents/analysts/news_analyst.py` — `get_insider_transactions` is now imported, bound as a news analyst tool, and explicitly listed in the news prompt for stock-specific insider buying/selling context.
- ✅ **FIXED follow-up** `dataflows/decision_vendor_adapters.py` — BEA macro context now fetches every calendar year in the requested lookback window instead of only `curr_date.year`.
- ✅ **FIXED follow-up** `graph/analyst_execution.py` / `graph/setup.py` / `graph/conditional_logic.py` — social/sentiment analyst is now tool-free in the execution plan. Graph setup skips the dead `tools_social` branch while market/news/fundamentals keep their tool loops.
- ✅ **FIXED follow-up** `config/research_provider_fallbacks.json` / `research/provider_orchestrator.py` / `dataflows/interface.py` — `earnings_transcripts`, `short_interest`, and `options_iv_flow` are first-class ticker-provider needs. `options_iv_flow` attempts supplemental public `dataflow:yfinance_options` evidence before the gap packet; `short_interest` attempts supplemental public `dataflow:yfinance_short_interest` metadata before the gap packet and rejects metadata-only responses with no real short-interest fields. All three routes are analysis-only and confirmation/downrank-only; options and short-interest are low-authority public supplemental sources, while transcripts are optional FMP/connector evidence with explicit gap fallback. `earnings_transcripts` now attempts optional FMP transcript evidence before the explicit analysis-only gap packet; missing keys, plan limits, or missing transcript text still produce `blocked=true` and `downrank_evidence=true` so overnight research accounts for the missing transcript instead of ignoring it.
- ✅ **FIXED follow-up** `evals/real_simulation_audit.py` — audit output paths are now precomputed and written once with self-referential `json_path` / `markdown_path`, instead of writing the same run twice.
- ✅ **FIXED follow-up** `evals/automation_health_audit.py` — `_run_id_for_path` now preserves microsecond-suffixed packet IDs such as `20260601-010550-274605`, ignores generic `latest/current` pointers, and keeps explicit packet `run_id` values authoritative.
- ✅ **FIXED follow-up** `evals/automation_health_audit.py` — harmless hourly no-action/no-issue duplicate packets are now de-noised when automation memory covers the latest packet; duplicates with submissions or issues remain degraded. Real proof: `results\automation_health\automation-health-audit-20260604-165711.json` has `ok_count=13`, `duplicate_count=0`, `submitted_order_count=0`, `issue_count=0`.
- ✅ **FIXED follow-up** `cli/main.py` — the stale `from cli.utils import *`
  wildcard is gone. Removing it exposed and fixed two hidden CLI output-name
  bugs, and the focused Alpaca CLI slices plus Ruff/compileall passed.
- ✅ **FIXED follow-up** `llm_clients/model_catalog.py` / `research/model_routing.py`
  — model routes now carry machine-readable `context_window_tokens`; overnight
  graph configs and telemetry packets expose the field without label parsing.

---

## 6. Cross-cutting themes

1. **Dead-but-implemented code.** SEC and EIA are now wired into the decision vendor path. Massive is now wired as a bounded analyst-facing OHLCV fallback adapter. ScrapingBee remains a research/enrichment connector until a bounded analyst-facing route is justified.
2. **Error-string vs. raise.** The dataflows fallback chain no longer treats known vendor error/no-data strings as successful evidence; this is now pinned by tests.
3. **Fail-open edges in otherwise fail-closed safety.** The verified live-gate null-entry-price edge is fixed. The alleged builder live-cap issue was withdrawn as an intentional policy choice.
4. **Unsafe example defaults.** The example risk envelope now defaults to `fixed_tranche`, not `autonomous_uncapped`.
5. **Subagent-grade analysis needs verification.** ~40% of the "P0" bug claims did not survive reading the actual code (see §7). The inventories and *gap* findings were reliable; the *bug* line-claims were not.

---

## 7. Cleared — agent claims that did NOT survive verification

These were flagged P0/P1 by subagents but are **not bugs**; documented so they're not chased:

- ✗ `execution/tiny_live.py:110-121` "clock unavailable → fail-open." **False.** `allowed = not issues` (line 136) and the unavailable-clock branch *appends an issue* → `allowed=False`. Already fail-closed.
- ✗ `graph/trading_graph.py:383-385` "debug merge drops messages." **False.** Graph runs with `stream_mode="values"`, so each chunk is a full state snapshot; the merge yields the correct final state.
- ✗ `graph/trading_graph.py:438` "`investment_plan` KeyError every run." **False.** The Research Manager writes `investment_plan`; the graph agent's scope excluded `agents/managers/` so it couldn't see the writer.
- ✗ `agents/analysts/*` "report overwritten with `''` on tool turns." **Overstated.** In normal flow the final (no-tool-call) turn overwrites the intermediate `""`; latent only (defensive `report or state.get(...)` still nice-to-have).
- ✗ `cli/main.py` "`reconcile_orcl_sell_state` imported twice." **False.** Imported once (line 86), used at line 4526.
- ✗ `brokers/alpaca.py:507` "live exposure cap not enforced in `build_order_pairs`." **Intentional, not a bug.** `tests/test_alpaca_execution.py::test_build_order_pairs_does_not_apply_old_live_exposure_cap` documents that the static live cap is deliberately bypassed here; live sizing is governed by the risk envelope + live gate. (Discovered by running the test after applying the "fix" — promptly reverted.)

---

## 8. Fix log (this pass)

**Applied and verified** (`tests/test_live_gate.py tests/test_alpaca_execution.py tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py tests/test_agent_intelligence_ledger.py tests/test_automation_health_audit.py tests/test_structured_agents.py` → **177 passed** after revert; targeted re-run **41 passed**):

1. **P0-1** `fundamentals_analyst.py:30` — removed the trailing comma; `system_message` is now a string.
2. **P0-3** `policy/live_gate.py:290` — loss-exit gate now only skips review on a *confirmed* non-loss (both proposed price and avg entry known, proposed ≥ entry); incomplete price provenance now requires review (fail-closed).
3. **P0-4** `config/risk_envelope.example.yaml` — example defaults to `fixed_tranche` (was `autonomous_uncapped`); the user's real envelope is untouched.
4. **P1-4** `pyproject.toml` — added `python-dotenv>=1.0.1` as a declared dependency.
5. **P1-5** `evals/automation_health_audit.py` — removed the dead, shadowed `_has_near_duplicate_artifacts` definition.
6. **P1-6** `evals/agent_intelligence_ledger.py:626` — `load_ledger` now skips malformed/schema-drifted JSONL lines instead of aborting the whole load.

**Reverted after testing:** P0-2 (`alpaca.py` live cap) — see §7.

**Applied and verified in follow-up pass** (`tests/test_official_dataflows.py tests/test_dataflows_interface.py tests/test_llm_client_config.py tests/test_agent_asset_context.py tests/test_self_heal_handoff.py tests/test_n8n_runner_policy.py` → **86 passed**):

7. **P1-1** `dataflows/interface.py` / `decision_vendor_adapters.py` / `sec.py` — wired SEC fundamentals via SEC ticker→CIK lookup plus companyfacts/submissions, and wired EIA as an energy/macro fallback source.
8. **P1-2/P1-3** `dataflows/interface.py` — fallback routing now treats known vendor `"Error..."` / `"No data..."` strings as failed evidence so yfinance and Alpha Vantage string failures cannot block backup sources.
9. **P1-7/P1-8** `orchestration/n8n_policy.py` / `orchestration/self_heal.py` — verified n8n rejects broker-capable non-submit jobs and pinned self-heal counter triggers as actionable high/medium severity.
10. **P1-9** `agents/analysts/fundamentals_analyst.py`, `agents/analysts/sentiment_analyst.py`, `agents/managers/research_manager.py`, `agents/managers/portfolio_manager.py` — threaded `asset_type` into remaining instrument-context call sites.
11. **P1-12/P1-13** `llm_clients/google_client.py`, `llm_clients/azure_client.py`, `.env.example` — Gemini 2.5 minimal gets a small positive thinking budget; Azure validates endpoint/version/deployment and documents required vars.

**Roadmap (remaining after follow-up fixes):**
- The §5 P2/P3 list.

Net: **13 verified P0/P1 fixes applied, 1 reverted as intentional policy, no focused test regressions.** The verification step cleared **6 false/overstated P0–P1 claims** before they could cause harm.

## 9. Foundation hygiene checkpoint

The repo-local P0 static-analysis hygiene from `docs/IMPROVEMENT_PROGRAM.md` is
now implemented and verified. `pyproject.toml` declares the `static-analysis`
group, Ruff runs with `E,F,I,B,UP,SIM`, broad mypy covers broker/policy/
execution/dataflow as the current baseline, and strict mypy covers the typed
frontier (`integration_registry`, execution clock/lock, live control, compact
policy packets, risk posture, default config, crawler policy). `requirements.txt`
is repaired for legacy pip users, and `backtrader` is removed because the
offline-validation path replays the live graph instead of adding a separate
engine.

Fresh proof:
- `uv run --no-sync --group static-analysis ruff check` → passed.
- `uv run --no-sync --group static-analysis mypy tradingagents/brokers tradingagents/policy tradingagents/execution tradingagents/dataflows` → passed, 52 source files.
- `uv run --no-sync --group static-analysis mypy --strict tradingagents/dataflows/integration_registry.py tradingagents/execution/clock.py tradingagents/execution/lock.py tradingagents/policy/live_control.py tradingagents/policy/packets.py tradingagents/policy/risk_posture.py tradingagents/default_config.py tradingagents/research/crawler_policy.py` → passed, 8 source files.
- `uv run --no-sync --with pytest python -m pytest -q tests/test_integration_registry.py tests/test_config_examples.py tests/test_n8n_runner_policy.py tests/test_real_simulation_audit.py tests/test_live_gate.py` → 63 passed.

This does not close the roadmap. The remaining architecture work is still:
the §5 P2/P3 items and the improvement-program P2/P3/P5 workstreams. P4's
MiroFish handoff availability gate has since been met; it is now an
advisory-only validation/outcome-labeling lane, not a waiting gate.

## 10. Decision-quality checkpoint

The P2 program now has a first analysis-only report slice. It does not run
orders and does not replace the future walk-forward harness; it makes replay
readiness measurable now. `tradingagents research decision-quality-report`
writes a `ResearchBatchRunPacket` with:
- a point-in-time audit table for dataflow routes,
- point-in-time gap/mixed/live-only status counts,
- shrinkage-based rating-probability calibration from resolved Agent
  Intelligence Ledger rows,
- explicit `execution_authority="none"` and forbidden order effects.

Latest packet:
`results\research_batches\research-batch-research-batch-4b94859e548b4221ac1b974fc8b27560.json`.
It currently shows 0 point-in-time gaps, 0 mixed routes, public
Reddit/StockTwits marked `live_only_unscored_in_replay`, and insufficient
resolved rating forecasts, so priors stay unchanged. The Google News RSS
latest-fetch gap was closed by filtering RSS items by `pubDate` inside the
requested `start_date` / `end_date` window and threading those dates through
the decision adapter. EIA/Treasury macro routes were moved out of the mixed
bucket by threading monthly EIA `start`/`end` windows and Treasury
`record_date` filters from `curr_date`. SEC/FMP/EODHD rendered fundamentals now
drop future-dated rows and date-keyed sections after `curr_date`, while raw
vendor packets remain archived as latest evidence. Public social routes remain
advisory live/recent evidence unless a timestamped archive is added, so replay
excludes them instead of pretending they are point-in-time fixtures. Verified
with 59 focused official-dataflow / decision-adapter / replay-ablation tests,
repo Ruff, broad mypy, and compile checks. Remaining P2 work: the >=10-name
fixed-as-of walk-forward graph replay.

The first walk-forward replay harness now exists as
`tradingagents research walk-forward-replay --fixture-path <json>`. It accepts
fixed-as-of rows, scores deterministic and advisory arms, and leaves missing
overlays unavailable instead of inventing social/news/Deep Research history.
Fixture proof:
`results\research_batches\research-batch-research-batch-8691b073a65b4372ac1da19341f2e563.json`
from `tests\fixtures\walk_forward_replay_sample.json`, with 10 rows,
`sample_floor_met=true`, `execution_authority="none"`, baseline accuracy
`0.7000`, TradingAgents advisory overlay accuracy `0.9000`, and no order-capable
effects. This closes the CLI/scoring harness slice; remaining P2 work is the
captured historical graph-decision dataset/generator.

The captured-decision generator slice is now present:
`tradingagents research walk-forward-fixture-from-overnight --overnight-packet
<packet.json> --returns-path <returns.json>`. It converts overnight
`ticker_results` plus supplied later returns into replay fixture rows, tags
full-graph/`status=ok` rows as `tradingagents_advisory_overlay`, keeps fallback
rows baseline-only, and skips missing returns with a reason. Proof:
`results\research_batches\walk_forward_fixture_from_overnight_sample.json`
(`row_count=2`, `skipped_count=1`) followed by replay packet
`results\research_batches\research-batch-research-batch-e09e0e205e8e4f72a915ed0bfe939996.json`
(`sample_floor_met=true` for the 2-row proof, `execution_authority="none"`).
Remaining P2 work: gather real later return rows for captured overnight packets
and scale the replay cohort before promotion decisions.

The later-return collector is also present:
`tradingagents research walk-forward-returns-from-overnight --overnight-packet
<packet.json>`. It uses the ledger-style yfinance lookup by default and supports
deterministic `--price-rows-path` proof input. Proof artifacts:
`results\research_batches\walk_forward_returns_from_overnight_sample.json`,
`results\research_batches\walk_forward_fixture_from_collected_returns_sample.json`,
and replay packet
`results\research_batches\research-batch-research-batch-58e875ebe0b74df28c5b1349f886ecda.json`.
All remain analysis-only; missing prices/returns are skipped with explicit
reasons instead of filled.

Real captured-packet proof is now present too. A 3-trading-day yfinance
collector run over six June 1 overnight packets wrote
`results\research_batches\walk_forward_returns_real_20260601_h3.json`
(`row_count=70`, `skipped_count=0`, benchmark `SPY`), fixture generation wrote
`results\research_batches\walk_forward_fixture_real_20260601_h3.json`
(`row_count=210`), and replay wrote
`results\research_batches\research-batch-research-batch-ee09089c106b4902a776046dd1bfd87a.json`
with `sample_floor_met=true`, deterministic directional accuracy `0.4048`,
false-positive rate `0.1667`, average Brier `0.2555`, average relative return
vs benchmark `0.2481`, and average action-relative return `0.0409`.

## 11. Self-heal dedupe checkpoint

P3 now has a durable safe-plane dedupe slice. `results\self_heal\signature-state.json`
records root-cause signatures shared by self-heal handoffs and plans. Repeated
handoff triggers are still visible in the packet, but already-recorded
signatures no longer request another repair chat. Self-heal plans also dedupe
from this durable state, not only from `plans/latest.json`.

Latest real proof:
`results\self_heal\plans\self-heal-plan-20260604-005437.json` executed one
allowlisted compact-context refresh, verified it, deduped one prior connector
signal, and kept `can_submit_orders=false`, `execution_authority="none"`, no
email, and no automation-status mutation. Focused verification: 45 self-heal /
automation-health / n8n tests passed; Ruff, broad mypy, and strict frontier mypy
passed.

Follow-up proof:
`results\automation_health\automation-health-audit-20260604-061458.json` shows
the health monitor no longer turns paused/manual automation evidence into
duplicate-run blockers. Paused hourly/paper jobs use `expected_run_count=0`,
rolling premarket briefs are no longer counted as overnight-planning artifacts,
and timely self-heal duplicate history is de-noised when the latest actionable
handoff receives a verified plan inside the SLA. The packet has
`duplicate_count=0`, `timeliness_issue_count=0`, and self-heal follow-up lag
`33s`. Focused verification: 60 automation-health / compact-context / n8n tests
passed; Ruff passed for the touched automation-health files.

## 14. Compact high-traffic CLI output checkpoint

P5 now has compact stdout lanes for four high-traffic automation commands plus
the source-quality research-control-plane command:
`alpaca plan-overnight --json-output --compact-json-output`,
`alpaca premarket-brief --json-output --compact-json-output`, and
`alpaca supervise-hourly --dry-run --json-output --compact-json-output`, plus
`alpaca supervisor-daily-report --json-output --compact-json-output`, and
`research source-quality-review --json-output --compact-json-output`.
Each compact payload writes a schema-tagged summary with `raw_packet_path` plus
counts, top symbols, quality/status fields, and raw-field group pointers while
leaving the raw JSON packet unchanged. This lets n8n/hooks/agents consume compact
context by default without losing access to full evidence when flags require a
drilldown. Daily-report compact mode is the one exception that creates the raw
report packet first, because the prior daily-report command printed JSON without
persisting it.

Latest real hourly dry-run proof:
`results\hourly_supervisor\compact_probe\hourly-supervisor-20260604-040457-404346.json`
was written with `decision=hold`, `submitted_count=0`, `issue_count=0`, and live
budget `mode=autonomous_uncapped`. Focused hourly verification passed with 11
`supervise_hourly` tests; compact helper/CLI tests, Ruff, and CLI compile checks
also passed. Latest real daily-report compact proof:
`results\daily_reports\compact_probe\supervisor-daily-report-20260603-231950-817954.json`
was written with `body_summary.char_count=1998`, `ranked_candidates=35`,
`top_candidate=GOOGL`, and `execution_board.can_submit_orders=false`. Focused
daily verification passed with 4 daily-report tests.

Measured audit proof:
`alpaca compact-output-audit --json-output` wrote
`results\token_efficiency\compact-output-audit-20260603-233723-460063.json`
and `.md`, measuring raw `535,462` bytes versus compact `6,846` bytes across
hourly, overnight, premarket, and daily report packets. That saves `528,616`
bytes, and every row is `lossless_by_reference=true`. Remaining P5 compact work
is editor-side execution of the n8n Evaluation Trigger workflow when a visible
quality-score run is needed, plus compact adoption for any newly added
high-volume automation command.

2026-06-05 source-quality compact proof: direct CLI compact run wrote raw review
`results\source_quality\source-quality-review-20260605-092148.json`; the n8n
bridge job wrote `results\source_quality\source-quality-review-20260605-092211.json`
and returned parsed schema `compact_source_quality_review_v1` with
`source_count=250`, `stale_count=88`, `stale_needs_refresh_count=0`, and
`submit_capable=false`. Focused verification passed with 46 source-quality/n8n
tests, Ruff passed on the touched files, process review
`results\process_reviews\process-review-20260605-092402.json` reported
`unchecked_step_count=0`, and full pytest passed with `885 passed, 1 skipped,
9 warnings, 75 subtests passed`.

2026-06-05 n8n evaluation compact/sync proof: `research
n8n-evaluation-dataset --json-output --compact-json-output` now emits
`compact_n8n_evaluation_dataset_v1` with row/job/edge counts and artifact paths
instead of dumping all evaluation rows to stdout. The dataset now has 23
columns, including six writable actual-output columns for n8n Set Outputs:
`actual_http_status`, `actual_status`, `actual_json`, `actual_quality_score`,
`actual_checked_at`, and `actual_error`. Source control now includes
`TA · Built-in Automation Evaluation`, a native n8n Evaluation Trigger workflow
with HTTP runner call, Code metrics, Evaluation Set Outputs, and Evaluation Set
Metrics nodes. Direct CLI proof wrote
`results\n8n_evaluations\n8n-evaluation-dataset-20260605-123501-987045.json`;
the current dataset proof is
`results\n8n_evaluations\n8n-evaluation-dataset-20260606-204956-806412.json`
with 183 rows across 20 allowlisted jobs.
Local n8n at `http://localhost:5678` imported the built-in workflow successfully;
`n8n list:workflow` returned
`taBuiltInAutomationEvaluation|TA · Built-in Automation Evaluation`. The local
n8n Data Table was refreshed through the public API using a temporary SQLite-key
copy without printing or storing the key. Current redacted sync proof
`results\n8n_evaluations\n8n-api-sync-20260606-205308-805632.json` reports
`expected_row_count=183`, `final_row_count=183`, `row_count_matches=true`,
`column_count=23`, and `api_key_redacted=true`. Workflow sync proof
`results\n8n_evaluations\n8n-workflow-sync-20260606-210202-886336.json`
created the missing inactive observer workflows in local n8n. A real
`n8n execute` probe confirmed that CLI execution
is not the correct acceptance gate for Evaluation Trigger workflows: the first
probe hit the running task-broker port and the second, with a separate broker
port, failed with `Missing node to start execution` because Evaluation Trigger is
not an Execute Workflow Trigger. Focused n8n/real-simulation tests passed with
58 tests.
Compact context now carries the same n8n proof in
`results\_context\latest-summary.json` as `n8n_evaluation_dataset` with
`row_count=183`, `column_count=23`, `has_actual_output_columns=true`,
`sync_status=ok`, `sync_current_row_count_matches=true`,
`workflow_sync_status=ok`, and redacted API-key fields; raw n8n packets are only
a drilldown target when those compact fields fail. Focused context/n8n proof
passed with 76 tests, and
the full post-change suite passed with 896 tests, 1 skipped live-key test,
9 warnings, and 75 subtests.
A redacted native-run API probe with the local SQLite API key returned `404` for
the public `/api/v1` test-run routes and `401` for the internal `/rest`
test-run routes, confirming that starting a built-in n8n Evaluation Trigger run
still requires an authenticated editor/evaluations UI session on this n8n
version.

## 12. Compact-context field provenance checkpoint

P5 now has its first lossless proof artifact. `scripts/automation_context_snapshot.py`
writes `results\_context\field-provenance.json` alongside
`latest-summary.json`, `latest-flags.json`, and `context-manifest.json`.
The provenance file gives every compact `latest_packets[*]` field a
machine-readable pointer back to either the raw packet field, a raw file metric,
a drilldown-rule derivation, or an explicit missing-packet marker. Raw result
packets remain unchanged and authoritative.

Fresh proof:
full regression passed before this slice with 703 tests, 1 skipped live-key
test, 9 warnings, and 75 subtests. The P5 focused gate then passed with 58
automation-context / hook / n8n tests, plus Ruff, broad mypy, and
`py_compile scripts/automation_context_snapshot.py`.

## 13. MiroFish structured-prior checkpoint

P4 now has the accepted final MiroFish handoff for `report_9c77ca2557ae`.
`tradingagents\research\mirofish_handoff.py` normalizes machine-readable
scenario probabilities, ticker attention maps, category attention maps,
retail-flow hypotheses, validation tasks, false-signal filters, source-artifact
pointers, review-packet zip, and the final acceptance decision. The overnight
context, compact context snapshot, CLI status command, and n8n runner expose
bounded advisory versions for morning research jobs.

The Stage 04 `full_report.md` is also read and distilled into the compact
AI-bot-copycat / institutional-liquidity filter: treat social and prompt-bot
momentum as false-signal risk until independent volume, broker/API execution,
options liquidity, and institutional participation confirm durable flow. The
parser now preserves the prose section `AI-Bot Correlation and Institutional
Liquidity Adaptation` as `full_report_ai_bot_liquidity_summary`, including the
warning that obvious AI-bot convergence can create false-positive crowding while
institutional desks fade, absorb, or briefly amplify novice flow to manage
order-flow toxicity. The valid advisory window is `2026-06-04 through
2026-06-13`, with refresh required before tomorrow premarket, at market open,
during macro/rates windows, and after material broker/API rule or status-page
updates.

Full-report provenance is explicit rather than assumed: the status packet now
stores every discovered `full_report.md` candidate in
`full_report_candidate_reports` with size and SHA-256. The selected canonical
backend report hash is
`f118ff9a38464f1687e205be426395c0b0867ae7e26f3972c1f5d3f78061e5df`; the
explicit Downloads copy hash is
`d24e9841b5f0533eab680b7eb8a33851b0ea01e99a245f7cd7d49fd8621af7af`.

Execution authority remains `none`: MiroFish priors are analysis-only and do
not create, size, submit, or promote orders. Current proof:
`results\mirofish_handoff\latest.json` has `final_handoff_available=true`,
`full_report_highlight_available=true`, and `can_submit_orders=false`; n8n
`mirofish_handoff_status` returns `submit_capable=false`.

## 15. Social date-window checkpoint

The P2/P3 social-date roadmap slice is now fixed. `get_current_date()` uses the
UTC date; the sentiment decision adapters pass `start_date` / `end_date` through
to StockTwits and Reddit; and those public recent-message fetchers filter
returned items by timestamp before rendering analyst context. This keeps noisy
copycat social evidence from leaking into a point-in-time prompt under the wrong
window. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_safe_ticker_component.py tests/test_reddit_dataflow.py
tests/test_decision_vendor_adapters.py` passed with 24 tests; targeted Ruff
passed on the touched dataflow and test files.

## 16. BEA macro-window checkpoint

The BEA macro roadmap slice is now fixed. `get_bea_macro_context()` uses the
same calendar-year window helper as BLS and fetches every year in the requested
lookback window instead of only `curr_date.year`. The wrapper does separate
per-year fetches rather than assuming BEA accepts a comma/range year syntax.
Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_decision_vendor_adapters.py tests/test_official_dataflows.py
tests/test_dataflows_interface.py` passed with 56 tests; targeted Ruff and
py_compile passed.

## 17. News insider-tool checkpoint

The news analyst now receives the insider-transactions tool it was already
supposed to share with the graph ToolNode. `create_news_analyst` imports and
binds `get_insider_transactions`, and the system prompt names
`get_insider_transactions(ticker)` as the stock-specific insider buying/selling
confirmation route. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_agent_asset_context.py tests/test_graph_tool_routing.py
tests/test_dataflows_interface.py::test_decision_path_vendor_map_exposes_promoted_research_sources`
passed with 7 tests; targeted Ruff passed.

## 18. Supervisor missing-price close-order checkpoint

The live supervisor no longer falls back to `Decimal("1")` when closing a live
position. If an otherwise approved loss exit lacks positive `current_price`, it
returns `decision="loss-review"` with no actions and asks BOARD/manual review to
refresh broker price data. If a profit-taking sell lacks positive
`current_price`, it returns `decision="profit-review"` with no actions. This
keeps both "sell the spike" and loss-exit paths fail-closed on stale broker
position data. Focused proof:
`uv run --no-sync --with pytest python -m pytest -q tests/test_alpaca_supervisor.py
tests/test_live_gate.py` passed with 73 tests; compact hourly CLI proof passed
with 2 tests; targeted Ruff, mypy for `alpaca_supervisor.py`, and py_compile
passed.

## 19. MiroFish Deep Research report-33 checkpoint

The MiroFish ingestion path now has a second advisory overlay from
`C:\Users\Corbin\Downloads\deep-research-report (33).md`. The parser treats it
as a Deep Research review of the MiroFish report, not as a trade instruction.
It extracts a compact `deep_research_report_33` block with macro-first context,
stock-selection biases, risk controls, validation requirements, limitations,
and any parsed directional/practical decision tables. The overlay is visible in
CLI JSON, the source context packet, overnight research-context summaries,
compact context snapshots, and n8n `mirofish_handoff_status`.

Operational interpretation for June 4-13: the system should avoid obvious
AI-bot copycat crowding, require broker/flow/options/price confirmation before
treating the PDT/rule-change thesis as durable, prefer validated relative
strength over heroic directional bets, and be cautious on QQQ/semis/crowded AI
beta unless post-data confirmation appears. Execution authority remains `none`;
this overlay only affects research priors, validation checklists, and false-
signal filters.

Proof: `research mirofish-handoff-status --json-output` reports
`deep_research_review_available=true`, `deep_research_review_report_id=
deep_research_report_33`, and `can_submit_orders=false`. Focused tests passed
in the 12-test MiroFish/n8n/overnight batch, and the later department sweep
passed with 156 tests.

Follow-up: the advisory overlay now reaches the overnight ranking path instead
of stopping at status/report packets. `alpaca plan-overnight` enriches market
rows with MiroFish/report-33 tags before `build_candidate_signals(...)` scores
them. Unconfirmed social/prompt-bot copycat attention is downranked, and
crowded AI-beta symbols during macro-event risk are penalized until independent
confirmation appears. This preserves the buy-dip/sell-spike and green-spike
anti-chase rules while making the "AI-bot correlation and institutional
liquidity adaptation" warning actionable in stock selection. The overlay
remains advisory-only: no order creation, sizing, promotion, or live-gate
bypass. Focused proof covers prior tagging, controlled-dip preference, and
bot-copycat downranking.

2026-06-05 follow-up: the report-33 overlay now includes the positive relative
trade side, not only the negative crowded-growth filters. The enrichment layer
sets `deep_research_positive_relative_bias` for Dow/quality/energy/defensive
stock rows when the Deep Research review's positive-bias map is present.
Candidate scoring gives that flag a modest boost only for non-spike,
non-falling-knife rows, so the pipeline favors controlled dips and steadier
relative-strength candidates without overriding the anti-chase rule. This is
still an advisory ranking input only; it creates no trade intent, size,
promotion, or execution authority. Fresh real proof after the patch:
MiroFish/report-33 status packet
`results\mirofish_handoff\research-intel-research-intel-670b65db8e334d2ebf2ad8edb1e04d4a.json`,
overnight verifier
`results\overnight_system_verification\overnight-system-verification-20260605-040252.json`
with `overall_status=pass`, source-quality review
`results\source_quality\source-quality-review-20260605-090250.json` with
`stale_needs_refresh_count=0`, process review
`results\process_reviews\process-review-20260605-090324.json` with
`unchecked_step_count=0`, and full pytest `883 passed, 1 skipped, 9 warnings,
75 subtests passed`.

Latest parser fix: qualitative MiroFish telemetry is no longer ignored when the
report names a risk index without a numeric value. The handoff parser
canonicalizes variants such as `AI_bot_copycat_index` and assigns conservative
elevated advisory pressure to observed-but-nonnumeric indices. Fresh real status
`results\mirofish_handoff\latest.json` now returns
`mirofish_advisory_gate_action=suppress` with `broker_friction`,
`macro_override`, and `attribution_error` triggered. This is the intended
architecture: report warnings become pre-action validation pressure, not direct
trade authority.

## 20. Overnight original-graph and live circuit-breaker checkpoint

The overnight planner had current packets, but it had degraded to fallback-only
when Windows Ollama was unavailable and Mac `deepseek-r1:14b` was intentionally
kept as a low-cost helper lane. The architecture audit should therefore
classify the old overnight issue as a model/runtime route quality warning, not
as a missing packet. `alpaca verify-overnight-system` now adds
`overnight_original_graph_execution` and only treats the original graph lane as
healthy when at least one graph run completes successfully.

Follow-up: the active overnight automation now explicitly requests the
credentialed Google graph route (`--overnight-llm-provider google`, quick
`gemini-2.5-flash-lite`, deep `gemini-2.5-flash`) so graph execution no
longer depends on Windows Ollama being healthy. Explicit non-Ollama routes
clear inherited Ollama backend URLs and are not auto-disabled by the local
Ollama probe. The planner now records
`full_graph_attempt_count` and `full_graph_success_count` separately, and the
verifier only treats the original graph lane as healthy when at least one graph
run completes successfully. Real no-write OpenAI probe
`results\overnight_plans\openai_graph_probe\overnight-plan-20260604-182040-000000.json`
proved the route attempts the graph and then falls back cleanly when credentials
are missing: `full_graph_attempt_count=1`, `full_graph_success_count=0`,
`graph_failure_count=1`, submitted 0 orders. Real no-write Google probe
`results\overnight_plans\google_graph_probe\overnight-plan-20260604-182923-000000.json`
proved a successful graph completion: `full_graph_attempt_count=1`,
`full_graph_success_count=1`, `graph_failure_count=0`, submitted 0 orders, top
candidate AMD from `method=full_graph`.

Full route proof: the real Google-routed overnight command completed at
`results\overnight_plans\overnight-plan-20260604-184407-000000.json` with
zero submitted orders, top candidates `KO`, `HD`, `AMD`, `TXN`, `PEP`,
`full_graph_attempt_count=3`, `full_graph_success_count=3`,
`fallback_count=32`, and `graph_failure_count=0`. It also wrote creator
workflow packets for the successful original-graph symbols `KO`, `HD`, and
`AMD`. The refreshed premarket brief
`results\premarket_briefs\premarket-brief-20260604-185159-000000.json` links
to the same overnight plan with top symbol `KO`, no stale warnings, and no
unresolved blockers. The latest verifier packet
`results\overnight_system_verification\overnight-system-verification-20260604-140301.json`
has `overall_status=pass`.

Prior-feed verifier follow-up: the planner now writes the compact
`overnight_prior_feed_v1` handoff artifact and `alpaca verify-overnight-system`
audits it with an `overnight_prior_feed` check. Missing pointers in old packets
warn, but unreadable or unsafe pointed artifacts fail. Current verifier proof
`results\overnight_system_verification\overnight-system-verification-20260604-180544.json`
has `overall_status=pass`; the latest full overnight packet carries the prior
feed pointer and premarket enriches skinny prior-feed refs from the pointed JSON
when old packets are missing guardrail fields.

Live rerun proof: `results\overnight_plans\overnight-plan-20260604-223730-000000.json`
clears the transitional warning with three successful original graph runs,
32 fallback tickers, zero graph failures, zero submissions, and prior-feed
`results\overnight_plans\research_context\overnight-prior-feed-20260604-222820.json`.
`results\premarket_briefs\premarket-brief-20260604-224631-000000.json` now
points the morning brief at top symbol `TXN` with no stale warnings or blockers,
and refreshed brief `results\premarket_briefs\premarket-brief-20260604-230506-000000.json`
carries the prior-feed proof with `analysis_only=true`, `execution_authority=none`,
and forbidden effects including `submit_order`. Pre-open hourly validation carries
that compact prior-feed summary into hourly evidence; outside the pre-open window
the real closed-session dry-run
`results\hourly_supervisor\hourly-supervisor-20260604-232011-923105.json`
properly stayed `hold` with zero submissions/issues. Verifier
`results\overnight_system_verification\overnight-system-verification-20260604-180544.json`
has `overall_status=pass`. During the provider refresh, Crawlee reused an old
QCOM queue for later symbols because `CRAWLEE_STORAGE_DIR` was set with
`setdefault`; the runner now uses per-run storage and restores the prior env var.

Final rerun proof: the latest explicit Google original-graph command completed
at `results\overnight_plans\overnight-plan-20260605-040719-000000.json` with
top candidates `KO`, `IBM`, `HD`, `CRM`, `QCOM`, three successful original
TradingAgents graph runs, 32 fallback-scored tickers, zero graph failures, and
zero submissions. Provider bundles refreshed for `KO`, `IBM`, and `HD`; fresh
premarket brief `results\premarket_briefs\premarket-brief-20260605-040926-000000.json`
has no blockers/stale warnings; verifier
`results\overnight_system_verification\overnight-system-verification-20260604-231510.json`
passes. The return-row generator now writes `generated_at`, `analysis_only`,
and `can_submit_orders=false` metadata; after regenerating
`results\research_batches\walk_forward_returns_real_20260601_h3.json`, source
quality `results\source_quality\source-quality-review-20260605-063725.json`
has all stale sources safe/downranked, `missing_or_invalid_count=0`, and compact
context has no raw-packet flags.

Model telemetry now distinguishes current route state from historical failures.
The 2026-06-07 follow-up corrected the stale local-helper diagnosis: Windows
Ollama is installed and can be auto-discovered at `http://127.0.0.1:11434/v1`
when no operator env var is set. The CLI probes `/api/tags`, and if the default
`gpt-oss:20b` is absent with no explicit model override, it uses the installed
tag for that run. Current proof
`results\model_telemetry_reports\model-telemetry-report-20260607-060331-009792.json`
shows `windows_local_ollama` as `success` with
`tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest`; Mac
`mac_ollama_research_mule` remains optional/degraded because
`http://macbook-pro.tail37edd7.ts.net:11434/api/tags` timed out. Compact
context and n8n should treat this as "one local helper selected, one optional
helper degraded," not as an overnight research blocker.

2026-06-07 verification follow-up: the default research-batch context was
refreshed after Windows helper auto-discovery. Current compact research batch
`results\research_batches\latest-compact.json` has
`advisory_missing_gates=[]`, `at_least_one_local_worker_ready=true`,
`research_quality_high_enough=true`, and no blockers. The real overnight
verifier
`results\overnight_system_verification\overnight-system-verification-20260607-010942.json`
passes with active overnight automation, 3/3 original TradingAgents graph
successes, 40 ranked candidates, top symbol `XOM`, and zero submissions.

The remaining compact flags are intentionally order-adjacent review flags, not
overnight/model/data freshness failures. Latest loss-review evidence
`results\loss_review_evidence\source-evidence-source-evidence-9343e9daa75949868f6caa9a6140a4a3.json`
and BOARD review
`results\execution_board\execution-board-review-20260607-061102.json` both
match the latest hourly packet
`results\hourly_supervisor\hourly-supervisor-20260607-060828-521016.json`.
They record 0 hard violations and 0 submitted orders while keeping the TSM loss
exit blocked until allowed reason/source, thesis status, confidence, and a
tradeable session are available. This preserves the requested sell/buy
independence: do not pair loss sells with replacement buys, do not chase green
spikes, and allow new buys only as separate controlled dip/support setups.

The live gate also now enforces the parsed risk-envelope circuit-breaker fields
for new live buys. `daily_loss_halt_usd` and `max_drawdown_halt_pct` block new
buy attempts even when `live_budget_mode=autonomous_uncapped`; profit-taking
sells are still allowed, and loss-taking sells still require structured
loss-exit evidence.

Final broker-friction follow-up: the remaining EDGE-01-style buying-power gap is
closed at the final live-submit guard. `evaluate_go_live_guard(...)` now
requires current broker `buying_power` for live buy actions, and
`validate_supervisor_live_submit_allowed(...)` receives the live account
snapshot from both submit-capable CLI paths. Missing buying power blocks a new
live buy; a proposed live buy above broker buying power blocks; sells are
independent of the buying-power check. This honors the uncapped live-budget
policy as "no repo dollar cap" while still respecting actual broker capacity.

Overnight scheduler follow-up: the apparent "overnight research has not
completed" failure was a control-plane state problem, not a missing research
artifact. The automation was found `PAUSED` during the afternoon controller
window, then restored to `ACTIVE`. `alpaca verify-overnight-system` now includes
`automation_status:tradingagents-overnight-planning`, so this state drift fails
verification directly. Latest real verifier after the patch:
`results\overnight_system_verification\overnight-system-verification-20260604-192530.json`,
`overall_status=pass`, expected/actual automation status `ACTIVE`, 3/3 graph
successes, 32 fallbacks, and no graph failures.

Prior-feed integrity follow-up: the verifier now rejects a modern overnight
packet whose compact prior-feed reference points outside that packet's
`research_context` directory or disagrees with the loaded JSON on schema,
packet/block counts, analysis-only status, or execution authority. This closes
a stale/foreign-context silent pass mode while still allowing truly old packets
to warn when they predate prior-feed pointers.

Submit-helper boundary follow-up: `execute_order_pairs(...)` is no longer a
direct live-order footgun for imported callers. It returns failed issues unless
the caller passes `live_guard_approved=True`; the legacy CLI path passes that
flag only after `validate_supervisor_live_submit_allowed(...)` has already
accepted the action set. This adds a library-level fail-closed check underneath
the existing CLI source-order tests.

Broker-clock/session follow-up: the remaining local-session-only submit risk is
closed for tiny-live hourly submits. The operational guard still checks broker
clock skew, and now also requires broker `clock.is_open=true` for regular-hours
orders. If an action is explicitly extended-hours, the broker calendar must
confirm the current date is a trading day; otherwise the submit is blocked. This
addresses holiday/closed-session drift without changing PDT policy or enabling
n8n/hook order authority.

Proof packets and tests:
- `results\overnight_system_verification\overnight-system-verification-20260604-140301.json`
  has `overall_status=pass` and confirms
  `overnight_original_graph_execution.status=pass`.
- `uv run --no-sync --with pytest python -m pytest -q
  tests/test_alpaca_cli.py::test_plan_overnight_writes_fallback_rankings_when_graph_fails
  tests/test_alpaca_cli.py::test_overnight_graph_config_honors_explicit_openai_without_backend
  tests/test_alpaca_cli.py::test_plan_overnight_runs_explicit_openai_graph_without_backend
  tests/test_alpaca_cli.py::test_overnight_graph_config_uses_mac_helper_metadata_when_windows_is_down
  tests/test_alpaca_cli.py::test_plan_overnight_disables_full_graph_when_only_mac_helper_is_healthy
  tests/test_alpaca_cli.py::test_verify_overnight_system_warns_when_original_graph_requested_but_disabled
  tests/test_automation_context_snapshot.py::test_snapshot_summarizes_creator_workflow_refs_inside_overnight_packet`
  passed with 7 tests.
- `uv run --no-sync --with pytest python -m pytest -q tests/test_live_gate.py
  tests/test_execution_safety.py` passed with 33 tests.
- Full `tests/test_alpaca_cli.py` passed with 72 tests; broader department
  sweep passed with 156 tests.

## 21. Provider-route repair checkpoint

The overnight research pipeline no longer has to treat the most useful missing
ticker bundle routes as vague "unsupported" gaps. The local orchestrator now has
explicit analysis-only fetch paths for:

- `official_cache`: reuses cached source evidence packets without rereading raw
  full reports by default.
- `yfinance`: writes compact quote/price context for ticker bundles.
- `sec_edgar`: resolves ticker-to-CIK and writes SEC fundamentals/submissions
  context.
- `reddit_watchlist`: writes read-only social-attention context from configured
  watchlists.

Real KO/HD/AMD ticker bundle proof after the repair:

- `results\research_evidence\source-evidence-source-evidence-32051257a7b14911a6be98bdb6f1fdf0.json`
  for `KO`
- `results\research_evidence\source-evidence-source-evidence-61eacab2639b45c7ac2cf08043168f7a.json`
  for `HD`
- `results\research_evidence\source-evidence-source-evidence-060370eae0f843579b45cc4e6e47ce17.json`
  for `AMD`

Each proof bundle wrote 12 analysis-only packets covering `official_cache`,
`reddit_watchlist`, `alpaca_news`, `google_news_rss`, `yfinance`, `sec_edgar`,
`finnhub`, `tiingo`, and `fmp`. `official_cache` also now records a
`cache_miss` route attempt instead of masquerading as an unsupported source when
the cache is empty.

Follow-up Crawlee repair: `crawlee` is now supported as a separate
`crawler_research` evidence need in default ticker bundles. It uses
deterministic ticker-to-target policy only, currently the static SEC company
endpoint allowlisted to `sec.gov`, so the repo does not invent arbitrary crawl
targets from ticker symbols. The first real run exposed a broken environment
dependency (`greenlet` imported as a namespace with no `greenlet.greenlet`);
`uv pip install --python .\.venv\Scripts\python.exe --reinstall greenlet==3.2.3`
repaired the venv, and `crawler_runtime_status()` now reports
`greenlet_available` so automation self-heal can catch this before a crawl.

Real default-bundle proof after the repair:

- Summary:
  `results\research_evidence\source-evidence-source-evidence-936ac99338724c81ace3517511764085.json`
- Source packet:
  `results\research_evidence\source-evidence-source-evidence-090551d446f04343b05a16cc96028bac.json`
- Default evidence needs:
  `market_news,quote_price_context,fundamentals_profile,crawler_research`
- Result: `crawler_status=success`, `quality=medium`, fetched
  `https://www.sec.gov/cgi-bin/browse-edgar?CIK=KO&owner=exclude&action=getcompany`,
  title `EDGAR Search Results`, `blocked=false`, and
  `execution_authority=none`.

Follow-up broker-snapshot repair: `broker_snapshot` now comes from an
already-sanitized hourly supervisor artifact, not a direct broker API call and
not a ticker-only fetcher. The provider route reads the newest
`results/hourly_supervisor/hourly-supervisor-*.json` packet (or an explicit
`--broker-snapshot-dir` file/directory), extracts account summaries,
symbol-specific position/open-order context, ranked-candidate context, and
counts, and omits raw broker/order IDs. The route is read-only,
`execution_authority=none`, uses zero cache TTL, and does not stale-fallback on
account context.

Real broker-snapshot proof after the repair:

- Source packet:
  `results\research_evidence\source-evidence-source-evidence-f5c7d62d87ca4be0901db1a13d67c0cb.json`
- Summary packet:
  `results\research_evidence\source-evidence-source-evidence-e18ebac6c69f40fdba377c26660a4391.json`
- Source supervisor packet:
  `results\hourly_supervisor\hourly-supervisor-20260604-201930-941804.json`
- Result for `KO`: `submitted_order_count=0`, no live/paper KO position, no KO
  open orders, ranked candidate reason `controlled dip`, `read_only=true`, and
  `execution_authority=none`.

The remaining unsupported routes are intentionally scoped rather than
forgotten. Twitter/X stays blocked until Docker MCP `twitter-research` has a
repo-readable evidence bridge, and its current provider route now writes a
blocked packet instead of silently disappearing.

Follow-up social-provider repair: `reddit` provider fallback now uses the
repo-local public Reddit dataflow (`dataflow:reddit_public`) for
`social_sentiment` only, preserving the regular news route for `market_news`.
The provider can therefore capture low-authority social context when available
and still degrade when public Reddit blocks a subreddit. Twitter/X now produces
an explicit blocked `twitter` source packet until the Docker MCP bridge exists.

Real social-provider proofs:

- Public Reddit source packet:
  `results\research_evidence\source-evidence-source-evidence-068230c2d7054c3b9d6d8569d719d566.json`
- Public Reddit summary:
  `results\research_evidence\source-evidence-source-evidence-12e04870b2c54213b3f127c9d1221c97.json`
- Twitter/X blocked source packet:
  `results\research_evidence\source-evidence-source-evidence-f283adc9db7244ff95f7dfde34ade5b4.json`
- Twitter/X summary:
  `results\research_evidence\source-evidence-source-evidence-7130c49642a64cec967304a9349c6b0e.json`
- Result: both routes remain analysis-only; Reddit route is honest
  `dataflow:reddit_public`; Twitter/X failure is visible to source-quality and
  self-heal as a connector bridge gap.

Fresh source-quality proof after the provider/crawler rerun:
`results\source_quality\source-quality-review-20260604-200123.json` reported
`source_count=250`, `stale_count=43`, `stale_downrank_count=43`, and
`stale_needs_refresh_count=0`.

Fresh source-quality proof after broker-snapshot/local-source profiles:
`results\source_quality\source-quality-review-20260604-202541.json` reported
`source_count=250`, `stale_count=42`, `stale_downrank_count=42`,
`stale_needs_refresh_count=0`, and reduced unknown classifications to `5` by
explicitly profiling `broker_snapshot`, `ticker_provider_orchestrator`,
`official_cache`, and `crawlee`.

Fresh source-quality proof after social-provider routing:
`results\source_quality\source-quality-review-20260604-203820.json` reported
`source_count=250`, `stale_count=38`, `stale_downrank_count=38`,
`stale_needs_refresh_count=0`, and `unknown=3`.

2026-06-05 source-quality routing repair: provider fallback ordering is now
dynamic when `results/source_quality/latest.json` exists. Reviews record
`blocked_count`, and the route selector penalizes blocked/stale/low-quality
history before cost tier so unknown or blocked limited APIs do not crowd out
fresh local/unlimited evidence. The route attempt flight recorder now includes
`source_quality_score` and `source_quality_reason`; the bundle summary exposes
`source_quality_ordering`. Latest proof:
`results\source_quality\source-quality-review-20260605-080800.json` reported
`source_count=250`, `stale_count=96`, `blocked_count=65`, and
`stale_needs_refresh_count=0`; KO market-news bundle
`results\research_evidence\source-evidence-source-evidence-73f035b4ea7d47af86fd34ce55c9be7f.json`
used dynamic ordering and selected cache plus `reddit_watchlist` before blocked
limited APIs. This is analysis-only and does not grant order authority.

Connector-health noise repair: public Reddit HTTP 403 from `reddit_public` now
classifies as an optional endpoint block when there is no circuit, rate limit,
or fallback. The error still appears in connector health for visibility, but it
does not raise the `connector_health` drilldown flag. Real compact-context
refresh after the patch left only the paper-tournament candidate-change and
MiroFish drilldown flags. Proof:
`uv run --no-sync --with pytest python -m pytest -q
tests/test_automation_context_snapshot.py` passed with 27 tests, and targeted
Ruff/compile checks passed.

2026-06-05 morning-control repair: the overnight planner missed the scheduled
2:30 AM native automation run, so a real catch-up pass was executed through the
repo executable using the compact original TradingAgents graph route with Google
models. The packet
`results\overnight_plans\overnight-plan-20260605-101740-000000.json` completed
with `3` full graph successes, `0` graph failures, `36` ranked candidates,
`submitted=[]`, and top symbols `KO`, `IBM`, `HD`, `CVX`, and `XOM`. The verifier
now understands the controller contract: `tradingagents-overnight-planning` may
be `PAUSED` after a complete analysis-only overnight packet exists. Proof:
`results\overnight_system_verification\overnight-system-verification-20260605-061215.json`
passed.

Automation-health repair: controller memory parsing now uses the memory file
write time when the latest memory entry is date-only, which removed the false
wake-controller stale flag. The native automation tool also set
`hourly-market-supervisor` and `paper-strategy-tournament-runner` ACTIVE before
market open, paused overnight planning after the catch-up, and simplified the
self-heal monitor to the supported hourly RRULE form. Real health proof:
`results\automation_health\automation-health-audit-20260605-110115.json`
reported `ok_count=12`, `missing_count=0`, `late_count=0`, `duplicate_count=0`,
and one remaining stale controller: `tradingagents-night-shift-supervisor`.
That stale night-shift memory is a real missed-patrol signal and should be
cleared only by a genuine native automation run or a future app-run evidence
bridge, not by hand-editing memory.

Night-shift cadence repair: the active night-shift supervisor automation now has
the intended four-hour patrol cadence instead of skipping the daytime/evening
patrol slots. Real proof after the app update:
`results\automation_health\automation-health-audit-20260605-113550.json`.
The audit still reports `stale_memory` because the missed 2026-06-05 patrol has
not been replaced by a native automation thread; that remaining flag is expected
and should stay visible.

Night-shift cadence regression guard: `automation_health_audit` now validates the
controller cadence itself and reports `night_shift_cadence_mismatch` if the
schedule falls back to the broken partial-hour set. Focused tests passed with 22
automation-health cases, and the live post-guard audit
`results\automation_health\automation-health-audit-20260605-114237.json` shows
the corrected live cadence is accepted.

Night-shift evidence bridge: the active controller prompt now runs
`research night-shift-patrol --json-output` after compact context refresh. The
new CLI command writes an analysis-only packet under `results\night_shift_patrol\`
with `can_submit_orders=false`, `execution_authority=none`, and
`submitted_count=0`; automation health treats these packets as night-shift
schedule evidence. Focused proof: 24 automation-health/CLI tests passed, Ruff
passed on touched files, real packet
`results\night_shift_patrol\night-shift-patrol-20260605-135243.json` wrote
successfully, and real audit
`results\automation_health\automation-health-audit-20260605-135301.json` moved
night-shift from stale to partial with `actual_artifact_count=1`. Full-suite
proof passed with `899 passed, 1 skipped, 9 warnings, 75 subtests passed`.
Historical missed patrols were not backfilled.

Wake/sleep controller evidence bridge: `research controller-patrol` writes
analysis-only controller packets for
`tradingagents-automation-wake-controller` and
`tradingagents-automation-sleep-controller`. Automation health now discovers
`results\control_plane_patrol\wake-controller-patrol-*.json` and
`sleep-controller-patrol-*.json`, while preserving legitimate controller memory
as fallback evidence. The active wake/sleep controller prompts were updated
through the automation app to run the packet writer after status-only work. Real
proof: `results\control_plane_patrol\wake-controller-patrol-20260605-143624.json`
and `results\automation_health\automation-health-audit-20260605-143645.json`;
global `stale_count=0`, wake controller `status=ok` with
`actual_artifact_count=1`, and only night-shift remains partial because old
missed patrols were not backfilled. Full-suite proof after this slice passed
with `901 passed, 1 skipped, 9 warnings, 75 subtests passed`.

Real-simulation acceptance repair: the audit now treats an unreachable Mac
DeepSeek lane as optional helper degradation instead of failing the core
live-data dry-run when every order/research safety gate is otherwise clean.
Latest proof
`results\real_simulation_audits\real-simulation-audit-20260605-115602.json`:
8 departments, 28 commands, 0 failed commands, 0 submitted orders, no unsafe
submission evidence, all structured outputs present, stale sources safe or
downranked, `accepted=true`, `core_accepted=true`, and
`optional_helper_degraded=true`.

Final 2026-06-05 verification after this repair: process review
`results\process_reviews\process-review-20260605-153745.json` reported
`unchecked_step_count=0`; compact context refresh opened the current hourly
`loss-review`, `results\execution_board\latest.json`, and
`results\automation_health\latest.json`; full pytest passed with `903 passed,
1 skipped, 9 warnings, 75 subtests passed`. The current hourly packet is a
`loss-review`
hold with zero actions, zero issues, and zero submissions, so loss exits remain
independent/manual-review gated rather than automatic red-candle sells.

Compact BOARD drilldown repair: `scripts/automation_context_snapshot.py` now
flags hourly `loss-review` packets and execution-board summaries whose latest
reviewed packet is `loss-review` as `board_review` drilldowns. This closes a
token-efficient-context blind spot where the raw hourly packet and BOARD packet
could be skipped even though the system was intentionally paused for manual
thesis-break/time-value/capital-reuse review. Real proof:
`results\execution_board\execution-board-review-20260605-152357.json` and fresh
`results\_context\latest-flags.json`; the BOARD run stayed
`analysis_only=true`, `can_submit_orders=false`, and submitted 0 orders.

2026-06-06 SAFE-01 fail-closed reconciliation: Claude's submit-path handoff was
read and verified against current disk state. The local live config now parses
as `live_budget_mode="autonomous_with_caps"`, account max `$250`, per-name `$50`,
and `issues=[]`; `config/risk_envelope.yaml` is ignored and must not be
committed. The live-control dead-man remains lapsed, so the current money
posture is fail-closed even though promotion state may still be live-enabled.
Submit-path hardening is present in the shared files (hard account ceiling,
rolling live-order rate limit, dead-man re-check, paper/live rollback); the
standalone rate-limit module/tests are committed as unsigned `3970998`, and the
targeted submit-path regression slice passed with `159` tests. Ruff passed,
broad mypy passed over broker/policy/execution/dataflow with 57 source files,
and full pytest passed with `903 passed, 1 skipped, 9 warnings, 75 subtests
passed`.

2026-06-06 compact overnight-quality repair: the latest raw overnight packet was
complete, but `results\_context\latest-summary.json` only exposed a subset of
the nested `overnight_quality` evidence. `scripts/automation_context_snapshot.py`
now carries `completion_status`, `completion_reasons`, graph limit/attempt/
success counts, fallback/failure counts, research-context packet/block counts,
and graph provider/model route fields into compact context. Field provenance
maps these summaries back to `overnight_quality.*`, so n8n/hooks/morning bots
can trust the compact packet as the first read path and only open the raw
overnight packet for flagged drilldowns. Real refreshed context shows
`completion_status=complete`, 3/3 full-graph successes, `fallback_count=33`,
`graph_failure_count=0`, `research_context_packet_count=13`,
`research_context_blocked_count=0`, Google route
`explicit_google_overnight_graph`, zero submissions, and no overnight drilldown.
Focused context tests passed with 33 tests, targeted Ruff passed, and the real
context refresh rewrote `results\_context\latest-summary.json` plus
`field-provenance.json`.

2026-06-06 automation-health Saturday/no-market repair: automation health now
filters Saturday 02:30 local overnight-planning due windows because they do not
prepare a useful U.S. regular-session market morning; Sunday and Monday-Friday
overnight due checks still count, so the Friday missed-run regression remains
intact. `tradingagents-overnight-planning` was also reactivated after app/disk
state showed it was paused. Real safe observer refreshes wrote wake/sleep
controller patrol packets, a night-shift patrol packet, a self-heal handoff, and
a self-heal plan with `can_submit_orders=false`.
The latest health audit
`results\automation_health\automation-health-audit-20260606-192741.json` has
wake/sleep/self-heal/overnight `ok`, overnight `config_status=ACTIVE`,
self-heal follow-up lag `37s`, `missing_count=0`, `stale_count=0`, `late_count=0`,
`timeliness_issue_count=0`, and `submitted_order_count=0`.
Only night-shift remains `partial` while its six-window patrol history fills in.
Fresh overnight verifier
`results\overnight_system_verification\overnight-system-verification-20260606-141132.json`
is `overall_status=pass` and records `validation_skipped=true` plus
`skip_reason=saturday_no_regular_market_morning`; Sunday/Monday-Friday overnight
checks still count. Focused verifier/automation-health/context tests passed with
59 tests and targeted Ruff passed.

Current BOARD/Saturday overnight-evidence refresh:
`results\execution_board\execution-board-review-20260606-193832.json` now
reviews through the current hourly loss-review packet
`results\hourly_supervisor\hourly-supervisor-20260606-193752-094749.json`.
The hourly packet proves the supervisor no longer treats a recent Friday
overnight plan as stale on a no-market Saturday:
`evidence.overnight_plan.status=not_required`, `validation_skipped=true`, and
`skip_reason=saturday_no_regular_market_morning`; malformed/missing packets and
Sunday/weekdays still enforce freshness.
The BOARD packet is fresh, analysis-only, has `can_submit_orders=false`, zero
submitted orders, zero hard violations, one negative-live-P/L warning, and
`new_buy_state=caution`. Compact context should continue to flag this as
`board_review` until the negative P/L / loss-review evidence question is
resolved by new data or a later clean packet. Compact context now exposes the
useful proof directly: `board_hard_issue=false`,
`latest_packet_decision=loss-review`, `latest_packet_needs_review=true`,
`negative_live_pl_packets=24`, `warning_types=["negative_live_unrealized_pl"]`,
the real dry-run loss-review email proof (`email_clarity_eval` score 100,
24 lines, no issues/warnings, no pasted blocker checklist),
the independent buy/sell policy text, and self-heal signal classifications
showing automation-health as `safe_autofix` while hourly/BOARD review remain
`escalate_order_adjacent`. Focused Saturday overnight validation tests passed,
the real hourly dry-run submitted zero orders, BOARD refreshed with zero hard
violations, targeted Ruff passed, and
`results\process_reviews\process-review-20260606-195734.json` has
`unchecked_step_count=0`.

Blocked-provider quota follow-up: ticker provider bundles now treat blocked
limited/paid enrichment packets as failed attempts, not usable evidence. The
exceptions are connected-MCP/broker diagnostic packets and explicit local
research-gap packets, where the blocked status itself is the evidence. Real KO
market-news proof:
`results\research_evidence\source-evidence-source-evidence-b868493be1c74f63bce96e877d13f19c.json`
logs blocked `tiingo` as an attempt but counts only `google_news_rss`,
`official_cache`, and `reddit_watchlist`, with `limited_source_packet_count=0`.
Fresh source-quality review
`results\source_quality\source-quality-review-20260606-195554.json` has
`source_count=250`, `stale_count=174`, `blocked_count=69`, and
`stale_needs_refresh_count=0`. Provider/source-quality tests passed with 37
tests and targeted Ruff passed.

Claude-handoff prep refresh:
Codex re-read the submit-path hardening handoff and verified current state
again after the latest dirty-tree reconciliation. The local live config still
parses with the current `(envelope, issues)` loader API as
`live_budget_mode="autonomous_with_caps"`, account max `$250`, per-name `$50`,
optional hard ceiling/rate-limit knobs unset, and `issues=[]`; the dead-man
remains lapsed. The submit-path regression slice now passes with `160` tests,
Python-targeted Ruff passes, the example YAML parses through the repo loader as
`fixed_tranche` with `issues=[]`, and broad mypy still reports no issues in 57
broker/policy/execution/dataflow source files. Latest process review
`results\process_reviews\process-review-20260606-201150.json` reports
`unchecked_step_count=0` and `can_submit_orders=false`. Fresh overnight verifier
`results\overnight_system_verification\overnight-system-verification-20260606-143651.json`
is `overall_status=pass` with 3/3 original graph successes and 0 submissions.
Fresh n8n job discovery now reports 20 allowlisted jobs and `submit_capable_count=0`;
fresh n8n evaluation dataset
`results\n8n_evaluations\n8n-evaluation-dataset-20260606-204956-806412.json`
has 183 rows, 20 jobs, 17 edge tags, and 23 columns. Fresh automation health
`results\automation_health\automation-health-audit-20260606-193723.json` has no
missing/stale/late/timeliness issues and keeps only night-shift partial while
patrol history fills in. Fresh source-quality review
`results\source_quality\source-quality-review-20260606-193732.json` reviewed 250
sources and found 238 stale, 75 stale-downranked, 65 blocked, and 0 invalid;
this is a research-quality warning for next-session evidence refresh/downranking,
not a live-submit blocker.

P5 automation-health compact-output follow-up:
`research automation-health-audit --json-output --compact-json-output` now emits
`compact_automation_health_audit_v1` and still writes the full raw audit plus
Markdown packet. n8n now calls the compact flag for `automation_health_audit`,
and the runner parses both compact and legacy full JSON. Real bridge proof:
`python -m tradingagents.orchestration.n8n_runner --run-job
automation_health_audit` returned the compact schema with `submit_capable=false`,
`submitted_order_count=0`, and only `tradingagents-night-shift-supervisor` as
the current attention/problem automation. The latest compact-output audit
`results\token_efficiency\compact-output-audit-20260606-154240-507832.json`
measures 5 families, total `8729059 -> 9568` bytes, `automation_health_audit`
`14662 -> 1140` bytes (`92.22%` reduction), and every row
`lossless_by_reference=true`. Fresh n8n evaluation dataset
`results\n8n_evaluations\n8n-evaluation-dataset-20260606-203911-855013.json`
now covers 20 allowlisted jobs and 183 rows.

P1-10 analyst-concurrency follow-up:
`tradingagents\graph\analyst_execution.py` now computes bounded analyst batches
from `analyst_concurrency_limit`, and `tradingagents\graph\setup.py` wires those
batches through LangGraph `Send` fan-out plus explicit batch join nodes. The
default graph still runs analysts sequentially; compact and market-news
overnight profiles now set `analyst_concurrency_limit=2` so overnight research
can overlap independent analyst work without turning the full tool-loop route
into an uncontrolled fan-out. `TRADINGAGENTS_ANALYST_CONCURRENCY_LIMIT` is also
available for explicit operator overrides. Focused proof: analyst execution,
graph routing/compile, env override, and overnight CLI graph-config tests passed
with `38 passed`; targeted Ruff passed; direct `py_compile` over touched source
and tests passed. Real no-latest overnight probe:
`results\overnight_plans\concurrency_probe\overnight-plan-20260606-201918-000000.json`
has `execution_authority=none`, `submitted_count=0`, graph profile `compact`,
and `overnight_quality.graph_config.analyst_concurrency_limit=2`. A broad mypy
sweep over `tradingagents\graph` still exposes pre-existing typed-frontier debt
in graph/agent/LLM modules and is not treated as this slice's regression gate.

Top-symbol evidence refresh:
Analysis-only ticker provider bundles were refreshed for the current top
overnight symbols `KO`, `IBM`, and `HD`. Each wrote 17 source packets and a
medium-quality summary packet:
`results\research_evidence\source-evidence-source-evidence-ec8d000296f048f2b8f30ddaa4c3a276.json`
for `KO`,
`results\research_evidence\source-evidence-source-evidence-955ee8e83ad144ce88eedd64ead3bbc6.json`
for `IBM`, and
`results\research_evidence\source-evidence-source-evidence-ead7e6ab12294983bc2e236a5cf16540.json`
for `HD`. IBM's crawler leg hit SEC 403 after retries and was recorded as
blocked evidence. The follow-up source-quality review
`results\source_quality\source-quality-review-20260606-194532.json` reduced
stale sources from 238 to 186, raised fresh sources to 64, recorded 60
stale-downranked and 71 blocked, and still has 0 invalid packets.

P2 real walk-forward checkpoint:
`tradingagents research walk-forward-refresh-overnight-cohort --json-output`
wrote
`results\research_batches\walk_forward_cohort_refresh_20260606-195033_h3.json`.
The command is analysis-only and selected 12 mature overnight packets, skipped 5
not-yet-mature packets, collected 140 yfinance later-return rows, generated 420
fixture rows, and met the replay sample floor. The result is useful but not
flattering: deterministic sleeve rows scored `0.3905` directional accuracy,
`0.1690` false-positive rate, `0.2577` average Brier, and `-0.3781` average
action-relative return. The TradingAgents advisory overlay had only 11 scored
rows with `0.4545` directional accuracy, `0.5455` false-positive rate, `0.2901`
average Brier, and `-0.2109` average action-relative return. Official,
news/social/crawler, and Deep Research overlays were unavailable for this
cohort. This proves the outcome loop is wired, and also proves the strategy
layer still needs calibration, anti-crowding, and more mature samples before it
earns greater influence.

Agent intelligence and model telemetry checkpoint:
`research agent-ledger-resolve`, `research agent-ledger-summary`,
`research model-telemetry-report`, and `research outcome-labeling` refreshed the
learning loop after the cohort. The agent ledger has 2,740 pending forecasts and
0 resolved forecasts, so all agent weights remain `insufficient_history` at
`1.00`; dynamic agent influence is intentionally not active yet. Model telemetry
packet
`results\model_telemetry_reports\model-telemetry-report-20260606-195125-804423.json`
shows Mac `deepseek-r1:14b` helper success, deterministic helper success,
Codex/thread judgment fallback, Windows local Ollama blocked because no Windows
Ollama URL is configured, and 0 resolved model-run usefulness outcomes. The
pipeline should keep Mac DeepSeek as a cheap helper lane and Codex/OpenAI as the
judgment lane until resolved usefulness evidence justifies anything else.

n8n evaluation sync-drift guard:
`scripts\automation_context_snapshot.py` now compares the current n8n evaluation
dataset row count to both `final_row_count` and `expected_row_count` in
`results\n8n_evaluations\latest-sync.json`. A stale sync proof that says
`row_count_matches=true` for an older dataset now sets
`sync_current_row_count_matches=false` and opens an `audit` drilldown. Real proof:
the local n8n Data Table sync was refreshed to the current 183-row dataset at
`results\n8n_evaluations\n8n-api-sync-20260606-205308-805632.json`, with
`api_key_redacted=true`, `inserted_count=183`, and `row_count_matches=true`;
fresh compact context reports `sync_current_row_count_matches=true` and no n8n
drilldown. Focused snapshot tests passed with 35 tests, targeted Ruff passed,
and direct `py_compile` passed.

n8n workflow-sync guard:
`tradingagents.orchestration.n8n_workflow_sync` and
`research n8n-sync-workflows --json-output` create missing local n8n workflows
from `n8n/workflows/*.json` through the public API while keeping them inactive
and redacting the API-key source. Real proof
`results\n8n_evaluations\n8n-workflow-sync-20260606-210202-886336.json`
created inactive `TA · Automation Evaluations (observer)` and
`TA · Sync Evaluation Dataset (observer)` workflows, found 10 existing
source-controlled matches, recorded 12 source workflows, and left the two legacy
duplicate `TA · Sync Evaluation Dataset` workflows untouched. Compact context
now summarizes `workflow_sync_status`, source/existing/created counts, duplicate
name counts, created/source workflow names, and key redaction; missing or unsafe
workflow-sync proof opens an `n8n_evaluation_dataset` audit drilldown.

Automation-health benign-partial guard:
compact context now preserves the raw night-shift continuity fact without
forcing every morning reader into the raw automation-health packet. If the only
partial row is `tradingagents-night-shift-supervisor` with real patrol artifacts
and only the historical `observed_runs_less_than_expected` / `missed_run`
condition, the summary keeps `partial_count=1` but sets
`actionable_partial_count=0`, records the id under `benign_partial_automation_ids`,
and leaves `problem_automation_ids=[]`. Missing/stale/late/duplicate/cadence/
self-heal SLA issues still flag `automation_health`. Real refreshed context now
has no automation-health drilldown; focused snapshot tests passed with 36 tests
and targeted Ruff passed.

Self-heal covered-escalation guard:
compact context now treats self-heal as a repair/execution wrapper, not as a
second source of truth for order-adjacent BOARD review. When a self-heal plan has
no active safe fixes and only escalates `hourly` / `execution_board_review`
`board_review` signals already opened elsewhere, it records those labels under
`self_heal_covered_escalated_labels`, sets `actionable_escalation_count=0`, and
does not add a separate `issues` drilldown. Active safe fixes, failed
verification, schema issues, or non-covered high-severity escalations still
flag. Real refreshed context keeps the hourly loss-review, BOARD review, and
loss-review-evidence packets open while self-heal is quiet; focused snapshot
tests passed with 37 tests and targeted Ruff passed.

Loss-review evidence freshness guard:
compact context now verifies that `results\loss_review_evidence\latest.json`
was built from the current latest hourly packet. The summary exposes
`hourly_packet_path`, `latest_hourly_packet_path`, and
`evidence_matches_latest_hourly`; if the evidence packet targets an older hourly
loss-review, the snapshot raises a `stale` drilldown. Real proof: after a newer
hourly loss-review packet appeared at
`results\hourly_supervisor\hourly-supervisor-20260606-210521-309775.json`,
`research loss-review-evidence --json-output` refreshed the evidence packet at
`results\loss_review_evidence\source-evidence-source-evidence-3b63e2d1943b43e6badf40a133ee361b.json`
with `execution_authority=none` and no submissions. Refreshed compact context
shows `evidence_matches_latest_hourly=true`; focused context/loss-review/n8n
tests passed with 81 tests, targeted Ruff and `py_compile` passed, and process
review reports `unchecked_step_count=0`.

Execution BOARD freshness guard:
compact context now verifies that `results\execution_board\latest.json` reviewed
the current latest hourly packet. The summary exposes
`board_latest_reviewed_packet_path`, `latest_hourly_packet_path`, and
`board_matches_latest_hourly`; if the BOARD packet's newest reviewed hourly
packet is older than the newest hourly packet on disk, the snapshot raises a
`stale` drilldown. Real proof: after the latest hourly loss-review advanced to
`results\hourly_supervisor\hourly-supervisor-20260606-210521-309775.json`,
`research execution-board-review --json-output` refreshed the BOARD packet at
`results\execution_board\execution-board-review-20260606-212113.json` with
`analysis_only=true`, `can_submit_orders=false`, 0 submitted orders, and that
hourly packet included as `review_window.newest_packet`. Focused snapshot tests
passed with 42 tests.

Night-shift/self-heal timeliness guard:
compact context no longer hides multi-window night-shift patrol gaps. The
previous benign-partial rule treated any
`tradingagents-night-shift-supervisor` `observed_runs_less_than_expected:*`
packet with at least one artifact as history fill-in; that was too broad for
timely self-heal/controller monitoring. The rule now only de-noises a one-window
gap, while larger gaps raise `automation_health` with
`problem_automation_ids=["tradingagents-night-shift-supervisor"]`. Real proof:
`research night-shift-patrol --json-output` wrote
`results\night_shift_patrol\night-shift-patrol-20260606-213112.json` with no
execution authority and no submissions; the follow-up automation-health audit
kept night shift partial at `3/6` observed patrols; and
`research self-heal-plan --execute-safe --json-output` recorded the
automation-health signal on the safe plane without modifying automation status,
orders, goals, emails, or secrets. Focused context/health/self-heal tests passed
with 85 tests.

Overnight compact sidecar guard:
new overnight plan writes now keep the full raw packet and also emit a compact
machine sidecar beside it (`overnight-plan-*.compact.json`) plus
`results\overnight_plans\latest-compact.json` whenever `latest.json` is updated.
The sidecar uses the same `compact_overnight_plan_v1` builder as
`--compact-json-output`, preserving raw evidence by reference through
`raw_packet_path` while exposing counts, top candidate, quality metadata,
research-context counts, and model-route graph config. The current real packet
was backfilled: raw latest is `8,445,004` bytes while
`latest-compact.json` is `2,927` bytes. `scripts\automation_context_snapshot.py`
now prefers the compact sidecar for the `overnight` summary when present, so
morning agents and n8n keep seeing `KO`, the Google overnight graph route, 3/3
full-graph successes, and zero graph failures without opening the 8.4 MB raw
archive. Focused writer/CLI/snapshot tests passed with 6 tests; targeted Ruff
and `py_compile` passed.

Overnight calibration guard:
`tradingagents\evals\overnight_calibration.py` builds a no-execution-authority
packet from the latest walk-forward cohort, and `cli.main research
overnight-calibration-guard --json-output` writes it under
`results\overnight_calibration\`. The current real packet returns
`guard_decision=tighten` because both deterministic and TradingAgents advisory
overlays have negative action-relative returns, and the advisory overlay
false-positive rate is too high. Compact context and n8n now summarize the guard
so morning agents see "tighten, do not promote" before opening raw packets.
Focused proof passed for the guard, compact context, and n8n policy tests; the
real n8n runner returned a compact parsed summary with `submit_capable=false`.

n8n evaluation compact sidecar:
`tradingagents\orchestration\n8n_evaluations.py` now writes durable compact
sidecars beside the full n8n Data Table artifacts. Compact context uses
`results\n8n_evaluations\latest-compact.json` for the
`n8n_evaluation_dataset` summary and keeps `raw_packet_path` pointed at the full
archive. The sidecar retains the safety-critical proofs (analysis-only,
execution authority none, row/job/edge counts, actual-output columns, Data Table
sync, and workflow sync) without loading all evaluation rows. Real proof:
`results\n8n_evaluations\latest.json` is 290,235 bytes and
`latest-compact.json` is 3,482 bytes; refreshed context reports
`approx_tokens=871`, `has_actual_output_columns=true`,
`sync_current_row_count_matches=true`, and `workflow_sync_status=ok`. Process
review `results\process_reviews\process-review-20260606-215955.json` has
`unchecked_step_count=0` and no findings; the raw n8n dataset is no longer a
token hotspot. Focused tests passed with 94 tests, plus targeted Ruff and
`py_compile`.

Source-quality compact sidecar:
`tradingagents\evals\source_quality.py` now writes durable compact sidecars next
to the raw source-quality review. Compact context uses
`results\source_quality\latest-compact.json` for the `source_quality_review`
summary and keeps `latest.json` as the raw evidence archive for provider
ordering and drilldown. The sidecar keeps the counts morning agents need:
source count, quality/freshness counts, stale/downrank/refresh counts, blocked
count, missing/invalid count, execution authority, and raw packet path. Real
proof: `results\source_quality\latest.json` is 162,387 bytes and
`latest-compact.json` is 5,259 bytes; refreshed context reports
`source_count=250`, `stale_count=109`, `stale_needs_refresh_count=0`,
`missing_or_invalid_count=0`, `blocked_count=50`, `can_submit_orders=false`, and
`execution_authority=none`. Process review
`results\process_reviews\process-review-20260606-220722.json` has
`unchecked_step_count=0` and no findings; the raw source-quality packet is no
longer a token hotspot. Focused tests passed with 94 tests, plus targeted Ruff
and `py_compile`.

MiroFish compact sidecar:
`tradingagents\research\mirofish_handoff.py` now exposes
`build_compact_mirofish_handoff_status(...)`, and the CLI writes a durable
compact sidecar beside each raw MiroFish status packet. Compact context uses
`results\mirofish_handoff\latest-compact.json` for the
`mirofish_handoff_status` summary and keeps `latest.json` as the raw evidence
archive. The sidecar preserves the final handoff status, report id, advisory
validity, attention/forecast symbols, report-33 overlay, false-signal filters,
MiroFish advisory gate action, clean-room flags, and execution authority. Real
proof: `results\mirofish_handoff\latest.json` is 123,711 bytes and
`latest-compact.json` is 6,926 bytes; refreshed context reports
`final_handoff_available=true`, `missing_piece_count=0`,
`mirofish_advisory_gate_action=suppress`, triggered gates
`broker_friction`, `macro_override`, and `attribution_error`,
`deep_research_review_available=true`, `can_submit_orders=false`, and
`execution_authority=none`. Process review
`results\process_reviews\process-review-20260606-221918.json` has
`unchecked_step_count=0` and no findings; raw MiroFish is no longer a token
hotspot. Focused tests passed with 93 tests, plus targeted Ruff and
`py_compile`.

Premarket compact sidecar:
`tradingagents\brokers\alpaca_supervisor.py` now writes durable compact
sidecars for rolling premarket briefs. The raw latest packet stays available for
drilldown, but compact context uses
`results\premarket_briefs\latest-compact.json` for the `premarket_brief`
summary. The sidecar keeps top symbol, latest hourly decision, paper leader,
source packet count, blocker count, stale-warning count, and raw packet path.
Real proof: `results\premarket_briefs\latest.json` is 103,292 bytes and
`latest-compact.json` is 961 bytes; refreshed context reports `top_symbol=KO`,
`latest_hourly_decision=loss-review`,
`paper_tournament_leader=pullback-support`, `source_packet_count=54`,
`blockers=0`, and `stale_warnings=0`. Process review
`results\process_reviews\process-review-20260606-223113.json` has
`unchecked_step_count=0` and no findings; raw premarket is no longer a token
hotspot. Focused tests passed with 111 tests, plus targeted Ruff and
`py_compile`.

Paper tournament compact sidecar:
`tradingagents\brokers\paper_tournament.py` now writes durable compact sidecars
beside the paper tournament ledger. The full
`results\paper_strategy_tournament\latest.json` and
`paper-tournament-ledger.json` remain the raw evidence archive, while compact
context uses `results\paper_strategy_tournament\latest-compact.json` for the
`paper_tournament` summary. The sidecar keeps tournament id, generated time,
strategy count, paper-account baseline, top rankings, live strategy candidate,
AlphaInsider paper-watch summary, raw packet path, and explicit
`can_submit_orders=false` / `execution_authority=none`. Real proof:
`results\paper_strategy_tournament\latest.json` is 69,101 bytes and
`latest-compact.json` is 2,510 bytes; refreshed context reports
`leader=pullback-support`, `candidate_status=candidate`,
`candidate_strategy=pullback-support`, `ranking_count=3`,
`submitted_count=0`, and `approx_tokens=628`. Process review
`results\process_reviews\process-review-20260606-224426.json` has
`unchecked_step_count=0` and no findings; raw paper tournament is no longer a
token hotspot. Focused tests passed with 100 tests, plus targeted Ruff and
`py_compile`.

Night-shift automation-health repair:
`tradingagents\evals\automation_health_audit.py` now floors expected due windows
and artifact evidence to an automation config's `updated_at`/`created_at`
effective time when that metadata is present. This prevents the health audit
from blaming a newly updated schedule for patrol windows before the current
schedule existed, while preserving real missed-run detection after the effective
time. The real night-shift patrol command was exercised and wrote
`results\night_shift_patrol\night-shift-patrol-20260606-225022.json` with
`analysis_only=true`, `can_submit_orders=false`, `execution_authority=none`, and
no issues. Real health proof:
`results\automation_health\automation-health-audit-20260606-225956.json` reports
13/13 automations OK, `partial_count=0`, `missing_count=0`, `late_count=0`,
`timeliness_issue_count=0`, `submitted_order_count=0`, and night-shift
`status_reason=night_shift_latest_due_covered_history_ramp_up`. Refreshed
compact context no longer flags `automation_health_audit`; the remaining flags
are the expected BOARD/loss-review items. Focused tests passed with 114 tests,
plus targeted Ruff and `py_compile`.

Capability-audit compact sidecar:
`cli\main.py` now writes durable compact sidecars for
`integrations doctor --write-packet`. The full raw audit remains available at
`results\capability_audits\latest.json`, while compact context reads
`results\capability_audits\latest-compact.json` by default. The compact sidecar
keeps the redacted availability/authority facts morning research needs: env
present/missing counts, missing env preview, integration count, MCP/Composio/
Alpaca configuration, authority counts, `can_submit_orders=false`,
`execution_authority=none`, and raw packet path. Real proof: raw latest is
39,574 bytes and compact latest is 2,113 bytes; refreshed context reports
`approx_tokens=529`, `env_present_count=14`, `missing_env_count=12`,
`integration_count=44`, `docker_mcp_configured=true`,
`composio_configured=true`, and `secrets_redacted=true`. Focused tests passed
with 88 tests, plus targeted Ruff and `py_compile`.

Research-batch compact sidecar:
`tradingagents\policy\packets.py` now writes durable compact sidecars for every
`ResearchBatchRunPacket` emitted through `write_research_packet(...)`. The full
raw packet remains the evidence archive under `results\research_batches`, while
compact context reads `results\research_batches\latest-compact.json` by
default. The sidecar keeps top candidates, candidate/route/reference/fallback
counts, quality-gate status, advisory missing gates, `can_submit_orders=false`,
`execution_authority=none`, and raw packet path. This lets overnight research,
walk-forward calibration, and model-orchestration agents see whether the batch
is usable without opening rows of replay metrics or raw packet refs. Real proof:
the current latest raw research batch is 18,281 bytes and compact latest is
2,778 bytes; refreshed context reports `approx_tokens=695`, `status=success`,
`fallback_actions=3`, `failed_quality_gates=[]`, `can_submit_orders=false`, and
no `quality` drilldown flag. Process review
`results\process_reviews\process-review-20260606-231826.json` has
`unchecked_step_count=0` and no findings; raw research batches are no longer a
token hotspot. Focused tests passed with 56 tests, plus targeted Ruff and
`py_compile`.

Hourly compact sidecar:
`tradingagents\brokers\alpaca_supervisor.py` now writes durable compact sidecars
for hourly supervisor packets through `write_hourly_decision_packet(...)`. The
CLI compact output wrapper delegates to the same broker helper, so future hourly
runs and direct CLI compact output share one schema. The raw packet remains the
evidence archive, while compact context reads
`results\hourly_supervisor\latest-compact.json` by default. The sidecar keeps
decision/reason, action/issue/submitted counts, notify state, raw packet path,
live/paper portfolio counts, context pointers, `can_submit_orders=false`, and
`execution_authority=none`. Real proof: the current latest raw hourly packet is
34,277 bytes and compact latest is 3,481 bytes; refreshed context reports
`approx_tokens=871`, `decision=loss-review`, `action_count=0`, `issues=0`,
`submitted=0`, and `notify=false`. The expected BOARD-review flag remains, but
the raw hourly packet is no longer a process-review token hotspot. Process
review `results\process_reviews\process-review-20260606-233050.json` has
`unchecked_step_count=0` and no findings. Focused tests passed with 53 tests,
plus targeted Ruff and `py_compile`.

Automation-health compact sidecar:
`tradingagents\evals\automation_health_audit.py` now writes durable compact
sidecars from `write_automation_health_audit(...)`. The raw JSON/Markdown audit
remains available for drilldown, while compact context reads
`results\automation_health\latest-compact.json` by default. The sidecar keeps
health counts, problem/attention IDs, self-heal timeliness, benign night-shift
ramp-up IDs, raw packet path, `analysis_only=true`, and
`can_submit_orders=false`. The CLI compact output delegates to the same builder.
Real proof: `research automation-health-audit --json-output` wrote
`results\automation_health\automation-health-audit-20260606-233958.json` and
compact sidecars; refreshed context reports `approx_tokens=306`, 13 automations,
zero missing/partial/late/stale/warning/timeliness issues, zero submissions, and
no automation-health drilldown flag. Process review
`results\process_reviews\process-review-20260606-234021.json` has
`unchecked_step_count=0` and no findings; raw automation health is no longer a
token hotspot. Focused tests passed with 119 tests, plus targeted Ruff and
`py_compile`.

BOARD compact-sidecar freshness repair:
`tradingagents\evals\execution_board.py` now excludes hourly compact sidecars
and latest pointers from BOARD packet review. It reads only raw
`hourly-supervisor-*.json` packets, preventing compact context artifacts from
inflating packet counts or duplicating the latest hourly decision. The context
snapshot also compares BOARD and loss-review evidence freshness against the raw
packet referenced by `hourly/latest-compact.json`, not the compact file path.
Real proof: refreshed BOARD review
`results\execution_board\execution-board-review-20260606-234450.json` reviewed
24 raw hourly packets, submitted zero orders, and found zero hard violations.
Refreshed loss-review evidence
`results\loss_review_evidence\source-evidence-source-evidence-6cec5ab4ac894773a657c46fce716db8.json`
resolved 3 blocker categories while keeping `can_submit_orders=false`.
Compact context now reports `board_matches_latest_hourly=true` and
`evidence_matches_latest_hourly=true`; only intended BOARD-review flags remain.
Process review `results\process_reviews\process-review-20260606-235250.json`
has `unchecked_step_count=0` and no findings. Focused tests passed with 62
tests, plus targeted Ruff and `py_compile`.

## 22. n8n evaluation sync drift checkpoint

The n8n observer/evaluation control plane now has current local dashboard proof
after the Agent Intelligence learning-loop job expanded the built-in evaluation
dataset. The repo dataset advanced to 201 rows, but the prior n8n Data Table
sync proof was still at 192 rows, which correctly triggered a compact-context
`audit` flag for `n8n_evaluation_dataset`.

The first direct sync attempt without `N8N_API_KEY` failed closed with redacted
`blocked_missing_api_key` JSON packets. The successful path copied the running
n8n container's `/home/node/.n8n/database.sqlite` to a temporary `%TEMP%`
directory, passed that copy via `--api-key-sqlite-db`, and deleted the copied DB
after the proof packets were written. No broker, live-control, automation
status, schedule, or credential files were changed.

Fresh proof:
- `results\n8n_evaluations\n8n-api-sync-20260607-022929-127780.json`:
  `status=ok`, `expected_row_count=201`, `final_row_count=201`,
  `row_count_matches=true`, `api_key_redacted=true`, `analysis_only=true`,
  and `can_submit_orders=false`.
- `results\n8n_evaluations\n8n-workflow-sync-20260607-022936-100872.json`:
  `status=ok`, `source_workflow_count=12`, `existing_count=12`,
  `created_count=0`, `would_create_count=0`, `api_key_redacted=true`,
  `analysis_only=true`, and `can_submit_orders=false`.
- Refreshed compact context removed the n8n audit drilldown; only the intended
  hourly/BOARD/loss-review review flags remain.
- Process review
  `results\process_reviews\process-review-20260607-023015.json` has
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

## 23. Hourly/loss-review compact-context merge checkpoint

The remaining BOARD/loss-review flags now carry current blocker state instead of
stale hourly prose. The hourly supervisor packet that triggered TSM
`loss-review` originally listed 13 missing evidence categories. The later
loss-review evidence bridge resolved 8 of those categories, but compact context
still displayed only the old hourly reason. That made morning agents reopen the
same already-resolved gaps.

`scripts\automation_context_snapshot.py` now reads the latest
`loss_review_evidence` compact packet while summarizing `hourly`, compares the
evidence's `hourly_packet_path` to the hourly compact sidecar's
`raw_packet_path`, and only then adds a bounded `loss_review_*` summary to the
hourly packet summary. Stale or mismatched evidence cannot overwrite the hourly
state. The hourly packet remains flagged for `board_review`; this is context
clarity only, not a sell approval.

Fresh proof after regenerating compact context:
- `hourly.loss_review_evidence_matches_latest=true`.
- `hourly.loss_review_entry_context_found=true`.
- `hourly.loss_review_remaining_blockers_before_refresh_count=13`.
- `hourly.loss_review_resolved_blocker_count=8`.
- `hourly.loss_review_remaining_blocker_count=5`.
- `hourly.drilldown_reasons=["board_review"]`.

Focused verification:
`tests/test_automation_context_snapshot.py::test_snapshot_merges_matching_loss_review_evidence_into_hourly_summary`
plus the related hourly/loss-review snapshot tests passed with 5 tests; targeted
Ruff and `py_compile` passed.

## 24. Premarket Compact Validation-Checklist Checkpoint

The raw rolling premarket brief already carried the required fresh-validation
contract before any market action: fresh quotes/spreads, overnight and morning
news/social deltas, open live and paper orders, current positions/P&L, and live
sizing room/buying power. The compact premarket sidecar dropped that list,
which meant morning agents could follow the token-efficient path and still miss
the exact checks that keep the overnight research packet from becoming an
execution shortcut.

`tradingagents\brokers\alpaca_supervisor.py` now preserves
`premarket_instructions.summary` and bounded `must_validate_fresh` entries in
`compact_premarket_brief_payload(...)`. `scripts\automation_context_snapshot.py`
surfaces the same list in `results\_context\latest-summary.json` for the
`premarket_brief` packet. This adds no authority and no flag: the packet remains
analysis-only with `execution_authority=none`, and agents still open the raw
brief only for blockers, stale warnings, top-symbol changes, or missing
instructions.

Fresh proof:
- `results\premarket_briefs\premarket-brief-20260607-030938-000000.json` and
  `results\premarket_briefs\latest-compact.json` now include the five
  `must_validate_fresh` entries.
- Refreshed `results\_context\latest-summary.json` reports
  `premarket_brief.must_validate_fresh=[...]`, `top_symbol=XOM`, zero blockers,
  and zero stale warnings.
- Process review
  `results\process_reviews\process-review-20260607-031011.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
- Focused tests passed with 4 tests, the wider premarket/overnight/context
  slice passed with 14 tests, and targeted Ruff passed.

## 25. Premarket Checklist Verifier Checkpoint

The premarket compact sidecar is now covered by the overnight verifier. This
closes the remaining failure mode where the raw packet could retain
`must_validate_fresh`, but the token-efficient first-read packet could lose it
again and still let `verify-overnight-system` pass.

`cli\main.py` now emits a `premarket_fresh_validation_checklist` verification
check. It requires:

- the raw premarket packet to include the five fresh validation items;
- `results\premarket_briefs\latest-compact.json` to use
  `compact_premarket_brief_v1`;
- the compact premarket instructions to include the same five items;
- the compact packet to point back to either `latest.json` or the timestamped
  raw `premarket-brief-*.json` in the same directory.

This is a verifier-only guard. It does not change live authority, order
submission, automation status, schedules, credentials, or dead-man state.

Fresh proof:

- `results\overnight_system_verification\overnight-system-verification-20260606-222604.json`
  reports `overall_status=pass` and
  `premarket_fresh_validation_checklist=pass` with five raw items, five compact
  items, no missing entries, and `compact_points_to_latest_raw=true`.
- `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py::test_verify_overnight_system_audits_full_chain -q`
  passed with a negative subcase proving a compact packet missing
  `must_validate_fresh` fails verification.
- `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -k "verify_overnight_system or premarket_brief or simulated_preopen_validation" -q`
  passed with 9 tests, 75 deselected.
- `uv run --no-sync --group static-analysis ruff check cli\main.py tests\test_alpaca_cli.py`
  passed.

## 41. Claude Submit-Path Prep Refresh

Codex re-read the Claude submit-path deep review and verified the current branch
against it again. The current branch is
`wip/submit-path-hardening-2026-06-05`; `HEAD` remains unsigned commit
`3970998`, limited to the standalone live-order rate-limit module and its test.
The local/sensitive live envelope remains fail-closed and uncommitted:
`config/risk_envelope.yaml` parses with `issues=[]`,
`live_budget_mode="autonomous_with_caps"`, account cap `$250`, and per-name cap
`$50`. `results/policy/live_control.json` is not frozen, but its dead-man is
expired at `2026-06-04T19:57:06+00:00`, so live submission remains blocked until
an explicit operator refresh.

Hygiene is still prepared: `.gitignore` covers `config/risk_envelope.yaml`,
`.claude/`, `setup_n8n.py`, and `analysis_mypy.txt`, while `.codex/` remains
visible for hook review. Fresh proof passed:

- Targeted Ruff over the submit-path files and tests -> passed.
- Submit-path regression gate -> `163 passed in 118.49s`.

No orders, emails, dead-man refreshes, credential edits, automation status
changes, staging, commits, or live-authority changes occurred during this prep
refresh.

## 42. Automation Memory Rollup Plan

Codex added a safe rollup-planning path for token-heavy automation memories.
`research automation-memory-rollup --json-output` discovers
`C:\cm\automations\*/memory.md`, scores large memories for future compaction,
and writes analysis-only packets under `results\token_efficiency`. It does not
edit automation memory files, change automation status, trade, refresh live
control, or delete history.

Fresh real proof wrote
`results\token_efficiency\automation-memory-rollup-20260607-071207.json`.
The packet inspected 12 automation memories and found 2 rollup candidates:
`hourly-market-supervisor` and `paper-strategy-tournament-runner`. Candidate
token mass is about 71,658 tokens. The recommended future path is archive full
memory first, then keep a digest plus retained tail only after explicit
operator approval.

`results/_context/context-manifest.json` now includes an
`automation_memory_rollup` summary with the latest packet path, candidate count,
candidate approx tokens, and dry-run/no-authority flags. Verification passed:

- `tests/test_automation_memory_rollup.py` -> 3 passed.
- `tests/test_automation_memory_rollup.py tests/test_automation_context_snapshot.py`
  -> 69 passed.
- Targeted Ruff over the new module, CLI, context snapshot, and tests -> passed.
- Process review
  `results\process_reviews\process-review-20260607-071504.json` reports
  `unchecked_step_count=0` and no findings.

## 43. Automation Memory Rollup Apply Gate

The automation memory rollup tool now supports a guarded maintenance path:
`research automation-memory-rollup --apply --confirm-apply`. The double flag is
intentional. A normal run remains dry-run only; an apply run verifies the
candidate memory hash, archives the full original memory, then replaces only
rollup candidates with a compact digest plus retained tail. The apply result
stays `analysis_only=true`, `can_submit_orders=false`, and
`execution_authority=none`; it does not touch prompts, schedules, statuses,
credentials, live-control state, or broker paths.

Codex did not run the apply path on real `C:\cm\automations` memories. A fresh
real dry-run wrote
`results\token_efficiency\automation-memory-rollup-20260607-072153.json`,
showing 12 inspected memories, 2 rollup candidates, and about 71,658 candidate
tokens. Compact context points to that latest dry-run packet. Verification:

- `tests/test_automation_memory_rollup.py` -> 7 passed.
- `tests/test_automation_memory_rollup.py tests/test_automation_context_snapshot.py`
  -> 73 passed.
- Targeted Ruff over the rollup module, CLI, and tests -> passed.
- Process review
  `results\process_reviews\process-review-20260607-072224.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

## 44. Model Context-Window Metadata

The model catalog no longer requires human label parsing for known context
windows. `tradingagents.llm_clients.model_catalog` now exposes
`ModelMetadata`, `get_model_metadata(...)`, and
`get_model_context_window_tokens(...)`. Known entries are deliberately bounded
to models with stable/repo-listed capacity: OpenAI 1M-context models, Gemini
2.5 models, GLM 204K models, and MiniMax M2 204.8K models. Custom and local
Ollama builds return `None` rather than guessed context capacity.

`ModelRoute.model_dump()` now includes `context_window_tokens` when the route's
provider/model is known. Overnight graph config also includes
`quick_context_window_tokens`, `deep_context_window_tokens`, and
`helper_context_window_tokens`, so overnight packets and verifiers can reason
about model capacity without re-opening docs or parsing labels.

Verification:

- Model catalog/routing/overnight graph-config slice -> 33 passed.
- Catalog/routing/Ollama-label compatibility slice -> 31 passed.
- Targeted Ruff over the catalog, routing, CLI, and tests -> passed.
- Direct sanity proof showed Gemini 2.5 Flash Lite / Flash overnight config
  with 1,048,576-token quick/deep context windows and a capped Gemini judgment
  route dump carrying `context_window_tokens=1048576`.

## 26. Loss-Review Compact Payload Trimming Checkpoint

The loss-review evidence sidecar was still too close to a raw packet: it copied
the full nested `advisory_analysis`, including source refs and provider-route
details, into `results\loss_review_evidence\latest-compact.json`. That kept the
BOARD flag useful, but it made every compact-context read pay for evidence that
should stay behind the raw packet pointer.

`tradingagents\policy\packets.py` now writes loss-review compact payloads by
reference. The compact packet keeps the fields needed for morning routing and
BOARD triage: blocker counts and lists, resolved blocker list, evidence needs
and coverage, source packet IDs, route/source counts, a bounded entry-context
summary, current review snapshot, and an `advisory_summary` with the HOLD-vs-SELL
frame and thesis-status candidate. Full source refs, provider route details,
and submit IDs stay in the raw evidence packet.

Fresh proof:

- `research loss-review-evidence --json-output` wrote
  `results\loss_review_evidence\source-evidence-source-evidence-bae59d8683014d51812d06f14c595cc0.json`
  and refreshed `results\loss_review_evidence\latest-compact.json`.
- The compact sidecar is now `6,393` bytes / about `1,599` tokens, down from the
  previous `12,144` bytes / about `3,036` tokens, while retaining
  `remaining_blockers_before_refresh_count=13`, `resolved_blocker_count=8`,
  `remaining_blocker_count=5`, `review_allowed=false`, `can_submit_orders=false`,
  and `execution_authority=none`.
- Refreshed `results\_context\latest-summary.json` still flags the intended
  hourly/BOARD/loss-review drilldowns only, and the hourly summary still merges
  the current matching evidence packet.
- `uv run --no-sync --with pytest python -m pytest tests/test_loss_review_evidence.py tests/test_automation_context_snapshot.py -q`
  passed with 63 tests.
- Targeted Ruff passed; process review
  `results\process_reviews\process-review-20260607-032651.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

## 27. Overnight Verification Compact Sidecar Checkpoint

The overnight verification packet is now compact-context first. Before this
checkpoint, `results\_context` had to summarize the raw
`results\overnight_system_verification\latest.json` verifier packet, which
included full evidence for every overnight, premarket, hourly, tournament, and
automation check. That was useful for debugging but wasteful for routine morning
agent routing.

`cli\main.py` now writes `latest-compact.json` and timestamped `.compact.json`
sidecars for `alpaca verify-overnight-system`. The compact sidecar carries the
verifier state needed for control-plane decisions: overall status, status
counts, failed/warned checks, raw packet path, overnight top symbol and graph
success counts, freshness, automation-contract summary, original
TradingAgents graph status, premarket fresh-validation checklist status,
hourly and paper-tournament zero-submit checks, simulated pre-open status, and
explicit `can_submit_orders=false` / `execution_authority=none`.

`scripts\automation_context_snapshot.py` now prefers the compact sidecar for
`overnight_verification`; it flags a drilldown for any warning or failed check.
It also reads compact loss-review `advisory_summary` as a fallback to the old
raw `advisory_analysis`, preserving the hourly
`loss_review_current_thesis_status_candidate` field after the compact payload
trim.

Fresh proof:

- `.\.venv\Scripts\tradingagents.exe alpaca verify-overnight-system --json-output`
  wrote
  `results\overnight_system_verification\overnight-system-verification-20260606-224410.json`
  and refreshed `results\overnight_system_verification\latest-compact.json`.
- Raw `latest.json` is `10,346` bytes; compact `latest-compact.json` is
  `3,680` bytes.
- The compact verifier reports `overall_status=pass`, `check_count=15`,
  `failed_checks=[]`, `warned_checks=[]`, `top_symbol=XOM`,
  `full_graph_success_count=3`, `premarket_compact_item_count=5`,
  `can_submit_orders=false`, and `execution_authority=none`.
- Refreshed `results\_context\latest-summary.json` reads
  `overnight_verification` from `latest-compact.json` at about `920` tokens and
  adds no overnight drilldown flag.
- Refreshed hourly compact context again shows
  `loss_review_current_thesis_status_candidate` from the current compact
  loss-review evidence sidecar.
- `uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_alpaca_cli.py::test_verify_overnight_system_audits_full_chain -q`
  passed with 62 tests.
- Targeted Ruff passed; process review
  `results\process_reviews\process-review-20260607-034618.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

## 28. Daily-Report Compact Audit Discovery Checkpoint

The compact daily-report writer existed, but the compact-output audit still had
a blind spot: it searched only the root `results\daily_reports` directory. The
current automation/n8n path writes daily-report packets under namespaced
subdirectories such as `results\daily_reports\n8n`, so the audit reported the
daily-report family as `missing` despite a valid raw packet being present.

`_latest_packet_path(...)` now has an opt-in `recursive` mode. The
`supervisor_daily_report` row in `alpaca compact-output-audit` uses recursive
discovery, while hourly, overnight, premarket, and automation-health rows keep
their existing root/latest behavior. This avoids mixing unrelated probe
families while allowing the audit to measure the real daily-report layout.

Fresh proof:

- `.\.venv\Scripts\tradingagents.exe alpaca compact-output-audit --json-output`
  wrote
  `results\token_efficiency\compact-output-audit-20260606-225850-079574.json`.
- The audit now reports `row_count=5`, `measured_count=5`, and every row
  `lossless_by_reference=true`.
- The daily-report row now points to
  `results\daily_reports\n8n\supervisor-daily-report-20260604-000811-878577.json`,
  reducing `133,407` raw bytes to `2,141` compact bytes (`98.4%` reduction).
- `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py::test_compact_output_audit_measures_packet_families tests/test_alpaca_cli.py::test_compact_output_audit_finds_nested_daily_report_packets -q`
  passed with 2 tests.
- Targeted Ruff passed; process review
  `results\process_reviews\process-review-20260607-035916.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

## 29. Pre-Open Validation Packet Checkpoint

The premarket brief already listed the required fresh validations, but morning
automation still needed a concrete packet proving those validations were read
from current broker/context state. Without that packet, a future supervisor
could see a good-looking brief and skip the actual quote/order/position/sizing
checks the brief explicitly requires.

`cli\main.py` now exposes `alpaca preopen-validation`. The command is
analysis-only and writes raw plus compact packets under
`results\preopen_validation\`. It reads live and paper Alpaca account state,
positions, and open orders; fetches the current candidate market-data snapshot;
validates the latest premarket brief and overnight plan against current
candidates; reads `results\policy\live_control.json`; parses
`config\risk_envelope.yaml`; and records five checks:

- `premarket_quotes_and_spreads`
- `overnight_and_morning_news_social_deltas`
- `open_live_and_paper_orders`
- `current_positions_and_pl`
- `live_sizing_room_and_buying_power`

The packet contract is deliberately non-executing:
`analysis_only=true`, `can_submit_orders=false`,
`execution_authority=none`, and `submitted_count=0`. It does not refresh
live-control, send email, mutate automations, or submit orders.

`scripts\automation_context_snapshot.py` now includes a compact
`preopen_validation` summary and flags a raw-packet drilldown only when checks
fail, warn, or skip. `config\n8n_tradingagents_allowlist.json` adds the
read-only `preopen_validation_preview` job, and
`tradingagents\orchestration\n8n_policy.py` allows that Alpaca command only
with `--no-write-latest`, `--json-output`, and `--compact-json-output`.

Fresh proof:

- `.\.venv\Scripts\tradingagents.exe alpaca preopen-validation --json-output`
  wrote
  `results\preopen_validation\preopen-validation-20260607-035809.json`.
- The real packet reports `overall_status=pass_with_warnings`,
  `failed_check_ids=[]`, `market_session=closed`, `top_symbol=XOM`,
  0 open live orders, 0 open paper orders, 4 live positions, 14 paper positions,
  and live buying power `$86.38`.
- The only warning is expected fail-closed live authority:
  `live_sizing_room_and_buying_power` warns because the live-control dead-man
  expired at `2026-06-04T19:57:06+00:00`.
- The only skip is calendar-honest:
  `premarket_quotes_and_spreads` skips because the market session was closed.
- `.\.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner
  --run-job preopen_validation_preview --json` returned `status=ok`,
  `submit_capable=false`, and parsed
  `results\preopen_validation\n8n\preopen-validation-20260607-035839.json`.
- `results\_context\latest-summary.json` now includes
  `preopen_validation` from `results\preopen_validation\latest-compact.json`
  with the same warn/skip state and a raw packet pointer.

## 30. Pre-Open Closed-Market De-Noise Checkpoint

The pre-open validation packet correctly records warning/skip state when run
while the market is closed and live control is intentionally fail-closed. But
the compact context was treating that expected state as a stale drilldown,
creating a false morning-readiness flag even though there was no failed check
and no order authority.

`scripts\automation_context_snapshot.py` now distinguishes expected deferred
pre-open validation from real stale pre-open validation. If the market session
is non-tradeable, the only skipped check is `premarket_quotes_and_spreads`, the
only warning is `live_sizing_room_and_buying_power`, and there are no failed
checks, compact context sets:

- `deferred_for_closed_market=true`
- `fail_closed_live_control_warning_only=true`
- `drilldown_required=false`

Raw packets still preserve the warning and skip details for audit/debugging.
During actual `pre_open` or other tradeable sessions, warning/skip states still
produce a drilldown.

Fresh proof:

- `python scripts\automation_context_snapshot.py --write` refreshed compact
  context.
- `results\_context\latest-summary.json` shows `preopen_validation` with
  `overall_status=pass_with_warnings`, `market_session=closed`,
  `warned_check_ids=["live_sizing_room_and_buying_power"]`,
  `skipped_check_ids=["premarket_quotes_and_spreads"]`,
  `deferred_for_closed_market=true`, and no drilldown reasons.
- `results\_context\latest-flags.json` now contains only the intended
  hourly/BOARD/loss-review review flags.
- `uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py::test_snapshot_summarizes_compact_preopen_validation tests/test_automation_context_snapshot.py::test_snapshot_flags_preopen_validation_warnings tests/test_automation_context_snapshot.py::test_snapshot_defers_closed_market_preopen_validation_warning -q`
  passed with 3 tests.
- Targeted Ruff passed; process review
  `results\process_reviews\process-review-20260607-040621.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

## 31. n8n Evaluation Data Table Refresh Checkpoint

The n8n evaluation dataset grew after the `preopen_validation_preview` wrapper
was added: current dataset proof is 210 rows across 23 allowlisted jobs. The
previous n8n Data Table sync proof still covered 201 rows across 22 jobs, so
compact context correctly opened an `n8n_evaluation_dataset` audit drilldown
with `sync_current_row_count_matches=false`.

The direct sync command without `N8N_API_KEY` failed closed and redacted the
missing-key condition. Codex then followed the documented local fallback:
copy the running n8n container's `/home/node/.n8n/database.sqlite` to a
temporary file, pass that copy with `--api-key-sqlite-db`, and delete the copy
immediately after the sync. The proof packet records only the redacted key
source label.

Fresh proof:

- `research n8n-sync-evaluation-table --api-key-sqlite-db <temp-copy>
  --json-output` wrote
  `results\n8n_evaluations\n8n-api-sync-20260607-041459-118935.json`.
- The proof reports `status=ok`, `expected_row_count=210`,
  `inserted_count=210`, `final_row_count=210`, `row_count_matches=true`,
  `api_key_redacted=true`, `analysis_only=true`, `can_submit_orders=false`,
  and `execution_authority=none`.
- The temporary copied DB was deleted; `Test-Path` returned `False`.
- Refreshed `results\_context\latest-summary.json` reports
  `n8n_evaluation_dataset.row_count=210`,
  `sync_expected_row_count=210`, `sync_final_row_count=210`,
  `sync_current_row_count_matches=true`, and no n8n drilldown reasons.
- Refreshed `results\_context\latest-flags.json` contains only the intended
  hourly/BOARD/loss-review review flags.
- Process review
  `results\process_reviews\process-review-20260607-041528.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

## 32. Automation Prompt Live-Posture Alignment Checkpoint

The repo-level pre-open validation command was not enough by itself: the
app-level TradingAgents market/report automation prompts still carried stale
live-budget wording from the prior no-cap phase, and the pre-open supervisor did
not yet require `alpaca preopen-validation` before the submit-capable dry-run.

Codex updated the following automations through the Codex automation tool while
preserving status, schedule, model, reasoning effort, execution environment, and
cwd:

- `hourly-market-supervisor`
- `market-supervisor-15-min-before-open`
- `market-supervisor-30-min-after-open`
- `market-supervisor-30-min-before-close`
- `market-supervisor-15-min-after-close`
- `tradingagents-daily-market-report`

The pre-open supervisor now runs:

1. `alpaca check`
2. `alpaca premarket-brief --json-output`
3. `alpaca preopen-validation --json-output`
4. read `results/preopen_validation/latest-compact.json`
5. hourly dry-run
6. guarded submit only when dry-run and required pre-open checks are clean

All updated market/report prompts now read live authority from current
`config/risk_envelope.yaml`, `results/policy/live_control.json`, broker buying
power, and the unified live gate. They explicitly avoid stale memory-based cap
assumptions.

Fresh proof:

- Post-update automation text search found the `preopen-validation` requirement
  in `market-supervisor-15-min-before-open`.
- The same search found no remaining stale no-cap keyword in automation TOMLs.
- `.\.venv\Scripts\tradingagents.exe research automation-health-audit
  --json-output` wrote
  `results\automation_health\automation-health-audit-20260607-042251.json`
  with `automation_count=13`, `ok_count=13`, `issue_count=0`, and
  `submitted_order_count=0`.
- The self-heal monitor still reports timely follow-up within the 30-minute SLA;
  the audit records one overlap-run issue type but classifies the automation as
  `ok` with no live/order issue.

## 33. Overnight Source-Quality Routing Checkpoint

Source-quality review was visible in compact context but not threaded into the
overnight provider path before ranking. The overnight context now loads
`results/source_quality/latest.json`, passes source-quality strengths into
provider fallback ordering, writes a bounded
`research_context.watchlists.source_quality` advisory, and includes the same
summary in the compact overnight prior feed. This keeps stale/low-quality
research downranking inside the overnight packet instead of relying on a
separate dashboard flag.

n8n remains a wrapper/dashboard layer: `overnight_plan_compact_preview` now runs
`research source-quality-review --json-output --compact-json-output` first, then
the existing no-latest/no-ledger/no-research-context overnight preview. The
n8n runner now requires `schema=compact_overnight_plan_v1` before adding an
overnight parsed summary, so the source-quality step cannot masquerade as an
overnight plan.

The app-level `tradingagents-overnight-planning` automation prompt was updated
through the Codex automation tool without changing status, schedule, model,
reasoning effort, execution environment, or cwd. It now refreshes source
quality before ranking and passes `--source-quality-review-path
results/source_quality/latest.json --source-quality-ordering` into both
`alpaca plan-overnight` and the post-ranking ticker provider bundles.

Fresh proof:

- Focused pytest command for source-quality, provider ordering, overnight CLI
  context, and n8n preview behavior passed: 15 tests.
- Targeted Ruff over the touched Python files/tests passed.
- No-latest/no-ledger/zero-full-graph overnight probe wrote
  `results\overnight_plans\source_quality_probe\overnight-plan-20260607-044822-000000.json`
  with `submitted_count=0`, `research_context_packet_count=14`,
  `research_context_blocked_count=0`, source-quality ordering enabled,
  16 scored sources, `source_count=250`, `stale_count=43`,
  `stale_downrank_count=23`, and `stale_needs_refresh_count=0`.
- `python -m tradingagents.orchestration.n8n_runner --run-job
  overnight_plan_compact_preview --json` returned `status=ok`, two steps, and
  `submit_capable=false`.
- `research automation-health-audit --json-output --compact-json-output` wrote
  `results\automation_health\automation-health-audit-20260607-045136.json`
  with `automation_count=13`, `ok_count=13`, `issue_count=0`,
  `submitted_order_count=0`, and timely self-heal follow-up.
- `research process-review --json-output` wrote
  `results\process_reviews\process-review-20260607-045136.json` with
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
- After a stale n8n evaluation-test expectation was updated for the new
  two-command overnight preview, the full repo gate passed:
  `uv run --no-sync --with pytest python -m pytest -q` -> `980 passed`,
  `1 skipped` (live DeepSeek API key not set), `9 warnings`, and `75 subtests
  passed`.

## 34. Claude Deep-Review Handoff Prep Refresh

The Claude submit-path review response has been re-verified against current
repo state. The active branch is still `wip/submit-path-hardening-2026-06-05`,
and `3970998` remains a two-file standalone commit for
`tradingagents/policy/order_rate_limit.py` and
`tests/test_order_rate_limit.py`. The shared hardening diff is still entangled
with broader uncommitted work, so the landing rule remains selective staging and
review by file/hunk only.

Current live posture remains fail-closed: `config/risk_envelope.yaml` parses as
`live_budget_mode=autonomous_with_caps`, account cap `$250`, per-name cap `$50`,
with optional hard-ceiling/rate-limit knobs unset. The live-control dead-man is
still expired at `2026-06-04T19:57:06+00:00`, so no live submit should be
possible without an intentional operator refresh. Git ignore hygiene still
protects `config/risk_envelope.yaml`, `.claude/`, `setup_n8n.py`, and
`analysis_mypy.txt`, while `.codex/hooks` stays visible for hook review.

Current compact context prep is clean for this handoff: the stale
`agent_intelligence_summary` schema flag is cleared after refreshing the ledger,
with 3,648 ledger records matching the summary, 10 influence-weighted agents,
and zero resolved forecasts. The only current drilldown flags are the expected
hourly/BOARD/loss-review evidence review paths.

## 35. n8n Model-Route Health and Lock-Recovery Checkpoint

The n8n observer layer now includes a read-only model/source orchestration
health job: `research_automation_orchestration_plan`. It calls
`research automation-orchestration-plan --candidate-symbols XOM,ADBE,CVX
--no-research-context --json-output`, has `submit_capable=false`, and is parsed
down to compact dashboard fields rather than exposing the full research packet.
The parser preserves model/helper route statuses, Mac Ollama reachability and
expected model, quality-gate state, fallback action count, blocker count,
telemetry ref count, and packet path.

Real runner proof found a control-plane failure mode: an ownerless
`results\_context\n8n-runner.lock` directory blocked the new job. The repo-local
run-lock helper now recovers ownerless lock directories after a short grace
period and chmods stale lock directories before removing them, which fixes the
Windows cleanup case without weakening owner-bearing lock protection.

Fresh proof:

- `python -m tradingagents.orchestration.n8n_runner --list-jobs --json` reports
  24 allowlisted jobs and `submit_capable_count=0`.
- `python -m tradingagents.orchestration.n8n_runner --run-job
  research_automation_orchestration_plan --json` recovered the orphan lock and
  returned `status=ok`, `lock_stale_recovered=true`, `blocker_count=0`,
  `research_quality_high_enough=true`, `fallback_required=false`,
  `optional_helper_degraded=true`, degraded helper lanes
  `windows_local` and `mac_ollama`, Mac expected model `deepseek-r1:14b`, and
  `execution_authority=none`.
- `research n8n-evaluation-dataset --json-output --compact-json-output` wrote
  `results\n8n_evaluations\n8n-evaluation-dataset-20260607-054313-903039.json`
  with 219 rows, 24 jobs, and 17 edge tags.
- `research n8n-sync-evaluation-table --api-key-sqlite-db <temp-copy>
  --json-output` refreshed the local n8n Data Table to 219 rows at
  `results\n8n_evaluations\n8n-api-sync-20260607-054521-434145.json`; the API
  key remained redacted and the temporary SQLite copy was deleted.
- Refreshed compact context cleared the n8n evaluation audit flag. Current
  drilldowns are hourly/BOARD/loss-review plus model telemetry because both
  local helper lanes are down; that is a degraded helper signal, not a submit
  blocker.
- Focused proof passed with 84 n8n/model tests, targeted Ruff passed, and
  process review `results\process_reviews\process-review-20260607-054548.json`
  reports `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

## 36. Local Helper Model Self-Heal Timing Checkpoint

The model-route observer now has a specific safe-plane signal for "all local
helper model lanes are down." A single missing optional helper remains advisory,
but when both `mac_ollama_research_mule` and `windows_local_ollama` are blocked
and neither is selected, compact context sets `local_helper_repair_signal=true`
and raises `model_telemetry`. This preserves the research fallback path while
making the repair timely enough for the self-heal monitor.

Real route proof on 2026-06-07:

- `research automation-orchestration-plan --candidate-symbols XOM
  --no-research-context --output-dir
  results/research_batches/model_route_health --model-telemetry-dir
  results/model_telemetry --json-output` exited 0 and wrote
  `results\research_batches\model_route_health\research-batch-research-batch-594482b4004044e69a433fa3ebdb6bd0.json`.
- The Mac lane is correctly configured as the 32 GB helper route with
  `deepseek-r1:14b`, but `http://macbook-pro.tail37edd7.ts.net:11434/api/tags`
  timed out from Windows. It must stay degraded/fallback until the Mac/Tailscale
  endpoint is reachable again.
- The Windows local lane is still blocked because
  `TRADINGAGENTS_WINDOWS_OLLAMA_URL` is not configured.
- Deterministic helpers and the Codex/ChatGPT judgment route stayed usable, so
  `research_quality_high_enough=true`, `fallback_required=false`,
  `execution_authority=none`, and `can_submit_orders=false`.

The self-heal action for `model_telemetry` now executes only allowlisted
safe-plane commands: route probe, model telemetry report, and compact context
refresh. The real executor wrote
`results\self_heal\plans\self-heal-plan-20260607-055123.json` with
`executed_count=1`, `verified_count=1`, `verify_failed_count=0`, and
`skipped_escalated_count=2`, proving it verified the model-route repair path and
did not touch order-adjacent BOARD signals. Follow-up health gates also passed:
`results\automation_health\automation-health-audit-20260607-055213.json`
reports 13/13 automations OK and timely self-heal follow-up, and
`results\process_reviews\process-review-20260607-055212.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
Focused self-heal, automation-health, and model-routing regression proof passed
with 74 tests.

## 37. P5 n8n Compact-Output Adoption Proof

The high-traffic n8n observer/dashboard jobs now have fresh real-run proof that
they are compact-output consumers, not raw packet expanders or submit paths.

- `python -m tradingagents.orchestration.n8n_runner --run-job
  daily_report_preview --json` returned `status=ok`,
  `compact_output_only=true`, and `submit_capable=false`. The parsed summary
  exposed the daily-report subject, top candidate `MSFT`, body length, and raw
  packet pointer
  `results\daily_reports\n8n\supervisor-daily-report-20260607-011853-293175.json`.
- A concurrent `compact_output_audit` attempt returned `status=busy` against
  the active n8n runner lock, proving wrapper jobs serialize instead of
  overlapping.
- Retrying `compact_output_audit` by itself returned `status=ok`,
  `compact_output_only=true`, `submit_capable=false`,
  `execution_authority=none`, and wrote
  `results\token_efficiency\compact-output-audit-20260607-011933-987395.json`
  plus `results\token_efficiency\compact-output-audit-20260607-011933-987395.md`.
  The audit measured 5 packet families and reduced 6,798,235 raw bytes to 11,516
  compact bytes by reference.
- Focused regression passed:
  `uv run --no-sync --with pytest python -m pytest
  tests/test_alpaca_cli.py::test_alpaca_supervisor_daily_report_compact_json_writes_raw_packet
  tests/test_alpaca_cli.py::test_compact_output_audit_measures_packet_families
  tests/test_alpaca_cli.py::test_compact_output_audit_finds_nested_daily_report_packets
  tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_compact_daily_report_json
  tests/test_n8n_evaluations.py -q` -> 15 passed.

## 38. P2 Walk-Forward Guard Refresh and n8n Lock Release Repair

The current mature overnight cohort was refreshed instead of relying on older
June 6 calibration evidence. `research walk-forward-refresh-overnight-cohort
--json-output` wrote
`results\research_batches\walk_forward_cohort_refresh_20260607-062755_h3.json`
from 12 mature overnight packets, 175 return rows, 420 fixture rows, and replay
packet `results\research_batches\research-batch-research-batch-d53dae27b36b4a67b2d729ab8f114e69.json`.
The evidence supports a tighter overnight-influence posture, not promotion:
deterministic sleeve accuracy `0.3119`, deterministic action-relative return
`-1.2219`, TradingAgents overlay accuracy `0.5000`, and TradingAgents overlay
false-positive rate `0.5000`.

`research overnight-calibration-guard --json-output` then wrote
`results\overnight_calibration\overnight-calibration-guard-20260607-062907.json`
with `guard_decision=tighten`, `can_increase_live_influence=false`,
`new_buy_permission=controlled_dip_support_reclaim_only`,
`replacement_buy_permission=disabled_unless_fresh_independent_setup`, and
`sell_permission=independent_profit_or_board_approved_exit_only`.
This preserves the buy-dip/sell-spike and independent sell/buy policy while the
weak walk-forward cohort matures.

Real n8n wrapper proof found and repaired a small Windows control-plane
cleanup gap. After a successful observer pass, an ownerless
`results\_context\n8n-runner.lock` directory could remain briefly and make the
next serial job report `status=busy`. `tradingagents\orchestration\run_lock.py`
now chmods the lock directory before release cleanup, and
`tests\test_n8n_runner_policy.py` pins that read-only lock directories are
removed after successful jobs. Real runner proof:

- `overnight_calibration_guard` returned `status=ok`,
  `submit_capable=false`, `fixture_row_count=420`, and the tighten policy.
- Parallel `agent_ledger_update` and `outcome_labeling` attempts returned
  `status=busy`, proving the lock still prevents overlapping work.
- Serial `agent_ledger_update` recovered the stale ownerless lock with
  `lock_stale_recovered=true`, returned `forecast_count=3670`,
  `resolved_forecast_count=0`, and `execution_authority=none`.
- Serial `outcome_labeling` returned `status=ok`, `model_outcomes` unresolved
  for 156 model packets, and left no `n8n-runner.lock` directory behind.
- Focused proof passed with 35 P2/n8n/ledger tests; targeted Ruff passed.

## 39. Real Department Simulation Audit With Actionable Samples

The live-data dry-run department audit was rerun after the n8n lock fix. The
full default pass
`results\real_simulation_audits\real-simulation-audit-20260607-064030.json`
covered 8 departments and 28 commands. It exited with
`failed_command_count=0`, `commands_missing_structured_output=[]`,
`total_submitted_order_count=0`, `unsafe_submission_evidence=false`,
`all_commands_clean=true`, `all_structured_output_present=true`, and
`core_accepted=true`. The only non-green strict condition is optional:
`mac_deepseek_available=false` because the Mac Ollama tags endpoint timed out.

The audit summarizer now includes bounded `attention_samples` on each command
result. This fixes a practical observability gap where source quality could show
20 blockers and only counts. A real one-symbol verification pass
`results\real_simulation_audits\real-simulation-audit-20260607-064912.json`
proved the new field on real output: source-quality blocker samples identify
fresh local research-gap packets such as `options_iv_flow_gap`,
`short_interest_gap`, and `earnings_transcripts_gap`, plus stale low-quality
`yfinance_options` rows. The same audit still accepted the core path:
8 departments, 26 commands, 0 failures, 0 submitted orders, no unsafe submission
evidence, and stale sources downranked or otherwise safe.

The one-symbol audit exposed a stale `loss_review_evidence` compact flag during
self-heal planning. Codex refreshed loss-review evidence and BOARD rather than
leaving the safe-plane flag for the next automation:

- `research loss-review-evidence --json-output` wrote
  `results\loss_review_evidence\source-evidence-source-evidence-6cd6b53f19814032bc847dcd51dac467.json`
  for `TSM`, matched to latest hourly packet
  `results\hourly_supervisor\hourly-supervisor-20260607-065131-399090.json`.
- The refreshed evidence has `entry_context_found=true`,
  `resolved_blocker_count=8`, `remaining_blocker_count=5`, and
  `review_allowed=false`.
- `research execution-board-review --json-output` wrote
  `results\execution_board\execution-board-review-20260607-065350.json` with
  0 hard violations, 0 submitted orders, and the independent sell/buy policy
  intact.
- `research self-heal-plan --execute-safe --json-output` had no safe-plane
  action left after the refresh; it only escalated order-adjacent BOARD review.
- Refreshed compact context now has exactly three intentional BOARD/loss-review
  flags and no stale, n8n, model, source-quality, process, or self-heal repair
  flags.

Focused proof: `tests/test_real_simulation_audit.py` plus the source-quality
compact test passed with 14 tests, and targeted Ruff passed over the touched
audit/test files.

## 38. BOARD Loss-Review Evidence and Email Clarity Checkpoint

The latest Claude submit-path review remains prepared as a fail-closed
operating constraint, and the current BOARD path now has matching evidence for
the open TSM loss-review instead of relying on stale blocker text.

`execution-board-review` reads the latest matching
`results/loss_review_evidence` packet, attaches `loss_review_evidence` to the
review, and raises `loss_review_evidence_pending` when the refreshed evidence
still lacks thesis-break confidence or an allowed loss-exit rationale. The Risk
Chair language now keeps HOLD/default cash as the posture until BOARD can prove
that selling is better than holding. New buys remain independent and limited to
separate controlled dip/support setups; a loss exit does not force a replacement
buy, and profit sells remain independent.

The hourly supervisor carries that BOARD `loss_review_evidence` summary into
`decision.evidence`, so loss-review alert emails use refreshed counts instead
of the stale immediate `loss_exit_review` blocker count. The current email says
5 evidence items remain open after refresh, 8 were resolved, HOLD remains the
default, and no live loss sell was submitted. Email clarity proof
`results\email_clarity\email-clarity-20260607-061818.json` passed with score
100, 24 lines, max line length 176, and no issues.

Fresh proof:

- `alpaca check` passed for both paper and live read-only accounts.
- `alpaca supervise-hourly --dry-run --json-output --compact-json-output`
  wrote
  `results\hourly_supervisor\hourly-supervisor-20260607-061747-678303.json`
  with `submitted_count=0`, `can_submit_orders=false`,
  `execution_authority=none`, and a loss-review HOLD decision.
- `research loss-review-evidence --json-output` wrote
  `results\loss_review_evidence\source-evidence-source-evidence-dd9b26c629cc4b27924cbd505fe826a0.json`
  targeting that latest hourly packet, with 8 blockers resolved and 5
  remaining.
- `research execution-board-review --json-output` wrote
  `results\execution_board\execution-board-review-20260607-062012.json`,
  matched the latest hourly packet, found 0 hard issues and 2 warnings, and
  preserved independent sell/buy policy.
- `research automation-health-audit --json-output --compact-json-output` wrote
  `results\automation_health\automation-health-audit-20260607-061947.json`
  with 13/13 automations OK and timely self-heal follow-up.
- Focused regression passed: 113 tests across model telemetry, self-heal,
  execution BOARD, supervisor, and CLI slices; targeted Ruff passed; process
  review `results\process_reviews\process-review-20260607-062041.json`
  reports `unchecked_step_count=0` and no findings.

Current compact context still flags hourly/BOARD/loss-review because TSM
remains a true pending loss-review, not because an order was submitted or the
email is stale. It no longer flags model telemetry: Windows local Ollama is
selected successfully with
`tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest`, while the Mac
`deepseek-r1:14b` helper remains degraded by Tailnet timeout.

## 40. n8n Native Evaluation Run-Probe Checkpoint

The n8n evaluation control plane now has a first-class proof packet for native
Evaluation Trigger run availability. `research n8n-evaluation-run-probe
--json-output` lists local n8n workflows, probes the public run/test-run routes
for `TA · Built-in Automation Evaluation`, and writes redacted evidence to
`results\n8n_evaluations\latest-run-probe.json`. The command is analysis-only,
sets `can_submit_orders=false`, uses `execution_authority=none`, and never
activates workflows or calls broker commands.

Fresh real proof against the running local n8n container wrote
`results\n8n_evaluations\n8n-evaluation-run-probe-20260607-065656-414493.json`.
The workflow exists as `taBuiltInAutomationEvaluation`, but the public routes
are not supported for starting native evaluation runs: `/test-runs` returned
`405`, `/test-runs/new` returned `404`, `/run` returned `405`, and `/execute`
returned `405`. The packet therefore reports `status=editor_required`,
`editor_run_required=true`, `supported_endpoint_count=0`,
`api_key_redacted=true`, and no order authority. The temporary copied SQLite DB
used to read the local n8n API key was deleted.

Compact context now carries `run_probe_status`, `run_probe_editor_required`,
`run_probe_supported_endpoint_count`, `run_probe_api_key_redacted`, and
`run_probe_path` inside the `n8n_evaluation_dataset` summary. This keeps future
agents from reopening full n8n packets unless the run-probe is broken or
unsafe. The probe remains a direct CLI/context proof rather than an allowlisted
n8n runner job, because it needs an API-key source and the runner should not be
forced to own that secret. Fresh job discovery still reports 24 allowlisted jobs
and `submit_capable_count=0`. Focused proof passed:

- `tests/test_n8n_evaluations.py` -> 14 passed.
- n8n/context focused slice -> 17 passed.
- Targeted Ruff over the new probe module, CLI, compact context, and tests ->
  passed.

## 41. Loss-Review Thesis-Status Classifier Checkpoint

The BOARD/loss-review path now resolves one more real evidence gap without
granting execution authority. `tradingagents.research.loss_review_evidence`
classifies the current thesis as
`thesis_under_pressure_falling_knife_watch` when refreshed candidate evidence is
falling-knife/sharp-drop, the prior live entry was momentum/time-sensitive, and
the current position is below average entry. The compact loss-review packet now
includes `thesis_status_evidence` so n8n, hooks, execution BOARD, and email
translation can use the small packet instead of reopening raw evidence.

Safety invariant: this is advisory only. It resolves the missing thesis-status
blocker, but `review_allowed_after_refresh` remains false and loss exits still
need an allowed loss-exit reason, source, confidence, and a tradeable market
session.

Fresh real proof:

- `research loss-review-evidence --json-output` ->
  `results\loss_review_evidence\source-evidence-source-evidence-f1d9dc5e8a8045ddb2120b4396d5dc35.json`,
  `review_allowed=false`, `execution_authority=none`, 9 blockers resolved, 4
  blockers remaining.
- `research execution-board-review --json-output` ->
  `results\execution_board\execution-board-review-20260607-073717.json`, 0
  submitted orders, 0 hard violations, loss-review evidence still pending.
- `results\loss_review_evidence\latest-compact.json` now carries
  `current_thesis_status_candidate=thesis_under_pressure_falling_knife_watch`
  and the three drivers in `thesis_status_evidence`.
- Focused tests passed: loss-review/execution-board/context `81 passed`.
- Targeted Ruff passed.
- Process review:
  `results\process_reviews\process-review-20260607-073804.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

## 42. Pre-Open Submit Gate Code Enforcement Checkpoint

The pre-open validation requirement is now enforced in code, not only in
automation prompt order. `alpaca supervise-hourly` accepts
`--preopen-validation-dir` (default `results/preopen_validation`) and, during
`market_session=pre_open`, a `--submit-actions` run must have a latest pre-open
validation packet that is fresh, `overall_status=pass`, `market_session=pre_open`,
and has no failed, warned, or skipped checks. Otherwise the supervisor converts
the decision to `blocked` with a `preopen-validation` `OrderIssue` before the
live-submit validation/tiny-live guard path can run. The packet summary is also
included in hourly evidence for audit/email translation.

This closes the gap where the pre-open supervisor prompt required:

1. `alpaca check`
2. `alpaca premarket-brief --json-output`
3. `alpaca preopen-validation --json-output`
4. read `results/preopen_validation/latest-compact.json`
5. hourly dry-run
6. guarded submit only when pre-open checks are clean

but the submit-capable CLI path itself did not enforce step 4. Dry-run behavior
remains analysis-only; the gate only blocks submit-capable pre-open runs.

Fresh proof:

- TDD red: the new tests failed because `--preopen-validation-dir` did not
  exist.
- New tests now pass: missing validation blocks before tiny-live guard; clean
  validation permits the pre-open submit path.
- Focused hourly/pre-open submit slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -k
  "preopen or supervise_hourly_live or supervise_hourly_paper_first or
  supervise_hourly_dry_run or supervise_hourly_compact" -q` -> `12 passed`.
- n8n/preopen/overnight policy slice -> `5 passed`.
- Targeted Ruff over `cli\main.py` and `tests\test_alpaca_cli.py` -> passed.
- Real dry-run probe:
  `results\hourly_supervisor\preopen_gate_probe\hourly-supervisor-20260607-075610-009451.json`,
  `submitted_count=0`, `can_submit_orders=false`.
- Process review:
  `results\process_reviews\process-review-20260607-075731.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

## 42. Model Telemetry Context-Window Checkpoint

The pipeline now carries model context-window metadata through model telemetry
as well as route selection and overnight graph config. `ModelRunTelemetryPacket`
records `context_window_tokens`; model telemetry rollups and compact reports
preserve it in `current_route_statuses`, including explicit `null` for
custom/local routes where capacity is unknown. This gives dashboards and n8n
evaluation workflows a stable schema for route suitability.

Fresh proof: model catalog/routing tests `29 passed`, targeted Ruff passed, and
a real analysis-only orchestration/telemetry probe wrote
`results\research_batches\model_catalog_context_probe\research-batch-research-batch-29a3904622ac46279b1334ad61fc502d.json`
plus
`results\model_telemetry_reports\model-telemetry-report-20260607-074452-543468.json`.
Current model route status: Windows local Ollama success, Mac DeepSeek blocked
by tags-endpoint timeout, deterministic helpers success, Codex/ChatGPT external
fallback, no trading authority.

## 51. Local Helper Context-Window Inference

The prior model-telemetry schema repair was not enough for the current morning
packet: historical telemetry packets could still have `context_window_tokens`
set to `null` even when their provider/model was now known. That meant the
automation summary could not distinguish a 4k helper lane from an unknown
custom lane without opening docs.

Follow-up implementation:

- `tradingagents/llm_clients/model_catalog.py` now records conservative
  operational windows for the repo-local Ollama helper aliases:
  `tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k[:latest] -> 4096` and
  `deepseek-r1:14b -> 4096`.
- `tradingagents/research/model_telemetry.py` enriches current-route status
  rows from the catalog when raw packets have missing context-window metadata.
- Unknown/custom external and deterministic lanes remain `null` rather than
  guessed.

Fresh proof:

- Focused tests: `tests/test_model_catalog.py tests/test_model_routing.py`
  -> `31 passed`.
- Targeted Ruff over the catalog/telemetry modules and tests -> passed.
- Real packet:
  `results\model_telemetry_reports\model-telemetry-report-20260607-093720-965799.json`.
- Current compact/context rows now show both local helper routes with
  `context_window_tokens=4096`, while the Mac lane remains correctly blocked as
  `mac_host_unreachable` and Windows local Ollama remains selected/successful.

This is route-evidence metadata only. It does not alter model selection, broker
authority, schedules, credentials, or execution behavior.

## 43. Claude Submit-Path Review Prep

The Claude handoff remains loaded into the operating context. SAFE-01 is still
fail-closed with `autonomous_with_caps`, `$250.00` account cap, `$50.00`
per-name cap, `issues=[]`, and a lapsed dead-man
(`2026-06-04T19:57:06+00:00`). Commit `3970998` remains only the standalone
rate-limit module/test; broader submit-path hardening is still a dirty shared
worktree slice requiring hunk-level staging. No orders, emails, dead-man
refresh, credential change, automation status change, staging/commit, or
live-authority change occurred in this prep.

## 44. Overnight Next-Market-Date Checkpoint

The overnight pipeline now defaults weekend planning runs to the next weekday
instead of the previous Friday. This aligns the CLI with the active automation
contract, which runs on weekend nights specifically to prepare for the next
market open. Weekday overnight runs still use the local Central date.

Fresh proof:

- Direct helper sanity for Sunday `2026-06-07` returned `2026-06-08`.
- A real analysis-only isolated probe with `--no-write-latest` wrote
  `results\overnight_plans\date_probe\overnight-plan-20260607-080010-000000.json`
  with `trade_date=2026-06-08`, 40 ranked fallback candidates, and
  `submitted_count=0`.
- `alpaca verify-overnight-system --json-output` wrote
  `results\overnight_system_verification\overnight-system-verification-20260607-025548.json`
  with `overall_status=pass`, 3/3 full graph successes, top `CVX`, and graph
  config matching the active Gemini automation contract.
- `research creator-workflow-status --json-output` shows 3 complete creator
  workflows (`XOM`, `ADBE`, `CVX`), each with 9 roles and no execution
  authority.
- `research automation-health-audit --json-output --compact-json-output` wrote
  `results\automation_health\automation-health-audit-20260607-075551.json`
  with 13/13 automations OK and timely self-heal follow-up.

Focused proof passed: overnight CLI slice `4 passed`, connector/agent-ledger
context slice `2 passed`, and targeted Ruff passed. No orders, emails,
dead-man refresh, credential change, automation status change, staging/commit,
or live-authority change occurred.

## 45. Preopen Validation Freshness Checkpoint

Compact context now treats preopen validation as stale when it predates the
latest overnight or premarket brief packet. This fixes a morning-readiness
blind spot where a closed-market preopen validation could be quiet even after
new overnight research changed the top candidate from the older validation's
view. Closed-market warning de-noising remains in place for current packets.

Real proof after context refresh:

- `results\_context\latest-summary.json` reports
  `preopen_validation.stale_after_latest_context=true`.
- The stale comparison is explicit:
  preopen `generated_at=2026-06-07T03:58:09+00:00`, latest overnight
  `2026-06-07T07:48:58+00:00`, latest premarket
  `2026-06-07T07:53:22+00:00`.
- `results\_context\latest-flags.json` now includes
  `preopen_validation` with reason `stale`, alongside the intentional
  BOARD/loss-review drilldowns.
- Focused preopen/context tests `3 passed`; targeted Ruff passed; process
  review `results\process_reviews\process-review-20260607-081243.json`
  reports `unchecked_step_count=0`, `findings=[]`, and
  `can_submit_orders=false`.

This checkpoint is analysis/context-only and grants no execution authority.

## 46. Preopen And BOARD Freshness Repair

After the latest overnight and premarket packets, Codex ran the real
analysis-only preopen validation and refreshed the execution BOARD review
against the newest hourly packet. This repaired the freshness state rather than
leaving morning agents to inspect stale preopen/BOARD context.

Fresh proof:

- `alpaca preopen-validation --json-output` wrote
  `results\preopen_validation\preopen-validation-20260607-082431.json`.
  Compact context now reports `stale_after_latest_context=false`, `top_symbol=CVX`,
  `analysis_only=true`, `can_submit_orders=false`, and `submitted_count=0`.
- `research execution-board-review --json-output` wrote
  `results\execution_board\execution-board-review-20260607-082625.json`.
  It now matches the latest hourly packet, found zero hard violations, and kept
  the correct next-hour guardrail: sell decisions are independent from buys;
  loss exits free cash but do not force a same-run replacement buy; new buys
  need separate controlled dip/support evidence and no green-spike chasing.
- `results\_context\latest-flags.json` no longer contains
  `preopen_validation` stale or execution BOARD stale. Remaining flags are
  expected review signals for hourly/loss-review/BOARD.
- Automation health
  `results\automation_health\automation-health-audit-20260607-082521.json`
  reports 13/13 automations OK, zero issues, zero submitted orders, and timely
  self-heal follow-up.
- Process review
  `results\process_reviews\process-review-20260607-082704.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 63. Overnight Verifier Checks Source-Quality And Provider-Bundle Readiness

The overnight system verifier now checks two research-readiness contracts that
were previously only implied by adjacent artifacts:

- `overnight_source_quality_context` verifies the latest overnight packet
  carries `research_context.watchlists.source_quality`, source-quality ordering
  is enabled, stale sources needing refresh are zero, missing/invalid packets
  are zero, unreadable packets are zero, and the source-quality packet is not
  blocked.
- `overnight_top_provider_bundles` verifies broad provider-bundle coverage for
  the top ranked overnight candidates. It prefers embedded
  `top_provider_bundles` from newer overnight packets, and falls back to
  `results/_context/source-routing-compact.json` for already-produced packets
  whose bundle refreshes live in compact context.

Real proof:

- `.\.venv\Scripts\tradingagents.exe alpaca verify-overnight-system --json-output`
  wrote
  `results\overnight_system_verification\overnight-system-verification-20260607-184746.json`.
- The packet is `overall_status=pass`, `execution_authority=none`,
  `can_submit_orders=false`, and has no failed or warned checks.
- Source quality passed with 250 reviewed sources, 21 stale sources, 13
  stale-downranked, 0 stale needing refresh, 0 missing/invalid, and 0
  unreadable.
- Provider-bundle readiness passed for top symbols `XOM`, `CVX`, and `ADBE`
  through `results\_context\source-routing-compact.json`; `missing_symbols=[]`.
- Focused verifier/provider tests passed:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py tests/test_automation_context_snapshot.py -q -k "verify_overnight or provider_bundle"`
  -> `9 passed, 167 deselected`.
- Targeted Ruff over `cli/main.py` and `tests/test_alpaca_cli.py` passed.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## Tail Pointer: Ledger, Calibration, And Transcript Readiness (2026-06-07 22:07 UTC)

Claude's submit-path handoff remains prepared in the current worktree. SAFE-01
stays fail-closed in local machine state, and no live-control/dead-man/risk
authority was changed.

The analysis-only research feedback loop is current:

- `research agent-ledger-update --json-output` read the latest overnight packet
  and MiroFish handoff, confirmed `forecast_count=4582`,
  `discovered_forecast_count=130`, `appended_count=0`, and
  `resolved_forecast_count=0`. Agent influence weights stay at `1.00` until
  enough forecasts resolve.
- `research outcome-labeling --json-output` refreshed model telemetry at
  `results\model_telemetry_reports\model-telemetry-report-20260607-220600-406582.json`.
  Windows local Ollama is successful, deterministic helpers are successful, and
  the Mac `deepseek-r1:14b` lane remains skipped as `mac_host_unreachable`.
- `research overnight-calibration-guard --json-output` wrote
  `results\overnight_calibration\overnight-calibration-guard-20260607-220624.json`
  with `guard_decision=tighten`, `can_increase_live_influence=false`,
  controlled-dip/support-reclaim entry requirements, no green-spike chasing,
  sell/buy independence, source freshness, and anti-crowding confirmation for
  bot-copycat/crowded-AI names.

The previous overnight-target transcript gap is no longer the active compact
source-routing state. `tradingagents/research/youtube_transcript.py` provides a
read-only Docker MCP transcript route before FMP/gap fallback. Real proof:

- `XOM` transcript packet:
  `results\research_evidence\youtube_transcript_probe\source-evidence-source-evidence-107cb2c1d5bf4cf9b6c71c1e3af1cd78.json`.
- `CVX` summary:
  `results\research_evidence\source-evidence-source-evidence-43183b7d0f874a08bf384074a682e438.json`.
- `ADBE` summary:
  `results\research_evidence\source-evidence-source-evidence-fd80a8881c8c4e309cff9f6855424eb3.json`.
- `results\_context\source-routing-compact.json` now reports no overnight target
  symbols missing bundles and no target evidence needs without non-gap packets;
  `results\_context\latest-flags.json` has no `source_routing` flag.

Process review
`results\process_reviews\process-review-20260607-220707.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`. Safety
boundary held: no orders, no emails, no dead-man refresh, no credential changes,
no automation status changes, no staging/commit, and no live-authority changes.

## Tail Pointer: Fresh Overnight Control-Plane Sweep (2026-06-07 22:24 UTC)

The current overnight/control-plane proof was refreshed after the transcript,
ledger, and calibration updates:

- `alpaca verify-overnight-system --json-output` wrote
  `results\overnight_system_verification\overnight-system-verification-20260607-172054.json`
  with `overall_status=pass`, 16/16 checks passed, analysis-only,
  `can_submit_orders=false`, top `XOM`, trade date `2026-06-08`, 3/3 original
  graph successes, 0 graph failures, and 0 submitted orders.
- `research source-quality-review --json-output --compact-json-output` wrote
  `results\source_quality\source-quality-review-20260607-222048.json`:
  250 sources, 205 fresh, 45 stale, 45 stale-safe, 25 stale-downranked,
  38 blocked gap packets, 0 unreadable, 0 missing/invalid, and
  `stale_needs_refresh_count=0`.
- `research automation-health-audit --json-output` wrote
  `results\automation_health\automation-health-audit-20260607-222049.json`:
  13/13 automations OK, 0 missing/partial/late/stale/warnings,
  self-heal timely at 30 seconds, and 0 submitted orders.
- `python -m tradingagents.orchestration.n8n_runner --list-jobs --json`
  returned 24 allowlisted jobs and `submit_capable_count=0`.
- Compact context was refreshed; `latest-flags.json` contains only the
  intentional hourly/BOARD/loss-review review routes. Process review
  `results\process_reviews\process-review-20260607-222354.json` has
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, YouTube transcript provider route, 2026-06-07 21:45 UTC:

The P1 source-routing path now has a real local-unlimited transcript route for
overnight top-provider bundles. `tradingagents/research/youtube_transcript.py`
discovers plausible ticker earnings-call YouTube videos, calls Docker MCP
`youtube_transcript__get_transcript`, validates that real transcript text looks
earnings-call related, and emits a read-only `youtube_transcript` packet with
`execution_authority=none`. `provider_orchestrator.py` now attempts that route
before FMP for `earnings_transcripts`; failures remain explicit blocked attempts
and still fall through to FMP or `earnings_transcripts_gap`.

Real proof:

- `research ticker-provider-bundle --symbol XOM --evidence-needs earnings_transcripts`
  with probe output/cache directories wrote non-gap transcript packet
  `results\research_evidence\youtube_transcript_probe\source-evidence-source-evidence-107cb2c1d5bf4cf9b6c71c1e3af1cd78.json`
  and summary
  `results\research_evidence\youtube_transcript_probe\source-evidence-source-evidence-e4c80ea7e67e457cb29e5fb2be8ab63a.json`.
- That summary has `route_status_counts={"cache_miss":1,"packet_written":1}`,
  `unsupported_route_count=0`, `blocked_packet_attempt_count=0`,
  `gap_packet_count=0`, and no missing non-gap needs.
- Compact overnight probe
  `results\overnight_plans\youtube_transcript_probe\overnight-plan-20260607-214130-000000.json`
  had top candidate `XOM`, `submitted_count=0`,
  `execution_authority=none`, `top_provider_bundle_error_count=0`, and
  `top_provider_bundle_missing_non_gap_needs=[]`.

Verification passed: `tests/test_youtube_transcript_bridge.py` plus full
provider orchestrator tests -> `34 passed`; overnight CLI plan slice ->
`14 passed, 82 deselected`; targeted Ruff passed.

Follow-up, 2026-06-07 21:55 UTC:

The compact source-routing overlay now uses the latest provider bundle per
symbol when deciding whether current overnight targets still have missing
non-gap evidence. This fixes the stale-history problem where an older XOM/CVX
or ADBE bundle could keep a target flagged after a newer bundle had already
closed the gap.

Fresh target bundle refreshes:

- CVX summary:
  `results\research_evidence\source-evidence-source-evidence-43183b7d0f874a08bf384074a682e438.json`
  with `youtube_transcript` written, official-cache short-interest/options hits,
  `unsupported_route_count=0`, `blocked_packet_attempt_count=0`,
  `gap_packet_count=0`, and no missing non-gap needs.
- ADBE summary:
  `results\research_evidence\source-evidence-source-evidence-fd80a8881c8c4e309cff9f6855424eb3.json`
  with the same clean transcript/short-interest/options coverage shape.
- Refreshed `results\_context\source-routing-compact.json` reports target
  symbols `["XOM","CVX","ADBE"]`, all bundled, no missing target bundle, no
  target symbol with missing non-gap evidence, and no target missing non-gap
  evidence needs. `latest-flags.json` no longer includes `source_routing`.

Verification passed: source-routing overlay regression tests ->
`3 passed, 75 deselected`; targeted Ruff passed; process review
`results\process_reviews\process-review-20260607-215353.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Tail pointer, overnight top-provider bundles, 2026-06-07 21:13 UTC:

Claude's submit-path hardening handoff remains prepared, and SAFE-01 remains
fail-closed locally. The latest pipeline repair moved top-candidate provider
bundle refreshes from a manual follow-up into `alpaca plan-overnight` itself:
the command now defaults to refreshing compact analysis-only bundles for the
top 3 ranked candidates and writes only summary paths/counts into the overnight
packet under `top_provider_bundles`. Use `--top-provider-bundle-count 0` for
probes or tests that must skip provider work.

Real no-latest proof:
`results\overnight_plans\top_provider_bundle_probe\overnight-plan-20260607-210455-000000.json`
has `submitted_count=0`, top candidate `XOM`, one top-provider bundle, 7 source
packets, `top_provider_bundle_error_count=0`, and `execution_authority=none`.

Context consistency repair: `scripts/automation_context_snapshot.py` now
persists the same fresh provider overlay into
`results\_context\source-routing-compact.json` that it uses in
`latest-summary.json`. Current source-routing compact evidence shows target
symbols `XOM`, `CVX`, and `ADBE` all have provider bundles; none are missing a
bundle, and the remaining target weakness is limited to non-gap transcript
coverage (`earnings_transcripts`).

Fresh proof:

- `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "plan_overnight or compact_overnight"` -> `14 passed`.
- `uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_research_provider_orchestrator.py -q` -> `104 passed`.
- Source-routing overlay slice -> `2 passed`.
- Targeted Ruff over the edited CLI, overnight, context-snapshot, and test files
  passed.
- Process review
  `results\process_reviews\process-review-20260607-211322.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Tail pointer, source-routing provider evidence overlay, 2026-06-07 20:25 UTC:

The static decision-source routing audit no longer hides real provider-bundle
evidence gaps. `scripts/automation_context_snapshot.py` now annotates
`results\_context\source-routing-compact.json` and the `source_routing` entry
in `results\_context\latest-summary.json` with bounded counters from recent
`ticker_provider_orchestrator` summary packets under
`results\research_evidence\`.

Current production proof after the real CVX provider bundle:

- Static source-routing health still reports `gap_count=0` and
  `coverage_count=3`, meaning the categories have configured routes.
- Recent provider-bundle overlay reports `latest_provider_bundle_symbol=CVX`,
  `recent_provider_bundle_count=9`, `recent_provider_bundle_gap_count=2`,
  `recent_provider_gap_packet_count=6`,
  `recent_provider_unsupported_route_count=10`,
  `recent_provider_blocked_packet_attempt_count=8`,
  `recent_provider_evidence_needs_without_non_gap_packets=["earnings_transcripts"]`,
  and `recent_provider_symbols_with_missing_non_gap=["CVX"]`.
- `results\_context\latest-flags.json` now includes a `source_routing`
  drilldown pointing at `results\_context\source-routing-compact.json`.

Verification:

- `uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py -q -k "source_routing or provider_bundle"`
  -> `2 passed, 74 deselected`.
- `uv run --no-sync --group static-analysis ruff check scripts\automation_context_snapshot.py tests\test_automation_context_snapshot.py`
  -> passed.
- `results\process_reviews\process-review-20260607-202515.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, overnight-target provider-bundle relevance, 2026-06-07 20:39 UTC:

The source-routing overlay now checks recent provider bundles against the
current overnight top-three symbols instead of trusting the latest arbitrary
ticker. It dedupes `latest.json` versus timestamped summary duplicates and
writes target coverage fields into both `results\_context\source-routing-compact.json`
and the `source_routing` entry in `results\_context\latest-summary.json`.

Current real proof:

- Overnight target symbols are `XOM`, `CVX`, and `ADBE`.
- Analysis-only provider bundles were run for all three:
  `results\research_evidence\source-evidence-source-evidence-b662653f431f49ea89efebb825adca60.json`
  (`XOM`),
  `results\research_evidence\source-evidence-source-evidence-bdb6fdea329b4be9a22aa63dfa61e4ce.json`
  (`CVX`), and
  `results\research_evidence\source-evidence-source-evidence-be59e593d1f94b1fa47eb065d0cafd1f.json`
  (`ADBE`).
- Compact source routing now reports
  `recent_provider_target_symbols_with_bundle=["XOM","CVX","ADBE"]`,
  `recent_provider_target_symbols_missing_bundle=[]`,
  `recent_provider_target_bundle_gap_count=3`, and
  `recent_provider_target_evidence_needs_without_non_gap_packets=["earnings_transcripts"]`.
- The remaining `source_routing` compact flag is therefore a real evidence
  quality/downranking signal, not missing top-candidate provider coverage.

Fresh source-quality proof after the target bundles:
`results\source_quality\source-quality-review-20260607-203833.json`,
`source_count=250`, `fresh=205`, `stale_count=45`,
`stale_needs_refresh_count=0`, `blocked_count=36`, and
`missing_or_invalid_count=0`.

Verification:

- `uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_research_provider_orchestrator.py -q`
  -> `103 passed`.
- Targeted Ruff over source-routing/provider files and tests -> passed.
- `results\process_reviews\process-review-20260607-203905.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, provider-bundle gap counters for higher-authority evidence,
2026-06-07 20:10 UTC:

Ticker provider summary packets now expose compact route-quality counters so
overnight research agents do not have to manually parse every route attempt to
see evidence gaps. `ticker_provider_orchestrator` summary payloads include
`route_status_counts`, `unsupported_route_count`,
`blocked_packet_attempt_count`, `gap_packet_count`,
`evidence_needs_with_gap_packets`, and
`evidence_needs_without_non_gap_packets`.

Real CVX proof:

- `.\.venv\Scripts\tradingagents.exe research ticker-provider-bundle --symbol CVX --evidence-needs earnings_transcripts,short_interest,options_iv_flow --json-output`
  wrote summary packet
  `results\research_evidence\source-evidence-source-evidence-bdb6fdea329b4be9a22aa63dfa61e4ce.json`.
- The packet reports `unsupported_route_count=5`,
  `blocked_packet_attempt_count=4`, `gap_packet_count=3`,
  `evidence_needs_with_gap_packets=["earnings_transcripts","options_iv_flow","short_interest"]`,
  and `evidence_needs_without_non_gap_packets=["earnings_transcripts"]`.
  Translation: short-interest and options/IV/flow have low-authority non-gap
  evidence plus gap warnings; earnings transcripts still need a working
  authoritative route beyond FMP/gap. The unsupported configured routes are
  `youtube_transcript`, `benzinga`, `finnhub`/`fmp` for short interest, and
  `massive_options`.

Fresh proof:

- Focused provider-orchestrator tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_research_provider_orchestrator.py -q -k "gap_packets_for_missing_categories or yfinance_short_interest_before_gap or fmp_transcript_blocks"`
  -> `3 passed, 24 deselected`.
- Targeted Ruff over `tradingagents\research\provider_orchestrator.py` and
  `tests\test_research_provider_orchestrator.py` passed.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, overnight prior-feed applied-state/dedupe proof, 2026-06-07
19:48 UTC:

The overnight research prior feed now makes carry-forward state explicit for
automation readers. `build_overnight_prior_feed(...)` dedupes packet references,
marks whether advisory priors were applied, and records input/unique/duplicate
reference counts plus a `carry_forward_scope`. Premarket context compaction and
`scripts/automation_context_snapshot.py` now preserve those fields, so future
agents can prove prior work was carried forward without opening raw overnight
packets.

Real no-latest/no-submit probe:

- `.\.venv\Scripts\tradingagents.exe alpaca plan-overnight --json-output --compact-json-output --log-dir results\overnight_plans\prior_dedupe_probe --no-write-latest --full-graph-tickers 0 --time-budget-minutes 0 --no-agent-ledger`
  wrote
  `results\overnight_plans\prior_dedupe_probe\overnight-plan-20260607-194517-000000.json`.
- Its compact stdout and prior-feed latest packet report
  `prior_applied=true`, `dedupe_applied=true`,
  `input_packet_ref_count=14`, `unique_packet_ref_count=14`,
  `duplicate_packet_ref_count=0`, carry-forward scope
  `source_packet_refs`, `provider_fallbacks`, `watchlists`, `mirofish`, and
  `methodology`, plus `analysis_only=true`, `execution_authority=none`, and
  `submit_order` in `forbidden_effects`.

Fresh proof:

- Focused prior-feed creation/context/premarket tests -> `2 passed`,
  `1 passed`, and `1 passed`.
- Legacy production compatibility proof:
  after `scripts/automation_context_snapshot.py --write`,
  `results\_context\latest-summary.json` now enriches the current production
  overnight packet
  `results\overnight_plans\overnight-plan-20260607-101157-000000.json` with
  `overnight_prior_feed_applied=true`,
  `overnight_prior_feed_dedupe_applied=true`,
  `overnight_prior_feed_input_packet_ref_count=14`,
  `overnight_prior_feed_unique_packet_ref_count=14`,
  `overnight_prior_feed_duplicate_packet_ref_count=0`, and carry-forward scope
  `source_packet_refs`, `provider_fallbacks`, `watchlists`, `mirofish`, and
  `methodology`, while preserving its 3/3 Google graph successes and
  `graph_failure_count=0`.
- Broader prior-feed/overnight selector:
  `uv run --no-sync --with pytest python -m pytest tests/test_research_crawler_social.py tests/test_automation_context_snapshot.py tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py -q -k "prior_feed or compact_overnight_sidecar or overnight_research_context"`
  -> `8 passed, 275 deselected`.
- Targeted Ruff over touched prior-feed/context files and tests passed.
- Process review:
  `results\process_reviews\process-review-20260607-194744.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Post-check: full pytest also passed after this checkpoint:
`uv run --no-sync --with pytest python -m pytest -q` -> 1067 passed, 1
skipped, 9 warnings, 75 subtests passed in 395.36s. Final process review
`results\process_reviews\process-review-20260607-183102.json` still reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Tail pointer, stale evidence self-heal and Claude handoff prep, 2026-06-07
18:17 UTC:

Claude's submit-path hardening handoff has been re-read against current disk
state. SAFE-01 remains fail-closed locally:
`config/risk_envelope.yaml` loads as `autonomous_with_caps` with `$250` account
max and `$50` per-name caps; live control is not frozen but the dead-man is
expired at `2026-06-04T19:57:06+00:00`. Commit `3970998` still contains only
`tradingagents/policy/order_rate_limit.py` and
`tests/test_order_rate_limit.py`; shared submit-path edits remain dirty and
must be hunk-reviewed before staging.

The safe self-heal executor now has explicit stale-evidence refresh routes for
`loss_review_evidence` and `preopen_validation`. These routes run only
allowlisted analysis-only commands plus compact context refresh. They do not
trade, email, mutate automations, refresh live control, or approve BOARD
loss-exit candidates.

Fresh proof:

- Self-heal no-op/escalation proof:
  `results\self_heal\plans\self-heal-plan-20260607-181507.json` had no stale
  safe fixes left to run, executed 0 commands, and skipped 2 order-adjacent
  BOARD escalations.
- Preopen proof:
  `results\preopen_validation\preopen-validation-20260607-181534.json` is
  `pass_with_warnings` only because market session is closed and live-control
  is expired; 0 submitted orders.
- Loss-review evidence proof:
  `results\loss_review_evidence\source-evidence-source-evidence-e23335b8bedd4bf6a91277c8a355aeda.json`
  is fresh and resolves 12/13 TSM evidence blockers while leaving only the
  closed-session blocker.
- BOARD proof:
  `results\execution_board\execution-board-review-20260607-181725.json` has 0
  violations and 0 submitted orders; it preserves independent sell/buy policy,
  profit-taking separation, and controlled-dip/no-green-spike buy discipline.
- Automation health:
  `results\automation_health\automation-health-audit-20260607-181654.json`
  reports 13/13 OK and self-heal timely in 30 seconds.
- Process review:
  `results\process_reviews\process-review-20260607-181651.json` has
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Verification:

- Self-heal focused slice -> 8 passed.
- Self-heal/context slice -> 42 passed.
- Targeted Ruff and compileall passed.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 63. Overnight Packet Source-Of-Truth Hardened

The overnight production loader and CLI verifier no longer blindly trust
`latest.json` when a newer timestamped raw production packet exists. They now
rank readable production packets by `generated_at` first and file mtime second,
while skipping compact sidecars and raw packets tagged
`latest_alias_written=false`.

This preserves the intended split:

- production morning context can recover from a stale `latest.json` alias;
- no-latest probe packets stay observable and cannot become the morning source
  of truth;
- compact sidecars remain compact context only, not raw-packet candidates.

Fresh proof:

- Focused overnight loader tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "overnight_packet_writer or load_latest_overnight_plan or overnight_validation or overnight_markdown"`
  -> `7 passed, 75 deselected`.
- Focused CLI verifier tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "latest_json_packet_path or verify_overnight_system"`
  -> `6 passed, 88 deselected`.
- Targeted Ruff and compileall passed over the edited CLI, overnight loader,
  and tests.
- Real verifier:
  `results\overnight_system_verification\overnight-system-verification-20260607-125346.json`
  reports `overall_status=pass`, `execution_authority=none`,
  `can_submit_orders=false`, top `XOM`, trade date `2026-06-08`, 3/3 original
  graph successes, 0 graph failures, and 0 submissions.
- Process review:
  `results\process_reviews\process-review-20260607-175343.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, n8n archived-duplicate sync repair, 2026-06-07 17:42 UTC:

The n8n evaluation/dashboard lane was rechecked against the live Docker n8n
database and public API. The duplicate `TA · Sync Evaluation Dataset` name was
one current workflow plus one archived historical copy. The repo now treats
that correctly: current duplicates still flag an audit, archived duplicates are
shown only as compact context history.

Fresh proof:

- Workflow sync:
  `results\n8n_evaluations\n8n-workflow-sync-20260607-174046-570170.json`
  reports 12 updated workflows, 0 created workflows,
  `duplicate_name_counts={}`, and
  `archived_duplicate_name_counts={"TA · Sync Evaluation Dataset": 2}`.
- Data Table sync:
  `results\n8n_evaluations\n8n-api-sync-20260607-174052-514756.json`
  reports `final_row_count=243`, `expected_row_count=243`,
  `row_count_matches=true`, and `api_key_redacted=true`.
- Built-in evaluation probe:
  `results\n8n_evaluations\n8n-evaluation-run-probe-20260607-174058-485932.json`
  reports `workflow_found=true`, `status=editor_required`, and
  `supported_endpoint_count=0`, so native n8n evaluation execution remains an
  editor/evaluations UI action.
- Compact context:
  `results\_context\latest-summary.json` no longer has an n8n audit drilldown.
  It records `workflow_sync_duplicate_name_counts={}` and preserves
  `workflow_sync_archived_duplicate_name_counts` for observability.
- Process review:
  `results\process_reviews\process-review-20260607-174215.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Verification:

- `uv run --no-sync --with pytest python -m pytest tests/test_n8n_evaluations.py tests/test_automation_context_snapshot.py -q -k "n8n_workflow_sync or n8n_evaluation_dataset"`
  -> `9 passed, 83 deselected`.
- Targeted Ruff passed over the n8n sync/context implementation and tests.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, real-simulation freshness guard and live dry-run proof,
2026-06-07 17:13 UTC:

`tradingagents.evals.real_simulation_audit` now rejects stale process-review
proof. The `process_review` department result must include a parseable
`generated_at` within the freshness window; otherwise
`acceptance.process_review_fresh=false` and the audit is not accepted.

Regression proof:

- `tests/test_real_simulation_audit.py::test_real_simulation_audit_rejects_stale_process_review_packet`
  covers a clean but old process-review packet.
- Focused real-simulation/process-review/n8n tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_real_simulation_audit.py tests/test_process_review.py tests/test_n8n_evaluations.py tests/test_n8n_runner_policy.py -q`
  -> `78 passed`.
- Targeted Ruff and compileall passed for touched modules.

Real live-data dry-run proof:
`results\real_simulation_audits\real-simulation-audit-20260607-170922.json`
ran 28 commands across 8 departments. It reports `failed_command_count=0`,
`commands_missing_structured_output=[]`,
`stale_process_review_commands=[]`, `total_submitted_order_count=0`,
`unsafe_submission_evidence=false`, `acceptance.process_review_fresh=true`,
and `acceptance.core_accepted=true`.

Remaining non-blocking model note: Mac DeepSeek remains optional/degraded
because the Mac Ollama tags endpoint timed out. The audit still accepts the
core route through Windows local/deterministic/Codex paths.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, MiroFish future-report guard, 2026-06-07 16:55 UTC:

Claude's submit-path handoff was reconciled with the current MiroFish/research
lane. SAFE-01 remains fail-closed in local machine state:
`load_risk_envelope("config/risk_envelope.yaml")` parses with
`live_budget_mode=autonomous_with_caps`, `account_max_capital_at_risk_usd=250`,
`per_name_cap_usd=50`, and `issues=[]`.

The MiroFish handoff guard now supports future report ids without a code edit.
`tradingagents.research.mirofish_handoff.resolve_required_report_id(...)`
resolves in this order: explicit CLI/function value,
`TRADINGAGENTS_MIROFISH_REQUIRED_REPORT_ID`, then the current accepted fallback
`report_9c77ca2557ae`. The CLI default for `research
mirofish-handoff-status --required-report-id` now uses that same resolver.
Empty explicit/env values intentionally disable the report-id guard only for
repair/debug runs.

Real status proof:
`results\mirofish_handoff\research-intel-research-intel-9d3206b3149e42fa96319e315fe8d6c6.json`
reports `final_handoff_available=true`,
`required_report_id=report_9c77ca2557ae`, `scenario_branch_count=7`,
`validation_task_count=12`, `false_signal_filter_count=8`, and
`execution_authority=none`. The current packet preserves the AI-bot copycat /
institutional-liquidity warning and report-33 macro-first stock-selection
overlay for overnight/premarket analysis only.

Fresh proof:

- Focused MiroFish tests:
  `uv run --isolated --with pytest pytest -q tests/test_mirofish_handoff.py`
  -> `12 passed`.
- Targeted Ruff:
  `.venv\Scripts\python.exe -m ruff check tradingagents\research\mirofish_handoff.py cli\main.py tests\test_mirofish_handoff.py`
  -> clean.
- Compile check:
  `.venv\Scripts\python.exe -m compileall -q tradingagents\research\mirofish_handoff.py cli\main.py`
  -> clean.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, n8n built-in evaluation/dashboard sync, 2026-06-07 16:58 UTC:

The local n8n wrapper/dashboard layer is synced but remains non-authoritative
for trading. Docker container `tradingagents-main-n8n-1` is up on
`localhost:5678`, and the repo allowlisted runner bridge is reachable on
`127.0.0.1:8765`.

`python -m tradingagents.orchestration.n8n_runner --list-jobs --json` reports
24 allowlisted jobs, all `submit_capable=false`, and `submit_capable_count=0`.

The built-in evaluation dataset now has 243 rows across 24 allowlisted jobs,
18 edge tags, and 23 columns. Data Table sync proof:
`results\n8n_evaluations\n8n-api-sync-20260607-165753-318068.json` with
`expected_row_count=243`, `final_row_count=243`, `row_count_matches=true`, and
`api_key_redacted=true`.

Workflow sync proof:
`results\n8n_evaluations\n8n-workflow-sync-20260607-165802-734061.json` with
12 source-controlled observer/evaluation workflows updated and left inactive.

Native built-in evaluation run probe:
`results\n8n_evaluations\n8n-evaluation-run-probe-20260607-165811-433546.json`
found `taBuiltInAutomationEvaluation`, but no public API route can start the
Evaluation Trigger run (`editor_required`). This matches the n8n workflow
contract: run the final native evaluation from the editor/evaluations UI, while
repo tests and sync commands prove the static workflow/data-table wiring.

Fresh proof:

- n8n dataset command:
  `research n8n-evaluation-dataset --json-output --compact-json-output`
  -> 243 rows, 24 jobs, 18 edge tags.
- Focused n8n tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_n8n_evaluations.py tests/test_n8n_runner_policy.py -q`
  -> `62 passed`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, hourly decision router extraction, 2026-06-07 16:48 UTC:

The remaining hourly decision router has now moved into
`tradingagents/brokers/supervisor/hourly.py` as
`build_hourly_decision(...)`. The legacy
`tradingagents.brokers.alpaca_supervisor.build_hourly_decision(...)` public
surface remains intact and delegates to the extracted module with explicit
injections for trade-session checks, positive-price parsing, and the live
sleeve name. This keeps branch precedence centralized with the previously
extracted open-order, loss-review, profit-take, buy-candidate, and trailing-hold
helpers.

Fresh proof:

- Direct extracted-router/facade/branch tests:
  `uv run --isolated --with pytest pytest -q tests/test_alpaca_supervisor.py -k "extracted_hourly_decision_router or reviews_open_orders_before_loss_or_buy or branch or facade or hourly"`
  -> `12 passed, 69 deselected`.
- Full supervisor tests:
  `uv run --isolated --with pytest pytest -q tests/test_alpaca_supervisor.py`
  -> `81 passed`.
- Automation-facing hourly/daily CLI slice:
  `uv run --isolated --with pytest pytest -q tests/test_alpaca_cli.py -k "supervise_hourly or compact_hourly or alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_output_audit_finds_nested_daily_report_packets"`
  -> `16 passed, 76 deselected`.
- Targeted Ruff and compileall passed for the supervisor facade and extracted
  hourly module.
- Real hourly dry-run no-submit probe:
  `results\hourly_supervisor\hourly_router_extraction_probe\hourly-supervisor-20260607-164738-252488.json`
  with compact sidecar `latest-compact.json`, `decision=loss-review`,
  `submitted_count=0`, `issue_count=0`, `can_submit_orders=false`,
  `execution_authority=none`, and `action_count=0`.
- Process review:
  `results\process_reviews\process-review-20260607-164809.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Remaining P3 decomposition work: the hourly state machine is extracted. Future
P3 work should shift to higher-leverage cleanup unless a new branch-precedence
or packet-IO duplication appears in current evidence.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.


Tail pointer, self-heal timeliness and agent-ledger schema repair, 2026-06-07
16:27 UTC:

The transient `agent_intelligence_summary` schema drilldown was caused by
`results\agent_intelligence\summary.json` lagging behind
`results\agent_intelligence\ledger.jsonl`. The safe refresh path repaired it:
`research agent-ledger-summary --json-output` rewrote the summary with
`forecast_count=4491`, matching the 4,491 ledger records, and compact context
now reports `summary_ledger_count_matches=true` with no schema drilldown.

The self-heal monitor was also tested end-to-end with the real automation
sequence. It wrote handoff
`results\self_heal\self-heal-handoff-20260607-162425.json`, then wrote plan
`results\self_heal\plans\self-heal-plan-20260607-162437.json` 12 seconds
later. The plan intentionally escalated BOARD/order-adjacent review signals
instead of auto-fixing them. Automation health
`results\automation_health\automation-health-audit-20260607-162446.json`
reports 13/13 automations OK, `timeliness_issue_count=0`, and
self-heal follow-up `timely=true`.

Fresh proof:

- Focused self-heal and automation-health tests -> `6 passed`.
- Process review:
  `results\process_reviews\process-review-20260607-162700.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.
- Refreshed compact flags now contain only the intentional hourly/BOARD/loss
  review drilldowns; no `agent_intelligence_summary` schema flag and no
  automation-health flag remain.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.


## 65. Self-Heal Timeliness Follow-Up Verified

After refreshing compact context, the Agent Intelligence Ledger summary was
stale relative to the JSONL ledger (`forecast_count=4469` vs current
`ledger_record_count=4491`). Codex refreshed the summary and then reran compact
context. That cleared the `agent_intelligence_summary` schema drilldown:
`summary_ledger_count_matches=true`, `forecast_count=4491`,
`agent_count=10`, and `influence_weight_count=10`.

The next compact refresh surfaced an automation-health drilldown for
`tradingagents-self-heal-monitor`: a new actionable self-heal handoff existed
without a follow-up plan. Codex ran the real safe-plane self-heal executor,
which wrote night-shift patrol evidence and reran automation health. The follow
up completed inside the 30-minute SLA.

Fresh proof:

- `.\.venv\Scripts\tradingagents.exe research agent-ledger-summary --json-output`
  refreshed `results\agent_intelligence\summary.json` to 4,491 forecasts.
- `.\.venv\Scripts\tradingagents.exe research self-heal-plan --execute-safe --json-output`
  wrote `results\self_heal\plans\self-heal-plan-20260607-162219.json` with
  `executed_count=1`, `verified_count=1`, `verify_failed_count=0`,
  `can_submit_orders=false`, and `execution_authority=none`.
- The self-heal executor ran the real safe commands:
  `research night-shift-patrol --json-output` and
  `research automation-health-audit --json-output`.
- `results\automation_health\latest-compact.json` now reports
  `ok_count=13`, `problem_automation_ids=[]`, `duplicate_count=0`,
  `stale_count=0`, `late_count=0`, `submitted_order_count=0`, and
  `self_heal_timeliness.timely=true` with `followup_lag_seconds=51`.
- Final compact flags are only the expected hourly notify/BOARD,
  execution-BOARD, and loss-review BOARD flags.
- Final process review:
  `results\process_reviews\process-review-20260607-162248.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 64. CLI Wildcard Import Removed And Hidden Output Bugs Fixed

The roadmap still listed `from cli.utils import *` as a cleanup item. Removing
that wildcard exposed two real undefined-name defects that had been hidden from
static analysis:

- stale unreachable code after `_rank_overnight_results(...)` referenced
  `decision.issues` and `decision.submitted`;
- the non-JSON `alpaca supervisor-daily-report` branch echoed undefined `body`
  instead of the rendered daily report body stored in the payload.

Implemented:

- `cli/main.py` now imports only the utility provider/selection helpers it
  actually uses from `cli.utils`;
- the unreachable stale `decision` block after overnight ranking was removed;
- plain daily-report output now echoes `payload["body"]`.

Fresh proof:

- Targeted Ruff:
  `.\.venv\Scripts\python.exe -m ruff check cli\main.py`
  -> `All checks passed!`.
- Targeted compileall:
  `.\.venv\Scripts\python.exe -m compileall cli\main.py`
  -> passed.
- Overnight/provider/preopen CLI slice:
  `uv run --isolated --with pytest pytest -q tests\test_alpaca_cli.py -k "plan_overnight or verify_overnight or preopen or n8n or research_provider_fallbacks"`
  -> `24 passed, 68 deselected`.
- Daily-report CLI slice:
  `uv run --isolated --with pytest pytest -q tests\test_alpaca_cli.py -k "daily_report or supervisor_daily_report"`
  -> `5 passed, 87 deselected`.
- Compact context regenerated with
  `.\.venv\Scripts\python.exe scripts\automation_context_snapshot.py --write`.
- Process review:
  `results\process_reviews\process-review-20260607-161652.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 63. Core Price Fallback Chain Now Includes Massive

The source-routing audit found one remaining mismatch between the connector
leverage plan and the decision path: OHLCV price routing used
`yfinance -> tiingo -> alpha_vantage`, while the plan called for the keyed
Massive/Polygon replacement route to participate in price fallbacks. That gap
is now closed.

Implemented:

- `tradingagents/dataflows/massive.py::fetch_massive_daily_prices(...)` for
  Massive aggregate daily range bars;
- `tradingagents/dataflows/decision_vendor_adapters.py::get_massive_stock_data(...)`
  to convert Massive aggregate bars into the same analyst-friendly CSV shape as
  yfinance/Tiingo;
- `tradingagents/dataflows/interface.py` now exposes `massive` in
  `VENDOR_LIST` and routes `get_stock_data` through
  `yfinance -> tiingo -> massive -> alpha_vantage`;
- `tradingagents/default_config.py` now defaults `core_stock_apis` to
  `yfinance,tiingo,massive,alpha_vantage`.

Fresh proof:

- Focused dataflow tests:
  `uv run --isolated --with pytest pytest -q tests\test_dataflows_interface.py tests\test_dataflows_config.py tests\test_official_dataflows.py`
  -> `53 passed`.
- Targeted Ruff:
  `.\.venv\Scripts\python.exe -m ruff check tradingagents\dataflows\massive.py tradingagents\dataflows\decision_vendor_adapters.py tradingagents\dataflows\interface.py tradingagents\default_config.py tests\test_dataflows_interface.py tests\test_dataflows_config.py`
  -> `All checks passed!`.
- Targeted compileall passed over the touched dataflow/config modules.
- Compact context regenerated with
  `.\.venv\Scripts\python.exe scripts\automation_context_snapshot.py --write`.
- `results\_context\source-routing-compact.json` reports
  `gap_count=0` and `get_stock_data.effective_fallback_chain=[
  "yfinance", "tiingo", "massive", "alpha_vantage"]`.
- Overnight verifier:
  `.\.venv\Scripts\tradingagents.exe alpaca verify-overnight-system --json-output`
  -> `overall_status=pass`, packet
  `results\overnight_system_verification\overnight-system-verification-20260607-110413.json`,
  `analysis_only=true`, `can_submit_orders=false`,
  `execution_authority=none`.
- Process review:
  `results\process_reviews\process-review-20260607-160435.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, overnight model route refresh checkpoint, 2026-06-07 16:03 UTC:

Claude handoff preparation is current. SAFE-01 remains fail-closed:
`config/risk_envelope.yaml` is still `live_budget_mode=autonomous_with_caps`
with `account_max_capital_at_risk_usd` 250.00, `per_name_cap_usd` 50.00, and
`tiny_live_tranche_usd` 25.00. Commit `3970998` still contains only
`tradingagents/policy/order_rate_limit.py` and
`tests/test_order_rate_limit.py`.

The latest model route telemetry prepared the overnight research stack for the
next automation run:

- Windows local Ollama is the selected free local worker:
  `tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest`.
- Mac Ollama remains an optional/degraded helper lane. The endpoint
  `http://macbook-pro.tail37edd7.ts.net:11434` timed out on `/api/tags`, so
  the system must skip the Mac `deepseek-r1:14b` helper until the host and
  Ollama tags endpoint respond again.
- Deterministic packet helpers are ready.
- Codex/ChatGPT stays the judgment route.
- Research orchestration quality is high enough without the Mac lane:
  `research_quality_high_enough=true`, `fallback_required=false`,
  `source_packet_count=14`, and `blocked_source_packet_count=0`.

Fresh proof:

- Model telemetry:
  `results\model_telemetry_reports\model-telemetry-report-20260607-160148-958256.json`.
- Research orchestration:
  `results\research_batches\research-batch-research-batch-1d4818323dc949bfb7f4526233280ccb.json`.
- Focused route/context tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_model_routing.py tests/test_research_automation_orchestrator.py tests/test_automation_context_snapshot.py -q -k "ollama or mac or windows_local or model_telemetry or orchestration or local_worker or overnight_calibration_guard"`
  -> `23 passed, 83 deselected`.
- Process review:
  `results\process_reviews\process-review-20260607-160321.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 63. Hourly Branch Decomposition Complete

The hourly supervisor decision path is now fully decomposed into pure branch
helpers under `tradingagents/brokers/supervisor/hourly.py`, with the legacy
`tradingagents.brokers.alpaca_supervisor` facade still preserving the public API
and dependency-injection boundary. The branch order is explicit and tested:

1. `build_open_orders_review_decision(...)`
2. `build_loss_review_decision(...)`
3. `build_profit_take_decision(...)`
4. `build_buy_candidate_decision(...)`
5. `build_trailing_hold_decision(...)`

This closes the stale P3 "continue branch-by-branch hourly decomposition"
checkpoint. The implementation preserves the intended trading behavior:
open-order inspection wins first, loss-review cannot pair with a replacement
buy, profitable sell-the-spike decisions outrank new buys, green-spike buys are
held as no-chase, BOARD pauses block new live buys, and the final trailing hold
branch emits no order action.

Fresh proof:

- Final branch helper/precedence tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "open_orders_review or trailing_hold or profit_take_still_outranks_trailing or reviews_open_orders_before_loss_or_buy or branch"`
  -> `5 passed, 75 deselected`.
- Targeted Ruff:
  `uv run --no-sync --group static-analysis ruff check tradingagents\brokers\supervisor\hourly.py tradingagents\brokers\alpaca_supervisor.py tests\test_alpaca_supervisor.py`
  -> passed.
- Compile check:
  `.\.venv\Scripts\python.exe -m compileall tradingagents\brokers\supervisor\hourly.py tradingagents\brokers\alpaca_supervisor.py tests\test_alpaca_supervisor.py`
  -> passed.
- Real hourly dry-run no-submit probe:
  `results\hourly_supervisor\hourly_branch_completion_probe\hourly-supervisor-20260607-155220-678827.json`
  with compact sidecar `latest-compact.json`, `decision=loss-review`,
  `submitted_count=0`, `issue_count=0`, `can_submit_orders=false`,
  `execution_authority=none`, and `action_count=0`.
- Process review:
  `results\process_reviews\process-review-20260607-155211.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 63. Hourly Trailing Hold Branch Extracted

The final no-action hourly fallback branch has been moved into
`tradingagents/brokers/supervisor/hourly.py` as
`build_trailing_hold_decision(...)` and re-exported through
`tradingagents.brokers.alpaca_supervisor`. The large facade now returns this
helper after open-order review, loss-review, profit-taking, and buy-candidate
logic all decline to act.

The helper owns two no-action outcomes:

- material `profit-review` when a position is above the profit threshold but a
  higher-priority profit-take order branch did not fire, for example because the
  session is not tradeable;
- quiet non-material `hold` when there is no risk, profit, order, or
  thesis-change trigger.

This keeps the "sell spike when allowed, otherwise review/hold" behavior clear
without adding any submission authority. New tests prove the fallback emits no
actions and that regular-session profit-taking still outranks the fallback
profit-review path.

Fresh proof:

- Focused trailing-hold/profit/facade tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "trailing_hold or profit_take_still_outranks or quiet_hourly_hold or profit_review or facade"`
  -> `7 passed, 73 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `80 passed`.
- Hourly plus daily-report CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_supervisor_daily_report_payload_points_to_raw_packet or compact_output_audit_finds_nested_daily_report_packets"`
  -> `17 passed, 75 deselected`.
- Targeted Ruff and compileall passed over
  `tradingagents/brokers/supervisor/hourly.py`,
  `tradingagents/brokers/alpaca_supervisor.py`, and
  `tests/test_alpaca_supervisor.py`.
- Real hourly no-submit probe:
  `results\hourly_supervisor\hourly_trailing_hold_extraction_probe\hourly-supervisor-20260607-154338-781974.json`
  with `decision=loss-review`, `actions=[]`, `submitted=[]`, and `issues=[]`.
  The compact sidecar shows `submitted_count=0`, `issue_count=0`,
  `can_submit_orders=false`, and `execution_authority=none`.
- Agent Intelligence Ledger was normalized after the probe with
  `research agent-ledger-resolve --json-output`; `results\agent_intelligence\ledger.jsonl`
  and `results\agent_intelligence\summary.json` now match at 4,469 forecasts.
- Compact context refresh cleared the transient Agent Intelligence schema flag.
  `results\_context\latest-flags.json` now shows only the expected hourly notify
  plus BOARD/loss-review drilldowns.
- Process review:
  `results\process_reviews\process-review-20260607-154406.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Remaining P3 decomposition work: the hourly decision tree is now branch-isolated
enough that future work should focus on either moving `build_hourly_decision(...)`
itself into the supervisor hourly module or addressing higher-leverage overnight
research quality and source-routing gaps. Keep the same proof pattern: focused
branch tests, full supervisor/CLI slice, real no-submit probe, compact context,
and process review.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 62. Hourly Buy Candidate Branch Extracted

The next order-adjacent hourly branch has been moved out of
`tradingagents/brokers/alpaca_supervisor.py` and into
`tradingagents/brokers/supervisor/hourly.py` as
`build_buy_candidate_decision(...)`. The legacy facade re-exports the helper and
`build_hourly_decision(...)` now calls it only after open-order review,
loss-review, and profit-taking have had a chance to return.

The helper preserves the exact prior buy behavior:

- no decision outside tradeable sessions;
- BOARD pause returns material `hold` and creates no action;
- green-spike/chase candidates return non-material `hold` with "do not chase";
- time-sensitive controlled dips may create a tiny-live buy inside the supplied
  unallocated live cap;
- non-urgent paper-first candidates stay paper-only.

This explicitly advances the "buy dips, sell spikes, keep sell/buy independent"
methodology without widening live authority. Profit-taking and loss-review still
outrank any clean dip-buy candidate, so the system cannot pair a sell review
with an immediate replacement buy inside the same branch.

Fresh proof:

- Focused buy-branch/facade/precedence tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "buy_candidate or aggressive_decision_can_live_buy or refuses_green_spike or board_pause or paper_first or profit_take_still_outranks or facade"`
  -> `11 passed, 66 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `77 passed`.
- Hourly plus daily-report CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_supervisor_daily_report_payload_points_to_raw_packet or compact_output_audit_finds_nested_daily_report_packets"`
  -> `17 passed, 75 deselected`.
- Targeted Ruff and compileall passed over
  `tradingagents/brokers/supervisor/hourly.py`,
  `tradingagents/brokers/alpaca_supervisor.py`, and
  `tests/test_alpaca_supervisor.py`.
- Real hourly no-submit probe:
  `results\hourly_supervisor\hourly_buy_branch_extraction_probe\hourly-supervisor-20260607-153203-899772.json`
  with `decision=loss-review`, `actions=[]`, `submitted=[]`, and `issues=[]`.
  The compact sidecar shows `submitted_count=0`, `issue_count=0`,
  `can_submit_orders=false`, and `execution_authority=none`.
- Mac helper probe was real and still failed at the host layer:
  `ssh macbook-codex ...` timed out on port 22, and
  `http://macbook-pro.tail37edd7.ts.net:11434/api/tags` timed out from
  Windows. The Mac `deepseek-r1:14b` lane remains optional/degraded until the
  host or Tailnet path is reachable; overnight still has the explicit Google
  route plus Windows local Ollama fallback.
- Safe self-heal ran on the automation-health timeliness flag:
  `research self-heal-plan --execute-safe --json-output` wrote
  `results\self_heal\plans\self-heal-plan-20260607-153551.json`, executed only
  the allowlisted night-shift patrol and automation-health refresh, and reported
  `executed_count=1`, `verified_count=1`, `verify_failed_count=0`.
- Agent Intelligence Ledger was normalized with
  `research agent-ledger-resolve --json-output`; the ledger and summary now
  both show 4,448 forecasts and 0 resolved forecasts.
- Compact context refresh cleared the temporary automation-health and
  agent-ledger schema flags. `results\_context\latest-flags.json` now shows
  only the expected hourly notify plus BOARD/loss-review drilldowns.
- Process review:
  `results\process_reviews\process-review-20260607-153657.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Remaining P3 decomposition work: extract the trailing profit-review/hold branch
or other hourly decision branches only with branch-precedence tests and a real
no-submit probe. Separately, keep Mac helper self-heal advisory until the Mac
host is reachable; do not block overnight research on it while the Google and
Windows-local routes remain healthy.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 61. Hourly Profit-Take Branch Extracted

The first order-adjacent hourly decision branch has been extracted without
changing branch precedence. `build_profit_take_decision(...)` now lives in
`tradingagents/brokers/supervisor/hourly.py` and is re-exported through the
legacy `tradingagents.brokers.alpaca_supervisor` facade. The helper covers the
"sell the spike" path only:

- returns no decision when there is no profitable live position, the position is
  below the profit-review threshold, or the current market session is not
  tradeable;
- returns a material `profit-review` packet when the position is profitable but
  current price is missing;
- returns a `profit-take` close/sell action only when the profitable position
  has a current price and the session can trade.

This keeps independent sell/buy behavior explicit. The extracted profit branch
does not size new buys, does not chase green spikes, and cannot outrank the
existing open-order or loss-review branches. New branch-precedence tests prove
open orders still win before profit-taking, and loss-review still wins before
profit-taking. The broader submit path remains governed by the unified live
guard and the current fail-closed SAFE-01 posture.

Claude submit-path handoff constraints remain prepared and verified:

- `config/risk_envelope.yaml` parses as `live_budget_mode=autonomous_with_caps`,
  `account_max_capital_at_risk_usd=250.0`, `per_name_cap_usd=50.0`, and
  `tiny_live_tranche_usd=25.0`.
- `results/policy/live_control.json` still has the lapsed dead-man at
  `2026-06-04T19:57:06+00:00`.
- Commit `3970998` contains only
  `tradingagents/policy/order_rate_limit.py` and
  `tests/test_order_rate_limit.py`; the broader shared hardening edits are still
  unstaged/shared and require hunk-level review before any commit.
- The cold-start handoff remains at
  `reports/handoff/CODEX_SUBMIT_PATH_HARDENING_HANDOFF_2026-06-05.md`.

Fresh proof:

- Focused profit/facade/precedence slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "profit or open_orders_still_outrank or loss_review_still_outrank or extracted or facade"`
  -> `8 passed, 62 deselected`.
- Windows path regression plus profit slice after daily-report path fix:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "daily_report_payload_builder_collects_context_lines or profit or open_orders_still_outrank or loss_review_still_outrank or extracted or facade"`
  -> `9 passed, 62 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `71 passed`.
- Hourly plus daily-report CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or alpaca_supervisor_daily_report or daily_report_includes_latest_premarket_brief or compact_supervisor_daily_report_payload_points_to_raw_packet or compact_output_audit_finds_nested_daily_report_packets"`
  -> `17 passed, 75 deselected`.
- Targeted Ruff passed over `tradingagents/brokers/supervisor/hourly.py`,
  `tradingagents/brokers/supervisor/daily_report.py`,
  `tradingagents/brokers/alpaca_supervisor.py`,
  `tests/test_alpaca_supervisor.py`, and `tests/test_alpaca_cli.py`.
- Compileall passed over the edited supervisor modules.
- Real hourly no-submit probe:
  `results\hourly_supervisor\hourly_profit_branch_extraction_probe\hourly-supervisor-20260607-150833-590490.json`
  with `decision=loss-review`, `submitted=[]`, `actions=[]`, and `issues=[]`.
  Its compact sidecar has `submitted_count=0`, `issue_count=0`,
  `can_submit_orders=false`, and `execution_authority=none`.
- Agent Intelligence Ledger summary refresh:
  `tradingagents.exe research agent-ledger-summary --json-output` rewrote
  `results\agent_intelligence\summary.json` with 4,443 forecasts, 0 resolved
  forecasts, and all agent influence weights neutral at `1.00` because there is
  not enough resolved history yet.
- Compact context refresh:
  `python scripts/automation_context_snapshot.py --write` cleared the previous
  `agent_intelligence_summary` schema flag. `results\_context\latest-flags.json`
  now shows only the expected hourly notify plus BOARD/loss-review drilldowns.
- Process review:
  `results\process_reviews\process-review-20260607-150907.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Remaining P3 decomposition work: extract the next hourly decision branch only
with branch-precedence tests and a real no-submit probe. Good next candidates
are the paper-first candidate branch or the trailing profit-review hold branch.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 60. Daily Report Packet IO Extracted From CLI

P3 decomposition moved supervisor daily-report packet writing and compact packet
shaping out of `cli/main.py` and into
`tradingagents/brokers/supervisor/daily_report.py` as
`write_supervisor_daily_report_packet(...)` and
`compact_supervisor_daily_report_payload(...)`. The CLI still keeps private
compatibility wrappers named `_write_supervisor_daily_report_packet(...)` and
`_compact_supervisor_daily_report_payload(...)`, so existing tests and internal
call sites keep working while the report packet contract is now owned by the
supervisor daily-report module.

This is reporting-only. The extracted helpers write JSON report packets and
compact summaries; they do not read credentials, submit/cancel orders, refresh
dead-man state, or send email.

Fresh proof:

- Daily-report CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervisor_daily_report or daily_report or compact_output_audit_finds_nested_daily_report_packets"`
  -> `5 passed, 87 deselected`.
- Targeted Ruff over `tradingagents/brokers/supervisor/daily_report.py`,
  `cli/main.py`, and `tests/test_alpaca_cli.py` passed after mechanical import
  sorting; compileall over the daily-report module and CLI passed.
- Real compact daily-report probe:
  `.\.venv\Scripts\tradingagents.exe alpaca supervisor-daily-report --json-output --compact-json-output --daily-report-log-dir results\daily_reports\daily_packet_io_extraction_probe`
  wrote
  `results\daily_reports\daily_packet_io_extraction_probe\supervisor-daily-report-20260607-145656-470308.json`
  and `latest.json`. Compact stdout reported
  `schema=compact_supervisor_daily_report_v1`, `hourly_packets=7`,
  `material_hourly_packets=7`, `ranked_candidates=40`, live equity `$198.69`,
  paper equity `$98298.21`, execution-board `can_submit_orders=false`, and
  body stored only by `raw_packet_path.body`.
- Process review
  `results\process_reviews\process-review-20260607-145724.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

The compact context flags remain the expected hourly notify plus BOARD/loss
review drilldowns. No new source, stale, schema, process, or submit blocker was
introduced by this checkpoint.

Remaining P3 decomposition work: continue branch-by-branch hourly decision
decomposition only where branch precedence can be proven; avoid moving the full
decision tree as one broad refactor.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 57. Hourly Order And Notification Helpers Extracted

P3 supervisor decomposition advanced in a small order-adjacent slice. The
hourly notification-policy helper, order-action classifier, and supervisor
order-payload formatter now live in
`tradingagents/brokers/supervisor/orders.py`:

- `should_notify_supervisor(...)`
- `is_order_action(...)`
- `build_supervisor_order_payload(...)`

The legacy `tradingagents.brokers.alpaca_supervisor` facade imports and
re-exports the same names, so existing CLI, tests, and automation imports keep
their public surface. The new module is deliberately formatting/classification
only: it does not evaluate live authority, call Alpaca, refresh dead-man state,
or submit orders.

Codex inspected the remaining hourly decision engine and found that adjacent
work has already extracted `HourlyDecisionContext` and
`build_open_orders_review_decision(...)` into the hourly module. Because the
facade is actively changing, Codex stopped this slice at the order/notification
boundary instead of forcing a large `build_hourly_decision(...)` move on top of
that state. The next slice should move the decision engine only after its
loss-exit review dependencies are isolated.

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
- Targeted Ruff over `tradingagents\brokers\supervisor\orders.py`,
  `types.py`, `hourly.py`, the supervisor facade, and focused tests passed
  after import sorting.
- Compileall over the supervisor package and facade passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\hourly_orders_extraction_probe\hourly-supervisor-20260607-142308-275624.json`
  with `decision=loss-review`, `actions=[]`, `issues=[]`, `submitted=[]`, and
  compact sidecar `submitted_count=0`, `can_submit_orders=false`,
  `execution_authority=none`.
- Automation health was refreshed after compact context saw a stale
  self-heal-follow-up warning. The fresh packet
  `results\automation_health\automation-health-audit-20260607-142426.json`
  reports 13 OK automations, no problem jobs, and timely self-heal follow-up
  with `followup_lag_seconds=52`.
- Agent Intelligence summary was refreshed after the supervisor probe advanced
  the ledger. Compact context now reports `forecast_count=4422`,
  `ledger_record_count=4422`, and `summary_ledger_count_matches=true`.
- Compact context now only carries the intentional hourly notify, hourly BOARD
  review, execution BOARD review, and loss-review evidence BOARD review routes.
- Process review
  `results\process_reviews\process-review-20260607-142453.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 decomposition work: isolate loss-exit review helpers, then move
`build_hourly_decision(...)` as a dedicated test-backed slice. Daily-report
packet IO remains a later, lower-risk extraction after the order-adjacent path
stays stable.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## Latest P3 Checkpoint: Hourly Decision Context Extracted (2026-06-07 14:09 UTC)

A code-mapper subagent reviewed `build_hourly_decision(...)` and identified the
smallest safe next seam as the pure pre-decision context scan, not the
loss-review/live-buy/profit-review branches. That context scan now lives in
`tradingagents/brokers/supervisor/hourly.py` as
`build_hourly_decision_context(...)` and returns a frozen
`HourlyDecisionContext` with held symbols, unused live capacity, top unheld
candidate, worst position, and best position. The legacy supervisor facade
imports and re-exports the helper, while `build_hourly_decision(...)` keeps the
same downstream local names and branch behavior.

This slice intentionally does not move the riskier branches. The code-mapper
called out the loss-review path, BOARD/manual-review wording, live-buy action
shape, chase suppression, and downstream live-submit validation as the parts
that should move only in later, narrower slices.

Fresh proof:

- Focused hourly/facade/context tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "decision_context or hourly_decision_context or hourly or extracted or facade or packet_writers"`
  -> `10 passed, 54 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `64 passed`.
- CLI submit-shape/hourly/report slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or submit or guard or loss_review or preopen_validation or supervisor_daily_report or compact_output_audit"`
  -> `32 passed, 60 deselected`.
- Policy IO regression:
  `uv run --no-sync --with pytest python -m pytest tests/test_policy_io.py -q`
  -> `5 passed`.
- Targeted Ruff and compileall over the hourly module, supervisor facade, policy
  IO, CLI, and focused tests passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\hourly_decision_context_probe\hourly-supervisor-20260607-140918-597923.json`
  with `decision=loss-review`, `submitted=0`, `actions=0`, and `issues=0`.
  Its compact sidecar has `schema=compact_hourly_supervisor_v1`,
  `submitted_count=0`, `execution_authority=none`, and
  `can_submit_orders=false`.
- Process review
  `results\process_reviews\process-review-20260607-140953.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 decomposition work: add direct coverage for the
`review-open-orders` early return, then move one branch at a time, starting with
the least order-adjacent branch. Do not move loss-review, live-buy, BOARD pause,
and profit-review in a single refactor.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 56. Hourly Data Contracts Extracted

P3 supervisor decomposition advanced again without moving the hourly decision
state machine. The pure hourly data contracts now live in
`tradingagents/brokers/supervisor/types.py`:

- `HourlySupervisorConfig`
- `HourlySupervisorAction`
- `HourlySupervisorDecision`

The legacy `tradingagents.brokers.alpaca_supervisor` facade imports and
re-exports the same names, so existing CLI, tests, automations, and downstream
imports keep the old public surface. This creates a stable data-contract module
for the next extraction slice, where `build_hourly_decision(...)` can move only
after its dependencies are isolated and covered.

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
- Targeted Ruff over `tradingagents\brokers\supervisor\types.py`, hourly/alert
  modules, the supervisor facade, and focused tests passed after import sorting.
- Compileall over the supervisor package and facade passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\hourly_types_extraction_probe\hourly-supervisor-20260607-140838-048532.json`
  with `decision=loss-review`, `actions=[]`, `issues=[]`, `submitted=[]`,
  `alert.severity=NOTABLE`, and compact sidecar
  `submitted_count=0`, `can_submit_orders=false`,
  `execution_authority=none`.
- Agent Intelligence summary was refreshed after compact context found a
  schema/ledger-count drift. `results\_context\latest-summary.json` now reports
  `forecast_count=4417`, `ledger_record_count=4417`, and
  `summary_ledger_count_matches=true`.
- Compact context now only carries the intentional hourly notify, hourly BOARD
  review, execution BOARD review, and loss-review evidence BOARD review routes.
- Process review
  `results\process_reviews\process-review-20260607-141028.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 decomposition work: isolate the dependencies of
`build_hourly_decision(...)` and move the decision state machine only in a
dedicated, test-backed slice. Daily-report packet IO should still wait until the
hourly order-adjacent path remains stable after that move.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 55. Hourly Alert And Email Contract Extracted

Codex re-read the Claude submit-path hardening handoff before this slice and
kept its active operating constraints in force: SAFE-01 remains fail-closed,
`config/risk_envelope.yaml` is still `autonomous_with_caps` with the local
`$250` account and `$50` per-name caps, the live-control dead-man remains
expired, and commit `3970998` is still treated as the standalone rate-limit
commit only.

P3 supervisor decomposition advanced into the hourly alert layer. The alert
dataclass, alert fingerprinting, throttling, classification, and human-readable
hourly alert email renderer now live in
`tradingagents/brokers/supervisor/alert.py`. The legacy
`tradingagents.brokers.alpaca_supervisor` facade imports the same public helper
names, so CLI callers, tests, and automation imports keep their current surface
while the alert/email contract can be tested and reviewed separately from the
hourly decision state machine.

This is intentionally not a behavior change. The alert renderer still produces
short ELI5-style operator text, loss-review alerts still require BOARD/manual
review before any loss exit, and alert emails remain downstream of the existing
notify/suppression logic. No order path, broker gate, dead-man state, or
automation status was changed.

Fresh proof:

- Email clarity eval:
  `uv run --no-sync --with pytest python -m pytest tests/test_email_clarity_eval.py -q`
  -> `4 passed`.
- Focused supervisor/CLI alert slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py -q -k "alert or email or throttle or hourly or extracted or facade or compact_hourly"`
  -> `27 passed, 128 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `63 passed`.
- Targeted Ruff over the extracted alert module, hourly module, supervisor
  facade, and focused tests passed.
- Compileall over the supervisor package and facade passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\hourly_alert_extraction_probe\hourly-supervisor-20260607-135351-891610.json`
  with `decision=loss-review`, `submitted=[]`, `actions=[]`, `issues=[]`,
  `alert.severity=NOTABLE`, `alert_email.subject="TradingAgents NOTABLE: loss-review"`,
  and a plain-English body explaining that TSM hit loss review, the bot held,
  no loss sell was submitted, and BOARD/manual review is required before a loss
  exit. The compact sidecar has `submitted_count=0`,
  `can_submit_orders=false`, and `execution_authority=none`.
- Compact context refresh still carries only the intentional hourly notify,
  hourly BOARD review, execution BOARD review, and loss-review evidence BOARD
  review routes.
- Process review
  `results\process_reviews\process-review-20260607-135731.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 decomposition work: move the hourly decision dataclasses and then
the `build_hourly_decision(...)` state machine only in smaller test-backed
slices. Daily-report packet IO can move after the hourly order-adjacent path is
stable.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 55. Generic Packet IO Moved Out Of Supervisor Facade

P3 decomposition continued with a small non-order cleanup discovered during the
hourly packet-IO slice. `cli/main.py` still depended on private
`tradingagents.brokers.alpaca_supervisor` file helpers for generic report packet
writers. That made the supervisor facade carry unrelated packet path/atomic
write helpers after the hourly extraction.

`tradingagents/policy/io.py` now owns `unique_packet_path(...)` alongside
`atomic_write_text(...)`. `cli/main.py` imports both from policy IO, and
`tradingagents/brokers/alpaca_supervisor.py` no longer re-exports the temporary
`_atomic_write_text` / `_unique_packet_path` compatibility helpers. This keeps
the supervisor facade narrower before the future `build_hourly_decision(...)`
extraction.

Fresh proof:

- Policy IO tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_policy_io.py -q`
  -> `5 passed`.
- Supervisor regression:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `63 passed`.
- CLI packet-writer/hourly slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or preopen_validation or supervisor_daily_report or compact_output_audit"`
  -> `22 passed, 70 deselected`.
- Targeted Ruff and compileall over policy IO, CLI, supervisor facade, and the
  extracted alert/helper modules passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\policy_io_cli_probe\hourly-supervisor-20260607-135402-987759.json`
  with `decision=loss-review`, `submitted=0`, `actions=0`, `issues=0`,
  compact `schema=compact_hourly_supervisor_v1`, `execution_authority=none`,
  and `can_submit_orders=false`.
- Process review
  `results\process_reviews\process-review-20260607-135909.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 decomposition work: wait for the `build_hourly_decision(...)`
dependency map, then move only the smallest low-risk decision-tree slice. Avoid
moving live-gate, BOARD/loss-review, candidate selection, and order payload
branches in one broad refactor.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 54. Hourly Packet IO Facade Delegates To Extracted Module

Codex re-read and re-verified the Claude submit-path hardening handoff before
continuing this slice. SAFE-01 remains fail-closed:
`config/risk_envelope.yaml` parses as
`live_budget_mode=autonomous_with_caps`,
`account_max_capital_at_risk_usd=250.00`, `per_name_cap_usd=50.00`, optional
hard-ceiling/rate-limit knobs unset, and `issues=[]`. The live-control dead-man
remains expired at `2026-06-04T19:57:06+00:00`; do not refresh it without
explicit operator approval. Commit `3970998` still contains only the standalone
rate-limit module plus its tests.

P3 supervisor decomposition completed the current hourly packet-IO slice:
`build_hourly_evidence(...)`, `serialize_hourly_decision(...)`, and
`write_hourly_decision_packet(...)` are owned by
`tradingagents/brokers/supervisor/hourly.py`, while the legacy
`tradingagents.brokers.alpaca_supervisor` facade keeps thin compatibility
wrappers for existing CLI/tests/automation imports. The stale duplicate
facade-only helpers `_parse_generated_at(...)`, `_atomic_write_text(...)`,
`_previous_packet_summary(...)`, and the old hourly packet path allocation block
were removed from the hourly facade surface. A small legacy
`_atomic_write_text`/`_unique_packet_path` export remains only because
`cli/main.py` still uses those generic report-writer helpers; moving that CLI
packet IO belongs in a later CLI extraction slice.

Fresh proof:

- Focused hourly/facade tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "hourly or extracted or facade or packet_writers"`
  -> `9 passed, 54 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `63 passed`.
- Hourly CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly"`
  -> `12 passed, 80 deselected`.
- Targeted Ruff over the hourly/formatting/daily-report modules, supervisor
  facade, and focused test passed; compileall over the supervisor package and
  facade passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\hourly_io_extraction_probe\hourly-supervisor-20260607-134457-819380.json`
  with `decision=loss-review`, `submitted=0`, `actions=0`, and `issues=0`.
  Its compact sidecar has `schema=compact_hourly_supervisor_v1`,
  `submitted_count=0`, `execution_authority=none`, and
  `can_submit_orders=false`.
- Process review
  `results\process_reviews\process-review-20260607-134532.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 decomposition work: keep `build_hourly_decision(...)` in the
facade until its inputs, candidate ranking, live gate references, and BOARD/loss
review branches can be moved in a separate test-backed slice. After that, move
the remaining CLI report packet IO out of `cli/main.py` so the supervisor facade
no longer has to export generic private file helpers.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 54. Hourly Evidence And Packet Writer Boundary Extracted

P3 supervisor decomposition advanced one more step without moving the hourly
decision tree. `build_hourly_evidence(...)`, the core hourly decision
serializer, and the hourly packet writer now live in
`tradingagents/brokers/supervisor/hourly.py`. The legacy
`tradingagents.brokers.alpaca_supervisor` facade preserves the public function
names and injects the existing alert classifier, alert throttler, alert email
renderer, client-order-id builder, and order-action predicate. That keeps
notification and idempotency behavior unchanged while making hourly packet IO
auditable outside the large supervisor facade.

This is intentionally not a trading-behavior change. The `build_hourly_decision`
state machine, live-submit validation, alert classification, and email
rendering remain in the facade for now and should move only in later,
smaller slices.

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
- Targeted Ruff over the extracted hourly module, supervisor facade, and
  focused tests passed; compileall over the supervisor package and facade
  passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\hourly_contract_extraction_probe\hourly-supervisor-20260607-133557-140742.json`
  with `decision=loss-review`, `submitted=[]`, `actions=[]`, and `issues=[]`.
  Its compact sidecar has `schema=compact_hourly_supervisor_v1`,
  `submitted_count=0`, `can_submit_orders=false`,
  `execution_authority=none`, `market_session=closed`, and
  `top_candidate=MSFT`.

Remaining P3 decomposition work: extract the alert/email cluster and the
decision dataclasses only after a dedicated alert-contract test slice; then
consider moving the actual `build_hourly_decision(...)` state machine last.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 53. Daily Report Renderer Extracted From Supervisor Facade

P3 decomposition advanced again: the daily digest renderer now lives in
`tradingagents/brokers/supervisor/daily_report.py`. The legacy
`tradingagents.brokers.alpaca_supervisor` facade imports and re-exports
`render_daily_supervisor_report`, so CLI, tests, and automations keep the same
public import surface.

This is a reporting-only ownership move. It does not change order submission,
live gates, risk caps, daily-report packet schema, compact-output behavior,
email routing, automation status, credentials, or dead-man state. The duplicated
private formatting helpers in `daily_report.py` are temporary by design so the
later hourly-decision extraction can move or share the alert formatting layer
without creating a circular import.

Fresh proof:

- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `63 passed`.
- Daily-report CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py::test_alpaca_supervisor_daily_report_includes_balances_and_positions tests/test_alpaca_cli.py::test_alpaca_supervisor_daily_report_compact_json_writes_raw_packet tests/test_alpaca_cli.py::test_daily_report_includes_latest_premarket_brief tests/test_alpaca_cli.py::test_compact_supervisor_daily_report_payload_points_to_raw_packet -q`
  -> `4 passed`.
- Targeted Ruff over `tradingagents\brokers\alpaca_supervisor.py`,
  `tradingagents\brokers\supervisor\daily_report.py`, and the focused
  supervisor/CLI tests passed; compileall over the supervisor package and
  facade passed.
- Real compact daily-report preview:
  `results\daily_reports\daily_report_extraction_probe\supervisor-daily-report-20260607-081540-459683.json`
  with compact stdout `schema=compact_supervisor_daily_report_v1`,
  `hourly_packets=7`, `material_hourly_packets=7`, `ranked_candidates=40`,
  `top_candidate=MSFT`, premarket context `top_symbol=XOM`, execution-board
  `can_submit_orders=false`, and a raw body reference only.

Remaining P3 decomposition work: extract hourly decision assembly and any
shared alert/report formatting in small, test-backed slices while preserving the
current public facade.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 52. Premarket Builder Extracted From Supervisor Facade

P3 decomposition advanced again: `build_premarket_brief_packet(...)` and its
private packet-record/timeline/material-change helpers now live in
`tradingagents/brokers/supervisor/premarket.py` beside the already-extracted
premarket render/compact/write/load helpers. The legacy
`tradingagents.brokers.alpaca_supervisor` facade imports and re-exports
`build_premarket_brief_packet`, so CLI, tests, and existing automations keep
the same public import surface.

This is a pure ownership move. Premarket packet schema, analysis-only posture,
latest/no-latest behavior, stale warning behavior, blocker classification, and
fresh-validation instructions remain unchanged.

Fresh proof:

- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `63 passed`.
- Premarket CLI slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py::test_premarket_brief_command_is_file_only tests/test_alpaca_cli.py::test_compact_premarket_brief_payload_points_to_raw_packet tests/test_alpaca_cli.py::test_premarket_brief_compact_json_output_is_file_only tests/test_alpaca_cli.py::test_preopen_supervisor_includes_premarket_brief_validation -q`
  -> `4 passed`.
- Targeted Ruff over `tradingagents\brokers\alpaca_supervisor.py`,
  `tradingagents\brokers\supervisor\premarket.py`, and the focused supervisor
  and CLI tests passed; compileall over the supervisor package and facade
  passed.
- Real analysis-only no-latest premarket probe:
  `results\premarket_briefs\premarket_builder_extraction_probe\premarket-brief-20260607-130409-000000.json`
  with compact stdout `schema=compact_premarket_brief_v1`,
  `source_packets=54`, `top_symbol=XOM`, `latest_hourly_decision=loss-review`,
  `paper_tournament_leader=pullback-support`, `unresolved_blockers=0`,
  `stale_warnings=0`, and `execution_authority=none`. No probe `latest.*`
  files were written.

Remaining P3 decomposition work: continue extracting hourly decision assembly
and daily-report responsibilities in small, test-backed slices while preserving
the current public facade.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 52. n8n Built-In Evaluation Full-Dataset Sync

The n8n evaluation control plane now avoids a subtle false-coverage failure.
The Data Table had 219 rows across 24 allowlisted jobs and 17 edge tags, but the
source-controlled native Evaluation Trigger workflow was capped at 25 rows. The
workflow now runs the full Data Table (`limitRows=false`, no `maxRows`) so an
editor-side native n8n evaluation can cover all generated cases.

The source-controlled workflow sync also now updates existing local n8n
workflows through the public API instead of only creating missing workflows.
This matters because otherwise a changed workflow JSON could pass repo tests
but leave `http://localhost:5678/` running an older workflow definition. The
sync keeps workflows inactive and analysis-only; it does not give n8n shell,
broker, order, email, dead-man, credential, or automation-status authority.

Fresh proof:

- Focused n8n/context tests passed with `18 passed`; targeted Ruff passed.
- Real Docker n8n workflow sync wrote
  `results\n8n_evaluations\n8n-workflow-sync-20260607-115951-020420.json` with
  `status=ok`, `source_workflow_count=12`, `existing_count=12`,
  `updated_count=12`, `created_count=0`, `api_key_redacted=true`, and all
  updated workflows inactive.
- Real native run-probe wrote
  `results\n8n_evaluations\n8n-evaluation-run-probe-20260607-120018-912286.json`
  with `status=editor_required`, `workflow_found=true`, and
  `supported_endpoint_count=0`. This confirms the public API still cannot start
  n8n's native Evaluation Trigger workflow; a visible built-in evaluation run
  must be started from the n8n editor/evaluations UI.
- Compact context now carries the proof under `n8n_evaluation_dataset`:
  `row_count=219`, `allowlisted_job_count=24`, `edge_tag_count=17`,
  `sync_current_row_count_matches=true`,
  `sync_current_dataset_generated_at_matches=true`,
  `workflow_sync_updated_count=12`, `run_probe_status=editor_required`, and no
  n8n drilldown flag.
- Process review
  `results\process_reviews\process-review-20260607-120048.json` has
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

## 51. n8n Evaluation Data Table Sync Consistency Repair

Compact context correctly flagged the n8n evaluation dataset after a real Data
Table sync because `latest-sync.json` described a newly generated in-memory
dataset while `latest.json` and `latest-compact.json` still pointed to the
previous generated dataset. Row counts matched, but
`sync_current_dataset_generated_at_matches=false`, leaving the dashboard proof
ambiguous.

Repair: `sync_n8n_evaluation_data_table(...)` now writes the exact evaluation
dataset artifacts it syncs when no packet is supplied. This keeps the JSON/CSV/
compact latest pointers and the sync proof aligned.

Proof:

- Added regression `test_n8n_api_sync_writes_same_dataset_that_it_syncs`.
- Focused n8n evaluation/context tests passed with `19 passed`.
- Targeted Ruff passed.
- Real Docker n8n sync copied `/home/node/.n8n/database.sqlite` only long
  enough to read the existing local API key, then deleted the temporary DB copy.
  The redacted sync proof now shows `status=ok`, `final_row_count=219`,
  `expected_row_count=219`, `row_count_matches=true`, `column_count=23`,
  `api_key_redacted=true`, and
  `dataset_generated_at=2026-06-07T11:33:58+00:00`.
- Refreshed compact context shows `sync_current_dataset_generated_at_matches=true`,
  `sync_current_row_count_matches=true`, `workflow_sync_status=ok`,
  `run_probe_status=editor_required`, and no n8n evaluation drilldown.
- Process review
  `results\process_reviews\process-review-20260607-113527.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

The built-in n8n evaluation workflow remains editor/UI-run gated because the
local n8n public API probe reports `editor_required`; this is now accurately
represented as an operational note rather than a stale dataset-sync audit
failure.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 50. Current Overnight Verifier and n8n Preview Proof

Codex ran the current no-submit overnight verification and n8n dashboard wrapper
after the calibration refresh. The production overnight path is healthy; the n8n
preview remains a non-authoritative dashboard helper.

Proof:

- `alpaca verify-overnight-system --json-output` wrote
  `results\overnight_system_verification\overnight-system-verification-20260607-061428.json`
  with `overall_status=pass`, 16/16 checks passing, latest packet age `1.04h`,
  expected/actual trade date `2026-06-08`, and active overnight automation.
- `results\overnight_plans\latest-compact.json` points to
  `results\overnight_plans\overnight-plan-20260607-101157-000000.json`: top
  candidate `XOM`, 40 ranked candidates, 3/3 original TradingAgents graph
  successes, 0 graph failures, 14 research-context packets, 0 research-context
  blockers, and 0 submitted orders.
- Source-quality was refreshed by the n8n preview first:
  `results\source_quality\source-quality-review-20260607-111430.json` reports
  250 sources, 224 fresh, 26 stale, 18 stale-downranked,
  `stale_needs_refresh_count=0`, 31 blocked gap packets, and 0
  missing/invalid sources.
- `n8n_runner --run-job overnight_plan_compact_preview --json` returned
  `status=ok`, `submit_capable=false`, two successful steps, and compact preview
  packet `results\overnight_plans\n8n\overnight-plan-20260607-111445-000000.json`.
  Its top candidate was `MSFT`, which is acceptable because the preview is
  deliberately zero-full-graph/no-latest/no-ledger and cannot replace the
  production overnight packet.
- Automation health
  `results\automation_health\automation-health-audit-20260607-111431.json`
  reports 13/13 automations OK, no stale/late/duplicate/missing/warning issues,
  no submissions, and timely self-heal follow-up.
- Process review
  `results\process_reviews\process-review-20260607-111600.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
- Focused tests passed: overnight verifier/source-quality `11 passed`; n8n
  overnight-preview parser `1 passed`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 49. Submit-Path Prep and Overnight Calibration Refresh

Codex re-read the Claude submit-path hardening handoff and verified current
disk state before continuing the overnight research readiness lane. The local
live posture remains fail-closed: `config/risk_envelope.yaml` parses as
`live_budget_mode=autonomous_with_caps`, account max `$250.00`, per-name
`$50.00`, optional hard-ceiling/rate-limit knobs unset, and `issues=[]`.
`results/policy/live_control.json` remains expired at
`2026-06-04T19:57:06+00:00`. No live-control refresh occurred.

The current Agent Intelligence summary had drifted stale relative to
`results\agent_intelligence\ledger.jsonl`. Codex repaired it through the
existing analysis-only CLI path, `research agent-ledger-summary --json-output`.
Compact context now reports `forecast_count=4342`, `ledger_record_count=4342`,
`summary_ledger_count_matches=true`, 10 advisory influence-weighted agents, and
0 resolved forecasts. The ledger schema drilldown is cleared.

The overnight walk-forward/calibration lane was refreshed against the latest
mature packets:

- Cohort:
  `results\research_batches\walk_forward_cohort_refresh_20260607-110407_h3.json`.
- Guard:
  `results\overnight_calibration\overnight-calibration-guard-20260607-110523.json`.
- Decision: `tighten`; `can_increase_live_influence=false`.
- Live influence policy remains conservative: new buys need controlled
  dip/support-reclaim evidence, replacement buys are disabled unless a fresh
  independent setup exists, sells remain independent profit or BOARD-approved
  thesis exits only, and bot-copycat/crowded AI names require anti-crowding
  confirmation.

Metrics justify the conservative posture:

- Deterministic sleeve:
  `directional_accuracy=0.3119`, `false_positive_rate=0.2286`,
  `average_action_relative_return=-1.2219`.
- TradingAgents advisory overlay:
  `directional_accuracy=0.5000`, `false_positive_rate=0.5000`,
  `average_action_relative_return=-0.1140`.
- Several June 7 overnight packets were skipped as `not_mature_yet`; do not use
  those for influence changes until their horizon resolves.

Fresh proof:

- Submit-path focused tests -> `168 passed`; targeted submit-path Ruff passed.
- Ledger/context/n8n focused tests -> `15 passed`.
- Replay/calibration/n8n focused tests -> `64 passed`; targeted Ruff passed.
- n8n job discovery reports 24 jobs and `submit_capable_count=0`.
- Process review
  `results\process_reviews\process-review-20260607-110647.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
- Compact context refreshed at `2026-06-07T11:06:43+00:00`; only intentional
  hourly notify, hourly BOARD review, execution BOARD review, and loss-review
  evidence review flags remain.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 49. Hourly Compact Sidecar Reason Reconciliation

The previous loss-review clarity patch cleaned `results/_context/latest-summary.json`
but did not guarantee that direct readers of
`results/hourly_supervisor/latest-compact.json` saw the same plain-English
reason. That was a pipeline ownership gap: the compact sidecar can feed
dashboards, n8n, or email paths without going through the context summary.

`scripts/automation_context_snapshot.py` now persists the refreshed loss-review
reason back into the hourly compact sidecar only when all of these are true:

- The snapshot packet is the hourly compact packet.
- The latest loss-review evidence matches the same raw hourly packet.
- The hourly compact schema is `compact_hourly_supervisor_v1`.
- The hourly decision is `loss-review`.
- The compact sidecar raw packet path matches the summary raw packet path.

The real sidecar now says:

`TSM is in loss review. No live sell was submitted. Refreshed evidence resolved
12 of 13 checks. Remaining blocker: market session is not tradeable for a live
loss exit. BOARD-only candidate: thesis_invalidated at confidence 0.78; this is
not approval to sell.`

Fresh proof:

- `uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_loss_review_evidence.py tests/test_execution_board.py -q`
  -> `88 passed`.
- `uv run --no-sync --group static-analysis ruff check scripts/automation_context_snapshot.py tests/test_automation_context_snapshot.py`
  -> passed.
- `scripts/automation_context_snapshot.py --write` reconciled the real hourly
  compact sidecar.
- `research automation-health-audit --json-output --compact-json-output` wrote
  `results/automation_health/automation-health-audit-20260607-110418.json` with
  13/13 automations OK, no issues, no duplicate automation findings, and timely
  self-heal follow-up.
- `research process-review --json-output` wrote
  `results/process_reviews/process-review-20260607-110450.json` with
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 50. Overnight Automation-Health De-Noise And Real Self-Heal Reverification

Codex removed a noisy automation-health blocker that was left behind by the
overnight latest-pointer repair. The health audit already had an intended rule
for complete analysis-only overnight reruns, but real overnight packets were
being reduced to generic metrics before classification. As a result,
`tradingagents-overnight-planning` stayed marked `duplicate` even when the
extra packets were no-order repair/verification reruns.

The audit now preserves overnight-specific fields from real packets:
`analysis_only`, `trade_date`, `submitted`, and `overnight_quality`. The
classifier now de-noises two safe cases:

- Complete no-order reruns for the same trade date.
- Superseded stale-trade-date repair runs where a later complete analysis-only
  packet for the newer trade date exists.

This still fails closed for any packet with submissions, packet issues, missing
analysis-only posture, incomplete overnight quality, or graph failures.

Fresh proof:

- Red regression:
  `test_overnight_analysis_only_complete_reruns_are_visible_but_not_health_duplicates`
  failed before the extractor patch.
- Green focused gate:
  `uv run --no-sync --with pytest python -m pytest tests/test_automation_health_audit.py tests/test_automation_context_snapshot.py tests/test_self_heal_handoff.py -q`
  -> `126 passed`.
- Targeted Ruff over automation-health/context/self-heal files and tests passed.
- Real automation-health compact latest now reports 13 OK, `duplicate_count=0`,
  no problem/attention automation ids, timely self-heal, and no submitted
  orders.
- Real self-heal plan
  `results\self_heal\plans\self-heal-plan-20260607-104423.json` reverified the
  safe-plane path after SLA and kept BOARD/order-adjacent work escalated.
- Real self-heal handoff
  `results\self_heal\self-heal-handoff-20260607-104502.json` now has
  `should_start_new_chat=false`, `active_trigger_count=0`, and
  `active_max_severity=none`.
- Compact context now has no automation-health or self-heal issue flag; only
  intended hourly/BOARD/loss-review review flags remain.
- Process review
  `results\process_reviews\process-review-20260607-104544.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 49. Claude Handoff Prep, Overnight Latest Guard, And Self-Heal Timing

Codex re-read Claude's submit-path hardening handoff and verified the current
disk state before continuing market-readiness work. The submit-path posture is
prepared, but still fail-closed:

- `config/risk_envelope.yaml` parses as
  `live_budget_mode=autonomous_with_caps`, account max `$250.00`, per-name
  `$50.00`, optional hard ceiling/rate-limit knobs unset, and `issues=[]`.
- `results/policy/live_control.json` remains expired at
  `2026-06-04T19:57:06+00:00`; this audit did not refresh the dead-man.
- Commit `3970998` still contains only the standalone live-order rate-limit
  module/test. The shared submit-path hardening files remain dirty-tree work
  that should be staged only with hunk-level review.

Pipeline reliability prep added and proved a guard for stale explicit overnight
trade dates: automation-facing overnight latest pointers now reject an explicit
stale `--trade-date` unless the caller uses `--no-write-latest` for a
historical probe. A real overnight rerun then wrote
`results\overnight_plans\overnight-plan-20260607-101157-000000.json` for
`trade_date=2026-06-08`, top `XOM`, 3/3 original graph successes, 0 graph
failures, and no submitted orders. Premarket and verification packets also
refreshed cleanly:

- `results\premarket_briefs\premarket-brief-20260607-101228-000000.json`
  -> top `XOM`, no stale warnings, `execution_authority=none`.
- `results\overnight_system_verification\overnight-system-verification-20260607-051231.json`
  -> `overall_status=pass`, expected/actual trade date `2026-06-08`, no failed
  checks.

Self-heal timing was tested through the real safe-plane monitor path.
`research self-heal-plan --execute-safe --json-output` wrote night-shift patrol
evidence, reran automation health, verified exit code 0, and left order-adjacent
BOARD signals escalated instead of auto-changing trade authority. Automation
health now records self-heal follow-up as timely inside the SLA window. After
the focused tests appended ledger rows, `research agent-ledger-summary` was run
again so the agent intelligence summary and JSONL ledger both show 4,320
forecasts.

Fresh proof:

- Focused gate:
  `uv run --no-sync --with pytest python -m pytest tests/test_order_rate_limit.py tests/test_live_gate.py tests/test_execution_safety.py tests/test_alpaca_execution.py tests/test_alpaca_cli.py tests/test_model_catalog.py tests/test_model_routing.py tests/test_self_heal_handoff.py tests/test_automation_context_snapshot.py -q`
  -> `292 passed`.
- Targeted Ruff over touched Python/test files passed.
- Final compact context has no overnight stale, preopen stale, source-quality
  schema, model-telemetry schema, or agent-intelligence schema flag.
- Process review
  `results\process_reviews\process-review-20260607-103209.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 50. Self-Heal Overlap Health De-Noise

The automation health audit now separates timely self-heal follow-up artifacts
from real automation failures. A real monitor run can produce more than one
self-heal artifact in a schedule bucket when the hook/monitor path is doing its
job quickly; that remains visible as `overlap_count`, but it should not appear
as a blocker or problem automation when the follow-up plan arrives within the
timeliness SLA.

Implementation:

- `tradingagents/evals/automation_health_audit.py` removes `overlap_run` from
  `issue_types` for self-heal rows when `self_heal_timeliness.timely=true`.
- The status reason records the de-noise branch, such as
  `self_heal_timely_overlap_artifacts_de_noised`.
- `tests/test_automation_health_audit.py` now covers the timely-overlap case
  with two same-bucket self-heal artifacts and verifies no problem automation
  is emitted.

Real proof:

- `results\automation_health\automation-health-audit-20260607-092414.json`:
  13/13 automations OK, `submitted_order_count=0`, `issue_count=0`.
- `tradingagents-self-heal-monitor`: `status=ok`, `issue_types=[]`,
  `overlap_count=1`, `self_heal_timeliness.followup_lag_seconds=26`.
- `results\_context\latest-compact.json`: no problem or attention automation
  IDs after the health refresh.
- `results\process_reviews\process-review-20260607-092443.json`:
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

This is an observability/readability repair only. It does not trade, send
email, refresh the dead-man, change schedules, or change live authority.

## 49. Mac Helper Timeout Classification

The model-helper observer now separates "Mac host is unreachable" from generic
Mac Ollama misconfiguration. This matters because the current Mac lane is a
32 GB `deepseek-r1:14b` helper for cheap source triage, contradiction hunting,
draft cleanup, and compression, not an intelligent judgment route. If the Mac
host/Tailnet path is down, overnight research should continue through Windows
local Ollama, deterministic helpers, and Codex/ChatGPT fallback rather than
flagging a hard model issue.

Current real proof:

- Route probe:
  `results\research_batches\model_route_health\research-batch-research-batch-dfd3019cbd994b43b145db01de7c3c0e.json`.
  Windows local Ollama was reachable/selected; Mac `deepseek-r1:14b` timed out
  at `http://macbook-pro.tail37edd7.ts.net:11434/api/tags`.
- Telemetry report:
  `results\model_telemetry_reports\model-telemetry-report-20260607-090501-858574.json`
  records `error_kind=mac_host_unreachable`, a plain-English fallback summary,
  and the self-heal checklist for Mac/Tailscale/SSH/Ollama recovery.
- Compact context:
  `results\_context\latest-summary.json` now preserves capped
  `blocked_route_summaries`, including the Mac recovery checklist, so n8n and
  self-heal readers do not need the raw telemetry report.
- Process review:
  `results\process_reviews\process-review-20260607-091004.json` has
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
- Focused verification: model-routing/context tests `97 passed`; targeted Ruff
  passed.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 52. Model-Helper And Overnight Readiness Refresh

The current overnight architecture does not depend on the Mac helper. A fresh
overnight-system verification packet,
`results\overnight_system_verification\overnight-system-verification-20260607-040319.json`,
passes with a 1.24-hour-old overnight plan, 3/3 full original TradingAgents
graph successes, 40 ranked candidates, no submissions, fresh premarket
checklist coverage, and active overnight automation.

Fresh helper route probes show:

- Windows local Ollama is reachable and has
  `tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest`.
- Mac Ollama tags at `macbook-pro.tail37edd7.ts.net:11434` timeout.
- SSH to `macbook-codex` also times out on port 22, so this is a
  host/Tailscale availability issue rather than just an Ollama API issue.

The current route-health packet
`results\research_batches\model_route_health\research-batch-research-batch-d3eaf44d8cae40ea984671bb77e760e6.json`
therefore selects deterministic helpers and Windows local Ollama, keeps
`research_quality_high_enough=true`, and treats Mac `deepseek-r1:14b` as
optional/degraded. The current telemetry report
`results\model_telemetry_reports\model-telemetry-report-20260607-090430-196143.json`
records deterministic success, Windows local success, Mac blocked, and
Codex/ChatGPT fallback, with zero estimated spend.

Conclusion: morning readiness should proceed without waiting for the Mac. The
Mac lane remains useful as a cheap/offloaded helper when reachable, but the
current best overnight research path is Google original graph + deterministic
helpers + Windows local summaries + Codex judgment.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 51. Agent Intelligence Summary Safe-Heal

The compact context surfaced a real stale-summary issue after new Agent
Intelligence forecasts were appended: `results/agent_intelligence/ledger.jsonl`
had 3,867 records while `summary.json` still represented an old one-forecast
state. Running the existing read-only `research agent-ledger-summary
--json-output` regenerated the summary and removed the compact schema flag.

The self-heal safe plane now knows this exact repair. When compact context flags
`agent_intelligence_summary` with `reason=schema`, it runs only allowlisted
analysis-only commands:

1. `uv run --no-sync python -m cli.main research agent-ledger-summary --json-output`
2. `uv run --no-sync python scripts/automation_context_snapshot.py --write`

This is intentionally narrower than a generic schema repair. It refreshes the
Agent Intelligence Ledger summary and compact context, but it cannot trade,
email, mutate automations, refresh live control, promote sleeves, or waive any
live gate. Order-adjacent hourly/BOARD signals continue to escalate.

Fresh proof:

- Focused tests for the new safe-plane repair plus the existing stale-ledger
  context flag -> 3 passed.
- Targeted Ruff over `tradingagents/orchestration/self_heal.py` and
  `tests/test_self_heal_handoff.py` passed.
- Real `research self-heal-plan --execute-safe --json-output` wrote
  `results\self_heal\plans\self-heal-plan-20260607-085848.json`; because the
  ledger summary had already been regenerated, it had no active safe schema
  action and skipped the order-adjacent escalations.
- Latest compact context no longer flags `agent_intelligence_summary`.
- Process review
  `results\process_reviews\process-review-20260607-085917.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 50. Claude Submit-Path And n8n Readiness Sweep

After the provider-gap check, Codex reran the specific submit-path surface from
the Claude handoff and rechecked the n8n wrapper boundary. The result preserves
the intended architecture: the Python repo owns trading logic and live gates;
n8n only discovers/runs allowlisted compact observer jobs.

Fresh proof:

- Submit-path focused regression:
  `uv run --no-sync --with pytest python -m pytest tests/test_order_rate_limit.py tests/test_live_gate.py tests/test_execution_safety.py tests/test_alpaca_execution.py tests/test_alpaca_cli.py -q`
  -> 165 passed.
- n8n job discovery:
  `python -m tradingagents.orchestration.n8n_runner --list-jobs --json`
  -> 24 jobs and `submit_capable_count=0`.
- Automation health:
  `results\automation_health\automation-health-audit-20260607-084830.json`
  -> 13/13 automations OK, no issues, no stale/late/duplicate/missing jobs,
  no submitted orders, and self-heal follow-up timely at 45 seconds.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 48. P2 Overnight Calibration Refresh

Codex refreshed the mature overnight walk-forward cohort and regenerated the
overnight calibration guard from current evidence. The June 7 overnight packets
were skipped as `not_mature_yet` until `2026-06-08`, which is the right
behavior for the weekend/next-market-date repair.

Fresh proof:

- `research walk-forward-refresh-overnight-cohort --json-output` wrote
  `results\research_batches\walk_forward_cohort_refresh_20260607-083610_h3.json`
  with 12 mature packets, 5 immature skipped packets, 175 return rows, 420
  fixture rows, and `sample_floor_met=true`.
- Replay packet
  `results\research_batches\research-batch-research-batch-7f751ce2a64a43aeb82ff1097b69b158.json`
  scored 420 deterministic rows and 20 TradingAgents advisory-overlay rows.
- `research overnight-calibration-guard --json-output` wrote
  `results\overnight_calibration\overnight-calibration-guard-20260607-083704.json`
  with `guard_decision=tighten`, `can_increase_live_influence=false`,
  deterministic action-relative return `-1.2219`, TradingAgents
  action-relative return `-0.1140`, and TradingAgents false-positive rate
  `0.5000`.
- Live influence remains tightened: controlled dip/support/reclaim only,
  no green-spike chase, no forced replacement buy after a sell, and
  anti-crowding confirmation required.
- Compact context was refreshed. Process review
  `results\process_reviews\process-review-20260607-083743.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 49. P2 Overnight Calibration De-Duplication

Codex fixed a real evidence-quality problem in the prior P2 proof. The previous
420-row fixture count was not a real sample-size increase; multiple mature
overnight packets could carry the same `symbol/as_of` decision, so the fixture
builder was counting duplicates while the return-row collector had already
deduped later performance rows. `build_walk_forward_fixture_from_overnight_packets(...)`
now keeps one decision per `symbol/as_of`, records later copies as
`duplicate_symbol_as_of`, and exposes `duplicate_skipped_count`.

Fresh proof:

- Red/green regression:
  `test_walk_forward_fixture_generator_dedupes_duplicate_symbol_as_of_rows`
  failed before the patch and passed after it.
- `research walk-forward-refresh-overnight-cohort --json-output` wrote
  `results\research_batches\walk_forward_cohort_refresh_20260607-115316_h3.json`
  with 12 mature packets, 175 return rows, 175 fixture rows, 245 skipped fixture
  rows, and `sample_floor_met=true`.
- Replay packet
  `results\research_batches\research-batch-research-batch-4e6e40129dd34dcd932391e367f758eb.json`
  scored 175 deterministic rows and 12 TradingAgents advisory-overlay rows.
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

## 47. Compact Next-Open De-Duplication

Compact flags still preserve all drilldown reasons, but `next_open` now emits a
unique path worklist. This prevents agents and n8n/dashboard readers from
opening the same compact packet twice when one packet has multiple reasons,
such as hourly `notify` plus `board_review`.

Fresh proof:

- Regression added for one hourly loss-review packet with both `notify=true`
  and `board_review`: `flags` keeps both reasons while `next_open` contains one
  path.
- Focused tests:
  `tests/test_automation_context_snapshot.py::test_snapshot_deduplicates_next_open_paths_when_packet_has_multiple_reasons`
  and
  `tests/test_automation_context_snapshot.py::test_snapshot_flags_hourly_loss_review_for_board_drilldown`
  -> `2 passed`.
- Targeted Ruff over `scripts/automation_context_snapshot.py` and
  `tests/test_automation_context_snapshot.py` -> passed.
- Real `results\_context\latest-flags.json` now has four flags but only three
  `next_open` paths: hourly, execution BOARD, and loss-review evidence.
- Process review
  `results\process_reviews\process-review-20260607-083215.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 47. BOARD-Only Loss-Exit Candidate Checkpoint

Codex re-read the Claude submit-path handoff and verified the operating
constraint before preparing the morning path: SAFE-01 is still fail-closed
(`autonomous_with_caps`, `$250.00` account cap, `$50.00` per-name cap,
`issues=[]`), the dead-man remains expired at
`2026-06-04T19:57:06+00:00`, and commit `3970998` still contains only
`tradingagents/policy/order_rate_limit.py` plus
`tests/test_order_rate_limit.py`. Broader submit-path hardening is still shared
dirty-tree work and must be staged only with hunk-level review.

The TSM loss-review evidence bridge now converts refreshed evidence into a
BOARD-only candidate instead of leaving generic blockers for the user to decode.
The evidence packet at
`results\loss_review_evidence\source-evidence-source-evidence-a2b1faa05e0a4ee5bb6b50e99c175f8d.json`
targets
`results\hourly_supervisor\hourly-supervisor-20260607-082307-913209.json`.
Its compact wrapper keeps packet metadata at the root and stores the decision
fields under `payload.advisory_summary`. That nested payload now includes:

- `current_thesis_status_candidate=thesis_under_pressure_falling_knife_watch`.
- `loss_exit_candidate.allowed_exit_reason_candidate=thesis_invalidated`.
- `loss_exit_candidate.allowed_exit_reason_source=refreshed_loss_review_evidence`.
- `loss_exit_candidate.confidence=0.78` and `confidence_tier=medium`.
- `loss_exit_candidate.approval_effect=board_review_input_not_loss_exit_approval`.

This resolves 12 loss-review evidence blockers while preserving the safety
line: `review_allowed=false`, `execution_authority=none`,
`can_submit_orders=false`, and the only remaining blocker is
`market session is not tradeable for a live loss exit`.

The refreshed BOARD packet
`results\execution_board\execution-board-review-20260607-082625.json` now
matches the latest hourly/evidence window. It found zero hard violations and
keeps the next-hour policy explicit: sells are independent from buys, a
loss-exit candidate does not force a replacement buy, and new buys still need
separate controlled dip/support evidence with no green-spike chasing.

## 50. Claude Submit-Path Prep Checkpoint

Codex re-read the Claude deep-review response and
`reports/handoff/CODEX_SUBMIT_PATH_HARDENING_HANDOFF_2026-06-05.md` before
continuing the pipeline work. The submit-path safety state is prepared and
fail-closed, but this does not close the broader architecture program.

Verified current state:

- SAFE-01 is fail-closed:
  `config/risk_envelope.yaml` loads as `autonomous_with_caps`, `$250.00`
  account cap, `$50.00` per-name cap, optional hard-ceiling/rate-limit knobs
  unset, and `issues=[]`.
- Live control remains expired:
  `results/policy/live_control.json` has
  `dead_man_expires_at=2026-06-04T19:57:06+00:00`.
- Commit `3970998` is still limited to the standalone rate-limit module and
  tests, so the rest of the submit-path hardening edits remain dirty shared
  worktree state requiring hunk-level staging before any future commit.
- `CONTEXT_ROUTER.md` now marks the old 2026-06-05/06 "Nearest checks" row as
  historical/superseded. Agents should start from `Current nearest checks`,
  compact context, and the newest process-review packet instead of old packet
  names.

Fresh proof:

- `git show --stat --oneline 3970998` -> only
  `tradingagents/policy/order_rate_limit.py` and
  `tests/test_order_rate_limit.py`.
- Risk envelope loader sanity -> mode `autonomous_with_caps`, account max
  `$250.00`, per-name `$50.00`, no optional hard ceiling, no optional order
  rate limit, and no loader issues.
- `scripts/automation_context_snapshot.py --write` refreshed compact context.
- `research process-review --json-output` wrote
  `results\process_reviews\process-review-20260607-091259.json` with
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
- `results\_context\latest-flags.json` contains only the intended hourly
  notify/BOARD/loss-review routes.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 49. Claude-Review Provider Gap Readiness Check

The Claude submit-path handoff was re-read and the active safety posture was
verified before testing the research/provider layer. `config/risk_envelope.yaml`
still loads as `autonomous_with_caps` with `$250.00` account and `$50.00`
per-name caps, no optional hard-ceiling/rate-limit knobs armed, and `issues=[]`.
`results/policy/live_control.json` still has the expired dead-man at
`2026-06-04T19:57:06+00:00`. This section is research-readiness proof only; it
does not arm live authority.

The optional-but-high-leverage evidence categories from the audit are now
current live-data checks, not just planned routes. Real analysis-only provider
bundles ran for `CVX` (latest overnight top) and `MSFT` (latest preopen rank)
with `earnings_transcripts`, `short_interest`, and `options_iv_flow`.

Evidence behavior is conservative:

- Transcript routes attempt cache/connected/vendor paths and then write a
  blocked `earnings_transcripts_gap` when no authoritative transcript is
  available.
- Short-interest and options routes can use public yfinance supplemental
  packets, but they stay low-authority and confirmation/downrank-only.
- When supplemental public evidence exists but an authoritative source is still
  missing, a blocked gap packet may also be written. That is intentional: it
  prevents weak public evidence from being mistaken for a complete institutional
  source stack.

Fresh proof:

- `CVX` summary packet:
  `results\research_evidence\source-evidence-source-evidence-f64c4d5e9bde40128a57c589af76d4b0.json`.
- `MSFT` summary packet:
  `results\research_evidence\source-evidence-source-evidence-83b72d4f141e4f79b029a834ade79d18.json`.
- Source-quality review after those bundles:
  `results\source_quality\source-quality-review-20260607-084521.json`, 250
  sources reviewed, 241 fresh, 9 stale, 6 stale-downranked, 32 blocked,
  0 missing/invalid, and no stale source requiring refresh.
- Focused tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_research_provider_orchestrator.py tests/test_source_quality.py -q`
  -> 37 passed.
- Targeted Ruff over provider/source-quality/dataflow tests and modules passed.
- Compact context refreshed and process review
  `results\process_reviews\process-review-20260607-084555.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 53. P3 Supervisor Candidate/Sizing/Session/Premarket Decomposition

The remaining P3 supervisor-decomposition roadmap is now underway with a
compatibility-preserving pure slice. Candidate-ranking helpers moved out of
the monolithic `tradingagents/brokers/alpaca_supervisor.py` into
`tradingagents/brokers/supervisor/candidates.py`, and dynamic-cap/exposure
helpers moved into `tradingagents/brokers/supervisor/sizing.py`. Market-session
helpers moved into `tradingagents/brokers/supervisor/session.py`. Premarket
validation, research-context compaction, expected hourly safety-lock
classification, and blocker splitting moved into
`tradingagents/brokers/supervisor/premarket.py`:

- `CandidateSignal`.
- `build_candidate_signals(...)`.
- `is_chase_buy_candidate(...)` and `is_buy_entry_candidate(...)`.
- `choose_autonomous_live_buy_notional(...)`.
- `aggressive_limit_price(...)`.
- The aggressive universe and MiroFish/report-33 candidate-scoring constants.
- `BASE_LIVE_CAP`, `MAX_DYNAMIC_LIVE_CAP`.
- `live_exposure_from_positions(...)`, `total_unrealized_pl(...)`, and
  `calculate_dynamic_live_cap(...)`.
- `market_session_label(...)` and `can_trade_session(...)`.
- `validate_premarket_brief_against_candidates(...)`.
- `is_expected_hourly_safety_lock(...)`.
- Premarket research-context/prior-feed compaction and blocker splitting.

`alpaca_supervisor.py` keeps explicit facade exports, so public imports remain
stable for the CLI, tests, and paper tournament. This is a pure refactor slice:
no live-gate, cap, order-submission, packet-schema, automation-status, email,
credential, or dead-man behavior changed.

Fresh proof:

- Candidate/no-chase/sizing focused tests: `9 passed`.
- Follow-up candidate/sizing regression after dynamic-cap extraction:
  `4 passed`.
- Follow-up session/facade regression after market-session extraction:
  `2 passed`.
- Focused premarket extraction regression: `6 passed`.
- Full `tests/test_alpaca_supervisor.py`: `63 passed`.
- Import-adjacent CLI/paper tournament slice: `3 passed`.
- CLI premarket slice: `4 passed`.
- Targeted Ruff over touched supervisor files and tests passed.
- Compile check over the new supervisor package and legacy facade passed.
- Real hourly dry-run compact probe:
  `results\hourly_supervisor\premarket_module_probe\hourly-supervisor-20260607-124208-635006.json`
  with `submitted_count=0`, `can_submit_orders=false`, and no live authority.
- Real file-only premarket compact probe:
  `results\premarket_briefs\premarket_module_probe\premarket-brief-20260607-124159-000000.json`
  with `source_packets=54`, `unresolved_blockers=0`, `stale_warnings=0`, and
  `execution_authority=none`.
- Real no-latest/no-research-context overnight compact probe:
  `results\overnight_plans\premarket_module_probe\overnight-plan-20260607-124210-000000.json`
  with `trade_date=2026-06-08`, `ranked_candidates=40`, `submitted_count=0`,
  and `execution_authority=none`.
- Compact context still has only expected hourly/BOARD/loss-review review
  flags, and process review
  `results\process_reviews\process-review-20260607-122005.json` reports
  `unchecked_step_count=0`.

Remaining P3 decomposition work: continue extracting `hourly`, the remaining
premarket packet construction/rendering/writing layer, and `daily_report`
responsibilities in small, test-backed slices while preserving the existing
public entry points.

## 48. Hourly Loss-Review Reason Clarity

The compact context path now fixes the user-facing reason string, not just the
structured fields. When matching refreshed loss-review evidence exists for the
same raw hourly packet, `scripts/automation_context_snapshot.py` rewrites the
hourly `reason` from the stale original blocker list to a short plain-English
summary.

Current real `results\_context\latest-summary.json` hourly reason:
`TSM is in loss review. No live sell was submitted. Refreshed evidence resolved
12 of 13 checks. Remaining blocker: market session is not tradeable for a live
loss exit. BOARD-only candidate: thesis_invalidated at confidence 0.78; this is
not approval to sell.`

This keeps alert/email/context readers aligned with the refreshed evidence:
BOARD sees a candidate, but no live sell is approved; only the tradeable-session
blocker remains visible in the short reason.

Fresh proof:

- Red regression:
  `test_snapshot_rewrites_hourly_loss_review_reason_from_refreshed_evidence`
  failed before the translator patch because `summary["reason"]` still had the
  stale blocker list.
- Green focused slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_loss_review_evidence.py tests/test_execution_board.py -q`
  -> `85 passed`.
- Targeted Ruff over the context/loss-review/BOARD files and tests passed.
- Real context refresh wrote the shorter hourly reason to
  `results\_context\latest-summary.json`.
- Process review
  `results\process_reviews\process-review-20260607-084432.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 49. n8n Evaluation Dataset Covers Duplicate Evidence

The n8n evaluation/control-plane layer now tests the overnight calibration
dedupe failure mode. The dataset adds
`duplicate_evidence_deduped_before_scoring` across the allowlisted jobs, with
`duplicate_evidence`, `source_quality`, and `no_live_submit` tags. This keeps
n8n as a wrapper/evaluation surface while the Python repo remains the owner of
calibration, source-quality, and no-submit enforcement.

Fresh proof:

- `research n8n-evaluation-dataset --json-output --compact-json-output` wrote
  `results\n8n_evaluations\n8n-evaluation-dataset-20260607-120614-394063.json`
  with `row_count=243`, `allowlisted_job_count=24`,
  `edge_tag_count=18`, and `duplicate_evidence` present.
- `research n8n-sync-evaluation-table --api-key-sqlite-db <temporary-db-copy>`
  wrote `results\n8n_evaluations\n8n-api-sync-20260607-120733-909721.json`
  with `inserted_count=24`, `final_row_count=243`, and
  `row_count_matches=true`. The temporary n8n DB copy was deleted after use.
- `research n8n-evaluation-run-probe --api-key-sqlite-db <temporary-db-copy>`
  wrote
  `results\n8n_evaluations\n8n-evaluation-run-probe-20260607-120833-367542.json`.
  It found workflow `TA * Built-in Automation Evaluation`
  (`taBuiltInAutomationEvaluation`) and returned `status=editor_required`
  because the probed local n8n API endpoints did not remotely start built-in
  editor evaluation runs.
- `uv run --no-sync --with pytest python -m pytest tests/test_n8n_evaluations.py -q`
  -> `16 passed`.
- `uv run --no-sync --with pytest python -m pytest tests/test_n8n_runner_policy.py -q -k "evaluation_dataset or overnight_calibration"`
  -> `3 passed, 43 deselected`.
- Targeted Ruff passed for the n8n evaluation dataset code and tests.
- Process review
  `results\process_reviews\process-review-20260607-120903.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 50. Compact Context Agent-Ledger Cleanup

After the n8n evaluation work advanced the Agent Intelligence Ledger,
`research agent-ledger-summary --json-output` refreshed the saved summary so
compact context no longer emits a schema drilldown for a stale ledger count.

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

## 51. Overnight Packet IO Extracted From Supervisor Facade

P3 decomposition advanced one step: overnight packet writing, compacting,
markdown rendering, latest loading, and candidate validation now live in
`tradingagents/brokers/supervisor/overnight.py`. The legacy
`tradingagents.brokers.alpaca_supervisor` facade imports and re-exports those
helpers so CLI, tests, and existing automations keep their public imports.

This is intentionally not a behavior change. Packet schemas, latest/no-latest
behavior, analysis-only posture, and validation statuses remain the same. The
move makes the overnight research foundation easier to audit separately from
hourly trading decisions.

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
- Targeted Ruff over `tradingagents\brokers\supervisor\overnight.py`,
  `tradingagents\brokers\alpaca_supervisor.py`, and
  `tests\test_alpaca_supervisor.py` passed; compileall over the supervisor
  package and facade passed.
- Real analysis-only no-latest probe:
  `results\overnight_plans\overnight_packet_extraction_probe\overnight-plan-20260607-124445-000000.json`
  with `analysis_only=true`, `trade_date=2026-06-08`,
  `ranked_candidates=40`, `submitted=[]`, and `execution_authority=none`.
  The probe directory has raw, compact, and markdown packets and no `latest.*`
  files.
- Real automation-facing verifier:
  `results\overnight_system_verification\overnight-system-verification-20260607-074606.json`
  reports `overall_status=pass`, latest overnight packet age `2.57h`, Monday
  trade date `2026-06-08`, 3/3 original graph successes, and no submitted
  orders.
- Compact context still only carries the intentional hourly notify, hourly
  BOARD review, execution BOARD review, and loss-review evidence BOARD review
  routes. Process review
  `results\process_reviews\process-review-20260607-124635.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 decomposition work: continue extracting hourly decision assembly,
premarket packet IO, and daily-report responsibilities in small, test-backed
slices while preserving the current public facade.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 52. Premarket Packet IO Extracted From Supervisor Facade

P3 supervisor decomposition advanced another step: premarket brief markdown
rendering, compact packet creation, packet writing, latest loading, expected
hourly safety-lock classification, and candidate validation now live in
`tradingagents/brokers/supervisor/premarket.py`. The legacy
`tradingagents.brokers.alpaca_supervisor` facade imports and re-exports the
same helper names, so CLI callers, tests, and automations keep their public
surface while premarket research packet behavior is easier to audit separately
from hourly trading decisions.

This is intentionally not a behavior change. Premarket packets remain
`analysis_only`, `execution_authority=none`, and latest/no-latest behavior is
preserved for production writes versus probes.

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
- Targeted Ruff over `tradingagents\brokers\supervisor\premarket.py`,
  `tradingagents\brokers\alpaca_supervisor.py`, and
  `tests\test_alpaca_supervisor.py` passed after import sorting; compileall over
  the supervisor package and facade passed.
- Real analysis-only no-latest probe:
  `results\premarket_briefs\premarket_packet_extraction_probe\premarket-brief-20260607-125905-000000.json`
  with `analysis_only=true`, `execution_authority=none`, `source_packets=54`,
  `top_symbol=XOM`, `unresolved_blockers=0`, and `stale_warnings=0`. The probe
  directory has raw, compact, and markdown packets and no `latest.*` files.
- Compact context after refresh still carries only the intentional hourly
  notify, hourly BOARD review, execution BOARD review, and loss-review evidence
  BOARD review routes.
- Process review
  `results\process_reviews\process-review-20260607-130803.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 decomposition work: continue extracting hourly decision assembly
and daily-report responsibilities in small, test-backed slices while preserving
the public facade.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 53. Hourly Compact Packet Helpers Extracted

P3 supervisor decomposition advanced into the hourly path without touching the
decision tree. `compact_hourly_supervisor_payload(...)` and
`find_latest_hourly_packet(...)` now live in
`tradingagents/brokers/supervisor/hourly.py`. The legacy
`tradingagents.brokers.alpaca_supervisor` facade imports and re-exports both
helpers, so CLI callers, compact-context readers, tests, and automation imports
keep their existing surface.

This slice intentionally leaves `build_hourly_decision(...)`,
`serialize_hourly_decision(...)`, and `write_hourly_decision_packet(...)` in the
facade for now. The stateful decision tree and order-adjacent serialization are
higher-risk and should move only in smaller follow-up slices with real probes.

The duplicated hourly/daily reason-text formatter was also moved into
`tradingagents/brokers/supervisor/formatting.py`. Both the daily digest renderer
and hourly alert email renderer now share the same pure truncation/decimal
cleanup helper.

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
- Targeted Ruff over the new hourly/formatting modules, daily report module,
  supervisor facade, and focused test passed; compileall over the supervisor
  package and facade passed.
- Real dry-run no-submit probe:
  `results\hourly_supervisor\hourly_packet_extraction_probe\hourly-supervisor-20260607-132214-836105.json`
  with `decision=loss-review`, `submitted=0`, `actions=0`, and `issues=0`.
  Its compact sidecar has `schema=compact_hourly_supervisor_v1`,
  `submitted_count=0`, and `execution_authority=none`.
- Process review
  `results\process_reviews\process-review-20260607-132832.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Remaining P3 decomposition work: move `build_hourly_evidence(...)`,
`serialize_hourly_decision(...)`, and `write_hourly_decision_packet(...)` only
after the call contract is isolated; then consider moving CLI daily-report
packet IO out of `cli/main.py`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## Tail Pointer: Latest P3 Checkpoint (2026-06-07 14:12 UTC)

The latest P3 work is the mapper-backed hourly decision context extraction:
`HourlyDecisionContext` and `build_hourly_decision_context(...)` now live in
`tradingagents/brokers/supervisor/hourly.py`, and the supervisor facade uses
that pure context helper without moving branch semantics. Checkpoint process
review: `results\process_reviews\process-review-20260607-141222.json` with
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

## Tail Pointer: Latest P3 Checkpoint (2026-06-07 14:22 UTC)

The latest P3 work moved the no-action `review-open-orders` early return into
`tradingagents/brokers/supervisor/hourly.py` as
`build_open_orders_review_decision(...)`. Direct helper coverage now proves the
inspection packet has no actions/submissions, and branch precedence coverage
proves open orders are reviewed before loss-review or buy logic. Current process
review: `results\process_reviews\process-review-20260607-142241.json` with
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

## Tail Pointer: Latest canonical checkpoint (2026-06-07 14:30 UTC)

Use this tail pointer if earlier checkpoints conflict or appear out of order.
Codex re-read the Claude submit-path hardening response and current handoff
before continuing. SAFE-01 is still fail-closed:
`config/risk_envelope.yaml` parses as `autonomous_with_caps` with
`account_max_capital_at_risk_usd=250.00`, `per_name_cap_usd=50.00`,
`tiny_live_tranche_usd=25.00`, optional hard-ceiling/rate-limit knobs unset,
and `issues=[]`; the live-control dead-man remains lapsed at
`2026-06-04T19:57:06+00:00`. Commit `3970998` still contains only the
standalone live-order rate-limit module and test.

The overnight pipeline is currently healthy. `alpaca verify-overnight-system
--json-output` wrote
`results\overnight_system_verification\overnight-system-verification-20260607-092939.json`
with `overall_status=pass`, 16/16 checks passed, 0 warnings/failures,
`execution_authority=none`, and no submitted orders. The latest production
overnight packet is
`results\overnight_plans\overnight-plan-20260607-101157-000000.json`: trade
date `2026-06-08`, top symbol `XOM`, 40 ranked candidates, explicit Google
compact graph route, 3/3 original TradingAgents graph successes, 37 fallback
rankings, 0 graph failures, and `submitted=[]`. Automation health also passed
with `results\automation_health\automation-health-audit-20260607-142940.json`
showing 13/13 automations ok and no stale/late/missing/timeliness issues. The
overnight automation is allowed to be `PAUSED` after a complete current packet;
the verifier enforces that as `ACTIVE_OR_PAUSED_AFTER_COMPLETE_PACKET`.

Current process review:
`results\process_reviews\process-review-20260607-143611.json` with
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

## Tail Pointer: Latest canonical checkpoint (2026-06-07 14:46 UTC)

Use this tail pointer if earlier checkpoints conflict or appear out of order.
P3/P5 cleanup advanced one small slice: hourly packet writing now calls the
shared `tradingagents.policy.io.unique_packet_path(...)` helper instead of a
private duplicate allocator in `tradingagents/brokers/supervisor/hourly.py`.
The supervisor facade still wraps the extracted helper to inject alert/email
and live-client-order dependencies.

`CONTEXT_ROUTER.md` first-screen evidence was also refreshed. The current
overnight proof is
`results\overnight_system_verification\overnight-system-verification-20260607-094459.json`
with `overall_status=pass`, 16/16 checks passed, no warnings/failures,
`execution_authority=none`, and no submitted orders. The latest production
overnight packet remains
`results\overnight_plans\overnight-plan-20260607-101157-000000.json`.
The final process review for this slice is
`results\process_reviews\process-review-20260607-144636.json` with
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Focused proof: `tests/test_policy_io.py tests/test_alpaca_supervisor.py` ->
`71 passed`; hourly/overnight CLI slice -> `21 passed, 71 deselected`;
targeted Ruff and compileall passed; real hourly dry-run probe
`results\hourly_supervisor\shared_packet_io_probe\hourly-supervisor-20260607-144555-943520.json`
submitted no orders and wrote a compact no-authority sidecar.

## 58. Hourly Loss-Review Packet Helpers Extracted

P3 supervisor decomposition moved the loss-exit review evidence packet builder
out of `tradingagents/brokers/alpaca_supervisor.py` and into
`tradingagents/brokers/supervisor/loss_review.py`.
`tradingagents.brokers.alpaca_supervisor` now imports and re-exports
`loss_exit_review_packet(...)`, and the old private
`_loss_exit_review_packet(...)` is a compatibility wrapper. This keeps existing
CLI/test/automation imports stable while giving BOARD/loss-review evidence a
dedicated module with no broker submission authority.

The extracted helper owns the allowed loss-exit reason taxonomy, recent-position
churn guard, required SPY/QQQ/sector evidence checks, broad-market red-day
filter, holding-period parsing, confidence/source-packet requirements, and the
loss-exit blocker list. It still only returns a packet; it does not size,
approve, submit, cancel, refresh dead-man state, or send email.

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
- Targeted Ruff over the supervisor modules, facade, and focused tests passed;
  compileall over the supervisor package and facade passed.
- Real hourly no-submit probe:
  `results\hourly_supervisor\hourly_loss_review_extraction_probe\hourly-supervisor-20260607-143752-856089.json`
  with `decision=loss-review`, `submitted=[]`, `actions=[]`, `issues=[]`, and
  compact sidecar
  `results\hourly_supervisor\hourly_loss_review_extraction_probe\latest-compact.json`
  showing `submitted_count=0`, `issue_count=0`, `can_submit_orders=false`, and
  `execution_authority=none`.
- Process review
  `results\process_reviews\process-review-20260607-143822.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

The latest compact context flags remain the intentional loss-review/BOARD review
routes; no new stale/source/schema/process blocker was introduced by this slice.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes. SAFE-01 remains fail-closed: local live caps are armed under
`autonomous_with_caps`, and the dead-man remains lapsed.

## 59. Hourly Packet IO Boundary Locked

The "isolate the rest of hourly packet IO" P3 item is now explicitly covered.
`build_hourly_evidence(...)`, `serialize_hourly_decision(...)`, and
`write_hourly_decision_packet(...)` already live in
`tradingagents/brokers/supervisor/hourly.py`. This checkpoint added direct
module-level coverage proving the extracted hourly packet writer accepts
injected facade callbacks for alert classification, throttling, email rendering,
client-order-id generation, and order-action detection. The legacy
`tradingagents.brokers.alpaca_supervisor` wrapper still supplies the production
callbacks, so existing callers keep the same simple API while the extracted
module stays independent of broker submission and email side effects.

This intentionally does not move `build_hourly_decision(...)`. The decision
tree is order-adjacent and should remain in place until its branches can be
moved one at a time with branch-precedence tests and real no-submit probes.

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
- Targeted Ruff over `tradingagents/brokers/supervisor/hourly.py`,
  `tradingagents/brokers/supervisor/loss_review.py`,
  `tradingagents/brokers/alpaca_supervisor.py`, and the focused tests passed;
  compileall over the supervisor package and facade passed.
- Real hourly no-submit probe:
  `results\hourly_supervisor\hourly_packet_io_boundary_probe\hourly-supervisor-20260607-144620-165773.json`
  with `decision=loss-review`, `submitted=[]`, `actions=[]`, `issues=[]`, and
  compact sidecar
  `results\hourly_supervisor\hourly_packet_io_boundary_probe\latest-compact.json`
  showing `submitted_count=0`, `issue_count=0`, `can_submit_orders=false`, and
  `execution_authority=none`.
- Process review
  `results\process_reviews\process-review-20260607-144649.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

The compact context flags remain the expected hourly notify plus BOARD/loss
review drilldowns. No new source, stale, schema, process, or submit blocker was
introduced by this checkpoint.

Remaining P3 decomposition work: extract daily-report responsibilities from
`cli/main.py`, then continue branch-by-branch hourly decision decomposition only
where branch precedence can be proven.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 60. Daily Report Payload Boundary Extracted

The "extract daily-report responsibilities from `cli/main.py`" P3 item has now
advanced into a tested packet-boundary split. `cli/main.py` still owns the
runtime-only responsibilities: Alpaca account/position/order reads, current
candidate construction, CLI options, and validation of the latest premarket
brief against current candidates. The report payload/body/context assembly now
lives with the renderer and compact writer in
`tradingagents/brokers/supervisor/daily_report.py`:

- `build_supervisor_daily_report_payload(...)` creates the raw daily-report
  packet shape.
- `daily_model_telemetry_line(...)` and
  `daily_execution_board_line(...)` own the report context lines that were
  previously private CLI helpers.
- `write_supervisor_daily_report_packet(...)` and
  `compact_supervisor_daily_report_payload(...)` remain the packet writer and
  compact context contract.

This is intentionally a behavior-preserving extraction. It does not move broker
reads, does not add email authority, and does not touch submit-path logic. Claude
submit-path constraints remain prepared and verified: SAFE-01 is fail-closed
under `autonomous_with_caps`, the live-control dead-man is expired at
`2026-06-04T19:57:06+00:00`, and commit `3970998` still contains only the
standalone rate-limit module/test.

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
- Targeted Ruff and compileall passed over the edited Python files.
- Real daily-report compact probe:
  `results\daily_reports\daily_report_payload_builder_probe\supervisor-daily-report-20260607-150720-246270.json`
  with `schema=compact_supervisor_daily_report_v1`, 7 hourly packets, 40 ranked
  candidates, top candidate `MSFT`, BOARD `can_submit_orders=false`, no email
  flag, and no submit-capable path.
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

## 61. Hourly Loss-Review Branch Extracted

The next branch-by-branch hourly decomposition slice moved the loss-review
decision branch out of `tradingagents/brokers/alpaca_supervisor.py` and into
`tradingagents/brokers/supervisor/hourly.py` as
`build_loss_review_decision(...)`. The helper uses the existing pure
`loss_exit_review_packet(...)` evidence builder and keeps the same policy:

- loss exits require explicit thesis-break/exit evidence;
- non-tradeable sessions block live loss exits;
- approved loss exits generate a sell plus independent `hold_cash`, not a
  forced replacement buy;
- missing current-price evidence returns `loss-review`, not an order.

The facade still supplies session/current-price/liveness dependencies and keeps
the public `build_hourly_decision(...)` API stable. Open-order review still
outranks loss-review; loss-review still outranks profit-taking and buy logic.

Fresh proof:

- Focused loss-review/precedence slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "loss_review or loss_exit or open_orders_still_outrank_profit_take or loss_review_still_outranks_profit_take or extracted"`
  -> `13 passed, 60 deselected`.
- Full supervisor tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q`
  -> `73 passed`.
- Hourly CLI guard/submit slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q -k "supervise_hourly or compact_hourly or loss_review or submit or guard"`
  -> `24 passed, 68 deselected`.
- Targeted Ruff and compileall passed over
  `tradingagents/brokers/supervisor/hourly.py`,
  `tradingagents/brokers/alpaca_supervisor.py`, and
  `tests/test_alpaca_supervisor.py`.
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

## 62. Hourly Buy/No-Chase Tail Verified

The buy/paper-first/no-chase tail of `build_hourly_decision(...)` is now
confirmed as extracted and wired through
`tradingagents/brokers/supervisor/hourly.py::build_buy_candidate_decision(...)`.
The facade delegates the candidate-entry branch after open-order review,
loss-review, and profit-taking, preserving branch precedence.

Direct coverage proves the behavior the strategy needs:

- controlled dips can become tiny-live buys when score, time sensitivity,
  session, and live unallocated notional qualify;
- green spikes return `hold` with no actions, so the system does not chase
  already-moved stocks;
- BOARD new-buy pause returns a material hold and blocks new buys;
- nonurgent candidates remain paper-first;
- loss-review does not rotate into a green-spike buy or pair a loss review with
  a clean dip buy.

Fresh proof:

- Focused buy/no-chase/paper-first tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py -q -k "buy_candidate or live_buy_time_sensitive_controlled_dip or green_spike_chase or board_pause or paper_first or loss_review_does_not_pair or loss_review_does_not_rotate"`
  -> `10 passed, 67 deselected`.
- Combined hourly/supervisor/CLI tail slice:
  `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py -q -k "buy_candidate or live_buy_time_sensitive_controlled_dip or green_spike_chase or board_pause or paper_first or loss_review_does_not_pair or loss_review_does_not_rotate or supervise_hourly or compact_hourly"`
  -> `22 passed, 147 deselected`.
- Targeted Ruff passed over
  `tradingagents/brokers/supervisor/hourly.py`,
  `tradingagents/brokers/alpaca_supervisor.py`, and
  `tests/test_alpaca_supervisor.py`.
- Real hourly no-submit probe:
  `results\hourly_supervisor\hourly_buy_tail_probe\hourly-supervisor-20260607-153130-530914.json`
  with compact sidecar `latest-compact.json`, `decision=loss-review`,
  `submitted_count=0`, `issue_count=0`, `can_submit_orders=false`,
  `execution_authority=none`, and `action_count=0`.
- Process review:
  `results\process_reviews\process-review-20260607-153207.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Remaining P3 decomposition work: the main hourly decision tree is now mostly a
branch router. Continue extracting any remaining final hold/profit-review tail
only if it removes meaningful duplication or makes branch precedence easier to
prove; otherwise shift to the next higher-leverage plan item.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, self-heal timeliness and agent-ledger schema repair, 2026-06-07
16:27 UTC:

The transient `agent_intelligence_summary` schema drilldown was caused by
`results\agent_intelligence\summary.json` lagging behind
`results\agent_intelligence\ledger.jsonl`. The safe refresh path repaired it:
`research agent-ledger-summary --json-output` rewrote the summary with
`forecast_count=4491`, matching the 4,491 ledger records, and compact context
now reports `summary_ledger_count_matches=true` with no schema drilldown.

The self-heal monitor was also tested end-to-end with the real automation
sequence. It wrote handoff
`results\self_heal\self-heal-handoff-20260607-162425.json`, then wrote plan
`results\self_heal\plans\self-heal-plan-20260607-162437.json` 12 seconds
later. The plan intentionally escalated BOARD/order-adjacent review signals
instead of auto-fixing them. Automation health
`results\automation_health\automation-health-audit-20260607-162446.json`
reports 13/13 automations OK, `timeliness_issue_count=0`, and
self-heal follow-up `timely=true`.

Fresh proof:

- Focused self-heal and automation-health tests -> `6 passed`.
- Process review:
  `results\process_reviews\process-review-20260607-162700.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.
- Refreshed compact flags now contain only the intentional hourly/BOARD/loss
  review drilldowns; no `agent_intelligence_summary` schema flag and no
  automation-health flag remain.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, Claude handoff and fresh BOARD/loss-review refresh, 2026-06-07
16:40 UTC:

The Claude submit-path hardening handoff remains prepared for follow-on agents.
SAFE-01 is still fail-closed in local machine state, and commit `3970998`
remains the standalone unsigned order-rate-limit commit only. Do not fold the
shared dirty submit-path hardening edits into that commit without hunk-level
review.

The live loss-review/BOARD path was refreshed from current packets. Loss-review
evidence `results\loss_review_evidence\source-evidence-source-evidence-5aaad830f6e244ada344c4ff0bd1b4b9.json`
resolved 12 of the 13 prior TSM loss-review blockers and left only
`market session is not tradeable for a live loss exit`. It is analysis-only,
`can_submit_orders=false`, and `execution_authority=none`.

Execution BOARD packet
`results\execution_board\execution-board-review-20260607-163834.json` now
matches that fresh evidence: `violation_count=0`, `submitted_order_count=0`,
`warning_count=2`, and the next-hour policy keeps sells independent, profit
taking separate from new buys, and new buys limited to controlled dip/support
setups with no green-spike chase language.

Fresh proof:

- Focused BOARD/loss-review tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_execution_board.py tests/test_loss_review_evidence.py -q`
  -> `16 passed`.
- Focused compact-context tests:
  `uv run --no-sync --with pytest python -m pytest tests/test_automation_context_snapshot.py -q -k "loss_review or execution_board or board_review"`
  -> `13 passed, 60 deselected`.
- Process review:
  `results\process_reviews\process-review-20260607-164046.json`,
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

## 62. n8n Overnight Preview Carries Source-Quality Context

The n8n `overnight_plan_compact_preview` wrapper now proves the source-quality
contract that the overnight automation relies on. Before this fix, the job ran
`research source-quality-review`, then invoked `alpaca plan-overnight` with
`--no-research-context`, so the dashboard preview could not verify
`research_context.watchlists.source_quality`.

Current behavior keeps the wrapper bounded and no-submit: `--no-write-latest`,
`--no-agent-ledger`, `--full-graph-tickers 0`, `--time-budget-minutes 0`,
`--top-provider-bundle-count 0`, `submit_capable=false`, and no
`--submit-actions`. It now passes
`--source-quality-review-path results/source_quality/latest.json` plus
`--source-quality-ordering` and leaves research context enabled.

Real proof:

- `python -m tradingagents.orchestration.n8n_runner --run-job overnight_plan_compact_preview --json`
  returned `status=ok`, `submit_capable=false`, and wrote
  `results\overnight_plans\n8n\overnight-plan-20260607-231000-000000.json`.
- The preview packet reports `analysis_only=true`, `submitted=[]`, 40 ranked
  candidates, top `XOM`, 14 research-context packets, and provider bundles
  disabled.
- `research_context.watchlists.source_quality` reports `status=available`,
  `source_quality_ordering_enabled=true`, 250 reviewed sources, 25 stale
  sources downranked, 0 stale needing refresh, and 0 missing/invalid.
- n8n job discovery still reports 24 jobs and `submit_capable_count=0`.
- Focused tests: n8n/provider/source-quality suite -> 85 passed; Alpaca
  overnight CLI slice -> 19 passed.
- JSON allowlist parse passed; targeted Ruff over n8n policy/tests passed.
- Process review
  `results\process_reviews\process-review-20260607-231502.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, Agent Intelligence Ledger test isolation repair, 2026-06-07
19:15 UTC:

Claude's submit-path hardening response is prepared for future agents and
SAFE-01 remains fail-closed: local `config/risk_envelope.yaml` loads as
`autonomous_with_caps` with account max `$250`, per-name `$50`, no optional
hard-ceiling/rate-limit knobs armed, and `issues=[]`. Live control is not
frozen, but its dead-man is expired at `2026-06-04T19:57:06+00:00`.

The latest full-suite verification found and fixed a second Agent Intelligence
Ledger shared-state leak. `alpaca plan-overnight` tests were invoking the
production default ledger path, so full pytest appended 23 overnight forecasts
to `results/agent_intelligence/ledger.jsonl` and left
`results/agent_intelligence/summary.json` stale. The test runner in
`tests/test_alpaca_cli.py` now auto-adds `--no-agent-ledger` only for
test-local `alpaca plan-overnight` invocations that do not explicitly pass an
agent-ledger flag. The plan-overnight ledger write path is still covered with a
temp `--agent-ledger-path`.

Fresh proof:

- `research agent-ledger-summary --json-output` repaired production summary to
  `forecast_count=4582`, matching 4,582 ledger records.
- `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py -q
  -k "plan_overnight"` -> `12 passed, 83 deselected`, with production ledger
  still matched after the slice.
- Focused CLI/self-heal regressions -> `2 passed` and
  `5 passed, 21 deselected`.
- Targeted Ruff over `tests/test_alpaca_cli.py`,
  `tests/test_self_heal_handoff.py`, and
  `tradingagents/orchestration/self_heal.py` passed.
- Full pytest -> `1067 passed, 1 skipped, 9 warnings, 75 subtests passed`.
- Post-suite ledger proof: `forecast_count=4582`, `ledger_record_count=4582`,
  `matches=true`, `agent_count=10`.
- Refreshed compact context has only the intentional hourly/BOARD/loss-review
  drilldowns; no `agent_intelligence_summary` schema flag.
- Process review
  `results\process_reviews\process-review-20260607-191506.json` reports
  `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Safety boundary held: no orders, no emails, no dead-man refresh, no credential
changes, no automation status changes, no staging/commit, and no live-authority
changes.

Tail pointer, overnight verifier source-quality/provider-bundle guard,
2026-06-07 23:48 UTC:

`alpaca verify-overnight-system` now explicitly checks source-quality context
and top-provider-bundle coverage. Real proof
`results\overnight_system_verification\overnight-system-verification-20260607-184746.json`
is `overall_status=pass`, with no failed/warned checks. Source quality passed
with 250 reviewed sources, 21 stale, 13 stale-downranked, 0 stale needing
refresh, 0 missing/invalid, and 0 unreadable. Top bundle coverage passed for
`XOM`, `CVX`, and `ADBE` through
`results\_context\source-routing-compact.json`, with `missing_symbols=[]`.
Focused verifier/provider tests passed (`9 passed, 167 deselected`), and
targeted Ruff over `cli/main.py` plus `tests/test_alpaca_cli.py` passed.

Tail pointer, self-heal timeliness and optional transcript connector noise,
2026-06-08 00:16 UTC:

The safe-plane self-heal loop was exercised with the real command path:
`research self-heal-plan --execute-safe --safe-reverify-minutes 0 --json-output`
wrote `results\self_heal\plans\self-heal-plan-20260608-000706.json` and
executed one allowlisted safe action. That action ran night-shift patrol and
then automation-health audit, with `verified_count=1`, `verify_failed_count=0`,
`can_submit_orders=false`, and `execution_authority=none`.

Latest automation health
`results\automation_health\automation-health-audit-20260608-000705.json`
reports 14/14 automations OK, zero submitted orders, no stale/late/duplicate
jobs, and self-heal follow-up `timely=true` with 74 second lag.

Latest TSM loss-review evidence and BOARD review remain analysis-only:
`results\loss_review_evidence\source-evidence-source-evidence-c263d6f15eca4685ab471abb8cf276ed.json`
and `results\execution_board\execution-board-review-20260608-001151.json`.
They show 0 submitted orders, 0 hard violations, blocker delta `13 -> 1`, and
only the closed/non-tradeable market-session blocker.

`scripts/automation_context_snapshot.py` now keeps `youtube_transcript` MCP
timeouts visible in connector health while treating them as quiet optional
endpoint noise in the top-level compact flags once the provider orchestrator
falls through to an earnings-transcript gap packet. This preserves source
telemetry without making the morning first-screen context chase optional
transcript failures.

Verification: connector-health focused context tests passed (`2 passed, 77
deselected`), targeted Ruff passed, and process review
`results\process_reviews\process-review-20260608-001637.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

Tail pointer, real walk-forward cohort says tighten, 2026-06-08 00:26 UTC:

`research walk-forward-refresh-overnight-cohort --json-output` wrote
`results\research_batches\walk_forward_cohort_refresh_20260608-002404_h3.json`
from 12 mature overnight packets; two `2026-06-08` packets were skipped as not
mature. The refresh collected 105 later-return rows, generated 140 replay
fixture rows, and stayed analysis-only.

The latest real replay does not justify increasing live influence:
deterministic sleeve directional accuracy `0.3143`, false-positive rate
`0.2786`, and average action-relative return `-1.6585`; TradingAgents advisory
overlay scored only 8 rows, below sample floor, with directional accuracy
`0.3750`, false-positive rate `0.6250`, and action-relative return `-1.3762`.

`research overnight-calibration-guard --json-output` wrote
`results\overnight_calibration\overnight-calibration-guard-20260608-002515.json`
with `guard_decision=tighten` and `can_increase_live_influence=false`. The
live influence policy stays `tighten_or_hold_reduced_weight`: controlled
dip/support reclaim only, no green-spike chase, independent buys and sells,
fresh/downrank-aware sources, and anti-crowding confirmation.

Focused walk-forward/calibration/context tests passed (`18 passed, 80
deselected`), and process review
`results\process_reviews\process-review-20260608-002613.json` reports
`unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
