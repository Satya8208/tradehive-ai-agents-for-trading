"""
Postflop Engine - Board-dependent decision making
The art of playing after the flop
Built with love by TradeHive
"""

from enum import Enum
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict
from collections import Counter
import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.poker.core.hand_evaluator import Card, HandResult, HandRank, HandEvaluator
from src.agents.poker.core.board_analyzer import BoardAnalyzer, BoardTexture, DrawType
from src.agents.poker.core.odds_calculator import OddsCalculator
from src.agents.poker.core.equity_calculator import EquityCalculator
from src.agents.poker.core.range_manager import Range
from src.agents.poker.core.poker_types import Street, PostflopAction


class HandCategory(Enum):
    """Hand strength categories for decision making"""
    NUTS = "nuts"                    # Best possible hand
    VERY_STRONG = "very_strong"      # 2nd/3rd nuts
    STRONG = "strong"                # Top pair+, overpair
    MEDIUM = "medium"                # Middle pair, weak top pair
    WEAK = "weak"                    # Bottom pair, A-high
    DRAW = "draw"                    # Drawing hands
    TRASH = "trash"                  # No equity hands


@dataclass
class PostflopDecision:
    """Result of postflop analysis"""
    action: PostflopAction
    frequency: float
    sizing_fraction: Optional[float]  # Fraction of pot (if betting)
    reasoning: str
    hand_category: HandCategory
    equity: float
    pot_odds: Optional[float]
    ev: Optional[float]
    alternative: Optional[PostflopAction] = None
    alt_frequency: float = 0.0


