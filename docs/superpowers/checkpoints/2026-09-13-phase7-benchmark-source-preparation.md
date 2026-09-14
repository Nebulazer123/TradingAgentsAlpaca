# Phase 7 benchmark source preparation — 2026-09-13

## Full-role adapter source checkpoint

The source runner now implements the actual retained-only full graph. This is
**source preparation, not real Task 7.1 qualification**. The earlier baseline
sections below are historical; they do not describe the latest adapter as absent.
Canonical integration requires the clean-source proof described below.

New owners are `tradingagents/research/qualification_full_graph.py` (supplemental
registration, all-case preflight, isolated graph execution and receipts) and
`tradingagents/research/qualification_graph_model.py` (strict observed callbacks,
structured roles and private response custody). The existing benchmark executor
and CLI require explicit `--execute-openrouter --execute-full-graph`, an explicit
supplemental registration, and a new isolated run root. Default scoring stays
model-free. Deterministic and FTS prerequisites run first; a graph whose registered
gain is unattainable is not invoked. No real execution was authorized or run.

The immutable supplemental registration binds all 1,400 exact sorted case IDs to
explicit stock/date context, the base registration, clean Git revision and lock.
No ticker/date is inferred from a question, and the existing v4 base registration
is not rewritten. Both graph variants bind identical model/pricing settings.
Every source/no-text projection receives privacy preflight before any model
client; each case binds its exact input, variant and isolated learning/decision
predecessors into the accepted checkpoint identity. Concurrency remains 1;
English, temperature 0, no SDK retries and required structured output are bound.
Ambient non-English settings reject rather than being silently changed.

The production analyst/researcher/manager/trader/risk/portfolio-manager topology
executes twelve role calls and emits three linked analysis-only packets. The
Portfolio Manager supplies `benchmark_answer` in its existing structured response;
there is no extra answer model. Callback role order, outcome uniqueness, actual
provider/model/revision/route, no fallback, tokens and derived cost are checked.
All callbacks retain private `0600` LangChain message representations, not claimed
original HTTP bodies, with exact file SHA-256 links in the case receipt. Returned
and parsed answers must match the observed response. Sensitive final response
fields reject before a successful case receipt. No old case is resumed/overwritten;
failed namespaces remain for inspection.

A real graph exposed a locked SQLite saver compatibility defect: metadata writes
contained `AIMessage`, which its separate JSON encoder could not serialize.
`tradingagents/graph/checkpointer.py` now converts message-bearing metadata to
complete standard message envelopes, rejects unsupported/noncanonical values,
and leaves typed checkpoint channel serialization unchanged. No dependency
upgrade, discarded write metadata or old-checkpoint rewrite was used. Authority
inventory has an exact local-SQLite classification for this `put` call; two
unchanged CLI queue classifications moved to 6651/6663. Guards were not weakened.

Verification on this source candidate:

- Final nine-module affected gate: **341 passed in 32.10s**, exit 0, with two
  existing AST invalid-escape warnings. Modules: research qualification/full graph,
  checkpoint message metadata/resume/CLI/runtime identity, graph packet handoffs,
  retained context and authority alignment. Canonical Python 3.13.14, feature
  `PYTHONPATH`, `TA_LIVE_SUBMIT=0`, and `-m 'not integration and not network'`.
  Receipt: canonical SDD `phase7-full-graph-source-gate-corrected-20260913.xml`.
- Its preceding run had 340 pass and one unclassified local-SQLite occurrence;
  adding the exact classification was the only intervening candidate change.
- Response custody RED: three intended failures (missing files/hash links and
  sensitive final response accepted); GREEN: three pass in 1.80s.
- Earlier real-SDK 503 regression proved three unwanted automatic attempts;
  all source/reviewer/full-graph factories now pass `max_retries=0` and
  `temperature=0`, and source/reviewer prompt contracts include those settings.
  Historical registrations/receipts remain immutable; newly executed lanes must
  register the new contract. A two-failure intermediate run contained only stale
  factory-argument expectations, since corrected without changing production.
- Scoped nine-path Ruff, five-source compileall, offline `uv lock --check`, and
  `git diff --check` passed. The lock hash remains
  `3467e3497c8bf436ef9a4f939ccf0d4460906c61268565d6e275b21cb41413d2`.

The 1,400-case CLI test preserves the full minimums and executes both 2,800-case
lane orchestrations using synthetic responses; its per-case graph executor alone
is stubbed. Separate tests execute both actual twelve-role graphs with production
client/HTTP mock transport, real SQLite and packet stores. Their source-revision
probe is mocked, so a separate exact-clean-Git proof is required before integration.
No synthetic result is presented as a real registered corpus or model evaluation.

Solo source/quality/security review covered context and source binding, no answer
key projection, all-case privacy, default-off execution, isolated destinations,
actual callback/parsed-response consistency, no hidden retry, packet authentication
and immutable checkpoint evidence. No independent reviewer or subagent was used.
Cost budgets currently govern lane selection, not authorization or a guaranteed
pre-call spending ceiling; real execution must remain held until the separate
model/spend controls and genuine corpus prerequisites are satisfied.

## Earlier combined baseline

