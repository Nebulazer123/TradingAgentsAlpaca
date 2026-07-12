from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part.strip() for part in parts if part and part.strip()).strip()
    return str(content or "").strip()


def _tool_call_name(tool_call: Any) -> str:
    if isinstance(tool_call, Mapping):
        if tool_call.get("name"):
            return str(tool_call["name"])
        function = tool_call.get("function")
        if isinstance(function, Mapping) and function.get("name"):
            return str(function["name"])
    name = getattr(tool_call, "name", None)
    return str(name or "unknown_tool")


def analyst_report_from_result(
    result: Any,
    *,
    analyst_label: str,
    report_label: str,
) -> str:
    content = _content_to_text(getattr(result, "content", ""))
    tool_calls = list(getattr(result, "tool_calls", None) or [])

    if tool_calls:
        names = ", ".join(_tool_call_name(call) for call in tool_calls[:8])
        if len(tool_calls) > 8:
            names += f", ... +{len(tool_calls) - 8} more"
        return (
            f"## {analyst_label} report incomplete\n\n"
            "Status: INCOMPLETE_TOOL_CALL_LOOP\n\n"
            f"The analyst requested tool calls instead of producing a final {report_label}. "
            f"Requested tools: {names or 'unknown_tool'}.\n\n"
            "If this appears in a final packet, treat the analyst output as incomplete, "
            "inspect tool errors/recursion limits, and rerun with the pre-fetched/tool-free "
            "analyst profile or fresh source packets."
        )

    if content:
        return content

    return (
        f"## {analyst_label} report unavailable\n\n"
        "Status: EMPTY_ANALYST_RESPONSE\n\n"
        f"The analyst returned no final {report_label}. Treat this as missing evidence, "
        "not as a neutral or successful report. Inspect model/tool logs and rerun with "
        "a bounded fallback before using this analysis for a trade plan."
    )
