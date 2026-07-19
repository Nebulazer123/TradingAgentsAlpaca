from datetime import datetime, timedelta

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_global_news,
    get_insider_transactions,
    get_language_instruction,
    get_macro_context,
    get_news,
)
from tradingagents.agents.utils.reporting import analyst_report_from_result
from tradingagents.dataflows.config import get_config


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = build_instrument_context(
            state["company_of_interest"], asset_type
        )

        tools = [
            get_news,
            get_global_news,
            get_macro_context,
            get_insider_transactions,
        ]

        system_message = (
            "You are a news researcher tasked with analyzing recent news and trends over "
            "the past week. Please write a comprehensive report of the current state of "
            "the world that is relevant for trading and macroeconomics. Use the available "
            f"tools: get_news(ticker, start_date, end_date) for {asset_label}-specific news by "
            "ticker symbol, get_global_news(curr_date, look_back_days, limit) "
            "for broader macroeconomic news, get_macro_context(curr_date, look_back_days, "
            "limit) when official rates, inflation, employment, Treasury, or GDP context "
            "could confirm or contradict the news narrative, and get_insider_transactions"
            "(ticker) when insider buying/selling would confirm or contradict a "
            "stock-specific news thesis. Provide specific, actionable insights with "
            "supporting evidence to help traders make informed decisions."
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = analyst_report_from_result(
            result,
            analyst_label="News Analyst",
            report_label="news report",
        )

        return {
            "messages": [result],
            "news_report": report,
        }

    return news_analyst_node


def _truncate_block(value: str, *, max_chars: int = 7000) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n<snipped for bounded overnight context>"


def create_prefetched_news_analyst(llm):
    """Create a news analyst that receives bounded news data upfront.

    The original news analyst lets the LLM decide when to call tools, which is
    useful with strong hosted tool-call models but can loop or stall on local
    models. Overnight planning needs predictable runtime, so this variant keeps
    the same news lane while fetching ticker and macro news before one LLM call.
    """

    def news_analyst_node(state):
        ticker = state["company_of_interest"]
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = build_instrument_context(ticker, asset_type)
        config = get_config()
        lookback_days = int(config.get("global_news_lookback_days", 3) or 3)
        article_limit = int(config.get("global_news_article_limit", 5) or 5)
        current_dt = datetime.strptime(current_date, "%Y-%m-%d")
        start_date = (current_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        try:
            ticker_news = get_news.func(ticker, start_date, current_date)
        except Exception as exc:
            ticker_news = f"<unavailable: {exc}>"
        try:
            global_news = get_global_news.func(current_date, lookback_days, article_limit)
        except Exception as exc:
            global_news = f"<unavailable: {exc}>"
        try:
            macro_context = get_macro_context.func(current_date, lookback_days, 5)
        except Exception as exc:
            macro_context = f"<unavailable: {exc}>"

        system_message = f"""You are a news researcher analyzing recent news and macro trends relevant to trading {ticker}.

The data has already been fetched for you to avoid slow tool loops. Produce a concise, evidence-grounded report covering:
1. {asset_label}-specific headlines or lack of fresh headlines
2. macro / rate / sector / geopolitical context
3. whether official macro/rates data confirms or contradicts the headline narrative
4. catalysts, risks, and whether any item is thesis-changing
5. short-horizon implication for a trading supervisor
6. a Markdown table of the most important news signals

<start_of_ticker_news>
{_truncate_block(ticker_news)}
<end_of_ticker_news>

<start_of_global_news>
{_truncate_block(global_news)}
<end_of_global_news>

<start_of_macro_context>
{_truncate_block(macro_context)}
<end_of_macro_context>

Be honest about stale, missing, weekend, paywalled, or unavailable data. Do not invent sources, prices, or headlines.{get_language_instruction()}"""

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant collaborating with other trading assistants."
                    "\n{system_message}\n"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)
        result = (prompt | llm).invoke(state["messages"])

        return {
            "messages": [result],
            "news_report": analyst_report_from_result(
                result,
                analyst_label="News Analyst",
                report_label="news report",
            ),
        }

    return news_analyst_node
