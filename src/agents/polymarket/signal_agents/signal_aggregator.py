"""
TradeHive's Signal Aggregator
Combines signals from LiquidationAgent and WhaleAgent

Weights:
- LiquidationAgent: 60%
- WhaleAgent: 40%
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple
from enum import Enum

from .liquidation_agent import LiquidationAgent
from .whale_agent import WhaleAgent


class TradingDecision(Enum):
    """Final trading decision"""
    STRONG_BUY_YES = "STRONG_BUY_YES"   # Very bullish - buy YES shares
    BUY_YES = "BUY_YES"                  # Bullish - buy YES shares
    HOLD = "HOLD"                        # No clear edge
    BUY_NO = "BUY_NO"                    # Bearish - buy NO shares
    STRONG_BUY_NO = "STRONG_BUY_NO"     # Very bearish - buy NO shares


@dataclass
class AggregatedSignal:
    """Final aggregated signal for trading"""
    decision: TradingDecision
    confidence: float           # 0-100
    score: float               # -100 to +100
    timestamp: datetime

    # Component details
    liquidation_score: float
    whale_score: float

    # Metrics from each agent
    liquidation_metrics: Dict
    whale_metrics: Dict


class SignalAggregator:
    """
    Combines signals from multiple agents with configurable weights
    to produce a final trading decision.

    Weights:
    - LiquidationAgent: 60%
    - WhaleAgent: 40%
    """

    # Agent weights (must sum to 1.0)
    LIQUIDATION_WEIGHT = 0.60
    WHALE_WEIGHT = 0.40

    # Decision thresholds
    STRONG_THRESHOLD = 50   # Score > 50 = strong signal
    SIGNAL_THRESHOLD = 25   # Score > 25 = regular signal

    def __init__(self):
        """Initialize with both signal agents"""
        self.liquidation_agent = LiquidationAgent()
        self.whale_agent = WhaleAgent()

        print("[SignalAggregator] Initialized")
        print(f"  Liquidation Weight: {self.LIQUIDATION_WEIGHT*100:.0f}%")
        print(f"  Whale Weight: {self.WHALE_WEIGHT*100:.0f}%")

    # =========================================================================
    # Data input methods - pass data to appropriate agents
    # =========================================================================

    def add_liquidation(
        self,
        exchange: str,
        symbol: str,
        side: str,
        size_usd: float,
        price: float,
        timestamp: datetime = None
    ) -> None:
        """Forward liquidation data to LiquidationAgent"""
        self.liquidation_agent.add_liquidation(
            exchange=exchange,
            symbol=symbol,
            side=side,
            size_usd=size_usd,
            price=price,
            timestamp=timestamp
        )

    def update_order_book(
        self,
        symbol: str,
        bids: list,
        asks: list,
        timestamp: datetime = None
    ) -> None:
        """Forward order book data to WhaleAgent"""
        self.whale_agent.update_order_book(
            symbol=symbol,
            bids=bids,
            asks=asks,
            timestamp=timestamp
        )

    # =========================================================================
    # Signal generation
    # =========================================================================

    def get_aggregated_signal(self) -> AggregatedSignal:
        """
        Combine all agent signals into final trading decision

        Returns:
            AggregatedSignal with decision, confidence, and metrics
        """
        # Get scores from each agent
        liq_score, liq_metrics = self.liquidation_agent.get_signal_score()
        whale_score, whale_metrics = self.whale_agent.get_signal_score()

        # Apply weights
        weighted_liq = liq_score * self.LIQUIDATION_WEIGHT
        weighted_whale = whale_score * self.WHALE_WEIGHT

        # Final combined score (-100 to +100)
        final_score = weighted_liq + weighted_whale

        # Determine decision based on score
        if final_score >= self.STRONG_THRESHOLD:
            decision = TradingDecision.STRONG_BUY_YES
        elif final_score >= self.SIGNAL_THRESHOLD:
            decision = TradingDecision.BUY_YES
        elif final_score <= -self.STRONG_THRESHOLD:
            decision = TradingDecision.STRONG_BUY_NO
        elif final_score <= -self.SIGNAL_THRESHOLD:
            decision = TradingDecision.BUY_NO
        else:
            decision = TradingDecision.HOLD

        # Calculate confidence based on agreement and magnitude
        # Higher confidence when both agents agree
        same_direction = (liq_score > 0 and whale_score > 0) or (liq_score < 0 and whale_score < 0)

        base_confidence = abs(final_score)
        if same_direction:
            confidence = min(100, base_confidence + 15)
        else:
            confidence = max(0, base_confidence - 10)

        return AggregatedSignal(
            decision=decision,
            confidence=confidence,
            score=final_score,
            timestamp=datetime.utcnow(),
            liquidation_score=liq_score,
            whale_score=whale_score,
            liquidation_metrics=liq_metrics,
            whale_metrics=whale_metrics
        )

    def should_trade(self) -> Tuple[bool, str, float]:
        """
        Simple check if we should trade

        Returns:
            (should_trade, side, confidence)
            side is "YES" or "NO"
        """
        signal = self.get_aggregated_signal()

        if signal.decision == TradingDecision.HOLD:
            return False, None, signal.confidence

        side = "YES" if "YES" in signal.decision.value else "NO"
        return True, side, signal.confidence

    def print_status(self) -> None:
        """Print current status of all agents and final signal"""
        signal = self.get_aggregated_signal()

        print("\n" + "="*70)
        print("                   SIGNAL AGGREGATOR STATUS")
        print("="*70)

        # Liquidation Agent
        print("\n[LIQUIDATION AGENT] (60% weight)")
        print(f"  Signal: {signal.liquidation_metrics.get('signal', 'N/A')}")
        print(f"  Score: {signal.liquidation_score:.1f}")
        print(f"  Long Liqs: ${signal.liquidation_metrics.get('long_volume', 0):,.0f}")
        print(f"  Short Liqs: ${signal.liquidation_metrics.get('short_volume', 0):,.0f}")

        # Whale Agent
        print("\n[WHALE AGENT] (40% weight)")
        print(f"  Signal: {signal.whale_metrics.get('signal', 'N/A')}")
        print(f"  Score: {signal.whale_score:.1f}")
        print(f"  Imbalance: {signal.whale_metrics.get('imbalance_ratio', 1):.2f}")

        # Final Decision
        print("\n" + "-"*70)
        print("                      FINAL DECISION")
        print("-"*70)
        print(f"  Combined Score: {signal.score:.1f}")
        print(f"  Decision: {signal.decision.value}")
        print(f"  Confidence: {signal.confidence:.0f}%")

        # Action
        should, side, conf = self.should_trade()
        if should:
            print(f"\n  >>> TRADE: BUY {side} @ {conf:.0f}% confidence")
        else:
            print(f"\n  >>> NO TRADE (signal not strong enough)")

        print("="*70 + "\n")


# Package init
def create_aggregator() -> SignalAggregator:
    """Factory function to create a SignalAggregator"""
    return SignalAggregator()


# =============================================================================
# Standalone test
# =============================================================================
if __name__ == "__main__":
    import random

    agg = SignalAggregator()

    # Simulate liquidations (bearish - more longs being liquidated)
    print("\nSimulating liquidation data (bearish bias)...")
    for i in range(30):
        side = random.choice(["long", "long", "long", "short"])  # 3:1 long bias
        agg.add_liquidation(
            exchange=random.choice(["Binance", "Bybit"]),
            symbol="BTCUSDT",
            side=side,
            size_usd=random.uniform(10000, 200000),
            price=87000
        )

    # Simulate order book (neutral to slightly bearish)
    print("Simulating order book data...")
    bids = [{"price": 87000 - i*10, "size": random.uniform(0.5, 3)} for i in range(30)]
    asks = [{"price": 87010 + i*10, "size": random.uniform(0.5, 5)} for i in range(30)]
    agg.update_order_book("BTC", bids, asks)

    # Print status
    agg.print_status()
