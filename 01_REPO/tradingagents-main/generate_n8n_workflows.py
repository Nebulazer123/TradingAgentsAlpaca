#!/usr/bin/env python3
"""
Generate n8n workflow definitions from the workflow map.
These are read-only observer workflows that call the local runner bridge.
"""

import json

# Bridge endpoint (when n8n runs in Docker, this is the host bridge)
RUNNER_HOST = "host.docker.internal"
RUNNER_PORT = 8765
RUNNER_URL = f"http://{RUNNER_HOST}:{RUNNER_PORT}/run"

# Define workflows: each has a name and a list of job calls (in order)
WORKFLOWS = [
    {
        "name": "hourly supervisor",
        "jobs": ["context_snapshot", "execution_board_review"],
        "description": "Show latest supervisor state, blockers, submitted count, BOARD pause status"
    },
    {
        "name": "paper tournament",
        "jobs": ["context_snapshot", "agent_ledger_summary"],
        "description": "Show paper leader, popular strategy scorecards, candidate flags"
    },
    {
        "name": "overnight planner",
        "jobs": ["context_snapshot", "creator_workflow_status", "source_quality_review", "agent_ledger_summary"],
        "description": "Show source freshness, ledger influence, blockers"
    },
    {
        "name": "pre-open supervisor",
        "jobs": ["pre_open_context_refresh", "source_quality_review"],
        "description": "Refresh MiroFish handoff status, show stale data, safety locks"
    },
    {
        "name": "post-open supervisor",
        "jobs": ["context_snapshot", "execution_board_review"],
        "description": "Show submitted actions, abnormal P/L, independence warnings"
    },
    {
        "name": "pre-close supervisor",
        "jobs": ["context_snapshot", "execution_board_review"],
        "description": "Show profit-taking, exposure, unresolved issues"
    },
    {
        "name": "after-close supervisor",
        "jobs": ["context_snapshot", "agent_ledger_summary"],
        "description": "Show what resolved today, labels applied"
    },
    {
        "name": "daily report",
        "jobs": ["daily_report_preview"],
        "description": "Preview/send human-readable report"
    },
    {
        "name": "status dashboard/health check",
        "jobs": ["context_snapshot", "process_review", "automation_health_audit"],
        "description": "Display latest packet paths, open plan count, service status"
    }
]

def build_workflow(workflow_info):
    """Build a single n8n workflow JSON."""
    name = workflow_info["name"]
    jobs = workflow_info["jobs"]
    
    # Build HTTP request nodes for each job
    nodes = [
        {
            "id": "1",
            "name": "Manual Trigger",
            "type": "n8n-nodes-base.manualTrigger",
            "position": [250, 300],
            "typeVersion": 1,
            "parameters": {}
        }
    ]
    
    connections = {"Manual Trigger": []}
    
    # Add an HTTP request node for each job
    for idx, job in enumerate(jobs, start=2):
        node_id = str(idx)
        previous_node = nodes[-1]["name"]
        
        node = {
            "id": node_id,
            "name": f"Call {job}",
            "type": "n8n-nodes-base.httpRequest",
            "position": [250 + idx * 250, 300],
            "typeVersion": 4.1,
            "parameters": {
                "url": RUNNER_URL,
                "method": "POST",
                "contentType": "application/json",
                "specifyBody": "json",
                "jsonBody": json.dumps({"job": job}),
            }
        }
        nodes.append(node)
        
        # Connect previous node to this one
        if previous_node not in connections:
            connections[previous_node] = []
        connections[previous_node].append({
            "node": f"Call {job}",
            "type": "main",
            "index": 0
        })
    
    # Build the workflow object
    workflow = {
        "name": name,
        "active": True,
        "nodes": nodes,
        "connections": connections,
        "settings": {
            "saveDataExecution": "all",
            "saveManualExecutions": True,
            "timezone": "America/New_York"
        },
        "tags": [
            {"id": "tradingagents", "name": "tradingagents"}
        ]
    }
    
    return workflow

def main():
    """Generate all workflows and save to /tmp/n8n_workflows/"""
    import os
    
    output_dir = "/tmp/n8n_workflows"
    os.makedirs(output_dir, exist_ok=True)
    
    for workflow_info in WORKFLOWS:
        workflow = build_workflow(workflow_info)
        filename = workflow_info["name"].replace(" ", "_").replace("/", "_") + ".json"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w') as f:
            json.dump(workflow, f, indent=2)
        
        print(f"Generated: {filename}")
    
    print(f"\nWorkflows saved to {output_dir}")
    print(f"Total: {len(WORKFLOWS)} workflows")

if __name__ == "__main__":
    main()
