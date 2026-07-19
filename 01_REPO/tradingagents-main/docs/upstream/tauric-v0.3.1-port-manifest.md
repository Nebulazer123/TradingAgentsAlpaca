# TauricResearch v0.3.1 Selective Port Manifest

Pinned source:

- Checkout: `/tmp/tradingagents-upstream.VojTjl`
- Commit: `01477f9afb7a47b849ed4c9259d3a9a4738d9fda`
- Tag: `v0.3.1`

The source is a reference, not a replacement tree. `implementation_state`
distinguishes completed adaptations from work that remains pending or deferred.

| commit | upstream_subject | priority | local_status | decision | implementation_state | local_files | upstream_tests | focused_proof | reason |
|---|---|---:|---|---|---|---|---|---|---|
| `b47a828` | fix(graph): give the shared debate/risk routers a complete path_map | P0 | equivalent | adapt | adapted | `tradingagents/graph/setup.py`; `tests/test_risk_router_path_map.py` | `tests/test_risk_router_path_map.py` | Router/manifest/concurrency/tool routing: 17 passed. Full suite: 1,490 passed, 1 skipped, 75 subtests passed. | Uses complete shared identity maps while preserving local `Send` fan-out, concurrency limits, tool-free/prefetched factories, branch-local message IDs, and cleanup. |
| `daf1da9` | fix(graph): key checkpoints on graph shape and expose the LLM retry budget | P0 | partial | adapt | pending | None in this slice. | `tests/test_checkpoint_resume.py`; `tests/test_llm_max_retries.py` | Pending. | Planned checkpoint/retry adaptation has not been claimed complete. |
| `7df18fc` | refactor(data): unify vendor errors under a VendorError hierarchy | P0 | partial | adapt | pending | None in this slice. | `tests/test_vendor_errors.py` | Pending. | Planned vendor-error adaptation has not been claimed complete. |
| `ee1ece3` | fix(dataflows): degrade gracefully when an optional vendor fails | P0 | partial | adapt | pending | None in this slice. | `tests/test_fred.py`; `tests/test_vendor_routing.py` | Pending. | Planned graceful-fallback adaptation has not been claimed complete. |
| `9fd54f8` | fix(data): reject stale yfinance OHLCV instead of reporting wrong prices | P0 | missing | port | pending | None in this slice. | `tests/test_yfinance_stale_ohlcv_guard.py` | Pending. | Selected stale-data guard has not been ported. |
| `3570f2e` | fix(dataflows): apply the Alpha Vantage fundamentals look-ahead filter | P0 | missing | port | pending | None in this slice. | `tests/test_alpha_vantage_hardening.py` | Pending. | Selected point-in-time filter has not been ported. |
| `9ad98c5` | fix(data): normalize ticker on the news path | P0 | missing | port | pending | None in this slice. | `tests/test_symbol_normalization_paths.py` | Pending. | Selected news normalization has not been ported. |
| `517eeaf` | fix(structured): harden structured output for local servers and thinking models | P0 | partial | adapt | pending | None in this slice. | `tests/test_openai_compatible_provider.py`; `tests/test_structured_agents.py` | Pending. | Planned structured-output adaptation has not been claimed complete. |
| `0405168` | fix(schema): coerce null-ish strings in optional float fields | P0 | missing | port | pending | None in this slice. | `tests/test_structured_agents.py` | Pending. | Selected schema coercion has not been ported. |
| `622f99d` | fix(analysts): align the news prompt with the get_news tool signature | P0 | missing | port | pending | None in this slice. | `tests/test_news_analyst_prompt.py` | Pending. | Selected prompt/tool alignment has not been ported. |
| `a0120e1` | feat(reporting): share the report-tree writer between the CLI and the API | P1 | partial | adapt | pending | None in this slice. | `tests/test_reporting.py` | Pending. | Planned reporting adaptation has not been claimed complete. |
| `eeb84aa` | fix(reddit): go RSS-first with 429 backoff and robust transport errors | P1 | partial | adapt | pending | None in this slice. | `tests/test_reddit_fallback.py` | Pending. | Planned Reddit adaptation has not been claimed complete. |
| `308757c` | fix(data): catch http.client transport errors in StockTwits | P1 | missing | port | pending | None in this slice. | `tests/test_stocktwits_resilience.py` | Pending. | Selected StockTwits resilience change has not been ported. |
| `a102afa` | fix(dataflows): map crypto to StockTwits/Reddit sentiment symbols | P1 | partial | adapt | pending | None in this slice. | `tests/test_reddit_fallback.py`; `tests/test_stocktwits_resilience.py`; `tests/test_symbol_utils.py` | Pending. | Planned crypto-symbol adaptation has not been claimed complete. |
| `ddfb840` | feat(data): add FRED macro indicators as an optional vendor | P1 | partial | adapt | pending comparison | None in this slice. | `tests/test_fred.py` | Pending comparison. | Local FRED already exists and must be compared before accepting upstream changes. |
| `db05903` | feat(data): add Polymarket prediction markets as a keyless vendor | P2 | missing | port | deferred | None. | `tests/test_polymarket.py` | Deferred. | Add only after P0 proof and only as non-executable advisory evidence. |
| `43bd32b` | feat(llm): support Bedrock API-key auth via AWS_BEARER_TOKEN_BEDROCK | P2 | missing | port | deferred | None. | `tests/test_bedrock_provider.py` | Deferred. | Add only when a real approved credential route is configured. |
| `a420ad0` | fix(cli): honor env precedence for LLM and run config | P1 | partial | adapt | pending | None in this slice. | `tests/test_anthropic_effort.py`; `tests/test_cli_config_precedence.py`; `tests/test_cli_env_skip.py`; `tests/test_env_overrides.py`; `tests/test_openai_reasoning_effort.py` | Pending. | Planned adaptation around the local CLI has not been claimed complete. |
