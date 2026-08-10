# MiroFish Stage 05 Interview Plan

Generated: 2026-06-03

Purpose: pre-plan character interviews after Stage 04 using telemetry, not manual guessing. Do not run these interviews before the real Stage 03 and Stage 04 report are complete.

## Selection Inputs

Use `docs\mirror_fish\mirofish_postrun_telemetry.py` after the run to identify:

- unique active agents
- top influential agents
- actions by actor layer
- forecast ballot outliers
- false-signal sources
- bot-correlation sources
- agents whose predictions changed after macro data
- agents whose behavior was copied by others

## Interview Targets

| Target | Selection Rule |
| --- | --- |
| Most influential beginner trader | Retail/Person actor with high action count and beginner segment tags |
| Most copied finfluencer/media actor | Finfluencer or MediaOutlet actor repeatedly referenced, liked, quoted, or echoed |
| Broker support/risk desk actor | BrokerPlatform/Organization actor tied to support, risk, rejection, or clarification events |
| API/bot developer actor | DeveloperCommunity actor tied to bot/copycat/API/MCP language |
| Volatility market maker actor | InstitutionalInvestor actor tied to IV/gamma/spread/hedging language |
| ETF/index desk actor | InstitutionalInvestor actor tied to SPY/QQQ/IWM/index liquidity language |
| Contrarian systematic trader | RetailTrader or InstitutionalInvestor actor that faded crowded novice signals |
| Regulator/policy clarification actor | RegulatorAgency actor tied to FINRA/SEC/investor education |
| Most wrong prediction | Forecast ballot with largest later contradiction |
| Strongest false-signal creator | Actor whose posts drove narrative without validation support |
| Narrative propagation center | Actor with high cross-platform echo or quote influence |
| Bot-correlation center | Actor whose bot/API framing was copied by other agents |
| Macro mind-changer | Actor whose branch probability changed after jobs/CPI/PPI |
| Macro misattributor | Actor who credited PDT for a move explained better by macro/oil/rates |

## Interview Questions

Each interview should ask:

- What changed your behavior?
- What signal did you trust?
- What did you misunderstand?
- What would invalidate your belief?
- Which ticker/category did you influence?
- What real-world data would prove your branch right or wrong?
- What did other agents copy from you?
- Which part of the story was noise?
- What did you misattribute?

## Output Use

Stage 05 responses should feed the final Codex synthesis, TradingAgents advisory evidence packet, causal attribution ledger, validation tasks, false-signal filters, ticker/category watchlist, broker/platform confusion assumptions, bot-correlation warnings, and daily refresh checklist.
