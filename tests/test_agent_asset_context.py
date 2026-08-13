from types import SimpleNamespace

from langchain_core.runnables import RunnableLambda

from tradingagents.agents.analysts import fundamentals_analyst, news_analyst, sentiment_analyst
from tradingagents.agents.managers import portfolio_manager, research_manager
from tradingagents.dataflows._official_common import DataTransportError


def test_research_manager_passes_asset_type_to_instrument_context(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        research_manager,
        "build_instrument_context",
        lambda ticker, asset_type="stock": seen.setdefault("args", (ticker, asset_type)) or "context",
    )
    monkeypatch.setattr(research_manager, "bind_structured", lambda llm, schema, role: llm)
    monkeypatch.setattr(
        research_manager,
        "invoke_structured_or_freetext",
        lambda *_args, **_kwargs: "research plan",
    )

    node = research_manager.create_research_manager(object())
    result = node(
        {
            "company_of_interest": "BTC-USD",
            "asset_type": "crypto",
            "investment_debate_state": {"history": "debate", "count": 1},
        }
    )

    assert seen["args"] == ("BTC-USD", "crypto")
    assert result["investment_plan"] == "research plan"


def test_portfolio_manager_passes_asset_type_to_instrument_context(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        portfolio_manager,
        "build_instrument_context",
        lambda ticker, asset_type="stock": seen.setdefault("args", (ticker, asset_type)) or "context",
    )
    monkeypatch.setattr(portfolio_manager, "bind_structured", lambda llm, schema, role: llm)
    monkeypatch.setattr(
        portfolio_manager,
        "invoke_structured_or_freetext",
        lambda *_args, **_kwargs: "portfolio decision",
    )

    node = portfolio_manager.create_portfolio_manager(object())
    result = node(
        {
            "company_of_interest": "BTC-USD",
            "asset_type": "crypto",
            "investment_plan": "research plan",
            "trader_investment_plan": "trader plan",
            "risk_debate_state": {
                "history": "risk debate",
                "aggressive_history": "",
                "conservative_history": "",
                "neutral_history": "",
                "current_aggressive_response": "",
                "current_conservative_response": "",
                "current_neutral_response": "",
                "count": 1,
            },
        }
    )

    assert seen["args"] == ("BTC-USD", "crypto")
    assert result["final_trade_decision"] == "portfolio decision"


def test_prefetched_fundamentals_passes_asset_type_to_instrument_context(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        fundamentals_analyst,
        "build_instrument_context",
        lambda ticker, asset_type="stock": seen.setdefault("args", (ticker, asset_type)) or "context",
    )
    monkeypatch.setattr(fundamentals_analyst, "_safe_fundamental_block", lambda *_args: "data")

    llm = RunnableLambda(lambda _prompt: SimpleNamespace(content="fundamentals report"))
    node = fundamentals_analyst.create_prefetched_fundamentals_analyst(llm)
    result = node(
        {
            "company_of_interest": "BTC-USD",
            "asset_type": "crypto",
            "trade_date": "2026-06-03",
            "messages": [],
        }
    )

    assert seen["args"] == ("BTC-USD", "crypto")
    assert result["fundamentals_report"] == "fundamentals report"


def test_sentiment_analyst_passes_asset_type_to_instrument_context(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        sentiment_analyst,
        "build_instrument_context",
        lambda ticker, asset_type="stock": seen.setdefault("args", (ticker, asset_type)) or "context",
    )
    monkeypatch.setattr(sentiment_analyst.get_news, "func", lambda *_args: "news")
    monkeypatch.setattr(sentiment_analyst, "fetch_stocktwits_messages", lambda *_args, **_kwargs: "stocktwits")
    monkeypatch.setattr(sentiment_analyst, "fetch_reddit_posts", lambda *_args, **_kwargs: "reddit")

    llm = RunnableLambda(lambda _prompt: SimpleNamespace(content="sentiment report"))
    node = sentiment_analyst.create_sentiment_analyst(llm)
    result = node(
        {
            "company_of_interest": "BTC-USD",
            "asset_type": "crypto",
            "trade_date": "2026-06-03",
            "messages": [],
        }
    )

    assert seen["args"] == ("BTC-USD", "crypto")
    assert result["sentiment_report"] == "sentiment report"


def test_sentiment_analyst_degrades_recoverable_reddit_failure(monkeypatch):
    seen = {}
    monkeypatch.setattr(sentiment_analyst.get_news, "func", lambda *_args: "news")
    monkeypatch.setattr(
        sentiment_analyst,
        "fetch_stocktwits_messages",
        lambda *_args, **_kwargs: "stocktwits",
    )

    def fail_reddit(*_args, **_kwargs):
        raise DataTransportError("HTTP 403: official source request failed")

    monkeypatch.setattr(sentiment_analyst, "fetch_reddit_posts", fail_reddit)

    def invoke(prompt_value):
        seen["system_prompt"] = prompt_value.to_messages()[0].content
        return SimpleNamespace(content="sentiment report")

    node = sentiment_analyst.create_sentiment_analyst(RunnableLambda(invoke))
    result = node(
        {
            "company_of_interest": "CRM",
            "asset_type": "stock",
            "trade_date": "2026-08-13",
            "messages": [],
        }
    )

    assert result["sentiment_report"] == "sentiment report"
    assert "<reddit unavailable: DataTransportError>" in seen["system_prompt"]
    assert "HTTP 403" not in seen["system_prompt"]


def test_news_analyst_exposes_insider_transactions_tool(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        news_analyst,
        "build_instrument_context",
        lambda ticker, asset_type="stock": f"{ticker}/{asset_type}",
    )

    class FakeLLM:
        def bind_tools(self, tools):
            seen["tool_names"] = [tool.name for tool in tools]

            def invoke(prompt_value):
                messages = prompt_value.to_messages()
                seen["system_prompt"] = messages[0].content
                return SimpleNamespace(tool_calls=[], content="news report")

            return RunnableLambda(invoke)

    node = news_analyst.create_news_analyst(FakeLLM())
    result = node(
        {
            "company_of_interest": "CRM",
            "asset_type": "stock",
            "trade_date": "2026-06-04",
            "messages": [],
        }
    )

    assert "get_insider_transactions" in seen["tool_names"]
    assert "get_insider_transactions(ticker)" in seen["system_prompt"]
    assert result["news_report"] == "news report"
