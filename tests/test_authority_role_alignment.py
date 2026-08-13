import ast
import json
from collections import Counter
from pathlib import Path

import pytest

from tradingagents.orchestration.authority import ActionClass, authority_for

ROOT = Path(__file__).parents[1]
EXPECTED_AUTOMATIONS = {
    "tradingagents-automation-sleep-controller": "schedule_controller",
    "tradingagents-automation-wake-controller": "schedule_controller",
    "tradingagents-autonomous-execution-board": "portfolio_executive",
    "tradingagents-autonomous-safety-sentinel": "integrity_verifier",
    "tradingagents-autonomous-self-healer": "reliability_controller",
    "tradingagents-daily-report": "reporting_utility",
    "tradingagents-market-supervisor": "execution_operator",
    "tradingagents-overnight-research": "strategy_learning",
    "tradingagents-paper-tournament": "strategy_learning",
    "tradingagents-preopen-validation": "integrity_verifier",
}
MACHINE_ROLE_ACTIONS = {
    "strategy_learning": {"strategy_change", "promotion_change"},
    "portfolio_executive": {"trade_decision", "risk_change"},
    "reliability_controller": {"repair", "rearm_request"},
    "integrity_verifier": {"freeze", "verify", "rearm_issue"},
    "execution_operator": {"order_submit"},
}
UTILITY_ROLES = {"schedule_controller", "reporting_utility"}
BROKER_WRITE_EFFECTS = {
    "broker_order_write",
    "submit_order",
    "cancel_order",
    "replace_order",
}
EXPECTED_COMMAND_FAMILIES = {
    "strategy_learning": [
        "alpaca plan-overnight --json-output",
        "alpaca paper-tournament run --all --dry-run --json-output",
        "policy sync-promotion",
    ],
    "portfolio_executive": [
        "research execution-board-review --json-output",
    ],
    "reliability_controller": [
        "research self-heal-handoff --json-output",
        "research self-heal-plan --execute-safe --json-output",
    ],
    "integrity_verifier": [
        "alpaca check",
        "alpaca reconcile-symbol-incident",
        "policy freeze-live",
        "policy recover-incident",
    ],
    "execution_operator": [
        "scripts/mac/ta_job.sh hourly",
    ],
    "schedule_controller": [
        "automation status",
        "research controller-patrol --json-output",
    ],
    "reporting_utility": [
        "scripts/mac/ta_job.sh daily-report",
        "scripts/mac/ta_job.sh deliver-outbox",
    ],
}


def _registry():
    path = ROOT / "config" / "automation_roles.json"
    assert path.exists(), "automation role registry must be versioned in config"
    return json.loads(path.read_text(encoding="utf-8"))


def test_role_registry_matches_the_exact_charter_owners_and_ten_automations():
    registry = _registry()

    assert registry["schema_version"] == 1
    assert registry["automations"] == EXPECTED_AUTOMATIONS
    assert set(registry["roles"]) == set(MACHINE_ROLE_ACTIONS) | UTILITY_ROLES
    all_machine_actions = set().union(*MACHINE_ROLE_ACTIONS.values())
    for role, actions in MACHINE_ROLE_ACTIONS.items():
        record = registry["roles"][role]
        assert set(record["allowed_actions"]) == actions
        assert record["kind"] == "business"
        assert record["command_family"] == EXPECTED_COMMAND_FAMILIES[role]
        expected_forbidden = all_machine_actions - actions
        if role == "execution_operator":
            expected_forbidden |= {"recovery_order_submit"}
        else:
            expected_forbidden |= BROKER_WRITE_EFFECTS
        assert set(record["forbidden_effects"]) == expected_forbidden
    assert (
        registry["roles"]["strategy_learning"]["display_name"]
        == "Research & Strategy Council"
    )


def test_utility_roles_have_zero_business_authority():
    registry = _registry()

    for role in UTILITY_ROLES:
        record = registry["roles"][role]
        assert record["kind"] == "utility"
        assert record["allowed_actions"] == []
        assert record["command_family"] == EXPECTED_COMMAND_FAMILIES[role]
        assert set(record["forbidden_effects"]) == (
            set().union(*MACHINE_ROLE_ACTIONS.values())
            | BROKER_WRITE_EFFECTS
        )


def test_each_business_action_has_exactly_one_registry_owner():
    registry = _registry()
    machine_actions = {
        action.value
        for action in ActionClass
        if authority_for(action).human_required is False
    }
    owners = {
        action: [
            role
            for role, record in registry["roles"].items()
            if action in record["allowed_actions"]
        ]
        for action in machine_actions
    }

    assert all(len(action_owners) == 1 for action_owners in owners.values())
    assert {
        action: action_owners[0] for action, action_owners in owners.items()
    } == {
        action: authority_for(action).owner_role for action in machine_actions
    }


