"""
Liquidation Agent

Tracks crypto liquidations as market signals using real-time WebSocket data.
Heavy long liquidations = bearish, heavy short liquidations = bullish.

Weight: 30% | Accuracy: 60-62%
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
from src.agents.crypto_polymarket.data_agents.base_data_agent import (
    BaseDataAgent,
    SyncDataAgentMixin,
)

if TYPE_CHECKING:
    from src.data.connectors.unified_pipeline import UnifiedDataPipeline


class LiquidationAgent(BaseDataAgent, SyncDataAgentMixin):
    """
    Tracks crypto liquidations as market signals.

    Uses real-time WebSocket data from UnifiedDataPipeline instead of
    polling TradeHive API. Aggregates liquidations from Binance and Bybit.

    Signal Logic:
    - Heavy long liquidations -> Bearish (longs getting squeezed)
    - Heavy short liquidations -> Bullish (shorts getting squeezed)
    - Ratio > 1.5 = strong bearish, Ratio < 0.67 = strong bullish

    Accuracy: 60-62%
    Weight: 30%
    """

    def __init__(
        self,
        config: CryptoPolymarketConfig,
        pipeline: Optional["UnifiedDataPipeline"] = None,
    ):
        """
        Initialize liquidation agent.

        Args:
            config: Agent configuration
            pipeline: UnifiedDataPipeline instance (required for real-time data)
        """
        super().__init__(config, "liquidation")
        self.pipeline = pipeline
        self.lookback_seconds = config.liquidation_lookback_hours * 3600

        # Thresholds for signal generation
        self.strong_bullish_ratio = 0.5  # Ratio below this = strong bullish
        self.weak_bullish_ratio = 0.67  # Ratio below this = weak bullish
        self.weak_bearish_ratio = 1.5  # Ratio above this = weak bearish
        self.strong_bearish_ratio = 2.0  # Ratio above this = strong bearish
        self.min_volume_usd = 25000  # Lowered for better signals in quiet markets

    def set_pipeline(self, pipeline: "UnifiedDataPipeline") -> None:
        """Set the data pipeline (for late initialization)."""
        self.pipeline = pipeline

    async def fetch_data(self) -> Dict[str, Any]:
        """
        Fetch liquidation data from the unified pipeline.

        Returns real-time aggregated data from Binance and Bybit.
        """
        if not self.pipeline:
            return {"error": "Pipeline not initialized", "timestamp": datetime.utcnow()}

        # Get data for last 2 minutes (120 seconds) - faster signals for 15-min markets
        lookback = 120

        # Get aggregated volumes
        total_volume = self.pipeline.get_liquidation_volume(seconds=lookback)
        btc_volume = self.pipeline.get_liquidation_volume(
            seconds=lookback, symbol="BTC"
        )
        eth_volume = self.pipeline.get_liquidation_volume(
            seconds=lookback, symbol="ETH"
        )

        # Get ratios
        total_ratio = self.pipeline.get_liquidation_ratio(seconds=lookback)
        btc_ratio = self.pipeline.get_liquidation_ratio(
            seconds=lookback
        )  # Most liquidations are BTC anyway

        # Get counts
        counts = self.pipeline.get_liquidation_count(seconds=lookback)

        # Get recent large liquidations
        large_liqs = self.pipeline.get_recent_liquidations(
            seconds=lookback, min_usd_value=50000
        )

        return {
            "total_volume": total_volume,
            "btc_volume": btc_volume,
            "eth_volume": eth_volume,
            "total_ratio": total_ratio,
            "btc_ratio": btc_ratio,
            "counts": counts,
            "large_liquidations": large_liqs,
            "timestamp": datetime.utcnow(),
        }

    def analyze(self, raw_data: Dict[str, Any]) -> MarketSignal:
        """
        Analyze liquidation data for trading signal.

        Uses the long/short ratio and volume to determine market direction.
        """
        if raw_data.get("error"):
            return self._create_neutral_signal(
                symbol="BOTH", reasoning=raw_data["error"]
            )

        total_volume = raw_data.get("total_volume", {})
        ratio = raw_data.get("total_ratio", 1.0)
        counts = raw_data.get("counts", {})

        long_vol = total_volume.get("long", 0)
        short_vol = total_volume.get("short", 0)
        total_vol = total_volume.get("total", 0)

        # Check minimum volume threshold
        if total_vol < self.min_volume_usd:
            return self._create_neutral_signal(
                symbol="BOTH",
                reasoning=f"Low liquidation volume (${total_vol:,.0f}) - no clear signal",
            )

        # Determine direction based on ratio
        # ratio > 1 means more longs liquidated (bearish)
        # ratio < 1 means more shorts liquidated (bullish)
        if ratio >= self.strong_bearish_ratio:
            direction = SignalDirection.BEARISH
            strength = min(1.0, (ratio - 1) * 0.4)
            confidence = min(0.85, total_vol / 1000000)
            reasoning = f"Heavy long liquidations (ratio: {ratio:.2f}) - strong bearish"

        elif ratio >= self.weak_bearish_ratio:
            direction = SignalDirection.BEARISH
            strength = min(0.6, (ratio - 1) * 0.3)
            confidence = min(0.7, total_vol / 1000000)
            reasoning = f"More longs liquidated (ratio: {ratio:.2f}) - weak bearish"

        elif ratio <= self.strong_bullish_ratio:
            direction = SignalDirection.BULLISH
            strength = min(1.0, (1 / ratio - 1) * 0.4)
            confidence = min(0.85, total_vol / 1000000)
            reasoning = (
                f"Heavy short liquidations (ratio: {ratio:.2f}) - strong bullish"
            )

        elif ratio <= self.weak_bullish_ratio:
            direction = SignalDirection.BULLISH
            strength = min(0.6, (1 / ratio - 1) * 0.3)
            confidence = min(0.7, total_vol / 1000000)
            reasoning = f"More shorts liquidated (ratio: {ratio:.2f}) - weak bullish"

        else:
            direction = SignalDirection.NEUTRAL
            strength = 0.0
            confidence = 0.5
            reasoning = f"Balanced liquidations (ratio: {ratio:.2f})"

        # Ensure minimum confidence
        confidence = max(0.3, confidence)

        # Determine primary symbol (BTC dominates)
        btc_vol = raw_data.get("btc_volume", {}).get("total", 0)
        eth_vol = raw_data.get("eth_volume", {}).get("total", 0)
        symbol = "BTC" if btc_vol > eth_vol else "ETH" if eth_vol > btc_vol else "BOTH"

        return MarketSignal(
            agent_name=self.name,
            timestamp=datetime.utcnow(),
            symbol=symbol,
            direction=direction,
            strength=strength,
            confidence=confidence,
            raw_data={
                "long_volume": long_vol,
                "short_volume": short_vol,
                "total_volume": total_vol,
                "ratio": ratio,
                "long_count": counts.get("long", 0),
                "short_count": counts.get("short", 0),
            },
            reasoning=reasoning,
        )

    def get_signal_sync(self) -> MarketSignal:
        """
        Synchronous method to get current signal.

        Useful for quick polling without async overhead.
        For 15-min markets, use 2-minute window for faster signals.
        """
        if not self.pipeline:
            return self._create_neutral_signal(
                symbol="BOTH", reasoning="Pipeline not initialized"
            )

        # Get 2-minute window data (faster signals for 15-min markets)
        ratio = self.pipeline.get_liquidation_ratio(seconds=120)
        volume = self.pipeline.get_liquidation_volume(seconds=120)

        total_vol = volume.get("total", 0)
        long_vol = volume.get("long", 0)
        short_vol = volume.get("short", 0)

        if total_vol < self.min_volume_usd:
            return self._create_neutral_signal(
                symbol="BOTH", reasoning=f"Low volume: ${total_vol:,.0f}"
            )

        # Quick signal determination
        if ratio > self.weak_bearish_ratio:
            direction = SignalDirection.BEARISH
            strength = min(1.0, (ratio - 1) * 0.3)
            reasoning = f"Long liq dominance ({ratio:.2f})"
        elif ratio < self.weak_bullish_ratio:
            direction = SignalDirection.BULLISH
            strength = min(1.0, (1 / ratio - 1) * 0.3)
            reasoning = f"Short liq dominance ({ratio:.2f})"
        else:
            direction = SignalDirection.NEUTRAL
            strength = 0.0
            reasoning = f"Balanced ({ratio:.2f})"

        return MarketSignal(
            agent_name=self.name,
            timestamp=datetime.utcnow(),
            symbol="BOTH",
            direction=direction,
            strength=strength,
            confidence=min(0.7, total_vol / 500000),
            raw_data={"ratio": ratio, "volume": total_vol},
            reasoning=reasoning,
        )

    def get_liquidation_summary(self) -> str:
        """Get human-readable summary of current liquidation state."""
        if not self.pipeline:
            return "Pipeline not initialized"

        # Use 2-minute window for faster signals (15-min market trading)
        ratio = self.pipeline.get_liquidation_ratio(seconds=120)
        volume = self.pipeline.get_liquidation_volume(seconds=120)
        counts = self.pipeline.get_liquidation_count(seconds=120)

        if ratio > 1.5:
            sentiment = "BEARISH [BEAR]"
        elif ratio < 0.67:
            sentiment = "BULLISH [BULL]"
        else:
            sentiment = "NEUTRAL [NEUTRAL]"

        summary = f"""
[CHART] Liquidation Summary (2min window)
{"=" * 40}
Sentiment: {sentiment}
Ratio: {ratio:.2f} (long/short)

Volume:
  Long:  ${volume["long"]:>12,.0f}
  Short: ${volume["short"]:>12,.0f}
  Total: ${volume["total"]:>12,.0f}

Count:
  Long:  {counts["long"]:>6}
  Short: {counts["short"]:>6}
  Total: {counts["total"]:>6}
{"=" * 40}
"""
        return summary
