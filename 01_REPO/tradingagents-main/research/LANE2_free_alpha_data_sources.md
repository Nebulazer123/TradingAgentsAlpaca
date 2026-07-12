# Lane 2 Free Alpha Data Service Discovery

## Executive recommendation

After reading the provided context pack, the highest-confidence free upgrade path is not “more price data” and definitely not “blindly copy whatever a marketplace says is hot.” The best incremental stack is official SEC filing intelligence, a small official macro regime layer, ETF/sector context from issuer holdings, and a cache-first enrichment layer that can feed the existing overnight and hourly automations without blowing up runtime. The strongest free sources here are also the most boring: SEC, Fed, Treasury, BLS, BEA, EIA, Alpaca utilities, and issuer holdings pages. That is exactly why they are attractive. They are durable, legal, and testable. citeturn15view0turn34view2turn17search1turn18search11turn19search4

The main reason to prioritize SEC-first enrichment is speed and relevance. The SEC’s submissions API updates throughout the day in real time, with typical delays of less than a second for submissions and under a minute for XBRL APIs; Form 4 is generally due within two business days; and the SEC also provides free daily indexes, latest-filings views, RSS feeds, and XBRL company facts. That is a much better fit for finding under-reacted, filing-supported setups than adding yet another mediocre retail sentiment source. citeturn34view2turn35search6turn35search15turn22view2turn24search22

### Top free additions that are actually worth it

| Addition | Why it matters for this repo now | Recommended mode |
|---|---|---|
| SEC Form 4 + 8-K + submissions/daily-index scanner | Best free path to “temporarily mispriced, under-reacted, filing-supported” setups; official, fast, and legally clear. citeturn15view0turn34view2turn35search6turn35search15turn24search22 | **Immediate priority** |
| SEC companyfacts/companyconcept fundamentals layer | Free structured fundamentals from official XBRL APIs; ideal for quality filters, balance-sheet sanity checks, and post-filing deltas. citeturn34view0turn34view2turn15view0 | **Immediate priority** |
| FRED + ALFRED regime packet | Free macro series plus vintages for point-in-time regime features; useful for swing/multi-day risk-on/risk-off filters without paying for macro feeds. citeturn17search1turn17search5turn17search9turn17search0 | **Immediate priority** |
| ETF holdings + sector/industry relationship layer | Daily/near-daily holdings transparency from major issuers plus free SIC/Fama-French industry mapping gives better peer/sector context and pullback validation. citeturn31search6turn31search5turn31search12turn30search2turn30search7 | **High priority** |
| Alpaca utilities already in your stack | Free Basic plan gives IEX-only real-time equity data, market calendar, and corporate-actions endpoints. That is enough for execution context, but not enough to be your sole alpha feed. citeturn19search4turn19search13turn19search3turn19search2turn19search8 | **Use, but do not over-trust** |

### Top things not to waste time on

| Avoid | Why it is a bad tradeoff |
|---|---|
| Live-copying third-party strategies through Alpha Insider or any similar marketplace | AlphaInsider does support Alpaca paper/live linking and has an official API, but it requires handing third-party infrastructure broker/API credentials, and its own materials explicitly disclaim suitability/profitability. That is fine for observation or paper testing, not fine as a default production dependency. citeturn2view5turn6view0turn8view0turn1search21turn13search7 |
| Using 13F as a short-term entry trigger | Form 13F is filed up to 45 days after quarter-end; it is useful for slow sponsorship context, not for fresh trade timing. citeturn38search0turn38search2turn37search0 |
| Making Alpha Vantage the backbone of the system | The free tier is only 25 requests per day. Useful for a tiny supplemental feed, not for a multi-automation local bot with nightly and hourly tasks. citeturn20search10turn20search14turn30search0 |
| Building a production sentiment layer around Stocktwits or Google Trends | Stocktwits’ current developer docs point to sentiment/rankings access via enterprise contact, and Google’s Trends API is still limited to a small alpha-test group. citeturn23search0turn22view3 |
| Treating yfinance as a legally clean production-grade market-data source | The maintainer explicitly says yfinance is unofficial, not affiliated with Yahoo, and intended for research/educational purposes. Great for prototyping, weak as a legal/ops backbone. citeturn20search0 |

## Ranked free source and service table

