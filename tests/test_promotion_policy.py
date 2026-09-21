from decimal import Decimal
from pathlib import Path

import pytest

from tradingagents.policy.promotion import (
    SleevePromotionEvidence,
    build_promotion_state,
    evaluate_sleeve_promotion,
    write_promotion_state,
)


@pytest.fixture(autouse=True)
def _promotion_owner_authority_clock(monkeypatch):
    """Keep historical promotion fixtures off the production authority clock."""

    import datetime as _datetime

    import tradingagents.policy.promotion as promotion_module

    monkeypatch.setattr(
        promotion_module,
        "_owner_approval_authority_utc_now",
        lambda: _datetime.datetime(2026, 6, 1, 15, 10, tzinfo=_datetime.timezone.utc),
    )


def _evidence(**overrides):
    values = {
        "sleeve": "pullback-support",
        "preregistered": True,
        "ci_green": True,
        "shadow_confirmed": True,
        "benchmark_excess_return": Decimal("0.03"),
        "cost_adjusted_alpha": Decimal("0.02"),
        "recent_alpha": Decimal("0.01"),
        "capacity_usd": Decimal("500"),
        "requested_tiny_live_tranche_usd": Decimal("25"),
        "validation_report_ref": "results/validation/pullback-support.json",
        "risk_envelope_ref": "config/risk_envelope.yaml",
    }
    values.update(overrides)
    return SleevePromotionEvidence(**values)


def test_promotion_policy_builds_tiny_live_eligible_state_when_all_gates_pass():
    decision = evaluate_sleeve_promotion(
        _evidence(),
        arm_live=True,
        promoted_at="2026-06-01T15:00:00+00:00",
    )

    assert decision.passed is True
    assert decision.stage == "tiny_live_eligible"
    assert decision.live_enabled is True
    assert decision.state["benchmark_gate_passed"] is True
    assert decision.state["recent_alpha_gate_passed"] is True
    assert decision.state["risk_envelope_ref"] == "config/risk_envelope.yaml"


def test_promotion_policy_keeps_live_disabled_until_armed():
    decision = evaluate_sleeve_promotion(_evidence(), arm_live=False)

    assert decision.passed is True
    assert decision.stage == "tiny_live_eligible"
    assert decision.live_enabled is False
    assert decision.state["live_enabled"] is False


def test_promotion_policy_blocks_weak_or_low_capacity_sleeve():
    decision = evaluate_sleeve_promotion(
        _evidence(
            recent_alpha=Decimal("-0.01"),
            capacity_usd=Decimal("10"),
            requested_tiny_live_tranche_usd=Decimal("25"),
        ),
        arm_live=True,
    )

    assert decision.passed is False
    assert decision.stage == "paper_only"
    assert decision.live_enabled is False
    assert "recent_alpha_gate_passed" in decision.issues
    assert "capacity_gate_passed" in decision.issues


