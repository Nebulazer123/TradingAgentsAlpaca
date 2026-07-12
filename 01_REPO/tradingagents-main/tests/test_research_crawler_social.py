import datetime
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from tradingagents.research import crawler_runner
from tradingagents.research.crawler_policy import (
    CrawlerPolicy,
    crawler_run_packet,
    domain_allowed,
    evaluate_crawler_target,
)
from tradingagents.research.crawler_runner import (
    CrawlerRuntimeStatus,
    CrawlEvidence,
    run_crawlee_research_packet,
)
from tradingagents.research.market_structure import (
    build_intraday_margin_market_structure_packet,
)
from tradingagents.research.mirofish_handoff import build_mirofish_source_context_packet
from tradingagents.research.overnight_context import (
    build_overnight_prior_feed,
    build_overnight_research_context_packets,
    summarize_overnight_research_context,
    write_overnight_research_context,
)
from tradingagents.research.provider_fallbacks import (
    build_provider_fallback_packet,
    fallback_candidates_for_need,
    load_provider_fallback_config,
    select_available_fallbacks,
)
from tradingagents.research.reddit_watchlists import (
    REQUIRED_BUCKETS as REDDIT_REQUIRED_BUCKETS,
)
from tradingagents.research.reddit_watchlists import (
    build_reddit_watchlist_packet,
    classify_reddit_watch_url,
    compact_reddit_summary,
    flatten_reddit_watchlists,
    load_reddit_watchlist_config,
    should_open_raw_thread,
)
from tradingagents.research.release_calendar import build_release_calendar_packet
from tradingagents.research.social_anomaly import social_anomaly_packet
from tradingagents.research.social_watchlists import (
    FORBIDDEN_EFFECTS as SOCIAL_WATCH_FORBIDDEN_EFFECTS,
)
from tradingagents.research.social_watchlists import (
    build_social_watchlist_packet,
    classify_social_watch_url,
    flatten_social_watchlists,
    load_social_watchlist_config,
)
from tradingagents.research.tool_routing import validate_autonomous_research_route
from tradingagents.schemas.research import SocialAnomalyPacket


def test_crawler_allows_exact_and_subdomain_but_not_lookalike_domain():
    assert domain_allowed("www.sec.gov", ("sec.gov",)) is True
    assert domain_allowed("data.sec.gov", ("sec.gov",)) is True
    assert domain_allowed("sec.gov.evil.example", ("sec.gov",)) is False


def test_crawler_blocks_non_allowlisted_target_and_writes_packet():
    policy = CrawlerPolicy(allowed_domains=("sec.gov",), max_pages=3)

    packet = crawler_run_packet(
        run_id="crawl-test",
        target="https://example.com/thread",
        policy=policy,
    )

    assert packet.analysis_only is True
    assert packet.status == "blocked"
    assert packet.blocked_urls == ["https://example.com/thread"]
    assert packet.freshness["target_policy"]["reason"] == "target domain is not allowlisted"
    assert packet.tool_route == "crawler:crawlee_playwright"


def test_crawler_caps_fetched_urls_to_max_pages():
    policy = CrawlerPolicy(allowed_domains=("sec.gov",), max_pages=2)

    packet = crawler_run_packet(
        run_id="crawl-test",
        target="https://www.sec.gov/newsroom",
        policy=policy,
        fetched_urls=[
            "https://www.sec.gov/a",
            "https://www.sec.gov/b",
            "https://www.sec.gov/c",
        ],
    )

    assert packet.status == "success"
    assert packet.fetched_urls == [
        "https://www.sec.gov/a",
        "https://www.sec.gov/b",
    ]


def test_crawlee_runner_blocks_when_runtime_missing():
    packet = run_crawlee_research_packet(
        run_id="crawl-1",
        target="https://www.sec.gov/newsroom",
        policy=CrawlerPolicy(allowed_domains=("sec.gov",), max_pages=3),
        runtime_status=CrawlerRuntimeStatus(
            crawlee_available=False,
            playwright_available=False,
        ),
    )

    assert packet.status == "blocked"
    assert packet.blocked_urls == ["https://www.sec.gov/newsroom"]
    assert packet.freshness["blocked_reason"] == "Crawlee + Playwright runtime is not installed"
    assert packet.freshness["read_only"] is True


