"""
Regime Detection Engine for Crypto Polymarket Agent

Detects market conditions to adapt signal interpretation and weights.
Different strategies work in different regimes - this ensures optimal
performance across all market conditions.

Regimes:
- LOW_VOL: Range-bound, consolidation (mean reversion works)
- HIGH_VOL: Breakout, high volatility (trend following works)
- TRENDING: Clear directional trend (momentum works)
- RANGING: No clear direction (contrarian works)

Built with love by TradeHive
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime
import numpy as np
from termcolor import cprint

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig, SignalDirection
from src.data.connectors.unified_pipeline import UnifiedDataPipeline


from enum import Enum, auto


class MarketRegime(str, Enum):
    """Market regime classification"""

    LOW_VOL = "low_vol"  # Low volatility, consolidation
    HIGH_VOL = "high_vol"  # High volatility, breakout
    TRENDING = "trending"  # Clear directional trend
    RANGING = "ranging"  # No clear direction, mean reversion


class RegimeDetectionEngine:
    """
    Detects current market regime based on multiple indicators.

    Regime influences:
    1. Signal weights (which agents to trust more)
    2. Signal interpretation (continuation vs mean reversion)
    3. Position sizing (larger in trending, smaller in ranging)
    4. Timeframe selection (faster signals in high vol)
    """

    def __init__(
        self,
        config: CryptoPolymarketConfig,
        pipeline: UnifiedDataPipeline,
        atr_period: int = 14,
        adx_period: int = 14,
        bb_period: int = 20,
    ):
        """
        Initialize regime detection engine.

        Args:
            config: Agent configuration
            pipeline: Unified data pipeline
            atr_period: Period for Average True Range
            adx_period: Period for ADX (trend strength)
            bb_period: Period for Bollinger Bands
        """
        self.config = config
        self.pipeline = pipeline
        self.atr_period = atr_period
        self.adx_period = adx_period
        self.bb_period = bb_period

        # Regime state cache
        self.current_regime: Optional[str] = None
        self.regime_start_time: Optional[datetime] = None
        self.regime_history: list = []

        # Technical indicator buffers
        self.price_history: list = []
        self.atr_history: list = []
        self.adx_history: list = []
        self.bb_width_history: list = []

        cprint("[OK] Regime Detection Engine initialized", "cyan")

    async def detect_regime(self, symbol: str = "BTC") -> Dict[str, Any]:
        """
        Detect current market regime for a symbol.

        Combines multiple indicators:
        1. Volatility (ATR as % of price)
        2. Trend strength (ADX)
        3. Bollinger Band width (contraction/expansion)
        4. Volume profile (high/low volume environment)

        Args:
            symbol: Coin symbol (BTC, ETH)

        Returns:
            Dict with {
                "regime": str ("low_vol", "high_vol", "trending", "ranging"),
                "confidence": float,
                "indicators": Dict,
                "since": datetime
            }
        """
        indicators = await self._calculate_regime_indicators(symbol)

        if not indicators:
            return {
                "regime": "ranging",  # Default safe regime
                "confidence": 0.3,
                "indicators": {},
                "since": datetime.utcnow(),
                "reasoning": "Insufficient data for regime detection",
            }

        # Extract key metrics
        volatility_pct = indicators["volatility_pct"]
        adx = indicators["adx"]
        bb_width_pct = indicators["bb_width_pct"]
        volume_velocity = indicators["volume_velocity"]

        # REGIME DETECTION LOGIC

        # 1. HIGH VOLATILITY REGIME
        if volatility_pct > self.config.vol_high_threshold:
            # High volatility - check if trending or just volatile
            if adx > self.config.adx_trend_threshold:
                regime = "high_vol_trending"
                reasoning = f"High volatility ({volatility_pct:.2f}%) AND strong trend (ADX {adx:.1f}) = trending breakout"
            else:
                regime = "high_vol_choppy"
                reasoning = f"High volatility ({volatility_pct:.2f}%) but weak trend (ADX {adx:.1f}) = choppy volatility"

            confidence = 0.85

        # 2. LOW VOLATILITY REGIME
        elif volatility_pct < self.config.vol_low_threshold:
            regime = "low_vol"
            reasoning = (
                f"Low volatility ({volatility_pct:.2f}%) = consolidation/range-bound"
            )
            confidence = 0.75

        # 3. TRENDING REGIME (normal volatility but clear direction)
        elif adx > self.config.adx_strong_threshold:
            regime = "trending"
            reasoning = f"Strong trend (ADX {adx:.1f}) = directional market"
            confidence = 0.80

        # 4. RANGING REGIME (normal volatility, no clear trend)
        else:
            regime = "ranging"
            reasoning = f"Weak trend (ADX {adx:.1f}) with normal volatility = ranging/mean-reverting"
            confidence = 0.70

        # Store regime
        prev_regime = self.current_regime
        self.current_regime = regime

        if prev_regime != regime:
            self.regime_start_time = datetime.utcnow()

        # Log to history
        self.regime_history.append(
            {
                "timestamp": datetime.utcnow(),
                "regime": regime,
                "confidence": confidence,
                "indicators": indicators,
            }
        )

        # Keep only last 100 entries
        if len(self.regime_history) > 100:
            self.regime_history = self.regime_history[-100:]

        cprint(
            f"[CRYSTAL] Regime: {regime:20} | Confidence: {confidence:.1%} | "
            f"Vol: {volatility_pct:.2f}% | ADX: {adx:.1f}",
            "white",
        )

        return {
            "regime": regime,
            "confidence": confidence,
            "indicators": indicators,
            "since": self.regime_start_time,
            "reasoning": reasoning,
        }

    async def _calculate_regime_indicators(
        self, symbol: str
    ) -> Optional[Dict[str, float]]:
        """
        Calculate technical indicators for regime detection.

        Args:
            symbol: Coin symbol

        Returns:
            Dict with indicator values or None if insufficient data
        """
        try:
            # Get recent price data
            # Note: Would need OHLCV data in practice
            # For now, use order book mid prices
            book = self.pipeline.get_order_book(symbol, exchange="hyperliquid")

            if not book:
                return None

            current_price = (
                (book.best_bid() + book.best_ask()) / 2
                if (book.best_bid() and book.best_ask())
                else 0
            )

            if current_price == 0:
                return None

            # Get volume data
            volume_metrics = self.pipeline.get_volume_metrics(
                symbol, seconds=3600
            )  # 1 hour

            # Calculate ATR (simplified - would need OHLCV)
            # For now, use order book spread as volatility proxy
            spread = book.spread() or 0
            spread_pct = (spread / current_price * 100) if current_price > 0 else 0

            # Calculate ADX (would need price history)
            # For now, use simplified trend strength based on volume imbalance
            buy_sell_ratio = (
                volume_metrics.get("buy_sell_ratio", 1.0) if volume_metrics else 1.0
            )
            adx = min(abs((buy_sell_ratio - 1) * 10), 40)  # Scale to ADX range (0-40)

            # Bollinger Band width (simplified)
            bb_width_pct = spread_pct * 2  # Rough approximation

            # Volume velocity (USD per second)
            volume_velocity = (
                volume_metrics.get("volume_velocity", 0) if volume_metrics else 0
            )

            return {
                "volatility_pct": spread_pct,  # Simplified
                "adx": adx,  # Simplified
                "bb_width_pct": bb_width_pct,
                "volume_velocity": volume_velocity,
                "current_price": current_price,
                "spread_usd": spread,
            }

        except Exception as e:
            cprint(f"[WARN]  Error calculating indicators: {e}", "yellow")
            return None

    def get_signal_weight_adjustments(self, regime: Dict[str, Any]) -> Dict[str, float]:
        """
        Get signal weight multipliers for current regime.

        Args:
            regime: Regime dict from detect_regime()

        Returns:
            Dict mapping signal_name to weight multiplier (1.0 = normal)
        """
        regime_name = regime["regime"]

        # Get base multipliers from config
        if regime_name in self.config.regime_multipliers:
            return self.config.regime_multipliers[regime_name]

        # Default neutral regime
        return {
            "liquidation": 1.0,
            "funding": 1.0,
            "open_interest": 1.0,
            "volume": 1.0,
        }

    def get_recommended_position_multiplier(self, regime: Dict[str, Any]) -> float:
        """
        Get position size multiplier for current regime.

        Args:
            regime: Regime dict from detect_regime()

        Returns:
            Multiplier (1.0 = standard size, <1.0 = smaller, >1.0 = larger)
        """
        regime_name = regime["regime"]
        confidence = regime["confidence"]

        # Base multipliers by regime
        base_multipliers = {
            "low_vol": 0.6,  # Smaller positions in chop
            "high_vol_choppy": 0.8,  # Cautious in chop
            "high_vol_trending": 1.4,  # Larger in trending volatility
            "trending": 1.3,  # Larger in clear trends
            "ranging": 0.7,  # Smaller in ranges
        }

        base = base_multipliers.get(regime_name, 1.0)

        # Adjust by confidence
        confidence_factor = confidence / 0.75  # Normalize to 1.0

        return base * confidence_factor

    def get_regime_history_summary(self, last_n: int = 10) -> str:
        """
        Get summary of recent regime changes.

        Args:
            last_n: Number of recent regime changes to show

        Returns:
            Formatted string summary
        """
        if not self.regime_history:
            return "No regime history available"

        recent = self.regime_history[-last_n:]

        summary = "\n[CHART_UP] Recent Regime History:\n"
        summary += "=" * 60 + "\n"

        for entry in recent:
            timestamp = entry["timestamp"].strftime("%H:%M:%S")
            regime = entry["regime"][:20]  # Truncate for display
            confidence = entry["confidence"]
            vol = entry["indicators"].get("volatility_pct", 0)

            summary += f"{timestamp} | {regime:20} | Conf: {confidence:.1%} | Vol: {vol:.2f}%\n"

        # Show most common regime
        from collections import Counter

        regimes = [entry["regime"] for entry in recent]
        most_common = Counter(regimes).most_common(1)

        if most_common:
            regime, count = most_common[0]
            summary += f"\nMost Common: {regime} ({count}/{len(recent)} times)\n"

        summary += "=" * 60 + "\n"

        return summary

    async def detect_current_regime(self, symbol: str = "BTC") -> MarketRegime:
        """
        v2.0: Detect current regime and return MarketRegime enum.

        Wraps detect_regime() and converts string result to MarketRegime enum.

        Args:
            symbol: Coin symbol (BTC, ETH)

        Returns:
            MarketRegime enum value
        """
        regime_data = await self.detect_regime(symbol)
        regime_str = regime_data["regime"]

        # Map string regimes to enum
        if "high_vol" in regime_str:
            return MarketRegime.HIGH_VOL
        elif regime_str == "low_vol":
            return MarketRegime.LOW_VOL
        elif regime_str == "trending":
            return MarketRegime.TRENDING
        elif regime_str == "ranging":
            return MarketRegime.RANGING
        else:
            # Default fallback
            return MarketRegime.RANGING


if __name__ == "__main__":
    import asyncio

    async def test_regime_detection():
        print("\n[CRYSTAL] Testing Regime Detection Engine")
        print("=" * 60)

        config = CryptoPolymarketConfig()
        pipeline = UnifiedDataPipeline()

        engine = RegimeDetectionEngine(config, pipeline)

        try:
            await pipeline.start()

            # Let it collect some data
            await asyncio.sleep(10)

            # Detect regime
            regime = await engine.detect_regime("BTC")

            print(f"\nCurrent Regime: {regime['regime']}")
            print(f"Confidence: {regime['confidence']:.1%}")
            print(f"Reasoning: {regime['reasoning']}")
            print(f"\nIndicators:")
            for key, value in regime["indicators"].items():
                print(f"  - {key}: {value}")

            # Get weight adjustments
            adjustments = engine.get_signal_weight_adjustments(regime)
            print(f"\nSignal Weight Adjustments:")
            for signal, multiplier in adjustments.items():
                print(f"  - {signal:15}: {multiplier:.2f}x")

            # Get position multiplier
            position_multiplier = engine.get_recommended_position_multiplier(regime)
            print(f"\nPosition Size Multiplier: {position_multiplier:.2f}x")

        except Exception as e:
            print(f"Error: {e}")
            import traceback

            traceback.print_exc()
        finally:
            await pipeline.stop()

        print("\n" + "=" * 60)

    asyncio.run(test_regime_detection())
