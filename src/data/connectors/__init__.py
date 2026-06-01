"""
🌙 TradeHive's Data Connectors Package
Real-time market data from multiple exchanges for Polymarket trading signals

Built with love by TradeHive 🚀
"""

from .base_connector import BaseConnector
from .hyperliquid_connector import HyperliquidConnector
from .binance_connector import BinanceConnector
from .bybit_connector import BybitConnector
from .unified_pipeline import UnifiedDataPipeline

# Optional imports (may not be fully implemented)
try:
    from .polymarket_connector import PolymarketConnector
except ImportError:
    PolymarketConnector = None

try:
    from .dydx_connector import DydxConnector
except ImportError:
    DydxConnector = None

__all__ = [
    'BaseConnector',
    'HyperliquidConnector',
    'BinanceConnector',
    'BybitConnector',
    'UnifiedDataPipeline'
]
