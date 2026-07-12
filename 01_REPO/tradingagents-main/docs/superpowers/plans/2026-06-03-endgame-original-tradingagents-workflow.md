# Endgame Original TradingAgents Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` for multi-file implementation slices or `superpowers:executing-plans` for focused inline execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the original TradingAgents creator workflow a first-class, runnable, persisted, scored research pipeline inside this repo while keeping our data adapters, Agent Intelligence Ledger, source-quality checks, n8n/hooks, paper tournament, and Alpaca safety gates as the execution authority.

**Architecture:** Do not replace the creator graph. Run `TradingAgentsGraph.propagate(...)` as the creator pipeline lane, preserve every role output as structured artifacts, convert role claims into scoreable ledger forecasts, and feed only compact summaries into `results/_context/`. Our overlays add official/free data, source quality, market mirror, plugin methodology, paper-only strategy experiments, and deterministic execution policy; they do not let agents, plugins, hooks, n8n, or Deep Research submit or approve live orders.

**Tech Stack:** Python 3, Typer CLI, existing `TradingAgentsGraph`, existing overnight planner, `tradingagents/schemas/research.py`, `tradingagents/evals/agent_intelligence_ledger.py`, `tradingagents/research/source_quality.py`, `tradingagents/orchestration/n8n_runner.py`, `.codex/hooks/`, `results/_context/`, and focused pytest suites.

---

## Current Goal Anchor

Active goal: complete the TradingAgents market-ready endgame build by integrating the original TradingAgents multi-agent workflow, official/free data adapters, compact context, Agent Intelligence Ledger, source-quality, n8n, hooks, Mirror Fish handoff ingestion, paper strategy tournament, AlphaInsider paper-shadow, buy-dip/sell-spike behavior, uncapped-live-budget policy, and deterministic Alpaca safety gates.

This plan is the compact source of truth for the remaining endgame work. Future agents should start from:

1. `AGENTS.md`
2. `CONTEXT_ROUTER.md`
3. `results/_context/latest-summary.json`
4. this plan

Open older plans only when process-review names an unchecked item that cannot be understood from this file.

## Non-Negotiable Boundaries

- `TradingAgentsGraph` is research authority only.
- Alpaca execution remains `alpaca check -> dry-run -> submit only if clean`.
- Live budget is uncapped by repo dollar limits in `autonomous_uncapped` mode, but broker buying power, reconciliation, promotion, stock-only, limit-only, live-control, and risk-envelope gates still apply.
- Old PDT day-count, old `$25k` PDT minimum, PDT designation, and old day-trading-buying-power blockers must not be reintroduced for the June 4, 2026 intraday-margin regime.
- n8n uses `python -m tradingagents.orchestration.n8n_runner --run-job ...`; it never receives arbitrary shell or direct broker credentials.
- Hooks refresh/write compact context only. Hooks must not read secrets, place trades, promote sleeves, cancel orders, or approve live actions.
- Plugins and skills are methodology/eval inputs. They are not runtime trading authority.
- AlphaInsider stays paper-only shadow/strategy reference.
- Binance stays read-only public-market context unless a later explicit request adds a different boundary.

## File Responsibilities

- `tradingagents/research/original_workflow.py`: reusable extraction and writer for creator workflow role artifacts.
- `tests/test_original_tradingagents_workflow.py`: tests artifact writing, compact packet shape, forbidden effects, and overnight summary integration.
- `cli/main.py`: call the reusable writer from overnight graph runs and keep interactive report saving compatible.
- `tradingagents/evals/agent_intelligence_ledger.py`: convert creator role artifacts into forecasts with role, setup, horizon, source refs, and public-equity methodology fields.
- `tradingagents/schemas/research.py`: add creator workflow packet schema if plain dicts become too loose.
- `tradingagents/evals/source_quality.py`: emit compact source-quality review packets for broad provider bundles and creator workflow source refs.
- `tradingagents/orchestration/n8n_policy.py`: keep only safe observer/eval jobs allowlisted.
- `.codex/hooks/token_context_hook.py`: keep compact event packets and warning-only raw-context guidance.
- `scripts/automation_context_snapshot.py`: summarize creator workflow packet counts and open raw artifacts only on graph failure, missing role artifacts, source-quality failure, or ledger influence changes.
- `CONTEXT_ROUTER.md`: current checkpoint and inspection route.
- `TRADING_METHODS_AND_AUTOMATIONS.md`: human-facing method documentation.

