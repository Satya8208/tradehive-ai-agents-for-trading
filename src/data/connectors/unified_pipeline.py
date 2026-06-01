"""
🌙 TradeHive's Unified Data Pipeline
Central aggregation layer for all exchange data connectors

Replaces TradeHiveAPIClient with real-time WebSocket data from:
- Binance (liquidations)
- Bybit (liquidations)
- Hyperliquid (order book, trades, funding)

Built with love by TradeHive 🚀
"""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any, Union

from termcolor import cprint

from src.data.connectors.base_connector import (
    BaseConnector,
    DataType,
    LiquidationEvent,
    OrderBookUpdate,
    TradeEvent,
    FundingRateEvent,
)
from src.data.connectors.binance_connector import BinanceConnector
from src.data.connectors.bybit_connector import BybitConnector
from src.data.connectors.hyperliquid_connector import HyperliquidConnector


logger = logging.getLogger(__name__)


@dataclass
class DataBuffer:
    """
    Rolling buffer for market data with time-based pruning.

    Maintains a fixed-size buffer of recent events with automatic
    cleanup of old entries.
    """
    max_size: int = 1000
    time_window_seconds: int = 300  # 5 minutes
    items: deque = field(default_factory=deque)

    def append(self, item: Any) -> None:
        """Add item to buffer and prune old entries."""
        self.items.append(item)
        self._prune()

    def _prune(self) -> None:
        """Remove items outside time window or over max size."""
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=self.time_window_seconds)

        # Remove old items
        while self.items:
            oldest = self.items[0]
            if hasattr(oldest, 'timestamp') and oldest.timestamp < cutoff:
                self.items.popleft()
            elif len(self.items) > self.max_size:
                self.items.popleft()
            else:
                break

    def get_recent(self, seconds: int = 60) -> List[Any]:
        """Get items from last N seconds."""
        cutoff = datetime.utcnow() - timedelta(seconds=seconds)
        return [
            item for item in self.items
            if hasattr(item, 'timestamp') and item.timestamp > cutoff
        ]

    def get_all(self) -> List[Any]:
        """Get all items in buffer."""
        return list(self.items)

    def clear(self) -> None:
        """Clear all items."""
        self.items.clear()

    def __len__(self) -> int:
        return len(self.items)


