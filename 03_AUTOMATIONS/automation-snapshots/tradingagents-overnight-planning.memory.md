# TradingAgents Overnight Planning Automation Memory

## 2026-06-19 02:53:01 -05:00

- Ran the required bounded, analysis-only overnight planning sequence after
  refreshing compact context. The explicit system `python
  scripts/automation_context_snapshot.py --write` failed with
  `ModuleNotFoundError: No module named 'tradingagents'`; reran the same helper
  successfully through the repo venv Python and refreshed compact context again
  after packet generation.
- Initial compact context flagged the prior overnight packet as stale for the
  June 19 trade date and as having graph failures. Separate hourly/BOARD,
  preopen, n8n, automation-health, execution-board, and loss-review flags were
  present but were not overnight blockers. No raw order action was taken.
- `alpaca check` through the repo executable passed: paper ACTIVE with buying
  power 357330.96 / equity 97763.6; live ACTIVE with buying power 86.38 /
  equity 199.5.
- Research orchestration succeeded:
  `results\research_batches\research-batch-research-batch-d115fa7c761b4f4f9b234ccc05c42dc8.json`.
  Windows local/deterministic lanes were usable. Mac Ollama was optional and
  blocked by DNS/host lookup (`getaddrinfo failed`), not a blocker for the
  analysis-only run.
- Refreshed source-quality review:
  `results\source_quality\source-quality-review-20260619-073504.json`.
  Result: source_count 250, stale_count 244, stale_downrank_count 56,
  stale_needs_refresh_count 0, unreadable_count 0, missing_or_invalid_count 0,
  blocked_count 50.
- Agent Intelligence Ledger resolve/summary completed. Resolve marked 4732
  forecasts newly resolved, raising resolved_forecast_count to 4864. After the
  overnight run, summary showed forecast_count 4944, resolved_forecast_count
  4864, pending 80. Earned influence weights are advisory only and cannot bypass
  risk gates.
- Overnight planner packet:
  `results\overnight_plans\overnight-plan-20260619-073832-000000.json`.
  Result: analysis_only true, submitted_count 0, top candidates JPM, JNJ, XOM,
  CVX, COST; ranked_count 40; full_graph_attempt_count 3,
  full_graph_success_count 0, graph_failure_count 3, fallback_count 40,
  research_context_packet_count 15, research_context_blocked_count 0. Graph
  config was compact Google with quick model `gemini-2.5-flash-lite`, deep model
  `gemini-2.5-flash`, max_completion_tokens 220, source-quality ordering enabled
  via `results\source_quality\latest.json`.
- Full graph failed for JPM, JNJ, and XOM with the same message-deletion error
  class: `Attempting to delete a message with an ID that doesn't exist`. Each
  symbol was preserved through market snapshot fallback scoring. The packet is
  premarket-readable but the original TradingAgents graph lane did not succeed.
- Optional StockTwits/Reddit public HTTP 403 warnings appeared during graph
  collection for JPM, JNJ, and XOM. They were recorded as optional-source limits
  and did not block packet generation.
- Ran explicit ticker provider bundles for top candidates JPM, JNJ, and XOM.
  Summary packets: `results\research_evidence\source-evidence-source-evidence-2a844813b0c94669be2aeb26fea171bb.json`
  for JPM, `results\research_evidence\source-evidence-source-evidence-e0a9d519dee3486aa66891d0d76a0551.json`
  for JNJ, and `results\research_evidence\source-evidence-source-evidence-9f1f4e65950549be82872bd817616938.json`
  for XOM. JPM and JNJ each wrote 16 packets and still lacked a non-gap
  earnings_transcripts packet; XOM wrote 18 packets with no missing non-gap
  needs. Depleted sources were empty. Limited/paid/unsupported routes were
  recorded while Alpaca News, broker snapshot, yfinance, SEC/official cache,
  Google News RSS or local/cache routes, Reddit watchlist, and Crawlee continued.
- Refreshed premarket brief:
  `results\premarket_briefs\premarket-brief-20260619-075131-000000.json`.
  Result: analysis_only true, top symbol JPM, latest overnight generated_at
  2026-06-19T02:38:32-05:00, source_packet_count 54, unresolved_blockers 0,
  stale_warnings 0, material change: top symbol changed from CVX to JPM.
- Final compact context refresh completed. Remaining overnight flag is graph
  failure; separate BOARD/loss-review, preopen stale, n8n audit,
  automation-health, connector-health, and source-routing flags remain as
  non-order context for their own lanes.
- No live or paper orders were submitted. No email was sent because both the
  overnight packet and premarket brief were produced and account/data/model
  checks were not hard-blocked for this analysis-only run.
- Current run time at memory update: 2026-06-19 02:53:01 -05:00.

## 2026-06-11 01:00:08 -05:00

- Ran the required bounded, analysis-only overnight planning sequence after
  refreshing compact context. System `python scripts/automation_context_snapshot.py
  --write` again failed because system Python could not import `tradingagents`;
  reran the helper successfully through the repo venv Python and refreshed
  compact context again after packet generation.
- Initial compact context flagged the prior overnight packet as stale for the
  June 11 trade date and as having graph failures. It also had non-overnight
  BOARD/self-heal/preopen/n8n flags. No raw order action was taken.
- `alpaca check` through the repo executable passed: paper ACTIVE with buying
  power 355665.03 / equity 97168.62; live ACTIVE with buying power 86.38 /
  equity 197.83.
- Research orchestration succeeded:
  `results\research_batches\research-batch-research-batch-7ec1b80e4fe94eb8ae94c9ddda12a7db.json`.
  Deterministic helpers and Codex judgment were usable. Windows local Ollama was
  blocked by missing URL config and Mac Ollama timed out; both were optional
  degraded helper lanes, not blockers for the analysis-only packet.
- Refreshed source-quality review:
  `results\source_quality\source-quality-review-20260611-055159.json`.
  Result: source_count 250, stale_count 241, stale_downrank_count 54,
  stale_needs_refresh_count 0, unreadable_count 0, missing_or_invalid_count 0,
  blocked_count 50.
- Agent Intelligence Ledger resolve/summary completed. Forecast count increased
  from 4784 to 4864 after the overnight run; newly_resolved_count was 0 and
  resolved_forecast_count stayed 132. Earned influence weights remained
  advisory only and cannot bypass risk gates.
