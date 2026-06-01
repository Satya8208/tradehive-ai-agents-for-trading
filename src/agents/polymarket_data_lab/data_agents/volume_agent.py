"""
Volume Agent for Crypto Polymarket Trading

Tracks trading volume as a momentum and conviction indicator.
- Volume spike + price move = high conviction signal
- Low volume + price move = weak signal (likely to reverse)
- Volume acceleration = smart money entering

Weight: 20% (confirmation signal)
Best for: Confirming breakouts and identifying exhaustion

Built with love by TradeHive
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, TYPE_CHECKING
import asyncio

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig, SignalDirection
from src.agents.crypto_polymarket.models import MarketSignal
from src.agents.crypto_polymarket.data_agents.base_data_agent import BaseDataAgent

if TYPE_CHECKING:
    from src.data.connectors.unified_pipeline import UnifiedDataPipeline


class VolumeAgent(BaseDataAgent):
    """
    Volume analysis agent for detecting momentum and conviction.

    Volume confirms price movements:
    - High volume + price↑ = Strong bullish conviction
    - High volume + price↓ = Strong bearish conviction
    - Low volume + price move = Weak signal (likely fakeout)

    Also detects volume spikes as early warning of major moves.
    """

    def __init__(
        self,
        config: CryptoPolymarketConfig,
        pipeline: Optional["UnifiedDataPipeline"] = None,
        lookback_seconds: int = 300,  # 5 minutes default
        volume_spike_threshold: float = 2.0,  # 2x average = spike
    ):
        """
        Initialize Volume agent.

        Args:
            config: Agent configuration
            pipeline: UnifiedDataPipeline for data access
            lookback_seconds: Time window for volume analysis
            volume_spike_threshold: Multiplier over recent average for spike detection
        """
        super().__init__(config, "volume")
        self.pipeline = pipeline
        self.lookback_seconds = lookback_seconds
        self.volume_spike_threshold = volume_spike_threshold
        self.volume_history: Dict[str, float] = {}  # symbol -> avg volume

    def set_pipeline(self, pipeline: "UnifiedDataPipeline") -> None:
        """Set the data pipeline for late initialization."""
        self.pipeline = pipeline

    async def fetch_data(self) -> Dict[str, Any]:
        """
        Fetch volume data from pipeline.

        Returns:
            Dict with volume metrics per symbol
        """
        if not self.pipeline:
            return {"error": "Pipeline not initialized", "timestamp": datetime.utcnow()}

        try:
            data = {"timestamp": datetime.utcnow(), "symbols": {}}

            # Get volume metrics for BTC and ETH
            for symbol in ["BTC", "ETH"]:
                metrics = self.pipeline.get_volume_metrics(
                    symbol, seconds=self.lookback_seconds
                )

                if metrics:
                    data["symbols"][symbol] = metrics

                    # Calculate spike vs historical average
                    avg_volume = self.volume_history.get(
                        symbol, metrics["total_volume"]
                    )
                    current_volume = metrics["total_volume"]

                    spike_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

                    metrics["spike_ratio"] = spike_ratio
                    metrics["avg_volume"] = avg_volume

                    # Update historical average (exponential moving average)
                    alpha = 0.1  # Smoothing factor
                    new_avg = (alpha * current_volume) + ((1 - alpha) * avg_volume)
                    self.volume_history[symbol] = new_avg

            return data

        except Exception as e:
            return {"error": str(e), "timestamp": datetime.utcnow()}

    def analyze(self, raw_data: Dict[str, Any]) -> MarketSignal:
        """
        Analyze volume patterns and generate signal.

        Logic:
        1. Volume spike + confident direction = Strong signal (higher weight)
        2. Low volume + any direction = Weak signal (lower confidence)
        3. Volume acceleration (increasing over time) = Early warning
        4. High volume + price flat = Absorption/indistribution

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
            return self._create_neutral_signal(symbol, f"No volume data for {symbol}")

        total_volume = symbol_data.get("total_volume", 0)
        buy_volume = symbol_data.get("buy_volume", 0)
        sell_volume = symbol_data.get("sell_volume", 0)
        trade_count = symbol_data.get("trade_count", 0)
        spike_ratio = symbol_data.get("spike_ratio", 1.0)
        whale_volume = symbol_data.get("whale_volume", 0)

        # Signal detection logic
        direction = SignalDirection.NEUTRAL
        strength = 0.0
        confidence = 0.5
        reasoning = ""

        # Check for volume spike (> threshold)
        if spike_ratio >= self.volume_spike_threshold:
            # Volume spike detected - strong conviction signal

            # Determine direction from buy/sell ratio
            buy_sell_ratio = symbol_data.get("buy_sell_ratio", 1.0)

            if buy_sell_ratio > 1.5:
                # Significantly more buy volume = bullish
                direction = SignalDirection.BULLISH
                strength = min(spike_ratio / self.volume_spike_threshold * 0.8, 0.9)
                confidence = 0.70
                reasoning = f"Volume SPIKE {spike_ratio:.1f}x avg with {buy_sell_ratio:.1f}x buy volume = strong bullish conviction"

            elif buy_sell_ratio < 0.67:
                # Significantly more sell volume = bearish
                direction = SignalDirection.BEARISH
                strength = min(spike_ratio / self.volume_spike_threshold * 0.8, 0.9)
                confidence = 0.70
                reasoning = f"Volume SPIKE {spike_ratio:.1f}x avg with {1 / buy_sell_ratio:.1f}x sell volume = strong bearish conviction"

            else:
                # Volume spike but balanced = battle, no clear direction
                direction = SignalDirection.NEUTRAL
                strength = 0.3
                confidence = 0.50
                reasoning = f"Volume spike {spike_ratio:.1f}x but balanced buy/sell = indecision"

        # Check for low volume
        elif trade_count < 10:
            # Low volume = weak signal regardless of direction
            direction = SignalDirection.NEUTRAL
            strength = 0.0
            confidence = 0.40
            reasoning = f"Low volume ({trade_count} trades, ${total_volume:,.0f}) = unreliable signal"

        # Moderate volume check
        else:
            buy_sell_ratio = symbol_data.get("buy_sell_ratio", 1.0)

            if buy_sell_ratio > 1.3:
                direction = SignalDirection.BULLISH
                strength = 0.3
                confidence = 0.55
                reasoning = f"Moderate volume with {buy_sell_ratio:.1f}x buy bias = mild bullish"

            elif buy_sell_ratio < 0.77:
                direction = SignalDirection.BEARISH
                strength = 0.3
                confidence = 0.55
                reasoning = f"Moderate volume with {1 / buy_sell_ratio:.1f}x sell bias = mild bearish"

            else:
                direction = SignalDirection.NEUTRAL
                strength = 0.0
                confidence = 0.5
                reasoning = f"Moderate volume but balanced = no clear bias"

        return MarketSignal(
            agent_name=self.name,
            symbol=symbol,
            timestamp=datetime.utcnow(),
            direction=direction,
            strength=strength,
            confidence=confidence,
            raw_data=symbol_data,
            reasoning=reasoning,
        )

    def set_lookback(self, seconds: int) -> None:
        """
        Set lookback period for volume analysis.

        Useful for multi-timeframe analysis.

        Args:
            seconds: Time window in seconds
        """
        self.lookback_seconds = seconds

    def is_volume_spike(self, symbol: str, current_volume: float) -> bool:
        """
        Check if current volume is a spike vs historical average.

        Args:
            symbol: Coin symbol
            current_volume: Current volume to check

        Returns:
            True if volume is above spike threshold
        """
        avg_volume = self.volume_history.get(symbol, current_volume)

        if avg_volume == 0:
            return False

        ratio = current_volume / avg_volume
        return ratio >= self.volume_spike_threshold


