# TradingAgents harness modernization

## Result

Local development now proceeds through task-selected context, implementation,
direct checks and repair. The root entry chain (`AGENTS.md`, `CLAUDE.md`,
`START_HERE.md`) fell from **1,227 to 634 words**, about **48% smaller**.
`AGENTS.md` itself fell from 130 to 60 lines. The 1,121-line historical router
was preserved exactly in `docs/history/2026-10-01-context-router.md`; its root
replacement is an 18-line index and is no longer a generated startup requirement.

Detailed procedures load through three repo skills: research/economic evaluation,
runtime diagnosis, and source release/recovery. Readiness has a completion
contract plus current progress, separate from permanent guidance and historical
checkpoints. The twelve-phase research, economics, learning and six-session
acceptance requirements remain in their existing plan/specification owners.
The program suits a native Codex Goal; none was created without an explicit request.

## Reporting and automation

Root, Claude bridge, Goal handoff and role prompts report results, changes,
material actions/blockers and relevant checks. Complete machine fields remain
in packet owners. There is no required unchanged global-state recital.
Lifecycle hooks no longer refresh runtime state, write generic turn receipts or
print a status recap. A targeted nonblocking PreToolUse warning remains for
relevant broad raw/private-input reads. Ordinary source tools are silent.

All ten saved automation prompts were updated through the app's automation tool,
read back, and bound to exact source text under `config/automation_prompts/`.
Combined prompt size fell from 12,595 to 6,816 characters, about **46%**. Shared
role procedures have one conditional owner in `docs/orchestration/automation-runbook.md`.
The contract changes only prompt fingerprints and model/reasoning assignments;
schedule, notification, target, cwd, phase, role, dependency and no-submit fields
were compared against the original values. The legacy Windows prompt/frequency
proposal generator now points to the maintained sources.

## Executable protections

- Email credentials and an hourly action flag cannot send queued mail.
  The transport previews by default and requires `--send` plus selected queued
  IDs before opening SMTP. Missing/ambiguous scope fails before transport;
  failures leave unsent messages queued. Routine daily reporting composes locally.
- Paid advisory routing requires an explicit opt-in, a positive finite per-run
  dollar cap and cost estimate, valid positive configured usage limits and
  finite nonnegative monthly accounting. Malformed direct policies and decimal
  environment values fail closed. Free/deterministic lanes retain their behavior.
- Existing broker, live-control, owner-approval, execution, paper and scheduler
  paths retain their controls. Machine authority/evidence fields were not removed
  to reduce conversational repetition.

The [boundary map](BOUNDARIES.md) states the practical limits. Advisory estimates
are not a universal billed-dollar reservation/settlement controller. Existing
holdout release records do not authenticate a human signature. The host remains
full access, so this refactor does not claim a new credential/network sandbox.
These limitations are documented; no decorative rule file or fake proof layer
was added to imply they were solved.

## Models

At the owner’s follow-up request, saved Codex jobs use GPT-6 Luna/medium for
wake/sleep controllers, Luna/high for preopen checks and daily reporting, and
Luna/max for the safety sentinel and tournament. GPT-6.1 Sol/max handles BOARD,
recovery, supervisor and research synthesis. Higher effort reflects complexity
and consequence; it is not a measured quality-improvement claim. Versioned graph defaults are Sol for deep roles and Luna for quick
roles; advisory judgment defaults to Sol. Explicit provider/model overrides
remain available. Astra is in the API catalog for difficult measured escalation,
with no extra job. Active primary-session settings were not switched.

The local Codex cache and current official model pages were inspected. API
catalog context is 1,050,000 tokens for the three added models; the Codex UI cache's
272k context describes its own surface. Native OpenAI already uses Responses,
the required tool-calling path. Offline tests verify model/endpoint/reasoning
configuration; API account access, remote execution and forecast improvement
were not established by configuration tests.

## Validation

The first affected run passed 116 tests; the expanded routing/automation/hook
run passed 246 tests. Full-source Ruff passed after two import sorts and one
test closure fix; the initial failed lint output is retained. Independent
read-only review covered authority scope, model compatibility, role semantics,
stable scheduler fields and exact prompt bindings. It caught a source-versus-editor
whitespace mismatch, which was repaired and given a direct contract regression.

The final 19-module affected run passed **612 tests in 35.57 seconds**, with one
existing Google-model fixture warning. It covers routing, provider configuration,
context/hooks, automation contracts, outbox transport, broker/supervisor,
owner/paper authority and graph handoffs. The wording-only documentation test
was removed; executable context and lifecycle behavior remains covered.

