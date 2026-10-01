# TradingAgents Alpaca source probe — implementation package

This package contains real implementation code and executed offline tests, not
another research prompt. The change is intentionally the first bounded slice:
source-intake diagnostics and replay, not the final historical security master.

## Deliverables

- `tradingagents-alpaca-source-probe.patch`: four additive repository files.
- `source/`: the same four files as readable source.
- `BUILD_RECEIPT.json`: exact source hashes, validation scope and limitations.
- `TEST_RESULTS.txt`: the actual final pytest output.
- `SYNTHETIC_DIAGNOSTIC_REPORT.json`: toy-fixture result, not real stock data.
- `EXAMPLE_PLAN.json`: explicit non-executed request scope.
- `EXAMPLE_REQUESTS.json`: generated URLs for reviewing that example scope.
- `INTEGRATION_NOTE.md`: instructions for the current local coding session.

The remote reference inspected was `b3484fe22270b9282adef2228a35477558730b4a`.
A full clone could not be downloaded in the implementation environment. The new
module and its standalone script were therefore tested in isolation. Neither the
GitHub repository nor the current local Mac checkout has been changed. No real
Alpaca request was executed, and no market dataset is being represented as qualified.

## Integrate without discarding current work

Use the current checkout or an intentional worktree based on it. Do NOT reset to
the older remote revision. First inspect the patch and the current working tree;
preserve all Codex-runner and benchmark edits. The patch only adds:

1. `tradingagents/dataflows/alpaca_source_probe.py`
2. `scripts/alpaca_source_probe.py`
3. `tests/test_alpaca_source_probe.py`
4. `docs/data/ALPACA_SOURCE_PROBE.md`

After reviewing it, check and apply the patch from the intended repository root:

```sh
git apply --check "/absolute/path/to/tradingagents-alpaca-source-probe.patch"
git apply "/absolute/path/to/tradingagents-alpaca-source-probe.patch"
```

If the check fails or one of the four new paths already exists, stop and reconcile
with that local work instead of forcing the patch. These instructions do not
change branches, reset files, commit, push, or execute a data collection.

Then use the project's existing environment for the focused tests and ordinary
static checks. Read `docs/data/ALPACA_SOURCE_PROBE.md` for exact usage and limitations.

## What the passing tests mean

85 tests passed on Python 3.13.5. Python 3.10 syntax compatibility, compilation,
patch application in a fresh directory, and source-byte equality were checked.
Ruff was not installed in this environment and was not run. The full repository
suite and integration into the latest local checkout are still required at their
appropriate checkpoint.

The tests cover fixed GET-only routes, no redirects, explicit collection opt-in,
no package/dotenv initialization for offline use, response/byte/page budgets,
pagination, exact decimal medians, 60-session completeness, identity ambiguities,
raw replay, malformed inputs, event redelivery, and no false cohort qualification.
They do not prove live endpoint entitlement, historical coverage, real corporate
history, complete universe membership, or investment performance.
