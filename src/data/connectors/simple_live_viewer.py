"""
TradeHive's Simple Live Data Viewer
Minimal version that bypasses the connector framework for testing
Shows real-time liquidation data in terminal

Run: python -u src/data/connectors/simple_live_viewer.py
Press Ctrl+C to stop.
"""

import asyncio
import json
import sys
from datetime import datetime
import websockets

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)


async def stream_binance_liquidations():
    """Stream Binance liquidations"""
    url = "wss://fstream.binance.com/ws/!forceOrder@arr"

    print("[BINANCE] Connecting to liquidation stream...")

    try:
        async with websockets.connect(url) as ws:
            print("[BINANCE] Connected! Waiting for liquidations...\n")

            while True:
                msg = await ws.recv()
                data = json.loads(msg)

                # Handle array of liquidations
                if isinstance(data, list):
                    for item in data:
                        if item.get("e") == "forceOrder":
                            await process_binance_liq(item.get("o", {}))
                elif data.get("e") == "forceOrder":
                    await process_binance_liq(data.get("o", {}))

    except Exception as e:
        print(f"[BINANCE ERROR] {e}")


async def process_binance_liq(order):
    """Process Binance liquidation"""
    symbol = order.get("s", "UNKNOWN")
    side = order.get("S", "").upper()
    price = float(order.get("p", 0))
    qty = float(order.get("q", 0))
    usd_value = price * qty

    # Determine liquidated side
    liq_side = "SHORT" if side == "BUY" else "LONG"

    timestamp = datetime.now().strftime("%H:%M:%S")

    # Only show liquidations >= $5000
    if usd_value >= 5000:
        marker = "[LONG-LIQ] " if liq_side == "LONG" else "[SHORT-LIQ]"
        print(f"[{timestamp}] BINANCE  {marker} {symbol:12} ${usd_value:>12,.2f} @ {price:,.2f}")


async def stream_bybit_liquidations():
    """Stream Bybit liquidations"""
    url = "wss://stream.bybit.com/v5/public/linear"

    print("[BYBIT] Connecting to liquidation stream...")

    try:
        async with websockets.connect(url) as ws:
            # Subscribe to liquidations
            symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
            for symbol in symbols:
                sub_msg = {
                    "op": "subscribe",
                    "args": [f"allLiquidation.{symbol}"]
                }
                await ws.send(json.dumps(sub_msg))

            print("[BYBIT] Connected! Waiting for liquidations...\n")

            # Send pings
            async def ping():
                while True:
                    await asyncio.sleep(20)
                    await ws.send(json.dumps({"op": "ping"}))

            ping_task = asyncio.create_task(ping())

            try:
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)

                    if data.get("topic", "").startswith("allLiquidation"):
                        await process_bybit_liq(data.get("data", {}))
            finally:
                ping_task.cancel()

    except Exception as e:
        print(f"[BYBIT ERROR] {e}")


async def process_bybit_liq(liq_data):
    """Process Bybit liquidation"""
    symbol = liq_data.get("symbol", "UNKNOWN")
    side = liq_data.get("side", "").upper()
    price = float(liq_data.get("price", 0))
    size = float(liq_data.get("size", 0))
    usd_value = price * size

    # Determine liquidated side
    liq_side = "SHORT" if side == "BUY" else "LONG"

    timestamp = datetime.now().strftime("%H:%M:%S")

    # Show all Bybit liquidations
    if usd_value >= 1000:
        marker = "[LONG-LIQ] " if liq_side == "LONG" else "[SHORT-LIQ]"
        print(f"[{timestamp}] BYBIT    {marker} {symbol:12} ${usd_value:>12,.2f} @ {price:,.2f}")


async def stream_hyperliquid():
    """Stream Hyperliquid order book"""
    url = "wss://api.hyperliquid.xyz/ws"

    print("[HYPERLIQUID] Connecting...")

    try:
        async with websockets.connect(url) as ws:
            # Subscribe to BTC order book
            sub_msg = {
                "method": "subscribe",
                "subscription": {
                    "type": "l2Book",
                    "coin": "BTC"
                }
            }
            await ws.send(json.dumps(sub_msg))

            print("[HYPERLIQUID] Connected! Streaming BTC order book...\n")

            count = 0
            while True:
                msg = await ws.recv()
                data = json.loads(msg)

                if data.get("channel") == "l2Book":
                    count += 1
                    if count % 10 == 0:  # Only show every 10th update
                        book_data = data.get("data", {})
                        levels = book_data.get("levels", [[], []])

                        if levels[0] and levels[1]:
                            best_bid = float(levels[0][0].get("px", 0))
                            best_ask = float(levels[1][0].get("px", 0))
                            spread = best_ask - best_bid

                            timestamp = datetime.now().strftime("%H:%M:%S")
                            print(f"[{timestamp}] HYPERLIQ [ORDERBOOK] BTC  Bid: {best_bid:>10,.2f} | Ask: {best_ask:>10,.2f} | Spread: ${spread:.2f}")

    except Exception as e:
        print(f"[HYPERLIQUID ERROR] {e}")


async def main():
    """Run all streams concurrently"""
    print("\n" + "="*70)
    print("  TRADEHIVE'S SIMPLE LIVE DATA VIEWER")
    print("  Streaming: Binance + Bybit Liquidations + Hyperliquid Order Book")
    print("  Press Ctrl+C to stop")
    print("="*70 + "\n")

    print("-"*70)
    print(f"{'TIME':10} {'EXCHANGE':9} {'TYPE':12} {'SYMBOL':12} {'DETAILS'}")
    print("-"*70 + "\n")

    # Run all streams concurrently
    try:
        await asyncio.gather(
            stream_binance_liquidations(),
            stream_bybit_liquidations(),
            stream_hyperliquid()
        )
    except KeyboardInterrupt:
        print("\n\n[STOPPED] User interrupted.")


if __name__ == "__main__":
    asyncio.run(main())
