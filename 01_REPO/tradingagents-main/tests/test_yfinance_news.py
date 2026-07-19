from __future__ import annotations

import pytest

from tradingagents.dataflows import yfinance_news

YAHOO_NEWS_SYMBOL_CASES = (
    ("AAPL", "AAPL"),
    (" cnc.to ", "CNC.TO"),
    ("GC=F", "GC=F"),
    ("^GSPC", "^GSPC"),
    ("BTCUSD", "BTC-USD"),
    ("BTC-USDT", "BTC-USD"),
    ("BTC-USDC", "BTC-USD"),
    ("EURUSD", "EURUSD=X"),
    ("XAUUSD", "GC=F"),
    ("XAUUSD+", "GC=F"),
)


def _patch_yfinance(
    monkeypatch: pytest.MonkeyPatch,
    *,
    news: list[dict] | None = None,
    error: Exception | None = None,
) -> list[str]:
    queried_symbols: list[str] = []

    class FakeTicker:
        def __init__(self, symbol: str) -> None:
            queried_symbols.append(symbol)

        def get_news(self, *, count: int) -> list[dict]:
            assert count > 0
            if error is not None:
                raise error
            return [] if news is None else news

    monkeypatch.setattr(yfinance_news.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(yfinance_news, "yf_retry", lambda operation: operation())
    return queried_symbols


@pytest.mark.parametrize(("requested", "expected"), YAHOO_NEWS_SYMBOL_CASES)
def test_normalize_yahoo_news_symbol_matches_bounded_contract(
    requested: str,
    expected: str,
) -> None:
    assert yfinance_news._normalize_yahoo_news_symbol(requested) == expected


@pytest.mark.parametrize(("requested", "expected"), YAHOO_NEWS_SYMBOL_CASES)
def test_get_news_queries_only_the_translated_yahoo_symbol(
    monkeypatch: pytest.MonkeyPatch,
    requested: str,
    expected: str,
) -> None:
    queried_symbols = _patch_yfinance(monkeypatch)

    yfinance_news.get_news_yfinance(requested, "2026-07-18", "2026-07-18")

    assert queried_symbols == [expected]


def test_empty_news_output_keeps_trimmed_requested_display_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queried_symbols = _patch_yfinance(monkeypatch)

    result = yfinance_news.get_news_yfinance(
        " cnc.to ",
        "2026-07-18",
        "2026-07-18",
    )

    assert queried_symbols == ["CNC.TO"]
    assert result == "No news found for CNC.TO"


def test_resolved_empty_news_output_shows_yahoo_query_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queried_symbols = _patch_yfinance(monkeypatch)

    result = yfinance_news.get_news_yfinance(
        "XAUUSD+",
        "2026-07-18",
        "2026-07-18",
    )

    assert queried_symbols == ["GC=F"]
    assert "No news found for XAUUSD+" in result
    assert result.count("(Yahoo query: GC=F)") == 1


@pytest.mark.parametrize(("requested", "expected"), (
    ("BTC-USD", "BTC-USD"),
    ("EURUSD=X", "EURUSD=X"),
    ("GC=F", "GC=F"),
    ("^GSPC", "^GSPC"),
))
def test_already_native_yahoo_symbols_remain_unchanged_without_provenance(
    monkeypatch: pytest.MonkeyPatch,
    requested: str,
    expected: str,
) -> None:
    queried_symbols = _patch_yfinance(monkeypatch)

    result = yfinance_news.get_news_yfinance(
        requested,
        "2026-07-18",
        "2026-07-18",
    )

    assert queried_symbols == [expected]
    assert "Yahoo query:" not in result


def test_article_output_keeps_requested_symbol_in_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article = {
        "content": {
            "title": "Gold edges higher before the close",
            "summary": "Bullion held a narrow gain.",
            "provider": {"displayName": "Example Markets"},
            "canonicalUrl": {"url": "https://example.test/gold-news"},
            "pubDate": "2026-07-18T12:00:00Z",
        },
    }
    queried_symbols = _patch_yfinance(monkeypatch, news=[article])

    result = yfinance_news.get_news_yfinance(
        "XAUUSD+",
        "2026-07-18",
        "2026-07-18",
    )

    assert queried_symbols == ["GC=F"]
    assert result.startswith("## XAUUSD+ News, from 2026-07-18 to 2026-07-18")
    assert "## GC=F News" not in result
    assert result.count("(Yahoo query: GC=F)") == 1
    assert "Gold edges higher before the close" in result


def test_date_filtered_no_news_keeps_requested_identity_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article = {
        "content": {
            "title": "Euro moves before the requested window",
            "provider": {"displayName": "Example FX"},
            "pubDate": "2026-07-01T12:00:00Z",
        },
    }
    queried_symbols = _patch_yfinance(monkeypatch, news=[article])

    result = yfinance_news.get_news_yfinance(
        "EURUSD",
        "2026-07-18",
        "2026-07-18",
    )

    assert queried_symbols == ["EURUSD=X"]
    assert "No news found for EURUSD" in result
    assert "between 2026-07-18 and 2026-07-18" in result
    assert result.count("(Yahoo query: EURUSD=X)") == 1


def test_provider_error_keeps_requested_identity_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queried_symbols = _patch_yfinance(
        monkeypatch,
        error=RuntimeError("provider offline"),
    )

    result = yfinance_news.get_news_yfinance(
        "BTC-USDT",
        "2026-07-18",
        "2026-07-18",
    )

    assert queried_symbols == ["BTC-USD"]
    assert "Error fetching news for BTC-USDT" in result
    assert result.count("(Yahoo query: BTC-USD)") == 1
    assert result.endswith(": provider offline")


def test_non_allowlisted_six_letter_value_remains_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queried_symbols = _patch_yfinance(monkeypatch)

    result = yfinance_news.get_news_yfinance(
        "ABCDEF",
        "2026-07-18",
        "2026-07-18",
    )

    assert queried_symbols == ["ABCDEF"]
    assert result == "No news found for ABCDEF"
