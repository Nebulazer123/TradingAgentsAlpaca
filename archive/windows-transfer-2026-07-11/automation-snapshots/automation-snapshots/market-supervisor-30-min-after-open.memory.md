2026-06-01 09:08:58 -05:00 America/Chicago

- Ran pinned executable `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe` from repo cwd.
- `alpaca check`: paper `ACTIVE`, live `ACTIVE`; live buying power `75`, live equity `203.22`; paper buying power `192502.57`, paper equity `100102.57`.
- Dry run `alpaca supervise-hourly --dry-run --json-output ...`: `decision=paper-first`, `issues=[]`, `actions=1`; proposed CRM paper-first buy, `$100.00` notional, limit `206.24`; `notify=true`; dry-run packet `results\hourly_supervisor\hourly-supervisor-20260601-140309-122008.json`.
- Submit-capable run executed because account checks were clean and dry-run returned valid actions with no issues.
- Submit output: `decision=paper-first`, CRM paper buy limit `$100` at `206.20`, order `5c749834-6d6b-4d92-8d94-61333a366ab9`, client `ta-hourly-20260601-140349-1-crm-buy`, status initially `pending_new`, packet `results\hourly_supervisor\hourly-supervisor-20260601-140349-635161.json`, `notify=true`.
- Refreshed rolling premarket brief with required command; latest checked brief was `results\premarket_briefs\premarket-brief-20260601-140432-000000.json`, analysis-only, top symbol `IBM`, latest hourly decision `paper-first`, blockers `0`.
- Direct packet/order verification found latest hourly packet `results\hourly_supervisor\hourly-supervisor-20260601-140410-464942.json` with a second CRM paper submit: order `a30537c4-872a-4558-8b57-72fee1446b2e`, client `ta-hourly-20260601-140410-1-crm-buy`, limit `206.18`, status `pending_new` in packet.
- Post-run Alpaca order verification: live open orders `0`; paper open orders only existing MSFT limit order `71cef98a-4a6c-4562-bd0a-ad74cec716bc`; both CRM paper orders were filled (`205.82` and `205.498` average fill prices), so no open duplicate CRM order remained.
- Live state in latest hourly packet: exposure `125.00`, dynamic cap `125.00`, unused cap `0.00`, live buying power `75.00`, live equity `203.15`, live unrealized P/L `3.15`, live positions AVGO/GOOGL/MSFT/NVDA, live open orders `0`.
- Mechanical checks observed: CRM actions were paper account only, US equity, buy side, limit orders, day TIF, no extended hours; no live crypto/options/shorts/margin/market orders submitted.
- Because submit-capable run returned `notify=true`, sent urgent exception email to `nebulazer2003@gmail.com` via Gmail; message id `19e83830581835bd`. Email explicitly called out the duplicate filled CRM paper orders and no live order.

2026-06-02 09:03:51 -05:00 America/Chicago

- Ran pinned executable `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe` from repo cwd.
- Refreshed context snapshot before broker actions.
- `alpaca check`: paper `ACTIVE`, live `ACTIVE`; live buying power `49.99`, live equity `203.43`; paper buying power `169827.07`, paper equity `100166.33`.
- Dry run `alpaca supervise-hourly --dry-run --json-output ...`: `decision=blocked`, `material=true`, `reason=hourly supervisor action failed guardrail validation`; proposed live GOOGL close `$42.78` limit about `364.63` and live CSCO buy `$25.00` limit about `126.69`; issue `live-exposure: new live buy would exceed live exposure limit without a paired reduction`; submitted `0`.
- Did not run `--submit-actions` because the dry-run had an issue and was blocked by guardrail validation.
- Dry-run stdout packet path was `results\hourly_supervisor\hourly-supervisor-20260602-140308-644377.json`; latest hourly packet after run was `results\hourly_supervisor\hourly-supervisor-20260602-140321-800372.json`.
- Latest hourly packet remained `CRITICAL` but had `alert.notify=false`, `email_suppressed=true`, and suppression reason `same-cause alert already emitted inside throttle window`; no duplicate urgent email was sent.
- Refreshed rolling premarket brief with required command. Latest checked brief was `results\premarket_briefs\premarket-brief-20260602-140351-000000.json`; analysis-only; top symbol `NOW`; latest hourly decision `blocked`; unresolved blockers `0`; control-plane locks `1`; stale warnings `0`.
- Live state in latest hourly packet: exposure `150.00`, dynamic cap `100.00`, unused cap `0.00`, live buying power `49.99`, live equity `203.24`, live unrealized P/L `3.26`, live positions AVGO/GOOGL/MSFT/NVDA/TSM, live open orders `0`.
- Paper state in latest hourly packet: buying power `169814.30`, equity `100153.56`, unrealized P/L `152.28`, open orders `0`.
- Mechanical checks observed: no live or paper orders submitted; proposed actions were stocks, limit orders, no extended hours, no crypto/options/shorts/margin/market orders.