def test_promotion_state_writer_uses_live_gate_shape(tmp_path, monkeypatch):
    import hashlib
    import json
    from datetime import datetime
    from datetime import timezone as _tz

    from tests._owner_approval_testing import (
        build_owner_approval,
        install_isolated_owner_trust,
    )
    from tradingagents.policy.promotion import (
        _write_promotion_subject_and_source,
    )

    handle = install_isolated_owner_trust(monkeypatch, tmp_path / "owner", seed=b"promotion-policy-seed")
    decision = evaluate_sleeve_promotion(
        _evidence(),
        arm_live=True,
        promoted_at="2026-06-01T15:00:00+00:00",
    )
    moment = datetime(2026, 6, 1, 15, 10, tzinfo=_tz.utc)
    state = build_promotion_state(
        [decision], generated_at=moment.isoformat(timespec="seconds")
    )
    output_path = (tmp_path / "promotion.json").resolve()
    payload_sha256 = hashlib.sha256(
        json.dumps(state, indent=2).encode("utf-8")
    ).hexdigest()
    subject, source_binding, purpose = _write_promotion_subject_and_source(
        [decision],
        output_path=output_path,
        payload_sha256=payload_sha256,
        envelope_ref="config/risk_envelope.yaml",
        envelope_sha256="e" * 64,
    )
    approval = build_owner_approval(
        private_key_hex=handle.private_hex,
        action="live_promotion",
        issued_at=datetime(2026, 6, 1, 15, 0, tzinfo=_tz.utc),
        ttl_minutes=30,
        subject=subject,
        source_binding=source_binding,
        risk_envelope_ref="config/risk_envelope.yaml",
        risk_envelope_sha256="e" * 64,
    )
    path = write_promotion_state(
        tmp_path / "promotion.json",
        [decision],
        owner_approval=approval,
        owner_approval_envelope_ref="config/risk_envelope.yaml",
        owner_approval_envelope_sha256="e" * 64,
        now=moment,
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "1.0.0"
    assert state["schema_version"] == "1.0.0"
    assert state["sleeves"]["pullback-support"]["stage"] == "tiny_live_eligible"
    assert saved["sleeves"]["pullback-support"]["live_enabled"] is True
    assert saved["sleeves"]["pullback-support"]["validation_report_ref"]
    assert list(tmp_path.glob(".promotion.json.*.tmp")) == []


def test_write_promotion_rejects_changed_output_path_or_decision_payload(
    tmp_path, monkeypatch
):
    import hashlib
    import json
    from datetime import datetime, timedelta
    from datetime import timezone as _tz

    import pytest

    from tests._owner_approval_testing import (
        build_owner_approval,
        install_isolated_owner_trust,
    )
    from tradingagents.policy.owner_approval import OwnerApprovalError
    from tradingagents.policy.promotion import (
        _write_promotion_subject_and_source,
    )

    handle = install_isolated_owner_trust(monkeypatch, tmp_path / "owner", seed=b"promotion-policy-seed")
    now = datetime(2026, 6, 1, 15, 10, tzinfo=_tz.utc)

    def _approval_for(decisions, output_path):
        payload = build_promotion_state(decisions)
        payload_sha256 = hashlib.sha256(
            json.dumps(payload, indent=2).encode("utf-8")
        ).hexdigest()
        subject, source_binding, _purpose = _write_promotion_subject_and_source(
            [
                decision
                for decision in decisions
                if decision.stage == "tiny_live_eligible" or decision.live_enabled
            ],
            output_path=output_path.resolve(),
            payload_sha256=payload_sha256,
            envelope_ref="config/risk_envelope.yaml",
            envelope_sha256="e" * 64,
        )
        return build_owner_approval(
            private_key_hex=handle.private_hex,
            action="live_promotion",
            issued_at=now - timedelta(minutes=10),
            ttl_minutes=30,
            subject=subject,
            source_binding=source_binding,
            risk_envelope_ref="config/risk_envelope.yaml",
            risk_envelope_sha256="e" * 64,
        )

    intended_output = (tmp_path / "intended.json").resolve()

    # Changed resolved output path: approval bound to the intended path.
    decision = evaluate_sleeve_promotion(
        _evidence(), arm_live=True, promoted_at="2026-06-01T15:00:00+00:00"
    )
    approval = _approval_for([decision], intended_output)
    other_dir = tmp_path / "other"
    other_dir.mkdir()

    with pytest.raises(OwnerApprovalError):
        write_promotion_state(
            other_dir / "promotion.json",
            [decision],
            owner_approval=approval,
            owner_approval_envelope_ref="config/risk_envelope.yaml",
            owner_approval_envelope_sha256="e" * 64,
            now=now,
        )
    assert not (other_dir / "promotion.json").exists()
    assert not intended_output.exists()


@pytest.mark.parametrize("tamper_consumed_sidecar", (False, True))
def test_write_promotion_prepare_crash_recovers_once_after_approval_expiry(
    tmp_path, monkeypatch, tamper_consumed_sidecar
):
    """A consumed promotion write resumes its exact prepared output only once.

    The failure is deliberately injected after the durable owner-consumption
    ledger record.  Retrying after the signed artifact expires may finish that
    exact write, but a changed decision cannot inherit the consumed authority.
    """

    import hashlib
    import json
    from datetime import datetime, timedelta
    from datetime import timezone as _tz

    import pytest

    import tradingagents.policy.promotion as promotion_module
    from tests._owner_approval_testing import (
        build_owner_approval,
        install_isolated_owner_trust,
    )
    from tradingagents.policy.owner_approval import (
        OwnerApprovalError,
        owner_approval_prepare_path,
    )
    from tradingagents.policy.promotion import _write_promotion_subject_and_source

    handle = install_isolated_owner_trust(
        monkeypatch, tmp_path / "owner", seed=b"promotion-crash-safe-seed"
    )
    moment = datetime(2026, 6, 1, 15, 10, tzinfo=_tz.utc)
    late = moment + timedelta(minutes=31)
    state_path = (tmp_path / "promotion.json").resolve()
    decision = evaluate_sleeve_promotion(
        _evidence(), arm_live=True, promoted_at="2026-06-01T15:00:00+00:00"
    )
    payload = build_promotion_state(
        [decision], generated_at=moment.isoformat(timespec="seconds")
    )
    payload_sha256 = hashlib.sha256(json.dumps(payload, indent=2).encode("utf-8")).hexdigest()
    subject, source_binding, _purpose = _write_promotion_subject_and_source(
        [decision],
        output_path=state_path,
        payload_sha256=payload_sha256,
        envelope_ref="config/risk_envelope.yaml",
        envelope_sha256="e" * 64,
    )
    approval = build_owner_approval(
        private_key_hex=handle.private_hex,
        action="live_promotion",
        issued_at=moment - timedelta(minutes=10),
        ttl_minutes=30,
        subject=subject,
        source_binding=source_binding,
        risk_envelope_ref="config/risk_envelope.yaml",
        risk_envelope_sha256="e" * 64,
    )
    real_atomic_write = promotion_module.atomic_write_text
    writes = 0

    def crash_after_consumption(path, text):
        nonlocal writes
        writes += 1
        if writes == 1:
            raise OSError("injected promotion output crash")
        return real_atomic_write(path, text)

    monkeypatch.setattr(promotion_module, "atomic_write_text", crash_after_consumption)
    with pytest.raises(OSError, match="injected promotion output crash"):
        write_promotion_state(
            state_path,
            [decision],
            owner_approval=approval,
            owner_approval_envelope_ref="config/risk_envelope.yaml",
            owner_approval_envelope_sha256="e" * 64,
            now=moment,
        )

    prepare_path = owner_approval_prepare_path(state_path)
    assert prepare_path.exists()
    assert not state_path.exists()
    records = [
        json.loads(line)
        for line in handle.ledger.read_text().splitlines()
        if line.strip()
    ]
    assert [record["approval_id"] for record in records].count(approval["approval_id"]) == 1

    if tamper_consumed_sidecar:
        # This is a real writer crash window: the output write failed only
        # after the exact generic prepare and ledger consumption existed.
        # Altering the retained sidecar must refuse before touching output.
        raw = json.loads(prepare_path.read_text(encoding="utf-8"))
        raw["transaction"]["serialized_output"] = "{}"
        prepare_path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(OwnerApprovalError, match="prepare|transaction|subject|expired"):
            write_promotion_state(
                state_path,
                [decision],
                owner_approval=approval,
                owner_approval_envelope_ref="config/risk_envelope.yaml",
                owner_approval_envelope_sha256="e" * 64,
                now=late,
            )
        assert not state_path.exists()
        assert [
            record for record in records if record["approval_id"] == approval["approval_id"]
        ] == [
            record
            for record in (
                json.loads(line)
                for line in handle.ledger.read_text().splitlines()
                if line.strip()
            )
            if record["approval_id"] == approval["approval_id"]
        ]
        return

    changed = evaluate_sleeve_promotion(
        _evidence(requested_tiny_live_tranche_usd=Decimal("30")),
        arm_live=True,
        promoted_at="2026-06-01T15:00:00+00:00",
    )
    with pytest.raises(ValueError, match="does not match"):
        write_promotion_state(
            state_path,
            [changed],
            owner_approval=approval,
            owner_approval_envelope_ref="config/risk_envelope.yaml",
            owner_approval_envelope_sha256="e" * 64,
            now=late,
        )
    assert not state_path.exists()

    write_promotion_state(
        state_path,
        [decision],
        owner_approval=approval,
        owner_approval_envelope_ref="config/risk_envelope.yaml",
        owner_approval_envelope_sha256="e" * 64,
        now=late,
    )
    assert state_path.exists()
    assert not prepare_path.exists()
    records_after = [
        json.loads(line)
        for line in handle.ledger.read_text().splitlines()
        if line.strip()
    ]
    assert [record["approval_id"] for record in records_after].count(approval["approval_id"]) == 1


def test_prepared_promotion_write_without_ledger_consumption_cannot_write(
    tmp_path, monkeypatch
):
    """A generic prepare record alone remains inert after a crash."""

    import hashlib
    import json
    from datetime import datetime, timedelta
    from datetime import timezone as _tz

    import pytest

    import tradingagents.policy.promotion as promotion_module
    from tests._owner_approval_testing import (
        build_owner_approval,
        install_isolated_owner_trust,
    )
    from tradingagents.policy.owner_approval import (
        OwnerApprovalError,
        owner_approval_prepare_path,
        transaction_binding_sha256,
        write_owner_approval_prepare,
    )
    from tradingagents.policy.promotion import _write_promotion_subject_and_source

    handle = install_isolated_owner_trust(
        monkeypatch, tmp_path / "owner", seed=b"promotion-prepared-only-seed"
    )
    moment = datetime(2026, 6, 1, 15, 10, tzinfo=_tz.utc)
    state_path = (tmp_path / "promotion.json").resolve()
    decision = evaluate_sleeve_promotion(
        _evidence(), arm_live=True, promoted_at="2026-06-01T15:00:00+00:00"
    )
    serialized = json.dumps(
        build_promotion_state([decision], generated_at=moment.isoformat(timespec="seconds")),
        indent=2,
    )
    payload_sha256 = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    subject, source_binding, purpose = _write_promotion_subject_and_source(
        [decision],
        output_path=state_path,
        payload_sha256=payload_sha256,
        envelope_ref="config/risk_envelope.yaml",
        envelope_sha256="e" * 64,
    )
    approval = build_owner_approval(
        private_key_hex=handle.private_hex,
        action="live_promotion",
        issued_at=moment - timedelta(minutes=10),
        ttl_minutes=30,
        subject=subject,
        source_binding=source_binding,
        risk_envelope_ref="config/risk_envelope.yaml",
        risk_envelope_sha256="e" * 64,
    )
    recovery_identity = {
        "operation": "promotion_state_write",
        "output_path": str(state_path),
        "risk_envelope_ref": "config/risk_envelope.yaml",
        "risk_envelope_sha256": "e" * 64,
        "canonical_before_sha256": hashlib.sha256(b"").hexdigest(),
        "canonical_before_kind": "absent",
        "gated_decisions": [
            {
                "sleeve": decision.sleeve,
                "state_sha256": promotion_module._decision_state_sha256(decision),
                "stage": decision.stage,
                "live_enabled": decision.live_enabled,
            }
        ],
    }
    binding = transaction_binding_sha256(
        approval_id=approval["approval_id"],
        action="live_promotion",
        purpose=purpose,
        subject=subject,
        risk_envelope_ref="config/risk_envelope.yaml",
        risk_envelope_sha256="e" * 64,
    )
    write_owner_approval_prepare(
        owner_approval_prepare_path(state_path),
        approval_id=approval["approval_id"],
        action="live_promotion",
        purpose=purpose,
        transaction_binding_sha256=binding,
        transaction={
            "operation": "promotion_state_write",
            "subject": subject,
            "source_binding": source_binding,
            "risk_envelope_ref": "config/risk_envelope.yaml",
            "risk_envelope_sha256": "e" * 64,
            "canonical_before_sha256": hashlib.sha256(b"").hexdigest(),
            "canonical_before_kind": "absent",
            "canonical_after_sha256": payload_sha256,
            "output_path": str(state_path),
            "serialized_output": serialized,
            "recovery_identity": recovery_identity,
        },
        now=moment,
    )

    with pytest.raises(OwnerApprovalError, match="no exact owner approval consumption"):
        write_promotion_state(
            state_path,
            [decision],
            owner_approval=approval,
            owner_approval_envelope_ref="config/risk_envelope.yaml",
            owner_approval_envelope_sha256="e" * 64,
            now=moment,
        )
    assert not state_path.exists()


def test_write_promotion_historical_evidence_clock_cannot_revive_expired_owner_approval(
    tmp_path, monkeypatch
):
    """A public output timestamp cannot become the authority TTL clock."""

    import hashlib
    import json
    from datetime import datetime, timedelta
    from datetime import timezone as _tz

    import tradingagents.policy.promotion as promotion_module
    from tests._owner_approval_testing import (
        build_owner_approval,
        install_isolated_owner_trust,
    )
    from tradingagents.policy.owner_approval import (
        OwnerApprovalError,
        owner_approval_has_consumption,
    )
    from tradingagents.policy.promotion import _write_promotion_subject_and_source

    handle = install_isolated_owner_trust(
        monkeypatch, tmp_path / "owner", seed=b"promotion-authority-clock"
    )
    evidence_now = datetime(2026, 6, 1, 15, 10, tzinfo=_tz.utc)
    authority_now = evidence_now + timedelta(minutes=31)
    # The seam is deliberately private; the public ``now`` below must remain
    # evidence/output time. ``raising=False`` makes this a genuine RED test
    # against the prior implementation, which had no seam and ignored it.
    monkeypatch.setattr(
        promotion_module,
        "_owner_approval_authority_utc_now",
        lambda: authority_now,
        raising=False,
    )
    state_path = (tmp_path / "promotion.json").resolve()
    decision = evaluate_sleeve_promotion(
        _evidence(), arm_live=True, promoted_at="2026-06-01T15:00:00+00:00"
    )
    serialized = json.dumps(
        build_promotion_state(
            [decision], generated_at=evidence_now.isoformat(timespec="seconds")
        ),
        indent=2,
    )
    subject, source_binding, purpose = _write_promotion_subject_and_source(
        [decision],
        output_path=state_path,
        payload_sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        envelope_ref="config/risk_envelope.yaml",
        envelope_sha256="e" * 64,
    )
    approval = build_owner_approval(
        private_key_hex=handle.private_hex,
        action="live_promotion",
        issued_at=evidence_now - timedelta(minutes=10),
        ttl_minutes=30,
        subject=subject,
        source_binding=source_binding,
        risk_envelope_ref="config/risk_envelope.yaml",
        risk_envelope_sha256="e" * 64,
    )

    with pytest.raises(OwnerApprovalError, match="expired"):
        write_promotion_state(
            state_path,
            [decision],
            owner_approval=approval,
            owner_approval_envelope_ref="config/risk_envelope.yaml",
            owner_approval_envelope_sha256="e" * 64,
            now=evidence_now,
        )

    assert not state_path.exists()
    assert not owner_approval_has_consumption(approval["approval_id"])


def test_gated_promotion_writer_serializes_against_paper_writer(
    tmp_path, monkeypatch
):
    """A paper-only write cannot overlap a gated prepare lifecycle."""

    import threading

    import tradingagents.policy.promotion as promotion_module

    state_path = tmp_path / "promotion.json"
    gated_decision = evaluate_sleeve_promotion(
        _evidence(), arm_live=True, promoted_at="2026-06-01T15:00:00+00:00"
    )
    paper_decision = evaluate_sleeve_promotion(
        _evidence(ci_green=False),
        arm_live=False,
        promoted_at="2026-06-01T15:00:00+00:00",
    )
    assert paper_decision.stage == "paper_only"
    first_inside = threading.Event()
    release_first = threading.Event()
    second_ready = threading.Event()
    guard = threading.Lock()
    active = 0
    maximum_active = 0
    calls = 0
    errors: list[BaseException] = []

    def fake_unlocked(path, decisions, **_kwargs):
        nonlocal active, maximum_active, calls
        with guard:
            active += 1
            calls += 1
            maximum_active = max(maximum_active, active)
            ordinal = calls
        try:
            if ordinal == 1:
                first_inside.set()
                assert release_first.wait(timeout=5)
            return Path(path)
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(
        promotion_module,
        "_write_promotion_state_unlocked",
        fake_unlocked,
    )

    def invoke(decision, *, ready: threading.Event | None = None):
        if ready is not None:
            ready.set()
        try:
            write_promotion_state(state_path, [decision])
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=invoke, args=(gated_decision,))
    second = threading.Thread(
        target=invoke,
        args=(paper_decision,),
        kwargs={"ready": second_ready},
    )
    first.start()
    assert first_inside.wait(timeout=5)
    second.start()
    assert second_ready.wait(timeout=5)
    with guard:
        assert calls == 1
        assert maximum_active == 1
    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert calls == 2
    assert maximum_active == 1
