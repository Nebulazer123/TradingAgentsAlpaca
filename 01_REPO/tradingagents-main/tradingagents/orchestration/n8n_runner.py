"""Localhost n8n bridge for allowlisted TradingAgents jobs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from tradingagents.orchestration.n8n_policy import (
    DEFAULT_ALLOWLIST_PATH,
    REPO_ROOT,
    N8NJob,
    get_n8n_job,
    load_n8n_allowlist,
)


def _repo_python(repo_root: Path) -> str:
    for candidate in (
        repo_root / ".venv" / "Scripts" / "python.exe",
        repo_root / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _resolve_command(command: list[str], *, repo_root: Path) -> list[str]:
    if command and command[0].lower() in {"python", "python.exe", "py"}:
        return [_repo_python(repo_root), *command[1:]]
    return command


def _tail(text: str, *, max_lines: int = 12, max_chars: int = 4000) -> str:
    lines = text.splitlines()
    tail = "\n".join(lines[-max_lines:])
    return tail[-max_chars:]


def _job_payload(job: N8NJob, *, include_commands: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": job.name,
        "description": job.description,
        "timeout_seconds": job.timeout_seconds,
        "submit_capable": job.submit_capable,
        "compact_output_only": job.compact_output_only,
        "command_count": len(job.commands),
    }
    if include_commands:
        payload["commands"] = job.commands
    return payload


def list_jobs(
    *,
    allowlist_path: str | Path | None = None,
    include_commands: bool = True,
) -> dict[str, Any]:
    jobs = load_n8n_allowlist(allowlist_path)
    return {
        "schema_version": 1,
        "status": "ok",
        "allowlist_path": str(Path(allowlist_path) if allowlist_path else DEFAULT_ALLOWLIST_PATH),
        "job_count": len(jobs),
        "submit_capable_count": sum(1 for job in jobs.values() if job.submit_capable),
        "jobs": [
            _job_payload(job, include_commands=include_commands)
            for job in sorted(jobs.values(), key=lambda item: item.name)
        ],
    }


def run_job(
    job_name: str,
    *,
    allowlist_path: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root else REPO_ROOT
    job = get_n8n_job(job_name, allowlist_path)
    command_results: list[dict[str, Any]] = []
    overall_returncode = 0

    for index, command in enumerate(job.commands, start=1):
        resolved = _resolve_command(command, repo_root=root)
        try:
            completed = subprocess.run(
                resolved,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=job.timeout_seconds,
                check=False,
            )
            result = {
                "index": index,
                "command": command,
                "resolved_command": resolved,
                "returncode": completed.returncode,
                "stdout_tail": _tail(completed.stdout),
                "stderr_tail": _tail(completed.stderr),
            }
            if completed.returncode != 0 and overall_returncode == 0:
                overall_returncode = completed.returncode
        except subprocess.TimeoutExpired as exc:
            result = {
                "index": index,
                "command": command,
                "resolved_command": resolved,
                "returncode": 124,
                "stdout_tail": _tail(exc.stdout or ""),
                "stderr_tail": _tail(exc.stderr or "timed out"),
                "timed_out": True,
            }
            overall_returncode = 124
        command_results.append(result)
        if result["returncode"] != 0:
            break

    return {
        "schema_version": 1,
        "status": "ok" if overall_returncode == 0 else "failed",
        "job": _job_payload(job, include_commands=False),
        "returncode": overall_returncode,
        "submit_capable": job.submit_capable,
        "can_submit_orders": job.submit_capable,
        "compact_output_only": job.compact_output_only,
        "commands": command_results,
    }


def _read_json_body(handler: BaseHTTPRequestHandler, *, max_bytes: int = 64_000) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or "0")
    if length > max_bytes:
        raise ValueError(f"request body too large: {length} bytes")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload


def _write_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class _N8NHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
        if self.path == "/health":
            _write_json(self, 200, {"status": "ok", "service": "tradingagents-n8n-runner"})
            return
        if self.path == "/jobs":
            try:
                _write_json(self, 200, list_jobs())
            except Exception as exc:  # noqa: BLE001 - surface bridge failure as JSON.
                _write_json(self, 500, {"status": "error", "error": str(exc)})
            return
        _write_json(self, 404, {"status": "not_found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API.
        if self.path != "/run":
            _write_json(self, 404, {"status": "not_found"})
            return
        try:
            payload = _read_json_body(self)
            job_name = str(payload.get("job") or payload.get("job_name") or "")
            if not job_name:
                _write_json(self, 400, {"status": "error", "error": "missing job"})
                return
            result = run_job(job_name)
        except KeyError as exc:
            _write_json(self, 400, {"status": "not_allowlisted", "error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - bridge callers need JSON.
            _write_json(self, 500, {"status": "error", "error": str(exc)})
            return
        _write_json(self, 200 if result["returncode"] == 0 else 500, result)


def _serve(host: str, port: int) -> int:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("n8n runner may only bind to localhost by default")
    server = ThreadingHTTPServer((host, port), _N8NHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allowlist", default=str(DEFAULT_ALLOWLIST_PATH))
    parser.add_argument("--list-jobs", action="store_true")
    parser.add_argument("--run-job")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    try:
        if args.list_jobs:
            payload = list_jobs(allowlist_path=args.allowlist)
            if args.json_output:
                print(json.dumps(payload, indent=2))
            else:
                for job in payload["jobs"]:
                    print(f"{job['name']}: {job['description']}")
            return 0
        if args.run_job:
            payload = run_job(args.run_job, allowlist_path=args.allowlist)
            if args.json_output:
                print(json.dumps(payload, indent=2))
            else:
                print(f"{payload['job']['name']}: {payload['status']}")
            return int(payload["returncode"])
        if args.serve:
            return _serve(args.host, args.port)
    except Exception as exc:  # noqa: BLE001 - CLI should fail with a concise error.
        if args.json_output:
            print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

