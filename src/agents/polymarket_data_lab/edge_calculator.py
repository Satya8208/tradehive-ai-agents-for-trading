"""
Edge Calculator & Kelly Position Sizing for Crypto Polymarket Agent

Calculates expected value and optimal bet sizes for prediction markets.

KEY CONCEPTS:
- Edge: Difference between estimated probability and market price
- Kelly Criterion: Optimal bet size to maximize geometric growth
- Risk-adjusted returns: Account for volatility and uncertainty
- Time decay: Signals lose predictive power closer to resolution

Formula:
Kelly Fraction = (p * b - q) / b
where:
- p = probability of winning (our estimate)
- q = probability of losing (1 - p)
- b = odds received (1 / market_price - 1)

Built with love by TradeHive
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import numpy as np
from scipy import stats
from termcolor import cprint

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig
from src.agents.crypto_polymarket.models import CryptoMarket, TradeDecision


class EdgeCalculator:
    """
    Calculates expected value and optimal position sizing for prediction markets.

    Methods:
    1. Calculate edge: Signal probability vs market price
    2. Kelly sizing: Optimal bet fraction
    3. Risk-adjusted sizing: Conservative fractional Kelly
    4. Time decay: Reduce edge as event approaches
    """

    def __init__(self, config: CryptoPolymarketConfig):
        """
        Initialize edge calculator.

        Args:
            config: Agent configuration with risk parameters
        """
        self.config = config
        self.kelly_fraction = config.kelly_fraction
        self.min_edge_threshold = config.min_edge_threshold
        self.max_position_percentage = config.max_position_percentage
        self.min_position_usd = config.min_position_usd

        # Time decay parameters
        # Edge decreases exponentially as event approaches resolution
        self.time_decay_half_life_hours = config.time_decay_half_life_hours
        self.time_decay_minimum = config.time_decay_minimum

        cprint("[OK] Edge Calculator initialized", "cyan")

    def calculate_edge(
        self,
        signal_probability: float,  # Our estimated probability (0-1)
        market_price: float,  # Current polymarket price (0-1)
        confidence_interval: float = 0.10,  # Uncertainty around estimate (±10%)
        hours_until_resolution: float = 24,  # Time to event resolution
    ) -> Dict[str, float]:
        """
        Calculate edge components for a trade opportunity.

        Args:
            signal_probability: Our estimated win probability (0-1)
            market_price: Current market price (0-1)
            confidence_interval: Uncertainty around estimate (±X%)
            hours_until_resolution: Hours until event resolves

        Returns:
            Dict with {
                "edge_percent": float,          # Edge as % of position
                "edge_confidence": float,       # Confidence in edge (0-1)
                "expected_value": float,        # EV per $1 bet
                "time_decay": float,             # Time decay factor (0-1)
                "probability_range": (low, high) # Range of possible true probabilities
            }
        """
        # Validate inputs
        if not (0 <= signal_probability <= 1):
            raise ValueError(
                f"signal_probability must be between 0 and 1, got {signal_probability}"
            )

        if not (0 <= market_price <= 1):
            raise ValueError(
                f"market_price must be between 0 and 1, got {market_price}"
            )

        # Calculate time decay factor
        # Edge decreases exponentially as event approaches
        time_decay = self._calculate_time_decay(hours_until_resolution)

        # Calculate probability range (confidence interval)
        prob_low = max(0.0, signal_probability - confidence_interval)
        prob_high = min(1.0, signal_probability + confidence_interval)

        # Conservative estimate: use lower bound of confidence interval if edge is positive
        conservative_prob = prob_low if signal_probability > market_price else prob_high

        # Calculate edge
        # Edge = (True Win Probability * Payout) - (Loss Probability * Loss Amount)
        # For YES bet at price $0.45: payout = $1.00, loss = $0.45
        # If true probability = 0.60: edge = (0.60 * 0.55) - (0.40 * 0.45) = 0.33 - 0.18 = 0.15

        win_probability = conservative_prob
        loss_probability = 1 - win_probability

        # Payout if win = (1 - market_price) because we pay $0.45 to win $1.00
        payout_if_win = 1 - market_price
        loss_if_wrong = market_price

        expected_value = (win_probability * payout_if_win) - (
            loss_probability * loss_if_wrong
        )

        # Edge as percentage
        edge_percent = (expected_value / market_price * 100) if market_price > 0 else 0

        # Edge confidence (lower when uncertainty high)
        edge_confidence = max(
            0.0, 1.0 - (confidence_interval * 2)
        )  # Wider CI = lower confidence
        edge_confidence *= time_decay  # Decay over time

        return {
            "edge_percent": edge_percent,
            "edge_confidence": edge_confidence,
            "expected_value": expected_value,
            "expected_value_ratio": expected_value / market_price
            if market_price > 0
            else 0,
            "time_decay": time_decay,
            "time_decay_factor": 1.0 - time_decay,
            "probability_range": (prob_low, prob_high),
            "conservative_probability": conservative_prob,
            "win_probability": win_probability,
            "loss_probability": loss_probability,
            "payout_if_win": payout_if_win,
            "loss_if_wrong": loss_if_wrong,
        }

    def calculate_kelly_fraction(
        self,
        edge_data: Dict[str, float],
        risk_factor: float = 1.0,  # Conservative: 0.25, Standard: 0.5, Aggressive: 1.0
        confidence_penalty: bool = True,
    ) -> Dict[str, float]:
        """
        Calculate Kelly Criterion position sizing.

        Kelly Formula: f* = (bp - q) / b
        where:
        - b = decimal odds - 1
        - p = probability of winning
        - q = probability of losing = 1 - p

        Args:
            edge_data: Output from calculate_edge()
            risk_factor: Conservative multiplier (1.0 = full Kelly, 0.5 = half Kelly, etc.)
            confidence_penalty: Reduce size based on confidence level

        Returns:
            Dict with {
                "kelly_fraction": float,        # Full Kelly fraction
                "fractional_kelly": float,      # Conservative fraction
                "bet_size_usd": float,          # Recommended bet in USD
                "expected_growth": float,       # Expected geometric growth
                "risk_of_ruin": float,          # Probability of significant loss
                "optimal_position": str,        # Recommended: "aggressive", "standard", "conservative"
            }
        """
        p = edge_data["win_probability"]  # Probability of winning
        q = edge_data["loss_probability"]  # Probability of losing
        b = edge_data["payout_if_win"] / edge_data["loss_if_wrong"]  # Odds

        # Calculate full Kelly fraction
        kelly_fraction = (b * p - q) / b if b > 0 else 0.0

        # Clamp between 0 and 1.0 (never risk more than 100% of bankroll)
        kelly_fraction = max(0.0, min(1.0, kelly_fraction))

        # Apply conservative risk factor (fractional Kelly)
        fractional_kelly = kelly_fraction * risk_factor

        # Apply confidence penalty (wider uncertainty = smaller position)
        if confidence_penalty:
            confidence_factor = edge_data["edge_confidence"]
            fractional_kelly *= confidence_factor

        # Calculate bet size in USD
        # Position sizing based on max exposure and current bankroll
        max_position = self.config.max_trade_size_usd
        bet_size_usd = fractional_kelly * max_position

        # Apply minimum position
        if bet_size_usd < self.config.min_position_usd:
            bet_size_usd = 0  # No trade if below minimum

        # Calculate expected geometric growth
        expected_growth_rate = (p * np.log(1 + fractional_kelly * b)) + (
            q * np.log(1 - fractional_kelly)
        )

        # Risk of ruin (simplified - probability of 50% drawdown)
        if kelly_fraction > 0.5:
            risk_of_ruin = q**2  # Higher Kelly = higher risk
        else:
            risk_of_ruin = q  # Lower Kelly = lower risk

        # Risk assessment
        if fractional_kelly > 0.5:
            risk_level = "aggressive"
        elif fractional_kelly > 0.25:
            risk_level = "standard"
        else:
            risk_level = "conservative"

        return {
            "kelly_fraction": kelly_fraction,
            "fractional_kelly": fractional_kelly,
            "bet_size_usd": bet_size_usd,
            "bet_percentage_of_max": bet_size_usd / max_position
            if max_position > 0
            else 0,
            "expected_growth_rate": expected_growth_rate,
            "risk_of_ruin": risk_of_ruin,
            "optimal_position": risk_level,
            "risk_level": risk_level,
            "edge_confidence": edge_data["edge_confidence"],
            "risk_reward_ratio": edge_data["payout_if_win"] / edge_data["loss_if_wrong"]
            if edge_data["loss_if_wrong"] > 0
            else 0,
        }

    def calculate_position_size(
        self,
        market: CryptoMarket,
        composite_score: float,  # From TimeframeController (-1 to 1)
        hours_until_resolution: float,
        bankroll_usd: float,  # Current available capital
    ) -> TradeDecision:
        """
        Calculate complete position sizing and generate TradeDecision.

        Args:
            market: Polymarket market data
            composite_score: Timeframe-weighted signal score (-1 to 1)
            hours_until_resolution: Hours until event resolves
            bankroll_usd: Available capital

        Returns:
            TradeDecision with side, size, and reasoning
        """
        # Convert composite score to probability estimate
        # Score of 0.5 = 75% probability, score of 0 = 50% probability
        base_probability = 0.5 + (composite_score * 0.25)

        # Clamp probability to realistic bounds
        estimated_probability = max(0.3, min(0.7, base_probability))

        # Calculate edge
        edge_data = self.calculate_edge(
            signal_probability=estimated_probability,
            market_price=market.current_price,
            confidence_interval=abs(composite_score)
            * 0.15,  # Wider CI for uncertain signals
            hours_until_resolution=hours_until_resolution,
        )

        # Check if edge is sufficient
        if edge_data["edge_percent"] < self.min_edge_threshold:
            return TradeDecision(
                market_id=market.market_id,
                side=TradeSide.NO_TRADE,
                size_usd=0.0,
                confidence=0.0,
                reasoning=f"Insufficient edge: {edge_data['edge_percent']:.1f}% < {self.min_edge_threshold}%",
                expected_value=0.0,
                edge_data=edge_data,
            )

        # Calculate Kelly sizing
        kelly_data = self.calculate_kelly_fraction(
            edge_data=edge_data,
            risk_factor=self.kelly_fraction,
            confidence_penalty=True,
        )

        # If Kelly says no position, return NO_TRADE
        if kelly_data["bet_size_usd"] <= 0:
            return TradeDecision(
                market_id=market.market_id,
                side=TradeSide.NO_TRADE,
                size_usd=0.0,
                confidence=kelly_data["edge_confidence"],
                reasoning=f"Kelly criterion suggests no position (edge confidence too low)",
                expected_value=edge_data["expected_value"],
                edge_data=edge_data,
            )

        # Determine trade side from composite score
        if composite_score > 0:
            side = TradeSide.YES
            side_reasoning = "YES (bullish signals)"
        else:
            side = TradeSide.NO
            side_reasoning = "NO (bearish signals)"

        # Cap position by max percentage of bankroll
        max_bankroll_pct = self.config.max_position_percentage / 100
        max_from_bankroll = bankroll_usd * max_bankroll_pct

        final_size = min(kelly_data["bet_size_usd"], max_from_bankroll)

        # Build reasoning
        reasoning = (
            f"Edge: {edge_data['edge_percent']:.1f}% | "
            f"EV: ${edge_data['expected_value']:.3f}/{edge_data['loss_if_wrong']:.3f} | "
            f"Kelly: {kelly_data['fractional_kelly']:.1%} | "
            f"Risk: {kelly_data['risk_level']} | "
            f"Side: {side_reasoning}"
        )

        return TradeDecision(
            market_id=market.market_id,
            side=side,
            size_usd=final_size,
            confidence=kelly_data["edge_confidence"],
            reasoning=reasoning,
            expected_value=edge_data["expected_value"] * final_size,
            edge_data=edge_data,
            kelly_data=kelly_data,
            time_decay_factor=edge_data["time_decay"],
        )

    def _calculate_time_decay(self, hours_until_resolution: float) -> float:
        """
        Calculate time decay factor for signal relevance.

        Signals become less predictive as event approaches resolution.
        Using exponential decay with configurable half-life.

        Args:
            hours_until_resolution: Hours until event resolves

        Returns:
            Decay factor (0 to 1, where 1 = no decay)
        """
        if hours_until_resolution <= 0:
            return self.config.time_decay_minimum

        half_life = self.config.time_decay_half_life_hours
        decay_exponent = -hours_until_resolution / half_life
        decay_factor = np.exp(decay_exponent)

        # Ensure minimum
        return max(self.config.time_decay_minimum, decay_factor)


if __name__ == "__main__":
    # Test the calculator
    print("\n[CALC] Testing Edge Calculator & Kelly Sizing")
    print("=" * 70)

    config = CryptoPolymarketConfig()
    calculator = EdgeCalculator(config)

    # Mock market data
    mock_market = CryptoMarket(
        market_id="test_market",
        title="Will BTC > $90k by Jan 30?",
        description="Test market",
        categories=["crypto", "price"],
        current_price=0.42,
        volume_24h=100000,
        liquidity=500000,
        best_bid=0.41,
        best_ask=0.43,
    )

    # Test 1: Strong bullish signal
    print("\n🔼 TEST 1: Strong Bullish Signal (composite = +0.65)")
    decision1 = calculator.calculate_position_size(
        market=mock_market,
        composite_score=0.65,
        hours_until_resolution=48,
        bankroll_usd=10000,
    )

    print(f"Decision: {decision1.side.value}")
    print(f"Size: ${decision1.size_usd:.0f}")
    print(f"Confidence: {decision1.confidence:.1%}")
    print(f"Reasoning: {decision1.reasoning[:80]}...")

    # Test 2: Strong bearish signal
    print("\n🔽 TEST 2: Strong Bearish Signal (composite = -0.70)")
    decision2 = calculator.calculate_position_size(
        market=mock_market,
        composite_score=-0.70,
        hours_until_resolution=24,
        bankroll_usd=10000,
    )

    print(f"Decision: {decision2.side.value}")
    print(f"Size: ${decision2.size_usd:.0f}")
    print(f"Confidence: {decision2.confidence:.1%}")

    # Test 3: Weak signal (no edge)
    print("\n[ANALYSIS]  TEST 3: Weak Signal (composite = +0.05)")
    decision3 = calculator.calculate_position_size(
        market=mock_market,
        composite_score=0.05,
        hours_until_resolution=48,
        bankroll_usd=10000,
    )

    print(f"Decision: {decision3.side.value}")
    print(f"Size: ${decision3.size_usd:.0f}")

    print("\n" + "=" * 70)
