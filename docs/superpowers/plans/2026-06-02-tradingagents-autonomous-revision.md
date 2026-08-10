# TradingAgents Autonomous Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` for multi-file implementation slices or `superpowers:executing-plans` for inline execution. This file is the approved source of truth for the repo-wide build. Update checkboxes as work lands.

**Goal:** Finish the TradingAgents repo-wide revision into a safe, autonomous, evidence-first equity trading system with deterministic paper/live gates, clear exception emails, a pullback-support paper sleeve, advisory research intelligence, cloud/local knowledge memory, social/crawler evidence, cost-aware model routing, and performance tracking over time.

**Architecture:** Keep the trading path deterministic and fail-closed. Research, Crawlee/Playwright crawls, social/anomaly signals, Composio/Docker/Codex tool outputs, local/Gemini model output, graph memory, and MiroFish-inspired market-mirror simulations produce packetized evidence only; policy and Alpaca live gates remain the only authority near order submission. Build the core paper loop first, then promotion/live gates, then tiny-live behind the full gate stack.

**Tech Stack:** Python 3.10+, Typer CLI, Pydantic schemas, existing Alpaca broker layer, existing result packets, Crawlee + Playwright for crawler runs, optional Zep free-tier memory via `ZEP_API_KEY`, local SQLite/JSONL memory fallback, Gemini via `GOOGLE_API_KEY`/`GEMINI_API_KEY` as capped paid fallback, local/Ollama/free paths as default fallbacks, and the 2019 Intel i9 MacBook as an optional overnight local-model research mule reachable through Tailscale when awake.

---

## Non-Negotiable Defaults

- **No uncontrolled paid runtime.** Scheduled repo automations default to deterministic/free/local execution. Gemini can be used first only behind explicit budget caps and telemetry. OpenAI API stays disabled by default unless later armed.
- **No secret values in repo.** Keys live in Windows user environment or ignored `.env`; code and docs mention only variable names.
- **No AGPL contamination.** MiroFish is methodology inspiration only. Do not copy code, schemas, prompts, tests, or distinctive implementation from AGPL repos.
- **Research is not execution.** Crawlers, Composio, Browser, social feeds, local models, Gemini, Zep, and market-mirror outputs cannot create, size, approve, or submit live orders.
- **Tool output must become evidence first.** Composio, Docker MCP, Browser, Codex subagents, and external connectors are allowed to help research, but scheduled trading code consumes only normalized packets, never raw tool authority.
- **Ops-only human approval.** Emails may ask for configuration, credentials, risk-envelope, kill/freeze, or setup decisions. They must not ask for per-trade or per-promotion approval.
- **Operator emails explain like a clear teenager-level brief.** Keep important numbers and blockers, but explain what happened plainly, say what the bot already did, say what Codex will self-heal next, and ask only a simple ops-approval question when a decision is truly needed.
- **Live remains tiny-live only, with uncapped autonomous live budget.** Existing `live_now` style actions stay blocked. When `config/risk_envelope.yaml` opts into `live_budget_mode: autonomous_uncapped`, the promoted sleeve may choose live order size without repo dollar caps or per-trade approval, but broker buying power, live control, promotion, reconciliation, stock-only, and limit-only gates still apply.
- **Use the June 4, 2026 intraday-margin regime now.** Do not add or preserve old PDT blockers based on 3 day trades in 5 business days, the old `$25,000` PDT minimum, PDT designation, or old day-trading-buying-power logic. Alpaca/FINRA intraday margin and broker buying power/account checks still matter, and the market-structure transition should make research more skeptical of crowd/AI-bot spike-chasing.
- **Cash default.** Every branch must be able to emit `HOLD_CASH` with a packet.
- **Risk can be performance-seeking only inside rails.** `performance_seeking` may widen paper exploration, top-N research, and tiny-live candidate evaluation inside numeric caps; it never waives freshness, dry-run, reconciliation, stock-only, limit-only, risk envelope, promotion, or live-gate checks.
- **The Intel Mac is a research worker, not an execution worker.** It may run Ollama, crawlers, GPT Researcher/Open WebUI-style tooling, and long local-model reports. It must not hold broker credentials, Composio/social write authority, or direct live-order capability.

---

## Current Source Of Truth

- Governing handoff: `CODEX_HANDOFF_PROMPT.md`.
- Detailed spec: `CODEX_IMPLEMENTATION_SPEC.md`.
- Original foundation package: `C:\Users\Corbin\Downloads\SEND_THIS_TO_CODEX_TradingAgents_Final_Handoff.zip`.
  - `FINAL_MERGED_IMPLEMENTATION_PLAN.md`: foundation sprint first, then SEC/FRED/ETF/policy/pullback/tournament/overnight/supervisor queue.
  - `source_reports/DR1_AUTONOMOUS_TRADING_BOT_RESEARCH_BLUEPRINT_EXTRACTED.md`: point-in-time discipline, local research store, validation, deterministic policy, promotion gates.
  - `source_reports/LANE2_FREE_ALPHA_DATA_SERVICE_DISCOVERY.md`: free official data and social/source queue.
  - `source_reports/LANE3_METHODOLOGY_DESTRUCTIVE_REDESIGN.md`: trade-intent pipeline, pullback-support rewrite, sleeve methodology, shadow migration.
  - `supporting_context/CURRENT_SYSTEM_CONTEXT_PACK.md`: current automation/runtime/strategy context.
- Fast orientation: `AGENTS.md` then `CONTEXT_ROUTER.md`.
- Existing safety foundation to preserve:
  - `tradingagents/policy/live_gate.py`
  - `tradingagents/policy/risk_envelope.py`
  - `tradingagents/policy/live_control.py`
  - `tradingagents/schemas/trading.py`
  - `tradingagents/policy/packets.py`
  - `tradingagents/sleeves/pullback_support.py`
  - `config/risk_envelope.example.yaml`
- Most useful focused green slice already seen:
  - `uv run --with pytest python -m pytest tests/test_live_gate.py tests/test_policy_foundation.py tests/test_alpaca_supervisor.py::test_alert_classifier_separates_routine_notable_and_critical tests/test_alpaca_supervisor.py::test_critical_alert_serializes_clear_exception_email tests/test_alpaca_supervisor.py::test_portfolio_snapshot_and_daily_digest_formats_key_balances_and_gains -q`
- Latest focused green slice:
  - `uv run --with pytest python -m pytest tests/test_model_routing.py tests/test_research_automation_orchestrator.py tests/test_research_provider_orchestrator.py tests/test_agent_intelligence_ledger.py tests/test_paper_tournament.py::test_alphainsider_paper_watch_uses_only_remaining_paper_budget tests/test_paper_tournament.py::test_paper_tournament_alphainsider_watch_writes_paper_only_packet tests/test_alpaca_cli.py::test_research_agent_ledger_from_overnight_writes_forecasts tests/test_alpaca_cli.py::test_research_agent_ledger_summary_includes_influence_weights -q`
  - Result: 27 passed.
- Latest safety/email/strategy slice:
  - `uv run --with pytest python -m pytest tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py::test_alpaca_supervisor_daily_report_includes_balances_and_positions tests/test_alpaca_cli.py::test_daily_report_includes_latest_premarket_brief -q`
  - Result: 40 passed.
  - Also passed: live cap removal focused suites across `tests/test_alpaca_supervisor.py`, `tests/test_live_gate.py`, and `tests/test_alpaca_execution.py`.
  - Daily report clarity follow-up:
    - Real daily report render against current packets now says `Problem: none` after later clean packets instead of presenting historical blockers as current blockers.
    - Historical old-cap blocker math is translated to a short cleared note.
    - Sell-to-close submitted orders render as `sell qty ...` instead of `$0.00`.
    - Submitted-order status is labeled as packet-time status.
    - Real rendered daily report was reduced to 59 lines while keeping live/paper money, holdings, open orders, submitted orders, cleared issue, top dip candidates, and ops need.
    - `uv run --with pytest python -m pytest tests/test_alpaca_supervisor.py tests/test_alpaca_cli.py::test_alpaca_supervisor_daily_report_includes_balances_and_positions tests/test_alpaca_cli.py::test_daily_report_includes_latest_premarket_brief -q`
    - Result: 43 passed.
  - 2026-06-02 live follow-through proof:
    - `.\.venv\Scripts\tradingagents.exe alpaca supervise-hourly --submit-actions --json-output --notification-policy urgent-exceptions --log-dir results/hourly_supervisor --overnight-log-dir results/overnight_plans --paper-tournament-log-dir results/paper_strategy_tournament --premarket-brief-log-dir results/premarket_briefs`
    - Result: no issues, no old live-cap blocker, submitted live AVGO sell-to-close after a green spike.
    - Packet: `results/hourly_supervisor/hourly-supervisor-20260602-181457-426090.json`.
    - Broker check by client order id confirmed Alpaca filled AVGO at `472.76`; post-fill live open order count was `0`.
    - Follow-up profit-taking pass also found no issues and submitted live NVDA sell-to-close.
    - Packet: `results/hourly_supervisor/hourly-supervisor-20260602-183155-682968.json`.
    - Broker check by client order id confirmed Alpaca filled NVDA at about `223.114`; post-fill live holdings were ORCL and TSM only, with open order count `0`.
  - Latest post-submit focused suite:
    - `uv run --with pytest python -m pytest tests/test_alpaca_supervisor.py tests/test_live_gate.py tests/test_alpaca_execution.py tests/test_market_verification.py tests/test_token_context_hooks.py tests/test_n8n_runner_policy.py -q`
    - Result: 82 passed.
- Latest hook/n8n POC slice:
  - `uv run --with pytest python -m pytest tests/test_token_context_hooks.py tests/test_n8n_runner_policy.py -q`
  - Result: 8 passed.
  - Real no-trade proofs:
    - `.venv\Scripts\python.exe .codex\hooks\token_context_hook.py` with a fake secret payload wrote a redacted hook event packet.
    - `.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job context_snapshot --json` refreshed compact context with `submit_capable=false`.
    - `.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job daily_report_preview --json` returned `submit_capable=false`, `Problem: none`, body line count `63`, live spent today `$88.23`, paper spent today `$0.00`.
    - `.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job process_review --json` returned `submit_capable=false`, `unchecked_step_count=0`, and packet `results\process_reviews\process-review-20260602-201316.json`.
  - Latest refreshed process review after email/anti-chase slice: `results\process_reviews\process-review-20260602-205858.json`, still `submit_capable=false`, `unchecked_step_count=0`, and `can_submit_orders=false`.
- Latest email clarity eval slice:
  - Added `tradingagents/evals/email_clarity.py` plus `research email-clarity-eval`.
  - n8n `daily_report_preview` now includes compact `email_clarity` status, score, issue count, and warnings.
  - The evaluator fails emails that are too long, miss the plain-English/account/money/problem/need sections, include old cap math like `cap $100`, use programmer repair language, or ask for trade-level approval.
  - Focused proof: `uv run --with pytest python -m pytest tests/test_email_clarity_eval.py tests/test_n8n_runner_policy.py tests/test_alpaca_supervisor.py::test_daily_digest_explains_uncapped_live_budget_without_cap_room tests/test_alpaca_supervisor.py::test_daily_digest_clears_historical_blocker_after_later_clean_packet -q`
  - Result: 13 passed.
  - Compile proof: `python -m py_compile tradingagents\evals\email_clarity.py tradingagents\orchestration\n8n_runner.py cli\main.py`.
  - Real n8n proof: `daily_report_preview` returned `submit_capable=false`, `Problem: none`, body line count `65`, `email_clarity.status=pass`, `score=100`, live spent today `$114.99`, and paper spent today `$0.00`.
- Latest anti-chase trading guard slice:
  - `build_hourly_decision` now refuses buy entries when the top candidate is a green-spike/chase setup, even if an upstream research layer marks it time-sensitive.
  - Replacement buys after closing a loser now also require a non-chase entry; otherwise the bot closes the loser and keeps the freed money in cash.
  - Controlled-dip buys and sell-the-spike profit taking remain allowed.
  - Focused proof: `uv run --with pytest python -m pytest tests/test_alpaca_supervisor.py::test_build_candidate_signals_prefers_controlled_dip_over_green_spike tests/test_alpaca_supervisor.py::test_aggressive_decision_can_live_buy_time_sensitive_controlled_dip tests/test_alpaca_supervisor.py::test_aggressive_decision_refuses_green_spike_chase_buy tests/test_alpaca_supervisor.py::test_loss_close_holds_cash_instead_of_rotating_into_green_spike tests/test_alpaca_supervisor.py::test_hourly_decision_sells_profit_spike_instead_of_only_reviewing -q`
  - Result: 5 passed.
  - Combined slice proof: `uv run --with pytest python -m pytest tests/test_email_clarity_eval.py tests/test_n8n_runner_policy.py tests/test_alpaca_supervisor.py::test_build_candidate_signals_prefers_controlled_dip_over_green_spike tests/test_alpaca_supervisor.py::test_aggressive_decision_can_live_buy_time_sensitive_controlled_dip tests/test_alpaca_supervisor.py::test_aggressive_decision_refuses_green_spike_chase_buy tests/test_alpaca_supervisor.py::test_loss_close_holds_cash_instead_of_rotating_into_green_spike tests/test_alpaca_supervisor.py::test_hourly_decision_sells_profit_spike_instead_of_only_reviewing tests/test_alpaca_supervisor.py::test_daily_digest_explains_uncapped_live_budget_without_cap_room tests/test_alpaca_supervisor.py::test_daily_digest_clears_historical_blocker_after_later_clean_packet -q`
  - Result: 18 passed.
