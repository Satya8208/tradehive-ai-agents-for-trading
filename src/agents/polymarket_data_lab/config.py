"""
Crypto Polymarket Trading Agent Configuration

All settings for the agent, loaded from environment variables.
Built with love by TradeHive
"""

import os
from enum import Enum
from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent.parent


class ExecutionMode(str, Enum):
    """Trading execution mode"""

    DRY_RUN = "dry_run"  # Analysis only, no trades
    PAPER = "paper"  # Simulated trades with tracking
    LIVE = "live"  # Actual trading on Polymarket


class SignalDirection(str, Enum):
    """Direction of a market signal"""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class TradeSide(str, Enum):
    """Side of a Polymarket trade"""

    YES = "YES"
    NO = "NO"


@dataclass
class CryptoPolymarketConfig:
    """
    Configuration for Crypto Polymarket Trading Agent

    All settings can be overridden via environment variables with CRYPTO_PM_ prefix.
    Example: CRYPTO_PM_EXECUTION_MODE=live
    """

    # =========================================================================
    # API KEYS
    # =========================================================================
    anthropic_api_key: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_KEY", "")
    )
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_KEY", ""))
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_KEY", ""))
    xai_api_key: str = field(default_factory=lambda: os.getenv("XAI_API_KEY", ""))
    tradehive_api_key: str = field(
        default_factory=lambda: os.getenv("TRADEHIVE_API_KEY", "")
    )

    # Polymarket trading credentials
    polymarket_private_key: str = field(
        default_factory=lambda: os.getenv("POLYMARKET_PRIVATE_KEY", "")
    )
    polymarket_funder_address: str = field(
        default_factory=lambda: os.getenv("POLYMARKET_FUNDER_ADDRESS", "")
    )

    # =========================================================================
    # EXECUTION SETTINGS
    # =========================================================================
    execution_mode: ExecutionMode = field(
        default_factory=lambda: ExecutionMode(
            os.getenv("CRYPTO_PM_EXECUTION_MODE", "dry_run")
        )
    )

    # Confidence thresholds
    min_confidence_threshold: float = 0.70  # 70% swarm consensus required
    min_signal_strength: float = 0.3  # Minimum aggregated signal strength

    # Trade size limits (USD)
    min_trade_size_usd: float = 500.0
    max_trade_size_usd: float = 5000.0
    max_position_per_market_usd: float = 10000.0
    max_total_exposure_usd: float = 50000.0

    # =========================================================================
    # EDGE CALCULATOR & KELLY SIZING (Edge-Based Position Sizing v2.0)
    # =========================================================================
    # Replaces fixed position sizes with edge-based optimal sizing

    enable_edge_calculator: bool = True
    enable_kelly_sizing: bool = True

    # Edge thresholds (minimum edge required to trade)
    min_edge_threshold: float = 5.0  # Minimum 5% edge to trade
    min_edge_confidence: float = 0.50  # Minimum 50% confidence in edge

    # Kelly Criterion parameters
    kelly_fraction: float = 0.50  # Use 50% of full Kelly (fractional Kelly for safety)
    min_position_usd: float = 100.0  # Minimum position size

    # Time decay parameters
    # Signals lose predictive power exponentially approaching resolution
    # For 15-min markets: use shorter half-life for faster signal decay
    time_decay_half_life_hours: float = 0.5  # Edge halves every 30 minutes (for short-duration markets)
    time_decay_minimum: float = 0.20  # Never decay below 20% edge

    # =========================================================================
    # RISK MANAGEMENT
    # =========================================================================
    max_position_percentage: float = 10.0  # Max % of bankroll per position
    max_drawdown_threshold: float = 15.0  # Stop trading if drawdown > 15%
    daily_loss_limit: float = 2000.0  # Stop trading if daily loss > $2k

    # =========================================================================
    # SIGNAL WEIGHTS (must sum to 1.0)
    # Based on historical accuracy:
    # - Liquidation: 60-62% accuracy (primary signal)
    # - Whale: 70%+ accuracy (confirmation signal)
    # =========================================================================
    liquidation_weight: float = 0.60
    whale_weight: float = 0.40

    # =========================================================================
    # DATA COLLECTION SETTINGS
    # =========================================================================
    liquidation_lookback_hours: int = 4
    liquidation_limit: int = 10000  # Max records to fetch

    whale_threshold_percent: float = 31.0  # OI change threshold for whale detection
    whale_lookback_periods: int = 10  # Periods for moving average

    # =========================================================================
    # AI CONFIGURATION
    # =========================================================================
    swarm_timeout_seconds: int = 120  # Timeout per model (standard mode)
    swarm_timeout_fast_seconds: int = 30  # Timeout per model (fast mode for 15-min markets)
    consensus_model: str = "deepseek-v4-flash"  # Model for consensus summary
    enable_fast_swarm_mode: bool = True  # Use fast swarm for short-duration markets

    # Models to use in swarm (provider, model_name)
    swarm_models: list = field(
        default_factory=lambda: [
            ("deepseek", "deepseek-v4-flash"),
            ("xai", "grok-4-fast-reasoning"),
            ("claude", "claude-sonnet-4-6"),
            ("claude", "claude-opus-4-7"),
            ("openrouter", "qwen/qwen3-max"),
            ("openrouter", "z-ai/glm-4.6"),
            ("openrouter", "openai/gpt-5.4-mini"),
        ]
    )

    # Fast swarm models (for 15-min markets - uses only fastest models)
    swarm_models_fast: list = field(
        default_factory=lambda: [
            ("deepseek", "deepseek-v4-flash"),  # Fastest
            ("xai", "grok-4-fast-reasoning"),  # Fast reasoning
            ("openrouter", "openai/gpt-5.4-mini"),  # Fast mini model
        ]
    )

    # =========================================================================
    # POLYMARKET API ENDPOINTS
    # =========================================================================
    polymarket_clob_url: str = "https://clob.polymarket.com"
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    polymarket_ws_url: str = "wss://ws-live-data.polymarket.com"
    polymarket_data_api_url: str = "https://data-api.polymarket.com"

    # TradeHive API
    tradehive_api_url: str = field(
        default_factory=lambda: os.getenv("TRADEHIVE_API_BASE_URL", "http://localhost:8000")
    )

    # Hyperliquid API (for volume data)
    hyperliquid_api_url: str = "https://api.hyperliquid.xyz/info"

    # =========================================================================
    # MARKET FILTERING
    # =========================================================================
    # Keywords to identify crypto markets (case-insensitive)
    crypto_keywords: list = field(
        default_factory=lambda: [
            "bitcoin",
            "btc",
            "ethereum",
            "eth",
            "crypto",
        ]
    )

    # Symbols to focus on
    target_symbols: list = field(default_factory=lambda: ["BTC", "ETH"])

    # Market filters
    min_market_liquidity_usd: float = 50000.0
    min_market_volume_24h_usd: float = 10000.0

    min_time_remaining_hours: float = 0.1  # 6 minutes minimum (for 15-min markets)
    max_markets_to_analyze: int = 10
    max_spread_percent: float = 0.05  # 5% max bid-ask spread

    # Decision engine thresholds
    min_signal_score: float = 0.15  # Minimum absolute composite score
    min_swarm_agreement: float = 0.60  # 60% model agreement required
    max_entry_price: float = 0.85  # Don't buy if price > 85%

    # =========================================================================
    # TIMING
    # =========================================================================
    cycle_interval_seconds: int = 60  # 1 minute between cycles (for 15-min market trading)
    data_refresh_seconds: int = 30  # Refresh market data more frequently

    # =========================================================================
    # MULTI-TIMEFRAME CONFIGURATION (Multi-Timeframe Enhancement v2.0)
    # =========================================================================
    # Enable multi-timeframe analysis for different event durations
    enable_multi_timeframe: bool = True

    # Timeframe definitions (seconds)
    # Each timeframe will generate independent signals via dedicated agents
    timeframes: Dict[str, int] = field(
        default_factory=lambda: {
            "15m": 900,  # 15 minutes - for hourly/daily events
            "30m": 1800,  # 30 minutes - for 2-7 day events
            "1h": 3600,  # 1 hour - for weekly events
            "4h": 14400,  # 4 hours - for monthly events
        }
    )

    # Signal weighting by timeframe (higher = more weight to that timeframe)
    # Based on event resolution matching (15m for short events, 4h for long events)
    timeframe_weights: Dict[str, float] = field(
        default_factory=lambda: {
            "15m": 1.0,  # Standard weight for short events
            "30m": 1.2,  # Slightly higher for medium events
            "1h": 1.5,  # Higher for longer events (more data)
            "4h": 2.0,  # Highest for longest events (most reliable)
        }
    )

    # Agent lookback periods by timeframe (in seconds)
    agent_lookbacks: Dict[str, Dict[str, int]] = field(
        default_factory=lambda: {
            "liquidation": {
                "15m": 900,  # 15 minutes of liquidation data
                "30m": 1800,  # 30 minutes of liquidation data
                "1h": 3600,  # 1 hour of liquidation data
                "4h": 14400,  # 4 hours of liquidation data
            },
            "funding": {
                "15m": 3600,  # 1 hour of funding data (hourly rates)
                "30m": 7200,  # 2 hours of funding data
                "1h": 14400,  # 4 hours of funding data
                "4h": 57600,  # 16 hours of funding data
            },
            "volume": {
                "15m": 900,  # 15 minutes of volume data
                "30m": 1800,  # 30 minutes of volume data
                "1h": 3600,  # 1 hour of volume data
                "4h": 14400,  # 4 hours of volume data
            },
            "open_interest": {
                "15m": 900,  # 15 minutes of OI data
                "30m": 1800,  # 30 minutes of OI data
                "1h": 3600,  # 1 hour of OI data
                "4h": 14400,  # 4 hours of OI data
            },
            "orderbook": {
                "15m": 60,   # 1 minute snapshot (order books are real-time)
                "30m": 120,  # 2 minute snapshot
                "1h": 300,   # 5 minute snapshot
                "4h": 900,   # 15 minute snapshot
            },
        }
    )

    # =========================================================================
    # DYNAMIC WEIGHTING (Adaptive Signal Weights v2.0)
    # =========================================================================
    # Static weights cause poor performance in changing regimes
    # Dynamic weights adapt based on market conditions

    enable_dynamic_weights: bool = True

    # Base weights (used when dynamic weighting is disabled or as starting point)
    # v2.1: Rebalanced to include orderbook agent (must sum to 1.0)
    base_liquidation_weight: float = 0.30   # Was 0.35, reduced by 5%
    base_funding_weight: float = 0.22       # Was 0.25, reduced by 3%
    base_oi_weight: float = 0.18            # Was 0.20, reduced by 2%
    base_volume_weight: float = 0.15        # Was 0.20, reduced by 5%
    base_orderbook_weight: float = 0.15     # NEW: Order book imbalance

    # Dynamic weight adjustment factors
    # Weights shift based on market regime and signal reliability
    weight_adjustment_ranges: Dict[str, float] = field(
        default_factory=lambda: {
            "liquidation": 0.15,  # Can shift ±15% from base
            "funding": 0.10,  # Can shift ±10% from base
            "open_interest": 0.10,  # Can shift ±10% from base
            "volume": 0.10,  # Can shift ±10% from base
            "orderbook": 0.10,  # Can shift ±10% from base (5-25%)
        }
    )

    # =========================================================================
    # MARKET REGIME DETECTION (Regime-Aware Trading v2.0)
    # =========================================================================
    # Different strategies work in different market conditions
    # Regime detection adapts signal interpretation and weights

    enable_regime_detection: bool = True

    # Volatility regime thresholds (based on ATR as % of price)
    vol_low_threshold: float = 0.015  # <1.5% ATR = low vol (consolidation)
    vol_high_threshold: float = 0.040  # >4% ATR = high vol (breakout/trend)

    # Trend regime thresholds (based on ADX)
    adx_trend_threshold: float = 25.0  # ADX > 25 = trending
    adx_strong_threshold: float = 35.0  # ADX > 35 = strong trend

    # Regime-specific signal multipliers
    regime_multipliers: Dict[str, Dict[str, float]] = field(
        default_factory=lambda: {
            "low_vol": {  # Range-bound, consolidation
                "liquidation": 0.7,  # Less reliable in chop
                "funding": 1.2,  # More important for mean reversion
                "open_interest": 0.8,  # Less predictive
                "volume": 1.0,  # Standard importance
                "orderbook": 1.3,  # Subtle imbalances matter more in quiet markets
            },
            "high_vol": {  # Breakout, high volatility
                "liquidation": 1.3,  # Very reliable (forced moves)
                "funding": 0.9,  # Less reliable (extremes common)
                "open_interest": 1.2,  # Very important (commitment)
                "volume": 1.4,  # Critical for confirmation
                "orderbook": 0.8,  # Spreads widen, less reliable
            },
            "trending": {  # Clear directional bias
                "liquidation": 1.2,  # Reliable for continuation
                "funding": 1.1,  # Good for trend confirmation
                "open_interest": 1.3,  # Excellent for trend strength
                "volume": 1.2,  # Important for momentum
                "orderbook": 1.1,  # Confirms trend direction
            },
            "ranging": {  # No clear trend
                "liquidation": 0.8,  # Less reliable
                "funding": 1.3,  # Excellent for mean reversion
                "open_interest": 0.7,  # Less predictive
                "volume": 0.9,  # Standard
                "orderbook": 1.4,  # Shows who's stacking - excellent in ranges
            },
        }
    )

    # =========================================================================
    # DATA PATHS
    # =========================================================================
    @property
    def data_dir(self) -> Path:
        return PROJECT_ROOT / "src" / "data" / "crypto_polymarket"

    @property
    def markets_dir(self) -> Path:
        return self.data_dir / "markets"

    @property
    def signals_dir(self) -> Path:
        return self.data_dir / "signals"

    @property
    def predictions_dir(self) -> Path:
        return self.data_dir / "predictions"

    @property
    def trades_dir(self) -> Path:
        return self.data_dir / "trades"

    @property
    def positions_dir(self) -> Path:
        return self.data_dir / "positions"

    @property
    def min_market_liquidity(self) -> float:
        """Alias for min_market_liquidity_usd for backward compatibility."""
        return self.min_market_liquidity_usd

    def validate_weights(self) -> bool:
        """Ensure signal weights sum to 1.0"""
        total = self.liquidation_weight + self.whale_weight
        return abs(total - 1.0) < 0.01

    def validate_credentials(self) -> dict:
        """Check which credentials are configured"""
        return {
            "anthropic": bool(self.anthropic_api_key),
            "openai": bool(self.openai_api_key),
            "deepseek": bool(self.deepseek_api_key),
            "xai": bool(self.xai_api_key),
            "tradehive": bool(self.tradehive_api_key),
            "polymarket": bool(
                self.polymarket_private_key and self.polymarket_funder_address
            ),
        }

    def is_live_trading_enabled(self) -> bool:
        """Check if live trading is configured and enabled"""
        return (
            self.execution_mode == ExecutionMode.LIVE
            and bool(self.polymarket_private_key)
            and bool(self.polymarket_funder_address)
        )


# Default configuration instance
default_config = CryptoPolymarketConfig()


def get_config() -> CryptoPolymarketConfig:
    """Get the default configuration instance"""
    return default_config
