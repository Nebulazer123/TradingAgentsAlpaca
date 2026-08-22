# Clean-Day Qualification and Five-Day Paper Trial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fail-closed, on-demand qualification and bounded Alpaca-paper trial that never activates schedules or permits live trading.

**Architecture:** The paper tournament gains a deterministic submission lease, bounded by Central market dates and an immutable ledger. A read-only safety sentinel and a hash-bound shadow-day verifier turn direct, manually invoked runtime commands into evidence that can be adjudicated as clean, failed, or incomplete. All runtime state is ignored evidence under `results/`; production source never writes live-control or automation status.

**Tech Stack:** Python 3, Typer CLI, existing Alpaca REST client, pytest, Ruff.

## Global Constraints

- All ten Codex automations remain `PAUSED`; this plan never calls the automation update API.
- Live orders, live-control refresh/rearm/unfreeze, strategy promotion, risk/capital changes, external email delivery, and remote workflows are forbidden.
- Paper `POST /v2/orders` is allowed only through the validated paper client and only after the explicit bounded lease validates.
- `TA_LIVE_SUBMIT=0` is set for every runtime supervisor/overnight command.
- A valid HOLD or no paper signal is not an error; stale/missing/malformed/transport/provider/model/reconciliation/authority/configuration errors are not countable clean days.
- All behavior changes begin RED, then minimal GREEN, then focused and dependent verification.

---

### Task 1: Bound the paper-tournament submission lease

**Files:**
- Modify: `tradingagents/brokers/paper_tournament.py`
- Modify: `cli/main.py`
- Test: `tests/test_paper_tournament.py`

**Interfaces:**
- `initialize_tournament(..., duration_days: int = 31, max_submission_market_days: int = 31) -> dict` adds `authorized_market_day_limit`, `submitted_market_dates`, and `submission_window_status`.
- `alpaca paper-tournament init --duration-days INT --max-submission-market-days INT` accepts only 1–31 values and defaults to 31 for backward compatibility.
- `alpaca paper-tournament run` defaults to `--dry-run`; `--submit-actions` is the only paper-write route.
- `alpaca paper-tournament finalize --log-dir PATH --json-output` performs a paper-only reconciliation and closes the lease without canceling or liquidating orders.

- [ ] Write RED tests for default dry-run, exact paper endpoint, current/regular Central market date, duplicate date, sixth date, expired/future lease, selection suppression, and finalization.
- [ ] Run the selected tests and record the expected failures.
- [ ] Add ledger validation before any paper submit; reject all invalid leases before transport.
- [ ] Record one Central market date only after a successful paper submit; never write a live-strategy selection for this trial type.
- [ ] Implement finalization: reconcile only `ta-paperbot-*` orders, reject unresolved open/ambiguous orders as HOLD, otherwise close the submission window and preserve positions.
- [ ] Run focused paper tests, the paper/authority/supervisor dependent tests, Ruff, and `git diff --check`.
- [ ] Commit the bounded paper lease.

### Task 2: Add a deterministic read-only safety-sentinel command

**Files:**
- Create: `tradingagents/evals/safety_sentinel.py`
- Modify: `cli/main.py`
- Test: `tests/test_safety_sentinel.py`

**Interfaces:**
- `build_safety_sentinel_packet(...) -> dict` returns schema version, `status` (`CLEAR`, `HOLD`, or `FROZEN`), exact evidence paths/digests, `analysis_only=true`, `execution_authority="none"`, and `can_submit_orders=false`.
- `research safety-sentinel-audit --json-output` captures live account/positions/open orders/clock through read-only adapters and writes `results/safety_sentinel/safety-sentinel-*.json`.

- [ ] Write RED tests with a complete read-only broker fake: frozen control returns `FROZEN`, missing/stale/corrupt evidence returns `HOLD`, and no write/cancel/rearm method is invoked.
- [ ] Run the selected tests and record RED.
- [ ] Implement deterministic packet construction, SHA-256 file capture, schedule-contract checking in `predeployment_paused`, and strict read-only broker snapshots.
- [ ] Add the CLI command without any `freeze-live`, automation-update, submit, or cancel path.
- [ ] Run focused sentinel/authority tests, Ruff, compileall, and `git diff --check`.
- [ ] Commit the sentinel command.

### Task 3: Persist and adjudicate the clean-day trial state

**Files:**
- Create: `tradingagents/evals/shadow_trial.py`
- Modify: `cli/main.py`
- Test: `tests/test_shadow_trial.py`

