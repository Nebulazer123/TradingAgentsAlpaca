# TradingAgents Repo Overview

> **Current workspace:** `/Users/corbinfloyd/Documents/TradingAgents`. For the
> consolidated Mac repository map and current commands, begin with
> `START_HERE.md` and `docs/consolidation/REPOSITORY_MAP.md`. Windows examples
> below are retained for historical and cross-platform context.

This repository is a Python package and CLI for running multi-agent financial analysis, then optionally using that analysis to drive tightly controlled Alpaca paper/live-mirror workflows. It started as the TradingAgents multi-agent LLM framework and this checkout adds a practical trading-automation layer around Alpaca supervision, overnight planning, premarket briefs, paper strategy tournaments, and daily reports.

The project is research and automation infrastructure, not financial advice. The Alpaca paths include explicit dry-run, paper-only, analysis-only, cap, and validation gates because the code can interact with brokerage APIs when enabled.

## Quick Mental Model

At the center is a LangGraph workflow that sends a ticker through a team of agents:

1. Analyst agents collect and summarize market, sentiment, news, and fundamentals context.
2. Bull and bear researchers debate the evidence.
3. A research manager resolves the debate.
4. A trader proposes an action.
5. Aggressive, neutral, and conservative risk agents debate risk.
6. A portfolio manager emits the final decision.

The CLI wraps that engine in two main modes:

- Interactive or single-ticker research through `tradingagents analyze`.
- Alpaca operations through `tradingagents alpaca ...`, including account checks, previews, submissions, hourly supervision, overnight plans, premarket briefs, paper tournaments, and reports.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `cli/` | Typer/Rich command-line app. `cli/main.py` is the main entry point and defines the `tradingagents` command. |
| `tradingagents/graph/` | LangGraph orchestration, graph setup, propagation, checkpointing, reflection, and signal processing. |
| `tradingagents/agents/` | Agent implementations: analysts, researchers, trader, risk debaters, managers, shared schemas, and utilities. |
| `tradingagents/dataflows/` | Market/news/fundamental data adapters for yfinance, Alpha Vantage, Reddit, StockTwits, and stockstats-style indicators. |
| `tradingagents/llm_clients/` | Provider abstraction for OpenAI-compatible, Google, Anthropic, Azure, DeepSeek, Qwen, GLM, MiniMax, OpenRouter, and Ollama models. |
| `tradingagents/brokers/` | Alpaca integration and supervisor logic. This is the local automation-heavy layer. |
| `tests/` | Pytest coverage for config, dataflows, LLM provider handling, signal processing, Alpaca execution/supervision, and the paper tournament. |
| `scripts/` | Small support scripts, including local Ollama evaluation/model setup helpers. |
| `results/` | Runtime packets and generated reports. This is where automation evidence lands. |
| `.env.example` | Documented environment variable surface for LLMs, Ollama, config overrides, and Alpaca. |
| `pyproject.toml` | Package metadata, dependencies, CLI script registration, and pytest config. |

## Main Package Entry Points

The package name is `tradingagents`. The installed console script is:

```powershell
tradingagents
```

The source entry point is:

```powershell
python -m cli.main
```

On this Windows checkout, prefer the repo virtualenv executable when running automation so PATH issues do not matter:

```powershell
& ".\.venv\Scripts\tradingagents.exe" alpaca check
```

## Core Graph Flow

The core orchestrator is `tradingagents/graph/trading_graph.py`.

`TradingAgentsGraph` does the setup work:

- Applies config into the dataflow layer.
- Creates cache and result directories.
- Builds quick-thinking and deep-thinking LLM clients.
- Creates tool nodes for market, social, news, and fundamentals tools.
- Builds the LangGraph workflow through `GraphSetup`.
- Runs `.propagate(ticker, trade_date)` and returns final state plus decision.

`tradingagents/graph/setup.py` defines the graph shape. The selected analysts run first, then the research debate, trader, risk debate, and portfolio manager.

