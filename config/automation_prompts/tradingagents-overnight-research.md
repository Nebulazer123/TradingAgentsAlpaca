Work from /Users/corbinfloyd/Documents/TradingAgents. Read AGENTS.md and the relevant role entry in docs/orchestration/automation-runbook.md.

Run analysis-only overnight research using TA_LIVE_SUBMIT=0 /bin/zsh scripts/mac/ta_job.sh overnight. Inspect the newest packet and diagnose any failing stage from its log. Use deterministic tooling for packet mechanics; the configured research/model workflow owns synthesis and its authorized budget. Do not edit trading configuration or submit orders.

Report material changes, actions, or blockers with the evidence needed to assess them. Routine unchanged state needs no recap.