from datetime import datetime, timedelta

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_indicators,
    get_language_instruction,
    get_macro_context,
    get_stock_data,
)
from tradingagents.agents.utils.reporting import analyst_report_from_result
from tradingagents.dataflows.config import get_config


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        instrument_context = build_instrument_context(
            state["company_of_interest"], asset_type
        )

        tools = [
            get_stock_data,
            get_indicators,
            get_macro_context,
        ]

        system_message = (
            """You are a trading assistant tasked with analyzing financial markets. Your role is to select the **most relevant indicators** for a given market condition or trading strategy from the following list. The goal is to choose up to **8 indicators** that provide complementary insights without redundancy. Categories and each category's indicators are:

Moving Averages:
- close_50_sma: 50 SMA: A medium-term trend indicator. Usage: Identify trend direction and serve as dynamic support/resistance. Tips: It lags price; combine with faster indicators for timely signals.
- close_200_sma: 200 SMA: A long-term trend benchmark. Usage: Confirm overall market trend and identify golden/death cross setups. Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries.
- close_10_ema: 10 EMA: A responsive short-term average. Usage: Capture quick shifts in momentum and potential entry points. Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals.

MACD Related:
- macd: MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers and divergence as signals of trend changes. Tips: Confirm with other indicators in low-volatility or sideways markets.
- macds: MACD Signal: An EMA smoothing of the MACD line. Usage: Use crossovers with the MACD line to trigger trades. Tips: Should be part of a broader strategy to avoid false positives.
- macdh: MACD Histogram: Shows the gap between the MACD line and its signal. Usage: Visualize momentum strength and spot divergence early. Tips: Can be volatile; complement with additional filters in fast-moving markets.

Momentum Indicators:
- rsi: RSI: Measures momentum to flag overbought/oversold conditions. Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis.

Volatility Indicators:
- boll: Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. Usage: Acts as a dynamic benchmark for price movement. Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals.
- boll_ub: Bollinger Upper Band: Typically 2 standard deviations above the middle line. Usage: Signals potential overbought conditions and breakout zones. Tips: Confirm signals with other tools; prices may ride the band in strong trends.
- boll_lb: Bollinger Lower Band: Typically 2 standard deviations below the middle line. Usage: Indicates potential oversold conditions. Tips: Use additional analysis to avoid false reversal signals.
- atr: ATR: Averages true range to measure volatility. Usage: Set stop-loss levels and adjust position sizes based on current market volatility. Tips: It's a reactive measure, so use it as part of a broader risk management strategy.

Volume-Based Indicators:
- vwma: VWMA: A moving average weighted by volume. Usage: Confirm trends by integrating price action with volume data. Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses.

- Select indicators that provide diverse and complementary information. Avoid redundancy (e.g., do not select both rsi and stochrsi). Also briefly explain why they are suitable for the given market context. When you tool call, please use the exact name of the indicators provided above as they are defined parameters, otherwise your call will fail. Please make sure to call get_stock_data first to retrieve the CSV that is needed to generate indicators. Then use get_indicators with the specific indicator names."""
            + """ Use get_macro_context when rates, inflation, unemployment, Treasury yields, or broader regime could affect whether a dip is buyable or a spike should be sold. Write a very detailed and nuanced report of the trends you observe. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."""
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
            analyst_label="Market Analyst",
            report_label="market report",
        )

        return {
            "messages": [result],
            "market_report": report,
        }

    return market_analyst_node


def create_prefetched_market_analyst(llm):
    """Create a market analyst that receives data upfront instead of tool-calling.

    Local OpenAI-compatible models can be slow or repetitive with LangChain tool
    loops. Overnight planning still needs a market analyst report, but it can
    safely prefetch a bounded, deterministic data bundle before the LLM call.
    """

    def market_analyst_node(state):
        ticker = state["company_of_interest"]
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        instrument_context = build_instrument_context(ticker, asset_type)
        current_dt = datetime.strptime(current_date, "%Y-%m-%d")
        start_date = (current_dt - timedelta(days=14)).strftime("%Y-%m-%d")
        # yfinance-style data sources treat the end date as exclusive, so add
        # one day to avoid empty same-day weekend/after-close ranges.
        end_date = (current_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        stock_block = get_stock_data.func(ticker, start_date, end_date)
        indicator_names = get_config().get(
            "overnight_market_indicators",
            ["close_10_ema", "close_50_sma", "rsi", "macd", "vwma"],
        )
        indicator_blocks = []
        for indicator in indicator_names[:6]:
            try:
                indicator_blocks.append(
                    f"## {indicator}\n"
                    + get_indicators.func(ticker, indicator, current_date, 20)
                )
            except Exception as exc:
                indicator_blocks.append(f"## {indicator}\n<unavailable: {exc}>")
        try:
            macro_block = get_macro_context.func(current_date, 30, 5)
        except Exception as exc:
            macro_block = f"<unavailable: {exc}>"

        system_message = f"""You are a trading assistant tasked with analyzing financial markets for {ticker}.

The data has already been fetched for you to avoid slow tool loops. Produce a concise but evidence-grounded market report with:
1. trend direction and momentum
2. support/resistance or price-level observations visible in the data
3. volume confirmation or lack of confirmation
4. official macro/rates context that affects whether dips are buyable or spikes should be sold
5. tactical implication for a short-horizon trading supervisor
6. a Markdown table summarizing the strongest signals

<start_of_stock_data>
{stock_block}
<end_of_stock_data>

<start_of_indicators>
{chr(10).join(indicator_blocks)}
<end_of_indicators>

<start_of_macro_context>
{macro_block}
<end_of_macro_context>

Be honest about stale, missing, weekend, or unavailable data. Do not invent prices or indicators.{get_language_instruction()}"""

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
            "market_report": analyst_report_from_result(
                result,
                analyst_label="Market Analyst",
                report_label="market report",
            ),
        }

    return market_analyst_node
