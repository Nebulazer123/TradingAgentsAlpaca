from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from tradingagents.agents.analysts.market_analyst import create_market_analyst
from tradingagents.agents.utils.reporting import analyst_report_from_result


def test_analyst_report_preserves_normal_content():
    result = SimpleNamespace(content="Trend is improving.", tool_calls=[])

    assert (
        analyst_report_from_result(
            result,
            analyst_label="Market Analyst",
            report_label="market report",
        )
        == "Trend is improving."
    )


def test_analyst_report_marks_tool_call_loop_as_incomplete():
    result = SimpleNamespace(
        content="",
        tool_calls=[
            {"name": "get_stock_data"},
            {"function": {"name": "get_indicators"}},
        ],
    )

    report = analyst_report_from_result(
        result,
        analyst_label="Market Analyst",
        report_label="market report",
    )

    assert "INCOMPLETE_TOOL_CALL_LOOP" in report
    assert "get_stock_data" in report
    assert "get_indicators" in report
    assert "treat the analyst output as incomplete" in report


def test_analyst_report_marks_empty_final_response_as_missing_evidence():
    result = SimpleNamespace(content="", tool_calls=[])

    report = analyst_report_from_result(
        result,
        analyst_label="News Analyst",
        report_label="news report",
    )

    assert "EMPTY_ANALYST_RESPONSE" in report
    assert "missing evidence" in report


def test_tool_calling_market_analyst_never_returns_silent_empty_report():
    class _ToolCallingLLM:
        def bind_tools(self, _tools):
            return RunnableLambda(
                lambda _messages: AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_stock_data",
                            "args": {"symbol": "MSFT"},
                            "id": "call_1",
                        }
                    ],
                )
            )

    node = create_market_analyst(_ToolCallingLLM())

    output = node(
        {
            "company_of_interest": "MSFT",
            "trade_date": "2026-06-08",
            "asset_type": "stock",
            "messages": [HumanMessage(content="Analyze MSFT.")],
        }
    )

    assert output["market_report"]
    assert "INCOMPLETE_TOOL_CALL_LOOP" in output["market_report"]
    assert "get_stock_data" in output["market_report"]
