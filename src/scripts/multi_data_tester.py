"""
🌙 TradeHive's Multi-Data Strategy Tester
Tests a backtesting strategy on ALL available data files

Built with love by TradeHive 🚀

FEATURES:
- Auto-discovers all CSV files in data directories
- Tests strategy on each dataset
- Captures performance metrics for each
- Saves results to CSV for comparison
- Identifies robust strategies (work across multiple assets)

USAGE:
    From RBI agent (automatic):
        test_on_all_data(strategy_code, strategy_name)

    Standalone (manual):
        python src/scripts/multi_data_tester.py --strategy path/to/strategy.py

OUTPUT:
    ./results/{strategy_name}.csv
    Columns: Data, Return %, Sharpe, Sortino, Max DD, Trades, etc.
"""

import os
import sys
import pandas as pd
from pathlib import Path
import subprocess
import tempfile
from termcolor import cprint
import argparse
import re

# Data directories to search
DATA_DIRS = [
    Path(__file__).parent.parent / 'data',
    Path(__file__).parent.parent / 'data' / 'market_data',
    Path(__file__).parent.parent / 'data' / 'rbi'
]

# Results directory
RESULTS_DIR = Path('./results')
RESULTS_DIR.mkdir(exist_ok=True)


def find_all_data_files():
    """Find all CSV files in data directories"""
    data_files = []

    for data_dir in DATA_DIRS:
        if not data_dir.exists():
            continue

        # Find all CSV files recursively
        for csv_file in data_dir.rglob('*.csv'):
            # Skip results and other non-OHLCV files
            if any(skip in str(csv_file) for skip in ['results', 'backtest_stats', 'ideas', 'processed', 'history']):
                continue

            # Check if file has OHLCV structure
            try:
                df = pd.read_csv(csv_file, nrows=5)
                # Check for required columns (case insensitive)
                cols_lower = [c.lower() for c in df.columns]
                has_ohlcv = all(col in cols_lower for col in ['open', 'high', 'low', 'close'])

                if has_ohlcv:
                    data_files.append(csv_file)
            except:
                pass

    return data_files


def run_backtest_on_data(strategy_code, data_file):
    """Run a strategy backtest on a specific data file"""
    try:
        # Create temporary strategy file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            # Modify strategy code to use the specific data file
            modified_code = strategy_code.replace(
                "pd.read_csv('BTC-USD-15m.csv')",
                f"pd.read_csv('{data_file}')"
            )

            # Also try other common patterns
            modified_code = re.sub(
                r"pd\.read_csv\(['\"].*?\.csv['\"]\)",
                f"pd.read_csv('{data_file}')",
                modified_code
            )

            f.write(modified_code)
            temp_file = f.name

        # Run the backtest
        result = subprocess.run(
            ['python', temp_file],
            capture_output=True,
            text=True,
            timeout=60
        )

        # Clean up temp file
        os.unlink(temp_file)

        # Parse output for metrics
        output = result.stdout + result.stderr

        metrics = {
            'Data': data_file.stem,
            'Return %': None,
            'Sharpe Ratio': None,
            'Sortino Ratio': None,
            'Max Drawdown %': None,
            'Trades': None,
            'Win Rate %': None,
            'Success': False
        }

        # Extract metrics from output
        if 'Return' in output:
            metrics['Success'] = True

            # Parse common metric patterns
            patterns = {
                'Return %': r"Return.*?(\d+\.?\d*)%?",
                'Sharpe Ratio': r"Sharpe.*?(\d+\.?\d*)",
                'Sortino Ratio': r"Sortino.*?(\d+\.?\d*)",
                'Max Drawdown %': r"(?:Max.*?Drawdown|Drawdown).*?(\d+\.?\d*)%?",
                'Trades': r"(?:#.*?Trades|Trades).*?(\d+)",
                'Win Rate %': r"Win Rate.*?(\d+\.?\d*)%?"
            }

            for metric, pattern in patterns.items():
                match = re.search(pattern, output, re.IGNORECASE)
                if match:
                    try:
                        metrics[metric] = float(match.group(1))
                    except:
                        pass

        return metrics

    except Exception as e:
        return {
            'Data': data_file.stem,
            'Return %': None,
            'Sharpe Ratio': None,
            'Sortino Ratio': None,
            'Max Drawdown %': None,
            'Trades': None,
            'Win Rate %': None,
            'Success': False,
            'Error': str(e)
        }


def test_on_all_data(strategy_code, strategy_name):
    """
    Test a strategy on all available data files

    Args:
        strategy_code (str): Python code for the strategy
        strategy_name (str): Name of the strategy

    Returns:
        pd.DataFrame: Results for all data files
    """
    cprint(f"\n🧪 Testing {strategy_name} on all data files...", "cyan", attrs=["bold"])

    # Find all data files
    data_files = find_all_data_files()

    if not data_files:
        cprint("⚠️  No data files found!", "yellow")
        return pd.DataFrame()

    cprint(f"📁 Found {len(data_files)} data files", "white")

    # Test on each file
    results = []

    for i, data_file in enumerate(data_files, 1):
        cprint(f"  [{i}/{len(data_files)}] Testing on {data_file.stem}...", "white")

        metrics = run_backtest_on_data(strategy_code, data_file)
        results.append(metrics)

        if metrics['Success']:
            return_pct = metrics.get('Return %', 0) or 0
            color = "green" if return_pct > 0 else "red"
            cprint(f"    ✅ Return: {return_pct:.2f}%", color)
        else:
            cprint(f"    ❌ Failed", "red")

    # Create results DataFrame
    df_results = pd.DataFrame(results)

    # Save to CSV
    output_file = RESULTS_DIR / f"{strategy_name}.csv"
    df_results.to_csv(output_file, index=False)
    cprint(f"\n💾 Results saved to {output_file}", "green")

    # Summary
    successful = df_results['Success'].sum()
    total = len(df_results)

    if successful > 0:
        avg_return = df_results[df_results['Success']]['Return %'].mean()
        cprint(f"\n📊 Summary:", "cyan", attrs=["bold"])
        cprint(f"  ✅ Successful: {successful}/{total}", "green")
        cprint(f"  📈 Avg Return: {avg_return:.2f}%", "white")

        # Best performer
        best_idx = df_results['Return %'].idxmax()
        best = df_results.loc[best_idx]
        cprint(f"  🏆 Best: {best['Data']} ({best['Return %']:.2f}%)", "yellow")
    else:
        cprint(f"\n❌ No successful backtests", "red")

    return df_results


def main():
    """Command-line interface"""
    parser = argparse.ArgumentParser(description='Test strategy on all data files')
    parser.add_argument('--strategy', required=True, help='Path to strategy Python file')
    parser.add_argument('--name', help='Strategy name (default: filename)')

    args = parser.parse_args()

    # Read strategy file
    strategy_path = Path(args.strategy)
    if not strategy_path.exists():
        cprint(f"❌ Strategy file not found: {strategy_path}", "red")
        sys.exit(1)

    with open(strategy_path) as f:
        strategy_code = f.read()

    strategy_name = args.name or strategy_path.stem

    # Run test
    test_on_all_data(strategy_code, strategy_name)


if __name__ == "__main__":
    main()
