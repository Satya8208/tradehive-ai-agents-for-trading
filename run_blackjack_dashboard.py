"""
Blackjack Twitter Dashboard Launcher
Starts both the FastAPI backend (port 8002) and React frontend
"""

import subprocess
import sys
import os
import time
import webbrowser
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).parent
DASHBOARD_DIR = PROJECT_ROOT / "src" / "dashboard"
BACKEND_DIR = DASHBOARD_DIR / "backend"
FRONTEND_DIR = DASHBOARD_DIR / "frontend"

def print_banner():
    banner = """
    ╔════════════════════════════════════════════════════════════╗
    ║                                                            ║
    ║    🃏  BLACKJACK TWITTER DASHBOARD                        ║
    ║                                                            ║
    ║    The High Roller's Command Center                        ║
    ║                                                            ║
    ║    Modes: CARD COUNTER | HIGH ROLLER | TABLE READER       ║
    ║           BANKROLL MGR | THE DEALER | SHARK               ║
    ║                                                            ║
    ╚════════════════════════════════════════════════════════════╝
    """
    print(banner)

def main():
    print_banner()

    print("━" * 60)
    print("  Backend API:   http://localhost:8002")
    print("  Frontend UI:   http://localhost:3000")
    print("━" * 60)

    # Check if node_modules exists
    if not (FRONTEND_DIR / "node_modules").exists():
        print("\n📦 Installing frontend dependencies...")
        subprocess.run(
            ["npm", "install"],
            cwd=FRONTEND_DIR,
            shell=True
        )

    print("\n🚀 Starting servers...")
    print("\n   Press Ctrl+C to stop both servers\n")

    # Start blackjack backend on port 8002
    backend_process = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "src.dashboard.backend.blackjack_api:app",
            "--reload",
            "--port", "8002",
            "--host", "0.0.0.0"
        ],
        cwd=PROJECT_ROOT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    )

    # Give backend time to start
    time.sleep(2)

    # Prepare frontend env - set mode to blackjack
    frontend_env = os.environ.copy()
    frontend_env["VITE_APP_MODE"] = "blackjack"

    # Start frontend
    frontend_process = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=FRONTEND_DIR,
        shell=True,
        env=frontend_env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    )

    # Open browser after a delay
    time.sleep(3)
    webbrowser.open("http://localhost:3000")

    print("\n" + "━" * 60)
    print("  🃏 Blackjack Dashboard is running!")
    print("  🎰 Open http://localhost:3000 in your browser")
    print("━" * 60)

    try:
        # Wait for processes
        backend_process.wait()
        frontend_process.wait()
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down...")
        backend_process.terminate()
        frontend_process.terminate()
        print("👋 The house always wins... but you cashed out smart!")


if __name__ == "__main__":
    main()
