"""Small local graph-memory store for public-market research context."""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from tradingagents.schemas.research import (
    GraphMemoryQueryPacket,
    KnowledgeGraphEdgePacket,
    KnowledgeGraphNodePacket,
)

from .memory import contains_sensitive_text, memory_backend_status_from_env, redact_payload

UTC = datetime.timezone.utc


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return digest


@dataclass(frozen=True)
class GraphMemoryStore:
    path: Path = Path("results/research_memory/graph_memory.jsonl")

    def _append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def _records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

    def upsert_node(
        self,
        *,
        node_type: str,
        label: str,
        properties: dict[str, Any] | None = None,
    ) -> KnowledgeGraphNodePacket:
        safe_properties, redacted = redact_payload(properties or {})
        if contains_sensitive_text(label):
            raise ValueError("graph memory node label contains sensitive account/secret text")
        packet = KnowledgeGraphNodePacket(
            node_id=f"{node_type}:{_stable_id(node_type, label.upper())}",
            node_type=node_type,
            label=label.upper() if node_type == "symbol" else label,
            properties=safe_properties,
            tool_route="local_graph_memory",
            redaction_status="redacted" if redacted else "no_secrets_seen",
        )
        self._append({"kind": "node", "written_at": _now_iso(), **packet.model_dump()})
        return packet

    def upsert_edge(
        self,
        *,
        source_node_id: str,
        target_node_id: str,
        relation: str,
        properties: dict[str, Any] | None = None,
    ) -> KnowledgeGraphEdgePacket:
        if any(contains_sensitive_text(value) for value in (source_node_id, target_node_id, relation)):
            raise ValueError("graph memory edge contains sensitive account/secret text")
        safe_properties, redacted = redact_payload(properties or {})
        packet = KnowledgeGraphEdgePacket(
            edge_id=f"{relation}:{_stable_id(source_node_id, target_node_id, relation)}",
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            relation=relation,
            properties=safe_properties,
            tool_route="local_graph_memory",
            redaction_status="redacted" if redacted else "no_secrets_seen",
        )
        self._append({"kind": "edge", "written_at": _now_iso(), **packet.model_dump()})
        return packet

    def query_symbol_context(self, symbol: str, *, limit: int = 20) -> GraphMemoryQueryPacket:
        needle = symbol.strip().upper()
        return self._query(f"symbol:{needle}", "symbol", needle, limit=limit)

    def query_theme_context(self, theme: str, *, limit: int = 20) -> GraphMemoryQueryPacket:
        return self._query(f"theme:{theme}", "theme", theme, limit=limit)

    def _query(self, query_id: str, field: Literal["symbol", "theme"], value: str, *, limit: int) -> GraphMemoryQueryPacket:
        result_refs = []
        for record in reversed(self._records()):
            text = json.dumps(record, sort_keys=True).lower()
            if value.lower() in text:
                result_refs.append(str(record.get("packet_id") or record.get("node_id") or record.get("edge_id")))
            if len(result_refs) >= limit:
                break
        return GraphMemoryQueryPacket(
            query_id=query_id,
            query=f"{field}:{value}",
            status="success",
            result_refs=result_refs,
            local_fallback_used=True,
            tool_route="local_graph_memory",
            redaction_status="no_secrets_seen",
        )

    def label_outcome(
        self,
        *,
        thesis_ref: str,
        outcome: str,
        properties: dict[str, Any] | None = None,
    ) -> KnowledgeGraphEdgePacket:
        return self.upsert_edge(
            source_node_id=thesis_ref,
            target_node_id=f"outcome:{outcome}",
            relation="resolved_as",
            properties=properties,
        )


def graph_memory_store_from_env(env: dict[str, str], path: str | Path | None = None) -> tuple[GraphMemoryStore, dict[str, Any]]:
    status = memory_backend_status_from_env(env)
    return GraphMemoryStore(Path(path or "results/research_memory/graph_memory.jsonl")), status.model_dump()
