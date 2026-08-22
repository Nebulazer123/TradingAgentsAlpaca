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

For every run-bound or `--require-paused` sentinel invocation, the command itself
pins schedule capture to the private canonical path
`/Users/corbinfloyd/.codex/automations`. Do not supply `--automation-root` in this
preflight: a conflicting override is rejected before broker reads or packet writes.
`CODEX_HOME` and `HOME` do not select the preflight source. The option remains only
for an unbound, non-qualifying observer inspection.

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

This means explicit paper submission is permitted only after broker clock proves
regular session open: the exact paper client must return a timezone-aware `/v2/clock`
timestamp within 15 minutes of the local policy time, `is_open` must be the exact
boolean `true`, and its America/Chicago date must be the current qualifying market
date. A missing, malformed, stale, future, closed, after-hours, or wrong-date
clock rejects before the durable submission transaction and before any paper POST.
The CLI completes the broker calendar lookup before its final exact paper-clock
read, so a slow calendar reply cannot leave a stale authorization window. It then
brackets that final clock response with local policy time. The post-response local
sample is authoritative for every time-sensitive lease check (start, expiry,
current Central date, and day capacity); it must not move backward from the
pre-request sample, and both final policy and broker clock dates must match the
queried calendar date. The CLI repeats that complete boundary check immediately
before it persists the transaction and immediately before every POST. A delayed
preparation fails before the transaction with zero posts. A close-boundary failure
after a prior POST seals recovery-required evidence and makes zero additional
posts. Successful submission evidence must have nondecreasing `recorded_at`
values (equal times are valid), so a persisted reverse-order response record is
recovery-required rather than eligible for finalization.

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
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main research shadow-streak-status --json-output
```

Run `paper-tournament finalize` only after the preceding qualifier adjudication is
`clean`, then inspect progress only with the read-only `shadow-streak-status`. That
command appends nothing to the pinned ledger and never blocks Trial Day 1. Never call
the terminal `research shadow-streak-report` after qualification or after Trial Days
1–4: it admits a terminal readiness record that permanently closes the ledger. After a
clean qualifier, initialize a **new**, distinct five-day root with
`init --duration-days 5 --max-submission-market-days 5 --log-dir
results/paper_strategy_tournament/trial-<run-id>`. On each trial day repeat the same
start/sentinel-first observer sequence and bind the trial-root paper packet. Do not
finalize ordinary trial days; finalize only after the clean Day 5 adjudication, then
prove the closed lease rejects any future submission, and only then emit the terminal
readiness record exactly once:

```zsh
# Terminal program record — valid only after the clean Day 5 adjudication and
# trial-root finalization, or as an explicit owner-decided final NO-GO via
# `research shadow-streak-report --final-no-go`. Never run it earlier.
TA_LIVE_SUBMIT=0 .venv/bin/python -m cli.main research shadow-streak-report --json-output
```

Never overwrite a qualifier
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

## Final source-gate evidence

- Final integrated source HEAD: `269cc134f542e6d83c2efc06136ec30baed41b3d` (`fix: recheck paper clock after calendar`).
- Independent Sol review: approved with P0=0 and P1=0; one non-blocking P2 remains about `started_at` labeling the validation-boundary sample rather than the exact durable-write instant.
- Full repository suite: `3905 passed, 1 skipped, 11 warnings, 75 subtests passed in 405.21s (0:06:45)`. The single skip is the existing DeepSeek live-API test because `DEEPSEEK_API_KEY` is not configured. Warnings are existing model-name/runtime warnings and the authority-inventory source-parser warnings.
- Static/source checks: `ruff check cli tradingagents scripts tests` passed; `compileall -q cli tradingagents scripts` passed; `git diff --check master...HEAD` passed; `zsh -n scripts/mac/ta_job.sh` passed.
- At source-gate capture, canonical `master` was clean at `6a68cecb79c9af07b05676d60dfd266babfa97fb`; the feature worktree remained clean at the reviewed HEAD. The later local fast-forward is recorded below.
- Frozen live-control SHA-256 remained `a3fc5ddb2b300596833c48c1554fad088ecb43d46bd70aeeac074531d6e9fb07`; no refresh, rearm, unfreeze, or write occurred.
- All ten TradingAgents automation records retained their preflight SHA-256 values and `status = "PAUSED"`; no automation API/TOML update or schedule activation occurred.
- The isolated worktree contains 122 ignored `results/` files from prior/test-only activity: 60 `manual_alpaca_submit`, 51 `research_evidence`, one `policy` lock, one `safety_sentinel`, plus the ignored `_context` index. These were inventoried and preserved, not treated as qualification evidence and not deleted. No qualification or five-day runtime trial has run.
- Runtime rollout remains unstarted. Task 5 stays blocked until a future regular market day is explicitly chosen for the manual one-day qualification; schedules remain paused, live control remains frozen, and no live or paper transport was invoked by the source gate.

## Post-merge finishing verification

- Canonical `master` was fast-forwarded from the recorded base through `25e67f3f95fe44674bccc620596ebbdc089b5b6f` (`docs: record final clean-day source gate`); this report-only verification update is the later canonical commit. The isolated `codex/clean-day-paper-trial` worktree remains clean at the source-gate commit for inspection; no remote, PR, push, or historical-worktree cleanup was performed.
- A fresh detached worktree at the exact merged commit, with no ignored operational `results/` evidence, passed the full repository suite: `3905 passed, 1 skipped, 12 warnings, 75 subtests passed in 408.34s (0:06:48)`. The single skip is the existing DeepSeek live-API test because `DEEPSEEK_API_KEY` is not configured.
- A direct suite run from canonical `master` exposed two environment-dependent `tests/test_execution_board.py` failures because pre-existing ignored `results/loss_review_evidence/` packets are intentionally visible to the default BOARD review path. The same two tests pass in the clean feature/base worktrees and in the fresh merged verification worktree; the ignored evidence was neither modified nor deleted. This is recorded as an evidence-environment finding, not waived as a source failure.
- Post-merge static checks passed: `ruff check cli tradingagents scripts tests`, `compileall -q cli tradingagents scripts`, `git diff --check`, and `zsh -n scripts/mac/ta_job.sh`. Canonical `master` is clean after the documentation update.
- The frozen live-control SHA-256 is still `a3fc5ddb2b300596833c48c1554fad088ecb43d46bd70aeeac074531d6e9fb07`; all ten TradingAgents automation records remain `PAUSED` with the preflight hashes; no schedule was activated and no broker/provider/network transport was invoked.

## Ox-assisted verification repair checkpoint

- Ox Alpha implemented the bounded analysis-only CLI seam in `cli/main.py`: `research execution-board-review` now accepts `--loss-review-evidence-dir`, while its production default remains `results/loss_review_evidence` and the canonical decision/evidence roots remain hardcoded and unchanged.
- Ox Alpha made `tests/test_execution_board.py` hermetic with an autouse temporary working directory, explicit empty evidence paths for the two formerly contaminated cases, and a non-empty custom-evidence CLI test. The custom test deliberately breaks source binding, asserts `analysis_only=true`, `execution_authority=none`, `can_submit_orders=false`, and proves the canonical decision-ledger bytes do not change.
- The exact-source authority inventory was refreshed for the two moved multiprocessing queue transports: `cli/main.py:5244` remains classified as the non-trading local result queue and `cli/main.py:5256` as the non-trading local error queue. No wildcard, broad exemption, or new mutation class was introduced.
- Focused verification: execution-board, Alpaca CLI, and policy-authority suites — `170 passed`; full authority-role suite — `53 passed`; Ruff, compileall, wrapper syntax, and diff checks — passed.
- Canonical full repository verification after both repairs: `3906 passed, 1 skipped, 11 warnings, 75 subtests passed in 424.49s (0:07:04)`. The DeepSeek live-API test remains the single configured-key skip. The earlier two execution-board environment failures and the later stale-coordinate inventory failure are both resolved.
- Canonical graph was refreshed at `91ddbdb6b7eb7b15e999f6dbd9d698a4566df1e7` with 12,212 nodes and 74,427 edges, no skipped files, and one unrelated parse-partial Dockerfile range in the archived MiroFish transfer. This graph is structural evidence only; ignored results/docs remain direct-read lanes.
- Runtime remains intentionally unstarted: all ten TradingAgents automations are still paused, live control remains frozen at the recorded SHA-256, and no broker/provider/network transport, paper submission, schedule activation, email, promotion, rearm, or live order occurred. Task 5 remains pending for a future confirmed regular market day.
- Post-verification ignored-results inventory: 15,177 files under `results/`; 15 files have current-session timestamps (11 `research_evidence` test packets and 4 `manual_alpaca_submit` refusal packets). The four refusal packets report `submitted_count=0`, `estimated_spent_this_run_by_account.live=0.00`, and `estimated_spent_this_run_by_account.paper=0.00`; the research packets are `analysis_only`. These are preserved, explicitly excluded from qualification evidence, and were not deleted.

## Ox Alpha Task 5 boundary audit

- Ox Alpha performed a fresh read-only audit in the isolated `codex/clean-day-paper-trial` worktree at `c216ff554f5396b2634cb82a5c04237435176dff`. All 19 documented runbook command fragments were mapped to the current Typer registrations and exact option sets; no stale command or undocumented flag was found.
- The audit rechecked the safety boundary: the sentinel remains observer-only and writes its packet before a `--require-paused` failure; the paper lease remains exact-paper-endpoint, Central-session, current-ledger, date-capacity, and per-submit-clock bound; qualification/trial ledgers cannot write live-strategy selections; the twelve-stage manifest and anchored adjudication reverify paths, hashes, same-day identity, frozen-control continuity, and all-ten-paused evidence.
- Hermetic verification in the feature worktree used the canonical interpreter with the feature source first on `PYTHONPATH`: `tests/test_paper_tournament.py tests/test_safety_sentinel.py tests/test_shadow_trial.py tests/test_alpaca_cli.py` — `261 passed`; Ruff and `git diff --check` passed. No runtime, broker, network, schedule, control, paper, or email action was invoked.
- Ox found no concrete bounded source defect relevant to preventing unsafe or misleading qualification/trial evidence, so no source change was made. Task 5 is therefore a real market-day evidence boundary, not an unresolved source implementation defect.

## Current paused-automation inventory

Read-only inventory of the ten TradingAgents records under `/Users/corbinfloyd/.codex/automations` after the Ox audit; every record is still `PAUSED`:

| Record | SHA-256 |
| --- | --- |
| `tradingagents-automation-wake-controller` | `001f1084c86fb6da2a3e7b09e5d34c443ad45f7240d7ecda313618cf930a7fcf` |
| `tradingagents-automation-sleep-controller` | `16a187f5c54239139986c959378a5ed69b49f8190a7f6de81611eb361f0b7a98` |
| `tradingagents-overnight-research` | `4c2ffc7a45183563d39683564536171dd9a12a51bf10ec126ac18587964c7428` |
| `tradingagents-autonomous-execution-board` | `537b58c6430e4cd61ae0f2c6ca8a81ceb870ab1a42e847b01648f37f2fc6d00e` |
| `tradingagents-daily-report` | `55934c5740307d4e4703a0eb51cf7244f07160a4531340d966e65a51ec37d32b` |
| `tradingagents-market-supervisor` | `607b6961f31c164361b2d00b20baeecd9e73370acbc994b5773161caddc3fea8` |
| `tradingagents-autonomous-self-healer` | `77c9c9472cb32c1f3f168c3618c05e27676fe8a2fd084a71b6151fd6081a1672` |
| `tradingagents-paper-tournament` | `db226476f71c9a49ef694b25cdb5c649d50ab45773b570a1c70ec47cb7a41ea9` |
| `tradingagents-preopen-validation` | `dcb7c28a0f1e329434c097cb741ebf68d9e60b622673bf45d4e61ebdb90901c9` |
| `tradingagents-autonomous-safety-sentinel` | `df5928810a2c53c8af96d72778f2de4093c56f836141ec1ac14f4141f7504579` |

## Ox Alpha re-audit of historical manual-shadow findings

- A stale Sol review of historical commits `ad76916..b4408a6` reported P0/P1 findings about caller-controlled reserved admission callbacks, route-marker/root rollback forgery, and self-attested calendar mappings. Ox Alpha re-audited the actual current feature HEAD `c216ff554f5396b2634cb82a5c04237435176dff`, including `fad8327` and `b471fbe`, rather than carrying those historical findings into the current source decision.
- The raw callback-driven admission surface is absent; generic admission rejects all three reserved manual-shadow kinds even after instance-state mutation; the three semantic facades expose no caller-controlled route, validator, calendar, clock, root, or live-control parameters; and callback re-entry guards remain armed.
- The route identity is anchor-owned and bound to the canonical root. Replay rejects missing/mismatched anchors, head rollback, uncommitted head advance, copied-root identity mismatch, stripped routes, and non-SHA-256 routes. The calendar is captured inside the private direct-Alpaca read seam and cannot be injected through production API signatures.
- Verification at the exact current HEAD: `tests/test_shadow_trial.py tests/test_strategy_evidence_store.py` — `176 passed`; dependent staged-intent, promotion, attestation, and authority-alignment suites — `481 passed`; Ruff clean. No runtime, broker/network, scheduler, paper, control, or email action occurred. The prior P0/P1 report is therefore historical and not a current source blocker.

## Ox Alpha stale/malformed day-evidence regression checkpoint

- Ox Alpha added `tests/test_shadow_trial.py` coverage in commit `768daa9b882b8bbd8282a22f95e4cc649dd6a01f`, then independently reviewed it with P0=0, P1=0, and only non-blocking P2 test-maintenance notes.
- The stale-sentinel test mutates only `generated_at`, rebinds the manifest through the production manifest builder so hash changes are not the failure cause, and requires both top-level and stage timestamp rejection reasons. The malformed-paper test writes truncated JSON, rebinds the manifest, and requires unreadable/unbound and stage-unreadable reasons without a hash-change reason.
- Focused verification after cherry-picking into canonical `master`: `tests/test_shadow_trial.py tests/test_paper_tournament.py tests/test_safety_sentinel.py tests/test_alpaca_cli.py` — `263 passed`; full repository suite — `3908 passed, 1 skipped, 11 warnings, 75 subtests passed in 425.79s (0:07:05)`. The single skip remains the configured-key DeepSeek live-API test. Ruff, compileall, diff, and wrapper syntax checks passed.
- The regression is test-only; no production behavior, runtime state, broker/provider transport, automation, schedule, paper, live-control, or email path changed. Task 5 remains the only unchecked plan section and is still deferred to a future regular market day.

## Post-full-suite ignored-results inventory

- After the final full suite, canonical `master` has `15,184` ignored files under `results/`. Nine files have timestamps from this continuation turn: six `research_evidence` packets (including `latest.json`) marked `analysis_only=true`, and three `manual_alpaca_submit` refusal packets (including `latest.json`) with `submitted_count=0`, live/paper estimated spend `0.00`, and the existing explicit refusal reason.
- These nine files are test-created or refusal evidence, not qualification-day artifacts. They remain preserved and are excluded from any future shadow-day manifest; no ignored results were deleted or overwritten as part of this checkpoint.

## Ox Alpha malformed-forecast timestamp hardening

- Ox Alpha found and fixed a concrete source defect in the outcome-learning path: malformed, missing, or timezone-overflowed persisted `created_at`/`resolve_after` values could abort forecast resolution instead of deferring safely. The reviewed chain adds `_stored_utc_or_none`, catches `TypeError`, `ValueError`, and `OverflowError`, defers unresolved rows with the machine reason `invalid_forecast_timestamps`, and downgrades retro-audited rows to `suspect` with no verifiable resolution window. Stored outcomes are never rewritten, and learning admission still requires a non-empty verified window.
- A follow-up review also found and fixed the adjacent `summarize_agent_scores` and agent-intelligence maturity-radar overflow paths, preserving the brain's no-raise behavior and preventing malformed timestamps from producing maturity or timing claims.
- The three commits were independently reviewed by Ox Alpha with P0=0 and P1=0: `981b539` (`fix: defer malformed forecast timestamps`), `847a937` (`Harden _stored_utc_or_none against OverflowError timestamps`), and `eb2be8b` (`Reuse _stored_utc_or_none in summarize TTR and maturity radar`). The final review approved the chain for integration; remaining notes are pre-existing P2 follow-ups outside this bounded change.
- RED-GREEN evidence on the isolated feature worktree: overflow regression tests failed before the follow-up and passed after it; the final focused evaluation set (`tests/test_agent_intelligence_ledger.py`, `tests/test_agent_intelligence_brain.py`, `tests/test_resolution_quality.py`) passed `51`; adjacent consumer tests passed `131`; Ruff passed on all four changed files.

## Post-integration source checkpoint

- The reviewed chain was cherry-picked onto clean canonical `master` from `1c57c9673c3686916a78768ace7dc3b19a8d3cc5`; canonical source HEAD before this report-only commit is `eb2be8b`.
- Focused/dependent verification after integration: `741 passed`. Full repository verification: `3914 passed, 1 skipped, 11 warnings, 75 subtests passed in 436.52s (0:07:16)`. The single skip remains the existing DeepSeek live-API test because `DEEPSEEK_API_KEY` is not configured. Ruff, compileall, `git diff --check`, and `zsh -n scripts/mac/ta_job.sh` all passed.
- The frozen live-control file remains byte-identical at SHA-256 `a3fc5ddb2b300596833c48c1554fad088ecb43d46bd70aeeac074531d6e9fb07`. The ten records under `/Users/corbinfloyd/.codex/automations` remain exactly the previously inventoried records with `status = "PAUSED"`; no automation API/TOML update or schedule activation occurred.
- The current continuation produced no runtime qualification or paper-trial evidence. Ignored `results/` artifacts remain preserved and excluded from qualification manifests; no broker/provider/network transport, email, promotion, rearm, live order, or paper submission occurred.
- Task 5 remains the only unchecked plan section. Runtime work is intentionally deferred to a future confirmed regular U.S. equities market day and will still require the one-day clean qualifier before any five-day paper streak. The goal remains active.

## Ox Alpha schedule-clock source checkpoint

- Ox Alpha implemented the bounded schedule-clock correction in isolated worktree
  `/Users/corbinfloyd/.codex/worktrees/tradingagents-schedule-clock-semantics-20260822`,
  branch `codex/schedule-clock-semantics-20260822`, as commit `3c95e2f`
  (`Fail schedule contract evaluation closed on actual TOML rrule drift`). The
  reviewed change was cherry-picked onto canonical `master` as `93ec604`.
- The source change adds an explicit `expected_central_schedules` map for all ten
  TradingAgents records, pinned to `America/Chicago`, and compares that map with
  the exact captured external TOML RRULEs inside `evaluate_schedule_contract`.
  An exact one-hour Eastern-stored signature emits
  `contract_expected_central_schedule_eastern_stored`; any other drift emits
  `contract_expected_central_schedule_mismatch`. Missing, unsafe, changed, or
  malformed captured sources still fail through the trusted snapshot manifest
  before schedule evaluation. No scheduler/API next-run proof was fabricated or
  inferred from this source map.
- Fresh Ox Alpha review of `3c95e2f` against `8ce7b7d`: P0=0, P1=0, P2=1,
  P3=1, verdict `Cherry-pick: YES`. A second final review of integrated `93ec604`
  against `8ce7b7d`: P0=0, P1=0, P2=4, verdict `APPROVE — integrate`. The
  non-blocking notes concern diagnostic specificity/redundancy only; they do not
  weaken the fail-closed result.
- RED-GREEN/source verification: the focused role-contract and health-audit
  suites passed `52`; the affected/dependent suite passed `414`; the full
  repository suite passed `3922 passed, 1 skipped, 11 warnings, 75 subtests` in
  `402.14s`. The only skip remains the existing DeepSeek live-API test because
  `DEEPSEEK_API_KEY` is not configured. Ruff, compileall, `git diff --check`, and
  `zsh -n scripts/mac/ta_job.sh` all passed.
- The canonical code graph was re-indexed at `93ec604`: `12,250` nodes and
  `74,716` edges, zero skipped files, and the same unrelated parse-partial
  archived MiroFish Dockerfile range. Excluded docs/results/scripts remain direct
  evidence lanes rather than graph completeness claims.
- Post-suite ignored-results inventory: `15,197` files under `results/`; eight
  files were created or refreshed during this continuation after the noon
  checkpoint—six `research_evidence` packets marked `analysis_only=true` and two
  `manual_alpaca_submit` refusal packets with `submitted_count=0`. They are
  preserved, excluded from qualification evidence, and were not deleted.
- Frozen live-control SHA-256 remains
  `a3fc5ddb2b300596833c48c1554fad088ecb43d46bd70aeeac074531d6e9fb07`.
  All ten automation records remain `PAUSED` with the previously inventoried
  hashes. No automation API/TOML update, schedule activation, broker/provider
  transport, paper submission, email, promotion, rearm, unfreeze, or live order
  occurred.
- Saturday `2026-08-22` is not a regular U.S. equities market day. Qualification
  and the five-day trial remain unstarted; Task 5 remains the next runtime gate
  for a future confirmed market day, with all schedules paused.

## Ox Alpha crash-safe shadow-day closure checkpoint (Task 4.5 Increment 2)

- Ox Alpha implemented Increment 2 of `docs/superpowers/plans/2026-08-22-task-4-5-source-frozen-shadow-protocol-hardening.md` in the isolated worktree `/Users/corbinfloyd/.codex/worktrees/tradingagents-source-frozen-shadow-protocol-20260822`, branch `codex/source-frozen-shadow-protocol-20260822`, based on canonical commit `ba7c6d4`. The increment adds crash-safe closure for a stranded pending shadow day so a crash can never permanently block the ledger.
- Core surface (`tradingagents/evals/shadow_trial.py`): new facades `abort_shadow_day(start_object_id, stopped_at_stage, notes, artifacts=None)` and argument-free `expire_pending_shadow_day()`. Abort closes only the authenticated pending start whose market date equals the current Central date; it records the interrupted stage (`day_start` or any fixed daily-chain stage key), required operator notes, and every present artifact binding, and always admits a terminal non-clean result (forced reason `shadow_day_aborted_by_operator`) with phase `repair_required`. Expire converts only a pending start whose Central market date has passed into exactly one immutable `incomplete` result carrying `pending_day_expired_without_adjudication`; missing evidence stays missing, nothing is backfilled, repeated calls return `None`, and normal adjudication is refused once closed.
- Schema/replay: day-result payloads gained exact fields `closure_kind`, `stopped_at_stage`, `notes`. Replay validation admits a late-recorded day result only for `closure_kind="pending_expired"` recorded on a strictly later Central date; abort closures remain same-date-only; unclosed days keep the strict rule. Non-clean closure results flow through unchanged `_day_phase`, `_clean_trial_streak`, and `_start_spec` logic, forcing repair→requalification transitions and resetting streaks.
- Refactor: the previously triplicated inline anchored admission transaction in start/adjudicate/report was extracted verbatim into one shared `_admit_shadow_envelope` helper now used by all five semantic facades. A normalized diff against the pre-change blocks confirmed identical behavior modulo parameterization; the pinned store, trusted-head anchor lifecycle, rollback detection, and reserved-kind rejection surfaces are unchanged.
- CLI (`cli/main.py`): new fail-closed commands `research shadow-day-abort --start-object-id ID --stopped-at-stage KEY --notes TEXT [--safety-sentinel PATH] [--paper-tournament PATH] [--daily-chain-manifest PATH] [--json-output]` and argument-free `research shadow-day-expire-pending [--json-output]` (reports `expired: false` with `execution_authority: none` when nothing qualifies). No caller-controlled clock, ledger identity, control/schedule/automation paths, phase, or force/dry-run switches are exposed.
- RED→GREEN: 20 new tests were written first and all failed against `ba7c6d4` (`abort_shadow_day`/`expire_pending_shadow_day` absent, CLI commands absent). After implementation all pass: normal abort with terminal failed/repair_required plus duplicate-closure refusal; wrong identity/stage/non-pending refusal; stale-date abort refusal followed by successful expire; full expire conversion with idempotency and repair recovery; same-date expire leaving surfaces byte-identical; a 13-case interruption matrix over every stop stage each admitting exactly one non-clean result then recovering via repair predecessor; anchor/journal damage failing closed for both facades without mutating any ledger surface; and CLI pinning/fail-closed/authority assertions including read-only calendar as the only broker interaction.
- Verification evidence (canonical venv Python 3.13.14): focused+dependent runs — `tests/test_shadow_trial.py` 78 passed; `tests/test_alpaca_cli.py tests/test_paper_tournament.py tests/test_safety_sentinel.py` 211 passed; `tests/test_authority_role_alignment.py tests/test_safety_sentinel.py` 158 passed; recovery suites `tests/test_strategy_evidence_store.py tests/test_strategy_shadow_attestation.py` 360 passed. Static: Ruff clean on `tradingagents/evals/shadow_trial.py cli/main.py tests/test_shadow_trial.py`; `compileall -q tradingagents/evals cli tests` clean; `git diff --check` clean.
- Boundaries honored: source-only worktree changes; all ten automations untouched and `PAUSED`; frozen live-control bytes untouched; no broker write/read beyond the established read-only calendar seam inside faked tests; no schedule, outbox, promotion, risk, capital, credential, endpoint, or live-control change; no scheduled or runtime qualification activity. Runtime identity capture (Increment 3) was intentionally not implemented.
