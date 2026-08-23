"""Fixture-only, deterministic runtime identity capture for evaluations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn

_IDENTITY_SCHEMA = "runtime_identity/v1"
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40,64}")
_CHUNK_SIZE_BYTES = 1 << 20


class RuntimeIdentityError(ValueError):
    """Raised when identity inputs are invalid or the worktree is not clean."""


def _fail(message: str) -> NoReturn:
    raise RuntimeIdentityError(message)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _validated_repo_root(repo_root: Path) -> Path:
    if not isinstance(repo_root, (str, os.PathLike)):
        _fail("repo_root must be a filesystem path")
    root = Path(os.path.realpath(Path(repo_root)))
    if not root.is_dir():
        _fail("repo_root must be an existing directory")
    return root


def _validated_label(label: object, field: str) -> None:
    if not isinstance(label, str) or not label.strip():
        _fail(f"{field} labels must be non-empty strings")


def _validated_string_mapping(values: Mapping[str, str], field: str) -> dict[str, str]:
    if not isinstance(values, Mapping):
        _fail(f"{field} must be a mapping of non-empty strings")
    validated: dict[str, str] = {}
    for label, value in values.items():
        _validated_label(label, field)
        if not isinstance(value, str) or not value.strip():
            _fail(f"{field}[{label!r}] must be a non-empty string")
        validated[label] = value
    return dict(sorted(validated.items()))


def _validated_path_mapping(values: Mapping[str, Path], field: str) -> dict[str, Path]:
    if not isinstance(values, Mapping):
        _fail(f"{field} must be a mapping of labels to filesystem paths")
    validated: dict[str, Path] = {}
    for label, value in values.items():
        _validated_label(label, field)
        if not isinstance(value, (str, os.PathLike)):
            _fail(f"{field}[{label!r}] must be a filesystem path")
        validated[label] = Path(value)
    return dict(sorted(validated.items()))


def _validated_optional_string(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} must be a non-empty string when provided")
    return value


def _normalized_package_inventory(inventory: Sequence[str] | None) -> list[str]:
    if inventory is None:
        return []
    if isinstance(inventory, (str, bytes)) or not isinstance(inventory, Sequence):
        _fail("package_inventory must be a sequence of strings")
    normalized: set[str] = set()
    for entry in inventory:
        if not isinstance(entry, str) or not entry.strip():
            _fail("package_inventory entries must be non-empty strings")
        normalized.add(entry.strip().lower())
    return sorted(normalized)


def _run_git(root: Path, arguments: list[str]) -> str:
    completed = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown failure"
        _fail(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def _capture_git_state(root: Path) -> str:
    head = _run_git(root, ["rev-parse", "HEAD"]).strip()
    if not _COMMIT_PATTERN.fullmatch(head):
        _fail("repository HEAD must resolve to an exact commit")
    status = _run_git(root, ["status", "--porcelain"])
    if status.strip():
        preview = "; ".join(status.splitlines()[:5])
        _fail(f"worktree is not clean: {preview}")
    return head


def _checked_regular_file(root: Path, given: Path) -> Path:
    if not isinstance(given, (str, os.PathLike)):
        _fail("identity file inputs must be filesystem paths")
    candidate_path = Path(given)
    candidate = Path(os.path.abspath(candidate_path if candidate_path.is_absolute() else root / candidate_path))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise RuntimeIdentityError(f"{candidate_path} is outside repo_root {root}") from exc
    if not relative.parts:
        _fail("repo_root itself cannot serve as an identity file")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            _fail(f"{relative} traverses a symlink at {part}")
    try:
        file_mode = current.lstat().st_mode
    except OSError as exc:
        raise RuntimeIdentityError(f"{relative} is missing or unreadable") from exc
    if not stat.S_ISREG(file_mode):
        _fail(f"{relative} is missing or is not a regular file")
    return current


def _hash_file(root: Path, path: Path) -> str:
    target = _checked_regular_file(root, path)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_runtime_identity(
    *,
    repo_root: Path,
    required_files: Mapping[str, Path],
    schedule_contract: Path,
    role_contract: Path,
    automation_tomls: Mapping[str, Path],
    live_control: Path,
    provider_routes: Mapping[str, str],
    schema_versions: Mapping[str, str],
    python_executable: str | None = None,
    package_inventory: Sequence[str] | None = None,
) -> dict[str, object]:
    """Return a deterministic, JSON-safe identity built only from explicit fixture inputs."""
    root = _validated_repo_root(repo_root)
    required = _validated_path_mapping(required_files, "required_files")
    automations = _validated_path_mapping(automation_tomls, "automation_tomls")
    for single in (schedule_contract, role_contract, live_control):
        if not isinstance(single, (str, os.PathLike)):
            _fail("contract and control inputs must be filesystem paths")
    routes = _validated_string_mapping(provider_routes, "provider_routes")
    schemas = _validated_string_mapping(schema_versions, "schema_versions")
    executable = _validated_optional_string(python_executable, "python_executable")
    inventory = _normalized_package_inventory(package_inventory)

    commit = _capture_git_state(root)
    payload: dict[str, Any] = {
        "identity_schema": _IDENTITY_SCHEMA,
        "git_commit": commit,
        "worktree_clean": True,
        "required_files_sha256": {label: _hash_file(root, path) for label, path in required.items()},
        "schedule_contract_sha256": _hash_file(root, Path(schedule_contract)),
        "role_contract_sha256": _hash_file(root, Path(role_contract)),
        "live_control_sha256": _hash_file(root, Path(live_control)),
        "automation_tomls_sha256": {label: _hash_file(root, path) for label, path in automations.items()},
        "provider_routes": dict(routes),
        "provider_routes_sha256": _json_sha256(routes),
        "schema_versions": dict(schemas),
        "schema_versions_sha256": _json_sha256(schemas),
        "python_executable": executable,
        "package_inventory": inventory,
        "package_inventory_sha256": _json_sha256(inventory),
    }
    payload["identity_sha256"] = _json_sha256(payload)
    return payload
