import json
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.dataflows._official_common import evidence_packet
from tradingagents.policy.packets import write_research_packet
from tradingagents.research.loss_review_evidence import (
    DEFAULT_LOSS_REVIEW_EVIDENCE_NEEDS,
    build_loss_review_evidence_packet,
    find_latest_loss_review_packet,
    find_prior_live_entry_context,
)
from tradingagents.research.provider_orchestrator import TickerProviderResearchResult

runner = CliRunner()


def _hourly_packet(symbol: str = "TSM") -> dict:
    return {
        "generated_at": "2026-06-06T20:06:33+00:00",
        "decision": "loss-review",
        "actions": [],
        "submitted": [],
        "evidence": {
            "loss_exit_review": {
                "symbol": symbol,
                "allowed": False,
                "blocked_reasons": [
                    "allowed loss-exit reason is missing",
                    "source packet ids are missing",
                ],
                "blockers": [
                    "allowed loss-exit reason is missing",
                    "source packet ids are missing",
                    "SPY/QQQ/sector context is missing",
                    "company-specific news check is missing",
                    "earnings/guidance/filing check is missing",
                    "why HOLD is worse than SELL is missing",
                    "why this is not broad-market red-day noise is missing",
                    "market session is not tradeable for a live loss exit",
                ],
                "source_packet_ids": [],
                "current_price": "415.17",
                "average_entry_price": "448.96",
                "unrealized_pl": "-1.88",
                "unrealized_pnl_percent": "-7.52",
                "market_session": "closed",
            }
        },
    }


def _source_packet(source_name: str, evidence_type: str, symbol: str = "TSM"):
    return evidence_packet(
        source_name=source_name,
        evidence_type=evidence_type,
        subject=symbol,
        symbol=symbol,
        source_ref=f"https://example.test/{source_name}/{symbol}",
        payload={"source": source_name, "symbol": symbol},
        quality="medium",
        tool_route=f"{source_name}_test",
    )


def _provider_result(symbol: str = "TSM") -> TickerProviderResearchResult:
    packets = [
        _source_packet("broker_snapshot", "quote_price_context", symbol),
        _source_packet("google_news_rss", "market_news", symbol),
        _source_packet("sec_edgar", "fundamentals_profile", symbol),
        _source_packet("earnings_transcripts_gap", "earnings_transcripts", symbol),
    ]
    summary = _source_packet(
        "ticker_provider_orchestrator",
        "ticker_research_provider_bundle",
        symbol,
    )
    return TickerProviderResearchResult(
        symbol=symbol,
        packets=packets,
        summary_packet=summary,
        route_attempts=[
            {"evidence_need": packet.evidence_type, "source_name": packet.source_name}
            for packet in packets
        ],
    )


def test_find_latest_loss_review_packet_selects_newest_review(tmp_path):
    old_path = tmp_path / "hourly-supervisor-20260606-190000.json"
    old_path.write_text(json.dumps({"decision": "hold"}), encoding="utf-8")
    latest_path = tmp_path / "hourly-supervisor-20260606-200000.json"
    latest_path.write_text(json.dumps(_hourly_packet()), encoding="utf-8")
    compact_sidecar = tmp_path / "hourly-supervisor-20260606-210000.compact.json"
    compact_sidecar.write_text(json.dumps(_hourly_packet()), encoding="utf-8")

    path, packet, review = find_latest_loss_review_packet(tmp_path)

    assert path == latest_path
    assert packet["decision"] == "loss-review"
    assert review["symbol"] == "TSM"


