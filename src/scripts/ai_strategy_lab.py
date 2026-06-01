"""
🌙 TradeHive's AI Strategy Lab
Conversational strategy development with DeepSeek and Grok

This is NOT a template generator - this is a creative strategy workshop where
AIs think deeply, explain their reasoning, and compete to find alpha.
"""

import sys
from pathlib import Path
import json
from datetime import datetime
import os

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.models.model_factory import ModelFactory

# Configuration
DATA_DIR = PROJECT_ROOT / "src/data/rbi_pp_multi"
CONVERSATIONS_DIR = DATA_DIR / "strategy_conversations"
STRATEGY_DOCS_DIR = DATA_DIR / "strategy_docs"
AI_LAB_STRATEGIES_DIR = DATA_DIR / "ai_lab_strategies"  # NEW: Individual strategy files for RBI agent
DEEPSEEK_IDEAS = DATA_DIR / "deepseek_ideas.txt"
GROK_IDEAS = DATA_DIR / "grok_ideas.txt"

# Create directories
CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
STRATEGY_DOCS_DIR.mkdir(parents=True, exist_ok=True)
AI_LAB_STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)  # NEW: Create ai_lab_strategies folder

# AI Configuration
DEEPSEEK_MODEL = "deepseek-v4-pro"  # Uses chain-of-thought
GROK_MODEL = "grok-4-fast-reasoning"   # Fast reasoning mode

# System prompts - TWO MODES

# ALPHA MODE: For creative research and novel ideas
MISSION_BRIEF_ALPHA = """You are an elite quantitative trader competing to find alpha in crypto markets.

🎯 YOUR MISSION: Generate creative, non-obvious trading strategies that can generate consistent returns.

We're NOT looking for textbook strategies. We want YOUR unique insights that others might miss.

📊 EVALUATION CRITERIA:
- Profitability across multiple market conditions
- Robustness (works on different assets/timeframes)
- Originality (not just "RSI < 30, buy")
- Risk-adjusted returns (Sharpe ratio >1.0)
- Practical edge (exploits real market inefficiencies)

💡 CRITICAL REQUIREMENTS:
1. Explain WHY you think this strategy will generate alpha
2. What market inefficiency does it exploit?
3. Why haven't others exploited this already?
4. What could make this strategy stop working?

🚨 CRITICAL BALANCE - Creativity WITH Tradeability:
- Be creative and novel, BUT strategies MUST generate 10+ trades on 2 years of data
- Maximum 3-4 indicators (not 6+)
- Each condition should trigger at least 20% of the time independently
- Complexity is only valuable if the strategy still TRADES

Examples of GOOD creative strategies:
- "Combine RSI divergence with volume spike detection" (2 concepts, will trade)
- "Mean reversion to VWAP with volatility filter" (3 indicators, will trade)
- "Breakout with order flow imbalance" (creative concept, simple execution)

Examples of BAD creative strategies:
- "5 indicators must align perfectly" (will never trigger)
- "Multi-timeframe with regime detection and microstructure" (too complex)
- "Exotic indicator combinations with tight thresholds" (won't trade)

🚀 Be creative. Think outside the box. But keep it tradeable.

The user will engage in conversation with you. Think deeply, reason through your ideas,
and be ready to defend your hypotheses."""

