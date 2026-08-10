# TradingAgents Methods and Automations

> **Current workspace:** `/Users/corbinfloyd/Documents/TradingAgents`. Mac jobs
> are defined in `scripts/mac/ta_job.sh` and installed through
> `scripts/mac/install_launchd.sh`. The dated Windows automation material below
> is retained as history; current automation state comes from the active Mac
> launchd jobs and the current Codex automation definitions.

Generated for the local TradingAgents checkout at:

`C:\Users\Corbin\Documents\Coding projects\TradingAgents-main`

This document explains the active trading methods, the scheduled automations under `C:\cm\automations`, what each one does, which model/reasoning level orchestrates it, what inner TradingAgents model is used when applicable, and how long each normally runs based on current local evidence.

## Important Safety Context

These automations are trading infrastructure, not financial advice. The system uses several safeguards:

- `alpaca check` is required before order-affecting work.
- Supervisor automations run dry-run first and submit only when actions are valid and checks are clean.
- Orders are stocks-only, limit-only, and constrained by the live gate, broker buying power, and risk-envelope safety checks.
- No crypto, options, shorts, margin expansion, or market orders.
- The repo is wired for the June 4, 2026 intraday-margin rule: old PDT day-count, old `$25,000` PDT minimum, PDT designation, and old day-trading-buying-power logic are not bot blockers anymore. Broker buying power, account status, intraday-margin context, and fresh validation still matter.
- Overnight plans and premarket briefs are analysis-only.
- Paper tournament work is paper-only and must never place live orders.
- Routine quiet checks usually write local packets and do not send email.

## Current Trading Methods

### Methodology Inputs From Plugins And Skills

The repo borrows methodology from enabled plugins, but plugins do not become trading authority. Superpowers and Plugin Eval guide build/eval discipline; Public Equity Investing contributes thesis, catalyst, invalidator, scenario, and PM-action structure; Data Analytics contributes source-quality checks; AlphaInsider contributes paper-only strategy-allocation ideas; Binance is optional read-only market context; Investment Banking contributes evidence-control and model tie-out habits.

The current integration plan is `docs/superpowers/plans/2026-06-03-plugin-methodology-integration.md`. Any plugin-derived runtime output must become a packet with `execution_authority=none` unless it passes through the existing Python Alpaca policy path.

### Real Simulation Audit

**Purpose:** This is the repo-wide department check before calling the market workflow ready. It runs live-data dry-run commands for preflight, integrations, model routing, research, policy, Alpaca, paper strategy, and BOARD review.

**Latest proof:** `results\real_simulation_audits\real-simulation-audit-20260603-192427.json` ran 25 department commands, failed 0, submitted 0 orders, selected the Mac `deepseek-r1:14b` helper lane, and explicitly marked all 115 stale source packets safe by refresh/downrank/low-quality handling. The paired automation-health packet `results\automation_health\automation-health-audit-20260603-191840.json` reported `timeliness_issue_count=0`, `late_count=0`, `missing_count=0`, and `partial_count=0`.

**Important behavior:** It never relies on "market closed" as a safety control. Live submission stays disabled during the audit, paper execution is dry-run where supported, and any failed department or stale evidence gap must be patched or documented before the system is treated as ready.

**Where implemented:**

- `tradingagents/evals/real_simulation_audit.py`
- `cli/main.py`
- `tests/test_real_simulation_audit.py`

### Original TradingAgents Creator Workflow Lane

**Purpose:** The original creator workflow now remains a first-class research lane instead of being compressed into a single ticker score. Overnight graph runs call `TradingAgentsGraph.propagate(...)` and preserve the Analyst Team, Bull/Bear Research Team, Trader, Risk Management Team, and Portfolio Manager outputs as role artifacts.

**What it writes:** Full role markdown and a compact JSON packet under the overnight run's `agent_runs/<SYMBOL>/` folder:

- `1_analysts/market.md`, `sentiment.md`, `news.md`, `fundamentals.md`
- `2_research/bull.md`, `bear.md`, `manager.md`
- `3_trading/trader.md`
- `4_risk/aggressive.md`, `neutral.md`, `conservative.md`
- `5_portfolio/decision.md`
- `complete_report.md`
- `creator_workflow_packet.json`