This is an isolated source checkpoint, **not completed Task 7.1 or Phase 7
acceptance**. Reviewed benchmark source `d907483` is combined with accepted
canonical `1c502e8` in the existing benchmark worktree. Canonical integration
waits for the remaining full-graph source work and its affected proof.

The merged baseline retains registered deterministic SEC/XBRL extraction,
metadata/FTS5/BM25 before model construction, source-bound/no-text model pairs,
ambiguous-case distinct-model review, full-cohort cost comparisons, and strict
observed routing/usage metadata. All actual outbound case/source fields receive
the existing privacy policy before any client construction; no credentials or
answer keys are intentionally projected to adapters. Missing actual provider
metadata is unavailable, never synthesized from requested settings.

The conflict-free CLI merge preserves its one benchmark-changed and seventeen
canonical-changed definitions and all new imports exactly, with no duplicate
definitions (AST comparison against common base `53a286a`). Exact-source
inventory locations for two unchanged local queue calls move from 6558/6570 to
6624/6636 without changing their nontrading classifications.

Merged baseline proof: **90 passed in 33.31s**, two existing AST invalid-escape
warnings, exit 0. The three-module gate covered
`tests/test_research_qualification_benchmark.py`,
`tests/test_authority_role_alignment.py`, and `tests/test_checkpoint_cli.py`,
excluding integration/network markers. Five-path Ruff, three-source compileall,
offline lock and both diff checks passed. The one verifier used canonical
Python 3.13.14, feature `PYTHONPATH`, and `TA_LIVE_SUBMIT=0`; no real model or
provider invocation occurred. Separate solo review reused the previous reviewed
source and inspected the merged CLI and compatible-provider metadata changes.

Completed JUnit receipt (suite time 33.183s, distinct from pytest's elapsed
summary) is under canonical SDD as
`phase7-benchmark-merged-source-gate-20260913.xml`, SHA-256
`546075ea77c141e3473b6abbfa11243f16e436cce2cf882da429036e679ed3f1`.
At `2026-09-14T01:24:52.488464Z`, all four frozen-owner and ten PAUSED automation
hashes still matched the preservation baseline. No real ledger, control,
schedule, packet family or external account was changed.

Remaining source work is the actual full-role graph adapter: retained-only
analyst inputs (ordinary prefetched analysts still fetch externally), explicit
registered graph-case context, isolated packet/checkpoint stores, exact variant
identity, and observed per-call telemetry with no silent fallback. A single
question-answer model call is not a full graph. The 500/300/400/200 real corpus
and its admission, source/model qualification, and all later program gates
remain unfinished. Existing external/model/holdout/submission boundaries hold.

## Retained-only analyst source slice

After preserving the merged baseline at `677412c`, the next bounded source
slice adds `tradingagents/agents/analysts/retained_analyst.py` and an explicit
`retained_analyst_context` mode in `tradingagents/graph/setup.py`, tested in
`tests/test_graph_retained_context.py`. Default graph behavior is unchanged.
Retained mode gives the four existing analyst roles exact caller-supplied text,
never invokes the ordinary prefetch factories, and removes their tool nodes and
tool loops. Empty text is deliberately absent source, not a fetch request.
Nontext context, tool-node registration, implicit relative destinations, and a
ledger outside the explicit evidence root reject before node construction.
Analyst responses with tools, invalid tool calls or no text reject; they cannot
silently become successful research reports.

The full researcher, research manager, trader, risk, portfolio-manager and three
packet boundaries remain the actual production topology. Four synthetic runs
(text/no-text, sequential/concurrent) execute all twelve model-role calls and
verify all three real linked packets in temporary destinations. Concurrency 2
here is a hermetic regression test, not Task 5.5's real concurrency qualification
or a runtime settings change. The fake deliberately exercises ordinary
free-text model support; this does not prove the future benchmark's strict
no-fallback telemetry contract.

RED: ten intended failures on the absent input mode/factory, 1.31s. The first
postimplementation attempt passed six tests; four topology tests exposed an
invalid arbitrary run ID in the new fixture. The fixture now uses the production
Propagator's SHA-bound run-ID path; the production packet guard was not changed.
Final five-module affected proof: **93 passed in 1.48s**, exit 0, covering the
new mode, packet handoffs, graph analyst concurrency, analyst execution plans,
and checkpoint runtime identity. Scoped Ruff, compileall and diff checks pass.
Receipts are `phase7-retained-context-red-20260913.xml`,
`phase7-retained-context-green-20260913.xml` (the fixture-error attempt, not a
successful GREEN), and `phase7-retained-context-affected-20260913.xml` in canonical
SDD. A subsequent test comment correction is nonbehavioral; no gate is replayed
solely for that wording.

This slice still is **not the full benchmark adapter**. It does not admit data,
construct clients, bind benchmark case/variant identity, implement strict
per-call telemetry or grade the registered question from the graph result.
The adapter must supply legitimate registered instrument/date context (the
current v4 case schema lacks it), bind exact retained/no-text inputs to the
accepted checkpoint identity, isolate stores, and account for every real role
call without hidden structured-output retries. No real model call is authorized
by adding this source mode. Canonical remains at accepted `1c502e8` until the
remaining Phase 7 source work is complete and verified.
