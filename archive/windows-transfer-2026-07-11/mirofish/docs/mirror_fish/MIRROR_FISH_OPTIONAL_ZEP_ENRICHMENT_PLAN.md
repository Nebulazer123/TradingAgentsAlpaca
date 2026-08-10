# Mirror Fish Optional Zep Enrichment Plan

Generated: 2026-06-03

## Verdict

`report_44fb26ddc574` is the accepted current Step 4 baseline. It is complete, usable, English-only, and does not need an immediate Step 4 rerun for basic report quality.

Do not rerun Stage 1, Stage 2, Stage 3, hydration, or Step 4 just to make the report feel newer. A Step 4 rerun is justified only if targeted Zep enrichment materially changes the weak areas below.

This plan is optional enrichment only. It does not call Zep, does not run cache hydration, does not rerun Step 4, and does not touch simulations or trading execution.

## Current Evidence State

- Active report: `backend/uploads/reports/report_44fb26ddc574/`
- Simulation: `sim_974459649906`
- Zep graph: `mirofish_4a9df9ae8b184878`
- Zep cache: `backend/uploads/reports/_zep_cache/mirofish_4a9df9ae8b184878/`
- Hydration summary: `completed_queries=40`, `calls_succeeded=40`, `calls_rate_limited=0`
- Step 4 diagnostics: `calls_attempted=50`, `calls_succeeded=48`, `calls_rate_limited=2`, `calls_skipped=98`, `cache_hits=20`, `cache_misses=146`
- `graph.search` worked, but all-node/all-edge panorama was skipped/deferred by safe mode.
- Every section passed quality gates, but every section still has pending/rate-limited provenance preserved in evidence packets.

## Weak Areas To Target

1. Company/executive narrative.
   - Primary target. Section 13 is usable but thin compared with macro, ticker, early-warning, and institutional sections.
   - It had a direct `zep_rate_limited` miss on the company/executive panorama query.
   - Enrichment should look for Apple WWDC, Nvidia/semiconductor AI infrastructure, Oracle/Broadcom-style AI infrastructure beats, broker/fintech executives, investor-relations framing, and HOOD/BULL broker-stock narrative links.

2. Broker/platform implementation.
   - Section 8 is strong enough for baseline use, but additional graph facts could sharpen platform-specific differences.
   - Target broker notices, status-page language, buying-power rejections, API field changes, settlement confusion, compliance review, and customer-support correction loops across Robinhood, Alpaca, Schwab, Fidelity, Webull, IBKR, and tastytrade.

3. External validation query pack.
   - Section 18 correctly identifies validation tasks, but the report does not pull live quotes, options chains, Treasury auction results, oil headlines, broker rejection rates, or market-maker flow.
   - Enrichment should produce a cleaner mapping from simulation indices to real-world validation checks, not trade signals.

4. Institutional liquidity.
   - Section 10 is adequate, but several institutional and liquidity-provider queries were skipped for section budget exhaustion.
   - Target dealer gamma, 0DTE hedging, ETF desk reaction, order-flow toxicity, spread widening, retail clustering, fade/absorb/amplify behavior, and macro-liquidity overrides.

5. AI/bot/developer behavior.
   - Sections 7 and 12 are useful but mostly synthesized from local telemetry and capped Zep facts.
   - Target prompt-bot hallucinated leverage, API retry queues, sandbox validation failures, broker API branch divergence, open-source bot framework updates, and automation risk circuits.

6. Retail/social narrative.
   - Sections 6 and 11 are acceptable, but additional graph facts could separate real narrative changes from repeated simulated chatter.
   - Target Reddit/X/YouTube/TikTok simplification loops, finfluencer correction cycles, 0DTE gambler behavior, cash-account settlement confusion, and screenshot-driven false positives.

## Targeted Zep graph.search Query Packs

Run these as graph.search enrichment candidates only after approval. Use small batches, one group at a time. Prefer exact strings below so cache keys stay deterministic and reviewable.

### Company/Executive

```text
company and tech executive narrative map Apple WWDC Nvidia Oracle Broadcom AI infrastructure fintech executives broker executives investor relations June 4 13 2026 PDT intraday margin
fintech founders broker executives investor relations corporate narratives PDT transition macro override June 2026 HOOD BULL Robinhood Schwab Fidelity Webull Alpaca
Apple WWDC June 8 2026 AI announcements semiconductor executives Nvidia Oracle Broadcom retail flow narrative broker platform stocks PDT intraday margin
agentic trading product framing broker executives fintech investor relations HOOD BULL relative performance PDT intraday margin June 2026
semiconductor AI infrastructure executive narrative Nvidia Oracle Broadcom Apple WWDC macro override retail speculation June 4 13 2026
broker platform stock narrative HOOD BULL Schwab Fidelity Robinhood Alpaca executive comments investor relations PDT removal intraday margin
```

