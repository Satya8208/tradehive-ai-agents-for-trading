"""
BJ Scorer — ParamSet + scoring for blackjack autoresearch

Mirrors the pattern from polymarket_trader/backtest_scorer.py:
- BJParamSet: all tunable parameters
- BJBacktestResult: metrics from simulation
- BJScorer: runs batch simulator, returns scored result

Usage:
    python -m src.agents.blackjack.bj_scorer
"""

import math
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .batch_simulator import BatchSimulator, BatchResult
from .game_engine import GameRules


@dataclass
class BJParamSet:
    """All tunable parameters for blackjack autoresearch"""

    # === Continuous parameters (optimized) ===
    penetration: float = 0.50               # 0.40–0.85
    kelly_fraction: float = 0.50            # 0.10–1.00
    spread_ratio: float = 12.0              # 4.0–20.0
    bet_ramp_tc: float = 1.0                # 1.0–3.0
    insurance_threshold: float = 3.0        # 1.5–4.0 (reserved for v2)
    wong_out_tc: float = -2.0               # -3.0–-1.0
    wong_in_tc: float = 1.0                 # 0.0–2.0

    # === Discrete parameters (optimized) ===
    counting_system: str = 'hi_lo'          # hi_lo | omega_ii | wong_halves
    betting_method: str = 'spread'          # kelly | spread | spread_aggressive
    num_decks: int = 6                      # 4 | 6 | 8
    use_deviations: bool = True             # True | False
    dealer_hits_soft_17: bool = True        # True | False

    # === Fixed parameters (not in search space) ===
    min_bet: float = 10.0
    max_bet: float = 200.0
    starting_bankroll: float = 10000.0
    blackjack_pays: float = 1.5
    double_after_split: bool = True
    late_surrender: bool = True


@dataclass
class BJBacktestResult:
    """Metrics from a blackjack simulation evaluation"""
    hands_played: int = 0
    hands_won: int = 0
    hands_lost: int = 0
    hands_pushed: int = 0
    blackjacks: int = 0
    total_bet: float = 0.0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    roi: float = 0.0
    profit_per_hand: float = 0.0
    hourly_rate: float = 0.0               # at 80 hands/hour
    max_drawdown: float = 0.0
    ruin_rate: float = 0.0
    hands_wonged_out: int = 0
    play_rate: float = 0.0
    session_hourly_rates: List[float] = field(default_factory=list)
    hourly_rate_stddev: float = 0.0
    hourly_rate_ci_low: float = 0.0
    hourly_rate_ci_high: float = 0.0
    score: float = 0.0


HANDS_PER_HOUR = 80  # typical live BJ pace


