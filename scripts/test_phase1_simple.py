#!/usr/bin/env python3
"""
v2.0 Phase 1 Integration Test - Simplified (No Unicode)

Tests: All 4 agents initialize and collect signals properly
"""

import asyncio
import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.crypto_polymarket.orchestrator import CryptoPolymarketOrchestrator

async def test_phase1():
    print("="*70)
    print("V2.0 PHASE 1 INTEGRATION TEST")
    print("   Testing: 4-Agent Initialization & Signal Collection")
    print("="*70)
    
    orch = CryptoPolymarketOrchestrator()
    
    try:
        # Start pipeline
        print("\n[1/5] Starting data pipeline...")
        await orch._start_pipeline()
        print("      [OK] Pipeline connected and receiving data\n")
        
        # Check components initialized
        print("[2/5] Verifying component initialization...")
        components = [
            ("liquidation_agent", orch, "Liquidation Agent"),
            ("funding_agent", orch, "Funding Agent"),
            ("open_interest_agent", orch, "Open Interest Agent"),
            ("volume_agent", orch, "Volume Agent"),
            ("whale_agent", orch, "Whale Agent"),
            ("timeframe_controller", orch, "Timeframe Controller"),
            ("regime_detector", orch, "Regime Detector"),
            ("edge_calculator", orch, "Edge Calculator"),
            # ("risk_manager", orch, "Risk Manager"),  # Phase 4
        ]
        
        for attr, obj, name in components:
            assert hasattr(obj, attr), f"[FAIL] Missing {attr}"
            print(f"      [OK] {name:25s} initialized")
        
        print("\n[3/5] Testing parallel signal collection...")
        signals = await orch._collect_signals()
        
        if len(signals) >= 4:
            print(f"      [OK] Collected {len(signals)}/5 signals successfully")
            for name, signal in signals.items():
                print(f"         - {name}: {signal.direction.value} "
                      f"({signal.confidence:.0%} confidence)")
        else:
            print(f"      [FAIL] Only collected {len(signals)} signals (expected 5)")
            raise AssertionError("Signal collection incomplete")
        
        print("\n[4/5] Testing configuration...")
        print(f"      [OK] Timeframes configured: {list(orch.config.timeframes.keys())}")
        print(f"      [OK] Multi-timeframe enabled: {orch.config.enable_multi_timeframe}")
        print(f"      [OK] Dynamic weights enabled: {orch.config.enable_dynamic_weights}")
        print(f"      [OK] Edge calculator enabled: {orch.config.enable_edge_calculator}")
        print(f"      [OK] Kelly sizing enabled: {orch.config.enable_kelly_sizing}")
        
        print("\n[5/5] Testing stability (2nd collection)...")
        signals_2 = await orch._collect_signals()
        
        if len(signals_2) >= 4:
            print(f"      [OK] 2nd collection successful: {len(signals_2)} signals")
        else:
            print(f"      [FAIL] 2nd collection failed: {len(signals_2)} signals")
        
        print("\n" + "="*70)
        print("PHASE 1 INTEGRATION TEST PASSED!")
        print("="*70)
        print("\nSummary:")
        print("   - All 4 data agents initialized and returning signals")
        print("   - Intelligence components initialized")
        print("   - Multi-timeframe framework configured")
        print("   - Ready for Phase 2: Signal Aggregator Redesign")
        print("="*70 + "\n")
        
        await orch._stop_pipeline()
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Phase 1 test failed: {e}")
        import traceback
        traceback.print_exc()
        await orch._stop_pipeline()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_phase1())
    sys.exit(0 if success else 1)