def test_crawler_runtime_status_includes_self_heal_install_guidance():
    status = CrawlerRuntimeStatus(
        crawlee_available=False,
        playwright_available=True,
    )

    payload = status.as_dict()

    assert payload["ready"] is False
    assert "uv pip install" in payload["install_commands"]["python_dependencies"]
    assert "playwright install chromium" in payload["install_commands"]["browser_binaries"]
    assert "install_crawlee_playwright_python_extra" in payload["self_heal_actions"]
    assert "Codex" in payload["operator_summary"]


def test_crawler_runtime_status_catches_broken_greenlet_dependency():
    status = CrawlerRuntimeStatus(
        crawlee_available=True,
        playwright_available=True,
        greenlet_available=False,
    )

    payload = status.as_dict()

    assert payload["ready"] is False
    assert payload["greenlet_available"] is False
    assert "repair_greenlet_dependency" in payload["self_heal_actions"]
    assert "greenlet" in payload["operator_summary"]


def test_crawlee_runner_uses_per_run_storage_and_restores_env(monkeypatch, tmp_path):
    seen_storage_dirs: list[str | None] = []

    async def fake_crawl(target: str, policy: CrawlerPolicy) -> CrawlEvidence:
        seen_storage_dirs.append(os.environ.get("CRAWLEE_STORAGE_DIR"))
        return CrawlEvidence(
            fetched_urls=[target],
            page_titles={target: "SEC Company Search"},
            metrics={"page_count": 1, "max_pages": policy.max_pages},
        )

    monkeypatch.setattr(crawler_runner, "_crawl_with_python_crawlee", fake_crawl)
    monkeypatch.setenv("CRAWLEE_STORAGE_DIR", "previous-storage")

    packet = run_crawlee_research_packet(
        run_id="ticker-provider-qcom-crawler_research",
        target="https://www.sec.gov/cgi-bin/browse-edgar?CIK=QCOM&owner=exclude&action=getcompany",
        policy=CrawlerPolicy(allowed_domains=("sec.gov",), max_pages=2),
        runtime_status=CrawlerRuntimeStatus(
            crawlee_available=True,
            playwright_available=True,
        ),
        storage_dir=tmp_path / "crawler-storage",
    )

    assert packet.status == "success"
    assert seen_storage_dirs == [
        str((tmp_path / "crawler-storage" / "ticker-provider-qcom-crawler_research").resolve())
    ]
    assert os.environ["CRAWLEE_STORAGE_DIR"] == "previous-storage"


def test_crawlee_runner_uses_injected_read_only_crawler():
    def fake_crawler(target, policy):
        assert policy.max_pages == 2
        return CrawlEvidence(
            fetched_urls=[target, "https://www.sec.gov/filings"],
            page_titles={target: "SEC News"},
            metrics={"page_count": 2},
        )

    packet = run_crawlee_research_packet(
        run_id="crawl-2",
        target="https://www.sec.gov/newsroom",
        policy=CrawlerPolicy(allowed_domains=("sec.gov",), max_pages=2),
        crawler=fake_crawler,
        runtime_status=CrawlerRuntimeStatus(
            crawlee_available=True,
            playwright_available=True,
        ),
    )

    assert packet.status == "success"
    assert packet.fetched_urls == ["https://www.sec.gov/newsroom", "https://www.sec.gov/filings"]
    assert packet.freshness["page_titles"]["https://www.sec.gov/newsroom"] == "SEC News"
    assert packet.tool_route == "crawler:crawlee_playwright"


def test_evaluate_crawler_target_rejects_missing_hostname():
    decision = evaluate_crawler_target("not-a-url", CrawlerPolicy(allowed_domains=("sec.gov",)))

    assert decision.allowed is False
    assert decision.reason == "target URL has no hostname"


