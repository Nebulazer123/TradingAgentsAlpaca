"""Run the frozen source gate with file-backed output and durable exit receipts.

Use --detach for a long gate: its worker and check output have no client pipe.
This proves local source only, and never enables a schedule or trading control.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


def _now():
    return datetime.now(UTC).isoformat()


def _persist(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as output:
        json.dump(value, output, indent=2, allow_nan=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def _identity(root):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()

    return {"head": git("rev-parse", "HEAD"), "status": git("status", "--porcelain")}


def _environment(root):
    environment = dict(os.environ, TA_LIVE_SUBMIT="0", PYTHONPATH=str(root), PYTHONUNBUFFERED="1")
    tree = ast.parse((root / "tests/conftest.py").read_text())
    key_names = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "_API_KEY_ENV_VARS" for target in node.targets))
    for name in key_names:
        environment[name] = "placeholder"
    return environment


def run_checks(*, root, output, candidate, commands, environment):
    """No stdout writes: a disconnected caller cannot invalidate completed checks."""
    receipt_path = output / "receipt.json"
    if receipt_path.exists():
        raise FileExistsError("preserve the previous gate receipt; use a fresh output directory")
    receipt = {
        "schema_version": "source_gate_run/v1",
        "candidate": candidate,
        "cwd": str(root),
        "started_at": _now(),
        "runner_pid": os.getpid(),
        "status": "running",
        "checks": [],
        "commands": [{"name": name, "command": command} for name, command in commands],
        "current_check": None,
        "process_pid": None,
        "source_changed": None,
        "exit_code": None,
        "live_model_execution_authorized": False,
        "operational_or_economic_qualification_claimed": False,
    }
    _persist(receipt_path, receipt)
    process = None
    try:
        if _identity(root) != {"head": candidate, "status": ""}:
            raise ValueError("gate requires the exact clean frozen candidate")
        for name, command in commands:
            receipt["current_check"] = name
            _persist(receipt_path, receipt)
            started = time.monotonic()
            log = output / f"{name}.log"
            with log.open("xb") as stream:
                process = subprocess.Popen(command, cwd=root, env=environment, stdout=stream, stderr=subprocess.STDOUT)
                receipt["process_pid"] = process.pid
                _persist(receipt_path, receipt)
                code = process.wait()
                stream.flush()
                os.fsync(stream.fileno())
            process = None
            receipt["checks"].append({"name": name, "command": command, "exit_code": code, "elapsed_seconds": round(time.monotonic() - started, 3), "log": str(log)})
            receipt["process_pid"] = None
            receipt["exit_code"] = code
            receipt["source_changed"] = _identity(root) != {"head": candidate, "status": ""}
            _persist(receipt_path, receipt)
            if code or receipt["source_changed"]:
                receipt["status"] = "failed"
                receipt["exit_code"] = code or 1
                break
        else:
            receipt["status"] = "passed"
            receipt["exit_code"] = 0
    except (Exception, KeyboardInterrupt) as exc:
        receipt["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "runner_error"
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        receipt["exit_code"] = 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        receipt["process_pid"] = None
        receipt["finished_at"] = _now()
        _persist(receipt_path, receipt)
    return receipt["exit_code"]


def _commands(python, output):
    return [
        ("ruff", [str(Path(python).parent / "ruff"), "check", "cli", "tradingagents", "scripts", "tests"]),
        ("compileall", [python, "-m", "compileall", "-q", "cli", "tradingagents", "scripts"]),
        ("lock", ["uv", "lock", "--check", "--offline", "--no-progress", "--python", python]),
        ("shell", ["zsh", "-n", "scripts/mac/ta_job.sh"]),
        ("retired_installer_syntax", ["zsh", "-n", "scripts/mac/install_launchd.sh"]),
        ("diff", ["git", "diff", "--check"]),
        ("pytest", [python, "-m", "pytest", "-q", "--durations=15", f"--junitxml={output / 'pytest.xml'}"]),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--detach", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.umask(0o077)
    root, output = args.root.resolve(), args.output.resolve()
    if not args.worker:
        if _identity(root) != {"head": args.candidate, "status": ""}:
            parser.error("gate requires the exact clean frozen candidate")
        output.mkdir(parents=True, mode=0o700, exist_ok=False)
    if args.detach:
        command = [args.python, str(Path(__file__).resolve()), "--root", str(root), "--output", str(output), "--candidate", args.candidate, "--python", args.python, "--worker"]
        with (output / "runner.log").open("xb") as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
        _persist(output / "launch.json", {"candidate": args.candidate, "pid": process.pid, "started_at": _now(), "receipt": str(output / "receipt.json")})
        return 0

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt("worker interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    return run_checks(root=root, output=output, candidate=args.candidate, commands=_commands(args.python, output), environment=_environment(root))


if __name__ == "__main__":
    raise SystemExit(main())
