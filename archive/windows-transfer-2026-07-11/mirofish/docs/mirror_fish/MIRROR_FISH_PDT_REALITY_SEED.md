# Mirror Fish PDT / Intraday Margin Reality Seed

Generated: 2026-06-02

Purpose: upload this as the reality seed/report for the one-time MiroFish trading-society simulation. It is background evidence for an advisory TradingAgents packet, not trade truth and not an execution instruction.

## Core Thesis

June 4, 2026 is a real rule-change date for U.S. margin day trading, but it should not be modeled as a clean one-day market-structure regime break. The old pattern day trader day-count framework and old $25,000 PDT minimum equity requirement are being replaced by a risk-based intraday-margin framework. The likely market effect is a broker-staggered retail-flow catalyst concentrated in small margin accounts, options-active retail, broker/platform narratives, AI-bot users, and highly liquid intraday products.

The simulation should focus on behavior, not mythology:

- Many traders will hear "PDT is gone" and behave as if day trading is broadly unlocked.
- Brokers still impose buying power, margin eligibility, account equity, house requirements, settlement/cash limits, open-order reservations, and real-time risk controls.
- The broader tape from June 4 through June 13 can easily be dominated by jobs, CPI, PPI, Treasury auctions, oil/geopolitical headlines, Fed repricing, and AI/semiconductor events.
- The useful question is how trader groups behave when they believe access got easier while the market and brokers still punish poor risk control.

## Core Regulatory Facts

- FINRA adopted new intraday margin requirements that replace the old day-trading margin provisions, including the pattern day trader framework.
- The new requirements become effective on June 4, 2026, with an allowed brokerage-firm transition period through October 20, 2027.
- The old PDT day-count designation and the old $25,000 PDT minimum equity requirement are removed under the new framework once a firm transitions.
- The new framework is risk-based: brokerage firms monitor whether a margin account maintains adequate equity during the trading day relative to actual intraday exposure.
- Repeated failure to satisfy intraday margin deficits promptly may lead to account restrictions for up to 90 days.
- Standard margin basics still matter. FINRA investor guidance says $2,000 is the minimum equity required to engage in leveraged margin trading, and maintenance margin requirements still apply.
- Firms may implement the new framework differently. Some may proactively block trades that would create deficits; others may compute end-of-day intraday margin requirements and call for margin afterward; some may use a hybrid.

## Broker / Platform Rollout Assumptions

- Robinhood states that on June 4, 2026, FINRA's new intraday-margin standards replace PDT for Robinhood margin accounts; Robinhood says the $25,000 minimum portfolio value goes away but the $2,000 margin minimum still applies.
- Robinhood also says it monitors accounts in real time to prevent activity that creates or increases intraday margin deficits.
- Alpaca says it will implement the change for Trading API users and Broker API partners on June 4, 2026. Alpaca says PDT fields and day-trade-count logic are being removed/replaced and pre-trade checks will reject orders that would create a margin deficit.
- Schwab says the new rules take effect June 4, but Schwab plans to stop counting day trades and stop opening new PDT accounts on June 8.
- Fidelity says the new rules go into effect June 4, firms have up to 18 months to implement, and Fidelity expects to align with the new requirements soon after June 4.
- Webull says the amendment takes effect June 4 and brokers may begin implementing on that date, but its help page says it will share more information on its own implementation timing as the effective date approaches.
- Therefore the simulation should assume fragmented rollout, mixed UI messaging, and broker-specific user confusion rather than one universal switch.

## June 4 Through June 13 Catalyst Calendar

The simulation should not attribute every move to the rule change. The following catalysts should compete with the retail-flow narrative:

- June 3: Fed Beige Book, ISM Services PMI, Broadcom earnings after close, Microsoft Build AI/developer narrative.
- June 4: FINRA intraday-margin effective date, Treasury auction announcements, Fed/regulatory testimony, productivity/cost data.
- June 5: U.S. Employment Situation, consumer credit, weekly options expiration.
- June 6: FOMC blackout begins for the June 16-17 meeting.
- June 8: Apple WWDC begins, Schwab planned day-trade-count change, first observable fallout from June 4/5 behavior.
- June 9: Trade balance, 3-year Treasury auction.
- June 10: May CPI, 10-year Treasury auction, Oracle earnings after close.
- June 11: May PPI, Fed Z.1, 30-year Treasury auction.
- June 12: University of Michigan preliminary sentiment/inflation expectations, weekly options expiration.
- Ongoing: oil, Iran/Hormuz, inflation expectations, rates, Fed repricing, and AI/semiconductor leadership.

