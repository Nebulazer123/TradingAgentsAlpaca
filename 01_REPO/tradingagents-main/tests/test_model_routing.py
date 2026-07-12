import json
from dataclasses import replace
from decimal import Decimal

from tradingagents.evals.agent_intelligence_ledger import forecasts_from_overnight_packet
from tradingagents.policy.packets import write_research_packet
from tradingagents.research.model_routing import (
    ModelRoutingPolicy,
    evaluate_model_budget_caps,
    model_routing_policy_from_env,
    select_intelligent_model_route,
    select_mac_ollama_model_route,
    select_parallel_research_model_routes,
    select_research_model_route,
    select_windows_local_model_route,
)
from tradingagents.research.model_telemetry import (
    compact_model_telemetry_report,
    label_model_telemetry_from_agent_outcomes,
    load_model_telemetry_packets,
    model_route_telemetry_packet,
    model_upgrade_recommendation,
    summarize_model_telemetry,
    write_model_telemetry_report,
)
from tradingagents.schemas.research import ModelRunTelemetryPacket


def test_model_routing_prefers_free_local_route_even_when_paid_key_exists():
    route = select_research_model_route(
        env={
            "TRADINGAGENTS_WINDOWS_OLLAMA_URL": "http://127.0.0.1:11434/v1",
            "TRADINGAGENTS_MAC_OLLAMA_URL": "http://100.116.42.66:11434/v1",
            "GEMINI_API_KEY": "present",
            "TRADINGAGENTS_MODEL_ALLOW_PAID": "true",
            "TRADINGAGENTS_MODEL_MAX_COST_USD_PER_RUN": "1.00",
        },
        estimated_cost_usd=Decimal("0.10"),
        route_health={
            "windows_local": {
                "reachable": True,
                "models": ["gpt-oss:20b"],
                "model_present": True,
            }
        },
    )

    assert route.provider == "ollama"
    assert route.route == "windows_local_ollama"
    assert route.paid is False
    assert route.estimated_cost_usd == Decimal("0")


def test_model_routing_uses_mac_route_when_windows_route_is_unavailable():
    route = select_research_model_route(
        env={"TRADINGAGENTS_MAC_OLLAMA_URL": "http://100.116.42.66:11434/v1"},
        estimated_cost_usd=Decimal("0.10"),
        route_health={
            "mac_ollama": {
                "reachable": True,
                "models": ["deepseek-r1:14b"],
                "model_present": True,
            }
        },
    )

    assert route.provider == "ollama"
    assert route.route == "mac_ollama_research_mule"
    assert route.model == "deepseek-r1:14b"
    assert route.role == "offloaded_research_helper"
    assert route.can_use_connectors is False
    assert route.can_submit_orders is False


def test_parallel_model_routes_keep_windows_mac_and_judgment_lanes_separate_with_override():
    routes = select_parallel_research_model_routes(
        env={
            "TRADINGAGENTS_WINDOWS_OLLAMA_URL": "http://127.0.0.1:11434/v1",
            "TRADINGAGENTS_MAC_OLLAMA_URL": "http://100.116.42.66:11434/v1",
            "TRADINGAGENTS_WINDOWS_RESEARCH_MODEL": "gpt-oss:20b",
            "TRADINGAGENTS_MAC_RESEARCH_MODEL": "qwen3:30b",
        },
        route_health={
            "windows_local": {
                "reachable": True,
                "models": ["gpt-oss:20b"],
                "model_present": True,
            },
            "mac_ollama": {
                "reachable": True,
                "models": ["qwen3:30b"],
                "model_present": True,
            },
        },
    )

    assert routes["deterministic_helpers"].route == "deterministic_packet_helpers"
    assert routes["deterministic_helpers"].can_use_connectors is True
    assert routes["windows_local"].route == "windows_local_ollama"
    assert routes["windows_local"].model == "gpt-oss:20b"
    assert routes["mac_ollama"].route == "mac_ollama_research_mule"
    assert routes["mac_ollama"].model == "qwen3:30b"
    assert routes["intelligent_judgment"].route == "codex_or_chatgpt_thread_judgment"
    assert routes["intelligent_judgment"].status == "external"
    assert all(route.can_submit_orders is False for route in routes.values())
    assert routes["windows_local"].self_heal_actions == ()
    assert routes["mac_ollama"].self_heal_actions == ()