### Broker/Platform

```text
broker platform UI confusion buying power margin calculation API changes settlement misunderstanding compliance review rollout fragmentation June 4 13 2026
Robinhood Alpaca Schwab Fidelity Webull IBKR tastytrade PDT intraday margin implementation buying power rejection status page API field changes
broker status page updates API rate limits compliance review UI text translation PDT intraday margin June 2026
Alpaca Trading API Broker API PDT field removal day trade count margin deficit rejection June 4 2026 intraday margin
broker customer support FAQ PDT removal cash account settlement margin account buying power confusion June 2026
platform rollout fragmentation Robinhood Alpaca Schwab Fidelity Webull implementation timeline broker confusion index June 4 13 2026
```

### Macro/Options Validation

```text
validation tasks real market data mapping simulation indices to real metrics macro override broker friction bot correlation institutional liquidity
June 5 2026 jobs report SPY QQQ intraday volume volatility Treasury yields PDT retail flow causal attribution
June 10 CPI June 11 PPI Treasury auctions oil geopolitics Fed repricing retail flow PDT intraday margin validation
0DTE options SPY QQQ June 5 June 12 2026 gamma IV open interest spreads retail clustering validation
macro dominance index payrolls CPI PPI Treasury auction yield curve oil shock options expiration PDT transition
broker rejection rates buying power failures options IV OI spreads market maker flow validation June 4 13 2026
```

### Institutional/Liquidity

```text
institutional investor market maker liquidity provider reaction order flow toxicity spread adjustment gamma hedging June 4 2026 PDT transition
institutional liquidity provider market maker reaction order flow toxicity options gamma hedging 0DTE retail clustering fade absorb
quant fund ETF desk prop desk reaction retail clustering 0DTE PDT intraday margin June 2026
institutional_fade_absorb_amplify_index market maker liquidity provider reaction order flow toxicity macro override
dealer gamma hedging ETF desk liquidity withdrawal spread widening retail flow toxicity June 4 13 2026
market maker liquidity provider adaptive spreads broker friction macro dominance retail order flow June 2026 PDT intraday margin
```

### AI/Bot/Developer

```text
AI bot prompt bot failure modes brittle signal convergence prompt engineering flaws API integration failures false positive crowding June 4 13 PDT intraday margin
AI bot API integration failures prompt hallucination leverage PDT transition buying power rejection broker risk checks
developer community broker API changes bot framework updates June 2026 PDT transition open source trading infrastructure
developer infrastructure branch API error handling bot framework sandbox validation retry queues broker platform fragmentation
prompt engineered trading bots copycat behavior context drift API rate limits sandbox validation 0DTE retail flow PDT June 2026
automation risk circuits broker API maintainers hard risk checks order routing slippage PDT intraday margin June 2026
```

### Retail/Social

```text
retail trader archetypes behavior PDT intraday margin transition small account cash account AI bot prompt bot 0DTE gambler
cash account settlement misunderstanding 0DTE gambler PDT rule confusion retail flow behavior June 2026
media influencer narrative evolution YouTube TikTok Reddit X PDT June 2026 broker FAQ correction
media influencer YouTube TikTok Reddit finfluencer narrative simplification PDT June 2026 order flow false positive
weak noisy signals false positives retail UI screenshots broker status page panic 0DTE volume spikes AI bot copycat convergence
false signal risk index broker status page retail screenshots 0DTE volume noise AI bot copycat false positive
```

## Slow Hydration Command

Do not run this until enrichment is approved. This command is intentionally slow, resumable, cache-first, graph.search-only, and small-batch.

```powershell
.\backend\.venv\Scripts\python.exe backend\scripts\hydrate_zep_report_cache.py `
  --simulation-id sim_974459649906 `
  --graph-id mirofish_4a9df9ae8b184878 `
  --cache-root backend\uploads\reports\_zep_cache\mirofish_4a9df9ae8b184878 `
  --interval-seconds 20 `
  --limit 6 `
  --max-queries 8 `
  --section "Company and tech-executive narrative map"
