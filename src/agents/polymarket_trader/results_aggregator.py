"""
Results Aggregator for Parallel Timeframe Edge Testing

Reads data from all timeframe bucket directories and produces a comparison table
with realized PnL, win/loss tracking, fees, and ROI.

Usage:
    python -m src.agents.polymarket_trader.results_aggregator
    python -m src.agents.polymarket_trader.results_aggregator --data-root src/data
"""

import argparse
import json
from pathlib import Path
from termcolor import cprint

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

BUCKETS = [
    ("ultra_short", "5-15min"),
    ("short", "15min-1hr"),
    ("intraday", "1hr-4hr"),
    ("daily", "4hr-24hr"),
    ("weekly", "1-7 days"),
]


def load_trades(data_dir: Path) -> list:
    trades_dir = data_dir / "trades"
    if not trades_dir.exists():
        return []
    trades = []
    for f in sorted(trades_dir.glob("trades_*.jsonl")):
        for line in f.read_text().strip().split("\n"):
            if line.strip():
                trades.append(json.loads(line))
    return trades


def load_risk_state(data_dir: Path) -> dict:
    rs = data_dir / "positions" / "risk_state.json"
    if rs.exists():
        return json.loads(rs.read_text())
    return {}


def load_cycles(data_dir: Path) -> list:
    cycles_dir = data_dir / "cycles"
    if not cycles_dir.exists():
        return []
    cycles = []
    for f in sorted(cycles_dir.glob("cycle_*.json")):
        cycles.append(json.loads(f.read_text()))
    return cycles


def compute_bucket_stats(data_dir: Path) -> dict:
    trades = load_trades(data_dir)
    risk_state = load_risk_state(data_dir)
    cycles = load_cycles(data_dir)

    empty = {
        "exists": data_dir.exists(),
        "cycles": len(cycles), "open_trades": 0, "closed_trades": 0,
        "total_trades": 0, "wins": 0, "losses": 0, "win_pct": 0,
        "avg_edge": 0, "realized_pnl": 0, "unrealized_pnl": 0,
        "total_pnl": 0, "total_fees": 0, "capital_deployed": 0,
        "roi_pct": 0, "positions": 0, "swarm_trades": 0, "arb_trades": 0,
    }
    if not trades:
        return empty

    # Separate opens from closes
    opens = {}  # market_id -> list of opening trades
    close_trades = []
    for t in trades:
        status = t.get("status", "")
        mid = t.get("market_id", "")
        if status in ("paper_filled", "filled", "simulated"):
            opens.setdefault(mid, []).append(t)
        elif status == "closed":
            close_trades.append(t)

    # Compute realized PnL from closed trades
    realized_pnl = 0.0
    wins = 0
    losses = 0
    for ct in close_trades:
        mid = ct.get("market_id", "")
        open_list = opens.get(mid, [])
        if not open_list:
            continue
        # Average entry price weighted by size
        total_size = sum(o.get("size_usd", 0) for o in open_list)
        if total_size == 0:
            continue
        avg_entry = sum(o.get("price", 0) * o.get("size_usd", 0) for o in open_list) / total_size
        close_price = ct.get("price", 0)
        side = open_list[0].get("side", "YES")
        if avg_entry > 0:
            shares = total_size / avg_entry
            if side == "YES":
                pnl = shares * (close_price - avg_entry)
            else:
                pnl = shares * (avg_entry - close_price)
        else:
            pnl = 0
        realized_pnl += pnl
        if pnl >= 0:
            wins += 1
        else:
            losses += 1

    # Also pull from risk_state expiry_stats/source_stats (RiskManager tracks resolved PnL)
    expiry_stats = risk_state.get("expiry_stats", {})
    source_stats = risk_state.get("source_stats", {})
    for stats_dict in [expiry_stats, source_stats]:
        for key, st in stats_dict.items():
            if isinstance(st, dict):
                realized_pnl += st.get("realized_pnl", 0)
                wins += st.get("wins", 0)
                losses += st.get("losses", 0)

    # Unrealized from open positions
    positions = risk_state.get("positions", [])
    unrealized_pnl = sum(p.get("unrealized_pnl", 0) for p in positions)

    # Fees
    total_fees = sum(t.get("fees", 0) for t in trades)

    # Capital deployed (opening trades only)
    all_opens = [t for t in trades if t.get("status") in ("paper_filled", "filled", "simulated")]
    capital_deployed = sum(t.get("size_usd", 0) for t in all_opens)

    # Edge from trade reasons
    edges = []
    for t in all_opens:
        reason = t.get("reason", "")
        if "Edge:" in reason:
            try:
                edge_str = reason.split("Edge:")[1].split("%")[0].strip()
                edges.append(float(edge_str))
            except (ValueError, IndexError):
                pass

    # Source breakdown
    swarm_trades = len([t for t in all_opens if t.get("source") == "swarm"])
    arb_trades = len([t for t in all_opens if t.get("source") == "arbitrage"])

    total_pnl = realized_pnl + unrealized_pnl
    total_decided = wins + losses
    roi_pct = (total_pnl / capital_deployed * 100) if capital_deployed > 0 else 0

    return {
        "exists": True,
        "cycles": len(cycles),
        "open_trades": len(all_opens),
        "closed_trades": len(close_trades),
        "total_trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_pct": (wins / total_decided * 100) if total_decided > 0 else 0,
        "avg_edge": sum(edges) / len(edges) if edges else 0,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "total_pnl": total_pnl,
        "total_fees": total_fees,
        "capital_deployed": capital_deployed,
        "roi_pct": roi_pct,
        "positions": len(positions),
        "swarm_trades": swarm_trades,
        "arb_trades": arb_trades,
    }


