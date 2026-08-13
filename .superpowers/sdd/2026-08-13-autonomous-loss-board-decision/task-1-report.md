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

## Repair round 1: review NO-GO remediation

The review found that the first implementation could infer completeness from
missing structures and could accept self-described source metadata. Repair
round 1 replaced that permissive path with a fail-closed contract:

- Supervisor `blockers` and `blocked_reasons` must each be present as exact
  empty lists; missing, malformed, or nonempty values force HOLD.
- Raw loss `remaining_blockers` must be present as an exact empty list.
  Missing is not interpreted as empty.
- The raw loss payload must bind the exact relative supervisor packet path and
  supervisor decision ID, in addition to both matching the same uppercase
  symbol. Unrelated same-symbol packets are rejected before any publication.
- Each accepted source is now an exact descriptor for a contained, regular,
  non-symlink source packet: relative path, captured SHA-256, byte count,
  packet ID, source name/type, as-of timestamp, and quality. The source file is
  read once for its hash and parse; all descriptor and packet fields must match.
  URL/self-label descriptors do not qualify. Mutation is detected by the
  decision verifier.
- SELL qualification now requires exact allowlisted loss-exit reasons,
  canonical SPY/QQQ and their relative-performance values, a meaningful sector
  relative value, substantive company-specific news and filing/guidance text,
  and all three fresh, high/medium-quality source categories. Gap, connector,
  and submissions-index source material remains a blocker.
- The advisory loss-exit candidate must exactly agree with the supervisor on
  reason, source, confidence, current thesis, and why HOLD is worse, and must
  remain explicitly BOARD-only. Missing/zero/contradictory candidate state
  forces HOLD.
- Verification now requires exact canonical JSON bytes, the exact schema with
  no dropped/extra entries, source-byte validation, and
  `generated_at <= now < expires_at`.
- Publication resolves a real evidence root, rejects symlink or escaping target
  paths/parents, uses no-follow creation where supported, fsyncs the file and
  directory, and calls the ledger only after the durable boundary. Collision and
  injected crash-boundary tests confirm no new ledger event is appended.

### Repair RED/GREEN evidence

The repair began with targeted RED tests against the original implementation:

```text
tests/test_loss_board_decision.py -k 'supervisor_blockers or missing_raw'
5 failed
```

Those failures showed nonempty/malformed supervisor blockers and omitted raw
remaining blockers could incorrectly produce SELL.

Final repair verification used the canonical virtualenv with this worktree on
`PYTHONPATH`:

```text
python -m pytest -q tests/test_loss_board_decision.py
28 passed in 0.24s

python -m pytest -q tests/test_loss_board_decision.py tests/test_work_packets.py tests/test_decision_ledger.py
159 passed in 0.45s

ruff check tradingagents/policy/loss_board_decision.py tradingagents/orchestration/work_packets.py tests/test_loss_board_decision.py
All checks passed!

git diff --check
(no output; passed)
```

## Ledger-authenticated verifier interface

The public `verify_autonomous_loss_board_decision` interface now requires
`ledger_root`, `ledger_packet_id`, and `evidence_root`; a standalone decision
path is not authentication. `DecisionLedger.read_authenticated_packet` is the
narrow read-only provenance API: it replays the immutable journal and packet
objects, requires exactly one matching event, and checks the stored packet hash
against that event.

The BOARD authenticator captures the exact decision, supervisor, and raw-loss
ledger references; enforces immutable identity path/hash bindings; rebuilds the
decision at its stored `generated_at` policy moment; preserves one capture per
accepted source; and compares the complete rebuilt decision and canonical
WorkPacket bytes. Current expiration remains independently enforced. It rejects
canonical decision files without a ledger event, self-admitted or substituted
packets, ledgered but fabricated decision flags, journal corruption, and
evidence-reference substitution. Real recorded SELL and HOLD decisions pass.

### Ledger-authenticator RED/GREEN evidence

RED demonstrated that the prior standalone parser could inspect a canonical
decision file without a matching ledger record. New adversarial tests prove
rejection of a copied evidence tree with no journal event, a separately admitted
self-consistent packet, and a ledgered canonical HOLD that contradicts the
evidence-derived SELL.

```text
python -m pytest -q tests/test_loss_board_decision.py
49 passed in 0.41s

python -m pytest -q tests/test_loss_board_decision.py tests/test_work_packets.py tests/test_decision_ledger.py
180 passed in 0.57s

ruff check tradingagents/policy/loss_board_decision.py tradingagents/orchestration/decision_ledger.py tradingagents/orchestration/work_packets.py tests/test_loss_board_decision.py
All checks passed!

git diff --check
(no output; passed)
```

## Repair round 3: typed source references and strict directional evidence

Round 3 removes the last narrative and self-declared-boolean route to SELL.
Every SELL-supporting source payload now has one exact, bounded schema:

- Market evidence contains only the symbol/current as-of plus exact SPY, QQQ,
  and company-sector-relative typed value records. The source values must equal
  the supervisor values and each company relative value must be at or below
  `-0.01`; favorable numeric values fail closed.
- News evidence contains only symbol/current as-of, one allowlisted adverse
  event category, `direction="adverse"`, and a finite negative impact fraction
  at or below `-0.01`. Unknown or raised guidance categories, favorable
  numeric values, and extra prose fields do not qualify.
- Filing/guidance evidence has the corresponding exact typed schema, using an
  allowlisted adverse filing event and a finite negative change fraction at or
  below `-0.01`. Transcript sources remain insufficient rather than being
  treated as a substitute for substantive filing/guidance evidence.
