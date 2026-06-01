"""
Preflop Engine - Position-based preflop strategy with GTO ranges
The foundation of profitable poker
Built with love by TradeHive
"""

from enum import Enum, IntEnum
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict
import json
import os
from pathlib import Path

import sys
project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.poker.core.hand_evaluator import Card, Rank, RANK_NAMES
from src.agents.poker.core.range_manager import Range
from src.agents.poker.core.poker_types import Position


class PreflopAction(Enum):
    """Possible preflop actions"""
    FOLD = "fold"
    CALL = "call"        # Limp or call
    RAISE = "raise"      # Open or raise
    THREE_BET = "3bet"   # Re-raise (3-bet)
    FOUR_BET = "4bet"    # Re-re-raise (4-bet)
    FIVE_BET = "5bet"    # 5-bet (usually all-in)
    ALL_IN = "all_in"


class FacingAction(Enum):
    """What action we're facing preflop"""
    UNOPENED = "unopened"       # No action, we can open
    LIMPED = "limped"           # Player(s) limped
    RAISED = "raised"           # Facing a raise (RFI)
    THREE_BET = "3bet"          # Facing 3-bet
    FOUR_BET = "4bet"           # Facing 4-bet
    FIVE_BET = "5bet"           # Facing 5-bet
    ALL_IN = "all_in"


@dataclass
class PreflopDecision:
    """Result of preflop analysis"""
    action: PreflopAction
    frequency: float           # How often to take this action (0-1)
    sizing: Optional[float]    # Bet sizing in BB (if applicable)
    reasoning: str             # Explanation
    range_strength: str        # Where hand falls in range (premium/strong/playable/marginal)
    alternative: Optional[PreflopAction] = None  # Mixed strategy alternative
    alt_frequency: float = 0.0


