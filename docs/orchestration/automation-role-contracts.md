# TradingAgents Automation Role and Schedule Contract

`config/automation_roles.json` is the source of truth for business authority.
`config/automation_schedule_contract.json` is the source of truth for the
ten current Codex automation records' intended Central-Time schedule, model
tier, prompt fingerprint, artifact expectations, ordering, and predeployment
no-submit posture.  These are deliberately separate: an authority change and
a scheduler configuration change have different review and activation gates.

## Current state

The contract has two status phases.  `predeployment_paused` requires all ten
external records to be `PAUSED`; that is the current safe predeployment state,
but it is **not** evidence that the schedule is deployed or healthy.
`frozen_observer` permits only overnight research, preopen validation,
self-healer, safety sentinel, execution BOARD, paper tournament, and daily
report to be `ACTIVE`.  Market supervisor plus wake and sleep controllers must
remain `PAUSED`, and every active role remains contractually `no_submit`.
The market supervisor is deliberately `no_submit: false`: its scheduled command
is order-capable and remains safe in these phases only because it is required to
stay `PAUSED`.

Neither phase proves a schedule is deployed or healthy.  A schedule is
deployable only after all of the following exist:

1. The external TOML matches the versioned contract.
2. The automation API returns the next scheduled run in both Central and UTC.
3. Current no-submit shadow evidence proves `execution_authority: none`,
   `can_submit_orders: false`, and zero submissions.
4. Current expected artifacts pass automation-health checks.

This contract never changes an external automation.  Its test reads the TOMLs
from `$CODEX_HOME/automations` (or `~/.codex/automations`) and reports field
drift as structured `mismatch` rows.  Predeployment records remain
`not_deployed`, even if every source field matches.

## Contract fields

Each exact automation ID has:

- `timezone`: the global `America/Chicago` schedule interpretation;
- the intended `rrule`, model, reasoning effort, and `failed_runs_only`
  notification policy;
- the exact display name, local project target, cwd list, and execution
  environment recorded by the external TOML;
- a role mapped to `config/automation_roles.json`;
- a SHA-256 prompt fingerprint plus semantic required/forbidden phrases;
- expected artifact patterns and ordering dependencies;
- a `no_submit` invariant for every frozen-observer active role; an
  order-capable record is permitted only when every no-submit observer phase
  requires it to stay paused;
- exact `PAUSED`/`ACTIVE` membership for both named deployment phases.

The prompt digest catches unreviewed prompt changes.  The semantic clauses
catch known safety requirements that a digest alone cannot describe.  In
particular, the sentinel is intentionally Luna/medium for deterministic
verification and must escalate uncertain diagnosis; the self-healer is a
weekday market-session reliability controller, not a fictitious 24/7 service.

## Intended Central-Time matrix

| Automation ID | Intended CT schedule | Model / effort | Dependency |
| --- | --- | --- | --- |
| `tradingagents-overnight-research` | Weekdays 03:30 | Terra / high | — |
| `tradingagents-automation-wake-controller` | Weekdays 06:45 | Luna / medium | — |
| `tradingagents-autonomous-self-healer` | Weekdays 07:03, 09:03, 11:03, 13:03, 15:03 | Terra / high | — |
| `tradingagents-preopen-validation` | Weekdays 08:10 | Terra / high | Overnight research |
| `tradingagents-autonomous-safety-sentinel` | Weekdays 08:20, then hourly through 14:20 | Luna / medium | Preopen + self-healer |
| `tradingagents-market-supervisor` | Weekdays 08:35, then hourly through 14:35 | Terra / high | Sentinel |
| `tradingagents-autonomous-execution-board` | Weekdays 08:50, then hourly through 14:50 | Terra / high | Sentinel + supervisor |
| `tradingagents-paper-tournament` | Weekdays 09:10 | Terra / high | Overnight research |
| `tradingagents-daily-report` | Weekdays 15:30 | Luna / medium | BOARD |
| `tradingagents-automation-sleep-controller` | Weekdays 16:45 | Luna / medium | Daily report |

The currently observed external RRULEs are not yet the deployment proof for
this matrix.  The existing one-hour schedule drift, the self-healer's `24/7`
claim, and the scheduled-paper dry-run issue are intentionally reported rather
than silently normalized.  Any external correction remains `PAUSED` until a
separate API-confirmed, no-submit shadow validation completes.

## Read-only verification

```zsh
PYTHONDONTWRITEBYTECODE=1 /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python \
  -m pytest -q -p no:cacheprovider tests/test_automation_role_contracts.py
```

The evaluator lives in `tradingagents/evals/automation_health_audit.py` as
`evaluate_schedule_contract`.  Its optional `deployment_phase` argument
defaults to `predeployment_paused`; pass `frozen_observer` only when evaluating
that exact status contract.  It performs source reads only and must never be
used to activate, pause, update, re-arm, or otherwise mutate an automation.
