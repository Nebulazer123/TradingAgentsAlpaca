# Operator Attestation: Manual Alpaca NFLX Sale

Recorded on 2026-07-28 from the operator's direct statement.

## Attestation

The operator states that they manually logged in to Alpaca and made the Netflix
(`NFLX`) sale recorded by Alpaca on 2026-07-27. The sale was a human action in
the Alpaca interface, not an order submitted by TradingAgents, the market
supervisor, the Execution BOARD, the Safety Sentinel, the self-healer, or n8n.

The broker record identified in the Execution BOARD integrity addendum is:

- Symbol: `NFLX`
- Side: `sell`
- Quantity: `0.320946047`
- Status: `filled`
- Submitted at: `2026-07-27T18:46:48.172614025Z`
- Filled at: `2026-07-27T18:46:48.183994596Z`
- Broker order ID: `e5d06403-6ed5-4159-97f2-d45b9d0585aa`
- Client order ID: `19c4b727-f643-4dd6-972c-0dcd9a768a89`

## Evidence Link

The original machine-observed integrity finding remains in:

`results/execution_board/execution-board-integrity-addendum-20260727-195542.json`

That packet correctly reported that the local TradingAgents execution history
did not contain an intent, submission, reconciliation, or fill record for this
broker order.

## Safety Effect

This attestation identifies the submitting authority as the human operator. It
does not rewrite generated result packets, fabricate a TradingAgents execution
record, refresh or unfreeze `results/policy/live_control.json`, reconcile stale
promotion or scheduler evidence, or authorize replay of any NFLX sell intent.
Live trading remains fail-closed until the remaining integrity requirements are
independently verified and any re-arm is explicitly authorized.
