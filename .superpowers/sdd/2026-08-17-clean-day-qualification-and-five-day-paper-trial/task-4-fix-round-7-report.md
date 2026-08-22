# Task 4 fix round 7 — implementation report

## Scope and starting point

- Worktree: `/Users/corbinfloyd/.codex/worktrees/tradingagents-clean-day-paper-trial`
- Branch: `codex/clean-day-paper-trial`
- Starting HEAD: `a9f9f28b4e49eca9ec506b318543a862eb252687`
- Fix scope: close two fresh P1 false-clean paths without changing the valid
  empty-candidate/no-signal or complete loss-review HOLD behavior.
- The codebase graph and direct source reads traced
  `_fetch_aggressive_candidate_market_data` to paper tournament run/report,
  overnight planning, preopen validation, overnight verification, hourly
  supervision, and the daily report.
- The implementation did not change `results/policy/live_control.json`, an
  automation TOML, provider configuration, broker state, or any schedule.

## RED evidence

The worktree has no `.venv` link, so verification used the canonical repository's
existing interpreter at `/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python`.

```zsh
/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q \
  -p no:cacheprovider \
  tests/test_alpaca_cli.py::test_fetch_aggressive_candidate_market_data_raises_on_total_provider_failure \
  tests/test_alpaca_cli.py::test_candidate_market_data_result_distinguishes_empty_success_from_failure \
  tests/test_alpaca_cli.py::test_all_aggressive_candidate_market_data_callers_use_explicit_result_channel \
  tests/test_shadow_trial.py::test_stage_semantics_accept_native_shapes_and_reject_provider_graph_and_broker_errors
```

Initial outcome: `4 failed in 9.03s`. The failures proved that total yfinance
transport failure still returned `{}`, no explicit result/error helper existed,
none of the seven callers used such a channel, and blocked/incomplete loss-review
evidence still returned no stage-semantic rejection reason.

## GREEN implementation

- `cli/main.py`
  - Adds `AggressiveCandidateMarketDataError`; successful fetches still return the
    original dictionary, including a valid empty dictionary, while a total
    provider/transport exception is no longer converted into empty success.
  - Adds one safe result helper that returns `(market_data, errors)`. A legitimate
    empty result is `({}, {})`; failure is `({}, {"market_data": ...})`.
  - Routes all seven production callers through that explicit channel.
  - Persists the error mapping in overnight, preopen, hourly, daily-report, and
    paper tournament packets; the verifier records a failed check. Preopen retains
    its native broker-error path and now exposes those errors at packet top level.
- `tradingagents/evals/shadow_trial.py`
  - Retains the existing recursive explicit-error rejection for every stage.
  - Requires loss-review `remaining_blockers` and current-review blockers to be
    empty and `trade_decision_allowed=true`, proving complete current evidence.
  - Requires a native nonempty `advisory_analysis.route_summary` and rejects
    malformed, blocked, or explicit error/failed provider attempts.
  - Preserves `next_action=autonomous_hold`, non-authorizing fields, and exactly
    zero submitted orders as the clean loss-review authority contract.
- `tests/test_alpaca_cli.py` and `tests/test_shadow_trial.py`
  - Prove transport failure differs from valid empty success.
  - Prove every traced caller both uses and persists the failure channel.
  - Prove valid empty/no-signal overnight, preopen, hourly, daily, and paper stage
    shapes remain acceptable while the same shapes with a market-data error fail.
  - Prove blocked provider attempts, incomplete refreshed evidence, and explicit
    loss-review errors fail independently; the complete unblocked HOLD stays clean.
- `tests/test_authority_role_alignment.py`
  - Updates only the two exact `cli/main.py` source-line inventory coordinates
    shifted by the new helper. The classified HTTP mutation scopes and meanings
    are unchanged.

## Verification evidence

Focused GREEN after implementation and the final separated blocked/incomplete
assertions:

```zsh
/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q \
  -p no:cacheprovider \
  tests/test_shadow_trial.py::test_stage_semantics_accept_native_shapes_and_reject_provider_graph_and_broker_errors \
  tests/test_alpaca_cli.py::test_fetch_aggressive_candidate_market_data_raises_on_total_provider_failure \
  tests/test_alpaca_cli.py::test_candidate_market_data_result_distinguishes_empty_success_from_failure \
  tests/test_alpaca_cli.py::test_all_aggressive_candidate_market_data_callers_persist_explicit_failures
```

Outcome: `4 passed in 0.84s`.

Final affected/dependent suite:

```zsh
/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q \
  -p no:cacheprovider \
  tests/test_shadow_trial.py tests/test_alpaca_cli.py \
  tests/test_paper_tournament.py tests/test_loss_review_evidence.py \
  tests/test_research_provider_orchestrator.py tests/test_alpaca_supervisor.py \
  tests/test_safety_sentinel.py tests/test_authority_role_alignment.py \
  tests/test_overnight_calibration_guard.py tests/test_overnight_context.py
```

Outcome: `475 passed, 2 warnings in 15.90s`. Both warnings are the existing
`SyntaxWarning: invalid escape sequence '\\`' reports from the two authority
inventory tests. An earlier authority-dependent pass reported `173 passed, 1
failed` only because adding the helper shifted two exact line coordinates; after
updating those coordinates, that batch passed `174 passed, 2 warnings`.

Static, compilation, whitespace, and shell verification:

```zsh
/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/ruff check \
  cli/main.py tradingagents/evals/shadow_trial.py \
  tests/test_alpaca_cli.py tests/test_shadow_trial.py \
  tests/test_authority_role_alignment.py
/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m compileall -q \
  cli/main.py tradingagents/evals/shadow_trial.py \
  tests/test_alpaca_cli.py tests/test_shadow_trial.py \
  tests/test_authority_role_alignment.py
git diff --check
zsh -n scripts/mac/ta_job.sh
```

Outcome: Ruff reported `All checks passed!`; compileall, `git diff --check`, and
the zsh syntax check exited zero with no output.

## No-runtime assertion

Only source/report edits, hermetic pytest cases with fake clients/providers and
temporary paths, static analysis, compilation, Git inspection, graph/source
inspection, and shell syntax parsing were performed. No provider or broker was
called; no runtime, scheduler, automation-management, safety-sentinel, self-heal,
paper-trial, live-control, order, cancellation, reconciliation, finalization,
outbox, or delivery command was run. No order was submitted or cancelled, no
schedule was activated, and no live-control or automation configuration was
modified.

Fresh independent Sol review remains required; this report does not self-approve
Task 4.
