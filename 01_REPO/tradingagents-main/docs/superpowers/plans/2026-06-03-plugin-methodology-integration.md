# Plugin Methodology Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` for multi-file implementation slices or `superpowers:executing-plans` for focused inline execution. Keep this plan updated as work lands.

**Goal:** Convert the useful parts of Superpowers, Plugin Eval, Public Equity Investing, Data Analytics, AlphaInsider, Alpaca, Binance, and Deep Research into durable TradingAgents methodology, automation, and eval surfaces without weakening broker safety or adding noisy/token-heavy runtime paths.

**Architecture:** Plugins and skills are advisory inputs. The Python repo remains the trading authority. n8n and Codex hooks remain a context/notification/control-plane wrapper. Public-equity and data-analytics ideas become deterministic repo methodology and eval checks. AlphaInsider and Binance remain read-only or paper-only evidence lanes unless a later explicit operator approval changes that. No plugin, hook, n8n workflow, browser run, social connector, or Deep Research report may submit, approve, size, promote, or cancel live orders.

**Tech Stack:** Existing Typer CLI, `results/_context/`, `tradingagents/orchestration`, `tradingagents/evals`, `tradingagents/dataflows`, existing Alpaca execution gate, ignored environment variables for secrets, bundled Plugin Eval Node script when the global CLI is unavailable, and focused pytest slices.

---

## Findings From Skill And Report Review

- Superpowers should guide build discipline: read skill guidance before major work, brainstorm for open design, write implementation plans with exact files/tests, and use TDD for risky code paths.
- Plugin Eval is useful as a process pattern, but this repo is not a single skill/plugin. Use repo-native process review for trading surfaces and Plugin Eval only on actual skill/plugin-like artifacts.
- Public Equity Investing contributes the strongest trading-methodology vocabulary: thesis pillars, priced-in view, variant wedge, catalyst path, invalidators, action thresholds, scenario skew, PM action verbs, and separation of company quality from security/action readiness.
- Data Analytics contributes the source-quality layer: freshness, grain, nulls, duplicates, schema drift, broken joins, backfills, source mismatch, severity, confidence, and remediation.
- AlphaInsider belongs in this phase as a paper-only shadow and strategy-allocation reference. Do not route live broker authority through it.
- Investment Banking is not a runtime trading plugin for this repo. Its useful borrowings are evidence control, model tie-out, source traceability, and artifact QA.
- Binance is currently a read-only public-market plugin route. Treat it as optional crypto/liquidity/risk-sentiment context, not as an account or order path.
- Deep Research reports agree with the repo direction: official/primary data first, point-in-time discipline, sleeve-specific intents, paper promotion gates, and deterministic execution policy between agents and Alpaca.

## Already Landed In This Slice

- [x] **Process-review scans all Superpowers plans**
  - Files:
    - `tradingagents/evals/process_review.py`
    - `tests/test_process_review.py`
  - Outcome: `build_process_review()` now scans every `docs/superpowers/plans/*.md` file and reports plan doc count plus unchecked items with filename prefixes.
  - Proof: `uv run --with pytest python -m pytest tests/test_process_review.py tests/test_n8n_runner_policy.py tests/test_token_context_hooks.py -q` passed with 23 tests.

- [x] **n8n allowlist rejects broker-capable drift**
  - Files:
    - `tradingagents/orchestration/n8n_policy.py`
    - `tests/test_n8n_runner_policy.py`
  - Outcome: non-submit n8n jobs now reject unsafe Alpaca, paper-tournament, generic submit/order, and compact-output-only submit-capable command shapes.
  - Proof: same 23-test focused suite passed.

- [x] **Codex hook parser recognizes native hook event shapes**
  - Files:
    - `.codex/hooks/token_context_hook.py`
    - `tests/test_token_context_hooks.py`
  - Outcome: hook event detection now supports `hook_event_name`, `hookEventName`, `event_name`, and nested hook metadata while preserving `CODEX_HOOK_EVENT` precedence.
  - Proof: same 23-test focused suite passed, plus `py_compile` passed for changed Python files.

## API Key Handling

- [x] **Record only names and capabilities, never values**
  - Current key families observed from the provided material and process environment: Alpaca live/paper, Alpha Vantage, AlphaInsider, BEA, BLS, Composio, EIA, FRED, Gemini/Google, Hugging Face, OpenAI, OpenRouter, SEC user agent, Zep, and local-model routing variables.
  - Missing or not currently wired as first-class repo integrations: Binance account keys, Benzinga, Finnhub, EODHD, FMP, Massive/Polygon, Marketaux, NewsAPI, ScrapingBee, Tiingo.
  - Rule: code/docs may mention variable names and required purpose only. Do not print, commit, or store secret values.

