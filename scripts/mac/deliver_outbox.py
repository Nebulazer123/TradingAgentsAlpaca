"""Deliver queued notification emails from results/outbox via SMTP.

The renderers in this repo only compose messages; historically the Windows
Codex automation was the transport. On the Mac, notifications queue in
``results/outbox``. Sending requires ``--send --message-id ID`` for each
explicitly authorized message. Otherwise this script only reports the backlog,
even with SMTP credentials configured. Trading flags do not authorize email.

Configuration (all required to actually send; otherwise messages stay
queued and this script exits 0 after reporting the backlog):

    SMTP_HOST       e.g. smtp.gmail.com
    SMTP_PORT       e.g. 587
    SMTP_USERNAME   e.g. nebulazer2003@gmail.com
    SMTP_PASSWORD   an app password; never a real account password
    SMTP_TO         destination address (defaults to SMTP_USERNAME)

Credentials load from the repo .env (the package bootstraps python-dotenv).
"""

from __future__ import annotations

import argparse
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import tradingagents  # noqa: E402, F401  (loads .env)
from tradingagents.notifications.outbox import (  # noqa: E402
    list_undelivered,
    mark_delivered,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="Send explicitly authorized message IDs")
    parser.add_argument("--message-id", action="append", default=[], help="Authorized queued ID; repeat for several")
    args = parser.parse_args(argv)
    if args.send != bool(args.message_id):
        parser.error("delivery requires both --send and at least one --message-id")
    outbox_dir = REPO_ROOT / "results" / "outbox"
    pending = list_undelivered(outbox_dir)
    if not args.send:
        print(f"outbox preview: {len(pending)} message(s) queued")
        return 0
    requested = set(args.message_id)
    if requested - {item["id"] for item in pending}:
        parser.error("one or more requested message IDs are not queued; nothing sent")
    pending = [item for item in pending if item["id"] in requested]
    if len(pending) != len(requested):
        parser.error("requested message IDs are ambiguous; nothing sent")

    host = os.environ.get("SMTP_HOST", "").strip()
    port = os.environ.get("SMTP_PORT", "").strip()
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    to_addr = os.environ.get("SMTP_TO", "").strip() or username

    if not (host and port and username and password):
        print(
            f"{len(pending)} message(s) queued; SMTP_HOST/SMTP_PORT/"
            "SMTP_USERNAME/SMTP_PASSWORD not fully configured, leaving queued"
        )
        return 0

    delivered = 0
    with smtplib.SMTP(host, int(port), timeout=30) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        for item in pending:
            message = EmailMessage()
            message["From"] = username
            message["To"] = to_addr
            message["Subject"] = item.get("subject", "TradingAgents update")
            message.set_content(item.get("body", ""))
            smtp.send_message(message)
            mark_delivered(item["id"], outbox_dir)
            delivered += 1
    print(f"delivered {delivered} message(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
