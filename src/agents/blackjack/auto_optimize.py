"""
BJ AutoOptimizer — Autonomous Blackjack Strategy Optimizer

Applies Karpathy's autoresearch pattern to blackjack card counting:
1. Modify a parameter (counting system, bet spread, wong thresholds, etc.)
2. Simulate thousands of hands (fast — seconds, not hours)
3. Keep if improved, discard if not
4. Loop forever

Usage:
    python -m src.agents.blackjack.auto_optimize --rounds 50
    python -m src.agents.blackjack.auto_optimize --rounds 50 --profile online_4deck
    python -m src.agents.blackjack.auto_optimize --rounds 0  # infinite
"""

import argparse
import csv
import json
import random
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from termcolor import cprint

from .bj_scorer import BJScorer, BJParamSet, BJBacktestResult
from .casino_profiles import CASINO_PROFILES, apply_profile


# Parameter search space — what we can mutate
SEARCH_SPACE = {
    "penetration": (0.40, 0.85),
    "kelly_fraction": (0.10, 1.00),
    "spread_ratio": (4.0, 20.0),
    "bet_ramp_tc": (1.0, 3.0),
    "insurance_threshold": (1.5, 4.0),
    "wong_out_tc": (-3.0, -1.0),
    "wong_in_tc": (0.0, 2.0),
}

# Discrete parameters
DISCRETE_SPACE = {
    "counting_system": ["hi_lo", "omega_ii", "wong_halves"],
    "betting_method": ["kelly", "spread", "spread_aggressive"],
    "num_decks": [4, 6, 8],
    "use_deviations": [True, False],
    "dealer_hits_soft_17": [True, False],
}

# Minimum hands actually played (not wonged out) to accept a result
MIN_HANDS_THRESHOLD = 1000
MAX_DRAWDOWN_THRESHOLD = 0.50
MIN_PLAY_RATE = 0.35


