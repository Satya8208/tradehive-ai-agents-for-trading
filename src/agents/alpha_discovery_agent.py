"""
🌙 TradeHive's Alpha Discovery Agent 🚀
Built with love by TradeHive 🚀

This agent uses Grok and DeepSeek to THINK DEEPLY and discover novel trading strategies.
Not a template generator - a true research and discovery system!

PHILOSOPHY:
- Grok thinks outside the box and finds unconventional patterns
- DeepSeek reasons deeply about market inefficiencies
- Both explore ideas humans wouldn't naturally consider
- Focus on DISCOVERING alpha, not recycling known strategies

HOW IT WORKS:
1. Each model starts with a research prompt about market inefficiencies
2. Models explore different angles (technical, behavioral, statistical, etc.)
3. They reason through what MIGHT work and WHY
4. Generate specific, testable hypotheses
5. Output detailed strategy descriptions for backtesting

OUTPUT:
- Saves creative strategies to ai_lab_strategies/ folder
- RBI agent automatically picks them up and backtests
- Only novel, well-reasoned ideas make it through

Created with ❤️ by TradeHive
"""

import os
import sys
import time
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

# Model configurations
GROK_CONFIG = {
    "type": "xai",
    "name": "grok-4-fast-reasoning"  # Grok's reasoning model
}

DEEPSEEK_CONFIG = {
    "type": "deepseek",
    "name": "deepseek-v4-pro"  # DeepSeek's reasoning model
}

# Research themes to explore (rotated randomly)
RESEARCH_THEMES = [
    {
        "name": "Behavioral Anomalies",
        "focus": "How do traders behave irrationally? What patterns emerge from fear, greed, FOMO, or panic that create exploitable inefficiencies?"
    },
    {
        "name": "Statistical Arbitrage",
        "focus": "What mathematical relationships exist between price, volume, volatility, and time that most traders overlook? What mean-reversion or momentum patterns are hidden in the data?"
    },
    {
        "name": "Market Microstructure",
        "focus": "How do order flow, liquidity, spreads, and market maker behavior create opportunities? What happens during transitions between market regimes?"
    },
    {
        "name": "Unconventional Indicators",
        "focus": "What non-standard measurements could predict price movement? Think beyond RSI/MACD - what about entropy, fractal dimensions, or information theory?"
    },
    {
        "name": "Time-Based Patterns",
        "focus": "How does time-of-day, day-of-week, month, or season affect markets? Are there cyclical patterns that create edge?"
    },
    {
        "name": "Volatility Dynamics",
        "focus": "How can we profit from volatility clustering, volatility mean reversion, or volatility asymmetry? What patterns exist in ATR, Bollinger Band width, or option-implied vol?"
    },
    {
        "name": "Multi-Asset Correlations",
        "focus": "What hidden relationships exist between crypto, stocks, commodities, or indices? Can we exploit correlation breakdown or convergence?"
    },
    {
        "name": "Regime Detection",
        "focus": "Can we identify market regimes (trending, ranging, volatile, calm) and trade differently in each? What signals indicate regime changes?"
    },
    {
        "name": "Contrarian Logic",
        "focus": "When does the crowd get it wrong? What overbought/oversold conditions actually lead to reversals vs continuation? When should we fade the trend?"
    },
    {
        "name": "Structural Breaks",
        "focus": "How can we detect and exploit breakouts, breakdowns, support/resistance failures, or trend changes EARLY before they're obvious?"
    }
]

