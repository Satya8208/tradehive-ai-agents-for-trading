"""
Order Book Imbalance Agent for Crypto Polymarket Trading

Analyzes bid/ask volume imbalance to generate directional signals.
- Heavy bid wall = buyers stacking (bullish)
- Heavy ask wall = sellers stacking (bearish)
- Balanced book = no clear direction

Weight: 15% (real-time order flow signal)
Best for: Detecting near-term buying/selling pressure

Built with love by TradeHive
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, TYPE_CHECKING

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig, SignalDirection
from src.agents.crypto_polymarket.models import MarketSignal
from src.agents.crypto_polymarket.data_agents.base_data_agent import BaseDataAgent

if TYPE_CHECKING:
    from src.data.connectors.unified_pipeline import UnifiedDataPipeline


class OrderBookImbalanceAgent(BaseDataAgent):
    """
    Order book imbalance analysis agent for detecting buying/selling pressure.

    Uses bid/ask volume imbalance from the order book to generate signals:
    - Imbalance > +40%: Strong bullish (heavy bid wall)
    - Imbalance +20% to +40%: Weak bullish
    - Imbalance -20% to +20%: Neutral (balanced book)
    - Imbalance -40% to -20%: Weak bearish
    - Imbalance < -40%: Strong bearish (heavy ask wall)

    Confidence modifiers:
    - Whale bids detected: +10%
    - Whale asks detected: +10%
    - Tight spread (<5 bps): +5%
    - Wide spread (>20 bps): -10%

    Weight: 15%
    Accuracy: Best in ranging markets, confirms trend in trending markets
    """

    # Imbalance thresholds
    STRONG_BULLISH_THRESHOLD = 0.40  # > +40%
    WEAK_BULLISH_THRESHOLD = 0.20    # +20% to +40%
    WEAK_BEARISH_THRESHOLD = -0.20   # -20% to -40%
    STRONG_BEARISH_THRESHOLD = -0.40 # < -40%

    # Spread thresholds (basis points)
    TIGHT_SPREAD_BPS = 5
    WIDE_SPREAD_BPS = 20

    def __init__(
        self,
        config: CryptoPolymarketConfig,
        pipeline: Optional["UnifiedDataPipeline"] = None,
        levels: int = 10,
    ):
        """
        Initialize Order Book Imbalance agent.

        Args:
            config: Agent configuration
            pipeline: UnifiedDataPipeline for data access
            levels: Number of order book levels to analyze
        """
        super().__init__(config, "orderbook")
        self.pipeline = pipeline
        self.levels = levels

    def set_pipeline(self, pipeline: "UnifiedDataPipeline") -> None:
        """Set the data pipeline for late initialization."""
        self.pipeline = pipeline

    async def fetch_data(self) -> Dict[str, Any]:
        """
        Fetch order book data from pipeline.

        Returns:
            Dict with order book metrics per symbol
        """
        if not self.pipeline:
            return {"error": "Pipeline not initialized", "timestamp": datetime.utcnow()}

        try:
            data = {"timestamp": datetime.utcnow(), "symbols": {}}

            # Get order book metrics for BTC and ETH
            for symbol in ["BTC", "ETH"]:
                metrics = self.pipeline.get_order_book_metrics(
                    symbol, levels=self.levels
                )

                if metrics:
                    # Also get the simple imbalance for verification
                    imbalance = self.pipeline.get_order_book_imbalance(
                        symbol, levels=self.levels
                    )
                    metrics["imbalance_simple"] = imbalance

                    data["symbols"][symbol] = metrics

            return data

        except Exception as e:
            return {"error": str(e), "timestamp": datetime.utcnow()}

    def analyze(self, raw_data: Dict[str, Any]) -> MarketSignal:
        """
        Analyze order book imbalance and generate signal.

        Logic:
        1. > +40% imbalance = Strong bullish (heavy bid wall)
        2. +20% to +40% imbalance = Weak bullish
        3. -20% to +20% imbalance = Neutral
        4. -40% to -20% imbalance = Weak bearish
        5. < -40% imbalance = Strong bearish (heavy ask wall)

        Confidence is adjusted based on:
        - Whale presence (large orders)
        - Spread tightness

        Args:
            raw_data: Data from fetch_data()

        Returns:
            MarketSignal with direction, strength, and confidence
        """
        if "error" in raw_data:
            return self._create_error_signal(raw_data["error"])

        symbol = "BTC"  # Primary focus
        symbol_data = raw_data["symbols"].get(symbol, {})

        if not symbol_data:
            return self._create_neutral_signal(symbol, f"No order book data for {symbol}")

        # Extract metrics
        imbalance = symbol_data.get("imbalance_ratio", 0.0)
        bid_volume = symbol_data.get("bid_volume", 0)
        ask_volume = symbol_data.get("ask_volume", 0)
        whale_bids = symbol_data.get("whale_bids", 0)
        whale_asks = symbol_data.get("whale_asks", 0)
        spread = symbol_data.get("spread", None)
        total_liquidity = symbol_data.get("total_liquidity", 0)

        # Check minimum liquidity
        if total_liquidity < 1000:  # Less than $1k liquidity = unreliable
            return self._create_neutral_signal(
                symbol,
                f"Low order book liquidity (${total_liquidity:,.0f}) - no reliable signal"
            )

        # Signal detection logic based on imbalance
        direction = SignalDirection.NEUTRAL
        strength = 0.0
        base_confidence = 0.5

        if imbalance > self.STRONG_BULLISH_THRESHOLD:
            direction = SignalDirection.BULLISH
            strength = min(0.9, 0.5 + (imbalance - self.STRONG_BULLISH_THRESHOLD))
            base_confidence = 0.75
            reasoning = f"Strong bid wall ({imbalance:+.1%}) - heavy buyer stacking"

        elif imbalance > self.WEAK_BULLISH_THRESHOLD:
            direction = SignalDirection.BULLISH
            strength = 0.3 + (imbalance - self.WEAK_BULLISH_THRESHOLD) * 2
            base_confidence = 0.60
            reasoning = f"Mild bid dominance ({imbalance:+.1%}) - buyers accumulating"

        elif imbalance < self.STRONG_BEARISH_THRESHOLD:
            direction = SignalDirection.BEARISH
            strength = min(0.9, 0.5 + abs(imbalance + self.STRONG_BEARISH_THRESHOLD))
            base_confidence = 0.75
            reasoning = f"Strong ask wall ({imbalance:+.1%}) - heavy seller stacking"

        elif imbalance < self.WEAK_BEARISH_THRESHOLD:
            direction = SignalDirection.BEARISH
            strength = 0.3 + (abs(imbalance) - abs(self.WEAK_BEARISH_THRESHOLD)) * 2
            base_confidence = 0.60
            reasoning = f"Mild ask dominance ({imbalance:+.1%}) - sellers accumulating"

        else:
            direction = SignalDirection.NEUTRAL
            strength = 0.0
            base_confidence = 0.50
            reasoning = f"Balanced order book ({imbalance:+.1%}) - no clear pressure"

        # Apply confidence modifiers
        confidence = base_confidence

        # Whale presence modifier
        if whale_bids > 0 and direction == SignalDirection.BULLISH:
            confidence += 0.10
            reasoning += f" | {whale_bids} whale bid(s) detected"
        elif whale_asks > 0 and direction == SignalDirection.BEARISH:
            confidence += 0.10
            reasoning += f" | {whale_asks} whale ask(s) detected"
        elif whale_bids > 0 and whale_asks > 0:
            reasoning += f" | Whales on both sides ({whale_bids}B/{whale_asks}A)"

        # Spread modifier
        if spread is not None:
            mid_price = symbol_data.get("mid_price", 0)
            if mid_price > 0:
                spread_bps = (spread / mid_price) * 10000

                if spread_bps < self.TIGHT_SPREAD_BPS:
                    confidence += 0.05
                    reasoning += f" | Tight spread ({spread_bps:.1f}bps)"
                elif spread_bps > self.WIDE_SPREAD_BPS:
                    confidence -= 0.10
                    reasoning += f" | Wide spread ({spread_bps:.1f}bps) - less reliable"

        # Clamp confidence
        confidence = max(0.3, min(0.90, confidence))

        return MarketSignal(
            agent_name=self.name,
            symbol=symbol,
            timestamp=datetime.utcnow(),
            direction=direction,
            strength=strength,
            confidence=confidence,
            raw_data={
                "imbalance": imbalance,
                "bid_volume": bid_volume,
                "ask_volume": ask_volume,
                "total_liquidity": total_liquidity,
                "whale_bids": whale_bids,
                "whale_asks": whale_asks,
                "spread": spread,
            },
            reasoning=reasoning,
        )

    def get_orderbook_summary(self) -> str:
        """Get human-readable summary of current order book state."""
        if not self.pipeline:
            return "Pipeline not initialized"

        summary_lines = []
        summary_lines.append("\n[BOOK] Order Book Summary")
        summary_lines.append("=" * 40)

        for symbol in ["BTC", "ETH"]:
            metrics = self.pipeline.get_order_book_metrics(symbol, levels=self.levels)

            if not metrics:
                summary_lines.append(f"{symbol}: No data")
                continue

            imbalance = metrics.get("imbalance_ratio", 0)

            if imbalance > self.STRONG_BULLISH_THRESHOLD:
                sentiment = "BULLISH [BULL]"
            elif imbalance > self.WEAK_BULLISH_THRESHOLD:
                sentiment = "MILD BULLISH"
            elif imbalance < self.STRONG_BEARISH_THRESHOLD:
                sentiment = "BEARISH [BEAR]"
            elif imbalance < self.WEAK_BEARISH_THRESHOLD:
                sentiment = "MILD BEARISH"
            else:
                sentiment = "NEUTRAL"

            summary_lines.append(f"\n{symbol}:")
            summary_lines.append(f"  Sentiment: {sentiment}")
            summary_lines.append(f"  Imbalance: {imbalance:+.1%}")
            summary_lines.append(f"  Bid Vol:   ${metrics.get('bid_volume', 0):>12,.0f}")
            summary_lines.append(f"  Ask Vol:   ${metrics.get('ask_volume', 0):>12,.0f}")
            summary_lines.append(f"  Liquidity: ${metrics.get('total_liquidity', 0):>12,.0f}")

            if metrics.get("whale_bids", 0) > 0 or metrics.get("whale_asks", 0) > 0:
                summary_lines.append(
                    f"  Whales:    {metrics.get('whale_bids', 0)}B / {metrics.get('whale_asks', 0)}A"
                )

        summary_lines.append("=" * 40)
        return "\n".join(summary_lines)


if __name__ == "__main__":
    import asyncio
    from src.data.connectors.unified_pipeline import UnifiedDataPipeline

    async def test_orderbook_agent():
        print("\n[BOOK] Testing Order Book Imbalance Agent")
        print("=" * 60)

        config = CryptoPolymarketConfig()
        pipeline = UnifiedDataPipeline()

        agent = OrderBookImbalanceAgent(config, pipeline, levels=10)

        try:
            await pipeline.start()

            # Let it collect some data
            print("Waiting for order book data...")
            await asyncio.sleep(5)

            # Get signal
            signal = await agent.get_signal()

            print(f"\nSignal: {signal.direction.value}")
            print(f"Strength: {signal.strength:.2f}")
            print(f"Confidence: {signal.confidence:.2f}")
            print(f"Reasoning: {signal.reasoning}")

            if signal.raw_data:
                metrics = signal.raw_data
                print(f"\nOrder Book Metrics:")
                print(f"  Imbalance: {metrics.get('imbalance', 0):+.1%}")
                print(f"  Bid Volume: ${metrics.get('bid_volume', 0):,.0f}")
                print(f"  Ask Volume: ${metrics.get('ask_volume', 0):,.0f}")
                print(f"  Whale Bids: {metrics.get('whale_bids', 0)}")
                print(f"  Whale Asks: {metrics.get('whale_asks', 0)}")

            # Print summary
            print(agent.get_orderbook_summary())

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await pipeline.stop()

        print("\n" + "=" * 60)

    asyncio.run(test_orderbook_agent())