---

### Task 1: Preserve Creator Workflow Artifacts During Overnight Runs

**Files:**
- Create: `tradingagents/research/original_workflow.py`
- Create: `tests/test_original_tradingagents_workflow.py`
- Modify: `cli/main.py`
- Modify: `CONTEXT_ROUTER.md`

- [x] **Step 1: Write artifact writer tests**

Create tests that use a fake final state with all original creator roles:

```python
def _creator_final_state():
    return {
        "market_report": "Market analyst says controlled dip with support.",
        "sentiment_report": "Sentiment analyst says crowd is cautious.",
        "news_report": "News analyst says positive guidance is underpriced.",
        "fundamentals_report": "Fundamentals analyst says margins are improving.",
        "investment_debate_state": {
            "bull_history": "Bull researcher argues upside.",
            "bear_history": "Bear researcher argues valuation risk.",
            "judge_decision": "Research manager favors a watchlist entry.",
        },
        "trader_investment_plan": "Trader proposes wait for pullback support.",
        "risk_debate_state": {
            "aggressive_history": "Aggressive risk analyst accepts small paper risk.",
            "neutral_history": "Neutral risk analyst wants confirmation.",
            "conservative_history": "Conservative risk analyst wants cash default.",
            "judge_decision": "**Rating**: Overweight\nPortfolio manager approves analysis-only watch.",
        },
        "final_trade_decision": "**Rating**: Overweight\nPortfolio manager approves analysis-only watch.",
    }
```

Assertions:

```python
packet = write_creator_workflow_artifacts(
    _creator_final_state(),
    symbol="NVDA",
    trade_date="2026-06-03",
    output_root=tmp_path,
    rating="Overweight",
    signal="Overweight",
)
assert packet["analysis_only"] is True
assert packet["execution_authority"] == "none"
assert "submit_order" in packet["forbidden_effects"]
assert packet["role_count"] == 12
assert (tmp_path / "NVDA" / "1_analysts" / "market.md").exists()
assert (tmp_path / "NVDA" / "2_research" / "bull.md").exists()
assert (tmp_path / "NVDA" / "3_trading" / "trader.md").exists()
assert (tmp_path / "NVDA" / "4_risk" / "aggressive.md").exists()
assert (tmp_path / "NVDA" / "5_portfolio" / "decision.md").exists()
assert Path(packet["complete_report_path"]).exists()
```

Run: `uv run --with pytest python -m pytest tests/test_original_tradingagents_workflow.py -q`
Expected: fail before implementation because `write_creator_workflow_artifacts` does not exist.

- [x] **Step 2: Implement reusable extraction and writer**

Implement in `tradingagents/research/original_workflow.py`:

```python
CREATOR_ROLE_SPECS = (
    ("market_analyst", "1_analysts", "market.md", ("market_report",)),
    ("sentiment_analyst", "1_analysts", "sentiment.md", ("sentiment_report",)),
    ("news_analyst", "1_analysts", "news.md", ("news_report",)),
    ("fundamentals_analyst", "1_analysts", "fundamentals.md", ("fundamentals_report",)),
    ("bull_researcher", "2_research", "bull.md", ("investment_debate_state", "bull_history")),
    ("bear_researcher", "2_research", "bear.md", ("investment_debate_state", "bear_history")),
    ("research_manager", "2_research", "manager.md", ("investment_debate_state", "judge_decision")),
    ("trader", "3_trading", "trader.md", ("trader_investment_plan",)),
    ("aggressive_risk_analyst", "4_risk", "aggressive.md", ("risk_debate_state", "aggressive_history")),
    ("neutral_risk_analyst", "4_risk", "neutral.md", ("risk_debate_state", "neutral_history")),
    ("conservative_risk_analyst", "4_risk", "conservative.md", ("risk_debate_state", "conservative_history")),
    ("portfolio_manager", "5_portfolio", "decision.md", ("risk_debate_state", "judge_decision")),
)
```

The writer must:

- validate the ticker with `safe_ticker_component`
- write role markdown files only when content is non-empty
- write `complete_report.md`
- write `creator_workflow_packet.json`
- return a compact dict with `analysis_only=true`, `execution_authority=none`, `role_count`, `role_artifacts`, `complete_report_path`, `packet_path`, `rating`, and `signal`

