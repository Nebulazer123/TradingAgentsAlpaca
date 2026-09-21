# Agent Communication and Strategy Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TradingAgents communicate through compact, verifiable evidence packets and improve its decisions over time by scoring agent forecasts, promoting useful evidence, generating bounded strategy variants, testing them out of sample, and automatically promoting, demoting, or rolling them back.

**Architecture:** Keep the current analyst, bull/bear, trader, risk-debate, and portfolio-manager roles. Add deterministic packet compiler nodes at major handoff boundaries, one append-only decision/event ledger, a bounded learning context derived only from resolved outcomes, and a strategy genome layer that changes parameters rather than editing executable trading code. LLMs propose; schemas, time splits, the paper tournament, risk envelopes, and promotion gates decide what is eligible.

**Tech Stack:** Existing LangGraph state graph, dataclasses, JSON/JSONL, SHA-256 evidence digests, existing agent-intelligence ledger/hypothesis factory/lifecycle/paper tournament/promotion sync modules, pytest, and existing model telemetry.

## Global Constraints

- Packet references are the communication spine; raw transcripts are drill-down evidence.
- Each mutable state has one canonical owner. Other files point to it instead of copying a second authoritative value.
- Agent reputation is contextual and outcome-based. A high score in one sector, horizon, or evidence type does not grant global authority.
- Only resolved forecasts may change agent influence. Pending forecasts are not wins or losses.
- No future-dated price/news/evidence may enter a historical evaluation.
- Ordinary strategy evolution changes validated parameter genomes, not Python source code during a market session.
- A candidate must be preregistered before its evaluation window begins.
- Strategy selection uses out-of-sample and paper evidence; a persuasive LLM explanation is not promotion evidence.
- Preserve `HOLD_CASH` as a first-class strategy and action.
- Worker roles are event-driven. Parallelize independent analysis; do not delegate tiny deterministic operations.
- Cap compact learning and handoff context so the intelligence layer does not consume more tokens than the decision it supports.

---

### Task 1: Define Compact Evidence And Work Packets

**Files:**
- Create: `tradingagents/orchestration/work_packets.py`
- Create: `tests/test_work_packets.py`
- Modify: `tradingagents/orchestration/__init__.py`

- [ ] **Step 1: Write failing packet tests**

```python
import datetime as dt
from pathlib import Path

import pytest

from tradingagents.orchestration.work_packets import (
    EvidenceRef,
    WorkPacket,
    validate_work_packet,
)


def test_evidence_ref_detects_source_mutation(tmp_path):
    source = tmp_path / "research.json"
    source.write_text('{"stance":"bullish"}')
    ref = EvidenceRef.from_path(source)
    assert ref.verify() is True
    source.write_text('{"stance":"bearish"}')
    assert ref.verify() is False


def test_packet_contains_only_compact_handoff_fields(tmp_path):
    source = tmp_path / "research.json"
    source.write_text('{"stance":"bullish"}')
    packet = WorkPacket.create(
        packet_id="packet-1",
        kind="research_synthesis",
        producer_role="research_manager",
        run_id="research-run-1",
        subject="NFLX",
        evidence_refs=[EvidenceRef.from_path(source)],
        claims=["NFLX has support near the current price"],
        assumptions=["regular market session"],
        recommendation="hold_cash",
        confidence=0.62,
        expires_at=dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(hours=2),
    )
    assert validate_work_packet(packet) == []
    assert "raw_transcript" not in packet.compact()
    assert len(packet.compact()["claims"]) == 1


def test_expired_or_unverifiable_packet_is_rejected(tmp_path):
    packet = WorkPacket.create(
        packet_id="packet-2",
        kind="risk_review",
        producer_role="risk_council",
        run_id="risk-run-1",
        subject="NFLX",
        evidence_refs=[],
        claims=[],
        assumptions=[],
        recommendation="block",
        confidence=0.8,
        expires_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    )
    issues = validate_work_packet(
        packet,
        now=dt.datetime(2026, 7, 18, tzinfo=dt.timezone.utc),
    )
    assert "packet expired" in issues
```

- [ ] **Step 2: Run and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_work_packets.py -q
```

Expected: FAIL because the packet module does not exist.

- [ ] **Step 3: Implement evidence references**

```python
@dataclass(frozen=True)
class EvidenceRef:
    path: str
    sha256: str
    size_bytes: int

    @classmethod
    def from_path(cls, path: str | Path) -> "EvidenceRef":
        source = Path(path)
        payload = source.read_bytes()
        return cls(
            path=str(source),
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
        )

    def verify(self) -> bool:
        source = Path(self.path)
        if not source.is_file():
            return False
        payload = source.read_bytes()
        return (
            len(payload) == self.size_bytes
            and hashlib.sha256(payload).hexdigest() == self.sha256
        )
```

- [ ] **Step 4: Implement the packet schema**

`WorkPacket` must contain:

```text
schema_version
packet_id
kind
created_at
expires_at
producer_role
run_id
subject
evidence_refs
parent_packet_ids
claims
assumptions
recommendation
confidence
allowed_effects
forbidden_effects
```

Use `WorkPacket.create()` to:

- Require non-empty `packet_id`, `kind`, `producer_role`, `run_id`, and `subject`.
- Clamp confidence to `0.0 <= confidence <= 1.0` by rejecting out-of-range values.
- Default `parent_packet_ids`, `allowed_effects`, and `forbidden_effects` to empty tuples.
- Record UTC ISO timestamps.

`compact()` returns:

```python
{
    "packet_id": self.packet_id,
    "kind": self.kind,
    "created_at": self.created_at,
    "expires_at": self.expires_at,
    "producer_role": self.producer_role,
    "run_id": self.run_id,
    "subject": self.subject,
    "evidence_refs": [asdict(ref) for ref in self.evidence_refs],
    "parent_packet_ids": list(self.parent_packet_ids),
    "claims": list(self.claims[:5]),
    "assumptions": list(self.assumptions[:5]),
    "recommendation": self.recommendation,
    "confidence": self.confidence,
    "allowed_effects": list(self.allowed_effects),
    "forbidden_effects": list(self.forbidden_effects),
}
```

`validate_work_packet()` must reject expiry, missing required fields, more than five compact claims/assumptions, invalid confidence, and any missing or digest-mismatched evidence reference.

- [ ] **Step 5: Verify and commit**

```bash
uv run --with pytest python -m pytest tests/test_work_packets.py -q
git add tradingagents/orchestration/work_packets.py tradingagents/orchestration/__init__.py tests/test_work_packets.py
git commit -m "feat: add compact verifiable work packets"
```

Expected: PASS.

---

### Task 2: Add One Canonical Decision And Event Ledger

**Files:**
- Create: `tradingagents/orchestration/decision_ledger.py`
- Create: `tests/test_decision_ledger.py`
- Modify: `scripts/automation_context_snapshot.py`

- [ ] **Step 1: Write failing single-authority tests**

```python
from tradingagents.orchestration.decision_ledger import DecisionLedger


def test_ledger_appends_events_and_updates_kind_pointer(tmp_path, packet):
    ledger = DecisionLedger(tmp_path)
    path = ledger.record(packet)
    assert path.exists()
    assert (tmp_path / "events.jsonl").read_text().count("\n") == 1
    assert (tmp_path / "latest" / "research_synthesis.json").exists()


def test_recording_same_packet_id_is_idempotent(tmp_path, packet):
    ledger = DecisionLedger(tmp_path)
    first = ledger.record(packet)
    second = ledger.record(packet)
    assert first == second
    assert (tmp_path / "events.jsonl").read_text().count("\n") == 1


def test_same_id_with_different_payload_is_rejected(tmp_path, packet):
    ledger = DecisionLedger(tmp_path)
    ledger.record(packet)
    changed = dataclasses.replace(packet, recommendation="buy")
    with pytest.raises(ValueError, match="packet id collision"):
        ledger.record(changed)
```

- [ ] **Step 2: Run and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_decision_ledger.py -q
```

Expected: FAIL.

- [ ] **Step 3: Implement the ledger**

Canonical paths:

```text
results/control_plane/decisions/events.jsonl
results/control_plane/decisions/packets/<packet_id>.json
results/control_plane/decisions/latest/<kind>.json
```

`DecisionLedger.record()` must:

1. Validate the packet.
2. Serialize with sorted keys.
3. Hash the serialized packet.
4. Return the existing path without appending when the same ID and digest already exist.
5. Reject the same ID with a different digest.
6. Atomically write the immutable packet and latest pointer.
7. Append one compact event line containing only `packet_id`, `kind`, `producer_role`, `run_id`, `subject`, `recommendation`, `confidence`, `created_at`, and `digest`.

- [ ] **Step 4: Expose only compact ledger health**

Add to the context snapshot:

```json
{
  "decision_packet_count_24h": 12,
  "invalid_packet_count_24h": 0,
  "expired_latest_kind_count": 0,
  "latest_decision_refs": {
    "research_synthesis": "results/control_plane/decisions/latest/research_synthesis.json",
    "portfolio_decision": "results/control_plane/decisions/latest/portfolio_decision.json"
  }
}
```

- [ ] **Step 5: Verify and commit**

```bash
uv run --with pytest python -m pytest tests/test_decision_ledger.py tests/test_automation_context_snapshot.py -q
git add tradingagents/orchestration/decision_ledger.py scripts/automation_context_snapshot.py tests/test_decision_ledger.py tests/test_automation_context_snapshot.py
git commit -m "feat: add canonical decision ledger"
```

Expected: PASS.

---

### Task 3: Packetize The Existing TradingAgents Graph At Decision Boundaries

**Files:**
- Create: `tradingagents/graph/packet_nodes.py`
- Modify: `tradingagents/agents/utils/agent_states.py`
- Modify: `tradingagents/graph/propagation.py`
- Modify: `tradingagents/graph/setup.py`
- Modify: `tradingagents/graph/trading_graph.py`
- Create: `tests/test_graph_packet_handoffs.py`
- Modify: `tests/test_original_tradingagents_workflow.py`

- [ ] **Step 1: Write the failing graph-shape test**

```python
def test_graph_has_deterministic_packet_boundaries(compiled_workflow):
    nodes = set(compiled_workflow.nodes)
    assert {
        "Research Evidence Packet",
        "Trader Proposal Packet",
        "Portfolio Decision Packet",
    } <= nodes


def test_packet_nodes_do_not_call_llms(monkeypatch, sample_agent_state, tmp_path):
    node = create_research_evidence_packet_node(tmp_path)
    output = node(sample_agent_state)
    assert output["decision_packet_refs"]
    assert output["decision_packet_refs"][-1]["kind"] == "research_evidence"
```

- [ ] **Step 2: Run and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_graph_packet_handoffs.py -q
```

Expected: FAIL because the packet nodes do not exist.

- [ ] **Step 3: Extend state without replacing existing reports**

Add:

```python
decision_packet_refs: Annotated[list[dict], "Compact decision packet references"]
learning_context: Annotated[str, "Bounded outcome-derived context"]
```

Initialize both in `Propagator.create_initial_state()`:

```python
"decision_packet_refs": [],
"learning_context": "",
```

- [ ] **Step 4: Implement deterministic packet compiler nodes**

Create three factories:

```python
create_research_evidence_packet_node(ledger_root)
create_trader_proposal_packet_node(ledger_root)
create_portfolio_decision_packet_node(ledger_root)
```

Each node:

1. Reads the relevant existing state fields.
2. Writes its full state slice to one evidence JSON file.
3. Builds an `EvidenceRef`.
4. Creates a `WorkPacket`.
5. Records it through `DecisionLedger`.
6. Returns the prior `decision_packet_refs` plus the new compact packet.
7. Calls no model and no tool.

Use these mappings:

```text
research_evidence:
  market_report, sentiment_report, news_report, fundamentals_report

trader_proposal:
  investment_debate_state.judge_decision, investment_plan, trader_investment_plan

portfolio_decision:
  risk_debate_state.judge_decision, final_trade_decision
```

- [ ] **Step 5: Wire the nodes without removing the existing roles**

Graph order:

```text
analyst batches
-> Research Evidence Packet
-> Bull Researcher
<-> Bear Researcher
-> Research Manager
-> Trader
-> Trader Proposal Packet
-> Aggressive/Conservative/Neutral risk debate
-> Portfolio Manager
-> Portfolio Decision Packet
-> END
```

Preserve current analyst concurrency and tool-loop behavior.

- [ ] **Step 6: Verify and commit**

```bash
uv run --with pytest python -m pytest \
  tests/test_graph_packet_handoffs.py \
  tests/test_original_tradingagents_workflow.py \
  tests/test_analyst_concurrency.py \
  tests/test_structured_agents.py -q
git add tradingagents/graph/packet_nodes.py tradingagents/agents/utils/agent_states.py tradingagents/graph/propagation.py tradingagents/graph/setup.py tradingagents/graph/trading_graph.py tests/test_graph_packet_handoffs.py tests/test_original_tradingagents_workflow.py
git commit -m "feat: packetize agent decision handoffs"
```

Expected: PASS.

---

### Task 4: Inject Bounded Outcome-Derived Learning Context

**Files:**
- Create: `tradingagents/evals/learning_context.py`
- Create: `tests/test_learning_context.py`
- Modify: `tradingagents/graph/trading_graph.py`
- Modify: `tradingagents/graph/propagation.py`

- [ ] **Step 1: Write failing context-budget and outcome tests**

```python
from tradingagents.evals.learning_context import build_learning_context


def test_learning_context_is_bounded():
    context = build_learning_context(
        memory_context="m" * 6000,
        influence_context="i" * 6000,
        hypothesis_context="h" * 6000,
        max_chars=4000,
    )
    assert len(context) <= 4000


def test_context_keeps_source_sections_separate():
    context = build_learning_context(
        memory_context="Past decisions",
        influence_context="Resolved agent scores",
        hypothesis_context="Active preregistered hypotheses",
        max_chars=4000,
    )
    assert "Past decisions" in context
    assert "Resolved agent scores" in context
    assert "Active preregistered hypotheses" in context


def test_pending_forecasts_do_not_change_influence(resolved_and_pending_ledger):
    context = learning_context_from_stores(
        ledger_path=resolved_and_pending_ledger,
        as_of="2026-07-18",
    )
    assert "pending-forecast-agent" not in context
```

- [ ] **Step 2: Run and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_learning_context.py -q
```

Expected: FAIL.

- [ ] **Step 3: Implement the compact combiner**

```python
SECTION_ORDER = (
    ("Past outcome lessons", "memory_context"),
    ("Contextual agent influence", "influence_context"),
    ("Active preregistered hypotheses", "hypothesis_context"),
)


def build_learning_context(
    *,
    memory_context: str,
    influence_context: str,
    hypothesis_context: str,
    max_chars: int = 4000,
) -> str:
    if max_chars < 256:
        raise ValueError("max_chars must be at least 256")
    sections = {
        "memory_context": memory_context.strip(),
        "influence_context": influence_context.strip(),
        "hypothesis_context": hypothesis_context.strip(),
    }
    nonempty = [(title, sections[key]) for title, key in SECTION_ORDER if sections[key]]
    if not nonempty:
        return ""
    per_section = max(64, (max_chars - 64) // len(nonempty))
    rendered = [
        f"## {title}\n{body[:per_section].rstrip()}"
        for title, body in nonempty
    ]
    return "\n\n".join(rendered)[:max_chars].rstrip()
```

- [ ] **Step 4: Build context only from eligible records**

`learning_context_from_stores()` must:

- Call existing agent-ledger functions using resolved forecasts only.
- Filter forecasts and hypotheses to `created_at <= as_of`.
- Include at most four agent influence records matched to ticker, sector, evidence type, and horizon.
- Include at most four active preregistered hypotheses.
- Exclude rejected, retired, pending, unresolved, or future records.
- Include source packet IDs so the manager can drill down when needed.

- [ ] **Step 5: Inject it once per graph run**

In `TradingAgentsGraph.propagate()`:

```python
memory_context = self.memory_log.get_past_context(company_name)
learning_context = learning_context_from_stores(
    ticker=company_name,
    as_of=trade_date,
    max_chars=int(self.config.get("learning_context_max_chars", 4000)),
)
past_context = build_learning_context(
    memory_context=memory_context,
    influence_context=learning_context.influence,
    hypothesis_context=learning_context.hypotheses,
    max_chars=int(self.config.get("learning_context_max_chars", 4000)),
)
```

Do not inject the same context separately into every analyst prompt.

- [ ] **Step 6: Verify and commit**

