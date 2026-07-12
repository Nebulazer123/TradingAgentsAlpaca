# GOOGL Staged-Buy Evidence Packet

Date prepared: 2026-05-25  
Workspace: `C:\Users\Corbin\Documents\Coding projects\TradingAgents-main`  
Current working conclusion: GOOGL is the best current single-stock staged-buy candidate from the reviewed large-cap AI/growth set, using a Fidelity shares-only order plan capped at about $1,000.

This packet is a research handoff. It captures the evidence and leads that persuaded the current conclusion, plus the items that should be verified or expanded by deeper web research.

## 1. Decision Snapshot

Current candidate set reviewed:

- NVDA
- MSFT
- GOOGL
- AMZN
- META
- AVGO
- AMD
- Additional screen context: TSM, ORCL, CRWD, PLTR, SCHG, QQQ, SPY, SMH

Current conclusion:

- Primary staged-buy candidate: GOOGL
- Runner-up: NVDA
- Strong but less clean: AMZN, MSFT
- Watch/wait: AVGO, META
- Avoid chasing now: AMD

Current execution constraint:

- Broker: Fidelity
- Budget for this idea: $1,000 maximum, whole shares only
- Last reviewed GOOGL price: about $382.97 from the latest regular close available in the local market-data pull, dated 2026-05-22
- Whole-share implication: 2 shares of GOOGL is about $766 before any price movement; 3 shares would exceed the $1,000 cap

Working order plan:

1. Buy 1 share GOOGL with a regular-session day limit around $386 after the Tuesday open settles.
2. Buy 1 additional share GOOGL with a GTC limit around $370-$372 for a pullback.
3. Do not force the full $1,000 budget if the setup only justifies 1-2 shares.
4. Do not use a market order, on-open order, stop order, or trailing stop for the entry.

## 2. TradingAgents Methodology Packet

The TradingAgents repo uses a graph of roles rather than one monolithic analyst. The active flow verified from the repo is:

`Market Analyst -> Sentiment Analyst -> News Analyst -> Fundamentals Analyst -> Bull/Bear debate -> Research Manager -> Trader -> Aggressive/Conservative/Neutral risk debate -> Portfolio Manager -> parsed signal`

Local repo evidence:

- `tradingagents/graph/setup.py` wires the graph roles and order.
- `tradingagents/graph/analyst_execution.py` maps the saved `social` wire key to the active user-facing `Sentiment Analyst`.
- `tradingagents/agents/analysts/social_media_analyst.py` is deprecated and only aliases the active sentiment analyst.
- `tradingagents/agents/schemas.py` defines structured outputs for Research Manager, Trader, and Portfolio Manager.
- `tradingagents/agents/managers/research_manager.py` uses the 5-tier scale: Buy, Overweight, Hold, Underweight, Sell.
- `tradingagents/agents/trader/trader.py` converts the research plan into Buy/Hold/Sell plus entry, stop, and sizing.
- `tradingagents/agents/managers/portfolio_manager.py` synthesizes the risk debate into the final 5-tier position decision.

How the method affected this decision:

- Market Analyst role favored GOOGL over AMD because GOOGL had strong trend without extreme RSI/overextension.
- Sentiment Analyst role treated very hot NVDA/AMD sentiment as both confirmation and crowding risk.
- News Analyst role treated GOOGL regulatory headlines as real but not thesis-breaking; AVGO had near-term event risk.
- Fundamentals Analyst role found GOOGL's cloud growth and margins strong enough to compete with NVDA's superior AI infrastructure growth.
- Bull Researcher role liked GOOGL's combination of AI monetization, Cloud growth, Search strength, and less-exhausted entry.
- Bear Researcher role flagged regulatory risk, capex, and the fact that GOOGL is not immune to mega-cap AI drawdowns.
- Research Manager and Portfolio Manager roles preferred GOOGL on risk-adjusted entry quality, not because NVDA's fundamentals are weaker.
- Trader role translated the conclusion into staged limit orders rather than an open-price chase.

## 3. Fidelity Order Mechanics Packet

Primary broker-source evidence:

- Fidelity order-type FAQ: https://www.fidelity.com/trading/faqs-order-types
- Fidelity placing-orders FAQ: https://www.fidelity.com/trading/faqs-placing-orders
- Fidelity trading-stocks help: https://www.fidelity.com/webcontent/ap002390-mlo-content/19.07/help/learn_trading_stocks.shtml
- Fidelity order types and conditions help: https://www.fidelity.com/webcontent/ap002390-mlo-content/19.09/help/learn_order_types_conditions.shtml
- Fidelity stop loss / stop limit learning page: https://www.fidelity.com/learning-center/trading-investing/trading/stop-loss-video

Broker facts that affected the plan:

- Fidelity extended-hours stock trading is available premarket and after-hours, but the useful rule is that Fidelity accepts limit orders only in extended-hours sessions.
- Fidelity says all other order types are ineligible for extended-hours trading.
- Fidelity says GTC orders are not available for extended-hours trading.
- Fidelity says premarket orders not filled by 9:28 a.m. ET are canceled.
- Fidelity says after-hours orders not filled by 8:00 p.m. ET are canceled.
- Fidelity says conditions such as All or None are not available on extended-hours trades.
- Fidelity's order-type FAQ says trailing stop loss triggers a market order once triggered.
- Fidelity's order-type FAQ says trailing stop limit triggers a limit order once triggered.
- Fidelity says trailing stop orders may be based on last round-lot trade, bid, or ask.
- Fidelity says trailing stop orders may be Day or GTC.
- Fidelity says Fidelity.com GTC orders expire after 180 days.
- Fidelity's stop-order page says trailing stops are monitored during regular market hours, 9:30 a.m. to 4:00 p.m. ET.

Order-type conclusions for this specific entry:

| Order type                  | Entry use here | Why                                                                                              |
| --------------------------- | --------------:| ------------------------------------------------------------------------------------------------ |
| Market                      | No             | Too much open-price/slippage risk, especially after holiday/overnight headlines.                 |
| Limit                       | Yes            | Sets maximum acceptable buy price and fits both regular session and extended-hours restrictions. |
| Stop loss                   | No             | Better as a later exit tool. On trigger, becomes a market order.                                 |
| Stop limit                  | No for entry   | Better as a later exit tool if a minimum sale price matters, but may not fill.                   |
| Trailing stop loss dollar   | No for entry   | Exit/risk-management tool after owning shares; triggers market order.                            |
| Trailing stop loss percent  | No for entry   | Same as above; possible later protective sell tool.                                              |
| Trailing stop limit dollar  | No for entry   | Exit tool; protects limit price but can miss execution.                                          |
| Trailing stop limit percent | No for entry   | Same as above; more complex and not needed for a 1-2 share starter.                              |

Time-in-force conclusions:

- Day: useful for the first starter limit order.
- GTC: useful for the second regular-session pullback limit order.
- Fill or Kill: not useful for 1-2 shares; unnecessary all-or-nothing execution constraint.
- Immediate or Cancel: not useful; partial-fill logic does not matter much for 1 share.
- On the Open: rejected because the plan specifically avoids taking the opening print.
- All or None: rejected because the plan uses 1-share tickets and extended-hours conditions are restricted.

## 4. Market Calendar Packet

Source:

- NYSE market hours and calendars: https://www.nyse.com/markets/hours-calendars

Facts that affected the plan:

- Monday, 2026-05-25 is Memorial Day.
- U.S. stock markets are closed for the holiday.
- The next regular session is Tuesday, 2026-05-26.

Decision effect:

- Avoid placing a market order for the next open.
- Use limit orders and reassess if Tuesday premarket produces a large gap or thesis-changing news.

## 5. Technical / Price Action Packet

Source used:

- Local yfinance data pull run from this workspace on 2026-05-25.
- Latest regular-session close in that pull: 2026-05-22.

Snapshot:

| Symbol | Close  | Day % | 5d %  | 1m %  | 3m %   | 6m %   | 1y drawdown % | vs 50dma % | vs 200dma % | RSI14 |
| ------ | ------:| -----:| -----:| -----:| ------:| ------:| -------------:| ----------:| -----------:| -----:|
| NVDA   | 215.33 | -1.90 | -3.14 | 3.39  | 11.66  | 19.20  | -8.66         | 9.41       | 15.13       | 62.5  |
| MSFT   | 418.57 | -0.12 | -1.17 | -1.42 | 7.60   | -12.51 | -22.78        | 4.53       | -9.09       | 54.3  |
| GOOGL  | 382.97 | -1.21 | -3.52 | 11.20 | 23.18  | 32.31  | -4.88         | 12.26      | 29.30       | 49.8  |
| AMZN   | 266.32 | -0.80 | 0.55  | 0.88  | 27.69  | 22.65  | -3.15         | 10.08      | 15.51       | 43.3  |
| META   | 610.26 | 0.47  | -0.16 | -9.60 | -4.54  | 3.58   | -22.75        | -1.22      | -8.84       | 49.9  |
| AVGO   | 414.14 | -0.10 | -1.56 | -2.04 | 27.24  | 19.41  | -5.83         | 9.84       | 18.38       | 49.0  |
| AMD    | 467.51 | 3.99  | 11.05 | 34.42 | 118.63 | 126.92 | 0.00          | 54.20      | 102.49      | 75.2  |
| TSM    | 404.52 | -0.65 | 2.16  | 0.51  | 4.87   | 45.77  | -3.57         | 8.42       | 27.27       | 51.2  |
| ORCL   | 192.08 | 1.22  | 2.93  | 10.85 | 31.44  | -8.83  | -41.50        | 14.87      | -7.64       | 60.1  |
| CRWD   | 663.46 | 2.35  | 7.21  | 48.05 | 89.42  | 32.35  | 0.00          | 43.35      | 42.62       | 94.4  |
| PLTR   | 136.88 | -0.39 | 1.29  | -4.34 | 6.24   | -12.11 | -33.93        | -4.04      | -15.84      | 35.7  |
| SCHG   | 34.37  | 0.20  | 0.53  | 4.40  | 11.59  | 10.27  | -0.92         | 8.13       | 8.03        | 71.3  |
| QQQ    | 717.54 | 0.42  | 1.65  | 8.08  | 18.04  | 22.52  | -0.31         | 11.75      | 16.74       | 73.5  |
| SPY    | 745.64 | 0.39  | 0.95  | 4.44  | 8.48   | 14.27  | -0.34         | 7.03       | 9.84        | 71.8  |
| SMH    | 576.32 | 1.49  | 5.52  | 13.80 | 37.49  | 77.27  | -0.35         | 23.08      | 50.61       | 68.5  |

What persuaded the technical decision:

- GOOGL had strong 1m/3m/6m trend, small drawdown, and positive 50/200-day positioning.
- GOOGL RSI14 was about 49.8, making it less overheated than QQQ/SPY/SCHG/AMD/CRWD.
- NVDA had strong trend but RSI was warmer at 62.5 and sentiment/crowding were higher.
- AMD had extraordinary momentum but extreme extension: +34.42% in 1 month, +118.63% in 3 months, +126.92% in 6 months, +54.20% above 50dma, +102.49% above 200dma, RSI14 75.2.
- CRWD was even more technically overheated by RSI at 94.4 and was not chosen.

Research follow-up:

- Refresh these technicals before entry because the table used 2026-05-22 close.
- Verify premarket gap on Tuesday, 2026-05-26.
- Pull current 20/50/100/200-day moving averages, ATR, volume, and support/resistance for GOOGL and NVDA.
- Compare GOOGL's pullback zones against ATR, not only a simple 3-5% rule.

## 6. GOOGL / Alphabet Evidence Packet

Primary sources:

- Alphabet Q1 2026 earnings release PDF: https://s206.q4cdn.com/479360582/files/doc_financials/2026/q1/2026q1-alphabet-earnings-release.pdf
- Alphabet SEC earnings exhibit: https://www.sec.gov/Archives/edgar/data/1652044/000165204426000043/googexhibit991q12026.htm

Evidence gathered:

- Alphabet Q1 2026 revenue was about $109.896 billion.
- Google Cloud revenue was about $20.028 billion, up about 63% year over year.
- Consolidated operating margin was about 36.1%.
- Search revenue growth was cited as strong by the subagent packet, with a 19% figure that should be rechecked against the official release.
- GOOGL had an RSI14 near 49.8 in the local technical pull.
- GOOGL had strong 1m/3m/6m price momentum without AMD-style overextension.

