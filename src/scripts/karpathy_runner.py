"""
Karpathy Runner — Stack Zero-Cost Optimization Loops

Launches poker, blackjack, and polymarket auto-optimizers in parallel.
All run with ZERO API calls (pure simulation / historical replay).

Usage:
    python src/scripts/karpathy_runner.py                          # full run
    python src/scripts/karpathy_runner.py --dry-run                # print commands only
    python src/scripts/karpathy_runner.py --poker-rounds 5 --bj-rounds 5 --poly-rounds 5  # smoke test
"""

import argparse
import csv
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from termcolor import cprint

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# TSV paths (defaults used by each optimizer)
POKER_TSV = PROJECT_ROOT / "src/data/poker_agent/optimization_results.tsv"
POLY_TSV = PROJECT_ROOT / "src/data/polymarket_trader/optimization_results.tsv"

# Unbuffered env so subprocess logs stream in real-time
UNBUF_ENV = {**os.environ, "PYTHONUNBUFFERED": "1"}

# Global state for signal handling
ALL_PROCESSES = []       # all Popen objects
PROC_NAMES = {}          # pid -> name mapping
SHUTDOWN = False


def parse_args():
    parser = argparse.ArgumentParser(
        description="Karpathy Runner — Stack Zero-Cost Optimization Loops"
    )
    parser.add_argument("--poker-rounds", type=int, default=500)
    parser.add_argument("--bj-rounds", type=int, default=200,
                        help="Rounds per BJ profile")
    parser.add_argument("--poly-rounds", type=int, default=500)
    parser.add_argument("--bj-profiles", type=str, default="live_75pen,coin_casino",
                        help="Comma-separated BJ profiles")
    parser.add_argument("--monitor-interval", type=int, default=60,
                        help="Seconds between progress prints")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print commands without executing")
    return parser.parse_args()


def create_run_dir():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = PROJECT_ROOT / "src/data/karpathy_runs" / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def archive_tsv(tsv_path: Path, run_dir: Path):
    """Rename existing TSV so optimizer starts fresh."""
    if tsv_path.exists() and tsv_path.stat().st_size > 0:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = tsv_path.with_suffix(f".{ts}.bak")
        tsv_path.rename(backup)
        cprint(f"  Archived: {tsv_path.name} -> {backup.name}", "yellow")


def count_tsv_rounds(tsv_path: Path) -> int:
    """Count completed rounds from TSV line count."""
    if not tsv_path.exists():
        return 0
    try:
        with open(tsv_path) as f:
            lines = sum(1 for _ in f)
        return max(0, lines - 2)  # minus header and baseline
    except Exception:
        return 0


def read_tsv_summary(tsv_path: Path) -> dict:
    """Read a TSV and return summary stats."""
    if not tsv_path.exists():
        return None
    try:
        with open(tsv_path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)
    except Exception:
        return None

    if not rows:
        return None

    baseline_score = float(rows[0].get("score", 0))
    best_row = max(rows, key=lambda r: float(r.get("score", 0)))
    best_score = float(best_row["score"])
    improvements = sum(1 for r in rows if r.get("status") == "keep")
    total_rounds = len(rows) - 1  # subtract baseline

    return {
        "rounds": total_rounds,
        "improvements": improvements,
        "improvement_rate": improvements / max(total_rounds, 1),
        "baseline_score": baseline_score,
        "best_score": best_score,
        "best_row": best_row,
    }


def launch_process(cmd, log_path: Path, label: str, name: str = None):
    """Launch a subprocess with output piped to a log file."""
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=str(PROJECT_ROOT),
        env=UNBUF_ENV,
    )
    ALL_PROCESSES.append(proc)
    if name:
        PROC_NAMES[proc.pid] = name
    cprint(f"  Launched: {label} (PID {proc.pid}) -> {log_path.name}", "green")
    return proc, log_file


def run_bj_chain(profiles, rounds, run_dir):
    """Run BJ profiles sequentially. Called from a thread."""
    global SHUTDOWN
    for profile in profiles:
        if SHUTDOWN:
            break
        output_path = run_dir / f"bj_{profile}.tsv"
        cmd = [
            sys.executable, "-m", "src.agents.blackjack.auto_optimize",
            "--rounds", str(rounds),
            "--hands", "10000",
            "--sessions", "3",
            "--profile", profile,
            "--output", str(output_path),
        ]
        label = f"Blackjack ({profile})"
        log_path = run_dir / f"bj_{profile}.log"

        log_file = open(log_path, "w")
        proc = subprocess.Popen(
            cmd, stdout=log_file, stderr=subprocess.STDOUT,
            cwd=str(PROJECT_ROOT), env=UNBUF_ENV,
        )
        ALL_PROCESSES.append(proc)
        name = f"bj_{profile}"
        PROC_NAMES[proc.pid] = name
        cprint(f"  Launched: {label} (PID {proc.pid}) -> {log_path.name}", "green")

        proc.wait()
        log_file.close()

        if proc.returncode != 0 and not SHUTDOWN:
            cprint(f"  Warning: {label} exited with code {proc.returncode}", "yellow")


