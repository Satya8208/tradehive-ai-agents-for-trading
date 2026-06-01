"""
🌙 TradeHive's AI Backtest Runner
Runs the sophisticated RBI agent on DeepSeek and Grok strategies separately

This script:
1. Processes DeepSeek strategies using DeepSeek for code generation
2. Processes Grok strategies using Grok for code generation
3. Saves results separately for comparison
4. Uses the existing rbi_agent_pp_multi.py infrastructure
"""

import sys
from pathlib import Path
import subprocess
import time
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

# Paths
RBI_AGENT = PROJECT_ROOT / "src/agents/rbi_agent_pp_multi.py"
DATA_DIR = PROJECT_ROOT / "src/data/rbi_pp_multi"
DEEPSEEK_IDEAS = DATA_DIR / "deepseek_ideas.txt"
GROK_IDEAS = DATA_DIR / "grok_ideas.txt"
RESULTS_DIR = DATA_DIR / "ai_comparison_results"

# Create results directory
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

def count_strategies(ideas_file):
    """Count strategies in a file"""
    if not ideas_file.exists():
        return 0

    with open(ideas_file, 'r', encoding='utf-8') as f:
        content = f.read()
        # Count strategy markers (lines starting with # but not comments)
        return content.count('# Generated:')

def run_backtests(ideas_file, ai_name, use_ai_for_coding):
    """Run RBI agent on a specific ideas file"""

    print("\n" + "="*60)
    print(f"🚀 BACKTESTING {ai_name.upper()} STRATEGIES")
    print("="*60)

    strategy_count = count_strategies(ideas_file)
    print(f"\n📊 Found {strategy_count} strategies from {ai_name}")

    if strategy_count == 0:
        print(f"⚠️ No strategies to test for {ai_name}")
        return

    print(f"\n⏳ This will take approximately {strategy_count * 5} minutes...")
    print(f"💡 Using {use_ai_for_coding} for code generation")
    print(f"🎯 Target: 50% return | Save threshold: 1%")
    print("\nStarting in 3 seconds...")
    time.sleep(3)

    # Temporarily copy ideas to main ideas.txt for RBI agent
    main_ideas = DATA_DIR / "ideas.txt"
    backup_ideas = DATA_DIR / "ideas_backup.txt"

    # Backup existing ideas.txt if it exists
    if main_ideas.exists():
        import shutil
        shutil.copy(main_ideas, backup_ideas)
        print(f"📦 Backed up existing ideas.txt")

    # Copy AI-specific ideas to main ideas.txt
    import shutil
    shutil.copy(ideas_file, main_ideas)
    print(f"✅ Loaded {ai_name} strategies into RBI agent")

    # Run RBI agent
    print(f"\n🤖 Starting RBI agent with {ai_name} strategies...\n")

    try:
        # Note: RBI agent configuration should be set to use the appropriate AI model
        # You'll need to manually configure this in rbi_agent_pp_multi.py:
        # - For DeepSeek strategies: Set RESEARCH_CONFIG, BACKTEST_CONFIG to use 'deepseek'
        # - For Grok strategies: Set them to use 'xai'

        result = subprocess.run(
            [sys.executable, str(RBI_AGENT)],
            cwd=str(PROJECT_ROOT),
            capture_output=False,  # Show output in real-time
            text=True
        )

        if result.returncode == 0:
            print(f"\n✅ {ai_name} backtests completed successfully!")
        else:
            print(f"\n⚠️ {ai_name} backtests completed with errors")

    except KeyboardInterrupt:
        print(f"\n⚠️ Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error running backtests: {str(e)}")

    # Restore original ideas.txt
    if backup_ideas.exists():
        shutil.copy(backup_ideas, main_ideas)
        backup_ideas.unlink()
        print(f"📦 Restored original ideas.txt")

    # Move results to AI-specific folder
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ai_results_dir = RESULTS_DIR / f"{ai_name}_{timestamp}"
    ai_results_dir.mkdir(parents=True, exist_ok=True)

    # Copy backtest stats
    stats_file = DATA_DIR / "backtest_stats.csv"
    if stats_file.exists():
        shutil.copy(stats_file, ai_results_dir / "backtest_stats.csv")
        print(f"📊 Results saved to: {ai_results_dir}")

def show_menu():
    """Display main menu"""
    print("\n" + "="*60)
    print("🌙 TRADEHIVE'S AI BACKTEST RUNNER")
    print("="*60)

    ds_count = count_strategies(DEEPSEEK_IDEAS)
    grok_count = count_strategies(GROK_IDEAS)

    print(f"\n📊 Strategy Counts:")
    print(f"   💎 DeepSeek: {ds_count} strategies")
    print(f"   ⚡ Grok: {grok_count} strategies")
    print(f"   📈 Total: {ds_count + grok_count} strategies")

    print("\n" + "="*60)
    print("OPTIONS:")
    print("="*60)
    print("\n1. Backtest DeepSeek strategies")
    print("2. Backtest Grok strategies")
    print("3. Backtest BOTH (sequential)")
    print("4. View results")
    print("5. Configure AI models")
    print("6. Exit")
    print("\n" + "="*60)

