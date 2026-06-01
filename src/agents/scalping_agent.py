"""
TradeHive's Scalping Strategy Generator Agent v6.4 - DUPLICATE FIX

This agent uses the AI SWARM (all available models) to generate and validate
SCALPING strategies optimized for PURE ALPHA GENERATION.

NEW IN v6.1 - COUNCIL OF ADVISORS IMPROVEMENTS:
- 🚀 PARALLEL GENERATION: ALL models generate simultaneously!
  4 models = 4 strategies per cycle (Marcus Chen's suggestion)
- 🐟🦈🐋 MODE PERSONALITIES: PIRANHA, SHARK, WHALE modes!
  (Luna Martinez's fun naming suggestion)
- 🎯 BEHAVIORAL EDGE TECHNIQUES: Exploit retail trader mistakes!
  FOMO fades, gap fades, breakout traps, panic wick scalps
  (Luna Martinez's behavioral patterns suggestion)

v6.0 Features (retained):
- MODES: 1m_hft, 5m_momentum, 15m_swing (configurable!)
- PURE ALPHA FOCUS - no cost concerns (backtester handles that)
- Mode-specific techniques optimized for each timeframe's edge sources
- Quant mindset: WHY does edge exist? (behavioral, liquidity, information)
- "BE CREATIVE - let backtester validate!" philosophy

MODE-SPECIFIC INDICATOR PERIODS:
  * 1m HFT (PIRANHA): RSI 3-7, EMA 3/5/8/13, MACD 5/13/5, BB 10-15
  * 5m Momentum (SHARK): RSI 7-14, EMA 5/9/21/34, MACD 8/21/5, BB 15-20
  * 15m Swing (WHALE): RSI 9-21, EMA 9/21/50/100, MACD 12/26/9, BB 20-25

v5.0 Features (retained):
- 50+ techniques (all standard indicators)
- Volume as LEADING indicator
- ALL strategies EXECUTABLE by backtester!

v4.0 Features (retained):
- Adaptive technique weighting by historical WIN RATE and SHARPE ratio
- ATR-based dynamic stops and targets (scales with volatility)
- Enforced 2:1 minimum risk/reward ratio for all strategies
- Multi-confirmation entries required (2+ signals for every trade)
- Performance tracking to learn from backtest results

v3.0 Features (retained):
- Weighted technique rotation - ADAPTIVE to performance
- Semantic fingerprinting for duplicate detection
- Novelty scoring system
- Dynamic prompts with strategy history injection

v2.0 Features (retained):
- Uses ALL AI models from .env via SwarmAgent
- AI Consensus validation - 50%+ models must agree
- RBI Agent integration - outputs to ideas.txt

QUANT COUNCIL PHILOSOPHY:
- Scalping Agent = Pure alpha/edge discovery
- RBI Backtester = Validates if edge survives costs
- Volume LEADS price, not confirms
- Let data decide - don't self-censor!

Created with love by TradeHive
"""

# ============================================
# SCALPING AGENT v6.4 CONFIG - DUPLICATE PREVENTION FIX
# ============================================

# ============================================
# SCALPING MODE SELECTION
# ============================================
# Options: "1m_hft", "5m_momentum", "15m_swing"
# This will be set at startup via user prompt
SCALPING_MODE = "5m_contrarian"  # Default mode (can be changed at startup)

# Generation interval (seconds between ideas)
GENERATION_INTERVAL = 5  # Fast generation - let backtester filter bad ideas!

# ============================================
# CONSENSUS DISABLED (v6.0)
# ============================================
# Bad strategies will fail in backtesting anyway - no need to pre-filter
# This speeds up idea generation significantly!
SKIP_CONSENSUS = True  # Set to False to re-enable swarm validation

# Legacy settings (only used if SKIP_CONSENSUS = False)
MIN_CONSENSUS_THRESHOLD = 0.5

# Strategy validation - require these components
REQUIRED_COMPONENTS = ["entry", "exit", "stop"]

# Use swarm mode (all models) or single model for GENERATION
USE_SWARM_MODE = True

# v6.1 - PARALLEL MODE: Generate with ALL models simultaneously!
# When True: 4 models = 4 ideas per cycle (more throughput!)
# When False: Use original swarm mode (1 random model per cycle)
PARALLEL_MODE = True  # Marcus Chen's suggestion - maximize idea throughput!

# Single model config (if USE_SWARM_MODE = False and PARALLEL_MODE = False)
SINGLE_MODEL_CONFIG = {"type": "deepseek", "name": "deepseek-v4-flash"}

# Market context - fetch current market data before generating
USE_MARKET_CONTEXT = False  # Set to True to add BTC/ETH context to prompts

# ============================================
# v4.0 ALPHA MODE - QUANT COUNCIL SETTINGS
# ============================================

# Performance tracking file (for adaptive technique selection)
TECHNIQUE_PERFORMANCE_FILE = None  # Set in setup_files()

# Minimum risk/reward ratio (2:1 = target must be 2x stop loss)
MIN_RISK_REWARD_RATIO = 2.0

# Adaptive technique selection weights
ADAPTIVE_CONFIG = {
    "win_rate_weight": 0.4,  # Weight for historical win rate
    "sharpe_weight": 0.3,  # Weight for average Sharpe ratio
    "diversity_weight": 0.2,  # Weight for underused techniques
    "recency_weight": 0.1,  # Weight for recent performance
    "min_samples": 3,  # Minimum backtests before using adaptive weights
    "default_win_rate": 0.5,  # Assumed win rate for new techniques
    "default_sharpe": 1.0,  # Assumed Sharpe for new techniques
}

# Quality requirements for generated strategies
QUALITY_REQUIREMENTS = {
    "require_volume_filter": True,  # Must include volume confirmation
    "require_confirmation": True,  # Must have 2+ entry signals
    "min_risk_reward": 2.0,  # Minimum R/R ratio
    "require_atr_sizing": True,  # Prefer ATR-based stops/targets
}

# ============================================
# PROMPTS - DYNAMIC GENERATION SYSTEM
# ============================================

# ============================================
# 🔥 MODE-SPECIFIC TECHNIQUE LIBRARIES (v6.0)
# ============================================
# Each mode has techniques optimized for its timeframe
# Techniques are selected based on SCALPING_MODE setting

# 1m HFT Techniques - Micro-structure patterns, mean reversion, noise exploitation
HFT_TECHNIQUES = [
    # Micro mean reversion (core HFT edge)
    {
        "name": "Micro RSI Snap",
        "indicator": "RSI",
        "params": {"period": [3, 5], "extreme": [15, 85]},
    },
    {
        "name": "RSI Velocity Burst",
        "indicator": "RSI",
        "params": {"period": [5], "momentum": [5, 10], "vol_confirm": [1.5, 2.0]},
    },
    {
        "name": "VWAP Rubber Band",
        "indicator": "VWAP",
        "params": {"std": [1.5, 2.0], "snap_target": [0.5, 1.0]},
    },
    {
        "name": "BB Extreme Touch",
        "indicator": "BB",
        "params": {"period": [10], "std": [2.5], "reversal": True},
    },
    {
        "name": "BB Micro Squeeze",
        "indicator": "BB",
        "params": {"period": [10, 15], "std": [1.5, 2.0], "squeeze_pct": [0.5, 0.8]},
    },
    # Volume-driven (information asymmetry)
    {
        "name": "Volume Spike Fade",
        "indicator": "VOL",
        "params": {"spike": [2.5, 3.0], "fade_bars": [2, 3]},
    },
    {
        "name": "Exhaustion Candle",
        "indicator": "VOL",
        "params": {"vol_spike": [3.0], "wick_ratio": [0.6, 0.7]},
    },
    {
        "name": "Volume Spike Entry",
        "indicator": "VOL",
        "params": {"spike_mult": [2.0, 2.5, 3.0], "ma_period": [5, 10]},
    },
    {
        "name": "OBV Micro Divergence",
        "indicator": "OBV",
        "params": {"lookback": [5, 7, 10]},
    },
    # Micro momentum
    {
        "name": "EMA Micro Thrust",
        "indicator": "EMA",
        "params": {"fast": [3], "slow": [8], "vol_confirm": True},
    },
    {
        "name": "Stoch Velocity",
        "indicator": "STOCH",
        "params": {"k": [5], "velocity": [20, 30]},
    },
    {
        "name": "Micro MACD Cross",
        "indicator": "MACD",
        "params": {"fast": [5, 8], "slow": [13, 21], "signal": [3, 5]},
    },
    {
        "name": "Fast EMA Cross",
        "indicator": "EMA",
        "params": {"fast": [3, 5], "slow": [8, 13]},
    },
    # VWAP-based (structural)
    {
        "name": "VWAP Breakout Scalp",
        "indicator": "VWAP",
        "params": {"break_std": [2.0], "vol_surge": [1.5, 2.0]},
    },
    {
        "name": "VWAP Bounce",
        "indicator": "VWAP",
        "params": {"std_bands": [1, 1.5, 2], "vol_confirm": [1.2, 1.5]},
    },
    {
        "name": "VWAP + RSI Scalp",
        "indicator": "VWAP",
        "params": {"vwap_std": [1.5], "rsi_period": [5], "rsi_level": [30, 70]},
    },
    # Stochastic extremes
    {
        "name": "Stoch Micro Snap",
        "indicator": "STOCH",
        "params": {"k": [5, 7], "d": [3], "extreme": [10, 90]},
    },
    {
        "name": "Stoch + RSI HFT",
        "indicator": "STOCH",
        "params": {"stoch_k": [5], "rsi_period": [5], "double_extreme": True},
    },
    # ATR volatility
    {
        "name": "ATR Micro Breakout",
        "indicator": "ATR",
        "params": {"period": [5, 7], "mult": [1.0, 1.5, 2.0]},
    },
    {
        "name": "ATR Volatility Expansion",
        "indicator": "ATR",
        "params": {"period": [5, 7], "expansion": [1.3, 1.5, 2.0]},
    },
    # Creative combos (edge stacking)
    {
        "name": "Triple Micro Confirm",
        "indicator": "COMBO",
        "params": {"rsi": [5], "ema_cross": [5, 13], "vol_mult": [1.5]},
    },
    {
        "name": "BB + Stoch Reversal",
        "indicator": "COMBO",
        "params": {"bb_period": [10], "stoch_k": [5], "extreme_combo": True},
    },
    {
        "name": "VWAP + BB + RSI",
        "indicator": "COMBO",
        "params": {"vwap_std": [1.5], "bb_period": [10], "rsi": [5]},
    },
    {
        "name": "Momentum + Volume + EMA",
        "indicator": "COMBO",
        "params": {"mom_period": [5], "vol_spike": [2.0], "ema": [8]},
    },
    # 🎯 BEHAVIORAL EDGE - Exploit retail trader mistakes (Luna Martinez)
    {
        "name": "Retail FOMO Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "RSI crosses above 30 from oversold",
            "condition": "volume spike + price fails to break resistance in 2 candles",
            "action": "fade the move (short)",
            "edge": "Retail rushes in on first sign of recovery, smart money sells into it",
        },
    },
    {
        "name": "Micro Gap Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "gap > 0.3% from prior close",
            "wait_bars": [3, 5],
            "action": "fade gap direction",
            "edge": "Retail chases gaps, mean reversion wins 60%+ on small gaps",
        },
    },
    {
        "name": "First Bar Trap",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "first 1m bar strong direction",
            "condition": "low volume day or after news",
            "action": "fade after 3-5 bars if direction fails",
            "edge": "Emotional retail trades first bar, smart money fades",
        },
    },
    {
        "name": "Breakout Trap Micro",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price breaks key level (prev high/low)",
            "condition": "volume < 1.5x average on break",
            "action": "fade the false breakout",
            "edge": "Weak volume breakouts trap retail, revert 70%+ of time",
        },
    },
    {
        "name": "Panic Wick Scalp",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "sudden spike down with long wick",
            "condition": "wick > 60% of candle, quick recovery",
            "action": "buy the wick recovery",
            "edge": "Panic selling creates liquidity for smart money accumulation",
        },
    },
    {
        "name": "Round Number Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price approaches round number (00, 50)",
            "condition": "weak momentum approaching level",
            "action": "fade at round number",
            "edge": "Retail clusters stops/orders at round numbers",
        },
    },
]

