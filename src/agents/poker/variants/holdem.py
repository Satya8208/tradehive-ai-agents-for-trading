"""
Texas Hold'em Variant - Hold'em specific rules and utilities
Built with love by TradeHive
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict
from enum import Enum

import sys
from pathlib import Path
project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.poker.core.hand_evaluator import (
    Card, HandEvaluator, HandResult, Deck, Rank, Suit,
    RANK_NAMES, RANK_MAP
)


class Street(Enum):
    """Betting streets in Hold'em"""
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"


class Position(Enum):
    """Table positions (9-max)"""
    UTG = "UTG"      # Under The Gun
    UTG1 = "UTG+1"
    UTG2 = "UTG+2"
    MP = "MP"        # Middle Position
    MP2 = "MP+1"
    HJ = "HJ"        # Hijack
    CO = "CO"        # Cutoff
    BTN = "BTN"      # Button
    SB = "SB"        # Small Blind
    BB = "BB"        # Big Blind


# Position order for action (preflop vs postflop)
PREFLOP_ORDER = [Position.UTG, Position.UTG1, Position.UTG2, Position.MP,
                 Position.MP2, Position.HJ, Position.CO, Position.BTN,
                 Position.SB, Position.BB]

POSTFLOP_ORDER = [Position.SB, Position.BB, Position.UTG, Position.UTG1,
                  Position.UTG2, Position.MP, Position.MP2, Position.HJ,
                  Position.CO, Position.BTN]


@dataclass
class HoleCards:
    """Player's two hole cards in Hold'em"""
    cards: Tuple[Card, Card]

    def __str__(self) -> str:
        return f"{self.cards[0]}{self.cards[1]}"

    def pretty(self) -> str:
        return f"{self.cards[0].pretty()} {self.cards[1].pretty()}"

    @property
    def is_pair(self) -> bool:
        return self.cards[0].rank == self.cards[1].rank

    @property
    def is_suited(self) -> bool:
        return self.cards[0].suit == self.cards[1].suit

    @property
    def is_connected(self) -> bool:
        """Cards are consecutive ranks"""
        diff = abs(self.cards[0].rank - self.cards[1].rank)
        # Also check A-2 connection
        if {self.cards[0].rank, self.cards[1].rank} == {Rank.ACE, Rank.TWO}:
            return True
        return diff == 1

    @property
    def gap(self) -> int:
        """Number of gaps between cards (0 = connected)"""
        r1, r2 = self.cards[0].rank, self.cards[1].rank
        if {r1, r2} == {Rank.ACE, Rank.TWO}:
            return 0
        return abs(r1 - r2) - 1

    @property
    def high_card(self) -> Card:
        return max(self.cards, key=lambda c: c.rank)

    @property
    def low_card(self) -> Card:
        return min(self.cards, key=lambda c: c.rank)

    def notation(self) -> str:
        """
        Get standard hand notation like 'AKs', 'QJo', '88'
        """
        c1, c2 = sorted(self.cards, key=lambda c: c.rank, reverse=True)
        r1 = RANK_NAMES[c1.rank]
        r2 = RANK_NAMES[c2.rank]

        if self.is_pair:
            return f"{r1}{r2}"
        elif self.is_suited:
            return f"{r1}{r2}s"
        else:
            return f"{r1}{r2}o"

    @classmethod
    def from_notation(cls, notation: str, suit1: Suit = None, suit2: Suit = None) -> 'HoleCards':
        """
        Create hole cards from notation like 'AKs', 'QJo', '88'

        For suited hands, randomly assigns same suit if not specified.
        For offsuit hands, assigns different suits.
        For pairs, assigns different suits.
        """
        notation = notation.strip().upper()

        if len(notation) < 2:
            raise ValueError(f"Invalid notation: {notation}")

        # Parse ranks
        if notation[0] == '1' and notation[1] == '0':
            r1_str = 'T'
            rest = notation[2:]
        else:
            r1_str = notation[0]
            rest = notation[1:]

        if rest[0] == '1' and len(rest) > 1 and rest[1] == '0':
            r2_str = 'T'
            suffix = rest[2:] if len(rest) > 2 else ''
        else:
            r2_str = rest[0]
            suffix = rest[1:] if len(rest) > 1 else ''

        rank1 = RANK_MAP.get(r1_str)
        rank2 = RANK_MAP.get(r2_str)

        if rank1 is None or rank2 is None:
            raise ValueError(f"Invalid ranks in notation: {notation}")

        # Determine suits
        is_suited = 's' in suffix.lower()
        is_offsuit = 'o' in suffix.lower()
        is_pair = rank1 == rank2

        if suit1 is None or suit2 is None:
            if is_pair or is_offsuit:
                suit1 = suit1 or Suit.HEARTS
                suit2 = suit2 or Suit.DIAMONDS
            elif is_suited:
                suit1 = suit1 or Suit.HEARTS
                suit2 = suit1
            else:
                # Default to offsuit
                suit1 = suit1 or Suit.HEARTS
                suit2 = suit2 or Suit.DIAMONDS

        return cls((Card(rank1, suit1), Card(rank2, suit2)))

    @classmethod
    def from_strings(cls, card1: str, card2: str) -> 'HoleCards':
        """Create from two card strings like 'Ah', 'Ks'"""
        return cls((Card.from_string(card1), Card.from_string(card2)))


