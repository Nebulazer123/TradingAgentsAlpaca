"""Owner-approval authority boundary: strict artifact verification contract.

Public verification is canonical-only: callers cannot select the trust
anchor, consumption ledger, repository root, or policy fingerprint.  These
tests redirect ONLY the canonical resolver functions into a temp directory
(via ``install_isolated_owner_trust``) and sign genuine Ed25519 artifacts
under exactly that redirected trust root.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
import pwd
import threading
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tests._owner_approval_testing import (
    DEFAULT_ENVELOPE_REF,
    DEFAULT_ENVELOPE_SHA256,
    build_owner_approval,
    canonical_json_bytes,
    install_isolated_owner_trust,
)
from tradingagents.orchestration.authority import ActionClass, authority_for
from tradingagents.policy.owner_approval import (
    OWNER_APPROVAL_KIND,
    OwnerApprovalError,
    consume_owner_approval,
    default_policy_fingerprint,
    requires_owner_approval,
    verify_owner_approval,
)

NOW = datetime.datetime(2026, 6, 3, 15, 10, tzinfo=datetime.timezone.utc)
ACTION = ActionClass.LIVE_PROMOTION.value
SUBJECT = {"kind": "sleeve_live_eligibility", "sleeves": ["pullback-support"]}
SOURCE = {"tournament_id": "paper-tournament-1", "canonical_input_sha256": "a" * 64}
PURPOSE = "promotion_sync:paper-tournament-1"


@pytest.fixture()
def trust(tmp_path, monkeypatch):
    from tradingagents.policy import owner_approval as owner_module

    handle = install_isolated_owner_trust(
        monkeypatch, tmp_path / "trust", seed=b"owner-approval-suite-seed"
    )
    monkeypatch.setattr(owner_module, "_owner_approval_authority_utc_now", lambda: NOW)
    return handle


def _sign(trust, *, action=ACTION, mutate=None, **kwargs):
    values = {
        "subject": SUBJECT,
        "source_binding": SOURCE,
        "issued_at": NOW,
        "ttl_minutes": 30,
    }
    values.update(kwargs)
    return build_owner_approval(
        private_key_hex=trust.private_hex, action=action, mutate=mutate, **values
    )


def _verify(
    approval,
    *,
    now=NOW,
    action=ACTION,
    subject=SUBJECT,
    source_binding=SOURCE,
    risk_envelope_ref=DEFAULT_ENVELOPE_REF,
    risk_envelope_sha256=DEFAULT_ENVELOPE_SHA256,
    purpose=PURPOSE,
    consume=True,
):
    return verify_owner_approval(
        approval=approval,
        expected_action=action,
        subject=subject,
        source_binding=source_binding,
        risk_envelope_ref=risk_envelope_ref,
        risk_envelope_sha256=risk_envelope_sha256,
        now=now,
        purpose=purpose,
        consume=consume,
    )


def test_valid_isolated_approval_verifies_and_consumes_once(trust):
    approval = _sign(trust)

    verdict = _verify(approval)

    assert verdict.allowed is True
    assert verdict.action == ACTION
    assert verdict.approval_id == approval["approval_id"]
    ledger = trust.ledger.read_text(encoding="utf-8")
    line = json.loads(ledger.splitlines()[0])
    assert set(line) == {
        "schema_version",
        "approval_id",
        "action",
        "purpose",
        "transaction_binding_sha256",
        "consumed_at",
    }
    assert line["approval_id"] == approval["approval_id"]


def test_replayed_approval_fails_closed_even_for_the_same_purpose(trust):
    approval = _sign(trust)
    _verify(approval)

    with pytest.raises(OwnerApprovalError, match="already used"):
        _verify(approval)

    with pytest.raises(OwnerApprovalError, match="already used"):
        _verify(approval, purpose="second-privilege")


def test_verify_without_consumption_does_not_write_the_ledger(trust):
    approval = _sign(trust)

    _verify(approval, consume=False)

    assert not trust.ledger.exists()
    _verify(approval)
    with pytest.raises(OwnerApprovalError, match="already used"):
        _verify(approval)


def test_structure_only_verification_never_consumes(trust):
    from tradingagents.policy.owner_approval import verify_owner_approval_structure

    approval = _sign(trust)
    artifact = verify_owner_approval_structure(
        approval=approval,
        expected_action=ACTION,
        subject=SUBJECT,
        source_binding=SOURCE,
        now=NOW,
        purpose=PURPOSE,
    )
    assert artifact["approval_id"] == approval["approval_id"]
    assert not trust.ledger.exists()


def test_consume_requires_a_complete_exact_transaction_binding(trust):
    approval = _sign(trust)

    with pytest.raises(OwnerApprovalError, match="transaction binding"):
        consume_owner_approval(
            approval_id=approval["approval_id"],
            action=ACTION,
            purpose=PURPOSE,
            transaction_binding_sha256="not-a-digest",
            now=NOW,
        )
    assert not trust.ledger.exists()


def test_missing_trust_anchor_refuses_privileged_transition(tmp_path, monkeypatch):
    trust = install_isolated_owner_trust(monkeypatch, tmp_path / "trust", seed=b"owner-approval-suite-seed")
    approval = _sign(trust)
    monkeypatch.setattr(
        "tradingagents.policy.owner_approval.canonical_owner_trust_anchor_path",
        lambda: tmp_path / "absent-anchor.hex",
    )

    with pytest.raises(OwnerApprovalError, match="trust anchor"):
        _verify(approval)


def test_canonical_owner_state_paths_ignore_hostile_home(monkeypatch):
    """An environment-controlled HOME cannot redirect owner authority state."""

    from tradingagents.policy.owner_approval import (
        canonical_owner_consumption_ledger_path,
        canonical_owner_trust_anchor_path,
        canonical_risk_envelope_authorization_path,
    )

    hostile = Path("/tmp") / "hostile-owner-home"
    monkeypatch.setenv("HOME", str(hostile))
    account_root = Path(pwd.getpwuid(os.geteuid()).pw_dir)

    for protected_path in (
        canonical_owner_trust_anchor_path(),
        canonical_owner_consumption_ledger_path(),
        canonical_risk_envelope_authorization_path(),
    ):
        assert protected_path.is_relative_to(account_root)
        assert not protected_path.is_relative_to(hostile)


@pytest.mark.parametrize("kind", ["anchor", "anchor_parent", "ledger", "lock"])
def test_protected_owner_paths_reject_symlinked_components(trust, tmp_path, kind):
    """Anchor, ledger, and lock state never follows an attacker symlink."""

    approval = _sign(trust)
    if kind == "anchor":
        target = tmp_path / "attacker-anchor.hex"
        target.write_text(trust.anchor.read_text(encoding="utf-8"), encoding="utf-8")
        trust.anchor.unlink()
        trust.anchor.symlink_to(target)
    elif kind == "anchor_parent":
        parent = trust.anchor.parent
        backing = tmp_path / "backing-owner-approval"
        parent.rename(backing)
        parent.symlink_to(backing, target_is_directory=True)
    elif kind == "ledger":
        target = tmp_path / "attacker-ledger.jsonl"
        target.write_text("", encoding="utf-8")
        trust.ledger.symlink_to(target)
    else:
        lock = trust.ledger.with_name(f".{trust.ledger.name}.lock")
        target = tmp_path / "attacker-ledger.lock"
        target.write_text("", encoding="utf-8")
        lock.symlink_to(target)

    with pytest.raises(OwnerApprovalError, match="protected|trust anchor|ledger"):
        _verify(approval)
    assert not trust.ledger.exists() or trust.ledger.is_symlink()


def test_symlinked_risk_authorization_state_is_inert(trust, tmp_path, monkeypatch):
    """Authorization state is rejected before parsing, even if its bytes look valid."""

    from tradingagents.policy import owner_approval as owner_module

    target = tmp_path / "attacker-authorization.json"
    target.write_text('{"attacker": "state"}', encoding="utf-8")
    trust.authorization.symlink_to(target)
    monkeypatch.setattr(
        owner_module,
        "_validate_risk_envelope_authorization_record",
        lambda raw: raw,
    )

    assert owner_module.read_risk_envelope_authorization() is None


def test_protected_owner_paths_reject_group_or_other_writable_state(trust):
    """Effective-UID ownership alone is insufficient when others can write."""

    approval = _sign(trust)
    os.chmod(trust.anchor, 0o660)
    with pytest.raises(OwnerApprovalError, match="protected"):
        _verify(approval)
    assert not trust.ledger.exists()

    os.chmod(trust.anchor, 0o600)
    state_root = trust.ledger.parent
    os.chmod(state_root, 0o770)
    with pytest.raises(OwnerApprovalError, match="protected"):
        _verify(approval)
    assert not trust.ledger.exists()


def test_generic_prepare_presence_rejects_unsafe_intermediate_and_reports_absence(
    tmp_path,
):
    """Generic sidecars use descriptor-relative presence, never ``Path.exists``."""

    from tradingagents.policy.owner_approval import (
        owner_approval_prepare_exists,
        owner_approval_prepare_path,
    )

    parent = tmp_path / "safe-output-parent"
    parent.mkdir()
    os.chmod(parent, 0o700)
    prepare_path = owner_approval_prepare_path(parent / "promotion.json")
    assert owner_approval_prepare_exists(prepare_path) is False

    os.chmod(parent, 0o770)
    with pytest.raises(OwnerApprovalError, match="protected"):
        owner_approval_prepare_exists(prepare_path)
    os.chmod(parent, 0o700)

    backing = tmp_path / "generic-backing"
    parent.rename(backing)
    parent.symlink_to(backing, target_is_directory=True)
    with pytest.raises(OwnerApprovalError, match="protected"):
        owner_approval_prepare_exists(prepare_path)


@pytest.mark.parametrize("surface", ("ledger", "authorization"))
def test_protected_owner_state_reads_serialize_with_their_canonical_locks(
    trust, surface
):
    """Readers cannot observe a ledger or authorization state mid-replace."""

    from tradingagents.policy import owner_approval as owner_module

    if surface == "ledger":
        lock_path = owner_module._ledger_lock_path(trust.ledger)

        def reader() -> bool:
            return owner_module.owner_approval_has_consumption("0" * 64)

        label = "owner approval consumption ledger lock"
    else:
        lock_path = owner_module._risk_envelope_authorization_lock_path()

        def reader() -> object:
            return owner_module.read_risk_envelope_authorization()

        label = "risk envelope authorization lock"
    done = threading.Event()
    results: list[object] = []

    def run_reader() -> None:
        results.append(reader())
        done.set()

    with owner_module._protected_lock(lock_path, label=label, canonical=True):
        worker = threading.Thread(target=run_reader)
        worker.start()
        assert done.wait(0.05) is False
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert done.is_set()
    assert results == ([False] if surface == "ledger" else [None])


def test_risk_envelope_lock_rejects_unsafe_parent_and_reads_no_follow_bytes(tmp_path):
    """The final-send lock shares the no-follow protected-parent protocol."""

    from tradingagents.policy.risk_envelope import (
        read_risk_envelope_bytes_locked,
        risk_envelope_lock,
    )

    parent = tmp_path / "risk-parent"
    parent.mkdir()
    os.chmod(parent, 0o700)
    envelope = parent / "risk.yaml"
    envelope.write_bytes(b"per_name_cap_usd: 50.00\n")

    with risk_envelope_lock(envelope):
        assert read_risk_envelope_bytes_locked(envelope) == envelope.read_bytes()

    os.chmod(parent, 0o770)
    with pytest.raises(ValueError, match="protected path"), risk_envelope_lock(
        envelope
    ):
        pass


def test_malformed_trust_anchor_refuses(tmp_path, monkeypatch, trust):
    approval = _sign(trust)
    anchor = tmp_path / "bad.hex"
    anchor.write_text("zzzz-not-hex\n", encoding="utf-8")
    monkeypatch.setattr(
        "tradingagents.policy.owner_approval.canonical_owner_trust_anchor_path",
        lambda: anchor,
    )

    with pytest.raises(OwnerApprovalError, match="trust anchor"):
        _verify(approval)


@pytest.mark.parametrize(
    "mutate",
    [
        {"schema_version": 2},
        {"kind": "tradingagents.owner_approval.v0"},
        {"unexpected_field": "x"},
        {"action": KeyError},
        {"issued_by": "strategy_learning"},
        {"signature": KeyError},
        {"risk_envelope_binding": KeyError},
        {"ttl_minutes": "30"},
        {"ttl_minutes": 0},
        {"ttl_minutes": 91},
        {"approval_id": "0" * 64},
        {"policy_fingerprint_sha256": "not-a-digest"},
    ],
)
def test_structurally_invalid_artifacts_fail_closed(trust, mutate):
    approval = _sign(trust, mutate=mutate)
    with pytest.raises(OwnerApprovalError):
        _verify(approval)


def test_non_object_and_corrupt_payloads_fail_closed(trust):
    for payload in ("[]", '"approval"', "{", ""):
        with pytest.raises(OwnerApprovalError):
            _verify(payload)


def test_tampered_body_breaks_digest_and_signature(trust):
    approval = _sign(trust)
    tampered = copy.deepcopy(approval)
    tampered["subject"]["sleeves"].append("second-sleeve")

    with pytest.raises(OwnerApprovalError):
        _verify(tampered)


def test_signature_from_a_different_key_fails_closed(trust):
    """Swapping only the claimed anchor-key digest to a distinct correctly
    derived digest must deny, without touching global resolver state."""

    from tests._owner_approval_testing import owner_signing_keypair

    approval = _sign(trust)
    other_public_hex, _other_private = owner_signing_keypair(b"other-anchor-seed")
    approval["signature"]["public_key_sha256"] = hashlib.sha256(
        bytes.fromhex(other_public_hex)
    ).hexdigest()

    with pytest.raises(OwnerApprovalError):
        _verify(approval)

    assert not trust.ledger.exists()


def test_arbitrary_alternate_key_cannot_self_authorize(trust):
    """An attacker keypair cannot self-authorize while the canonical anchor
    belongs to the real owner key: the signature block binds the artifact to
    the anchor key digest and Ed25519 verification refuses anything else."""

    from tests._owner_approval_testing import owner_signing_keypair

    attacker_public_hex, attacker_private_hex = owner_signing_keypair(
        b"attacker-seed"
    )
    attacker_anchor_digest = hashlib.sha256(
        bytes.fromhex(attacker_public_hex)
    ).hexdigest()

    # A fully attacker-signed artifact (fresh body + signature under the
    # attacker key, claiming the attacker digest) fails because the
    # canonical anchor digest differs.
    forged = _sign(trust)
    body = {
        k: v for k, v in forged.items() if k not in ("signature", "approval_id")
    }
    encoded = canonical_json_bytes(body)
    attacker_signer = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(attacker_private_hex)
    )
    forged["approval_id"] = hashlib.sha256(encoded).hexdigest()
    forged["signature"] = {
        "algorithm": "ed25519",
        "public_key_sha256": attacker_anchor_digest,
        "value": attacker_signer.sign(encoded).hex(),
    }

    with pytest.raises(OwnerApprovalError, match="local trust anchor"):
        _verify(forged)
    assert not trust.ledger.exists()


def test_alternate_ledger_or_repo_root_cannot_authorize(tmp_path, trust, monkeypatch):
    """Pointing an alternate ledger file or repo root anywhere else cannot
    make public verification permit: public APIs take no such arguments."""

    approval = _sign(trust)
    _verify(approval)  # consumes in the canonical ledger

    stray = tmp_path / "stray-ledger.jsonl"
    stray.write_text("", encoding="utf-8")

    # Even a completely empty alternate ledger is irrelevant: replay still
    # consults only the canonical ledger and denies.
    with pytest.raises(OwnerApprovalError, match="already used"):
        _verify(approval)
    assert stray.read_text() == ""

    # default_policy_fingerprint is zero-argument by design.
    with pytest.raises(TypeError):
        default_policy_fingerprint(tmp_path)  # type: ignore[call-arg]


def test_flipped_signature_byte_fails_closed(trust):
    approval = _sign(trust)
    raw = bytearray(bytes.fromhex(approval["signature"]["value"]))
    raw[5] ^= 0x01
    approval["signature"]["value"] = bytes(raw).hex()

    with pytest.raises(OwnerApprovalError, match="signature"):
        _verify(approval)


def test_expired_future_and_non_canonical_time_fail_closed(trust):
    expired = _sign(trust, issued_at=NOW - datetime.timedelta(minutes=45), ttl_minutes=30)
    with pytest.raises(OwnerApprovalError, match="expired"):
        _verify(expired)

    future = _sign(trust, issued_at=NOW + datetime.timedelta(minutes=1), ttl_minutes=30)
    with pytest.raises(OwnerApprovalError, match="future"):
        _verify(future)

    naive = _sign(trust, issued_at=NOW.replace(tzinfo=None), ttl_minutes=30)
    with pytest.raises(OwnerApprovalError):
        _verify(naive)


def test_ttl_window_mismatch_fails_closed(trust):
    approval = _sign(trust, ttl_minutes=30)
    approval["expires_at"] = (
        datetime.datetime.fromisoformat(approval["issued_at"])
        + datetime.timedelta(minutes=31)
    ).isoformat(timespec="seconds")
    body = {k: v for k, v in approval.items() if k not in ("signature", "approval_id")}
    encoded = canonical_json_bytes(body)
    signer = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(trust.private_hex))
    approval["approval_id"] = hashlib.sha256(encoded).hexdigest()
    approval["signature"]["value"] = signer.sign(encoded).hex()

    with pytest.raises(OwnerApprovalError, match="window"):
        _verify(approval)


def test_wrong_target_action_fails_closed(trust):
    approval = _sign(trust, action=ActionClass.RISK_ENVELOPE_EXPANSION.value)
    with pytest.raises(OwnerApprovalError, match="action"):
        _verify(approval)


def test_source_subject_policy_and_envelope_mismatch_fail_closed(trust):
    stale_policy = _sign(trust, policy_fingerprint_sha256="f" * 64)
    with pytest.raises(OwnerApprovalError, match="policy"):
        _verify(stale_policy)

    approval = _sign(trust)
    with pytest.raises(OwnerApprovalError, match="subject"):
        _verify(approval, subject={"kind": "something_else"})
    with pytest.raises(OwnerApprovalError, match="source"):
        _verify(approval, source_binding={"tournament_id": "other"})
    with pytest.raises(OwnerApprovalError, match="envelope"):
        _verify(approval, risk_envelope_sha256="1" * 64)
    with pytest.raises(OwnerApprovalError, match="envelope"):
        _verify(approval, risk_envelope_ref="config/other.yaml")


def test_ledger_corruption_or_unwritable_ledger_fails_closed(trust):
    ledger = trust.ledger
    first = _sign(trust)
    _verify(first)

    lines = ledger.read_text(encoding="utf-8").splitlines()
    ledger.write_text("\n".join([*lines, "{corrupt"]), encoding="utf-8")

    second = _sign(trust)
    with pytest.raises(OwnerApprovalError, match="ledger"):
        _verify(second)


def test_default_policy_fingerprint_binds_full_enforcement_surface():
    from tradingagents.policy.owner_approval import _POLICY_FINGERPRINT_FILES

    repo_root = Path(__file__).resolve().parents[1]
    manifest_files = list(_POLICY_FINGERPRINT_FILES)
    expected = hashlib.sha256(
        "".join(
            f"{name}:{hashlib.sha256((repo_root / name).read_bytes()).hexdigest()}\n"
            for name in manifest_files
        ).encode("utf-8")
    ).hexdigest()
    fingerprint = default_policy_fingerprint()
    assert fingerprint == expected
    # The manifest must cover the direct owner-authority enforcement modules.
    for required in (
        "tradingagents/policy/owner_approval.py",
        "tradingagents/policy/live_gate.py",
        "tradingagents/policy/risk_envelope.py",
        "tradingagents/policy/order_rate_limit.py",
        "tradingagents/brokers/alpaca_supervisor.py",
        "tradingagents/brokers/alpaca.py",
        "tradingagents/brokers/supervisor/types.py",
        "tradingagents/execution/authorized_normal_trade_intent.py",
        "tradingagents/execution/reconcile.py",
        "config/autonomous_firm.json",
        "cli/main.py",
    ):
        assert required in manifest_files


@pytest.mark.parametrize(
    "relative",
    [
        "tradingagents/policy/risk_envelope.py",
        "tradingagents/brokers/alpaca.py",
        "tradingagents/execution/authorized_normal_trade_intent.py",
        "tradingagents/execution/reconcile.py",
    ],
)
def test_manifest_file_change_alters_fingerprint_and_invalidates_artifact(
    tmp_path, monkeypatch, trust, relative
):
    """Changing one manifest file invalidates an artifact signed before it."""

    from tradingagents.policy import owner_approval as owner_approval_module
    from tradingagents.policy.owner_approval import _POLICY_FINGERPRINT_FILES

    approval = _sign(trust)
    real_root = Path(__file__).resolve().parents[1]
    isolated_root = tmp_path / "fingerprint-root"
    for relative in _POLICY_FINGERPRINT_FILES:
        destination = isolated_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((real_root / relative).read_bytes())
    monkeypatch.setattr(
        owner_approval_module,
        "canonical_repo_root",
        lambda: isolated_root,
    )

    # The byte-identical isolated tree keeps the original fingerprint valid.
    _verify(approval, consume=False)

    target = isolated_root / relative
    target.write_bytes(target.read_bytes() + b"\n# fingerprint mutation\n")
    assert default_policy_fingerprint() != approval["policy_fingerprint_sha256"]
    with pytest.raises(OwnerApprovalError, match="policy"):
        _verify(approval, consume=False)


def test_no_default_key_credential_or_approval_exists_in_checkout():
    repo_root = Path(__file__).parents[1]
    assert not (repo_root / "config/owner_approval_public_key.hex").exists()
    assert not (repo_root / "results/policy/owner_approval_consumption.jsonl").exists()


def test_privileged_charter_actions_require_owner_approval():
    for action in (ActionClass.LIVE_PROMOTION, ActionClass.RISK_ENVELOPE_EXPANSION):
        verdict = authority_for(action)
        assert verdict.allowed is False
        assert verdict.human_required is True
        assert verdict.owner_role == "account_owner"
        assert requires_owner_approval(action) is True


def test_autonomous_charter_actions_stay_machine_operable():
    autonomous = {
        ActionClass.TRADE_DECISION,
        ActionClass.STRATEGY_CHANGE,
        ActionClass.RISK_CHANGE,
        ActionClass.PROMOTION_CHANGE,
        ActionClass.FREEZE,
        ActionClass.REPAIR,
        ActionClass.VERIFY,
        ActionClass.REARM_REQUEST,
        ActionClass.REARM_ISSUE,
        ActionClass.ORDER_SUBMIT,
    }
    for action in autonomous:
        verdict = authority_for(action)
        assert verdict.allowed is True
        assert verdict.human_required is False
        assert requires_owner_approval(action) is False
    assert OWNER_APPROVAL_KIND == "tradingagents.owner_approval.v1"
