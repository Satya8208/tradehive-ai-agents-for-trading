"""
Funding Agent

Tracks funding rates as contrarian signals using real-time data.
Extreme positive funding = bearish, extreme negative = bullish.

Weight: 20% | Accuracy: 48-50%
Built with love by TradeHive
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, TYPE_CHECKING

project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig, SignalDirection
from src.agents.crypto_polymarket.models import MarketSignal
from src.agents.crypto_polymarket.data_agents.base_data_agent import BaseDataAgent, SyncDataAgentMixin

if TYPE_CHECKING:
    from src.data.connectors.unified_pipeline import UnifiedDataPipeline


class FundingAgent(BaseDataAgent, SyncDataAgentMixin):
    """
    Tracks funding rates as contrarian signals.

    Uses real-time data from UnifiedDataPipeline (Hyperliquid REST API).

    Signal Logic:
    - Extremely positive funding (>0.05%) -> Bearish (too many longs)
    - Extremely negative funding (<-0.02%) -> Bullish (too many shorts)
    - Neutral zone between

    This is a contrarian indicator: when funding is extreme,
    the market is overleveraged and likely to reverse.

    Accuracy: 48-50% (use primarily as confirmation)
    Weight: 20%
    """

    def __init__(
        self,
        config: CryptoPolymarketConfig,
        pipeline: Optional["UnifiedDataPipeline"] = None
    ):
        """
        Initialize funding agent.

        Args:
            config: Agent configuration
            pipeline: UnifiedDataPipeline instance (required for real-time data)
        """
        super().__init__(config, "funding")
        self.pipeline = pipeline

        # Funding thresholds (8-hour rate, not annualized)
        # Typical rates: -0.01% to 0.03%
        # Extreme high: > 0.05% (very bullish sentiment, contrarian bearish)
        # Extreme low: < -0.02% (very bearish sentiment, contrarian bullish)
        self.extreme_high = 0.0005  # 0.05% per 8 hours
        self.extreme_low = -0.0002  # -0.02% per 8 hours
        self.strong_high = 0.001    # 0.1% per 8 hours (very extreme)
        self.strong_low = -0.0005   # -0.05% per 8 hours (very extreme)

    def set_pipeline(self, pipeline: "UnifiedDataPipeline") -> None:
        """Set the data pipeline (for late initialization)."""
        self.pipeline = pipeline

    async def fetch_data(self) -> Dict[str, Any]:
        """
        Fetch funding rate data from the unified pipeline.

        Uses Hyperliquid REST API for current funding rates.
        """
        if not self.pipeline:
            return {
                "error": "Pipeline not initialized",
                "timestamp": datetime.utcnow()
            }

        # Get funding rates from Hyperliquid
        funding_rates = await self.pipeline.get_funding_rates()

        # Extract BTC and ETH rates
        btc_rate = funding_rates.get("BTC")
        eth_rate = funding_rates.get("ETH")

        return {
            "funding_rates": funding_rates,
            "btc_rate": btc_rate.rate if btc_rate else 0.0,
            "eth_rate": eth_rate.rate if eth_rate else 0.0,
            "timestamp": datetime.utcnow(),
        }

    def analyze(self, raw_data: Dict[str, Any]) -> MarketSignal:
        """
        Analyze funding rates for trading signal.

        Uses contrarian logic: extreme funding = market reversal likely.
        """
        if raw_data.get("error"):
            return self._create_neutral_signal(
                symbol="BOTH",
                reasoning=raw_data["error"]
            )

        btc_rate = raw_data.get("btc_rate", 0.0)
        eth_rate = raw_data.get("eth_rate", 0.0)

        # Analyze BTC (primary)
        btc_signal = self._analyze_funding(btc_rate, "BTC")
        eth_signal = self._analyze_funding(eth_rate, "ETH")

        # Use BTC as primary signal
        if btc_signal["direction"] != SignalDirection.NEUTRAL:
            return MarketSignal(
                agent_name=self.name,
                timestamp=datetime.utcnow(),
                symbol="BTC",
                direction=btc_signal["direction"],
                strength=btc_signal["strength"],
                confidence=btc_signal["confidence"],
                raw_data={
                    "btc_rate": btc_rate,
                    "eth_rate": eth_rate,
                    "btc_rate_pct": btc_rate * 100,
                    "eth_rate_pct": eth_rate * 100,
                },
                reasoning=btc_signal["reasoning"]
            )

        # Fall back to ETH signal
        if eth_signal["direction"] != SignalDirection.NEUTRAL:
            return MarketSignal(
                agent_name=self.name,
                timestamp=datetime.utcnow(),
                symbol="ETH",
                direction=eth_signal["direction"],
                strength=eth_signal["strength"],
                confidence=eth_signal["confidence"],
                raw_data={
                    "btc_rate": btc_rate,
                    "eth_rate": eth_rate,
                    "btc_rate_pct": btc_rate * 100,
                    "eth_rate_pct": eth_rate * 100,
                },
                reasoning=eth_signal["reasoning"]
            )

        # Both neutral
        btc_pct = btc_rate * 100
        eth_pct = eth_rate * 100
        return self._create_neutral_signal(
            symbol="BOTH",
            reasoning=f"Funding rates neutral (BTC: {btc_pct:.4f}%, ETH: {eth_pct:.4f}%)"
        )

    def _analyze_funding(self, funding_rate: float, symbol: str) -> Dict[str, Any]:
        """
        Analyze funding rate for a symbol.

        Funding rate is in decimal form (e.g., 0.0001 = 0.01%)
        Returns dict with direction, strength, confidence, reasoning.
        """
        rate_pct = funding_rate * 100  # Convert to percentage for display

        # Strong positive funding = strong bearish (too many longs)
        if funding_rate >= self.strong_high:
            direction = SignalDirection.BEARISH
            strength = min(1.0, (funding_rate - self.extreme_high) / 0.001)
            reasoning = f"{symbol}: EXTREME funding ({rate_pct:.4f}%) - overleveraged longs"
            confidence = 0.6

        # Extreme positive funding = bearish
        elif funding_rate >= self.extreme_high:
            direction = SignalDirection.BEARISH
            strength = min(0.6, (funding_rate - self.extreme_high) / 0.0005)
            reasoning = f"{symbol}: High funding ({rate_pct:.4f}%) - longs paying shorts"
            confidence = 0.5

        # Strong negative funding = strong bullish (too many shorts)
        elif funding_rate <= self.strong_low:
            direction = SignalDirection.BULLISH
            strength = min(1.0, abs(funding_rate - self.extreme_low) / 0.0005)
            reasoning = f"{symbol}: EXTREME negative funding ({rate_pct:.4f}%) - overleveraged shorts"
            confidence = 0.6

        # Extreme negative funding = bullish
        elif funding_rate <= self.extreme_low:
            direction = SignalDirection.BULLISH
            strength = min(0.6, abs(funding_rate - self.extreme_low) / 0.0003)
            reasoning = f"{symbol}: Negative funding ({rate_pct:.4f}%) - shorts paying longs"
            confidence = 0.5

        # Neutral zone
        else:
            direction = SignalDirection.NEUTRAL
            strength = 0.0
            reasoning = f"{symbol}: Funding neutral ({rate_pct:.4f}%)"
            confidence = 0.3

        return {
            "direction": direction,
            "strength": strength,
            "confidence": confidence,
            "reasoning": reasoning,
            "funding_rate": funding_rate,
            "funding_rate_pct": rate_pct,
        }

    def get_signal_sync(self) -> MarketSignal:
        """
        Synchronous method to get current signal.

        Note: Funding rates require async call to Hyperliquid REST API.
        This method returns neutral if no cached data is available.
        """
        return self._create_neutral_signal(
            symbol="BOTH",
            reasoning="Use async get_signal() for funding data"
        )

    def get_funding_summary(self) -> str:
        """Get human-readable summary of current funding rates."""
        if not self.pipeline:
            return "Pipeline not initialized"

        # Note: This would need async call, return placeholder
        return """
Funding Rate Summary
{'='*40}
Use async fetch to get current rates from Hyperliquid.
Funding updates every 8 hours.
{'='*40}
"""
