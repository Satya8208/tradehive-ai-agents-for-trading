"""
🌙 TradeHive's Bybit Connector
Real-time liquidation data from Bybit Futures

WebSocket: wss://stream.bybit.com/v5/public/linear
Requires subscription per symbol

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


class BybitConnector(BaseConnector):
    """
    Bybit Futures liquidation stream connector.

    Requires explicit subscription to each symbol's liquidation channel.
    Uses the allLiquidation channel for bulk subscriptions.

    Usage:
        connector = BybitConnector()
        connector.on_data(DataType.LIQUIDATION, my_callback)
        await connector.run_forever(
            ["BTCUSDT", "ETHUSDT"],
            [DataType.LIQUIDATION]
        )
    """

    # Bybit linear perpetual WebSocket
    WS_URL = "wss://stream.bybit.com/v5/public/linear"

    # Default symbols to track
    DEFAULT_SYMBOLS = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT",
        "XRPUSDT", "DOGEUSDT", "ADAUSDT",
        "AVAXUSDT", "LINKUSDT", "MATICUSDT"
    ]

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        use_linear: bool = True,
        min_usd_value: float = 1000.0
    ):
        """
        Initialize Bybit connector.

        Args:
            symbols: List of symbols to track (default: major pairs)
            use_linear: Use linear perpetuals (True) or inverse (False)
            min_usd_value: Minimum USD value to emit
        """
        super().__init__("bybit")
        self.symbols = symbols or self.DEFAULT_SYMBOLS
        self.use_linear = use_linear
        self.min_usd_value = min_usd_value
        self._message_count = 0
        self._ping_task: Optional[asyncio.Task] = None

    @property
    def websocket_url(self) -> str:
        """WebSocket URL for Bybit."""
        if self.use_linear:
            return "wss://stream.bybit.com/v5/public/linear"
        return "wss://stream.bybit.com/v5/public/inverse"

    async def subscribe(self, symbols: List[str], data_types: List[DataType]) -> None:
        """
        Subscribe to liquidation channels for given symbols.

        Args:
            symbols: List of symbols (uses self.symbols if empty)
            data_types: Data types to subscribe (only LIQUIDATION supported)
        """
        if not self.ws:
            return

        # Use provided symbols or default
        target_symbols = symbols if symbols else self.symbols

        # Subscribe to liquidation channel for each symbol
        subscribe_args = [f"liquidation.{sym}" for sym in target_symbols]

        subscribe_msg = {
            "op": "subscribe",
            "args": subscribe_args
        }

        await self.ws.send(json.dumps(subscribe_msg))

        from termcolor import cprint
        cprint(f"[BYBIT] Subscribed to {len(target_symbols)} symbols", "green")

        # Start ping task to keep connection alive
        if self._ping_task is None or self._ping_task.done():
            self._ping_task = asyncio.create_task(self._ping_loop())

    async def _ping_loop(self) -> None:
        """Send periodic pings to keep connection alive."""
        while self.running and self.ws:
            try:
                await asyncio.sleep(20)
                if self.ws and self.connected:
                    await self.ws.send(json.dumps({"op": "ping"}))
            except Exception:
                break

    async def disconnect(self) -> None:
        """Disconnect and cleanup."""
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass

        await super().disconnect()

    async def _handle_message(self, message: str) -> None:
        """
        Handle incoming WebSocket message.

        Bybit liquidation message format:
        {
            "topic": "liquidation.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304486868,
            "data": {
                "updatedTime": 1672304486868,
                "symbol": "BTCUSDT",
                "side": "Buy",        # Direction of liquidation order
                "size": "0.001",      # Position size
                "price": "16800.00"   # Bankruptcy price
            }
        }
        """
        try:
            data = json.loads(message)

            # Handle ping/pong
            if data.get("op") == "pong" or data.get("ret_msg") == "pong":
                return

            # Handle subscription confirmation
            if data.get("op") == "subscribe":
                if data.get("success"):
                    from termcolor import cprint
                    cprint("[BYBIT] Subscription confirmed", "green")
                return

            # Handle liquidation data
            topic = data.get("topic", "")
            if topic.startswith("liquidation."):
                await self._process_liquidation(data)

        except json.JSONDecodeError as e:
            self._log_error(f"Failed to parse message: {e}")
        except Exception as e:
            self._log_error(f"Error handling message: {e}")

    async def _process_liquidation(self, data: dict) -> None:
        """Process a single liquidation event."""
        liq_data = data.get("data", {})
        if not liq_data:
            return

        try:
            symbol = liq_data.get("symbol", "UNKNOWN")
            side = liq_data.get("side", "").upper()
            price = float(liq_data.get("price", 0))
            size = float(liq_data.get("size", 0))
            usd_value = price * size

            # Filter by minimum value
            if usd_value < self.min_usd_value:
                return

            # Determine liquidated side
            # BUY order = short position was liquidated (forced to buy to cover)
            # SELL order = long position was liquidated (forced to sell)
            liquidated_side = "short" if side == "BUY" else "long"

            # Get timestamp
            updated_time = liq_data.get("updatedTime") or data.get("ts", 0)
            if updated_time:
                timestamp = datetime.fromtimestamp(updated_time / 1000)
            else:
                timestamp = datetime.utcnow()

            # Create standardized event
            event = LiquidationEvent(
                exchange="bybit",
                symbol=symbol,
                timestamp=timestamp,
                side=liquidated_side,
                size=usd_value,
                price=price,
                bankruptcy_price=price,
            )

            self._message_count += 1

            # Emit to callbacks
            await self._emit(DataType.LIQUIDATION, event)

        except (ValueError, TypeError) as e:
            self._log_error(f"Failed to parse liquidation data: {e}")

    def _log_error(self, message: str) -> None:
        """Log error message."""
        from termcolor import cprint
        cprint(f"[BYBIT ERROR] {message}", "red")

    @property
    def message_count(self) -> int:
        """Number of messages processed."""
        return self._message_count


# Quick test
if __name__ == "__main__":
    import asyncio
    from termcolor import cprint

    async def test_bybit():
        cprint("\n🌙 Testing Bybit Liquidation Stream...\n", "cyan")

        connector = BybitConnector(min_usd_value=1000)

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

    asyncio.run(test_bybit())
