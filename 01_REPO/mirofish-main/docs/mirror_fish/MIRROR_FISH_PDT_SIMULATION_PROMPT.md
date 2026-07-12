# Mirror Fish PDT / Intraday Margin Simulation Prompt

Generated: 2026-06-03

Simulate the market-social reaction around the June 4, 2026 U.S. PDT-to-intraday-margin transition through the June 13 macro/options window. This is for an advisory TradingAgents research packet, not for direct trading.

Use the uploaded reality seed as the source of truth. Build a simulated society that includes regular market participants and institutional actors. Do not limit the world to retail people.

Required actor layers:

- Retail and individual traders: new small-account day traders, PDT-rule-confused traders, AI-bot users, prompt-engineered bot users, options gamblers, 0DTE traders, cash-account users misunderstanding settlement, cautious broker/platform users, panic sellers, FOMO buyers, systematic traders, contrarian liquidity-takers, and risk-managed experienced individuals.
- Broker/platform/clearing actors: Robinhood, Alpaca/API users, Fidelity, Schwab, Interactive Brokers, Webull, tastytrade/tastylive, margin/risk desks, clearing and settlement desks, broker support teams, broker status pages, broker API/platform reliability teams, and compliance/legal reviewers.
- Government, regulator, and policy actors: FINRA, SEC market-structure staff, Federal Reserve/FOMC macro voices, Treasury auction context, congressional/policy-maker commentary, investor-education offices, and public-facing regulatory communications.
- Institutional investor and market-structure actors: market makers, liquidity providers, ETF/index desks, prop desks, quant funds, hedge funds, asset managers, volatility desks, sell-side/electronic-execution desks, and risk managers watching novice clustering, 0DTE demand, and order-flow toxicity.
- Media and narrative actors: financial media outlets, YouTube/TikTok explainers, Reddit/X communities, newsletters, finfluencers, headline aggregators, broker education pages, and data-dashboard accounts that amplify or correct simplified rule narratives.
- Developer, automation, and tech actors: broker API developers, bot-framework maintainers, TradingView/script users, AI-agent builders, prompt-bot operators, autonomous-broker integrators, open-source trading communities, infrastructure vendors, broker/platform executives, fintech founders, AI-company executives, Apple WWDC participants, semiconductor/AI-infrastructure executives, and investor-relations teams.

Each layer must have clear incentives, constraints, failure modes, and influence paths. Not every actor trades. Some actors shape regulation, media framing, broker implementation, liquidity, developer tooling, executive narrative, or validation signals. Preserve cross-layer feedback loops: policy language becomes broker UI text; broker UI text becomes retail screenshots; screenshots become influencer content; influencer content becomes novice order flow; novice order flow becomes market-maker/quant signal; market-maker response becomes retail conspiracy narrative; regulator/broker clarification then either cools or intensifies the next wave.

Focus on how narratives, confusion, overconfidence, risk misunderstandings, ticker attention, broker/platform constraints, AI-assisted automation, institutional liquidity response, media interpretation, policy clarification, developer tooling, and macro catalysts evolve. Do not model June 4 as a universal broker switch. Do not assume "PDT is gone" means unlimited leverage. Do not ignore payrolls, CPI, PPI, Treasury auctions, oil/geopolitics, Fed repricing, AI/semiconductor events, Apple WWDC, broker rollouts, or the October 20, 2027 implementation transition window.

Run at least these scenario branches:

1. Mostly narrative: broker rollout is fragmented and macro dominates, so the observable effect is modest.
2. Medium retail-flow effect: early broker/API rollout creates localized churn in SPY, QQQ, 0DTE/short-dated options, semis, and broker/platform stocks.
3. Large speculative-flow effect: cooperative macro and AI news amplify rule-change hype into reflexive retail crowding.
4. Adverse macro override: hot payrolls/CPI/PPI, weak auctions, oil/geopolitical stress, or Fed repricing overwhelms the retail-flow story.
5. Valid-support branch: some crowd dip-buying is correct, so not all retail flow is bad signal.
6. Broker-friction branch: traders discover buying power, intraday margin deficits, settlement, account state, house requirements, and API risk checks still block activity.
7. Bot-correlation branch: AI-assisted traders and simple bot stacks converge on the same obvious signals, compressing reaction time and increasing false-positive crowding.
8. Institutional-liquidity branch: market makers, quant funds, ETF desks, and prop desks adapt to novice clustering and either dampen, fade, or temporarily amplify the flow.
9. Policy/media-clarification branch: FINRA/SEC/broker explanations compete with viral simplified narratives and change behavior after the first wave of confusion.
10. Developer-infrastructure branch: broker APIs, bot frameworks, and AI-agent tooling accelerate both disciplined automation and brittle copycat behavior.