**Important behavior:** This lane is analysis-only with `execution_authority=none`. It creates evidence and role claims, and the Agent Intelligence Ledger can now turn those role artifacts into scoreable forecasts with `setup=creator_tradingagents_workflow`. It cannot submit orders, size positions, promote sleeves, waive live gates, or cancel orders.

**Where implemented:**

- `tradingagents/research/original_workflow.py`
- `tradingagents/evals/agent_intelligence_ledger.py`
- `cli/main.py`
- `tests/test_original_tradingagents_workflow.py`

### 1. Current Aggressive TradingAgents

**Purpose:** This is the current live/paper supervisor style. It still watches strong liquid names, but the live-facing logic now prefers controlled dips and profit-taking spikes instead of chasing a stock after it already jumped.

**What it looks for:**

- Controlled intraday dips that are not falling knives.
- High relative volume.
- Mega-cap/liquid names that can be traded safely.
- Existing position profit/loss thresholds.
- Opportunities to buy dips, sell/close spikes, reduce risk, rotate, paper-test, hold, or hold cash.

**Important behavior:** The old momentum chase was narrowed. A green spike is downranked with a “do not chase” reason, a controlled dip is ranked higher when the support/volume context is clean, and a profitable live holding can trigger a `profit-take` sell action with “Sell the spike” wording.

**Where implemented:**

- `tradingagents/brokers/alpaca_supervisor.py`
- `tradingagents/brokers/paper_tournament.py`

### Market-Structure Transition Overlay

**Purpose:** The June 4, 2026 shift from old PDT rules to intraday-margin/risk monitoring changes crowd behavior. More retail traders and AI-bot operators may be able to trade intraday, so the research side treats sudden spikes, squeezes, panic dips, and social hype as more unstable.

**Important behavior:** This overlay does not submit orders. It tells overnight research, premarket context, and market-mirror simulations to ignore old PDT blockers while watching for crowd/AI-bot overreaction. The trading side still requires broker buying power, fresh price/support checks, live gate approval, and limit-only orders.

**MiroFish final advisory handoff:** `reports/mirofish/MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md` stores the accepted final `report_9c77ca2557ae` advisory handoff. It is valid as a research prior for the June 4-13 window only and must be refreshed around premarket, open, macro/rates windows, and broker/API status changes.

**MiroFish handoff status:** `research mirofish-handoff-status` writes `results/mirofish_handoff/latest.json`, and n8n can run the allowlisted `mirofish_handoff_status` job. This is advisory only; expected current status is `final_handoff_available` for required report id `report_9c77ca2557ae`, with execution authority `none`.

**Full-report highlight:** the MiroFish full report is summarized into compact context as an AI-bot copycat / institutional-liquidity filter: identical prompt-bot signals can create false-positive crowding, while market makers, quant funds, and ETF desks may fade or absorb novice clustering. TradingAgents must validate independent volume, broker/API execution, options liquidity, institutional participation, and macro attribution before treating social momentum as usable evidence.

**Where implemented:**

- `tradingagents/research/market_structure.py`
- `tradingagents/research/overnight_context.py`
- `tradingagents/research/market_mirror.py`
- `tradingagents/research/mirofish_handoff.py`
- `tradingagents/brokers/alpaca_supervisor.py`

### 2. Pullback Support Buyer

**Purpose:** This is the “buy the dip” style already present in the paper tournament. It tries to buy strong liquid stocks on disciplined, non-thesis-breaking pullbacks.

**What it looks for:**

- A stock not already held by that strategy sleeve.
- A controlled pullback, currently around `-0.3%` to `-2.5%` on the day.
- Volume ratio no higher than `2.5`, so it avoids panic-style moves.

**Important behavior:** This is much closer to “buying the dips.” Right now it is tested inside the paper strategy tournament and is not yet promoted to live behavior because the tournament needs more tracked days and a positive winner.

**Where implemented:**

- `tradingagents/brokers/paper_tournament.py`

### 3. Catalyst / Relative Strength Rotation

**Purpose:** This paper tournament sleeve focuses on fresh strength, volume, and catalyst-style momentum.

**What it looks for:**

- Time-sensitive candidate signals.
- Scores at or above the catalyst threshold.
- Fresh volume/price confirmation.

**Important behavior:** This is also momentum-oriented, but narrower than the current aggressive method.

**Where implemented:**

- `tradingagents/brokers/paper_tournament.py`

## Popular Strategy Coverage From Deep Research

