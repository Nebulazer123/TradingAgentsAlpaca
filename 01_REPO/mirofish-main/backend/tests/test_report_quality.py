from app.services.report_quality import (
    MIRROR_FISH_REQUIRED_SECTIONS,
    build_section_queries,
    evaluate_section_quality,
)


def test_required_outline_has_twenty_sections():
    assert len(MIRROR_FISH_REQUIRED_SECTIONS) == 20
    assert MIRROR_FISH_REQUIRED_SECTIONS[7] == "Broker/platform confusion patterns"


def test_section_queries_are_compact_english():
    queries = build_section_queries("Macro override risks")
    assert queries
    assert all(len(q) <= 260 for q in queries)
    assert not any("模拟" in q or "报告" in q for q in queries)


def test_company_executive_queries_include_specific_enrichment_targets():
    queries = build_section_queries("Company and tech-executive narrative map")
    joined = " ".join(queries)

    assert queries[0].startswith("Company and tech-executive narratives around PDT transition")
    assert "Apple WWDC" in joined
    assert "Nvidia" in joined
    assert "Broadcom" in joined
    assert "HOOD BULL" in joined
    assert "investor relations" in joined


def test_validation_queries_include_real_market_gate_targets():
    queries = build_section_queries("Recommended validation tasks using real market data")
    joined = " ".join(queries)

    assert queries[0].startswith("validation tasks real market data mapping simulation indices")
    assert "broker rejection rates" in joined
    assert "open interest" in joined
    assert "Treasury auctions" in joined
    assert "oil geopolitics" in joined


def test_quality_rejects_raw_rate_limit_error():
    result = evaluate_section_quality(
        "Executive summary",
        "This section says Rate limit exceeded for FREE plan.",
        evidence_labels=["live_zep"],
    )
    assert not result.passed
    assert "raw_error_leak" in result.failure_codes


def test_quality_rejects_chinese_final_prose():
    result = evaluate_section_quality(
        "Executive summary",
        "这是中文最终报告正文，应该被拒绝。",
        evidence_labels=["live_zep"],
    )
    assert not result.passed
    assert "non_english_final_prose" in result.failure_codes


def test_quality_rejects_fake_empty_graph():
    result = evaluate_section_quality(
        "Ticker/category attention map",
        "The graph has 0 nodes and 0 edges.",
        evidence_labels=["unavailable_rate_limited"],
    )
    assert not result.passed
    assert "fake_empty_graph_claim" in result.failure_codes
