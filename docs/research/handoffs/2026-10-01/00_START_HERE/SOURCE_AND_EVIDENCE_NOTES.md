# Source/evidence notes for the next agent

## Do not confuse these evidence levels

1. **Current snapshot** — what a source says now.
2. **Historical reconstruction** — a source retrieved now says a fact was effective historically.
3. **Historical as-known/versioned** — archived source versions show what the source published at historical times.
4. **TradingAgents prospective custody** — TradingAgents itself retained the source bytes before the decision cutoff.

The existing project often requires level 4 for admitted point-in-time decisions. New data collected in October 2026 cannot be backdated into old forecasts.

## Primary URLs repeatedly used in the research

### Alpaca

- Historical market data overview: https://docs.alpaca.markets/us/docs/about-market-data-api
- Market data FAQ / SIP distinctions: https://docs.alpaca.markets/us/docs/market-data-faq
- Assets: https://docs.alpaca.markets/us/reference/get-v2-assets-1
- Single asset: https://docs.alpaca.markets/us/reference/get-v2-assets-symbol_or_asset_id
- Historical single-symbol bars: https://docs.alpaca.markets/us/reference/stockbarsingle-1
- Multi-symbol bars: https://docs.alpaca.markets/us/reference/stockbars
- Corporate actions: https://docs.alpaca.markets/us/reference/corporateactions-1
- Corporate-action replay stream: https://docs.alpaca.markets/us/reference/subscribetocorporateactionseventssse
- Mandatory corporate actions / asset behavior: https://docs.alpaca.markets/us/docs/mandatory-corporate-actions
- Corporate-action SSE changelog: https://docs.alpaca.markets/us/changelog/2026-07-20-corporate-actions-b7b8e98

### SEC

- EDGAR API docs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- Developer access guidance: https://www.sec.gov/about/developer-resources

### OpenFIGI

- API: https://www.openfigi.com/api/documentation
- Overview: https://www.openfigi.com/about/overview

### Exchange/public data

- Nasdaq symbol directory definitions: https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs
- Nasdaq Daily List product: https://www.nasdaqtrader.com/Trader.aspx?id=DailyListpD
- 2026 Nasdaq rule filing / free event-data changes: https://www.federalregister.gov/documents/2026/08/07/2026-16097/self-regulatory-organizations-the-nasdaq-stock-market-llc-notice-of-filing-and-immediate
- NYSE corporate actions: https://www.nyse.com/trade/corporate-actions
- FINRA OTC Daily List: https://otce.finra.org/otce/dailyList
- Cboe listed symbols: https://www.cboe.com/us/equities/market_statistics/listed_symbols/

### Optional/free corroboration

- Alpha Vantage Listing Status: https://www.alphavantage.co/documentation/#listing-status

## Documentary real-world regression cases used in the research

- FB → META ticker change: https://investor.atmeta.com/investor-news/press-release-details/2022/Meta-Platforms-Inc.-to-Change-Ticker-Symbol-to-META-on-June-9/default.aspx
- META ticker reuse by Roundhill ETF / change to METV: https://www.sec.gov/Archives/edgar/data/1683471/000089418922000256/meta497etickerchange.htm
- Pioneer → ExxonMobil merger: https://www.sec.gov/Archives/edgar/data/1038357/000119312524130052/d803313d8k.htm
- Twitter cash acquisition: https://www.sec.gov/Archives/edgar/data/1418091/000119312522272772/d411753d8k.htm
- Palantir NYSE → Nasdaq transfer notice: https://www.miaxglobal.com/alert/2024/11/25/miax-exchange-group-options-markets-change-market-underlying-security-used
- Bed Bath & Beyond listed → OTC evidence: https://www.sec.gov/Archives/edgar/data/886158/000088615823000059/bbby-20230225.htm
- Xperi/Adeia separation: https://www.sec.gov/Archives/edgar/data/1803696/000095017024019362/adea-20231231.htm
- Alphabet GOOG/GOOGL share-class history: https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm
- Reddit IPO first trading date evidence: https://www.sec.gov/Archives/edgar/data/1713445/000171344525000018/R10.htm

## Paid sources researched only as completeness benchmarks

These are **not** recommended dependencies at present:

- Databento
- CRSP
- Sharadar
- Norgate
- QuantConnect
- Massive
- Tiingo
- Intrinio
- LSEG/Refinitiv
- FactSet
- Bloomberg
- ICE

See `02_RESEARCH/FREE_FIRST_SECURITY_MASTER_RESEARCH.md` for why each is not currently preferred.
