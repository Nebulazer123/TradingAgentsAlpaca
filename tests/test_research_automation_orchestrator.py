import json
from decimal import Decimal

from typer.testing import CliRunner

from cli.main import app
from tradingagents.research.automation_orchestrator import (
    build_research_automation_orchestration,
)

runner = CliRunner()


def test_research_orchestration_packet_separates_parallel_model_lanes(tmp_path):
    result = build_research_automation_orchestration(
        candidate_symbols=["nvda", "msft"],
        env={
            "TRADINGAGENTS_WINDOWS_OLLAMA_URL": "http://127.0.0.1:11434/v1",
            "TRADINGAGENTS_MAC_OLLAMA_URL": "http://100.116.42.66:11434/v1",
            "TRADINGAGENTS_WINDOWS_RESEARCH_MODEL": "gpt-oss:20b",
            "TRADINGAGENTS_MAC_RESEARCH_MODEL": "qwen3:30b",
        },
        route_health={
            "windows_local": {
                "reachable": True,
                "models": ["gpt-oss:20b"],
                "model_present": True,
            },
            "mac_ollama": {
                "reachable": True,
                "models": ["qwen3:30b"],
                "model_present": True,
            },
        },
        include_research_context=False,
        model_telemetry_dir=tmp_path / "model_telemetry",
        batch_output_dir=tmp_path / "research_batches",
        estimated_judgment_cost_usd=Decimal("0"),
    )

    packet = result.batch_packet
    lanes = {lane["lane"]: lane for lane in packet.orchestration_lanes}

    assert packet.analysis_only is True
    assert packet.status == "partial"
    assert packet.candidate_symbols == ["MSFT", "NVDA"]
    assert lanes["deterministic_helpers"]["route"] == "deterministic_packet_helpers"
    assert lanes["windows_local"]["route"] == "windows_local_ollama"
    assert lanes["windows_local"]["model"] == "gpt-oss:20b"
    assert lanes["mac_ollama"]["route"] == "mac_ollama_research_mule"
    assert lanes["mac_ollama"]["model"] == "qwen3:30b"
    assert lanes["intelligent_judgment"]["route"] == "codex_or_chatgpt_thread_judgment"
    assert lanes["intelligent_judgment"]["status"] == "external"
    assert packet.quality_gates["route_plan_runnable"] is True
    assert packet.quality_gates["research_quality_high_enough"] is False
    assert all(lane["can_submit_orders"] is False for lane in packet.orchestration_lanes)
    assert "submit_order" in packet.forbidden_effects
    assert packet.output_packet_refs
    assert packet.graph_memory_refs
    assert packet.mirror_packet_refs
    assert packet.input_hashes["cache_key"]
    assert "toolful_research_boundary" in packet.freshness
    assert result.replay_plan_packet is not None
    assert result.replay_plan_packet.quality_gates["sleeve"] == "pullback-support"
    assert result.replay_plan_path is not None
    assert result.replay_plan_path.exists()
    assert result.batch_packet_path.exists()
    assert len(result.model_telemetry_paths) == 4


def test_research_orchestration_uses_default_mac_deepseek_helper_without_endpoint(tmp_path):
    result = build_research_automation_orchestration(
        candidate_symbols="tsm",
        env={},
        include_research_context=False,
        model_telemetry_dir=tmp_path / "model_telemetry",
        batch_output_dir=tmp_path / "research_batches",
    )

    lanes = {lane["lane"]: lane for lane in result.batch_packet.orchestration_lanes}

    assert result.batch_packet.status == "partial"
    assert lanes["mac_ollama"]["status"] == "blocked"
    assert lanes["mac_ollama"]["model"] == "deepseek-r1:14b"
    assert lanes["mac_ollama"]["endpoint_url"] == "http://macbook-pro.tail37edd7.ts.net:11434/v1"
    assert any("skip Windows local model lane" in action for action in result.batch_packet.fallback_actions)
    assert any("Mac" in action for action in result.batch_packet.fallback_actions)
    assert not any("windows_local" in blocker for blocker in result.batch_packet.blockers)
    assert not any("mac_ollama" in blocker for blocker in result.batch_packet.blockers)


