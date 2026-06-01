"""
Crypto Polymarket Trading Agent

A full orchestration-based trading agent for BTC/ETH prediction markets on Polymarket.
Uses market signals from multiple data sub-agents and AI swarm consensus for decisions.

Built with love by TradeHive
"""

from .orchestrator import CryptoPolymarketOrchestrator
from .config import CryptoPolymarketConfig, ExecutionMode

__all__ = [
    "CryptoPolymarketOrchestrator",
    "CryptoPolymarketConfig",
    "ExecutionMode",
]
