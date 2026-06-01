"""
🌙 TradeHive's Exposure % Debug Script 🚀
Tests backtest output to debug why Exposure % is showing as N/A
"""

import subprocess
import re
from pathlib import Path

# Test file from your CSV
TEST_FILE = "/Users/md/Dropbox/dev/github/tradehive-ai-agents-for-trading/src/data/rbi_pp_multi/10_27_2025/backtests_package/T13_BandedOscillator_PKG.py"

print("="*80)
print("🌙 TradeHive's Exposure % Debugger")
print("="*80)
print(f"\n📂 Testing file: {TEST_FILE}\n")

if not Path(TEST_FILE).exists():
    print(f"❌ File not found: {TEST_FILE}")
    exit(1)

print("🚀 Running backtest...")
print("="*80)

try:
    # Run the backtest
    result = subprocess.run(
        ['conda', 'run', '-n', 'tflow', 'python', TEST_FILE],
        capture_output=True,
        text=True,
        timeout=60
    )

    stdout = result.stdout
    stderr = result.stderr

    print("\n📊 STDOUT OUTPUT:")
    print("="*80)
    print(stdout)
    print("="*80)

    if stderr:
        print("\n⚠️ STDERR OUTPUT:")
        print("="*80)
        print(stderr)
        print("="*80)

    # Test the regex patterns from rbi_agent_pp_multi.py
    print("\n🔍 TESTING REGEX PATTERNS:")
    print("="*80)

    patterns = {
        'Return %': r'Return \[%\]\s+([-\d.]+)',
        'Buy & Hold %': r'Buy & Hold Return \[%\]\s+([-\d.]+)',
        'Max Drawdown %': r'Max\. Drawdown \[%\]\s+([-\d.]+)',
        'Sharpe Ratio': r'Sharpe Ratio\s+([-\d.]+)',
        'Sortino Ratio': r'Sortino Ratio\s+([-\d.]+)',
        'Exposure Time [%]': r'Exposure Time \[%\]\s+([-\d.]+)',
        '# Trades': r'# Trades\s+(\d+)',
    }

    for name, pattern in patterns.items():
        match = re.search(pattern, stdout)
        if match:
            print(f"✅ {name:20s} = {match.group(1)}")
        else:
            print(f"❌ {name:20s} = NOT FOUND")

    # Show all lines containing "Exposure"
    print("\n🔎 ALL LINES CONTAINING 'Exposure':")
    print("="*80)
    exposure_lines = [line for line in stdout.split('\n') if 'Exposure' in line or 'exposure' in line]
    if exposure_lines:
        for line in exposure_lines:
            print(f"  {line}")
    else:
        print("  (No lines found)")

    # Show all stat lines (lines with numbers and [%] or percentages)
    print("\n📈 ALL STATS-LIKE LINES:")
    print("="*80)
    for line in stdout.split('\n'):
        if '[%]' in line or 'Ratio' in line or '# Trades' in line:
            print(f"  {line}")

except subprocess.TimeoutExpired:
    print("❌ Backtest timed out after 60 seconds")
except Exception as e:
    print(f"❌ Error running backtest: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80)
print("🌙 Debug complete!")
print("="*80)
