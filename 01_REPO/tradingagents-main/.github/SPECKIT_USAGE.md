# Using /speckit.* prompts in this repository

Short guide for contributors on how to invoke Speckit workflow prompts in VS Code Copilot Chat / agent mode.

- **Prompt files location:** [.github/prompts](.github/prompts)
- **Spec Kit templates & memory:** [.specify](.specify)
- **Copilot guidance file:** [.github/copilot-instructions.md](.github/copilot-instructions.md)

How to invoke:

1. Open GitHub Copilot Chat (agent mode) while this workspace is open.
2. Type the slash command for the workflow you want, for example: `/speckit.constitution` or `/speckit.specify`.
3. If the prompt does not appear in suggestions, reload the VS Code window (Command Palette → Reload Window) and try again.

Notes and best practices:

- Prompts are grounded in the repository `.specify/` templates and `.specify/memory/`. Outputs should reference repository files only.
- If you want to revert the prompt edits made by the team, backups exist in `.github/prompts/*.orig`.
- If Copilot still does not surface the slash command after a reload, restart the Copilot extension or sign out/in of Copilot Chat.
- Do not run automated repository edits without review; prompts may request permission before applying changes.

If you want, I can also add a short README snippet or a workspace `README.guides.md` with these instructions.
