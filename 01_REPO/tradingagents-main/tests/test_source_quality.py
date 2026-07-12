import datetime
import json
from pathlib import Path

from tradingagents.evals.source_quality import (
    build_compact_source_quality_review,
    build_source_quality_review,
    discover_source_packet_paths,
    write_source_quality_review,
)
from tradingagents.research.source_quality import (
    FORBIDDEN_EFFECTS,
    apply_source_quality,
    assess_source_quality,
    build_source_quality_strengths,
    load_source_quality_strengths,
)
from tradingagents.schemas.research import SourceEvidencePacket
from tradingagents.schemas.trading import SourceProvenance

UTC = datetime.timezone.utc


def test_official_source_is_high_quality_when_fresh():
    now = datetime.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    decision = assess_source_quality(
        "sec_edgar",
        as_of="2026-06-01T10:00:00+00:00",
        current_time=now,
    )

    assert decision.quality == "high"
    assert decision.freshness_status == "fresh"
    assert "veto" in decision.allowed_effects
    assert decision.forbidden_effects == FORBIDDEN_EFFECTS


def test_stale_official_source_downgrades_but_stays_advisory():
    now = datetime.datetime(2026, 6, 5, 12, 0, tzinfo=UTC)

    decision = assess_source_quality(
        "fred",
        as_of="2026-06-01T10:00:00+00:00",
        current_time=now,
    )

    assert decision.quality == "medium"
    assert decision.freshness_status == "stale"
    assert "submit_order" in decision.forbidden_effects
    assert "create_trade_intent" in decision.forbidden_effects


def test_social_and_yfinance_sources_are_low_authority():
    reddit = assess_source_quality(
        "reddit",
        as_of="2026-06-01T10:00:00+00:00",
        current_time=datetime.datetime(2026, 6, 1, 11, 0, tzinfo=UTC),
    )
    yfinance = assess_source_quality(
        "yfinance",
        as_of="2026-06-01T10:00:00+00:00",
        current_time=datetime.datetime(2026, 6, 1, 11, 0, tzinfo=UTC),
    )
    yfinance_options = assess_source_quality(
        "yfinance_options",
        as_of="2026-06-01T10:00:00+00:00",
        current_time=datetime.datetime(2026, 6, 1, 11, 0, tzinfo=UTC),
    )
    yfinance_short_interest = assess_source_quality(
        "yfinance_short_interest",
        as_of="2026-06-01T10:00:00+00:00",
        current_time=datetime.datetime(2026, 6, 1, 11, 0, tzinfo=UTC),
    )

    assert reddit.quality == "low"
    assert yfinance.quality == "low"
    assert yfinance_options.quality == "low"
    assert yfinance_short_interest.quality == "low"
    assert "downrank" in yfinance_options.allowed_effects
    assert "downrank" in yfinance_short_interest.allowed_effects
    assert "request_more_research" in reddit.allowed_effects
    assert "submit_order" in yfinance.forbidden_effects


def test_optional_news_and_scrape_sources_are_advisory_only():
    now = datetime.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    marketaux = assess_source_quality(
        "marketaux",
        as_of="2026-06-01T11:00:00+00:00",
        current_time=now,
    )
    alpaca_news = assess_source_quality(
        "alpaca_news",
        as_of="2026-06-01T11:00:00+00:00",
        current_time=now,
    )
    newsapi = assess_source_quality(
        "newsapi",
        as_of="2026-06-01T11:00:00+00:00",
        current_time=now,
    )
    tiingo = assess_source_quality(
        "tiingo",
        as_of="2026-06-01T11:00:00+00:00",
        current_time=now,
    )
    methodology = assess_source_quality(
        "strategy_methodology_cards",
        as_of="2026-06-01T11:00:00+00:00",
        current_time=now,
    )
    google_news = assess_source_quality(
        "google_news_rss",
        as_of="2026-06-01T11:00:00+00:00",
        current_time=now,
    )
    scrapingbee = assess_source_quality(
        "scrapingbee",
        as_of="2026-06-01T11:00:00+00:00",
        current_time=now,
    )
    watchlist = assess_source_quality(
        "social_watchlist",
        as_of="2026-06-01T11:00:00+00:00",
        current_time=now,
    )
    reddit_watchlist = assess_source_quality(
        "reddit_watchlist",
        as_of="2026-06-01T11:00:00+00:00",
        current_time=now,
    )
    provider_fallback = assess_source_quality(
        "provider_fallback_policy",
        as_of="2026-06-01T11:00:00+00:00",
        current_time=now,
    )
    ticker_provider = assess_source_quality(
        "ticker_provider_orchestrator",
        as_of="2026-06-01T11:00:00+00:00",
        current_time=now,
    )
    official_cache = assess_source_quality(
        "official_cache",
        as_of="2026-06-01T11:00:00+00:00",
        current_time=now,
    )
    crawlee = assess_source_quality(
        "crawlee",
        as_of="2026-06-01T11:00:00+00:00",
        current_time=now,
    )
    broker_snapshot = assess_source_quality(
        "broker_snapshot",
        as_of="2026-06-01T11:30:00+00:00",
        current_time=now,
    )

    assert marketaux.quality == "medium"
    assert alpaca_news.quality == "medium"
    assert newsapi.quality == "medium"
    assert tiingo.quality == "medium"
    assert methodology.quality == "medium"
    assert google_news.quality == "low"
    assert scrapingbee.quality == "low"
    assert watchlist.quality == "low"
    assert reddit_watchlist.quality == "low"
    assert provider_fallback.quality == "medium"
    assert ticker_provider.quality == "medium"
    assert official_cache.quality == "medium"
    assert crawlee.quality == "medium"
    assert broker_snapshot.quality == "medium"
    assert marketaux.role == "supplemental_market_news_sentiment_context"
    assert alpaca_news.role == "execution_adjacent_read_only_news_context"
    assert newsapi.role == "supplemental_broad_news_discovery_context"
    assert tiingo.role == "supplemental_price_news_metadata_context"
    assert methodology.role == "local_methodology_contract_context"
    assert reddit_watchlist.role == "read_only_reddit_market_sentiment_watchlist"
    assert provider_fallback.role == "read_only_research_source_fallback_policy"
    assert ticker_provider.role == "read_only_ticker_provider_route_summary"
    assert official_cache.role == "read_only_cached_evidence_context"
    assert crawlee.role == "read_only_allowlisted_crawler_context"
    assert broker_snapshot.role == "read_only_sanitized_broker_account_context"
    assert "submit_order" in marketaux.forbidden_effects
    assert "submit_order" in alpaca_news.forbidden_effects
    assert "create_trade_intent" in methodology.forbidden_effects
    assert "create_trade_intent" in google_news.forbidden_effects
    assert "downrank" in google_news.allowed_effects
    assert scrapingbee.allowed_effects == ("request_more_research",)
    assert "downrank" in crawlee.allowed_effects
    assert broker_snapshot.allowed_effects == ("request_more_research",)


