from inspect import getsource

from tradingagents.agents.analysts.news_analyst import create_news_analyst
from tradingagents.agents.utils.agent_utils import get_news


def test_get_news_tool_contract_uses_ticker_not_free_form_query():
    assert tuple(get_news.args) == ("ticker", "start_date", "end_date")
    assert "query" not in get_news.args


def test_news_analyst_prompt_matches_get_news_ticker_contract():
    prompt_source = getsource(create_news_analyst)

    assert "get_news(ticker, start_date, end_date)" in prompt_source
    assert "get_news(query" not in prompt_source