def view_results():
    """Show comparison of results"""
    print("\n" + "="*60)
    print("📊 BACKTEST RESULTS COMPARISON")
    print("="*60)

    # Find latest results for each AI
    ds_results = sorted(RESULTS_DIR.glob("deepseek_*/backtest_stats.csv"))
    grok_results = sorted(RESULTS_DIR.glob("grok_*/backtest_stats.csv"))

    if not ds_results and not grok_results:
        print("\n⚠️ No results found. Run backtests first.")
        return

    print("\n💎 DeepSeek Results:")
    if ds_results:
        latest_ds = ds_results[-1]
        print(f"   📁 {latest_ds.parent.name}")
        show_stats_summary(latest_ds)
    else:
        print("   ⚠️ No results yet")

    print("\n⚡ Grok Results:")
    if grok_results:
        latest_grok = grok_results[-1]
        print(f"   📁 {latest_grok.parent.name}")
        show_stats_summary(latest_grok)
    else:
        print("   ⚠️ No results yet")

def show_stats_summary(csv_file):
    """Show summary statistics from CSV"""
    try:
        import pandas as pd
        df = pd.read_csv(csv_file)

        if len(df) == 0:
            print("   ⚠️ No successful backtests")
            return

        print(f"   ✅ Strategies tested: {len(df)}")
        print(f"   📈 Average return: {df['Return %'].mean():.2f}%")
        print(f"   🎯 Best return: {df['Return %'].max():.2f}%")
        print(f"   📉 Worst return: {df['Return %'].min():.2f}%")
        print(f"   💎 Average Sharpe: {df['Sharpe Ratio'].mean():.2f}")

        profitable = len(df[df['Return %'] > 0])
        print(f"   ✨ Profitable: {profitable}/{len(df)} ({profitable/len(df)*100:.1f}%)")

    except Exception as e:
        print(f"   ❌ Error reading results: {str(e)}")

def configure_models():
    """Show instructions for configuring AI models"""
    print("\n" + "="*60)
    print("⚙️ AI MODEL CONFIGURATION")
    print("="*60)

    print("\n📝 TO USE DIFFERENT AIS FOR BACKTESTING:")
    print("\nEdit: src/agents/rbi_agent_pp_multi.py")
    print("\nFind lines ~136-163 and modify:")
    print("""
For DeepSeek strategies, set:
    RESEARCH_CONFIG = {'type': 'deepseek', 'name': 'deepseek-v4-pro'}
    BACKTEST_CONFIG = {'type': 'deepseek', 'name': 'deepseek-v4-flash'}
    DEBUG_CONFIG = {'type': 'deepseek', 'name': 'deepseek-v4-flash'}

For Grok strategies, set:
    RESEARCH_CONFIG = {'type': 'xai', 'name': 'grok-4-fast-reasoning'}
    BACKTEST_CONFIG = {'type': 'xai', 'name': 'grok-4-fast-reasoning'}
    DEBUG_CONFIG = {'type': 'xai', 'name': 'grok-4-fast-reasoning'}
    """)

    print("\n💡 TIP: Change these before running each AI's backtests")
    print("Or create separate copies of rbi_agent_pp_multi.py for each AI")

def main():
    """Main entry point"""

    while True:
        show_menu()
        choice = input("\nChoice: ").strip()

        if choice == '1':
            print("\n⚠️ IMPORTANT: Make sure rbi_agent_pp_multi.py is configured to use DeepSeek")
            confirm = input("Continue? (y/n): ").strip().lower()
            if confirm == 'y':
                run_backtests(DEEPSEEK_IDEAS, "deepseek", "DeepSeek")

        elif choice == '2':
            print("\n⚠️ IMPORTANT: Make sure rbi_agent_pp_multi.py is configured to use Grok")
            confirm = input("Continue? (y/n): ").strip().lower()
            if confirm == 'y':
                run_backtests(GROK_IDEAS, "grok", "Grok")

        elif choice == '3':
            print("\n⚠️ You'll need to switch AI configuration between runs")
            print("1. First run will use current configuration for DeepSeek strategies")
            print("2. Then update configuration and run Grok strategies")
            confirm = input("Continue? (y/n): ").strip().lower()
            if confirm == 'y':
                print("\n📝 Step 1: Running DeepSeek strategies with current config...")
                run_backtests(DEEPSEEK_IDEAS, "deepseek", "Current config")

                print("\n" + "="*60)
                print("⚠️ NOW UPDATE rbi_agent_pp_multi.py TO USE GROK")
                print("="*60)
                input("\nPress Enter when ready to run Grok strategies...")

                run_backtests(GROK_IDEAS, "grok", "Current config")

        elif choice == '4':
            view_results()

        elif choice == '5':
            configure_models()

        elif choice == '6':
            print("\n👋 Goodbye!")
            break

        else:
            print("❌ Invalid choice")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user. Goodbye!")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
