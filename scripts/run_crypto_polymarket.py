#!/usr/bin/env python3
"""
Legacy Polymarket runner.

This wrapper is intentionally kept as a compatibility stub so older shell
aliases fail safely instead of importing the removed crypto_polymarket module.
"""

from __future__ import annotations

import argparse
import sys


DEPRECATION_MESSAGE = """\
scripts/run_crypto_polymarket.py is deprecated.

Use one of the maintained entrypoints instead:
  python -m src.agents.polymarket_trader.paper_run --cycles 5
  python -m src.agents.polymarket_trader.live_run --confirm-live --cycles 1

This legacy script no longer imports the removed src.agents.crypto_polymarket package.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deprecated Polymarket runner")
    parser.add_argument("--mode", default="paper", help="Legacy mode flag retained for compatibility")
    parser.add_argument("--status", action="store_true", help="Ignored. Use the new entrypoints above.")
    parser.add_argument("--no-banner", action="store_true", help="Ignored compatibility flag.")
    return parser


def main() -> int:
    parser = build_parser()
    parser.parse_args()
    print(DEPRECATION_MESSAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
