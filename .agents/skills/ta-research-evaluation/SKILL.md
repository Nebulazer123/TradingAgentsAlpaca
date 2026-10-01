---
name: ta-research-evaluation
description: Qualify TradingAgents research inputs, compared model lanes, or prospective economic outcomes against the existing experiment contracts.
---

# Research and evaluation

Identify the acceptance claim and its source owner before choosing a lane.
Use deterministic readers first for extraction and validation; retrieval and
model judgment address the remaining measured need.
Research memory uses local redacted packets; the existing Zep status helper does
not enable a cloud backend. A new memory service needs its own explicit scope.

- For document input and benchmark work, read `docs/readiness/REAL_DOCUMENT_INPUTS.md`
  and the relevant registration/benchmark code in `tradingagents/research/`.
  Keep original custody, page/span identity, equal lane inputs, and gold labels
  outside the material visible to a compared lane.
- For economics, read
  `docs/superpowers/specs/2026-08-24-evidence-first-economic-evaluation-protocol.md`
  and `tradingagents/evals/economic_evaluation_admission.py`.
  Follow prospective phase order and point-in-time capture; forecasts and
  unverified ledger labels cannot substitute for observed outcomes.
- For model comparisons, inspect `tradingagents/research/model_routing.py`,
  provider compatibility, and telemetry. A route recommendation does not run a
  model. Paid execution needs authorized scope and a positive finite budget;
  local model loading also needs its applicable authority.

Use the relevant acceptance row in `docs/readiness/COMPLETION_CONTRACT.md` only
when continuing that program. Preserve replay of accepted registrations and
state the measured limits of the result. A reproducible null/negative result is
valid; missing evidence remains an open claim. Protected holdout release uses
its separate owner record described in `docs/harness/BOUNDARIES.md`.
