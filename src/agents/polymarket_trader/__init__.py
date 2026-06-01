"""
Polymarket CLI Trading Agents

A modular trading system that uses the Polymarket CLI binary
for market discovery, analysis, and trade execution.

Usage:
    python -m src.agents.polymarket_trader.paper_run --cycles 3
    python -m src.agents.polymarket_trader.live_run --confirm-live --cycles 1

Components:
    - config: All configuration settings
    - models: Data models (CLIMarket, SwarmConsensus, TradeDecision, etc.)
    - cli_wrapper: Subprocess wrapper for polymarket binary
    - market_scanner: Discover + filter crypto markets
    - swarm_analyzer: 3-model AI consensus
    - edge_calculator: Kelly criterion + edge calculation
    - arbitrage_detector: Combinatorial + cross-market arb detection
    - risk_manager: Circuit breakers, position tracking
    - trader: Trade execution (dry_run/paper/live)
    - whale_tracker: Monitor top traders
    - orchestrator: Main loop
"""

from .config import PolymarketCLIConfig, ExecutionMode, get_config, get_polymarket_cli_config
from .orchestrator import PolymarketCLIOrchestrator
from .research_team import QuantResearchTeam

__version__ = "1.0.0"
__all__ = [
    "PolymarketCLIConfig",
    "ExecutionMode",
    "get_polymarket_cli_config",
    "get_config",
    "PolymarketCLIOrchestrator",
    "QuantResearchTeam",
]
