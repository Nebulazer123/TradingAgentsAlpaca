## 2026-05-29 14:33:42 -05:00

- Ran `.\.venv\Scripts\python.exe -m cli.main alpaca check`: paper `ACTIVE`, live `ACTIVE`, live buying power `100`, live equity `202.27`.
- Ran dry run `alpaca supervise-hourly --dry-run --json-output --notification-policy urgent-exceptions --log-dir results/hourly_supervisor`.
- Dry-run result: `decision=profit-review`, `reason=MSFT reached profit review threshold`, `live_exposure=100.00`, `actions=[]`, `issues=[]`, `notify=false`.
- Close-prep state: no open live orders, no stale orders to cancel, positions remain `GOOGL`, `MSFT`, `NVDA`, and no replacement rotation qualified within the `$100` live cap.
- Submit-capable run was intentionally skipped because the required gate was not met: the dry run returned no actions.
- Packet to compare next run against: `results\hourly_supervisor\hourly-supervisor-20260529-193311.json`.

## 2026-06-01 14:36:10 -05:00

- Ran `tradingagents.exe alpaca check`: paper `ACTIVE`, live `ACTIVE`, live buying power `50`, live equity `204.01`.
- Ran dry run `alpaca supervise-hourly --dry-run --json-output --notification-policy urgent-exceptions --log-dir results/hourly_supervisor --overnight-log-dir results/overnight_plans --paper-tournament-log-dir results/paper_strategy_tournament --premarket-brief-log-dir results/premarket_briefs`.
- Dry-run result: `decision=blocked`, `material=true`, `reason=hourly supervisor action failed guardrail validation`, `live_exposure=150.00`, `actions=[paper-first ORCL buy $100.00 limit $250.14]`, `issues=[live-exposure: new live buy would exceed live exposure limit without a paired reduction]`.
- Submit-capable run was skipped because the dry-run had an issue; no live orders were submitted.
- Refreshed rolling premarket brief: `results\premarket_briefs\premarket-brief-20260601-193349-000000.json`; analysis-only, latest hourly decision `blocked`, unresolved blockers `3`, paper tournament leader `current-aggressive`.
- Urgent exception email sent to `nebulazer2003@gmail.com`; Gmail message id `19e84af65b80ac47`.
- Packet to compare next run against: `results\hourly_supervisor\hourly-supervisor-20260601-193308-733004.json`.

## 2026-06-01 14:41:20 -05:00

- User clarified paper trades are acceptable, but asked what live trades were being requested/blocked.
- Inspected blocked hourly packets `20260601-180437`, `20260601-190440`, `20260601-193308`, and fresh `20260601-193922`; none requested a live order. Each blocked action was `ORCL` buy, `account=paper`, `execution_mode=paper_first`, with live-exposure issue triggered because existing live exposure was already `150.00` vs dynamic cap `100.00`.
- Ran fresh `alpaca check`: paper `ACTIVE`, live `ACTIVE`, live buying power `50`, live equity around `203.84-203.88`.
- Ran fresh hourly dry run: `results\hourly_supervisor\hourly-supervisor-20260601-193922-433917.json`; result remained `decision=blocked`, `actions=[paper ORCL buy $100 limit $249.68]`, `issues=[live-exposure]`, `submitted=[]`.
- Ran paper-tournament dry run `alpaca paper-tournament run --all --dry-run --json-output --log-dir results/paper_strategy_tournament`: `actions=[]`, `payloads=[]`, `submitted_count=0`; no paper-only tournament orders were available to submit.
- Refreshed rolling premarket brief: `results\premarket_briefs\premarket-brief-20260601-194105-000000.json`; latest hourly decision `blocked`, unresolved blockers `4`, paper tournament leader `current-aggressive`.

## 2026-06-02 14:46:52 -05:00

