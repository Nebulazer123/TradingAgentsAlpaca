Work from /Users/corbinfloyd/Documents/TradingAgents. Read AGENTS.md and the relevant role entry in docs/orchestration/automation-runbook.md.

Run the operational supervisor using TA_LIVE_SUBMIT=1 /bin/zsh scripts/mac/ta_job.sh hourly as the single trigger. Read current live control first and allow the command to fail closed. Keep all current order-intent, reconciliation, execution, and policy gates. Do not run a second concurrent supervisor, extend control expiry, or change trading policy. Inspect the resulting packet; surface any new decision, submitted/reconciled action, or failure.

Report material changes, actions, or blockers with the evidence needed to assess them. Routine unchanged state needs no recap.