def test_mac_ollama_defaults_to_reachable_32gb_deepseek_helper_model():
    route = select_mac_ollama_model_route(
        env={"TRADINGAGENTS_MAC_OLLAMA_URL": "http://macbook-pro.tail37edd7.ts.net:11434/v1"},
        endpoint_health={
            "reachable": True,
            "models": ["deepseek-r1:14b"],
            "model_present": True,
        },
    )

    assert route.status == "selected"
    assert route.model == "deepseek-r1:14b"
    assert route.max_parallel_jobs == 1
    assert "source_triage" in route.preferred_tasks
    assert "report_compression" in route.preferred_tasks
    assert "deep intelligence" not in route.reason.lower()
    assert route.can_submit_orders is False


def test_mac_ollama_blocks_when_probe_reachable_but_helper_model_missing():
    route = select_mac_ollama_model_route(
        env={"TRADINGAGENTS_MAC_OLLAMA_URL": "http://macbook-pro.tail37edd7.ts.net:11434/v1"},
        endpoint_health={
            "reachable": True,
            "models": ["llama3.1:8b"],
        },
    )

    assert route.status == "blocked"
    assert route.model == "deepseek-r1:14b"
    assert "not in tags" in route.reason
    assert "pull_TRADINGAGENTS_MAC_RESEARCH_MODEL_on_mac_ollama" in route.self_heal_actions


def test_mac_ollama_timeout_points_to_tailnet_host_recovery():
    route = select_mac_ollama_model_route(
        env={"TRADINGAGENTS_MAC_OLLAMA_URL": "http://macbook-pro.tail37edd7.ts.net:11434/v1"},
        endpoint_health={
            "reachable": False,
            "models": [],
            "error": "<urlopen error timed out>",
        },
    )

    assert route.status == "blocked"
    assert route.model == "deepseek-r1:14b"
    assert "health probe failed" in route.reason
    assert "verify_mac_tailscale_or_host_is_online" in route.self_heal_actions
    assert "verify_mac_ssh_macbook_codex" in route.self_heal_actions
    assert "verify_mac_ollama_tags_endpoint" in route.self_heal_actions
    assert route.can_submit_orders is False


def test_individual_local_routes_block_cleanly_when_endpoint_missing():
    windows = select_windows_local_model_route(env={})
    mac = select_mac_ollama_model_route(env={})

    assert windows.status == "blocked"
    assert windows.route == "windows_local_ollama"
    assert windows.operator_summary
    assert "Codex" in windows.operator_summary
    assert "install_or_start_windows_ollama" in windows.self_heal_actions
    assert mac.status == "blocked"
    assert mac.route == "mac_ollama_research_mule"
    assert mac.model == "deepseek-r1:14b"
    assert mac.endpoint_url == "http://macbook-pro.tail37edd7.ts.net:11434/v1"
    assert "health probe" in mac.reason
    assert "verify_mac_ollama_tags_endpoint" in mac.self_heal_actions


def test_windows_local_route_blocks_when_probe_fails():
    route = select_windows_local_model_route(
        env={"TRADINGAGENTS_WINDOWS_OLLAMA_URL": "http://127.0.0.1:11434/v1"},
        endpoint_health={
            "reachable": False,
            "models": [],
            "error": "connection refused",
        },
    )

    assert route.status == "blocked"
    assert route.route == "windows_local_ollama"
    assert "health probe failed" in route.reason
    assert "restart_windows_ollama" in route.self_heal_actions