class PreflopEngine:
    """
    GTO-based preflop decision engine

    Handles:
    - RFI (Raise First In) by position
    - 3-bet ranges vs different positions
    - 4-bet/5-bet strategies
    - BB defense ranges
    - SB strategy
    """

    # === RAISE FIRST IN (RFI) RANGES BY POSITION ===
    # Percentage shown is approximate range % of all hands

    RFI_RANGES = {
        Position.UTG: {
            'range': "AA-77,AKo-AJo,KQo,AKs-ATs,KQs-KJs,QJs,JTs,T9s,98s",
            'sizing': 2.5,
            'percent': 12,
        },
        Position.UTG1: {
            'range': "AA-66,AKo-ATo,KQo-KJo,QJo,AKs-A9s,KQs-KTs,QJs-QTs,JTs,T9s,98s,87s",
            'sizing': 2.5,
            'percent': 14,
        },
        Position.UTG2: {
            'range': "AA-55,AKo-ATo,KQo-KJo,QJo,AKs-A8s,KQs-K9s,QJs-Q9s,JTs-J9s,T9s,98s,87s,76s",
            'sizing': 2.5,
            'percent': 16,
        },
        Position.MP: {
            'range': "AA-44,AKo-A9o,KQo-KTo,QJo-QTo,JTo,AKs-A5s,KQs-K8s,QJs-Q8s,JTs-J8s,T9s-T8s,98s-97s,87s,76s,65s",
            'sizing': 2.5,
            'percent': 20,
        },
        Position.MP2: {
            'range': "AA-33,AKo-A8o,KQo-K9o,QJo-Q9o,JTo-J9o,T9o,AKs-A4s,KQs-K7s,QJs-Q7s,JTs-J7s,T9s-T7s,98s-96s,87s-86s,76s-75s,65s,54s",
            'sizing': 2.5,
            'percent': 23,
        },
        Position.HJ: {
            'range': "AA-22,AKo-A7o,KQo-K9o,QJo-Q9o,JTo-J8o,T9o-T8o,98o,AKs-A2s,KQs-K5s,QJs-Q5s,JTs-J6s,T9s-T6s,98s-95s,87s-85s,76s-74s,65s-64s,54s,43s",
            'sizing': 2.5,
            'percent': 27,
        },
        Position.CO: {
            'range': "AA-22,AKo-A5o,KQo-K8o,QJo-Q8o,JTo-J8o,T9o-T8o,98o-97o,87o,AKs-A2s,KQs-K3s,QJs-Q3s,JTs-J4s,T9s-T5s,98s-94s,87s-84s,76s-74s,65s-63s,54s-53s,43s",
            'sizing': 2.5,
            'percent': 32,
        },
        Position.BTN: {
            'range': "AA-22,AKo-A2o,KQo-K5o,QJo-Q6o,JTo-J7o,T9o-T7o,98o-96o,87o-85o,76o-75o,65o,AKs-A2s,KQs-K2s,QJs-Q2s,JTs-J2s,T9s-T3s,98s-93s,87s-83s,76s-73s,65s-62s,54s-52s,43s-42s,32s",
            'sizing': 2.5,
            'percent': 48,
        },
        Position.SB: {
            'range': "AA-22,AKo-A7o,KQo-K9o,QJo-Q9o,JTo-J9o,T9o,AKs-A2s,KQs-K4s,QJs-Q6s,JTs-J6s,T9s-T6s,98s-96s,87s-85s,76s-74s,65s-64s,54s,43s",
            'sizing': 3.0,  # Larger sizing from SB
            'percent': 35,
        },
    }

    # === 3-BET RANGES (VS RFI FROM DIFFERENT POSITIONS) ===
    # Structure: defender_position -> {raiser_position: range}

    THREE_BET_RANGES = {
        Position.BTN: {
            Position.UTG: "AA-QQ,AKs,AKo",  # Tight vs UTG
            Position.MP: "AA-JJ,AKs-AQs,AKo",
            Position.CO: "AA-TT,AKs-AJs,KQs,AKo-AQo",
            'sizing': 3.0,  # Multiplier of open
        },
        Position.SB: {
            Position.UTG: "AA-QQ,AKs",
            Position.MP: "AA-JJ,AKs,AKo",
            Position.CO: "AA-TT,AKs-AQs,AKo",
            Position.BTN: "AA-99,AKs-ATs,KQs-KJs,AKo-AJo",  # Wider vs BTN
            'sizing': 3.5,
        },
        Position.BB: {
            Position.UTG: "AA-JJ,AKs,AKo",
            Position.MP: "AA-TT,AKs-AQs,AKo",
            Position.CO: "AA-88,AKs-ATs,KQs,AKo-AJo",
            Position.BTN: "AA-77,AKs-A9s,KQs-KTs,QJs,AKo-ATo,KQo",
            Position.SB: "AA-55,AKs-A7s,KQs-K9s,QJs-QTs,JTs,AKo-A9o,KQo-KJo,QJo",
            'sizing': 3.5,
        },
    }

    # === BB DEFENSE RANGES (VS VARIOUS POSITIONS) ===
    # These are CALLING ranges (not 3-betting)

    BB_DEFENSE_RANGES = {
        Position.UTG: {
            'call': "TT-22,AQs-A2s,KQs-K9s,QJs-Q9s,JTs-J9s,T9s,98s,87s,76s,65s,54s,AQo-ATo,KQo",
            'percent': 15,
        },
        Position.MP: {
            'call': "99-22,AJs-A2s,KQs-K7s,QJs-Q8s,JTs-J8s,T9s-T8s,98s-97s,87s-86s,76s-75s,65s,54s,AJo-A9o,KQo-KTo,QJo",
            'percent': 20,
        },
        Position.CO: {
            'call': "88-22,ATs-A2s,KJs-K5s,QTs-Q6s,JTs-J7s,T9s-T7s,98s-96s,87s-85s,76s-74s,65s-64s,54s,ATo-A8o,KJo-K9o,QJo-Q9o,JTo",
            'percent': 28,
        },
        Position.BTN: {
            'call': "77-22,A9s-A2s,KTs-K3s,Q9s-Q4s,J9s-J5s,T9s-T6s,98s-95s,87s-84s,76s-73s,65s-63s,54s-53s,43s,A9o-A5o,KTo-K7o,QTo-Q8o,JTo-J8o,T9o,98o",
            'percent': 40,
        },
        Position.SB: {
            'call': "66-22,A8s-A2s,K9s-K2s,Q8s-Q3s,J8s-J4s,T8s-T5s,97s-94s,86s-84s,75s-73s,64s-63s,53s-52s,A8o-A3o,K9o-K6o,Q9o-Q7o,J9o-J7o,T9o-T8o,98o",
            'percent': 45,
        },
    }

    # === 4-BET RANGES ===
    FOUR_BET_VALUE = "AA,KK,QQ,AKs"
    FOUR_BET_BLUFF = "A5s,A4s,76s,65s"  # Blockers + playability

    # === 5-BET/ALL-IN RANGES ===
    FIVE_BET_VALUE = "AA,KK"
    FIVE_BET_BLUFF = "AKs"  # Sometimes

    def __init__(self, custom_ranges: Dict = None):
        """
        Initialize with optional custom ranges

        Args:
            custom_ranges: Override default ranges for specific positions
        """
        self.custom_ranges = custom_ranges or {}
        self._load_chart_data()

    def _load_chart_data(self):
        """Load any external chart data"""
        # For now using embedded ranges, but can load from JSON files
        self.charts_loaded = True

    def get_rfi_decision(self, hole_cards: List[Card], position: Position) -> PreflopDecision:
        """
        Get raise-first-in decision for unopened pot

        Args:
            hole_cards: Two hole cards
            position: Our table position

        Returns:
            PreflopDecision with action and reasoning
        """
        hand_str = self._cards_to_notation(hole_cards)

        if position == Position.BB:
            return PreflopDecision(
                action=PreflopAction.CALL,
                frequency=1.0,
                sizing=None,
                reasoning="In BB with no raise - check option",
                range_strength="n/a"
            )

        if position not in self.RFI_RANGES:
            position = Position.MP  # Default to MP for unusual positions

        rfi_data = self.RFI_RANGES[position]
        rfi_range = Range.from_notation(rfi_data['range'])

        if self._hand_in_range(hole_cards, rfi_range):
            strength = self._classify_hand_strength(hole_cards, rfi_range)
            return PreflopDecision(
                action=PreflopAction.RAISE,
                frequency=1.0,
                sizing=rfi_data['sizing'],
                reasoning=f"Open from {position.name} with {hand_str} - in top {rfi_data['percent']}% range",
                range_strength=strength
            )
        else:
            return PreflopDecision(
                action=PreflopAction.FOLD,
                frequency=1.0,
                sizing=None,
                reasoning=f"Fold from {position.name} with {hand_str} - outside opening range",
                range_strength="weak"
            )

    def get_vs_raise_decision(self, hole_cards: List[Card], our_position: Position,
                               raiser_position: Position, raise_size: float = 2.5) -> PreflopDecision:
        """
        Get decision when facing an open raise

        Args:
            hole_cards: Our hole cards
            our_position: Our position
            raiser_position: Position of the raiser
            raise_size: Size of open in BB

        Returns:
            PreflopDecision
        """
        hand_str = self._cards_to_notation(hole_cards)

        # Check 3-bet range
        if our_position in self.THREE_BET_RANGES:
            three_bet_data = self.THREE_BET_RANGES[our_position]
            if raiser_position in three_bet_data:
                three_bet_range = Range.from_notation(three_bet_data[raiser_position])
                if self._hand_in_range(hole_cards, three_bet_range):
                    sizing = raise_size * three_bet_data['sizing']
                    return PreflopDecision(
                        action=PreflopAction.THREE_BET,
                        frequency=1.0,
                        sizing=sizing,
                        reasoning=f"3-bet {hand_str} vs {raiser_position.name} open to {sizing:.1f}bb",
                        range_strength="premium"
                    )

        # Check call range (BB defense)
        if our_position == Position.BB and raiser_position in self.BB_DEFENSE_RANGES:
            defense_data = self.BB_DEFENSE_RANGES[raiser_position]
            call_range = Range.from_notation(defense_data['call'])
            if self._hand_in_range(hole_cards, call_range):
                return PreflopDecision(
                    action=PreflopAction.CALL,
                    frequency=1.0,
                    sizing=None,
                    reasoning=f"Defend BB with {hand_str} vs {raiser_position.name}",
                    range_strength=self._classify_hand_strength(hole_cards, call_range)
                )

        # Default: fold
        return PreflopDecision(
            action=PreflopAction.FOLD,
            frequency=1.0,
            sizing=None,
            reasoning=f"Fold {hand_str} vs {raiser_position.name} open - outside 3bet/call range",
            range_strength="weak"
        )

    def get_vs_3bet_decision(self, hole_cards: List[Card], original_position: Position,
                              threebetter_position: Position) -> PreflopDecision:
        """
        Get decision when our open is 3-bet

        Args:
            hole_cards: Our hole cards
            original_position: Where we opened from
            threebetter_position: Who 3-bet us

        Returns:
            PreflopDecision
        """
        hand_str = self._cards_to_notation(hole_cards)

        # 4-bet value range
        value_range = Range.from_notation(self.FOUR_BET_VALUE)
        if self._hand_in_range(hole_cards, value_range):
            return PreflopDecision(
                action=PreflopAction.FOUR_BET,
                frequency=1.0,
                sizing=2.5,  # 2.5x the 3-bet
                reasoning=f"4-bet {hand_str} for value vs {threebetter_position.name} 3-bet",
                range_strength="premium"
            )

        # 4-bet bluff range (some frequency)
        bluff_range = Range.from_notation(self.FOUR_BET_BLUFF)
        if self._hand_in_range(hole_cards, bluff_range):
            return PreflopDecision(
                action=PreflopAction.FOUR_BET,
                frequency=0.3,  # Mixed strategy
                sizing=2.5,
                reasoning=f"4-bet {hand_str} as bluff vs {threebetter_position.name} (30% frequency)",
                range_strength="playable",
                alternative=PreflopAction.FOLD,
                alt_frequency=0.7
            )

        # Call with medium pairs and suited broadways
        call_range = Range.from_notation("JJ-99,AQs,AJs,KQs,AQo")
        if self._hand_in_range(hole_cards, call_range):
            return PreflopDecision(
                action=PreflopAction.CALL,
                frequency=1.0,
                sizing=None,
                reasoning=f"Call 3-bet with {hand_str} - strong but not 4-bet value",
                range_strength="strong"
            )

        return PreflopDecision(
            action=PreflopAction.FOLD,
            frequency=1.0,
            sizing=None,
            reasoning=f"Fold {hand_str} to 3-bet - outside continue range",
            range_strength="weak"
        )

    def get_vs_4bet_decision(self, hole_cards: List[Card]) -> PreflopDecision:
        """Get decision when facing a 4-bet"""
        hand_str = self._cards_to_notation(hole_cards)

        # 5-bet/shove value
        value_range = Range.from_notation(self.FIVE_BET_VALUE)
        if self._hand_in_range(hole_cards, value_range):
            return PreflopDecision(
                action=PreflopAction.ALL_IN,
                frequency=1.0,
                sizing=None,
                reasoning=f"5-bet all-in with {hand_str} - premium holding",
                range_strength="premium"
            )

        # Sometimes 5-bet bluff with AK
        if self._hand_in_range(hole_cards, Range.from_notation("AKs")):
            return PreflopDecision(
                action=PreflopAction.ALL_IN,
                frequency=0.5,
                sizing=None,
                reasoning=f"5-bet all-in with {hand_str} (50% frequency)",
                range_strength="strong",
                alternative=PreflopAction.CALL,
                alt_frequency=0.5
            )

        # Call with QQ, AKo
        call_range = Range.from_notation("QQ,AKo")
        if self._hand_in_range(hole_cards, call_range):
            return PreflopDecision(
                action=PreflopAction.CALL,
                frequency=1.0,
                sizing=None,
                reasoning=f"Call 4-bet with {hand_str} - strong but not 5-bet value",
                range_strength="strong"
            )

        return PreflopDecision(
            action=PreflopAction.FOLD,
            frequency=1.0,
            sizing=None,
            reasoning=f"Fold {hand_str} to 4-bet",
            range_strength="weak"
        )

    def get_decision(self, hole_cards: List[Card], our_position: Position,
                     facing: FacingAction, raiser_position: Position = None,
                     raise_size: float = 2.5) -> PreflopDecision:
        """
        Main entry point - get preflop decision based on situation

        Args:
            hole_cards: Our two cards
            our_position: Our seat
            facing: What action we're facing
            raiser_position: Where the raise came from (if applicable)
            raise_size: Size of raise in BB

        Returns:
            PreflopDecision
        """
        if facing == FacingAction.UNOPENED:
            return self.get_rfi_decision(hole_cards, our_position)

        elif facing == FacingAction.RAISED:
            return self.get_vs_raise_decision(hole_cards, our_position,
                                              raiser_position or Position.MP, raise_size)

        elif facing == FacingAction.THREE_BET:
            return self.get_vs_3bet_decision(hole_cards, our_position,
                                             raiser_position or Position.BB)

        elif facing == FacingAction.FOUR_BET:
            return self.get_vs_4bet_decision(hole_cards)

        elif facing == FacingAction.LIMPED:
            # Iso-raise or complete
            rfi_decision = self.get_rfi_decision(hole_cards, our_position)
            if rfi_decision.action == PreflopAction.RAISE:
                return PreflopDecision(
                    action=PreflopAction.RAISE,
                    frequency=1.0,
                    sizing=4.0,  # Larger iso-raise
                    reasoning=f"Iso-raise vs limper with {self._cards_to_notation(hole_cards)}",
                    range_strength=rfi_decision.range_strength
                )
            return rfi_decision

        elif facing in (FacingAction.FIVE_BET, FacingAction.ALL_IN):
            # Only call with nuts
            nuts_range = Range.from_notation("AA,KK")
            if self._hand_in_range(hole_cards, nuts_range):
                return PreflopDecision(
                    action=PreflopAction.ALL_IN,
                    frequency=1.0,
                    sizing=None,
                    reasoning=f"Call all-in with {self._cards_to_notation(hole_cards)}",
                    range_strength="premium"
                )
            return PreflopDecision(
                action=PreflopAction.FOLD,
                frequency=1.0,
                sizing=None,
                reasoning="Fold to all-in without AA/KK",
                range_strength="weak"
            )

        return PreflopDecision(
            action=PreflopAction.FOLD,
            frequency=1.0,
            sizing=None,
            reasoning="Unknown situation - default fold",
            range_strength="unknown"
        )

    def get_position_range(self, position: Position, facing: FacingAction = FacingAction.UNOPENED) -> Range:
        """Get the range for a position in a given situation"""
        if facing == FacingAction.UNOPENED and position in self.RFI_RANGES:
            return Range.from_notation(self.RFI_RANGES[position]['range'])
        return Range()

    def _cards_to_notation(self, cards: List[Card]) -> str:
        """Convert cards to standard notation like AKs or AKo"""
        if len(cards) != 2:
            return "??"

        c1, c2 = cards
        # Order by rank (higher first)
        if c2.rank > c1.rank:
            c1, c2 = c2, c1

        r1 = RANK_NAMES[c1.rank]
        r2 = RANK_NAMES[c2.rank]

        if c1.rank == c2.rank:
            return f"{r1}{r2}"
        elif c1.suit == c2.suit:
            return f"{r1}{r2}s"
        else:
            return f"{r1}{r2}o"

    def _hand_in_range(self, cards: List[Card], range_obj: Range) -> bool:
        """Check if a hand is in a range"""
        notation = self._cards_to_notation(cards)
        # Use the __contains__ method of Range class
        return notation in range_obj

    def _classify_hand_strength(self, cards: List[Card], reference_range: Range) -> str:
        """Classify hand strength within a range"""
        notation = self._cards_to_notation(cards)

        # Premium hands
        if notation in ["AA", "KK", "QQ", "AKs", "AKo"]:
            return "premium"

        # Strong hands
        if notation in ["JJ", "TT", "AQs", "AQo", "AJs", "KQs"]:
            return "strong"

        # Playable
        if notation[0] in "AKQJT" or (len(notation) >= 2 and notation[:2] in ["99", "88", "77"]):
            return "playable"

        return "marginal"


