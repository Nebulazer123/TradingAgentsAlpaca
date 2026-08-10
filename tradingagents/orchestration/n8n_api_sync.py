"""Sync TradingAgents n8n evaluation rows through n8n's public API.

The n8n Data Table node is editor/runtime dependent and can fail under
``n8n execute`` when its helper proxy is unavailable. This module uses the
public Data Table API instead, so repo verification can prove the dashboard
state without granting n8n shell or broker authority.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from tradingagents.orchestration.n8n_evaluations import (
    DATASET_COLUMNS,
    write_n8n_evaluation_dataset,
)
from tradingagents.orchestration.n8n_policy import N8NJob

DEFAULT_N8N_API_BASE_URL = "http://localhost:5678/api/v1"
DEFAULT_DATA_TABLE_NAME = "TradingAgents_Automation_Evaluations"
DEFAULT_API_KEY_ENV = "N8N_API_KEY"
DEFAULT_API_KEY_LABELS = ("Docker", "Codex")
DELETE_ALL_FILTER = {
    "type": "and",
    "filters": [
        {
            "columnName": "case_id",
            "condition": "neq",
            "value": "__tradingagents_no_case_should_match_this__",
        }
    ],
}


class N8NApiSyncError(RuntimeError):
    """Raised when the local n8n API sync cannot complete."""


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _source_without_secret(source: str | None) -> str:
    return source or "unknown"


def _normalize_api_base_url(api_base_url: str) -> str:
    return api_base_url.rstrip("/")


def _query_param_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return value


def load_n8n_api_key_from_env(env_name: str = DEFAULT_API_KEY_ENV) -> tuple[str | None, str | None]:
    """Return an n8n API key from an env var without logging it."""
    value = os.environ.get(env_name)
    if not value:
        return None, None
    return value, f"env:{env_name}"


def _sqlite_row_value(row: sqlite3.Row, *names: str) -> Any | None:
    keys = set(row.keys())
    for name in names:
        if name in keys:
            return row[name]
    return None


def load_n8n_api_key_from_sqlite(
    db_path: str | Path,
    *,
    labels: tuple[str, ...] = DEFAULT_API_KEY_LABELS,
) -> tuple[str | None, str | None]:
    """Load a local n8n API key from a copied SQLite DB, returning a redacted source."""
    path = Path(db_path)
    if not path.exists():
        raise N8NApiSyncError(f"n8n SQLite database not found: {path}")
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM user_api_keys").fetchall()
        except sqlite3.Error as exc:
            raise N8NApiSyncError("could not read user_api_keys from n8n SQLite database") from exc
    for wanted in labels:
        for row in rows:
            label_value = _sqlite_row_value(row, "label")
            label = str(label_value) if label_value is not None else ""
            if label == wanted:
                key = _sqlite_row_value(row, "apiKey", "api_key")
                if key:
                    return str(key), f"sqlite:{path.name}:label:{label}"
    for row in rows:
        key = _sqlite_row_value(row, "apiKey", "api_key")
        label_value = _sqlite_row_value(row, "label")
        label = str(label_value) if label_value is not None else "unlabeled"
        if key:
            return str(key), f"sqlite:{path.name}:label:{label}"
    return None, None


def resolve_n8n_api_key(
    *,
    api_key: str | None = None,
    env_name: str = DEFAULT_API_KEY_ENV,
    sqlite_db_path: str | Path | None = None,
    sqlite_labels: tuple[str, ...] = DEFAULT_API_KEY_LABELS,
) -> tuple[str, str]:
    """Resolve the n8n API key from explicit value, env, or local SQLite."""
    if api_key:
        return api_key, "argument:redacted"
    key, source = load_n8n_api_key_from_env(env_name)
    if key:
        return key, str(source)
    if sqlite_db_path is not None:
        key, source = load_n8n_api_key_from_sqlite(sqlite_db_path, labels=sqlite_labels)
        if key:
            return key, str(source)
    raise N8NApiSyncError(
        f"missing n8n API key; set {env_name} or pass a copied n8n SQLite DB path"
    )


class N8NDataTableApiClient:
    """Small n8n public API client for Data Table sync."""

    def __init__(self, *, api_base_url: str = DEFAULT_N8N_API_BASE_URL, api_key: str, timeout_seconds: float = 30.0):
        self.api_base_url = _normalize_api_base_url(api_base_url)
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Any | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        query_text = ""
        if query:
            query_text = "?" + urllib.parse.urlencode(
                {
                    key: _query_param_value(value)
                    for key, value in query.items()
                    if value is not None
                }
            )
        url = f"{self.api_base_url}{path}{query_text}"
        headers = {
            "X-N8N-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        data = _json_bytes(payload) if payload is not None else None
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
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

    def list_data_tables(self, *, name: str | None = None) -> list[dict[str, Any]]:
        query = {"filter": {"name": name}} if name else None
        payload = self.request("GET", "/data-tables", query=query)
        return list(payload.get("data") or []) if isinstance(payload, dict) else []

    def create_data_table(self, *, name: str, columns: list[dict[str, str]]) -> dict[str, Any]:
        return dict(self.request("POST", "/data-tables", payload={"name": name, "columns": columns}))

    def list_columns(self, table_id: str) -> list[dict[str, Any]]:
        payload = self.request("GET", f"/data-tables/{urllib.parse.quote(table_id)}/columns")
        return list(payload or [])

    def create_column(self, table_id: str, *, name: str, column_type: str, index: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name, "type": column_type}
        if index is not None:
            payload["index"] = index
        return dict(self.request("POST", f"/data-tables/{urllib.parse.quote(table_id)}/columns", payload=payload))

    def list_rows(self, table_id: str, *, limit: int = 250) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            payload = self.request(
                "GET",
                f"/data-tables/{urllib.parse.quote(table_id)}/rows",
                query={"limit": limit, "cursor": cursor},
            )
            if not isinstance(payload, dict):
                break
            rows.extend(item for item in payload.get("data") or [] if isinstance(item, dict))
            cursor = payload.get("nextCursor")
            if not cursor:
                break
        return rows

    def delete_all_rows(self, table_id: str) -> Any:
        return self.request(
            "DELETE",
            f"/data-tables/{urllib.parse.quote(table_id)}/rows/delete",
            query={"filter": DELETE_ALL_FILTER, "returnData": False, "dryRun": False},
        )

    def insert_rows(self, table_id: str, rows: list[dict[str, Any]], *, return_type: str = "count") -> Any:
        return self.request(
            "POST",
            f"/data-tables/{urllib.parse.quote(table_id)}/rows",
            payload={"data": rows, "returnType": return_type},
        )


def _expected_columns(packet: dict[str, Any]) -> list[dict[str, str]]:
    columns = packet.get("columns") or [{"name": name, "type": column_type} for name, column_type in DATASET_COLUMNS]
    return [{"name": str(item["name"]), "type": str(item["type"])} for item in columns]


def _chunked(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _insert_result_count(result: Any, fallback_count: int) -> int:
    if isinstance(result, dict):
        count = result.get("count")
        if isinstance(count, (int, float)) and not isinstance(count, bool):
            return int(count)
    if isinstance(result, (int, float)) and not isinstance(result, bool):
        return int(result)
    return fallback_count


def sync_n8n_evaluation_data_table(
    *,
    api_base_url: str = DEFAULT_N8N_API_BASE_URL,
    api_key: str | None = None,
    api_key_source: str | None = None,
    api_key_env: str = DEFAULT_API_KEY_ENV,
    api_key_sqlite_db: str | Path | None = None,
    table_name: str = DEFAULT_DATA_TABLE_NAME,
    replace: bool = True,
    dry_run: bool = False,
    insert_chunk_size: int = 50,
    output_dir: Path = Path("results/n8n_evaluations"),
    jobs: dict[str, N8NJob] | None = None,
    packet: dict[str, Any] | None = None,
    client: N8NDataTableApiClient | None = None,
) -> dict[str, Any]:
    """Create/update the n8n evaluation Data Table and return a redacted proof packet."""
    dataset = (
        packet
        if packet is not None
        else write_n8n_evaluation_dataset(output_dir=output_dir, jobs=jobs)
    )
    key = api_key
    key_source = api_key_source
    if client is None:
        key, key_source = resolve_n8n_api_key(
            api_key=api_key,
            env_name=api_key_env,
            sqlite_db_path=api_key_sqlite_db,
        )
        client = N8NDataTableApiClient(api_base_url=api_base_url, api_key=key)
    rows = [dict(row) for row in dataset["rows"]]
    columns = _expected_columns(dataset)
    tables = client.list_data_tables(name=table_name)
    created_table = False
    if tables:
        table = tables[0]
    elif dry_run:
        table = {"id": None, "name": table_name}
    else:
        table = client.create_data_table(name=table_name, columns=columns)
        created_table = True
    table_id = table.get("id")
    if not table_id and not dry_run:
        raise N8NApiSyncError("n8n Data Table create/list response did not include an id")

    missing_columns: list[str] = []
    if table_id and not created_table:
        existing_columns = client.list_columns(str(table_id))
        existing_names = {str(column.get("name")) for column in existing_columns}
        for index, column in enumerate(columns):
            if column["name"] not in existing_names:
                missing_columns.append(column["name"])
                if not dry_run:
                    client.create_column(
                        str(table_id),
                        name=column["name"],
                        column_type=column["type"],
                        index=index,
                    )

    existing_row_count = 0
    final_row_count = 0
    deleted_existing_rows = False
    inserted_count = 0
    if table_id:
        existing_row_count = len(client.list_rows(str(table_id)))
        if replace and existing_row_count and not dry_run:
            client.delete_all_rows(str(table_id))
            deleted_existing_rows = True
        if not dry_run:
            for chunk in _chunked(rows, max(1, insert_chunk_size)):
                result = client.insert_rows(str(table_id), chunk)
                inserted_count += _insert_result_count(result, len(chunk))
            final_row_count = len(client.list_rows(str(table_id)))
        else:
            final_row_count = existing_row_count

    generated_at = dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="seconds")
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
        "data_table_name": table_name,
        "data_table_id": table_id,
        "created_table": created_table,
        "replace": replace,
        "deleted_existing_rows": deleted_existing_rows,
        "existing_row_count": existing_row_count,
        "inserted_count": inserted_count,
        "final_row_count": final_row_count,
        "expected_row_count": dataset["row_count"],
        "row_count_matches": (final_row_count == dataset["row_count"]) if not dry_run else None,
        "column_count": len(columns),
        "missing_columns_added": missing_columns,
        "dataset_generated_at": dataset["generated_at"],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"n8n-api-sync-{dt.datetime.now(tz=dt.timezone.utc):%Y%m%d-%H%M%S-%f}"
    json_path = output_dir / f"{stem}.json"
    result["json_path"] = str(json_path)
    text = json.dumps(result, indent=2)
    json_path.write_text(text, encoding="utf-8")
    (output_dir / "latest-sync.json").write_text(text, encoding="utf-8")
    return result