- Overnight planner packet:
  `results\overnight_plans\overnight-plan-20260611-055506-000000.json`.
  Result: analysis_only true, submitted_count 0, top candidates CVX, XOM, ORCL,
  IBM, WMT; full_graph_attempt_count 3, full_graph_success_count 0,
  graph_failure_count 3, fallback_count 40, ranked_count 40,
  research_context_packet_count 15, research_context_blocked_count 0. Graph
  config was compact Google with quick model `gemini-2.5-flash-lite`, deep model
  `gemini-2.5-flash`, max_completion_tokens 220, source-quality ordering enabled
  via `results\source_quality\latest.json`.
- Full graph failed for CVX, XOM, and ORCL with transient graph errors:
  `Attempting to delete a message with an ID that doesn't exist`. Each symbol
  was preserved through market snapshot fallback scoring. The packet is
  premarket-readable but the original TradingAgents graph lane did not succeed.
- Optional StockTwits/Reddit public HTTP 403 warnings appeared for CVX, XOM, and
  ORCL during graph/source collection. They were recorded as optional-source
  limits and did not block packet generation.
- Ran ticker provider bundles for top candidates CVX, XOM, and ORCL. Summary
  packets: `results\research_evidence\source-evidence-source-evidence-894b7dd82e9648cfb4714412a8a7dcd6.json`
  for CVX, `results\research_evidence\source-evidence-source-evidence-d4c96207ea37416e97e74ca1facfdfc0.json`
  for XOM, and `results\research_evidence\source-evidence-source-evidence-20a538181845494fad5c5f0043313518.json`
  for ORCL. Each wrote 18 analysis-only packets. Depleted sources were empty.
  Paid/limited/unsupported routes and gap packets were recorded while Alpaca
  News, broker snapshot, yfinance, SEC/official cache, YouTube transcript, local
  crawler, Reddit watchlist, and other free/cache routes continued.
- Refreshed premarket brief:
  `results\premarket_briefs\premarket-brief-20260611-055852-000000.json`.
  Result: analysis_only true, top symbol CVX, latest overnight generated_at
  2026-06-11T05:55:06+00:00, source_packet_count 54, unresolved_blockers 0,
  stale_warnings 0, material change: top symbol changed from HD to CVX.
- Final compact context refresh completed. Remaining flags are overnight graph
  failure plus separate hourly/BOARD, preopen stale, n8n audit, self-heal, and
  loss-review context flags.
- No live or paper orders were submitted. No email was sent because both the
  overnight packet and premarket brief were produced and account/data/model
  checks were not hard-blocked for this analysis-only run.
- Current run time at memory update: 2026-06-11 01:00:08 -05:00.

## 2026-06-09 02:51:50 -05:00

- Ran the required bounded, analysis-only overnight planning sequence after
  refreshing compact context. System `python scripts/automation_context_snapshot.py
  --write` failed because system Python could not import `tradingagents`; reran
  the same helper successfully through the repo venv Python and refreshed compact
  context again after the packets were written.
- Initial compact context flagged the prior overnight packet as stale for the
  June 9 trade date and the prior research batch as partial/quality-drilldown.
- `alpaca check` through the repo executable passed: paper ACTIVE with buying
  power 359394.99 / equity 98500.75; live ACTIVE with buying power 86.38 /
  equity 199.31.
- Research orchestration succeeded:
  `results\research_batches\research-batch-research-batch-d37c36be7ead4961b4163f83fe967304.json`.
  Windows local Ollama and deterministic helpers were usable. Mac Ollama timed
  out and was skipped as an optional degraded helper, not a blocker.
- Refreshed source-quality review:
  `results\source_quality\source-quality-review-20260609-073712.json`.
  Result: source_count 250, stale_count 199, stale_downrank_count 40,
  stale_needs_refresh_count 0, unreadable_count 0, missing_or_invalid_count 0,
  blocked_count 42.
- Agent Intelligence Ledger resolve/summary completed. Forecast count increased
  from 4704 to 4784 after the overnight run; resolved_count remained 0, so all
  agent influence weights stayed neutral at 1.00.
- Overnight planner packet:
  `results\overnight_plans\overnight-plan-20260609-074022-000000.json`.
  Result: analysis_only true, submitted_count 0, top candidates HD, IBM, V,
  MA, PG; full_graph_attempt_count 3, full_graph_success_count 0,
  graph_failure_count 3, fallback_count 40, research_context_packet_count 14,
  research_context_blocked_count 0. Graph config was compact Google with quick
  model `gemini-2.5-flash-lite`, deep model `gemini-2.5-flash`,
  max_completion_tokens 220, source-quality ordering enabled via
  `results\source_quality\latest.json`.
- Full graph failed for HD, IBM, and V with `contents are required`; each symbol
  was preserved through `market_snapshot_fallback` scoring. This produced a
  premarket-readable fallback-ranked packet, but the original TradingAgents
  graph lane did not succeed this run.
- Optional StockTwits/Reddit public HTTP 403 warnings appeared for HD, IBM, and
  V during graph/source collection. They were recorded as optional-source limits
  and did not block packet generation.
- Ran ticker provider bundles for top candidates HD, IBM, and V. Summary packets:
  `results\research_evidence\source-evidence-source-evidence-e8ee5f5a882846b7b7fe5267df252cfa.json`
  for HD,
  `results\research_evidence\source-evidence-source-evidence-22543feffae74eccb230260280325d60.json`
  for IBM, and
  `results\research_evidence\source-evidence-source-evidence-9c0045c056374effbaed7f0670a0b23e.json`
  for V. HD wrote 17 packets; IBM and V wrote 18 each. Depleted sources were
  empty. Paid/limited/unsupported routes and gap packets were recorded while
  free/local/read-only sources continued. HD had `crawler_research` as the only
  missing non-gap need.
- Refreshed premarket brief:
  `results\premarket_briefs\premarket-brief-20260609-074839-000000.json`.
  Result: analysis_only true, top symbol HD, latest overnight generated_at
  2026-06-09T02:40:22-05:00, source_packet_count 54, unresolved_blockers 0,
  stale_warnings 0, material change: top symbol changed from XOM to HD.
