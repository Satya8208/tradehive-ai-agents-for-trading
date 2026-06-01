"""
Board Analyzer - Analyze board texture, draws, and strategic implications
Critical for postflop decision-making
Built with love by TradeHive
"""

from dataclasses import dataclass, field
from typing import List, Dict, Set, Tuple, Optional
from enum import Enum
from collections import Counter

import sys
from pathlib import Path
project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.poker.core.hand_evaluator import (
    Card, Rank, Suit, HandEvaluator, RANK_NAMES, SUIT_SYMBOLS
)


class BoardTexture(Enum):
    """Board texture categories"""
    DRY = "dry"               # Disconnected, rainbow (K72r)
    SEMI_DRY = "semi_dry"     # Some connectivity but limited draws
    SEMI_WET = "semi_wet"     # Moderate draws present
    WET = "wet"               # Many draws (flush, straight)
    MONOTONE = "monotone"     # All same suit
    PAIRED = "paired"         # One pair on board
    DOUBLE_PAIRED = "double_paired"  # Two pairs
    TRIPS = "trips"           # Three of a kind on board


class DrawType(Enum):
    """Types of draws"""
    FLUSH_DRAW = "flush_draw"           # 4 to flush
    BACKDOOR_FLUSH = "backdoor_flush"   # 3 to flush (on flop)
    OESD = "oesd"                       # Open-ended straight draw (8 outs)
    GUTSHOT = "gutshot"                 # Inside straight draw (4 outs)
    DOUBLE_GUTSHOT = "double_gutshot"   # Two ways to complete straight
    BACKDOOR_STRAIGHT = "backdoor_straight"  # 3 to straight


@dataclass
class Draw:
    """Represents a possible draw"""
    draw_type: DrawType
    outs: int
    completing_cards: List[Rank]
    description: str


@dataclass
class BoardAnalysis:
    """Complete board analysis result"""
    texture: BoardTexture
    texture_score: float          # 0 (dry) to 1 (wet)
    high_card: Rank
    is_rainbow: bool
    is_monotone: bool
    is_paired: bool
    pair_rank: Optional[Rank]
    is_connected: bool
    straight_possible: bool
    flush_possible: bool
    flush_suit: Optional[Suit]
    draws: List[Draw]
    nut_hands: List[str]
    danger_cards: List[Rank]      # Cards that complete obvious draws
    description: str


