"""
AutoTrader — Autonomous Strategy Optimizer

Applies Karpathy's autoresearch pattern to Polymarket trading:
1. Modify a parameter
2. Score against historical trades (fast — seconds, not hours)
3. Keep if improved, discard if not
4. Loop forever

Usage:
    python -m src.agents.polymarket_trader.auto_optimize --rounds 50
    python -m src.agents.polymarket_trader.auto_optimize --rounds 0  # infinite
"""

import argparse
import csv
import json
import random
import time
from copy import deepcopy
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from termcolor import cprint

from .backtest_scorer import BacktestScorer, ParamSet, BacktestResult


# Parameter search space — what we can mutate
SEARCH_SPACE = {
    "min_edge_threshold": (3.0, 30.0),
    "min_edge_confidence": (0.30, 0.80),
    "kelly_fraction": (0.10, 0.50),
    "min_arb_edge_percent": (5.0, 50.0),
    "max_position_usd": (15.0, 100.0),
    "min_arb_token_price": (0.01, 0.10),
}

# Discrete parameters
DISCRETE_SPACE = {
    "allow_swarm": [True, False],
    "allow_arb": [True, False],
    "allowed_symbols": [
        ["ETH"],
        ["BTC"],
        ["ETH", "BTC"],
        ["ETH", "BTC", "SOL"],
        ["ETH", "BTC", "SOL", "XRP", "DOGE"],
    ],
}


