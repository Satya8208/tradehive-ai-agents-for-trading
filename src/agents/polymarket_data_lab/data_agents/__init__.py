"""
Data Agents for Crypto Polymarket

Sub-agents that collect market signals (v2.1):
- LiquidationAgent: Tracks long/short liquidations (30% weight)
- FundingAgent: Monitors funding rates (22% weight)
- OpenInterestAgent: Tracks open interest changes (18% weight)
- VolumeAgent: Analyzes trading volume (15% weight)
- OrderBookImbalanceAgent: Analyzes bid/ask imbalance (15% weight)
- WhaleAgent: Detects whale activity via OI changes (confirmation)
"""

from .base_data_agent import BaseDataAgent
from .liquidation_agent import LiquidationAgent
from .whale_agent import WhaleAgent
from .orderbook_agent import OrderBookImbalanceAgent

__all__ = [
    "BaseDataAgent",
    "LiquidationAgent",
    "WhaleAgent",
    "OrderBookImbalanceAgent",
]