def setup_signal_handler():
    """Graceful Ctrl+C: first sends SIGINT to children, second force-kills."""
    def handler(sig, frame):
        global SHUTDOWN
        if SHUTDOWN:
            cprint("\nForce killing all processes...", "red")
            for p in ALL_PROCESSES:
                if p.poll() is None:
                    p.kill()
            sys.exit(1)
        SHUTDOWN = True
        cprint("\nShutting down (Ctrl+C again to force)...", "yellow")
        for p in ALL_PROCESSES:
            if p.poll() is None:
                p.send_signal(signal.SIGINT)

    signal.signal(signal.SIGINT, handler)


def _is_name_running(name):
    """Check if any process registered under this name is still running."""
    for proc in ALL_PROCESSES:
        if PROC_NAMES.get(proc.pid) == name and proc.poll() is None:
            return True
    return False


def monitor_loop(tsv_map, targets, interval, bj_thread):
    """Print progress every interval seconds until all done."""
    global SHUTDOWN
    while not SHUTDOWN:
        time.sleep(interval)
        if SHUTDOWN:
            break

        # Check if everything is done
        all_done = all(p.poll() is not None for p in ALL_PROCESSES)
        if not bj_thread.is_alive() and all_done:
            break

        cprint(f"\n  --- Progress ({_elapsed()}) ---", "cyan")
        for name, tsv_path in tsv_map.items():
            rounds_done = count_tsv_rounds(tsv_path)
            target = targets.get(name, "?")
            running = _is_name_running(name)
            if running:
                status = "RUNNING"
            elif rounds_done > 0:
                status = "DONE"
            elif name.startswith("bj_") and bj_thread.is_alive():
                status = "PENDING"
            else:
                status = "WAITING"
            cprint(f"  {name:20s} [{status:7s}]  {rounds_done}/{target} rounds", "cyan")
        cprint(f"  ---", "cyan")

        if all_done and not bj_thread.is_alive():
            break


_START_TIME = None


def _elapsed():
    if _START_TIME is None:
        return "0s"
    secs = int(time.time() - _START_TIME)
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    secs = secs % 60
    if mins < 60:
        return f"{mins}m {secs}s"
    hrs = mins // 60
    mins = mins % 60
    return f"{hrs}h {mins}m"


def print_banner(args, profiles):
    cprint("=" * 70, "cyan")
    cprint("  KARPATHY RUNNER — Stacked Zero-Cost Optimization Loops", "cyan", attrs=["bold"])
    cprint("=" * 70, "cyan")
    cprint(f"  Poker:       {args.poker_rounds} rounds  (1000 hands x 3 sessions/round)", "cyan")
    cprint(f"  Polymarket:  {args.poly_rounds} rounds  (historical trade replay)", "cyan")
    for p in profiles:
        cprint(f"  Blackjack:   {args.bj_rounds} rounds  ({p})", "cyan")
    cprint(f"  Monitor:     every {args.monitor_interval}s", "cyan")
    cprint("=" * 70, "cyan")
    print()


