"""
Equity Calculator - Monte Carlo simulation for hand vs range equity
The heart of poker decision-making
Built with love by TradeHive
"""

import random
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict
from concurrent.futures import ThreadPoolExecutor
import time

import sys
from pathlib import Path
project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.poker.core.hand_evaluator import (
    Card, HandEvaluator, Deck, Rank, Suit, HandResult
)
from src.agents.poker.core.range_manager import Range


@dataclass
class EquityResult:
    """Result of equity calculation"""
    equity: float              # Win + tie/2 probability
    win_rate: float            # Pure win probability
    tie_rate: float            # Tie probability
    loss_rate: float           # Loss probability
    simulations: int           # Number of simulations run
    confidence: float          # Statistical confidence
    time_ms: int               # Calculation time in ms
    breakdown: Optional[Dict]  # Detailed breakdown by hand type


class EquityCalculator:
    """
    Monte Carlo equity calculator for poker hands

    Calculates equity through simulation:
    1. Sample opponent hand(s) from range(s)
    2. Complete the board with remaining deck
    3. Evaluate all hands
    4. Track wins/ties/losses
    5. Return equity = wins + ties/2
    """

    def __init__(self, evaluator: HandEvaluator = None):
        self.evaluator = evaluator or HandEvaluator()

    def hand_vs_hand(self, hero: List[Card], villain: List[Card],
                     board: List[Card] = None,
                     iterations: int = 10000) -> EquityResult:
        """
        Calculate equity of one hand vs another

        Args:
            hero: Hero's hole cards
            villain: Villain's hole cards
            board: Community cards (can be partial)
            iterations: Number of runouts to simulate

        Returns:
            EquityResult with equity breakdown
        """
        start_time = time.time()
        board = board or []

        # Cards already dealt
        known_cards = set(hero + villain + board)

        wins = ties = losses = 0
        cards_needed = 5 - len(board)

        for _ in range(iterations):
            # Create deck without known cards
            deck = Deck(list(known_cards))
            deck.shuffle()

            # Complete board
            runout = deck.deal(cards_needed)
            full_board = board + runout

            # Evaluate hands
            hero_result = self.evaluator.evaluate(hero, full_board)
            villain_result = self.evaluator.evaluate(villain, full_board)

            # Compare
            comparison = self.evaluator.compare(hero_result, villain_result)
            if comparison < 0:
                wins += 1
            elif comparison > 0:
                losses += 1
            else:
                ties += 1

        total = wins + ties + losses
        equity = (wins + ties * 0.5) / total

        elapsed_ms = int((time.time() - start_time) * 1000)

        return EquityResult(
            equity=equity,
            win_rate=wins / total,
            tie_rate=ties / total,
            loss_rate=losses / total,
            simulations=iterations,
            confidence=self._confidence(total),
            time_ms=elapsed_ms,
            breakdown=None
        )

    def hand_vs_range(self, hero: List[Card], villain_range: Range,
                      board: List[Card] = None,
                      iterations: int = 10000) -> EquityResult:
        """
        Calculate equity of a hand vs a range

        Args:
            hero: Hero's hole cards
            villain_range: Villain's range
            board: Community cards (can be partial)
            iterations: Number of simulations

        Returns:
            EquityResult with equity breakdown
        """
        start_time = time.time()
        board = board or []

        known_cards = set(hero + board)

        wins = ties = losses = 0
        cards_needed = 5 - len(board)

        # Track breakdown by hand type
        breakdown = {}

        for _ in range(iterations):
            # Sample villain hand from range (avoiding known cards)
            attempts = 0
            while attempts < 100:
                v1, v2 = villain_range.sample()
                if v1 not in known_cards and v2 not in known_cards:
                    break
                attempts += 1

            if attempts >= 100:
                continue  # Skip if can't find valid hand

            villain = [v1, v2]
            all_known = known_cards | {v1, v2}

            # Create deck and complete board
            deck = Deck(list(all_known))
            deck.shuffle()

            runout = deck.deal(cards_needed) if cards_needed > 0 else []
            full_board = board + runout

            # Evaluate hands
            hero_result = self.evaluator.evaluate(hero, full_board)
            villain_result = self.evaluator.evaluate(villain, full_board)

            # Compare
            comparison = self.evaluator.compare(hero_result, villain_result)
            if comparison < 0:
                wins += 1
            elif comparison > 0:
                losses += 1
            else:
                ties += 1

            # Track vs specific hands for breakdown
            hand_key = f"{v1}{v2}"
            if hand_key not in breakdown:
                breakdown[hand_key] = {'w': 0, 't': 0, 'l': 0}
            if comparison < 0:
                breakdown[hand_key]['w'] += 1
            elif comparison > 0:
                breakdown[hand_key]['l'] += 1
            else:
                breakdown[hand_key]['t'] += 1

        total = wins + ties + losses
        if total == 0:
            return EquityResult(0.5, 0.33, 0.34, 0.33, 0, 0, 0, None)

        equity = (wins + ties * 0.5) / total

        elapsed_ms = int((time.time() - start_time) * 1000)

        return EquityResult(
            equity=equity,
            win_rate=wins / total,
            tie_rate=ties / total,
            loss_rate=losses / total,
            simulations=total,
            confidence=self._confidence(total),
            time_ms=elapsed_ms,
            breakdown=breakdown
        )

    def range_vs_range(self, hero_range: Range, villain_range: Range,
                       board: List[Card] = None,
                       iterations: int = 10000) -> EquityResult:
        """
        Calculate equity of one range vs another

        Useful for analyzing preflop spots and range balance.

        Args:
            hero_range: Hero's range
            villain_range: Villain's range
            board: Community cards (can be partial)
            iterations: Number of simulations

        Returns:
            EquityResult
        """
        start_time = time.time()
        board = board or []

        board_set = set(board)
        wins = ties = losses = 0
        cards_needed = 5 - len(board)

        for _ in range(iterations):
            # Sample hero hand
            attempts = 0
            while attempts < 50:
                h1, h2 = hero_range.sample()
                if h1 not in board_set and h2 not in board_set:
                    break
                attempts += 1
            if attempts >= 50:
                continue

            hero = [h1, h2]
            known = board_set | {h1, h2}

            # Sample villain hand
            attempts = 0
            while attempts < 50:
                v1, v2 = villain_range.sample()
                if v1 not in known and v2 not in known:
                    break
                attempts += 1
            if attempts >= 50:
                continue

            villain = [v1, v2]
            all_known = known | {v1, v2}

            # Complete board
            deck = Deck(list(all_known))
            deck.shuffle()

            runout = deck.deal(cards_needed) if cards_needed > 0 else []
            full_board = board + runout

            # Evaluate
            hero_result = self.evaluator.evaluate(hero, full_board)
            villain_result = self.evaluator.evaluate(villain, full_board)

            comparison = self.evaluator.compare(hero_result, villain_result)
            if comparison < 0:
                wins += 1
            elif comparison > 0:
                losses += 1
            else:
                ties += 1

        total = wins + ties + losses
        if total == 0:
            return EquityResult(0.5, 0.33, 0.34, 0.33, 0, 0, 0, None)

        equity = (wins + ties * 0.5) / total

        elapsed_ms = int((time.time() - start_time) * 1000)

        return EquityResult(
            equity=equity,
            win_rate=wins / total,
            tie_rate=ties / total,
            loss_rate=losses / total,
            simulations=total,
            confidence=self._confidence(total),
            time_ms=elapsed_ms,
            breakdown=None
        )

    def multiway_equity(self, hero: List[Card],
                        villain_ranges: List[Range],
                        board: List[Card] = None,
                        iterations: int = 10000) -> EquityResult:
        """
        Calculate equity in a multiway pot

        Args:
            hero: Hero's hole cards
            villain_ranges: List of villain ranges
            board: Community cards
            iterations: Number of simulations

        Returns:
            EquityResult (hero's equity vs all opponents)
        """
        start_time = time.time()
        board = board or []

        known = set(hero + board)
        wins = ties = losses = 0
        cards_needed = 5 - len(board)

        for _ in range(iterations):
            # Sample hands for each villain
            villain_hands = []
            current_known = set(known)

            valid = True
            for v_range in villain_ranges:
                attempts = 0
                while attempts < 50:
                    v1, v2 = v_range.sample()
                    if v1 not in current_known and v2 not in current_known:
                        villain_hands.append([v1, v2])
                        current_known.add(v1)
                        current_known.add(v2)
                        break
                    attempts += 1
                if attempts >= 50:
                    valid = False
                    break

            if not valid:
                continue

            # Complete board
            deck = Deck(list(current_known))
            deck.shuffle()

            runout = deck.deal(cards_needed) if cards_needed > 0 else []
            full_board = board + runout

            # Evaluate all hands
            hero_result = self.evaluator.evaluate(hero, full_board)
            villain_results = [
                self.evaluator.evaluate(v, full_board) for v in villain_hands
            ]

            # Check if hero beats all villains
            hero_wins = all(
                self.evaluator.compare(hero_result, v) < 0
                for v in villain_results
            )
            hero_ties = not hero_wins and any(
                self.evaluator.compare(hero_result, v) == 0
                for v in villain_results
            ) and all(
                self.evaluator.compare(hero_result, v) <= 0
                for v in villain_results
            )

            if hero_wins:
                wins += 1
            elif hero_ties:
                ties += 1
            else:
                losses += 1

        total = wins + ties + losses
        if total == 0:
            return EquityResult(0.5, 0.33, 0.34, 0.33, 0, 0, 0, None)

        # In multiway pots, ties are split
        num_players = len(villain_ranges) + 1
        equity = (wins + ties / num_players) / total

        elapsed_ms = int((time.time() - start_time) * 1000)

        return EquityResult(
            equity=equity,
            win_rate=wins / total,
            tie_rate=ties / total,
            loss_rate=losses / total,
            simulations=total,
            confidence=self._confidence(total),
            time_ms=elapsed_ms,
            breakdown=None
        )

    def fold_equity(self, bet_size: float, pot_size: float,
                    villain_continue_range: Range,
                    villain_total_range: Range) -> float:
        """
        Estimate fold equity based on villain's continuing range

        Args:
            bet_size: Our bet
            pot_size: Current pot
            villain_continue_range: Hands villain continues with
            villain_total_range: Villain's full range before our bet

        Returns:
            Fold equity as decimal
        """
        continue_combos = villain_continue_range.combo_count()
        total_combos = villain_total_range.combo_count()

        if total_combos == 0:
            return 0.0

        continue_freq = continue_combos / total_combos
        return 1 - continue_freq

    def _confidence(self, n: int) -> float:
        """
        Calculate confidence level based on sample size

        With n samples, 95% CI is approximately ± 1/sqrt(n)
        """
        if n <= 0:
            return 0.0
        margin = 1 / (n ** 0.5)
        # Return confidence as inverse of margin (capped at 99%)
        return min(0.99, 1 - margin)

    def quick_equity(self, hero_notation: str, villain_notation: str,
                     board_str: str = "", iterations: int = 5000) -> float:
        """
        Quick equity calculation from notation strings

        Args:
            hero_notation: Hero hand like "AhKs"
            villain_notation: Villain range like "QQ+,AKs"
            board_str: Board like "Qh Jc 2d"
            iterations: Simulations to run

        Returns:
            Equity as decimal
        """
        from src.agents.poker.core.hand_evaluator import Card

        # Parse hero
        hero_cards = hero_notation.replace(" ", "")
        h1 = Card.from_string(hero_cards[:2])
        h2 = Card.from_string(hero_cards[2:])
        hero = [h1, h2]

        # Parse villain range
        villain_range = Range.from_notation(villain_notation)

        # Parse board
        board = []
        if board_str.strip():
            for card_str in board_str.split():
                if card_str.strip():
                    board.append(Card.from_string(card_str))

        result = self.hand_vs_range(hero, villain_range, board, iterations)
        return result.equity


