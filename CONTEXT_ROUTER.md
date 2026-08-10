# TradingAgents Context Router

> **Current canonical root (2026-08-10):**
> `/Users/corbinfloyd/Documents/TradingAgents`. Begin with `START_HERE.md`, then
> refresh compact context using
> `.venv/bin/python scripts/automation_context_snapshot.py --write`. Older
> Windows commands and dated status notes below are retained as operational
> history; current Mac runtime evidence is authoritative for present state.

Purpose: give Codex a compact starting point for recurring TradingAgents/Alpaca
work without rereading the whole repo, old packets, or long handoff docs.

## Current Build Scoreboard

Plain English: the bot is being upgraded into a research-heavy but safety-first
trading system. The research side can read, crawl, summarize, simulate, and
write evidence. The trading side can only spend money after deterministic checks
and live gates pass. Current local live posture is SAFE-01 fail-closed:
`config/risk_envelope.yaml` is `autonomous_with_caps` with the $250 account cap
and $50 per-name cap re-armed, and the live-control dead-man is lapsed until the
operator intentionally refreshes it. The repo still supports
`autonomous_uncapped` as an explicit optional mode, where broker buying power,
promotion, reconciliation, stock-only, limit-only, live-control, loss-review,
and optional hard-ceiling/rate-limit gates still apply. The repo is wired for the June 4, 2026
intraday-margin regime: old PDT day-count, old `$25k` PDT minimum, PDT
designation, and old day-trading-buying-power logic are not bot blockers anymore;
broker buying power, account status, intraday-margin context, and fresh
validation still matter.

| Status | Meaning |
| --- | --- |
| Done | Foundation docs, no-secret capability audit, connected-tool baseline, clearer ELI5-style emails, self-heal/proposal tone, spent-today accounting, alert throttling, risk posture, static live-submit guard, research packet schemas/writers, current submit-path packet coverage, official SEC/FRED/BLS/BEA/EIA/Treasury evidence adapters plus cache helper, supplemental EODHD/Finnhub/Massive/FMP/Google News RSS/Marketaux/ScrapingBee/NewsAPI/Tiingo/Alpaca News evidence adapters, strategy methodology cards, source quality/failure policy, official release-calendar event-risk context, June 4 intraday-margin/PDT-reform market-structure context, Agent Intelligence Ledger for scoreable TradingAgents role forecasts plus earned influence weights, replay/ablation plan packet for deterministic baseline versus advisory overlays, decision-quality point-in-time audit/calibration packet, fixed-as-of walk-forward replay harness CLI, expanded read-only social attention watchlists, Reddit market-sentiment watchlist and compact schema, provider fallback policy for depleted APIs, shared connector retry/backoff/circuit telemetry for all research/data HTTP adapters, ticker-level broad provider bundle CLI with proven official_cache, yfinance quote context, SEC EDGAR fundamentals, reddit_watchlist routes, and allowlisted Crawlee `crawler_research`, overnight research-context packet attachment, premarket research-context carry-forward, crawler/social packet policy plus Crawlee packet runner and runtime doctor, installed Crawlee/Playwright/greenlet browser runtime with successful read-only packet proof, pullback-support dry-run/paper-submit loop, AlphaInsider popular-strategy paper watch plan plus paper-shadow emulation using leftover paper budget after the $30,000 tournament reserve, promotion evidence scaffold and stronger live gate, sleeve preregistration store, fail-closed SAFE-01 local live posture with caps re-armed, autonomous uncapped live-budget mode available only by deliberate config, uncapped live-budget buying-power fix, controlled-dip ranking plus sell-the-spike profit-taking in current-aggressive, loss-review instead of automatic losing live exits, live-gate daily-loss/drawdown circuit breakers for new buys, BOARD underperformer-review live-buy pause with structured loss-exit evidence checks, stable tiny-live live-submit order IDs, broker duplicate-response classification plus existing-order lookup and intended-vs-existing comparison for tiny-live idempotency conflicts, latest-packet live order reconciliation, tiny-live safety helper scaffolds plus hourly submit guard wiring, hard model spend/token/call caps, explicit Windows-local/Mac-Ollama/intelligent-judgment/deterministic-helper model lanes, Mac 32 GB DeepSeek helper lane, graph memory, prompt registry, clean-room market mirror with PDT-reform crowd actors, MiroFish final handoff normalized into advisory branches/tasks/filters plus ledger forecasts, Deep Research report 33 macro-first overlay for MiroFish/overnight context, `research automation-orchestration-plan`, model routing/telemetry rollups with usefulness/outcome labels and upgrade recommendations, daily-report model telemetry section, safe-plane PA self-heal plan/executor with dedupe, forbidden-effect escalation, and automation-health timeliness SLA checks, captured ChatGPT Deep Research technical due-diligence artifact plus protocol packet, Plugin Eval-style process review, token-efficient context bundle, repo-local token context hooks with compact goal/subagent metadata and warning-only `PreToolUse` raw-context guidance, n8n status-dashboard POC runner plus job discovery, automation-health, self-heal plan/execute-safe jobs, and native n8n Evaluation Trigger workflow plus 23-column Data Table actual-output sync, real simulation audit runner, premarket blocker/safety-lock split, and overnight-system verification that now warns when the original graph is fallback-only. |
| In progress | Market-open observation, optional external account/tool activation checks, plus outcome labeling as the new Google-routed overnight forecasts resolve. The overnight automation explicitly requests Google for the original graph; Windows local Ollama is now a healthy cheap helper, while Mac DeepSeek is optional/degraded until the Mac host/Tailscale/Ollama endpoint responds. MiroFish final advisory handoff `report_1e3059f732b1` is available and remains advisory-only. |
| Blocked | No repo-code blocker. OpenAI is blank in this shell, but Google and OpenRouter credentials are present; the Google overnight graph completed successfully. Mac helper is currently host-unreachable: both `http://macbook-pro.tail37edd7.ts.net:11434/api/tags` and `ssh macbook-codex` timed out. This is not a morning blocker because deterministic helpers, Windows local Ollama, Google graph, and Codex judgment remain available. |
| Next gate | Use the passed full Google overnight packet for morning context, run fresh quote/news/account validation at open, keep TSM loss-review as BOARD/manual review only, label outcomes as forecasts resolve, and let Mac rejoin only after Tailscale/SSH/Ollama tags respond. |
| Current nearest checks | Latest overnight packet is `results\overnight_plans\overnight-plan-20260607-101157-000000.json`: trade date `2026-06-08`, top candidate `XOM`, 40 ranked candidates, 3/3 original TradingAgents graph successes on explicit Google compact routing, 37 fallback-ranked tickers, 14 prior-feed packets, 0 blocked research-context packets, 0 graph failures, and 0 submitted orders. Latest verifier is `results\overnight_system_verification\overnight-system-verification-20260607-094459.json`, `overall_status=pass`, 16/16 checks passed, no warnings/failures, `execution_authority=none`, and `can_submit_orders=false`. Latest premarket brief is `results\premarket_briefs\latest.json`, top `XOM`, 54 source packets, no blockers/stale warnings. Latest preopen validation is `results\preopen_validation\latest.json`, `pass_with_warnings` only because the market is closed and live-control is intentionally expired; it read 0 open live orders, 0 open paper orders, 4 live positions, 14 paper positions, and live buying power `$86.38`. Latest source quality is `results\source_quality\source-quality-review-20260607-111430.json`: 250 sources, 224 fresh, 26 stale, 18 stale-downranked, 31 blocked gap packets, 0 missing/invalid, `stale_needs_refresh_count=0`. Latest model telemetry is `results\model_telemetry_reports\model-telemetry-report-20260607-093720-965799.json`: deterministic success, Windows local success, Mac blocked/unreachable, Codex fallback, spend `$0.0000`. Latest BOARD/loss-review proof is `results\execution_board\execution-board-review-20260607-082625.json` plus `results\loss_review_evidence\source-evidence-source-evidence-a2b1faa05e0a4ee5bb6b50e99c175f8d.json`: 0 hard violations, 0 submitted orders, TSM evidence blocker delta `13 -> 1`, only remaining blocker is closed/non-tradeable session, and the loss-exit candidate is BOARD input only. Latest process review is `results\process_reviews\latest.json`, `unchecked_step_count=0`. |
| Current verification refresh | Compact context refreshed after the Claude-handoff/wake-verification checkpoint; latest flags only open the intentional hourly notify, hourly BOARD review, execution BOARD review, and loss-review evidence review routes. Fresh proof: overnight verifier passed 16/16 checks, automation-health passed 14/14 automations including wake verification, process review has `unchecked_step_count=0`, and no orders/emails/dead-man refreshes/automation status changes were performed. |
| Historical checks (superseded) | 2026-06-05/06 snapshot retained for provenance only; current agents should use `Current nearest checks` above first. Latest full Google overnight packet then was `results\overnight_plans\overnight-plan-20260605-040719-000000.json`, top five `KO`, `IBM`, `HD`, `CRM`, `QCOM`, submitted 0 orders, `full_graph_attempt_count=3`, `full_graph_success_count=3`, `fallback_count=32`, `graph_failure_count=0`, `research_context_packet_count=13`, creator workflow artifacts for `KO`, `IBM`, and `HD`. Latest provider-route proof bundles then: `results\research_evidence\source-evidence-source-evidence-26dedb9a401f4268b66e104f020a20d9.json` for `KO`, `results\research_evidence\source-evidence-source-evidence-6097ce36839744abb71f34fdb4d1186f.json` for `IBM`, and `results\research_evidence\source-evidence-source-evidence-0f438c6a9c8f47e2bbf124831c59b53e.json` for `HD`; each stayed analysis-only and now requests first-class transcript, short-interest, and options evidence. Earnings transcripts now have an optional FMP transcript route before the explicit gap packet; real proof summary `results\research_evidence\source-evidence-source-evidence-6cdfc969960f48a0857db7ae4a9a1571.json` shows current machine fallback to `earnings_transcripts_gap`, FMP blocked/no transcript text, and `limited_source_packet_count=0`. Options/IV/flow has supplemental low-authority `yfinance_options` evidence before the gap packet; real proof packets: `results\research_evidence\source-evidence-source-evidence-d41f4b74d07c4c54afa9a7e60474f806.json` for `KO` and `results\research_evidence\source-evidence-source-evidence-72716c8795e54d7d9b30b30202fb34a8.json` for `QQQ`, both analysis-only with `execution_authority=none`. Short interest has supplemental low-authority `yfinance_short_interest` evidence before the gap packet; real proof packet `results\research_evidence\source-evidence-source-evidence-4a99920e4758414483244e05bf049368.json` for `KO` wrote Yahoo short-interest metadata, while `QQQ` correctly fell through to `short_interest_gap` at `results\research_evidence\source-evidence-source-evidence-daa193ee538a4df5a24fc8921ef8247d.json` because Yahoo exposed no actual short-interest fields. Latest premarket brief then: `results\premarket_briefs\premarket-brief-20260605-040926-000000.json`, top symbol `KO`, no stale warnings, no unresolved blockers. Latest MiroFish status: `results\mirofish_handoff\latest.json`, action `suppress`, gates `broker_friction`, `macro_override`, `attribution_error`, execution authority `none`. Latest overnight-system verification then: `results\overnight_system_verification\overnight-system-verification-20260604-231510.json`, `overall_status=pass`. Latest source-quality review then: `results\source_quality\source-quality-review-20260605-063725.json`, `source_count=250`, `stale_count=73`, `stale_safe_count=73`, `stale_needs_refresh_count=0`, `missing_or_invalid_count=0`. Latest compact context then opened the hourly `loss-review`, `results\execution_board\latest.json`, and `results\loss_review_evidence\latest.json`. `results\_context\source-routing.json` reported `gap_count=0`, `coverage_count=3`, and coverage categories `earnings_transcripts`, `options_iv_flow`, and `short_interest`. n8n job discovery then had 21 allowlisted jobs, `submit_capable_count=0`. Process review then: `results\process_reviews\process-review-20260606-235921.json`, `unchecked_step_count=0`. Full gate then passed: full pytest `952 passed, 1 skipped, 9 warnings, 75 subtests passed`; repo Ruff clean; mypy clean across 57 broker/policy/execution/dataflow files. |

> Current 2026-06-07 22:44 UTC override: Claude submit-path review is verified
> and prepared for future agents. Branch is
> `wip/submit-path-hardening-2026-06-05` at unsigned commit `3970998`; that
> commit contains only `tradingagents/policy/order_rate_limit.py` and
> `tests/test_order_rate_limit.py`. Local SAFE-01 remains fail-closed:
> `config/risk_envelope.yaml` is ignored/untracked and loads as
> `live_budget_mode=autonomous_with_caps`, account cap `$250.00`, per-name cap
> `$50.00`, optional hard-ceiling/rate-limit knobs unset, and `issues=[]`.
> `results\policy\live_control.json` is not frozen but the dead-man is still
> expired at `2026-06-04T19:57:06+00:00`; do not refresh it without explicit
> operator approval. Shared submit-path hardening edits remain dirty and must be
> reviewed/staged hunk-by-hunk before any commit. Fresh submit-path proof:
> `uv run --no-sync --with pytest python -m pytest tests/test_order_rate_limit.py tests/test_live_gate.py tests/test_execution_safety.py tests/test_alpaca_execution.py tests/test_alpaca_cli.py -q`
> -> `172 passed`; targeted Ruff over the submit-path surface passed; process
> review `results\process_reviews\process-review-20260607-225937.json` has
> `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
> Wake verification is now evidence-backed: real packet
> `results\control_plane_patrol\wake-verification-patrol-20260607-225844.json`
> wrote with `analysis_only=true`, `can_submit_orders=false`, 14 automation
> configs observed, and 0 submitted orders.
> Automation health
> `results\automation_health\automation-health-audit-20260607-225910.json`
> reports 14/14 automations OK, zero submitted orders, zero issues, and self-heal
> timely at 61 seconds. n8n runner discovery still reports 24 allowlisted jobs
> and `submit_capable_count=0`.
> Safety boundary held: no orders, emails, dead-man refreshes, credential
> changes, automation status changes, staging, commits, or live-authority
> changes.

> Current 2026-06-07 23:15 UTC override: n8n overnight preview now proves the
> same source-quality context contract it refreshes. The allowlisted
> `overnight_plan_compact_preview` job still runs with `submit_capable=false`,
> `--no-write-latest`, `--no-agent-ledger`, zero full-graph tickers, zero model
> time budget, and `--top-provider-bundle-count 0`, but no longer disables
> research context. Real proof:
> `python -m tradingagents.orchestration.n8n_runner --run-job overnight_plan_compact_preview --json`
> wrote `results\overnight_plans\n8n\overnight-plan-20260607-231000-000000.json`
> with `analysis_only=true`, `submitted=[]`, 40 ranked candidates, top `XOM`,
> 14 research-context packets, and source-quality watchlist status `available`.
> That packet has `source_quality_ordering_enabled=true`, 250 sources reviewed,
> 25 stale sources downranked, 0 stale needing refresh, 0 missing/invalid, and
> provider bundles disabled. n8n discovery still reports 24 jobs and
> `submit_capable_count=0`. Focused proof: n8n/provider/source-quality tests
> `85 passed`, Alpaca overnight CLI slice `19 passed`, JSON allowlist parse
> passed, targeted Ruff passed, process review
> `results\process_reviews\process-review-20260607-231502.json` has
> `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