@pytest.mark.parametrize(
    ("role", "forbidden"),
    [
        (
            "reliability_controller",
            {"verify", "rearm_issue", "order_submit"},
        ),
        (
            "integrity_verifier",
            {"repair", "rearm_request", "order_submit"},
        ),
        (
            "strategy_learning",
            {
                "freeze",
                "repair",
                "verify",
                "rearm_request",
                "rearm_issue",
                "order_submit",
            },
        ),
    ],
)
def test_role_contract_does_not_cross_the_chain_of_command(role, forbidden):
    allowed = set(_registry()["roles"][role]["allowed_actions"])

    assert allowed.isdisjoint(forbidden)


def test_execution_requires_bounded_paper_and_separate_normal_trade_inputs():
    portfolio = _registry()["roles"]["portfolio_executive"]
    execution = _registry()["roles"]["execution_operator"]

    assert portfolio["required_outputs"] == ["authorized_normal_trade_intent"]
    assert execution["allowed_actions"] == ["order_submit"]
    assert execution["required_inputs"] == [
        "authorized_paper_order_request",
        "authorized_normal_trade_intent",
        "normal_live_activation_receipt",
    ]


_EXCLUDED_PRODUCTION_PATH_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "generated",
    "node_modules",
}
_LIVE_WRITE_CALLER_CLASSIFICATIONS = {
        ("cli/main.py", "_alpaca_clients", "AlpacaSettings.from_env"): "hard-disabled",
        ("cli/main.py", "_alpaca_clients", "live_client.assert_expected_mode"): "hard-disabled",
        ("cli/main.py", "_alpaca_live_client", "definition"): "hard-disabled",
        ("cli/main.py", "_alpaca_live_client", "AlpacaSettings.from_env"): "hard-disabled",
        ("cli/main.py", "_alpaca_live_client", "live_client.assert_expected_mode"): "hard-disabled",
        ("cli/main.py", "alpaca_reconcile_orcl_incident", "_alpaca_live_client"): "hard-disabled",
        ("cli/main.py", "alpaca_reconcile_symbol_incident", "_alpaca_live_client"): "hard-disabled",
        ("cli/main.py", "alpaca_paper_tournament_run", "paper_client.submit_order"): "paper-only",
        ("cli/main.py", "alpaca_supervise_hourly", "paper_client.submit_order"): "paper-only",
        ("tradingagents/brokers/alpaca.py", "AlpacaRestClient.submit_order", "definition"): "exact-intent-boundary",
        ("tradingagents/brokers/alpaca.py", "AlpacaRestClient._collect_normal_live_reconciliation_reads", "self.assert_expected_mode"): "exact-intent-boundary",
        ("tradingagents/brokers/alpaca.py", "AlpacaRestClient.list_orders", "order-endpoint-primitive"): "read-only",
        ("tradingagents/brokers/alpaca.py", "_AlpacaTransport.get_json", "self.__session.request"): "read-only",
        ("tradingagents/brokers/alpaca.py", "_AlpacaTransport.post_order_json", "definition"): "internal-transport",
        ("tradingagents/brokers/alpaca.py", "_AlpacaTransport.post_order_json", "self.__session.request"): "internal-transport",
        ("tradingagents/brokers/alpaca.py", "AlpacaRestClient._post_normal_live_order_payload", "definition"): "exact-intent-boundary",
        ("tradingagents/brokers/alpaca.py", "AlpacaRestClient._post_normal_live_order_payload", "self.assert_expected_mode"): "exact-intent-boundary",
        ("tradingagents/brokers/alpaca.py", "AlpacaRestClient._post_normal_live_order_payload", "self.__transport.post_order_json"): "exact-intent-boundary",
        ("tradingagents/brokers/alpaca.py", "AlpacaRestClient._post_paper_order_payload", "self.__transport.post_order_json"): "paper-only",
        ("tradingagents/brokers/alpaca.py", "execute_order_pairs", "definition"): "hard-disabled",
        ("tradingagents/brokers/alpaca.py", "execute_order_pairs", "live_client.assert_expected_mode"): "hard-disabled",
        ("tradingagents/brokers/alpaca.py", "execute_order_pairs", "paper_client.submit_order"): "hard-disabled",
        ("tradingagents/brokers/alpaca.py", "execute_order_pairs", "live_client.submit_order"): "hard-disabled",
        ("tradingagents/brokers/alpaca.py", "execute_paper_orders", "paper_client.submit_order"): "paper-only",
        ("tradingagents/brokers/alpaca_supervisor.py", "submit_authorized_normal_live_order", "live_client.submit_order"): "exact-intent-boundary",
        ("tradingagents/execution/reconcile.py", "_owned_normal_live_broker_post", "_post_normal_live_order_payload"): "exact-intent-boundary",
    }


def _production_python_paths(root: Path = ROOT) -> list[Path]:
    paths = []
    for directory in (root / "tradingagents", root / "cli"):
        if not directory.exists():
            continue
        for path in directory.rglob("*.py"):
            if _EXCLUDED_PRODUCTION_PATH_PARTS.isdisjoint(path.parts):
                paths.append(path)
    return sorted(paths)


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_call_name(node.value)}.{node.attr}"
    return "<dynamic>"


