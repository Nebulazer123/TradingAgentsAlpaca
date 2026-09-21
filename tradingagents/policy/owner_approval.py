"""Owner-approval artifact verification for privileged transitions.

The account owner is the only source of authority for entering live
eligibility, promotion into live, normal-live activation, capital expansion,
or risk-envelope expansion.  This module verifies a separately owner-issued,
current, signed approval artifact and durably records single use.  It can
never manufacture authority: there is no signing capability here, no default
key, and every failure mode (missing trust anchor, malformed artifact, bad
signature or digest, expired or future issuance, replayed use, wrong action,
subject, source, policy, or risk-envelope binding) refuses closed.

The artifact schema is exact:

    {
      "schema_version": 1,
      "kind": "tradingagents.owner_approval.v1",
      "approval_id": "<sha256 of canonical body>",
      "action": "<ActionClass value>",
      "issued_by": "account_owner",
      "issued_at": "<canonical UTC +00:00 whole seconds>",
      "expires_at": "<canonical UTC +00:00 whole seconds>",
      "ttl_minutes": <int 1..90>,
      "subject": {..exact requested scope facts..},
      "source_binding": {..exact caller source facts..},
      "policy_fingerprint_sha256": "<sha256>",
      "risk_envelope_binding": {"ref": "...", "sha256": "<sha256>"},
      "signature": {"algorithm": "ed25519",
                    "public_key_sha256": "<sha256 of anchor key>",
                    "value": "<hex ed25519 signature over canonical body>"}
    }

The canonical body is the artifact JSON with sorted keys and compact
separators excluding ``signature`` and ``approval_id``; ``approval_id`` is
its SHA-256 and the Ed25519 signature covers exactly those bytes.
"""

from __future__ import annotations

import datetime
import fcntl
import hashlib
import json
import os
import pwd
import secrets
import stat
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

OWNER_APPROVAL_SCHEMA_VERSION = 1
OWNER_APPROVAL_KIND = "tradingagents.owner_approval.v1"
OWNER_APPROVAL_SIGNING_ALGORITHM = "ed25519"
OWNER_APPROVED_ISSUER = "account_owner"
MIN_OWNER_APPROVAL_TTL_MINUTES = 1
MAX_OWNER_APPROVAL_TTL_MINUTES = 90

# Deliberately explicit deterministic manifest of every source/config file
# that enforces or feeds the owner-approval and authority boundary — charter,
# authority resolution, verification, ledger I/O, both go-live gates, all
# promotion writers, the supervisor admission/commit chain, and the CLI
# command that accepts owner artifacts.
_POLICY_FINGERPRINT_FILES = (
    "config/autonomous_firm.json",
    "cli/main.py",
    "tradingagents/orchestration/authority.py",
    "tradingagents/orchestration/recovery.py",
    "tradingagents/orchestration/self_heal.py",
    "tradingagents/policy/owner_approval.py",
    "tradingagents/policy/io.py",
    "tradingagents/policy/live_gate.py",
    "tradingagents/policy/live_control.py",
    "tradingagents/policy/risk_envelope.py",
    "tradingagents/policy/order_rate_limit.py",
    "tradingagents/policy/promotion.py",
    "tradingagents/policy/promotion_sync.py",
    "tradingagents/policy/strategy_promotion_sync.py",
    "tradingagents/brokers/alpaca.py",
    "tradingagents/brokers/alpaca_supervisor.py",
    "tradingagents/brokers/supervisor/types.py",
    "tradingagents/execution/authorized_normal_trade_intent.py",
    "tradingagents/execution/reconcile.py",
)

_LEDGER_SCHEMA_VERSION = 1
_LEDGER_FIELDS = (
    "schema_version",
    "approval_id",
    "action",
    "purpose",
    "transaction_binding_sha256",
    "consumed_at",
)
_PREPARED_LEDGER_FIELDS = _LEDGER_FIELDS + (
    "prepared_transaction_binding_sha256",
)


class OwnerApprovalError(ValueError):
    """An owner-approval artifact did not prove current, scoped authority."""


_EXACT_EXPIRED_RECOVERY_APPROVAL_ID: ContextVar[str | None] = ContextVar(
    "exact_expired_recovery_approval_id", default=None
)


def _owner_approval_authority_utc_now() -> datetime.datetime:
    """Return the policy-owned current UTC authority clock.

    Public caller timestamps are evidence or deterministic-output inputs, not
    a capability to revive an expired, unconsumed owner signature.  Tests may
    patch this private no-argument seam without exposing it through a runtime
    or CLI parameter.
    """

    return datetime.datetime.now(tz=datetime.timezone.utc).replace(microsecond=0)


def _trusted_account_root() -> Path:
    """Return the effective account's OS-owned home directory.

    ``HOME`` is caller-controlled process environment, so it is never an
    authority root.  Tests may replace this *private* seam with a secure
    disposable account root; production always derives it from the effective
    UID's passwd record.
    """

    try:
        return Path(pwd.getpwuid(os.geteuid()).pw_dir)
    except (KeyError, OSError) as exc:
        raise OwnerApprovalError(
            "owner approval cannot determine the effective account root"
        ) from exc


def canonical_repo_root() -> Path:
    """Root of the loaded source checkout that owns enforcement."""

    return Path(__file__).resolve().parents[2]


def canonical_risk_envelope_authorization_path() -> Path:
    """Protected stored state for the currently authorized risk envelope.

    Records the exact envelope ref/SHA-256 that a consumed
    ``risk_envelope_expansion`` approval authorized.  It deliberately lives
    outside every checkout so a source-tree write cannot manufacture runtime
    authority.  Tests may monkeypatch this resolver with temp equivalents.
    Absence means no expansion has ever been authorized.
    """

    return (
        _trusted_account_root()
        / ".local"
        / "state"
        / "tradingagents"
        / "risk_envelope_authorization.json"
    )


def canonical_owner_trust_anchor_path() -> Path:
    """External protected owner anchor under the account config root.

    Lives OUTSIDE the checkout so source-tree writes can never mint trust.
    No key ships by default; absence refuses every privileged transition.
    Tests may monkeypatch this resolver with temp equivalents.
    """

    return (
        _trusted_account_root()
        / ".config"
        / "tradingagents"
        / "owner-approval"
        / "owner_approval_public_key.hex"
    )


def canonical_owner_consumption_ledger_path() -> Path:
    """External protected single-use consumption ledger under state root."""

    return (
        _trusted_account_root()
        / ".local"
        / "state"
        / "tradingagents"
        / "owner_approval_consumption.jsonl"
    )


def _protected_path_error(label: str, detail: str) -> OwnerApprovalError:
    return OwnerApprovalError(f"{label} protected path is unsafe: {detail}")


def _absolute_lexical_path(path: str | Path) -> Path:
    """Absolute lexical path without resolving (and thereby following) links."""

    return Path(os.path.abspath(os.fspath(path)))


_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _validate_protected_directory_state(
    metadata: os.stat_result, *, label: str, canonical: bool
) -> None:
    """Validate a directory already pinned by an open descriptor."""

    if not stat.S_ISDIR(metadata.st_mode):
        raise _protected_path_error(label, "directory component is not a directory")
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise _protected_path_error(label, "directory component is group/other writable")
    if canonical:
        if metadata.st_uid != os.geteuid():
            raise _protected_path_error(
                label, "canonical directory is not owned by effective uid"
            )
    elif metadata.st_uid not in {0, os.geteuid()}:
        raise _protected_path_error(
            label, "generic prepare directory has an unexpected owner"
        )


def _validate_protected_file_state(
    metadata: os.stat_result, *, label: str
) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise _protected_path_error(label, "final path is not a regular file")
    if metadata.st_uid != os.geteuid():
        raise _protected_path_error(label, "file is not owned by effective uid")
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise _protected_path_error(label, "file is group/other writable")


