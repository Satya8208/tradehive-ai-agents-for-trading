"""
Signal Aggregator

Combines weighted signals from all data agents into a composite score.
Built with love by TradeHive
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig, SignalDirection
from src.agents.crypto_polymarket.models import MarketSignal, AggregatedSignal


class SignalAggregator:
    """
    Aggregates signals from data agents into a weighted composite.

    Weights (based on historical accuracy):
    - Liquidation: 60% (60-62% accuracy, primary signal)
    - Whale: 40% (70%+ accuracy, confirmation signal)

    The composite score ranges from -1.0 (very bearish) to +1.0 (very bullish).
    """

    def __init__(self, config: CryptoPolymarketConfig):
        self.config = config
        self.weights = {
            "liquidation": config.liquidation_weight,
            "whale": config.whale_weight,
        }

        # Verify weights sum to ~1.0
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Signal weights must sum to 1.0, got {total}")

    def aggregate(self, signals: Dict[str, MarketSignal]) -> AggregatedSignal:
        """
        Aggregate all signals into a weighted composite.

        Args:
            signals: Dict mapping agent names to their signals

        Returns:
            AggregatedSignal with composite score and direction
        """
        weighted_score = 0.0
        total_weight = 0.0
        valid_signals: List[MarketSignal] = []
        signal_breakdown: Dict[str, float] = {}

        for agent_name, signal in signals.items():
            # Handle error signals (they're exceptions, not MarketSignal)
            if isinstance(signal, Exception):
                continue

            # Get weight for this agent
            weight = self.weights.get(agent_name, 0.0)
            if weight == 0:
                continue

            # Convert direction to numeric (-1, 0, 1)
            direction_value = self._direction_to_numeric(signal.direction)

            # Calculate weighted contribution
            # Contribution = direction * strength * confidence * weight
            contribution = (
                direction_value * signal.strength * signal.confidence * weight
            )

            weighted_score += contribution
            total_weight += weight
            valid_signals.append(signal)
            signal_breakdown[agent_name] = contribution

        # Normalize to -1 to 1 range
        if total_weight > 0:
            composite_score = weighted_score / total_weight
        else:
            composite_score = 0.0

        # Determine overall direction based on composite score
        direction = self._score_to_direction(composite_score)

        # Find dominant signal (highest absolute contribution)
        dominant_signal = "none"
        if signal_breakdown:
            dominant_signal = max(
                signal_breakdown.keys(), key=lambda k: abs(signal_breakdown[k])
            )

        # Calculate overall confidence (weighted average of confidences)
        confidence = 0.0
        if valid_signals:
            total_conf_weight = 0.0
            for signal in valid_signals:
                weight = self.weights.get(signal.agent_name, 0.0)
                confidence += signal.confidence * weight
                total_conf_weight += weight
            if total_conf_weight > 0:
                confidence = confidence / total_conf_weight

        # Determine primary symbol from signals
        symbol = self._determine_symbol(valid_signals)

        return AggregatedSignal(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            direction=direction,
            composite_score=composite_score,
            confidence=confidence,
            signals=valid_signals,
            dominant_signal=dominant_signal,
            signal_breakdown=signal_breakdown,
        )

    def aggregate_for_symbol(
        self, signals: Dict[str, MarketSignal], symbol: str
    ) -> AggregatedSignal:
        """
        Aggregate signals for a specific symbol.

        Filters signals to only include those for the given symbol.

        Args:
            signals: Dict mapping agent names to their signals
            symbol: Symbol to filter for (BTC, ETH, or BOTH)

        Returns:
            AggregatedSignal for the specific symbol
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
            )

        result = self.aggregate(filtered)
        result.symbol = symbol  # Ensure correct symbol
        return result

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
        Convert composite score to direction.

        Uses thresholds to avoid noise:
        - Above 0.2: Bullish
        - Below -0.2: Bearish
        - Otherwise: Neutral
        """
        if score > 0.2:
            return SignalDirection.BULLISH
        elif score < -0.2:
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
        Get a human-readable summary of the aggregated signal.

        Args:
            aggregated: The aggregated signal

        Returns:
            Summary string
        """
        direction_emoji = {
            SignalDirection.BULLISH: "[BULL]",
            SignalDirection.BEARISH: "[BEAR]",
            SignalDirection.NEUTRAL: "[NEUTRAL]",
        }

        emoji = direction_emoji[aggregated.direction]
        score = aggregated.composite_score

        summary = f"{emoji} {aggregated.symbol}: {aggregated.direction.value.upper()}\n"
        summary += f"   Composite Score: {score:+.3f}\n"
        summary += f"   Confidence: {aggregated.confidence:.1%}\n"
        summary += f"   Dominant Signal: {aggregated.dominant_signal}\n"

        if aggregated.signal_breakdown:
            summary += "   Contributions:\n"
            for agent, contrib in sorted(
                aggregated.signal_breakdown.items(),
                key=lambda x: abs(x[1]),
                reverse=True,
            ):
                summary += f"      - {agent}: {contrib:+.3f}\n"

        return summary