# 5m Momentum Techniques - Trend continuation, breakouts, momentum bursts
MOMENTUM_TECHNIQUES = [
    # Trend continuation
    {
        "name": "EMA Alignment Ride",
        "indicator": "EMA",
        "params": {"emas": [5, 9, 21], "aligned_bars": [3, 5]},
    },
    {
        "name": "EMA Pullback Entry",
        "indicator": "EMA",
        "params": {"fast": [9], "slow": [21], "pullback_bars": [2, 3]},
    },
    {
        "name": "Triple EMA Thrust",
        "indicator": "EMA",
        "params": {"fast": [5], "mid": [9], "slow": [21], "confirm": [2]},
    },
    # MACD momentum
    {
        "name": "MACD Momentum Burst",
        "indicator": "MACD",
        "params": {
            "fast": [8],
            "slow": [21],
            "signal": [5],
            "histogram_expansion": [1.5, 2.0],
        },
    },
    {
        "name": "MACD Zero Cross",
        "indicator": "MACD",
        "params": {"fast": [8, 12], "slow": [21, 26], "signal": [5, 9]},
    },
    {
        "name": "MACD + EMA Filter",
        "indicator": "MACD",
        "params": {"macd_fast": [8], "macd_slow": [21], "ema_filter": [34, 50]},
    },
    # Breakout patterns
    {
        "name": "BB Squeeze Pop",
        "indicator": "BB",
        "params": {
            "period": [15, 20],
            "squeeze_bars": [5, 8],
            "expansion_trigger": True,
        },
    },
    {
        "name": "Volume Breakout",
        "indicator": "VOL",
        "params": {"breakout_mult": [2.0, 2.5], "price_break": True},
    },
    {
        "name": "ATR Expansion Breakout",
        "indicator": "ATR",
        "params": {"period": [10, 14], "expansion": [1.5, 2.0]},
    },
    # RSI momentum
    {
        "name": "RSI Momentum Surge",
        "indicator": "RSI",
        "params": {"period": [7, 9], "momentum_zone": [50, 70], "breakout": True},
    },
    {
        "name": "RSI + Volume Confirmation",
        "indicator": "RSI",
        "params": {"period": [9, 14], "vol_mult": [1.5, 2.0]},
    },
    {
        "name": "RSI Divergence",
        "indicator": "RSI",
        "params": {"period": [9, 14], "lookback": [5, 10]},
    },
    # VWAP trends
    {
        "name": "VWAP Trend Ride",
        "indicator": "VWAP",
        "params": {"trend_above": True, "vol_confirm": [1.2, 1.5]},
    },
    {
        "name": "VWAP Breakout Momentum",
        "indicator": "VWAP",
        "params": {"break_std": [1.5, 2.0], "vol_surge": [1.5, 2.0]},
    },
    # Stochastic momentum
    {
        "name": "Stochastic Momentum Cross",
        "indicator": "STOCH",
        "params": {"k": [9, 14], "d": [3], "momentum_zone": [50, 80]},
    },
    # Creative combos
    {
        "name": "EMA + RSI + Volume",
        "indicator": "COMBO",
        "params": {"ema": [9, 21], "rsi": [9, 14], "vol_ma": [15]},
    },
    {
        "name": "MACD + Stoch Combo",
        "indicator": "COMBO",
        "params": {"stoch_k": [9, 14], "macd_fast": [8]},
    },
    {
        "name": "Triple Momentum Confirm",
        "indicator": "COMBO",
        "params": {"rsi": [9], "macd": True, "vol": [1.5]},
    },
    # 🎯 BEHAVIORAL EDGE - Exploit retail trader mistakes (Luna Martinez)
    {
        "name": "Gap Fade Morning",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "overnight gap > 0.5%",
            "wait": "30 minutes after open (6 bars)",
            "action": "fade gap direction if momentum stalls",
            "edge": "Retail chases gaps, professional money fades 60-70% fill rate",
        },
    },
    {
        "name": "Lunch Hour Chop Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "time": "11:30-13:00 EST (low volume)",
            "condition": "range bound, low volume",
            "action": "fade extremes of the range",
            "edge": "Thin liquidity causes retail to overshoot, reverts quickly",
        },
    },
    {
        "name": "FOMO Momentum Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "3+ consecutive strong bars same direction",
            "condition": "RSI extreme + volume climax",
            "action": "fade the exhaustion",
            "edge": "Retail piles in at end of moves, smart money exits",
        },
    },
    {
        "name": "Failed Breakout Trap",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price breaks key level",
            "condition": "fails to hold above/below for 2-3 bars",
            "action": "trade reversal back through level",
            "edge": "Breakout traders get trapped, stops fuel reversal",
        },
    },
    {
        "name": "News Spike Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "sharp move on news/event",
            "wait": "5-10 minutes for dust to settle",
            "action": "fade 50% of the move",
            "edge": "Retail overreacts to news, mean reversion wins",
        },
    },
]

# 15m Swing Techniques - Trend riding, S/R reactions, exhaustion patterns
SWING_TECHNIQUES = [
    # Trend riding
    {
        "name": "EMA Cloud Ride",
        "indicator": "EMA",
        "params": {"fast": [9], "slow": [21], "cloud": True},
    },
    {
        "name": "EMA Golden Cross",
        "indicator": "EMA",
        "params": {"fast": [21], "slow": [50], "confirm_bars": [2, 3]},
    },
    {
        "name": "Triple EMA Trend",
        "indicator": "EMA",
        "params": {"fast": [9], "mid": [21], "slow": [50], "alignment": True},
    },
    # RSI patterns
    {
        "name": "RSI Trend Pullback",
        "indicator": "RSI",
        "params": {"period": [14], "pullback_zone": [40, 60]},
    },
    {
        "name": "RSI Oversold Bounce",
        "indicator": "RSI",
        "params": {"period": [14, 21], "oversold": [25, 30], "overbought": [70, 75]},
    },
    {
        "name": "Exhaustion Divergence",
        "indicator": "RSI",
        "params": {"period": [14], "divergence_bars": [5, 10]},
    },
    # Bollinger patterns
    {
        "name": "BB Mean Reversion",
        "indicator": "BB",
        "params": {"period": [20, 25], "std": [2.0, 2.5], "rsi_confirm": [30, 70]},
    },
    {
        "name": "BB Squeeze Breakout",
        "indicator": "BB",
        "params": {"period": [20], "std": [2.0], "squeeze_bars": [8, 12]},
    },
    {
        "name": "BB Walk",
        "indicator": "BB",
        "params": {"period": [20], "std": [2.0], "consecutive": [3, 4]},
    },
    # MACD swing
    {
        "name": "MACD Swing Cross",
        "indicator": "MACD",
        "params": {"fast": [12], "slow": [26], "signal": [9]},
    },
    {
        "name": "MACD Histogram Divergence",
        "indicator": "MACD",
        "params": {"fast": [12], "slow": [26], "signal": [9], "divergence": True},
    },
    # Stochastic swing
    {
        "name": "Stochastic Oversold Swing",
        "indicator": "STOCH",
        "params": {"k": [14, 21], "d": [3], "oversold": [20, 25]},
    },
    {
        "name": "Stochastic Cross",
        "indicator": "STOCH",
        "params": {"k": [14], "d": [3], "smooth": [3]},
    },
    # Session-based
    {
        "name": "Session Extreme Fade",
        "indicator": "RANGE",
        "params": {"session_pct": [90, 95], "reversal": True},
    },
    {
        "name": "Session Open Breakout",
        "indicator": "RANGE",
        "params": {"open_range_bars": [4, 6], "breakout": True},
    },
    # Volume exhaustion
    {
        "name": "Volume Climax Reversal",
        "indicator": "VOL",
        "params": {"climax_mult": [3.0, 4.0], "reversal_bars": [2, 3]},
    },
    {
        "name": "OBV Divergence",
        "indicator": "OBV",
        "params": {"lookback": [10, 14, 20]},
    },
    # ATR swing
    {
        "name": "ATR Channel Breakout",
        "indicator": "ATR",
        "params": {"period": [14, 20], "mult": [2.0, 2.5]},
    },
    # Creative combos
    {
        "name": "RSI + BB Combo",
        "indicator": "COMBO",
        "params": {"rsi": [14], "bb_period": [20], "bb_std": [2.0]},
    },
    {
        "name": "EMA + RSI + Volume",
        "indicator": "COMBO",
        "params": {"ema": [21, 50], "rsi": [14], "vol_ma": [20]},
    },
    {
        "name": "Triple Confirmation",
        "indicator": "COMBO",
        "params": {"ind1": "RSI", "ind2": "MACD", "ind3": "VOL"},
    },
    # 🎯 BEHAVIORAL EDGE - Exploit retail trader mistakes (Luna Martinez)
    {
        "name": "First Hour Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "first 15m candle strong direction",
            "wait": "30-45 minutes",
            "condition": "reversal pattern forms + volume decline",
            "action": "fade first hour direction",
            "edge": "Retail trades first hour emotionally, 60% reversals by lunch",
        },
    },
    {
        "name": "Session High/Low Trap",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price approaches session high/low",
            "condition": "multiple tests without break + declining volume",
            "action": "fade the failed breakout attempt",
            "edge": "Retail clusters stops beyond session extremes",
        },
    },
    {
        "name": "End of Day Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "strong move in last 30-60 minutes",
            "condition": "extended from VWAP + overbought/oversold",
            "action": "fade for overnight mean reversion",
            "edge": "Late retail FOMO creates overnight reversal opportunities",
        },
    },
    {
        "name": "Trend Exhaustion Trap",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "3+ consecutive trend bars same direction",
            "condition": "RSI extreme + volume declining",
            "action": "fade the exhaustion",
            "edge": "Late trend joiners provide exit liquidity for smart money",
        },
    },
    {
        "name": "Support/Resistance Fake",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price breaks S/R level briefly",
            "condition": "immediate reversal back through level",
            "action": "trade in direction of reversal",
            "edge": "Stop hunts trap breakout traders, fuel reversal moves",
        },
    },
    {
        "name": "Weekend Gap Setup",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "Monday gap from Friday close",
            "wait": "first 30-60 minutes of Monday",
            "action": "trade toward gap fill if momentum aligns",
            "edge": "Weekend gaps fill 70%+ of time, retail fights direction",
        },
    },
]

# ============================================
# VIPER MODE - Contrarian/Retail Fade Techniques
# "Strike fast on retail mistakes, venomous precision"
# Exploits: FOMO, breakout traps, panic reversals, round numbers, gaps
# ============================================
CONTRARIAN_TECHNIQUES = [
    # ============================================
    # CATEGORY 1: FOMO FADE PATTERNS (7 techniques)
    # Retail chases exhausted moves, smart money exits
    # ============================================
    {
        "name": "FOMO Exhaustion Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "3+ consecutive strong bars same direction",
            "condition": "RSI extreme (>75 or <25) + volume climax (>2.5x avg)",
            "action": "fade the exhaustion",
            "edge": "Late retail piles in at move exhaustion, providing exit liquidity",
        },
    },
    {
        "name": "Momentum Climax Reversal",
        "indicator": "COMBO",
        "params": {
            "rsi_period": [7, 9],
            "rsi_extreme": [80, 20],
            "vol_climax": [2.5, 3.0],
            "consecutive_bars": [3, 4, 5],
            "fade_after": True,
        },
    },
    {
        "name": "VWAP Overextension Snap",
        "indicator": "VWAP",
        "params": {
            "std_deviation": [2.0, 2.5, 3.0],
            "rsi_confirm": [75, 25],
            "action": "mean reversion to VWAP",
            "edge": "Retail chases moves far from VWAP, mean reversion wins 65%+",
        },
    },
    {
        "name": "Parabolic Exhaustion",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price accelerating (each bar larger than previous)",
            "condition": "3+ bars of acceleration + volume spike",
            "action": "fade when acceleration stalls",
            "edge": "Parabolic moves attract retail FOMO, always revert",
        },
    },
    {
        "name": "Social Spike Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "sudden volume spike >3x with no clear catalyst",
            "wait_bars": [3, 5],
            "condition": "price fails to continue after initial spike",
            "action": "fade 50% of the move",
            "edge": "Viral posts cause retail piling, smart money sells into it",
        },
    },
    {
        "name": "Retail Hour Exhaustion",
        "indicator": "BEHAVIORAL",
        "params": {
            "time_window": "9:30-10:30 EST (retail active)",
            "trigger": "strong directional move in first hour",
            "condition": "RSI extreme + momentum stalling",
            "action": "fade for mean reversion",
            "edge": "Retail trades emotionally at open, professionals fade by 10:30",
        },
    },
    {
        "name": "Late Momentum Fade",
        "indicator": "COMBO",
        "params": {
            "macd_fast": [8],
            "macd_slow": [21],
            "condition": "MACD histogram divergence from price",
            "vol_declining": True,
            "action": "fade when momentum weakens but price continues",
            "edge": "Retail follows price, smart money watches momentum",
        },
    },
    # ============================================
    # CATEGORY 2: BREAKOUT TRAP PATTERNS (6 techniques)
    # False breakouts trap retail, reversals provide alpha
    # ============================================
    {
        "name": "Failed Breakout Trap",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price breaks key level (prev high/low, round number)",
            "condition": "volume < 1.5x average on breakout",
            "wait_bars": [2, 3],
            "action": "fade when price reverses back through level",
            "edge": "Weak volume breakouts are traps, 70%+ revert",
        },
    },
    {
        "name": "Bull Bear Trap Classic",
        "indicator": "COMBO",
        "params": {
            "bb_period": [15, 20],
            "bb_std": [2.0],
            "trigger": "price breaks BB, then re-enters within 2 bars",
            "vol_on_break": [1.0, 1.5],
            "action": "trade reversal direction",
            "edge": "BB breakout with weak volume traps trend followers",
        },
    },
    {
        "name": "Range Breakout Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price breaks consolidation range (5+ bars)",
            "condition": "breakout bar has long wick + volume declining",
            "action": "fade back into range",
            "edge": "Retail breakout traders get trapped outside range",
        },
    },
    {
        "name": "Double Pattern Trap",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price approaches previous swing high/low",
            "condition": "fails to break by 0.1% on reduced volume",
            "action": "trade reversal from pattern",
            "edge": "Retail expects breakout at double patterns, fails often",
        },
    },
    {
        "name": "Resistance Rejection Scalp",
        "indicator": "COMBO",
        "params": {
            "ema_period": [21, 34],
            "trigger": "price touches EMA resistance with declining momentum",
            "rsi_divergence": True,
            "action": "fade at resistance",
            "edge": "Retail buys breakouts, smart money sells at resistance",
        },
    },
    {
        "name": "ORB Breakout Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price breaks 15-min opening range",
            "condition": "low conviction break (small bar, weak volume)",
            "wait_bars": [2, 4],
            "action": "fade failed breakout back to range mid",
            "edge": "ORB failures trap early breakout traders",
        },
    },
    # ============================================
    # CATEGORY 3: PANIC REVERSAL PATTERNS (5 techniques)
    # Buy retail panic, sell retail euphoria
    # ============================================
    {
        "name": "Panic Wick Reversal",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "sudden spike with long wick (>60% of candle)",
            "condition": "quick recovery within same bar + volume spike",
            "action": "trade the wick recovery",
            "edge": "Panic creates liquidity for smart money accumulation",
        },
    },
    {
        "name": "Capitulation Reversal",
        "indicator": "COMBO",
        "params": {
            "rsi_period": [7, 9],
            "rsi_extreme": [15, 20],
            "vol_spike": [3.0, 4.0],
            "condition": "RSI extreme + volume climax + long wick",
            "action": "buy capitulation",
            "edge": "Mass retail panic creates optimal entries",
        },
    },
    {
        "name": "Flash Crash Recovery",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price drops >1% in 1-2 bars",
            "condition": "immediate bounce begins (higher low forms)",
            "action": "buy the recovery",
            "edge": "Flash crashes are liquidity hunts, not trend changes",
        },
    },
    {
        "name": "Stop Hunt Reversal",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price spikes through obvious stop level (prev low)",
            "condition": "immediate reversal (V-shape), volume spike",
            "action": "trade reversal direction",
            "edge": "Stop hunts accumulate, reversals are predictable",
        },
    },
    {
        "name": "Euphoria Top Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price makes new high with extreme RSI (>80)",
            "condition": "volume climax + small body/long upper wick",
            "action": "fade the euphoria",
            "edge": "Retail buys tops with maximum confidence, distribution follows",
        },
    },
    # ============================================
    # CATEGORY 4: ROUND NUMBER & PSYCHOLOGICAL LEVELS (4 techniques)
    # Retail clusters at round numbers, creates fade opportunities
    # ============================================
    {
        "name": "Round Number Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price approaches round number (x.00, x.50, x000)",
            "condition": "momentum weakening approaching level",
            "action": "fade at round number",
            "edge": "Retail clusters stops/orders at round numbers",
        },
    },
    {
        "name": "Psychological Level Trap",
        "indicator": "COMBO",
        "params": {
            "levels": ["round_100", "round_500", "round_1000"],
            "trigger": "price pierces level briefly",
            "condition": "fails to hold beyond level for 2 bars",
            "action": "trade reversal through level",
            "edge": "Retail breakout orders at psych levels get trapped",
        },
    },
    {
        "name": "Whole Number Magnet",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "price hovering near round number",
            "condition": "multiple touches without decisive break",
            "action": "fade moves away from the level",
            "edge": "Price gravitates to round numbers, use as mean",
        },
    },
    {
        "name": "Previous Day Level Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "levels": ["prev_close", "prev_high", "prev_low"],
            "trigger": "price approaches previous day level",
            "condition": "weak momentum, declining volume",
            "action": "fade at level",
            "edge": "Retail watches these levels, creates clustering",
        },
    },
    # ============================================
    # CATEGORY 5: GAP FADE PATTERNS (3 techniques)
    # Gap trading failures create contrarian opportunities
    # ============================================
    {
        "name": "Gap Fill Setup",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "overnight gap > 0.5%",
            "wait": "first 15-30 minutes",
            "condition": "momentum stalls, fails to continue gap direction",
            "action": "fade toward gap fill",
            "edge": "70%+ of gaps fill same day, retail fights direction",
        },
    },
    {
        "name": "Exhaustion Gap Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "gap after extended move (3+ days same direction)",
            "condition": "gap opens at extreme RSI levels",
            "action": "fade the exhaustion gap",
            "edge": "Exhaustion gaps signal trend end, retail piles in late",
        },
    },
    {
        "name": "Weekend Gap Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "Monday gap from Friday close",
            "wait": "30-60 minutes after Monday open",
            "condition": "gap direction momentum stalls",
            "action": "trade toward gap fill",
            "edge": "Weekend gaps are retail-driven, fill 65%+",
        },
    },
    # ============================================
    # CATEGORY 6: NEWS & EVENT FADE PATTERNS (3 techniques)
    # Retail overreacts to news, creates fade opportunities
    # ============================================
    {
        "name": "News Spike Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "sharp move on news/event",
            "wait_bars": [3, 6, 10],
            "condition": "initial momentum exhausted, range forming",
            "action": "fade 50% of the move",
            "edge": "Retail overreacts to news, mean reversion wins 60%+",
        },
    },
    {
        "name": "Earnings Overreaction Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "post-earnings gap or spike",
            "wait": "10-15 minutes for dust to settle",
            "condition": "extreme RSI + volume exhaustion",
            "action": "fade the overreaction",
            "edge": "Initial earnings moves overshoot, revert 50%+ often",
        },
    },
    {
        "name": "Economic Data Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "trigger": "spike on economic data release",
            "wait": "5-10 minutes",
            "condition": "initial reaction fades, opposite pressure building",
            "action": "fade the knee-jerk reaction",
            "edge": "Algo first-reaction often wrong, reversion follows",
        },
    },
    # ============================================
    # CATEGORY 7: SESSION & TIME-BASED PATTERNS (2 techniques)
    # Session transitions create contrarian opportunities
    # ============================================
    {
        "name": "Lunch Hour Chop Fade",
        "indicator": "BEHAVIORAL",
        "params": {
            "time_window": "11:30-13:00 EST",
            "condition": "range-bound, low volume, thin liquidity",
            "action": "fade extremes of the range",
            "edge": "Thin liquidity causes overshoots, quick reversions",
        },
    },
    {
        "name": "End of Day Reversal",
        "indicator": "BEHAVIORAL",
        "params": {
            "time_window": "15:00-15:45 EST",
            "trigger": "strong directional move in final hour",
            "condition": "extended from VWAP + extreme RSI",
            "action": "fade for overnight mean reversion",
            "edge": "Late retail FOMO creates overnight reversal opportunities",
        },
    },
]

