# Task 4 — manual runtime runbook and source-gate evidence

## Status and boundary

This is a source-only runbook. It does not authorize or record a qualification,
paper submission, provider call, broker call, order cancellation, email delivery,
automation update, or schedule activation. All ten automation records must remain
`PAUSED`. `results/policy/live_control.json` remains frozen and is never refreshed,
rearmed, or rewritten.

Before a future manually started runtime, record `git status`, the SHA-256 of the
frozen live-control file, all ten automation TOML hashes and statuses, existing locks,
and read-only live/paper account, positions, and open-order snapshots. Stop before
runtime if any of the ten records is absent, contract-mismatched, or not `PAUSED`.
The automation API is not a runtime prerequisite and must not be used to correct the
records during this program.

Every future command below is launched from the canonical repository with
`TA_LIVE_SUBMIT=0`. Local result packets are expected writes; no command below may
change live-control, risk, promotion, credentials, capital, account settings, or an
automation status.

## Future manual qualification/trial sequence

The following replacement sequence is the only future runtime ordering. It is
intentionally **not run by this source task**. Start on a confirmed regular market
day by creating the immutable start record, then immediately prove the paused
preflight before any research or daily-chain work:

```zsh
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main research shadow-day-start \
  --run-id <fresh-run-id> --market-date <YYYY-MM-DD> --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main research safety-sentinel-audit \
  --shadow-start-object-id <start-object-id> --require-paused --json-output
```

`--require-paused` writes a HOLD evidence packet and exits nonzero if the exact
ten-record paused contract is not proven. Stop there on any failure. The remaining
observer chain uses the same start ID, runs only with `TA_LIVE_SUBMIT=0`, never uses
an outbox, and preserves every emitted packet path for the one final manifest.

1. Run one bounded one-ticker overnight probe (never retry it that day), then
   premarket brief, preopen validation, and `alpaca supervise-hourly --dry-run`.
   The persisted hourly packet must carry its explicit dry-run metadata.
2. Run bound sentinel, read-only `alpaca reconcile-observer`, loss-review evidence,
   BOARD review, `self-heal-handoff`, and `self-heal-plan --no-execute-safe`.
3. Render `alpaca supervisor-daily-report --no-write-outbox --json-output
   --compact-json-output` locally only.
4. Initialize the qualifier ledger in its own root, then run exactly one
   `alpaca paper-tournament run --all --dry-run --shadow-start-object-id
   <start-object-id>`. An optional explicitly owner-authorized paper
   `--submit-actions` tick, if ever used, happens **before** the sole manifest and
   adjudication; it never happens on repair days.
5. Create one 12-stage `research shadow-day-manifest`, then adjudicate exactly once.
   Finalize the qualifier only after that adjudication is clean. A trial uses a new
   five-day ledger root; do not finalize ordinary trial days, and finalize only after
   the clean Day 5 adjudication.

Use distinct roots such as `results/paper_strategy_tournament/qualifier-<run-id>`
and `results/paper_strategy_tournament/trial-<run-id>`; they must never overwrite
each other. Finalization reconciles only and closes the lease; it must neither
liquidate positions nor cancel ambiguous orders.

## Failure and count rules

Missing, stale, malformed, hash-mismatched, cross-run, provider/model/transport,
lock, reconciliation, authority, or configuration evidence makes the day failed or
incomplete. Stop all remaining runtime and paper submissions for that day, preserve
the exact artifacts, reserve the next regular market day for a deterministic repair,
obtain independent source review, and then require a new one-day qualification.

Only a complete clean qualification may begin a new five-day trial. The qualification
does not count as Day 1. Trial dates must be distinct regular market days; any failed
or incomplete trial day resets its clean streak to zero. A valid HOLD, empty candidate
set, or no qualifying paper order is not itself an error. Five clean days produce only
a non-authorizing readiness packet; they do not rearm live-control or authorize live
execution.

## Source evidence

## Exact future-only stage command fragment

