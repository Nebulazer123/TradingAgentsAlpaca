## 2026-05-29 15:22:17 -05:00
- Ran daily supervisor report for results/hourly_supervisor and emailed nebulazer2003@gmail.com.
- Bare tradingagents command was not on PATH in this PowerShell session; used repo fallback: .\.venv\Scripts\python.exe -m cli.main alpaca supervisor-daily-report --json-output --log-dir results/hourly_supervisor --email-to nebulazer2003@gmail.com.
- Gmail send confirmation: message id 19e7566b3cc4880a, thread id 19e7566b3cc4880a.
- Report highlights: live equity $201.90, live buying power $100.00, live unrealized P/L $1.90, paper equity $100062.86, paper unrealized P/L $62.85, 5 supervisor checks, 2 material checks, 0 submitted orders, no open live orders.

## 2026-05-29 15:31:46 -05:00
- Updated daily supervisor report formatting in repo code: comma-formatted display amounts, removed Live buying power, Live exposure, and Paper equity from the email body, and added total live unrealized P/L percent next to the dollar amount.
- Verified with targeted render and tests: uv run --with pytest python -m pytest tests\test_alpaca_supervisor.py tests\test_alpaca_cli.py -q passed 26 tests.

## 2026-06-01 15:36:19 -05:00
- Ran read-only daily supervisor report with the repo executable: .venv\Scripts\tradingagents.exe alpaca supervisor-daily-report --json-output --log-dir results/hourly_supervisor --paper-tournament-log-dir results/paper_strategy_tournament --premarket-brief-log-dir results/premarket_briefs --email-to nebulazer2003@gmail.com.
- Sent Gmail report to nebulazer2003@gmail.com with subject "TradingAgents Daily Market Supervisor Report"; Gmail message id 19e84e657e80afb0, thread id 19e84e657e80afb0.
- Report highlights: latest decision blocked at 2026-06-01T20:18:13+00:00 because live-exposure guardrail blocked a new live buy without paired reduction; 32 supervisor checks, 32 material checks, 6 submitted orders earlier today, no open live orders.
- Balances/P&L: live equity $203.62, live cap $100.00, unused live cap $0.00, live unrealized P/L $3.62 (2.41%), paper unrealized P/L $407.68.
- Current positions: live AVGO, GOOGL, MSFT, NVDA, TSM; paper tournament leader current-aggressive, live strategy candidate pending current-aggressive; latest premarket brief results\premarket_briefs\latest.json top IBM/status amended/sources 54.

## 2026-06-01 15:38:58 -05:00
- Sent a corrected authoritative Gmail report using the exact returned subject/body fields after noticing the first email had a condensed material-decisions section.
- Authoritative Gmail message id 19e84e8e15488368, thread id 19e84e8e15488368. Earlier concise email id 19e84e657e80afb0 can be ignored in favor of this exact-body send.
- Refreshed exact report values: live equity $203.69, live cap $100.00, unused live cap $0.00, live unrealized P/L $3.69 (2.46%), paper unrealized P/L $416.40.
- Latest blocker unchanged: 2026-06-01T20:18:13+00:00 hourly supervisor action failed guardrail validation, live-exposure guardrail blocked a new live buy without paired reduction; no open live orders.
## 2026-06-03 15:38:10 -05:00
- Ran daily supervisor report after refreshing compact context and agent-ledger history.
- Ledger is still building history: 734 pending forecasts, 0 resolved, and all influence weights remain 1.00 / insufficient_history.
- Daily report command returned subject/body for "TradingAgents Daily Market Supervisor Report" and included current live/paper state, one submitted order, and market-session-closed context.
- Compact research packet counts for the latest orchestration batch: source_packet_count 13; no AlphaInsider paper-watch status was present in the compact context.

## 2026-06-04 15:35:04 -05:00
- Refreshed compact context, opened the paper-tournament candidate-change packet, and ran `research agent-ledger-summary --json-output`.
- Ledger still has no resolved forecasts yet; all influence weights remain 1.00 with `insufficient_history`.
- Ran `alpaca supervisor-daily-report --json-output --log-dir results/hourly_supervisor --paper-tournament-log-dir results/paper_strategy_tournament --premarket-brief-log-dir results/premarket_briefs --email-to nebulazer2003@gmail.com`.
- Report returned subject/body for "TradingAgents Daily Market Supervisor Report" with hold state, 0 submitted orders, live unrealized P/L -$1.39, paper unrealized P/L -$540.38, paper leader pullback-support, and paper watch blocked fetch status.

## 2026-06-08 15:36:07 -05:00
- Refreshed compact context with the repo venv, then ran `research agent-ledger-summary --json-output` and `alpaca supervisor-daily-report --json-output --log-dir results/hourly_supervisor --paper-tournament-log-dir results/paper_strategy_tournament --premarket-brief-log-dir results/premarket_briefs --email-to nebulazer2003@gmail.com`.
- Ledger is still building history: 4,704 pending forecasts, 0 resolved, and all influence weights remain 1.00 with `insufficient_history`.
- Daily report subject was `TradingAgents Daily Market Supervisor Report`; live gate stayed fail-closed under caps, paper leader remained `pullback-support`, and AlphaInsider paper watch stayed `paper_strategy_emulation` with 0 watch items and 0 shadow orders.

## 2026-06-11 00:52:20 -05:00
- Refreshed compact context with `.venv\\Scripts\\python.exe scripts/automation_context_snapshot.py --write`, then ran `research agent-ledger-summary --json-output` and `alpaca supervisor-daily-report --json-output --log-dir results/hourly_supervisor --paper-tournament-log-dir results/paper_strategy_tournament --premarket-brief-log-dir results/premarket_briefs --email-to nebulazer2003@gmail.com` through the repo executable.
- Ledger is now well past the minimum history threshold: 4,784 forecasts, 132 resolved, influence weights earned for 8 agents, with `bull_researcher` and `aggressive_risk_analyst` still at `insufficient_history`.
- Daily report subject was `TradingAgents Daily Market Supervisor Report`; report body said nothing urgent happened, live equity was $197.83 with live unrealized P/L of -$3.53, paper unrealized P/L was -$2,831.11, BOARD review was `review_underperformers_before_new_buys`, and the report command completed successfully.
- Current live gate/risk envelope stayed cap-armed and fail-closed: `live_control.json` is unfrozen, `risk_envelope.yaml` keeps `live_budget_mode: autonomous_with_caps`, `account_max_capital_at_risk_usd: 250.00`, and `per_name_cap_usd: 50.00`.
- AlphaInsider paper-watch state remains analysis-only / paper-only with `execution_authority: none`, `paper_shadow_mode: paper_strategy_emulation`, `fetch_status: blocked`, `strategy_count: 0`, and `shadow_order_count: 0`.
