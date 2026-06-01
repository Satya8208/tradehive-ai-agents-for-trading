"""
Paper Trading Runner for Polymarket CLI Agents

Runs the orchestrator in PAPER mode with real-time monitoring.
Analyzes more markets per cycle to find real edges.

Usage:
    python -m src.agents.polymarket_trader.paper_run
    python -m src.agents.polymarket_trader.paper_run --cycles 10 --interval 120
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from termcolor import cprint

from .config import PolymarketCLIConfig, ExecutionMode
from .orchestrator import PolymarketCLIOrchestrator


def main():
    parser = argparse.ArgumentParser(description="Polymarket Paper Trading")
    parser.add_argument("--cycles", type=int, default=0, help="Cycles to run (0=infinite)")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between cycles")
    parser.add_argument("--status", action="store_true", help="Print health/status and exit")
    parser.add_argument("--markets", type=int, default=5, help="Markets to analyze per cycle")
    parser.add_argument("--balance", type=float, default=1000.0, help="Starting paper balance")
    parser.add_argument("--market-vertical", choices=["crypto", "weather"], default="crypto",
                        help="Market vertical to scan and analyze")
    parser.add_argument("--weather", action="store_true",
                        help="Shortcut for --market-vertical weather")
    parser.add_argument("--max-expiry-hours", type=float, default=None,
                        help="Only trade markets expiring within N hours (e.g., 0.25 for 15min)")
    parser.add_argument("--min-expiry-hours", type=float, default=None,
                        help="Only trade markets expiring AFTER N hours (e.g., 24 for long-term)")
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="Restrict the scan universe to these symbols (e.g., ETH BTC)")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Override data directory for isolated parallel runs")
    parser.add_argument("--weather-high-res-ingest", action="store_true",
                        help="In weather mode, ingest HRRR/NBM point artifacts before analysis")
    parser.add_argument("--weather-high-res-cache-dir", type=str, default="",
                        help="Cache directory for weather HRRR/NBM point artifacts")
    parser.add_argument("--weather-require-high-res", action="store_true",
                        help="In weather mode, block paper candidates unless high-resolution sources are live-safe")
    parser.add_argument("--weather-evidence-off", action="store_true",
                        help="Disable append-only weather evidence capture for this run")
    parser.add_argument("--weather-fetch-orderbook", action="store_true",
                        help="In weather mode, fetch CLOB order books for executable tape snapshots")
    parser.add_argument("--weather-fetch-last-trade", action="store_true",
                        help="In weather mode, fetch last-trade data for tape snapshots")
    args = parser.parse_args()
    market_vertical = "weather" if args.weather else args.market_vertical

    cprint("=" * 84, "cyan")
    cprint(" Polymarket CLI Paper Trading ", "cyan", attrs=["bold"])
    cprint("=" * 84, "cyan")
    cprint("  3-Model AI Swarm (GPT-5.5 + DeepSeek + Grok)   ", "cyan")
    cprint("  Kelly Criterion | Arb Detection | Price Context       ", "cyan")
    cprint("=" * 84, "cyan")

    config_kwargs = dict(
        execution_mode=ExecutionMode.PAPER,
        market_vertical=market_vertical,
        cycle_interval_seconds=args.interval,
        max_markets_to_analyze=args.markets,
        paper_starting_balance=args.balance,

        # Paper trading settings - moderate risk
        max_position_usd=150.0,
        max_total_exposure_usd=600.0,
        daily_loss_limit_usd=100.0,
        max_positions=8,
        max_per_market_usd=200.0,

        # Edge thresholds - use config defaults (3.0% absolute edge after fix)
        kelly_fraction=0.25,  # Quarter Kelly

        # Diversification
        max_positions_per_symbol=8,

        # Arb settings - tighter matching for quality
        arb_fuzzy_match_threshold=0.85,

        # Whale tracking every 3 cycles
        whale_scan_interval_cycles=3,
    )

    if market_vertical == "weather":
        config_kwargs.update(
            search_symbols=["WEATHER"],
            min_liquidity_usd=500.0,
            min_volume_24h_usd=0.0,
            max_expiry_hours=args.max_expiry_hours if args.max_expiry_hours is not None else 16 * 24,
            min_expiry_minutes=0.0,
            max_positions_per_symbol=12,
            min_edge_threshold=5.0,
            weather_auto_ingest_high_resolution=args.weather_high_res_ingest,
            weather_require_high_resolution_confirmation=args.weather_require_high_res,
            weather_evidence_enabled=not args.weather_evidence_off,
            weather_market_tape_fetch_orderbook=args.weather_fetch_orderbook,
            weather_market_tape_fetch_last_trade=args.weather_fetch_last_trade,
        )
        if args.weather_high_res_cache_dir:
            config_kwargs["weather_high_resolution_cache_dir"] = args.weather_high_res_cache_dir
    elif args.symbols:
        config_kwargs["search_symbols"] = [
            str(symbol).strip().upper()
            for symbol in args.symbols
            if str(symbol).strip()
        ]

    # Preserve config defaults unless the operator explicitly overrides them.
    if args.max_expiry_hours is not None and market_vertical != "weather":
        config_kwargs["max_expiry_hours"] = args.max_expiry_hours
    if args.min_expiry_hours is not None:
        config_kwargs["min_expiry_hours"] = args.min_expiry_hours

    config = PolymarketCLIConfig(**config_kwargs)

    if args.data_dir:
        config._data_dir_override = Path(args.data_dir)

    # Auto-tune cycle interval for short-expiry targets
    if config.max_expiry_hours is not None and args.interval == 60:
        if config.max_expiry_hours <= 0.25:  # 15-min or less
            config.cycle_interval_seconds = 30
            config.swarm_timeout_seconds = 25
            config.market_cache_seconds = 60
        elif config.max_expiry_hours <= 1.0:  # 1 hour or less
            config.cycle_interval_seconds = 45
            config.swarm_timeout_seconds = 35
            config.market_cache_seconds = 120

    # Auto-calculate min time guard: 2x cycle budget
    if config.max_expiry_hours is not None:
        cycle_budget_seconds = config.cycle_interval_seconds + config.swarm_timeout_seconds + 30
        config.min_expiry_minutes = (cycle_budget_seconds / 60.0) * 2.0

    cprint(f"  Mode: PAPER TRADING", "yellow")
    cprint(f"  Market Vertical: {config.market_vertical}", "white")
    cprint(f"  Starting Balance: ${args.balance:,.2f}", "white")
    cprint(f"  Max Position: ${config.max_position_usd:.0f}", "white")
    cprint(f"  Max Exposure: ${config.max_total_exposure_usd:.0f}", "white")
    cprint(f"  Markets/Cycle: {args.markets}", "white")
    cprint(f"  Cycle Interval: {args.interval}s", "white")
    cprint(f"  Kelly Fraction: {config.kelly_fraction}", "white")
    cprint(f"  Min Edge: {config.min_edge_threshold}%", "white")
    cprint(f"  Symbols: {', '.join(config.search_symbols)}", "white")
    swarm_desc = " | ".join(f"{provider}/{model}" for provider, model in config.swarm_models)
    cprint(f"  Swarm: {swarm_desc}", "white")
    cprint(f"  Max/Symbol: {config.max_positions_per_symbol}", "white")
    if market_vertical == "weather":
        cprint(
            f"  High-Res Ingest: {'on' if config.weather_auto_ingest_high_resolution else 'off'}",
            "yellow" if config.weather_auto_ingest_high_resolution else "white",
        )
        if config.weather_high_resolution_cache_dir:
            cprint(f"  High-Res Cache: {config.weather_high_resolution_cache_dir}", "white")
        if config.weather_require_high_resolution_confirmation:
            cprint("  High-Res Gate: required", "yellow")
        cprint(
            f"  Evidence Capture: {'off' if not config.weather_evidence_enabled else 'on'}",
            "yellow" if config.weather_evidence_enabled else "white",
        )
        if config.weather_market_tape_fetch_orderbook:
            cprint("  Market Tape: orderbook fetch on", "yellow")
    if config.max_expiry_hours is not None or config.min_expiry_hours is not None:
        parts = []
        if config.min_expiry_hours is not None:
            parts.append(f">= {config.min_expiry_hours}h")
        if config.max_expiry_hours is not None:
            parts.append(f"<= {config.max_expiry_hours}h")
        cprint(f"  Expiry Filter: {' and '.join(parts)}", "yellow")
        if config.min_expiry_minutes > 0:
            cprint(f"  Min Time Guard: {config.min_expiry_minutes:.1f}min (2x cycle budget)", "yellow")
        if config.max_expiry_hours is not None:
            cprint(f"  Auto-tuned: {config.cycle_interval_seconds}s cycles, "
                   f"{config.swarm_timeout_seconds}s swarm timeout", "yellow")
    cprint(f"  Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n", "white")

    orchestrator = PolymarketCLIOrchestrator(config)
    if args.status:
        status = orchestrator.get_run_status()
        cprint("Status:", "cyan")
        cprint(json.dumps(status, indent=2, default=str), "white")
        return

    orchestrator.run(cycles=args.cycles)


if __name__ == "__main__":
    main()
