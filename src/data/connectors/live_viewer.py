"""
TradeHive's Live Data Viewer
Shows real-time order book and liquidation data in terminal

Run this script to see live data streaming from exchanges!
Press Ctrl+C to stop.
"""

import asyncio
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, ".")

from src.data.connectors.base_connector import DataType, LiquidationEvent, OrderBookUpdate
from src.data.connectors.hyperliquid_connector import HyperliquidConnector
from src.data.connectors.binance_connector import BinanceConnector
from src.data.connectors.bybit_connector import BybitConnector


class LiveDataViewer:
    """
    Live terminal viewer for crypto market data
    Shows order book updates and liquidations in real-time
    """

    def __init__(self):
        self.liquidation_count = 0
        self.trade_count = 0
        self.orderbook_updates = 0
        self.total_long_liq = 0.0
        self.total_short_liq = 0.0

    def print_header(self):
        """Print the header"""
        print("\n" + "="*70)
        print("  TRADEHIVE'S LIVE CRYPTO DATA VIEWER")
        print("  Streaming: Hyperliquid + Binance + Bybit")
        print("  Press Ctrl+C to stop")
        print("="*70 + "\n")

    def print_liquidation(self, liq: LiquidationEvent):
        """Print a liquidation event"""
        self.liquidation_count += 1

        if liq.side == "long":
            self.total_long_liq += liq.size
            marker = "[LONG-LIQ]"
        else:
            self.total_short_liq += liq.size
            marker = "[SHORT-LIQ]"

        timestamp = datetime.now().strftime("%H:%M:%S")

        # Only show liquidations >= $1000
        if liq.size >= 1000:
            print(f"[{timestamp}] {marker} {liq.exchange:12} {liq.symbol:12} ${liq.size:>12,.2f} @ {liq.price:,.2f}")

    def print_orderbook(self, update: OrderBookUpdate):
        """Print order book update (first few only)"""
        self.orderbook_updates += 1

        if self.orderbook_updates <= 5:  # Only show first 5
            timestamp = datetime.now().strftime("%H:%M:%S")
            spread = update.spread() if update.spread() else 0
            print(f"[{timestamp}] [ORDERBOOK] {update.exchange:12} {update.symbol:8} Bid: {update.best_bid():>10,.2f} | Ask: {update.best_ask():>10,.2f} | Spread: {spread:.4f}")

    def print_trade(self, trade):
        """Print trade event (sampled)"""
        self.trade_count += 1

        # Only show every 10th trade to avoid spam
        if self.trade_count % 10 == 0:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] [TRADE] {trade.exchange:12} {trade.symbol:8} {trade.side.upper():4} {trade.size:>10,.4f} @ {trade.price:,.2f}")

    def print_stats(self):
        """Print current statistics"""
        print("\n" + "-"*70)
        print(f"  STATS | Liquidations: {self.liquidation_count} | Trades: {self.trade_count} | OrderBook updates: {self.orderbook_updates}")
        print(f"  TOTALS | Long Liq: ${self.total_long_liq:,.2f} | Short Liq: ${self.total_short_liq:,.2f}")
        if self.total_short_liq > 0:
            ratio = self.total_long_liq / self.total_short_liq
            print(f"  RATIO | Long/Short: {ratio:.2f} {'(BEARISH - more longs liquidated)' if ratio > 1.5 else '(BULLISH - more shorts liquidated)' if ratio < 0.67 else '(NEUTRAL)'}")
        print("-"*70 + "\n")

    async def run(self, duration_minutes: int = None):
        """
        Run the live data viewer

        Args:
            duration_minutes: Run for this many minutes, or None for indefinite
        """
        self.print_header()

        # Create connectors
        print("[INFO] Initializing connectors...")
        hyperliquid = HyperliquidConnector()
        binance = BinanceConnector(use_all_markets=True)
        bybit = BybitConnector(use_linear=True)

        # Register callbacks
        hyperliquid.on_data(DataType.LIQUIDATION, self.print_liquidation)
        hyperliquid.on_data(DataType.ORDER_BOOK, self.print_orderbook)
        hyperliquid.on_data(DataType.TRADE, self.print_trade)

        binance.on_data(DataType.LIQUIDATION, self.print_liquidation)
        bybit.on_data(DataType.LIQUIDATION, self.print_liquidation)

        print("[INFO] Connecting to exchanges...\n")

        try:
            # Start all connectors
            await hyperliquid.start(
                ["BTC", "ETH", "SOL"],
                [DataType.ORDER_BOOK, DataType.TRADE, DataType.LIQUIDATION]
            )
            await binance.start([], [DataType.LIQUIDATION])
            await bybit.start(
                ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
                [DataType.LIQUIDATION]
            )

            print("[LIVE] Streaming data... (Ctrl+C to stop)\n")
            print("-"*70)
            print(f"{'TIME':10} {'TYPE':12} {'EXCHANGE':12} {'SYMBOL':12} {'DETAILS'}")
            print("-"*70)

            # Run until stopped
            stats_interval = 60  # Print stats every 60 seconds
            elapsed = 0

            while True:
                await asyncio.sleep(1)
                elapsed += 1

                # Print stats periodically
                if elapsed % stats_interval == 0:
                    self.print_stats()

                # Check duration limit
                if duration_minutes and elapsed >= duration_minutes * 60:
                    break

        except KeyboardInterrupt:
            print("\n\n[STOPPING] User interrupted...")
        except Exception as e:
            print(f"\n[ERROR] {e}")
        finally:
            # Cleanup
            print("[INFO] Disconnecting...")
            await hyperliquid.disconnect()
            await binance.disconnect()
            await bybit.disconnect()

            # Final stats
            self.print_stats()
            print("[DONE] Live viewer stopped.\n")


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="TradeHive's Live Crypto Data Viewer")
    parser.add_argument(
        "-d", "--duration",
        type=int,
        default=None,
        help="Duration in minutes (default: run indefinitely)"
    )
    args = parser.parse_args()

    viewer = LiveDataViewer()
    asyncio.run(viewer.run(args.duration))


if __name__ == "__main__":
    main()
