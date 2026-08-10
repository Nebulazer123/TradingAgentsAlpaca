# MiroFish Causal Attribution Plan

Generated: 2026-06-03

Purpose: force the final report to separate likely causes instead of producing one blended market story.

## Cause Taxonomy

Every major simulated social or market move must be tagged using this taxonomy:

- PDT/intraday-margin narrative
- broker rollout/friction
- AI-agent/bot adoption
- macro/labor/inflation/rates
- Treasury auctions/liquidity
- oil/geopolitical shock
- AI/semiconductor/capex narratives
- options expiry/gamma/IV
- institutional/liquidity-provider reaction
- random/noise/normal volatility

## Required Ledger Fields

```json
{
  "round": 15,
  "move_or_social_shift": "SPY/QQQ 0DTE chatter spikes after CPI",
  "primary_cause": "macro/labor/inflation/rates",
  "secondary_causes": ["options expiry/gamma/IV", "PDT/intraday-margin narrative"],
  "confidence": 72,
  "simulation_evidence": ["agents cited CPI/yields before PDT", "market-maker actors discussed spread widening"],
  "real_world_validation_data_needed": ["CPI surprise", "Treasury yields", "SPY/QQQ options volume and IV", "broker support chatter"],
  "false_attribution_risk": "High if social posts credit June 4 while macro data explains the timing."
}
```

## Control Branch

The control branch is explicit:

No meaningful retail-flow effect: social chatter rises, but broker implementation is fragmented, real-time controls block many attempts, macro dominates, and realized flow does not confirm the narrative.

Every scenario branch must be compared against this control. The report must not automatically credit June 4 for moves that macro data, oil, yields, AI earnings, options expiry, or institutional/liquidity response can explain.

## Validation Discipline

Each branch must include:

```json
{
  "signal": "",
  "expected_if_branch_true": "",
  "expected_if_branch_false": "",
  "data_to_check": "",
  "confidence_update": "",
  "false_positive_warning": ""
}
```

Required validation areas:

- SPY/QQQ/0DTE attention and volume
- HOOD/BULL relative performance
- broker support/UI confusion
- order rejection or buying-power confusion
- options volume/IV/open-interest changes
- Treasury auction/yield reaction
- CPI/PPI/jobs macro override
- oil/geopolitical shock
- AI/semi narrative persistence or failure
- small-cap/meme spillover
- bot-correlation/copycat behavior
- institutional/liquidity absorption or fading of novice flow