- Latest live-budget / June 4 market-structure slice:
  - Uncapped live budget now treats broker `buying_power` as spendable room on top of existing live holdings, so stale old-cap packets cannot shrink active live room back to `$100`.
  - Hourly supervisor evidence now states the old PDT day-count, old `$25k` PDT minimum, and old day-trading-buying-power gates are ignored under the June 4, 2026 intraday-margin regime.
  - Overnight research context now includes `market_structure_policy` with PDT-reform/intraday-margin planner flags.
  - Market mirror now includes `AI-bot day trader` and `new retail intraday trader after PDT reform` actors for crowd-reaction simulation.
  - Focused proof: `uv run --with pytest python -m pytest tests/test_alpaca_cli.py::test_uncapped_live_budget_uses_broker_buying_power_even_after_prior_issue tests/test_alpaca_supervisor.py::test_hourly_evidence_separates_baseline_from_delta tests/test_research_crawler_social.py::test_intraday_margin_market_structure_packet_removes_old_pdt_gates tests/test_research_crawler_social.py::test_overnight_research_context_includes_market_structure_transition tests/test_market_mirror_memory.py::test_market_mirror_includes_pdt_reform_crowd_actors tests/test_n8n_runner_policy.py -q`
  - Result: 12 passed.
  - Compile proof: `python -m py_compile cli\main.py tradingagents\brokers\alpaca_supervisor.py tradingagents\research\market_structure.py tradingagents\research\overnight_context.py tradingagents\research\market_mirror.py`.
- Latest independent execution / BOARD review slice:
  - Loss exits no longer create same-run replacement buys. The close action emits `HOLD_CASH`, so freed money waits for a separate clean dip/support setup.
  - Sell-side and buy-side decisions are independent: profit-taking sells can proceed, loss exits free cash, and buys must qualify on their own evidence instead of being paired to whatever was just sold.
  - The new analysis-only BOARD review (`research execution-board-review`) scans recent hourly packets for paired live sell+buy plans, chase buys, buy-without-dip evidence, loss exits, unsafe broker statuses, and negative live P/L.
  - If the latest BOARD recommendation is `pause_new_buys_and_review`, hourly supervision pauses new buy actions while preserving independent sell decisions and writes compact BOARD evidence into the hourly packet.
  - n8n allowlist now includes `execution_board_review` as `submit_capable=false`, and `automation_context_snapshot.py` summarizes the latest BOARD packet under compact context.
  - Real current BOARD result: `results\execution_board\execution-board-review-20260602-215706.json` reviewed 24 hourly packets, found 19 hard issues and 14 warnings from older packets, and recommended `pause_new_buys_and_review`.
  - Focused proof: `uv run --with pytest python -m pytest tests/test_execution_board.py tests/test_n8n_runner_policy.py tests/test_automation_context_snapshot.py tests/test_alpaca_supervisor.py::test_hourly_decision_closes_position_at_risk_threshold tests/test_alpaca_supervisor.py::test_loss_close_holds_cash_instead_of_rotating_into_green_spike tests/test_alpaca_supervisor.py::test_loss_close_holds_cash_even_when_clean_dip_candidate_exists tests/test_alpaca_supervisor.py::test_board_pause_blocks_new_buys_but_keeps_decision_packet_material tests/test_alpaca_supervisor.py::test_aggressive_decision_can_live_buy_time_sensitive_controlled_dip tests/test_alpaca_supervisor.py::test_aggressive_decision_refuses_green_spike_chase_buy tests/test_alpaca_supervisor.py::test_hourly_decision_sells_profit_spike_instead_of_only_reviewing tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_live_submit_uses_tiny_live_idempotency_key tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_honors_board_pause_for_new_buys tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_live_buy_requires_submit_guard tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_tiny_live_guard_blocks_reconciliation_mismatch tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_duplicate_tiny_live_id_blocks_for_reconcile tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_blocks_when_latest_live_packet_order_is_missing -q`
  - Result: 27 passed.
  - Wider CLI proof: `uv run --with pytest python -m pytest tests/test_alpaca_cli.py -q`
  - Result: 53 passed.
  - Compile proof: `python -m py_compile tradingagents\evals\execution_board.py tradingagents\brokers\alpaca_supervisor.py tradingagents\orchestration\n8n_runner.py scripts\automation_context_snapshot.py cli\main.py`.
  - Real n8n proof: `.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job execution_board_review --json` returned `submit_capable=false`, `recommendation=pause_new_buys_and_review`, 24 packets, 8 submitted orders, 19 violations, and 14 warnings.
  - Compact context refreshed with `.venv\Scripts\python.exe scripts\automation_context_snapshot.py --write`.
- Latest automation controller slice:
  - Added Codex automation `tradingagents-night-shift-supervisor`.
  - It patrols the overnight window every few hours, inspects automation configs and compact context, keeps high-frequency hourly/paper jobs paused overnight, keeps useful overnight planning active, keeps fixed market-window jobs ready for trading days, and reports follow-up jobs separately.
  - The night-shift supervisor is controller-only: it must not run TradingAgents trading commands, submit orders, send emails, or edit repo files.
  - Updated sleep and wake controller prompts so they recognize `tradingagents-night-shift-supervisor` as a controller and classify `fetch-tradingagents-deep-research-report` as a one-off Browser/report heartbeat instead of an unknown TradingAgents job.
  - Verified current automation status: hourly supervisor and paper tournament are `PAUSED`; overnight planning, market-window jobs, daily report, sleep/wake controllers, night-shift supervisor, and the Deep Research follow-up are `ACTIVE`.
- Latest promotion-state cleanup:
  - Current `results\policy\promotion_state.json` now has top-level `schema_version: 1.0.0`.
  - Added regression coverage so `write_promotion_state` and `build_promotion_state` keep emitting the versioned live-gate shape.
  - Focused proof: `uv run --with pytest python -m pytest tests/test_promotion_policy.py tests/test_automation_context_snapshot.py -q`
  - Result: 6 passed.
  - Compact context was refreshed after the change. Promotion state still appears in `latest-flags.json` because `current-aggressive` is live-enabled, not because the packet is malformed.
- Latest automation-index hardening:
  - `scripts/automation_context_snapshot.py` now includes `tradingagents-night-shift-supervisor` in the managed automation set.
  - The automation index now discovers all `C:\cm\automations\*\automation.toml` files, classifies them as controller, market-day, hourly/paper, overnight research, daily report, one-off follow-up, n8n/hook, unknown TradingAgents, or other.
  - `fetch-tradingagents-deep-research-report` is now a known `one_off_followup`, not an unknown scheduler.
  - Generated `results\_context\automation-index.json` now reports `automation_count=12`, classification counts, known follow-ups, and zero unknown/unmanaged TradingAgents automations.
  - Re-verified live automation configs on 2026-06-02: the night-shift, wake, and sleep controllers all know about the Deep Research follow-up and keep controller-only rules in their prompts.
  - Focused proof: `uv run --with pytest python -m pytest tests/test_automation_context_snapshot.py -q`
  - Result: 4 passed.
  - Compile proof: `python -m py_compile scripts\automation_context_snapshot.py`.
- Latest model-telemetry clarity slice:
  - Model telemetry reports now aggregate blocked routes into `blocked_route_summaries` with plain-English status and self-heal actions.
  - The report now includes `operator_summary` so emails/supervisors can say what is happening without raw model-routing jargon.
  - `automation_context_snapshot.py` now carries compact model fields: `operator_summary`, `blocked_route_count`, and `blocked_routes`.
  - Current real report says 2 local routes are blocked: `mac_ollama_research_mule` and `windows_local_ollama`; resolved runs are `0/16`; estimated spend is `$0.0000`; deterministic/free fallback remains the right default.
  - Daily report rendering now uses the model `operator_summary` when available instead of making Corbin read raw usefulness/outcome count maps.
  - Daily report rendering also reads the latest BOARD packet and translates `pause_new_buys_and_review` as: new buys paused, sells still work independently, and fresh buys wait for cleaner dip/support evidence.
  - Daily report wording now says `Paper tournament leader` instead of the less clear `Paper strategy` label.
  - Daily email bodies are now shorter by default: redundant `To`/`Subject` lines are removed from the body, submitted-order lines hide client IDs, only the first five submitted orders are shown, live account money is collapsed into fewer lines, and long decimal telemetry in the decision reason is rounded for humans.
  - The email clarity gate now caps daily reports at 60 lines instead of 75.
  - Focused proof: `uv run --with pytest python -m pytest tests/test_model_routing.py::test_model_telemetry_rollup_dedupes_latest_and_tracks_budget tests/test_model_routing.py::test_model_telemetry_rollup_tracks_usefulness_and_outcomes tests/test_model_routing.py::test_model_telemetry_rollup_explains_blocked_local_routes tests/test_model_routing.py::test_model_upgrade_recommendation_requires_history_and_never_auto_upgrades tests/test_automation_context_snapshot.py -q`
  - Result: 7 passed.
  - Real refresh proof: `.venv\Scripts\python.exe -m cli.main research model-telemetry-report --json-output` wrote `results\model_telemetry_reports\model-telemetry-report-20260602-222753-845114.json`, then compact context was refreshed.
  - Focused email proof: `uv run --with pytest python -m pytest tests/test_paper_tournament.py::test_daily_report_includes_paper_tournament_leader tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_daily_report_json tests/test_email_clarity_eval.py -q`
  - Result: 6 passed.
  - Stricter focused email proof: `uv run --with pytest python -m pytest tests/test_alpaca_supervisor.py::test_portfolio_snapshot_and_daily_digest_formats_key_balances_and_gains tests/test_alpaca_supervisor.py::test_daily_digest_excludes_rejected_orders_from_spent_today tests/test_alpaca_supervisor.py::test_daily_digest_formats_sell_to_close_as_quantity_not_zero_spend tests/test_paper_tournament.py::test_daily_report_includes_paper_tournament_leader tests/test_email_clarity_eval.py tests/test_n8n_runner_policy.py::test_n8n_runner_summarizes_daily_report_json -q`
  - Result: 9 passed.
  - Real n8n daily report preview proof: `.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job daily_report_preview --json` returned `body_line_count=55`, `email_clarity.status=pass`, `score=100`, `submit_capable=false`, `Problem: none`, live spent `$114.99`, and paper spent `$0.00`.
  - n8n daily preview parsed summaries now expose `model_telemetry`, `board_review`, and `board_new_buys_paused` so dashboards/controllers can show “no owner blocker” separately from “new buys paused by BOARD review.”
  - Focused n8n summary proof: `uv run --with pytest python -m pytest tests/test_n8n_runner_policy.py tests/test_email_clarity_eval.py -q`
  - Result: 12 passed.
  - Real n8n parsed-summary proof: `daily_report_preview` returned `board_new_buys_paused=true`, the full BOARD review line, the model telemetry line, `body_line_count=55`, and `email_clarity.score=100`.
  - Compile proof: `python -m py_compile cli\main.py scripts\automation_context_snapshot.py`.
  - Process-review proof after tightening: `.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job process_review --json` wrote `results\process_reviews\process-review-20260602-231206.json`, returned `unchecked_step_count=0`, `can_submit_orders=false`, `submit_capable=false`, and only repeated the known finding that raw packets are token hotspots.
  - Process-review proof after n8n parsed-summary update: `.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job process_review --json` wrote `results\process_reviews\process-review-20260602-231819.json`, returned `unchecked_step_count=0`, `can_submit_orders=false`, `submit_capable=false`, and only repeated the known raw-packet token hotspot.
- Latest research-batch context flag cleanup:
  - `automation_context_snapshot.py` no longer treats `quality_gates.fallback_required=false` as a failed gate.
  - Missing optional local workers are now `advisory_missing_gates` when deterministic helpers, judgment route, source breadth, and overall research quality are ready.
  - Current compact context now keeps `research_batch` unflagged: status `success`, `failed_quality_gates=[]`, `advisory_missing_gates=["at_least_one_local_worker_ready"]`.
  - Focused proof: `uv run --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_model_routing.py::test_model_telemetry_rollup_explains_blocked_local_routes -q`
  - Result: 5 passed.
  - Compile proof: `python -m py_compile scripts\automation_context_snapshot.py tradingagents\research\model_telemetry.py`.

---

## Phase 0 - Plan, Goal Anchor, Environment, And Capability Baseline

**Files:**
- Create/update: `docs/superpowers/plans/2026-06-02-tradingagents-autonomous-revision.md`
- Create/update: `reports/research_merge/FINAL_TRADINGAGENTS_RESEARCH_MERGE_PLAN.md`
- Create/update: `reports/research_merge/LIVE_SENSITIVE_PATH_MAP.md`
- Create/update: `reports/research_merge/NEXT_BATCH_QUEUE.md`
- Create/update: `reports/research_merge/BATCH_1_HANDOFF.md`
- Create/update: `reports/research_merge/FOUNDATION_MASTER_MAP.md`
- Inspect only: `C:\cm\config.toml`, `.env`, `.gitignore`, `AGENTS.md`, `CONTEXT_ROUTER.md`

- [x] **Step 0.1: Write this durable plan file**
  - The plan itself is the approved execution artifact.
  - Keep it current as the repo changes.
  - Read `reports/research_merge/FOUNDATION_MASTER_MAP.md` before continuing any new implementation slice. It explains the system in operator-friendly language and records the current checkpoint.

- [x] **Step 0.2: Store new secrets outside the repo**
  - User-level env vars are the intended home:
    - `GOOGLE_API_KEY`
    - `GEMINI_API_KEY`
    - `GEMINI_PROJECT_NAME`
    - `ZEP_API_KEY`
  - Verification prints only presence and length, never values.

- [x] **Step 0.3: Add a no-secret environment audit command**
  - Add a CLI or script helper that reports required env vars as `{present, length, source}` without values.
  - Include Composio/Docker profile status as names only.
  - Do not print token prefixes.

- [x] **Step 0.4: Baseline connected tool posture**
  - Confirm Docker MCP `profile` servers: `memory`, `twitter-research`, `fetch`, `duckduckgo`, `playwright`, `youtube_transcript`, `github-official`.
  - Confirm Composio active toolkits by name only.
  - Record a packet under `results/capability_audits/` with no secrets.
  - Latest packet: `results/capability_audits/connection-baseline-20260602-manual.json`.
  - Note: current process has a short `GOOGLE_API_KEY` while Windows user env has the full Gemini key length; prefer `GEMINI_API_KEY` or fresh shell for Gemini routing.

