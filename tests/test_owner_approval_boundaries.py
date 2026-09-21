"""Owner-approval boundary coverage.

These tests are the direct security coverage for privileged transitions.
Canonical trust paths are external to the checkout; every test redirects
ONLY the canonical resolver functions into a temp directory with
``monkeypatch`` and signs genuine Ed25519 artifacts.  No production API
accepts caller-selected anchor, ledger, repo root, or policy digest.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from tradingagents.brokers.alpaca_supervisor import HourlySupervisorAction
from tradingagents.policy import live_gate as live_gate_module
from tradingagents.policy.live_control import _commitment_id
from tradingagents.policy.live_gate import evaluate_go_live_guard
from tradingagents.policy.owner_approval import (
    OwnerApprovalError,
    canonical_owner_consumption_ledger_path,
    canonical_owner_trust_anchor_path,
    consume_owner_approval,
    default_policy_fingerprint,
    exact_expired_owner_approval_recovery,
    finalize_owner_approval_prepare,
    owner_approval_prepare_matches,
    owner_approval_prepare_path,
    owner_prepare_has_exact_consumption,
    prepared_transaction_binding_sha256,
    prepared_transaction_sha256,
    read_owner_approval_prepare,
    require_prior_consumption_for_commitment_recovery,
    transaction_binding_sha256,
    verify_owner_approval_structure,
    write_owner_approval_prepare,
)

NOW = datetime.datetime(2026, 6, 3, 15, 0, tzinfo=datetime.timezone.utc)
LIVE_PROMOTION = "live_promotion"
INTENT_A = "a" * 64
PAYLOAD_SHA = "b" * 64
RATE_SHA = "c" * 64


@pytest.fixture()
def trust(tmp_path, monkeypatch):
    """Redirect canonical resolvers into this test's temp directory."""

    from tests._owner_approval_testing import install_isolated_owner_trust

    handle = install_isolated_owner_trust(monkeypatch, tmp_path / "owner-trust", seed=b"owner-boundaries-seed")
    from tradingagents.policy import owner_approval as owner_module

    monkeypatch.setattr(
        owner_module,
        "_owner_approval_authority_utc_now",
        lambda: NOW,
    )
    return handle