class BoardAnalyzer:
    """
    Analyzes poker boards for texture and strategic implications

    Handles:
    - Texture classification (dry/wet/monotone/paired)
    - Draw detection (flush, straight, backdoor)
    - Nut hand identification
    - Danger card analysis
    - Range advantage estimation
    """

    def __init__(self):
        self.evaluator = HandEvaluator()

    def analyze(self, board: List[Card]) -> BoardAnalysis:
        """
        Perform complete board analysis

        Args:
            board: List of community cards (3-5)

        Returns:
            BoardAnalysis with complete breakdown
        """
        if len(board) < 3:
            raise ValueError("Need at least 3 cards for board analysis")

        board = self._parse_cards(board)
        ranks = [c.rank for c in board]
        suits = [c.suit for c in board]

        # Basic analysis
        high_card = max(ranks)
        suit_counts = Counter(suits)
        rank_counts = Counter(ranks)

        # Pairing
        is_paired = max(rank_counts.values()) >= 2
        is_double_paired = list(rank_counts.values()).count(2) >= 2
        is_trips = max(rank_counts.values()) >= 3
        pair_rank = None
        if is_paired:
            for r, c in rank_counts.items():
                if c >= 2:
                    pair_rank = r
                    break

        # Suits
        is_rainbow = max(suit_counts.values()) == 1
        is_monotone = max(suit_counts.values()) >= 3 and len(board) == 3
        is_monotone = is_monotone or (max(suit_counts.values()) >= 4 and len(board) >= 4)
        is_two_tone = max(suit_counts.values()) == 2 and len(board) == 3

        flush_possible = max(suit_counts.values()) >= 3
        flush_suit = None
        if flush_possible:
            flush_suit = max(suit_counts.keys(), key=lambda s: suit_counts[s])

        # Connectivity
        sorted_ranks = sorted(set(ranks), reverse=True)
        is_connected = self._check_connected(sorted_ranks)
        straight_possible = self._check_straight_possible(sorted_ranks)

        # Texture classification
        texture, texture_score = self._classify_texture(
            is_rainbow, is_monotone, is_paired, is_double_paired, is_trips,
            is_connected, flush_possible, straight_possible, len(board)
        )

        # Draw detection
        draws = self._detect_draws(board, suits, ranks)

        # Nut hands
        nut_hands = self._find_nut_hands(board, texture)

        # Danger cards
        danger_cards = self._find_danger_cards(board, draws, flush_suit)

        # Description
        description = self._generate_description(
            board, texture, is_rainbow, is_paired, flush_possible
        )

        return BoardAnalysis(
            texture=texture,
            texture_score=texture_score,
            high_card=high_card,
            is_rainbow=is_rainbow,
            is_monotone=is_monotone,
            is_paired=is_paired,
            pair_rank=pair_rank,
            is_connected=is_connected,
            straight_possible=straight_possible,
            flush_possible=flush_possible,
            flush_suit=flush_suit,
            draws=draws,
            nut_hands=nut_hands,
            danger_cards=danger_cards,
            description=description
        )

    def _parse_cards(self, cards: List) -> List[Card]:
        """Parse cards to Card objects if needed"""
        result = []
        for c in cards:
            if isinstance(c, str):
                result.append(Card.from_string(c))
            else:
                result.append(c)
        return result

    def _check_connected(self, sorted_ranks: List[Rank]) -> bool:
        """Check if board has connected cards (within 2 ranks)"""
        if len(sorted_ranks) < 2:
            return False

        for i in range(len(sorted_ranks) - 1):
            diff = sorted_ranks[i] - sorted_ranks[i + 1]
            if diff <= 2:
                return True

        # Check ace-low connectivity
        if Rank.ACE in sorted_ranks:
            low_ranks = [r for r in sorted_ranks if r <= Rank.FIVE]
            if low_ranks:
                return True

        return False

    def _check_straight_possible(self, sorted_ranks: List[Rank]) -> bool:
        """Check if a straight is possible with the board"""
        # Need to check if 3 cards within 5-rank span
        ranks_set = set(sorted_ranks)

        # Add ace as both high and low
        if Rank.ACE in ranks_set:
            ranks_set.add(Rank.TWO - 1)  # Represent ace-low as 1

        for high in range(max(sorted_ranks), min(sorted_ranks) - 1, -1):
            span = set(range(high - 4, high + 1))
            overlap = span & ranks_set
            if len(overlap) >= 3:
                return True

        return False

    def _classify_texture(self, is_rainbow: bool, is_monotone: bool,
                          is_paired: bool, is_double_paired: bool,
                          is_trips: bool, is_connected: bool,
                          flush_possible: bool, straight_possible: bool,
                          num_cards: int) -> Tuple[BoardTexture, float]:
        """Classify board texture and return wetness score"""

        # Special textures first
        if is_trips:
            return BoardTexture.TRIPS, 0.3

        if is_double_paired:
            return BoardTexture.DOUBLE_PAIRED, 0.3

        if is_paired:
            # Paired boards are generally drier
            if is_monotone:
                return BoardTexture.MONOTONE, 0.7
            elif flush_possible or straight_possible:
                return BoardTexture.SEMI_WET, 0.5
            else:
                return BoardTexture.PAIRED, 0.4

        if is_monotone:
            return BoardTexture.MONOTONE, 0.9

        # Calculate wetness score
        wetness = 0.0

        if flush_possible:
            wetness += 0.4

        if straight_possible:
            if is_connected:
                wetness += 0.4
            else:
                wetness += 0.2

        if is_rainbow:
            wetness -= 0.2

        wetness = max(0.0, min(1.0, wetness))

        # Classify
        if wetness >= 0.7:
            return BoardTexture.WET, wetness
        elif wetness >= 0.4:
            return BoardTexture.SEMI_WET, wetness
        elif wetness >= 0.2:
            return BoardTexture.SEMI_DRY, wetness
        else:
            return BoardTexture.DRY, wetness

    def _detect_draws(self, board: List[Card], suits: List[Suit],
                      ranks: List[Rank]) -> List[Draw]:
        """Detect all possible draws on the board"""
        draws = []
        num_cards = len(board)

        # Flush draws
        suit_counts = Counter(suits)
        for suit, count in suit_counts.items():
            if count == 4 and num_cards >= 4:
                # Made flush possible
                pass
            elif count == 3 and num_cards == 4:
                # 4-flush draw on turn
                draws.append(Draw(
                    DrawType.FLUSH_DRAW,
                    outs=9,
                    completing_cards=[],
                    description=f"Flush draw in {SUIT_SYMBOLS[suit]}"
                ))
            elif count == 2 and num_cards == 3:
                # Backdoor flush on flop
                draws.append(Draw(
                    DrawType.BACKDOOR_FLUSH,
                    outs=10,  # Running suited cards
                    completing_cards=[],
                    description=f"Backdoor flush possible ({SUIT_SYMBOLS[suit]})"
                ))

        # Straight draws
        unique_ranks = sorted(set(ranks), reverse=True)

        # Check for OESD
        oesd_cards = self._find_oesd(unique_ranks)
        if oesd_cards:
            draws.append(Draw(
                DrawType.OESD,
                outs=8,
                completing_cards=oesd_cards,
                description=f"Open-ended straight draw ({', '.join(RANK_NAMES[r] for r in oesd_cards)})"
            ))

        # Check for gutshots
        gutshot_cards = self._find_gutshots(unique_ranks)
        if gutshot_cards and not oesd_cards:
            draws.append(Draw(
                DrawType.GUTSHOT,
                outs=4,
                completing_cards=gutshot_cards,
                description=f"Gutshot straight draw ({', '.join(RANK_NAMES[r] for r in gutshot_cards)})"
            ))

        return draws

    def _find_oesd(self, sorted_ranks: List[Rank]) -> List[Rank]:
        """Find cards that complete an open-ended straight draw"""
        completing = []
        ranks_set = set(sorted_ranks)

        # Check 4 consecutive with gaps on both ends
        for i in range(len(sorted_ranks) - 2):
            span = sorted_ranks[i:i + 3]
            if span[0] - span[2] <= 3:
                # Check if cards on both ends complete
                low = span[2] - 1
                high = span[0] + 1
                if low >= 2 and high <= 14:
                    if low not in ranks_set:
                        completing.append(Rank(low))
                    if high not in ranks_set:
                        completing.append(Rank(high))

        return list(set(completing))[:2]

    def _find_gutshots(self, sorted_ranks: List[Rank]) -> List[Rank]:
        """Find cards that complete a gutshot straight"""
        completing = []
        ranks_set = set(sorted_ranks)

        # Look for one-gapper patterns
        for high in range(14, 5, -1):
            needed = set(range(high - 4, high + 1))
            present = needed & ranks_set
            missing = needed - ranks_set

            if len(present) == 4 and len(missing) == 1:
                completing.append(Rank(list(missing)[0]))

        return completing[:2]

    def _find_nut_hands(self, board: List[Card], texture: BoardTexture) -> List[str]:
        """Identify the nut hands on this board"""
        nuts = []
        ranks = [c.rank for c in board]
        suits = [c.suit for c in board]
        sorted_ranks = sorted(set(ranks), reverse=True)

        # Check for flush/straight flush nuts
        suit_counts = Counter(suits)
        max_suit_count = max(suit_counts.values())

        if max_suit_count >= 3:
            flush_suit = max(suit_counts.keys(), key=lambda s: suit_counts[s])
            flush_ranks = [c.rank for c in board if c.suit == flush_suit]

            # Nut flush
            for r in [Rank.ACE, Rank.KING, Rank.QUEEN]:
                if r not in flush_ranks:
                    nuts.append(f"{RANK_NAMES[r]}{SUIT_SYMBOLS[flush_suit]} (nut flush)")
                    break

        # Check for straight nuts
        if self._check_straight_possible(sorted_ranks):
            # Find highest straight possible
            for high in range(14, 5, -1):
                needed = set(range(high - 4, high + 1))
                present = needed & set(sorted_ranks)
                if len(present) >= 3:
                    missing = needed - set(sorted_ranks)
                    if len(missing) <= 2:
                        nuts.append(f"Straight to {RANK_NAMES[high]}")
                        break

        # Set/full house on paired boards
        if texture in [BoardTexture.PAIRED, BoardTexture.DOUBLE_PAIRED]:
            top_rank = max(ranks)
            nuts.append(f"Set of {RANK_NAMES[top_rank]}s")

        # Top set on dry boards
        if texture in [BoardTexture.DRY, BoardTexture.SEMI_DRY]:
            top_rank = sorted_ranks[0]
            nuts.append(f"Set of {RANK_NAMES[top_rank]}s")

        return nuts[:3]

    def _find_danger_cards(self, board: List[Card], draws: List[Draw],
                           flush_suit: Optional[Suit]) -> List[Rank]:
        """Find cards that complete obvious draws"""
        danger = set()

        for draw in draws:
            for rank in draw.completing_cards:
                danger.add(rank)

        # Add flush completing cards
        if flush_suit is not None:
            suit_cards = [c.rank for c in board if c.suit == flush_suit]
            if len(suit_cards) == 4:
                # Any card of suit completes flush
                for r in Rank:
                    if r not in suit_cards:
                        danger.add(r)
                        break

        return sorted(list(danger), reverse=True)[:5]

    def _generate_description(self, board: List[Card], texture: BoardTexture,
                              is_rainbow: bool, is_paired: bool,
                              flush_possible: bool) -> str:
        """Generate human-readable board description"""
        ranks = sorted([c.rank for c in board], reverse=True)
        high = RANK_NAMES[ranks[0]]
        low = RANK_NAMES[ranks[-1]]

        parts = []

        # Texture
        texture_names = {
            BoardTexture.DRY: "Dry",
            BoardTexture.SEMI_DRY: "Semi-dry",
            BoardTexture.SEMI_WET: "Semi-wet",
            BoardTexture.WET: "Wet",
            BoardTexture.MONOTONE: "Monotone",
            BoardTexture.PAIRED: "Paired",
            BoardTexture.DOUBLE_PAIRED: "Double-paired",
            BoardTexture.TRIPS: "Trips"
        }
        parts.append(texture_names[texture])

        # High card
        parts.append(f"{high}-high")

        # Rainbow/flush
        if is_rainbow:
            parts.append("rainbow")
        elif flush_possible:
            parts.append("flush draw")

        # Paired
        if is_paired:
            parts.append("paired")

        return " ".join(parts)

    def range_advantage(self, ip_range, oop_range, board: List[Card]) -> Tuple[str, float]:
        """
        Estimate which player has range advantage on this board

        Args:
            ip_range: In-position player's range
            oop_range: Out-of-position player's range
            board: Board cards

        Returns:
            Tuple of (player with advantage, advantage score 0-1)
        """
        # Simplified heuristic based on board texture
        analysis = self.analyze(board)

        # High cards favor IP (usually has more suited broadways)
        # Paired boards favor OOP (usually has more pairs)
        # Connected boards are more neutral

        if analysis.texture == BoardTexture.PAIRED:
            return ("OOP", 0.6)
        elif analysis.texture == BoardTexture.DRY and analysis.high_card >= Rank.KING:
            return ("IP", 0.65)
        elif analysis.texture == BoardTexture.WET:
            return ("IP", 0.55)
        else:
            return ("IP", 0.52)


