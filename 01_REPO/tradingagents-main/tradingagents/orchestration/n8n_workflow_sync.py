"""Sync source-controlled n8n observer workflows through the local public API."""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from tradingagents.orchestration.n8n_api_sync import (
    DEFAULT_N8N_API_BASE_URL,
    N8NApiSyncError,
    resolve_n8n_api_key,
)

DEFAULT_WORKFLOW_DIR = Path("n8n/workflows")


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _source_without_secret(source: str | None) -> str:
    return source or "unknown"


def _is_archived_workflow(item: dict[str, Any]) -> bool:
    """Return whether an n8n workflow list/detail item is archived."""

    return bool(item.get("isArchived") or item.get("archived"))


class N8NWorkflowApiClient:
    """Small n8n public API client for source-controlled workflow sync."""

    def __init__(
        self,
        *,
        api_base_url: str = DEFAULT_N8N_API_BASE_URL,
        api_key: str,
        timeout_seconds: float = 30.0,
    ):
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, path: str, *, payload: Any | None = None) -> Any:
        request = urllib.request.Request(
            f"{self.api_base_url}{path}",
            data=_json_bytes(payload) if payload is not None else None,
            headers={
                "X-N8N-API-KEY": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise N8NApiSyncError(
                f"n8n API {method} {path} failed with HTTP {exc.code}: {body[:500]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise N8NApiSyncError(f"n8n API {method} {path} failed: {exc}") from exc
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return body

    def list_workflows(self) -> list[dict[str, Any]]:
        payload = self.request("GET", "/workflows?limit=250")
        return list(payload.get("data") or []) if isinstance(payload, dict) else []

    def create_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        create_payload = {key: value for key, value in payload.items() if key != "active"}
        result = self.request("POST", "/workflows", payload=create_payload)
        return dict(result) if isinstance(result, dict) else {}

    def update_workflow(self, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        update_payload = {key: value for key, value in payload.items() if key != "active"}
        result = self.request(
            "PUT",
            f"/workflows/{urllib.parse.quote(workflow_id)}",
            payload=update_payload,
        )
        return dict(result) if isinstance(result, dict) else {}


def _workflow_paths(workflow_dir: Path) -> list[Path]:
    return sorted(path for path in workflow_dir.glob("*.json") if path.is_file())


def _load_source_workflow(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise N8NApiSyncError(f"n8n workflow file must contain an object: {path}")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise N8NApiSyncError(f"n8n workflow file is missing name: {path}")
    return {
        "name": name,
        "nodes": list(raw.get("nodes") or []),
        "connections": dict(raw.get("connections") or {}),
        "settings": dict(raw.get("settings") or {}),
        "active": False,
    }


def sync_n8n_workflows(
    *,
    api_base_url: str = DEFAULT_N8N_API_BASE_URL,
    api_key: str | None = None,
    api_key_source: str | None = None,
    api_key_env: str = "N8N_API_KEY",
    api_key_sqlite_db: str | Path | None = None,
    workflow_dir: Path = DEFAULT_WORKFLOW_DIR,
    workflow_paths: list[Path] | None = None,
    dry_run: bool = False,
    output_dir: Path = Path("results/n8n_evaluations"),
    client: N8NWorkflowApiClient | None = None,
) -> dict[str, Any]:
    """Create or update source-controlled n8n workflows, keeping them inactive."""

    key_source = api_key_source
    if client is None:
        key, key_source = resolve_n8n_api_key(
            api_key=api_key,
            env_name=api_key_env,
            sqlite_db_path=api_key_sqlite_db,
        )
        client = N8NWorkflowApiClient(api_base_url=api_base_url, api_key=key)

    paths = workflow_paths if workflow_paths is not None else _workflow_paths(workflow_dir)
    source_workflows = [
        {"path": str(path), "payload": _load_source_workflow(path)}
        for path in paths
    ]
    existing = client.list_workflows()
    current_existing = [item for item in existing if not _is_archived_workflow(item)]
    archived_existing = [item for item in existing if _is_archived_workflow(item)]
    existing_by_name: dict[str, dict[str, Any]] = {}
    current_name_counts = Counter(
        str(item.get("name") or "") for item in current_existing if item.get("name")
    )
    archived_name_counts = Counter(
        str(item.get("name") or "") for item in archived_existing if item.get("name")
    )
    all_name_counts = Counter(
        str(item.get("name") or "") for item in existing if item.get("name")
    )
    for item in current_existing:
        name = str(item.get("name") or "")
        if name and name not in existing_by_name:
            existing_by_name[name] = item

    existing_matches: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    created: list[dict[str, Any]] = []
    would_create: list[dict[str, Any]] = []
    would_update: list[dict[str, Any]] = []
    for entry in source_workflows:
        payload = dict(entry["payload"])
        name = str(payload["name"])
        if name in existing_by_name:
            workflow_id = existing_by_name[name].get("id")
            existing_matches.append(
                {"name": name, "id": workflow_id, "path": entry["path"]}
            )
            if dry_run:
                would_update.append({"name": name, "id": workflow_id, "path": entry["path"]})
                continue
            if workflow_id:
                updated_result = client.update_workflow(str(workflow_id), payload)
                updated.append(
                    {
                        "name": name,
                        "id": updated_result.get("id", workflow_id),
                        "path": entry["path"],
                        "active": bool(updated_result.get("active", payload.get("active"))),
                    }
                )
            continue
        if dry_run:
            would_create.append({"name": name, "path": entry["path"]})
            continue
        created_result = client.create_workflow(payload)
        created.append(
            {
                "name": name,
                "id": created_result.get("id"),
                "path": entry["path"],
                "active": bool(created_result.get("active", payload.get("active"))),
            }
        )

    generated_at = dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="seconds")
    duplicate_counts = {
        name: count
        for name, count in sorted(current_name_counts.items())
        if count > 1
    }
    archived_duplicate_counts = {
        name: count
        for name, count in sorted(all_name_counts.items())
        if count > 1 and archived_name_counts.get(name, 0) > 0
    }
    result = {
        "schema_version": 1,
        "generated_at": generated_at,
        "status": "dry_run" if dry_run else "ok",
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "api_base_url": api_base_url,
        "api_key_source": _source_without_secret(key_source),
        "api_key_redacted": True,
        "workflow_dir": str(workflow_dir),
        "source_workflow_count": len(source_workflows),
        "source_workflow_names": [
            str(entry["payload"].get("name") or "") for entry in source_workflows
        ],
        "discovered_workflow_count": len(existing),
        "current_workflow_count": len(current_existing),
        "archived_workflow_count": len(archived_existing),
        "existing_count": len(existing_matches),
        "updated_count": len(updated),
        "created_count": len(created),
        "would_create_count": len(would_create),
        "would_update_count": len(would_update),
        "duplicate_name_counts": duplicate_counts,
        "archived_duplicate_name_counts": archived_duplicate_counts,
        "updated_workflows": updated,
        "created_workflows": created,
        "existing_workflows": existing_matches,
        "would_create_workflows": would_create,
        "would_update_workflows": would_update,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"n8n-workflow-sync-{dt.datetime.now(tz=dt.timezone.utc):%Y%m%d-%H%M%S-%f}"
    json_path = output_dir / f"{stem}.json"
    result["json_path"] = str(json_path)
    text = json.dumps(result, indent=2)
    json_path.write_text(text, encoding="utf-8")
    (output_dir / "latest-workflow-sync.json").write_text(text, encoding="utf-8")
    return result
