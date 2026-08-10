"""Prompt registry metadata for research and market-mirror prompts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tradingagents.policy.packets import write_research_packet
from tradingagents.schemas.research import PromptRegistryPacket

from .memory import redact_research_text

FORBIDDEN_TRADE_OUTPUTS = {
    "trade_intent",
    "submit_order",
    "size_position",
    "promote_sleeve",
    "waive_live_gate",
}


def prompt_hash(prompt_text: str) -> str:
    safe_prompt, _ = redact_research_text(prompt_text)
    return hashlib.sha256(safe_prompt.encode("utf-8")).hexdigest()


def register_prompt_metadata(
    *,
    prompt_id: str,
    prompt_text: str,
    prompt_role: str,
    allowed_outputs: list[str] | None = None,
    forbidden_outputs: list[str] | None = None,
    methodology_refs: list[str] | None = None,
    model_route: str = "deterministic_or_local",
    output_dir: str | Path = "results/prompt_registry",
) -> tuple[PromptRegistryPacket, Path]:
    forbidden = sorted(set(forbidden_outputs or []) | FORBIDDEN_TRADE_OUTPUTS)
    packet = PromptRegistryPacket(
        prompt_id=prompt_id,
        prompt_hash=prompt_hash(prompt_text),
        prompt_role=prompt_role,
        allowed_outputs=allowed_outputs or ["research_summary", "invalidators", "watch_items"],
        forbidden_outputs=forbidden,
        source_refs=methodology_refs or [],
        freshness={
            "raw_prompt_stored": False,
            "model_route": model_route,
            "clean_room": "methodology inspiration only; no copied AGPL code/schema/prompt",
        },
        tool_route="prompt_registry",
        redaction_status="redacted",
    )
    return packet, write_research_packet(packet, output_dir)


def prompt_metadata_view(packet: PromptRegistryPacket) -> dict[str, Any]:
    return {
        "prompt_id": packet.prompt_id,
        "prompt_hash": packet.prompt_hash,
        "prompt_role": packet.prompt_role,
        "allowed_outputs": packet.allowed_outputs,
        "forbidden_outputs": packet.forbidden_outputs,
        "raw_prompt_stored": packet.freshness.get("raw_prompt_stored", False),
    }