- [x] **Step 0.5: Preserve the original foundation sprint artifacts**
  - Write `reports/research_merge/FINAL_TRADINGAGENTS_RESEARCH_MERGE_PLAN.md` as the compact repo-local merge of DR1, Lane 2, Lane 3, the current handoff, and this plan.
  - Write `reports/research_merge/LIVE_SENSITIVE_PATH_MAP.md` with:
    - research-only paths,
    - overnight-only paths,
    - paper-only paths,
    - supervisor dry-run paths,
    - supervisor submit paths,
    - report-only paths,
    - every route to Alpaca order placement.
  - Write `reports/research_merge/NEXT_BATCH_QUEUE.md` with the staged queue:
    - safety/invariants/schemas,
    - SEC filing foundation,
    - SEC fundamentals,
    - FRED/ALFRED macro regime,
    - ETF/sector context,
    - policy engine shadow mode,
    - pullback-support paper rewrite,
    - paper tournament promotion,
    - overnight research batch planner,
    - supervisor/live gate cutover,
    - token/context compression.
  - Write `reports/research_merge/BATCH_1_HANDOFF.md` after the foundation slice lands.

- [x] **Step 0.6: Add risk posture configuration**
  - Add a config concept:
    - `risk_posture: conservative | balanced | performance_seeking`
  - Default: `balanced` for paper and `conservative` for live unless explicitly configured.
  - `performance_seeking` may:
    - increase paper candidate breadth,
    - run more top-N research,
    - permit wider paper exploration budgets,
    - evaluate tiny-live candidates more aggressively after promotion evidence.
  - `performance_seeking` may not:
    - bypass live gate,
    - increase live caps beyond risk envelope,
    - skip dry-run,
    - skip reconciliation,
    - accept stale data,
    - allow non-stock, short, option, crypto, margin, or market orders.

**Focused checks:**
- `git status --short`
- Fresh-shell env presence check for new vars, lengths only.
- Static path map review before touching live-sensitive code.

---

## Phase 1 - Email And Alert Foundation

**Intent:** Make supervisor/daily/urgent email clear enough that the operator can instantly tell what happened, what broke, which account is involved, what was spent today, and what ops decision is needed.

**Files:**
- Modify: `tradingagents/brokers/alpaca_supervisor.py`
- Modify tests: `tests/test_alpaca_supervisor.py`, `tests/test_alpaca_cli.py`

- [x] **Step 1.1: Preserve structured alert levels**
  - Use `CRITICAL`, `NOTABLE`, and `ROUTINE`.
  - Preserve packet writing for all events.
  - Email only for configured alert policy.

- [x] **Step 1.2: Render clear exception emails**
  - Daily report sections now stay compact:
    - `Plain English`
    - `What happened`
    - `Problem`
    - `Money today`
    - `Live account`
    - `Paper account`
    - `Open orders`
    - `Submitted orders`
    - `Rejected/canceled orders` only when needed
    - `Need from you`
  - Urgent exception emails now use the same plain-English tone and avoid long system labels.
  - `Need from you` must be ops-only: credentials, config, risk envelope, kill/freeze, missing data, stale setup.
  - Tone must be plain-English and proposal style:
    - do not tell the operator to "fix" things;
    - say trading stayed blocked before live money was spent;
    - ask whether Codex should repair/refresh safe setup items;
    - if credentials, arming, or freeze decisions are needed, ask one question and keep trading blocked.

- [x] **Step 1.3: Compute spent-today from packets**
  - Read submitted hourly packets structurally.
  - Split live vs paper.
  - Treat failed/rejected/canceled orders separately from filled/submitted notional.
  - Include unknown values as `unknown`, not guessed.

- [x] **Step 1.4: Add alert storm throttle**
  - Collapse repeated same-cause alerts into one digest window.
  - CRITICAL still emits at least once per incident.

- [x] **Step 1.5: Stop chase-spike language in supervisor behavior**
  - `build_candidate_signals()` now ranks controlled dips above sharp green spikes when the market data is otherwise clean.
  - Green spikes are labeled `do not chase`.
  - Profitable live holdings can emit `decision="profit-take"` with a `Sell the spike` close action.
  - Focused tests cover controlled dip ranking and profit-take sells.

**Focused tests:**
- Fake-mailer clarity test.
- `CRITICAL` reconciliation mismatch email includes accounts, holdings, blocker, ops ask.
- `ROUTINE` trade writes packet but does not email.
- `NOTABLE` demotion/promotion batches.
- Spent-today splits live vs paper.

---

## Phase 2 - Unified Live-Submit Chokepoint

**Intent:** Every live order must pass one path: `alpaca check -> dry-run evidence -> unified live gate -> submit`. No research, crawler, Composio, or model path may bypass it.

**Files:**
- Modify: `tradingagents/policy/live_gate.py`
- Modify: `tradingagents/brokers/alpaca_supervisor.py`
- Modify: `tradingagents/brokers/alpaca.py`
- Modify: `cli/main.py`
- Tests: `tests/test_live_gate.py`, `tests/test_alpaca_cli.py`, `tests/test_alpaca_execution.py`

- [x] **Step 2.1: Make submit chokepoint explicit**
  - Keep `validate_supervisor_live_submit_allowed()` as the supervisor-facing gate.
  - Add a static/contract test that all live `submit_order()` call sites route through the gate.

- [x] **Step 2.2: Preserve paper-only behavior**
  - Paper-first actions cannot be blocked by live exposure unless the action can affect live.
  - Paper tournament remains paper-only.
  - Pullback-support paper command and paper-only submit tests confirm live clients are not created.

- [x] **Step 2.3: Keep `live_now` rejected**
  - Existing aggressive/legacy live actions with `execution_mode="live_now"` remain blocked.
  - Tiny-live requires promotion, risk envelope, live control, dry-run evidence, and stock/long/limit-only constraints.
  - `tests/test_live_gate.py` and `tests/test_alpaca_cli.py` keep this covered.

- [x] **Step 2.4: Add operational blockers**
  - Reconciliation mismatch blocks all live.
  - Missing or stale dry-run evidence blocks live.
  - Clock skew blocks live.
  - Stale dead-man blocks live.
  - Missing risk envelope blocks live.
  - Unpromoted sleeve blocks live.
  - Covered by live-gate, execution-safety, hourly-supervisor, freeze/dead-man, and latest-packet reconciliation tests.

**Focused tests:**
- Live submit requires unified gate.
- Research/overnight cannot submit.
- Paper tournament cannot submit live.
- Paper action not blocked by live exposure.
- No shorts/options/crypto/margin/market orders.
- Dry-run required before submit.
- Stale/missing data fails closed.
- Unpromoted sleeve cannot live trade.

---

## Phase 3 - Schemas, Packets, And Provenance

**Intent:** Every decision and research artifact has a versioned, packetable contract. Every source carries provenance and freshness.

**Files:**
- Modify: `tradingagents/schemas/trading.py`
- Modify/create: `tradingagents/policy/packets.py`
- Create: `tradingagents/schemas/research.py`
- Tests: `tests/test_policy_foundation.py`, `tests/test_research_schemas.py`

- [x] **Step 3.1: Expand existing trading schemas conservatively**
  - Add missing fields from the handoff only when required by gates:
    - `freshness`
    - `feature completeness`
    - `data_integrity_ref`
    - `limit_low`, `limit_high`, `tif`
    - `size_context`
    - immutable `packet_id`
    - `code_version`, `config_version`
  - Keep backwards-compatible optional fields where current packets already exist.

- [x] **Step 3.2: Add research schemas**
  - `SourceEvidencePacket`
  - `ResearchIntelligencePacket`
  - `MarketActorProfile`
  - `MarketMirrorScenarioPacket`
  - `ModelRunTelemetryPacket`
  - `CrawlerRunPacket`
  - `KnowledgeGraphNodePacket`
  - `KnowledgeGraphEdgePacket`
  - `GraphMemoryQueryPacket`
  - `SocialAnomalyPacket`
  - `PromptRegistryPacket`
  - `ResearchBatchRunPacket`
  - All must include:
    - `schema_version`
    - `generated_at`
    - `analysis_only: true`
    - `sources`
    - `source_refs`
    - `input_hashes`
    - `redaction_status`
    - `freshness`
    - `tool_route`

- [x] **Step 3.3: Add packet writer for research artifacts**
  - Write under separate paths:
    - `results/research_evidence/`
    - `results/research_simulations/`
    - `results/model_telemetry/`
    - `results/crawler_runs/`
    - `results/research_batches/`
    - `results/research_memory/`
    - `results/prompt_registry/`
  - Use atomic writes and unique timestamped names.
  - Maintain `latest.json` only where useful.

- [x] **Step 3.4: Ensure every decision writes a packet for current submit-capable surfaces**
  - `HOLD_CASH`, `watch`, `reject`, `paper_enter`, and live-blocked actions are packetable.
  - Pullback-support now writes packets for both `paper_enter` and `HOLD_CASH`.
  - Hourly supervisor, overnight plans, premarket briefs, paper tournament, pullback-support, and legacy manual Alpaca submit now have packet/receipt writers.
  - Legacy `alpaca submit` now writes a receipt packet for refused settings, planning blocks, unified live-gate blocks, submitted paper/live runs, and partial broker failures.
  - `tests/test_packet_coverage.py` guards the current submit-capable CLI surfaces against losing packet writers.
  - Future production Crawlee/model-batch/tiny-live paths must add packet writers as they become real submit or decision surfaces.

**Focused tests:**
- Schema round-trip.
- Unknown old packet fields do not break readers.
- `analysis_only` research packet cannot be cast into `TradeIntent`.
- Every policy decision writes a packet.

---

## Phase 4 - Pullback-Support Paper Loop

**Intent:** Build the deterministic paper-first sleeve as the first real strategy loop. It should embody the Lane 3 good-dip vs falling-knife method and run without LLMs.

**Files:**
- Modify: `tradingagents/sleeves/pullback_support.py`
- Modify: `tradingagents/brokers/paper_tournament.py`
- Modify: `cli/main.py`
- Tests: `tests/test_policy_foundation.py`, `tests/test_paper_tournament.py`, `tests/test_alpaca_cli.py`

- [x] **Step 4.1: Complete pullback features**
  - Trend anchors: rising 50D and 200D.
  - Support proximity.
  - ATR depth: good dip `0.75-2.5 ATR`; falling knife `>3 ATR`.
  - Sell volume behavior: decelerating/moderate vs expanding/panic.
  - Gap state: none/small/reclaimed vs large/open down.
  - Sector confirmation placeholder until adapter is real.
  - Regime placeholder: neutral/risk-on allowed; risk-off/panic blocked.
  - Blackouts: earnings, fresh negative event, trading halt.

- [x] **Step 4.2: Emit deterministic `TradeIntent` or `HOLD_CASH`**
  - Paper only.
  - Stocks only, long only, limit only.
  - Idempotency key deterministic from sleeve, symbol, as-of bucket, limit band, size, environment.
  - `tradingagents/sleeves/pullback_support.py` now builds the full `RunPacket` for both outcomes.

- [x] **Step 4.3: Route through existing safe Alpaca flow**
  - `alpaca check`
  - dry-run
  - submit to paper only if clean and actionable.
  - `tradingagents alpaca pullback-support-paper` defaults to dry-run, writes a packet, checks the paper account before planning paper orders, and submits only with `--submit-actions` plus paper-enabled config.

- [x] **Step 4.4: Treat tournament live strategy as advisory**
  - Tournament selection can recommend a sleeve.
  - It cannot promote or trade live until the promotion gate exists.
  - Existing paper tournament evidence marks live strategy selection as `advisory_only`.

- [x] **Step 4.5: Add AlphaInsider popular-strategy paper watch**
  - Added read-only AlphaInsider helper: `tradingagents/research/alphainsider.py`.
  - Added paper budget planner: `build_alphainsider_paper_watch_plan()`.
  - Added CLI command: `alpaca paper-tournament alphainsider-watch`.
  - Uses leftover paper buying power after the existing `$30,000` tournament reserve.
  - Writes `alphainsider-paper-watch-*.json` packets and stores the latest watch plan in `paper-tournament-ledger.json` when the ledger exists.
  - Does not submit AlphaInsider orders, start bots, submit live orders, or guess missing strategy/bot IDs.
  - Focused check landed: `uv run --with pytest python -m pytest tests/test_paper_tournament.py::test_alphainsider_paper_watch_uses_only_remaining_paper_budget tests/test_paper_tournament.py::test_paper_tournament_alphainsider_watch_writes_paper_only_packet -q` passed with 2 tests.

**Focused tests:**
- Clean good dip trades paper.
- Falling knife blocks and writes `HOLD_CASH`.
- Fresh negative filing/news blackout blocks.
- Paper submit does not touch live.
- Tournament candidate remains advisory.
- AlphaInsider paper watch uses only leftover paper budget and never touches live.

---

## Phase 5 - Free Official Data And Social/Crawler Evidence

**Intent:** Use free/legal/testable data as enrichment, not as the execution authority. Official data first; social/crawled data as anomaly/context.

**Files:**
- Create/modify under: `tradingagents/dataflows/`
- Modify: `tradingagents/dataflows/interface.py`
- Modify: `tradingagents/agents/utils/news_data_tools.py`
- Tests: `tests/test_dataflows_*.py`, `tests/test_research_schemas.py`

- [x] **Step 5.1: Add official free adapters as thin cache-first sources**
  - SEC EDGAR submissions/companyfacts/Form 4/8-K.
  - FRED/ALFRED macro regime.
  - BLS v2 release data.
  - BEA API data.
  - EIA data.
  - Alpha Vantage ETF/top-N only where rate limits allow.
  - Treasury FiscalData and release calendars as event-risk context.
  - Implemented first-pass packet adapters:
    - `tradingagents/dataflows/sec.py`
    - `tradingagents/dataflows/fred.py`
    - `tradingagents/dataflows/bls.py`
    - `tradingagents/dataflows/bea.py`
    - `tradingagents/dataflows/eia.py`
    - `tradingagents/dataflows/treasury_fiscal.py`
  - Current scope is official evidence packet production, release-calendar event-risk context, and shared cache helper.
  - Supplemental vendor/news adapters also landed as evidence-only enrichment:
    - `tradingagents/dataflows/eodhd.py`
    - `tradingagents/dataflows/finnhub.py`
    - `tradingagents/dataflows/massive.py`
    - `tradingagents/dataflows/fmp.py`
    - `tradingagents/dataflows/google_news.py`
    - `tradingagents/dataflows/marketaux.py`
    - `tradingagents/dataflows/scrapingbee.py`
  - These adapters use env var names only, strip key-bearing query params from packets, and are forbidden from creating trade intents or live-order authority.

