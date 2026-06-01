"""
TradeHive's AI-Enhanced Signal Aggregator
Uses a swarm of AI models to make consensus trading decisions
based on liquidation and order book data.

This replaces simple threshold-based logic with AI consensus.
"""

import sys
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple
from enum import Enum

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


class TradingDecision(Enum):
    """Final trading decision"""
    STRONG_BUY_YES = "STRONG_BUY_YES"
    BUY_YES = "BUY_YES"
    HOLD = "HOLD"
    BUY_NO = "BUY_NO"
    STRONG_BUY_NO = "STRONG_BUY_NO"


@dataclass
class AISignal:
    """AI-generated trading signal"""
    decision: TradingDecision
    confidence: float
    consensus_reasoning: str
    models_agreed: int
    models_total: int
    timestamp: datetime
    raw_metrics: Dict


# =============================================================================
# AI Prompt Templates
# =============================================================================

SIGNAL_ANALYSIS_SYSTEM_PROMPT = """You are an expert crypto derivatives trader analyzing real-time market data.

Your job is to analyze liquidation data and order book imbalances to predict short-term price direction for Bitcoin.

Rules:
1. Heavy LONG liquidations = BEARISH (price dropping, longs getting stopped out)
2. Heavy SHORT liquidations = BULLISH (price rising, shorts getting squeezed)
3. Order book bid-heavy = BULLISH (buyers accumulating)
4. Order book ask-heavy = BEARISH (sellers distributing)
5. Be decisive - traders need clear signals, not maybes

Respond with EXACTLY this format:
DECISION: [BUY_YES or BUY_NO or HOLD]
CONFIDENCE: [0-100]
REASONING: [1-2 sentences explaining why]"""


SIGNAL_ANALYSIS_USER_PROMPT = """Analyze this real-time crypto market data and provide a trading signal for Polymarket crypto price prediction markets.

=== LIQUIDATION DATA (Last 5 minutes) ===
- Total Long Liquidations: ${long_liq:,.0f}
- Total Short Liquidations: ${short_liq:,.0f}
- Long/Short Ratio: {ratio:.2f}
- Total Liquidation Events: {total_events}
- Liquidation Velocity: {velocity:.1f} events/min

Interpretation:
{liq_interpretation}

=== ORDER BOOK DATA ===
- Total Bid Volume: ${bid_vol:,.0f}
- Total Ask Volume: ${ask_vol:,.0f}
- Bid/Ask Imbalance: {imbalance:.2f}
- Whale Orders (>$100k) on Bid: {whale_bids}
- Whale Orders (>$100k) on Ask: {whale_asks}

Interpretation:
{ob_interpretation}

=== COMBINED SIGNAL ===
The rule-based system suggests: {rule_signal} with {rule_confidence:.0f}% confidence

Based on ALL the above data, what is your trading recommendation for a Polymarket crypto price prediction market (like "Will BTC exceed $X")?"""


