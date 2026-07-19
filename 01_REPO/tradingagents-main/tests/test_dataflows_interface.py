from __future__ import annotations

import copy
import json

import pytest

import tradingagents.default_config as default_config
from tradingagents.dataflows import decision_vendor_adapters, interface
from tradingagents.dataflows._official_common import OfficialDataError
from tradingagents.dataflows.config import set_config


@pytest.fixture(autouse=True)
def reset_dataflow_config():
    set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))


def test_route_to_vendor_falls_back_on_transient_timeout(monkeypatch):
    calls = []

    def primary(*_args, **_kwargs):
        calls.append("alpha_vantage")
        raise TimeoutError("temporary timeout")

    def fallback(*args, **kwargs):
        calls.append("yfinance")
        return {"args": args, "kwargs": kwargs, "vendor": "yfinance"}

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_stock_data",
        {"alpha_vantage": primary, "yfinance": fallback},
    )
    set_config({"tool_vendors": {"get_stock_data": "alpha_vantage,yfinance"}})

    result = interface.route_to_vendor("get_stock_data", "CRM", start="2026-06-01")

    assert result["vendor"] == "yfinance"
    assert calls == ["alpha_vantage", "yfinance"]


def test_route_to_vendor_falls_back_on_empty_result(monkeypatch):
    calls = []

    def primary(*_args, **_kwargs):
        calls.append("alpha_vantage")
        return ""

    def fallback(*_args, **_kwargs):
        calls.append("yfinance")
        return "csv-data"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_stock_data",
        {"alpha_vantage": primary, "yfinance": fallback},
    )
    set_config({"tool_vendors": {"get_stock_data": "alpha_vantage,yfinance"}})

    assert interface.route_to_vendor("get_stock_data", "CRM") == "csv-data"
    assert calls == ["alpha_vantage", "yfinance"]


def test_route_to_vendor_falls_back_on_vendor_error_string(monkeypatch):
    calls = []

    def primary(*_args, **_kwargs):
        calls.append("yfinance")
        return "Error fetching news for CRM: upstream timeout"

    def fallback(*_args, **_kwargs):
        calls.append("google_news")
        return "Google News backup evidence"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_news",
        {"yfinance": primary, "google_news": fallback},
    )
    set_config({"tool_vendors": {"get_news": "yfinance,google_news"}})

    result = interface.route_to_vendor("get_news", "CRM", "2026-06-01", "2026-06-03")

    assert "Google News backup evidence" in result
    assert "upstream timeout" not in result
    assert calls == ["yfinance", "google_news"]


def test_news_route_merges_multiple_sources_and_dedupes(monkeypatch):
    calls = []

    def marketaux(*_args, **_kwargs):
        calls.append("marketaux")
        return "Shared headline\nMarketaux-only headline"

    def finnhub(*_args, **_kwargs):
        calls.append("finnhub")
        return "Shared headline\nFinnhub-only headline"

    def newsapi(*_args, **_kwargs):
        calls.append("newsapi")
        return ""

    def google_news(*_args, **_kwargs):
        calls.append("google_news")
        return "Google-only headline"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_news",
        {
            "marketaux": marketaux,
            "finnhub": finnhub,
            "newsapi": newsapi,
            "google_news": google_news,
        },
    )
    set_config({"tool_vendors": {"get_news": "marketaux,finnhub,newsapi,google_news"}})

    result = interface.route_to_vendor("get_news", "CRM", "2026-06-01", "2026-06-03")

    assert "Merged get_news evidence" in result
    assert "Execution authority: none" in result
    assert result.count("Shared headline") == 1
    assert "Marketaux-only headline" in result
    assert "Finnhub-only headline" in result
    assert "Google-only headline" in result
    assert calls == ["marketaux", "finnhub", "newsapi", "google_news"]


