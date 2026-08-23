"""Deterministic runtime identity capture and strict validation.

The canonical identity is the flat ``runtime_identity/v1`` payload produced by
:func:`capture_runtime_identity`.  It binds the exact worktree commit, clean
state, source lockfiles, authority-source file digests, external automation
TOML digests, provider/schema mappings, Python executable, normalized package
inventory, and a whole-payload digest.  Identities are nonsecret by contract:
names and hashes only, never credentials, endpoints, or file contents.
"""

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
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_CHUNK_SIZE_BYTES = 1 << 20
_GIT_TIMEOUT_SECONDS = 30
_OVERNIGHT_ROUTE_LABELS = frozenset(
    {"llm_provider", "quick_think_llm", "deep_think_llm"}
)
_IDENTITY_FIELDS = frozenset(
    {
        "identity_schema",
        "git_commit",
        "worktree_clean",
        "required_files_sha256",
        "schedule_contract_sha256",
        "role_contract_sha256",
        "live_control_sha256",
        "automation_tomls_sha256",
        "provider_routes",
        "provider_routes_sha256",
        "schema_versions",
        "schema_versions_sha256",
        "overnight_route",
        "overnight_route_sha256",
        "python_executable",
        "package_inventory",
        "package_inventory_sha256",
        "identity_sha256",
    }
)


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


def _git_environment() -> dict[str, str]:
    """Drop inherited GIT_* routing so a hostile environment cannot redirect reads."""

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


def _run_git(root: Path, arguments: list[str]) -> str:
    command = [
        "git",
        "-C",
        str(root),
        "--no-pager",
        "-c",
        "core.optionalLocks=false",
        *arguments,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_git_environment(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        _fail(f"git {' '.join(arguments)} timed out after {_GIT_TIMEOUT_SECONDS}s")
    except OSError as exc:
        _fail(f"git {' '.join(arguments)} could not run: {exc}")
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown failure"
        _fail(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def _capture_git_state(root: Path) -> str:
    head = _run_git(root, ["rev-parse", "HEAD"]).strip()
    if not _COMMIT_PATTERN.fullmatch(head):
        _fail("repository HEAD must resolve to an exact commit")
    # --untracked-files is pinned on the command line so inherited user-global
    # config (for example status.showUntrackedFiles=no) cannot hide dirt.
    status = _run_git(root, ["status", "--porcelain", "--untracked-files=all"])
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
    try:
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK_SIZE_BYTES), b""):
                digest.update(chunk)
    except OSError as exc:
        _fail(f"{target} could not be read: {exc}")
    return digest.hexdigest()


def _validated_boundary_root(boundary: Path | None, field: str) -> Path | None:
    if boundary is None:
        return None
    if not isinstance(boundary, (str, os.PathLike)):
        _fail(f"{field} must be a filesystem path")
    root = Path(os.path.realpath(Path(boundary)))
    if not root.is_dir():
        _fail(f"{field} must be an existing directory")
    return root


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
    overnight_route: Mapping[str, str] | None = None,
    automation_root: Path | None = None,
) -> dict[str, object]:
    """Return a deterministic, JSON-safe identity built only from explicit inputs.

    Repository files, contracts, and live control stay constrained to
    ``repo_root``.  When ``automation_root`` is provided it becomes the exact
    containment boundary for ``automation_tomls`` instead of ``repo_root``;
    external TOMLs must be regular non-symlink files inside that directory.
    """

    root = _validated_repo_root(repo_root)
    automations_boundary = _validated_boundary_root(automation_root, "automation_root")
    required = _validated_path_mapping(required_files, "required_files")
    automations = _validated_path_mapping(automation_tomls, "automation_tomls")
    for single in (schedule_contract, role_contract, live_control):
        if not isinstance(single, (str, os.PathLike)):
            _fail("contract and control inputs must be filesystem paths")
    routes = _validated_string_mapping(provider_routes, "provider_routes")
    schemas = _validated_string_mapping(schema_versions, "schema_versions")
    if not required:
        _fail("required_files must bind at least one required source file")
    if not automations:
        _fail("automation_tomls must bind at least one automation TOML")
    if not schemas:
        _fail("schema_versions must bind at least one schema version")
    executable = _validated_optional_string(python_executable, "python_executable")
    inventory = _normalized_package_inventory(package_inventory)
    route: dict[str, str] | None = None
    if overnight_route is not None:
        route = dict(_validated_string_mapping(overnight_route, "overnight_route"))

    commit = _capture_git_state(root)
    payload: dict[str, Any] = {
        "identity_schema": _IDENTITY_SCHEMA,
        "git_commit": commit,
        "worktree_clean": True,
        "required_files_sha256": {
            label: _hash_file(root, path) for label, path in required.items()
        },
        "schedule_contract_sha256": _hash_file(root, Path(schedule_contract)),
        "role_contract_sha256": _hash_file(root, Path(role_contract)),
        "live_control_sha256": _hash_file(root, Path(live_control)),
        "automation_tomls_sha256": {
            label: _hash_file(
                automations_boundary if automations_boundary is not None else root,
                path,
            )
            for label, path in automations.items()
        },
        "provider_routes": dict(routes),
        "provider_routes_sha256": _json_sha256(routes),
        "schema_versions": dict(schemas),
        "schema_versions_sha256": _json_sha256(schemas),
        "overnight_route": route,
        "overnight_route_sha256": None if route is None else _json_sha256(route),
        "python_executable": executable,
        "package_inventory": inventory,
        "package_inventory_sha256": _json_sha256(inventory),
    }
    payload["identity_sha256"] = _json_sha256(payload)
    return payload