The Deep Research reports did not recommend blindly turning every popular trading idea into live orders. The repo now separates them into three buckets:

- **Active order paths:** deterministic code can create supervisor or paper-tournament actions, still gated by `alpaca check`, dry-run, policy checks, and live gates.
- **Research-only or overlay:** the strategy is implemented as a structured methodology card for overnight research, replay planning, and future paper sleeves, but it cannot submit orders by itself.
- **Intentionally deferred:** the idea is documented as out of scope or unsafe for the current stocks-only, long-only, limit-only setup.

| Strategy idea | Repo status | Where it lives | What that means |
| --- | --- | --- | --- |
| Momentum / breakout continuation | Active as a narrowed research/paper behavior; the live-facing current supervisor now downranks green spikes | `tradingagents/brokers/alpaca_supervisor.py`, `tradingagents/brokers/paper_tournament.py`, `tradingagents/research/methodology_cards.py` | Can influence current supervisor/paper actions, but live buys should not chase after a sharp green move and still cannot bypass live gates. |
| Pullback / support buying | Active paper-first deterministic sleeve | `tradingagents/sleeves/pullback_support.py`, `tradingagents/brokers/paper_tournament.py`, `tradingagents/research/methodology_cards.py` | This is the main "buy the dip, not falling knife" engine; live remains gated. |
| Catalyst / relative strength | Active paper tournament sleeve and research methodology | `tradingagents/brokers/paper_tournament.py`, `tradingagents/research/methodology_cards.py` | Paper-only tournament strategy unless future promotion gates pass. |
| Earnings drift / post-earnings underreaction | Research-only methodology card | `tradingagents/research/methodology_cards.py` | Overnight research can reason about it, but it needs a dedicated paper policy before trading. |
| Event-driven catalyst continuation | Research-only methodology card | `tradingagents/research/methodology_cards.py` | Used as structured research context around 8-Ks, macro events, corporate actions, and news. |
| News / sentiment swing | Research-only methodology card | `tradingagents/research/methodology_cards.py` | News and social context can confirm or warn, but social chatter is never trade truth. |
| Pairs / co-movement residual | Research-only methodology card | `tradingagents/research/methodology_cards.py` | Tracked for future long-only or hedged variants; short-biased execution is deferred. |
| Mean-reversion swing | Research-only methodology card | `tradingagents/research/methodology_cards.py` | Treated as controlled overreaction research until a separate paper sleeve exists. |
| Macro regime rotation | Overlay-only methodology card | `tradingagents/research/methodology_cards.py` | Can downrank, veto, or size down inside policy; it is not a standalone ticker trigger. |
| Factor quality/value/low-beta context | Overlay-only methodology card | `tradingagents/research/methodology_cards.py` | Used for portfolio context and future ablation, not direct order creation. |
| Microstructure-aware limit execution | Execution overlay-only methodology card | `tradingagents/research/methodology_cards.py` | Helps avoid bad limit orders; not treated as standalone alpha. |
| Options overlays, volatility arbitrage, true ETF arbitrage, standalone calendar seasonality, short-biased pairs | Intentionally deferred | Documented in methodology packet coverage status | Deferred because the repo is currently stocks-only, long-only, limit-only, and not built for AP ETF mechanics, options assignment risk, or standalone short/volatility strategies. |

The paper tournament report now also includes `popular_strategy_scorecards` from
`build_popular_strategy_scorecards(...)`. These are paper-only scorecards for
pullback support, earnings drift / estimate revision, event underreaction,
pairs/co-movement residuals, news/sentiment swing, macro regime overlay, and
AlphaInsider-style allocation shadow. Each scorecard records setup type, thesis,
pass/fail criteria, paper metrics when available, `execution_authority=none`,
and forbidden effects including live submission and live-gate waivers. Live can
only mirror a paper sleeve after that sleeve becomes the deterministic tournament
candidate and the Alpaca live gate passes.

The command that writes the methodology packet is:

```powershell
.\.venv\Scripts\tradingagents.exe research methodology-cards --json-output
```

That packet is analysis-only. It explicitly records `execution_authority = none` and forbidden effects like `submit_order`, `size_position`, `promote_sleeve`, and `waive_live_gate`.

## Automation Summary Table

