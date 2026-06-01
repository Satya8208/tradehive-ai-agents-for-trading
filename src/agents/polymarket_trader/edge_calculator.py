"""
Edge Calculator for Polymarket CLI Agents

Kelly criterion position sizing and edge calculation.
Adapted from src/agents/crypto_polymarket/edge_calculator.py
"""

import math
from typing import Optional

from termcolor import cprint

from .config import PolymarketCLIConfig, get_config
from .models import EdgeResult


class CLIEdgeCalculator:
    """
    Edge calculation and Kelly position sizing for prediction market trading.

    Input: swarm probability estimate + market price
    Output: edge percentage, expected value, Kelly-optimal position size
    """

    def __init__(self, config: Optional[PolymarketCLIConfig] = None):
        self.config = config or get_config()

    def calculate_edge(self, estimated_probability: float,
                       market_price: float,
                       confidence: float = 0.8,
                       hours_until_resolution: float = 24.0,
                       available_capital: Optional[float] = None) -> EdgeResult:
        """
        Calculate edge between our probability estimate and market price.

        For YES bets: edge = (estimated_prob * payout) - market_price
        For NO bets: edge = ((1 - estimated_prob) * payout) - (1 - market_price)

        Uses lower bound of confidence interval for conservative estimate.
        """
        # Clamp inputs
        estimated_probability = max(0.01, min(0.99, estimated_probability))
        market_price = max(0.01, min(0.99, market_price))
        confidence = max(0.1, min(1.0, confidence))

        # Apply time decay
        time_decay = self._calculate_time_decay(hours_until_resolution)

        # Conservative estimate: use lower bound of confidence interval
        # Width of interval shrinks with confidence
        # 0.15 multiplier is more conservative — requires larger edge to trigger
        interval_half = (1 - confidence) * 0.15
        conservative_prob = estimated_probability - interval_half

        # Apply time decay to our probability edge (not the raw probability)
        prob_diff = conservative_prob - market_price
        decayed_prob = market_price + (prob_diff * time_decay)
        decayed_prob = max(0.01, min(0.99, decayed_prob))

        # Determine side and calculate edge
        # NOTE: market_price must always be YES price. Calculator determines direction.
        # Edge is absolute probability difference (not relative), capped at 100%
        if decayed_prob > market_price:
            # YES bet: we think YES is more likely than market implies
            recommended_side = "YES"
            side_price = market_price
            win_prob = decayed_prob
            ev = win_prob * (1.0 - side_price) - (1 - win_prob) * side_price
            edge_pct = min((decayed_prob - market_price) * 100, 100.0)
            # Market disagreement discount: if we say YES but market says <20%, be cautious
            if market_price < 0.20 and edge_pct > 30:
                edge_pct *= 0.5  # Halve edge when going against strong market NO
        else:
            # NO bet: we think NO is more likely
            recommended_side = "NO"
            side_price = 1.0 - market_price
            win_prob = 1.0 - decayed_prob
            ev = win_prob * (1.0 - side_price) - (1 - win_prob) * side_price
            edge_pct = min((market_price - decayed_prob) * 100, 100.0)
            # Market disagreement discount: if we say NO but market says >80%, be cautious
            if market_price > 0.80 and edge_pct > 30:
                edge_pct *= 0.5  # Halve edge when going against strong market YES

        # Kelly fraction
        if side_price > 0 and side_price < 1:
            b = (1.0 / side_price) - 1.0  # Decimal odds - 1
            q = 1.0 - win_prob
            kelly = (b * win_prob - q) / b if b > 0 else 0
            kelly = max(0, kelly)
        else:
            kelly = 0

        # Apply fractional Kelly and confidence penalty
        fractional_kelly = kelly * self.config.kelly_fraction
        confidence_penalty = confidence  # Linear penalty — low confidence gets punished harder
        adjusted_kelly = fractional_kelly * confidence_penalty

        # Calculate recommended size using available capital (not max exposure)
        bankroll = available_capital if available_capital is not None else self.config.max_total_exposure_usd
        raw_size = bankroll * adjusted_kelly
        recommended_size = min(raw_size, self.config.max_position_usd)
        min_pos = getattr(self.config, 'min_position_usd', 5.0)
        if 0 < recommended_size < min_pos:
            # For small bankrolls: if edge and confidence are strong enough,
            # trade at minimum size instead of skipping entirely
            if edge_pct >= self.config.min_edge_threshold and confidence >= self.config.min_edge_confidence:
                recommended_size = min_pos
            else:
                recommended_size = 0  # Too small and edge not convincing
        recommended_size = max(0, recommended_size)

        return EdgeResult(
            edge_percent=edge_pct,
            expected_value=ev,
            win_probability=win_prob,
            market_price=market_price,
            kelly_fraction=kelly,
            recommended_size_usd=recommended_size,
            time_decay_factor=time_decay,
            confidence=confidence,
            recommended_side=recommended_side,
        )

    def should_trade(self, edge: EdgeResult) -> bool:
        """Check if edge meets minimum thresholds."""
        if edge.edge_percent < self.config.min_edge_threshold:
            return False
        if edge.confidence < self.config.min_edge_confidence:
            return False
        if edge.recommended_size_usd <= 0:
            return False
        if edge.expected_value <= 0:
            return False
        # Abstain when our estimate is too close to market price (likely noise, not real edge)
        raw_gap = abs(edge.win_probability - edge.market_price)
        if raw_gap < 0.05:
            return False
        return True

    def _calculate_time_decay(self, hours: float) -> float:
        """
        INVERTED for prediction markets: near resolution = MORE reliable signal.

        Near resolution means less time for price reversals, so our edge is
        MORE reliable (not less). Far-out markets are more uncertain.

        Returns 1.0 at <=1h, drops fast to floor at >=24h.
        Weekly markets (>24h) get heavy penalty — historical data shows they lose.
        """
        if hours <= 0:
            return self.config.time_decay_minimum

        if hours <= 1:
            return 1.0  # Near resolution — signal is very reliable
        elif hours >= 24:
            return self.config.time_decay_minimum  # Daily+ markets — very uncertain
        else:
            # Steeper decay: 1.0 at 1h to minimum at 24h (was 48h)
            return 1.0 - (1.0 - self.config.time_decay_minimum) * ((hours - 1) / 23.0)

    def format_edge_summary(self, edge: EdgeResult) -> str:
        """Format edge result as readable string."""
        return (
            f"Side={edge.recommended_side} | Edge={edge.edge_percent:+.1f}% | "
            f"EV=${edge.expected_value:+.4f} | "
            f"Kelly={edge.kelly_fraction:.3f} | "
            f"Size=${edge.recommended_size_usd:.2f} | "
            f"Decay={edge.time_decay_factor:.2f}"
        )


