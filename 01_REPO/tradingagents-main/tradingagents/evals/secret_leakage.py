"""B1/B3: scan repo output for leaked secrets, and check credential hygiene.

The scanner reports FINGERPRINTS (first 8 hex of sha256), never raw secret values,
so the report itself is safe to log or email. It looks for two things:

* the *actual value* of a loaded credential appearing in a results/log file (the
  strongest, zero-false-positive signal), and
* generic secret-assignment patterns (``authorization: Bearer …``, ``api_key=…``,
  JWTs, ``sk_…`` style tokens) reused from the research-lane redactor.

Emails and account references are intentionally NOT treated as leaks — they appear
legitimately in owner notifications. This module is analysis-only; it cannot trade.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from tradingagents.research.memory import SECRET_PATTERNS

#: Environment variables whose *values* must never appear in results/logs/outbox.
MONITORED_KEY_ENV_VARS: tuple[str, ...] = (
    "ALPACA_LIVE_API_KEY",
    "ALPACA_LIVE_SECRET_KEY",
    "ALPACA_PAPER_API_KEY",
    "ALPACA_PAPER_SECRET_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "SMTP_PASSWORD",
    "ZEP_API_KEY",
)

_TEXT_SUFFIXES = frozenset({".json", ".jsonl", ".log", ".txt", ".md", ".yaml", ".yml", ".csv"})
_SKIP_DIR_PARTS = frozenset({".git", ".venv", "node_modules", "__pycache__", ".ruff_cache", ".pytest_cache"})
_SKIP_FILE_NAMES = frozenset({".env"})
_MAX_SCAN_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class Leak:
    file: str
    kind: str
    fingerprint: str
    detail: str


def fingerprint(value: str) -> str:
    """First 8 hex chars of sha256 — identifies a secret without revealing it."""

    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:8]


def _loaded_key_values(env: Mapping[str, str]) -> list[tuple[str, str]]:
    loaded: list[tuple[str, str]] = []
    for name in MONITORED_KEY_ENV_VARS:
        value = str(env.get(name, "")).strip()
        if len(value) >= 8:  # ignore empty/placeholder values
            loaded.append((name, value))
    return loaded


def scan_text_for_secrets(
    text: str, *, loaded_key_values: Iterable[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Return (kind, fingerprint) findings for one blob of text."""

    findings: list[tuple[str, str]] = []
    for name, value in loaded_key_values:
        if value and value in text:
            findings.append((f"loaded_key:{name}", fingerprint(value)))
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(("secret_pattern", ""))
            break
    return findings


def email_contains_secret(text: str) -> bool:
    """B2: does a rendered notification contain a secret (key/token), ignoring
    the emails/account refs that legitimately appear in owner mail?"""

    return any(pattern.search(str(text)) for pattern in SECRET_PATTERNS)


def find_secret_leaks(
    scan_dirs: Iterable[str | Path],
    *,
    env: Mapping[str, str] | None = None,
) -> list[Leak]:
    """Scan directories for leaked secrets. Returns fingerprinted findings only."""

    environ = env if env is not None else os.environ
    loaded = _loaded_key_values(environ)
    leaks: list[Leak] = []
    for scan_dir in scan_dirs:
        root = Path(scan_dir)
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name in _SKIP_FILE_NAMES:
                continue
            if any(part in _SKIP_DIR_PARTS for part in path.parts):
                continue
            if path.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > _MAX_SCAN_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for kind, fp in scan_text_for_secrets(text, loaded_key_values=loaded):
                leaks.append(Leak(
                    file=str(path),
                    kind=kind,
                    fingerprint=fp,
                    detail=(
                        f"{kind} match in {path.name}"
                        + (f" (fingerprint {fp})" if fp else "")
                    ),
                ))
    return leaks


def check_key_hygiene(env: Mapping[str, str] | None = None) -> list[str]:
    """B3: cheap credential-hygiene checks (no filesystem scan)."""

    environ = env if env is not None else os.environ
    issues: list[str] = []

    live_key = str(environ.get("ALPACA_LIVE_API_KEY", "")).strip()
    paper_key = str(environ.get("ALPACA_PAPER_API_KEY", "")).strip()
    if live_key and paper_key and live_key == paper_key:
        issues.append("live and paper Alpaca API keys are identical — use separate keys")

    live_secret = str(environ.get("ALPACA_LIVE_SECRET_KEY", "")).strip()
    paper_secret = str(environ.get("ALPACA_PAPER_SECRET_KEY", "")).strip()
    if live_secret and paper_secret and live_secret == paper_secret:
        issues.append("live and paper Alpaca secret keys are identical — use separate secrets")

    return issues


def leaks_summary(leaks: Iterable[Leak]) -> dict:
    leak_list = list(leaks)
    return {
        "leak_count": len(leak_list),
        "files": sorted({lk.file for lk in leak_list}),
        "kinds": sorted({lk.kind for lk in leak_list}),
        "fingerprints": sorted({lk.fingerprint for lk in leak_list if lk.fingerprint}),
    }
