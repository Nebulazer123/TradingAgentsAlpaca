# User Inputs and Dependency Checklist

This is the complete remaining-input list for the prepared Mac workspace. The software and lockfile dependencies are already installed. The only unfinished items are choices, credentials, external services, and operating limits that belong to the owner.

Do not paste secret values into Codex chat, this document, Git, or the USB transfer. Put secrets in the local files named below or in the macOS Keychain, then tell Codex only which variables are present. A value shown as `<FILL_ME>` is a placeholder, not a usable credential.

## 1. Already prepared

- [x] TradingAgents source imported at `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main`.
- [x] MiroFish source imported at `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/mirofish-main`.
- [x] TradingAgents Python 3.13 environment created at `01_REPO/tradingagents-main/.venv`.
- [x] MiroFish backend Python 3.12 environment created at `01_REPO/mirofish-main/backend/.venv`.
- [x] MiroFish root and frontend Node dependencies installed from their lockfiles.
- [x] TradingAgents focused tests passed (4/4).
- [x] MiroFish backend tests passed (40/40).
- [x] MiroFish frontend production build passed.
- [x] Docker was checked and is not installed; Docker is optional.
- [x] No credential-bearing `.env` files were present in the original transfer. Local `.env` files now exist; values are not included in this checklist.

## 2. Minimum choices to run research

### TradingAgents

Choose exactly one model provider and supply its key. The default code path is OpenAI, but any one of these is supported:

| Provider | Required variable | Model/base-url choices to provide |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | Deep model and quick model, or accept defaults `gpt-5.4` / `gpt-5.4-mini` |
| Google Gemini | `GOOGLE_API_KEY` | Deep model and quick model |
| Anthropic | `ANTHROPIC_API_KEY` | Deep model and quick model |
| xAI | `XAI_API_KEY` | Deep model and quick model |
| DeepSeek | `DEEPSEEK_API_KEY` | Deep model and quick model |
| Qwen international | `DASHSCOPE_API_KEY` | Model names and DashScope region |
| Qwen China | `DASHSCOPE_CN_API_KEY` | Model names and China endpoint |
| GLM international | `ZHIPU_API_KEY` | Model names and Z.AI endpoint |
| GLM China | `ZHIPU_CN_API_KEY` | Model names and BigModel endpoint |
| MiniMax global | `MINIMAX_API_KEY` | Model names and global endpoint |
| MiniMax China | `MINIMAX_CN_API_KEY` | Model names and China endpoint |
| OpenRouter | `OPENROUTER_API_KEY` | Full routed model IDs |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` | Also `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME`; optionally `OPENAI_API_VERSION` |
| Ollama | no API key | Local/remote URL, model IDs, and whether the model is already pulled |

Tell Codex these non-secret choices:

```text
TradingAgents provider:
TradingAgents deep model:
TradingAgents quick model:
TradingAgents backend URL (or “provider default”):
TradingAgents output language:
Local Ollama or hosted provider:
```

### MiroFish

MiroFish has one required LLM route and one required memory service:

- `LLM_API_KEY` — key for the selected OpenAI-compatible provider.
- `LLM_BASE_URL` — for example `https://api.openai.com/v1` or the approved OpenRouter/DashScope-compatible endpoint.
- `LLM_MODEL_NAME` — exact model ID accepted by that endpoint.
- `ZEP_API_KEY` — Zep Cloud memory key.

MiroFish loads these from `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/mirofish-main/.env`; the backend does not need a separate `.env` file.

Provide these non-secret choices:

```text
MiroFish LLM provider:
MiroFish LLM base URL:
MiroFish model name:
MiroFish max simulation rounds:
Use LLM boost route: yes/no
```

If boost is enabled, also provide values for `LLM_BOOST_API_KEY`, `LLM_BOOST_BASE_URL`, and `LLM_BOOST_MODEL_NAME`. Leave the boost variables absent when boost is not being used.

## 3. Optional TradingAgents research sources

The framework can run with public/free fallbacks, including yfinance, Google News RSS, Treasury data, Stocktwits, Reddit, and local indicator computation. These keys improve coverage but are not required for the base install. Add only the sources you actually want:

| Source | Variables | Effect when absent |
|---|---|---|
| SEC EDGAR | `SEC_USER_AGENT` (use a real name and contact email) | SEC route skipped |
| FRED | `FRED_API_KEY` | Macro route skipped |
| BLS | `BLS_API_KEY` | Lower-rate public route may continue |
| BEA | `BEA_API_KEY` | BEA route skipped |
| EIA | `EIA_API_KEY` | EIA route skipped |
| Alpha Vantage | `ALPHA_VANTAGE_API_KEY` | Alpha Vantage enrichment skipped |
| EODHD | `EODHD_API_TOKEN` (optional `EODHD_API_KEY`) | EODHD route skipped |
| AlphaInsider | `ALPHAINSIDER_API_KEY`; optional `ALPHAINSIDER_STRATEGY_ID`, `ALPHAINSIDER_BOT_ID` | Paper-shadow lane skips it |
| Finnhub | `FINNHUB_API_KEY` | Finnhub route skipped |
| Financial Modeling Prep | `FMP_API_KEY` | FMP route skipped |
| Massive/Polygon | `MASSIVE_API_KEY` (optional `POLYGON_API_KEY`) | Massive route skipped |
| Tiingo | `TIINGO_API_KEY` | Tiingo route skipped |
| NewsAPI | `NEWSAPI_API_KEY` | NewsAPI route skipped |
| Marketaux | `MARKETAUX_API_KEY` (optional `MARKETAUX_API_TOKEN`) | Marketaux route skipped |
| ScrapingBee | `SCRAPINGBEE_API_KEY` | Crawler uses fallback routes |
| Composio | `COMPOSIO_API_KEY` | Connected read-only tools skipped |

The complete source-of-truth registry is [research_integrations.example.json](/Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main/config/research_integrations.example.json). It records which integrations are read-only and which values are required by each route.

## 4. Optional local-model setup

Choose this only if you want to avoid paid hosted model calls:

- Install Ollama for macOS.
- Confirm `ollama --version` works.
- Provide `OLLAMA_BASE_URL` only when using a remote server; local default is `http://localhost:11434/v1`.
- Provide `TRADINGAGENTS_DEEP_THINK_LLM` and `TRADINGAGENTS_QUICK_THINK_LLM` model IDs.
- Pull the selected model(s) with `ollama pull <model-id>`.
- For the prepared compact profile, optionally provide `TRADINGAGENTS_OLLAMA_TEMPERATURE`, `TRADINGAGENTS_OLLAMA_MAX_COMPLETION_TOKENS`, `TRADINGAGENTS_OLLAMA_TOP_P`, `TRADINGAGENTS_OLLAMA_PRESENCE_PENALTY`, and valid JSON in `TRADINGAGENTS_OLLAMA_EXTRA_BODY_JSON`.

No Ollama server or model was started by setup.

## 5. Optional Alpaca paper/live path

Do not fill or enable this section for research-only use. If the owner later wants broker connectivity, these are the required values:

### Paper account

- `ALPACA_PAPER_API_KEY`
- `ALPACA_PAPER_SECRET_KEY`
- `ALPACA_PAPER_API_ENDPOINT` (normally `https://paper-api.alpaca.markets`)
- `TRADINGAGENTS_ALPACA_PAPER_ENABLED=true`
- Confirm the paper exposure cap, currently `TRADINGAGENTS_PAPER_EXPOSURE_LIMIT=1000` unless deliberately changed.

### Live mirror account

- `ALPACA_LIVE_API_KEY`
- `ALPACA_LIVE_SECRET_KEY`
- `ALPACA_LIVE_API_ENDPOINT` (normally `https://api.alpaca.markets`)
- `TRADINGAGENTS_ALPACA_LIVE_MIRROR_ENABLED=true`
- Confirm `TRADINGAGENTS_LIVE_MIRROR_RATIO` (default `0.10`).
- Confirm `TRADINGAGENTS_LIVE_EXPOSURE_LIMIT` (default `100`, hard-capped by the project policy).
- Review and, only when intentionally arming live execution, create `config/risk_envelope.yaml` from `config/risk_envelope.example.yaml`.
- Provide the intended account risk limit, per-name cap, sector cap, aggregate beta cap, daily loss halt, drawdown halt, and emergency hard ceiling.

