# Sanitized environment template

No credential-bearing `.env` file is included in this transfer. Create local machine-only files from the project examples and fill them manually on the Mac.

## TradingAgents

Use `01_REPO/tradingagents-main/.env.example` as the variable-name reference. Do not copy secrets from the Windows machine into this package.

## MiroFish

Use `01_REPO/mirofish-main/.env.example` and any backend/frontend example files as the variable-name reference. Do not restore `.env` backups from the Windows machine without reviewing and rotating every credential.

## Safety

Keep broker keys, model keys, OAuth tokens, passwords, and private certificates in the Mac keychain or untracked local environment files. Never commit them or place them on a shared drive.