The table below is ranked for this specific repo and this specific goal: improve stock-only, limit-order, long-only detection of under-reaction, filing support, macro context, and better pullback quality.

| Source or service | Category | Truly free? | API or key needed? | Legal or API clarity | Data provided | Best use in current system | Rate limits or constraints | Reliability | Implementation difficulty | Priority |
|---|---|---:|---|---|---|---|---|---|---|---|
| SEC EDGAR submissions + daily/full indexes + latest filings + RSS citeturn15view0turn35search15turn35search6turn22view2turn16search1 | Public filings | Yes | No key | Very clear; official public SEC access | Filing history, latest filings, RSS, daily index metadata | Watchlist event scanner for 8-K, 13D/13G, ownership filings, and per-ticker filing freshness | SEC asks you to stay under roughly 10 requests/sec and identify your client properly | Very high | Medium | **P1** |
| SEC XBRL APIs: companyfacts, companyconcept, frames citeturn34view0turn34view2turn15view0 | Fundamentals | Yes | No key | Very clear; official public SEC APIs | Structured facts from 10-K, 10-Q, and XBRL-enabled filings | Quality gates, leverage/profitability/liquidity features, post-filing change detection | Real-time-ish updates; no CORS; bulk ZIPs available nightly | Very high | Medium | **P1** |
| SEC Form 4 raw filings + insider data sets citeturn24search22turn36search0turn36search3turn36search7 | Insider data | Yes | No key | Very clear; official public SEC data | Ownership XML filings, flattened quarterly insider datasets | Insider-buy support layer; cluster-buy filters; research backfill | Raw filings are timely, but SEC’s flattened dataset is quarterly | Very high for raw filings; medium for flattened archive | Medium | **P1** |
| Alpaca Basic + calendar + corporate actions citeturn19search4turn19search13turn19search3turn19search2turn19search8 | Market utility data | Yes | Account/API keys | Clear official docs | IEX-only real-time equities on free plan, market calendar, corporate actions | Execution-day context, event-risk flags, trading-day alignment, splits/dividends sanity checks | Free real-time coverage is limited to IEX; not full-market SIP | High | Low | **P1** |
| FRED + ALFRED citeturn17search1turn17search5turn17search9turn17search0 | Macro regime | Yes | Free key | Clear official docs and terms | Economic time series plus vintages | Slow regime filters, recession/liquidity/inflation backdrop, point-in-time backtests | Key required; terms say service can change | Very high | Low | **P1** |
| ETF issuer holdings pages and files from State Street, iShares, Invesco citeturn31search6turn31search5turn31search9turn31search12turn30search9 | Sector and constituent context | Yes | Usually no key | Clear enough for normal use, but provider-specific and brittle | Fund holdings, weights, sector allocations | Sector-relative strength, “held by the same basket” peer features, rebalance awareness | No uniform API; formats differ by issuer and fund | High | Medium | **P1** |
| SEC Form 13F data sets + 13F section guidance citeturn37search0turn38search0turn37search8turn37search10 | Institutional holdings | Yes | No key | Clear official public data | Quarterly institutional holdings and 13(f) universe | Slow sponsorship context, accumulation proxies, “owned by smart money” filters | Quarterly and stale by design; 45-day lag | High for what it is | Medium | **P2** |
| BLS Public Data API citeturn29view0turn29view1 | Macro regime | Yes | V2 registration key recommended | Clear official docs | Employment, CPI and other labor stats | Macro calendar and labor/inflation regime features | One-day publication lag to API; series-ID friction; daily/query caps | High | Medium | **P2** |
| BEA + Treasury FiscalData + EIA + Fed calendars citeturn29view2turn18search11turn29view4turn18search6turn18search2turn29view7 | Macro regime and event calendars | Yes | BEA/EIA keys; Treasury/Fed no key | Clear official docs | GDP/income data, fiscal series, energy data, FOMC calendars and blackout windows | Regime overlays and macro-event risk flags | Mostly low-frequency; EIA/BEA require keys; not entry-timing alpha by themselves | High | Medium | **P2** |
| SEC SIC + Ken French industry assignments citeturn30search2turn30search3turn30search7 | Industry classification | Yes | No key | Clear official or academic sources | SIC codes and free industry portfolio mappings | Replace proprietary sector taxonomies with free industry buckets | Coarser than GICS; some mapping work needed | High | Low | **P2** |
| Reddit Data API citeturn33search0turn22view0turn33search9 | Sentiment | Yes, for eligible free use | OAuth | Legally clearer than scraping, but more restrictive than people assume | Public posts, comments, subreddit streams | Only as a narrow watchlist anomaly flag, not as core alpha | 100 QPM per OAuth client in free access docs; commercial and higher-volume uses need separate agreement | Medium | Medium | **P3** |
| Alpha Vantage free tier citeturn20search10turn20search14turn30search0turn32search13 | Market and event data | Yes | Free key | Clear official docs | Prices, fundamentals, technical indicators, earnings calendar | Tiny supplemental source for earnings/event annotation on a short watchlist | 25 requests/day on standard free service | Medium | Low | **P3** |
| Nasdaq Data Link free datasets citeturn32search0turn32search4turn32search11 | Mixed financial datasets | Mixed free and premium | Free account/API key | Official docs are clear that some data is free and some is premium | Free and premium tables/series from many publishers | Selective add-on datasets only, if a specific free dataset is valuable | Key required; dataset-specific licensing and access rules vary | Medium | Medium | **P3** |
| yfinance citeturn20search0turn20search8 | Market data helper | Yes | No key | Unofficial and weaker legally | Easy historical prices and convenience helpers | Prototype-only fallback or local research notebook utility | Subject to breakage/TOS ambiguity | Medium | Low | **P4** |
| Stooq citeturn20search1turn20search5 | Historical market data | Yes | No key, but friction | Automation clarity is weak | Free historical flat files | Emergency historical backfill only | CAPTCHA/manual flow makes reliable automation poor | Medium | Medium | **P4** |
| Stocktwits developer access citeturn23search0turn21search21 | Sentiment | Not meaningfully free for your use case | Unclear/public web and enterprise channels | Current public docs point sentiment/rankings users to enterprise contact | Sentiment and ranking products | Not worth building around right now | Access path appears sales-led for the useful endpoints | Low-to-medium | Medium | **Reject as core feed** |