| Automation | Schedule | Outer model | Reasoning | Normal runtime | Main output |
| --- | --- | --- | --- | --- | --- |
| `hourly-market-supervisor` | Every hour at minute `00` | `gpt-5.5` | `xhigh` | Usually about 2-4 minutes lately; older runs sometimes 5-12 minutes | `results/hourly_supervisor/`, refreshed `results/premarket_briefs/` |
| `paper-strategy-tournament-runner` | Every hour at minute `05` | `gpt-5.5` | `high` | Usually a few seconds once initialized | `results/paper_strategy_tournament/` |
| `tradingagents-overnight-planning` | Daily at 3:00 AM local time | `gpt-5.5` | `xhigh` | Latest clean run took about 35 minutes; budget is 90 minutes | `results/overnight_plans/`, refreshed `results/premarket_briefs/` |
| `market-supervisor-15-min-before-open` | Weekdays at 8:15 AM local time | `gpt-5.5` | `xhigh` | Expected similar to hourly supervisor, about 2-5 minutes unless submit work occurs | `results/hourly_supervisor/`, refreshed `results/premarket_briefs/` |
| `market-supervisor-30-min-after-open` | Weekdays at 9:00 AM local time | `gpt-5.5` | `xhigh` | Expected similar to hourly supervisor, about 2-5 minutes unless submit work occurs | `results/hourly_supervisor/`, refreshed `results/premarket_briefs/` |
| `market-supervisor-30-min-before-close` | Weekdays at 2:30 PM local time | `gpt-5.5` | `xhigh` | Expected similar to hourly supervisor, about 2-5 minutes unless submit work occurs | `results/hourly_supervisor/`, refreshed `results/premarket_briefs/` |
| `market-supervisor-15-min-after-close` | Weekdays at 3:15 PM local time | `gpt-5.5` | `xhigh` | Expected similar to hourly supervisor, about 2-5 minutes unless submit work occurs | `results/hourly_supervisor/`, refreshed `results/premarket_briefs/` |
| `tradingagents-daily-market-report` | Weekdays at 3:30 PM local time | `gpt-5.5` | `high` | Expected about 1-3 minutes | Gmail report plus in-thread summary |

## Automation Details

### Hourly Market Supervisor

**Automation ID:** `hourly-market-supervisor`

**Purpose:** Runs one Aggressive Live Trading Supervisor V2 tick every hour. This is the main recurring live/paper strategy monitor.

**Sequence:**

1. Runs `tradingagents alpaca check`.
2. Runs `tradingagents alpaca supervise-hourly --dry-run`.
3. If dry-run returns valid actions with no issues and account checks are clean, runs `tradingagents alpaca supervise-hourly --submit-actions`.
4. Refreshes the rolling premarket brief.
5. Sends urgent email only if `notify: true`; otherwise it keeps local packets only.

**What it reviews:**

- Live and paper account status.
- Buying power, equity, exposure, and current live sizing mode.
- Live and paper positions.
- Open live orders.
- Fresh candidate rankings.
- Overnight plan validation.
- Premarket brief validation.
- Paper tournament live-strategy selection, when available.

**Model/intelligence:**

- Outer automation model: `gpt-5.5`
- Outer reasoning effort: `xhigh`
- Inner TradingAgents model: not usually a full LLM graph. The supervisor mostly uses deterministic Alpaca/account checks, market data, candidate scoring, and prior overnight/premarket/tournament packets.

**Normal runtime:** Recent memory entries show about 2-4 minutes per quiet tick. Older runs recorded about 5-12 minutes.

**Normal quiet outcome:** A valid quiet packet can have `decision=profit-review`, `actions=[]`, `issues=[]`, `submitted=[]`, and `notify=false`. That is not a failure.

### Paper Strategy Tournament Runner

**Automation ID:** `paper-strategy-tournament-runner`

**Purpose:** Runs the paper-only strategy tournament every hour. It compares the strategy sleeves before allowing any live-strategy promotion.

**Sequence:**

1. Initializes the tournament ledger if missing.
2. Runs `tradingagents alpaca paper-tournament run --all`.
3. Verifies the returned packet has `submitted_count`, `report.rankings`, `ledger_path`, and `packet_path`.
4. Posts only if paper orders submit, a blocker appears, or the live strategy candidate changes.

**Strategies tested:**

- `current-aggressive`
- `pullback-support`
- `catalyst-relative-strength`

