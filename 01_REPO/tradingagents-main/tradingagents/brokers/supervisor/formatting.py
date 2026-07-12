"""Shared supervisor formatting helpers."""

from __future__ import annotations

import re
from decimal import Decimal


def email_reason_text(reason: object, *, max_length: int = 190) -> str:
    text = str(reason or "no supervisor packets found").strip()

    def _round_long_decimal(match: re.Match[str]) -> str:
        try:
            return f"{Decimal(match.group(0)):.2f}"
        except Exception:
            return match.group(0)

    text = re.sub(r"\b\d+\.\d{5,}\b", _round_long_decimal, text)
    if len(text) > max_length:
        return text[: max_length - 3].rstrip() + "..."
    return text