def test_build_loss_review_evidence_packet_preserves_hold_and_attaches_sources():
    packet = build_loss_review_evidence_packet(
        hourly_packet_path=Path("results/hourly_supervisor/hourly-supervisor-test.json"),
        hourly_packet=_hourly_packet(),
        provider_result=_provider_result(),
    )

    payload = packet.payload
    assert packet.analysis_only is True
    assert payload["execution_authority"] == "none"
    assert "submit_order" in payload["forbidden_effects"]
    assert payload["symbol"] == "TSM"
    assert payload["hourly_decision"] == "loss-review"
    assert payload["review_allowed"] is False
    assert payload["source_packet_ids"]
    assert set(payload["evidence_needs"]) == set(DEFAULT_LOSS_REVIEW_EVIDENCE_NEEDS)
    assert payload["next_action"] == "manual_board_review_with_refreshed_evidence_required"
    assert payload["remaining_blockers_before_refresh"] == [
        "allowed loss-exit reason is missing",
        "source packet ids are missing",
        "SPY/QQQ/sector context is missing",
        "company-specific news check is missing",
        "earnings/guidance/filing check is missing",
        "why HOLD is worse than SELL is missing",
        "why this is not broad-market red-day noise is missing",
        "market session is not tradeable for a live loss exit",
    ]
    assert payload["resolved_blockers_by_refresh"] == [
        "source packet ids are missing",
        "SPY/QQQ/sector context is missing",
        "company-specific news check is missing",
        "earnings/guidance/filing check is missing",
        "why HOLD is worse than SELL is missing",
        "why this is not broad-market red-day noise is missing",
    ]
    assert "source packet ids are missing" not in payload["remaining_blockers"]
    assert "SPY/QQQ/sector context is missing" not in payload["remaining_blockers"]
    assert "company-specific news check is missing" not in payload["remaining_blockers"]
    assert "earnings/guidance/filing check is missing" not in payload["remaining_blockers"]
    assert "why HOLD is worse than SELL is missing" not in payload["remaining_blockers"]
    assert "why this is not broad-market red-day noise is missing" not in payload["remaining_blockers"]
    assert payload["advisory_analysis"]["review_allowed_after_refresh"] is False
    assert payload["advisory_analysis"]["market_context_attached"] is True
    assert "submit_order" in payload["advisory_analysis"]["forbidden_effects"]
    assert payload["remaining_blockers"] == [
        "allowed loss-exit reason is missing",
        "market session is not tradeable for a live loss exit",
    ]