- No live or paper orders were submitted. No email was sent because both the
  overnight packet and premarket brief were produced and account/data/model
  checks were not hard-blocked, though graph quality needs follow-up.
- Current run time at memory update: 2026-06-09 02:51:50 -05:00.

## 2026-06-07 02:55:09 -05:00

- Ran the required bounded, analysis-only overnight planning sequence after the
  weekend/closed-market compact context refresh.
- Refreshed compact context first. Overnight/premarket/source-quality/model
  runtime were not flagged as blocked. Separate non-overnight flags remained for
  TSM loss-review BOARD context only; no order action was taken.
- `alpaca check` through the repo executable passed: paper ACTIVE with buying
  power 358827.89 / equity 98298.21; live ACTIVE with buying power 86.38 /
  equity 198.69.
- Research orchestration succeeded:
  `results\research_batches\research-batch-research-batch-a40c2d736a4642049cdbeb2823d023a7.json`.
  Deterministic helpers and Windows local Ollama were usable. Mac Ollama timed
  out and was treated as an optional degraded helper, not a blocker.
- Refreshed source-quality review:
  `results\source_quality\source-quality-review-20260607-073615.json`.
  Result: source_count 250, stale_count 23, stale_downrank_count 11,
  stale_needs_refresh_count 0, missing_or_invalid_count 0, unreadable_count 0,
  blocked_count 21.
- Agent Intelligence Ledger resolve/summary completed. Forecast count increased
  to 3834 after the overnight run; resolved_count remained 0, so all agent
  influence weights stayed neutral at 1.00.
- Overnight planner packet:
  `results\overnight_plans\overnight-plan-20260607-074858-000000.json`.
  Result: analysis_only true, submitted_count 0, top candidates CVX, ADBE, BAC,
  CRM, XOM; full_graph_attempt_count 3, full_graph_success_count 3,
  fallback_count 37, graph_failure_count 0, research_context_packet_count 14,
  research_context_blocked_count 0. Graph config was compact Google with
  quick model `gemini-2.5-flash-lite`, deep model `gemini-2.5-flash`,
  max_completion_tokens 220, source-quality ordering enabled via
  `results\source_quality\latest.json`.
- Optional StockTwits/Reddit public HTTP 403 warnings appeared for XOM, ADBE,
  and CVX during graph/source collection. They were recorded as optional-source
  limits and did not block packet generation.
- Ran ticker provider bundles for top candidates CVX, ADBE, and BAC. Each wrote
  16 analysis-only packets plus a summary packet. Summary packets:
  `results\research_evidence\source-evidence-source-evidence-7c4044d960644b39960a3759c1b075fb.json`
  for CVX,
  `results\research_evidence\source-evidence-source-evidence-04943aebff914d6eb167ecb3766156c5.json`
  for ADBE, and
  `results\research_evidence\source-evidence-source-evidence-2fa5e190d90a4f6180b7a62a9245cd5f.json`
  for BAC. Depleted sources were empty; missing-key/unsupported limited or paid
  routes were captured while official cache, Google News RSS, Alpha Vantage,
  yfinance, SEC/official, Reddit watchlist, and Crawlee continued.
- Refreshed premarket brief:
  `results\premarket_briefs\premarket-brief-20260607-075322-000000.json`.
  Result: analysis_only true, top symbol CVX, source_packet_count 54,
  unresolved_blockers 0, stale_warnings 0, material change: top symbol changed
  from XOM to CVX.
- Refreshed compact context after the run. Final `latest-flags.json` only kept
  the separate TSM loss-review BOARD context flags; the Agent Intelligence schema
  flag cleared after ledger refresh.
- No live or paper orders were submitted. No email was sent because both the
  overnight packet and premarket brief were produced and checks were not blocked.
- Current run time at memory update: 2026-06-07 02:55:09 -05:00.

## 2026-06-04 14:50:00 -05:00

- Follow-up crawler-provider repair after the KO/HD/AMD provider-route slice.
- Default ticker provider bundles now include a separate `crawler_research`
  evidence need. This keeps Crawlee from crowding out Google/Alpaca market-news
  packets while still adding local/unlimited browser research when available.
- `crawlee` now uses deterministic ticker-to-target policies only. The current
  ticker target is the static SEC company endpoint allowlisted to `sec.gov`;
  arbitrary ticker-derived web crawling is still not allowed.
- Real runtime issue found and repaired: Crawlee and Playwright were importable,
  but the venv had a broken `greenlet` install (`greenlet.greenlet` missing).
  Ran:
  `uv pip install --python .\.venv\Scripts\python.exe --reinstall greenlet==3.2.3`.
  After repair, `greenlet` imports from the repo venv with version `3.2.3`.
- Runtime doctor now checks `greenlet_available`, so this class of broken
  dependency becomes a self-healable runtime issue before the first crawl.
- Real no-order default Crawlee provider proof for `KO`:
  summary packet
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\research_evidence\source-evidence-source-evidence-936ac99338724c81ace3517511764085.json`;
  source packet
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\research_evidence\source-evidence-source-evidence-090551d446f04343b05a16cc96028bac.json`.
  Result: default evidence needs
  `market_news,quote_price_context,fundamentals_profile,crawler_research`,
  `crawler_status=success`, `quality=medium`, fetched one allowlisted SEC URL,
  title `EDGAR Search Results`, `blocked=false`,
  `execution_authority=none`.
- Refreshed source-quality review:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\source_quality\source-quality-review-20260604-200123.json`
  Result: source_count 250, stale_count 43, stale_downrank_count 43,
  stale_needs_refresh_count 0.
- Refreshed compact context after the crawler repair. Current drilldowns remain
  paper tournament candidate change and MiroFish handoff status only, not
  overnight breakage.
- No live or paper orders were submitted. No email was sent.

## 2026-06-04 14:25:00 -05:00

- Follow-up provider-route repair after the successful Google overnight run.
- Local ticker provider bundles now support the previously missing
  high-leverage free/local routes: `official_cache`, `yfinance`,
  `sec_edgar`, and `reddit_watchlist`.
- Real no-order ticker bundles for `KO`, `HD`, and `AMD` each wrote 12
  analysis-only packets covering `official_cache`, `reddit_watchlist`,
  `alpaca_news`, `google_news_rss`, `yfinance`, `sec_edgar`, `finnhub`,
  `tiingo`, and `fmp`.
- Proof packets:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\research_evidence\source-evidence-source-evidence-32051257a7b14911a6be98bdb6f1fdf0.json`
  for `KO`;
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\research_evidence\source-evidence-source-evidence-61eacab2639b45c7ac2cf08043168f7a.json`
  for `HD`;
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\research_evidence\source-evidence-source-evidence-060370eae0f843579b45cc4e6e47ce17.json`
  for `AMD`.
