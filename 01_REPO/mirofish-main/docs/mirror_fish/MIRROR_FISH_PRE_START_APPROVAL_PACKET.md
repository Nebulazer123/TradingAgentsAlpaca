# MiroFish Pre-Start Approval Packet

Generated: 2026-06-02
Updated: 2026-06-03

Status: stage 01/02 setup is complete. A capped stage 03 stress copy passed. Do not start the real simulation until the user explicitly says the real engine may start.

## 0. Current Launch Packet

Prepared real-run artifacts:

- Project: `proj_8ece728e49fe`
- Graph: `mirofish_4a9df9ae8b184878`
- Simulation: `sim_974459649906`
- Config: `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\simulations\sim_974459649906\simulation_config.json`
- Seed: `C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_PDT_REALITY_SEED.md`
- Prompt: `C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_PDT_SIMULATION_PROMPT.md`

Prepared population:

- 1,000 runnable OASIS agents.
- 420 retail/new-trader agents.
- 120 broker/platform/clearing agents.
- 130 developer/automation agents.
- 80 media/narrative agents.
- 70 policy/regulatory agents.
- 140 institutional/liquidity agents.
- 40 tech-company/executive agents.

Read-only actor-population audit:

- Command: `python docs\mirror_fish\mirofish_actor_population_audit.py`
- Result: passed against `sim_974459649906`.
- Non-retail quota: 580 agents.
- Actual non-retail entity count: 565 agents.
- Required named anchors present: SEC Market Structure Staff, Congressional Market Structure Staff, Citadel Securities Market Maker Desk, Jane Street ETF Quant Desk, BlackRock iShares ETF Desk, Volatility Market Maker Desk, CNBC Markets Desk, Bloomberg Market Structure Desk, Open-source Trading Bot Maintainers, Fintech Brokerage CEO Roundtable, and AI Trading Infrastructure Founder.
- Initial event posts include retail, broker/platform, developer/community, regulator/policy, media, finfluencer, institution/market-structure, organization/company, and tech-executive voices.

This explicitly routes government/regulatory/policy actors, companies, media outlets, developer communities, tech executives, institutional investors, market makers, liquidity providers, broker/platform desks, and retail trader cohorts. The run is not retail-only and is not just regular people reacting online.

Capped proof:

- Stress copy: `sim_974459649906_stress2`
- `max_rounds=2`
- Completed dual-platform startup with 24 total actions.
- Zep graph memory update sent all 24 stress activities with `failed=0`.
- Stress environment was closed with `close-env`; the real simulation remains `ready` and unstarted.

Actual prepared-config stage 03 estimate for 30 rounds:

- Dual-platform active-agent actions: low 704, mid 1257, high 1786.
- Action-only LLM estimate: mid `$1.0703`, worst `$3.1300`.
- This excludes stage 04 report, stage 05 interviews, Zep operations, retries, and any long-output spikes.

Predictive-quality pass:

- The 30 rounds now map explicitly to June 4-13 event beats in `event_config.scheduled_events` and `MIRROR_FISH_EVENT_BEAT_MAP.md`.
- Launch-path integrity hardening now makes those beats runtime-visible to both Twitter/common and Reddit/boost agents through per-round context posts, with `round_event` metadata logged for telemetry.
- Forecast ballots are required on rounds 3, 6, 11, 18, 22, 25, and 30.
- Fourteen simulated state variables are defined for ReportAgent and post-run telemetry.
- 525 retail/person/broker/organization actors carry broker/account segment tags in config and profile text.
- The final report must compare every branch against the no-meaningful-retail-flow control and maintain causal attribution plus validation thresholds.

## 1. Purpose

Run one high-quality MiroFish simulation for the June 4-13, 2026 PDT-to-intraday-margin market/social reaction window.

Core question:

How do different trader groups behave when they suddenly believe day trading got easier, while brokers still impose real-time constraints and the market is simultaneously reacting to jobs, CPI, PPI, Treasury auctions, oil/geopolitics, AI-semiconductor catalysts, and broker/platform rollout confusion?

The output is an advisory evidence packet for TradingAgents. It should produce research questions, watchlists, validation tasks, false-signal filters, retail-flow hypotheses, broker/platform confusion patterns, bot-user failure modes, scenario branches, and daily refresh signals. It must not trigger live orders, paper orders, or automation changes.

## 2. Exact `.env` Model Shape

Current repo `.env` is now switched to the approved quality-first OpenRouter route. It currently uses:

```env
LLM_MODEL_NAME=qwen/qwen3.6-plus
LLM_BOOST_MODEL_NAME=deepseek/deepseek-v4-pro
```

Recommended approved-run shape:

```env
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL_NAME=qwen/qwen3.6-plus

LLM_BOOST_BASE_URL=https://openrouter.ai/api/v1
LLM_BOOST_MODEL_NAME=deepseek/deepseek-v4-pro
```