Basic programmatic use:

```python
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "ollama"
config["quick_think_llm"] = "tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k"
config["deep_think_llm"] = "tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k"
config["backend_url"] = "http://localhost:11434/v1"

ta = TradingAgentsGraph(config=config)
final_state, decision = ta.propagate("MSFT", "2026-05-29")
print(decision)
```

## Configuration

Defaults live in `tradingagents/default_config.py`. Most important knobs can be overridden with `TRADINGAGENTS_*` environment variables:

- `TRADINGAGENTS_LLM_PROVIDER`
- `TRADINGAGENTS_DEEP_THINK_LLM`
- `TRADINGAGENTS_QUICK_THINK_LLM`
- `TRADINGAGENTS_LLM_BACKEND_URL`
- `TRADINGAGENTS_MAX_DEBATE_ROUNDS`
- `TRADINGAGENTS_MAX_RISK_ROUNDS`
- `TRADINGAGENTS_CHECKPOINT_ENABLED`
- `TRADINGAGENTS_ALPACA_PAPER_ENABLED`
- `TRADINGAGENTS_ALPACA_LIVE_MIRROR_ENABLED`
- `TRADINGAGENTS_PAPER_EXPOSURE_LIMIT`
- `TRADINGAGENTS_LIVE_MIRROR_RATIO`
- `TRADINGAGENTS_LIVE_EXPOSURE_LIMIT`
- Ollama tuning vars such as `TRADINGAGENTS_OLLAMA_MAX_COMPLETION_TOKENS`

On Windows, the config loader can also read matching Windows User environment variables, which is useful for persistent local automation.

API keys and endpoints are documented in `.env.example`. Do not put real keys in repo files.

## LLM and Data Providers

Supported LLM providers are routed through `tradingagents/llm_clients/`. The default config lists OpenAI-style defaults, while the README and `.env.example` show how to use Ollama for local unattended runs.

Data access is abstracted through `tradingagents/dataflows/` and agent tool functions in `tradingagents/agents/utils/agent_utils.py`. The default vendor settings use yfinance for stock data, technical indicators, fundamentals, and news, with optional Alpha Vantage support.

## Alpaca Layer

The Alpaca layer lives mainly in:

- `tradingagents/brokers/alpaca.py`
- `tradingagents/brokers/alpaca_supervisor.py`
- `tradingagents/brokers/paper_tournament.py`

`alpaca.py` handles credentials, account-mode safety checks, order planning, paper order building, live mirror rules, and REST calls.

`alpaca_supervisor.py` builds account snapshots, candidate rankings, dynamic live-cap calculations, hourly decisions, premarket briefs, overnight candidate universes, and daily report text.

`paper_tournament.py` runs a paper-only strategy tournament that compares strategy sleeves such as `current-aggressive`, `pullback-support`, and `catalyst-relative-strength`.

Common commands:

```powershell
tradingagents alpaca check
tradingagents alpaca preview --run-id 20260526-tuesday --third-symbol MSFT --third-limit-price 500
tradingagents alpaca submit --run-id 20260526-tuesday --third-symbol MSFT --third-limit-price 500
tradingagents alpaca supervise-hourly --dry-run --json-output
tradingagents alpaca supervisor-daily-report --json-output
```

The durable safe automation pattern is:

```powershell
alpaca check -> dry-run -> submit only if checks are clean and valid actions exist
```

## Overnight and Premarket Workflow

The overnight planner is analysis-only. It builds a candidate universe from:

- Base liquid/mega-cap universe.
- Current live and paper positions.
- Open order symbols.
- Recent hourly supervisor packets.
- Market verification mentions.
- Optional watchlist files.

Then it ranks candidates and, when runtime allows, runs the full TradingAgents graph for top names. Runtime-bounded fallbacks still rank all tradable names with a shared market snapshot rubric.

Key commands:

