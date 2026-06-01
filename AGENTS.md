# AGENTS.md

This file provides guidance to Codex and other coding agents when working with code in this repository.

## Project Overview

This is an experimental AI trading system that orchestrates 48+ specialized AI agents to analyze markets, execute strategies, and manage risk across cryptocurrency markets, primarily Solana. The project uses a modular agent architecture with a unified LLM provider abstraction supporting Claude, OpenAI, DeepSeek, Groq, xAI, OpenRouter, and local Ollama models.

## Key Development Commands

### Environment Setup

```bash
# Use the existing conda environment (do not create new virtual environments)
conda activate tflow

# Install or update dependencies
pip install -r requirements.txt

# Update requirements.txt every time you add a new package
pip freeze > requirements.txt
```

### Running the System

```bash
# Run the main orchestrator
python src/main.py

# Run individual agents standalone
python src/agents/trading_agent.py
python src/agents/risk_agent.py
python src/agents/rbi_agent.py
python src/agents/chat_agent.py
```

Most agents under `src/agents/` are designed to run independently as scripts.

### Backtesting

```bash
# Use backtesting.py with pandas_ta or talib for indicators
# Sample OHLCV data is available at:
# src/data/rbi/BTC-USD-15m.csv
```

## Architecture Overview

### Core Structure

```text
src/
├── agents/              # Specialized AI agents
├── models/              # LLM provider abstraction (ModelFactory pattern)
├── strategies/          # User-defined trading strategies
├── scripts/             # Standalone utility scripts
├── data/                # Agent outputs, memory, analysis results
├── config.py            # Global configuration
├── main.py              # Main orchestrator
├── nice_funcs.py        # Shared trading utilities
├── nice_funcs_hl.py     # Hyperliquid-specific utilities
└── ezbot.py             # Legacy trading controller
```

### Agent Ecosystem

- Trading agents: `trading_agent`, `strategy_agent`, `risk_agent`, `copybot_agent`
- Market analysis: `sentiment_agent`, `whale_agent`, `funding_agent`, `liquidation_agent`, `chartanalysis_agent`
- Content creation: `chat_agent`, `clips_agent`, `tweet_agent`, `video_agent`, `phone_agent`
- Strategy development: `rbi_agent`, `research_agent`
- Specialized: `sniper_agent`, `solana_agent`, `tx_agent`, `million_agent`, `tiktok_agent`, `compliance_agent`

Each agent can run independently or as part of the main orchestrator loop.

### LLM Integration

Located at `src/models/model_factory.py` and documented in `src/models/README.md`.

All agents should use `ModelFactory.create_model()` for consistent LLM access:

```python
from src.models.model_factory import ModelFactory

model = ModelFactory.create_model("anthropic")  # or "openai", "deepseek", "groq", etc.
response = model.generate_response(system_prompt, user_content, temperature, max_tokens)
```

### Configuration Management

Primary configuration lives in `src/config.py`.

- Trading settings: monitored and excluded tokens, position sizing, order size caps
- Risk management: cash percentage, position caps, loss and gain limits, minimum balance
- Agent behavior: sleep interval and active agent orchestration
- AI settings: model, max tokens, temperature

Environment variables live in `.env` with examples in `.env_example`.

- Trading APIs: `BIRDEYE_API_KEY`, `TRADEHIVE_API_KEY`, `COINGECKO_API_KEY`
- AI services: `ANTHROPIC_KEY`, `OPENAI_KEY`, `DEEPSEEK_KEY`, `GROQ_API_KEY`, `GROK_API_KEY`, `OPENROUTER_API_KEY`
- Blockchain: `SOLANA_PRIVATE_KEY`, `HYPER_LIQUID_ETH_PRIVATE_KEY`, `RPC_ENDPOINT`

### Shared Utilities

`src/nice_funcs.py` contains core trading functions including:

- Data access: `token_overview()`, `token_price()`, `get_position()`, `get_ohlcv_data()`
- Trading actions: `market_buy()`, `market_sell()`, `chunk_kill()`, `open_position()`
- Analysis helpers: technical indicators, PnL calculations, rug pull detection