2026-06-03 09:10:02 -05:00 America/Chicago

- Ran pinned executable `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe` from repo cwd.
- Read automation memory first, refreshed compact context with `python scripts/automation_context_snapshot.py --write`, then opened only flagged packets: latest hourly action packet, overnight verification stale warning, and self-heal handoff.
- Initial compact context showed latest hourly `decision=close`, `actions=2`, `issues=0`, `submitted=0`, reason `ORCL breached loss review threshold`; stale self-heal trigger was from an older dead-man guard packet.
- `alpaca check`: paper `ACTIVE`, buying power `169391.32`, equity `99730.58`; live `ACTIVE`, buying power `62.44`, equity `199.28`.
- Dry run `alpaca supervise-hourly --dry-run --json-output ...`: `decision=close`, `issues=[]`, proposed live ORCL sell-to-close `qty≈0.10272087`, notional about `$23.96`, limit `233.30`, plus `hold_cash`; dry-run packet `results\hourly_supervisor\hourly-supervisor-20260603-140541-382637.json`; `alert.severity=NOTABLE`, `notify=false`, `email_suppressed=true` due same-cause throttle.
- Submit-capable run executed because account checks were clean and dry-run returned valid close action with no issues.
- Submit output: live ORCL sell-to-close limit order `1ed67324-23d8-4b4e-a636-f4921f4a6f0d`, client `ta-tiny-20260603-current-orcl-sell-c7f2b0007a`, qty `0.10272087`, limit `233.37`, status initially `pending_new`; packet `results\hourly_supervisor\hourly-supervisor-20260603-140628-188414.json`; `issues=[]`, `submitted=1`.
- Refreshed rolling premarket brief with required command; latest checked brief `results\premarket_briefs\premarket-brief-20260603-140707-000000.json`, analysis-only, top symbol `NOW`, latest hourly decision `close`, blockers `0`, stale warnings `0`.
- Read-only order verification by client order id found ORCL order status `new`, filled qty `0`, filled average price `null`; live open orders contained exactly that ORCL sell order; live ORCL position still present pending fill.
- Final compact context refresh completed; `latest-summary.json` points to submitted hourly packet and refreshed brief; recent deltas show hourly `submitted: 0 -> 1`; self-heal handoff now `should_start_new_chat=false`, max severity `low`.
- No email sent because the submitted packet had NOTABLE severity but structured `notify=false` / `email_suppressed=true` for same-cause throttle; no legacy `notify: true`.
- Mechanical checks observed: submitted order was live account, US equity, sell side, limit order, day TIF, no extended hours, sell-to-close; no crypto/options/shorts/margin/market orders submitted.

2026-06-04 09:11:54 -05:00 America/Chicago

- Ran pinned executable `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe` from repo cwd.
- Read automation memory first, refreshed compact context with `python scripts/automation_context_snapshot.py --write`, and opened only flagged narrow evidence for paper candidate change, BOARD caution, and connector health.
- Pre-run compact context showed latest hourly `decision=loss-review`, `actions=0`, `issues=0`, `submitted=0`; paper tournament leader/candidate changed to `pullback-support`; BOARD recommended reviewing underperformers before new buys; connector health had closed-circuit AlphaInsider HTTP 400 errors, no rate limits/fallbacks.
- `alpaca check`: paper `ACTIVE`, buying power `337927.72`, equity `99303.12`; live `ACTIVE`, buying power `86.38`, equity `200.34`.
- Dry run `alpaca supervise-hourly --dry-run --json-output ...`: `decision=loss-review`, `issues=[]`, `actions=[]`, `submitted=[]`; packet `results\hourly_supervisor\hourly-supervisor-20260604-140901-757296.json`.
- Did not run `--submit-actions` because the dry-run had no valid actions to submit.
- Latest hourly packet: TSM crossed loss review, but HOLD/loss-review stayed active because required loss-exit evidence was missing; BOARD/manual review required before a loss exit; new live buys paused during review.
- Alert state: `alert.severity=NOTABLE`, `alert.notify=false`, `email_suppressed=true`, suppression reason `same-cause alert already emitted inside throttle window`; no legacy `notify: true`; no email sent.
- Final live state from packet: exposure `114.99`, buying power `86.38`, equity about `200.31`, unrealized P/L `-1.06`, positions AMZN/MA/NFLX/TSM, open live orders `0`.
- Paper state from packet: buying power `337872.28`, equity `99275.40`, unrealized P/L `-724.54`, open paper orders `0`.
- Refreshed rolling premarket brief with required command; latest checked brief `results\premarket_briefs\premarket-brief-20260604-141007-000000.json`, analysis-only, latest hourly decision `loss-review`, top symbol `AMZN`, paper tournament leader `pullback-support`, blockers `0`, stale warnings `0`, control lock `null`.
- Final context snapshot completed; `results\_context\latest-summary.json` points to the new hourly packet and refreshed brief; recent deltas show no watched-field changes.
- Mechanical checks observed: no live or paper orders submitted; no open live orders; no crypto/options/shorts/margin/market orders.