class UnifiedDataPipeline:
    """
    Central data aggregation layer for crypto market data.

    Manages multiple exchange connectors and provides a unified API
    for accessing real-time market data. Replaces TradeHiveAPIClient.

    Features:
    - Real-time WebSocket data from multiple exchanges
    - Rolling buffers for each data type
    - Aggregated metrics (liquidation ratio, whale trades, etc.)
    - Callback registration for real-time updates

    Usage:
        pipeline = UnifiedDataPipeline()
        await pipeline.start()

        # Get recent liquidations
        liqs = pipeline.get_recent_liquidations(seconds=60)

        # Get liquidation ratio
        ratio = pipeline.get_liquidation_ratio()

        # Get order book
        book = pipeline.get_order_book("BTC")

        await pipeline.stop()
    """

    def __init__(
        self,
        enable_binance: bool = True,
        enable_bybit: bool = True,
        enable_hyperliquid: bool = True,
        buffer_size: int = 1000,
        buffer_window_seconds: int = 300,
    ):
        """
        Initialize the unified pipeline.

        Args:
            enable_binance: Enable Binance liquidation stream
            enable_bybit: Enable Bybit liquidation stream
            enable_hyperliquid: Enable Hyperliquid data stream
            buffer_size: Maximum items per buffer
            buffer_window_seconds: Time window for buffer pruning
        """
        self.enable_binance = enable_binance
        self.enable_bybit = enable_bybit
        self.enable_hyperliquid = enable_hyperliquid

        # Data buffers
        self._buffers: Dict[DataType, DataBuffer] = {
            DataType.LIQUIDATION: DataBuffer(buffer_size, buffer_window_seconds),
            DataType.ORDER_BOOK: DataBuffer(100, 60),  # Smaller buffer for order books
            DataType.TRADE: DataBuffer(buffer_size, buffer_window_seconds),
            DataType.FUNDING_RATE: DataBuffer(50, 3600),  # 1 hour for funding
            DataType.OPEN_INTEREST: DataBuffer(200, 86400),  # 24 hours for OI tracking
        }

        # Historical tracking for backtesting and signal analysis
        self._funding_rate_history: Dict[str, List[FundingRateEvent]] = {}  # symbol -> list
        self._oi_history: Dict[str, List[Dict[str, Any]]] = {}  # symbol -> list
        self._volume_history: Dict[str, List[Dict[str, Any]]] = {}  # symbol -> list

        # Connectors
        self._connectors: Dict[str, BaseConnector] = {}

        # Callback registry
        self._callbacks: Dict[DataType, List[Callable]] = {
            dt: [] for dt in DataType
        }

        # State
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._start_time: Optional[datetime] = None

        # Statistics
        self._stats = {
            "liquidations_received": 0,
            "trades_received": 0,
            "orderbook_updates": 0,
            "long_liq_volume": 0.0,
            "short_liq_volume": 0.0,
        }

        cprint("[PIPELINE] Unified Data Pipeline initialized", "cyan")

    def _init_connectors(self) -> None:
        """Initialize exchange connectors."""
        if self.enable_binance:
            connector = BinanceConnector(min_usd_value=1000)
            connector.on_data(DataType.LIQUIDATION, self._on_liquidation)
            self._connectors["binance"] = connector
            cprint("[PIPELINE] Binance connector added", "green")

        if self.enable_bybit:
            connector = BybitConnector(min_usd_value=1000)
            connector.on_data(DataType.LIQUIDATION, self._on_liquidation)
            self._connectors["bybit"] = connector
            cprint("[PIPELINE] Bybit connector added", "green")

        if self.enable_hyperliquid:
            connector = HyperliquidConnector()
            connector.on_data(DataType.ORDER_BOOK, self._on_orderbook)
            connector.on_data(DataType.TRADE, self._on_trade)
            self._connectors["hyperliquid"] = connector
            cprint("[PIPELINE] Hyperliquid connector added", "green")

    # ==================== LIFECYCLE ====================

    async def start(self) -> None:
        """Start all connectors and begin streaming data."""
        if self._running:
            cprint("[PIPELINE] Already running", "yellow")
            return

        cprint("\n[PIPELINE] Starting unified data pipeline...", "cyan")
        self._running = True
        self._start_time = datetime.utcnow()

        # Initialize connectors
        self._init_connectors()

        # Start each connector
        for name, connector in self._connectors.items():
            try:
                if name == "binance":
                    task = asyncio.create_task(
                        connector.start([], [DataType.LIQUIDATION])
                    )
                elif name == "bybit":
                    task = asyncio.create_task(
                        connector.start([], [DataType.LIQUIDATION])
                    )
                elif name == "hyperliquid":
                    task = asyncio.create_task(
                        connector.start(
                            ["BTC", "ETH", "SOL"],
                            [DataType.ORDER_BOOK, DataType.TRADE]
                        )
                    )
                else:
                    continue

                self._tasks.append(task)
                cprint(f"[PIPELINE] Started {name} connector", "green")

            except Exception as e:
                cprint(f"[PIPELINE] Failed to start {name}: {e}", "red")

        cprint("[PIPELINE] All connectors started", "green")

    async def stop(self) -> None:
        """Stop all connectors and cleanup."""
        if not self._running:
            return

        cprint("\n[PIPELINE] Stopping...", "yellow")
        self._running = False

        # Disconnect all connectors
        for name, connector in self._connectors.items():
            try:
                await connector.disconnect()
                cprint(f"[PIPELINE] Disconnected {name}", "yellow")
            except Exception as e:
                cprint(f"[PIPELINE] Error disconnecting {name}: {e}", "red")

        # Cancel tasks
        for task in self._tasks:
            task.cancel()

        self._tasks.clear()
        cprint("[PIPELINE] Stopped", "yellow")

    # ==================== CALLBACKS ====================

    async def _on_liquidation(self, event: LiquidationEvent) -> None:
        """Handle incoming liquidation event."""
        self._buffers[DataType.LIQUIDATION].append(event)
        self._stats["liquidations_received"] += 1

        # Track volume by side
        if event.side == "long":
            self._stats["long_liq_volume"] += event.size
        else:
            self._stats["short_liq_volume"] += event.size

        # Emit to registered callbacks
        await self._emit_callbacks(DataType.LIQUIDATION, event)

    async def _on_orderbook(self, event: OrderBookUpdate) -> None:
        """Handle incoming order book update."""
        self._buffers[DataType.ORDER_BOOK].append(event)
        self._stats["orderbook_updates"] += 1

        await self._emit_callbacks(DataType.ORDER_BOOK, event)

    async def _on_trade(self, event: TradeEvent) -> None:
        """Handle incoming trade event."""
        self._buffers[DataType.TRADE].append(event)
        self._stats["trades_received"] += 1

        await self._emit_callbacks(DataType.TRADE, event)

    async def _emit_callbacks(self, data_type: DataType, event: Any) -> None:
        """Emit event to registered callbacks."""
        for callback in self._callbacks[data_type]:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                logger.error(f"Callback error for {data_type.value}: {e}")

    def subscribe(self, data_type: DataType, callback: Callable) -> None:
        """Register a callback for real-time data updates."""
        self._callbacks[data_type].append(callback)

    def unsubscribe(self, data_type: DataType, callback: Callable) -> None:
        """Remove a callback."""
        if callback in self._callbacks[data_type]:
            self._callbacks[data_type].remove(callback)

    # ==================== LIQUIDATION API ====================

    def get_recent_liquidations(
        self,
        seconds: int = 60,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        min_usd_value: float = 0,
    ) -> List[LiquidationEvent]:
        """
        Get recent liquidation events.

        Args:
            seconds: Time window in seconds
            exchange: Filter by exchange (binance, bybit)
            symbol: Filter by symbol (BTCUSDT, ETHUSDT)
            min_usd_value: Minimum USD value filter

        Returns:
            List of LiquidationEvent sorted by timestamp (newest first)
        """
        liquidations = self._buffers[DataType.LIQUIDATION].get_recent(seconds)

        # Apply filters
        if exchange:
            liquidations = [l for l in liquidations if l.exchange == exchange]
        if symbol:
            liquidations = [l for l in liquidations if symbol.upper() in l.symbol.upper()]
        if min_usd_value > 0:
            liquidations = [l for l in liquidations if l.size >= min_usd_value]

        # Sort by timestamp descending
        return sorted(liquidations, key=lambda x: x.timestamp, reverse=True)

    def get_liquidation_volume(
        self,
        seconds: int = 300,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Get aggregated liquidation volume by side.

        Args:
            seconds: Time window
            exchange: Filter by exchange
            symbol: Filter by symbol

        Returns:
            Dict with 'long', 'short', and 'total' USD volumes
        """
        liquidations = self.get_recent_liquidations(seconds, exchange, symbol)

        result = {"long": 0.0, "short": 0.0, "total": 0.0}
        for liq in liquidations:
            result[liq.side] += liq.size
            result["total"] += liq.size

        return result

    def get_liquidation_ratio(
        self,
        seconds: int = 300,
        exchange: Optional[str] = None,
    ) -> float:
        """
        Get long/short liquidation ratio.

        Returns:
            Ratio > 1.0 means more longs liquidated (bearish pressure)
            Ratio < 1.0 means more shorts liquidated (bullish pressure)
            Ratio = 1.0 means balanced
        """
        volume = self.get_liquidation_volume(seconds, exchange)

        if volume["short"] == 0:
            return float('inf') if volume["long"] > 0 else 1.0

        return volume["long"] / volume["short"]

    def get_liquidation_count(
        self,
        seconds: int = 300,
        exchange: Optional[str] = None,
    ) -> Dict[str, int]:
        """Get liquidation count by side."""
        liquidations = self.get_recent_liquidations(seconds, exchange)

        result = {"long": 0, "short": 0, "total": 0}
        for liq in liquidations:
            result[liq.side] += 1
            result["total"] += 1

        return result

    # ==================== ORDER BOOK API ====================

    def get_order_book(
        self,
        symbol: str,
        exchange: str = "hyperliquid"
    ) -> Optional[OrderBookUpdate]:
        """
        Get latest order book snapshot for a symbol.

        Args:
            symbol: Coin symbol (BTC, ETH)
            exchange: Exchange name

        Returns:
            Latest OrderBookUpdate or None
        """
        books = self._buffers[DataType.ORDER_BOOK].get_all()

        # Find most recent book for this symbol
        for book in reversed(books):
            if book.symbol.upper() == symbol.upper() and book.exchange == exchange:
                return book

        return None

    def get_order_book_imbalance(
        self,
        symbol: str,
        levels: int = 5
    ) -> float:
        """
        Calculate bid/ask volume imbalance.

        Returns:
            Value between -1 and 1
            > 0 means bid heavy (bullish)
            < 0 means ask heavy (bearish)
        """
        book = self.get_order_book(symbol)
        if not book or not book.bids or not book.asks:
            return 0.0

        bid_volume = sum(b["size"] for b in book.bids[:levels])
        ask_volume = sum(a["size"] for a in book.asks[:levels])

        total = bid_volume + ask_volume
        if total == 0:
            return 0.0

        return (bid_volume - ask_volume) / total

    def get_spread(self, symbol: str) -> Optional[float]:
        """Get current bid-ask spread for a symbol."""
        book = self.get_order_book(symbol)
        if book:
            return book.spread()
        return None

    # ==================== TRADE API ====================

    def get_recent_trades(
        self,
        symbol: str,
        seconds: int = 60,
        exchange: Optional[str] = None,
    ) -> List[TradeEvent]:
        """Get recent trades for a symbol."""
        trades = self._buffers[DataType.TRADE].get_recent(seconds)

        # Filter by symbol
        trades = [t for t in trades if t.symbol.upper() == symbol.upper()]

        if exchange:
            trades = [t for t in trades if t.exchange == exchange]

        return sorted(trades, key=lambda x: x.timestamp, reverse=True)

    def get_trade_flow(
        self,
        symbol: str,
        seconds: int = 60
    ) -> Dict[str, float]:
        """
        Get buy/sell volume flow for a symbol.

        Returns:
            Dict with 'buy', 'sell', and 'net' USD volumes
        """
        trades = self.get_recent_trades(symbol, seconds)

        result = {"buy": 0.0, "sell": 0.0, "net": 0.0}
        for trade in trades:
            usd_value = trade.price * trade.size
            result[trade.side] += usd_value

        result["net"] = result["buy"] - result["sell"]
        return result

    def get_whale_trades(
        self,
        min_usd_value: float = 100000,
        seconds: int = 300,
        symbol: Optional[str] = None,
    ) -> List[TradeEvent]:
        """
        Get large trades above threshold.

        Args:
            min_usd_value: Minimum USD value for whale trade
            seconds: Time window
            symbol: Optional symbol filter

        Returns:
            List of whale trades
        """
        trades = self._buffers[DataType.TRADE].get_recent(seconds)

        whale_trades = []
        for trade in trades:
            usd_value = trade.price * trade.size
            if usd_value >= min_usd_value:
                if symbol is None or trade.symbol.upper() == symbol.upper():
                    whale_trades.append(trade)

        return sorted(whale_trades, key=lambda x: x.timestamp, reverse=True)

    # ==================== FUNDING API ====================

    async def get_funding_rates(self) -> Dict[str, FundingRateEvent]:
        """
        Fetch current funding rates from Hyperliquid.

        Returns:
            Dict mapping coin to FundingRateEvent
        """
        if "hyperliquid" in self._connectors:
            connector = self._connectors["hyperliquid"]
            if isinstance(connector, HyperliquidConnector):
                return await connector.get_funding_rates()
        return {}

    async def get_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Fetch open interest data for a symbol via Hyperliquid connector.

        Args:
            symbol: Coin symbol (BTC, ETH, etc.)

        Returns:
            Dict with open_interest, oi_change_24h, and timestamp
            or None if not available
        """
        if "hyperliquid" in self._connectors:
            connector = self._connectors["hyperliquid"]
            if isinstance(connector, HyperliquidConnector):
                return await connector.get_open_interest(symbol)
        return None

    async def get_funding_rate_summary(
        self,
        symbol: str,
        hours: int = 24
    ) -> Optional[Dict[str, Any]]:
        """
        Get comprehensive funding rate analysis for a symbol.

        Args:
            symbol: Coin symbol (BTC, ETH, etc.)
            hours: Lookback period in hours (default: 24)

        Returns:
            Dict with current_rate, avg_rate, trend, max/min values
            or None if not available
        """
        if "hyperliquid" in self._connectors:
            connector = self._connectors["hyperliquid"]
            if isinstance(connector, HyperliquidConnector):
                # Note: This method exists in HyperliquidConnector but name differs
                # We'll use the available method
                return await connector.get_funding_rate_24h_summary(symbol)
        return None

    def get_order_book_metrics(
        self,
        symbol: str,
        levels: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        Calculate comprehensive order book metrics.

        Args:
            symbol: Coin symbol (BTC, ETH, etc.)
            levels: Number of order book levels to analyze

        Returns:
            Dict with {
                'bid_volume': float,
                'ask_volume': float,
                'imbalance_ratio': float ( -1 to 1),
                'total_liquidity': float,
                'bid_depth': float (avg per level),
                'ask_depth': float (avg per level),
                'whale_bids': int (>$100k orders),
                'whale_asks': int (>$100k orders),
                'spread': Optional[float],
                'mid_price': Optional[float]
            }
            or None if no order book data available
        """
        book = self.get_order_book(symbol)
        if not book or not book.bids or not book.asks:
            return None

        # Calculate bid/ask volumes
        bid_volume = sum(b["size"] for b in book.bids[:levels])
        ask_volume = sum(a["size"] for a in book.asks[:levels])
        total_liquidity = bid_volume + ask_volume

        # Calculate imbalance
        imbalance = 0.0
        if total_liquidity > 0:
            imbalance = (bid_volume - ask_volume) / total_liquidity

        # Count whale orders (>$100k)
        whale_bids = sum(1 for b in book.bids[:levels] if b["size"] * (book.best_bid() or 0) >= 100000)
        whale_asks = sum(1 for a in book.asks[:levels] if a["size"] * (book.best_ask() or 0) >= 100000)

        # Average depth per level
        bid_depth = bid_volume / levels if levels > 0 else 0
        ask_depth = ask_volume / levels if levels > 0 else 0

        return {
            "symbol": symbol,
            "bid_volume": bid_volume,
            "ask_volume": ask_volume,
            "imbalance_ratio": imbalance,
            "total_liquidity": total_liquidity,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "whale_bids": whale_bids,
            "whale_asks": whale_asks,
            "spread": book.spread(),
            "mid_price": (book.best_bid() + book.best_ask()) / 2 if book.best_bid() and book.best_ask() else None,
            "timestamp": datetime.utcnow()
        }

    def get_volume_metrics(
        self,
        symbol: str,
        seconds: int = 300
    ) -> Optional[Dict[str, Any]]:
        """
        Calculate volume-based metrics for signal analysis.

        Args:
            symbol: Coin symbol (BTC, ETH, etc.)
            seconds: Lookback window in seconds (default: 5 minutes)

        Returns:
            Dict with {
                'total_volume': float (USD),
                'buy_volume': float (USD),
                'sell_volume': float (USD),
                'buy_sell_ratio': float,
                'trade_count': int,
                'avg_trade_size': float (USD),
                'volume_velocity': float (USD per second),
                'whale_volume': float (USD from trades >$100k),
                'whale_trade_count': int
            }
            or None if no trades available
        """
        trades = self.get_recent_trades(symbol, seconds)

        if not trades:
            return None

        total_volume = 0.0
        buy_volume = 0.0
        sell_volume = 0.0
        whale_volume = 0.0
        whale_trade_count = 0

        for trade in trades:
            usd_value = trade.price * trade.size
            total_volume += usd_value

            if trade.side == "buy":
                buy_volume += usd_value
            else:
                sell_volume += usd_value

            # Whale detection
            if usd_value >= 100000:
                whale_volume += usd_value
                whale_trade_count += 1

        # Calculate metrics
        trade_count = len(trades)
        buy_sell_ratio = buy_volume / sell_volume if sell_volume > 0 else 0
        avg_trade_size = total_volume / trade_count if trade_count > 0 else 0
        volume_velocity = total_volume / seconds if seconds > 0 else 0

        return {
            "symbol": symbol,
            "total_volume": total_volume,
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "buy_sell_ratio": buy_sell_ratio,
            "trade_count": trade_count,
            "avg_trade_size": avg_trade_size,
            "volume_velocity": volume_velocity,
            "whale_volume": whale_volume,
            "whale_trade_count": whale_trade_count,
            "timestamp": datetime.utcnow(),
            "lookback_seconds": seconds
        }

    # ==================== STATUS & STATS ====================

    def get_status(self) -> Dict[str, Any]:
        """Get pipeline health status."""
        uptime = None
        if self._start_time:
            uptime = (datetime.utcnow() - self._start_time).total_seconds()

        return {
            "running": self._running,
            "uptime_seconds": uptime,
            "connectors": {
                name: {
                    "connected": conn.connected,
                    "message_count": getattr(conn, 'message_count', 0),
                }
                for name, conn in self._connectors.items()
            },
            "buffer_sizes": {
                dt.name: len(self._buffers[dt])
                for dt in DataType
                if dt in self._buffers
            },
            "stats": self._stats.copy(),
        }

    def get_stats_summary(self) -> str:
        """Get human-readable stats summary."""
        status = self.get_status()

        summary = "\n" + "="*50 + "\n"
        summary += "📊 UNIFIED PIPELINE STATUS\n"
        summary += "="*50 + "\n"

        summary += f"Running: {'✅' if status['running'] else '❌'}\n"
        if status['uptime_seconds']:
            mins = status['uptime_seconds'] / 60
            summary += f"Uptime: {mins:.1f} minutes\n"

        summary += "\n📡 Connectors:\n"
        for name, info in status['connectors'].items():
            status_icon = "🟢" if info['connected'] else "🔴"
            summary += f"  {status_icon} {name}: {info['message_count']} messages\n"

        summary += "\n📦 Buffers:\n"
        for name, size in status['buffer_sizes'].items():
            summary += f"  {name}: {size} items\n"

        stats = status['stats']
        summary += f"\n💰 Liquidations:\n"
        summary += f"  Total: {stats['liquidations_received']}\n"
        summary += f"  Long Vol: ${stats['long_liq_volume']:,.0f}\n"
        summary += f"  Short Vol: ${stats['short_liq_volume']:,.0f}\n"

        if stats['short_liq_volume'] > 0:
            ratio = stats['long_liq_volume'] / stats['short_liq_volume']
            sentiment = "BEARISH 🔴" if ratio > 1.5 else "BULLISH 🟢" if ratio < 0.67 else "NEUTRAL 🟡"
            summary += f"  Ratio: {ratio:.2f} ({sentiment})\n"

        summary += "="*50 + "\n"
        return summary


# Quick test
if __name__ == "__main__":
    async def test_pipeline():
        cprint("\n🌙 Testing Unified Data Pipeline...\n", "cyan")

        pipeline = UnifiedDataPipeline()

        try:
            await pipeline.start()

            # Run for 60 seconds
            for i in range(12):
                await asyncio.sleep(5)

                # Print stats every 5 seconds
                print(pipeline.get_stats_summary())

                # Print liquidation ratio
                ratio = pipeline.get_liquidation_ratio(seconds=60)
                volume = pipeline.get_liquidation_volume(seconds=60)
                cprint(
                    f"[SIGNAL] 60s Ratio: {ratio:.2f} | "
                    f"Long: ${volume['long']:,.0f} | Short: ${volume['short']:,.0f}",
                    "yellow"
                )

        except KeyboardInterrupt:
            cprint("\n[STOPPED]", "yellow")
        finally:
            await pipeline.stop()

    asyncio.run(test_pipeline())