`src/agents/api.py` exposes the `TradeHiveAPI` class for custom TradeHive endpoints such as liquidation, funding, OI, and copybot data.

### Data Flow Pattern

```text
Config/Input -> Agent Init -> API Data Fetch -> Data Parsing ->
LLM Analysis (via ModelFactory) -> Decision Output ->
Result Storage (CSV/JSON in src/data/) -> Optional Trade Execution
```

## Development Rules

### File Management

- Keep files under 800 lines where practical. If a file grows past that, split it and update nearby documentation.
- Do not move files without asking first.
- Do not create new virtual environments. Use `conda activate tflow`.
- Update `requirements.txt` after adding any dependency.

### Backtesting

- Use `backtesting.py` for backtests.
- Use `pandas_ta` or `talib` for technical indicators instead of built-in indicator helpers.
- Prefer the sample data already in the repo, especially `src/data/rbi/BTC-USD-15m.csv`.

### Code Style

- Do not use fake or synthetic market data. Use real data or fail clearly.
- Keep error handling pragmatic. Avoid burying real failures behind excessive `try/except`.
- Never expose API keys or secrets from `.env`.

### Agent Development Pattern

When creating a new agent:

1. Reuse patterns from existing agents.
2. Use `ModelFactory` for LLM access.
3. Store outputs in `src/data/[agent_name]/`.
4. Make the agent independently executable.
5. Add configuration to `src/config.py` if needed.
6. Follow the `[purpose]_agent.py` naming pattern.

### Testing Strategies

Place strategy definitions in `src/strategies/`:

```python
class YourStrategy(BaseStrategy):
    name = "strategy_name"
    description = "what it does"

    def generate_signals(self, token_address, market_data):
        return {
            "action": "BUY" | "SELL" | "NOTHING",
            "confidence": 0-100,
            "reasoning": "explanation",
        }
```

## Important Context

### Risk-First Philosophy

- The risk agent runs before trading decisions in the main loop.
- Circuit breakers are configurable through values like `MAX_LOSS_USD` and `MINIMUM_BALANCE_USD`.
- Position-closing decisions can use AI confirmation through config flags such as `USE_AI_CONFIRMATION`.

### Data Sources

1. BirdEye API for Solana token data including price, volume, liquidity, and OHLCV
2. TradeHive API for custom signals such as liquidations, funding rates, OI, and copybot data
3. CoinGecko API for token metadata, market caps, and sentiment
4. Helius RPC for Solana blockchain interaction

### Autonomous Execution

- The main loop runs every 15 minutes by default through `SLEEP_BETWEEN_RUNS_MINUTES`.
- Agents are expected to keep running through non-fatal issues.
- Keyboard interrupt should allow graceful shutdown.
- Console logging uses color output via `termcolor`.

### RBI Agent Workflow

1. User provides a YouTube URL, PDF, or trading idea text.
2. The RBI flow analyzes and extracts strategy logic.
3. It generates `backtesting.py`-compatible code.
4. It executes the backtest and returns performance metrics.

## Common Patterns

### Adding a New Agent

1. Create `src/agents/your_agent.py`.
2. Implement standalone execution logic.
3. Add it to `ACTIVE_AGENTS` in `main.py` if orchestration is needed.
4. Use `ModelFactory` for LLM calls.
5. Store results in `src/data/your_agent/`.

### Switching AI Models

Edit `src/config.py`:

```python
AI_MODEL = "claude-3-haiku-20240307"
# AI_MODEL = "claude-3-sonnet-20240229"
# AI_MODEL = "claude-3-opus-20240229"
```

Or choose a provider per agent:

```python
model = ModelFactory.create_model("deepseek")
model = ModelFactory.create_model("groq")
```

### Reading Market Data

```python
from src.nice_funcs import token_overview, get_ohlcv_data, token_price

overview = token_overview(token_address)
ohlcv = get_ohlcv_data(token_address, timeframe="1H", days_back=3)
price = token_price(token_address)
```

## Project Philosophy

This is an experimental, educational project demonstrating AI agent patterns through algorithmic trading.

- There are no guarantees of profitability and the system carries substantial risk of loss.
- The project is open source and intended for learning.
- The architecture is useful beyond trading as a practical multi-agent orchestration example.