def test_windows_local_route_blocks_when_required_model_missing():
    route = select_windows_local_model_route(
        env={
            "TRADINGAGENTS_WINDOWS_OLLAMA_URL": "http://127.0.0.1:11434/v1",
            "TRADINGAGENTS_WINDOWS_RESEARCH_MODEL": "gpt-oss:20b",
        },
        endpoint_health={
            "reachable": True,
            "models": ["qwen3:30b"],
        },
    )

    assert route.status == "blocked"
    assert route.model == "gpt-oss:20b"
    assert "not in tags" in route.reason
    assert "pull_TRADINGAGENTS_WINDOWS_RESEARCH_MODEL_on_windows_ollama" in (
        route.self_heal_actions
    )


def test_intelligent_route_uses_codex_thread_when_paid_models_not_armed():
    route = select_intelligent_model_route(
        env={"GEMINI_API_KEY": "present"},
        estimated_cost_usd=Decimal("0.01"),
    )

    assert route.provider == "codex"
    assert route.status == "external"
    assert route.route == "codex_or_chatgpt_thread_judgment"
    assert route.paid is False


def test_intelligent_route_uses_capped_gemini_when_paid_is_explicitly_allowed():
    route = select_intelligent_model_route(
        env={
            "GOOGLE_API_KEY": "present",
            "TRADINGAGENTS_MODEL_ALLOW_PAID": "true",
            "TRADINGAGENTS_MODEL_MAX_COST_USD_PER_RUN": "1.00",
        },
        estimated_cost_usd=Decimal("0.10"),
    )

    assert route.provider == "gemini"
    assert route.route == "paid_capped_gemini_judgment"
    assert route.paid is True


def test_model_routing_uses_gemini_first_when_paid_is_explicitly_allowed():
    route = select_research_model_route(
        env={
            "GEMINI_API_KEY": "present",
            "OPENAI_API_KEY": "present",
            "TRADINGAGENTS_MODEL_ALLOW_PAID": "true",
            "TRADINGAGENTS_MODEL_ALLOW_OPENAI_PAID": "true",
            "TRADINGAGENTS_MODEL_MAX_COST_USD_PER_RUN": "1.00",
        },
        estimated_cost_usd=Decimal("0.10"),
    )

    assert route.provider == "gemini"
    assert route.route == "paid_capped_gemini"
    assert route.paid is True


def test_model_routing_blocks_paid_by_default():
    route = select_research_model_route(
        env={"GEMINI_API_KEY": "present"},
        estimated_cost_usd=Decimal("0.01"),
    )

    assert route.status == "blocked"
    assert route.route == "deterministic_only"


def test_model_routing_blocks_when_budget_exceeded():
    route = select_research_model_route(
        env={
            "GEMINI_API_KEY": "present",
            "TRADINGAGENTS_MODEL_ALLOW_PAID": "true",
            "TRADINGAGENTS_MODEL_MAX_COST_USD_PER_RUN": "0.01",
        },
        estimated_cost_usd=Decimal("0.02"),
    )

    assert route.status == "blocked"
    assert route.route == "budget_blocked"


def test_model_routing_openai_requires_extra_switch():
    blocked = select_research_model_route(
        env={
            "OPENAI_API_KEY": "present",
            "TRADINGAGENTS_MODEL_ALLOW_PAID": "true",
            "TRADINGAGENTS_MODEL_MAX_COST_USD_PER_RUN": "1.00",
        },
        estimated_cost_usd=Decimal("0.01"),
    )
    allowed = select_research_model_route(
        env={
            "OPENAI_API_KEY": "present",
            "TRADINGAGENTS_MODEL_ALLOW_PAID": "true",
            "TRADINGAGENTS_MODEL_ALLOW_OPENAI_PAID": "true",
            "TRADINGAGENTS_MODEL_MAX_COST_USD_PER_RUN": "1.00",
        },
        estimated_cost_usd=Decimal("0.01"),
    )

    assert blocked.provider == "none"
    assert allowed.provider == "openai"


