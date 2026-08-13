import datetime as dt
import json
import multiprocessing as mp
from dataclasses import replace

import pytest

from tradingagents.orchestration.incidents import (
    ALLOWED_TRANSITIONS,
    Incident,
    IncidentStage,
    IncidentStore,
    transition_incident,
)


def _incident() -> Incident:
    return Incident.open(
        incident_id="inc-nflx-rule-conflict",
        kind="policy_rule_conflict",
        subject="NFLX",
        owner_role="reliability_controller",
        now=dt.datetime(2026, 7, 18, tzinfo=dt.timezone.utc),
    )


def _record_concurrent_event(root: str, incident_id: str) -> None:
    IncidentStore(root).record(
        Incident.open(
            incident_id=incident_id,
            kind="policy_rule_conflict",
            subject="NFLX",
            owner_role="reliability_controller",
            now=dt.datetime(2026, 7, 18, tzinfo=dt.timezone.utc),
        ),
        event="opened",
    )


def test_freeze_incident_is_owned_and_actionable():
    incident = _incident()
    assert incident.stage is IncidentStage.DETECTED
    assert incident.owner_role == "reliability_controller"
    assert incident.next_action
    assert incident.retry_budget == 3
    assert incident.lease_expires_at == "2026-07-18T00:30:00+00:00"


def test_open_rejects_an_empty_owner():
    with pytest.raises(ValueError, match="owner_role must not be empty"):
        Incident.open(
            incident_id="inc-unowned",
            kind="policy_rule_conflict",
            subject="NFLX",
            owner_role=" ",
            now=dt.datetime(2026, 7, 18, tzinfo=dt.timezone.utc),
        )


def test_transition_table_accepts_every_declared_edge_and_rejects_all_others():
    for source, allowed_targets in ALLOWED_TRANSITIONS.items():
        source_incident = replace(_incident(), stage=source)
        for target in IncidentStage:
            if target in allowed_targets:
                assert transition_incident(source_incident, target).stage is target
            else:
                with pytest.raises(ValueError, match="invalid incident transition"):
                    transition_incident(source_incident, target)


def test_transition_appends_an_immutable_history_event():
    incident = _incident()
    transitioned = transition_incident(
        incident,
        IncidentStage.DIAGNOSING,
        now=dt.datetime(2026, 7, 18, 0, 1, tzinfo=dt.timezone.utc),
    )

    assert incident.stage is IncidentStage.DETECTED
    assert transitioned.stage is IncidentStage.DIAGNOSING
    assert transitioned.history[-1] == {
        "event": "transitioned",
        "from_stage": "detected",
        "to_stage": "diagnosing",
        "at": "2026-07-18T00:01:00+00:00",
    }


def test_store_writes_append_only_event_and_latest_snapshot(tmp_path):
    store = IncidentStore(tmp_path)
    incident = store.record(_incident(), event="opened")
    event_path = tmp_path / "events.jsonl"
    assert event_path.read_text().count("\n") == 1
    assert (tmp_path / incident.incident_id / "latest.json").exists()
    assert json.loads((tmp_path / "latest.json").read_text())["incident_id"] == incident.incident_id


def test_store_never_truncates_existing_events(tmp_path):
    store = IncidentStore(tmp_path)
    opened = store.record(_incident(), event="opened")
    store.record(
        transition_incident(opened, IncidentStage.DIAGNOSING),
        event="transitioned",
    )

    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [event["event"] for event in events] == ["opened", "transitioned"]


@pytest.mark.parametrize("incident_id", ["../outside", "nested/id", r"nested\\id", "", "   "])
def test_store_rejects_unsafe_incident_ids_before_any_write(tmp_path, incident_id):
    incident = Incident.open(
        incident_id=incident_id,
        kind="policy_rule_conflict",
        subject="NFLX",
        owner_role="reliability_controller",
        now=dt.datetime(2026, 7, 18, tzinfo=dt.timezone.utc),
    )

    with pytest.raises(ValueError, match="invalid incident_id"):
        IncidentStore(tmp_path).record(incident, event="opened")

    assert list(tmp_path.iterdir()) == []


def test_concurrent_records_leave_one_complete_json_line_per_event(tmp_path):
    root = tmp_path / "incidents"
    process_count = 12
    context = mp.get_context("spawn")
    processes = [
        context.Process(target=_record_concurrent_event, args=(str(root), f"inc-{index}"))
        for index in range(process_count)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
    assert len(events) == process_count
    assert {event["incident_id"] for event in events} == {
        f"inc-{index}" for index in range(process_count)
    }
