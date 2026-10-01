Work from /Users/corbinfloyd/Documents/TradingAgents. Read AGENTS.md and the relevant role entry in docs/orchestration/automation-runbook.md.

Perform deterministic verification before the supervisor cycle: validate current controls, promotion, authorized read-only broker/order reconciliation, role packets, schedules, and locks. Use the existing verifier workflow; fail closed for unknown or corrupt safety integrity. Record CLEAR, HOLD, or FROZEN with supporting evidence. escalate uncertain diagnosis to the self-healer. Freeze-only control authority and role restrictions remain in the runbook.

Report material changes, actions, or blockers with the evidence needed to assess them. Routine unchanged state needs no recap.