# Goal And Agent Token Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a hook-driven control layer that keeps Codex goals, subagents, and TradingAgents automations token-efficient by default while preserving safety and evidence quality.

**Architecture:** Use native Codex lifecycle hooks only for context hygiene, compact summaries, and run bookkeeping. Keep trading authority, broker checks, and live-submit gates inside the Python repo. Treat "goal hooks" as a repo-local contract because Codex currently documents lifecycle hooks but not a dedicated `GoalStart` or `GoalStop` event.

**Tech Stack:** Codex `hooks.json`, Python 3, PowerShell wrappers, existing `scripts/automation_context_snapshot.py`, existing `results/_context/` compact context artifacts, focused pytest slices.

---

## Current Findings

- `C:\cm\config.toml` already has `[features].hooks = true`, `[features].goals = true`, `[features].multi_agent = true`, and `[features].memories = true`.
- `C:\cm\config.toml` already has a `notify = [...]` turn-ended integration for Computer Use. Do not replace it. If notification chaining is needed later, wrap it carefully after a separate test.
- Official Codex lifecycle hook events currently include `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PreCompact`, `PostCompact`, `SubagentStart`, `SubagentStop`, and `Stop`.
- Matching hooks from multiple files all run. More than one matching command hook can run at the same time. Hook scripts must be idempotent and fast.
- Non-managed command hooks must be reviewed and trusted before they run. Any repo-local hook file change can require retrust.
- `results/_context/` is already the right compact context surface for TradingAgents:
  - `latest-summary.json`
  - `latest-flags.json`
  - `automation-index.json`
  - `recent-deltas.md`
  - `context-manifest.json`
  - `automation-compaction-approval-plan.md`
- The repo already says raw packets should only be opened for blockers, submitted actions, issues, stale data, failed graph runs, changed candidates, changed paper tournament leader, schema mismatch, abnormal P/L, or unexplained action changes.

## Plain-English Model

The hook layer should work like a small airlock.

Before a goal, agent, or automation gets deep into the repo, it should refresh the small dashboard files. Then it should decide whether the big evidence files are actually needed. After the run, it should write a tiny summary of what changed.

That means future Codex runs spend tokens on:

- the current state
- the exact files that matter
- the exact blocker or trade decision

They should not spend tokens on:

- old packets
- full stdout logs
- entire automation memories
- full Deep Research reports unless flagged
- raw secret-bearing environment files

## Native Hook Event Mapping

| Codex event | Use for this repo | Token-efficiency behavior |
| --- | --- | --- |
| `SessionStart` | Start of a Codex thread or resumed session | Refresh `results/_context/` and print a tiny orientation path. |
| `UserPromptSubmit` | New user request | Detect TradingAgents scope, classify as `routine`, `implementation`, `investigation`, or `live-risk`. |
| `SubagentStart` | A delegated agent starts | Give the subagent only the compact context contract and exact task boundary. |
| `SubagentStop` | A delegated agent finishes | Store only the subagent summary, file references, commands run, and blockers. |
| `PreToolUse` | Before shell or edit tools | Warn or block only obviously token-expensive reads when a compact index should be used first. |
| `PostToolUse` | After shell or edit tools | Record command class, output size, changed paths, and whether a compact summary needs refresh. |
| `PreCompact` | Before context compaction | Write a handoff packet under `results/_context/handoffs/`. |
| `PostCompact` | After context compaction | Rehydrate from compact files instead of old chat history. |
| `Stop` | End of a turn | Append a compact run event and refresh `latest-summary.json` if TradingAgents files changed. |

## Files To Create

- Create: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.codex\hooks\hooks.json`
  - Repo-local hook definitions. Start with only the probe and compact snapshot hooks.
- Create: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.codex\hooks\hook_probe.py`
  - Captures the redacted hook payload shape for this machine. Writes keys and event names, not full prompts or secrets.