- [x] **Step 5.2: Add source quality policy**
  - SEC/FRED/BLS/BEA/EIA/Treasury = high or medium depending freshness.
  - Alpha Vantage = useful but rate-limited.
  - Reddit/X/social = anomaly/context only.
  - yfinance = prototype/convenience, not core truth.
  - Delisted free price history = low-quality and excluded from sizing.
  - Implemented `tradingagents/research/source_quality.py`.
  - Implemented safe blocked evidence fallback in `tradingagents/dataflows/_official_common.py`.
  - Implemented official evidence cache helper in `tradingagents/dataflows/_official_common.py`:
    - fresh cache hit avoids refetch,
    - expired cache can become stale fallback when refresh fails,
    - cache keys are hashed and do not store API keys in filenames.
  - Release-calendar orchestration landed in Step 5.13.
  - Added trust profiles for EODHD, Finnhub, Massive, FMP, Google News RSS, Marketaux, ScrapingBee, and `social_watchlist`.

- [x] **Step 5.3: Add Crawlee + Playwright research crawler packet runner**
  - Start with Python Crawlee + Playwright to fit the Python repo.
  - Keep JS Crawlee sidecar as optional future escape hatch for targets Python cannot handle.
  - Domain allowlist required.
  - Respect robots where possible.
  - No auth-wall bypass.
  - No stored browser sessions by default.
  - Rate limits, max pages, max bytes, and cache TTL required.
  - First policy scaffold landed in `tradingagents/research/crawler_policy.py`.
  - Packet runner landed in `tradingagents/research/crawler_runner.py`.
  - CLI command landed: `research crawl-target`.
  - If Crawlee/Playwright are missing, the command writes a blocked analysis-only packet instead of silently pretending it crawled.
  - `research crawler-runtime-doctor` now reports runtime readiness plus self-heal install commands.
  - Crawlee/Playwright were installed into the repo Python 3.11 venv and Chromium browser binaries were installed.
  - A one-page read-only crawl succeeded and wrote `results/crawler_runs/crawler-run-crawler-run-e6f37ae65806419db0e6d8d18a24c7d1.json`.
  - Runtime dependency setup is saved in `requirements-crawler.txt`; keep it out of normal project dependencies because Crawlee 1.7.1 conflicts with the repo's Python 3.10 dependency resolution path.

- [x] **Step 5.4: Use Browser and Docker Playwright correctly**
  - Browser plugin = Codex interactive inspection/spot checks.
  - Docker Playwright = reproducible browser tests and screenshots.
  - Runtime crawler = Crawlee + Playwright packet producer, not Browser.
  - ChatGPT Deep Research browser route was saved in `reports/research_merge/CHATGPT_DEEP_RESEARCH_RUNS.md`; crawler runtime remains separate from Browser plugin control.

- [x] **Step 5.5: Scope authenticated connectors**
  - Composio social/cloud tools are read-only by default.
  - Writes require explicit per-action user approval and are never callable from autonomous trading loops.
  - Reddit/Facebook/X/YouTube/social outputs become evidence packets only.
  - Implemented route/action policy in `tradingagents/research/tool_routing.py`.

- [x] **Step 5.6: Add explicit Composio/Docker routing contract**
  - Composio is for authenticated cloud/social/account-backed evidence reads:
    - Gmail/Drive/Docs/Calendar/GitHub/Supabase/OpenAI/Reddit/Facebook/YouTube/Benzinga/Firecrawl/Alpaca metadata only when useful and read-only.
  - Docker MCP is for local/dev and public research utilities:
    - fetch/search,
    - Playwright checks,
    - YouTube transcripts,
    - Twitter/X research if configured,
    - local filesystem/dev helpers,
    - memory graph tools for Codex-side work.
  - Autonomous trading runtime must not depend on live Codex MCP tools directly.
  - MCP outputs must be normalized into `SourceEvidencePacket`, `SocialAnomalyPacket`, or `ResearchBatchRunPacket` before scheduled automations consume them.
  - Any cloud write/post/send/trade/change action is forbidden unless the user explicitly asks for that exact action in that moment.
  - Implemented autonomous route validation for read-only research paths.

- [x] **Step 5.7: Build social anomaly packets**
  - Convert Reddit/StockTwits/X/Twitter/Facebook/YouTube/social inputs into `SocialAnomalyPacket` before any LLM or mirror use.
  - Required fields:
    - source platform,
    - query/topic/symbol,
    - collection window,
    - post/count sample summary,
    - anomaly score or reason,
    - quoted evidence refs,
    - freshness,
    - read-only route,
    - redaction status.
  - Social can:
    - downrank,
    - demote to watch,
    - request more research,
    - flag narrative/stale/contradiction risk.
  - Social cannot:
    - create a trade intent,
    - size a position,
    - promote a sleeve,
    - waive any gate.
  - Implemented `tradingagents/research/social_anomaly.py`.

- [x] **Step 5.8: Save operator social attention watchlists**
  - Stable read-only watchlists landed in `config/social_watchlists.json`.
  - X/Twitter routes use Docker `twitter-research`.
  - Facebook/Instagram/LinkedIn routes use Composio read-only research routes.
  - Facebook group searches and company-specific Instagram/LinkedIn pages are saved as dynamic research suggestions, not permanent always-on monitoring.
  - Dynamic company pages should be activated only for open positions, overnight top candidates, high-conviction watchlists, or consumer-facing companies where comments matter.
  - Group searches should be ranked by recent post volume, comments, ticker relevance, and source quality instead of member count.
  - `tradingagents/research/social_watchlists.py` packetizes this as `SourceEvidencePacket` with write/trade effects forbidden.

- [x] **Step 5.9: Add Reddit market-sentiment watchlist**
  - Added `config/reddit_market_watchlists.json`.
  - Added `tradingagents/research/reddit_watchlists.py`.
  - Required buckets:
    - `core_market_pulse`
    - `retail_speculative_heat`
    - `macro_fear_context`
    - `ai_semiconductor_theme`
    - `dynamic_ticker_pages`
    - `reddit_search_queries`
  - Default Reddit policy:
    - recent posts only by default,
    - subreddit `/new` pages,
    - searches must use `sort=new&t=day`,
    - summaries/listings first,
    - raw thread drilldown only for holdings, overnight top candidates, paper candidates, major macro events, major ticker spikes, or unusually high engagement,
    - no full comment dumps by default.
  - Compact summaries are validated by `RedditCompactSummary`.
  - Reddit outputs are stored as context/sentiment evidence only and may produce flags such as `retail_panic`, `retail_euphoria`, `buy_the_dip_chatter`, `squeeze_hype`, `macro_fear`, `earnings_reaction`, and `no_signal`.
  - Handoff written: `reports/research_merge/REDDIT_MARKET_SENTIMENT_WATCHLIST_HANDOFF.md`.

- [x] **Step 5.10: Add provider fallback policy for quota/depletion**
  - Added `config/research_provider_fallbacks.json`.
  - Added `tradingagents/research/provider_fallbacks.py`.
  - Added CLI packet command: `research provider-fallbacks`.
  - Policy:
    - prefer cache, local unlimited tools, connected read-only MCPs, and free/unmetered sources before limited APIs where practical,
    - treat limited APIs as optional enrichment,
    - if an API is out of calls, mark it depleted, skip it, use fallback routes, and continue with lower confidence,
    - never let fallback selection create trade intents, position sizes, promotions, live-gate waivers, or orders.
  - Evidence needs with fallback routes:
    - `market_news`
    - `quote_price_context`
    - `fundamentals_profile`
    - `macro_official`
    - `social_sentiment`
    - `crawler_research`
  - Focused tests confirm depleted Marketaux/Finnhub/FMP/EODHD are skipped while Google News RSS, Reddit watchlist, Docker X/Twitter research, Crawlee, cache, or other read-only routes remain available.
  - Ticker-level provider bundle landed:
    - Added `tradingagents/research/provider_orchestrator.py`.
    - Added CLI command: `research ticker-provider-bundle`.
    - Supports broad overlapping ticker packets for Google News RSS, Finnhub, FMP, EODHD, Marketaux, Massive, and Alpha Vantage-style packet wrappers where the repo has safe adapters.
    - Unsupported local/MCP routes are recorded as unsupported attempts instead of disappearing.
    - Depleted sources are skipped before fetch.
    - Focused check landed: `uv run --with pytest python -m pytest tests/test_research_provider_orchestrator.py -q` passed with 3 tests.

- [x] **Step 5.11: Attach research context to overnight plans**
  - Added `tradingagents/research/overnight_context.py`.
  - `alpaca plan-overnight` now writes analysis-only research-context packets under `LOG_DIR/research_context` by default.
  - Overnight packets now include `research_context` with:
    - provider fallback choices by evidence need,
    - depleted/disabled source skips,
    - Reddit watchlist policy summary,
    - social watchlist policy summary,
    - context packet refs,
    - blocked context packets if a config is missing or malformed,
    - consumer metadata for candidate, tradable, live-position, and paper-position symbols.
  - New CLI options:
    - `--include-research-context/--no-research-context`
    - `--research-context-dir`
    - `--depleted-research-sources`
    - `--disabled-research-sources`
  - This is still context only. It cannot create orders, position sizes, promotions, or live-gate waivers.

- [x] **Step 5.12: Carry compact research context into premarket briefs**
  - `_overnight_timeline_item()` now keeps compact research-context metadata:
    - packet count,
    - blocked context count,
    - provider fallback evidence needs,
    - watchlist families,
    - skipped/depleted sources,
    - execution authority.
  - `build_premarket_brief_packet()` now includes `latest_research_context` in `premarket_instructions`.
  - Premarket markdown shows research-context packet/watchlist counts without dumping raw Reddit/social/provider payloads.
  - Hourly/live paths still must validate fresh quotes, orders, positions, and gates before any action.

- [x] **Step 5.13: Add official release-calendar event-risk context**
  - Added `config/release_calendar_watchlist.json` with official Fed, BLS, BEA, and EIA source refs.
  - Added `tradingagents/research/release_calendar.py`.
  - Added `research release-calendar-packet` CLI command.
  - `alpaca plan-overnight` now accepts `--release-calendar-config-path` and includes release-calendar packets in overnight research context.
  - Overnight context summary now exposes `watchlists.release_calendar` with event-risk state, active window count, upcoming count, high-impact count, and planner flags.
  - This is still analysis-only. It can say "macro event window is active" and "fresh post-release validation is needed"; it cannot create, size, approve, or submit orders.
  - Official source basis checked during implementation:
    - BLS Employment Situation page lists the June 5, 2026 8:30 AM release and the BLS `.ics` calendar.
    - Federal Reserve monetary-policy page lists FOMC calendar/upcoming dates.
    - BEA release schedule page lists 2026 scheduled economic releases.
    - EIA information releases and upcoming reports pages list weekly petroleum and natural gas release timing.
  - Focused check landed: `uv run --with pytest python -m pytest tests/test_research_crawler_social.py::test_release_calendar_packet_marks_active_event_window tests/test_research_crawler_social.py::test_overnight_research_context_includes_release_calendar_packet tests/test_research_crawler_social.py::test_overnight_research_context_writes_provider_and_watchlist_packets tests/test_alpaca_cli.py::test_research_release_calendar_packet_writes_macro_context tests/test_alpaca_cli.py::test_plan_overnight_includes_research_context_and_depleted_source_fallbacks -q` passed with 5 tests.

- [x] **Step 5.14: Add Agent Intelligence Ledger**
  - Added `tradingagents/evals/agent_intelligence_ledger.py`.
  - Converts TradingAgents graph outputs into scoreable forecasts by role: Market Analyst, Sentiment Analyst, News Analyst, Fundamentals Analyst, Research Manager, Trader, and Portfolio Manager.
  - Stores forecasts in append-only JSONL at `results/agent_intelligence/ledger.jsonl`.
  - Resolves due forecasts against ticker-vs-benchmark return windows and records actual return, benchmark return, relative return, Brier score, and agent score delta.
  - Added CLI commands:
    - `research agent-ledger-from-overnight`
    - `research agent-ledger-resolve`
    - `research agent-ledger-summary`
  - `alpaca plan-overnight` now appends scoreable forecasts automatically unless `--no-agent-ledger` is used.
  - Earned influence weights landed:
    - `agent_influence_weights()` computes bounded advisory weights from resolved accuracy, Brier calibration, and score delta.
    - `render_agent_influence_context()` produces a compact prompt/context block.
    - `research agent-ledger-summary` and `research agent-ledger-resolve` now include `influence_weights`.
    - `write_summary()` persists `influence_weights` under `results/agent_intelligence/summary.json`.
  - This lets agents earn influence over time instead of every role always receiving the same trust weight.
  - Focused check landed: `uv run --with pytest python -m pytest tests/test_agent_intelligence_ledger.py tests/test_alpaca_cli.py::test_research_agent_ledger_from_overnight_writes_forecasts tests/test_alpaca_cli.py::test_research_agent_ledger_summary_includes_influence_weights -q` passed with 6 tests.

**Focused tests:**
- SEC/FRED/BLS/BEA/EIA adapter returns normalized packet with provenance.
- Adapter failure writes null/default and does not crash automation.
- Crawler skips non-allowlisted domain.
- Crawler respects robots/disallow fixture.
- Crawler enforces max pages/rate limits.
- Authenticated social write tool cannot be called from autonomous loop.
- Social anomaly packet cannot become `TradeIntent`.
- MCP route metadata is stored without secrets.

---

## Phase 6 - Model Routing, Cost Guardrails, And Performance Telemetry

**Intent:** Track model cost, accuracy, usefulness, latency, and degradation over time so upgrade decisions are based on evidence, not vibes.

**Files:**
- Create: `tradingagents/research/model_routing.py`
- Create: `tradingagents/research/model_telemetry.py`
- Create: `tradingagents/research/memory.py`
- Create: `tradingagents/telemetry/model_research.py`
- Modify: `cli/main.py`
- Tests: `tests/test_model_routing.py`, `tests/test_model_telemetry.py`, `tests/test_model_research_telemetry.py`

