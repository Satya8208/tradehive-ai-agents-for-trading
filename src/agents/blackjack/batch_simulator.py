"""
Batch Simulator — Headless blackjack simulator for autoresearch optimization

Runs N hands with zero I/O (no voice, dashboard, sleep, cprint).
Reuses game_engine, card_counter, strategy_engine.

Usage:
    python -m src.agents.blackjack.batch_simulator
"""

import random
from dataclasses import dataclass, field
from typing import Optional

from .game_engine import BlackjackSimulator, GameRules
from .card_counter import CardCounter
from .strategy_engine import StrategyEngine, Hand as StratHand
from .betting_manager import BettingManager


@dataclass
class BatchResult:
    """Aggregate results from a batch simulation run"""
    hands_played: int = 0
    hands_won: int = 0
    hands_lost: int = 0
    hands_pushed: int = 0
    blackjacks: int = 0
    busts: int = 0
    doubles_won: int = 0
    splits: int = 0
    surrenders: int = 0
    total_bet: float = 0.0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    ruin_count: int = 0
    hands_wonged_out: int = 0


class HeadlessBetCalculator:
    """
    Pure-math bet sizing — no file I/O, no CSV logging.
    Extracts the calculation logic from BettingManager.
    """

    # Standard spread table (from BettingManager)
    SPREAD_TABLE = BettingManager.SPREAD_TABLE
    SPREAD_TABLE_AGGRESSIVE = BettingManager.SPREAD_TABLE_AGGRESSIVE

    def __init__(
        self,
        min_bet: float = 10.0,
        max_bet: float = 200.0,
        bankroll: float = 10000.0,
        kelly_fraction: float = 0.5,
        spread_ratio: float = 12.0,
        method: str = 'spread',
        bet_ramp_tc: float = 1.0,
    ):
        self.min_bet = min_bet
        self.max_bet = max_bet
        self.bankroll = bankroll
        self.kelly_fraction = kelly_fraction
        self.spread_ratio = spread_ratio
        self.method = method
        self.bet_ramp_tc = bet_ramp_tc

    def calculate_edge(self, true_count: float) -> float:
        """Estimate player edge: base -0.5% + 0.5% per TC"""
        return -0.005 + true_count * 0.005

    def get_bet(self, true_count: float) -> float:
        """Get bet size based on configured method"""
        if self.method == 'kelly':
            return self._kelly_bet(true_count)
        elif self.method == 'spread_aggressive':
            return self._spread_aggressive_bet(true_count)
        else:  # 'spread' default
            return self._spread_bet(true_count)

    def _kelly_bet(self, true_count: float) -> float:
        """Kelly Criterion bet sizing"""
        edge = self.calculate_edge(true_count)
        if edge <= 0:
            return self._clamp(self.min_bet)

        variance = 1.15
        kelly_optimal = edge / variance
        fractional = kelly_optimal * self.kelly_fraction
        bet = self.bankroll * fractional
        return self._clamp(bet)

    def _spread_bet(self, true_count: float) -> float:
        """Standard spread table lookup"""
        # Below ramp TC → min bet
        if true_count < self.bet_ramp_tc:
            return self._clamp(self.min_bet)

        tc_rounded = max(-5, min(6, round(true_count)))
        multiplier = self.SPREAD_TABLE.get(tc_rounded, 1.0)
        return self._clamp(self.min_bet * multiplier)

    def _spread_aggressive_bet(self, true_count: float) -> float:
        """Aggressive spread for poor penetration"""
        if true_count < self.bet_ramp_tc:
            return self._clamp(self.min_bet)

        tc_rounded = max(-5, min(6, round(true_count)))
        multiplier = self.SPREAD_TABLE_AGGRESSIVE.get(tc_rounded, 1.0)
        return self._clamp(self.min_bet * multiplier)

    def _clamp(self, bet: float) -> float:
        """Clamp bet to min/max and available bankroll"""
        max_allowed = min(self.max_bet, self.bankroll)
        return max(self.min_bet, min(bet, max_allowed))

    def update_bankroll(self, pnl: float) -> None:
        """Update bankroll after a hand"""
        self.bankroll += pnl


