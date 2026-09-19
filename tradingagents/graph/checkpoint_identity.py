"""Pure, complete identities for evidence-safe LangGraph checkpoints.

This module deliberately knows nothing about Git, files, stores, providers, or
LangGraph persistence.  Callers must resolve those inputs before building an
identity, keeping resume compatibility explicit and independently auditable.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

CHECKPOINT_RUN_IDENTITY_SCHEMA_VERSION = 2

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@=-]{0,255}$")
_SECRET_FIELD = re.compile(
    r"(?:api[_-]?key|authorization|credential|password|secret|signature|token)",
    re.IGNORECASE,
)
_FORBIDDEN_BEHAVIOR_FIELD = re.compile(
    r"(?:environment|prompt|report)",
    re.IGNORECASE,
)
_SAFE_ROUTE_QUERY_FIELDS = frozenset(
    {
        "api-version",
        "api_version",
        "deployment",
        "organization",
        "project",
        "region",
        "tenant",
        "version",
    }
)
_SAFE_REASONING_SETTING_FIELDS = frozenset(
    {
        "adaptive_thinking",
        "budget",
        "budget_tokens",
        "effort",
        "enabled",
        "frequency_penalty",
        "include_reasoning",
        "include_thoughts",
        "max_completion_tokens",
        "max_output_tokens",
        "max_tokens",
        "min_p",
        "mode",
        "presence_penalty",
        "reasoning",
        "reasoning_budget",
        "reasoning_effort",
        "reasoning_summary",
        "seed",
        "temperature",
        "thinking",
        "timeout_seconds",
        "top_k",
        "top_p",
        "verbosity",
        "max_retries",
    }
)

_IDENTITY_FIELDS = frozenset(
    {
        "identity_schema_version",
        "clean_source_revision",
        "source_tree_dirty",
        "uv_lock_sha256",
        "selected_analysts",
        "asset_type",
        "max_debate_rounds",
        "max_risk_discuss_rounds",
        "max_analyst_tool_rounds",
        "max_recur_limit",
        "analyst_concurrency_limit",
        "tool_free_analysts",
        "requested_provider",
        "requested_quick_model",
        "requested_deep_model",
        "backend_route_identity",
        "output_language",
        "provider_reasoning_settings",
        "graph_topology_sha256",
        "agent_prompt_surface_sha256",
        "bound_tool_surface_sha256",
        "data_route_surface_sha256",
        "packet_handoff_schema_version",
        "learning_context_policy_identity",
        "trade_date_cutoff_policy_identity",
        "learning_evidence_predecessor",
        "decision_ledger_predecessor",
        "identity_sha256",
    }
)


class CheckpointRunIdentityError(ValueError):
    """Raised when a checkpoint identity is incomplete, unsafe, or noncanonical."""


def _secret_bearing_name(value: str) -> bool:
    """Recognize common secret-bearing names across snake, kebab, and camel case."""

    compact = re.sub(r"[^a-z0-9]", "", value.casefold())
    return bool(_SECRET_FIELD.search(value)) or compact == "key" or compact.endswith(
        ("apikey", "accesskey", "clientkey", "privatekey", "secretkey")
    )


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _identifier(value: object, *, field: str) -> str:
    if type(value) is not str or not _SAFE_IDENTIFIER.fullmatch(value):
        raise CheckpointRunIdentityError(f"{field} must be a canonical identifier")
    if _secret_bearing_name(value):
        raise CheckpointRunIdentityError(f"{field} must not contain a secret")
    return value


def _output_language(value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or "\n" in value:
        raise CheckpointRunIdentityError("output_language must be a canonical non-empty string")
    if _secret_bearing_name(value):
        raise CheckpointRunIdentityError("output_language must not contain a secret")
    return value


def _digest(value: object, *, field: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise CheckpointRunIdentityError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _positive_int(value: object, *, field: str, zero_allowed: bool = False) -> int:
    minimum = 0 if zero_allowed else 1
    if type(value) is not int or value < minimum:
        raise CheckpointRunIdentityError(f"{field} must be an integer >= {minimum}")
    return value


def _sequence(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (bytes, str)):
        raise CheckpointRunIdentityError(f"{field} must be a sequence of identifiers")
    normalized = tuple(_identifier(item, field=field) for item in value)
    if not normalized or len(set(normalized)) != len(normalized):
        raise CheckpointRunIdentityError(f"{field} must be non-empty and unique")
    return normalized


def _set_sequence(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (bytes, str)):
        raise CheckpointRunIdentityError(f"{field} must be a sequence of identifiers")
    return tuple(sorted({_identifier(item, field=field) for item in value}))


def _freeze_reasoning_settings(value: object, *, field: str = "provider_reasoning_settings") -> Any:
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str or not _SAFE_IDENTIFIER.fullmatch(key):
                raise CheckpointRunIdentityError(f"{field} contains a noncanonical key")
            if (
                key not in _SAFE_REASONING_SETTING_FIELDS
                or _FORBIDDEN_BEHAVIOR_FIELD.search(key)
            ):
                raise CheckpointRunIdentityError(f"{field} contains a forbidden key")
            normalized[key] = _freeze_reasoning_settings(item, field=field)
        return MappingProxyType(dict(sorted(normalized.items())))
    if isinstance(value, Sequence) and not isinstance(value, (bytes, str)):
        return tuple(_freeze_reasoning_settings(item, field=field) for item in value)
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is str and value == value.strip() and "\n" not in value:
        if "://" in value or _secret_bearing_name(value):
            raise CheckpointRunIdentityError(f"{field} must not contain a secret")
        return value
    raise CheckpointRunIdentityError(f"{field} contains a noncanonical value")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def normalize_backend_route_identity(value: object) -> str:
    """Return a normalized route while stripping credentials and secret query keys."""

    if type(value) is not str or value != value.strip() or "\n" in value:
        raise CheckpointRunIdentityError("backend_route_identity must be a canonical route")
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise CheckpointRunIdentityError("backend_route_identity must be an HTTP(S) route")
    try:
        port = parsed.port
    except ValueError as exc:
        raise CheckpointRunIdentityError("backend_route_identity has an invalid port") from exc
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    query: list[tuple[str, str]] = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        normalized_key = key.casefold()
        if _secret_bearing_name(key):
            continue
        if normalized_key not in _SAFE_ROUTE_QUERY_FIELDS:
            raise CheckpointRunIdentityError(
                "backend_route_identity contains an unregistered query dimension"
            )
        query.append((normalized_key, item))
    if len({key for key, _ in query}) != len(query):
        raise CheckpointRunIdentityError("backend_route_identity repeats a query dimension")
    query.sort()
    return urlunsplit(
        (
            parsed.scheme.lower(),
            netloc,
            parsed.path or "/",
            urlencode(query, doseq=True),
            "",
        )
    )


@dataclass(frozen=True, slots=True, init=False)
class CheckpointRunIdentity:
    """Immutable, canonical material that is allowed to select a checkpoint."""

    identity_schema_version: int
    clean_source_revision: str
    source_tree_dirty: bool
    uv_lock_sha256: str
    selected_analysts: tuple[str, ...]
    asset_type: str
    max_debate_rounds: int
    max_risk_discuss_rounds: int
    max_analyst_tool_rounds: int
    max_recur_limit: int
    analyst_concurrency_limit: int
    tool_free_analysts: tuple[str, ...]
    requested_provider: str
    requested_quick_model: str
    requested_deep_model: str
    backend_route_identity: str
    output_language: str
    provider_reasoning_settings: Mapping[str, Any]
    graph_topology_sha256: str
    agent_prompt_surface_sha256: str
    bound_tool_surface_sha256: str
    data_route_surface_sha256: str
    packet_handoff_schema_version: int
    learning_context_policy_identity: str
    trade_date_cutoff_policy_identity: str
    learning_evidence_predecessor: str
    decision_ledger_predecessor: str
    identity_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "identity_schema_version": self.identity_schema_version,
            "clean_source_revision": self.clean_source_revision,
            "source_tree_dirty": self.source_tree_dirty,
            "uv_lock_sha256": self.uv_lock_sha256,
            "selected_analysts": list(self.selected_analysts),
            "asset_type": self.asset_type,
            "max_debate_rounds": self.max_debate_rounds,
            "max_risk_discuss_rounds": self.max_risk_discuss_rounds,
            "max_analyst_tool_rounds": self.max_analyst_tool_rounds,
            "max_recur_limit": self.max_recur_limit,
            "analyst_concurrency_limit": self.analyst_concurrency_limit,
            "tool_free_analysts": list(self.tool_free_analysts),
            "requested_provider": self.requested_provider,
            "requested_quick_model": self.requested_quick_model,
            "requested_deep_model": self.requested_deep_model,
            "backend_route_identity": self.backend_route_identity,
            "output_language": self.output_language,
            "provider_reasoning_settings": _thaw(self.provider_reasoning_settings),
            "graph_topology_sha256": self.graph_topology_sha256,
            "agent_prompt_surface_sha256": self.agent_prompt_surface_sha256,
            "bound_tool_surface_sha256": self.bound_tool_surface_sha256,
            "data_route_surface_sha256": self.data_route_surface_sha256,
            "packet_handoff_schema_version": self.packet_handoff_schema_version,
            "learning_context_policy_identity": self.learning_context_policy_identity,
            "trade_date_cutoff_policy_identity": self.trade_date_cutoff_policy_identity,
            "learning_evidence_predecessor": self.learning_evidence_predecessor,
            "decision_ledger_predecessor": self.decision_ledger_predecessor,
            "identity_sha256": self.identity_sha256,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


def build_checkpoint_run_identity(
    *,
    identity_schema_version: int,
    clean_source_revision: str,
    source_tree_dirty: bool,
    uv_lock_sha256: str,
    selected_analysts: Sequence[str],
    asset_type: str,
    max_debate_rounds: int,
    max_risk_discuss_rounds: int,
    max_analyst_tool_rounds: int,
    max_recur_limit: int,
    analyst_concurrency_limit: int,
    tool_free_analysts: Sequence[str],
    requested_provider: str,
    requested_quick_model: str,
    requested_deep_model: str,
    backend_route_identity: str,
    output_language: str,
    provider_reasoning_settings: Mapping[str, Any],
    graph_topology_sha256: str,
    agent_prompt_surface_sha256: str,
    bound_tool_surface_sha256: str,
    data_route_surface_sha256: str,
    packet_handoff_schema_version: int,
    learning_context_policy_identity: str,
    trade_date_cutoff_policy_identity: str,
    learning_evidence_predecessor: str,
    decision_ledger_predecessor: str,
) -> CheckpointRunIdentity:
    """Build one complete identity from already-resolved, behavior-affecting inputs."""

    if identity_schema_version != CHECKPOINT_RUN_IDENTITY_SCHEMA_VERSION:
        raise CheckpointRunIdentityError("identity_schema_version is not supported")
    if source_tree_dirty is not False:
        raise CheckpointRunIdentityError("source_tree_dirty must be exactly false")
    if type(clean_source_revision) is not str or _GIT_REVISION.fullmatch(clean_source_revision) is None:
        raise CheckpointRunIdentityError("clean_source_revision must be a clean lowercase Git revision")
    material: dict[str, object] = {
        "identity_schema_version": identity_schema_version,
        "clean_source_revision": clean_source_revision,
        "source_tree_dirty": False,
        "uv_lock_sha256": _digest(uv_lock_sha256, field="uv_lock_sha256"),
        "selected_analysts": list(_sequence(selected_analysts, field="selected_analysts")),
        "asset_type": _identifier(asset_type, field="asset_type"),
        "max_debate_rounds": _positive_int(
            max_debate_rounds,
            field="max_debate_rounds",
            zero_allowed=True,
        ),
        "max_risk_discuss_rounds": _positive_int(
            max_risk_discuss_rounds,
            field="max_risk_discuss_rounds",
            zero_allowed=True,
        ),
        "max_analyst_tool_rounds": _positive_int(
            max_analyst_tool_rounds,
            field="max_analyst_tool_rounds",
            zero_allowed=True,
        ),
        "max_recur_limit": _positive_int(max_recur_limit, field="max_recur_limit"),
        "analyst_concurrency_limit": _positive_int(
            analyst_concurrency_limit,
            field="analyst_concurrency_limit",
        ),
        "tool_free_analysts": list(
            _set_sequence(tool_free_analysts, field="tool_free_analysts")
        ),
        "requested_provider": _identifier(requested_provider, field="requested_provider"),
        "requested_quick_model": _identifier(
            requested_quick_model,
            field="requested_quick_model",
        ),
        "requested_deep_model": _identifier(
            requested_deep_model,
            field="requested_deep_model",
        ),
        "backend_route_identity": normalize_backend_route_identity(backend_route_identity),
        "output_language": _output_language(output_language),
        "provider_reasoning_settings": _thaw(_freeze_reasoning_settings(provider_reasoning_settings)),
        "graph_topology_sha256": _digest(
            graph_topology_sha256,
            field="graph_topology_sha256",
        ),
        "agent_prompt_surface_sha256": _digest(
            agent_prompt_surface_sha256,
            field="agent_prompt_surface_sha256",
        ),
        "bound_tool_surface_sha256": _digest(
            bound_tool_surface_sha256,
            field="bound_tool_surface_sha256",
        ),
        "data_route_surface_sha256": _digest(
            data_route_surface_sha256,
            field="data_route_surface_sha256",
        ),
        "packet_handoff_schema_version": _positive_int(
            packet_handoff_schema_version,
            field="packet_handoff_schema_version",
        ),
        "learning_context_policy_identity": _identifier(
            learning_context_policy_identity,
            field="learning_context_policy_identity",
        ),
        "trade_date_cutoff_policy_identity": _identifier(
            trade_date_cutoff_policy_identity,
            field="trade_date_cutoff_policy_identity",
        ),
        "learning_evidence_predecessor": _digest(
            learning_evidence_predecessor, field="learning_evidence_predecessor",
        ),
        "decision_ledger_predecessor": _digest(
            decision_ledger_predecessor, field="decision_ledger_predecessor",
        ),
    }
    digest = _sha256(material)
    identity = object.__new__(CheckpointRunIdentity)
    for field, value in material.items():
        if field == "selected_analysts" or field == "tool_free_analysts":
            value = tuple(value)
        elif field == "provider_reasoning_settings":
            value = _freeze_reasoning_settings(value)
        object.__setattr__(identity, field, value)
    object.__setattr__(identity, "identity_sha256", digest)
    return identity


def validate_checkpoint_run_identity(value: object) -> CheckpointRunIdentity:
    """Canonically rebuild a serialized identity and reject any drift or extras."""

    if not isinstance(value, Mapping) or set(value) != _IDENTITY_FIELDS:
        raise CheckpointRunIdentityError("checkpoint run identity fields are invalid")
    payload = dict(value)
    supplied_digest = _digest(payload.pop("identity_sha256"), field="identity_sha256")
    rebuilt = build_checkpoint_run_identity(**payload)
    if supplied_digest != rebuilt.identity_sha256:
        raise CheckpointRunIdentityError("checkpoint run identity digest does not match")
    if _canonical_json_bytes(value) != rebuilt.canonical_json_bytes():
        raise CheckpointRunIdentityError("checkpoint run identity is not canonical")
    return rebuilt