- Remaining unsupported routes are intentional: `broker_snapshot` should be read
  from sanitized account/supervisor packets, generic `crawlee` still needs a
  ticker-to-target allowlist, and account-backed reddit/twitter stay skipped
  until authenticated connectors are present.
- Refreshed source-quality review:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\source_quality\source-quality-review-20260604-192516.json`
  Result: source_count 250, stale_count 59, stale_downrank_count 59,
  stale_needs_refresh_count 0.
- Refreshed compact context after the provider rerun. Current drilldowns remain
  paper tournament candidate change and MiroFish handoff status only, not
  overnight breakage.
- No live or paper orders were submitted. No email was sent.

## 2026-06-04 13:55:00 -05:00

- Follow-up real run after the Google route repair proved the original
  TradingAgents graph lane is healthy again.
- Restored the missing repo console script by running `uv pip install -e .`;
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe --help`
  now opens the CLI successfully.
- Ran full overnight planner through the repo executable with explicit Google
  graph routing:
  `alpaca plan-overnight --json-output --log-dir results/overnight_plans --overnight-graph-profile compact --overnight-llm-provider google --overnight-quick-think-llm gemini-2.5-flash-lite --overnight-deep-think-llm gemini-2.5-flash --full-graph-tickers 3 --per-ticker-timeout-minutes 25 --time-budget-minutes 90 --overnight-max-completion-tokens 220`.
- Overnight packet:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\overnight_plans\overnight-plan-20260604-184407-000000.json`
  Result: analysis_only true, submitted_count 0, top candidates KO, HD, AMD,
  TXN, PEP; `full_graph_attempt_count=3`, `full_graph_success_count=3`,
  `fallback_count=32`, `graph_failure_count=0`, `research_context_packet_count=13`.
- Successful original-graph creator workflow packets were written for KO, HD,
  and AMD under `results\overnight_plans\agent_runs\...\creator_workflow_packet.json`.
- Ran ticker provider bundles for KO, HD, and AMD. Each wrote 9 analysis-only
  packets. Alpaca News and Google News RSS contributed; local orchestrator
  support is still missing for broker snapshot, yfinance, SEC, local cache,
  social, and crawler routes. Finnhub/FMP/Tiingo packet paths exist but still
  need API-key/provider cleanup where marked blocked or unknown.
- Refreshed premarket brief:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\premarket_briefs\premarket-brief-20260604-185159-000000.json`
  Result: analysis_only true, top symbol KO, latest overnight generated_at
  2026-06-04T18:44:07+00:00, stale_warnings 0, unresolved_blockers 0.
- Verified overnight system:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\overnight_system_verification\overnight-system-verification-20260604-140301.json`
  Result: overall_status pass; original graph execution pass; premarket top KO.
- Ran `research source-quality-review --json-output`:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\source_quality\source-quality-review-20260604-185206.json`
  Result: source_count 250, stale_count 95, stale_downrank_count 95,
  stale_needs_refresh_count 0.
- Refreshed compact context. Current drilldowns are paper tournament candidate
  change and MiroFish handoff status only, not overnight breakage.
- No live or paper orders were submitted. No email was sent because all
  analysis-only packets were produced and checks were not blocked.

## 2026-06-04 07:45:13 -05:00

- Manual morning refresh run by Codex because compact context showed stale overnight verification while the scheduled overnight automation was `PAUSED` by the wake/sleep controller state.
- Ran direct repo executable precheck:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe alpaca check`
  Result: paper ACTIVE, live ACTIVE; live buying power was 86.38 and live equity was 199.41.
- Refreshed research orchestration:
  `research automation-orchestration-plan --json-output --output-dir results/research_batches --model-telemetry-dir results/model_telemetry --research-context-dir results/research_evidence/orchestration_context`
  Result: success, analysis_only true, Mac `deepseek-r1:14b` helper selected, Windows local Ollama skipped as non-blocking, quality gates passed, blockers empty.
- Resolved/summarized Agent Intelligence Ledger:
  `research agent-ledger-resolve --json-output` and `research agent-ledger-summary --json-output`
  Result: 1183 pending forecasts, 0 resolved, all influence weights still 1.00 due to insufficient resolved history.
- Ran fresh bounded overnight planner:
  `alpaca plan-overnight --json-output --compact-json-output --log-dir results/overnight_plans --overnight-graph-profile compact --full-graph-tickers 3 --per-ticker-timeout-minutes 25 --time-budget-minutes 90 --overnight-max-completion-tokens 220`
  Result: completed successfully, analysis_only true, submitted_count 0.
- Overnight packet:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\overnight_plans\overnight-plan-20260604-124300-000000.json`
  Top candidates: AMZN, TSM, GOOGL. Quality: full_graph_count 0, fallback_count 35, graph_failure_count 0, research_context_packet_count 13. Full graph was intentionally disabled because Mac DeepSeek is configured as a cheap helper lane, not the primary full-debate graph.
- Ran ticker provider bundles for AMZN, TSM, and GOOGL. Each wrote 9 analysis-only packets. Alpaca News and Google News contributed; Finnhub/FMP/Tiingo missing-key or blocked states were recorded without stopping the workflow.
- Refreshed premarket brief:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\premarket_briefs\premarket-brief-20260604-124421-000000.json`
  Result: analysis_only true, top symbol AMZN, latest overnight generated_at 2026-06-04T12:43:00+00:00, stale_warnings 0, unresolved_blockers 0.
- Verified overnight system:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\overnight_system_verification\overnight-system-verification-20260604-074446.json`
  Result: overall_status pass; simulated_preopen_validation confirmed AMZN for overnight, premarket, and fresh candidate ranking.
