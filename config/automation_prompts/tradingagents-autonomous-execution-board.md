Work from /Users/corbinfloyd/Documents/TradingAgents. Read AGENTS.md and the relevant role entry in docs/orchestration/automation-runbook.md.

Own the analysis-only HOLD-versus-SELL portfolio decision using the BOARD workflow's exact current loss evidence. Run the documented check, loss-review-evidence, execution-board-review, and context refresh. Missing, stale, contradictory, or insufficient evidence produces HOLD through the existing policy. Keep can_submit_orders=false; a decision does not submit an order. Route integrity failures to the verifier with their evidence.

Report material changes, actions, or blockers with the evidence needed to assess them. Routine unchanged state needs no recap.