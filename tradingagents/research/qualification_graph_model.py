"""Strict model adapter for an observed full-role benchmark, with no retries."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, message_to_dict
from pydantic import Field

from tradingagents.agents.schemas import PortfolioDecision
from tradingagents.research.qualification_benchmark import (
    ResearchQualificationBenchmarkError,
    _bytes,
    _sensitive_outbound_value,
    _text,
    write_research_qualification_receipt,
)


class BenchmarkPortfolioDecision(PortfolioDecision):
    benchmark_answer: str = Field(
        description="Only the answer to the registered benchmark query, from the graph reports; UNAVAILABLE if insufficient.",
    )


class GraphModelTelemetry(BaseCallbackHandler):
    """Capture actual callbacks, not requested settings masquerading as usage."""

    raise_error = True

    def __init__(self, spec, expected_roles, response_root: Path):
        self.spec = spec
        self.expected_roles = tuple(expected_roles)
        self.calls = []
        self.pending = None
        self.response_root = response_root
        self.last_response = None

    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kwargs):
        if self.pending is not None or len(messages) != 1:
            raise ResearchQualificationBenchmarkError("full-graph model calls must be sequential")
        role = (metadata or {}).get("langgraph_node")
        if type(role) is not str or not role:
            raise ResearchQualificationBenchmarkError("actual graph role telemetry is unavailable")
        if len(self.calls) >= len(self.expected_roles) or role != self.expected_roles[len(self.calls)]:
            raise ResearchQualificationBenchmarkError("full-graph role order or call limit differs from registration")
        payload = [message_to_dict(message) for message in messages[0]]
        if _sensitive_outbound_value(payload):
            raise ResearchQualificationBenchmarkError("outbound graph prompt contains sensitive text")
        self.pending = {
            "callback_run_id": str(run_id), "role": role,
            "prompt_sha256": hashlib.sha256(_bytes(payload)).hexdigest(),
            "started_ns": time.monotonic_ns(),
        }

    def on_llm_end(self, response, *, run_id, **kwargs):
        if self.pending is None or self.pending["callback_run_id"] != str(run_id):
            raise ResearchQualificationBenchmarkError("full-graph callback continuity is invalid")
        if len(response.generations) != 1 or len(response.generations[0]) != 1:
            raise ResearchQualificationBenchmarkError("full-graph model completion is ambiguous")
        message = getattr(response.generations[0][0], "message", None)
        metadata, usage = getattr(message, "response_metadata", None), getattr(message, "usage_metadata", None)
        if not isinstance(metadata, Mapping) or not isinstance(usage, Mapping):
            raise ResearchQualificationBenchmarkError("full-graph response telemetry is unavailable")
        actual = tuple(metadata.get(key) for key in ("provider", "model_name", "system_fingerprint", "route"))
        expected = tuple(self.spec[key] for key in ("provider", "model", "revision", "route"))
        if actual != expected or metadata.get("fallback_used") is not False:
            raise ResearchQualificationBenchmarkError("full-graph observed route differs from registration")
        counts = [usage.get(key) for key in ("input_tokens", "output_tokens")]
        if any(type(value) is not int or value < 0 for value in counts):
            raise ResearchQualificationBenchmarkError("full-graph observed usage is invalid")
        outcome = _text(metadata.get("id"), "full-graph outcome id")
        if outcome in {row["outcome_id"] for row in self.calls}:
            raise ResearchQualificationBenchmarkError("full-graph outcome id is duplicated")
        if not isinstance(message, AIMessage):
            raise ResearchQualificationBenchmarkError("full-graph response is not an assistant message")
        # Retain the actual LangChain message representation, not an invented
        # HTTP body. Copy before downstream parsers can change mutable fields.
        captured = json.loads(_bytes(message_to_dict(message)))
        if _sensitive_outbound_value(captured):
            raise ResearchQualificationBenchmarkError("full-graph response contains sensitive text")
        payload = {"outcome_id": outcome, "message": captured}
        response_path = f"model-response-{len(self.calls) + 1:04d}.json"
        write_research_qualification_receipt(payload, self.response_root / response_path)
        response_sha256 = hashlib.sha256(_bytes(payload) + b"\n").hexdigest()
        cost = sum(Decimal(count) * Decimal(self.spec[key]) for count, key in zip(
            counts, ("input_price_per_million_usd", "output_price_per_million_usd"), strict=True,
        )) / Decimal(1_000_000)
        pending = dict(self.pending)
        started = pending.pop("started_ns")
        self.calls.append({
            **pending, "outcome_id": outcome,
            "response_path": response_path, "response_sha256": response_sha256,
            "actual_provider": actual[0], "actual_model": actual[1],
            "actual_revision": actual[2], "route": actual[3], "fallback_used": False,
            "input_tokens": counts[0], "output_tokens": counts[1],
            "cost_usd": "0" if cost.is_zero() else format(cost.normalize(), "f"),
            "latency_ms": max(0, (time.monotonic_ns() - started) // 1_000_000),
        })
        self.pending = None
        self.last_response = captured


class StrictGraphModel:
    """Keep the ordinary graph's fallback handlers from making another call."""

    def __init__(self, llm, telemetry: GraphModelTelemetry, question: str):
        self.llm, self.telemetry, self.question = llm, telemetry, question
        self.failed = False
        self.benchmark_answer = None

    def _call(self, runner, prompt, schema=None):
        if self.failed:
            raise ResearchQualificationBenchmarkError("full-graph fallback/retry is prohibited")
        try:
            framed = _bytes({
                "role_prompt": prompt,
                "benchmark_task": {
                    "adapter_query": self.question,
                    "instruction": "Preserve your role. The final Portfolio Manager must answer this query in benchmark_answer from graph reports, or UNAVAILABLE; no external data or authority.",
                },
            }).decode()
            if _sensitive_outbound_value({"prompt": framed}):
                raise ResearchQualificationBenchmarkError("outbound graph prompt contains sensitive text")
            before = len(self.telemetry.calls)
            result = runner.invoke(framed, config={"callbacks": [self.telemetry]})
            if len(self.telemetry.calls) != before + 1 or self.telemetry.pending is not None:
                raise ResearchQualificationBenchmarkError("full-graph actual callback receipt is missing")
            if schema is None:
                if not isinstance(result, AIMessage) or result.tool_calls or result.invalid_tool_calls:
                    raise ResearchQualificationBenchmarkError("full-graph plain role requested tools")
                self._validate_observed_message(result)
                return result
            if not isinstance(result, Mapping) or result.get("parsing_error") is not None:
                raise ResearchQualificationBenchmarkError("full-graph structured response failed")
            parsed = result.get("parsed")
            if not isinstance(parsed, schema):
                raise ResearchQualificationBenchmarkError("full-graph structured response schema is invalid")
            raw = result.get("raw")
            if not isinstance(raw, AIMessage) or raw.invalid_tool_calls or len(raw.tool_calls) > 1:
                raise ResearchQualificationBenchmarkError("full-graph structured tool envelope is invalid")
            if raw.tool_calls and raw.tool_calls[0]["name"] != schema.__name__:
                raise ResearchQualificationBenchmarkError("full-graph structured tool identity is invalid")
            captured = self._validate_observed_message(raw)["data"]
            if captured["tool_calls"]:
                arguments = captured["tool_calls"][0]["args"]
            elif type(captured["content"]) is str:
                arguments = json.loads(captured["content"])
            else:
                raise ResearchQualificationBenchmarkError("full-graph structured response has no auditable JSON")
            if schema.model_validate(arguments).model_dump(mode="json") != parsed.model_dump(mode="json"):
                raise ResearchQualificationBenchmarkError("full-graph parsed output differs from retained response")
            if schema is BenchmarkPortfolioDecision:
                self.benchmark_answer = _text(parsed.benchmark_answer, "full-graph benchmark answer")
            return parsed
        except Exception as exc:
            self.failed = True
            raise ResearchQualificationBenchmarkError("full-graph model call failed without fallback") from exc

    def _validate_observed_message(self, message):
        captured = self.telemetry.last_response
        if captured is None or _bytes(message_to_dict(message)) != _bytes(captured):
            raise ResearchQualificationBenchmarkError("full-graph returned message differs from its actual callback")
        return captured

    def invoke(self, prompt):
        return self._call(self.llm, prompt)

    def with_structured_output(self, schema):
        effective = BenchmarkPortfolioDecision if schema is PortfolioDecision else schema
        try:
            runner = self.llm.with_structured_output(effective, include_raw=True)
        except Exception as exc:
            self.failed = True
            raise ResearchQualificationBenchmarkError("full-graph requires structured output support") from exc
        owner = self

        class StructuredRole:
            def invoke(self, prompt):
                return owner._call(runner, prompt, effective)

        return StructuredRole()