## Expected Crowd Psychology Inputs

- New small-account traders may rush into familiar high-volume names after hearing "the PDT rule is gone."
- Total beginners, under-$25k overconfident traders, and PDT-rule-confused traders are likely to lean on simplified narratives, social proof, broker UI cues, and obvious watchlists.
- Reddit/social momentum chasers, FOMO buyers, panic sellers, and news-reactive traders will respond to influencer framing, price movement, screenshots, and headline bursts.
- AI-bot hobbyists, prompt-engineered bot users, broker/API developers, and autonomous-broker users may deploy simple ranking, backtest, copy-social, dip-buy, breakout, or mean-reversion loops.
- Options gamblers and 0DTE traders may treat the change as a green light for faster short-dated expression, even when assignment, buying power, and margin mechanics remain binding.
- Prepared systematic traders, contrarian liquidity-takers, and risk-managed professional-ish traders may use novice clustering as a liquidity signal and fade obvious crowd behavior.
- Finfluencers and YouTube explainers may simplify the rule change into clickable narratives, accelerating misunderstanding even when the legal/mechanical details are more nuanced.
- Broker-support-confused users may provide noisy but useful evidence of rollout fragmentation, UI ambiguity, account restrictions, and margin-block surprises.
- Experienced traders exploiting novice flow may watch for screenshots, crowded watchlists, and sudden 0DTE/leveraged-ETF attention as liquidity or fade signals.
- Social narratives may overcompress the rule change into false slogans: "PDT is dead," "unlimited day trading," "$2k is the new $25k," "brokers are opening the gates," "AI agents can trade now," or "0DTE is the easiest route."
- The model should not treat all AI traders as smart or all new entrants as equally naive. Some agents are crude prompt wrappers, some are fast but brittle bot stacks, and some are disciplined systematic traders.

## Required Institutional Actor Ecology

The simulated society must include more than regular people and retail trading accounts. Treat the market as a multi-layer information system where some actors trade, some shape rules, some shape narratives, and some change the infrastructure that makes novice flow possible.

Required first-class actor layers:

- Retail and individual layer: new day traders, small margin accounts, PDT-confused traders, options gamblers, 0DTE traders, cash-account users misunderstanding settlement, panic sellers, FOMO buyers, and risk-managed experienced individuals.
- Broker, clearing, and platform layer: Robinhood, Alpaca/API users, Fidelity, Schwab, Interactive Brokers, Webull, tastytrade/tastylive, clearing/risk desks, margin departments, broker support teams, broker status pages, and API/platform reliability teams.
- Government, regulator, and policy layer: FINRA, SEC market-structure staff, Federal Reserve/FOMC macro voices, Treasury auction context, congressional/policy-maker commentary, investor-education offices, and broker compliance/legal teams interpreting rule obligations.
- Institutional investor and market-structure layer: market makers, liquidity providers, ETF/index desks, prop desks, quant funds, hedge funds, asset managers, volatility desks, risk managers, and sell-side/electronic-execution desks watching novice clustering and order-flow toxicity.
- Media and narrative layer: financial media outlets, broker education pages, YouTube/TikTok explainers, Reddit/X communities, newsletters, finfluencers, headline aggregators, and data-dashboard accounts that can amplify simplified or corrected versions of the rule.
- Developer and automation layer: broker API developers, bot-framework maintainers, TradingView/script users, AI-agent builders, prompt-bot operators, autonomous-broker integrators, open-source trading communities, and infrastructure vendors whose tools can compress reaction times.
- Company and tech-executive layer: broker/platform executives, fintech founders, AI-company executives, mega-cap tech event speakers, Apple WWDC participants, semiconductor/AI-infrastructure executives, and investor-relations teams whose public narratives can redirect attention.

