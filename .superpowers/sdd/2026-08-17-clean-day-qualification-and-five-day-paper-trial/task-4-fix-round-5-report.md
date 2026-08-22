# Task 4 fix round 5 — implementation report

## Scope and starting point

- Worktree: `/Users/corbinfloyd/.codex/worktrees/tradingagents-clean-day-paper-trial`
- Starting HEAD: `f18815748e51ab5729491c4d2fb81de97e059a2d`
- Fix scope: close the sentinel exact-roster/source-identity gate and repair the
  future-only Task 4 runbook command sequence.
- The implementation did not change `results/policy/live_control.json`, an
  automation TOML, or any runtime/provider/broker/scheduler/order/outbox surface.

## RED evidence

The worktree has no `.venv` link, so verification used the canonical repository's
existing interpreter at `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python`.

```zsh
/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q \
  -p no:cacheprovider \
  tests/test_shadow_trial.py::test_safety_sentinel_accepts_only_real_shape_bound_to_admitted_sources \
  tests/test_shadow_trial.py::test_safety_sentinel_false_clean_roster_and_source_identities_fail_closed \
  tests/test_alpaca_cli.py::test_clean_day_runbook_exact_commands_exist_without_executing_runtime
```

Initial outcome: `8 failed`. The sentinel cases failed because the admitted start
did not yet retain a schedule source manifest; the runbook regression failed because
the exact no-refresh commands and final streak command were absent.

## GREEN implementation

- `tradingagents/evals/shadow_trial.py`
  - Derives the ten expected IDs from the schedule evaluator's canonical frozen
    active/paused contract constants rather than a caller-provided roster.
  - Requires exactly ten unique expected IDs, `status=match`,
    `config_status=PAUSED`, empty mismatches, and exact integer
    `automation_count=configured_count=paused_count=10`.
  - Captures the contract, role contract, and ten automation TOMLs through the
    existing trusted schedule snapshot; retains exact paths, raw SHA-256 digests,
    sizes, and descriptor/file identities in the immutable start/manifest binding.
  - Requires the sentinel schedule evaluation/configuration to match that admitted
    schedule binding, live control to match the admitted path/digest/size, and
    preopen to match the exact manifest artifact path/digest/size.
  - Missing bindings, duplicate/wrong IDs, active rows, count drift, malformed
    provenance, or arbitrary alternate source paths now fail closed.
- `tests/test_shadow_trial.py`
  - Adds producer-real positive coverage using `build_safety_sentinel_packet`.
  - Reproduces wrong-ID, active-row, count, alternate live-control, alternate
    preopen, and alternate schedule-contract false-clean cases.
  - Updates the complete-chain fixture to carry admitted source identities.
- `tests/test_alpaca_cli.py`
  - Parses every exact future-only runbook argv without invoking a command.
  - Checks every documented option against the real Click/Typer command tree.
  - Requires exact self-heal no-refresh argv and post-adjudication streak ordering.
- `.superpowers/sdd/2026-08-17-clean-day-qualification-and-five-day-paper-trial/task-4-report.md`
  - Documents exact `research self-heal-handoff --no-refresh-context`.
  - Documents `research self-heal-plan --no-execute-safe --no-refresh-context`.
  - Adds `research shadow-streak-report --json-output` after adjudication/finalize.

## Verification evidence

Focused GREEN:

```zsh
/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q \
  -p no:cacheprovider \
  tests/test_shadow_trial.py::test_safety_sentinel_rejects_extra_reason_or_missing_observer_proof \
  tests/test_shadow_trial.py::test_safety_sentinel_accepts_only_real_shape_bound_to_admitted_sources \
  tests/test_shadow_trial.py::test_safety_sentinel_false_clean_roster_and_source_identities_fail_closed \
  tests/test_alpaca_cli.py::test_clean_day_runbook_exact_commands_exist_without_executing_runtime
```

Outcome: `9 passed in 0.94s`.

Full shadow-trial module:

```zsh
/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q \
  -p no:cacheprovider tests/test_shadow_trial.py
```

Outcome: `48 passed in 9.12s`.

Final affected/dependent suite:

```zsh
/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q \
  -p no:cacheprovider tests/test_shadow_trial.py tests/test_alpaca_cli.py \
  tests/test_safety_sentinel.py tests/test_authority_role_alignment.py \
  tests/test_alpaca_supervisor.py
```

Outcome: `335 passed, 2 warnings in 14.64s`. The warnings are the existing
`SyntaxWarning: invalid escape sequence '\\`' reports from the two authority
inventory tests.

Static and shell verification:

```zsh
/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/ruff check \
  tradingagents/evals/shadow_trial.py tests/test_shadow_trial.py \
  tests/test_alpaca_cli.py tradingagents/evals/safety_sentinel.py \
  tests/test_safety_sentinel.py tests/test_authority_role_alignment.py
/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m compileall -q \
  tradingagents/evals/shadow_trial.py tests/test_shadow_trial.py \
  tests/test_alpaca_cli.py
git diff --check
zsh -n scripts/mac/ta_job.sh
```

Outcome: Ruff reported `All checks passed`; compileall, diff check, and zsh syntax
check exited zero with no output.

## No-runtime assertion

Only source/report edits, hermetic pytest cases, static analysis, compilation, Git
diff inspection, and shell syntax parsing were performed. No provider or broker was
called; no runtime, scheduler, automation, safety-sentinel, self-heal, paper-trial,
order, reconciliation, finalization, outbox, or delivery command was run. No live
control or automation configuration was read for authority or modified. All producer
tests used fake clients and temporary fixture paths.

Fresh Sol review remains required; this report does not self-approve Task 4.