if __name__ == "__main__":
    import asyncio

    async def test_volume_agent():
        print("\n[TARGET] Testing Volume Agent")
        print("=" * 60)

        config = CryptoPolymarketConfig()
        pipeline = UnifiedDataPipeline()

        agent = VolumeAgent(config, pipeline, lookback_seconds=300)

        try:
            await pipeline.start()

            # Let it collect some data
            await asyncio.sleep(10)

            # Get signal
            signal = await agent.get_signal()

            print(f"\nSignal: {signal.direction.value}")
            print(f"Strength: {signal.strength:.2f}")
            print(f"Confidence: {signal.confidence:.2f}")
            print(f"Reasoning: {signal.reasoning}")

            if signal.raw_data:
                metrics = signal.raw_data
                print(f"\nVolume Metrics:")
                print(f"  Total: ${metrics.get('total_volume', 0):,.0f}")
                print(f"  Buy: ${metrics.get('buy_volume', 0):,.0f}")
                print(f"  Sell: ${metrics.get('sell_volume', 0):,.0f}")
                print(f"  Spike Ratio: {metrics.get('spike_ratio', 0):.1f}x")

        except Exception as e:
            print(f"Error: {e}")
            import traceback

            traceback.print_exc()
        finally:
            await pipeline.stop()

        print("\n" + "=" * 60)

    asyncio.run(test_volume_agent())
