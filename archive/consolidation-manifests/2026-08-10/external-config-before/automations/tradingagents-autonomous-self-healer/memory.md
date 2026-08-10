# TradingAgents Autonomous Self-Healer Memory

## Run 2026-07-28T05:21:46Z follow-up verification

- Final status: FROZEN / ESCALATED; observer/recovery plane healthy.
- Re-read all 10 TradingAgents automation TOMLs after the overnight transition:
  wake/sleep controllers and overnight research ACTIVE; seven market-day jobs
  PAUSED as intended. The sentinel is already `gpt-5.6-sol` at high reasoning.
- Preserved `results/policy/live_control.json` unchanged at SHA-256
  `45a11fe65c8848b8f58127e9c23b1a5b04ddceb0921a1e95fe0b7828b7033e0b`.
  The human attestation identifies the NFLX submitter, but durable external-fill
  reconciliation, promotion provenance, and pre-boundary scheduler proof remain
  unresolved; no re-arm or extra freeze was performed.
- Alpaca live/paper accounts were ACTIVE. Fresh probe
  `results/preopen_validation/self_healer_probe/preopen-validation-20260728-051450.json`
  reported 0 live and 0 paper open orders, 0 submissions, readable positions,
  and only the frozen-control warning plus a closed-market skip.
- Final service verification: runner `/health` and `/jobs` HTTP 200, 24 jobs,
  0 submit-capable jobs; n8n `/healthz` and `/healthz/readiness` HTTP 200;
  Docker container `tradingagents-main-n8n-1` up. No lock files or order-capable
  TradingAgents processes remained.
- Required handoff:
  `results/self_heal/self-heal-handoff-20260728-052057.json` (7 deduplicated
  triggers, 0 active). Required safe plan:
  `results/self_heal/plans/self-heal-plan-20260728-052059.json`
  (`escalation_required`, 1 order-adjacent escalation, 0 actions executed,
  0 verification failures). Context snapshot refreshed under `results/_context/`.
- No broker action, live-control edit, strategy/risk/promotion change, code edit,
  lock removal, service restart, or automation-status change was performed in
  this follow-up.

## Run 2026-07-28T05:14:29Z

- Final status: REPAIRED + FROZEN / ESCALATED.
- Current TradingAgents schedule posture after the sleep controller: wake and
  sleep controllers ACTIVE; overnight research ACTIVE; seven market-day jobs
  PAUSED. Ten TOMLs were present.
- Safely repaired
  `tradingagents-autonomous-safety-sentinel/automation.toml` through the Codex
  automation API by changing only `reasoning_effort` from `medium` to `high`;
  its PAUSED overnight status and all other fields were preserved.
- The local n8n runner stayed healthy on `127.0.0.1:8765` with 24 allowlisted
  jobs and zero submit-capable jobs. Docker Desktop was initially stopped and
  its first restart was blocked while repairing a privileged helper. Docker
  later completed startup and restored the existing n8n container. Final
  `/healthz` and `/healthz/readiness` checks both returned `{"status":"ok"}`.
- Fresh Alpaca checks showed live and paper accounts ACTIVE with zero open
  orders. Probe packet:
  `results/preopen_validation/self_heal_probe/preopen-validation-20260728-051227.json`.
- No files existed under `results/mac_automation/locks`.
- Live control remained frozen and was not edited by this run. Final SHA-256:
  `45a11fe65c8848b8f58127e9c23b1a5b04ddceb0921a1e95fe0b7828b7033e0b`.
  The current reason records an NFLX fill that lacked TradingAgents provenance.
- The operator then attested that they personally logged in to Alpaca and made
  the NFLX sale. Added
  `docs/policy/manual-alpaca-nflx-sale-attestation-2026-07-27.md` to identify
  the human submitting authority without rewriting generated packets or
  changing live authority.
- Required handoff:
  `results/self_heal/self-heal-handoff-20260728-051040.json`.
- Required safe plan:
  `results/self_heal/plans/self-heal-plan-20260728-051127.json`; two
  context-only actions executed and verified, zero verification failures, one
  order-adjacent escalation skipped.
- Final compact refresh wrote `results/_context/context-manifest.json` and the
  other standard `_context` artifacts. Latest self-heal plan at close:
  `results/self_heal/plans/self-heal-plan-20260728-051212.json`.
- Fresh automation health:
  `results/automation_health/automation-health-audit-20260728-051157.json`;
  10 automations, 9 OK, overnight research stale, zero missing/late/duplicate,
  zero submitted orders.
- BOARD evidence:
  `results/execution_board/execution-board-integrity-addendum-20260727-195542.json`.
  The human attestation narrows order provenance, but promotion provenance,
  historical scheduler gaps, stale overnight evidence, and durable
  external-fill reconciliation remain unresolved. Do not re-arm live control.
