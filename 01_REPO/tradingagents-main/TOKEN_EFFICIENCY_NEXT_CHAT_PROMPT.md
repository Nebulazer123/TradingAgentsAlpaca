# Prompt For A Future Token-Efficiency Optimizer Chat

Copy this into a new Codex chat after the repo's methodology/framework
implementation work is done, or when it is stable enough that efficiency changes
will not fight active feature work.

## What I Want You To Do

Optimize this TradingAgents/Alpaca repo for token efficiency and context
efficiency without lowering report quality, trading safety, methodology quality,
or evidence quality. Think of it as lossless compression for agent work: keep the
raw evidence and deep reasoning available, but make the default path compact,
indexed, and drilldown-based.

The repo path is:

`C:\Users\Corbin\Documents\Coding projects\TradingAgents-main`

## Current Situation

Another chat recently worked on repo methodology, frameworks, tests, and trading
logic. Before changing token-efficiency structures, first inspect the current
worktree and recent files so you do not optimize around stale assumptions.

There is already a starter compression layer:

- `AGENTS.md`
- `CONTEXT_ROUTER.md`
- `TOKEN_EFFICIENCY_AUDIT.md`
- `NEW_CHAT_TOKEN_EFFICIENCY_HANDOFF.md`
- `scripts/automation_context_snapshot.py`
- Generated artifacts under `results/_context/`

The generated context artifacts are intentionally lossy indexes. They point to
raw evidence packets. They are not replacements for raw packets when the task
needs proof.

## First Commands

Run these first:

```powershell
cd "C:\Users\Corbin\Documents\Coding projects\TradingAgents-main"
git status --short
python -m py_compile scripts\automation_context_snapshot.py
python scripts\automation_context_snapshot.py --write
Get-Content results\_context\recent-deltas.md
Get-Content results\_context\latest-flags.json
```

Then inspect:

```powershell
Get-Content AGENTS.md
Get-Content CONTEXT_ROUTER.md
Get-Content TOKEN_EFFICIENCY_AUDIT.md
Get-Content results\_context\automation-compaction-approval-plan.md
```

## How To Decide When To Optimize

Do token-efficiency work when one of these is true:

- The methodology/framework implementation is complete enough that core files
  are not changing every few minutes.
- The automation paths are producing valid packets again after methodology work.
- Tests around the new methodology are passing or at least the remaining failures
  are known and unrelated to context routing.
- There are repeated chats reading the same packets/docs again.
- Automation prompts, memories, or latest packets are growing faster than the
  useful new information they contain.

Wait or only measure if:

- The repo is mid-refactor and packet shapes are still changing.
- Trading safety gates are being actively rewritten.
- The next task requires deep methodology correctness, not operational context
  compression.
- The generated summaries disagree with raw packet truth.

## What To Measure

Use practical approximations. Exact tokenizer accounting is not required.

Measure:

- File sizes, line counts, and rough token weights for route docs.
- Active automation prompt sizes under `C:\cm\automations`.
- Active automation memory sizes under `C:\cm\automations`.
- Latest result packets under:
  - `results/hourly_supervisor/`
  - `results/paper_strategy_tournament/`
  - `results/overnight_plans/`
  - `results/premarket_briefs/`
  - `results/overnight_system_verification/`
- Common command outputs that may dump full JSON into chat.
- Any new methodology/framework docs that became routine context.

Current known large sinks before later methodology work:

- `results/overnight_plans/latest.json` was about 228 KB.
- `results/premarket_briefs/latest.json` was about 56-58 KB.
- `C:\cm\automations\hourly-market-supervisor\memory.md` was over 115 KB.
- `C:\cm\automations\paper-strategy-tournament-runner\memory.md` was over 54 KB.
- Active automation prompts collectively had about 5,871 rough tokens, with an
  estimated compact target near 1,800 rough tokens.

Re-measure these. Do not assume the numbers are still current.

## Active Automation Families To Review

Review every active automation, including any new ones:

- `hourly-market-supervisor`
- `paper-strategy-tournament-runner`
- `tradingagents-overnight-planning`
- `market-supervisor-15-min-before-open`
- `market-supervisor-30-min-after-open`
- `market-supervisor-30-min-before-close`
- `market-supervisor-15-min-after-close`
- `tradingagents-daily-market-report`
- `tradingagents-automation-wake-controller`
- `tradingagents-automation-sleep-controller`

For each automation, inspect:

- Prompt size and repeated context.
- Model.
- Reasoning effort.
- Schedule/frequency.
- Whether it reads summaries first or raw packets first.
- What output it posts in-thread.
- Whether it should run at all during weekends, holidays, after-hours, or while
  methodology work is unstable.
- Whether it can share a compact prompt template with sibling automations.

## What Good Looks Like

The best final state is:

- Future sessions start from:
  `AGENTS.md -> CONTEXT_ROUTER.md -> results/_context/latest-summary.json -> results/_context/latest-flags.json -> raw packet only when flagged`.
- Detailed evidence remains in raw packets and result files.
- Chat replies are short unless a human explicitly asks for the full analysis.
- Automation prompts reference compact repo-local docs instead of restating the
  same long instructions everywhere.
- The wake/sleep controllers reduce unnecessary hourly automation runs without
  reducing trading quality.
- Daily reports remain high quality and detailed where they matter, but the chat
  handoff can be concise with paths to evidence.
- Methodology/framework docs are classified as either routine context,
  route-specific context, or archival/deep-drilldown context.
- Old stale files are deleted only when you are confident they are generated,
  duplicated, superseded, or actively confusing. Otherwise, mark them archival
  instead of deleting them.

## Ideas To Consider

You are free to choose better ideas after inspecting the repo. Useful directions:

- Add a repo-native CLI command like `tradingagents alpaca context-summary`.
- Add `--summary-json` output to commands that currently dump full JSON.
- Add tests for `scripts/automation_context_snapshot.py`.
- Add a compact memory-tail reader for automation memory files.
- Write `results/_context/context-history.jsonl` with one compact row per run.
- Generate a "what changed since last run" summary for each automation family.
- Split route docs only if `CONTEXT_ROUTER.md` becomes too large.
- Compact active automation prompts by replacing repeated text with references
  to the repo read path and generated context artifacts.
- Keep paper tournament execution separate from live supervisor execution, but
  make their summaries interoperate.
- Keep market-window schedules separate if they encode different risk moments,
  but share prompt templates where possible.

## Questions To Ask Before Changing Anything Big

- Am I preserving raw evidence?
- Am I preserving report quality?
- Am I preserving trading safety?
- Is this changing behavior or only changing context routing?
- Could this make a future chat miss a blocker, submitted action, stale packet,
  candidate change, graph failure, or schema mismatch?
- Does this reduce repeated input tokens in normal runs?
- Does this still allow deep work when deep work is actually needed?
- Is this file stale/noisy enough to delete, or should it simply be marked
  archival/deep-drilldown?

## Deliverables I Want

Produce:

- A measured context audit with current numbers.
- Updated generated context artifacts under `results/_context/`.
- A list of the largest current repeated context sinks.
- A list of active automation model/reasoning/frequency recommendations.
- Any safe repo-local changes that improve summary-first workflows.
- A clear note on what should wait until after methodology/framework work.
- A concise final handoff with changed files, validation commands, and remaining
  token sinks.

## Tone And Priority

Be creative and high leverage, but do not be theatrical. This is not about making
the repo look tidy; it is about preserving best-in-class performance while
spending fewer unnecessary tokens.
