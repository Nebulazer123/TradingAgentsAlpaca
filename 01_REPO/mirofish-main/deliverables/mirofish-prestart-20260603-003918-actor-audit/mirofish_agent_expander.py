#!/usr/bin/env python3
"""Expand a prepared MiroFish simulation into a larger runnable population.

Stage 02 creates one OASIS agent per extracted Zep entity. For broad market
society runs, that can be too small even when the prompt requests 1,000 agents.
This helper preserves the LLM-generated archetypes, adds explicit institutional
anchors, then creates deterministic cohort variants in the profile and config
files OASIS actually consumes.

Default mode is dry-run. Execution requires an exact confirmation phrase.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import shutil
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


ROOT = Path(__file__).resolve().parents[2]
CONFIRM = "expand-mirofish-agent-population"

CATEGORY_QUOTAS = {
    "retail_new_traders": 420,
    "broker_platform_clearing": 120,
    "developer_automation": 130,
    "media_narrative": 80,
    "policy_regulatory": 70,
    "institutional_liquidity": 140,
    "tech_company_exec": 40,
}

VARIANT_REGIONS = [
    "New York",
    "Chicago",
    "Austin",
    "San Francisco",
    "Boston",
    "Washington DC",
    "Atlanta",
    "Phoenix",
    "Miami",
    "Seattle",
]

VARIANT_BROKERS = [
    "Robinhood",
    "Alpaca",
    "Fidelity",
    "Schwab",
    "Interactive Brokers",
    "Webull",
    "tastytrade",
]

VARIANT_ASSETS = [
    "SPY/QQQ shares",
    "0DTE index options",
    "semiconductor names",
    "leveraged ETFs",
    "broker/platform stocks",
    "small caps",
    "AI infrastructure names",
    "cash-account watchlists",
]

VARIANT_BEHAVIORS = [
    "treats broker UI screenshots as evidence",
    "waits for official policy text before acting",
    "copies high-engagement social posts",
    "uses a simple Python or TradingView script",
    "tracks order-flow and liquidity quality",
    "monitors support tickets and margin-call language",
    "reacts mainly to macro data and rates",
    "tests pre-trade checks through an API sandbox",
]


ANCHORS: List[Dict[str, Any]] = [
    {
        "name": "SEC Market Structure Staff",
        "entity_type": "RegulatorAgency",
        "category": "policy_regulatory",
        "profession": "Federal securities market-structure policy and investor protection staff",
        "bio": "Official-style securities policy staff account focused on market structure, broker implementation, and investor protection.",
        "persona": (
            "Represents SEC market-structure staff observing the PDT-to-intraday-margin transition. "
            "Does not trade or hype tickers. Evaluates whether broker messaging, API controls, and media narratives "
            "create investor-protection issues. Speaks carefully, cites rule mechanics, and distinguishes official policy "
            "from social shorthand."
        ),
        "topics": ["SEC market structure", "investor protection", "broker disclosures", "rule interpretation"],
        "activity": 0.18,
        "influence": 2.9,
        "stance": "observer",
    },
    {
        "name": "Congressional Market Structure Staff",
        "entity_type": "RegulatorAgency",
        "category": "policy_regulatory",
        "profession": "Policy-maker staff monitoring retail-market fairness and brokerage risk controls",
        "bio": "Policy staff watching whether rule-change narratives create visible retail harm or platform failures.",
        "persona": (
            "Represents policy-maker staff and legislative aides watching public reaction, complaint patterns, "
            "broker-platform fairness, and whether regulatory clarification is needed. Does not trade. "
            "Translates citizen complaints and media narratives into questions for hearings or staff briefings."
        ),
        "topics": ["retail investor complaints", "market fairness", "broker oversight", "policy hearings"],
        "activity": 0.12,
        "influence": 2.2,
        "stance": "observer",
    },
    {
        "name": "Citadel Securities Market Maker Desk",
        "entity_type": "InstitutionalInvestor",
        "category": "institutional_liquidity",
        "profession": "Electronic market making, liquidity provision, and retail order-flow risk management",
        "bio": "Institutional market-making desk observing novice clustering, spreads, and order-flow toxicity.",
        "persona": (
            "A market-making desk that watches novice order clustering, 0DTE demand, ETF flow, spread behavior, "
            "and broker-routing friction. It does not moralize about retail traders; it reprices liquidity, widens or "
            "tightens markets, and treats social screenshots as noisy flow signals."
        ),
        "topics": ["market making", "order-flow toxicity", "0DTE liquidity", "spread control"],
        "activity": 0.28,
        "influence": 2.7,
        "stance": "opposing",
    },
    {
        "name": "Jane Street ETF Quant Desk",
        "entity_type": "InstitutionalInvestor",
        "category": "institutional_liquidity",
        "profession": "ETF arbitrage, quantitative execution, and cross-asset liquidity analysis",
        "bio": "ETF and quant desk tracking whether retail flow distorts index products and levered ETF baskets.",
        "persona": (
            "A systematic ETF desk monitoring SPY, QQQ, IWM, leveraged ETFs, gamma pressure, and cross-asset hedges. "
            "Looks for retail-driven dislocations but remains skeptical unless price impact survives macro and auction data."
        ),
        "topics": ["ETF arbitrage", "index liquidity", "gamma exposure", "cross-asset hedging"],
        "activity": 0.24,
        "influence": 2.4,
        "stance": "observer",
    },
    {
        "name": "BlackRock iShares ETF Desk",
        "entity_type": "InstitutionalInvestor",
        "category": "institutional_liquidity",
        "profession": "ETF issuer liquidity, index-product monitoring, and institutional client risk communication",
        "bio": "ETF issuer desk monitoring index-product volumes, client questions, and retail-flow spillovers.",
        "persona": (
            "Represents an ETF issuer and institutional client desk. Watches whether small-account day-trading excitement "
            "changes ETF turnover, creation/redemption pressure, and client questions. Speaks in measured, institutional language."
        ),
        "topics": ["ETF flows", "creation redemption", "institutional clients", "index products"],
        "activity": 0.18,
        "influence": 2.3,
        "stance": "neutral",
    },
    {
        "name": "Volatility Market Maker Desk",
        "entity_type": "InstitutionalInvestor",
        "category": "institutional_liquidity",
        "profession": "Options market making, volatility surface monitoring, and 0DTE risk control",
        "bio": "Options liquidity desk tracking 0DTE retail demand, implied volatility, and hedging feedback loops.",
        "persona": (
            "An options market-making desk focused on 0DTE flow, volatility skew, gamma hedging, and intraday risk limits. "
            "Uses novice option demand as a liquidity signal and adjusts prices rapidly around payrolls, CPI, and Fed repricing."
        ),
        "topics": ["0DTE options", "volatility surface", "gamma hedging", "options liquidity"],
        "activity": 0.32,
        "influence": 2.5,
        "stance": "opposing",
    },
    {
        "name": "CNBC Markets Desk",
        "entity_type": "MediaOutlet",
        "category": "media_narrative",
        "profession": "Financial media desk covering retail flow, brokers, macro data, and market structure",
        "bio": "Markets-news desk translating broker-rule confusion, macro catalysts, and retail flow into public narratives.",
        "persona": (
            "A real-time financial media desk looking for accurate but clickable framing. Amplifies visible broker confusion, "
            "expert commentary, and market moves, while correcting oversimplified claims when official sources contradict them."
        ),
        "topics": ["financial news", "retail trading", "broker platforms", "macro catalysts"],
        "activity": 0.55,
        "influence": 2.6,
        "stance": "neutral",
    },
    {
        "name": "Bloomberg Market Structure Desk",
        "entity_type": "MediaOutlet",
        "category": "media_narrative",
        "profession": "Institutional financial journalism and market-structure data analysis",
        "bio": "Institutional news desk focused on market plumbing, broker implementation, and data-backed flow evidence.",
        "persona": (
            "A market-structure reporting desk that separates viral retail narratives from evidence in volumes, spreads, "
            "broker disclosures, and derivatives data. Uses institutional language and seeks corroboration before declaring a regime shift."
        ),
        "topics": ["market structure", "broker implementation", "volume analysis", "institutional commentary"],
        "activity": 0.38,
        "influence": 2.5,
        "stance": "observer",
    },
    {
        "name": "Open-source Trading Bot Maintainers",
        "entity_type": "DeveloperCommunity",
        "category": "developer_automation",
        "profession": "Open-source trading automation maintainers and risk-control reviewers",
        "bio": "Developer community maintaining trading-bot templates, API wrappers, and safety guard examples.",
        "persona": (
            "Maintainers of public trading-bot repositories and API templates. Debate whether to add intraday-margin checks, "
            "pre-trade buying-power guards, and warnings against copy-paste automation. Can accelerate both better controls and brittle bots."
        ),
        "topics": ["open-source bots", "broker APIs", "risk controls", "automation templates"],
        "activity": 0.62,
        "influence": 1.9,
        "stance": "neutral",
    },
    {
        "name": "Fintech Brokerage CEO Roundtable",
        "entity_type": "TechExecutive",
        "category": "tech_company_exec",
        "profession": "Brokerage and fintech executives shaping product rollout and public messaging",
        "bio": "Executive-level voices balancing growth narratives, compliance, customer education, and platform safety.",
        "persona": (
            "A composite executive roundtable for brokers and fintech platforms. Talks about customer access, platform reliability, "
            "AI-agent integrations, compliance obligations, and reputational risk. Does not trade; shapes public framing and product priorities."
        ),
        "topics": ["fintech strategy", "broker product rollout", "AI agents", "compliance messaging"],
        "activity": 0.2,
        "influence": 2.8,
        "stance": "neutral",
    },
    {
        "name": "AI Trading Infrastructure Founder",
        "entity_type": "TechExecutive",
        "category": "tech_company_exec",
        "profession": "AI trading infrastructure founder and agentic-finance product strategist",
        "bio": "Tech-executive voice pushing agentic trading tooling while acknowledging brokerage risk controls.",
        "persona": (
            "Founder of an AI trading-infrastructure startup. Frames the rule change as a product opportunity but must answer "
            "hard questions about safety, backtesting, rate limits, hallucinated strategies, and broker API failures."
        ),
        "topics": ["agentic trading", "AI infrastructure", "broker APIs", "product risk"],
        "activity": 0.34,
        "influence": 2.1,
        "stance": "supportive",
    },
]


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "agent"


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = ["user_id", "name", "username", "user_char", "description"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def classify_config(cfg: Dict[str, Any]) -> str:
    entity_type = str(cfg.get("entity_type", "")).lower()
    name = str(cfg.get("entity_name", "")).lower()
    if entity_type == "institutionalinvestor" or any(k in name for k in ["market maker", "quant desk", "etf desk", "volatility"]):
        return "institutional_liquidity"
    if entity_type == "techexecutive" or any(k in name for k in ["ceo", "founder", "executive"]):
        return "tech_company_exec"
    if entity_type == "regulatoragency" or any(k in name for k in ["finra", "fomc", "sec", "congressional"]):
        return "policy_regulatory"
    if entity_type == "brokerplatform" or any(k in name for k in ["broker", "fidelity", "schwab", "alpaca", "webull"]):
        return "broker_platform_clearing"
    if entity_type == "developercommunity" or any(k in name for k in ["bot", "developer", "api", "automation"]):
        return "developer_automation"
    if entity_type == "mediaoutlet" or "finfluencer" in entity_type or any(k in name for k in ["youtube", "cnbc", "bloomberg", "finfluencer"]):
        return "media_narrative"
    return "retail_new_traders"


def anchor_to_profile(anchor: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    return {
        "user_id": user_id,
        "username": f"{slugify(anchor['name'])}_{user_id}",
        "name": anchor["name"],
        "bio": anchor["bio"][:150],
        "persona": anchor["persona"],
        "karma": 2500 + (user_id % 5000),
        "created_at": "2026-06-03",
        "age": 42,
        "gender": "other",
        "mbti": "INTJ",
        "country": "United States",
        "profession": anchor["profession"],
        "interested_topics": anchor["topics"],
    }


def anchor_to_config(anchor: Dict[str, Any], agent_id: int, simulation_id: str) -> Dict[str, Any]:
    active_hours = list(range(9, 18))
    if anchor["category"] in {"retail_new_traders", "developer_automation", "media_narrative"}:
        active_hours = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]
    if anchor["category"] == "institutional_liquidity":
        active_hours = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
    return {
        "agent_id": agent_id,
        "entity_uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{simulation_id}:{anchor['name']}:{agent_id}")),
        "entity_name": anchor["name"],
        "entity_type": anchor["entity_type"],
        "activity_level": anchor["activity"],
        "posts_per_hour": round(0.6 + anchor["activity"] * 5.0, 2),
        "comments_per_hour": round(1.0 + anchor["activity"] * 8.0, 2),
        "active_hours": active_hours,
        "response_delay_min": 5 if anchor["category"] not in {"policy_regulatory", "tech_company_exec"} else 45,
        "response_delay_max": 35 if anchor["category"] not in {"policy_regulatory", "tech_company_exec"} else 180,
        "sentiment_bias": 0.0,
        "stance": anchor["stance"],
        "influence_weight": anchor["influence"],
    }


def make_variant(
    source_profile: Dict[str, Any],
    source_config: Dict[str, Any],
    agent_id: int,
    category: str,
    simulation_id: str,
    rng: random.Random,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    region = rng.choice(VARIANT_REGIONS)
    broker = rng.choice(VARIANT_BROKERS)
    asset = rng.choice(VARIANT_ASSETS)
    behavior = rng.choice(VARIANT_BEHAVIORS)
    risk = rng.choice(["low", "medium", "high", "very high"])
    cohort = f"{category.replace('_', ' ')} cohort {agent_id:04d}"
    source_name = str(source_profile.get("name") or source_config.get("entity_name") or "agent")
    variant_name = f"{source_name} {agent_id:04d}"
    username = f"{slugify(source_name)}_{agent_id:04d}"
    note = (
        f"Variant notes: {cohort}; region={region}; broker={broker}; focus={asset}; "
        f"risk_tolerance={risk}; behavior={behavior}. "
        "Respond consistently with the source archetype while preserving this local context."
    )
    base_persona = str(source_profile.get("persona") or source_profile.get("user_char") or source_profile.get("bio") or "")
    base_persona = base_persona.replace("\n", " ").strip()
    if len(base_persona) > 1200:
        base_persona = base_persona[:1200].rsplit(" ", 1)[0] + "..."
    bio = str(source_profile.get("bio") or source_profile.get("description") or source_name)
    bio = bio.replace("\n", " ").strip()
    if len(bio) > 110:
        bio = bio[:110].rsplit(" ", 1)[0]
    profile = deepcopy(source_profile)
    profile.update(
        {
            "user_id": agent_id,
            "username": username,
            "name": variant_name,
            "bio": f"{bio} | {region} | {broker}"[:150],
            "persona": f"{base_persona} {note}".strip(),
            "karma": int(source_profile.get("karma") or 1000) + (agent_id % 997),
            "created_at": "2026-06-03",
            "country": "United States",
        }
    )
    topics = list(source_profile.get("interested_topics") or [])
    for topic in [asset, broker, category.replace("_", " ")]:
        if topic not in topics:
            topics.append(topic)
    profile["interested_topics"] = topics[:10]

    cfg = deepcopy(source_config)
    cfg.update(
        {
            "agent_id": agent_id,
            "entity_uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{simulation_id}:{variant_name}:{agent_id}")),
            "entity_name": variant_name,
            "entity_type": source_config.get("entity_type", "Person"),
        }
    )
    jitter = rng.uniform(0.85, 1.15)
    cfg["activity_level"] = max(0.05, min(0.98, round(float(cfg.get("activity_level", 0.5)) * jitter, 3)))
    cfg["posts_per_hour"] = max(0.1, round(float(cfg.get("posts_per_hour", 1.0)) * rng.uniform(0.8, 1.2), 2))
    cfg["comments_per_hour"] = max(0.1, round(float(cfg.get("comments_per_hour", 2.0)) * rng.uniform(0.8, 1.2), 2))
    cfg["influence_weight"] = max(0.3, round(float(cfg.get("influence_weight", 1.0)) * rng.uniform(0.75, 1.1), 2))

    twitter_row = {
        "user_id": agent_id,
        "name": variant_name,
        "username": username,
        "user_char": f"{profile['bio']} {profile['persona']}".replace("\n", " ").replace("\r", " "),
        "description": profile["bio"],
    }
    return profile, twitter_row, cfg


def choose_sources_by_category(
    reddit_profiles: List[Dict[str, Any]],
    twitter_rows: List[Dict[str, str]],
    agent_configs: List[Dict[str, Any]],
) -> Dict[str, List[Tuple[Dict[str, Any], Dict[str, str], Dict[str, Any]]]]:
    twitter_by_id = {int(row["user_id"]): row for row in twitter_rows if str(row.get("user_id", "")).isdigit()}
    profile_by_id = {int(p["user_id"]): p for p in reddit_profiles if isinstance(p.get("user_id"), int)}
    grouped: Dict[str, List[Tuple[Dict[str, Any], Dict[str, str], Dict[str, Any]]]] = {key: [] for key in CATEGORY_QUOTAS}
    for cfg in agent_configs:
        agent_id = int(cfg.get("agent_id", 0))
        profile = profile_by_id.get(agent_id)
        twitter = twitter_by_id.get(agent_id)
        if not profile or not twitter:
            continue
        grouped.setdefault(classify_config(cfg), []).append((profile, twitter, cfg))
    return grouped


def build_expanded(sim_dir: Path, target: int, seed: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    config_path = sim_dir / "simulation_config.json"
    reddit_path = sim_dir / "reddit_profiles.json"
    twitter_path = sim_dir / "twitter_profiles.csv"
    config = load_json(config_path)
    reddit_profiles = load_json(reddit_path)
    twitter_rows = read_csv_rows(twitter_path)

    if target < len(reddit_profiles):
        raise ValueError(f"target {target} is smaller than existing profile count {len(reddit_profiles)}")

    rng = random.Random(seed)
    agent_configs = config.get("agent_configs", [])
    expanded_reddit = [deepcopy(p) for p in reddit_profiles]
    expanded_twitter = [deepcopy(r) for r in twitter_rows]
    expanded_configs = [deepcopy(c) for c in agent_configs]

    next_id = len(expanded_reddit)
    for anchor in ANCHORS:
        if next_id >= target:
            break
        expanded_reddit.append(anchor_to_profile(anchor, next_id))
        cfg = anchor_to_config(anchor, next_id, config.get("simulation_id", "simulation"))
        expanded_configs.append(cfg)
        expanded_twitter.append(
            {
                "user_id": next_id,
                "name": anchor["name"],
                "username": f"{slugify(anchor['name'])}_{next_id}",
                "user_char": f"{anchor['bio']} {anchor['persona']}",
                "description": anchor["bio"],
            }
        )
        next_id += 1

    grouped = choose_sources_by_category(expanded_reddit, expanded_twitter, expanded_configs)
    for anchor in ANCHORS:
        category = anchor["category"]
        aid = next(
            (idx for idx, profile in enumerate(expanded_reddit) if profile.get("name") == anchor["name"]),
            None,
        )
        if aid is not None:
            grouped.setdefault(category, []).append((expanded_reddit[aid], expanded_twitter[aid], expanded_configs[aid]))

    desired_counts = dict(CATEGORY_QUOTAS)
    if target != sum(CATEGORY_QUOTAS.values()):
        scale = target / sum(CATEGORY_QUOTAS.values())
        desired_counts = {key: int(round(value * scale)) for key, value in CATEGORY_QUOTAS.items()}
        delta = target - sum(desired_counts.values())
        desired_counts["retail_new_traders"] += delta

    current_counts = {key: 0 for key in desired_counts}
    for cfg in expanded_configs:
        category = classify_config(cfg)
        current_counts[category] = current_counts.get(category, 0) + 1

    category_order: List[str] = []
    for category, desired in desired_counts.items():
        category_order.extend([category] * max(0, desired - current_counts.get(category, 0)))
    rng.shuffle(category_order)

    source_indices = {key: 0 for key in desired_counts}
    for category in category_order:
        if next_id >= target:
            break
        sources = grouped.get(category) or grouped["retail_new_traders"]
        if not sources:
            raise ValueError(f"no source archetypes available for {category}")
        source = sources[source_indices[category] % len(sources)]
        source_indices[category] += 1
        profile, twitter_row, cfg = make_variant(
            source_profile=source[0],
            source_config=source[2],
            agent_id=next_id,
            category=category,
            simulation_id=config.get("simulation_id", "simulation"),
            rng=rng,
        )
        expanded_reddit.append(profile)
        expanded_twitter.append(twitter_row)
        expanded_configs.append(cfg)
        next_id += 1

    config["agent_configs"] = expanded_configs[:target]
    config.setdefault("expansion_metadata", {})
    config["expansion_metadata"] = {
        "expanded_at": datetime.now(timezone.utc).isoformat(),
        "target_agents": target,
        "method": "deterministic archetype expansion from stage02 profiles plus institutional anchors",
        "seed": seed,
        "anchors_added": [a["name"] for a in ANCHORS],
        "category_quotas": desired_counts,
    }
    config["generation_reasoning"] = (
        str(config.get("generation_reasoning", ""))
        + f" | Population expansion: stage02 archetypes expanded to {target} agents with explicit institutional, market-maker, media, developer, policy, and tech-executive anchors."
    ).strip()

    # Add institutional initial posts if anchors were inserted.
    name_to_id = {cfg["entity_name"]: cfg["agent_id"] for cfg in config["agent_configs"]}
    extra_posts = [
        (
            "Citadel Securities Market Maker Desk",
            "Market-maker desk note: early retail clustering is visible in index options, but liquidity response will depend on macro data, broker pre-trade checks, and spread quality.",
            "InstitutionalInvestor",
        ),
        (
            "SEC Market Structure Staff",
            "Investor-protection reminder: removal of the old PDT framework should not be interpreted as unlimited leverage or absence of broker risk controls.",
            "RegulatorAgency",
        ),
        (
            "Fintech Brokerage CEO Roundtable",
            "Executive product note: access expansion only works if customer education, API checks, and real-time margin controls are understandable at the point of trade.",
            "TechExecutive",
        ),
        (
            "Bloomberg Market Structure Desk",
            "Market-structure desk: watch volumes, rejected orders, spread behavior, and real broker notices before attributing index moves to the rule change.",
            "MediaOutlet",
        ),
    ]
    initial_posts = config.setdefault("event_config", {}).setdefault("initial_posts", [])
    existing_contents = {post.get("content") for post in initial_posts}
    for name, content, poster_type in extra_posts:
        agent_id = name_to_id.get(name)
        if agent_id is not None and content not in existing_contents:
            initial_posts.append({"content": content, "poster_type": poster_type, "poster_agent_id": agent_id})

    return config, expanded_reddit[:target], expanded_twitter[:target]


def counts(agent_configs: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for cfg in agent_configs:
        category = classify_config(cfg)
        result[category] = result.get(category, 0) + 1
    return dict(sorted(result.items()))


def backup_files(sim_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = sim_dir / f"pre_expansion_backup_{stamp}"
    backup_dir.mkdir(exist_ok=False)
    for name in ["simulation_config.json", "reddit_profiles.json", "twitter_profiles.csv", "state.json"]:
        path = sim_dir / name
        if path.exists():
            shutil.copy2(path, backup_dir / name)
    return backup_dir


def update_state(sim_dir: Path, target: int) -> None:
    state_path = sim_dir / "state.json"
    if not state_path.exists():
        return
    state = load_json(state_path)
    state["profiles_count"] = target
    state["expanded_agents_count"] = target
    state["agent_population_expanded"] = True
    state["updated_at"] = datetime.now().isoformat()
    write_json(state_path, state)


def main() -> int:
    parser = argparse.ArgumentParser(description="Expand prepared MiroFish agent population.")
    parser.add_argument("--simulation-id", required=True)
    parser.add_argument("--target", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260603)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    sim_dir = ROOT / "backend" / "uploads" / "simulations" / args.simulation_id
    if not sim_dir.exists():
        raise SystemExit(f"Simulation directory not found: {sim_dir}")

    config, reddit_profiles, twitter_rows = build_expanded(sim_dir, args.target, args.seed)
    result = {
        "simulation_id": args.simulation_id,
        "sim_dir": str(sim_dir),
        "mode": "dry_run",
        "target_agents": args.target,
        "expanded_counts": counts(config.get("agent_configs", [])),
        "initial_posts": len(config.get("event_config", {}).get("initial_posts", [])),
        "required_confirm": CONFIRM,
        "side_effects": "none",
    }

    if args.execute:
        if args.confirm != CONFIRM:
            raise SystemExit(f"Execution requires --confirm {CONFIRM!r}")
        backup_dir = backup_files(sim_dir)
        write_json(sim_dir / "simulation_config.json", config)
        write_json(sim_dir / "reddit_profiles.json", reddit_profiles)
        write_csv_rows(sim_dir / "twitter_profiles.csv", twitter_rows)
        update_state(sim_dir, args.target)
        result.update(
            {
                "mode": "executed",
                "backup_dir": str(backup_dir),
                "side_effects": "expanded simulation_config.json, reddit_profiles.json, twitter_profiles.csv, and state.json",
            }
        )

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
