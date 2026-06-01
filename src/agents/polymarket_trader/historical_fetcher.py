"""
Historical Market Fetcher for Polymarket

Fetches resolved crypto prediction markets from Polymarket's Gamma API
and saves them in benchmark_markets.json format for backtesting with score_prompts().

Free API, no auth required. Produces hundreds of markets with known YES/NO outcomes.

Usage:
    python -m src.agents.polymarket_trader.historical_fetcher
    python -m src.agents.polymarket_trader.historical_fetcher --max-markets 50
    python -m src.agents.polymarket_trader.historical_fetcher --tags crypto-prices,ethereum --min-volume 50000
"""

import argparse
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests
from termcolor import cprint

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

DEFAULT_TAGS = ["crypto-prices", "crypto", "ethereum", "solana"]
DEFAULT_OUTPUT = str(Path(__file__).parent / "benchmark_markets_large.json")


# =========================================================================
# SYMBOL & MARKET TYPE DETECTION (mirrors market_scanner.py)
# =========================================================================

def detect_symbol(text: str) -> Optional[str]:
    """Detect crypto symbol from question text."""
    t = text.lower()
    if "bitcoin" in t or re.search(r'\bbtc\b', t):
        return "BTC"
    if "ethereum" in t or re.search(r'\beth\b', t) or "ether" in t:
        return "ETH"
    if "solana" in t or re.search(r'\bsol\b', t):
        return "SOL"
    if re.search(r'\bxrp\b', t):
        return "XRP"
    if "dogecoin" in t or re.search(r'\bdoge\b', t):
        return "DOGE"
    return None


def detect_market_type(question: str) -> str:
    """Determine if market is bullish/bearish/neutral."""
    q = question.lower()
    if "up or down" in q:
        return "binary_updown"
    bullish = ["above", "over", "exceed", "surpass", "reach", "hit", "higher"]
    bearish = ["below", "under", "fall", "drop", "lower", "crash", "dip"]
    if any(w in q for w in bullish):
        return "bullish"
    if any(w in q for w in bearish):
        return "bearish"
    return "neutral"


def is_binary_yes_no(outcomes_str: str) -> bool:
    """Check if market has exactly 2 outcomes: Yes/No."""
    try:
        outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
        if len(outcomes) != 2:
            return False
        labels = [o.lower().strip() for o in outcomes]
        return "yes" in labels and "no" in labels
    except (json.JSONDecodeError, TypeError):
        return False


def parse_resolution(outcomes_str: str, prices_str: str) -> Optional[bool]:
    """
    Parse outcomePrices to determine if YES won.
    outcomePrices: ["1", "0"] means first outcome (Yes) won.
    outcomePrices: ["0", "1"] means second outcome (No) won.
    Returns True if YES resolved, False if NO resolved, None if ambiguous.
    """
    try:
        outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
        prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str

        if len(outcomes) != 2 or len(prices) != 2:
            return None

        # Find which index is "Yes"
        yes_idx = None
        for i, o in enumerate(outcomes):
            if o.lower().strip() == "yes":
                yes_idx = i
                break

        if yes_idx is None:
            return None

        yes_price = float(prices[yes_idx])
        # Resolved: price is 1.0 (won) or 0.0 (lost)
        if yes_price >= 0.95:
            return True
        elif yes_price <= 0.05:
            return False
        else:
            return None  # Not clearly resolved

    except (json.JSONDecodeError, TypeError, ValueError, IndexError):
        return None


# =========================================================================
# GAMMA API — FETCH RESOLVED EVENTS
# =========================================================================

def fetch_resolved_events(tags: List[str], min_volume: float = 10000,
                          max_events: int = 500) -> List[dict]:
    """Paginate through Gamma API to collect resolved crypto events."""
    all_events = {}  # deduplicate by event id

    for tag in tags:
        offset = 0
        while True:
            try:
                resp = requests.get(f"{GAMMA_API}/events", params={
                    "closed": "true",
                    "tag_slug": tag,
                    "limit": 100,
                    "offset": offset,
                    "order": "volume",
                    "ascending": "false",
                }, timeout=15)
                resp.raise_for_status()
                batch = resp.json()
            except Exception as e:
                cprint(f"  Gamma API error (tag={tag}, offset={offset}): {e}", "red")
                break

            if not batch:
                break

            for event in batch:
                eid = event.get("id", "")
                if eid and eid not in all_events:
                    all_events[eid] = event

            cprint(f"  [{tag}] offset={offset}, batch={len(batch)}, total={len(all_events)}", "white")
            offset += len(batch)

            if len(batch) < 100:
                break  # Last page
            if len(all_events) >= max_events:
                break

            time.sleep(0.3)  # Rate limit

        if len(all_events) >= max_events:
            break

    events = list(all_events.values())

    # Filter by volume
    filtered = []
    for event in events:
        vol = float(event.get("volume", 0) or 0)
        if vol >= min_volume:
            filtered.append(event)

    cprint(f"Fetched {len(events)} events, {len(filtered)} pass volume >= ${min_volume:,.0f}", "cyan")
    return filtered