## Alpha Insider and strategy-marketplace assessment

### What is real and potentially useful

AlphaInsider is not vaporware. It has an official API, documented endpoints for strategies, trades, bots, webhooks, and websockets, and documented account-tier limits. It also publishes official instructions for connecting Alpaca paper or live accounts by pasting Alpaca API keys, and its own blog materials show that a strategy can be public, private, or paid. Its public-facing materials also indicate that users can track performance before turning on automation, and that followers of a public strategy can see positions and posts in real time. citeturn6view0turn8view0turn7view0turn2view5turn41search0turn10search0

That means there is genuine product value in three places. First, it is a real signal marketplace, not just screenshots. Second, it is a real no-code execution layer for people willing to trust a third party with broker credentials. Third, its marketplace UX is worth studying as a product pattern: public strategy pages, performance summaries, follower/subscription concepts, and optional automation are all things your local repo could mimic internally without inheriting the same broker-key and survivorship risks. citeturn10search0turn41search0turn13search9

### What looks like marketing fluff or at least needs suspicion

The same official ecosystem that proves AlphaInsider is real also gives reasons to distrust it as an external alpha source. Its materials lean heavily on no-code AI workflows, strategy marketplaces, copying public figures, and public performance/ranking narratives. Meanwhile, AlphaInsider’s own public disclaimer says it makes no representation that strategies are suitable or profitable, and its bot-risk materials explicitly frame the product around automating third-party strategies. That is exactly the environment where survivorship bias, strategy churn, backtest theater, and “looks great until slippage or crowding shows up” are most likely. citeturn1search21turn13search7turn41search0turn13search9

There is also a practical inconsistency problem. Public marketing and blog posts say the first automation or first broker connection is free, and the pricing snippet shows a free tier with one broker connection. But the API limits page shows a “Standard” account with zero bots. I could not fully reconcile that from public sources. That does not mean the platform is dishonest; it does mean you should assume the free-plan surface can drift or be ambiguously documented, which is bad for unattended production dependencies. citeturn42search0turn41search0turn3search2turn7view0

### Can signals be observed without giving live broker keys

