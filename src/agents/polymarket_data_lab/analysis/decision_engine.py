"""
Decision Engine

Makes final trade decisions based on signals and swarm consensus.
Implements risk checks and position sizing.

Built with love by TradeHive
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple
from termcolor import cprint

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.config import CryptoPolymarketConfig, SignalDirection
from src.agents.crypto_polymarket.models import (
    AggregatedSignal,
    CryptoMarket,
    SwarmAnalysisResult,
    TradeDecision,
)
from src.agents.crypto_polymarket.market.position_tracker import PositionTracker


class DecisionEngine:
    """
    Makes final trading decisions.

    Decision factors:
    1. Signal strength and direction
    2. Swarm consensus and confidence
    3. Market liquidity and pricing
    4. Risk limits and current exposure

    All criteria must pass for a trade to execute.
    """

    def __init__(self, config: CryptoPolymarketConfig):
        self.config = config
        self.position_tracker = PositionTracker(config)

    def make_decision(
        self,
        signal: AggregatedSignal,
        market: CryptoMarket,
        swarm_result: SwarmAnalysisResult,
    ) -> TradeDecision:
        """
        Make a trade decision based on all inputs.

        Args:
            signal: Aggregated signal from data agents
            market: Market to potentially trade
            swarm_result: AI swarm consensus result

        Returns:
            TradeDecision with trade parameters or rejection reason
        """
        # Run all checks
        checks = [
            self._check_signal_strength(signal),
            self._check_swarm_consensus(swarm_result),
            self._check_market_liquidity(market),
            self._check_time_remaining(market),
            self._check_spread(market),
            self._check_price_attractiveness(market, swarm_result),
            self._check_risk_limits(market),
            self._check_signal_swarm_alignment(signal, market, swarm_result),
        ]

        # All checks must pass
        for passed, reason in checks:
            if not passed:
                return TradeDecision(
                    market_id=market.market_id,
                    timestamp=datetime.utcnow(),
                    should_trade=False,
                    side="",
                    size_usd=0.0,
                    confidence=0.0,
                    reason=reason,
                    signal_score=signal.composite_score,
                    swarm_consensus=swarm_result.consensus_prediction,
                    swarm_confidence=swarm_result.consensus_confidence,
                )

        # Determine trade parameters
        side = self._determine_side(signal, market, swarm_result)
        size_usd = self._calculate_position_size(signal, swarm_result, market)
        confidence = self._calculate_overall_confidence(signal, swarm_result)

        return TradeDecision(
            market_id=market.market_id,
            timestamp=datetime.utcnow(),
            should_trade=True,
            side=side,
            size_usd=size_usd,
            confidence=confidence,
            reason=f"All checks passed - {side} with {confidence:.0%} confidence",
            signal_score=signal.composite_score,
            swarm_consensus=swarm_result.consensus_prediction,
            swarm_confidence=swarm_result.consensus_confidence,
        )

    def _check_signal_strength(self, signal: AggregatedSignal) -> Tuple[bool, str]:
        """
        Check if signal is strong enough to trade.

        Criteria:
        - Non-neutral direction
        - Minimum composite score threshold (from config)
        """
        if signal.direction == SignalDirection.NEUTRAL:
            return (False, "Signal direction is NEUTRAL - no clear trend")

        min_score = self.config.min_signal_score
        if abs(signal.composite_score) < min_score:
            return (
                False,
                f"Signal score {signal.composite_score:+.3f} below minimum {min_score}",
            )

        return (True, "Signal strength OK")

    def _check_swarm_consensus(
        self, swarm_result: SwarmAnalysisResult
    ) -> Tuple[bool, str]:
        """
        Check if swarm has sufficient consensus.

        Criteria:
        - Not ABSTAIN
        - Minimum confidence threshold (from config)
        - Minimum agreement ratio (from config)
        """
        if swarm_result.consensus_prediction == "ABSTAIN":
            return (False, "Swarm consensus is ABSTAIN - no clear agreement")

        if swarm_result.consensus_confidence < self.config.min_confidence_threshold:
            return (
                False,
                f"Swarm confidence {swarm_result.consensus_confidence:.1%} below minimum {self.config.min_confidence_threshold:.1%}",
            )

        if swarm_result.agreement_ratio < self.config.min_swarm_agreement:
            return (
                False,
                f"Swarm agreement {swarm_result.agreement_ratio:.1%} below minimum {self.config.min_swarm_agreement:.1%}",
            )

        return (True, "Swarm consensus OK")

    def _check_market_liquidity(self, market: CryptoMarket) -> Tuple[bool, str]:
        """Check if market has sufficient liquidity."""
        if market.liquidity < self.config.min_market_liquidity:
            return (
                False,
                f"Market liquidity ${market.liquidity:,.0f} below minimum ${self.config.min_market_liquidity:,.0f}",
            )

        return (True, "Market liquidity OK")

    def _check_time_remaining(self, market: CryptoMarket) -> Tuple[bool, str]:
        """
        Check if market has sufficient time remaining before resolution.

        For 15-minute markets:
        - Minimum 6 minutes (0.1 hours) required
        - Sub-hour markets are valid trading targets

        For longer markets:
        - Less time for price to move in our favor
        - Higher volatility near resolution
        - Potential for manipulation
        """
        if not market.end_date:
            return (True, "No end date specified - time OK")

        hours_left = (market.end_date - datetime.utcnow()).total_seconds() / 3600

        if hours_left < 0:
            return (False, "Market has already expired")

        if hours_left < self.config.min_time_remaining_hours:
            # Format time remaining appropriately (minutes for sub-hour, hours otherwise)
            if hours_left < 1:
                time_str = f"{hours_left * 60:.0f}min"
                min_str = f"{self.config.min_time_remaining_hours * 60:.0f}min"
            else:
                time_str = f"{hours_left:.1f}h"
                min_str = f"{self.config.min_time_remaining_hours:.1f}h"
            return (
                False,
                f"Only {time_str} remaining - below {min_str} minimum",
            )

        # Format output appropriately for 15-min markets
        if hours_left < 1:
            return (True, f"Time remaining OK ({hours_left * 60:.0f}min)")
        return (True, f"Time remaining OK ({hours_left:.0f}h)")

    def _check_spread(self, market: CryptoMarket) -> Tuple[bool, str]:
        """
        Check if bid-ask spread is acceptable.

        Wide spreads mean:
        - Poor price execution
        - Higher trading costs
        - Low market efficiency
        """
        # Calculate spread as difference between YES and (1 - NO)
        # In an efficient market: yes_price + no_price ≈ 1.0
        spread = abs(market.yes_price + market.no_price - 1.0)

        if spread > self.config.max_spread_percent:
            return (
                False,
                f"Spread {spread:.1%} exceeds maximum {self.config.max_spread_percent:.1%}",
            )

        return (True, f"Spread OK ({spread:.1%})")

    def _check_price_attractiveness(
        self, market: CryptoMarket, swarm_result: SwarmAnalysisResult
    ) -> Tuple[bool, str]:
        """
        Check if current prices are attractive for the predicted outcome.

        We want to buy when price is below expected value.
        """
        if swarm_result.consensus_prediction == "YES":
            # Buying YES - want low price
            if market.yes_price > 0.85:
                return (
                    False,
                    f"YES price ${market.yes_price:.2f} too high - limited upside",
                )
        else:
            # Buying NO - want low price
            if market.no_price > 0.85:
                return (
                    False,
                    f"NO price ${market.no_price:.2f} too high - limited upside",
                )

        return (True, "Price attractiveness OK")

    def _check_risk_limits(self, market: CryptoMarket) -> Tuple[bool, str]:
        """Check position and exposure limits."""
        suggested_size = self.position_tracker.get_suggested_position_size(
            market.market_id
        )

        if suggested_size < self.config.min_trade_size_usd:
            current_exposure = self.position_tracker.get_total_exposure()
            return (
                False,
                f"Position limits reached - current exposure ${current_exposure:,.0f}",
            )

        return (True, "Risk limits OK")

    def _check_signal_swarm_alignment(
        self,
        signal: AggregatedSignal,
        market: CryptoMarket,
        swarm_result: SwarmAnalysisResult,
    ) -> Tuple[bool, str]:
        """
        Check if signal direction aligns with swarm prediction.

        Alignment logic:
        - Bullish signal + bullish market + YES swarm = aligned
        - Bearish signal + bearish market + YES swarm = aligned
        - Bullish signal + bearish market + NO swarm = aligned
        - etc.
        """
        expected_swarm = self._get_expected_swarm_prediction(signal, market)

        if swarm_result.consensus_prediction != expected_swarm:
            return (
                False,
                f"Signal-swarm misalignment: expected {expected_swarm}, got {swarm_result.consensus_prediction}",
            )

        return (True, "Signal-swarm alignment OK")

    def _get_expected_swarm_prediction(
        self, signal: AggregatedSignal, market: CryptoMarket
    ) -> str:
        """
        Determine expected swarm prediction based on signal and market type.

        Logic:
        - Bullish signal + bullish market (price goes up) -> YES expected
        - Bullish signal + bearish market (price goes down) -> NO expected
        - Bearish signal + bullish market -> NO expected
        - Bearish signal + bearish market -> YES expected
        """
        if signal.direction == SignalDirection.BULLISH:
            if market.market_type == "bullish":
                return "YES"  # Bullish signal, bullish market = YES
            else:
                return "NO"  # Bullish signal, bearish market = NO
        elif signal.direction == SignalDirection.BEARISH:
            if market.market_type == "bearish":
                return "YES"  # Bearish signal, bearish market = YES
            else:
                return "NO"  # Bearish signal, bullish market = NO
        else:
            return "ABSTAIN"

    def _determine_side(
        self,
        signal: AggregatedSignal,
        market: CryptoMarket,
        swarm_result: SwarmAnalysisResult,
    ) -> str:
        """Determine which side to trade (YES or NO)."""
        # Use swarm prediction as the side
        return swarm_result.consensus_prediction

    def _calculate_position_size(
        self,
        signal: AggregatedSignal,
        swarm_result: SwarmAnalysisResult,
        market: CryptoMarket,
    ) -> float:
        """
        Calculate position size based on confidence and limits.

        Size scaling:
        - Base size adjusted by signal confidence
        - Adjusted by swarm confidence
        - Capped by position limits
        """
        # Get maximum available size
        max_size = self.position_tracker.get_suggested_position_size(market.market_id)

        if max_size <= 0:
            return 0.0

        # Start with base size
        base_size = self.config.min_trade_size_usd

        # Scale by signal confidence (0.5x to 1.5x)
        signal_multiplier = 0.5 + signal.confidence

        # Scale by swarm confidence (0.5x to 1.5x)
        swarm_multiplier = 0.5 + swarm_result.consensus_confidence

        # Scale by swarm agreement
        agreement_multiplier = 0.5 + (swarm_result.agreement_ratio * 0.5)

        # Calculate final size
        size = base_size * signal_multiplier * swarm_multiplier * agreement_multiplier

        # Apply limits
        size = max(self.config.min_trade_size_usd, size)
        size = min(self.config.max_trade_size_usd, size)
        size = min(max_size, size)

        return size

    def _calculate_overall_confidence(
        self, signal: AggregatedSignal, swarm_result: SwarmAnalysisResult
    ) -> float:
        """Calculate overall trade confidence."""
        # Weight: 40% signal, 60% swarm
        signal_weight = 0.4
        swarm_weight = 0.6

        overall = (
            signal.confidence * signal_weight
            + swarm_result.consensus_confidence * swarm_weight
        )

        # Boost for high agreement
        if swarm_result.agreement_ratio > 0.8:
            overall *= 1.1

        return min(1.0, overall)

    def get_decision_summary(self, decision: TradeDecision) -> str:
        """Generate human-readable decision summary."""
        if decision.should_trade:
            emoji = "[OK]"
            action = f"TRADE {decision.side}"
        else:
            emoji = "[FAIL]"
            action = "NO TRADE"

        summary = f"{emoji} Decision: {action}\n"
        summary += f"   Market: {decision.market_id[:20]}...\n"
        summary += f"   Reason: {decision.reason}\n"

        if decision.should_trade:
            summary += f"   Size: ${decision.size_usd:,.2f}\n"
            summary += f"   Confidence: {decision.confidence:.1%}\n"

        summary += f"\n   Signal Score: {decision.signal_score:+.3f}\n"
        summary += (
            f"   Swarm: {decision.swarm_consensus} ({decision.swarm_confidence:.1%})\n"
        )

        return summary

    def evaluate_market_opportunity(
        self,
        signal: AggregatedSignal,
        market: CryptoMarket,
    ) -> Dict[str, any]:
        """
        Quick evaluation without full swarm analysis.

        Used for preliminary filtering before expensive AI calls.
        """
        score = 0.0
        reasons = []

        # Signal strength
        if signal.direction != SignalDirection.NEUTRAL:
            score += 0.3
            reasons.append(f"Signal: {signal.direction.value}")

        if abs(signal.composite_score) > 0.2:
            score += 0.2
            reasons.append(f"Strong signal: {signal.composite_score:+.2f}")

        # Market alignment
        if (
            signal.direction == SignalDirection.BULLISH
            and market.market_type == "bullish"
        ):
            score += 0.2
            reasons.append("Signal-market aligned (bullish)")
        elif (
            signal.direction == SignalDirection.BEARISH
            and market.market_type == "bearish"
        ):
            score += 0.2
            reasons.append("Signal-market aligned (bearish)")

        # Price attractiveness
        if market.market_type == "bullish" and market.yes_price < 0.5:
            score += 0.15
            reasons.append(f"Underpriced YES: ${market.yes_price:.2f}")
        elif market.market_type == "bearish" and market.no_price < 0.5:
            score += 0.15
            reasons.append(f"Underpriced NO: ${market.no_price:.2f}")

        # Liquidity
        if market.liquidity > self.config.min_market_liquidity * 2:
            score += 0.15
            reasons.append(f"Good liquidity: ${market.liquidity:,.0f}")

        return {
            "score": score,
            "worth_analyzing": score >= 0.5,
            "reasons": reasons,
        }