def _open_directory_component(
    parent_fd: int,
    name: str,
    *,
    label: str,
    canonical: bool,
    create: bool,
) -> int:
    """Open exactly one child directory through its already-pinned parent."""

    flags = os.O_RDONLY | _DIRECTORY | _NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            raise _protected_path_error(label, f"required directory is missing: {name}") from None
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            descriptor = os.open(name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise _protected_path_error(
                label, f"cannot create protected directory {name}: {exc}"
            ) from exc
    except OSError as exc:
        raise _protected_path_error(
            label, f"cannot safely open directory component {name}: {exc}"
        ) from exc
    try:
        _validate_protected_directory_state(
            os.fstat(descriptor), label=label, canonical=canonical
        )
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _open_absolute_directory(
    path: Path,
    *,
    label: str,
    canonical_final: bool,
) -> int:
    """Walk an absolute directory without following any component symlink."""

    absolute = _absolute_lexical_path(path)
    if not absolute.is_absolute():  # Defensive: _absolute_lexical_path promises this.
        raise _protected_path_error(label, "directory path is not absolute")
    try:
        descriptor = os.open(absolute.anchor, os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
    except OSError as exc:
        raise _protected_path_error(label, f"cannot open filesystem root: {exc}") from exc
    try:
        _validate_protected_directory_state(
            os.fstat(descriptor), label=label, canonical=False
        )
        for index, component in enumerate(absolute.parts[1:]):
            child = _open_directory_component(
                descriptor,
                component,
                label=label,
                canonical=canonical_final and index == len(absolute.parts) - 2,
                create=False,
            )
            os.close(descriptor)
            descriptor = child
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


@contextmanager
def _protected_parent_fd(
    path: str | Path,
    *,
    label: str,
    canonical: bool,
    create: bool,
):
    """Yield a pinned parent descriptor and final basename for one safe file.

    Every component is opened through its parent with ``O_DIRECTORY`` and
    ``O_NOFOLLOW``.  Canonical account-state components are required to be
    owned by the effective UID; generic sibling prepares also reject writable
    or link-based intermediate redirection while allowing safe root-owned
    system ancestors.
    """

    target = _absolute_lexical_path(path)
    if target.name in {"", ".", ".."}:
        raise _protected_path_error(label, "final path name is unsafe")
    parent = target.parent
    if canonical:
        root = _absolute_lexical_path(_trusted_account_root())
        try:
            relative_parent = parent.relative_to(root)
        except ValueError as exc:
            raise _protected_path_error(
                label, f"path escapes the effective account root: {target}"
            ) from exc
        descriptor = _open_absolute_directory(
            root, label=label, canonical_final=True
        )
        parts = relative_parent.parts
    else:
        descriptor = _open_absolute_directory(
            Path(parent.anchor), label=label, canonical_final=False
        )
        parts = parent.parts[1:]
    try:
        for component in parts:
            child = _open_directory_component(
                descriptor,
                component,
                label=label,
                canonical=canonical,
                create=create,
            )
            os.close(descriptor)
            descriptor = child
        yield descriptor, target.name, target
    finally:
        os.close(descriptor)


def _validate_protected_open_file(
    descriptor: int, *, label: str, path: Path
) -> None:
    try:
        _validate_protected_file_state(os.fstat(descriptor), label=label)
    except OSError as exc:
        raise _protected_path_error(label, f"cannot stat opened file {path}: {exc}") from exc


def _protected_file_present(
    path: str | Path, *, label: str, canonical: bool
) -> bool:
    """Return safe presence without a path-following ``Path.exists`` check."""

    with _protected_parent_fd(
        path, label=label, canonical=canonical, create=False
    ) as (parent_fd, name, _target):
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _protected_path_error(label, f"cannot inspect final file: {exc}") from exc
        _validate_protected_file_state(metadata, label=label)
        return True


def _read_protected_text(
    path: str | Path,
    *,
    label: str,
    canonical: bool,
    missing_ok: bool = False,
) -> str | None:
    try:
        with _protected_parent_fd(
            path, label=label, canonical=canonical, create=False
        ) as (parent_fd, name, target):
            try:
                descriptor = os.open(
                    name, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd
                )
            except FileNotFoundError:
                if missing_ok:
                    return None
                raise
            except OSError as exc:
                raise _protected_path_error(
                    label, f"cannot safely open {target}: {exc}"
                ) from exc
            try:
                _validate_protected_open_file(descriptor, label=label, path=target)
                with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                    descriptor = -1
                    return handle.read()
            except UnicodeError as exc:
                raise _protected_path_error(
                    label, f"is not UTF-8 text: {target}"
                ) from exc
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
    except OwnerApprovalError as exc:
        if missing_ok and "required directory is missing" in str(exc):
            return None
        raise


def _write_protected_text(
    path: str | Path,
    text: str,
    *,
    label: str,
    canonical: bool,
) -> None:
    """Descriptor-relative atomic replace without following a path component."""

    data = text.encode("utf-8")
    with _protected_parent_fd(
        path, label=label, canonical=canonical, create=True
    ) as (parent_fd, name, target):
        try:
            existing = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        except OSError as exc:
            raise _protected_path_error(label, f"cannot inspect {target}: {exc}") from exc
        if existing is not None:
            _validate_protected_file_state(existing, label=label)
        temporary_name = f".{name}.tmp-{os.getpid()}-{secrets.token_hex(12)}"
        descriptor = -1
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            _validate_protected_open_file(descriptor, label=label, path=target)
            offset = 0
            while offset < len(data):
                offset += os.write(descriptor, data[offset:])
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(
                temporary_name,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            check_fd = os.open(name, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)
            try:
                _validate_protected_open_file(check_fd, label=label, path=target)
            finally:
                os.close(check_fd)
            os.fsync(parent_fd)
        except OSError as exc:
            raise _protected_path_error(label, f"cannot atomically write {target}: {exc}") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise _protected_path_error(
                    label, f"cannot remove temporary file for {target}: {exc}"
                ) from exc


def _append_protected_text(
    path: str | Path, text: str, *, label: str, canonical: bool
) -> None:
    with _protected_parent_fd(
        path, label=label, canonical=canonical, create=True
    ) as (parent_fd, name, target):
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | _NOFOLLOW
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=parent_fd)
        except OSError as exc:
            raise _protected_path_error(label, f"cannot safely open {target}: {exc}") from exc
        try:
            _validate_protected_open_file(descriptor, label=label, path=target)
            data = text.encode("utf-8")
            offset = 0
            while offset < len(data):
                offset += os.write(descriptor, data[offset:])
            os.fsync(descriptor)
        except (OSError, UnicodeError) as exc:
            raise _protected_path_error(label, f"cannot append {target}: {exc}") from exc
        finally:
            os.close(descriptor)


@contextmanager
def _protected_lock(
    path: str | Path, *, label: str, canonical: bool
):
    with _protected_parent_fd(
        path, label=label, canonical=canonical, create=True
    ) as (parent_fd, name, lock_path):
        flags = os.O_CREAT | os.O_RDWR | _NOFOLLOW
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=parent_fd)
        except OSError as exc:
            raise _protected_path_error(
                label, f"cannot safely open lock {lock_path}: {exc}"
            ) from exc
        try:
            _validate_protected_open_file(descriptor, label=label, path=lock_path)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield lock_path
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _unlink_protected_file(
    path: str | Path, *, label: str, canonical: bool
) -> None:
    with _protected_parent_fd(
        path, label=label, canonical=canonical, create=False
    ) as (parent_fd, name, target):
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise _protected_path_error(label, f"cannot inspect {target}: {exc}") from exc
        _validate_protected_file_state(metadata, label=label)
        try:
            os.unlink(name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except OSError as exc:
            raise _protected_path_error(label, f"cannot remove {target}: {exc}") from exc


@dataclass(frozen=True)
class OwnerTrustAnchor:
    public_key_hex: str
    public_key_sha256: str
    source_path: str


@dataclass(frozen=True)
class OwnerApprovalVerdict:
    allowed: bool
    action: str
    approval_id: str
    purpose: str
    reason: str


def _is_sha256_hex(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical_json_bytes(payload) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _load_trust_anchor_at(path: str | Path) -> OwnerTrustAnchor:
    """Private primitive: parse an ed25519 public-key anchor at an explicit path.

    Public verification always resolves the canonical anchor; only tests may
    reach this primitive, and production callers cannot select the path.
    """

    anchor_path = _absolute_lexical_path(path)
    try:
        text = _read_protected_text(
            anchor_path,
            label="owner approval trust anchor",
            canonical=True,
        )
    except FileNotFoundError as exc:
        raise OwnerApprovalError(
            f"owner approval trust anchor is missing at {anchor_path}; "
            "privileged transitions are refused without an owner-issued "
            "public key"
        ) from exc
    except OwnerApprovalError:
        raise
    assert text is not None
    text = text.strip()
    raw: bytes | None = None
    if _is_sha256_hex(text):
        try:
            raw = bytes.fromhex(text)
        except ValueError:
            raw = None
    if raw is None or len(raw) != 32:
        raise OwnerApprovalError(
            "owner approval trust anchor must be a hex ed25519 public key"
        )
    digest = hashlib.sha256(raw).hexdigest()
    try:
        Ed25519PublicKey.from_public_bytes(raw)
    except Exception as exc:
        raise OwnerApprovalError("owner approval trust anchor is not a valid ed25519 public key") from exc
    return OwnerTrustAnchor(
        public_key_hex=text,
        public_key_sha256=digest,
        source_path=str(anchor_path),
    )


def default_policy_fingerprint() -> str:
    """Digest the full authority-enforcement manifest from canonical root.

    Zero-argument by design: callers cannot select the repository root or a
    subset of enforcement files.  The manifest binds every module and config
    file that enforces the owner-approval boundary.
    """

    root = canonical_repo_root()
    lines: list[str] = []
    for name in _POLICY_FINGERPRINT_FILES:
        candidate = root / name
        try:
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        except OSError as exc:
            raise OwnerApprovalError(
                f"owner approval policy fingerprint cannot read {candidate}"
            ) from exc
        lines.append(f"{name}:{digest}\n")
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def requires_owner_approval(action: object) -> bool:
    from tradingagents.orchestration.authority import ActionClass, authority_for

    normalized = action if isinstance(action, ActionClass) else ActionClass(str(action))
    verdict = authority_for(normalized)
    return verdict.human_required is True and verdict.owner_role == OWNER_APPROVED_ISSUER


def _canonical_utc(value: object, *, label: str) -> datetime.datetime:
    if type(value) is not str:
        raise OwnerApprovalError(f"owner approval {label} must be a canonical UTC string")
    parsed: datetime.datetime | None = None
    if value.endswith("+00:00"):
        try:
            candidate = datetime.datetime.fromisoformat(value)
        except ValueError:
            candidate = None
        if candidate is not None and candidate.tzinfo is not None:
            parsed = candidate.astimezone(datetime.timezone.utc)
    if (
        parsed is None
        or parsed.utcoffset() != datetime.timedelta(0)
        or parsed.microsecond
        or parsed.isoformat(timespec="seconds") != value
    ):
        raise OwnerApprovalError(f"owner approval {label} must be canonical UTC (+00:00, whole seconds)")
    return parsed


def _binding_canonical(value: object, *, label: str) -> str:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise OwnerApprovalError(f"owner approval {label} must be an object")
    return _canonical_json_bytes(dict(value)).decode("utf-8")


def _require_exact_fields(artifact: Mapping) -> None:
    required = {
        "schema_version",
        "kind",
        "approval_id",
        "action",
        "issued_by",
        "issued_at",
        "expires_at",
        "ttl_minutes",
        "subject",
        "source_binding",
        "policy_fingerprint_sha256",
        "risk_envelope_binding",
        "signature",
    }
    if set(artifact) != required:
        raise OwnerApprovalError("owner approval artifact fields are invalid")
    if artifact["schema_version"] != OWNER_APPROVAL_SCHEMA_VERSION:
        raise OwnerApprovalError("owner approval schema_version is unsupported")
    if artifact["kind"] != OWNER_APPROVAL_KIND:
        raise OwnerApprovalError("owner approval kind is invalid")
    if artifact["issued_by"] != OWNER_APPROVED_ISSUER:
        raise OwnerApprovalError("owner approval issued_by must be account_owner")
    if type(artifact["ttl_minutes"]) is not int or isinstance(artifact["ttl_minutes"], bool):
        raise OwnerApprovalError("owner approval ttl_minutes must be an integer")
    if not MIN_OWNER_APPROVAL_TTL_MINUTES <= artifact["ttl_minutes"] <= MAX_OWNER_APPROVAL_TTL_MINUTES:
        raise OwnerApprovalError("owner approval ttl_minutes is out of range")
    if not _is_sha256_hex(artifact["approval_id"]) or not _is_sha256_hex(
        artifact["policy_fingerprint_sha256"]
    ):
        raise OwnerApprovalError("owner approval digest fields are invalid")
    if type(artifact["action"]) is not str or not artifact["action"]:
        raise OwnerApprovalError("owner approval action is invalid")


def _verify_structure_at_paths(
    *,
    approval: object,
    expected_action: str,
    subject: Mapping[str, object],
    source_binding: Mapping[str, object],
    trust_anchor_path: str | Path,
    now: datetime.datetime,
    purpose: str,
) -> dict:
    """Private primitive: full structural verification at explicit paths.

    Never touches the consumption ledger.  Public callers must use
    :func:`verify_owner_approval_structure`, which resolves the canonical
    protected trust anchor; no production caller may select these paths.
    """

    if now.tzinfo is None or now.utcoffset() is None:
        raise OwnerApprovalError("owner approval verification requires an aware clock")
    moment = now.astimezone(datetime.timezone.utc)
    if type(purpose) is not str or not purpose:
        raise OwnerApprovalError("owner approval purpose is required")
    expected_subject = _binding_canonical(subject, label="expected subject")
    expected_source = _binding_canonical(source_binding, label="expected source binding")

    if isinstance(approval, (str, Path, bytes)):
        raise OwnerApprovalError("owner approval must be supplied as a parsed object")
    if not isinstance(approval, Mapping):
        raise OwnerApprovalError("owner approval artifact is malformed")
    artifact = dict(approval)
    _require_exact_fields(artifact)

    anchor = _load_trust_anchor_at(trust_anchor_path)
    signature = artifact["signature"]
    if (
        not isinstance(signature, Mapping)
        or set(signature) != {"algorithm", "public_key_sha256", "value"}
        or signature["algorithm"] != OWNER_APPROVAL_SIGNING_ALGORITHM
        or not _is_sha256_hex(signature.get("public_key_sha256"))
    ):
        raise OwnerApprovalError("owner approval signature block is invalid")
    if signature["public_key_sha256"] != anchor.public_key_sha256:
        raise OwnerApprovalError(
            "owner approval was not issued under the local trust anchor"
        )
    body = {
        key: value
        for key, value in artifact.items()
        if key not in ("signature", "approval_id")
    }
    encoded_body = _canonical_json_bytes(body)
    if hashlib.sha256(encoded_body).hexdigest() != artifact["approval_id"]:
        raise OwnerApprovalError("owner approval digest does not match its body")

    issued_at = _canonical_utc(artifact["issued_at"], label="issued_at")
    expires_at = _canonical_utc(artifact["expires_at"], label="expires_at")
    window = datetime.timedelta(minutes=artifact["ttl_minutes"])
    if expires_at - issued_at != window:
        raise OwnerApprovalError("owner approval time window is inconsistent with ttl_minutes")
    if issued_at > moment:
        raise OwnerApprovalError(f"owner approval issuance is in the future: {issued_at.isoformat()}")
    if (
        expires_at <= moment
        and _EXACT_EXPIRED_RECOVERY_APPROVAL_ID.get() != artifact["approval_id"]
    ):
        raise OwnerApprovalError(f"owner approval expired at {expires_at.isoformat()}")

    signature_value = signature["value"]
    if type(signature_value) is not str:
        raise OwnerApprovalError("owner approval signature value is invalid")
    try:
        signature_bytes = bytes.fromhex(signature_value)
    except ValueError as exc:
        raise OwnerApprovalError("owner approval signature value is invalid") from exc
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(anchor.public_key_hex)).verify(
            signature_bytes, encoded_body
        )
    except InvalidSignature as exc:
        raise OwnerApprovalError("owner approval signature is invalid") from exc
    except Exception as exc:
        raise OwnerApprovalError("owner approval signature is unusable") from exc

    if artifact["action"] != expected_action:
        raise OwnerApprovalError(
            f"owner approval action {artifact['action']!r} does not match "
            f"requested {expected_action!r}"
        )
    if _binding_canonical(artifact["subject"], label="subject") != expected_subject:
        raise OwnerApprovalError("owner approval subject does not match the requested scope")
    if _binding_canonical(artifact["source_binding"], label="source_binding") != expected_source:
        raise OwnerApprovalError("owner approval source binding does not match this request")
    if artifact["policy_fingerprint_sha256"] != default_policy_fingerprint():
        raise OwnerApprovalError("owner approval policy fingerprint mismatch")
    envelope = artifact["risk_envelope_binding"]
    if (
        not isinstance(envelope, Mapping)
        or set(envelope) != {"ref", "sha256"}
        or type(envelope.get("ref")) is not str
        or not envelope.get("ref")
        or not _is_sha256_hex(envelope.get("sha256"))
    ):
        raise OwnerApprovalError("owner approval risk envelope binding is invalid")

    return artifact


def verify_owner_approval_structure(
    *,
    approval: object,
    expected_action: str,
    subject: Mapping[str, object],
    source_binding: Mapping[str, object],
    now: datetime.datetime,
    purpose: str,
) -> dict:
    """Canonical structural verification; NEVER consumes.

    Resolves the protected canonical trust anchor internally — callers
    cannot select trust roots, ledgers, repository roots, or policy
    digests.  Returns the parsed artifact so privileged writers can bind
    its ``risk_envelope_binding`` and compute their transaction binding
    before any consuming call.  Consumption requires the complete exact
    transaction binding via :func:`consume_owner_approval`.
    """

    return _verify_structure_at_paths(
        approval=approval,
        expected_action=expected_action,
        subject=subject,
        source_binding=source_binding,
        trust_anchor_path=canonical_owner_trust_anchor_path(),
        now=now,
        purpose=purpose,
    )


def consume_owner_approval(
    *,
    approval_id: str,
    action: str,
    purpose: str,
    transaction_binding_sha256: str,
    prepared_transaction_binding_sha256: str | None = None,
    now: datetime.datetime,
) -> None:
    """Durably record the single permitted use of one approval.

    Uses only the canonical protected consumption ledger.  Callers must
    invoke this only after every binding check has passed, at the final
    successful privilege boundary, and MUST supply the complete exact
    transaction binding.  Any prior recorded use of the same
    ``approval_id`` raises and writes nothing.
    """

    if action == "risk_envelope_expansion":
        raise OwnerApprovalError(
            "risk envelope expansion consumption requires the atomic "
            "authorization transaction"
        )
    if not _is_sha256_hex(transaction_binding_sha256):
        raise OwnerApprovalError(
            "owner approval consumption requires a complete exact "
            "transaction binding (sha256)"
        )
    if now.tzinfo is None or now.utcoffset() is None:
        raise OwnerApprovalError("owner approval consumption requires an aware clock")
    moment = now.astimezone(datetime.timezone.utc)
    _consume_owner_approval(
        canonical_owner_consumption_ledger_path(),
        approval_id=approval_id,
        action=action,
        purpose=purpose,
        transaction_binding_sha256=transaction_binding_sha256,
        prepared_transaction_binding_sha256=prepared_transaction_binding_sha256,
        consumed_at=moment,
    )


def verify_owner_approval(
    *,
    approval: object,
    expected_action: str,
    subject: Mapping[str, object],
    source_binding: Mapping[str, object],
    risk_envelope_ref: str,
    risk_envelope_sha256: str,
    now: datetime.datetime,
    purpose: str,
    consume: bool = True,
) -> OwnerApprovalVerdict:
    """Verify one owner approval against the exact requested scope.

    Every mismatch raises :class:`OwnerApprovalError`; nothing is written
    unless every check passes.  An approval is single use: once its
    ``approval_id`` appears in the consumption ledger, ANY later verification
    — same purpose or not — refuses closed.  With ``consume=False`` the
    ledger is not consulted or extended; privileged writers consume exactly
    when they create their fresh durable transaction, so an existing prepare
    can still support crash-repair inside its own transaction without a new
    grant.
    """

    if type(risk_envelope_ref) is not str or not risk_envelope_ref or not _is_sha256_hex(
        risk_envelope_sha256
    ):
        raise OwnerApprovalError("owner approval envelope expectation is invalid")
    # A public caller may supply ``now`` for non-consuming structural/evidence
    # checks, but it may never rewind a fresh privileged consumption.  Exact
    # prepare-plus-ledger recovery is handled by the narrow context used by
    # the specialized finalizers, not by this public minting surface.
    authority_moment = _owner_approval_authority_utc_now() if consume else now
    artifact = verify_owner_approval_structure(
        approval=approval,
        expected_action=expected_action,
        subject=subject,
        source_binding=source_binding,
        now=authority_moment,
        purpose=purpose,
    )
    envelope = artifact["risk_envelope_binding"]
    if (
        envelope["ref"] != risk_envelope_ref
        or envelope["sha256"] != risk_envelope_sha256
    ):
        raise OwnerApprovalError(
            "owner approval risk envelope binding does not match this request"
        )
    if consume:
        consume_owner_approval(
            approval_id=artifact["approval_id"],
            action=artifact["action"],
            purpose=purpose,
            transaction_binding_sha256=transaction_binding_sha256(
                approval_id=artifact["approval_id"],
                action=artifact["action"],
                purpose=purpose,
                subject=dict(subject),
                risk_envelope_ref=risk_envelope_ref,
                risk_envelope_sha256=risk_envelope_sha256,
            ),
            now=authority_moment,
        )
    return OwnerApprovalVerdict(
        allowed=True,
        action=artifact["action"],
        approval_id=artifact["approval_id"],
        purpose=purpose,
        reason="current owner approval matches the exact requested scope",
    )


def owner_approval_has_consumption(approval_id: str) -> bool:
    """Return True only when the canonical ledger records this approval id."""

    return any(
        entry["approval_id"] == approval_id
        for entry in _read_ledger_entries(canonical_owner_consumption_ledger_path())
    )


def require_prior_consumption_for_commitment_recovery(
    *,
    approval_id: str,
    action: str,
    purpose: str,
    transaction_binding_sha256: str,
    prepared_transaction_binding_sha256: str | None = None,
) -> None:
    """Deny commitment-carried recovery without an exact prior consumption.

    The durable ledger must already record the SAME deterministic approval
    id, action, purpose, and transaction binding for this exact privileged
    transaction before crash recovery may continue without consuming again.
    Binding-agnostic recovery is deliberately unsupported.
    """

    if not _is_sha256_hex(transaction_binding_sha256):
        raise OwnerApprovalError(
            "commitment recovery requires the complete exact owner-approval "
            "transaction binding"
        )
    if (
        prepared_transaction_binding_sha256 is not None
        and not _is_sha256_hex(prepared_transaction_binding_sha256)
    ):
        raise OwnerApprovalError(
            "commitment recovery requires the complete exact prepared "
            "transaction binding"
        )

    for entry in _read_ledger_entries(canonical_owner_consumption_ledger_path()):
        if (
            entry["approval_id"] == approval_id
            and entry["action"] == action
            and entry["purpose"] == purpose
            and entry["transaction_binding_sha256"]
            == transaction_binding_sha256
            and (
                prepared_transaction_binding_sha256 is None
                or entry.get("prepared_transaction_binding_sha256")
                == prepared_transaction_binding_sha256
            )
        ):
            return
    raise OwnerApprovalError(
        "privileged transaction carries no matching prior consumption of "
        "this owner approval (same id, action, purpose, and binding); "
        "recovery is denied"
    )


RISK_ENVELOPE_AUTHORIZATION_SCHEMA_VERSION = 2
_RISK_ENVELOPE_PREPARE_SCHEMA_VERSION = 2
_RISK_ENVELOPE_AUTHORIZATION_FIELDS = {
    "schema_version",
    "risk_envelope_ref",
    "risk_envelope_sha256",
    "risk_envelope_text",
    "approval_id",
    "action",
    "purpose",
    "transaction_binding_sha256",
    "previous_sha256",
    "authorized_at",
    "updated_at",
    "owner_approval",
    "tightening_history",
}
_RISK_ENVELOPE_HISTORY_FIELDS = {
    "sha256",
    "text",
    "transition",
    "recorded_at",
}
_RISK_ENVELOPE_PREPARE_FIELDS = {
    "schema_version",
    "risk_envelope_ref",
    "risk_envelope_sha256",
    "risk_envelope_text",
    "previous_sha256",
    "approval_id",
    "action",
    "purpose",
    "transaction_binding_sha256",
    "transaction_sha256",
    "prepared_transaction_binding_sha256",
    "owner_approval",
    "prepared_at",
}


def canonical_risk_envelope_authorization_prepare_path() -> Path:
    """Sibling crash-recovery intent for one exact envelope authorization."""

    path = canonical_risk_envelope_authorization_path()
    return path.with_name(f".{path.name}.prepare")


def _risk_envelope_authorization_lock_path() -> Path:
    """Canonical lock for authorization state and its recovery sidecar."""

    path = canonical_risk_envelope_authorization_path()
    return path.with_name(f".{path.name}.lock")


def _aware_utc_text(value: datetime.datetime, *, label: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise OwnerApprovalError(f"{label} requires an aware clock")
    return value.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _validate_risk_envelope_snapshot(
    *, text: object, expected_sha256: object
) -> object:
    """Validate exact stored bytes and return their parsed RiskEnvelope."""

    from tradingagents.policy.risk_envelope import load_risk_envelope_text

    if type(text) is not str or not _is_sha256_hex(expected_sha256):
        raise OwnerApprovalError("risk envelope authorization snapshot is malformed")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest != expected_sha256:
        raise OwnerApprovalError(
            "risk envelope authorization snapshot does not match its sha256"
        )
    envelope, issues = load_risk_envelope_text(text)
    if envelope is None or issues:
        raise OwnerApprovalError(
            "risk envelope authorization snapshot is invalid: " + "; ".join(issues)
        )
    return envelope


def _read_current_risk_envelope_snapshot(
    path: str | Path, *, expected_sha256: str
) -> tuple[str, object]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise OwnerApprovalError(
            f"risk envelope is unavailable while binding authority: {exc}"
        ) from exc
    envelope = _validate_risk_envelope_snapshot(
        text=text, expected_sha256=expected_sha256
    )
    return text, envelope


def _validate_risk_envelope_authorization_record(raw: object) -> dict:
    """Require a signed root, exact ledger consumption, and tightening chain."""

    from tradingagents.policy.risk_envelope import is_monotonic_risk_tightening

    if (
        not isinstance(raw, dict)
        or set(raw) != _RISK_ENVELOPE_AUTHORIZATION_FIELDS
        or raw.get("schema_version") != RISK_ENVELOPE_AUTHORIZATION_SCHEMA_VERSION
        or type(raw.get("risk_envelope_ref")) is not str
        or not raw["risk_envelope_ref"].strip()
        or not _is_sha256_hex(raw.get("risk_envelope_sha256"))
        or not _is_sha256_hex(raw.get("approval_id"))
        or raw.get("action") != "risk_envelope_expansion"
        or type(raw.get("purpose")) is not str
        or not _is_sha256_hex(raw.get("transaction_binding_sha256"))
        or not (
            raw.get("previous_sha256") == ""
            or _is_sha256_hex(raw.get("previous_sha256"))
        )
        or type(raw.get("tightening_history")) is not list
        or not raw["tightening_history"]
    ):
        raise OwnerApprovalError("risk envelope authorization record is invalid")

    authorized_at = _canonical_utc(raw["authorized_at"], label="authorized_at")
    updated_at = _canonical_utc(raw["updated_at"], label="updated_at")
    history = raw["tightening_history"]
    previous_envelope = None
    previous_recorded_at = None
    for index, item in enumerate(history):
        if (
            not isinstance(item, dict)
            or set(item) != _RISK_ENVELOPE_HISTORY_FIELDS
            or not _is_sha256_hex(item.get("sha256"))
            or type(item.get("text")) is not str
            or item.get("transition")
            != ("owner_expansion" if index == 0 else "machine_risk_reduction")
        ):
            raise OwnerApprovalError(
                "risk envelope authorization tightening history is invalid"
            )
        recorded_at = _canonical_utc(
            item["recorded_at"], label="tightening_history.recorded_at"
        )
        if index == 0 and recorded_at != authorized_at:
            raise OwnerApprovalError(
                "risk envelope authorization root timestamp is inconsistent"
            )
        if previous_recorded_at is not None and recorded_at < previous_recorded_at:
            raise OwnerApprovalError(
                "risk envelope authorization history clock moved backward"
            )
        current_envelope = _validate_risk_envelope_snapshot(
            text=item["text"], expected_sha256=item["sha256"]
        )
        if previous_envelope is not None and not is_monotonic_risk_tightening(
            previous_envelope, current_envelope
        ):
            raise OwnerApprovalError(
                "risk envelope authorization history contains a risk expansion"
            )
        previous_envelope = current_envelope
        previous_recorded_at = recorded_at

    root = history[0]
    tip = history[-1]
    if (
        raw["risk_envelope_sha256"] != tip["sha256"]
        or raw["risk_envelope_text"] != tip["text"]
        or updated_at
        != _canonical_utc(tip["recorded_at"], label="tightening_history.recorded_at")
    ):
        raise OwnerApprovalError("risk envelope authorization tip is inconsistent")

    subject = risk_envelope_expansion_subject(
        ref=raw["risk_envelope_ref"],
        sha256=root["sha256"],
        previous_sha256=raw["previous_sha256"] or None,
    )
    expected_purpose = f"risk_envelope_expansion:{root['sha256']}"
    if raw["purpose"] != expected_purpose:
        raise OwnerApprovalError("risk envelope authorization purpose is inconsistent")
    parsed = _verify_structure_at_paths(
        approval=raw["owner_approval"],
        expected_action="risk_envelope_expansion",
        subject=subject,
        source_binding={"gate": "normal_live_admission"},
        trust_anchor_path=canonical_owner_trust_anchor_path(),
        now=authorized_at,
        purpose=expected_purpose,
    )
    binding = parsed["risk_envelope_binding"]
    expected_binding = transaction_binding_sha256(
        approval_id=parsed["approval_id"],
        action=parsed["action"],
        purpose=expected_purpose,
        subject=subject,
        risk_envelope_ref=raw["risk_envelope_ref"],
        risk_envelope_sha256=root["sha256"],
    )
    if (
        parsed["approval_id"] != raw["approval_id"]
        or binding["ref"] != raw["risk_envelope_ref"]
        or binding["sha256"] != root["sha256"]
        or expected_binding != raw["transaction_binding_sha256"]
    ):
        raise OwnerApprovalError("risk envelope authorization proof is inconsistent")
    require_prior_consumption_for_commitment_recovery(
        approval_id=raw["approval_id"],
        action=raw["action"],
        purpose=raw["purpose"],
        transaction_binding_sha256=raw["transaction_binding_sha256"],
    )
    return dict(raw)


def _read_risk_envelope_authorization_unlocked() -> dict | None:
    """Read authorization state while its canonical authorization lock is held."""

    try:
        text = _read_protected_text(
            canonical_risk_envelope_authorization_path(),
            label="risk envelope authorization state",
            canonical=True,
            missing_ok=True,
        )
        if text is None:
            return None
        raw = json.loads(text)
        return _validate_risk_envelope_authorization_record(raw)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        OwnerApprovalError,
    ):
        return None


def read_risk_envelope_authorization() -> dict | None:
    """Return a serialized cryptographically and ledger-proven record."""

    with _protected_lock(
        _risk_envelope_authorization_lock_path(),
        label="risk envelope authorization lock",
        canonical=True,
    ):
        return _read_risk_envelope_authorization_unlocked()


def _write_risk_envelope_authorization_unlocked(
    *,
    risk_envelope_ref: str,
    risk_envelope_sha256: str,
    risk_envelope_text: str,
    previous_sha256: str | None,
    owner_approval: Mapping[str, object],
    approval_id: str,
    transaction_binding_sha256: str,
    authorized_at: datetime.datetime,
) -> None:
    """Finalize one prepared, consumed expansion with the auth lock held."""

    moment = _aware_utc_text(authorized_at, label="risk envelope authorization")
    record = {
        "schema_version": RISK_ENVELOPE_AUTHORIZATION_SCHEMA_VERSION,
        "risk_envelope_ref": risk_envelope_ref,
        "risk_envelope_sha256": risk_envelope_sha256,
        "risk_envelope_text": risk_envelope_text,
        "approval_id": approval_id,
        "action": "risk_envelope_expansion",
        "purpose": f"risk_envelope_expansion:{risk_envelope_sha256}",
        "transaction_binding_sha256": transaction_binding_sha256,
        "previous_sha256": previous_sha256 or "",
        "authorized_at": moment,
        "updated_at": moment,
        "owner_approval": dict(owner_approval),
        "tightening_history": [
            {
                "sha256": risk_envelope_sha256,
                "text": risk_envelope_text,
                "transition": "owner_expansion",
                "recorded_at": moment,
            }
        ],
    }
    # A ledger entry without the exact durable risk prepare is never authority
    # to create state.  The caller holds authorization before this nested
    # ledger proof, preserving authorization-state -> owner-ledger order.
    prepared = _read_risk_envelope_prepare_unlocked()
    if (
        prepared is None
        or prepared["risk_envelope_ref"] != risk_envelope_ref
        or prepared["risk_envelope_sha256"] != risk_envelope_sha256
        or prepared["risk_envelope_text"] != risk_envelope_text
        or prepared["previous_sha256"] != (previous_sha256 or "")
        or prepared["approval_id"] != approval_id
        or prepared["transaction_binding_sha256"] != transaction_binding_sha256
        or prepared["owner_approval"] != dict(owner_approval)
        or not _has_exact_owner_consumption(prepared)
    ):
        raise OwnerApprovalError(
            "risk envelope authorization finalization requires the exact "
            "durable prepare and matching canonical ledger consumption"
        )
    current = _read_risk_envelope_authorization_unlocked()
    expected_previous = previous_sha256 or ""
    if current is None:
        if expected_previous:
            raise OwnerApprovalError(
                "risk envelope authorization predecessor disappeared before commit"
            )
    elif (
        current["risk_envelope_ref"] != risk_envelope_ref
        or current["risk_envelope_sha256"] != expected_previous
    ):
        raise OwnerApprovalError(
            "risk envelope authorization predecessor changed before commit"
        )
    validated = _validate_risk_envelope_authorization_record(record)
    _write_protected_text(
        canonical_risk_envelope_authorization_path(),
        json.dumps(validated, indent=2, sort_keys=True),
        label="risk envelope authorization state",
        canonical=True,
    )


def write_risk_envelope_authorization(
    *,
    risk_envelope_ref: str,
    risk_envelope_sha256: str,
    risk_envelope_text: str,
    previous_sha256: str | None,
    owner_approval: Mapping[str, object],
    approval_id: str,
    transaction_binding_sha256: str,
    authorized_at: datetime.datetime,
) -> None:
    """Finalize only an exact protected prepare plus canonical consumption.

    This compatibility wrapper cannot mint fresh authority: callers cannot
    create a record from identifiers or a historical clock without the exact
    custom prepare and its prepared ledger binding.
    """

    with _protected_lock(
        _risk_envelope_authorization_lock_path(),
        label="risk envelope authorization lock",
        canonical=True,
    ):
        _write_risk_envelope_authorization_unlocked(
            risk_envelope_ref=risk_envelope_ref,
            risk_envelope_sha256=risk_envelope_sha256,
            risk_envelope_text=risk_envelope_text,
            previous_sha256=previous_sha256,
            owner_approval=owner_approval,
            approval_id=approval_id,
            transaction_binding_sha256=transaction_binding_sha256,
            authorized_at=authorized_at,
        )


def risk_envelope_expansion_subject(
    *,
    ref: str,
    sha256: str,
    previous_sha256: str | None,
) -> dict:
    """Canonical subject for a risk_envelope_expansion approval."""

    return {
        "kind": "risk_envelope_expansion",
        "ref": ref,
        "sha256": sha256,
        "previous_sha256": previous_sha256 or "",
    }


def _has_exact_owner_consumption(entry: Mapping[str, object]) -> bool:
    """Return exact prior use; reject same-id use under any other binding."""

    approval_id = entry.get("approval_id")
    for record in _read_ledger_entries(canonical_owner_consumption_ledger_path()):
        if record["approval_id"] != approval_id:
            continue
        if (
            record["action"] == entry.get("action")
            and record["purpose"] == entry.get("purpose")
            and record["transaction_binding_sha256"]
            == entry.get("transaction_binding_sha256")
            and record.get("prepared_transaction_binding_sha256")
            == entry.get("prepared_transaction_binding_sha256")
        ):
            return True
        raise OwnerApprovalError(
            "risk envelope prepare approval was consumed under a different "
            "privileged transaction"
        )
    return False


_OWNER_APPROVAL_PREPARE_SCHEMA_VERSION = 2
_OWNER_APPROVAL_PREPARE_FIELDS = (
    "schema_version",
    "approval_id",
    "action",
    "purpose",
    "transaction_binding_sha256",
    "transaction_sha256",
    "prepared_transaction_binding_sha256",
    "transaction",
    "prepared_at",
)


def owner_approval_prepare_path(output_path: str | Path) -> Path:
    """Strict sibling prepare path for a promotion-state/output write."""

    output = Path(output_path)
    return output.with_name(f".{output.name}.owner-approval-prepare")


def owner_approval_prepare_exists(prepare_path: str | Path) -> bool:
    """Safe-presence probe for a generic prepare without path-following I/O."""

    try:
        return _protected_file_present(
            prepare_path, label="owner approval prepare", canonical=False
        )
    except OwnerApprovalError as exc:
        if "required directory is missing" in str(exc):
            return False
        raise


def _write_owner_approval_prepare_unlocked(
    prepare_path: str | Path,
    *,
    approval_id: str,
    action: str,
    purpose: str,
    transaction_binding_sha256: str,
    transaction: Mapping[str, object],
    now: datetime.datetime,
) -> str:
    """Write one generic prepare while its per-sidecar lock is held.

    ``transaction`` is the caller's immutable, canonical transaction image.
    It must bind the operation-specific input/output, source, subject, risk,
    and before/after facts that the caller will require on recovery.  The
    generic owner record deliberately cannot decide what those facts are, but
    it preserves them byte-for-byte and refuses to overwrite a different
    prepare.  The record is non-executable by contract.
    """

    if not isinstance(transaction, Mapping) or not transaction:
        raise OwnerApprovalError("owner approval prepare transaction is required")
    try:
        transaction_image = json.loads(_canonical_json_bytes(dict(transaction)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OwnerApprovalError(
            "owner approval prepare transaction is not canonical JSON"
        ) from exc
    if not isinstance(transaction_image, dict) or not transaction_image:
        raise OwnerApprovalError("owner approval prepare transaction is invalid")
    transaction_sha256 = prepared_transaction_sha256(transaction_image)
    prepared_binding = prepared_transaction_binding_sha256(
        transaction_binding_sha256=transaction_binding_sha256,
        transaction_sha256=transaction_sha256,
    )
    prepared = {
        "schema_version": _OWNER_APPROVAL_PREPARE_SCHEMA_VERSION,
        "approval_id": approval_id,
        "action": action,
        "purpose": purpose,
        "transaction_binding_sha256": transaction_binding_sha256,
        "transaction_sha256": transaction_sha256,
        "prepared_transaction_binding_sha256": prepared_binding,
        "transaction": transaction_image,
        "analysis_only": True,
        "execution_authority": "none",
        "can_submit_orders": False,
        "prepared_at": _aware_utc_text(
            now, label="owner approval transaction prepare"
        ),
    }
    if set(prepared) != set(_OWNER_APPROVAL_PREPARE_FIELDS) | {
        "analysis_only",
        "execution_authority",
        "can_submit_orders",
    }:
        raise OwnerApprovalError("owner approval prepare schema is invalid")
    target = _absolute_lexical_path(prepare_path)
    existing = read_owner_approval_prepare(target)
    if existing is not None:
        existing_comparable = dict(existing)
        proposed_comparable = dict(prepared)
        existing_comparable.pop("prepared_at")
        proposed_comparable.pop("prepared_at")
        if existing_comparable != proposed_comparable:
            raise OwnerApprovalError(
                "owner approval prepare already binds a different transaction"
            )
        return str(existing["prepared_transaction_binding_sha256"])
    if owner_approval_prepare_exists(target):
        raise OwnerApprovalError("owner approval prepare is malformed")
    _write_protected_text(
        target,
        json.dumps(prepared, indent=2, sort_keys=True),
        label="owner approval prepare",
        canonical=False,
    )
    return prepared_binding


def write_owner_approval_prepare(
    prepare_path: str | Path,
    *,
    approval_id: str,
    action: str,
    purpose: str,
    transaction_binding_sha256: str,
    transaction: Mapping[str, object],
    now: datetime.datetime,
) -> str:
    """Durably record the intended consumption before the ledger write.

    The per-sidecar lock serializes the complete absent/read/compare/replace
    lifecycle.  Two different transactions can therefore never both observe
    an absent prepare and each report that their recovery image was admitted.
    """

    target = _absolute_lexical_path(prepare_path)
    lock_path = target.with_name(f".{target.name}.lock")
    with _protected_lock(
        lock_path,
        label="owner approval prepare lock",
        canonical=False,
    ):
        return _write_owner_approval_prepare_unlocked(
            target,
            approval_id=approval_id,
            action=action,
            purpose=purpose,
            transaction_binding_sha256=transaction_binding_sha256,
            transaction=transaction,
            now=now,
        )


def read_owner_approval_prepare(prepare_path: str | Path) -> dict | None:
    """Return the durable prepare, or None when absent/malformed (fail closed)."""

    try:
        text = _read_protected_text(
            prepare_path,
            label="owner approval prepare",
            canonical=False,
            missing_ok=True,
        )
        if text is None:
            return None
        raw = json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError, OwnerApprovalError):
        return None
    required = set(_OWNER_APPROVAL_PREPARE_FIELDS) | {
        "analysis_only",
        "execution_authority",
        "can_submit_orders",
    }
    if (
        not isinstance(raw, dict)
        or set(raw) != required
        or raw.get("schema_version") != _OWNER_APPROVAL_PREPARE_SCHEMA_VERSION
        or not _is_sha256_hex(raw.get("approval_id"))
        or not _is_sha256_hex(raw.get("transaction_binding_sha256"))
        or not _is_sha256_hex(raw.get("transaction_sha256"))
        or not _is_sha256_hex(raw.get("prepared_transaction_binding_sha256"))
        or type(raw.get("action")) is not str
        or type(raw.get("purpose")) is not str
        or not isinstance(raw.get("transaction"), dict)
        or not raw.get("transaction")
        or raw.get("analysis_only") is not True
        or raw.get("execution_authority") != "none"
        or raw.get("can_submit_orders") is not False
    ):
        return None
    if raw["transaction_sha256"] != prepared_transaction_sha256(raw["transaction"]):
        return None
    if raw["prepared_transaction_binding_sha256"] != prepared_transaction_binding_sha256(
        transaction_binding_sha256=raw["transaction_binding_sha256"],
        transaction_sha256=raw["transaction_sha256"],
    ):
        return None
    return raw


def owner_approval_prepare_matches(
    prepare_path: str | Path,
    *,
    transaction: Mapping[str, object],
) -> dict | None:
    """Return an exact durable prepare for ``transaction``, else ``None``.

    This does *not* prove consumption.  Callers must pair it with
    :func:`owner_prepare_has_exact_consumption` before recovering or
    finalizing a privileged transition.  Canonical comparison means map order
    cannot mask a changed source, subject, output, or before/after image.
    """

    prepared = read_owner_approval_prepare(prepare_path)
    if prepared is None:
        return None
    try:
        expected = json.loads(_canonical_json_bytes(dict(transaction)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OwnerApprovalError(
            "owner approval prepare transaction is not canonical JSON"
        ) from exc
    if prepared["transaction"] != expected:
        return None
    return prepared


def owner_approval_prepare_recovery_matches(
    prepare_path: str | Path,
    *,
    recovery_identity: Mapping[str, object],
) -> dict | None:
    """Return a consumed-transaction candidate with this exact retry identity.

    A retry identity deliberately excludes only the generated output image.  It
    still binds the requested subject/source, resolved output, prior image, and
    risk facts, so a later caller may resume the *same* interrupted transition
    without manufacturing a new timestamped payload.  This helper does not
    establish ledger authority; callers must separately require
    :func:`owner_prepare_has_exact_consumption`.
    """

    prepared = read_owner_approval_prepare(prepare_path)
    if prepared is None:
        return None
    transaction = prepared["transaction"]
    try:
        expected = json.loads(_canonical_json_bytes(dict(recovery_identity)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OwnerApprovalError(
            "owner approval prepare recovery identity is not canonical JSON"
        ) from exc
    if transaction.get("recovery_identity") != expected:
        return None
    return prepared


@contextmanager
def exact_expired_owner_approval_recovery(
    prepare_path: str | Path,
    *,
    recovery_identity: Mapping[str, object],
):
    """Allow one verifier call to replay an exact ledger-proven transaction.

    This narrow, process-local context is only for legacy gate plumbing that
    must structurally inspect the original signed artifact while resuming a
    committed transaction.  It proves the exact durable prepare and ledger
    record before temporarily permitting that artifact's expired timestamp.
    Ordinary verification never enters this context and remains fail-closed.
    """

    prepared = owner_approval_prepare_recovery_matches(
        prepare_path, recovery_identity=recovery_identity
    )
    if prepared is None or not owner_prepare_has_exact_consumption(prepare_path):
        raise OwnerApprovalError(
            "expired owner approval recovery requires an exact prepared transaction "
            "and canonical ledger consumption"
        )
    token = _EXACT_EXPIRED_RECOVERY_APPROVAL_ID.set(prepared["approval_id"])
    try:
        yield prepared
    finally:
        _EXACT_EXPIRED_RECOVERY_APPROVAL_ID.reset(token)


def owner_prepare_has_exact_consumption(prepare_path: str | Path) -> bool:
    """True when the canonical ledger proves this exact prepare consumption."""

    prepared = read_owner_approval_prepare(prepare_path)
    if prepared is None:
        return False
    return any(
        record["approval_id"] == prepared["approval_id"]
        and record["action"] == prepared["action"]
        and record["purpose"] == prepared["purpose"]
        and record["transaction_binding_sha256"]
        == prepared["transaction_binding_sha256"]
        and record.get("prepared_transaction_binding_sha256")
        == prepared["prepared_transaction_binding_sha256"]
        for record in _read_ledger_entries(canonical_owner_consumption_ledger_path())
    )


def prepared_transaction_sha256(transaction: Mapping[str, object]) -> str:
    """Digest the complete canonical image protected by an owner prepare."""

    if not isinstance(transaction, Mapping) or not transaction:
        raise OwnerApprovalError("owner approval prepare transaction is required")
    try:
        encoded = _canonical_json_bytes(dict(transaction))
    except (TypeError, ValueError) as exc:
        raise OwnerApprovalError(
            "owner approval prepare transaction is not canonical JSON"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def prepared_transaction_binding_sha256(
    *,
    transaction_binding_sha256: str,
    transaction_sha256: str,
) -> str:
    """Bind the signed approval scope to one complete prepared transaction."""

    if not _is_sha256_hex(transaction_binding_sha256) or not _is_sha256_hex(
        transaction_sha256
    ):
        raise OwnerApprovalError("prepared transaction binding inputs are invalid")
    return hashlib.sha256(
        _canonical_json_bytes(
            {
                "schema_version": 1,
                "owner_approval_transaction_binding_sha256": transaction_binding_sha256,
                "prepared_transaction_sha256": transaction_sha256,
            }
        )
    ).hexdigest()


def finalize_owner_approval_prepare(prepare_path: str | Path) -> None:
    """Remove the durable prepare after a finalized privileged transition."""

    _unlink_protected_file(
        prepare_path, label="owner approval prepare", canonical=False
    )


def _risk_envelope_prepare_transaction(raw: Mapping[str, object]) -> dict[str, object]:
    """Canonical authority image for one expansion authorization."""

    return {
        "risk_envelope_ref": raw["risk_envelope_ref"],
        "risk_envelope_sha256": raw["risk_envelope_sha256"],
        "risk_envelope_text": raw["risk_envelope_text"],
        "previous_sha256": raw["previous_sha256"],
        "approval_id": raw["approval_id"],
        "action": raw["action"],
        "purpose": raw["purpose"],
        "transaction_binding_sha256": raw["transaction_binding_sha256"],
        "owner_approval": raw["owner_approval"],
    }


def _validate_risk_envelope_prepare(raw: object) -> dict:
    if (
        not isinstance(raw, dict)
        or set(raw) != _RISK_ENVELOPE_PREPARE_FIELDS
        or raw.get("schema_version") != _RISK_ENVELOPE_PREPARE_SCHEMA_VERSION
        or type(raw.get("risk_envelope_ref")) is not str
        or not raw["risk_envelope_ref"].strip()
        or not _is_sha256_hex(raw.get("risk_envelope_sha256"))
        or not _is_sha256_hex(raw.get("approval_id"))
        or raw.get("action") != "risk_envelope_expansion"
        or type(raw.get("purpose")) is not str
        or not _is_sha256_hex(raw.get("transaction_binding_sha256"))
        or not _is_sha256_hex(raw.get("transaction_sha256"))
        or not _is_sha256_hex(raw.get("prepared_transaction_binding_sha256"))
        or not (
            raw.get("previous_sha256") == ""
            or _is_sha256_hex(raw.get("previous_sha256"))
        )
    ):
        raise OwnerApprovalError("risk envelope authorization prepare is invalid")
    prepared_at = _canonical_utc(raw["prepared_at"], label="prepared_at")
    _validate_risk_envelope_snapshot(
        text=raw["risk_envelope_text"],
        expected_sha256=raw["risk_envelope_sha256"],
    )
    subject = risk_envelope_expansion_subject(
        ref=raw["risk_envelope_ref"],
        sha256=raw["risk_envelope_sha256"],
        previous_sha256=raw["previous_sha256"] or None,
    )
    expected_purpose = f"risk_envelope_expansion:{raw['risk_envelope_sha256']}"
    if raw["purpose"] != expected_purpose:
        raise OwnerApprovalError("risk envelope authorization prepare purpose is invalid")
    parsed = _verify_structure_at_paths(
        approval=raw["owner_approval"],
        expected_action="risk_envelope_expansion",
        subject=subject,
        source_binding={"gate": "normal_live_admission"},
        trust_anchor_path=canonical_owner_trust_anchor_path(),
        now=prepared_at,
        purpose=expected_purpose,
    )
    binding = parsed["risk_envelope_binding"]
    expected_binding = transaction_binding_sha256(
        approval_id=parsed["approval_id"],
        action=parsed["action"],
        purpose=expected_purpose,
        subject=subject,
        risk_envelope_ref=raw["risk_envelope_ref"],
        risk_envelope_sha256=raw["risk_envelope_sha256"],
    )
    if (
        parsed["approval_id"] != raw["approval_id"]
        or binding["ref"] != raw["risk_envelope_ref"]
        or binding["sha256"] != raw["risk_envelope_sha256"]
        or expected_binding != raw["transaction_binding_sha256"]
    ):
        raise OwnerApprovalError("risk envelope authorization prepare is inconsistent")
    transaction = _risk_envelope_prepare_transaction(raw)
    transaction_sha256 = prepared_transaction_sha256(transaction)
    if raw["transaction_sha256"] != transaction_sha256 or (
        raw["prepared_transaction_binding_sha256"]
        != prepared_transaction_binding_sha256(
            transaction_binding_sha256=raw["transaction_binding_sha256"],
            transaction_sha256=transaction_sha256,
        )
    ):
        raise OwnerApprovalError("risk envelope authorization prepare binding is invalid")
    return dict(raw)


def _read_risk_envelope_prepare_unlocked() -> dict | None:
    path = canonical_risk_envelope_authorization_prepare_path()
    try:
        text = _read_protected_text(
            path,
            label="risk envelope authorization prepare",
            canonical=True,
            missing_ok=True,
        )
        if text is None:
            return None
    except (OSError, UnicodeError, OwnerApprovalError) as exc:
        raise OwnerApprovalError(
            f"risk envelope authorization prepare is unreadable: {exc}"
        ) from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OwnerApprovalError(
            "risk envelope authorization prepare is corrupt"
        ) from exc
    return _validate_risk_envelope_prepare(raw)


def _read_risk_envelope_prepare() -> dict | None:
    """Read the authorization sidecar under its shared canonical lock."""

    with _protected_lock(
        _risk_envelope_authorization_lock_path(),
        label="risk envelope authorization lock",
        canonical=True,
    ):
        return _read_risk_envelope_prepare_unlocked()


def _owner_expansion_entry(
    *,
    envelope_ref: str,
    envelope_sha256: str,
    envelope_text: str,
    previous_sha256: str | None,
    parsed: Mapping[str, object],
) -> dict[str, object]:
    subject = risk_envelope_expansion_subject(
        ref=envelope_ref,
        sha256=envelope_sha256,
        previous_sha256=previous_sha256,
    )
    purpose = f"risk_envelope_expansion:{envelope_sha256}"
    final_binding = transaction_binding_sha256(
        approval_id=str(parsed["approval_id"]),
        action=str(parsed["action"]),
        purpose=purpose,
        subject=subject,
        risk_envelope_ref=envelope_ref,
        risk_envelope_sha256=envelope_sha256,
    )
    return {
        "authorization_mode": "owner_expansion",
        "risk_envelope_ref": envelope_ref,
        "risk_envelope_sha256": envelope_sha256,
        "risk_envelope_text": envelope_text,
        "previous_sha256": previous_sha256 or "",
        "owner_approval": dict(parsed),
        "approval_id": str(parsed["approval_id"]),
        "action": str(parsed["action"]),
        "purpose": purpose,
        "transaction_binding_sha256": final_binding,
    }


def _prepare_risk_envelope_authorization_unlocked(
    entry: Mapping[str, object], *, now: datetime.datetime
) -> dict[str, object] | None:
    """Durably prepare one exact owner expansion with the auth lock held."""

    if entry.get("authorization_mode") != "owner_expansion":
        return None
    envelope_ref = str(entry.get("risk_envelope_ref") or "")
    envelope_sha256 = str(entry.get("risk_envelope_sha256") or "")
    current_text, _current = _read_current_risk_envelope_snapshot(
        envelope_ref, expected_sha256=envelope_sha256
    )
    if current_text != entry.get("risk_envelope_text"):
        raise OwnerApprovalError("risk envelope changed before authorization prepare")
    prepared = {
        "schema_version": _RISK_ENVELOPE_PREPARE_SCHEMA_VERSION,
        "risk_envelope_ref": envelope_ref,
        "risk_envelope_sha256": envelope_sha256,
        "risk_envelope_text": current_text,
        "previous_sha256": str(entry.get("previous_sha256") or ""),
        "approval_id": entry.get("approval_id"),
        "action": entry.get("action"),
        "purpose": entry.get("purpose"),
        "transaction_binding_sha256": entry.get("transaction_binding_sha256"),
        "owner_approval": entry.get("owner_approval"),
        "prepared_at": _aware_utc_text(
            now, label="risk envelope authorization prepare"
        ),
    }
    transaction = _risk_envelope_prepare_transaction(prepared)
    prepared["transaction_sha256"] = prepared_transaction_sha256(transaction)
    prepared["prepared_transaction_binding_sha256"] = (
        prepared_transaction_binding_sha256(
            transaction_binding_sha256=str(prepared["transaction_binding_sha256"]),
            transaction_sha256=str(prepared["transaction_sha256"]),
        )
    )
    validated = _validate_risk_envelope_prepare(prepared)
    # The expansion entry was constructed from a predecessor snapshot.  Recheck
    # that exact tip before a sidecar or ledger record can be written.
    current_record = _read_risk_envelope_authorization_unlocked()
    expected_previous = validated["previous_sha256"]
    if current_record is None:
        if expected_previous:
            raise OwnerApprovalError(
                "risk envelope authorization predecessor disappeared before prepare"
            )
    elif (
        current_record["risk_envelope_ref"] != envelope_ref
        or current_record["risk_envelope_sha256"] != expected_previous
    ):
        raise OwnerApprovalError(
            "risk envelope authorization predecessor changed before prepare"
        )
    existing = _read_risk_envelope_prepare_unlocked()
    if existing is not None:
        comparison_fields = _RISK_ENVELOPE_PREPARE_FIELDS - {"prepared_at"}
        if all(existing[field] == validated[field] for field in comparison_fields):
            return existing
        if _has_exact_owner_consumption(existing):
            raise OwnerApprovalError(
                "a different consumed risk envelope authorization is awaiting "
                "crash recovery"
            )
    _write_protected_text(
        canonical_risk_envelope_authorization_prepare_path(),
        json.dumps(validated, indent=2, sort_keys=True),
        label="risk envelope authorization prepare",
        canonical=True,
    )
    return validated


def prepare_risk_envelope_authorization(
    entry: Mapping[str, object], *, now: datetime.datetime
) -> dict[str, object] | None:
    """Refuse public preparation outside the atomic authorization transaction."""

    del entry, now
    raise OwnerApprovalError(
        "risk envelope authorization preparation requires the atomic "
        "authorization transaction"
    )


def _finalize_risk_envelope_authorization_unlocked(
    entry: Mapping[str, object], *, now: datetime.datetime
) -> None:
    """Commit a validated transition while the authorization lock is held."""

    mode = entry.get("authorization_mode")
    envelope_ref = str(entry.get("risk_envelope_ref") or "")
    envelope_sha256 = str(entry.get("risk_envelope_sha256") or "")
    current_text, current_envelope = _read_current_risk_envelope_snapshot(
        envelope_ref, expected_sha256=envelope_sha256
    )
    if current_text != entry.get("risk_envelope_text"):
        raise OwnerApprovalError("risk envelope changed before authorization commit")

    if mode in {"owner_expansion", "owner_recovery"}:
        require_prior_consumption_for_commitment_recovery(
            approval_id=str(entry.get("approval_id") or ""),
            action=str(entry.get("action") or ""),
            purpose=str(entry.get("purpose") or ""),
            transaction_binding_sha256=str(
                entry.get("transaction_binding_sha256") or ""
            ),
            prepared_transaction_binding_sha256=str(
                entry.get("prepared_transaction_binding_sha256") or ""
            ),
        )
        authorization_time = now
        if mode == "owner_recovery":
            authorization_time = _canonical_utc(
                entry.get("authorization_originated_at"),
                label="authorization_originated_at",
            )
        _write_risk_envelope_authorization_unlocked(
            risk_envelope_ref=envelope_ref,
            risk_envelope_sha256=envelope_sha256,
            risk_envelope_text=current_text,
            previous_sha256=str(entry.get("previous_sha256") or "") or None,
            owner_approval=entry.get("owner_approval"),
            approval_id=str(entry.get("approval_id") or ""),
            transaction_binding_sha256=str(
                entry.get("transaction_binding_sha256") or ""
            ),
            authorized_at=authorization_time,
        )
        _unlink_protected_file(
            canonical_risk_envelope_authorization_prepare_path(),
            label="risk envelope authorization prepare",
            canonical=True,
        )
        return

    if mode != "machine_risk_reduction":
        raise OwnerApprovalError("risk envelope authorization mode is invalid")

    from tradingagents.policy.risk_envelope import (
        is_monotonic_risk_tightening,
    )

    record = _read_risk_envelope_authorization_unlocked()
    if record is None or record["risk_envelope_ref"] != envelope_ref:
        raise OwnerApprovalError(
            "risk reduction cannot proceed without the proven prior authorization"
        )
    if record["risk_envelope_sha256"] == envelope_sha256:
        return
    if record["risk_envelope_sha256"] != entry.get("previous_authorized_sha256"):
        raise OwnerApprovalError(
            "risk envelope authorization changed during risk-reduction commit"
        )
    previous_envelope = _validate_risk_envelope_snapshot(
        text=record["risk_envelope_text"],
        expected_sha256=record["risk_envelope_sha256"],
    )
    if not is_monotonic_risk_tightening(previous_envelope, current_envelope):
        raise OwnerApprovalError("risk envelope change is not a monotonic risk reduction")
    moment = _aware_utc_text(now, label="risk envelope risk-reduction commit")
    if _canonical_utc(moment, label="updated_at") < _canonical_utc(
        record["updated_at"], label="updated_at"
    ):
        raise OwnerApprovalError("risk envelope risk-reduction clock moved backward")
    updated = dict(record)
    updated["risk_envelope_sha256"] = envelope_sha256
    updated["risk_envelope_text"] = current_text
    updated["updated_at"] = moment
    updated["tightening_history"] = [
        *record["tightening_history"],
        {
            "sha256": envelope_sha256,
            "text": current_text,
            "transition": "machine_risk_reduction",
            "recorded_at": moment,
        },
    ]
    validated = _validate_risk_envelope_authorization_record(updated)
    locked_record = _read_risk_envelope_authorization_unlocked()
    if (
        locked_record is None
        or locked_record["risk_envelope_ref"] != envelope_ref
        or locked_record["risk_envelope_sha256"] != record["risk_envelope_sha256"]
    ):
        raise OwnerApprovalError(
            "risk envelope authorization changed during risk-reduction commit"
        )
    _write_protected_text(
        canonical_risk_envelope_authorization_path(),
        json.dumps(validated, indent=2, sort_keys=True),
        label="risk envelope authorization state",
        canonical=True,
    )


def finalize_risk_envelope_authorization(
    entry: Mapping[str, object], *, now: datetime.datetime
) -> None:
    """Commit an exact consumed expansion or monotonic reduction atomically."""

    with _protected_lock(
        _risk_envelope_authorization_lock_path(),
        label="risk envelope authorization lock",
        canonical=True,
    ):
        _finalize_risk_envelope_authorization_unlocked(entry, now=now)


def _require_machine_reduction_tip_unlocked(
    entry: Mapping[str, object], *, now: datetime.datetime
) -> None:
    """Prove a machine tightening against the current serialized tip."""

    from tradingagents.policy.risk_envelope import is_monotonic_risk_tightening

    envelope_ref = str(entry.get("risk_envelope_ref") or "")
    envelope_sha256 = str(entry.get("risk_envelope_sha256") or "")
    current_text, current_envelope = _read_current_risk_envelope_snapshot(
        envelope_ref, expected_sha256=envelope_sha256
    )
    if current_text != entry.get("risk_envelope_text"):
        raise OwnerApprovalError("risk envelope changed before authorization commit")
    record = _read_risk_envelope_authorization_unlocked()
    if record is None or record["risk_envelope_ref"] != envelope_ref:
        raise OwnerApprovalError(
            "risk reduction cannot proceed without the proven prior authorization"
        )
    if record["risk_envelope_sha256"] == envelope_sha256:
        return
    if record["risk_envelope_sha256"] != entry.get("previous_authorized_sha256"):
        raise OwnerApprovalError(
            "risk envelope authorization changed during risk-reduction commit"
        )
    previous_envelope = _validate_risk_envelope_snapshot(
        text=record["risk_envelope_text"],
        expected_sha256=record["risk_envelope_sha256"],
    )
    if not is_monotonic_risk_tightening(previous_envelope, current_envelope):
        raise OwnerApprovalError("risk envelope change is not a monotonic risk reduction")
    moment = _canonical_utc(
        _aware_utc_text(now, label="risk envelope risk-reduction commit"),
        label="risk envelope risk-reduction commit",
    )
    if moment < _canonical_utc(record["updated_at"], label="updated_at"):
        raise OwnerApprovalError("risk envelope risk-reduction clock moved backward")


def _require_owner_transition_tip_unlocked(entry: Mapping[str, object]) -> None:
    """Prove the exact predecessor and retained recovery sidecar."""

    envelope_ref = str(entry.get("risk_envelope_ref") or "")
    expected_previous = str(entry.get("previous_sha256") or "")
    current = _read_risk_envelope_authorization_unlocked()
    if current is None:
        if expected_previous:
            raise OwnerApprovalError(
                "risk envelope authorization predecessor disappeared before commit"
            )
    elif (
        current["risk_envelope_ref"] != envelope_ref
        or current["risk_envelope_sha256"] != expected_previous
    ):
        raise OwnerApprovalError(
            "risk envelope authorization predecessor changed before commit"
        )
    if entry.get("authorization_mode") == "owner_recovery":
        prepared = _read_risk_envelope_prepare_unlocked()
        if (
            prepared is None
            or prepared["risk_envelope_ref"] != envelope_ref
            or prepared["risk_envelope_sha256"]
            != str(entry.get("risk_envelope_sha256") or "")
            or prepared["transaction_binding_sha256"]
            != str(entry.get("transaction_binding_sha256") or "")
            or prepared["prepared_transaction_binding_sha256"]
            != str(entry.get("prepared_transaction_binding_sha256") or "")
            or not _has_exact_owner_consumption(prepared)
        ):
            raise OwnerApprovalError(
                "risk envelope recovery requires the exact prepare and consumption"
            )


def _commit_owner_approval_transaction(
    entries: list[dict[str, str]],
    *,
    expansion_entry: Mapping[str, object] | None,
    now: datetime.datetime,
) -> dict[str, object] | None:
    """Consume and commit one authorization transaction without a stale burn.

    The authorization lock owns the complete risk transition.  Any nested
    ledger acquisition therefore follows the fixed authorization -> ledger
    order, and an intervening tip is rejected before any approval is appended.
    """

    if expansion_entry is None:
        consume_owner_approvals_batch(entries, now=now)
        return None

    with _protected_lock(
        _risk_envelope_authorization_lock_path(),
        label="risk envelope authorization lock",
        canonical=True,
    ):
        mode = expansion_entry.get("authorization_mode")
        enriched = dict(expansion_entry)
        consumption_moment = now
        if mode == "owner_expansion":
            _require_owner_transition_tip_unlocked(enriched)
            authority_moment = _owner_approval_authority_utc_now()
            envelope_ref = str(enriched.get("risk_envelope_ref") or "")
            envelope_sha256 = str(enriched.get("risk_envelope_sha256") or "")
            previous_sha256 = str(enriched.get("previous_sha256") or "") or None
            subject = risk_envelope_expansion_subject(
                ref=envelope_ref,
                sha256=envelope_sha256,
                previous_sha256=previous_sha256,
            )
            purpose = f"risk_envelope_expansion:{envelope_sha256}"
            parsed = _verify_structure_at_paths(
                approval=enriched.get("owner_approval"),
                expected_action="risk_envelope_expansion",
                subject=subject,
                source_binding={"gate": "normal_live_admission"},
                trust_anchor_path=canonical_owner_trust_anchor_path(),
                now=authority_moment,
                purpose=purpose,
            )
            expected = _owner_expansion_entry(
                envelope_ref=envelope_ref,
                envelope_sha256=envelope_sha256,
                envelope_text=str(enriched.get("risk_envelope_text") or ""),
                previous_sha256=previous_sha256,
                parsed=parsed,
            )
            for field in (
                "approval_id",
                "action",
                "purpose",
                "transaction_binding_sha256",
                "previous_sha256",
            ):
                if enriched.get(field) != expected.get(field):
                    raise OwnerApprovalError(
                        "risk envelope expansion changed before atomic commit"
                    )
            prepared = _prepare_risk_envelope_authorization_unlocked(
                enriched, now=authority_moment
            )
            if prepared is None:
                raise OwnerApprovalError("risk envelope authorization prepare is missing")
            enriched.update(
                {
                    "transaction_sha256": prepared["transaction_sha256"],
                    "prepared_transaction_binding_sha256": prepared[
                        "prepared_transaction_binding_sha256"
                    ],
                }
            )
            entries = [
                *entries,
                {
                    "approval_id": str(enriched["approval_id"]),
                    "action": str(enriched["action"]),
                    "purpose": str(enriched["purpose"]),
                    "transaction_binding_sha256": str(
                        enriched["transaction_binding_sha256"]
                    ),
                    "prepared_transaction_binding_sha256": str(
                        enriched["prepared_transaction_binding_sha256"]
                    ),
                },
            ]
            consumption_moment = authority_moment
        elif mode == "owner_recovery":
            _require_owner_transition_tip_unlocked(enriched)
        elif mode == "machine_risk_reduction":
            _require_machine_reduction_tip_unlocked(enriched, now=now)
        else:
            raise OwnerApprovalError("risk envelope authorization mode is invalid")

        _consume_owner_approvals_batch(
            entries,
            now=consumption_moment,
            authorization_locked=True,
        )
        _finalize_risk_envelope_authorization_unlocked(
            enriched,
            now=consumption_moment,
        )
        return enriched


def require_risk_envelope_expansion(
    *,
    resolved_envelope_path: str | Path,
    current_envelope_sha256: str,
    expansion_approval: Mapping[str, object] | None,
    now: datetime.datetime,
    consume: bool = False,
) -> dict[str, object]:
    """Policy-layer enforcement point for ``risk_envelope_expansion``.

    A changed/enlarged live risk envelope becomes usable only through an
    independently signed, single-use expansion artifact whose subject binds
    the exact canonical ref, new SHA-256, and previous authorized digest.

    With ``consume=False`` this performs structural verification only — no
    ledger write and no record update — so callers can preflight before
    ordinary live gates run.  With ``consume=True`` the artifact is durably
    consumed and the authorization record atomically updated; call that only
    at the final permitted transition after every ordinary gate has passed.
    Raises :class:`OwnerApprovalError` on any refusal.
    """

    envelope_ref = str(resolved_envelope_path)
    if not _is_sha256_hex(current_envelope_sha256):
        raise OwnerApprovalError("risk envelope expansion digest is invalid")
    envelope_text, current_envelope = _read_current_risk_envelope_snapshot(
        resolved_envelope_path, expected_sha256=current_envelope_sha256
    )
    authorization_path = canonical_risk_envelope_authorization_path()
    record = read_risk_envelope_authorization()
    if (
        record is not None
        and record["risk_envelope_ref"] == envelope_ref
        and record["risk_envelope_sha256"] == current_envelope_sha256
    ):
        # Unchanged: already authorized and ledger/signature proven.
        return {}

    if record is not None and record["risk_envelope_ref"] == envelope_ref:
        from tradingagents.policy.risk_envelope import (
            is_monotonic_risk_tightening,
        )

        previous_envelope = _validate_risk_envelope_snapshot(
            text=record["risk_envelope_text"],
            expected_sha256=record["risk_envelope_sha256"],
        )
        if is_monotonic_risk_tightening(previous_envelope, current_envelope):
            entry: dict[str, object] = {
                "authorization_mode": "machine_risk_reduction",
                "risk_envelope_ref": envelope_ref,
                "risk_envelope_sha256": current_envelope_sha256,
                "risk_envelope_text": envelope_text,
                "previous_authorized_sha256": record["risk_envelope_sha256"],
            }
            if consume:
                committed = _commit_owner_approval_transaction(
                    [], expansion_entry=entry, now=now
                )
                if committed is not None:
                    entry = committed
            return entry

    prepared = _read_risk_envelope_prepare()
    if (
        prepared is not None
        and prepared["risk_envelope_ref"] == envelope_ref
        and prepared["risk_envelope_sha256"] == current_envelope_sha256
        and prepared["risk_envelope_text"] == envelope_text
        and _has_exact_owner_consumption(prepared)
    ):
        if record is None:
            if prepared["previous_sha256"]:
                raise OwnerApprovalError(
                    "risk envelope recovery lost its proven previous authorization"
                )
        elif prepared["previous_sha256"] != record["risk_envelope_sha256"]:
            raise OwnerApprovalError(
                "risk envelope recovery does not continue the current "
                "authorization tip"
            )
        recovery = {
            **prepared,
            "authorization_mode": "owner_recovery",
            "authorization_originated_at": prepared["prepared_at"],
        }
        recovery.pop("schema_version", None)
        recovery.pop("prepared_at", None)
        if consume:
            committed = _commit_owner_approval_transaction(
                [], expansion_entry=recovery, now=now
            )
            if committed is not None:
                recovery = committed
        return recovery

    if record is None and _protected_file_present(
        authorization_path,
        label="risk envelope authorization state",
        canonical=True,
    ):
        raise OwnerApprovalError(
            "stored risk envelope authorization is malformed or unproven; "
            "risk envelope expansion is refused until protected state is repaired"
        )

    previous_sha256 = (
        str(record["risk_envelope_sha256"]) if record is not None else None
    )
    if expansion_approval is None:
        raise OwnerApprovalError(
            "risk envelope expansion requires an account_owner "
            "risk_envelope_expansion approval; the changed envelope cannot "
            "affect live eligibility or normal-live use"
        )
    subject = risk_envelope_expansion_subject(
        ref=envelope_ref,
        sha256=current_envelope_sha256,
        previous_sha256=previous_sha256,
    )
    source_binding = {"gate": "normal_live_admission"}
    purpose = f"risk_envelope_expansion:{current_envelope_sha256}"
    # A recovery with an exact durable prepare plus exact canonical ledger
    # record returned above is the sole post-expiry route.  Every new
    # expansion instead reads a private policy clock before verification,
    # prepare, first consumption, and authorization finalization.
    authority_moment = _owner_approval_authority_utc_now()
    parsed = _verify_structure_at_paths(
        approval=expansion_approval,
        expected_action="risk_envelope_expansion",
        subject=subject,
        source_binding=source_binding,
        trust_anchor_path=canonical_owner_trust_anchor_path(),
        now=authority_moment,
        purpose=purpose,
    )
    binding = parsed["risk_envelope_binding"]
    if binding["ref"] != envelope_ref or binding["sha256"] != current_envelope_sha256:
        raise OwnerApprovalError(
            "owner approval risk envelope binding does not match this request"
        )
    entry = _owner_expansion_entry(
        envelope_ref=envelope_ref,
        envelope_sha256=current_envelope_sha256,
        envelope_text=envelope_text,
        previous_sha256=previous_sha256,
        parsed=parsed,
    )
    if consume:
        committed = _commit_owner_approval_transaction(
            [], expansion_entry=entry, now=authority_moment
        )
        if committed is None:
            raise OwnerApprovalError("risk envelope authorization commit is missing")
        entry = committed
    return entry


def _ledger_lock_path(path: Path) -> Path:
    ledger = Path(path)
    return ledger.with_name(f".{ledger.name}.lock")


def _read_ledger_entries_unlocked(path: Path) -> list[dict]:
    """Read a ledger while its canonical ledger lock is already held."""

    try:
        text = _read_protected_text(
            path,
            label="owner approval consumption ledger",
            canonical=True,
            missing_ok=True,
        )
        if text is None:
            return []
    except (OSError, UnicodeError, OwnerApprovalError) as exc:
        raise OwnerApprovalError(f"owner approval ledger is unreadable: {exc}") from exc
    entries: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OwnerApprovalError("owner approval ledger is corrupt") from exc
        if (
            not isinstance(entry, dict)
            or frozenset(entry)
            not in {frozenset(_LEDGER_FIELDS), frozenset(_PREPARED_LEDGER_FIELDS)}
            or entry.get("schema_version") != _LEDGER_SCHEMA_VERSION
            or not _is_sha256_hex(entry.get("approval_id"))
            or not _is_sha256_hex(entry.get("transaction_binding_sha256"))
            or (
                "prepared_transaction_binding_sha256" in entry
                and not _is_sha256_hex(
                    entry.get("prepared_transaction_binding_sha256")
                )
            )
            or type(entry.get("action")) is not str
            or type(entry.get("purpose")) is not str
            or type(entry.get("consumed_at")) is not str
        ):
            raise OwnerApprovalError("owner approval ledger entry is invalid")
        entries.append(entry)
    return entries


def _read_ledger_entries(path: Path) -> list[dict]:
    """Serialize a complete ledger proof against concurrent append/replace."""

    ledger = Path(path)
    with _protected_lock(
        _ledger_lock_path(ledger),
        label="owner approval consumption ledger lock",
        canonical=True,
    ):
        return _read_ledger_entries_unlocked(ledger)


def _check_owner_approval_ledger(
    path: str | Path, approval_id: str, *, ledger_locked: bool = False
) -> None:
    """Refuse any prior use of this approval id (single-use, purpose-agnostic)."""

    ledger = Path(path)
    entries = (
        _read_ledger_entries_unlocked(ledger)
        if ledger_locked
        else _read_ledger_entries(ledger)
    )
    for entry in entries:
        if entry["approval_id"] == approval_id:
            raise OwnerApprovalError(
                "owner approval already used; replaying an approval for a "
                "second privilege or a repeat evaluation fails closed"
            )


def transaction_binding_sha256(
    *,
    approval_id: str,
    action: str,
    purpose: str,
    subject: Mapping[str, object],
    risk_envelope_ref: str,
    risk_envelope_sha256: str,
) -> str:
    """Deterministic binding over the exact approved order evidence."""

    payload = {
        "approval_id": approval_id,
        "action": action,
        "purpose": purpose,
        "subject": dict(subject),
        "risk_envelope_ref": risk_envelope_ref,
        "risk_envelope_sha256": risk_envelope_sha256,
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()



def _consume_owner_approvals_batch(
    entries: list[dict[str, str]],
    *,
    now: datetime.datetime,
    authorization_locked: bool,
) -> None:
    """All-or-nothing durable consumption of a batch of approvals.

    Every entry must carry approval_id, action, purpose, and the complete
    exact transaction binding.  Under one exclusive ledger lock: validate all
    bindings, refuse if ANY approval id already has a recorded use, and
    append every consumption record in one atomic write.  A rejected entry
    burns nothing.
    """

    if not entries:
        return
    if now.tzinfo is None or now.utcoffset() is None:
        raise OwnerApprovalError("owner approval consumption requires an aware clock")
    moment = now.astimezone(datetime.timezone.utc)
    consumed_at = moment.replace(microsecond=0).isoformat()
    prepared: list[tuple[dict[str, str], str]] = []
    for entry in entries:
        binding = entry.get("transaction_binding_sha256")
        prepared_binding = entry.get("prepared_transaction_binding_sha256")
        approval_id = entry.get("approval_id")
        action = entry.get("action")
        purpose = entry.get("purpose")
        if (
            not _is_sha256_hex(binding)
            or not _is_sha256_hex(approval_id)
            or type(action) is not str
            or not action
            or type(purpose) is not str
            or not purpose
            or (
                prepared_binding is not None
                and not _is_sha256_hex(prepared_binding)
            )
        ):
            raise OwnerApprovalError(
                "owner approval batch consumption requires complete exact "
                "entries (id, action, purpose, transaction binding)"
            )
        if action == "risk_envelope_expansion":
            if not authorization_locked:
                raise OwnerApprovalError(
                    "risk envelope expansion consumption requires the atomic "
                    "authorization transaction"
                )
            # A batch entry is not itself authority for an envelope expansion.
            # It must carry the same prepared binding as the freshly validated
            # durable prepare, otherwise an altered/missing sidecar binding
            # could burn the signed artifact under a different transaction.
            if prepared_binding is None:
                raise OwnerApprovalError(
                    "risk envelope expansion batch consumption requires an "
                    "exact durable prepared transaction binding"
                )
            durable_prepare = _read_risk_envelope_prepare_unlocked()
            if (
                durable_prepare is None
                or durable_prepare["approval_id"] != approval_id
                or durable_prepare["action"] != action
                or durable_prepare["purpose"] != purpose
                or durable_prepare["transaction_binding_sha256"] != binding
                or durable_prepare["prepared_transaction_binding_sha256"]
                != prepared_binding
            ):
                raise OwnerApprovalError(
                    "risk envelope expansion batch binding does not match the "
                    "durable prepared transaction"
                )
        ledger_entry = {
            "schema_version": _LEDGER_SCHEMA_VERSION,
            "approval_id": approval_id,
            "action": action,
            "purpose": purpose,
            "transaction_binding_sha256": binding,
            "consumed_at": consumed_at,
        }
        if prepared_binding is not None:
            ledger_entry["prepared_transaction_binding_sha256"] = prepared_binding
        line = json.dumps(
            ledger_entry,
            sort_keys=True,
            separators=(",", ":"),
        )
        prepared.append((entry, line))

    ledger = canonical_owner_consumption_ledger_path()
    lock_path = _ledger_lock_path(ledger)
    with _protected_lock(
        lock_path, label="owner approval consumption ledger lock", canonical=True
    ):
        prepared_ids = [pair[0]["approval_id"] for pair in prepared]
        if len(set(prepared_ids)) != len(prepared_ids):
            raise OwnerApprovalError(
                "owner approval batch contains a duplicate approval id; "
                "batch refused with no approvals burned"
            )
        existing_ids = {
            record["approval_id"]
            for record in _read_ledger_entries_unlocked(ledger)
        }
        for entry, _line in prepared:
            if entry["approval_id"] in existing_ids:
                raise OwnerApprovalError(
                    f"owner approval {entry['approval_id']} already used; "
                    "batch refused with no approvals burned"
                )
        combined = "\n".join(line for _entry, line in prepared) + "\n"
        _append_protected_text(
            ledger,
            combined,
            label="owner approval consumption ledger",
            canonical=True,
        )


def consume_owner_approvals_batch(
    entries: list[dict[str, str]],
    *,
    now: datetime.datetime,
) -> None:
    """Consume a non-risk batch; risk expansion uses its atomic transaction."""

    _consume_owner_approvals_batch(
        entries,
        now=now,
        authorization_locked=False,
    )


def _consume_owner_approval(
    path: str | Path,
    *,
    approval_id: str,
    action: str,
    purpose: str,
    transaction_binding_sha256: str,
    prepared_transaction_binding_sha256: str | None,
    consumed_at: datetime.datetime,
) -> None:
    """Record exactly one durable use; any prior use refuses the transition."""

    ledger = Path(path)
    lock_path = _ledger_lock_path(ledger)
    with _protected_lock(
        lock_path, label="owner approval consumption ledger lock", canonical=True
    ):
        _check_owner_approval_ledger(ledger, approval_id, ledger_locked=True)
        entry = {
            "schema_version": _LEDGER_SCHEMA_VERSION,
            "approval_id": approval_id,
            "action": action,
            "purpose": purpose,
            "transaction_binding_sha256": transaction_binding_sha256,
            "consumed_at": consumed_at.replace(microsecond=0).isoformat(),
        }
        if prepared_transaction_binding_sha256 is not None:
            if not _is_sha256_hex(prepared_transaction_binding_sha256):
                raise OwnerApprovalError(
                    "owner approval consumption requires a complete prepared "
                    "transaction binding (sha256)"
                )
            entry["prepared_transaction_binding_sha256"] = (
                prepared_transaction_binding_sha256
            )
        line = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        _append_protected_text(
            ledger,
            line + "\n",
            label="owner approval consumption ledger",
            canonical=True,
        )