class AISignalAggregator:
    """
    Enhanced signal aggregator that uses AI swarm consensus
    to make trading decisions based on market data.
    """

    def __init__(self, use_ai: bool = True):
        """
        Initialize the AI-enhanced aggregator

        Args:
            use_ai: If True, use AI swarm. If False, use rule-based only.
        """
        self.use_ai = use_ai
        self.swarm = None

        # Import signal agents
        from .liquidation_agent import LiquidationAgent
        from .whale_agent import WhaleAgent

        self.liquidation_agent = LiquidationAgent()
        self.whale_agent = WhaleAgent()

        # Initialize swarm if using AI
        if use_ai:
            try:
                from src.agents.swarm_agent import SwarmAgent
                self.swarm = SwarmAgent()
                print("[AISignalAggregator] AI Swarm loaded successfully!")
            except Exception as e:
                print(f"[AISignalAggregator] WARNING: Could not load swarm: {e}")
                print("[AISignalAggregator] Falling back to rule-based decisions")
                self.use_ai = False

        print(f"[AISignalAggregator] Initialized | AI Mode: {self.use_ai}")

    # =========================================================================
    # Data input methods
    # =========================================================================

    def add_liquidation(self, exchange: str, symbol: str, side: str,
                       size_usd: float, price: float, timestamp=None):
        """Forward liquidation to agent"""
        self.liquidation_agent.add_liquidation(
            exchange, symbol, side, size_usd, price, timestamp
        )

    def update_order_book(self, symbol: str, bids: list, asks: list, timestamp=None):
        """Forward order book to agent"""
        self.whale_agent.update_order_book(symbol, bids, asks, timestamp)

    # =========================================================================
    # Signal generation
    # =========================================================================

    def _get_rule_based_signal(self) -> Tuple[str, float, Dict]:
        """Get the rule-based signal from agents"""
        # Get metrics from each agent
        liq_score, liq_metrics = self.liquidation_agent.get_signal_score()
        whale_score, whale_metrics = self.whale_agent.get_signal_score()

        # Weighted combination
        final_score = liq_score * 0.60 + whale_score * 0.40

        if final_score >= 50:
            signal = "STRONG_BUY_YES"
        elif final_score >= 25:
            signal = "BUY_YES"
        elif final_score <= -50:
            signal = "STRONG_BUY_NO"
        elif final_score <= -25:
            signal = "BUY_NO"
        else:
            signal = "HOLD"

        return signal, abs(final_score), {
            "liq_score": liq_score,
            "whale_score": whale_score,
            "final_score": final_score,
            "liq_metrics": liq_metrics,
            "whale_metrics": whale_metrics
        }

    def _build_ai_prompt(self, metrics: Dict) -> str:
        """Build the prompt for AI analysis"""
        liq = metrics["liq_metrics"]
        whale = metrics["whale_metrics"]

        # Liquidation interpretation
        ratio = liq.get("long_short_ratio", 1)
        if ratio > 2:
            liq_interp = "BEARISH - Significantly more longs getting liquidated than shorts"
        elif ratio > 1.5:
            liq_interp = "Slightly BEARISH - More longs liquidated"
        elif ratio < 0.5:
            liq_interp = "BULLISH - Significantly more shorts getting liquidated (short squeeze)"
        elif ratio < 0.67:
            liq_interp = "Slightly BULLISH - More shorts liquidated"
        else:
            liq_interp = "NEUTRAL - Balanced liquidations"

        # Order book interpretation
        imb = whale.get("imbalance_ratio", 1)
        if imb > 1.5:
            ob_interp = "BULLISH - Strong bid pressure, buyers accumulating"
        elif imb > 1.2:
            ob_interp = "Slightly BULLISH - Bid-heavy order book"
        elif imb < 0.67:
            ob_interp = "BEARISH - Strong ask pressure, sellers distributing"
        elif imb < 0.8:
            ob_interp = "Slightly BEARISH - Ask-heavy order book"
        else:
            ob_interp = "NEUTRAL - Balanced order book"

        rule_signal, rule_conf, _ = self._get_rule_based_signal()

        prompt = SIGNAL_ANALYSIS_USER_PROMPT.format(
            long_liq=liq.get("long_volume", 0),
            short_liq=liq.get("short_volume", 0),
            ratio=ratio,
            total_events=liq.get("total_count", 0),
            velocity=liq.get("velocity_per_min", 0),
            liq_interpretation=liq_interp,
            bid_vol=whale.get("total_bid_volume", 0),
            ask_vol=whale.get("total_ask_volume", 0),
            imbalance=imb,
            whale_bids=whale.get("whale_bid_count", 0),
            whale_asks=whale.get("whale_ask_count", 0),
            ob_interpretation=ob_interp,
            rule_signal=rule_signal,
            rule_confidence=rule_conf
        )

        return prompt

    def _parse_ai_responses(self, swarm_result: Dict) -> Tuple[TradingDecision, float, str, int, int]:
        """Parse AI responses and calculate consensus"""
        decisions = []
        confidences = []
        reasonings = []

        for model_name, model_data in swarm_result.get("responses", {}).items():
            if not model_data.get("success"):
                continue

            response = model_data.get("response", "")

            # Parse decision
            if "DECISION:" in response.upper():
                try:
                    decision_line = [l for l in response.split('\n') if 'DECISION:' in l.upper()][0]
                    decision_text = decision_line.split(':')[1].strip().upper()

                    if "HOLD" in decision_text:
                        decisions.append("HOLD")
                    elif "YES" in decision_text or "BUY_YES" in decision_text:
                        decisions.append("YES")
                    elif "NO" in decision_text or "BUY_NO" in decision_text:
                        decisions.append("NO")
                except:
                    pass

            # Parse confidence
            if "CONFIDENCE:" in response.upper():
                try:
                    conf_line = [l for l in response.split('\n') if 'CONFIDENCE:' in l.upper()][0]
                    conf_text = conf_line.split(':')[1].strip()
                    conf = float(''.join(c for c in conf_text if c.isdigit() or c == '.'))
                    confidences.append(min(100, max(0, conf)))
                except:
                    pass

            # Parse reasoning
            if "REASONING:" in response.upper():
                try:
                    reas_line = [l for l in response.split('\n') if 'REASONING:' in l.upper()][0]
                    reasonings.append(reas_line.split(':', 1)[1].strip())
                except:
                    pass

        total_models = len(swarm_result.get("responses", {}))

        if not decisions:
            return TradingDecision.HOLD, 0, "No valid AI responses", 0, total_models

        # Calculate consensus
        yes_count = decisions.count("YES")
        no_count = decisions.count("NO")
        hold_count = decisions.count("HOLD")

        avg_confidence = sum(confidences) / len(confidences) if confidences else 50

        if yes_count > no_count and yes_count > hold_count:
            if avg_confidence > 70:
                decision = TradingDecision.STRONG_BUY_YES
            else:
                decision = TradingDecision.BUY_YES
            agreed = yes_count
        elif no_count > yes_count and no_count > hold_count:
            if avg_confidence > 70:
                decision = TradingDecision.STRONG_BUY_NO
            else:
                decision = TradingDecision.BUY_NO
            agreed = no_count
        else:
            decision = TradingDecision.HOLD
            agreed = hold_count

        # Combine reasonings
        combined_reasoning = " | ".join(reasonings[:3]) if reasonings else "No reasoning provided"

        return decision, avg_confidence, combined_reasoning, agreed, len(decisions)

    def get_ai_signal(self, timeout: int = 30) -> AISignal:
        """
        Get AI-powered trading signal

        Args:
            timeout: Maximum seconds to wait for AI responses

        Returns:
            AISignal with decision, confidence, and reasoning
        """
        # Get base metrics
        rule_signal, rule_conf, metrics = self._get_rule_based_signal()

        if not self.use_ai or self.swarm is None:
            # Return rule-based signal
            decision = TradingDecision[rule_signal]
            return AISignal(
                decision=decision,
                confidence=rule_conf,
                consensus_reasoning="Rule-based signal (AI not available)",
                models_agreed=0,
                models_total=0,
                timestamp=datetime.utcnow(),
                raw_metrics=metrics
            )

        # Build prompt with current data
        prompt = self._build_ai_prompt(metrics)

        print("\n[AI] Querying swarm for trading decision...")

        # Query AI swarm
        try:
            swarm_result = self.swarm.query(
                prompt=prompt,
                system_prompt=SIGNAL_ANALYSIS_SYSTEM_PROMPT
            )

            # Parse responses
            decision, confidence, reasoning, agreed, total = self._parse_ai_responses(swarm_result)

            print(f"[AI] Consensus: {decision.value} ({agreed}/{total} models agreed)")

            return AISignal(
                decision=decision,
                confidence=confidence,
                consensus_reasoning=reasoning,
                models_agreed=agreed,
                models_total=total,
                timestamp=datetime.utcnow(),
                raw_metrics=metrics
            )

        except Exception as e:
            print(f"[AI] Error: {e} - falling back to rule-based")
            decision = TradingDecision[rule_signal]
            return AISignal(
                decision=decision,
                confidence=rule_conf,
                consensus_reasoning=f"Fallback to rules (AI error: {str(e)[:50]})",
                models_agreed=0,
                models_total=0,
                timestamp=datetime.utcnow(),
                raw_metrics=metrics
            )

    def print_status(self, use_ai: bool = False) -> None:
        """Print current status"""
        rule_signal, rule_conf, metrics = self._get_rule_based_signal()

        print("\n" + "="*70)
        print("           AI SIGNAL AGGREGATOR STATUS")
        print("="*70)

        # Liquidation metrics
        liq = metrics["liq_metrics"]
        print(f"\n[LIQUIDATION DATA] (60% weight)")
        print(f"  Long Liqs: ${liq.get('long_volume', 0):,.0f}")
        print(f"  Short Liqs: ${liq.get('short_volume', 0):,.0f}")
        print(f"  Ratio: {liq.get('long_short_ratio', 1):.2f}")
        print(f"  Signal: {liq.get('signal', 'N/A')}")

        # Whale metrics
        whale = metrics["whale_metrics"]
        print(f"\n[ORDER BOOK DATA] (40% weight)")
        print(f"  Bid/Ask Imbalance: {whale.get('imbalance_ratio', 1):.2f}")
        print(f"  Whale Bids: {whale.get('whale_bid_count', 0)}")
        print(f"  Whale Asks: {whale.get('whale_ask_count', 0)}")
        print(f"  Signal: {whale.get('signal', 'N/A')}")

        print(f"\n" + "-"*70)
        print(f"[RULE-BASED SIGNAL]")
        print(f"  Decision: {rule_signal}")
        print(f"  Confidence: {rule_conf:.0f}%")

        if use_ai and self.use_ai:
            print(f"\n[AI CONSENSUS]")
            ai_signal = self.get_ai_signal()
            print(f"  Decision: {ai_signal.decision.value}")
            print(f"  Confidence: {ai_signal.confidence:.0f}%")
            print(f"  Models: {ai_signal.models_agreed}/{ai_signal.models_total} agreed")
            print(f"  Reasoning: {ai_signal.consensus_reasoning[:100]}...")

        print("="*70 + "\n")


