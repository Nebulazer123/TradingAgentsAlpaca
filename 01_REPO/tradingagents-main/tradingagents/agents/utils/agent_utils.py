from langchain_core.messages import HumanMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import get_stock_data
from tradingagents.agents.utils.fundamental_data_tools import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
)
from tradingagents.agents.utils.news_data_tools import (
    get_global_news,
    get_insider_transactions,
    get_macro_context,
    get_news,
    get_sentiment_context,
    get_supplemental_market_context,
)
from tradingagents.agents.utils.technical_indicators_tools import get_indicators

__all__ = [
    "build_instrument_context",
    "create_msg_delete",
    "get_balance_sheet",
    "get_cashflow",
    "get_fundamentals",
    "get_global_news",
    "get_income_statement",
    "get_indicators",
    "get_insider_transactions",
    "get_language_instruction",
    "get_macro_context",
    "get_news",
    "get_sentiment_context",
    "get_stock_data",
    "get_supplemental_market_context",
]


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Applied to every agent whose output reaches the saved report —
    analysts, researchers, debaters, research manager, trader, and
    portfolio manager — so a non-English run produces a fully localized
    report rather than a mix of languages.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(ticker: str, asset_type: str = "stock") -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    instrument_label = "asset" if asset_type == "crypto" else "instrument"
    extra_hint = (
        " Treat it as a crypto asset rather than a company, and do not assume company fundamentals are available."
        if asset_type == "crypto"
        else ""
    )
    return (
        f"The {instrument_label} to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`, `-USD`)."
        + extra_hint
    )

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        # Under concurrent analyst fan-out each branch only sees its own
        # ephemeral message state, so enumerating per-id RemoveMessage ops
        # crashes the add_messages reducer at the merge when an id is not in
        # the shared canonical channel ("Attempting to delete a message with
        # an ID that doesn't exist"). The REMOVE_ALL_MESSAGES sentinel clears
        # the channel without naming ids, which is safe in both the
        # sequential and parallel paths.
        removal = RemoveMessage(id=REMOVE_ALL_MESSAGES)

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": [removal, placeholder]}

    return delete_messages


        