- Create: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.codex\hooks\token_context_hook.py`
  - Shared hook entrypoint for `SessionStart`, `SubagentStart`, `SubagentStop`, `PreCompact`, `PostCompact`, and `Stop`.
- Create: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\config\token_context_policy.json`
  - Compact rules, raw-packet open triggers, max output sizes, and safe command classes.
- Create: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\scripts\tradingagents_hooked_run.ps1`
  - Optional wrapper for automations and n8n. Runs snapshot before and after repo commands.
- Create: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\tradingagents\orchestration\token_context.py`
  - Pure Python helpers for reading compact context, classifying flags, and writing hook event packets.
- Create: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\tests\test_token_context_hooks.py`
  - Focused tests for compact context, raw-packet triggers, redaction, and event packet writing.

## Files To Modify

- Modify: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\AGENTS.md`
  - Add a short rule that every TradingAgents goal, subagent, and automation starts from `results/_context/`.
- Modify: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\CONTEXT_ROUTER.md`
  - Add the hook contract and the exact "open raw packets only when flagged" policy.
- Modify: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\scripts\automation_context_snapshot.py`
  - Add an optional `--hook-event EVENT` mode that writes a small hook event packet without changing trading behavior.
- Modify later, after hook POC: `C:\cm\automations\*\automation.toml`
  - Add compact context preface text to automation prompts. Do this after one low-risk proof, not all at once.

## Files Not To Modify First

- Do not modify `C:\cm\config.toml` during the first proof.
- Do not replace the existing `notify = [...]` turn-ended line.
- Do not move live-submit approval into hooks.
- Do not let hooks read `.env`, raw packet bodies, full automation memories, or full Deep Research reports by default.
- Do not let hooks place, approve, promote, cancel, or modify trades.

## Task 1: Add A Harmless Hook Payload Probe

**Files:**
- Create: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.codex\hooks\hook_probe.py`
- Create: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.codex\hooks\hooks.json`

- [x] **Step 1: Create the probe script**

```python
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        lower = value.lower()
        if any(token in lower for token in ("api_key", "secret", "token", "password", "bearer")):
            return "[REDACTED]"
        if len(value) > 300:
            return value[:300] + "...[truncated]"
        return value
    if isinstance(value, dict):
        return {str(k): _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value[:25]]
    return value


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {"raw_stdin_prefix": raw[:300], "parse_error": "json_decode_failed"}

    event = os.environ.get("CODEX_HOOK_EVENT") or payload.get("hook_event") or payload.get("event") or "unknown"
    root = Path.cwd()
    out_dir = root / "results" / "_context" / "hook-events"
    out_dir.mkdir(parents=True, exist_ok=True)
    packet = {
        "schema_version": 1,
        "event": event,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cwd": str(root),
        "payload_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
        "payload_sample": _redact(payload),
    }
    out_path = out_dir / f"hook-probe-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}.json"
    out_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 2: Create the minimal hook config**

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|compact",
        "hooks": [
          {
            "type": "command",
            "commandWindows": "python .codex\\hooks\\hook_probe.py",
            "timeout": 10,
            "statusMessage": "Recording safe hook shape"
          }
        ]
      }
    ],
    "SubagentStart": [
      {
        "hooks": [
          {
            "type": "command",
            "commandWindows": "python .codex\\hooks\\hook_probe.py",
            "timeout": 10,
            "statusMessage": "Recording safe subagent hook shape"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "commandWindows": "python .codex\\hooks\\hook_probe.py",
            "timeout": 10,
            "statusMessage": "Recording safe stop hook shape"
          }
        ]
      }
    ]
  }
}
```

- [x] **Step 3: Trust the hook through Codex UI or CLI**

Run `/hooks` in Codex, review the exact hook definitions, and trust them only after confirming they call repo-local Python scripts.

Result: CLI/runtime proof completed for the repo-local hook command path. Manual Codex UI trust can still be required after hook file edits and remains documented as an intentional rollout control in `reports\orchestration\TOKEN_HOOK_FINAL_EVAL.md`.

