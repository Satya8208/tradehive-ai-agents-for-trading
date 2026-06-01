"""
TradeHive's Model Benchmark Runner
Built with love by TradeHive

This script compares different AI models on the same backtesting strategies
to determine which model performs best for code generation tasks.

MODELS BEING COMPARED:
1. DeepSeek (current default)
2. MiniMax M2.1 via OpenRouter (74% SWE-bench, best price/performance)
3. Kimi K2 via OpenRouter (65.8% SWE-bench, strong agentic coding)
4. Qwen 2.5 Coder via OpenRouter (coding specialist)

METRICS TRACKED:
- Success Rate (strategies that produce working backtest)
- Time per Strategy
- Debug Iterations Required
- Estimated Cost
"""

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime
from termcolor import cprint
from dotenv import load_dotenv
import subprocess
import re

# Setup paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

# Load environment variables
load_dotenv(PROJECT_ROOT / ".env")

from src.models import model_factory

# ============================================
# BENCHMARK CONFIGURATION
# ============================================

# Models to benchmark
BENCHMARK_MODELS = [
    {
        "name": "DeepSeek Coder",
        "type": "deepseek",
        "model": "deepseek-coder",
        "cost_per_1m_input": 0.14,
        "cost_per_1m_output": 0.28,
    },
    {
        "name": "MiniMax M2.1",
        "type": "openrouter",
        "model": "minimax/minimax-m2.1",
        "cost_per_1m_input": 0.20,
        "cost_per_1m_output": 1.10,
    },
    {
        "name": "Kimi K2",
        "type": "openrouter",
        "model": "moonshotai/kimi-k2",
        "cost_per_1m_input": 0.55,
        "cost_per_1m_output": 2.20,
    },
    {
        "name": "Qwen 2.5 Coder",
        "type": "openrouter",
        "model": "qwen/qwen-2.5-coder-32b-instruct",
        "cost_per_1m_input": 0.50,
        "cost_per_1m_output": 1.50,
    },
]

# Test strategies - simple enough to test code generation capabilities
TEST_STRATEGIES = [
    "[TECHNIQUE:RSI_Reversal] RSI oversold reversal: Buy when RSI(14) crosses above 30 from below, sell when RSI crosses below 70 from above. Use ATR(10) for stop loss at 1.5x below entry.",
    "[TECHNIQUE:MACD_Cross] MACD crossover trend: Buy when MACD line crosses above signal line and both are below zero, sell on opposite crossover. Hold for minimum 5 bars.",
    "[TECHNIQUE:BB_Squeeze] Bollinger Band squeeze breakout: Enter long when price breaks above upper band after a squeeze (bandwidth < 0.05), exit when price returns to middle band.",
]

# Benchmark settings
MAX_DEBUG_ITERATIONS = 5
EXECUTION_TIMEOUT = 180  # 3 minutes per strategy
CONDA_ENV = "tflow"

# Data file for testing (using sample BTC data with proper format)
TEST_DATA_PATH = PROJECT_ROOT / "sample_BTC_data.csv"

# Results directory
RESULTS_DIR = PROJECT_ROOT / "src" / "data" / "benchmarks"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================
# PROMPTS
# ============================================

BACKTEST_PROMPT = """
You are a Python backtest code generator. Generate COMPLETE, RUNNABLE backtesting.py code.

REQUIREMENTS:
1. Use the backtesting.py library
2. Include ALL imports (backtesting, talib, pandas, numpy)
3. Create a Strategy class that inherits from Strategy
4. Use self.I() wrapper for ALL indicator calculations
5. Include proper entry/exit logic with self.buy() and self.sell()
6. Set position size to 0.95 (95% of portfolio)

DATA HANDLING:
- Read CSV from: {data_path}
- Clean columns: data.columns = data.columns.str.strip().str.lower()
- Map to required format: Open, High, Low, Close, Volume (capital first letter)

CRITICAL: Include if __name__ == "__main__" block that:
1. Loads data
2. Runs backtest with initial cash=1000000
3. Prints stats using print(stats)

OUTPUT: Only the Python code, no explanations.

STRATEGY TO IMPLEMENT:
{strategy}
"""

