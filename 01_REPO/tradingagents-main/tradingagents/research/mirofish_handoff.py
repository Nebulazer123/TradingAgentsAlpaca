"""Advisory MiroFish handoff status packets.

This module records whether the external MiroFish run has produced a final
TradingAgents handoff yet. It intentionally reads only handoff/scaffold text and
does not import MiroFish code.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

from tradingagents.research.mirofish_gates import ELEVATED, evaluate_mirofish_gates
from tradingagents.schemas.research import ResearchIntelligencePacket, SourceEvidencePacket

FORBIDDEN_EFFECTS = [
    "create_trade_intent",
    "size_position",
    "submit_order",
    "promote_sleeve",
    "waive_live_gate",
]
DEFAULT_FINAL_HANDOFF_PATHS = (
    "reports/mirofish/MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md",
    "reports/mirofish/MIROFISH_TRADINGAGENTS_HANDOFF.md",
    "reports/mirofish/MIROFISH_FINAL_HANDOFF.md",
    r"C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md",
    r"C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_TRADINGAGENTS_HANDOFF.md",
)
DEFAULT_REVIEW_ARTIFACT_PATHS = (
    r"C:\Users\Corbin\Documents\Coding projects\mirofish-main\docs\mirror_fish\MIRROR_FISH_FINAL_ACCEPTANCE_DECISION.md",
    r"C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\reports\report_1e3059f732b1\review_packet_report_1e3059f732b1.zip",
)
DEFAULT_FULL_REPORT_PATHS = (
    r"C:\Users\Corbin\Documents\Coding projects\mirofish-main\backend\uploads\reports\report_1e3059f732b1\full_report.md",
    r"C:\Users\Corbin\Downloads\full_report.md",
)
DEFAULT_DEEP_RESEARCH_REVIEW_PATHS = (
    r"C:\Users\Corbin\Downloads\deep-research-report (33).md",
)
DISCOVERY_NAME_HINTS = (
    "handoff",
    "tradingagents",
    "reportagent",
    "report",
    "stage",
    "simulation",
    "summary",
    "pdt",
    "mirror_fish",
    "mirofish",
)
DISCOVERY_SUFFIXES = {".md", ".json", ".jsonl", ".txt"}
SKIP_PARTS = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache"}
FINAL_HANDOFF_POSITIVE_MARKERS = (
    "MIROFISH FINAL TRADINGAGENTS HANDOFF",
    "MIRROR FISH FINAL TRADINGAGENTS HANDOFF",
    "MACHINE-READABLE ADVISORY PACKET",
    "\"SCENARIO_BRANCHES\"",
    '"TICKER_ATTENTION_MAP"',
)
DEFAULT_REQUIRED_REPORT_ID = "report_1e3059f732b1"
REQUIRED_REPORT_ID_ENV = "TRADINGAGENTS_MIROFISH_REQUIRED_REPORT_ID"
MIROFISH_ATTENTION_SYMBOLS = ("SPY", "QQQ", "TSLA", "AAPL", "NVDA", "AMD", "SMH", "IWM")
AI_BOT_LIQUIDITY_SECTION_TITLE = "AI-Bot Correlation and Institutional Liquidity Adaptation"
AI_BOT_FALSE_SIGNAL_VALIDATION_TITLE = "AI-Bot Correlation and False-Signal Validation"
INSTITUTIONAL_LIQUIDITY_VALIDATION_TITLE = "Institutional Liquidity and Causal Attribution Validation"
DEEP_RESEARCH_REPORT_33_ID = "deep_research_report_33"
QUALITATIVE_OBSERVED_INDEX_VALUE = ELEVATED + 0.05
TELEMETRY_INDEX_ALIASES = {
    "ai_bot_copycat_index": "ai_bot_copycat_index",
    "ai bot copycat index": "ai_bot_copycat_index",
    "aibotcopycatindex": "ai_bot_copycat_index",
    "broker_confusion_index": "broker_confusion_index",
    "broker confusion index": "broker_confusion_index",
    "brokerconfusionindex": "broker_confusion_index",
    "buying_power_rejection_confusion": "buying_power_rejection_confusion",
    "buying power rejection confusion": "buying_power_rejection_confusion",
    "buyingpowerrejectionconfusion": "buying_power_rejection_confusion",
    "false_signal_risk_index": "false_signal_risk_index",
    "false signal risk index": "false_signal_risk_index",
    "falsesignalriskindex": "false_signal_risk_index",
    "macro_dominance_index": "macro_dominance_index",
    "macro dominance index": "macro_dominance_index",
    "macrodominanceindex": "macro_dominance_index",
    "options_gamma_iv_pressure": "options_gamma_iv_pressure",
    "options gamma iv pressure": "options_gamma_iv_pressure",
    "optionsgammaivpressure": "options_gamma_iv_pressure",
    "retail_flow_intensity": "retail_flow_intensity",
    "retail flow intensity": "retail_flow_intensity",
    "retailflowintensity": "retail_flow_intensity",
}


def _extract_backtick_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in re.finditer(r"`([^`]+)`", text):
        value = match.group(1).strip()
        if ":\\" in value or value.startswith("/") or value.lower().endswith(".md"):
            paths.append(value)
    return list(dict.fromkeys(paths))


def _dedupe_paths(paths: Iterable[str | Path]) -> list[Path]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for value in paths:
        path = Path(value)
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _path_kind(path: Path) -> str:
    name = path.name.lower()
    if "handoff" in name:
        return "handoff"
    if "report" in name:
        return "report"
    if "stage" in name or "simulation" in name:
        return "simulation_artifact"
    if "seed" in name or "readiness" in name or "runbook" in name:
        return "prep_artifact"
    return "artifact"


def _safe_mtime(path: Path) -> str | None:
    try:
        return datetime.datetime.fromtimestamp(
            path.stat().st_mtime,
            tz=datetime.timezone.utc,
        ).isoformat(timespec="seconds")
    except OSError:
        return None


def _safe_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _file_sha256(path: Path) -> str | None:
    try:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


def _looks_like_discovery_artifact(path: Path) -> bool:
    if any(part in SKIP_PARTS for part in path.parts):
        return False
    if path.suffix.lower() not in DISCOVERY_SUFFIXES:
        return False
    name = path.name.lower()
    return any(hint in name for hint in DISCOVERY_NAME_HINTS)


def _discover_directory_artifacts(directory: Path, *, limit: int = 120) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    artifacts: list[Path] = []
    try:
        iterator = directory.rglob("*")
        for path in iterator:
            if len(artifacts) >= limit:
                break
            if path.is_file() and _looks_like_discovery_artifact(path):
                artifacts.append(path)
    except OSError:
        return []
    return artifacts


def _build_candidate_artifact_paths(
    *,
    scaffold: Path,
    scaffold_text: str,
    final_handoff_path: Path,
    additional_handoff_paths: Iterable[str | Path] | None = None,
) -> list[Path]:
    seeded_paths: list[str | Path] = [final_handoff_path]
    default_final = Path(DEFAULT_FINAL_HANDOFF_PATHS[0])
    if Path(final_handoff_path) == default_final:
        seeded_paths.extend(DEFAULT_FINAL_HANDOFF_PATHS)
        seeded_paths.extend(DEFAULT_REVIEW_ARTIFACT_PATHS)
        seeded_paths.extend(DEFAULT_FULL_REPORT_PATHS)
    seeded_paths.extend([*_extract_backtick_paths(scaffold_text), *(additional_handoff_paths or ())])
    if scaffold.parent.exists():
        seeded_paths.append(scaffold.parent)

    expanded: list[str | Path] = []
    for path in _dedupe_paths(seeded_paths):
        expanded.append(path)
        expanded.extend(_discover_directory_artifacts(path))
    return _dedupe_paths(expanded)


def _artifact_record(path: Path) -> dict[str, object]:
    exists = path.exists()
    return {
        "path": str(path),
        "exists": exists,
        "is_file": path.is_file() if exists else False,
        "is_dir": path.is_dir() if exists else False,
        "kind": _path_kind(path),
        "size_bytes": _safe_size(path) if exists and path.is_file() else None,
        "modified_at": _safe_mtime(path) if exists else None,
    }


def _extract_bullets_between(text: str, start_header: str, end_header: str | None = None) -> list[str]:
    start = text.find(start_header)
    if start < 0:
        return []
    section = text[start + len(start_header) :]
    if end_header:
        end = section.find(end_header)
        if end >= 0:
            section = section[:end]
    items: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def _section_between(text: str, start_header: str, end_header: str | None = None) -> str:
    start = text.find(start_header)
    if start < 0:
        return ""
    section = text[start + len(start_header) :]
    if end_header:
        end = section.find(end_header)
        if end >= 0:
            section = section[:end]
    return section


def _compact_text(text: str, *, max_chars: int = 900) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "..."


def _extract_bold_report_section(text: str, title: str) -> str:
    escaped_title = re.escape(title)
    patterns = (
        rf"(?:^|\n)\s*\*\*{escaped_title}\*\*\s*(.*?)(?=\n\s*(?:\*\*[^*\n]+\*\*|#{{1,6}}\s+)|\Z)",
        rf"(?:^|\n)\s*#{{1,6}}\s+{escaped_title}\s*(.*?)(?=\n\s*#{{1,6}}\s+|\Z)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return _compact_text(match.group(1))
    return ""


def _extract_numbered_between(text: str, start_header: str, end_header: str | None = None) -> list[str]:
    section = _section_between(text, start_header, end_header)
    items: list[str] = []
    for line in section.splitlines():
        match = re.match(r"\s*\d+\.\s+(.+?)\s*$", line)
        if match:
            items.append(match.group(1).strip())
    return items


def _extract_json_advisory_packet(text: str) -> dict[str, Any]:
    section_match = re.search(
        r"##\s+machine[- ]readable (?:advisory packet|summary(?: if practical)?)\s*(.*?)(?:\n##\s+|\Z)",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    section = section_match.group(1) if section_match else _section_between(
        text,
        "## Machine-Readable Advisory Packet",
        "## How TradingAgents",
    )
    payloads = _json_code_blocks(section)
    if not payloads and not section_match:
        payloads = [
            payload
            for payload in _json_code_blocks(text)
            if any(
                key in payload
                for key in (
                    "scenario_branches",
                    "ticker_attention_map",
                    "telemetry_indices_observed",
                    "key_findings",
                    "risk_gates_and_false_positive_filters",
                )
            )
        ]
    return dict(payloads[-1]) if payloads else {}


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _symbol_list(value: Any) -> list[str]:
    symbols = _text_list(value)
    normalized = [symbol.upper() for symbol in symbols if re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{0,9}", symbol)]
    return list(dict.fromkeys(normalized))


def _probability(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip().rstrip("%")
        try:
            parsed = float(stripped)
        except ValueError:
            return None
        return parsed / 100 if value.strip().endswith("%") else parsed
    return None


def _normalize_scenario_branches(machine_packet: dict[str, Any], fallback_descriptions: list[str]) -> list[dict[str, Any]]:
    raw_branches = machine_packet.get("scenario_branches")
    if isinstance(raw_branches, list) and raw_branches:
        branches: list[dict[str, Any]] = []
        for index, item in enumerate(raw_branches, start=1):
            if isinstance(item, dict):
                description = str(item.get("description") or item.get("hypothesis") or item.get("name") or "").strip()
                probability = _probability(item.get("probability"))
                branches.append(
                    {
                        "scenario_id": str(item.get("scenario_id") or item.get("id") or f"mirofish_branch_{index}"),
                        "description": description,
                        "probability": probability,
                        "probability_source": (
                            str(item.get("probability_source") or "machine_readable_packet")
                            if probability is not None
                            else str(item.get("probability_source") or "not_provided_by_handoff")
                        ),
                    }
                )
            elif isinstance(item, str) and item.strip():
                branches.append(
                    {
                        "scenario_id": f"mirofish_branch_{index}",
                        "description": item.strip(),
                        "probability": None,
                        "probability_source": "not_provided_by_handoff",
                    }
                )
        return branches
    return [
        {
            "scenario_id": f"mirofish_branch_{index}",
            "description": description,
            "probability": None,
            "probability_source": "not_provided_by_handoff",
        }
        for index, description in enumerate(fallback_descriptions, start=1)
    ]


def _normalize_ticker_attention_map(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_symbol, raw_payload in value.items():
        symbol = str(raw_symbol).upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol):
            continue
        payload = raw_payload if isinstance(raw_payload, dict) else {"hypothesis": raw_payload}
        normalized[symbol] = {
            "symbol": symbol,
            "category": str(payload.get("category") or "unspecified"),
            "hypothesis": str(payload.get("hypothesis") or payload.get("description") or "").strip(),
            "probability": _probability(payload.get("probability")),
            "validation_tasks": _text_list(payload.get("validation_tasks")),
            "false_signal_filters": _text_list(payload.get("false_signal_filters")),
        }
    return normalized


def _normalize_category_attention_map(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_category, raw_payload in value.items():
        category = str(raw_category).strip()
        if not category:
            continue
        payload = raw_payload if isinstance(raw_payload, dict) else {"hypothesis": raw_payload}
        normalized[category] = {
            "category": category,
            "symbols": _symbol_list(payload.get("symbols")),
            "hypothesis": str(payload.get("hypothesis") or payload.get("description") or "").strip(),
            "probability": _probability(payload.get("probability")),
            "validation_tasks": _text_list(payload.get("validation_tasks")),
            "false_signal_filters": _text_list(payload.get("false_signal_filters")),
        }
    return normalized


def _normalize_retail_flow_hypotheses(value: Any) -> list[dict[str, Any]]:
    raw_items = value if isinstance(value, list) else [value] if value else []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items, start=1):
        if isinstance(item, dict):
            description = str(item.get("description") or item.get("hypothesis") or "").strip()
            normalized.append(
                {
                    "hypothesis_id": str(item.get("hypothesis_id") or item.get("id") or f"retail_flow_hypothesis_{index}"),
                    "description": description,
                    "symbols": _symbol_list(item.get("symbols")),
                    "probability": _probability(item.get("probability")),
                    "confirmations": _text_list(item.get("confirmations")),
                    "invalidators": _text_list(item.get("invalidators")),
                }
            )
        elif isinstance(item, str) and item.strip():
            normalized.append(
                {
                    "hypothesis_id": f"retail_flow_hypothesis_{index}",
                    "description": item.strip(),
                    "symbols": [],
                    "probability": None,
                    "confirmations": [],
                    "invalidators": [],
                }
            )
    return normalized


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _existing_artifact_path(value: str | Path | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    return str(path) if path.exists() else str(path)


def _augment_source_artifacts(source_artifacts: dict[str, Any]) -> dict[str, Any]:
    augmented = dict(source_artifacts)
    if "acceptance_decision" not in augmented:
        for path in DEFAULT_REVIEW_ARTIFACT_PATHS:
            candidate = Path(path)
            if candidate.name.upper() == "MIRROR_FISH_FINAL_ACCEPTANCE_DECISION.MD":
                augmented["acceptance_decision"] = str(candidate)
                break
    if "review_packet_zip" not in augmented:
        for path in DEFAULT_REVIEW_ARTIFACT_PATHS:
            candidate = Path(path)
            if candidate.suffix.lower() == ".zip":
                augmented["review_packet_zip"] = str(candidate)
                break
    if "downloaded_full_report" not in augmented:
        downloaded_candidate: Path | None = None
        fallback_candidate: Path | None = None
        for path in DEFAULT_FULL_REPORT_PATHS:
            candidate = Path(path)
            if not (candidate.exists() and candidate.name == "full_report.md"):
                continue
            fallback_candidate = fallback_candidate or candidate
            if "downloads" in {part.lower() for part in candidate.parts}:
                downloaded_candidate = candidate
                break
        selected = downloaded_candidate or fallback_candidate
        if selected:
            augmented["downloaded_full_report"] = str(selected)
    if "deep_research_report_33" not in augmented:
        for path in DEFAULT_DEEP_RESEARCH_REVIEW_PATHS:
            candidate = Path(path)
            if candidate.exists() and candidate.is_file():
                augmented["deep_research_report_33"] = str(candidate)
                break
    return augmented


def _json_code_blocks(text: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for match in re.finditer(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _markdown_table_rows(section: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in section.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return []
    headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(headers):
            continue
        row = {headers[index]: cells[index] for index in range(len(headers))}
        if any(value and not set(value) <= {"-", ":"} for value in row.values()):
            rows.append(row)
    return rows


def _report_probability(row: Mapping[str, str]) -> float | None:
    for key in ("Probability", "probability"):
        if key in row:
            return _probability(row[key])
    return None


def _deep_research_candidate_paths(source_artifacts: dict[str, Any]) -> list[Path]:
    candidates: list[str | Path] = []
    for key in (
        "deep_research_review",
        "deep_research_report",
        "deep_research_report_33",
        "downloaded_deep_research_review",
    ):
        value = source_artifacts.get(key)
        if value:
            candidates.append(str(value))
    candidates.extend(DEFAULT_DEEP_RESEARCH_REVIEW_PATHS)
    return _dedupe_paths(candidates)


def _build_deep_research_review_highlights(source_artifacts: dict[str, Any]) -> dict[str, Any]:
    candidate_paths = [
        path for path in _deep_research_candidate_paths(source_artifacts) if path.exists() and path.is_file()
    ]
    candidate_records = [
        {
            "path": str(path),
            "size_bytes": _safe_size(path),
            "sha256": _file_sha256(path),
        }
        for path in candidate_paths
    ]
    for path in candidate_paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        directional_rows = _markdown_table_rows(
            _section_between(text, "### Directional outlook", "## Actionable implications")
        )
        practical_rows = _markdown_table_rows(
            _section_between(text, "### Practical decision table", "## Timeline")
        )
        outlook = [
            {
                "market_or_sector": row.get("Market / sector") or row.get("Market") or "",
                "base_case": row.get("My base case for the next 7–10 days")
                or row.get("My base case for the next 7-10 days")
                or row.get("Base case")
                or "",
                "probability": _report_probability(row),
                "why": row.get("Why") or "",
            }
            for row in directional_rows
        ]
        decision_rules = [
            {
                "situation": row.get("Situation") or "",
                "better_response": row.get("Better response") or "",
                "worse_response": row.get("Worse response") or "",
            }
            for row in practical_rows
        ]
        return {
            "report_id": DEEP_RESEARCH_REPORT_33_ID,
            "source_path": str(path),
            "source_size_bytes": _safe_size(path),
            "source_sha256": _file_sha256(path),
            "candidate_reports": [
                {
                    **record,
                    "selected": record["path"] == str(path),
                }
                for record in candidate_records
            ],
            "core_filter": (
                "Use report 33 as macro-first, relative-trade context: prefer risk control and "
                "validated relative strength over heroic directional bets; treat the June 4 rule "
                "change as secondary until broker, flow, OI, and price confirmation appear."
            ),
            "market_regime": {
                "primary_driver": "macro_dominant_dispersion_heavy",
                "retail_rule_change_role": "secondary_until_confirmed",
                "expected_texture": "range_bound_relative_strength_and_gap_risk",
                "valid_window": "2026-06-04 through roughly 2026-06-13",
            },
            "stock_selection_biases": {
                "positive_bias": ["DIA_or_Dow_quality", "energy", "quality_cyclicals", "defensives"],
                "neutral_cautious": ["SPY_or_broad_market"],
                "negative_bias": ["QQQ_or_Nasdaq", "SMH_or_SOXX_semiconductors", "crowded_AI_beta"],
                "event_sensitive_watch": ["HOOD", "BULL", "IBKR", "SCHW"],
            },
            "selection_rules": [
                "When macro event risk is high, trim semis/AI beta before the release window.",
                "Do not upgrade PDT/rule-change trades without broker-specific and flow confirmation.",
                "If confirmation is absent, prefer Dow/energy/quality relative baskets over crowded growth.",
                "Social chatter is weak evidence until flow, OI, and price response agree.",
                "Wait for post-data confirmation before chasing green spikes in QQQ/semis/high-beta growth.",
            ],
            "risk_controls": [
                "Cut normal directional risk by roughly one-third to one-half ahead of major macro prints.",
                "Prefer defined-risk structures during high-volatility or options-sensitive windows.",
                "Use planned closing stops/reviews instead of impulsive intraday stops around data whipsaws.",
                "Pair growth exposure with energy or quality buffers when oil/rates risk is live.",
            ],
            "validation_requirements": [
                "Official macro/rate context and release-calendar state.",
                "Broker/platform rollout and buying-power behavior.",
                "Price, volume, options open interest, IV, spread, and dealer/liquidity response.",
                "Outcome logging through June 13 for SPY, QQQ, DIA, sector ETFs, and broker proxies.",
            ],
            "limitations": [
                "Qualitative scenario review, not a statistically validated price-target model.",
                "No clean scoreable numeric SPY/QQQ/DIA return target table was provided.",
                "Synthetic consensus can inflate confidence when agents share the same seed.",
                "Social intensity is not durable capital flow without microstructure confirmation.",
            ],
            "directional_outlook": outlook,
            "practical_decision_rules": decision_rules,
            "execution_authority": "none",
            "can_submit_orders": False,
        }
    return {}


def _canonical_telemetry_index_name(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    compact = re.sub(r"[^a-z0-9]+", "", lowered)
    return TELEMETRY_INDEX_ALIASES.get(lowered) or TELEMETRY_INDEX_ALIASES.get(compact) or raw


def _telemetry_index_value(value: Any) -> float | None:
    probability = _probability(value)
    if probability is not None:
        return probability
    if isinstance(value, Mapping):
        for key in (
            "value",
            "score",
            "probability",
            "normalized",
            "index",
            "level",
            "estimate",
        ):
            probability = _probability(value.get(key))
            if probability is not None:
                return probability
        joined = " ".join(str(item).lower() for item in value.values())
        if any(token in joined for token in ("high", "elevated", "peak", "strong")):
            return QUALITATIVE_OBSERVED_INDEX_VALUE
    if isinstance(value, str) and any(
        token in value.lower() for token in ("high", "elevated", "peak", "strong")
    ):
        return QUALITATIVE_OBSERVED_INDEX_VALUE
    return None


def _telemetry_indices_from_packet(machine_packet: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
    observed_names: list[str] = []
    index_values: dict[str, float] = {}
    raw_indices = machine_packet.get("telemetry_indices_observed") or machine_packet.get("telemetry_indices")
    if isinstance(raw_indices, dict):
        observed_names.extend(str(key) for key in raw_indices if str(key).strip())
        for key, value in raw_indices.items():
            canonical = _canonical_telemetry_index_name(key)
            probability = _telemetry_index_value(value)
            if probability is None:
                probability = QUALITATIVE_OBSERVED_INDEX_VALUE
            if canonical:
                index_values[canonical] = probability
    elif isinstance(raw_indices, list):
        for item in raw_indices:
            canonical = _canonical_telemetry_index_name(item)
            if canonical:
                observed_names.append(str(item))
                index_values.setdefault(canonical, QUALITATIVE_OBSERVED_INDEX_VALUE)
    state_variables = machine_packet.get("key_state_variables_and_signals")
    if isinstance(state_variables, dict):
        for key, value in state_variables.items():
            if not str(key).strip():
                continue
            observed_names.append(str(key))
            canonical = _canonical_telemetry_index_name(key)
            probability = _telemetry_index_value(value)
            if probability is not None:
                if canonical:
                    index_values[canonical] = probability
            elif canonical:
                index_values.setdefault(canonical, QUALITATIVE_OBSERVED_INDEX_VALUE)
    return index_values, list(dict.fromkeys(observed_names))


def _full_report_candidate_paths(source_artifacts: dict[str, Any]) -> list[Path]:
    candidates: list[str | Path] = []
    for key in ("stage04_report", "full_report", "downloaded_full_report"):
        value = source_artifacts.get(key)
        if value:
            candidates.append(str(value))
    candidates.extend(DEFAULT_FULL_REPORT_PATHS)
    return _dedupe_paths(candidates)


def _build_full_report_highlights(source_artifacts: dict[str, Any]) -> dict[str, Any]:
    candidate_paths = [path for path in _full_report_candidate_paths(source_artifacts) if path.exists() and path.is_file()]
    candidate_records = [
        {
            "path": str(path),
            "size_bytes": _safe_size(path),
            "sha256": _file_sha256(path),
        }
        for path in candidate_paths
    ]
    for path in candidate_paths:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        ai_bot_liquidity_excerpt = _extract_bold_report_section(text, AI_BOT_LIQUIDITY_SECTION_TITLE)
        ai_bot_validation_excerpt = _extract_bold_report_section(text, AI_BOT_FALSE_SIGNAL_VALIDATION_TITLE)
        ai_bot_validation_excerpt = ai_bot_validation_excerpt or _extract_bold_report_section(
            text,
            "AI-bot and prompt-bot failure modes",
        )
        institutional_validation_excerpt = _extract_bold_report_section(
            text,
            INSTITUTIONAL_LIQUIDITY_VALIDATION_TITLE,
        )
        institutional_validation_excerpt = institutional_validation_excerpt or _extract_bold_report_section(
            text,
            "Institutional investor, market-maker, and liquidity-provider reaction map",
        )
        if not ai_bot_liquidity_excerpt:
            ai_bot_liquidity_excerpt = _compact_text(
                " ".join(
                    excerpt
                    for excerpt in (ai_bot_validation_excerpt, institutional_validation_excerpt)
                    if excerpt
                )
            )
        machine_packet = next(
            (
                payload
                for payload in reversed(_json_code_blocks(text))
                if "scenario_branches" in payload or "key_state_variables_and_signals" in payload
            ),
            {},
        )
        scenario_branches = _dict_value(machine_packet.get("scenario_branches"))
        state_variables = _dict_value(machine_packet.get("key_state_variables_and_signals"))
        risk_gates = _dict_value(machine_packet.get("risk_gates_and_false_positive_filters"))
        confidence = _dict_value(machine_packet.get("confidence_and_uncertainty"))
        telemetry_values, telemetry_indices_observed = _telemetry_indices_from_packet(machine_packet)
        advisory_gate_verdict = evaluate_mirofish_gates(
            telemetry_values,
            context={
                "scheduled_catalyst": True,
                "social_spike": bool(telemetry_indices_observed),
                "low_liquidity": False,
                "off_peak": False,
                "institutional_confirmation": False,
            },
        )
        return {
            "source_path": str(path),
            "source_size_bytes": _safe_size(path),
            "source_sha256": _file_sha256(path),
            "candidate_reports": [
                {
                    **record,
                    "selected": record["path"] == str(path),
                }
                for record in candidate_records
            ],
            "bot_correlation_false_positive": _dict_value(
                scenario_branches.get("bot_correlation_false_positive")
            ),
            "institutional_liquidity_response": _dict_value(
                scenario_branches.get("institutional_liquidity_response")
            ),
            "ai_bot_copycat_index": _dict_value(state_variables.get("AI_bot_copycat_index")),
            "false_signal_risk_index": _dict_value(state_variables.get("false_signal_risk_index")),
            "telemetry_indices_observed": telemetry_indices_observed,
            "advisory_gate_verdict": advisory_gate_verdict,
            "risk_gates": {
                key: value
                for key, value in risk_gates.items()
                if key
                in {
                    "liquidity_trap",
                    "weekend_consolidation_risk",
                    "macro_attribution_blindness",
                    "sandbox_validation_failure",
                }
            },
            "validation_tasks": [
                str(item)
                for item in _text_list(machine_packet.get("validation_tasks_for_real_market_data"))
                if any(
                    token in str(item).lower()
                    for token in ("ai-bot", "institutional", "order-flow", "market-maker", "volume")
                )
            ][:8],
            "operational_rules": _text_list(machine_packet.get("trading_agents_operational_rules"))[:8],
            "high_confidence": _text_list(confidence.get("high_confidence"))[:6],
            "model_bias_warning": str(confidence.get("model_bias_warning") or ""),
            "ai_bot_liquidity_adaptation": {
                "section_available": bool(ai_bot_liquidity_excerpt),
                "section_title": AI_BOT_LIQUIDITY_SECTION_TITLE,
                "excerpt": ai_bot_liquidity_excerpt,
                "operator_rule": (
                    "Do not chase obvious bot-crowded breakouts; require real flow and "
                    "institutional confirmation before treating retail/social momentum as durable."
                ),
                "institutional_response_watch": [
                    "fade",
                    "absorb",
                    "temporarily_amplify",
                    "spread_or_depth_adjustment",
                    "order_flow_toxicity_management",
                ],
                "validation_gates": [
                    "independent_volume_confirmation",
                    "broker_api_execution_confirmation",
                    "options_liquidity_confirmation",
                    "institutional_participation_confirmation",
                    "market_maker_spread_or_depth_confirmation",
                ],
            },
            "ai_bot_false_signal_validation_excerpt": ai_bot_validation_excerpt,
            "institutional_liquidity_validation_excerpt": institutional_validation_excerpt,
            "core_filter": (
                "Treat AI-bot copycat spikes, obvious-signal convergence, and social momentum as "
                "false-signal risk until independent volume, broker/API execution, options "
                "liquidity, and institutional participation confirm durable flow; assume market "
                "makers may fade, absorb, or briefly amplify crowded novice flow."
            ),
            "execution_authority": "none",
            "can_submit_orders": False,
        }
    return {}


def _ordered_symbols(*symbol_groups: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    discovered: list[str] = []
    for group in symbol_groups:
        for symbol in group:
            normalized = str(symbol).upper()
            if normalized and normalized not in seen:
                seen.add(normalized)
                discovered.append(normalized)
    ordered = [symbol for symbol in MIROFISH_ATTENTION_SYMBOLS if symbol in seen]
    ordered.extend(symbol for symbol in discovered if symbol not in ordered)
    return ordered


def _attention_symbols(text: str) -> list[str]:
    mentioned = {symbol for symbol in MIROFISH_ATTENTION_SYMBOLS if re.search(rf"\b{symbol}\b", text)}
    return [symbol for symbol in MIROFISH_ATTENTION_SYMBOLS if symbol in mentioned]


def _build_final_advisory_payload(final_handoff_paths: Iterable[str | Path]) -> dict[str, Any] | None:
    for path_value in final_handoff_paths:
        path = Path(path_value)
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        machine_packet = _extract_json_advisory_packet(text)
        scenario_descriptions = _extract_numbered_between(
            text,
            "## Scenario Branches To Track",
            "## Morning Validation Queue",
        )
        scenario_branches = _normalize_scenario_branches(machine_packet, scenario_descriptions)
        validation_tasks = _extract_bullets_between(
            text,
            "## Morning Validation Queue",
            "## False-Signal Filters",
        )
        false_signal_filters = _extract_bullets_between(
            text,
            "## False-Signal Filters",
            "## Stage 05 Interview Targets",
        )
        interview_targets = _extract_bullets_between(
            text,
            "## Stage 05 Interview Targets",
            "## Machine-Readable Advisory Packet",
        )
        primary_values = machine_packet.get("primary_hypotheses", [])
        primary_hypotheses = [
            str(item) for item in primary_values if isinstance(item, str)
        ] if isinstance(primary_values, list) else []
        staleness = _dict_value(machine_packet.get("staleness"))
        source_artifacts = _augment_source_artifacts(_dict_value(machine_packet.get("source_artifacts")))
        full_report_highlights = _build_full_report_highlights(source_artifacts)
        deep_research_review = _build_deep_research_review_highlights(source_artifacts)
        ticker_attention_map = _normalize_ticker_attention_map(machine_packet.get("ticker_attention_map"))
        category_attention_map = _normalize_category_attention_map(machine_packet.get("category_attention_map"))
        retail_flow_hypotheses = _normalize_retail_flow_hypotheses(machine_packet.get("retail_flow_hypotheses"))
        symbols = _ordered_symbols(
            _attention_symbols(text),
            ticker_attention_map,
            *[item.get("symbols", []) for item in category_attention_map.values()],
            *[item.get("symbols", []) for item in retail_flow_hypotheses],
        )
        forecast_symbols = [
            symbol
            for symbol in _ordered_symbols(
                _symbol_list(machine_packet.get("forecast_symbols")),
                [symbol for symbol in symbols if symbol != "SPY"],
            )
            if symbol != "SPY"
        ]
        return {
            "type": "mirofish_final_advisory",
            "source_path": str(path),
            "status": machine_packet.get("status") or "final_advisory_no_execution_authority",
            "created_date": machine_packet.get("created_date"),
            "execution_authority": machine_packet.get("execution_authority") or "none",
            "simulation_id": machine_packet.get("simulation_id"),
            "project_id": machine_packet.get("project_id"),
            "graph_id": machine_packet.get("graph_id"),
            "report_id": machine_packet.get("report_id"),
            "rounds_completed": machine_packet.get("rounds_completed"),
            "agents_configured": machine_packet.get("agents_configured"),
            "unique_active_agents": machine_packet.get("unique_active_agents"),
            "generated_actions_total": machine_packet.get("generated_actions_total"),
            "graph_memory": machine_packet.get("graph_memory", {}),
            "allowed_uses": machine_packet.get("allowed_uses", []),
            "blocked_uses": machine_packet.get("blocked_uses", []),
            "staleness": staleness,
            "valid_window": staleness.get("valid_window"),
            "expires_after": staleness.get("expires_after"),
            "requires_refresh": _text_list(staleness.get("requires_refresh")),
            "primary_hypotheses": primary_hypotheses,
            "scenario_branches": scenario_branches,
            "validation_tasks": validation_tasks,
            "false_signal_filters": false_signal_filters,
            "interview_targets": interview_targets,
            "ticker_attention_map": ticker_attention_map,
            "ticker_attention_symbols": list(ticker_attention_map),
            "category_attention_map": category_attention_map,
            "retail_flow_hypotheses": retail_flow_hypotheses,
            "attention_symbols": symbols,
            "forecast_symbols": forecast_symbols,
            "source_artifacts": source_artifacts,
            "review_packet_zip": _existing_artifact_path(source_artifacts.get("review_packet_zip")),
            "acceptance_decision_path": _existing_artifact_path(source_artifacts.get("acceptance_decision")),
            "full_report_highlights": full_report_highlights,
            "deep_research_review": deep_research_review,
            "machine_readable_packet": machine_packet,
            "advisory_instruction": (
                "Use these items as research priors, validation tasks, and false-signal "
                "filters only. They have no execution authority."
            ),
        }
    return None


def resolve_required_report_id(required_report_id: str | None = None) -> str | None:
    """Resolve the active MiroFish report id guard.

    A caller-provided value wins. Otherwise automations can advance to a new
    MiroFish report by setting TRADINGAGENTS_MIROFISH_REQUIRED_REPORT_ID, while
    the current accepted report remains the repo fallback.
    """
    if required_report_id is not None:
        cleaned = str(required_report_id).strip()
        return cleaned or None
    env_value = os.environ.get(REQUIRED_REPORT_ID_ENV)
    if env_value is not None:
        cleaned = env_value.strip()
        return cleaned or None
    return DEFAULT_REQUIRED_REPORT_ID


def _required_report_id_matches(text: str, required_report_id: str | None) -> bool:
    if not required_report_id:
        return True
    return required_report_id.lower() in text.lower()


def _final_handoff_available(path: Path, *, required_report_id: str | None = None) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    upper = text.upper()
    if any(marker in upper for marker in ["DRAFT ONLY", "NOT FINAL", "NOT SENDABLE"]):
        return False
    if not _required_report_id_matches(text, required_report_id):
        return False
    return any(marker in upper for marker in FINAL_HANDOFF_POSITIVE_MARKERS)


def build_mirofish_handoff_status(
    *,
    scaffold_path: str | Path = "reports/mirofish/MIROFISH_PENDING_LEARNING_SCAFFOLD.md",
    final_handoff_path: str | Path = "reports/mirofish/MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md",
    additional_handoff_paths: Iterable[str | Path] | None = None,
    required_report_id: str | None = None,
) -> ResearchIntelligencePacket:
    """Build an analysis-only packet describing current external MiroFish handoff state."""
    required_report_id = resolve_required_report_id(required_report_id)
    scaffold = Path(scaffold_path)
    final_handoff = Path(final_handoff_path)
    if scaffold.exists():
        scaffold_text = scaffold.read_text(encoding="utf-8", errors="replace")
        scaffold_missing = False
    else:
        scaffold_text = ""
        scaffold_missing = True

    candidate_artifact_paths = _build_candidate_artifact_paths(
        scaffold=scaffold,
        scaffold_text=scaffold_text,
        final_handoff_path=final_handoff,
        additional_handoff_paths=additional_handoff_paths,
    )
    artifact_records = [_artifact_record(path) for path in candidate_artifact_paths]
    available_artifacts = [record for record in artifact_records if record["exists"]]
    final_handoff_candidates = [
        path for path in candidate_artifact_paths if path.is_file() and _path_kind(path) == "handoff"
    ]
    final_handoff_paths = [
        str(path)
        for path in final_handoff_candidates
        if _final_handoff_available(path, required_report_id=required_report_id)
    ]
    ignored_handoff_paths = [str(path) for path in final_handoff_candidates if str(path) not in final_handoff_paths]
    final_advisory = _build_final_advisory_payload(final_handoff_paths)
    final_available = bool(final_handoff_paths)
    confidence: Literal["high", "medium", "low", "unknown"]
    if final_available:
        status = "final_handoff_available"
        summary = (
            "One or more final MiroFish handoff artifacts are available. Morning "
            "research jobs should read the discovered handoff paths as advisory "
            "research context only until converted into normalized packets and validated."
        )
        confidence = "medium"
    elif scaffold_missing:
        status = "blocked_missing_scaffold"
        summary = (
            "The MiroFish scaffold is missing, so TradingAgents cannot recover the "
            "external-run setup from repo-local context yet."
        )
        confidence = "low"
    else:
        status = "pending_final_handoff"
        if required_report_id and ignored_handoff_paths:
            summary = (
                "No current MiroFish handoff is available yet. Final-looking local "
                f"handoff artifacts were ignored because they do not match {required_report_id}."
            )
        else:
            summary = (
                "No final MiroFish handoff is available yet. The repo has only a pending "
                "scaffold with artifact paths, prerequisites, and advisory-only boundaries."
            )
        confidence = "low"

    artifact_paths = _extract_backtick_paths(scaffold_text)
    required_artifacts = _extract_bullets_between(
        scaffold_text,
        "The final, sendable handoff should not be written until after all of these exist:",
        "Final handoff should include:",
    )
    missing_pieces = _extract_bullets_between(scaffold_text, "## Current Missing Pieces")

    clean_room = {
        "agpl_code_import_allowed": False,
        "source_code_imported": False,
        "allowed_use": "advisory_research_context_only",
        "prohibited_use": "direct_trade_trigger",
        "can_submit_orders": False,
    }
    signals = [
        {
            "type": "mirofish_handoff_status",
            "status": status,
            "final_handoff_available": final_available,
            "required_report_id": required_report_id,
            "scaffold_path": str(scaffold),
            "final_handoff_path": str(final_handoff),
            "final_handoff_paths": final_handoff_paths,
            "ignored_handoff_paths": ignored_handoff_paths,
        },
        {
            "type": "clean_room_boundary",
            "execution_authority": "none",
            **clean_room,
        },
        {
            "type": "artifact_paths",
            "count": len(artifact_paths),
            "paths": artifact_paths,
        },
        {
            "type": "handoff_discovery_manifest",
            "candidate_artifact_count": len(artifact_records),
            "available_artifact_count": len(available_artifacts),
            "final_handoff_count": len(final_handoff_paths),
            "available_artifacts": available_artifacts[:80],
            "final_handoff_paths": final_handoff_paths,
            "ignored_handoff_paths": ignored_handoff_paths,
            "required_report_id": required_report_id,
            "morning_bot_instruction": (
                "Refresh this packet before overnight/premarket analysis; if "
                "final_handoff_available is true and required_report_id matches, open final_handoff_paths and "
                "convert findings into analysis-only priors, validation tasks, "
                "and false-signal filters. Never create/size/submit/promote orders."
            ),
        },
        {
            "type": "required_final_handoff_artifacts",
            "count": len(required_artifacts),
            "items": required_artifacts,
        },
        {
            "type": "missing_pieces",
            "count": len(missing_pieces),
            "items": missing_pieces,
        },
    ]
    if final_advisory:
        signals.append(final_advisory)

    final_advisory_refs: list[str] = []
    if final_advisory:
        source_artifacts = final_advisory.get("source_artifacts")
        source_artifact_values = source_artifacts.values() if isinstance(source_artifacts, dict) else []
        final_advisory_refs = [
            str(value)
            for value in source_artifact_values
            if value
        ]
    attention_symbols = final_advisory.get("attention_symbols") if final_advisory else []
    symbols = [
        str(symbol)
        for symbol in attention_symbols
        if isinstance(symbol, str)
    ] if isinstance(attention_symbols, list) else []
    scenario_branches = final_advisory.get("scenario_branches") if final_advisory else []
    validation_tasks = final_advisory.get("validation_tasks") if final_advisory else []
    false_signal_filters = final_advisory.get("false_signal_filters") if final_advisory else []
    forecast_symbols = final_advisory.get("forecast_symbols") if final_advisory else []
    ticker_attention_map = final_advisory.get("ticker_attention_map") if final_advisory else {}
    category_attention_map = final_advisory.get("category_attention_map") if final_advisory else {}
    retail_flow_hypotheses = final_advisory.get("retail_flow_hypotheses") if final_advisory else []
    staleness = final_advisory.get("staleness") if final_advisory else {}
    source_artifacts = final_advisory.get("source_artifacts") if final_advisory else {}
    full_report_highlights = final_advisory.get("full_report_highlights") if final_advisory else {}
    deep_research_review = final_advisory.get("deep_research_review") if final_advisory else {}
    return ResearchIntelligencePacket(
        subject="MiroFish external-run handoff status",
        summary=summary,
        signals=signals,
        symbols=symbols,
        confidence=confidence,
        evidence_refs=[*artifact_paths, *final_handoff_paths, *final_advisory_refs],
        source_refs=[ref for ref in ([str(scaffold)] if scaffold.exists() else []) + final_handoff_paths],
        freshness={
            "mirofish_status": status,
            "final_handoff_available": final_available,
            "required_report_id": required_report_id,
            "scaffold_path": str(scaffold),
            "final_handoff_path": str(final_handoff),
            "final_handoff_paths": final_handoff_paths,
            "ignored_handoff_paths": ignored_handoff_paths,
            "final_advisory_available": bool(final_advisory),
            "advisory_valid_window": (
                staleness.get("valid_window") if isinstance(staleness, dict) else None
            ),
            "advisory_expires_after": (
                staleness.get("expires_after") if isinstance(staleness, dict) else None
            ),
            "advisory_requires_refresh": (
                staleness.get("requires_refresh", []) if isinstance(staleness, dict) else []
            ),
            "scenario_branch_count": len(scenario_branches) if isinstance(scenario_branches, list) else 0,
            "validation_task_count": len(validation_tasks) if isinstance(validation_tasks, list) else 0,
            "false_signal_filter_count": len(false_signal_filters) if isinstance(false_signal_filters, list) else 0,
            "attention_symbols": symbols,
            "forecast_symbols": list(forecast_symbols) if isinstance(forecast_symbols, list) else [],
            "ticker_attention_count": len(ticker_attention_map) if isinstance(ticker_attention_map, dict) else 0,
            "category_attention_count": len(category_attention_map) if isinstance(category_attention_map, dict) else 0,
            "retail_flow_hypothesis_count": (
                len(retail_flow_hypotheses) if isinstance(retail_flow_hypotheses, list) else 0
            ),
            "source_artifacts": source_artifacts if isinstance(source_artifacts, dict) else {},
            "review_packet_zip": (
                final_advisory.get("review_packet_zip") if isinstance(final_advisory, dict) else None
            ),
            "acceptance_decision_path": (
                final_advisory.get("acceptance_decision_path") if isinstance(final_advisory, dict) else None
            ),
            "full_report_highlight_available": bool(full_report_highlights),
            "full_report_source_path": (
                full_report_highlights.get("source_path") if isinstance(full_report_highlights, dict) else None
            ),
            "full_report_source_sha256": (
                full_report_highlights.get("source_sha256") if isinstance(full_report_highlights, dict) else None
            ),
            "full_report_candidate_count": (
                len(full_report_highlights.get("candidate_reports", []))
                if isinstance(full_report_highlights, dict)
                else 0
            ),
            "full_report_candidate_reports": (
                full_report_highlights.get("candidate_reports", [])
                if isinstance(full_report_highlights, dict)
                else []
            ),
            "full_report_core_filter": (
                full_report_highlights.get("core_filter") if isinstance(full_report_highlights, dict) else None
            ),
            "full_report_ai_bot_liquidity_available": (
                bool(
                    full_report_highlights.get("ai_bot_liquidity_adaptation", {}).get("section_available")
                )
                if isinstance(full_report_highlights, dict)
                else False
            ),
            "full_report_ai_bot_liquidity_summary": (
                full_report_highlights.get("ai_bot_liquidity_adaptation", {}).get("excerpt")
                if isinstance(full_report_highlights, dict)
                else None
            ),
            "mirofish_advisory_gate_action": (
                full_report_highlights.get("advisory_gate_verdict", {}).get("action")
                if isinstance(full_report_highlights, dict)
                else None
            ),
            "mirofish_advisory_triggered_gates": (
                full_report_highlights.get("advisory_gate_verdict", {}).get("triggered_gates", [])
                if isinstance(full_report_highlights, dict)
                else []
            ),
            "deep_research_review_available": bool(deep_research_review),
            "deep_research_review_report_id": (
                deep_research_review.get("report_id") if isinstance(deep_research_review, dict) else None
            ),
            "deep_research_review_source_path": (
                deep_research_review.get("source_path") if isinstance(deep_research_review, dict) else None
            ),
            "deep_research_review_source_sha256": (
                deep_research_review.get("source_sha256") if isinstance(deep_research_review, dict) else None
            ),
            "deep_research_review_core_filter": (
                deep_research_review.get("core_filter") if isinstance(deep_research_review, dict) else None
            ),
            "deep_research_review_market_regime": (
                deep_research_review.get("market_regime") if isinstance(deep_research_review, dict) else {}
            ),
            "deep_research_review_stock_selection_biases": (
                deep_research_review.get("stock_selection_biases") if isinstance(deep_research_review, dict) else {}
            ),
            "deep_research_review_selection_rules": (
                deep_research_review.get("selection_rules", [])[:8]
                if isinstance(deep_research_review, dict)
                else []
            ),
            "deep_research_review_risk_controls": (
                deep_research_review.get("risk_controls", [])[:8]
                if isinstance(deep_research_review, dict)
                else []
            ),
            "deep_research_review_validation_requirements": (
                deep_research_review.get("validation_requirements", [])[:8]
                if isinstance(deep_research_review, dict)
                else []
            ),
            "execution_authority": "none",
            "can_submit_orders": False,
            "allowed_use": "advisory_only",
            "prohibited_use": "direct_trade_trigger",
            "forbidden_effects": FORBIDDEN_EFFECTS,
            "clean_room": clean_room,
            "artifact_path_count": len(artifact_paths),
            "candidate_artifact_count": len(artifact_records),
            "available_artifact_count": len(available_artifacts),
            "available_artifacts": available_artifacts[:80],
            "ignored_handoff_count": len(ignored_handoff_paths),
            "required_artifact_count": len(required_artifacts),
            "missing_piece_count": len(missing_pieces),
            "morning_bot_instruction": (
                "Use this packet as the first MiroFish lookup. When final handoff "
                "paths appear and match the required report id, read them as advisory context for analysis jobs only."
            ),
        },
        tool_route="local",
        redaction_status="no_secrets_seen",
    )


def build_compact_mirofish_handoff_status(
    packet: ResearchIntelligencePacket,
    *,
    packet_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a compact status sidecar for automation context and n8n dashboards."""

    freshness = packet.freshness
    clean_room = freshness.get("clean_room")
    if not isinstance(clean_room, dict):
        clean_room = {}
    status_signal = next(
        (
            signal
            for signal in packet.signals
            if signal.get("type") == "mirofish_handoff_status"
        ),
        {},
    )
    raw_packet_path = str(packet_path) if packet_path is not None else None
    freshness_keys = (
        "mirofish_status",
        "final_handoff_available",
        "required_report_id",
        "execution_authority",
        "can_submit_orders",
        "allowed_use",
        "prohibited_use",
        "artifact_path_count",
        "candidate_artifact_count",
        "available_artifact_count",
        "final_handoff_paths",
        "ignored_handoff_count",
        "advisory_valid_window",
        "advisory_expires_after",
        "advisory_requires_refresh",
        "final_advisory_available",
        "scenario_branch_count",
        "validation_task_count",
        "false_signal_filter_count",
        "attention_symbols",
        "forecast_symbols",
        "source_artifacts",
        "review_packet_zip",
        "acceptance_decision_path",
        "full_report_highlight_available",
        "full_report_source_path",
        "full_report_core_filter",
        "full_report_ai_bot_liquidity_available",
        "full_report_ai_bot_liquidity_summary",
        "mirofish_advisory_gate_action",
        "mirofish_advisory_triggered_gates",
        "deep_research_review_available",
        "deep_research_review_report_id",
        "deep_research_review_source_path",
        "deep_research_review_core_filter",
        "deep_research_review_stock_selection_biases",
        "required_artifact_count",
        "missing_piece_count",
        "morning_bot_instruction",
    )
    compact_freshness = {key: freshness.get(key) for key in freshness_keys}
    compact_freshness["clean_room"] = {
        "agpl_code_import_allowed": clean_room.get("agpl_code_import_allowed"),
        "source_code_imported": clean_room.get("source_code_imported"),
    }

    return {
        "schema": "compact_mirofish_handoff_status_v1",
        "packet_id": packet.packet_id,
        "generated_at": packet.generated_at,
        "analysis_only": packet.analysis_only,
        "subject": packet.subject,
        "summary": packet.summary,
        "status": status_signal.get("status") or freshness.get("mirofish_status"),
        "final_handoff_available": status_signal.get("final_handoff_available"),
        "raw_packet_path": raw_packet_path,
        "packet_path": raw_packet_path,
        "freshness": compact_freshness,
        "raw_field_groups": {
            "signals": "signals",
            "full_freshness": "freshness",
            "evidence_refs": "evidence_refs",
        },
    }