Yes, at least partially. AlphaInsider’s own materials say you can track performance before enabling automation and that public strategy followers can see positions and posts in real time. The official API also exposes strategy-discovery and performance endpoints. What I did **not** verify cleanly from public sources is a fully anonymous, stable, legally redistributable export path for marketplace signals at scale. There is an official API, but it is token-based, and I did not find a clear public-data license for bulk external reuse. citeturn41search0turn6view0turn8view0turn10search0

### Similar systems and whether they matter here

| System | What is real | Fit for this repo |
|---|---|---|
| AlphaInsider citeturn2view5turn6view0turn8view0turn41search0 | Official API, public/private/paid strategies, Alpaca paper/live support, broker automation | **Observe only or paper only**; use as UX inspiration |
| eToro CopyTrader citeturn42search1turn42search13turn42search21 | Large social-copy ecosystem; CopyTrader itself has no extra fee in eToro’s guide | Wrong shape for a local Alpaca-based repo; **inspiration only** |
| Collective2 citeturn42search2turn42search10turn42search18 | Real strategy marketplace with brokerage autotrade | Not free in practice; strategy fees plus autotrade fees; **reject** |
| QuantConnect Alpha Streams citeturn42search3turn42search7 | Real quant ecosystem and open-source LEAN engine | Better as research inspiration than external signal subscription for this repo; **not a Lane 2 execution source** |

### Recommendation

For this project, AlphaInsider should be treated as **observe-only or paper-only**. It is useful as a reconnaissance target and as inspiration for an internal strategy-allocation layer. It is a bad tradeoff to make it a live-production dependency by default, because doing so means delegating execution authority to a third-party marketplace stack whose economics and free-plan details can change, and whose marketplace incentives are not aligned with robust, uncrowded, stock-only alpha. citeturn2view5turn7view0turn1search21turn13search7turn41search0

That internal strategy-allocation layer **is** worth building eventually. Not a clone of AlphaInsider’s social marketplace nonsense; a local allocator that compares your own strategies plus new filing/macro/context signals, scores them by regime fit and evidence quality, and allocates paper capital across them. That is the smart version.

## Best free signal families to add

The system’s stated weakness is that it already finds visible strength but misses temporarily mispriced, under-reacted, insider-supported, filing-supported, and macro-supported setups. The best signal families below are ranked for fixing that exact gap.

| Signal family | Edge hypothesis | Data needed | Frequency | Lag or staleness | Robustness | Current-system fit |
|---|---|---|---|---|---|---|
| Public insider and Form 4 support | Insider buying is not magic, but fresh insider purchases can be useful when they are large, clustered, and plausibly discretionary. The practical edge is not “insider buys = buy”; it is “recent insider accumulation strengthens a separate setup you already like,” especially because Form 4 is filed quickly while the quarterly insider flat files are better for backtests than live discovery. This is an inference from the official Form 4 timing and dataset structure. citeturn24search22turn36search0turn36search3 | Raw Form 4 ownership filings, issuer-insider-role fields, transaction-type parser, historical baseline per ticker | Hourly/nightly | Raw filings: low lag; SEC flat datasets: quarterly and stale | Medium to high if heavily filtered; poor if naively pooled | **Excellent** |
| 13F and institutional support | 13F is too stale for timing but still useful as a slow sponsorship prior: “who owns this name,” “is ownership broadening,” “is a new institution showing up,” or “does this stock sit in a bucket institutions keep allocating to.” Use it as context, never as a trigger. citeturn37search0turn38search0turn37search8 | 13F flat files, manager history, security map, lag-aware features | Monthly/quarterly refresh | Very stale by design; up to 45 days after quarter-end | Medium if used only as background support | **Good** |
| 8-K and filing-event support | Many under-reactions start in filings instead of charts. A clean free edge is to detect fresh 8-Ks and classify them into materially good, bad, or ambiguous corporate events, then only act when price action and liquidity confirm. SEC latest-filings tools, RSS, and filing APIs make this practical for a watchlist. citeturn35search6turn35search15turn22view2turn24search17 | EDGAR latest filings, submissions history, 8-K text/exhibits, simple item/event classifier | Hourly/nightly | Very low if you scan the official feed | Medium to high if event taxonomy is sane | **Excellent** |
| Macro regime support | Macro is usually useless as stock picking and useful as a regime gate. A compact official stack from FRED/ALFRED, BLS, BEA, Treasury, EIA, and Fed calendars can tell you whether to lean into beta, hide in quality, or avoid over-interpreting single-name breakouts into bad tape. citeturn17search1turn17search9turn29view0turn29view2turn18search11turn18search2 | Small set of monthly/weekly macro series plus FOMC/calendar flags | Daily/nightly | Mostly slow-moving; event flags are fresh | High if kept simple; low if overfit into a giant macro dashboard | **Very good** |
| Free news and sentiment support | The only free sentiment worth trusting here is structured sentiment from filings and a narrow social-anomaly layer. SEC RSS is free and official. Reddit’s API is usable for small-scale watchlist anomaly detection, but its terms and free-rate limits make it a support feature, not a backbone. Stocktwits and Google Trends are poor current tradeoffs. citeturn22view2turn33search0turn22view0turn23search0turn22view3 | SEC RSS, watchlist Reddit pulls, maybe company IR feeds where easy | Hourly/nightly | Mixed; social can be fast but noisy | Low to medium; use as a veto/attention feature, not alpha engine | **Moderate** |
| ETF and sector relationship support | Under-reaction often becomes clearer when you know the basket. If a stock is pulling back but its sector ETF, top thematic ETF, and close holdings cohort are still healthy, the setup quality improves. Free daily issuer holdings and free industry mappings make this feasible without GICS licenses. citeturn31search6turn31search9turn31search12turn30search2turn30search7 | ETF holdings files/pages, free sector/industry map, relative-strength features | Daily/nightly | Low to moderate depending on issuer update cadence | High if kept simple | **Very good** |
| Earnings and calendar support | Free calendars are best used as risk controls. Alpha Vantage offers a free earnings-calendar endpoint, but the free request budget is tiny, so use it to annotate a short watchlist, not the whole universe. Combine with filing scans for post-earnings under-reaction rather than relying on the calendar itself for alpha. citeturn30search0turn20search10 | Earnings calendar, recent results/filing timestamps, post-event drift features | Daily/nightly | Calendar is forward-looking but limited; confirmation comes after reports | Medium as risk management, low as standalone alpha | **Good** |

