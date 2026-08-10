# Upstream Intelligence Hardening Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Selectively port the highest-value correctness and intelligence fixes from `TauricResearch/TradingAgents` v0.3.1 into the local production fork without losing its Alpaca execution, live policy, paper tournament, connector registry, research orchestration, analyst concurrency, or autonomous-firm work.

**Architecture:** Treat upstream commit `01477f9afb7a47b849ed4c9259d3a9a4738d9fda` as a pinned reference, not as a replacement tree. For each selected change, copy the upstream regression test first, prove the local gap, adapt the smallest implementation to local abstractions, run focused and local safety tests, and commit one concern at a time. Existing local behavior wins when both implementations are valid but the local fork is more capable.

**Tech Stack:** Git, Python, LangGraph, existing provider/dataflow abstractions, pytest, codebase-memory for impact analysis, and the pinned upstream checkout.

## Global Constraints

- Never merge or cherry-pick upstream wholesale.
- Never replace the local Alpaca broker/supervisor, unified live gate, promotion sync, paper tournament, 45-entry integration registry, research packet layers, n8n observer, or analyst concurrency.
- Upstream tests are leads. Adapt them to the local public API when paths or abstractions differ.
- Port correctness and resilience before adding providers.
- A provider failure must degrade to a documented fallback or no-data result; it must not fabricate data.
- Every historical-data port must preserve point-in-time boundaries and reject future information.
- Do not add a dependency unless the selected feature is enabled and the dependency is pinned in `pyproject.toml`.
- Record every accepted, adapted, or rejected upstream item in a manifest with evidence.

---

### Task 1: Pin The Source And Create A Port Manifest

**Files:**
- Create: `docs/upstream/tauric-v0.3.1-port-manifest.md`
- Create: `tests/test_upstream_port_manifest.py`
- Reference checkout: `/tmp/tradingagents-upstream.VojTjl`

- [ ] **Step 1: Verify the pinned source**

```bash
cd /tmp/tradingagents-upstream.VojTjl
git rev-parse HEAD
git describe --tags --exact-match HEAD
```

Expected:

```text
01477f9afb7a47b849ed4c9259d3a9a4738d9fda
v0.3.1
```

- [ ] **Step 2: Write the manifest structure**

Use one row per upstream commit:

```text
commit
upstream_subject
priority
local_status: missing | partial | equivalent | superseded
decision: port | adapt | reject
local_files
upstream_tests
focused_proof
reason
```

Seed these decisions:

| Commit | Priority | Initial decision |
|---|---:|---|
| `b47a828` complete debate/risk path maps | P0 | adapt |
| `daf1da9` graph-shape checkpoint and LLM retry budget | P0 | adapt |
| `7df18fc` vendor error hierarchy | P0 | adapt |
| `ee1ece3` optional-vendor graceful fallback | P0 | adapt |
| `9fd54f8` stale yfinance OHLCV guard | P0 | port |
| `3570f2e` Alpha Vantage look-ahead filter | P0 | port |
| `9ad98c5` news ticker normalization | P0 | port |
| `517eeaf` structured-output hardening | P0 | adapt |
| `0405168` null-ish structured fields | P0 | port |
| `622f99d` news prompt/tool alignment | P0 | port |
| `a0120e1` shared report writer | P1 | adapt |
| `eeb84aa` Reddit resilience | P1 | adapt |
| `308757c` StockTwits transport resilience | P1 | port |
| `a102afa` crypto sentiment normalization | P1 | adapt |
| `ddfb840` FRED | P1 | compare; local FRED already exists |
| `db05903` Polymarket | P2 | add only after P0 proof |
| `43bd32b` Bedrock API-key auth | P2 | add only when configured |
| `a420ad0` CLI env precedence | P1 | adapt around local CLI |

- [ ] **Step 3: Add a manifest consistency test**

```python
from pathlib import Path


def test_manifest_tracks_every_selected_commit():
    text = Path("docs/upstream/tauric-v0.3.1-port-manifest.md").read_text()
    selected = {
        "b47a828",
        "daf1da9",
        "7df18fc",
        "ee1ece3",
        "9fd54f8",
        "3570f2e",
        "9ad98c5",
        "517eeaf",
        "0405168",
        "622f99d",
        "a0120e1",
        "eeb84aa",
        "308757c",
        "a102afa",
        "ddfb840",
        "db05903",
        "43bd32b",
        "a420ad0",
    }
    assert all(commit in text for commit in selected)
    assert "01477f9afb7a47b849ed4c9259d3a9a4738d9fda" in text
```

