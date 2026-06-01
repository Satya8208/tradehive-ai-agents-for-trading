"""
Data Models for Crypto Polymarket Trading Agent

Defines all data structures used throughout the agent.
Built with love by TradeHive
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum

from .config import SignalDirection, TradeSide


# =============================================================================
# MARKET SIGNALS
# =============================================================================

@dataclass
class MarketSignal:
    """
    Signal from a single data agent (liquidation, whale).

    Each signal contains:
    - Direction: bullish/bearish/neutral
    - Strength: 0.0 to 1.0 (how strong the signal is)
    - Confidence: 0.0 to 1.0 (how confident we are in the signal)
    """
    agent_name: str
    symbol: str  # BTC or ETH
    timestamp: datetime
    direction: SignalDirection
    strength: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    raw_data: Dict[str, Any]
    reasoning: str = ""

    def to_dict(self) -> Dict:
        return {
            "agent_name": self.agent_name,
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "direction": self.direction.value,
            "strength": self.strength,
            "confidence": self.confidence,
            "raw_data": self.raw_data,
            "reasoning": self.reasoning,
        }


@dataclass
class AggregatedSignal:
    """
    Weighted aggregate of all signals for a symbol.

    Combines signals from all data agents into a single composite score.
    v2.0: Added regime and weights_used fields for tracking.
    """
    symbol: str
    timestamp: datetime
    direction: SignalDirection
    composite_score: float  # -1.0 to 1.0 (bearish to bullish)
    confidence: float
    signals: List[MarketSignal]
    dominant_signal: str  # Which signal has most influence
    signal_breakdown: Dict[str, float]  # Agent contributions
    regime: str = "none"  # Market regime during aggregation (v2.0)
    weights_used: Dict[str, float] = field(default_factory=dict)  # Actual weights (v2.0)

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "direction": self.direction.value,
            "composite_score": self.composite_score,
            "confidence": self.confidence,
            "dominant_signal": self.dominant_signal,
            "signal_breakdown": self.signal_breakdown,
            "signals": [s.to_dict() for s in self.signals],
            "regime": self.regime,
            "weights_used": self.weights_used,
        }


@dataclass
class TimeframeSignalBundle:
    """
    Container for all signals at a specific timeframe.

    Used by TimeframeController to organize signals by timeframe.
    """
    timeframe: str  # "15m", "30m", "1h", "4h"
    window_seconds: int
    liquidation: Optional['MarketSignal'] = None
    funding: Optional['MarketSignal'] = None
    open_interest: Optional['MarketSignal'] = None
    volume: Optional['MarketSignal'] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def get_all_signals(self) -> List['MarketSignal']:
        """Get all non-None signals for this timeframe."""
        signals = []
        for signal in [self.liquidation, self.funding, self.open_interest, self.volume]:
            if signal is not None:
                signals.append(signal)
        return signals


# =============================================================================
# POLYMARKET MARKETS
# =============================================================================

class MarketCategory(str, Enum):
    """Category of crypto prediction market"""
    PRICE_ABOVE = "price_above"  # "Bitcoin above $X by date"
    PRICE_BELOW = "price_below"  # "Bitcoin below $X by date"
    PRICE_HIT = "price_hit"      # "Will Bitcoin hit $X"
    DATE_TARGET = "date_target"  # "Bitcoin by end of year"
    EVENT = "event"              # Other crypto events


@dataclass
class CryptoMarket:
    """
    Polymarket market focused on crypto.

    Contains market details and current pricing.
    """
    market_id: str
    question: str
    symbol: str  # BTC or ETH
    yes_token_id: str
    no_token_id: str
    yes_price: float  # 0.0 to 1.0
    no_price: float   # 0.0 to 1.0
    liquidity: float
    end_date: Optional[datetime] = None
    is_active: bool = True
    price_target: Optional[float] = None
    market_type: str = "neutral"  # bullish, bearish, neutral
    # Optional legacy fields
    condition_id: str = ""
    description: str = ""
    category: Optional[MarketCategory] = None
    volume_24h: float = 0.0
    event_slug: str = ""
    last_updated: datetime = field(default_factory=datetime.utcnow)

    @property
    def implied_probability_yes(self) -> float:
        """Implied probability of YES outcome"""
        return self.yes_price

    @property
    def implied_probability_no(self) -> float:
        """Implied probability of NO outcome"""
        return self.no_price

    @property
    def market_url(self) -> str:
        """URL to the market on Polymarket"""
        if self.event_slug:
            return f"https://polymarket.com/event/{self.event_slug}"
        return f"https://polymarket.com/market/{self.market_id}"

    @property
    def time_remaining_hours(self) -> float:
        """Hours until market resolution"""
        if not self.end_date:
            return 999.0  # No end date
        delta = self.end_date - datetime.utcnow()
        return max(0, delta.total_seconds() / 3600)

    def to_dict(self) -> Dict:
        return {
            "market_id": self.market_id,
            "question": self.question,
            "symbol": self.symbol,
            "yes_price": self.yes_price,
            "no_price": self.no_price,
            "liquidity": self.liquidity,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "is_active": self.is_active,
            "price_target": self.price_target,
            "market_type": self.market_type,
            "time_remaining_hours": self.time_remaining_hours,
        }


# =============================================================================
# AI ANALYSIS
# =============================================================================

@dataclass
class ModelPrediction:
    """Individual prediction from a single AI model in the swarm."""
    model_name: str
    prediction: str  # "YES" or "NO"
    confidence: float  # 0.0 to 1.0
    reasoning: str
    weight: float  # Model's weight in consensus
    timestamp: datetime

    def to_dict(self) -> Dict:
        return {
            "model_name": self.model_name,
            "prediction": self.prediction,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "weight": self.weight,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ModelResponse:
    """Response from a single AI model (legacy format)"""
    provider: str
    model_name: str
    decision: TradeSide  # YES, NO
    confidence: int  # 0-100
    reasoning: str
    response_time: float
    success: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "provider": self.provider,
            "model_name": self.model_name,
            "decision": self.decision.value if self.decision else None,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "response_time": self.response_time,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class SwarmAnalysisResult:
    """
    Result from AI swarm consensus analysis.

    Contains individual model predictions and calculated consensus.
    """
    market_id: str
    timestamp: datetime
    predictions: List[ModelPrediction]
    consensus_prediction: str  # "YES", "NO", or "ABSTAIN"
    consensus_confidence: float  # 0.0 to 1.0
    yes_votes: int
    no_votes: int
    agreement_ratio: float  # 0.0 to 1.0

    def to_dict(self) -> Dict:
        return {
            "market_id": self.market_id,
            "timestamp": self.timestamp.isoformat(),
            "consensus_prediction": self.consensus_prediction,
            "consensus_confidence": self.consensus_confidence,
            "yes_votes": self.yes_votes,
            "no_votes": self.no_votes,
            "agreement_ratio": self.agreement_ratio,
            "predictions": [p.to_dict() for p in self.predictions],
        }


# =============================================================================
# TRADE DECISIONS
# =============================================================================

@dataclass
class TradeDecision:
    """
    Final trade decision for a market.

    Includes all context for the decision and risk assessment.
    """
    market_id: str
    timestamp: datetime
    should_trade: bool
    side: str  # "YES" or "NO"
    size_usd: float
    confidence: float
    reason: str
    signal_score: float
    swarm_consensus: str
    swarm_confidence: float

    def to_dict(self) -> Dict:
        return {
            "market_id": self.market_id,
            "timestamp": self.timestamp.isoformat(),
            "should_trade": self.should_trade,
            "side": self.side,
            "size_usd": self.size_usd,
            "confidence": self.confidence,
            "reason": self.reason,
            "signal_score": self.signal_score,
            "swarm_consensus": self.swarm_consensus,
            "swarm_confidence": self.swarm_confidence,
        }


class OrderStatus(str, Enum):
    """Status of a trade order"""
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class TradeExecution:
    """
    Record of an executed trade.

    Captures all details of the execution.
    """
    decision: TradeDecision
    order_id: str
    executed_price: float
    executed_size: float
    fees: float
    status: OrderStatus
    timestamp: datetime = field(default_factory=datetime.utcnow)
    error_message: Optional[str] = None

    @property
    def total_cost(self) -> float:
        """Total cost including fees"""
        return (self.executed_price * self.executed_size) + self.fees

    def to_dict(self) -> Dict:
        return {
            "order_id": self.order_id,
            "market_id": self.decision.market.market_id,
            "side": self.decision.side.value,
            "executed_price": self.executed_price,
            "executed_size": self.executed_size,
            "fees": self.fees,
            "total_cost": self.total_cost,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "error_message": self.error_message,
        }


# =============================================================================
# POSITION TRACKING
# =============================================================================

@dataclass
class Position:
    """
    An open position on Polymarket.
    """
    market: CryptoMarket
    side: TradeSide
    size: float  # Number of shares
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    opened_at: datetime
    last_updated: datetime = field(default_factory=datetime.utcnow)

    @property
    def market_value(self) -> float:
        """Current market value of position"""
        return self.size * self.current_price

    @property
    def cost_basis(self) -> float:
        """Original cost of position"""
        return self.size * self.avg_entry_price

    @property
    def pnl_percentage(self) -> float:
        """P&L as percentage"""
        if self.cost_basis == 0:
            return 0
        return (self.unrealized_pnl / self.cost_basis) * 100

    def to_dict(self) -> Dict:
        return {
            "market_id": self.market.market_id,
            "market_question": self.market.question,
            "side": self.side.value,
            "size": self.size,
            "avg_entry_price": self.avg_entry_price,
            "current_price": self.current_price,
            "market_value": self.market_value,
            "cost_basis": self.cost_basis,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "pnl_percentage": self.pnl_percentage,
            "opened_at": self.opened_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
        }


# =============================================================================
# ORCHESTRATOR RESULTS
# =============================================================================

@dataclass
class OrchestratorCycleResult:
    """
    Result of a single orchestrator cycle.

    Captures the full state of one trading cycle.
    """
    cycle_number: int
    timestamp: datetime
    signals: Dict[str, MarketSignal]
    aggregated_signal: Optional[AggregatedSignal]
    markets_scanned: List[CryptoMarket]
    swarm_results: List[SwarmAnalysisResult]
    decisions: List[TradeDecision]
    executions: List[Any]  # TradeExecution when available
    cycle_duration: float

    def to_dict(self) -> Dict:
        return {
            "cycle_number": self.cycle_number,
            "timestamp": self.timestamp.isoformat(),
            "signals_count": len(self.signals),
            "aggregated_signal": self.aggregated_signal.to_dict() if self.aggregated_signal else None,
            "markets_scanned": len(self.markets_scanned),
            "swarm_results": len(self.swarm_results),
            "decisions": len(self.decisions),
            "executions": len(self.executions),
            "cycle_duration": self.cycle_duration,
        }
