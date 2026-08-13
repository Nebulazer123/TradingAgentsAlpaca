# Reachable Production Evidence Repair

Commit: `1ff953a`

## Result

The autonomous loss BOARD can now reach a decision-only SELL from complete,
current, configured-route-shaped source packets, while the normal incomplete
TSM-shaped evidence remains a HOLD. No change enables order submission.

## Evidence admission

- Market context accepts Alpaca latest-trade packet fields for the symbol, SPY,
  QQQ, and XLK, then derives numeric relative values.
- Company news accepts a current Finnhub company-news record only when its
  structured fields deterministically classify an adverse company event.
- Earnings/guidance accepts transcript content only when it contains a current,
  numeric guidance-cut fact. A SEC submissions index alone remains insufficient.
- Old fabricated `market_context` / `company_event` test payloads no longer
  create authority material.

## Integrity and authority

- Source capture and normalized evidence publication use descriptor-relative,
  no-follow file operations and immutable collision checks.
- The supervisor accepts an exit-reason source only as `{packet_id,path,sha256}`.
- `thesis_invalidated` requires the dedicated normalized invalidator event;
  generic prose, earnings misses, or impairment labels cannot infer it.
- Authenticated BOARD compact output uses the exact scalar-only
  `autonomous_loss_board_sidecar_v1` contract.

## Verification

Focused tests: `78 passed, 99 deselected`.

Ruff passed on every owned source and test file. `git diff --check` passed.

## Scope boundary

The decision remains `analysis_only=true`, `execution_authority=none`, and
`can_submit_orders=false`. Live control was not read, altered, or unfrozen.