class AutoOptimizer:
    """
    Autonomous parameter optimizer using the autoresearch pattern.

    Maintains a "best known" parameter set and explores mutations.
    Keeps improvements, discards regressions.
    """

    def __init__(self, results_path: str = "src/data/polymarket_trader/optimization_results.tsv"):
        self.scorer = BacktestScorer()
        self.results_path = Path(results_path)
        self.results_path.parent.mkdir(parents=True, exist_ok=True)

        # Current best
        self.best_params = ParamSet()
        self.best_result = self.scorer.score(self.best_params)
        self.best_score = self.best_result.score

        # History
        self.round_num = 0
        self.improvements = 0
        self.discards = 0

        # Initialize results file
        self._init_results_file()

    def _init_results_file(self):
        """Create TSV with header if it doesn't exist."""
        if not self.results_path.exists():
            with open(self.results_path, "w", newline="") as f:
                writer = csv.writer(f, delimiter="\t")
                writer.writerow([
                    "round", "score", "win_rate", "pnl", "trades",
                    "roi", "status", "description", "params_changed"
                ])

        # Log baseline
        self._log_result(
            0, self.best_result, "baseline",
            "initial parameters", "{}"
        )

    def run(self, max_rounds: int = 0):
        """
        Run the optimization loop.

        max_rounds=0 means infinite (until interrupted).
        """
        cprint("=" * 70, "cyan")
        cprint("AUTOTRADER — Autonomous Strategy Optimizer", "cyan", attrs=["bold"])
        cprint(f"Loaded {len(self.scorer.trades)} resolved trades", "cyan")
        cprint(f"Baseline score: {self.best_score:.2f} "
               f"({self.best_result.win_rate:.1%} WR, "
               f"${self.best_result.total_pnl:+.2f} P&L)", "cyan")
        cprint("=" * 70, "cyan")
        print()

        try:
            while True:
                self.round_num += 1

                if max_rounds > 0 and self.round_num > max_rounds:
                    break

                self._run_experiment()

        except KeyboardInterrupt:
            cprint("\nStopped by user", "yellow")

        self._print_final_summary()

    def _run_experiment(self):
        """Run a single experiment: mutate, score, keep/discard."""
        # Choose mutation strategy
        strategy = random.choice([
            "single_continuous",
            "single_discrete",
            "double_mutation",
            "random_restart",
        ])

        if strategy == "single_continuous":
            candidate, description, changes = self._mutate_continuous()
        elif strategy == "single_discrete":
            candidate, description, changes = self._mutate_discrete()
        elif strategy == "double_mutation":
            candidate, description, changes = self._mutate_double()
        else:
            candidate, description, changes = self._random_restart()

        # Score
        result = self.scorer.score(candidate)

        # Decide: keep or discard
        if result.score > self.best_score and result.filtered_trades >= 5:
            status = "keep"
            improvement = result.score - self.best_score
            self.best_params = candidate
            self.best_result = result
            self.best_score = result.score
            self.improvements += 1

            cprint(f"  R{self.round_num:3d} KEEP   "
                   f"score={result.score:.1f} (+{improvement:.1f}) | "
                   f"{result.win_rate:.0%} WR | "
                   f"${result.total_pnl:+.0f} | "
                   f"{result.filtered_trades}t | "
                   f"{description}", "green")
        else:
            status = "discard"
            self.discards += 1

            if result.filtered_trades < 5:
                reason = f"too few trades ({result.filtered_trades})"
            else:
                reason = f"score={result.score:.1f} vs best={self.best_score:.1f}"

            cprint(f"  R{self.round_num:3d} DISCARD "
                   f"score={result.score:.1f} | "
                   f"{result.win_rate:.0%} WR | "
                   f"${result.total_pnl:+.0f} | "
                   f"{result.filtered_trades}t | "
                   f"{description} ({reason})", "red")

        self._log_result(
            self.round_num, result, status,
            description, json.dumps(changes)
        )

    def _mutate_continuous(self) -> Tuple[ParamSet, str, Dict]:
        """Mutate a single continuous parameter."""
        candidate = deepcopy(self.best_params)
        param = random.choice(list(SEARCH_SPACE.keys()))
        lo, hi = SEARCH_SPACE[param]

        old_val = getattr(candidate, param)
        # Gaussian mutation centered on current value
        sigma = (hi - lo) * 0.15
        new_val = max(lo, min(hi, old_val + random.gauss(0, sigma)))
        new_val = round(new_val, 3)

        setattr(candidate, param, new_val)

        description = f"{param}: {old_val:.3f} -> {new_val:.3f}"
        changes = {param: {"old": old_val, "new": new_val}}
        return candidate, description, changes

    def _mutate_discrete(self) -> Tuple[ParamSet, str, Dict]:
        """Mutate a single discrete parameter."""
        candidate = deepcopy(self.best_params)
        param = random.choice(list(DISCRETE_SPACE.keys()))
        options = DISCRETE_SPACE[param]

        old_val = getattr(candidate, param)
        new_val = random.choice([v for v in options if v != old_val] or options)

        setattr(candidate, param, new_val)

        description = f"{param}: {old_val} -> {new_val}"
        changes = {param: {"old": str(old_val), "new": str(new_val)}}
        return candidate, description, changes

    def _mutate_double(self) -> Tuple[ParamSet, str, Dict]:
        """Mutate two parameters at once."""
        candidate = deepcopy(self.best_params)
        changes = {}

        # First mutation: continuous
        param1 = random.choice(list(SEARCH_SPACE.keys()))
        lo, hi = SEARCH_SPACE[param1]
        old1 = getattr(candidate, param1)
        sigma = (hi - lo) * 0.15
        new1 = max(lo, min(hi, old1 + random.gauss(0, sigma)))
        new1 = round(new1, 3)
        setattr(candidate, param1, new1)
        changes[param1] = {"old": old1, "new": new1}

        # Second mutation: could be continuous or discrete
        if random.random() < 0.5 and DISCRETE_SPACE:
            param2 = random.choice(list(DISCRETE_SPACE.keys()))
            old2 = getattr(candidate, param2)
            new2 = random.choice(DISCRETE_SPACE[param2])
            setattr(candidate, param2, new2)
            changes[param2] = {"old": str(old2), "new": str(new2)}
        else:
            param2 = random.choice([p for p in SEARCH_SPACE if p != param1])
            lo2, hi2 = SEARCH_SPACE[param2]
            old2 = getattr(candidate, param2)
            sigma2 = (hi2 - lo2) * 0.15
            new2 = max(lo2, min(hi2, old2 + random.gauss(0, sigma2)))
            new2 = round(new2, 3)
            setattr(candidate, param2, new2)
            changes[param2] = {"old": old2, "new": new2}

        description = f"{param1}={new1:.3f} + {param2}={new2}"
        return candidate, description, changes

    def _random_restart(self) -> Tuple[ParamSet, str, Dict]:
        """Generate completely random parameters (exploration)."""
        candidate = ParamSet()
        changes = {}

        for param, (lo, hi) in SEARCH_SPACE.items():
            val = round(random.uniform(lo, hi), 3)
            setattr(candidate, param, val)
            changes[param] = {"old": "baseline", "new": val}

        # Random discrete params
        for param, options in DISCRETE_SPACE.items():
            val = random.choice(options)
            setattr(candidate, param, val)
            changes[param] = {"old": "baseline", "new": str(val)}

        description = "RANDOM RESTART"
        return candidate, description, changes

    def _log_result(self, round_num: int, result: BacktestResult,
                    status: str, description: str, params_json: str):
        """Append result to TSV."""
        with open(self.results_path, "a", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow([
                round_num,
                f"{result.score:.2f}",
                f"{result.win_rate:.3f}",
                f"{result.total_pnl:.2f}",
                result.filtered_trades,
                f"{result.roi:.3f}",
                status,
                description,
                params_json,
            ])

    def _print_final_summary(self):
        """Print optimization summary."""
        cprint("\n" + "=" * 70, "cyan")
        cprint("OPTIMIZATION COMPLETE", "cyan", attrs=["bold"])
        cprint("=" * 70, "cyan")

        print(f"Rounds: {self.round_num}")
        print(f"Improvements: {self.improvements}")
        print(f"Discards: {self.discards}")
        print(f"Improvement rate: {self.improvements/max(self.round_num,1):.1%}")
        print()

        print(f"BEST PARAMETERS (score={self.best_score:.2f}):")
        print(f"  min_edge_threshold:  {self.best_params.min_edge_threshold:.1f}%")
        print(f"  min_edge_confidence: {self.best_params.min_edge_confidence:.2f}")
        print(f"  kelly_fraction:      {self.best_params.kelly_fraction:.2f}")
        print(f"  min_arb_edge:        {self.best_params.min_arb_edge_percent:.1f}%")
        print(f"  max_position_usd:    ${self.best_params.max_position_usd:.0f}")
        print(f"  min_arb_token_price: ${self.best_params.min_arb_token_price:.3f}")
        print(f"  allow_swarm:         {self.best_params.allow_swarm}")
        print(f"  allow_arb:           {self.best_params.allow_arb}")
        print(f"  allowed_symbols:     {self.best_params.allowed_symbols}")
        print()

        r = self.best_result
        print(f"BEST RESULT:")
        print(f"  Trades: {r.filtered_trades}/{r.total_trades}")
        print(f"  Win rate: {r.win_rate:.1%} ({r.wins}W/{r.losses}L)")
        print(f"  P&L: ${r.total_pnl:+.2f} on ${r.total_deployed:.0f}")
        print(f"  ROI: {r.roi:.1%}")
        print(f"  Score: {r.score:.2f}")

        if r.by_source:
            print(f"\n  By source:")
            for src, stats in r.by_source.items():
                wr = stats["wins"] / stats["count"] if stats["count"] > 0 else 0
                print(f"    {src:12s}: {stats['count']}t | "
                      f"${stats['pnl']:+.2f} | {wr:.0%} WR")

        if r.by_symbol:
            print(f"\n  By symbol:")
            for sym, stats in r.by_symbol.items():
                wr = stats["wins"] / stats["count"] if stats["count"] > 0 else 0
                print(f"    {sym:5s}: {stats['count']}t | "
                      f"${stats['pnl']:+.2f} | {wr:.0%} WR")

        print(f"\nResults saved to: {self.results_path}")
        cprint("=" * 70, "cyan")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AutoTrader — Autonomous Strategy Optimizer")
    parser.add_argument("--rounds", type=int, default=50,
                        help="Number of optimization rounds (0=infinite)")
    args = parser.parse_args()

    optimizer = AutoOptimizer()
    optimizer.run(max_rounds=args.rounds)