- [x] **Step 3: Wire overnight graph runs**

Modify `_run_overnight_ticker_analysis()` in `cli/main.py` so that after `graph.propagate(...)` it writes creator artifacts under:

```text
<overnight-log-dir>/agent_runs/<SYMBOL>/
```

Add compact result fields:

```python
"creator_workflow": {
    "packet_path": packet["packet_path"],
    "complete_report_path": packet["complete_report_path"],
    "role_count": packet["role_count"],
    "execution_authority": "none",
}
```

Do not put full role text into compact overnight results beyond the existing short `reports` subset.

- [x] **Step 4: Run focused tests**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_original_tradingagents_workflow.py tests/test_alpaca_cli.py::test_plan_overnight_passes_overnight_graph_config_to_guarded -q
.\.venv\Scripts\python.exe -m py_compile tradingagents\research\original_workflow.py cli\main.py
```

Result: passed with 3 tests; compile succeeded.

---

### Task 2: Convert Creator Workflow Roles Into Ledger Forecasts

**Files:**
- Modify: `tradingagents/evals/agent_intelligence_ledger.py`
- Modify: `tests/test_agent_intelligence_ledger.py`
- Modify: `tests/test_alpaca_cli.py`

- [x] **Step 1: Add creator workflow forecast extraction tests**

Test that `forecasts_from_overnight_packet(...)` reads `ticker_results[*].creator_workflow.packet_path` when present, opens the small packet, and creates forecasts for these agents:

```text
market_analyst, sentiment_analyst, news_analyst, fundamentals_analyst,
bull_researcher, bear_researcher, research_manager, trader,
aggressive_risk_analyst, neutral_risk_analyst, conservative_risk_analyst,
portfolio_manager
```

Each forecast must include:

```python
assert forecast.setup == "creator_tradingagents_workflow"
assert forecast.evidence_refs
assert forecast.source_packet_id
assert forecast.horizon == "5 trading days"
assert forecast.benchmark == "SPY"
```

- [x] **Step 2: Add extraction implementation**

Add a helper:

```python
def forecasts_from_creator_workflow_packet(packet: Mapping[str, Any], *, benchmark: str, horizon_days: int, alpha_threshold_pct: Decimal | str, regime: str) -> list[AgentForecast]:
    ...
```

It must score stance using the existing `_stance_from_text`, build claims with role-specific source names, and use `creator_tradingagents_workflow` as setup.

- [x] **Step 3: Run focused tests**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_agent_intelligence_ledger.py tests/test_alpaca_cli.py::test_research_agent_ledger_from_overnight_writes_forecasts -q
```

Expected: creator role forecasts append without duplicate IDs and older overnight packets still work.

Result:

```powershell
uv run --with pytest python -m pytest tests/test_agent_intelligence_ledger.py tests/test_alpaca_cli.py::test_research_agent_ledger_from_overnight_writes_forecasts -q
```

Passed with 8 tests. Compile also passed:

```powershell
.\.venv\Scripts\python.exe -m py_compile tradingagents\evals\agent_intelligence_ledger.py tradingagents\research\original_workflow.py cli\main.py
```

---

### Task 3: Overlay Public-Equity Methodology And Source Quality

**Files:**
- Modify: `tradingagents/schemas/research.py`
- Create/modify: `tradingagents/evals/source_quality.py`
- Modify: `tests/test_source_quality.py`
- Modify: `docs/superpowers/plans/2026-06-03-plugin-methodology-integration.md`

- [x] **Step 1: Add thesis fields to role/forecast metadata**

Add optional metadata keys to creator workflow packets and ledger forecasts:

```text
thesis_pillars, variant_wedge, priced_in_view, catalyst_path,
invalidators, action_thresholds, scenario_skew, pm_action
```

Keep these as advisory strings/lists. They must not create trade intents.

Result:

`AgentForecast` now carries `thesis_pillars`, `variant_wedge`, `priced_in_view`, `catalyst_path`, `invalidators`, `action_thresholds`, `scenario_skew`, and `pm_action`. Creator workflow forecasts populate those fields from role text while remaining advisory.

```powershell
uv run --with pytest python -m pytest tests/test_agent_intelligence_ledger.py tests/test_alpaca_cli.py::test_research_agent_ledger_from_overnight_writes_forecasts -q
```