- [x] **Step 6.1: Add provider routing policy**
  - Default scheduled mode: deterministic/free/local.
  - Gemini first paid fallback when explicitly allowed:
    - env: `GOOGLE_API_KEY` or `GEMINI_API_KEY`
    - env: `GEMINI_PROJECT_NAME`
    - default model class: cheapest capable Gemini flash/lite option available in the repo catalog.
  - OpenAI API disabled by default.
  - Windows local Ollama is the quick local/free lane.
  - Mac Ollama is the overnight research mule lane.
  - Deterministic helpers do source packets, schemas, and safety checks without a model.
  - Codex/ChatGPT research is the high-judgment fallback when scheduled paid model use is not armed.
  - Implemented in `tradingagents/research/model_routing.py`.
  - Current order for single-route callers: Windows local Ollama, then Mac Ollama, then capped Gemini if paid routing is explicitly allowed, then OpenAI only with an extra explicit switch.
  - Parallel route planner landed:
    - `deterministic_helpers`
    - `windows_local`
    - `mac_ollama`
    - `intelligent_judgment`
  - CLI command landed: `research automation-orchestration-plan`, which writes a `ResearchBatchRunPacket`, model telemetry packets, quality gates, fallback actions, and a no-order authority contract.

- [x] **Step 6.2: Add hard spend and token caps**
  - Required config:
    - `allow_paid_model_research: false` by default
    - `preferred_paid_provider: gemini`
    - `max_model_calls_per_run`
    - `max_input_tokens_per_run`
    - `max_output_tokens_per_run`
    - `max_estimated_cost_usd_per_run`
    - `monthly_soft_budget_usd`
  - If cost cannot be estimated, fail closed to local/free.
  - Implemented in `ModelRoutingPolicy`: preferred paid provider, per-run model-call cap, input-token cap, output-token cap, per-run cost cap, and monthly soft budget.
  - Unknown paid-route cost fails closed to local/free/deterministic.
  - Focused check landed: `uv run --with pytest python -m pytest tests/test_model_routing.py -q` passed with 18 tests.

- [x] **Step 6.3: Add model telemetry packet and lightweight report**
  - Record per model run:
    - `run_id`
    - `run_type`
    - `command_surface`
    - `started_at`
    - `completed_at`
    - `duration_sec`
    - provider
    - model
    - base URL kind, not full URL if sensitive
    - reasoning profile
    - selected analysts
    - analyst wall times
    - route reason
    - prompt hash
    - input/output token estimate or actual usage
    - LLM call count
    - tool call count
    - estimated cost
    - cost source
    - cost estimate confidence
    - latency
    - timeout/retry count
    - graph failure count
    - analyst failure count
    - stale source count
    - candidate count
    - top candidates
    - parse success
    - schema validation success
    - source-claim verification rate
    - decision status: `success | partial | failed | degraded`
    - linked output paths
    - later outcome labels when available
    - whether output changed a decision from `research_only` to `watch/downrank/block`
  - Never store raw secrets or full prompts unless explicitly redacted.
  - Store packets under:
    - `results/model_research_telemetry/runs/`
    - `results/model_research_telemetry/latest.json`
    - `results/model_research_telemetry/daily/YYYY-MM-DD.json`
    - `results/model_research_telemetry/weekly/YYYY-WW.json`
  - First helper implemented in `tradingagents/research/model_telemetry.py` using `ModelRunTelemetryPacket`.
  - Lightweight report helpers now dedupe `latest.json`, count status/provider/route, total tokens, estimate spend, track latency, and show optional budget remaining.
  - CLI command landed: `research model-telemetry-report`.
  - Orchestration CLI now writes one model telemetry packet per lane.
  - `ModelRunTelemetryPacket` now carries usefulness labels, outcome labels, quality scores, outcome notes, and resolution timestamps.
  - `research model-telemetry-report` now reports usefulness counts, outcome counts, resolved run count, quality score, and cost by usefulness.
  - Daily supervisor reports now include the latest model telemetry summary.
  - Current model runs are honestly `pending/unresolved` until later market evidence labels them.

- [x] **Step 6.4: Add upgrade triggers**
  - Consider upgrade only if:
    - local/free parse success below threshold over N runs,
    - Gemini improves verified useful signal rate by a defined margin,
    - latency stays inside overnight budget,
    - estimated monthly cost stays inside budget,
    - no secret/redaction violations.
  - Downgrade or disable if:
    - cost cap hit,
    - hallucination/unsourced claim rate too high,
    - output rarely changes research packet decisions,
    - parse failures exceed threshold.
  - Trigger checks require enough history:
    - default minimum: at least 20 comparable runs in 7 days, or a manually marked experiment window.
    - no automatic paid-model escalation; telemetry recommends only.
  - Track:
    - cost per successful run,
    - cost per promoted candidate,
    - promotion rate to paper/live pipeline,
    - next-close and 5-day excess return vs QQQ for top candidates when enough data exists,
    - model/mirror warning precision and over-block rate.
  - Implemented `model_upgrade_recommendation()` in `tradingagents/research/model_telemetry.py`.
  - Recommendation is advisory only: it can suggest insufficient history, downgrade/disable, keep default, or human-approved capped experiment; it never auto-upgrades paid routes.
  - Focused tests verify minimum-history and never-auto-upgrade behavior.

- [x] **Step 6.5: Add daily/weekly model score summaries**
  - Write under `results/model_research_telemetry/summary-latest.json`.
  - Include provider win/loss, cost, latency, parse, verification, usefulness, and budget remaining.
  - Current implementation writes `results/model_telemetry_reports/latest.json`; daily/weekly automations can consume that file until a separate calendar-bucket archive is needed.
  - Focused tests cover outcome/usefulness rollup and daily-report inclusion.

- [x] **Step 6.6: Keep routing implementation small**
  - Prefer `tradingagents/llm_clients/routing_policy.py` and a thin router over broad framework churn.
  - Reuse `model_catalog.py`, `capabilities.py`, and `default_config.py`.
  - Put budget caps in a policy object, not scattered CLI branches.
  - Budget caps live in `tradingagents/research/model_routing.py` policy helpers; CLI surfaces consume summaries/packets rather than duplicating cap logic.

**Focused tests:**
- Paid model cannot run when `allow_paid_model_research=false`.
- Gemini selected before OpenAI when paid allowed.
- Cost cap blocks run.
- Missing usage estimate blocks paid run.
- Telemetry written for success, timeout, parse fail, and fallback.
- Secret-like fake tokens are redacted from prompt artifacts.
- Daily rollup aggregates mixed provider/model packets.
- Weekly trigger ignores samples below minimum.
- Markout enrichment is idempotent and skips unfinished horizons.

---

## Phase 7 - Knowledge Graph, Prompt Registry, And MiroFish-Inspired Market Mirror

**Intent:** Capture the useful MiroFish idea - simulated market participants, persistent memory, narrative diffusion, and adversarial interviews - without importing AGPL code, adding heavy dependencies, or creating a trading authority.

**Files:**
- Create: `tradingagents/research/knowledge_graph.py`
- Create: `tradingagents/research/prompt_registry.py`
- Create: `tradingagents/research/market_mirror.py`
- Create: `tradingagents/research/market_mirror_prompts.py`
- Create: `tradingagents/research/memory.py`
- Modify: `tradingagents/schemas/research.py`
- Modify: `cli/main.py`
- Tests: `tests/test_knowledge_graph_memory.py`, `tests/test_prompt_registry.py`, `tests/test_market_mirror.py`, `tests/test_model_routing.py`

- [x] **Step 7.1: Add graph memory store**
  - Define `GraphMemoryStore`:
    - `upsert_node`
    - `upsert_edge`
    - `query_symbol_context`
    - `query_theme_context`
    - `label_outcome`
  - Default backend:
    - local SQLite/DuckDB/JSONL under ignored runtime state or `results/research_memory/`.
  - Optional backend:
    - Zep/cloud graph memory via env vars, only with redacted public-market entities.
  - Never store:
    - broker credentials,
    - raw order IDs,
    - account balances,
    - cookies,
    - auth headers,
    - email addresses,
    - connector metadata,
    - secret values.
  - Implemented local JSONL `GraphMemoryStore` in `tradingagents/research/knowledge_graph.py`.
  - Generated proof packet set through `research graph-memory-note`: `results/research_memory/graph_memory.jsonl` plus node/edge/query packets.
  - Sensitive labels are rejected and properties are redacted before storage.

- [x] **Step 7.2: Add prompt registry**
  - Register research, sentiment, market mirror, analyst, risk, and methodology prompts by:
    - `prompt_id`
    - `prompt_hash`
    - `methodology_refs`
    - `allowed_inputs`
    - `forbidden_outputs`
    - `model_route`
    - `redaction_required`
  - Store prompt hashes and metadata by default, not raw unredacted prompts.
  - Include clean-room field for MiroFish-inspired work:
    - methodology inspiration only,
    - no AGPL code/schema/prompt copied.
  - Implemented `tradingagents/research/prompt_registry.py` and `research prompt-registry-defaults`.
  - Generated proof packet: `results/prompt_registry/prompt-registry-prompt-registry-60f4ef947c9c4b61908318d29176dad5.json`.
  - Raw prompt text is not stored; only the redacted prompt hash and metadata are packeted.

- [x] **Step 7.3: Build a small bounded market-mirror panel**
  - Default actors, not 1,000 agents:
    - long-only portfolio manager
    - risk manager
    - retail momentum trader
    - skeptical analyst
    - sector specialist
    - filing/event watcher
    - macro/regime watcher
    - liquidity/market-structure critic
    - bear-case adversary
  - Default candidates: top-N overnight candidates only.
  - Default rounds: small and capped.
  - Each actor produces stance, evidence refs, invalidators, confidence, and what would change their mind.
  - Implemented `tradingagents/research/market_mirror.py` with a capped 1-9 actor clean-room panel.
  - Generated proof scenario: `results/research_simulations/market-mirror-market-mirror-f8d69b7ed00c456b9b6a22347f793dc6.json`.

- [x] **Step 7.4: Add memory abstraction**
  - Default memory: local SQLite or JSONL under ignored runtime state.
  - Optional memory: Zep via `ZEP_API_KEY`, only if available and free-tier safe.
  - If Zep quota/error occurs, fall back to local memory without failing trading.
  - Do not store broker credentials, account balances, raw order IDs, emails, auth headers, or connector metadata.
  - Implemented local default plus optional-Zep-status fallback in `tradingagents/research/memory.py`.
  - Zep key presence does not automatically move memory to cloud; local redacted memory remains default.

- [x] **Step 7.5: Add redaction before model prompts**
  - Strip secrets, tokens, auth headers, cookies, email addresses where not required, broker order IDs, connector metadata, and raw account identifiers.
  - Strip prompt-injection patterns from crawled text into quoted evidence fields.
  - Implemented `redact_research_text()` and `redact_payload()` in `tradingagents/research/memory.py`.
  - Prompt registry hashes redacted text and tests confirm fake secrets/injection phrases are removed or quoted.

- [x] **Step 7.6: Emit advisory scenario packets only**
  - Output:
    - likely narratives
    - fear/greed attention risk
    - social fragility
    - contradiction map
    - invalidators
    - confidence calibration note
    - `analysis_only: true`
  - Allowed downstream influence:
    - add context to overnight packet
    - add warning to premarket brief
    - downrank or demote to watch if contradictory/stale
    - request more research
  - Forbidden downstream influence:
    - create `TradeIntent`
    - size positions
    - submit orders
    - waive gates
    - promote sleeves
  - Market-mirror packets use `analysis_only=true`, `execution_authority=none`, and forbidden effects including trade intent, sizing, order submit, promotion, and live-gate waiver.

- [x] **Step 7.7: Track mirror performance**
  - Later labels compare warnings/stances to outcomes:
    - did invalidator occur?
    - did narrative risk materialize?
    - did the mirror block a bad trade?
    - did it over-block good trades?
    - did it add useful context beyond deterministic features?
  - Report precision/recall-like metrics for warnings, not PnL alone.
  - First scaffold is in place through `MarketMirrorScenarioPacket` refs plus Agent Intelligence Ledger/model telemetry outcome labeling.
  - Current state is advisory/unresolved until later outcome labels determine whether mirror warnings helped or over-blocked.
  - Focused check landed: `uv run --with pytest python -m pytest tests/test_market_mirror_memory.py -q` passed with 8 tests.

**Focused tests:**
- Graph memory stores and queries redacted public-market context.
- Graph memory rejects fake secrets/account identifiers.
- Prompt registry writes hash metadata and blocks forbidden output classes.
- Market mirror output cannot create a trade intent.
- Prompt redaction removes fake secrets.
- Zep failure falls back to local memory.
- Actor output without source refs is downgraded.
- Model disagreement demotes to watch.
- Sizing cannot import/read model confidence or actor confidence.

---

## Phase 8 - Overnight Research Factory Integration

**Intent:** Overnight can be many parts, but it remains analysis-only and packet-first. It should gather, normalize, simulate, summarize, and then leave execution to the deterministic morning/supervisor path.

**Files:**
- Modify: `cli/main.py`
- Modify: `tradingagents/brokers/alpaca_supervisor.py`
- Modify: `tradingagents/graph/setup.py`
- Modify/create: `tradingagents/research/*`
- Tests: `tests/test_alpaca_cli.py`, `tests/test_alpaca_supervisor.py`, `tests/test_market_mirror.py`

- [x] **Step 8.1: Add overnight packet input stages**
  - Candidate universe.
  - Official evidence fetch.
  - Crawled public evidence fetch.
  - Social anomaly fetch.
  - Feature packet.
  - Optional market mirror.
  - Optional LLM/Gemini summary if budget allows.
  - Ranking remains review priority, not an order.
  - `ResearchBatchRunPacket.freshness["input_stages"]` now records the staged path, including graph memory, optional market mirror, optional LLM/Gemini summary, and replay/ablation.

