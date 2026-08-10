from __future__ import annotations

from tradingagents.dataflows import decision_vendor_adapters as adapters
from tradingagents.dataflows._official_common import OfficialDataError
from tradingagents.schemas.research import SourceEvidencePacket


def _packet(source_name: str, payload: dict) -> SourceEvidencePacket:
    return SourceEvidencePacket(
        source_name=source_name,
        evidence_type="market_news",
        subject="CRM",
        symbol="CRM",
        as_of="2026-06-03T14:30:00+00:00",
        source_refs=["https://example.test/source"],
        payload=payload,
        quality="medium",
        tool_route=f"{source_name}_api",
    )


def test_marketaux_adapter_renders_source_packet_for_analyst_prompt(monkeypatch):
    def fake_fetch_marketaux_news(**_kwargs):
        return _packet("marketaux", {"data": [{"title": "CRM raises guidance"}]})

    monkeypatch.setattr(adapters, "fetch_marketaux_news", fake_fetch_marketaux_news)

    rendered = adapters.get_marketaux_news("crm", "2026-06-01", "2026-06-03")

    assert "Marketaux news for CRM" in rendered
    assert "Execution authority: none" in rendered
    assert "CRM raises guidance" in rendered
    assert "https://example.test/source" in rendered


def test_google_news_adapter_passes_point_in_time_date_window(monkeypatch):
    seen = {}

    def fake_fetch_google_news_rss(**kwargs):
        seen.update(kwargs)
        return _packet("google_news_rss", {"items": [{"title": "CRM windowed news"}]})

    monkeypatch.setattr(adapters, "fetch_google_news_rss", fake_fetch_google_news_rss)

    rendered = adapters.get_google_news("crm", "2026-06-01", "2026-06-03")

    assert seen["start_date"] == "2026-06-01"
    assert seen["end_date"] == "2026-06-03"
    assert "CRM windowed news" in rendered


def test_fmp_statement_rendering_filters_future_rows(monkeypatch):
    def fake_fetch_fmp_route(*_args, **_kwargs):
        return _packet(
            "fmp",
            {
                "rows": [
                    {"date": "2026-06-30", "revenue": 999},
                    {"date": "2026-03-31", "revenue": 111},
                ]
            },
        )

    monkeypatch.setattr(adapters, "fetch_fmp_route", fake_fetch_fmp_route)

    rendered = adapters.get_fmp_income_statement("crm", curr_date="2026-06-03")

    assert "2026-03-31" in rendered
    assert "2026-06-30" not in rendered
    assert "as_of_filter" in rendered


def test_sec_fundamentals_rendering_filters_future_companyfacts_and_submissions(monkeypatch):
    monkeypatch.setattr(adapters, "_sec_cik_for_symbol", lambda _symbol: "0000123456")
    monkeypatch.setattr(
        adapters,
        "fetch_sec_companyfacts",
        lambda *_args, **_kwargs: _packet(
            "sec_edgar",
            {
                "facts": {
                    "us-gaap": {
                        "Revenue": {
                            "units": {
                                "USD": [
                                    {"end": "2026-06-30", "val": 999},
                                    {"end": "2026-03-31", "val": 111},
                                ]
                            }
                        }
                    }
                }
            },
        ),
    )
    monkeypatch.setattr(
        adapters,
        "fetch_sec_submissions",
        lambda *_args, **_kwargs: _packet(
            "sec_edgar",
            {
                "filings": {
                    "recent": {
                        "filingDate": ["2026-06-30", "2026-03-31"],
                        "accessionNumber": ["future-accession", "past-accession"],
                        "form": ["10-Q", "10-Q"],
                    }
                }
            },
        ),
    )

    rendered = adapters.get_sec_fundamentals("crm", curr_date="2026-06-03")

    assert "2026-03-31" in rendered
    assert "past-accession" in rendered
    assert "2026-06-30" not in rendered
    assert "future-accession" not in rendered


def test_eodhd_fundamentals_rendering_filters_future_date_keys(monkeypatch):
    monkeypatch.setattr(
        adapters,
        "fetch_eodhd_fundamentals",
        lambda *_args, **_kwargs: _packet(
            "eodhd",
            {
                "Financials": {
                    "Income_Statement": {
                        "quarterly": {
                            "2026-06-30": {"totalRevenue": 999},
                            "2026-03-31": {"totalRevenue": 111},
                        }
                    }
                }
            },
        ),
    )

    rendered = adapters.get_eodhd_fundamentals("crm", curr_date="2026-06-03")

    assert "2026-03-31" in rendered
    assert "2026-06-30" not in rendered


def test_tiingo_stock_data_adapter_returns_csv_shape(monkeypatch):
    def fake_fetch_tiingo_daily_prices(*_args, **_kwargs):
        return _packet(
            "tiingo",
            {
                "data": [
                    {
                        "date": "2026-06-01",
                        "open": 100,
                        "high": 105,
                        "low": 99,
                        "close": 104,
                        "adjClose": 104,
                        "volume": 12345,
                    }
                ]
            },
        )

    monkeypatch.setattr(adapters, "fetch_tiingo_daily_prices", fake_fetch_tiingo_daily_prices)

    rendered = adapters.get_tiingo_stock_data("crm", "2026-06-01", "2026-06-03")

    assert rendered.startswith("# Tiingo daily prices for CRM")
    assert "Date,Open,High,Low,Close,Adj Close,Volume" in rendered
    assert "2026-06-01,100,105,99,104,104,12345" in rendered


