# Consolidation Verification Results

Date: 2026-08-10

## Repository and application

- Canonical root: `/Users/corbinfloyd/Documents/TradingAgents`
- Active worktrees: one, at the canonical root on `master`
- Preserved branches: `master`, `fable`, and `codex/autonomous-trading-firm`
- Python import resolves `tradingagents` from the canonical root.
- `.venv/bin/python -m cli.main --help` and the Alpaca help surface load.
- `git fsck --full` completed successfully; it reported recoverable dangling
  objects from prior history and no object corruption.

## Tests and static analysis

- Focused context, automation-health, n8n-policy, n8n-evaluation, and isolation
  slice: `69 passed in 1.41s`.
- Full suite: `1108 passed, 1 skipped, 75 subtests passed in 11.20s`.
- The skipped test is the expected live DeepSeek API test because its API key is
  absent or a placeholder.
- The nine warnings cover intentionally unknown future-model test values and one
  LangChain parameter-forwarding warning.
- Ruff across `cli`, `tradingagents`, `scripts`, and `tests`: all checks passed.
- `git diff --check`: clean.

## Preserved state

- `.env` SHA-256 before and after:
  `33b04093e30ecf68f2cc25723b073d45414e6c7bdbf853ae7ab2c8e60473a22f`.
- `.env` mode after consolidation: `0600`.
- `results/policy/live_control.json` SHA-256 before and after:
  `a22bce0bcad3880f31d6a7c51fa9def17fb33c9f951c3810b1ece53737b225d6`.
- Live control remains `frozen=true`.
- Ten TradingAgents Codex automation definitions remain `PAUSED`; their TOML
  structures match the pre-migration copies after exact root substitution.

## Runtime

- n8n runner PID at verification: `72540`.
- Runner current working directory:
  `/Users/corbinfloyd/Documents/TradingAgents`.
- Runner executable path uses the root `.venv/bin/python`.
- `http://127.0.0.1:8765/health` returned
  `{"status":"ok","service":"tradingagents-n8n-runner"}`.
- Active repository and external configuration scans found zero references to
  the former nested runtime path. The consolidation plan retains that string as
  historical documentation.

## Recovery archives

- SHA-256 checks passed for the autonomous-firm archive, fable archive, public
  clone archive, and public Git bundle.
- `git bundle verify` confirmed three advertised refs and complete history for
  the former public clone.
- Pre-move and post-move file and hash manifests remain under
  `archive/consolidation-manifests/2026-08-10/`.

## Directory audit

- Spotlight and filesystem review identify the canonical repository as the only
  runnable TradingAgents project under Documents.
- TradingAgents-named Eportfolio files are portfolio assets and reference
  material, so they retain their project-specific locations.
- Eight obsolete Codex task shells contained only empty `work` and `outputs`
  directories. Exact type, realpath, symlink, and contents checks preceded their
  removal. The exact list is in
  `archive/consolidation-manifests/2026-08-10/obsolete-task-directories.txt`.

## Agent guide language check

The root `AGENTS.md` contains affirmative operating guidance and returned zero
matches for the requested prohibitive-language scan.