- [x] **Add repo-local integration capability registry**
  - Created: `config/research_integrations.example.json`
  - Created: `tradingagents/dataflows/integration_registry.py`
  - Created: `tests/test_integration_registry.py`
  - Modified: `cli/main.py`
  - Modified: `tests/test_alpaca_cli.py`
  - Include:
    - provider name
    - env var names
    - free/paid/unknown tier
    - read/write authority
    - trading authority always `none` except Alpaca broker boundary
    - source priority
    - request-budget/fallback behavior
  - Test:
    - missing optional keys produce skipped-source evidence, not crashes
    - secret values are never serialized
    - depleted limited APIs fall back to cache/free routes when configured
  - Proof:
    - `uv run --with pytest python -m pytest tests/test_integration_registry.py tests/test_alpaca_cli.py::test_integrations_doctor_redacts_env_and_writes_packet -q`
    - Result: 5 passed.
    - `.\.venv\Scripts\python.exe -m py_compile tradingagents\dataflows\integration_registry.py cli\main.py`

## Public Equity Methodology Layer

- [x] **Add sleeve thesis contract**
  - Modify/create:
    - `tradingagents/schemas/research.py`
    - `tradingagents/evals/agent_intelligence_ledger.py`
    - `tests/test_agent_intelligence_ledger.py`
  - Add structured fields where missing:
    - `thesis_pillars`
    - `variant_wedge`
    - `priced_in_view`
    - `catalyst_path`
    - `invalidators`
    - `action_thresholds`
    - `scenario_skew`
    - `pm_action`
  - Rule: a thesis can improve influence only after resolved outcomes validate it by sleeve, regime, ticker/sector, evidence type, and horizon.
  - Proof:
    - `uv run --with pytest python -m pytest tests/test_agent_intelligence_ledger.py tests/test_alpaca_cli.py::test_research_agent_ledger_from_overnight_writes_forecasts -q`
    - Result: 8 passed.
  - Note: this completed the forecast/role thesis contract in `AgentForecast`. The broader paper sleeve scorecard variants remain tracked by the separate "Turn popular strategies into explicit sleeve scorecards" item.

- [x] **Turn popular strategies into explicit sleeve scorecards**
  - Modify:
    - `TRADING_METHODS_AND_AUTOMATIONS.md`
    - `tradingagents/brokers/paper_tournament.py`
    - `tests/test_paper_tournament.py`
  - Track paper-only scorecards for:
    - pullback support
    - earnings drift / estimate revision
    - event underreaction
    - pairs/co-movement residuals
    - news/sentiment swing
    - macro regime overlay
    - AlphaInsider-style allocation shadow
  - Rule: paper may explore broad strategy variants; live only mirrors promoted sleeves that pass deterministic gates.
  - Result: `build_popular_strategy_scorecards(...)` now emits paper-only scorecards for all listed variants and `build_tournament_report(...)` attaches them as `popular_strategy_scorecards`.
  - Proof:
    - `uv run --with pytest python -m pytest tests/test_paper_tournament.py::test_tournament_report_includes_popular_strategy_scorecards_with_authority_boundaries -q`
    - `uv run --with pytest python -m pytest tests/test_paper_tournament.py -q`
    - `.\.venv\Scripts\python.exe -m py_compile tradingagents\brokers\paper_tournament.py tests\test_paper_tournament.py`
  - Result detail: the suite passed with 10 tests; a stale advisory-selection assertion was updated after the current controlled-dip logic correctly returned a dry-run `buy` decision with no submitted orders.

## Data Analytics Quality Layer

