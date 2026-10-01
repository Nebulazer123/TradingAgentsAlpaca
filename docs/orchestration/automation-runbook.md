# Automation role procedures

Load only the entry for the running role. Job identity, schedule, model, prompt
binding, deployment phase and dependencies live in
`config/automation_schedule_contract.json`; business roles and action separation
live in `config/automation_roles.json` and `config/autonomous_firm.json`.
The source prompts are `config/automation_prompts/<automation-id>.md`.

## Shared operational scope

An activated job performs its defined role, using current policy at call time.
Activation and additional financial, message, or credential authority require
the owner's separate scope; job instructions cannot grant them. Inspect
`docs/harness/BOUNDARIES.md` when the role encounters a protected operation.
Use compact context for relevant packet discovery, then current controls and
the exact evidence needed by the role. Refresh it after packet inputs change.

Record complete machine outputs in their existing packet/log owners. Human
updates report changed state, material actions, failures and blockers. Link
evidence supporting those claims; routine success needs no global status recap.

## Schedule controllers

Inspect actual TradingAgents records and the contract's deployment phase before
evaluating status work. Without the owner's activation authority, evaluation is
read-only. An audit or a model decision cannot advance deployment phase.
Unknown IDs need investigation, not status mutation.

The wake/sleep controllers preserve each other's records. Use the contract's
market-day IDs and dependencies instead of copying a second timetable.
For an authorized activated cadence, wake uses the current market calendar,
applies the allowed market-day phase and pauses overnight research after its
window. Sleep pauses that group after the report and evaluates whether the next
overnight run prepares for a real trading day. A weekday fallback is an explicit
calendar limitation. Keep the supervisor ineligible without its specific current
readiness and scheduling authority. Change status only with the automation tool,
preserving all other fields; read back changed records and run controller-patrol.
Schedule roles have no broker, repair, strategy, risk or control-write authority.

## Execution BOARD

Use `.venv/bin/python -m cli.main` for `alpaca check`,
`research loss-review-evidence --json-output`, and
`research execution-board-review --json-output`, then refresh context.
The current immutable evidence and policy determine HOLD/SELL; invalid or
insufficient evidence produces HOLD. Keep `analysis_only=true`,
`execution_authority=none`, and `can_submit_orders=false` in the packet.
Decision authority does not include orders, policy edits, or control writes.

## Safety sentinel

Perform the existing integrity-verifier role using current controls, promotion,
authorized broker/order reads, packets, schedule audit, and lock ownership.
Unknown/corrupt/unreconciled safety integrity invokes the existing freeze-only
path with its specific evidence. Otherwise record CLEAR/HOLD/FROZEN as policy
requires. Repair belongs to the self-healer; rearming, orders, strategy/risk,
promotion, and credential changes are outside this role.

## Self-healer

Inspect current deployment expectations, relevant locks/processes, localhost
n8n health and current role packets. Use `research self-heal-handoff --json-output`
and `research self-heal-plan --execute-safe --json-output`. Existing bounded
recipes and role checks govern local observer repairs; verify changed behavior.
Clear a stale lock only after proving no owner process exists. A defined
broker/order/scheduler/control integrity failure takes the existing
`policy freeze-live --reason <specific failure> --json-output` route. Other
dependencies can remain blocked while independent repairs continue. This role
cannot rearm, order, expand strategy/risk/promotion, or expose credentials.

## Wrapper roles

Use `scripts/mac/ta_job.sh` for overnight research, preopen validation, tournament,
daily report and the supervisor. Preopen and tournament use the wrapper's dry-run
routes. The supervisor is the only role that requests the existing hourly action
route, with all current broker and execution gates. None of these roles edits
source code or product/trading configuration, or extends control expiry during
an operational run. Source repair belongs to the scoped self-healer or an
authorized development task.

The daily report queues a local message. `deliver-outbox` previews the backlog.
Separately authorized sending uses
`.venv/bin/python scripts/mac/deliver_outbox.py --send --message-id <queued-id>`;
each selected ID needs scope. SMTP credentials or `TA_LIVE_SUBMIT` alone cannot
send. Inspect failed delivery without printing secrets and leave unsent items
queued. Source-only development uses fixtures instead of running these jobs.
