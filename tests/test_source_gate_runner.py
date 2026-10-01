"""Regression checks for disconnected output and durable gate failures."""

import json
import os
import subprocess
import sys

import pytest

from scripts.run_source_gate import run_checks


@pytest.fixture
def frozen_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    for command in [["git", "init", "-q"], ["git", "-c", "user.name=Gate Test", "-c", "user.email=gate@example.invalid", "commit", "--allow-empty", "-qm", "fixture"]]:
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    output = tmp_path / "output"
    output.mkdir()
    return root, head, output


def test_completed_receipt_survives_closed_caller_output(frozen_repo):
    root, head, output = frozen_repo
    # The worker's stdout is literally closed. Its noisy child's output must go
    # to a durable file, and a successful exit must still be recorded.
    code = """import os
from pathlib import Path
from scripts.run_source_gate import run_checks
os.close(1)
raise SystemExit(run_checks(root=Path(__import__('sys').argv[1]), output=Path(__import__('sys').argv[2]), candidate=__import__('sys').argv[3], commands=[('noisy', [__import__('sys').executable, '-c', 'print(\"durable result\")'])], environment=dict(os.environ)))
"""
    result = subprocess.run([sys.executable, "-c", code, str(root), str(output), head], cwd=os.getcwd(), capture_output=True)
    assert result.returncode == 0, result.stderr
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["status"] == "passed" and receipt["exit_code"] == 0
    assert (output / "noisy.log").read_text() == "durable result\n"


@pytest.mark.parametrize(
    "command,status,exit_code",
    [
        ([sys.executable, "-c", "raise SystemExit(9)"], "failed", 9),
        (["/nonexistent/tradingagents-gate-command"], "runner_error", 1),
        ([sys.executable, "-c", "from pathlib import Path; Path('new-source').write_text('changed')"], "failed", 1),
    ],
)
def test_failure_or_changed_candidate_is_terminal_and_does_not_run_next_check(frozen_repo, command, status, exit_code):
    root, head, output = frozen_repo
    code = run_checks(root=root, output=output, candidate=head, commands=[("first", command), ("must_not_run", [sys.executable, "-c", "print('unexpected')"])], environment=dict(os.environ))
    receipt = json.loads((output / "receipt.json").read_text())
    assert code == exit_code and receipt["status"] == status and receipt["finished_at"]
    assert not (output / "must_not_run.log").exists()
    assert receipt["process_pid"] is None


def test_previous_receipt_cannot_be_overwritten(frozen_repo):
    root, head, output = frozen_repo
    receipt = output / "receipt.json"
    receipt.write_bytes(b'{"status":"old failure"}\n')
    with pytest.raises(FileExistsError, match="preserve"):
        run_checks(root=root, output=output, candidate=head, commands=[], environment=dict(os.environ))
    assert receipt.read_bytes() == b'{"status":"old failure"}\n'