@dataclass
class Board:
    """Community cards in Hold'em"""
    cards: List[Card]

    def __str__(self) -> str:
        return " ".join(str(c) for c in self.cards)

    def pretty(self) -> str:
        return " ".join(c.pretty() for c in self.cards)

    @property
    def street(self) -> Street:
        n = len(self.cards)
        if n == 0:
            return Street.PREFLOP
        elif n == 3:
            return Street.FLOP
        elif n == 4:
            return Street.TURN
        elif n == 5:
            return Street.RIVER
        else:
            raise ValueError(f"Invalid board size: {n}")

    @property
    def flop(self) -> List[Card]:
        return self.cards[:3] if len(self.cards) >= 3 else []

    @property
    def turn(self) -> Optional[Card]:
        return self.cards[3] if len(self.cards) >= 4 else None

    @property
    def river(self) -> Optional[Card]:
        return self.cards[4] if len(self.cards) >= 5 else None

    @classmethod
    def from_strings(cls, *card_strings: str) -> 'Board':
        """Create from card strings like 'Ah', 'Ks', 'Qd'"""
        return cls([Card.from_string(s) for s in card_strings])

    @classmethod
    def empty(cls) -> 'Board':
        return cls([])


class HoldemVariant:
    """
    Texas Hold'em game rules and utilities
    """

    # Game constants
    HOLE_CARDS = 2
    BOARD_CARDS = 5
    FLOP_CARDS = 3
    MAX_PLAYERS = 10

    def __init__(self):
        self.evaluator = HandEvaluator()

    def evaluate_hand(self, hole_cards: HoleCards, board: Board) -> HandResult:
        """Evaluate a Hold'em hand"""
        cards = list(hole_cards.cards) + board.cards
        if len(cards) < 5:
            raise ValueError("Need at least 5 cards for evaluation")
        return self.evaluator.evaluate(list(hole_cards.cards), board.cards)

    def compare_hands(self, hand1: Tuple[HoleCards, Board],
                      hand2: Tuple[HoleCards, Board]) -> int:
        """
        Compare two hands

        Returns:
            -1 if hand1 wins
            0 if tie
            1 if hand2 wins
        """
        result1 = self.evaluate_hand(hand1[0], hand1[1])
        result2 = self.evaluate_hand(hand2[0], hand2[1])
        return self.evaluator.compare(result1, result2)

    def deal_hand(self, exclude: List[Card] = None) -> Tuple[HoleCards, Deck]:
        """Deal a random hole card hand, return remaining deck"""
        deck = Deck(exclude)
        deck.shuffle()
        cards = deck.deal(2)
        return HoleCards((cards[0], cards[1])), deck

    def deal_board(self, deck: Deck, street: Street) -> Board:
        """Deal community cards for a specific street"""
        if street == Street.PREFLOP:
            return Board.empty()
        elif street == Street.FLOP:
            return Board(deck.deal(3))
        elif street == Street.TURN:
            flop = deck.deal(3)
            turn = deck.deal(1)
            return Board(flop + turn)
        elif street == Street.RIVER:
            cards = deck.deal(5)
            return Board(cards)

    def get_outs(self, hole_cards: HoleCards, board: Board) -> List[Card]:
        """Get all cards that improve the hand"""
        return self.evaluator.get_outs(
            list(hole_cards.cards),
            board.cards
        )

    def calculate_outs_equity(self, num_outs: int, street: Street) -> float:
        """
        Calculate approximate equity from number of outs

        Uses the "Rule of 2 and 4":
        - Flop to River: outs * 4 (approximate %)
        - Turn to River: outs * 2 (approximate %)
        """
        if street == Street.FLOP:
            # Two cards to come
            return min(num_outs * 4, 100) / 100
        elif street == Street.TURN:
            # One card to come
            return min(num_outs * 2, 100) / 100
        else:
            return 0.0

    def is_drawing_hand(self, hole_cards: HoleCards, board: Board) -> Dict[str, bool]:
        """
        Check for various draws

        Returns dict with:
        - flush_draw: 4 to a flush
        - open_straight_draw: 8 outs to straight
        - gutshot: 4 outs to straight
        - combo_draw: flush + straight draw
        """
        if len(board.cards) < 3:
            return {
                'flush_draw': False,
                'open_straight_draw': False,
                'gutshot': False,
                'combo_draw': False
            }

        all_cards = list(hole_cards.cards) + board.cards

        # Check flush draw
        suit_counts = {}
        for card in all_cards:
            suit_counts[card.suit] = suit_counts.get(card.suit, 0) + 1

        flush_draw = max(suit_counts.values()) == 4

        # Check straight draws
        ranks = sorted(set(c.rank for c in all_cards))
        open_straight = False
        gutshot = False

        # Check for open-ended (4 consecutive)
        for i in range(len(ranks) - 3):
            if ranks[i + 3] - ranks[i] == 3:
                open_straight = True
                break

        # Check for gutshot (4 cards with one gap)
        for i in range(len(ranks) - 3):
            window = ranks[i:i + 4]
            if window[-1] - window[0] == 4:  # 4 rank span = one gap
                gaps = sum(1 for j in range(3) if window[j + 1] - window[j] > 1)
                if gaps == 1:
                    gutshot = True
                    break

        return {
            'flush_draw': flush_draw,
            'open_straight_draw': open_straight,
            'gutshot': gutshot and not open_straight,
            'combo_draw': flush_draw and (open_straight or gutshot)
        }

    def hand_category(self, notation: str) -> str:
        """
        Categorize a hand notation

        Returns: 'premium', 'strong', 'playable', 'marginal', 'trash'
        """
        notation = notation.upper().strip()

        # Premium hands
        premium = ['AA', 'KK', 'QQ', 'AKS', 'AKO']
        if any(notation.startswith(p.replace('S', '').replace('O', ''))
               and ('S' in p) == ('S' in notation)
               for p in premium):
            return 'premium'

        # Strong hands
        strong = ['JJ', 'TT', 'AQS', 'AQO', 'AJS', 'KQS']
        if any(notation == s or notation.replace('S', '') == s.replace('S', '')
               for s in strong):
            return 'strong'

        # Parse for more detailed analysis
        try:
            hole = HoleCards.from_notation(notation)
        except:
            return 'trash'

        high = max(hole.cards[0].rank, hole.cards[1].rank)
        low = min(hole.cards[0].rank, hole.cards[1].rank)

        # Pairs
        if hole.is_pair:
            if high >= Rank.NINE:
                return 'strong'
            elif high >= Rank.SIX:
                return 'playable'
            else:
                return 'marginal'

        # Suited connectors
        if hole.is_suited and hole.is_connected:
            if high >= Rank.NINE:
                return 'playable'
            else:
                return 'marginal'

        # Broadway cards (T+)
        if high >= Rank.TEN and low >= Rank.TEN:
            return 'playable' if hole.is_suited else 'marginal'

        # Ace-x suited
        if high == Rank.ACE and hole.is_suited:
            if low >= Rank.TEN:
                return 'strong'
            elif low >= Rank.FIVE:
                return 'playable'
            else:
                return 'marginal'

        # King-x suited
        if high == Rank.KING and hole.is_suited and low >= Rank.TEN:
            return 'playable'

        return 'trash'