def test_loss_review_evidence_attaches_prior_live_entry_context(tmp_path):
    buy_path = tmp_path / "hourly-supervisor-20260601-170250.json"
    buy_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T17:02:50+00:00",
                "decision": "buy",
                "actions": [
                    {
                        "action": "buy",
                        "symbol": "TSM",
                        "side": "buy",
                        "account": "live",
                        "notional": "25.00",
                        "limit_price": "449.80",
                        "reason": "Time-sensitive high-conviction candidate: score from price momentum 7.28%, volume ratio 1.04.",
                    }
                ],
                "submitted": [
                    {
                        "symbol": "TSM",
                        "side": "buy",
                        "client_order_id": "ta-hourly-20260601-170250-1-tsm-buy",
                        "submitted_at": "2026-06-01T17:02:50Z",
                        "status": "filled",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loss_packet = _hourly_packet()
    blockers = loss_packet["evidence"]["loss_exit_review"]["blockers"]
    blockers.insert(1, "holding period evidence is missing")
    blockers.insert(2, "original buy thesis is missing")
    loss_path = tmp_path / "hourly-supervisor-20260606-210521.json"
    loss_path.write_text(json.dumps(loss_packet), encoding="utf-8")

    path, hourly_packet, _review = find_latest_loss_review_packet(tmp_path)
    entry_context = find_prior_live_entry_context(
        path,
        symbol="TSM",
        review_at=None,
    )
    packet = build_loss_review_evidence_packet(
        hourly_packet_path=path,
        hourly_packet=hourly_packet,
        provider_result=_provider_result(),
    )

    payload = packet.payload
    assert entry_context is not None
    assert entry_context["packet_path"] == str(buy_path)
    assert payload["entry_context_found"] is True
    assert payload["entry_context"]["client_order_id"] == "ta-hourly-20260601-170250-1-tsm-buy"
    assert payload["entry_context"]["holding_period_trading_days"] == 4
    assert "holding period evidence is missing" in payload["resolved_blockers_by_refresh"]
    assert "original buy thesis is missing" in payload["resolved_blockers_by_refresh"]
    assert "holding period evidence is missing" not in payload["remaining_blockers"]
    assert "original buy thesis is missing" not in payload["remaining_blockers"]
    assert "allowed loss-exit reason is missing" in payload["remaining_blockers"]
    assert payload["review_allowed"] is False
    assert payload["advisory_analysis"]["review_allowed_after_refresh"] is False


def test_loss_review_evidence_classifies_falling_knife_thesis_without_approval(tmp_path):
    hourly_packet = _hourly_packet()
    blockers = hourly_packet["evidence"]["loss_exit_review"]["blockers"]
    blockers.insert(1, "current thesis status is missing")
    blockers.insert(2, "allowed loss-exit reason source is missing")
    blockers.insert(3, "loss-exit confidence is missing")
    hourly_packet["ranked_candidates"] = [
        {
            "symbol": "TSM",
            "score": "0.38",
            "day_change_pct": "-6.68",
            "volume_ratio": "1.58",
            "reason": "sharp drop -6.69%; falling-knife watch only until support reclaims",
        }
    ]
    packet = build_loss_review_evidence_packet(
        hourly_packet_path=Path("results/hourly_supervisor/hourly-supervisor-test.json"),
        hourly_packet=hourly_packet,
        provider_result=_provider_result(),
        entry_context={
            "entry_reason": "Time-sensitive high-conviction candidate: score from price momentum 7.28%",
            "holding_period_trading_days": 4,
        },
    )

    payload = packet.payload
    advisory = payload["advisory_analysis"]
    assert advisory["current_thesis_status_candidate"] == (
        "thesis_under_pressure_falling_knife_watch"
    )
    assert advisory["thesis_status_evidence"] == {
        "status": "thesis_under_pressure_falling_knife_watch",
        "drivers": [
            "current candidate is flagged as falling-knife/sharp-drop watch",
            "prior entry thesis was momentum or time-sensitive",
            "position is below average entry price",
        ],
        "approval_effect": "advisory_only_not_loss_exit_approval",
        "requires_board_decision": True,
    }
    assert "current thesis status is missing" in payload["resolved_blockers_by_refresh"]
    assert "allowed loss-exit reason is missing" in payload["resolved_blockers_by_refresh"]
    assert "allowed loss-exit reason source is missing" in payload["resolved_blockers_by_refresh"]
    assert "loss-exit confidence is missing" in payload["resolved_blockers_by_refresh"]
    assert "current thesis status is missing" not in payload["remaining_blockers"]
    assert "allowed loss-exit reason is missing" not in payload["remaining_blockers"]
    assert "allowed loss-exit reason source is missing" not in payload["remaining_blockers"]
    assert "loss-exit confidence is missing" not in payload["remaining_blockers"]
    assert payload["remaining_blockers"] == [
        "market session is not tradeable for a live loss exit",
    ]
    assert payload["review_allowed"] is False
    assert advisory["review_allowed_after_refresh"] is False
    assert advisory["loss_exit_candidate"] == {
        "allowed_exit_reason_candidate": "thesis_invalidated",
        "allowed_exit_reason_source": "refreshed_loss_review_evidence",
        "confidence": "0.78",
        "confidence_tier": "medium",
        "reason_summary": (
            "Prior momentum/time-sensitive thesis is under pressure while the "
            "current candidate is a falling-knife watch below average entry."
        ),
        "drivers": [
            "current candidate is flagged as falling-knife/sharp-drop watch",
            "prior entry thesis was momentum or time-sensitive",
            "position is below average entry price",
            "refreshed market and company evidence attached",
            "holding period is available",
        ],
        "approval_effect": "board_review_input_not_loss_exit_approval",
        "requires_board_decision": True,
        "requires_tradeable_session": True,
        "can_submit_orders": False,
    }

    packet_path = write_research_packet(packet, tmp_path)
    compact = json.loads(packet_path.with_suffix(".compact.json").read_text(encoding="utf-8"))
    assert compact["payload"]["advisory_summary"]["thesis_status_evidence"] == {
        "status": "thesis_under_pressure_falling_knife_watch",
        "drivers": [
            "current candidate is flagged as falling-knife/sharp-drop watch",
            "prior entry thesis was momentum or time-sensitive",
            "position is below average entry price",
        ],
        "approval_effect": "advisory_only_not_loss_exit_approval",
        "requires_board_decision": True,
    }
    assert compact["payload"]["advisory_summary"]["loss_exit_candidate"][
        "allowed_exit_reason_candidate"
    ] == "thesis_invalidated"
    assert compact["payload"]["advisory_summary"]["loss_exit_candidate"][
        "confidence"
    ] == "0.78"


def test_loss_review_evidence_cli_writes_analysis_only_packet(monkeypatch, tmp_path):
    hourly_dir = tmp_path / "hourly"
    hourly_dir.mkdir()
    hourly_path = hourly_dir / "hourly-supervisor-20260606-200000.json"
    hourly_path.write_text(json.dumps(_hourly_packet()), encoding="utf-8")
    output_dir = tmp_path / "loss_review"

    monkeypatch.setattr(
        "cli.main.build_ticker_provider_research_packets",
        lambda *args, **kwargs: _provider_result(),
    )

    result = runner.invoke(
        app,
        [
            "research",
            "loss-review-evidence",
            "--hourly-dir",
            str(hourly_dir),
            "--output-dir",
            str(output_dir),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["can_submit_orders"] is False
    assert payload["execution_authority"] == "none"
    assert payload["symbol"] == "TSM"
    assert payload["hourly_decision"] == "loss-review"
    assert payload["review_allowed"] is False
    assert payload["evidence_needs"] == list(DEFAULT_LOSS_REVIEW_EVIDENCE_NEEDS)
    assert payload["remaining_blockers_before_refresh_count"] == 8
    assert payload["remaining_blocker_count"] == 2
    assert payload["resolved_blocker_count"] == 6
    assert payload["resolved_blockers_by_refresh"] == [
        "source packet ids are missing",
        "SPY/QQQ/sector context is missing",
        "company-specific news check is missing",
        "earnings/guidance/filing check is missing",
        "why HOLD is worse than SELL is missing",
        "why this is not broad-market red-day noise is missing",
    ]
    assert payload["next_action"] == "manual_board_review_with_refreshed_evidence_required"
    assert payload["source_packet_count"] == 4
    assert payload["packet_path"].endswith(".json")
    written = json.loads(Path(payload["packet_path"]).read_text(encoding="utf-8"))
    assert written["payload"]["next_action"] == "manual_board_review_with_refreshed_evidence_required"
    assert written["payload"]["resolved_blockers_by_refresh"]
    compact_path = Path(payload["packet_path"]).with_suffix(".compact.json")
    assert compact_path.exists()
    latest_compact_path = output_dir / "latest-compact.json"
    assert latest_compact_path.exists()
    compact = json.loads(latest_compact_path.read_text(encoding="utf-8"))
    assert compact["schema"] == "compact_loss_review_evidence_v1"
    assert compact["raw_packet_path"] == payload["packet_path"]
    assert compact["can_submit_orders"] is False
    assert compact["execution_authority"] == "none"
    assert compact["payload"]["symbol"] == "TSM"
    assert len(compact["payload"]["remaining_blockers_before_refresh"]) == 8
    assert len(compact["payload"]["remaining_blockers"]) == 2
    assert len(compact["payload"]["resolved_blockers_by_refresh"]) == 6
    assert isinstance(compact["payload"]["entry_context"], dict)
    assert "client_order_id" not in compact["payload"]["entry_context"]
    assert "submitted_at" not in compact["payload"]["entry_context"]
    assert "advisory_analysis" not in compact["payload"]
    assert compact["payload"]["advisory_summary"][
        "review_allowed_after_refresh"
    ] is False
    assert compact["payload"]["advisory_summary"]["source_ref_count"] == 5
    assert compact["payload"]["advisory_summary"]["blocked_route_count"] == 0