All six final static checks passed: full-source Ruff, Python compilation,
offline dependency-lock consistency, both Mac shell syntax checks and diff
whitespace. The three skills passed their format validator; readback found no
missing local link targets across fourteen current instruction/report files.
This is representative affected validation, not a full-repository pytest claim.
Durable output and exit results are in
`results/harness-modernization-final-validation.log` / `.exit` and
`results/harness-modernization-final-static.log` / `.exit`; earlier failed and
successful outputs remain under `results/harness-modernization-*`.
No result in this report is deployment, economic or remote model acceptance.

## Research basis

Official guidance and observed source behavior outweighed community anecdotes.
The implementation follows concise root guidance, conditional detail and direct
feedback, rather than copying example approval gates or artifact trees.

| Current source read | Applied conclusion |
| --- | --- |
| [Rethinking skills and prompts for GPT-6 Astra](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra) | Remove accumulated handholding; give clear local completion authority; keep skill discovery short and conditional. |
| [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) | Root/nested instruction scope and precedence; no dynamic task tracker in root. |
| [Best practices](https://learn.chatgpt.com/guides/best-practices) | Clear outcome/context/constraints; practical short project guidance and task-specific references. |
| [Customization](https://learn.chatgpt.com/docs/customization/overview) | Separate stable instructions, repeatable skills and mechanical hooks/checks. |
| [Permissions](https://learn.chatgpt.com/docs/permissions), [Sandbox](https://learn.chatgpt.com/docs/sandboxing) | Autonomy within effective technical boundaries; approval settings are distinct from isolation. |
| [Auto-review](https://learn.chatgpt.com/docs/sandboxing/auto-review), [Rules](https://learn.chatgpt.com/docs/agent-configuration/rules) | Reviewer substitution does not expand permissions; command rules are scoped, not a universal firewall. |
| [Agent Skills](https://learn.chatgpt.com/docs/build-skills), [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) | Short precise triggers, progressive detail, bounded independent work and one writer. |
| [Using Goals in Codex](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex) | A thread-scoped completion contract suits uncertain multi-turn readiness work; explicit user lifecycle authority remains. |
| [Build iterative repair loops](https://developers.openai.com/cookbook/examples/codex/build_iterative_repair_loops_with_codex) | Review, focused repair and actual feedback; use observed failures to choose the next step. |
| [Iterating Development Workflows](https://developers.openai.com/cookbook/examples/codex/iterating-development-workflows-with-codex) | Separate goal/progress/evidence; its large phase/approval artifact tree is an optional example, not platform policy. |
| [Per-run spending controller](https://developers.openai.com/cookbook/articles/per_run_spending_controller_responses_api) | A real hard token-cost ceiling reserves worst-case cost before dispatch and settles verified usage; sample prices are not current rates. |
| [GPT-6 guide and migration](https://developers.openai.com/api/docs/guides/latest-model), [Codex models](https://learn.chatgpt.com/docs/models) | Choose by workload; preserve supported reasoning/provider semantics and distinguish API from Codex metadata. |
| [Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) | Exact published IDs/context; Responses supports the intended function-tool path. |
| [Open AGENTS.md standard](https://agents.md/) | Plain Markdown and nearest scope; an instruction format supplies no execution enforcement. |

The smaller practitioner scan covered Reddit, GitHub and technical writeups.
[Repeated apology/overengineering](https://www.reddit.com/r/codex/comments/1ve9nxe/why_does_codex_constantly_overengineer_code_and/),
[large anti-overengineering prompts](https://www.reddit.com/r/codex/comments/1vf5elq/how_do_you_stop_codexclaude_from_overengineering/),
[small direct result checks](https://www.reddit.com/r/codex/comments/1v5dn0i/what_prompts_or_agentsmd_rules_keep_codex_from/), and
[long iteration complaints](https://www.reddit.com/r/codex/comments/1vk7p9q/i_am_tired_of_codex_over_engineering_everything/)
were mixed anecdotal reports, including useful safeguards as well as cumbersome
fail-safe accumulation. They were not adopted as prompts.
[Thoughtworks on instruction bloat](https://www.thoughtworks.com/en-us/radar/techniques/agent-instruction-bloat),
[the progressive-disclosure proposal](https://github.com/agentsmd/agents.md/issues/135), and
[BeeWare's duplication/retrieval discussion](https://github.com/beeware/beeware/discussions/630)
supported testing context placement and avoiding synchronized duplicates; the
GitHub proposal is not an adopted AGENTS.md requirement. No useful accessible
firsthand X/Twitter source was found in the smaller scan.

Detailed per-instruction dispositions: [INSTRUCTION_INVENTORY.md](INSTRUCTION_INVENTORY.md).
