"""Exposure and dynamic live-cap helpers for supervisor decisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import ROUND_DOWN, Decimal

BASE_LIVE_CAP = Decimal("100")
MAX_DYNAMIC_LIVE_CAP = Decimal("200")


def _as_decimal(value: Decimal | int | float | str | None, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return value if isinstance(value, Decimal) else Decimal(str(value))


def live_exposure_from_positions(positions: Sequence[Mapping]) -> Decimal:
    return sum(
        _as_decimal(position.get("cost_basis") or position.get("market_value"))
        for position in positions
    )


def total_unrealized_pl(positions: Sequence[Mapping]) -> Decimal:
    return sum(_as_decimal(position.get("unrealized_pl")) for position in positions)


def calculate_dynamic_live_cap(
    *,
    live_positions: Sequence[Mapping],
    recent_packets: Sequence[Mapping] = (),
    base_cap: Decimal = BASE_LIVE_CAP,
    max_cap: Decimal = MAX_DYNAMIC_LIVE_CAP,
) -> Decimal:
    if any(packet.get("issues") for packet in recent_packets):
        return min(base_cap, max_cap)
    exposure = live_exposure_from_positions(live_positions)
    if exposure <= 0:
        return min(base_cap, max_cap)
    pl_ratio = total_unrealized_pl(live_positions) / exposure
    cap = base_cap
    cap_span = max(Decimal("0"), max_cap - base_cap)
    for threshold, step_fraction in (
        (Decimal("0.08"), Decimal("1.00")),
        (Decimal("0.05"), Decimal("0.75")),
        (Decimal("0.03"), Decimal("0.50")),
        (Decimal("0.01"), Decimal("0.25")),
    ):
        if pl_ratio >= threshold:
            cap = base_cap + (cap_span * step_fraction)
            break
    return min(cap, max_cap).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