def test_model_telemetry_packet_is_analysis_only_and_records_cost():
    route = select_research_model_route(
        env={
            "GEMINI_API_KEY": "present",
            "TRADINGAGENTS_MODEL_ALLOW_PAID": "true",
            "TRADINGAGENTS_MODEL_MAX_COST_USD_PER_RUN": "1.00",
        },
        estimated_cost_usd=Decimal("0.10"),
    )

    packet = model_route_telemetry_packet(
        run_id="model-test",
        route=route,
        input_tokens=1000,
        output_tokens=250,
        latency_seconds=1.5,
    )

    assert packet.analysis_only is True
    assert packet.provider == "gemini"
    assert packet.context_window_tokens == 1_048_576
    assert packet.estimated_cost_usd == "0.10"
    assert packet.input_tokens == 1000


def test_model_routing_policy_from_env_uses_gemini_model_override():
    policy = model_routing_policy_from_env(
        {
            "TRADINGAGENTS_MODEL_ALLOW_PAID": "true",
            "TRADINGAGENTS_MODEL_MAX_COST_USD_PER_RUN": "0.50",
            "TRADINGAGENTS_WINDOWS_RESEARCH_MODEL": "windows-test-model",
            "TRADINGAGENTS_MAC_RESEARCH_MODEL": "mac-test-model",
            "TRADINGAGENTS_GEMINI_RESEARCH_MODEL": "gemini-test-model",
        }
    )

    assert policy.allow_paid is True
    assert policy.max_cost_usd_per_run == Decimal("0.50")
    assert policy.windows_local_model == "windows-test-model"
    assert policy.mac_local_model == "mac-test-model"
    assert policy.local_model == "windows-test-model"
    assert policy.gemini_model == "gemini-test-model"


def test_model_routing_policy_from_env_reads_hard_caps():
    policy = model_routing_policy_from_env(
        {
            "TRADINGAGENTS_MODEL_ALLOW_PAID": "true",
            "TRADINGAGENTS_MODEL_MAX_COST_USD_PER_RUN": "0.50",
            "TRADINGAGENTS_MODEL_PREFERRED_PAID_PROVIDER": "gemini",
            "TRADINGAGENTS_MODEL_MAX_CALLS_PER_RUN": "3",
            "TRADINGAGENTS_MODEL_MAX_INPUT_TOKENS_PER_RUN": "10000",
            "TRADINGAGENTS_MODEL_MAX_OUTPUT_TOKENS_PER_RUN": "2000",
            "TRADINGAGENTS_MODEL_MONTHLY_SOFT_BUDGET_USD": "5.00",
        }
    )

    assert policy.preferred_paid_provider == "gemini"
    assert policy.max_model_calls_per_run == 3
    assert policy.max_input_tokens_per_run == 10000
    assert policy.max_output_tokens_per_run == 2000
    assert policy.monthly_soft_budget_usd == Decimal("5.00")


def test_model_budget_caps_fail_closed_on_unknown_cost_and_usage_limits():
    policy = ModelRoutingPolicy(
        allow_paid=True,
        max_cost_usd_per_run=Decimal("0.50"),
        max_model_calls_per_run=2,
        max_input_tokens_per_run=100,
        max_output_tokens_per_run=50,
        monthly_soft_budget_usd=Decimal("1.00"),
    )

    unknown_cost = evaluate_model_budget_caps(
        policy=policy,
        estimated_cost_usd=None,
        input_tokens=101,
        output_tokens=51,
        model_calls=3,
    )
    monthly = evaluate_model_budget_caps(
        policy=policy,
        estimated_cost_usd=Decimal("0.20"),
        monthly_spend_so_far_usd=Decimal("0.90"),
    )

    assert "estimated model cost is unavailable" in unknown_cost
    assert any("input tokens" in issue for issue in unknown_cost)
    assert any("output tokens" in issue for issue in unknown_cost)
    assert any("model calls" in issue for issue in unknown_cost)
    assert monthly == ["estimated cost would exceed monthly soft budget 1.00"]


