from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

import pytest

from tradingagents.orchestration.work_packets import (
    WORK_PACKET_SCHEMA_VERSION,
    EvidenceRef,
    WorkPacket,
    build_packet_id,
    validate_work_packet,
)

UTC = dt.timezone.utc
NOW = dt.datetime(2030, 1, 2, 15, 4, 5, tzinfo=UTC)
HISTORICAL_NOW = dt.datetime(2020, 1, 2, 15, 4, 5, tzinfo=UTC)
ALLOWED_KINDS = {
    "research_evidence",
    "research_synthesis",
    "trader_proposal",
    "risk_review",
    "portfolio_decision",
}
REQUIRED_FORBIDDEN_EFFECTS = {
    "submit_order",
    "cancel_order",
    "replace_order",
    "size_position",
    "waive_live_gate",
    "override_risk_envelope",
    "arm_live_control",
}
COMPACT_KEYS = {
    "schema_version",
    "packet_id",
    "kind",
    "created_at",
    "expires_at",
    "producer_role",
    "run_id",
    "subject",
    "evidence_refs",
    "parent_packet_ids",
    "claims",
    "assumptions",
    "recommendation",
    "confidence",
    "allowed_effects",
    "forbidden_effects",
    "analysis_only",
    "execution_authority",
    "can_submit_orders",
}


def _evidence(tmp_path: Path, *, name: str = "research.json") -> EvidenceRef:
    source = tmp_path / name
    source.write_bytes(b'{"stance":"bullish"}')
    return EvidenceRef.from_path(source)


def _packet(tmp_path: Path, **overrides) -> WorkPacket:
    values = {
        "kind": "research_synthesis",
        "producer_role": "research_manager",
        "run_id": "research-run-1",
        "subject": "NFLX",
        "evidence_refs": [_evidence(tmp_path)],
        "parent_packet_ids": [],
        "claims": ["NFLX has support near the current price"],
        "assumptions": ["regular market session"],
        "recommendation": "hold_cash",
        "confidence": 0.62,
        "allowed_effects": ["recommend_hold_cash"],
        "forbidden_effects": [],
        "expires_at": NOW + dt.timedelta(hours=2),
        "now": NOW,
    }
    values.update(overrides)
    return WorkPacket.create(**values)


def _historical_packet(tmp_path: Path) -> WorkPacket:
    return _packet(
        tmp_path,
        now=HISTORICAL_NOW,
        expires_at=HISTORICAL_NOW + dt.timedelta(hours=2),
    )


@pytest.mark.parametrize(
    "run_id",
    [
        "",
        " ",
        "run id",
        "../run",
        "run/child",
        "run\\child",
        "run\nchild",
        "a" * 129,
    ],
)
def test_build_packet_id_rejects_invalid_run_ids(run_id):
    with pytest.raises(ValueError):
        build_packet_id(run_id, "research_evidence")


def test_build_packet_id_is_deterministic_and_trims_inputs():
    first = build_packet_id(" graph-run.1 ", " research_evidence ")
    second = build_packet_id("graph-run.1", "research_evidence")

    assert first == "wp-graph-run.1-research_evidence"
    assert second == first


def test_packet_kinds_are_exactly_the_phase_one_allowlist():
    observed = {
        build_packet_id("run-1", kind).removeprefix("wp-run-1-")
        for kind in ALLOWED_KINDS
    }

    assert observed == ALLOWED_KINDS
    for kind in ("", "news", "execution", "research/evidence", " risk review "):
        with pytest.raises(ValueError):
            build_packet_id("run-1", kind)


def test_evidence_ref_hashes_exact_bytes_and_detects_mutation(tmp_path):
    source = tmp_path / "research.json"
    source.write_bytes(b'{"stance":"bullish"}')

    ref = EvidenceRef.from_path(source)

    assert ref.path == str(source)
    assert ref.sha256 == "6e6e94ebafe8527716da46dc0b5d822a3350e3330ca7759c033d59df1c343be6"
    assert ref.size_bytes == 20
    assert ref.verify() is True

    source.write_bytes(b'{"stance":"bearish"}')
    assert ref.verify() is False


def test_evidence_ref_requires_existing_regular_file(tmp_path):
    with pytest.raises(ValueError):
        EvidenceRef.from_path(tmp_path / "missing.json")
    with pytest.raises(ValueError):
        EvidenceRef.from_path(tmp_path)


def test_evidence_ref_resolves_relative_path_beneath_root(tmp_path):
    source = tmp_path / "evidence" / "research.json"
    source.parent.mkdir()
    source.write_bytes(b"evidence")
    absolute = EvidenceRef.from_path(source)
    relative = dataclasses.replace(
        absolute,
        path="evidence/research.json",
    )

    assert relative.resolve(tmp_path) == source.resolve()
    assert relative.verify(tmp_path) is True