- [ ] **Step 4: Verify and commit**

```bash
uv run --with pytest python -m pytest tests/test_upstream_port_manifest.py -q
git add docs/upstream/tauric-v0.3.1-port-manifest.md tests/test_upstream_port_manifest.py
git commit -m "docs: pin upstream hardening manifest"
```

Expected: PASS.

---

### Task 2: Port Complete Graph Routing Maps

**Files:**
- Modify: `tradingagents/graph/setup.py`
- Create/adapt: `tests/test_risk_router_path_map.py`
- Modify: `tests/test_original_tradingagents_workflow.py`
- Preserve: `tradingagents/graph/analyst_execution.py`

- [ ] **Step 1: Inspect the exact upstream diff**

```bash
git -C /tmp/tradingagents-upstream.VojTjl show b47a828 -- \
  tradingagents/graph/setup.py \
  tests/test_risk_router_path_map.py
```

- [ ] **Step 2: Copy the regression test and run RED**

Copy the upstream test, then adapt imports only.

```bash
uv run --with pytest python -m pytest tests/test_risk_router_path_map.py -q
```

Expected: FAIL if any shared conditional router omits a declared destination.

- [ ] **Step 3: Add explicit complete `path_map` dictionaries**

Every shared debate/risk router must enumerate all reachable destinations:

```python
DEBATE_PATH_MAP = {
    "Bull Researcher": "Bull Researcher",
    "Bear Researcher": "Bear Researcher",
    "Research Manager": "Research Manager",
}

RISK_PATH_MAP = {
    "Aggressive Analyst": "Aggressive Analyst",
    "Conservative Analyst": "Conservative Analyst",
    "Neutral Analyst": "Neutral Analyst",
    "Portfolio Manager": "Portfolio Manager",
}
```

Use the applicable subset at each node only when LangGraph requires it, but the test must prove every value returned by each conditional function appears in that node's `path_map`.

- [ ] **Step 4: Preserve local analyst concurrency**

Run:

```bash
uv run --with pytest python -m pytest \
  tests/test_risk_router_path_map.py \
  tests/test_analyst_concurrency.py \
  tests/test_original_tradingagents_workflow.py -q
```

Expected: PASS; concurrent `Send` fan-out remains available.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/graph/setup.py tests/test_risk_router_path_map.py tests/test_original_tradingagents_workflow.py docs/upstream/tauric-v0.3.1-port-manifest.md
git commit -m "fix: complete graph router path maps"
```

---

### Task 3: Key Checkpoints To Graph Shape And Expose Retry Budgets

**Files:**
- Modify: `tradingagents/default_config.py`
- Modify: `tradingagents/graph/checkpointer.py`
- Modify: `tradingagents/graph/trading_graph.py`
- Create/adapt: `tests/test_llm_max_retries.py`
- Modify: `tests/test_checkpoint_resume.py`

- [ ] **Step 1: Inspect upstream**

```bash
git -C /tmp/tradingagents-upstream.VojTjl show daf1da9 -- \
  tradingagents/default_config.py \
  tradingagents/graph/checkpointer.py \
  tradingagents/graph/trading_graph.py \
  tests/test_checkpoint_resume.py \
  tests/test_llm_max_retries.py
```

- [ ] **Step 2: Port tests and run RED**

```bash
uv run --with pytest python -m pytest tests/test_checkpoint_resume.py tests/test_llm_max_retries.py -q
```

Expected: at least one test fails before the port.

- [ ] **Step 3: Add a stable graph-shape signature**

The checkpoint identity must include:

```text
selected analyst keys and order
analyst concurrency limit
tool-free analyst set
debate-round limit
risk-round limit
packet-boundary schema version
```

Do not include volatile timestamps, model responses, or absolute worktree paths.

- [ ] **Step 4: Route `llm_max_retries` to every client**

Default config:

```python
"llm_max_retries": 2,
```

Provider kwargs must pass the configured value to quick and deep clients. A value of `0` must remain `0`, not be replaced by a truthy default.

- [ ] **Step 5: Verify and commit**

```bash
uv run --with pytest python -m pytest \
  tests/test_checkpoint_resume.py \
  tests/test_llm_max_retries.py \
  tests/test_graph_packet_handoffs.py \
  tests/test_original_tradingagents_workflow.py -q
