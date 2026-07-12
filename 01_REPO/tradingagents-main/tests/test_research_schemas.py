import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import tradingagents.policy.packets as packet_writers
from tradingagents.policy.packets import compact_research_batch_payload, write_research_packet
from tradingagents.schemas.research import (
    MarketMirrorScenarioPacket,
    ModelRunTelemetryPacket,
    ResearchBatchRunPacket,
    SocialAnomalyPacket,
    SourceEvidencePacket,
)
from tradingagents.schemas.trading import SourceProvenance


def test_source_evidence_packet_round_trip_and_writer(tmp_path):
    packet = SourceEvidencePacket(
        source_name="sec_edgar",
        evidence_type="companyfacts",
        subject="Microsoft company facts",
        symbol="msft",
        sources=[
            SourceProvenance(
                source="sec:data.sec.gov",
                as_of="2026-06-01T12:00:00+00:00",
                quality="high",
            )
        ],
        source_refs=["https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json"],
        input_hashes={"request": "abc123"},
        freshness={"as_of": "2026-06-01T12:00:00+00:00", "stale": False},
        payload={"facts_seen": 12},
        quality="high",
    )

    written = write_research_packet(packet, tmp_path / "research_evidence")
    saved = json.loads(written.read_text(encoding="utf-8"))

    assert saved["analysis_only"] is True
    assert saved["symbol"] == "MSFT"
    assert saved["packet_id"].startswith("source-evidence-")
    assert saved["sources"][0]["quality"] == "high"
    assert json.loads((tmp_path / "research_evidence" / "latest.json").read_text(encoding="utf-8"))["packet_id"] == saved["packet_id"]


def test_research_packets_reject_trade_intent_smuggling():
    with pytest.raises(ValidationError):
        SourceEvidencePacket.model_validate(
            {
                "source_name": "crawler",
                "evidence_type": "social",
                "subject": "example",
                "analysis_only": True,
                "intent": {"symbol": "MSFT", "side": "buy"},
            }
        )


def test_research_packets_are_analysis_only():
    with pytest.raises(ValidationError):
        SocialAnomalyPacket(
            platform="reddit",
            anomaly_type="volume_spike",
            summary="mentions jumped",
            analysis_only=False,
        )


def test_research_packet_writer_routes_packet_families(tmp_path):
    model_packet = ModelRunTelemetryPacket(
        run_id="model-test",
        provider="local",
        model="gpt-oss:20b",
        route="mac_mule",
        status="success",
    )
    mirror_packet = MarketMirrorScenarioPacket(
        scenario_id="mirror-msft-1",
        symbol="msft",
        consensus="buyers wait for support confirmation",
    )
    batch_packet = ResearchBatchRunPacket(
        batch_id="overnight-20260601",
        status="partial",
        candidate_symbols=["msft", "orcl"],
        source_packet_refs=["source-evidence-1"],
    )

    model_path = write_research_packet(model_packet, tmp_path / "model_telemetry")
    mirror_path = write_research_packet(mirror_packet, tmp_path / "research_simulations")
    batch_path = write_research_packet(batch_packet, tmp_path / "research_batches")

    assert model_path.name.startswith("model-telemetry-")
    assert mirror_path.name.startswith("market-mirror-")
    assert batch_path.name.startswith("research-batch-")
    assert json.loads(batch_path.read_text(encoding="utf-8"))["candidate_symbols"] == [
        "MSFT",
        "ORCL",
    ]
    latest_compact = json.loads(
        (tmp_path / "research_batches" / "latest-compact.json").read_text(encoding="utf-8")
    )
    assert latest_compact["schema"] == "compact_research_batch_v1"
    assert latest_compact["candidate_symbols"] == ["MSFT", "ORCL"]
    assert latest_compact["source_packet_ref_count"] == 1
    assert latest_compact["can_submit_orders"] is False
    assert latest_compact["raw_packet_path"] == str(batch_path)
    assert batch_path.with_suffix(".compact.json").exists()


def test_compact_research_batch_keeps_walk_forward_summary_only():
    packet = ResearchBatchRunPacket(
        batch_id="walk-forward-20260606",
        status="success",
        candidate_symbols=["msft", "nvda", "goog", "aapl", "amd", "tsla", "meta", "avgo", "orcl"],
        orchestration_lanes=[{"lane": "primary"}, {"lane": "mac_helper"}],
        source_packet_refs=["source-1", "source-2"],
        crawler_packet_refs=["crawler-1"],
        model_telemetry_refs=["model-1"],
        fallback_actions=["refresh stale macro source"],
        quality_gates={
            "research_quality_high_enough": True,
            "fallback_required": False,
            "at_least_one_local_worker_ready": False,
            "walk_forward_row_count": 420,
            "walk_forward_metrics": [
                {
                    "arm_id": "pullback-support",
                    "status": "accepted",
                    "scored_count": 120,
                    "directional_accuracy": 0.62,
                    "average_action_relative_return": 0.014,
                    "false_positive_rate": 0.18,
                    "sample_floor_met": True,
                    "execution_authority": "none",
                    "raw_rows": [{"large": "omitted"}],
                }
            ],
        },
    )

    compact = compact_research_batch_payload(packet, raw_packet_path="results/research_batches/raw.json")

    assert compact["candidate_symbols"] == ["MSFT", "NVDA", "GOOG", "AAPL", "AMD", "TSLA", "META", "AVGO"]
    assert compact["candidate_symbol_count"] == 9
    assert compact["lane_count"] == 2
    assert compact["source_packet_ref_count"] == 2
    assert compact["fallback_action_count"] == 1
    assert compact["failed_quality_gates"] == []
    assert compact["advisory_missing_gates"] == ["at_least_one_local_worker_ready"]
    assert compact["quality_gates"]["walk_forward_metrics"] == [
        {
            "arm_id": "pullback-support",
            "status": "accepted",
            "scored_count": 120,
            "directional_accuracy": 0.62,
            "average_action_relative_return": 0.014,
            "false_positive_rate": 0.18,
            "sample_floor_met": True,
            "execution_authority": "none",
        }
    ]
    assert compact["can_submit_orders"] is False


def test_research_packet_writer_retries_transient_replace_permission_error(
    tmp_path,
    monkeypatch,
):
    packet = SourceEvidencePacket(
        source_name="sec_edgar",
        evidence_type="companyfacts",
        subject="Microsoft company facts",
        symbol="msft",
        sources=[
            SourceProvenance(
                source="sec:data.sec.gov",
                as_of="2026-06-01T12:00:00+00:00",
                quality="high",
            )
        ],
        source_refs=["https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json"],
        input_hashes={"request": "abc123"},
        freshness={"as_of": "2026-06-01T12:00:00+00:00", "stale": False},
        payload={"facts_seen": 12},
        quality="high",
    )
    original_replace = Path.replace
    latest_failures = {"count": 0}

    def flaky_replace(self, target):
        if Path(target).name == "latest.json" and latest_failures["count"] == 0:
            latest_failures["count"] += 1
            raise PermissionError("simulated transient Windows file lock")
        return original_replace(self, target)

    monkeypatch.setattr(packet_writers.time, "sleep", lambda _: None)
    monkeypatch.setattr(Path, "replace", flaky_replace)

    written = write_research_packet(packet, tmp_path / "research_evidence")

    latest = json.loads((tmp_path / "research_evidence" / "latest.json").read_text(encoding="utf-8"))
    assert latest["packet_id"] == json.loads(written.read_text(encoding="utf-8"))["packet_id"]
    assert latest_failures["count"] == 1