def test_social_anomaly_packet_requires_read_only_route():
    packet = social_anomaly_packet(
        platform="reddit",
        query="MSFT pullback",
        route="composio:reddit",
        anomaly_type="attention_spike",
        severity="medium",
        summary="Mentions rose while official evidence stayed neutral.",
        symbol="msft",
        metrics={"mention_count": 42},
        evidence_refs=["https://reddit.example.test/thread/1"],
    )

    assert packet.analysis_only is True
    assert packet.symbol == "MSFT"
    assert packet.metrics["read_only_route"] == "composio:reddit"
    assert packet.tool_route == "composio:reddit"


def test_social_anomaly_packet_accepts_instagram_and_linkedin_read_routes():
    instagram = social_anomaly_packet(
        platform="instagram",
        query="AAPL comments",
        route="composio:instagram",
        anomaly_type="comment_sentiment_shift",
        summary="Comments changed tone under an official account post.",
    )
    linkedin = social_anomaly_packet(
        platform="linkedin",
        query="NVDA professional narrative",
        route="composio:linkedin",
        anomaly_type="professional_narrative_shift",
        summary="Official company-page discussion changed tone.",
    )

    assert instagram.analysis_only is True
    assert linkedin.analysis_only is True
    assert instagram.tool_route == "composio:instagram"
    assert linkedin.tool_route == "composio:linkedin"


def test_social_anomaly_packet_rejects_unapproved_route():
    with pytest.raises(ValueError):
        social_anomaly_packet(
            platform="reddit",
            query="MSFT",
            route="composio:reddit:write",
            anomaly_type="attention_spike",
            summary="bad route",
        )


def test_social_packet_schema_rejects_trade_intent_smuggling():
    with pytest.raises(ValidationError):
        SocialAnomalyPacket.model_validate(
            {
                "platform": "reddit",
                "anomaly_type": "attention_spike",
                "summary": "mentions rose",
                "analysis_only": True,
                "trade_intent": {"symbol": "MSFT", "side": "buy"},
            }
        )


def test_autonomous_tool_route_allows_reads_and_blocks_writes():
    read_decision = validate_autonomous_research_route("docker:twitter-research", "read")
    write_decision = validate_autonomous_research_route("composio:reddit", "post")
    unknown_decision = validate_autonomous_research_route("composio:gmail", "read")

    assert read_decision.allowed is True
    assert write_decision.allowed is False
    assert "write/post/send/trade" in write_decision.reason
    assert unknown_decision.allowed is False


def test_social_watchlist_config_is_read_only_and_preserves_dynamic_suggestions():
    config = load_social_watchlist_config()

    targets = flatten_social_watchlists(config)
    packet = build_social_watchlist_packet(config=config)

    assert targets
    assert packet.analysis_only is True
    assert packet.source_name == "social_watchlist"
    assert packet.payload["read_only"] is True
    assert "submit_order" in packet.payload["forbidden_effects"]
    assert "facebook_group_searches_to_rank" in packet.payload["dynamic_research_suggestions"]
    assert "recent post volume" in packet.payload["dynamic_research_suggestions"][
        "facebook_group_searches_to_rank"
    ]["selection_rule"]
    assert all(target.read_only for target in targets)
    assert all("submit_order" in target.forbidden_effects for target in targets)
    assert set(packet.payload["counts_by_platform"]) >= {"x", "facebook", "instagram", "linkedin"}


def test_social_watchlist_url_classifier_routes_known_platforms_to_read_only_tools():
    assert classify_social_watch_url("https://x.com/CNBC")[1] == "docker:twitter-research"
    assert classify_social_watch_url("https://www.facebook.com/CNBC/")[1] == "composio:facebook"
    assert classify_social_watch_url("https://www.instagram.com/cnbc/")[1] == "composio:instagram"
    assert classify_social_watch_url("https://www.linkedin.com/company/cnbc/")[1] == "composio:linkedin"

    with pytest.raises(ValueError):
        classify_social_watch_url("https://example.com/not-approved")


