"""
Hand Evaluator - Core poker hand ranking engine
Evaluates and compares poker hands with 7462 distinct rankings
Built with love by TradeHive
"""

from enum import IntEnum
from dataclasses import dataclass
from typing import List, Tuple, Optional
from itertools import combinations


class Rank(IntEnum):
    """Card ranks (2-14 where 14=Ace)"""
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6
    SEVEN = 7
    EIGHT = 8
    NINE = 9
    TEN = 10
    JACK = 11
    QUEEN = 12
    KING = 13
    ACE = 14


class Suit(IntEnum):
    """Card suits"""
    CLUBS = 0
    DIAMONDS = 1
    HEARTS = 2
    SPADES = 3


class HandRank(IntEnum):
    """
    Hand ranking categories (lower = better)
    Royal Flush is just a special Straight Flush
    """
    STRAIGHT_FLUSH = 1
    FOUR_OF_A_KIND = 2
    FULL_HOUSE = 3
    FLUSH = 4
    STRAIGHT = 5
    THREE_OF_A_KIND = 6
    TWO_PAIR = 7
    ONE_PAIR = 8
    HIGH_CARD = 9


# Rank symbols for parsing
RANK_MAP = {
    '2': Rank.TWO, '3': Rank.THREE, '4': Rank.FOUR, '5': Rank.FIVE,
    '6': Rank.SIX, '7': Rank.SEVEN, '8': Rank.EIGHT, '9': Rank.NINE,
    'T': Rank.TEN, '10': Rank.TEN,
    'J': Rank.JACK, 'Q': Rank.QUEEN, 'K': Rank.KING, 'A': Rank.ACE
}

SUIT_MAP = {
    'c': Suit.CLUBS, 'C': Suit.CLUBS,
    'd': Suit.DIAMONDS, 'D': Suit.DIAMONDS,
    'h': Suit.HEARTS, 'H': Suit.HEARTS,
    's': Suit.SPADES, 'S': Suit.SPADES
}

RANK_NAMES = {
    2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8', 9: '9',
    10: 'T', 11: 'J', 12: 'Q', 13: 'K', 14: 'A'
}

SUIT_NAMES = {0: 'c', 1: 'd', 2: 'h', 3: 's'}
SUIT_SYMBOLS = {0: '♣', 1: '♦', 2: '♥', 3: '♠'}


@dataclass
class Card:
    """Represents a playing card"""
    rank: Rank
    suit: Suit

    def __str__(self) -> str:
        return f"{RANK_NAMES[self.rank]}{SUIT_NAMES[self.suit]}"

    def __repr__(self) -> str:
        return self.__str__()

    def pretty(self) -> str:
        """Pretty print with suit symbols"""
        return f"{RANK_NAMES[self.rank]}{SUIT_SYMBOLS[self.suit]}"

    def __hash__(self):
        return hash((self.rank, self.suit))

    def __eq__(self, other):
        if not isinstance(other, Card):
            return False
        return self.rank == other.rank and self.suit == other.suit

    def __lt__(self, other):
        return self.rank < other.rank

    @classmethod
    def from_string(cls, s: str) -> 'Card':
        """
        Parse card from string like 'Ah', 'Ks', '10c', 'Td'
        """
        s = s.strip()
        if len(s) < 2:
            raise ValueError(f"Invalid card string: {s}")

        # Handle '10' as a special case
        if s.startswith('10'):
            rank_str = '10'
            suit_str = s[2:]
        else:
            rank_str = s[0].upper()
            suit_str = s[1:]

        if rank_str not in RANK_MAP:
            raise ValueError(f"Invalid rank: {rank_str}")
        if not suit_str or suit_str[0].lower() not in SUIT_MAP:
            raise ValueError(f"Invalid suit: {suit_str}")

        return cls(RANK_MAP[rank_str], SUIT_MAP[suit_str[0].lower()])


@dataclass
class HandResult:
    """
    Result of hand evaluation

    Attributes:
        rank: The hand category (STRAIGHT_FLUSH, etc.)
        score: Numeric score for comparison (lower = better)
        cards: The 5 cards making up the hand
        description: Human-readable description
        kickers: Kicker cards for tie-breaking
    """
    rank: HandRank
    score: int
    cards: List[Card]
    description: str
    kickers: List[Rank]

    def __lt__(self, other: 'HandResult') -> bool:
        """Lower score = better hand"""
        return self.score < other.score

    def __gt__(self, other: 'HandResult') -> bool:
        return self.score > other.score

    def __eq__(self, other: 'HandResult') -> bool:
        return self.score == other.score

    def beats(self, other: 'HandResult') -> bool:
        """Returns True if this hand beats the other"""
        return self.score < other.score

    def ties(self, other: 'HandResult') -> bool:
        """Returns True if hands are equal"""
        return self.score == other.score


