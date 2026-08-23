"""Deterministic, nonsecret runtime identity capture for shadow trials.

The capture freezes one exact execution context: canonical repository path,
HEAD commit, clean tracked worktree, dependency-lock hashes, interpreter facts,
normalized installed-package inventory digest, schedule/role/live-control
contract hashes, the configured automation TOML hashes, the nonsecret
overnight provider/model route, and packet schema versions. Every filesystem
and process fact is constructor-injectable so callers can capture against
fixtures without touching credentials, brokers, automation APIs, or runtime
results. Any ambiguity fails closed with :class:`RuntimeIdentityError`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import tomllib

from tradingagents.default_config import DEFAULT_CONFIG

RUNTIME_IDENTITY_SCHEMA_VERSION = "runtime_identity_v1"
REQUIRED_SOURCE_FILES = (
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    "requirements-crawler.txt",
)
SCHEDULE_CONTRACT_RELPATH = ("config", "automation_schedule_contract.json")
ROLE_CONTRACT_RELPATH = ("config", "automation_roles.json")
LIVE_CONTROL_RELPATH = ("results", "policy", "live_control.json")
AUTOMATION_TOML_NAME = "automation.toml"

_HEAD_COMMIT_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_AUTOMATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PACKAGE_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_PACKAGE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+!~-]{0,127}$")
_ROUTE_STRING_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{0,199}$")
_SCHEMA_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_GIT_TIMEOUT_SECONDS = 60


class RuntimeIdentityError(ValueError):
    """The requested runtime identity cannot be captured safely."""


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeIdentityError("runtime identity payload is not JSON-safe") from exc


def _capture_timestamp(now: dt.datetime | None) -> str:
    moment = dt.datetime.now(dt.timezone.utc) if now is None else now
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise RuntimeIdentityError("now must be timezone-aware")
    return moment.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _resolve_repo_root(repo_root: str | Path) -> Path:
    try:
        root = Path(os.fspath(repo_root)).expanduser().resolve()
    except OSError as exc:
        raise RuntimeIdentityError("repo_root cannot be resolved") from exc
    if not root.is_dir():
        raise RuntimeIdentityError("repo_root must be an existing directory")
    return root


def _default_automation_root() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    base = Path(codex_home) if codex_home else Path.home() / ".codex"
    return base / "automations"


def _read_regular_file(path_value: str | Path, *, label: str) -> bytes:
    """Read exact bytes from a regular, non-symlink file, rejecting drift."""

    path = Path(os.fspath(path_value))
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RuntimeIdentityError(f"{label} is missing: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise RuntimeIdentityError(f"{label} must not be a symlink: {path}")
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeIdentityError(f"{label} must be a regular file: {path}")
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise RuntimeIdentityError(f"{label} must be a regular file: {path}")
            raw = handle.read()
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise RuntimeIdentityError(f"{label} is unreadable: {path}") from exc
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise RuntimeIdentityError(f"{label} changed while being read: {path}")
    return raw


def _file_sha256(path_value: str | Path, *, label: str) -> str:
    return hashlib.sha256(_read_regular_file(path_value, label=label)).hexdigest()


def _source_file_record(path_value: str | Path, name: str) -> dict[str, Any]:
    raw = _read_regular_file(path_value, label=f"required source file {name}")
    return {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def _git_output(repo_root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", os.fspath(repo_root), *arguments],
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeIdentityError(f"git is unavailable for {repo_root}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[:200]
        raise RuntimeIdentityError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.decode("utf-8", errors="strict")


def _head_commit(repo_root: Path) -> str:
    commit = _git_output(repo_root, "rev-parse", "HEAD").strip().lower()
    if not _HEAD_COMMIT_RE.fullmatch(commit):
        raise RuntimeIdentityError("repository HEAD is not a resolvable commit")
    return commit


def _tracked_tree_is_clean(repo_root: Path) -> bool:
    status = _git_output(repo_root, "status", "--porcelain", "--untracked-files=no")
    if status.strip():
        raise RuntimeIdentityError("tracked worktree is dirty")
    return True


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeIdentityError("schedule contract contains duplicate JSON keys")
        result[key] = value
    return result


def _expected_automation_ids(schedule_raw: bytes) -> tuple[str, ...]:
    try:
        document = json.loads(schedule_raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeIdentityError("schedule contract is not valid JSON") from exc
    automations = document.get("automations") if isinstance(document, dict) else None
    if not isinstance(automations, dict) or not automations:
        raise RuntimeIdentityError("schedule contract defines no automations")
    identifiers: list[str] = []
    for identifier in automations:
        if not isinstance(identifier, str) or not _AUTOMATION_ID_RE.fullmatch(identifier):
            raise RuntimeIdentityError("schedule contract has an invalid automation id")
        identifiers.append(identifier)
    return tuple(sorted(identifiers))


def _route_string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise RuntimeIdentityError(f"{field} must be a string")
    stripped = value.strip()
    if not _ROUTE_STRING_RE.fullmatch(stripped):
        raise RuntimeIdentityError(f"{field} is not a nonsecret route string")
    return stripped


def _overnight_route(
    *,
    provider: str | None,
    quick_model: str | None,
    deep_model: str | None,
) -> dict[str, str]:
    return {
        "provider": _route_string(provider or DEFAULT_CONFIG.get("llm_provider"), field="overnight_provider"),
        "quick_think_llm": _route_string(quick_model or DEFAULT_CONFIG.get("quick_think_llm"), field="overnight_quick_model"),
        "deep_think_llm": _route_string(deep_model or DEFAULT_CONFIG.get("deep_think_llm"), field="overnight_deep_model"),
    }


def _normalize_package_name(name: object) -> str:
    if not isinstance(name, str):
        raise RuntimeIdentityError("package names must be strings")
    normalized = re.sub(r"[-_.]+", "-", name.strip()).lower()
    if not _PACKAGE_NAME_RE.fullmatch(normalized):
        raise RuntimeIdentityError("package inventory contains an invalid name")
    return normalized


def _package_version(version: object) -> str:
    if not isinstance(version, str):
        raise RuntimeIdentityError("package versions must be strings")
    text = version.strip()
    if not _PACKAGE_VERSION_RE.fullmatch(text):
        raise RuntimeIdentityError("package inventory contains an invalid version")
    return text


def normalized_package_inventory_sha256(
    packages: Sequence[tuple[str, str]] | Mapping[str, str],
) -> dict[str, int]:
    """Digest a PEP 503-normalized, de-duplicated package inventory."""

    items: list[tuple[object, object]]
    if isinstance(packages, Mapping):
        items = list(packages.items())
    elif isinstance(packages, Sequence):
        items = [(entry[0], entry[1]) for entry in packages]
    else:
        raise RuntimeIdentityError("installed_packages must be a sequence or mapping")
    rows: set[tuple[str, str]] = set()
    for name, version in items:
        rows.add((_normalize_package_name(name), _package_version(version)))
    text = "".join(f"{name}=={version}\n" for name, version in sorted(rows))
    return {"inventory_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "count": len(rows)}


def _ambient_package_inventory() -> list[tuple[str, str]]:
    try:
        import importlib.metadata

        entries: list[tuple[str, str]] = []
        for distribution in importlib.metadata.distributions():
            name = distribution.metadata.get("Name") if distribution.metadata is not None else None
            version = distribution.version
            if name and version:
                entries.append((name, version))
        return entries
    except Exception as exc:
        raise RuntimeIdentityError("installed-package inventory is unavailable") from exc


def _schema_versions(supplied: Mapping[str, object] | None) -> dict[str, Any]:
    versions: dict[str, Any] = {"runtime_identity": RUNTIME_IDENTITY_SCHEMA_VERSION}
    if supplied is None:
        return versions
    for key, value in supplied.items():
        if not isinstance(key, str) or not _SCHEMA_KEY_RE.fullmatch(key):
            raise RuntimeIdentityError("packet schema version keys must be simple identifiers")
        if isinstance(value, str):
            if not value.strip() or len(value) > 128:
                raise RuntimeIdentityError("packet schema versions must be short strings or ints")
        elif isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeIdentityError("packet schema versions must be short strings or ints")
        versions[key] = value
    return versions


def capture_runtime_identity(
    *,
    repo_root: str | Path,
    schedule_contract_path: str | Path | None = None,
    role_contract_path: str | Path | None = None,
    live_control_path: str | Path | None = None,
    automation_root: str | Path | None = None,
    now: dt.datetime | None = None,
    python_executable: str | None = None,
    python_version: str | None = None,
    installed_packages: Sequence[tuple[str, str]] | Mapping[str, str] | None = None,
    overnight_provider: str | None = None,
    overnight_quick_model: str | None = None,
    overnight_deep_model: str | None = None,
    packet_schema_versions: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Capture one immutable, JSON-safe, nonsecret runtime identity snapshot."""

    root = _resolve_repo_root(repo_root)
    schedule_path = Path(schedule_contract_path) if schedule_contract_path else root.joinpath(*SCHEDULE_CONTRACT_RELPATH)
    role_path = Path(role_contract_path) if role_contract_path else root.joinpath(*ROLE_CONTRACT_RELPATH)
    control_path = Path(live_control_path) if live_control_path else root.joinpath(*LIVE_CONTROL_RELPATH)
    automations_dir = Path(automation_root) if automation_root else _default_automation_root()

    schedule_raw = _read_regular_file(schedule_path, label="schedule contract")
    identity: dict[str, Any] = {
        "schema_version": RUNTIME_IDENTITY_SCHEMA_VERSION,
        "captured_at": _capture_timestamp(now),
        "repo": {
            "root": str(root),
            "head_commit": _head_commit(root),
            "tracked_tree_clean": _tracked_tree_is_clean(root),
        },
        "source_files": {name: _source_file_record(root / name, name) for name in REQUIRED_SOURCE_FILES},
        "python": {
            "executable": python_executable or sys.executable,
            "version": python_version or platform.python_version(),
        },
        "packages": normalized_package_inventory_sha256(installed_packages if installed_packages is not None else _ambient_package_inventory()),
        "contracts": {
            "schedule_contract_sha256": hashlib.sha256(schedule_raw).hexdigest(),
            "role_contract_sha256": _file_sha256(role_path, label="role contract"),
            "live_control_sha256": _file_sha256(control_path, label="live control"),
        },
        "automation_tomls": {},
        "overnight_route": _overnight_route(
            provider=overnight_provider,
            quick_model=overnight_quick_model,
            deep_model=overnight_deep_model,
        ),
        "schema_versions": _schema_versions(packet_schema_versions),
    }

    for identifier in _expected_automation_ids(schedule_raw):
        toml_path = automations_dir / identifier / AUTOMATION_TOML_NAME
        raw = _read_regular_file(toml_path, label=f"automation TOML {identifier}")
        try:
            tomllib.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise RuntimeIdentityError(f"automation TOML {identifier} is malformed") from exc
        identity["automation_tomls"][identifier] = hashlib.sha256(raw).hexdigest()

    _canonical_json_bytes(identity)
    return identity
