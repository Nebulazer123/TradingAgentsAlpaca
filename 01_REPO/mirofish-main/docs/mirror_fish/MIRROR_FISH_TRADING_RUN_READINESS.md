# Mirror Fish Trading Run Readiness Report

Generated: 2026-06-02
Updated: 2026-06-03
Post-run hardening update: 2026-06-08

Status: the original pre-launch readiness gates have been superseded by the completed MiroFish run and post-run hardening. The real Stage 03 simulation `sim_974459649906` completed 30 rounds; accepted Step 4/5 packet is `report_9c77ca2557ae`; supplemental graph-wide Zep panorama and a live Step 5 smoke are now included in the final review packet.

## Current Prepared State

The real prepared simulation is:

- Project: `proj_8ece728e49fe`
- Graph: `mirofish_4a9df9ae8b184878`
- Simulation: `sim_974459649906`
- Seed file: `C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_PDT_REALITY_SEED.md`
- Prompt file: `C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_PDT_SIMULATION_PROMPT.md`
- Prepared config: `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\simulations\sim_974459649906\simulation_config.json`

Stage 01 app-path graph construction completed with the institutional seed:

- Graph task: `8ec471b9-64f6-4113-9b0d-9c41dd4e1ed0`
- Extracted chunks: 48
- Zep graph result: 103 nodes, 117 edges
- Actor ontology included regulator/government, broker/platform, media, developer community, retail, finfluencer, and organization layers.

Stage 02 app-path environment setup completed:

- Prepare task: `3a246c2c-919e-40c5-a514-5eb5a37e653c`
- Initial app-generated profiles/configs: 23
- Runnable OASIS population after guarded expansion: 1,000 agents
- Real simulation status: `completed/stopped`; the accepted post-run report is `report_9c77ca2557ae`.

The 1,000-agent population is intentionally not retail-only. Expansion quotas:

| Actor Layer | Count |
| --- | ---: |
| Retail/new traders | 420 |
| Broker/platform/clearing | 120 |
| Developer/automation | 130 |
| Media/narrative | 80 |
| Policy/regulatory | 70 |
| Institutional/liquidity | 140 |
| Tech-company/executive | 40 |

Institutional anchors include `SEC Market Structure Staff`, `Congressional Market Structure Staff`, `Citadel Securities Market Maker Desk`, `Jane Street ETF Quant Desk`, `BlackRock iShares ETF Desk`, `Volatility Market Maker Desk`, `CNBC Markets Desk`, `Bloomberg Market Structure Desk`, `Open-source Trading Bot Maintainers`, `Fintech Brokerage CEO Roundtable`, and `AI Trading Infrastructure Founder`.

A capped stage 03 stress copy passed without consuming the real simulation:

- Stress simulation copy: `sim_974459649906_stress2`
- Cap: `max_rounds=2`
- Dual platform: Twitter + Reddit
- Result: completed, 24 total actions, 12 Twitter and 12 Reddit
- Graph memory update: enabled; Zep updater sent all 24 activities in 6 batches with `failed=0`, then stopped cleanly after `close-env`.

Current post-run state:

- Stage 03 real run completed 30 rounds with 657 unique active agents, 1,089 Reddit actions, 764 Twitter actions, and 144 ballot-like actions.
- Stage 04 accepted report: `report_9c77ca2557ae`.
- Supplemental all-node/all-edge Zep panorama completed against `mirofish_4a9df9ae8b184878` with 973 nodes and 2,678 edges.
- The old real runner process is no longer alive, so true live interviews cannot be produced for `sim_974459649906`; this is documented by Step 5 live-unavailable artifacts.
- A separate capped smoke `sim_763e1e31b320` proved true live Step 5 IPC interviews with Twitter/Reddit transcripts before close-env.
- Final review packet: `backend/uploads/reports/report_9c77ca2557ae/review_packet_report_9c77ca2557ae.zip`.

## 1. Recommended Env / Model Shape

Recommended repo `.env` shape for the one-time run:

```env
LLM_API_KEY=<OpenRouter regular key>
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL_NAME=qwen/qwen3.6-plus

LLM_BOOST_API_KEY=<OpenRouter regular key or dedicated capped run key>
LLM_BOOST_BASE_URL=https://openrouter.ai/api/v1
LLM_BOOST_MODEL_NAME=deepseek/deepseek-v4-pro

ZEP_API_KEY=<Zep Cloud key>
OPENROUTER_MANAGEMENT_API_KEY=<OpenRouter management key>
```