git add tradingagents/default_config.py tradingagents/graph/checkpointer.py tradingagents/graph/trading_graph.py tests/test_checkpoint_resume.py tests/test_llm_max_retries.py docs/upstream/tauric-v0.3.1-port-manifest.md
git commit -m "fix: bind checkpoints to graph shape"
```

Expected: PASS.

---

### Task 4: Unify Vendor Failures And Preserve Graceful Fallbacks

**Files:**
- Create/adapt: `tradingagents/dataflows/errors.py`
- Modify: `tradingagents/dataflows/interface.py`
- Modify: `tradingagents/dataflows/alpha_vantage_common.py`
- Modify: `tradingagents/dataflows/fred.py`
- Modify: `tradingagents/dataflows/symbol_utils.py`
- Create/adapt: `tests/test_vendor_errors.py`
- Modify: `tests/test_vendor_routing.py`
- Modify: `tests/test_fred.py`

- [ ] **Step 1: Inspect both upstream commits**

```bash
git -C /tmp/tradingagents-upstream.VojTjl show 7df18fc
git -C /tmp/tradingagents-upstream.VojTjl show ee1ece3
```

- [ ] **Step 2: Copy error and routing tests, then run RED**

```bash
uv run --with pytest python -m pytest \
  tests/test_vendor_errors.py \
  tests/test_vendor_routing.py \
  tests/test_fred.py -q
```

Expected: FAIL where local errors are untyped or optional vendor failures abort the entire dataflow.

- [ ] **Step 3: Implement the hierarchy**

```python
class VendorError(RuntimeError):
    vendor: str
    retryable: bool

    def __init__(self, message: str, *, vendor: str, retryable: bool):
        super().__init__(message)
        self.vendor = vendor
        self.retryable = retryable


class VendorAuthenticationError(VendorError):
    pass


class VendorRateLimitError(VendorError):
    pass


class VendorNoDataError(VendorError):
    pass


class VendorTransportError(VendorError):
    pass


class VendorSchemaError(VendorError):
    pass
```

Classify:

```text
missing/invalid key -> VendorAuthenticationError(retryable=False)
HTTP 429 -> VendorRateLimitError(retryable=True)
timeout/connection/http.client errors -> VendorTransportError(retryable=True)
valid empty response -> VendorNoDataError(retryable=False)
malformed payload -> VendorSchemaError(retryable=False)
```

- [ ] **Step 4: Add fallback behavior**

Optional vendors return a structured unavailable result:

```json
{
  "status": "unavailable",
  "vendor": "fred",
  "retryable": true,
  "reason": "transport error",
  "data": null
}
```

Required market-price data remains fail-closed; it must not fall back to fabricated or stale values.

- [ ] **Step 5: Verify and commit**

```bash
uv run --with pytest python -m pytest \
  tests/test_vendor_errors.py \
  tests/test_vendor_routing.py \
  tests/test_fred.py \
  tests/test_research_provider_orchestrator.py \
  tests/test_decision_vendor_adapters.py -q
git add tradingagents/dataflows/errors.py tradingagents/dataflows/interface.py tradingagents/dataflows/alpha_vantage_common.py tradingagents/dataflows/fred.py tradingagents/dataflows/symbol_utils.py tests/test_vendor_errors.py tests/test_vendor_routing.py tests/test_fred.py docs/upstream/tauric-v0.3.1-port-manifest.md
git commit -m "fix: unify vendor failures and fallbacks"
```

Expected: PASS.

---

### Task 5: Reject Stale Market Data And Future Fundamentals

**Files:**
- Modify: `tradingagents/dataflows/stockstats_utils.py`
- Modify: `tradingagents/dataflows/y_finance.py`
- Modify: `tradingagents/dataflows/alpha_vantage_fundamentals.py`
- Create/adapt: `tests/test_yfinance_stale_ohlcv_guard.py`
- Modify: `tests/test_alpha_vantage_hardening.py`
- Modify: `tests/test_date_boundaries.py`

- [ ] **Step 1: Inspect upstream**

```bash
git -C /tmp/tradingagents-upstream.VojTjl show 9fd54f8
git -C /tmp/tradingagents-upstream.VojTjl show 3570f2e
```

- [ ] **Step 2: Port tests and run RED**

```bash
uv run --with pytest python -m pytest \
  tests/test_yfinance_stale_ohlcv_guard.py \
  tests/test_alpha_vantage_hardening.py \
  tests/test_date_boundaries.py -q
