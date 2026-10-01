# TradingAgents

Work from `/Users/corbinfloyd/Documents/TradingAgents` or an intentional Git
worktree derived from it. Check the checkout and local changes, then use
`START_HERE.md` to choose context for the task.

## Own the task

Carry authorized local work through inspection, implementation, relevant checks,
and repair. Make reversible in-scope edits without another approval step.
Investigate project terminology and saved evidence yourself. Continue useful
independent work when a dependency is unavailable. Ask only for missing access,
a consequential unresolved choice, or separate protected-operation authority.

Prefer the smallest complete solution. Preserve unrelated changes, worktrees,
credentials, generated evidence, and recovery history. Use one writer per
worktree. Delegate bounded independent exploration, research, or review when it
helps; keep consequential decisions and integration with the primary agent.

## Find the owner

| Task | Start at |
| --- | --- |
| CLI behavior | `cli/main.py`, matching CLI tests |
| Agent workflow | `tradingagents/graph/`, `tradingagents/agents/` |
| Research, models, inputs | `tradingagents/research/`, `tradingagents/dataflows/` |
| Brokers, authority, risk | `tradingagents/brokers/`, `tradingagents/policy/`, `tradingagents/execution/` |
| Scheduling and operations | `tradingagents/orchestration/`, `scripts/mac/`, `config/` |
| Evaluation | `tradingagents/evals/`, matching tests |

Read only the relevant owners. Use `rg` and direct reads for exact evidence;
structural tools are optional. Runtime tasks start with existing
`results/_context/latest-summary.json` and `latest-flags.json`, then current
controls/processes and the raw packets needed by the task. Historical records
describe their recorded time. Source-only work does not require runtime history.

## Check the result

Use sufficient direct evidence: readback/diff for prose, focused behavior checks
for code, and affected integration or release gates for consequential changes.
Reuse valid checks on unchanged inputs. Diagnose failures and rerun affected
checks after repairs. A preview or test pass proves only what it exercised.
Keep durable output for long checks and immutable custody where it has recovery,
security, or experiment value. Ordinary edits need no new hash manifest.

## Authority and instruction placement

Protected financial and external actions require their current call-time policy
and separate task authority: orders, trading controls, schedule activation,
message sending, credentials, billed execution, protected evidence release, and
destructive cleanup. Agent instructions and analysis artifacts grant none.
Preserve the executable gates; see `docs/harness/BOUNDARIES.md` when changing one.

Keep root guidance stable. Put repeatable procedures in `.agents/skills/`,
subtree rules in nested guidance only when needed, current progress in status or
task contracts, and deterministic constraints in code/configuration.

Report the result, useful changed paths, relevant checks, and material blockers.
Mention existing state only when it changed, affected this result, explains a
blocker, or was requested. Keep updates specific and avoid stock closing text.