class PostflopEngine:
    """
    GTO-influenced postflop decision engine

    Handles:
    - C-betting strategy
    - Check-raise construction
    - Value betting
    - Bluff catching
    - Drawing decisions
    """

    # C-bet frequencies by texture (IP = In Position)
    CBET_FREQUENCIES = {
        BoardTexture.DRY: {
            'ip_freq': 0.70,
            'ip_size': 0.33,
            'oop_freq': 0.60,
            'oop_size': 0.50,
        },
        BoardTexture.SEMI_DRY: {
            'ip_freq': 0.65,
            'ip_size': 0.50,
            'oop_freq': 0.50,
            'oop_size': 0.66,
        },
        BoardTexture.WET: {
            'ip_freq': 0.50,
            'ip_size': 0.66,
            'oop_freq': 0.40,
            'oop_size': 0.75,
        },
        BoardTexture.MONOTONE: {
            'ip_freq': 0.45,
            'ip_size': 0.75,
            'oop_freq': 0.35,
            'oop_size': 0.75,
        },
        BoardTexture.PAIRED: {
            'ip_freq': 0.60,
            'ip_size': 0.33,
            'oop_freq': 0.45,
            'oop_size': 0.50,
        },
    }

    def __init__(self):
        self.evaluator = HandEvaluator()
        self.board_analyzer = BoardAnalyzer()
        self.odds_calc = OddsCalculator()
        self.equity_calc = EquityCalculator()

    def _hero_draw_profile(self, hole_cards: List[Card], board: List[Card]) -> Dict[str, int | bool]:
        """Detect actual hero draws instead of inheriting generic board texture draws."""
        if not hole_cards or not board:
            return {"flush_draw": False, "oesd": False, "gutshot": False, "outs": 0}

        hole_ranks = {int(card.rank) for card in hole_cards}
        all_ranks = set(hole_ranks) | {int(card.rank) for card in board}

        if 14 in all_ranks:
            all_ranks.add(1)
        if 14 in hole_ranks:
            hole_ranks.add(1)

        flush_draw = False
        all_suits = Counter(card.suit for card in hole_cards + board)
        hole_suits = Counter(card.suit for card in hole_cards)
        for suit, count in all_suits.items():
            if count == 4 and hole_suits.get(suit, 0) > 0:
                flush_draw = True
                break

        oesd_missing = set()
        gutshot = False
        for start in range(1, 11):
            window = set(range(start, start + 5))
            present = window & all_ranks
            missing = window - all_ranks
            if len(present) != 4 or len(missing) != 1:
                continue
            if not (window & hole_ranks):
                continue

            missing_rank = next(iter(missing))
            if missing_rank in {start, start + 4}:
                oesd_missing.add(missing_rank)
            else:
                gutshot = True

        oesd = len(oesd_missing) >= 2
        if oesd:
            gutshot = False

        outs = 0
        if flush_draw:
            outs += 9
        if oesd:
            outs += 8
        elif gutshot:
            outs += 4

        return {
            "flush_draw": flush_draw,
            "oesd": oesd,
            "gutshot": gutshot,
            "outs": outs,
        }

    def analyze_hand_strength(self, hole_cards: List[Card], board: List[Card]) -> Tuple[HandCategory, HandResult]:
        """
        Categorize hand strength relative to board

        Returns:
            (HandCategory, HandResult)
        """
        result = self.evaluator.evaluate(hole_cards, board)
        analysis = self.board_analyzer.analyze(board)
        hero_draws = self._hero_draw_profile(hole_cards, board)

        # Get nut hands for comparison
        nut_hands = analysis.nut_hands[:3] if analysis.nut_hands else []

        # Check if we have the nuts or near-nuts
        if result.rank == HandRank.STRAIGHT_FLUSH:
            return HandCategory.NUTS, result

        if result.rank == HandRank.FOUR_OF_A_KIND:
            return HandCategory.NUTS, result

        if result.rank == HandRank.FULL_HOUSE:
            # Check if it's the best full house
            if result.description in nut_hands[:1]:
                return HandCategory.NUTS, result
            return HandCategory.VERY_STRONG, result

        if result.rank == HandRank.FLUSH:
            # Nut flush vs non-nut
            if result.kickers and result.kickers[0].value >= 14:  # Ace-high flush
                return HandCategory.VERY_STRONG, result
            return HandCategory.STRONG, result

        if result.rank == HandRank.STRAIGHT:
            # Nut straight check
            if len(board) >= 3:
                return HandCategory.STRONG, result

        if result.rank == HandRank.THREE_OF_A_KIND:
            return HandCategory.STRONG, result

        if result.rank == HandRank.TWO_PAIR:
            return HandCategory.STRONG, result

        if result.rank == HandRank.ONE_PAIR:
            # Evaluate pair strength relative to the board
            pair_rank = result.cards[0].rank if result.cards else None
            hole_ranks = sorted([c.rank for c in hole_cards], reverse=True)
            board_ranks = sorted([c.rank for c in board], reverse=True)

            if board_ranks and pair_rank:
                # Check if pair is made with BOTH hole cards (pocket pair = overpair/underpair)
                is_pocket_pair = (hole_ranks[0] == hole_ranks[1])

                if is_pocket_pair and pair_rank > board_ranks[0]:
                    # Overpair (e.g., QQ on J-7-3)
                    return HandCategory.STRONG, result
                elif pair_rank >= board_ranks[0]:
                    # Top pair — check kicker
                    kicker = hole_ranks[0] if hole_ranks[1] == pair_rank else hole_ranks[1]
                    if kicker.value >= 12:  # Q+ kicker = TPTK/TPGK
                        return HandCategory.STRONG, result
                    elif kicker.value >= 9:  # 9+ kicker = decent top pair
                        return HandCategory.MEDIUM, result
                    else:
                        return HandCategory.MEDIUM, result
                elif is_pocket_pair and pair_rank >= board_ranks[1] if len(board_ranks) > 1 else False:
                    # Middle pocket pair (e.g., 99 on K-7-3 — underpair to top but over middle)
                    num_overcards = sum(1 for br in board_ranks if br > pair_rank)
                    if num_overcards >= 2:
                        return HandCategory.WEAK, result
                    return HandCategory.MEDIUM, result
                elif len(board_ranks) > 1 and pair_rank >= board_ranks[1]:
                    # Middle pair
                    return HandCategory.WEAK, result
                else:
                    # Bottom pair or underpair
                    return HandCategory.WEAK, result

        # Check for draws
        if hero_draws["flush_draw"] or hero_draws["oesd"] or hero_draws["gutshot"]:
            return HandCategory.DRAW, result

        return HandCategory.TRASH, result

    def get_cbet_decision(self, hole_cards: List[Card], board: List[Card],
                          pot_size: float, in_position: bool = True,
                          is_preflop_aggressor: bool = True) -> PostflopDecision:
        """
        Get c-bet or check decision on flop

        Args:
            hole_cards: Our cards
            board: Flop cards (3)
            pot_size: Current pot
            in_position: Are we in position?
            is_preflop_aggressor: Did we raise preflop?

        Returns:
            PostflopDecision
        """
        analysis = self.board_analyzer.analyze(board)
        hero_draws = self._hero_draw_profile(hole_cards, board)
        hand_cat, hand_result = self.analyze_hand_strength(hole_cards, board)

        texture = analysis.texture
        cbet_params = self.CBET_FREQUENCIES.get(texture, self.CBET_FREQUENCIES[BoardTexture.WET])

        pos_key = 'ip' if in_position else 'oop'
        base_freq = cbet_params[f'{pos_key}_freq']
        sizing = cbet_params[f'{pos_key}_size']

        # Adjust frequency based on hand strength
        if hand_cat in (HandCategory.NUTS, HandCategory.VERY_STRONG, HandCategory.STRONG):
            # Always bet value hands
            return PostflopDecision(
                action=PostflopAction.BET_MEDIUM if sizing >= 0.5 else PostflopAction.BET_SMALL,
                frequency=1.0,
                sizing_fraction=sizing,
                reasoning=f"Value bet with {hand_cat.value} hand on {texture.value} board",
                hand_category=hand_cat,
                equity=0.75,  # Estimate
                pot_odds=None,
                ev=pot_size * 0.3  # Rough EV estimate
            )

        elif hand_cat == HandCategory.MEDIUM:
            # Bet for protection and value
            return PostflopDecision(
                action=PostflopAction.BET_MEDIUM if sizing >= 0.5 else PostflopAction.BET_SMALL,
                frequency=base_freq + 0.1,
                sizing_fraction=sizing,
                reasoning=f"Value/protection bet with {hand_result.description}",
                hand_category=hand_cat,
                equity=0.55,
                pot_odds=None,
                ev=pot_size * 0.15,
                alternative=PostflopAction.CHECK,
                alt_frequency=1 - (base_freq + 0.1)
            )

        elif hand_cat == HandCategory.DRAW:
            # Semi-bluff with draws
            if hero_draws["flush_draw"] or hero_draws["oesd"] or hero_draws["gutshot"]:
                return PostflopDecision(
                    action=PostflopAction.BET_MEDIUM,
                    frequency=base_freq,
                    sizing_fraction=sizing,
                    reasoning="Semi-bluff with strong draw",
                    hand_category=hand_cat,
                    equity=0.40,
                    pot_odds=None,
                    ev=pot_size * 0.1,
                    alternative=PostflopAction.CHECK,
                    alt_frequency=1 - base_freq
                )

        elif hand_cat == HandCategory.WEAK:
            # Sometimes bluff, sometimes give up
            return PostflopDecision(
                action=PostflopAction.CHECK,
                frequency=1 - (base_freq * 0.3),
                sizing_fraction=None,
                reasoning="Check back weak hand",
                hand_category=hand_cat,
                equity=0.25,
                pot_odds=None,
                ev=0,
                alternative=PostflopAction.BET_SMALL,
                alt_frequency=base_freq * 0.3
            )

        # Trash hands - mostly give up, occasional bluff
        bluff_freq = base_freq * 0.2
        return PostflopDecision(
            action=PostflopAction.CHECK,
            frequency=1 - bluff_freq,
            sizing_fraction=None,
            reasoning="Give up with air",
            hand_category=hand_cat,
            equity=0.10,
            pot_odds=None,
            ev=0,
            alternative=PostflopAction.BET_SMALL,
            alt_frequency=bluff_freq
        )

    def get_facing_bet_decision(self, hole_cards: List[Card], board: List[Card],
                                 pot_size: float, bet_size: float,
                                 villain_range: Range = None) -> PostflopDecision:
        """
        Decide when facing a bet

        Args:
            hole_cards: Our cards
            board: Board cards
            pot_size: Pot before bet
            bet_size: Bet we're facing
            villain_range: Estimated villain range

        Returns:
            PostflopDecision
        """
        hand_cat, hand_result = self.analyze_hand_strength(hole_cards, board)
        analysis = self.board_analyzer.analyze(board)
        hero_draws = self._hero_draw_profile(hole_cards, board)

        # Calculate pot odds
        pot_odds_result = self.odds_calc.pot_odds(bet_size, pot_size)
        required_equity = pot_odds_result.break_even_equity

        # Calculate Equity: God Mode vs Heuristic
        if villain_range:
            # GOD MODE: Real Monte Carlo Simulation
            eq_result = self.equity_calc.hand_vs_range(
                hole_cards, villain_range, board, iterations=1000
            )
            estimated_equity = eq_result.equity
            equity_source = "Simulated"
        else:
            # Heuristic Mode
            equity_source = "Estimated"
            if hand_cat == HandCategory.NUTS:
                estimated_equity = 0.95
            elif hand_cat == HandCategory.VERY_STRONG:
                estimated_equity = 0.85
            elif hand_cat == HandCategory.STRONG:
                estimated_equity = 0.70
            elif hand_cat == HandCategory.MEDIUM:
                estimated_equity = 0.50
            elif hand_cat == HandCategory.WEAK:
                estimated_equity = 0.30
            elif hand_cat == HandCategory.DRAW:
                outs = hero_draws["outs"]
                cards_to_come = 5 - len(board)
                estimated_equity = self.odds_calc.outs_to_equity(outs, cards_to_come)
            else:
                estimated_equity = 0.10

        # Calculate EV of calling
        ev_call = self.odds_calc.ev_call(bet_size, pot_size, estimated_equity)

        # Decision based on equity vs pot odds
        if hand_cat in (HandCategory.NUTS, HandCategory.VERY_STRONG):
            # Raise for value
            raise_size = bet_size * 2.5
            return PostflopDecision(
                action=PostflopAction.RAISE,
                frequency=0.7,
                sizing_fraction=raise_size / pot_size,
                reasoning=f"Raise for value with {hand_result.description} ({equity_source} Eq: {estimated_equity*100:.1f}%)",
                hand_category=hand_cat,
                equity=estimated_equity,
                pot_odds=required_equity,
                ev=ev_call * 2,
                alternative=PostflopAction.CALL,
                alt_frequency=0.3
            )

        elif estimated_equity >= required_equity:
            # Profitable call
            return PostflopDecision(
                action=PostflopAction.CALL,
                frequency=1.0,
                sizing_fraction=None,
                reasoning=f"Call - {equity_source} Equity {estimated_equity*100:.1f}% > Required {required_equity*100:.1f}%",
                hand_category=hand_cat,
                equity=estimated_equity,
                pot_odds=required_equity,
                ev=ev_call
            )

        elif hand_cat == HandCategory.DRAW:
            # Consider implied odds for draws
            implied_odds = self.odds_calc.implied_odds(bet_size, pot_size, pot_size * 2)
            if estimated_equity >= implied_odds.break_even_equity:
                return PostflopDecision(
                    action=PostflopAction.CALL,
                    frequency=1.0,
                    sizing_fraction=None,
                    reasoning=f"Call draw with implied odds ({estimated_equity*100:.0f}%)",
                    hand_category=hand_cat,
                    equity=estimated_equity,
                    pot_odds=implied_odds.break_even_equity,
                    ev=ev_call
                )

        # Fold
        return PostflopDecision(
            action=PostflopAction.FOLD,
            frequency=1.0,
            sizing_fraction=None,
            reasoning=f"Fold - Equity {estimated_equity*100:.1f}% < Required {required_equity*100:.1f}%",
            hand_category=hand_cat,
            equity=estimated_equity,
            pot_odds=required_equity,
            ev=0
        )

    def get_river_value_bet(self, hole_cards: List[Card], board: List[Card],
                            pot_size: float, effective_stack: float) -> PostflopDecision:
        """
        River value betting decision

        Args:
            hole_cards: Our cards
            board: Full board (5 cards)
            pot_size: Current pot
            effective_stack: Remaining stack

        Returns:
            PostflopDecision
        """
        hand_cat, hand_result = self.analyze_hand_strength(hole_cards, board)

        spr = self.odds_calc.spr(effective_stack, pot_size)

        if hand_cat in (HandCategory.NUTS, HandCategory.VERY_STRONG):
            # Big value bet
            if spr < 1:
                return PostflopDecision(
                    action=PostflopAction.ALL_IN,
                    frequency=1.0,
                    sizing_fraction=effective_stack / pot_size,
                    reasoning=f"Jam river with {hand_result.description}",
                    hand_category=hand_cat,
                    equity=0.95,
                    pot_odds=None,
                    ev=pot_size * 0.5
                )
            else:
                sizing = min(1.0, 0.75)
                return PostflopDecision(
                    action=PostflopAction.BET_LARGE,
                    frequency=1.0,
                    sizing_fraction=sizing,
                    reasoning=f"Value bet river with {hand_result.description}",
                    hand_category=hand_cat,
                    equity=0.85,
                    pot_odds=None,
                    ev=pot_size * sizing * 0.6
                )

        elif hand_cat == HandCategory.STRONG:
            # Medium value bet
            sizing = 0.50
            return PostflopDecision(
                action=PostflopAction.BET_MEDIUM,
                frequency=0.8,
                sizing_fraction=sizing,
                reasoning=f"Thin value with {hand_result.description}",
                hand_category=hand_cat,
                equity=0.65,
                pot_odds=None,
                ev=pot_size * sizing * 0.3,
                alternative=PostflopAction.CHECK,
                alt_frequency=0.2
            )

        elif hand_cat == HandCategory.MEDIUM:
            # Check for showdown value
            return PostflopDecision(
                action=PostflopAction.CHECK,
                frequency=0.9,
                sizing_fraction=None,
                reasoning="Check medium hand for showdown",
                hand_category=hand_cat,
                equity=0.45,
                pot_odds=None,
                ev=0,
                alternative=PostflopAction.BET_SMALL,
                alt_frequency=0.1
            )

        # Bluff candidates
        previous_street = board[:-1] if len(board) == 5 else board
        hero_draws = self._hero_draw_profile(hole_cards, previous_street)
        has_missed_draw = hand_cat == HandCategory.TRASH and hero_draws["outs"] > 0

        if has_missed_draw:
            bluff_freq = 0.25  # Some bluffing frequency
            return PostflopDecision(
                action=PostflopAction.BET_MEDIUM,
                frequency=bluff_freq,
                sizing_fraction=0.66,
                reasoning="Bluff with missed draw",
                hand_category=hand_cat,
                equity=0.10,
                pot_odds=None,
                ev=pot_size * 0.66 * -0.5,  # Negative EV if called
                alternative=PostflopAction.CHECK,
                alt_frequency=1 - bluff_freq
            )

        return PostflopDecision(
            action=PostflopAction.CHECK,
            frequency=1.0,
            sizing_fraction=None,
            reasoning="Check and give up",
            hand_category=hand_cat,
            equity=0.10,
            pot_odds=None,
            ev=0
        )


