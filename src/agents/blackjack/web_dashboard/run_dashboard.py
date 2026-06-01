#!/usr/bin/env python3
"""
Blackjack Advisor Dashboard Launcher
Run this to start the web dashboard!

Usage:
    python run_dashboard.py

Then open http://localhost:8000 in your browser

Built with love by TradeHive
"""

import sys
import os
import webbrowser
import time
from pathlib import Path
from threading import Timer

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

def open_browser():
    """Open browser after a short delay"""
    time.sleep(1.5)
    webbrowser.open("http://localhost:8000")

def main():
    print("""
    +==============================================================+
    |                                                              |
    |   * BLACKJACK ADVISOR DASHBOARD *                            |
    |                                                              |
    |   Built with love by TradeHive                                |
    |                                                              |
    +==============================================================+
    |                                                              |
    |   KEYBOARD SHORTCUTS:                                        |
    |   ------------------------------------------------------     |
    |   A, 2-9, 0/T, J, Q, K  ->  Add card to current target       |
    |   P                     ->  Switch to Player hand            |
    |   D                     ->  Switch to Dealer                 |
    |   O                     ->  Switch to Other players          |
    |   N                     ->  New hand                         |
    |   Shift+S               ->  Shuffle deck (reset count)       |
    |                                                              |
    +==============================================================+
    |                                                              |
    |   Opening browser at http://localhost:8000                   |
    |   Press Ctrl+C to stop the server                            |
    |                                                              |
    +==============================================================+
    """)

    # Open browser after a delay
    Timer(1.5, lambda: webbrowser.open("http://localhost:8000")).start()

    try:
        import uvicorn
        uvicorn.run(
            "src.agents.blackjack.web_dashboard.api:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="warning"
        )
    except ImportError:
        print("\n  ERROR: uvicorn not installed!")
        print("  Run: pip install uvicorn fastapi\n")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n  Dashboard stopped. Good luck at the tables! ♠\n")


if __name__ == "__main__":
    main()
