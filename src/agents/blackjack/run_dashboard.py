#!/usr/bin/env python3
"""
🎰 Blackjack Twitter Dashboard Launcher
Run: python run_dashboard.py
Then open: http://localhost:8051
"""

import subprocess
import sys
from pathlib import Path

def main():
    print("\n" + "=" * 50)
    print("🎰 BLACKJACK TWITTER DASHBOARD")
    print("=" * 50)
    print("\nStarting server on http://localhost:8051")
    print("The house edge is ignorance. Your edge is wisdom.")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 50 + "\n")

    # Run the API
    api_path = Path(__file__).parent / "api.py"
    subprocess.run([sys.executable, str(api_path)])


if __name__ == "__main__":
    main()
