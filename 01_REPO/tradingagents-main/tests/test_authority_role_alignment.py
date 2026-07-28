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
