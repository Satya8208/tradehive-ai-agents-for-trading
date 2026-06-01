"""
TradeHive Dashboard Launcher
Starts both the FastAPI backend and React frontend
Supports modes: 'operator', 'poker', 'nuts', 'all'
"""

import subprocess
import sys
import os
import time
import webbrowser
import argparse
from pathlib import Path

# Paths
DASHBOARD_DIR = Path(__file__).parent
BACKEND_DIR = DASHBOARD_DIR / "backend"
FRONTEND_DIR = DASHBOARD_DIR / "frontend"
PROJECT_ROOT = DASHBOARD_DIR.parent.parent

def main():
    parser = argparse.ArgumentParser(description="TradeHive Agents Dashboard")
    parser.add_argument("--mode", type=str, default="operator", choices=["operator", "poker", "nuts", "all"],
                      help="Dashboard mode: 'operator', 'poker', 'nuts', or 'all'")
    args = parser.parse_args()

    title = "TRADEHIVE AGENTS DASHBOARD"
    if args.mode == "operator":
        title = "♠ OPERATOR COCKPIT"
    elif args.mode == "poker":
        title = "🎰 POKER GOD DASHBOARD"
    elif args.mode == "nuts":
        title = "🥜 NIRVANA NUTS DASHBOARD"

    print(f"\n{title}")
    print("━" * 40)
    print(f"Mode: {args.mode.upper()}")

    # Check if node_modules exists
    if not (FRONTEND_DIR / "node_modules").exists():
        print("\n📦 Installing frontend dependencies...")
        subprocess.run(
            ["npm", "install"],
            cwd=FRONTEND_DIR,
            shell=True
        )

    print("\n🚀 Starting servers...")
    print("   Backend:  http://localhost:8000")
    print("   Frontend: http://localhost:3000")
    print("\n   Press Ctrl+C to stop both servers\n")

    # Start backend
    backend_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.dashboard.backend.api:app", "--reload", "--port", "8000"],
        cwd=PROJECT_ROOT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    )

    # Give backend time to start
    time.sleep(2)

    # Prepare frontend env
    frontend_env = os.environ.copy()
    frontend_env["VITE_APP_MODE"] = args.mode

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

    try:
        # Wait for processes
        backend_process.wait()
        frontend_process.wait()
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down...")
        backend_process.terminate()
        frontend_process.terminate()
        print("👋 Goodbye!")


if __name__ == "__main__":
    main()