# Deep thinking prompt for discovery
DISCOVERY_PROMPT_TEMPLATE = """
You are TradeHive's Alpha Discovery AI - a creative trading research system.

Your mission: DISCOVER novel, exploitable patterns in financial markets.

DO NOT generate standard strategies everyone knows (moving average crossovers, basic RSI, etc.)
DO NOT just combine common indicators in obvious ways.
DO NOT give me textbook approaches.

INSTEAD, think deeply about THIS research theme:

═══════════════════════════════════════════════════
RESEARCH THEME: {theme_name}
═══════════════════════════════════════════════════

FOCUS AREA:
{theme_focus}

═══════════════════════════════════════════════════

YOUR TASK:

1. THINK DEEPLY about this theme
   - What market inefficiencies exist here?
   - What patterns might traders miss?
   - What mathematical relationships could we exploit?
   - What behavioral biases create opportunities?

2. REASON through potential edge
   - Why would this approach work?
   - What makes it different from standard strategies?
   - What market conditions favor it?
   - What are the failure modes?

3. DESIGN a specific, PRACTICAL, testable strategy
   - Clear entry conditions (be specific about calculations)
   - Clear exit conditions (take profit, stop loss, or signals)
   - Position sizing approach
   - Risk management rules

🚨 CRITICAL REQUIREMENTS FOR BACKTESTING SUCCESS:

**Data Reality:**
- You're testing on 15-minute OHLCV crypto data (BTC, ETH, SOL)
- Crypto trades 24/7 - NO "market open/close" times
- NO time-of-day dependencies (9:30 AM, session overlaps, etc.)
- NO complex time windows or pre-positioning

**Entry Conditions Must Be:**
- Based ONLY on: price, volume, and standard indicators (RSI, MACD, ATR, SMA, EMA, Bollinger Bands)
- Simple boolean logic (2-3 conditions maximum)
- Trigger at least 10-20 times per month on typical crypto data
- NO "pre-calculate historical ATR by time slot" or similar complex logic

**Examples of GOOD entry conditions:**
✅ "Enter long when RSI < 35 AND price closes above 20-period SMA"
✅ "Enter when price breaks above Bollinger Band upper AND volume > 1.5x average"
✅ "Enter when MACD crosses above signal line AND ATR is expanding"

**Examples of BAD entry conditions (DO NOT USE):**
❌ "Enter 15 minutes before historically high-volatility time slots"
❌ "Pre-calculate mean ATR for each 15-minute interval over 30 days"
❌ "Enter only during London-NY session overlap (13:00-17:00 UTC)"
❌ "Calculate order flow imbalance with normalized toxicity metrics"

**Keep It Simple:**
- Novelty comes from COMBINING indicators in unique ways, not complex logic
- Focus on WHAT conditions to check, not WHEN or WHERE
- Make it tradeable FIRST, then optimize later

4. EXPLAIN your reasoning
   - Why this particular approach?
   - What makes it unique?
   - What evidence or logic supports it?

═══════════════════════════════════════════════════
OUTPUT FORMAT:
═══════════════════════════════════════════════════

STRATEGY NAME: [Create a unique, descriptive 2-3 word name]

CORE INSIGHT:
[The key market inefficiency or pattern you're exploiting - 2-3 sentences]

HYPOTHESIS:
[Why you believe this will generate alpha - your reasoning - 3-5 sentences]

STRATEGY LOGIC:

Entry Conditions:
[Be VERY specific - exact calculations, thresholds, confirmations]
Example: "Enter long when 20-period ATR exceeds 1.5x its 50-period moving average AND price closes above the 5-day high AND volume is 2x the 20-day average"

Exit Conditions:
[Specific profit targets, stop losses, or exit signals]

Position Sizing:
[How to size positions - fixed, volatility-based, etc.]

Risk Management:
[Stop losses, max drawdown limits, exposure limits]

UNIQUE ASPECTS:
[What makes this different from standard approaches? Why might it work?]

EXPECTED MARKET CONDITIONS:
[When this strategy should perform well vs poorly]

═══════════════════════════════════════════════════

IMPORTANT GUIDELINES:

✅ Be creative and unconventional
✅ Think about market psychology and inefficiencies
✅ Provide specific, actionable details
✅ Explain your reasoning clearly
✅ Make it testable with backtesting.py library

❌ No generic moving average crossovers
❌ No basic RSI overbought/oversold without a twist
❌ No standard textbook strategies
❌ No vague or unspecific conditions

Remember: We want to discover ALPHA - real edge that others don't have!

Think deeply. Be creative. Find something unique.

NOW: Generate your novel trading strategy for this research theme.
"""

def print_banner():
    """Print TradeHive banner"""
    banner = """
╔════════════════════════════════════════════════════════════╗
║  🌙 TradeHive's Alpha Discovery Agent 🚀                   ║
║                                                            ║
║  Using Grok + DeepSeek to discover novel trading edge    ║
║  Deep thinking → Creative exploration → Real alpha        ║
╚════════════════════════════════════════════════════════════╝
"""
    cprint(banner, "cyan", attrs=['bold'])

def get_creative_research_theme():
    """Get a random research theme for exploration"""
    import random
    return random.choice(RESEARCH_THEMES)