if __name__ == "__main__":
    calc = CLIEdgeCalculator()

    # Example: Swarm says 65% probability, market prices YES at 50%
    print("Example 1: Strong edge (65% vs 50%)")
    edge = calc.calculate_edge(
        estimated_probability=0.65,
        market_price=0.50,
        confidence=0.80,
        hours_until_resolution=12.0
    )
    print(f"  {calc.format_edge_summary(edge)}")
    print(f"  Should trade: {calc.should_trade(edge)}")

    # Example: Weak edge (55% vs 50%)
    print("\nExample 2: Weak edge (55% vs 50%)")
    edge2 = calc.calculate_edge(
        estimated_probability=0.55,
        market_price=0.50,
        confidence=0.60,
        hours_until_resolution=12.0
    )
    print(f"  {calc.format_edge_summary(edge2)}")
    print(f"  Should trade: {calc.should_trade(edge2)}")

    # Example: NO side edge (30% vs 50%)
    print("\nExample 3: NO side (30% vs 50%)")
    edge3 = calc.calculate_edge(
        estimated_probability=0.30,
        market_price=0.50,
        confidence=0.85,
        hours_until_resolution=48.0
    )
    print(f"  {calc.format_edge_summary(edge3)}")
    print(f"  Should trade: {calc.should_trade(edge3)}")