class BatchSimulator:
    """
    Headless blackjack simulator for running N hands without any I/O.

    Usage:
        sim = BatchSimulator(rules=GameRules(num_decks=4, penetration=0.50))
        result = sim.run(10000)
        print(f"P&L: ${result.total_pnl:+.2f}")
    """

    def __init__(
        self,
        rules: GameRules = None,
        counting_system: str = 'hi_lo',
        betting_method: str = 'spread',
        min_bet: float = 10.0,
        max_bet: float = 200.0,
        starting_bankroll: float = 10000.0,
        kelly_fraction: float = 0.5,
        spread_ratio: float = 12.0,
        use_deviations: bool = True,
        insurance_threshold: float = 3.0,
        wong_out_tc: float = -2.0,
        wong_in_tc: float = 1.0,
        bet_ramp_tc: float = 1.0,
        seed: Optional[int] = None,
    ):
        self.rules = rules or GameRules()
        self.counting_system = counting_system
        self.use_deviations = use_deviations
        self.insurance_threshold = insurance_threshold
        self.wong_out_tc = wong_out_tc
        self.wong_in_tc = wong_in_tc
        self.starting_bankroll = starting_bankroll
        self.seed = seed

        # Bet calculator (no file I/O)
        self.bet_calc = HeadlessBetCalculator(
            min_bet=min_bet,
            max_bet=max_bet,
            bankroll=starting_bankroll,
            kelly_fraction=kelly_fraction,
            spread_ratio=spread_ratio,
            method=betting_method,
            bet_ramp_tc=bet_ramp_tc,
        )

    def run(self, num_hands: int = 10000) -> BatchResult:
        """
        Run num_hands of blackjack and return aggregate results.

        If bankroll hits zero, increments ruin_count and resets bankroll
        to continue simulation for statistical significance.
        """
        # Save and restore global random state so we don't interfere with
        # the optimizer's random mutations
        saved_state = random.getstate()
        if self.seed is not None:
            random.seed(self.seed)

        # Initialize components
        simulator = BlackjackSimulator(self.rules)
        counter = CardCounter(self.counting_system, self.rules.num_decks)
        strategy = StrategyEngine(ai_model=None)

        result = BatchResult()
        peak_bankroll = self.starting_bankroll
        is_sitting_out = False

        for _ in range(num_hands):
            # Check shuffle
            if simulator.shoe_needs_shuffle:
                counter.reset()

            tc = counter.true_count

            # Wong-out / wong-in logic
            if is_sitting_out:
                if tc >= self.wong_in_tc:
                    is_sitting_out = False
                else:
                    result.hands_wonged_out += 1
                    # Simulate other players consuming ~5 cards per round
                    for _ in range(5):
                        if simulator.deck.cards_remaining > 0:
                            card = simulator.deck.deal()
                            counter.add_card(card)
                    # Check if shoe needs shuffle
                    if simulator.deck.needs_shuffle():
                        simulator.deck.shuffle()
                        counter.reset()
                        is_sitting_out = False  # Fresh shoe, come back
                    continue
            else:
                if tc < self.wong_out_tc:
                    is_sitting_out = True
                    result.hands_wonged_out += 1
                    continue

            # Check bankroll — can we still bet?
            if self.bet_calc.bankroll < self.bet_calc.min_bet:
                result.ruin_count += 1
                self.bet_calc.bankroll = self.starting_bankroll
                peak_bankroll = self.starting_bankroll

            # Get bet
            bet = self.bet_calc.get_bet(tc)

            # Deal
            state = simulator.new_round(bet)

            # If hand completes immediately (dealer/player blackjack)
            if state.is_complete:
                # Count all dealt cards (includes hole card on immediate completion)
                for card in state.cards_dealt:
                    counter.add_card(card)

                # Process results
                hand_pnl = sum(pnl for _, pnl in state.results)
                self._update_stats(result, state, hand_pnl)
                self.bet_calc.update_bankroll(hand_pnl)

                # Track drawdown
                if self.bet_calc.bankroll > peak_bankroll:
                    peak_bankroll = self.bet_calc.bankroll
                dd = (peak_bankroll - self.bet_calc.bankroll) / peak_bankroll if peak_bankroll > 0 else 0
                if dd > result.max_drawdown:
                    result.max_drawdown = dd

                continue

            # Play each player hand
            hand_idx = 0
            while hand_idx < len(state.player_hands):
                hand = state.player_hands[hand_idx]

                if simulator.is_hand_complete(hand_idx):
                    hand_idx += 1
                    continue

                # Get strategy action
                strat_hand = StratHand(cards=hand.cards[:])
                action, _ = strategy.get_action(
                    strat_hand,
                    state.dealer_upcard,
                    true_count=counter.true_count,
                    can_double=hand.can_double(simulator.rules),
                    can_split=hand.can_split(simulator.rules, simulator._count_splits()),
                    can_surrender=self.rules.late_surrender,
                    use_deviations=self.use_deviations,
                )

                # Execute action
                state = simulator.player_action(hand_idx, action)

                # Move to next hand if done
                if action in ['S', 'D', 'R'] or simulator.is_hand_complete(hand_idx):
                    hand_idx += 1

            # Play dealer
            state = simulator.play_dealer()

            # Count ALL cards dealt this round (clean approach — avoids split-counting bugs)
            for card in state.cards_dealt:
                counter.add_card(card)

            # Process results
            hand_pnl = sum(pnl for _, pnl in state.results)
            self._update_stats(result, state, hand_pnl)
            self.bet_calc.update_bankroll(hand_pnl)

            # Track drawdown
            if self.bet_calc.bankroll > peak_bankroll:
                peak_bankroll = self.bet_calc.bankroll
            dd = (peak_bankroll - self.bet_calc.bankroll) / peak_bankroll if peak_bankroll > 0 else 0
            if dd > result.max_drawdown:
                result.max_drawdown = dd

        # Restore global random state
        if self.seed is not None:
            random.setstate(saved_state)

        return result

    def _update_stats(self, result: BatchResult, state, hand_pnl: float) -> None:
        """Update batch result stats from a completed hand"""
        from .game_engine import GameResult

        for res, pnl in state.results:
            result.hands_played += 1
            result.total_pnl += pnl

            if res in (GameResult.WIN, GameResult.BLACKJACK):
                result.hands_won += 1
            elif res in (GameResult.LOSE, GameResult.BUST):
                result.hands_lost += 1
            elif res == GameResult.PUSH:
                result.hands_pushed += 1

            if res == GameResult.BLACKJACK:
                result.blackjacks += 1
            if res == GameResult.BUST:
                result.busts += 1
            if res == GameResult.SURRENDER:
                result.hands_lost += 1  # surrender is a loss

        result.total_bet += sum(h.bet for h in state.player_hands)