```

Expected: FAIL before implementation.

- [ ] **Step 3: Enforce OHLCV freshness**

For a requested as-of date:

- Reject an empty frame.
- Reject a final bar older than the allowed market-session tolerance.
- Reject a bar later than the as-of boundary in historical mode.
- Include the requested date, actual final bar date, and vendor in the error.
- Never relabel the latest available old bar as current.

- [ ] **Step 4: Enforce point-in-time fundamentals**

Filter Alpha Vantage statements by the date the information was available, not merely the fiscal period. A statement published after `as_of` must not appear in historical analysis.

- [ ] **Step 5: Verify and commit**

```bash
uv run --with pytest python -m pytest \
  tests/test_yfinance_stale_ohlcv_guard.py \
  tests/test_alpha_vantage_hardening.py \
  tests/test_date_boundaries.py \
  tests/test_market_verification.py \
  tests/test_live_gate.py -q
git add tradingagents/dataflows/stockstats_utils.py tradingagents/dataflows/y_finance.py tradingagents/dataflows/alpha_vantage_fundamentals.py tests/test_yfinance_stale_ohlcv_guard.py tests/test_alpha_vantage_hardening.py tests/test_date_boundaries.py docs/upstream/tauric-v0.3.1-port-manifest.md
git commit -m "fix: reject stale and future market evidence"
```

Expected: PASS.

---

### Task 6: Normalize Symbols Across News And Sentiment

**Files:**
- Modify: `tradingagents/dataflows/symbol_utils.py`
- Modify: `tradingagents/dataflows/yfinance_news.py`
- Modify: `tradingagents/dataflows/reddit.py`
- Modify: `tradingagents/dataflows/stocktwits.py`
- Create/adapt: `tests/test_symbol_normalization_paths.py`
- Modify: `tests/test_symbol_utils.py`
- Modify: `tests/test_reddit_fallback.py`
- Modify: `tests/test_stocktwits_resilience.py`

- [ ] **Step 1: Inspect upstream**

```bash
git -C /tmp/tradingagents-upstream.VojTjl show 9ad98c5
git -C /tmp/tradingagents-upstream.VojTjl show a102afa
git -C /tmp/tradingagents-upstream.VojTjl show eeb84aa
git -C /tmp/tradingagents-upstream.VojTjl show 308757c
```

- [ ] **Step 2: Port tests and run RED**

```bash
uv run --with pytest python -m pytest \
  tests/test_symbol_normalization_paths.py \
  tests/test_symbol_utils.py \
  tests/test_reddit_fallback.py \
  tests/test_stocktwits_resilience.py -q
```

Expected: at least one failure.

- [ ] **Step 3: Use one instrument identity**

Normalize:

```text
equity canonical symbol
vendor-specific news symbol
StockTwits symbol
Reddit search symbol
crypto base/quote pair when analysis mode is crypto
```

Do not let crypto normalization alter the stock-only live execution charter.

- [ ] **Step 4: Add transport resilience**

- Reddit: RSS-first, bounded 429 backoff, typed transport failure.
- StockTwits: catch `http.client` transport errors and return structured unavailable evidence.
- Neither source failure blocks price/fundamental analysis when those lanes are healthy.

- [ ] **Step 5: Verify and commit**

```bash
uv run --with pytest python -m pytest \
  tests/test_symbol_normalization_paths.py \
  tests/test_symbol_utils.py \
  tests/test_reddit_fallback.py \
  tests/test_stocktwits_resilience.py \
  tests/test_crypto_asset_mode.py -q
