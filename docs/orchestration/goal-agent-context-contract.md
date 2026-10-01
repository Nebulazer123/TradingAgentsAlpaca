# Goals and task context

A native Codex Goal is a thread-scoped completion contract. Create it only when
requested. Its objective, current progress, historical evidence, and permanent
repository rules have separate owners. A goal confers no financial or external
authority. Hooks must not create, complete, block, or rewrite goals.

## State

Optional context labels remain available to existing hook consumers:

| Label | Meaning |
| --- | --- |
| `goal_absent` | No explicit Goal; carry out the current task. |
| `goal_active` | Continue toward the defined outcome using direct evidence. |
| `goal_waiting_for_user` | A dependent step needs a choice, access, or external change; continue independent work. |
| `goal_blocked` | Native tool requirements for repeated blocking have been met. |
| `goal_complete` | Objective checked; no required work remains. |

## Context and continuation

Source goals read relevant source and tests. Runtime/readiness goals use existing
compact summary/flags and the particular packets or controls the task needs.
Refresh the snapshot when those inputs change or the index is missing/stale;
ordinary goal lifecycle events do not require a write. Hook warnings help choose
context and never enforce broker, scheduler, or spending authority.

Keep a compact progress record for substantial work: objective, decisions,
completed changes, useful evidence, exact blocker, and next step. Record deltas
instead of a fresh global status recap after every turn. Readiness continuation
uses `docs/readiness/COMPLETION_CONTRACT.md` and its current status page.

Give a subagent one bounded question and clear ownership. Its result should
contain the finding, useful changed paths, relevant checks, and blockers.
Request exact inspected files or raw-packet details when needed to assess a
claim; no fixed checklist applies to every result. Keep private evidence and
large logs in their local owners, linking the material needed for integration.
