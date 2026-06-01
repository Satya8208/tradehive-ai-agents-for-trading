"""
TradeHive's Whale Signal Agent
Analyzes order book data to detect whale activity

Weight: 40% of final signal
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum
from collections import deque


class Signal(Enum):
    """Trading signal types"""
    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"


@dataclass
class WhaleSignal:
    """Signal output from the WhaleAgent"""
    signal: Signal
    confidence: float  # 0-100
    timestamp: datetime
    metrics: Dict


class WhaleAgent:
    """
    Analyzes order book data to detect whale activity and
    bid/ask imbalances that indicate directional intent.

    Logic:
    - Large bids appearing = Whales buying = BULLISH
    - Large asks appearing = Whales selling = BEARISH
    - Bid/ask imbalance indicates directional pressure

    Weight in final signal: 40%
    """

    def __init__(
        self,
        whale_threshold_usd: float = 100_000,  # $100k+ = whale order
        mega_whale_threshold: float = 500_000,  # $500k+ = mega whale
        imbalance_threshold: float = 1.5,       # 1.5x imbalance = signal
    ):
        self.whale_threshold = whale_threshold_usd
        self.mega_whale_threshold = mega_whale_threshold
        self.imbalance_threshold = imbalance_threshold

        # Store order book snapshots
        self.order_books: Dict[str, Dict] = {}

        # Track whale orders over time
        self.whale_orders: deque = deque(maxlen=1000)

        print(f"[WhaleAgent] Initialized | Whale: ${whale_threshold_usd:,.0f} | Mega: ${mega_whale_threshold:,.0f}")

    def update_order_book(
        self,
        symbol: str,
        bids: List[Dict],  # [{"price": 87000, "size": 1.5}, ...]
        asks: List[Dict],
        timestamp: datetime = None
    ) -> None:
        """Update order book for a symbol"""
        if timestamp is None:
            timestamp = datetime.utcnow()

        # Calculate metrics
        bid_volume = sum(b["price"] * b["size"] for b in bids[:20])  # Top 20 levels
        ask_volume = sum(a["price"] * a["size"] for a in asks[:20])

        # Detect whale orders
        whale_bids = [b for b in bids if b["price"] * b["size"] >= self.whale_threshold]
        whale_asks = [a for a in asks if a["price"] * a["size"] >= self.whale_threshold]

        # Track whale orders
        for bid in whale_bids:
            size_usd = bid["price"] * bid["size"]
            self.whale_orders.append({
                "type": "bid",
                "symbol": symbol,
                "price": bid["price"],
                "size_usd": size_usd,
                "timestamp": timestamp
            })

        for ask in whale_asks:
            size_usd = ask["price"] * ask["size"]
            self.whale_orders.append({
                "type": "ask",
                "symbol": symbol,
                "price": ask["price"],
                "size_usd": size_usd,
                "timestamp": timestamp
            })

        # Store current state
        self.order_books[symbol] = {
            "bids": bids,
            "asks": asks,
            "bid_volume": bid_volume,
            "ask_volume": ask_volume,
            "whale_bids": whale_bids,
            "whale_asks": whale_asks,
            "timestamp": timestamp,
            "best_bid": bids[0]["price"] if bids else 0,
            "best_ask": asks[0]["price"] if asks else 0
        }

    def get_metrics(self) -> Dict:
        """Calculate current whale activity metrics"""
        # Aggregate across all symbols
        total_bid_vol = sum(ob["bid_volume"] for ob in self.order_books.values())
        total_ask_vol = sum(ob["ask_volume"] for ob in self.order_books.values())

        # Count current whale orders
        whale_bid_count = sum(len(ob["whale_bids"]) for ob in self.order_books.values())
        whale_ask_count = sum(len(ob["whale_asks"]) for ob in self.order_books.values())

        whale_bid_vol = sum(
            sum(b["price"] * b["size"] for b in ob["whale_bids"])
            for ob in self.order_books.values()
        )
        whale_ask_vol = sum(
            sum(a["price"] * a["size"] for a in ob["whale_asks"])
            for ob in self.order_books.values()
        )

        # Calculate imbalance ratio
        if total_ask_vol > 0:
            imbalance_ratio = total_bid_vol / total_ask_vol
        else:
            imbalance_ratio = 1.0

        # Recent whale activity (last 5 min)
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        recent_whales = [w for w in self.whale_orders if w["timestamp"] > cutoff]

        recent_bid_vol = sum(w["size_usd"] for w in recent_whales if w["type"] == "bid")
        recent_ask_vol = sum(w["size_usd"] for w in recent_whales if w["type"] == "ask")

        return {
            "total_bid_volume": total_bid_vol,
            "total_ask_volume": total_ask_vol,
            "imbalance_ratio": imbalance_ratio,
            "whale_bid_count": whale_bid_count,
            "whale_ask_count": whale_ask_count,
            "whale_bid_volume": whale_bid_vol,
            "whale_ask_volume": whale_ask_vol,
            "recent_whale_bid_vol": recent_bid_vol,
            "recent_whale_ask_vol": recent_ask_vol,
            "symbols_tracked": len(self.order_books)
        }

    def generate_signal(self) -> WhaleSignal:
        """
        Generate a trading signal based on order book analysis
        """
        metrics = self.get_metrics()

        # Not enough data
        if metrics["symbols_tracked"] == 0:
            return WhaleSignal(
                signal=Signal.NEUTRAL,
                confidence=0,
                timestamp=datetime.utcnow(),
                metrics=metrics
            )

        imbalance = metrics["imbalance_ratio"]
        whale_bid_vol = metrics["recent_whale_bid_vol"]
        whale_ask_vol = metrics["recent_whale_ask_vol"]

        # Start with neutral
        signal = Signal.NEUTRAL
        confidence = 20

        # Check imbalance
        if imbalance >= 2.0:
            signal = Signal.STRONG_BULLISH
            confidence = 60 + min(30, (imbalance - 2) * 10)
        elif imbalance >= self.imbalance_threshold:
            signal = Signal.BULLISH
            confidence = 40 + (imbalance - 1.5) * 30
        elif imbalance <= 0.5:
            signal = Signal.STRONG_BEARISH
            confidence = 60 + min(30, (1/imbalance - 2) * 10)
        elif imbalance <= 0.67:
            signal = Signal.BEARISH
            confidence = 40 + (1/imbalance - 1.5) * 30

        # Boost from whale activity
        if whale_bid_vol > whale_ask_vol * 2:
            if signal in [Signal.NEUTRAL, Signal.BULLISH]:
                signal = Signal.BULLISH if signal == Signal.NEUTRAL else Signal.STRONG_BULLISH
                confidence = min(100, confidence + 15)
        elif whale_ask_vol > whale_bid_vol * 2:
            if signal in [Signal.NEUTRAL, Signal.BEARISH]:
                signal = Signal.BEARISH if signal == Signal.NEUTRAL else Signal.STRONG_BEARISH
                confidence = min(100, confidence + 15)

        # Mega whale detection
        mega_whales = [w for w in self.whale_orders
                      if w["size_usd"] >= self.mega_whale_threshold
                      and w["timestamp"] > datetime.utcnow() - timedelta(minutes=5)]

        if mega_whales:
            mega_bids = sum(1 for w in mega_whales if w["type"] == "bid")
            mega_asks = sum(1 for w in mega_whales if w["type"] == "ask")

            if mega_bids > mega_asks:
                confidence = min(100, confidence + 20)
                if signal == Signal.BULLISH:
                    signal = Signal.STRONG_BULLISH
            elif mega_asks > mega_bids:
                confidence = min(100, confidence + 20)
                if signal == Signal.BEARISH:
                    signal = Signal.STRONG_BEARISH

        return WhaleSignal(
            signal=signal,
            confidence=min(100, max(0, confidence)),
            timestamp=datetime.utcnow(),
            metrics=metrics
        )

    def get_signal_score(self) -> Tuple[float, Dict]:
        """
        Get normalized score for signal aggregation

        Returns:
            score: -100 to +100 (negative = bearish, positive = bullish)
            metrics: detailed metrics
        """
        sig = self.generate_signal()

        signal_scores = {
            Signal.STRONG_BULLISH: 80,
            Signal.BULLISH: 40,
            Signal.NEUTRAL: 0,
            Signal.BEARISH: -40,
            Signal.STRONG_BEARISH: -80
        }

        base_score = signal_scores[sig.signal]
        final_score = base_score * (sig.confidence / 100)

        return final_score, {
            "signal": sig.signal.value,
            "confidence": sig.confidence,
            "raw_score": base_score,
            "final_score": final_score,
            **sig.metrics
        }

    def print_status(self) -> None:
        """Print current status"""
        metrics = self.get_metrics()
        sig = self.generate_signal()

        print("\n" + "="*60)
        print("[WHALE AGENT STATUS]")
        print("="*60)
        print(f"  Symbols Tracked: {metrics['symbols_tracked']}")
        print(f"  Bid Volume: ${metrics['total_bid_volume']:,.0f}")
        print(f"  Ask Volume: ${metrics['total_ask_volume']:,.0f}")
        print(f"  Imbalance Ratio: {metrics['imbalance_ratio']:.2f}")
        print(f"  Whale Bids: {metrics['whale_bid_count']} (${metrics['whale_bid_volume']:,.0f})")
        print(f"  Whale Asks: {metrics['whale_ask_count']} (${metrics['whale_ask_volume']:,.0f})")
        print("-"*60)
        print(f"  SIGNAL: {sig.signal.value}")
        print(f"  CONFIDENCE: {sig.confidence:.0f}%")
        print("="*60 + "\n")


# =============================================================================
# Standalone test
# =============================================================================
if __name__ == "__main__":
    import random

    agent = WhaleAgent()

    # Simulate order book with bid-heavy whale activity
    print("\nSimulating whale-heavy order book...")

    bids = [
        {"price": 87000 - i*10, "size": random.uniform(0.5, 10)}
        for i in range(50)
    ]
    bids[0]["size"] = 15  # Whale bid at top
    bids[3]["size"] = 20  # Another whale

    asks = [
        {"price": 87010 + i*10, "size": random.uniform(0.5, 5)}
        for i in range(50)
    ]

    agent.update_order_book("BTC", bids, asks)
    agent.print_status()

    score, metrics = agent.get_signal_score()
    print(f"Final Score: {score:.2f}")
