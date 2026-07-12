import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tradingagents.orchestration.n8n_policy import load_n8n_allowlist
from tradingagents.orchestration.n8n_runner import _N8NHandler, list_jobs, main, run_job


def test_n8n_policy_loads_context_snapshot_job():
    jobs = load_n8n_allowlist()
    job = jobs["context_snapshot"]

    assert job.name == "context_snapshot"
    assert job.submit_capable is False
    assert job.compact_output_only is True
    assert ["python", "scripts/automation_context_snapshot.py", "--write"] in job.commands


def test_n8n_runner_lists_allowlisted_jobs_without_running_them(capsys):
    result = list_jobs()

    by_name = {job["name"]: job for job in result["jobs"]}
    assert result["schema_version"] == 1
    assert result["status"] == "ok"
    assert "context_snapshot" in by_name
    assert "hourly_supervisor_dry_run_preview" in by_name
    assert "n8n_evaluation_dataset" in by_name
    assert by_name["context_snapshot"]["submit_capable"] is False
    assert by_name["context_snapshot"]["compact_output_only"] is True
    assert by_name["context_snapshot"]["command_count"] == 1

    exit_code = main(["--list-jobs", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["job_count"] == len(payload["jobs"])
    assert any(job["name"] == "context_snapshot" for job in payload["jobs"])
    assert any(job["name"] == "self_heal_handoff" for job in payload["jobs"])


def test_n8n_allowlist_jobs_are_non_submit_compact_and_timed():
    jobs = load_n8n_allowlist()

    assert jobs
    for job in jobs.values():
        assert job.submit_capable is False
        assert job.compact_output_only is True
        assert job.timeout_seconds > 0
        for command in job.commands:
            assert "--submit-actions" not in command


def test_n8n_policy_rejects_non_submit_job_with_submit_actions(tmp_path):
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(
        json.dumps(
            {
                "jobs": {
                    "bad": {
                        "description": "unsafe",
                        "commands": [
                            [
                                "python",
                                "-m",
                                "cli.main",
                                "alpaca",
                                "supervise-hourly",
                                "--submit-actions",
                            ]
                        ],
                        "submit_capable": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="--submit-actions"):
        load_n8n_allowlist(allowlist)


def test_n8n_runner_runs_temp_allowlisted_job(tmp_path):
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(
        json.dumps(
            {
                "jobs": {
                    "echo_json": {
                        "description": "safe test command",
                        "commands": [
                            [
                                "python",
                                "-c",
                                "import json; print(json.dumps({'ok': True}))",
                            ]
                        ],
                        "timeout_seconds": 10,
                        "submit_capable": False,
                        "compact_output_only": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_job("echo_json", allowlist_path=allowlist, repo_root=tmp_path)

    assert result["status"] == "ok"
    assert result["returncode"] == 0
    assert result["submit_capable"] is False
    assert '"ok": true' in result["commands"][0]["stdout_tail"].lower()


def test_n8n_runner_serves_jobs_over_http():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _N8NHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/jobs"
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert payload["status"] == "ok"
    assert payload["job_count"] >= 1
    assert any(job["name"] == "context_snapshot" for job in payload["jobs"])
