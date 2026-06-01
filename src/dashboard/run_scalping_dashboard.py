"""
Scalping Agent Dashboard Launcher
Starts both the FastAPI backend (port 8010) and React frontend
"""

import subprocess
import sys
import os
import time
import webbrowser
from pathlib import Path

# Paths
DASHBOARD_DIR = Path(__file__).parent
BACKEND_DIR = DASHBOARD_DIR / "backend"
FRONTEND_DIR = DASHBOARD_DIR / "frontend"
PROJECT_ROOT = DASHBOARD_DIR.parent.parent

def print_banner():
    banner = """
    ╔════════════════════════════════════════════════════════════╗
    ║                                                            ║
    ║    🎯  SCALPING AGENT DASHBOARD                           ║
    ║                                                            ║
    ║    AI-Powered Trading Strategy Generation                  ║
    ║                                                            ║
    ║    Modes: PIRANHA | SHARK | WHALE | VIPER                 ║
    ║                                                            ║
    ╚════════════════════════════════════════════════════════════╝
    """
    print(banner)

def main():
    print_banner()

    print("━" * 60)
    print("  Backend API:   http://localhost:8010")
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

    # Start scalping backend on port 8010
    backend_process = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "src.dashboard.backend.scalping_api:app",
            "--reload",
            "--port", "8010",
            "--host", "0.0.0.0"
        ],
        cwd=PROJECT_ROOT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    )

    # Give backend time to start
    time.sleep(2)

    # Prepare frontend env - set mode to scalping
    frontend_env = os.environ.copy()
    frontend_env["VITE_APP_MODE"] = "scalping"

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
    print("  🎯 Scalping Dashboard is running!")
    print("  📊 Open http://localhost:3000 in your browser")
    print("━" * 60)

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