def build_mirofish_source_context_packet(
    *,
    scaffold_path: str | Path = "reports/mirofish/MIROFISH_PENDING_LEARNING_SCAFFOLD.md",
    final_handoff_path: str | Path = "reports/mirofish/MIROFISH_FINAL_TRADINGAGENTS_HANDOFF.md",
    additional_handoff_paths: Iterable[str | Path] | None = None,
    required_report_id: str | None = None,
) -> SourceEvidencePacket:
    """Build a SourceEvidencePacket so overnight/premarket context can consume MiroFish status."""
    status_packet = build_mirofish_handoff_status(
        scaffold_path=scaffold_path,
        final_handoff_path=final_handoff_path,
        additional_handoff_paths=additional_handoff_paths,
        required_report_id=required_report_id,
    )
    status_signal = next(
        signal for signal in status_packet.signals if signal.get("type") == "mirofish_handoff_status"
    )
    discovery_signal = next(
        signal for signal in status_packet.signals if signal.get("type") == "handoff_discovery_manifest"
    )
    final_advisory: dict[str, Any] = {}
    for signal in status_packet.signals:
        if signal.get("type") == "mirofish_final_advisory":
            final_advisory = dict(signal)
            break
    return SourceEvidencePacket(
        source_name="mirofish_handoff",
        evidence_type="external_market_simulation_handoff",
        subject="mirofish_external_run_advisory_context",
        payload={
            "status": status_signal.get("status"),
            "summary": status_packet.summary,
            "signals": status_packet.signals,
            "final_handoff_available": status_signal.get("final_handoff_available"),
            "final_handoff_paths": status_signal.get("final_handoff_paths", []),
            "ignored_handoff_paths": status_signal.get("ignored_handoff_paths", []),
            "required_report_id": status_signal.get("required_report_id"),
            "available_artifacts": discovery_signal.get("available_artifacts", []),
            "morning_bot_instruction": discovery_signal.get("morning_bot_instruction"),
            "final_advisory": final_advisory,
            "staleness": final_advisory.get("staleness", {}),
            "advisory_valid_window": final_advisory.get("valid_window"),
            "advisory_expires_after": final_advisory.get("expires_after"),
            "advisory_requires_refresh": final_advisory.get("requires_refresh", []),
            "scenario_branches": final_advisory.get("scenario_branches", []),
            "validation_tasks": final_advisory.get("validation_tasks", []),
            "false_signal_filters": final_advisory.get("false_signal_filters", []),
            "primary_hypotheses": final_advisory.get("primary_hypotheses", []),
            "ticker_attention_map": final_advisory.get("ticker_attention_map", {}),
            "ticker_attention_symbols": final_advisory.get("ticker_attention_symbols", []),
            "category_attention_map": final_advisory.get("category_attention_map", {}),
            "retail_flow_hypotheses": final_advisory.get("retail_flow_hypotheses", []),
            "source_artifacts": final_advisory.get("source_artifacts", {}),
            "review_packet_zip": final_advisory.get("review_packet_zip"),
            "acceptance_decision_path": final_advisory.get("acceptance_decision_path"),
            "full_report_highlights": final_advisory.get("full_report_highlights", {}),
            "deep_research_review": final_advisory.get("deep_research_review", {}),
            "attention_symbols": final_advisory.get("attention_symbols", []),
            "forecast_symbols": final_advisory.get("forecast_symbols", []),
            "execution_authority": "none",
            "can_submit_orders": False,
            "allowed_use": "advisory_only",
            "prohibited_use": "direct_trade_trigger",
            "forbidden_effects": FORBIDDEN_EFFECTS,
        },
        source_refs=status_packet.source_refs,
        freshness=status_packet.freshness,
        quality="high" if final_advisory else "medium" if status_signal.get("final_handoff_available") else "low",
        tool_route="local_mirofish_handoff",
        redaction_status=status_packet.redaction_status,
    )