def test_route_to_vendor_preserves_non_transient_errors(monkeypatch):
    def broken_vendor(*_args, **_kwargs):
        raise ValueError("bad indicator name")

    def fallback(*_args, **_kwargs):
        raise AssertionError("non-transient errors must not fall through")

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_indicators",
        {"alpha_vantage": broken_vendor, "yfinance": fallback},
    )
    set_config({"tool_vendors": {"get_indicators": "alpha_vantage,yfinance"}})

    with pytest.raises(ValueError, match="bad indicator name"):
        interface.route_to_vendor("get_indicators", "CRM", "bad_indicator")


def test_route_to_vendor_falls_back_on_official_data_error(monkeypatch):
    calls = []

    def point_in_time_rejection(*_args, **_kwargs):
        calls.append("alpha_vantage")
        raise OfficialDataError("historical Alpha Vantage evidence unavailable")

    def fallback(*_args, **_kwargs):
        calls.append("yfinance")
        return "historical fallback evidence"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_balance_sheet",
        {
            "alpha_vantage": point_in_time_rejection,
            "yfinance": fallback,
        },
    )
    set_config(
        {"tool_vendors": {"get_balance_sheet": "alpha_vantage,yfinance"}}
    )

    assert (
        interface.route_to_vendor(
            "get_balance_sheet",
            "NFLX",
            curr_date="2024-02-15",
        )
        == "historical fallback evidence"
    )
    assert calls == ["alpha_vantage", "yfinance"]


def test_decision_path_vendor_map_exposes_promoted_research_sources():
    assert "sec" in interface.VENDOR_LIST
    assert "eia" in interface.VENDOR_LIST
    assert "massive" in interface.VENDOR_LIST
    assert list(interface.VENDOR_METHODS["get_stock_data"])[:4] == [
        "yfinance",
        "tiingo",
        "massive",
        "alpha_vantage",
    ]
    assert list(interface.VENDOR_METHODS["get_fundamentals"])[:4] == ["fmp", "eodhd", "finnhub", "sec"]
    assert list(interface.VENDOR_METHODS["get_news"])[:4] == [
        "marketaux",
        "finnhub",
        "newsapi",
        "google_news",
    ]
    assert list(interface.VENDOR_METHODS["get_global_news"])[:2] == ["marketaux", "google_news"]
    assert list(interface.VENDOR_METHODS["get_macro_context"])[:5] == [
        "fred",
        "bls",
        "bea",
        "eia",
        "treasury_fiscal",
    ]
    assert list(interface.VENDOR_METHODS["get_sentiment_context"])[:3] == [
        "stocktwits",
        "reddit",
        "eodhd",
    ]
    assert list(interface.VENDOR_METHODS["get_earnings_transcript_context"]) == ["fmp"]
    assert list(interface.VENDOR_METHODS["get_options_iv_flow_context"]) == ["yfinance_options"]
    assert list(interface.VENDOR_METHODS["get_short_interest_context"]) == ["yfinance_short_interest"]
    assert list(interface.VENDOR_METHODS["get_earnings_calendar_context"]) == [
        "yfinance_earnings_calendar"
    ]
    assert list(interface.VENDOR_METHODS["get_release_calendar_context"]) == [
        "official_release_calendar"
    ]
    assert list(interface.VENDOR_METHODS["get_supplemental_market_context"]) == ["local"]


def test_default_config_routes_macro_and_sentiment_decision_tools():
    config = default_config.DEFAULT_CONFIG

    assert config["data_vendors"]["core_stock_apis"] == "yfinance,tiingo,massive,alpha_vantage"
    assert config["data_vendors"]["fundamental_data"] == "fmp,eodhd,finnhub,sec,yfinance,alpha_vantage"
    assert config["data_vendors"]["macro_context"] == "fred,bls,bea,eia,treasury_fiscal"
    assert config["data_vendors"]["sentiment_data"] == "stocktwits,reddit,eodhd"
    assert config["data_vendors"]["event_microstructure_context"] == (
        "local,fmp,yfinance_options,yfinance_short_interest,yfinance_earnings_calendar,official_release_calendar"
    )