```bash
uv run --with pytest python -m pytest \
  tests/test_learning_context.py \
  tests/test_agent_intelligence_ledger.py \
  tests/test_hypothesis_factory.py \
  tests/test_hypothesis_lifecycle.py \
  tests/test_memory_log.py -q
git add tradingagents/evals/learning_context.py tradingagents/graph/trading_graph.py tradingagents/graph/propagation.py tests/test_learning_context.py
git commit -m "feat: inject bounded outcome learning"
```

Expected: PASS.

---

### Task 5: Define Safe Strategy Genomes

**Files:**
- Create: `tradingagents/strategy/__init__.py`
- Create: `tradingagents/strategy/genome.py`
- Create: `config/strategy_evolution.json`
- Create: `tests/test_strategy_genome.py`

- [ ] **Step 1: Write failing validation tests**

```python
import pytest

from tradingagents.strategy.genome import StrategyFamily, StrategyGenome


def test_valid_pullback_genome_has_stable_id():
    genome = StrategyGenome.create(
        family=StrategyFamily.PULLBACK_SUPPORT,
        entry_threshold="-2.0",
        stop_loss_pct="-8.0",
        take_profit_pct="6.0",
        max_holding_days=10,
        max_position_pct="25.0",
        min_dollar_volume="10000000",
        generation=1,
        parent_id="current-aggressive",
    )
    assert genome.genome_id == StrategyGenome.from_dict(genome.to_dict()).genome_id


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("entry_threshold", "-25"),
        ("stop_loss_pct", "1"),
        ("take_profit_pct", "-1"),
        ("max_holding_days", 0),
        ("max_position_pct", "101"),
        ("min_dollar_volume", "-1"),
    ],
)
def test_out_of_envelope_genome_is_rejected(field, value):
    values = {
        "family": StrategyFamily.PULLBACK_SUPPORT,
        "entry_threshold": "-2",
        "stop_loss_pct": "-8",
        "take_profit_pct": "6",
        "max_holding_days": 10,
        "max_position_pct": "25",
        "min_dollar_volume": "10000000",
        "generation": 1,
        "parent_id": "base",
    }
    values[field] = value
    with pytest.raises(ValueError):
        StrategyGenome.create(**values)
```

- [ ] **Step 2: Run and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_strategy_genome.py -q
```

Expected: FAIL.

- [ ] **Step 3: Implement the genome**

Families:

```python
class StrategyFamily(str, Enum):
    HOLD_CASH = "hold_cash"
    PULLBACK_SUPPORT = "pullback_support"
    CATALYST_RELATIVE_STRENGTH = "catalyst_relative_strength"
    MEAN_REVERSION = "mean_reversion"
    MOMENTUM = "momentum"
```

Validation envelope:

```text
-10 <= entry_threshold <= 10
-20 <= stop_loss_pct <= -1
1 <= take_profit_pct <= 30
1 <= max_holding_days <= 60
1 <= max_position_pct <= 35
0 <= min_dollar_volume
0 <= generation
```

`genome_id` is:

```python
payload = json.dumps(self.parameter_payload(), sort_keys=True, separators=(",", ":"))
return f"{self.family.value}-{hashlib.sha256(payload.encode()).hexdigest()[:12]}"
```

Store decimals as strings in JSON.

- [ ] **Step 4: Add the evolution policy**

```json
{
  "schema_version": 1,
  "enabled": true,
  "max_active_candidates": 8,
  "mutations_per_cycle": 3,
  "minimum_tracked_days": 5,
  "minimum_closed_trades": 10,
  "minimum_walk_forward_windows": 3,
  "maximum_live_drawdown_pct": -10,
  "mutation_bounds": {
    "entry_threshold": 0.5,
    "stop_loss_pct": 1.0,
    "take_profit_pct": 1.0,
    "max_holding_days": 2,
    "max_position_pct": 2.5
  }
}
```

- [ ] **Step 5: Verify and commit**

```bash
uv run --with pytest python -m pytest tests/test_strategy_genome.py -q
git add tradingagents/strategy config/strategy_evolution.json tests/test_strategy_genome.py
git commit -m "feat: define bounded strategy genomes"
```

Expected: PASS.

---

### Task 6: Generate, Preregister, And Evaluate Strategy Variants

**Files:**
- Create: `tradingagents/strategy/evolution.py`
- Create: `tradingagents/strategy/registry.py`
- Create: `tests/test_strategy_evolution.py`
- Create: `tests/test_strategy_registry.py`
- Modify: `tradingagents/brokers/paper_tournament.py`
- Modify: `tests/test_paper_tournament.py`

- [ ] **Step 1: Write failing deterministic mutation tests**

```python
def test_mutation_is_deterministic_for_seed(base_genome):
    first = mutate_genome(base_genome, seed="cycle-2026-07-18", count=3)
    second = mutate_genome(base_genome, seed="cycle-2026-07-18", count=3)
    assert [item.genome_id for item in first] == [item.genome_id for item in second]


def test_candidate_is_registered_before_evaluation(base_genome, tmp_path):
    registry = StrategyRegistry(tmp_path / "registry.jsonl")
    record = registry.preregister(
        base_genome,
        hypothesis="shallower pullbacks improve fill quality",
        evaluation_start="2026-07-20",
        evaluation_end="2026-08-03",
    )
    assert record["registered_at"] < record["evaluation_start"]


def test_tournament_accepts_registered_dynamic_genome(base_genome, tmp_path):
    ledger = initialize_tournament(
        starting_cash=Decimal("200"),
        strategy_genomes=[base_genome],
        strategy_registry_path=tmp_path / "registry.jsonl",
    )
    assert base_genome.genome_id in {
        item["strategy_id"] for item in ledger["strategies"]
    }
```

- [ ] **Step 2: Run and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_strategy_evolution.py tests/test_strategy_registry.py -q
```

Expected: FAIL.

- [ ] **Step 3: Implement bounded mutation**

`mutate_genome()` must:

- Use `random.Random(seed)` rather than global randomness.
- Change one or two parameters per child.
- Clamp every result through `StrategyGenome.create()`.
- Never mutate `HOLD_CASH`.
- Reject a duplicate `genome_id`.
- Record `parent_id` and increment `generation`.

- [ ] **Step 4: Implement append-only preregistration**

Each registry line contains:

```json
{
  "schema_version": 1,
  "genome": {},
  "genome_id": "pullback_support-abc123",
  "hypothesis": "shallower pullbacks improve fill quality",
  "registered_at": "2026-07-18T00:00:00+00:00",
  "evaluation_start": "2026-07-20T00:00:00+00:00",
  "evaluation_end": "2026-08-03T00:00:00+00:00",
  "status": "paper_candidate"
}
```

Reject a registration whose evaluation start is not after `registered_at`.

- [ ] **Step 5: Adapt the tournament**

Extend `initialize_tournament()` with optional:

```python
strategy_genomes: Sequence[StrategyGenome] | None = None
strategy_registry_path: str | Path | None = None
```

When provided:

- Verify every genome is preregistered.
- Convert each genome to the existing strategy ledger shape.
- Preserve all current built-in strategies by default.
- Keep paper and live cash accounting isolated.
- Include `genome_id`, `parent_id`, `generation`, and registry reference in reports.

- [ ] **Step 6: Verify and commit**

```bash
uv run --with pytest python -m pytest \
  tests/test_strategy_genome.py \
  tests/test_strategy_evolution.py \
  tests/test_strategy_registry.py \
  tests/test_paper_tournament.py -q
git add tradingagents/strategy tradingagents/brokers/paper_tournament.py tests/test_strategy_evolution.py tests/test_strategy_registry.py tests/test_paper_tournament.py
git commit -m "feat: evolve preregistered paper strategies"
```

Expected: PASS.

---

### Task 7: Select, Promote, Demote, And Roll Back Dynamic Strategies

**Files:**
- Create: `tradingagents/strategy/selection.py`
- Create: `tests/test_strategy_selection.py`
- Modify: `tradingagents/policy/promotion_sync.py`
- Modify: `tests/test_promotion_sync.py`
- Modify: `tradingagents/policy/live_gate.py`
- Modify: `tests/test_live_gate.py`

- [ ] **Step 1: Write failing selection tests**

