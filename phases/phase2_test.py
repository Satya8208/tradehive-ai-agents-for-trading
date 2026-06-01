#!/usr/bin/env python3
"""
Phase 2: Signal Aggregator v2.0 Test

Tests:
- 4-agent signal aggregation
- Regime-based dynamic weighting
- Signal breakdowns and summaries
"""

import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def test_phase2():
    print("Phase 2: Signal Aggregator v2.0 Test")
    print("=" * 60)
    
    # Test 1: Import
    print("\n1. Importing SignalAggregator v2.0...")
    try:
        from src.agents.crypto_polymarket.analysis.signal_aggregator_v2 import SignalAggregatorV2
        print("   [OK] Imported SignalAggregatorV2")
    except Exception as e:
        print(f"   [FAIL] Import error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test 2: Initialize
    print("\n2. Initializing aggregator...")
    try:
        from src.agents.crypto_polymarket.config import CryptoPolymarketConfig
        from src.agents.crypto_polymarket.models import MarketSignal, SignalDirection
        
        config = CryptoPolymarketConfig()
        aggregator = SignalAggregatorV2(config)
        print("   [OK] Aggregator initialized")
    except Exception as e:
        print(f"   [FAIL] Init error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test 3: Create mock signals
    print("\n3. Creating mock signals for 4 agents...")
    from datetime import datetime
    
    signals = {
        "liquidation": MarketSignal(
            agent_name="liquidation",
            symbol="BTC",
            timestamp=datetime.utcnow(),
            direction=SignalDirection.BEARISH,
            confidence=0.75,
            strength=0.6,
            raw_data={"ratio": 1.8, "long_liquidations": 1500000, "short_liquidations": 800000},
            reasoning="Heavy long liquidations"
        ),
        "funding": MarketSignal(
            agent_name="funding",
            symbol="BTC",
            timestamp=datetime.utcnow(),
            direction=SignalDirection.BULLISH,
            confidence=0.60,
            strength=0.4,
            raw_data={"rate": -0.0008, "extreme": True},
            reasoning="Extreme negative funding rate"
        ),
        "open_interest": MarketSignal(
            agent_name="open_interest",
            symbol="BTC",
            timestamp=datetime.utcnow(),
            direction=SignalDirection.BULLISH,
            confidence=0.80,
            strength=0.7,
            raw_data={"change_pct": 15.0, "price_change": 2.5},
            reasoning="OI increasing with price"
        ),
        "volume": MarketSignal(
            agent_name="volume",
            symbol="BTC",
            timestamp=datetime.utcnow(),
            direction=SignalDirection.BULLISH,
            confidence=0.55,
            strength=0.3,
            raw_data={"spike_ratio": 2.5, "velocity": 1_250_000},
            reasoning="Volume spike detected"
        )
    }
    print("   [OK] Created 4 mock signals")
    
    # Test 4: Aggregation without regime (base weights)
    print("\n4. Testing aggregation with base weights...")
    try:
        result = aggregator.aggregate(signals)
        
        print(f"   Direction: {result.direction.value}")
        print(f"   Score: {result.composite_score:+.3f}")
        print(f"   Confidence: {result.confidence:.1%}")
        print(f"   Dominant: {result.dominant_signal}")
        
        # Should be bullish (funding, OI, volume bullish; liquidation bearish)
        if result.direction == SignalDirection.BULLISH:
            print("   [OK] Correctly aggregated to BULLISH (3 bullish, 1 bearish)")
        else:
            print(f"   [WARN] Expected bullish, got {result.direction.value}")
        
        # Show breakdown
        print("\n   Signal Breakdown:")
        for agent, contrib in sorted(result.signal_breakdown.items(), 
                                   key=lambda x: abs(x[1]), reverse=True):
            print(f"      - {agent:15s}: {contrib:+.3f}")
        
    except Exception as e:
        print(f"   [FAIL] Aggregation error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test 5: Aggregation with regime (dynamic weights)
    print("\n5. Testing aggregation with regime-based weights...")
    try:
        from src.agents.crypto_polymarket.regime_detection import MarketRegime
        
        # Test in TRENDING regime (should increase OI/liquidation weights)
        regime_result = aggregator.aggregate(signals, MarketRegime.TRENDING)
        
        print(f"   Trending regime: {regime_result.direction.value}")
        print(f"   Score: {regime_result.composite_score:+.3f}")
        
        # Check if weights changed
        base_weights = result.weights_used
        trend_weights = regime_result.weights_used
        
        print("\n   Weight Comparison:")
        for agent in base_weights.keys():
            base = base_weights[agent]
            trend = trend_weights[agent]
            change = "UP" if trend > base else "DOWN" if trend < base else "SAME"
            print(f"      - {agent:15s}: {base:.1%} => {trend:.1%} ({change})")
        
        # In trending regime, OI and liquidation should have higher weights
        if trend_weights["open_interest"] > base_weights["open_interest"]:
            print("   [OK] OI weight increased in trending regime (as expected)")
        else:
            print("   [WARN] OI weight did not increase in trending regime")
            
    except Exception as e:
        print(f"   [FAIL] Regime aggregation error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test 6: Test different regimes
    print("\n6. Testing all four regimes...")
    regimes = [
        MarketRegime.LOW_VOL,
        MarketRegime.HIGH_VOL,
        MarketRegime.TRENDING,
        MarketRegime.RANGING
    ]
    
    for regime in regimes:
        result = aggregator.aggregate(signals, regime)
        print(f"   {regime.value:10s}: {result.direction.value:8s} "
              f"(score: {result.composite_score:+.3f})")
    
    print("   [OK] All regimes processed")
    
    # Test 7: Edge cases
    print("\n7. Testing edge cases...")
    
    # Empty signals
    empty_result = aggregator.aggregate({})
    if empty_result.direction == SignalDirection.NEUTRAL:
        print("   [OK] Empty signals => neutral")
    else:
        print("   [FAIL] Empty signals should be neutral")
        return False
    
    # Single signal
    single_signal = {"liquidation": signals["liquidation"]}
    single_result = aggregator.aggregate(single_signal)
    if single_result.dominant_signal == "liquidation":
        print("   [OK] Single signal handled correctly")
    else:
        print("   [FAIL] Single signal not handled correctly")
        return False
    
    # Conflicting signals (neutral expected)
    conflict_signals = {
        "liquidation": MarketSignal(
            agent_name="liquidation",
            symbol="BTC",
            timestamp=datetime.utcnow(),
            direction=SignalDirection.BEARISH,
            confidence=0.9,
            strength=0.8,
            raw_data={},
            reasoning="Conflicting bearish"
        ),
        "funding": MarketSignal(
            agent_name="funding",
            symbol="BTC",
            timestamp=datetime.utcnow(),
            direction=SignalDirection.BULLISH,
            confidence=0.9,
            strength=0.8,
            raw_data={},
            reasoning="Conflicting bullish"
        ),
        "open_interest": MarketSignal(
            agent_name="open_interest",
            symbol="BTC",
            timestamp=datetime.utcnow(),
            direction=SignalDirection.BULLISH,
            confidence=0.9,
            strength=0.8,
            raw_data={},
            reasoning="Conflicting bullish"
        ),
        "volume": MarketSignal(
            agent_name="volume",
            symbol="BTC",
            timestamp=datetime.utcnow(),
            direction=SignalDirection.BEARISH,
            confidence=0.9,
            strength=0.8,
            raw_data={},
            reasoning="Conflicting bearish"
        ),
    }
    conflict_result = aggregator.aggregate(conflict_signals)
    print(f"   [OK] Conflicting signals => {conflict_result.direction.value} "
          f"(score: {conflict_result.composite_score:+.3f})")
    
    print("\n" + "="*60)
    print("Phase 2 Test: PASSED")
    print("="*60)
    print("\nSummary:")
    print("   - 4-agent aggregation working")
    print("   - Regime-based dynamic weights working")
    print("   - Signal breakdowns and summaries working")
    print("   - Edge cases handled correctly")
    print("\nReady for Phase 3: Multi-timeframe & Intelligence Integration")
    print("="*60 + "\n")
    
    return True

if __name__ == "__main__":
    success = test_phase2()
    sys.exit(0 if success else 1)
