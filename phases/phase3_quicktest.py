#!/usr/bin/env python3
"""
Quick Phase 3 test - just validate components initialize
"""

import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

print("Phase 3 Quick Test - Components Check")
print("=" * 50)

# Test imports
try:
    print("\n[1] Testing imports...")
    from src.agents.crypto_polymarket.orchestrator import CryptoPolymarketOrchestrator
    from src.agents.crypto_polymarket.analysis.signal_aggregator_v2 import SignalAggregatorV2
    from src.agents.crypto_polymarket.regime_detection import MarketRegime, RegimeDetectionEngine
    from src.agents.crypto_polymarket.edge_calculator import EdgeCalculator
    print("   [OK] All imports successful")
except Exception as e:
    print(f"   [FAIL] {e}")
    sys.exit(1)

# Test codegen
try:
    print("\n[2] Testing orchestrator generation...")
    orch = CryptoPolymarketOrchestrator()
    print("   [OK] Orchestrator created")
    
    # Check components
    for comp in ['liquidation_agent', 'funding_agent', 'open_interest_agent', 'volume_agent']:
        if hasattr(orch, comp):
            print(f"   [OK] {comp} exists")
        else:
            print(f"   [FAIL] Missing {comp}")
            sys.exit(1)
    
    if hasattr(orch, 'edge_calculator'):
        print("   [OK] edge_calculator exists")
    else:
        print("   [FAIL] Missing edge_calculator")
        sys.exit(1)
        
    if hasattr(orch, 'regime_detector'):
        print("   [OK] regime_detector exists")
    else:
        print("   [FAIL] Missing regime_detector")
        sys.exit(1)
        
    if isinstance(orch.signal_aggregator, SignalAggregatorV2):
        print("   [OK] SignalAggregatorV2 active")
    else:
        print(f"   [FAIL] Wrong aggregator type: {type(orch.signal_aggregator)}")
        sys.exit(1)
        
except Exception as e:
    print(f"   [FAIL] {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 50)
print("Phase 3 Quick Test: PASSED")
print("=" * 50)
print("\nv2.0 components successfully initialized!")
print("Ready for integration testing.")
sys.exit(0)