def _is_raw_http_transport_call(node: ast.expr, name: str) -> bool:
    """Identify direct HTTP transport methods outside named application APIs.

    The inventory must see a potentially order-writing request before trying to
    prove its URL is safe: a formatted or concatenated URL must not evade the
    source gate merely because it is not an ``ast.Constant``.
    """

    if name.endswith("._request"):
        return True
    method = name.rsplit(".", 1)[-1]
    if method not in {"delete", "patch", "post", "put", "request", "send"}:
        return False
    receiver_parts = name.rsplit(".", 1)[0].split(".")
    receiver = node.value if isinstance(node, ast.Attribute) else None
    fluent_constructor = (
        _call_name(receiver.func)
        if isinstance(receiver, ast.Call)
        else None
    )
    return (
        name.startswith(("requests.", "httpx.", "urllib3.", "aiohttp."))
        or any(part.endswith("session") for part in receiver_parts)
        or any(part.endswith("transport") for part in receiver_parts)
        or fluent_constructor
        in {
            "requests.Session",
            "httpx.AsyncClient",
            "httpx.Client",
            "urllib3.PoolManager",
            "aiohttp.ClientSession",
        }
    )


_HTTP_MUTATION_METHODS = frozenset({"delete", "patch", "post", "put", "request", "send"})
_MUTATING_HTTP_VERBS = frozenset({"DELETE", "PATCH", "POST", "PUT"})


def _resolve_import_alias(name: str, aliases: dict[str, str]) -> str:
    head, *tail = name.split(".")
    target = aliases.get(head)
    if target is None:
        return name
    return ".".join((target, *tail))


def _is_potentially_mutating_urllib_request(node: ast.Call, name: str) -> bool:
    if name != "urllib.request.Request":
        return False
    method = next((keyword.value for keyword in node.keywords if keyword.arg == "method"), None)
    if method is None and len(node.args) >= 6:
        method = node.args[5]
    if method is None:
        data = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "data"),
            node.args[1] if len(node.args) >= 2 else None,
        )
        return data is not None and not (
            isinstance(data, ast.Constant) and data.value is None
        )
    if not isinstance(method, ast.Constant) or not isinstance(method.value, str):
        return True
    return method.value.upper() in _MUTATING_HTTP_VERBS


