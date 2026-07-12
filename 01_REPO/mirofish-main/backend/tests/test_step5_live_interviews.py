import importlib.util
import json
import time
from pathlib import Path
from threading import Thread

from app.services.simulation_ipc import CommandType, SimulationIPCClient, SimulationIPCServer


REPO_ROOT = Path(__file__).resolve().parents[2]
STEP5_SCRIPT = REPO_ROOT / "docs" / "mirror_fish" / "mirofish_step5_live_interviews.py"


def _load_step5_module():
    spec = importlib.util.spec_from_file_location("mirofish_step5_live_interviews_test", STEP5_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_step5_harness_calls_live_batch_path_when_readiness_is_positive(monkeypatch, tmp_path):
    module = _load_step5_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    sim_dir = tmp_path / "backend" / "uploads" / "simulations" / "sim_live"
    _write_json(
        sim_dir / "postrun_telemetry.json",
        {
            "agents_to_interview_in_stage05": [
                {
                    "agent_id": 644,
                    "agent_name": "CNBC Markets Desk 0644",
                    "actor_layer": "media/narrative",
                    "actions": 18,
                },
                {
                    "agent_id": 3,
                    "agent_name": "Prompt Bot Users",
                    "actor_layer": "developer/automation",
                    "actions": 12,
                },
            ]
        },
    )
    captured = {}

    monkeypatch.setattr(
        module.SimulationRunner,
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

    def fake_interview_agents_batch(cls, simulation_id, interviews, platform=None, timeout=120.0):
        captured["simulation_id"] = simulation_id
        captured["interviews"] = interviews
        captured["platform"] = platform
        captured["timeout"] = timeout
        return {
            "success": True,
            "interviews_count": len(interviews),
            "result": {"results": {"agent_644": {"response": "true live transcript"}}},
        }

    monkeypatch.setattr(
        module.SimulationRunner,
        "interview_agents_batch",
        classmethod(fake_interview_agents_batch),
    )

    data, json_path, md_path = module.run_step5_live_interviews(
        simulation_id="sim_live",
        output_dir=tmp_path / "step5_live",
        max_agents=2,
        timeout=7.0,
        platform=None,
    )

    assert data["status"] == "completed"
    assert data["result"]["result"]["results"]["agent_644"]["response"] == "true live transcript"
    assert data["targets"][0]["agent_id"] == 644
    assert captured["simulation_id"] == "sim_live"
    assert captured["platform"] is None
    assert captured["timeout"] == 7.0
    assert [item["agent_id"] for item in captured["interviews"]] == [644, 3]
    assert "What is most likely wrong in this simulation?" in captured["interviews"][0]["prompt"]
    assert "What should TradingAgents watch first tomorrow?" in captured["interviews"][0]["prompt"]
    assert json_path.exists()
    assert md_path.exists()
    assert "true live transcript" in md_path.read_text(encoding="utf-8")


def test_step5_harness_falls_back_to_config_targets_without_telemetry(monkeypatch, tmp_path):
    module = _load_step5_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    sim_dir = tmp_path / "backend" / "uploads" / "simulations" / "sim_config_only"
    _write_json(
        sim_dir / "simulation_config.json",
        {
            "agent_configs": [
                {"agent_id": 10, "entity_name": "Small Account Trader", "entity_type": "RetailTrader"},
                {"agent_id": 11, "entity_name": "Broker API Developer", "entity_type": "DeveloperCommunity"},
            ]
        },
    )
    captured = {}

    monkeypatch.setattr(
        module.SimulationRunner,
        "get_live_interview_readiness",
        classmethod(lambda cls, simulation_id: {"live_interviews_available": True, "reason": "live"}),
    )
    def fake_interview_agents_batch(cls, simulation_id, interviews, platform=None, timeout=120.0):
        captured["interviews"] = interviews
        return {
            "success": True,
            "interviews_count": len(interviews),
            "result": {"results": {"agent_10": {"response": "config fallback transcript"}}},
        }

    monkeypatch.setattr(module.SimulationRunner, "interview_agents_batch", classmethod(fake_interview_agents_batch))

    data, _, _ = module.run_step5_live_interviews(
        simulation_id="sim_config_only",
        output_dir=tmp_path / "step5_live",
        max_agents=2,
        timeout=7.0,
        platform="twitter",
    )

    assert data["status"] == "completed"
    assert [target["agent_id"] for target in data["targets"]] == [10, 11]
    assert data["targets"][0]["agent_name"] == "Small Account Trader"
    assert data["targets"][0]["actor_layer"] == "RetailTrader"
    assert [item["agent_id"] for item in captured["interviews"]] == [10, 11]


def test_batch_interview_ipc_round_trip_uses_command_and_response_files(tmp_path):
    sim_dir = tmp_path / "sim_ipc"
    client = SimulationIPCClient(str(sim_dir))
    server = SimulationIPCServer(str(sim_dir))
    seen = {}

    def worker():
        deadline = time.time() + 5
        while time.time() < deadline:
            command = server.poll_commands()
            if command is None:
                time.sleep(0.05)
                continue
            seen["command_type"] = command.command_type
            seen["args"] = command.args
            server.send_success(
                command.command_id,
                {"results": {"agent_7": {"response": "ipc live transcript"}}},
            )
            return
        seen["timeout"] = True

    thread = Thread(target=worker)
    thread.start()
    response = client.send_batch_interview(
        interviews=[{"agent_id": 7, "prompt": "What did you see?"}],
        platform="reddit",
        timeout=5.0,
    )
    thread.join(timeout=5.0)

    assert seen.get("timeout") is not True
    assert seen["command_type"] == CommandType.BATCH_INTERVIEW
    assert seen["args"] == {
        "interviews": [{"agent_id": 7, "prompt": "What did you see?"}],
        "platform": "reddit",
    }
    assert response.status.value == "completed"
    assert response.result["results"]["agent_7"]["response"] == "ipc live transcript"
    assert not any((sim_dir / "ipc_commands").glob("*.json"))
    assert not any((sim_dir / "ipc_responses").glob("*.json"))