def test_evidence_ref_accepts_absolute_path_beneath_root(tmp_path):
    ref = _evidence(tmp_path)

    assert ref.resolve(tmp_path) == Path(ref.path).resolve()
    assert ref.verify(tmp_path) is True


@pytest.mark.parametrize("stored_path", ["../outside.json", "../../escape", "/tmp/outside.json"])
def test_evidence_ref_rejects_root_escape(stored_path, tmp_path):
    ref = EvidenceRef(path=stored_path, sha256="0" * 64, size_bytes=0)

    with pytest.raises(ValueError):
        ref.resolve(tmp_path)
    assert ref.verify(tmp_path) is False


def test_valid_packet_has_stable_canonical_bytes_and_digest(tmp_path):
    packet = _packet(tmp_path)

    assert validate_work_packet(packet, now=NOW) == []
    expected = json.dumps(
        packet.compact(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert packet.canonical_json_bytes() == expected
    assert packet.payload_digest() == hashlib.sha256(expected).hexdigest()


def test_retry_with_same_inputs_and_now_is_byte_identical(tmp_path):
    ref = _evidence(tmp_path)
    values = {
        "kind": "research_evidence",
        "producer_role": "market_analyst",
        "run_id": "graph-run-99",
        "subject": "NFLX",
        "evidence_refs": [ref],
        "claims": ["price held support"],
        "assumptions": [],
        "recommendation": "request confirmation",
        "confidence": 0.55,
        "expires_at": NOW + dt.timedelta(minutes=30),
        "now": NOW,
    }

    first = WorkPacket.create(**values)
    second = WorkPacket.create(**values)

    assert first.packet_id == second.packet_id
    assert first.canonical_json_bytes() == second.canonical_json_bytes()


def test_compact_packet_has_only_bounded_handoff_and_fixed_authority_fields(tmp_path):
    packet = _packet(tmp_path)

    compact = packet.compact()

    assert set(compact) == COMPACT_KEYS
    assert compact["analysis_only"] is True
    assert compact["execution_authority"] == "none"
    assert compact["can_submit_orders"] is False
    assert "raw_transcript" not in compact
    assert len(compact["claims"]) == 1
    assert isinstance(compact["claims"], list)
    assert isinstance(packet.claims, tuple)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("producer_role", ""),
        ("producer_role", " "),
        ("subject", ""),
        ("subject", " "),
        ("recommendation", ""),
        ("recommendation", " "),
    ],
)
def test_required_packet_strings_reject_empty_values(tmp_path, field, value):
    with pytest.raises(ValueError):
        _packet(tmp_path, **{field: value})


@pytest.mark.parametrize("field", ["producer_role", "subject"])
def test_role_and_subject_are_bounded(tmp_path, field):
    with pytest.raises(ValueError, match="160 characters"):
        _packet(tmp_path, **{field: "x" * 161})


def test_work_packet_is_frozen(tmp_path):
    packet = _packet(tmp_path)

    with pytest.raises(dataclasses.FrozenInstanceError):
        packet.recommendation = "buy"  # type: ignore[misc]


@pytest.mark.parametrize(
    "confidence",
    [True, False, -0.01, 1.01, math.nan, math.inf, -math.inf],
)
def test_confidence_rejects_bool_out_of_range_nan_and_infinity(tmp_path, confidence):
    with pytest.raises(ValueError):
        _packet(tmp_path, confidence=confidence)


@pytest.mark.parametrize("confidence", ["0.5", None])
def test_confidence_rejects_non_numeric_values_with_value_error(
    tmp_path,
    confidence,
):
    with pytest.raises(ValueError, match="confidence must be an int or float"):
        _packet(tmp_path, confidence=confidence)


def test_time_contract_rejects_naive_equal_and_expired_values(tmp_path):
    with pytest.raises(ValueError, match="timezone-aware"):
        _packet(tmp_path, now=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="timezone-aware"):
        _packet(
            tmp_path,
            expires_at=(NOW + dt.timedelta(hours=1)).replace(tzinfo=None),
        )
    with pytest.raises(ValueError, match="strictly after"):
        _packet(tmp_path, expires_at=NOW)

    packet = _packet(tmp_path)
    issues = packet.validate(now=NOW + dt.timedelta(hours=3))
    assert "packet expired" in issues