# Select techniques based on SCALPING_MODE
MODE_TECHNIQUES = {
    "1m_hft": HFT_TECHNIQUES,
    "5m_momentum": MOMENTUM_TECHNIQUES,
    "15m_swing": SWING_TECHNIQUES,
    "5m_contrarian": CONTRARIAN_TECHNIQUES,
}

# Active technique library based on mode
SCALPING_TECHNIQUES = MODE_TECHNIQUES.get(SCALPING_MODE, HFT_TECHNIQUES)

# ============================================
# 🚀 MODE CONFIGURATIONS - Quant Council Approved (v6.0)
# ============================================
# Each mode optimized for its timeframe's market microstructure
# Switch modes by changing SCALPING_MODE at top of file

MODE_CONFIGS = {
    "1m_hft": {
        "tf": "1m",
        "name": "🐟 PIRANHA MODE",
        "tagline": "Fast, aggressive, swarm attacks on micro-inefficiencies",
        "hold": "30 seconds to 3 minutes",
        "trades": "20-50 per day",
        "stop_atr": "0.5-1x ATR(7)",
        "target_atr": "1-2x ATR(7)",
        "stop_pct": "0.15-0.4%",
        "target_pct": "0.4-1%",
        "edge_sources": [
            "Mean reversion at micro extremes",
            "Liquidity imbalances",
            "Noise trader exploitation",
            "VWAP deviation snaps",
            "Volume spike reversals",
        ],
        "indicator_periods": {
            "rsi": [3, 5, 7],
            "ema": [3, 5, 8, 13],
            "macd": [5, 13, 5],
            "bb": [10, 15],
            "stoch": [5, 7],
            "atr": [5, 7],
        },
    },
    "5m_momentum": {
        "tf": "5m",
        "name": "🦈 SHARK MODE",
        "tagline": "Patient hunter, strikes when momentum builds",
        "hold": "5-20 minutes",
        "trades": "10-25 per day",
        "stop_atr": "1-1.5x ATR(10)",
        "target_atr": "2-3x ATR(10)",
        "stop_pct": "0.3-0.6%",
        "target_pct": "0.8-1.5%",
        "edge_sources": [
            "Trend continuation patterns",
            "Breakout momentum",
            "Volume-confirmed moves",
            "EMA alignment trends",
            "MACD momentum divergence",
        ],
        "indicator_periods": {
            "rsi": [7, 9, 14],
            "ema": [5, 9, 21, 34],
            "macd": [8, 21, 5],
            "bb": [15, 20],
            "stoch": [9, 14],
            "atr": [10, 14],
        },
    },
    "15m_swing": {
        "tf": "15m",
        "name": "🐋 WHALE MODE",
        "tagline": "Massive moves, rides the big waves",
        "hold": "15-60 minutes",
        "trades": "5-12 per day",
        "stop_atr": "1.5-2x ATR(14)",
        "target_atr": "3-4x ATR(14)",
        "stop_pct": "0.5-1%",
        "target_pct": "1.5-2.5%",
        "edge_sources": [
            "Established trend riding",
            "Support/resistance reactions",
            "Session-based patterns",
            "Higher timeframe confluence",
            "Exhaustion reversals",
        ],
        "indicator_periods": {
            "rsi": [9, 14, 21],
            "ema": [9, 21, 50, 100],
            "macd": [12, 26, 9],
            "bb": [20, 25],
            "stoch": [14, 21],
            "atr": [14, 20],
        },
    },
    "5m_contrarian": {
        "tf": "5m",
        "name": "🐍 VIPER MODE",
        "tagline": "Strike fast on retail mistakes, venomous precision",
        "hold": "3-15 minutes",
        "trades": "10-30 per day",
        "stop_atr": "1-1.5x ATR(10)",
        "target_atr": "1.5-2.5x ATR(10)",
        "stop_pct": "0.4-0.8%",
        "target_pct": "0.8-1.5%",
        "edge_sources": [
            "FOMO exhaustion reversals",
            "Failed breakout traps",
            "Panic selling capitulation",
            "Round number clustering",
            "Gap fade mean reversion",
            "News overreaction fades",
            "Retail herd behavior exploitation",
        ],
        "indicator_periods": {
            "rsi": [7, 9, 14],
            "ema": [9, 21, 34],
            "macd": [8, 21, 5],
            "bb": [15, 20],
            "stoch": [9, 14],
            "atr": [10, 14],
        },
    },
}

# Select active mode based on SCALPING_MODE setting
ACTIVE_MODE = MODE_CONFIGS[SCALPING_MODE]
TIMEFRAMES = [ACTIVE_MODE]  # Use selected mode

# Exit strategies
EXIT_STRATEGIES = [
    "fixed profit target of {profit_pct}%",
    "trailing stop of {trail_pct}% from high",
    "ATR-based exit at {atr_mult}x ATR",
    "indicator reversal (opposite signal)",
    "time-based exit after {minutes} minutes if not hit target",
    "partial exit at {partial_pct}%, remainder at {full_pct}%",
]

# Track used techniques to ensure rotation
TECHNIQUE_USAGE_FILE = None  # Set in setup_files()
INDICATOR_USAGE_FILE = None  # Set in setup_files()

# Novelty scoring configuration
NOVELTY_CONFIG = {
    "min_novelty_score": 0.4,  # Minimum novelty required (0-1)
    "underused_bonus": 0.2,  # Bonus for using underused indicators
    "combo_bonus": 0.15,  # Bonus for multi-indicator combos
    "param_variance_bonus": 0.1,  # Bonus for unusual parameters
}


def get_existing_fingerprints_summary(max_fingerprints=20):
    """
    v6.4 FIX: Get a summary of existing strategy fingerprints to prevent duplicates.
    Returns a compact string describing what indicator+parameter combos already exist.
    """
    existing_ideas = load_existing_ideas()
    if not existing_ideas:
        return ""

    # Extract fingerprints from existing ideas
    combo_counts = {}  # Track indicator combinations
    param_values = {}  # Track parameter values used

    for idea in list(existing_ideas)[:50]:  # Sample up to 50 for efficiency
        fp = extract_strategy_fingerprint(idea)

        # Track indicator combinations
        if fp["indicators"]:
            combo_key = "+".join(sorted(fp["indicators"]))
            combo_counts[combo_key] = combo_counts.get(combo_key, 0) + 1

        # Track parameter values
        for param in fp["parameters"]:
            param_values[param] = param_values.get(param, 0) + 1

    # Build summary of overused combinations
    overused_combos = [
        k for k, v in sorted(combo_counts.items(), key=lambda x: -x[1])[:8]
    ]
    overused_params = [
        k for k, v in sorted(param_values.items(), key=lambda x: -x[1])[:12]
    ]

    return overused_combos, overused_params


def get_feedback_insights_section():
    """
    v6.5 - Get performance insights from feedback connector for prompt injection.
    Returns a formatted string with top performers and underperformers.
    """
    if not FEEDBACK_ENABLED:
        return ""

    try:
        insights_text = feedback_connector.format_insights_for_prompt()
        return insights_text
    except Exception as e:
        # Silently fail - don't disrupt generation
        return ""


def build_dynamic_prompt(
    technique, timeframe, params, recent_strategies, used_indicators
):
    """Build a focused prompt for complete strategy generation - v6.4 (DUPLICATE FIX)"""

    # v6.4 FIX: Build comprehensive avoid guidance
    avoid_section = ""

    # Get existing fingerprints to avoid
    try:
        overused_combos, overused_params = get_existing_fingerprints_summary()
    except:
        overused_combos, overused_params = [], []

    # Build avoid section with more strategies (15 instead of 5)
    if recent_strategies:
        # Show more recent strategies to avoid
        strategies_to_avoid = (
            recent_strategies[-15:]
            if len(recent_strategies) > 15
            else recent_strategies
        )
        avoid_section = f"""
⚠️ CRITICAL: AVOID DUPLICATES!
These strategies ALREADY EXIST (DO NOT recreate similar ones):
{chr(10).join(f"• {s[:80]}" for s in strategies_to_avoid[-10:])}
"""

    # Add overused indicator combos to avoid
    if overused_combos:
        avoid_section += f"""
🚫 OVERUSED indicator combinations (use DIFFERENT combos):
{", ".join(overused_combos[:6])}
"""

    # Add overused parameter values to avoid
    if overused_params:
        avoid_section += f"""
🚫 OVERUSED parameter values (use DIFFERENT values):
{", ".join(overused_params[:10])}
"""

    # Get mode-specific info
    mode_name = timeframe.get("name", "Scalping")
    indicator_periods = timeframe.get("indicator_periods", {})

    # Suggest alternative parameter values to encourage novelty
    alt_rsi = [p for p in [3, 4, 6, 8, 9, 11, 12] if f"RSI_{p}" not in overused_params][
        :3
    ]
    alt_ema = [
        p
        for p in [4, 6, 7, 10, 11, 12, 14, 15, 17, 20]
        if f"EMA_{p}" not in overused_params
    ][:4]

    novelty_hints = ""
    if alt_rsi or alt_ema:
        novelty_hints = f"""
💡 SUGGESTED FRESH VALUES (less used):
- RSI periods: {alt_rsi if alt_rsi else "try 4, 6, 8, 11"}
- EMA periods: {alt_ema if alt_ema else "try 4, 7, 11, 15, 17"}
- Use UNIQUE threshold values: 18, 22, 28, 32, 72, 78, 82 (not 20, 25, 30, 70, 75, 80)
"""

    # v6.4: Enhanced prompt with better duplicate prevention
    prompt = f"""Generate ONE UNIQUE {timeframe["tf"]} scalping strategy using {technique["name"]} ({technique["indicator"]}).

PARAMETERS TO USE: {params}

REQUIREMENTS:
1. Use {technique["indicator"]} as primary indicator with SPECIFIC & UNIQUE values
2. Add ONE confirmation signal (volume, price structure, or secondary indicator)
3. Profit target: {timeframe["target_pct"]} (must be 2x stop loss)
4. Stop loss: {timeframe["stop_pct"]}
5. Hold time: {timeframe["hold"]}
6. ⭐ USE UNIQUE PARAMETER VALUES - NOT the common ones like RSI(5), RSI(7), EMA(9), EMA(21)

INDICATOR PERIODS for {timeframe["tf"]}:
- RSI: {indicator_periods.get("rsi", [7, 14])[0]} (but try nearby values like +/-2)
- EMA: {indicator_periods.get("ema", [9, 21])} (but try nearby values)
- Stoch: {indicator_periods.get("stoch", [5, 14])[0]}
- ATR: {indicator_periods.get("atr", [7, 14])[0]}
{avoid_section}{novelty_hints}{get_feedback_insights_section()}
OUTPUT YOUR STRATEGY NOW in this EXACT format:
"{timeframe["tf"]} [YourUniqueName]: Enter long when [PRIMARY SIGNAL with UNIQUE exact values] AND [CONFIRMATION], take profit at [X%] or [Xx ATR], stop loss [Y%] below entry."

Example: "1m RSIMicroSnap: Enter long when RSI(6) crosses above 22 AND volume exceeds 1.8x 8-period average, take profit at 0.7% or 1.4x ATR(6), stop loss 0.35% below entry."

YOUR COMPLETE UNIQUE STRATEGY:"""

    return prompt


