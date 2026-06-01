"""
TradeHive's Liquidation Signal Agent
Analyzes liquidation data to generate trading signals

Weight: 60% of final signal
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum
from collections import deque


class Signal(Enum):
    """Trading signal types"""
    STRONG_BULLISH = "STRONG_BULLISH"   # Heavy short liquidations
    BULLISH = "BULLISH"                  # More shorts than longs liquidated
    NEUTRAL = "NEUTRAL"                  # Balanced or low activity
    BEARISH = "BEARISH"                  # More longs than shorts liquidated
    STRONG_BEARISH = "STRONG_BEARISH"   # Heavy long liquidations


@dataclass
class LiquidationSignal:
    """Signal output from the LiquidationAgent"""
    signal: Signal
    confidence: float  # 0-100
    timestamp: datetime
    metrics: Dict  # Supporting data


class LiquidationAgent:
    """
    Analyzes liquidation data from multiple exchanges to generate
    directional signals for crypto markets.

    Logic:
    - Heavy long liquidations = BEARISH (price dropping, longs getting rekt)
    - Heavy short liquidations = BULLISH (price rising, shorts getting rekt)

    Weight in final signal: 60%
    """

    def __init__(
        self,
        rolling_window_minutes: int = 5,
        cascade_threshold_usd: float = 5_000_000,  # $5M in window = cascade
        min_volume_threshold: float = 100_000,      # Min $100k to generate signal
    ):
        self.rolling_window = rolling_window_minutes
        self.cascade_threshold = cascade_threshold_usd
        self.min_volume = min_volume_threshold

        # Rolling buffers for each exchange
        self.liquidations: deque = deque(maxlen=10000)

        # Metrics tracking
        self.total_long_liqs = 0.0
        self.total_short_liqs = 0.0

        print(f"[LiquidationAgent] Initialized | Window: {rolling_window_minutes}min | Cascade: ${cascade_threshold_usd:,.0f}")

    def add_liquidation(
        self,
        exchange: str,
        symbol: str,
        side: str,  # "long" or "short"
        size_usd: float,
        price: float,
        timestamp: datetime = None
    ) -> None:
        """Add a liquidation event to the buffer"""
        if timestamp is None:
            timestamp = datetime.utcnow()

        liq = {
            "exchange": exchange,
            "symbol": symbol,
            "side": side.lower(),
            "size": size_usd,
            "price": price,
            "timestamp": timestamp
        }

        self.liquidations.append(liq)

        # Track totals
        if side.lower() == "long":
            self.total_long_liqs += size_usd
        else:
            self.total_short_liqs += size_usd

    def get_rolling_metrics(self) -> Dict:
        """Calculate metrics for the rolling window"""
        cutoff = datetime.utcnow() - timedelta(minutes=self.rolling_window)

        recent = [liq for liq in self.liquidations if liq["timestamp"] > cutoff]

        long_volume = sum(liq["size"] for liq in recent if liq["side"] == "long")
        short_volume = sum(liq["size"] for liq in recent if liq["side"] == "short")
        total_volume = long_volume + short_volume

        # Calculate ratio (protect against division by zero)
        if long_volume == 0 and short_volume == 0:
            ratio = 1.0
        elif long_volume == 0:
            ratio = 0.01  # Very bullish (all shorts liquidated)
        elif short_volume == 0:
            ratio = 100.0  # Very bearish (all longs liquidated)
        else:
            ratio = long_volume / short_volume

        # Count events
        long_count = sum(1 for liq in recent if liq["side"] == "long")
        short_count = sum(1 for liq in recent if liq["side"] == "short")

        # Calculate velocity (liquidations per minute)
        if recent:
            time_span = (max(liq["timestamp"] for liq in recent) -
                        min(liq["timestamp"] for liq in recent)).total_seconds() / 60
            velocity = len(recent) / max(time_span, 1)
        else:
            velocity = 0

        return {
            "window_minutes": self.rolling_window,
            "long_volume": long_volume,
            "short_volume": short_volume,
            "total_volume": total_volume,
            "long_short_ratio": ratio,
            "long_count": long_count,
            "short_count": short_count,
            "total_count": len(recent),
            "velocity_per_min": velocity
        }

    def generate_signal(self) -> LiquidationSignal:
        """
        Generate a trading signal based on current liquidation data

        Returns LiquidationSignal with:
        - signal: STRONG_BULLISH to STRONG_BEARISH
        - confidence: 0-100
        - metrics: supporting data
        """
        metrics = self.get_rolling_metrics()

        total_volume = metrics["total_volume"]
        ratio = metrics["long_short_ratio"]

        # Not enough data
        if total_volume < self.min_volume:
            return LiquidationSignal(
                signal=Signal.NEUTRAL,
                confidence=0,
                timestamp=datetime.utcnow(),
                metrics=metrics
            )

        # Determine signal based on ratio
        # ratio > 1 = more longs liquidated = bearish
        # ratio < 1 = more shorts liquidated = bullish

        if ratio >= 3.0:
            # Heavy long liquidations - very bearish
            signal = Signal.STRONG_BEARISH
            confidence = min(90, 50 + (ratio - 3) * 10)
        elif ratio >= 1.5:
            # More longs than shorts - bearish
            signal = Signal.BEARISH
            confidence = 30 + (ratio - 1.5) * 20
        elif ratio <= 0.33:
            # Heavy short liquidations - very bullish
            signal = Signal.STRONG_BULLISH
            confidence = min(90, 50 + (1/ratio - 3) * 10)
        elif ratio <= 0.67:
            # More shorts than longs - bullish
            signal = Signal.BULLISH
            confidence = 30 + (1/ratio - 1.5) * 20
        else:
            # Balanced - neutral
            signal = Signal.NEUTRAL
            confidence = 20

        # Boost confidence if cascade detected
        if total_volume >= self.cascade_threshold:
            confidence = min(100, confidence + 20)
            # Upgrade signal strength
            if signal == Signal.BULLISH:
                signal = Signal.STRONG_BULLISH
            elif signal == Signal.BEARISH:
                signal = Signal.STRONG_BEARISH

        return LiquidationSignal(
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

        # Map signal to base score
        signal_scores = {
            Signal.STRONG_BULLISH: 80,
            Signal.BULLISH: 40,
            Signal.NEUTRAL: 0,
            Signal.BEARISH: -40,
            Signal.STRONG_BEARISH: -80
        }

        base_score = signal_scores[sig.signal]

        # Scale by confidence
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
        metrics = self.get_rolling_metrics()
        sig = self.generate_signal()

        print("\n" + "="*60)
        print("[LIQUIDATION AGENT STATUS]")
        print("="*60)
        print(f"  Window: {self.rolling_window} minutes")
        print(f"  Total Events: {metrics['total_count']}")
        print(f"  Long Liqs: ${metrics['long_volume']:,.0f} ({metrics['long_count']} events)")
        print(f"  Short Liqs: ${metrics['short_volume']:,.0f} ({metrics['short_count']} events)")
        print(f"  Long/Short Ratio: {metrics['long_short_ratio']:.2f}")
        print(f"  Velocity: {metrics['velocity_per_min']:.1f}/min")
        print("-"*60)
        print(f"  SIGNAL: {sig.signal.value}")
        print(f"  CONFIDENCE: {sig.confidence:.0f}%")
        print("="*60 + "\n")


# =============================================================================
# Standalone test
# =============================================================================
if __name__ == "__main__":
    import random

    agent = LiquidationAgent()

    # Simulate some liquidations
    print("\nSimulating liquidation events...")

    for i in range(50):
        side = random.choice(["long", "long", "short"])  # Bias to longs
        size = random.uniform(5000, 500000)
        agent.add_liquidation(
            exchange=random.choice(["Binance", "Bybit", "Hyperliquid"]),
            symbol="BTCUSDT",
            side=side,
            size_usd=size,
            price=87000 + random.uniform(-500, 500)
        )

    agent.print_status()
    score, metrics = agent.get_signal_score()
    print(f"Final Score: {score:.2f}")
