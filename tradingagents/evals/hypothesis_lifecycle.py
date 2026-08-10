"""Hypothesis Lifecycle Ledger.

The hypothesis store (``hypotheses.jsonl``) is current-state-only: each
factory run rewrites every row with its latest status, which is the right
shape for consumers but silently destroys history. This module is the
append-only event ledger underneath it. Every meaningful transition —
registration, the first supported/refuted verdict, evidence-insufficient
downgrades, advisory-prior emission and retraction — becomes one immutable,
machine-readable event with a deterministic id, so the learning history is
auditable and replayable even as statuses oscillate.

Design rules:

- Events are derived by diffing the store state before and after an
  evaluation run; an unchanged hypothesis emits nothing.
- Registration events are backfilled from store state (dated at
  ``preregistered_at``), so a store that predates this ledger seeds its own
  history on the first run.
- Event ids are deterministic hashes of the transition, so replaying the
  same diff never duplicates history (`append_lifecycle_events` dedupes).
- The ledger is analysis-only; events carry no execution authority.

This module deliberately imports nothing from ``hypothesis_factory`` (the
factory imports it), so hypotheses are read duck-typed via the attributes
``hypothesis_id``, ``status``, ``preregistered_at``, ``context``, ``claim``,
``out_of_sample_count``, and ``out_of_sample_delta``.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

UTC = datetime.timezone.utc

DEFAULT_LIFECYCLE_PATH = Path("results/hypothesis_factory/lifecycle.jsonl")

EVENT_HYPOTHESIS_REGISTERED = "hypothesis_registered"
EVENT_HYPOTHESIS_SUPPORTED = "hypothesis_supported"
EVENT_HYPOTHESIS_REFUTED = "hypothesis_refuted"
EVENT_HYPOTHESIS_EVIDENCE_INSUFFICIENT = "hypothesis_evidence_insufficient"
EVENT_HYPOTHESIS_STATUS_CHANGED = "hypothesis_status_changed"
EVENT_PRIOR_EMITTED = "prior_emitted"
EVENT_PRIOR_RETRACTED = "prior_retracted"

# Status strings mirror the Hypothesis Factory vocabulary. They are restated
# here (instead of imported) so the factory can depend on this module without
# a cycle; tests assert the two vocabularies stay in lockstep.
_STATUS_PREREGISTERED = "preregistered"
_STATUS_SUPPORTED = "supported"
_STATUS_REFUTED = "refuted"
_STATUS_INSUFFICIENT = "insufficient_out_of_sample"

STATUS_EVENT_TYPES: dict[str, str] = {
    _STATUS_SUPPORTED: EVENT_HYPOTHESIS_SUPPORTED,
    _STATUS_REFUTED: EVENT_HYPOTHESIS_REFUTED,
    _STATUS_INSUFFICIENT: EVENT_HYPOTHESIS_EVIDENCE_INSUFFICIENT,
}


@dataclass(frozen=True)
class HypothesisLifecycleEvent:
    """One immutable transition in a hypothesis's life."""

    event_id: str
    event_type: str
    hypothesis_id: str
    occurred_at: str
    from_status: str | None
    to_status: str | None
    out_of_sample_count: int | None = None
    out_of_sample_delta: str | None = None
    prior_multiplier: str | None = None
    context: dict[str, str] = field(default_factory=dict)
    claim: str = ""
    note: str = ""
    analysis_only: bool = True
    execution_authority: str = "none"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(value: str | datetime.datetime) -> str:
    if isinstance(value, datetime.datetime):
        stamped = value if value.tzinfo else value.replace(tzinfo=UTC)
        return stamped.astimezone(UTC).isoformat(timespec="seconds")
    return str(value).strip()


def _event_id(
    hypothesis_id: str,
    event_type: str,
    occurred_at: str,
    from_status: str | None,
    to_status: str | None,
) -> str:
    payload = json.dumps(
        [hypothesis_id, event_type, occurred_at, from_status or "", to_status or ""],
        sort_keys=True,
    )
    return f"hle-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _make_event(
    *,
    event_type: str,
    hypothesis: Any,
    occurred_at: str,
    from_status: str | None,
    to_status: str | None,
    prior_multiplier: str | None = None,
    note: str = "",
) -> HypothesisLifecycleEvent:
    return HypothesisLifecycleEvent(
        event_id=_event_id(
            str(hypothesis.hypothesis_id), event_type, occurred_at, from_status, to_status
        ),
        event_type=event_type,
        hypothesis_id=str(hypothesis.hypothesis_id),
        occurred_at=occurred_at,
        from_status=from_status,
        to_status=to_status,
        out_of_sample_count=getattr(hypothesis, "out_of_sample_count", None),
        out_of_sample_delta=getattr(hypothesis, "out_of_sample_delta", None),
        prior_multiplier=prior_multiplier,
        context=dict(getattr(hypothesis, "context", {}) or {}),
        claim=str(getattr(hypothesis, "claim", "") or ""),
        note=note,
    )


