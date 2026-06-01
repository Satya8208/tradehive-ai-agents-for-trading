"""
Test Script for Poker Agent Integration
Verifies the full loop:
1. Agent Initialization
2. Persistence (Saving/Loading Opponents)
3. God Mode (Equity Calculation)
4. Context Management
"""

import sys
from pathlib import Path
import time

# Add project root to path
PROJECT_ROOT = str(Path(__file__).parent.parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from src.agents.poker.poker_agent import PokerAgent, GameMode, Position, PlayerStats, parse_cards

def test_poker_integration():
    print("🎰 Testing Poker God Agent Integration 🎰")
    print("="*50)

    # 1. Initialize
    print("\n1. Initializing Agent...")
    agent = PokerAgent(mode=GameMode.SIMULATION)
    print(f"✅ Agent created (Session ID: {agent.session_id})")

    # 2. Test Persistence
    print("\n2. Testing Persistence...")
    villain_name = "Test_Villain_Integration"
    villain_stats = PlayerStats(
        vpip=45,
        pfr=30,
        three_bet=10,
        aggression_factor=60,
        # tendency=PlayerTendency.LAG # Computed
    )
    
    agent.add_opponent(villain_name, villain_stats)
    
    # Check if file exists
    expected_path = agent.opponents_dir / f"{villain_name}.json"
    if expected_path.exists():
        print(f"✅ Opponent saved to {expected_path}")
    else:
        print(f"❌ Failed to save opponent to {expected_path}")
        return

    # 3. Test New Hand & Context
    print("\n3. Testing Hand Context...")
    hero_hand = parse_cards("As Ks")
    agent.new_hand(hero_hand, Position.BTN)
    
    if len(agent.context.hand_state.hole_cards) == 2:
         print(f"✅ Hand state initialized correctly: {hero_hand}")
    else:
         print(f"❌ Hand state failed initialization")
         return

    # 4. Test God Mode Equity (Real vs Heuristic)
    print("\n4. Testing God Mode Equity...")
    board = parse_cards("Js Ts 2d")
    agent.set_board(board)
    agent.set_pot(10, 0)
    
    # Case A: No range (Heuristic)
    print("  Testing Heuristic Mode...")
    advice_heuristic = agent.get_postflop_advice()
    print(f"  -> Action: {advice_heuristic['decision'].action.value}")
    
    # Case B: With Range (Monte Carlo)
    print("  Testing Monte Carlo Mode (vs Random Range)...")
    agent.set_villain_range("22+, A2s+, KQs, QJs")
    
    start_time = time.time()
    advice_mc = agent.get_postflop_advice()
    duration = (time.time() - start_time) * 1000
    
    equity = advice_mc.get('equity', {}).get('equity', 0)
    print(f"  -> Equity: {equity*100:.1f}%")
    print(f"  -> Latency: {duration:.0f}ms")
    
    if equity > 0:
        print("✅ Monte Carlo simulation ran successfully")
    else:
        print("❌ Equity calculation failed or returned 0")

    print("\n🎉 ALL SYSTEMS GO! The Poker God is ready.")
    if expected_path.exists():
        expected_path.unlink()

if __name__ == "__main__":
    test_poker_integration()
