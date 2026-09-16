import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def test_scheduled_tournament_wrapper_is_explicitly_dry_run():
    wrapper = (ROOT / "scripts" / "mac" / "ta_job.sh").read_text(encoding="utf-8")

    tournament_block = wrapper.split("  tournament)\n", maxsplit=1)[1].split("    ;;", maxsplit=1)[0]

    assert 'run "$PY" -m cli.main alpaca paper-tournament run --all --dry-run --json-output' in tournament_block


def _run_wrapper(tmp_path, job, submit_flag):
    """Run the real wrapper with a no-network, recording-only Python substitute."""
    if not Path('/bin/zsh').is_file():
        pytest.skip('Mac wrapper execution requires zsh')
    fake_python = tmp_path / '.venv/bin/python'
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TA_TEST_TRACE"\n', encoding='utf-8')
    fake_python.chmod(0o700)
    trace = tmp_path / 'commands.txt'
    completed = subprocess.run(
        ['/bin/zsh', str(ROOT / 'scripts/mac/ta_job.sh'), job],
        cwd=tmp_path,
        env={'PATH': os.defpath, 'TA_REPO': str(tmp_path),
             'TA_LIVE_SUBMIT': submit_flag, 'TA_TEST_TRACE': str(trace)},
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return trace.read_text(encoding='utf-8').splitlines()


@pytest.mark.parametrize(('job', 'submit_flag'), [('hourly', '0'), ('preopen', '0'), ('preopen', '1')])
def test_analysis_wrapper_never_submits_or_drains_queued_notifications(tmp_path, job, submit_flag):
    commands = _run_wrapper(tmp_path, job, submit_flag)

    supervisor = [command for command in commands if 'supervise-hourly' in command]
    assert len(supervisor) == 1
    assert '--dry-run' in supervisor[0]
    assert '--submit-actions' not in supervisor[0]
    assert not any('deliver_outbox.py' in command for command in commands)
    assert not (tmp_path / f'results/mac_automation/locks/{job}.lock').exists()


def test_explicit_hourly_action_mode_keeps_the_guarded_action_route_and_delivery(tmp_path):
    commands = _run_wrapper(tmp_path, 'hourly', '1')

    supervisor = [command for command in commands if 'supervise-hourly' in command]
    assert len(supervisor) == 1 and '--submit-actions' in supervisor[0]
    assert sum('deliver_outbox.py' in command for command in commands) == 1


def test_explicit_outbox_job_remains_available(tmp_path):
    commands = _run_wrapper(tmp_path, 'deliver-outbox', '0')

    assert commands == ['scripts/mac/deliver_outbox.py']


@pytest.mark.parametrize('arguments', [[], ['--install'], ['--uninstall'], ['--force'], ['--help']])
def test_legacy_installer_is_non_mutating_and_names_the_current_contract(tmp_path, arguments):
    installer = ROOT / 'scripts/mac/install_launchd.sh'
    source = installer.read_text(encoding='utf-8')
    # Fail before executing old source: never test the historical installer
    # against the user's real LaunchAgents directory or launchd session.
    assert 'retired' in source.lower()
    assert 'write_plist' not in source
    assert 'launchctl ' not in source
    assert 'mkdir ' not in source
    assert 'rm ' not in source
    if not Path('/bin/zsh').is_file():
        pytest.skip('Mac installer execution requires zsh')
    completed = subprocess.run(
        ['/bin/zsh', str(installer), *arguments], cwd=tmp_path,
        env={'PATH': os.defpath}, capture_output=True, text=True, timeout=10, check=False,
    )
    assert completed.returncode == (0 if arguments == ['--help'] else 2)
    assert 'config/automation_schedule_contract.json' in completed.stdout + completed.stderr
    assert list(tmp_path.iterdir()) == []
