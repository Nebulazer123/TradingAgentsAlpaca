# Market Supervisor 15 Min After Close Memory

## 2026-06-01 run at 2026-06-01 15:19:58 -05:00
- Ran repo executable directly: .venv\Scripts\tradingagents.exe.
- lpaca check passed: paper ACTIVE buying power 170055.5 equity 100394.76; live ACTIVE buying power 50 equity 203.63.
- Dry-run wrote hourly packet: C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\hourly_supervisor\hourly-supervisor-20260601-201813-504123.json.
- Decision: blocked. Reason: hourly supervisor action failed guardrail validation.
- Guardrail issue: live-exposure; new live buy would exceed live exposure limit without a paired reduction.
- Proposed dry-run action: paper-first ORCL buy, notional 100, limit 248.64; no submit-capable command was run because issues were present and live exposure was already 150 vs dynamic cap 100.
- Submitted orders: 0. Live open orders: 0. Live positions: AVGO, GOOGL, MSFT, NVDA, TSM. Live unrealized P/L: 3.62.
- Top ranked candidates: NVDA, ORCL, ADBE, CRM, IBM.
- Refreshed rolling premarket brief: C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\premarket_briefs\premarket-brief-20260601-201839-000000.json. Brief remains analysis-only; latest hourly decision blocked; paper tournament leader current-aggressive; premarket top_symbol IBM.
- Email: not sent. The submit-capable run was skipped, so there was no submit-run 
otify: true trigger.

## 2026-06-02 run at 2026-06-02 15:38:06 -05:00
- Ran compact context snapshot first and inspected flagged context: prior hourly packet had submitted live MA buy; promotion state kept current-aggressive tiny-live eligible; research/model flags were analysis-only with no execution authority.
- Ran repo executable directly: .venv\Scripts\tradingagents.exe.
- alpaca check passed: paper ACTIVE buying power 169910.7 equity 100249.96; live ACTIVE buying power 89.21 equity 202.09.
- Dry-run wrote hourly packet: C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\hourly_supervisor\hourly-supervisor-20260602-202803-332192.json.
- Dry-run decision: clean/actionable buy. Proposed one live tiny_live NFLX buy, notional 26.76, limit 83.57, extended_hours true; no issues.
- Submit run wrote hourly packet: C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\hourly_supervisor\hourly-supervisor-20260602-202944-393506.json.
- Submitted order: NFLX live buy, notional 26.76, limit 83.57, client_order_id ta-tiny-20260602-current-nflx-buy-0a6cfdbc2d, status pending_new, filled_qty 0, filled_at null, expires_at 2026-06-03T00:00:00Z.
- Live account in submit packet: ACTIVE buying power 89.21 equity 202.14 exposure 113.23 unrealized P/L -0.29; positions AMZN, MA, ORCL, TSM; packet snapshot listed 0 open live orders before/around submission while the submitted order itself was pending_new.
- Paper account in submit packet: ACTIVE buying power 169914.72 equity 100253.98 unrealized P/L 253.98; open paper orders 0.
- Refreshed rolling premarket brief: C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\premarket_briefs\premarket-brief-20260602-203205-000000.json. Brief remains analysis-only; context summary latest_hourly_decision buy, top_symbol NOW, paper tournament leader current-aggressive, blockers 0, stale_warnings 0.
- Email: not sent manually. Final submit packet alert severity was NOTABLE but notify=false and email_suppressed=true with suppression_reason same-cause alert already emitted inside throttle window.

## 2026-06-04 run at 2026-06-04 15:21:22 -05:00
- Ran compact context snapshot first. Flags required raw drilldown for paper_tournament candidate_change and MiroFish handoff drilldown; both were advisory/analysis-only with no execution authority. Paper tournament candidate/leader is pullback-support.
- Ran repo executable directly: .venv\Scripts\tradingagents.exe.
- alpaca check passed: paper ACTIVE buying power 338248.95 equity 99463.74; live ACTIVE buying power 86.38 equity 200.04.
- Dry-run wrote hourly packet: C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\hourly_supervisor\hourly-supervisor-20260604-201930-941804.json.
- Decision: hold. Reason: new live buys paused by BOARD review; BOARD recommended review_underperformers_before_new_buys with 0 hard issues, 1 warning, 24 hourly packets reviewed.
- Gate result: no actions, no issues, no submitted orders, alert severity ROUTINE, notify false. Submit-capable command was skipped because there were no valid actions to submit.
- Live account in dry-run: ACTIVE buying power 86.38 equity 200.04 exposure 114.99 unrealized P/L -1.32; positions AMZN, MA, NFLX, TSM; open live orders 0.
- Paper account in dry-run: ACTIVE buying power 338254.83 equity 99466.67 unrealized P/L -533.32; open paper orders 0.
- Top ranked candidates: QCOM, KO, IBM, TXN, CRM. QCOM/KO/IBM/TXN/CRM were controlled-dip candidates, but BOARD caution kept new live buys paused. AVGO was flagged falling-knife watch only; several green-spike names were not chased.
- Refreshed rolling premarket brief: C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\premarket_briefs\premarket-brief-20260604-202009-000000.json. Brief remains analysis-only; latest hourly decision hold; top_symbol KO; paper tournament leader pullback-support; blockers 0; stale_warnings 0.
- Email: not sent. Final supervisor alert was ROUTINE with notify false and no legacy notify true.

