# Task 4 fix round 13 — calendar-before-final-clock boundary

## Scope and boundary

- Worktree: `/Users/corbinfloyd/.codex/worktrees/tradingagents-clean-day-paper-trial`
- Branch: `codex/clean-day-paper-trial`
- Starting HEAD: `ca4bdb12d473bffaa3547d36d99fcd49291d07be`
- Scope: close the remaining slow-calendar time-of-check/time-of-use gap by
  reading the broker calendar before the final exact broker-clock/local-time
  bracket, then basing every time-sensitive lease decision on that final sample.
  Also prove equal successful response timestamps remain valid while reverse
  ordering remains fail-closed.
- No runtime, broker/provider/network, scheduler, automation, live-control,
  paper/live transport, order/cancel, reconciliation, or outbox command was run.
  Tests use fake clients and temporary directories only.

## RED evidence

- Added a fake paper client whose third calendar query—at the per-POST
  boundary—advances the local policy clock from `14:59:50` to `15:00:01`
  America/Chicago. The prior order read the broker clock before that slow
  calendar operation and submitted a fake order after close.
- Added a two-payload transaction with equal `recorded_at` values and exercised
  recording, completion, recovery sealing, and persisted completed-state
  validation. Equality is intentionally nondecreasing and must remain valid.
- Initial command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py::test_paper_tournament_calendar_delay_rechecks_final_clock_before_any_post tests/test_paper_tournament.py::test_submission_response_timestamps_allow_equal_values_across_all_validators`
- Initial outcome: `1 failed, 1 passed in 1.04s`. Before the fix, the delayed
  calendar regression returned success and made a paper POST.

## GREEN implementation

- The lease validator now derives a provisional Central calendar date only to
  query the exact broker calendar first. Its final operation that can block is
  the existing exact paper broker-clock request followed by the fresh local
  post-response policy sample.
- It re-derives the final Central date from that authoritative sample and rejects
  any date change during the calendar request. The final broker timestamp and
  final policy timestamp must each match the queried calendar date; session,
  lease-start, expiry, duplicate-day, and capacity checks all use final values.
- The existing deterministic post-clock seam and backward-local-bracket
  rejection remain intact. The zero-post close-boundary regression proves that
  a calendar delay cannot authorize a later transaction or POST.
- The runbook now states calendar-before-final-clock ordering and explicitly
  distinguishes allowed equal `recorded_at` timestamps from forbidden reverse
  order.

## Verification evidence

- Focused command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py::test_paper_tournament_calendar_delay_rechecks_final_clock_before_any_post tests/test_paper_tournament.py::test_submission_response_timestamps_allow_equal_values_across_all_validators`
- Focused outcome: `2 passed in 1.10s`.
- Paper tournament suite: `59 passed in 2.06s`.
- Final affected/dependent command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py tests/test_alpaca_cli.py tests/test_authority_role_alignment.py tests/test_shadow_trial.py`
- Final outcome: `287 passed, 2 warnings in 16.57s`. Both warnings are existing
  `SyntaxWarning: invalid escape sequence '\\`' reports from authority inventory
  test source; this change emitted no new warnings.
- Static commands:
  `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/ruff check tradingagents/brokers/paper_tournament.py cli/main.py tests/test_paper_tournament.py tests/test_alpaca_cli.py`;
  `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m compileall -q tradingagents/brokers/paper_tournament.py cli/main.py tests/test_paper_tournament.py tests/test_alpaca_cli.py`;
  `git diff --check`; and `zsh -n scripts/mac/ta_job.sh`.
- Static outcome: Ruff reported `All checks passed!`; compileall, diff check, and
  shell syntax parsing exited zero with no output.
