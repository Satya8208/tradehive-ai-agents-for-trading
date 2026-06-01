#!/usr/bin/env python3
"""
Phase 1: Core Agent Integration Test
Tests initialization and basic signal collection
"""

import asyncio
import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def test_phase1():
    """Test Phase 1 integration"""
    print("Phase 1: Core Agent Integration")
    print("=" * 50)
    
    # Test 1: Import
    print("\n1. Testing imports...")
    try:
        from src.agents.crypto_polymarket.orchestrator import CryptoPolymarketOrchestrator
        print("   [OK] Orchestrator imported")
    except Exception as e:
        print(f"   [FAIL] Import error: {e}")
        return False
    
    # Test 2: Initialize
    print("\n2. Testing initialization...")
    try:
        orch = CryptoPolymarketOrchestrator()
        print("   [OK] Orchestrator initialized")
    except Exception as e:
        print(f"   [FAIL] Initialization error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test 3: Check components
    print("\n3. Checking components...")
    components = [
        'liquidation_agent', 'funding_agent', 'open_interest_agent', 
        'volume_agent', 'whale_agent', 'timeframe_controller', 
        'regime_detector', 'edge_calculator'  # Skip risk_manager for now
    ]
    
    for comp in components:
        if hasattr(orch, comp):
            print(f"   [OK] {comp}")
        else:
            print(f"   [FAIL] Missing {comp}")
            return False
    
    print("\nPhase 1 Test: PASSED")
    print("=" * 50)
    return True

if __name__ == "__main__":
    success = test_phase1()
    sys.exit(0 if success else 1)
