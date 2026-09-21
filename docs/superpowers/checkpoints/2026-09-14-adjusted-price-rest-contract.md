# Adjusted-price REST contract repair — 2026-09-14

## Finding and scope

Follow-up to the preserved Alpaca capture identified a real source defect on
canonical `57718091b589a291d22d62c1526937d1247cdb59`:
`adjusted_price_windows.py` required a single-symbol REST URI but expected
symbol-indexed `bars`, the format of a different endpoint or SDK conversion.
Consequently valid single-symbol responses could not produce adjusted windows,
while synthetic fixtures with the wrong route/body combination could pass.

Alpaca's [single-symbol reference](https://docs.alpaca.markets/us/reference/stockbarsingle-1)
and [official OpenAPI schema](https://github.com/alpacahq/alpaca-docs/blob/master/oas/data/openapi.yaml)
were read on September 14. `BarsResponse` defines a bar list, a response symbol,
and a nullable page token. The [multi-symbol endpoint](https://docs.alpaca.markets/us/reference/stockbars)
is distinct and can paginate across symbols. Only public documentation was
queried; no account, market-data or model request ran during this repair.

The existing isolated `oai/tradingagents-alpaca-bar-shapes-20260913` branch was
clean at `8fc3296` and fast-forwarded to canonical `5771809` before editing.
The worktree/inline execution skills preserved the existing branch, dependencies
and full plan; no new worktree or subagent was created.

## Repair

- Parse the actual single-symbol REST bar list and require its response symbol
  to equal the symbol bound by the source URI and requested window.
- Require an explicitly null `next_page_token`. Reject non-final or malformed
  responses and requests that start from a continuation token: one retained
  final page cannot prove the missing predecessor pages.
- Keep the exact single-symbol route, request bounds, adjustment/feed,
  retrieval cutoff, raw-byte hashes, session and positive-price checks.
- Correct eight synthetic response literals across seven dependent test/fixture
  modules. An AST comparison against `5771809` confirmed that these files differ
  only by moving the existing bar sequence into the REST list and adding its
  same symbol and null page token. Prices, dates, forecasts and assertions were
  not changed. No real retained object was converted or overwritten.

Production owner: `tradingagents/dataflows/pit/adjusted_price_windows.py`.
New regression owner: `tests/test_pit_adjusted_price_rest_contract.py`.
Other changed files are the seven source-bound learning/economic fixtures listed
in the Git diff. No CLI, live-control, promotion, ledger or automation code changed.

## Verification and stopped candidate

The new regression module first produced **2 expected failures / 11 passes in
0.64 seconds**, terminal session 40292 exit 1. Failures demonstrated rejection
of valid REST and acceptance of the wrong body shape. After repair, all **13
passed in 0.11 seconds**, exit 0. Cases cover exact raw-byte re-verification,
symbol mismatch/missing identity, wrong response shape, missing/malformed page
fields and a final continuation page without its predecessor evidence.

Receipts under the existing ignored SDD directory:

- `phase10-adjusted-rest-red-20260914.xml`, SHA-256
  `4156ef81ad001e35a94ed209c7ae37627f85171cccdf626b9d228348df9ccb71`.
- `phase10-adjusted-rest-green-20260914.xml`, SHA-256
  `c8c39275a9ebdfb4e228d834a3eb120deeeaa05529c0e0833ca7d846d9322811`.
- Affected seven-module gate: **155 passed in 120.50 seconds**, terminal session
  58807 exit 0. One existing `cli/utils.py:451` invalid-escape warning.
  `phase10-adjusted-rest-affected-20260914.xml`, SHA-256
  `3a7a0f27a900ea32a81d15ceec0862fdd61182704e47dabc2db3bdde4c805f03`.

The affected command ran `tests/test_pit_adjusted_price_rest_contract.py`,
`tests/test_pit_adjusted_price_windows.py`, `tests/test_source_bound_resolution.py`,
`tests/test_agent_intelligence_ledger.py`, `tests/test_agent_variants.py`,
`tests/test_economic_execution_outcomes.py` and
`tests/test_economic_evaluation_protocol.py` with canonical Python, the exact
isolated worktree as `PYTHONPATH`, `TA_LIVE_SUBMIT=0`, `-q --durations=10` and
the JUnit destination above. The broad shared-fixture consumers remain part of
the required corrected full repository gate, not an additional duplicate run.

Nine-path Ruff, source compilation, diff checking and the exact eight-literal
AST comparison passed. Dependency files are unchanged. Solo diff review
confirmed that request/custody/economic gates were not loosened; this was not
an independent-agent review.

Only after reproducing the defect was original full-gate pytest PID 63420
terminated once. Its owner session 42107 is terminal exit 1; the retained runner
records pytest exit **-15**, 1,747.873 seconds, `source_changed=false` and passing
post-run preservation. Runner and pytest PIDs were then absent. This was an
intentional supersession for a demonstrated defect, not a restart caused by
quiet output, timeout or confused process handles. The original statics passed,
but the interrupted full suite has no passing result. Preserve its complete
`phase10-source-gate-20260913-5771809/` directory unchanged.
The terminal receipt SHA-256 is
`b7222390b5ecd6463751968e60603567404279a0ff083c0c3f08117e87ff04d2`.

## Unchanged evidence boundaries

The real capture used a broad multi-symbol request. It still does **not** match
the strict adjusted-window input contract. This repair does not make the 3,492
overlapping ledger rows accepted labels, supply the 28 uncaptured tickers,
create a historical custody record, supply an economic event mapping or admit
a protocol. No price-window receipt or actual ledger reconciliation was run.
Future collection remains within its separate authorization boundary.

All four frozen owners, ten PAUSED automation files, 24 private Alpaca response
hashes and the original Phase 5 ZIP passed the stopped runner's final preservation
check. Live control remains frozen; the actual promotion/ledger files retain
their prior bytes. The full readiness goal remains incomplete. A final corrected
source gate, real evidence/qualification and all operational authorization
requirements are still outstanding.