def test_social_watchlist_forbids_write_and_trade_effects():
    assert "post" in SOCIAL_WATCH_FORBIDDEN_EFFECTS
    assert "message" in SOCIAL_WATCH_FORBIDDEN_EFFECTS
    assert "submit_order" in SOCIAL_WATCH_FORBIDDEN_EFFECTS


def test_reddit_watchlist_config_has_required_recent_only_buckets():
    config = load_reddit_watchlist_config()

    targets = flatten_reddit_watchlists(config)
    packet = build_reddit_watchlist_packet(config=config)

    assert set(config["reddit_watchlists"]) == set(REDDIT_REQUIRED_BUCKETS)
    assert targets
    assert packet.analysis_only is True
    assert packet.source_name == "reddit_watchlist"
    assert packet.payload["read_only"] is True
    assert packet.payload["route"] == "composio:reddit"
    assert packet.payload["policy"]["default_recent_only"] is True
    assert packet.payload["policy"]["raw_comment_threads_by_default"] is False
    assert "retail_panic" in packet.payload["allowed_context_flags"]
    assert "submit_order" in packet.payload["policy"]["forbidden_effects"]
    assert set(packet.payload["counts_by_bucket"]) == set(REDDIT_REQUIRED_BUCKETS)
    assert all(target.recent_only for target in targets)
    assert all(target.raw_thread_default is False for target in targets)
    assert all(target.mode in {"subreddit_new", "reddit_search_new_day"} for target in targets)


def test_reddit_url_classifier_rejects_hot_and_stale_search_links():
    new_target = classify_reddit_watch_url("https://www.reddit.com/r/stocks/new/")
    search_target = classify_reddit_watch_url(
        "https://www.reddit.com/search/?q=stock%20market&sort=new&t=day"
    )

    assert new_target.subreddit == "stocks"
    assert new_target.mode == "subreddit_new"
    assert search_target.mode == "reddit_search_new_day"
    assert search_target.query == "stock market"
    with pytest.raises(ValueError):
        classify_reddit_watch_url("https://www.reddit.com/r/stocks/hot/")
    with pytest.raises(ValueError):
        classify_reddit_watch_url("https://www.reddit.com/search/?q=NVDA&sort=top&t=year")


def test_reddit_compact_summary_schema_and_drilldown_rules():
    summary = compact_reddit_summary(
        source_url="https://www.reddit.com/r/stocks/new/",
        subreddit="stocks",
        post_time="2026-06-01T12:00:00Z",
        post_title="NVDA selloff looks like buy the dip",
        post_url="https://www.reddit.com/r/stocks/comments/example/nvda/",
        ticker_mentions=["$nvda", "spy"],
        theme="buy_the_dip",
        sentiment="bullish",
        confidence=0.72,
        engagement={"upvotes": 123, "comments": 42},
        why_it_matters="Retail is discussing a pullback candidate already in the overnight list.",
        open_raw_thread=False,
    )

    assert summary.ticker_mentions == ["NVDA", "SPY"]
    assert summary.open_raw_thread is False
    assert should_open_raw_thread(summary) is False
    assert should_open_raw_thread(summary, trigger_reasons=["overnight_top_candidate"]) is True

    high_engagement_payload = summary.model_dump()
    high_engagement_payload["engagement"] = {"upvotes": 2000, "comments": 300}
    high_engagement = compact_reddit_summary(**high_engagement_payload)
    assert should_open_raw_thread(high_engagement) is True


