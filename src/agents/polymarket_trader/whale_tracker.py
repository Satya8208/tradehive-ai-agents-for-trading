"""
Whale Tracker for Polymarket CLI Agents

Monitors top Polymarket traders via CLI leaderboard.
Tracks position changes and flags whale activity on crypto markets.
"""

import json
import time
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path
from termcolor import cprint

from .config import PolymarketCLIConfig, get_config
from .cli_wrapper import PolymarketCLI
from .models import CLIMarket


class WhaleTracker:
    """
    Tracks top Polymarket traders via CLI leaderboard.
    Compares snapshots to detect new whale positions on crypto markets.
    """

    def __init__(self, config: Optional[PolymarketCLIConfig] = None,
                 cli: Optional[PolymarketCLI] = None):
        self.config = config or get_config()
        self.cli = cli or PolymarketCLI(self.config)
        self.tracked_whales: Dict[str, Dict] = {}
        self._last_scan = 0.0
        self._load_state()

    def scan_whales(self) -> List[Dict]:
        """
        Fetch leaderboard, compare to previous snapshot, return changes.
        """
        cprint("Scanning whale activity...", "cyan")

        leaderboard = self.cli.get_leaderboard(
            period="week",
            order_by="pnl",
            limit=self.config.whale_leaderboard_top_n
        )

        if not leaderboard:
            cprint("Could not fetch leaderboard", "yellow")
            return []

        # Handle response format
        if isinstance(leaderboard, dict):
            leaderboard = leaderboard.get("data", [leaderboard])

        changes = []
        new_snapshot = {}

        for whale in leaderboard:
            if not isinstance(whale, dict):
                continue

            address = whale.get("proxy_wallet", whale.get("address", ""))
            if not address:
                continue

            pnl = float(whale.get("pnl", 0) or 0)
            volume = float(whale.get("volume", 0) or 0)
            rank = whale.get("rank", 0)
            name = whale.get("user_name", address[:10])

            new_snapshot[address] = {
                "name": name,
                "pnl": pnl,
                "volume": volume,
                "rank": rank,
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Compare to previous
            if address in self.tracked_whales:
                prev = self.tracked_whales[address]
                pnl_change = pnl - prev.get("pnl", 0)
                vol_change = volume - prev.get("volume", 0)

                if abs(pnl_change) > 1000 or abs(vol_change) > 5000:
                    changes.append({
                        "address": address,
                        "name": name,
                        "rank": rank,
                        "pnl_change": pnl_change,
                        "volume_change": vol_change,
                        "current_pnl": pnl,
                    })
            else:
                # New whale on leaderboard
                changes.append({
                    "address": address,
                    "name": name,
                    "rank": rank,
                    "pnl_change": 0,
                    "volume_change": 0,
                    "current_pnl": pnl,
                    "is_new": True,
                })

        # Update state
        self.tracked_whales = new_snapshot
        self._save_state()
        self._last_scan = time.time()

        if changes:
            cprint(f"Detected {len(changes)} whale changes", "magenta")

        return changes

    def get_whale_signals(self, crypto_markets: List[CLIMarket]) -> List[Dict]:
        """
        Cross-reference whale changes with current crypto markets.
        Returns signals where whales are active on markets we're watching.
        """
        # For now, return the raw whale changes as informational signals
        # In the future, we can fetch individual whale positions via CLI
        return self.scan_whales()

    def _load_state(self):
        """Load previous whale snapshot from disk."""
        state_file = self.config.whales_dir / "whale_state.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    self.tracked_whales = json.load(f)
            except Exception:
                self.tracked_whales = {}

    def _save_state(self):
        """Persist current whale snapshot."""
        self.config.ensure_dirs()
        state_file = self.config.whales_dir / "whale_state.json"
        try:
            with open(state_file, "w") as f:
                json.dump(self.tracked_whales, f, indent=2)
        except Exception as e:
            cprint(f"Failed to save whale state: {e}", "red")

    def get_summary(self) -> str:
        """Return human-readable whale summary."""
        if not self.tracked_whales:
            return "No whales tracked yet"

        lines = [f"Tracking {len(self.tracked_whales)} whales:"]
        sorted_whales = sorted(
            self.tracked_whales.items(),
            key=lambda x: x[1].get("pnl", 0),
            reverse=True
        )
        for addr, info in sorted_whales[:5]:
            name = info.get("name", addr[:10])
            pnl = info.get("pnl", 0)
            lines.append(f"  #{info.get('rank', '?')} {name}: ${pnl:,.0f} PnL")

        return "\n".join(lines)


if __name__ == "__main__":
    tracker = WhaleTracker()
    changes = tracker.scan_whales()

    print(f"\n{tracker.get_summary()}")

    if changes:
        print(f"\nRecent changes:")
        for c in changes[:5]:
            print(f"  {c['name']}: PnL change ${c['pnl_change']:+,.0f}")