@pytest.mark.parametrize("field", ["created_at", "expires_at"])
@pytest.mark.parametrize("value", ["not-a-time", "2030-01-02T15:04:05"])
def test_from_dict_rejects_malformed_or_naive_stored_timestamps(
    tmp_path,
    field,
    value,
):
    payload = _packet(tmp_path).compact()
    payload[field] = value

    with pytest.raises(ValueError):
        WorkPacket.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("claims", ["claim"] * 6),
        ("assumptions", ["assumption"] * 6),
        ("claims", ["x" * 501]),
        ("assumptions", ["x" * 501]),
    ],
)
def test_claim_and_assumption_bounds_are_enforced(tmp_path, field, value):
    with pytest.raises(ValueError):
        _packet(tmp_path, **{field: value})


def test_recommendation_and_total_packet_size_are_bounded(tmp_path):
    with pytest.raises(ValueError):
        _packet(tmp_path, recommendation="x" * 1001)

    evidence_refs = []
    for index in range(100):
        nested = tmp_path / ("evidence-" + ("x" * 80)) / f"{index:03d}.json"
        nested.parent.mkdir(exist_ok=True)
        nested.write_bytes(str(index).encode("utf-8"))
        evidence_refs.append(EvidenceRef.from_path(nested))

    with pytest.raises(ValueError, match="16 KiB"):
        _packet(tmp_path, evidence_refs=evidence_refs)


def test_from_dict_rejects_unknown_missing_and_wrong_collection_fields(tmp_path):
    packet = _packet(tmp_path)

    unknown = packet.compact()
    unknown["raw_transcript"] = "forbidden"
    with pytest.raises(ValueError):
        WorkPacket.from_dict(unknown)

    missing = packet.compact()
    missing.pop("subject")
    with pytest.raises(ValueError):
        WorkPacket.from_dict(missing)

    wrong_collection = packet.compact()
    wrong_collection["claims"] = ("not", "a", "list")
    with pytest.raises(ValueError):
        WorkPacket.from_dict(wrong_collection)

    invalid_evidence = packet.compact()
    invalid_evidence["evidence_refs"] = [{"path": "research.json"}]
    with pytest.raises(ValueError):
        WorkPacket.from_dict(invalid_evidence)


def test_from_dict_rejects_non_string_payload_keys(tmp_path):
    payload = _packet(tmp_path).compact()
    payload[1] = "not a field"

    with pytest.raises(ValueError):
        WorkPacket.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("analysis_only", False),
        ("analysis_only", 1),
        ("execution_authority", "live"),
        ("can_submit_orders", True),
        ("can_submit_orders", 0),
    ],
)
def test_from_dict_rejects_authority_overrides(tmp_path, field, value):
    payload = _packet(tmp_path).compact()
    payload[field] = value

    with pytest.raises(ValueError):
        WorkPacket.from_dict(payload)


def test_from_dict_round_trip_is_exact(tmp_path):
    packet = _packet(tmp_path)

    restored = WorkPacket.from_dict(packet.compact())

    assert restored == packet
    assert restored.canonical_json_bytes() == packet.canonical_json_bytes()


def test_from_dict_without_now_rejects_expired_historical_packet(tmp_path):
    packet = _historical_packet(tmp_path)

    with pytest.raises(ValueError, match="packet expired"):
        WorkPacket.from_dict(packet.compact())


def test_from_dict_accepts_historical_packet_with_aware_clock_inside_lifetime(
    tmp_path,
):
    packet = _historical_packet(tmp_path)

    restored = WorkPacket.from_dict(
        packet.compact(),
        now=HISTORICAL_NOW + dt.timedelta(hours=1),
    )

    assert restored.canonical_json_bytes() == packet.canonical_json_bytes()


def test_from_dict_rejects_historical_packet_with_clock_at_expiry(tmp_path):
    packet = _historical_packet(tmp_path)

    with pytest.raises(ValueError, match="packet expired"):
        WorkPacket.from_dict(
            packet.compact(),
            now=HISTORICAL_NOW + dt.timedelta(hours=2),
        )