def _production_http_mutation_occurrences(
    root: Path = ROOT,
) -> list[tuple[str, int, str, str]]:
    """Inventory every raw production HTTP mutation without trusting aliases or URLs.

    Attribute mutations are deliberately receiver-agnostic: a renamed requests
    session, a custom client, or a dynamically built URL must be classified
    before source can use it.  urllib is tracked from a potentially mutating
    Request through its urlopen/opener dispatch.
    """

    occurrences: list[tuple[str, int, str, str]] = []

    class _HttpMutationVisitor(ast.NodeVisitor):
        def __init__(self, relative_path: str):
            self.relative_path = relative_path
            self.scope: list[str] = []
            self.scope_kinds: list[str] = ["module"]
            self.import_aliases: dict[str, str] = {}
            self.urllib_requests: list[set[str]] = [set()]
            self.raw_http_aliases: list[dict[str, str]] = [{}]
            self.urllib_dispatch_aliases: list[set[str]] = [set()]

        def _scope_name(self) -> str:
            return ".".join(self.scope)

        def _record(self, node: ast.AST, name: str) -> None:
            occurrences.append((self.relative_path, node.lineno, self._scope_name(), name))

        def _resolved_call_name(self, node: ast.expr) -> str:
            return _resolve_import_alias(_call_name(node), self.import_aliases)

        def _push_scope(self, name: str, kind: str, node: ast.AST) -> None:
            self.scope.append(name)
            self.scope_kinds.append(kind)
            self.urllib_requests.append(set())
            self.raw_http_aliases.append({})
            self.urllib_dispatch_aliases.append(set())
            self.generic_visit(node)
            self.urllib_dispatch_aliases.pop()
            self.raw_http_aliases.pop()
            self.urllib_requests.pop()
            self.scope_kinds.pop()
            self.scope.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._push_scope(node.name, "class", node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._push_scope(node.name, "function", node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.visit_FunctionDef(node)

        def visit_Import(self, node: ast.Import) -> None:
            for imported in node.names:
                if imported.asname:
                    self.import_aliases[imported.asname] = imported.name
                else:
                    # ``import urllib.request`` binds ``urllib``, not the
                    # final dotted component.  Preserve that Python binding
                    # so ``urllib.request.Request`` resolves canonically.
                    binding = imported.name.split(".", 1)[0]
                    self.import_aliases.setdefault(binding, binding)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            module = node.module or ""
            for imported in node.names:
                if imported.name == "*":
                    continue
                binding = imported.asname or imported.name
                self.import_aliases[binding] = f"{module}.{imported.name}".strip(".")

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self._remember_urllib_request(node.value, [node.target])
            self._remember_raw_http_alias(node.value, [node.target])
            self._remember_urllib_dispatch_alias(node.value, [node.target])
            self.generic_visit(node)

        def visit_Assign(self, node: ast.Assign) -> None:
            self._remember_urllib_request(node.value, node.targets)
            self._remember_raw_http_alias(node.value, node.targets)
            self._remember_urllib_dispatch_alias(node.value, node.targets)
            self.generic_visit(node)

        def _binding_scope_index(self, target: ast.expr) -> int:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                for index in range(len(self.scope_kinds) - 1, -1, -1):
                    if self.scope_kinds[index] == "class":
                        return index
            return -1

        def _bind_names(
            self, bindings: list[set[str]], targets: list[ast.expr]
        ) -> None:
            for target in targets:
                if isinstance(target, (ast.Name, ast.Attribute)):
                    bindings[self._binding_scope_index(target)].add(_call_name(target))

        def _bind_raw_http_aliases(
            self, method: str, targets: list[ast.expr]
        ) -> None:
            for target in targets:
                if isinstance(target, (ast.Name, ast.Attribute)):
                    self.raw_http_aliases[self._binding_scope_index(target)][
                        _call_name(target)
                    ] = method

        def _lookup_raw_http_alias(self, name: str) -> str | None:
            for frame in reversed(self.raw_http_aliases):
                if name in frame:
                    return frame[name]
            return None

        def _raw_http_mutation_method(self, node: ast.expr) -> str | None:
            name = _call_name(node)
            bound_method = self._lookup_raw_http_alias(name)
            if bound_method is not None:
                return bound_method
            resolved_name = self._resolved_call_name(node)
            method = resolved_name.rsplit(".", 1)[-1]
            if method not in _HTTP_MUTATION_METHODS:
                return None
            if isinstance(node, ast.Attribute):
                return method
            if isinstance(node, ast.Name) and resolved_name.startswith(
                ("requests.", "httpx.", "urllib3.", "aiohttp.")
            ):
                return method
            return None

        def _is_urllib_dispatch_callable(self, node: ast.expr) -> bool:
            name = _call_name(node)
            if any(name in names for names in reversed(self.urllib_dispatch_aliases)):
                return True
            resolved_name = self._resolved_call_name(node)
            return (
                resolved_name
                in {"urllib.request.urlopen", "urllib.request.OpenerDirector.open"}
                or (isinstance(node, ast.Attribute) and node.attr == "open")
            )

        @staticmethod
        def _urllib_dispatch_request_arguments(node: ast.Call) -> list[ast.expr]:
            return [
                *node.args[:1],
                *(
                    keyword.value
                    for keyword in node.keywords
                    if keyword.arg in {"url", "fullurl"}
                ),
            ]

        def _remember_urllib_request(
            self, value: ast.expr | None, targets: list[ast.expr]
        ) -> None:
            is_request = (
                isinstance(value, ast.Call)
                and _is_potentially_mutating_urllib_request(
                    value, self._resolved_call_name(value.func)
                )
            ) or self._is_tracked_urllib_request(value)
            if not is_request:
                return
            self._bind_names(self.urllib_requests, targets)

        def _remember_raw_http_alias(
            self, value: ast.expr | None, targets: list[ast.expr]
        ) -> None:
            if value is None:
                return
            method = self._raw_http_mutation_method(value)
            if method is not None:
                self._bind_raw_http_aliases(method, targets)

        def _remember_urllib_dispatch_alias(
            self, value: ast.expr | None, targets: list[ast.expr]
        ) -> None:
            if value is not None and self._is_urllib_dispatch_callable(value):
                self._bind_names(self.urllib_dispatch_aliases, targets)

        def _is_tracked_urllib_request(self, node: ast.expr | None) -> bool:
            if isinstance(node, ast.Call):
                return _is_potentially_mutating_urllib_request(
                    node, self._resolved_call_name(node.func)
                )
            if not isinstance(node, (ast.Name, ast.Attribute)):
                return False
            name = _call_name(node)
            return any(name in names for names in reversed(self.urllib_requests))

        def visit_Call(self, node: ast.Call) -> None:
            raw_http_method = self._raw_http_mutation_method(node.func)
            if raw_http_method is not None:
                self._record(node, f"raw-http-{raw_http_method}")
            elif (
                self._is_urllib_dispatch_callable(node.func)
                and any(
                    self._is_tracked_urllib_request(argument)
                    for argument in self._urllib_dispatch_request_arguments(node)
                )
            ):
                self._record(node, "raw-urllib-mutation-dispatch")
            self.generic_visit(node)

    for path in _production_python_paths(root):
        relative_path = path.relative_to(root).as_posix()
        visitor = _HttpMutationVisitor(relative_path)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
    return occurrences


_HTTP_MUTATION_CLASSIFICATIONS: dict[tuple[str, int, str, str], str] = {
    # These are deliberately exact source locations, rather than a module or
    # receiver allow-list.  A new raw write must get reviewed classification.
    ("cli/main.py", 5107, "_overnight_ticker_process_main", "raw-http-put"): (
        "non-trading-local-process-result-queue"
    ),
    ("cli/main.py", 5119, "_overnight_ticker_process_main", "raw-http-put"): (
        "non-trading-local-process-error-queue"
    ),
    ("tradingagents/brokers/alpaca.py", 70, "_AlpacaTransport.get_json", "raw-http-request"): (
        "approved-internal-alpaca-read-transport"
    ),
    ("tradingagents/brokers/alpaca.py", 83, "_AlpacaTransport.post_order_json", "raw-http-request"): (
        "approved-internal-alpaca-order-transport"
    ),
    ("tradingagents/dataflows/_official_common.py", 368, "_request_json", "raw-http-post"): (
        "non-trading-external-official-research-post"
    ),
    ("tradingagents/orchestration/n8n_api_sync.py", 171, "N8NDataTableApiClient.request", "raw-urllib-mutation-dispatch"): (
        "non-trading-external-n8n-data-table-generic-method-transport"
    ),
    ("tradingagents/orchestration/n8n_api_sync.py", 189, "N8NDataTableApiClient.list_data_tables", "raw-http-request"): (
        "non-trading-external-n8n-data-table-read"
    ),
    ("tradingagents/orchestration/n8n_api_sync.py", 193, "N8NDataTableApiClient.create_data_table", "raw-http-request"): (
        "non-trading-external-n8n-data-table-create"
    ),
    ("tradingagents/orchestration/n8n_api_sync.py", 196, "N8NDataTableApiClient.list_columns", "raw-http-request"): (
        "non-trading-external-n8n-data-table-read"
    ),
    ("tradingagents/orchestration/n8n_api_sync.py", 203, "N8NDataTableApiClient.create_column", "raw-http-request"): (
        "non-trading-external-n8n-data-table-create"
    ),
    ("tradingagents/orchestration/n8n_api_sync.py", 209, "N8NDataTableApiClient.list_rows", "raw-http-request"): (
        "non-trading-external-n8n-data-table-read"
    ),
    ("tradingagents/orchestration/n8n_api_sync.py", 223, "N8NDataTableApiClient.delete_all_rows", "raw-http-request"): (
        "non-trading-external-n8n-data-table-delete"
    ),
    ("tradingagents/orchestration/n8n_api_sync.py", 230, "N8NDataTableApiClient.insert_rows", "raw-http-request"): (
        "non-trading-external-n8n-data-table-insert"
    ),
    ("tradingagents/orchestration/n8n_evaluation_run_probe.py", 74, "N8NEvaluationRunProbeClient.request", "raw-urllib-mutation-dispatch"): (
        "non-trading-external-n8n-evaluation-generic-method-transport"
    ),
    ("tradingagents/orchestration/n8n_evaluation_run_probe.py", 91, "N8NEvaluationRunProbeClient.list_workflows", "raw-http-request"): (
        "non-trading-external-n8n-evaluation-read"
    ),
    ("tradingagents/orchestration/n8n_evaluation_run_probe.py", 106, "N8NEvaluationRunProbeClient.probe", "raw-urllib-mutation-dispatch"): (
        "non-trading-external-n8n-evaluation-generic-method-probe"
    ),
    ("tradingagents/orchestration/n8n_workflow_sync.py", 63, "N8NWorkflowApiClient.request", "raw-urllib-mutation-dispatch"): (
        "non-trading-external-n8n-workflow-generic-method-transport"
    ),
    ("tradingagents/orchestration/n8n_workflow_sync.py", 80, "N8NWorkflowApiClient.list_workflows", "raw-http-request"): (
        "non-trading-external-n8n-workflow-read"
    ),
    ("tradingagents/orchestration/n8n_workflow_sync.py", 85, "N8NWorkflowApiClient.create_workflow", "raw-http-request"): (
        "non-trading-external-n8n-workflow-create"
    ),
    ("tradingagents/orchestration/n8n_workflow_sync.py", 90, "N8NWorkflowApiClient.update_workflow", "raw-http-request"): (
        "non-trading-external-n8n-workflow-update"
    ),
}


def _assert_all_http_mutations_classified(
    occurrences: list[tuple[str, int, str, str]],
    classifications: dict[tuple[str, int, str, str], str],
) -> None:
    observed = Counter(occurrences)
    expected = Counter(classifications.keys())
    unknown = [
        f"{path}:{line}: {scope or '<module>'} -> {name}"
        for path, line, scope, name in occurrences
        if (path, line, scope, name) not in classifications
    ]
    missing = list((expected - observed).elements())
    duplicates = list((observed - expected).elements())
    assert not unknown and not missing and not duplicates, (
        "unclassified production HTTP mutation(s): "
        f"{unknown}; missing expected occurrences: {missing}; "
        f"duplicate occurrences: {duplicates}"
    )


def _live_write_occurrences(root: Path = ROOT) -> list[tuple[str, int, str, str]]:
    occurrences = []

    class _InventoryVisitor(ast.NodeVisitor):
        def __init__(self, relative_path: str):
            self.relative_path = relative_path
            self.scope: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            qualified = ".".join([*self.scope, node.name])
            if node.name in {
                "submit_order",
                "execute_order_pairs",
                "_alpaca_live_client",
                "_post_normal_live_order_payload",
                "_request",
                "post_order_json",
            }:
                occurrences.append((self.relative_path, node.lineno, qualified, "definition"))
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.visit_FunctionDef(node)

        def visit_Call(self, node: ast.Call) -> None:
            name = _call_name(node.func)
            has_paper_false = any(
                keyword.arg == "paper"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is False
                for keyword in node.keywords
            )
            is_raw_http_transport_call = _is_raw_http_transport_call(node.func, name)
            is_raw_transport_helper = name.endswith(".post_order_json")
            has_order_endpoint_primitive = (
                not is_raw_http_transport_call
                and any(
                isinstance(argument, ast.Constant) and argument.value == "/v2/orders"
                for argument in (*node.args, *(keyword.value for keyword in node.keywords))
                )
            )
            if (
                is_raw_http_transport_call
                or is_raw_transport_helper
                or name == "submit_order"
                or name.endswith(".submit_order")
                or name.endswith("._post_normal_live_order_payload")
                or name in {"execute_order_pairs", "_alpaca_live_client"}
                or has_paper_false
            ):
                occurrences.append(
                    (self.relative_path, node.lineno, ".".join(self.scope), name)
                )
            if (
                name == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "_post_normal_live_order_payload"
            ):
                occurrences.append(
                    (
                        self.relative_path,
                        node.lineno,
                        ".".join(self.scope),
                        "_post_normal_live_order_payload",
                    )
                )
            elif has_order_endpoint_primitive:
                occurrences.append(
                    (
                        self.relative_path,
                        node.lineno,
                        ".".join(self.scope),
                        "order-endpoint-primitive",
                    )
                )
            self.generic_visit(node)

    for path in _production_python_paths(root):
        relative_path = path.relative_to(root).as_posix()
        visitor = _InventoryVisitor(relative_path)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
    return occurrences


def _assert_all_live_write_occurrences_classified(
    occurrences: list[tuple[str, int, str, str]],
    classifications: dict[tuple[str, str, str], str],
) -> None:
    observed = Counter((path, scope, name) for path, _line, scope, name in occurrences)
    expected = Counter(classifications.keys())
    unknown = [
        f"{path}:{line}: {scope or '<module>'} -> {name}"
        for path, line, scope, name in occurrences
        if (path, scope, name) not in classifications
    ]
    missing = list((expected - observed).elements())
    duplicates = list((observed - expected).elements())
    assert not unknown and not missing and not duplicates, (
        "unclassified live-write occurrence(s): "
        f"{unknown}; missing expected occurrences: {missing}; "
        f"duplicate occurrences: {duplicates}"
    )


def test_production_live_write_inventory_has_no_unclassified_caller():
    """Every production live-write-shaped occurrence is explicitly fail-closed."""

    _assert_all_live_write_occurrences_classified(
        _live_write_occurrences(),
        _LIVE_WRITE_CALLER_CLASSIFICATIONS,
    )
    assert set(_LIVE_WRITE_CALLER_CLASSIFICATIONS.values()) == {
        "paper-only",
        "hard-disabled",
        "exact-intent-boundary",
        "read-only",
        "internal-transport",
    }


def test_production_raw_http_mutation_inventory_has_no_unclassified_transport():
    """All raw mutation transports are exact-source classified before use."""

    _assert_all_http_mutations_classified(
        _production_http_mutation_occurrences(),
        _HTTP_MUTATION_CLASSIFICATIONS,
    )
    assert _HTTP_MUTATION_CLASSIFICATIONS


def test_live_write_inventory_rejects_an_unclassified_new_production_path(tmp_path):
    source = tmp_path / "tradingagents" / "new_live_caller.py"
    source.parent.mkdir()
    source.write_text(
        "def bypass(client):\n    return client.submit_order({})\n",
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match=r"tradingagents/new_live_caller.py:2"):
        _assert_all_live_write_occurrences_classified(
            _live_write_occurrences(tmp_path),
            {},
        )


def test_live_write_inventory_rejects_an_unclassified_raw_post_caller(tmp_path):
    source = tmp_path / "tradingagents" / "new_raw_live_caller.py"
    source.parent.mkdir()
    source.write_text(
        "def bypass(client):\n    return client._post_normal_live_order_payload({})\n",
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match=r"tradingagents/new_raw_live_caller.py:2"):
        _assert_all_live_write_occurrences_classified(
            _live_write_occurrences(tmp_path),
            {},
        )


@pytest.mark.parametrize(
    "source_text",
    (
        "def bypass():\n"
        "    return requests.post('https://api.alpaca.markets/v2/orders', json={})\n",
        "def bypass():\n"
        "    return requests.request('POST', 'https://api.alpaca.markets/v2/orders', json={})\n",
        "def bypass():\n"
        "    return requests.send('https://api.alpaca.markets/v2/orders')\n",
        "def bypass():\n"
        "    return requests.put('https://api.alpaca.markets/v2/orders/example', json={})\n",
        "def bypass():\n"
        "    return requests.patch('https://api.alpaca.markets/v2/orders/example', json={})\n",
        "def bypass():\n"
        "    return requests.delete('https://api.alpaca.markets/v2/orders/example')\n",
        "def bypass():\n"
        "    return requests.Session().post('https://api.alpaca.markets/v2/orders', json={})\n",
        "LIVE_BASE_URL = 'https://api.alpaca.markets'\n"
        "def bypass():\n"
        "    return requests.Session().request('POST', f'{LIVE_BASE_URL}/v2/orders', json={})\n",
        "def bypass():\n"
        "    return requests.Session().delete('https://api.alpaca.markets/v2/orders/example')\n",
        "LIVE_BASE_URL = 'https://api.alpaca.markets'\n"
        "def bypass():\n"
        "    return httpx.Client().post(f'{LIVE_BASE_URL}/v2/orders', json={})\n",
        "LIVE_BASE_URL = 'https://api.alpaca.markets'\n"
        "def bypass(client):\n"
        "    return client._request('POST', f'{LIVE_BASE_URL}/v2/orders', json={})\n",
        "LIVE_BASE_URL = 'https://api.alpaca.markets'\n"
        "def bypass(client):\n"
        "    return client._request('POST', '{}/v2/orders'.format(LIVE_BASE_URL), json={})\n",
        "LIVE_BASE_URL = 'https://api.alpaca.markets'\n"
        "def bypass(client):\n"
        "    return client._request('POST', LIVE_BASE_URL + '/v2/orders', json={})\n",
        "def bypass(client):\n"
        "    return client._raw_session.post('https://api.alpaca.markets/v2/orders', json={})\n",
    ),
)
def test_live_write_inventory_rejects_absolute_and_constructed_raw_http_bypasses(
    tmp_path, source_text
):
    source = tmp_path / "tradingagents" / "new_constructed_transport_bypass.py"
    source.parent.mkdir()
    source.write_text(source_text, encoding="utf-8")

    with pytest.raises(
        AssertionError, match=r"tradingagents/new_constructed_transport_bypass.py"
    ):
        _assert_all_live_write_occurrences_classified(
            _live_write_occurrences(tmp_path),
            {},
        )


@pytest.mark.parametrize(
    "source_text",
    (
        'def bypass(client):\n    return client._request("POST", "/v2/orders", json={})\n',
        'def bypass(client):\n    return client._request("POST", "/v2/orders?retry=1", json={})\n',
        'def bypass(client):\n    return client._request("POST", "/v2/orders/", json={})\n',
        'def bypass(client):\n    return client._request("POST", "/v2/orders#submit", json={})\n',
        'def bypass(client):\n    return client.session.request("POST", "/v2/orders", json={})\n',
        'def bypass(client):\n    return client.session.post("/v2/orders", json={})\n',
        'def bypass(client):\n    return client.session.send("/v2/orders")\n',
        'def bypass(client):\n    return client._session.request("POST", "/v2/orders", json={})\n',
        'def bypass(client):\n    return client.session._raw_session.request("POST", "/v2/orders", json={})\n',
        'def bypass(client):\n    return client._transport.post_order_json(url="/v2/orders", payload={})\n',
        'def bypass(client):\n    return requests.post("/v2/orders", json={})\n',
    ),
)
def test_live_write_inventory_rejects_unclassified_generic_transport_bypass(
    tmp_path, source_text
):
    source = tmp_path / "tradingagents" / "new_transport_bypass.py"
    source.parent.mkdir()
    source.write_text(source_text, encoding="utf-8")

    with pytest.raises(AssertionError, match=r"tradingagents/new_transport_bypass.py:2"):
        _assert_all_live_write_occurrences_classified(
            _live_write_occurrences(tmp_path),
            {},
        )


@pytest.mark.parametrize(
    "source_text",
    (
        "import requests as rq\n"
        "def bypass():\n"
        "    return rq.post('https://api.alpaca.markets/v2/orders', json={})\n",
        "from requests import post as raw_post\n"
        "def bypass():\n"
        "    return raw_post('https://api.alpaca.markets/v2/orders', json={})\n",
        "from httpx import Client as HttpClient\n"
        "def bypass():\n"
        "    return HttpClient().post('https://api.alpaca.markets/v2/orders', json={})\n",
        "import requests\n"
        "def bypass():\n"
        "    client = requests.Session()\n"
        "    return client.post('https://api.alpaca.markets/v2/orders', json={})\n",
        "from urllib.request import Request as WireRequest, urlopen as wire_open\n"
        "def bypass():\n"
        "    request = WireRequest('https://api.alpaca.markets/v2/orders', method='POST')\n"
        "    return wire_open(request)\n",
        "from urllib.request import Request as WireRequest, urlopen\n"
        "def bypass():\n"
        "    return urlopen(WireRequest('https://api.alpaca.markets/v2/orders', method='POST'))\n",
        "import urllib.request as wire\n"
        "BASE_URL = 'https://api.alpaca.markets'\n"
        "def bypass():\n"
        "    request = wire.Request(f'{BASE_URL}/v2/orders', method='POST')\n"
        "    return wire.urlopen(request)\n",
        "import urllib.request as wire\n"
        "def bypass():\n"
        "    request = wire.Request('https://api.alpaca.markets/v2/orders', method='POST')\n"
        "    return wire.build_opener().open(request)\n",
    ),
)
def test_live_write_inventory_rejects_aliased_and_urllib_raw_http_bypasses(
    tmp_path, source_text
):
    source = tmp_path / "tradingagents" / "new_aliased_transport_bypass.py"
    source.parent.mkdir()
    source.write_text(source_text, encoding="utf-8")

    with pytest.raises(
        AssertionError, match=r"tradingagents/new_aliased_transport_bypass.py"
    ):
        _assert_all_http_mutations_classified(
            _production_http_mutation_occurrences(tmp_path),
            {},
        )


@pytest.mark.parametrize(
    ("source_text", "expected"),
    (
        (
            "def bypass(client):\n"
            "    send_order = client.post\n"
            "    return send_order('https://api.alpaca.markets/v2/orders', json={})\n",
            ("bypass", 3, "raw-http-post"),
        ),
        (
            "from requests import post as raw_post\n"
            "def bypass():\n"
            "    send_order = raw_post\n"
            "    return send_order('https://api.alpaca.markets/v2/orders', json={})\n",
            ("bypass", 4, "raw-http-post"),
        ),
        (
            "from urllib.request import Request, urlopen as wire_open\n"
            "def bypass():\n"
            "    request = Request('https://api.alpaca.markets/v2/orders', method='POST')\n"
            "    dispatch = wire_open\n"
            "    return dispatch(request)\n",
            ("bypass", 5, "raw-urllib-mutation-dispatch"),
        ),
        (
            "class Writer:\n"
            "    def __init__(self, client):\n"
            "        self.send_order = client.post\n"
            "    def submit(self):\n"
            "        return self.send_order('https://api.alpaca.markets/v2/orders', json={})\n",
            ("Writer.submit", 5, "raw-http-post"),
        ),
        (
            "from urllib.request import Request, urlopen\n"
            "class Writer:\n"
            "    def __init__(self):\n"
            "        self.request = Request('https://api.alpaca.markets/v2/orders', method='POST')\n"
            "    def submit(self):\n"
            "        return urlopen(url=self.request)\n",
            ("Writer.submit", 6, "raw-urllib-mutation-dispatch"),
        ),
        (
            "from urllib.request import Request, build_opener\n"
            "class Writer:\n"
            "    def __init__(self):\n"
            "        self.request = Request('https://api.alpaca.markets/v2/orders', None, {}, None, False, 'POST')\n"
            "        self.opener = build_opener()\n"
            "    def submit(self):\n"
            "        return self.opener.open(fullurl=self.request)\n",
            ("Writer.submit", 7, "raw-urllib-mutation-dispatch"),
        ),
        (
            "from urllib.request import Request, urlopen\n"
            "def bypass():\n"
            "    request = Request('https://api.alpaca.markets/v2/orders', data=None, method='POST')\n"
            "    return urlopen(url=request)\n",
            ("bypass", 4, "raw-urllib-mutation-dispatch"),
        ),
    ),
)
def test_raw_http_mutation_inventory_tracks_callable_and_request_provenance(
    tmp_path, source_text, expected
):
    """Bound aliases cannot hide a raw HTTP mutation from exact-source review."""

    source = tmp_path / "tradingagents" / "new_bound_transport_bypass.py"
    source.parent.mkdir()
    source.write_text(source_text, encoding="utf-8")

    occurrences = _production_http_mutation_occurrences(tmp_path)

    scope, line, name = expected
    assert (
        "tradingagents/new_bound_transport_bypass.py",
        line,
        scope,
        name,
    ) in occurrences


def test_strategy_tournament_command_is_intent_only_and_cannot_write_orders():
    strategy = _registry()["roles"]["strategy_learning"]

    tournament_commands = [
        command
        for command in strategy["command_family"]
        if "paper-tournament" in command
    ]
    assert tournament_commands == [
        "alpaca paper-tournament run --all --dry-run --json-output"
    ]
    assert "broker_order_write" in strategy["forbidden_effects"]
    assert "order_submit" in strategy["forbidden_effects"]


def test_role_contract_does_not_claim_human_or_separate_process_approval():
    registry_text = json.dumps(_registry()).casefold()
    source_text = "\n".join(
        (ROOT / path).read_text(encoding="utf-8").casefold()
        for path in (
            "tradingagents/orchestration/recovery.py",
            "tradingagents/orchestration/self_heal.py",
            "cli/main.py",
        )
    )

    assert "human_approval" not in registry_text
    for unsupported_claim in (
        "independent_verifier",
        "independent_verification",
        "durable independent evidence",
        "independently verified packets",
    ):
        assert unsupported_claim not in source_text