> Current 2026-06-07 23:48 UTC override: overnight verification now checks the
> source-quality and top-provider-bundle contracts directly, not just the core
> overnight packet shape. `alpaca verify-overnight-system --json-output` wrote
> `results\overnight_system_verification\overnight-system-verification-20260607-184746.json`
> with `overall_status=pass`, no failed/warned checks, `execution_authority=none`,
> and `can_submit_orders=false`. New proof checks:
> `overnight_source_quality_context=pass` with 250 reviewed sources, 21 stale
> sources, 13 stale-downranked, 0 stale needing refresh, 0 missing/invalid, and
> 0 unreadable; `overnight_top_provider_bundles=pass` with coverage for top
> symbols `XOM`, `CVX`, and `ADBE` via
> `results\_context\source-routing-compact.json`, `recent_provider_bundle_count=7`,
> and `missing_symbols=[]`. Focused verification:
> `uv run --no-sync --with pytest python -m pytest tests/test_alpaca_cli.py tests/test_automation_context_snapshot.py -q -k "verify_overnight or provider_bundle"`
> -> `9 passed, 167 deselected`; targeted Ruff over `cli/main.py` and
> `tests/test_alpaca_cli.py` passed. Safety boundary held: no orders, emails,
> dead-man refreshes, credential changes, automation status changes, staging, or
> commits.

> Current 2026-06-08 00:16 UTC override: safe-plane self-heal timeliness and
> connector-health compaction were refreshed after the TSM loss-review evidence
> run. `research self-heal-plan --execute-safe --safe-reverify-minutes 0
> --json-output` wrote
> `results\self_heal\plans\self-heal-plan-20260608-000706.json`; it executed
> exactly one allowlisted safe action, running night-shift patrol and then
> automation-health audit, with `executed_count=1`, `verified_count=1`,
> `verify_failed_count=0`, `can_submit_orders=false`, and
> `execution_authority=none`. Latest automation health
> `results\automation_health\automation-health-audit-20260608-000705.json`
> reports 14/14 automations OK, no missing/partial/late/duplicate/stale/warning
> jobs, 0 submitted orders, and self-heal timely with 74 second lag. Fresh
> loss-review evidence
> `results\loss_review_evidence\source-evidence-source-evidence-c263d6f15eca4685ab471abb8cf276ed.json`
> and BOARD review
> `results\execution_board\execution-board-review-20260608-001151.json` remain
> analysis-only: 0 submitted orders, 0 hard violations, TSM evidence blocker
> delta `13 -> 1`, and the only remaining blocker is closed/non-tradeable
> session. Connector-health still records optional FMP missing key plus
> YouTube transcript timeout, but compact context now treats that transcript
> timeout as visible/quiet once the provider orchestrator falls through to the
> earnings-transcript gap packet; latest flags no longer open connector health.
> Verification: connector-health focused context tests `2 passed, 77
> deselected`, targeted Ruff passed, process review
> `results\process_reviews\process-review-20260608-001637.json` has
> `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

> Current 2026-06-08 00:26 UTC override: real overnight walk-forward cohort and
> calibration guard were refreshed. `research
> walk-forward-refresh-overnight-cohort --json-output` wrote
> `results\research_batches\walk_forward_cohort_refresh_20260608-002404_h3.json`
> from 12 mature overnight packets; 2 current `2026-06-08` packets were skipped
> as not mature. The run collected 105 later-return rows, generated 140 replay
> fixture rows, and stayed `analysis_only=true`, `can_submit_orders=false`,
> `execution_authority=none`. Metrics are weak: deterministic sleeve scored
> 140 rows with directional accuracy `0.3143` and average action-relative return
> `-1.6585`; TradingAgents advisory overlay scored only 8 rows, below sample
> floor, with directional accuracy `0.3750`, false-positive rate `0.6250`, and
> action-relative return `-1.3762`. `research overnight-calibration-guard
> --json-output` wrote
> `results\overnight_calibration\overnight-calibration-guard-20260608-002515.json`
> with `guard_decision=tighten`, `can_increase_live_influence=false`, and live
> influence policy `tighten_or_hold_reduced_weight`: buys require controlled
> dip/support reclaim, no green-spike chase, sell/buy independence, fresh source
> quality, and anti-crowding confirmation. `research outcome-labeling
> --json-output` refreshed model/mirror labels but forecasts remain unresolved.
> Focused proof:
> `uv run --no-sync --with pytest python -m pytest tests/test_replay_ablation_plan.py tests/test_overnight_calibration_guard.py tests/test_automation_context_snapshot.py -q -k "walk_forward or overnight_calibration or model_telemetry or source_routing or connector_health"`
> -> `18 passed, 80 deselected`; process review
> `results\process_reviews\process-review-20260608-002613.json` has
> `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

> Current 2026-06-07 20:02 UTC override: overnight prior-feed applied-state and
> dedupe proof is implemented and visible for the current canonical overnight
> packet without rerunning or downgrading the verified Google graph. Compact
> context now enriches legacy prior-feed pointers from the feed JSON itself:
> `results\_context\latest-summary.json` shows production packet
> `results\overnight_plans\overnight-plan-20260607-101157-000000.json`, top
> `XOM`, 3/3 full graph successes, `graph_failure_count=0`,
> `overnight_prior_feed_applied=true`, `overnight_prior_feed_dedupe_applied=true`,
> 14 input refs, 14 unique refs, 0 duplicates, and carry-forward scope covering
> source packet refs, provider fallbacks, watchlists, MiroFish, and methodology.
> The original no-latest/no-submit probe remains available at
> `results\overnight_plans\prior_dedupe_probe\overnight-plan-20260607-194517-000000.json`
> and prior feed
> `results\overnight_plans\prior_dedupe_probe\research_context\overnight-prior-feed-latest.json`
> with `analysis_only=true` and `execution_authority=none`.

> Current 2026-06-07 22:07 UTC override: provider-bundle summaries now expose
> route-gap counters, overnight-target relevance, and a working unlimited local
> YouTube transcript route before FMP/gap fallback. Real analysis-only bundles
> cover the current overnight top-three symbols `XOM`, `CVX`, and `ADBE`;
> compact source routing reports
> `recent_provider_target_symbols_missing_bundle=[]`,
> `recent_provider_target_symbols_with_missing_non_gap=[]`, and no
> `source_routing` drilldown flag. Current transcript proof packets include
> `results\research_evidence\youtube_transcript_probe\source-evidence-source-evidence-107cb2c1d5bf4cf9b6c71c1e3af1cd78.json`
> for `XOM` plus refreshed clean summary packets for `CVX` and `ADBE`:
> `results\research_evidence\source-evidence-source-evidence-43183b7d0f874a08bf384074a682e438.json`
> and
> `results\research_evidence\source-evidence-source-evidence-fd80a8881c8c4e309cff9f6855424eb3.json`.
> The latest calibration guard is
> `results\overnight_calibration\overnight-calibration-guard-20260607-220624.json`:
> `guard_decision=tighten`, new buys require controlled dip/support reclaim,
> green-spike chasing is rejected, sell/buy decisions remain independent, and
> bot-copycat/crowded-AI names require anti-crowding confirmation. The latest
> Agent Intelligence Ledger update has 4,582 forecasts, all pending, so agent
> influence weights stay neutral until enough forecasts resolve.