- Refreshed compact context and automation health after the run. Remaining compact flags were paper tournament candidate change and MiroFish handoff drilldown only. Automation health was clean with 13 ok, 0 submitted orders, and 0 issues.
- No live or paper orders were submitted. No email was sent because all analysis-only packets were produced and checks were not blocked.

## 2026-05-31 15:06:49 -05:00

- First recorded run for automation `tradingagents-overnight-planning`.
- Read initial automation memory: file was missing before this run.
- Ran direct repo executable precheck:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe alpaca check`
  Result: paper ACTIVE, live ACTIVE.
- Ran direct repo executable overnight planner:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe alpaca plan-overnight --json-output --log-dir results/overnight_plans`
  Result: blocked/stopped after roughly 30+ minutes. No `overnight-plan-*.json` packet was produced. The only completed ticker report was AAPL and it failed with LangGraph recursion limit 100.
- Partial overnight artifact:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\overnight_plans\ticker_reports\AAPL\summary.json`
- Refreshed premarket brief despite missing overnight packet:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\premarket_briefs\premarket-brief-20260531-200342.json`
  Latest rolling packet immediately after inspection:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\premarket_briefs\premarket-brief-20260531-200346.json`
- Premarket brief status: `analysis_only: true`, top symbol `MSFT`, latest hourly decision `profit-review`, stale warning `No overnight plan packet was found for the rolling premarket brief.`
- Read-only universe reconstruction after the blocked run: 67 candidate symbols, 38 tradable, 29 rejected. This was reconstructed separately because no overnight packet existed.
- Sent blocked-run email to `nebulazer2003@gmail.com` via Gmail; sent message id `19e7fa3208a021ae`.
- No live or paper orders were submitted.

## 2026-05-31 16:39:37 -05:00

- Ran required direct repo executable precheck:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe alpaca check`
  Result: paper ACTIVE, live ACTIVE.
- Ran bounded overnight planner with:
  `alpaca plan-overnight --json-output --log-dir results/overnight_plans --full-graph-tickers 3 --per-ticker-timeout-minutes 5 --time-budget-minutes 25`
  Result: completed successfully, analysis_only true, submitted empty.
- Overnight packet:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\overnight_plans\overnight-plan-20260531-213728.json`
  Universe: 35 candidate / 35 tradable / 35 ranked / 0 rejected. Top candidates: ORCL, NOW, MSFT, IBM, CRM. Full graph count 3; fallback count 35; graph failure count 3. The graph failures were converted to fallback rankings for ADBE, AVGO, and CRM; CRM emitted Reddit HTTP 403 warnings.
- Refreshed premarket brief:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\premarket_briefs\premarket-brief-20260531-213745.json`
  Result: analysis_only true, top symbol ORCL, unresolved blockers 0, stale warnings 0, material change category no_material_change.
- No live or paper orders were submitted. No email was sent because both packets were produced and account/data/model checks were not blocked.

## 2026-06-04 13:20:40 -05:00

- Overnight planner route repair: the automation prompt now runs `alpaca plan-overnight` with explicit Google graph routing:
  `--overnight-llm-provider google --overnight-quick-think-llm gemini-2.5-flash-lite --overnight-deep-think-llm gemini-2.5-flash`.
- Repo patch: explicit non-Ollama overnight routes no longer inherit local/Ollama backend URLs and are not disabled by the Windows Ollama probe. Mac `deepseek-r1:14b` stays helper-only for source triage / stale-source summaries / contradiction hunting / cleanup / compression.
- Quality semantics patch: overnight packets now distinguish `full_graph_attempt_count` from `full_graph_success_count`; verification should treat the original graph lane as healthy only when `full_graph_success_count > 0`.
- OpenAI no-write probe:
  `results\overnight_plans\openai_graph_probe\overnight-plan-20260604-182040-000000.json`
  Result: analysis_only true, submitted 0, `full_graph_attempt_count=1`, `full_graph_success_count=0`, `graph_failure_count=1`; OpenAI key is blank/missing in this process.
- Google no-write probe:
  `results\overnight_plans\google_graph_probe\overnight-plan-20260604-182923-000000.json`
  Result: analysis_only true, submitted 0, `full_graph_attempt_count=1`, `full_graph_success_count=1`, `graph_failure_count=0`; top candidate AMD came from `method=full_graph`.

## 2026-06-02 03:18:03 -05:00

- Ran required direct repo executable precheck:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe alpaca check`
  Result: paper ACTIVE, live ACTIVE.
- Built research orchestration packet:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\research_batches\research-batch-research-batch-1c8e0d84f0e347a08be94f013f1349ca.json`
  Result: success, analysis_only true, deterministic helpers ready, source breadth ready, fallback_required false. Windows local and Mac Ollama lanes were blocked/not configured but non-critical for packet production.
- Resolved due Agent Intelligence Ledger forecasts before ranking:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\agent_intelligence\summary.json`
  Result: no newly resolved forecasts before the overnight planner.
- Ran required bounded overnight planner command with compact graph profile, 3 full-graph tickers, 25-minute per-ticker timeout, 90-minute budget, and 220 max completion tokens.
  Result: completed successfully with exit code 0; analysis_only true; submitted empty.
- Overnight packet:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\overnight_plans\overnight-plan-20260602-081259-000000.json`
  Validation: analysis_only true, submitted: [], 35 candidate / 35 ranked, top candidates NOW, IBM, CRM, ADBE, TSM.
  Quality: full_graph_count 3, fallback_count 32, graph_failure_count 0. Graph config compact, tool-free market/social/news/fundamentals, Ollama model `tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k`, backend `http://localhost:11434/v1`, max_completion_tokens 220.