# === Standalone Test ===
if __name__ == "__main__":
    from termcolor import cprint
    from src.agents.poker.core.hand_evaluator import Card, Rank, Suit

    cprint("\n=== Preflop Engine Test ===\n", "cyan", attrs=['bold'])

    engine = PreflopEngine()

    # Test hands
    test_hands = [
        ([Card(Rank.ACE, Suit.SPADES), Card(Rank.ACE, Suit.HEARTS)], Position.UTG),
        ([Card(Rank.KING, Suit.HEARTS), Card(Rank.QUEEN, Suit.HEARTS)], Position.BTN),
        ([Card(Rank.SEVEN, Suit.CLUBS), Card(Rank.TWO, Suit.DIAMONDS)], Position.MP),
        ([Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.SPADES)], Position.CO),
    ]

    cprint("RFI Decisions:", "yellow")
    for cards, pos in test_hands:
        decision = engine.get_rfi_decision(cards, pos)
        hand_str = engine._cards_to_notation(cards)
        color = 'green' if decision.action != PreflopAction.FOLD else 'red'
        cprint(f"  {hand_str} from {pos.name}: {decision.action.value.upper()}", color)
        if decision.sizing:
            cprint(f"    Size: {decision.sizing}bb | {decision.reasoning}", "white")

    print()
    cprint("Vs Raise Decisions (facing UTG open):", "yellow")
    raiser = Position.UTG

    test_hands_vs_raise = [
        ([Card(Rank.ACE, Suit.SPADES), Card(Rank.ACE, Suit.HEARTS)], Position.BTN),
        ([Card(Rank.JACK, Suit.SPADES), Card(Rank.JACK, Suit.HEARTS)], Position.BB),
        ([Card(Rank.NINE, Suit.HEARTS), Card(Rank.EIGHT, Suit.HEARTS)], Position.BB),
    ]

    for cards, pos in test_hands_vs_raise:
        decision = engine.get_vs_raise_decision(cards, pos, raiser)
        hand_str = engine._cards_to_notation(cards)
        color = 'green' if decision.action != PreflopAction.FOLD else 'red'
        cprint(f"  {hand_str} vs UTG from {pos.name}: {decision.action.value.upper()}", color)
        cprint(f"    {decision.reasoning}", "white")

    print()
    cprint("Range Sizes by Position:", "yellow")
    for pos in [Position.UTG, Position.MP, Position.CO, Position.BTN, Position.SB]:
        if pos in engine.RFI_RANGES:
            data = engine.RFI_RANGES[pos]
            cprint(f"  {pos.name}: ~{data['percent']}% of hands", "white")

    print()
    cprint("BB Defense Range vs BTN:", "yellow")
    if Position.BTN in engine.BB_DEFENSE_RANGES:
        data = engine.BB_DEFENSE_RANGES[Position.BTN]
        cprint(f"  Call ~{data['percent']}% of hands", "white")