Current repo `.env` is now in this quality-first shape. It currently has:

- `LLM_BASE_URL=https://openrouter.ai/api/v1`
- `LLM_MODEL_NAME=qwen/qwen3.6-plus`
- `LLM_BOOST_BASE_URL=https://openrouter.ai/api/v1`
- `LLM_BOOST_MODEL_NAME=deepseek/deepseek-v4-pro`
- OpenRouter, OpenRouter management, boost, and Zep keys are present, but values must not be printed.

Most recent guarded switch backup:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\.env.mirofish-backup-20260603T014719Z`

Current Qwen primary recommendation is `qwen/qwen3.6-plus` because the user clarified that model quality is first and cost value is a close second. `qwen/qwen-plus-2025-07-28:thinking` remains the cost-value Qwen fallback if the actual prepared config makes Qwen3.6 Plus too expensive.

## 2. Model Decision

Use OpenRouter for this run with explicit model lanes, not `openrouter/auto`.

Latest user update changed the plan from Gemini-first to Qwen-first. The main swarm model should be Qwen-shaped because this run values differentiated agents, high-throughput persona behavior, and creator-aligned social simulation economics more than a single high-reasoning market essay.

Qwen candidate metadata and realistic probe results:

| Candidate | Exact OpenRouter Slug | Price Per Token From OpenRouter Metadata | Probe Result | Latency | Notes |
| --- | --- | --- | --- | --- | --- |
| Qwen3.6 Plus | `qwen/qwen3.6-plus` | prompt `0.000000325`, completion `0.00000195` | Passed | 61.30s | Quality-first primary. Slower, but speed is not a selection priority. |
| Qwen3.5 Plus 2026-04-20 | `qwen/qwen3.5-plus-20260420` | prompt `0.0000003`, completion `0.0000018` | Passed | 86.94s | Grounded but slowest in this probe. |
| Qwen Plus 0728 Thinking | `qwen/qwen-plus-2025-07-28:thinking` | prompt `0.00000026`, completion `0.00000078` | Passed | 25.00s | Cost-value fallback with good grounding and cheaper output pricing. |

DeepSeek boost/contrarian probe results:

- `deepseek/deepseek-v4-pro` metadata: prompt `0.000000435`, completion `0.00000087`.
- Compact `max_tokens=650` probe failed because it spent the visible output budget poorly.
- Retest with `max_tokens=1200` produced visible Reddit/contrarian archetypes, false-positive risks, and validation tasks in 23.99s.
- Retest with `reasoning: { "exclude": true }` produced visible text in 39.84s while hiding reasoning from the response, but still consumed reasoning tokens.
- Retest with `reasoning: { "effort": "low", "exclude": true }` failed by spending the whole completion budget invisibly. Do not force this setting.

Gemini fallback status:

- `google/gemini-3-flash-preview` metadata: prompt `0.0000005`, completion/reasoning `0.000003`.
- Prior realistic probe passed in 1.39s and produced archetypes, narrative evolution, uncertainty/model-bias warnings, and TradingAgents validation implications.
- Keep as quality fallback if Qwen becomes generic, incoherent, unavailable, or weak in app-path graph/environment setup.

Direct Google `gemini-3.5-flash` is not clean enough for the unpatched MiroFish path right now. Default and low-effort direct probes produced almost no visible output under an 800-token budget; `reasoning_effort=minimal` produced coherent output but was slow and requires Gemini-specific request controls that MiroFish does not pass today.

Final recommendation:

- Primary/common swarm lane: `qwen/qwen3.6-plus`.
- Cost-value Qwen fallback: `qwen/qwen-plus-2025-07-28:thinking`.
- Boost/Reddit/contrarian lane: `deepseek/deepseek-v4-pro`.
- Cheap fallback: `deepseek/deepseek-v4-flash`.
- Quality fallback: `google/gemini-3-flash-preview`.
- Do not add any unapproved model family to the swarm default.
- Avoid OpenRouter Auto Router for the main simulation because explicit lanes are needed to know which model shaped which platform behavior.

## 3. Boost Route Status

Boost route exists and is active when `LLM_BOOST_API_KEY` is present.

Code path:

- Twitter / mainstream lane: `backend/scripts/run_parallel_simulation.py`, `run_twitter_simulation(...)`, calls `create_model(config, use_boost=False)`.
- Reddit / alternate social lane: `backend/scripts/run_parallel_simulation.py`, `run_reddit_simulation(...)`, calls `create_model(config, use_boost=True)`.
- `create_model(...)` reads `LLM_BOOST_API_KEY`, `LLM_BOOST_BASE_URL`, and `LLM_BOOST_MODEL_NAME`; if boost is absent, it falls back to normal `LLM_*`.

Recommended interpretation:

- Qwen primary = common social swarm, persona diversity, mainstream/Twitter-style narrative spread, map construction, environment setup, broad society simulation.
- DeepSeek V4 Pro boost = Reddit/contrarian/high-context social lane, skeptical false-positive discovery, alternate model-family perspective.
- Gemini 3 Flash Preview = quality fallback if Qwen is weak or if app-path setup needs stronger instruction following.

## 4. Deep Research Integration

Primary MiroFish content source:

- `C:\Users\Corbin\Downloads\deep-research-report (32).md`

This report has now been absorbed into the upload seed. It adds the key run logic: June 4 is a real regulatory change, but likely a broker-staggered medium retail-flow catalyst rather than a full market-structure break; the June 4-13 tape must also price payrolls, CPI, PPI, Treasury auctions, oil/geopolitics, Fed repricing, and AI/semiconductor events.

Supporting synthesis-only sources:

- `C:\Users\Corbin\Downloads\deep-research-report (31).md` - TradingAgents architecture and deterministic execution boundary.
- `C:\Users\Corbin\Downloads\deep-research-report (25).md` - Alpaca mechanics, paper/live mismatch, order validation, and PDT transition caveats.
- `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\TRADING_METHODS_AND_AUTOMATIONS.md`
- `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\CONTEXT_ROUTER.md`
- `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\tradingagents\research\market_mirror.py`
- `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main\tradingagents\research\market_structure.py`

Recommendation: upload only the seed to MiroFish for graph construction. Keep the broader TradingAgents reports for post-run Codex synthesis so the simulated world is not overloaded with trading-system architecture.

## 5. External Source Verification

Current primary-source checks performed on 2026-06-02:

- FINRA confirms the new intraday-margin requirements become effective June 4, 2026, with a brokerage transition period through October 20, 2027.
- FINRA confirms no old $25,000 PDT minimum and no trade-count PDT designation under the new risk-based framework, while intraday margin deficits and possible restrictions still matter.
- Robinhood says its margin accounts move to the new intraday-margin standard on June 4, with real-time monitoring and the $2,000 margin minimum still applying.
- Alpaca says it will implement on June 4 for Trading API users and Broker API partners, replace old PDT fields/logic, and use pre-trade checks.
- Schwab says the rules take effect June 4 but Schwab plans to stop counting day trades on June 8 and use real-time monitoring.
- Fidelity says it expects to align soon after June 4 and still requires the $2,000 margin-account minimum.
- Webull confirms the June 4 effective date but does not publicly pin its own implementation date on the checked help page.
- Robinhood and Interactive Brokers public pages confirm AI/agentic brokerage integration is no longer hypothetical, though rollout and safety controls vary.

## 6. Readiness Checks

| Check | Result | Notes |
| --- | --- | --- |
| MiroFish backend health | Passed | `http://localhost:5001/health` returned `{"service":"MiroFish Backend","status":"ok"}` on 2026-06-02 after these doc updates. |
| MiroFish frontend health | Passed | `http://localhost:3000` returned HTTP 200 on 2026-06-02 after these doc updates. |
| Read-only preflight checker | Passed | `python docs\mirror_fish\mirofish_preflight.py` found all planning artifacts, redacted keys present, backend/frontend healthy, no raw key patterns, and stage 03 gate closed. |
| Guarded `.env` model-route helper | Passed preview/apply | `python docs\mirror_fish\mirofish_env_gate.py` previews the Qwen/DeepSeek route without writing. The approved apply wrote a timestamped backup; restore requires `--confirm restore-mirofish-env`. |
| Creator workflow source audit | Passed | `python docs\mirror_fish\mirofish_workflow_audit.py --json` passed 43/43 static source checks across all five creator stages. It is read-only and keeps stage 03 closed. |
| Read-only actor-population audit | Passed | `python docs\mirror_fish\mirofish_actor_population_audit.py --json` passed against `sim_974459649906`: non-retail quota `580`, actual non-retail entity count `565`, required named agency/desk/media/developer/executive anchors present, all major initial-post layers present, and required final-report actor sections present in the prepared prompt. |
| Read-only readiness bundle | Updated | `python docs\mirror_fish\mirofish_readiness_bundle.py` bundles env preview, workflow audit, actor-population audit, preflight, actual prepared-config cost estimate, backend refresh proof, completion-audit status, objective alignment, and approval-gate ledger while keeping the real stage 03 run closed and final handoff draft-only. |
| Read-only completion audit | Updated | `python docs\mirror_fish\mirofish_completion_audit.py` checks each major objective requirement, now depends on the actor-population audit for non-retail routing proof, and explicitly keeps `safe_to_mark_goal_complete=false` until the real stage 03 run, stage 04 report, stage 05 deep interactions, Codex synthesis, and final handoff are done. |
| Guarded app-path setup helper | Added dry-run | `python docs\mirror_fish\mirofish_app_path_setup.py` previews the exact stage 01/02 app API calls and required confirmation phrases. Stage 01 execution requires `--confirm run-mirofish-stage01-setup`; stage 02 execution requires `--confirm run-mirofish-stage02-setup`. The helper has no stage 03 start action. |
| OpenRouter/Camel request controls | Passed no-network check | Optional env controls now flow into direct OpenAI SDK calls and Camel `ModelFactory` creation. A local constructor check produced `OpenRouterModel` with `max_tokens` plus OpenRouter `extra_body.reasoning/provider` config, without starting simulation or calling an API. The check also confirmed the repo `.env` model name controls the script path, which is why the applied Qwen/DeepSeek route matters. |
| Tiny upload/parsing | Pending approval | App endpoint `/api/graph/ontology/generate` invokes the primary LLM. Run only after explicit approval so the check uses the intended Qwen lane and records the project/graph ids. |
| Zep create/write/search | Partially passed | Direct MiroFish `GraphBuilderService` previously created graph `mirofish_b9c39b8d1a50483c` with one episode and extracted nodes/edges. Full app endpoint graph build should be re-run after final env shape. |
| Qwen primary candidates | Passed with caveat | `qwen/qwen3.6-plus`, `qwen/qwen3.5-plus-20260420`, and `qwen/qwen-plus-2025-07-28:thinking` all returned grounded Deep Research-seed outputs. Qwen3.6 Plus is the current primary recommendation because quality outranks speed; Qwen Plus 0728 Thinking is the cost-value fallback. |
| DeepSeek V4 Pro boost | Passed with caveat | `deepseek/deepseek-v4-pro` returned clean visible output when given enough token room. Do not force `reasoning.effort=low`; that variant returned no visible text in the retest. |
| Gemini quality fallback | Passed | OpenRouter `google/gemini-3-flash-preview` returned clean output in prior realistic probe. |
| Direct Google Gemini 3.5 | Failed for unpatched run | Direct `gemini-3.5-flash` only became usable with `reasoning_effort=minimal`, was slow, and still stopped by length. |
| OpenRouter admin MCP | Passed live tool check | Local Codex MCP `openrouter_admin` is visible in-session. Completion-key status passed, management-key status passed with 5 key metadata entries, and model lookup found the Qwen/DeepSeek/Gemini candidates. |
| Zep Cloud admin MCP | Passed live tool check | Local Codex MCP `zep_cloud_admin` is visible in-session. Project status reached Zep project `trading agents`; graph search against smoke graph `mirofish_b9c39b8d1a50483c` returned MiroFish/PDT smoke-test facts. The summary helper has an SDK-method limitation, so use search as the read-only proof path. |
| Codex config doctor | Passed | `CODEX_HOME=C:\cm codex --strict-config doctor --summary` returned 18 ok, 3 notes, 0 warn, 0 fail. |
| Output paths known | Passed | See section 11. |
| TradingAgents-main readable | Passed | Found PDT/intraday-margin docs and market mirror code. |

