"""
Data Models for Polymarket CLI Trading Agents

All dataclasses used across the system — markets, predictions, trades, positions, arbitrage.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any


# =============================================================================
# POLYMARKET MARKETS
# =============================================================================

@dataclass
class CLIMarket:
    """A Polymarket prediction market parsed from CLI JSON output."""
    condition_id: str
    question: str
    symbol: str  # BTC, ETH, SOL, CRYPTO
    yes_token_id: str
    no_token_id: str
    yes_price: float  # 0.0 to 1.0
    no_price: float  # 0.0 to 1.0
    liquidity: float
    volume_24h: float
    end_date: Optional[datetime] = None
    is_active: bool = True
    market_type: str = "neutral"  # bullish, bearish, neutral, binary_updown
    price_target: Optional[float] = None
    duration_minutes: Optional[int] = None  # For short-term Up/Down markets (5, 15, 60, 240)
    event_slug: str = ""
    spread: float = 0.0
    slug: str = ""
    description: str = ""

    @property
    def time_remaining_hours(self) -> float:
        if not self.end_date:
            return 999.0
        delta = self.end_date - datetime.utcnow()
        return max(0, delta.total_seconds() / 3600)

    @property
    def implied_probability(self) -> float:
        return self.yes_price

    @property
    def market_url(self) -> str:
        if self.slug:
            return f"https://polymarket.com/event/{self.slug}"
        return f"https://polymarket.com"

    def to_dict(self) -> Dict:
        return {
            "condition_id": self.condition_id,
            "question": self.question,
            "symbol": self.symbol,
            "yes_price": self.yes_price,
            "no_price": self.no_price,
            "liquidity": self.liquidity,
            "volume_24h": self.volume_24h,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "is_active": self.is_active,
            "market_type": self.market_type,
            "price_target": self.price_target,
            "duration_minutes": self.duration_minutes,
            "time_remaining_hours": self.time_remaining_hours,
            "spread": self.spread,
        }


# =============================================================================
# SWARM ANALYSIS
# =============================================================================

@dataclass
class SwarmPrediction:
    """One model's prediction for a market."""
    model_provider: str  # "claude", "deepseek", "xai"
    model_name: str
    prediction: str  # "YES" or "NO"
    probability_estimate: float  # Model's estimated true probability (0.0-1.0)
    confidence: float  # Model's self-assessed confidence (0.0-1.0)
    reasoning: str
    response_time: float  # Seconds

    def to_dict(self) -> Dict:
        return {
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "prediction": self.prediction,
            "probability_estimate": self.probability_estimate,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "response_time": self.response_time,
        }


@dataclass
class SwarmConsensus:
    """Aggregated consensus from 3 models."""
    market_id: str
    timestamp: datetime
    predictions: List[SwarmPrediction]
    consensus_prediction: str  # "YES", "NO", "ABSTAIN"
    consensus_probability: float  # Weighted average probability from majority
    consensus_confidence: float  # agreement_ratio * avg_confidence
    yes_votes: int
    no_votes: int
    agreement_ratio: float  # 0.0 to 1.0
    analysis_path: str = ""

    def to_dict(self) -> Dict:
        return {
            "market_id": self.market_id,
            "timestamp": self.timestamp.isoformat(),
            "consensus_prediction": self.consensus_prediction,
            "consensus_probability": self.consensus_probability,
            "consensus_confidence": self.consensus_confidence,
            "yes_votes": self.yes_votes,
            "no_votes": self.no_votes,
            "agreement_ratio": self.agreement_ratio,
            "analysis_path": self.analysis_path,
            "predictions": [p.to_dict() for p in self.predictions],
        }


# =============================================================================
# EDGE CALCULATION
# =============================================================================

@dataclass
class EdgeResult:
    """Output from edge calculator."""
    edge_percent: float  # Edge as percentage
    expected_value: float  # EV per $1 bet
    win_probability: float  # Our estimated probability
    market_price: float  # Current market price (YES price)
    kelly_fraction: float  # Raw Kelly fraction
    recommended_size_usd: float  # Kelly-adjusted position size
    time_decay_factor: float  # Time decay applied
    confidence: float  # Confidence in edge estimate
    recommended_side: str = ""  # "YES" or "NO" — the side with edge

    def to_dict(self) -> Dict:
        return {
            "edge_percent": round(self.edge_percent, 2),
            "expected_value": round(self.expected_value, 4),
            "win_probability": round(self.win_probability, 3),
            "market_price": round(self.market_price, 3),
            "kelly_fraction": round(self.kelly_fraction, 4),
            "recommended_size_usd": round(self.recommended_size_usd, 2),
            "time_decay_factor": round(self.time_decay_factor, 3),
            "confidence": round(self.confidence, 3),
            "recommended_side": self.recommended_side,
        }


# =============================================================================
# ARBITRAGE
# =============================================================================

@dataclass
class ArbitrageOpportunity:
    """Detected arbitrage between related markets."""
    arb_type: str  # "combinatorial", "complementary", "cross_market"
    markets: List[CLIMarket]
    description: str
    edge_percent: float
    recommended_trades: List[Dict[str, Any]]
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            "arb_type": self.arb_type,
            "description": self.description,
            "edge_percent": round(self.edge_percent, 2),
            "markets": [m.condition_id for m in self.markets],
            "recommended_trades": self.recommended_trades,
            "timestamp": self.timestamp.isoformat(),
        }


# =============================================================================
# TRADE DECISIONS & EXECUTION
# =============================================================================