# === Standalone Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n=== Equity Calculator Test ===\n", "cyan", attrs=['bold'])

    calc = EquityCalculator()

    # Test hand vs hand
    cprint("Hand vs Hand:", "yellow")
    hero = [Card.from_string("As"), Card.from_string("Ah")]
    villain = [Card.from_string("Ks"), Card.from_string("Kh")]

    result = calc.hand_vs_hand(hero, villain, iterations=10000)
    cprint(f"  AA vs KK preflop", "white")
    cprint(f"  Equity: {result.equity*100:.1f}%", "green")
    cprint(f"  Win: {result.win_rate*100:.1f}% | Tie: {result.tie_rate*100:.1f}% | Lose: {result.loss_rate*100:.1f}%", "white")
    cprint(f"  ({result.simulations} sims, {result.time_ms}ms)", "cyan")

    print()

    # With board
    cprint("Hand vs Hand (with flop):", "yellow")
    board = [
        Card.from_string("Qh"),
        Card.from_string("Jc"),
        Card.from_string("Td")
    ]
    result = calc.hand_vs_hand(hero, villain, board, iterations=10000)
    cprint(f"  AA vs KK on Qh Jc Td", "white")
    cprint(f"  Equity: {result.equity*100:.1f}%", "green")

    print()

    # Test hand vs range
    cprint("Hand vs Range:", "yellow")
    hero = [Card.from_string("Ah"), Card.from_string("Kh")]
    villain_range = Range.from_notation("QQ+,AKs,AKo")

    result = calc.hand_vs_range(hero, villain_range, iterations=10000)
    cprint(f"  AKs vs {{QQ+,AK}}", "white")
    cprint(f"  Equity: {result.equity*100:.1f}%", "green")
    cprint(f"  ({result.simulations} sims, {result.time_ms}ms)", "cyan")

    print()

    # Test range vs range
    cprint("Range vs Range:", "yellow")
    hero_range = Range.from_notation("AA,KK,QQ,AKs")
    villain_range = Range.from_notation("TT+,AQs+,AKo")

    result = calc.range_vs_range(hero_range, villain_range, iterations=10000)
    cprint(f"  Premium (AA-QQ,AKs) vs Top 5% (TT+,AQs+,AKo)", "white")
    cprint(f"  Equity: {result.equity*100:.1f}%", "green")

    print()

    # Quick equity test
    cprint("Quick Equity (helper function):", "yellow")
    equity = calc.quick_equity("AhKh", "QQ-TT,AQs+", "Qh Jc 2d")
    cprint(f"  AKhh vs {{QQ-TT,AQs+}} on QhJc2d", "white")
    cprint(f"  Equity: {equity*100:.1f}%", "green")
