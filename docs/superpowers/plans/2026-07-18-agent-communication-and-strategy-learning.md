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
