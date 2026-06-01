"""
Signal Aggregator v2.1

Combines weighted signals from 5 data agents into a composite score.
Supports dynamic weight adjustment based on market regime.

Base Weights:
- Liquidation: 30% (most reliable in trending markets)
- Funding: 22% (excellent for mean reversion in ranging markets)
- Open Interest: 18% (best for trend confirmation)
- Volume: 15% (confirmation signal across all regimes)
- Order Book: 15% (real-time buying/selling pressure)

Built for TradeHive's v2.1 Crypto Polymarket Trading System
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig, SignalDirection
from src.agents.crypto_polymarket.models import MarketSignal, AggregatedSignal
from src.agents.crypto_polymarket.regime_detection import MarketRegime


class SignalAggregatorV2:
    """
    v2.1 Signal Aggregator with dynamic regime-based weighting.

    Handles 5 data agents with base weights that adapt based on market regime.
    """

    def __init__(self, config: CryptoPolymarketConfig):
        self.config = config

        # v2.1: 5-agent base weights (from config)
        self.base_weights = {
            "liquidation": config.base_liquidation_weight,  # 0.30
            "funding": config.base_funding_weight,  # 0.22
            "open_interest": config.base_oi_weight,  # 0.18
            "volume": config.base_volume_weight,  # 0.15
            "orderbook": config.base_orderbook_weight,  # 0.15
        }

        # Validate total = 1.0 (with tolerance)
        total = sum(self.base_weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"v2.0 base weights must sum to 1.0, got {total:.3f}")

        # Cache regime multipliers for performance
        self.regime_multipliers = config.regime_multipliers

        print("[OK] SignalAggregator v2.1 initialized")
        print(f"   Base weights: {self.base_weights}")

    def aggregate(
        self, signals: Dict[str, MarketSignal], regime: Optional[MarketRegime] = None
    ) -> AggregatedSignal:
        """
        v2.1: Aggregate 5-agent signals with optional regime-based weighting.

        Args:
            signals: Dict mapping agent names to their MarketSignal
            regime: Optional market regime for dynamic weighting

        Returns:
            AggregatedSignal with composite score and detailed breakdown
        """
        if not signals:
            return AggregatedSignal(
                symbol="BOTH",
                timestamp=datetime.utcnow(),
                direction=SignalDirection.NEUTRAL,
                composite_score=0.0,
                confidence=0.0,
                signals=[],
                dominant_signal="none",
                signal_breakdown={},
                regime=regime.value if regime else "none",
                weights_used=self.base_weights,
            )

        # Determine weights (static base or dynamic by regime)
        weights = self._calculate_dynamic_weights(signals, regime)

        # Calculate weighted composite score
        composite_score = 0.0
        total_weight_used = 0.0
        weighted_confidence = 0.0
        signal_breakdown: Dict[str, float] = {}
        valid_signals: List[MarketSignal] = []

        for agent_name, signal in signals.items():
            # Skip errors
            if isinstance(signal, Exception):
                continue

            # Extract base agent name from composite keys (e.g., "liquidation:15m" -> "liquidation")
            base_agent_name = agent_name.split(":")[0] if ":" in agent_name else agent_name

            # Get weight for this agent (use base name for lookup)
            weight = weights.get(base_agent_name, 0.0)
            if weight <= 0.0:
                continue

            # Convert direction to numeric (-1, 0, 1)
            direction_value = self._direction_to_numeric(signal.direction)

            # Calculate weighted contribution
            # Contribution = direction * strength * confidence * weight
            contribution = (
                direction_value * signal.strength * signal.confidence * weight
            )

            composite_score += contribution
            weighted_confidence += signal.confidence * weight
            total_weight_used += weight
            valid_signals.append(signal)
            signal_breakdown[agent_name] = contribution

        # Normalize composite score
        if total_weight_used > 0:
            composite_score /= total_weight_used
            weighted_confidence /= total_weight_used

        # Determine direction based on score and threshold
        direction = self._score_to_direction(composite_score)

        # Find dominant signal (highest absolute contribution)
        dominant_signal = "none"
        if signal_breakdown:
            dominant_signal = max(
                signal_breakdown.keys(), key=lambda k: abs(signal_breakdown[k])
            )

        # Determine primary symbol
        symbol = self._determine_symbol(valid_signals)

        return AggregatedSignal(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            direction=direction,
            composite_score=composite_score,
            confidence=min(weighted_confidence, 1.0),
            signals=valid_signals,
            dominant_signal=dominant_signal,
            signal_breakdown=signal_breakdown,
            regime=regime.value if regime else "none",
            weights_used=weights,
        )

    def _calculate_dynamic_weights(
        self, signals: Dict[str, MarketSignal], regime: Optional[MarketRegime]
    ) -> Dict[str, float]:
        """
        Calculate weights (base weights or regime-adjusted).

        If regime is provided and dynamic weighting is enabled,
        adjust weights using regime multipliers.
        """
        # Start with base weights
        weights = self.base_weights.copy()

        # Apply regime-based adjustments if enabled
        if regime and self.config.enable_dynamic_weights:
            regime_name = regime.value
            multipliers = self.regime_multipliers.get(regime_name, {})

            for agent, base_weight in weights.items():
                if agent in multipliers:
                    weights[agent] = base_weight * multipliers[agent]

        # Filter to only include agents that provided signals
        # Handle composite keys (e.g., "liquidation:15m" -> "liquidation")
        available_base_agents = set()
        for k, v in signals.items():
            if not isinstance(v, Exception):
                base_name = k.split(":")[0] if ":" in k else k
                available_base_agents.add(base_name)

        weights = {
            agent: weight
            for agent, weight in weights.items()
            if agent in available_base_agents
        }

        # Normalize to ensure sum = 1.0
        total = sum(weights.values())
        if total > 0:
            weights = {agent: weight / total for agent, weight in weights.items()}

        return weights

    def aggregate_for_symbol(
        self,
        signals: Dict[str, MarketSignal],
        symbol: str,
        regime: Optional[MarketRegime] = None,
    ) -> AggregatedSignal:
        """
        v2.0: Aggregate signals for a specific symbol.

        Filters signals to only include those for the given symbol,
        then aggregates with regime-based weighting.
        """
        # Filter signals for this symbol
        filtered = {}
        for agent_name, signal in signals.items():
            if isinstance(signal, Exception):
                continue
            if signal.symbol == symbol or signal.symbol == "BOTH":
                filtered[agent_name] = signal

        if not filtered:
            # Return neutral signal if no matching signals
            return AggregatedSignal(
                symbol=symbol,
                timestamp=datetime.utcnow(),
                direction=SignalDirection.NEUTRAL,
                composite_score=0.0,
                confidence=0.0,
                signals=[],
                dominant_signal="none",
                signal_breakdown={},
                regime=regime.value if regime else "none",
                weights_used=self.base_weights,
            )

        result = self.aggregate(filtered, regime)
        result.symbol = symbol
        return result

    def aggregate_multi_timeframe(
        self,
        timeframe_signals: Dict[str, Dict[str, MarketSignal]],
        regime: Optional[MarketRegime] = None,
    ) -> AggregatedSignal:
        """
        v2.0: Aggregate signals across multiple timeframes.

        Args:
            timeframe_signals: Dict of timeframe -> agent_signals
            regime: Optional market regime

        Returns:
            Single AggregatedSignal combining all timeframes
        """
        # Flatten all signals with timeframe weighting
        all_signals = {}
        signal_metadata = []  # Track which signals came from where

        for timeframe, agent_signals in timeframe_signals.items():
            timeframe_weight = self.config.timeframe_weights.get(timeframe, 1.0)

            for agent_name, signal in agent_signals.items():
                if isinstance(signal, Exception):
                    continue

                # Create composite key to avoid collisions
                composite_key = f"{agent_name}:{timeframe}"
                all_signals[composite_key] = signal

                # Store metadata for tracking
                signal_metadata.append(
                    {
                        "key": composite_key,
                        "agent": agent_name,
                        "timeframe": timeframe,
                        "weight": timeframe_weight,
                    }
                )

        # Aggregate all signals
        if not all_signals:
            return AggregatedSignal(
                symbol="BOTH",
                timestamp=datetime.utcnow(),
                direction=SignalDirection.NEUTRAL,
                composite_score=0.0,
                confidence=0.0,
                signals=[],
                dominant_signal="none",
                signal_breakdown={},
                regime=regime.value if regime else "none",
                weights_used=self.base_weights,
            )

        return self.aggregate(all_signals, regime)

    def _direction_to_numeric(self, direction: SignalDirection) -> float:
        """Convert SignalDirection to numeric value."""
        if direction == SignalDirection.BULLISH:
            return 1.0
        elif direction == SignalDirection.BEARISH:
            return -1.0
        else:
            return 0.0

    def _score_to_direction(self, score: float) -> SignalDirection:
        """
        Convert composite score to direction with threshold to avoid noise.

        Thresholds:
        - Above 0.15: Bullish
        - Below -0.15: Bearish
        - Otherwise: Neutral
        """
        if score > 0.15:
            return SignalDirection.BULLISH
        elif score < -0.15:
            return SignalDirection.BEARISH
        else:
            return SignalDirection.NEUTRAL

    def _determine_symbol(self, signals: List[MarketSignal]) -> str:
        """
        Determine the primary symbol from a list of signals.

        If all signals agree on a symbol, use that.
        If mixed, prefer BTC over ETH, and use BOTH as fallback.
        """
        if not signals:
            return "BOTH"

        symbols = set(s.symbol for s in signals)

        if len(symbols) == 1:
            return symbols.pop()

        # Multiple symbols - prioritize
        if "BTC" in symbols:
            return "BTC"
        elif "ETH" in symbols:
            return "ETH"
        else:
            return "BOTH"

    def get_signal_summary(self, aggregated: AggregatedSignal) -> str:
        """
        Get human-readable summary of aggregated signal.
        """
        direction_labels = {
            SignalDirection.BULLISH: "[BULLISH]",
            SignalDirection.BEARISH: "[BEARISH]",
            SignalDirection.NEUTRAL: "[NEUTRAL]",
        }

        label = direction_labels[aggregated.direction]
        score = aggregated.composite_score

        summary = f"{label} {aggregated.symbol}: {aggregated.direction.value.upper()}\n"
        summary += f"   Score: {score:+.3f} | Confidence: {aggregated.confidence:.1%}\n"
        summary += (
            f"   Regime: {aggregated.regime} | Dominant: {aggregated.dominant_signal}\n"
        )

        if aggregated.signal_breakdown:
            summary += "   Agent Contributions:\n"
            for agent, contrib in sorted(
                aggregated.signal_breakdown.items(),
                key=lambda x: abs(x[1]),
                reverse=True,
            ):
                # If multi-timeframe, show timeframe too
                agent_name = agent.split(":")[0] if ":" in agent else agent
                summary += f"      - {agent_name:15s}: {contrib:+.3f}\n"

        # Show weights if dynamic
        if aggregated.weights_used != self.base_weights:
            summary += "   Weights (dynamic):\n"
            for agent, weight in aggregated.weights_used.items():
                agent_name = agent.split(":")[0] if ":" in agent else agent
                summary += f"      - {agent_name:15s}: {weight:.1%}\n"

        return summary


# Backward compatibility alias for v1.0 code
SignalAggregator = SignalAggregatorV2
