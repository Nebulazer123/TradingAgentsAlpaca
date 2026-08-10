import json

from app.services.simulation_ipc import CommandStatus, IPCResponse
from app.services.simulation_runner import SimulationRunner


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _reset_runner(monkeypatch, tmp_path):
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    SimulationRunner._run_states.clear()
    SimulationRunner._processes.clear()


def test_live_interview_readiness_flags_stale_env_alive(monkeypatch, tmp_path):
    _reset_runner(monkeypatch, tmp_path)
    sim_dir = tmp_path / "sim_done"
    _write_json(
        sim_dir / "run_state.json",
        {
            "simulation_id": "sim_done",
            "runner_status": "stopped",
            "process_pid": 999999,
        },
    )
    _write_json(
        sim_dir / "env_status.json",
        {
            "status": "alive",
            "twitter_available": True,
            "reddit_available": True,
            "timestamp": "2026-06-07T00:00:00",
        },
    )
    monkeypatch.setattr(SimulationRunner, "_has_live_runner_process", lambda simulation_id, state=None: False)

    readiness = SimulationRunner.get_live_interview_readiness("sim_done")

    assert readiness["live_interviews_available"] is False
    assert readiness["runner_process_alive"] is False
    assert readiness["ipc_env_alive"] is True
    assert readiness["stale_env_status"] is True
    assert "stale env_status" in readiness["reason"]
    assert SimulationRunner.check_env_alive("sim_done") is False


def test_live_interview_readiness_requires_process_and_ipc_alive(monkeypatch, tmp_path):
    _reset_runner(monkeypatch, tmp_path)
    sim_dir = tmp_path / "sim_live"
    _write_json(
        sim_dir / "run_state.json",
        {
            "simulation_id": "sim_live",
            "runner_status": "running",
            "process_pid": 12345,
        },
    )
    _write_json(
        sim_dir / "env_status.json",
        {
            "status": "alive",
            "twitter_available": True,
            "reddit_available": True,
            "timestamp": "2026-06-07T00:00:00",
        },
    )
    monkeypatch.setattr(SimulationRunner, "_has_live_runner_process", lambda simulation_id, state=None: True)

    readiness = SimulationRunner.get_live_interview_readiness("sim_live")

    assert readiness["live_interviews_available"] is True
    assert readiness["runner_process_alive"] is True
    assert readiness["ipc_env_alive"] is True
    assert readiness["stale_env_status"] is False
    assert readiness["reason"] == "live interview IPC is available"
    assert SimulationRunner.check_env_alive("sim_live") is True


def test_batch_interview_uses_ipc_when_readiness_is_live(monkeypatch, tmp_path):
    _reset_runner(monkeypatch, tmp_path)
    sim_dir = tmp_path / "sim_live"
    sim_dir.mkdir(parents=True)
    captured = {}

    monkeypatch.setattr(
        SimulationRunner,
        "get_live_interview_readiness",
        classmethod(
            lambda cls, simulation_id: {
                "simulation_id": simulation_id,
                "live_interviews_available": True,
                "runner_process_alive": True,
                "ipc_env_alive": True,
                "stale_env_status": False,
                "runner_status": "completed",
                "process_pid": 12345,
                "reason": "live interview IPC is available",
            }
        ),
    )

    def fake_send_batch_interview(self, interviews, platform=None, timeout=120.0):
        captured["simulation_dir"] = self.simulation_dir
        captured["interviews"] = interviews
        captured["platform"] = platform
        captured["timeout"] = timeout
        return IPCResponse(
            command_id="cmd_live",
            status=CommandStatus.COMPLETED,
            result={"results": {"agent_7": {"response": "live transcript"}}},
        )

    monkeypatch.setattr(
        "app.services.simulation_runner.SimulationIPCClient.send_batch_interview",
        fake_send_batch_interview,
    )

    result = SimulationRunner.interview_agents_batch(
        simulation_id="sim_live",
        interviews=[{"agent_id": 7, "prompt": "What did you see?"}],
        platform="twitter",
        timeout=9.0,
    )

    assert result["success"] is True
    assert result["interviews_count"] == 1
    assert result["result"]["results"]["agent_7"]["response"] == "live transcript"
    assert captured == {
        "simulation_dir": str(sim_dir),
        "interviews": [{"agent_id": 7, "prompt": "What did you see?"}],
        "platform": "twitter",
        "timeout": 9.0,
    }