def test_provider_fallbacks_prefer_unmetered_and_skip_depleted_api_sources():
    config = load_provider_fallback_config()

    candidates = fallback_candidates_for_need(
        "market_news",
        config=config,
        depleted_sources={"marketaux", "finnhub", "fmp", "eodhd"},
    )
    available = select_available_fallbacks(
        "market_news",
        config=config,
        depleted_sources={"marketaux", "finnhub", "fmp", "eodhd"},
    )
    packet = build_provider_fallback_packet(
        evidence_need="market_news",
        config=config,
        depleted_sources={"marketaux", "finnhub", "fmp", "eodhd"},
    )

    active_names = [candidate.source_name for candidate in available]
    social_active_names = [
        candidate.source_name
        for candidate in select_available_fallbacks("social_sentiment", config=config)
    ]
    skipped_names = [
        candidate.source_name for candidate in candidates if candidate.status == "depleted"
    ]
    assert "google_news_rss" in active_names
    assert "reddit_watchlist" in active_names
    assert "twitter" not in active_names
    assert "twitter" in social_active_names
    assert "marketaux" not in active_names
    assert set(skipped_names) >= {"marketaux", "finnhub", "fmp", "eodhd"}
    assert packet.analysis_only is True
    assert packet.source_name == "provider_fallback_policy"
    assert packet.payload["depletion_safe"] is True
    assert packet.payload["limited_api_behavior"] == "skip_when_depleted"
    assert "submit_order" in packet.payload["policy"]["forbidden_effects"]
    assert any(
        route["cost_tier"] in {"cache", "local_unlimited", "connected_mcp_read", "free_unmetered"}
        for route in packet.payload["preferred_free_or_mcp_routes"]
    )


def test_provider_fallbacks_have_backups_for_limited_sources():
    config = load_provider_fallback_config()

    for evidence_need, routes in config["fallbacks"].items():
        limited = {
            route["source_name"]
            for route in routes
            if route["cost_tier"] in {"free_limited", "paid_limited"}
        }
        preferred = {
            route["source_name"]
            for route in routes
            if route["cost_tier"] in {
                "cache",
                "local_unlimited",
                "connected_mcp_read",
                "free_unmetered",
            }
        }
        if limited:
            assert preferred, f"{evidence_need} lacks non-limited fallback routes"


def test_overnight_research_context_writes_provider_and_watchlist_packets(tmp_path):
    result = write_overnight_research_context(
        output_dir=tmp_path,
        depleted_sources={"marketaux", "finnhub"},
        disabled_sources={"scrapingbee"},
    )

    assert result.summary["analysis_only"] is True
    assert result.summary["execution_authority"] == "none"
    assert result.summary["packet_count"] == len(result.packets)
    assert result.prior_feed_path is not None
    assert result.prior_feed_path.exists()
    assert result.summary["prior_feed"]["schema"] == "overnight_prior_feed_v1"
    assert result.summary["prior_feed"]["path"] == str(result.prior_feed_path)
    assert result.summary["prior_feed"]["analysis_only"] is True
    assert result.summary["prior_feed"]["execution_authority"] == "none"
    assert "submit_order" in result.summary["prior_feed"]["forbidden_effects"]
    prior_feed = json.loads(result.prior_feed_path.read_text(encoding="utf-8"))
    assert prior_feed["schema"] == "overnight_prior_feed_v1"
    assert prior_feed["execution_authority"] == "none"
    assert prior_feed["packet_count"] == len(result.packets)
    assert prior_feed["prior_applied"] is True
    assert prior_feed["dedupe_applied"] is True
    assert prior_feed["input_packet_ref_count"] == len(result.packets)
    assert prior_feed["unique_packet_ref_count"] == len(result.packets)
    assert prior_feed["duplicate_packet_ref_count"] == 0
    assert "source_packet_refs" in prior_feed["carry_forward_scope"]
    assert "submit_order" in prior_feed["forbidden_effects"]
    assert set(result.summary["provider_fallbacks"]["market_news"]["skipped_source_names"]) >= {
        "finnhub",
        "marketaux",
        "scrapingbee",
    }
    assert "google_news_rss" in result.summary["provider_fallbacks"]["market_news"]["active_source_names"]
    assert "reddit" in result.summary["watchlists"]
    assert "social" in result.summary["watchlists"]
    assert result.summary["mirofish_handoff"]["status"] in {
        "pending_final_handoff",
        "final_handoff_available",
        "blocked_missing_scaffold",
    }
    assert result.summary["mirofish_handoff"]["execution_authority"] == "none"
    assert "submit_order" in result.summary["mirofish_handoff"]["forbidden_effects"]
    assert result.summary["watchlists"]["reddit"]["raw_comment_threads_by_default"] is False