The filters I would add first are not exotic. For insider support, I would prioritize **recent discretionary buys, multiple insiders in a short window, larger dollar commitment, and a first meaningful buy after a long gap**, while downweighting routine grants, automatic plan noise, and mechanically reported transactions. For 13F, I would prioritize **new or expanding sponsorship over multiple quarters**, not absolute popularity. For 8-K, I would prioritize **fresh material events with readable business impact**, not every filing. Those are recommendations rather than SEC rules, but they map cleanly onto the filing structures the SEC already exposes. citeturn36search0turn37search0turn35search6

## Integration map and libraries for Codex

### Likely files and modules to inspect

Because another lane is handling broader architecture and methodology, the right Lane 2 change is a **thin enrichment layer**, not a repo redesign. Based on your system description, the likely inspection targets are the existing market-data adapters, ticker packet builders, overnight planner graph, strategy-scoring modules for `current-aggressive`, `pullback-support`, and `catalyst-relative-strength`, the CLI task entrypoints that feed hourly and overnight jobs, the automation wrappers for supervisors/tournaments/reports, and the local cache/storage helpers.

The design rule should be simple: **new sources must enrich existing packets, never become mandatory runtime blockers**. If a source fails, the packet should degrade gracefully and the current automations should still run.

### New adapters to add

I would add adapters in this order:

| Adapter | Purpose | Runtime posture |
|---|---|---|
| `sec_filings_adapter` | Recent 8-K / Form 4 / 13D-13G / submissions scan for watchlist names | Cached, incremental, non-blocking |
| `sec_fundamentals_adapter` | companyfacts/companyconcept snapshot and simple deltas | Nightly cache refresh, reused hourly |
| `macro_regime_adapter` | Compact FRED/BLS/BEA/Treasury/EIA/Fed packet | Daily refresh only |
| `etf_sector_adapter` | ETF membership, top-holdings overlap, sector-relative context | Daily refresh only |
| `13f_support_adapter` | Slow sponsorship/support fields | Monthly or quarterly refresh |
| `social_anomaly_adapter` | Reddit-only watchlist anomaly flag | Paper-only or low-weight support feature |

### Suggested output packet shape

Use a normalized enrichment packet that can be merged into the current per-ticker object without forcing immediate downstream rewrites:

