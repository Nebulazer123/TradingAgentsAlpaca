# Task 4 fix round 11 — bracketed paper clock and monotonic events

## Scope and boundary

- Worktree: `/Users/corbinfloyd/.codex/worktrees/tradingagents-clean-day-paper-trial`
- Branch: `codex/clean-day-paper-trial`
- Starting HEAD: `aaf83cf997b1d6bc1a644687f540c9efc78d2366`
- Scope: avoid false future-clock rejection by sampling local policy time after
  the exact broker clock response, while retaining genuine future rejection;
  record monotonic response/completion/recovery timestamps; accurately document
  that a post-boundary failure makes zero additional posts rather than rewriting
  the fact of a previous accepted fake-money POST.
- No runtime, broker/provider/network, scheduler, automation, live-control,
  paper/live transport, order/cancel, reconciliation, or outbox command was run.
  All verification uses fake clients and temporary directories.

## RED evidence

- Added a deterministic direct lease regression with a broker timestamp one
  millisecond after the pre-request policy sample and a local post-response
  sample one millisecond later. The previous public function rejected the new
  deterministic seam with `TypeError`, proving no response-bracketed policy
  sample existed.
- Added a three-order fake run that crosses the close between POST one and POST
  two. The previous code returned success and posted every payload.
- Initial command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py::test_submission_lease_brackets_broker_clock_with_post_response_policy_time tests/test_paper_tournament.py::test_paper_tournament_multi_order_close_between_posts_sends_zero_additional_posts`
- Initial outcome: `2 failed in 0.92s`.

## GREEN implementation

- `validate_submission_lease` and `validate_submission_runtime_boundary` accept
  the optional deterministic `post_clock_now` seam. After `get_clock()` returns,
  the validator samples that fresh aware policy time and uses it—not the
  pre-request sample—for future/staleness, Central-date, and regular-session
  checks. A response one millisecond after the request is accepted when the
  post-response local sample brackets it; a timestamp later than that post sample
  remains a genuine future failure.
- The CLI supplies `_alpaca_policy_now` for that seam at initial lease,
  transaction, and every pre-POST boundary. It records each broker response with
  a fresh post-POST timestamp, completes with a fresh completion timestamp, and
  records recovery with a fresh failure timestamp.
- Transaction helpers and persisted-state validation now require the ordering
  `started_at <= recorded_at <= completed_at`; recovery timestamps cannot precede
  the start or any successfully recorded submission.
- The multi-order close regression proves that after the first accepted fake-money
  response, a second boundary failure produces `recovery_required` and zero
  additional posts. The runbook now says exactly that.

## Verification evidence

- Focused boundary/event command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py::test_submission_lease_brackets_broker_clock_with_post_response_policy_time tests/test_paper_tournament.py::test_paper_tournament_submission_event_timestamps_are_monotonic tests/test_paper_tournament.py::test_paper_tournament_multi_order_close_between_posts_sends_zero_additional_posts tests/test_paper_tournament.py::test_paper_tournament_submit_records_current_regular_central_date_and_suppresses_selection tests/test_paper_tournament.py::test_paper_tournament_submit_rechecks_clock_before_transaction_after_delayed_preparation tests/test_paper_tournament.py::test_paper_tournament_submit_rechecks_clock_immediately_before_each_post`
- Outcome before the final persisted-validation assertion: `6 passed in 1.09s`.
- Final affected/dependent command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py tests/test_alpaca_cli.py tests/test_authority_role_alignment.py tests/test_shadow_trial.py`
- Final outcome: `283 passed, 2 warnings in 15.82s`. Both warnings are existing
  `SyntaxWarning: invalid escape sequence '\\`' reports from authority inventory
  test source; this change emitted no new warnings.
- Static commands:
  `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/ruff check tradingagents/brokers/paper_tournament.py cli/main.py tests/test_paper_tournament.py tests/test_alpaca_cli.py`;
  `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m compileall -q tradingagents/brokers/paper_tournament.py cli/main.py tests/test_paper_tournament.py tests/test_alpaca_cli.py`;
  `git diff --check`; and `zsh -n scripts/mac/ta_job.sh`.
- Static outcome: Ruff reported `All checks passed!`; compileall, diff check, and
  shell syntax parsing exited zero with no output.
