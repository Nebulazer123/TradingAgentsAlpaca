# Task 2 implementation report: close autonomous loss decisions in authority and BOARD

## Scope completed

Implemented the Task 2 connection points only:

- `tradingagents/policy/decision_authority.py`
- `tradingagents/evals/execution_board.py`
- `tradingagents/research/loss_review_evidence.py`
- `cli/main.py`
- their focused test modules.

`ExitAuthorityVerdict` now distinguishes whether a loss decision is resolved
from whether that decision permits an exit.  The older `allowed` read remains
as a compatibility property.  A ledger-authenticated BOARD HOLD is resolved
but exit-disallowed; a ledger-authenticated SELL is resolved and exit-allowed,
but still has `execution_authority="none"` and no order capability.

## Authority and evidence boundary

- The resolver accepts only a `ledger_packet_id` plus caller-configured,
  preexisting ledger and evidence roots.  It rejects self-described decisions,
  copied paths, malformed inputs, stale/mutated records, and decisions for a
  different supervisor review.
- The BOARD records a decision only from a source-bound raw loss-evidence
  packet and its exact supervisor packet.  It publishes the immutable decision
  reference in `autonomous_loss_decision` and retains analysis-only/no-submit
  fields.
- The loss-evidence command writes provider source packets first and passes
  their exact local paths into the wrapper.  The wrapper preserves contained
  packet path, SHA-256, size, packet ID, as-of, and quality descriptors for the
  Task 1 recorder.
- Generic ticker quotes, watchlist/config/cache material, SEC submissions
  metadata, and transcript/connector-gap packets no longer clear market,
  company-news, or filing/guidance blockers.  Incomplete TSM-style evidence
  now deterministically remains `autonomous_hold`.
- The BOARD command has explicit repo-local `--decision-ledger-root` and
  `--decision-evidence-root` options.  Neither root comes from a research
  packet.  The default ledger is separate from the `results` evidence root.

## RED then GREEN

The authority RED test failed as intended before implementation:

```text
TypeError: resolve_exit_authority() got an unexpected keyword argument 'board_decision'
```

The final focused Task 2 verification was:

```text
PYTHONPATH=/Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-loss-board \
  /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q \
  tests/test_loss_board_decision.py \
  tests/test_decision_authority.py \
  tests/test_execution_board.py \
  tests/test_loss_review_evidence.py \
  tests/test_policy_rule_approval_contract.py

105 passed in 1.00s

/Users/corbinfloyd/Documents/TradingAgents/.venv/bin/ruff check \
  tradingagents/policy/loss_board_decision.py \
  tradingagents/policy/decision_authority.py \
  tradingagents/evals/execution_board.py \
  tradingagents/research/loss_review_evidence.py \
  cli/main.py \
  tests/test_decision_authority.py \
  tests/test_execution_board.py \
  tests/test_loss_review_evidence.py

All checks passed!

git diff --check

(no output; passed)
```

## Runtime posture

No broker, live-control, schedule, rearm, submit, cancel, or replace operation
was added or performed.  The new BOARD decision is deliberately a separate
decision record; even an evidence-qualified SELL awaits an independently
authorized execution intent.

## Repair round 1: reviewer hardening

The independent review correctly found two authority-boundary gaps.  They are
now repaired:

- **Exact current supervisor binding.**  `resolve_exit_authority` no longer
  treats a matching symbol and decision ID as sufficient.  For an autonomous
  BOARD decision it requires a `CurrentSupervisorReviewBinding` built from the
  caller's already-captured supervisor packet bytes.  The comparison requires
  the exact repository-relative path, SHA-256, byte size, decoded current
  review, decision ID, and symbol to match the authenticated Task 1 decision.
  The authority resolver does not reread the path, preventing a check-then-use
  file swap.  Tests reject both a replaced packet with the same symbol/ID and
  a wrong path/hash, while accepting the exact captured bytes.
- **Fixed production roots.**  The two public root override flags were removed
  from the execution BOARD and loss-evidence commands.  They now derive fixed
  canonical repository constants for `results` evidence and the separate
  `state/decision_ledger` boundary.  Tests verify the flags are absent from CLI
  help.  Internal builder arguments remain explicit so isolated tests can use
  temporary roots without weakening the production command.
- **Terminology.**  Remaining BOARD/manual loss-review wording in the owned
  paths now says autonomous portfolio BOARD.

Repair verification:

```text
109 passed in 1.01s
ruff check: All checks passed
git diff --check: passed
```

## Cross-slice repair: authenticated BOARD receipt projection

Task 3's strict self-heal verification exposed that the full BOARD report had
only a ledger packet ID and human-oriented paths.  Task 2 now publishes a
minimal machine-verifiable receipt derived after immediate ledger-authenticated
verification:

- `autonomous_loss_decision` retains the decision/result fields and adds the
  exact decision evidence path/SHA/size, symbol, supervisor decision ID and
  bound supervisor path/SHA/size, bound raw-loss packet ID/path/SHA/size,
  source revision, and a canonical accepted-source-list SHA/count.
- `loss_review_evidence.source_binding.bindings` projects exact `supervisor`
  and `raw_loss` identities in the schema Task 3 consumes.  These bindings are
  built from the authenticated decision and its exact captured raw-loss packet,
  not copied from summary input.
- Neither projection contains a caller-selectable trust root or gains any
  execution/order authority.
- The compact BOARD packet round-trips the complete immutable receipt and keeps
  `kind`, schema, analysis-only, `execution_authority="none"`, and
  `can_submit_orders=false`.

Cross-slice verification:

```text
242 passed in 3.03s
ruff check: All checks passed
git diff --check: passed
```