# === Standalone Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n=== Hold'em Variant Test ===\n", "cyan", attrs=['bold'])

    holdem = HoldemVariant()

    # Test hole cards notation
    cprint("Hand Notation Tests:", "yellow")
    test_notations = ['AA', 'AKs', 'AKo', 'QJs', '72o', 'TT', 'T9s']
    for notation in test_notations:
        hole = HoleCards.from_notation(notation)
        category = holdem.hand_category(notation)
        cprint(f"  {notation} -> {hole.pretty()} | Category: {category}", "white")

    print()

    # Test hand evaluation
    cprint("Hand Evaluation:", "yellow")
    hole = HoleCards.from_strings("Ah", "Kh")
    board = Board.from_strings("Qh", "Jh", "Th", "2c", "3d")

    result = holdem.evaluate_hand(hole, board)
    cprint(f"  Hole: {hole.pretty()}", "white")
    cprint(f"  Board: {board.pretty()}", "white")
    cprint(f"  Result: {result.description}", "green", attrs=['bold'])

    print()

    # Test draw detection
    cprint("Draw Detection:", "yellow")
    hole = HoleCards.from_strings("Ah", "Kh")
    board = Board.from_strings("Qh", "Jc", "2h")

    draws = holdem.is_drawing_hand(hole, board)
    cprint(f"  Hole: {hole.pretty()}", "white")
    cprint(f"  Board: {board.pretty()}", "white")
    for draw_type, has_draw in draws.items():
        color = 'green' if has_draw else 'red'
        cprint(f"  {draw_type}: {has_draw}", color)

    print()

    # Test outs
    cprint("Outs Calculation:", "yellow")
    outs = holdem.get_outs(hole, board)
    equity = holdem.calculate_outs_equity(len(outs), Street.FLOP)
    cprint(f"  Outs: {len(outs)} cards", "white")
    cprint(f"  Approximate Equity: {equity*100:.1f}%", "green")