```

Recommended sequence if enrichment proceeds:

1. Start with `--section "Company and tech-executive narrative map"` because it is the thinnest material section.
2. Re-run later with `--section "Broker/platform confusion patterns"` only if company/executive hydration produces useful new facts.
3. Re-run later with `--section "Institutional investor, market-maker, and liquidity-provider reaction map"` only if broker/platform hydration produces useful new facts.
4. Stop after each small batch and inspect `backend/uploads/reports/_zep_cache/mirofish_4a9df9ae8b184878/hydration_summary.json`.

## Avoiding 429 Storms

- No parallel Zep calls.
- Do not run multiple hydration commands at once.
- Keep `--interval-seconds 20` or slower.
- Obey any `Retry-After` value if Zep returns one. If it is greater than 20 seconds, use the larger value.
- Keep `--max-queries` small, preferably 6 to 8 per pass.
- Keep `--limit` small, preferably 6 to 8 facts per query.
- Do not use `--force-live` unless deliberately refreshing stale or bad cache entries after cooldown.
- Do not run all-node/all-edge graph panorama inside interactive Step 4.
- Do not run all-node/all-edge backfill as part of this enrichment plan.
- Resume from the existing cache path rather than deleting cache.
- Preserve pending/rate-limited provenance in evidence packets; do not hide it by overwriting diagnostics.

## Rerun Criteria

Rerun Step 4 only if enrichment creates materially better evidence in at least one of these ways:

- Company/executive: at least 4 new, non-duplicate, section-relevant Zep facts that name specific companies, executives, investor-relations framing, Apple WWDC, semiconductor AI infrastructure, or broker/fintech product narratives.
- Broker/platform: at least 4 new, non-duplicate, broker-specific facts that distinguish implementation, API, buying-power, settlement, or support-message differences across named platforms.
- External validation: a concrete validation mapping that adds real-world observable fields for at least 3 of these: quotes/volume, options IV/OI/spreads, broker rejection/buying-power evidence, Treasury/yield data, oil/geopolitical headlines, market-maker/dealer flow.
- Institutional/liquidity: at least 3 new facts that sharpen dealer, ETF desk, market-maker, quant, spread, gamma, or order-flow-toxicity behavior beyond the current local telemetry synthesis.
- AI/bot/developer: at least 3 new facts that distinguish actual API/framework/risk-control behavior from generic bot-copycat narrative.
- The new evidence would change a section's conclusion, confidence level, scenario weighting, validation checklist, or TradingAgents advisory caveat.

If those thresholds are met, rerun Step 4 only. Preserve `report_44fb26ddc574` as the accepted baseline.

## Waste Criteria

Do not rerun Step 4 if enrichment only produces:

- Duplicate facts already visible in `section_*_evidence.json`.
- Generic PDT, retail, bot, or macro text that does not name concrete entities, mechanisms, or validation fields.
- More cache hits with no new facts for the weak sections.
- More pending/rate-limited entries than useful facts.
- Only macro calendar facts already covered by the audit.
- Only external validation needs that must be answered by live market data outside Zep.
- No change to section conclusions, confidence, validation tasks, or TradingAgents advisory rules.

## Expected Output Paths If Step 4 Reruns

Baseline to preserve:

- `backend/uploads/reports/report_44fb26ddc574/full_report.md`
- `backend/uploads/reports/report_44fb26ddc574/step4_diagnostics.json`
- `backend/uploads/reports/report_44fb26ddc574/section_*_evidence.json`
- `backend/uploads/reports/report_44fb26ddc574/review_packet_report_44fb26ddc574.zip`

Hydration outputs before any rerun:

- `backend/uploads/reports/_zep_cache/mirofish_4a9df9ae8b184878/hydration_summary.json`
- `backend/uploads/reports/_zep_cache/mirofish_4a9df9ae8b184878/hydration_summary.md`
- cached graph.search result files under `backend/uploads/reports/_zep_cache/mirofish_4a9df9ae8b184878/`

Expected new Step 4 output pattern if a rerun is approved:

- `backend/uploads/reports/report_<new_report_id>/full_report.md`
- `backend/uploads/reports/report_<new_report_id>/step4_diagnostics.json`
- `backend/uploads/reports/report_<new_report_id>/section_01.md` through `section_20.md`
- `backend/uploads/reports/report_<new_report_id>/section_01_evidence.json` through `section_20_evidence.json`
- `backend/uploads/reports/report_<new_report_id>/section_01_evidence.md` through `section_20_evidence.md`
- `backend/uploads/reports/report_<new_report_id>/review_packet_report_<new_report_id>.zip`

## Stop Conditions

- Stop immediately if Zep returns repeated 429s after obeying cooldown.
- Stop if hydration summary shows mostly pending entries.
- Stop if company/executive enrichment does not produce material new facts.
- Stop before any Step 4 rerun and require explicit approval.
- Never convert this optional enrichment plan into simulation execution or trading authorization.
