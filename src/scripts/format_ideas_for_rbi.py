"""
Format multi-line strategies from AI Strategy Lab into single-line format for RBI agent

The RBI agent reads ideas.txt line-by-line, but our AI strategies are multi-paragraph.
This script condenses each strategy into a single line (or creates separate strategy files).
"""

from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "src/data/rbi_pp_multi"

DEEPSEEK_IDEAS = DATA_DIR / "deepseek_ideas.txt"
GROK_IDEAS = DATA_DIR / "grok_ideas.txt"
OUTPUT_IDEAS = DATA_DIR / "ideas.txt"

def parse_multi_line_strategies(file_path):
    """Parse multi-line strategies into individual strategy blocks"""
    if not file_path.exists():
        return []

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split by strategy markers (lines starting with # followed by non-# text)
    strategies = []
    current_strategy = []
    strategy_name = None

    for line in content.split('\n'):
        # Check if it's a strategy name (# but not ## or #generated)
        if line.strip().startswith('# ') and not line.strip().startswith('# Generated'):
            # Save previous strategy if exists
            if current_strategy:
                strategy_text = ' '.join(current_strategy).strip()
                if strategy_text:
                    strategies.append({
                        'name': strategy_name or 'Unnamed',
                        'text': strategy_text
                    })
                current_strategy = []

            # Start new strategy
            strategy_name = line.strip()[2:].strip()  # Remove '# '

        # Skip comment lines but keep content
        elif line.strip() and not line.strip().startswith('#'):
            current_strategy.append(line.strip())

    # Don't forget the last strategy
    if current_strategy:
        strategy_text = ' '.join(current_strategy).strip()
        if strategy_text:
            strategies.append({
                'name': strategy_name or 'Unnamed',
                'text': strategy_text
            })

    return strategies

def condense_strategy(strategy_text, max_length=2000):
    """Condense a strategy to a reasonable length while keeping key info"""
    # If already short enough, return as is
    if len(strategy_text) <= max_length:
        return strategy_text

    # Try to extract key sections
    sections = []

    # Look for key phrases
    key_phrases = [
        'STRATEGY NAME',
        'CORE INSIGHT',
        'ALPHA HYPOTHESIS',
        'Entry',
        'Exit',
        'WHY THIS WORKS'
    ]

    # Extract sentences containing key phrases
    sentences = strategy_text.split('.')
    for sentence in sentences:
        for phrase in key_phrases:
            if phrase.lower() in sentence.lower():
                sections.append(sentence.strip())
                break

    # If we extracted good content, use it
    if sections:
        condensed = '. '.join(sections)
        if len(condensed) <= max_length:
            return condensed

    # Otherwise just truncate intelligently
    return strategy_text[:max_length] + '...'

def format_for_rbi():
    """Main function to format strategies for RBI agent"""
    print("\n" + "="*60)
    print("📝 FORMATTING STRATEGIES FOR RBI AGENT")
    print("="*60)

    all_strategies = []

    # Parse DeepSeek strategies
    print("\n💎 Processing DeepSeek strategies...")
    ds_strategies = parse_multi_line_strategies(DEEPSEEK_IDEAS)
    print(f"   Found {len(ds_strategies)} DeepSeek strategies")
    for strat in ds_strategies:
        strat['source'] = 'DeepSeek'
        all_strategies.append(strat)

    # Parse Grok strategies
    print("\n⚡ Processing Grok strategies...")
    grok_strategies = parse_multi_line_strategies(GROK_IDEAS)
    print(f"   Found {len(grok_strategies)} Grok strategies")
    for strat in grok_strategies:
        strat['source'] = 'Grok'
        all_strategies.append(strat)

    if not all_strategies:
        print("\n⚠️ No strategies found!")
        return

    print(f"\n📊 Total strategies: {len(all_strategies)}")

    # Write to ideas.txt (one strategy per line)
    print(f"\n💾 Writing to {OUTPUT_IDEAS}...")

    with open(OUTPUT_IDEAS, 'w', encoding='utf-8') as f:
        f.write("# AI Strategy Lab - Formatted for RBI Agent\n")
        f.write("# Each line is one complete strategy\n")
        f.write("# Format: [AI_Name] Strategy: description\n\n")

        for strat in all_strategies:
            # Condense the strategy to a reasonable length
            condensed = condense_strategy(strat['text'], max_length=2000)

            # Write as single line with source tag
            line = f"[{strat['source']}] {strat['name']}: {condensed}\n"
            f.write(line)

        f.write("\n")

    print(f"✅ Formatted {len(all_strategies)} strategies")
    print(f"📄 Output: {OUTPUT_IDEAS}")

    # Show preview
    print("\n" + "="*60)
    print("📋 PREVIEW (first 2 strategies):")
    print("="*60)

    with open(OUTPUT_IDEAS, 'r') as f:
        lines = [line for line in f if line.strip() and not line.startswith('#')]
        for i, line in enumerate(lines[:2]):
            print(f"\nStrategy {i+1}:")
            print(line[:200] + "..." if len(line) > 200 else line)

    print("\n" + "="*60)
    print("✅ READY FOR BACKTESTING!")
    print("="*60)
    print("\nRun: python -m src.agents.rbi_agent_pp_multi")
    print()

if __name__ == "__main__":
    try:
        format_for_rbi()
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
