# Task 4 fix round 12 — authoritative post-clock lease time

## Scope and boundary

- Worktree: `/Users/corbinfloyd/.codex/worktrees/tradingagents-clean-day-paper-trial`
- Branch: `codex/clean-day-paper-trial`
- Starting HEAD: `4e00951a88d7d4d9a55b3d72149f748dc8ed4a66`
- Scope: make the local policy sample taken after the exact broker-clock response
  authoritative for every time-sensitive paper lease predicate, reject a local
  clock that moves backward across that response, and require nondecreasing
  successful-response evidence throughout recording, completion/recovery, and
  persisted-ledger validation.
- No runtime, broker/provider/network, scheduler, automation, live-control,
  paper/live transport, order/cancel, reconciliation, or outbox command was run.
  Tests use fake clients and temporary directories only.

## RED evidence

- Added a deterministic lease whose pre-request sample is one second before
  expiry and post-response sample is one second after expiry. The previous code
  accepted it because it used the pre-request time for the lease end predicate.
- Added a reverse local bracket regression; a post-response local sample one
  millisecond earlier than the pre-request sample must fail closed.
- Added two successful fake response records at `18:02` then `18:01` UTC. The
  previous recorder accepted the reverse order, and persisted completed evidence
  did not identify it as recovery-required.
- Initial command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py::test_submission_lease_uses_post_response_policy_time_for_expiry_and_clock_order tests/test_paper_tournament.py::test_submission_response_and_persisted_ledger_reject_reversed_record_times`
- Initial outcome: `2 failed in 1.01s`.

## GREEN implementation

- `_validate_regular_paper_broker_clock` now returns the exact broker timestamp
  and the fresh post-response local policy timestamp. It rejects a naive or
  malformed sample, a future or stale broker timestamp, and a post-response
  local timestamp that moved backward from the pre-request sample.
- `_validate_submission_lease` uses the returned post-response local timestamp
  for lease start/expiry, Central date, market-day calendar lookup, duplicate-day
  and capacity decisions, and regular-session comparison. This applies to the
  initial, transaction, and per-POST callers without changing dry-run behavior.
- Successful `recorded_at` timestamps are nondecreasing in the recorder,
  completion and recovery checks, and persisted transaction-state validation.
  A reverse sequence is rejected before a second durable order record and is
  recovery-required if discovered in persisted evidence.
- The future-only runbook now records post-response authority, nondecreasing
  local bracketing, zero-post delayed-preparation behavior, and the reverse-time
  persisted-evidence rejection.

## Verification evidence

- Focused command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py::test_submission_lease_uses_post_response_policy_time_for_expiry_and_clock_order tests/test_paper_tournament.py::test_submission_response_and_persisted_ledger_reject_reversed_record_times tests/test_paper_tournament.py::test_submission_lease_brackets_broker_clock_with_post_response_policy_time tests/test_paper_tournament.py::test_paper_tournament_submission_event_timestamps_are_monotonic tests/test_paper_tournament.py::test_paper_tournament_multi_order_close_between_posts_sends_zero_additional_posts`
- Focused outcome: `5 passed in 0.97s`.
- Final affected/dependent command:
  `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_paper_tournament.py tests/test_alpaca_cli.py tests/test_authority_role_alignment.py tests/test_shadow_trial.py`
- Final outcome: `285 passed, 2 warnings in 15.73s`. Both warnings are existing
  `SyntaxWarning: invalid escape sequence '\\`' reports from authority inventory
  test source; this change emitted no new warnings.
- Static commands:
  `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/ruff check tradingagents/brokers/paper_tournament.py cli/main.py tests/test_paper_tournament.py tests/test_alpaca_cli.py`;
  `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m compileall -q tradingagents/brokers/paper_tournament.py cli/main.py tests/test_paper_tournament.py tests/test_alpaca_cli.py`;
  `git diff --check`; and `zsh -n scripts/mac/ta_job.sh`.
- Static outcome: Ruff reported `All checks passed!`; compileall, diff check, and
  shell syntax parsing exited zero with no output.
