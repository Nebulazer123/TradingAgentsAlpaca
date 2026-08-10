# TradingAgents overnight research memory

- Current run time: 2026-07-30 13:13:53 UTC.
- Invocation: exactly one `TA_LIVE_SUBMIT=0 /bin/zsh scripts/mac/ta_job.sh overnight` run from `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main`.
- Outcome: wrapper exit 0; success heartbeat `2026-07-30T13:12:08Z overnight ok`; packet completion status `complete`; analysis-only `true`; execution authority `none`; submitted count `0`.
- Graph: 3 attempts, 1 success, 2 failures. BULL succeeded (`Underweight`, 0.30). LLY failed in the full graph with `GRAPH_RECURSION_LIMIT` at recursion limit 100 and JNJ timed out after 300 seconds; both used market-snapshot fallback. Total fallback count: 39.
- Model route: `explicit_openrouter_overnight_graph`; provider `openrouter`; quick model `qwen/qwen3-30b-a3b-instruct-2507`; deep model `deepseek/deepseek-v4-flash`.
- Top ranked symbols: LLY 0.84 Buy, JNJ 0.84 Buy, HD 0.83 Buy, BAC 0.83 Buy, SCHW 0.82 Buy; all five are fallback-ranked.
- Warnings: packet and downstream premarket stale-warning counts were 0; research-context blocked count was 0 of 15; premarket unresolved blockers were empty. Source-quality review counted 250 sources, 244 stale, 69 downranked, 0 requiring refresh, and 52 blocked source records, while the overall source-quality watchlist was not blocked. Log recorded Reddit HTTP 403 warnings for JNJ and BULL plus two structured-output validation retries that recovered through free-text handling. Premarket retained one expected safety control-plane lock from the frozen hourly supervisor.
- Packet: `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main/results/overnight_plans/overnight-plan-20260730-131159-000000.json`
- Compact packet: `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main/results/overnight_plans/overnight-plan-20260730-131159-000000.compact.json`
- Premarket packet: `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main/results/premarket_briefs/premarket-brief-20260730-131207-000000.json`
- Log: `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main/results/mac_automation/logs/overnight-20260730-090159.log`
- Verification: all overnight and premarket full/compact/Markdown `latest` aliases were byte-identical to their timestamped artifacts; the lock and wrapper/planner processes were absent after completion; the pre-existing dirty worktree path set was unchanged. No code, strategy/config, live-control, or order action was performed.
