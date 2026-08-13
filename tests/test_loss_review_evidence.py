import json
from datetime import datetime
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.dataflows._official_common import evidence_packet
from tradingagents.policy.loss_board_decision import record_autonomous_loss_board_decision
from tradingagents.policy.packets import write_research_packet
from tradingagents.research import loss_review_evidence as loss_evidence
from tradingagents.research.loss_review_evidence import (
    DEFAULT_LOSS_REVIEW_EVIDENCE_NEEDS,
    build_loss_review_evidence_packet,
    find_latest_loss_review_packet,
    find_prior_live_entry_context,
)
from tradingagents.research.provider_orchestrator import TickerProviderResearchResult

runner = CliRunner()


def _clock(now: str, *, is_open: bool = True) -> dict:
    return {
        "source_name": "alpaca_clock",
        "source_ref": "alpaca:/v2/clock",
        "as_of": now,
        "captured_at": now,
        "is_open": is_open,
        "raw_clock": {"timestamp": now, "is_open": is_open},
    }


def test_clock_normalizer_rejects_tampered_wrapper_and_normalizes_fractional_raw_time():
    raw = "2026-08-13T14:55:00.987654+00:00"
    normalized, issue = loss_evidence._current_market_clock(
        {
            "source_name": "alpaca_clock",
            "source_ref": "alpaca:/v2/clock",
            "as_of": "2026-08-13T14:55:00+00:00",
            "captured_at": "2026-08-13T14:55:01.999999+00:00",
            "is_open": True,
            "raw_clock": {"timestamp": raw, "is_open": True},
        }
    )
    assert issue == ""
    assert normalized["as_of"] == "2026-08-13T14:55:00+00:00"
    assert normalized["captured_at"] == "2026-08-13T14:55:01+00:00"
    assert loss_evidence._current_market_clock(
        {
            "source_name": "alpaca_clock", "source_ref": "alpaca:/v2/clock",
            "as_of": "2026-08-13T14:55:01+00:00", "captured_at": "2026-08-13T14:55:01+00:00",
            "is_open": True, "raw_clock": {"timestamp": raw, "is_open": False},
        }
    )[0] is None


def test_keyword_only_or_generic_news_never_becomes_loss_board_adverse_fact():
    generic = evidence_packet(
        source_name="google_news_rss", evidence_type="market_news", subject="ORCL", symbol="ORCL",
        source_ref="https://example.test/rss", payload={"articles": [{"headline": "Oracle cuts guidance"}]},
        quality="high", as_of="2026-08-13T14:55:00+00:00", tool_route="google_news",
    )
    keyword_only = evidence_packet(
        source_name="finnhub", evidence_type="market_news", subject="ORCL", symbol="ORCL",
        source_ref="https://example.test/finnhub", payload={"data": [{"datetime": 1786632840, "headline": "Oracle cuts guidance", "url": "https://issuer.test/news"}]},
        quality="medium", as_of="2026-08-13T14:55:00+00:00", tool_route="finnhub_api",
    )
    assert loss_evidence._normalize_provider_packet(packet=generic, stored=generic.model_dump(), symbol="ORCL") is None
    assert loss_evidence._normalize_provider_packet(packet=keyword_only, stored=keyword_only.model_dump(), symbol="ORCL") is None


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


def _complete_provider_result(symbol: str = "ORCL") -> TickerProviderResearchResult:
    """Real-shaped raw provider packets, not already-normalized authority."""
    packets = [
        evidence_packet(
            source_name="broker_market_context", evidence_type="quote_price_context",
            subject=symbol, symbol=symbol, source_ref="https://example.test/market",
            payload={"market_context": {"spy": "0.10", "qqq": "0.20", "sector_relative": "-0.03"}}, quality="high", tool_route="test",
        ),
        evidence_packet(
            source_name="company_news_provider", evidence_type="market_news",
            subject=symbol, symbol=symbol, source_ref="https://example.test/news",
            payload={"company_event": {"event_category": "thesis_invalidator", "direction": "adverse", "impact_fraction": "-0.08"}}, quality="high", tool_route="test",
        ),
        evidence_packet(
            source_name="earnings_transcript_provider", evidence_type="earnings_transcripts",
            subject=symbol, symbol=symbol, source_ref="https://example.test/transcript",
            payload={"company_event": {"event_category": "guidance_cut", "direction": "adverse", "change_fraction": "-0.12"}}, quality="high", tool_route="test",
        ),
    ]
    return TickerProviderResearchResult(symbol=symbol, packets=packets, summary_packet=None, route_attempts=[])


