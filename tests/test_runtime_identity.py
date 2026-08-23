"""Focused coverage for the fixture-only runtime identity capture."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from tradingagents.evals.runtime_identity import (
    RuntimeIdentityError,
    capture_runtime_identity,
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "user.name=fixture",
            *arguments,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


def _build_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write(repo / "locks" / "requirements-lock.txt", "pandas==2.0.3\n")
    _write(repo / "contracts" / "schedule.json", '{"cadence": "weekdays"}\n')
    _write(repo / "contracts" / "role.json", '{"role": "supervisor"}\n')
    _write(repo / "automation" / "daily.toml", '[job]\nname = "daily"\n')
    _write(repo / "policy" / "live_control.json", '{"mode": "paper"}\n')
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    return repo


def _kwargs(repo: Path) -> dict[str, object]:
    return {
        "repo_root": repo,
        "required_files": {"lock": repo / "locks" / "requirements-lock.txt"},
        "schedule_contract": repo / "contracts" / "schedule.json",
        "role_contract": repo / "contracts" / "role.json",
        "automation_tomls": {"daily": repo / "automation" / "daily.toml"},
        "live_control": repo / "policy" / "live_control.json",
        "provider_routes": {"news": "alpaca-news", "prices": "iex"},
        "schema_versions": {"decision_packet": "v2"},
    }


def _head(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def test_identity_is_deterministic_json_safe_and_complete(tmp_path: Path):
    repo = _build_repo(tmp_path)

    first = capture_runtime_identity(**_kwargs(repo))
    second = capture_runtime_identity(**_kwargs(repo))

    assert first == second
    assert first["identity_schema"] == "runtime_identity/v1"
    assert first["worktree_clean"] is True
    assert first["git_commit"] == _head(repo)
    lock_digest = hashlib.sha256((repo / "locks" / "requirements-lock.txt").read_bytes()).hexdigest()
    assert first["required_files_sha256"] == {"lock": lock_digest}
    schedule_digest = hashlib.sha256((repo / "contracts" / "schedule.json").read_bytes()).hexdigest()
    assert first["schedule_contract_sha256"] == schedule_digest
    role_digest = hashlib.sha256((repo / "contracts" / "role.json").read_bytes()).hexdigest()
    assert first["role_contract_sha256"] == role_digest
    control_digest = hashlib.sha256((repo / "policy" / "live_control.json").read_bytes()).hexdigest()
    assert first["live_control_sha256"] == control_digest
    daily_digest = hashlib.sha256((repo / "automation" / "daily.toml").read_bytes()).hexdigest()
    assert first["automation_tomls_sha256"] == {"daily": daily_digest}
    assert first["provider_routes"] == {"news": "alpaca-news", "prices": "iex"}
    assert first["schema_versions"] == {"decision_packet": "v2"}
    assert first["python_executable"] is None
    assert first["package_inventory"] == []
    assert json.loads(json.dumps(first, allow_nan=False)) == first


def test_python_executable_is_recorded_verbatim(tmp_path: Path):
    repo = _build_repo(tmp_path)

    payload = capture_runtime_identity(python_executable="/opt/venv/bin/python3", **_kwargs(repo))

    assert payload["python_executable"] == "/opt/venv/bin/python3"


@pytest.mark.parametrize("mutation", ["untracked", "modified"])
def test_dirty_worktree_is_rejected(tmp_path: Path, mutation: str):
    repo = _build_repo(tmp_path)
    if mutation == "untracked":
        _write(repo / "scratch.txt", "stray\n")
    else:
        _write(repo / "policy" / "live_control.json", '{"mode": "live"}\n')

    with pytest.raises(RuntimeIdentityError, match="clean"):
        capture_runtime_identity(**_kwargs(repo))


def test_symlinked_file_and_symlink_reachable_file_are_rejected(tmp_path: Path):
    repo = _build_repo(tmp_path)
    linked_file = repo / "locks" / "alias-lock.txt"
    linked_file.symlink_to(repo / "locks" / "requirements-lock.txt")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "alias")

    file_kwargs = _kwargs(repo)
    file_kwargs["required_files"]["alias"] = linked_file
    with pytest.raises(RuntimeIdentityError, match="symlink"):
        capture_runtime_identity(**file_kwargs)

    _write(repo / "vendor" / "actual" / "note.txt", "hello\n")
    link_dir = repo / "vendor" / "linked"
    link_dir.symlink_to("actual", target_is_directory=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "vendor links")

    dir_kwargs = _kwargs(repo)
    dir_kwargs["role_contract"] = link_dir / "note.txt"
    with pytest.raises(RuntimeIdentityError, match="symlink"):
        capture_runtime_identity(**dir_kwargs)


def test_missing_and_non_regular_paths_are_rejected(tmp_path: Path):
    repo = _build_repo(tmp_path)

    missing_kwargs = _kwargs(repo)
    missing_kwargs["required_files"]["ghost"] = repo / "locks" / "absent.txt"
    with pytest.raises(RuntimeIdentityError, match="missing"):
        capture_runtime_identity(**missing_kwargs)

    directory_kwargs = _kwargs(repo)
    directory_kwargs["role_contract"] = repo / "contracts"
    with pytest.raises(RuntimeIdentityError, match="regular"):
        capture_runtime_identity(**directory_kwargs)


def test_paths_outside_repo_root_are_rejected(tmp_path: Path):
    repo = _build_repo(tmp_path)
    outside = tmp_path / "outside.txt"
    _write(outside, "external\n")

    kwargs = _kwargs(repo)
    kwargs["required_files"]["outside"] = outside
    with pytest.raises(RuntimeIdentityError, match="outside"):
        capture_runtime_identity(**kwargs)


def test_package_inventory_is_normalized_sorted_unique_lowercase_and_hashed(tmp_path: Path):
    repo = _build_repo(tmp_path)
    kwargs = _kwargs(repo)

    payload = capture_runtime_identity(
        package_inventory=[" Beta ", "alpha", "ALPHA", "beta", " gamma "],
        **kwargs,
    )

    assert payload["package_inventory"] == ["alpha", "beta", "gamma"]
    expected_digest = hashlib.sha256(_canonical_json(["alpha", "beta", "gamma"]).encode("utf-8")).hexdigest()
    assert payload["package_inventory_sha256"] == expected_digest

    baseline = capture_runtime_identity(**kwargs)
    assert baseline["package_inventory"] == []
    assert baseline["package_inventory_sha256"] == hashlib.sha256(_canonical_json([]).encode("utf-8")).hexdigest()


def test_content_changes_change_hashes_and_identity(tmp_path: Path):
    repo = _build_repo(tmp_path)
    before = capture_runtime_identity(**_kwargs(repo))

    _write(repo / "locks" / "requirements-lock.txt", "pandas==2.2.0\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "bump lock")
    after = capture_runtime_identity(**_kwargs(repo))

    assert after["required_files_sha256"]["lock"] != before["required_files_sha256"]["lock"]
    assert after["schedule_contract_sha256"] == before["schedule_contract_sha256"]
    assert after["git_commit"] != before["git_commit"]
    assert after["identity_sha256"] != before["identity_sha256"]


def test_metadata_changes_change_mapping_hashes(tmp_path: Path):
    repo = _build_repo(tmp_path)
    before = capture_runtime_identity(**_kwargs(repo))
    kwargs = _kwargs(repo)
    kwargs["provider_routes"] = {"news": "polygon-news", "prices": "iex"}

    after = capture_runtime_identity(**kwargs)

    assert after["provider_routes"] == {"news": "polygon-news", "prices": "iex"}
    assert after["provider_routes_sha256"] != before["provider_routes_sha256"]
    assert after["schema_versions_sha256"] == before["schema_versions_sha256"]
    assert after["identity_sha256"] != before["identity_sha256"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_routes", {"news": 3}),
        ("provider_routes", {"news": ""}),
        ("provider_routes", ["news"]),
        ("schema_versions", {"packet": None}),
        ("required_files", {"lock": 17}),
        ("package_inventory", "alpha"),
        ("package_inventory", ["fine", 7]),
        ("package_inventory", ["   "]),
        ("python_executable", ""),
        ("python_executable", 3),
    ],
)
def test_invalid_values_are_rejected(tmp_path: Path, field: str, value: object):
    repo = _build_repo(tmp_path)
    kwargs = _kwargs(repo)
    kwargs[field] = value

    with pytest.raises(RuntimeIdentityError):
        capture_runtime_identity(**kwargs)


def test_identity_hash_binds_the_whole_payload(tmp_path: Path):
    repo = _build_repo(tmp_path)

    payload = capture_runtime_identity(**_kwargs(repo))

    body = {key: value for key, value in payload.items() if key != "identity_sha256"}
    expected = hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()
    assert payload["identity_sha256"] == expected