# PRACTICAL MODE: For backtestable, tradeable strategies
MISSION_BRIEF_PRACTICAL = """You are a professional algorithmic trader creating backtestable trading strategies.

🎯 YOUR MISSION: Generate SIMPLE, ROBUST strategies that will actually TRADE and can be backtested immediately.

🚨 CRITICAL: Your strategy MUST generate trades. A strategy that never triggers is worthless.

📊 EVALUATION CRITERIA:
- TRADES FREQUENTLY (10+ trades on 2 years of data)
- Simple logic (2-3 indicators maximum)
- Clear entry/exit conditions
- Proven concepts that work in real markets
- Easy to implement in code

💡 REQUIREMENTS:
1. Keep it SIMPLE - fewer conditions = more trades
2. Use battle-tested indicators (RSI, MA, MACD, Bollinger Bands)
3. Specify EXACT parameter values (not ranges)
4. Make conditions LOOSE enough to trigger regularly
5. Focus on robustness over alpha

🎯 GOAL: Create a strategy that will actually execute trades when backtested.

Examples of GOOD strategies:
- "Buy when 20 EMA crosses above 50 EMA with volume > average"
- "Buy when RSI < 30 and price > 200 SMA, exit when RSI > 70"
- "Buy on breakout above 20-day high with volume confirmation"

Examples of BAD strategies:
- "Buy when 5 indicators align perfectly" (will never trigger)
- "Complex multi-timeframe analysis" (too complicated)
- "Exotic indicators combinations" (won't trade)

Keep it simple. Make it trade."""

# SCALPING MODE: For high-frequency 1m scalping strategies
MISSION_BRIEF_SCALPING = """You are a professional scalper creating HIGH-FREQUENCY trading strategies.

🎯 YOUR MISSION: Generate scalping strategies that execute 50-200+ trades with small, consistent profits.

⚡ SCALPING CHARACTERISTICS:
- VERY short hold time (1-10 bars, typically 1-10 minutes on 1m chart)
- Small profit targets (0.5-2% per trade)
- Tight stop losses (0.3-1% maximum)
- High frequency (50-200+ trades expected on 30 days 1m data)
- Quick entries and exits

📊 EVALUATION CRITERIA:
- Trade frequency (more is better for scalping)
- Win rate (60%+ preferred due to tight targets)
- Risk/reward ratio (1:1.5 to 1:3)
- Low drawdown (no big losses)

💡 REQUIREMENTS:
1. Use FAST indicators (EMA not SMA, short periods like 5, 10, 20)
2. Maximum 2-3 indicators (speed is critical)
3. Clear entry/exit rules with EXACT values
4. Position sizing: 5-10% of capital per trade

🚀 SCALPING CONCEPTS THAT WORK:
- Bollinger Band bounces (quick mean reversion)
- EMA crossovers on 1m (5 EMA × 10 EMA)
- RSI extremes with quick exits (RSI < 20 buy, exit at RSI 50)
- Volume spikes with momentum
- Support/resistance scalps
- VWAP touches

⚠️ AVOID:
- Long-term indicators (200 EMA, daily pivots)
- Wide stops (defeats scalping purpose)
- Complex multi-timeframe analysis (too slow)

Keep it FAST. Keep it SIMPLE. High frequency is the goal."""

MISSION_BRIEF = MISSION_BRIEF_PRACTICAL  # Default to practical mode

STRATEGY_TEMPLATE_ALPHA = """When presenting a strategy, structure your response as:

1. **STRATEGY NAME**: Give it a creative, memorable name
2. **CORE INSIGHT**: What's the key observation/pattern you noticed?
3. **ALPHA HYPOTHESIS**: What market inefficiency does this exploit?
4. **DETAILED LOGIC**:
   - Entry conditions (with reasoning for each)
   - Exit conditions (with reasoning)
   - Position sizing approach
5. **WHY THIS WORKS**: Your reasoning for why this generates returns
6. **WHY IT'S NOT OBVIOUS**: Why others haven't exploited this
7. **FAILURE MODES**: What conditions would make this stop working
8. **EXPECTED CHARACTERISTICS**:
   - Expected win rate
   - Expected returns
   - Best market conditions
   - 🎯 MANDATORY: Expected trade frequency (e.g., "15-40 trades on 2 years BTC 15m data")
9. **BACKTESTING NOTES**: What to look for when testing

Be thorough but conversational. Think out loud. Show your reasoning process."""

