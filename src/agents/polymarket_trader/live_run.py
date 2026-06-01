"""
Live Trading Runner for Polymarket CLI Agents

REAL MONEY. Requires --confirm-live flag.
Runs pre-flight checks before starting the orchestrator.

Usage:
    python -m src.agents.polymarket_trader.live_run --confirm-live --cycles 5
    python -m src.agents.polymarket_trader.live_run --confirm-live --max-position 25 --max-exposure 100
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from termcolor import cprint

from .config import PolymarketCLIConfig, ExecutionMode
from .cli_wrapper import PolymarketCLI
from .preflight import run_preflight_checks
from .orchestrator import PolymarketCLIOrchestrator
from .weather_live_eligibility import WeatherLiveEligibilityGate


def main():
    parser = argparse.ArgumentParser(description="Polymarket LIVE Trading")
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Required flag to confirm live trading with real money",
    )
    parser.add_argument("--status", action="store_true", help="Print health/status and exit")
    parser.add_argument("--cycles", type=int, default=0, help="Cycles to run (0=infinite)")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between cycles")
    parser.add_argument("--markets", type=int, default=4, help="Markets to analyze per cycle")
    parser.add_argument("--market-vertical", choices=["crypto", "weather"], default="crypto",
                        help="Market vertical to scan and analyze")
    parser.add_argument("--weather", action="store_true",
                        help="Shortcut for --market-vertical weather")
    parser.add_argument("--max-position", type=float, default=None,
                        help="Max USD per position (default: 3 crypto, 10 weather)")
    parser.add_argument("--max-exposure", type=float, default=7.0,
                        help="Max total USD exposure (default: 7)")
    parser.add_argument("--max-expiry-hours", type=float, default=None,
                        help="Only trade markets expiring within N hours")
    parser.add_argument("--min-expiry-hours", type=float, default=None,
                        help="Only trade markets expiring AFTER N hours")
    parser.add_argument("--weather-alpha-report", type=str, default="",
                        help="Path to an accepted weather alpha JSON report required for live weather trades")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="Deprecated flag. Live mode no longer allows skipping pre-flight checks.")
    args = parser.parse_args()
    market_vertical = "weather" if args.weather else args.market_vertical
    base_max_position = args.max_position if args.max_position is not None else 3.0

    # =========================================================================
    # WARNING BANNER
    # =========================================================================
    cprint("=" * 84, "red")
    cprint(" LIVE TRADING - REAL MONEY ", "red", attrs=["bold"])
    cprint("=" * 84, "red")
    cprint("  This will execute REAL trades on Polymarket. ", "red")
    cprint("  Losses are PERMANENT. There is no undo. ", "red")
    cprint(" ", "red")
    cprint("  3-Model AI Swarm (GPT-5.5 + DeepSeek + Grok)  ", "red")
    cprint("  Kelly Criterion | Arb Detection | Fill Monitor ", "red")
    cprint("=" * 84, "red")

    # =========================================================================
    # CONFIG - tighter defaults than paper trading
    # =========================================================================
    config_kwargs = dict(
        execution_mode=ExecutionMode.LIVE,
        market_vertical=market_vertical,
        cycle_interval_seconds=args.interval,
        max_markets_to_analyze=args.markets,

        # Tighter risk limits for live
        max_position_usd=base_max_position,
        max_total_exposure_usd=args.max_exposure,
        daily_loss_limit_usd=6.0,
        max_positions=2,
        max_per_market_usd=base_max_position,
        min_position_usd=3.0,  # CLOB minimum is 5 shares; $3 ensures >=5 shares at any price
        min_expiry_minutes=60.0,  # Don't trade markets expiring within 1 hour

        # Conservative Kelly for live
        kelly_fraction=0.20,  # vs 0.25 for paper

        # Edge thresholds - keep proven settings
        min_edge_threshold=5.0,
        min_edge_confidence=0.50,

        # Diversification
        max_positions_per_symbol=8,

        # Arb settings
        min_arb_edge_percent=2.0,
        arb_fuzzy_match_threshold=0.85,

        # Whale tracking
        whale_scan_interval_cycles=3,

        # Live safety
        order_fill_timeout_seconds=30,
        max_slippage_pct=2.0,
        live_max_position_usd=base_max_position,
        live_min_balance_usd=2.0,
        live_balance_reserve_usd=5.0,
        unrealized_loss_limit_usd=6.0,
        live_order_stale_seconds=180,
    )

    if market_vertical == "weather":
        weather_max_position = args.max_position if args.max_position is not None else 10.0
        config_kwargs.update(
            search_symbols=["WEATHER"],
            min_liquidity_usd=500.0,
            min_volume_24h_usd=0.0,
            max_expiry_hours=args.max_expiry_hours if args.max_expiry_hours is not None else 16 * 24,
            min_expiry_minutes=0.0,
            min_arb_edge_percent=2.0,
            min_arb_token_price=0.001,
            max_position_usd=weather_max_position,
            max_per_market_usd=weather_max_position,
            live_max_position_usd=weather_max_position,
            max_positions=64,
            max_positions_per_symbol=64,
            max_positions_per_direction=64,
            max_daily_trades=200,
            weather_require_alpha_verification=True,
            weather_alpha_report_path=args.weather_alpha_report,
        )

    # Preserve config defaults unless the operator explicitly overrides them.
    if args.max_expiry_hours is not None and market_vertical != "weather":
        config_kwargs["max_expiry_hours"] = args.max_expiry_hours
    if args.min_expiry_hours is not None:
        config_kwargs["min_expiry_hours"] = args.min_expiry_hours

    config = PolymarketCLIConfig(**config_kwargs)

    # Auto-tune for short-expiry targets
    if config.max_expiry_hours is not None and args.interval == 60:
        if config.max_expiry_hours <= 0.25:
            config.cycle_interval_seconds = 30
            config.swarm_timeout_seconds = 25
            config.market_cache_seconds = 60
        elif config.max_expiry_hours <= 1.0:
            config.cycle_interval_seconds = 45
            config.swarm_timeout_seconds = 35
            config.market_cache_seconds = 120

    # Auto-calculate min time guard
    if config.max_expiry_hours is not None and config.min_expiry_minutes == 0:
        cycle_budget_seconds = config.cycle_interval_seconds + config.swarm_timeout_seconds + 30
        config.min_expiry_minutes = (cycle_budget_seconds / 60.0) * 2.0

    orchestrator = PolymarketCLIOrchestrator(config)
    if args.status:
        status = orchestrator.get_run_status()
        if market_vertical == "weather":
            status["weather_live_eligibility"] = WeatherLiveEligibilityGate(config).evaluate().to_dict()
        cprint("Status:", "cyan")
        cprint(json.dumps(status, indent=2, default=str), "white")
        return

    if not args.confirm_live:
        cprint("LIVE mode requires --confirm-live to proceed", "red")
        sys.exit(1)

    if args.skip_preflight:
        cprint(
            "LIVE mode no longer permits --skip-preflight. A passing pre-flight is required.",
            "red",
        )
        sys.exit(2)

    if market_vertical == "weather":
        live_eligibility = WeatherLiveEligibilityGate(config).evaluate()
        if not live_eligibility.eligible:
            cprint("WEATHER LIVE ELIGIBILITY FAILED - aborting before authenticated pre-flight", "red")
            cprint(json.dumps(live_eligibility.to_dict(), indent=2, default=str), "yellow")
            sys.exit(2)

    # =========================================================================
    # PRE-FLIGHT CHECKS
    # =========================================================================
    cli = PolymarketCLI(config)
    if not run_preflight_checks(config, cli):
        cprint("PRE-FLIGHT FAILED - aborting live trading", "red")
        sys.exit(1)

    # =========================================================================
    # PRINT SETTINGS
    # =========================================================================
    cprint(f"  Mode: LIVE TRADING", "red")
    cprint(f"  Market Vertical: {config.market_vertical}", "white")
    cprint(f"  Max Position: ${config.max_position_usd:.0f}", "white")
    cprint(f"  Max Exposure: ${config.max_total_exposure_usd:.0f}", "white")
    cprint(f"  Max Positions: {config.max_positions}", "white")
    cprint(f"  Kelly Fraction: {config.kelly_fraction}", "white")
    cprint(f"  Min Edge: {config.min_edge_threshold}%", "white")
    cprint(f"  Fill Timeout: {config.order_fill_timeout_seconds}s", "white")
    cprint(f"  Max Slippage: {config.max_slippage_pct}%", "white")
    cprint(f"  Markets/Cycle: {args.markets}", "white")
    cprint(f"  Cycle Interval: {config.cycle_interval_seconds}s", "white")
    if config.max_expiry_hours is not None or config.min_expiry_hours is not None:
        parts = []
        if config.min_expiry_hours is not None:
            parts.append(f">= {config.min_expiry_hours}h")
        if config.max_expiry_hours is not None:
            parts.append(f"<= {config.max_expiry_hours}h")
        cprint(f"  Expiry Filter: {' and '.join(parts)}", "yellow")
        if config.min_expiry_minutes > 0:
            cprint(f"  Min Time Guard: {config.min_expiry_minutes:.1f}min", "yellow")
    cprint(f"  Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n", "white")

    # =========================================================================
    # RUN
    # =========================================================================
    orchestrator.run(cycles=args.cycles)


if __name__ == "__main__":
    main()