Target 1,000 agents, acceptable range 750-1,500. Target 30 rounds, acceptable range 25-35. Do not jump to 40-50 rounds unless readiness and cost estimates justify it. Use short-to-medium agent messages. Enable graph memory updates if stable. Preserve simulation environment/files after report generation for deep interaction and character interviews. Keep the final report long, structured, skeptical, and operational.

The final report must separate:

- what the simulated society strongly suggests
- what might be model bias
- what requires real market-data validation
- what should not be acted on directly

Required final sections:

- executive summary
- scenario probability map
- strongest simulated narratives
- weak or noisy signals
- false-positive patterns
- retail trader archetypes
- AI-bot and prompt-bot failure modes
- broker/platform confusion patterns
- government, regulator, and policy-maker reaction map
- institutional investor, market-maker, and liquidity-provider reaction map
- media outlet and influencer narrative map
- developer community, bot-framework, and broker API behavior map
- company and tech-executive narrative map
- ticker/category attention map
- macro override risks
- early-warning signals
- TradingAgents rule implications
- recommended validation tasks using real market data
- confidence levels
- machine-readable summary if practical

This run is advisory only. Do not turn simulated hype, tickers, or character opinions into direct trade instructions. Convert findings into validation tasks, false-signal filters, risk gates, broker-confusion warnings, and market-psychology assumptions for TradingAgents.

## Predictive-Quality Upgrade Patch

Use the 30-round June 4-13 event-beat map from `MIRROR_FISH_EVENT_BEAT_MAP.md`. If a round has a mapped beat, agents should react to that date's catalysts instead of treating rounds as generic hours. If the runner does not inject scheduled events directly, infer the beat from this prompt and the prepared `event_config.scheduled_events` metadata.

Every round should update these simulated social/behavioral state variables, without pretending they are live market data: retail_flow_intensity, broker_confusion_index, buying_power_rejection_confusion, AI_bot_copycat_index, 0DTE_attention_index, options_gamma_IV_pressure, meme_smallcap_spillover, macro_dominance_index, oil_geopolitical_pressure, AI_semiconductor_momentum, institutional_fade_absorb_amplify_index, policy_media_clarification_index, false_signal_risk_index, and branch_confidence_distribution.

On rounds 3, 6, 11, 18, 22, 25, and 30, selected agents should emit forecast ballots. A forecast ballot must provide probability estimates for: mostly narrative / limited effect, medium retail-flow, large speculative-flow, adverse macro override, valid-support, broker-friction, bot-correlation, institutional-liquidity, policy/media clarification, developer-infrastructure, and no meaningful retail-flow control branches. Each ballot must include confidence 0-100, top evidence used, what would change the agent's mind, tickers/categories expected to be most affected, and whether the agent attributes movement to retail/PDT, macro/rates, AI/semis, oil/geopolitics, options expiry, or institutional/liquidity response.

The final report must include a causal attribution ledger. Each major simulated social or market move must tag primary cause, secondary causes, confidence, simulation evidence, real-world validation data needed, and false-attribution risk. Never automatically credit June 4 for moves explainable by jobs, CPI/PPI, Treasury auctions, oil/geopolitical pressure, AI/semiconductor momentum, options expiry, or institutional/liquidity response.

Add the explicit control branch: no meaningful retail-flow effect. In that branch, social chatter rises, but broker implementation is fragmented, real-time controls block many attempts, macro dominates, and realized flow does not confirm the narrative. Compare every other branch against this control.

Every major scenario branch must include falsifiable validation logic with fields: signal, expected_if_branch_true, expected_if_branch_false, data_to_check, confidence_update, and false_positive_warning. Required validation areas are SPY/QQQ/0DTE attention and volume, HOOD/BULL relative performance, broker support/UI confusion, order rejection or buying-power confusion, options volume/IV/open-interest changes, Treasury auction/yield reaction, CPI/PPI/jobs macro override, oil/geopolitical shock, AI/semi narrative persistence or failure, small-cap/meme spillover, bot-correlation/copycat behavior, and institutional/liquidity absorption or fading of novice flow.

