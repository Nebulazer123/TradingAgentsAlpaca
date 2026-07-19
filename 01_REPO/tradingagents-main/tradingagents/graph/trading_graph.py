# TradingAgents/graph/trading_graph.py

import json
import logging
import os
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

from langgraph.prebuilt import ToolNode

from tradingagents.agents import *

# Import the new abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_global_news,
    get_income_statement,
    get_indicators,
    get_insider_transactions,
    get_macro_context,
    get_news,
    get_sentiment_context,
    get_stock_data,
    get_supplemental_market_context,
)
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.orchestration.work_packets import build_packet_id

from .checkpointer import checkpoint_step, clear_checkpoint, get_checkpointer, thread_id
from .conditional_logic import ConditionalLogic
from .packet_nodes import (
    DECISION_PACKET_REF_SCHEMA_VERSION,
    PACKET_HANDOFF_SCHEMA_VERSION,
    build_graph_run_id,
)
from .propagation import Propagator
from .reflection import Reflector
from .setup import GraphSetup
from .signal_processing import SignalProcessor

CHECKPOINT_SIGNATURE_SCHEMA_VERSION = 1
_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHECKPOINT_PACKET_REF_FIELDS = {
    "schema_version",
    "packet_id",
    "kind",
    "packet_sha256",
    "packet_path",
    "evidence_sha256",
    "analysis_only",
    "execution_authority",
    "can_submit_orders",
}
_CHECKPOINT_PACKET_KIND_ORDER = (
    "research_evidence",
    "trader_proposal",
    "portfolio_decision",
)


