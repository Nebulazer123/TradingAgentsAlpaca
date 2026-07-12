# MiroFish Event Beat Map

Generated: 2026-06-03

Purpose: make the prepared 30-round Stage 03 run explicitly represent the June 4-13, 2026 market-social window. This map is pre-run guidance only. It does not start Stage 03 and it does not claim access to live social feeds.

## Runner Interpretation

- Current runner behavior: rounds are generated from `time_config.total_simulation_hours` and `minutes_per_round`; active agents are selected from `agents_per_hour_min`, `agents_per_hour_max`, multipliers, `active_hours`, and `activity_level`.
- Current event injection behavior: the runtime injects `event_config.initial_posts`; it does not actively schedule per-round event posts from `scheduled_events`.
- Patch strategy: `event_config.scheduled_events` now stores the 30-round beat map as durable metadata, and `simulation_requirement` plus `MIRROR_FISH_PDT_SIMULATION_PROMPT.md` instruct agents and ReportAgent to honor it.

## Beat Map

| Round | Date | Beat | Primary Catalysts | Required Interpretation |
| --- | --- | --- | --- | --- |
| 1 | 2026-06-04 | Rule effective date opens | FINRA effective date, first broker UI/support confusion, first small-account trade attempts | Start with confusion, not certainty. |
| 2 | 2026-06-04 | Broker first-reaction loop | Early Robinhood/Alpaca narratives, cash-vs-margin confusion, screenshots | Separate actual eligibility from viral claims. |
| 3 | 2026-06-04 | First branch ballot | Initial forecast ballot, no-flow control check, first options attention scan | Emit probabilities and evidence. |
| 4 | 2026-06-05 | Jobs report shock gate | May employment situation, weekly options expiration | Test macro override immediately. |
| 5 | 2026-06-05 | Payroll digestion | Yield reaction, support backlog, HOOD/BULL watch | Do not over-credit PDT narrative. |
| 6 | 2026-06-05 | Weekly expiry branch ballot | Weekly options expiry, 0DTE evidence check | Refresh branch probabilities. |
| 7 | 2026-06-06 | Weekend social digestion | YouTube/Reddit/X simplification, FOMC blackout begins | Let narrative spread without pretending new flow is confirmed. |
| 8 | 2026-06-07 | Weekend narrative consolidation | Copycat bot templates, support-story virality | Identify false-signal channels. |
| 9 | 2026-06-08 | Schwab cutover and WWDC open | Schwab day-trade-count change, Apple WWDC | Broker rollout and AI narrative can interact. |
| 10 | 2026-06-08 | Platform implementation comparison | Schwab/Fidelity/Webull contrast, agentic trading framing | Compare broker-specific friction. |
| 11 | 2026-06-08 | AI-agent branch ballot | AI-agent adoption ballot, WWDC effect check | Update bot-correlation probability. |
| 12 | 2026-06-09 | Trade balance and 3-year auction | Trade balance, 3-year Treasury auction | Rates/liquidity must compete with retail story. |
| 13 | 2026-06-09 | Auction-liquidity digestion | Yield reaction, institutional fade/absorb decision | Watch institutional response. |
| 14 | 2026-06-09 | Pre-CPI positioning | CPI setup, 0DTE positioning risk | Mark pre-data speculation as fragile. |
| 15 | 2026-06-10 | CPI release shock gate | May CPI, 10-year Treasury auction | Macro branch can dominate. |
| 16 | 2026-06-10 | CPI attribution fight | Retail/PDT vs inflation/yield attribution | Force cause separation. |
| 17 | 2026-06-10 | Oracle and AI infrastructure readthrough | Oracle earnings, AI infrastructure/capex | AI/semis can be independent cause. |
| 18 | 2026-06-10 | CPI branch ballot | Post-CPI ballot, control comparison | Update probabilities and causal ledger. |
| 19 | 2026-06-11 | PPI release shock gate | May PPI, 30-year Treasury auction | Re-test inflation/rates branch. |
| 20 | 2026-06-11 | Long-end auction digestion | 30-year demand, liquidity response | Watch spreads and absorption/fading. |
| 21 | 2026-06-11 | Broker friction persistence test | Support complaints, buying-power rejection | Distinguish lasting friction from day-one confusion. |
| 22 | 2026-06-11 | PPI branch ballot | Post-PPI ballot, macro probability refresh | Update institutional-liquidity branch. |
| 23 | 2026-06-12 | Michigan sentiment and weekly expiry | Sentiment/inflation expectations, weekly options expiration | Check options/IV confirmation. |
| 24 | 2026-06-12 | Second weekly expiry digestion | Open interest/volume confirmation need | Filter false social signals. |
| 25 | 2026-06-12 | Validation ballot | Validation thresholds, control comparison | Convert story into falsifiable checks. |
| 26 | 2026-06-13 | Recap begins | June 4-12 recap, confirmed flow vs chatter | Separate evidence from interpretation. |
| 27 | 2026-06-13 | Causal consolidation | Primary/secondary cause ledger | Tag false-attribution risk. |
| 28 | 2026-06-13 | TradingAgents validation queue | Validation task extraction, watchlist | Prepare advisory evidence path. |
| 29 | 2026-06-13 | Stage 05 interview shortlist | Wrong predictions, false-signal sources | Select interview targets from telemetry. |
| 30 | 2026-06-13 | Final pre-report ballot | Final ballot, branch history, ReportAgent handoff | Preserve uncertainty and evidence. |

## Forecast Ballot Rounds

Required ballot rounds: 3, 6, 11, 18, 22, 25, and 30.

Each ballot must include:

- branch probabilities across all required branches
- confidence 0-100
- top evidence used
- what would change the agent's mind
- affected tickers/categories
- causal attribution choice: retail/PDT, macro/rates, AI/semis, oil/geopolitics, options expiry, or institutional/liquidity

## Config Patch

`backend\uploads\simulations\sim_974459649906\simulation_config.json` now includes 30 `event_config.scheduled_events` records matching this map. The map is metadata plus prompt instruction; the current runner does not inject scheduled events directly.
