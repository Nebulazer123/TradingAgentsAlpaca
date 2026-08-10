# TradingAgents Codex Start Here

This repo is a recurring TradingAgents/Alpaca automation workspace. Future Codex
sessions should avoid rediscovering the whole repo.

## Fast Orientation

1. Read `CONTEXT_ROUTER.md` first.
2. Run `python scripts/automation_context_snapshot.py --write` to refresh
   `results/_context/`, then read `results/_context/latest-summary.json` and
   `results/_context/latest-flags.json`.
3. Inspect only the source files named by the relevant automation route.
4. Prefer the repo executable on Windows:
   `.\.venv\Scripts\tradingagents.exe`.

## Hook And Control-Plane POC

- Repo-local Codex hooks live under `.codex/hooks/`. They refresh compact
  context and write small redacted event packets only; they must not trade,
  approve, promote, cancel, or read secrets.
- Hook event packets go under `results/_context/hook-events/`. The latest hook
  event is summarized in compact context with event, goal, and subagent metadata
  only; do not paste full hook payloads into chat unless debugging that hook.
- Goal/subagent state and output rules live in
  `docs/orchestration/goal-agent-context-contract.md`; hooks write context
  packets only and must not create, complete, block, or rewrite goals.
- n8n must use the allowlisted local runner only:
  `python -m tradingagents.orchestration.n8n_runner --run-job context_snapshot`.
  Do not give n8n arbitrary shell commands or direct Alpaca credentials.
- Supervisor/control-plane error self-heal uses compact handoff packets:
  `python -m cli.main research self-heal-handoff --json-output`. This writes
  `results/self_heal/latest.json` and `latest-prompt.txt` for a fresh Codex
  repair chat. Hooks and n8n may create/read this handoff, but they must not
  trade, send email, mutate goals, or edit repo files by themselves.

## Context Budget Rules

- Do not read whole `results/` packets unless investigating that exact run.
- Start from `latest.json` and the snapshot helper, then open timestamped packets
  only when the summary shows a blocker, submission, changed candidate, or stale
  validation.
- For goals, subagents, hooks, n8n, and automations, the default route is
  `results/_context/` first and raw packets only when `latest-flags.json` says
  why.
- For market-readiness work, the operational tracker is
  `docs/superpowers/plans/2026-06-08-market-readiness-execution-board.md`.
  Before editing, name the board ID being worked. After completing a slice,
  update that checkbox with the date, packet/test evidence, and exact
  verification command. Do not create duplicate trackers, and do not repeat a
  completed item unless fresh evidence proves a regression.
- Before any market-readiness final close-out, complete board item `P0-13`:
  reconcile `docs/superpowers/plans/2026-06-08-finish-overnight-research-control-plane.md`,
  `reports/market_readiness/market-readiness-goal-assessment-20260608.md`,
  and `reports/market_readiness/market-readiness-goal-assessment-20260608.json`
  into the board. No P0/P1 requirement from those files may remain only in a
  superseded plan or assessment.
- Do not read `uv.lock`, `.venv/`, images, caches, or `__pycache__/` during repo
  orientation.
- Keep chat updates short. Put durable detail in files or result packets.
- For order-affecting paths, keep the known gate: `alpaca check` first, then
  dry-run, then submit only if clean and actionable.

## Core Files

- CLI entrypoints: `cli/main.py`
- Live/hourly/daily/premarket logic: `tradingagents/brokers/alpaca_supervisor.py`
- Paper tournament logic: `tradingagents/brokers/paper_tournament.py`
- Broker execution/safety: `tradingagents/brokers/alpaca.py`
- Main automation router: `CONTEXT_ROUTER.md`

## Reporting Contract

Final chat reports should usually include only: what ran or changed, packet paths,
status, blockers/submissions, validation command, and next inspection point. Save
long evidence in repo files or existing result folders.
