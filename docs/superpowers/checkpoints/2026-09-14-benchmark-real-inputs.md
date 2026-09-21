# Benchmark real-input corrections — 2026-09-14

## Scope and result

Two source defects found while preparing real retained documents are corrected
in the existing isolated `oai/tradingagents-research-benchmark-20260907` worktree.
It was clean and fast-forwarded from 3901c2c to accepted baseline 5cecf297 before
this slice. No new worktree, subagent, dependency, source fetch or model was used.

1. The official JSON loader deliberately preserves fractions as `Decimal`, but
   the benchmark scalar adapter rejected that exact type. It now reuses the
   existing bounded PIT canonical normalization for decimals, without a binary
   float conversion. Fractions, negative values, exponent notation and negative
   zero work; booleans, null, containers, duplicate keys, nonfinite numbers and
   resource-exceeding exponents still reject.
2. The FTS corpus previously indexed one copy of a page per question, then
   required retrieval to return the current case ID. Multiple legitimate
   questions on one page therefore competed with duplicate copies of their own
   evidence. The corpus now indexes each exact original-hash/byte-span unit once
   and applies the current question's selector only when that source unit is
   retrieved. Inconsistent bytes for one unit reject. Different spans and
   originals remain distinct; aliases cannot multiply pages. Stable unit IDs,
   not arbitrary question IDs, resolve equal-score ordering.

The original readiness plan was extended in place with exact owners, interfaces,
acceptance checks and the remaining media gap. Historical registrations and
receipts, case minimums, severity thresholds, no-text twins, source matching,
privacy and authority fields remain unchanged. Expected answers are not read
by the corrected scalar/retrieval functions.

## Evidence

- RED on original source: **7 failed, 9 passed, 0.44s**, terminal session 46435
  exit 1. Five finite-decimal failures, one shared-page retrieval failure and one
  missing inconsistent-byte rejection.
- GREEN after correction: **16 passed, 0.13s**, terminal exit 0.
- Final affected group: **72 passed, 42.26s**, terminal session 90322 exit 0.
  Modules: `test_research_qualification_source_inputs.py`,
  `test_research_qualification_benchmark.py`, `test_research_full_graph.py`.
  The new 18-case input module includes distinct-original and alias controls.
  A registered 1,400-case integration fixture preserves all original minimums
  while adding a second, different question to one original page.
- An earlier affected command used an incorrect full-graph test filename and
  exited 4 before running any tests. Its empty XML is retained separately;
  the corrected run used the discovered `tests/test_research_full_graph.py`.
  No broad source gate was started or restarted.
- Scoped Ruff and `git diff --check` pass. Solo source/spec/security review
  checked scalar normalization boundaries, exact shared-source identity,
  per-question extraction, no gold projection, deduplicated retrieval and all
  unchanged submission/qualification gates. No independent reviewer is claimed.

The actual retained-data probe also passed with network connections blocked:
`results/research_benchmark_preparation/20260914-retained-json-probe/receipt.json`.
It reopens the unchanged AAPL SEC company-facts response, hash
`73a86c6aedc31f77cac2ea4df5f80f0b3bd7e6eb58bb4e01444fbedf3afb9c43`, captured
at `2026-09-14T05:35:19.173397+00:00`. Two exact JSON paths in accession
`0000320193-26-000020` select basic and diluted EPS scalars. Both reject on the
original benchmark source and match an independent exact-decimal read on the
correction. FTS answers both questions from that same original response.
This is source-format/lookup proof, not historical custody, financial advice,
economic admission, a registered benchmark or model qualification.

Corrected module SHA:
`d44a65573e2975de515120e568a1806028178f31e9912f33703b991836f5309a`.
RED XML SHA:
`c826ab2d3680f6b5e70b0198fe9a83a95dce396725304a5e44742b162a9eec3f`.
GREEN XML SHA:
`09a3b5f5ccd142d65b8be73e70c4367583f2db4df74486f243977b75a232ba97`.
Final affected XML SHA:
`477627e73248426b2d87749cce330faff621da7e7b3f6baefb3b8f3615b5e65f`.
All XML receipts remain beside canonical SDD `progress.md`. The retained-data
probe is terminal session 63723 exit 0; do not replay its exclusive destination.

## Remaining boundaries

This does **not** resolve the separate direct HTML/PDF/image input gap. All 81
retained HTML filings still need an authenticated raw-media/derivative route,
legitimate page units and independently checked labels before real qualification.
The 500/300/400/200 registered cohort and permitted deterministic/FTS outcomes
remain required before any model lane. A few scalar fixes or synthetic media
labels do not satisfy that acceptance.

The new source is isolated, not integrated or covered by the concurrent full
wrapper gate on 76199c1. Preserve that gate and its old-worktree fingerprint until
terminal; then complete the already-authorized exact historical retirement and
integrate tested repairs without overwriting newer canonical documentation.
Retain this research branch through its remaining real-media work and affected
phase gate. The complete source gate belongs at the corrected source boundary,
not after every ordinary edit or on the unchanged old revision.

The real ledger, promotion state, frozen control, ten PAUSED automation hashes,
24 original Alpaca bodies and original Phase 5 ZIP reverified unchanged before
and after the retained-data probe. No trading, cancellation, holdout release,
schedule activation, outbox delivery, model call or external publication occurred.
The full readiness goal remains active and incomplete.