def load_indicator_usage():
    """Load indicator usage counts from tracking file"""
    global INDICATOR_USAGE_FILE
    if INDICATOR_USAGE_FILE is None:
        return {}

    if not INDICATOR_USAGE_FILE.exists():
        return {}

    try:
        import json

        with open(INDICATOR_USAGE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_indicator_usage(usage):
    """Save indicator usage counts to tracking file"""
    global INDICATOR_USAGE_FILE
    if INDICATOR_USAGE_FILE is None:
        return

    try:
        import json

        with open(INDICATOR_USAGE_FILE, "w") as f:
            json.dump(usage, f, indent=2)
    except Exception as e:
        cprint(f"Warning: Could not save indicator usage: {e}", "yellow")


def load_technique_usage():
    """Load technique usage counts from tracking file"""
    global TECHNIQUE_USAGE_FILE
    if TECHNIQUE_USAGE_FILE is None:
        return {}

    if not TECHNIQUE_USAGE_FILE.exists():
        return {}

    try:
        import json

        with open(TECHNIQUE_USAGE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_technique_usage(usage):
    """Save technique usage counts to tracking file"""
    global TECHNIQUE_USAGE_FILE
    if TECHNIQUE_USAGE_FILE is None:
        return

    try:
        import json

        with open(TECHNIQUE_USAGE_FILE, "w") as f:
            json.dump(usage, f, indent=2)
    except Exception as e:
        cprint(f"Warning: Could not save technique usage: {e}", "yellow")


# ============================================
# v4.0 PERFORMANCE TRACKING FUNCTIONS
# ============================================


def load_technique_performance():
    """Load technique performance data from tracking file"""
    global TECHNIQUE_PERFORMANCE_FILE
    if TECHNIQUE_PERFORMANCE_FILE is None:
        return {}

    if not TECHNIQUE_PERFORMANCE_FILE.exists():
        return {}

    try:
        import json

        with open(TECHNIQUE_PERFORMANCE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_technique_performance(performance):
    """Save technique performance data to tracking file"""
    global TECHNIQUE_PERFORMANCE_FILE
    if TECHNIQUE_PERFORMANCE_FILE is None:
        return

    try:
        import json

        with open(TECHNIQUE_PERFORMANCE_FILE, "w") as f:
            json.dump(performance, f, indent=2)
    except Exception as e:
        cprint(f"Warning: Could not save technique performance: {e}", "yellow")


def update_technique_performance(technique_name, backtest_return, sharpe_ratio=None):
    """
    Update performance metrics for a technique after backtest results.
    Call this when backtest results are available.
    """
    perf = load_technique_performance()

    if technique_name not in perf:
        perf[technique_name] = {
            "attempts": 0,
            "successes": 0,
            "total_return": 0.0,
            "returns": [],
            "sharpes": [],
            "avg_return": 0.0,
            "avg_sharpe": 1.0,
            "win_rate": 0.5,
        }

    tech_perf = perf[technique_name]
    tech_perf["attempts"] += 1
    tech_perf["returns"].append(backtest_return)
    tech_perf["total_return"] += backtest_return

    if backtest_return > 0:
        tech_perf["successes"] += 1

    if sharpe_ratio is not None:
        tech_perf["sharpes"].append(sharpe_ratio)

    # Keep only last 20 results for recency
    tech_perf["returns"] = tech_perf["returns"][-20:]
    tech_perf["sharpes"] = tech_perf["sharpes"][-20:]

    # Calculate rolling averages
    tech_perf["avg_return"] = sum(tech_perf["returns"]) / len(tech_perf["returns"])
    tech_perf["win_rate"] = tech_perf["successes"] / tech_perf["attempts"]

    if tech_perf["sharpes"]:
        tech_perf["avg_sharpe"] = sum(tech_perf["sharpes"]) / len(tech_perf["sharpes"])

    save_technique_performance(perf)
    return tech_perf


def select_technique_weighted():
    """
    v4.0 ADAPTIVE TECHNIQUE SELECTION
    Selects techniques based on:
    1. Historical win rate (40% weight)
    2. Average Sharpe ratio (30% weight)
    3. Diversity bonus for underused (20% weight)
    4. Recency bonus (10% weight)

    Falls back to diversity-only for new techniques with < min_samples.
    """
    usage = load_technique_usage()
    performance = load_technique_performance()

    weights = []
    for tech in SCALPING_TECHNIQUES:
        name = tech["name"]
        count = usage.get(name, 0)

        # Get performance data or use defaults
        perf = performance.get(name, {})
        attempts = perf.get("attempts", 0)

        if attempts >= ADAPTIVE_CONFIG["min_samples"]:
            # Use adaptive weighting based on performance
            win_rate = perf.get("win_rate", ADAPTIVE_CONFIG["default_win_rate"])
            avg_sharpe = perf.get("avg_sharpe", ADAPTIVE_CONFIG["default_sharpe"])

            # Normalize Sharpe (cap at 3.0 for weight calculation)
            normalized_sharpe = min(avg_sharpe, 3.0) / 3.0

            # Calculate component weights
            win_rate_score = win_rate * ADAPTIVE_CONFIG["win_rate_weight"]
            sharpe_score = normalized_sharpe * ADAPTIVE_CONFIG["sharpe_weight"]
            diversity_score = (1.0 / (count + 1)) * ADAPTIVE_CONFIG["diversity_weight"]

            # Recency: boost if recent results are positive
            recent_returns = perf.get("returns", [])[-5:]
            recency_score = 0
            if recent_returns:
                recent_win_rate = sum(1 for r in recent_returns if r > 0) / len(
                    recent_returns
                )
                recency_score = recent_win_rate * ADAPTIVE_CONFIG["recency_weight"]

            weight = win_rate_score + sharpe_score + diversity_score + recency_score
        else:
            # Not enough data - use diversity weighting only
            # Give slight boost to untested techniques
            weight = (1.0 / (count + 1)) * 0.5 + 0.5  # Base weight + diversity bonus

        weights.append(max(weight, 0.01))  # Minimum weight to avoid zero

    # Normalize weights
    total = sum(weights)
    weights = [w / total for w in weights]

    # Weighted random selection
    selected = random.choices(SCALPING_TECHNIQUES, weights=weights, k=1)[0]

    return selected


def select_random_params(technique):
    """Select random parameters from the technique's parameter options"""
    params = {}
    for key, values in technique["params"].items():
        if isinstance(values, list):
            params[key] = random.choice(values)
        else:
            params[key] = values
    return params


def record_technique_usage(technique_name, indicators_used):
    """Record that a technique and its indicators were used"""
    # Update technique usage
    tech_usage = load_technique_usage()
    tech_usage[technique_name] = tech_usage.get(technique_name, 0) + 1
    save_technique_usage(tech_usage)

    # Update indicator usage
    ind_usage = load_indicator_usage()
    for ind in indicators_used:
        ind_usage[ind] = ind_usage.get(ind, 0) + 1
    save_indicator_usage(ind_usage)


def calculate_novelty_score(strategy, existing_ideas):
    """
    Calculate a novelty score (0-1) for a strategy.
    Higher scores = more novel/unique strategy.
    """
    fingerprint = extract_strategy_fingerprint(strategy)
    ind_usage = load_indicator_usage()

    base_score = 1.0  # Start with perfect novelty

    # Penalize for similarity to existing strategies
    max_similarity = 0.0
    for existing in existing_ideas:
        existing_fp = extract_strategy_fingerprint(existing)
        similarity = fingerprint_similarity(fingerprint, existing_fp)
        max_similarity = max(max_similarity, similarity)

    # Reduce score based on max similarity found
    base_score -= max_similarity * 0.6

    # Bonus for using underused indicators
    if fingerprint["indicators"]:
        total_ind_usage = sum(ind_usage.values()) + 1
        for ind in fingerprint["indicators"]:
            ind_count = ind_usage.get(ind, 0)
            if total_ind_usage > 0:
                usage_ratio = ind_count / total_ind_usage
                if usage_ratio < 0.1:  # Underused indicator
                    base_score += NOVELTY_CONFIG["underused_bonus"]

    # Bonus for multi-indicator combos
    if len(fingerprint["indicators"]) >= 2:
        base_score += NOVELTY_CONFIG["combo_bonus"]
    if len(fingerprint["indicators"]) >= 3:
        base_score += NOVELTY_CONFIG["combo_bonus"]

    # Cap at 1.0
    return min(1.0, max(0.0, base_score))


def get_recent_strategies(count=25):
    """Get the most recent validated strategies for the prompt - v6.4: increased count"""
    recent = []

    # Load from validated CSV
    if VALIDATED_CSV.exists():
        try:
            df = pd.read_csv(VALIDATED_CSV)
            if "strategy" in df.columns and len(df) > 0:
                # v6.4: Get more strategies to improve duplicate prevention
                recent = df["strategy"].tail(count).tolist()
        except:
            pass

    return recent


def get_used_indicators():
    """Get set of indicators that have been heavily used"""
    usage = load_indicator_usage()
    if not usage:
        return set()

    # Find average usage
    avg_usage = sum(usage.values()) / len(usage) if usage else 0

    # Return indicators used more than average
    heavily_used = set()
    for ind, count in usage.items():
        if count > avg_usage:
            heavily_used.add(ind)

    return heavily_used


SCALPING_GENERATION_PROMPT = """You are TradeHive's Scalping Strategy Generator.

Generate ONE unique SCALPING strategy that can be backtested with backtesting.py.
Your strategy MUST be optimized for:

TIMEFRAME: 1-minute, 5-minute, OR 15-minute charts ONLY
SPEED: Entry to exit in seconds to minutes (max 15 mins hold time)
TIGHT RISK: Stop loss 0.5-2% maximum
SMALL PROFITS: Target 0.5-3% per trade
HIGH FREQUENCY: Multiple trades per day possible
SMALL CAPITAL: Works with $100-$5000 accounts

Focus on ONE of these scalping techniques:
- VWAP bounces and deviations
- EMA/SMA crossovers on 1-5m charts (e.g., 9/21 EMA)
- RSI extremes on short timeframes (RSI < 20 or > 80)
- Stochastic oversold/overbought reversals
- Volume spikes and exhaustion patterns
- Momentum breakouts with tight stops
- Bollinger Band squeezes and breakouts
- MACD histogram divergences on 1-5m

Your strategy MUST include ALL of these clearly:
1. ENTRY: Specific trigger conditions (be exact with indicator values!)
2. EXIT: Profit target OR trailing stop method (specific % or ATR multiple)
3. STOP LOSS: Where to place it (specific % or ATR-based)
4. TIMEFRAME: Specify 1m, 5m, or 15m

Respond with ONLY the strategy in 2-3 sentences. No explanations, no introductions, no markdown.

EXAMPLE FORMAT (follow this exactly):
"5m RSI Scalp: Enter long when RSI(7) crosses above 25 with volume spike above 20-period average, take profit at 1.5% or RSI crossing 70, stop loss 0.75% below entry."

Your response must be a single strategy description ready to be backtested."""

SCALPING_VALIDATION_PROMPT = """You are a trading strategy validator. Analyze this scalping strategy and decide if it's VALID for backtesting.

STRATEGY TO VALIDATE:
{strategy}

A VALID scalping strategy must have:
1. Clear ENTRY conditions (specific indicator values or price action)
2. Clear EXIT conditions (profit target % or indicator-based)
3. Clear STOP LOSS (specific % or ATR-based)
4. Timeframe of 1m, 5m, or 15m
5. Realistic for small capital ($100-$5000)

Respond with ONLY one word:
- "VALID" if the strategy has all required components
- "INVALID" if missing components or unclear

Your response (one word only):"""

CONSENSUS_REVIEW_PROMPT = """You are reviewing a scalping strategy that multiple AI models have validated.

STRATEGY: {strategy}

VALIDATION RESULTS:
{validations}

Based on the validation results:
1. If majority (50%+) said VALID, respond: "CONSENSUS: APPROVED"
2. If majority said INVALID, respond: "CONSENSUS: REJECTED"

Also provide a 1-sentence reason.

Format: "CONSENSUS: [APPROVED/REJECTED] - [reason]"
"""

import os
import time
import csv
import random
from datetime import datetime
from pathlib import Path
from termcolor import cprint, colored
import pandas as pd
import sys
import shutil
import textwrap
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import model factory and swarm agent
from src.models import model_factory

# v6.5 - Import feedback connector for learning from backtest results
try:
    from src.agents import feedback_connector

    FEEDBACK_ENABLED = True
except ImportError:
    FEEDBACK_ENABLED = False
    print("⚠️ Feedback connector not available - running without backtest learning")

# ============================================
# PATH CONFIGURATION
# ============================================

DATA_DIR = PROJECT_ROOT / "src" / "data" / "scalping_strategies"
IDEAS_TXT = DATA_DIR / "ideas.txt"
IDEAS_CSV = DATA_DIR / "scalping_ideas.csv"
VALIDATED_CSV = DATA_DIR / "validated_strategies.csv"

# RBI Agent integration - output to RBI's ideas.txt
RBI_IDEAS_TXT = PROJECT_ROOT / "src" / "data" / "rbi_pp_multi" / "ideas.txt"

# Fun emojis for animation
EMOJIS = ["⚡", "🔥", "💰", "📈", "🎯", "💎", "🚀", "⭐", "🌟", "💫", "🧠", "🌙"]
MOON_PHASES = ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"]

# Get terminal width for better formatting
TERM_WIDTH = shutil.get_terminal_size().columns


def clear_line():
    """Clear the current line in the terminal"""
    print("\r" + " " * TERM_WIDTH, end="\r", flush=True)


def setup_files():
    """Set up the necessary files if they don't exist"""
    global TECHNIQUE_USAGE_FILE, INDICATOR_USAGE_FILE, TECHNIQUE_PERFORMANCE_FILE

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Set up tracking files
    TECHNIQUE_USAGE_FILE = DATA_DIR / "technique_usage.json"
    INDICATOR_USAGE_FILE = DATA_DIR / "indicator_usage.json"
    TECHNIQUE_PERFORMANCE_FILE = DATA_DIR / "technique_performance.json"

    if not IDEAS_TXT.exists():
        cprint(f"Creating scalping ideas.txt at {IDEAS_TXT}", "yellow")
        with open(IDEAS_TXT, "w") as f:
            f.write("# TradeHive's Scalping Strategy Ideas\n")
            f.write("# Generated by Scalping Strategy Agent v2.0\n")
            f.write("# One idea per line - Ready for RBI backtesting\n\n")

    if not IDEAS_CSV.exists():
        cprint(f"Creating scalping CSV at {IDEAS_CSV}", "white")
        with open(IDEAS_CSV, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "timestamp",
                    "model",
                    "idea",
                    "consensus_score",
                    "status",
                    "novelty_score",
                    "technique",
                ]
            )

    if not VALIDATED_CSV.exists():
        cprint(f"Creating validated strategies CSV at {VALIDATED_CSV}", "green")
        with open(VALIDATED_CSV, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "timestamp",
                    "strategy",
                    "consensus_score",
                    "models_agreed",
                    "total_models",
                    "novelty_score",
                    "technique",
                    "indicators",
                ]
            )

    # Initialize tracking files if they don't exist
    if not TECHNIQUE_USAGE_FILE.exists():
        cprint(f"Creating technique usage tracker at {TECHNIQUE_USAGE_FILE}", "cyan")
        save_technique_usage({})

    if not INDICATOR_USAGE_FILE.exists():
        cprint(f"Creating indicator usage tracker at {INDICATOR_USAGE_FILE}", "cyan")
        save_indicator_usage({})

    # v4.0 - Initialize performance tracking file
    if not TECHNIQUE_PERFORMANCE_FILE.exists():
        cprint(
            f"🎯 Creating technique PERFORMANCE tracker at {TECHNIQUE_PERFORMANCE_FILE}",
            "green",
        )
        save_technique_performance({})


def load_existing_ideas():
    """Load existing ideas from all sources to check for duplicates"""
    all_ideas = set()

    # Load from scalping CSV
    if IDEAS_CSV.exists():
        try:
            df = pd.read_csv(IDEAS_CSV)
            if "idea" in df.columns:
                ideas = set(
                    idea.lower().strip()
                    for idea in df["idea"].tolist()
                    if pd.notna(idea)
                )
                all_ideas.update(ideas)
        except Exception as e:
            cprint(f"Warning: Error loading scalping ideas: {str(e)}", "yellow")

    # Load from RBI ideas.txt
    if RBI_IDEAS_TXT.exists():
        try:
            with open(RBI_IDEAS_TXT, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        all_ideas.add(line.lower())
        except Exception as e:
            cprint(f"Warning: Error loading RBI ideas: {str(e)}", "yellow")

    # Load from validated strategies
    if VALIDATED_CSV.exists():
        try:
            df = pd.read_csv(VALIDATED_CSV)
            if "strategy" in df.columns:
                ideas = set(
                    idea.lower().strip()
                    for idea in df["strategy"].tolist()
                    if pd.notna(idea)
                )
                all_ideas.update(ideas)
        except:
            pass

    cprint(f"Loaded {len(all_ideas)} existing ideas for duplicate check", "cyan")
    return all_ideas


def extract_strategy_fingerprint(strategy):
    """
    Extract semantic fingerprint from strategy for better duplicate detection.
    Returns a dict of key components that define the strategy's uniqueness.
    """
    strategy_lower = strategy.lower()

    fingerprint = {
        "indicators": set(),
        "timeframe": None,
        "entry_type": None,
        "exit_type": None,
        "parameters": set(),
    }

    # Extract indicators used
    indicator_patterns = {
        "RSI": r"rsi\s*\(?(\d+)?\)?",
        "EMA": r"ema\s*\(?(\d+)?\)?|(\d+)[\s-]*(?:period\s+)?ema",
        "SMA": r"sma\s*\(?(\d+)?\)?|(\d+)[\s-]*(?:period\s+)?sma",
        "MACD": r"macd",
        "BB": r"bollinger|bb\s*\(|band",
        "STOCH": r"stochastic|stoch",
        "VWAP": r"vwap",
        "ATR": r"atr\s*\(?(\d+)?\)?",
        "VOL": r"volume|vol\s+spike|vol\s+above",
        "OBV": r"obv|on[\s-]*balance",
        "MOM": r"momentum",
        "ROC": r"roc\s*\(?(\d+)?\)?|rate\s+of\s+change",
    }

    for ind, pattern in indicator_patterns.items():
        if re.search(pattern, strategy_lower):
            fingerprint["indicators"].add(ind)
            # Extract parameter values
            match = re.search(pattern, strategy_lower)
            if match and match.groups():
                for g in match.groups():
                    if g and g.isdigit():
                        fingerprint["parameters"].add(f"{ind}_{g}")

    # Extract timeframe
    tf_match = re.search(r"(\d+)\s*m(?:in)?(?:ute)?", strategy_lower)
    if tf_match:
        fingerprint["timeframe"] = tf_match.group(1)

    # Extract entry type
    entry_types = [
        "cross",
        "bounce",
        "breakout",
        "divergence",
        "reversal",
        "squeeze",
        "spike",
        "extreme",
    ]
    for et in entry_types:
        if et in strategy_lower:
            fingerprint["entry_type"] = et
            break

    # Extract exit type
    if "trailing" in strategy_lower:
        fingerprint["exit_type"] = "trailing"
    elif "target" in strategy_lower or "profit" in strategy_lower:
        fingerprint["exit_type"] = "target"
    elif "atr" in strategy_lower and "exit" in strategy_lower:
        fingerprint["exit_type"] = "atr"

    return fingerprint


def fingerprint_similarity(fp1, fp2):
    """
    Calculate similarity between two strategy fingerprints.
    v7.0 FIX: Reduced parameter weight from 50% to 25% to allow more parameter variations.
    Added parameter tolerance for similar values (RSI_5 vs RSI_6 should be similar, not different).
    """
    score = 0.0
    # v7.0: Reduced parameter weight to allow more exploration of similar parameters
    # Old: {'indicators': 0.35, 'timeframe': 0.05, 'entry_type': 0.10, 'parameters': 0.50}
    weights = {
        "indicators": 0.50,  # Increased - indicator type matters most
        "timeframe": 0.10,  # Increased slightly
        "entry_type": 0.15,  # Increased - entry strategy matters
        "parameters": 0.25,  # REDUCED from 0.50 - allow more parameter exploration
    }

    # Indicator overlap (Jaccard similarity)
    if fp1["indicators"] and fp2["indicators"]:
        intersection = len(fp1["indicators"] & fp2["indicators"])
        union = len(fp1["indicators"] | fp2["indicators"])
        score += weights["indicators"] * (intersection / union if union > 0 else 0)

    # Timeframe match
    if fp1["timeframe"] and fp2["timeframe"]:
        score += weights["timeframe"] * (
            1.0 if fp1["timeframe"] == fp2["timeframe"] else 0
        )

    # Entry type match
    if fp1["entry_type"] and fp2["entry_type"]:
        score += weights["entry_type"] * (
            1.0 if fp1["entry_type"] == fp2["entry_type"] else 0
        )

    # Parameter overlap with tolerance for similar values
    if fp1["parameters"] and fp2["parameters"]:
        # Use tolerant parameter matching instead of exact matching
        parameter_similarity = calculate_parameter_similarity(
            fp1["parameters"], fp2["parameters"]
        )
        score += weights["parameters"] * parameter_similarity

    return score


def calculate_parameter_similarity(params1, params2):
    """
    Calculate similarity between parameter sets with tolerance for similar values.
    RSI_5 and RSI_6 should be considered similar, not completely different.
    """
    if not params1 or not params2:
        return 0.0

    # Convert parameter strings to structured format
    def parse_parameter(param_str):
        """Parse 'RSI_5' into ('RSI', 5)"""
        parts = param_str.split("_")
        if len(parts) == 2:
            try:
                return parts[0], int(parts[1])
            except ValueError:
                return param_str, None
        return param_str, None

    # Parse both parameter sets
    parsed1 = [parse_parameter(p) for p in params1]
    parsed2 = [parse_parameter(p) for p in params2]

    # Calculate similarity with tolerance
    total_similarity = 0.0
    matches = 0

    for indicator1, value1 in parsed1:
        best_match_similarity = 0.0

        for indicator2, value2 in parsed2:
            # Exact indicator match
            if indicator1 == indicator2:
                if value1 is not None and value2 is not None:
                    # Numeric parameters - use tolerance
                    if value1 == value2:
                        # Exact match
                        similarity = 1.0
                    elif abs(value1 - value2) <= 2:  # RSI_5 vs RSI_6, RSI_7
                        # Close values - high similarity
                        similarity = 0.8
                    elif abs(value1 - value2) <= 5:  # RSI_5 vs RSI_9, RSI_10
                        # Moderate difference - medium similarity
                        similarity = 0.5
                    else:
                        # Large difference - low similarity
                        similarity = 0.2
                else:
                    # Non-numeric parameters - exact match required
                    similarity = 1.0 if value1 == value2 else 0.0

                best_match_similarity = max(best_match_similarity, similarity)

        total_similarity += best_match_similarity
        if best_match_similarity > 0:
            matches += 1

    # Return average similarity, weighted by number of matches
    if matches == 0:
        return 0.0

    # Prefer strategies with more matching indicators
    match_ratio = matches / max(len(params1), len(params2))
    avg_similarity = total_similarity / len(params1)

    # Combine match ratio and average similarity
    return match_ratio * avg_similarity


def is_duplicate(idea, existing_ideas, threshold=0.65):
    """
    Check if an idea is a duplicate using semantic fingerprinting.
    v7.0 FIX: Reduced threshold from 0.75 to 0.65 to allow more exploration of similar strategies.
    With better parameter tolerance, we can be more permissive while still avoiding true duplicates.
    """
    idea_lower = idea.lower().strip()

    # Exact match
    if idea_lower in existing_ideas:
        return True, "exact_match", 1.0

    # Extract fingerprint for new idea
    new_fp = extract_strategy_fingerprint(idea)

    # Check against all existing ideas using fingerprinting
    for existing in existing_ideas:
        existing_fp = extract_strategy_fingerprint(existing)
        similarity = fingerprint_similarity(new_fp, existing_fp)

        if similarity >= threshold:
            return True, existing[:50], similarity

    # Also do word overlap as backup (with higher threshold)
    idea_words = set(idea_lower.split())
    for existing in existing_ideas:
        existing_words = set(existing.split())
        if len(idea_words) > 0 and len(existing_words) > 0:
            overlap = len(idea_words.intersection(existing_words))
            word_similarity = overlap / max(len(idea_words), len(existing_words))
            if word_similarity > 0.80:  # Higher threshold for word overlap
                return True, existing[:50], word_similarity

    return False, None, 0.0


def is_complete_strategy(idea):
    """
    Quick check if a strategy is complete enough to be useful.
    Rejects truncated/incomplete outputs from models.
    """
    if not idea:
        return False, "empty"

    # Minimum length check (complete strategies are usually 80+ chars)
    if len(idea) < 80:
        return False, f"too short ({len(idea)} chars)"

    # Must have entry condition keywords
    idea_lower = idea.lower()
    has_entry = any(
        word in idea_lower for word in ["enter", "buy", "long", "short", "when"]
    )
    if not has_entry:
        return False, "no entry condition"

    # Must have exit/profit keywords
    has_exit = any(
        word in idea_lower for word in ["profit", "target", "exit", "take", "tp", "%"]
    )
    if not has_exit:
        return False, "no exit/profit target"

    # Reject if ends with colon (truncated)
    if idea.rstrip().endswith(":"):
        return False, "truncated (ends with colon)"

    # Reject if it's just a title/header (common fragment patterns)
    fragment_patterns = [
        "edge source",
        "strategy:",
        "scalp:",
        "mode:",
        "technique:",
        "indicator:",
        "setup:",
    ]
    if any(
        idea_lower.strip().startswith(p) or idea_lower.strip() == p.rstrip(":")
        for p in fragment_patterns
    ):
        return False, "fragment/header only"

    return True, "valid"


def validate_complete_parameters(strategy):
    """
    Enhanced validation for complete parameter values.
    Checks for truncated percentages, incomplete ATR parameters, and realistic ranges.
    """
    if not strategy:
        return False, "empty strategy"

    # Check for truncated percentages (end with digit + .)
    if re.search(r"\d+\.$", strategy.strip()):  # Ends with "0." or "1."
        return False, "incomplete percentage value"

    # Check for incomplete ATR multipliers ("1x ATR" vs "1.5x ATR(14)")
    if re.search(r"\d+x ATR$", strategy.strip()):  # Missing the ATR period
        return False, "incomplete ATR parameters"

    # Check for incomplete stop/profit values
    incomplete_patterns = [
        r"stop loss\s+\d+\.?$",  # "stop loss 0."
        r"take profit\s+\d+\.?$",  # "take profit 1."
        r"stop\s+\d+\.?$",  # "stop 0."
        r"profit\s+\d+\.?$",  # "profit 1."
    ]

    for pattern in incomplete_patterns:
        if re.search(pattern, strategy.lower()):
            return False, "incomplete stop/profit value"

    # Check for realistic parameter ranges based on timeframe
    return validate_realistic_parameters(strategy)


def validate_realistic_parameters(strategy):
    """
    Validate that strategy parameters are realistic for scalping.
    Based on timeframe and market microstructure realities.
    """
    strategy_lower = strategy.lower()

    # Realistic parameter ranges by timeframe
    REALISTIC_RANGES = {
        "1m": {
            "rsi_period": (3, 9),
            "rsi_threshold": (15, 85),
            "ema_period": (3, 21),
            "volume_mult": (1.5, 4.0),
            "atr_mult": (0.5, 2.0),
            "stoch_period": (3, 9),
            "bb_period": (10, 20),
            "macd_fast": (3, 12),
            "macd_slow": (8, 26),
        },
        "5m": {
            "rsi_period": (5, 14),
            "rsi_threshold": (20, 80),
            "ema_period": (5, 34),
            "volume_mult": (1.3, 3.5),
            "atr_mult": (0.8, 2.5),
            "stoch_period": (7, 14),
            "bb_period": (15, 25),
            "macd_fast": (8, 21),
            "macd_slow": (12, 34),
        },
        "15m": {
            "rsi_period": (9, 21),
            "rsi_threshold": (25, 75),
            "ema_period": (9, 50),
            "volume_mult": (1.2, 3.0),
            "atr_mult": (1.0, 3.0),
            "stoch_period": (9, 21),
            "bb_period": (20, 30),
            "macd_fast": (12, 26),
            "macd_slow": (21, 50),
        },
    }

    # Extract timeframe from strategy
    timeframe_match = re.search(r"(\d+)m", strategy_lower)
    if not timeframe_match:
        return True, "valid"  # Can't validate without timeframe

    timeframe = timeframe_match.group(1) + "m"
    if timeframe not in REALISTIC_RANGES:
        return True, "valid"  # Unknown timeframe

    ranges = REALISTIC_RANGES[timeframe]

    # Validate RSI parameters
    rsi_matches = re.findall(r"rsi\((\d+)\)", strategy_lower)
    for period in rsi_matches:
        rsi_period = int(period)
        if rsi_period < ranges["rsi_period"][0] or rsi_period > ranges["rsi_period"][1]:
            return (
                False,
                f"RSI period {rsi_period} unrealistic for {timeframe} (should be {ranges['rsi_period'][0]}-{ranges['rsi_period'][1]})",
            )

    # Validate RSI thresholds
    rsi_threshold_matches = re.findall(
        r"rsi\(\d+\)\s*[\u003c\u003e]\s*(\d+)", strategy_lower
    )
    for threshold in rsi_threshold_matches:
        rsi_threshold = int(threshold)
        if (
            rsi_threshold < ranges["rsi_threshold"][0]
            or rsi_threshold > ranges["rsi_threshold"][1]
        ):
            return (
                False,
                f"RSI threshold {rsi_threshold} unrealistic for {timeframe} (should be {ranges['rsi_threshold'][0]}-{ranges['rsi_threshold'][1]})",
            )

    # Validate EMA periods
    ema_matches = re.findall(r"ema\((\d+)\)", strategy_lower)
    for period in ema_matches:
        ema_period = int(period)
        if ema_period < ranges["ema_period"][0] or ema_period > ranges["ema_period"][1]:
            return (
                False,
                f"EMA period {ema_period} unrealistic for {timeframe} (should be {ranges['ema_period'][0]}-{ranges['ema_period'][1]})",
            )

    # Validate volume multipliers
    volume_matches = re.findall(r"(\d+\.?\d*)x.*volume", strategy_lower)
    for mult in volume_matches:
        volume_mult = float(mult)
        if (
            volume_mult < ranges["volume_mult"][0]
            or volume_mult > ranges["volume_mult"][1]
        ):
            return (
                False,
                f"Volume multiplier {volume_mult}x unrealistic for {timeframe} (should be {ranges['volume_mult'][0]}-{ranges['volume_mult'][1]}x)",
            )

    # Validate ATR multipliers
    atr_matches = re.findall(r"(\d+\.?\d*)x.*atr", strategy_lower)
    for mult in atr_matches:
        atr_mult = float(mult)
        if atr_mult < ranges["atr_mult"][0] or atr_mult > ranges["atr_mult"][1]:
            return (
                False,
                f"ATR multiplier {atr_mult}x unrealistic for {timeframe} (should be {ranges['atr_mult'][0]}-{ranges['atr_mult'][1]}x)",
            )

    # Validate stop/profit percentages are realistic for scalping
    percent_matches = re.findall(r"(\d+\.?\d*)%", strategy_lower)
    for pct in percent_matches:
        percentage = float(pct)
        if percentage < 0.1 or percentage > 5.0:  # Scalping range: 0.1% to 5%
            return (
                False,
                f"Percentage {percentage}% unrealistic for scalping (should be 0.1%-5%)",
            )

    return True, "valid"


def clean_idea(idea):
    """Clean up the generated idea text"""
    # Remove thinking tags if present (for DeepSeek-R1)
    if "<think>" in idea and "</think>" in idea:
        idea = re.sub(r"<think>.*?</think>", "", idea, flags=re.DOTALL).strip()

    # Extract content from markdown bold/quotes if present
    bold_match = re.search(r'\*\*"?(.*?)"?\*\*', idea)
    if bold_match:
        idea = bold_match.group(1).strip()

    # Handle common prefixes from models
    prefixes_to_remove = [
        "Sure",
        "Sure,",
        "Here's",
        "Here is",
        "I'll",
        "I will",
        "A unique",
        "One unique",
        "Here's a",
        "Here is a",
        "Trading strategy:",
        "Strategy idea:",
        "Trading idea:",
        "Scalping strategy:",
        "Scalping idea:",
        "Strategy:",
    ]

    for prefix in prefixes_to_remove:
        if idea.lower().startswith(prefix.lower()):
            idea = idea[len(prefix) :].strip()
            idea = idea.lstrip(",:;.- ")

    # Remove any markdown formatting
    idea = idea.replace("```", "").replace("#", "")

    # Remove quotes if they wrap the entire idea
    if (idea.startswith('"') and idea.endswith('"')) or (
        idea.startswith("'") and idea.endswith("'")
    ):
        idea = idea[1:-1].strip()

    # Ensure it's a clean single/multi line
    idea = " ".join(idea.split())

    # Truncate if too long (aim for 2-3 sentences max)
    sentences = re.split(r"[.!?]+", idea)
    if len(sentences) > 4:
        idea = ".".join(sentences[:3]).strip() + "."

    # Ensure first letter is capitalized
    if idea and not idea[0].isupper():
        idea = idea[0].upper() + idea[1:]

    return idea


def validate_strategy_components(strategy):
    """
    Check if strategy has all required components.
    v4.0 - Now checks for QUALITY REQUIREMENTS for alpha generation.
    """
    strategy_lower = strategy.lower()

    # Check for entry conditions
    has_entry = any(
        word in strategy_lower
        for word in ["enter", "buy", "long", "short", "sell", "entry", "when", "if"]
    )

    # Check for exit conditions
    has_exit = any(
        word in strategy_lower
        for word in ["exit", "take profit", "tp", "target", "profit", "close", "%"]
    )

    # Check for stop loss
    has_stop = any(word in strategy_lower for word in ["stop", "sl", "loss", "risk"])

    # Check for timeframe
    has_timeframe = any(
        tf in strategy_lower
        for tf in ["1m", "5m", "15m", "1-min", "5-min", "15-min", "minute"]
    )

    # v4.0 QUALITY CHECKS
    # Check for volume filter/confirmation
    has_volume_filter = any(
        word in strategy_lower
        for word in [
            "volume",
            "vol",
            "v>",
            "volume above",
            "volume spike",
            "volume exceeds",
        ]
    )

    # Check for multi-confirmation (2+ signals)
    confirmation_signals = 0
    signal_types = [
        # Primary indicators
        ["rsi", "stoch", "macd", "ema", "sma", "ma ", "moving average"],
        # Volume confirmation
        ["volume", "vol "],
        # Price structure
        ["higher low", "lower high", "breakout", "pullback", "support", "resistance"],
        # Secondary indicators
        ["bollinger", "atr", "adx", "cci", "momentum", "divergence"],
    ]
    for signal_group in signal_types:
        if any(sig in strategy_lower for sig in signal_group):
            confirmation_signals += 1
    has_multi_confirmation = confirmation_signals >= 2

    # Check for ATR-based sizing
    has_atr_sizing = "atr" in strategy_lower

    # Extract risk/reward ratio
    risk_reward_ok = False
    import re

    # Look for patterns like "stop 0.5%, profit 1%" or "stop loss 0.8%, take profit 1.6%"
    stop_match = re.search(r"stop[^\d]*(\d+\.?\d*)\s*%", strategy_lower)
    profit_match = re.search(
        r"(?:profit|target|tp)[^\d]*(\d+\.?\d*)\s*%", strategy_lower
    )

    if stop_match and profit_match:
        try:
            stop_pct = float(stop_match.group(1))
            profit_pct = float(profit_match.group(1))
            if stop_pct > 0:
                actual_rr = profit_pct / stop_pct
                risk_reward_ok = actual_rr >= QUALITY_REQUIREMENTS["min_risk_reward"]
        except:
            pass

    # If can't extract, give benefit of doubt if it mentions 2:1 or similar
    if not risk_reward_ok:
        risk_reward_ok = any(
            term in strategy_lower
            for term in ["2:1", "2x", "twice", "2 times", "double"]
        )

    # Calculate quality score (0-100)
    quality_score = 0
    quality_score += 25 if has_volume_filter else 0
    quality_score += 25 if has_multi_confirmation else 0
    quality_score += 25 if risk_reward_ok else 0
    quality_score += 25 if has_atr_sizing else 0

    # Basic validity (entry + exit + stop)
    basic_valid = has_entry and has_exit and has_stop

    # v4.0 ALPHA QUALITY - need at least 50% quality score
    alpha_quality = quality_score >= 50

    return {
        "has_entry": has_entry,
        "has_exit": has_exit,
        "has_stop": has_stop,
        "has_timeframe": has_timeframe,
        "is_valid": basic_valid,
        # v4.0 quality metrics
        "has_volume_filter": has_volume_filter,
        "has_multi_confirmation": has_multi_confirmation,
        "confirmation_signals": confirmation_signals,
        "has_atr_sizing": has_atr_sizing,
        "risk_reward_ok": risk_reward_ok,
        "quality_score": quality_score,
        "alpha_quality": alpha_quality,
    }


# Cache for working models (tested once at startup)
_WORKING_MODELS_CACHE = None


def get_available_models():
    """Get list of WORKING models by actually testing them (cached after first call)"""
    global _WORKING_MODELS_CACHE

    # Return cached results if already tested
    if _WORKING_MODELS_CACHE is not None:
        return _WORKING_MODELS_CACHE

    available = []

    cprint("\n🔍 Testing available AI models (one-time check)...", "yellow")

    # Check each model type - ordered by reliability
    model_checks = [
        ("deepseek", "DEEPSEEK_KEY", "deepseek-v4-flash"),
        ("xai", "GROK_API_KEY", "grok-4-fast-reasoning"),
        ("openrouter", "OPENROUTER_API_KEY", "google/gemini-2.5-flash"),
        (
            "claude",
            "ANTHROPIC_KEY",
            "claude-opus-4-7",
        ),  # Upgraded to Opus 4.7!
        ("openai", "OPENAI_KEY", "gpt-5.4-mini"),
        ("groq", "GROQ_API_KEY", "mixtral-8x7b-32768"),
        ("gemini", "GEMINI_KEY", "gemini-2.0-flash"),
    ]

    for model_type, env_key, default_model in model_checks:
        api_key = os.getenv(env_key)

        # Skip if no API key or placeholder value
        if not api_key:
            cprint(f"  ⏭️  {model_type} - No API key set", "yellow")
            continue

        if api_key.startswith("your_") or "here" in api_key.lower():
            cprint(f"  ⏭️  {model_type} - Placeholder API key (update .env)", "yellow")
            continue

        # Try to actually use the model
        try:
            model = model_factory.get_model(model_type, default_model)
            if model and model.is_available():
                # Quick test - try a simple generation
                test_response = model.generate_response(
                    system_prompt="Say OK",
                    user_content="Test",
                    temperature=0.1,
                    max_tokens=10,
                )
                if test_response:
                    available.append({"type": model_type, "name": default_model})
                    cprint(f"  ✅ {model_type} ({default_model}) - WORKING", "green")
                else:
                    cprint(f"  ❌ {model_type} - No response", "red")
            else:
                cprint(f"  ❌ {model_type} - Model not available", "red")
        except Exception as e:
            error_msg = str(e)[:60].replace("\n", " ")
            cprint(f"  ❌ {model_type} - {error_msg}", "red")

    # Cache the results
    _WORKING_MODELS_CACHE = available

    if available:
        cprint(f"\n✅ {len(available)} working model(s) found!", "green")
    else:
        cprint(f"\n❌ No working models found! Check your .env file.", "red")

    return available


def generate_with_single_model(model_config, prompt):
    """Generate strategy using a single model"""
    try:
        model = model_factory.get_model(model_config["type"], model_config["name"])
        if not model:
            return None

        # v6.3 FIX: Better prompt structure for complete responses
        # - System prompt: Short role definition
        # - User content: Detailed task (this is where the real work happens)
        system_role = """You are TradeHive's Scalping Strategy Generator. Your ONLY job is to output a complete trading strategy in this EXACT format:

"[Timeframe] [StrategyName]: Enter [long/short] when [ENTRY CONDITIONS with exact values] AND [CONFIRMATION], take profit at [X%] or [Xx ATR], stop loss [Y%] below entry."

CRITICAL: Output ONLY the strategy. No explanations, no headers, no "Edge Source:", no thinking - JUST the strategy in quotes."""

        response = model.generate_response(
            system_prompt=system_role,
            user_content=prompt,  # The detailed technique/params go here
            temperature=0.85,
            max_tokens=500,  # v6.3: Explicit token limit for complete strategies
        )

        if isinstance(response, str):
            return response
        elif hasattr(response, "content"):
            return response.content
        else:
            return str(response)
    except Exception as e:
        cprint(f"Error with {model_config['type']}: {str(e)}", "red")
        return None


def generate_scalping_idea_swarm():
    """Generate a scalping strategy using the AI swarm with dynamic diversity system"""
    # Determine step count based on consensus setting
    steps = "[1/2]" if SKIP_CONSENSUS else "[1/4]"
    total_steps = 2 if SKIP_CONSENSUS else 4

    cprint("\n" + "=" * 60, "cyan")
    cprint(f" {ACTIVE_MODE['name'].upper()} - ALPHA GENERATOR ", "white", "on_magenta")
    cprint("=" * 60, "cyan")

    available_models = get_available_models()

    if not available_models:
        cprint("No AI models available! Check your .env file.", "red")
        return None, None, 0, None

    cprint(f"\nAvailable models: {len(available_models)}", "green")
    for m in available_models:
        cprint(f"  - {m['type']}: {m['name']}", "cyan")

    # Step 1: Select technique using weighted rotation (favors less-used techniques)
    cprint(f"\n{steps} Selecting technique (weighted rotation)...", "yellow")

    selected_technique = select_technique_weighted()
    selected_params = select_random_params(selected_technique)
    selected_timeframe = random.choice(TIMEFRAMES)

    cprint(f"  Technique: {selected_technique['name']}", "cyan")
    cprint(f"  Indicator: {selected_technique['indicator']}", "cyan")
    cprint(f"  Params: {selected_params}", "cyan")
    cprint(f"  Timeframe: {selected_timeframe['tf']}", "cyan")

    # Get recent strategies and used indicators for the prompt
    recent_strategies = get_recent_strategies(10)
    used_indicators = get_used_indicators()

    # Build dynamic prompt
    dynamic_prompt = build_dynamic_prompt(
        technique=selected_technique,
        timeframe=selected_timeframe,
        params=selected_params,
        recent_strategies=recent_strategies,
        used_indicators=used_indicators,
    )

    # Step 2: Generate strategy with a random model
    steps = "[2/2]" if SKIP_CONSENSUS else "[2/4]"
    cprint(f"\n{steps} Generating strategy...", "yellow")

    generator_model = random.choice(available_models)
    cprint(f"Using {generator_model['type']} for generation", "cyan")

    # Use dynamic prompt with higher temperature for creativity
    idea = generate_with_single_model(generator_model, dynamic_prompt)

    if not idea:
        # Fallback to static prompt
        cprint("Dynamic prompt failed, trying static prompt...", "yellow")
        idea = generate_with_single_model(generator_model, SCALPING_GENERATION_PROMPT)

    if not idea:
        cprint("Failed to generate strategy", "red")
        return None, None, 0, selected_technique

    idea = clean_idea(idea)
    cprint(f"\nGenerated: {idea[:100]}...", "green")

    # Skip validation if SKIP_CONSENSUS is True
    if SKIP_CONSENSUS:
        cprint("\n Consensus SKIPPED (fast mode - backtester will validate)", "cyan")
        return idea, generator_model, 1.0, selected_technique  # Return 100% consensus

    # Step 3: Validate with all available models (only if consensus enabled)
    cprint("\n[3/4] Validating with AI swarm...", "yellow")

    validations = {}
    valid_count = 0

    for model_config in available_models:
        try:
            cprint(f"  Checking with {model_config['type']}...", "cyan", end=" ")

            validation_prompt = SCALPING_VALIDATION_PROMPT.format(strategy=idea)
            result = generate_with_single_model(model_config, validation_prompt)

            if result:
                result_clean = result.strip().upper()
                is_valid = "VALID" in result_clean and "INVALID" not in result_clean
                validations[model_config["type"]] = is_valid

                if is_valid:
                    valid_count += 1
                    cprint("VALID", "green")
                else:
                    cprint("INVALID", "red")
            else:
                cprint("NO RESPONSE", "yellow")

        except Exception as e:
            cprint(f"ERROR: {str(e)}", "red")

    # Step 4: Calculate consensus
    total_models = len(validations)
    consensus_score = valid_count / total_models if total_models > 0 else 0

    cprint(
        f"\n[4/4] Consensus: {valid_count}/{total_models} models ({consensus_score * 100:.0f}%)",
        "green" if consensus_score >= MIN_CONSENSUS_THRESHOLD else "red",
    )

    return idea, generator_model, consensus_score, selected_technique


def generate_scalping_ideas_parallel():
    """
    Generate scalping strategies using ALL models in PARALLEL.
    Returns ALL successful ideas (not just the first/best).

    v6.1 - Marcus Chen's suggestion: 4 models = 4 strategies per cycle!
    v6.3 - COMPLETE RESPONSE FIX: Simplified prompts + explicit max_tokens + proper system/user split
    """
    cprint("\n" + "=" * 60, "cyan")
    cprint(
        f" {ACTIVE_MODE['name'].upper()} - PARALLEL ALPHA GENERATOR ",
        "white",
        "on_magenta",
    )
    cprint("=" * 60, "cyan")

    available_models = get_available_models()

    if not available_models:
        cprint("No AI models available! Check your .env file.", "red")
        return []

    cprint(
        f"\n🚀 PARALLEL MODE: Using ALL {len(available_models)} models simultaneously!",
        "green",
    )
    for m in available_models:
        cprint(f"  - {m['type']}: {m['name']}", "cyan")

    # v6.2 DIVERSITY FIX: Select DIFFERENT techniques for each model!
    cprint(
        f"\n[1/2] Selecting {len(available_models)} DIFFERENT techniques for diversity...",
        "yellow",
    )

    # Get recent strategies and used indicators for the prompts
    recent_strategies = get_recent_strategies(10)
    used_indicators = get_used_indicators()
    selected_timeframe = random.choice(TIMEFRAMES)

    # Select unique techniques for each model
    model_assignments = []
    used_techniques = set()

    for model_config in available_models:
        # Keep trying to find an unused technique
        attempts = 0
        while attempts < 10:
            technique = select_technique_weighted()
            if technique["name"] not in used_techniques or attempts >= 5:
                used_techniques.add(technique["name"])
                params = select_random_params(technique)

                # Build unique prompt for this model
                prompt = build_dynamic_prompt(
                    technique=technique,
                    timeframe=selected_timeframe,
                    params=params,
                    recent_strategies=recent_strategies,
                    used_indicators=used_indicators,
                )

                model_assignments.append(
                    {
                        "model": model_config,
                        "technique": technique,
                        "params": params,
                        "prompt": prompt,
                    }
                )

                cprint(
                    f"  [{model_config['type']}] → {technique['name']} ({technique['indicator']})",
                    "cyan",
                )
                break
            attempts += 1

    # Step 2: Generate strategies with ALL models in PARALLEL (each with DIFFERENT technique)
    cprint(
        f"\n[2/2] Generating with ALL {len(available_models)} models in parallel...",
        "yellow",
    )

    ideas = []

    def generate_single(assignment):
        """Worker function for parallel generation - each model gets its own technique!"""
        model_config = assignment["model"]
        technique = assignment["technique"]
        prompt = assignment["prompt"]

        try:
            result = generate_with_single_model(model_config, prompt)
            if result:
                cleaned = clean_idea(result)
                return {
                    "idea": cleaned,
                    "model": model_config,
                    "technique": technique,
                    "timeframe": selected_timeframe,
                }
        except Exception as e:
            return {"error": str(e), "model": model_config}
        return None

    # Run all models in parallel with their unique prompts
    with ThreadPoolExecutor(max_workers=len(available_models)) as executor:
        futures = {
            executor.submit(generate_single, a): a["model"] for a in model_assignments
        }

        for future in as_completed(futures, timeout=60):
            model = futures[future]
            try:
                result = future.result()
                if result and "idea" in result:
                    ideas.append(result)
                    cprint(f"  ✓ {model['type']}: {result['idea'][:60]}...", "green")
                elif result and "error" in result:
                    cprint(f"  ✗ {model['type']}: {result['error'][:40]}", "red")
                else:
                    cprint(f"  ✗ {model['type']}: No response", "yellow")
            except Exception as e:
                cprint(f"  ✗ {model['type']}: Timeout/Error - {str(e)[:30]}", "red")

    cprint(
        f"\n🎯 Generated {len(ideas)} ideas from {len(available_models)} models!",
        "green" if ideas else "red",
    )

    return ideas


def generate_scalping_idea_single():
    """Generate a scalping strategy using a single model with dynamic diversity"""
    cprint("\n" + "=" * 60, "cyan")
    cprint(" SCALPING STRATEGY GENERATOR v3.0 - SINGLE MODEL ", "white", "on_blue")
    cprint("=" * 60, "cyan")

    cprint(
        f"\nUsing: {SINGLE_MODEL_CONFIG['type']} - {SINGLE_MODEL_CONFIG['name']}",
        "cyan",
    )

    # Select technique using weighted rotation
    selected_technique = select_technique_weighted()
    selected_params = select_random_params(selected_technique)
    selected_timeframe = random.choice(TIMEFRAMES)

    cprint(f"  Technique: {selected_technique['name']}", "cyan")
    cprint(f"  Params: {selected_params}", "cyan")

    # Get recent strategies and build dynamic prompt
    recent_strategies = get_recent_strategies(10)
    used_indicators = get_used_indicators()

    dynamic_prompt = build_dynamic_prompt(
        technique=selected_technique,
        timeframe=selected_timeframe,
        params=selected_params,
        recent_strategies=recent_strategies,
        used_indicators=used_indicators,
    )

    idea = generate_with_single_model(SINGLE_MODEL_CONFIG, dynamic_prompt)

    if not idea:
        # Fallback to static prompt
        idea = generate_with_single_model(
            SINGLE_MODEL_CONFIG, SCALPING_GENERATION_PROMPT
        )

    if not idea:
        return None, SINGLE_MODEL_CONFIG, 0, selected_technique

    idea = clean_idea(idea)

    # Basic validation + v4.0 quality checks
    validation = validate_strategy_components(idea)
    consensus_score = 1.0 if validation["is_valid"] else 0.0

    cprint(f"\nGenerated: {idea}", "green")
    cprint(
        f"Validation: {'PASSED' if validation['is_valid'] else 'FAILED'}",
        "green" if validation["is_valid"] else "red",
    )

    # v4.0 - Log ALPHA QUALITY metrics
    quality_icon = "🎯" if validation["alpha_quality"] else "⚠️"
    cprint(
        f"{quality_icon} Quality Score: {validation['quality_score']}/100",
        "green" if validation["quality_score"] >= 50 else "yellow",
    )

    quality_checks = []
    quality_checks.append(
        f"✓ Volume Filter" if validation["has_volume_filter"] else "✗ Volume Filter"
    )
    quality_checks.append(
        f"✓ Multi-Confirm ({validation['confirmation_signals']} signals)"
        if validation["has_multi_confirmation"]
        else f"✗ Multi-Confirm ({validation['confirmation_signals']} signals)"
    )
    quality_checks.append(
        f"✓ R/R >= 2:1" if validation["risk_reward_ok"] else "✗ R/R >= 2:1"
    )
    quality_checks.append(
        f"✓ ATR-based" if validation["has_atr_sizing"] else "✗ ATR-based"
    )
    cprint(f"   {' | '.join(quality_checks)}", "white")

    return idea, SINGLE_MODEL_CONFIG, consensus_score, selected_technique


def log_idea(
    idea,
    model_config,
    consensus_score,
    approved=True,
    novelty_score=0.0,
    technique=None,
    rejection_reason=None,
):
    """Log a new idea to CSV files and RBI ideas.txt"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    model_name = f"{model_config['type']}-{model_config['name']}"
    status = "APPROVED" if approved else "REJECTED"
    technique_name = technique["name"] if technique else "unknown"

    # Extract indicators from the strategy
    fingerprint = extract_strategy_fingerprint(idea)
    indicators_str = (
        ",".join(sorted(fingerprint["indicators"])) if fingerprint["indicators"] else ""
    )

    # Log to scalping CSV (all ideas) - use UTF-8 for Windows emoji support
    with open(IDEAS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                timestamp,
                model_name,
                idea,
                f"{consensus_score:.2f}",
                status,
                f"{novelty_score:.2f}",
                technique_name,
            ]
        )

    if approved:
        # Log to validated strategies CSV
        with open(VALIDATED_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    timestamp,
                    idea,
                    f"{consensus_score:.2f}",
                    int(consensus_score * 10),
                    10,
                    f"{novelty_score:.2f}",
                    technique_name,
                    indicators_str,
                ]
            )

        # Record technique and indicator usage for diversity tracking
        if technique:
            record_technique_usage(technique_name, fingerprint["indicators"])

        # Append to scalping ideas.txt
        with open(IDEAS_TXT, "a", encoding="utf-8") as f:
            f.write(f"{idea}\n")

        # Append to RBI ideas.txt for backtesting
        # v6.5 - Include technique metadata for feedback loop matching
        if RBI_IDEAS_TXT.parent.exists():
            with open(RBI_IDEAS_TXT, "a", encoding="utf-8") as f:
                # Format: [TECHNIQUE:name] strategy_text
                f.write(f"[TECHNIQUE:{technique_name}] {idea}\n")
            cprint(f"Added to RBI ideas.txt for backtesting!", "green")

        cprint(
            f"Strategy saved! Consensus: {consensus_score * 100:.0f}%, Novelty: {novelty_score * 100:.0f}%",
            "green",
        )
    else:
        reason = f" ({rejection_reason})" if rejection_reason else ""
        cprint(
            f"Strategy rejected{reason} - Consensus: {consensus_score * 100:.0f}%, Novelty: {novelty_score * 100:.0f}%",
            "yellow",
        )


def select_mode_interactive():
    """Interactive mode selection at startup"""
    global SCALPING_MODE, SCALPING_TECHNIQUES, TIMEFRAMES, ACTIVE_MODE

    cprint("\n" + "=" * 60, "magenta")
    cprint(" TRADEHIVE'S SCALPING AGENT v6.4 - ALPHA GENERATION ", "white", "on_magenta")
    cprint("=" * 60, "magenta")

    cprint("\n 🎯 Select Your Hunting Style:", "cyan")
    cprint(
        "  [1] 🐟 PIRANHA MODE (1m)  - Fast, aggressive micro-structure attacks",
        "green",
    )
    cprint("  [2] 🦈 SHARK MODE (5m)    - Patient hunter, momentum strikes", "yellow")
    cprint("  [3] 🐋 WHALE MODE (15m)   - Ride the big waves, trend surfing", "blue")
    cprint(
        "  [4] 🐍 VIPER MODE (5m)    - Strike fast on retail mistakes, venomous precision",
        "red",
    )

    while True:
        try:
            choice = input("\nEnter choice (1/2/3/4) [default=1]: ").strip() or "1"
            if choice == "1":
                SCALPING_MODE = "1m_hft"
                break
            elif choice == "2":
                SCALPING_MODE = "5m_momentum"
                break
            elif choice == "3":
                SCALPING_MODE = "15m_swing"
                break
            elif choice == "4":
                SCALPING_MODE = "5m_contrarian"
                break
            else:
                cprint("Invalid choice. Enter 1, 2, 3, or 4.", "red")
        except KeyboardInterrupt:
            cprint("\nExiting...", "yellow")
            return False

    # Update globals based on mode selection
    ACTIVE_MODE = MODE_CONFIGS[SCALPING_MODE]
    TIMEFRAMES[:] = [ACTIVE_MODE]  # Update in place
    SCALPING_TECHNIQUES[:] = MODE_TECHNIQUES.get(SCALPING_MODE, HFT_TECHNIQUES)

    cprint(f"\n ✅ Selected: {ACTIVE_MODE['name']} ({ACTIVE_MODE['tf']})", "green")
    cprint(f'    "{ACTIVE_MODE.get("tagline", "")}"', "white")
    cprint(f"  Edge Sources: {', '.join(ACTIVE_MODE['edge_sources'][:3])}...", "cyan")
    return True


def run_scalping_loop():
    """Run the scalping idea generation loop with diversity tracking"""
    setup_files()

    # v6.5 - Sync feedback from backtest results on startup
    if FEEDBACK_ENABLED:
        try:
            cprint("\n🔄 Syncing feedback from backtest results...", "cyan")
            sync_result = feedback_connector.process_new_results()
            if sync_result.get("results_processed", 0) > 0:
                cprint(
                    f"✅ Processed {sync_result['results_processed']} results, updated {sync_result['techniques_updated']} techniques",
                    "green",
                )
            else:
                cprint("📭 No new backtest results to process", "yellow")
        except Exception as e:
            cprint(f"⚠️ Feedback sync failed: {e}", "yellow")

    # Interactive mode selection
    if not select_mode_interactive():
        return

    cprint("\n" + "=" * 60, "magenta")
    cprint(
        f" {ACTIVE_MODE['name'].upper()} - ALPHA GENERATION MODE ",
        "white",
        "on_magenta",
    )
    cprint("=" * 60, "magenta")
    cprint(f"\nTimeframe: {ACTIVE_MODE['tf']}", "cyan")
    cprint(
        f"Mode: {'🚀 PARALLEL (ALL models)' if PARALLEL_MODE else '🔄 Sequential (1 model/cycle)'}",
        "green" if PARALLEL_MODE else "yellow",
    )
    cprint(
        f"Consensus: {'DISABLED (fast mode)' if SKIP_CONSENSUS else f'{MIN_CONSENSUS_THRESHOLD * 100:.0f}%'}",
        "cyan",
    )
    cprint(f"Min Novelty: {NOVELTY_CONFIG['min_novelty_score'] * 100:.0f}%", "cyan")
    cprint(f"Techniques Available: {len(SCALPING_TECHNIQUES)}", "cyan")
    cprint(f"Interval: {GENERATION_INTERVAL}s", "cyan")
    cprint(f"RBI Output: {RBI_IDEAS_TXT}", "cyan")
    cprint("\nPress Ctrl+C to stop\n", "yellow")

    ideas_generated = 0
    ideas_approved = 0
    duplicates_caught = 0
    low_novelty_rejected = 0
    incomplete_rejected = 0  # v6.1 - Track incomplete/truncated strategies

    try:
        while True:
            existing_ideas = load_existing_ideas()
            cycle_approved = 0
            cycle_generated = 0

            # v6.1 PARALLEL MODE: Generate with ALL models simultaneously
            if PARALLEL_MODE:
                generated_ideas = generate_scalping_ideas_parallel()

                # Process ALL returned ideas
                for idea_data in generated_ideas:
                    idea = idea_data["idea"]
                    model_config = idea_data["model"]
                    technique = idea_data["technique"]
                    consensus_score = 1.0  # Skip consensus in parallel mode

                    ideas_generated += 1
                    cycle_generated += 1

                    # v7.0 - Enhanced validation: check completeness AND parameter validity
                    is_complete, reject_reason = is_complete_strategy(idea)
                    if not is_complete:
                        incomplete_rejected += 1
                        cprint(
                            f"\n[{model_config['type']}] INCOMPLETE ({reject_reason})",
                            "red",
                        )
                        log_idea(
                            idea,
                            model_config,
                            consensus_score,
                            approved=False,
                            novelty_score=0,
                            technique=technique,
                            rejection_reason=f"incomplete ({reject_reason})",
                        )
                        continue  # Skip to next idea

                    # v7.0 - Additional validation for complete parameters
                    params_valid, params_reason = validate_complete_parameters(idea)
                    if not params_valid:
                        incomplete_rejected += 1
                        cprint(
                            f"\n[{model_config['type']}] INVALID PARAMS ({params_reason})",
                            "red",
                        )
                        log_idea(
                            idea,
                            model_config,
                            consensus_score,
                            approved=False,
                            novelty_score=0,
                            technique=technique,
                            rejection_reason=f"invalid params ({params_reason})",
                        )
                        continue  # Skip to next idea

                    # Check for duplicates using semantic fingerprinting
                    is_dup, similar_to, similarity = is_duplicate(idea, existing_ideas)

                    # Calculate novelty score
                    novelty_score = calculate_novelty_score(idea, existing_ideas)

                    if is_dup:
                        duplicates_caught += 1
                        cprint(
                            f"\n[{model_config['type']}] DUPLICATE ({similarity * 100:.0f}% similar)",
                            "yellow",
                        )
                        log_idea(
                            idea,
                            model_config,
                            consensus_score,
                            approved=False,
                            novelty_score=novelty_score,
                            technique=technique,
                            rejection_reason=f"duplicate ({similarity * 100:.0f}% similar)",
                        )

                    elif novelty_score < NOVELTY_CONFIG["min_novelty_score"]:
                        low_novelty_rejected += 1
                        cprint(
                            f"\n[{model_config['type']}] LOW NOVELTY ({novelty_score * 100:.0f}%)",
                            "yellow",
                        )
                        log_idea(
                            idea,
                            model_config,
                            consensus_score,
                            approved=False,
                            novelty_score=novelty_score,
                            technique=technique,
                            rejection_reason=f"low novelty ({novelty_score * 100:.0f}%)",
                        )

                    else:
                        # Approved!
                        cprint(
                            f"\n✅ [{model_config['type']}] APPROVED!",
                            "white",
                            "on_green",
                        )
                        cprint(
                            f"   Technique: {technique['name'] if technique else 'N/A'}",
                            "green",
                        )
                        cprint(f"   Novelty: {novelty_score * 100:.0f}%", "green")
                        log_idea(
                            idea,
                            model_config,
                            consensus_score,
                            approved=True,
                            novelty_score=novelty_score,
                            technique=technique,
                        )
                        ideas_approved += 1
                        cycle_approved += 1

                        # Add to existing ideas to prevent same-cycle duplicates
                        existing_ideas.add(idea.lower())

                cprint(
                    f"\n🎯 Cycle Result: {cycle_approved}/{cycle_generated} approved this cycle!",
                    "cyan",
                )

            else:
                # Original single-idea generation mode
                if USE_SWARM_MODE:
                    idea, model_config, consensus_score, technique = (
                        generate_scalping_idea_swarm()
                    )
                else:
                    idea, model_config, consensus_score, technique = (
                        generate_scalping_idea_single()
                    )

                if idea:
                    ideas_generated += 1
                    cycle_generated = 1

                    # Check for duplicates using semantic fingerprinting
                    is_dup, similar_to, similarity = is_duplicate(idea, existing_ideas)

                    # Calculate novelty score
                    novelty_score = calculate_novelty_score(idea, existing_ideas)

                    if is_dup:
                        duplicates_caught += 1
                        cprint(
                            f"\nSEMANTIC DUPLICATE DETECTED ({similarity * 100:.0f}% similar)",
                            "yellow",
                        )
                        cprint(f"  Similar to: {similar_to}...", "yellow")
                        log_idea(
                            idea,
                            model_config,
                            consensus_score,
                            approved=False,
                            novelty_score=novelty_score,
                            technique=technique,
                            rejection_reason=f"duplicate ({similarity * 100:.0f}% similar)",
                        )

                    elif novelty_score < NOVELTY_CONFIG["min_novelty_score"]:
                        low_novelty_rejected += 1
                        cprint(
                            f"\nLOW NOVELTY ({novelty_score * 100:.0f}%) - Rejected",
                            "yellow",
                        )
                        log_idea(
                            idea,
                            model_config,
                            consensus_score,
                            approved=False,
                            novelty_score=novelty_score,
                            technique=technique,
                            rejection_reason=f"low novelty ({novelty_score * 100:.0f}%)",
                        )

                    elif SKIP_CONSENSUS or consensus_score >= MIN_CONSENSUS_THRESHOLD:
                        # Approved!
                        cprint("\nSTRATEGY APPROVED!", "white", "on_green")
                        cprint(
                            f"  Technique: {technique['name'] if technique else 'N/A'}",
                            "green",
                        )
                        cprint(f"  Novelty: {novelty_score * 100:.0f}%", "green")
                        if SKIP_CONSENSUS:
                            cprint(
                                f"  (Consensus skipped - backtester will validate)",
                                "cyan",
                            )
                        log_idea(
                            idea,
                            model_config,
                            consensus_score,
                            approved=True,
                            novelty_score=novelty_score,
                            technique=technique,
                        )
                        ideas_approved += 1
                        cycle_approved = 1

                    else:
                        # Rejected due to low consensus
                        cprint("\nLOW CONSENSUS - Rejected", "red")
                        log_idea(
                            idea,
                            model_config,
                            consensus_score,
                            approved=False,
                            novelty_score=novelty_score,
                            technique=technique,
                            rejection_reason="low consensus",
                        )

            # Stats
            cprint(
                f"\n📊 Total Stats: {ideas_approved}/{ideas_generated} approved | "
                f"Duplicates: {duplicates_caught} | Low Novelty: {low_novelty_rejected} | Incomplete: {incomplete_rejected}",
                "cyan",
            )

            # Show technique usage summary every 10 generations
            if ideas_generated % 10 == 0:
                tech_usage = load_technique_usage()
                if tech_usage:
                    most_used = sorted(
                        tech_usage.items(), key=lambda x: x[1], reverse=True
                    )[:3]
                    least_used = sorted(tech_usage.items(), key=lambda x: x[1])[:3]
                    cprint(
                        f"  Most used: {', '.join([f'{k}({v})' for k, v in most_used])}",
                        "cyan",
                    )
                    cprint(
                        f"  Least used: {', '.join([f'{k}({v})' for k, v in least_used])}",
                        "cyan",
                    )

            # Cooldown
            cprint(f"\nNext generation in {GENERATION_INTERVAL}s...", "yellow")

            for i in range(GENERATION_INTERVAL):
                remaining = GENERATION_INTERVAL - i
                emoji = MOON_PHASES[i % len(MOON_PHASES)]
                clear_line()
                print(f"\r{emoji} {remaining}s remaining...", end="", flush=True)
                time.sleep(1)

            print()

    except KeyboardInterrupt:
        cprint("\n\nScalping Agent stopped", "yellow")
        cprint(
            f"Final stats: {ideas_approved}/{ideas_generated} strategies approved",
            "cyan",
        )
        cprint(
            f"Duplicates caught: {duplicates_caught} | Low novelty rejected: {low_novelty_rejected} | Incomplete rejected: {incomplete_rejected}",
            "cyan",
        )

        # Show final technique distribution
        tech_usage = load_technique_usage()
        if tech_usage:
            cprint("\nTechnique Usage Distribution:", "magenta")
            for tech, count in sorted(
                tech_usage.items(), key=lambda x: x[1], reverse=True
            ):
                cprint(f"  {tech}: {count}", "cyan")


def test_run(num_ideas=1):
    """Run a test generation of scalping ideas with diversity tracking"""
    setup_files()

    cprint("\n" + "=" * 60, "magenta")
    cprint(" SCALPING AGENT v3.0 - TEST MODE ", "white", "on_yellow")
    cprint("=" * 60, "magenta")
    cprint(f"\nGenerating {num_ideas} idea(s)...\n", "cyan")
    cprint(f"Techniques available: {len(SCALPING_TECHNIQUES)}", "cyan")

    existing_ideas = load_existing_ideas()
    ideas_generated = 0
    attempts = 0
    max_attempts = num_ideas * 5  # Limit retries

    while ideas_generated < num_ideas and attempts < max_attempts:
        attempts += 1

        if USE_SWARM_MODE:
            idea, model_config, consensus_score, technique = (
                generate_scalping_idea_swarm()
            )
        else:
            idea, model_config, consensus_score, technique = (
                generate_scalping_idea_single()
            )

        if idea:
            # Check for duplicates
            is_dup, similar_to, similarity = is_duplicate(idea, existing_ideas)
            novelty_score = calculate_novelty_score(idea, existing_ideas)

            if is_dup:
                cprint(
                    f"DUPLICATE ({similarity * 100:.0f}% similar) - Retrying...",
                    "yellow",
                )
                continue

            if novelty_score < NOVELTY_CONFIG["min_novelty_score"]:
                cprint(
                    f"LOW NOVELTY ({novelty_score * 100:.0f}%) - Retrying...", "yellow"
                )
                continue

            if consensus_score >= MIN_CONSENSUS_THRESHOLD:
                log_idea(
                    idea,
                    model_config,
                    consensus_score,
                    approved=True,
                    novelty_score=novelty_score,
                    technique=technique,
                )
                ideas_generated += 1
                existing_ideas.add(idea.lower())
                cprint(
                    f"\nGenerated {ideas_generated}/{num_ideas} unique strategies",
                    "green",
                )
            else:
                cprint(
                    f"Low consensus ({consensus_score * 100:.0f}%) - Retrying...",
                    "yellow",
                )

        if ideas_generated < num_ideas:
            time.sleep(2)

    # Show summary
    cprint(
        f"\nTest complete! Generated {ideas_generated} strategies in {attempts} attempts",
        "green",
    )

    tech_usage = load_technique_usage()
    if tech_usage:
        cprint("\nTechniques used this session:", "cyan")
        for tech, count in sorted(tech_usage.items(), key=lambda x: x[1], reverse=True):
            cprint(f"  {tech}: {count}", "cyan")


def main():
    """Main function to run the scalping agent"""
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        test_run()
    elif len(sys.argv) > 1 and sys.argv[1] == "--once":
        test_run(num_ideas=1)
    else:
        run_scalping_loop()


if __name__ == "__main__":
    main()