- [x] **Step 8.2: Implement the research-batch operating model backbone**
  - Batch sequence:
    - `alpaca check` preflight when broker context is needed; analysis-only unless entering normal gated supervisor path.
    - Capability audit: env presence/lengths only, Composio/Docker names only, no secrets.
    - Deterministic candidate screen for all names.
    - Official evidence fetch: SEC, macro, calendar, sector/ETF, Alpaca utility data.
    - Social/crawler anomaly fetch for active watchlist/top-N only.
    - Query graph memory for prior theses, invalidators, recurring narratives, and outcome labels.
    - Deep research escalation only for top-N or contradictory candidates:
      - Gemini first when paid research is explicitly enabled and under caps.
      - local/Ollama/free fallback.
      - if all model routes fail, skip optional model stage and write deterministic packet.
    - Market mirror advisory pass for top-N only.
    - Write `ResearchBatchRunPacket`, graph-memory updates, model telemetry, and overnight packet.
    - Premarket brief consumes packets as context only.
  - Cadence:
    - weekly: graph maintenance, outcome labeling, validation summaries, slow macro/sector refresh;
    - overnight: full deterministic scan, official evidence, top-N deep research, market mirror;
    - hourly/session: freshness, spread/liquidity, invalidators, open-order/reconciliation state;
    - after close: outcome labels, alert summaries, model/mirror usefulness scoring.
  - Landed:
    - `tradingagents/research/automation_orchestrator.py`
    - CLI command: `research automation-orchestration-plan`
    - Writes `ResearchBatchRunPacket` with explicit lanes:
      - deterministic helpers,
      - Windows local Ollama,
      - Mac Ollama research mule,
      - Codex/Gemini/OpenAI judgment route.
    - Writes one `ModelRunTelemetryPacket` per lane.
    - Adds `quality_gates`, `fallback_actions`, and no-order `forbidden_effects`.
    - If quality is weak, the packet marks fallback/revision instead of becoming trade truth.
    - Active Codex automations now call the backbone:
      - `tradingagents-overnight-planning` runs `research automation-orchestration-plan`, `research agent-ledger-resolve`, `alpaca plan-overnight`, top-candidate `research ticker-provider-bundle`, `research agent-ledger-summary`, then `alpaca premarket-brief`.
      - `paper-strategy-tournament-runner` runs `alpaca paper-tournament alphainsider-watch` before the paper tournament tick, using only leftover paper buying power after the reserved `$30,000` paper tournament budget.
      - Hourly and market-window supervisors consume research/provider/ledger packets as context only, keep `alpaca check -> dry-run -> submit if clean`, and defer live authority to the unified live-submit guard.
      - Daily report automation refreshes agent-ledger summary and asks for ops-level decisions only; it does not ask for per-trade or per-promotion approval.
    - Focused check landed: `uv run --with pytest python -m pytest tests/test_model_routing.py tests/test_research_automation_orchestrator.py -q` passed.
  - Still open inside Phase 8:
    - actually running the deeper crawler/model/mirror workers from this batch plan,
    - graph-memory updates,
    - daily/weekly usefulness and outcome labels.

- [x] **Step 8.3: Cache by hashes**
  - Do not rerun model/crawler work when source hashes and thesis hashes are unchanged.
  - Reuse prior packet with freshness note.
  - Orchestration packets now include `input_hashes` for candidate symbols, research context, model routes, and a combined `cache_key`.
  - `freshness["cache_policy"]` states when prior model/crawler/mirror packets can be reused.

- [x] **Step 8.4: Keep toolful research outside local model**
  - Codex/Composio/Browser/Crawlee fetches evidence.
  - Local/Gemini sees sanitized packets only.
  - No connector or broker tools inside model calls.
  - Model routes set `can_use_connectors=false` and `can_submit_orders=false` except deterministic helpers, and orchestration records the boundary in `freshness["toolful_research_boundary"]`.

- [x] **Step 8.5: Premarket brief summarizes research as context**
  - Include market mirror summary only as advisory.
  - Include stale warnings.
  - Include blocker if research failed.
  - Do not create orders.
  - Premarket research-context carry-forward is implemented and verified by focused tests; mirror output remains a source/advisory packet only.

- [x] **Step 8.6: Set up the Intel Mac overnight research mule**
  - Target host: `macbook-codex` / `macbook-pro.tail37edd7.ts.net` over Tailscale.
  - Current audit status:
    - Latest real simulation audit reached `http://macbook-pro.tail37edd7.ts.net:11434/v1`.
    - Ollama tags probe found `deepseek-r1:14b`.
    - Mac is 32 GB, so it is not the deep-intelligence lane.
    - Default Mac model route is `deepseek-r1:14b` unless `TRADINGAGENTS_MAC_RESEARCH_MODEL` overrides it.
    - Codex/OpenAI stays the judgment route.
  - Current role:
    1. Source triage.
    2. Stale-source summaries.
    3. Contradiction hunting.
    4. Overnight draft cleanup.
    5. Report compression.
  - Boundaries:
    - Mac receives sanitized packets only.
    - Mac has no broker credentials, Composio/social write authority, or direct order capability.
    - Mac output remains analysis-only until repo policy/evals decide whether it earns influence.
  - Repo-side route, tags health probe, self-heal actions, and operator summaries are implemented in model routing, orchestration telemetry, and the real simulation audit.

**Focused tests:**
- `plan-overnight` writes analysis packet without submitting.
- Stale overnight packet invalidates premarket support.
- Market mirror packet included as source only.
- Budget cap skips optional model stage and still writes deterministic packet.
- Research batch packet links evidence, graph query, model telemetry, and output packet paths.
- Mac DeepSeek helper reports are analysis-only packets and cannot create orders.

---

## Phase 9 - Promotion, Validation, And Live Eligibility

**Intent:** Make promotion a computed state, not a feeling. Sleeves earn paper, shadow, and tiny-live environments by testable evidence.

**Files:**
- Create: `tradingagents/policy/promotion.py`
- Create: `tradingagents/validation/*`
- Create/modify: `config/risk_envelope.example.yaml`
- Tests: `tests/test_promotion.py`, `tests/test_walkforward.py`, `tests/test_cost_model.py`, `tests/test_live_gate.py`

- [x] **Step 9.1: Add pre-registration store**
  - Freeze hypothesis, rules, benchmark, min sample, power target, cost assumptions, capacity.
  - Rule changes create a new registration ID.
  - Implemented `tradingagents/policy/preregistration.py` plus `policy preregister-sleeve`.
  - Focused check landed: `uv run --with pytest python -m pytest tests/test_preregistration_policy.py -q` passed with 2 tests.

- [x] **Step 9.2: Add benchmark and cost gates**
  - Compare against QQQ/SPY as appropriate.
  - Conservative slippage/cost model.
  - Recent alpha weighted heavily.
  - If no surviving recent alpha, sleeve shelves itself.
  - First scaffold implemented in `SleevePromotionEvidence`:
    - `benchmark_excess_return`
    - `cost_adjusted_alpha`
    - `recent_alpha`
    - minimum thresholds for each gate.
  - Full walk-forward/cost-model engine remains a later validation slice.

- [x] **Step 9.3: Add numeric capacity**
  - `capacity_ceiling_usd`
  - `max_participation_rate`
  - `tiny_live_tranche_usd`
  - `tiny_live_max_loss_usd`
  - Missing values block promotion.
  - First scaffold requires `capacity_usd >= requested_tiny_live_tranche_usd`.
  - Full participation-rate/capacity model remains a later validation slice.

- [x] **Step 9.4: Add promotion state machine**
  - `research_only`
  - `paper_candidate`
  - `paper_validated`
  - `shadow_confirmed`
  - `tiny_live_eligible`
  - `paused`
  - `shelved`
  - Live gate allows only `tiny_live_eligible` with `live_enabled=true`, `ci_green=true`, and `shadow_confirmed=true`.
  - First promotion writer/evaluator is implemented in `tradingagents/policy/promotion.py`.
  - Live gate now also requires:
    - `preregistered=true`
    - benchmark/cost/recent-alpha/capacity gates true
    - validation report reference
    - risk envelope reference.

- [x] **Step 9.5: Add autonomous live budget mode**
  - `config/risk_envelope.example.yaml` now documents `live_budget_mode`.
  - Default/older envelopes remain `fixed_tranche`, where each live order stays under `tiny_live_tranche_usd`.
  - `autonomous_with_caps` lets the bot pick live order size above the fixed tranche after all live gates pass.
  - The live gate still enforces `per_name_cap_usd` and `account_max_capital_at_risk_usd`.
  - `autonomous_uncapped` removes repo dollar caps while preserving broker buying power, live control, promotion, reconciliation, stock-only, and limit-only gates.
  - Hourly supervisor live buys now use `execution_mode="tiny_live"` and sleeve `current-aggressive`, not legacy `live_now`.
  - The supervisor packet includes `evidence.live_budget` so operator emails/reports can explain whether autonomous live budget is active, uncapped, or blocked by missing setup.
  - Focused check landed: `uv run --with pytest python -m pytest tests/test_live_gate.py tests/test_alpaca_supervisor.py::test_dynamic_cap_scales_with_profitable_clean_live_strategy tests/test_alpaca_supervisor.py::test_autonomous_live_buy_notional_scales_with_candidate_strength tests/test_alpaca_supervisor.py::test_aggressive_decision_can_live_buy_time_sensitive_candidate tests/test_alpaca_supervisor.py::test_hourly_decision_closes_position_at_risk_threshold tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_live_buy_requires_submit_guard tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_tiny_live_guard_blocks_reconciliation_mismatch tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_suppresses_duplicate_alert_email -q` passed with 18 tests.

**Focused tests:**
- Pre-registration hash changes on rule change.
- Benchmark fail shelves sleeve.
- Missing capacity blocks promotion.
- Unpromoted sleeve cannot live trade.
- Promotion state remains advisory to paper until gate passes.

---

## Phase 10 - Tiny-Live Hardening Behind Gates

**Intent:** Allow one tiny-live sleeve only after operational safety is proved. This is the first real-money milestone, not the default mode.

**Files:**
- Modify: `tradingagents/brokers/alpaca.py`
- Modify: `tradingagents/brokers/alpaca_supervisor.py`
- Modify: `tradingagents/policy/live_control.py`
- Create: `tradingagents/execution/lock.py`
- Create: `tradingagents/execution/reconcile.py`
- Create: `tradingagents/execution/clock.py`
- Create: `tradingagents/execution/tiny_live.py`
- Tests: `tests/test_execution_safety.py`, `tests/test_live_gate.py`, `tests/test_alpaca_execution.py`, `tests/test_alpaca_cli.py`

- [x] **Step 10.1: Deterministic idempotency**
  - Use `TradeIntent.idempotency_key` as Alpaca `client_order_id`.
  - Retry with same key cannot double-submit.
  - First helper landed: `build_tiny_live_order_payload()` uses `TradeIntent.idempotency_key`.
  - Hourly supervisor tiny-live actions now derive a stable `ta-tiny-...` client order ID from trading day, sleeve, symbol, side, notional, and limit price.
  - Hourly live submit now uses that stable ID instead of a seconds-level timestamp ID.
  - Hourly packets include the live action `idempotency_key` preview for operator/debug clarity.
  - Broker duplicate-response classification now treats duplicate `client_order_id` responses as an idempotency conflict that must reconcile existing Alpaca orders before retry.
  - The supervisor does not create a replacement live order ID after a duplicate response.
  - When Alpaca reports a duplicate, hourly submit now looks up the existing order by `client_order_id` and attaches a compact `reconciled_orders` summary to the packet if found.
  - The looked-up existing order is compared against the intended action for symbol, side, order type, limit price, size, and unsafe terminal statuses.
  - Latest-packet reconciliation now compares prior live submitted/reconciled order IDs against Alpaca before allowing any later retry.
  - Focused check landed: `uv run --with pytest python -m pytest tests/test_alpaca_supervisor.py::test_supervisor_live_client_order_id_is_stable_for_same_decision_day tests/test_alpaca_supervisor.py::test_aggressive_decision_can_live_buy_time_sensitive_candidate tests/test_alpaca_supervisor.py::test_hourly_decision_closes_position_at_risk_threshold tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_paper_first_submits_to_paper tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_live_submit_uses_tiny_live_idempotency_key tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_live_buy_requires_submit_guard tests/test_alpaca_cli.py::test_live_submit_call_sites_stay_behind_unified_gate -q` passed with 7 tests.
  - Focused duplicate-response check landed: `uv run --with pytest python -m pytest tests/test_alpaca_execution.py::test_classify_alpaca_duplicate_client_order_id_requires_reconciliation tests/test_alpaca_execution.py::test_classify_alpaca_generic_submit_error_preserves_broker_text tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_live_submit_uses_tiny_live_idempotency_key tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_duplicate_tiny_live_id_blocks_for_reconcile -q` passed with 4 tests.
  - Focused existing-order lookup check landed: `uv run --with pytest python -m pytest tests/test_alpaca_execution.py::test_classify_alpaca_duplicate_client_order_id_requires_reconciliation tests/test_alpaca_execution.py::test_classify_alpaca_generic_submit_error_preserves_broker_text tests/test_alpaca_execution.py::test_find_order_by_client_order_id_prefers_direct_broker_lookup tests/test_alpaca_execution.py::test_find_order_by_client_order_id_falls_back_to_list_orders tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_duplicate_tiny_live_id_blocks_for_reconcile -q` passed with 5 tests.
  - Focused intended-vs-existing comparison check landed: `uv run --with pytest python -m pytest tests/test_alpaca_execution.py::test_classify_alpaca_duplicate_client_order_id_requires_reconciliation tests/test_alpaca_execution.py::test_classify_alpaca_generic_submit_error_preserves_broker_text tests/test_alpaca_execution.py::test_find_order_by_client_order_id_prefers_direct_broker_lookup tests/test_alpaca_execution.py::test_find_order_by_client_order_id_falls_back_to_list_orders tests/test_alpaca_execution.py::test_compare_alpaca_order_to_intent_accepts_matching_order_summary tests/test_alpaca_execution.py::test_compare_alpaca_order_to_intent_flags_mismatch_or_unsafe_status tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_duplicate_tiny_live_id_blocks_for_reconcile tests/test_alpaca_supervisor.py::test_critical_alert_serializes_clear_exception_email tests/test_alpaca_supervisor.py::test_same_cause_alert_throttle_suppresses_duplicate_email_only tests/test_alpaca_supervisor.py::test_alert_throttle_allows_new_cause_and_stale_repeat -q` passed with 10 tests.

