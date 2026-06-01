#!/bin/bash
# Quick Cleanup Script - Blackjack God Agent
# Run this after making the changes below to verify

echo "🧹 CLEANUP VERIFICATION"
echo "======================"

# 1. Add Fab 4 deviations (manual step required)
echo "✅ Step 1: Add Fab 4 deviations to strategy_engine.py"
echo "   - Add 3 lines to ILLUSTRIOUS_18 dict"
echo "   - (14, '10', False, False): ('R', 3)"
echo "   - (15, '9', False, False): ('R', 2)"
echo "   - (15, 'A', False, False): ('R', 1)"

# 2. Fix insurance thresholds (manual step required)
echo "✅ Step 2: Add SYSTEM_INSURANCE in strategy_engine.py"
echo "   - Define per-system thresholds"
echo "   - Hi-Lo: 3, Omega II: 2, Wong Halves: 1.5"

# 3. Run tests
echo "✅ Step 3: Run verification tests"
python test_advisor_mode.py

echo ""
echo "If all tests pass → DEPLOY!"
echo "If any fail → Debug the specific deviation"
