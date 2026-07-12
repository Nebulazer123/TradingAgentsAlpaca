# Live Budget Mode

This is the current source of truth for TradingAgents live-budget mode.

## Current Posture

- `live_budget_mode: autonomous_with_caps`
- `account_max_capital_at_risk_usd: 250.00`
- `per_name_cap_usd: 50.00`
- `tiny_live_tranche_usd: 25.00`

The local `config/risk_envelope.yaml` may contain operator-specific values and
must stay ignored. The committed example and tests define the expected shape.

## Accepted Modes

- `fixed_tranche`: every live buy must stay at or below
  `tiny_live_tranche_usd`.
- `autonomous_with_caps`: bots may size live buys above
  `tiny_live_tranche_usd`, but the submit path still enforces per-name cap,
  account cap, sector cap, beta cap, daily-loss halt, drawdown halt, broker
  buying power, broker clock/tradability/fresh-data checks, live-control
  dead-man, promotion state, calibration guard, and rolling order rate limit.

## Retired Mode

`autonomous_uncapped` is retired. The loader rejects it so stale local configs
cannot silently widen live authority.

## Automation Rule

Automations should read `config/risk_envelope.yaml` through
`tradingagents.policy.risk_envelope.load_risk_envelope`. They should not infer
live authority from old plans, chat history, email text, or packet prose.