This fragment records the one future-only manual sequence. It is not executed by
this source task. Every path below is retained as evidence; `<packet>` means the
exact path emitted by the immediately preceding named stage. Stop at the first
nonzero exit or malformed/stale packet. No command activates an automation.

```zsh
# 1. Create the daily identity, then prove all ten external automations are PAUSED
# before paper initialization, research, or any other daily work.
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main research shadow-day-start \
  --run-id <fresh-run-id> --market-date <YYYY-MM-DD> --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main research safety-sentinel-audit \
  --shadow-start-object-id <start-object-id> --require-paused --json-output

# 2. One bounded, analysis-only graph pass.  It never retries, writes latest,
# expands Reddit/provider context, appends an agent ledger, or refreshes top bundles.
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main alpaca plan-overnight \
  --full-graph-tickers 1 --per-ticker-timeout-minutes 2 --time-budget-minutes 3 \
  --overnight-graph-profile market-only --overnight-max-completion-tokens 800 \
  --overnight-llm-timeout-seconds 30 --overnight-llm-max-retries 0 \
  --no-research-context --no-agent-intelligence \
  --top-provider-bundle-count 0 --no-agent-ledger --no-write-latest \
  --log-dir results/overnight_plans/observer-<run-id> --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main alpaca premarket-brief \
  --overnight-log-dir results/overnight_plans/observer-<run-id> \
  --log-dir results/premarket_briefs/observer-<run-id> --no-write-latest --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main alpaca preopen-validation \
  --overnight-log-dir results/overnight_plans/observer-<run-id> \
  --premarket-brief-log-dir results/premarket_briefs/observer-<run-id> \
  --log-dir results/preopen_validation/observer-<run-id> --no-write-latest --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main alpaca supervise-hourly --dry-run \
  --no-write-outbox \
  --notification-policy material-only \
  --overnight-log-dir results/overnight_plans/observer-<run-id> \
  --premarket-brief-log-dir results/premarket_briefs/observer-<run-id> \
  --preopen-validation-dir results/preopen_validation/observer-<run-id> \
  --log-dir results/hourly_supervisor/observer-<run-id> --json-output

# 3. Bound all remaining observer stages to the same day.  The daily report
# writes no outbox; no command below submits or cancels a live order.
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main research safety-sentinel-audit \
  --shadow-start-object-id <start-object-id> --require-paused \
  --preopen-validation-path results/preopen_validation/observer-<run-id>/<preopen-packet> \
  --output-dir results/safety_sentinel/observer-<run-id> --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main alpaca reconcile-observer \
  --shadow-start-object-id <start-object-id> \
  --output-dir results/observer_reconciliation/observer-<run-id> --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main research loss-review-evidence \
  --hourly-dir results/hourly_supervisor/observer-<run-id> \
  --output-dir results/loss_review_evidence/observer-<run-id> --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main research execution-board-review \
  --hourly-dir results/hourly_supervisor/observer-<run-id> \
  --output-dir results/execution_board/observer-<run-id> --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main research self-heal-handoff \
  --no-refresh-context --output-dir results/self_heal/observer-<run-id> --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main research self-heal-plan --no-execute-safe \
  --no-refresh-context --output-dir results/self_heal/plans/observer-<run-id> --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main alpaca supervisor-daily-report \
  --no-write-outbox --log-dir results/hourly_supervisor/observer-<run-id> \
  --daily-report-log-dir results/daily_reports/observer-<run-id> \
  --compact-json-output --json-output

# 4. Qualifier-only paper ledger and a normal dry-run tick.  The trial uses the
# distinct trial root given below, never this qualifier root.
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main alpaca paper-tournament init \
  --duration-days 1 --max-submission-market-days 1 \
  --log-dir results/paper_strategy_tournament/qualifier-<run-id> --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main alpaca paper-tournament run --all --dry-run \
  --shadow-start-object-id <start-object-id> \
  --log-dir results/paper_strategy_tournament/qualifier-<run-id> --json-output
```