STRATEGY_TEMPLATE_PRACTICAL = """When presenting a strategy, be CONCISE and SPECIFIC:

1. **STRATEGY NAME**: Short, descriptive name
2. **ENTRY RULES**: Exact conditions (with specific parameter values)
   - Example: "Buy when RSI(14) < 30 AND price > SMA(200)"
   - NOT: "Buy when momentum is oversold in uptrend"
3. **EXIT RULES**: Exact conditions
   - Example: "Exit when RSI(14) > 70 OR 15 bars passed OR 3% stop loss hit"
   - NOT: "Exit when momentum reverses"
4. **POSITION SIZING**: Specific rule
   - Example: "10% of capital per trade" or "Risk 1% per trade"
5. **EXPECTED TRADES**: Estimate (e.g., "20-50 trades on 2 years BTC data")

Keep response SHORT (10-15 lines max). Be direct. Use exact numbers. No long explanations."""

STRATEGY_TEMPLATE_SCALPING = """Present scalping strategy VERY CONCISELY:

1. **STRATEGY NAME**: Short, action-oriented
2. **ENTRY**: Exact conditions (use FAST indicators: 5/10/20 periods)
   - Example: "Buy when price touches lower BB(20,2) AND RSI(14) < 30"
3. **EXIT**: Two rules (profit target + stop loss + time limit)
   - Example: "Exit at 1.5% profit OR 0.5% stop loss OR after 10 bars"
4. **POSITION**: 5-10% of capital per trade
5. **EXPECTED**: High frequency (e.g., "100-200 trades on 30 days 1m BTC data")

Keep under 10 lines. Ultra-concise. Scalpers move fast."""

STRATEGY_TEMPLATE = STRATEGY_TEMPLATE_PRACTICAL  # Default to practical mode