## 7. Source Connectivity Matrix

| Source | Available | Tiny Test | High-Level Result | Treat As |
| --- | --- | --- | --- | --- |
| General web/search | Yes | Passed | FINRA, broker pages, OpenRouter, and Google docs reachable. | Live/background evidence |
| FINRA / regulatory docs | Yes | Passed | Confirms June 4, 2026 effective date and Oct 20, 2027 transition period. | Primary evidence |
| Broker docs / commentary | Yes | Passed | Robinhood, Alpaca, Schwab, Fidelity, Webull, and tastylive checked for implementation and user-confusion details. | Implementation evidence |
| Reddit public web | Limited | Passed via web snippets/search | Public Reddit posts are visible through web search, but no dedicated MiroFish live Reddit ingestion is configured. | Sentiment context, not proof of capital flow |
| X/Twitter research MCP | Configured | Status passed | Docker read-only `twitter-research` reports configured with bearer token; query-shape test is pending because the CLI hides complex schema. | Optional live evidence if queried through MCP |
| MiroFish live social feeds | No | Repo inspection | MiroFish simulates Twitter/Reddit-like platforms through OASIS; it does not ingest live Reddit/X by default. | Simulated reaction only |
| TradingAgents-main | Yes | Passed | Repo docs and `market_mirror.py` are readable. | Local system context |
| Uploaded seed inside MiroFish | New seed prepared | Pending upload | Use `docs/mirror_fish/MIRROR_FISH_PDT_REALITY_SEED.md`. | Source of truth for simulation seed |