# ============================================
# BENCHMARK FUNCTIONS
# ============================================

def get_model_instance(model_config):
    """Get model instance from factory"""
    try:
        api_key_map = {
            "deepseek": "DEEPSEEK_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "claude": "ANTHROPIC_KEY",
            "openai": "OPENAI_KEY",
        }

        api_key = os.getenv(api_key_map.get(model_config["type"], ""))
        if not api_key:
            cprint(f"  No API key for {model_config['name']}", "yellow")
            return None

        # model_factory is already the ModelFactory instance (singleton)
        model = model_factory.get_model(
            model_config["type"],
            model_config["model"]
        )
        return model
    except Exception as e:
        cprint(f"  Error getting model {model_config['name']}: {e}", "red")
        return None

def generate_backtest_code(model, strategy, data_path):
    """Generate backtest code using the model"""
    prompt = BACKTEST_PROMPT.format(
        strategy=strategy,
        data_path=str(data_path)
    )

    start_time = time.time()
    response = model.generate_response(
        system_prompt="You are a Python code generator. Output only valid Python code.",
        user_content=prompt,
        temperature=0.3,
        max_tokens=4000
    )
    elapsed = time.time() - start_time

    if response is None:
        return None, elapsed, 0

    # Extract code from response
    code = response.content

    # Clean up markdown code blocks if present
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0]
    elif "```" in code:
        code = code.split("```")[1].split("```")[0]

    # Estimate tokens used (rough approximation)
    tokens_used = len(prompt.split()) * 1.3 + len(code.split()) * 1.3

    return code.strip(), elapsed, int(tokens_used)

def execute_backtest(code, work_dir):
    """Execute the generated backtest code"""
    # Save code to file
    code_path = work_dir / "test_strategy.py"
    with open(code_path, "w") as f:
        f.write(code)

    # Execute with conda - quote paths to handle spaces
    try:
        result = subprocess.run(
            f'conda run -n {CONDA_ENV} python "{code_path}"',
            shell=True,
            capture_output=True,
            text=True,
            timeout=EXECUTION_TIMEOUT,
            cwd=str(work_dir)
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": "Execution timeout",
            "returncode": -1
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "returncode": -1
        }

def extract_metrics(stdout):
    """Extract performance metrics from backtest output"""
    metrics = {
        "return_pct": None,
        "sharpe": None,
        "trades": None,
        "win_rate": None
    }

    # Try to extract Return [%]
    return_match = re.search(r"Return \[%\]\s+([-\d.]+)", stdout)
    if return_match:
        metrics["return_pct"] = float(return_match.group(1))

    # Try to extract Sharpe Ratio
    sharpe_match = re.search(r"Sharpe Ratio\s+([-\d.]+)", stdout)
    if sharpe_match:
        metrics["sharpe"] = float(sharpe_match.group(1))

    # Try to extract # Trades
    trades_match = re.search(r"# Trades\s+(\d+)", stdout)
    if trades_match:
        metrics["trades"] = int(trades_match.group(1))

    # Try to extract Win Rate
    winrate_match = re.search(r"Win Rate \[%\]\s+([-\d.]+)", stdout)
    if winrate_match:
        metrics["win_rate"] = float(winrate_match.group(1))

    return metrics