2026-06-08 09:08:34 -05:00 America/Chicago

- Read automation memory first.
- Initial `python scripts/automation_context_snapshot.py --write` failed under system Python with `ModuleNotFoundError: No module named 'tradingagents'`; reran successfully with repo venv Python: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`.
- Pre-run compact context flagged hourly BOARD review/loss-review, stale preopen validation, execution-board warnings, and TSM loss-review evidence. Risk posture: `config/risk_envelope.yaml` has `live_budget_mode: autonomous_with_caps`, account max cap `$250`, per-name cap `$50`, tiny live tranche `$25`; `results/policy/live_control.json` is not frozen but dead-man expired at `2026-06-04T19:57:06+00:00`, so posture remains fail-closed unless the unified live gate allows action.
- Ran pinned executable `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe`.
- `alpaca check`: paper `ACTIVE`, buying power `358966.66`, equity `98347.78`; live `ACTIVE`, buying power `86.38`, equity `199.23`.
- Dry run `alpaca supervise-hourly --dry-run --json-output --notification-policy urgent-exceptions ...`: `decision=loss-review`, `issues=[]`, `actions=[]`, `submitted=[]`; packet `results\hourly_supervisor\hourly-supervisor-20260608-140623-649790.json`.
- Did not run `--submit-actions` because the dry-run had no valid actions.
- Latest hourly packet: TSM remains in loss review; no live sell submitted because HOLD/loss-review is active and thesis-break/exit evidence is still incomplete. BOARD/manual review remains required before any loss exit. New live buys remain paused/caution while review is open.
- Alert state: `severity=NOTABLE`, `notify=false`, `email_suppressed=true`, suppression reason `same-cause alert already emitted inside throttle window`; no legacy `notify: true`; no email sent.
- Final live state from latest hourly compact: exposure `114.99`, buying power `86.38`, equity `199.29`, unrealized P/L `-2.07`, positions AMZN/MA/NFLX/TSM, open live orders `0`.
- Final paper state from latest hourly compact: buying power `359026.74`, equity `98369.23`, unrealized P/L `-1630.37`, open paper orders `0`.
- Refreshed rolling premarket brief with required command; latest checked brief `results\premarket_briefs\premarket-brief-20260608-140708-000000.json`, analysis-only, latest hourly decision `loss-review`, top symbol `XOM`, paper tournament leader `pullback-support`, blockers `0`, stale warnings `0`.
- Final context snapshot completed with repo venv Python; `results\_context\latest-summary.json` points to the new hourly packet and refreshed brief; `results\_context\recent-deltas.md` shows no watched-field changes.
- Mechanical checks observed: no live or paper orders submitted; no open live or paper orders; no crypto/options/shorts/margin/market orders.

2026-06-11 00:53:10 -05:00 America/Chicago

- Read automation memory first.
- Initial `python scripts/automation_context_snapshot.py --write` failed under system Python with `ModuleNotFoundError: No module named 'tradingagents'`; reran successfully with repo venv Python: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`.
- Pre-run compact context flagged hourly BOARD/loss-review posture, stale/failed overnight graph context, stale preopen validation, execution-board warnings, loss-review evidence, and source routing gaps. Risk posture: `config/risk_envelope.yaml` has `live_budget_mode: autonomous_with_caps`, account max cap `$250`, per-name cap `$50`, tiny live tranche `$25`; `results/policy/live_control.json` is not frozen but dead-man expired at `2026-06-04T19:57:06+00:00`, so posture remains fail-closed unless the unified live gate allows action.
- Ran pinned executable `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe`.
- `alpaca check`: paper `ACTIVE`, buying power `355663.63`, equity `97168.12`; live `ACTIVE`, buying power `86.38`, equity `197.83`.
- Dry run `alpaca supervise-hourly --dry-run --json-output --notification-policy urgent-exceptions ...`: `decision=loss-review`, `issues=[]`, `actions=[]`, `submitted=[]`; stdout packet `results\hourly_supervisor\hourly-supervisor-20260611-055153-591599.json`.
- Did not run `--submit-actions` because the dry-run had no valid actions.
- Latest hourly packet after premarket refresh/final snapshot: `results\hourly_supervisor\hourly-supervisor-20260611-055245-932837.json`; `decision=loss-review`, `market_session=closed`, `issues=0`, `actions=0`, `submitted=0`.
- Latest hourly reason: TSM crossed loss review, but no live sell was submitted because HOLD/loss-review is active; BOARD/manual review remains required before any loss exit; market session was not tradeable; new live buys remain paused while review is open.
- Alert state: `severity=NOTABLE`, `notify=false`, `email_suppressed=true`, suppression reason `same-cause alert already emitted inside throttle window`; no legacy `notify: true`; no email sent.
- Final live state from latest hourly compact: exposure `114.99`, buying power `86.38`, equity `197.82`, unrealized P/L `-3.54`, positions AMZN/MA/NFLX/TSM, open live orders `0`.
- Final paper state from latest hourly compact: buying power `355661.06`, equity `97167.21`, unrealized P/L `-2832.79`, open paper orders `0`.
- Refreshed rolling premarket brief with required command; latest checked brief `results\premarket_briefs\premarket-brief-20260611-055310-000000.json`, analysis-only, latest hourly decision `loss-review`, top symbol `HD`, paper tournament leader `pullback-support`, blockers `0`, stale warnings `0`, control locks `0`.
- Final context snapshot completed with repo venv Python; `results\_context\latest-summary.json` points to the refreshed hourly and brief compacts; `results\_context\recent-deltas.md` shows no watched-field changes.
- Mechanical checks observed: no live or paper orders submitted; no open live or paper orders; no crypto/options/shorts/margin/market orders. Timing note: this run executed at `2026-06-11 00:51-00:53 America/Chicago`, and the supervisor packet reported `market_session=closed`, so it did not observe an actual 30-min-after-open market window.

