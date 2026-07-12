# Final USB validation

- Destination: `D:\TRADINGAGENTS_MAC_TRANSFER`
- Format: exFAT
- Source files: 13,123
- USB files: 13,123
- Source bytes: 483,008,425
- USB bytes: 483,008,425
- Missing relative paths: 0
- Extra relative paths: 0
- Size mismatches: 0
- SHA-256 mismatches: 0
- Focused non-trading tests: 4 passed
- Credential-pattern scan: no matches
- Real `.env` files: excluded; only example templates remain
- `.venv`, `node_modules`, Git metadata, and caches: excluded from the transfer

The full per-file comparison is in `usb-hash-compare.csv`. The USB package includes the source trees, generated TradingAgents results, redacted same-day Codex rollout transcripts, automation snapshots, pause receipt, setup notes, and source-state/diff records.