def test_massive_stock_data_adapter_renders_csv(monkeypatch):
    class Packet:
        payload = {
            "results": [
                {
                    "t": 1780444800000,
                    "o": 100.0,
                    "h": 103.0,
                    "l": 99.5,
                    "c": 102.25,
                    "v": 1234567,
                }
            ]
        }

    def fake_fetch(symbol: str, *, start_date: str, end_date: str):
        assert symbol == "CRM"
        assert start_date == "2026-06-02"
        assert end_date == "2026-06-03"
        return Packet()

    monkeypatch.setattr(decision_vendor_adapters, "fetch_massive_daily_prices", fake_fetch)

    result = decision_vendor_adapters.get_massive_stock_data("crm", "2026-06-02", "2026-06-03")

    assert result.startswith("# Massive daily prices for CRM")
    assert "Date,Open,High,Low,Close,Adj Close,Volume" in result
    assert "2026-06-03,100.0,103.0,99.5,102.25,102.25,1234567" in result


def test_macro_context_falls_back_between_official_sources(monkeypatch):
    calls = []

    def fred(*_args, **_kwargs):
        calls.append("fred")
        raise TimeoutError("fred timeout")

    def bls(*_args, **_kwargs):
        calls.append("bls")
        return "BLS macro context"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_macro_context",
        {"fred": fred, "bls": bls},
    )
    set_config({"tool_vendors": {"get_macro_context": "fred,bls"}})

    assert interface.route_to_vendor("get_macro_context", "2026-06-03", 7, 5) == "BLS macro context"
    assert calls == ["fred", "bls"]


def test_sentiment_context_falls_back_from_empty_social_source(monkeypatch):
    calls = []

    def stocktwits(*_args, **_kwargs):
        calls.append("stocktwits")
        return ""

    def reddit(*_args, **_kwargs):
        calls.append("reddit")
        return "Reddit sentiment context"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_sentiment_context",
        {"stocktwits": stocktwits, "reddit": reddit},
    )
    set_config({"tool_vendors": {"get_sentiment_context": "stocktwits,reddit"}})

    assert interface.route_to_vendor("get_sentiment_context", "CRM", "2026-06-01", "2026-06-03") == "Reddit sentiment context"
    assert calls == ["stocktwits", "reddit"]


