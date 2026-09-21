"""Locked SQLite checkpoint compatibility with real message-bearing writes."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, MessagesState, StateGraph

from tradingagents.graph.checkpointer import get_checkpointer


def test_real_sqlite_retains_typed_messages_and_json_metadata(tmp_path):
    model_message = AIMessage(
        content="retained report", id="model-response",
        response_metadata={"provider": "synthetic", "id": "provider-response"},
        usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
    )
    workflow = StateGraph(MessagesState)
    workflow.add_node("analyst", lambda _state: {"messages": [model_message]})
    workflow.add_edge(START, "analyst")
    workflow.add_edge("analyst", END)
    config = {"configurable": {"thread_id": "synthetic-message-checkpoint"}}
    with get_checkpointer(tmp_path / "cache", "AAPL") as saver:
        graph = workflow.compile(checkpointer=saver)
        state = graph.invoke({"messages": [HumanMessage(content="question", id="human")]}, config)
        assert state["messages"][-1] == model_message
        checkpoint = saver.get_tuple(config)
        assert isinstance(checkpoint.checkpoint["channel_values"]["messages"][-1], AIMessage)
        metadata_message = checkpoint.metadata["writes"]["analyst"]["messages"][0]
        assert metadata_message["type"] == "ai"
        assert metadata_message["data"]["content"] == model_message.content
        assert metadata_message["data"]["usage_metadata"] == model_message.usage_metadata
    with get_checkpointer(tmp_path / "cache", "AAPL") as saver:
        restored = workflow.compile(checkpointer=saver).get_state(config)
        assert restored.next == ()
        assert restored.values["messages"][-1] == model_message


@pytest.mark.parametrize("bad", [object(), {1: "nonstring-key"}, float("nan")])
def test_checkpoint_metadata_rejects_unknown_or_noncanonical_values(bad):
    from tradingagents.graph.checkpointer import _json_checkpoint_metadata

    with pytest.raises(ValueError, match="checkpoint metadata"):
        _json_checkpoint_metadata({"writes": bad})
