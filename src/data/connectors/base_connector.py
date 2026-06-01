"""
🌙 TradeHive's Base Connector Class
Abstract base class for all exchange data connectors

Built with love by TradeHive 🚀
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import websockets
from termcolor import cprint

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataType(Enum):
    """Types of market data"""
    ORDER_BOOK = "order_book"
    LIQUIDATION = "liquidation"
    TRADE = "trade"
    FUNDING_RATE = "funding_rate"
    PRICE = "price"
    OPEN_INTEREST = "open_interest"


@dataclass
class OrderBookUpdate:
    """Standardized order book update"""
    exchange: str
    symbol: str
    timestamp: datetime
    bids: List[Dict[str, float]]  # [{"price": 100.0, "size": 1.5}, ...]
    asks: List[Dict[str, float]]
    sequence: Optional[int] = None

    def best_bid(self) -> Optional[float]:
        return self.bids[0]["price"] if self.bids else None

    def best_ask(self) -> Optional[float]:
        return self.asks[0]["price"] if self.asks else None

    def spread(self) -> Optional[float]:
        if self.best_bid() and self.best_ask():
            return self.best_ask() - self.best_bid()
        return None


@dataclass
class LiquidationEvent:
    """Standardized liquidation event"""
    exchange: str
    symbol: str
    timestamp: datetime
    side: str  # "long" or "short"
    size: float  # Position size in USD
    price: float  # Liquidation price
    bankruptcy_price: Optional[float] = None

    def __str__(self):
        marker = "[LONG-LIQ]" if self.side == "long" else "[SHORT-LIQ]"
        return f"{marker} {self.exchange} {self.symbol} {self.side.upper()} liquidated: ${self.size:,.2f} @ {self.price}"


@dataclass
class TradeEvent:
    """Standardized trade event"""
    exchange: str
    symbol: str
    timestamp: datetime
    side: str  # "buy" or "sell"
    price: float
    size: float
    trade_id: Optional[str] = None


@dataclass
class FundingRateEvent:
    """Standardized funding rate event"""
    exchange: str
    symbol: str
    timestamp: datetime
    rate: float  # Funding rate as decimal (0.0001 = 0.01%)
    next_funding_time: Optional[datetime] = None


class BaseConnector(ABC):
    """
    Abstract base class for exchange data connectors

    All connectors must implement:
    - connect(): Establish WebSocket connection
    - disconnect(): Close connection gracefully
    - subscribe(): Subscribe to specific data feeds
    - _handle_message(): Process incoming messages
    """

    def __init__(self, name: str):
        self.name = name
        self.ws = None
        self.connected = False
        self.running = False
        self.callbacks: Dict[DataType, List[Callable]] = {dt: [] for dt in DataType}
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 1  # seconds
        self._tasks: List[asyncio.Task] = []

        cprint(f"[INIT] TradeHive's {self.name} Connector initialized", "cyan")

    @property
    @abstractmethod
    def websocket_url(self) -> str:
        """WebSocket URL for the exchange"""
        pass

    @abstractmethod
    async def subscribe(self, symbols: List[str], data_types: List[DataType]) -> None:
        """Subscribe to data feeds for given symbols"""
        pass

    @abstractmethod
    async def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message"""
        pass

    def on_data(self, data_type: DataType, callback: Callable) -> None:
        """Register callback for specific data type"""
        self.callbacks[data_type].append(callback)
        cprint(f"[OK] Registered callback for {data_type.value} on {self.name}", "green")

    async def _emit(self, data_type: DataType, data: Any) -> None:
        """Emit data to registered callbacks"""
        for callback in self.callbacks[data_type]:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                logger.error(f"Error in callback for {data_type.value}: {e}")

    async def connect(self) -> None:
        """Establish WebSocket connection"""
        try:
            cprint(f"[CONNECTING] {self.name}...", "yellow")
            self.ws = await websockets.connect(
                self.websocket_url,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=5
            )
            self.connected = True
            self.reconnect_attempts = 0
            cprint(f"[CONNECTED] {self.name}!", "green")
        except Exception as e:
            cprint(f"[ERROR] Failed to connect to {self.name}: {e}", "red")
            raise

    async def disconnect(self) -> None:
        """Close WebSocket connection gracefully"""
        self.running = False
        if self.ws:
            await self.ws.close()
            self.connected = False
            cprint(f"[DISCONNECTED] {self.name}", "yellow")

        # Cancel all running tasks
        for task in self._tasks:
            task.cancel()

    async def _reconnect(self) -> None:
        """Attempt to reconnect with exponential backoff"""
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            delay = min(self.reconnect_delay * (2 ** self.reconnect_attempts), 60)
            cprint(f"[RECONNECTING] {self.name} in {delay}s (attempt {self.reconnect_attempts})...", "yellow")
            await asyncio.sleep(delay)

            try:
                await self.connect()
                return
            except Exception as e:
                cprint(f"[ERROR] Reconnection failed: {e}", "red")

        cprint(f"[FATAL] Max reconnection attempts reached for {self.name}", "red")

    async def _listen(self) -> None:
        """Main listening loop for WebSocket messages"""
        while self.running:
            try:
                if not self.connected:
                    await self._reconnect()
                    if not self.connected:
                        break

                message = await self.ws.recv()
                await self._handle_message(message)

            except websockets.ConnectionClosed:
                cprint(f"[WARN] Connection closed to {self.name}", "yellow")
                self.connected = False
                if self.running:
                    await self._reconnect()
            except Exception as e:
                logger.error(f"Error in {self.name} listener: {e}")
                await asyncio.sleep(1)

    async def start(self, symbols: List[str], data_types: List[DataType]) -> None:
        """Start the connector"""
        self.running = True
        await self.connect()
        await self.subscribe(symbols, data_types)

        # Start listening in background
        listen_task = asyncio.create_task(self._listen())
        self._tasks.append(listen_task)

    async def run_forever(self, symbols: List[str], data_types: List[DataType]) -> None:
        """Run the connector indefinitely"""
        await self.start(symbols, data_types)
        try:
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            cprint(f"\n[STOPPING] {self.name}...", "yellow")
        finally:
            await self.disconnect()