2026-07-11 16:09:54 -05:00 America/Chicago

- Read automation memory first and refreshed compact context with repo venv Python: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\python.exe scripts/automation_context_snapshot.py --write`.
- Pre-run compact context flagged latest hourly notify/BOARD review, stale overnight/preopen/execution-board/loss-review lanes, and no recent watched-field changes. Risk posture from `config/risk_envelope.yaml`: `live_budget_mode: autonomous_with_caps`, account cap `$250`, per-name cap `$50`, tiny tranche `$25`; `results/policy/live_control.json` was not frozen but dead-man expired at `2026-06-04T19:57:06+00:00`, so posture stayed fail-closed unless unified guard allowed action.
- Ran pinned executable `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe`.
- `alpaca check`: paper `ACTIVE`, buying power `355808.07`, equity `97219.71`; live `ACTIVE`, buying power `86.42`, equity `199.72`.
- Dry run `alpaca supervise-hourly --dry-run --json-output --notification-policy urgent-exceptions ...`: `decision=loss-review`, `issues=[]`, `actions=[]`, `submitted=[]`, `market_session=closed`; packet `results\hourly_supervisor\hourly-supervisor-20260711-210702-805824.json`.
- Did not run `--submit-actions` because the dry-run had no valid actions to submit.
- Latest hourly reason: NFLX crossed loss review, but HOLD/loss-review stayed active because loss-exit evidence remains incomplete and market session was closed; BOARD/manual review required before any loss exit; new live buys paused while review is open.
- Alert state: `severity=NOTABLE`, `notify=true`, `email_suppressed=false`; sent Gmail alert to `nebulazer2003@gmail.com`, message id `19f53029146ba0c9`.
- Final live state from packet: exposure `114.99`, buying power `86.42`, equity `199.72`, unrealized P/L `-1.69`, positions AMZN/MA/NFLX/TSM, live open orders `0`.
- Final paper state from packet: buying power `355808.07`, equity `97219.71`, unrealized P/L `-2780.29`, paper open orders `0`.
- Refreshed rolling premarket brief with required command; latest checked brief `results\premarket_briefs\premarket-brief-20260711-210732-000000.json`, analysis-only, latest hourly decision `loss-review`, top symbol `JPM`, blockers `0`, stale warnings `0`, control locks `0`, material change live unrealized P/L `-1.87 -> -1.69`.
- Final context snapshot completed with repo venv Python; `results\_context\latest-summary.json` points to the new hourly packet and refreshed brief; `results\_context\recent-deltas.md` shows no watched-field changes.
- Mechanical checks observed: no live or paper orders submitted; no open live or paper orders; no crypto/options/shorts/margin/market orders. Timing note: run executed Saturday `2026-07-11 16:04-16:08 America/Chicago`; market session was closed, so this did not observe a real 30-min-after-open window.