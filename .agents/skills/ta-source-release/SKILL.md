---
name: ta-source-release
description: Freeze and verify a TradingAgents release candidate, or recover historical source and evidence while preserving checkout ownership and custody.
---

# Source qualification and recovery

Establish the exact checkout, branch, local changes, and intended candidate.
Inspect `git worktree list --porcelain` before worktree lifecycle changes.
Keep unrelated work, immutable evidence, and recovery archives in their existing
owners. Read `docs/consolidation/CONSOLIDATION_REPORT.md` when lineage is unclear;
use `CONTEXT_ROUTER.md` to find older decisions.

During implementation run affected checks. For an integrated release candidate,
use the existing `scripts/run_source_gate.py` interface and one complete gate:
`.venv/bin/python -m pytest -q` plus the configured static checks. Long runs need
durable logs and exit status independent of the client connection. Keep failed
results; rerun changed inputs and repairs instead of obsolete candidates.

For readiness qualification, read `docs/readiness/COMPLETION_CONTRACT.md` and
the corresponding plan section. Source qualification, deployment, and real
market-session acceptance are distinct claims. Before a protected operation,
verify the current authority through `docs/harness/BOUNDARIES.md`.

Recovery/removal needs exact-target authorization and a recoverable copy of
source, dirt, branch history, and needed ignored material. Inspect a retained
archive before trusting it. Keep handoffs until their unique facts have canonical
destinations. Report the recovered change and evidence relevant to the task.