> Current 2026-06-07 22:24 UTC override: fresh no-submit readiness sweep passed
> after the ledger/calibration/source-routing refresh. Overnight verification
> `results\overnight_system_verification\overnight-system-verification-20260607-172054.json`
> is `overall_status=pass`, 16/16 checks passed, latest overnight packet top
> `XOM`, trade date `2026-06-08`, 3/3 original graph successes, 0 graph
> failures, and `submitted_count=0`. Source quality
> `results\source_quality\source-quality-review-20260607-222048.json` reviewed
> 250 sources with 205 fresh, 45 stale, 45 stale-safe, 25 stale-downranked,
> 38 blocked gap packets, 0 unreadable, 0 missing/invalid, and
> `stale_needs_refresh_count=0`. Automation health
> `results\automation_health\automation-health-audit-20260607-222049.json`
> reports 13/13 automations OK, 0 missing/partial/late/stale/warnings,
> self-heal timely at 30 seconds, and 0 submitted orders. n8n job discovery
> reports 24 allowlisted jobs and `submit_capable_count=0`. Process review
> `results\process_reviews\process-review-20260607-222354.json` has
> `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.

> Current 2026-06-07 18:17 UTC override: stale preopen/loss-review evidence is
> now handled by the safe self-heal plane. The real safe-plan packet
> `results\self_heal\plans\self-heal-plan-20260607-181507.json` had no stale
> safe fixes left and skipped only order-adjacent BOARD escalations. Fresh
> preopen proof is
> `results\preopen_validation\preopen-validation-20260607-181534.json`;
> fresh TSM loss-review proof is
> `results\loss_review_evidence\source-evidence-source-evidence-e23335b8bedd4bf6a91277c8a355aeda.json`;
> fresh BOARD proof is
> `results\execution_board\execution-board-review-20260607-181725.json`;
> automation health is
> `results\automation_health\automation-health-audit-20260607-181654.json`;
> process review is
> `results\process_reviews\process-review-20260607-183102.json`.
> Compact flags are intentional hourly notify/BOARD and loss-review review
> routes only. No orders, emails, live-control refreshes, automation status
> changes, staging, commits, or live-authority changes occurred.
> Full pytest after this checkpoint passed: 1067 passed, 1 skipped, 9 warnings,
> 75 subtests passed.

> Current 2026-06-07 14:38 UTC override: use the newest verified overnight
> packet first:
> `results\overnight_plans\overnight-plan-20260607-101157-000000.json`.
> It is analysis-only, trade date `2026-06-08`, top candidate `XOM`,
> submitted 0 orders,
> `full_graph_attempt_count=3`, `full_graph_success_count=3`,
> `graph_failure_count=0`, `fallback_count=37`, 14 research-context packets,
> and `graph_config.analyst_concurrency_limit=1`. The verifier passes at
> `results\overnight_system_verification\overnight-system-verification-20260607-094459.json`
> with `overall_status=pass`, 16/16 checks passed, no warnings/failures, and
> `overnight_packet_trade_date` expected/actual `2026-06-08`; the fresh
> premarket brief is `results\premarket_briefs\latest.json` with top symbol
> `XOM`, 54 source packets, no stale warnings, and no unresolved blockers.
> Fresh preopen validation is
> `results\preopen_validation\latest.json`;
> it is `pass_with_warnings` only because the market is closed and the
> live-control dead-man is intentionally expired.
> Current helper routing: Windows local Ollama is healthy with
> `tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest`; Mac
> `deepseek-r1:14b` is optional/degraded because both Ollama tags and SSH to
> `macbook-codex` time out. Do not wait on Mac for morning readiness.
> Root cause of the earlier overnight failure was a compact-profile LangGraph
> `RemoveMessage` race. Current code now has two layers of protection:
> message cleanup deduplicates concrete message IDs and concurrent analyst
> branches start with an empty message scratchpad; compact overnight still uses
> sequential analyst execution until a market-hours run proves higher
> concurrency is worth re-enabling. Durable repair checkpoint:
> `reports\overnight_reliability\overnight-research-repair-20260607.md`.

> Current 2026-06-07 loss-review override: use the refreshed TSM evidence
> packet at
> `results\loss_review_evidence\source-evidence-source-evidence-2594f15673fe4fe5825f31325f00df88.json`.
> The loss-review bridge found the original local live-buy context from
> `results\hourly_supervisor\hourly-supervisor-20260601-170250-428127.json`,
> including client order id `ta-hourly-20260601-170250-1-tsm-buy`, entry reason,
> and 4 trading days of holding-period evidence. Blocker delta is now
> `13 -> 5` with `resolved_blocker_count=8` and
> `entry_context_found=true`. Remaining blockers are true BOARD/manual/session
> items: allowed loss-exit reason/source, current thesis status, loss-exit
> confidence, and market session not tradeable. n8n `loss_review_evidence`
> reports the same summary with `submit_capable=false`. Latest BOARD packet
> `results\execution_board\execution-board-review-20260607-015047.json`
> has zero hard violations, zero submitted orders, `new_buy_policy.state=caution`,
> and preserves independent sell/buy policy.

> Current 2026-06-05 override: the newest verified overnight catch-up packet is
> `results\overnight_plans\overnight-plan-20260605-101740-000000.json`, not the
> older pre-schedule packet. It completed after the missed 2:30 AM Central window
> with top five `KO`, `IBM`, `HD`, `CVX`, `XOM`, `full_graph_success_count=3`,
> `graph_failure_count=0`, and `submitted_count=0`. The latest hourly packet
> `results\hourly_supervisor\hourly-supervisor-20260605-115730-204920.json`
> is `decision=loss-review` with `actions=[]`, `issues=0`, and `submitted=0`;
> it did not sell TSM at a loss without BOARD/manual thesis-break evidence. The
> latest compact context now opens the hourly packet and
> `results\execution_board\latest.json` on `board_review` whenever the latest
> hourly packet is `loss-review`; this is review routing only, not order
> authority. Compact context also intentionally still flags
> `automation_health_audit` when controller evidence is incomplete; wake/sleep
> controllers now write analysis-only controller packets under
> `results\control_plane_patrol\`, and `tradingagents-night-shift-supervisor`
> writes patrol packets under `results\night_shift_patrol\`. Overnight planning
> itself is `ok`. For n8n, compact context now carries the evaluation dataset/sync
> proof, so open raw
> `results\n8n_evaluations\` packets only when the compact n8n summary flags
> missing actual-output columns, failed sync, row-count mismatch, or bad redaction.

## Latest Checkpoint

- 2026-06-07 loss-review entry-history bridge checkpoint: the current TSM
  loss-review evidence now attaches bounded prior-entry context instead of
  leaving "original buy thesis" and "holding period" as fake blockers. Real
  proof `research loss-review-evidence --json-output` wrote
  `results\loss_review_evidence\source-evidence-source-evidence-2594f15673fe4fe5825f31325f00df88.json`
  with `entry_context_found=true`, source
  `local_hourly_supervisor_history`, client order id
  `ta-hourly-20260601-170250-1-tsm-buy`, entry reason from the original TSM
  live buy packet, 4 trading days held, `resolved_blocker_count=8`, and
  `remaining_blocker_count=5`. It remains analysis-only:
  `review_allowed=false`, `can_submit_orders=false`,
  `execution_authority=none`, and `mark_loss_exit_allowed` stays forbidden.
  The real n8n wrapper `python -m tradingagents.orchestration.n8n_runner
  --run-job loss_review_evidence --json` returned `status=ok`,
  `submit_capable=false`, `entry_context_found=true`, and the same blocker
  counts. BOARD was refreshed at
  `results\execution_board\execution-board-review-20260607-015047.json` with
  zero hard violations, zero submitted orders, new buys in caution, no
  green-spike chase allowance, and sell/buy independence preserved. Compact
  context was refreshed; current flags remain the intended hourly/BOARD/
  loss-review review routes only.
- 2026-06-06 night-shift self-heal repair checkpoint: the safe-plane
  automation-health action now writes the missing analysis-only night-shift
  patrol evidence before rerunning the automation-health audit. Forced real
  proof `research self-heal-plan --execute-safe --safe-reverify-minutes 0
  --json-output` wrote
  `results\self_heal\plans\self-heal-plan-20260606-225530.json` with
  `executed_count=1`, `verified_count=1`, `verify_failed_count=0`,
  two allowlisted command results, `can_submit_orders=false`, and
  `execution_authority=none`. It wrote
  `results\night_shift_patrol\night-shift-patrol-20260606-225524.json`, then
  refreshed automation health at
  `results\automation_health\automation-health-audit-20260606-225529.json`.
  The latest audit has all 13 automations `ok`, `partial_count=0`,
  `submitted_order_count=0`, and night-shift
  `status_reason=night_shift_latest_due_covered_history_ramp_up` with
  `history_gap_count=1`; the latest due slot is covered while older history
  finishes filling in. Compact context no longer opens `automation_health`;
  current remaining flags are only BOARD/loss-review review routes. Fresh
  verification: focused self-heal/automation-health tests passed with
  `46 passed`, targeted Ruff passed, process review
  `results\process_reviews\process-review-20260606-225623.json` has
  `unchecked_step_count=0`, and compact context was refreshed.
- 2026-06-06 self-heal reverify checkpoint: persistent safe-plane signals are no
  longer suppressed forever by durable signature dedupe. `research
  self-heal-plan --execute-safe --safe-reverify-minutes 0 --json-output` forced
  a real reverify of the still-active `automation_health` signal, ran the
  allowlisted `automation-health-audit` command, and wrote
  `results\self_heal\plans\self-heal-plan-20260606-221514.json` with
  `executed_count=1`, `verified_count=1`, `verify_failed_count=0`,
  `can_submit_orders=false`, and `execution_authority=none`. The default SLA is
  15 minutes; immediate repeats still dedupe, while still-active safe issues
  after the SLA become `planned` with
  `reverify_reason=persistent_safe_autofix_after_sla`. Order-adjacent hourly and
  BOARD signals remain manual escalations, not auto-fixes. Fresh automation
  health still has only `tradingagents-night-shift-supervisor` partial at `3/6`
  observed patrols, with no submitted orders. Verification: focused
  self-heal/context tests passed, CLI packet-coverage regression passed, Ruff
  and `py_compile` passed, process review
  `results\process_reviews\process-review-20260606-222118.json` has
  `unchecked_step_count=0`, and full pytest passed with `937 passed, 1 skipped,
  9 warnings, 75 subtests passed`.
- 2026-06-06 loss-review evidence/n8n observer checkpoint: the latest hourly
  `loss-review` no longer leaves BOARD with only a blocker list or stale
  "missing evidence" noise. The analysis-only command
  `research loss-review-evidence --json-output` now records
  `remaining_blockers_before_refresh`, `resolved_blockers_by_refresh`, and the
  post-refresh `remaining_blockers`. Current real packet:
  `results\loss_review_evidence\latest.json`, symbol `TSM`,
  `hourly_decision=loss-review`, `review_allowed=false`,
  `remaining_blockers_before_refresh_count=13`,
  `resolved_blocker_count=3`, `remaining_blocker_count=10`,
  `next_action=manual_board_review_with_refreshed_evidence_required`,
  `analysis_only=true`, `can_submit_orders=false`, and
  `execution_authority=none`. The refreshed evidence resolved the source IDs,
  company-news, and earnings/guidance/filing blockers; remaining blockers are
  true BOARD judgment/session constraints such as thesis status, HOLD-vs-SELL
  reasoning, loss-exit confidence, and closed market session. Compact context
  exposes the same blocker deltas and flags only `board_review`; no
  automation-health/self-heal duplicate flag is open. n8n job discovery reports
  21 allowlisted jobs and `submit_capable_count=0`; real wrapper proof
  `python -m tradingagents.orchestration.n8n_runner --run-job
  loss_review_evidence --json` returned `status=ok`, `can_submit_orders=false`,
  `execution_authority=none`, `review_allowed=false`,
  `remaining_blockers_before_refresh_count=13`,
  `resolved_blocker_count=3`, `remaining_blocker_count=10`, and
  `source_path_count=7`. Follow-on hardening after this checkpoint fixed raw
  packet discovery so broad `hourly-supervisor-*.json` readers skip
  `.compact.json` sidecars and same-timestamp packets are ordered by file mtime,
  not fragile filename sort. Real compact-output audit after the fix wrote
  `results\token_efficiency\compact-output-audit-20260606-185316-147838.json`
  with four measured packet families, `can_submit_orders=false`, and
  `execution_authority=none`; the current daily-report packet family is simply
  missing in local results. Focused proof:
  `uv run --no-sync --with pytest python -m pytest
  tests/test_loss_review_evidence.py tests/test_automation_context_snapshot.py
  tests/test_n8n_runner_policy.py tests/test_alpaca_supervisor.py::test_packet_writers_keep_same_second_packets_unique
  tests/test_automation_health_audit.py -q` passed with 125 tests; submit-path
  regression `uv run --no-sync --with pytest python -m pytest
  tests/test_live_gate.py tests/test_execution_safety.py
  tests/test_alpaca_execution.py tests/test_order_rate_limit.py
  tests/test_alpaca_cli.py -q` passed with 160 tests; targeted Ruff passed.
  Full regression gate after the repair also passed: `uv run --no-sync --with
  pytest python -m pytest -q` -> 952 passed, 1 skipped, 9 warnings, 75 subtests;
  `uv run --no-sync --group static-analysis ruff check` -> clean; `uv run
  --no-sync --group static-analysis mypy tradingagents\brokers
  tradingagents\policy tradingagents\execution tradingagents\dataflows` -> no
  issues in 57 source files.
- 2026-06-06 overnight calibration guard checkpoint: real walk-forward cohort
  underperformance now has an explicit analysis-only guard instead of living only
  in prose. `research overnight-calibration-guard --json-output` writes
  `results\overnight_calibration\latest.json` and the latest n8n bridge proof
  wrote
  `results\overnight_calibration\overnight-calibration-guard-20260606-214537.json`.
  Current decision is `guard_decision=tighten`,
  `can_increase_live_influence=false`, `can_submit_orders=false`, and
  `execution_authority=none`. Morning bots should keep overnight research
  advisory, require controlled-dip/support/reclaim evidence before buy-side
  escalation, reject green-spike chase setups, and downrank crowded AI-bot/
  broker-friction ideas until independent flow or institutional confirmation
  appears. n8n now exposes `overnight_calibration_guard` as a
  `submit_capable=false` observer job, and the synced built-in evaluation
  dataset has 201 rows across 22 allowlisted jobs with row-count sync proof
  `results\n8n_evaluations\n8n-api-sync-20260607-022929-127780.json`.
- 2026-06-06 automation-health compact-output checkpoint:
  `research automation-health-audit --json-output --compact-json-output` now
  prints `compact_automation_health_audit_v1` while preserving the raw audit and
  Markdown packet. n8n `automation_health_audit` now calls the compact flag, and
  `python -m tradingagents.orchestration.n8n_runner --run-job
  automation_health_audit` returned parsed schema
  `compact_automation_health_audit_v1`, `submit_capable=false`,
  `submitted_order_count=0`, and only `tradingagents-night-shift-supervisor` as
  the attention/problem automation. Latest compact-output audit:
  `results\token_efficiency\compact-output-audit-20260606-154240-507832.json`,
  5 measured families, total `8729059 -> 9568` bytes, automation-health
  `14662 -> 1140` bytes (`92.22%` reduction), all
  `lossless_by_reference=true`. Focused n8n/compact tests passed with
  `48 passed`, and targeted Ruff passed.
- 2026-06-06 P1-10 analyst-concurrency checkpoint: compact and market-news
  overnight graph profiles now request `analyst_concurrency_limit=2`, while the
  default/full graph remains sequential unless explicitly overridden.
  `tradingagents\graph\setup.py` uses LangGraph `Send` fan-out with explicit
  batch joins, so independent analyst roles can overlap without giving the LLM
  graph any execution authority. Focused proof: analyst execution,
  graph routing/compile, env override, and overnight CLI graph-config tests
  passed with `38 passed`; targeted Ruff passed; direct `py_compile` over
  touched source and tests passed. Real no-latest probe
  `results\overnight_plans\concurrency_probe\overnight-plan-20260606-201918-000000.json`
  has `execution_authority=none`, `submitted_count=0`, graph profile `compact`,
  and `overnight_quality.graph_config.analyst_concurrency_limit=2`. Broad graph
  mypy still exposes pre-existing typed-frontier debt and is not used as this
  slice's gate.
- 2026-06-06 Claude submit-path handoff prep refresh: the current branch
  `wip/submit-path-hardening-2026-06-05` still contains unsigned standalone
  commit `3970998` with only `tradingagents/policy/order_rate_limit.py` and
  `tests/test_order_rate_limit.py`. The local fail-closed live envelope was
  rechecked with the current `(envelope, issues)` loader API:
  `live_budget_mode=autonomous_with_caps`, account max `$250`, per-name `$50`,
  optional hard ceiling/rate-limit knobs unset, and `issues=[]`. The live-control
  dead-man remains expired, so no live submit should happen without explicit
  operator refresh. Fresh focused proof:
  submit-path tests `160 passed`, submit-path Ruff passed, and process review
  `results\process_reviews\process-review-20260606-201150.json` has
  `unchecked_step_count=0` and `can_submit_orders=false`. Detailed handoff:
  `reports\handoff\CODEX_SUBMIT_PATH_HARDENING_HANDOFF_2026-06-05.md`.
- 2026-06-06 compact overnight-quality checkpoint: compact context now exposes
  the nested `overnight_quality` proof fields from the latest overnight packet,
  so morning bots can confirm readiness without opening the full raw JSON.
  `results\_context\latest-summary.json` now shows overnight
  `completion_status=complete`, `completion_reasons=["3 full graph run(s) completed"]`,
  `full_graph_attempt_count=3`, `full_graph_success_count=3`,
  `fallback_count=33`, `graph_failure_count=0`,
  `research_context_packet_count=13`, `research_context_blocked_count=0`,
  `overnight_model_route=explicit_google_overnight_graph`,
  `overnight_llm_provider=google`, quick model `gemini-2.5-flash-lite`, deep
  model `gemini-2.5-flash`, `submitted=0`, and `drilldown_required=false`.
  `results\_context\field-provenance.json` maps those compact fields back to
  `overnight_quality.*`, preserving the lossless-by-reference context contract.
  Focused proof: `uv run --no-sync --with pytest python -m pytest
  tests/test_automation_context_snapshot.py -q` passed with 33 tests, targeted
  Ruff passed, and `python scripts\automation_context_snapshot.py --write`
  refreshed the real compact context.
- 2026-06-06 automation-health Saturday/no-market checkpoint: automation health
  no longer treats Saturday 02:30 local overnight-planning as a missed run,
  because that slot is not a useful U.S. regular-session prep point; Sunday and
  Monday-Friday overnight due checks still count. `tradingagents-overnight-planning`
  was also reactivated after app/disk state showed it was paused. Real observer
  refreshes wrote `results\night_shift_patrol\night-shift-patrol-20260606-185609.json`,
  `results\control_plane_patrol\wake-controller-patrol-20260606-190119.json`,
  `results\control_plane_patrol\sleep-controller-patrol-20260606-190121.json`,
  `results\self_heal\self-heal-handoff-20260606-191759.json`, and
  `results\self_heal\plans\self-heal-plan-20260606-191838.json`. Fresh
  automation health
  `results\automation_health\automation-health-audit-20260606-192741.json`
  reports wake/sleep/self-heal/overnight `ok`, overnight `config_status=ACTIVE`,
  self-heal follow-up lag `37s`, `missing_count=0`, `stale_count=0`,
  `late_count=0`, `timeliness_issue_count=0`, and `submitted_order_count=0`;
  only `tradingagents-night-shift-supervisor` remains `partial` while its
  six-window patrol history fills in. Fresh overnight verifier
  `results\overnight_system_verification\overnight-system-verification-20260606-141132.json`
  is `overall_status=pass` and skips only simulated pre-open validation with
  `validation_skipped=true` and `skip_reason=saturday_no_regular_market_morning`;
  Sunday/Monday-Friday overnight checks remain active. Focused verifier/health/
  context proof passed with 59 tests and targeted Ruff passed.
- 2026-06-06 current BOARD/Saturday overnight-evidence refresh: the stale June 5
  BOARD packet was replaced with
  `results\execution_board\execution-board-review-20260606-193832.json`, which
  includes the latest hourly loss-review packet
  `results\hourly_supervisor\hourly-supervisor-20260606-193752-094749.json`.
  That hourly dry-run also proves Saturday no-market handling in the real
  supervisor path: `evidence.overnight_plan.status=not_required`,
  `validation_skipped=true`, and
  `skip_reason=saturday_no_regular_market_morning` while no orders submitted.
  BOARD remains `analysis_only=true`, `can_submit_orders=false`,
  `submitted_order_count=0`, `violation_count=0`, `warning_count=1`, and
  `new_buy_state=caution`; compact context still flags `board_review` because
  live unrealized P/L is negative and loss exits require thesis-break evidence.
  Compact context now exposes the useful BOARD/self-heal fields directly:
  `board_hard_issue=false`, `latest_packet_decision=loss-review`,
  `latest_packet_needs_review=true`, `negative_live_pl_packets=24`,
  `warning_types=["negative_live_unrealized_pl"]`, independent buy/sell policy
  text, and self-heal signal classifications showing automation-health as
  `safe_autofix` while hourly/BOARD review stay `escalate_order_adjacent`.
  The same live-data dry-run proved the shortened loss-review email body:
  24 lines, `email_clarity_eval` score `100`, no issues/warnings, and no
  pasted blocker checklist in the inbox; full missing-evidence details remain
  in the hourly packet.
  Latest process review:
  `results\process_reviews\process-review-20260606-195734.json`,
  `unchecked_step_count=0`. Focused Saturday-overnight validation proof passed
  with 3 tests, the real hourly dry-run wrote `submitted=[]`, refreshed BOARD
  wrote zero hard violations, compact context was refreshed, and targeted Ruff
  passed.
- 2026-06-06 blocked-provider quota checkpoint: ticker provider bundles now log
  blocked limited/paid providers as attempts without letting them consume the
  usable evidence quota; connected-MCP/broker diagnostic blocked packets and
  explicit local research-gap packets still count when the blocked status is the
  evidence. Real KO market-news proof:
  `results\research_evidence\source-evidence-source-evidence-b868493be1c74f63bce96e877d13f19c.json`
  records blocked `tiingo` as an attempt, but actual packet counts are
  `google_news_rss`, `official_cache`, and `reddit_watchlist`, with
  `limited_source_packet_count=0`. Fresh source-quality review:
  `results\source_quality\source-quality-review-20260606-195554.json`,
  `source_count=250`, `stale_count=174`, `blocked_count=69`,
  `stale_needs_refresh_count=0`. Provider/source-quality tests passed with 37
  tests and targeted Ruff passed.
- 2026-06-05 compact BOARD drilldown checkpoint: compact context no longer
  treats `decision=loss-review` as a quiet no-action packet. Hourly summaries
  with `loss-review` now set `drilldown_required=true` and
  `drilldown_reasons=["board_review"]`; execution-board summaries now expose
  `latest_packet_decision` plus `latest_packet_needs_review`, and stay drilldown
  required when the latest reviewed packet is a loss-review. Real proof:
  `results\hourly_supervisor\hourly-supervisor-20260605-115730-204920.json`,
  `results\execution_board\execution-board-review-20260605-152357.json`, and
  `results\_context\latest-flags.json`, which opens both the hourly packet and
  `results\execution_board\latest.json` for `board_review`. This is
  analysis/review routing only: `execution_board_review` remains
  `analysis_only=true`, `can_submit_orders=false`, and submitted order count 0.
- 2026-06-05 automation-health/self-heal checkpoint: overnight research had not
  completed in the scheduled 2:30 AM Central window, and the health audit was
  incorrectly suppressing the expected run because it treated overnight planning
  as wake-controller-dependent. `tradingagents-overnight-planning` is now
  due-aligned with its own settled due window, so pre-due memories no longer mask
  a missed overnight run. Regression proof:
  `tests/test_automation_health_audit.py::test_overnight_planner_due_is_not_suppressed_by_daytime_wake_sleep_window`.
  Real catch-up proof:
  `results\overnight_plans\overnight-plan-20260605-101740-000000.json`,
  premarket brief `results\premarket_briefs\premarket-brief-20260605-101901-000000.json`,
  verifier `results\overnight_system_verification\overnight-system-verification-20260605-051922.json`
  with `overall_status=pass`, and automation health
  `results\automation_health\automation-health-audit-20260605-102631.json` with
  overnight `status=ok`. Self-heal now plans on `reason=automation_health`,
  runs only the allowlisted real audit command, writes verified plan
  `results\self_heal\plans\self-heal-plan-20260605-102632.json`, then dedupes
  the same signature on the next planner run. Remaining operational watch:
  stale memories for `tradingagents-automation-wake-controller` and
  `tradingagents-night-shift-supervisor`; do not treat that as an overnight
  research-packet failure.
- 2026-06-05 MiroFish/report-33 scoring checkpoint: the candidate universe now
  includes report-33 broker/fintech watch names `HOOD`, `BULL`, `IBKR`, and
  `SCHW`, but unconfirmed broker-friction/social-flow setups are penalized by
  the advisory `mirofish_false_signal_suppression` gate. Ranked fallback rows now
  keep both a human-readable market `reason` and a separate `fallback_reason`.
  Real no-latest/no-submit scoring proof:
  `results\overnight_plans\mirofish_score_probe\overnight-plan-20260605-103822-000000.json`
  with `candidate_universe=40`, `tradable_universe=40`, `submitted_count=0`,
  top five `KO`, `IBM`, `HD`, `CVX`, `XOM`, and research prior feed
  `results\overnight_plans\mirofish_score_probe\research_context\overnight-prior-feed-20260605-103817.json`.
  The proof packet shows KO/IBM/HD/CVX/XOM as controlled-dip quality/energy/
  defensive relative-bias ideas, while `SCHW`, `IBKR`, `AMD`, `HOOD`, and `BULL`
  are downranked until broker/flow or institutional confirmation appears.

- 2026-06-05 report-33 positive relative-bias checkpoint: the MiroFish/report-33
  overlay now tags Dow/quality/energy/defensive-style stock rows with
  `deep_research_positive_relative_bias` when the report's positive-bias map is
  present. `build_candidate_signals(...)` gives those rows a small advisory
  boost only when price action is not a green spike or falling knife, preserving
  the buy-dip / no-chase behavior while making report 33's "relative trades and
  risk control" logic actionable. Real refreshes after this patch:
  MiroFish/report-33 packet
  `results\mirofish_handoff\research-intel-research-intel-670b65db8e334d2ebf2ad8edb1e04d4a.json`,
  overnight verifier
  `results\overnight_system_verification\overnight-system-verification-20260605-040252.json`
  with `overall_status=pass`, source-quality review
  `results\source_quality\source-quality-review-20260605-090250.json` with
  `source_count=250`, `stale_needs_refresh_count=0`, `blocked_count=62`, process
  review `results\process_reviews\process-review-20260605-090324.json` with
  `unchecked_step_count=0`, and cohort replay summary
  `results\research_batches\walk_forward_cohort_refresh_20260605-090325_h3.json`.
  Verification: targeted Ruff passed, focused MiroFish/scorer tests passed with
  19 tests, and full pytest passed with `883 passed, 1 skipped, 9 warnings,
  75 subtests passed`.
- 2026-06-05 source-ordering and overnight-completion checkpoint: provider
  bundles now use `results/source_quality/latest.json` for source-strength-aware
  ordering when available. Source-quality reviews include `blocked_count`, and
  blocked providers are penalized before cost tier so unlimited/known-good
  sources can be used before blocked limited APIs. Latest source-quality proof:
  `results\source_quality\source-quality-review-20260605-080800.json` with
  `source_count=250`, `stale_count=96`, `blocked_count=65`,
  `stale_needs_refresh_count=0`; real KO market-news proof
  `results\research_evidence\source-evidence-source-evidence-73f035b4ea7d47af86fd34ce55c9be7f.json`
  selected `official_cache` plus fresh local `reddit_watchlist` with
  `source_quality_ordering.enabled=true`. Overnight packets now expose
  `overnight_quality.completion_status` / `completion_reasons`, and compact
  overnight stdout carries the same fields. Real no-latest compact preview
  `results\overnight_plans\completion_status_probe\overnight-plan-20260605-082412-000000.json`
  returned `completion_status=not_requested` and `submitted_count=0`; the
  production overnight verifier still reports `overall_status=pass`.
  Focused proof: source/provider tests passed with 35 tests, overnight/verifier
  tests passed with 15 tests, and targeted Ruff passed.
- 2026-06-04/05 overnight and MiroFish qualitative-gate checkpoint: fresh MiroFish status now treats observed qualitative telemetry indices as conservative advisory evidence instead of zero-value no-ops. Latest `results\mirofish_handoff\latest.json` shows `mirofish_advisory_gate_action=suppress`, triggered gates `broker_friction`, `macro_override`, and `attribution_error`, `execution_authority=none`, and no missing advisory pieces. Fresh overnight rerun `results\overnight_plans\overnight-plan-20260605-040719-000000.json` completed the explicit Google original-graph route with top candidates `KO`, `IBM`, `HD`, `CRM`, `QCOM`, `full_graph_attempt_count=3`, `full_graph_success_count=3`, `fallback_count=32`, `graph_failure_count=0`, and `submitted=[]`. Provider bundles refreshed for `KO`, `IBM`, and `HD` at `results\research_evidence\source-evidence-source-evidence-26dedb9a401f4268b66e104f020a20d9.json`, `results\research_evidence\source-evidence-source-evidence-6097ce36839744abb71f34fdb4d1186f.json`, and `results\research_evidence\source-evidence-source-evidence-0f438c6a9c8f47e2bbf124831c59b53e.json`. Fresh premarket brief `results\premarket_briefs\premarket-brief-20260605-040926-000000.json` has top symbol `KO`, no stale warnings, and no unresolved blockers. Fresh verifier `results\overnight_system_verification\overnight-system-verification-20260604-231510.json` is `overall_status=pass`. `walk-forward-returns-from-overnight` now writes `generated_at`/analysis-only metadata, regenerated `results\research_batches\walk_forward_returns_real_20260601_h3.json`, and fresh source quality `results\source_quality\source-quality-review-20260605-063725.json` has `source_count=250`, `stale_count=73`, `stale_safe_count=73`, `stale_needs_refresh_count=0`, `missing_or_invalid_count=0`; compact context has `flags=[]`, `next_open=[]`, and source-routing `gap_count=0`.
- 2026-06-04 updated overnight proof: a real rerun of the automation path produced `results\overnight_plans\overnight-plan-20260604-223730-000000.json` with top candidates `TXN`, `QCOM`, `KO`, `IBM`, `INTC`, `full_graph_attempt_count=3`, `full_graph_success_count=3`, `fallback_count=32`, `graph_failure_count=0`, `submitted=[]`, and prior-feed pointer `results\overnight_plans\research_context\overnight-prior-feed-20260604-222820.json`. Provider bundles refreshed for `QCOM`, `TXN`, and `KO`; a Crawlee storage leak was fixed so each run uses a per-run `CRAWLEE_STORAGE_DIR` instead of reusing an old ticker queue. Fresh premarket brief `results\premarket_briefs\premarket-brief-20260604-230506-000000.json` has top symbol `TXN`, no stale warnings, no unresolved blockers, and a compact `latest_research_context.prior_feed` enriched from the prior-feed JSON with `analysis_only=true`, `execution_authority=none`, and forbidden effects including `submit_order`. Fresh verifier `results\overnight_system_verification\overnight-system-verification-20260604-180544.json` is `overall_status=pass`, including `overnight_prior_feed=pass`. Fresh source-quality review `results\source_quality\source-quality-review-20260604-224903.json` has `source_count=250`, `stale_count=36`, `stale_needs_refresh_count=0`, and `missing_or_invalid_count=0`. Compact context refresh after verification has `flags=[]` and `next_open=[]`.
- 2026-06-04 final-submit safety and overnight-status verifier checkpoint: live buys now require current broker `buying_power` inside `evaluate_go_live_guard(...)` and `validate_supervisor_live_submit_allowed(...)`; this is not a restored repo dollar cap, and profit-taking/loss-review sell behavior is unchanged. `alpaca verify-overnight-system` now also audits `automation_status:tradingagents-overnight-planning`, so a future accidental `PAUSED` overnight automation fails verification instead of looking like a research-quality problem. Latest real verifier after this patch: `results\overnight_system_verification\overnight-system-verification-20260604-192530.json`, `overall_status=pass`, expected/actual status `ACTIVE`, top overnight `TXN`, current top `QCOM`, premarket top `TXN`, 3/3 graph successes, 32 fallbacks, and 0 graph failures.
- 2026-06-04 submit-helper and prior-feed integrity checkpoint: the lower-level `execute_order_pairs(...)` helper now refuses paper/live mirrored live orders unless its caller explicitly passes `live_guard_approved=True`, which the legacy CLI does only after `validate_supervisor_live_submit_allowed(...)` returns clean. `alpaca verify-overnight-system` now also checks that the compact prior-feed reference and loaded JSON agree on schema/counts/authority and that the path stays under the overnight packet's `research_context` directory. Focused proof: 7 verifier/execution tests passed, including corrupt prior-feed mismatch and direct helper calls without guard approval.
- 2026-06-04 broker-clock/session submit checkpoint: the tiny-live operational guard now consults Alpaca broker clock session state before live submits. Regular-hours tiny-live orders require broker `clock.is_open=true`; extended-hours actions require the broker calendar to confirm the current date is a trading day. This blocks holiday/closed-session drift without reintroducing PDT/day-count rules. Focused proof: broker session, execution safety, live gate, and hourly submit tests passed with 43 tests.
- 2026-06-04 stale-quote candidate checkpoint: `_fetch_aggressive_candidate_market_data()` now tags yfinance `5d/1d` rows with `quote_fresh=false`, `stale_quote=true`, session label, and stale reason during tradeable sessions; `build_candidate_signals()` refuses rows explicitly marked stale/not fresh. This keeps daily closes usable for closed-market overnight context while preventing in-session live/paper candidates from ranking off a stale daily bar. Focused proof: stale quote fetcher/scorer regressions passed, and Ruff stayed clean.
- 2026-06-04 intraday quote replacement checkpoint: during tradeable sessions the aggressive-candidate fetcher now attempts yfinance `1d/5m` with `prepost=true`; a row becomes rankable only when the latest intraday bar has a parseable timestamp no older than 30 minutes. Daily bars still provide closed-market context and previous-close fallback, but stale/unavailable intraday data stays marked `stale_quote=true`. Proof: focused intraday/stale regressions passed, targeted Ruff passed, compile passed, and the CLI/supervisor slice passed with 133 tests.
- 2026-06-04 Alpaca market-data quote checkpoint: `tradingagents.dataflows.alpaca_market_data.fetch_alpaca_latest_trades(...)` is a read-only Alpaca Data API adapter with `execution_authority=none`. During tradeable sessions the aggressive-candidate feed now prefers fresh Alpaca latest-trade rows, falls back to yfinance `1d/5m` when Alpaca is missing or stale, and leaves rows stale if no fresh provider is available. Real read-only simulated-regular probe produced 35 rows and correctly marked after-hours yfinance bars stale; focused provider/fallback tests passed and broader provider/CLI/supervisor slice passed with 154 tests.
- 2026-06-04 hourly bridge checkpoint: pre-open `validate_premarket_brief_against_candidates` now returns compact `latest_research_context.prior_feed`, so `alpaca supervise-hourly` evidence can consume the MiroFish/report-33/overnight prior feed without opening raw premarket or research packets. Focused CLI proof passed via `tests/test_alpaca_cli.py::test_preopen_supervisor_includes_premarket_brief_validation`; closed-session real dry-run `results\hourly_supervisor\hourly-supervisor-20260604-232011-923105.json` stayed `decision=hold`, `submitted_count=0`, and `issue_count=0`.
- 2026-06-04 MiroFish/report-33 overlay checkpoint: `research mirofish-handoff-status --json-output` now exposes the final MiroFish advisory handoff for `report_9c77ca2557ae`, the full MiroFish report highlights, and `C:\Users\Corbin\Downloads\deep-research-report (33).md` as `deep_research_report_33`. Morning research should treat this as advisory-only priors: macro-first, relative-trade context; positive bias to Dow/quality/energy/defensives, negative/cautious bias to QQQ/semis/crowded AI beta, and event-sensitive broker/fintech watch names (`HOOD`, `BULL`, `IBKR`, `SCHW`) only after broker/flow confirmation. It must not submit, size, or promote orders.
- 2026-06-04 MiroFish/report-33 ranking checkpoint: overnight planning now applies the advisory priors to market rows before candidate scoring. Rows can be tagged with `macro_event_risk`, `mirofish_bot_correlation`, and `deep_research_crowded_ai_beta`; unconfirmed prompt-bot/social copycat attention is downranked, and crowded AI-beta names during macro-event risk are penalized unless independent confirmation appears. This is an advisory ranking filter only; it never creates an action, order, size, or promotion.
- 2026-06-04 late-control checkpoint: `tradingagents-overnight-planning` is ACTIVE again for the 2:30 AM America/Chicago run after the wake controller's morning pause. Real verification `results\automation_health\automation-health-audit-20260604-212831.json` reports all 13 automations OK, `issue_count=0`, `submitted_order_count=0`, and overnight planning `config_status=ACTIVE`. The current overnight packet is not missing: `alpaca verify-overnight-system --json-output` passed at `results\overnight_system_verification\overnight-system-verification-20260604-162641.json`.
- 2026-06-06 n8n dashboard/workflow sync checkpoint: local n8n remains reachable at `http://localhost:5678` and the repo runner bridge remains healthy on `127.0.0.1:8765`. The current evaluation dataset proof is `results\n8n_evaluations\n8n-evaluation-dataset-20260606-204956-806412.json` with `row_count=183`, 20 allowlisted jobs, 17 edge tags, and 23 columns. The local n8n Data Table `TradingAgents_Automation_Evaluations` was refreshed through the public API via a temporary SQLite-key copy, with redacted proof `results\n8n_evaluations\n8n-api-sync-20260606-205308-805632.json`, `expected_row_count=183`, `final_row_count=183`, `row_count_matches=true`, `column_count=23`, and `api_key_redacted=true`. `research n8n-sync-workflows --json-output` then created missing inactive local copies of source-controlled `TA · Automation Evaluations (observer)` and `TA · Sync Evaluation Dataset (observer)` workflows; proof `results\n8n_evaluations\n8n-workflow-sync-20260606-210202-886336.json` recorded 12 source workflows, 10 existing matches, 2 creates, and two legacy duplicate `TA · Sync Evaluation Dataset` workflows left untouched. Compact context now summarizes both Data Table sync and workflow sync under `n8n_evaluation_dataset`, including `sync_current_row_count_matches=true` and `workflow_sync_status=ok`; agents should open raw n8n packets only when compact context flags missing columns, sync drift, workflow drift, row mismatch, or key-redaction failure.
- 2026-06-05 n8n evaluation checkpoint: the first local n8n Data Table/API sync and native `TA · Built-in Automation Evaluation` import worked, and real CLI probes established that Evaluation Trigger execution still has to be started from the authenticated editor/evaluations UI rather than `n8n execute`. The 2026-06-06 dashboard/workflow sync checkpoint above supersedes the old row/job counts and proof paths.
- 2026-06-05 n8n native-run boundary: a redacted public API probe using the local SQLite API key returned `404` for `/api/v1/workflows/taBuiltInAutomationEvaluation/test-runs*` and `401` for internal `/rest/workflows/.../test-runs*`; the public key can sync Data Tables but cannot start native Evaluation Trigger test-runs. Start the actual built-in evaluation from an authenticated n8n editor/evaluations UI session.
- 2026-06-04 overnight prior-feed checkpoint: `write_overnight_research_context` now emits a compact `overnight_prior_feed_v1` JSON artifact beside raw source packets, compact overnight stdout exposes `research_context_summary.prior_feed`, and `alpaca verify-overnight-system` audits the pointer as `overnight_prior_feed`. Real no-latest/no-graph proof `results\overnight_plans\prior_feed_probe\research_context\overnight-prior-feed-20260604-221007.json` carries provider fallbacks, watchlists, MiroFish/report-33 filters, deep-research route policy, packet refs, `analysis_only=true`, and `execution_authority=none`. The latest real full overnight packet now carries the pointer, premarket enriches skinny old pointers by reading the pointed prior-feed JSON, and verifier `results\overnight_system_verification\overnight-system-verification-20260604-180544.json` is `overall_status=pass`.
- 2026-06-04 overnight truth checkpoint: overnight planning was not missing; it had degraded to fallback-only when Windows Ollama was unavailable and Mac `deepseek-r1:14b` was correctly kept as a cheap helper lane, not the full original TradingAgents graph lane. The automation command now explicitly requests the Google graph route (`--overnight-llm-provider google`, quick `gemini-2.5-flash-lite`, deep `gemini-2.5-flash`), and explicit non-Ollama routes clear inherited Ollama backend URLs. A real full run completed three original TradingAgents graph tickers with zero order submissions: `results\overnight_plans\overnight-plan-20260604-184407-000000.json` has `full_graph_attempt_count=3`, `full_graph_success_count=3`, `fallback_count=32`, `graph_failure_count=0`, and top candidates `KO`, `HD`, `AMD`, `TXN`, `PEP`. `alpaca verify-overnight-system` now passes at `results\overnight_system_verification\overnight-system-verification-20260604-140301.json`. The OpenAI probe failed only because the shell lacks `OPENAI_API_KEY` / `OPENAI_ADMIN_KEY`.
- 2026-06-04 live-gate circuit-breaker checkpoint: `daily_loss_halt_usd` and `max_drawdown_halt_pct` from `config/risk_envelope.yaml` now block new live buys when account daily loss/drawdown meets the configured thresholds, even in `autonomous_uncapped`. Profit-taking sells remain allowed, and losing sells still require the structured loss-exit review.
- 2026-06-04 broker-snapshot provider checkpoint: `research ticker-provider-bundle --symbol KO --evidence-needs quote_price_context` now writes sanitized `broker_snapshot` evidence from the newest hourly supervisor packet instead of querying broker APIs. Proof packet `results\research_evidence\source-evidence-source-evidence-f5c7d62d87ca4be0901db1a13d67c0cb.json` carries live/paper account summaries, symbol-specific position/open-order context, ranked candidate context, `submitted_order_count=0`, `read_only=true`, and `execution_authority=none`; raw broker/order IDs are not copied.
- 2026-06-04 social-provider checkpoint: `reddit` in `config/research_provider_fallbacks.json` now routes to `dataflow:reddit_public` and only emits `social_sentiment` packets so it does not crowd out Google/Alpaca/news-provider `market_news`. Real NVDA proof `results\research_evidence\source-evidence-source-evidence-068230c2d7054c3b9d6d8569d719d566.json` wrote a low-authority read-only Reddit packet even when public Reddit returned HTTP 403 for one subreddit. `twitter` now routes only to `social_sentiment` and calls Docker MCP `twitter-research` from repo code through `tradingagents.research.twitter_mcp`; real proof `results\research_evidence\source-evidence-source-evidence-93ac9af1591c4a54a5d10d377e59afa7.json` is read-only, `execution_authority=none`, and currently blocked by X recent-search 401/API tier rather than a missing repo bridge.
- 2026-06-04 connector-health noise checkpoint: public Reddit HTTP 403 from `reddit_public` is now classified as an optional endpoint block when there is no open circuit, rate limit, or fallback, so it stays visible in connector health but does not create a hard `connector_health` wake-up flag. Real compact-context refresh after the patch removed the connector-health flag; focused proof `tests/test_automation_context_snapshot.py` passed with 27 tests.
- 2026-06-04 compact context/model telemetry checkpoint: paper tournament compaction now surfaces `latest_report.generated_at`, keeps the unchanged `pullback-support` candidate visible, and only raises `candidate_change` for real promotion/selection/submission events. Model telemetry now separates current route state from historical blocked packets: `results\model_telemetry_reports\model-telemetry-report-20260604-210104-955683.json` shows current Mac `mac_ollama_research_mule` success on `deepseek-r1:14b`, deterministic packet helpers success, Codex thread judgment fallback, and only Windows local Ollama currently blocked. `results\_context\latest-summary.json` exposes `selected_helper_routes` so morning agents can use Mac DeepSeek helper work without opening the raw telemetry report; `latest-flags.json` now only asks for MiroFish drilldown.
- 2026-06-04 MiroFish compaction checkpoint: clean final MiroFish handoff now stays visible through compact context without permanently raising a raw-packet drilldown. `results\_context\latest-summary.json` carries `full_report_core_filter` and `deep_research_review_core_filter`, `missing_piece_count=0`, `final_advisory_available=true`, and `execution_authority=none`; `results\_context\latest-flags.json` is empty after the real refresh. Open raw MiroFish only if required advisory pieces are missing, the scaffold is stale/missing, or clean-room/execution-authority fields are wrong.
- Fresh verification for this checkpoint: compile checks passed; Ruff passed on touched files; focused tests passed: MiroFish/report-33/n8n/overnight warning `12 passed`, overnight+n8n/source/research `49 passed`, live gate/execution safety `33 passed`, full `tests/test_alpaca_cli.py` `72 passed`, department sweep `156 passed`. Real read-only commands refreshed `results\mirofish_handoff\latest.json`, `results\overnight_system_verification\latest.json`, `results\process_reviews\latest.json`, and `results\_context\latest-summary.json`.
- Repo improvement program (6 prioritized, handoff-ready Codex workstreams P0–P5: foundation hygiene, connector resilience + health telemetry, decision-quality backtest/calibration, supervisor/self-heal/overnight reliability, gated MiroFish ingestion, lossless token compression): `docs/IMPROVEMENT_PROGRAM.md`. Dispatch one per chat; prepend the shared preamble; analysis-only, no order wiring.
- Endgame original TradingAgents workflow plan: `docs/superpowers/plans/2026-06-03-endgame-original-tradingagents-workflow.md`.
- Active endgame direction: run the original `TradingAgentsGraph.propagate(...)` creator workflow as a first-class research lane, preserve role artifacts, convert role claims into Agent Intelligence Ledger forecasts, and keep Alpaca execution authority inside deterministic broker gates.
- Latest creator-workflow artifact slice: `tradingagents/research/original_workflow.py` writes full Analyst/Researcher/Trader/Risk/Portfolio role markdown plus `creator_workflow_packet.json`; overnight full-graph ticker results now include compact `creator_workflow` refs with `execution_authority=none`.
- Creator-workflow focused proof: `uv run --with pytest python -m pytest tests/test_original_tradingagents_workflow.py tests/test_alpaca_cli.py::test_plan_overnight_passes_overnight_graph_config_to_guarded -q` passed with 3 tests; `.\.venv\Scripts\python.exe -m py_compile tradingagents\research\original_workflow.py cli\main.py` passed.
- Creator-workflow ledger slice: `tradingagents/evals/agent_intelligence_ledger.py` now follows `creator_workflow.packet_path`, reads role artifacts, and creates scoreable forecasts for original workflow roles with `setup=creator_tradingagents_workflow`.
- Creator-ledger focused proof: `uv run --with pytest python -m pytest tests/test_agent_intelligence_ledger.py tests/test_alpaca_cli.py::test_research_agent_ledger_from_overnight_writes_forecasts -q` passed with 8 tests; `.\.venv\Scripts\python.exe -m py_compile tradingagents\evals\agent_intelligence_ledger.py tradingagents\research\original_workflow.py cli\main.py` passed.
- Source-quality eval slice: `research source-quality-review --json-output --compact-json-output` writes full analysis-only review packets under `results/source_quality/` while printing `compact_source_quality_review_v1` with counts, sample flagged sources, and raw drilldown paths; n8n allowlisted job `source_quality_review` now calls the compact flag and remains `submit_capable=false`.
- Source-quality focused proof: `uv run --with pytest python -m pytest tests/test_source_quality.py tests/test_integration_registry.py tests/test_n8n_runner_policy.py -q` passed with 26 tests; real n8n job wrote `results\source_quality\source-quality-review-20260603-030556.json`.
- Compact context slice: `scripts/automation_context_snapshot.py` now summarizes overnight `creator_workflow` refs and `source_quality_review` packets; proof `uv run --with pytest python -m pytest tests/test_automation_context_snapshot.py -q` passed with 14 tests.
- Compact context provenance slice: `scripts/automation_context_snapshot.py --write` now also writes `results/_context/field-provenance.json`, mapping every compact `latest-summary.json.latest_packets[*]` field to a raw packet field, raw file metric, drilldown-rule derivation, or missing-packet marker. Focused proof: `uv run --no-sync --with pytest python -m pytest -q tests/test_automation_context_snapshot.py tests/test_token_context_hooks.py tests/test_n8n_runner_policy.py` passed with 58 tests; full-suite baseline before the slice passed with 703 tests, 1 skipped live-key test, 9 warnings, and 75 subtests.
- n8n observer slice: allowlisted `creator_workflow_status`, `agent_ledger_summary`, and `source_quality_review` jobs are `submit_capable=false`; real n8n runs for creator status and ledger summary returned `status=ok`.
- P1 connector-transport slice: all research/data HTTP adapters now route through `tradingagents.dataflows._official_common` with retry/backoff, 429 `Retry-After`, circuit telemetry, and `results/_context/connector-health.json`; only the Alpaca broker transport remains separate. Proof: `uv run --no-sync --with pytest python -m pytest tests/test_alphainsider.py tests/test_reddit_dataflow.py tests/test_official_dataflows.py -q` passed with 35 tests; targeted Ruff and dataflows/AlphaInsider mypy passed.
- Warning-only `PreToolUse` hook slice: `.codex/hooks/hooks.json` now calls `.codex/hooks/token_context_hook.py` before tool use; `tradingagents/orchestration/token_context.py` warns on broad raw packet reads, broad `results` searches, automation memories, Deep Research reports, and `.env` reads while keeping `warning_only=true` and `block_execution=false`.
- Warning-only hook proof: `uv run --with pytest python -m pytest tests/test_token_context_hooks.py tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py -q` passed with 42 tests; compile check passed; manual fake `PreToolUse` payload returned `0`, wrote `results\_context\hook-events\hook-event-20260603-034001-934940.json`, printed `pre_tool_warning=warning_only`, and redacted `api_key`.
- Popular strategy scorecard slice: `tradingagents/brokers/paper_tournament.py` now exposes `build_popular_strategy_scorecards(...)` and attaches `popular_strategy_scorecards` to tournament reports for pullback support, earnings drift / estimate revision, event underreaction, pairs/co-movement residuals, news/sentiment swing, macro regime overlay, and AlphaInsider allocation shadow. Proof: `uv run --with pytest python -m pytest tests/test_paper_tournament.py -q` passed with 10 tests.
- n8n workflow-map slice: `docs/orchestration/n8n-workflow-map.md` documents n8n as observer/control-plane wrapper, the local runner bridge, compact-context rules, all requested workflows, phased migration, and the manual status-dashboard POC. Proof: `uv run --with pytest python -m pytest tests/test_n8n_runner_policy.py -q` passed with 18 tests.
- n8n job-discovery slice: `python -m tradingagents.orchestration.n8n_runner --list-jobs --json` lists the allowlisted compact jobs without running them; all discovered jobs are `submit_capable=false`.
- n8n evaluation harness slice: `research n8n-evaluation-dataset --json-output --compact-json-output` writes a full Data Table-ready JSON/CSV/Markdown dataset with 201 rows across 22 allowlisted jobs and 17 edge tags while stdout emits only `compact_n8n_evaluation_dataset_v1`. Latest compact proof: `results\n8n_evaluations\n8n-evaluation-dataset-20260607-022657-756033.json`. The local runner exposes full rows at `/evaluation-dataset`; `research n8n-sync-evaluation-table --json-output` syncs the local n8n Data Table `TradingAgents_Automation_Evaluations` through n8n's public API and writes a redacted proof packet to `results\n8n_evaluations\latest-sync.json`. Current sync proof `results\n8n_evaluations\n8n-api-sync-20260607-022929-127780.json` used a temporary copied n8n SQLite database only to read the existing API key, inserted 201 rows, and has `row_count_matches=true` with `api_key_redacted=true`. `research n8n-sync-workflows --json-output` syncs source-controlled observer workflows into local n8n as inactive workflows and writes `results\n8n_evaluations\latest-workflow-sync.json`. Source-controlled observer workflow JSON includes evaluation dataset and automation-evaluation observers plus native workflow `TA · Built-in Automation Evaluation`. Compact context exposes the dataset, Data Table sync, and workflow sync status, so raw n8n packets are only needed when columns, sync, workflow names, row counts, or redaction fail. Built-in n8n Evaluation Trigger workflows still need to be run from the editor after login; CLI/MCP execution is not the acceptance gate for Evaluation Trigger nodes.
- Self-heal handoff slice: `research self-heal-handoff --json-output` writes `results/self_heal/latest.json`, `latest.md`, and `latest-prompt.txt`; it is analysis-only, cannot submit orders, and tells the Codex self-heal automation whether a fresh repair chat should run.
- PA self-heal safe-executor slice: `research self-heal-plan --json-output` classifies compact failure signals into safe plans or escalations; `research self-heal-plan --execute-safe --json-output` runs only allowlisted context-refresh verification actions. Latest proof: `results\self_heal\plans\self-heal-plan-20260603-191016.json`, `executed_count=2`, `verified_count=2`, `verify_failed_count=0`, `escalation_count=1`, `can_submit_orders=false`. Timeliness proof: `results\automation_health\automation-health-audit-20260604-165711.json`, `ok_count=13`, `timeliness_issue_count=0`, `submitted_order_count=0`, `issue_count=0`.
- Goal/subagent contract slice: `docs/orchestration/goal-agent-context-contract.md` defines repo-local goal states, compact goal context rules, subagent output contract, wrapper proof boundary, and the rule that hidden hooks do not mutate native Codex goals.
- Endgame eval summary: `reports/orchestration/ENDGAME_EVAL_SUMMARY.md`; focused endgame regression passed with 78 tests and broad repo regression passed with 586 tests, 1 skipped live-key test, 8 warnings, and 75 subtests.
- Latest real simulation audit before the loss-review patch: `results\real_simulation_audits\real-simulation-audit-20260603-065410.json`, `failed_command_count=0`, `total_submitted_order_count=0`, `stale_source_count=35`, `stale_downrank_count=35`, Mac Ollama `deepseek-r1:14b` reachable, and `can_submit_orders=false`.
- Loss-review safety checkpoint: an audit-time live ORCL loss close filled before the rule was tightened. Current code now emits `decision=loss-review`, `actions=[]`, and `submitted=[]` for unapproved losing live exits; explicit thesis-break/time-value/capital-reuse evidence is required before a loss exit can become an action. Clean proof packet: `results\hourly_supervisor\hourly-supervisor-20260603-142301-935239.json`.
- Execution BOARD checkpoint: `review_underperformers_before_new_buys` pauses new live buys only; it does not pause paper exploration or force a sell. Latest BOARD evidence: `results\execution_board\execution-board-review-20260603-192427.json`; historical ORCL loss-sell packets without structured `evidence.loss_exit_review` are flagged, while newer `loss-review` packets do not submit.
- Latest real simulation audit after the loss-review, MiroFish, self-heal-timeliness, and BOARD patches: `results\real_simulation_audits\real-simulation-audit-20260603-192427.json`, `failed_command_count=0`, `total_submitted_order_count=0`, `total_blocker_count=0`, `stale_source_count=115`, `stale_safe_count=115`, Mac Ollama `deepseek-r1:14b` reachable, and `can_submit_orders=false`.
- Latest process review after self-heal monitor wiring: `results\process_reviews\process-review-20260603-200020.json`, `unchecked_step_count=0`, `can_submit_orders=false`.
- Plugin methodology integration plan: `docs/superpowers/plans/2026-06-03-plugin-methodology-integration.md`.
- Latest control-plane hardening slice: process-review now scans all Superpowers plan docs; n8n rejects non-submit broker-capable command drift; Codex hook event parsing supports native hook payload names. Focused proof: `uv run --with pytest python -m pytest tests/test_process_review.py tests/test_n8n_runner_policy.py tests/test_token_context_hooks.py -q` passed with 23 tests.
- P0 foundation/static-analysis checkpoint: `pyproject.toml` now has the `static-analysis` group, Ruff `E,F,I,B,UP,SIM`, broad broker/policy/execution/dataflow mypy baseline, and strict typed-frontier mypy. `requirements.txt` is repaired for legacy pip users and `backtrader` is removed. Fresh proof: `uv run --no-sync --group static-analysis ruff check` passed; broad mypy passed on 52 source files; strict frontier mypy passed on 8 source files; `uv run --no-sync --with pytest python -m pytest -q tests/test_integration_registry.py tests/test_config_examples.py tests/test_n8n_runner_policy.py tests/test_real_simulation_audit.py tests/test_live_gate.py` passed with 63 tests.
- P2 decision-quality checkpoint: `tradingagents research decision-quality-report --candidate-symbols NVDA,MSFT --json-output` writes an analysis-only point-in-time audit plus shrinkage rating calibration packet. Latest packet: `results\research_batches\research-batch-research-batch-4b94859e548b4221ac1b974fc8b27560.json`, with `status=success`, `point_in_time_gap_count=0`, `point_in_time_mixed_count=0`, public Reddit/StockTwits marked `live_only_unscored_in_replay`, insufficient resolved rating history, and `execution_authority=none`. Google News RSS is now date-window filtered; EIA/Treasury macro routes thread `curr_date` into bounded query params; SEC/FMP/EODHD rendered fundamentals drop future-dated rows/date-keyed sections after `curr_date`; public social routes remain live/recent advisory evidence unless timestamped archives are added. Remaining P2 work is the >=10-name fixed-as-of walk-forward graph replay. Focused proof: `uv run --no-sync --with pytest python -m pytest -q tests/test_official_dataflows.py tests/test_decision_vendor_adapters.py tests/test_dataflows_interface.py tests/test_replay_ablation_plan.py` passed with 59 tests; Ruff/broad mypy/compile checks passed.
- Walk-forward replay checkpoint: `tradingagents research walk-forward-replay --fixture-path tests\fixtures\walk_forward_replay_sample.json --candidate-symbols NVDA,MSFT,AAPL,AMZN,GOOGL,META,TSLA,AMD,AVGO,JPM --minimum-decisions-per-arm 10 --json-output` wrote `results\research_batches\research-batch-research-batch-8691b073a65b4372ac1da19341f2e563.json`, with `status=success`, `walk_forward_row_count=10`, `sample_floor_met=true`, baseline accuracy `0.7000`, TradingAgents advisory overlay accuracy `0.9000`, social/crawler and Deep Research overlays unavailable, and `execution_authority=none`. Remaining P2 work is a captured historical graph-decision dataset/generator so the harness scores real TradingAgents pipeline outputs.
- Captured overnight-to-fixture checkpoint: `tradingagents research walk-forward-fixture-from-overnight --overnight-packet tests\fixtures\overnight_packet_sample.json --returns-path tests\fixtures\overnight_returns_sample.json --output-path results\research_batches\walk_forward_fixture_from_overnight_sample.json --json-output` wrote `row_count=2`, `skipped_count=1`, `execution_authority=none`; replaying that generated fixture wrote `results\research_batches\research-batch-research-batch-e09e0e205e8e4f72a915ed0bfe939996.json` with `sample_floor_met=true` for the 2-row proof. Remaining P2 work is automated later-return collection for real captured overnight packets and a larger replay cohort before any influence promotion.
- Later-return collection checkpoint: `tradingagents research walk-forward-returns-from-overnight --overnight-packet tests\fixtures\overnight_packet_sample.json --price-rows-path tests\fixtures\overnight_price_rows_sample.json --horizon-days 5 --output-path results\research_batches\walk_forward_returns_from_overnight_sample.json --json-output` wrote `row_count=2`, `skipped_count=1`, `price_route=static_price_rows`, `execution_authority=none`; fixture output from those returns is `results\research_batches\walk_forward_fixture_from_collected_returns_sample.json`; replay packet is `results\research_batches\research-batch-research-batch-58e875ebe0b74df28c5b1349f886ecda.json`. Remaining P2 work is running the yfinance route on real captured packets as enough historical outcomes mature, then expanding sample size before influence promotion.
- Real captured-packet replay checkpoint: yfinance return collection over six June 1 overnight packets wrote `results\research_batches\walk_forward_returns_real_20260601_h3.json` with `row_count=70`, `skipped_count=0`, `horizon_days=3`, benchmark `SPY`; fixture generation wrote `results\research_batches\walk_forward_fixture_real_20260601_h3.json` with `row_count=210`; replay wrote `results\research_batches\research-batch-research-batch-ee09089c106b4902a776046dd1bfd87a.json` with `sample_floor_met=true`, deterministic accuracy `0.4048`, false-positive rate `0.1667`, average Brier `0.2555`, average relative return vs benchmark `0.2481`, average action-relative return `0.0409`, and `execution_authority=none`.
- Provider gap promotion checkpoint: ticker-provider bundles now include `earnings_transcripts`, `short_interest`, and `options_iv_flow` as first-class needs. `earnings_transcripts` attempts optional FMP transcript evidence before its gap packet; missing keys, plan limits, or missing transcript text fall through to `local:research_gap` with `blocked=true`, `downrank_evidence=true`, and `execution_authority=none`. `options_iv_flow` attempts supplemental public `dataflow:yfinance_options` before its gap packet, and `short_interest` attempts supplemental public `dataflow:yfinance_short_interest` before its gap packet. All three are analysis-only, confirmation/downrank-only routes.
- Graph cleanup checkpoint: social/sentiment remains the saved config key, but the sentiment analyst is now graph-declared tool-free. `tools_social` is no longer registered as a dead graph branch; the read-only `get_sentiment_context` tool remains available for non-dead routes/tests.
- P5 compact overnight output checkpoint: `alpaca plan-overnight --json-output --compact-json-output` now emits `compact_overnight_plan_v1` with `raw_packet_path`, counts, top candidate, ticker status counts, selected quality fields, and raw-field group pointers instead of dumping the full packet to stdout. Real probe with `--full-graph-tickers 0 --no-research-context --no-agent-ledger --no-write-latest --log-dir results\overnight_plans\compact_probe` wrote compact stdout pointing to `results\overnight_plans\compact_probe\overnight-plan-20260604-033601-000000.json`; `submitted_count=0`, `ticker_results=35`, `fallback_count=35`, `execution_authority=none`.
- P5 compact premarket output checkpoint: `alpaca premarket-brief --json-output --compact-json-output` now emits `compact_premarket_brief_v1` with raw packet path, counts, compact instruction fields, stale warnings, and raw-field group pointers. Real file-only probe with `--no-write-latest --log-dir results\premarket_briefs\compact_probe` wrote compact stdout pointing to `results\premarket_briefs\compact_probe\premarket-brief-20260604-034911-000000.json`; `source_packets=54`, `unresolved_blockers=0`, `stale_warnings=0`, `execution_authority=none`.
- P5 compact hourly output checkpoint: `alpaca supervise-hourly --dry-run --json-output --compact-json-output` now emits `compact_hourly_supervisor_v1` with raw packet path, decision/materiality, submission/issue/action counts, compact portfolio counts, top candidate, overnight/premarket/tournament/BOARD refs, live-budget mode, risk posture, and alert state. Real dry-run probe wrote compact stdout pointing to `results\hourly_supervisor\compact_probe\hourly-supervisor-20260604-040457-404346.json`; `decision=hold`, `submitted_count=0`, `issue_count=0`, `market_session=closed`, live budget `mode=autonomous_uncapped`.
- P5 compact daily-report output checkpoint: `alpaca supervisor-daily-report --json-output --compact-json-output` now writes the full raw report under `results\daily_reports` or `--daily-report-log-dir`, then emits `compact_supervisor_daily_report_v1` with body length/ref, hourly/material counts, compact portfolio, top candidate, paper tournament, premarket, model telemetry, and BOARD refs. Real account-read-only probe wrote compact stdout pointing to `results\daily_reports\compact_probe\supervisor-daily-report-20260603-231950-817954.json`; `body_summary.char_count=1998`, `ranked_candidates=35`, `top_candidate=GOOGL`, `execution_board.can_submit_orders=false`. Remaining P5 work: byte-reduction tables and follow-on automation/n8n adoption of compact flags.
- P5 compact-output audit checkpoint: `alpaca compact-output-audit --json-output` writes the measured byte-reduction table under `results\token_efficiency\`. Latest real audit `results\token_efficiency\compact-output-audit-20260603-233723-460063.json` measured raw `535,462` bytes versus compact `6,846` bytes across hourly, overnight, premarket, and daily report, saving `528,616` bytes with every row `lossless_by_reference=true`. Remaining P5 work: follow-on automation/n8n adoption of compact flags and n8n evaluation datasets.
- P5 source-quality compact-output checkpoint: `research source-quality-review --json-output --compact-json-output` now emits `compact_source_quality_review_v1` instead of dumping all per-source decisions to stdout. Real CLI proof wrote compact stdout pointing to `results\source_quality\source-quality-review-20260605-092148.json`; real n8n bridge proof wrote `results\source_quality\source-quality-review-20260605-092211.json`, parsed schema `compact_source_quality_review_v1`, `source_count=250`, `stale_count=88`, `stale_needs_refresh_count=0`, and `submit_capable=false`. Verification: source-quality/n8n focused tests passed with 46 tests, targeted Ruff passed, process review `results\process_reviews\process-review-20260605-095308.json` had `unchecked_step_count=0`, and full pytest passed with `885 passed, 1 skipped, 9 warnings, 75 subtests passed`.
- P3 self-heal dedupe checkpoint: self-heal handoffs/plans now share durable root-cause signatures in `results\self_heal\signature-state.json`; repeat handoff triggers remain audited but do not request another repair chat once recorded, and plans dedupe even if `plans/latest.json` is missing. Real safe execution proof: `results\self_heal\plans\self-heal-plan-20260604-005437.json`, `executed_count=1`, `verified_count=1`, `deduped_prior_count=1`, `can_submit_orders=false`. Focused proof: `uv run --no-sync --with pytest python -m pytest -q tests/test_self_heal_handoff.py tests/test_automation_health_audit.py tests/test_n8n_runner_policy.py` passed with 45 tests; Ruff/broad mypy/strict mypy passed.
- Deep Research artifact: `reports/research_merge/CHATGPT_DEEP_RESEARCH_TECHNICAL_DUE_DILIGENCE_2026-06-02.md`.
- Deep Research run log and repeatable browser route: `reports/research_merge/CHATGPT_DEEP_RESEARCH_RUNS.md`.
- Deep Research protocol packet proof: `results/research_evidence/source-evidence-source-evidence-15b05c70c2b5409aa762a06095826b56.json`.
- Replay/ablation plan proof: `results/research_batches/research-batch-research-batch-a2162fd572da4fdbb8b281e63b20c071.json`.
- Latest orchestration packet with graph memory, market mirror, cache key, replay-plan reference, and local-model self-heal guidance: `results/research_batches/research-batch-research-batch-2f4aaab74d9a4432a8e193b287a1656c.json`.
- MiroFish final handoff status: final advisory handoff `report_1e3059f732b1` is available at `reports/mirofish/MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md`. It is a market-mirror validation-prior layer only: no order creation, sizing, submission, promotion, or live/paper execution authority.
- Latest MiroFish status packet: `results/mirofish_handoff/latest.json`; refresh with `tradingagents research mirofish-handoff-status --json-output` before morning analysis. It should show `final_handoff_available=true`, required report id `report_1e3059f732b1`, the advisory valid window `2026-06-04 through 2026-06-13`, and full-report highlights for AI-bot copycat false positives plus institutional liquidity fade/absorb behavior. The Stage 04 prose section `AI-Bot Correlation and Institutional Liquidity Adaptation` is preserved as `full_report_ai_bot_liquidity_summary`; morning reports should treat obvious bot-crowded breakouts as false-signal risk until independent volume, broker/API execution, options liquidity, and institutional participation confirm durable flow. Execution authority remains `none`.
- Full-report provenance note: `results/mirofish_handoff/latest.json` records discovered `full_report.md` candidates in `full_report_candidate_reports` with SHA-256 hashes. The selected canonical backend report is `d5897ad3a13a0086e4b4350ac20c090575aa22c36fd043fe1105ac1df123d6f9`; `report_9c77ca2557ae` remains preserved only as a superseded baseline.
- MiroFish structured-prior note: the parser supports explicit `ticker_attention_map`, `category_attention_map`, and `retail_flow_hypotheses` when a future final handoff includes them. Missing fields must stay absent/count 0 rather than being invented from prose.
- Latest hook event summary: `results/_context/hook-events/latest.json`; compact context shows the latest hook event, goal excerpt, subagent metadata, and raw-context decision without copying the full hook payload.
- Latest clean premarket brief: `results/premarket_briefs/premarket-brief-20260602-085811-000000.json`.
- Current premarket state: `unresolved_blockers=0`, `control_plane_locks=1`, `historical_blockers=6`.
- Final broad regression gate: `uv run --no-sync --with pytest python -m pytest -q` passed with 662 tests, 1 skipped live-key test, 8 warnings, and 75 subtests.
- Regression triage: one expectation in `tests/test_research_crawler_social.py::test_overnight_research_context_fails_soft_when_config_is_missing` was updated after the overnight context correctly began attaching methodology and Deep Research protocol packets; the rerun passed without weakening gates.
- Latest overnight-system verification: `results/overnight_system_verification/overnight-system-verification-20260602-055309.json`, status `pass`.
- Latest capability audit packet: `results/capability_audits/capability-audit-20260602-105307-579641.json`; secrets redacted, optional missing vendor keys treated as skip/fallback, not crash.
- Focused API/methodology slice check: `uv run --with pytest python -m pytest tests/test_official_dataflows.py tests/test_research_provider_orchestrator.py tests/test_source_quality.py -q` passed with 38 tests.
- Focused Deep Research/replay/intelligence check: `uv run --with pytest python -m pytest tests/test_deep_research_protocol.py tests/test_replay_ablation_plan.py tests/test_research_automation_orchestrator.py tests/test_agent_intelligence_ledger.py tests/test_research_provider_orchestrator.py tests/test_source_quality.py -q` passed with 23 tests.
- Focused model-route self-heal check: `uv run --with pytest python -m pytest tests/test_model_routing.py tests/test_research_automation_orchestrator.py -q` passed with 16 tests.
- Focused AlphaInsider paper-shadow check: `uv run --with pytest python -m pytest tests/test_paper_tournament.py::test_alphainsider_paper_watch_uses_only_remaining_paper_budget tests/test_paper_tournament.py::test_alphainsider_paper_watch_builds_shadow_orders_from_strategy_tickers tests/test_paper_tournament.py::test_paper_tournament_alphainsider_watch_writes_paper_only_packet tests/test_paper_tournament.py::test_paper_tournament_run_submits_strategy_prefixed_paper_orders -q` passed with 4 tests.
- Crawler runtime doctor: `.\.venv\Scripts\tradingagents.exe research crawler-runtime-doctor --json-output` reports `ready=true`.
- Crawler runtime proof packet: `results/crawler_runs/crawler-run-crawler-run-e6f37ae65806419db0e6d8d18a24c7d1.json`, status `success`, page_count `1`.
- Latest model telemetry report: `results/model_telemetry_reports/model-telemetry-report-20260602-113520-840871.json`, with 16 model-lane packets currently `pending/unresolved`, `$0.0000` spend, and `auto_upgrade_allowed=false` until enough resolved evidence exists.
- Latest market-mirror proof: `results/research_simulations/market-mirror-market-mirror-f8d69b7ed00c456b9b6a22347f793dc6.json`, advisory-only with execution authority `none`.
- Latest graph-memory proof: `results/research_memory/graph_memory.jsonl` plus graph node/edge/query packets under `results/research_memory/`.
- Latest prompt-registry proof: `results/prompt_registry/prompt-registry-prompt-registry-60f4ef947c9c4b61908318d29176dad5.json`, raw prompt not stored.
- Latest process review: `results/process_reviews/process-review-20260602-114710.json`, unchecked long-plan item count `0`.
- Focused follow-on suite: `uv run --with pytest python -m pytest tests/test_deep_research_protocol.py tests/test_model_routing.py tests/test_market_mirror_memory.py tests/test_research_automation_orchestrator.py tests/test_preregistration_policy.py tests/test_process_review.py tests/test_automation_context_snapshot.py -q` passed with 39 tests.
- Focused model outcome/daily-report check: `uv run --with pytest python -m pytest tests/test_model_routing.py::test_model_telemetry_rollup_tracks_usefulness_and_outcomes tests/test_model_routing.py::test_model_telemetry_rollup_dedupes_latest_and_tracks_budget tests/test_alpaca_cli.py::test_research_model_telemetry_report_writes_budget_summary tests/test_paper_tournament.py::test_daily_report_includes_paper_tournament_leader -q` passed with 4 tests.

## System At A Glance

| Loop | What it does | What it is allowed to do | What happens if it breaks |
| --- | --- | --- | --- |
| Overnight research | Studies candidates, filings, macro, news, social chatter, crawler results, graph memory, and optional local/Gemini model summaries. | Writes analysis-only packets and a morning watch plan. | Falls back to deterministic packets, marks stale/missing data, and emails only if an ops decision is needed. |
| Research orchestration | `research automation-orchestration-plan` coordinates deterministic helpers, Windows local Ollama, Mac Ollama, and the Codex/Gemini/OpenAI judgment lane. | Writes a `ResearchBatchRunPacket` plus model telemetry for each lane. | If quality is weak, marks `fallback_required` and keeps the output advisory instead of feeding it as trade truth. |
| Model telemetry | `research model-telemetry-report`; daily report reads `results/model_telemetry_reports/latest.json` | Tracks provider/route status, cost, latency, usefulness labels, outcome labels, and resolved count. | Unresolved runs stay `pending/unresolved`; they do not gain influence until later evidence labels them. |
| Crawler runtime | `research crawler-runtime-doctor`; `research crawl-target --target URL` | Runs Crawlee + Playwright only for allowlisted, read-only targets and writes `CrawlerRunPacket`. | If runtime or target policy fails, writes blocked analysis-only packets with self-heal actions and falls back to other read-only sources. |
| Replay/ablation plan | `research replay-ablation-plan` defines the test arms for deterministic baseline versus official, news/social/crawler, TradingAgents, and Deep Research overlays. | Writes an analysis-only packet. | If replay evidence is too thin, overlays do not earn influence. |
| Ticker provider bundle | `research ticker-provider-bundle --symbol SYMBOL` collects broad overlapping source packets for a ticker. | Writes local/free/cache packets for official_cache, yfinance quote context, SEC EDGAR fundamentals, reddit_watchlist, allowlisted Crawlee crawler_research, Alpaca News, Google News RSS, Finnhub, Tiingo, FMP, and other supported vendor routes, plus a summary packet. | Skips depleted sources, marks only genuinely unsupported local routes, and keeps all output analysis-only. |
| Premarket brief | Turns overnight packets plus fresh market context into a watch list. | Summarizes what to watch; does not trade. | Marks the brief stale/invalidated and keeps the supervisor from trusting it. |
| Hourly supervisor | Checks live/paper accounts, holdings, orders, candidate signals, and gates. | Can submit paper actions; live actions must pass the unified live gate. Losing live exits require explicit thesis-break/time-value/capital-reuse evidence. | Writes a packet, blocks unsafe action, emits `loss-review`/BOARD review instead of automatic losing sells, self-heals where possible, sends clear CRITICAL email only when needed. |
| Paper tournament | Tests strategy sleeves in paper. | Submits paper-only orders and suggests advisory live candidates. | Keeps tournament paper-only and reports blockers. |
| Daily report | Explains what happened today. | Sends a plain-English report with accounts, holdings, orders, spend, and blockers. | If report data is missing, it says what is missing and what Codex will retry. |

Status words:

- `all_good`: packet written, no human action needed.
- `blocked`: bot stopped before doing something unsafe.
- `loss-review`: a losing live position needs explicit BOARD/thesis-break or time-value approval before any sell is allowed.
- `self_healing`: Codex can safely retry/repair without asking.
- `needs_ops_approval`: one human decision is needed.
- `analysis_only`: information for context; cannot place orders.

## First Commands

```powershell
python scripts/automation_context_snapshot.py --write
Get-Content results\_context\recent-deltas.md
.\.venv\Scripts\tradingagents.exe alpaca --help
```

## Static Analysis

P0 foundation hygiene adds a repo-local static-analysis group. Run it with:

```powershell
uv run --group static-analysis ruff check
uv run --group static-analysis mypy tradingagents\brokers tradingagents\policy tradingagents\execution tradingagents\dataflows
uv run --group static-analysis mypy --strict tradingagents\dataflows\integration_registry.py tradingagents\execution\clock.py tradingagents\execution\lock.py tradingagents\policy\live_control.py tradingagents\policy\packets.py tradingagents\policy\risk_posture.py tradingagents\default_config.py tradingagents\research\crawler_policy.py
```

`pyproject.toml` keeps Ruff on `E,F,I,B,UP,SIM`, makes the broad broker/policy/
execution/dataflow command pass as the enforceable baseline, and keeps strict
mypy on the current typed frontier: registry, compact policy packets, live
control, risk posture, execution clock/lock, default config, and crawler policy.
Expand the strict frontier one module at a time before broad connector/backtest
or supervisor refactors.

Use `results/_context/` before opening large JSON packets. These generated files
are lossy indexes with paths to raw evidence:

- `latest-summary.json`: current packet summaries and drilldown recommendations.
- `latest-flags.json`: exact reasons a raw packet should be opened.
- `automation-index.json`: automation prompt/model/reasoning/frequency audit.
- `recent-deltas.md`: watched-field changes across recent packets.
- `context-manifest.json`: measured size/token-weight audit.
- `automation-compaction-approval-plan.md`: proposed prompt/model/frequency changes.

## Repo Map

| Area | Start here | Notes |
| --- | --- | --- |
| CLI commands | `cli/main.py` | Typer app. Alpaca commands start around the `alpaca_app` commands. |
| Hourly/window supervisor | `tradingagents/brokers/alpaca_supervisor.py` | Decisions, evidence packets, premarket and overnight validation, daily report rendering. |
| Broker safety | `tradingagents/brokers/alpaca.py` | Account mode, order building, live/paper submit constraints. |
| Paper tournament | `tradingagents/brokers/paper_tournament.py` | Strategy sleeves, ledger, promotion candidate. |
| Tests | `tests/test_alpaca_cli.py`, `tests/test_alpaca_supervisor.py`, `tests/test_paper_tournament.py`, `tests/test_alpaca_execution.py` | Run slices, not the full suite, unless changing shared execution behavior. |
| Full repo docs | `REPO_OVERVIEW.md`, `TRADING_METHODS_AND_AUTOMATIONS.md` | Useful background, but read sections only after this router. |
| Large future spec | `CODEX_HANDOFF_PROMPT.md`, `CODEX_IMPLEMENTATION_SPEC.md` | Not required for routine automation work. |

## Automation Routing Map

| Automation | Entrypoint | First source files | Results | Narrow validation | First inspection |
| --- | --- | --- | --- | --- | --- |
| Hourly market supervisor | `alpaca check`; `alpaca supervise-hourly --dry-run`; conditional `--submit-actions`; `alpaca premarket-brief` | `cli/main.py`, `alpaca_supervisor.py`, `alpaca.py`, `paper_tournament.py` | `results/hourly_supervisor/`, `results/premarket_briefs/`, optional `results/paper_strategy_tournament/live-strategy-selection.json` | `uv run --with pytest python -m pytest tests/test_alpaca_cli.py tests/test_alpaca_supervisor.py tests/test_paper_tournament.py -q` | latest hourly JSON summary, then `alert`, `evidence`, `actions`, `issues`, `submitted`, legacy `notify` fallback |
| Paper strategy tournament | `alpaca paper-tournament init` if no ledger; `alpaca paper-tournament alphainsider-watch`; `alpaca paper-tournament run --all`; `alpaca paper-tournament report` | `cli/main.py`, `paper_tournament.py`, `alpaca.py`, `tradingagents/research/alphainsider.py` | `results/paper_strategy_tournament/`, `paper-tournament-ledger.json`, `latest.json`, optional `live-strategy-selection.json`, `alphainsider-paper-watch-*.json` | `uv run --with pytest python -m pytest tests/test_paper_tournament.py tests/test_alpaca_cli.py -q` | latest packet fields: `submitted_count`, `report.rankings`, `ledger_path`, candidate status, AlphaInsider watch status |
| AlphaInsider paper watch | `alpaca paper-tournament alphainsider-watch` | `cli/main.py`, `tradingagents/research/alphainsider.py`, `paper_tournament.py` | `results/paper_strategy_tournament/alphainsider-paper-watch-*.json`, `paper-tournament-ledger.json` | `uv run --with pytest python -m pytest tests/test_paper_tournament.py::test_alphainsider_paper_watch_uses_only_remaining_paper_budget tests/test_paper_tournament.py::test_alphainsider_paper_watch_builds_shadow_orders_from_strategy_tickers tests/test_paper_tournament.py::test_paper_tournament_alphainsider_watch_writes_paper_only_packet -q` | `available_shadow_budget_usd`, `watch_items`, `paper_shadow_orders`, `paper_shadow_spend_usd`, `fetch_status`, `paper_only`, `forbidden_effects` |
| Overnight planner | `alpaca check`; `research automation-orchestration-plan`; `research agent-ledger-update`; `alpaca plan-overnight --overnight-graph-profile compact ...`; `research ticker-provider-bundle` for up to 3 top candidates; `research agent-ledger-summary`; `alpaca premarket-brief` | `cli/main.py`, `alpaca_supervisor.py`, `tradingagents/research/automation_orchestrator.py`, `provider_orchestrator.py`, `agent_intelligence_ledger.py`, `tradingagents/graph/trading_graph.py` | `results/overnight_plans/`, `results/research_batches/`, `results/research_evidence/`, `results/agent_intelligence/`, ticker summaries under `results/overnight_plans/ticker_reports/`, refreshed `results/premarket_briefs/` | `uv run --with pytest python -m pytest tests/test_alpaca_cli.py tests/test_alpaca_supervisor.py tests/test_research_automation_orchestrator.py tests/test_research_provider_orchestrator.py tests/test_agent_intelligence_ledger.py -q`; `.\.venv\Scripts\tradingagents.exe alpaca verify-overnight-system --json-output` | `latest.json` summary, `overnight_quality`, top candidates, research batch quality gates, provider bundle counts, agent influence weights, failed ticker summaries |
| 15 min before open | `alpaca check`; refresh `premarket-brief`; `alpaca preopen-validation --json-output`; `supervise-hourly --dry-run`; conditional submit; refresh brief | same as hourly plus pre-open validation helpers in `cli/main.py` | `results/hourly_supervisor/`, `results/premarket_briefs/`, `results/preopen_validation/` | same as hourly plus `verify-overnight-system` if overnight or premarket validation looks stale; inspect `preopen_validation` first if checks warn/skip/fail | `results\preopen_validation\latest-compact.json`, then `evidence.overnight_plan`, `evidence.premarket_brief`, fresh account/order state |
| 30 min after open | `alpaca check`; `supervise-hourly --dry-run`; conditional submit; refresh brief | same as hourly | same as hourly | same as hourly | latest hourly decision, open orders, gap/volume-sensitive evidence |
| 30 min before close | `alpaca check`; `supervise-hourly --dry-run`; conditional submit; refresh brief | same as hourly | same as hourly | same as hourly | latest hourly decision, close/reduce/cancel/hold-cash actions |
| 15 min after close | `alpaca check`; `supervise-hourly --dry-run`; conditional submit; refresh brief | same as hourly | same as hourly | same as hourly | fills/rejections/stale orders and daily-report inputs |
| Daily market report | `research agent-ledger-summary`; `alpaca supervisor-daily-report --json-output --email-to ...` | `cli/main.py`, `alpaca_supervisor.py`, `paper_tournament.py`, `agent_intelligence_ledger.py` | reads `results/hourly_supervisor/`, `results/paper_strategy_tournament/`, `results/premarket_briefs/`, `results/research_batches/`, `results/research_evidence/`, `results/agent_intelligence/`; sends email | `uv run --with pytest python -m pytest tests/test_alpaca_cli.py tests/test_alpaca_supervisor.py tests/test_paper_tournament.py tests/test_agent_intelligence_ledger.py -q` | latest report JSON fields `subject`, `body`, balances, positions, P/L, packet counts, research quality, AlphaInsider watch, influence weights |
| Rolling premarket brief | `alpaca premarket-brief --json-output` | `cli/main.py`, `alpaca_supervisor.py` | `results/premarket_briefs/` | `uv run --with pytest python -m pytest tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py -q` | `premarket_instructions`, `source_packets`, `stale_warnings`, `unresolved_blockers` |
| Wake/sleep automation controllers | Codex automation status updates only | `C:\cm\automations\tradingagents-automation-wake-controller`, `C:\cm\automations\tradingagents-automation-sleep-controller` | automation statuses/memories only | Inspect TOMLs and controller memory; do not run trading commands | Confirm they only change statuses, preserve prompts/schedules/models, and never trade |

## Common Failure Modes

- Current 2026-06-05 morning override: overnight catch-up completed at
  `results\overnight_plans\overnight-plan-20260605-101740-000000.json`, the
  premarket brief refreshed cleanly, and
  `results\overnight_system_verification\overnight-system-verification-20260605-061215.json`
  passed while `tradingagents-overnight-planning` was PAUSED. That PAUSED state
  is valid after a complete analysis-only overnight packet exists.
- Current 2026-06-05 controller posture: `hourly-market-supervisor` and
  `paper-strategy-tournament-runner` were set ACTIVE through the native
  automation tool before market open; `tradingagents-overnight-planning` was set
  PAUSED after the catch-up. `tradingagents-self-heal-monitor` was simplified to
  the supported hourly RRULE form at minute 15. Do not undo these statuses unless
  a controller run proves the market-day state changed.
- Current 2026-06-06 SAFE-01 live-budget posture: Claude's handoff decision was
  verified and reconciled on disk. The real `config/risk_envelope.yaml` now
  parses as `live_budget_mode="autonomous_with_caps"`, account max `$250`, per
  name `$50`, and `issues=[]`; `config/risk_envelope.yaml` is ignored and must
  not be committed. `results\policy\live_control.json` still has a lapsed
  dead-man (`dead_man_expires_at=2026-06-04T19:57:06+00:00`), so money remains
  doubly fail-closed until the operator intentionally refreshes control. The
  submit-path hardening branch is `wip/submit-path-hardening-2026-06-05` with
  unsigned commit `3970998` for the standalone rate-limit module/tests; focused
  submit-path tests, Ruff, broad mypy, and full pytest passed after reconciliation.
- 2026-06-06 Claude-handoff prep refresh: Codex re-read the submit-path hardening
  handoff and verified current state again. Fresh submit-path regression
  `uv run --no-sync --with pytest python -m pytest tests/test_order_rate_limit.py
  tests/test_live_gate.py tests/test_execution_safety.py tests/test_alpaca_execution.py
  tests/test_alpaca_cli.py -q` passed with `160` tests; Python-targeted Ruff
  passed; the YAML example parsed via `load_risk_envelope(...)` as
  `fixed_tranche` with `issues=[]`; broad mypy still reports no issues in 57
  broker/policy/execution/dataflow source files. Fresh overnight verifier
  `results\overnight_system_verification\overnight-system-verification-20260606-143651.json`
  is `overall_status=pass` with 3/3 original graph successes and 0 submissions.
  n8n job discovery now reports 20 allowlisted jobs and `submit_capable_count=0`;
  refreshed n8n evaluation dataset
  `results\n8n_evaluations\n8n-evaluation-dataset-20260606-204956-806412.json`
  has 183 rows, 20 jobs, 17 edge tags, and 23 columns. Fresh automation health
  `results\automation_health\automation-health-audit-20260606-193723.json`
  has no missing/stale/late/timeliness issues; only night-shift remains partial
  while patrol history fills in. Fresh source quality
  `results\source_quality\source-quality-review-20260606-193732.json` reviewed
  250 sources and found 238 stale, 75 stale-downranked, 65 blocked, and 0
  invalid; next-session research must refresh or downrank stale evidence before
  relying on it for trade decisions.
- 2026-06-06 top-symbol evidence refresh: the stale-source warning was followed
  by analysis-only `research ticker-provider-bundle --json-output` refreshes for
  current top overnight symbols `KO`, `IBM`, and `HD`. Each wrote 17 source
  packets and a medium-quality summary:
  `results\research_evidence\source-evidence-source-evidence-ec8d000296f048f2b8f30ddaa4c3a276.json`
  for `KO`,
  `results\research_evidence\source-evidence-source-evidence-955ee8e83ad144ce88eedd64ead3bbc6.json`
  for `IBM`, and
  `results\research_evidence\source-evidence-source-evidence-ead7e6ab12294983bc2e236a5cf16540.json`
  for `HD`. IBM's crawler leg hit SEC 403 after retries and was captured as
  blocked evidence, not silent success. Fresh source-quality review
  `results\source_quality\source-quality-review-20260606-194532.json` reduced
  stale sources from 238 to 186, raised fresh sources to 64, recorded 60
  stale-downranked and 71 blocked, and still has 0 invalid packets.
- 2026-06-06 P2 decision-quality reality check: real captured overnight
  outcomes were refreshed with
  `tradingagents research walk-forward-refresh-overnight-cohort --json-output`.
  Packet:
  `results\research_batches\walk_forward_cohort_refresh_20260606-195033_h3.json`.
  The run selected 12 mature overnight packets, skipped 5 not-yet-mature June
  4/5 packets, collected 140 later-return rows, generated 420 replay fixture
  rows, and met the replay sample floor. This is analysis-only with
  `execution_authority=none`.
- The cohort is a warning, not a promotion proof. `deterministic_sleeve_only`
  scored 420 rows with directional accuracy `0.3905`, false-positive rate
  `0.1690`, average Brier `0.2577`, and average action-relative return
  `-0.3781`. `tradingagents_advisory_overlay` scored only 11 rows with
  directional accuracy `0.4545`, false-positive rate `0.5455`, average Brier
  `0.2901`, and average action-relative return `-0.2109`. Official,
  news/social/crawler, and Deep Research overlays remain unavailable for this
  cohort. Morning agents must keep these overlays advisory until mature sample
  floors and calibration improve; do not convert this checkpoint into increased
  live influence.
- The same cohort now feeds `overnight_calibration_guard` in compact context and
  n8n. If the compact summary says `guard_decision=tighten`, do not increase
  live influence from overnight overlays; use the guardrails and open the raw
  packet only for schema/status drift or to inspect the red-flag list.
- 2026-06-06 ledger/model-route checkpoint: `research agent-ledger-update`,
  `research agent-ledger-summary`, `research model-telemetry-report`, and
  `research outcome-labeling` refreshed the evidence loop. The agent ledger has
  2,740 pending forecasts and 0 resolved forecasts, so all dynamic influence
  weights remain `insufficient_history` at `1.00`. Model telemetry packet
  `results\model_telemetry_reports\model-telemetry-report-20260606-195125-804423.json`
  shows current Mac helper success on `deepseek-r1:14b`, deterministic helper
  success, Codex/thread judgment fallback, Windows local Ollama still blocked
  because no Windows Ollama URL is configured, and 0 resolved model-run
  usefulness outcomes. Keep Codex/OpenAI as the judgment route, keep Mac
  DeepSeek as cheap helper work, and do not spend/promote paid model routes from
  this telemetry alone.
- Automation-health false positive fixed: date-only controller memories such as
  `Run time: 2026-06-04` now use the memory file write time as run evidence. Real
  proof: `results\automation_health\automation-health-audit-20260605-110115.json`.
- Remaining known controller risk: `tradingagents-night-shift-supervisor` still
  has stale memory from `2026-06-04T05:19:18+00:00`; this is a real missed patrol
  signal, not a repo verifier failure. Do not fake-fix it by editing
  `C:\cm\automations\tradingagents-night-shift-supervisor\memory.md`.
- Night-shift schedule repair: the controller remains ACTIVE and now patrols on
  the intended four-hour cadence instead of skipping the 8, 12, and 16 hour
  patrols. Real health proof after the app update:
  `results\automation_health\automation-health-audit-20260605-113550.json`.
  It still reports the last patrol as stale, which is correct until the native
  automation creates a fresh run.
- Night-shift cadence regression guard: automation health now emits
  `night_shift_cadence_mismatch` if the night-shift controller drifts away from
  the intended 0/4/8/12/16/20:15 all-days cadence. Focused proof:
  `tests/test_automation_health_audit.py` passed with 22 tests. Real post-guard
  proof `results\automation_health\automation-health-audit-20260605-114237.json`
  shows no cadence warning on the live automation config; only the real stale
  memory remains.
- Night-shift evidence packet repair: the controller prompt now runs
  `research night-shift-patrol --json-output`, which writes an analysis-only,
  no-order-authority packet under `results\night_shift_patrol\`. Real proof:
  `results\night_shift_patrol\night-shift-patrol-20260605-135243.json` and
  `results\automation_health\automation-health-audit-20260605-135301.json`,
  where night-shift moves from stale to partial with `actual_artifact_count=1`.
  Focused proof passed with 24 tests and the full suite passed with 899 tests,
  1 skipped live-key test, 9 warnings, and 75 subtests. Do not backfill old
  missed patrols; the next native runs should create fresh evidence on their
  normal cadence.
- Wake/sleep controller evidence repair: `research controller-patrol` now writes
  analysis-only controller evidence packets, and automation health consumes
  `results\control_plane_patrol\wake-controller-patrol-*.json` /
  `sleep-controller-patrol-*.json` alongside controller memory. Wake and sleep
  automation prompts were updated through the automation app to write these
  packets after status-only work. Real proof:
  `results\control_plane_patrol\wake-controller-patrol-20260605-143624.json`
  and `results\automation_health\automation-health-audit-20260605-143645.json`,
  where `tradingagents-automation-wake-controller` is `ok` with
  `actual_artifact_count=1`, global `stale_count=0`, and only night-shift remains
  partial because old missed patrols were not backfilled. Full-suite proof after
  this slice passed with 901 tests, 1 skipped live-key test, 9 warnings, and 75
  subtests.
- 2026-06-05 real department audit after cadence/live-budget repairs:
  `results\real_simulation_audits\real-simulation-audit-20260605-115602.json`
  covered 8 departments and 28 commands with `failed_command_count=0`,
  `total_submitted_order_count=0`, `unsafe_submission_evidence=false`,
  `all_structured_output_present=true`, `stale_sources_refreshed_or_downranked=true`,
  and `acceptance.accepted=true`. The Mac DeepSeek helper was unreachable from
  Windows/Tailscale during this run, so the packet records
  `optional_helper_degraded=true` and `strict_optional_model_accepted=false`;
  this degrades cheap helper capacity only and does not waive any order gate.
- 2026-06-05 final verification checkpoint: process review
  `results\process_reviews\process-review-20260605-153745.json` reports
  `unchecked_step_count=0`; compact context refresh now opens the hourly
  `loss-review`, `results\execution_board\latest.json`, and
  `results\automation_health\latest.json`. Full pytest passed with
  `903 passed, 1 skipped, 9 warnings, 75 subtests passed`.
- Quiet hourly run with `actions=[]`, `submitted=[]`, and a `ROUTINE` alert (or legacy `notify=false`) is valid.
- Hourly `decision=loss-review` with `actions=[]` and `submitted=[]` is a safety hold, not a broken run. Inspect `alert.problem`, BOARD packet refs, and thesis-break evidence before allowing a loss exit.
- BOARD `review_underperformers_before_new_buys` pauses new live buys only. It does not require selling losers, stop paper tournament tests, or block research.
- A real simulation audit must report `total_submitted_order_count=0`; market-closed status is not accepted as the safety control.
- Missing hourly `*-evidence.md` is not a failure when JSON is valid.
- Overnight CLI can exit nonzero while a fresh timestamped packet exists; inspect
  the packet before declaring failure.
- Overnight `latest.json` can lag a fresher timestamped production packet; the
  loader/verifier now ranks readable production packets by `generated_at` and
  skips explicit no-latest probes, so use the loader path before manual packet
  spelunking.
- Full graph ticker timeouts can be preserved through fallback rankings. Treat as
  graph/runtime evidence, not an order/account failure.
- Saved paper tournament JSON may omit `packet_path`; the CLI return can still be
  authoritative.
- Automation memory files can grow large. Read compact context first; the two
  largest memories were rolled up on 2026-06-07 with full originals archived
  under `results\token_efficiency\automation_memory_archives\`. Do not open raw
  archived memories unless investigating that automation's history.
- Overnight automation health can show multiple complete analysis-only packets
  in one expected window when Codex runs manual/proof reruns after the scheduled
  packet. If all such packets are zero-order, zero-issue, same trade date,
  complete, and graph-failure-free, health de-noises them as benign while
  preserving packet counts and paths. Treat that as visibility, not a scheduler
  blocker.
- 2026-06-07 source-routing compact context now distinguishes static route
  coverage from real provider-bundle evidence gaps and whether those bundles
  cover the current overnight targets. Static
  `results\_context\source-routing-compact.json` can correctly show
  `gap_count=0` and `coverage_count=3`, while recent provider bundles set
  `recent_provider_target_symbols_with_bundle=["XOM","CVX","ADBE"]`,
  `recent_provider_target_symbols_missing_bundle=[]`, and
  `recent_provider_target_evidence_needs_without_non_gap_packets=["earnings_transcripts"]`.
  Compact flags still include `source_routing`, but now for a true evidence
  quality gap rather than missing top-candidate coverage. Morning research
  should refresh/downrank transcript-sensitive claims before relying on them.

## Context Loading Policy

Use full context when changing shared execution, broker safety, packet schemas,
automation schedules/models, or test contracts. Read the relevant source files,
focused tests, and the active automation TOMLs.

Use delta-only context for routine automation runs, daily reports, and status
checks. Run `python scripts/automation_context_snapshot.py --write`, inspect
`results/_context/latest-summary.json`, `latest-flags.json`, and
`recent-deltas.md`, then open only the latest packet or failed ticker summary if
needed.

Open raw packets when any of these appear: blockers, submitted actions, issues,
changed live candidate, stale data, failed graph runs, changed tournament leader,
schema mismatch, or unexplained P/L/action changes.

Keep out of persistent context: full packet bodies, raw stdout, whole test output,
entire automation memories, old timestamped reports, full lock files, images,
`.venv/`, caches, and future-methodology specs unless the task is about them.

## Chat Reporting Contract

Routine automation replies:

- status
- packet path(s)
- top candidate or decision
- `submitted` / `notify`
- blockers only if present
- next file to inspect if the next session continues

Deep investigations should save detail in a repo doc or packet and give chat a
short pointer.

## Latest Tail Pointer, 2026-06-07 21:13 UTC

- Claude submit-path handoff remains prepared: branch
  `wip/submit-path-hardening-2026-06-05`, commit `3970998` is still only the
  standalone order-rate-limit module/test, and SAFE-01 remains fail-closed in
  local machine state. Do not refresh the live dead-man or stage the shared
  dirty submit-path edits without explicit operator review.
- `alpaca plan-overnight` now refreshes analysis-only provider bundles for the
  top ranked overnight candidates by default via `--top-provider-bundle-count`
  (default `3`; use `0` for probes/tests). The packet stores compact
  `top_provider_bundles` paths/counts only; raw evidence stays in
  `results\research_evidence\`.
- Real no-latest probe:
  `results\overnight_plans\top_provider_bundle_probe\overnight-plan-20260607-210455-000000.json`
  produced `submitted_count=0`, top candidate `XOM`, one provider bundle, 7
  source packets, and `execution_authority=none`.
- Compact source-routing now writes the same fresh provider overlay to
  `results\_context\source-routing-compact.json` that appears in
  `latest-summary.json`. Current target coverage:
  `recent_provider_target_symbols_with_bundle=["XOM","CVX","ADBE"]`,
  `recent_provider_target_symbols_missing_bundle=[]`; the only target
  non-gap evidence weakness remains `earnings_transcripts`.
- Verification: overnight CLI slice `14 passed`, provider/context slice
  `104 passed`, source-routing overlay slice `2 passed`, targeted Ruff passed,
  and process review
  `results\process_reviews\process-review-20260607-211322.json` reports
  `unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.