- Refreshed compact context with `python scripts/automation_context_snapshot.py --write`; flags required drilldown for a prior submitted hourly action, research quality context, model telemetry, and promotion state.
- Prior flagged packet `results\hourly_supervisor\hourly-supervisor-20260602-191113-454996.json` had already submitted a tiny live `AMZN` buy for about `$25.00`; no issues; order status at packet write was `pending_new`.
- Ran `tradingagents.exe alpaca check`: paper `ACTIVE`, live `ACTIVE`, live buying power `127.44`, live equity `202.37`.
- Ran close-prep dry run `alpaca supervise-hourly --dry-run --json-output --notification-policy urgent-exceptions ...`: packet `results\hourly_supervisor\hourly-supervisor-20260602-193935-959070.json`; clean action `buy NFLX live ~$38.23 limit $83.67`, `issues=[]`, `submitted=[]`, `notify=true`.
- Because the dry run had a valid action and no issues, ran the same supervisor command with `--submit-actions`; final packet `results\hourly_supervisor\hourly-supervisor-20260602-194058-098596.json` submitted tiny live `MA` buy for about `$38.23`, limit `$482.26`, order id `5aee7f47-0073-4db3-9e51-3fb813923c8a`, client id `ta-tiny-20260602-current-ma-buy-3a1e51e9c6`, status `pending_new`, no issues.
- Refreshed rolling premarket brief: `results\premarket_briefs\premarket-brief-20260602-194152-000000.json`; analysis-only, latest hourly decision `buy`, unresolved blockers `0`, stale warnings `0`, paper tournament leader `current-aggressive`.
- Sent NOTABLE alert email to `nebulazer2003@gmail.com`; Gmail message id `19e89de767c41f62`.

## 2026-06-03 14:38:10 -05:00

- Refreshed compact context with `python scripts/automation_context_snapshot.py --write`; latest hourly state was already `loss-review` with no actions/issues/submissions. Raw drilldowns opened for flagged automation health, self-heal, and connector health only; they were analysis-only/nonblocking for this close-prep run.
- Required executable `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.venv\Scripts\tradingagents.exe` was missing, and PATH had an older user-level `tradingagents.cmd`; used direct repo venv fallback `.\.venv\Scripts\python.exe -m cli.main ...` to avoid PATH drift.
- Ran repo-local `alpaca check`: paper `ACTIVE`, paper buying power `169298.21`, paper equity `99637.47`; live `ACTIVE`, live buying power `86.38`, live equity `198.61`.
- Ran dry run `alpaca supervise-hourly --dry-run --json-output --notification-policy urgent-exceptions --log-dir results/hourly_supervisor --overnight-log-dir results/overnight_plans --paper-tournament-log-dir results/paper_strategy_tournament --premarket-brief-log-dir results/premarket_briefs`.
- Dry-run packet: `results\hourly_supervisor\hourly-supervisor-20260603-193730-878220.json`; `decision=loss-review`, `reason=AMZN crossed loss review but loss-exit evidence is missing`, `live_exposure=114.99`, `actions=[]`, `issues=[]`, `submitted=[]`, live positions `AMZN, MA, NFLX, TSM`, open live orders `0`, top candidates `GOOGL, AAPL, ADBE, TSM, V`.
- Submit-capable run was skipped because the dry-run had no valid actions. Alert was `NOTABLE` but `alert.notify=false`, `email_suppressed=true`, `suppression_reason=same-cause alert already emitted inside throttle window`; no email sent.
- Refreshed rolling premarket brief: `results\premarket_briefs\premarket-brief-20260603-193810-000000.json`; analysis-only, latest hourly decision `loss-review`, unresolved blockers `0`, stale warnings `0`, paper tournament leader `pullback-support`.
- Packet to compare next run against: `results\hourly_supervisor\hourly-supervisor-20260603-193730-878220.json`.
## 2026-06-04 14:35:55 -05:00

- Refreshed compact context with python scripts/automation_context_snapshot.py --write; flags required drilldown for paper tournament candidate change only. Tournament leader/candidate remained pullback-support; packet is paper/analysis-only with no execution authority.
- Ran pinned repo executable tradingagents.exe alpaca check: paper ACTIVE, paper buying power 338638.6, paper equity 99658.56; live ACTIVE, live buying power 86.38, live equity 200.29.
- Ran close-prep dry run alpaca supervise-hourly --dry-run --json-output --notification-policy urgent-exceptions ...; packet results\hourly_supervisor\hourly-supervisor-20260604-193419-588316.json; decision hold; live_exposure 114.99; actions 0; issues 0; submitted 0; alert severity ROUTINE; notify False.
- Submit-capable run skipped because dry-run produced no valid actions. No live or paper orders submitted; final live open orders 0; live positions AMZN, MA, NFLX, TSM; live unrealized P/L -1.10.
- Refreshed rolling premarket brief: results\premarket_briefs\premarket-brief-20260604-193441-000000.json; analysis-only, latest hourly decision hold; unresolved blockers 0; stale warnings 0; paper tournament leader pullback-support; top symbol KO.
- Email not sent: alert was ROUTINE and notify=false.

