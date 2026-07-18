"""Local, owned incident lifecycle records for the control plane."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any

from tradingagents.policy.io import atomic_write_text


class IncidentStage(str, Enum):
    DETECTED = "detected"
    DIAGNOSING = "diagnosing"
    REPAIRING = "repairing"
    VERIFYING = "verifying"
    READY = "ready"
    REARMED = "rearmed"
    MONITORING = "monitoring"
    CLOSED = "closed"
    EXTERNAL_BLOCKED = "external_blocked"


ALLOWED_TRANSITIONS = {
    IncidentStage.DETECTED: {IncidentStage.DIAGNOSING, IncidentStage.EXTERNAL_BLOCKED},
    IncidentStage.DIAGNOSING: {
        IncidentStage.REPAIRING,
        IncidentStage.VERIFYING,
        IncidentStage.EXTERNAL_BLOCKED,
    },
    IncidentStage.REPAIRING: {
        IncidentStage.VERIFYING,
        IncidentStage.DIAGNOSING,
        IncidentStage.EXTERNAL_BLOCKED,
    },
    IncidentStage.VERIFYING: {
        IncidentStage.READY,
        IncidentStage.REPAIRING,
        IncidentStage.EXTERNAL_BLOCKED,
    },
    IncidentStage.READY: {
        IncidentStage.REARMED,
        IncidentStage.REPAIRING,
        IncidentStage.EXTERNAL_BLOCKED,
    },
    IncidentStage.REARMED: {IncidentStage.MONITORING, IncidentStage.REPAIRING},
    IncidentStage.MONITORING: {IncidentStage.CLOSED, IncidentStage.REPAIRING},
    IncidentStage.EXTERNAL_BLOCKED: {IncidentStage.DIAGNOSING},
    IncidentStage.CLOSED: set(),
}

_SAFE_INCIDENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def is_safe_incident_id(value: object) -> bool:
    return isinstance(value, str) and _SAFE_INCIDENT_ID.fullmatch(value) is not None


def _as_utc(value: dt.datetime | None) -> dt.datetime:
    current = value or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=dt.timezone.utc)
    return current.astimezone(dt.timezone.utc)


def _timestamp(value: dt.datetime) -> str:
    return value.isoformat()


@dataclass(frozen=True)
class Incident:
    schema_version: str
    incident_id: str
    kind: str
    subject: str
    stage: IncidentStage
    owner_role: str
    created_at: str
    updated_at: str
    lease_expires_at: str
    next_action: str
    retry_budget: int
    attempt_count: int
    repairer_run_id: str | None
    verifier_run_id: str | None
    evidence_refs: tuple[str, ...]
    external_blockers: tuple[str, ...]
    history: tuple[dict[str, Any], ...]

    @classmethod
    def open(
        cls,
        *,
        incident_id: str,
        kind: str,
        subject: str,
        owner_role: str,
        now: dt.datetime | None = None,
    ) -> Incident:
        owner = owner_role.strip()
        if not owner:
            raise ValueError("owner_role must not be empty")
        opened_at = _as_utc(now)
        opened_at_text = _timestamp(opened_at)
        return cls(
            schema_version="tradingagents.incident.v1",
            incident_id=incident_id,
            kind=kind,
            subject=subject,
            stage=IncidentStage.DETECTED,
            owner_role=owner,
            created_at=opened_at_text,
            updated_at=opened_at_text,
            lease_expires_at=_timestamp(opened_at + dt.timedelta(minutes=30)),
            next_action="diagnose_root_cause",
            retry_budget=3,
            attempt_count=0,
            repairer_run_id=None,
            verifier_run_id=None,
            evidence_refs=(),
            external_blockers=(),
            history=(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "incident_id": self.incident_id,
            "kind": self.kind,
            "subject": self.subject,
            "stage": self.stage.value,
            "owner_role": self.owner_role,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "lease_expires_at": self.lease_expires_at,
            "next_action": self.next_action,
            "retry_budget": self.retry_budget,
            "attempt_count": self.attempt_count,
            "repairer_run_id": self.repairer_run_id,
            "verifier_run_id": self.verifier_run_id,
            "evidence_refs": list(self.evidence_refs),
            "external_blockers": list(self.external_blockers),
            "history": list(self.history),
        }


def transition_incident(
    incident: Incident,
    target_stage: IncidentStage,
    *,
    now: dt.datetime | None = None,
) -> Incident:
    if target_stage not in ALLOWED_TRANSITIONS[incident.stage]:
        raise ValueError(
            "invalid incident transition: "
            f"{incident.stage.value} -> {target_stage.value}"
        )
    transitioned_at = _timestamp(_as_utc(now))
    history_event = {
        "event": "transitioned",
        "from_stage": incident.stage.value,
        "to_stage": target_stage.value,
        "at": transitioned_at,
    }
    return replace(
        incident,
        stage=target_stage,
        updated_at=transitioned_at,
        history=(*incident.history, history_event),
    )


class IncidentStore:
    """Persist immutable event lines beside mutable incident snapshots."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def record(self, incident: Incident, *, event: str) -> Incident:
        if not is_safe_incident_id(incident.incident_id):
            raise ValueError("invalid incident_id")
        serialized = incident.to_dict()
        incident_snapshot = self.root / incident.incident_id / "latest.json"
        atomic_write_text(incident_snapshot, json.dumps(serialized, indent=2, sort_keys=True))
        self._append_event(incident, event)
        atomic_write_text(self.root / "latest.json", json.dumps(serialized, indent=2, sort_keys=True))
        return incident

    def _append_event(self, incident: Incident, event: str) -> None:
        event_path = self.root / "events.jsonl"
        event_path.parent.mkdir(parents=True, exist_ok=True)
        compact_event = {
            "event": str(event)[:128],
            "incident_id": incident.incident_id,
            "stage": incident.stage.value,
            "owner_role": str(incident.owner_role)[:128],
            "updated_at": str(incident.updated_at)[:64],
        }
        encoded_line = (
            json.dumps(compact_event, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8")
        # A single O_APPEND write keeps concurrent records from interleaving lines.
        descriptor = os.open(event_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            if os.write(descriptor, encoded_line) != len(encoded_line):
                raise OSError("incomplete incident event append")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
