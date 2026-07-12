import datetime
import json
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.research.deep_research_protocol import (
    build_deep_research_protocol_packet,
)
from tradingagents.research.overnight_context import (
    build_overnight_research_context_packets,
    summarize_overnight_research_context,
)
from tradingagents.research.source_quality import assess_source_quality

runner = CliRunner()


def test_deep_research_protocol_packet_is_advisory_only():
    packet = build_deep_research_protocol_packet()

    assert packet.source_name == "chatgpt_deep_research_protocol"
    assert packet.analysis_only is True
    assert packet.payload["execution_authority"] == "none"
    assert "submit_order" in packet.payload["forbidden_effects"]
    assert "phase_gate_due_diligence" in {
        item["use_case"] for item in packet.payload["use_cases"]
    }
    assert packet.payload["primary_route"]["ui_url"] == "https://chatgpt.com/deep-research"
    assert packet.payload["primary_route"]["preferred_entry"] == "dedicated Deep Research page"
    assert "dom_rendered_text_extraction" in packet.payload["backup_routes"]
    assert "slash_picker_mode_selection" in packet.payload["backup_routes"]
    reliable_route = packet.payload["reliable_browser_route"]
    assert reliable_route["start_page"] == "https://chatgpt.com/deep-research"
    assert reliable_route["operator_auth_boundary"].startswith("Codex may open")
    assert "extract rendered assistant/report DOM text" in reliable_route["capture_failover_order"]
    assert {item["route"] for item in reliable_route["mode_selector_routes"]} == {
        "dropdown",
        "slash_picker_backup",
    }
    assert "before promoting a new methodology from idea to paper policy" in packet.payload[
        "when_tradingagents_should_use_deep_research"
    ]
    assert packet.payload["methodology_insert"]["tradingagents_role"] == (
        "advisory_hypothesis_engine_only"
    )


def test_overnight_context_includes_methodology_and_deep_research_protocol():
    packets = build_overnight_research_context_packets()
    source_names = {packet.source_name for packet in packets}

    assert "strategy_methodology_cards" in source_names
    assert "chatgpt_deep_research_protocol" in source_names
    assert "mirofish_handoff" in source_names

    summary = summarize_overnight_research_context(packets)
    methodology = summary["methodology"]

    assert methodology["strategy_card_count"] >= 5
    assert methodology["deep_research"]["primary_route"] == "chatgpt_deep_research_pro"
    assert methodology["deep_research"]["execution_authority"] == "none"
    assert "submit_order" in methodology["deep_research"]["forbidden_effects"]
    assert summary["mirofish_handoff"]["execution_authority"] == "none"


def test_deep_research_protocol_cli_writes_packet(tmp_path):
    result = runner.invoke(
        app,
        [
            "research",
            "deep-research-protocol",
            "--output-dir",
            str(tmp_path / "evidence"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["source_name"] == "chatgpt_deep_research_protocol"
    assert Path(payload["packet_path"]).exists()
    assert payload["payload"]["execution_authority"] == "none"


def test_deep_research_protocol_source_quality_is_bounded_advisory():
    decision = assess_source_quality(
        "chatgpt_deep_research_protocol",
        as_of="2026-06-02T10:00:00+00:00",
        current_time=datetime.datetime(2026, 6, 2, 12, 0, tzinfo=datetime.timezone.utc),
    )

    assert decision.quality == "medium"
    assert decision.role == "external_deep_research_methodology_context"
    assert decision.allowed_effects == ("request_more_research",)
    assert "promote_sleeve" in decision.forbidden_effects