def discover_with_model(model_config, theme, model_name_display):
    """
    Use a model to discover novel trading strategies

    Args:
        model_config: Dict with 'type' and 'name' for model
        theme: Research theme dict
        model_name_display: Display name for logging

    Returns:
        Generated strategy text or None
    """
    try:
        cprint(f"\n{'='*70}", "cyan")
        cprint(f"🧠 {model_name_display} - DEEP THINKING MODE", "yellow", attrs=['bold'])
        cprint(f"{'='*70}", "cyan")
        cprint(f"📚 Research Theme: {theme['name']}", "magenta", attrs=['bold'])
        cprint(f"🎯 Focus: {theme['focus'][:100]}...", "cyan")

        # Get model instance
        model = model_factory.get_model(model_config["type"], model_config["name"])
        if not model:
            cprint(f"❌ Could not initialize {model_config['type']} model!", "red")
            return None

        # Generate discovery prompt
        discovery_prompt = DISCOVERY_PROMPT_TEMPLATE.format(
            theme_name=theme['name'],
            theme_focus=theme['focus']
        )

        cprint(f"\n⏳ {model_name_display} is thinking deeply...", "yellow")
        cprint("💭 Exploring market inefficiencies...", "cyan")

        start_time = time.time()

        # Generate response
        response = model.generate_response(
            system_prompt="You are a creative trading research AI focused on discovering novel alpha-generating strategies.",
            user_content=discovery_prompt,
            temperature=0.9,  # Higher temperature for creativity
            max_tokens=4000
        )

        elapsed = time.time() - start_time

        if not response:
            cprint(f"❌ {model_name_display} returned no response", "red")
            return None

        # Extract content
        if hasattr(response, 'content'):
            strategy_text = response.content
        elif isinstance(response, str):
            strategy_text = response
        else:
            strategy_text = str(response)

        # Clean up thinking tags if present
        if "<think>" in strategy_text and "</think>" in strategy_text:
            import re
            # Extract content after </think> tag
            match = re.search(r'</think>\s*(.+)', strategy_text, re.DOTALL)
            if match:
                strategy_text = match.group(1).strip()

        cprint(f"\n✅ {model_name_display} completed in {elapsed:.1f}s", "green", attrs=['bold'])
        cprint(f"📄 Generated {len(strategy_text)} characters", "cyan")

        return strategy_text

    except Exception as e:
        cprint(f"❌ Error with {model_name_display}: {str(e)}", "red")
        import traceback
        cprint(traceback.format_exc(), "red")
        return None