- Observed non-blocking social-source warnings during planner stdout: Reddit HTTP 403 for TSM, ORCL, and NVDA. These did not block packet generation and no graph failures were recorded.
- Ran provider bundles for top three candidates:
  NOW: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\research_evidence\source-evidence-source-evidence-30a85a76bf394f338da5bc6039629bce.json`
  IBM: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\research_evidence\source-evidence-source-evidence-2eb2c4433cd24280be0964661bf169a0.json`
  CRM: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\research_evidence\source-evidence-source-evidence-3e0b139f87d84a7197970ac8a1443a79.json`
  Result: each produced 9 analysis-only packets. NOW first attempt hit a transient Windows `latest.json` PermissionError and succeeded on retry. Provider limitations recorded: FINNHUB_API_KEY missing, FMP blocked, EODHD blocked, and Alpha Vantage premium endpoint/date-filter warnings; Google News RSS and Alpha Vantage evidence still contributed.
- Summarized Agent Intelligence Ledger after planner:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\agent_intelligence\summary.json`
  Result: 85 forecasts, 0 resolved, all influence weights 1.00 due to insufficient history.
- Refreshed premarket brief:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\premarket_briefs\premarket-brief-20260602-081708-000000.json`
  Result: analysis_only true, top symbol NOW, latest overnight generated_at 2026-06-02T08:12:59+00:00, stale_warnings 0, material change: top symbol changed from IBM to NOW. It carries 7 unresolved blockers from prior hourly supervisor guardrail failures, latest_hourly_decision blocked.
- No live or paper orders were submitted. No email was sent because both overnight and premarket packets were produced and the account/data/model checks were not hard-blocked for this analysis-only run.
- Current run time at memory update: 2026-06-02 03:18:03 -05:00.

## 2026-06-01 03:34:46 -05:00

- Ran required direct repo executable precheck:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe alpaca check`
  Result: paper ACTIVE, live ACTIVE.
- Ran required bounded overnight planner command with compact graph profile, 3 full-graph tickers, 25-minute per-ticker timeout, 90-minute budget, and 220 max completion tokens.
  Result: completed successfully with exit code 0; analysis_only true; submitted empty.
- Overnight packet:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\overnight_plans\overnight-plan-20260601-083346-000000.json`
  Validation: analysis_only true, submitted: [], 35 candidate / 35 ranked, top candidates IBM, CRM, AVGO, ADBE, ORCL.
  Quality: full_graph_count 3, fallback_count 32, graph_failure_count 0. Graph config compact, tool-free market/social/news/fundamentals, Ollama model `tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k`, backend `http://localhost:11434/v1`, max_completion_tokens 220.
- Observed non-blocking source warnings during planner stdout: ORCL/SPY weekend/date-boundary price-data warnings and Reddit HTTP 403 warnings for ORCL, NOW, and MSFT. These did not block packet generation and no graph failures were recorded.
- Refreshed premarket brief:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\premarket_briefs\premarket-brief-20260601-083427-000000.json`
  Result: analysis_only true, top symbol IBM, latest overnight generated_at 2026-06-01T03:33:46-05:00, unresolved_blockers 0, stale_warnings 0, material change no_material_change, paper tournament leader current-aggressive.
- Current run time at memory update: 2026-06-01 03:34:46 -05:00; overnight planner elapsed roughly 30m35s from packet quality timestamps.
- No live or paper orders were submitted. No email was sent because both packets were produced and account/data/model checks were not blocked.

## 2026-05-31 16:45:20 -05:00

- User asked to show the report inline in the thread. Reused the completed 2026-05-31 16:39:37 automation result rather than rerunning commands.
- Current inline report fields: overnight packet `overnight-plan-20260531-213728.json`, premarket brief `premarket-brief-20260531-213745.json`, top candidates ORCL/NOW/MSFT/IBM/CRM, 35 ranked candidates, 3 full graph attempts, 35 fallbacks, 3 graph failures, no blockers, no orders submitted.

## 2026-05-31 16:48:21 -05:00

- User asked to explain all failures from the report. Inspected `overnight-plan-20260531-213728.json` and per-ticker reports.
- All three graph failures were timeout failures after 300 seconds each: ADBE, AVGO, CRM. Each was safely converted to `market_snapshot_fallback` with score 0.95 / Buy / BUY, so the packet completed and no orders were submitted.
- CRM also emitted Reddit HTTP 403 warnings during the full graph attempt; those were data-source access warnings and not blockers because fallback scoring completed.

## 2026-05-31 20:48:47 -05:00

- Ran required direct repo executable precheck:
  C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe alpaca check
  Result: paper ACTIVE, live ACTIVE.
- Ran required overnight planner command with --full-graph-tickers 3 --per-ticker-timeout-minutes 25 --time-budget-minutes 90 --overnight-max-completion-tokens 220.
  Result: command exited with code 1 after writing an overnight packet; stdout did not include the final JSON blob.
- Overnight packet produced:
  C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\overnight_plans\overnight-plan-20260601-013525-000000.json
  Validation: nalysis_only: true, submitted: [], 35 candidate / 35 tradable / 35 ranked, top candidates ORCL, NOW, MSFT, IBM, CRM.
  Quality recorded by packet: full_graph_limit 1, full_graph_count 1, fallback_count 35, graph_failure_count 1, per_ticker_timeout_minutes 25.0, time_budget_minutes 30.0, graph_config ollama 	radingagents-qwen3-30b-a3b-instruct-2507-q4-4k, backend http://localhost:11434/v1, max_completion_tokens 220.
  Graph failure: ADBE timed out after 1500 seconds; fallback preserved the ranking via market_snapshot_fallback.
- Observed latest.json still pointed at older overnight-plan-20260531-235251-000000.json after the planner exited. Synced esults\overnight_plans\latest.json and latest.md to the current 20260601-013525 packet before refreshing premarket so the brief would not read stale overnight data.
- Refreshed premarket brief:
  C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\premarket_briefs\premarket-brief-20260601-014719-000000.json
  Result: nalysis_only: true, top symbol ORCL, latest overnight generated_at 2026-06-01T01:35:25+00:00, unresolved_blockers 0, stale_warnings 0, material change no_material_change.
- No live or paper orders were submitted. No email was sent because both packets were produced and account/data/model checks were not blocked.

## 2026-06-04 15:25:41 -05:00

- Provider-route repair: `broker_snapshot` is now a sanitized local hourly-supervisor packet reader for `quote_price_context`, not a direct broker API call. It reads the newest `results/hourly_supervisor/hourly-supervisor-*.json` packet or an explicit `--broker-snapshot-dir`, uses zero cache TTL, disables stale fallback, and writes analysis-only source evidence with `execution_authority=none`.
- Real KO proof:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\research_evidence\source-evidence-source-evidence-f5c7d62d87ca4be0901db1a13d67c0cb.json`
  Source supervisor packet:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\hourly_supervisor\hourly-supervisor-20260604-201930-941804.json`
  Result: KO had no live/paper position, no KO open orders, `submitted_order_count=0`, controlled-dip ranked candidate context, read-only true, no raw broker/order IDs copied.
- Source-quality profiles added for `broker_snapshot`, `ticker_provider_orchestrator`, `official_cache`, and `crawlee`. Latest review:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\source_quality\source-quality-review-20260604-202541.json`
  Result: `source_count=250`, `stale_count=42`, `stale_downrank_count=42`, `stale_needs_refresh_count=0`, `unknown=5`.
