# Goal And Subagent Context Contract

This repo uses Codex goals, hooks, subagents, automations, and n8n as control
surfaces around the Python TradingAgents system. None of those surfaces may
submit orders, approve orders, promote sleeves, cancel orders, waive live gates,
or read secrets.

## Goal States

Use these repo-local state names when summarizing goal context in hook packets,
handoffs, and process reviews:

| State | Meaning |
| --- | --- |
| `goal_absent` | No explicit durable Codex goal is active. Use normal compact orientation. |
| `goal_active` | A durable goal exists and work should continue against it. |
| `goal_waiting_for_user` | Progress needs a user decision, credential, hook trust action, or external state change. |
| `goal_blocked` | The same blocker has repeated long enough that work cannot continue meaningfully without user/external action. |
| `goal_complete` | The objective is achieved, tests/evals ran, and no required work remains. |

## Goal Context Rules

When a goal exists:

1. Run `python scripts/automation_context_snapshot.py --write`.
2. Read `results/_context/latest-summary.json`, `latest-flags.json`, and
   `recent-deltas.md` before opening raw packets.
3. Open raw packets only when compact flags name a reason or exact path.
4. Keep native Codex goal updates human-visible. Hooks may write compact event
   packets, but hidden hooks must not create, complete, block, or rewrite goals.
5. Dispatch subagents only with a narrow task boundary and explicit files or
   result folders to inspect.

## Subagent Output Contract

Every subagent result should return only:

- task result
- exact files inspected
- exact files changed
- tests or commands run
- compact blocker list
- raw packets opened and why
- recommended next inspection point

Subagents should not paste full raw packets, full stdout logs, secrets, full
Deep Research reports, or entire automation memories into the main thread.

## Hook And Wrapper Proof Boundary

The hooked runner and n8n runner may refresh compact context and write compact
event packets. They do not bypass `alpaca check`, dry-run, unified live-submit
guard, risk envelope, stale-data checks, or promotion gates.

Low-risk wrapper proof should start with `context_snapshot` or daily/paper
observer jobs before any live-adjacent supervisor rollout. Hook trust remains a
manual Codex UI/CLI action whenever hook files change.