def test_from_dict_rejects_naive_historical_validation_clock(tmp_path):
    packet = _historical_packet(tmp_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        WorkPacket.from_dict(
            packet.compact(),
            now=(HISTORICAL_NOW + dt.timedelta(hours=1)).replace(tzinfo=None),
        )


def test_from_dict_rejects_packet_id_that_does_not_match_run_and_kind(tmp_path):
    payload = _packet(tmp_path).compact()
    payload["packet_id"] = build_packet_id("another-run", "research_synthesis")

    with pytest.raises(ValueError, match="packet_id does not match"):
        WorkPacket.from_dict(payload)


def test_parent_packet_ids_reject_duplicates_self_and_unsafe_values(tmp_path):
    parent_id = build_packet_id("parent-run", "research_evidence")
    with pytest.raises(ValueError):
        _packet(tmp_path, parent_packet_ids=[parent_id, parent_id])

    packet_id = build_packet_id("research-run-1", "research_synthesis")
    with pytest.raises(ValueError):
        _packet(tmp_path, parent_packet_ids=[packet_id])

    with pytest.raises(ValueError):
        _packet(tmp_path, parent_packet_ids=["wp-../unsafe-research_evidence"])


@pytest.mark.parametrize(
    "allowed_effects",
    [
        ["submit_order"],
        ["cancel_order"],
        ["unknown_effect"],
        ["unsafe effect"],
        ["request_more_research", "request_more_research"],
    ],
)
def test_allowed_effects_reject_execution_unknown_unsafe_and_duplicate_values(
    tmp_path,
    allowed_effects,
):
    with pytest.raises(ValueError):
        _packet(tmp_path, allowed_effects=allowed_effects)


def test_effect_collections_reject_overlap(tmp_path):
    with pytest.raises(ValueError):
        _packet(
            tmp_path,
            allowed_effects=["request_more_research"],
            forbidden_effects=["request_more_research"],
        )


def test_required_forbidden_effects_are_unioned_and_sorted(tmp_path):
    packet = _packet(
        tmp_path,
        forbidden_effects=["log_incident", "cancel_order"],
    )

    assert set(packet.forbidden_effects) == REQUIRED_FORBIDDEN_EFFECTS | {
        "log_incident"
    }
    assert packet.forbidden_effects == tuple(sorted(packet.forbidden_effects))
    assert packet.allowed_effects == tuple(sorted(packet.allowed_effects))


@pytest.mark.parametrize(
    "forbidden_effects",
    [
        ["unsafe effect"],
        ["log_incident", "log_incident"],
    ],
)
def test_forbidden_effects_reject_unsafe_and_duplicate_values(
    tmp_path,
    forbidden_effects,
):
    with pytest.raises(ValueError):
        _packet(tmp_path, forbidden_effects=forbidden_effects)


@pytest.mark.parametrize("field", ["allowed_effects", "forbidden_effects"])
def test_from_dict_rejects_unsorted_effect_collections(tmp_path, field):
    packet = _packet(
        tmp_path,
        allowed_effects=["request_more_research", "downrank_confidence"],
        forbidden_effects=["log_incident"],
    )
    payload = packet.compact()
    payload[field] = list(reversed(payload[field]))

    with pytest.raises(ValueError, match=f"{field} must be sorted"):
        WorkPacket.from_dict(payload)


@pytest.mark.parametrize(
    "replacement",
    [
        {"path": " "},
        {"sha256": "A" * 64},
        {"sha256": "0" * 63},
        {"size_bytes": True},
        {"size_bytes": -1},
    ],
)
def test_evidence_reference_shape_is_strict(tmp_path, replacement):
    ref = dataclasses.replace(_evidence(tmp_path), **replacement)

    with pytest.raises(ValueError):
        _packet(tmp_path, evidence_refs=[ref])


def test_duplicate_evidence_reference_triples_reject(tmp_path):
    ref = _evidence(tmp_path)

    with pytest.raises(ValueError, match="duplicate references"):
        _packet(tmp_path, evidence_refs=[ref, ref])


def test_missing_and_mutated_evidence_have_deterministic_validation_issue(tmp_path):
    packet = _packet(tmp_path)
    source = Path(packet.evidence_refs[0].path)
    expected = ("evidence_refs[0] failed verification",)

    source.unlink()
    assert packet.validate(now=NOW) == expected

    source.write_bytes(b'{"stance":"bearish"}')
    assert packet.validate(now=NOW) == expected
    assert validate_work_packet(packet, now=NOW) == list(expected)


def test_verify_evidence_false_checks_only_reference_shape(tmp_path):
    packet = _packet(tmp_path)
    Path(packet.evidence_refs[0].path).unlink()

    assert packet.validate(now=NOW, verify_evidence=False) == ()


def test_canonical_json_uses_sorted_keys_and_compact_separators(tmp_path):
    packet = _packet(tmp_path)
    encoded = packet.canonical_json_bytes()

    assert encoded.startswith(b'{"allowed_effects":')
    assert b'": ' not in encoded
    assert b", " not in encoded
    assert encoded == json.dumps(
        packet.compact(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def test_schema_version_is_fixed_and_caller_cannot_change_it(tmp_path):
    packet = _packet(tmp_path)
    assert packet.schema_version == WORK_PACKET_SCHEMA_VERSION == 1

    payload = packet.compact()
    payload["schema_version"] = 2
    with pytest.raises(ValueError):
        WorkPacket.from_dict(payload)
