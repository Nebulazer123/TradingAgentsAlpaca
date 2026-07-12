import json

from app.services.report_agent import ReportAgent, ReportManager, ReportOutline, ReportSection
from app.services.report_quality import MIRROR_FISH_REQUIRED_SECTIONS


class FakeLLM:
    def chat_json(self, *args, **kwargs):
        raise AssertionError("fixed Step 4 outline should not call chat_json")


class CapturingLLM:
    def __init__(self):
        self.messages = None
        self.first_messages = None

    def chat(self, messages, **kwargs):
        if self.first_messages is None:
            self.first_messages = messages
        self.messages = messages
        return (
            "Final Answer:\n"
            "This English-only section paraphrases all source evidence and includes "
            "uncertainty plus real-market validation tasks."
        )


class RepairLLM:
    def chat(self, messages, **kwargs):
        return (
            "Final Answer:\n"
            "Simulated Stage 3 evidence indicates broker and trader behavior must be treated cautiously. "
            "Zep graph evidence and local telemetry support a higher-confidence read that broker rollout, "
            "margin constraints, options mechanics, institutional liquidity, media narratives, and macro "
            "conditions interact rather than moving independently. Confidence is moderate because this is "
            "simulation evidence, not live market validation. TradingAgents should validate fresh broker API "
            "risk parameters, buying-power rejections, premarket liquidity, option spreads, gamma exposure, "
            "rates, Treasury auction context, oil/geopolitical stress, and real flow confirmation before "
            "treating the thesis as useful."
        )


class ExplodingRepairLLM:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        raise AssertionError("repair LLM should not be called for already-valid drafts")


class FakeZepTools:
    report_cache = None
    report_mode = "standard"

    def get_simulation_context(self, **kwargs):
        assert kwargs["safe_mode"] is True
        return {
            "related_facts": ["Zep graph.search evidence sample"],
            "graph_statistics": {
                "graph_id": kwargs["graph_id"],
                "total_nodes": None,
                "total_edges": None,
                "entity_types": {},
                "relation_types": {},
                "graph_wide_fetch_deferred": True,
            },
            "entities": [],
            "total_entities": 0,
        }


def test_safe_step4_uses_fixed_required_outline(monkeypatch):
    agent = ReportAgent(
        graph_id="mirofish_4a9df9ae8b184878",
        simulation_id="sim_974459649906",
        simulation_requirement="Mirror Fish Step 4",
        llm_client=FakeLLM(),
        zep_tools=FakeZepTools(),
        report_mode="zep_throttle_cached",
        outline_mode="mirror_fish_full",
        zep_safe_mode=True,
    )
    monkeypatch.setattr(agent, "_merge_local_context", lambda context: context)

    outline = agent.plan_outline()

    assert [section.title for section in outline.sections] == MIRROR_FISH_REQUIRED_SECTIONS
    assert "Zep graph.search is canonical" in outline.summary


def test_full_report_assembly_excludes_section_evidence_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))

    report_id = "report_clean_assembly"
    report_dir = tmp_path / report_id
    report_dir.mkdir()
    (report_dir / "section_01.md").write_text("## Executive summary\n\nClean prose.\n", encoding="utf-8")
    (report_dir / "section_01_evidence.md").write_text(
        "# Section 01 Evidence\n\n- Provenance labels: unavailable_rate_limited\n",
        encoding="utf-8",
    )
    (report_dir / "section_02.md").write_text("## Scenario probability map\n\nMore clean prose.\n", encoding="utf-8")

    outline = ReportOutline(
        title="Clean Report",
        summary="Reader-facing report should not inline evidence packets.",
        sections=[
            ReportSection(title="Executive summary"),
            ReportSection(title="Scenario probability map"),
        ],
    )

    generated_sections = ReportManager.get_generated_sections(report_id)
    assembled = ReportManager.assemble_full_report(report_id, outline)

    assert [section["filename"] for section in generated_sections] == ["section_01.md", "section_02.md"]
    assert "Clean prose." in assembled
    assert "More clean prose." in assembled
    assert "Section 01 Evidence" not in assembled
    assert "unavailable_rate_limited" not in assembled