def _validated_identity_sha256(value: object, field: str) -> str:
    if type(value) is not str or not _SHA256_PATTERN.fullmatch(value):
        _fail(f"{field} must be a lowercase sha256 hex digest")
    return value


def _validated_identity_string_mapping(
    value: object,
    field: str,
    *,
    labels: frozenset[str] | None = None,
) -> dict[str, str]:
    if not isinstance(value, Mapping) or isinstance(value, (str, bytes)):
        _fail(f"{field} must be an object")
    keys = set(value)
    if not all(type(key) is str for key in keys):
        _fail(f"{field} keys must be strings")
    if labels is not None and keys != set(labels):
        _fail(f"{field} must bind exactly the canonical labels")
    validated: dict[str, str] = {}
    for label, item in value.items():
        if type(label) is not str or not label.strip():
            _fail(f"{field} labels must be non-empty strings")
        if type(item) is not str or not item.strip():
            _fail(f"{field}[{label!r}] must be a non-empty string")
        validated[label] = item
    return validated


def _validated_identity_digest_mapping(value: object, field: str) -> dict[str, str]:
    validated = _validated_identity_string_mapping(value, field)
    for label, digest in validated.items():
        _validated_identity_sha256(digest, f"{field}[{label!r}]")
    return validated


def validate_runtime_identity(value: object) -> dict[str, object]:
    """Strictly validate one flat ``runtime_identity/v1`` payload.

    Requires the exact canonical field set with exact types, rejects every
    missing/extra/malformed/obsolete (nested legacy) shape, verifies each
    component mapping digest and the whole-payload ``identity_sha256``, and
    returns a plain JSON-safe copy.  Every invalid form raises
    :class:`RuntimeIdentityError`.
    """

    if not isinstance(value, Mapping) or isinstance(value, (str, bytes)):
        _fail("runtime identity must be a JSON object")
    keys = set(value)
    if not all(type(key) is str for key in keys):
        _fail("runtime identity keys must be strings")
    if keys != set(_IDENTITY_FIELDS):
        missing = sorted(set(_IDENTITY_FIELDS) - keys)
        unknown = sorted(keys - set(_IDENTITY_FIELDS))
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unknown:
            detail.append("unknown " + ", ".join(unknown))
        raise RuntimeIdentityError(
            "runtime identity fields are invalid"
            + (": " + "; ".join(detail) if detail else "")
        )

    schema = value["identity_schema"]
    if type(schema) is not str or schema != _IDENTITY_SCHEMA:
        _fail('identity_schema must be exactly "runtime_identity/v1"')
    commit = value["git_commit"]
    if type(commit) is not str or not _COMMIT_PATTERN.fullmatch(commit):
        _fail("git_commit must be an exact lowercase git commit hash")
    if value["worktree_clean"] is not True:
        _fail("worktree_clean must be exactly true")

    required_files = _validated_identity_digest_mapping(
        value["required_files_sha256"], "required_files_sha256"
    )
    if not required_files:
        _fail("required_files_sha256 must bind at least one required source file")
    schedule_digest = _validated_identity_sha256(
        value["schedule_contract_sha256"], "schedule_contract_sha256"
    )
    role_digest = _validated_identity_sha256(
        value["role_contract_sha256"], "role_contract_sha256"
    )
    control_digest = _validated_identity_sha256(
        value["live_control_sha256"], "live_control_sha256"
    )
    automation_digests = _validated_identity_digest_mapping(
        value["automation_tomls_sha256"], "automation_tomls_sha256"
    )
    if not automation_digests:
        _fail("automation_tomls_sha256 must bind at least one automation TOML")

    routes = _validated_identity_string_mapping(value["provider_routes"], "provider_routes")
    schemas = _validated_identity_string_mapping(value["schema_versions"], "schema_versions")
    if not schemas:
        _fail("schema_versions must bind at least one schema version")
    routes_digest = _validated_identity_sha256(
        value["provider_routes_sha256"], "provider_routes_sha256"
    )
    schemas_digest = _validated_identity_sha256(
        value["schema_versions_sha256"], "schema_versions_sha256"
    )
    if routes_digest != _json_sha256(routes):
        _fail("provider_routes_sha256 does not match provider_routes")
    if schemas_digest != _json_sha256(schemas):
        _fail("schema_versions_sha256 does not match schema_versions")

    route_value = value["overnight_route"]
    route_digest_value = value["overnight_route_sha256"]
    route: dict[str, str] | None
    route_digest: str | None
    if route_value is None and route_digest_value is None:
        route = None
        route_digest = None
    else:
        route = _validated_identity_string_mapping(
            route_value, "overnight_route", labels=_OVERNIGHT_ROUTE_LABELS
        )
        route_digest = _validated_identity_sha256(
            route_digest_value, "overnight_route_sha256"
        )
        if route_digest != _json_sha256(route):
            _fail("overnight_route_sha256 does not match overnight_route")

    executable = value["python_executable"]
    if executable is not None and (
        type(executable) is not str or not executable.strip()
    ):
        _fail("python_executable must be a non-empty string when provided")

    inventory_value = value["package_inventory"]
    if isinstance(inventory_value, (str, bytes)) or not isinstance(inventory_value, Sequence):
        _fail("package_inventory must be a list of name==version strings")
    inventory: list[str] = []
    for entry in inventory_value:
        if type(entry) is not str or not entry.strip():
            _fail("package_inventory entries must be non-empty strings")
        inventory.append(entry)
    normalized = sorted({entry.strip().lower() for entry in inventory})
    if inventory != normalized:
        _fail("package_inventory must already be normalized, deduplicated, and sorted")
    inventory_digest = _validated_identity_sha256(
        value["package_inventory_sha256"], "package_inventory_sha256"
    )
    if inventory_digest != _json_sha256(normalized):
        _fail("package_inventory_sha256 does not match package_inventory")

    identity: dict[str, object] = {
        "identity_schema": schema,
        "git_commit": commit,
        "worktree_clean": True,
        "required_files_sha256": required_files,
        "schedule_contract_sha256": schedule_digest,
        "role_contract_sha256": role_digest,
        "live_control_sha256": control_digest,
        "automation_tomls_sha256": automation_digests,
        "provider_routes": routes,
        "provider_routes_sha256": routes_digest,
        "schema_versions": schemas,
        "schema_versions_sha256": schemas_digest,
        "overnight_route": route,
        "overnight_route_sha256": route_digest,
        "python_executable": executable,
        "package_inventory": normalized,
        "package_inventory_sha256": inventory_digest,
    }
    whole = _validated_identity_sha256(value["identity_sha256"], "identity_sha256")
    body = {key: item for key, item in identity.items() if key != "identity_sha256"}
    if whole != _json_sha256(body):
        _fail("identity_sha256 does not match the whole payload")
    identity["identity_sha256"] = whole
    return identity
