# MiroFish PDT Run Operator Runbook

Generated: 2026-06-02
Updated: 2026-06-03

Do not start the real simulation until the user explicitly says the real stage 03 engine may start.

## 0. Current Prepared Run

- Project: `proj_8ece728e49fe`
- Graph: `mirofish_4a9df9ae8b184878`
- Simulation: `sim_974459649906`
- Prepared config: `C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\simulations\sim_974459649906\simulation_config.json`
- Prompt: `C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_PDT_SIMULATION_PROMPT.md`
- Real simulation status: `ready`; not started.

Stage 01/02 are already complete. The stage 02 config was expanded from the 23 app-generated profiles to 1,000 runnable OASIS agents. The actor mix includes retail traders plus broker/platform, developer/automation, media/narrative, policy/regulatory, institutional/liquidity, and tech-company/executive layers.

Capped stress proof:

- Stress copy: `sim_974459649906_stress2`
- Cap: 2 rounds
- Result: completed, 24 total actions across Twitter and Reddit.
- Zep graph memory update: 24 sent, 0 failed.

Remaining operator sequence:

1. Confirm backend/frontend/preflight still pass.
2. Review cost and actor-population audit. The actor audit must show non-retail quota `580`, actual non-retail entity count `565`, and passing government/policy, institutional/liquidity, media, developer/API, broker/company, tech-executive, and retail layers.
3. Wait for explicit user approval to start the real `sim_974459649906`.
4. Start stage 03 with graph memory enabled.
5. Preserve environment and files for stage 04 report plus stage 05 deep interactions.

## 1. Current Purpose

Run one high-quality MiroFish simulation for the June 4-13, 2026 PDT-to-intraday-margin market/social reaction window.

This is not a generic "retail traders go crazy" prompt. The simulation should test how differentiated trader groups behave when they believe day trading got easier while brokers still enforce real-time intraday-margin constraints and the market is also reacting to payrolls, CPI, PPI, Treasury auctions, oil/geopolitics, AI-semiconductor catalysts, and broker/platform rollout confusion.

Final output becomes advisory evidence for TradingAgents only. It must not trigger live orders, paper orders, or automation changes by itself.

The final TradingAgents handoff is not sendable during planning. It can be marked final only after the stage 03 run, stage 04 ReportAgent output, stage 05 deep interactions/interviews, Codex synthesis, and this chat's final user decisions are complete.

## 2. Files To Use

Primary MiroFish upload seed:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_PDT_REALITY_SEED.md`

Detailed readiness report:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_TRADING_RUN_READINESS.md`

Pre-start approval packet:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_PRE_START_APPROVAL_PACKET.md`

Cost estimator:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_cost_estimator.py`

Read-only preflight checker:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_preflight.py`

Guarded model-route switch helper:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_env_gate.py`

Read-only creator-workflow coverage audit:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_workflow_audit.py`

Read-only actor-population audit:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_actor_population_audit.py`

Read-only readiness bundle:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_readiness_bundle.py`

Read-only completion audit:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_completion_audit.py`

Guarded app-path setup helper:

`C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\mirofish_app_path_setup.py`

Deep Research source retained for synthesis:

`C:\Users\Corbin\Downloads\deep-research-report (32).md`

## 3. Model Plan

Recommended `.env` model lines:

```env
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL_NAME=qwen/qwen3.6-plus
LLM_BOOST_BASE_URL=https://openrouter.ai/api/v1
LLM_BOOST_MODEL_NAME=deepseek/deepseek-v4-pro
```

Optional request controls are available but should stay unset unless explicitly approved before launch:

```env
LLM_MODEL_PLATFORM=OPENROUTER
LLM_MAX_TOKENS=
LLM_MAX_COMPLETION_TOKENS=
LLM_MODEL_CONFIG_JSON=
LLM_EXTRA_BODY_JSON=
LLM_REASONING_JSON=
LLM_BOOST_MODEL_PLATFORM=OPENROUTER
LLM_BOOST_MAX_TOKENS=
LLM_BOOST_EXTRA_BODY_JSON=
```

Model roles:

- Qwen3.6 Plus: quality-first primary/common swarm lane.
- DeepSeek V4 Pro: Reddit/contrarian/false-positive lane.
- Qwen Plus 0728 Thinking: cost-value fallback if the prepared config cost is too high.
- DeepSeek V4 Flash: cheap fallback only.
- Gemini 3 Flash Preview: quality fallback if Qwen becomes weak or generic.

## 4. Required Readiness Before Stage 03

1. Confirm the current `.env` model route remains quality-first Qwen3.6 Plus plus DeepSeek V4 Pro.
2. Preview the exact `.env` model-route state:

```powershell
python docs\mirror_fish\mirofish_env_gate.py
```

3. If a future preview is not already correct, apply only the model-route lines with backup:

```powershell
python docs\mirror_fish\mirofish_env_gate.py --apply --confirm switch-mirofish-models
```

4. Restart or refresh backend so selected `.env` model names are active.
5. Re-check backend and frontend health.
6. Run the read-only preflight, actor-population audit, and completion audit.
7. Review the prepared population: `sim_974459649906` should have 1,000 agents, status `ready`, non-retail quota `580`, and actual non-retail entity count `565`.
8. Review the actual prepared-config cost estimate.
9. Confirm output paths are known.
10. Stop and ask for explicit user approval before the real stage 03 simulation start.

Rollback command if the model switch needs to be reverted before launch:

```powershell
python docs\mirror_fish\mirofish_env_gate.py --restore <backup_path> --confirm restore-mirofish-env
```

Read-only preflight command:

```powershell
python docs\mirror_fish\mirofish_preflight.py
```

Read-only workflow audit command:

```powershell
python docs\mirror_fish\mirofish_workflow_audit.py
```

Read-only actor-population audit command:

```powershell
python docs\mirror_fish\mirofish_actor_population_audit.py
```

Read-only readiness bundle command:

```powershell
python docs\mirror_fish\mirofish_readiness_bundle.py
```

Read-only completion audit command:

```powershell
python docs\mirror_fish\mirofish_completion_audit.py
```

Guarded app-path setup dry-run command:

```powershell
python docs\mirror_fish\mirofish_app_path_setup.py
```

Historical stage 01 app-path setup command, already completed for `proj_8ece728e49fe` / `mirofish_4a9df9ae8b184878`:

```powershell
python docs\mirror_fish\mirofish_app_path_setup.py --execute-stage01 --confirm run-mirofish-stage01-setup --wait
```

Historical stage 02 app-path setup command, already completed for `sim_974459649906`:

```powershell
python docs\mirror_fish\mirofish_app_path_setup.py --execute-stage02 --project-id proj_8ece728e49fe --graph-id mirofish_4a9df9ae8b184878 --confirm run-mirofish-stage02-setup --wait
```

The setup helper has no stage 03 start action. Stage 03 must be started separately only after explicit user approval.

The readiness bundle collects env preview, workflow audit, actor-population audit, preflight, actual prepared-config cost, backend refresh proof, completion-audit status, objective-alignment status, an approval-gate ledger, closed real-stage-03 gate, and draft-only handoff status. The completion audit must say `safe_to_mark_goal_complete=false` until the real stage 03 run, report, deep interactions, synthesis, and final handoff are complete. The workflow audit verifies local source coverage for all five creator stages. It also documents that "automatic demand analysis" is represented by automated requirement analysis, generated time/event/agent configs, hot topics, narrative direction, and ReportAgent tools rather than a single endpoint named demand analysis.

## 5. Target Run Shape

- Target agents: 1,000.
- Acceptable range: 750-1,500.
- Target rounds: 30.
- Acceptable range: 25-35.
- Use short-to-medium agent messages.
- Enable graph memory updates; the capped stress copy proved the updater path.
- Preserve simulation files/environment after report generation for deep interaction and character interviews.

## 6. Scenario Branches To Encode

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

## 7. Success Criteria

The final MiroFish output should include:

- executive summary
- scenario branch comparison
- June 4-13 timeline
- trader archetype behavior
- narrative spread dynamics
- platform/channel differences
- broker confusion patterns
- government, regulator, and policy-maker reaction map
- institutional investor, market-maker, and liquidity-provider reaction map
- media outlet and influencer narrative map
- developer community, bot-framework, and broker API behavior map
- company and tech-executive narrative map
- AI-bot user behavior
- ticker/category attention map
- false-positive patterns
- early-warning signals
- daily validation checklist
- confidence/uncertainty
- machine-readable advisory packet if practical
- preserved environment for ReportAgent and character interviews

Weak output warning signs:

- It only says retail traders will be emotional.
- It only says AI stocks may move.
- It treats PDT removal as unlimited leverage.
- It ignores broker-staggered rollout.
- It ignores regulators, policy makers, media outlets, developer communities, tech executives, or institutional liquidity providers.
- It ignores macro/rates/oil/AI catalyst competition.
- It gives generic finance commentary without social dynamics.

## 8. Approval Packet Before Real Simulation

Before starting stage 03, report:

- exact `.env` model shape
- exact chosen Qwen slug and why
- Qwen realistic probe result
- DeepSeek boost probe result
- fallback support status
- chosen agents/rounds
- exact seed file path
- final MiroFish simulation prompt path/text
- expected artifact output paths
- cost estimate
- unresolved decisions
- explicit wait for user approval

Do not write or send the final TradingAgents handoff from this pre-start packet. The handoff remains draft-only until the full run and chat closeout are complete.
