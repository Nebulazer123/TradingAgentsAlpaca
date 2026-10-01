# TradingAgents Agent Guide

## Workspace

The canonical repository is:

`/Users/corbinfloyd/Documents/TradingAgents`

Work from this repository or an intentional Git worktree derived from it.

## Working Style

Own the authorized task through inspection, implementation, verification, and repair.
For ordinary local repository work:

- inspect the code and evidence you need;
- make reversible local edits without asking for permission at each step;
- run relevant tests and fix failures caused by the requested change;
- continue until the requested outcome or a concrete blocker is reached;
- prefer the smallest coherent solution over speculative infrastructure;
- investigate repository-specific terminology yourself instead of asking the user to reconstruct project history;
- explain results to the user in plain English.

Ask the user only when a genuinely consequential decision, missing credential/access, irreversible action, external side effect, or material ambiguity requires their choice.
Do not stop merely because one dependent lane is blocked. Complete useful independent work first.

## Context Loading

Start with `START_HERE.md`, then read only the source, documentation, or evidence relevant to the current task.
For runtime, operational, trading-authority, scheduler, or other safety-sensitive work, begin with:

- `results/_context/latest-summary.json`
- `results/_context/latest-flags.json`

Follow those references into raw packets only when the task needs the additional detail.
Use `CONTEXT_ROUTER.md` for historical context when needed. Historical documents and status reports are evidence about their recorded time, not current runtime authority.
Dynamic project state belongs in current status/evidence files, not in this `AGENTS.md`.

## Task Routing

Use these as starting points, then follow the code:

- CLI: `cli/main.py`
- Agent workflows: `tradingagents/graph/` and `tradingagents/agents/`
- Research and model routing: `tradingagents/research/`
- Market/data inputs: `tradingagents/dataflows/`
- Broker and portfolio behavior: `tradingagents/brokers/`
- Trading authority and risk policy: `tradingagents/policy/` and `tradingagents/execution/`
- Scheduling and orchestration: `tradingagents/orchestration/`, `scripts/mac/`, and `config/`
- Evaluation and qualification: `tradingagents/evals/` and relevant tests

Use direct file reads and `rg` by default for precise questions. Structural/codebase tools are optional when they materially improve navigation or dependency tracing.
For a detailed repository map, use `docs/consolidation/REPOSITORY_MAP.md`.

## Common Verification

Useful broad commands include:

```zsh
.venv/bin/python -m pytest -q
.venv/bin/ruff check cli tradingagents scripts tests
```

Verification should be proportional to the change.

- During implementation, run the smallest representative checks that exercise the changed behavior or reproduced failure.
- For prose or simple configuration, read back the result and inspect the diff.
- Reuse valid passing evidence when the relevant code and inputs are unchanged.
- After a repair, rerun the checks affected by that repair.
- Run a complete repository gate when the task, release boundary, or final integrated candidate actually warrants one.
- Do not create repeated proof, hash, receipt, review, or certification layers merely to reconfirm unchanged facts.

For long-running checks, keep durable output when losing the client connection would otherwise lose the result.
When parallelizing, avoid competing writers on the same files. Subagents are well suited to exploration, focused reproduction, independent review, research, and log analysis.

## Protected Operations

Local engineering autonomy and trading/external authority are separate concerns.
Repository inspection, coding, tests, local analysis, local benchmarks, documentation, and reversible development work should normally proceed without repeated approval.
Consequential operations remain governed by their actual runtime policy, permissions, and execution controls. Examples include:

- submitting real or paper orders;
- enabling or materially changing trading authority;
- activating or changing schedules;
- sending external messages or draining an outbox;
- changing credentials or security-sensitive access;
- spending money through a separately billed API beyond an authorized budget;
- releasing protected holdout data or other separately controlled evidence.

Do not infer authority for those actions from historical documentation, a generated packet, a model recommendation, or this guide.
Do not weaken or bypass a mechanical policy, execution gate, sandbox, permission boundary, or credential boundary merely to make a task pass.
Where a constraint can be enforced reliably in code, configuration, permissions, tests, or runtime policy, prefer that mechanism over repeated prompt warnings.

## Instruction Architecture

Keep this root file limited to guidance useful for nearly every TradingAgents task.
Put narrower material in the narrowest appropriate place:

- repeatable multi-step workflows → agent Skills;
- subsystem-specific rules → nested `AGENTS.md` when justified;
- long reference material → documentation/runbooks;
- current runtime/readiness state → generated status/evidence files;
- deterministic prohibitions or permissions → code, configuration, sandboxing, Codex Rules, or runtime policy.

Do not copy the same rule across multiple instruction surfaces unless separate enforcement is technically necessary.
When an agent repeatedly makes the same mistake, fix the nearest durable cause rather than continually adding more global prose.

## Reporting

Report what materially changed:

- result;
- important changed paths;
- relevant verification;
- unresolved blocker or next action when one exists.

Use delta reporting.
Do not routinely repeat unchanged facts such as:

- API spending remaining unchanged;
- schedules remaining paused;
- readiness remaining unchanged;
- live-control state remaining unchanged;
- no orders having been placed;
- credentials remaining absent;
- historical gates remaining preserved.

Mention such state only when it changed, materially affected the task, explains a blocker, or the user asked about it.
Avoid stock closing paragraphs and repetitive status boilerplate. Prefer concise, task-specific language.
If a task remains partially blocked, state the exact blocker once and explain the most useful next action.