def test_apply_source_quality_updates_packet_freshness_and_provenance():
    packet = SourceEvidencePacket(
        source_name="fred",
        evidence_type="series_observations",
        subject="GDP",
        as_of="2026-06-01T10:00:00+00:00",
        sources=[
            SourceProvenance(
                source="fred",
                as_of="2026-06-01T10:00:00+00:00",
                path="https://api.stlouisfed.org/fred/series/observations?series_id=GDP",
                quality="unknown",
            )
        ],
        source_refs=["https://api.stlouisfed.org/fred/series/observations?series_id=GDP"],
        payload={"observations": []},
    )

    updated = apply_source_quality(
        packet,
        current_time=datetime.datetime(2026, 6, 4, 12, 0, tzinfo=UTC),
    )

    assert updated.quality == "medium"
    assert updated.sources[0].quality == "medium"
    assert updated.freshness["stale"] is True
    assert updated.freshness["source_quality"]["role"] == "official_macro_context"


def test_source_quality_handles_missing_invalid_future_and_unknown_sources():
    now = datetime.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    missing = assess_source_quality("sec_edgar", as_of=None, current_time=now)
    invalid = assess_source_quality("sec_edgar", as_of="not-a-date", current_time=now)
    future = assess_source_quality(
        "sec_edgar",
        as_of="2026-06-02T12:00:00+00:00",
        current_time=now,
    )
    unknown = assess_source_quality(
        "mystery_source",
        as_of="2026-06-01T11:00:00+00:00",
        current_time=now,
    )

    assert missing.freshness_status == "missing_or_invalid"
    assert missing.quality == "unknown"
    assert invalid.freshness_status == "missing_or_invalid"
    assert future.freshness_status == "fresh"
    assert unknown.quality == "unknown"
    assert unknown.role == "unclassified_context"


def test_source_quality_review_writes_analysis_only_packet(tmp_path):
    fresh = SourceEvidencePacket(
        source_name="sec_edgar",
        evidence_type="filing",
        subject="NVDA 10-Q",
        symbol="NVDA",
        as_of="2026-06-01T11:00:00+00:00",
        payload={"form": "10-Q"},
    )
    stale = SourceEvidencePacket(
        source_name="fred",
        evidence_type="macro",
        subject="GDP",
        as_of="2026-05-20T11:00:00+00:00",
        payload={"series": "GDP"},
    )
    fresh_path = tmp_path / "fresh.json"
    stale_path = tmp_path / "stale.json"
    fresh_path.write_text(fresh.model_dump_json(indent=2), encoding="utf-8")
    stale_path.write_text(stale.model_dump_json(indent=2), encoding="utf-8")

    review = build_source_quality_review(
        [fresh_path, stale_path],
        current_time=datetime.datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )
    written = write_source_quality_review(review, output_dir=tmp_path / "review")
    compact_path = Path(written["json_path"]).with_suffix(".compact.json")
    latest_compact_path = tmp_path / "review" / "latest-compact.json"

    assert review["analysis_only"] is True
    assert review["can_submit_orders"] is False
    assert review["execution_authority"] == "none"
    assert review["source_count"] == 2
    assert review["quality_counts"]["high"] == 1
    assert review["freshness_counts"]["stale"] == 1
    assert review["stale_downrank_count"] == 1
    assert review["stale_low_or_unknown_count"] == 0
    assert review["stale_safe_count"] == 1
    assert review["stale_needs_refresh_count"] == 0
    assert review["blocked_count"] == 0
    assert "submit_order" in review["forbidden_effects"]
    assert Path(written["json_path"]).exists()
    assert compact_path.exists()
    assert latest_compact_path.exists()
    saved = json.loads(Path(written["json_path"]).read_text(encoding="utf-8"))
    compact = json.loads(compact_path.read_text(encoding="utf-8"))
    latest_compact = json.loads(latest_compact_path.read_text(encoding="utf-8"))
    assert saved["source_count"] == 2
    assert compact == latest_compact
    assert compact["raw_packet_path"] == written["json_path"]
    assert compact["source_count"] == 2
    assert "decisions" not in compact


