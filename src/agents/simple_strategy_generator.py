"""
🌙 TradeHive's SIMPLE Strategy Generator 🚀

This generates PRACTICAL, TESTABLE strategies that will ACTUALLY WORK with the RBI agent.
No pairs trading, no time-of-day logic, no complex calculations.

Just simple, tradeable strategies based on standard indicators.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from termcolor import cprint
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

# Load environment
load_dotenv()

# Import model factory
from src.models.model_factory import model_factory

# Configuration
STRATEGIES_OUTPUT_DIR = Path(__file__).parent.parent / "data/rbi_pp_multi/ai_lab_strategies"
STRATEGIES_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Ultra-simple prompt that FORCES practical strategies
SIMPLE_STRATEGY_PROMPT = """
You are creating a SIMPLE, TESTABLE trading strategy for crypto (BTC/ETH/SOL).

🚨 CRITICAL CONSTRAINTS:
1. SINGLE ASSET ONLY (no pairs, no ratios, no BTC/ETH comparisons)
2. 15-MINUTE OHLCV DATA (price, volume only)
3. STANDARD INDICATORS ONLY (RSI, MACD, SMA, EMA, ATR, Bollinger Bands)
4. 2-3 CONDITIONS MAXIMUM for entry
5. MUST TRIGGER 10-20+ TIMES PER MONTH

═══════════════════════════════════════════════════
STRATEGY TEMPLATE (FILL THIS OUT):
═══════════════════════════════════════════════════

STRATEGY NAME: [2-3 words, unique]

CORE IDEA:
[1-2 sentences explaining the edge in simple terms]

ENTRY CONDITIONS (choose 2-3 from below and specify exact values):
✅ RSI-based: "RSI(14) < 30" or "RSI(14) > 70"
✅ Moving Average: "Price crosses above SMA(20)" or "EMA(10) > EMA(50)"
✅ MACD: "MACD line crosses above signal line"
✅ Bollinger Bands: "Price closes above upper band" or "Price closes below lower band"
✅ Volume: "Volume > 1.5x SMA(20)" or "Volume < 0.7x SMA(20)"
✅ ATR: "ATR(14) > 1.2x SMA(ATR, 20)" (volatility expansion)

Example good entry:
"Enter LONG when RSI(14) < 35 AND price closes above SMA(20) AND volume > 1.3x average"

EXIT CONDITIONS:
- Take Profit: [X% gain or X * ATR]
- Stop Loss: [Y% loss or Y * ATR]
- Optional: Exit signal (e.g., "RSI > 70")

POSITION SIZING:
Fixed or volatility-based (e.g., "Risk 1% per trade based on ATR")

WHY IT WORKS:
[1-2 sentences on the behavioral/statistical edge]

═══════════════════════════════════════════════════
EXAMPLES OF GOOD STRATEGIES:
═══════════════════════════════════════════════════

Example 1: Mean Reversion Bounce
- Enter LONG when RSI(14) < 30 AND price closes above SMA(50)
- Exit when RSI > 60 or +2% gain
- Stop loss at -1.5% or price closes below SMA(50)
- Edge: Oversold bounces off longer-term support

Example 2: Volatility Breakout
- Enter LONG when price closes above Bollinger Band upper AND volume > 2x average
- Exit at +3% or when price closes back inside bands
- Stop at -2%
- Edge: High-volume breakouts tend to continue

Example 3: Trend Following
- Enter LONG when EMA(10) crosses above EMA(30) AND MACD > 0
- Exit when EMA(10) crosses below EMA(30)
- Stop at -2.5%
- Edge: Momentum persistence in crypto

═══════════════════════════════════════════════════