def test_macro_context_adapter_renders_official_macro_packets(monkeypatch):
    def fake_fetch_fred_series_observations(series_id, **_kwargs):
        return _packet("fred", {"observations": [{"series_id": series_id, "value": "4.25"}]})

    monkeypatch.setattr(adapters, "fetch_fred_series_observations", fake_fetch_fred_series_observations)

    rendered = adapters.get_fred_macro_context("2026-06-03", 7, 5)

    assert "FRED macro context" in rendered
    assert "Execution authority: none" in rendered
    assert "FEDFUNDS" in rendered
    assert "4.25" in rendered


def test_bea_macro_context_fetches_all_years_in_lookback_window(monkeypatch):
    seen_years = []

    def fake_fetch_bea_data(_dataset_name, **kwargs):
        seen_years.append(kwargs["Year"])
        return _packet("bea", {"year": kwargs["Year"], "data": [{"LineDescription": "GDP"}]})

    monkeypatch.setattr(adapters, "fetch_bea_data", fake_fetch_bea_data)

    rendered = adapters.get_bea_macro_context("2026-06-15", look_back_days=500)

    assert seen_years == ["2025", "2026"]
    assert "BEA macro context: GDP 2025" in rendered
    assert "BEA macro context: GDP 2026" in rendered
    assert "Execution authority: none" in rendered


def test_eia_macro_context_threads_as_of_month_window(monkeypatch):
    seen = {}

    def fake_fetch_eia_route(route, **kwargs):
        seen["route"] = route
        seen.update(kwargs)
        return _packet("eia", {"response": {"data": [{"period": "2026-06", "value": "72"}]}})

    monkeypatch.setattr(adapters, "fetch_eia_route", fake_fetch_eia_route)

    rendered = adapters.get_eia_energy_macro_context("2026-06-15", look_back_days=45, limit=7)

    assert seen["route"] == "steo/data/"
    assert seen["start"] == "2026-05"
    assert seen["end"] == "2026-06"
    assert seen["length"] == 7
    assert seen["as_of"] == "2026-06-15"
    assert "72" in rendered


def test_treasury_macro_context_threads_as_of_record_date_filter(monkeypatch):
    seen = {}

    def fake_fetch_treasury_fiscal(path, **kwargs):
        seen["path"] = path
        seen.update(kwargs)
        return _packet("treasury_fiscal", {"data": [{"record_date": "2026-06-12"}]})

    monkeypatch.setattr(adapters, "fetch_treasury_fiscal", fake_fetch_treasury_fiscal)

    rendered = adapters.get_treasury_macro_context("2026-06-15", look_back_days=30, limit=4)

    assert seen["path"] == "v2/accounting/od/avg_interest_rates"
    assert seen["filter"] == "record_date:gte:2026-05-16,record_date:lte:2026-06-15"
    assert seen["sort"] == "-record_date"
    assert seen["page[size]"] == 4
    assert seen["as_of"] == "2026-06-15"
    assert "2026-06-12" in rendered


def test_sentiment_context_adapter_combines_reddit_and_stocktwits(monkeypatch):
    seen = {}

    def fake_stocktwits(ticker, **kwargs):
        seen["stocktwits"] = kwargs
        return f"StockTwits says {ticker} bullish"

    def fake_reddit(ticker, **kwargs):
        seen["reddit"] = kwargs
        return f"Reddit says {ticker} cautious"

    monkeypatch.setattr(adapters, "fetch_stocktwits_messages", fake_stocktwits)
    monkeypatch.setattr(adapters, "fetch_reddit_posts", fake_reddit)

    rendered = adapters.get_social_sentiment_context("crm", "2026-06-01", "2026-06-03")

    assert "Social sentiment context for CRM" in rendered
    assert "StockTwits says CRM bullish" in rendered
    assert "Reddit says CRM cautious" in rendered
    assert "Execution authority: none" in rendered
    assert seen["stocktwits"]["start_date"] == "2026-06-01"
    assert seen["stocktwits"]["end_date"] == "2026-06-03"
    assert seen["reddit"]["start_date"] == "2026-06-01"
    assert seen["reddit"]["end_date"] == "2026-06-03"


def test_supplemental_market_context_marks_missing_optional_sources_as_downranked(monkeypatch):
    monkeypatch.setattr(
        adapters,
        "get_fmp_latest_earnings_transcript_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OfficialDataError("FMP_API_KEY is missing")),
    )
    monkeypatch.setattr(
        adapters,
        "get_yfinance_options_context",
        lambda *_args, **_kwargs: "## options section\nExecution authority: none",
    )
    monkeypatch.setattr(
        adapters,
        "get_yfinance_short_interest_context",
        lambda *_args, **_kwargs: "## short-interest section\nExecution authority: none",
    )
    monkeypatch.setattr(
        adapters,
        "get_yfinance_earnings_calendar_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OfficialDataError("no upcoming yfinance earnings date")),
    )
    monkeypatch.setattr(
        adapters,
        "get_release_calendar_context",
        lambda *_args, **_kwargs: "## official release calendar\nExecution authority: none",
    )

    rendered = adapters.get_supplemental_market_context("crm", "2026-06-15", 14)

    assert rendered.startswith("# Supplemental event and microstructure context for CRM")
    assert "Execution authority: none" in rendered
    assert "earnings_transcripts gap/downrank for CRM" in rendered
    assert "earnings_calendar gap/downrank for CRM" in rendered
    assert rendered.count("Downrank evidence: true") == 2
    assert "Fallback source: local:research_gap" in rendered
    assert "Fallback source: local:release_calendar_watchlist" in rendered
    assert "options section" in rendered
    assert "short-interest section" in rendered
    assert "official release calendar" in rendered