Keys are present in repo/user env but are intentionally not printed.

The most recent guarded switch wrote backup:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\.env.mirofish-backup-20260603T014719Z`

Guarded preview command:

```powershell
python docs\mirror_fish\mirofish_env_gate.py
```

To re-apply the recommended model-route lines and write a timestamped backup:

```powershell
python docs\mirror_fish\mirofish_env_gate.py --apply --confirm switch-mirofish-models
```

Rollback command before launch if needed:

```powershell
python docs\mirror_fish\mirofish_env_gate.py --restore <backup_path> --confirm restore-mirofish-env
```

## 3. Chosen Model And Why

Chosen primary/common swarm lane:

`qwen/qwen3.6-plus`

Reason:

- Passed the realistic Deep Research seed probe.
- Stayed grounded to broker-staggered rollout, macro competition, and social-simulation behavior.
- Is the quality-first Qwen choice for this run; speed is not a selection priority.
- Still has acceptable cost value for a quality-first swarm run.
- Fits MiroFish's value better than a single expensive reasoning model: persona diversity, platform dynamics, many agent interactions, and ReportAgent synthesis.

Cost-value Qwen fallback:

`qwen/qwen-plus-2025-07-28:thinking`

Use it only if the prepared `simulation_config.json` makes Qwen3.6 Plus cost materially worse than expected.

## 4. Probe Results

Qwen candidates:

| Model | Result | Latency | Notes |
| --- | --- | --- | --- |
| `qwen/qwen3.6-plus` | Pass | 61.30s | Quality-first primary; slower, but speed is not the deciding factor. |
| `qwen/qwen-plus-2025-07-28:thinking` | Pass | 25.00s | Cost-value fallback; good grounding at cheaper output pricing. |
| `qwen/qwen3.5-plus-20260420` | Pass | 86.94s | Grounded but slowest of the Qwen probes. |

DeepSeek boost:

`deepseek/deepseek-v4-pro`

- Compact `max_tokens=650` probe was not reliable.
- Retest with `max_tokens=1200` produced visible Reddit/contrarian archetypes, false-positive risks, and validation tasks in 23.99s.
- Do not force `reasoning.effort=low`; that retest spent the whole budget invisibly.

Fallbacks:

- Cheap fallback: `deepseek/deepseek-v4-flash`.
- Quality fallback: `google/gemini-3-flash-preview`.
- Avoid direct Google `gemini-3.5-flash` for the unpatched MiroFish route.
- Avoid OpenRouter Auto Router for the main run.

## 5. Chosen Run Shape

- Target agents: 1,000.
- Acceptable range: 750-1,500.
- Target rounds: 30.
- Acceptable range: 25-35.
- Do not jump to 40-50 rounds unless readiness and cost estimate justify it.
- Use short-to-medium agent messages.
- Enable graph memory updates if stable.
- Preserve simulation environment/files after report generation for deep interaction and character interviews.

## 6. Seed And Prompt

Primary seed file:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_PDT_REALITY_SEED.md`

Operator runbook:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_OPERATOR_RUNBOOK.md`

Final prompt source:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_TRADING_RUN_READINESS.md`, section "Final Simulation Prompt To Paste Into MiroFish".

Required scenario branches:

1. Mostly narrative / limited effect.
2. Medium retail-flow effect.
3. Large speculative-flow effect.
4. Adverse macro override.
5. Valid-support branch.
6. Broker-friction branch.
7. Bot-correlation branch.
8. Institutional-liquidity branch.
9. Policy/media-clarification branch.
10. Developer-infrastructure branch.

## 7. Expected Artifact Paths

Project and extracted seed:

- `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\projects\<project_id>\project.json`
- `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\projects\<project_id>\extracted_text.txt`

Simulation:

- `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\simulations\<simulation_id>\simulation_config.json`
- `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\simulations\<simulation_id>\run_state.json`
- `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\simulations\<simulation_id>\simulation.log`
- `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\simulations\<simulation_id>\twitter_simulation.db`
- `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\simulations\<simulation_id>\reddit_simulation.db`

Report:

- `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\reports\<report_id>\meta.json`
- `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\reports\<report_id>\full_report.md`
- `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\reports\<report_id>\agent_log.jsonl`
- `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\reports\<report_id>\console_log.txt`
- `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\reports\<report_id>\section_*.md`

## 8. Cost Estimate

Estimator:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_cost_estimator.py`

Read-only preflight checker:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_preflight.py`

Read-only readiness bundle:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_readiness_bundle.py`

Read-only completion audit:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_completion_audit.py`

