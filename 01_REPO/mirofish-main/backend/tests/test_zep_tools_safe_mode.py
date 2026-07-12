from app.services.zep_tools import EdgeInfo, NodeInfo, SearchResult, ZepToolsService


def test_panorama_safe_mode_defers_graph_wide_fetches():
    service = ZepToolsService(api_key="dummy")

    def fail_graph_wide(*args, **kwargs):
        raise AssertionError("graph-wide fetch should not run in safe mode")

    service.get_all_nodes = fail_graph_wide
    service.get_all_edges = fail_graph_wide
    service.search_graph = lambda **kwargs: SearchResult(
        facts=["macro rates and broker friction sample"],
        edges=[],
        nodes=[],
        query=kwargs["query"],
        total_count=1,
        provenance={"source": "pending"},
    )

    result = service.panorama_search("g1", "macro risks", safe_mode=True)

    assert result.active_facts == ["macro rates and broker friction sample"]
    assert result.provenance["graph_wide_fetch_deferred"] is True
    assert "0 nodes" not in result.to_text().lower()


def test_panorama_non_safe_mode_fetches_all_nodes_and_edges():
    service = ZepToolsService(api_key="dummy")
    calls = {"nodes": 0, "edges": 0}

    def get_all_nodes(graph_id):
        calls["nodes"] += 1
        assert graph_id == "g1"
        return [
            NodeInfo("n1", "Retail Trader", ["Entity", "Actor"], "Small account trader", {}),
            NodeInfo("n2", "Broker Desk", ["Entity", "Broker"], "Risk desk", {}),
        ]

    def get_all_edges(graph_id, include_temporal=True):
        calls["edges"] += 1
        assert graph_id == "g1"
        assert include_temporal is True
        return [
            EdgeInfo("e1", "MENTIONS", "Retail traders cite broker buying-power blocks.", "n1", "n2"),
            EdgeInfo("e2", "OLD_SIGNAL", "Old social signal expired before macro data.", "n1", "n2", expired_at="2026-06-10"),
        ]

    service.get_all_nodes = get_all_nodes
    service.get_all_edges = get_all_edges

    result = service.panorama_search("g1", "broker macro", safe_mode=False)

    assert calls == {"nodes": 1, "edges": 1}
    assert result.total_nodes == 2
    assert result.total_edges == 2
    assert result.active_count == 1
    assert result.historical_count == 1
    assert result.provenance == {}


def test_quick_search_passes_safe_mode_to_search_graph():
    service = ZepToolsService(api_key="dummy")
    captured = {}

    def fake_search_graph(**kwargs):
        captured.update(kwargs)
        return SearchResult(
            facts=[],
            edges=[],
            nodes=[],
            query=kwargs["query"],
            total_count=0,
            provenance={"source": "pending"},
        )

    service.search_graph = fake_search_graph
    service.quick_search("g1", "0DTE broker confusion", safe_mode=True, section_index=7)

    assert captured["safe_mode"] is True
    assert captured["tool_name"] == "quick_search"
    assert captured["section_index"] == 7


def test_stopped_step4_interviews_are_replay_deferred(monkeypatch):
    service = ZepToolsService(api_key="dummy", report_mode="zep_throttle_cached")
    monkeypatch.setattr(service, "_is_simulation_stopped_or_completed", lambda simulation_id: True)
    monkeypatch.setattr(
        service,
        "_offline_interview_targets",
        lambda simulation_id, max_agents=5: [
            {"agent_id": 12, "realname": "Agent Twelve", "profession": "retail trader"}
        ],
    )

    result = service.interview_agents("sim_done", "broker confusion", max_agents=3)

    assert result.deferred is True
    assert result.mode == "replay_deferred"
    text = result.to_text()
    assert "Live interviews:** deferred" in text
    assert "0 / 1000 interviewed" not in text
    assert result.selected_agents[0]["agent_id"] == 12
