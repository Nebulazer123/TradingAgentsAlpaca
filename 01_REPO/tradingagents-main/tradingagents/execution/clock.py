"""Clock-skew guard for submit-capable runs."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

UTC = datetime.timezone.utc


@dataclass(frozen=True)
class ClockGuardResult:
    allowed: bool
    skew_seconds: float
    reason: str


def evaluate_clock_guard(
    *,
    local_time: datetime.datetime,
    reference_time: datetime.datetime,
    max_skew_seconds: int = 120,
) -> ClockGuardResult:
    local = local_time if local_time.tzinfo else local_time.replace(tzinfo=UTC)
    reference = reference_time if reference_time.tzinfo else reference_time.replace(tzinfo=UTC)
    skew = abs((local.astimezone(UTC) - reference.astimezone(UTC)).total_seconds())
    if skew > max_skew_seconds:
        return ClockGuardResult(
            allowed=False,
            skew_seconds=skew,
            reason=f"clock skew {skew:.0f}s exceeds {max_skew_seconds}s",
        )
    return ClockGuardResult(
        allowed=True,
        skew_seconds=skew,
        reason="clock skew is within tolerance",
    )
