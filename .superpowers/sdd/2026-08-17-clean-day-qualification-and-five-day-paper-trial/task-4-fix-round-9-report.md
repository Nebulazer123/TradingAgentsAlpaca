# Task 4 fix round 9 — broker-clock paper submission gate

## Scope and boundary

- Worktree: `/Users/corbinfloyd/.codex/worktrees/tradingagents-clean-day-paper-trial`
- Branch: `codex/clean-day-paper-trial`
- Starting HEAD: `94c1a199ed08a5757175cae2841fa1d6f7e4b289`
- Scope: require one fresh exact-paper broker clock before the paper tournament
  can create a durable submission transaction or call `submit_order`.
- No runtime command, broker/provider request, scheduler action, automation action,
  live-control access, paper order, live order, cancellation, or outbox action was
  invoked. All verification used fake clients and temporary directories.

## RED evidence

- Added the real CLI-path regression
  `test_paper_tournament_submit_rejects_unsafe_broker_clock_before_transaction_or_post`.
- Initial command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py::test_paper_tournament_submit_rejects_unsafe_broker_clock_before_transaction_or_post`
- Initial outcome: `1 failed in 0.97s`. A fake paper client returned the exact
  current clock timestamp with `is_open=false`; the vulnerable CLI returned zero
  and reached a paper submission.
- Added the runbook assertion in
  `test_clean_day_runbook_exact_commands_exist_without_executing_runtime`.
- Initial command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_alpaca_cli.py::test_clean_day_runbook_exact_commands_exist_without_executing_runtime`
- Initial outcome: `1 failed in 0.78s` because the future-only runbook did not
  state the broker-clock gate.

## GREEN implementation

- `tradingagents/brokers/paper_tournament.py` now reads the exact paper client
  clock inside `validate_submission_lease`, after endpoint/lease/calendar checks
  and before `begin_submission_transaction` can run.
- The gate accepts only a mapping with exact boolean `is_open=true` and a
  timezone-aware ISO timestamp. It rejects unavailable or malformed clock reads,
  stale/future timestamps outside a 15-minute bound, a clock whose
  America/Chicago date differs from the requested current market date, and clock
  times outside 08:30–15:00 Central regular session. The caller still verifies the
  broker calendar, paper endpoint, one-date lease, and capacity.
- `tests/test_paper_tournament.py` covers the real submit path and proves zero
  submission transaction and zero paper POST for unavailable, pre-open,
  after-hours, stale, future, malformed, and wrong-Central-date clocks.
- The tracked future-only runbook states that explicit paper submission is
  permitted only after this broker-clock proof, with all failures occurring before
  a durable transaction or paper POST.

## Verification evidence

- Focused paper suite:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py`
- Outcome: `48 passed in 2.11s`.
- Final affected/dependent command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py tests/test_alpaca_cli.py tests/test_authority_role_alignment.py tests/test_shadow_trial.py`
- Final outcome: `277 passed, 2 warnings in 15.40s`. Both warnings are existing
  `SyntaxWarning: invalid escape sequence '\\`' reports from authority inventory
  test source; the clock change emitted no new warnings.
- Static commands:
  `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/ruff check tradingagents/brokers/paper_tournament.py cli/main.py tests/test_paper_tournament.py tests/test_alpaca_cli.py`;
  `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m compileall -q tradingagents/brokers/paper_tournament.py cli/main.py tests/test_paper_tournament.py tests/test_alpaca_cli.py`;
  `git diff --check`; and `zsh -n scripts/mac/ta_job.sh`.
- Static outcome: Ruff reported `All checks passed!`; compileall, diff check, and
  shell syntax parsing exited zero with no output.