## Latest Tail Pointer, 2026-06-07 21:45 UTC

- Claude submit-path handoff is still prepared and SAFE-01 remains fail-closed:
  local live caps are armed, the live-control dead-man is lapsed, and no live
  authority was changed in this slice.
- The `earnings_transcripts` provider gap now has a local-unlimited Docker MCP
  route before FMP: `tradingagents.research.youtube_transcript` discovers
  plausible YouTube earnings-call videos and calls
  `youtube_transcript__get_transcript` through Docker MCP. Valid transcript text
  writes a medium-quality, read-only `youtube_transcript` evidence packet;
  discovery/tool failures still fall through to FMP and then the explicit
  `earnings_transcripts_gap`.
- Real transcript proof:
  `.\.venv\Scripts\tradingagents.exe research ticker-provider-bundle --symbol XOM --evidence-needs earnings_transcripts --max-packets-per-need 1 --output-dir results\research_evidence\youtube_transcript_probe --cache-dir results\research_provider_cache\youtube_transcript_probe --json-output`
  wrote
  `results\research_evidence\youtube_transcript_probe\source-evidence-source-evidence-107cb2c1d5bf4cf9b6c71c1e3af1cd78.json`
  plus summary
  `results\research_evidence\youtube_transcript_probe\source-evidence-source-evidence-e4c80ea7e67e457cb29e5fb2be8ab63a.json`;
  route attempts were `official_cache` cache miss then `youtube_transcript`
  packet written, with `unsupported_route_count=0`, `blocked_packet_attempt_count=0`,
  `gap_packet_count=0`, and no missing non-gap needs.
