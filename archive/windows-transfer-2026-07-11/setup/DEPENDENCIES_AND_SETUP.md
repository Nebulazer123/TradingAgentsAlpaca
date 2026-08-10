# Dependencies and Mac Setup

## TradingAgents

- Python requirement: `>=3.10`; the existing README recommends Python 3.13.
- Preferred dependency command: `uv sync` using `pyproject.toml` and `uv.lock`.
- Alternative: create a fresh Python environment and run `pip install .`.
- Static-analysis dependencies are defined in the `static-analysis` dependency group.

Do not copy or reuse the Windows `.venv`. Create a new Mac environment from the lockfile.

## MiroFish

Use the existing `package.json`, `package-lock.json`, backend manifests, Docker files, and README instructions as the dependency source of truth. Do not copy `node_modules` or `backend/.venv`; install them on Mac after reviewing the setup instructions.

## Credentials

The live Windows `.env` files were excluded. Populate a new local environment manually from the included example files. Never commit API keys, broker credentials, email credentials, or access tokens.

## Safe first setup

Install dependencies and inspect tests first. Do not start scheduled jobs, send email, call broker submit endpoints, or launch autonomous research until the Mac-side configuration has been reviewed.