```python
def test_candidate_needs_walk_forward_and_paper_evidence(candidate_evidence):
    decision = select_strategy_candidate(candidate_evidence)
    assert decision.eligible is True
    assert decision.reason == "all machine promotion gates passed"


def test_in_sample_only_winner_is_rejected(candidate_evidence):
    candidate_evidence["walk_forward_windows"] = 0
    decision = select_strategy_candidate(candidate_evidence)
    assert decision.eligible is False
    assert "walk-forward" in decision.issues[0]


def test_live_drawdown_triggers_automatic_rollback(promoted_record):
    decision = evaluate_strategy_rollback(
        promoted_record,
        live_drawdown_pct=Decimal("-10.5"),
        max_live_drawdown_pct=Decimal("-10"),
    )
    assert decision.demote is True
    assert decision.fallback_strategy_id == "hold_cash"
```

- [ ] **Step 2: Run and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_strategy_selection.py -q
```

Expected: FAIL.

- [ ] **Step 3: Implement selection gates**

Require:

```text
preregistered
focused tests green
no look-ahead violation
at least 3 walk-forward windows
at least 5 tracked paper days
at least 10 closed paper trades
positive benchmark excess return
positive cost-adjusted alpha
drawdown inside the configured floor
capacity >= requested live tranche
fresh risk envelope
```

Return an immutable `StrategySelectionDecision` containing eligibility, issues, evidence refs, and rollback thresholds.

- [ ] **Step 4: Remove the hardcoded preregistration bottleneck**

Replace `PREREGISTERED_TOURNAMENT_SLEEVES` as the sole source with:

```python
def is_preregistered_strategy(
    sleeve_id: str,
    *,
    strategy_registry_path: str | Path,
    evaluation_started_at: str,
) -> bool:
```

Keep the three existing built-ins registered by a migration fixture. Dynamic genomes must be in the append-only registry before their evaluation start.

- [ ] **Step 5: Add automatic rollback**

Demote to `paper_only` and switch the live fallback to `hold_cash` when any condition occurs:

```text
live drawdown breaches configured maximum
broker reconciliation mismatch
promotion evidence expires
strategy parameters do not match the promoted digest
out-of-sample alpha turns negative over the minimum window
```

This is machine risk management, not a human approval point.

- [ ] **Step 6: Verify and commit**

```bash
uv run --with pytest python -m pytest \
  tests/test_strategy_selection.py \
  tests/test_promotion_sync.py \
  tests/test_promotion_policy.py \
  tests/test_live_gate.py -q
git add tradingagents/strategy/selection.py tradingagents/policy/promotion_sync.py tradingagents/policy/live_gate.py tests/test_strategy_selection.py tests/test_promotion_sync.py tests/test_live_gate.py
git commit -m "feat: promote and roll back dynamic strategies"
```

Expected: PASS.

---

### Task 8: Route Worker Intelligence Without Permanent Role Overhead

**Files:**
- Create: `config/agent_workforce.json`
- Create: `tradingagents/orchestration/workforce.py`
- Create: `tests/test_workforce_routing.py`
- Modify: `tradingagents/research/model_routing.py`
- Modify: `tests/test_model_routing.py`

- [ ] **Step 1: Write failing routing tests**

```python
def test_deterministic_integrity_tasks_use_no_llm():
    route = route_work("broker_reconciliation", severity="high")
    assert route.model is None
    assert route.worker_role == "integrity_verifier"


def test_routine_compaction_uses_low_cost_worker():
    route = route_work("packet_compaction", severity="low")
    assert route.model == "gpt-5.6-luna"
    assert route.reasoning_effort == "medium"


def test_hard_incident_gets_frontier_review_only_after_trigger():
    route = route_work(
        "incident_root_cause",
        severity="high",
        prior_attempts=2,
        conflicting_evidence=True,
    )
    assert route.model == "gpt-5.6-sol"
    assert route.reasoning_effort == "high"


def test_repairer_and_verifier_roles_are_separate():
    repair = route_work("incident_repair", severity="high")
    verify = route_work("incident_verification", severity="high")
    assert repair.worker_role != verify.worker_role
```

- [ ] **Step 2: Run and confirm RED**

```bash
uv run --with pytest python -m pytest tests/test_workforce_routing.py -q
```

Expected: FAIL.

- [ ] **Step 3: Implement the event-driven routing table**

```json
{
  "schema_version": 1,
  "routes": {
    "deterministic_integrity": {
      "model": null,
      "reasoning_effort": null,
      "parallel": false
    },
    "routine_compaction": {
      "model": "gpt-5.6-luna",
      "reasoning_effort": "medium",
      "parallel": false
    },
    "research_analysis": {
      "model": "gpt-5.6-terra",
      "reasoning_effort": "high",
      "parallel": true
    },
    "portfolio_decision": {
      "model": "gpt-5.6-terra",
      "reasoning_effort": "high",
      "parallel": false
    },
    "adversarial_incident_review": {
      "model": "gpt-5.6-sol",
      "reasoning_effort": "high",
      "parallel": false
    }
  },
  "frontier_escalation": {
    "minimum_prior_attempts": 2,
    "requires_conflicting_evidence": true
  }
}
```

Rules:

- Use no worker for deterministic checks that can be completed locally.
- Parallelize only independent analyst/source lanes.
- Use one portfolio executive for the final investment decision.
- Use one repair worker and one different verifier for incidents.
- Escalate to Sol only after the configured trigger, not on every hourly run.
- Every worker receives task boundary, allowed files/effects, non-decisions, input packet refs, expected output packet kind, and verification command.

- [ ] **Step 4: Verify and commit**

```bash
uv run --with pytest python -m pytest tests/test_workforce_routing.py tests/test_model_routing.py -q
git add config/agent_workforce.json tradingagents/orchestration/workforce.py tradingagents/research/model_routing.py tests/test_workforce_routing.py tests/test_model_routing.py
git commit -m "feat: route event-driven agent workforce"
```

Expected: PASS.

---

### Task 9: Run Communication And Learning Done Proof

**Files:**
- Create: `tests/integration/test_agent_learning_loop.py`
- Create runtime proof: `results/control_plane/proofs/agent-learning.json`

- [ ] **Step 1: Test the complete learning loop**

The integration test must prove:

```text
analysts create evidence
-> deterministic research packet
-> bull/bear and trader consume compact refs
-> deterministic portfolio packet
-> forecast stored
-> outcome later resolved
-> contextual agent influence changes
-> new strategy genome preregistered
-> walk-forward and paper evidence recorded
-> eligible candidate promoted or ineligible candidate rejected
-> rollback returns to HOLD_CASH when live evidence breaches the envelope
```

- [ ] **Step 2: Add false-green traps**

Reject:

```text
mutated evidence digest
expired packet
pending forecast counted as success
future-dated evidence
candidate registered after evaluation began
in-sample-only performance
same repairer/verifier run
strategy parameters differing from promoted digest
```

- [ ] **Step 3: Run focused proof**

```bash
uv run --with pytest python -m pytest \
  tests/test_work_packets.py \
  tests/test_decision_ledger.py \
  tests/test_graph_packet_handoffs.py \
  tests/test_learning_context.py \
  tests/test_strategy_genome.py \
  tests/test_strategy_evolution.py \
  tests/test_strategy_registry.py \
  tests/test_strategy_selection.py \
  tests/test_workforce_routing.py \
  tests/integration/test_agent_learning_loop.py -q
```

Expected: PASS.

- [ ] **Step 4: Verify token discipline**

The runtime proof must show:

```json
{
  "max_learning_context_chars": 4000,
  "max_claims_per_packet": 5,
  "max_assumptions_per_packet": 5,
  "raw_transcripts_in_handoffs": 0,
  "frontier_model_used_without_trigger": 0,
  "unresolved_forecasts_used_for_influence": 0
}
```

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_agent_learning_loop.py
git commit -m "test: prove packetized agent learning loop"
```

Expected: PASS and clean focused diff.

---

### Evidence-First Increment 1: Agent Ledger Reconciliation And Dependence Bounds

**Status:** Approved continuation after the owner-approval authority boundary
was integrated and reverified on canonical `master` at
`e50ec697f8ee0379261a324563a13ecc9d0792c6`.

**Files:**

- Create: `tradingagents/evals/agent_intelligence_reconciliation.py`
- Modify: `tradingagents/evals/agent_intelligence_ledger.py`
- Modify: `cli/main.py`
- Create or extend: `tests/test_agent_intelligence_reconciliation.py`
- Extend only when required by the public summary contract:
  `tests/test_agent_intelligence_ledger.py`