def test_get_report_prefers_canonical_full_report_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))

    report_id = "report_canonical_markdown"
    report_dir = tmp_path / report_id
    report_dir.mkdir()
    (report_dir / "meta.json").write_text(
        json.dumps(
            {
                "report_id": report_id,
                "simulation_id": "sim_test",
                "graph_id": "graph_test",
                "simulation_requirement": "requirement",
                "status": "completed",
                "outline": None,
                "markdown_content": "STALE\n\n**Section 01 Evidence**\n\nunavailable_rate_limited",
                "created_at": "",
                "completed_at": "",
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    (report_dir / "full_report.md").write_text("CLEAN canonical report", encoding="utf-8")

    report = ReportManager.get_report(report_id)

    assert report is not None
    assert report.markdown_content == "CLEAN canonical report"
    assert "unavailable_rate_limited" not in report.markdown_content


def test_safe_step4_prompt_requires_translation_of_non_english_evidence():
    llm = CapturingLLM()
    agent = ReportAgent(
        graph_id="mirofish_4a9df9ae8b184878",
        simulation_id="sim_974459649906",
        simulation_requirement="Mirror Fish Step 4",
        llm_client=llm,
        zep_tools=FakeZepTools(),
        report_mode="zep_throttle_cached",
        outline_mode="mirror_fish_full",
        zep_safe_mode=True,
    )
    outline = ReportOutline(
        title="Mirror Fish Stage 4 Zep-Backed TradingAgents Analysis",
        summary="safe report",
        sections=[ReportSection(title="AI-bot and prompt-bot failure modes")],
    )

    content = agent._generate_section_react(
        section=outline.sections[0],
        outline=outline,
        previous_sections=[],
        section_index=7,
    )

    assert "English-only section" in content
    system_prompt = llm.first_messages[0]["content"]
    assert "translate or paraphrase" in system_prompt
    assert "do not quote non-English phrases verbatim" in system_prompt


def test_preserved_report_context_includes_repair_evidence(tmp_path):
    report_dir = tmp_path / "report_previous"
    report_dir.mkdir()
    (report_dir / "machine_readable_summary.json").write_text(
        json.dumps(
            {
                "simulation_metadata": {
                    "report_id": "report_previous",
                    "total_rounds": 30,
                    "unique_active_agents": 657,
                    "actions_by_platform": {"reddit": 1089, "twitter": 764},
                    "forecast_ballots": {"total_detected": 144},
                },
                "report_artifacts": {
                    "section_count": 20,
                    "evidence_json_count": 20,
                    "evidence_md_count": 20,
                    "reader_forbidden_pattern_counts": {"Rate limit exceeded": 0},
                },
                "zep_provenance": {
                    "supplemental_graph_wide_panorama": {
                        "status": "completed",
                        "truly_graph_wide": True,
                        "node_count": 973,
                        "edge_count": 2678,
                        "active_fact_count": 1389,
                        "historical_fact_count": 1289,
                        "errors": [],
                    },
                    "live_step5_smoke_quality": {
                        "status": "completed",
                        "platform": "reddit",
                        "live_interviews_available": True,
                        "interview_target_count": 3,
                        "quality_scan": {"cjk": False, "raw_error": False},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    smoke_dir = report_dir / "step5_live_smoke_quality"
    smoke_dir.mkdir()
    (smoke_dir / "live_step5_smoke_summary.json").write_text(
        json.dumps(
            {
                "interview_attempt": {
                    "result": {
                        "result": {
                            "results": {
                                "0": {
                                    "response": "Execution realism and broker margin validation matter before any thesis is used."
                                }
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    agent = ReportAgent(
        graph_id="mirofish_4a9df9ae8b184878",
        simulation_id="sim_974459649906",
        simulation_requirement="Mirror Fish Step 4",
        llm_client=FakeLLM(),
        zep_tools=FakeZepTools(),
        report_mode="zep_throttle_cached",
        outline_mode="mirror_fish_full",
        zep_safe_mode=True,
        old_report_preserved_path=str(report_dir),
    )

    facts = agent._build_preserved_report_context_facts()

    joined = "\n".join(facts)
    assert "Supplemental Zep graph-wide panorama evidence" in joined
    assert "Repaired Step 5 live-quality smoke" in joined
    assert "Execution realism and broker margin validation" in joined


def test_step4_no_prefix_draft_uses_repair_pass():
    agent = ReportAgent(
        graph_id="mirofish_4a9df9ae8b184878",
        simulation_id="sim_974459649906",
        simulation_requirement="Mirror Fish Step 4",
        llm_client=RepairLLM(),
        zep_tools=FakeZepTools(),
        report_mode="zep_throttle_cached",
        outline_mode="mirror_fish_full",
        zep_safe_mode=True,
    )
    section = ReportSection(title="Media outlet and influencer narrative map")

    repaired = agent._repair_step4_final_answer(
        section=section,
        draft="Too short.",
        messages=[{"role": "user", "content": "context"}],
        tool_calls_count=3,
    )

    assert "Confidence is moderate" in repaired
    assert "TradingAgents should validate" in repaired
    assert "Too short" not in repaired


def test_step4_repair_skips_already_valid_draft():
    llm = ExplodingRepairLLM()
    agent = ReportAgent(
        graph_id="mirofish_4a9df9ae8b184878",
        simulation_id="sim_974459649906",
        simulation_requirement="Mirror Fish Step 4",
        llm_client=llm,
        zep_tools=FakeZepTools(),
        report_mode="zep_throttle_cached",
        outline_mode="mirror_fish_full",
        zep_safe_mode=True,
    )
    section = ReportSection(title="AI-bot and prompt-bot failure modes")
    draft = (
        "Simulated Stage 3 evidence indicates that AI-bot and prompt-bot behavior should be "
        "treated as advisory market-psychology evidence, not as a direct order signal. "
        "Zep graph evidence and local telemetry support the same broad read: copycat scripts, "
        "broker API retry queues, margin checks, account-state mismatch, and 0DTE options "
        "mechanics can combine into false-positive crowding. Confidence is moderate because "
        "this is simulated evidence and requires validation against real broker logs, fresh "
        "quotes, market depth, options spreads, gamma exposure, macro/rates context, Treasury "
        "auction reactions, oil/geopolitical stress, and institutional liquidity response. "
        "TradingAgents should not act directly on this simulated signal. It should route the "
        "finding into risk gates, broker-confusion warnings, false-signal filters, and real "
        "market data validation tasks before any strategy module treats the thesis as useful. "
        "Model bias may overstate retail impact if the seed overweights social chatter, so the "
        "final interpretation must separate narrative velocity from confirmed flow."
    )

    repaired = agent._repair_step4_final_answer(
        section=section,
        draft=draft,
        messages=[{"role": "user", "content": "context"}],
        tool_calls_count=3,
    )

    assert repaired == draft
    assert llm.calls == 0
