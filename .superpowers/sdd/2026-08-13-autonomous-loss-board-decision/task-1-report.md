# Task 1 implementation report: autonomous loss BOARD decision boundary

## Scope completed

Implemented the immutable, decision-only HOLD/SELL boundary in the assigned
files only:

- `tradingagents/policy/loss_board_decision.py`
- `tradingagents/orchestration/work_packets.py`
- `tests/test_loss_board_decision.py`

The recorder captures each supplied supervisor and loss-evidence file as bytes
once, then parses those captured bytes and binds their relative path, SHA-256,
and byte count. It writes the canonical decision object as a content-addressed,
immutable evidence file and records an analysis-only `portfolio_decision` work
packet through `DecisionLedger`.

## Decision and safety contract

- `AutonomousLossBoardDecision` is a frozen dataclass with the required fixed
  producer and execution fields: `portfolio_executive`, `analysis_only=true`,
  `execution_authority="none"`, and `can_submit_orders=false`.
- The decision ID is SHA-256 over canonical JSON material excluding the ID.
- The schema validates uppercase symbols, a lowercase 40-hex source revision,
  canonical decimal confidence, exact booleans, unique source bindings, and
  whole-second canonical UTC timestamps with a maximum 15-minute lifetime.
- It enforces the requested equivalence: `SELL == exit_allowed ==
  evidence_complete`. Any HOLD has `exit_allowed=false`, incomplete evidence,
  and at least one structural evidence gap.
- A SELL requires source-bound supervisor and loss packets; matching symbols;
  fresh quality-qualified market, company-news, and earnings/guidance/filing
  sources; actual SPY/QQQ/sector values; a company-specific news finding;
  filing substance rather than a SEC submissions index; a loss-exit reason and
  source; a current thesis/why-HOLD-is-worse explanation; confidence >= 0.75;
  and no non-session blockers.
- Gap, missing, unavailable, connector, and SEC-index-style evidence cannot
  qualify a SELL. Failed qualification records HOLD or fails before recording;
  it never produces SELL.
- The only new work-packet advisory effect is `record_trade_decision`. The
  recorded recommendation is `autonomous_hold` or
  `autonomous_sell_authorized_pending_execution_intent`; no order, sizing,
  control, promotion, or risk effect was added.

## RED/GREEN evidence

RED was run before implementation:

```text
PYTHONPATH=/Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-loss-board \
  /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q \
  tests/test_loss_board_decision.py

ModuleNotFoundError: No module named 'tradingagents.policy.loss_board_decision'
```

The final focused validation was run using the canonical repository virtualenv
with `PYTHONPATH` set to this isolated worktree:

```text
PYTHONPATH=/Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-loss-board \
  /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/python -m pytest -q \
  tests/test_loss_board_decision.py tests/test_work_packets.py \
  tests/test_decision_ledger.py

146 passed in 0.35s

PYTHONPATH=/Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-loss-board \
  /Users/corbinfloyd/Documents/TradingAgents/.venv/bin/ruff check \
  tradingagents/policy/loss_board_decision.py \
  tradingagents/orchestration/work_packets.py \
  tests/test_loss_board_decision.py

All checks passed!

git diff --check

(no output; passed)
```

## Tests added

`tests/test_loss_board_decision.py` covers:

- a fully qualified immutable SELL decision with immediate ledger and decision
  verification;
- malformed/string booleans;
- exact symbol mismatch;
- stale supervisor, source, and raw loss-packet timestamps;
- missing sector values;
- missing company news;
- SEC-submissions-index-only evidence;
- stale cached news;
- transcript/config-gap source evidence;
- immutable source-byte mutation detection; and
- tampered canonical decision ID detection.

## Runtime posture

This task introduces no execution authority and submits no orders. A recorded
SELL remains a ledgered portfolio decision pending a separate execution intent
and its independent controls.
