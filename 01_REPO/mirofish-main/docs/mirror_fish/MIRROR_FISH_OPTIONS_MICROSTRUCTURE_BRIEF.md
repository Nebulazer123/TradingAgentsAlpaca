# MiroFish Options And Microstructure Brief

Generated: 2026-06-03

Purpose: improve 0DTE/options realism without turning MiroFish into an order-book or options-flow engine.

## Simulation Boundary

MiroFish should simulate attention, misunderstanding, narrative spread, and institutional/liquidity response. It should not calculate exact Greeks, predict option prices, validate full options flow, or produce trade recommendations.

## Required Mechanics

- 0DTE behavior: agents can treat same-day SPY/QQQ options as the fast expression of a narrative, but the report must distinguish attention from confirmed flow.
- Assignment and exercise confusion: SPY/QQQ/TSLA/AAPL equity and ETF options are physically settled; some novices should misunderstand assignment, exercise, buying power, and delivery.
- Index-option contrast: cash-settled index options such as SPX/XSP-style products behave differently from physically settled equity/ETF options.
- Dealer gamma and hedging response: market-maker and volatility-desk actors should discuss whether novice clustering changes hedging pressure, spreads, and liquidity.
- IV expansion/crush: social attention may lift IV into events, then crush after macro or earnings catalysts.
- Open interest and volume confirmation: final report should require real OI/volume checks before treating social chatter as capital flow.
- Bid/ask spread widening: crowded novice options demand may widen spreads, especially under macro stress.
- Liquidity thinning: long-end auctions, CPI/PPI, and oil shocks can thin liquidity independent of PDT effects.
- Weekly options expirations: June 5 and June 12 are explicit expiry beats.

## Required Signal Separation

The final report must separate:

- retail attention signal
- actual options-flow signal
- IV/gamma/liquidity signal
- market-maker response
- false social signal

## False-Positive Warnings

- A viral 0DTE post is not proof of aggregate options volume.
- High IV can come from CPI/PPI, earnings, oil/geopolitics, or broad risk, not only PDT-rule attention.
- SPY/QQQ index-level moves need macro and institutional checks before being assigned to retail rule changes.
- Broker rejections can reduce realized flow even when attention rises.
