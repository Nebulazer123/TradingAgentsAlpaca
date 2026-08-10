# Repository Consolidation Report

Date: 2026-08-10

## Outcome

TradingAgents now has one canonical working root:

`/Users/corbinfloyd/Documents/TradingAgents`

The runnable Python application was flattened from the former nested directory
into this root. Git history, active source, tests, local environment, credentials,
generated evidence, documentation, and archives now have a single coherent home.

## Preserved material

- The pre-consolidation working tree was checkpointed in Git.
- The autonomous-firm and fable worktrees were archived completely before their
  registered worktrees were retired; their branches remain in Git.
- The standalone TradingAgentsAlpaca-public clone was preserved as a full tar
  archive and verified Git bundle, then moved to the macOS Trash as a recoverable
  pre-consolidation copy.
- The Windows transfer was reorganized under a dated archive with its original
  README, setup files, automation snapshots, validation material, and MiroFish
  payload.
- The autonomy PDF and DOCX were retained under `docs/history/` with matching
  hashes.
- Pre-move and post-move inventories, SHA-256 manifests, Git evidence, runtime
  evidence, and external configuration backups were recorded under
  `archive/consolidation-manifests/2026-08-10/`.

## Active path migration

Active repository files, ten paused Codex automation definitions and memories,
the launchd property list, and the n8n runner wrapper now point to the canonical
root. Automation structures and paused statuses were preserved. The local n8n
runner was restarted from the canonical root and passed its health check.

## Workspace organization

- `cli/` and `tradingagents/`: active application
- `tests/`: verification
- `scripts/mac/`: Mac operations
- `config/`: configuration and examples
- `results/`: runtime evidence
- `docs/`: durable documentation and history
- `archive/`: transferred and recovery material
- `START_HERE.md` and `AGENTS.md`: new-chat entrypoint and agent guidance

The exhaustive review ledger classifies every repository file and records every
tracked authored text file read during the consolidation audit. Binary,
environment, cache, runtime, and archive content was inventoried and hashed by
category.

## Recovery

Archive verification commands, checksums, and restore mappings live in
`archive/inactive-checkouts/README.md` and `SHA256SUMS.txt`. The public Git bundle
retains all advertised refs. The macOS Trash copy provides an additional
recoverable duplicate of the former public-clone directory.

## Verification

Final command results are recorded in `docs/consolidation/VERIFICATION_RESULTS.md`.