- [x] **Add source-quality eval packets**
  - Created:
    - `tradingagents/evals/source_quality.py`
  - Modified:
    - `tests/test_source_quality.py`
    - `tests/test_n8n_runner_policy.py`
    - `tradingagents/orchestration/n8n_policy.py`
    - `tradingagents/orchestration/n8n_runner.py`
    - `config/n8n_tradingagents_allowlist.json`
    - `cli/main.py`
  - Added CLI:
    - `research source-quality-review --json-output`
  - Added n8n allowlist job:
    - `source_quality_review`, `submit_capable=false`
  - Evaluate:
    - freshness
    - grain mismatch
    - null/duplicate rates
    - schema drift
    - broken joins/entity mapping
    - backfill/revision risk
    - source mismatch across redundant providers
  - Output compact summaries to `results/_context/`; open raw source packets only on flagged quality failures.
  - Proof:
    - `uv run --with pytest python -m pytest tests/test_source_quality.py tests/test_integration_registry.py tests/test_n8n_runner_policy.py -q`
    - Result: 26 passed.
    - `.\.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job source_quality_review --json`
    - Result: `status=ok`, `submit_capable=false`, wrote `results\source_quality\source-quality-review-20260603-030556.json`.

## AlphaInsider Paper-Only Lane

- [x] **Verify and document paper-only weekly rotation**
  - Modify:
    - `tradingagents/brokers/paper_tournament.py`
    - `tradingagents/dataflows/alphainsider.py`
    - `TRADING_METHODS_AND_AUTOMATIONS.md`
  - Requirements:
    - `execution_authority=none`
    - `paper_only=true`
    - no live broker calls
    - no third-party bot/order/webhook endpoints
    - weekly strategy refresh schedule can use RRULE format
    - paper allocation is not capped by live-money rules
  - Test:
    - AlphaInsider missing key skips cleanly
    - strategy metadata does not expose raw normalized strategy values
    - paper shadow packets cannot route to live submit code
  - Proof:
    - `uv run --with pytest python -m pytest tests/test_mirofish_handoff.py tests/test_paper_tournament.py::test_alphainsider_paper_watch_uses_only_remaining_paper_budget tests/test_paper_tournament.py::test_alphainsider_paper_watch_builds_shadow_orders_from_strategy_tickers tests/test_paper_tournament.py::test_paper_tournament_alphainsider_watch_writes_paper_only_packet -q`
    - Result: 5 passed.

## Binance And Crypto Context

- [x] **Add optional read-only Binance context classification**
  - Create/modify:
    - `config/research_integrations.example.json`
    - `TRADING_METHODS_AND_AUTOMATIONS.md`
  - Do not add account/trading behavior.
  - Use cases:
    - broad risk-on/risk-off liquidity context
    - crypto-beta sensitivity for certain equities
    - weekend/macro sentiment background
  - Test:
    - Binance disabled/missing route records `route_unavailable`
    - Binance evidence packets have `execution_authority=none`
  - Proof:
    - `uv run --with pytest python -m pytest tests/test_integration_registry.py tests/test_alpaca_cli.py::test_integrations_doctor_redacts_env_and_writes_packet -q`
    - Result: 5 passed.

## Hooks And n8n Control Plane

- [x] **Add warning-only PreToolUse hook after payload proof**
  - Modify:
    - `.codex/hooks/hooks.json`
    - `.codex/hooks/token_context_hook.py`
    - `tests/test_token_context_hooks.py`
  - Warn on broad raw packet reads, full automation memories, Deep Research reports, and `.env` reads when compact context should be used first.
  - First version must be warning-only and context-only.
  - Result: `.codex/hooks/hooks.json` now has a `PreToolUse` hook that calls `.codex/hooks/token_context_hook.py`; `tradingagents/orchestration/token_context.py` classifies broad raw packet reads, broad `results` searches, automation memories, Deep Research reports, and `.env` reads as `warning_only=true` with `block_execution=false`.
  - Proof:
    - `uv run --with pytest python -m pytest tests/test_token_context_hooks.py tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py -q`
    - `.\.venv\Scripts\python.exe -m py_compile tradingagents\orchestration\token_context.py .codex\hooks\token_context_hook.py scripts\automation_context_snapshot.py tradingagents\orchestration\n8n_runner.py tradingagents\orchestration\n8n_policy.py`
    - Manual fake `PreToolUse` payload returned `0`, wrote `results\_context\hook-events\hook-event-20260603-034001-934940.json`, printed `pre_tool_warning=warning_only`, and redacted `api_key`.

- [x] **Add n8n source/eval dashboard workflow map**
  - Create:
    - `docs/orchestration/n8n-workflow-map.md`
  - Include:
    - hourly supervisor observer
    - paper tournament observer
    - overnight planner observer
    - pre/post open/close observers
    - daily report preview
    - source quality review
    - outcome labeling
    - execution BOARD review
    - manual emergency context snapshot
  - Rule: n8n calls `python -m tradingagents.orchestration.n8n_runner --run-job ...`; it does not receive arbitrary shell access.
  - Result: `docs/orchestration/n8n-workflow-map.md` now documents n8n as an observer/control-plane wrapper, the local execution bridge, compact-context rules, workflow map, phased migration path, and smallest POC.
  - Proof:
    - `uv run --with pytest python -m pytest tests/test_n8n_runner_policy.py::test_n8n_workflow_map_documents_observer_layer_and_runner -q`
    - `uv run --with pytest python -m pytest tests/test_n8n_runner_policy.py -q`