class BJScorer:
    """
    Scores a BJParamSet by running batch simulations.

    Runs multiple sessions with different seeds for statistical reliability,
    then computes a composite score balancing profit, risk, and volume.
    """

    def __init__(
        self,
        num_hands: int = 10000,
        num_sessions: int = 3,
        base_seed: int = 42,
    ):
        self.num_hands = num_hands
        self.num_sessions = num_sessions
        self.base_seed = base_seed

    def score(self, params: BJParamSet) -> BJBacktestResult:
        """Run simulation(s) and return scored result."""

        rules = GameRules(
            num_decks=params.num_decks,
            dealer_hits_soft_17=params.dealer_hits_soft_17,
            blackjack_pays=params.blackjack_pays,
            penetration=params.penetration,
            double_after_split=params.double_after_split,
            late_surrender=params.late_surrender,
        )

        # Accumulate across sessions
        total_hands = 0
        total_won = 0
        total_lost = 0
        total_pushed = 0
        total_bjs = 0
        total_bet = 0.0
        total_pnl = 0.0
        total_wonged = 0
        max_dd = 0.0
        total_ruins = 0
        session_hourly_rates: List[float] = []

        for session_idx in range(self.num_sessions):
            seed = self.base_seed + session_idx

            sim = BatchSimulator(
                rules=rules,
                counting_system=params.counting_system,
                betting_method=params.betting_method,
                min_bet=params.min_bet,
                max_bet=params.max_bet,
                starting_bankroll=params.starting_bankroll,
                kelly_fraction=params.kelly_fraction,
                spread_ratio=params.spread_ratio,
                use_deviations=params.use_deviations,
                insurance_threshold=params.insurance_threshold,
                wong_out_tc=params.wong_out_tc,
                wong_in_tc=params.wong_in_tc,
                bet_ramp_tc=params.bet_ramp_tc,
                seed=seed,
            )

            batch = sim.run(self.num_hands)

            total_hands += batch.hands_played
            total_won += batch.hands_won
            total_lost += batch.hands_lost
            total_pushed += batch.hands_pushed
            total_bjs += batch.blackjacks
            total_bet += batch.total_bet
            total_pnl += batch.total_pnl
            total_wonged += batch.hands_wonged_out
            total_ruins += batch.ruin_count
            if batch.max_drawdown > max_dd:
                max_dd = batch.max_drawdown
            if batch.hands_played > 0:
                session_hourly_rates.append((batch.total_pnl / batch.hands_played) * HANDS_PER_HOUR)
            else:
                session_hourly_rates.append(0.0)

        # Build result
        result = BJBacktestResult()
        result.hands_played = total_hands
        result.hands_won = total_won
        result.hands_lost = total_lost
        result.hands_pushed = total_pushed
        result.blackjacks = total_bjs
        result.total_bet = total_bet
        result.total_pnl = total_pnl
        result.hands_wonged_out = total_wonged
        result.max_drawdown = max_dd
        result.ruin_rate = total_ruins / self.num_sessions if self.num_sessions > 0 else 0
        result.session_hourly_rates = session_hourly_rates

        # Derived metrics
        if total_hands > 0:
            result.win_rate = total_won / total_hands
            result.profit_per_hand = total_pnl / total_hands
            result.hourly_rate = result.profit_per_hand * HANDS_PER_HOUR
        if total_bet > 0:
            result.roi = total_pnl / total_bet
        total_attempted = total_hands + total_wonged
        if total_attempted > 0:
            result.play_rate = total_hands / total_attempted
        if len(session_hourly_rates) > 1:
            result.hourly_rate_stddev = statistics.stdev(session_hourly_rates)
            margin = 1.96 * result.hourly_rate_stddev / math.sqrt(len(session_hourly_rates))
            result.hourly_rate_ci_low = result.hourly_rate - margin
            result.hourly_rate_ci_high = result.hourly_rate + margin
        elif session_hourly_rates:
            result.hourly_rate_ci_low = result.hourly_rate
            result.hourly_rate_ci_high = result.hourly_rate

        # Composite score
        result.score = self._compute_score(result, params.min_bet)
        return result

    def _compute_score(self, result: BJBacktestResult, min_bet: float) -> float:
        """
        Composite score balancing profitability and risk.

        Components:
        1. profit_per_hand (primary — in bet units)
        2. Drawdown penalty (penalize strategies that risk ruin)
        3. Volume bonus (reward strategies that actually play)
        """
        if result.hands_played == 0:
            return -999.0

        # Normalize profit per hand to bet units
        pph_units = result.profit_per_hand / min_bet

        # Base score: profit per hand × 1000
        base = pph_units * 1000

        # Survival factor: penalize high drawdown (0.0 → 1.0, perfect = 1.0)
        survival_factor = max(1.0 - result.max_drawdown, 0.1)

        # Ruin penalty: exponential penalty for ruin
        ruin_penalty = (1.0 - result.ruin_rate) ** 2

        # Volume factor: penalize excessive wonging out (>50% of total hands attempted)
        if result.play_rate > 0:
            volume_factor = min(result.play_rate / 0.5, 1.0)
        else:
            volume_factor = 0.0

        score = base * survival_factor * ruin_penalty * volume_factor
        return round(score, 2)


# Standalone test
if __name__ == "__main__":
    from termcolor import cprint
    import time

    cprint("\n=== BJ Scorer Test ===\n", "cyan", attrs=["bold"])

    scorer = BJScorer(num_hands=10000, num_sessions=3, base_seed=42)
    params = BJParamSet()

    cprint(f"Testing default params: {params.counting_system}, {params.betting_method}, "
           f"{params.num_decks} decks, {params.penetration:.0%} pen", "white")

    start = time.time()
    result = scorer.score(params)
    elapsed = time.time() - start

    cprint(f"\nResults ({result.hands_played} hands, {elapsed:.1f}s):", "yellow")
    cprint(f"  Win rate:       {result.win_rate:.1%}", "white")
    cprint(f"  Total P&L:      ${result.total_pnl:+,.2f}", "green" if result.total_pnl > 0 else "red")
    cprint(f"  ROI:            {result.roi:.2%}", "white")
    cprint(f"  Profit/hand:    ${result.profit_per_hand:+.4f}", "white")
    cprint(f"  Hourly rate:    ${result.hourly_rate:+.2f}/hr", "white")
    cprint(f"  95% CI:         ${result.hourly_rate_ci_low:+.2f} to ${result.hourly_rate_ci_high:+.2f}/hr", "white")
    cprint(f"  Max drawdown:   {result.max_drawdown:.1%}", "white")
    cprint(f"  Ruin rate:      {result.ruin_rate:.1%}", "white")
    cprint(f"  Play rate:      {result.play_rate:.1%}", "white")
    cprint(f"  Wonged out:     {result.hands_wonged_out}", "white")
    cprint(f"  SCORE:          {result.score:.2f}", "cyan", attrs=["bold"])

    # Also test a bad config (flat betting, no counting)
    print()
    cprint("Testing flat betting (no advantage):", "yellow")
    flat_params = BJParamSet(
        counting_system='hi_lo',
        betting_method='spread',
        use_deviations=False,
        wong_out_tc=-99.0,  # never wong out
        wong_in_tc=-99.0,
        bet_ramp_tc=99.0,   # never ramp (always min bet)
    )
    flat_result = scorer.score(flat_params)
    cprint(f"  P&L: ${flat_result.total_pnl:+,.2f} | Score: {flat_result.score:.2f}", "red")