def test_paid_model_route_blocks_when_hard_caps_fail():
    route = select_research_model_route(
        env={
            "GEMINI_API_KEY": "present",
            "TRADINGAGENTS_MODEL_ALLOW_PAID": "true",
            "TRADINGAGENTS_MODEL_MAX_COST_USD_PER_RUN": "1.00",
            "TRADINGAGENTS_MODEL_MAX_INPUT_TOKENS_PER_RUN": "100",
        },
        estimated_cost_usd=Decimal("0.10"),
        input_tokens=101,
    )
    unknown = select_intelligent_model_route(
        env={
            "GOOGLE_API_KEY": "present",
            "TRADINGAGENTS_MODEL_ALLOW_PAID": "true",
            "TRADINGAGENTS_MODEL_MAX_COST_USD_PER_RUN": "1.00",
        },
        estimated_cost_usd=None,
    )

    assert route.status == "blocked"
    assert route.route == "budget_blocked"
    assert "input tokens" in route.reason
    assert unknown.status == "blocked"
    assert unknown.route == "intelligent_budget_blocked"
    assert "cost is unavailable" in unknown.reason


def test_model_telemetry_rollup_dedupes_latest_and_tracks_budget(tmp_path):
    gemini = select_research_model_route(
        env={
            "GEMINI_API_KEY": "present",
            "TRADINGAGENTS_MODEL_ALLOW_PAID": "true",
            "TRADINGAGENTS_MODEL_MAX_COST_USD_PER_RUN": "1.00",
        },
        estimated_cost_usd=Decimal("0.10"),
    )
    blocked = select_research_model_route(
        env={"GEMINI_API_KEY": "present"},
        estimated_cost_usd=Decimal("0.01"),
    )
    telemetry_dir = tmp_path / "model_telemetry"
    write_research_packet(
        model_route_telemetry_packet(
            run_id="run-1",
            route=gemini,
            input_tokens=100,
            output_tokens=25,
            latency_seconds=1.5,
        ),
        telemetry_dir,
    )
    write_research_packet(
        model_route_telemetry_packet(
            run_id="run-2",
            route=blocked,
            error_summary="paid models disabled",
        ),
        telemetry_dir,
    )

    packets = load_model_telemetry_packets(telemetry_dir)
    report = summarize_model_telemetry(packets, budget_limit_usd=Decimal("0.25"))
    report_path = write_model_telemetry_report(report, tmp_path / "reports")

    assert len(packets) == 3
    assert report["packet_count"] == 2
    assert report["status_counts"] == {"success": 1, "blocked": 1}
    assert report["estimated_cost_total_usd"] == "0.1000"
    assert report["budget_remaining_usd"] == "0.1500"
    assert report["total_input_tokens"] == 100
    assert (tmp_path / "reports" / "latest.json").exists()
    assert report_path.exists()
    compact_path = report_path.with_name(f"{report_path.stem}.compact.json")
    assert compact_path.exists()
    latest_compact = json.loads(
        (tmp_path / "reports" / "latest-compact.json").read_text(encoding="utf-8")
    )
    assert latest_compact["schema"] == "compact_model_telemetry_report_v1"
    assert latest_compact["raw_packet_path"] == str(report_path)
    assert latest_compact["can_submit_orders"] is False
    assert latest_compact["packet_count"] == 2
    assert latest_compact["status_counts"] == {"success": 1, "blocked": 1}


