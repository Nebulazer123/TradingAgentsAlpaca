# New Chat Handoff: TradingAgents Token Efficiency

Use this file to start a fresh Codex chat in this repo without carrying this
thread's context.

## One-Sentence Goal

Finish a lossless-style context compression system for this TradingAgents/Alpaca
automation repo: preserve full evidence and report quality, but make future
sessions start from compact generated indexes and drill down only when flags say
raw packets matter.

## First Commands In A New Chat

```powershell
cd "C:\Users\Corbin\Documents\Coding projects\TradingAgents-main"
python scripts\automation_context_snapshot.py --write
Get-Content results\_context\recent-deltas.md
Get-Content results\_context\latest-flags.json
```

Then read, in order:

1. `AGENTS.md`
2. `CONTEXT_ROUTER.md`
3. `results/_context/latest-summary.json`
4. `results/_context/automation-index.json`
5. Raw packets only if `latest-flags.json` says so.

## What The New Chat Should Ask Itself

- Which automation path am I working on: hourly, paper tournament, overnight,
  market-window, daily report, premarket brief, or wake/sleep controller?
- Is this a full-context change or a delta-only task?
- Did `latest-flags.json` require opening a full packet?
- Are there blockers, submitted actions, issues, stale data, graph failures,
  changed candidates, changed tournament leader, schema mismatch, or unexplained
  P/L/action changes?
- Which exact file should be opened next?
- Can the answer be a short chat summary plus a saved artifact instead of a long
  chat report?
- Is this changing trading behavior, or only context/routing/reporting?

## Current Compression Artifacts

- `scripts/automation_context_snapshot.py`: writes the generated context bundle.
- `results/_context/latest-summary.json`: compact current packet view.
- `results/_context/latest-flags.json`: raw-packet drilldown triggers.
- `results/_context/recent-deltas.md`: watched changes between recent packets.
- `results/_context/automation-index.json`: automation model, reasoning,
  frequency, prompt size, memory size, and recommendations.
- `results/_context/context-manifest.json`: measured context load.
- `results/_context/automation-compaction-approval-plan.md`: proposed prompt,
  model, frequency, and consolidation changes. Approval needed before applying.

## Active Automation Families

- Hourly market supervisor.
- Paper strategy tournament runner.
- Overnight planner.
- Four market-window supervisors.
- Daily market report.
- Wake/sleep automation controllers that pause/wake token-heavy jobs by market
  day.

## Do Not Waste Tokens On These By Default

- Whole `results/` trees.
- Full overnight or premarket JSON unless flagged.
- Entire automation memory files.
- `uv.lock`, `.venv/`, images, caches, `__pycache__/`, or old one-off evidence
  packets unless the task is specifically about them.
- Future methodology docs unless the task is methodology work.

## Approval Boundary

Safe to do without extra approval:

- Refresh `results/_context/`.
- Improve compact docs or generated summaries.
- Add tests for context-summary behavior.
- Make chat reporting shorter while preserving saved evidence.

Needs approval:

- Active `C:\cm\automations\...\automation.toml` prompt rewrites.
- Schedule/frequency reductions.
- Model downgrades or reasoning-effort reductions.
- Packet schema compaction.
- Deleting old evidence or methodology files.

## End State

A best-in-class repo workflow where future Codex sessions can answer:

- What changed?
- What matters?
- What file should I open next?
- Can I stay in summary mode, or do I need full evidence?

without rereading raw packets or rebuilding the repo mental model every time.
