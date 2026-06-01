"""
Poker AutoOptimizer — Autonomous Poker Strategy Optimizer

Applies Karpathy's autoresearch pattern to poker strategy:
1. Modify a parameter (open %, cbet freq, bluff ratio, etc.)
2. Simulate thousands of hands (fast — seconds, not hours)
3. Keep if improved, discard if not
4. Loop forever

Usage:
    python -m src.agents.poker.auto_optimize --rounds 50
    python -m src.agents.poker.auto_optimize --rounds 0  # infinite
"""

import argparse
import csv
import json
import random
import time
from copy import deepcopy
from pathlib import Path
from typing import Dict, Tuple

from termcolor import cprint

from .poker_scorer import PokerScorer, PokerParamSet, PokerBacktestResult


# Parameter search space
SEARCH_SPACE = {
    "rfi_utg_pct": (8.0, 18.0),
    "rfi_mp_pct": (12.0, 22.0),
    "rfi_co_pct": (20.0, 35.0),
    "rfi_btn_pct": (30.0, 55.0),
    "rfi_sb_pct": (25.0, 50.0),
    "three_bet_vs_ep": (3.0, 10.0),
    "three_bet_vs_lp": (6.0, 18.0),
    "cbet_freq": (0.40, 0.85),
    "cbet_size_pct": (0.25, 0.75),
    "turn_barrel_freq": (0.25, 0.65),
    "river_bet_freq": (0.20, 0.55),
    "raise_vs_bet_freq": (0.05, 0.30),
    "bluff_ratio": (0.15, 0.45),
}

MIN_HANDS_THRESHOLD = 500
MAX_DRAWDOWN_THRESHOLD = 0.80