git add tradingagents/dataflows/symbol_utils.py tradingagents/dataflows/yfinance_news.py tradingagents/dataflows/reddit.py tradingagents/dataflows/stocktwits.py tests/test_symbol_normalization_paths.py tests/test_symbol_utils.py tests/test_reddit_fallback.py tests/test_stocktwits_resilience.py docs/upstream/tauric-v0.3.1-port-manifest.md
git commit -m "fix: normalize symbols and sentiment fallbacks"
```

Expected: PASS.

---

### Task 7: Harden Structured Output And Analyst Prompts

**Files:**
- Modify: `tradingagents/agents/utils/structured.py`
- Modify: `tradingagents/agents/schemas.py`
- Modify: `tradingagents/llm_clients/openai_client.py`
- Modify: `tradingagents/agents/analysts/news_analyst.py`
- Modify: `tradingagents/agents/analysts/market_analyst.py`
- Modify: `tradingagents/agents/analysts/fundamentals_analyst.py`
- Modify: `tradingagents/agents/analysts/sentiment_analyst.py`
- Modify: `tests/test_structured_agents.py`
- Create/adapt: `tests/test_openai_compatible_provider.py`
- Create/adapt: `tests/test_news_analyst_prompt.py`
- Create/adapt: `tests/test_openai_responses_base_url.py`

- [ ] **Step 1: Inspect upstream**

```bash
git -C /tmp/tradingagents-upstream.VojTjl show 517eeaf
git -C /tmp/tradingagents-upstream.VojTjl show 0405168
git -C /tmp/tradingagents-upstream.VojTjl show 622f99d
git -C /tmp/tradingagents-upstream.VojTjl show 2b2d685
git -C /tmp/tradingagents-upstream.VojTjl show 3cddf1e
```

- [ ] **Step 2: Port tests and run RED**

```bash
uv run --with pytest python -m pytest \
  tests/test_structured_agents.py \
  tests/test_openai_compatible_provider.py \
  tests/test_news_analyst_prompt.py \
  tests/test_openai_responses_base_url.py -q
```

Expected: at least one failure.

- [ ] **Step 3: Harden parsing and client selection**

- Coerce null-ish optional numeric strings (`""`, `"null"`, `"none"`, `"n/a"`) to `None`.
- Preserve a real numeric zero.
- Use native OpenAI Responses API only for native OpenAI endpoints.
- Use compatible chat-completions behavior for local/OpenRouter-compatible base URLs.
- Preserve reasoning/thinking-model structured-output behavior.

- [ ] **Step 4: Align prompts**

- Put the actual trade date near the top.
- Make the news tool signature in the prompt match the bound function.
- Explicitly prohibit evidence published after the trade date.
- Preserve the local macro/supplemental tools and packet references.

- [ ] **Step 5: Verify and commit**

```bash
uv run --with pytest python -m pytest \
  tests/test_structured_agents.py \
  tests/test_openai_compatible_provider.py \
  tests/test_news_analyst_prompt.py \
  tests/test_openai_responses_base_url.py \
  tests/test_openai_reasoning_effort.py \
  tests/test_llm_clients.py -q
git add tradingagents/agents/utils/structured.py tradingagents/agents/schemas.py tradingagents/llm_clients/openai_client.py tradingagents/agents/analysts tests/test_structured_agents.py tests/test_openai_compatible_provider.py tests/test_news_analyst_prompt.py tests/test_openai_responses_base_url.py docs/upstream/tauric-v0.3.1-port-manifest.md
git commit -m "fix: harden structured analyst output"
```

Expected: PASS.

---

### Task 8: Share Report Writing Without Replacing Local Packets

**Files:**
- Create/adapt: `tradingagents/reporting.py`
- Modify: `tradingagents/graph/trading_graph.py`
- Modify: `cli/main.py`
- Create/adapt: `tests/test_reporting.py`

- [ ] **Step 1: Inspect upstream**

```bash
git -C /tmp/tradingagents-upstream.VojTjl show a0120e1
```

- [ ] **Step 2: Port the report writer test and run RED**

```bash
uv run --with pytest python -m pytest tests/test_reporting.py -q
```

Expected: FAIL if CLI and API still duplicate or disagree on report trees.

- [ ] **Step 3: Adapt the shared writer**

The writer must:

- Write the original analyst/debate/trader/risk/portfolio reports.
- Include compact decision packet references.
- Never embed broker secrets or raw environment values.
- Preserve existing result packet paths consumed by supervisors and automations.
- Be callable from both CLI and `TradingAgentsGraph`.

- [ ] **Step 4: Verify and commit**

```bash
uv run --with pytest python -m pytest \
  tests/test_reporting.py \
  tests/test_original_tradingagents_workflow.py \
  tests/test_graph_packet_handoffs.py \
  tests/test_alpaca_cli.py -q
