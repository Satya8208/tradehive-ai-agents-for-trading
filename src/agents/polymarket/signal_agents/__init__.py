"""
TradeHive's Signal Agents Package
Agents that analyze market data to generate trading signals
"""

from .liquidation_agent import LiquidationAgent, LiquidationSignal
from .whale_agent import WhaleAgent, WhaleSignal
from .signal_aggregator import SignalAggregator, AggregatedSignal, TradingDecision
from .ai_signal_aggregator import AISignalAggregator, AISignal

__all__ = [
    "LiquidationAgent",
    "LiquidationSignal",
    "WhaleAgent",
    "WhaleSignal",
    "SignalAggregator",
    "AggregatedSignal",
    "TradingDecision",
    "AISignalAggregator",
    "AISignal"
]
