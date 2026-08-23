<div align="center">

# TradingAgents Alpaca

**Evidence-rich multi-agent market analysis with explicit safety gates between research, paper execution, and live brokerage.**

[![Python 3.10+][python-badge]][pyproject] [![Version 0.2.5][version-badge]][changelog] [![Apache 2.0][license-badge]][license] [![Analysis first][safety-badge]][safety]

[Quick start](#quick-start) · [Capabilities](#what-this-repository-adds) · [Safety model](#safety-and-broker-boundaries) · [Architecture](#architecture) · [Python API](#python-api) · [Documentation](#documentation)

</div>

<p align="center">
  <img src="assets/schema.png" alt="TradingAgents multi-agent market research and decision workflow" width="100%">
</p>

TradingAgents Alpaca turns market data, news, fundamentals, sentiment, and technical signals into an auditable multi-agent decision process. Specialized analysts build evidence, bullish and bearish researchers challenge it, a trader proposes a position, and risk agents pressure-test the proposal before a portfolio decision is produced.

This repository goes beyond a research demo. It adds provider fallback, evidence packets, persistent decisions, checkpoint recovery, evaluation workflows, Alpaca paper tooling, and fail-closed policy controls around any broker-capable path.

> [!IMPORTANT]
> This project is research and operator tooling—not financial, investment, or trading advice. Language-model output, backtests, paper results, and historical performance do not guarantee future results.

## Why this repository exists

Many trading-agent demos treat a model response as the finish line. Real operation needs a stronger boundary: sources must be inspectable, interruptions must be recoverable, decisions must be replayable, and broker actions must remain separate from research unless an authorized operator deliberately clears every gate.

TradingAgents Alpaca is designed around that boundary:

- **Research stays evidence-first.** Provider routing, source-quality checks, and timestamped packets make it possible to inspect what informed a decision.
- **Agent disagreement is useful.** Analysts and researchers take distinct roles so a single narrative does not silently become consensus.
- **Execution fails closed.** Broker submission is not part of the default analysis path, and live-capable behavior requires explicit configuration plus current policy approval.
- **Operations leave a trail.** Decisions, checkpoints, supervision packets, calibration results, and reconciliation evidence support review and recovery.

## What this repository adds

| Capability | What it gives you |
| --- | --- |
| Multi-agent market judgment | Fundamental, sentiment, news, and technical analysis followed by structured bull/bear debate, trading, and risk review |
| Broad model routing | OpenAI, Google, Anthropic, xAI, DeepSeek, Qwen, GLM, MiniMax, OpenRouter, Azure OpenAI, and local Ollama support |
| Evidence and provenance | Read-only research packets, provider fallback plans, source-quality reviews, and fixed-as-of evaluation inputs |
| Recovery and memory | LangGraph checkpoint resume plus a persistent decision log that carries prior outcomes into later analysis |
| Alpaca operating tools | Connectivity checks, observer reconciliation, paper previews, portfolio supervision, daily reporting, and separately gated submit commands |
| Decision evaluation | Forecast ledgers, outcome labels, calibration guards, walk-forward replay, telemetry, and process-quality reports |
| Local orchestration | Allowlisted automation jobs and an n8n observer bridge that can operate without receiving broker credentials |
| Defensive controls | Policy packets, execution locks, risk envelopes, runtime evidence, and non-authorizing shadow-trial workflows |

## Quick start

### Prerequisites

- Python 3.10 or newer
- [uv](https://docs.astral.sh/uv/) (recommended) or `pip`
- An API key for at least one supported LLM provider, or a local Ollama server

### Install and run

~~~bash
git clone https://github.com/Nebulazer123/TradingAgentsAlpaca.git
cd TradingAgentsAlpaca
cp .env.example .env
# Add one LLM provider key to .env, then:
uv sync
uv run tradingagents
~~~

The interactive CLI asks for a ticker, analysis date, provider, models, analyst roles, and research depth. To see the complete command surface without starting an analysis:

~~~bash
uv run tradingagents --help
uv run tradingagents research --help
uv run tradingagents alpaca --help
~~~

### Install with pip

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
tradingagents
~~~

On Windows, activate the environment with `.venv\Scripts\activate`.

### Run with Docker

~~~bash
cp .env.example .env
# Add one LLM provider key to .env, then:
docker compose run --rm tradingagents
~~~

For local models through the included Ollama profile:

~~~bash
docker compose --profile ollama run --rm tradingagents-ollama
~~~

## Safety and broker boundaries

Research and brokerage are intentionally different modes. The safest useful command should always be the easiest one to reach.

| Surface | Effect | Broker mutation |
| --- | --- | --- |
| `tradingagents` / `tradingagents analyze` | Runs the interactive multi-agent analysis | None |
| `tradingagents research ...` | Produces analysis-only evidence, evaluation, and audit packets | None |
| `tradingagents alpaca check` | Verifies configured account connectivity | None |
| Observer and reconciliation commands | Read broker state and write local evidence | None |
| `tradingagents alpaca preview` | Builds an order preview without submission | None |
| `tradingagents alpaca submit` | Enters the broker-capable path | **Yes—only when explicitly invoked and authorized** |

The checked-in defaults keep both Alpaca paper submission and live mirroring disabled. Enabling environment variables alone is not a blanket authorization: submit-capable paths also evaluate the current policy, control state, execution locks, risk limits, and command-specific requirements at call time.

Safe broker setup starts with read-only checks and previews:

~~~bash
uv run tradingagents alpaca check
uv run tradingagents alpaca preview --paper-only --run-id local-preview
~~~

No submit command is included in this quick path. Review `tradingagents alpaca submit --help`, the policy documentation, and the active control state before any authorized broker operation.

## Architecture

~~~mermaid
flowchart LR
    data[Market data, filings, news, sentiment] --> analysts[Specialist analysts]
    analysts --> debate[Bull and bear research debate]
    debate --> trader[Trader proposal]
    trader --> risk[Risk debate]
    risk --> portfolio[Portfolio decision]
    portfolio --> gate{Policy and execution gates}
    gate -->|authorized| broker[Alpaca paper or live path]
    gate -->|not authorized| hold[Hold or fail closed]

    evidence[Evidence packets, checkpoints, decisions, evaluations]
    analysts -.-> evidence
    portfolio -.-> evidence
    gate -.-> evidence
~~~

The implementation is organized around clear responsibility boundaries:

| Area | Primary path | Responsibility |
| --- | --- | --- |
| Command surface | `cli/main.py` | Typer commands and subsystem composition |
| Agent workflow | `tradingagents/graph/`, `tradingagents/agents/` | Analyst-to-researcher-to-trader-to-risk graph |
| Research and data | `tradingagents/research/`, `tradingagents/dataflows/` | Evidence collection, routing, provenance, and fallback |
| Broker supervision | `tradingagents/brokers/` | Alpaca reads, decisions, previews, reconciliation, and paper workflows |
| Policy and execution | `tradingagents/policy/`, `tradingagents/execution/` | Current authority evaluation, controls, locks, and submit coordination |
| Evaluation | `tradingagents/evals/` | Outcomes, calibration, replay, source quality, and telemetry |
| Orchestration | `tradingagents/orchestration/`, `n8n/` | Allowlisted local jobs and observer integration |
| Verification | `tests/` | Unit, integration, policy, orchestration, and CLI coverage |

## Agent workflow

### Analyst team

- **Fundamentals analyst** evaluates financial statements, business performance, valuation signals, and material risks.
- **Sentiment analyst** turns supported social and market-attention sources into a bounded short-term sentiment view.
- **News analyst** reviews company, sector, macroeconomic, and geopolitical developments.
- **Technical analyst** evaluates price, volume, momentum, and indicator structure.

<p align="center">
  <img src="assets/analyst.png" alt="Fundamental, sentiment, news, and technical analyst roles" width="100%">
</p>

### Bull and bear researchers

The research team argues both sides of the analyst evidence. Structured debate surfaces weak assumptions, missing evidence, asymmetric risks, and conditions that would invalidate the thesis.

<p align="center">
  <img src="assets/researcher.png" alt="Bullish and bearish research agents debating market evidence" width="72%">
</p>

### Trader

The trader turns the research record into a concrete proposal: action, timing, sizing rationale, and the evidence that supports or contradicts it.

<p align="center">
  <img src="assets/trader.png" alt="Trader agent composing a decision proposal" width="72%">
</p>

### Risk team and portfolio manager

Aggressive, conservative, and neutral risk agents challenge the proposal from different postures. The portfolio manager then produces the final decision for the analysis graph. A decision is still not broker authority; any execution remains subject to the separate policy and execution boundary above.

<p align="center">
  <img src="assets/risk.png" alt="Risk agents and portfolio manager reviewing a proposed trade" width="72%">
</p>

## Configuration

Copy the versioned example and keep real credentials out of Git:

~~~bash
cp .env.example .env
~~~

Choose one primary LLM route:

~~~dotenv
OPENAI_API_KEY=
# or GOOGLE_API_KEY, ANTHROPIC_API_KEY, XAI_API_KEY,
# DEEPSEEK_API_KEY, DASHSCOPE_API_KEY, ZHIPU_API_KEY,
# MINIMAX_API_KEY, or OPENROUTER_API_KEY
~~~

Common optional settings include:

~~~dotenv
TRADINGAGENTS_LLM_PROVIDER=openai
TRADINGAGENTS_DEEP_THINK_LLM=gpt-5.4
TRADINGAGENTS_QUICK_THINK_LLM=gpt-5.4-mini
TRADINGAGENTS_MAX_DEBATE_ROUNDS=2
TRADINGAGENTS_CHECKPOINT_ENABLED=true
~~~

See [`.env.example`](.env.example) for the complete non-secret template, including enterprise providers, local Ollama, optional market-data keys, and disabled-by-default Alpaca settings. Provider and model choices can also be made interactively in the CLI.

## CLI tour

Launch the interactive analysis with:

~~~bash
uv run tradingagents
~~~

<p align="center">
  <img src="assets/cli/cli_init.png" alt="TradingAgents interactive CLI configuration screen" width="100%">
</p>

Reports stream into the interface as the agent graph progresses from evidence gathering through the final portfolio decision.

<p align="center">
  <img src="assets/cli/cli_news.png" alt="TradingAgents CLI showing a news analysis report" width="49%">
  <img src="assets/cli/cli_transaction.png" alt="TradingAgents CLI showing the final transaction decision" width="49%">
</p>

## Python API

The same graph can be called from Python. Use a historical or current analysis date that matches the data you intend to evaluate:

~~~python
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"
config["deep_think_llm"] = "gpt-5.4"
config["quick_think_llm"] = "gpt-5.4-mini"
config["max_debate_rounds"] = 2

graph = TradingAgentsGraph(debug=True, config=config)
final_state, decision = graph.propagate("NVDA", "2026-08-21")

print(decision)
~~~

`TradingAgentsGraph.propagate()` defaults to the stock pipeline; programmatic callers can pass `asset_type="crypto"` for the crypto graph. See [`tradingagents/default_config.py`](tradingagents/default_config.py) for the supported configuration surface.

## Persistence and recovery

TradingAgents persists two complementary forms of state:

- **Decision memory:** completed decisions are appended to `~/.tradingagents/memory/trading_memory.md`. Later runs can incorporate realized outcomes and recent same-ticker or cross-ticker lessons. Override the path with `TRADINGAGENTS_MEMORY_LOG_PATH`.
- **Checkpoint resume:** `--checkpoint` stores LangGraph progress per ticker so an interrupted run can resume from its last compatible node. Databases default to `~/.tradingagents/cache/checkpoints/`; override the base with `TRADINGAGENTS_CACHE_DIR`.

~~~bash
uv run tradingagents analyze --checkpoint
uv run tradingagents analyze --clear-checkpoints
~~~

Successful runs clear their completed checkpoint. Generated research, policy, supervision, and evaluation packets remain separate evidence artifacts for later audit and replay.

## Development

Set up the repository with the static-analysis group, then run the focused or complete checks appropriate to your change:

~~~bash
uv sync --group static-analysis
uv run pytest -q
uv run --group static-analysis ruff check cli tradingagents scripts tests
uv run --group static-analysis mypy tradingagents/brokers tradingagents/policy tradingagents/execution tradingagents/dataflows
python -m compileall -q cli tradingagents
~~~

The broad mypy command is the current brokerage/dataflow baseline. A smaller set of modules is held to strict typing; see [`pyproject.toml`](pyproject.toml) before expanding that frontier.

## Contributing

Bug fixes, tests, documentation improvements, provider integrations, and carefully bounded research features are welcome.

1. Create a focused branch or fork.
2. Add or update tests for the behavior you change.
3. Run the relevant pytest, Ruff, typing, and compile checks.
4. Open a pull request that explains the behavior, safety impact, and verification evidence.

Past contributions and release changes are recorded in [`CHANGELOG.md`](CHANGELOG.md).

## Documentation

- [CHANGELOG](CHANGELOG.md) — releases and contributor credits
- [Repository overview](REPO_OVERVIEW.md) — system-level orientation
- [Repository map](docs/consolidation/REPOSITORY_MAP.md) — source domains and operational entry points
- [Pipeline architecture audit](docs/PIPELINE_ARCHITECTURE_AUDIT.md) — architecture findings and boundaries
- [Trading methods and automations](TRADING_METHODS_AND_AUTOMATIONS.md) — research, supervision, and automation inventory
- [Live budget mode](docs/policy/live-budget-mode.md) — broker budget and authority rules

## Research lineage and citation

This repository is independently maintained and extends the multi-agent TradingAgents research baseline with brokerage controls, evidence pipelines, evaluation, orchestration, and recovery layers. For the original framework methodology, read [*TradingAgents: Multi-Agents LLM Financial Trading Framework*](https://arxiv.org/abs/2412.20138).

If the research framework supports your work, cite the paper:

~~~bibtex
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
  title         = {TradingAgents: Multi-Agents LLM Financial Trading Framework},
  author        = {Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
  year          = {2025},
  eprint        = {2412.20138},
  archivePrefix = {arXiv},
  primaryClass  = {q-fin.TR},
  url           = {https://arxiv.org/abs/2412.20138}
}
~~~

## License

Licensed under the [Apache License 2.0](LICENSE).

[python-badge]: https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white
[version-badge]: https://img.shields.io/badge/version-0.2.5-2563EB
[license-badge]: https://img.shields.io/badge/license-Apache--2.0-0F766E
[safety-badge]: https://img.shields.io/badge/default-analysis--first-D97706
[pyproject]: pyproject.toml
[changelog]: CHANGELOG.md
[license]: LICENSE
[safety]: #safety-and-broker-boundaries
