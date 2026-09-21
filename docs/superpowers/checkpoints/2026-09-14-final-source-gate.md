# Final source gate — 2026-09-14

## Accepted source, not operational readiness

The corrected canonical source candidate
`81b7463cbfe612bdbb9c7c0f25b0a3e05a1349da` passed the complete repository gate.
Canonical `master` was clean before and after the run. Its tree is
`a9739c935fb1a1bff4ed145d1ec420313704545b`.
The reused bar-shapes worktree was also clean at that revision before this
documentation-only checkpoint. No new worktree, subagent or dependency was added.

The original full program remains active and incomplete. This accepts the
source/test portion of Phase 10; it does not supply the missing real economic,
learning, research, supersession or operational evidence. The earlier stopped
`5771809` run remains preserved and is not a passing gate.

## Terminal verification

The one corrected full run started at `2026-09-14T03:25:05.857039+00:00` and
finished at `2026-09-14T05:13:13.127466+00:00`. Tool session **24109** terminated
with exit **0**; runner PID 21143 and pytest PID 21190 were then absent.
These handles are terminal: do not poll or restart them.

| Required check | Result |
| --- | --- |
| Complete pytest, no module deselection | 5,005 passed, 1 skipped, 75 subtests passed; 6,485.33 seconds |
| Ruff on `cli tradingagents scripts tests` | Passed |
| Compile `cli tradingagents scripts` | Passed |
| `uv lock --check --offline --no-progress` | Passed; 124 packages resolved |
| `zsh -n scripts/mac/ta_job.sh` | Passed |
| `git diff --check` | Passed |

Pytest used `TA_LIVE_SUBMIT=0`, canonical `PYTHONPATH`, `-q --durations=15`, and
a retained JUnit report. All 36 API-key environment names used by the existing
test fixture were set to placeholders before collection; real credentials were
not modified. The sole live DeepSeek integration was skipped explicitly. This
is not live provider, broker, model, account or economic acceptance.

JUnit reports 5,081 cases including subtests, zero failures, zero errors and
one skip, consistent with the terminal summary. Eleven warnings remain: seven
unknown/future Anthropic model-name cases, one Google model-name case, two
existing invalid-escape warnings during AST inventory checks, and one Ollama
test's `response_format` forwarding warning. They were read, not hidden or
treated as live model qualification. No performance improvement is claimed.

All six log hashes were independently read back and matched the terminal
receipt. This was a solo receipt/requirements audit, not independent-agent review.
Earlier focused/affected proof remains in the Phase 4, 5, 6.1, 7, 8 and
[REST-repair](2026-09-14-adjusted-price-rest-contract.md) checkpoints; it was not
replayed. The last repair's affected gate passed 155 tests in 120.50 seconds.

## Durable identities

Receipts remain under
`.superpowers/sdd/2026-08-30-tradingagents-evidence-first-working-state-completion/`.

| Artifact | SHA-256 |
| --- | --- |
| `phase10-source-gate-20260913-81b7463/receipt.json` | `e369c485c8e5dbe3d19863be94d875f7624c2cf7faf113ebaa7fc2ae3e8fa40e` |
| Same directory, `pytest.log` | `3cfe7b7bbf1d1459363a7ab9bb9557aaad12523551b299a3eed09bd637af3f8e` |
| Same directory, `pytest.xml` | `d1f50b50fffbc080c18bc25b2d193d8b599c0c17007502890ecbaf5efa96a0a0` |
| `phase10-final-source-hashes-20260914.sha256` | `4223d4fa58db8789fb953bb3a91a0c90742b9e5a6f413b482d67c50d482fc2e9` |
| `phase10-final-source-index-20260914.json` | `dba4fc8ebb0d811a6d06a5363e7e690093be221dafb362635aeeb323fcfcaf37` |
| `pyproject.toml` | `87de7ad2ffaf1c49856916a8977a72028538701f8a299d6d95a249ac3be9435a` |
| `uv.lock` | `3467e3497c8bf436ef9a4f939ccf0d4460906c61268565d6e275b21cb41413d2` |
| `tradingagents/default_config.py` | `f000343da0b187dfd7250ca1ad7c9dd9b56b610be2cca7a034bcf412c0a69eb0` |

Runtime identity: canonical `.venv/bin/python`, Python 3.13.14; pytest 9.1.1,
Ruff 0.15.15, LangGraph 0.4.8, SQLite checkpoint package 3.1.0,
langchain-core 1.4.0 and OpenAI SDK 2.38.0. Tracked defaults remain checkpointing
off and analyst concurrency 1. Tracked model defaults are OpenAI `gpt-5.4` and
`gpt-5.4-mini`; these are source defaults, not a claim about an active runtime,
an accepted research lane or permission to call them. The registered research
plan's OpenRouter route and deterministic-first prerequisite remain unchanged.

