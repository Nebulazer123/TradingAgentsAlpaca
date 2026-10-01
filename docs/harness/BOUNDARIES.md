# Consequential operation boundaries

Use this map when changing an authority path or preparing a separately authorized
operation. These mechanisms evaluate current inputs. Historical receipts, model
recommendations and instruction files do not grant external authority.

| Operation | Current mechanism and source | What it proves |
| --- | --- | --- |
| Live order submission | `tradingagents/brokers/alpaca.py`, `alpaca_supervisor.py`, `policy/live_control.py`, `policy/owner_approval.py`, `execution/` | Intent, current approval/control/evidence, risk, reconciliation and execution coordination are checked at submission. Preserve the full path and final recheck. |
| Paper submission | `cli/main.py` paper-tournament/hourly commands, `strategy/paper_execution_authorization.py`, broker paper path | Explicit paper mode, account, clock, request and applicable paper guards. The tournament/preopen wrapper supplies dry-run; a paper account alone is not task authority. Some direct paper-client routes do not use the promoted-strategy artifact. |
| Schedule activation | Actual Codex scheduler records; `config/automation_schedule_contract.json`, `orchestration/automation_health_audit.py` | Scheduler status governs execution. The audit checks exact record topology, fields and deployment evidence; it does not authorize or perform activation. |
| Email transport | `scripts/mac/deliver_outbox.py` | Preview by default. `--send` plus explicit queued IDs is required before SMTP access. Broker flags and configured credentials cannot drain the queue. This is explicit scope, not cryptographic authentication of a human. |
| Paid advisory route | `research/model_routing.py` | Opt-in, a positive finite dollar cap, known positive finite estimate and configured usage limits are required. Invalid direct policies and malformed environment values fail closed. Selection is advisory; it is not billing settlement. |
| Graph/model execution | `graph/trading_graph.py`, `cli/stats_handler.py`, provider clients | Existing timeout, retry, output, call and token settings bound configured runs. These are not a universal hard dollar controller. A paid experiment needs an authorized dispatcher with verified pricing, pre-dispatch worst-case reservation and usage settlement (including uncertain charges). |
| Holdout release | `evals/economic_evaluation_admission.py`, `economic_evaluation_protocol.py` | Current protocol/validation/tournament custody and a distinct release record are required before protected input access. The current `released_by` identifier is a claim, not signed owner authentication. It remains a separate owner operation; no release was performed by this refactor. |
| Credentials/private evidence | `.env` mode 0600, ignored stores, targeted redaction in official adapters and research memory | File permissions, Git exclusions and packet redaction serve their respective scopes. They do not sandbox a full-access agent. Avoid copying private inputs to external tools. |
| Recovery/removal | Existing archive manifests, exact worktree identity and owner/process inspection | Recoverability and custody for the authorized target; never infer cleanup authority from a stale handoff. |

## Effective Codex permissions

This host currently selects full filesystem/network access with approval policy
`never`. No project permission profile or command-rule layer was present. This
refactor does not change host security settings or claim a new sandbox boundary.
The existing user rule file contains sixteen allow prefixes and no
TradingAgents-specific restriction; those permissions were retained.

Current Codex permissions can bound local work while allowing autonomy inside
the workspace. Rules constrain command prefixes outside the sandbox; they are
not a complete broker, SMTP, Python, MCP or credential firewall. Auto-review
reviews eligible boundary crossings and grants no wider sandbox access. A future
permission migration must check the effective configuration: legacy
`sandbox_mode` settings take precedence over new named profiles, network domain
restrictions need the supported proxy, and CLI/MCP/browser surfaces have distinct
controls. See [permissions](https://learn.chatgpt.com/docs/permissions),
[sandboxing](https://learn.chatgpt.com/docs/sandboxing),
[auto-review](https://learn.chatgpt.com/docs/sandboxing/auto-review), and
[Rules](https://learn.chatgpt.com/docs/agent-configuration/rules).

## Check changed boundaries directly

Use isolated malformed/partial inputs and a fake transport/adapter. Confirm the
denied path cannot reach its external operation and the correctly scoped fixture
still reaches the intended adapter. Reuse existing owner/live/paper/scheduler
tests when those inputs are unchanged. Neither a model upgrade nor a simpler
instruction is evidence that external execution is authorized.