class AIStrategyLab:
    def __init__(self):
        """Initialize the AI Strategy Lab"""
        self.model_factory = ModelFactory()
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.conversation_history = {
            'deepseek': [],
            'grok': []
        }

        print("\n" + "="*60)
        print("🌙 TRADEHIVE'S AI STRATEGY LAB")
        print("="*60)
        print("\n🤖 Initializing AI strategists...")

        # Initialize models
        self.deepseek = self.model_factory.get_model('deepseek', DEEPSEEK_MODEL)
        self.grok = self.model_factory.get_model('xai', GROK_MODEL)

        print("✅ DeepSeek V4 Pro ready")
        print("✅ Grok-4 Fast Reasoning ready")
        print("\n" + "="*60 + "\n")

    def get_next_strategy_number(self, ai_name):
        """Get the next available strategy number for an AI"""
        prefix = f"{ai_name}_strategy_"
        existing_files = list(AI_LAB_STRATEGIES_DIR.glob(f"{prefix}*.txt"))
        if not existing_files:
            return 1

        # Extract numbers from existing files
        numbers = []
        for file in existing_files:
            try:
                num_str = file.stem.replace(prefix, "")
                numbers.append(int(num_str))
            except ValueError:
                continue

        return max(numbers) + 1 if numbers else 1

    def chat_with_ai(self, ai_name, user_message, include_mission=True):
        """Have a conversation with an AI"""
        model = self.deepseek if ai_name == 'deepseek' else self.grok
        history = self.conversation_history[ai_name]

        # Build conversation context
        if include_mission and not history:
            system_prompt = MISSION_BRIEF + "\n\n" + STRATEGY_TEMPLATE
        else:
            system_prompt = MISSION_BRIEF

        # Add conversation history
        conversation_context = ""
        for msg in history[-3:]:  # Last 3 exchanges for context
            conversation_context += f"\nUser: {msg['user']}\nAI: {msg['ai']}\n"

        full_prompt = conversation_context + f"\nUser: {user_message}\n\nAI:"

        print(f"\n🤔 {ai_name.title()} is thinking...\n")

        # Get response
        try:
            # Temperature based on mode
            if MISSION_BRIEF == MISSION_BRIEF_PRACTICAL:
                temp = 0.3  # Focused
            elif MISSION_BRIEF == MISSION_BRIEF_SCALPING:
                temp = 0.4  # Focused but adaptive for scalping
            else:  # Alpha
                temp = 0.6  # Creative but constrained

            response_obj = model.generate_response(
                system_prompt=system_prompt,
                user_content=full_prompt,
                temperature=temp,
                max_tokens=2000
            )

            # Extract content from ModelResponse object
            response = response_obj.content if hasattr(response_obj, 'content') else str(response_obj)

            # Store in history
            history.append({
                'user': user_message,
                'ai': response,
                'timestamp': datetime.now().isoformat()
            })

            return response

        except Exception as e:
            return f"Error communicating with {ai_name}: {str(e)}"

    def creative_mode(self):
        """Free-form conversation mode"""
        print("\n🎨 CREATIVE MODE")
        print("="*60)
        print("Have open-ended conversations with DeepSeek and Grok.")
        print("Push them to think creatively and explain their reasoning.")
        print("\n📝 MULTI-LINE INPUT:")
        print("  - Paste or type your prompt (can be multiple lines)")
        print("  - Press ENTER on an empty line when done")
        print("\nCommands:")
        print("  'switch' - Switch between DeepSeek and Grok")
        print("  'both' - Ask both AIs the same question")
        print("  'save' - Save current strategy")
        print("  'exit' - Exit creative mode")
        print("="*60 + "\n")

        current_ai = 'deepseek'

        while True:
            ai_display = f"💎 DeepSeek" if current_ai == 'deepseek' else "⚡ Grok"

            # Multi-line input: collect lines until double empty line
            print(f"\n[{ai_display}] You (press ENTER twice when done):")
            lines = []
            empty_count = 0
            while True:
                line = input()
                if line.strip() == "":
                    empty_count += 1
                    if empty_count >= 2:  # Two consecutive empty lines = done
                        break
                    lines.append(line)  # Keep the blank line
                else:
                    empty_count = 0  # Reset counter
                    lines.append(line)

            user_input = "\n".join(lines).strip()

            if not user_input:
                continue

            # Handle commands (check exact match first, including '/save' variant)
            cmd = user_input.lower().strip()

            if cmd == 'exit' or cmd == '/exit':
                self.save_session()
                break

            elif cmd == 'switch' or cmd == '/switch':
                current_ai = 'grok' if current_ai == 'deepseek' else 'deepseek'
                print(f"\n✅ Switched to {current_ai.title()}")
                continue

            elif cmd == 'both' or cmd == '/both':
                print("\n📝 Question for both AIs (press ENTER twice when done):")
                both_lines = []
                empty_count = 0
                while True:
                    line = input()
                    if line.strip() == "":
                        empty_count += 1
                        if empty_count >= 2:  # Two consecutive empty lines = done
                            break
                        both_lines.append(line)  # Keep the blank line
                    else:
                        empty_count = 0  # Reset counter
                        both_lines.append(line)
                question = "\n".join(both_lines).strip()

                if question:
                    print("\n" + "="*60)
                    print("💎 DEEPSEEK'S RESPONSE:")
                    print("="*60)
                    ds_response = self.chat_with_ai('deepseek', question)
                    print(ds_response)

                    print("\n" + "="*60)
                    print("⚡ GROK'S RESPONSE:")
                    print("="*60)
                    grok_response = self.chat_with_ai('grok', question)
                    print(grok_response)
                continue

            elif cmd == 'save' or cmd == '/save':
                print(f"\n💾 Saving {current_ai} strategy...")
                self.save_current_strategy(current_ai)
                continue

            # Normal conversation
            response = self.chat_with_ai(current_ai, user_input)
            print(f"\n{ai_display}: {response}")

    def save_current_strategy(self, ai_name):
        """Save the current strategy discussion"""
        history = self.conversation_history[ai_name]

        if not history:
            print("\n⚠️ No conversation to save")
            return

        # Auto-generate strategy name using next number
        strategy_num = self.get_next_strategy_number(ai_name)
        strategy_name = f"{ai_name.title()} Strategy {strategy_num}"

        print(f"\n💾 Auto-saving as: {strategy_name}")

        # Clean strategy name
        clean_name = strategy_name.replace(" ", "_")

        # Save full conversation
        conv_file = CONVERSATIONS_DIR / f"{clean_name}_{ai_name}_session.md"
        with open(conv_file, 'w', encoding='utf-8') as f:
            f.write(f"# {strategy_name}\n")
            f.write(f"**AI**: {ai_name.title()}\n")
            f.write(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("---\n\n")

            for msg in history:
                f.write(f"## User\n{msg['user']}\n\n")
                f.write(f"## {ai_name.title()}\n{msg['ai']}\n\n")
                f.write("---\n\n")

        # Extract strategy description (last AI response)
        strategy_desc = history[-1]['ai']

        # 🌙 NEW: Save as individual file for RBI agent to read (strategy_num already calculated above)
        individual_file = AI_LAB_STRATEGIES_DIR / f"{ai_name}_strategy_{strategy_num:03d}.txt"
        with open(individual_file, 'w', encoding='utf-8') as f:
            f.write(f"# {strategy_name}\n")
            f.write(f"# AI Model: {ai_name.title()}\n")
            f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Strategy Number: {strategy_num}\n\n")
            f.write(strategy_desc)  # Full strategy description with all details

        # Also append to ideas file (FULL strategy, not truncated) - for backward compatibility
        ideas_file = DEEPSEEK_IDEAS if ai_name == 'deepseek' else GROK_IDEAS
        with open(ideas_file, 'a', encoding='utf-8') as f:
            f.write(f"\n# {strategy_name}\n")
            f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{strategy_desc}\n\n")  # Full strategy description

        # Save detailed strategy document
        doc_file = STRATEGY_DOCS_DIR / f"{clean_name}.md"
        with open(doc_file, 'w', encoding='utf-8') as f:
            f.write(f"# {strategy_name}\n\n")
            f.write(f"**Created by**: {ai_name.title()}\n")
            f.write(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("## Strategy Details\n\n")
            f.write(strategy_desc)
            f.write("\n\n## Full Conversation\n\n")
            f.write(f"See: {conv_file.name}\n")

        print(f"\n✅ Strategy saved!")
        print(f"   📄 Conversation: {conv_file}")
        print(f"   📋 Strategy doc: {doc_file}")
        print(f"   🎯 RBI backtest file: {individual_file.name}")
        print(f"   💾 Added to: {ideas_file.name}")

    def compare_mode(self):
        """Have both AIs tackle the same problem"""
        print("\n⚔️ COMPARE MODE")
        print("="*60)
        print("Challenge both AIs with the same question.")
        print("See how their approaches differ.")
        print("="*60 + "\n")

        # Multi-line input support - wait for double ENTER
        print("🎯 Challenge for both AIs (press ENTER twice when done):")
        lines = []
        empty_count = 0
        while True:
            line = input()
            if line.strip() == "":
                empty_count += 1
                if empty_count >= 2:  # Two consecutive empty lines = done
                    break
                lines.append(line)  # Keep the blank line in output
            else:
                empty_count = 0  # Reset counter if we get content
                lines.append(line)

        challenge = "\n".join(lines).strip()

        if not challenge:
            print("❌ No challenge provided")
            return

        print("\n" + "="*60)
        print("💎 DEEPSEEK'S APPROACH:")
        print("="*60)
        ds_response = self.chat_with_ai('deepseek', challenge)
        print(ds_response)

        print("\n" + "="*60)
        print("⚡ GROK'S APPROACH:")
        print("="*60)
        grok_response = self.chat_with_ai('grok', challenge)
        print(grok_response)

        # Auto-save both strategies
        print("\n💾 Auto-saving both strategies...")

        # Generate base name from challenge (first few words)
        words = challenge.split()[:3]
        base_name = "_".join(words).replace(":", "").replace("?", "").replace("!", "")
        if len(base_name) > 30:
            base_name = base_name[:30]

        self.save_comparison(base_name, challenge, ds_response, grok_response)

    def save_comparison(self, base_name, challenge, ds_response, grok_response):
        """Save a head-to-head comparison"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Save comparison document
        comp_file = STRATEGY_DOCS_DIR / f"{base_name}_comparison_{timestamp}.md"
        with open(comp_file, 'w', encoding='utf-8') as f:
            f.write(f"# {base_name} - AI Comparison\n\n")
            f.write(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"## Challenge\n\n{challenge}\n\n")
            f.write("---\n\n")
            f.write("## 💎 DeepSeek's Approach\n\n")
            f.write(ds_response)
            f.write("\n\n---\n\n")
            f.write("## ⚡ Grok's Approach\n\n")
            f.write(grok_response)

        # 🌙 NEW: Save individual files for RBI agent
        saved_files = []
        for ai_short_name, response, ai_display_name in [
            ('deepseek', ds_response, 'DeepSeek'),
            ('grok', grok_response, 'Grok')
        ]:
            strategy_num = self.get_next_strategy_number(ai_short_name)
            individual_file = AI_LAB_STRATEGIES_DIR / f"{ai_short_name}_strategy_{strategy_num:03d}.txt"
            with open(individual_file, 'w', encoding='utf-8') as f:
                f.write(f"# {base_name} ({ai_display_name})\n")
                f.write(f"# AI Model: {ai_display_name}\n")
                f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Strategy Number: {strategy_num}\n")
                f.write(f"# Challenge: {challenge}\n\n")
                f.write(response)  # Full strategy description
            saved_files.append(individual_file.name)

        # Add to both ideas files (FULL responses, not truncated) - for backward compatibility
        for ideas_file, response, ai_name in [
            (DEEPSEEK_IDEAS, ds_response, 'DeepSeek'),
            (GROK_IDEAS, grok_response, 'Grok')
        ]:
            with open(ideas_file, 'a', encoding='utf-8') as f:
                f.write(f"\n# {base_name} ({ai_name})\n")
                f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Challenge: {challenge}\n")
                f.write(f"{response}\n\n")  # Full response, not truncated

        print(f"\n✅ Comparison saved: {comp_file}")
        print(f"   🎯 RBI backtest files: {', '.join(saved_files)}")

    def save_session(self):
        """Save the entire session"""
        session_file = CONVERSATIONS_DIR / f"session_{self.session_id}.json"

        session_data = {
            'session_id': self.session_id,
            'timestamp': datetime.now().isoformat(),
            'deepseek_exchanges': len(self.conversation_history['deepseek']),
            'grok_exchanges': len(self.conversation_history['grok']),
            'conversations': self.conversation_history
        }

        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2)

        print(f"\n💾 Session saved: {session_file}")

    def run(self):
        """Main entry point"""
        # First, select mode
        global MISSION_BRIEF, STRATEGY_TEMPLATE

        print("\n" + "="*60)
        print("🎯 SELECT MODE")
        print("="*60)
        print("\n1. 🎯 PRACTICAL MODE (Swing/position trading, 15m-4h data)")
        print("   - Simple, tradeable strategies")
        print("   - 2-3 indicators, proven concepts")
        print("   - For RBI agent backtesting")
        print("   - Temperature: 0.3 (focused)")
        print("\n2. 🚀 ALPHA MODE (Creative strategies, any timeframe)")
        print("   - Novel, creative strategies")
        print("   - 2-4 indicators maximum")
        print("   - MUST still generate 10+ trades")
        print("   - Temperature: 0.6 (balanced)")
        print("\n3. ⚡ SCALPING MODE (High-frequency, 1m data)")
        print("   - 50-200+ trades expected")
        print("   - 1-3 indicators, very fast")
        print("   - Small profits (0.5-2%), tight stops")
        print("   - Temperature: 0.4 (focused+adaptive)")
        print("\n" + "="*60)

        mode_choice = input("\nMode: ").strip()

        if mode_choice == '3':
            MISSION_BRIEF = MISSION_BRIEF_SCALPING
            STRATEGY_TEMPLATE = STRATEGY_TEMPLATE_SCALPING
            print("\n✅ SCALPING MODE activated - High frequency!")
            print("⚠️  NOTE: Scalping strategies saved to separate folder")
            print("   Use dedicated scalping backtest workflow (not RBI agent)\n")
        elif mode_choice == '2':
            MISSION_BRIEF = MISSION_BRIEF_ALPHA
            STRATEGY_TEMPLATE = STRATEGY_TEMPLATE_ALPHA
            print("\n✅ ALPHA MODE activated - Get creative!\n")
        else:
            MISSION_BRIEF = MISSION_BRIEF_PRACTICAL
            STRATEGY_TEMPLATE = STRATEGY_TEMPLATE_PRACTICAL
            print("\n✅ PRACTICAL MODE activated - Focus on trades!\n")

        while True:
            print("\n" + "="*60)
            print("🎨 AI STRATEGY LAB - MAIN MENU")
            print("="*60)
            print("\n1. Creative Mode - Free conversation with AIs")
            print("2. Compare Mode - Challenge both AIs")
            print("3. Quick Strategy - Get one strategy idea")
            print("4. View Session Stats")
            print("5. Exit")
            print("\n" + "="*60)

            choice = input("\nChoice: ").strip()

            if choice == '1':
                self.creative_mode()
            elif choice == '2':
                self.compare_mode()
            elif choice == '3':
                self.quick_strategy()
            elif choice == '4':
                self.show_stats()
            elif choice == '5':
                self.save_session()
                print("\n👋 Thanks for using AI Strategy Lab!")
                break
            else:
                print("❌ Invalid choice")

    def quick_strategy(self):
        """Generate one strategy quickly"""
        ai_choice = input("\n🤖 Which AI? (deepseek/grok): ").strip().lower()
        if ai_choice not in ['deepseek', 'grok']:
            print("❌ Invalid choice")
            return

        concept = input("\n💡 Strategy concept: ").strip()
        if not concept:
            print("❌ No concept provided")
            return

        prompt = f"Create a creative trading strategy based on: {concept}\n\n{STRATEGY_TEMPLATE}"

        response = self.chat_with_ai(ai_choice, prompt)
        print(f"\n{'='*60}")
        print(f"{'💎 DEEPSEEK' if ai_choice == 'deepseek' else '⚡ GROK'} STRATEGY:")
        print("="*60)
        print(response)

        save = input("\n💾 Save this strategy? (y/n): ").strip().lower()
        if save == 'y':
            self.save_current_strategy(ai_choice)

    def show_stats(self):
        """Show session statistics"""
        print("\n" + "="*60)
        print("📊 SESSION STATISTICS")
        print("="*60)
        print(f"\nSession ID: {self.session_id}")
        print(f"DeepSeek exchanges: {len(self.conversation_history['deepseek'])}")
        print(f"Grok exchanges: {len(self.conversation_history['grok'])}")

        # Count saved strategies
        ds_count = 0
        grok_count = 0

        if DEEPSEEK_IDEAS.exists():
            with open(DEEPSEEK_IDEAS, 'r') as f:
                ds_count = f.read().count('# Generated:')

        if GROK_IDEAS.exists():
            with open(GROK_IDEAS, 'r') as f:
                grok_count = f.read().count('# Generated:')

        print(f"\nTotal strategies saved:")
        print(f"  DeepSeek: {ds_count}")
        print(f"  Grok: {grok_count}")
        print(f"  Total: {ds_count + grok_count}")


if __name__ == "__main__":
    try:
        lab = AIStrategyLab()
        lab.run()
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user. Goodbye!")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