Passed with 8 tests. Compile passed:

```powershell
.\.venv\Scripts\python.exe -m py_compile tradingagents\evals\agent_intelligence_ledger.py
```

- [x] **Step 2: Add source-quality review command**

Add CLI command:

```powershell
.\.venv\Scripts\tradingagents.exe research source-quality-review --json-output
```

It must write a packet under `results/source_quality/`, summarize compactly in `results/_context/`, and fail soft when optional provider packets are missing.

- [x] **Step 3: Run focused tests**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_source_quality.py tests/test_integration_registry.py -q
```

Result:

```powershell
uv run --with pytest python -m pytest tests/test_source_quality.py tests/test_integration_registry.py tests/test_n8n_runner_policy.py -q
```

Passed with 26 tests. Real n8n proof:

```powershell
.\.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job source_quality_review --json
```

Returned `status=ok`, `submit_capable=false`, `source_count=47`, `stale_count=26`, and wrote `results\source_quality\source-quality-review-20260603-030556.json`.

---

### Task 4: Keep n8n And Hooks Token-Efficient Around Creator Workflow

**Files:**
- Modify: `scripts/automation_context_snapshot.py`
- Modify: `tradingagents/orchestration/n8n_policy.py`
- Modify: `tradingagents/orchestration/n8n_runner.py`
- Modify: `.codex/hooks/token_context_hook.py`
- Modify: `tests/test_automation_context_snapshot.py`
- Modify: `tests/test_n8n_runner_policy.py`
- Modify: `tests/test_token_context_hooks.py`

- [x] **Step 1: Summarize creator artifacts compactly**

Compact context should include only:

```json
{
  "label": "creator_workflow",
  "symbol": "NVDA",
  "role_count": 12,
  "packet_path": "results/overnight_plans/agent_runs/NVDA/creator_workflow_packet.json",
  "complete_report_path": "results/overnight_plans/agent_runs/NVDA/complete_report.md",
  "execution_authority": "none"
}
```

Open raw creator role reports only when role count is too low, graph failed, source-quality failed, or ledger influence changed.

Result:

```powershell
uv run --with pytest python -m pytest tests/test_automation_context_snapshot.py -q
```

Passed with 14 tests. `scripts/automation_context_snapshot.py` now summarizes `creator_workflow` refs inside overnight packets and includes `source_quality_review` latest packets with quality flags.

- [x] **Step 2: Add safe n8n observer jobs**

Allowlist these non-submit jobs only:

```text
creator_workflow_status
source_quality_review
agent_ledger_summary
execution_board_review
context_snapshot
daily_report_preview
```

Reject any job that combines creator workflow status with `submit`, `order`, `cancel`, `promote`, or arbitrary command execution.

- [x] **Step 3: Run focused tests**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py tests/test_token_context_hooks.py -q
```

Expected: compact context stays small and all n8n/hook jobs remain `submit_capable=false`.

Result:

```powershell
uv run --with pytest python -m pytest tests/test_original_tradingagents_workflow.py tests/test_n8n_runner_policy.py -q
```

Passed with 20 tests. Real n8n proofs:

```powershell
.\.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job creator_workflow_status --json
.\.venv\Scripts\python.exe -m tradingagents.orchestration.n8n_runner --run-job agent_ledger_summary --json
```

Both returned `status=ok` and `submit_capable=false`. `creator_workflow_status` found `workflow_count=0` in the current historical `latest.json` because that overnight packet predates the new artifact refs; future full-graph runs will populate the refs.

Additional `PreToolUse` hook proof:

```powershell
uv run --with pytest python -m pytest tests/test_token_context_hooks.py tests/test_automation_context_snapshot.py tests/test_n8n_runner_policy.py -q
.\.venv\Scripts\python.exe -m py_compile tradingagents\orchestration\token_context.py .codex\hooks\token_context_hook.py scripts\automation_context_snapshot.py tradingagents\orchestration\n8n_runner.py tradingagents\orchestration\n8n_policy.py
'{"hook_event_name":"PreToolUse","tool_name":"exec_command","tool_input":{"cmd":"Get-Content results\\hourly_supervisor\\old-big-packet.json"},"api_key":"fake-secret"}' | .\.venv\Scripts\python.exe .codex\hooks\token_context_hook.py
```

