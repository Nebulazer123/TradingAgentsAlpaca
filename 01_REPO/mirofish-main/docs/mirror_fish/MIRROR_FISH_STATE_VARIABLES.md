# MiroFish State Variables

Generated: 2026-06-03

These variables are simulated social and behavioral measurements. They are not live market data and must not be treated as direct trading signals.

## Variables

| Variable | Meaning | Update Evidence |
| --- | --- | --- |
| `retail_flow_intensity` | Simulated pressure from new or newly unconstrained retail traders | posts about first trades, account screenshots, ticker clustering |
| `broker_confusion_index` | Degree of fragmented broker rollout and user uncertainty | support complaints, UI mismatches, help-page contradictions |
| `buying_power_rejection_confusion` | Confusion caused by margin, buying power, settled funds, or rejected orders | rejection posts, support desk actors, broker risk-desk responses |
| `AI_bot_copycat_index` | Herding from agentic trading, prompt bots, MCP integrations, and copied scripts | shared bot templates, duplicate watchlists, API developer chatter |
| `0DTE_attention_index` | Retail attention on 0DTE or short-dated options | SPY/QQQ/TSLA/AAPL options posts, expiry chatter |
| `options_gamma_IV_pressure` | Simulated pressure from options volume, gamma, IV, spreads, and market-maker reaction | dealer/vol-desk actors, IV/gamma discussion, spread-quality warnings |
| `meme_smallcap_spillover` | Rotation into small caps, low-float, short-interest, or meme names | IWM/meme/low-float mentions and social proof loops |
| `macro_dominance_index` | Degree to which jobs, CPI, PPI, rates, Treasury auctions, Fed repricing, or sentiment dominate | macro actors, yield talk, data-release reactions |
| `oil_geopolitical_pressure` | Competing oil/Middle East/Hormuz shock pressure | oil, crude, Hormuz, Iran, Middle East mentions |
| `AI_semiconductor_momentum` | AI infrastructure, capex, semiconductor, and WWDC/Oracle/Broadcom/Marvell narrative pressure | AI capex, AVGO/MRVL/NVDA/ORCL/AAPL discussion |
| `institutional_fade_absorb_amplify_index` | Institutional or liquidity-provider response to novice clustering | market-maker, ETF desk, quant, prop, hedge fund, spread behavior |
| `policy_media_clarification_index` | Corrective explanations from regulators, brokers, media, or educators | FINRA/SEC/broker education, mainstream media, finfluencer corrections |
| `false_signal_risk_index` | Risk that social evidence is not confirmed by real flow or market data | unverified screenshots, causality conflicts, over-attribution warnings |
| `branch_confidence_distribution` | Probability distribution across scenario branches | forecast ballots, final report probability map |

## Round Update Rule

Every round should update at least the three state variables listed in that round's `state_variable_focus`. ReportAgent should preserve a compact round-by-round trace and use it in:

- scenario probability map
- causal attribution ledger
- validation thresholds
- post-run telemetry extraction
- Stage 05 interview target selection

## Output Shape

Preferred machine-readable trace:

```json
{
  "round": 15,
  "date": "2026-06-10",
  "beat": "CPI release shock gate",
  "state_variables": {
    "retail_flow_intensity": {"level": 42, "direction": "down", "evidence": "macro shock overwhelmed PDT posts"},
    "macro_dominance_index": {"level": 86, "direction": "up", "evidence": "CPI/yield branch dominated"},
    "false_signal_risk_index": {"level": 74, "direction": "up", "evidence": "agents misattributed macro move to PDT"}
  }
}
```
