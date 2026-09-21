"""Isolated owner-approval test tooling.

This module exists ONLY for tests. It signs artifacts with a throwaway
Ed25519 key so production code can stay verify-only: no signing capability,
no private key, and no default approval ever ships in ``tradingagents``.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

DEFAULT_TEST_ISSUED_AT = datetime(2026, 6, 3, 15, 0, tzinfo=timezone.utc)
DEFAULT_POLICY_FINGERPRINT = "f" * 64
DEFAULT_ENVELOPE_REF = "config/risk_envelope.yaml"
DEFAULT_ENVELOPE_SHA256 = "e" * 64


def owner_signing_keypair(seed: bytes) -> tuple[str, str]:
    """Return (public_key_hex_text, private_seed_hex_text) for tests."""

    material = hashlib.sha256(seed).digest()
    private_key = Ed25519PrivateKey.from_private_bytes(material)
    public_hex = (
        private_key.public_key()
        .public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
        .hex()
    )
    return public_hex, material.hex()


def _private_key(material_hex: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(material_hex))


def owner_public_key_sha256_from_private(private_material_hex: str) -> str:
    public_hex = (
        _private_key(private_material_hex)
        .public_key()
        .public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
        .hex()
    )
    return hashlib.sha256(bytes.fromhex(public_hex)).hexdigest()


def owner_sign(private_seed_hex: str, message: bytes) -> str:
    return _private_key(private_seed_hex).sign(message).hex()


def canonical_json_bytes(payload) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def write_anchor(
    directory: Path, *, seed: bytes
) -> tuple[Path, str]:
    """Write a throwaway anchor under ``directory``; seed is required."""
    directory.mkdir(parents=True, exist_ok=True)
    public_hex, private_hex = owner_signing_keypair(seed)
    anchor = directory / "owner_approval_public_key.hex"
    anchor.write_text(public_hex + "\n", encoding="utf-8")
    return anchor, private_hex


def anchor_public_key_sha256(anchor_text: str) -> str:
    return hashlib.sha256(bytes.fromhex(anchor_text.strip())).hexdigest()


def build_owner_approval(
    *,
    private_key_hex: str,
    action: str,
    issued_at: datetime | None = None,
    ttl_minutes: int = 30,
    subject: dict | None = None,
    source_binding: dict | None = None,
    policy_fingerprint_sha256: str | None = None,
    risk_envelope_ref: str = DEFAULT_ENVELOPE_REF,
    risk_envelope_sha256: str = DEFAULT_ENVELOPE_SHA256,
    public_key_sha256: str | None = None,
    mutate: dict | None = None,
) -> dict:
    moment = issued_at or DEFAULT_TEST_ISSUED_AT
    if policy_fingerprint_sha256 is None:
        from tradingagents.policy.owner_approval import default_policy_fingerprint

        policy_fingerprint_sha256 = default_policy_fingerprint()
    body = {
        "schema_version": 1,
        "kind": "tradingagents.owner_approval.v1",
        "action": action,
        "issued_by": "account_owner",
        "issued_at": moment.isoformat(timespec="seconds"),
        "expires_at": (moment + timedelta(minutes=ttl_minutes)).isoformat(
            timespec="seconds"
        ),
        "ttl_minutes": ttl_minutes,
        "subject": subject or {},
        "source_binding": source_binding or {},
        "policy_fingerprint_sha256": policy_fingerprint_sha256,
        "risk_envelope_binding": {
            "ref": risk_envelope_ref,
            "sha256": risk_envelope_sha256,
        },
    }
    encoded_body = canonical_json_bytes(body)
    artifact = {**body, "approval_id": hashlib.sha256(encoded_body).hexdigest()}
    if public_key_sha256 is None:
        public_key_sha256 = owner_public_key_sha256_from_private(private_key_hex)
    artifact["signature"] = {
        "algorithm": "ed25519",
        "public_key_sha256": public_key_sha256,
        "value": owner_sign(private_key_hex, encoded_body),
    }
    if mutate:
        for key, value in mutate.items():
            if value is KeyError:
                artifact.pop(key, None)
            else:
                artifact[key] = value
    return artifact


def approval_boundary_kwargs(approval: dict, *, anchor: Path, ledger: Path) -> dict:
    return {
        "owner_approval": approval,
        "owner_approval_anchor_path": anchor,
        "owner_approval_ledger_path": ledger,
    }


def install_isolated_owner_trust(monkeypatch, directory, *, seed: bytes):
    """Redirect the canonical protected trust resolvers into a temp directory.

    ``seed`` is explicit-required (no deterministic default ships here): every
    test module supplies its own distinct seed so keys are never shared across
    suites, and production never sees any of them.

    Narrowly scoped test-only substitution: production resolution remains
    canonical, but its *private trusted-account-root seam* points to the
    given secure disposable account root.  This keeps the tests honest about
    the production ``.config``/``.local/state`` layout and filesystem checks.
    The anchor and ledger live OUTSIDE any checkout; no key ships by default.
    Returns a handle with ``anchor``, ``ledger``, and ``private_hex`` so tests
    can sign genuine artifacts under exactly the redirected trust root.
    """

    from tradingagents.policy import live_gate as live_gate_module
    from tradingagents.policy import owner_approval as owner_module

    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    config_root = directory / ".config" / "tradingagents" / "owner-approval"
    state_root = directory / ".local" / "state" / "tradingagents"
    for protected_dir in (
        directory / ".config",
        directory / ".config" / "tradingagents",
        config_root,
        directory / ".local",
        directory / ".local" / "state",
        state_root,
    ):
        protected_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(protected_dir, 0o700)
    authorization = state_root / "risk_envelope_authorization.json"
    public_hex, private_hex = owner_signing_keypair(seed)
    anchor = config_root / "owner_approval_public_key.hex"
    anchor.write_text(public_hex + "\n", encoding="utf-8")
    os.chmod(anchor, 0o600)
    ledger = state_root / "owner_approval_consumption.jsonl"

    monkeypatch.setattr(owner_module, "_trusted_account_root", lambda: directory)
    # Historical fixture timestamps must opt in through a private policy seam,
    # never the public live-gate ``now`` parameter.  Follow the already
    # monkeypatchable owner-policy seam dynamically so callers that establish
    # a deterministic test authority moment keep both fresh-verification
    # paths aligned without altering production behavior.
    monkeypatch.setattr(
        live_gate_module,
        "_owner_approval_authority_utc_now",
        lambda: owner_module._owner_approval_authority_utc_now(),
    )

    class _Handle:
        pass

    handle = _Handle()
    handle.anchor = anchor
    handle.ledger = ledger
    handle.authorization = authorization
    handle.private_hex = private_hex
    return handle


def build_risk_envelope_expansion_approval(
    private_key_hex: str,
    *,
    ref: str,
    sha256: str,
    previous_sha256: str | None = None,
    issued_at=None,
):
    """Test-only artifact bound to the exact risk_envelope_expansion scope."""

    subject = {
        "kind": "risk_envelope_expansion",
        "ref": ref,
        "sha256": sha256,
        "previous_sha256": previous_sha256 or "",
    }
    return build_owner_approval(
        private_key_hex=private_key_hex,
        action="risk_envelope_expansion",
        issued_at=issued_at,
        ttl_minutes=30,
        subject=subject,
        source_binding={"gate": "normal_live_admission"},
        risk_envelope_ref=ref,
        risk_envelope_sha256=sha256,
    )
