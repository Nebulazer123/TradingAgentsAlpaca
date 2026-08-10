"""Quality gates and evidence helpers for Mirror Fish Step 4 reports."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ..config import Config
from .zep_report_cache import normalize_query


MIRROR_FISH_REQUIRED_SECTIONS: List[str] = [
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


SECTION_QUERY_TOPICS: Dict[str, List[str]] = {
    "Executive summary": [
        "overall findings scenario probabilities macro dominance broker friction TradingAgents advisory",
    ],
    "Scenario probability map": [
        "branch probabilities mostly narrative medium retail flow adverse macro broker friction bot correlation",
    ],
    "Strongest simulated narratives": [
        "dominant narratives PDT intraday margin macro rates broker rollout options AI semiconductors",
    ],
    "Weak or noisy signals": [
        "weak noisy signals social chatter not confirmed by realized flow control branch",
    ],
    "False-positive patterns": [
        "false positive breakouts AI bot copycat macro gates institutional fade retail flow not confirmed",
    ],
    "Retail trader archetypes": [
        "retail trader archetypes beginners FOMO panic sellers cash margin account equity options approval",
    ],
    "AI-bot and prompt-bot failure modes": [
        "AI bot prompt bot copycat failures context drift API retry queue rate limit sandbox validation",
    ],
    "Broker/platform confusion patterns": [
        "raw:broker compliance review status page updates API reliability UI text translation from policy cross-layer feedback",
        "broker platform confusion buying power margin settlement Robinhood Alpaca Schwab Fidelity Webull IBKR",
        "broker status page API rate limits compliance review UI text translation PDT intraday margin",
        "Alpaca Trading API Robinhood Schwab Fidelity Webull day trade count margin deficit rejection support FAQ",
    ],
    "Government, regulator, and policy-maker reaction map": [
        "FINRA SEC regulator policy maker clarification Rule 4210 investor education broker UI",
    ],
    "Institutional investor, market-maker, and liquidity-provider reaction map": [
        "raw:institutional investor market-maker liquidity provider reaction to PDT rule change retail order flow 0DTE toxicity",
        "institutional investor market maker liquidity provider dealer ETF desk quant fund gamma hedge",
        "dealer gamma hedging ETF desk liquidity withdrawal spread widening retail order flow toxicity 0DTE",
    ],
    "Media outlet and influencer narrative map": [
        "media outlet influencer narrative CNBC Bloomberg YouTube Reddit X finfluencer clarification",
    ],
    "Developer community, bot-framework, and broker API behavior map": [
        "raw:developer community bot-framework broker API behavior integration error handling automation tooling open-source",
        "developer community bot framework broker API maintainers order routing slippage hard risk circuits",
        "broker API integration failures prompt bot hallucinated leverage retry queues sandbox validation",
        "open source trading infrastructure broker API branch divergence automation risk controls PDT transition",
    ],
    "Company and tech-executive narrative map": [
        "raw:Company and tech-executive narratives around PDT transition, Apple WWDC, semiconductor AI infrastructure, fintech founders, investor relations, June 2026",
        "company tech executive narrative Apple WWDC AI semiconductor Nvidia Oracle platform executive",
        "Apple WWDC Nvidia Oracle Broadcom AI infrastructure fintech founders broker executives investor relations",
        "agentic trading product framing HOOD BULL Robinhood Schwab Fidelity Webull Alpaca executive comments",
        "semiconductor AI infrastructure executive narrative macro override retail speculation June 2026",
    ],
    "Ticker/category attention map": [
        "ticker category attention SPY QQQ TSLA AAPL NVDA HOOD IBKR options 0DTE semiconductors",
    ],
    "Macro override risks": [
        "macro override risks payrolls CPI PPI Treasury auctions oil geopolitics Fed repricing rates",
    ],
    "Early-warning signals": [
        "early warning signals broker confusion index false signal risk 0DTE IV gamma retail flow",
    ],
    "TradingAgents rule implications": [
        "TradingAgents rule implications dry run quote news order validation false signal filters broker warnings",
    ],
    "Recommended validation tasks using real market data": [
        "raw:validation tasks real market data mapping simulation indices to real metrics macro override broker friction bot correlation institutional liquidity",
        "real market data validation tasks volume options IV OI spreads broker status macro calendar quotes news",
        "broker rejection rates buying power failures options IV open interest spreads market maker flow validation",
        "Treasury auctions yield curve oil geopolitics macro dominance CPI PPI payrolls validation mapping",
    ],
    "Confidence levels": [
        "confidence levels uncertainty model bias evidence strength branch probabilities validation needs",
    ],
    "Machine-readable summary if practical": [
        "machine readable summary JSON branches signals risks validation tasks confidence TradingAgents fields",
    ],
}


RAW_ERROR_PATTERNS = [
    "Rate limit exceeded",
    "status=stopped",
    "0 / 1000 interviewed",
    "采访失败",
    "模拟环境进程未运行",
    "Zep Search API failed",
    "Traceback",
]


@dataclass
class QualityGateResult:
    passed: bool
    failure_codes: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "failure_codes": self.failure_codes,
            "notes": self.notes,
        }


def build_section_queries(section_title: str) -> List[str]:
    topics = SECTION_QUERY_TOPICS.get(section_title, [section_title])
    queries: List[str] = []
    for topic in topics:
        if topic.startswith("raw:"):
            queries.append(normalize_query(topic[4:]))
        else:
            queries.append(normalize_query(f"MiroFish Step 4 {section_title} {topic} June 4 13 PDT intraday margin"))
    queries.append(normalize_query(f"{section_title} Zep graph evidence local telemetry provenance uncertainty validation"))
    seen = set()
    out: List[str] = []
    for query in queries:
        if query in seen:
            continue
        seen.add(query)
        out.append(query)
    return out


def contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def evaluate_section_quality(
    section_title: str,
    content: str,
    evidence_labels: Iterable[str],
    min_chars: int = 1200,
    require_uncertainty: bool = True,
    require_validation_tasks: bool = False,
) -> QualityGateResult:
    labels = {str(label) for label in (evidence_labels or []) if label}
    failure_codes: List[str] = []
    notes: List[str] = []
    text = content or ""

    if len(text.strip()) < min_chars:
        failure_codes.append("too_short")
    if contains_cjk(text):
        failure_codes.append("non_english_final_prose")
    if any(pattern.lower() in text.lower() for pattern in RAW_ERROR_PATTERNS):
        failure_codes.append("raw_error_leak")
    if "status=stopped" in text.lower():
        failure_codes.append("stopped_interview_claim")
    if "0 / 1000 interviewed" in text:
        failure_codes.append("failed_interview_claim")
    if re.search(r"\b0\s+nodes\b.*\b0\s+edges\b|\b0\s+edges\b.*\b0\s+nodes\b", text, re.IGNORECASE):
        if "unavailable_rate_limited" in labels or "pending" in labels:
            failure_codes.append("fake_empty_graph_claim")
    if not labels:
        failure_codes.append("missing_evidence_labels")

    uncertainty_terms = ("uncertain", "uncertainty", "confidence", "requires validation", "model bias", "not act directly")
    if require_uncertainty and not any(term in text.lower() for term in uncertainty_terms):
        failure_codes.append("missing_uncertainty")

    if require_validation_tasks:
        validation_terms = ("validation", "verify", "real market data", "fresh quote", "fresh news", "dry-run", "order validation")
        if not any(term in text.lower() for term in validation_terms):
            failure_codes.append("missing_validation_tasks")

    if "live_zep" not in labels and "fresh_cache" not in labels and "stale_cache" not in labels:
        notes.append("section has no Zep-derived evidence label")

    return QualityGateResult(passed=not failure_codes, failure_codes=failure_codes, notes=notes)


def _report_folder(report_id: str) -> Path:
    return Path(Config.UPLOAD_FOLDER) / "reports" / report_id


def write_section_evidence_files(report_id: str, section_index: int, evidence_packet: Dict[str, Any]) -> Dict[str, str]:
    folder = _report_folder(report_id)
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / f"section_{section_index:02d}_evidence.json"
    md_path = folder / f"section_{section_index:02d}_evidence.md"
    json_path.write_text(json.dumps(evidence_packet, ensure_ascii=False, indent=2), encoding="utf-8")

    labels = sorted(set(evidence_packet.get("provenance_labels") or []))
    quality = evidence_packet.get("quality_gate_result") or {}
    lines = [
        f"# Section {section_index:02d} Evidence",
        "",
        f"- Section: {evidence_packet.get('section_name', '')}",
        f"- Provenance labels: {', '.join(labels) if labels else 'none'}",
        f"- Quality passed: {quality.get('passed')}",
        f"- Retry count: {evidence_packet.get('retry_count', 0)}",
        "",
        "## Canonical Queries",
    ]
    for query in evidence_packet.get("canonical_queries") or []:
        lines.append(f"- {query}")
    lines.extend(["", "## Evidence Counts"])
    for key in ("live_zep_facts", "cached_zep_facts", "local_telemetry_facts", "db_log_snippets", "unavailable_graph_calls"):
        value = evidence_packet.get(key) or []
        lines.append(f"- {key}: {len(value)}")
    if quality.get("failure_codes"):
        lines.extend(["", "## Quality Failures"])
        for code in quality.get("failure_codes") or []:
            lines.append(f"- {code}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def write_step4_diagnostics(report_id: str, diagnostics: Dict[str, Any]) -> Dict[str, str]:
    folder = _report_folder(report_id)
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / "step4_diagnostics.json"
    md_path = folder / "step4_diagnostics.md"
    json_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Step 4 Diagnostics",
        "",
        f"- Report ID: `{diagnostics.get('new_report_id', report_id)}`",
        f"- Simulation ID: `{diagnostics.get('simulation_id', '')}`",
        f"- Graph ID: `{diagnostics.get('graph_id', '')}`",
        f"- Mode: `{diagnostics.get('mode_used', '')}`",
        f"- Old report preserved: `{diagnostics.get('old_report_preserved_path', '')}`",
        f"- Zep canonical: {diagnostics.get('zep_canonical', True)}",
        f"- Graph search worked: {diagnostics.get('graph_search_worked')}",
        f"- All-node/all-edge skipped/deferred: {diagnostics.get('all_node_edge_skipped_deferred')}",
        f"- Interview mode: {diagnostics.get('interview_mode')}",
        "",
        "## Zep Counters",
    ]
    zep = diagnostics.get("zep_diagnostics") or {}
    for key in ("calls_attempted", "calls_succeeded", "calls_rate_limited", "calls_skipped", "cache_hits", "cache_misses", "stale_cache_hits"):
        lines.append(f"- {key}: {zep.get(key, 0)}")
    lines.extend(["", "## Required Outline Coverage"])
    coverage = diagnostics.get("required_outline_coverage") or {}
    lines.append(f"- Expected sections: {coverage.get('expected')}")
    lines.append(f"- Actual sections: {coverage.get('actual')}")
    lines.append(f"- Passed: {coverage.get('passed')}")
    lines.extend(["", "## Remaining Risks"])
    for risk in diagnostics.get("remaining_quality_risks") or []:
        lines.append(f"- {risk}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}