**Purpose:** Bind every derived count to one captured ledger byte snapshot and
make dependence visible without rewriting raw forecast history. The current
4,944 resolved rows collapse to 2,595 packet-event clusters and 354
conservative market-event clusters. The conservative cluster count is the
provisional effective sample until a separately preregistered estimator exists.

- [x] **Step 1: Add focused RED tests for a one-read snapshot**

The reader must capture the JSONL bytes once and derive the following from
those bytes only:

```text
schema_version = agent_intelligence_reconciliation/v1
ledger_sha256
ledger_byte_length
raw_nonempty_line_count
valid_forecast_count
corrupt_line_count
duplicate_forecast_id_row_count
conflicting_forecast_id_count
resolved_row_count
packet_event_cluster_count
market_event_cluster_count
provisional_effective_sample
summary_freshness
receipt_sha256
```

The packet-event key is the canonical tuple of `source_packet_id`, ticker,
benchmark, and canonical `resolution_window`. The conservative market-event
key is ticker, the UTC creation market date, horizon, and benchmark. Missing or
malformed cluster material is counted as unclusterable and never replaced with
invented identity.

- [x] **Step 2: Prove integrity failures remain visible and non-mutating**

RED fixtures must cover malformed JSON, schema-invalid rows, exact duplicate
IDs, conflicting duplicate IDs, missing source-packet identity, malformed
creation time, and distinct packet events that share one market event. The
ledger bytes and SHA-256 must be identical before and after every reconcile
call. No reconciliation path may call `append_forecasts`, `write_ledger`,
resolution, learning-availability, broker, runtime, schedule, or outbox code.

- [x] **Step 3: Add deterministic dependence fields to derived summaries**

`summarize_agent_scores()` and newly written summaries must expose the same
dependence block so a raw resolved-row count is never presented alone as an
effective sample. This increment does not change earned-influence math,
promotion, mutation, paper, or live behavior; the receipt must label that
row-weighted influence estimator as legacy/unregistered rather than imply that
the cluster bound is already a statistical estimator.

- [x] **Step 4: Add the read-only reconciliation CLI**

`research agent-ledger-reconcile` prints canonical JSON to stdout by default.
An explicit `--receipt-path` may atomically write only the derived receipt and
must reject the ledger path itself, an alias of it, or any partial overwrite.
It never replaces `summary.json` in this increment. Summary freshness states
are exact: missing, malformed, `unverifiable_legacy_summary` when no ledger
fingerprint exists, stale when the fingerprint differs, and current only when
the fingerprint and required counts match.

- [x] **Step 5: Verify the current evidence scale without mutating it**

Tests use synthetic fixtures. A separate read-only check may point the pure
reconciler at the current ignored ledger and must reproduce 6,244 valid rows,
4,944 resolved rows, 2,595 packet-event clusters, and 354 market-event clusters
with the current ledger SHA-256. Do not write a receipt into `results/` during
implementation verification.

- [x] **Step 6: Review and commit**

```bash
TA_LIVE_SUBMIT=0 .venv/bin/python -m pytest -q \
  tests/test_agent_intelligence_reconciliation.py \
  tests/test_agent_intelligence_ledger.py \
  tests/test_resolution_quality.py \
  tests/test_learning_context.py
.venv/bin/ruff check \
  tradingagents/evals/agent_intelligence_reconciliation.py \
  tradingagents/evals/agent_intelligence_ledger.py \
  cli/main.py \
  tests/test_agent_intelligence_reconciliation.py \
  tests/test_agent_intelligence_ledger.py
```

One implementation writer stops uncommitted. A fresh no-edit verifier, a fresh
specification reviewer, and a separate quality/security reviewer must accept
the complete diff before the scoped commit
`feat(evals): reconcile agent ledger dependence`.

**Explicit non-goals for this increment:** trial/mutation/source-span/producer
receipt wiring, supersession, a statistical estimator, influence reweighting,
economic backtests, data downloads, database/index migration, summary
replacement, schedule activation, trial execution, live-control changes, or
broker activity.

**Implementation record (2026-08-24, GREEN, uncommitted for fresh review):**

Worktree `~/.codex/worktrees/tradingagents-agent-ledger-reconciliation-20260824`,
branch `codex/agent-ledger-reconciliation-20260824` at base
`e50ec697f8ee0379261a324563a13ecc9d0792c6`. Changed paths:
`tradingagents/evals/agent_intelligence_reconciliation.py` (new),
`tradingagents/evals/agent_intelligence_ledger.py` (dependence block only),
`cli/main.py` (`research agent-ledger-reconcile` only),
`tests/test_agent_intelligence_reconciliation.py` (new);
`tests/test_agent_intelligence_ledger.py` needed no change.

RED evidence: first run of
`TA_LIVE_SUBMIT=0 .venv/bin/python -m pytest -q tests/test_agent_intelligence_reconciliation.py`
failed collection with
`ModuleNotFoundError: No module named 'tradingagents.evals.agent_intelligence_reconciliation'`.
After the pure module landed but before wiring, 13 passed / 6 failed with exact
assertions: missing receipt fields, wrong counts on the mixed fixture,
`KeyError: 'dependence'` from `summarize_agent_scores`, and
`No such command 'agent-ledger-reconcile'`.

GREEN: 19 reconciliation tests pass; focused set
(`tests/test_agent_intelligence_reconciliation.py`,
`tests/test_agent_intelligence_ledger.py`, `tests/test_resolution_quality.py`,
`tests/test_learning_context.py`) = 146 passed; adjacent
`tests/test_agent_intelligence_brain.py` = 7 passed.
Ruff clean on all five plan paths; `compileall` OK with
`PYTHONPYCACHEPREFIX` outside the repo; `uv lock --check` OK;
`git diff --check` clean.

Pinned semantics: both cluster keys cover resolved rows only; packet-event key
canonicalizes a missing/null `resolution_window` as JSON `null` (exact stored
value, not invented identity) while missing/empty packet/ticker/benchmark
material is unclusterable; market-event key requires a validated UTC
`created_at`, normalized ticker/horizon/benchmark; duplicate rows are counted
only when every row for a forecast id is canonically identical, otherwise the
id counts once as conflicting. Summary freshness expects a
`ledger_fingerprint` block (sha256 + byte length + valid/resolved counts) that
current writers do not emit yet, so live summaries read as
`unverifiable_legacy_summary`; no writer changed in this increment.

Current ignored ledger, read-only via the CLI and pure reconciler (stdout
only, no receipt or summary written under `results/`):
sha256 `10b3c228c1de2ecc91242083df90aac7a47f7cdd870f7e75eca657bd0d28c223`,
11,563,361 bytes, 6,244 valid, 4,944 resolved, 2,595 packet-event clusters,
354 market-event clusters, provisional effective sample 354, zero corrupt,
duplicate, conflicting, and unclusterable rows. Remaining risks: freshness
`current` is unreachable until a future writer emits fingerprints; duplicate/
conflict accounting for groups mixing identical and differing rows resolves to
"conflicting" by design.

**Review-fix round (2026-08-24, GREEN, still uncommitted for fresh review):**

RED evidence: the extended suite first failed collection with
`ImportError: cannot import name 'SummaryReadError'`; probes against the then-
current code confirmed each finding: a raw U+2028 inside one legal JSON string
made `str.splitlines()` report 5 nonempty / 1 valid / 4 corrupt instead of
2/2/0; `resolved: 1` parsed as a valid resolved row; a naive timestamp
clustered; a string `resolution_window` clustered as `"x"`; and the receipt
lacked `influence_weighting_status` plus all three null-window counters.