@dataclass
class TradeDecision:
    """Final trade decision for a market."""
    market_id: str
    timestamp: datetime
    should_trade: bool
    side: str  # "YES" or "NO"
    size_usd: float
    price: float
    confidence: float
    reason: str
    source: str  # "swarm", "arbitrage"
    prediction_path: str = ""

    def to_dict(self) -> Dict:
        return {
            "market_id": self.market_id,
            "timestamp": self.timestamp.isoformat(),
            "should_trade": self.should_trade,
            "side": self.side,
            "size_usd": round(self.size_usd, 2),
            "price": round(self.price, 4),
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "source": self.source,
            "prediction_path": self.prediction_path,
        }


@dataclass
class TradeExecution:
    """Record of an executed trade."""
    trade_id: str
    market_id: str
    token_id: str
    side: str  # YES or NO
    size_usd: float
    price: float
    status: str  # "simulated", "paper_filled", "submitted", "filled"
    execution_mode: str  # "dry_run", "paper", "live"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    order_id: Optional[str] = None
    fees: float = 0.0
    requested_size_usd: float = 0.0
    submitted_shares: float = 0.0
    submitted_notional_usd: float = 0.0
    filled_shares: float = 0.0
    filled_notional_usd: float = 0.0
    decision_price: float = 0.0
    placed_price: float = 0.0
    fill_status_source: str = ""
    prediction_path: str = ""

    @property
    def total_cost(self) -> float:
        return (self.filled_notional_usd or self.size_usd) + self.fees

    def to_dict(self) -> Dict:
        return {
            "trade_id": self.trade_id,
            "market_id": self.market_id,
            "token_id": self.token_id,
            "side": self.side,
            "size_usd": round(self.size_usd, 2),
            "price": round(self.price, 4),
            "status": self.status,
            "execution_mode": self.execution_mode,
            "timestamp": self.timestamp.isoformat(),
            "order_id": self.order_id,
            "fees": round(self.fees, 4),
            "requested_size_usd": round(self.requested_size_usd, 2),
            "submitted_shares": round(self.submitted_shares, 4),
            "submitted_notional_usd": round(self.submitted_notional_usd, 4),
            "filled_shares": round(self.filled_shares, 4),
            "filled_notional_usd": round(self.filled_notional_usd, 4),
            "decision_price": round(self.decision_price, 4),
            "placed_price": round(self.placed_price, 4),
            "fill_status_source": self.fill_status_source,
            "prediction_path": self.prediction_path,
        }


# =============================================================================
# POSITION TRACKING
# =============================================================================

@dataclass
class Position:
    """An open position (real or simulated)."""
    market_id: str
    token_id: str
    side: str  # YES or NO
    size_usd: float
    entry_price: float
    current_price: float
    entry_time: datetime
    question: str = ""
    unrealized_pnl: float = 0.0
    is_resolved: bool = False
    resolved_outcome: str = ""  # "Yes" or "No" when resolved
    end_date: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    source: str = ""  # "swarm" or "arbitrage"
    symbol: str = ""  # "BTC", "ETH", "SOL", etc.
    requested_size_usd: float = 0.0
    shares_count: float = 0.0
    filled_notional_usd: float = 0.0
    entry_order_id: str = ""

    @property
    def time_remaining_hours(self) -> float:
        """Hours until market expiry. 999 if unknown."""
        if not self.end_date:
            return 999.0
        delta = self.end_date - datetime.utcnow()
        return max(0, delta.total_seconds() / 3600)

    @property
    def shares(self) -> float:
        if self.shares_count > 0:
            return self.shares_count
        return self.size_usd / self.entry_price if self.entry_price > 0 else 0

    def update_price(self, new_price: float):
        self.current_price = new_price
        self.unrealized_pnl = self.shares * (new_price - self.entry_price)

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def return_pct(self) -> float:
        if self.size_usd <= 0:
            return 0.0
        return (self.unrealized_pnl / self.size_usd) * 100

    def to_dict(self) -> Dict:
        return {
            "market_id": self.market_id,
            "token_id": self.token_id,
            "side": self.side,
            "size_usd": round(self.size_usd, 2),
            "entry_price": round(self.entry_price, 4),
            "current_price": round(self.current_price, 4),
            "entry_time": self.entry_time.isoformat(),
            "question": self.question,
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "market_value": round(self.market_value, 2),
            "is_resolved": self.is_resolved,
            "resolved_outcome": self.resolved_outcome,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "duration_minutes": self.duration_minutes,
            "source": self.source,
            "symbol": self.symbol,
            "requested_size_usd": round(self.requested_size_usd, 2),
            "shares": round(self.shares, 4),
            "filled_notional_usd": round(self.filled_notional_usd, 4),
            "entry_order_id": self.entry_order_id,
        }


# =============================================================================
# CYCLE RESULTS
# =============================================================================

@dataclass
class CycleResult:
    """Result of a single orchestrator cycle."""
    cycle_number: int
    timestamp: datetime
    markets_found: int
    arb_opportunities: int
    swarm_analyses: int
    trades_executed: int
    cycle_duration: float
    risk_status: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "cycle_number": self.cycle_number,
            "timestamp": self.timestamp.isoformat(),
            "markets_found": self.markets_found,
            "arb_opportunities": self.arb_opportunities,
            "swarm_analyses": self.swarm_analyses,
            "trades_executed": self.trades_executed,
            "cycle_duration": round(self.cycle_duration, 2),
            "risk_status": self.risk_status,
        }