def _inputs(tmp_path):
    envelope = tmp_path / "risk_envelope.yaml"
    envelope.write_text(
        "\n".join(
            [
                "account_max_capital_at_risk_usd: 250.00",
                "per_name_cap_usd: 50.00",
                "per_sector_cap_pct: 0.20",
                "aggregate_beta_cap: 1.25",
                "daily_loss_halt_usd: 25.00",
                "max_drawdown_halt_pct: 0.05",
                "tiny_live_tranche_usd: 25.00",
                "tiny_live_max_loss_usd: 5.00",
                "new_sleeve_auto_promote: false",
                "alert_email: ops@example.com",
                "live_budget_mode: autonomous_with_caps",
            ]
        ),
        encoding="utf-8",
    )
    promotion = tmp_path / "promotion.json"
    promotion.write_text(
        json.dumps({"sleeves": {"pullback-support": _eligible_record()}}),
        encoding="utf-8",
    )
    control = tmp_path / "live_control.json"
    control.write_text(
        json.dumps(
            {
                "frozen": False,
                "reason": "boundary fixture",
                "dead_man_expires_at": "2026-06-03T16:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return envelope, promotion, control


def _eligible_record():
    return {
        "stage": "tiny_live_eligible",
        "live_enabled": True,
        "preregistered": True,
        "ci_green": True,
        "shadow_confirmed": True,
        "benchmark_gate_passed": True,
        "cost_gate_passed": True,
        "recent_alpha_gate_passed": True,
        "capacity_gate_passed": True,
        "validation_report_ref": "results/validation/pullback-support.json",
        "risk_envelope_ref": "config/risk_envelope.yaml",
        "source": {
            "kind": "paper_tournament",
            "tournament_id": "paper-tournament-boundary",
            "report_generated_at": "2026-05-30T00:00:00+00:00",
            "candidate_reason": "positive paper strategy",
        },
        "evidence_metrics": {
            "total_return": "311.36",
            "total_return_pct": "3.11",
            "max_drawdown_pct": "-1.91",
            "win_rate_pct": "85.71",
            "tracked_days": 11,
        },
    }


def _action(**overrides):
    values = {
        "action": "buy",
        "symbol": "MSFT",
        "notional": Decimal("20.00"),
        "limit_price": Decimal("410.00"),
        "side": "buy",
        "order_type": "limit",
        "account": "live",
        "execution_mode": "tiny_live",
        "sleeve": "pullback-support",
        "decision_id": "decision-boundary-1",
    }
    values.update(overrides)
    return HourlySupervisorAction(**values)


def _subject(action, *, client_order_id=None, intent_full_sha256=None, order_payload_sha256=None):
    subject = {
        "kind": "live_order_submit",
        "symbol": str(action.symbol).upper(),
        "side": str(action.side).lower(),
        "order_type": str(action.order_type).lower(),
        "notional_usd": str(action.notional),
        "limit_price": str(action.limit_price),
        "client_order_id": str(client_order_id or ""),
        "decision_id": str(action.decision_id),
    }
    if intent_full_sha256 is not None:
        subject["intent_full_sha256"] = intent_full_sha256
    if order_payload_sha256 is not None:
        subject["order_payload_sha256"] = order_payload_sha256
    return subject


def _sign(trust, action, *, envelope_path, issued_at=NOW, fingerprint=None, mutate=None,
          client_order_id=None, intent_full_sha256=None, order_payload_sha256=None):
    from tests._owner_approval_testing import build_owner_approval

    artifact = build_owner_approval(
        private_key_hex=trust.private_hex,
        action=LIVE_PROMOTION,
        issued_at=issued_at,
        ttl_minutes=30,
        subject=_subject(
            action,
            client_order_id=client_order_id,
            intent_full_sha256=intent_full_sha256,
            order_payload_sha256=order_payload_sha256,
        ),
        source_binding={"guard": "unified_go_live_guard"},
        policy_fingerprint_sha256=(
            fingerprint if fingerprint is not None else default_policy_fingerprint()
        ),
        risk_envelope_ref=str(envelope_path),
        risk_envelope_sha256=hashlib.sha256(envelope_path.read_bytes()).hexdigest(),
    )
    if mutate:
        for key, value in mutate.items():
            if value is KeyError:
                artifact.pop(key, None)
            else:
                artifact[key] = value
    return artifact


def _gate(actions, approval, *, envelope_path, promotion_path, control_path,
          commitment=None, intent_full=None, payload_sha=None, client_order_id=None,
          now=NOW, expansion_approval="auto", trust=None):
    if expansion_approval == "auto":
        from tests._owner_approval_testing import (
            build_risk_envelope_expansion_approval,
        )

        expansion_approval = build_risk_envelope_expansion_approval(
            trust.private_hex,
            ref=str(envelope_path),
            sha256=hashlib.sha256(envelope_path.read_bytes()).hexdigest(),
            issued_at=now,
        )
    return evaluate_go_live_guard(
        actions,
        risk_envelope_path=envelope_path,
        promotion_state_path=promotion_path,
        control_state_path=control_path,
        live_buying_power=Decimal("100.00"),
        now=now,
        owner_approval=approval,
        risk_envelope_expansion_approval=expansion_approval,
        normal_live_commitment=commitment,
        normal_live_intent_full_sha256=intent_full,
        normal_live_order_payload_sha256=payload_sha,
        normal_live_client_order_id=client_order_id,
    )


def _ledger_lines(trust):
    path = trust.ledger
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _direct_owner_prepare_fixture(tmp_path, trust, *, output_name="prepared-output.json"):
    """Build one complete, recovery-addressable prepare transaction."""

    envelope, promotion, control = _inputs(tmp_path)
    action = _action()
    client_order_id = "order-exact-prepare"
    subject = _subject(
        action,
        client_order_id=client_order_id,
        intent_full_sha256=INTENT_A,
        order_payload_sha256=PAYLOAD_SHA,
    )
    source_binding = {"guard": "unified_go_live_guard"}
    approval = _sign(
        trust,
        action,
        envelope_path=envelope,
        client_order_id=client_order_id,
        intent_full_sha256=INTENT_A,
        order_payload_sha256=PAYLOAD_SHA,
    )
    purpose = f"live_order:{subject['decision_id']}:{client_order_id}"
    risk_sha256 = hashlib.sha256(envelope.read_bytes()).hexdigest()
    binding = transaction_binding_sha256(
        approval_id=approval["approval_id"],
        action=approval["action"],
        purpose=purpose,
        subject=subject,
        risk_envelope_ref=str(envelope),
        risk_envelope_sha256=risk_sha256,
    )
    output_path = tmp_path / output_name
    recovery_identity = {
        "operation": "owner_boundary_prepare_recovery",
        "subject": subject,
        "source_binding": source_binding,
        "risk_envelope_ref": str(envelope),
        "risk_envelope_sha256": risk_sha256,
        "output_path": str(output_path),
        "canonical_before_sha256": "d" * 64,
        "canonical_after_sha256": "e" * 64,
    }
    transaction = {
        **recovery_identity,
        "recovery_identity": recovery_identity,
        "approval_artifact": dict(approval),
    }
    return {
        "action": action,
        "approval": approval,
        "binding": binding,
        "control": control,
        "envelope": envelope,
        "prepare_path": owner_approval_prepare_path(output_path),
        "promotion": promotion,
        "purpose": purpose,
        "recovery_identity": recovery_identity,
        "source_binding": source_binding,
        "subject": subject,
        "transaction": transaction,
    }


def test_canonical_resolvers_are_external_and_have_expected_shape():
    """Shape/location assertions only: the resolvers must point at the
    account-level external config/state roots (outside any checkout).  These
    are pure path computations — no filesystem reads, so the suite stays
    hermetic regardless of whether a real anchor exists on this machine."""

    anchor = Path(canonical_owner_trust_anchor_path())
    ledger = Path(canonical_owner_consumption_ledger_path())
    from tradingagents.policy.owner_approval import (
        canonical_risk_envelope_authorization_path,
    )

    authorization = Path(canonical_risk_envelope_authorization_path())
    assert anchor.is_absolute()
    assert ".config" in anchor.parts and "tradingagents" in anchor.parts
    assert "owner-approval" in anchor.parts
    assert ".local" in ledger.parts and "state" in ledger.parts
    assert "tradingagents" in ledger.parts
    assert ".local" in authorization.parts and "state" in authorization.parts
    assert "tradingagents" in authorization.parts


def test_missing_canonical_anchor_refuses_before_any_state_io(tmp_path, monkeypatch, trust):
    monkeypatch.setattr(
        "tradingagents.policy.owner_approval.canonical_owner_trust_anchor_path",
        lambda: tmp_path / "absent-anchor.hex",
    )
    envelope, promotion, control = _inputs(tmp_path)
    reached = []
    monkeypatch.setattr(
        live_gate_module,
        "load_risk_envelope",
        lambda *_a, **_k: reached.append("envelope") or (None, []),
    )
    result = _gate([_action()], None, envelope_path=envelope,
                   promotion_path=promotion, control_path=control, trust=trust)
    assert result.allowed is False
    assert result.checks["owner_approval"] is False
    assert any("owner approval" in i.reason for i in result.issues)
    assert reached == []


def test_malformed_old_and_mismatched_artifacts_deny_before_state_io(
    tmp_path, monkeypatch, trust
):
    envelope, promotion, control = _inputs(tmp_path)
    action = _action()
    cases = {
        "malformed_json": "{ not json",
        "old_schema": {"schema_version": 0},
        "missing_signature": {},
    }
    for label, artifact in cases.items():
        reached: list[str] = []

        def _spy(*_a, _reached=reached, **_k):
            _reached.append("envelope")
            return None, []

        monkeypatch.setattr(live_gate_module, "load_risk_envelope", _spy)
        result = _gate([action], artifact, envelope_path=envelope,
                       promotion_path=promotion, control_path=control, trust=trust)
        assert result.allowed is False, label
        assert result.checks["owner_approval"] is False, label
        assert reached == [], label

    # A structurally valid artifact whose subject was forged after signing.
    good = _sign(trust, action, envelope_path=envelope)
    forged = {**good, "subject": {**good["subject"], "decision_id": "forged"}}
    reached: list[str] = []
    monkeypatch.setattr(
        live_gate_module,
        "load_risk_envelope",
        lambda *_a, **_k: reached.append("envelope") or (None, []),
    )
    result = _gate([action], forged, envelope_path=envelope,
                   promotion_path=promotion, control_path=control, trust=trust)
    assert result.allowed is False
    assert reached == []


def test_changed_checkout_policy_rejects(tmp_path, monkeypatch, trust):
    envelope, promotion, control = _inputs(tmp_path)
    action = _action()
    stale = _sign(trust, action, envelope_path=envelope, fingerprint="f" * 64)
    reached = []
    monkeypatch.setattr(
        live_gate_module,
        "load_risk_envelope",
        lambda *_a, **_k: reached.append("envelope") or (None, []),
    )
    result = _gate([action], stale, envelope_path=envelope,
                   promotion_path=promotion, control_path=control, trust=trust)
    assert result.allowed is False
    assert any("policy" in i.reason.lower() for i in result.issues)


def test_expired_artifact_denies(tmp_path, trust):
    envelope, promotion, control = _inputs(tmp_path)
    action = _action()
    expired = _sign(
        trust,
        action,
        envelope_path=envelope,
        issued_at=NOW - datetime.timedelta(minutes=45),
    )
    result = _gate([action], expired, envelope_path=envelope,
                   promotion_path=promotion, control_path=control, trust=trust)
    assert result.allowed is False
    assert any("expired" in i.reason for i in result.issues)


def test_live_gate_is_pure_evaluation_and_does_not_consume_live_approval(
    tmp_path, trust
):
    envelope, promotion, control = _inputs(tmp_path)
    action = _action()
    approval = _sign(trust, action, envelope_path=envelope)

    first = _gate([action], approval, envelope_path=envelope,
                  promotion_path=promotion, control_path=control, trust=trust)
    assert first.allowed is True, [i.reason for i in first.issues]
    lines = _ledger_lines(trust)
    # The guard is fully observational until it receives the exact durable
    # commitment candidate; it cannot consume or authorize any transition.
    assert lines == []

    replay = _gate([action], approval, envelope_path=envelope,
                   promotion_path=promotion, control_path=control, trust=trust)
    assert replay.allowed is True
    assert _ledger_lines(trust) == []


def test_normal_live_same_economics_different_identity_denies(tmp_path, trust):
    envelope, promotion, control = _inputs(tmp_path)
    action = _action()
    approval = _sign(
        trust,
        action,
        envelope_path=envelope,
        client_order_id="order-AAA",
        intent_full_sha256=INTENT_A,
        order_payload_sha256=PAYLOAD_SHA,
    )

    def gate_as(client_order_id, intent_full):
        return _gate(
            [action],
            approval,
            envelope_path=envelope,
            promotion_path=promotion,
            control_path=control,
            intent_full=intent_full,
            payload_sha=PAYLOAD_SHA,
            client_order_id=client_order_id,
            trust=trust,
        )

    allowed = gate_as("order-AAA", INTENT_A)
    assert allowed.allowed is True
    assert _ledger_lines(trust) == []

    # Same economics, different client order id: the artifact signed for AAA
    # cannot authorize BBB.
    denied_b = gate_as("order-BBB", INTENT_A)
    assert denied_b.allowed is False
    assert any("subject" in i.reason for i in denied_b.issues)

    # Same economics, different intent hash: equally denied.
    denied_intent = gate_as("order-AAA", "9" * 64)
    assert denied_intent.allowed is False
    assert any("subject" in i.reason for i in denied_intent.issues)


def test_guard_only_replay_without_durable_prepare_never_burns_live_approval(
    tmp_path, trust
):
    envelope, promotion, control = _inputs(tmp_path)
    action = _action()
    approval = _sign(
        trust,
        action,
        envelope_path=envelope,
        client_order_id="order-crash",
        intent_full_sha256=INTENT_A,
        order_payload_sha256=PAYLOAD_SHA,
    )

    first = _gate(
        [action],
        approval,
        envelope_path=envelope,
        promotion_path=promotion,
        control_path=control,
        intent_full=INTENT_A,
        payload_sha=PAYLOAD_SHA,
        client_order_id="order-crash",
        trust=trust,
    )
    assert first.allowed is True
    # A guard-only evaluation is not a transaction commit.  It leaves the
    # supplied live-order approval untouched instead of creating a stranded,
    # unrecoverable ledger record.
    assert all(
        record["approval_id"] != approval["approval_id"]
        for record in _ledger_lines(trust)
    )

    retry = _gate(
        [action],
        approval,
        envelope_path=envelope,
        promotion_path=promotion,
        control_path=control,
        intent_full=INTENT_A,
        payload_sha=PAYLOAD_SHA,
        client_order_id="order-crash",
        trust=trust,
    )
    assert retry.allowed is True
    assert all(
        record["approval_id"] != approval["approval_id"]
        for record in _ledger_lines(trust)
    )


def test_exact_prepared_consumption_recovers_only_matching_transaction(
    tmp_path, monkeypatch, trust
):
    fixture = _direct_owner_prepare_fixture(tmp_path, trust)
    approval = fixture["approval"]
    transaction = fixture["transaction"]
    strict_binding = write_owner_approval_prepare(
        fixture["prepare_path"],
        approval_id=approval["approval_id"],
        action=approval["action"],
        purpose=fixture["purpose"],
        transaction_binding_sha256=fixture["binding"],
        transaction=transaction,
        now=NOW,
    )
    assert strict_binding == prepared_transaction_binding_sha256(
        transaction_binding_sha256=fixture["binding"],
        transaction_sha256=prepared_transaction_sha256(transaction),
    )
    consume_owner_approval(
        approval_id=approval["approval_id"],
        action=approval["action"],
        purpose=fixture["purpose"],
        transaction_binding_sha256=fixture["binding"],
        prepared_transaction_binding_sha256=strict_binding,
        now=NOW,
    )
    assert owner_approval_prepare_matches(
        fixture["prepare_path"], transaction=transaction
    ) is not None
    assert owner_prepare_has_exact_consumption(fixture["prepare_path"])

    # An exact, ledger-proven recovery may inspect the original artifact after
    # its TTL, but the ordinary verifier and ordinary gate still reject it.
    expired_at = NOW + datetime.timedelta(minutes=31)
    with exact_expired_owner_approval_recovery(
        fixture["prepare_path"], recovery_identity=fixture["recovery_identity"]
    ):
        recovered = verify_owner_approval_structure(
            approval=approval,
            expected_action=approval["action"],
            subject=fixture["subject"],
            source_binding=fixture["source_binding"],
            now=expired_at,
            purpose=fixture["purpose"],
        )
    assert recovered["approval_id"] == approval["approval_id"]
    with pytest.raises(OwnerApprovalError, match="expired"):
        verify_owner_approval_structure(
            approval=approval,
            expected_action=approval["action"],
            subject=fixture["subject"],
            source_binding=fixture["source_binding"],
            now=expired_at,
            purpose=fixture["purpose"],
        )
    monkeypatch.setattr(
        live_gate_module,
        "_owner_approval_authority_utc_now",
        lambda: expired_at,
    )
    ordinary_gate = _gate(
        [fixture["action"]],
        approval,
        envelope_path=fixture["envelope"],
        promotion_path=fixture["promotion"],
        control_path=fixture["control"],
        intent_full=INTENT_A,
        payload_sha=PAYLOAD_SHA,
        client_order_id="order-exact-prepare",
        now=expired_at,
        trust=trust,
    )
    assert ordinary_gate.allowed is False
    assert any("expired" in issue.reason for issue in ordinary_gate.issues)

    # A changed recovery identity and no durable prepare both fail closed.
    with (
        pytest.raises(OwnerApprovalError, match="requires an exact"),
        exact_expired_owner_approval_recovery(
            fixture["prepare_path"],
            recovery_identity={
                **fixture["recovery_identity"],
                "output_path": str(tmp_path / "other-output.json"),
            },
        ),
    ):
        pass
    with (
        pytest.raises(OwnerApprovalError, match="requires an exact"),
        exact_expired_owner_approval_recovery(
            tmp_path / "absent.owner-approval-prepare",
            recovery_identity=fixture["recovery_identity"],
        ),
    ):
        pass

    # The canonical ledger remains exactly one record for this approval.
    exact_records = [
        record
        for record in _ledger_lines(trust)
        if record["approval_id"] == approval["approval_id"]
    ]
    assert len(exact_records) == 1
    assert exact_records[0]["prepared_transaction_binding_sha256"] == strict_binding
    with pytest.raises(OwnerApprovalError, match="already used"):
        consume_owner_approval(
            approval_id=approval["approval_id"],
            action=approval["action"],
            purpose=fixture["purpose"],
            transaction_binding_sha256=fixture["binding"],
            prepared_transaction_binding_sha256=strict_binding,
            now=NOW + datetime.timedelta(minutes=1),
        )


def test_exact_prepare_idempotence_ignores_only_prepared_at(tmp_path, trust):
    fixture = _direct_owner_prepare_fixture(tmp_path, trust)
    approval = fixture["approval"]
    strict_binding = write_owner_approval_prepare(
        fixture["prepare_path"],
        approval_id=approval["approval_id"],
        action=approval["action"],
        purpose=fixture["purpose"],
        transaction_binding_sha256=fixture["binding"],
        transaction=fixture["transaction"],
        now=NOW,
    )
    # A crash before consumption can retry the same transaction at a later
    # clock value.  ``prepared_at`` is observability, not authority.
    assert write_owner_approval_prepare(
        fixture["prepare_path"],
        approval_id=approval["approval_id"],
        action=approval["action"],
        purpose=fixture["purpose"],
        transaction_binding_sha256=fixture["binding"],
        transaction=fixture["transaction"],
        now=NOW + datetime.timedelta(minutes=1),
    ) == strict_binding
    assert _ledger_lines(trust) == []
    with pytest.raises(OwnerApprovalError, match="different transaction"):
        write_owner_approval_prepare(
            fixture["prepare_path"],
            approval_id=approval["approval_id"],
            action=approval["action"],
            purpose=fixture["purpose"],
            transaction_binding_sha256=fixture["binding"],
            transaction={
                **fixture["transaction"],
                "output_path": str(tmp_path / "changed-output.json"),
            },
            now=NOW + datetime.timedelta(minutes=1),
        )
    consume_owner_approval(
        approval_id=approval["approval_id"],
        action=approval["action"],
        purpose=fixture["purpose"],
        transaction_binding_sha256=fixture["binding"],
        prepared_transaction_binding_sha256=strict_binding,
        now=NOW + datetime.timedelta(minutes=1),
    )
    finalize_owner_approval_prepare(fixture["prepare_path"])
    assert not fixture["prepare_path"].exists()
    assert len(_ledger_lines(trust)) == 1


def test_distinct_generic_prepares_cannot_both_observe_an_absent_sidecar(
    tmp_path, monkeypatch, trust
):
    """One prepare wins; a concurrent different transaction refuses."""

    import threading

    from tradingagents.policy import owner_approval as owner_module

    fixture = _direct_owner_prepare_fixture(tmp_path, trust)
    approval = fixture["approval"]
    real_write = owner_module._write_protected_text
    first_at_write = threading.Event()
    second_at_write = threading.Event()
    release_first = threading.Event()
    guard = threading.Lock()
    write_calls = 0
    results: list[str] = []
    errors: list[BaseException] = []

    def blocked_write(path, text, *, label, canonical):
        nonlocal write_calls
        if Path(path) == Path(fixture["prepare_path"]):
            with guard:
                write_calls += 1
                ordinal = write_calls
            if ordinal == 1:
                first_at_write.set()
                assert release_first.wait(timeout=5)
            else:
                second_at_write.set()
        return real_write(path, text, label=label, canonical=canonical)

    monkeypatch.setattr(owner_module, "_write_protected_text", blocked_write)

    def invoke(transaction):
        try:
            results.append(
                write_owner_approval_prepare(
                    fixture["prepare_path"],
                    approval_id=approval["approval_id"],
                    action=approval["action"],
                    purpose=fixture["purpose"],
                    transaction_binding_sha256=fixture["binding"],
                    transaction=transaction,
                    now=NOW,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=invoke, args=(fixture["transaction"],))
    second = threading.Thread(
        target=invoke,
        args=(
            {
                **fixture["transaction"],
                "output_path": str(tmp_path / "different-output.json"),
            },
        ),
    )
    first.start()
    assert first_at_write.wait(timeout=5)
    second.start()
    overlapped_before_release = second_at_write.wait(timeout=1)
    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert overlapped_before_release is False
    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], OwnerApprovalError)
    assert "different transaction" in str(errors[0])
    assert write_calls == 1
    assert _ledger_lines(trust) == []


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("source_binding", {"guard": "tampered"}),
        ("output_path", "/tmp/tampered-output.json"),
        ("canonical_before_sha256", "a" * 64),
        ("canonical_after_sha256", "b" * 64),
    ),
)
def test_tampered_prepared_transaction_never_matches_old_ledger_binding(
    tmp_path, trust, field, replacement
):
    fixture = _direct_owner_prepare_fixture(
        tmp_path, trust, output_name=f"tamper-{field}.json"
    )
    approval = fixture["approval"]
    strict_binding = write_owner_approval_prepare(
        fixture["prepare_path"],
        approval_id=approval["approval_id"],
        action=approval["action"],
        purpose=fixture["purpose"],
        transaction_binding_sha256=fixture["binding"],
        transaction=fixture["transaction"],
        now=NOW,
    )
    consume_owner_approval(
        approval_id=approval["approval_id"],
        action=approval["action"],
        purpose=fixture["purpose"],
        transaction_binding_sha256=fixture["binding"],
        prepared_transaction_binding_sha256=strict_binding,
        now=NOW,
    )
    raw = json.loads(fixture["prepare_path"].read_text(encoding="utf-8"))
    raw["transaction"][field] = replacement
    fixture["prepare_path"].write_text(
        json.dumps(raw, sort_keys=True), encoding="utf-8"
    )

    assert read_owner_approval_prepare(fixture["prepare_path"]) is None
    assert owner_approval_prepare_matches(
        fixture["prepare_path"], transaction=fixture["transaction"]
    ) is None
    assert owner_prepare_has_exact_consumption(fixture["prepare_path"]) is False
    with (
        pytest.raises(OwnerApprovalError, match="requires an exact"),
        exact_expired_owner_approval_recovery(
            fixture["prepare_path"],
            recovery_identity=fixture["recovery_identity"],
        ),
    ):
        pass