git add tradingagents/reporting.py tradingagents/graph/trading_graph.py cli/main.py tests/test_reporting.py docs/upstream/tauric-v0.3.1-port-manifest.md
git commit -m "refactor: share TradingAgents report writer"
```

Expected: PASS.

---

### Task 9: Evaluate Optional Provider Additions After P0 Is Green

**Files:**
- Compare: `tradingagents/dataflows/fred.py`
- Optionally create: `tradingagents/dataflows/polymarket.py`
- Optionally create: `tradingagents/agents/utils/prediction_markets_tools.py`
- Optionally create: `tradingagents/llm_clients/bedrock_client.py`
- Modify only if enabled: `tradingagents/default_config.py`, `pyproject.toml`, `.env.example`
- Create/adapt if enabled: `tests/test_polymarket.py`, `tests/test_bedrock_provider.py`

- [ ] **Step 1: Compare local FRED against `ddfb840` and `ee1ece3`**

```bash
git diff --no-index \
  /tmp/tradingagents-upstream.VojTjl/tradingagents/dataflows/fred.py \
  tradingagents/dataflows/fred.py
```

Expected: differences are classified in the manifest. Keep the local version when it has equivalent freshness, error, and fallback behavior.

- [ ] **Step 2: Add Polymarket only as advisory evidence**

If enabled, port `db05903` with:

```text
can_submit_orders = false
execution_authority = none
optional vendor failure = structured unavailable
prediction-market evidence = news/research input only
```

- [ ] **Step 3: Add Bedrock only when a real route is configured**

If `AWS_BEARER_TOKEN_BEDROCK` or an approved AWS credential route is not configured, mark `43bd32b` as deferred in the manifest and do not add dead code or dependencies.

- [ ] **Step 4: Verify enabled features**

```bash
uv run --with pytest python -m pytest tests/test_fred.py tests/test_polymarket.py tests/test_bedrock_provider.py -q
```

Expected: PASS for files that exist. If a feature is deferred, omit its nonexistent test from the command and record the reason.

- [ ] **Step 5: Commit the bounded optional slice**

```bash
git add tradingagents tests pyproject.toml .env.example docs/upstream/tauric-v0.3.1-port-manifest.md
git commit -m "feat: add vetted optional research providers"
```

Do not create this commit when both optional providers are deferred; commit only the manifest update with an accurate message.

---

### Task 10: Run Upstream Port Done Proof

**Files:**
- Update: `docs/upstream/tauric-v0.3.1-port-manifest.md`
- Create runtime proof: `results/control_plane/proofs/upstream-hardening.json`

- [ ] **Step 1: Run all port regressions**

```bash
uv run --with pytest python -m pytest \
  tests/test_risk_router_path_map.py \
  tests/test_checkpoint_resume.py \
  tests/test_llm_max_retries.py \
  tests/test_vendor_errors.py \
  tests/test_vendor_routing.py \
  tests/test_yfinance_stale_ohlcv_guard.py \
  tests/test_alpha_vantage_hardening.py \
  tests/test_symbol_normalization_paths.py \
  tests/test_symbol_utils.py \
  tests/test_reddit_fallback.py \
  tests/test_stocktwits_resilience.py \
  tests/test_structured_agents.py \
  tests/test_openai_compatible_provider.py \
  tests/test_news_analyst_prompt.py \
  tests/test_openai_responses_base_url.py \
  tests/test_reporting.py -q
```

Expected: PASS.

- [ ] **Step 2: Run local capability preservation tests**

```bash
uv run --with pytest python -m pytest \
  tests/test_analyst_concurrency.py \
  tests/test_integration_registry.py \
  tests/test_research_provider_orchestrator.py \
  tests/test_paper_tournament.py \
  tests/test_promotion_sync.py \
  tests/test_live_gate.py \
  tests/test_alpaca_execution.py \
  tests/test_alpaca_supervisor.py \
  tests/test_n8n_runner_policy.py -q
```

Expected: PASS.

- [ ] **Step 3: Re-index and run impact review**

Re-index the implementation worktree and use graph impact analysis on:

```text
tradingagents/graph/
tradingagents/dataflows/
tradingagents/llm_clients/
tradingagents/reporting.py
```

Verify coverage before claiming every route or provider is preserved.

- [ ] **Step 4: Finalize the manifest**

No row may remain `missing`, `partial`, or undecided. Every row ends as `ported`, `adapted`, `equivalent`, `superseded`, or `deferred` with an evidence-backed reason.

- [ ] **Step 5: Commit**

```bash
git add docs/upstream/tauric-v0.3.1-port-manifest.md
git commit -m "docs: close upstream hardening audit"
```

Expected: complete manifest and green proof.