- Real overnight proof:
  `results\overnight_plans\youtube_transcript_probe\overnight-plan-20260607-214130-000000.json`
  produced top candidate `XOM`, `submitted_count=0`,
  `execution_authority=none`, `top_provider_bundle_error_count=0`, and
  `top_provider_bundle_missing_non_gap_needs=[]`.
- Verification: `tests/test_youtube_transcript_bridge.py` plus full provider
  orchestrator tests -> `34 passed`; overnight CLI slice
  `tests/test_alpaca_cli.py -k "plan_overnight or compact_overnight"` ->
  `14 passed, 82 deselected`; targeted Ruff passed. Refresh compact context
  before relying on target overlays.

Follow-up at 2026-06-07 21:55 UTC: compact source-routing now evaluates target
coverage from the latest provider bundle per symbol, so older stale XOM/CVX/ADBE
bundles no longer keep a refreshed target falsely flagged. Fresh CVX and ADBE
provider bundles both wrote non-gap `youtube_transcript` packets plus cached
short-interest/options evidence:
`results\research_evidence\source-evidence-source-evidence-43183b7d0f874a08bf384074a682e438.json`
for CVX and
`results\research_evidence\source-evidence-source-evidence-fd80a8881c8c4e309cff9f6855424eb3.json`
for ADBE. After `python scripts\automation_context_snapshot.py --write`,
`results\_context\source-routing-compact.json` reports
`recent_provider_target_symbols_with_bundle=["XOM","CVX","ADBE"]`,
`recent_provider_target_symbols_missing_bundle=[]`,
`recent_provider_target_symbols_with_missing_non_gap=[]`, and
`recent_provider_target_evidence_needs_without_non_gap_packets=[]`; `source_routing`
is no longer in `latest-flags.json`. Process review
`results\process_reviews\process-review-20260607-215353.json` reports
`unchecked_step_count=0`, `findings=[]`, `can_submit_orders=false`.
