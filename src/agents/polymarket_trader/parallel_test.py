"""
Parallel Timeframe Edge Testing

Launches 5 independent paper trading sessions, one per timeframe bucket,
to discover which market expiry windows produce the best trading edge.

Usage:
    python -m src.agents.polymarket_trader.parallel_test --cycles 2 --balance 50
    python -m src.agents.polymarket_trader.parallel_test --cycles 20 --balance 50
"""

import argparse
import json
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from termcolor import cprint

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

TIMEFRAME_BUCKETS = [
    {
        "name": "ultra_short",
        "label": "5-15min",
        "min_expiry_hours": None,
        "max_expiry_hours": 0.25,
        "default_interval": 30,
    },
    {
        "name": "short",
        "label": "15min-1hr",
        "min_expiry_hours": 0.25,
        "max_expiry_hours": 1.0,
        "default_interval": 45,
    },
    {
        "name": "intraday",
        "label": "1hr-4hr",
        "min_expiry_hours": 1.0,
        "max_expiry_hours": 4.0,
        "default_interval": 60,
    },
    {
        "name": "daily",
        "label": "4hr-24hr",
        "min_expiry_hours": 4.0,
        "max_expiry_hours": 24.0,
        "default_interval": 60,
    },
    {
        "name": "weekly",
        "label": "1-7 days",
        "min_expiry_hours": 24.0,
        "max_expiry_hours": 168.0,
        "default_interval": 90,
    },
]


def build_command(bucket: dict, cycles: int, balance: float, markets: int) -> list:
    data_dir = PROJECT_ROOT / "src" / "data" / f"polymarket_trader_{bucket['name']}"
    cmd = [
        sys.executable, "-m", "src.agents.polymarket_trader.paper_run",
        "--balance", str(balance),
        "--cycles", str(cycles),
        "--markets", str(markets),
        "--interval", str(bucket["default_interval"]),
        "--data-dir", str(data_dir),
    ]
    if bucket["max_expiry_hours"] is not None:
        cmd += ["--max-expiry-hours", str(bucket["max_expiry_hours"])]
    if bucket["min_expiry_hours"] is not None:
        cmd += ["--min-expiry-hours", str(bucket["min_expiry_hours"])]
    return cmd


def read_progress(bucket_name: str) -> dict:
    risk_path = PROJECT_ROOT / "src" / "data" / f"polymarket_trader_{bucket_name}" / "positions" / "risk_state.json"
    cycles_dir = PROJECT_ROOT / "src" / "data" / f"polymarket_trader_{bucket_name}" / "cycles"

    cycle_count = 0
    if cycles_dir.exists():
        cycle_count = len(list(cycles_dir.glob("cycle_*.json")))

    positions = 0
    daily_pnl = 0.0
    trades = 0
    if risk_path.exists():
        try:
            rs = json.loads(risk_path.read_text())
            positions = len(rs.get("positions", []))
            daily_pnl = rs.get("daily_pnl", 0.0)
            trades = rs.get("daily_trade_count", 0)
        except (json.JSONDecodeError, KeyError):
            pass

    return {
        "cycles": cycle_count,
        "positions": positions,
        "daily_pnl": daily_pnl,
        "trades": trades,
    }


def print_progress(processes: dict, target_cycles: int):
    cprint("\n--- Progress Update ---", "cyan")
    for bucket in TIMEFRAME_BUCKETS:
        name = bucket["name"]
        proc = processes.get(name)
        alive = proc and proc.poll() is None
        status = "RUNNING" if alive else "DONE" if proc else "N/A"

        progress = read_progress(name)
        line = (
            f"  {name:<14} [{status:>7}] "
            f"cycles={progress['cycles']}/{target_cycles}  "
            f"trades={progress['trades']}  "
            f"pos={progress['positions']}  "
            f"pnl=${progress['daily_pnl']:+.2f}"
        )
        color = "green" if alive else "white"
        cprint(line, color)
    cprint("", "white")