def test_decision_source_routing_summary_surfaces_gaps_and_effective_chains(tmp_path):
    path = interface.write_decision_source_routing(tmp_path / "source-routing.json")

    assert path.exists()
    compact_path = tmp_path / "source-routing-compact.json"
    assert compact_path.exists()
    summary = interface.decision_source_routing_summary()
    compact = interface.compact_decision_source_routing_summary(
        summary,
        raw_packet_path=path,
    )
    written_compact = json.loads(compact_path.read_text(encoding="utf-8"))
    assert summary["analysis_only"] is True
    assert summary["can_submit_orders"] is False
    assert compact["schema"] == "compact_source_routing_v1"
    assert compact["raw_packet_path"] == str(path)
    assert compact["method_count"] == len(summary["methods"])
    assert compact["gap_count"] == 0
    assert written_compact["schema"] == "compact_source_routing_v1"
    assert written_compact["raw_packet_path"] == str(path)
    assert summary["methods"]["get_news"]["effective_fallback_chain"][:4] == [
        "marketaux",
        "finnhub",
        "newsapi",
        "google_news",
    ]
    assert summary["methods"]["get_stock_data"]["effective_fallback_chain"][:4] == [
        "yfinance",
        "tiingo",
        "massive",
        "alpha_vantage",
    ]
    assert summary["methods"]["get_news"]["routing_mode"] == "merge_dedup"
    assert summary["methods"]["get_news"]["merge_max_sources"] == 4
    assert summary["methods"]["get_macro_context"]["effective_fallback_chain"][:5] == [
        "fred",
        "bls",
        "bea",
        "eia",
        "treasury_fiscal",
    ]
    assert summary["methods"]["get_sentiment_context"]["effective_fallback_chain"][:2] == [
        "stocktwits",
        "reddit",
    ]
    assert summary["methods"]["get_earnings_transcript_context"]["effective_fallback_chain"] == [
        "fmp"
    ]
    assert summary["methods"]["get_options_iv_flow_context"]["effective_fallback_chain"] == [
        "yfinance_options"
    ]
    assert summary["methods"]["get_short_interest_context"]["effective_fallback_chain"] == [
        "yfinance_short_interest"
    ]
    assert summary["methods"]["get_earnings_calendar_context"]["effective_fallback_chain"] == [
        "yfinance_earnings_calendar"
    ]
    assert summary["methods"]["get_release_calendar_context"]["effective_fallback_chain"] == [
        "official_release_calendar"
    ]
    assert summary["methods"]["get_supplemental_market_context"]["effective_fallback_chain"] == [
        "local"
    ]
    assert compact["methods"]["get_news"]["effective_fallback_chain"][:4] == [
        "marketaux",
        "finnhub",
        "newsapi",
        "google_news",
    ]
    assert summary["source_category_gaps"] == []
    assert summary["source_category_coverage"] == [
        {
            "category": "earnings_transcripts",
            "status": "covered_by_optional_connector",
            "provider_evidence_need": "earnings_transcripts",
            "promotion_state": "fmp_transcripts_before_gap_packet",
            "why_it_matters": "Guidance tone and Q&A can validate event-underreaction theses.",
            "active_routes": [
                "local:official_cache",
                "docker:youtube_transcript",
                "dataflow:fmp",
                "composio:benzinga",
                "local:research_gap",
            ],
            "limitations": [
                "FMP transcript data requires FMP_API_KEY and may be plan-limited",
                "YouTube/Benzinga transcript routes are external connector hooks and may be unavailable",
                "use transcripts for advisory confirmation/downrank only, never direct execution",
            ],
        },
        {
            "category": "options_iv_flow",
            "status": "covered_by_supplemental_connector",
            "provider_evidence_need": "options_iv_flow",
            "promotion_state": "yfinance_options_before_gap_packet",
            "why_it_matters": "0DTE/gamma/IV context can affect intraday dip-buy and spike-sell behavior.",
            "active_routes": ["dataflow:yfinance_options", "local:research_gap"],
            "limitations": [
                "public yfinance options data is supplemental and lower-authority",
                "use for advisory confirmation/downrank only, never direct execution",
            ],
        },
        {
            "category": "short_interest",
            "status": "covered_by_supplemental_connector",
            "provider_evidence_need": "short_interest",
            "promotion_state": "yfinance_short_interest_before_gap_packet",
            "why_it_matters": "Crowded-short and squeeze risk can change position timing and risk review.",
            "active_routes": ["dataflow:yfinance_short_interest", "local:research_gap"],
            "limitations": [
                "public yfinance short-interest metadata is supplemental and lower-authority",
                "short-interest values can lag official exchange publications",
                "use for advisory confirmation/downrank only, never direct execution",
            ],
        },
        {
            "category": "earnings_calendar",
            "status": "covered_by_supplemental_connector",
            "provider_evidence_need": "earnings_calendar",
            "promotion_state": "yfinance_earnings_calendar_before_release_calendar_fallback",
            "why_it_matters": "Company earnings dates can require blackout, spread, and post-event validation before dip-buy decisions.",
            "active_routes": ["dataflow:yfinance_earnings_calendar", "local:release_calendar_watchlist"],
            "limitations": [
                "public yfinance calendar data is supplemental and can revise",
                "use release-calendar watchlist fallback when ticker-specific earnings date is unavailable",
                "use for advisory event-risk/downrank context only, never direct execution",
            ],
        },
        {
            "category": "macro_release_calendar",
            "status": "covered_by_official_watchlist",
            "provider_evidence_need": "macro_release_calendar",
            "promotion_state": "official_release_calendar_context_available",
            "why_it_matters": "Macro release windows can alter liquidity, spreads, and the reliability of intraday AI-bot crowd signals.",
            "active_routes": ["config:release_calendar_watchlist", "local:official_release_calendar"],
            "limitations": [
                "static config must be refreshed when official calendars change",
                "release windows require fresh quote/spread validation before any action",
                "use for advisory event-risk/downrank context only, never direct execution",
            ],
        },
    ]