- [x] **Step 10.2: Reconcile-on-start for hourly live submit**
  - Pull broker positions and open orders.
  - Compare the start-of-run live snapshot to the broker state immediately before live submit.
  - Any mismatch blocks live and emits CRITICAL.
  - Helper landed: `tradingagents/execution/reconcile.py`.
  - Hourly supervisor integration landed through `tradingagents/execution/tiny_live.py`.
  - Latest hourly packet reconciliation now checks prior live submitted/reconciled `client_order_id` values against Alpaca before allowing the next live submit.
  - If the previous packet's live order is missing or mismatched at the broker, the supervisor blocks before creating any new live order.
  - Focused check landed: `uv run --with pytest python -m pytest tests/test_execution_safety.py tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_live_submit_uses_tiny_live_idempotency_key tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_blocks_when_latest_live_packet_order_is_missing tests/test_alpaca_cli.py::test_alpaca_supervise_hourly_duplicate_tiny_live_id_blocks_for_reconcile -q` passed with 11 tests.

- [x] **Step 10.3: Single-writer lock for hourly live submit**
  - Overlapping scheduled runs cannot both submit.
  - Lock timeout blocks live.
  - Helper landed: `tradingagents/execution/lock.py`.
  - Hourly supervisor acquires the lock before live submit and releases it after block, success, or broker failure.

- [x] **Step 10.4: Clock guard and dead-man for hourly live submit**
  - Broker/server clock skew beyond tolerance blocks live.
  - Missing/stale heartbeat blocks live.
  - Helper landed: `tradingagents/execution/clock.py`.
  - Alpaca live clock is checked through `AlpacaRestClient.get_clock()`.
  - Existing live-control dead-man gate remains in place.

- [x] **Step 10.5: Kill/freeze commands**
  - Existing `policy freeze-live` remains.
  - `policy freeze-live --reason ...` is the supported manual live freeze/kill path; it writes `results/policy/live_control.json`.
  - `policy refresh-live-control --reason ... --ttl-hours ...` is the supported dead-man refresh path; it does not submit orders.
  - The live gate reads this same control state, so there is one freeze/dead-man source of truth.
  - Focused tests already cover freeze-live, refresh-live-control, and frozen/dead-man live-gate blocking.

**Focused tests:**
- Duplicate idempotency key submits once.
- Overlapping supervisor lock blocks second writer.
- Reconciliation mismatch blocks live and writes a CRITICAL hourly packet.
- Clock skew blocks live.
- Dead-man stale blocks live.
- Forced drawdown halt emails CRITICAL.

---

## Phase 11 - Token And Context Efficiency After Core Stabilizes

**Intent:** After core methodology and gates are stable, compress routine context without losing evidence.

**Files:**
- Existing: `AGENTS.md`, `CONTEXT_ROUTER.md`, `TOKEN_EFFICIENCY_AUDIT.md`
- Existing/create: `scripts/automation_context_snapshot.py`
- Generated: `results/_context/`

- [x] **Step 11.1: Wait until core packet shapes stabilize**
  - Do not optimize context while schemas and gates are moving heavily.
  - Core packet shapes are stable enough for a first generated-context pass after the broad phase gate.

- [x] **Step 11.2: Re-measure context sinks**
  - Packet sizes.
  - Automation prompt sizes.
  - Automation memory sizes.
  - New research/mirror/model telemetry packet sizes.
  - `python scripts\automation_context_snapshot.py --write` regenerated `results/_context/context-manifest.json` with current guidance, automation, and latest packet size estimates.

- [x] **Step 11.3: Preserve lossless drilldown**
  - Default route:
    - `AGENTS.md`
    - `CONTEXT_ROUTER.md`
    - `results/_context/latest-summary.json`
    - `results/_context/latest-flags.json`
    - raw packets only when flagged.
  - `results/_context/latest-flags.json` now keeps raw packet paths for hourly issues/actions, failed research quality gates, and model telemetry drilldown.

- [x] **Step 11.4: Add compact summaries for new research layers**
  - Crawler summary.
  - Market mirror summary.
  - Model telemetry summary.
  - Promotion state summary.
  - Snapshot helper now summarizes capability audit, research batch, market-mirror directory, crawler run, model telemetry report, promotion state, and Agent Intelligence Ledger summary packets.
  - Current generated summary includes `capability_audit`, `research_batch`, `market_mirror`, `crawler_run`, `model_telemetry_report`, `promotion_state`, and `agent_intelligence_summary` alongside hourly/paper/overnight/premarket/verification packets.
  - Missing market-mirror and promotion-state files are shown explicitly as missing state, not hidden.
  - Focused check landed: `uv run --with pytest python -m pytest tests/test_automation_context_snapshot.py -q` passed with 2 tests.

**Focused tests:**
- Snapshot script compiles.
- Snapshot generated artifacts include new packet families.
- Raw packet paths remain available.
- Summary does not hide blockers, submissions, stale packets, schema mismatches, or changed live candidates.

---

## Phase 12 - Broad Stress And Regression Gate

**Intent:** Save expensive testing until the core is worth validating broadly, but do not skip phase-gate proof.

- [x] **Step 12.1: Run targeted slices after each phase**
  - Use the narrow tests listed in each phase.
  - Targeted slices were run through the implementation pass for alerts, live gate, execution safety, official dataflows, source quality, research orchestration, Deep Research protocol, replay/ablation, Agent Intelligence Ledger, crawler/runtime, AlphaInsider paper-shadow, model routing, and daily-report telemetry.

- [x] **Step 12.2: Run broader suites at gates**
  - Before paper submit pipeline cutover.
  - Before promotion state can mark tiny-live eligible.
  - Before any live submit path is armed.
  - Final broad gate passed: `uv run --with pytest python -m pytest -q` returned 484 passed, 1 skipped, 8 warnings, and 75 subtests.

- [x] **Step 12.3: Final stress cases**
  - Stale/missing data.
  - Connector failure.
  - Crawler blocked.
  - Model budget exhausted.
  - Zep unavailable.
  - Alpaca rejected order.
  - Reconciliation mismatch.
  - Drawdown halt.
  - Overlapping supervisor runs.
  - Same-second packet writes.
  - Secret redaction probes.
  - Covered by the broad suite plus final CLI checks; any optional missing vendor key now becomes a skipped/fallback evidence packet instead of a crash.
  - One broad-suite expectation was updated after the overnight context correctly began writing methodology and Deep Research protocol packets alongside provider fallback packets.

**Broad commands, only at phase gates:**
- `uv run --with pytest python -m pytest -q`
- `.\.venv\Scripts\tradingagents.exe alpaca verify-overnight-system --json-output`
- `.\.venv\Scripts\tradingagents.exe alpaca check`
- `.\.venv\Scripts\tradingagents.exe alpaca supervise-hourly --dry-run`

**Final phase-gate evidence:**
- Broad pytest: 484 passed, 1 skipped, 8 warnings, 75 subtests.
- Overnight verifier: `results/overnight_system_verification/overnight-system-verification-20260602-055309.json`, status `pass`.
- Capability audit: `results/capability_audits/capability-audit-20260602-105307-579641.json`, secrets redacted.
- Crawler runtime: `research crawler-runtime-doctor --json-output` reports ready, and `results/crawler_runs/crawler-run-crawler-run-e6f37ae65806419db0e6d8d18a24c7d1.json` proves a read-only Crawlee/Playwright packet.
- Model telemetry: `results/model_telemetry_reports/model-telemetry-report-20260602-113520-840871.json` records 16 pending/unresolved model-lane packets, `$0.0000` spend, and no paid auto-upgrade.
- Latest orchestration packet: `results/research_batches/research-batch-research-batch-2f4aaab74d9a4432a8e193b287a1656c.json`, with graph-memory refs, market-mirror refs, replay-plan ref, cache key, and local-model self-heal guidance.
- Latest process review: `results/process_reviews/process-review-20260602-114710.json`, unchecked long-plan item count `0`.
- Latest Deep Research protocol proof after reliable-route update: `results/research_evidence/source-evidence-source-evidence-15b05c70c2b5409aa762a06095826b56.json`; it includes dropdown and slash-picker mode routes plus save/copy/DOM/screenshot capture backups.
- Focused follow-on suite after Deep Research protocol, model caps, market mirror, graph memory, preregistration, process review, and context snapshot: `uv run --with pytest python -m pytest tests/test_deep_research_protocol.py tests/test_model_routing.py tests/test_market_mirror_memory.py tests/test_research_automation_orchestrator.py tests/test_preregistration_policy.py tests/test_process_review.py tests/test_automation_context_snapshot.py -q` passed with 39 tests.

---

## Phase 13 - External-Style Evaluation Gate

**Intent:** After the repo build and later follow-on goal are truly complete, run an evaluation pass inspired by Plugin Eval and Superpowers skill-writing discipline. This is not a substitute for trading safety tests; it is a final process/repo quality audit.

- [x] **Step 13.1: Run Plugin Eval-inspired structural audit**
  - Use `plugin-eval` ideas for:
    - frontmatter/manifest-style consistency where applicable,
    - broken links and stale references,
    - oversized docs/prompts,
    - trigger/route clarity,
    - token budget hotspots,
    - benchmark-style scenario coverage.
  - The repo is not a single plugin or skill, so adapt the method instead of forcing a plugin-shaped report.
  - Implemented `tradingagents/evals/process_review.py` and `research process-review`.
  - First generated proof: `results/process_reviews/process-review-20260602-113146.json` and `.md`.

- [x] **Step 13.2: Use `evaluate-skill` and `improve-skill` patterns**
  - Use `plugin-eval analyze` style reports for local skills/prompts if they become repo artifacts.
  - Convert findings into a concrete improvement brief before editing.
  - Compare before/after behavior when possible.
  - Adapted the patterns into the process-review artifact: required docs, unchecked items, token hotspots, findings, fix-first recommendation, and generated JSON/Markdown output.

- [x] **Step 13.3: Use Superpowers `writing-skills` ideas for automation prompts**
  - Treat recurring automation prompt/docs as process artifacts that need pressure tests.
  - Create scenarios for stale data, depleted API calls, connector failures, model budget exhaustion, and live-gate temptation.
  - Verify the automation instructions push agents toward packets, fallbacks, and fail-closed behavior.
  - Process review includes pressure scenarios for stale data, depleted API calls, connector-write temptation, model budget exhaustion, and live-gate temptation.
  - Focused check landed: `uv run --with pytest python -m pytest tests/test_process_review.py -q` passed with 2 tests.

- [x] **Step 13.4: Rerun the current eval gate after hook/n8n POC completion**
  - Current hook/n8n POC eval was run after the repo-wide build slice, token-hook POC, and n8n status-runner POC landed.
  - Rerun this gate again before any future live-submit arming, warning/blocking hook rollout, or broad automation prompt migration.
  - Run the repo-native custom eval first:
    - `python scripts/automation_context_snapshot.py --write`
    - `.\.venv\Scripts\tradingagents.exe research process-review --json-output`
    - `uv run --with pytest python -m pytest tests/test_process_review.py tests/test_automation_context_snapshot.py tests/test_deep_research_protocol.py -q`
  - If any repo-local Codex skills or plugin-like artifacts exist, run Plugin Eval directly on those artifacts:
    - `plugin-eval analyze <skill-or-plugin-path> --format markdown`
    - `plugin-eval explain-budget <skill-or-plugin-path> --format markdown`
    - `plugin-eval init-benchmark <skill-or-plugin-path>` when benchmark scenarios are missing.
  - If Plugin Eval produces findings for a local skill, use the `plugin-eval:improve-skill` pattern before editing:
    - group required fixes versus recommended fixes,
    - write a concrete improvement brief,
    - apply the smallest fix set,
    - rerun `plugin-eval analyze`,
    - compare before/after behavior with `plugin-eval compare` when JSON reports exist.
  - For non-skill repo surfaces, do not force a plugin-shaped report. Use custom evals and process-review packets to inspect:
    - safety gaps,
    - stale docs,
    - missing tests,
    - token/context hotspots,
    - broken packet routes,
    - automation prompt drift,
    - live-gate temptation,
    - social/crawler write-risk,
    - source fallback behavior.
  - Save the final audit summary under `reports/orchestration/` and the machine-readable packet under `results/process_reviews/`.
  - Treat any high-severity finding as a new fix task before declaring the build complete.
  - Latest process review: `results/process_reviews/process-review-20260602-181024.json`, unchecked long-plan item count `0`, only remaining finding is that large raw packets are token hotspots.
  - Latest focused eval suite: `uv run --with pytest python -m pytest tests/test_process_review.py tests/test_automation_context_snapshot.py tests/test_deep_research_protocol.py tests/test_token_context_hooks.py tests/test_n8n_runner_policy.py -q` passed with 16 tests.
  - Hook/n8n focused suite plus supervisor/email checks passed with 48 tests.
  - Audit summary: `reports/orchestration/TOKEN_HOOK_FINAL_EVAL.md`.

---

## Latest Controller And Email Clarity Slice - 2026-06-02

- Night-shift supervisor is present and active:
  - id: `tradingagents-night-shift-supervisor`
  - schedule: `RRULE:FREQ=WEEKLY;BYHOUR=0,4,20;BYMINUTE=15;BYDAY=SU,MO,TU,WE,TH,FR,SA`
  - plain meaning: it patrols around 8:15 PM, 12:15 AM, and 4:15 AM America/Chicago each day.
  - role: keep high-frequency hourly/paper jobs asleep overnight, keep overnight planning active when the next market morning is useful, and report unknown/follow-up jobs without touching them.
- Current automation snapshot proof:
  - `hourly-market-supervisor`: `PAUSED`
  - `paper-strategy-tournament-runner`: `PAUSED`
  - `tradingagents-overnight-planning`: `ACTIVE`
  - `tradingagents-night-shift-supervisor`: `ACTIVE`
  - one-off Deep Research follow-up is classified as `one_off_followup`, not an unknown TradingAgents market job.
- Urgent/blocker emails were tightened in `tradingagents/brokers/alpaca_supervisor.py`:
  - starts directly with `Plain English`, not a redundant title line,
  - says whether live money moved,
  - adds compact `Money today`, `Live account`, and `Paper account` sections,
  - lists the current blocker as `Problem: ...`,
  - asks only one ops-level question,
  - says Codex will self-heal safe setup problems and otherwise keep trading blocked.