Fixed review findings: byte-level LF splitting with single trailing-CR
tolerance and strict per-record UTF-8 (decode failure = corrupt, no lossy
replacement; U+2028/U+2029/U+0085 never split rows); cached validator derived
from AgentForecast type hints (JSON object required, required/allowed fields,
strict str/bool/optional/list/dict shapes, list elements, dict keys,
bool-rejects-int, undeclared fields rejected) with schema-invalid rows corrupt;
packet/market keys require string key material, Mapping-or-null windows only,
offset-aware timestamps only, and `resolved is True`; receipt and dependence
blocks gained `packet_event_null_window_resolved_row_count`,
`packet_event_null_window_cluster_count`, and
`packet_event_non_null_window_cluster_count`, where raw parsing counts only an
explicit JSON null as a null-window row and a missing field stays distinct;
`influence_weighting_status` is now SHA-covered in every receipt and printed by
the CLI; invalid-UTF-8/invalid-JSON summaries are malformed, a summary
vanishing between exists/read is missing, other read errors raise
`SummaryReadError`, and CLI wording separates read failures ("could not read
ledger", accurate summary error text) from write failures ("could not write
receipt"); receipt writes fsync the parent directory after `os.replace` using
the repository's `getattr(os, "O_DIRECTORY"/"O_NOFOLLOW", 0)` style, raising
rather than reporting a failed write as successful.

P2 justification (function-local import kept): the deferred
`AgentForecast` import inside the module is retained as a stable cycle break —
it executes only at first reconciliation call, after both modules have fully
initialized, so import order cannot cycle; this bounded increment does not
duplicate the dataclass schema as a sixth module would.

Verification after fixes (`TA_LIVE_SUBMIT=0`, canonical venv):
`tests/test_agent_intelligence_reconciliation.py` = 45 passed (was 19),
focused four-file set = 172 passed, brain suite = 7 passed; Ruff clean on all
changed paths; `compileall` OK with `PYTHONPYCACHEPREFIX` outside the repo;
`uv lock --check` OK; `git diff --check` clean. Canonical ignored ledger re-
checked read-only with the explicit canonical summary path and no receipt
output: unchanged sha256
`10b3c228c1de2ecc91242083df90aac7a47f7cdd870f7e75eca657bd0d28c223`, 6,244
valid, 4,944 resolved, 2,595 total packet-event clusters preserved, 354
market-event clusters, provisional sample 354, and the new disclosure reads
132 explicit-null resolved rows across 66 null-window clusters with 2,529
non-null clusters; ledger and summary hashes unchanged. Remaining risks:
freshness `current` still awaits a fingerprint-emitting writer; object-space
dependence blocks cannot distinguish an absent window field from explicit
null after construction (raw receipts can), so the two surfaces agree exactly
only for fully serialized rows like this ledger's.

**Post-fix correction round (2026-08-24, GREEN, still uncommitted):**

Orchestrator findings corrected in tests and semantics only. (1) The Unicode
line-boundary fixture now serializes with `ensure_ascii=False` and asserts the
raw UTF-8 separator bytes U+2028/U+2029/U+0085 are present before reconciling.
(2) The invalid-UTF-8 case now corrupts a complete otherwise-valid row by
injecting one invalid byte into its claim, with a clean twin proving strict
decode is the only failure reason (RED first: the replace anchor missed under
default separators and was fixed inside the test). (3) The summary-vanishing
race test creates summary.json first and counts one exercised read before
mapping `FileNotFoundError` to `missing`. (4) Raw receipt semantics tightened:
for payload mappings an omitted `resolution_window` field is missing cluster
material and packet-event unclusterable while an explicitly present JSON null
remains the canonical legacy null sentinel; receipt packet/market clusters are
derived from validated raw mappings so field presence survives; object-space
dependence blocks still count `AgentForecast.resolution_window=None` as that
sentinel because construction loses presence, documented on the module,
`packet_event_key`, `dependence_block`, and the receipt builder.

RED evidence for the semantic change: the omitted-window key assertion and the
updated explicit-null-versus-missing assertions failed against the prior code
(`packet_event_key(...) is None` returned a clustered key; unclusterable count
0 instead of 1), then went GREEN after the tightening. Verification after this
round: reconciliation file 45 passed, focused four-file set 172 passed, brain
suite 7 passed; Ruff clean; `compileall` OK outside repo; `uv lock --check`
OK; `git diff --check` clean; canonical read-only check unchanged — sha256
`10b3c228c1de2ecc91242083df90aac7a47f7cdd870f7e75eca657bd0d28c223`,
6,244 valid, 4,944 resolved, 2,595 packet-event clusters, 354 market-event
clusters, provisional sample 354, 132 explicit-null rows across 66 null-window
clusters, 2,529 non-null clusters, zero corrupt/duplicate/conflicting/
unclusterable rows, ledger and summary hashes unchanged, no output written.

**Spec-review correction round (2026-08-24, GREEN, still uncommitted):**

Four findings fixed. (1) Duplicate/conflict accounting now groups validated
raw payload mappings directly instead of reconstructed `as_dict()` output, so
an omitted `resolution_window` and an explicit JSON null with otherwise
identical content are conflicting rows (0 duplicates / 1 conflict), not exact
duplicates; unclusterable and null-window accounting retained. RED: the
regression read duplicate=1 against expected 0. (2) A summary path physically
aliasing the ledger (direct path, symlink, or hardlink) no longer triggers a
second read: physical equivalence is detected stat-only via
`os.path.samefile`/realpath before any summary read, and the captured byte
snapshot is reused for summary parsing (a JSONL ledger deterministically
classifies as a malformed summary). Normal summary behavior unchanged;
`SummaryReadError` fail-closed semantics preserved. RED with inode-based
read instrumentation (`os.path.samefile`, catching name-based blind spots on
symlink/hardlink aliases): ledger read 2 times instead of 1 for all three
alias kinds. (3) A present summary containing JSON literal null is malformed,
not missing: decoded payloads are distinguished from the absent-file None
sentinel in `_decoded_summary_payload`. RED: state was `missing`. (4) CLI
wording locked by tests: missing-ledger asserts "could not read ledger" and
not the summary wording; a new faked summary PermissionError asserts the
distinct "could not read summary" wording without the ledger wording (this
pair passed immediately as a regression lock; the underlying split landed in
the earlier round).

Adjacent reassessment found no further drift: field presence is now honored
in every raw-space surface (clustering, null counters, duplicate grouping);
object-space dependence blocks keep their documented sentinel behavior.

Post-fix verification (`TA_LIVE_SUBMIT=0`, canonical venv):
`tests/test_agent_intelligence_reconciliation.py` = 51 passed,
focused four-file set = 178 passed, brain suite = 7 passed; Ruff clean on all
five changed paths; `compileall` OK with `PYTHONPYCACHEPREFIX` outside the
repo; `uv lock --check` OK; `git diff --check` clean; canonical ignored
ledger re-checked read-only via the CLI with the canonical summary path and
no output write: sha256
`10b3c228c1de2ecc91242083df90aac7a47f7cdd870f7e75eca657bd0d28c223`,
6,244 valid, 4,944 resolved, 2,595 packet-event clusters, 354 market-event
clusters, provisional sample 354, 132 explicit-null rows across 66
null-window clusters, 2,529 non-null clusters, zero corrupt/duplicate/
conflicting/unclusterable rows, `unverifiable_legacy_summary`, ledger and
summary hashes unchanged. Remaining risks unchanged: freshness `current`
awaits a fingerprint-emitting writer; object-space blocks cannot recover
field presence after construction (raw receipts can).

**Strict-JSON and summary-stat correction round (2026-08-24, GREEN, still
uncommitted):**

P1 strict JSON: one shared strict decoder (`_STRICT_JSON_DECODER` with
`object_pairs_hook` rejecting duplicate keys at any nesting level and
`parse_constant` rejecting NaN/Infinity/-Infinity) now parses ledger records
and summaries; non-strict ledger records count corrupt and non-strict
summaries classify malformed. `canonical_json_text` emits standards-compliant
JSON via `allow_nan=False` and rejects non-finite values instead of
serializing them (packet-key window canonicalization already treats that as
unclusterable). Raw-byte fixtures were hand-spliced, never produced by
json.dumps: a valid forecast with `"session_count":NaN` inside its
resolution_window; nested duplicate `entry_date` keys inside
resolution_window plus a top-level duplicate `ticker`; a fingerprint-bearing
summary containing NaN; and a summary with two `ledger_fingerprint` keys.
RED evidence: 7 failed / 51 passed — the NaN row was accepted as valid, both
duplicate-key rows were accepted as valid, canonical_json_text serialized
non-finite values without error, the NaN summary classified `current`
(silent acceptance despite a matching fingerprint), the duplicate-key summary
classified from last-key-wins parsing, and the alias-stat failure did not
raise.

Adjacent confirmed read defect: the summary read path no longer probes
existence at all. Physical alias detection is stat-only via
`_paths_equivalent(..., strict=True)`, which re-raises every non-
FileNotFoundError OSError so metadata/alias failures surface as
`SummaryReadError` ("could not read summary") instead of being silently
downgraded to a realpath guess or mislabeled "could not read ledger";
`read_bytes` FileNotFoundError maps to missing (vanish races preserved), all
other read OSErrors raise SummaryReadError, direct/symlink/hardlink alias
reuse keeps the one-captured-read contract, and JSON literal null stays
malformed. RED: faked `os.path.samefile` PermissionError did not raise and
the CLI exited 0; GREEN raises SummaryReadError and the CLI prints the
summary wording only. Regression tests use narrow monkeypatches of the exact
filesystem calls, no chmod.

Post-fix verification (`TA_LIVE_SUBMIT=0`, canonical venv): reconciliation
file = 58 passed; five-suite set = 192 passed (58+23+21+83+7); Ruff clean on
all changed Python/test paths; `compileall` OK with `PYTHONPYCACHEPREFIX`
outside the repo; `uv lock --check` OK; `git diff --check` clean; canonical
ignored ledger re-checked read-only via the CLI with the canonical summary
path and no receipt write: sha256
`10b3c228c1de2ecc91242083df90aac7a47f7cdd870f7e75eca657bd0d28c223`,
6,244 valid, 4,944 resolved, 2,595 packet-event clusters, 354 market-event
clusters, provisional sample 354, 132 explicit-null rows across 66
null-window clusters, 2,529 non-null clusters, zero corrupt/duplicate/
conflicting/unclusterable rows, `unverifiable_legacy_summary`, ledger and
summary hashes unchanged. Remaining risks unchanged: freshness `current`
awaits a fingerprint-emitting writer; object-space blocks cannot recover
field presence after construction (raw receipts can).

**Existence-probe removal correction (2026-08-24, GREEN, still uncommitted):**

Closed the docstring-versus-implementation mismatch: `_paths_equivalent` still
called `Path.exists` even though the record and `reconcile_ledger_file`
claimed the summary path never probes existence. RED: a tripwire
monkeypatching `pathlib.Path.exists` to raise for exactly the reconciled
ledger/summary paths failed with "unexpected existence probe on
.../summary.json" while reconciling a normal fingerprint-matching summary.
GREEN: the helper now calls `os.path.samefile` directly — True means inode
alias; FileNotFoundError means no inode alias and permits the realpath
fallback; any other samefile or realpath OSError re-raises only in strict
read mode (wrapped by the caller as `SummaryReadError`) and stays
non-raising for optional receipt-path protection; the realpath fallback sits
inside the guarded error handling so strict mode cannot silently swallow a
realpath OSError. Preserved: direct, symlink, and hardlink one-captured-read
aliasing; vanish-as-missing; summary PermissionError wording; all strict JSON
semantics. Verification: `tests/test_agent_intelligence_reconciliation.py`
= 59 passed, five-suite set = 193 passed, Ruff clean on changed paths,
`compileall` OK with external `PYTHONPYCACHEPREFIX`, `uv lock --check` OK,
`git diff --check` clean, and the canonical read-only CLI check reproduced
sha256 `10b3c228c1de2ecc91242083df90aac7a47f7cdd870f7e75eca657bd0d28c223`,
6,244 valid / 4,944 resolved / 2,595 packet-event clusters / 354 market-event
clusters with 132 explicit-null rows across 66 null-window clusters and
2,529 non-null clusters, ledger and summary hashes unchanged, no output
written.

**Blank-record classification correction (2026-08-24, GREEN, still
uncommitted):**

P1 raw-record gap: `build_reconciliation_receipt` used broad
`record.strip()` to detect blank records, and `bytes.strip` treats vertical
tab 0x0b and form feed 0x0c as whitespace, so such records could vanish from
both `raw_nonempty_line_count` and `corrupt_line_count`. RED evidence
history, stated exactly: the original RED fixture mixed one bare 0x0b record
with a JSON record carrying a trailing 0x0c, so it isolated only the
vertical-tab omission — the trailing-FF JSON record was already counted raw-
nonempty/corrupt because its leading byte is not whitespace under broad
strip. A post-fix tightening now makes both illegal bytes independent bare
records (one b"\x0b" line, one b"\x0c" line, plus one valid forecast line,
asserting raw_nonempty 3 / valid 1 / corrupt 2), independently locking form
feed against any future regression of the predicate; the companion space/tab
plus single-trailing-CR padding fixture is preserved unchanged. GREEN: the
blank predicate remains `record.strip(b" \t")`, accepting only exact
space/tab padding after the existing single trailing-CR strip; LF byte
splitting, strict decoder semantics, and every accepted count are unchanged.
P2: the module-level freshness documentation no longer references an
existence check; it now states the summary path is never probed for
existence and that a file vanishing before or directly during its read is
`missing`. Verification: reconciliation file = 61 passed, five-suite set =
195 passed (61+23+21+83+7), Ruff clean on changed paths, `compileall` OK
with external `PYTHONPYCACHEPREFIX`, `uv lock --check` OK, `git diff --check`
clean; canonical read-only CLI check reproduced sha256
`10b3c228c1de2ecc91242083df90aac7a47f7cdd870f7e75eca657bd0d28c223`,
6,244 raw nonempty/valid, 4,944 resolved, 2,595 packet-event clusters, 354
market-event clusters, provisional sample 354, 132 explicit-null rows across
66 null-window clusters, 2,529 non-null clusters, zero corrupt/duplicate/
conflicting/unclusterable rows, `unverifiable_legacy_summary`, ledger and
summary hashes unchanged, no receipt written. Test-evidence tightening
round (no production change): strengthened bare-record fixture passes
against the unchanged predicate; reconciliation file = 61 passed, five-suite
set = 195 passed, Ruff/compileall/uv-lock/diff-check all clean as above.

**Ox quality/security round (2026-08-24, GREEN, still uncommitted):**

P1 test hermeticity (custody correction, not production RED): the CLI JSON
test invoked `agent-ledger-reconcile` without `--summary-path` and asserted
`missing`, which only holds when the process CWD lacks the ignored
`results/agent_intelligence/summary.json`; the orchestrator independently
confirmed that canonical ignored summary exists and reads as
`unverifiable_legacy_summary`, so the ambient scenario is factual without
inventing a production failure (the sandbox denied a cd-based capture; no
external access was requested again). Fix: every reconciliation
`runner.invoke` case now passes an explicit tmp summary path unless it
intentionally tests a concrete summary file; the renamed
`test_cli_prints_canonical_json_and_hermetic_summary_state`, both
atomic-write invokes, the write-failure wording case, and the missing-ledger
case are hermetic. CLI production defaults unchanged.

P2 fingerprint types: numeric fingerprint fields now require exactly `int`
(`type(value) is int`) before equality — JSON `true` and float literals such
as `1.0` never classify current for ledger_byte_length,
valid_forecast_count, or resolved_row_count; sha stays nonempty-str;
malformed shapes remain unverifiable legacy; typed-but-wrong stays stale.
RED: value-equal `true`/`1.0` fingerprints classified current under Python
equality (4 parametrized failures); an initial byte_length=true case was
discarded because its base value 77 made it stale for the wrong reason.

P2 schema evolution: `_type_checker` now validates dict values alongside
keys (`dict[K, V]`), raises TypeError during construction for bare
list/dict/tuple/set/frozenset, variadic/fixed tuples, legacy typing.Dict/
typing.List, and any unrecognized annotation instead of silently accepting.
RED: 10 loud-rejection cases plus dict-value rejection failed under the old
accept-all fallback; one initial parametrization wrongly listed `object` as
unsupported — it is deliberately Any-equivalent and moved to an accepted-
hints test. AgentForecast acceptance and all counts unchanged.

P2 receipt write: successful staged/final receipts assert mode 0600
(mkstemp default, locked as regression). fdopen-failure cleanup hardened:
the mkstemp descriptor flag pattern guarantees close when `os.fdopen` fails,
temp residue is removed, and the original exception propagates; atomic
replace plus parent fsync unchanged. RED: capturing the real mkstemp fd and
faking `os.fdopen` to raise EBADF left the descriptor open (`os.fstat` did
not raise) before the fix; post-fix fstat raises EBADF, no temp remains, and
the test closes any deliberately leaked RED fd in its own finally.

Verification: reconciliation file = 77 passed, five-suite set = 211 passed
(77+23+21+83+7); Ruff clean on changed paths (two deliberate
`typing.Dict/List` fixtures carry noqa UP006); compileall OK with external
`PYTHONPYCACHEPREFIX`; `uv lock --check` OK; `git diff --check` clean;
canonical read-only CLI check reproduced sha256
`10b3c228c1de2ecc91242083df90aac7a47f7cdd870f7e75eca657bd0d28c223`,
6,244 valid / 4,944 resolved / 2,595 / 354 clusters, provisional 354,
132/66/2529 disclosure, zero corrupt/duplicate/conflicting/unclusterable,
`unverifiable_legacy_summary`, ledger and summary hashes unchanged, no
receipt written.

**Orchestrator hardening regression round (2026-08-24, GREEN, still
uncommitted):**

(1) Fingerprint exact types: added a direct
`evaluate_summary_freshness` regression for `ledger_byte_length` with
expected value 1 against recorded `True` and `1.0` (plus the exact-match
current control). Truthful evidence status: this case passed immediately —
the previous round's exact-int guard already covers byte_length, so it locks
existing behavior rather than new RED. The genuinely RED checker case was
`_type_checker(int)` accepting `bool` (`int_check(True)` returned True under
`isinstance`); its `1.0` assertion was already GREEN and remains a regression
lock. GREEN: `_type_checker(int)` now uses exact int semantics (rejects bool
and floats) while AgentForecast's declared hints contain no int fields, so no
current counts changed.

(2) fdopen original-exception custody: new regression fakes `os.fdopen` to
close the captured real descriptor first and then raise
`OSError(EIO, "storage media revoked")`. RED: the cleanup `os.close`
re-raised `[Errno 9] Bad file descriptor`, masking the original message.
GREEN: only the cleanup close is wrapped in `contextlib.suppress(OSError)`,
so the original fdopen error propagates while temp residue is still removed;
the earlier leak test (fd stays closed on plain fdopen failure) and all
strict-JSON/alias/freshness semantics are unchanged.

Verification: reconciliation file = 79 passed, five-suite set = 213 passed
(79+23+21+83+7); Ruff clean on changed paths; `compileall` OK with external
`PYTHONPYCACHEPREFIX`; `uv lock --check` OK; `git diff --check` clean;
canonical read-only CLI check reproduced sha256
`10b3c228c1de2ecc91242083df90aac7a47f7cdd870f7e75eca657bd0d28c223`,
6,244 valid / 4,944 resolved / 2,595 / 354 clusters, provisional 354,
132/66/2529 disclosure, zero corrupt/duplicate/conflicting/unclusterable,
`unverifiable_legacy_summary`, ledger and summary hashes unchanged, no
receipt written.

**Final Ox P2 review-fix round (2026-08-24, GREEN, still uncommitted):**

(1) Receipt-path alias protection fails closed: `write_reconciliation_receipt`
now evaluates protected-path equivalence with `strict=True` and converts any
non-FileNotFoundError metadata OSError (samefile/realpath resolution) into
`ReconciliationPathError` ("receipt path protection could not be verified
against ...") before any write, so an unstatable alias can never slip through
the lenient realpath guess and clobber a protected file. Normal missing-path
behavior is unchanged (FileNotFoundError still means not-aliased and the
write proceeds). RED: faking `os.path.samefile` to raise PermissionError for
the receipt target previously wrote the receipt silently (`DID NOT RAISE`);
post-fix it rejects with no ledger change, no target file, and no temp
residue.

(2) `cli/main.py` now imports and reuses `DEFAULT_SUMMARY_PATH` from the
ledger module instead of duplicating the
`Path("results/agent_intelligence/summary.json")` literal in seven option
defaults (identical value; pure de-duplication lock, no behavioral RED).

(3) The manual `Path.read_bytes` patch/try-finally restore in the one-read
test was converted to pytest `monkeypatch.setattr` auto-restoration
(test-mechanics refactor, semantics identical).

Verification: reconciliation file = 80 passed; five-suite set = 214 passed
(80+23+21+83+7); focused hardening selectors (new fail-closed case,
unsafe-receipt-path CLI parametrization, ledger suite) = 29 passed; Ruff
clean on all changed Python/test paths; `compileall` OK with external
`PYTHONPYCACHEPREFIX`; `uv lock --check` OK; `git diff --check` clean;
canonical read-only CLI check with explicit canonical summary path and no
receipt output reproduced sha256
`10b3c228c1de2ecc91242083df90aac7a47f7cdd870f7e75eca657bd0d28c223`,
6,244 valid / 4,944 resolved / 2,595 / 354 clusters, provisional 354,
132/66/2529 disclosure, zero corrupt/duplicate/conflicting/unclusterable,
`unverifiable_legacy_summary`, ledger and summary hashes unchanged.

**Terra alias-classification correction (2026-08-24, GREEN, still
uncommitted):**

P2: when a summary path physically aliased the ledger, the captured ledger
bytes were re-parsed as summary JSON. A multi-record JSONL ledger failed
strict parsing and happened to classify malformed, but a valid single-record
ledger parsed as one complete JSON object with no fingerprint and wrongly
classified `unverifiable_legacy_summary`. RED: new direct/symlink/hardlink
regressions using a valid single-record ledger physically aliased as the
summary (each instrumented to exactly one ledger read) failed all three ways
with `unverifiable_legacy_summary` instead of `malformed`. GREEN: the alias
branch now returns a private typed sentinel `_MalformedSummary` (slots class,
module-level instance) instead of parsing ledger bytes as a summary;
`evaluate_summary_freshness` classifies it malformed via the existing
non-Mapping branch. The one-captured-read guarantee, normal non-alias summary
parsing (including JSON literal null -> malformed), vanish-as-missing,
SummaryReadError wording, and strict-JSON semantics are unchanged.
Verification: reconciliation file = 83 passed; five-suite set = 217 passed
(83+23+21+83+7); focused alias selectors = 11 passed; Ruff clean on changed
Python/tests; `compileall` OK with external `PYTHONPYCACHEPREFIX`;
`uv lock --check` OK; `git diff --check` clean; canonical read-only CLI check
with explicit canonical paths and no receipt output reproduced sha256
`10b3c228c1de2ecc91242083df90aac7a47f7cdd870f7e75eca657bd0d28c223`,
6,244 valid / 4,944 resolved / 2,595 / 354 clusters, provisional 354,
132/66/2529 disclosure, zero anomalies, `unverifiable_legacy_summary`,
ledger and summary hashes unchanged.

**Final acceptance (2026-08-24):** fresh no-edit verification passed 217
tests across the five focused suites plus 41 strict hardening selectors;
Ruff, external-cache `compileall`, `uv lock --check`, and diff checks were
clean. The final Terra specification re-review and Ox Alpha/max
quality-security re-review both returned `ACCEPT` with no P0/P1/P2 findings.
Canonical ledger and summary hashes, the frozen live-control hash, and all ten
paused TradingAgents automation states remained unchanged. Scoped commit:
`feat(evals): reconcile agent ledger dependence`.

**Post-integration correction (2026-08-24, focused fix, uncommitted):**

After the scoped commit `49f4490 feat(evals): reconcile agent ledger
dependence`, the full suite ran RED `1 failed, 4389 passed, 1 skipped,
75 subtests`:
`tests/test_authority_role_alignment.py::test_production_raw_http_mutation_inventory_has_no_unclassified_transport`
reported the new 56-line `research agent-ledger-reconcile` command shifted
the `_overnight_ticker_process_main` raw-http-put occurrences in
`cli/main.py` from lines 5342/5354 to 5398/5410. Correction: updated only
the two exact classification tuples in
`tests/test_authority_role_alignment.py`
(`("cli/main.py", 5342, "_overnight_ticker_process_main", "raw-http-put") ->
5398`, `(..., 5354, ...) -> 5410`), preserving both classification names
(`non-trading-local-process-result-queue`,
`non-trading-local-process-error-queue`) and all production source behavior.
Focused GREEN: the previously failing test passes and
`tests/test_authority_role_alignment.py` is 53 passed; the 217-test ledger
five-suite gate stays green; Ruff clean on the changed test path;
external-cache compileall OK; `uv lock --check` OK; `git diff --check`
clean. Final full-suite rerun GREEN: 4,390 passed, 1 skipped, 11 warnings,
and 75 subtests passed in 520.90 seconds. The skip is the existing
credential-gated DeepSeek live-API case; no runtime, broker, schedule,
automation, or production command was invoked.