Now create a SIMPLE, PRACTICAL strategy following this template.
Keep it tradeable! Better simple and working than complex and broken.
"""

def generate_simple_strategy(model_name="grok"):
    """Generate one simple strategy using Grok or DeepSeek"""

    cprint(f"\n🎯 Generating simple strategy with {model_name}...", "cyan", attrs=['bold'])

    # Choose model
    if model_name.lower() == "grok":
        model = model_factory.get_model("xai", "grok-4-fast-reasoning")
    else:
        model = model_factory.get_model("deepseek", "deepseek-v4-flash")

    if not model:
        cprint(f"❌ Could not initialize {model_name} model!", "red")
        return None

    cprint("⏳ AI is creating a simple, practical strategy...", "yellow")

    # Generate strategy
    response = model.generate_response(
        system_prompt="You are a practical trading strategy designer. Create simple, testable strategies.",
        user_content=SIMPLE_STRATEGY_PROMPT,
        temperature=0.7,  # Lower temp for more practical output
        max_tokens=2000
    )

    if not response:
        cprint(f"❌ {model_name} returned no response", "red")
        return None

    # Extract content
    if hasattr(response, 'content'):
        strategy_text = response.content
    elif isinstance(response, str):
        strategy_text = response
    else:
        strategy_text = str(response)

    # Clean up thinking tags
    if "<think>" in strategy_text and "</think>" in strategy_text:
        import re
        match = re.search(r'</think>\s*(.+)', strategy_text, re.DOTALL)
        if match:
            strategy_text = match.group(1).strip()

    cprint(f"✅ Strategy generated!", "green")

    # Save to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Simple_{model_name.title()}_{timestamp}.txt"
    filepath = STRATEGIES_OUTPUT_DIR / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"# Generated by: {model_name.title()} (Simple Generator)\n")
        f.write(f"# Timestamp: {datetime.now().isoformat()}\n")
        f.write(f"# Type: Simple, Practical Strategy\n")
        f.write(f"# ═══════════════════════════════════════════════════\n\n")
        f.write(strategy_text)

    cprint(f"💾 Saved to: {filename}", "green", attrs=['bold'])

    # Show preview
    cprint(f"\n{'='*70}", "yellow")
    cprint("📋 STRATEGY PREVIEW", "yellow", attrs=['bold'])
    cprint(f"{'='*70}", "yellow")
    lines = strategy_text.split('\n')[:15]
    for line in lines:
        if "STRATEGY NAME" in line:
            cprint(line, "green", attrs=['bold'])
        elif "ENTRY" in line or "EXIT" in line:
            cprint(line, "cyan", attrs=['bold'])
        else:
            print(line)
    total_lines = len(strategy_text.split('\n'))
    if total_lines > 15:
        cprint(f"\n... ({total_lines - 15} more lines) ...", "cyan")
    cprint(f"{'='*70}\n", "yellow")

    return filepath

def main():
    """Generate simple strategies"""
    import argparse

    parser = argparse.ArgumentParser(description="Simple Strategy Generator")
    parser.add_argument('--num', type=int, default=3, help='Number of strategies (default: 3)')
    parser.add_argument('--model', type=str, default='both', choices=['grok', 'deepseek', 'both'],
                       help='Which model to use (default: both)')

    args = parser.parse_args()

    cprint("\n" + "="*70, "cyan", attrs=['bold'])
    cprint("🌙 TradeHive's SIMPLE Strategy Generator 🚀", "cyan", attrs=['bold'])
    cprint("="*70 + "\n", "cyan", attrs=['bold'])

    cprint("📋 Focus: PRACTICAL, TESTABLE strategies that ACTUALLY WORK", "yellow")
    cprint("🎯 No pairs, no time logic, just simple indicators\n", "magenta")

    strategies_generated = 0

    for i in range(args.num):
        # Alternate between models if "both"
        if args.model == 'both':
            model_name = 'grok' if i % 2 == 0 else 'deepseek'
        else:
            model_name = args.model

        cprint(f"\n{'#'*70}", "white", attrs=['bold'])
        cprint(f"# STRATEGY {i+1}/{args.num} - Using {model_name.title()}", "white", attrs=['bold'])
        cprint(f"{'#'*70}\n", "white", attrs=['bold'])

        filepath = generate_simple_strategy(model_name)

        if filepath:
            strategies_generated += 1

        if i < args.num - 1:
            cprint("\n⏳ Cooling down for 2 seconds...", "cyan")
            import time
            time.sleep(2)

    cprint(f"\n{'='*70}", "green", attrs=['bold'])
    cprint(f"✅ Generated {strategies_generated}/{args.num} simple strategies!", "green", attrs=['bold'])
    cprint(f"📂 Location: {STRATEGIES_OUTPUT_DIR}", "cyan")
    cprint(f"\n🚀 Run RBI Agent to backtest: python src/agents/rbi_agent_pp_multi.py", "magenta", attrs=['bold'])
    cprint(f"{'='*70}\n", "green", attrs=['bold'])

if __name__ == "__main__":
    main()