class PokerAutoOptimizer:
    """
    Autonomous parameter optimizer for poker strategy.
    Same Karpathy autoresearch pattern as BJ and Polymarket.
    """

    def __init__(
        self,
        num_hands: int = 2000,
        num_sessions: int = 3,
        results_path: str = None,
        min_hands_threshold: int = None,
        max_drawdown_threshold: float = MAX_DRAWDOWN_THRESHOLD,
    ):
        if results_path is None:
            results_path = "src/data/poker_agent/optimization_results.tsv"

        self.results_path = Path(results_path)
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        total_samples = num_hands * max(num_sessions, 1)
        self.min_hands_threshold = min_hands_threshold or max(MIN_HANDS_THRESHOLD, int(total_samples * 0.6))
        self.max_drawdown_threshold = max_drawdown_threshold

        self.scorer = PokerScorer(num_hands=num_hands, num_sessions=num_sessions)

        # Score baseline
        cprint("Scoring baseline params...", "cyan")
        self.best_params = PokerParamSet()
        self.best_result = self.scorer.score(self.best_params)
        self.best_score = self.best_result.score

        self.round_num = 0
        self.improvements = 0
        self.discards = 0

        self._init_results_file()

    def _init_results_file(self):
        """Create TSV with header."""
        if not self.results_path.exists():
            with open(self.results_path, "w", newline="") as f:
                writer = csv.writer(f, delimiter="\t")
                writer.writerow([
                    "round", "score", "bb_per_100", "pnl", "hands",
                    "vpip", "pfr", "max_drawdown", "bb100_ci_low", "bb100_ci_high",
                    "hand_errors", "status", "description", "params_changed",
                    "params_snapshot",
                ])

        self._log_result(
            0,
            self.best_result,
            "baseline",
            "initial parameters",
            "{}",
            self._serialize_params(self.best_params),
        )

    def run(self, max_rounds: int = 0):
        """Run the optimization loop."""
        cprint("=" * 70, "cyan")
        cprint("POKER AUTORESEARCH — Autonomous Strategy Optimizer", "cyan", attrs=["bold"])
        cprint(f"Simulating {self.scorer.num_hands} hands x {self.scorer.num_sessions} sessions/round", "cyan")
        cprint(f"Search space: {len(SEARCH_SPACE)} continuous params", "cyan")
        cprint(f"Baseline: score={self.best_score:.1f} "
               f"({self.best_result.bb_per_100:+.1f} BB/100, "
               f"VPIP={self.best_result.vpip:.0f}%)", "cyan")
        cprint("=" * 70, "cyan")
        print()

        start_time = time.time()

        try:
            while True:
                self.round_num += 1
                if max_rounds > 0 and self.round_num > max_rounds:
                    break
                self._run_experiment()
        except KeyboardInterrupt:
            cprint("\nStopped by user", "yellow")

        elapsed = time.time() - start_time
        self._print_final_summary(elapsed)

    def _run_experiment(self):
        """Mutate, score, keep/discard."""
        strategy = random.choice([
            "single_continuous",
            "single_continuous",
            "double_mutation",
            "random_restart",
        ])

        if strategy == "single_continuous":
            candidate, desc, changes = self._mutate_continuous()
        elif strategy == "double_mutation":
            candidate, desc, changes = self._mutate_double()
        else:
            candidate, desc, changes = self._random_restart()

        result = self.scorer.score(candidate)

        quality_ok, quality_reason = self._passes_quality_gate(result)
        if result.score > self.best_score and quality_ok:
            status = "keep"
            improvement = result.score - self.best_score
            self.best_params = candidate
            self.best_result = result
            self.best_score = result.score
            self.improvements += 1

            cprint(f"  R{self.round_num:3d} KEEP   "
                   f"score={result.score:.1f} (+{improvement:.1f}) | "
                   f"{result.bb_per_100:+.1f} BB/100 | "
                   f"VPIP={result.vpip:.0f}% | "
                   f"{desc}", "green")
        else:
            status = "discard"
            self.discards += 1

            if not quality_ok:
                reason = quality_reason
            else:
                reason = f"score={result.score:.1f} vs best={self.best_score:.1f}"

            cprint(f"  R{self.round_num:3d} DISCARD "
                   f"score={result.score:.1f} | "
                   f"{result.bb_per_100:+.1f} BB/100 | "
                   f"VPIP={result.vpip:.0f}% | "
                   f"{desc} ({reason})", "red")

        self._log_result(
            self.round_num,
            result,
            status,
            desc,
            json.dumps(changes),
            self._serialize_params(candidate),
        )

    def _passes_quality_gate(self, result: PokerBacktestResult) -> Tuple[bool, str]:
        """Reject noisy winners from short or error-prone runs."""
        if result.hands_played < self.min_hands_threshold:
            return False, f"too few hands ({result.hands_played} < {self.min_hands_threshold})"
        if result.bb_per_100_ci_low <= 0:
            return False, f"CI crosses zero ({result.bb_per_100_ci_low:+.1f} BB/100 low)"
        if result.max_drawdown > self.max_drawdown_threshold:
            return False, f"drawdown too high ({result.max_drawdown:.1%})"
        if result.hand_errors > 0:
            return False, f"simulation errors encountered ({result.hand_errors})"
        return True, ""

    def _serialize_params(self, params: PokerParamSet) -> str:
        """Persist the full parameter set for exact replay."""
        return json.dumps(vars(params), sort_keys=True)

    def _mutate_continuous(self) -> Tuple[PokerParamSet, str, Dict]:
        """Mutate a single continuous parameter."""
        candidate = deepcopy(self.best_params)
        param = random.choice(list(SEARCH_SPACE.keys()))
        lo, hi = SEARCH_SPACE[param]

        old_val = getattr(candidate, param)
        sigma = (hi - lo) * 0.15
        new_val = max(lo, min(hi, old_val + random.gauss(0, sigma)))
        new_val = round(new_val, 3)

        setattr(candidate, param, new_val)
        desc = f"{param}: {old_val:.3f} -> {new_val:.3f}"
        changes = {param: {"old": old_val, "new": new_val}}
        return candidate, desc, changes

    def _mutate_double(self) -> Tuple[PokerParamSet, str, Dict]:
        """Mutate two parameters at once."""
        candidate = deepcopy(self.best_params)
        changes = {}

        params = random.sample(list(SEARCH_SPACE.keys()), 2)
        for param in params:
            lo, hi = SEARCH_SPACE[param]
            old_val = getattr(candidate, param)
            sigma = (hi - lo) * 0.15
            new_val = max(lo, min(hi, old_val + random.gauss(0, sigma)))
            new_val = round(new_val, 3)
            setattr(candidate, param, new_val)
            changes[param] = {"old": old_val, "new": new_val}

        desc = " + ".join(f"{p}={changes[p]['new']:.2f}" for p in params)
        return candidate, desc, changes

    def _random_restart(self) -> Tuple[PokerParamSet, str, Dict]:
        """Generate random parameters."""
        candidate = PokerParamSet()
        changes = {}

        for param, (lo, hi) in SEARCH_SPACE.items():
            val = round(random.uniform(lo, hi), 3)
            setattr(candidate, param, val)
            changes[param] = {"old": "baseline", "new": val}

        return candidate, "RANDOM RESTART", changes

    def _log_result(self, round_num: int, result: PokerBacktestResult,
                    status: str, description: str, params_json: str, snapshot_json: str):
        """Append result to TSV."""
        with open(self.results_path, "a", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow([
                round_num,
                f"{result.score:.2f}",
                f"{result.bb_per_100:.2f}",
                f"{result.total_pnl:.2f}",
                result.hands_played,
                f"{result.vpip:.1f}",
                f"{result.pfr:.1f}",
                f"{result.max_drawdown:.3f}",
                f"{result.bb_per_100_ci_low:.2f}",
                f"{result.bb_per_100_ci_high:.2f}",
                result.hand_errors,
                status,
                description,
                params_json,
                snapshot_json,
            ])

    def _print_final_summary(self, elapsed: float = 0):
        """Print optimization summary."""
        cprint("\n" + "=" * 70, "cyan")
        cprint("OPTIMIZATION COMPLETE", "cyan", attrs=["bold"])
        cprint("=" * 70, "cyan")

        rounds = max(self.round_num - 1, 0)
        print(f"Rounds: {rounds}")
        print(f"Improvements: {self.improvements}")
        print(f"Discards: {self.discards}")
        print(f"Improvement rate: {self.improvements / max(rounds, 1):.1%}")
        if elapsed > 0:
            print(f"Time: {elapsed:.1f}s ({elapsed / max(rounds, 1):.1f}s/round)")
        print()

        p = self.best_params
        print("BEST PARAMETERS:")
        print(f"  Preflop Open %:")
        print(f"    UTG: {p.rfi_utg_pct:.1f}%  MP: {p.rfi_mp_pct:.1f}%  "
              f"CO: {p.rfi_co_pct:.1f}%  BTN: {p.rfi_btn_pct:.1f}%  SB: {p.rfi_sb_pct:.1f}%")
        print(f"  3-Bet %:")
        print(f"    vs EP: {p.three_bet_vs_ep:.1f}%  vs LP: {p.three_bet_vs_lp:.1f}%")
        print(f"  Postflop:")
        print(f"    C-bet: {p.cbet_freq:.0%} @ {p.cbet_size_pct:.0%} pot")
        print(f"    Turn barrel: {p.turn_barrel_freq:.0%}  River bet: {p.river_bet_freq:.0%}")
        print(f"    Raise vs bet: {p.raise_vs_bet_freq:.0%}  Bluff ratio: {p.bluff_ratio:.0%}")
        print()

        r = self.best_result
        print("BEST RESULT:")
        print(f"  Hands: {r.hands_played}")
        print(f"  BB/100: {r.bb_per_100:+.1f}")
        print(f"  P&L: {r.total_pnl:+.1f} BB")
        print(f"  VPIP: {r.vpip:.1f}%  PFR: {r.pfr:.1f}%")
        print(f"  Showdowns: {r.showdowns} ({r.showdowns_won} won)")
        print(f"  95% CI: {r.bb_per_100_ci_low:+.1f} to {r.bb_per_100_ci_high:+.1f} BB/100")
        print(f"  Hand errors: {r.hand_errors}")
        print(f"  Max drawdown: {r.max_drawdown:.1%}")
        print(f"  Score: {r.score:.2f}")

        print(f"\nResults saved to: {self.results_path}")
        cprint("=" * 70, "cyan")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Poker AutoOptimizer")
    parser.add_argument("--rounds", type=int, default=50)
    parser.add_argument("--hands", type=int, default=2000)
    parser.add_argument("--sessions", type=int, default=3)
    args = parser.parse_args()

    optimizer = PokerAutoOptimizer(num_hands=args.hands, num_sessions=args.sessions)
    optimizer.run(max_rounds=args.rounds)
