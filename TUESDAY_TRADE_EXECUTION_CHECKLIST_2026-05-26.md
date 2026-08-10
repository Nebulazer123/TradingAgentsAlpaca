# Tuesday Trade Execution Checklist

Date prepared: 2026-05-25  
Execution window: Tuesday 2026-05-26 through Friday 2026-05-29  
Broker: Fidelity  
Budget cap: about $1,000  
Share type: whole shares only

## Current Baseline

Latest available regular-market prices are still from Friday 2026-05-22 because U.S. cash equities are closed Monday for Memorial Day.

- GOOGL: $382.97
- NVDA: $215.33
- QQQ: $717.54

The plan is not valid for blind execution until Tuesday premarket/open confirms the setup.

## Tuesday Pre-Open Check

Before placing an order, check:

- GOOGL premarket bid/ask and last price
- NVDA premarket bid/ask and last price
- QQQ or Nasdaq futures tone
- Fresh GOOGL news, especially EU DMA fine details
- Fresh NVDA/TSM/AMD AI infrastructure or China/export-control news

## Decision Filter

- If GOOGL is $382-$386 and stable, Ticket 1 remains valid.
- If GOOGL is below $382 without worsening legal news, lower Ticket 1 to the current ask or below; do not panic-buy.
- If GOOGL is above $392-$397, skip Ticket 1 and let pullback orders work.
- If GOOGL is selling off hard on new EU details, pause Ticket 1 and reassess.
- If NVDA is not near $212.25, do not chase it.

## Ticket 1: GOOGL Starter

Use only after the pre-open check passes.

- Action: Buy
- Symbol: GOOGL
- Quantity: 1 share
- Order type: Limit
- Limit price: $383.50, or lower if premarket ask is lower
- Time in force: On the Open if Fidelity accepts it; otherwise Day
- Condition: None

Intent: Get one GOOGL share near Friday close without chasing a gap.

## Ticket 2: GOOGL Pullback

- Action: Buy
- Symbol: GOOGL
- Quantity: 1 share
- Order type: Limit
- Limit price: $378.25
- Time in force: GTC
- Condition: None
- Manual rule: cancel Friday 2026-05-29 if unfilled

Intent: Buy the S2/support pullback area.

## Ticket 3: NVDA Pullback Kicker

- Action: Buy
- Symbol: NVDA
- Quantity: 1 share
- Order type: Limit
- Limit price: $212.25
- Time in force: GTC
- Condition: None
- Manual rule: cancel Friday 2026-05-29 if unfilled

Intent: Add NVDA only if it pulls back near support.

## Max Spend

If all three tickets fill:

- GOOGL starter: $383.50
- GOOGL pullback: $378.25
- NVDA pullback: $212.25
- Maximum planned spend: $974.00

Unused cash is acceptable.

## Do Not Use

- No market orders for entry
- No stop-loss entries
- No stop-limit entries
- No trailing-stop entries
- No All or None condition for these 1-share tickets
- No chase above the GOOGL gap-up caution zone

## Automation

A Codex thread heartbeat named `Tuesday Pre-Open Trade Check` is scheduled for Tuesday 2026-05-26 at 6:00 a.m. Central time to rerun the live checks and return updated ticket suggestions.