def _configured_shape_provider_result(symbol: str = "ORCL") -> TickerProviderResearchResult:
    """Fixtures mirror the configured Alpaca, Finnhub, and FMP route shapes."""
    return TickerProviderResearchResult(
        symbol=symbol,
        packets=[
            evidence_packet(
                source_name="alpaca_market_data", evidence_type="quote_price_context",
                subject="ORCL,SPY,QQQ,XLK", symbol=symbol,
                source_ref="https://data.alpaca.markets/v2/stocks/trades/latest",
                payload={"request_context": {"symbols": [symbol, "SPY", "QQQ", "XLK"]}, "data": {"trades": {
                    symbol: {"p": 91.0, "pc": 100.0, "t": "2026-08-13T14:55:00Z"},
                    "SPY": {"p": 650.0, "pc": 648.0, "t": "2026-08-13T14:55:00Z"},
                    "QQQ": {"p": 580.0, "pc": 578.0, "t": "2026-08-13T14:55:00Z"},
                    "XLK": {"p": 260.0, "pc": 259.0, "t": "2026-08-13T14:55:00Z"},
                }}}, quality="high", as_of="2026-08-13T14:55:00+00:00", tool_route="alpaca_market_data_read_only",
            ),
            evidence_packet(
                source_name="finnhub", evidence_type="market_news", subject=symbol, symbol=symbol,
                source_ref="https://finnhub.io/api/v1/company-news",
                payload={"data": [{"category": "company news", "datetime": 1786632840, "headline": "Oracle cuts fiscal guidance after material contract loss", "summary": "The company lowered fiscal revenue guidance by 8% after losing a material customer contract.", "url": "https://issuer.example/adverse"}]},
                quality="medium", as_of="2026-08-13T14:55:00+00:00", tool_route="finnhub_api",
            ),
            evidence_packet(
                source_name="fmp", evidence_type="earnings_transcripts", subject=symbol, symbol=symbol,
                source_ref="https://financialmodelingprep.com/api/v3/earning-call-transcript/ORCL",
                payload={"symbol": symbol, "year": 2026, "quarter": 1, "transcript_items": [{"content": "Management lowered full-year revenue guidance by 12% because of the contract loss."}]},
                quality="high", as_of="2026-08-13T14:55:00+00:00", tool_route="fmp_api",
            ),
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


def test_find_latest_loss_review_packet_accepts_newer_blocked_exit_evidence(tmp_path):
    old_path = tmp_path / "hourly-supervisor-20260715-011255.json"
    old_path.write_text(json.dumps(_hourly_packet()), encoding="utf-8")
    latest_packet = _hourly_packet()
    latest_packet["generated_at"] = "2026-07-15T16:35:54+00:00"
    latest_packet["decision"] = "blocked"
    latest_packet["evidence"]["loss_exit_review"]["market_session"] = "regular"
    latest_path = tmp_path / "hourly-supervisor-20260715-163554.json"
    latest_path.write_text(json.dumps(latest_packet), encoding="utf-8")

    path, packet, review = find_latest_loss_review_packet(tmp_path)

    assert path == latest_path
    assert packet["decision"] == "blocked"
    assert review["market_session"] == "regular"


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
    assert payload["next_action"] == "autonomous_hold"
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
    # Generic quote/news/submissions/connector-gap packets remain advisory.
    # They cannot falsely clear the exact market, company-news, or filing
    # blockers needed for a loss decision.
    assert payload["resolved_blockers_by_refresh"] == ["source packet ids are missing"]
    assert "source packet ids are missing" not in payload["remaining_blockers"]
    assert payload["remaining_blockers"] == ["refreshed evidence is incomplete"]
    assert payload["advisory_analysis"]["review_allowed_after_refresh"] is False
    assert payload["advisory_analysis"]["market_context_attached"] is False
    assert "submit_order" in payload["advisory_analysis"]["forbidden_effects"]
    assert payload["remaining_blockers"] == ["refreshed evidence is incomplete"]


def test_fabricated_nested_provider_context_does_not_become_authority(tmp_path):
    hourly_packet = _hourly_packet("ORCL")
    review = hourly_packet["evidence"]["loss_exit_review"]
    review["symbol"] = "ORCL"
    review["blockers"] = ["SPY/QQQ/sector context is missing", "company-specific news check is missing", "earnings/guidance/filing check is missing"]
    review["blocked_reasons"] = list(review["blockers"])
    provider = _complete_provider_result()
    source_paths = {packet.packet_id: write_research_packet(packet, tmp_path / "raw") for packet in provider.packets}

    packet = build_loss_review_evidence_packet(
        hourly_packet_path=tmp_path / "hourly.json",
        hourly_packet=hourly_packet,
        provider_result=provider,
        source_packet_paths=source_paths,
        decision_evidence_root=tmp_path,
    )

    accepted = packet.payload["accepted_sources"]
    assert accepted == []
    assert packet.payload["advisory_analysis"]["qualified_evidence"] == {"market": False, "company_news": False, "filing": False}
    assert packet.payload["remaining_blockers"] == ["refreshed evidence is incomplete"]


def test_configured_provider_shapes_normalize_to_complete_adverse_loss_evidence(tmp_path):
    provider = _configured_shape_provider_result()
    hourly = _hourly_packet("ORCL")
    review = hourly["evidence"]["loss_exit_review"]
    review["blockers"] = ["SPY/QQQ/sector context is missing", "company-specific news check is missing", "earnings/guidance/filing check is missing"]
    review["blocked_reasons"] = list(review["blockers"])
    source_paths = {packet.packet_id: write_research_packet(packet, tmp_path / "raw") for packet in provider.packets}

    packet = build_loss_review_evidence_packet(
        hourly_packet_path=tmp_path / "hourly.json", hourly_packet=hourly,
        provider_result=provider, source_packet_paths=source_paths, decision_evidence_root=tmp_path,
    )

    assert {item["evidence_type"] for item in packet.payload["accepted_sources"]} == {"market_context", "company_news", "earnings_guidance_filing"}
    # The historical packet was not persisted inside the evidence root, so it
    # cannot become a current authority candidate in this unit-only fixture.
    assert packet.payload["current_loss_review"]["allowed"] is False
    news = next(item for item in packet.payload["accepted_sources"] if item["evidence_type"] == "company_news")
    normalized = json.loads((tmp_path / news["path"]).read_text(encoding="utf-8"))
    assert normalized["payload"]["event_category"] == "guidance_cut"


def test_real_configured_individual_quote_route_builds_bound_current_review_and_sell(tmp_path):
    """Production-shaped path: frozen supervisor -> refresh -> immutable SELL.

    Every quote is a separate configured one-symbol packet.  No test inserts a
    decision field into the current review; the refresh derives it from raw
    evidence and the recorder re-authenticates it through public APIs.
    """
    now = "2026-08-13T14:55:00+00:00"
    hourly = _hourly_packet("ORCL")
    review = hourly["evidence"]["loss_exit_review"]
    review.update(
        {
            "decision_id": "historical-orcl-loss-1",
            "market_session": "regular",
            "current_price": "91",
            "average_entry_price": "100",
            "blockers": ["SPY/QQQ/sector context is missing"],
            "blocked_reasons": ["SPY/QQQ/sector context is missing"],
        }
    )
    hourly_path = tmp_path / "hourly" / "hourly-supervisor-orcl.json"
    hourly_path.parent.mkdir()
    hourly_path.write_text(json.dumps(hourly), encoding="utf-8")

    def quote(symbol, price, previous):
        return evidence_packet(
            source_name="finnhub", evidence_type="quote_price_context", subject=symbol,
            symbol=symbol, source_ref=f"https://finnhub.test/quote/{symbol}",
            payload={"c": price, "pc": previous}, quality="high", as_of=now,
            tool_route="finnhub_api",
        )

    provider = TickerProviderResearchResult(
        symbol="ORCL",
        packets=[
            quote("ORCL", 91.0, 100.0), quote("SPY", 650.0, 648.0),
            quote("QQQ", 580.0, 578.0), quote("XLK", 260.0, 259.0),
            evidence_packet(
                source_name="finnhub", evidence_type="market_news", subject="ORCL", symbol="ORCL",
                source_ref="https://finnhub.test/news/ORCL",
                payload={"data": [{"category": "company", "datetime": 1786632840,
                                    "headline": "Oracle cuts revenue guidance", "summary": "Lowered revenue guidance by 8%.",
                                    "url": "https://issuer.test/adverse"}]},
                quality="medium", as_of=now, tool_route="finnhub_api",
            ),
            evidence_packet(
                source_name="fmp", evidence_type="earnings_transcripts", subject="ORCL", symbol="ORCL",
                source_ref="https://fmp.test/transcript/ORCL",
                payload={"symbol": "ORCL", "transcript_items": [{"content": "Management lowered revenue guidance by 12%."}]},
                quality="high", as_of=now, tool_route="fmp_api",
            ),
        ],
    )
    source_paths = {
        item.packet_id: write_research_packet(item, tmp_path / "raw") for item in provider.packets
    }
    packet = build_loss_review_evidence_packet(
        hourly_packet_path=hourly_path, hourly_packet=hourly, provider_result=provider,
        source_packet_paths=source_paths, decision_evidence_root=tmp_path,
        market_clock=_clock(now),
    )
    loss_path = write_research_packet(packet, tmp_path / "loss")
    current = packet.payload["current_loss_review"]
    assert current["allowed"] is True
    assert current["allowed_exit_reason"] == "earnings_or_guidance_break"
    assert isinstance(current["allowed_exit_reason_source"], dict)
    market = next(item for item in packet.payload["accepted_sources"] if item["evidence_type"] == "market_context")
    normalized_market = json.loads((tmp_path / market["path"]).read_text(encoding="utf-8"))
    assert len(normalized_market["provenance"]["components"]) == 4
    assert {item["symbol"] for item in normalized_market["provenance"]["components"]} == {"ORCL", "SPY", "QQQ", "XLK"}
    recorded = record_autonomous_loss_board_decision(
        supervisor_packet_path=hourly_path, loss_evidence_packet_path=loss_path,
        source_revision="1" * 40, ledger_root=tmp_path / "ledger",
        evidence_root=tmp_path, now=__import__("datetime").datetime.fromisoformat(now),
    )
    assert recorded.decision.decision == "SELL", recorded.decision.evidence_gaps
    assert recorded.decision.can_submit_orders is False


def test_closed_current_clock_allows_decision_only_sell_but_not_execution(tmp_path):
    """The present exchange clock, not the old hourly label, controls session state."""
    now = "2026-08-13T14:55:00+00:00"
    hourly = _hourly_packet("ORCL")
    review = hourly["evidence"]["loss_exit_review"]
    review.update({"decision_id": "clock-bound", "market_session": "regular", "current_price": "91", "average_entry_price": "100", "blockers": [], "blocked_reasons": []})
    hourly_path = tmp_path / "hourly.json"
    hourly_path.write_text(json.dumps(hourly), encoding="utf-8")

    def quote(symbol, price, previous, quality="high"):
        return evidence_packet(source_name="finnhub", evidence_type="quote_price_context", subject=symbol, symbol=symbol, source_ref=f"https://test/{symbol}", payload={"c": price, "pc": previous}, quality=quality, as_of=now, tool_route="test")
    provider = TickerProviderResearchResult("ORCL", [
        quote("ORCL", 91, 100), quote("SPY", 650, 648), quote("QQQ", 580, 578), quote("XLK", 260, 259),
        evidence_packet(
            source_name="finnhub", evidence_type="market_news", subject="ORCL",
            symbol="ORCL", source_ref="https://test/news",
            payload={"data": [{"datetime": 1786632840, "headline": "Oracle cuts guidance", "summary": "Lowered guidance by 8%", "url": "https://issuer.test/x"}]},
            quality="medium", as_of=now, tool_route="test",
        ),
        evidence_packet(source_name="fmp", evidence_type="earnings_transcripts", subject="ORCL", symbol="ORCL", source_ref="https://test/transcript", payload={"symbol": "ORCL", "transcript_items": [{"content": "Management lowered revenue guidance by 12%."}]}, quality="high", as_of=now, tool_route="test"),
    ])
    paths = {item.packet_id: write_research_packet(item, tmp_path / "raw") for item in provider.packets}
    closed = build_loss_review_evidence_packet(hourly_packet_path=hourly_path, hourly_packet=hourly, provider_result=provider, source_packet_paths=paths, decision_evidence_root=tmp_path, market_clock=_clock(now, is_open=False))
    closed_path = write_research_packet(closed, tmp_path / "loss-closed")
    assert closed.payload["current_loss_review"]["market_session"] == "closed"
    assert closed.payload["current_loss_review"]["allowed"] is True
    assert closed.payload["current_loss_review"]["trade_decision_allowed"] is True
    assert closed.payload["current_loss_review"]["execution_eligible"] is False
    assert closed.payload["current_loss_review"]["execution_blockers"] == [
        "market session is not tradeable for a live loss exit"
    ]
    assert closed.payload["current_loss_review"]["blockers"] == []
    # The board resolves SELL as a decision-only outcome while closed.
    decision = record_autonomous_loss_board_decision(supervisor_packet_path=hourly_path, loss_evidence_packet_path=closed_path, source_revision="1" * 40, ledger_root=tmp_path / "ledger", evidence_root=tmp_path, now=__import__("datetime").datetime.fromisoformat(now)).decision
    assert decision.decision == "SELL" and decision.can_submit_orders is False

    open_packet = build_loss_review_evidence_packet(hourly_packet_path=hourly_path, hourly_packet=hourly, provider_result=provider, source_packet_paths=paths, decision_evidence_root=tmp_path, market_clock=_clock(now, is_open=True))
    assert open_packet.payload["current_loss_review"]["market_session"] == "regular"
    assert open_packet.payload["current_loss_review"]["allowed"] is True
    assert open_packet.payload["current_loss_review"]["trade_decision_allowed"] is True
    assert open_packet.payload["current_loss_review"]["execution_eligible"] is True
    assert open_packet.payload["current_loss_review"]["execution_blockers"] == []


def test_low_quality_or_stale_clock_fails_closed_for_loss_board(tmp_path):
    now = "2026-08-13T14:55:00+00:00"
    # The normal complete fixture is enough to test that a low component cannot
    # be upgraded through aggregation.
    hourly = _hourly_packet("ORCL")
    hourly["evidence"]["loss_exit_review"].update({"decision_id": "low-quality", "current_price": "91", "average_entry_price": "100", "blockers": [], "blocked_reasons": []})
    hourly_path = tmp_path / "hourly.json"
    hourly_path.write_text(json.dumps(hourly), encoding="utf-8")
    provider = _configured_shape_provider_result("ORCL")
    packets = list(provider.packets)
    packets[0] = packets[0].model_copy(update={"quality": "low"})
    provider = TickerProviderResearchResult("ORCL", packets)
    paths = {item.packet_id: write_research_packet(item, tmp_path / "raw") for item in provider.packets}
    packet = build_loss_review_evidence_packet(hourly_packet_path=hourly_path, hourly_packet=hourly, provider_result=provider, source_packet_paths=paths, decision_evidence_root=tmp_path, market_clock=_clock(now))
    market = next(item for item in packet.payload["accepted_sources"] if item["evidence_type"] == "market_context")
    assert market["quality"] == "low"
    loss_path = write_research_packet(packet, tmp_path / "loss")
    decision = record_autonomous_loss_board_decision(supervisor_packet_path=hourly_path, loss_evidence_packet_path=loss_path, source_revision="2" * 40, ledger_root=tmp_path / "ledger", evidence_root=tmp_path, now=__import__("datetime").datetime.fromisoformat(now)).decision
    assert decision.decision == "HOLD"


def test_generic_tsm_provider_packets_are_not_normalized_into_authority(tmp_path):
    provider = _provider_result()
    source_paths = {packet.packet_id: write_research_packet(packet, tmp_path / "raw") for packet in provider.packets}
    packet = build_loss_review_evidence_packet(
        hourly_packet_path=tmp_path / "hourly.json", hourly_packet=_hourly_packet(), provider_result=provider,
        source_packet_paths=source_paths, decision_evidence_root=tmp_path,
    )
    assert packet.payload["accepted_sources"] == []
    assert packet.payload["advisory_analysis"]["qualified_evidence"] == {"market": False, "company_news": False, "filing": False}


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
    assert payload["remaining_blockers"] == ["refreshed evidence is incomplete"]
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
        "Refreshed evidence is incomplete; HOLD remains safer."
    )
    assert advisory["current_loss_review"]["schema"] == "tradingagents.refreshed_loss_review.v1"
    assert advisory["current_loss_review"]["allowed"] is False
    assert "current thesis status is missing" in payload["resolved_blockers_by_refresh"]
    assert "allowed loss-exit reason is missing" not in payload["resolved_blockers_by_refresh"]
    assert "allowed loss-exit reason source is missing" not in payload["resolved_blockers_by_refresh"]
    assert "loss-exit confidence is missing" not in payload["resolved_blockers_by_refresh"]
    assert "current thesis status is missing" not in payload["remaining_blockers"]
    assert payload["remaining_blockers"] == ["refreshed evidence is incomplete"]
    assert payload["review_allowed"] is False
    assert advisory["review_allowed_after_refresh"] is False
    assert advisory["loss_exit_candidate"]["allowed_exit_reason_candidate"] is None
    assert advisory["loss_exit_candidate"]["confidence"] == "0.00"
    assert advisory["qualified_evidence"] == {
        "market": False,
        "company_news": False,
        "filing": False,
    }

    packet_path = write_research_packet(packet, tmp_path)
    compact = json.loads(packet_path.with_suffix(".compact.json").read_text(encoding="utf-8"))
    # Compact advisory history is descriptive only; it may retain the
    # falling-knife diagnostic.  The decision-capable current review is the
    # separately bound Mapping asserted above.
    assert compact["payload"]["advisory_summary"]["thesis_status_evidence"]["status"] == (
        "thesis_under_pressure_falling_knife_watch"
    )
    assert compact["payload"]["advisory_summary"]["loss_exit_candidate"][
        "allowed_exit_reason_candidate"
    ] is None
    assert compact["payload"]["advisory_summary"]["loss_exit_candidate"][
        "confidence"
    ] == "0.00"


def test_loss_review_evidence_cli_writes_analysis_only_packet(monkeypatch, tmp_path):
    hourly_dir = tmp_path / "hourly"
    hourly_dir.mkdir()
    hourly_path = hourly_dir / "hourly-supervisor-20260606-200000.json"
    hourly_path.write_text(json.dumps(_hourly_packet()), encoding="utf-8")
    output_dir = tmp_path / "loss_review"

    calls = []
    def providers(symbol, **kwargs):
        calls.append((symbol, kwargs["evidence_needs"]))
        return _provider_result(symbol)
    monkeypatch.setattr("cli.main.build_loss_review_provider_research", providers)
    class FrozenClockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls.fromisoformat("2026-06-06T20:06:34.111222+00:00")
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr("cli.main.datetime.datetime", FrozenClockDatetime)
    monkeypatch.setattr(
        "cli.main._alpaca_live_client",
        lambda: type("ClockClient", (), {"get_clock": lambda self: {"timestamp": "2026-06-06T20:06:33.918273+00:00", "is_open": False}})(),
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
    assert payload["remaining_blocker_count"] == 1
    assert payload["resolved_blocker_count"] == 1
    assert payload["resolved_blockers_by_refresh"] == ["source packet ids are missing"]
    assert payload["next_action"] == "autonomous_hold"
    assert payload["source_packet_count"] == 4
    assert payload["packet_path"].endswith(".json")
    written = json.loads(Path(payload["packet_path"]).read_text(encoding="utf-8"))
    assert written["payload"]["next_action"] == "autonomous_hold"
    assert written["payload"]["resolved_blockers_by_refresh"]
    # The CLI captures the raw clock once, but exposes only canonical UTC
    # whole-second wrapper values for immutable evidence.
    assert written["payload"]["market_clock_snapshot"]["as_of"] == "2026-06-06T20:06:33+00:00"
    assert datetime.fromisoformat(
        written["payload"]["market_clock_snapshot"]["captured_at"]
    ).microsecond == 0
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
    assert len(compact["payload"]["remaining_blockers"]) == 1
    assert len(compact["payload"]["resolved_blockers_by_refresh"]) == 1
    assert isinstance(compact["payload"]["entry_context"], dict)
    assert "client_order_id" not in compact["payload"]["entry_context"]
    assert "submitted_at" not in compact["payload"]["entry_context"]
    assert "advisory_analysis" not in compact["payload"]
    assert compact["payload"]["advisory_summary"][
        "review_allowed_after_refresh"
    ] is False
    assert compact["payload"]["advisory_summary"]["source_ref_count"] == 5
    assert compact["payload"]["advisory_summary"]["blocked_route_count"] == 0
    assert calls == [("TSM", DEFAULT_LOSS_REVIEW_EVIDENCE_NEEDS)]