What this persuaded:

- GOOGL became the primary pick because it combined growth, margin quality, AI/cloud exposure, and a cleaner entry profile.
- It beat NVDA on risk-adjusted entry, not on pure AI earnings power.
- It beat MSFT because MSFT's longer technical setup was weaker in the local pull.
- It beat AMZN because AMZN had capex/valuation questions and a less direct clean entry.
- It beat META because META's capex/regulatory/profile concerns were larger relative to the setup.
- It beat AMD because AMD was technically too stretched.

Risks/leads to research deeper:

- EU/regulatory headlines and likely fine size/status.
- Whether Cloud growth is sustainable or pulled forward.
- AI search monetization evidence: revenue impact, cost impact, click/ad changes.
- Capex trajectory and whether incremental AI spend is earning returns.
- Current valuation versus forward EPS/free cash flow after the Q1 beat.
- Analyst estimate revisions after the Q1 release.
- Any antitrust remedies that could impair Search distribution, ads, Chrome, Android, or AI integration.

## 7. NVDA Evidence Packet

Primary source:

- NVIDIA Q1 FY2027 results: https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-First-Quarter-Fiscal-2027/default.aspx

Evidence gathered:

- NVIDIA Q1 FY2027 revenue was $81.6 billion, up 85% year over year.
- Data Center revenue was $75.2 billion, up 92% year over year.
- NVIDIA guided Q2 FY2027 revenue to $91.0 billion, plus or minus 2%.
- The release states the outlook assumes no Data Center compute revenue from China.
- Local technical pull: NVDA close $215.33, RSI14 62.5, +9.41% above 50dma, +15.13% above 200dma, -8.66% from 1-year high.

What this persuaded:

- NVDA remained the strongest fundamental AI name.
- NVDA stayed runner-up rather than final pick because the panel preferred GOOGL's cleaner risk-adjusted entry.
- If the goal were pure AI earnings power and not a fresh whole-share entry under $1,000, NVDA could have won.

Risks/leads to research deeper:

- China restrictions and whether the "no China Data Center compute revenue" assumption creates upside or downside.
- Customer concentration and hyperscaler capex dependency.
- Blackwell/Rubin supply and gross margin trajectory.
- Whether the $91B Q2 guide was already fully priced by the stock.
- Any post-earnings analyst revisions or target changes after May 20, 2026.
- Compare NVDA forward valuation to GOOGL using current consensus EPS and free cash flow.

## 8. MSFT Evidence Packet

Primary source:

- Microsoft FY2026 Q3 earnings: https://www.microsoft.com/en-us/investor/earnings/fy-2026-q3/press-release-webcast

Evidence gathered:

- Microsoft Cloud revenue was cited at $54.5 billion, up 29%.
- Azure growth was cited at about 40%.
- Local technical pull: MSFT close $418.57, RSI14 54.3, +4.53% above 50dma, -9.09% below 200dma, -12.51% over 6 months.

What this persuaded:

- MSFT was considered high-quality and safer, but the technical setup was less compelling than GOOGL.
- It remained a conservative alternative, not the best fresh entry.

Risks/leads to research deeper:

- Azure AI demand versus capex spend.
- Whether MSFT's 200-day weakness has reversed after the data pull.
- Copilot revenue and margin contribution.
- Any enterprise software slowdown indicators.

## 9. AMZN Evidence Packet

Primary source:

- Amazon Q1 2026 earnings release PDF: https://s2.q4cdn.com/299287126/files/doc_earnings/2026/q1/earnings-result/AMZN-Q1-2026-Earnings-Release.pdf

Evidence gathered:

- AWS segment sales increased 28% year over year to about $37.6 billion.
- Amazon exceeded a $20 billion annual revenue run rate for its chips business, including Graviton, Trainium, and Inferentia, according to the release.
- Local technical pull: AMZN close $266.32, RSI14 43.3, +27.69% over 3 months, +22.65% over 6 months, +10.08% above 50dma.

What this persuaded:

- AMZN was credible and had a non-overheated RSI, but GOOGL had the cleaner direct Cloud/AI acceleration plus margin story.
- AMZN stayed a watch/add-lower candidate.

Risks/leads to research deeper:

- AWS growth durability and margins.
- AI capex versus return profile.
- Retail margin contribution and logistics efficiency.
- Whether AMZN's current valuation gives a better risk/reward than GOOGL after latest price updates.

## 10. META Evidence Packet

Primary sources:

- Meta Q1 2026 results: https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-First-Quarter-2026-Results/
- Meta Q1 2026 PDF: https://s21.q4cdn.com/399680738/files/doc_news/Meta-Reports-First-Quarter-2026-Results-2026.pdf

Evidence gathered:

- Meta Q1 2026 revenue was about $56.311 billion, up 33%.
- Operating margin was cited at about 41%.
- 2026 capex guide was cited at $125-$145 billion.
- Local technical pull: META close $610.26, RSI14 49.9, -9.60% over 1 month, -4.54% over 3 months, -22.75% from 1-year high, -8.84% below 200dma.

What this persuaded:

- META looked potentially contrarian but less timely for a fresh buy than GOOGL.
- Capex intensity and weaker chart kept it below GOOGL/NVDA/AMZN/MSFT.

Risks/leads to research deeper:

- AI capex return and timing.
- Ads growth sustainability.
- Reality Labs losses.
- Regulatory or platform-dependency risk.
- Whether the current drawdown now offers a better entry than GOOGL after updated price action.

## 11. AVGO Evidence Packet

Primary source:

- Broadcom Q2 FY2026 announcement date: https://investors.broadcom.com/news-releases/news-release-details/broadcom-inc-announce-second-quarter-fiscal-year-2026-financial

Evidence gathered:

- Broadcom announced it would report Q2 FY2026 financial results and business outlook on Wednesday, 2026-06-03 after market close.
- Local technical pull: AVGO close $414.14, RSI14 49.0, +27.24% over 3 months, +19.41% over 6 months, +9.84% above 50dma.

What this persuaded:

- AVGO remained attractive but had near-term event risk.
- The panel did not want to initiate a fresh staged buy before the imminent earnings/business-outlook event without a specific event strategy.

Risks/leads to research deeper:

- Q2 FY2026 expectations and whisper numbers.
- AI semiconductor revenue trajectory.
- VMware integration and software growth.
- Customer concentration in custom AI accelerators.
- Whether waiting through June 3 is better than buying before earnings.

## 12. AMD Evidence Packet

Primary source:

- AMD Q1 2026 results: https://www.amd.com/en/newsroom/press-releases/2026-5-5-amd-reports-first-quarter-2026-financial-results.html

Evidence gathered:

- AMD Q1 2026 revenue was about $10.3 billion.
- Data Center segment revenue was about $5.8 billion, up 57% year over year.
- Local technical pull: AMD close $467.51, RSI14 75.2, +34.42% over 1 month, +118.63% over 3 months, +126.92% over 6 months, +54.20% above 50dma, +102.49% above 200dma, no drawdown from 1-year high in the pull.

What this persuaded:

- AMD had improving fundamentals and strong AI/data-center momentum.
- AMD was rejected as the fresh entry because the technical profile looked like a momentum chase.
- The small local model's earlier AMD pick was discounted because it appeared to chase price action and included weak or possibly invented claims.

Risks/leads to research deeper:

- Current valuation and forward EPS revisions.
- Data Center GPU share gains versus NVIDIA.
- Whether the price move is supported by actual estimate revisions.
- Any pullback zones where AMD becomes investable again.
- Insider/institutional flows after the run.

## 13. Sentiment / News Packet

Source used:

- Local yfinance news fetch on 2026-05-25.

Representative headlines captured:

GOOGL:

- EU plans to fine Google high triple-digit million euro sum, Handelsblatt reports.
- Google rolls out AI-powered ad formats at Marketing Live.
- AI/search and chatbot headlines were active.

NVDA:

- Nvidia described in multiple recent headlines as a top AI stock.
- BofA/Jim Cramer style AI-cycle commentary was present.

MSFT:

- Microsoft AI growth story meets revenue scrutiny and shifting big holders.
- AI trade commentary was active.

