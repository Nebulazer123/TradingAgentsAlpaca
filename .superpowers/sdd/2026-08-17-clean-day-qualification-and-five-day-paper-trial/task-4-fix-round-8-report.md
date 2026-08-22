# Task 4 fix round 8 — canonical sentinel preflight root

## Scope and starting point

- Worktree: `/Users/corbinfloyd/.codex/worktrees/tradingagents-clean-day-paper-trial`
- Branch: `codex/clean-day-paper-trial`
- Starting HEAD: `46075609f0727fc3b3fdcba4cd4d1dff7dd2acd3`
- Scope: bind only run-bound and `--require-paused` safety-sentinel preflight calls to the same private canonical automation-root seam as shadow-trial schedule validation. Unbound observer inspection remains compatible.
- No runbook command was executed; this is source-only work.

## RED evidence

- Command: `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_safety_sentinel.py::test_safety_sentinel_require_paused_rejects_hostile_automation_root_override tests/test_safety_sentinel.py::test_safety_sentinel_require_paused_writes_hold_then_exits_nonzero`
- Initial outcome: `1 failed, 1 passed in 1.20s`.
- The new hermetic test built two complete ten-record paused fixtures, set hostile `CODEX_HOME` and `HOME`, and passed the alternate root to preflight. The vulnerable command returned exit code `0`, proving a false-clean alternate tree.

## GREEN implementation

- `cli/main.py` adds `_resolve_safety_sentinel_automation_root(...)`. Qualification calls import the existing private `shadow_trial._canonical_automation_root()` seam and always use that root. In production it is the fixed literal `/Users/corbinfloyd/.codex/automations`.
- A supplied root must resolve to the canonical root. A conflicting `--automation-root` gets a CLI parameter error before broker reads or packet writes. `CODEX_HOME` and `HOME` are not consulted for qualifying preflight.
- The option default is now `None`; only unbound observer audits fall back to the ordinary environment default.
- `tests/test_safety_sentinel.py` proves both hostile environment substitution and an explicit hostile override cannot satisfy qualifying preflight.
- The future-only Task 4 runbook states that bound/paused sentinel commands force the private canonical root, must not pass `--automation-root`, and reject a conflict before a broker read or packet write.

## Verification evidence

- Focused GREEN command: `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_safety_sentinel.py::test_safety_sentinel_cli_uses_only_narrow_read_only_broker_adapter tests/test_safety_sentinel.py::test_safety_sentinel_require_paused_rejects_hostile_automation_root_override tests/test_safety_sentinel.py::test_safety_sentinel_require_paused_writes_hold_then_exits_nonzero tests/test_shadow_trial.py::test_bound_sentinel_cli_derives_start_identity_and_requires_paused tests/test_alpaca_cli.py::test_clean_day_runbook_exact_commands_exist_without_executing_runtime`
- Focused outcome: `5 passed in 0.95s`.
- Affected/dependent command: `PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_safety_sentinel.py tests/test_shadow_trial.py tests/test_alpaca_cli.py tests/test_automation_role_contracts.py tests/test_automation_context_snapshot.py tests/test_authority_role_alignment.py`
- Affected/dependent outcome: `308 passed, 2 warnings in 14.67s`. Both warnings are existing `SyntaxWarning: invalid escape sequence '\\`' reports from the authority inventory tests.
- Static commands: `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/ruff check cli/main.py tests/test_safety_sentinel.py tests/test_shadow_trial.py tests/test_alpaca_cli.py`; `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m compileall -q cli/main.py tests/test_safety_sentinel.py`; `git diff --check`; `zsh -n scripts/mac/ta_job.sh`.
- Static outcome: Ruff reported `All checks passed!`; compileall, diff check, and zsh syntax parsing exited zero with no output.

## No-runtime assertion

Only source, test, runbook, and report files changed. Verification used temporary fixtures and fake read-only clients. No provider, broker, scheduler, automation-management, safety-sentinel CLI, paper-trial, live-control, order, cancellation, reconciliation, outbox, delivery, or other runtime command was invoked. No automation record or live-control byte changed. A fresh independent Sol review remains required; this report does not self-approve Task 4.