```json
{
  "ticker": "XYZ",
  "asof_utc": "2026-06-01T05:00:00Z",
  "sec": {
    "recent_filings": [
      {
        "form": "8-K",
        "filed_at": "2026-05-31T20:12:00Z",
        "event_score": 0.72,
        "event_label": "material_positive",
        "summary": "..."
      }
    ],
    "insider": {
      "recent_buy_count": 2,
      "recent_sell_count": 0,
      "recent_net_buy_value_usd": 850000,
      "cluster_buy_flag": true,
      "support_score": 0.81
    },
    "fundamentals": {
      "profitability_ok": true,
      "balance_sheet_ok": true,
      "latest_quarter_delta_score": 0.34
    },
    "ownership": {
      "institutional_support_score": 0.44,
      "last_13f_quarter": "2026Q1"
    }
  },
  "macro": {
    "regime_label": "neutral_to_risk_on",
    "risk_score": 0.38,
    "fomc_window_flag": false
  },
  "peer_context": {
    "sector_bucket": "Semiconductors",
    "primary_etfs": ["SMH", "SOXX"],
    "etf_overlap_score": 0.67,
    "sector_relative_strength_score": 0.58
  },
  "event_risk": {
    "earnings_within_days": 4,
    "corp_action_flag": false
  }
}
```

### How to avoid breaking current hourly and overnight automations

The practical rule is to keep all new adapters **cache-first, universe-reduced, and budget-aware**. Do not scan the whole market every hour. For overnight, scan the planned universe plus a small expansion set. For hourly, only refresh names already on the active watchlist, in open positions, or newly surfaced by the existing pipeline.

The second rule is to separate **research backfill** from **live packet refresh**. SEC flat archives, 13F backfills, and old ETF holdings history should be populated by separate maintenance tasks, not by the main overnight graph.

The third rule is to gate every adapter behind a feature flag and timeout budget. If the SEC layer or macro layer times out, the packet should simply carry null/default fields and the current strategy stack should continue.

### Free and open-source libraries Codex should inspect

These are the best fit for a lightweight, Windows-friendly local stack.

| Library | Best use | Why it fits |
|---|---|---|
| `edgartools` citeturn25search1turn25search6turn25search17 | SEC parsing and filing abstraction | Broad filing coverage, structured SEC access, recent active releases, free/open-source |
| `sec-edgar-downloader` citeturn25search0turn25search13 | Lightweight filing downloads/backfills | Simple downloader, recent Python support, easy fallback |
| `pyfredapi` or `fredapi` citeturn25search3turn25search12turn25search2 | FRED/ALFRED access | Good FRED coverage; `fredapi` specifically highlights ALFRED point-in-time parsing |
| `requests-cache` citeturn26search2turn26search17 | HTTP caching | Exactly what this lane needs: keep official free APIs cheap and stable |
| `polars` citeturn26search5turn26search10 | Fast feature engineering | Very fast, Arrow-native, streaming-friendly, actively released |
| `duckdb` citeturn26search11turn26search1turn26search6 | Lightweight local analytical store | In-process, portable, good for local caches and research joins |
| `backtesting.py` citeturn26search3turn26search13 | Quick event-study/backtest harnesses | Simple, practical, lower ceremony than heavier frameworks |
| `ta` citeturn27search0turn27search15 | Technical feature generation | Pure Python/Pandas, enough indicators without TA-Lib pain |
| `empyrical-reloaded` citeturn27search2 | Return/risk metrics | Easy performance-metric layer for paper tournaments and signal tests |
| `PyPortfolioOpt` citeturn26search4turn26search9 | Lightweight risk/weight experiments | Useful if you later add internal strategy-allocation logic |

For second-tier tooling, I would keep an eye on `arch` for volatility/event-study work, `statsmodels` for regression/event-study validation, `scikit-learn`’s `TimeSeriesSplit` for leakage-safe validation, and `Optuna` for bounded hyperparameter search. Those are all real tools, but they should come **after** the filing/macro/ETF data plumbing exists. citeturn28search0turn28search13turn28search2turn28search11

### What should remain paper-only

Paper-only for now:

- Any live external strategy-copying through AlphaInsider or similar marketplaces.
- Any social-sentiment feature from Reddit until it proves incremental value beyond filing/event context.
- Any strategy-allocation layer that dynamically reallocates real capital between internal strategies based on newly added signals.
- Any use of unofficial feeds as a trading-critical dependency.