Guarded app-path setup helper:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_app_path_setup.py`

Actual prepared-config estimate command:

```powershell
python docs\mirror_fish\mirofish_cost_estimator.py --config backend\uploads\simulations\sim_974459649906\simulation_config.json --max-rounds 30
```

Current prepared stage 03 active-agent estimate:

- Per-platform active-agent actions: low 352, mid 629, high 893.
- Dual-platform active-agent actions: low 704, mid 1257, high 1786.
- Expected unique active agents: mid 436 per platform, mid 647 dual-platform.
- Mid-case stage 03 active-agent LLM cost: about `$1.0703`.
- Worst-case stage 03 active-agent LLM cost: about `$3.1300`.

Assumptions:

- Primary lane: `qwen/qwen3.6-plus`.
- Boost lane: `deepseek/deepseek-v4-pro`.
- Mid per active-agent action: 1,200 prompt tokens and 280 completion tokens.
- Worst per active-agent action: 2,200 prompt tokens and 650 completion tokens.
- This estimate covers stage 03 active-agent LLM actions only.
- Stage 01 graph build and stage 02 config/profile generation have already run and add separate historical cost.
- Stage 04 report generation, stage 05 interviews, Zep operations, retries, and longer-than-assumed outputs add separate future cost.

## 9. Readiness Status

Passed:

- Backend health check.
- Frontend health check.
- Guarded `.env` model-route apply: current route is `qwen/qwen3.6-plus` plus `deepseek/deepseek-v4-pro`, with a rollback backup written.
- Read-only preflight command: `python docs\mirror_fish\mirofish_preflight.py`.
- Read-only model-route preview command: `python docs\mirror_fish\mirofish_env_gate.py`.
- Read-only creator-workflow audit: `python docs\mirror_fish\mirofish_workflow_audit.py --json` passed 43/43 source checks across all five stages.
- Read-only readiness bundle: `python docs\mirror_fish\mirofish_readiness_bundle.py` summarizes env preview, workflow audit, actor-population audit, preflight, actual prepared-config cost, backend refresh proof, objective alignment, approval-gate ledger, closed real-stage-03 gate, and draft-only handoff status without writing or starting anything.
- Read-only completion audit: `python docs\mirror_fish\mirofish_completion_audit.py` verifies the plan is healthy but still not complete, with the real stage 03 run, report, deep interactions, synthesis, and final handoff left as explicit blockers.
- Guarded app-path setup helper dry-run: `python docs\mirror_fish\mirofish_app_path_setup.py` remains available for reproducibility and records the exact stage 01/02 API calls and confirmation phrases.
- Stage 01 app-path graph build completed for `proj_8ece728e49fe` / `mirofish_4a9df9ae8b184878`.
- Stage 02 prepare completed for `sim_974459649906`.
- Guarded population expansion completed: 1,000 runnable OASIS agents.
- Actor-population audit completed: 580 non-retail quota, 565 actual non-retail entities, required prompt/report sections and cross-layer feedback terms present.
- Capped stage 03 stress copy completed: `sim_974459649906_stress2`, 2 rounds, 24 actions, graph-memory update `failed=0`.
- OpenRouter completion-key status.
- OpenRouter management-key metadata access.
- OpenRouter model lookup for Qwen/DeepSeek/Gemini candidates.
- Zep project status for `trading agents`.
- Zep graph search against the earlier MiroFish/PDT smoke graph.
- Secret scan of docs/MCP setup paths.
- No-network OpenRouter/Camel constructor check for optional model controls: `OpenRouterModel` was created with `max_tokens` plus OpenRouter `extra_body.reasoning/provider` config, and no simulation/API call started.

Pending:

- Final TradingAgents handoff after stage 03 run, stage 04 report, stage 05 deep interactions/interviews, Codex synthesis, and final chat decisions.
- Explicit user approval before the real stage 03 simulation start.

## 10. Unresolved Decisions

- Decide whether to create a dedicated capped OpenRouter run key before the real run.
- Decide whether to enable any of the newly patched optional model controls for the real run: `LLM_MAX_TOKENS`, `LLM_MAX_COMPLETION_TOKENS`, `LLM_MODEL_CONFIG_JSON`, `LLM_EXTRA_BODY_JSON`, `LLM_REASONING_JSON`, or their `LLM_BOOST_*` variants. Default remains unchanged unless those env vars are set.
- Keep Qwen3.6 Plus as the quality-first primary unless the user explicitly chooses the cheaper Qwen fallback before launch.
- Confirm whether optional X/Twitter research MCP should be queried as external background before the run. MiroFish itself should not pretend live X/Reddit ingestion exists.
- Treat "automatic demand analysis" as the repo's automated requirement analysis plus generated time/event/agent configs, hot topics, narrative direction, platform timelines, and ReportAgent tools; it is not a standalone endpoint name.

## 11. Approval Gate

Stop here until the user approves the real stage 03 simulation start.

Stage 01/02 setup and the capped stress copy are complete. Starting stage 03 real simulation requires a separate explicit approval after this packet is reviewed.

The final TradingAgents handoff must remain draft-only and not sendable until the real run, ReportAgent output, deep interactions/interviews, Codex synthesis, and this chat's closeout decisions are complete.
