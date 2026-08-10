#!/usr/bin/env python3
"""
Generate and import n8n workflow definitions via the n8n REST API.
"""

import json
import subprocess
import sys

# n8n API endpoint
N8N_API = "http://localhost:5678/api/v1"

# Bridge endpoint
RUNNER_HOST = "host.docker.internal"
RUNNER_PORT = 8765
RUNNER_URL = f"http://{RUNNER_HOST}:{RUNNER_PORT}/run"

# Workflows
WORKFLOWS = [
    {
        "name": "hourly supervisor",
        "jobs": ["context_snapshot", "execution_board_review"],
    },
    {
        "name": "paper tournament",
        "jobs": ["context_snapshot", "agent_ledger_summary"],
    },
    {
        "name": "overnight planner",
        "jobs": ["context_snapshot", "creator_workflow_status", "source_quality_review", "agent_ledger_summary"],
    },
    {
        "name": "pre-open supervisor",
        "jobs": ["pre_open_context_refresh", "source_quality_review"],
    },
    {
        "name": "post-open supervisor",
        "jobs": ["context_snapshot", "execution_board_review"],
    },
    {
        "name": "pre-close supervisor",
        "jobs": ["context_snapshot", "execution_board_review"],
    },
    {
        "name": "after-close supervisor",
        "jobs": ["context_snapshot", "agent_ledger_summary"],
    },
    {
        "name": "daily report",
        "jobs": ["daily_report_preview"],
    },
    {
        "name": "status dashboard/health check",
        "jobs": ["context_snapshot", "process_review", "automation_health_audit"],
    }
]

def build_workflow_nodes(jobs):
    """Build n8n nodes for a workflow."""
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
    
    for idx, job in enumerate(jobs, start=2):
        node_id = str(idx)
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
        connections["Manual Trigger"].append({
            "node": f"Call {job}",
            "type": "main",
            "index": 0
        })
    
    return nodes, connections

def import_workflow(name, jobs):
    """Import a single workflow via n8n API."""
    nodes, connections = build_workflow_nodes(jobs)
    
    payload = {
        "name": name,
        "active": True,
        "nodes": nodes,
        "connections": connections,
        "settings": {
            "saveDataExecution": "all",
            "timezone": "America/New_York"
        }
    }
    
    try:
        # Use curl to POST to n8n API
        curl_cmd = [
            "curl", "-X", "POST",
            f"{N8N_API}/workflows",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload)
        ]
        result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            json.loads(result.stdout)
            print(f"✓ Imported: {name}")
            return True
        else:
            print(f"✗ Failed: {name} - {result.stderr}")
            return False
    except Exception as e:
        print(f"✗ Error importing {name}: {e}")
        return False

def main():
    print(f"n8n API: {N8N_API}")
    print(f"Runner bridge: {RUNNER_URL}\n")
    
    success_count = 0
    for workflow in WORKFLOWS:
        if import_workflow(workflow["name"], workflow["jobs"]):
            success_count += 1
    
    print(f"\nImported {success_count}/{len(WORKFLOWS)} workflows")
    
    if success_count == len(WORKFLOWS):
        print("✓ All workflows imported successfully!")
        return 0
    else:
        print("✗ Some workflows failed to import")
        return 1

if __name__ == "__main__":
    sys.exit(main())
