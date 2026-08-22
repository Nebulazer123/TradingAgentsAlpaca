# Task 2 Fix Round 4 Report — Automatic Capture Compatibility

## Scope and safety boundary

- Base: `9ffb5c699b6f8e06b57a4589421ce1142663282a` in the isolated
  `codex/clean-day-paper-trial` worktree.
- Modified only the schedule evaluator and its matching existing tests:
  `tradingagents/evals/automation_health_audit.py`,
  `tests/test_safety_sentinel.py`, and
  `tests/test_automation_role_contracts.py`.
- No sentinel implementation change was necessary.
- No automation TOML/API mutation, broker/provider/network request, result-packet
  generation, live-control action, submission, cancellation, rearm, or Task 3
  implementation was performed.

## Exact reproduction

Command:

```zsh
PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_automation_role_contracts.py
```

At the required starting HEAD this reported `8 failed in 0.16s`. Every case
short-circuited through `invalid_contract` with
`issues=["captured_snapshot_invalid"]`, preventing its intended role/schedule
assertions.

## Root cause

The automatic capture builder enumerated every syntactically valid automation
directory under the shared automation root. The current root contained the ten
contract-owned `tradingagents-*` records plus four unrelated records:

- `feather-watcher-backup-email-check`
- `lainie-records-check-1-week`
- `lainie-records-check-3-days`
- `weekly-review`

The immutable evaluator correctly rejected that fourteen-row capture because
its discovered and captured ID sets were not exactly the ten contract IDs. The
defect was therefore in builder namespace selection, not in the opaque trusted
capture or topology verifier.

After correcting namespace selection, two fixture-compatibility facts and one
error-priority issue became observable:

- The ten current external TradingAgents schedules now match the versioned
  contract, so historical assertions requiring RRULE/prompt drift were stale.
- A temporary relocated contract fixture omitted the explicit versioned
  role-contract path and therefore truthfully captured a missing sibling file.
- A missing contract was captured immutably as missing, but aggregate topology
  validation masked the established `contract_unreadable` reason as
  `captured_snapshot_invalid`.

## RED/GREEN repair

RED regression:

```zsh
PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_safety_sentinel.py::test_automatic_schedule_capture_ignores_unrelated_automation_namespace
```

Before the implementation change, this failed because the automatic evaluator
returned `contract_status="fail"` for a valid ten-record TradingAgents fixture
that coexisted with an unrelated `weekly-review` automation.

GREEN changes:

- Descriptor-relative discovery now considers only `tradingagents-*`
  directories. Every contract ID is still independently unioned into capture,
  so missing expected files are captured and rejected rather than hidden.
- Exact discovered/expected/TOML set equality is unchanged. Existing regressions
  prove that an extra `tradingagents-*` record and a symlinked source remain
  invalid.
- `evaluate_schedule_contract` decodes only the trusted evaluator-owned capture
  bytes, then reports an unreadable captured contract before aggregate capture
  diagnostics. This restores the normal source-path error contract without a
  mutable-path reread or an authorization path.
- Role-contract fixtures now supply the explicit role-contract path when they
  relocate a contract, and current-state expectations describe the verified
  current external configuration rather than historical drift.

## Security properties preserved

- Opaque exact-type handles and evaluator-owned canonical bytes remain the only
  captured-evaluation input.
- Authentication, manifest projection, and semantic parsing still consume
  fresh private copies decoded from the same immutable bytes.
- Hand-built and mutable mappings remain rejected as
  `captured_snapshot_invalid`.
- Capture timestamps, descriptor-relative no-follow reads, file identity,
  digests, sizes, statuses, root binding, and exact trusted TradingAgents
  topology remain enforced.
- No evaluator path rereads a captured contract, role file, or automation TOML.
- The weak-key trusted-capture lifetime design and sentinel interface are
  unchanged.
- Every failure result remains non-deploying and non-authorizing.

## Verification

- New compatibility plus same-namespace topology guards:

  `3 passed in 1.02s`

- Role-contract suite plus selected immutable/topology guards:

  `15 passed in 0.99s`

- Requested focused/dependent suites:

  ```zsh
  PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q tests/test_automation_role_contracts.py tests/test_automation_health_audit.py tests/test_safety_sentinel.py tests/test_authority_role_alignment.py
  ```

  Result: `120 passed, 2 warnings in 2.72s`. The warnings are the existing
  invalid-escape `SyntaxWarning` messages from authority-inventory AST parsing.

- Ruff:

  ```zsh
  PYTHONPATH="$PWD" /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m ruff check tradingagents/evals/automation_health_audit.py tests/test_safety_sentinel.py tests/test_automation_role_contracts.py
  ```

  Result: `All checks passed!`

- `compileall` passed for the three modified Python files.
- `git diff --check` passed.
- The exact worktree was re-indexed after the source change; all three operated
  Python paths had current metadata and no recorded graph-coverage issue.

## Retained concern

`tests/test_automation_role_contracts.py` intentionally reads the current
external TradingAgents automation TOMLs. A future legitimate schedule change
may make that current-state assertion fail until the versioned contract and
test expectation are deliberately reconciled. There is no remaining Task 2
automatic-capture blocker in the requested focused suites.