class HandEvaluator:
    """
    Evaluates poker hands and determines rankings

    Hand rankings (7462 distinct):
    - Straight Flush: 10 (1-10)
    - Four of a Kind: 156 (11-166)
    - Full House: 156 (167-322)
    - Flush: 1277 (323-1599)
    - Straight: 10 (1600-1609)
    - Three of a Kind: 858 (1610-2467)
    - Two Pair: 858 (2468-3325)
    - One Pair: 2860 (3326-6185)
    - High Card: 1277 (6186-7462)
    """

    def __init__(self):
        # Pre-compute straight patterns (including wheel A-2-3-4-5)
        self._straight_patterns = self._generate_straight_patterns()

    def _generate_straight_patterns(self) -> List[set]:
        """Generate all valid straight patterns"""
        patterns = []
        # Regular straights: 5-high through A-high
        for high in range(5, 15):
            pattern = set(range(high - 4, high + 1))
            patterns.append(pattern)
        # Wheel (A-2-3-4-5): Ace plays low
        patterns.append({14, 2, 3, 4, 5})
        return patterns

    def parse_cards(self, cards: List[str]) -> List[Card]:
        """Parse list of card strings to Card objects"""
        return [Card.from_string(c) if isinstance(c, str) else c for c in cards]

    def evaluate(self, hole_cards: List, board: List = None) -> HandResult:
        """
        Evaluate the best 5-card hand from hole cards + board

        Args:
            hole_cards: Player's hole cards (2 for Hold'em, 4 for Omaha)
            board: Community cards (0-5 cards)

        Returns:
            HandResult with best hand info
        """
        # Parse cards if strings
        hole = self.parse_cards(hole_cards) if hole_cards else []
        community = self.parse_cards(board) if board else []

        all_cards = hole + community

        if len(all_cards) < 5:
            raise ValueError(f"Need at least 5 cards, got {len(all_cards)}")

        # Find best 5-card combination
        best_result = None
        for combo in combinations(all_cards, 5):
            result = self._evaluate_5_cards(list(combo))
            if best_result is None or result.score < best_result.score:
                best_result = result

        return best_result

    def evaluate_5_cards(self, cards: List) -> HandResult:
        """Evaluate exactly 5 cards"""
        parsed = self.parse_cards(cards)
        if len(parsed) != 5:
            raise ValueError("Must provide exactly 5 cards")
        return self._evaluate_5_cards(parsed)

    def _evaluate_5_cards(self, cards: List[Card]) -> HandResult:
        """
        Evaluate a 5-card hand

        Returns HandResult with score where lower = better
        """
        # Sort by rank descending
        cards = sorted(cards, key=lambda c: c.rank, reverse=True)
        ranks = [c.rank for c in cards]
        suits = [c.suit for c in cards]

        # Check for flush
        is_flush = len(set(suits)) == 1

        # Check for straight
        is_straight, straight_high = self._check_straight(ranks)

        # Count rank occurrences
        rank_counts = {}
        for r in ranks:
            rank_counts[r] = rank_counts.get(r, 0) + 1

        # Sort by count then rank
        count_rank = sorted(rank_counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
        counts = [c for _, c in count_rank]

        # Determine hand type
        if is_straight and is_flush:
            # Straight flush (including royal flush)
            score = 1 + (14 - straight_high)  # A-high = 1, 5-high = 10
            desc = "Royal Flush" if straight_high == 14 else f"Straight Flush, {RANK_NAMES[straight_high]}-high"
            return HandResult(HandRank.STRAIGHT_FLUSH, score, cards, desc, [])

        if counts[0] == 4:
            # Four of a kind
            quad_rank = count_rank[0][0]
            kicker = count_rank[1][0]
            # Score: 11 + (14-quad_rank)*13 + (14-kicker)
            score = 11 + (14 - quad_rank) * 13 + (14 - kicker)
            desc = f"Four of a Kind, {RANK_NAMES[quad_rank]}s"
            return HandResult(HandRank.FOUR_OF_A_KIND, score, cards, desc, [kicker])

        if counts[0] == 3 and counts[1] == 2:
            # Full house
            trips_rank = count_rank[0][0]
            pair_rank = count_rank[1][0]
            score = 167 + (14 - trips_rank) * 13 + (14 - pair_rank)
            desc = f"Full House, {RANK_NAMES[trips_rank]}s full of {RANK_NAMES[pair_rank]}s"
            return HandResult(HandRank.FULL_HOUSE, score, cards, desc, [])

        if is_flush:
            # Flush
            score = self._flush_score(ranks)
            high_card = RANK_NAMES[max(ranks)]
            desc = f"Flush, {high_card}-high"
            return HandResult(HandRank.FLUSH, score, cards, desc, list(ranks))

        if is_straight:
            # Straight
            score = 1600 + (14 - straight_high)
            desc = f"Straight, {RANK_NAMES[straight_high]}-high"
            return HandResult(HandRank.STRAIGHT, score, cards, desc, [])

        if counts[0] == 3:
            # Three of a kind
            trips_rank = count_rank[0][0]
            kickers = sorted([r for r, c in count_rank if c == 1], reverse=True)
            score = 1610 + (14 - trips_rank) * 66 + self._kicker_value(kickers, 2)
            desc = f"Three of a Kind, {RANK_NAMES[trips_rank]}s"
            return HandResult(HandRank.THREE_OF_A_KIND, score, cards, desc, kickers)

        if counts[0] == 2 and counts[1] == 2:
            # Two pair
            pairs = sorted([r for r, c in count_rank if c == 2], reverse=True)
            kicker = [r for r, c in count_rank if c == 1][0]
            score = 2468 + (14 - pairs[0]) * 66 + (14 - pairs[1]) * 5 + (14 - kicker)
            desc = f"Two Pair, {RANK_NAMES[pairs[0]]}s and {RANK_NAMES[pairs[1]]}s"
            return HandResult(HandRank.TWO_PAIR, score, cards, desc, [kicker])

        if counts[0] == 2:
            # One pair
            pair_rank = count_rank[0][0]
            kickers = sorted([r for r, c in count_rank if c == 1], reverse=True)
            score = 3326 + (14 - pair_rank) * 220 + self._kicker_value(kickers, 3)
            desc = f"Pair of {RANK_NAMES[pair_rank]}s"
            return HandResult(HandRank.ONE_PAIR, score, cards, desc, kickers)

        # High card
        score = 6186 + self._kicker_value(ranks, 5)
        desc = f"High Card, {RANK_NAMES[ranks[0]]}"
        return HandResult(HandRank.HIGH_CARD, score, cards, desc, list(ranks))

    def _check_straight(self, ranks: List[Rank]) -> Tuple[bool, int]:
        """
        Check if ranks form a straight

        Returns: (is_straight, high_card_rank)
        """
        unique_ranks = set(ranks)
        if len(unique_ranks) != 5:
            return False, 0

        # Check wheel (A-2-3-4-5)
        if unique_ranks == {14, 2, 3, 4, 5}:
            return True, 5  # 5-high straight

        # Check regular straights
        min_rank = min(unique_ranks)
        max_rank = max(unique_ranks)
        if max_rank - min_rank == 4:
            return True, max_rank

        return False, 0

    def _flush_score(self, ranks: List[Rank]) -> int:
        """Calculate flush score based on card ranks"""
        sorted_ranks = sorted(ranks, reverse=True)
        # Base score 323, then rank-based ordering
        score = 323
        multipliers = [715, 55, 5, 1, 0]
        for i, r in enumerate(sorted_ranks[:4]):
            score += (14 - r) * multipliers[i]
        return score

    def _kicker_value(self, kickers: List[Rank], num_kickers: int) -> int:
        """Calculate kicker contribution to score"""
        value = 0
        multipliers = [169, 13, 1, 0, 0]
        for i, k in enumerate(kickers[:num_kickers]):
            value += (14 - k) * multipliers[i]
        return value

    def compare(self, hand1: HandResult, hand2: HandResult) -> int:
        """
        Compare two hands

        Returns:
            -1 if hand1 wins
            0 if tie
            1 if hand2 wins
        """
        if hand1.score < hand2.score:
            return -1
        elif hand1.score > hand2.score:
            return 1
        return 0

    def get_outs(self, hole_cards: List, board: List,
                 target_hands: List[HandRank] = None) -> List[Card]:
        """
        Find cards that improve the hand

        Args:
            hole_cards: Player's hole cards
            board: Current community cards
            target_hands: Optional list of target hand types

        Returns:
            List of cards that improve the hand
        """
        hole = self.parse_cards(hole_cards)
        community = self.parse_cards(board)

        if len(community) >= 5:
            return []

        current_result = self.evaluate(hole, community)
        known_cards = set(hole + community)
        outs = []

        # Check all remaining cards in deck
        for rank in Rank:
            for suit in Suit:
                card = Card(rank, suit)
                if card in known_cards:
                    continue

                # Test with this card added
                test_board = community + [card]
                new_result = self.evaluate(hole, test_board)

                # Check if improves
                improves = new_result.score < current_result.score

                # If target hands specified, check if reaches target
                if target_hands:
                    improves = improves and new_result.rank in target_hands

                if improves:
                    outs.append(card)

        return outs

    def get_hand_description(self, result: HandResult) -> str:
        """Get detailed hand description"""
        return result.description


class Deck:
    """Standard 52-card deck"""

    def __init__(self, exclude: List[Card] = None):
        """
        Initialize deck, optionally excluding known cards

        Args:
            exclude: Cards to remove from deck (already dealt)
        """
        self.cards = []
        exclude_set = set(exclude) if exclude else set()

        for rank in Rank:
            for suit in Suit:
                card = Card(rank, suit)
                if card not in exclude_set:
                    self.cards.append(card)

    def __len__(self):
        return len(self.cards)

    def shuffle(self):
        """Shuffle the deck"""
        import random
        random.shuffle(self.cards)

    def deal(self, n: int = 1) -> List[Card]:
        """Deal n cards from deck"""
        if n > len(self.cards):
            raise ValueError(f"Not enough cards: requested {n}, have {len(self.cards)}")
        dealt = self.cards[:n]
        self.cards = self.cards[n:]
        return dealt

    def remove(self, cards: List[Card]) -> None:
        """Remove specific cards from deck"""
        cards_set = set(cards)
        self.cards = [c for c in self.cards if c not in cards_set]


# === Standalone Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n=== Hand Evaluator Test ===\n", "cyan", attrs=['bold'])

    evaluator = HandEvaluator()

    # Test cases
    test_hands = [
        # Royal flush
        (["As", "Ks", "Qs", "Js", "Ts"], "Royal Flush"),
        # Straight flush
        (["9h", "8h", "7h", "6h", "5h"], "Straight Flush"),
        # Wheel straight flush
        (["Ac", "2c", "3c", "4c", "5c"], "Wheel Straight Flush"),
        # Four of a kind
        (["Ah", "Ad", "As", "Ac", "Kh"], "Four Aces"),
        # Full house
        (["Kh", "Kd", "Ks", "Qh", "Qd"], "Full House"),
        # Flush
        (["Ah", "Kh", "9h", "5h", "2h"], "Flush"),
        # Straight
        (["Th", "9c", "8d", "7h", "6s"], "Straight"),
        # Wheel straight
        (["Ah", "2c", "3d", "4h", "5s"], "Wheel Straight"),
        # Three of a kind
        (["Jh", "Jd", "Js", "Ah", "Kc"], "Three Jacks"),
        # Two pair
        (["Ah", "Ad", "Kh", "Kd", "Qc"], "Two Pair"),
        # One pair
        (["Ah", "Ad", "Kh", "Qd", "Jc"], "Pair of Aces"),
        # High card
        (["Ah", "Kd", "Qh", "Jd", "9c"], "High Card"),
    ]

    for cards, desc in test_hands:
        result = evaluator.evaluate_5_cards(cards)
        cprint(f"{desc}", "white")
        cprint(f"  Cards: {' '.join(cards)}", "cyan")
        cprint(f"  Result: {result.description}", "green")
        cprint(f"  Score: {result.score}", "yellow")
        print()

    # Test 7-card evaluation (Texas Hold'em)
    cprint("=== 7-Card Evaluation (Hold'em) ===\n", "cyan", attrs=['bold'])

    hole = ["Ah", "Kh"]
    board = ["Qh", "Jh", "Th", "2c", "3d"]
    result = evaluator.evaluate(hole, board)

    cprint(f"Hole: {' '.join(hole)}", "white")
    cprint(f"Board: {' '.join(board)}", "white")
    cprint(f"Best Hand: {result.description}", "green", attrs=['bold'])
    cprint(f"Using: {' '.join(str(c) for c in result.cards)}", "cyan")

    # Test outs calculation
    cprint("\n=== Outs Calculation ===\n", "cyan", attrs=['bold'])

    hole = ["Ah", "Kh"]
    board = ["Qh", "Jc", "2d"]  # 4 to the flush, 4 to the straight
    outs = evaluator.get_outs(hole, board)

    cprint(f"Hole: {' '.join(hole)}", "white")
    cprint(f"Board: {' '.join(board)}", "white")
    cprint(f"Outs ({len(outs)}): {' '.join(str(c) for c in outs[:10])}...", "green")