## Evaluation Gate

- [x] **Run repo-native evals after each implementation slice**
  - Commands:
    - `python scripts/automation_context_snapshot.py --write`
    - `.\.venv\Scripts\tradingagents.exe research process-review --json-output`
    - `uv run --with pytest python -m pytest tests/test_process_review.py tests/test_n8n_runner_policy.py tests/test_token_context_hooks.py -q`
  - Add slice-specific tests for every new module.
  - Result: this phase ran focused tests and compile checks after each hook, scorecard, n8n, source-quality, creator-workflow, and ledger slice.
  - Latest process review proof: `.\.venv\Scripts\tradingagents.exe research process-review --json-output` wrote `results\process_reviews\process-review-20260603-035421.json`, `can_submit_orders=false`, with 16 remaining documented plan items.

- [x] **Use bundled Plugin Eval only for skill/plugin artifacts**
  - Global `plugin-eval` is not available on this machine right now.
  - Use:
    - `node C:\cm\plugins\cache\openai-curated\plugin-eval\5e86d584\scripts\plugin-eval.js --help`
    - `node C:\cm\plugins\cache\openai-curated\plugin-eval\5e86d584\scripts\plugin-eval.js analyze <skill-or-plugin-path> --format markdown`
  - If a repo-local skill is created later, evaluate it with Plugin Eval, apply the `improve-skill` pattern, then rerun.
  - Do not pretend Plugin Eval validates live trading behavior; use repo-native safety tests for that.
  - Result: used bundled Plugin Eval only as advisory structural analysis on `docs/superpowers/plans`, not as trading validation.
  - Proof: `node C:\cm\plugins\cache\openai-curated\plugin-eval\5e86d584\scripts\plugin-eval.js analyze docs\superpowers\plans --format markdown > reports\orchestration\ENDGAME_PLANS_PLUGIN_EVAL.md`.
  - Finding: score `86/100`, grade `B`, high risk only because the plan directory has excessive deferred token cost. Mitigation follows the `improve-skill` pattern: keep `CONTEXT_ROUTER.md`, the active endgame plan, and process-review packets as the compact route, and do not bulk-load all plan docs unless a process-review item requires it.

- [x] **Run advisory Plugin Eval pass on plan directory**
  - Output:
    - `reports/orchestration/PLUGIN_METHODOLOGY_PLAN_PLUGIN_EVAL.md`
    - `reports/orchestration/PLUGIN_METHODOLOGY_PLANS_ANALYZE.md`
  - Result: grade `B`, score `86/100`, risk `high` only because the plan directory has about `38,826` deferred tokens.
  - Mitigation: future agents should start from `CONTEXT_ROUTER.md`, then open only this active plan and the specific plan file named by process-review. Do not bulk-load every historical plan doc.

## What Must Stay Inside Python

- Alpaca account checks, dry-runs, submit gates, reconciliation, stock-only/limit-only enforcement, sizing, promotion, source-quality packet creation, paper tournament scoring, outcome labeling, and BOARD decisions.
- n8n, hooks, Browser, Composio, Binance, AlphaInsider, Data Analytics, Public Equity, and Deep Research may enrich or audit evidence. They do not execute trades.

## Completion Criteria For This Plan

- Integration registry exists and tests prove optional keys skip cleanly without leaking secrets.
- Public-equity thesis fields are captured in forecasts or sleeve scorecards and resolve through the Agent Intelligence Ledger.
- Data-quality review emits compact packets and n8n can run it as `submit_capable=false`.
- AlphaInsider weekly paper-only lane is documented and tested as unable to route live.
- Binance is documented as optional read-only context or explicitly left unwired with a tested `route_unavailable` packet.
- n8n workflow map exists and keeps n8n as observer/controller, not scheduler replacement for Python trading logic.
- Process-review reports unfinished plan items across all plan docs until they are actually done.
- Focused tests, compile checks, process review, and any applicable Plugin Eval artifact review pass before this plan is marked complete.