**Model/intelligence:**

- Outer automation model: `gpt-5.5`
- Outer reasoning effort: `high`
- Inner TradingAgents model: no full LLM graph in routine ticks. The tournament uses deterministic strategy rules and Alpaca paper/account data.

**Normal runtime:** Recent paper tournament packets are written within a few seconds.

**Normal quiet outcome:** Most recent runs submitted `0` paper orders, had `0` issues, and still validly updated the ledger and latest report.

### TradingAgents Overnight Planning

**Automation ID:** `tradingagents-overnight-planning`

**Purpose:** Runs the bounded overnight planning pass after extended-hours trading is closed. It creates an analysis-only next-day candidate plan and refreshes the premarket brief.

**Sequence:**

1. Runs `tradingagents alpaca check`.
2. Runs `tradingagents alpaca plan-overnight` with compact graph settings.
3. Confirms the packet is analysis-only, has ranked candidates, has graph quality metadata, and submitted no orders.
4. Refreshes the premarket brief.
5. Posts a concise thread note. Emails only if the overnight packet or premarket brief cannot be produced, or if account/data/model checks are blocked.

**What it reviews:**

- Current live/paper holdings.
- Open-order symbols.
- Aggressive mega-cap/liquid universe.
- Recent supervisor packet symbols.
- Market verification symbols.
- Optional watchlist symbols.
- Full TradingAgents graph for top candidates when runtime allows.
- Market snapshot fallback scoring for the remaining candidates.

**Outer model/intelligence:**

- Outer automation model: `gpt-5.5`
- Outer reasoning effort: `xhigh`

**Inner TradingAgents model/intelligence:**

- Provider: `ollama`
- Quick model: `tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k`
- Deep model: `tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k`
- Backend: `http://localhost:11434/v1`
- Graph profile: `compact`
- Analysts: market, social/sentiment, news, fundamentals
- Tool-free/prefetched analyst mode for stability
- Max completion tokens: `220`
- Debate rounds: `0`
- Risk discussion rounds: `0`
- Full graph ticker limit: `3`
- Per-ticker timeout: `25` minutes
- Total budget: `90` minutes

**Normal runtime:** Latest clean run started at about 10:47 PM local time and completed at about 11:22 PM local time, so roughly 35 minutes. The budget is 90 minutes. Earlier tuning runs had timeouts or missing packet issues, but the latest verified run had `graph_failure_count=0`.

**Important behavior:** This is analysis-only. It is not permission to buy. It currently ranks many names by momentum/fallback scoring, so top picks can look expensive or hot.

### Market Supervisor 15 Minutes Before Open

**Automation ID:** `market-supervisor-15-min-before-open`

**Purpose:** Runs just before the regular U.S. market open to validate overnight planning and the rolling premarket brief against fresh market state before any action.

**Sequence:**

1. Runs `alpaca check`.
2. Refreshes the premarket brief.
3. Runs supervisor dry-run.
4. Reviews overnight plan status, premarket brief status, and live strategy selection.
5. Submits only if actions are valid, issues are clear, and account checks are clean.
6. Refreshes premarket brief again after final decision.

**What it focuses on:**

- Premarket quotes and spreads.
- Futures/risk tone.
- Fresh news/social deltas.
- Open orders.
- Overnight plan validation.
- Weekend/premarket brief validation.
- Whether paper tournament promoted a live profile.

**Model/intelligence:**

- Outer automation model: `gpt-5.5`
- Outer reasoning effort: `xhigh`
- Inner TradingAgents model: deterministic supervisor using fresh account/market data plus overnight/premarket/tournament packets; no routine full LLM graph.

**Normal runtime:** Expected around 2-5 minutes based on the same supervisor path, unless it has to submit actions or handle blockers.

### Market Supervisor 30 Minutes After Open

**Automation ID:** `market-supervisor-30-min-after-open`

**Purpose:** Checks the first movement window after the open.

**What it focuses on:**

- Gap behavior.
- Early support/resistance.
- Abnormal volume.
- Order/fill status.
- P/L.
- Whether the paper tournament live profile changes candidate handling.

**Model/intelligence:**

- Outer automation model: `gpt-5.5`
- Outer reasoning effort: `xhigh`
- Inner TradingAgents model: deterministic supervisor path, not routine full graph.

**Normal runtime:** Expected around 2-5 minutes unless action submission or errors require more work.