AMD:

- AMD planned to invest more than $10B in Taiwan's AI market, according to a headline.
- AMD was a trending stock with "facts to know before betting on it" type coverage.

AVGO:

- AI stock caution and AI-chip concentration headlines were visible.
- Near-term earnings event remained a research item.

META:

- AI optimism headlines plus platform/regulatory headlines.

AMZN:

- Growth stock / AI-related positive headlines.

What this persuaded:

- NVDA and AMD were sentiment-hot, which supported the AI thesis but increased crowding/chase concern.
- GOOGL sentiment was mixed, especially because of regulatory headlines, which made the entry less euphoric but increased headline risk.
- AVGO's near event date made a wait-through-event posture more reasonable.

Research follow-up:

- Verify the Google EU fine headline with primary or Reuters/Bloomberg-quality reporting.
- Pull current StockTwits/Reddit sentiment and compare to analyst headline sentiment.
- Separate "AI hype" headlines from revenue/earnings estimate revision data.
- Identify whether sentiment has deteriorated or improved since the 2026-05-25 yfinance pull.

## 14. Subagent Evidence Packet

Three Codex subagents were used and closed:

1. Repo-method auditor
2. Independent stock-pick verifier
3. Compact TradingAgents all-role panel

Subagent outputs that affected the decision:

- Repo-method auditor confirmed the active panel should include Market, Sentiment, News, Fundamentals, Bull, Bear, Research Manager, Trader, Aggressive Risk, Conservative Risk, Neutral Risk, Portfolio Manager, and final signal processing.
- Repo-method auditor confirmed Social Media Analyst is deprecated and should not be treated as a separate active role.
- Independent verifier selected GOOGL as the best staged entry and ranked NVDA second.
- All-role compact panel also selected GOOGL as final candidate and explicitly rejected AMD as a chase.
- Both decision subagents converged on GOOGL after an earlier parent-thread leaning toward NVDA.

Claims from subagents that need independent verification before relying on them:

- GOOGL P/E around 29.2.
- AMD P/E around 153.
- Any exact analyst target prices or consensus estimates not tied to primary source filings/releases.
- Any precise regulatory fine amount unless confirmed by primary reporting.

## 15. Current Ranking Rationale

1. GOOGL
   
   - Best balance of growth, margin quality, AI/cloud exposure, and non-overheated entry.
   - Technical setup showed strength without extreme RSI.
   - Whole-share budget works cleanly: 1-2 shares under $1,000.

2. NVDA
   
   - Best pure AI fundamentals.
   - Runner-up because entry/crowding risk is less clean.

3. AMZN
   
   - Strong AWS and chips story, non-overheated RSI.
   - Less clean than GOOGL on immediate evidence.

4. MSFT
   
   - High-quality conservative alternative.
   - Technical setup was weaker in the local pull.

5. AVGO
   
   - Strong AI exposure.
   - Event risk from 2026-06-03 earnings/business outlook.

6. META
   
   - Strong revenue/margins but heavy capex and weaker chart.

7. AMD
   
   - Strong fundamentals, but too extended technically.

## 16. Deep Research Handoff

Research objective:

Expand and verify the evidence trail behind the current GOOGL staged-buy conclusion. Treat this as web research and source validation. The trading system will analyze, decide, and execute separately.

Main question:

Is GOOGL still the best whole-share, under-$1,000 staged-entry candidate among NVDA, MSFT, GOOGL, AMZN, META, AVGO, and AMD after updating all facts, prices, catalysts, valuation, sentiment, and broker/order constraints?

Do not decide trade execution. Return research that helps the trading system decide.

Specific research tasks:

