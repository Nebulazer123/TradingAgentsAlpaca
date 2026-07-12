"""Build a true all-node/all-edge Zep panorama artifact for MiroFish.

This is intentionally separate from interactive Step 4 safe mode. It really
calls the graph-wide node and edge APIs, persists partial results, and records
whether the panorama was fully or partially fetched.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.zep_tools import EdgeInfo, NodeInfo, ZepToolsService  # noqa: E402


DEFAULT_GRAPH_ID = "mirofish_4a9df9ae8b184878"
DEFAULT_SIMULATION_ID = "sim_974459649906"


def _node_type(node: NodeInfo) -> str:
    return next((label for label in node.labels if label not in {"Entity", "Node"}), "Entity")


def _edge_is_historical(edge: EdgeInfo) -> bool:
    return bool(edge.expired_at or edge.invalid_at)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _render_markdown(data: dict[str, Any], *, limit_facts: int) -> str:
    errors = data.get("errors") or []
    node_types = data.get("node_types") or {}
    relation_types = data.get("relation_types") or {}
    active = data.get("active_facts") or []
    historical = data.get("historical_facts") or []
    lines = [
        "# MiroFish Zep Graph-Wide Panorama",
        "",
        f"- Graph ID: `{data.get('graph_id')}`",
        f"- Simulation ID: `{data.get('simulation_id')}`",
        f"- Status: `{data.get('status')}`",
        f"- Truly graph-wide: `{data.get('truly_graph_wide')}`",
        f"- Nodes fetched: `{data.get('node_count')}`",
        f"- Edges fetched: `{data.get('edge_count')}`",
        f"- Active facts: `{data.get('active_fact_count')}`",
        f"- Historical facts: `{data.get('historical_fact_count')}`",
        f"- Duration seconds: `{data.get('duration_seconds')}`",
        "",
        "## Node Types",
        "",
    ]
    if node_types:
        for key, value in sorted(node_types.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- `{key}`: {value}")
    else:
        lines.append("- No node type counts available.")

    lines.extend(["", "## Relation Types", ""])
    if relation_types:
        for key, value in sorted(relation_types.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- `{key}`: {value}")
    else:
        lines.append("- No relation type counts available.")

    lines.extend(["", "## Active Fact Sample", ""])
    if active:
        for idx, fact in enumerate(active[:limit_facts], 1):
            lines.append(f"{idx}. {fact}")
    else:
        lines.append("- No active facts fetched.")

    lines.extend(["", "## Historical Fact Sample", ""])
    if historical:
        for idx, fact in enumerate(historical[:limit_facts], 1):
            lines.append(f"{idx}. {fact}")
    else:
        lines.append("- No historical facts fetched.")

    lines.extend(["", "## Errors", ""])
    if errors:
        for error in errors:
            lines.append(f"- `{error.get('stage')}`: {error.get('error')}")
    else:
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def build_panorama(
    *,
    graph_id: str,
    simulation_id: str,
    output_dir: Path,
    include_temporal: bool,
    limit_facts: int,
) -> tuple[dict[str, Any], Path, Path]:
    start = time.monotonic()
    service = ZepToolsService()
    errors: list[dict[str, str]] = []
    nodes: list[NodeInfo] = []
    edges: list[EdgeInfo] = []

    try:
        nodes = service.get_all_nodes(graph_id)
    except Exception as exc:  # noqa: BLE001 - artifact must preserve raw failure class.
        errors.append({"stage": "get_all_nodes", "error": f"{type(exc).__name__}: {exc}"})

    try:
        edges = service.get_all_edges(graph_id, include_temporal=include_temporal)
    except Exception as exc:  # noqa: BLE001 - artifact must preserve raw failure class.
        errors.append({"stage": "get_all_edges", "error": f"{type(exc).__name__}: {exc}"})

    node_map = {node.uuid: node for node in nodes}
    node_types: dict[str, int] = {}
    for node in nodes:
        node_type = _node_type(node)
        node_types[node_type] = node_types.get(node_type, 0) + 1

    relation_types: dict[str, int] = {}
    active_facts: list[str] = []
    historical_facts: list[str] = []
    for edge in edges:
        relation_types[edge.name] = relation_types.get(edge.name, 0) + 1
        source = node_map.get(edge.source_node_uuid)
        target = node_map.get(edge.target_node_uuid)
        source_name = edge.source_node_name or (source.name if source else edge.source_node_uuid[:8])
        target_name = edge.target_node_name or (target.name if target else edge.target_node_uuid[:8])
        fact = f"{source_name} --[{edge.name}]--> {target_name}: {edge.fact}"
        if _edge_is_historical(edge):
            fact = f"[historical valid_at={edge.valid_at or 'unknown'} invalid_at={edge.invalid_at or edge.expired_at or 'unknown'}] {fact}"
            historical_facts.append(fact)
        elif edge.fact:
            active_facts.append(fact)

    status = "completed" if nodes and edges else "partial" if nodes or edges else "failed"
    data = {
        "schema": "mirofish.zep_graph_panorama.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "graph_id": graph_id,
        "simulation_id": simulation_id,
        "status": status,
        "truly_graph_wide": True,
        "include_temporal": include_temporal,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "active_fact_count": len(active_facts),
        "historical_fact_count": len(historical_facts),
        "node_types": node_types,
        "relation_types": relation_types,
        "active_facts": active_facts[:limit_facts],
        "historical_facts": historical_facts[:limit_facts],
        "nodes_sample": [node.to_dict() for node in nodes[:50]],
        "edges_sample": [edge.to_dict() for edge in edges[:50]],
        "errors": errors,
        "duration_seconds": round(time.monotonic() - start, 3),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "zep_graph_panorama.json"
    md_path = output_dir / "zep_graph_panorama.md"
    _write_json(json_path, data)
    md_path.write_text(_render_markdown(data, limit_facts=limit_facts), encoding="utf-8")
    return data, json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a true graph-wide Zep node/edge panorama artifact.")
    parser.add_argument("--graph-id", default=DEFAULT_GRAPH_ID)
    parser.add_argument("--simulation-id", default=DEFAULT_SIMULATION_ID)
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "backend" / "uploads" / "reports" / "_zep_panorama" / DEFAULT_GRAPH_ID),
    )
    parser.add_argument("--include-temporal", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--limit-facts", type=int, default=200)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data, json_path, md_path = build_panorama(
        graph_id=args.graph_id,
        simulation_id=args.simulation_id,
        output_dir=Path(args.output_dir),
        include_temporal=args.include_temporal,
        limit_facts=max(1, args.limit_facts),
    )
    print(json.dumps({
        "status": data["status"],
        "truly_graph_wide": data["truly_graph_wide"],
        "node_count": data["node_count"],
        "edge_count": data["edge_count"],
        "errors": data["errors"],
        "json_path": str(json_path),
        "markdown_path": str(md_path),
    }, ensure_ascii=False, indent=2))
    return 1 if data["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