# =========================================================================
# CLOB API — FETCH ENTRY PRICE
# =========================================================================

def fetch_entry_price(token_id: str) -> Optional[float]:
    """
    Fetch pre-resolution YES token price via CLOB API.
    Uses interval=all with daily fidelity (works for resolved markets).
    Returns median of realistic prices (0.02-0.98), or None.
    """
    try:
        resp = requests.get(f"{CLOB_API}/prices-history", params={
            "market": token_id,
            "interval": "all",
            "fidelity": 1440,  # daily granularity
        }, timeout=10)
        resp.raise_for_status()
        history = resp.json().get("history", [])

        if not history:
            return None

        # Filter to realistic pre-resolution prices (not 0/1 at resolution)
        prices = [float(h["p"]) for h in history if 0.02 < float(h["p"]) < 0.98]
        if not prices:
            return None

        prices.sort()
        median = prices[len(prices) // 2]
        return round(median, 4)

    except Exception:
        return None


# =========================================================================
# PARSE MARKETS FROM EVENTS
# =========================================================================

def parse_markets(events: List[dict], fetch_prices: bool = True,
                  max_markets: int = 500) -> List[dict]:
    """Extract benchmark-format entries from Gamma API events."""
    benchmarks = []
    seen_conditions = set()
    price_fetch_count = 0

    for event in events:
        for mkt in event.get("markets", []):
            if len(benchmarks) >= max_markets:
                break

            condition_id = mkt.get("conditionId", "")
            if not condition_id or condition_id in seen_conditions:
                continue
            seen_conditions.add(condition_id)

            question = mkt.get("question", "")
            if not question:
                continue

            # Must be binary Yes/No
            outcomes = mkt.get("outcomes", "[]")
            if not is_binary_yes_no(outcomes):
                continue

            # Must be crypto-related
            symbol = detect_symbol(question)
            if not symbol:
                continue

            # Must be clearly resolved
            prices_str = mkt.get("outcomePrices", "[]")
            yes_resolved = parse_resolution(outcomes, prices_str)
            if yes_resolved is None:
                continue

            # Must be closed
            if not mkt.get("closed", False):
                continue

            # Get entry price (pre-resolution)
            market_price_yes = None
            closed_time = mkt.get("closedTime", mkt.get("endDate", ""))

            if fetch_prices:
                # Tier 1: CLOB price history
                try:
                    token_ids = json.loads(mkt.get("clobTokenIds", "[]"))
                    if token_ids:
                        time.sleep(0.2)  # Rate limit
                        market_price_yes = fetch_entry_price(token_ids[0])
                        price_fetch_count += 1
                        if price_fetch_count % 20 == 0:
                            cprint(f"  Fetched {price_fetch_count} price histories...", "white")
                except (json.JSONDecodeError, IndexError):
                    pass

            # Tier 2 fallback: lastTradePrice if between 0.05-0.95
            if market_price_yes is None:
                ltp = float(mkt.get("lastTradePrice", 0) or 0)
                if 0.05 < ltp < 0.95:
                    market_price_yes = round(ltp, 4)

            # Tier 3 fallback: use 0.50 (neutral — swarm decides from fundamentals)
            if market_price_yes is None:
                market_price_yes = 0.50

            # Calculate time remaining (approximate — use endDate if available)
            time_remaining_hours = 24.0  # default
            end_date = mkt.get("endDate", "")
            if end_date and closed_time:
                try:
                    end_dt = datetime.fromisoformat(end_date.replace("Z", ""))
                    close_dt = datetime.fromisoformat(closed_time.replace("Z", "").replace("+00:00", "").split("+")[0])
                    # Approximate: how long was the market open before resolution?
                    # Use 24h or actual duration, whichever is smaller
                    duration = (close_dt - end_dt).total_seconds() / 3600
                    if duration < 0:
                        # endDate is AFTER closedTime — use endDate as the resolution point
                        # and estimate 24h remaining at entry
                        time_remaining_hours = 24.0
                    else:
                        time_remaining_hours = max(1.0, min(168.0, abs(duration)))
                except (ValueError, TypeError):
                    pass

            volume = float(mkt.get("volume", mkt.get("volumeClob", 0)) or 0)

            benchmarks.append({
                "question": question,
                "symbol": symbol,
                "market_type": detect_market_type(question),
                "market_price_yes": market_price_yes,
                "time_remaining_hours": round(time_remaining_hours, 2),
                "yes_resolved": yes_resolved,
                "volume": round(volume, 2),
                "condition_id": condition_id,
            })

        if len(benchmarks) >= max_markets:
            break

    return benchmarks


# =========================================================================
# SAVE
# =========================================================================

def save_benchmarks(benchmarks: List[dict], output_path: str):
    """Write benchmarks to JSON file."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(benchmarks, f, indent=2)
    cprint(f"Saved {len(benchmarks)} benchmark markets to {output_path}", "green")


# =========================================================================
# CLI
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Fetch resolved crypto markets from Polymarket for backtesting"
    )
    parser.add_argument("--tags", type=str, default=",".join(DEFAULT_TAGS),
                        help=f"Comma-separated tag slugs (default: {','.join(DEFAULT_TAGS)})")
    parser.add_argument("--min-volume", type=float, default=10000,
                        help="Minimum market volume in USD (default: 10000)")
    parser.add_argument("--max-markets", type=int, default=200,
                        help="Maximum benchmark markets to save (default: 200)")
    parser.add_argument("--max-events", type=int, default=500,
                        help="Maximum events to fetch from API (default: 500)")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT,
                        help=f"Output file path (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--no-prices", action="store_true",
                        help="Skip CLOB price history fetch (faster, uses lastTradePrice fallback)")
    args = parser.parse_args()

    tags = [t.strip() for t in args.tags.split(",")]

    cprint("""
    ╔══════════════════════════════════════════════════════════╗
    ║       POLYMARKET HISTORICAL FETCHER                     ║
    ║       Resolved Crypto Markets for Backtesting           ║
    ╚══════════════════════════════════════════════════════════╝
    """, "cyan")
    cprint(f"  Tags: {tags}", "white")
    cprint(f"  Min Volume: ${args.min_volume:,.0f}", "white")
    cprint(f"  Max Markets: {args.max_markets}", "white")
    cprint(f"  Fetch Prices: {not args.no_prices}", "white")
    cprint(f"  Output: {args.output}\n", "white")

    # Step 1: Fetch resolved events
    cprint("[1/3] Fetching resolved events from Gamma API...", "cyan")
    events = fetch_resolved_events(tags, min_volume=args.min_volume, max_events=args.max_events)

    if not events:
        cprint("No events found. Check your tags and volume filter.", "red")
        return

    # Step 2: Parse markets and fetch entry prices
    cprint(f"\n[2/3] Parsing markets and fetching entry prices...", "cyan")
    benchmarks = parse_markets(events, fetch_prices=not args.no_prices, max_markets=args.max_markets)

    if not benchmarks:
        cprint("No valid benchmark markets found.", "red")
        return

    # Step 3: Save
    cprint(f"\n[3/3] Saving benchmarks...", "cyan")
    save_benchmarks(benchmarks, args.output)

    # Summary
    from collections import Counter
    symbols = Counter(b["symbol"] for b in benchmarks)
    types = Counter(b["market_type"] for b in benchmarks)
    yes_count = sum(1 for b in benchmarks if b["yes_resolved"])
    no_count = len(benchmarks) - yes_count

    cprint(f"\nSummary:", "cyan")
    cprint(f"  Total: {len(benchmarks)} markets", "white")
    cprint(f"  Resolved YES: {yes_count} ({yes_count/len(benchmarks):.0%})", "white")
    cprint(f"  Resolved NO:  {no_count} ({no_count/len(benchmarks):.0%})", "white")
    cprint(f"  By symbol: {dict(symbols)}", "white")
    cprint(f"  By type:   {dict(types)}", "white")
    cprint(f"\nReady for backtesting:", "green")
    cprint(f"  scorer.score_prompts(\"{args.output}\")", "green")


if __name__ == "__main__":
    main()