# Standalone test
if __name__ == "__main__":
    from termcolor import cprint
    import time

    cprint("\n=== Batch Simulator Test ===\n", "cyan", attrs=["bold"])

    rules = GameRules(num_decks=6, penetration=0.75)

    start = time.time()
    sim = BatchSimulator(
        rules=rules,
        counting_system='hi_lo',
        betting_method='spread',
        starting_bankroll=10000.0,
        seed=42,
    )
    result = sim.run(10000)
    elapsed = time.time() - start

    cprint(f"Hands played: {result.hands_played}", "white")
    cprint(f"Win rate: {result.hands_won / max(result.hands_played, 1):.1%}", "white")
    cprint(f"Total P&L: ${result.total_pnl:+.2f}", "green" if result.total_pnl > 0 else "red")
    cprint(f"Total bet: ${result.total_bet:,.0f}", "white")
    roi = result.total_pnl / result.total_bet if result.total_bet > 0 else 0
    cprint(f"ROI: {roi:.2%}", "white")
    cprint(f"Max drawdown: {result.max_drawdown:.1%}", "white")
    cprint(f"Ruin count: {result.ruin_count}", "white")
    cprint(f"Wonged out: {result.hands_wonged_out}", "white")
    cprint(f"Blackjacks: {result.blackjacks}", "white")
    cprint(f"Time: {elapsed:.2f}s ({result.hands_played / elapsed:.0f} hands/sec)", "cyan")
