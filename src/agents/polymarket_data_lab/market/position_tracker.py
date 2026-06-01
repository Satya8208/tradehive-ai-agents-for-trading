"""
Position Tracker

Tracks open positions and manages exposure limits.
Built with love by TradeHive
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import asdict
from termcolor import cprint

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig
from src.agents.crypto_polymarket.models import Position, TradeExecution


class PositionTracker:
    """
    Tracks open positions and enforces risk limits.

    Risk limits:
    - Max position per market
    - Max total exposure
    - Position count limits

    Persists positions to disk for recovery.
    """

    def __init__(self, config: CryptoPolymarketConfig):
        self.config = config
        self.positions: Dict[str, Position] = {}
        self._load_positions()

    @property
    def positions_file(self) -> Path:
        """Path to positions storage file."""
        return self.config.data_dir / "positions" / "open_positions.json"

    def _load_positions(self) -> None:
        """Load positions from disk."""
        if self.positions_file.exists():
            try:
                with open(self.positions_file, "r") as f:
                    data = json.load(f)

                for pos_data in data:
                    pos = Position(
                        market_id=pos_data["market_id"],
                        token_id=pos_data["token_id"],
                        side=pos_data["side"],
                        size=pos_data["size"],
                        entry_price=pos_data["entry_price"],
                        current_price=pos_data.get(
                            "current_price", pos_data["entry_price"]
                        ),
                        unrealized_pnl=pos_data.get("unrealized_pnl", 0.0),
                        entry_time=datetime.fromisoformat(pos_data["entry_time"]),
                        last_updated=datetime.fromisoformat(
                            pos_data.get("last_updated", pos_data["entry_time"])
                        ),
                    )
                    self.positions[pos.market_id] = pos

                cprint(f"📂 Loaded {len(self.positions)} open positions", "cyan")

            except Exception as e:
                cprint(f"Error loading positions: {e}", "red")
                self.positions = {}

    def _save_positions(self) -> None:
        """Save positions to disk."""
        try:
            self.positions_file.parent.mkdir(parents=True, exist_ok=True)

            data = []
            for pos in self.positions.values():
                pos_dict = {
                    "market_id": pos.market_id,
                    "token_id": pos.token_id,
                    "side": pos.side,
                    "size": pos.size,
                    "entry_price": pos.entry_price,
                    "current_price": pos.current_price,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "entry_time": pos.entry_time.isoformat(),
                    "last_updated": pos.last_updated.isoformat(),
                }
                data.append(pos_dict)

            with open(self.positions_file, "w") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            cprint(f"Error saving positions: {e}", "red")

    def add_position(self, execution: TradeExecution) -> Position:
        """
        Add or update a position from a trade execution.

        If position exists in market, it will be averaged.
        """
        market_id = execution.market_id

        if market_id in self.positions:
            # Update existing position
            pos = self.positions[market_id]
            old_value = pos.size * pos.entry_price
            new_value = execution.size * execution.price
            total_size = pos.size + execution.size

            # Weighted average entry price
            pos.entry_price = (old_value + new_value) / total_size
            pos.size = total_size
            pos.last_updated = datetime.utcnow()

        else:
            # Create new position
            pos = Position(
                market_id=market_id,
                token_id=execution.token_id,
                side=execution.side,
                size=execution.size,
                entry_price=execution.price,
                current_price=execution.price,
                unrealized_pnl=0.0,
                entry_time=execution.timestamp,
                last_updated=datetime.utcnow(),
            )
            self.positions[market_id] = pos

        self._save_positions()
        return pos

    def remove_position(self, market_id: str) -> Optional[Position]:
        """Remove a closed position."""
        if market_id in self.positions:
            pos = self.positions.pop(market_id)
            self._save_positions()
            return pos
        return None

    def update_position_price(
        self, market_id: str, current_price: float
    ) -> Optional[Position]:
        """Update a position's current price and PnL."""
        if market_id not in self.positions:
            return None

        pos = self.positions[market_id]
        pos.current_price = current_price
        pos.unrealized_pnl = (current_price - pos.entry_price) * pos.size
        pos.last_updated = datetime.utcnow()

        self._save_positions()
        return pos

    def get_position(self, market_id: str) -> Optional[Position]:
        """Get a specific position."""
        return self.positions.get(market_id)

    def get_all_positions(self) -> List[Position]:
        """Get all open positions."""
        return list(self.positions.values())

    def get_total_exposure(self) -> float:
        """Calculate total USD exposure across all positions."""
        return sum(pos.size * pos.entry_price for pos in self.positions.values())

    def get_position_exposure(self, market_id: str) -> float:
        """Get USD exposure for a specific market."""
        pos = self.positions.get(market_id)
        if pos:
            return pos.size * pos.entry_price
        return 0.0

    def get_total_unrealized_pnl(self) -> float:
        """Calculate total unrealized PnL."""
        return sum(pos.unrealized_pnl for pos in self.positions.values())

    def can_open_position(self, market_id: str, size_usd: float) -> tuple[bool, str]:
        """
        Check if a new position can be opened within risk limits.

        Returns:
            Tuple of (allowed, reason)
        """
        # Check total exposure limit
        current_exposure = self.get_total_exposure()
        if current_exposure + size_usd > self.config.max_total_exposure_usd:
            return (
                False,
                f"Would exceed max total exposure (${self.config.max_total_exposure_usd:,.0f})",
            )

        # Check per-market limit
        current_market_exposure = self.get_position_exposure(market_id)
        if current_market_exposure + size_usd > self.config.max_position_per_market_usd:
            return (
                False,
                f"Would exceed max position per market (${self.config.max_position_per_market_usd:,.0f})",
            )

        # Check minimum trade size
        if size_usd < self.config.min_trade_size_usd:
            return (
                False,
                f"Below minimum trade size (${self.config.min_trade_size_usd:,.0f})",
            )

        # Check maximum trade size
        if size_usd > self.config.max_trade_size_usd:
            return (
                False,
                f"Exceeds maximum trade size (${self.config.max_trade_size_usd:,.0f})",
            )

        return (True, "OK")

    def get_suggested_position_size(self, market_id: str) -> float:
        """
        Calculate suggested position size for a market.

        Takes into account:
        - Current exposure
        - Per-market limits
        - Total exposure limits
        """
        current_total = self.get_total_exposure()
        current_market = self.get_position_exposure(market_id)

        # Room under total limit
        total_room = self.config.max_total_exposure_usd - current_total

        # Room under per-market limit
        market_room = self.config.max_position_per_market_usd - current_market

        # Take minimum of available room
        available = min(total_room, market_room)

        # Cap at max trade size
        suggested = min(available, self.config.max_trade_size_usd)

        # Floor at min trade size (or 0 if not enough room)
        if suggested < self.config.min_trade_size_usd:
            return 0.0

        return suggested

    def get_positions_summary(self) -> str:
        """Generate a human-readable summary of all positions."""
        if not self.positions:
            return "📭 No open positions"

        summary = f"[CHART] Open Positions ({len(self.positions)}):\n"
        summary += f"   Total Exposure: ${self.get_total_exposure():,.2f}\n"
        summary += f"   Unrealized PnL: ${self.get_total_unrealized_pnl():+,.2f}\n\n"

        for market_id, pos in self.positions.items():
            pnl_emoji = "[BULL]" if pos.unrealized_pnl >= 0 else "[BEAR]"
            summary += f"   {pnl_emoji} {market_id[:16]}...\n"
            summary += f"      Side: {pos.side} | Size: {pos.size:.2f}\n"
            summary += f"      Entry: ${pos.entry_price:.3f} | Current: ${pos.current_price:.3f}\n"
            summary += f"      PnL: ${pos.unrealized_pnl:+.2f}\n"

        return summary

    def get_risk_status(self) -> Dict[str, any]:
        """Get current risk status and utilization."""
        total_exposure = self.get_total_exposure()

        return {
            "total_exposure": total_exposure,
            "exposure_utilization": total_exposure / self.config.max_total_exposure_usd,
            "position_count": len(self.positions),
            "unrealized_pnl": self.get_total_unrealized_pnl(),
            "max_exposure": self.config.max_total_exposure_usd,
            "available_capital": self.config.max_total_exposure_usd - total_exposure,
        }