- [x] **Step 4: Verify probe output**

Run any tiny Codex turn in this repo, then check:

```powershell
Get-ChildItem results\_context\hook-events | Sort-Object LastWriteTime -Descending | Select-Object -First 5
```

Expected: one or more `hook-probe-*.json` files. They should contain event metadata and redacted payload samples only.

## Task 2: Add Pure Context Helpers

**Files:**
- Create: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\tradingagents\orchestration\token_context.py`
- Create: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\config\token_context_policy.json`
- Create: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\tests\test_token_context_hooks.py`

- [x] **Step 1: Write tests first**

Test cases:

- compact context loads from `results/_context/latest-summary.json` and `latest-flags.json`
- raw packet opening is required when flags include submitted actions, blockers, issues, stale data, graph failures, changed candidates, changed tournament leader, schema mismatch, abnormal P/L, or unexplained actions
- redaction removes values whose keys include `api_key`, `secret`, `token`, `password`, or `bearer`
- hook event packets stay small and do not include full raw packet bodies

- [x] **Step 2: Implement helpers**

Core functions:

```python
def load_compact_context(repo_root: Path) -> CompactContext: ...
def classify_raw_context_need(flags: Mapping[str, Any]) -> RawContextDecision: ...
def redact_hook_payload(payload: Any) -> Any: ...
def write_hook_event(repo_root: Path, event: str, payload: Mapping[str, Any], decision: RawContextDecision) -> Path: ...
```

- [x] **Step 3: Run focused tests**

```powershell
uv run --with pytest python -m pytest tests/test_token_context_hooks.py -q
```

Expected: all tests pass.

## Task 3: Replace Probe With Compact Hook Script

**Files:**
- Create: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.codex\hooks\token_context_hook.py`
- Modify: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.codex\hooks\hooks.json`

- [x] **Step 1: Build `token_context_hook.py`**

Behavior:

- Run `python scripts/automation_context_snapshot.py --write` on `SessionStart`, `SubagentStart`, `PostCompact`, and `Stop`.
- Read only `results/_context/latest-summary.json` and `results/_context/latest-flags.json`.
- Write one compact event packet under `results/_context/hook-events/`.
- Print at most 20 lines.
- Return exit code `0` unless the script itself is broken.

- [x] **Step 2: Use native events**

Hook config should use:

- `SessionStart` for fresh or resumed thread orientation
- `SubagentStart` to prepare compact context for delegated agents
- `SubagentStop` to capture the agent summary boundary
- `PreCompact` to write a handoff packet before compaction
- `PostCompact` to refresh compact context after compaction
- `Stop` to write the final compact event for the turn

- [x] **Step 3: Do not add `PreToolUse` enforcement yet**

Wait until probe payloads confirm the exact tool-use payload shape. Start with reporting and refresh, not blocking.

## Task 4: Add Optional PreToolUse Warnings

**Files:**
- Modify: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.codex\hooks\hooks.json`
- Modify: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\.codex\hooks\token_context_hook.py`
- Modify: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\tests\test_token_context_hooks.py`

- [x] **Step 1: Add warning-only policy**

Warn when a shell command tries to read these broad targets without first refreshing compact context:

- `results/**/*.json`
- `C:\cm\automations\*\memory.md`
- full Deep Research report files
- old timestamped packets
- `.env`

- [x] **Step 2: Keep warnings non-blocking**

The first version should record `warning_only=true`. Blocking can be added only after repeated proof that it does not break legitimate repo work.

- [x] **Step 3: Test command classification**

Use unit tests with strings like:

```powershell
Get-Content results\hourly_supervisor\old-big-packet.json
rg "submitted" results
python scripts\automation_context_snapshot.py --write
```

Expected:

- Broad raw packet reads warn.
- Snapshot command is allowed.
- Focused known-file reads are allowed when flags justify them.

Result:

```powershell
uv run --with pytest python -m pytest tests/test_token_context_hooks.py tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py -q
.\.venv\Scripts\python.exe -m py_compile tradingagents\orchestration\token_context.py .codex\hooks\token_context_hook.py scripts\automation_context_snapshot.py tradingagents\orchestration\n8n_runner.py tradingagents\orchestration\n8n_policy.py
'{"hook_event_name":"PreToolUse","tool_name":"exec_command","tool_input":{"cmd":"Get-Content results\\hourly_supervisor\\old-big-packet.json"},"api_key":"fake-secret"}' | .\.venv\Scripts\python.exe .codex\hooks\token_context_hook.py
```

Passed with 42 tests. The manual `PreToolUse` run returned `0`, printed `pre_tool_warning=warning_only`, wrote `results\_context\hook-events\hook-event-20260603-034001-934940.json`, and redacted the fake `api_key`.

## Task 5: Add A Hooked Automation Runner

**Files:**
- Create: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\scripts\tradingagents_hooked_run.ps1`

- [x] **Step 1: Create wrapper**

Behavior:

- Run `python scripts\automation_context_snapshot.py --write` before command execution.
- Run the requested repo command.
- Run `python scripts\automation_context_snapshot.py --write` after command execution.
- Write a compact run packet under `results/_context/hook-events/`.
- Return the original command exit code.

- [x] **Step 2: Preserve existing trading safety**

For order-affecting commands, the wrapper must not bypass:

- `alpaca check`
- dry-run
- unified live-submit guard
- risk envelope
- stale data checks
- promotion gates

- [x] **Step 3: Use wrapper only for one low-risk automation first**

Start with daily report or paper tournament context refresh. Do not start with live/hourly submit paths.

Result: low-risk wrapper proof ran `scripts\tradingagents_hooked_run.ps1` around `scripts\automation_context_snapshot.py --write`, returned exit `0`, and wrote `results\_context\hook-events\hooked-run-20260603-040235-344992.json` with `authority=context_wrapper_no_trade_bypass`.

## Task 6: Update Durable Instructions

**Files:**
- Modify: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\AGENTS.md`
- Modify: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\CONTEXT_ROUTER.md`

- [x] **Step 1: Add compact start rule**

Add this rule:

```markdown
For TradingAgents goals, subagents, and automations, run `python scripts/automation_context_snapshot.py --write` first, then read `results/_context/latest-summary.json`, `results/_context/latest-flags.json`, and `results/_context/recent-deltas.md`. Open raw packets only when those files flag a reason.
```

- [x] **Step 2: Add subagent output contract**

Every subagent should return:

- task result
- exact files inspected
- exact files changed
- tests or commands run
- compact blocker list
- raw packets opened and why

No subagent should paste full logs or full packet bodies into the main thread.

Result: `docs/orchestration/goal-agent-context-contract.md` now defines the subagent output contract; `AGENTS.md` and `CONTEXT_ROUTER.md` point future agents to it. Proof: `uv run --with pytest python -m pytest tests/test_token_context_hooks.py -q` passed with 12 tests including the contract doc check.

## Task 7: Update Automations In Phases

**Files:**
- Modify later: `C:\cm\automations\paper-strategy-tournament-runner\automation.toml`
- Modify later: `C:\cm\automations\tradingagents-daily-market-report\automation.toml`
- Modify later: `C:\cm\automations\hourly-market-supervisor\automation.toml`
- Modify later: `C:\cm\automations\market-supervisor-*\automation.toml`
- Modify later: `C:\cm\automations\tradingagents-overnight-planning\automation.toml`

- [x] **Step 1: Start with low-risk prompt compaction**

First update the daily report or paper tournament prompt:

```text
Start by running `python scripts/automation_context_snapshot.py --write`.
Read only `results/_context/latest-summary.json`, `latest-flags.json`, and `recent-deltas.md`.
Open raw packets only for submitted actions, issues, blockers, stale data, changed candidates, changed tournament leader, abnormal P/L, schema mismatch, or unexplained action changes.
Report compactly. Do not paste full packets or full stdout.
```

- [x] **Step 2: Observe two successful runs**

Verify:

- automation still completes
- output is shorter
- packet paths are preserved
- no safety gate is weakened
- no raw secrets are read

Result: low-risk observations succeeded through `scripts\run-tradingagents-job.ps1 -Job context_snapshot` and `scripts\tradingagents_hooked_run.ps1 ... automation_context_snapshot.py --write`. Both stayed compact/context-only; latest wrapper packet is `results\_context\hook-events\hooked-run-20260603-040235-344992.json`.

- [x] **Step 3: Apply to live-adjacent supervisors**

Only after low-risk proof, add the compact preface to hourly/open/close supervisor prompts.

- [x] **Step 4: Apply to overnight planner**

Overnight can stay high-context, but it should still start from compact state and open full reports only for flagged candidates or quality failures.

Applied prompt rollout on 2026-06-02 through Codex automation updates for:

- `hourly-market-supervisor`
- all market-window supervisors
- `tradingagents-daily-market-report`
- `paper-strategy-tournament-runner`
- `tradingagents-overnight-planning`
- wake/sleep controllers, with n8n/hooks classified as repo-local POC surfaces rather than Codex cron jobs

Strict prompt scan found no old live-budget blocker wording in active automation TOMLs.

## Task 8: Add Goal Operating Contract

**Files:**
- Modify: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\AGENTS.md`
- Modify: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\CONTEXT_ROUTER.md`

- [x] **Step 1: Define goal states**

Use these repo-local states in hook event packets:

- `goal_absent`
- `goal_active`
- `goal_waiting_for_user`
- `goal_blocked`
- `goal_complete`

Result: state definitions now live in `docs/orchestration/goal-agent-context-contract.md`.

- [x] **Step 2: Define goal context rules**

When a goal exists:

- Start every turn with compact context.
- Save a compact handoff before compaction.
- Dispatch subagents only with a narrow file/task boundary.
- Mark complete only after the relevant quick tests or explicit skipped-test note.

Result: context rules now live in `docs/orchestration/goal-agent-context-contract.md` and are linked from `AGENTS.md`/`CONTEXT_ROUTER.md`.

- [x] **Step 3: Keep native goal updates human-visible**

Do not create or update Codex goals from hidden hooks. Use hooks to write context packets; use visible Codex goal tools only when the user asked for a goal.

Result: `docs/orchestration/goal-agent-context-contract.md` explicitly says hidden hooks must not create, complete, block, or rewrite goals; the active goal in this thread was checked and managed with visible goal tools only.

## Task 9: n8n Bridge POC

**Files:**
- Created: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\tradingagents\orchestration\n8n_runner.py`
- Created: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\tradingagents\orchestration\n8n_policy.py`
- Created: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\config\n8n_tradingagents_allowlist.json`
- Created: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\config\n8n\workflows\status-dashboard-poc.json`
- Created: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\scripts\start-n8n-tradingagents-runner.ps1`
- Created: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\scripts\run-tradingagents-job.ps1`

- [x] **Step 1: Keep n8n as observer/controller**

n8n should call the hooked wrapper or read `results/_context/`. It should not become the place where trading decisions live.

- [x] **Step 2: Consume compact summaries only**

n8n should open full reports only on these flags:

- submitted actions
- blockers
- changed candidates
- stale data
- failed graph runs
- abnormal P/L or exposure change

## Task 10: Final Eval Gate After Hook Plan Completion

**Files:**
- Modify if needed: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\reports\orchestration\TOKEN_HOOK_FINAL_EVAL.md`
- Read: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\_context\hook-events\`
- Read: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\results\process_reviews\`

- [x] **Step 1: Run repo-native custom evals**

```powershell
python scripts/automation_context_snapshot.py --write
.\.venv\Scripts\tradingagents.exe research process-review --json-output
uv run --with pytest python -m pytest tests/test_process_review.py tests/test_automation_context_snapshot.py tests/test_deep_research_protocol.py -q
```

Expected:

- process review packet is written
- context snapshot still builds
- Deep Research methodology context still stays analysis-only
- no hook event packet leaks secrets, full prompts, or full raw packets

Result:

```powershell
python scripts/automation_context_snapshot.py --write
.\.venv\Scripts\tradingagents.exe research process-review --json-output
uv run --with pytest python -m pytest tests/test_process_review.py tests/test_automation_context_snapshot.py tests/test_deep_research_protocol.py -q
```

Passed with 20 tests. Latest process review packet: `results\process_reviews\process-review-20260603-035421.json`.

- [x] **Step 2: Run Plugin Eval only on actual skill/plugin artifacts**

If this plan creates a repo-local skill or plugin-like artifact, run:

```powershell
plugin-eval analyze <skill-or-plugin-path> --format markdown
plugin-eval explain-budget <skill-or-plugin-path> --format markdown
```

Do not force Plugin Eval onto the whole TradingAgents repo. For non-skill repo surfaces, use the custom process review and focused tests instead.

Result: no repo-local skill/plugin artifact was created by this hook plan. Plugin Eval was used only as advisory structural analysis on plan docs and saved to `reports\orchestration\ENDGAME_PLANS_PLUGIN_EVAL.md`.

- [x] **Step 3: Apply `plugin-eval:improve-skill` pattern when findings exist**

For any evaluated skill with findings:

- group required fixes versus recommended fixes
- write a concrete improvement brief
- apply the smallest safe rewrite
- rerun `plugin-eval analyze`
- compare before and after reports when JSON output exists

Result: the advisory finding was excessive deferred token cost for the whole plan directory. The improve-skill-style mitigation is to route through `CONTEXT_ROUTER.md`, active endgame plan, and process-review packets instead of bulk-loading all plan docs.

- [x] **Step 4: Save final audit summary**

Write a short final report under:

```text
C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\reports\orchestration\TOKEN_HOOK_FINAL_EVAL.md
```

The report must say:

- what hooks ran
- what token/context issues were found
- what was fixed
- what remains intentionally manual
- whether any high-severity finding blocks completion

Result: updated `reports\orchestration\TOKEN_HOOK_FINAL_EVAL.md`. It records hook runs, token/context hotspots, warning-only `PreToolUse`, Plugin Eval findings, remaining manual trust/observation controls, and no high-severity safety blocker.

## Validation Plan

Run these checks in order:

```powershell
python scripts/automation_context_snapshot.py --write
uv run --with pytest python -m pytest tests/test_token_context_hooks.py -q
uv run --with pytest python -m pytest tests/test_automation_context_snapshot.py -q
```

After prompt changes to automations, run only the affected focused slice first. Save broad regression for the phase gate.

Before enabling warning/blocking hooks on live-adjacent paths, run:

```powershell
uv run --with pytest python -m pytest tests/test_alpaca_cli.py tests/test_alpaca_supervisor.py tests/test_alpaca_execution.py tests/test_live_gate.py -q
```

## Completion Criteria

- Hooks are trusted and visible through `/hooks`.
- `results/_context/hook-events/` receives compact event packets.
- Subagent starts and stops produce compact boundaries.
- Compaction writes a usable handoff before context is lost.
- Automations start from `results/_context/`.
- Raw packets are opened only when flags justify them.
- No hook stores secrets, full prompts, full raw packets, or full command logs.
- No hook can place or approve trades.
- Focused tests pass.

## Self-Review

- Spec coverage: covers goals, subagents, automations, hooks, compaction, n8n bridge, and token efficiency.
- Placeholder scan: no `TBD` or implementation-by-handwave remains.
- Risk check: first step is probe-only and does not change `C:\cm\config.toml`, broker behavior, or live-submit gates.
- Token check: the design uses compact summaries first and escalates to raw packets only when flagged.