# =============================================================================
# Test
# =============================================================================
if __name__ == "__main__":
    import random

    # Test without AI first
    print("Testing AI Signal Aggregator (rule-based mode)...")
    agg = AISignalAggregator(use_ai=False)

    # Add some test data
    for _ in range(20):
        agg.add_liquidation(
            exchange="Binance",
            symbol="BTCUSDT",
            side=random.choice(["long", "short"]),
            size_usd=random.uniform(10000, 100000),
            price=87000
        )

    # Add order book
    bids = [{"price": 87000 - i*10, "size": random.uniform(0.5, 5)} for i in range(30)]
    asks = [{"price": 87010 + i*10, "size": random.uniform(0.5, 3)} for i in range(30)]
    agg.update_order_book("BTC", bids, asks)

    # Print status
    agg.print_status(use_ai=False)

    print("\n\n=== Now testing with AI swarm ===\n")
    ai_agg = AISignalAggregator(use_ai=True)

    # Add same test data
    for _ in range(20):
        ai_agg.add_liquidation(
            exchange="Binance", symbol="BTCUSDT",
            side=random.choice(["long", "short"]),
            size_usd=random.uniform(10000, 100000),
            price=87000
        )
    ai_agg.update_order_book("BTC", bids, asks)

    # Get AI signal
    signal = ai_agg.get_ai_signal()
    print(f"\nFinal AI Signal: {signal}")
