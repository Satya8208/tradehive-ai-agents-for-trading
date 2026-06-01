"""
TradeHive's Live AI Signal Runner
Connects real-time exchange data to AI-powered signal aggregator

This uses a SWARM of AI models to reach consensus on trading decisions!

Run: python -u src/agents/polymarket/live_ai_signals.py
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

from src.agents.polymarket.signal_agents.ai_signal_aggregator import AISignalAggregator


class LiveAISignalRunner:
    """
    Connects to exchange WebSockets and uses AI swarm
    to make consensus trading decisions
    """

    def __init__(self, use_ai: bool = True, signal_interval: int = 60):
        """
        Initialize the live runner

        Args:
            use_ai: Whether to use AI swarm (True) or just rules (False)
            signal_interval: Seconds between AI signal checks
        """
        self.aggregator = AISignalAggregator(use_ai=use_ai)
        self.running = True
        self.signal_interval = signal_interval
        self.liq_count = 0
        self.last_signal = None

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
        """Process Binance liquidation"""
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

        self.liq_count += 1

        # Print large liquidations
        if usd_value >= 100000:
            marker = "[LONG-LIQ]" if liq_side == "long" else "[SHORT-LIQ]"
            print(f">>> {marker} BINANCE {symbol} ${usd_value:,.0f}")

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

                async def ping():
                    while self.running:
                        await asyncio.sleep(20)
                        try:
                            await ws.send(json.dumps({"op": "ping"}))
                        except:
                            break

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

        self.liq_count += 1

        if usd_value >= 50000:
            marker = "[LONG-LIQ]" if liq_side == "long" else "[SHORT-LIQ]"
            print(f">>> {marker} BYBIT {symbol} ${usd_value:,.0f}")

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
        """Process order book"""
        levels = book_data.get("levels", [[], []])

        if not levels[0] or not levels[1]:
            return

        bids = [{"price": float(b.get("px", 0)), "size": float(b.get("sz", 0))}
                for b in levels[0][:50]]
        asks = [{"price": float(a.get("px", 0)), "size": float(a.get("sz", 0))}
                for a in levels[1][:50]]

        self.aggregator.update_order_book("BTC", bids, asks)

    async def generate_ai_signals_periodically(self):
        """Generate AI signals at regular intervals"""
        # Wait for initial data collection
        print(f"\n[INFO] Collecting data for {self.signal_interval}s before first AI signal...\n")
        await asyncio.sleep(self.signal_interval)

        while self.running:
            print("\n" + "="*70)
            print("      GENERATING AI CONSENSUS SIGNAL...")
            print("="*70)

            try:
                # Get AI signal (this queries the swarm)
                signal = self.aggregator.get_ai_signal()
                self.last_signal = signal

                # Print results
                print(f"\n[AI CONSENSUS RESULT]")
                print(f"  Decision: {signal.decision.value}")
                print(f"  Confidence: {signal.confidence:.0f}%")
                print(f"  Models Agreed: {signal.models_agreed}/{signal.models_total}")
                print(f"  Reasoning: {signal.consensus_reasoning}")

                # Print action
                if "HOLD" in signal.decision.value:
                    print(f"\n  >>> ACTION: NO TRADE (wait for stronger signal)")
                elif "YES" in signal.decision.value:
                    strength = "STRONG " if "STRONG" in signal.decision.value else ""
                    print(f"\n  >>> ACTION: {strength}BUY YES on crypto price prediction")
                    print(f"              (AI thinks BTC/crypto prices will GO UP)")
                else:
                    strength = "STRONG " if "STRONG" in signal.decision.value else ""
                    print(f"\n  >>> ACTION: {strength}BUY NO on crypto price prediction")
                    print(f"              (AI thinks BTC/crypto prices will GO DOWN)")

                print("="*70 + "\n")

            except Exception as e:
                print(f"[ERROR] Failed to generate AI signal: {e}")

            # Wait for next interval
            await asyncio.sleep(self.signal_interval)

    async def print_status_periodically(self):
        """Print basic status between AI signals"""
        await asyncio.sleep(30)

        while self.running:
            print(f"\n[STATUS] Liquidations collected: {self.liq_count} | Next AI signal in ~{self.signal_interval}s")
            await asyncio.sleep(30)

    async def run(self):
        """Run the live AI signal system"""
        print("\n" + "="*70)
        print("     TRADEHIVE'S LIVE AI SIGNAL RUNNER")
        print("     Using AI SWARM for consensus trading decisions!")
        print("="*70)
        print(f"  Data Sources: Binance + Bybit Liquidations + Hyperliquid Order Book")
        print(f"  AI Signal Interval: Every {self.signal_interval} seconds")
        print(f"  Press Ctrl+C to stop")
        print("="*70 + "\n")

        try:
            await asyncio.gather(
                self.stream_binance_liquidations(),
                self.stream_bybit_liquidations(),
                self.stream_hyperliquid_orderbook(),
                self.generate_ai_signals_periodically(),
                self.print_status_periodically()
            )
        except KeyboardInterrupt:
            self.running = False
            print("\n[STOPPED] Shutting down...")
            if self.last_signal:
                print(f"Last signal: {self.last_signal.decision.value}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="TradeHive's Live AI Signal Runner")
    parser.add_argument("--no-ai", action="store_true", help="Disable AI, use rules only")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between AI signals")
    args = parser.parse_args()

    runner = LiveAISignalRunner(
        use_ai=not args.no_ai,
        signal_interval=args.interval
    )
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
