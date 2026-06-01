"""
🌙 TradeHive's Binance Connector
Real-time liquidation data from Binance Futures

WebSocket: wss://fstream.binance.com/ws/!forceOrder@arr
Streams all liquidation events automatically (no subscription needed)

Built with love by TradeHive 🚀
"""

import json
import asyncio
from datetime import datetime
from typing import List, Optional

from src.data.connectors.base_connector import (
    BaseConnector,
    DataType,
    LiquidationEvent,
)


class BinanceConnector(BaseConnector):
    """
    Binance Futures liquidation stream connector.

    Streams all liquidation events from Binance Futures.
    No subscription required - the stream automatically sends all liquidations.

    Usage:
        connector = BinanceConnector()
        connector.on_data(DataType.LIQUIDATION, my_callback)
        await connector.run_forever([], [DataType.LIQUIDATION])
    """

    # Binance liquidation stream - streams ALL pairs automatically
    WS_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"

    def __init__(self, min_usd_value: float = 1000.0):
        """
        Initialize Binance connector.

        Args:
            min_usd_value: Minimum USD value to emit (filter small liquidations)
        """
        super().__init__("binance")
        self.min_usd_value = min_usd_value
        self._message_count = 0

    @property
    def websocket_url(self) -> str:
        """WebSocket URL for Binance liquidation stream."""
        return self.WS_URL

    async def subscribe(self, symbols: List[str], data_types: List[DataType]) -> None:
        """
        Subscribe to data feeds.

        For Binance liquidation stream, no subscription is needed.
        The stream automatically sends all liquidation events.
        """
        # No subscription needed for !forceOrder@arr stream
        pass

    async def _handle_message(self, message: str) -> None:
        """
        Handle incoming WebSocket message.

        Binance liquidation message format:
        {
            "e": "forceOrder",
            "E": 1568014460893,
            "o": {
                "s": "BTCUSDT",     # Symbol
                "S": "SELL",        # Side (SELL = long liquidation, BUY = short liquidation)
                "o": "LIMIT",       # Order type
                "f": "IOC",         # Time in force
                "q": "0.014",       # Original quantity
                "p": "9910",        # Price
                "ap": "9910",       # Average price
                "X": "FILLED",      # Order status
                "l": "0.014",       # Last filled quantity
                "z": "0.014",       # Cumulative filled quantity
                "T": 1568014460893  # Trade time
            }
        }
        """
        try:
            data = json.loads(message)

            # Handle array of events
            if isinstance(data, list):
                for item in data:
                    await self._process_liquidation(item)
            else:
                await self._process_liquidation(data)

        except json.JSONDecodeError as e:
            self._log_error(f"Failed to parse message: {e}")
        except Exception as e:
            self._log_error(f"Error handling message: {e}")

    async def _process_liquidation(self, data: dict) -> None:
        """Process a single liquidation event."""
        if data.get("e") != "forceOrder":
            return

        order = data.get("o", {})
        if not order:
            return

        try:
            symbol = order.get("s", "UNKNOWN")
            side = order.get("S", "").upper()
            price = float(order.get("p", 0))
            quantity = float(order.get("q", 0))
            usd_value = price * quantity

            # Filter by minimum value
            if usd_value < self.min_usd_value:
                return

            # Determine liquidated side
            # SELL order = long position was liquidated
            # BUY order = short position was liquidated
            liquidated_side = "long" if side == "SELL" else "short"

            # Get timestamp
            trade_time = order.get("T", data.get("E", 0))
            if trade_time:
                timestamp = datetime.fromtimestamp(trade_time / 1000)
            else:
                timestamp = datetime.utcnow()

            # Create standardized event
            event = LiquidationEvent(
                exchange="binance",
                symbol=symbol,
                timestamp=timestamp,
                side=liquidated_side,
                size=usd_value,
                price=price,
                bankruptcy_price=float(order.get("ap", price)),
            )

            self._message_count += 1

            # Emit to callbacks
            await self._emit(DataType.LIQUIDATION, event)

        except (ValueError, TypeError) as e:
            self._log_error(f"Failed to parse liquidation data: {e}")

    def _log_error(self, message: str) -> None:
        """Log error message."""
        from termcolor import cprint
        cprint(f"[BINANCE ERROR] {message}", "red")

    @property
    def message_count(self) -> int:
        """Number of messages processed."""
        return self._message_count


# Quick test
if __name__ == "__main__":
    import asyncio
    from termcolor import cprint

    async def test_binance():
        cprint("\n🌙 Testing Binance Liquidation Stream...\n", "cyan")

        connector = BinanceConnector(min_usd_value=5000)

        def on_liquidation(event: LiquidationEvent):
            marker = "[LONG-LIQ]" if event.side == "long" else "[SHORT-LIQ]"
            cprint(
                f"{marker} {event.symbol:12} ${event.size:>12,.2f} @ {event.price:,.2f}",
                "yellow" if event.side == "long" else "green"
            )

        connector.on_data(DataType.LIQUIDATION, on_liquidation)

        cprint("[INFO] Connecting... (will run for 60 seconds)", "white")

        try:
            await connector.start([], [DataType.LIQUIDATION])
            await asyncio.sleep(60)
        except KeyboardInterrupt:
            cprint("\n[STOPPED]", "yellow")
        finally:
            await connector.disconnect()
            cprint(f"\n[DONE] Processed {connector.message_count} liquidations", "cyan")

    asyncio.run(test_binance())
