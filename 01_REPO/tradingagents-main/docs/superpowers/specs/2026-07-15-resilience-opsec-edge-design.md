# Frontier + Survivable + Anonymous — Design Spec (2026-07-15)

Owner request: "keep it frontier above other trading bots and completely anonymous
even for a doomsday, broken state, or worst case." Approved scope: **build all three
buckets** on the `fable` worktree. Advisor (Fable 5) design grounded in the code.

## Guardrails (every item obeys these; violating one = rejected)
1. **Never weaken the go-live guard or any invariant.** Only ADD gates/evidence.
   Research/analysis lanes stay `execution_authority=none`. Fail closed on stale/
   corrupt/missing state. See `memory: trading-safety-invariants`.
2. **"Anonymous" = opsec/privacy/survivability only.** Protect secrets, identity,
   strategy; survive disasters. NO hiding trades from broker/regulators, NO
   detection evasion, NO defeating oversight. At a $250-cap KYC'd account that would
   be both illegal-adjacent and pointless.
3. **Codex owns scheduling.** No launchd installs, no self-scheduling. New tools are
   plain CLI + library code Codex can wire.
4. **Live is ARMED** (dead-man valid through 2026-07-17T12:58Z, NFLX hard-stop
   pending). New work is flag-gated, dry-run/warn defaults, on `fable`. Nothing
   changes production order-path behavior until the owner flips a flag.
5. Owner is non-technical, cost-sensitive: plain-language alerts, cheap lanes, no Zep.

## Test environment (non-obvious)
The `fable` worktree mirrors the whole wrapper repo, so trading code lives at
`01_REPO/tradingagents-fable/01_REPO/tradingagents-main/`. The fable `.venv` lacks
pytest. Run tests with the **production** venv from the **fable** dir (cwd shadows
imports to fable code): `cd <fable>/01_REPO/tradingagents-main && \
../../../tradingagents-main/.venv/bin/python -m pytest tests/ -q`.
Baseline: 1092 collected.

## Verified ground truth (do NOT rebuild — already fail-closed)
- Corrupt/missing `live_control.json` / `promotion_state.json` already BLOCKS
  (`live_gate.py` `_read_promotion_state`, `live_control.load_live_control_state`).
- Atomic writes exist (`policy/io.atomic_write_text`, temp + `os.replace`).
- Broker-vs-local reconciliation, clock-skew, single-writer lock exist in
  `execution/`. Research-lane redaction, gitignored `.env`, n8n `env -i`, paper-only
  live MCP all exist.

### Real gaps
1. No `fsync` anywhere → power-loss can leave a zero-length control file (fails
   closed, but also blocks protective sells with no owner-known recovery).
2. No tamper-evidence/checksums/audit on the two money-gating JSONs.
3. No panic-flatten kill-switch (only `freeze-live`).
4. `_promotion_issues` never expires stale promotion evidence.
5. No plain-language health/heartbeat CLI; no state snapshot; no boot reconcile CLI.
6. Order rate-limit code exists but config is unset (inert).
7. No secret-leak scan over `results/`/outbox; no `.env` perms check; no
   no-secrets-in-email guard.

## Bucket C — Doomsday / broken-state survivability (priority)
| ID | Item | Files | Default | Pri |
|----|------|-------|---------|-----|
| C2 | fsync durability in `atomic_write_text` (fsync temp + parent dir; F_FULLFSYNC on macOS) | `policy/io.py` | always on, same API | P0 |
| C1 | State integrity: `policy/integrity.py` sha256+seq+ts sidecar; loaders verify behind `TA_STATE_INTEGRITY=off\|warn\|enforce` (default **warn** = log only) | new `policy/integrity.py`, wire `live_control.py`, `live_gate._read_promotion_state`, `promotion_sync.py` | warn (no behavior change) | P0 |
| C4 | `cli policy health-check [--json]`: dead-man remaining, armed?, integrity, last-tick age, outbox backlog, broker reachable (read-only), disk, `.env` perms; CRITICAL → plain email | new `policy/health.py`, `cli/main.py` | read-only | P0 |
| C3 | `cli policy panic-flatten`: read live positions → fill-friendly sell limits w/ `user_manual_override` + full loss-exit review → run `evaluate_go_live_guard` + tiny-live op guard → submit only if ALL gates pass → freeze after; `--dry-run` default, real submit needs `--confirm FLATTEN` + `TA_LIVE_SUBMIT=1` | new `policy/panic_flatten.py`, `cli/main.py` | dry-run | P0 |
| C8 | Hash-chained audit log of safety-state mutations → `results/policy/state_audit.jsonl` | `policy/integrity.py`, wired writers | append-only | P1 |
| C5 | Optional `promotion_max_age_days` (inert unless set) → block stale promotion | `policy/risk_envelope.py`, `live_gate.py` | inert | P1 |
| C6 | `cli policy snapshot-state` / `restore-state` (restore dry-run+confirm) | new `policy/snapshots.py`, `cli/main.py` | read-only/confirm | P1 |
| C7 | `cli policy reconcile-live` standalone read-only broker-vs-packet reconcile | `cli/main.py` (reuse `execution/reconcile.py`) | read-only | P1 |
| C9 | Arm order rate limit config (owner flips AFTER NFLX window) | `config/risk_envelope.yaml` | owner action | P1 |

