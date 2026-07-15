# Runbook: Rotating your keys (plain language)

Your system uses a few secret keys to log in to services. If a key ever leaks — or
just once in a while for good hygiene — you replace it. This is called "rotation."
**You do the rotation yourself** in each service's website. The system can only
*check* that a key changed (it never sees or stores the actual key — only a short
fingerprint).

You never need to paste a key into a chat or share it with anyone. If someone or
something asks you to, stop — that's not part of this process.

## What keys exist
They all live in one file called `.env` in the trading repo. Each line is
`NAME=value`. You only ever edit the value after the `=`.

| Key name in `.env` | What it's for | Where you rotate it |
|---|---|---|
| `ALPACA_LIVE_API_KEY` / `ALPACA_LIVE_SECRET_KEY` | Real-money trading account | Alpaca dashboard → API keys (live) |
| `ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_SECRET_KEY` | Practice account | Alpaca dashboard → API keys (paper) |
| `OPENROUTER_API_KEY` | The AI research lanes | openrouter.ai → Keys |
| `SMTP_PASSWORD` | Sending your notification emails | Gmail → App passwords |

## Steps (do these in order)
1. **Pause live trading first** (so nothing trades with a half-changed key):
   `python -m cli.main policy freeze-live --reason "rotating keys"`
2. **Make the new key in the service's website.** Log in, create a new key, copy it.
3. **Put the new value in `.env`.** Open `.env`, replace the old value after the
   `=`, save. Keep the file owner-only: `chmod 600 .env`.
4. **Check it worked** without exposing anything:
   `python -m cli.main policy health-check` — the broker/login checks should be clean.
5. **Delete the old key** in the service's website (so the leaked one is dead).
6. **Un-pause when you're ready** by refreshing the safety timer (your normal arm
   step), or leave it frozen until you want to trade again.

## Verifying a rotation happened (fingerprints)
The system can store a short fingerprint of each key (a one-way code — the key can
never be reconstructed from it). Compare before/after to prove a key really changed:

- Record current fingerprints: `python -m cli.main policy key-fingerprints --record`
- After rotating, run it again without `--record`; it will tell you which keys
  changed. If a key you *didn't* rotate shows as changed, investigate.

## If a key is leaking right now (emergency)
1. Rotate that key immediately (steps 2–5 above) — the leaked one stops working the
   moment you delete it in the service.
2. Run `python -m cli.main policy scan-leaks` to find where it showed up in the
   system's files, and clean those up.
3. If it's the live trading key, also `policy freeze-live` and consider
   `policy panic-flatten` to stand down.

## Never do
- Never commit `.env` to git (the system warns you in `health-check` if it is).
- Never use the same key for live and paper (the system warns you if they match).
- Never paste a key into chat, email, or a web form that asked for it unexpectedly.