def run_benchmark_for_model(model_config, strategies, work_dir):
    """Run benchmark for a single model across all strategies"""
    cprint(f"\n{'='*60}", "cyan")
    cprint(f"  BENCHMARKING: {model_config['name']}", "cyan", attrs=['bold'])
    cprint(f"  Model: {model_config['model']}", "cyan")
    cprint(f"{'='*60}", "cyan")

    model = get_model_instance(model_config)
    if model is None:
        return {
            "model": model_config["name"],
            "available": False,
            "results": []
        }

    results = []

    for i, strategy in enumerate(strategies):
        cprint(f"\n  Strategy {i+1}/{len(strategies)}: {strategy[:50]}...", "yellow")

        strategy_result = {
            "strategy": strategy,
            "success": False,
            "time_seconds": 0,
            "debug_iterations": 0,
            "tokens_used": 0,
            "metrics": {},
            "error": None
        }

        total_time = 0
        total_tokens = 0

        # Generate initial code
        cprint("    Generating code...", "white")
        code, gen_time, tokens = generate_backtest_code(model, strategy, TEST_DATA_PATH)
        total_time += gen_time
        total_tokens += tokens

        if code is None:
            strategy_result["error"] = "Code generation failed"
            results.append(strategy_result)
            cprint(f"    FAILED: Code generation failed", "red")
            continue

        # Try to execute (with debug iterations if needed)
        for debug_iter in range(MAX_DEBUG_ITERATIONS):
            strategy_result["debug_iterations"] = debug_iter + 1

            cprint(f"    Executing (attempt {debug_iter + 1})...", "white")
            exec_result = execute_backtest(code, work_dir)

            if exec_result["success"]:
                strategy_result["success"] = True
                strategy_result["metrics"] = extract_metrics(exec_result["stdout"])
                cprint(f"    SUCCESS! Return: {strategy_result['metrics'].get('return_pct', 'N/A')}%", "green")
                break
            else:
                if debug_iter < MAX_DEBUG_ITERATIONS - 1:
                    # Try to debug
                    cprint(f"    Error: {exec_result['stderr'][:100]}...", "red")
                    # For now, we won't implement full debug loop - just track failure
                else:
                    strategy_result["error"] = exec_result["stderr"][:200]
                    cprint(f"    FAILED after {MAX_DEBUG_ITERATIONS} attempts", "red")

        strategy_result["time_seconds"] = total_time
        strategy_result["tokens_used"] = total_tokens
        results.append(strategy_result)

    return {
        "model": model_config["name"],
        "model_id": model_config["model"],
        "available": True,
        "cost_per_1m_input": model_config["cost_per_1m_input"],
        "cost_per_1m_output": model_config["cost_per_1m_output"],
        "results": results
    }

def calculate_summary(model_results):
    """Calculate summary statistics for a model"""
    results = model_results["results"]

    if not results:
        return {
            "success_rate": 0,
            "avg_time": 0,
            "avg_debug_iterations": 0,
            "total_tokens": 0,
            "estimated_cost": 0
        }

    successes = sum(1 for r in results if r["success"])
    total_time = sum(r["time_seconds"] for r in results)
    total_debug = sum(r["debug_iterations"] for r in results)
    total_tokens = sum(r["tokens_used"] for r in results)

    # Estimate cost (rough: assume 70% input, 30% output tokens)
    input_tokens = total_tokens * 0.7
    output_tokens = total_tokens * 0.3
    estimated_cost = (
        (input_tokens / 1_000_000) * model_results.get("cost_per_1m_input", 0) +
        (output_tokens / 1_000_000) * model_results.get("cost_per_1m_output", 0)
    )

    return {
        "success_rate": successes / len(results) * 100,
        "avg_time": total_time / len(results),
        "avg_debug_iterations": total_debug / len(results),
        "total_tokens": total_tokens,
        "estimated_cost": estimated_cost
    }

