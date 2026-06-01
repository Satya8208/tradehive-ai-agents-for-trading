# Scalping Strategy Generator Agent

**Created by TradeHive** ⚡🌙

The Scalping Agent uses AI to generate high-frequency scalping trading strategies optimized for quick in/out trades on small capital.

## What It Does
- Generates scalping strategies using AI (DeepSeek)
- Targets 1m, 5m, 15m timeframes
- Creates strategies with tight stops (0.5-2%)
- Small profit targets (0.5-3%)
- Outputs directly to ideas.txt for RBI backtesting

## Usage

```bash
# Run continuous generation
python src/agents/scalping_agent.py

# Run single test generation
python src/agents/scalping_agent.py --test

# Generate one idea and exit
python src/agents/scalping_agent.py --once
```

## Output
```
src/data/scalping_strategies/
├── ideas.txt           # All scalping ideas
├── scalping_ideas.csv  # Full log with timestamps
```

Also outputs to `src/data/rbi_pp_multi/ideas.txt` for immediate backtesting!

## Configuration

Edit the top of `scalping_agent.py`:

```python
# Generation interval (seconds)
GENERATION_INTERVAL = 10

# AI Models
MODELS = [
    {"type": "deepseek", "name": "deepseek-chat"},
    {"type": "deepseek", "name": "deepseek-reasoner"}
]
```

## Scalping Techniques

The agent generates strategies using:
- Order flow / tape reading
- VWAP bounces
- EMA crossovers (9/21)
- RSI/Stochastic extremes
- Volume spikes
- Momentum breakouts
- Liquidity grabs
- Bollinger Band squeezes

## Integration with RBI

After generating ideas, run the RBI agent to backtest:

```bash
# Terminal 1: Generate scalping ideas
python src/agents/scalping_agent.py

# Terminal 2: Backtest the ideas
python src/agents/rbi_agent_pp_multi.py
```

---

**Made with ❤️ by TradeHive**
