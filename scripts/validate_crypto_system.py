"""
Quick validation of enhanced crypto polymarket system components
Run this to verify all imports and basic functionality work
"""

import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    print(" Validating imports...")
    print("="*60)

    # Test 1: Config imports
    from src.agents.crypto_polymarket.config import CryptoPolymarketConfig, SignalDirection, TradeSide
    print(" Config imports successful")

    # Test 2: Data agents
    from src.agents.crypto_polymarket.data_agents.base_data_agent import BaseDataAgent
    from src.agents.crypto_polymarket.data_agents.liquidation_agent import LiquidationAgent
    from src.agents.crypto_polymarket.data_agents.funding_agent import FundingAgent
    from src.agents.crypto_polymarket.data_agents.open_interest_agent import OpenInterestAgent
    from src.agents.crypto_polymarket.data_agents.volume_agent import VolumeAgent
    print(" Data agents imports successful")

    # Test 3: Core components
    from src.agents.crypto_polymarket.timeframe_controller import TimeframeController
    from src.agents.crypto_polymarket.regime_detection import RegimeDetectionEngine
    from src.agents.crypto_polymarket.edge_calculator import EdgeCalculator
    print(" Core component imports successful")

    # Test 4: Models
    from src.agents.crypto_polymarket.models import (
        MarketSignal, AggregatedSignal, CryptoMarket, TradeDecision,
        TimeframeSignalBundle
    )
    print(" Models imports successful")

    # Test 5: Data pipeline
    from src.data.connectors.unified_pipeline import UnifiedDataPipeline
    print(" Data pipeline import successful")

    # Test 6: Config instantiation
    config = CryptoPolymarketConfig()
    print("\n Config instantiated")

    # Test 7: Models instantiation
    signal = MarketSignal(
        agent_name="test",
        symbol="BTC",
        timestamp=datetime.utcnow(),
        direction=SignalDirection.BULLISH,
        strength=0.5,
        confidence=0.6,
        raw_data={}
    )
    print(" MarketSignal instantiated")

    # Test 8: Edge calculation basics
    calculator = EdgeCalculator(config)
    # Mock edge calculation
    edge = calculator.calculate_edge(
        signal_probability=0.60,
        market_price=0.45,
        hours_until_resolution=24
    )
    print(f" Edge calculation works: {edge['edge_percent']:.1f}%")

    print("\n" + "="*60)
    print(" ALL SYSTEMS VALIDATED SUCCESSFULLY")
    print("="*60)
    print("\n Your enhanced crypto polymarket trading system is ready!")

except ImportError as e:
    print(f"\n Import error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

except Exception as e:
    print(f"\n Runtime error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

if __name__ == "__main__":
    from datetime import datetime
    globals()['datetime'] = datetime  # Make datetime available
    
    print("\nKimi's Crypto Polymarket System Validation")
    print("="*60 + "\n")
