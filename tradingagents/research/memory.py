"""Research-memory redaction and local fallback helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|ak|pk|z)_[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\b[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{16,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|authorization|bearer|token|secret)\s*[:=]\s*\S+"),
)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
ACCOUNTISH_PATTERN = re.compile(r"(?i)\b(account|acct|order)[_-]?(id)?\s*[:=]\s*[A-Za-z0-9_\-]{6,}\b")
PROMPT_INJECTION_PATTERN = re.compile(
    r"(?i)(ignore (all )?(previous|prior) instructions|system prompt|developer message|"
    r"reveal secrets|exfiltrate|tool call)"
)


def redact_research_text(value: str) -> tuple[str, bool]:
    """Redact secrets/account-like strings and quote prompt-injection text."""
    text = str(value or "")
    changed = False
    for pattern in SECRET_PATTERNS:
        text, count = pattern.subn("[REDACTED_SECRET]", text)
        changed = changed or bool(count)
    text, count = EMAIL_PATTERN.subn("[REDACTED_EMAIL]", text)
    changed = changed or bool(count)
    text, count = ACCOUNTISH_PATTERN.subn("[REDACTED_ACCOUNT_REF]", text)
    changed = changed or bool(count)
    text, count = PROMPT_INJECTION_PATTERN.subn("[QUOTED_UNTRUSTED_INSTRUCTION]", text)
    changed = changed or bool(count)
    return text, changed


def contains_sensitive_text(value: Any) -> bool:
    text = str(value)
    return any(pattern.search(text) for pattern in (*SECRET_PATTERNS, EMAIL_PATTERN, ACCOUNTISH_PATTERN))


def redact_payload(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        return redact_research_text(value)
    if isinstance(value, Mapping):
        changed = False
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            safe_item, item_changed = redact_payload(item)
            redacted[str(key)] = safe_item
            changed = changed or item_changed
        return redacted, changed
    if isinstance(value, list):
        changed = False
        items = []
        for item in value:
            safe_item, item_changed = redact_payload(item)
            items.append(safe_item)
            changed = changed or item_changed
        return items, changed
    return value, False


@dataclass(frozen=True)
class MemoryBackendStatus:
    backend: str
    status: str
    reason: str
    local_fallback_used: bool = True
    can_store_private_data: bool = False
    can_submit_orders: bool = False

    def model_dump(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "status": self.status,
            "reason": self.reason,
            "local_fallback_used": self.local_fallback_used,
            "can_store_private_data": self.can_store_private_data,
            "can_submit_orders": self.can_submit_orders,
        }


def memory_backend_status_from_env(env: Mapping[str, str]) -> MemoryBackendStatus:
    if str(env.get("ZEP_API_KEY", "")).strip():
        return MemoryBackendStatus(
            backend="local_with_optional_zep_available",
            status="fallback_local_default",
            reason="Zep key exists, but repo memory defaults to local redacted packets unless a future free-tier Zep adapter is explicitly enabled.",
        )
    return MemoryBackendStatus(
        backend="local_jsonl",
        status="selected",
        reason="No cloud graph memory is required; use local redacted JSONL memory.",
    )
