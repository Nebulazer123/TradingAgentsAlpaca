# n8n Setup for TradingAgents

## Status

✓ n8n is running in Docker at `http://localhost:5678`
✓ 9 workflows have been imported (all read-only observer workflows)
✓ Owner account created and ready to log in

## Login Credentials

```
Email:    admin@tradingagents.local
Password: TradingAgents123!
```

**⚠️ Change these credentials in production.** To update, log in to n8n, go to Settings > Users, and change the owner password.

## Workflows Imported

All workflows call the local runner bridge (`http://host.docker.internal:8765/run`) with allowlisted jobs:

1. **hourly supervisor** — `context_snapshot`, `execution_board_review`
2. **paper tournament** — `context_snapshot`, `agent_ledger_summary`
3. **overnight planner** — `context_snapshot`, `creator_workflow_status`, `source_quality_review`, `agent_ledger_summary`
4. **pre-open supervisor** — `pre_open_context_refresh`, `source_quality_review`
5. **post-open supervisor** — `context_snapshot`, `execution_board_review`
6. **pre-close supervisor** — `context_snapshot`, `execution_board_review`
7. **after-close supervisor** — `context_snapshot`, `agent_ledger_summary`
8. **daily report** — `daily_report_preview`
9. **status dashboard/health check** — `context_snapshot`, `process_review`, `automation_health_audit`

Each workflow is a manual-trigger chain that calls one or more jobs via HTTP POST to the bridge.

## Running the Bridge

The runner bridge must be running on your host machine (not in Docker) so n8n can reach it at `host.docker.internal:8765`.

### From PowerShell (Windows):

```powershell
cd C:\Users\Corbin\Documents\Coding projects\TradingAgents-main
.\.venv\Scripts\activate
python -m tradingagents.orchestration.n8n_runner --host 127.0.0.1 --port 8765
```

Or use the convenience script:

```powershell
python start_n8n_runner.py
```

The bridge will start on `http://127.0.0.1:8765` and accept POST requests like:

```json
POST http://127.0.0.1:8765/run
{
  "job": "context_snapshot"
}
```

When called from n8n (in Docker), use `http://host.docker.internal:8765/run`.
The full n8n evaluation dataset endpoint is
`http://host.docker.internal:8765/evaluation-dataset`.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│ n8n (Docker at localhost:5678)                          │
│  - Manual trigger → HTTP Request → Call runner bridge   │
│  - Read-only workflows only                             │
│  - No Alpaca credentials, no shell access              │
└─────────────────────────┬────────────────────────────────┘
                          │
                          │ POST /run {"job": "..."}
                          │ http://host.docker.internal:8765
                          ↓
┌──────────────────────────────────────────────────────────┐
│ Runner Bridge (Host, Python)                             │
│  - Allowlist only: 14 read-only jobs                    │
│  - HTTP POST → validate job name → execute locally     │
│  - Returns JSON result to n8n                           │
└─────────────────────────┬────────────────────────────────┘
                          │
                          ↓
┌──────────────────────────────────────────────────────────┐
│ TradingAgents (Python on Host)                           │
│  - Run the requested allowlisted job                    │
│  - Write results to results/_context/ or results/      │
│  - No order submission from n8n workflows              │
└──────────────────────────────────────────────────────────┘
```

## Testing a Workflow

1. **Access n8n:**
   
   - Open http://localhost:5678
   - Log in with the credentials above

2. **Ensure the bridge is running:**
   
   - On your host, start the bridge (see "Running the Bridge" above)
   - Test connectivity: `curl http://127.0.0.1:8765/health`
   - Should return `{"status": "ok"}`

3. **Trigger a workflow:**
   
   - In n8n, open any workflow (e.g., "status dashboard/health check")
   - Click "Test" or the play button
   - The workflow will POST to the bridge and call the jobs in sequence
   - Results appear in the n8n debug panel

4. **Common issues:**
   
   - **Bridge not reachable:** Ensure the bridge is running on your host and port 8765 is free
   - **Job failed:** Check the bridge logs and the TradingAgents repo for missing data files (e.g., `results/_context/latest-summary.json`)
   - **No workflows visible:** Log out and log back in, or clear your browser cache

## Next Steps

- **Set up notifications:** In n8n, add a notification node (Slack, email, etc.) to send alerts when flags include blockers or submitted actions
- **Add scheduled triggers:** Replace "Manual Trigger" with a Cron node to run hourly supervisor or daily report on a schedule
- **Expand workflows:** Add more nodes to format the results into a dashboard or report
- **Monitor bridge:** Consider adding a health-check trigger in n8n that periodically tests the bridge connection
- **Secure credentials:** Once in production, use n8n's credential storage for any external service integration (e.g., Slack webhook URLs)

## Files Created

- `setup_n8n.py` — One-time setup script to create owner account and import workflows
- `import_n8n_workflows.py` — Batch workflow importer (used by setup_n8n.py)
- `generate_n8n_workflows.py` — Workflow generator (creates JSON definitions)
- `start_n8n_runner.py` — Convenience script to start the runner bridge
- `N8N_SETUP.md` — This file

## Architecture Notes

This setup follows the "Phase 0" proof-of-concept from the workflow map:

- n8n is an observer/control-plane wrapper only
- All trade logic remains in Python (not n8n)
- n8n calls only allowlisted read-only jobs through the bridge
- No Alpaca credentials in n8n; no submit-capable commands
- Dashboards, notifications, and manual refreshes are the primary use cases

For more details, see `docs/orchestration/n8n-workflow-map.md`.
