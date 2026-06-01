#!/usr/bin/env python3
"""
Poker Advisor Web Dashboard - Startup Script
Built with love by TradeHive

Usage:
    python run_dashboard.py

Then open http://localhost:8001 in your browser
"""

import sys
from pathlib import Path

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def main():
    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn not installed. Run: pip install uvicorn")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  POKER ADVISOR WEB DASHBOARD")
    print("  GTO + Exploitative Play | Cash & Tournaments")
    print("  Built with love by TradeHive")
    print("=" * 60)
    print("\n  Open http://localhost:8001 in your browser")
    print("\n  Press Ctrl+C to stop the server")
    print("=" * 60 + "\n")

    # Run the FastAPI app
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info"
    )


if __name__ == "__main__":
    main()