The required pre-submit order is `alpaca check`, then dry-run preview, then a separately reviewed submit action. Never put broker keys in this document.

## 6. Optional automation, connector, and notification inputs

These are deliberately not prepared or enabled:

- n8n: `N8N_API_KEY` only if a separately installed local n8n instance is intentionally connected. Keep the allowlisted runner as the only execution path.
- Composio: `COMPOSIO_API_KEY` plus separately connected read-only app accounts, if used.
- Email: provide the approved delivery method and recipient only after inspecting the notification policy. Do not paste SMTP passwords or OAuth tokens into chat.
- Tailscale/remote Ollama: provide the remote host URL and a tested network path if a second Mac is used as a research mule.
- Docker: install Docker Desktop only if the container deployment path is desired; it is not needed for the source setup already completed.

### n8n local account and runtime

- Docker Desktop and n8n are now installed and running.
- Open `http://localhost:5678` once and create an owner email/password in the local n8n UI. Do not send that password to Codex.
- Owner login and license activation are now complete; the Usage and plan page reports `Community Edition — Registered`. The activation token remains only in n8n's local state.
- The 12 observer/evaluation workflows are already imported and inactive.
- `N8N_API_KEY` is optional and only needed for the repository's Data Table/workflow sync commands; it was intentionally not created.
- The persistent bridge is managed by `~/Library/LaunchAgents/com.tradingagents.n8n-runner.plist` and can be stopped with `launchctl bootout gui/$(id -u)/com.tradingagents.n8n-runner`.

## 7. Safe local file placement when values are ready

### TradingAgents

```bash
cd /Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-main
cp .env.example .env
chmod 600 .env
# Fill only the provider/source variables actually selected.
```

For Azure-only configuration, use `.env.enterprise.example` and keep the resulting file local and untracked.

### MiroFish

```bash
cd /Users/corbinfloyd/Documents/TradingAgents/01_REPO/mirofish-main
cp .env.example .env
chmod 600 .env
# Fill LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, and ZEP_API_KEY.
```

Do not run the servers or simulations merely by creating these files. First run the non-submitting readiness checks documented in the final status file.

## 8. What to send Codex next

Send one non-secret message containing:

1. The chosen TradingAgents provider, deep model, quick model, and whether Ollama is local or remote.
2. The chosen MiroFish base URL and model name.
3. Which optional research sources to activate.
4. Whether the scope is research-only, paper-only, or live-mirror preparation.
5. Whether Docker, Ollama, n8n, Composio, email, or a remote Mac should be prepared.
6. Confirmation that you placed the corresponding secrets locally, without sending the values.

Once those choices are known, Codex can write the local `.env` files from your supplied values, run presence-only checks that never print secrets, and validate the selected provider paths.

## 9. Current blockers and findings

- No selected provider or model has been supplied yet, so external LLM calls cannot be tested. The current MiroFish `.env` does not contain its four required runtime values.
- A local TradingAgents `.env` contains Alpaca variable names. Those values have not been used, and paper/live execution remains disabled and untested.
- No Zep key has been supplied, so MiroFish simulation/memory cannot be tested.
- No broker keys or risk envelope have been supplied; broker operations remain disabled.
- Docker is not installed.
- TradingAgents Ruff reports 25 existing findings; this does not prevent the installed focused tests from passing.
- npm audit reports dependency findings; lockfiles were intentionally not rewritten.

## 10. Readiness helper

Run this whenever you add or change local configuration:

```bash
/Users/corbinfloyd/Documents/TradingAgents/04_SETUP/check_setup_readiness.sh
```

It checks installed tools, virtual environments, Node dependencies, and the presence of the four MiroFish required variables without printing secret values or starting any external process. A `NOTE` for an absent `.env` is expected until the owner supplies configuration.