def test_tampered_prepared_binding_never_matches_its_unchanged_transaction(
    tmp_path, trust
):
    fixture = _direct_owner_prepare_fixture(tmp_path, trust)
    approval = fixture["approval"]
    strict_binding = write_owner_approval_prepare(
        fixture["prepare_path"],
        approval_id=approval["approval_id"],
        action=approval["action"],
        purpose=fixture["purpose"],
        transaction_binding_sha256=fixture["binding"],
        transaction=fixture["transaction"],
        now=NOW,
    )
    consume_owner_approval(
        approval_id=approval["approval_id"],
        action=approval["action"],
        purpose=fixture["purpose"],
        transaction_binding_sha256=fixture["binding"],
        prepared_transaction_binding_sha256=strict_binding,
        now=NOW,
    )
    raw = json.loads(fixture["prepare_path"].read_text(encoding="utf-8"))
    raw["prepared_transaction_binding_sha256"] = "0" * 64
    fixture["prepare_path"].write_text(
        json.dumps(raw, sort_keys=True), encoding="utf-8"
    )

    assert read_owner_approval_prepare(fixture["prepare_path"]) is None
    assert owner_prepare_has_exact_consumption(fixture["prepare_path"]) is False
    with (
        pytest.raises(OwnerApprovalError, match="requires an exact"),
        exact_expired_owner_approval_recovery(
            fixture["prepare_path"],
            recovery_identity=fixture["recovery_identity"],
        ),
    ):
        pass


