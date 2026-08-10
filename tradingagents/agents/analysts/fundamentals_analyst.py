from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_language_instruction,
)
from tradingagents.agents.utils.reporting import analyst_report_from_result


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        instrument_context = build_instrument_context(state["company_of_interest"], asset_type)

        tools = [
            get_fundamentals,
            get_balance_sheet,
            get_cashflow,
            get_income_statement,
        ]

        system_message = (
            "You are a researcher tasked with analyzing fundamental information over the past week about a company. Please write a comprehensive report of the company's fundamental information such as financial documents, company profile, basic company financials, and company financial history to gain a full view of the company's fundamental information to inform traders. Make sure to include as much detail as possible. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + " Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."
            + " Use the available tools: `get_fundamentals` for comprehensive company analysis, `get_balance_sheet`, `get_cashflow`, and `get_income_statement` for specific financial statements."
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
            analyst_label="Fundamentals Analyst",
            report_label="fundamentals report",
        )

        return {
            "messages": [result],
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node


def _truncate_block(value: str, *, max_chars: int = 7000) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n<snipped for bounded overnight context>"


def _safe_fundamental_block(label: str, fetcher, *args) -> str:
    try:
        return f"## {label}\n{_truncate_block(fetcher.func(*args))}"
    except Exception as exc:
        return f"## {label}\n<unavailable: {exc}>"


def create_prefetched_fundamentals_analyst(llm):
    """Create a fundamentals analyst with pre-fetched bounded data.

    This keeps the fundamentals lane in the overnight graph while avoiding
    local-model tool-call stalls. Each financial block is collected once, then
    summarized in a single model pass.
    """

    def fundamentals_analyst_node(state):
        ticker = state["company_of_interest"]
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        instrument_context = build_instrument_context(ticker, asset_type)
        blocks = [
            _safe_fundamental_block("Company fundamentals", get_fundamentals, ticker, current_date),
            _safe_fundamental_block("Quarterly balance sheet", get_balance_sheet, ticker, "quarterly", current_date),
            _safe_fundamental_block("Quarterly cash flow", get_cashflow, ticker, "quarterly", current_date),
            _safe_fundamental_block("Quarterly income statement", get_income_statement, ticker, "quarterly", current_date),
        ]

        system_message = f"""You are a fundamentals researcher analyzing {ticker} for a short-horizon trading supervisor.

The data has already been fetched for you to avoid slow tool loops. Produce a concise, evidence-grounded report covering:
1. financial strength and business quality
2. recent revenue / margin / cash-flow signals visible in the provided data
3. valuation or balance-sheet risks if available
4. whether fundamentals support, weaken, or merely contextualize a short-horizon trade
5. a Markdown table of the strongest fundamental signals

<start_of_fundamental_data>
{chr(10).join(blocks)}
<end_of_fundamental_data>

Be honest about stale, missing, or unavailable data. Do not invent figures that are not present in the data.{get_language_instruction()}"""

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
            "fundamentals_report": analyst_report_from_result(
                result,
                analyst_label="Fundamentals Analyst",
                report_label="fundamentals report",
            ),
        }

    return fundamentals_analyst_node