The source hash manifest covers all **75 changed source/test paths** between
the intake canonical `47ed452634a56b8b389013a1ba4b01ed1a55736f` and the accepted
candidate. Other differences in that interval are documentation; configuration,
dependency files and scripts have no diff in that comparison.

Canonical index `tradingagents-canonical-master-final-20260822` was refreshed at
`2026-09-14T03:29:37Z` in moderate mode without repository-artifact persistence:
14,431 nodes and 93,381 edges. The final 75-path coverage check found **73 matching
metadata records with no recorded issue**. `tests/fixtures/__init__.py` and
`tests/fixtures/economic_tournament.py` remain excluded by the existing fixture
subtree rule; direct source/AST and the full tests cover their verification.
The unrelated archived Dockerfile still has a partial parse at line 29.
Coverage is best-effort, not a claim of complete graph parsing; no ignore rule
was loosened and no second index rebuild was needed.

## Preserved owners and real evidence

The terminal runner's before/after checks matched all four frozen owners,
all ten PAUSED automation TOMLs, all 24 retained private Alpaca response hashes,
and the original Phase 5 ZIP. `.env` remains mode 0600. Exact automation
IDs/hashes remain in `task-3-preservation-2026-09-07.json`; all ten statuses
were checked as PAUSED, not inferred from that historical manifest alone.

- Live control remains frozen, SHA-256
  `a3fc5ddb2b300596833c48c1554fad088ecb43d46bd70aeeac074531d6e9fb07`.
- The real learning ledger remains SHA-256
  `10b3c228c1de2ecc91242083df90aac7a47f7cdd870f7e75eca657bd0d28c223`:
  6,244 rows, 4,944 resolved and 1,300 pending in the bound read-only audit.
  These are stored statuses, not newly accepted source-bound outcomes.
- Promotion state remains SHA-256
  `8b0e5d99cde2db1b59b1c522c458b1ddbde2770be38e18cf27d4b68bda45e196`.
  Actual legacy supersession has not happened; do not claim every sleeve is
  already paper-only/live-disabled.
- The original handoff remains SHA-256
  `d7440a09d358d37b4da531be9fe8c2ccd3c59b160438869a2e1f078aab4bd057`.
  Both handoffs and all preserved worktrees remain retained.

The account capture and standardized raw capture retain their existing IDs
`20260913T200134226135Z` and `20260913T201816173345Z`. Their manifest hashes are
`92171ab61186c41a48b34193947383381c6122ceb60ee9a0062c4201052fe153` and
`fcf78c0c8835c2b939764321ad4bea9e6eae8cc3440423c4820957d51264d611`.
This source checkpoint creates no admitted cohort/protocol, source-bound
economic receipt/store ID, frozen forecast/event mapping or benchmark verdict.
The newly retained multi-symbol bars are still not valid single-symbol adjusted
window inputs and cannot establish historical custody. Read the existing
Alpaca raw-custody and ledger-overlap reports for exact limits; do not refetch.

## Remaining full-program work

| Requirement | Still required; this source gate is not its evidence |
| --- | --- |
| Task 5.5 | Registered real cohort and permitted model calls before concurrency 1 versus 2 comparison; keep 1 |
| Task 6.2 | Accepted PIT/archive/window receipts and legitimate forecast/event mapping, then real backed-up fixed-point ledger reconciliation |
| Phases 7 and 9.2 | Real 500/300/400/200 benchmark corpus, deterministic/FTS acceptance, then permitted registered model lanes or a valid no-model verdict |
| Phase 8 actual transition | Ordered evidence prerequisites, trusted historical preservation/supersession and non-authorizing current readiness; no transition was performed here |
| Phase 9.1 | Genuine historical admission or a prospective 75/100/50 cohort with effective-dated security identity, official source custody, complete outcome evidence and ordered lifecycle |
| Holdout | Separate owner-reviewed release; never infer it from a passing test |
| Phase 10 evidence record | Fill real protocol/store/receipt identities and benchmark/economic verdicts only when accepted; do not replace them with synthetic test IDs |
| Phase 11 | All prerequisites and relevant fresh broker/model authority, then one future regular-session qualifier plus five distinct clean sessions; paper submission separately authorized |
| Phase 12 / retirement | Preparation-only seven-eligible/three-paused activation card, final non-authorizing checkpoint and full handoff reconciliation; no activation or deletion now |

The closed archive search is not reopened. Additional free SEC and Alpaca
universe collection remains the existing unanswered authority request; the
account-capture permission is not silently expanded. No broker call, model call,
submission, cancellation, schedule/outbox change, live rearm or actual
ledger/promotion mutation occurred in this checkpoint.

Next starting owner: the current continuation of the original implementation
plan. Reuse this accepted exact-source gate for documentation-only follow-up
and later unchanged-source evidence days. If source changes, verify the affected
behavior and the corrected candidate as required; never replay merely because
an observation timed out or a new task resumes.
