"""
Launcher for the Live Blackjack Table.

Usage:
    python -m src.agents.blackjack.live_table.run
"""

from __future__ import annotations

import sys
import threading
import time
import webbrowser
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import uvicorn  # noqa: E402

HOST = "127.0.0.1"
PORT = 8765


def _open_browser_after_delay() -> None:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return
    time.sleep(1.0)
    try:
        webbrowser.open(f"http://{HOST}:{PORT}/")
    except Exception:
        # Headless terminals often have no desktop opener; the printed URL is enough.
        pass


def main() -> None:
    print(f"\n  LIVE BLACKJACK TABLE")
    print(f"  Serving on http://{HOST}:{PORT}\n")
    threading.Thread(target=_open_browser_after_delay, daemon=True).start()
    uvicorn.run(
        "src.agents.blackjack.live_table.api:app",
        host=HOST,
        port=PORT,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