- Supervisor and raw advisory `allowed_exit_reason_source` fields are now an
  exact typed `{packet_id, path, sha256}` reference to exactly one captured
  accepted source binding. Text labels, missing/nonexistent bindings,
  disagreement, and duplicate bindings are rejected before ledger publication.
- On creation of the immutable decision directory, the pre-existing resolved
  evidence root is fsynced after `mkdir` and before file publication. Both
  root- and decision-directory descriptor cleanup is covered under injected
  fsync failures, and neither failure permits a ledger record.

The autonomous exit-reason subset remains deliberately narrower than the
canonical supervisor taxonomy: it permits only thesis invalidation,
company-specific negative news, and earnings/guidance breaks. Manual override
and pre-registered mechanical policy exits are not re-authorized by BOARD and
continue to fail closed in this analysis-only boundary.

### Repair round 3 RED/GREEN evidence

The round began RED with the new strict-schema and typed-reference adversarial
tests: legacy prose/flag qualification produced a HOLD baseline mismatch, and
the test helpers still supplied string source labels rather than immutable
bindings. The minimal implementation then replaced those contracts with exact
structured source packets and the typed binding reference.

Final verification used the canonical virtualenv with this worktree on
`PYTHONPATH`:

```text
python -m pytest -q tests/test_loss_board_decision.py
43 passed in 0.30s

python -m pytest -q tests/test_loss_board_decision.py tests/test_work_packets.py tests/test_decision_ledger.py
174 passed in 0.54s

ruff check tradingagents/policy/loss_board_decision.py tradingagents/orchestration/work_packets.py tests/test_loss_board_decision.py
All checks passed!

git diff --check
(no output; passed)
```

Repair implementation commit: `99d94b082a170b7190d314ec4f2154d97232bff2`

## Repair round 2: authentic source-content qualification

Source review found that round 1 authenticated source packet identity and bytes
but still accepted semantic labels and generic prose. Repair round 2 requires
the accepted source packet contents themselves to prove each decision input:

- The market source must bind the decision symbol and current `as_of`, and
  carry structured finite SPY, QQQ, and symbol-sector-relative decimal values
  that exactly equal the supervisor review values. Labels or prose mentioning
  those benchmarks cannot qualify.
- Company-news source data must bind the symbol/current `as_of`, explicitly
  mark `sentiment="negative"` and `thesis_break=true`, and provide meaningful
  adverse company-specific text. Favorable, neutral, positive/improved,
  no-impact, and placeholder content force HOLD.
- Filing/earnings/guidance data must bind symbol/current `as_of`, explicitly
  mark an adverse earnings/guidance state and `adverse_fact=true`, and include a
  meaningful adverse fact. A merely available filing or generic prose cannot
  qualify.
- The taxonomy source of truth is now the exact supervisor
  `ALLOWED_LOSS_EXIT_REASONS` set. The autonomous BOARD subset is deliberately
  narrower: `thesis_invalidated`, `company_specific_negative_news`, and
  `earnings_or_guidance_break`. It is checked against the canonical set at
  import time and in the contract tests. `user_manual_override` and mechanical
  policy/pre-registered exits remain non-BOARD and fail closed here; their
  separately authorized routes are outside this decision-only boundary.
- Directory fsync is now inside a `try/finally` that closes its descriptor even
  when `fsync` fails; fault injection proves no ledger event is written.

### Repair round 2 RED/GREEN evidence

The new RED slice initially failed six cases: the policy module lacked the
canonical taxonomy export, favorable/neutral/placeholder news and label-only
market/filing content could be accepted, and a directory-fsync exception left
its descriptor open.

Final targeted GREEN:

```text
pytest -q tests/test_loss_board_decision.py -k 'taxonomy or non_board or company_news_source or market_and_filing or directory_fsync'
9 passed, 28 deselected in 0.17s
```

Final combined verification:

```text
python -m pytest -q tests/test_loss_board_decision.py tests/test_work_packets.py tests/test_decision_ledger.py
168 passed in 0.48s

ruff check tradingagents/policy/loss_board_decision.py tradingagents/orchestration/work_packets.py tests/test_loss_board_decision.py
All checks passed!

git diff --check
(no output; passed)
```

## Atomic source-capture repair

Accepted source packets are now captured exactly once per source, as one
private immutable association of the captured bytes, decoded JSON object, and
verified source binding. During decision creation, descriptor hash/size,
canonical JSON parsing, packet identity/as-of/quality validation, semantic
qualification, exact exit-reason source resolution, and the decision's
accepted-source fields all consume that single capture. The semantic phase no
longer opens a source path.

Decision verification performs one corresponding capture per accepted source
and validates it against the stored binding without a second source read.
This prevents a time-of-check/time-of-use cross-bind between a packet's hash,
parsed object, and semantic content. Supervisor and raw-loss packet behavior is
unchanged.

### Atomic capture RED/GREEN evidence

The two new RED tests initially failed because creation opened every source
again for `BoundSourceEvidence.verify` and the semantic pass, while verification
opened it twice for hash and metadata validation. The tests inject a failure on
the second source open. Creation also mutates a source immediately after its
first capture: the created decision remains bound to the captured bytes, and a
later verification observes the on-disk mutation as a binding failure rather
than cross-binding it into the creation decision.

Final verification used the canonical virtualenv with this worktree on
`PYTHONPATH`:

```text
python -m pytest -q tests/test_loss_board_decision.py
45 passed in 0.30s

python -m pytest -q tests/test_loss_board_decision.py tests/test_work_packets.py tests/test_decision_ledger.py
176 passed in 0.49s

ruff check tradingagents/policy/loss_board_decision.py tradingagents/orchestration/work_packets.py tests/test_loss_board_decision.py
All checks passed!

git diff --check
(no output; passed)
```