def print_comparison_table(results: dict):
    cprint("\n" + "=" * 110, "cyan")
    cprint("  PARALLEL TIMEFRAME EDGE TEST - RESULTS COMPARISON", "cyan", attrs=["bold"])
    cprint("=" * 110, "cyan")

    header = (
        f"{'Bucket':<14} {'Label':<12} {'Cyc':>4} {'Trades':>6} "
        f"{'W/L':>7} {'Win%':>6} {'Edge':>6} "
        f"{'Real$':>8} {'Unrl$':>8} {'Total$':>8} {'Fees':>6} "
        f"{'ROI%':>7} {'Src':>8}"
    )
    cprint(header, "white", attrs=["bold"])
    cprint("-" * 110, "white")

    best_roi = ("", -999)
    best_edge = ("", -999)

    for bucket_name, label in BUCKETS:
        stats = results.get(bucket_name)
        if not stats or not stats.get("exists"):
            cprint(f"{bucket_name:<14} {label:<12} {'-- no data --':>70}", "dark_grey")
            continue

        if stats["total_trades"] == 0:
            cprint(f"{bucket_name:<14} {label:<12} {'-- 0 trades --':>70}", "dark_grey")
            continue

        wl = f"{stats['wins']}/{stats['losses']}"
        src = f"{stats['swarm_trades']}s/{stats['arb_trades']}a"

        line = (
            f"{bucket_name:<14} {label:<12} {stats['cycles']:>4} {stats['open_trades']:>6} "
            f"{wl:>7} {stats['win_pct']:>5.0f}% {stats['avg_edge']:>5.1f}% "
            f"{stats['realized_pnl']:>+7.2f} {stats['unrealized_pnl']:>+7.2f} "
            f"{stats['total_pnl']:>+7.2f} {stats['total_fees']:>5.2f} "
            f"{stats['roi_pct']:>+6.1f}% {src:>8}"
        )

        tp = stats["total_pnl"]
        color = "green" if tp > 0 else "yellow" if tp == 0 else "red"
        cprint(line, color)

        if stats["roi_pct"] > best_roi[1] and stats["total_trades"] > 0:
            best_roi = (bucket_name, stats["roi_pct"])
        if stats["avg_edge"] > best_edge[1] and stats["total_trades"] > 0:
            best_edge = (bucket_name, stats["avg_edge"])

    cprint("-" * 110, "white")

    if best_edge[0]:
        cprint(f"\n  Best Avg Edge:  {best_edge[0]} ({best_edge[1]:+.1f}%)", "green", attrs=["bold"])
    if best_roi[0]:
        cprint(f"  Best ROI:       {best_roi[0]} ({best_roi[1]:+.1f}%)", "green", attrs=["bold"])
    cprint("", "white")


def aggregate(data_root: Path = None):
    if data_root is None:
        data_root = PROJECT_ROOT / "src" / "data"

    results = {}
    for bucket_name, label in BUCKETS:
        data_dir = data_root / f"polymarket_trader_{bucket_name}"
        results[bucket_name] = compute_bucket_stats(data_dir)

    print_comparison_table(results)
    return results


def main():
    parser = argparse.ArgumentParser(description="Aggregate parallel timeframe test results")
    parser.add_argument("--data-root", type=str, default=None,
                        help="Root data directory (default: src/data)")
    args = parser.parse_args()

    data_root = Path(args.data_root) if args.data_root else None
    aggregate(data_root)


if __name__ == "__main__":
    main()
