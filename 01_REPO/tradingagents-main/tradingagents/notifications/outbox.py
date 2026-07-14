"""Durable outbox for rendered owner notifications.

The repo renders email subjects/bodies but has never owned a transport; on
Windows the outer Codex automation sent them. On the Mac, every rendered
notification is queued here and ``scripts/mac/deliver_outbox.py`` (or any
future transport) delivers and marks them. Pure stdlib, atomic writes,
analysis-only: nothing here can trade.
"""

from __future__ import annotations

import datetime
import json
import uuid
from pathlib import Path
from typing import Any, Mapping

from tradingagents.policy.io import atomic_write_text

UTC = datetime.timezone.utc
DEFAULT_OUTBOX_DIR = Path("results/outbox")


def _now_iso() -> str:
    return datetime.datetime.now(tz=UTC).isoformat(timespec="seconds")


def write_outbox_message(
    payload: Mapping[str, Any],
    outbox_dir: str | Path = DEFAULT_OUTBOX_DIR,
    *,
    report_type: str = "daily",
    severity: str = "ROUTINE",
) -> Path:
    """Queue one rendered notification; returns the message path."""
    outbox = Path(outbox_dir)
    outbox.mkdir(parents=True, exist_ok=True)
    message_id = f"{datetime.datetime.now(tz=UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    message = {
        "id": message_id,
        "created_at": _now_iso(),
        "report_type": report_type,
        "severity": severity,
        "email_to": str(payload.get("email_to") or ""),
        "subject": str(payload.get("subject") or ""),
        "body": str(payload.get("body") or ""),
        "delivered": False,
        "delivered_at": None,
    }
    text = json.dumps(message, indent=2)
    path = outbox / f"outbox-{message_id}.json"
    atomic_write_text(path, text)
    atomic_write_text(outbox / "latest.json", text)
    return path


def list_undelivered(outbox_dir: str | Path = DEFAULT_OUTBOX_DIR) -> list[dict]:
    outbox = Path(outbox_dir)
    if not outbox.exists():
        return []
    pending: list[dict] = []
    for path in sorted(outbox.glob("outbox-*.json")):
        try:
            message = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if message.get("delivered") is False:
            message["_path"] = str(path)
            pending.append(message)
    return pending


def mark_delivered(
    message_id: str,
    outbox_dir: str | Path = DEFAULT_OUTBOX_DIR,
) -> bool:
    outbox = Path(outbox_dir)
    for path in outbox.glob("outbox-*.json"):
        try:
            message = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if message.get("id") == message_id:
            message["delivered"] = True
            message["delivered_at"] = _now_iso()
            message.pop("_path", None)
            atomic_write_text(path, json.dumps(message, indent=2))
            return True
    return False