That is not caution for caution’s sake. It is avoiding dumb counterparty and data-quality risk.

## Batch roadmap and first Codex prompt

### Batch implementation roadmap

| Batch | Goal | Likely files touched | Runtime impact | Memory impact | Failure risks | Tests | Output packet or report |
|---|---|---|---|---|---|---|---|
| SEC filing foundation | Add official SEC client with rate limiting, user-agent, cache, recent 8-K/Form 4 scan for selected tickers | Data adapters, packet builder, config/flags, CLI task entrypoint, tests | Low to medium if watchlist-only | Low | SEC throttling, bad ticker-CIK mapping, XML edge cases | Mocked SEC responses; integration smoke test on a 5-ticker set | `sec.recent_filings`, `sec.insider` packet |
| SEC fundamentals layer | Add companyfacts/companyconcept snapshot and simple quality deltas | Same plus scoring helpers | Low after cache | Low to medium | XBRL tag normalization, sparse issuers | Unit tests on known issuers with mocked JSON | `sec.fundamentals` packet |
| ETF/sector context | Add ETF holding map and sector-relative features from free issuer pages/files | Adapter, cache, packet builder | Low daily refresh | Low | Provider format drift, missing funds | Parser tests using frozen sample files | `peer_context` packet |
| Macro regime mini-pack | Add compact FRED/BLS/BEA/Treasury/EIA/Fed context | Adapter, cache, nightly refresh hooks | Very low | Low | Series changes, key misconfig | Mocked API tests, stale-cache fallback test | `macro` packet |
| 13F support layer | Add slow institutional sponsorship features | Backfill task, local analytical store, packet builder | Very low live; heavier backfill | Medium during backfill | Security mapping errors, stale assumptions | Historical reconciliation tests | `sec.ownership` packet |
| Sentiment anomaly layer | Add optional Reddit watchlist anomaly flag | Separate optional adapter and config | Low if watchlist-only | Low | Terms/rate limits/noise | Disabled-by-default smoke tests | `sentiment` packet |
| Strategy allocation paper layer | Add internal allocator that scores evidence across current strategies | Scoring/ranking/report outputs only | Medium | Low to medium | Overfitting; changing current behavior too early | Paper-only tournament tests | Allocation report only |

### First Codex prompt for Lane 2 Batch 1

```text
Inspect the current TradingAgents repo and identify the existing data-adapter, packet-building, strategy-scoring, CLI entrypoint, and automation hook locations that are safest to extend without changing current behavior.

Implement the smallest useful Lane 2 foundation using ONLY official free SEC sources:
1) add a cache-first SEC client with proper User-Agent handling and conservative rate limiting,
2) support ticker->CIK resolution and watchlist scans for recent 8-K and Form 4 activity using official SEC submissions/latest-index-compatible data,
3) normalize results into a new optional per-ticker enrichment packet (recent filings summary + insider support summary),
4) wire the packet into the overnight planner path as a non-blocking enrichment behind a feature flag,
5) keep hourly/overnight automations working even if SEC is unavailable,
6) add unit tests with mocked SEC responses plus one small smoke test,
7) run tests and produce a concise handoff report listing touched files, feature flags, packet schema, runtime impact, known limitations, and the best next Batch 2 follow-up.
```

### Open questions and limitations

A few things remain genuinely incomplete from public sources and should be treated as such.

AlphaInsider’s public materials are internally inconsistent enough that I would not assume I fully pinned down the exact free-tier limits for broker automation from public evidence alone. The existence of a free tier and “first automation free” marketing is clear, but its exact current boundary conditions are not. citeturn42search0turn41search0turn3search2turn7view0

I also did not find a clean public-data license for bulk redistribution of AlphaInsider marketplace signals. The platform has an official API and clear tokenized access, but that is not the same thing as a safe right to repackage their marketplace data into your own production system. citeturn6view0turn8view0turn10search0

Finally, some free sources are technically usable but operationally bad. Stooq’s CAPTCHA/manual flow, yfinance’s unofficial status, and sentiment feeds with restrictive or unclear access are why this report keeps pushing you back toward official filing and macro sources. The boring stuff is better. Annoying, but true. citeturn20search1turn20search5turn20search0turn23search0turn22view3