## Bucket B — Opsec / anonymity (legitimate)
| ID | Item | Files | Pri |
|----|------|-------|-----|
| B1 | `cli policy scan-leaks`: `SECRET_PATTERNS` + loaded-key sha256 first-8 fingerprints across `results/`/outbox/logs; wired into health-check | new `evals/secret_leakage.py` | P1 |
| B2 | Outbox sensitivity eval: rendered emails must contain no keys/raw account ids before queueing | `evals/email_clarity.py` (or new eval) + alert render path | P1 |
| B3 | `.env` hygiene in health-check: mode 600, not git-tracked, live≠paper key, live key absent from research env | `policy/health.py` | P1 |
| B4 | Key-rotation runbook + `key_fingerprints.json` (fingerprints only, never keys) | `docs/runbooks/key_rotation.md`, `policy/health.py` | P2 |
| B5 | Off-machine encrypted recovery bundle (state+envelope+runbooks, NO keys) | `policy/snapshots.py` | P2 |

## Bucket A — Edge (honest: at $200 live, edge = evidence quality + discipline)
| ID | Item | Files | Pri |
|----|------|-------|-----|
| A1 | Tournament realized-PnL scoring + sell rules (promotions currently ride on mark-to-market) | `brokers/paper_tournament.py`, `promotion_sync.py` | P0-of-A |
| A3 | Optional `no_new_entry_days_before_earnings` guard (the NFLX lesson; inert unless set; blocks NEW buys only) | `brokers/supervisor/candidates.py`, `risk_envelope.py` | P1 |
| A4 | Anti-overfit promotion gates: optional min tracked-days / OOS split (inert unless set) | `promotion_sync.py`, `risk_envelope.py` | P1 |
| A2 | Execution-quality telemetry (slippage/time-to-fill/unfilled) | new `evals/execution_quality.py` | P1 |
| A6 | Regime-scaled sizing (shrink-only; caps unchanged) | `policy/risk_posture.py`, sizing | P2 |
| A5 | Cost-aware paper fills (spread haircut) | `brokers/paper_tournament.py` | P2 |

## DO NOT BUILD (rejected — evasion or self-defeating)
Order/traffic randomization to dodge broker surveillance; rotating broker
accounts/identities (structuring); VPN/Tor routing of broker API; editable/prunable
audit logs; system self-refreshing its own dead-man; any guard-bypass "emergency
lane"; self-installed launchd watchdog; live keys in research lanes.

## Owner decisions (later flips, not build blockers)
1. Flip `TA_STATE_INTEGRITY=enforce` after ~1 week warn burn-in.
2. Panic-flatten = sell ALL live positions + auto-freeze after (recommended yes).
3. `promotion_max_age_days` (recommend 30) — then stale evidence stops live trading.
4. Arm order rate limit (recommend 10/60min) AFTER NFLX earnings window.
5. Off-machine backup location + passphrase holder.
6. Key rotation is an owner dashboard action; system only verifies it happened.

## Build order
C2 → C1 → C4 → C3 (P0 survivability, zero armed-path behavior change) → C8/C5/C6/C7
→ B1/B2/B3 → A1/A3/A4/A2 → P2 items. Full suite green after each; new unit tests per
item; tests never touch production `results/policy/` files (use tmp dirs).
