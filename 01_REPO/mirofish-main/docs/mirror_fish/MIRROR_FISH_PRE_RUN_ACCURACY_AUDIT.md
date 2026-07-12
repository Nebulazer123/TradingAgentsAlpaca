# MiroFish Pre-Run Accuracy Audit

Generated: 2026-06-03

Scope: final predictive-quality upgrade pass before the real Stage 03 run. Stage 03 remains gated and unstarted.

## Scorecard

Scores are pre-run engineering estimates on a 0-10 scale. "Current" means the packet before this pass. "Post-fix expected" means the prepared local artifacts after this pass.

| Dimension | Current | Post-fix Expected | Weak Point Fixed |
| --- | ---: | ---: | --- |
| temporal fidelity | 7.0 | 9.2 | 30 rounds now map explicitly to June 4-13 event beats. |
| unique active-agent coverage | 4.5 | 7.6 | Per-hour targets doubled from 8-20 to 16-40. |
| social emergence depth | 8.2 | 8.8 | More active turns plus state-variable tracking. |
| broker/account realism | 5.0 | 8.5 | 525 actors now carry broker/account segment tags in config and profiles. |
| options/0DTE realism | 6.0 | 8.4 | Added options/microstructure signal separation and expiry beats. |
| macro/catalyst coverage | 8.0 | 9.1 | BLS, Treasury, WWDC, Oracle, oil, and AI/semi confounders explicitly mapped. |
| institutional/liquidity coverage | 8.0 | 8.8 | Causal plan and state variables force market-maker/ETF desk response. |
| live source grounding | 6.5 | 8.0 | Fresh public web/news patch added; X not claimed. |
| forecast measurability | 3.0 | 8.8 | Forecast ballots required on rounds 3, 6, 11, 18, 22, 25, and 30. |
| causal attribution quality | 4.5 | 8.6 | Final report must maintain a cause ledger and control branch comparison. |
| model throughput | 8.5 | 7.5 | More active actions raise cost but remain practical. |
| post-run telemetry quality | 3.5 | 8.2 | Added schema-tolerant telemetry extractor. |
| ReportAgent usefulness | 7.2 | 9.0 | Report now has state variables, ballots, validation schema, and cause ledger. |
| TradingAgents advisory usefulness | 6.8 | 9.0 | Added post-run evidence path and validation-task handoff. |

## Exact Changes Made

- Created `MIRROR_FISH_EVENT_BEAT_MAP.md`.
- Created `MIRROR_FISH_STATE_VARIABLES.md`.
- Created `MIRROR_FISH_CAUSAL_ATTRIBUTION_PLAN.md`.
- Created `MIRROR_FISH_OPTIONS_MICROSTRUCTURE_BRIEF.md`.
- Created `MIRROR_FISH_JUNE4_LIVE_CONTEXT_PATCH.md`.
- Created `MIRROR_FISH_STAGE05_INTERVIEW_PLAN.md`.
- Created `mirofish_active_coverage_estimator.py`.
- Created `mirofish_postrun_telemetry.py`.
- Patched `MIRROR_FISH_PDT_SIMULATION_PROMPT.md` with the predictive-quality upgrade requirements.
- Synced `backend\uploads\simulations\sim_974459649906\simulation_config.json` to the updated prompt.
- Added 30 `event_config.scheduled_events` beat records to the prepared config.
- Changed `time_config.agents_per_hour_min` from 8 to 16.
- Changed `time_config.agents_per_hour_max` from 20 to 40.
- Added `predictive_quality_upgrade` metadata with state variables, ballot rounds, validation schema, and control branch.
- Added broker/account segmentation fields to 525 retail/person/broker/organization actors.
- Appended segment tags into matching Reddit and Twitter profile text so the runtime profiles can express the account assumptions.

## Active Coverage

Before:

- per-platform actions: low 176, mid 315, high 450
- dual-platform actions: low 352, mid 630, high 900

After:

- per-platform actions: low 352, mid 629, high 893
- dual-platform actions: low 704, mid 1257, high 1786
- expected unique active agents: mid 436 per platform, mid 647 dual-platform

The after-pass dual-platform action estimate now fits the requested 1,200-2,000 practical range at mid/high settings. Expected mid unique coverage is slightly below the 450-agent lower target per platform, but dual-platform unique coverage is inside the desired range.

## Cost Estimate

Before:

- mid: $0.5360
- worst: $1.5772

After:

- mid: $1.0703
- worst: $3.1300

This estimate covers Stage 03 active-agent LLM actions only. Stage 04 report generation, Stage 05 interviews, Zep operations, retries, and long-output spikes remain separate costs.

## Post-Run TradingAgents Evidence Path

After the real run, Codex must read:

- uploaded seed
- project metadata/extracted text
- simulation config
- `twitter_simulation.db`
- `reddit_simulation.db`
- `simulation.log`
- `run_state.json`
- ReportAgent `full_report.md`
- report `agent_log.jsonl`
- `postrun_telemetry.json` and `postrun_telemetry.md`
- Zep graph/context export if available
- TradingAgents `market_mirror.py` and `market_structure.py`
- TradingAgents advisory packet schema if/when created

Post-run output should become:

- advisory evidence packet
- scenario probabilities
- forecast ballot aggregation
- causal attribution ledger
- validation tasks
- false-signal filters
- ticker/category watchlist
- broker/platform confusion assumptions
- bot-correlation warnings
- daily refresh checklist

## Remaining Launch Risks

- Launch-path integrity was hardened after this audit: `run_parallel_simulation.py` now injects scheduled-event context posts into both Twitter/common and Reddit/boost lanes and logs `round_event` metadata for telemetry. Keep `MIRROR_FISH_LAUNCH_PATH_INTEGRITY_AUDIT.md` as the source of truth for that runtime check.
- More active actions increase cost and output volume. Keep `max_rounds=30` unless a fresh cost review approves more.
- Public Reddit snippets are weak signal only. X/Twitter research was not queried in this pass.
- MiroFish still cannot validate actual options flow, support-ticket counts, order rejections, or market data. Those become post-run validation tasks.
- Stage 03 must remain closed until the user gives explicit approval.