Passed with 42 tests. The manual run returned `0`, printed `pre_tool_warning=warning_only`, wrote `results\_context\hook-events\hook-event-20260603-034001-934940.json`, and redacted the fake secret.

---

### Task 5: Preserve Buy-Dip/Sell-Spike And Independent Sell/Buy Behavior

**Files:**
- Modify: `tradingagents/brokers/alpaca_supervisor.py`
- Modify: `tradingagents/brokers/paper_tournament.py`
- Modify: `tests/test_alpaca_supervisor.py`
- Modify: `tests/test_execution_board.py`

- [x] **Step 1: Add regression checks**

Keep these tests passing:

```powershell
uv run --with pytest python -m pytest tests/test_alpaca_supervisor.py::test_build_candidate_signals_prefers_controlled_dip_over_green_spike tests/test_alpaca_supervisor.py::test_aggressive_decision_refuses_green_spike_chase_buy tests/test_alpaca_supervisor.py::test_hourly_decision_sells_profit_spike_instead_of_only_reviewing tests/test_alpaca_supervisor.py::test_loss_close_holds_cash_instead_of_rotating_into_green_spike tests/test_execution_board.py -q
```

Expected: sells can run independently, buys require clean dip/support evidence, and loss exits do not force immediate replacement buys.

- [x] **Step 2: Tie creator workflow influence to advisory weight only**

Creator workflow output may raise research priority or ledger influence after outcomes resolve. It must not bypass anti-chase, sell-profit, independent buy/sell, BOARD pause, or Alpaca gates.

Result:

```powershell
uv run --with pytest python -m pytest tests/test_alpaca_supervisor.py::test_build_candidate_signals_prefers_controlled_dip_over_green_spike tests/test_alpaca_supervisor.py::test_aggressive_decision_refuses_green_spike_chase_buy tests/test_alpaca_supervisor.py::test_hourly_decision_sells_profit_spike_instead_of_only_reviewing tests/test_alpaca_supervisor.py::test_loss_close_holds_cash_instead_of_rotating_into_green_spike tests/test_execution_board.py -q
```

Passed with 9 tests. Creator workflow forecasts stay in `AgentForecast`/influence-weight surfaces with `execution_authority=none` and cannot bypass Alpaca gates.

---

### Task 6: Mirror Fish, AlphaInsider, Popular Strategies, And Paper Tournament

**Files:**
- Modify: `reports/mirofish/MIROFISH_PENDING_LEARNING_SCAFFOLD.md`
- Modify: `tradingagents/research/mirofish_handoff.py`
- Modify: `tradingagents/brokers/paper_tournament.py`
- Modify: `TRADING_METHODS_AND_AUTOMATIONS.md`
- Modify: `tests/test_mirofish_handoff.py`
- Modify: `tests/test_paper_tournament.py`

- [x] **Step 1: Keep Mirror Fish clean-room handoff ingestion ready**

When the final external handoff lands, ingest instructions and artifacts as advisory market-reaction methodology only. Do not import AGPL code, schemas, prompts, or tests.

- [x] **Step 2: Keep AlphaInsider paper-only**

Run/verify:

```powershell
uv run --with pytest python -m pytest tests/test_paper_tournament.py::test_alphainsider_paper_watch_uses_only_remaining_paper_budget tests/test_paper_tournament.py::test_alphainsider_paper_watch_builds_shadow_orders_from_strategy_tickers tests/test_paper_tournament.py::test_paper_tournament_alphainsider_watch_writes_paper_only_packet -q
```

Expected: paper-only packets, no live broker calls, no live authority, weekly strategy rotation documented with RRULE format when scheduled.

Result:

```powershell
uv run --with pytest python -m pytest tests/test_mirofish_handoff.py tests/test_paper_tournament.py::test_alphainsider_paper_watch_uses_only_remaining_paper_budget tests/test_paper_tournament.py::test_alphainsider_paper_watch_builds_shadow_orders_from_strategy_tickers tests/test_paper_tournament.py::test_paper_tournament_alphainsider_watch_writes_paper_only_packet -q
```

Passed with 5 tests. MiroFish remains clean-room/advisory and AlphaInsider remains paper-only with no live broker authority.

---

### Task 7: Final Eval Gate And Durable Docs