Each layer should have explicit incentives, constraints, failure modes, and influence paths. Not every actor should trade. Some actors should change belief formation, platform behavior, liquidity, compliance messaging, media framing, or validation signals. The simulation should show cross-layer feedback loops: policy language becomes broker UI text; broker UI text becomes retail screenshots; screenshots become finfluencer content; finfluencer content becomes novice order flow; novice order flow becomes market-maker/quant signal; market-maker response becomes retail conspiracy narrative; regulator/broker clarification then either cools or intensifies the next wave.

Do not collapse all institutions into generic "Organization" behavior. If MiroFish has to use broad entity labels internally, the persona text and report sections must still preserve these distinct roles: policy maker, government/regulator, broker/platform, media outlet, developer community, tech executive, institutional investor, market maker/liquidity provider, and retail trader.

## Exposed Instruments And Themes

Highest-probability attention buckets:

- Index ETFs and short-dated options ecosystems: SPY, QQQ, IWM, DIA if relevant, SPX/XSP-style index-option expression where applicable.
- Leveraged ETFs and high-feedback products: TQQQ, SQQQ, SOXL, SOXS, TSLL if relevant.
- AI/semiconductor leadership: NVDA, AVGO, SOX ecosystem, Broadcom readthroughs, AI infrastructure narratives.
- Mega-cap tech and familiar retail names: AAPL, MSFT, AMZN if relevant, TSLA, ORCL.
- Broker/platform stocks and retail-enablement infrastructure: HOOD, BULL, and other firms tied to retail engagement/order volume.
- Weaker but plausible spillover: small caps, meme names, high-short-interest names, low-float names, crypto-linked equities.

Do not assume these tickers are trade recommendations. Treat them as attention and scenario nodes for simulation.

## Required Scenario Branches

Run the simulation as a multi-branch society, not a single deterministic story:

1. Mostly narrative: the rule is real, but broker rollout is fragmented, real-time blocks kick in quickly, and macro data dominates. Actual market effect is modest.
2. Medium retail-flow effect: Robinhood, Alpaca/API users, and early-implementing platforms create visible incremental intraday churn in index ETFs, 0DTE/short-dated options, semis, and broker stocks, but the effect stays localized.
3. Large speculative-flow effect: rule-change hype coincides with cooperative macro and AI news, creating reflexive crowding into SPY/QQQ options, semis, and selected high-beta names.
4. Adverse macro override: hot payrolls, hot CPI/PPI, weak Treasury auction demand, oil/geopolitical stress, or Fed repricing push yields higher and overwhelm the retail-flow narrative.
5. Valid-support branch: some retail dip buying is correct and not all crowd entries fail. Include this to avoid teaching the model that every retail-driven move is false.
6. Broker-friction branch: traders discover that buying power, margin deficits, settlement, and account state still block activity despite the old PDT restriction being gone.
7. Bot-correlation branch: AI-assisted traders and simple bot systems react to the same obvious signals, compressing reaction time and increasing false-positive crowding.

## False-Positive Risks

- Assuming every broker implements on June 4.
- Confusing no-PDT-count with unlimited leverage.
- Forgetting the rule mainly concerns margin accounts, while cash accounts are constrained by settled funds.
- Overestimating capital impact from small-account traders.
- Treating social hype as proof of durable capital flow.
- Ignoring real-time broker margin blocks and buying-power controls.
- Underweighting payrolls, CPI, PPI, Treasury auctions, Fed repricing, and oil/geopolitical shocks.
- Assuming AI-assisted retail trading is uniformly sophisticated or universally available.
- Letting the simulation overfit to SPY/QQQ/AI if social attention unexpectedly rotates into small caps, meme names, crypto proxies, or broker stocks.

## Validation Tasks For June 4 Through June 13

The final report should turn simulated output into validation tasks:

- Confirm broker-specific rollout dates and UI/account behavior on June 4 and June 8.
- Watch first-session changes in SPY/QQQ/0DTE message volume, options volume, intraday turnover, and reversal patterns.
- Track HOOD/BULL relative performance against market and broker-rollout headlines.
- Monitor Treasury auction demand and yields on June 9-11.
- Refresh macro and oil/geopolitical assumptions daily.
- Update scenario probabilities after payrolls, CPI, PPI, and Michigan sentiment.
- Check whether attention remains concentrated in SPY/QQQ/0DTE and large AI names or spills into small caps, meme names, or crypto proxies.
- Separate behavior-change evidence from capital-deployment evidence: more churn and screenshots do not automatically imply enough gross capital to move indices.

## Predictive-Quality Patch For This Prepared Run

The final prepared run now has a measurement contract, not only a narrative seed:

- 30 rounds map explicitly to June 4-13 event beats in `MIRROR_FISH_EVENT_BEAT_MAP.md` and `event_config.scheduled_events`.
- Agents should update simulated social/behavioral state variables each round, using `MIRROR_FISH_STATE_VARIABLES.md`.
- Forecast ballots are required on rounds 3, 6, 11, 18, 22, 25, and 30.
- The final report must use the causal attribution ledger in `MIRROR_FISH_CAUSAL_ATTRIBUTION_PLAN.md`.
- The options/0DTE layer must separate retail attention, actual options-flow signal, IV/gamma/liquidity signal, market-maker response, and false social signal.
- The explicit control branch is: no meaningful retail-flow effect. Social chatter can rise while fragmented broker rollout, real-time risk controls, macro, oil, rates, AI/semi news, and options expiry explain most realized movement.
- Post-run telemetry should be extracted with `mirofish_postrun_telemetry.py` after Stage 03 and Stage 04 artifacts exist.

## TradingAgents Interpretation Boundary

- Treat MiroFish output as advisory simulation evidence only.
- Do not act directly on simulated hype, tickers, or narratives.
- Convert findings into validation tasks, false-signal filters, risk gates, broker-confusion warnings, and market-psychology assumptions.
- Keep TradingAgents execution deterministic and fail-closed: stocks-only, long-only, limit-only, no options, no crypto, no shorts, no margin expansion, dry-run before submit, fresh quote/news/order validation, and live gates.
- Old PDT day-count, old $25,000 PDT minimum, PDT designation, and old day-trading-buying-power logic should not be blockers in the research interpretation once broker/account state has actually transitioned, but broker buying power and intraday-margin risk still matter.
- If Alpaca-facing code sees old PDT fields, treat them as transition-sensitive. Validate account buying power, account status, symbol eligibility, open orders, and API schema behavior directly before any future execution workflow.

## Research Sources Used

- Deep Research report: `C:\Users\Corbin\Downloads\deep-research-report (32).md`
- Trading architecture context: `C:\Users\Corbin\Downloads\deep-research-report (31).md`
- Alpaca execution mechanics context: `C:\Users\Corbin\Downloads\deep-research-report (25).md`
- FINRA intraday margin guidance: https://syndication.finra.org/content/understanding-new-intraday-margin-requirements
- FINRA Regulatory Notice 26-10: https://www.finra.org/rules-guidance/notices/26-10
- Robinhood day trading support: https://robinhood.com/us/en/support/articles/day-trading/
- Robinhood agentic trading announcement: https://robinhood.com/us/en/newsroom/robinhood-is-now-open-to-agents/
- Alpaca PDT/intraday-margin framework: https://alpaca.markets/blog/finra-retires-the-pdt-rule-introducing-alpacas-new-intraday-margin-framework/
- Schwab PDT change overview: https://www.schwab.com/learn/story/sec-approves-scrapping-25000-day-trader-minimum
- Fidelity day-trading margin overview: https://www.fidelity.com/learning-center/trading-investing/trading/day-trading-margin
- Webull day trading rules: https://www.webull.com/help/faq/10954-Understanding-day-trading
- tastylive PDT change and 0DTE nuance: https://www.tastylive.com/news-insights/the-pdt-rule-is-gone-here-s-what-changes-on-june-4
- Interactive Brokers AI integration: https://www.interactivebrokers.com/en/general/about/mediaRelations/6-1-26.php
