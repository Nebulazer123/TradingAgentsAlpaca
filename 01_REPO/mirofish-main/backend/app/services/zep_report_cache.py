"""Step 4 Zep graph-search cache, throttle, query pack, and locks.

This module intentionally supports graph.search only. Full graph-wide
node/edge hydration is deferred outside the interactive report path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("mirofish.zep_report_cache")


PROVENANCE_LIVE_ZEP = "live_zep"
PROVENANCE_FRESH_CACHE = "fresh_cache"
PROVENANCE_STALE_CACHE = "stale_cache"
PROVENANCE_LOCAL_DB = "local_db"
PROVENANCE_LOCAL_TELEMETRY = "local_telemetry"
PROVENANCE_LOCAL_LOG = "local_log"
PROVENANCE_SYNTHESIS = "synthesis"
PROVENANCE_PENDING = "pending"
PROVENANCE_RATE_LIMITED = "unavailable_rate_limited"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_query(query: Any, max_chars: int = 260) -> str:
    """Return compact deterministic English-ish graph.search query text."""
    text = re.sub(r"\s+", " ", str(query or "")).strip()
    if not text:
        text = "MiroFish Step 4 report evidence"
    text = re.sub(r"[\u4e00-\u9fff]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        text = "MiroFish Step 4 report evidence"
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


def parse_retry_after_seconds(text: Any) -> Optional[int]:
    match = re.search(r"retry-after['\"]?\s*[:=]\s*['\"]?(\d+)", str(text), re.IGNORECASE)
    if not match:
        return None
    try:
        return max(1, min(int(match.group(1)), 3600))
    except ValueError:
        return None


def parse_rate_limit_reset_epoch(text: Any) -> Optional[int]:
    match = re.search(r"x-ratelimit-reset['\"]?\s*[:=]\s*['\"]?(\d+)", str(text), re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


@dataclass
class ZepCacheConfig:
    graph_id: str
    cache_root: Path | str | None = None
    default_interval_seconds: float = 20.0
    max_live_calls: int = 50
    max_live_calls_per_section: int = 3
    max_query_limit: int = 15
    fresh_ttl_seconds: int = 24 * 60 * 60
    allow_stale_cache: bool = True

    def resolved_cache_root(self) -> Path:
        if self.cache_root is not None:
            return Path(self.cache_root)
        return Path(Config.UPLOAD_FOLDER) / "reports" / "_zep_cache" / self.graph_id


@dataclass
class ZepDiagnostics:
    calls_attempted: int = 0
    calls_succeeded: int = 0
    calls_rate_limited: int = 0
    calls_skipped: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    stale_cache_hits: int = 0
    retry_after_sleeps: List[Dict[str, Any]] = field(default_factory=list)
    outcomes_by_source: Dict[str, int] = field(default_factory=dict)
    skipped_graph_wide_calls: int = 0
    pending_queries: List[Dict[str, Any]] = field(default_factory=list)
    graph_search_worked: bool = False

    def record_source(self, source: str) -> None:
        self.outcomes_by_source[source] = self.outcomes_by_source.get(source, 0) + 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "calls_attempted": self.calls_attempted,
            "calls_succeeded": self.calls_succeeded,
            "calls_rate_limited": self.calls_rate_limited,
            "calls_skipped": self.calls_skipped,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "stale_cache_hits": self.stale_cache_hits,
            "retry_after_sleeps": self.retry_after_sleeps,
            "outcomes_by_source": self.outcomes_by_source,
            "skipped_graph_wide_calls": self.skipped_graph_wide_calls,
            "pending_queries": self.pending_queries,
            "graph_search_worked": self.graph_search_worked,
        }


@dataclass
class ZepSearchOutcome:
    query: str
    facts: List[str] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    source: str = PROVENANCE_PENDING
    tool_name: str = ""
    scope: str = "edges"
    limit: int = 10
    cache_key: str = ""
    cache_path: str = ""
    error: Optional[str] = None
    stale: bool = False
    pending: bool = False
    skipped_reason: Optional[str] = None
    created_at: str = field(default_factory=_utc_now_iso)

    @property
    def total_count(self) -> int:
        return len(self.facts)

    def to_cache_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "facts": self.facts,
            "edges": self.edges,
            "nodes": self.nodes,
            "source": self.source,
            "tool_name": self.tool_name,
            "scope": self.scope,
            "limit": self.limit,
            "cache_key": self.cache_key,
            "created_at": self.created_at,
        }

    @classmethod
    def from_cache_dict(cls, data: Dict[str, Any], source: str, stale: bool = False) -> "ZepSearchOutcome":
        return cls(
            query=str(data.get("query") or ""),
            facts=list(data.get("facts") or []),
            edges=list(data.get("edges") or []),
            nodes=list(data.get("nodes") or []),
            source=source,
            tool_name=str(data.get("tool_name") or ""),
            scope=str(data.get("scope") or "edges"),
            limit=int(data.get("limit") or 10),
            cache_key=str(data.get("cache_key") or ""),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            stale=stale,
        )


@dataclass
class LockResult:
    acquired: bool
    path: Path
    owner: str
    current_owner: Optional[Dict[str, Any]] = None

    def release(self) -> None:
        if not self.acquired or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if data.get("owner") == self.owner:
            self.path.unlink(missing_ok=True)


class ReportLock:
    """Simple process lock for report/cache writers."""

    @staticmethod
    def acquire(path: Path | str, owner: str) -> LockResult:
        lock_path = Path(path)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "owner": owner,
            "pid": os.getpid(),
            "started_at": _utc_now_iso(),
            "safe_next_action": "Wait for the current Step 4 job to finish, then rerun or remove the lock only after verifying the PID is stale.",
        }
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(str(lock_path), flags)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            return LockResult(acquired=True, path=lock_path, owner=owner, current_owner=payload)
        except FileExistsError:
            try:
                current = json.loads(lock_path.read_text(encoding="utf-8"))
            except Exception:
                current = {"owner": "unknown", "path": str(lock_path)}
            return LockResult(acquired=False, path=lock_path, owner=owner, current_owner=current)


@dataclass(frozen=True)
class QuerySpec:
    key: str
    query: str
    section: Optional[str] = None
    category: str = "section"


@dataclass
class MirrorFishQueryPack:
    required_sections: List[str]
    scenario_branches: List[str]
    extra_queries: List[str]

    @classmethod
    def default(cls) -> "MirrorFishQueryPack":
        required_sections = [
            "Executive summary",
            "Scenario probability map",
            "Strongest simulated narratives",
            "Weak or noisy signals",
            "False-positive patterns",
            "Retail trader archetypes",
            "AI-bot and prompt-bot failure modes",
            "Broker/platform confusion patterns",
            "Government, regulator, and policy-maker reaction map",
            "Institutional investor, market-maker, and liquidity-provider reaction map",
            "Media outlet and influencer narrative map",
            "Developer community, bot-framework, and broker API behavior map",
            "Company and tech-executive narrative map",
            "Ticker/category attention map",
            "Macro override risks",
            "Early-warning signals",
            "TradingAgents rule implications",
            "Recommended validation tasks using real market data",
            "Confidence levels",
            "Machine-readable summary if practical",
        ]
        scenario_branches = [
            "Mostly narrative limited retail flow macro dominates branch",
            "Medium retail flow localized churn SPY QQQ 0DTE semis broker stocks branch",
            "Large speculative flow cooperative macro AI news retail crowding branch",
            "Adverse macro override jobs CPI PPI Treasury oil Fed repricing branch",
            "Valid support crowd dip buying correct branch",
            "Broker friction buying power margin settlement API risk check branch",
            "Bot correlation AI assisted copycat false positive crowding branch",
            "Institutional liquidity market maker ETF desk quant fund adaptation branch",
            "Policy media clarification FINRA SEC broker education branch",
            "Developer infrastructure broker API bot framework agent tooling branch",
        ]
        extra_queries = [
            "MiroFish macro rates Treasury auction Fed repricing CPI PPI payrolls oil geopolitics",
            "MiroFish broker fragmentation Robinhood Alpaca Schwab Fidelity Webull IBKR tastytrade buying power margin",
            "MiroFish AI bot copycat prompt engineered trading bots API retry queues sandbox validation",
            "MiroFish 0DTE options microstructure SPY QQQ TSLA AAPL gamma IV open interest spreads liquidity",
            "MiroFish institutional liquidity response market maker dealer ETF desk quant fund order flow toxicity",
            "MiroFish media regulator clarification FINRA SEC broker FAQ finfluencer narrative correction",
            "MiroFish TradingAgents validation tasks false signal filters dry run quote news order validation",
        ]
        return cls(required_sections=required_sections, scenario_branches=scenario_branches, extra_queries=extra_queries)

    def section_queries(self, section: str) -> List[str]:
        base = normalize_query(f"MiroFish Step 4 {section} June 4 13 PDT intraday margin simulation evidence")
        return [
            base,
            normalize_query(f"{section} macro broker options AI bot institutional liquidity TradingAgents validation"),
        ]

    def specs(self) -> List[QuerySpec]:
        specs: List[QuerySpec] = []
        for idx, section in enumerate(self.required_sections, 1):
            for q_idx, query in enumerate(self.section_queries(section), 1):
                specs.append(QuerySpec(key=f"section_{idx:02d}_{q_idx}", query=query, section=section, category="section"))
        for idx, branch in enumerate(self.scenario_branches, 1):
            specs.append(QuerySpec(key=f"branch_{idx:02d}", query=normalize_query(f"MiroFish scenario branch {branch}"), category="branch"))
        for idx, query in enumerate(self.extra_queries, 1):
            specs.append(QuerySpec(key=f"extra_{idx:02d}", query=normalize_query(query), category="extra"))
        return specs

    def all_queries(self) -> List[str]:
        seen = set()
        queries: List[str] = []
        for spec in self.specs():
            if spec.query in seen:
                continue
            seen.add(spec.query)
            queries.append(spec.query)
        return queries


class ZepReportCache:
    """Sequential Step 4 graph.search budget with persistent cache."""

    def __init__(
        self,
        config: ZepCacheConfig,
        live_search: Optional[Callable[[str, int, str], Dict[str, Any]]] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        progress_callback: Optional[Callable[[str], None]] = None,
    ):
        self.config = config
        self.live_search = live_search
        self.sleep_fn = sleep_fn
        self.clock = clock
        self.progress_callback = progress_callback
        self.cache_root = config.resolved_cache_root()
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.diagnostics = ZepDiagnostics()
        self._last_live_call_at = 0.0
        self._cooldown_until = 0.0
        self._memory: Dict[str, ZepSearchOutcome] = {}
        self._section_live_counts: Dict[int, int] = {}

    def cache_key(self, tool_name: str, query: str, limit: int, scope: str = "edges") -> str:
        normalized = normalize_query(query)
        payload = {
            "graph_id": self.config.graph_id,
            "tool_name": tool_name,
            "query": normalized,
            "limit": min(int(limit or 10), self.config.max_query_limit),
            "scope": scope or "edges",
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def cache_path_for_key(self, key: str) -> Path:
        return self.cache_root / f"{key}.json"

    def _read_cache(self, key: str) -> Optional[Dict[str, Any]]:
        path = self.cache_path_for_key(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read Zep cache %s: %s", path, exc)
            return None

    def _write_cache(self, outcome: ZepSearchOutcome) -> None:
        path = self.cache_path_for_key(outcome.cache_key)
        outcome.cache_path = str(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(outcome.to_cache_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _is_fresh(self, data: Dict[str, Any]) -> bool:
        created_at = str(data.get("created_at") or "")
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
        except Exception:
            return False
        return (self.clock() - created) <= self.config.fresh_ttl_seconds

    def _from_cache(self, key: str, data: Dict[str, Any], source: str, stale: bool) -> ZepSearchOutcome:
        outcome = ZepSearchOutcome.from_cache_dict(data, source=source, stale=stale)
        outcome.cache_key = key
        outcome.cache_path = str(self.cache_path_for_key(key))
        self.diagnostics.record_source(source)
        return outcome

    def _pending(self, key: str, query: str, tool_name: str, limit: int, scope: str, reason: str, source: str = PROVENANCE_PENDING) -> ZepSearchOutcome:
        self.diagnostics.calls_skipped += 1
        payload = {"query": query, "tool_name": tool_name, "reason": reason, "created_at": _utc_now_iso()}
        self.diagnostics.pending_queries.append(payload)
        self.diagnostics.record_source(source)
        return ZepSearchOutcome(
            query=query,
            source=source,
            tool_name=tool_name,
            limit=limit,
            scope=scope,
            cache_key=key,
            cache_path=str(self.cache_path_for_key(key)),
            pending=True,
            skipped_reason=reason,
        )

    def _sleep_if_needed(self, query: str) -> None:
        now = self.clock()
        wait_until = max(self._cooldown_until, self._last_live_call_at + self.config.default_interval_seconds)
        if now >= wait_until:
            return
        sleep_for = max(0.0, wait_until - now)
        message = f"Sleeping {sleep_for:.0f}s for Zep rate limit before graph.search: {query[:80]}"
        logger.info(message)
        if self.progress_callback:
            self.progress_callback(message)
        self.diagnostics.retry_after_sleeps.append({"seconds": sleep_for, "query": query[:160], "reason": "spacing_or_cooldown"})
        self.sleep_fn(sleep_for)

    def _apply_rate_limit(self, error_text: str) -> None:
        retry_after = parse_retry_after_seconds(error_text)
        reset_epoch = parse_rate_limit_reset_epoch(error_text)
        now = self.clock()
        candidates: List[float] = []
        if retry_after:
            candidates.append(now + retry_after)
        if reset_epoch and reset_epoch > now:
            candidates.append(float(reset_epoch))
        cooldown = max(candidates) if candidates else now + 60
        self._cooldown_until = max(self._cooldown_until, cooldown)
        self.diagnostics.calls_rate_limited += 1

    def search(
        self,
        tool_name: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
        section_index: Optional[int] = None,
        live_search: Optional[Callable[[str, int, str], Dict[str, Any]]] = None,
        force_live: bool = False,
    ) -> ZepSearchOutcome:
        query = normalize_query(query)
        limit = min(int(limit or 10), self.config.max_query_limit)
        scope = scope or "edges"
        key = self.cache_key(tool_name=tool_name, query=query, limit=limit, scope=scope)

        if not force_live and key in self._memory:
            cached = self._memory[key]
            cached.source = PROVENANCE_FRESH_CACHE
            self.diagnostics.cache_hits += 1
            self.diagnostics.record_source(PROVENANCE_FRESH_CACHE)
            return cached

        cache_data = self._read_cache(key)
        if cache_data and self._is_fresh(cache_data) and not force_live:
            self.diagnostics.cache_hits += 1
            outcome = self._from_cache(key, cache_data, PROVENANCE_FRESH_CACHE, stale=False)
            self._memory[key] = outcome
            return outcome

        if cache_data:
            self.diagnostics.stale_cache_hits += 1
        else:
            self.diagnostics.cache_misses += 1

        if self.diagnostics.calls_attempted >= self.config.max_live_calls:
            if cache_data and self.config.allow_stale_cache:
                outcome = self._from_cache(key, cache_data, PROVENANCE_STALE_CACHE, stale=True)
                self._memory[key] = outcome
                return outcome
            return self._pending(key, query, tool_name, limit, scope, "live_zep_budget_exhausted")

        if section_index is not None:
            current = self._section_live_counts.get(section_index, 0)
            if current >= self.config.max_live_calls_per_section:
                if cache_data and self.config.allow_stale_cache:
                    outcome = self._from_cache(key, cache_data, PROVENANCE_STALE_CACHE, stale=True)
                    self._memory[key] = outcome
                    return outcome
                return self._pending(key, query, tool_name, limit, scope, "section_live_zep_budget_exhausted")

        now = self.clock()
        if now < self._cooldown_until:
            if cache_data and self.config.allow_stale_cache:
                outcome = self._from_cache(key, cache_data, PROVENANCE_STALE_CACHE, stale=True)
                self._memory[key] = outcome
                return outcome
            return self._pending(key, query, tool_name, limit, scope, "zep_cooldown_active", source=PROVENANCE_RATE_LIMITED)

        search_fn = live_search or self.live_search
        if not search_fn:
            if cache_data and self.config.allow_stale_cache:
                return self._from_cache(key, cache_data, PROVENANCE_STALE_CACHE, stale=True)
            return self._pending(key, query, tool_name, limit, scope, "live_search_not_configured")

        self._sleep_if_needed(query)
        self.diagnostics.calls_attempted += 1
        if section_index is not None:
            self._section_live_counts[section_index] = self._section_live_counts.get(section_index, 0) + 1

        try:
            data = search_fn(query, limit, scope) or {}
            self._last_live_call_at = self.clock()
            outcome = ZepSearchOutcome(
                query=query,
                facts=list(data.get("facts") or []),
                edges=list(data.get("edges") or []),
                nodes=list(data.get("nodes") or []),
                source=PROVENANCE_LIVE_ZEP,
                tool_name=tool_name,
                scope=scope,
                limit=limit,
                cache_key=key,
            )
            self._write_cache(outcome)
            self._memory[key] = outcome
            self.diagnostics.calls_succeeded += 1
            self.diagnostics.graph_search_worked = True
            self.diagnostics.record_source(PROVENANCE_LIVE_ZEP)
            return outcome
        except Exception as exc:
            error_text = str(exc)
            if "429" in error_text or "rate limit" in error_text.lower():
                self._apply_rate_limit(error_text)
                if cache_data and self.config.allow_stale_cache:
                    outcome = self._from_cache(key, cache_data, PROVENANCE_STALE_CACHE, stale=True)
                    self._memory[key] = outcome
                    outcome.error = error_text[:500]
                    return outcome
                return self._pending(key, query, tool_name, limit, scope, "zep_rate_limited", source=PROVENANCE_RATE_LIMITED)
            if cache_data and self.config.allow_stale_cache:
                outcome = self._from_cache(key, cache_data, PROVENANCE_STALE_CACHE, stale=True)
                outcome.error = error_text[:500]
                self._memory[key] = outcome
                return outcome
            raise

    def write_hydration_summary(self, simulation_id: str, max_queries: int, completed: int) -> Dict[str, Path]:
        summary = {
            "simulation_id": simulation_id,
            "graph_id": self.config.graph_id,
            "max_queries": max_queries,
            "completed_queries": completed,
            "created_at": _utc_now_iso(),
            "diagnostics": self.diagnostics.to_dict(),
        }
        json_path = self.cache_root / "hydration_summary.json"
        md_path = self.cache_root / "hydration_summary.md"
        json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        md_lines = [
            "# Zep Report Cache Hydration Summary",
            "",
            f"- Simulation: `{simulation_id}`",
            f"- Graph: `{self.config.graph_id}`",
            f"- Completed queries: {completed}",
            f"- Live Zep calls succeeded: {self.diagnostics.calls_succeeded}",
            f"- Rate-limited calls: {self.diagnostics.calls_rate_limited}",
            f"- Cache hits: {self.diagnostics.cache_hits}",
            f"- Pending/skipped: {self.diagnostics.calls_skipped}",
        ]
        md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        return {"json": json_path, "md": md_path}

