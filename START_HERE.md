# Start Here

Open TradingAgents in Codex at this exact folder:

`/Users/corbinfloyd/Documents/TradingAgents`

This is the single canonical Git repository and runnable application root. The
old nested application, Windows transfer, separate public clone, and development
worktrees were consolidated or preserved as recoverable archives on 2026-08-10.

## First minute

```zsh
cd /Users/corbinfloyd/Documents/TradingAgents
git status --short --branch
.venv/bin/python scripts/automation_context_snapshot.py --write
sed -n '1,220p' results/_context/latest-summary.json
sed -n '1,220p' results/_context/latest-flags.json
.venv/bin/python -m cli.main --help
```

Read `AGENTS.md` for working guidance, `CONTEXT_ROUTER.md` for operational
context, and `docs/consolidation/REPOSITORY_MAP.md` for the durable source map.

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
