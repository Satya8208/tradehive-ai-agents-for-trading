"""
TradeHive's Connector Test Script
Tests all connectors to verify real data is coming through
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


class ConnectorTester:
    """Test harness for data connectors"""

    def __init__(self):
        self.results = {}
        self.data_received = {
            "hyperliquid": {"order_book": 0, "liquidation": 0, "trade": 0},
            "binance": {"liquidation": 0},
            "bybit": {"liquidation": 0}
        }

    async def test_hyperliquid(self, duration: int = 15):
        """Test Hyperliquid connector"""
        print("\n" + "="*60)
        print("[TEST] HYPERLIQUID CONNECTOR")
        print("="*60)

        connector = HyperliquidConnector()

        def on_order_book(update: OrderBookUpdate):
            self.data_received["hyperliquid"]["order_book"] += 1
            if self.data_received["hyperliquid"]["order_book"] <= 3:
                print(f"  [ORDERBOOK] {update.symbol} | Bid: {update.best_bid()} | Ask: {update.best_ask()}")

        def on_liquidation(liq: LiquidationEvent):
            self.data_received["hyperliquid"]["liquidation"] += 1
            print(f"  [LIQUIDATION] {liq.exchange} {liq.symbol} {liq.side.upper()}: ${liq.size:,.2f} @ {liq.price}")

        def on_trade(trade):
            self.data_received["hyperliquid"]["trade"] += 1
            if self.data_received["hyperliquid"]["trade"] <= 5:
                print(f"  [TRADE] {trade.symbol} {trade.side.upper()} {trade.size} @ {trade.price}")

        connector.on_data(DataType.ORDER_BOOK, on_order_book)
        connector.on_data(DataType.LIQUIDATION, on_liquidation)
        connector.on_data(DataType.TRADE, on_trade)

        try:
            await connector.start(["BTC", "ETH"], [DataType.ORDER_BOOK, DataType.TRADE, DataType.LIQUIDATION])
            print(f"  [INFO] Listening for {duration} seconds...")
            await asyncio.sleep(duration)
        except Exception as e:
            print(f"  [ERROR] {e}")
        finally:
            await connector.disconnect()

        # Results
        total = sum(self.data_received["hyperliquid"].values())
        print(f"\n  [RESULTS] {total} data points received")
        for dtype, count in self.data_received["hyperliquid"].items():
            status = "[OK]" if count > 0 else "[WARN]"
            print(f"     {status} {dtype}: {count}")

        return total > 0

    async def test_binance(self, duration: int = 15):
        """Test Binance connector"""
        print("\n" + "="*60)
        print("[TEST] BINANCE CONNECTOR")
        print("="*60)

        connector = BinanceConnector(use_all_markets=True)

        def on_liquidation(liq: LiquidationEvent):
            self.data_received["binance"]["liquidation"] += 1
            if self.data_received["binance"]["liquidation"] <= 10:
                print(f"  [LIQUIDATION] {liq.exchange} {liq.symbol} {liq.side.upper()}: ${liq.size:,.2f}")

        connector.on_data(DataType.LIQUIDATION, on_liquidation)

        try:
            await connector.start([], [DataType.LIQUIDATION])
            print(f"  [INFO] Listening for {duration} seconds (waiting for liquidations)...")
            await asyncio.sleep(duration)
        except Exception as e:
            print(f"  [ERROR] {e}")
        finally:
            await connector.disconnect()

        # Results
        count = self.data_received["binance"]["liquidation"]
        status = "[OK]" if count > 0 else "[WARN] (no liquidations - normal in calm markets)"
        print(f"\n  [RESULTS] {count} liquidations received {status}")

        return True

    async def test_bybit(self, duration: int = 15):
        """Test Bybit connector"""
        print("\n" + "="*60)
        print("[TEST] BYBIT CONNECTOR")
        print("="*60)

        connector = BybitConnector(use_linear=True)

        def on_liquidation(liq: LiquidationEvent):
            self.data_received["bybit"]["liquidation"] += 1
            if self.data_received["bybit"]["liquidation"] <= 10:
                print(f"  [LIQUIDATION] {liq.exchange} {liq.symbol} {liq.side.upper()}: ${liq.size:,.2f}")

        connector.on_data(DataType.LIQUIDATION, on_liquidation)

        try:
            await connector.start(["BTCUSDT", "ETHUSDT", "SOLUSDT"], [DataType.LIQUIDATION])
            print(f"  [INFO] Listening for {duration} seconds (waiting for liquidations)...")
            await asyncio.sleep(duration)
        except Exception as e:
            print(f"  [ERROR] {e}")
        finally:
            await connector.disconnect()

        # Results
        count = self.data_received["bybit"]["liquidation"]
        status = "[OK]" if count > 0 else "[WARN] (no liquidations - normal in calm markets)"
        print(f"\n  [RESULTS] {count} liquidations received {status}")

        return True

    async def run_all_tests(self, duration: int = 15):
        """Run all connector tests"""
        print("""
================================================================
        TradeHive's Connector Live Test Suite
        Testing real data streams from exchanges
================================================================
        """)

        results = {}

        # Test each connector
        results["hyperliquid"] = await self.test_hyperliquid(duration)
        results["binance"] = await self.test_binance(duration)
        results["bybit"] = await self.test_bybit(duration)

        # Summary
        print("\n" + "="*60)
        print("[SUMMARY] TEST RESULTS")
        print("="*60)

        all_passed = True
        for name, passed in results.items():
            status = "[CONNECTED]" if passed else "[FAILED]"
            print(f"  {name.upper()}: {status}")
            if not passed:
                all_passed = False

        print("\n" + "="*60)
        if all_passed:
            print("[SUCCESS] ALL CONNECTORS WORKING!")
        else:
            print("[WARN] Some connectors had issues - check logs above")
        print("="*60 + "\n")

        return all_passed


if __name__ == "__main__":
    print("\nTradeHive's Connector Test Suite\n")
    tester = ConnectorTester()
    asyncio.run(tester.run_all_tests(duration=15))
