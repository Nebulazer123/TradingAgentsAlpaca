#!/usr/bin/env python3
"""Direct entry point avoiding tradingagents.__init__ and its dotenv loading."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def main() -> int:
    path = Path(__file__).resolve().parents[1] / "tradingagents/dataflows/alpaca_source_probe.py"
    spec = importlib.util.spec_from_file_location("_ta_alpaca_source_probe", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot locate the source-probe module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
