<!-- SPECKIT START -->
This repository uses GitHub Spec Kit workflows (.specify) and includes
project workflow prompts under `.github/prompts/`.

Guidance for Copilot Chat and agent mode:

- Recognize `/speckit.*` prompt files in `.github/prompts/` as project-level workflow commands (e.g. `/speckit.constitution`, `/speckit.specify`, `/speckit.plan`, `/speckit.tasks`, `/speckit.implement`, `/speckit.clarify`, `/speckit.analyze`, `/speckit.checklist`).
- Use `.specify/` templates, `.specify/memory/`, `.specify/workflows/`, and `templates/` when grounding outputs in repository facts.
- Do not invent product requirements or external constraints. Ask concise clarifying questions when necessary.
- When producing specs, plans, tasks, or implementation suggestions, reference repository file paths and existing templates.

If you are unable to find required context, ask the user for the missing details rather than assuming them.

<!-- SPECKIT END -->
