# TradingAgents and MiroFish Mac Transfer

This package is a Windows-to-Mac transfer snapshot captured on 2026-07-11. It contains the current TradingAgents working tree, MiroFish source, generated evidence, automation definitions, and today's agent work.

## Read first

1. Read `02_CONTEXT_TODAY_2026-07-11/TODAY_HANDOFF.md`.
2. Read `04_SETUP/DEPENDENCIES_AND_SETUP.md`.
3. Inspect `01_REPO/tradingagents-main/results/_context/latest-summary.json`, `latest-flags.json`, and `recent-deltas.md`.
4. Read `03_AUTOMATIONS/AUTOMATION_CATALOG.md` before re-enabling anything.

## Safety

Live credentials and `.env` files were intentionally excluded. Do not run live or paper trading commands until credentials, account mode, and risk controls are manually reviewed on Mac. The Windows Codex automations and Job Profile OS task were paused before this package was built.

## Repository roots

- `01_REPO/tradingagents-main`: TradingAgents source, tests, docs, configs, n8n files, reports, and results.
- `01_REPO/mirofish-main`: MiroFish source, backend, frontend, docs, deliverables, locales, and static assets.
- `02_CONTEXT_TODAY_2026-07-11`: Redacted agent rollouts and a compact index of today's work.
- `03_AUTOMATIONS`: Automation snapshots, purposes, schedules, dependencies, and pause receipt.
- `04_SETUP`: Dependency and Mac setup instructions.
- `05_VALIDATION`: Provenance, exclusions, manifests, hashes, and transfer checks.

## Recreate a local Git repository

Git metadata was excluded from the active transfer unless separately documented as safe. Use the recorded source state and initialize a new local repository after reviewing the files:

```bash
cd 01_REPO/tradingagents-main
git init
git add .
git commit -m "Import Windows TradingAgents transfer snapshot"
```

Do not add credentials or generated dependency folders to the new repository.