def main():
    parser = argparse.ArgumentParser(description="Parallel Timeframe Edge Testing")
    parser.add_argument("--cycles", type=int, default=50, help="Cycles per bucket (default: 50)")
    parser.add_argument("--balance", type=float, default=50.0, help="Paper balance per bucket (default: $50)")
    parser.add_argument("--markets", type=int, default=3, help="Markets per cycle (default: 3)")
    parser.add_argument("--stagger", type=int, default=15, help="Seconds between bucket launches (default: 15)")
    parser.add_argument("--monitor-interval", type=int, default=60, help="Seconds between progress checks (default: 60)")
    parser.add_argument("--clean", action="store_true", help="Delete existing bucket data before starting")
    args = parser.parse_args()

    cprint("""
    ============================================================
      PARALLEL TIMEFRAME EDGE TEST
      5 buckets x {cycles} cycles x {markets} markets/cycle
      ${balance:.0f} paper balance per bucket
    ============================================================
    """.format(cycles=args.cycles, markets=args.markets, balance=args.balance), "cyan", attrs=["bold"])

    for b in TIMEFRAME_BUCKETS:
        cprint(f"  {b['name']:<14} {b['label']:<12} interval={b['default_interval']}s", "white")
    cprint("", "white")

    if args.clean:
        cprint("  Cleaning existing bucket data...", "yellow")
        for bucket in TIMEFRAME_BUCKETS:
            data_dir = PROJECT_ROOT / "src" / "data" / f"polymarket_trader_{bucket['name']}"
            if data_dir.exists():
                shutil.rmtree(data_dir)
                cprint(f"    Removed {data_dir.name}/", "yellow")
        cprint("", "white")

    processes = {}
    shutdown = False

    def handle_sigint(sig, frame):
        nonlocal shutdown
        if shutdown:
            cprint("\nForce kill...", "red")
            for p in processes.values():
                if p.poll() is None:
                    p.kill()
            sys.exit(1)
        shutdown = True
        cprint("\nShutting down all buckets (Ctrl+C again to force)...", "yellow")
        for name, p in processes.items():
            if p.poll() is None:
                p.send_signal(signal.SIGINT)

    signal.signal(signal.SIGINT, handle_sigint)

    # Launch buckets with stagger
    for i, bucket in enumerate(TIMEFRAME_BUCKETS):
        if shutdown:
            break
        cmd = build_command(bucket, args.cycles, args.balance, args.markets)
        log_path = PROJECT_ROOT / "src" / "data" / f"polymarket_trader_{bucket['name']}" / "run.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "w")

        cprint(f"  Launching {bucket['name']} ({bucket['label']})...", "green")
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )
        processes[bucket["name"]] = proc

        if i < len(TIMEFRAME_BUCKETS) - 1 and not shutdown:
            time.sleep(args.stagger)

    cprint(f"\n  All {len(processes)} buckets launched. Monitoring...\n", "cyan")

    # Monitor loop
    while not shutdown:
        all_done = all(p.poll() is not None for p in processes.values())
        if all_done:
            break
        time.sleep(args.monitor_interval)
        if not shutdown:
            print_progress(processes, args.cycles)

    # Wait for all to finish
    cprint("\nWaiting for processes to finish...", "yellow")
    for name, p in processes.items():
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            cprint(f"  {name} timed out, killing...", "red")
            p.kill()
            p.wait()

    # Print exit codes
    cprint("\n--- Exit Status ---", "cyan")
    for name, p in processes.items():
        code = p.returncode
        color = "green" if code == 0 else "yellow" if code == -2 else "red"
        cprint(f"  {name:<14} exit={code}", color)

    # Aggregate results
    cprint("\nAggregating results...", "cyan")
    from .results_aggregator import aggregate
    aggregate()


if __name__ == "__main__":
    main()