class BJAutoOptimizer:
    """
    Autonomous parameter optimizer using the autoresearch pattern.

    Maintains a "best known" parameter set and explores mutations.
    Keeps improvements, discards regressions.
    """

    def __init__(
        self,
        num_hands: int = 10000,
        num_sessions: int = 3,
        profile: Optional[str] = None,
        results_path: str = "src/data/blackjack_agent/optimization_results.tsv",
        min_hands_threshold: Optional[int] = None,
        max_drawdown_threshold: float = MAX_DRAWDOWN_THRESHOLD,
        min_play_rate: float = MIN_PLAY_RATE,
    ):
        self.results_path = Path(results_path)
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile = profile
        total_samples = num_hands * max(num_sessions, 1)
        self.min_hands_threshold = min_hands_threshold or max(MIN_HANDS_THRESHOLD, int(total_samples * 0.5))
        self.max_drawdown_threshold = max_drawdown_threshold
        self.min_play_rate = min_play_rate

        # Set up search spaces (may be filtered by profile)
        self.search_space = dict(SEARCH_SPACE)
        self.discrete_space = dict(DISCRETE_SPACE)

        # Initialize best params
        self.best_params = BJParamSet()

        # Apply casino profile if specified
        if profile:
            self.search_space, self.discrete_space = apply_profile(
                self.best_params, profile,
                self.search_space, self.discrete_space,
            )

        # Scorer
        self.scorer = BJScorer(
            num_hands=num_hands,
            num_sessions=num_sessions,
        )

        # Score baseline
        cprint("Scoring baseline params...", "cyan")
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
                    "round", "score", "win_rate", "pnl", "hands",
                    "roi", "profit_per_hand", "max_drawdown", "ruin_rate",
                    "hourly_rate", "hourly_ci_low", "hourly_ci_high", "play_rate",
                    "wonged_out", "status", "description", "params_changed",
                    "params_snapshot",
                ])

        # Log baseline
        self._log_result(
            0, self.best_result, "baseline",
            "initial parameters", "{}", self._serialize_params(self.best_params)
        )

    def run(self, max_rounds: int = 0):
        """
        Run the optimization loop.

        max_rounds=0 means infinite (until interrupted).
        """
        cprint("=" * 70, "cyan")
        cprint("BJ AUTORESEARCH — Autonomous Blackjack Strategy Optimizer", "cyan", attrs=["bold"])
        if self.profile:
            cprint(f"Profile: {self.profile} — {CASINO_PROFILES[self.profile]['description']}", "cyan")
        cprint(f"Simulating {self.scorer.num_hands} hands x {self.scorer.num_sessions} sessions per round", "cyan")
        cprint(f"Search space: {len(self.search_space)} continuous + {len(self.discrete_space)} discrete params", "cyan")
        cprint(f"Baseline score: {self.best_score:.2f} "
               f"({self.best_result.win_rate:.1%} WR, "
               f"${self.best_result.total_pnl:+.0f} P&L, "
               f"${self.best_result.hourly_rate:+.2f}/hr)", "cyan")
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
        """Run a single experiment: mutate, score, keep/discard."""
        # Build strategy list based on available search spaces
        strategies = []
        if self.search_space:
            strategies.append("single_continuous")
        if self.discrete_space:
            strategies.append("single_discrete")
        if self.search_space:
            strategies.append("double_mutation")
        strategies.append("random_restart")

        strategy = random.choice(strategies)

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
                   f"{result.win_rate:.0%} WR | "
                   f"${result.total_pnl:+.0f} | "
                   f"${result.hourly_rate:+.1f}/hr | "
                   f"{description}", "green")
        else:
            status = "discard"
            self.discards += 1

            if not quality_ok:
                reason = quality_reason
            else:
                reason = f"score={result.score:.1f} vs best={self.best_score:.1f}"

            cprint(f"  R{self.round_num:3d} DISCARD "
                   f"score={result.score:.1f} | "
                   f"{result.win_rate:.0%} WR | "
                   f"${result.total_pnl:+.0f} | "
                   f"${result.hourly_rate:+.1f}/hr | "
                   f"{description} ({reason})", "red")

        self._log_result(
            self.round_num, result, status,
            description, json.dumps(changes), self._serialize_params(candidate)
        )

    def _passes_quality_gate(self, result: BJBacktestResult) -> Tuple[bool, str]:
        """Reject noisy or operationally unrealistic improvements."""
        if result.hands_played < self.min_hands_threshold:
            return False, f"too few hands ({result.hands_played} < {self.min_hands_threshold})"
        if result.hourly_rate_ci_low <= 0:
            return False, f"CI crosses zero (${result.hourly_rate_ci_low:+.2f}/hr low)"
        if result.max_drawdown > self.max_drawdown_threshold:
            return False, f"drawdown too high ({result.max_drawdown:.1%})"
        if result.play_rate < self.min_play_rate:
            return False, f"play rate too low ({result.play_rate:.1%})"
        return True, ""

    def _serialize_params(self, params: BJParamSet) -> str:
        """Persist a full snapshot so downstream tools can reload exact winners."""
        return json.dumps(vars(params), sort_keys=True)

    def _mutate_continuous(self) -> Tuple[BJParamSet, str, Dict]:
        """Mutate a single continuous parameter."""
        candidate = deepcopy(self.best_params)
        param = random.choice(list(self.search_space.keys()))
        lo, hi = self.search_space[param]

        old_val = getattr(candidate, param)
        # Gaussian mutation centered on current value
        sigma = (hi - lo) * 0.15
        new_val = max(lo, min(hi, old_val + random.gauss(0, sigma)))
        new_val = round(new_val, 3)

        setattr(candidate, param, new_val)

        description = f"{param}: {old_val:.3f} -> {new_val:.3f}"
        changes = {param: {"old": old_val, "new": new_val}}
        return candidate, description, changes

    def _mutate_discrete(self) -> Tuple[BJParamSet, str, Dict]:
        """Mutate a single discrete parameter."""
        candidate = deepcopy(self.best_params)
        param = random.choice(list(self.discrete_space.keys()))
        options = self.discrete_space[param]

        old_val = getattr(candidate, param)
        new_val = random.choice([v for v in options if v != old_val] or options)

        setattr(candidate, param, new_val)

        description = f"{param}: {old_val} -> {new_val}"
        changes = {param: {"old": str(old_val), "new": str(new_val)}}
        return candidate, description, changes

    def _mutate_double(self) -> Tuple[BJParamSet, str, Dict]:
        """Mutate two parameters at once."""
        candidate = deepcopy(self.best_params)
        changes = {}

        # First mutation: continuous
        param1 = random.choice(list(self.search_space.keys()))
        lo, hi = self.search_space[param1]
        old1 = getattr(candidate, param1)
        sigma = (hi - lo) * 0.15
        new1 = max(lo, min(hi, old1 + random.gauss(0, sigma)))
        new1 = round(new1, 3)
        setattr(candidate, param1, new1)
        changes[param1] = {"old": old1, "new": new1}

        # Second mutation: could be continuous or discrete
        if random.random() < 0.5 and self.discrete_space:
            param2 = random.choice(list(self.discrete_space.keys()))
            old2 = getattr(candidate, param2)
            new2 = random.choice(self.discrete_space[param2])
            setattr(candidate, param2, new2)
            changes[param2] = {"old": str(old2), "new": str(new2)}
        else:
            other_params = [p for p in self.search_space if p != param1]
            if other_params:
                param2 = random.choice(other_params)
                lo2, hi2 = self.search_space[param2]
                old2 = getattr(candidate, param2)
                sigma2 = (hi2 - lo2) * 0.15
                new2 = max(lo2, min(hi2, old2 + random.gauss(0, sigma2)))
                new2 = round(new2, 3)
                setattr(candidate, param2, new2)
                changes[param2] = {"old": old2, "new": new2}
            else:
                param2 = param1  # fallback

        description = f"{param1}={new1:.3f} + {param2}={changes.get(param2, {}).get('new', '?')}"
        return candidate, description, changes

    def _random_restart(self) -> Tuple[BJParamSet, str, Dict]:
        """Generate completely random parameters (exploration)."""
        candidate = deepcopy(self.best_params)  # preserve fixed/locked params
        changes = {}

        for param, (lo, hi) in self.search_space.items():
            val = round(random.uniform(lo, hi), 3)
            setattr(candidate, param, val)
            changes[param] = {"old": "baseline", "new": val}

        for param, options in self.discrete_space.items():
            val = random.choice(options)
            setattr(candidate, param, val)
            changes[param] = {"old": "baseline", "new": str(val)}

        description = "RANDOM RESTART"
        return candidate, description, changes

    def _log_result(self, round_num: int, result: BJBacktestResult,
                    status: str, description: str, params_json: str, snapshot_json: str):
        """Append result to TSV."""
        with open(self.results_path, "a", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow([
                round_num,
                f"{result.score:.2f}",
                f"{result.win_rate:.3f}",
                f"{result.total_pnl:.2f}",
                result.hands_played,
                f"{result.roi:.4f}",
                f"{result.profit_per_hand:.4f}",
                f"{result.max_drawdown:.3f}",
                f"{result.ruin_rate:.2f}",
                f"{result.hourly_rate:.2f}",
                f"{result.hourly_rate_ci_low:.2f}",
                f"{result.hourly_rate_ci_high:.2f}",
                f"{result.play_rate:.3f}",
                result.hands_wonged_out,
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

        rounds_completed = max(self.round_num - 1, 0) if self.round_num > 0 else 0
        print(f"Rounds: {rounds_completed}")
        print(f"Improvements: {self.improvements}")
        print(f"Discards: {self.discards}")
        print(f"Improvement rate: {self.improvements / max(rounds_completed, 1):.1%}")
        if elapsed > 0:
            print(f"Total time: {elapsed:.1f}s ({elapsed / max(rounds_completed, 1):.1f}s/round)")
        print()

        p = self.best_params
        print(f"BEST PARAMETERS (score={self.best_score:.2f}):")
        print(f"  counting_system:     {p.counting_system}")
        print(f"  betting_method:      {p.betting_method}")
        print(f"  num_decks:           {p.num_decks}")
        print(f"  penetration:         {p.penetration:.0%}")
        print(f"  use_deviations:      {p.use_deviations}")
        print(f"  dealer_hits_soft_17: {p.dealer_hits_soft_17}")
        print(f"  kelly_fraction:      {p.kelly_fraction:.2f}")
        print(f"  spread_ratio:        {p.spread_ratio:.1f}")
        print(f"  bet_ramp_tc:         {p.bet_ramp_tc:.1f}")
        print(f"  wong_out_tc:         {p.wong_out_tc:.1f}")
        print(f"  wong_in_tc:          {p.wong_in_tc:.1f}")
        print(f"  insurance_threshold: {p.insurance_threshold:.1f}")
        print()

        r = self.best_result
        print(f"BEST RESULT:")
        print(f"  Hands played: {r.hands_played} ({r.hands_wonged_out} wonged out)")
        print(f"  Win rate: {r.win_rate:.1%} ({r.hands_won}W / {r.hands_lost}L / {r.hands_pushed}P)")
        print(f"  Total P&L: ${r.total_pnl:+,.2f} on ${r.total_bet:,.0f} wagered")
        print(f"  ROI: {r.roi:.2%}")
        print(f"  Profit/hand: ${r.profit_per_hand:+.4f}")
        print(f"  Hourly rate: ${r.hourly_rate:+.2f}/hr (at {80} hands/hr)")
        print(f"  95% CI: ${r.hourly_rate_ci_low:+.2f} to ${r.hourly_rate_ci_high:+.2f}/hr")
        print(f"  Max drawdown: {r.max_drawdown:.1%}")
        print(f"  Ruin rate: {r.ruin_rate:.1%}")
        print(f"  Play rate: {r.play_rate:.1%}")
        print(f"  Score: {r.score:.2f}")

        print(f"\nResults saved to: {self.results_path}")
        cprint("=" * 70, "cyan")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="BJ AutoOptimizer — Autonomous Blackjack Strategy Optimizer"
    )
    parser.add_argument("--rounds", type=int, default=50,
                        help="Number of optimization rounds (0=infinite)")
    parser.add_argument("--hands", type=int, default=10000,
                        help="Hands per simulation session")
    parser.add_argument("--sessions", type=int, default=3,
                        help="Sessions per evaluation (different seeds)")
    parser.add_argument("--profile", type=str, default=None,
                        choices=list(CASINO_PROFILES.keys()),
                        help="Casino profile to lock game conditions")
    parser.add_argument("--output", type=str, default=None,
                        help="Custom output TSV path")
    args = parser.parse_args()

    optimizer = BJAutoOptimizer(
        num_hands=args.hands,
        num_sessions=args.sessions,
        profile=args.profile,
        results_path=args.output or "src/data/blackjack_agent/optimization_results.tsv",
    )
    optimizer.run(max_rounds=args.rounds)