## 8. Exact Seed File / Report To Upload

Upload:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_PDT_REALITY_SEED.md`

This seed now contains:

- regulatory facts
- broker/platform rollout assumptions
- June 4-13 catalyst calendar
- retail, social, and AI-bot archetypes
- exposed instrument/theme buckets
- seven scenario branches
- false-positive risks
- validation tasks
- TradingAgents advisory boundary

## 9. Final Simulation Prompt To Paste Into MiroFish

Simulate the market-social reaction around the June 4, 2026 U.S. PDT-to-intraday-margin transition through the June 13 macro/options window. This is for an advisory TradingAgents research packet, not for direct trading.

Use the uploaded seed as the source of truth. Build a simulated society of U.S. retail traders, new small-account day traders, PDT-rule-confused traders, AI-bot users, prompt-engineered bot users, broker/API developers, cautious broker/platform users, options gamblers, 0DTE traders, systematic traders, contrarian liquidity-takers, hype accounts, and market-structure observers.

Also include first-class institutional and narrative actors, not just regular people: FINRA, SEC market-structure staff, FOMC/Fed macro voices, Treasury auction context, policy-maker commentary, broker/platform executives, compliance/legal teams, broker support desks, financial media outlets, newsletters, YouTube/TikTok explainers, Reddit/X communities, developer communities, API/tooling maintainers, bot-framework builders, AI-agent builders, tech executives, fintech founders, market makers, liquidity providers, ETF/index desks, prop desks, quant funds, hedge funds, asset managers, volatility desks, sell-side/electronic-execution desks, and risk managers.

Each layer should have distinct incentives, constraints, failure modes, and influence paths. Do not collapse government agencies, media outlets, developer communities, tech executives, institutional investors, and retail traders into one generic crowd. Some actors should trade; others should shape regulation, broker implementation, narrative spread, platform stability, liquidity, risk controls, or validation signals.

Focus on how narratives, confusion, overconfidence, risk misunderstandings, ticker attention, broker/platform constraints, AI-assisted automation, and macro catalysts evolve. Do not model June 4 as a universal broker switch. Do not assume "PDT is gone" means unlimited leverage. Do not ignore payrolls, CPI, PPI, Treasury auctions, oil/geopolitics, Fed repricing, or AI/semiconductor events.

Run at least these seven scenario branches:

1. Mostly narrative: broker rollout is fragmented and macro dominates, so the observable effect is modest.
2. Medium retail-flow effect: early broker/API rollout creates localized churn in SPY, QQQ, 0DTE/short-dated options, semis, and broker stocks.
3. Large speculative-flow effect: cooperative macro and AI news amplify rule-change hype into reflexive retail crowding.
4. Adverse macro override: hot payrolls/CPI/PPI, weak auctions, oil/geopolitical stress, or Fed repricing overwhelms the retail-flow story.
5. Valid-support branch: some crowd dip-buying is correct, so not all retail flow is bad signal.
6. Broker-friction branch: traders discover buying power, intraday margin deficits, settlement, and account state still block activity.
7. Bot-correlation branch: AI-assisted traders and simple bot stacks converge on the same obvious signals, compressing reaction time and increasing false-positive crowding.
8. Institutional-liquidity branch: market makers, quant funds, ETF desks, and prop desks adapt to novice clustering and either dampen, fade, or temporarily amplify the flow.
9. Policy/media-clarification branch: FINRA/SEC/broker explanations compete with viral simplified narratives and change behavior after the first wave of confusion.
10. Developer-infrastructure branch: broker APIs, bot frameworks, and AI-agent tooling accelerate both disciplined automation and brittle copycat behavior.

Target 1,000 agents, acceptable range 750-1,500. Target 30 rounds, acceptable range 25-35. Do not jump to 40-50 rounds unless readiness and cost estimates justify it. Use short-to-medium agent messages. Enable graph memory updates if stable. Preserve simulation environment/files after report generation for deep interaction and character interviews. Keep the final report long, structured, skeptical, and operational.

The final report must separate:

- what the simulated society strongly suggests
- what might be model bias
- what requires real market-data validation
- what should not be acted on directly

Required final sections:

- executive summary
- scenario probability map
- strongest simulated narratives
- weak or noisy signals
- false-positive patterns
- retail trader archetypes
- AI-bot and prompt-bot failure modes
- broker/platform confusion patterns
- government, regulator, and policy-maker reaction map
- institutional investor, market-maker, and liquidity-provider reaction map
- media outlet and influencer narrative map
- developer community, bot-framework, and broker API behavior map
- company and tech-executive narrative map
- ticker/category attention map
- macro override risks
- early-warning signals
- TradingAgents rule implications
- recommended validation tasks using real market data
- confidence levels
- machine-readable summary if practical

## 10. Run Shape And Cost Discipline

Recommended run shape:

- Target agents: 1,000.
- Acceptable agent range: 750-1,500.
- Target rounds: 30.
- Acceptable round range: 25-35.
- Use short-to-medium agent messages.
- Enable graph memory updates; the capped stress copy proved graph-memory startup, flushing, and clean shutdown.
- Preserve simulation environment/files after report generation for deep interaction and character interviews.

Why this shape:

- MiroFish's value is differentiated agents, social interaction, memory updates, platform dynamics, and ReportAgent analysis.
- The creator phrase "automatic demand analysis" is not implemented as a single endpoint name in this repo. Treat it as the combined source path of requirement analysis, generated time/event/agent configs, hot topics, narrative direction, platform action timelines, and ReportAgent follow-up tools.
- More agents matter because they create more perspectives, positions, and unusual reactions, but only if the seed and active turns stay grounded.
- Do not chase massive agent counts for spectacle. The run is high-quality only if the simulated society remains interpretable and the output becomes an advisory evidence packet for TradingAgents.

Cost estimate method:

- The simulation code selects active agents per round from `time_config.agents_per_hour_min` and `agents_per_hour_max`, with peak/off-peak multipliers.
- The prepared config activates 16-40 agents per simulated hour before multipliers after the predictive-quality patch, not the whole 1,000-agent population every round.
- With dual-platform simulation and 25-35 rounds, practical cost depends on active agent actions, generated message length, prompt history, and whether Qwen/DeepSeek reasoning or long outputs expand token use.
- Qwen3.6 Plus is materially more expensive than Qwen Plus 0728 Thinking, but quality is the first priority. Keep Qwen Plus 0728 Thinking as the cost-value fallback if the actual prepared config makes Qwen3.6 Plus cost balloon.
- The current concrete estimate from `backend\uploads\simulations\sim_974459649906\simulation_config.json` is:
  - Per-platform active-agent actions over 30 rounds: low 352, mid 629, high 893.
  - Dual-platform active-agent actions over 30 rounds: low 704, mid 1257, high 1786.
  - Expected unique active agents: mid 436 per platform, mid 647 dual-platform.
  - Stage 03 action-only LLM estimate: mid `$1.0703`, worst `$3.1300`.
  - Primary model share: mid `$0.5887`, worst `$1.7704`.
  - Boost model share: mid `$0.4816`, worst `$1.3596`.
- This is not a total project cap. Stage 01/02 already consumed separate LLM/Zep cost; stage 04 report, stage 05 interviews, graph memory operations, retries, and any longer-than-assumed outputs add cost.

## 11. Creator Workflow Sequence Checklist

We will follow the normal five-stage MiroFish workflow, not bypass it with a custom shortcut.

| Stage | Creator Workflow | MiroFish Path | Setup Status |
| --- | --- | --- | --- |
| 01 | Map construction: reality seed extraction, individual/group memory injection, GraphRAG construction | Upload `MIRROR_FISH_PDT_REALITY_SEED.md` through `/api/graph/ontology/generate`, then build graph through `/api/graph/build` using Zep Cloud | Complete for `proj_8ece728e49fe` / `mirofish_4a9df9ae8b184878`; graph build produced 48 chunks, 103 nodes, and 117 edges |
| 02 | Environment setup: entity relationship extraction, persona generation, environment configuration, agent injection, simulation parameters | `/api/simulation/prepare` generates config and profiles using graph entities and `OasisProfileGenerator`; writes `reddit_profiles.json`, `twitter_profiles.csv`, and `simulation_config.json` | Complete for `sim_974459649906`; initial 23 agents were expanded to a 1,000-agent runnable population with institutional/policy/media/developer/tech-exec layers |
| 03 | Start simulation: dual-platform parallel simulation, automatic demand analysis, dynamic time-series memory | `/api/simulation/start` runs Twitter + Reddit in parallel through `run_parallel_simulation.py`; `enable_graph_memory_update` starts `ZepGraphMemoryUpdater`; per-round `scheduled_events` context is injected into both lanes and logged as `round_event` | Real `sim_974459649906` completed 30 rounds; stress copy and launch-path integrity checks passed |
| 04 | Report generation: ReportAgent toolset and simulated-environment interaction | `/api/report/generate` creates ReportAgent report using graph/search/interview tools; artifacts saved under `backend/uploads/reports/<report_id>` | Complete; accepted report is `report_9c77ca2557ae` |
| 05 | Deep Interaction: chat with simulated characters and ReportAgent | `Step5Interaction.vue`, `/api/report/chat`, `/api/simulation/interview`, `/api/simulation/interview/batch`, `/api/simulation/interview/all` | ReportAgent/replay-deferred Step 5 exists for the old stopped run; true live IPC Step 5 is proven by capped smoke `sim_763e1e31b320` and requires preserving the runner command window for future real runs |

Operational note: stage 05 is only meaningful after stage 04 produces a report and after stage 03 has produced profiles/simulation DBs. We should not close/clean the simulation environment before any planned character interviews.

## 12. Expected Output Artifact Paths

MiroFish project and extracted seed:

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

## 13. Final Codex Extra-High Synthesis Plan

After MiroFish finishes, Codex should read:

- uploaded seed file
- MiroFish project metadata and extracted text
- simulation config
- simulation logs and platform DB summaries
- MiroFish generated report
- Zep graph data if available
- Deep Research reports listed in section 4
- TradingAgents docs and market-mirror/market-structure files listed in section 4

Codex output should produce:

- executive summary
- operational TradingAgents implications
- false-signal filters
- risk gates
- broker/platform confusion warnings
- ticker/category attention map
- validation tasks requiring real market data
- confidence scoring
- machine-readable summary JSON

Keep the synthesis explicitly advisory. No live orders, no paper orders, and no TradingAgents automation changes unless separately approved.

## 14. Final Deliverable Before Starting

Before stage 03 starts, the approval packet should include:

- exact `.env` model shape
- exact chosen Qwen slug and reason
- Qwen realistic probe result
- DeepSeek boost probe result
- fallback support status
- chosen agents/rounds
- exact seed file path
- final MiroFish simulation prompt path/text
- expected artifact output paths
- cost estimate from the prepared simulation config
- unresolved decisions
- explicit wait for user approval

Current approval packet:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_PRE_START_APPROVAL_PACKET.md`