If an explicit paper-only action tick is separately authorized for the future
qualifier/trial, it replaces the dry-run paper packet **before** the one manifest
and adjudication. It is never run on a repair day:

```zsh
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main alpaca paper-tournament run --all \
  --submit-actions --shadow-start-object-id <start-object-id> \
  --log-dir results/paper_strategy_tournament/qualifier-<run-id> --json-output
```

Bind the final paper packet (dry-run or the explicitly authorized paper-only
submission packet) with exactly one complete 12-stage manifest and one adjudication:

```zsh
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main research shadow-day-manifest \
  --start-object-id <start-object-id> \
  --stage overnight_research=<packet> --stage premarket_brief=<packet> \
  --stage preopen_validation=<packet> --stage hourly_supervisor=<packet> \
  --stage safety_sentinel=<bound-sentinel> --stage loss_review=<packet> \
  --stage execution_board=<packet> --stage self_heal_handoff=<packet> \
  --stage self_heal_plan=<packet> --stage daily_report=<local-report> \
  --stage broker_reconciliation=<bound-reconciliation> \
  --stage paper_tournament=<bound-paper-run> --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main research shadow-day-adjudicate \
  --start-object-id <start-object-id> --safety-sentinel <bound-sentinel> \
  --paper-tournament <bound-paper-run> --daily-chain-manifest <manifest> --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main alpaca paper-tournament finalize \
  --log-dir results/paper_strategy_tournament/qualifier-<run-id> --json-output
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main research shadow-streak-report --json-output
```

Run `paper-tournament finalize` only after the preceding qualifier adjudication is
`clean`, then render the post-adjudication streak report. After a clean qualifier,
initialize a **new**, distinct five-day root with
`init --duration-days 5 --max-submission-market-days 5 --log-dir
results/paper_strategy_tournament/trial-<run-id>`. On each trial day repeat the same
start/sentinel-first observer sequence and bind the trial-root paper packet. Do not
finalize ordinary trial days; finalize only after the clean Day 5 adjudication, then
prove the closed lease rejects any future submission. Never overwrite a qualifier
ledger with a trial ledger, invoke outbox delivery, activate schedules, or turn this
non-authorizing readiness evidence into live execution authority.

- RED: `test_alpaca_supervisor_daily_report_no_write_outbox_keeps_report_local`
  initially failed because `--no-write-outbox` was not a recognized CLI option.
- GREEN: the same test now proves the local compact report exists while the hermetic
  outbox remains absent; a second default invocation proves the legacy outbox path is
  still written.
- Focused CLI regression plus the two existing daily-report CLI tests: `3 passed`.
- Dependent tournament daily-report test: `1 passed`.
- Full affected CLI module: `tests/test_alpaca_cli.py` — `119 passed`.
- Static source checks: Ruff on `cli/main.py` and `tests/test_alpaca_cli.py`,
  `compileall -q cli/main.py`, and `git diff --check` — all passed.
- All testing in this task uses fake CLI clients and temporary paths. No runtime,
  broker/provider/network, automation, scheduling, paper-submission, or email action
  was invoked.

## Source-gate baseline correction

- RED: `tests/test_automation_context_snapshot.py::test_installed_execution_board_prompt_owns_decision_but_not_execution` failed because its obsolete expected RRULE used `BYHOUR=9,10,11,12,13,14,15`, while the paused installed record and the versioned schedule contract both use `BYHOUR=8,9,10,11,12,13,14`.
- GREEN: updated only that installed-record assertion to the versioned contract value and documented the contract relationship in the test.
- Verification: `tests/test_automation_context_snapshot.py` — `45 passed`; Ruff on the changed test, `compileall -q` on the changed test, and `git diff --check` — all passed.
- This was a test baseline correction only. No automation API or TOML change, schedule activation, runtime/control mutation, provider/broker request, or live-control/results access occurred.