def test_compact_model_telemetry_report_preserves_route_decision_fields(tmp_path):
    report = {
        "kind": "model_telemetry_report",
        "generated_at": "2026-06-06T19:51:26+00:00",
        "analysis_only": True,
        "packet_count": 2,
        "status_counts": {"success": 1, "blocked": 1},
        "provider_counts": {"ollama": 2},
        "route_counts": {"mac_ollama_research_mule": 1, "windows_local_ollama": 1},
        "usefulness_counts": {"pending": 2},
        "outcome_counts": {"unresolved": 2},
        "resolved_model_run_count": 0,
        "estimated_cost_total_usd": "0.0000",
        "budget_remaining_usd": None,
        "average_quality_score": None,
        "error_count": 1,
        "recent_errors": [
            {
                "run_id": "run-2",
                "provider": "ollama",
                "route": "windows_local_ollama",
                "status": "blocked",
                "error_summary": "Windows local Ollama URL is not configured",
            }
        ],
        "current_route_statuses": [
            {
                "route": "mac_ollama_research_mule",
                "provider": "ollama",
                "model": "deepseek-r1:14b",
                "context_window_tokens": 32768,
                "status": "success",
                "generated_at": "2026-06-06T19:51:26+00:00",
            }
        ],
        "blocked_route_summaries": [
            {
                "route": "windows_local_ollama",
                "provider": "ollama",
                "blocked_count": 1,
                "latest_error": "Windows local Ollama URL is not configured",
                "error_kind": "windows_endpoint_not_configured",
                "plain_english": "Windows local Ollama endpoint is not configured.",
                "self_heal_actions": ["install_or_start_windows_ollama"],
            }
        ],
        "operator_summary": "Model routes have 2 packet(s), but none are resolved yet.",
    }

    compact = compact_model_telemetry_report(report, raw_packet_path=tmp_path / "raw.json")

    assert compact["schema"] == "compact_model_telemetry_report_v1"
    assert compact["raw_packet_path"] == str(tmp_path / "raw.json")
    assert compact["usefulness_counts"] == {"pending": 2}
    assert compact["recent_errors"][0]["route"] == "windows_local_ollama"
    assert compact["current_route_statuses"][0]["model"] == "deepseek-r1:14b"
    assert compact["current_route_statuses"][0]["context_window_tokens"] == 32768
    assert compact["blocked_route_summaries"][0]["blocked_count"] == 1
    assert (
        compact["blocked_route_summaries"][0]["error_kind"]
        == "windows_endpoint_not_configured"
    )
    assert compact["blocked_route_summaries"][0]["self_heal_actions"] == [
        "install_or_start_windows_ollama"
    ]
    assert compact["can_submit_orders"] is False


def test_model_telemetry_rollup_tracks_usefulness_and_outcomes():
    useful = ModelRunTelemetryPacket(
        run_id="useful-run",
        provider="gemini",
        model="gemini-test",
        route="paid_capped_gemini_judgment",
        status="success",
        estimated_cost_usd="0.0700",
        latency_seconds=2.0,
        usefulness_label="useful",
        outcome_label="helped",
        quality_score=0.8,
        outcome_notes="Helped catch a stale catalyst.",
    )
    harmful = ModelRunTelemetryPacket(
        run_id="bad-run",
        provider="local",
        model="local-test",
        route="windows_local_ollama",
        status="success",
        estimated_cost_usd="0",
        latency_seconds=1.0,
        usefulness_label="harmful",
        outcome_label="hurt",
        quality_score=-0.4,
    )
    pending = ModelRunTelemetryPacket(
        run_id="pending-run",
        provider="codex",
        model="external",
        route="codex_or_chatgpt_thread_judgment",
        status="fallback",
        usefulness_label="pending",
        outcome_label="unresolved",
    )

    report = summarize_model_telemetry([useful, harmful, pending])

    assert report["analysis_only"] is True
    assert report["usefulness_counts"] == {"useful": 1, "harmful": 1, "pending": 1}
    assert report["outcome_counts"] == {"helped": 1, "hurt": 1, "unresolved": 1}
    assert report["resolved_model_run_count"] == 2
    assert report["average_quality_score"] == 0.2
    assert report["cost_by_usefulness_usd"]["useful"] == "0.0700"
    assert report["policy"]["can_trade"] is False
    assert report["upgrade_recommendation"]["auto_upgrade_allowed"] is False