# === Standalone Test ===
if __name__ == "__main__":
    from termcolor import cprint
    from src.agents.poker.core.hand_evaluator import Card, Rank, Suit

    cprint("\n=== Postflop Engine Test ===\n", "cyan", attrs=['bold'])

    engine = PostflopEngine()

    # Test hands and boards
    hero = [Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)]
    flop = [Card(Rank.ACE, Suit.HEARTS), Card(Rank.SEVEN, Suit.CLUBS), Card(Rank.TWO, Suit.DIAMONDS)]

    cprint("Hand Strength Analysis:", "yellow")
    cat, result = engine.analyze_hand_strength(hero, flop)
    cprint(f"  AKo on A72r: {cat.value} ({result.description})", "white")

    print()
    cprint("C-bet Decision:", "yellow")
    decision = engine.get_cbet_decision(hero, flop, pot_size=10, in_position=True)
    cprint(f"  Action: {decision.action.value}", "green" if decision.action != PostflopAction.CHECK else "white")
    cprint(f"  Frequency: {decision.frequency*100:.0f}%", "white")
    if decision.sizing_fraction:
        cprint(f"  Sizing: {decision.sizing_fraction*100:.0f}% pot", "white")
    cprint(f"  Reasoning: {decision.reasoning}", "cyan")

    print()
    cprint("Facing Bet Decision:", "yellow")
    decision = engine.get_facing_bet_decision(hero, flop, pot_size=10, bet_size=6)
    cprint(f"  Facing 60% pot bet with top pair...", "white")
    cprint(f"  Action: {decision.action.value}", "green" if decision.action != PostflopAction.FOLD else "red")
    cprint(f"  {decision.reasoning}", "cyan")

    # Draw scenario
    print()
    cprint("Draw Scenario:", "yellow")
    draw_hand = [Card(Rank.QUEEN, Suit.HEARTS), Card(Rank.JACK, Suit.HEARTS)]
    draw_flop = [Card(Rank.TEN, Suit.HEARTS), Card(Rank.TWO, Suit.HEARTS), Card(Rank.FIVE, Suit.CLUBS)]

    cat, result = engine.analyze_hand_strength(draw_hand, draw_flop)
    cprint(f"  QJhh on Th2h5c: {cat.value}", "white")

    decision = engine.get_facing_bet_decision(draw_hand, draw_flop, pot_size=10, bet_size=5)
    cprint(f"  Facing 50% pot: {decision.action.value}", "green" if decision.action != PostflopAction.FOLD else "red")
    cprint(f"  {decision.reasoning}", "cyan")
