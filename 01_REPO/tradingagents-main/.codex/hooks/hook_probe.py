from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from tradingagents.orchestration.token_context import redact_hook_payload


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {"raw_stdin_prefix": raw[:300], "parse_error": "json_decode_failed"}

    event = os.environ.get("CODEX_HOOK_EVENT") or payload.get("hook_event") or payload.get("event") or "unknown"
    root = Path.cwd()
    out_dir = root / "results" / "_context" / "hook-events"
    out_dir.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc)
    packet = {
        "schema_version": 1,
        "event": event,
        "created_at": created.isoformat(),
        "cwd": str(root),
        "payload_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
        "payload_sample": redact_hook_payload(payload),
    }
    out_path = out_dir / f"hook-probe-{created.strftime('%Y%m%d-%H%M%S-%f')}.json"
    out_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
    print(f"hook probe wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

