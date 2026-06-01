"""
Whale Agent

Tracks whale activity via large trade detection using real-time WebSocket data.
Heavy buy flow = bullish accumulation, heavy sell flow = bearish distribution.

Weight: 40% | Accuracy: 70%+
Built with love by TradeHive
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, TYPE_CHECKING

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


class WhaleAgent(BaseDataAgent, SyncDataAgentMixin):
    """
    Tracks whale activity via large trade detection.

    Uses real-time WebSocket data from UnifiedDataPipeline instead of
    polling OI data. Monitors large trades from Hyperliquid.

    Signal Logic:
    - Heavy buy flow from whales = bullish (accumulation)
    - Heavy sell flow from whales = bearish (distribution)
    - Buy/sell ratio > 1.5 = strong bullish, < 0.67 = strong bearish

    This is the HIGHEST ACCURACY signal (70%+) so it gets 40% weight.

    Accuracy: 70%+
    Weight: 40%
    """

    def __init__(
        self,
        config: CryptoPolymarketConfig,
        pipeline: Optional["UnifiedDataPipeline"] = None,
    ):
        """
        Initialize whale agent.

        Args:
            config: Agent configuration
            pipeline: UnifiedDataPipeline instance (required for real-time data)
        """
        super().__init__(config, "whale")
        self.pipeline = pipeline
        self.lookback_seconds = 300  # 5 minute window for whale detection

        # Whale thresholds
        self.min_whale_trade_usd = 50000  # Minimum trade to consider "whale"
        self.large_whale_usd = 100000  # Large whale trade
        self.mega_whale_usd = 500000  # Mega whale trade

        # Signal thresholds
        self.strong_bullish_ratio = 2.0  # Buy/sell ratio for strong bullish
        self.weak_bullish_ratio = 1.3  # Buy/sell ratio for weak bullish
        self.weak_bearish_ratio = 0.77  # Buy/sell ratio for weak bearish
        self.strong_bearish_ratio = 0.5  # Buy/sell ratio for strong bearish
        self.min_whale_volume_usd = 100000  # Minimum whale volume for valid signal

    def set_pipeline(self, pipeline: "UnifiedDataPipeline") -> None:
        """Set the data pipeline (for late initialization)."""
        self.pipeline = pipeline

    async def fetch_data(self) -> Dict[str, Any]:
        """
        Fetch whale trade data from the unified pipeline.

        Returns real-time aggregated data from Hyperliquid trades.
        """
        if not self.pipeline:
            return {"error": "Pipeline not initialized", "timestamp": datetime.utcnow()}

        # Get whale trades (large trades above threshold)
        whale_trades = self.pipeline.get_whale_trades(
            seconds=self.lookback_seconds, min_usd_value=self.min_whale_trade_usd
        )

        # Get trade flow aggregates per symbol
        btc_flow = self.pipeline.get_trade_flow(
            symbol="BTC", seconds=self.lookback_seconds
        )
        eth_flow = self.pipeline.get_trade_flow(
            symbol="ETH", seconds=self.lookback_seconds
        )
        # Total flow is sum of BTC and ETH
        total_flow = {
            "buy": btc_flow.get("buy", 0) + eth_flow.get("buy", 0),
            "sell": btc_flow.get("sell", 0) + eth_flow.get("sell", 0),
            "net": btc_flow.get("net", 0) + eth_flow.get("net", 0),
        }

        # Categorize whale trades
        large_whales = [
            t for t in whale_trades if t.price * t.size >= self.large_whale_usd
        ]
        mega_whales = [
            t for t in whale_trades if t.price * t.size >= self.mega_whale_usd
        ]

        # Calculate whale-specific buy/sell volumes
        whale_buy_volume = sum(
            t.price * t.size for t in whale_trades if t.side == "buy"
        )
        whale_sell_volume = sum(
            t.price * t.size for t in whale_trades if t.side == "sell"
        )

        return {
            "whale_trades": whale_trades,
            "whale_count": len(whale_trades),
            "large_whale_count": len(large_whales),
            "mega_whale_count": len(mega_whales),
            "whale_buy_volume": whale_buy_volume,
            "whale_sell_volume": whale_sell_volume,
            "total_flow": total_flow,
            "btc_flow": btc_flow,
            "eth_flow": eth_flow,
            "timestamp": datetime.utcnow(),
        }

    def analyze(self, raw_data: Dict[str, Any]) -> MarketSignal:
        """
        Analyze whale trade data for trading signal.

        Uses whale trade flow (buy/sell) to determine market direction.
        """
        if raw_data.get("error"):
            return self._create_neutral_signal(
                symbol="BOTH", reasoning=raw_data["error"]
            )

        whale_count = raw_data.get("whale_count", 0)
        whale_buy_volume = raw_data.get("whale_buy_volume", 0)
        whale_sell_volume = raw_data.get("whale_sell_volume", 0)
        total_whale_volume = whale_buy_volume + whale_sell_volume
        mega_whale_count = raw_data.get("mega_whale_count", 0)

        # Check minimum whale activity
        if total_whale_volume < self.min_whale_volume_usd:
            return self._create_neutral_signal(
                symbol="BOTH",
                reasoning=f"Low whale volume (${total_whale_volume:,.0f}) - no clear signal",
            )

        # Calculate buy/sell ratio
        if whale_sell_volume > 0:
            ratio = whale_buy_volume / whale_sell_volume
        else:
            ratio = 10.0 if whale_buy_volume > 0 else 1.0

        # Determine direction based on ratio
        if ratio >= self.strong_bullish_ratio:
            direction = SignalDirection.BULLISH
            strength = min(1.0, (ratio - 1) * 0.3)
            confidence = min(0.9, total_whale_volume / 500000)
            reasoning = (
                f"WHALE ALERT: Heavy buying (ratio: {ratio:.2f}) - strong accumulation"
            )

        elif ratio >= self.weak_bullish_ratio:
            direction = SignalDirection.BULLISH
            strength = min(0.6, (ratio - 1) * 0.25)
            confidence = min(0.75, total_whale_volume / 500000)
            reasoning = f"Whale buy pressure (ratio: {ratio:.2f}) - accumulation"

        elif ratio <= self.strong_bearish_ratio:
            direction = SignalDirection.BEARISH
            strength = min(1.0, (1 / ratio - 1) * 0.3)
            confidence = min(0.9, total_whale_volume / 500000)
            reasoning = (
                f"WHALE ALERT: Heavy selling (ratio: {ratio:.2f}) - strong distribution"
            )

        elif ratio <= self.weak_bearish_ratio:
            direction = SignalDirection.BEARISH
            strength = min(0.6, (1 / ratio - 1) * 0.25)
            confidence = min(0.75, total_whale_volume / 500000)
            reasoning = f"Whale sell pressure (ratio: {ratio:.2f}) - distribution"

        else:
            direction = SignalDirection.NEUTRAL
            strength = 0.0
            confidence = 0.5
            reasoning = f"Balanced whale activity (ratio: {ratio:.2f})"

        # Boost confidence for mega whale presence
        if mega_whale_count > 0:
            confidence = min(0.95, confidence + 0.1)
            reasoning = f"{reasoning} [{mega_whale_count} mega whale(s)]"

        # Ensure minimum confidence
        confidence = max(0.4, confidence)

        # Determine primary symbol from flow data
        btc_flow = raw_data.get("btc_flow", {})
        eth_flow = raw_data.get("eth_flow", {})
        btc_total = btc_flow.get("total", 0)
        eth_total = eth_flow.get("total", 0)
        symbol = (
            "BTC"
            if btc_total > eth_total
            else "ETH"
            if eth_total > btc_total
            else "BOTH"
        )

        return MarketSignal(
            agent_name=self.name,
            timestamp=datetime.utcnow(),
            symbol=symbol,
            direction=direction,
            strength=strength,
            confidence=confidence,
            raw_data={
                "whale_count": whale_count,
                "whale_buy_volume": whale_buy_volume,
                "whale_sell_volume": whale_sell_volume,
                "total_whale_volume": total_whale_volume,
                "ratio": ratio,
                "mega_whale_count": mega_whale_count,
            },
            reasoning=reasoning,
        )

    def get_signal_sync(self) -> MarketSignal:
        """
        Synchronous method to get current signal.

        Useful for quick polling without async overhead.
        """
        if not self.pipeline:
            return self._create_neutral_signal(
                symbol="BOTH", reasoning="Pipeline not initialized"
            )

        # Get whale trades from 5-minute window
        whale_trades = self.pipeline.get_whale_trades(
            seconds=self.lookback_seconds, min_usd_value=self.min_whale_trade_usd
        )

        whale_buy = sum(t.price * t.size for t in whale_trades if t.side == "buy")
        whale_sell = sum(t.price * t.size for t in whale_trades if t.side == "sell")
        total_volume = whale_buy + whale_sell

        if total_volume < self.min_whale_volume_usd:
            return self._create_neutral_signal(
                symbol="BOTH", reasoning=f"Low whale volume: ${total_volume:,.0f}"
            )

        # Calculate ratio
        ratio = whale_buy / whale_sell if whale_sell > 0 else 10.0

        # Quick signal determination
        if ratio > self.weak_bullish_ratio:
            direction = SignalDirection.BULLISH
            strength = min(1.0, (ratio - 1) * 0.3)
            reasoning = f"Whale buy dominance ({ratio:.2f})"
        elif ratio < self.weak_bearish_ratio:
            direction = SignalDirection.BEARISH
            strength = min(1.0, (1 / ratio - 1) * 0.3)
            reasoning = f"Whale sell dominance ({ratio:.2f})"
        else:
            direction = SignalDirection.NEUTRAL
            strength = 0.0
            reasoning = f"Balanced whale flow ({ratio:.2f})"

        return MarketSignal(
            agent_name=self.name,
            timestamp=datetime.utcnow(),
            symbol="BOTH",
            direction=direction,
            strength=strength,
            confidence=min(0.8, total_volume / 500000),
            raw_data={
                "ratio": ratio,
                "volume": total_volume,
                "count": len(whale_trades),
            },
            reasoning=reasoning,
        )

    def get_whale_summary(self) -> str:
        """Get human-readable summary of current whale activity."""
        if not self.pipeline:
            return "Pipeline not initialized"

        whale_trades = self.pipeline.get_whale_trades(
            seconds=self.lookback_seconds, min_usd_value=self.min_whale_trade_usd
        )

        whale_buy = sum(t.price * t.size for t in whale_trades if t.side == "buy")
        whale_sell = sum(t.price * t.size for t in whale_trades if t.side == "sell")
        total_volume = whale_buy + whale_sell

        if whale_sell > 0:
            ratio = whale_buy / whale_sell
        else:
            ratio = 10.0 if whale_buy > 0 else 1.0

        if ratio > 1.3:
            sentiment = "BULLISH (accumulation)"
        elif ratio < 0.77:
            sentiment = "BEARISH (distribution)"
        else:
            sentiment = "NEUTRAL"

        # Count by size tier
        large_count = sum(
            1 for t in whale_trades if t.price * t.size >= self.large_whale_usd
        )
        mega_count = sum(
            1 for t in whale_trades if t.price * t.size >= self.mega_whale_usd
        )

        summary = f"""
Whale Activity Summary (5min window)
{"=" * 40}
Sentiment: {sentiment}
Buy/Sell Ratio: {ratio:.2f}

Volume:
  Buy:   ${whale_buy:>12,.0f}
  Sell:  ${whale_sell:>12,.0f}
  Total: ${total_volume:>12,.0f}

Whale Trades:
  Total:  {len(whale_trades):>6} (>$50k)
  Large:  {large_count:>6} (>$100k)
  Mega:   {mega_count:>6} (>$500k)
{"=" * 40}
"""
        return summary