- Focused verification passed: `uv run --no-sync --with pytest python -m pytest -q tests/test_research_provider_orchestrator.py tests/test_source_quality.py` (21 passed); targeted Ruff and py_compile passed; compact context refreshed.

## 2026-06-04 15:38:20 -05:00

- Provider-route repair: `reddit` now uses repo-local public Reddit JSON (`dataflow:reddit_public`) for `social_sentiment` only, so it cannot crowd out Google/Alpaca/news-provider `market_news`. Public Reddit can still return HTTP 403; that is captured as low-authority read-only context rather than a trading blocker.
- Real Reddit proof:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\research_evidence\source-evidence-source-evidence-068230c2d7054c3b9d6d8569d719d566.json`
  Summary:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\research_evidence\source-evidence-source-evidence-12e04870b2c54213b3f127c9d1221c97.json`
- `twitter` now writes an explicit blocked packet instead of an unsupported silent skip until Docker MCP `twitter-research` has a repo-readable evidence bridge:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\research_evidence\source-evidence-source-evidence-f283adc9db7244ff95f7dfde34ade5b4.json`
- Latest source-quality review:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\source_quality\source-quality-review-20260604-203820.json`
  Result: `source_count=250`, `stale_count=38`, `stale_downrank_count=38`, `stale_needs_refresh_count=0`, `unknown=3`.
- Focused verification passed: provider/source-quality tests 23 passed; targeted Ruff and py_compile passed.

## 2026-06-04 15:45:25 -05:00

- Connector-health noise repair: `reddit_public` HTTP 403 is now classified as an optional endpoint block when there is no open circuit, rate limit, or fallback. It remains visible in `results/_context/connector-health.json`, but it no longer raises a hard `connector_health` flag or self-heal-style wakeup by itself.
- Real compact-context refresh after the patch left only the expected `paper_tournament` candidate-change and `mirofish_handoff_status` drilldown flags.
- Focused verification passed: `uv run --no-sync --with pytest python -m pytest -q tests/test_automation_context_snapshot.py` (27 passed); targeted Ruff and py_compile passed.

## 2026-06-04 16:01:27 -05:00

- Compact-context noise repair: paper tournament compaction now uses `latest_report.generated_at`, keeps unchanged `pullback-support` candidate facts visible, and only raises `candidate_change` for a real promotion/selection/submission. Real compact-context refresh now leaves paper tournament unflagged when `submitted_count=0` and `live_selection_path=null`.
- Model telemetry repair: `research model-telemetry-report` now separates current route state from historical blocked packets. Latest real report:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\model_telemetry_reports\model-telemetry-report-20260604-210104-955683.json`
  shows current Mac `mac_ollama_research_mule` success on `deepseek-r1:14b`; Windows local Ollama is the only current local-model blocker. Old Mac blocked packets remain in `historical_blocked_route_summaries`.
- Compact context now exposes `selected_helper_routes`, including `mac_ollama_research_mule` / `deepseek-r1:14b`, so morning agents can use Mac as cheap/offloaded helper work without opening raw telemetry.
- Real read-only orchestration proof:
  `.\.venv\Scripts\tradingagents.exe research automation-orchestration-plan --candidate-symbols KO,HD,AMD --json-output --no-research-context`
  completed with `status=success`, `research_quality_high_enough=true`, zero order authority, Mac DeepSeek selected, and Windows local skipped via deterministic fallback.
- Focused verification passed: `uv run --no-sync --with pytest python -m pytest -q tests/test_automation_context_snapshot.py tests/test_model_routing.py tests/test_research_automation_orchestrator.py` (54 passed); targeted Ruff and py_compile passed.

## 2026-06-04 16:11:42 -05:00

- MiroFish compaction repair: a clean final MiroFish handoff no longer creates a permanent `drilldown` flag. Compact summary still carries the two critical advisory filters:
  - `full_report_core_filter`: treat AI-bot copycat spikes/social momentum as false-signal risk until independent volume, broker/API execution, options liquidity, and institutional participation confirm durable flow.
  - `deep_research_review_core_filter`: use report 33 as macro-first relative-trade context; prefer risk control and validated relative strength over heroic directional bets.
- Real compact-context refresh:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\_context\latest-flags.json`
  now has `flags=[]` and `next_open=[]`; `results\_context\latest-summary.json` still shows MiroFish `status=final_handoff_available`, `missing_piece_count=0`, `final_advisory_available=true`, and `execution_authority=none`.
- Focused verification passed: `uv run --no-sync --with pytest python -m pytest -q tests/test_automation_context_snapshot.py` (30 passed); targeted Ruff and py_compile passed.

## 2026-06-04 16:28:30 -05:00

