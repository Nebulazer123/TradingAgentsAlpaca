import json
from pathlib import Path

from typer.testing import CliRunner

from cli import main as cli_main
from cli.main import app
from tradingagents.dataflows._official_common import evidence_packet
from tradingagents.research import provider_orchestrator as orchestrator
from tradingagents.research.provider_fallbacks import load_provider_fallback_config
from tradingagents.research.provider_orchestrator import (
    DEFAULT_TICKER_EVIDENCE_NEEDS,
    TickerProviderResearchResult,
    build_ticker_provider_research_packets,
)
from tradingagents.schemas.research import CrawlerRunPacket

runner = CliRunner()


def _packet(source_name: str, *, evidence_type: str = "market_news", symbol: str = "NVDA"):
    return evidence_packet(
        source_name=source_name,
        evidence_type=evidence_type,
        subject=symbol,
        symbol=symbol,
        source_ref=f"https://example.test/{source_name}/{symbol}",
        payload={"source": source_name, "symbol": symbol},
        quality="medium" if source_name != "google_news_rss" else "low",
        tool_route=f"{source_name}_test",
    )


def test_ticker_provider_bundle_collects_broad_overlapping_news_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(
        orchestrator,
        "build_reddit_watchlist_packet",
        lambda: _packet("reddit_watchlist"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_google_news_rss",
        lambda **kwargs: _packet("google_news_rss"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_alpaca_news",
        lambda **kwargs: _packet("alpaca_news"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_finnhub_company_news",
        lambda symbol, **kwargs: _packet("finnhub"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_newsapi_everything",
        lambda query, **kwargs: _packet("newsapi"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_fmp_stock_news",
        lambda symbols, **kwargs: _packet("fmp"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_eodhd_news",
        lambda **kwargs: _packet("eodhd"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_marketaux_news",
        lambda **kwargs: _packet("marketaux"),
    )

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("market_news",),
        max_packets_per_need=5,
        cache_dir=tmp_path / "cache",
    )

    sources = [packet.source_name for packet in result.packets]

    assert sources == ["reddit_watchlist", "alpaca_news", "google_news_rss", "finnhub", "newsapi"]
    assert result.summary_packet is not None
    assert result.summary_packet.analysis_only is True
    assert result.summary_packet.payload["execution_authority"] == "none"
    assert result.summary_packet.payload["packet_counts_by_source"] == {
        "alpaca_news": 1,
        "finnhub": 1,
        "google_news_rss": 1,
        "newsapi": 1,
        "reddit_watchlist": 1,
    }
    assert result.summary_packet.payload["limited_source_packet_count"] == 2
    assert not any(
        attempt["source_name"] == "crawlee" for attempt in result.route_attempts
    )


def test_ticker_provider_bundle_uses_source_quality_ordering(monkeypatch, tmp_path):
    monkeypatch.setattr(
        orchestrator,
        "fetch_google_news_rss",
        lambda **kwargs: _packet("google_news_rss"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_alpaca_news",
        lambda **kwargs: _packet("alpaca_news"),
    )
    review_path = tmp_path / "source_quality_latest.json"
    review_path.write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "source_name": "google_news_rss",
                        "quality": "medium",
                        "freshness_status": "fresh",
                        "allowed_effects": ["downrank", "request_more_research"],
                    },
                    {
                        "source_name": "alpaca_news",
                        "quality": "medium",
                        "freshness_status": "stale",
                        "allowed_effects": ["downrank", "request_more_research"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("market_news",),
        disabled_sources={
            "official_cache",
            "reddit_watchlist",
            "reddit",
            "finnhub",
            "newsapi",
            "fmp",
            "tiingo",
            "eodhd",
            "marketaux",
            "scrapingbee",
        },
        max_packets_per_need=2,
        cache_dir=tmp_path / "cache",
        source_quality_review_path=review_path,
    )

    assert [packet.source_name for packet in result.packets] == [
        "google_news_rss",
        "alpaca_news",
    ]
    google_attempt = next(
        attempt
        for attempt in result.route_attempts
        if attempt["source_name"] == "google_news_rss"
    )
    alpaca_attempt = next(
        attempt
        for attempt in result.route_attempts
        if attempt["source_name"] == "alpaca_news"
    )
    assert google_attempt["source_quality_score"] > alpaca_attempt["source_quality_score"]
    assert result.summary_packet is not None
    assert result.summary_packet.payload["source_quality_ordering"] == {
        "enabled": True,
        "review_path": str(review_path),
        "scored_source_count": 2,
    }


def test_ticker_provider_bundle_does_not_prefer_unscored_source_over_known_fresh(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        orchestrator,
        "fetch_google_news_rss",
        lambda **kwargs: _packet("google_news_rss"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_newsapi_everything",
        lambda query, **kwargs: _packet("newsapi"),
    )
    review_path = tmp_path / "source_quality_latest.json"
    review_path.write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "source_name": "google_news_rss",
                        "quality": "low",
                        "freshness_status": "fresh",
                        "blocked": False,
                        "allowed_effects": ["downrank", "request_more_research"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("market_news",),
        disabled_sources={
            "official_cache",
            "alpaca_news",
            "reddit_watchlist",
            "reddit",
            "finnhub",
            "fmp",
            "tiingo",
            "eodhd",
            "marketaux",
            "scrapingbee",
        },
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
        source_quality_review_path=review_path,
    )

    assert [packet.source_name for packet in result.packets] == ["google_news_rss"]
    assert result.route_attempts[0]["source_quality_score"] == 75.0


def test_ticker_provider_bundle_skips_blocked_provider_packets(monkeypatch, tmp_path):
    monkeypatch.setattr(
        orchestrator,
        "fetch_google_news_rss",
        lambda **kwargs: _packet("google_news_rss"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_tiingo_news",
        lambda **kwargs: evidence_packet(
            source_name="tiingo",
            evidence_type="market_news",
            subject="NVDA",
            symbol="NVDA",
            source_ref="https://example.test/tiingo/NVDA",
            payload={"blocked": True},
            quality="unknown",
            tool_route="tiingo_test",
            freshness_extra={"blocked": True},
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_newsapi_everything",
        lambda query, **kwargs: _packet("newsapi"),
    )
    review_path = tmp_path / "source_quality_latest.json"
    review_path.write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "source_name": "google_news_rss",
                        "quality": "medium",
                        "freshness_status": "fresh",
                        "blocked": False,
                        "allowed_effects": ["downrank", "request_more_research"],
                    },
                    {
                        "source_name": "tiingo",
                        "quality": "medium",
                        "freshness_status": "fresh",
                        "blocked": False,
                        "allowed_effects": ["downrank", "request_more_research"],
                    },
                    {
                        "source_name": "newsapi",
                        "quality": "low",
                        "freshness_status": "fresh",
                        "blocked": False,
                        "allowed_effects": ["downrank", "request_more_research"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("market_news",),
        disabled_sources={
            "official_cache",
            "alpaca_news",
            "reddit_watchlist",
            "reddit",
            "finnhub",
            "fmp",
            "eodhd",
            "marketaux",
            "scrapingbee",
        },
        max_packets_per_need=2,
        cache_dir=tmp_path / "cache",
        source_quality_review_path=review_path,
    )

    assert [packet.source_name for packet in result.packets] == ["google_news_rss", "newsapi"]
    tiingo_attempt = next(
        attempt for attempt in result.route_attempts if attempt["source_name"] == "tiingo"
    )
    assert tiingo_attempt["status"] == "packet_written"
    assert tiingo_attempt["blocked"] is True
    assert result.summary_packet is not None
    assert result.summary_packet.payload["packet_counts_by_source"] == {
        "google_news_rss": 1,
        "newsapi": 1,
    }


def test_default_ticker_provider_needs_include_active_gap_categories():
    assert "earnings_transcripts" in DEFAULT_TICKER_EVIDENCE_NEEDS
    assert "short_interest" in DEFAULT_TICKER_EVIDENCE_NEEDS
    assert "options_iv_flow" in DEFAULT_TICKER_EVIDENCE_NEEDS


def test_ticker_provider_bundle_writes_gap_packets_for_missing_categories(tmp_path):
    cache_dir = tmp_path / "cache"
    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("earnings_transcripts", "short_interest", "options_iv_flow"),
        disabled_sources={
            "benzinga",
            "fmp",
            "youtube_transcript",
            "yfinance_options",
            "yfinance_short_interest",
        },
        max_packets_per_need=1,
        cache_dir=cache_dir,
    )

    packets_by_need = {packet.evidence_type: packet for packet in result.packets}

    assert set(packets_by_need) == {"earnings_transcripts", "short_interest", "options_iv_flow"}
    for evidence_need, packet in packets_by_need.items():
        assert packet.analysis_only is True
        assert packet.quality == "unknown"
        assert packet.source_name == f"{evidence_need}_gap"
        assert packet.tool_route == "local:research_gap"
        assert packet.payload["execution_authority"] == "none"
        assert packet.payload["research_action"].startswith("downrank confidence")
        assert packet.freshness["blocked"] is True
        assert packet.freshness["downrank_evidence"] is True

    assert result.summary_packet is not None
    assert result.summary_packet.payload["packet_counts_by_source"] == {
        "earnings_transcripts_gap": 1,
        "options_iv_flow_gap": 1,
        "short_interest_gap": 1,
    }
    assert result.summary_packet.payload["route_status_counts"] == {
        "cache_miss": 3,
        "packet_written": 3,
        "unsupported_in_local_orchestrator": 2,
    }
    assert result.summary_packet.payload["unsupported_route_count"] == 2
    assert result.summary_packet.payload["blocked_packet_attempt_count"] == 3
    assert result.summary_packet.payload["gap_packet_count"] == 3
    assert result.summary_packet.payload["evidence_needs_with_gap_packets"] == [
        "earnings_transcripts",
        "options_iv_flow",
        "short_interest",
    ]
    assert result.summary_packet.payload["evidence_needs_without_non_gap_packets"] == [
        "earnings_transcripts",
        "options_iv_flow",
        "short_interest",
    ]
    assert all(
        attempt["status"] == "packet_written" and attempt["blocked"] is True
        for attempt in result.route_attempts
        if attempt["source_name"].endswith("_gap")
    )

    second_result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("earnings_transcripts",),
        disabled_sources={"benzinga", "fmp", "youtube_transcript"},
        max_packets_per_need=1,
        cache_dir=cache_dir,
    )

    assert second_result.packets[0].source_name == "earnings_transcripts_gap"
    assert second_result.packets[0].tool_route == "local:research_gap"


def test_ticker_provider_bundle_uses_yfinance_short_interest_before_gap(monkeypatch, tmp_path):
    monkeypatch.setattr(
        orchestrator,
        "fetch_yfinance_short_interest",
        lambda symbol: _packet(
            "yfinance_short_interest",
            evidence_type="short_interest",
            symbol=symbol,
        ),
    )

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("short_interest",),
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["yfinance_short_interest"]
    packet = result.packets[0]
    assert packet.evidence_type == "short_interest"
    assert packet.analysis_only is True
    assert result.summary_packet is not None
    assert result.summary_packet.payload["packet_counts_by_source"] == {
        "yfinance_short_interest": 1,
    }
    assert result.summary_packet.payload["gap_packet_count"] == 0
    assert result.summary_packet.payload["evidence_needs_without_non_gap_packets"] == []
    assert any(
        attempt["source_name"] == "yfinance_short_interest"
        and attempt["status"] == "packet_written"
        and attempt["blocked"] is False
        for attempt in result.route_attempts
    )
    assert not any(packet.source_name == "short_interest_gap" for packet in result.packets)


def test_ticker_provider_bundle_falls_to_gap_when_yfinance_short_interest_blocks(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        orchestrator,
        "fetch_yfinance_short_interest",
        lambda symbol: (_ for _ in ()).throw(
            orchestrator.OfficialDataError("yfinance returned no short-interest fields")
        ),
    )

    result = build_ticker_provider_research_packets(
        "qqq",
        evidence_needs=("short_interest",),
        disabled_sources={"finnhub", "fmp"},
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["short_interest_gap"]
    assert result.packets[0].freshness["blocked"] is True
    assert any(
        attempt["source_name"] == "yfinance_short_interest"
        and attempt["status"] == "packet_written"
        and attempt["blocked"] is True
        for attempt in result.route_attempts
    )


def test_ticker_provider_bundle_uses_fmp_transcript_before_gap(monkeypatch, tmp_path):
    monkeypatch.setattr(
        orchestrator,
        "fetch_fmp_latest_earning_call_transcript",
        lambda symbol: _packet(
            "fmp",
            evidence_type="earnings_transcripts",
            symbol=symbol,
        ),
    )

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("earnings_transcripts",),
        disabled_sources={"youtube_transcript", "benzinga"},
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["fmp"]
    packet = result.packets[0]
    assert packet.evidence_type == "earnings_transcripts"
    assert packet.analysis_only is True
    assert result.summary_packet is not None
    assert result.summary_packet.payload["packet_counts_by_source"] == {"fmp": 1}
    assert any(
        attempt["source_name"] == "fmp"
        and attempt["status"] == "packet_written"
        and attempt["blocked"] is False
        for attempt in result.route_attempts
    )
    assert not any(packet.source_name == "earnings_transcripts_gap" for packet in result.packets)


def test_ticker_provider_bundle_uses_youtube_transcript_before_fmp(
    monkeypatch,
    tmp_path,
):
    fmp_called = False

    monkeypatch.setattr(
        orchestrator,
        "fetch_youtube_earnings_transcript_packet",
        lambda symbol, **kwargs: _packet(
            "youtube_transcript",
            evidence_type="earnings_transcripts",
            symbol=symbol,
        ),
    )

    def fake_fmp(*_args, **_kwargs):
        nonlocal fmp_called
        fmp_called = True
        return _packet("fmp", evidence_type="earnings_transcripts")

    monkeypatch.setattr(orchestrator, "fetch_fmp_latest_earning_call_transcript", fake_fmp)

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("earnings_transcripts",),
        disabled_sources={"benzinga"},
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["youtube_transcript"]
    assert fmp_called is False
    assert result.summary_packet is not None
    assert result.summary_packet.payload["packet_counts_by_source"] == {
        "youtube_transcript": 1,
    }
    assert result.summary_packet.payload["evidence_needs_without_non_gap_packets"] == []
    assert any(
        attempt["source_name"] == "youtube_transcript"
        and attempt["status"] == "packet_written"
        and attempt["blocked"] is False
        for attempt in result.route_attempts
    )


def test_ticker_provider_bundle_falls_to_gap_when_fmp_transcript_blocks(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        orchestrator,
        "fetch_fmp_latest_earning_call_transcript",
        lambda symbol: (_ for _ in ()).throw(
            orchestrator.OfficialDataError("FMP_API_KEY is not set")
        ),
    )

    result = build_ticker_provider_research_packets(
        "ko",
        evidence_needs=("earnings_transcripts",),
        disabled_sources={"youtube_transcript", "benzinga"},
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["earnings_transcripts_gap"]
    assert result.packets[0].freshness["blocked"] is True
    assert result.summary_packet is not None
    assert result.summary_packet.payload["limited_source_packet_count"] == 0
    assert result.summary_packet.payload["blocked_packet_attempt_count"] == 2
    assert result.summary_packet.payload["gap_packet_count"] == 1
    assert result.summary_packet.payload["evidence_needs_with_gap_packets"] == [
        "earnings_transcripts"
    ]
    assert result.summary_packet.payload["evidence_needs_without_non_gap_packets"] == [
        "earnings_transcripts"
    ]
    assert any(
        attempt["source_name"] == "fmp"
        and attempt["status"] == "packet_written"
        and attempt["blocked"] is True
        for attempt in result.route_attempts
    )


def test_ticker_provider_bundle_falls_through_when_youtube_transcript_blocks(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        orchestrator,
        "fetch_youtube_earnings_transcript_packet",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            orchestrator.OfficialDataError("youtube_transcript MCP timed out")
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_fmp_latest_earning_call_transcript",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            orchestrator.OfficialDataError("FMP_API_KEY is not set")
        ),
    )

    result = build_ticker_provider_research_packets(
        "ko",
        evidence_needs=("earnings_transcripts",),
        disabled_sources={"benzinga"},
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["earnings_transcripts_gap"]
    assert result.summary_packet is not None
    assert result.summary_packet.payload["blocked_packet_attempt_count"] == 3
    assert result.summary_packet.payload["gap_packet_count"] == 1
    assert result.summary_packet.payload["evidence_needs_without_non_gap_packets"] == [
        "earnings_transcripts"
    ]
    assert any(
        attempt["source_name"] == "youtube_transcript"
        and attempt["status"] == "packet_written"
        and attempt["blocked"] is True
        for attempt in result.route_attempts
    )
    assert any(
        attempt["source_name"] == "fmp"
        and attempt["status"] == "packet_written"
        and attempt["blocked"] is True
        for attempt in result.route_attempts
    )


def test_ticker_provider_bundle_uses_yfinance_options_before_gap(monkeypatch, tmp_path):
    monkeypatch.setattr(
        orchestrator,
        "fetch_yfinance_options_iv_flow",
        lambda symbol: _packet(
            "yfinance_options",
            evidence_type="options_iv_flow",
            symbol=symbol,
        ),
    )

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("options_iv_flow",),
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["yfinance_options"]
    packet = result.packets[0]
    assert packet.evidence_type == "options_iv_flow"
    assert packet.analysis_only is True
    assert result.summary_packet is not None
    assert result.summary_packet.payload["packet_counts_by_source"] == {
        "yfinance_options": 1,
    }
    assert any(
        attempt["source_name"] == "yfinance_options"
        and attempt["status"] == "packet_written"
        and attempt["blocked"] is False
        for attempt in result.route_attempts
    )
    assert not any(packet.source_name == "options_iv_flow_gap" for packet in result.packets)


def test_ticker_provider_bundle_skips_depleted_limited_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(
        orchestrator,
        "fetch_google_news_rss",
        lambda **kwargs: _packet("google_news_rss"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_alpaca_news",
        lambda **kwargs: _packet("alpaca_news"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_finnhub_company_news",
        lambda symbol, **kwargs: _packet("finnhub"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_newsapi_everything",
        lambda query, **kwargs: _packet("newsapi"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_fmp_stock_news",
        lambda symbols, **kwargs: _packet("fmp"),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_eodhd_news",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("EODHD should be depleted")),
    )
    monkeypatch.setattr(
        orchestrator,
        "fetch_marketaux_news",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Marketaux should be depleted")),
    )

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("market_news",),
        depleted_sources={"eodhd", "marketaux"},
        max_packets_per_need=5,
        cache_dir=tmp_path / "cache",
    )

    sources = [packet.source_name for packet in result.packets]

    assert "eodhd" not in sources
    assert "marketaux" not in sources
    assert result.summary_packet is not None
    assert result.summary_packet.payload["depleted_sources"] == ["eodhd", "marketaux"]


def test_ticker_provider_bundle_uses_public_reddit_social_context(monkeypatch, tmp_path):
    monkeypatch.setattr(
        orchestrator,
        "fetch_reddit_posts",
        lambda symbol, **kwargs: f"r/stocks: one fresh post about {symbol}",
    )

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("social_sentiment",),
        disabled_sources={
            "facebook",
            "google_news_rss",
            "instagram",
            "linkedin",
            "official_cache",
            "reddit_watchlist",
            "social_watchlist",
            "twitter",
        },
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["reddit"]
    packet = result.packets[0]
    assert packet.evidence_type == "social_sentiment"
    assert packet.payload["reddit_context"].startswith("r/stocks")
    assert packet.payload["execution_authority"] == "none"
    assert packet.freshness["read_only"] is True
    assert any(
        attempt["source_name"] == "reddit"
        and attempt["status"] == "packet_written"
        for attempt in result.route_attempts
    )


def test_ticker_provider_bundle_uses_twitter_mcp_social_context(monkeypatch, tmp_path):
    monkeypatch.setattr(
        orchestrator,
        "fetch_twitter_recent_search_packet",
        lambda symbol, **kwargs: evidence_packet(
            source_name="twitter",
            evidence_type=kwargs["evidence_need"],
            subject=f"twitter context for {symbol}",
            symbol=symbol,
            source_ref=f"docker-mcp://twitter-research/{symbol}",
            payload={
                "symbol": symbol,
                "twitter_result": {"ok": True, "data": [{"text": "NVDA stock attention"}]},
                "read_only": True,
                "analysis_only": True,
                "execution_authority": "none",
            },
            quality="low",
            tool_route="docker:twitter-research",
            freshness_extra={"read_only": True, "blocked": False, "route": "docker:twitter-research"},
        ),
    )

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("social_sentiment",),
        disabled_sources={
            "facebook",
            "google_news_rss",
            "instagram",
            "linkedin",
            "official_cache",
            "reddit",
            "reddit_watchlist",
            "social_watchlist",
        },
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["twitter"]
    packet = result.packets[0]
    assert packet.evidence_type == "social_sentiment"
    assert packet.tool_route == "docker:twitter-research"
    assert packet.freshness["blocked"] is False
    assert packet.payload["execution_authority"] == "none"
    assert any(
        attempt["source_name"] == "twitter"
        and attempt["status"] == "packet_written"
        and attempt["cost_tier"] == "connected_mcp_read"
        for attempt in result.route_attempts
    )


def test_twitter_mcp_route_is_social_sentiment_not_market_news():
    config = load_provider_fallback_config()

    market_news_sources = {
        candidate["source_name"] for candidate in config["fallbacks"]["market_news"]
    }
    social_sources = {
        candidate["source_name"] for candidate in config["fallbacks"]["social_sentiment"]
    }

    assert "twitter" not in market_news_sources
    assert "twitter" in social_sources


def test_ticker_provider_bundle_blocks_twitter_when_mcp_recent_search_unauthorized(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        orchestrator,
        "fetch_twitter_recent_search_packet",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            orchestrator.OfficialDataError(
                "twitter-research MCP failed: Unauthorized recent search access"
            )
        ),
    )

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("social_sentiment",),
        disabled_sources={
            "facebook",
            "google_news_rss",
            "instagram",
            "linkedin",
            "official_cache",
            "reddit",
            "reddit_watchlist",
            "social_watchlist",
        },
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["twitter"]
    assert result.packets[0].freshness["blocked"] is True
    assert "twitter-research" in result.packets[0].payload["reason"]
    assert "Unauthorized" in result.packets[0].payload["reason"]


def test_ticker_provider_bundle_uses_yfinance_price_context(monkeypatch, tmp_path):
    monkeypatch.setattr(
        orchestrator,
        "_fetch_yfinance_quote_price_context",
        lambda symbol, **kwargs: _packet(
            "yfinance",
            evidence_type="quote_price_context",
            symbol=symbol,
        ),
    )

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("quote_price_context",),
        disabled_sources={"broker_snapshot", "official_cache", "finnhub", "tiingo", "fmp", "alpha_vantage"},
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["yfinance"]
    assert result.packets[0].symbol == "NVDA"
    assert any(
        attempt["source_name"] == "yfinance"
        and attempt["status"] == "packet_written"
        and attempt["cost_tier"] == "free_unmetered"
        for attempt in result.route_attempts
    )


def test_ticker_provider_bundle_uses_sanitized_broker_snapshot(tmp_path):
    supervisor_dir = tmp_path / "hourly"
    supervisor_dir.mkdir()
    packet_path = supervisor_dir / "hourly-supervisor-20260604-150000-000000.json"
    packet_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-04T15:00:00-05:00",
                "decision": "hold",
                "live_exposure": "114.99",
                "issues": [],
                "submitted": [
                    {
                        "symbol": "AMZN",
                        "side": "buy",
                        "qty": "0.1",
                        "client_order_id": "do-not-copy",
                        "id": "broker-secret-id",
                        "status": "filled",
                    }
                ],
                "reconciled_orders": [],
                "portfolio": {
                    "market_session": "after_close",
                    "live": {
                        "status": "ACTIVE",
                        "buying_power": "86.38",
                        "equity": "200.07",
                        "portfolio_value": "200.07",
                        "cash": "86.38",
                        "exposure": "114.99",
                        "positions": [
                            {
                                "symbol": "AMZN",
                                "qty": "0.096770947",
                                "market_value": "24.52",
                                "cost_basis": "25.00",
                                "unrealized_pl": "-0.47",
                                "unrealized_plpc": "-1.89",
                                "current_price": "253.46",
                                "avg_entry_price": "258.34",
                            }
                        ],
                        "open_orders": [
                            {
                                "symbol": "AMZN",
                                "side": "sell",
                                "qty": "0.096770947",
                                "client_order_id": "also-do-not-copy",
                                "id": "order-id",
                                "status": "new",
                            }
                        ],
                    },
                    "paper": {
                        "status": "ACTIVE",
                        "buying_power": "338293.18",
                        "positions": [],
                        "open_orders": [],
                    },
                    "ranked_candidates": [
                        {
                            "symbol": "AMZN",
                            "score": "0.53",
                            "day_change_pct": "1.50",
                            "reason": "neutral drift; paper-first eligible",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    result = build_ticker_provider_research_packets(
        "amzn",
        evidence_needs=("quote_price_context",),
        broker_snapshot_dir=supervisor_dir,
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["broker_snapshot"]
    packet = result.packets[0]
    assert packet.analysis_only is True
    assert packet.payload["execution_authority"] == "none"
    assert packet.payload["source_packet_path"].endswith(packet_path.name)
    assert packet.payload["live_account"]["buying_power"] == "86.38"
    assert packet.payload["symbol_context"]["live_position"]["symbol"] == "AMZN"
    assert packet.payload["symbol_context"]["live_open_orders"][0]["side"] == "sell"
    assert packet.payload["symbol_context"]["ranked_candidate"]["score"] == "0.53"
    dumped = packet.model_dump_json()
    assert "do-not-copy" not in dumped
    assert "broker-secret-id" not in dumped
    assert any(
        attempt["source_name"] == "broker_snapshot"
        and attempt["status"] == "packet_written"
        and attempt["cost_tier"] == "connected_mcp_read"
        for attempt in result.route_attempts
    )


def test_ticker_provider_bundle_blocks_broker_snapshot_when_no_supervisor_packet(tmp_path):
    result = build_ticker_provider_research_packets(
        "amzn",
        evidence_needs=("quote_price_context",),
        broker_snapshot_dir=tmp_path / "missing",
        disabled_sources={"official_cache", "massive", "finnhub", "tiingo", "fmp", "alpha_vantage", "yfinance"},
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["broker_snapshot"]
    assert result.packets[0].freshness["blocked"] is True
    assert "supervisor" in result.packets[0].payload["reason"]


def test_ticker_provider_bundle_uses_official_cache_hit(tmp_path):
    cache_dir = tmp_path / "cache"
    cached = _packet("google_news_rss", symbol="NVDA")
    cache_path = orchestrator._cache_file_for_source(
        cache_dir,
        symbol="NVDA",
        evidence_need="market_news",
        source_name="google_news_rss",
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(cached.model_dump_json(), encoding="utf-8")

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("market_news",),
        disabled_sources={
            "alpaca_news",
            "crawlee",
            "eodhd",
            "finnhub",
            "fmp",
            "marketaux",
            "newsapi",
            "reddit",
            "reddit_watchlist",
            "scrapingbee",
            "tiingo",
            "twitter",
        },
        max_packets_per_need=1,
        cache_dir=cache_dir,
    )

    assert [packet.source_name for packet in result.packets] == ["official_cache"]
    assert result.packets[0].payload["cached_source_name"] == "google_news_rss"
    assert result.packets[0].payload["cached_packet_id"] == cached.packet_id
    assert any(
        attempt["source_name"] == "official_cache"
        and attempt["status"] == "packet_written"
        and attempt["blocked"] is False
        for attempt in result.route_attempts
    )


def test_ticker_provider_bundle_records_official_cache_miss(tmp_path):
    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("market_news",),
        disabled_sources={
            "alpaca_news",
            "crawlee",
            "eodhd",
            "finnhub",
            "fmp",
            "google_news_rss",
            "marketaux",
            "newsapi",
            "reddit",
            "reddit_watchlist",
            "scrapingbee",
            "tiingo",
            "twitter",
        },
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert result.packets == []
    assert any(
        attempt["source_name"] == "official_cache"
        and attempt["status"] == "cache_miss"
        for attempt in result.route_attempts
    )


def test_ticker_provider_bundle_uses_sec_edgar_for_fundamentals(monkeypatch, tmp_path):
    monkeypatch.setattr(
        orchestrator,
        "_fetch_sec_submissions_by_symbol",
        lambda symbol: _packet(
            "sec_edgar",
            evidence_type="fundamentals_profile",
            symbol=symbol,
        ),
    )

    result = build_ticker_provider_research_packets(
        "msft",
        evidence_needs=("fundamentals_profile",),
        disabled_sources={"official_cache", "fmp", "finnhub", "tiingo", "eodhd"},
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["sec_edgar"]
    assert result.packets[0].symbol == "MSFT"
    assert any(
        attempt["source_name"] == "sec_edgar"
        and attempt["status"] == "packet_written"
        and attempt["cost_tier"] == "free_unmetered"
        for attempt in result.route_attempts
    )


def test_ticker_provider_bundle_uses_crawlee_for_crawler_research(monkeypatch, tmp_path):
    monkeypatch.setattr(
        orchestrator,
        "_fetch_crawlee_ticker_research",
        lambda symbol, evidence_need: _packet(
            "crawlee",
            evidence_type=evidence_need,
            symbol=symbol,
        ),
    )

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("crawler_research",),
        max_packets_per_need=1,
        cache_dir=tmp_path / "cache",
    )

    assert [packet.source_name for packet in result.packets] == ["crawlee"]
    assert result.packets[0].evidence_type == "crawler_research"
    assert any(
        attempt["source_name"] == "crawlee"
        and attempt["status"] == "packet_written"
        and attempt["cost_tier"] == "local_unlimited"
        for attempt in result.route_attempts
    )


def test_crawlee_ticker_research_wraps_allowlisted_crawler_packet(monkeypatch):
    def fake_crawl(*, run_id, target, policy):
        assert run_id == "ticker-provider-nvda-crawler_research"
        assert target == "https://www.sec.gov/cgi-bin/browse-edgar?CIK=NVDA&owner=exclude&action=getcompany"
        assert policy.allowed_domains == ("sec.gov",)
        return CrawlerRunPacket(
            run_id=run_id,
            crawler="crawlee_playwright",
            target=target,
            status="success",
            fetched_urls=[target],
            max_pages=policy.max_pages,
            robots_policy=policy.robots_policy,
            source_refs=[target],
            freshness={
                "target_policy": {"allowed": True, "hostname": "www.sec.gov"},
                "metrics": {"page_count": 1},
                "page_titles": {target: "SEC Company Search"},
            },
            tool_route="crawler:crawlee_playwright",
            redaction_status="redacted",
        )

    monkeypatch.setattr(orchestrator, "run_crawlee_research_packet", fake_crawl)

    packet = orchestrator._fetch_crawlee_ticker_research("NVDA", "crawler_research")

    assert packet.source_name == "crawlee"
    assert packet.evidence_type == "crawler_research"
    assert packet.symbol == "NVDA"
    assert packet.quality == "medium"
    assert packet.payload["crawler_status"] == "success"
    assert packet.payload["target_policy"]["allowed"] is True
    assert packet.freshness["blocked"] is False


def test_crawlee_provider_refreshes_failed_cache_after_runtime_repair(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    cached_failed = evidence_packet(
        source_name="crawlee",
        evidence_type="crawler_research",
        subject="NVDA",
        symbol="NVDA",
        source_ref="https://www.sec.gov/cgi-bin/browse-edgar?CIK=NVDA&owner=exclude&action=getcompany",
        payload={"crawler_status": "failed", "error_summary": "broken greenlet"},
        quality="unknown",
        tool_route="crawler:crawlee_playwright",
        freshness_extra={"blocked": True, "crawler_status": "failed"},
    )
    cache_path = orchestrator._cache_file_for_source(
        cache_dir,
        symbol="NVDA",
        evidence_need="crawler_research",
        source_name="crawlee",
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(cached_failed.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        orchestrator,
        "_fetch_crawlee_ticker_research",
        lambda symbol, evidence_need: _packet(
            "crawlee",
            evidence_type=evidence_need,
            symbol=symbol,
        ),
    )

    result = build_ticker_provider_research_packets(
        "nvda",
        evidence_needs=("crawler_research",),
        max_packets_per_need=1,
        cache_dir=cache_dir,
    )

    assert result.packets[0].packet_id != cached_failed.packet_id
    assert result.packets[0].quality == "medium"
    assert any(
        attempt["source_name"] == "crawlee"
        and attempt["status"] == "packet_written"
        and attempt["blocked"] is False
        and attempt["cache_state"] == "refreshed"
        for attempt in result.route_attempts
    )


def test_ticker_provider_bundle_cli_writes_source_and_summary_packets(monkeypatch, tmp_path):
    packet = _packet("google_news_rss", symbol="MSFT")
    summary = evidence_packet(
        source_name="ticker_provider_orchestrator",
        evidence_type="ticker_research_provider_bundle",
        subject="MSFT",
        symbol="MSFT",
        source_ref="local://test",
        payload={
            "symbol": "MSFT",
            "source_packet_ids": [packet.packet_id],
            "execution_authority": "none",
            "forbidden_effects": ["submit_order"],
        },
        quality="medium",
    )
    fake_result = TickerProviderResearchResult(
        symbol="MSFT",
        packets=[packet],
        summary_packet=summary,
        route_attempts=[
            {
                "evidence_need": "market_news",
                "source_name": "google_news_rss",
                "status": "packet_written",
            }
        ],
    )
    monkeypatch.setattr(
        cli_main,
        "build_ticker_provider_research_packets",
        lambda *args, **kwargs: fake_result,
    )

    result = runner.invoke(
        app,
        [
            "research",
            "ticker-provider-bundle",
            "--symbol",
            "msft",
            "--output-dir",
            str(tmp_path / "evidence"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["analysis_only"] is True
    assert payload["packet_count"] == 1
    assert payload["symbol"] == "MSFT"
    assert Path(payload["summary_packet_path"]).exists()
    assert payload["summary_packet"]["payload"]["execution_authority"] == "none"


def test_research_methodology_cards_cli_writes_analysis_only_packet(tmp_path):
    result = runner.invoke(
        app,
        [
            "research",
            "methodology-cards",
            "--output-dir",
            str(tmp_path / "evidence"),
            "--json-output",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    sleeves = {card["sleeve"] for card in payload["payload"]["cards"]}
    assert payload["analysis_only"] is True
    assert Path(payload["packet_path"]).exists()
    assert "breakout-continuation" in sleeves
    assert "pullback-support" in sleeves
    assert "earnings-drift" in sleeves
    assert "event-catalyst-continuation" in sleeves
    assert "news-sentiment-swing" in sleeves
    assert "pairs-comovement-residual" in sleeves
    assert "mean-reversion-swing" in sleeves
    assert "macro-regime-overlay" in sleeves
    assert "factor-quality-overlay" in sleeves
    assert "microstructure-execution-overlay" in sleeves
    assert payload["payload"]["execution_authority"] == "none"
    assert "submit_order" in payload["payload"]["forbidden_effects"]
    assert "options_overlays" in payload["payload"]["coverage_status"]["intentionally_deferred"]
    assert "current-aggressive" in payload["payload"]["coverage_status"]["active_order_paths"]