def _pending_v4(tmp_path, action, *, approval_id, binding):
    control = tmp_path / "control-commitment.json"
    committed_at = NOW.isoformat(timespec="seconds")
    commitment_id = _commitment_id(
        intent_full_sha256=INTENT_A,
        order_payload_sha256=PAYLOAD_SHA,
        client_order_id="order-recover",
        control_preimage_sha256="0" * 64,
        rate_reservation_sha256=RATE_SHA,
        owner_approval_id=approval_id,
        risk_envelope_ref="config/risk_envelope.yaml",
        risk_envelope_sha256="e" * 64,
    )
    control.write_text(
        json.dumps(
            {
                "frozen": False,
                "reason": "recovery fixture",
                "dead_man_expires_at": "2026-06-03T16:00:00+00:00",
                "normal_live_submission_commitments": [
                    {
                        "schema_version": 4,
                        "commitment_id": commitment_id,
                        "intent_full_sha256": INTENT_A,
                        "order_payload_sha256": PAYLOAD_SHA,
                        "client_order_id": "order-recover",
                        "control_preimage_sha256": "0" * 64,
                        "rate_reservation_sha256": RATE_SHA,
                        "owner_approval_id": approval_id,
                        "owner_approval_transaction_binding_sha256": binding,
                        "risk_envelope_ref": "config/risk_envelope.yaml",
                        "risk_envelope_sha256": "e" * 64,
                        "committed_at": committed_at,
                        "state": "pending",
                        "outcome": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return control


def _binding_for(artifact, action):
    return transaction_binding_sha256(
        approval_id=artifact["approval_id"],
        action=LIVE_PROMOTION,
        purpose=f"live_order:{action.decision_id}:order-recover",
        subject=_subject(
            action,
            client_order_id="order-recover",
            intent_full_sha256=INTENT_A,
            order_payload_sha256=PAYLOAD_SHA,
        ),
        risk_envelope_ref="unused-ref",
        risk_envelope_sha256="0" * 64,
    )


def test_recovery_requires_matching_id_and_transaction_binding(tmp_path, trust):
    envelope, promotion, control = _inputs(tmp_path)
    action = _action(decision_id="decision-recover")
    purpose = f"live_order:{action.decision_id}:order-recover"

    approval = _sign(
        trust,
        action,
        envelope_path=envelope,
        client_order_id="order-recover",
        intent_full_sha256=INTENT_A,
        order_payload_sha256=PAYLOAD_SHA,
    )
    binding = transaction_binding_sha256(
        approval_id=approval["approval_id"],
        action=LIVE_PROMOTION,
        purpose=purpose,
        subject=_subject(
            action,
            client_order_id="order-recover",
            intent_full_sha256=INTENT_A,
            order_payload_sha256=PAYLOAD_SHA,
        ),
        risk_envelope_ref=str(envelope),
        risk_envelope_sha256=hashlib.sha256(envelope.read_bytes()).hexdigest(),
    )
    matching = _pending_v4(
        tmp_path, action,
        approval_id=approval["approval_id"],
        binding=binding,
    )
    # A public guard evaluation never burns an order approval.  Model the
    # only permitted recovery state directly: an inert exact prepare followed
    # by the matching canonical ledger record and durable commitment.
    transaction = {
        "operation": "normal_live_broker_submit",
        "subject": _subject(
            action,
            client_order_id="order-recover",
            intent_full_sha256=INTENT_A,
            order_payload_sha256=PAYLOAD_SHA,
        ),
        "control_path": str(matching),
        "normal_live_commitment": json.loads(
            matching.read_text(encoding="utf-8")
        )["normal_live_submission_commitments"][0],
    }
    prepare_path = owner_approval_prepare_path(matching)
    strict_binding = write_owner_approval_prepare(
        prepare_path,
        approval_id=approval["approval_id"],
        action=LIVE_PROMOTION,
        purpose=purpose,
        transaction_binding_sha256=binding,
        transaction=transaction,
        now=NOW,
    )
    consume_owner_approval(
        approval_id=approval["approval_id"],
        action=LIVE_PROMOTION,
        purpose=purpose,
        transaction_binding_sha256=binding,
        prepared_transaction_binding_sha256=strict_binding,
        now=NOW,
    )
    assert owner_prepare_has_exact_consumption(prepare_path)

    recovered = _gate(
        [action],
        approval,
        envelope_path=envelope,
        promotion_path=promotion,
        control_path=matching,
        commitment=json.loads(matching.read_text(encoding="utf-8"))[
            "normal_live_submission_commitments"
        ][0],
        intent_full=INTENT_A,
        payload_sha=PAYLOAD_SHA,
        client_order_id="order-recover",
        trust=trust,
    )
    assert recovered.allowed is True, [i.reason for i in recovered.issues]

    # A commitment bound to a DIFFERENT approval id denies.
    foreign = _pending_v4(
        tmp_path, action,
        approval_id="e" * 64,
        binding=binding,
    )
    denied = _gate(
        [action],
        approval,
        envelope_path=envelope,
        promotion_path=promotion,
        control_path=foreign,
        commitment=json.loads(foreign.read_text(encoding="utf-8"))[
            "normal_live_submission_commitments"
        ][0],
        intent_full=INTENT_A,
        payload_sha=PAYLOAD_SHA,
        client_order_id="order-recover",
        trust=trust,
    )
    assert denied.allowed is False

    # A commitment with a mismatched transaction binding denies.
    wrong_binding = _pending_v4(
        tmp_path, action,
        approval_id=approval["approval_id"],
        binding="7" * 64,
    )
    denied_binding = _gate(
        [action],
        approval,
        envelope_path=envelope,
        promotion_path=promotion,
        control_path=wrong_binding,
        commitment=json.loads(wrong_binding.read_text(encoding="utf-8"))[
            "normal_live_submission_commitments"
        ][0],
        intent_full=INTENT_A,
        payload_sha=PAYLOAD_SHA,
        client_order_id="order-recover",
        trust=trust,
    )
    assert denied_binding.allowed is False

    # Direct primitive proof: recovery requires id + action + purpose + binding.
    with pytest.raises(OwnerApprovalError):
        require_prior_consumption_for_commitment_recovery(
            approval_id=approval["approval_id"],
            action=LIVE_PROMOTION,
            purpose=purpose + "-tampered",
            transaction_binding_sha256=binding,
        )


def test_guard_only_envelope_expansion_is_structural_and_non_mutating(tmp_path, trust):
    """P1-A: once the envelope bytes change, live orders are refused unless an
    independently signed risk_envelope_expansion approval is supplied."""

    from tests._owner_approval_testing import (
        build_risk_envelope_expansion_approval,
    )

    envelope, promotion, control = _inputs(tmp_path)
    action = _action()
    approval = _sign(trust, action, envelope_path=envelope)

    # A guard-only call evaluates the original envelope but persists nothing.
    first = _gate([action], approval, envelope_path=envelope,
                  promotion_path=promotion, control_path=control, trust=trust)
    assert first.allowed is True

    # Enlarge the envelope (still valid) WITHOUT an expansion artifact.
    envelope.write_text(
        Path(envelope).read_text(encoding="utf-8").replace(
            "per_name_cap_usd: 50.00", "per_name_cap_usd: 500.00"
        ),
        encoding="utf-8",
    )
    fresh_order = _sign(trust, action, envelope_path=envelope)
    denied = _gate([action], fresh_order, envelope_path=envelope,
                   promotion_path=promotion, control_path=control,
                   trust=trust, expansion_approval=None)
    assert denied.allowed is False
    assert any("risk envelope expansion" in i.reason for i in denied.issues)
    assert denied.checks["risk_envelope_expansion"] is False

    # A wrong-action artifact is also refused.
    wrong_action = build_risk_envelope_expansion_approval(
        trust.private_hex,
        ref=str(envelope),
        sha256=hashlib.sha256(envelope.read_bytes()).hexdigest(),
        issued_at=NOW,
    )
    wrong_action = {**wrong_action, "action": "live_promotion"}
    body = {k: v for k, v in wrong_action.items()
            if k not in ("signature", "approval_id")}
    from tests._owner_approval_testing import canonical_json_bytes
    encoded = canonical_json_bytes(body)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    signer = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(trust.private_hex))
    wrong_action["approval_id"] = hashlib.sha256(encoded).hexdigest()
    wrong_action["signature"]["value"] = signer.sign(encoded).hex()

    denied_wrong_action = _gate(
        [action], fresh_order, envelope_path=envelope,
        promotion_path=promotion, control_path=control,
        trust=trust, expansion_approval=wrong_action,
    )
    assert denied_wrong_action.allowed is False

    # With the correct independently signed expansion approval, a guard-only
    # call may evaluate the enlarged envelope as admissible.  Because the
    # original guard was non-mutating there is no prior authorized digest yet.
    # This still cannot authorize the envelope or burn either artifact without
    # a durable live commitment.
    good_expansion = build_risk_envelope_expansion_approval(
        trust.private_hex,
        ref=str(envelope),
        sha256=hashlib.sha256(envelope.read_bytes()).hexdigest(),
        issued_at=NOW,
    )
    allowed = _gate([action], fresh_order, envelope_path=envelope,
                    promotion_path=promotion, control_path=control,
                    trust=trust, expansion_approval=good_expansion)
    assert allowed.allowed is True, [i.reason for i in allowed.issues]
    from tradingagents.policy.owner_approval import (
        canonical_risk_envelope_authorization_prepare_path,
        owner_approval_has_consumption,
    )

    assert not owner_approval_has_consumption(fresh_order["approval_id"])
    assert not owner_approval_has_consumption(good_expansion["approval_id"])
    assert not trust.ledger.exists()
    assert not trust.authorization.exists()
    assert not Path(canonical_risk_envelope_authorization_prepare_path()).exists()

    # Replaying the same structural evaluation remains non-mutating.
    replay = _gate([action], fresh_order, envelope_path=envelope,
                   promotion_path=promotion, control_path=control,
                   trust=trust, expansion_approval=good_expansion)
    assert replay.allowed is True
    assert not owner_approval_has_consumption(fresh_order["approval_id"])
    assert not owner_approval_has_consumption(good_expansion["approval_id"])
    assert not trust.ledger.exists()
    assert not trust.authorization.exists()


def test_well_formed_unledgered_envelope_authorization_cannot_mint_authority(
    tmp_path,
    trust,
):
    """A checkout-writable JSON record is never an authority source."""

    from tradingagents.policy.owner_approval import (
        require_risk_envelope_expansion,
    )

    envelope, _promotion, _control = _inputs(tmp_path)
    digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    trust.authorization.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "risk_envelope_ref": str(envelope),
                "risk_envelope_sha256": digest,
                "approval_id": "d" * 64,
                "transaction_binding_sha256": "e" * 64,
                "authorized_at": NOW.isoformat(),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(OwnerApprovalError, match="risk envelope expansion"):
        require_risk_envelope_expansion(
            resolved_envelope_path=envelope,
            current_envelope_sha256=digest,
            expansion_approval=None,
            now=NOW,
        )


def test_monotonic_risk_tightening_remains_machine_operable(tmp_path, trust):
    from tests._owner_approval_testing import build_risk_envelope_expansion_approval
    from tradingagents.policy.owner_approval import require_risk_envelope_expansion

    envelope, promotion, control = _inputs(tmp_path)
    action = _action()
    initial_order = _sign(trust, action, envelope_path=envelope)
    initial = _gate(
        [action],
        initial_order,
        envelope_path=envelope,
        promotion_path=promotion,
        control_path=control,
        trust=trust,
    )
    assert initial.allowed is True
    # Production establishes this durable authorization only beside an exact
    # commitment.  Seed that already-finalized predecessor here so the later
    # guard can prove a *machine* tightening without mutating the record.
    initial_digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    require_risk_envelope_expansion(
        resolved_envelope_path=envelope,
        current_envelope_sha256=initial_digest,
        expansion_approval=build_risk_envelope_expansion_approval(
            trust.private_hex,
            ref=str(envelope),
            sha256=initial_digest,
            issued_at=NOW,
        ),
        now=NOW,
        consume=True,
    )

    envelope.write_text(
        envelope.read_text(encoding="utf-8").replace(
            "per_name_cap_usd: 50.00",
            "per_name_cap_usd: 25.00",
        ),
        encoding="utf-8",
    )
    tightened_order = _sign(trust, action, envelope_path=envelope)
    tightened = _gate(
        [action],
        tightened_order,
        envelope_path=envelope,
        promotion_path=promotion,
        control_path=control,
        trust=trust,
        expansion_approval=None,
    )

    assert tightened.allowed is True, [issue.reason for issue in tightened.issues]
    record = json.loads(trust.authorization.read_text(encoding="utf-8"))
    # Guard-only evaluation does not write the tightened authorization; only
    # the committed path may finalize it.
    assert record["risk_envelope_sha256"] == initial_digest


def test_expansion_authorization_recovers_after_consumption_record_crash(
    tmp_path,
    monkeypatch,
    trust,
):
    from tests._owner_approval_testing import (
        build_risk_envelope_expansion_approval,
    )
    from tradingagents.policy import owner_approval as owner_module

    envelope, _promotion, _control = _inputs(tmp_path)
    digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    approval = build_risk_envelope_expansion_approval(
        trust.private_hex,
        ref=str(envelope),
        sha256=digest,
        issued_at=NOW,
    )
    real_write = owner_module._write_risk_envelope_authorization_unlocked

    def fail_record_write(**_kwargs):
        raise OSError("injected authorization record crash")

    monkeypatch.setattr(
        owner_module,
        "_write_risk_envelope_authorization_unlocked",
        fail_record_write,
    )
    with pytest.raises(OSError, match="authorization record crash"):
        owner_module.require_risk_envelope_expansion(
            resolved_envelope_path=envelope,
            current_envelope_sha256=digest,
            expansion_approval=approval,
            now=NOW,
            consume=True,
        )

    monkeypatch.setattr(
        owner_module,
        "_write_risk_envelope_authorization_unlocked",
        real_write,
    )
    owner_module.require_risk_envelope_expansion(
        resolved_envelope_path=envelope,
        current_envelope_sha256=digest,
        expansion_approval=None,
        now=NOW + datetime.timedelta(hours=2),
        consume=True,
    )

    record = json.loads(trust.authorization.read_text(encoding="utf-8"))
    assert record["approval_id"] == approval["approval_id"]
    assert record["risk_envelope_sha256"] == digest


def test_risk_expansion_historical_now_cannot_revive_expired_unconsumed_approval(
    tmp_path, monkeypatch, trust
):
    """Caller ``now`` is evidence time, never fresh expansion authority time."""

    from tests._owner_approval_testing import build_risk_envelope_expansion_approval
    from tradingagents.policy import owner_approval as owner_module

    envelope, _promotion, _control = _inputs(tmp_path)
    digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    authority_now = NOW + datetime.timedelta(minutes=31)
    # This is intentionally a no-op against the former implementation, so the
    # pre-fix call below consumes the artifact and the test is RED.
    monkeypatch.setattr(
        owner_module,
        "_owner_approval_authority_utc_now",
        lambda: authority_now,
        raising=False,
    )
    approval = build_risk_envelope_expansion_approval(
        trust.private_hex,
        ref=str(envelope),
        sha256=digest,
        issued_at=NOW - datetime.timedelta(minutes=10),
    )

    with pytest.raises(OwnerApprovalError, match="expired"):
        owner_module.require_risk_envelope_expansion(
            resolved_envelope_path=envelope,
            current_envelope_sha256=digest,
            expansion_approval=approval,
            now=NOW,
            consume=True,
        )

    assert _ledger_lines(trust) == []
    assert not trust.authorization.exists()


def test_public_verify_and_record_write_cannot_mint_historical_expansion(
    tmp_path, monkeypatch, trust
):
    """Two public APIs cannot turn a historical clock into fresh authority."""

    from tests._owner_approval_testing import build_risk_envelope_expansion_approval
    from tradingagents.policy import owner_approval as owner_module

    envelope, _promotion, _control = _inputs(tmp_path)
    digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    authority_now = NOW + datetime.timedelta(minutes=2)
    monkeypatch.setattr(
        owner_module,
        "_owner_approval_authority_utc_now",
        lambda: authority_now,
    )
    approval = build_risk_envelope_expansion_approval(
        trust.private_hex,
        ref=str(envelope),
        sha256=digest,
        issued_at=NOW - datetime.timedelta(minutes=29),
    )
    subject = owner_module.risk_envelope_expansion_subject(
        ref=str(envelope), sha256=digest, previous_sha256=None
    )
    purpose = f"risk_envelope_expansion:{digest}"
    binding = owner_module.transaction_binding_sha256(
        approval_id=approval["approval_id"],
        action="risk_envelope_expansion",
        purpose=purpose,
        subject=subject,
        risk_envelope_ref=str(envelope),
        risk_envelope_sha256=digest,
    )

    with pytest.raises(OwnerApprovalError, match="expired"):
        owner_module.verify_owner_approval(
            approval=approval,
            expected_action="risk_envelope_expansion",
            subject=subject,
            source_binding={"gate": "normal_live_admission"},
            risk_envelope_ref=str(envelope),
            risk_envelope_sha256=digest,
            now=NOW,
            purpose=purpose,
            consume=True,
        )

    with pytest.raises(
        OwnerApprovalError,
        match="exact durable prepare and matching canonical ledger consumption",
    ):
        owner_module.write_risk_envelope_authorization(
            risk_envelope_ref=str(envelope),
            risk_envelope_sha256=digest,
            risk_envelope_text=envelope.read_text(encoding="utf-8"),
            previous_sha256=None,
            owner_approval=approval,
            approval_id=approval["approval_id"],
            transaction_binding_sha256=binding,
            authorized_at=NOW,
        )

    assert _ledger_lines(trust) == []
    assert not trust.authorization.exists()


def test_public_helpers_cannot_compose_an_expired_risk_expansion(
    tmp_path, monkeypatch, trust
):
    """Risk prepare, consumption, and finalization are transaction-private."""

    from tests._owner_approval_testing import build_risk_envelope_expansion_approval
    from tradingagents.policy import owner_approval as owner_module

    envelope, _promotion, _control = _inputs(tmp_path)
    digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    authority_now = NOW + datetime.timedelta(minutes=2)
    approval = build_risk_envelope_expansion_approval(
        trust.private_hex,
        ref=str(envelope),
        sha256=digest,
        issued_at=NOW - datetime.timedelta(minutes=29),
    )
    entry = owner_module.require_risk_envelope_expansion(
        resolved_envelope_path=envelope,
        current_envelope_sha256=digest,
        expansion_approval=approval,
        now=NOW,
        consume=False,
    )
    monkeypatch.setattr(
        owner_module,
        "_owner_approval_authority_utc_now",
        lambda: authority_now,
    )

    with pytest.raises(OwnerApprovalError, match="atomic authorization transaction"):
        owner_module.prepare_risk_envelope_authorization(entry, now=NOW)
    with pytest.raises(OwnerApprovalError, match="atomic authorization transaction"):
        owner_module.consume_owner_approval(
            approval_id=str(entry["approval_id"]),
            action=str(entry["action"]),
            purpose=str(entry["purpose"]),
            transaction_binding_sha256=str(entry["transaction_binding_sha256"]),
            prepared_transaction_binding_sha256="f" * 64,
            now=NOW,
        )
    with pytest.raises(
        OwnerApprovalError,
        match="exact durable prepare and matching canonical ledger consumption",
    ):
        owner_module.write_risk_envelope_authorization(
            risk_envelope_ref=str(envelope),
            risk_envelope_sha256=digest,
            risk_envelope_text=envelope.read_text(encoding="utf-8"),
            previous_sha256=None,
            owner_approval=approval,
            approval_id=str(entry["approval_id"]),
            transaction_binding_sha256=str(entry["transaction_binding_sha256"]),
            authorized_at=NOW,
        )

    assert _ledger_lines(trust) == []
    assert not owner_module.canonical_risk_envelope_authorization_prepare_path().exists()
    assert not trust.authorization.exists()


def test_stale_expansion_tip_refuses_before_any_batch_approval_is_burned(
    tmp_path, trust
):
    """An intervening tightening wins before a stale expansion can consume."""

    from tests._owner_approval_testing import build_risk_envelope_expansion_approval
    from tradingagents.policy import owner_approval as owner_module

    envelope, _promotion, _control = _inputs(tmp_path)
    original_text = envelope.read_text(encoding="utf-8")
    original_digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    initial_approval = build_risk_envelope_expansion_approval(
        trust.private_hex,
        ref=str(envelope),
        sha256=original_digest,
        issued_at=NOW,
    )
    owner_module.require_risk_envelope_expansion(
        resolved_envelope_path=envelope,
        current_envelope_sha256=original_digest,
        expansion_approval=initial_approval,
        now=NOW,
        consume=True,
    )

    expanded_text = original_text.replace(
        "per_name_cap_usd: 50.00", "per_name_cap_usd: 100.00"
    )
    envelope.write_text(expanded_text, encoding="utf-8")
    expanded_digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    stale_approval = build_risk_envelope_expansion_approval(
        trust.private_hex,
        ref=str(envelope),
        sha256=expanded_digest,
        previous_sha256=original_digest,
        issued_at=NOW,
    )
    stale_entry = owner_module.require_risk_envelope_expansion(
        resolved_envelope_path=envelope,
        current_envelope_sha256=expanded_digest,
        expansion_approval=stale_approval,
        now=NOW,
        consume=False,
    )

    tightened_text = original_text.replace(
        "per_name_cap_usd: 50.00", "per_name_cap_usd: 25.00"
    )
    envelope.write_text(tightened_text, encoding="utf-8")
    tightened_digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    owner_module.require_risk_envelope_expansion(
        resolved_envelope_path=envelope,
        current_envelope_sha256=tightened_digest,
        expansion_approval=None,
        now=NOW + datetime.timedelta(seconds=1),
        consume=True,
    )

    envelope.write_text(expanded_text, encoding="utf-8")
    unrelated_batch_approval = {
        "approval_id": "9" * 64,
        "action": LIVE_PROMOTION,
        "purpose": "stale-risk-shared-batch",
        "transaction_binding_sha256": "8" * 64,
    }
    with pytest.raises(OwnerApprovalError, match="predecessor changed"):
        owner_module._commit_owner_approval_transaction(
            [unrelated_batch_approval],
            expansion_entry=stale_entry,
            now=NOW + datetime.timedelta(seconds=2),
        )

    ledger = _ledger_lines(trust)
    assert [entry["approval_id"] for entry in ledger] == [
        initial_approval["approval_id"]
    ]
    assert not owner_module.canonical_risk_envelope_authorization_prepare_path().exists()
    record = json.loads(trust.authorization.read_text(encoding="utf-8"))
    assert record["risk_envelope_sha256"] == tightened_digest


def test_stale_machine_tightening_cannot_relax_a_newer_safer_tip(tmp_path, trust):
    """Two reductions compare-and-write against the same serialized tip."""

    from tests._owner_approval_testing import build_risk_envelope_expansion_approval
    from tradingagents.policy import owner_approval as owner_module

    envelope, _promotion, _control = _inputs(tmp_path)
    original_text = envelope.read_text(encoding="utf-8")
    original_digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    initial_approval = build_risk_envelope_expansion_approval(
        trust.private_hex,
        ref=str(envelope),
        sha256=original_digest,
        issued_at=NOW,
    )
    owner_module.require_risk_envelope_expansion(
        resolved_envelope_path=envelope,
        current_envelope_sha256=original_digest,
        expansion_approval=initial_approval,
        now=NOW,
        consume=True,
    )

    stale_text = original_text.replace(
        "per_name_cap_usd: 50.00", "per_name_cap_usd: 45.00"
    )
    envelope.write_text(stale_text, encoding="utf-8")
    stale_digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    stale_entry = owner_module.require_risk_envelope_expansion(
        resolved_envelope_path=envelope,
        current_envelope_sha256=stale_digest,
        expansion_approval=None,
        now=NOW + datetime.timedelta(seconds=1),
        consume=False,
    )

    safer_text = original_text.replace(
        "per_name_cap_usd: 50.00", "per_name_cap_usd: 40.00"
    )
    envelope.write_text(safer_text, encoding="utf-8")
    safer_digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    owner_module.require_risk_envelope_expansion(
        resolved_envelope_path=envelope,
        current_envelope_sha256=safer_digest,
        expansion_approval=None,
        now=NOW + datetime.timedelta(seconds=2),
        consume=True,
    )

    envelope.write_text(stale_text, encoding="utf-8")
    with pytest.raises(OwnerApprovalError, match="changed during risk-reduction"):
        owner_module.finalize_risk_envelope_authorization(
            stale_entry,
            now=NOW + datetime.timedelta(seconds=3),
        )

    record = json.loads(trust.authorization.read_text(encoding="utf-8"))
    assert record["risk_envelope_sha256"] == safer_digest
    assert record["tightening_history"][-1]["sha256"] == safer_digest
    from tradingagents.policy.owner_approval import (
        canonical_risk_envelope_authorization_prepare_path,
    )

    assert not canonical_risk_envelope_authorization_prepare_path().exists()


@pytest.mark.parametrize(
    "prepared_binding",
    (None, "0" * 64),
    ids=("missing", "different"),
)
def test_expansion_batch_refuses_missing_or_different_durable_prepare_binding(
    tmp_path, trust, prepared_binding
):
    """A batch cannot burn an expansion approval from ledger-shaped input.

    It must carry the exact binding freshly validated from the durable custom
    prepare; missing or substituted bindings leave the signed artifact unused.
    """

    from tests._owner_approval_testing import (
        build_risk_envelope_expansion_approval,
    )
    from tradingagents.policy.owner_approval import (
        consume_owner_approvals_batch,
        require_risk_envelope_expansion,
    )

    envelope, _promotion, _control = _inputs(tmp_path)
    digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    approval = build_risk_envelope_expansion_approval(
        trust.private_hex,
        ref=str(envelope),
        sha256=digest,
        issued_at=NOW,
    )
    entry = require_risk_envelope_expansion(
        resolved_envelope_path=envelope,
        current_envelope_sha256=digest,
        expansion_approval=approval,
        now=NOW,
        consume=False,
    )
    batch_entry = {
        "approval_id": str(entry["approval_id"]),
        "action": str(entry["action"]),
        "purpose": str(entry["purpose"]),
        "transaction_binding_sha256": str(entry["transaction_binding_sha256"]),
    }
    if prepared_binding is not None:
        batch_entry["prepared_transaction_binding_sha256"] = prepared_binding

    with pytest.raises(OwnerApprovalError, match="atomic authorization transaction"):
        consume_owner_approvals_batch([batch_entry], now=NOW)

    assert not trust.ledger.exists()
    assert not trust.authorization.exists()


def test_tampered_expansion_prepare_cannot_reuse_exact_batch_consumption(
    tmp_path, monkeypatch, trust
):
    """The ledger binding is inert if the durable prepare's digest changes."""

    from tests._owner_approval_testing import (
        build_risk_envelope_expansion_approval,
    )
    from tradingagents.policy import owner_approval as owner_module

    envelope, _promotion, _control = _inputs(tmp_path)
    digest = hashlib.sha256(envelope.read_bytes()).hexdigest()
    approval = build_risk_envelope_expansion_approval(
        trust.private_hex,
        ref=str(envelope),
        sha256=digest,
        issued_at=NOW,
    )
    real_write = owner_module._write_risk_envelope_authorization_unlocked

    def fail_record_write(**_kwargs):
        raise OSError("injected authorization record crash")

    monkeypatch.setattr(
        owner_module,
        "_write_risk_envelope_authorization_unlocked",
        fail_record_write,
    )
    with pytest.raises(OSError, match="authorization record crash"):
        owner_module.require_risk_envelope_expansion(
            resolved_envelope_path=envelope,
            current_envelope_sha256=digest,
            expansion_approval=approval,
            now=NOW,
            consume=True,
        )
    monkeypatch.setattr(
        owner_module,
        "_write_risk_envelope_authorization_unlocked",
        real_write,
    )
    original_ledger = _ledger_lines(trust)
    assert len(original_ledger) == 1

    # Keep the old ledger record but change the sidecar's complete canonical
    # transaction.  Its digest is recomputed on read, so recovery must refuse
    # instead of turning the old consumption into this changed envelope write.
    prepare_path = owner_module.canonical_risk_envelope_authorization_prepare_path()
    raw = json.loads(prepare_path.read_text(encoding="utf-8"))
    raw["risk_envelope_text"] = raw["risk_envelope_text"].replace(
        "per_name_cap_usd: 50.00", "per_name_cap_usd: 500.00"
    )
    prepare_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(OwnerApprovalError, match="snapshot|prepare"):
        owner_module.require_risk_envelope_expansion(
            resolved_envelope_path=envelope,
            current_envelope_sha256=digest,
            expansion_approval=None,
            now=NOW + datetime.timedelta(hours=2),
            consume=True,
        )

    assert _ledger_lines(trust) == original_ledger
    assert not trust.authorization.exists()


def test_expired_expansion_artifact_denies(tmp_path, trust):
    import datetime as dt

    from tests._owner_approval_testing import (
        build_risk_envelope_expansion_approval,
    )

    envelope, promotion, control = _inputs(tmp_path)
    action = _action()
    approval = _sign(trust, action, envelope_path=envelope)

    # Change the envelope so the expansion transition is required.
    envelope.write_text(
        Path(envelope).read_text(encoding="utf-8").replace(
            "per_name_cap_usd: 50.00", "per_name_cap_usd: 400.00"
        ),
        encoding="utf-8",
    )

    expired_expansion = build_risk_envelope_expansion_approval(
        trust.private_hex,
        ref=str(envelope),
        sha256=hashlib.sha256(envelope.read_bytes()).hexdigest(),
        issued_at=NOW - dt.timedelta(minutes=45),
    )
    result = _gate([action], approval, envelope_path=envelope,
                   promotion_path=promotion, control_path=control,
                   trust=trust, expansion_approval=expired_expansion)
    assert result.allowed is False
    assert any("expired" in i.reason for i in result.issues)


def test_later_gate_denial_leaves_both_artifacts_unconsumed(tmp_path, trust):
    """P2-B regression: with a changed envelope, both the live_promotion and
    the risk_envelope_expansion artifacts must remain unconsumed when a later
    ordinary live gate (frozen control) denies the evaluation."""

    from tests._owner_approval_testing import (
        build_risk_envelope_expansion_approval,
    )
    from tradingagents.policy.owner_approval import (
        owner_approval_has_consumption,
    )

    envelope, promotion, control = _inputs(tmp_path)
    action = _action()
    order_approval = _sign(trust, action, envelope_path=envelope)
    expansion_approval = build_risk_envelope_expansion_approval(
        trust.private_hex,
        ref=str(envelope),
        sha256=hashlib.sha256(envelope.read_bytes()).hexdigest(),
        issued_at=NOW,
    )

    # Freeze control AFTER approvals were built: the expansion structural
    # preflight passes, but the frozen-control gate denies the evaluation.
    control.write_text(
        json.dumps(
            {
                "frozen": True,
                "reason": "later-gate denial fixture",
                "dead_man_expires_at": "2026-06-03T16:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    result = _gate(
        [action],
        order_approval,
        envelope_path=envelope,
        promotion_path=promotion,
        control_path=control,
        trust=trust,
        expansion_approval=expansion_approval,
    )
    assert result.allowed is False

    # Both artifacts remain unconsumed in the canonical ledger.
    assert not owner_approval_has_consumption(order_approval["approval_id"])
    assert not owner_approval_has_consumption(expansion_approval["approval_id"])
    assert not trust.ledger.exists()
