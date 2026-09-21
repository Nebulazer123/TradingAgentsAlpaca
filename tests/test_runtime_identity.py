"""Focused coverage for the fixture-only runtime identity capture."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from tradingagents.evals.runtime_identity import (
    RuntimeIdentityError,
    capture_runtime_identity,
    validate_runtime_identity,
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


def _flat_identity_body() -> dict[str, object]:
    return {
        "identity_schema": "runtime_identity/v1",
        "git_commit": "a" * 40,
        "worktree_clean": True,
        "required_files_sha256": {"lock": hashlib.sha256(b"lock").hexdigest()},
        "schedule_contract_sha256": hashlib.sha256(b"schedule").hexdigest(),
        "role_contract_sha256": hashlib.sha256(b"roles").hexdigest(),
        "live_control_sha256": hashlib.sha256(b"control").hexdigest(),
        "automation_tomls_sha256": {
            "daily": hashlib.sha256(b"daily").hexdigest()
        },
        "provider_routes": {"news": "alpaca-news"},
        "provider_routes_sha256": hashlib.sha256(
            _canonical_json({"news": "alpaca-news"}).encode("utf-8")
        ).hexdigest(),
        "schema_versions": {"decision_packet": "v2"},
        "schema_versions_sha256": hashlib.sha256(
            _canonical_json({"decision_packet": "v2"}).encode("utf-8")
        ).hexdigest(),
        "overnight_route": None,
        "overnight_route_sha256": None,
        "python_executable": "/opt/venv/bin/python3",
        "package_inventory": ["alpha==1.0"],
        "package_inventory_sha256": hashlib.sha256(
            _canonical_json(["alpha==1.0"]).encode("utf-8")
        ).hexdigest(),
    }


def _valid_identity() -> dict[str, object]:
    body = _flat_identity_body()
    body["identity_sha256"] = hashlib.sha256(
        _canonical_json(body).encode("utf-8")
    ).hexdigest()
    return body


def test_validate_accepts_the_exact_canonical_flat_payload():
    identity = _valid_identity()

    assert validate_runtime_identity(copy.deepcopy(identity)) == identity


def test_validate_rejects_the_obsolete_nested_legacy_shape():
    legacy = {
        "schema_version": "runtime_identity_v1",
        "captured_at": "2026-08-22T15:00:00Z",
        "repo": {"root": "/fixture/repo", "tracked_tree_clean": True},
        "packages": {"count": 2},
    }

    with pytest.raises(RuntimeIdentityError, match="fields are invalid"):
        validate_runtime_identity(legacy)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda i: i.pop("identity_schema"), id="missing_field"),
        pytest.param(lambda i: i.update({"extra": 1}), id="unknown_field"),
        pytest.param(
            lambda i: i.update({"identity_schema": "runtime_identity_v1"}),
            id="legacy_schema_value",
        ),
        pytest.param(lambda i: i.update({"git_commit": "A" * 40}), id="uppercase_commit"),
        pytest.param(lambda i: i.update({"git_commit": "a" * 39}), id="short_commit"),
        pytest.param(lambda i: i.update({"worktree_clean": 1}), id="truthy_not_true"),
        pytest.param(lambda i: i.update({"worktree_clean": False}), id="explicit_false"),
        pytest.param(
            lambda i: i["required_files_sha256"].update({"lock": "z" * 64}),
            id="bad_component_digest",
        ),
        pytest.param(
            lambda i: i["required_files_sha256"].clear(), id="empty_required_files"
        ),
        pytest.param(
            lambda i: i.update(
                {
                    "provider_routes_sha256": hashlib.sha256(b"other").hexdigest(),
                }
            ),
            id="routes_digest_mismatch",
        ),
        pytest.param(
            lambda i: i.update(
                {
                    "schema_versions_sha256": hashlib.sha256(b"other").hexdigest(),
                }
            ),
            id="schemas_digest_mismatch",
        ),
        pytest.param(
            lambda i: i.update({"overnight_route": {"llm_provider": "openai"}}),
            id="partial_route_labels",
        ),
        pytest.param(
            lambda i: i.update({"overnight_route": None, "overnight_route_sha256": "0" * 64}),
            id="route_pair_inconsistent",
        ),
        pytest.param(lambda i: i.update({"python_executable": ""}), id="blank_python"),
        pytest.param(lambda i: i.update({"python_executable": 7}), id="typed_python"),
        pytest.param(
            lambda i: i.update({"package_inventory": ["Alpha==1.0"]}),
            id="unnormalized_inventory",
        ),
        pytest.param(
            lambda i: i.update({"package_inventory": ["alpha==1.0", "alpha==1.0"]}),
            id="duplicate_inventory",
        ),
        pytest.param(
            lambda i: i.update({"package_inventory": ["beta==2.0"]}),
            id="inventory_digest_mismatch",
        ),
        pytest.param(
            lambda i: i.update({"identity_sha256": "0" * 64}),
            id="whole_digest_mismatch",
        ),
        pytest.param(
            lambda i: i.update({"identity_sha256": "g" * 64}),
            id="nonhex_whole_digest",
        ),
    ],
)
def test_validate_rejects_every_malformed_form(mutate):
    identity = mutate(_valid_identity())

    with pytest.raises(RuntimeIdentityError):
        validate_runtime_identity(identity)


def test_validate_rejects_non_object_inputs():
    for value in ([], "runtime_identity/v1", None, 7):
        with pytest.raises(RuntimeIdentityError):
            validate_runtime_identity(value)


def test_validate_accepts_captured_identity_round_trip(tmp_path: Path):
    repo = _build_repo(tmp_path)
    captured = capture_runtime_identity(**_kwargs(repo))

    assert validate_runtime_identity(copy.deepcopy(captured)) == captured


def test_external_automation_root_boundary_is_enforced(tmp_path: Path):
    repo = _build_repo(tmp_path)
    external = tmp_path / "external-automations"
    external_toml = external / "tradingagents-daily" / "automation.toml"
    _write(external_toml, '[job]\nname = "daily"\n')

    kwargs = _kwargs(repo)
    kwargs["automation_tomls"] = {
        "tradingagents-daily": external_toml,
    }
    kwargs["automation_root"] = external
    payload = capture_runtime_identity(**kwargs)
    expected_digest = hashlib.sha256(external_toml.read_bytes()).hexdigest()
    assert payload["automation_tomls_sha256"] == {
        "tradingagents-daily": expected_digest
    }

    symlinked = external / "alias" / "automation.toml"
    symlinked.parent.mkdir(parents=True, exist_ok=True)
    symlinked.symlink_to(external_toml)
    link_kwargs = dict(kwargs)
    link_kwargs["automation_tomls"] = {"alias": symlinked}
    with pytest.raises(RuntimeIdentityError, match="symlink"):
        capture_runtime_identity(**link_kwargs)

    outside_kwargs = dict(kwargs)
    outside_kwargs["automation_tomls"] = {"outside": repo / "automation" / "daily.toml"}
    with pytest.raises(RuntimeIdentityError, match="outside"):
        capture_runtime_identity(**outside_kwargs)

    missing_kwargs = dict(kwargs)
    missing_kwargs["automation_root"] = external / "absent"
    with pytest.raises(RuntimeIdentityError, match="automation_root"):
        capture_runtime_identity(**missing_kwargs)


def test_hostile_git_routing_environment_is_scrubbed(tmp_path: Path, monkeypatch):
    repo = _build_repo(tmp_path)
    hostile = tmp_path / "hostile"
    hostile.mkdir()
    monkeypatch.setenv("GIT_DIR", str(hostile / "fake.git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(hostile))
    monkeypatch.setenv("GIT_INDEX_FILE", str(hostile / "fake-index"))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(hostile / "objects"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")

    baseline_kwargs = _kwargs(repo)
    expected = capture_runtime_identity(**baseline_kwargs)

    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    monkeypatch.delenv("GIT_INDEX_FILE")
    monkeypatch.delenv("GIT_OBJECT_DIRECTORY")
    monkeypatch.delenv("GIT_CONFIG_COUNT")
    baseline = capture_runtime_identity(**_kwargs(repo))

    assert expected == baseline
    assert expected["git_commit"] == _head(repo)


def test_overnight_route_is_bound_with_component_and_whole_digests():
    body = _flat_identity_body()
    route = {
        "deep_think_llm": "gpt-5.4",
        "llm_provider": "openai",
        "quick_think_llm": "gpt-5.4-mini",
    }
    body["overnight_route"] = route
    body["overnight_route_sha256"] = hashlib.sha256(
        _canonical_json(route).encode("utf-8")
    ).hexdigest()
    body["identity_sha256"] = hashlib.sha256(
        _canonical_json(body).encode("utf-8")
    ).hexdigest()

    validated = validate_runtime_identity(copy.deepcopy(body))

    assert validated["overnight_route"] == route
    drifted = copy.deepcopy(body)
    drifted["overnight_route"]["deep_think_llm"] = "gpt-5.5-pro"
    drifted["overnight_route_sha256"] = hashlib.sha256(
        _canonical_json(drifted["overnight_route"]).encode("utf-8")
    ).hexdigest()
    drifted.pop("identity_sha256")
    drifted["identity_sha256"] = hashlib.sha256(
        _canonical_json(drifted).encode("utf-8")
    ).hexdigest()

    other = validate_runtime_identity(drifted)
    assert other["identity_sha256"] != validated["identity_sha256"]


def test_capture_rejects_structurally_empty_component_mappings(tmp_path: Path):
    repo = _build_repo(tmp_path)

    empty_required = _kwargs(repo)
    empty_required["required_files"] = {}
    with pytest.raises(RuntimeIdentityError, match="required_files must bind"):
        capture_runtime_identity(**empty_required)

    empty_automations = _kwargs(repo)
    empty_automations["automation_tomls"] = {}
    with pytest.raises(RuntimeIdentityError, match="automation_tomls must bind"):
        capture_runtime_identity(**empty_automations)

    empty_schemas = _kwargs(repo)
    empty_schemas["schema_versions"] = {}
    with pytest.raises(RuntimeIdentityError, match="schema_versions must bind"):
        capture_runtime_identity(**empty_schemas)


def _resealed_identity(mapping_field: str, mutate) -> dict[str, object]:
    """Mutate one component mapping, then recompute every affected digest."""

    identity = _valid_identity()
    mutate(identity[mapping_field])
    paired_digest_field = f"{mapping_field}_sha256"
    if paired_digest_field in identity:
        identity[paired_digest_field] = hashlib.sha256(
            _canonical_json(identity[mapping_field]).encode("utf-8")
        ).hexdigest()
    body = {
        key: value
        for key, value in identity.items()
        if key != "identity_sha256"
    }
    identity["identity_sha256"] = hashlib.sha256(
        _canonical_json(body).encode("utf-8")
    ).hexdigest()
    return identity


@pytest.mark.parametrize(
    ("mapping_field", "expected_message"),
    [
        ("required_files_sha256", "required_files_sha256 must bind"),
        ("automation_tomls_sha256", "automation_tomls_sha256 must bind"),
        ("schema_versions", "schema_versions must bind"),
    ],
)
def test_validate_rejects_empty_component_mappings_with_fresh_digests(
    mapping_field: str,
    expected_message: str,
):
    identity = _resealed_identity(mapping_field, lambda mapping: mapping.clear())

    with pytest.raises(RuntimeIdentityError, match=expected_message):
        validate_runtime_identity(identity)


def test_validate_accepts_intentionally_empty_provider_routes():
    identity = _resealed_identity("provider_routes", lambda mapping: mapping.clear())

    validated = validate_runtime_identity(identity)

    assert validated["provider_routes"] == {}
    assert validated["provider_routes_sha256"] == hashlib.sha256(
        _canonical_json({}).encode("utf-8")
    ).hexdigest()


def test_untracked_file_is_refused_under_hostile_global_status_config(
    tmp_path: Path, monkeypatch
):
    repo = _build_repo(tmp_path)
    fake_home = tmp_path / "hostile-home"
    fake_home.mkdir()
    (fake_home / ".gitconfig").write_text(
        "[status]\n\tshowUntrackedFiles = no\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(fake_home))
    _write(repo / "scratch.txt", "stray\n")

    with pytest.raises(RuntimeIdentityError, match="clean"):
        capture_runtime_identity(**_kwargs(repo))
