#!/usr/bin/env python3
"""
🥜 Nirvana Nuts Web Dashboard - Startup Script
Twitter Growth Engine by TradeHive

Usage:
    python run_dashboard.py

Then open http://localhost:8000 in your browser
"""

import sys
from pathlib import Path

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def main():
    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn not installed. Run: pip install uvicorn")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  🥜 NIRVANA NUTS GROWTH ENGINE")
    print("  Twitter Growth & Engagement AI")
    print("  Built with love by TradeHive")
    print("=" * 60)
    print("\n  Open http://localhost:8050 in your browser")
    print("\n  Press Ctrl+C to stop the server")
    print("=" * 60 + "\n")

    # Open browser automatically
    try:
        import webbrowser
        import threading
        import time

        def open_browser():
            time.sleep(1.5)  # Wait for server to start
            webbrowser.open("http://localhost:8050")

        threading.Thread(target=open_browser).start()
    except Exception:
        pass

    # Run the FastAPI app
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8050,
        reload=True,
        log_level="info"
    )


if __name__ == "__main__":
    main()
