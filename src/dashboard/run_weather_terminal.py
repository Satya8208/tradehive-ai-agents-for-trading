"""
Run the standalone Polymarket weather terminal.

Frontend: http://localhost:3020/
Backend:  http://localhost:8020/
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "src" / "dashboard" / "weather_terminal_frontend"
BACKEND_PORT = 8020
FRONTEND_PORT = 3020


def start_backend() -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.dashboard.backend.polymarket_weather_app:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(BACKEND_PORT),
        ],
        cwd=str(PROJECT_ROOT),
    )


def start_frontend() -> ThreadingHTTPServer:
    handler = partial(SimpleHTTPRequestHandler, directory=str(FRONTEND_DIR))
    return ThreadingHTTPServer(("0.0.0.0", FRONTEND_PORT), handler)


def main() -> int:
    backend = start_backend()
    frontend = start_frontend()
    stop = threading.Event()

    def handle_stop(signum, frame):
        stop.set()

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    thread = threading.Thread(target=frontend.serve_forever, daemon=True)
    thread.start()

    print(f"Weather terminal frontend: http://localhost:{FRONTEND_PORT}/")
    print(f"Weather terminal backend:  http://localhost:{BACKEND_PORT}/health")
    try:
        while not stop.is_set():
            if backend.poll() is not None:
                return backend.returncode or 1
            time.sleep(0.5)
    finally:
        frontend.shutdown()
        backend.terminate()
        try:
            backend.wait(timeout=10)
        except subprocess.TimeoutExpired:
            backend.kill()
    return 0


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    raise SystemExit(main())