## 2026-06-08 run at 2026-06-08 15:23:52 -05:00
- Read automation memory first. Ran compact context snapshot; bare `python scripts/automation_context_snapshot.py --write` failed with `ModuleNotFoundError: No module named 'tradingagents'`, then the repo venv Python succeeded and refreshed `results\_context\latest-summary.json`, `latest-flags.json`, and `recent-deltas.md`.
- Compact context flagged the prior hourly loss-review/BOARD caution, stale preopen validation, research quality/audit/automation-health flags, execution BOARD review, and loss-review evidence. No recent watched-field deltas were reported before this run.
- Ran repo executable directly: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe`.
- `alpaca check` passed: paper ACTIVE buying power 359116 equity 98401.11; live ACTIVE buying power 86.38 equity 198.95.
- Read live posture from `config\risk_envelope.yaml` and `results\policy\live_control.json`: risk envelope caps are armed with live_budget_mode `autonomous_with_caps`, account cap 250, per-name cap 50, tiny-live tranche 25; live_control frozen false but dead-man timestamp was expired at 2026-06-04T19:57:06Z.
- Dry-run wrote hourly packet: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\hourly_supervisor\hourly-supervisor-20260608-202241-649188.json`.
- Dry-run decision: `loss-review`. AMZN crossed loss review, but HOLD/loss-review stayed active because required thesis-break/exit evidence was missing. No live sell was submitted; BOARD/manual review remains required before any loss exit. New live buys remain paused during review.
- Gate result: no actions, no issues, no submitted orders, alert severity NOTABLE, alert_notify false, same-cause email suppression active. Submit-capable command was skipped because there were no valid actions to submit.
- Live account in dry-run: ACTIVE buying power 86.38 equity 198.91 exposure 114.99 dynamic cap 100.00 unrealized P/L -2.45; positions AMZN, MA, NFLX, TSM; open live orders 0.
- Paper account in dry-run: ACTIVE buying power 359068.20 equity 98384.04 unrealized P/L -1615.95; open paper orders 0.
- Top ranked candidates: AAPL, GOOGL, MSFT, META, ORCL. They were controlled-dip candidates, but loss-review/BOARD posture blocked new live buys. Green spikes such as AVGO, AMD, CSCO, TXN, TSM, HOOD, IBKR, INTC, and AMAT were not chased.
- Refreshed rolling premarket brief: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\premarket_briefs\premarket-brief-20260608-202313-000000.json`. Brief remains analysis-only; latest hourly decision loss-review; top_symbol XOM; paper tournament leader pullback-support; unresolved blockers 0; stale_warnings 0; material change was live unrealized P/L from -2.46 to -2.45.
- Email: not sent. Final supervisor alert was NOTABLE but `alert.notify=false`, no submitted orders existed, and same-cause suppression was active; no CRITICAL/legacy notify true trigger was present.

## 2026-06-11 run at 2026-06-11 00:55:01 -05:00
- Read automation memory first. Ran compact context snapshot; bare `python scripts/automation_context_snapshot.py --write` still failed with `ModuleNotFoundError: No module named 'tradingagents'`, then the repo venv Python succeeded and refreshed `results\_context\latest-summary.json`, `latest-flags.json`, and `recent-deltas.md`.
- Compact context before the run flagged stale overnight/preopen context, BOARD/loss-review posture, source routing, n8n audit, and self-heal issue drilldowns; recent-deltas reported no watched-field changes.
- Read live posture from `config\risk_envelope.yaml` and `results\policy\live_control.json`: risk envelope caps are armed with live_budget_mode `autonomous_with_caps`, account cap 250, per-name cap 50, tiny-live tranche 25; live_control frozen false but dead-man timestamp remained expired at 2026-06-04T19:57:06Z.
- Ran repo executable directly: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe`.
- `alpaca check` passed: paper ACTIVE buying power 355665.43 equity 97168.76; live ACTIVE buying power 86.38 equity 197.83.
- Dry-run wrote hourly packets during the refresh window; final compact/latest hourly packet is `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\hourly_supervisor\hourly-supervisor-20260611-055245-932837.json`.
- Final supervisor decision: `loss-review`. TSM crossed loss review, but HOLD/loss-review stayed active because BOARD/manual review is required, source/evidence gaps remain, and market session was closed/not tradeable for a live loss exit. New live buys remain paused while review is open.
- Gate result: no actions, no issues, no submitted orders, alert severity NOTABLE, alert_notify false, email_suppressed true. Submit-capable command was skipped because there were no valid actions to submit.
- Live account in final packet: ACTIVE buying power 86.38 equity 197.82 exposure 114.99 dynamic cap 100.00 unrealized P/L -3.54; positions AMZN, MA, NFLX, TSM; open live orders 0.
- Paper account in final packet: ACTIVE buying power 355661.06 equity 97167.21 unrealized P/L -2832.79; open paper orders 0.
- Top ranked candidate: ORCL, controlled dip -2.84% with buy-the-dip support/volume caveat. No green-spike chase or falling-knife action was taken.
- Refreshed rolling premarket brief: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\premarket_briefs\premarket-brief-20260611-055310-000000.json`. Brief remains analysis-only; latest hourly decision loss-review; top_symbol HD; paper tournament leader pullback-support; unresolved blockers 0; stale_warnings 0; material change was live unrealized P/L from -3.55 to -3.54.
- Refreshed compact context after the run. `results\_context\latest-flags.json` still flags expected hourly BOARD review, stale overnight/preopen/execution/loss evidence routes, n8n audit, self-heal issues, and source routing; `recent-deltas.md` reports no watched-field changes.
- Email: not sent. Final supervisor alert was NOTABLE but `alert.notify=false`, `email_suppressed=true`, no `alert_email` body was present, and there were no submitted orders or legacy notify true trigger in the final packet.
