"""Probe whether local n8n can start built-in Evaluation runs through the API.

The native Evaluation Trigger workflow is primarily an editor/evaluations UI
surface. This module records a redacted proof packet for that boundary so the
repo can distinguish "dataset synced" from "evaluation run actually triggerable"
without granting n8n shell or broker authority.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from tradingagents.orchestration.n8n_api_sync import (
    DEFAULT_N8N_API_BASE_URL,
    N8NApiSyncError,
    resolve_n8n_api_key,
)

DEFAULT_BUILTIN_EVALUATION_WORKFLOW_NAME = "TA · Built-in Automation Evaluation"
DEFAULT_PROBE_ENDPOINTS = (
    ("POST", "/workflows/{workflow_id}/test-runs", None),
    ("POST", "/workflows/{workflow_id}/test-runs/new", None),
    ("POST", "/workflows/{workflow_id}/run", None),
    ("POST", "/workflows/{workflow_id}/execute", None),
)
N8N_EDITOR_EVALUATION_SURFACE = "n8n_editor_evaluations_ui"
N8N_PUBLIC_API_SURFACE = "n8n_public_api"


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _source_without_secret(source: str | None) -> str:
    return source or "unknown"


def _body_preview(body: str, limit: int = 500) -> str:
    return " ".join(body.split())[:limit]


class N8NEvaluationRunProbeClient:
    """Tiny n8n public API client for non-mutating evaluation-run probing."""

    def __init__(
        self,
        *,
        api_base_url: str = DEFAULT_N8N_API_BASE_URL,
        api_key: str,
        timeout_seconds: float = 20.0,
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

    def probe(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
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
                body = response.read().decode("utf-8", errors="replace")
                status = response.status
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            status = exc.code
        except urllib.error.URLError as exc:
            body = str(exc)
            status = None
        return {
            "method": method,
            "path": path,
            "http_status": status,
            "response_preview": _body_preview(body),
            "supported": isinstance(status, int) and 200 <= status < 300,
        }


def _find_workflow(workflows: list[dict[str, Any]], workflow_name: str) -> dict[str, Any] | None:
    for workflow in workflows:
        if str(workflow.get("name") or "") == workflow_name:
            return workflow
    return None


def _write_probe_result(result: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"n8n-evaluation-run-probe-{dt.datetime.now(tz=dt.timezone.utc):%Y%m%d-%H%M%S-%f}"
    json_path = output_dir / f"{stem}.json"
    result["json_path"] = str(json_path)
    text = json.dumps(result, indent=2)
    json_path.write_text(text, encoding="utf-8")
    (output_dir / "latest-run-probe.json").write_text(text, encoding="utf-8")
    return result


def _acceptance_packet(
    *,
    accepted: bool,
    sanctioned_run_surface: str,
    api_trigger_supported: bool,
    editor_required_accepted: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "accepted": accepted,
        "core_accepted": accepted,
        "sanctioned_run_surface": sanctioned_run_surface,
        "api_trigger_supported": api_trigger_supported,
        "editor_required_accepted": editor_required_accepted,
        "reason": reason,
    }


def probe_n8n_builtin_evaluation_run(
    *,
    api_base_url: str = DEFAULT_N8N_API_BASE_URL,
    api_key: str | None = None,
    api_key_source: str | None = None,
    api_key_env: str = "N8N_API_KEY",
    api_key_sqlite_db: str | Path | None = None,
    workflow_name: str = DEFAULT_BUILTIN_EVALUATION_WORKFLOW_NAME,
    output_dir: Path = Path("results/n8n_evaluations"),
    client: N8NEvaluationRunProbeClient | None = None,
) -> dict[str, Any]:
    """Write a proof packet for native n8n Evaluation Trigger run availability."""

    key_source = api_key_source
    if client is None:
        key, key_source = resolve_n8n_api_key(
            api_key=api_key,
            env_name=api_key_env,
            sqlite_db_path=api_key_sqlite_db,
        )
        client = N8NEvaluationRunProbeClient(api_base_url=api_base_url, api_key=key)

    workflows = client.list_workflows()
    workflow = _find_workflow(workflows, workflow_name)
    workflow_id = str(workflow.get("id")) if workflow and workflow.get("id") else None
    generated_at = dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="seconds")
    base = {
        "schema_version": 1,
        "generated_at": generated_at,
        "analysis_only": True,
        "can_submit_orders": False,
        "execution_authority": "none",
        "api_base_url": api_base_url,
        "api_key_source": _source_without_secret(key_source),
        "api_key_redacted": True,
        "workflow_name": workflow_name,
        "workflow_id": workflow_id,
        "workflow_found": workflow is not None,
        "workflow_active": bool(workflow.get("active")) if workflow else None,
        "probes": [],
        "probe_count": 0,
        "supported_endpoint_count": 0,
    }
    if workflow_id is None:
        reason = "Built-in n8n Evaluation Trigger workflow is missing."
        result = {
            **base,
            "status": "missing_workflow",
            "editor_run_required": True,
            "accepted_as_current_gate": False,
            "sanctioned_run_surface": "unavailable",
            "acceptance_reason": reason,
            "acceptance": _acceptance_packet(
                accepted=False,
                sanctioned_run_surface="unavailable",
                api_trigger_supported=False,
                editor_required_accepted=False,
                reason=reason,
            ),
            "remediation": "Sync n8n workflows, then run this probe again.",
        }
        return _write_probe_result(result, output_dir)

    quoted_id = urllib.parse.quote(workflow_id, safe="")
    probes = [
        client.probe(
            method,
            path_template.format(workflow_id=quoted_id),
            payload=payload,
        )
        for method, path_template, payload in DEFAULT_PROBE_ENDPOINTS
    ]
    supported = [probe for probe in probes if probe.get("supported")]
    api_trigger_available = bool(supported)
    editor_required_accepted = not api_trigger_available
    sanctioned_run_surface = (
        N8N_PUBLIC_API_SURFACE if api_trigger_available else N8N_EDITOR_EVALUATION_SURFACE
    )
    acceptance_reason = (
        "Local n8n exposes a public API endpoint for the built-in evaluation run."
        if api_trigger_available
        else (
            "Local n8n public API does not expose a native Evaluation Trigger run "
            "endpoint; the authenticated editor/evaluations UI is the sanctioned run gate."
        )
    )
    result = {
        **base,
        "status": "api_trigger_available" if api_trigger_available else "editor_required",
        "editor_run_required": not api_trigger_available,
        "accepted_as_current_gate": True,
        "sanctioned_run_surface": sanctioned_run_surface,
        "acceptance_reason": acceptance_reason,
        "acceptance": _acceptance_packet(
            accepted=True,
            sanctioned_run_surface=sanctioned_run_surface,
            api_trigger_supported=api_trigger_available,
            editor_required_accepted=editor_required_accepted,
            reason=acceptance_reason,
        ),
        "probes": probes,
        "probe_count": len(probes),
        "supported_endpoint_count": len(supported),
        "remediation": (
            "Use the supported API endpoint recorded in probes."
            if api_trigger_available
            else (
                "Open http://localhost:5678, open the built-in evaluation workflow, "
                "and run it from the n8n editor/evaluations UI."
            )
        ),
    }
    return _write_probe_result(result, output_dir)