def test_model_telemetry_labels_referenced_runs_from_resolved_agent_outcomes():
    forecast = forecasts_from_overnight_packet(
        {
            "generated_at": "2026-06-01T12:00:00+00:00",
            "ticker_results": [
                {
                    "symbol": "NVDA",
                    "rating": "Buy",
                    "reports": {"market": "Bullish breakout and strong momentum."},
                }
            ],
        },
        benchmark="QQQ",
    )[0]
    useful_forecast = replace(
        forecast,
        resolved=True,
        outcome=True,
        relative_return="8.00",
        resolved_at="2026-06-08T12:00:00+00:00",
    )
    harmful_forecast = replace(
        forecast,
        forecast_id=f"{forecast.forecast_id}-miss",
        resolved=True,
        outcome=False,
        relative_return="-2.00",
        resolved_at="2026-06-08T12:00:00+00:00",
    )
    useful_packet = ModelRunTelemetryPacket(
        run_id="model-helped",
        provider="codex",
        model="chatgpt-codex",
        route="codex_or_chatgpt_thread_judgment",
        status="fallback",
        source_refs=[useful_forecast.forecast_id],
    )
    harmful_packet = ModelRunTelemetryPacket(
        run_id="model-hurt",
        provider="codex",
        model="chatgpt-codex",
        route="codex_or_chatgpt_thread_judgment",
        status="fallback",
        source_refs=[harmful_forecast.forecast_id],
    )
    unresolved_packet = ModelRunTelemetryPacket(
        run_id="model-pending",
        provider="codex",
        model="chatgpt-codex",
        route="codex_or_chatgpt_thread_judgment",
        status="fallback",
        source_refs=["missing-forecast"],
    )

    labeled = label_model_telemetry_from_agent_outcomes(
        [useful_packet, harmful_packet, unresolved_packet],
        [useful_forecast, harmful_forecast],
    )

    assert labeled[0].usefulness_label == "useful"
    assert labeled[0].outcome_label == "helped"
    assert labeled[0].quality_score and labeled[0].quality_score > 0
    assert labeled[0].resolved_at == "2026-06-08T12:00:00+00:00"
    assert labeled[1].usefulness_label == "harmful"
    assert labeled[1].outcome_label == "hurt"
    assert labeled[1].quality_score and labeled[1].quality_score < 0
    assert labeled[2].usefulness_label == "pending"
    assert labeled[2].outcome_label == "unresolved"


def test_model_telemetry_rollup_explains_blocked_local_routes():
    windows = ModelRunTelemetryPacket(
        run_id="windows-blocked",
        provider="ollama",
        model="gpt-oss:20b",
        route="windows_local_ollama",
        status="blocked",
        error_summary="Windows local Ollama URL is not configured",
        usefulness_label="pending",
        outcome_label="unresolved",
    )
    mac = ModelRunTelemetryPacket(
        run_id="mac-blocked",
        provider="ollama",
        model="gpt-oss:20b",
        route="mac_ollama_research_mule",
        status="blocked",
        error_summary="Mac Ollama URL is not configured or the Mac worker is not ready",
        usefulness_label="pending",
        outcome_label="unresolved",
    )

    report = summarize_model_telemetry([windows, mac])
    by_route = {item["route"]: item for item in report["blocked_route_summaries"]}

    assert "Model routes are safe but not fully ready" in report["operator_summary"]
    assert by_route["windows_local_ollama"]["blocked_count"] == 1
    assert "install_or_start_windows_ollama" in by_route["windows_local_ollama"]["self_heal_actions"]
    assert by_route["mac_ollama_research_mule"]["blocked_count"] == 1
    assert "verify_mac_ollama_tags_endpoint" in by_route["mac_ollama_research_mule"]["self_heal_actions"]
    assert report["policy"]["can_trade"] is False


