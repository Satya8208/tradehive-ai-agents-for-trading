"""
Polymarket Connector for Crypto Polymarket Agent

WebSocket connector for Polymarket CLOB (Central Limit Order Book) data.
Provides real-time order book updates, trade data, and market information.

Features:
- WebSocket connection to Polymarket data stream
- Order book snapshots and updates
- Trade execution data
- Market metadata and pricing

Built with love by TradeHive
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from termcolor import cprint
import aiohttp

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.data.connectors.base_connector import (
    BaseConnector,
    DataType,
    OrderBookUpdate,
    TradeEvent,
)


@dataclass
class PolymarketMarket:
    """Polymarket market data structure"""

    market_id: str
    question: str
    description: str
    end_date: datetime
    yes_token_id: str
    no_token_id: str
    yes_price: float
    no_price: float
    volume_24h: float
    liquidity: float
    best_bid: float
    best_ask: float
    spread: float


@dataclass
class PolymarketOrderBook:
    """Polymarket order book snapshot"""

    token_id: str
    bids: List[tuple[float, float]]  # (price, size)
    asks: List[tuple[float, float]]  # (price, size)
    timestamp: datetime
    spread: float
    mid_price: float


class PolymarketConnector(BaseConnector):
    """
    Polymarket WebSocket connector for real-time market data.

    Connects to Polymarket's WebSocket API for:
    - Order book updates
    - Trade execution data
    - Market metadata
    - Price feeds
    """

    def __init__(self):
        super().__init__()
        self.name = "polymarket"
        self.ws_url = "wss://ws-data.polymarket.com"
        self.rest_url = "https://clob.polymarket.com"
        self.gamma_url = "https://gamma-api.polymarket.com"

        self.ws_session: Optional[aiohttp.ClientSession] = None
        self.ws_connection: Optional[aiohttp.ClientWebSocketResponse] = None
        self.connection_task: Optional[asyncio.Task] = None

        self.markets: Dict[str, PolymarketMarket] = {}
        self.order_books: Dict[str, PolymarketOrderBook] = {}

        self.subscriptions: set = set()
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 1.0

        # Data handlers
        self.handlers: Dict[str, List[Callable]] = {
            "orderbook": [],
            "trades": [],
            "markets": [],
        }

        self._running = False

    async def connect(self) -> bool:
        """Establish WebSocket connection to Polymarket"""
        try:
            cprint(f"[POLYMARKET] Connecting to {self.ws_url}...", "cyan")

            self.ws_session = aiohttp.ClientSession()
            self.ws_connection = await self.ws_session.ws_connect(
                self.ws_url,
                heartbeat=30,
                autoping=True,
            )

            self._running = True
            self.reconnect_attempts = 0

            # Start message handling task
            self.connection_task = asyncio.create_task(self._handle_messages())

            cprint("[POLYMARKET] WebSocket connected successfully", "green")
            return True

        except Exception as e:
            cprint(f"[POLYMARKET] Connection failed: {e}", "red")
            await self.disconnect()
            return False

    async def disconnect(self) -> None:
        """Disconnect from WebSocket"""
        cprint("[POLYMARKET] Disconnecting...", "yellow")

        self._running = False

        if self.connection_task:
            self.connection_task.cancel()
            try:
                await self.connection_task
            except asyncio.CancelledError:
                pass

        if self.ws_connection:
            await self.ws_connection.close()

        if self.ws_session:
            await self.ws_session.close()

        cprint("[POLYMARKET] Disconnected", "green")

    async def subscribe_market(self, market_id: str, token_id: str) -> None:
        """Subscribe to specific market updates"""
        subscription = {
            "type": "subscribe",
            "channel": "orderbook",
            "market": market_id,
            "token": token_id,
        }

        if self.ws_connection:
            await self.ws_connection.send_str(json.dumps(subscription))
            self.subscriptions.add(f"{market_id}:{token_id}")
            cprint(f"[POLYMARKET] Subscribed to {market_id}:{token_id}", "white")

    async def _handle_messages(self) -> None:
        """Handle incoming WebSocket messages"""
        try:
            while self._running and self.ws_connection:
                msg = await self.ws_connection.receive()

                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._process_message(json.loads(msg.data))

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    cprint(f"[POLYMARKET] WebSocket error: {msg.data}", "red")
                    break

                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    cprint("[POLYMARKET] WebSocket closed", "yellow")
                    break

        except Exception as e:
            cprint(f"[POLYMARKET] Message handling error: {e}", "red")
        finally:
            if self._running:
                await self._handle_reconnection()

    async def _process_message(self, message: Dict[str, Any]) -> None:
        """Process incoming message"""
        try:
            msg_type = message.get("type")

            if msg_type == "orderbook":
                await self._process_orderbook(message)
            elif msg_type == "trade":
                await self._process_trade(message)
            elif msg_type == "market":
                await self._process_market(message)
            else:
                # Unknown message type
                pass

        except Exception as e:
            cprint(f"[POLYMARKET] Error processing message: {e}", "red")

    async def _process_orderbook(self, data: Dict[str, Any]) -> None:
        """Process order book update"""
        try:
            token_id = data.get("token")
            if not token_id:
                return

            # Extract order book data
            bids = [(float(b["price"]), float(b["size"])) for b in data.get("bids", [])]
            asks = [(float(a["price"]), float(a["size"])) for a in data.get("asks", [])]

            if not bids or not asks:
                return

            # Calculate metrics
            best_bid = max(bids, key=lambda x: x[0])[0]
            best_ask = min(asks, key=lambda x: x[0])[0]
            spread = best_ask - best_bid
            mid_price = (best_bid + best_ask) / 2

            # Create order book object
            orderbook = PolymarketOrderBook(
                token_id=token_id,
                bids=bids,
                asks=asks,
                timestamp=datetime.utcnow(),
                spread=spread,
                mid_price=mid_price,
            )

            self.order_books[token_id] = orderbook

            # Convert to standard format and notify handlers
            update = OrderBookUpdate(
                symbol=self._token_to_symbol(token_id),
                best_bid=best_bid,
                best_ask=best_ask,
                spread=spread,
                timestamp=orderbook.timestamp,
            )

            await self._notify_handlers("orderbook", update)

        except Exception as e:
            cprint(f"[POLYMARKET] Error processing orderbook: {e}", "red")

    async def _process_trade(self, data: Dict[str, Any]) -> None:
        """Process trade execution"""
        try:
            trade = TradeEvent(
                symbol=self._token_to_symbol(data.get("token", "")),
                price=float(data.get("price", 0)),
                size=float(data.get("size", 0)),
                side=data.get("side", "unknown"),
                timestamp=datetime.fromisoformat(
                    data.get("timestamp", datetime.utcnow().isoformat())
                ),
            )

            await self._notify_handlers("trades", trade)

        except Exception as e:
            cprint(f"[POLYMARKET] Error processing trade: {e}", "red")

    async def _process_market(self, data: Dict[str, Any]) -> None:
        """Process market metadata"""
        try:
            market = PolymarketMarket(
                market_id=data.get("market_id", ""),
                question=data.get("question", ""),
                description=data.get("description", ""),
                end_date=datetime.fromisoformat(
                    data.get("end_date", datetime.utcnow().isoformat())
                ),
                yes_token_id=data.get("yes_token_id", ""),
                no_token_id=data.get("no_token_id", ""),
                yes_price=float(data.get("yes_price", 0)),
                no_price=float(data.get("no_price", 0)),
                volume_24h=float(data.get("volume_24h", 0)),
                liquidity=float(data.get("liquidity", 0)),
                best_bid=float(data.get("best_bid", 0)),
                best_ask=float(data.get("best_ask", 0)),
                spread=float(data.get("spread", 0)),
            )

            self.markets[market.market_id] = market

            await self._notify_handlers("markets", market)

        except Exception as e:
            cprint(f"[POLYMARKET] Error processing market: {e}", "red")

    async def _handle_reconnection(self) -> None:
        """Handle WebSocket reconnection with exponential backoff"""
        self.reconnect_attempts += 1

        if self.reconnect_attempts > self.max_reconnect_attempts:
            cprint("[POLYMARKET] Max reconnection attempts reached", "red")
            return

        delay = min(self.reconnect_delay * (2**self.reconnect_attempts), 60)
        cprint(
            f"[POLYMARKET] Reconnecting in {delay}s (attempt {self.reconnect_attempts})",
            "yellow",
        )

        await asyncio.sleep(delay)

        if await self.connect():
            # Resubscribe to markets
            for subscription in self.subscriptions:
                market_id, token_id = subscription.split(":")
                await self.subscribe_market(market_id, token_id)

    def _token_to_symbol(self, token_id: str) -> str:
        """Convert token ID to symbol (placeholder logic)"""
        # This would need to be implemented based on actual token mapping
        if "yes" in token_id.lower():
            return "BTC_YES"
        elif "no" in token_id.lower():
            return "BTC_NO"
        else:
            return "UNKNOWN"

    async def _notify_handlers(self, data_type: str, data: Any) -> None:
        """Notify registered handlers of new data"""
        handlers = self.handlers.get(data_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                cprint(f"[POLYMARKET] Handler error: {e}", "red")

    # Public API methods

    def add_handler(self, data_type: str, handler: Callable) -> None:
        """Add data handler"""
        if data_type in self.handlers:
            self.handlers[data_type].append(handler)

    def get_orderbook(self, token_id: str) -> Optional[PolymarketOrderBook]:
        """Get current order book for token"""
        return self.order_books.get(token_id)

    def get_market(self, market_id: str) -> Optional[PolymarketMarket]:
        """Get market metadata"""
        return self.markets.get(market_id)

    def get_connection_status(self) -> Dict[str, Any]:
        """Get connection status"""
        return {
            "connected": self._running and self.ws_connection is not None,
            "subscriptions": len(self.subscriptions),
            "markets": len(self.markets),
            "order_books": len(self.order_books),
            "reconnect_attempts": self.reconnect_attempts,
        }

    # Implement abstract methods from BaseConnector

    async def get_liquidation_volume(
        self, seconds: int = 300, symbol: Optional[str] = None
    ) -> Dict[str, float]:
        """Get liquidation volume (not available on Polymarket)"""
        # Return empty data - Polymarket doesn't have liquidations
        return {"long": 0.0, "short": 0.0, "total": 0.0}

    async def get_liquidation_ratio(self, seconds: int = 300) -> float:
        """Get liquidation ratio (not available on Polymarket)"""
        return 1.0  # Neutral ratio

    async def get_funding_rate(self, symbol: str = "BTC") -> float:
        """Get funding rate (not available on Polymarket)"""
        return 0.0  # No funding rates

    async def get_open_interest(self, symbol: str = "BTC") -> float:
        """Get open interest (estimated from order book liquidity)"""
        # Estimate OI from total order book liquidity
        total_liquidity = 0.0
        for orderbook in self.order_books.values():
            total_bid_size = sum(size for _, size in orderbook.bids[:10])
            total_ask_size = sum(size for _, size in orderbook.asks[:10])
            total_liquidity += (total_bid_size + total_ask_size) * orderbook.mid_price

        return total_liquidity

    async def get_recent_trades(
        self, symbol: str = "BTC", limit: int = 100
    ) -> List[TradeEvent]:
        """Get recent trades (would need to be implemented with trade history)"""
        return []  # Placeholder - implement trade history

    async def get_orderbook_snapshot(
        self, symbol: str = "BTC"
    ) -> Optional[OrderBookUpdate]:
        """Get current order book snapshot"""
        # Find relevant order book
        for token_id, orderbook in self.order_books.items():
            if symbol.lower() in token_id.lower():
                return OrderBookUpdate(
                    symbol=symbol,
                    best_bid=orderbook.bids[0][0] if orderbook.bids else 0.0,
                    best_ask=orderbook.asks[0][0] if orderbook.asks else 0.0,
                    spread=orderbook.spread,
                    timestamp=orderbook.timestamp,
                )

        return None