Cost estimator:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_cost_estimator.py`

Read-only preflight checker:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_preflight.py`

Read-only readiness bundle:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_readiness_bundle.py`

Read-only actor-population audit:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_actor_population_audit.py`

Read-only completion audit:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_completion_audit.py`

Guarded app-path setup helper:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_app_path_setup.py`

## 15. Unresolved Decisions Affecting Output Quality

- Current repo `.env` model names are already switched to the recommended Qwen/DeepSeek shape; keep the rollback backup path available until launch is complete.
- Decide whether to create a dedicated capped OpenRouter run key via the management API before the real run.
- Do not re-run `python docs\mirror_fish\mirofish_env_gate.py --apply --confirm switch-mirofish-models` unless the route drifts; keep the generated backup path for rollback.
- Decide whether to keep `qwen/qwen3.6-plus` as the quality-first primary after the actual stage 02 config cost estimate, or fall back to `qwen/qwen-plus-2025-07-28:thinking` if cost value becomes poor.
- Optional model controls are now patched in as opt-in env knobs: `LLM_MODEL_PLATFORM`, `LLM_MAX_TOKENS`, `LLM_MAX_COMPLETION_TOKENS`, `LLM_MODEL_CONFIG_JSON`, `LLM_EXTRA_BODY_JSON`, and `LLM_REASONING_JSON`, with matching `LLM_BOOST_*` variants for the boost lane. Leave them unset unless the final pre-start approval explicitly chooses a cap or OpenRouter reasoning/provider body.
- Full app-path upload/ontology/graph build readiness remains pending explicit approval.
- X/Twitter live search can be used as external background only if queried separately through the Docker research MCP; MiroFish itself should not pretend it has live X/Reddit feeds.
- The plan is not complete until a fresh non-simulation smoke test verifies backend/frontend health and the seed can enter the graph-build path with the selected model.
- The final TradingAgents handoff is not sendable until stage 03 run, stage 04 report, stage 05 deep interactions/interviews, Codex synthesis, and this chat's final decisions are complete.

