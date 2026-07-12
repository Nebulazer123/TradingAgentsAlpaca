#!/usr/bin/env python3
"""
Start the n8n runner bridge for TradingAgents.

This bridge exposes allowlisted jobs to n8n over HTTP.
Usage:
  python -m tradingagents.orchestration.n8n_runner --host 127.0.0.1 --port 8765
"""

if __name__ == "__main__":
    import sys
    sys.argv.extend(["--host", "127.0.0.1", "--port", "8765"])
    
    # Import and run the runner
    from tradingagents.orchestration.n8n_runner import main
    main()