### Market Supervisor 30 Minutes Before Close

**Automation ID:** `market-supervisor-30-min-before-close`

**Purpose:** Prepares for the close and overnight holding decision.

**What it focuses on:**

- Whether to hold overnight.
- Whether to reduce or close risk.
- Whether to cancel stale orders.
- Whether to rotate into stronger evidence.
- Whether to paper-test a candidate.
- Whether to keep freed money in cash.

**Model/intelligence:**

- Outer automation model: `gpt-5.5`
- Outer reasoning effort: `xhigh`
- Inner TradingAgents model: deterministic supervisor path, not routine full graph.

**Normal runtime:** Expected around 2-5 minutes unless action submission or blockers require more work.

### Market Supervisor 15 Minutes After Close

**Automation ID:** `market-supervisor-15-min-after-close`

**Purpose:** Reviews after-close state once regular trading has ended.

**What it focuses on:**

- After-close fills.
- Rejected or stale orders.
- Closing P/L.
- After-hours news.
- Whether after-hours limit action is useful.
- What the daily report should summarize.

**Model/intelligence:**

- Outer automation model: `gpt-5.5`
- Outer reasoning effort: `xhigh`
- Inner TradingAgents model: deterministic supervisor path, not routine full graph.

**Normal runtime:** Expected around 2-5 minutes unless action submission or blockers require more work.

### Email Daily Market Report

**Automation ID:** `tradingagents-daily-market-report`

**Purpose:** Sends one daily TradingAgents market supervisor email after the final after-close packet has had time to finish.

**Sequence:**

1. Runs `tradingagents alpaca supervisor-daily-report`.
2. Uses returned `subject` and `body`.
3. Emails `nebulazer2003@gmail.com`.
4. Posts the same concise report in-thread.

**What it summarizes:**

- All supervisor checks for the day.
- Latest overnight plan validation status.
- Latest premarket brief path/status/top symbol.
- Live actions and submitted order IDs.
- Paper-only experiments.
- Paper strategy tournament leader and live-strategy candidate.
- Current balances, equity, buying power, and live sizing mode.
- Current positions and per-position unrealized P/L.
- Total live gain/loss.
- Open orders.
- Material decisions.
- Ranked-candidate rationale.
- Packet counts.

**Model/intelligence:**

- Outer automation model: `gpt-5.5`
- Outer reasoning effort: `high`
- Inner TradingAgents model: deterministic report renderer in `render_daily_supervisor_report`; no routine full LLM graph.

**Normal runtime:** Expected around 1-3 minutes.

**Important behavior:** This report automation must never place trades.

## Result Folders

| Folder | Meaning |
| --- | --- |
| `results/hourly_supervisor/` | Hourly and market-window supervisor packets. |
| `results/paper_strategy_tournament/` | Paper tournament ledger, run packets, latest report, and live-strategy selection candidate. |
| `results/overnight_plans/` | Overnight analysis-only plans, ranked candidates, fallback/full-graph ticker reports, and latest packet. |
| `results/premarket_briefs/` | Rolling premarket context briefs from hourly, overnight, and tournament packets. |
| `results/overnight_system_verification/` | Verification that overnight, premarket, hourly, tournament, and report workflows are connected. |
| `results/market_verification/` | Run-specific market verification packets. |
| `results/local_model_eval/` | Local model evaluation artifacts. |

## Current Runtime Evidence

- Latest clean overnight plan: about 35 minutes, `full_graph_count=3`, `fallback_count=32`, `graph_failure_count=0`, no submitted orders.
- Recent hourly supervisor ticks: about 2-4 minutes; repeated valid quiet outcome was `decision=profit-review`, `actions=[]`, `issues=[]`, `submitted=[]`, `notify=false`.
- Recent paper tournament ticks: a few seconds; latest runs showed `submitted_count=0`, `actions=0`, and `issues=0`.
- Latest overnight system verification: `pass`, with 10 checks passing.

## Practical Interpretation

The overnight plan currently answers: “What is looking strongest or most actionable for validation tomorrow?”

It does not primarily answer: “What is a great company that is temporarily cheap and ready to rebound?”

That second question is closer to the `pullback-support` method. If the goal is to buy dips instead of chase strength, the next strategy improvement should make pullback candidates a first-class section of the overnight report and supervisor inputs.