## 16. Codex-Side MCP Setup

Two local, secret-free MCP entries were added to `C:\cm\config.toml`:

- `openrouter_admin`: launched by `C:\cm\scripts\start-openrouter-admin-mcp.ps1`, server code at `C:\cm\mcp\openrouter-admin\server.py`.
- `zep_cloud_admin`: launched by `C:\cm\scripts\start-zep-cloud-admin-mcp.ps1`, server code at `C:\cm\mcp\zep-cloud-admin\server.py`.

The launchers load secrets from Windows User env, not from `config.toml`. Available tools are intentionally read-only/safe: OpenRouter completion key status, management-key metadata status, redacted key listing, model metadata lookup, small chat smoke test, Zep project status, Zep graph search, and Zep graph summary.

These tools are now visible in the current Codex session after tool discovery. Keep using them read-only unless the user explicitly approves account-management writes.

## Research Sources

- FINRA intraday margin guidance: https://syndication.finra.org/content/understanding-new-intraday-margin-requirements
- FINRA Regulatory Notice 26-10: https://www.finra.org/rules-guidance/notices/26-10
- Robinhood day trading support: https://robinhood.com/us/en/support/articles/day-trading/
- Robinhood agentic trading announcement: https://robinhood.com/us/en/newsroom/robinhood-is-now-open-to-agents/
- Alpaca PDT/intraday-margin framework: https://alpaca.markets/blog/finra-retires-the-pdt-rule-introducing-alpacas-new-intraday-margin-framework/
- Schwab PDT change overview: https://www.schwab.com/learn/story/sec-approves-scrapping-25000-day-trader-minimum
- Fidelity day-trading margin overview: https://www.fidelity.com/learning-center/trading-investing/trading/day-trading-margin
- Webull day trading rules: https://www.webull.com/help/faq/10954-Understanding-day-trading
- tastylive PDT change and 0DTE nuance: https://www.tastylive.com/news-insights/the-pdt-rule-is-gone-here-s-what-changes-on-june-4
- Interactive Brokers AI integration: https://www.interactivebrokers.com/en/general/about/mediaRelations/6-1-26.php
- Google Gemini model docs: https://ai.google.dev/gemini-api/docs/models
- OpenRouter quickstart: https://openrouter.ai/docs/quickstart
- OpenRouter model fallbacks: https://openrouter.ai/docs/guides/routing/model-fallbacks
- OpenRouter provider routing: https://openrouter.ai/docs/guides/routing/provider-selection