```powershell
tradingagents alpaca plan-overnight --json-output
tradingagents alpaca premarket-brief --json-output
tradingagents alpaca verify-overnight-system
```

Important result folders:

| Path | Meaning |
| --- | --- |
| `results/overnight_plans/` | Analysis-only overnight plans, ranked candidates, ticker reports, and full graph logs. |
| `results/premarket_briefs/` | Rolling context briefs built from overnight, hourly, and tournament packets. |
| `results/hourly_supervisor/` | One packet per hourly supervisor tick, including account state, positions, actions, issues, and evidence. |
| `results/paper_strategy_tournament/` | Paper-only tournament ledger, run packets, reports, and latest strategy state. |
| `results/overnight_system_verification/` | Verification packets proving the overnight/premarket/hourly/tournament/report chain is wired. |
| `results/market_verification/` | Manual or run-specific market verification packets. |
| `results/local_model_eval/` | Local model evaluation artifacts. |

Premarket briefs are context only. They do not replace fresh quote, news, order, account, and buying-power validation before any live action.

## Paper Strategy Tournament

The paper tournament is paper-only and should not place live orders. It maintains a ledger, reconciles fills, snapshots equity, ranks strategy sleeves, and can write a live-strategy-selection candidate only after promotion rules are satisfied.

Useful commands:

```powershell
tradingagents alpaca paper-tournament init
tradingagents alpaca paper-tournament run --all --json-output
tradingagents alpaca paper-tournament report --json-output
```

The expected routine state is often quiet: the run writes local packets and may submit no paper orders.

## Persistence and Recovery

There are two separate persistence concepts:

- Trading memory log: completed decisions are appended to the configured memory log so later runs can reflect on prior same-ticker and cross-ticker decisions.
- Checkpoints: when enabled with `--checkpoint` or `TRADINGAGENTS_CHECKPOINT_ENABLED=true`, LangGraph saves node progress so interrupted runs can resume.

Commands:

```powershell
tradingagents analyze --checkpoint
tradingagents analyze --clear-checkpoints
```

## Testing

Tests are pytest-based. The project has focused tests for:

- Alpaca execution and CLI behavior.
- Hourly supervisor decisions and report rendering.
- Paper tournament rules and packets.
- Config/env overrides.
- LLM provider validation and provider-specific options.
- Dataflow behavior and safe ticker handling.
- Signal processing, checkpointing, and persistent memory.

Small targeted checks are usually better than the whole suite while editing:

```powershell
uv run --with pytest python -m pytest tests\test_alpaca_supervisor.py tests\test_alpaca_cli.py -q
uv run --with pytest python -m pytest tests\test_paper_tournament.py -q
```

For a broader repo check:

```powershell
uv run --with pytest python -m pytest -q
```

## Operational Safety Notes

- Run `tradingagents alpaca check` before any order-affecting action.
- Treat `--dry-run` packets as evidence and submit only when the packet has valid actions and no blocking issues.
- Daily reports are read-only summaries.
- Overnight plans and premarket briefs are analysis-only context.
- Paper tournament automation is isolated to paper.
- Live action is capped by dynamic exposure rules and configured Alpaca live limits.
- Keep credentials in environment variables, not in files committed to the repo.

## Where to Start When Changing Code

- CLI command behavior: start in `cli/main.py`.
- Trading graph behavior: start in `tradingagents/graph/trading_graph.py` and `tradingagents/graph/setup.py`.
- Analyst prompt/tool behavior: start in `tradingagents/agents/`.
- Data vendor behavior: start in `tradingagents/dataflows/`.
- Alpaca order safety: start in `tradingagents/brokers/alpaca.py`.
- Hourly, overnight, premarket, and daily report behavior: start in `tradingagents/brokers/alpaca_supervisor.py`.
- Paper tournament behavior: start in `tradingagents/brokers/paper_tournament.py`.
- Regression tests: start in the matching file under `tests/`.
