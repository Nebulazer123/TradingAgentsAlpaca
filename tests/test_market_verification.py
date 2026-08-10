import datetime

from tradingagents.market_verification import (
    EvidenceItem,
    build_market_verification_packet,
    render_email_summary,
    render_market_verification_markdown,
)


def test_market_verification_packet_separates_baseline_from_delta():
    packet = build_market_verification_packet(
        run_id="20260526-tuesday",
        baseline_collected_at=datetime.datetime(2026, 5, 25, 20, 30),
        generated_at=datetime.datetime(2026, 5, 26, 8, 55),
        baseline_items=[
            EvidenceItem(
                category="GOOGL",
                summary="EU DMA fine headline known before execution.",
                source="https://example.com/baseline",
            )
        ],
        delta_items=[
            EvidenceItem(
                category="GOOGL",
                summary="Premarket ask moved above the no-chase band.",
                source="https://example.com/delta",
            )
        ],
        decision="Skip live Ticket 1.",
        email_to="nebulazer2003@gmail.com",
    )

    markdown = render_market_verification_markdown(packet)

    assert "## NOW Baseline" in markdown
    assert "EU DMA fine headline known before execution." in markdown
    assert "## Delta Since Baseline" in markdown
    assert "Premarket ask moved above the no-chase band." in markdown
    assert markdown.index("## NOW Baseline") < markdown.index("## Delta Since Baseline")


def test_market_verification_email_summary_includes_decision_and_sources():
    packet = build_market_verification_packet(
        run_id="20260526-tuesday",
        baseline_collected_at=datetime.datetime(2026, 5, 25, 20, 30),
        generated_at=datetime.datetime(2026, 5, 26, 8, 55),
        baseline_items=[
            EvidenceItem("Market", "Nasdaq futures risk-on.", "https://example.com/market")
        ],
        delta_items=[
            EvidenceItem("NVDA", "No new export-control shock.", "https://example.com/nvda")
        ],
        decision="Proceed inside the live gate with no repo dollar cap.",
        email_to="nebulazer2003@gmail.com",
    )

    summary = render_email_summary(packet)

    assert "To: nebulazer2003@gmail.com" in summary
    assert "Decision: Proceed inside the live gate with no repo dollar cap." in summary
    assert "Baseline sources: https://example.com/market" in summary
    assert "Delta sources: https://example.com/nvda" in summary
