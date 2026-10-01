# TradingAgents with your ChatGPT subscription

TradingAgents now calls the installed Codex runner using your existing ChatGPT
sign-in. No OpenAI API key is needed. This is the default model provider, `codex`,
with Luna 6 for quick analysis and Sol 6.1 for deeper work. The interactive CLI
offers **ChatGPT subscription (Codex)** as its first provider choice. Overnight
analysis uses this default without probing the local Ollama machines.

The connector turns each TradingAgents model request into an ephemeral Codex
turn. It passes the conversation and available application tools, receives a
checked response, and hands tool requests back to TradingAgents. TradingAgents
executes those tools and returns their results on the next turn. Structured
responses use the existing LangChain/Pydantic validation. Codex's native shell,
browser, apps, plugins and tool execution host are disabled for these calls.

For Python callers:

```python
from tradingagents.llm_clients.factory import create_llm_client

model = create_llm_client("codex", "gpt-6-luna", timeout=120).get_llm()
answer = model.invoke("Summarize the supplied public evidence...")
```

Existing explicit provider or environment overrides still apply. Select
`TRADINGAGENTS_LLM_PROVIDER=codex` if an older shell configuration overrides the
default; use `TRADINGAGENTS_OVERNIGHT_LLM_PROVIDER=codex` for an explicit overnight
override. The local route is `codex://local/exec`; the connector rejects API URLs
and strips API keys and broker credentials from the runner's environment.

The machine running TradingAgents needs Codex CLI and an active ChatGPT sign-in.
The implementation was checked with Codex CLI 0.159.2. `codex login status`
checks the sign-in; `codex login` establishes it when necessary. This route uses
your subscription allowance and can hit its limits. It does not provide unlimited
inference, and unattended runs depend on the machine and saved sign-in remaining
available. No API fallback or automatic model retry occurs.

The runner accepts at most 262,144 input bytes by default and bounds accepted
output characters. The CLI exposes no hard output-token spending cap:
TradingAgents' configured output-token setting is translated to a character
acceptance limit at four characters per configured token. Exceeding it rejects
the response after generation. Usage records identify subscription billing,
requested model, runner version and token usage; a serving revision is unavailable.
Checkpoint identities bind the local route, runner version and actual bounds.

Real subscription checks on October 1 succeeded for both Luna 6 and Sol 6.1:
each returned the expected structured 20% change for fictional prices 10 and 12.
A further Luna call requested a synthetic price through the application's
ToolNode, then used the returned 12.00 USD value. These establish connection,
structured-output and tool integration; they do not score investment quality.
The retained evidence is under
`results/readiness_continuation/20261001-codex-subscription-runner/` in the canonical
checkout. The initial failed calls and diagnostic output are preserved there.

OpenAI documents this signed-in route in [Authentication](https://learn.chatgpt.com/docs/auth)
and [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode).
The [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk) is another supported
integration option; this connector uses the already-installed CLI.