def print_final_summary(tsv_map, start_time):
    elapsed = time.time() - start_time
    mins = int(elapsed) // 60
    secs = int(elapsed) % 60

    cprint("\n" + "=" * 70, "cyan")
    cprint("  KARPATHY RUNNER — FINAL REPORT", "cyan", attrs=["bold"])
    cprint(f"  Runtime: {mins}m {secs}s", "cyan")
    cprint("=" * 70, "cyan")

    for name, tsv_path in tsv_map.items():
        summary = read_tsv_summary(tsv_path)
        print()
        if summary is None:
            cprint(f"  {name}: No results (TSV missing or empty)", "red")
            continue

        s = summary
        pct_change = ((s["best_score"] - s["baseline_score"]) / abs(s["baseline_score"]) * 100
                      if s["baseline_score"] != 0 else 0)
        sign = "+" if pct_change >= 0 else ""

        cprint(f"  {name}", "white", attrs=["bold"])
        cprint(f"  Rounds: {s['rounds']}  |  "
               f"Improvements: {s['improvements']} ({s['improvement_rate']:.1%})", "white")

        if s["best_score"] > s["baseline_score"]:
            cprint(f"  Baseline: {s['baseline_score']:.2f}  ->  "
                   f"Best: {s['best_score']:.2f}  ({sign}{pct_change:.1f}%)", "green")
        else:
            cprint(f"  Baseline: {s['baseline_score']:.2f}  ->  "
                   f"Best: {s['best_score']:.2f}  (no improvement)", "yellow")

        # Print key metrics from best row
        row = s["best_row"]
        metrics = []
        for key in ["bb_per_100", "win_rate", "pnl", "hourly_rate", "roi",
                     "hands", "trades"]:
            if key in row and row[key]:
                val = row[key]
                if key == "win_rate":
                    val = f"{float(val):.1%}"
                elif key in ("pnl", "hourly_rate"):
                    val = f"${float(val):+.2f}"
                elif key == "roi":
                    val = f"{float(val):.1%}"
                metrics.append(f"{key}={val}")
        if metrics:
            cprint(f"  Best: {' | '.join(metrics)}", "white")

        cprint(f"  TSV: {tsv_path}", "white")

    cprint("\n" + "=" * 70, "cyan")
    print()


def main():
    global _START_TIME, SHUTDOWN

    args = parse_args()
    profiles = [p.strip() for p in args.bj_profiles.split(",") if p.strip()]

    print_banner(args, profiles)

    if args.dry_run:
        cprint("DRY RUN — commands that would execute:\n", "yellow")
        cprint(f"  python -m src.agents.poker.auto_optimize "
               f"--rounds {args.poker_rounds} --hands 1000 --sessions 3", "white")
        cprint(f"  python -m src.agents.polymarket_trader.auto_optimize "
               f"--rounds {args.poly_rounds}", "white")
        for p in profiles:
            cprint(f"  python -m src.agents.blackjack.auto_optimize "
                   f"--rounds {args.bj_rounds} --hands 10000 --sessions 3 "
                   f"--profile {p} --output <run_dir>/bj_{p}.tsv", "white")
        return

    # Setup
    run_dir = create_run_dir()
    cprint(f"Run directory: {run_dir}\n", "cyan")

    # Archive existing TSVs so optimizers start fresh
    cprint("Archiving existing results...", "yellow")
    archive_tsv(POKER_TSV, run_dir)
    archive_tsv(POLY_TSV, run_dir)
    print()

    # Build TSV map for monitoring
    tsv_map = {"poker": POKER_TSV, "polymarket": POLY_TSV}
    targets = {
        "poker": args.poker_rounds,
        "polymarket": args.poly_rounds,
    }
    for p in profiles:
        key = f"bj_{p}"
        tsv_map[key] = run_dir / f"{key}.tsv"
        targets[key] = args.bj_rounds

    # Signal handler
    setup_signal_handler()

    _START_TIME = time.time()

    # Launch poker
    cprint("Launching optimizers...", "green")
    poker_proc, poker_log = launch_process(
        [sys.executable, "-m", "src.agents.poker.auto_optimize",
         "--rounds", str(args.poker_rounds), "--hands", "1000", "--sessions", "3"],
        run_dir / "poker.log", "Poker Strategy", name="poker",
    )

    # Launch polymarket
    poly_proc, poly_log = launch_process(
        [sys.executable, "-m", "src.agents.polymarket_trader.auto_optimize",
         "--rounds", str(args.poly_rounds)],
        run_dir / "polymarket.log", "Polymarket Trading", name="polymarket",
    )

    # Launch BJ chain in a thread
    bj_thread = threading.Thread(
        target=run_bj_chain,
        args=(profiles, args.bj_rounds, run_dir),
        daemon=True,
    )
    bj_thread.start()

    print()

    # Monitor
    monitor_loop(tsv_map, targets, args.monitor_interval, bj_thread)

    # Wait for everything
    cprint("\nWaiting for processes to finish...", "yellow")
    poker_proc.wait(timeout=60)
    poly_proc.wait(timeout=60)
    bj_thread.join(timeout=120)

    # Close log files
    poker_log.close()
    poly_log.close()

    # Final summary
    print_final_summary(tsv_map, _START_TIME)

    cprint(f"Logs and results: {run_dir}", "cyan")


if __name__ == "__main__":
    main()
