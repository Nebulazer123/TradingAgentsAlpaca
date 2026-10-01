# Start with the task

The canonical application and Git root is
`/Users/corbinfloyd/Documents/TradingAgents`. Intentional linked worktrees have
their own checkout state. Begin with `git status --short --branch` and `AGENTS.md`.
The canonical Python environment is `.venv/`; use it from linked worktrees too.

| Need | Read |
| --- | --- |
| Implement or explain source | Relevant subsystem and tests; [repository map](docs/consolidation/REPOSITORY_MAP.md) if useful |
| Diagnose runtime or authority | Existing compact summary/flags in `results/_context/`, then the specific current controls and packets |
| Continue readiness work | [Current progress](docs/readiness/CURRENT_STATUS.md) and [completion contract](docs/readiness/COMPLETION_CONTRACT.md) |
| Qualify research or economic evidence | `.agents/skills/ta-research-evaluation/SKILL.md` |
| Investigate operations | `.agents/skills/ta-runtime-diagnosis/SKILL.md` |
| Freeze a release candidate or recover history | `.agents/skills/ta-source-release/SKILL.md` |
| Find an older decision | [History router](CONTEXT_ROUTER.md) |

Application code lives in `cli/` and `tradingagents/`, tests in `tests/`, durable
docs in `docs/`, generated evidence in `results/`, and recovery material in
`archive/`. Local credentials stay in the ignored `.env`.

Refresh compact context with
`.venv/bin/python scripts/automation_context_snapshot.py --write` when its
inputs changed or the index is missing/stale for a runtime task. Startup and
source edits alone need no refresh. An index timestamp does not refresh the
underlying evidence.
