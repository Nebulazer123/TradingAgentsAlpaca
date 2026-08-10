# TradingAgents preopen validation memory

## 2026-07-30 13:19:08 UTC

- Ran exactly once from the production repo: `TA_LIVE_SUBMIT=0 /bin/zsh scripts/mac/ta_job.sh preopen`.
- Wrapper exited 0. No code/config edits were made; the pre-existing dirty worktree was left untouched.
- Overall result: WARN, no FAIL. Fresh preopen was `pass_with_warnings` (4 pass, 1 warn) because live-control is frozen/closed.
- Fresh quote and research checks passed with no stale warnings. The overnight plan and premarket brief were amended after the ranking shifted from LLY to NVDA.
- The hourly packet ran two seconds before the fresh preopen packet. It consumed the 2026-07-28T17:28:12Z preopen packet, age 157,775 seconds, status `blocked`, and invalidated the LLY overnight/brief context because NVDA became the current top candidate.
- Accounts/orders: live and paper accounts ACTIVE; 3 live and 14 paper positions; zero open orders in both; zero submitted or reconciled orders.
- Hourly remained dry-run (`can_submit_orders=false`, `execution_authority=none`) and prepared a $21.72 TSM live close at a $389.02 limit plus hold-cash action, submitting neither.
- Live-control remains frozen because filled manual NFLX order `e5d06403-6ed5-4159-97f2-d45b9d0585aa` lacks a durable TradingAgents external-action execution-history artifact, replay suppression remains unproven, and two same-day TSM close evaluations produced different idempotency keys.
- Packet paths:
  - `results/preopen_validation/preopen-validation-20260730-131749.json`
  - `results/hourly_supervisor/hourly-supervisor-20260730-131747-098053.json`
  - `results/mac_automation/logs/preopen-20260730-091741.log`

## 2026-07-28 13:18:05 UTC

- Ran exactly once from the production repo: `TA_LIVE_SUBMIT=0 /bin/zsh scripts/mac/ta_job.sh preopen`.
- Wrapper exited 0 and generated fresh packets at 13:17 UTC. No code/config edits were made; the pre-existing dirty worktree was unchanged.
- Overall result: WARN, no FAIL. Preopen was `pass_with_warnings` (4 pass, 1 warn) because live-control is frozen/closed.
- Fresh preopen quote and research checks passed. The overnight plan and premarket brief were amended because the ranking shifted from CVX to AVGO, but neither was marked stale.
- The hourly packet ran two seconds before today's preopen packet and referenced the prior 2026-07-27 preopen packet, age 63,873 seconds, status `blocked`, session `pre_close`.
- Accounts/orders: live and paper accounts ACTIVE; 3 live and 14 paper positions; zero open orders in both; zero submitted or reconciled orders.
- Hourly remained dry-run (`can_submit_orders=false`, `execution_authority=none`) and prepared a $21.47 TSM live close plus hold-cash action, submitting neither.
- Live-control remains frozen because the manually executed NFLX sale is not durably reconciled, stale-intent replay suppression is unproven, promotion evidence predates the new live strategy, a protected supervisor cycle lacked a completed pre-boundary sentinel gate, and live-gate code/tests are dirty.
- Packet paths:
  - `results/preopen_validation/preopen-validation-20260728-131709.json`
  - `results/hourly_supervisor/hourly-supervisor-20260728-131707-187387.json`
  - `results/mac_automation/logs/preopen-20260728-091701.log`

## 2026-07-27 13:53:24 UTC

- Ran exactly once from the production repo: `TA_LIVE_SUBMIT=0 /bin/zsh scripts/mac/ta_job.sh preopen`.
- Wrapper exited 0 and generated fresh packets at 13:50 UTC.
- Overall result: WARN, no FAIL. Preopen was `pass_with_warnings` (4 pass, 1 warn) because `live_sizing_room_and_buying_power` found live-control frozen.
- Live-control remains fail-closed due the July 23 scheduler/sentinel overlap, sentinel reasoning-effort mismatch, and paused/stale overnight-research memory.
- Freshness: the premarket brief and linked research context passed with no stale warnings, but the hourly packet separately marked the overnight plan stale or missing; its latest timestamp was 2026-07-24T22:20:37Z.
- Accounts/orders: live and paper accounts ACTIVE; 4 live and 14 paper positions; zero open orders in both; zero submitted or reconciled orders.
- Hourly remained dry-run (`can_submit_orders=false`, `execution_authority=none`) and prepared a $22.53 NFLX live close plus hold-cash action, submitting neither.
- Packet paths:
  - `results/preopen_validation/preopen-validation-20260727-135041.json`
  - `results/hourly_supervisor/hourly-supervisor-20260727-135025-980327.json`
  - `results/mac_automation/logs/preopen-20260727-095013.log`

## 2026-07-17 13:17:03 UTC

- Ran exactly once from the production repo: `TA_LIVE_SUBMIT=0 /bin/zsh scripts/mac/ta_job.sh preopen`.
- Wrapper completed successfully and generated fresh packets at 13:16 UTC.
- Overall result: WARN, no FAIL. Preopen was `pass_with_warnings` (4 pass, 1 warn) because live-control is frozen/closed or expired.
- Freshness: market quote and premarket research checks passed with no stale warnings. The warning cites lagging/conflicting governance evidence: promotion state dated 2026-06-20 versus tournament evidence dated 2026-07-16, plus prior loss-review/BOARD evidence that retained manual review.
- Accounts/orders: live and paper accounts ACTIVE; 4 live and 14 paper positions; zero open orders in both; zero submitted or reconciled orders.
- Hourly remained dry-run (`can_submit_orders=false`, `execution_authority=none`) and prepared an NFLX live close plus hold-cash action, submitting neither.
- Packet paths:
  - `results/preopen_validation/preopen-validation-20260717-131610.json`
  - `results/hourly_supervisor/hourly-supervisor-20260717-131609-532407.json`