def test_compact_source_quality_review_keeps_counts_and_paths_without_decisions(tmp_path):
    fresh = SourceEvidencePacket(
        source_name="sec_edgar",
        evidence_type="filing",
        subject="NVDA 10-Q",
        symbol="NVDA",
        as_of="2026-06-01T11:00:00+00:00",
        payload={"form": "10-Q"},
    )
    stale = SourceEvidencePacket(
        source_name="unknown_blog",
        evidence_type="social",
        subject="NVDA chatter",
        symbol="NVDA",
        as_of="2026-05-20T11:00:00+00:00",
        payload={"blocked": True},
    )
    fresh_path = tmp_path / "fresh.json"
    stale_path = tmp_path / "stale.json"
    fresh_path.write_text(fresh.model_dump_json(indent=2), encoding="utf-8")
    stale_path.write_text(stale.model_dump_json(indent=2), encoding="utf-8")

    review = build_source_quality_review(
        [fresh_path, stale_path],
        current_time=datetime.datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )
    written = write_source_quality_review(review, output_dir=tmp_path / "review")
    compact = build_compact_source_quality_review(written)

    assert compact["schema"] == "compact_source_quality_review_v1"
    assert compact["analysis_only"] is True
    assert compact["can_submit_orders"] is False
    assert compact["execution_authority"] == "none"
    assert compact["raw_packet_path"] == written["json_path"]
    assert compact["markdown_path"] == written["markdown_path"]
    assert compact["counts"] == {
        "source_count": 2,
        "unreadable_count": 0,
        "stale_count": 1,
        "stale_downrank_count": 0,
        "stale_low_or_unknown_count": 1,
        "stale_safe_count": 1,
        "stale_needs_refresh_count": 0,
        "blocked_count": 1,
        "missing_or_invalid_count": 0,
    }
    assert compact["quality_counts"]["high"] == 1
    assert compact["freshness_counts"]["stale"] == 1
    assert compact["sample_decisions"][0]["source_name"] == "unknown_blog"
    assert compact["sample_decisions"][0]["blocked"] is True
    assert "decisions" not in compact


def test_source_quality_strengths_rank_fresh_higher_than_stale(tmp_path):
    review = {
        "decisions": [
            {
                "source_name": "google_news_rss",
                "quality": "medium",
                "freshness_status": "fresh",
                "blocked": False,
                "allowed_effects": ["downrank", "request_more_research"],
            },
            {
                "source_name": "alpaca_news",
                "quality": "medium",
                "freshness_status": "stale",
                "blocked": False,
                "allowed_effects": ["downrank", "request_more_research"],
            },
            {
                "source_name": "fmp",
                "quality": "medium",
                "freshness_status": "fresh",
                "blocked": True,
                "allowed_effects": ["downrank", "request_more_research"],
            },
        ]
    }
    review_path = tmp_path / "latest.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")

    strengths = build_source_quality_strengths(review)
    loaded = load_source_quality_strengths(review_path)

    assert strengths["google_news_rss"].score > strengths["alpaca_news"].score
    assert strengths["google_news_rss"].score > strengths["fmp"].score
    assert loaded["google_news_rss"].score == strengths["google_news_rss"].score
    assert loaded["alpaca_news"].stale_count == 1
    assert loaded["fmp"].blocked_count == 1
    assert loaded["google_news_rss"].model_dump()["decision_count"] == 1


def test_source_quality_discovery_skips_fixture_and_sample_files(tmp_path):
    root = tmp_path / "research_batches"
    root.mkdir()
    (root / "current_research.json").write_text("{}", encoding="utf-8")
    (root / "walk_forward_fixture_from_overnight_sample.json").write_text("{}", encoding="utf-8")
    (root / "collected_returns_sample.json").write_text("{}", encoding="utf-8")

    paths = discover_source_packet_paths([root])

    assert [path.name for path in paths] == ["current_research.json"]
