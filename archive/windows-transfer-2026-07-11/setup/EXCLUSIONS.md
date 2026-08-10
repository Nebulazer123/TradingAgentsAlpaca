# Transfer Exclusions

- `.env`: contains machine credentials and API keys.
- `.venv` and `backend/.venv`: Windows-specific installed environments.
- `node_modules`: regenerated from lockfiles.
- `.git`: excluded from the active snapshot unless a separate history scan proves it safe; branch, remote, commit, status, and diff provenance are recorded separately.
- `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.cache`, `__pycache__`, and `.pyc`: generated caches.
- Machine-level Codex databases, credentials, and system state: not part of the project transfer.

The exclusions are documented so a Mac-side agent can distinguish intentionally omitted state from missing work.