**Files:**
- Modify: `CONTEXT_ROUTER.md`
- Modify: `TRADING_METHODS_AND_AUTOMATIONS.md`
- Modify: `docs/superpowers/plans/2026-06-03-plugin-methodology-integration.md`
- Create/update: `reports/orchestration/ENDGAME_EVAL_SUMMARY.md`

- [x] **Step 1: Run compact context and process review**

Run:

```powershell
python scripts/automation_context_snapshot.py --write
.\.venv\Scripts\tradingagents.exe research process-review --json-output
```

Result: `results\process_reviews\process-review-20260603-024807.json` listed unfinished plan items, `can_submit_orders=false`, and compact context was refreshed afterward.

- [x] **Step 2: Run focused regression gate**

Run:

```powershell
uv run --with pytest python -m pytest tests/test_original_tradingagents_workflow.py tests/test_agent_intelligence_ledger.py tests/test_source_quality.py tests/test_n8n_runner_policy.py tests/test_token_context_hooks.py tests/test_automation_context_snapshot.py tests/test_alpaca_supervisor.py::test_aggressive_decision_refuses_green_spike_chase_buy tests/test_alpaca_supervisor.py::test_hourly_decision_sells_profit_spike_instead_of_only_reviewing tests/test_execution_board.py -q
```

Expected: all pass.

Result:

```powershell
uv run --with pytest python -m pytest tests/test_original_tradingagents_workflow.py tests/test_agent_intelligence_ledger.py tests/test_source_quality.py tests/test_n8n_runner_policy.py tests/test_token_context_hooks.py tests/test_automation_context_snapshot.py tests/test_paper_tournament.py tests/test_alpaca_supervisor.py::test_aggressive_decision_refuses_green_spike_chase_buy tests/test_alpaca_supervisor.py::test_hourly_decision_sells_profit_spike_instead_of_only_reviewing tests/test_execution_board.py -q
```

Passed with 78 tests.

- [x] **Step 3: Run Plugin Eval only where it fits**

Use bundled Plugin Eval for plan/skill artifacts, not for live trading correctness:

```powershell
node C:\cm\plugins\cache\openai-curated\plugin-eval\5e86d584\scripts\plugin-eval.js analyze docs\superpowers\plans --format markdown > reports\orchestration\ENDGAME_PLANS_PLUGIN_EVAL.md
```

Expected: report is advisory. Any live/order safety concern must be verified with repo-native tests, not Plugin Eval alone.

Result: wrote `reports\orchestration\ENDGAME_PLANS_PLUGIN_EVAL.md`; advisory score `86/100`, grade `B`, high-risk only from excessive deferred token cost for the entire plan directory. Mitigation is compact routing through `CONTEXT_ROUTER.md`, the active endgame plan, and process-review packets.

- [x] **Step 4: Update docs**

Update `CONTEXT_ROUTER.md` with:

- latest endgame plan path
- creator workflow artifact packet path
- latest focused test commands
- current process-review packet

Update `TRADING_METHODS_AND_AUTOMATIONS.md` with:

- creator workflow lane
- ledger influence lane
- source-quality lane
- n8n/hook observer lane
- paper/live authority boundary

Result: updated `CONTEXT_ROUTER.md`, `TRADING_METHODS_AND_AUTOMATIONS.md`, `docs/superpowers/plans/2026-06-03-plugin-methodology-integration.md`, `docs/orchestration/n8n-workflow-map.md`, `docs/orchestration/goal-agent-context-contract.md`, `reports/orchestration/TOKEN_HOOK_FINAL_EVAL.md`, and `reports/orchestration/ENDGAME_EVAL_SUMMARY.md`.

## Completion Criteria

- Overnight graph runs persist creator workflow role artifacts and compact packet references.
- Agent Intelligence Ledger can score creator workflow role claims by role, setup, ticker, evidence type, and horizon.
- Source-quality review can flag stale/weak provider evidence without crashing or spending tokens on raw packets by default.
- n8n and hooks stay observer/context surfaces with `submit_capable=false`.
- Buy-dip/sell-spike, independent sell/buy, BOARD review, and uncapped-live-budget gates remain covered by tests.
- AlphaInsider and popular strategies stay paper-first until promoted by deterministic evidence.
- Mirror Fish handoff ingestion is clean-room and advisory only.
- Focused tests, compile checks, process review, and applicable Plugin Eval/custom evals have run.
- Remaining blockers are explicit in packet/docs; do not mark the active goal complete until all completion criteria are met.
