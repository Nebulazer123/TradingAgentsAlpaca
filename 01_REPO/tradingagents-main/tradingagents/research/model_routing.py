"""Cost-aware model routing policy for advisory research jobs.

The automation layer treats model workers as lanes with different jobs:

* Windows Ollama: fast local/free first-pass research.
* Mac Ollama: overnight research mule when reachable and healthy.
* Intelligent route: capped Gemini/OpenAI or an out-of-band Codex/ChatGPT review.
* Deterministic helpers: cheap packet/crawler/source summarization that needs no LLM.

These routes are advisory. They do not grant connector write access or broker
execution authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal

from tradingagents.llm_clients.model_catalog import get_model_context_window_tokens

WINDOWS_OLLAMA_ENV_NAMES = (
    "TRADINGAGENTS_WINDOWS_OLLAMA_URL",
    "TRADINGAGENTS_LOCAL_OLLAMA_URL",
    "TRADINGAGENTS_LOCAL_MODEL_URL",
    "OLLAMA_BASE_URL",
    "OLLAMA_HOST",
)
MAC_OLLAMA_ENV_NAMES = ("TRADINGAGENTS_MAC_OLLAMA_URL",)
DEFAULT_WINDOWS_OLLAMA_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MAC_OLLAMA_URL = "http://macbook-pro.tail37edd7.ts.net:11434/v1"


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str
    route: str
    status: str
    reason: str
    estimated_cost_usd: Decimal = Decimal("0")
    paid: bool = False
    endpoint_url: str | None = None
    role: str = "research"
    can_use_connectors: bool = False
    can_submit_orders: bool = False
    max_parallel_jobs: int = 1
    preferred_tasks: tuple[str, ...] = ()
    operator_summary: str = ""
    self_heal_actions: tuple[str, ...] = ()
    context_window_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.context_window_tokens is None:
            object.__setattr__(
                self,
                "context_window_tokens",
                get_model_context_window_tokens(self.provider, self.model),
            )

    def model_dump(self) -> dict:
        payload = asdict(self)
        payload["estimated_cost_usd"] = str(self.estimated_cost_usd)
        payload["preferred_tasks"] = list(self.preferred_tasks)
        return payload


@dataclass(frozen=True)
class ModelRoutingPolicy:
    allow_paid: bool = False
    allow_openai_paid: bool = False
    max_cost_usd_per_run: Decimal = Decimal("0")
    preferred_paid_provider: str = "gemini"
    max_model_calls_per_run: int = 8
    max_input_tokens_per_run: int = 120000
    max_output_tokens_per_run: int = 24000
    monthly_soft_budget_usd: Decimal = Decimal("0")
    windows_local_model: str = "gpt-oss:20b"
    mac_local_model: str = "deepseek-r1:14b"
    gemini_model: str = "gemini-2.5-flash"
    openai_model: str = "gpt-5.4-mini"
    codex_intelligent_model: str = "chatgpt-codex"

    @property
    def local_model(self) -> str:
        """Backward-compatible alias for older tests/callers."""
        return self.windows_local_model


def _env_present(env: Mapping[str, str], *names: str) -> bool:
    return any(bool(str(env.get(name, "")).strip()) for name in names)


def _first_env_value(env: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = str(env.get(name, "")).strip()
        if value:
            return value
    return None


def _decimal_env(env: Mapping[str, str], name: str, default: Decimal) -> Decimal:
    raw = str(env.get(name, "")).strip()
    if not raw:
        return default
    return Decimal(raw)


def _int_env(env: Mapping[str, str], name: str, default: int) -> int:
    raw = str(env.get(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def model_routing_policy_from_env(env: Mapping[str, str]) -> ModelRoutingPolicy:
    allow_paid = str(env.get("TRADINGAGENTS_MODEL_ALLOW_PAID", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    allow_openai_paid = str(env.get("TRADINGAGENTS_MODEL_ALLOW_OPENAI_PAID", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return ModelRoutingPolicy(
        allow_paid=allow_paid,
        allow_openai_paid=allow_openai_paid,
        max_cost_usd_per_run=_decimal_env(
            env,
            "TRADINGAGENTS_MODEL_MAX_COST_USD_PER_RUN",
            Decimal("0"),
        ),
        preferred_paid_provider=str(
            env.get("TRADINGAGENTS_MODEL_PREFERRED_PAID_PROVIDER") or "gemini"
        ).strip().lower(),
        max_model_calls_per_run=_int_env(
            env,
            "TRADINGAGENTS_MODEL_MAX_CALLS_PER_RUN",
            8,
        ),
        max_input_tokens_per_run=_int_env(
            env,
            "TRADINGAGENTS_MODEL_MAX_INPUT_TOKENS_PER_RUN",
            120000,
        ),
        max_output_tokens_per_run=_int_env(
            env,
            "TRADINGAGENTS_MODEL_MAX_OUTPUT_TOKENS_PER_RUN",
            24000,
        ),
        monthly_soft_budget_usd=_decimal_env(
            env,
            "TRADINGAGENTS_MODEL_MONTHLY_SOFT_BUDGET_USD",
            Decimal("0"),
        ),
        windows_local_model=str(
            env.get("TRADINGAGENTS_WINDOWS_RESEARCH_MODEL")
            or env.get("TRADINGAGENTS_LOCAL_RESEARCH_MODEL")
            or "gpt-oss:20b"
        ),
        mac_local_model=str(env.get("TRADINGAGENTS_MAC_RESEARCH_MODEL") or "deepseek-r1:14b"),
        gemini_model=str(env.get("TRADINGAGENTS_GEMINI_RESEARCH_MODEL") or "gemini-2.5-flash"),
        openai_model=str(env.get("TRADINGAGENTS_OPENAI_RESEARCH_MODEL") or "gpt-5.4-mini"),
        codex_intelligent_model=str(
            env.get("TRADINGAGENTS_CODEX_INTELLIGENT_MODEL") or "chatgpt-codex"
        ),
    )


def evaluate_model_budget_caps(
    *,
    policy: ModelRoutingPolicy,
    estimated_cost_usd: Decimal | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    model_calls: int = 1,
    monthly_spend_so_far_usd: Decimal = Decimal("0"),
) -> list[str]:
    """Return paid-model cap issues. Empty means the paid route is allowed."""
    issues: list[str] = []
    if model_calls < 0:
        issues.append("model_calls cannot be negative")
    if policy.max_model_calls_per_run > 0 and model_calls > policy.max_model_calls_per_run:
        issues.append(
            f"model calls {model_calls} exceed per-run cap {policy.max_model_calls_per_run}"
        )
    if (
        input_tokens is not None
        and policy.max_input_tokens_per_run > 0
        and input_tokens > policy.max_input_tokens_per_run
    ):
        issues.append(
            f"input tokens {input_tokens} exceed per-run cap {policy.max_input_tokens_per_run}"
        )
    if (
        output_tokens is not None
        and policy.max_output_tokens_per_run > 0
        and output_tokens > policy.max_output_tokens_per_run
    ):
        issues.append(
            f"output tokens {output_tokens} exceed per-run cap {policy.max_output_tokens_per_run}"
        )
    if estimated_cost_usd is None:
        issues.append("estimated model cost is unavailable")
    else:
        if estimated_cost_usd < Decimal("0"):
            issues.append("estimated model cost cannot be negative")
        if (
            policy.max_cost_usd_per_run > Decimal("0")
            and estimated_cost_usd > policy.max_cost_usd_per_run
        ):
            issues.append(
                f"estimated cost {estimated_cost_usd} exceeds per-run cap {policy.max_cost_usd_per_run}"
            )
        if (
            policy.monthly_soft_budget_usd > Decimal("0")
            and monthly_spend_so_far_usd + estimated_cost_usd > policy.monthly_soft_budget_usd
        ):
            issues.append(
                "estimated cost would exceed monthly soft budget "
                f"{policy.monthly_soft_budget_usd}"
            )
    return issues


def _budget_blocked_route(
    *,
    route: str,
    reason: str,
    estimated_cost_usd: Decimal | None,
    role: str = "research",
) -> ModelRoute:
    return ModelRoute(
        provider="none",
        model="none",
        route=route,
        status="blocked",
        reason=reason,
        estimated_cost_usd=estimated_cost_usd or Decimal("0"),
        role=role,
        paid=False,
        can_use_connectors=False,
        can_submit_orders=False,
    )


def select_windows_local_model_route(
    *,
    env: Mapping[str, str],
    policy: ModelRoutingPolicy | None = None,
    endpoint_health: Mapping[str, object] | None = None,
) -> ModelRoute:
    active_policy = policy or model_routing_policy_from_env(env)
    endpoint = _first_env_value(env, *WINDOWS_OLLAMA_ENV_NAMES)
    if endpoint:
        if endpoint_health is None:
            return ModelRoute(
                provider="ollama",
                model=active_policy.windows_local_model,
                route="windows_local_ollama",
                status="blocked",
                reason="Windows local Ollama requires a tags health probe before selection",
                endpoint_url=endpoint,
                role="local_research_worker",
                can_use_connectors=False,
                can_submit_orders=False,
                preferred_tasks=("cheap_research_drafts",),
                self_heal_actions=(
                    "verify_windows_ollama_tags_endpoint",
                    "fall_back_to_deterministic_helpers",
                ),
            )
        if endpoint_health is not None:
            reachable = bool(endpoint_health.get("reachable"))
            models = endpoint_health.get("models")
            model_names = {
                str(model).strip()
                for model in (models if isinstance(models, list) else [])
                if str(model).strip()
            }
            if not reachable:
                error = str(
                    endpoint_health.get("error")
                    or "Windows Ollama tags endpoint is unreachable"
                )
                return ModelRoute(
                    provider="ollama",
                    model=active_policy.windows_local_model,
                    route="windows_local_ollama",
                    status="blocked",
                    reason=f"Windows Ollama health probe failed: {error}",
                    endpoint_url=endpoint,
                    role="local_research_worker",
                    can_use_connectors=False,
                    can_submit_orders=False,
                    preferred_tasks=("cheap_research_drafts",),
                    operator_summary=(
                        "The Windows local model endpoint is configured but did not pass "
                        "the tags health check. Overnight research will keep using "
                        "deterministic helpers and the Codex review lane."
                    ),
                    self_heal_actions=(
                        "restart_windows_ollama",
                        "verify_windows_ollama_tags_endpoint",
                        "fall_back_to_deterministic_helpers",
                    ),
                )
            if model_names and active_policy.windows_local_model not in model_names:
                return ModelRoute(
                    provider="ollama",
                    model=active_policy.windows_local_model,
                    route="windows_local_ollama",
                    status="blocked",
                    reason=(
                        "Windows Ollama is reachable, but required helper model "
                        f"{active_policy.windows_local_model} is not in tags"
                    ),
                    endpoint_url=endpoint,
                    role="local_research_worker",
                    can_use_connectors=False,
                    can_submit_orders=False,
                    preferred_tasks=("cheap_research_drafts",),
                    self_heal_actions=(
                        "pull_TRADINGAGENTS_WINDOWS_RESEARCH_MODEL_on_windows_ollama",
                        "verify_windows_ollama_tags_endpoint",
                        "fall_back_to_deterministic_helpers",
                    ),
                )
        return ModelRoute(
            provider="ollama",
            model=active_policy.windows_local_model,
            route="windows_local_ollama",
            status="selected",
            reason="Windows local Ollama route is available for free first-pass research",
            endpoint_url=endpoint,
            role="local_research_worker",
            can_use_connectors=False,
            can_submit_orders=False,
            max_parallel_jobs=1,
            preferred_tasks=(
                "ticker_provider_summaries",
                "crawler_summaries",
                "source_overlap_notes",
                "cheap_research_drafts",
            ),
        )
    return ModelRoute(
        provider="ollama",
        model=active_policy.windows_local_model,
        route="windows_local_ollama",
        status="blocked",
        reason="Windows local Ollama URL is not configured",
        role="local_research_worker",
        can_use_connectors=False,
        can_submit_orders=False,
        preferred_tasks=("cheap_research_drafts",),
        operator_summary=(
            "Codex could not find a Windows Ollama endpoint for free local research. "
            "The bot will keep using deterministic packet helpers and Codex review "
            "instead of asking you to fix code."
        ),
        self_heal_actions=(
            "install_or_start_windows_ollama",
            "set_TRADINGAGENTS_WINDOWS_OLLAMA_URL_after_endpoint_exists",
            "fall_back_to_deterministic_helpers",
        ),
    )


def select_mac_ollama_model_route(
    *,
    env: Mapping[str, str],
    policy: ModelRoutingPolicy | None = None,
    endpoint_health: Mapping[str, object] | None = None,
) -> ModelRoute:
    active_policy = policy or model_routing_policy_from_env(env)
    endpoint = _first_env_value(env, *MAC_OLLAMA_ENV_NAMES) or DEFAULT_MAC_OLLAMA_URL
    if endpoint:
        if endpoint_health is None:
            return ModelRoute(
                provider="ollama",
                model=active_policy.mac_local_model,
                route="mac_ollama_research_mule",
                status="blocked",
                reason="Mac Ollama requires a tags health probe before selection",
                endpoint_url=endpoint,
                role="offloaded_research_helper",
                can_use_connectors=False,
                can_submit_orders=False,
                preferred_tasks=(
                    "source_triage",
                    "stale_source_summaries",
                    "contradiction_hunt",
                    "overnight_draft_cleanup",
                    "report_compression",
                ),
                operator_summary=(
                    "Mac DeepSeek helper has a default endpoint/model, but it was not "
                    "health-probed in this process. Treat it as optional until tags pass."
                ),
                self_heal_actions=(
                    "verify_mac_ollama_tags_endpoint",
                    "fall_back_to_windows_or_deterministic_lane",
                ),
            )
        if endpoint_health is not None:
            reachable = bool(endpoint_health.get("reachable"))
            models = endpoint_health.get("models")
            model_names = {
                str(model).strip()
                for model in (models if isinstance(models, list) else [])
                if str(model).strip()
            }
            if not reachable:
                error = str(endpoint_health.get("error") or "Mac Ollama tags endpoint is unreachable")
                network_unreachable = any(
                    marker in error.lower()
                    for marker in (
                        "timed out",
                        "timeout",
                        "connection timed out",
                        "host unreachable",
                        "network is unreachable",
                        "no route to host",
                        "getaddrinfo failed",
                    )
                )
                self_heal_actions = (
                    (
                        "verify_mac_tailscale_or_host_is_online",
                        "verify_mac_ssh_macbook_codex",
                        "restart_or_expose_mac_ollama_after_host_reachable",
                        "verify_mac_ollama_tags_endpoint",
                        "fall_back_to_windows_or_deterministic_lane",
                    )
                    if network_unreachable
                    else (
                        "verify_mac_ollama_tags_endpoint",
                        "restart_or_wake_mac_ollama",
                        "fall_back_to_windows_or_deterministic_lane",
                    )
                )
                return ModelRoute(
                    provider="ollama",
                    model=active_policy.mac_local_model,
                    route="mac_ollama_research_mule",
                    status="blocked",
                    reason=f"Mac Ollama health probe failed: {error}",
                    endpoint_url=endpoint,
                    role="offloaded_research_helper",
                    can_use_connectors=False,
                    can_submit_orders=False,
                    preferred_tasks=(
                        "source_triage",
                        "stale_source_summaries",
                        "contradiction_hunt",
                    ),
                    self_heal_actions=self_heal_actions,
                )
            if model_names and active_policy.mac_local_model not in model_names:
                return ModelRoute(
                    provider="ollama",
                    model=active_policy.mac_local_model,
                    route="mac_ollama_research_mule",
                    status="blocked",
                    reason=(
                        "Mac Ollama is reachable, but required helper model "
                        f"{active_policy.mac_local_model} is not in tags"
                    ),
                    endpoint_url=endpoint,
                    role="offloaded_research_helper",
                    can_use_connectors=False,
                    can_submit_orders=False,
                    preferred_tasks=(
                        "source_triage",
                        "stale_source_summaries",
                        "contradiction_hunt",
                    ),
                    self_heal_actions=(
                        "pull_TRADINGAGENTS_MAC_RESEARCH_MODEL_on_mac_ollama",
                        "verify_mac_ollama_tags_endpoint",
                        "fall_back_to_windows_or_deterministic_lane",
                    ),
                )
        return ModelRoute(
            provider="ollama",
            model=active_policy.mac_local_model,
            route="mac_ollama_research_mule",
            status="selected",
            reason=(
                "Mac Ollama helper is configured for cheap offloaded research chores on the "
                "32 GB Mac; Codex/OpenAI keeps final judgment."
            ),
            endpoint_url=endpoint,
            role="offloaded_research_helper",
            can_use_connectors=False,
            can_submit_orders=False,
            max_parallel_jobs=1,
            preferred_tasks=(
                "source_triage",
                "stale_source_summaries",
                "contradiction_hunt",
                "overnight_draft_cleanup",
                "report_compression",
            ),
        )
    return ModelRoute(
        provider="ollama",
        model=active_policy.mac_local_model,
        route="mac_ollama_research_mule",
        status="blocked",
        reason="Mac Ollama URL is not configured or the Mac worker is not ready",
        role="overnight_research_mule",
        can_use_connectors=False,
        can_submit_orders=False,
        preferred_tasks=("long_research_synthesis",),
        operator_summary=(
            "The Mac DeepSeek helper is not configured for this process yet. "
            "Codex will skip that offloaded helper lane and keep using deterministic "
            "packet helpers plus Codex/OpenAI judgment."
        ),
        self_heal_actions=(
            "verify_mac_ollama_tags_endpoint",
            "set_TRADINGAGENTS_MAC_OLLAMA_URL_after_endpoint_exists",
            "fall_back_to_windows_or_deterministic_lane",
        ),
    )


def select_deterministic_helper_route() -> ModelRoute:
    return ModelRoute(
        provider="none",
        model="rules_and_packets",
        route="deterministic_packet_helpers",
        status="selected",
        reason="No model is needed for compact source packets, fallback policy, and safety checks",
        role="cheap_helper_agents",
        paid=False,
        can_use_connectors=True,
        can_submit_orders=False,
        max_parallel_jobs=4,
        preferred_tasks=(
            "provider_fallback_packets",
            "reddit_listing_summaries",
            "release_calendar_packets",
            "schema_validation",
            "source_quality_checks",
        ),
    )


def select_intelligent_model_route(
    *,
    env: Mapping[str, str],
    policy: ModelRoutingPolicy | None = None,
    estimated_cost_usd: Decimal | None = Decimal("0"),
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    model_calls: int = 1,
    monthly_spend_so_far_usd: Decimal = Decimal("0"),
) -> ModelRoute:
    active_policy = policy or model_routing_policy_from_env(env)
    if active_policy.allow_paid:
        cap_issues = evaluate_model_budget_caps(
            policy=active_policy,
            estimated_cost_usd=estimated_cost_usd,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_calls=model_calls,
            monthly_spend_so_far_usd=monthly_spend_so_far_usd,
        )
        if cap_issues:
            return _budget_blocked_route(
                route="intelligent_budget_blocked",
                reason="; ".join(cap_issues),
                estimated_cost_usd=estimated_cost_usd,
                role="intelligent_judgment",
            )
        if _env_present(env, "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            return ModelRoute(
                provider="gemini",
                model=active_policy.gemini_model,
                route="paid_capped_gemini_judgment",
                status="selected",
                reason="Gemini is available for capped high-judgment synthesis",
                estimated_cost_usd=estimated_cost_usd or Decimal("0"),
                paid=True,
                role="intelligent_judgment",
                can_use_connectors=False,
                can_submit_orders=False,
                max_parallel_jobs=1,
                preferred_tasks=(
                    "contradiction_resolution",
                    "research_quality_grading",
                    "final_report_synthesis",
                    "self_improvement_handoff",
                ),
            )
        if active_policy.allow_openai_paid and _env_present(env, "OPENAI_API_KEY"):
            return ModelRoute(
                provider="openai",
                model=active_policy.openai_model,
                route="paid_capped_openai_judgment",
                status="selected",
                reason="OpenAI API is explicitly allowed for capped high-judgment synthesis",
                estimated_cost_usd=estimated_cost_usd or Decimal("0"),
                paid=True,
                role="intelligent_judgment",
                can_use_connectors=False,
                can_submit_orders=False,
                max_parallel_jobs=1,
                preferred_tasks=(
                    "contradiction_resolution",
                    "research_quality_grading",
                    "self_improvement_handoff",
                ),
            )
    return ModelRoute(
        provider="codex",
        model=active_policy.codex_intelligent_model,
        route="codex_or_chatgpt_thread_judgment",
        status="external",
        reason="Scheduled paid model use is not armed; route high-judgment review to Codex/ChatGPT in this thread",
        estimated_cost_usd=Decimal("0"),
        paid=False,
        role="intelligent_judgment",
        can_use_connectors=False,
        can_submit_orders=False,
        max_parallel_jobs=1,
        preferred_tasks=(
            "architecture_review",
            "contradiction_resolution",
            "final_approval_free_ops_review",
        ),
    )


def select_parallel_research_model_routes(
    *,
    env: Mapping[str, str],
    policy: ModelRoutingPolicy | None = None,
    estimated_judgment_cost_usd: Decimal | None = Decimal("0"),
    judgment_input_tokens: int | None = None,
    judgment_output_tokens: int | None = None,
    judgment_model_calls: int = 1,
    monthly_spend_so_far_usd: Decimal = Decimal("0"),
    route_health: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, ModelRoute]:
    active_policy = policy or model_routing_policy_from_env(env)
    return {
        "deterministic_helpers": select_deterministic_helper_route(),
        "windows_local": select_windows_local_model_route(
            env=env,
            policy=active_policy,
            endpoint_health=(route_health or {}).get("windows_local"),
        ),
        "mac_ollama": select_mac_ollama_model_route(
            env=env,
            policy=active_policy,
            endpoint_health=(route_health or {}).get("mac_ollama"),
        ),
        "intelligent_judgment": select_intelligent_model_route(
            env=env,
            policy=active_policy,
            estimated_cost_usd=estimated_judgment_cost_usd,
            input_tokens=judgment_input_tokens,
            output_tokens=judgment_output_tokens,
            model_calls=judgment_model_calls,
            monthly_spend_so_far_usd=monthly_spend_so_far_usd,
        ),
    }


def select_research_model_route(
    *,
    env: Mapping[str, str],
    policy: ModelRoutingPolicy | None = None,
    estimated_cost_usd: Decimal | None = Decimal("0"),
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    model_calls: int = 1,
    monthly_spend_so_far_usd: Decimal = Decimal("0"),
    route_health: Mapping[str, Mapping[str, object]] | None = None,
) -> ModelRoute:
    active_policy = policy or model_routing_policy_from_env(env)
    health = route_health or {}
    windows_route = select_windows_local_model_route(
        env=env,
        policy=active_policy,
        endpoint_health=health.get("windows_local"),
    )
    if windows_route.status == "selected":
        return windows_route
    mac_route = select_mac_ollama_model_route(
        env=env,
        policy=active_policy,
        endpoint_health=health.get("mac_ollama"),
    )
    if mac_route.status == "selected":
        return mac_route

    if not active_policy.allow_paid:
        return ModelRoute(
            provider="none",
            model="none",
            route="deterministic_only",
            status="blocked",
            reason="paid model routing is disabled and no health-verified local model route is available",
            estimated_cost_usd=Decimal("0"),
            paid=False,
        )

    cap_issues = evaluate_model_budget_caps(
        policy=active_policy,
        estimated_cost_usd=estimated_cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model_calls=model_calls,
        monthly_spend_so_far_usd=monthly_spend_so_far_usd,
    )
    if cap_issues:
        return _budget_blocked_route(
            route="budget_blocked",
            reason="; ".join(cap_issues),
            estimated_cost_usd=estimated_cost_usd,
        )

    if _env_present(env, "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        return ModelRoute(
            provider="gemini",
            model=active_policy.gemini_model,
            route="paid_capped_gemini",
            status="selected",
            reason="Gemini key is available and paid routing is explicitly allowed",
            estimated_cost_usd=estimated_cost_usd or Decimal("0"),
            paid=True,
        )

    if active_policy.allow_openai_paid and _env_present(env, "OPENAI_API_KEY"):
        return ModelRoute(
            provider="openai",
            model=active_policy.openai_model,
            route="paid_capped_openai",
            status="selected",
            reason="OpenAI API is explicitly allowed and Gemini was unavailable",
            estimated_cost_usd=estimated_cost_usd or Decimal("0"),
            paid=True,
        )

    return ModelRoute(
        provider="none",
        model="none",
        route="deterministic_only",
        status="blocked",
        reason="no approved model route is available",
        estimated_cost_usd=Decimal("0"),
        paid=False,
    )
