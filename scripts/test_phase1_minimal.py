#!/usr/bin/env python3
"""
Minimal Phase 1 test - just verify imports and basic initialization
"""

import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

print("Testing imports...")

try:
    from src.agents.crypto_polymarket.orchestrator import CryptoPolymarketOrchestrator
    print("[OK] Imported orchestrator")
    
    from src.agents.crypto_polymarket.data_agents.funding_agent import FundingAgent
    from src.agents.crypto_polymarket.data_agents.open_interest_agent import OpenInterestAgent
    from src.agents.crypto_polymarket.data_agents.volume_agent import VolumeAgent
    print("[OK] Imported all 3 new data agents")
    
    from src.agents.crypto_polymarket.timeframe_controller import TimeframeController
    from src.agents.crypto_polymarket.regime_detection import RegimeDetectionEngine
    from src.agents.crypto_polymarket.edge_calculator import EdgeCalculator
    print("[OK] Imported intelligence components")
    
    print("\n" + "="*60)
    print("PHASE 1 IMPORT TEST PASSED")
    print("="*60)
    print("\nAll components successfully imported!")
    print("Ready for actual integration testing.")
    
    sys.exit(0)
    
except Exception as e:
    print(f"\n[FAIL] Import error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