## 2026-06-08 14:39:13 -05:00

- Refreshed compact context with repo venv Python after system `python scripts/automation_context_snapshot.py --write` failed on `ModuleNotFoundError: No module named 'tradingagents'`; compact flags were order-adjacent review/stale/quality/audit context with no watched-field deltas.
- Ran pinned repo executable `tradingagents.exe alpaca check`: paper `ACTIVE`, paper buying power `359203.34`, paper equity `98432.31`; live `ACTIVE`, live buying power `86.38`, live equity `198.90`.
- Ran close-prep dry run `alpaca supervise-hourly --dry-run --json-output --notification-policy urgent-exceptions ...`; packet `results\hourly_supervisor\hourly-supervisor-20260608-193625-238239.json`; decision `loss-review`; live exposure `112.52`; live unrealized P/L `-2.46`; live positions `AMZN, MA, NFLX, TSM`; open live orders `0`; actions `0`; issues `0`; submitted `0`.
- Submit-capable run skipped because the dry-run produced no valid actions. No live or paper orders submitted; HOLD/loss-review remains default and new live buys are paused while BOARD/manual loss-exit evidence is unresolved.
- Alert was `NOTABLE` with `notify=true` and `email_suppressed=false`; sent rendered alert email to `nebulazer2003@gmail.com`, Gmail message id `19ea8be7895134b2`.
- Refreshed rolling premarket brief: `results\premarket_briefs\premarket-brief-20260608-193652-000000.json`; analysis-only, latest hourly decision `loss-review`, unresolved blockers `0`, stale warnings `0`, paper tournament leader `pullback-support`, top symbol `XOM`, material change: live unrealized P/L moved from `-2.07` to `-2.46`.

## 2026-06-11 00:54:27 -05:00

- Read automation memory, refreshed compact context; plain `python scripts/automation_context_snapshot.py --write` still failed with `ModuleNotFoundError: No module named 'tradingagents'`, then repo venv Python wrote `results\_context\latest-summary.json`, `latest-flags.json`, and `recent-deltas.md`.
- Compact flags showed stale/BOARD/research drilldowns but no watched-field deltas. Local posture: `config\risk_envelope.yaml` is `live_budget_mode=autonomous_with_caps`, account cap `$250.00`, per-name cap `$50.00`; `results\policy\live_control.json` dead-man remains expired at `2026-06-04T19:57:06+00:00`.
- Ran pinned repo executable `tradingagents.exe alpaca check`: paper `ACTIVE`, buying power `355665.43`, equity `97168.76`; live `ACTIVE`, buying power `86.38`, equity `197.83`.
- Ran close-prep dry run `alpaca supervise-hourly --dry-run --json-output --notification-policy urgent-exceptions ...`; latest final supervisor packet `results\hourly_supervisor\hourly-supervisor-20260611-055245-932837.json`; decision `loss-review`; live exposure `111.44`; actions `0`; issues `0`; submitted `0`; reconciled orders `0`; market session `closed`.
- Submit-capable run skipped because there were no valid actions. No live or paper orders submitted. HOLD/loss-review remains active for TSM; BOARD/manual review required before any loss exit; new live buys remain suspended by BOARD review.
- Final live posture from packet: live buying power `86.38`, equity `197.82`, unrealized P/L `-3.54`, positions `AMZN, MA, NFLX, TSM`, open live orders `0`; paper buying power `355661.06`, equity `97167.21`, open paper orders `0`.
- Alert was `NOTABLE` but `notify=false`, `email_suppressed=true`, suppression reason `same-cause alert already emitted inside throttle window`; no email sent.
- Refreshed rolling premarket brief: `results\premarket_briefs\premarket-brief-20260611-055239-000000.json`; analysis-only, unresolved blockers `0`, stale warnings `0`, material change `no_material_change`.

