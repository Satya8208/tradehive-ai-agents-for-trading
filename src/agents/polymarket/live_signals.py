"""
TradeHive's Live Signal Runner
Connects real-time exchange data to signal agents and displays trading decisions

Run: python -u src/agents/polymarket/live_signals.py
"""

import asyncio
import json
import sys
from datetime import datetime
import websockets

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)

# Add project root to path
sys.path.insert(0, ".")

from src.agents.polymarket.signal_agents import SignalAggregator


class LiveSignalRunner:
    """
    Connects to exchange WebSockets and feeds data to SignalAggregator
    Displays real-time trading signals
    """

    def __init__(self):
        self.aggregator = SignalAggregator()
        self.running = True
        self.signal_count = 0
        self.last_signal_time = None

    async def stream_binance_liquidations(self):
        """Stream Binance liquidations"""
        url = "wss://fstream.binance.com/ws/!forceOrder@arr"

        print("[BINANCE] Connecting...")

        try:
            async with websockets.connect(url) as ws:
                print("[BINANCE] Connected!")

                while self.running:
                    msg = await ws.recv()
                    data = json.loads(msg)

                    if isinstance(data, list):
                        for item in data:
                            if item.get("e") == "forceOrder":
                                await self.process_binance_liq(item.get("o", {}))
                    elif data.get("e") == "forceOrder":
                        await self.process_binance_liq(data.get("o", {}))

        except Exception as e:
            print(f"[BINANCE ERROR] {e}")

    async def process_binance_liq(self, order):
        """Process Binance liquidation and feed to aggregator"""
        symbol = order.get("s", "UNKNOWN")
        side = order.get("S", "").upper()
        price = float(order.get("p", 0))
        qty = float(order.get("q", 0))
        usd_value = price * qty

        liq_side = "short" if side == "BUY" else "long"

        self.aggregator.add_liquidation(
            exchange="Binance",
            symbol=symbol,
            side=liq_side,
            size_usd=usd_value,
            price=price
        )

        if usd_value >= 50000:
            marker = "[LONG]" if liq_side == "long" else "[SHORT]"
            print(f"[LIQ] BINANCE {marker} {symbol} ${usd_value:,.0f}")

        self.signal_count += 1

    async def stream_bybit_liquidations(self):
        """Stream Bybit liquidations"""
        url = "wss://stream.bybit.com/v5/public/linear"

        print("[BYBIT] Connecting...")

        try:
            async with websockets.connect(url) as ws:
                symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
                for symbol in symbols:
                    await ws.send(json.dumps({
                        "op": "subscribe",
                        "args": [f"allLiquidation.{symbol}"]
                    }))

                print("[BYBIT] Connected!")

                # Ping task
                async def ping():
                    while self.running:
                        await asyncio.sleep(20)
                        await ws.send(json.dumps({"op": "ping"}))

                ping_task = asyncio.create_task(ping())

                try:
                    while self.running:
                        msg = await ws.recv()
                        data = json.loads(msg)

                        if data.get("topic", "").startswith("allLiquidation"):
                            await self.process_bybit_liq(data.get("data", {}))
                finally:
                    ping_task.cancel()

        except Exception as e:
            print(f"[BYBIT ERROR] {e}")

    async def process_bybit_liq(self, liq_data):
        """Process Bybit liquidation"""
        symbol = liq_data.get("symbol", "UNKNOWN")
        side = liq_data.get("side", "").upper()
        price = float(liq_data.get("price", 0))
        size = float(liq_data.get("size", 0))
        usd_value = price * size

        liq_side = "short" if side == "BUY" else "long"

        self.aggregator.add_liquidation(
            exchange="Bybit",
            symbol=symbol,
            side=liq_side,
            size_usd=usd_value,
            price=price
        )

        if usd_value >= 10000:
            marker = "[LONG]" if liq_side == "long" else "[SHORT]"
            print(f"[LIQ] BYBIT {marker} {symbol} ${usd_value:,.0f}")

        self.signal_count += 1

    async def stream_hyperliquid_orderbook(self):
        """Stream Hyperliquid order book"""
        url = "wss://api.hyperliquid.xyz/ws"

        print("[HYPERLIQUID] Connecting...")

        try:
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps({
                    "method": "subscribe",
                    "subscription": {"type": "l2Book", "coin": "BTC"}
                }))

                print("[HYPERLIQUID] Connected!")

                while self.running:
                    msg = await ws.recv()
                    data = json.loads(msg)

                    if data.get("channel") == "l2Book":
                        await self.process_orderbook(data.get("data", {}))

        except Exception as e:
            print(f"[HYPERLIQUID ERROR] {e}")

    async def process_orderbook(self, book_data):
        """Process order book and feed to WhaleAgent"""
        levels = book_data.get("levels", [[], []])

        if not levels[0] or not levels[1]:
            return

        # Convert to expected format
        bids = [{"price": float(b.get("px", 0)), "size": float(b.get("sz", 0))}
                for b in levels[0][:50]]
        asks = [{"price": float(a.get("px", 0)), "size": float(a.get("sz", 0))}
                for a in levels[1][:50]]

        self.aggregator.update_order_book("BTC", bids, asks)

    async def print_signals_periodically(self):
        """Print aggregated signal every 30 seconds"""
        await asyncio.sleep(10)  # Initial wait

        while self.running:
            self.aggregator.print_status()
            await asyncio.sleep(30)

    async def run(self):
        """Run the live signal system"""
        print("\n" + "="*70)
        print("     TRADEHIVE'S LIVE SIGNAL RUNNER")
        print("     Streaming: Binance + Bybit Liquidations + Hyperliquid Order Book")
        print("     Signals update every 30 seconds")
        print("     Press Ctrl+C to stop")
        print("="*70 + "\n")

        try:
            await asyncio.gather(
                self.stream_binance_liquidations(),
                self.stream_bybit_liquidations(),
                self.stream_hyperliquid_orderbook(),
                self.print_signals_periodically()
            )
        except KeyboardInterrupt:
            self.running = False
            print("\n[STOPPED] Shutting down...")
            self.aggregator.print_status()


def main():
    runner = LiveSignalRunner()
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