1. Verify all primary-source financial figures in this packet.
2. Update prices, technical indicators, premarket movement, support/resistance, ATR, moving averages, RSI, and volume for each candidate.
3. Verify Fidelity's current rules for extended-hours trading, GTC orders, conditions, stop orders, and trailing stops.
4. Verify whether Tuesday, 2026-05-26 open creates a gap-up/gap-down situation that changes the entry plan.
5. Compare GOOGL versus NVDA on current forward valuation, EPS revisions, free cash flow, capex, revenue growth, and margin trajectory.
6. Compare GOOGL versus AMZN/MSFT/META on AI monetization and Cloud growth quality.
7. Compare GOOGL versus AVGO/NVDA/AMD on AI infrastructure exposure and crowding risk.
8. Find any better leads outside the current set that fit the same constraints: large-cap U.S.-listed stock, whole shares, about $1,000 max, not a microcap/speculative thin-volume name.
9. Identify disconfirming evidence that would make GOOGL no longer the best lead.
10. Identify missing evidence that would improve the final trading decision.

Desired output from deeper research:

- Corrections table: packet claim, verified truth, source, confidence.
- Updated candidate ranking with factual reasons.
- Best new leads discovered, if any.
- Updated GOOGL entry zones based on current price/ATR/support.
- Catalyst calendar for each candidate for the next 30-60 days.
- Regulatory/legal risk update for GOOGL.
- Valuation comparison table.
- Sentiment/news summary with source quality labels.
- Clear list of unresolved questions.

## 17. Source Index

Broker/order mechanics:

- Fidelity order-type FAQ: https://www.fidelity.com/trading/faqs-order-types
- Fidelity placing-orders FAQ: https://www.fidelity.com/trading/faqs-placing-orders
- Fidelity trading-stocks help: https://www.fidelity.com/webcontent/ap002390-mlo-content/19.07/help/learn_trading_stocks.shtml
- Fidelity order types and conditions help: https://www.fidelity.com/webcontent/ap002390-mlo-content/19.09/help/learn_order_types_conditions.shtml
- Fidelity stop loss / stop limit learning page: https://www.fidelity.com/learning-center/trading-investing/trading/stop-loss-video

Market calendar:

- NYSE hours and calendar: https://www.nyse.com/markets/hours-calendars

Company sources:

- Alphabet Q1 2026 earnings PDF: https://s206.q4cdn.com/479360582/files/doc_financials/2026/q1/2026q1-alphabet-earnings-release.pdf
- Alphabet SEC Q1 2026 earnings exhibit: https://www.sec.gov/Archives/edgar/data/1652044/000165204426000043/googexhibit991q12026.htm
- NVIDIA Q1 FY2027 results: https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-First-Quarter-Fiscal-2027/default.aspx
- Microsoft FY2026 Q3 earnings: https://www.microsoft.com/en-us/investor/earnings/fy-2026-q3/press-release-webcast
- Amazon Q1 2026 earnings PDF: https://s2.q4cdn.com/299287126/files/doc_earnings/2026/q1/earnings-result/AMZN-Q1-2026-Earnings-Release.pdf
- Meta Q1 2026 results: https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-First-Quarter-2026-Results/
- Meta Q1 2026 PDF: https://s21.q4cdn.com/399680738/files/doc_news/Meta-Reports-First-Quarter-2026-Results-2026.pdf
- AMD Q1 2026 results: https://www.amd.com/en/newsroom/press-releases/2026-5-5-amd-reports-first-quarter-2026-financial-results.html
- Broadcom Q2 FY2026 announcement date: https://investors.broadcom.com/news-releases/news-release-details/broadcom-inc-announce-second-quarter-fiscal-year-2026-financial

Local methodology files:

- `tradingagents/graph/setup.py`
- `tradingagents/graph/analyst_execution.py`
- `tradingagents/graph/conditional_logic.py`
- `tradingagents/agents/analysts/market_analyst.py`
- `tradingagents/agents/analysts/sentiment_analyst.py`
- `tradingagents/agents/analysts/news_analyst.py`
- `tradingagents/agents/analysts/fundamentals_analyst.py`
- `tradingagents/agents/researchers/bull_researcher.py`
- `tradingagents/agents/researchers/bear_researcher.py`
- `tradingagents/agents/managers/research_manager.py`
- `tradingagents/agents/trader/trader.py`
- `tradingagents/agents/risk_mgmt/aggressive_debator.py`
- `tradingagents/agents/risk_mgmt/conservative_debator.py`
- `tradingagents/agents/risk_mgmt/neutral_debator.py`
- `tradingagents/agents/managers/portfolio_manager.py`
- `tradingagents/agents/schemas.py`