- Overnight planning status repair: `tradingagents-overnight-planning` was found `PAUSED` during the afternoon controller window even though the next 2:30 AM America/Chicago run is useful for the next market morning. Updated the existing automation through Codex automation API to `ACTIVE` while preserving prompt, RRULE, model, reasoning effort, execution environment, and cwd.
- Fresh verification:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\automation_health\automation-health-audit-20260604-212831.json`
  reports all 13 automations `ok`, `issue_count=0`, `submitted_order_count=0`, and overnight planning `config_status=ACTIVE`.
- Fresh overnight verifier:
  `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\overnight_system_verification\overnight-system-verification-20260604-162641.json`
  reports `overall_status=pass`, 3/3 full graph successes, 32 fallback-scored tickers, no graph failures, no stale premarket warnings, and no submitted orders.
- n8n evaluation proof: dataset generation produced 174 rows across 19 allowlisted non-submitting jobs and 17 edge tags. Local n8n and runner health endpoints were reachable. Sync is currently blocked only by missing `N8N_API_KEY`; the CLI now emits a redacted `blocked_missing_api_key` packet plus fresh dataset paths instead of a traceback.

## 2026-06-07 09:30:40 -05:00

- Re-read the Claude submit-path hardening handoff before checking overnight readiness. SAFE-01 remains fail-closed: `config/risk_envelope.yaml` parses as `autonomous_with_caps`, account max `$250.00`, per-name `$50.00`, tiny tranche `$25.00`, optional hard-ceiling/rate-limit knobs unset, and `issues=[]`. `results/policy/live_control.json` still has the expired dead-man at `2026-06-04T19:57:06+00:00`; no dead-man refresh was performed.
- Overnight research is currently healthy, not missing. `alpaca verify-overnight-system --json-output` wrote `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\overnight_system_verification\overnight-system-verification-20260607-092939.json` with `overall_status=pass`, 16/16 checks passed, 0 warnings/failures, `can_submit_orders=false`, and `execution_authority=none`.
- Latest production overnight packet: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\overnight_plans\overnight-plan-20260607-101157-000000.json`. It is analysis-only, targets trade date `2026-06-08`, top candidate `XOM`, has 40 ranked candidates, 3/3 original TradingAgents graph successes on the explicit Google compact route, 37 fallback-ranked symbols, 0 graph failures, and `submitted=[]`.
- Matching premarket brief is current enough for Monday prep: top symbol `XOM`, 54 source packets, 0 stale warnings, and 0 unresolved blockers.
- `research automation-health-audit --json-output` wrote `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\automation_health\automation-health-audit-20260607-142940.json` with 13/13 automations ok, no stale/late/missing/timeliness issues, and `submitted_order_count=0`. `tradingagents-overnight-planning` is `PAUSED` only because a complete current analysis-only packet exists; the verifier accepts `ACTIVE_OR_PAUSED_AFTER_COMPLETE_PACKET`.
- Refreshed compact context and ran process review: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\process_reviews\process-review-20260607-143611.json` has `unchecked_step_count=0`, `findings=[]`, and `can_submit_orders=false`.
- No live or paper orders, emails, dead-man refreshes, credential changes, automation status changes, staging, commits, or live-authority changes were performed.

## 2026-07-11 16:21:44 -05:00

- Ran the required bounded, analysis-only overnight planning sequence after refreshing compact context with the repo venv Python.
- Initial compact context flagged the prior overnight packet as stale/graph-failed for the next trade date; final compact context now points at the new overnight and premarket packets, with the expected remaining overnight graph-failure flag plus separate non-overnight BOARD/preopen/automation-health context flags.
- lpaca check through the repo executable passed: paper ACTIVE with buying power 355808.07 / equity 97219.71; live ACTIVE with buying power 86.42 / equity 199.72.
- Research orchestration succeeded: esults\research_batches\research-batch-research-batch-8da32a61fe824ed8a55a0be8f70b27e1.json. Deterministic helpers and Codex judgment were usable; Windows Ollama URL was not configured and Mac Ollama timed out, both treated as optional degraded helper lanes.
- Source-quality review refreshed: esults\source_quality\source-quality-review-20260711-211154.json / esults\source_quality\latest.json. Counts: source_count 250, stale_count 244, stale_downrank_count 69, stale_needs_refresh_count 0, unreadable_count 0, missing_or_invalid_count 0, blocked_count 52.
- Agent Intelligence Ledger resolve/summary completed: 80 forecasts newly resolved before the planner; summary after planner showed forecast_count 5024, resolved_forecast_count 4944, pending 80. Earned influence weights remain advisory only and cannot bypass gates.
- Overnight planner packet: esults\overnight_plans\overnight-plan-20260711-211424-000000.json. Result: analysis_only true, trade_date 2026-07-13, submitted_count 0, top candidates IBM, NFLX, UNH, JNJ, PEP, ranked_count 40, full_graph_attempt_count 3, full_graph_success_count 0, graph_failure_count 3, fallback_count 40, research_context_packet_count 15, research_context_blocked_count 0.
- Graph config was compact Google with quick model gemini-2.5-flash-lite, deep model gemini-2.5-flash, max_completion_tokens 220, source-quality ordering enabled via esults\source_quality\latest.json.
- Full graph failed for IBM, NFLX, and UNH with the recurring message-deletion error (Attempting to delete a message with an ID that doesn't exist). All 40 tickers were preserved through fallback scoring, so the packet is premarket-readable but the original graph lane is not healthy.
- Optional StockTwits/Reddit public HTTP 403 warnings appeared for IBM, NFLX, and UNH and did not block packet generation.
- Explicit ticker provider bundles completed for IBM, NFLX, and UNH. Summary packets: IBM esults\research_evidence\source-evidence-source-evidence-b776912d277a4fcdbc33dd8d4d323eea.json (18 packets), NFLX esults\research_evidence\source-evidence-source-evidence-8eba2faf17004bb586b366de9fe9e28d.json (18 packets), UNH esults\research_evidence\source-evidence-source-evidence-c92906463a44438c9a8c57cf5b554d25.json (17 packets). Depleted sources were empty; paid/limited/unsupported routes and gap packets were recorded while Alpaca News, broker snapshot, yfinance, Alpha Vantage where available, Google News RSS where available, SEC/official cache, YouTube transcript, Reddit watchlist, and Crawlee continued. UNH had earnings_transcripts as a missing non-gap need in the planner-integrated bundle; explicit bundles ended with evidence_needs_without_non_gap_packets empty.
- Refreshed premarket brief: esults\premarket_briefs\premarket-brief-20260711-212012-000000.json. Result: analysis_only true, top symbol IBM, latest overnight generated_at 2026-07-11T21:14:24+00:00, source_packet_count 54, unresolved_blockers 0, stale_warnings 0, material change top symbol changed from JPM to IBM.
- No live or paper orders were submitted. No email was sent because both the overnight packet and premarket brief were produced and account/data/model checks were not hard-blocked for this analysis-only run.
- Current run time at memory update: 2026-07-11 16:21:44 -05:00.
