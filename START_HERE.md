# Start Here

Open TradingAgents in Codex at this exact folder:

`/Users/corbinfloyd/Documents/TradingAgents`

This is the single canonical Git repository and runnable application root. The
old nested application, Windows transfer, separate public clone, and development
worktrees were consolidated or preserved as recoverable archives on 2026-08-10.

## Start with the task

```zsh
cd /Users/corbinfloyd/Documents/TradingAgents
git status --short --branch
```

Read `AGENTS.md` for working guidance. Use
`docs/consolidation/REPOSITORY_MAP.md` when a source map helps. For runtime,
operational, or safety-sensitive work, read the existing compact summary and
flags under `results/_context/`, then only the raw packets they identify.
Refresh compact context only under the conditions in `AGENTS.md`; startup does
not require a write or a CLI invocation. Use `CONTEXT_ROUTER.md` selectively for
historical operational context, not as a current status report.

## What is current

- Application code: `cli/` and `tradingagents/`
- Tests: `tests/`
- Mac automation: `scripts/mac/`
- Local runtime state and evidence: `results/`
- Durable documentation: `docs/`
- Historical and recovery material: `archive/`
- Python environment: `.venv/`
- Local credentials: `.env`

The launchd n8n runner uses this root and serves its health endpoint at
`http://127.0.0.1:8765/health`.

## Current evidence order

1. Active process and broker state
2. `results/policy/live_control.json`
3. `results/_context/latest-summary.json` and `latest-flags.json`
4. The newest raw packets linked by compact context
5. Historical docs and archived packets

This order keeps a new chat centered on what the system is actually running.