# === Standalone Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n=== Board Analyzer Test ===\n", "cyan", attrs=['bold'])

    analyzer = BoardAnalyzer()

    # Test boards
    test_boards = [
        (["Ks", "7h", "2c"], "Dry rainbow"),
        (["Qh", "Jh", "Th"], "Monotone wet"),
        (["Ah", "Kd", "Qs", "Jc"], "Broadway connected"),
        (["Kh", "Kc", "7d"], "Paired"),
        (["9s", "8s", "7h", "2c"], "Connected with flush draw"),
        (["As", "Ah", "Kd", "Kc", "Qh"], "Double paired"),
    ]

    for cards, desc in test_boards:
        parsed = [Card.from_string(c) for c in cards]
        analysis = analyzer.analyze(parsed)

        cprint(f"\n{desc}:", "yellow")
        cprint(f"  Board: {' '.join(c.pretty() for c in parsed)}", "white")
        cprint(f"  Texture: {analysis.texture.value} ({analysis.texture_score:.2f})", "green")
        cprint(f"  {analysis.description}", "cyan")

        if analysis.draws:
            cprint("  Draws:", "white")
            for draw in analysis.draws:
                cprint(f"    - {draw.description} ({draw.outs} outs)", "yellow")

        if analysis.nut_hands:
            cprint("  Nut hands:", "white")
            for nut in analysis.nut_hands:
                cprint(f"    - {nut}", "magenta")

        if analysis.danger_cards:
            cprint(f"  Danger cards: {', '.join(RANK_NAMES[r] for r in analysis.danger_cards)}", "red")