def _checkpoint_run_start(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("checkpoint run_started_at must be canonical UTC seconds")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            "checkpoint run_started_at must be canonical UTC seconds"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("checkpoint run_started_at must be canonical UTC seconds")
    normalized = parsed.astimezone(timezone.utc)
    if (
        normalized.microsecond != 0
        or normalized.isoformat(timespec="seconds") != value
    ):
        raise ValueError("checkpoint run_started_at must be canonical UTC seconds")
    return value


def _checkpoint_packet_refs(value: Any, *, run_id: str) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("checkpoint decision_packet_refs must be a list")
    if len(value) > len(_CHECKPOINT_PACKET_KIND_ORDER):
        raise ValueError("checkpoint decision_packet_refs contains extra items")
    expected_kinds = list(_CHECKPOINT_PACKET_KIND_ORDER[: len(value)])
    normalized = []
    packet_ids = []
    for index, (reference, expected_kind) in enumerate(
        zip(value, expected_kinds, strict=True)
    ):
        if (
            not isinstance(reference, Mapping)
            or set(reference) != _CHECKPOINT_PACKET_REF_FIELDS
        ):
            raise ValueError(
                f"checkpoint decision_packet_refs[{index}] has invalid fields"
            )
        if type(reference["schema_version"]) is not int or (
            reference["schema_version"] != DECISION_PACKET_REF_SCHEMA_VERSION
        ):
            raise ValueError(
                f"checkpoint decision_packet_refs[{index}] has invalid schema"
            )
        packet_id = build_packet_id(run_id, expected_kind)
        if (
            reference["packet_id"] != packet_id
            or reference["kind"] != expected_kind
            or reference["packet_path"] != f"packets/{packet_id}.json"
        ):
            raise ValueError(
                f"checkpoint decision_packet_refs[{index}] has invalid identity"
            )
        if (
            not isinstance(reference["packet_sha256"], str)
            or _LOWER_SHA256.fullmatch(reference["packet_sha256"]) is None
            or not isinstance(reference["evidence_sha256"], str)
            or _LOWER_SHA256.fullmatch(reference["evidence_sha256"]) is None
        ):
            raise ValueError(
                f"checkpoint decision_packet_refs[{index}] has invalid digest"
            )
        if (
            reference["analysis_only"] is not True
            or reference["execution_authority"] != "none"
            or reference["can_submit_orders"] is not False
        ):
            raise ValueError(
                f"checkpoint decision_packet_refs[{index}] has invalid authority"
            )
        packet_ids.append(packet_id)
        normalized.append(dict(reference))
    if len(packet_ids) != len(set(packet_ids)):
        raise ValueError("checkpoint decision_packet_refs contains duplicates")
    return normalized


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=None,
        debug=False,
        config: dict[str, Any] = None,
        callbacks: list | None = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []
        if selected_analysts is None:
            selected_analysts = ["market", "social", "news", "fundamentals"]
        self.selected_analysts = tuple(selected_analysts)
        self._checkpoint_shape = {
            "schema_version": self.config.get(
                "checkpoint_signature_schema_version",
                CHECKPOINT_SIGNATURE_SCHEMA_VERSION,
            ),
            "selected_analysts": self.selected_analysts,
            "max_debate_rounds": self.config["max_debate_rounds"],
            "max_risk_discuss_rounds": self.config["max_risk_discuss_rounds"],
            "analyst_concurrency_limit": self.config.get(
                "analyst_concurrency_limit",
                1,
            ),
            "tool_free_analysts": tuple(
                sorted(set(self.config.get("tool_free_analysts", [])))
            ),
            "source_revision": self.config.get("checkpoint_source_revision"),
            "packet_handoff_schema_version": PACKET_HANDOFF_SCHEMA_VERSION,
        }

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        # Initialize LLMs with provider-specific thinking configuration
        llm_kwargs = self._get_provider_kwargs()

        # Add callbacks to kwargs if provided (passed to LLM constructor)
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        deep_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()
        
        self.memory_log = TradingMemoryLog(self.config)

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self._checkpoint_shape["max_debate_rounds"],
            max_risk_discuss_rounds=self._checkpoint_shape[
                "max_risk_discuss_rounds"
            ],
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.conditional_logic,
            analyst_concurrency_limit=self._checkpoint_shape[
                "analyst_concurrency_limit"
            ],
            tool_free_analysts=set(self._checkpoint_shape["tool_free_analysts"]),
            ledger_root=(
                Path(self.config["results_dir"])
                / "control_plane"
                / "decisions"
            ),
            evidence_root=Path(self.config["results_dir"]),
        )

        self.propagator = Propagator(
            max_recur_limit=self.config.get("max_recur_limit", 100),
            run_signature_factory=self._run_signature,
        )
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Set up the graph: keep the workflow for recompilation with a checkpointer.
        self.workflow = self.graph_setup.setup_graph(self.selected_analysts)
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None

    def _get_provider_kwargs(self) -> dict[str, Any]:
        """Get provider-specific kwargs for LLM client creation."""
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        timeout_seconds = self.config.get("llm_timeout_seconds")
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds

        max_retries = self.config.get("llm_max_retries")
        if max_retries is not None:
            if type(max_retries) is not int or max_retries < 0:
                raise ValueError(
                    "llm_max_retries must be a non-negative integer, "
                    f"got {max_retries!r}"
                )
            kwargs["max_retries"] = max_retries

        max_output_tokens = self.config.get("llm_max_output_tokens")
        if max_output_tokens is not None:
            if provider == "google":
                kwargs["max_output_tokens"] = max_output_tokens
            else:
                kwargs["max_tokens"] = max_output_tokens

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level

        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort

        elif provider == "anthropic":
            effort = self.config.get("anthropic_effort")
            if effort:
                kwargs["effort"] = effort

        elif provider == "ollama":
            ollama_options = {
                "temperature": self.config.get("ollama_temperature"),
                "max_tokens": self.config.get("ollama_max_completion_tokens"),
                "top_p": self.config.get("ollama_top_p"),
                "presence_penalty": self.config.get("ollama_presence_penalty"),
                "extra_body": self.config.get("ollama_extra_body"),
            }
            kwargs.update(
                {key: value for key, value in ollama_options.items() if value is not None}
            )

        return kwargs

    def _create_tool_nodes(self) -> dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods."""
        return {
            "market": ToolNode(
                [
                    # Core stock data tools
                    get_stock_data,
                    # Technical indicators
                    get_indicators,
                    # Official macro/rates context
                    get_macro_context,
                    # Event and microstructure context
                    get_supplemental_market_context,
                ]
            ),
            "social": ToolNode(
                [
                    # News tools for social media analysis
                    get_news,
                    get_sentiment_context,
                ]
            ),
            "news": ToolNode(
                [
                    # News and insider information
                    get_news,
                    get_global_news,
                    get_macro_context,
                    get_supplemental_market_context,
                    get_insider_transactions,
                ]
            ),
            "fundamentals": ToolNode(
                [
                    # Fundamental analysis tools
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                ]
            ),
        }

    def _resolve_benchmark(self, ticker: str) -> str:
        """Pick the benchmark ticker for alpha calculation against ``ticker``.

        ``config["benchmark_ticker"]`` overrides everything when set; otherwise
        the suffix map matches the ticker's exchange suffix (e.g. ``.T`` for
        Tokyo). US-listed tickers without a dotted suffix fall through to the
        empty-suffix entry (SPY by default). Unrecognised suffixes (including
        US tickers with dots like ``BRK.B``) also fall back to the empty-suffix
        entry, which is the right default because the alpha calculation works
        in USD.
        """
        explicit = self.config.get("benchmark_ticker")
        if explicit:
            return explicit
        benchmark_map = self.config.get("benchmark_map", {})
        ticker_upper = ticker.upper()
        for suffix, benchmark in benchmark_map.items():
            if suffix and ticker_upper.endswith(suffix.upper()):
                return benchmark
        return benchmark_map.get("", "SPY")

    def _fetch_returns(
        self, ticker: str, trade_date: str, holding_days: int = 5,
        benchmark: str = "SPY",
    ) -> tuple[float | None, float | None, int | None]:
        """Fetch raw and alpha return for ticker over holding_days from trade_date.

        ``benchmark`` is the index used as the alpha baseline (resolved by the
        caller via ``_resolve_benchmark``). Returns ``(raw_return, alpha_return,
        actual_holding_days)`` or ``(None, None, None)`` if price data is
        unavailable (too recent, delisted, or network error).
        """
        try:
            start = datetime.strptime(trade_date, "%Y-%m-%d")
            end = start + timedelta(days=holding_days + 7)  # buffer for weekends/holidays
            # Overnight planning can run before the future holding window exists.
            # Clamp the yfinance request so weekend/future-dated checks do not
            # produce noisy "possibly delisted" warnings for otherwise valid symbols.
            latest_available_end = datetime.now() + timedelta(days=1)
            if end > latest_available_end:
                end = latest_available_end
            if end <= start:
                return None, None, None
            end_str = end.strftime("%Y-%m-%d")

            stock = yf.Ticker(ticker).history(start=trade_date, end=end_str)
            bench = yf.Ticker(benchmark).history(start=trade_date, end=end_str)

            if len(stock) < 2 or len(bench) < 2:
                return None, None, None

            actual_days = min(holding_days, len(stock) - 1, len(bench) - 1)
            raw = float(
                (stock["Close"].iloc[actual_days] - stock["Close"].iloc[0])
                / stock["Close"].iloc[0]
            )
            bench_ret = float(
                (bench["Close"].iloc[actual_days] - bench["Close"].iloc[0])
                / bench["Close"].iloc[0]
            )
            alpha = raw - bench_ret
            return raw, alpha, actual_days
        except Exception as e:
            logger.warning(
                "Could not resolve outcome for %s on %s vs %s (will retry next run): %s",
                ticker, trade_date, benchmark, e,
            )
            return None, None, None

    def _resolve_pending_entries(self, ticker: str) -> None:
        """Resolve pending log entries for ticker at the start of a new run.

        Fetches returns for each same-ticker pending entry, generates reflections,
        then writes all updates in a single atomic batch write to avoid redundant I/O.
        Skips entries whose price data is not yet available (too recent or delisted).

        Trade-off: only same-ticker entries are resolved per run.  Entries for
        other tickers accumulate until that ticker is run again.
        """
        pending = [e for e in self.memory_log.get_pending_entries() if e["ticker"] == ticker]
        if not pending:
            return

        benchmark = self._resolve_benchmark(ticker)
        updates = []
        for entry in pending:
            raw, alpha, days = self._fetch_returns(
                ticker, entry["date"], benchmark=benchmark,
            )
            if raw is None:
                continue  # price not available yet — try again next run
            reflection = self.reflector.reflect_on_final_decision(
                final_decision=entry.get("decision", ""),
                raw_return=raw,
                alpha_return=alpha,
                benchmark_name=benchmark,
            )
            updates.append({
                "ticker": ticker,
                "trade_date": entry["date"],
                "raw_return": raw,
                "alpha_return": alpha,
                "holding_days": days,
                "reflection": reflection,
            })

        if updates:
            self.memory_log.batch_update_with_outcomes(updates)

    def _run_signature(self, asset_type: str) -> str:
        """Return the canonical allowlisted identity of this decision graph."""
        shape = self._checkpoint_shape
        schema_version = shape["schema_version"]
        if type(schema_version) is not int or schema_version < 1:
            raise ValueError(
                "checkpoint_signature_schema_version must be a positive integer"
            )

        source_revision = shape["source_revision"]
        if source_revision is not None:
            valid_revision = (
                isinstance(source_revision, str)
                and bool(source_revision)
                and source_revision == source_revision.strip()
                and not source_revision.lower().endswith("-dirty")
                and all(
                    character.isalnum() or character in "._-"
                    for character in source_revision
                )
            )
            if not valid_revision:
                raise ValueError(
                    "checkpoint_source_revision must be a clean revision token"
                )

        packet_handoff_schema_version = shape["packet_handoff_schema_version"]
        if (
            type(packet_handoff_schema_version) is not int
            or packet_handoff_schema_version < 1
        ):
            raise ValueError(
                "packet_handoff_schema_version must be a positive integer"
            )

        payload = {
            "schema_version": schema_version,
            "selected_analysts": list(shape["selected_analysts"]),
            "asset_type": asset_type,
            "max_debate_rounds": shape["max_debate_rounds"],
            "max_risk_discuss_rounds": shape["max_risk_discuss_rounds"],
            "analyst_concurrency_limit": shape["analyst_concurrency_limit"],
            "tool_free_analysts": list(shape["tool_free_analysts"]),
            "source_revision": source_revision,
            "packet_handoff_schema_version": packet_handoff_schema_version,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def propagate(self, company_name, trade_date, asset_type: str = "stock"):
        """Run the trading agents graph for a company on a specific date.

        ``asset_type`` selects between the stock pipeline (default) and the
        crypto pipeline (``"crypto"``) shipped in #567 — the CLI auto-detects
        from the ticker; programmatic callers pass it explicitly. When
        ``checkpoint_enabled`` is set in config, the graph is recompiled with
        a per-ticker SqliteSaver so a crashed run can resume from the last
        successful node only under the same ticker, date, and graph shape.
        """
        checkpoint_signature = self._run_signature(asset_type)
        if not isinstance(checkpoint_signature, str):
            if isinstance(self, TradingAgentsGraph):
                raise ValueError("graph run signature must be a string")
            # Preserve legacy duck-typed callers of this unbound method. Real
            # TradingAgentsGraph instances always use the frozen graph shape.
            checkpoint_signature = "standalone-v1"

        self.ticker = company_name

        # Resolve any pending memory-log entries for this ticker before the pipeline runs.
        self._resolve_pending_entries(company_name)

        # Recompile with a checkpointer if the user opted in.
        if self.config.get("checkpoint_enabled"):
            self._checkpointer_ctx = get_checkpointer(
                self.config["data_cache_dir"], company_name
            )
            saver = self._checkpointer_ctx.__enter__()
            self.graph = self.workflow.compile(checkpointer=saver)

            step = checkpoint_step(
                self.config["data_cache_dir"],
                company_name,
                str(trade_date),
                checkpoint_signature,
            )
            if step is not None:
                logger.info(
                    "Resuming from step %d for %s on %s", step, company_name, trade_date
                )
            else:
                logger.info("Starting fresh for %s on %s", company_name, trade_date)

        try:
            return self._run_graph(
                company_name,
                trade_date,
                asset_type=asset_type,
                checkpoint_signature=checkpoint_signature,
            )
        finally:
            if self._checkpointer_ctx is not None:
                self._checkpointer_ctx.__exit__(None, None, None)
                self._checkpointer_ctx = None
                self.graph = self.workflow.compile()

    def _run_graph(
        self,
        company_name,
        trade_date,
        asset_type: str = "stock",
        checkpoint_signature: str | None = None,
    ):
        """Execute the graph and write the resulting state to disk and memory log."""
        if checkpoint_signature is None:
            checkpoint_signature = self._run_signature(asset_type)
        expected_run_id = build_graph_run_id(
            company_name,
            str(trade_date),
            asset_type,
            checkpoint_signature,
        )
        args = self.propagator.get_graph_args()
        invocation_state = None
        checkpoint_values: Mapping[str, Any] | None = None

        # Only an identical ticker, date, and graph-shape signature may resume.
        if self.config.get("checkpoint_enabled"):
            tid = thread_id(company_name, str(trade_date), checkpoint_signature)
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid
            snapshot = self.graph.get_state(args["config"])
            raw_values = getattr(snapshot, "values", None)
            if raw_values:
                if not isinstance(raw_values, Mapping):
                    raise ValueError("checkpoint values must be a mapping")
                checkpoint_values = raw_values
                if raw_values.get("run_id") != expected_run_id:
                    raise ValueError(
                        "checkpoint run_id does not match the logical graph run"
                    )
                _checkpoint_run_start(raw_values.get("run_started_at"))
                _checkpoint_packet_refs(
                    raw_values.get("decision_packet_refs"),
                    run_id=expected_run_id,
                )
                if not isinstance(raw_values.get("learning_context"), str):
                    raise ValueError(
                        "checkpoint learning_context must be a string"
                    )

        if checkpoint_values is None:
            # Construct exactly one fresh state only after checkpoint inspection.
            past_context = self.memory_log.get_past_context(company_name)
            invocation_state = self.propagator.create_initial_state(
                company_name,
                trade_date,
                asset_type=asset_type,
                past_context=past_context,
                run_id=expected_run_id,
            )

        if self.debug:
            trace = []
            for chunk in self.graph.stream(invocation_state, **args):
                if len(chunk["messages"]) == 0:
                    pass
                else:
                    chunk["messages"][-1].pretty_print()
                    trace.append(chunk)
            # Streamed chunks are per-node deltas. Merge them so the returned
            # state matches what graph.invoke() yields in the non-debug path.
            final_state = {}
            for chunk in trace:
                final_state.update(chunk)
        else:
            final_state = self.graph.invoke(invocation_state, **args)

        # Store current state for reflection.
        self.curr_state = final_state

        # Log state to disk.
        self._log_state(trade_date, final_state)

        # Store decision for deferred reflection on the next same-ticker run.
        self.memory_log.store_decision(
            ticker=company_name,
            trade_date=trade_date,
            final_trade_decision=final_state["final_trade_decision"],
        )

        # Clear checkpoint on successful completion to avoid stale state.
        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(
                self.config["data_cache_dir"],
                company_name,
                str(trade_date),
                checkpoint_signature,
            )

        return final_state, self.process_signal(final_state["final_trade_decision"])

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "history": final_state["investment_debate_state"]["history"],
                "current_response": final_state["investment_debate_state"][
                    "current_response"
                ],
                "judge_decision": final_state["investment_debate_state"][
                    "judge_decision"
                ],
            },
            "trader_investment_decision": final_state["trader_investment_plan"],
            "risk_debate_state": {
                "aggressive_history": final_state["risk_debate_state"]["aggressive_history"],
                "conservative_history": final_state["risk_debate_state"]["conservative_history"],
                "neutral_history": final_state["risk_debate_state"]["neutral_history"],
                "history": final_state["risk_debate_state"]["history"],
                "judge_decision": final_state["risk_debate_state"]["judge_decision"],
            },
            "investment_plan": final_state["investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
        }

        # Save to file. Reject ticker values that would escape the
        # results directory when joined as a path component.
        safe_ticker = safe_ticker_component(self.ticker)
        directory = Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_states_log_{trade_date}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.log_states_dict[str(trade_date)], f, indent=4)

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal)