**Interfaces:**
- `create_shadow_day_start_manifest(...) -> dict` captures start-state hashes and statuses.
- `adjudicate_shadow_day(start_manifest: Mapping, artifacts: Mapping[str, Path], ...) -> dict` returns `clean`, `failed`, or `incomplete` with per-gate reasons and exact digests.
- `build_shadow_streak_report(...) -> dict` enforces a clean qualification followed by five distinct current regular market days; any failed/incomplete day resets the streak.
- `research shadow-day-start`, `research shadow-day-adjudicate`, and `research shadow-streak-report` write ignored, immutable evidence under `results/manual_shadow/` and remain non-authorizing.

- [ ] Write RED tests for duplicate dates, non-market dates, missing/stale/cross-run/mutated artifact hashes, unpaused schedules, live-control hash changes, a valid HOLD, failed-day reset, and five clean trial days after qualification.
- [ ] Run the selected tests and record RED.
- [ ] Implement canonical JSON/hash validation and the explicit phase machine: `qualification_pending`, `qualification_clean`, `repair_required`, `repair_in_progress`, `five_day_trial`, `trial_complete`, `readiness_no_go`, and `readiness_candidate`.
- [ ] Implement the three analysis-only CLI commands; reject unknown/extra artifact keys and never infer a success from absent evidence.
- [ ] Run focused shadow/sentinel/paper tests and dependent recovery/schedule tests, then Ruff, compileall, and `git diff --check`.
- [ ] Commit the trial evidence state machine.

### Task 4: Integrate, independently review, and prepare the manual runbook

**Files:**
- Modify: `cli/main.py`
- Modify: `docs/superpowers/plans/2026-08-17-clean-day-qualification-and-five-day-paper-trial.md`
- Test: `tests/test_alpaca_cli.py`

**Interface:**
- `alpaca supervisor-daily-report --write-outbox/--no-write-outbox` defaults to
  `--write-outbox` for compatibility. `--no-write-outbox` still renders the local
  report and JSON packet, but creates no notification-outbox record.

- [x] Produce a manual, on-demand runbook in this plan’s report that names the exact capped overnight command, preopen/hourly dry-run commands, sentinel, BOARD, self-heal analysis, local-only daily report, paper command, and adjudication command.
- [ ] Verify all ten automation TOMLs are paused before any runtime step; this is a hard prerequisite, not a change request.
- [ ] Run the declared focused suite, full pytest, Ruff, compileall, wrapper syntax, and authority inventory.
- [ ] Obtain task-scoped specification and quality reviews after each task and a fresh whole-branch authority/security review after Task 4.
- [ ] Commit the runbook/report update if it changes tracked documentation.

### Task 5: Execute the runtime state machine only after source review is clean

**Files:**
- Runtime evidence only under `results/manual_shadow/`, `results/paper_strategy_tournament/`, and existing ignored result directories.

- [ ] On a confirmed regular U.S. market day, create a one-day qualifier ledger and start manifest.
- [ ] Run exactly one capped overnight probe with `--full-graph-tickers 1 --per-ticker-timeout-minutes 2 --time-budget-minutes 3 --overnight-graph-profile market-only --overnight-max-completion-tokens 800 --overnight-llm-timeout-seconds 30 --overnight-llm-max-retries 0 --no-research-context --no-agent-intelligence --top-provider-bundle-count 0 --no-agent-ledger` and `TA_LIVE_SUBMIT=0`.
- [ ] Run direct preopen/hourly `--dry-run`, read-only reconciliation, safety sentinel, loss evidence, analysis-only BOARD, no-execute-safe self-heal analysis, local-only daily report, and at most one explicit paper submit.
- [ ] Adjudicate the qualifier. If it is not clean, stop all further runtime submits; the next regular market day is repair-only, followed by a new qualification day after repair/review.
- [ ] After a clean qualification, initialize a fresh five-day paper ledger. Each trial day runs the same full chain, with at most one paper submit and a fresh adjudication.
- [ ] A failed/incomplete trial day resets the streak to zero and returns to the repair loop. After five clean days, finalize paper, prove all future submissions reject, verify all ten automations remain paused, and issue a non-authorizing readiness packet.

## Self-Review

- Every requested runtime phase has a deterministic source-side evidence gate.
- Live execution and schedule activation are absent from all tasks.
- The only allowed broker write is the explicit, validated paper-tournament submission; it is time/date/endpoint limited and cannot write a live selection.
- Runtime evidence is not treated as a substitute for source verification, and source verification is not treated as a substitute for real market-day evidence.