def test_model_telemetry_rollup_explains_mac_timeout_as_host_unreachable():
    mac = ModelRunTelemetryPacket(
        run_id="mac-timeout",
        provider="ollama",
        model="deepseek-r1:14b",
        route="mac_ollama_research_mule",
        status="blocked",
        error_summary="Mac Ollama health probe failed: <urlopen error timed out>",
        usefulness_label="pending",
        outcome_label="unresolved",
    )
    windows = ModelRunTelemetryPacket(
        run_id="windows-ok",
        provider="ollama",
        model="tradingagents-qwen3-30b-a3b-instruct-2507-q4-4k:latest",
        route="windows_local_ollama",
        status="success",
        usefulness_label="pending",
        outcome_label="unresolved",
    )

    report = summarize_model_telemetry([mac, windows])
    compact = compact_model_telemetry_report(report, raw_packet_path="raw.json")
    by_route = {item["route"]: item for item in report["blocked_route_summaries"]}
    compact_by_route = {item["route"]: item for item in compact["blocked_route_summaries"]}
    current_by_route = {item["route"]: item for item in report["current_route_statuses"]}
    compact_current_by_route = {
        item["route"]: item for item in compact["current_route_statuses"]
    }

    mac_summary = by_route["mac_ollama_research_mule"]
    assert mac_summary["error_kind"] == "mac_host_unreachable"
    assert "Mac helper host is unreachable" in mac_summary["plain_english"]
    assert "verify_mac_tailscale_or_host_is_online" in mac_summary["self_heal_actions"]
    assert "verify_mac_ssh_macbook_codex" in mac_summary["self_heal_actions"]
    assert "Mac helper host is unreachable" in report["operator_summary"]
    assert compact_by_route["mac_ollama_research_mule"]["error_kind"] == "mac_host_unreachable"
    assert "plain_english" in compact_by_route["mac_ollama_research_mule"]
    assert "self_heal_actions" in compact_by_route["mac_ollama_research_mule"]
    assert current_by_route["mac_ollama_research_mule"]["context_window_tokens"] == 4_096
    assert current_by_route["windows_local_ollama"]["context_window_tokens"] == 4_096
    assert (
        compact_current_by_route["mac_ollama_research_mule"]["context_window_tokens"]
        == 4_096
    )
    assert compact_current_by_route["windows_local_ollama"]["context_window_tokens"] == 4_096
    assert report["policy"]["can_trade"] is False


def test_model_telemetry_rollup_uses_latest_route_status_for_current_blockers():
    old_mac_blocked = ModelRunTelemetryPacket(
        run_id="research-older-mac",
        generated_at="2026-06-02T07:00:00+00:00",
        provider="ollama",
        model="qwen3:30b",
        route="mac_ollama_research_mule",
        status="blocked",
        error_summary="Mac Ollama URL is not configured or the Mac worker is not ready",
        usefulness_label="pending",
        outcome_label="unresolved",
    )
    fresh_mac_success = ModelRunTelemetryPacket(
        run_id="research-newer-mac",
        generated_at="2026-06-04T20:57:15+00:00",
        provider="ollama",
        model="deepseek-r1:14b",
        route="mac_ollama_research_mule",
        status="success",
        usefulness_label="pending",
        outcome_label="unresolved",
    )

    report = summarize_model_telemetry([old_mac_blocked, fresh_mac_success])
    current_by_route = {item["route"]: item for item in report["current_route_statuses"]}

    assert report["blocked_route_summaries"] == []
    assert report["historical_blocked_route_count"] == 1
    assert current_by_route["mac_ollama_research_mule"]["status"] == "success"
    assert current_by_route["mac_ollama_research_mule"]["model"] == "deepseek-r1:14b"
    assert "no blocked helper lanes" in report["operator_summary"]
    assert "historical" in report["operator_summary"]


def test_model_upgrade_recommendation_requires_history_and_never_auto_upgrades():
    thin = model_upgrade_recommendation(
        {
            "packet_count": 3,
            "resolved_model_run_count": 2,
            "usefulness_counts": {"useful": 2},
            "outcome_counts": {"helped": 2},
        }
    )
    strong = model_upgrade_recommendation(
        {
            "packet_count": 25,
            "resolved_model_run_count": 25,
            "usefulness_counts": {"useful": 20, "mixed": 5},
            "outcome_counts": {"helped": 20, "neutral": 5},
        }
    )
    harmful = model_upgrade_recommendation(
        {
            "packet_count": 25,
            "resolved_model_run_count": 25,
            "usefulness_counts": {"useful": 20, "harmful": 4},
            "outcome_counts": {"helped": 20, "hurt": 4},
        }
    )

    assert thin["state"] == "insufficient_history"
    assert strong["state"] == "manual_experiment_candidate"
    assert harmful["state"] == "downgrade_or_disable"
    assert thin["auto_upgrade_allowed"] is False
    assert strong["auto_upgrade_allowed"] is False
    assert harmful["auto_upgrade_allowed"] is False