def test_research_orchestration_blocks_mac_helper_when_health_probe_fails(tmp_path):
    result = build_research_automation_orchestration(
        candidate_symbols="tsm",
        env={},
        route_health={
            "mac_ollama": {
                "reachable": False,
                "error": "timed out",
                "models": [],
            }
        },
        include_research_context=False,
        model_telemetry_dir=tmp_path / "model_telemetry",
        batch_output_dir=tmp_path / "research_batches",
    )

    lanes = {lane["lane"]: lane for lane in result.batch_packet.orchestration_lanes}

    assert result.batch_packet.status == "partial"
    assert lanes["mac_ollama"]["status"] == "blocked"
    assert "health probe failed" in lanes["mac_ollama"]["reason"]
    assert result.batch_packet.quality_gates["route_plan_runnable"] is True
    assert result.batch_packet.quality_gates["research_quality_high_enough"] is False
    assert result.batch_packet.quality_gates["optional_helper_degraded"] is True
    assert result.batch_packet.quality_gates["degraded_helper_lanes"] == [
        "windows_local",
        "mac_ollama",
    ]
    assert any("Mac DeepSeek helper lane" in action for action in result.batch_packet.fallback_actions)
    assert result.batch_packet.freshness["route_health_probe"]["mac_ollama"]["reachable"] is False
    assert result.batch_packet.blockers == []
    assert result.batch_packet.execution_authority == "none"


def test_research_automation_orchestration_plan_cli_writes_packet(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "cli.main._ollama_endpoint_health",
        lambda endpoint, *, expected_model=None: {
            "endpoint_url": endpoint,
            "tags_url": f"{endpoint}/api/tags",
            "reachable": True,
            "expected_model": expected_model,
            "model_present": True,
            "models": [expected_model],
        },
    )
    result = runner.invoke(
        app,
        [
            "research",
            "automation-orchestration-plan",
            "--candidate-symbols",
            "nvda,msft",
            "--output-dir",
            str(tmp_path / "batches"),
            "--model-telemetry-dir",
            str(tmp_path / "model_telemetry"),
            "--research-context-dir",
            str(tmp_path / "context"),
            "--no-research-context",
            "--json-output",
        ],
        env={
            "TRADINGAGENTS_WINDOWS_OLLAMA_URL": "http://127.0.0.1:11434/v1",
            "TRADINGAGENTS_MAC_OLLAMA_URL": "http://100.116.42.66:11434/v1",
        },
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["status"] == "partial"
    assert payload["candidate_symbols"] == ["MSFT", "NVDA"]
    assert payload["quality_gates"]["route_plan_runnable"] is True
    assert payload["quality_gates"]["research_quality_high_enough"] is False
    assert "submit_order" in payload["forbidden_effects"]
    assert all(lane["can_submit_orders"] is False for lane in payload["orchestration_lanes"])
    assert (tmp_path / "batches" / "latest.json").exists()
    assert payload["replay_plan_packet_path"]
    assert payload["output_packet_refs"]
    assert payload["graph_memory_refs"]
    assert payload["mirror_packet_refs"]
    assert payload["input_hashes"]["cache_key"]
    assert payload["freshness"]["market_mirror_analysis_only"] is True
    assert payload["freshness"]["route_health_probe"]["mac_ollama"]["reachable"] is True
    assert len(payload["model_telemetry_paths"]) == 4


def test_research_automation_orchestration_plan_cli_autodetects_windows_ollama(
    tmp_path,
    monkeypatch,
):
    def fake_health(endpoint, *, expected_model=None):
        if "127.0.0.1:11434" in endpoint:
            return {
                "endpoint_url": endpoint,
                "tags_url": f"{endpoint}/api/tags",
                "reachable": True,
                "expected_model": expected_model,
                "model_present": False,
                "models": ["tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest"],
            }
        return {
            "endpoint_url": endpoint,
            "tags_url": f"{endpoint}/api/tags",
            "reachable": False,
            "expected_model": expected_model,
            "models": [],
            "error": "timed out",
        }

    monkeypatch.setattr("cli.main._ollama_endpoint_health", fake_health)
    result = runner.invoke(
        app,
        [
            "research",
            "automation-orchestration-plan",
            "--candidate-symbols",
            "xom",
            "--output-dir",
            str(tmp_path / "batches"),
            "--model-telemetry-dir",
            str(tmp_path / "model_telemetry"),
            "--no-research-context",
            "--json-output",
        ],
        env={
            "TRADINGAGENTS_WINDOWS_OLLAMA_URL": "",
            "TRADINGAGENTS_LOCAL_OLLAMA_URL": "",
            "TRADINGAGENTS_LOCAL_MODEL_URL": "",
            "OLLAMA_BASE_URL": "",
            "OLLAMA_HOST": "",
            "TRADINGAGENTS_WINDOWS_RESEARCH_MODEL": "",
            "TRADINGAGENTS_LOCAL_RESEARCH_MODEL": "",
        },
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    lanes = {lane["lane"]: lane for lane in payload["orchestration_lanes"]}
    assert lanes["windows_local"]["status"] == "selected"
    assert (
        lanes["windows_local"]["model"]
        == "tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest"
    )
    assert lanes["windows_local"]["endpoint_url"] == "http://127.0.0.1:11434/v1"
    assert payload["freshness"]["route_health_probe"]["windows_local"]["reachable"] is True