def print_comparison_report(all_results):
    """Print formatted comparison report"""
    cprint("\n" + "="*80, "white", attrs=['bold'])
    cprint("  MODEL BENCHMARK COMPARISON REPORT", "white", attrs=['bold'])
    cprint("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "white")
    cprint("="*80, "white", attrs=['bold'])

    # Print per-model results
    for model_results in all_results:
        if not model_results["available"]:
            cprint(f"\n  {model_results['model']}: NOT AVAILABLE", "yellow")
            continue

        summary = calculate_summary(model_results)

        cprint(f"\n  {model_results['model']}", "cyan", attrs=['bold'])
        cprint(f"  " + "-"*40, "cyan")
        cprint(f"    Success Rate:     {summary['success_rate']:.1f}%", "green" if summary["success_rate"] > 50 else "red")
        cprint(f"    Avg Time:         {summary['avg_time']:.1f}s", "white")
        cprint(f"    Avg Debug Iters:  {summary['avg_debug_iterations']:.1f}", "white")
        cprint(f"    Total Tokens:     {summary['total_tokens']:,}", "white")
        cprint(f"    Est. Cost:        ${summary['estimated_cost']:.4f}", "white")

    # Print winner
    cprint("\n" + "="*80, "white", attrs=['bold'])
    cprint("  RANKING BY SUCCESS RATE", "yellow", attrs=['bold'])
    cprint("="*80, "white", attrs=['bold'])

    ranked = sorted(
        [r for r in all_results if r["available"]],
        key=lambda x: calculate_summary(x)["success_rate"],
        reverse=True
    )

    for i, r in enumerate(ranked, 1):
        summary = calculate_summary(r)
        medal = ["", "", ""][i-1] if i <= 3 else f"{i}."
        cprint(f"  {medal} {r['model']}: {summary['success_rate']:.1f}% success, ${summary['estimated_cost']:.4f}", "white")

    return ranked

def main():
    """Main benchmark runner"""
    cprint("\n" + "="*80, "magenta", attrs=['bold'])
    cprint("  TRADEHIVE'S MODEL BENCHMARK RUNNER", "magenta", attrs=['bold'])
    cprint("  Testing AI models for backtesting code generation", "magenta")
    cprint("="*80, "magenta", attrs=['bold'])

    # Check for test data
    if not TEST_DATA_PATH.exists():
        cprint(f"\n  Test data not found: {TEST_DATA_PATH}", "red")
        cprint("  Please ensure test data exists before running benchmark.", "yellow")
        return

    # Create work directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = RESULTS_DIR / f"benchmark_{timestamp}"
    work_dir.mkdir(parents=True, exist_ok=True)

    cprint(f"\n  Work Directory: {work_dir}", "white")
    cprint(f"  Test Strategies: {len(TEST_STRATEGIES)}", "white")
    cprint(f"  Models to Test: {len(BENCHMARK_MODELS)}", "white")

    # Run benchmarks
    all_results = []

    for model_config in BENCHMARK_MODELS:
        try:
            results = run_benchmark_for_model(model_config, TEST_STRATEGIES, work_dir)
            all_results.append(results)
        except Exception as e:
            cprint(f"\n  Error benchmarking {model_config['name']}: {e}", "red")
            all_results.append({
                "model": model_config["name"],
                "available": False,
                "results": [],
                "error": str(e)
            })

    # Print comparison report
    ranked = print_comparison_report(all_results)

    # Save results to JSON
    results_file = work_dir / "benchmark_results.json"
    with open(results_file, "w") as f:
        json.dump({
            "timestamp": timestamp,
            "strategies_tested": len(TEST_STRATEGIES),
            "models": [r["model"] for r in all_results],
            "results": all_results
        }, f, indent=2, default=str)

    cprint(f"\n  Results saved to: {results_file}", "green")

    # Recommendation
    if ranked:
        winner = ranked[0]
        summary = calculate_summary(winner)
        cprint("\n" + "="*80, "green", attrs=['bold'])
        cprint(f"  RECOMMENDATION: {winner['model']}", "green", attrs=['bold'])
        cprint(f"  Success Rate: {summary['success_rate']:.1f}% | Cost: ${summary['estimated_cost']:.4f}", "green")
        cprint("="*80, "green", attrs=['bold'])

if __name__ == "__main__":
    main()