- Focused proof:
  - `uv run --with pytest python -m pytest tests/test_alpaca_supervisor.py::test_critical_alert_serializes_clear_exception_email tests/test_alpaca_supervisor.py::test_urgent_exception_notification_policy tests/test_email_clarity_eval.py -q` passed with 6 tests.
  - `.\.venv\Scripts\python.exe -m py_compile tradingagents\brokers\alpaca_supervisor.py tradingagents\evals\email_clarity.py` passed.
  - Sample CRITICAL blocker body is 24 lines and passes `evaluate_email_clarity(..., report_type="urgent")`.

## Latest BOARD Anti-Freeze Slice - 2026-06-03

- Problem found: the BOARD correctly remembered older paired sell+buy/chase-buy mistakes, but the `pause_new_buys_and_review` recommendation could keep new buys frozen even after newer packets proved the anti-chase and independent-sell fixes were working.
- Change:
  - `tradingagents/evals/execution_board.py` now tracks per-packet review counts and `clean_packets_since_last_violation`.
  - If hard issues are still too recent, `new_buy_policy.state=paused` and supervisors keep new buys blocked.
  - If at least two clean packets appear after the latest hard issue, recommendation becomes `continue_with_guardrails_after_clean_streak` and `new_buy_policy.state=probation_allowed`.
  - Probation still allows only controlled dip/support buys; historical violations remain in the lesson list.
  - n8n parsed summaries and compact context expose `new_buy_state` and `clean_packets_since_last_violation`.
- Real current proof:
  - `.\.venv\Scripts\tradingagents.exe research execution-board-review --json-output` returned `recommendation=continue_with_guardrails_after_clean_streak`, `new_buy_state=probation_allowed`, and `clean_packets_since_last_violation=11`.
  - Daily preview now says: `BOARD review: earlier mistakes are still being watched, but new controlled-dip buys are allowed again. Clean packets since latest hard issue: 11. Sells still work independently.`
  - Daily preview remains 46 lines with `email_clarity.status=pass`, `score=100`, and `board_new_buys_paused=false`.
  - Compact context now shows `execution_board_review.new_buy_state=probation_allowed`.
- Focused proof:
  - `uv run --with pytest python -m pytest tests/test_execution_board.py tests/test_n8n_runner_policy.py tests/test_automation_context_snapshot.py -q` passed with 17 tests.
  - `.\.venv\Scripts\python.exe -m py_compile tradingagents\evals\execution_board.py tradingagents\orchestration\n8n_runner.py cli\main.py scripts\automation_context_snapshot.py` passed.
  - Follow-up focused suite: `uv run --with pytest python -m pytest tests/test_execution_board.py tests/test_n8n_runner_policy.py tests/test_automation_context_snapshot.py tests/test_email_clarity_eval.py -q` passed with 21 tests.
  - Process-review proof: `.\.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job process_review --json` wrote `results\process_reviews\process-review-20260603-000526.json`, returned `unchecked_step_count=0`, `can_submit_orders=false`, `submit_capable=false`, and only repeated the known raw-packet token hotspot.

## Latest Model-Telemetry False-Alarm Slice - 2026-06-03

- Problem found: optional Windows/Mac Ollama setup errors were still opening the model telemetry drilldown flag even when the model report said deterministic/free fallback was safe and spend was `$0.0000`.
- Change:
  - `scripts/automation_context_snapshot.py` now treats `windows_local_ollama` and `mac_ollama_research_mule` route errors as advisory when they are the only model issue.
  - Compact context still reports blocked local routes, recent error count, and operator summary.
  - The model telemetry flag remains active for non-local model errors, harmful/hurt outcomes, or exhausted model budget.
- Real current proof:
  - `results/_context/latest-summary.json` shows `model_telemetry_report.hard_model_issue=false`, `advisory_local_model_only=true`, and `recent_errors=8`.
  - `results/_context/latest-flags.json` no longer includes `model_telemetry_report`; later cleanup slices leave current compact flags empty.
- Focused proof:
  - `uv run --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_model_routing.py -q` passed with 24 tests.
  - `.\.venv\Scripts\python.exe -m py_compile scripts\automation_context_snapshot.py tradingagents\research\model_telemetry.py` passed.
  - Combined follow-up suite: `uv run --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_model_routing.py tests/test_execution_board.py tests/test_n8n_runner_policy.py tests/test_email_clarity_eval.py -q` passed with 41 tests.
  - Latest process review: `results\process_reviews\process-review-20260603-001148.json`, unchecked step count `0`, `can_submit_orders=false`, and only the known raw-packet token hotspot remains.

## Latest Promotion-State False-Alarm Slice - 2026-06-03

- Problem found: compact context flagged `promotion_state` every time a sleeve was already `live_enabled`, even when the state was clean and stable.
- Change:
  - Stable clean live-enabled sleeves now stay visible in `latest-summary.json` but do not force a drilldown.
  - Promotion-state issues still trigger the `candidate_change` drilldown flag.
  - The guidance text now says to open promotion state when issues appear or live-enabled sleeves unexpectedly change.
- Real current proof:
  - `results/_context/latest-summary.json` still shows `live_enabled_sleeves=["current-aggressive"]` and `issue_count=0`.
  - `results/_context/latest-flags.json` later returned to `flags=[]` after BOARD historical lessons became summary-only.
- Focused proof:
  - `uv run --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_promotion_policy.py -q` passed with 11 tests.
  - `.\.venv\Scripts\python.exe -m py_compile scripts\automation_context_snapshot.py tradingagents\policy\promotion.py` passed.
  - Combined follow-up suite: `uv run --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_promotion_policy.py tests/test_model_routing.py tests/test_execution_board.py tests/test_n8n_runner_policy.py tests/test_email_clarity_eval.py -q` passed with 47 tests.
  - Latest process review: `results\process_reviews\process-review-20260603-001750.json`, unchecked step count `0`, `can_submit_orders=false`, and only the known raw-packet token hotspot remains.

## Latest BOARD Context Flag Cleanup - 2026-06-03

- Problem found: compact context still treated older BOARD violations as an active drilldown reason even after the BOARD had moved to clean-streak probation.
- Change:
  - `scripts/automation_context_snapshot.py` now separates `board_hard_issue` from `historical_lessons_only`.
  - Historical BOARD lessons stay visible in `latest-summary.json`, including `new_buy_state`, `clean_packets_since_last_violation`, and violation/warning types.
  - `latest-flags.json` now opens BOARD only when new buys are actively paused, unsafe order statuses appear, or underperformers need fresh review.
- Real current proof:
  - `results/_context/latest-summary.json` shows `execution_board_review.new_buy_state=probation_allowed`, `clean_packets_since_last_violation=11`, `historical_lessons_only=true`, and `board_hard_issue=false`.
  - `results/_context/latest-flags.json` shows `flags=[]` and `next_open=[]`.
- Focused proof:
  - `uv run --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_execution_board.py tests/test_n8n_runner_policy.py -q` passed with 22 tests.
  - `.\.venv\Scripts\python.exe -m py_compile scripts\automation_context_snapshot.py tradingagents\evals\execution_board.py tradingagents\orchestration\n8n_runner.py` passed.
  - Combined follow-up suite: `uv run --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_promotion_policy.py tests/test_model_routing.py tests/test_execution_board.py tests/test_n8n_runner_policy.py tests/test_email_clarity_eval.py -q` passed with 49 tests.
  - Latest process review: `results\process_reviews\process-review-20260603-002922.json`, unchecked step count `0`, `can_submit_orders=false`, and only the known raw-packet token hotspot remains.

## Latest Outcome-Labeling Slice - 2026-06-03

- Problem found: the repo had Agent Intelligence forecasts, model telemetry packets, and market-mirror packets, but no reusable command that applied resolved outcomes back into model/mirror usefulness labels for n8n/dashboard consumption.
- Change:
  - `summarize_agent_scores()` now includes `resolved_forecast_count`, `outcome_counts`, and per-agent useful/harmful/pending counts.
  - `label_model_telemetry_from_agent_outcomes()` labels model runs only when a telemetry packet explicitly references resolved Agent Intelligence forecast ids.
  - `label_market_mirror_outcome()` labels whether mirror caution helped or hurt after same-symbol forecasts resolve, while preserving `execution_authority=none`.
  - New CLI command: `research outcome-labeling`.
  - New n8n allowlisted job: `outcome_labeling`, `submit_capable=false`.
  - Compact context exposes ledger outcome counts without opening raw packets or forcing drilldown.
- Real current proof:
  - `.\.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job outcome_labeling --json` returned `status=ok`, `forecast_count=129`, `resolved_forecast_count=0`, `resolved_model_run_count=0`, model outcomes `{"unresolved": 16}`, and market mirror `pending/unresolved` with `execution_authority=none`.
  - Serial snapshot refresh shows `results/_context/latest-flags.json` with `flags=[]`.
  - Current ledger summary shows `resolved_forecast_count=0`; future after-close/weekly runs can label outcomes once forecasts are due and price evidence resolves.
- Focused proof:
  - `uv run --with pytest python -m pytest tests/test_agent_intelligence_ledger.py tests/test_model_routing.py tests/test_market_mirror_memory.py tests/test_automation_context_snapshot.py tests/test_alpaca_cli.py::test_research_outcome_labeling_writes_model_and_mirror_labels tests/test_n8n_runner_policy.py -q` passed with 55 tests.
  - `.\.venv\Scripts\python.exe -m py_compile cli\main.py scripts\automation_context_snapshot.py tradingagents\evals\agent_intelligence_ledger.py tradingagents\research\model_telemetry.py tradingagents\research\market_mirror.py tradingagents\schemas\research.py tradingagents\orchestration\n8n_runner.py` passed.
  - Latest process review: `results\process_reviews\process-review-20260603-004746.json`, unchecked step count `0`, `can_submit_orders=false`, and only the known raw-packet token hotspot remains.

## Latest MiroFish Handoff Status Slice - 2026-06-03

- Problem found: the repo had a pending MiroFish scaffold, but future automations had no compact, machine-readable way to know whether the external MiroFish run had produced a final TradingAgents handoff.
- Change:
  - Added `tradingagents/research/mirofish_handoff.py`.
  - New CLI command: `research mirofish-handoff-status`.
  - New result root: `results/mirofish_handoff/`.
  - New n8n allowlisted job: `mirofish_handoff_status`, `submit_capable=false`.
  - `automation_context_snapshot.py` now summarizes `mirofish_handoff_status` without opening the scaffold or flagging normal pending status.
  - The packet explicitly preserves `analysis_only=true`, `execution_authority=none`, `agpl_code_import_allowed=false`, `source_code_imported=false`, and forbidden effects for trade intent, sizing, orders, promotion, and live-gate waivers.
- Real current proof:
  - `.\.venv\Scripts\python.exe -m cli.main research mirofish-handoff-status --json-output` wrote `results\mirofish_handoff\research-intel-research-intel-f5b2c8db3a6444feb6f5b834dff06d0d.json` and returned `status=pending_final_handoff`, `final_handoff_available=false`, `artifact_path_count=10`, `missing_piece_count=5`, `execution_authority=none`.
  - `.\.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job mirofish_handoff_status --json` returned `status=ok`, `submit_capable=false`, compact parsed summary `pending_final_handoff`, and packet `results\mirofish_handoff\research-intel-research-intel-11741213844e48a0ac0514d6e933c165.json`.
  - Compact context refresh shows `results/_context/latest-summary.json` includes `mirofish_handoff_status` with `drilldown_required=false`, and `results/_context/latest-flags.json` has `flags=[]`.
- Focused proof:
  - `uv run --with pytest python -m pytest tests/test_mirofish_handoff.py tests/test_n8n_runner_policy.py tests/test_automation_context_snapshot.py -q` passed with 23 tests.
  - `python -m py_compile tradingagents\research\mirofish_handoff.py tradingagents\orchestration\n8n_runner.py scripts\automation_context_snapshot.py cli\main.py` passed.

## Latest Hook Goal Metadata Slice - 2026-06-03

- Problem found: repo-local Codex hooks refreshed compact context and wrote redacted event packets, but future agents still had to open hook payloads to tell which goal, subagent, or run caused the event.
- Change:
  - `write_hook_event()` now records compact `hook_context` metadata: thread id, goal status, goal objective excerpt, truncation flag, agent id/name/role, and run id.
  - Hook packets now update `results/_context/hook-events/latest.json`.
  - `automation_context_snapshot.py` now summarizes the latest `hook_event` without copying `payload_sample`.
  - Hook output remains context-only: it cannot trade, approve, promote, cancel, or read secrets.
- Real current proof:
  - Ran `.venv\Scripts\python.exe .codex\hooks\token_context_hook.py` with a fake `SubagentStart` payload.
  - It wrote `results\_context\hook-events\hook-event-20260603-013215-067501.json`.
  - The latest hook summary includes `agent_name=Sentinel`, `goal_status=active`, `raw_context_required=false`, and the fake `api_key` was redacted in the packet.
  - Compact context refresh shows `hook_event` in `results/_context/latest-summary.json` and `results/_context/latest-flags.json` still has `flags=[]`.
- Focused proof:
  - RED tests failed first for missing `hook_context`, missing `latest.json`, and missing `hook_event` snapshot fields.
  - `uv run --with pytest python -m pytest tests/test_token_context_hooks.py tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py -q` passed with 27 tests.
  - `python -m py_compile tradingagents\orchestration\token_context.py scripts\automation_context_snapshot.py .codex\hooks\token_context_hook.py` passed.

---

## Subagent Usage Policy

- Main thread remains orchestrator.
- Use `gpt-5.4-mini` for bounded mapping, telemetry, schema, and test-plan sidecars.
- Use stronger fixed-role agents only for architecture/reviewer moments where correctness risk is high.
- Do not dispatch overlapping implementers to the same file set.
- Subagents must not print secrets or modify files outside their assigned scope.
- Review subagent results before integrating.

---

## Completion Definition

The first major milestone is complete when:

- Pullback-support paper loop can place or refuse paper trades deterministically.
- Every decision writes a packet.
- Email alerts are clear and ops-only.
- Unified live gate blocks all live paths except fully armed tiny-live.
- Promotion state and risk envelope are enforced.
- Market mirror and model outputs are advisory-only with telemetry.
- Paid model routes are capped and disabled by default for scheduled automations.
- Zep is optional and local memory fallback works.
- Forced drawdown halt and reconciliation mismatch produce CRITICAL email.
- Targeted tests pass, then broad regression passes at the phase gate.