def test_overnight_prior_feed_dedupes_packet_refs_and_marks_applied_state():
    prior_feed = build_overnight_prior_feed(
        {
            "packet_count": 4,
            "blocked_packets": [],
            "packet_refs": ["packet-a", "packet-b", "packet-a", "", "packet-c"],
            "provider_fallbacks": {"market_news": {"active_source_names": ["google_news_rss"]}},
            "watchlists": {},
            "mirofish_handoff": {},
            "methodology": {},
        }
    )

    assert prior_feed["packet_refs"] == ["packet-a", "packet-b", "packet-c"]
    assert prior_feed["prior_applied"] is True
    assert prior_feed["dedupe_applied"] is True
    assert prior_feed["input_packet_ref_count"] == 4
    assert prior_feed["unique_packet_ref_count"] == 3
    assert prior_feed["duplicate_packet_ref_count"] == 1
    assert prior_feed["carry_forward_scope"] == ["source_packet_refs", "provider_fallbacks"]


def test_overnight_summary_carries_structured_mirofish_attention_priors(monkeypatch, tmp_path):
    scaffold = tmp_path / "MIROFISH_PENDING_LEARNING_SCAFFOLD.md"
    final_handoff = tmp_path / "MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md"
    full_report = tmp_path / "full_report.md"
    deep_review = tmp_path / "deep-research-report (33).md"
    scaffold.write_text("# MiroFish Pending Learning Scaffold\n", encoding="utf-8")
    full_report.write_text(
        "\n".join(
            [
                "# Full report",
                "```json",
                (
                    '{"scenario_branches":{"institutional_liquidity_response":'
                    '{"stance":"fade_or_absorb"}},'
                    '"key_state_variables_and_signals":{"AI_bot_copycat_index":'
                    '{"description":"Measures convergence of automated traders on simplified narratives."}},'
                    '"risk_gates_and_false_positive_filters":{"liquidity_trap":'
                    '"Institutional desks fading novice clustering."},'
                    '"validation_tasks_for_real_market_data":['
                    '"Validate AI-bot correlation spikes against independent volume confirmation and institutional participation."]}'
                ),
                "```",
            ]
        ),
        encoding="utf-8",
    )
    deep_review.write_text(
        "\n".join(
            [
                "# Mirror Fish market prediction review",
                "",
                "### Directional outlook",
                "",
                "| Market / sector | My base case for the next 7-10 days | Probability | Why |",
                "|---|---|---:|---|",
                "| Semiconductors | Underperform broad market | 60% | AI expectations are crowded |",
                "",
                "## Actionable implications and risk management",
                "",
                "### Practical decision table",
                "",
                "| Situation | Better response | Worse response |",
                "|---|---|---|",
                "| Long semis/AI into data | Reduce size or hedge | Assume AI overrides rates |",
                "",
                "## Timeline and limitations",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "tradingagents.research.mirofish_handoff.DEFAULT_DEEP_RESEARCH_REVIEW_PATHS",
        (str(deep_review),),
    )
    final_handoff.write_text(
        "\n".join(
            [
                "# MiroFish Final TradingAgents Handoff",
                "",
                "## Machine-readable advisory packet",
                "",
                "```json",
                json.dumps(
                    {
                        "status": "final_advisory_no_execution_authority",
                        "execution_authority": "none",
                        "report_id": "report_9c77ca2557ae",
                        "staleness": {
                            "valid_window": "2026-06-04 through 2026-06-13",
                            "expires_after": "2026-06-13 market close unless refreshed",
                            "requires_refresh": ["before premarket", "at market open"],
                        },
                        "source_artifacts": {
                            "review_packet_zip": "C:\\reports\\review_packet.zip",
                            "acceptance_decision": "C:\\docs\\acceptance.md",
                            "full_report": str(full_report),
                        },
                        "ticker_attention_map": {
                            "TSLA": {
                                "category": "bot_correlation",
                                "hypothesis": "copycat attention watch",
                            }
                        },
                        "retail_flow_hypotheses": [
                            {
                                "description": "TSLA and QQQ retail-copycat flow",
                                "symbols": ["TSLA", "QQQ"],
                                "probability": 0.31,
                            }
                        ],
                    }
                ),
                "```",
                "",
                "## How TradingAgents Should Use This",
            ]
        ),
        encoding="utf-8",
    )
    packet = build_mirofish_source_context_packet(
        scaffold_path=scaffold,
        final_handoff_path=final_handoff,
    )

    summary = summarize_overnight_research_context([packet])
    mirofish = summary["mirofish_handoff"]

    assert mirofish["ticker_attention_symbols"] == ["TSLA"]
    assert mirofish["ticker_attention_map"]["TSLA"]["category"] == "bot_correlation"
    assert mirofish["advisory_valid_window"] == "2026-06-04 through 2026-06-13"
    assert mirofish["advisory_expires_after"] == "2026-06-13 market close unless refreshed"
    assert mirofish["advisory_requires_refresh"] == ["before premarket", "at market open"]
    assert mirofish["review_packet_zip"] == "C:\\reports\\review_packet.zip"
    assert mirofish["acceptance_decision_path"] == "C:\\docs\\acceptance.md"
    assert mirofish["full_report_highlights"]["institutional_liquidity_response"]["stance"] == "fade_or_absorb"
    assert "AI-bot copycat spikes" in mirofish["full_report_core_filter"]
    assert mirofish["mirofish_advisory_gate_action"] == "allow"
    assert mirofish["deep_research_review_available"] is True
    assert mirofish["deep_research_review_report_id"] == "deep_research_report_33"
    assert "macro-first" in mirofish["deep_research_review_core_filter"]
    assert "QQQ_or_Nasdaq" in mirofish["deep_research_review_stock_selection_biases"]["negative_bias"]
    assert mirofish["deep_research_review"]["directional_outlook"][0]["market_or_sector"] == "Semiconductors"
    assert mirofish["retail_flow_hypotheses"][0]["symbols"] == ["TSLA", "QQQ"]
    assert mirofish["retail_flow_hypothesis_count"] == 1
    assert mirofish["execution_authority"] == "none"


def test_release_calendar_packet_marks_active_event_window():
    packet = build_release_calendar_packet(
        now=datetime.datetime(2026, 6, 4, 14, 0, tzinfo=datetime.timezone.utc),
        lookahead_days=7,
    )

    assert packet.analysis_only is True
    assert packet.source_name == "official_release_calendar"
    assert packet.payload["event_risk_state"] == "active_release_window"
    assert packet.payload["planner_flags"]["macro_event_risk"] is True
    assert packet.payload["planner_flags"]["requires_fresh_post_release_validation"] is True
    assert packet.payload["policy"]["execution_authority"] == "none"
    assert "submit_order" in packet.payload["policy"]["forbidden_effects"]
    assert any(
        event["event_id"] == "bls-employment-situation-2026-06-05"
        for event in packet.payload["active_event_windows"]
    )


def test_overnight_research_context_includes_release_calendar_packet(tmp_path):
    result = write_overnight_research_context(
        output_dir=tmp_path,
        depleted_sources={"marketaux"},
        disabled_sources=set(),
    )

    assert "release_calendar" in result.summary["watchlists"]
    calendar = result.summary["watchlists"]["release_calendar"]
    assert calendar["blocked"] is False
    assert "macro_event_risk" in calendar["planner_flags"]
    assert all(packet.analysis_only is True for packet in result.packets)
    for ref in result.summary["packet_refs"]:
        assert ref["path"]
        assert Path(ref["path"]).exists()


def test_overnight_research_context_threads_source_quality_into_provider_fallbacks(tmp_path):
    review_path = tmp_path / "source-quality-latest.json"
    review_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-07T04:28:05+00:00",
                "source_count": 2,
                "stale_count": 1,
                "stale_downrank_count": 1,
                "stale_safe_count": 1,
                "stale_needs_refresh_count": 0,
                "blocked_count": 0,
                "missing_or_invalid_count": 0,
                "unreadable_count": 0,
                "quality_counts": {"medium": 2},
                "freshness_counts": {"fresh": 1, "stale": 1},
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
                ],
            }
        ),
        encoding="utf-8",
    )

    result = write_overnight_research_context(
        output_dir=tmp_path / "context",
        source_quality_review_path=review_path,
        evidence_needs=("market_news",),
        include_reddit=False,
        include_release_calendar=False,
        include_social_watchlists=False,
        include_methodology=False,
        include_market_structure=False,
        include_mirofish_handoff=False,
    )

    market_news = result.summary["provider_fallbacks"]["market_news"]
    source_quality = result.summary["watchlists"]["source_quality"]
    prior_feed = json.loads(result.prior_feed_path.read_text(encoding="utf-8"))

    assert market_news["source_quality_ordering_enabled"] is True
    assert market_news["scored_active_source_count"] >= 2
    assert source_quality["status"] == "available"
    assert source_quality["source_quality_ordering_enabled"] is True
    assert source_quality["scored_source_count"] == 2
    assert source_quality["stale_needs_refresh_count"] == 0
    assert source_quality["next_action"] == "use_review_for_downranking"
    assert prior_feed["watchlists"]["source_quality"]["review_path"] == str(review_path)
    assert prior_feed["watchlists"]["source_quality"]["source_quality_ordering_enabled"] is True
    assert result.summary["execution_authority"] == "none"


