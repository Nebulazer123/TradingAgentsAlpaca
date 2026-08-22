# Task 4 fix round 10 — paper submission close-boundary recheck

## Scope and boundary

- Worktree: `/Users/corbinfloyd/.codex/worktrees/tradingagents-clean-day-paper-trial`
- Branch: `codex/clean-day-paper-trial`
- Starting HEAD: `369ab468cb1ae57e64ff03d6dd22b9035c86cef8`
- Scope: close the paper-submit time-of-check/time-of-use gap by re-reading the
  current policy clock and exact paper broker clock at both irreversible points:
  immediately before the durable submission transaction and immediately before
  every paper POST.
- No runtime command, provider/broker request, scheduler action, automation action,
  live-control access, paper/live order, cancellation, or outbox action was run.
  Tests use fake clients and temporary directories only.

## RED evidence

- Added `test_paper_tournament_submit_rechecks_clock_before_transaction_after_delayed_preparation`
  and strengthened the close-boundary successful submission test to require three
  clock reads (initial lease, durable transaction, pre-POST).
- Initial command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py::test_paper_tournament_submit_records_current_regular_central_date_and_suppresses_selection tests/test_paper_tournament.py::test_paper_tournament_submit_rechecks_clock_before_transaction_after_delayed_preparation`
- Initial outcome: `2 failed in 0.99s`. The old flow performed one clock read,
  returned success after a preparation delay crossed 15:00 Central, and would
  create the durable transaction before checking current time again.

## GREEN implementation

- `tradingagents/brokers/paper_tournament.py` factors the complete lease checks
  into an internal shared validator and adds `validate_submission_runtime_boundary`.
  It validates the exact endpoint/mode, current ledger lease/calendar/capacity,
  exact `is_open is True`, timezone-aware policy and broker timestamps, same
  Central date, no future clock, a 15-minute stale cap, and 08:30–15:00 Central
  for both policy time and broker time.
- The runtime-boundary variant recognizes only the active in-flight transaction's
  own already-consumed Central date, so a multi-order same-day transaction can
  revalidate before its second/third POST without weakening duplicate-day or
  capacity checks for a new submission.
- `cli/main.py` re-runs full lease validation before `begin_submission_transaction`;
  a failure there creates neither a transaction nor a paper POST. It invokes the
  runtime boundary immediately before each `submit_order`. A later boundary
  failure records recovery-required evidence and sends zero additional posts.
- `tests/test_paper_tournament.py` covers a delayed preparation that crosses the
  close before transaction, a crossing after transaction but before POST, a valid
  14:59:59 Central transaction with all three fresh reads, and direct rejection of
  after-close or timezone-naive policy clocks.
- The future-only runbook now explicitly documents both boundary re-reads and
  zero-post close-boundary behavior.

## Verification evidence

- Focused boundary command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py::test_submission_lease_rejects_after_close_or_naive_policy_time tests/test_paper_tournament.py::test_paper_tournament_submit_rechecks_clock_before_transaction_after_delayed_preparation tests/test_paper_tournament.py::test_paper_tournament_submit_rechecks_clock_immediately_before_each_post`
- Outcome: `3 passed in 0.61s`.
- Final affected/dependent command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py tests/test_alpaca_cli.py tests/test_authority_role_alignment.py tests/test_shadow_trial.py`
- Final outcome: `280 passed, 2 warnings in 16.62s`. Both warnings are the
  existing `SyntaxWarning: invalid escape sequence '\\`' reports from authority
  inventory test source; this change emitted no new warnings.
- Static commands:
  `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/ruff check tradingagents/brokers/paper_tournament.py cli/main.py tests/test_paper_tournament.py tests/test_alpaca_cli.py`;
  `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m compileall -q tradingagents/brokers/paper_tournament.py cli/main.py tests/test_paper_tournament.py tests/test_alpaca_cli.py`;
  `git diff --check`; and `zsh -n scripts/mac/ta_job.sh`.
- Static outcome: Ruff reported `All checks passed!`; compileall, diff check, and
  shell syntax parsing exited zero with no output.