def save_strategy(strategy_text, model_name, theme_name):
    """
    Save strategy to file for RBI agent to process

    Args:
        strategy_text: The generated strategy
        model_name: Name of the model (for filename)
        theme_name: Research theme name (for filename)

    Returns:
        Path to saved file
    """
    try:
        # Create filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Sanitize theme name for filename
        safe_theme = theme_name.replace(" ", "_").replace("/", "-")
        filename = f"{model_name}_{safe_theme}_{timestamp}.txt"
        filepath = STRATEGIES_OUTPUT_DIR / filename

        # Save to file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Generated by: {model_name}\n")
            f.write(f"# Research Theme: {theme_name}\n")
            f.write(f"# Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"# ═══════════════════════════════════════════════════\n\n")
            f.write(strategy_text)

        cprint(f"\n💾 Saved strategy to: {filename}", "green", attrs=['bold'])
        cprint(f"📂 Location: {filepath}", "cyan")

        return filepath

    except Exception as e:
        cprint(f"❌ Error saving strategy: {str(e)}", "red")
        return None

def preview_strategy(strategy_text, max_lines=15):
    """Show preview of generated strategy"""
    cprint(f"\n{'='*70}", "yellow")
    cprint("📋 STRATEGY PREVIEW", "yellow", attrs=['bold'])
    cprint(f"{'='*70}", "yellow")

    lines = strategy_text.split('\n')
    preview_lines = lines[:max_lines]

    for line in preview_lines:
        if line.startswith("STRATEGY NAME:"):
            cprint(line, "green", attrs=['bold'])
        elif line.startswith("CORE INSIGHT:"):
            cprint(line, "cyan", attrs=['bold'])
        elif line.startswith("HYPOTHESIS:"):
            cprint(line, "magenta", attrs=['bold'])
        elif "Entry Conditions:" in line:
            cprint(line, "yellow", attrs=['bold'])
        else:
            print(line)

    if len(lines) > max_lines:
        cprint(f"\n... ({len(lines) - max_lines} more lines) ...", "cyan")

    cprint(f"{'='*70}\n", "yellow")

def run_discovery_session(num_strategies=5):
    """
    Run a discovery session to generate novel strategies

    Args:
        num_strategies: How many strategies to generate (default: 5)
    """
    print_banner()

    cprint(f"\n🎯 Discovery Session Configuration:", "cyan", attrs=['bold'])
    cprint(f"  ├─ Target strategies: {num_strategies}", "yellow")
    cprint(f"  ├─ Models: Grok + DeepSeek", "yellow")
    cprint(f"  ├─ Output: {STRATEGIES_OUTPUT_DIR}", "cyan")
    cprint(f"  └─ Mode: Deep Creative Exploration\n", "magenta")

    # Check model availability
    grok_available = model_factory.is_model_available("xai")
    deepseek_available = model_factory.is_model_available("deepseek")

    cprint("🔍 Model Availability Check:", "cyan")
    cprint(f"  ├─ Grok (xAI): {'✅ Available' if grok_available else '❌ Not available'}",
           "green" if grok_available else "red")
    cprint(f"  └─ DeepSeek: {'✅ Available' if deepseek_available else '❌ Not available'}",
           "green" if deepseek_available else "red")

    if not grok_available and not deepseek_available:
        cprint("\n❌ No models available! Check your API keys:", "red", attrs=['bold'])
        cprint("  ├─ GROK_API_KEY for Grok/xAI", "yellow")
        cprint("  └─ DEEPSEEK_KEY for DeepSeek", "yellow")
        return

    # Determine which models to use
    available_models = []
    if grok_available:
        available_models.append(("Grok", GROK_CONFIG))
    if deepseek_available:
        available_models.append(("DeepSeek", DEEPSEEK_CONFIG))

    cprint(f"\n🚀 Starting discovery with {len(available_models)} model(s)...\n", "green", attrs=['bold'])

    strategies_generated = 0

    for i in range(num_strategies):
        cprint(f"\n{'#'*70}", "white", attrs=['bold'])
        cprint(f"# DISCOVERY ITERATION {i+1}/{num_strategies}", "white", attrs=['bold'])
        cprint(f"{'#'*70}\n", "white", attrs=['bold'])

        # Get a random research theme
        theme = get_creative_research_theme()

        # Alternate between available models
        model_name, model_config = available_models[i % len(available_models)]

        # Generate strategy
        strategy_text = discover_with_model(model_config, theme, model_name)

        if strategy_text:
            # Preview the strategy
            preview_strategy(strategy_text)

            # Save the strategy
            saved_path = save_strategy(strategy_text, model_name, theme['name'])

            if saved_path:
                strategies_generated += 1
                cprint(f"✅ Strategy {strategies_generated}/{num_strategies} saved!", "green", attrs=['bold'])
        else:
            cprint(f"⚠️ Failed to generate strategy {i+1}", "yellow")

        # Small delay between iterations
        if i < num_strategies - 1:
            cprint("\n⏳ Cooling down for 2 seconds...", "cyan")
            time.sleep(2)

    # Summary
    cprint(f"\n{'='*70}", "green", attrs=['bold'])
    cprint(f"📊 DISCOVERY SESSION COMPLETE", "green", attrs=['bold'])
    cprint(f"{'='*70}", "green", attrs=['bold'])
    cprint(f"✅ Strategies generated: {strategies_generated}/{num_strategies}", "cyan")
    cprint(f"📂 Output folder: {STRATEGIES_OUTPUT_DIR}", "yellow")
    cprint(f"\n🚀 RBI Agent will automatically backtest these strategies!", "magenta", attrs=['bold'])
    cprint(f"💡 Run: python src/agents/rbi_agent_pp_multi.py\n", "cyan")

def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="TradeHive's Alpha Discovery Agent")
    parser.add_argument('--num-strategies', type=int, default=5,
                       help='Number of strategies to generate (default: 5)')
    parser.add_argument('--continuous', action='store_true',
                       help='Run continuously, generating strategies forever')
    parser.add_argument('--interval', type=int, default=300,
                       help='Seconds between continuous runs (default: 300)')

    args = parser.parse_args()

    if args.continuous:
        cprint(f"\n🔄 CONTINUOUS MODE - Generating {args.num_strategies} strategies every {args.interval}s",
               "cyan", attrs=['bold'])
        cprint("Press Ctrl+C to stop\n", "yellow")

        try:
            while True:
                run_discovery_session(args.num_strategies)
                cprint(f"\n😴 Sleeping for {args.interval} seconds...", "yellow")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            cprint("\n\n👋 Stopped by user. TradeHive out! 🌙", "cyan", attrs=['bold'])
    else:
        run_discovery_session(args.num_strategies)

if __name__ == "__main__":
    main()