def test_intraday_margin_market_structure_packet_removes_old_pdt_gates():
    packet = build_intraday_margin_market_structure_packet(
        now=datetime.datetime(2026, 6, 4, 15, 0, tzinfo=datetime.timezone.utc),
    )

    flags = packet.payload["planner_flags"]
    rule = packet.payload["rule_interpretation"]
    assert packet.analysis_only is True
    assert packet.source_name == "market_structure_policy"
    assert packet.payload["reform_active"] is True
    assert flags["ignore_old_pdt_trade_count_gate"] is True
    assert flags["ignore_old_25000_pdt_minimum_gate"] is True
    assert flags["mirrorfish_society_reaction_required"] is True
    assert rule["old_three_day_trades_in_five_business_days_counter_removed"] is True
    assert rule["old_25000_pdt_minimum_removed"] is True
    assert "submit_order" in packet.payload["policy"]["forbidden_effects"]


def test_overnight_research_context_includes_market_structure_transition(tmp_path):
    result = write_overnight_research_context(output_dir=tmp_path)

    market_structure = result.summary["watchlists"]["market_structure"]
    assert market_structure["reform_active"] in {True, False}
    assert market_structure["planner_flags"]["ignore_old_pdt_trade_count_gate"] is True
    assert market_structure["planner_flags"]["crowd_ai_bot_unpredictability"] is True
    assert market_structure["rule_interpretation"]["old_day_trading_buying_power_logic_removed"] is True
    assert all(packet.analysis_only is True for packet in result.packets)


def test_overnight_research_context_fails_soft_when_config_is_missing(tmp_path):
    packets = build_overnight_research_context_packets(
        provider_config_path=tmp_path / "missing-provider-config.json",
        evidence_needs=("market_news",),
        include_reddit=False,
        include_social_watchlists=False,
    )

    provider_packets = [
        packet for packet in packets if packet.source_name == "provider_fallback_policy"
    ]

    assert len(provider_packets) == 1
    assert all(packet.analysis_only is True for packet in packets)
    assert {packet.source_name for packet in packets} >= {
        "provider_fallback_policy",
        "mirofish_handoff",
        "strategy_methodology_cards",
        "chatgpt_deep_research_protocol",
    }
    assert provider_packets[0].redaction_status == "blocked"
    assert provider_packets[0].payload["status"] == "blocked"