def hypothesis_lifecycle_events(
    before: Sequence[Any],
    after: Sequence[Any],
    *,
    evaluated_at: str | datetime.datetime,
    known_events: Sequence[HypothesisLifecycleEvent] = (),
    prior_multipliers: Mapping[str, str] | None = None,
) -> list[HypothesisLifecycleEvent]:
    """Derive lifecycle events from a store diff.

    ``before`` is the store state loaded at the start of a factory run (last
    run's statuses); ``after`` is the freshly evaluated state. Registration
    events are backfilled for any ``after`` hypothesis that has no
    ``hypothesis_registered`` event in ``known_events``, dated at its own
    ``preregistered_at``. Status transitions and advisory-prior set changes
    are dated at ``evaluated_at``. Unchanged hypotheses emit nothing, so
    re-running the factory on identical evidence is event-silent.
    """

    stamp = _iso(evaluated_at)
    multipliers = dict(prior_multipliers or {})
    registered_ids = {
        event.hypothesis_id
        for event in known_events
        if event.event_type == EVENT_HYPOTHESIS_REGISTERED
    }
    before_by_id = {str(item.hypothesis_id): item for item in before}
    ordered_after = sorted(after, key=lambda item: str(item.hypothesis_id))

    registrations: list[HypothesisLifecycleEvent] = []
    transitions: list[HypothesisLifecycleEvent] = []
    emissions: list[HypothesisLifecycleEvent] = []
    retractions: list[HypothesisLifecycleEvent] = []
    for item in ordered_after:
        hypothesis_id = str(item.hypothesis_id)
        previous = before_by_id.get(hypothesis_id)
        if hypothesis_id not in registered_ids:
            registrations.append(
                _make_event(
                    event_type=EVENT_HYPOTHESIS_REGISTERED,
                    hypothesis=item,
                    occurred_at=_iso(getattr(item, "preregistered_at", stamp)),
                    from_status=None,
                    to_status=_STATUS_PREREGISTERED,
                    note=(
                        "preregistered from mined resolution evidence"
                        if previous is None
                        else "registration backfilled from store state"
                    ),
                )
            )
        previous_status = (
            str(previous.status) if previous is not None else _STATUS_PREREGISTERED
        )
        current_status = str(item.status)
        if current_status != previous_status:
            transitions.append(
                _make_event(
                    event_type=STATUS_EVENT_TYPES.get(
                        current_status, EVENT_HYPOTHESIS_STATUS_CHANGED
                    ),
                    hypothesis=item,
                    occurred_at=stamp,
                    from_status=previous_status,
                    to_status=current_status,
                    note=str(getattr(item, "evaluation_note", "") or ""),
                )
            )
        previously_supported = previous_status == _STATUS_SUPPORTED
        currently_supported = current_status == _STATUS_SUPPORTED
        if currently_supported and not previously_supported:
            emissions.append(
                _make_event(
                    event_type=EVENT_PRIOR_EMITTED,
                    hypothesis=item,
                    occurred_at=stamp,
                    from_status=previous_status,
                    to_status=current_status,
                    prior_multiplier=multipliers.get(hypothesis_id),
                    note="supported hypothesis now flows as a bounded advisory prior",
                )
            )
        elif previously_supported and not currently_supported:
            retractions.append(
                _make_event(
                    event_type=EVENT_PRIOR_RETRACTED,
                    hypothesis=item,
                    occurred_at=stamp,
                    from_status=previous_status,
                    to_status=current_status,
                    note="hypothesis left supported status; advisory prior withdrawn",
                )
            )
    return [*registrations, *transitions, *emissions, *retractions]


def load_lifecycle_events_with_stats(
    path: str | Path = DEFAULT_LIFECYCLE_PATH,
) -> tuple[list[HypothesisLifecycleEvent], int]:
    """Load the lifecycle ledger and count non-empty lines that fail to parse."""

    ledger_path = Path(path)
    if not ledger_path.exists():
        return [], 0
    events: list[HypothesisLifecycleEvent] = []
    corrupt_line_count = 0
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(HypothesisLifecycleEvent(**json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError):
            corrupt_line_count += 1
            continue
    return events, corrupt_line_count


def append_lifecycle_events(
    events: Sequence[HypothesisLifecycleEvent],
    *,
    path: str | Path = DEFAULT_LIFECYCLE_PATH,
) -> int:
    """Append events, skipping ids the ledger already holds. Never rewrites."""

    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = {event.event_id for event in load_lifecycle_events_with_stats(ledger_path)[0]}
    appended = 0
    with ledger_path.open("a", encoding="utf-8") as handle:
        for event in events:
            if event.event_id in existing_ids:
                continue
            handle.write(json.dumps(event.as_dict(), sort_keys=True) + "\n")
            existing_ids.add(event.event_id)
            appended += 1
    return appended


def summarize_lifecycle(
    events: Sequence[HypothesisLifecycleEvent],
) -> dict[str, Any]:
    """Aggregate the event history into a machine-readable summary."""

    event_type_counts: dict[str, int] = {}
    latest_event_by_hypothesis: dict[str, dict[str, Any]] = {}
    occurred: list[str] = []
    for event in events:
        event_type_counts[event.event_type] = event_type_counts.get(event.event_type, 0) + 1
        occurred.append(event.occurred_at)
        latest_event_by_hypothesis[event.hypothesis_id] = {
            "event_type": event.event_type,
            "occurred_at": event.occurred_at,
            "to_status": event.to_status,
        }
    return {
        "kind": "hypothesis_lifecycle_summary",
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "event_count": len(events),
        "event_type_counts": event_type_counts,
        "hypothesis_count": len(latest_event_by_hypothesis),
        "first_event_at": min(occurred) if occurred else None,
        "last_event_at": max(occurred) if occurred else None,
        "latest_event_by_hypothesis": latest_event_by_hypothesis,
    }
