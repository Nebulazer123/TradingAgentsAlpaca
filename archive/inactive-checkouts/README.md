# Inactive TradingAgents Checkout Recovery

The canonical working repository is `/Users/corbinfloyd/Documents/TradingAgents`.
These artifacts preserve the complete local state of checkouts retired during
the 2026-08-10 repository consolidation. Validate them with:

```zsh
cd /Users/corbinfloyd/Documents/TradingAgents/archive/inactive-checkouts
shasum -a 256 -c SHA256SUMS.txt
```

## Autonomous-firm worktree

- Source: `/Users/corbinfloyd/.codex/worktrees/tradingagents-autonomous-firm`
- Branch retained in the canonical repository: `codex/autonomous-trading-firm`
- HEAD: `6f8fa28025843fb87423c56716e8f77f741f0c67`
- Complete local archive: `tradingagents-autonomous-firm-2026-08-10.tar.gz`

Restore to a temporary inspection directory:

```zsh
mkdir -p /tmp/tradingagents-autonomous-firm-restore
tar -xzf tradingagents-autonomous-firm-2026-08-10.tar.gz \
  -C /tmp/tradingagents-autonomous-firm-restore
```

Create a fresh registered worktree from the retained branch:

```zsh
git -C /Users/corbinfloyd/Documents/TradingAgents worktree add \
  /tmp/tradingagents-autonomous-firm-worktree codex/autonomous-trading-firm
```

## Fable worktree

- Source: `/Users/corbinfloyd/Documents/TradingAgents/01_REPO/tradingagents-fable`
- Branch retained in the canonical repository: `fable`
- HEAD: `44074fee2eca65780d27e9e8a7fbf8d8251337bb`
- Complete local archive: `tradingagents-fable-2026-08-10.tar.gz`

Restore to a temporary inspection directory:

```zsh
mkdir -p /tmp/tradingagents-fable-restore
tar -xzf tradingagents-fable-2026-08-10.tar.gz \
  -C /tmp/tradingagents-fable-restore
```

Create a fresh registered worktree from the retained branch:

```zsh
git -C /Users/corbinfloyd/Documents/TradingAgents worktree add \
  /tmp/tradingagents-fable-worktree fable
```

## Public repository clone

- Source: `/Users/corbinfloyd/Documents/TradingAgentsAlpaca-public`
- Branch: `main`
- HEAD: `82353331a387307924e45a242b70527a45e91f23`
- Original remote: `https://github.com/Nebulazer123/TradingAgentsAlpaca.git`
- Complete local archive: `TradingAgentsAlpaca-public-2026-08-10.tar.gz`
- Complete Git history: `TradingAgentsAlpaca-public-2026-08-10.bundle`

Restore the complete directory snapshot:

```zsh
mkdir -p /tmp/tradingagents-public-restore
tar -xzf TradingAgentsAlpaca-public-2026-08-10.tar.gz \
  -C /tmp/tradingagents-public-restore
```

Clone only the Git history:

```zsh
git clone TradingAgentsAlpaca-public-2026-08-10.bundle \
  /tmp/TradingAgentsAlpaca-public
```

`SHA256SUMS.txt` binds all four recovery artifacts.
