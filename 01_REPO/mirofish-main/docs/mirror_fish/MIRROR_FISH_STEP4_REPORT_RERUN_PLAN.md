# Mirror Fish Step 4 Report Rerun Plan

## What Failed

The current failed Step 4 evidence report is preserved at `backend\uploads\reports\report_e22efc97ca64`. It completed, but it is not acceptable as final output because the report planner compressed the required Mirror Fish report into four broad sections, the first section is a short mixed-language fragment, Zep calls hit free-plan 429 rate limits, graph-wide fetch failures were represented as fake-empty graph results, and live `interview_agents` calls were attempted after `sim_974459649906` had stopped.

## What Was Degraded But Usable

Stage 3 artifacts appear usable and should not be rerun unless later checks prove corruption or missing files. Current telemetry indicates 30 rounds, 657 unique active agents, 1089 Reddit actions, 764 Twitter actions, and 144 ballot-like actions. Zep remains configured and canonical; `graph.search` works, but it must be paced, cached, and checkpointed.

## What Must Be Fixed Before Manual Rerun

Step 4 must run in Zep-canonical `zep_throttle_cached` mode with a global Zep query budget, sequential graph.search calls, deterministic compact English queries, cache reuse, no interactive all-node/all-edge panorama, completed-run replay/deferred interview handling, the full 20-section Mirror Fish outline, per-section evidence packets, report diagnostics, report/cache locks, and English-only quality gates before any section is accepted.

## Zep Account Action

No Zep account action is required for a clean Zep-canonical rerun using throttle/cache mode. Upgrading Zep is optional if fast graph-wide node/edge panorama becomes necessary, but the interactive Step 4 path is designed not to require that.

## Artifacts Step 4 Will Use

- `backend\uploads\simulations\sim_974459649906\postrun_telemetry.json`
- `backend\uploads\simulations\sim_974459649906\postrun_telemetry.md`
- `backend\uploads\simulations\sim_974459649906\run_state.json`
- `backend\uploads\simulations\sim_974459649906\twitter\actions.jsonl`
- `backend\uploads\simulations\sim_974459649906\reddit\actions.jsonl`
- `backend\uploads\simulations\sim_974459649906\twitter_profiles.csv`
- `backend\uploads\simulations\sim_974459649906\reddit_profiles.json`
- `backend\uploads\simulations\sim_974459649906\twitter_simulation.db`
- `backend\uploads\simulations\sim_974459649906\reddit_simulation.db`
- Zep graph `mirofish_4a9df9ae8b184878` through cached, throttled `graph.search`
- reusable Zep cache under `backend\uploads\reports\_zep_cache\mirofish_4a9df9ae8b184878`

## Browser Rerun Path

After the patch, use the normal browser Step 4 / Generate Report button for `sim_974459649906`. The browser path now sends safe rerun options: `force_regenerate=true`, `report_mode=zep_throttle_cached`, `outline_mode=mirror_fish_full`, `language=english`, `zep_safe_mode=true`, `zep_interval_seconds=20`, `max_live_zep_calls=50`, and `max_live_zep_calls_per_section=3`.

## API Fallback

```powershell
Invoke-RestMethod -Uri "http://localhost:5001/api/report/generate" -Method POST -ContentType "application/json" -Body '{"simulation_id":"sim_974459649906","force_regenerate":true,"report_mode":"zep_throttle_cached","outline_mode":"mirror_fish_full","language":"english","zep_safe_mode":true,"zep_interval_seconds":20,"max_live_zep_calls":50,"max_live_zep_calls_per_section":3}'
```

## Hydration Command

```powershell
.\backend\.venv\Scripts\python.exe backend\scripts\hydrate_zep_report_cache.py --simulation-id sim_974459649906 --graph-id mirofish_4a9df9ae8b184878 --interval-seconds 20 --limit 10 --max-queries 40
```

## Non-Goals

- Do not rerun Stage 3.
- Do not rerun full Step 4 until explicitly approved after implementation.
- Do not overwrite or rename `report_e22efc97ca64`.
- Do not send email.
- Do not update Google Drive.
- Do not replace Zep with local-only storage.
