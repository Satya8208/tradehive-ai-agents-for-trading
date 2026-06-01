"""
Range Manager - Parse, visualize, and manipulate poker hand ranges
Supports standard notation like "AA,KK,AKs,QQ-TT,ATs+"
Built with love by TradeHive
"""

import re
import random
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional, Iterator
from enum import Enum

import sys
from pathlib import Path
project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.poker.core.hand_evaluator import Rank, Suit, Card, RANK_NAMES, RANK_MAP


# All 13 ranks in order (A high)
RANKS_ORDERED = [Rank.ACE, Rank.KING, Rank.QUEEN, Rank.JACK, Rank.TEN,
                 Rank.NINE, Rank.EIGHT, Rank.SEVEN, Rank.SIX, Rank.FIVE,
                 Rank.FOUR, Rank.THREE, Rank.TWO]

RANK_TO_INDEX = {r: i for i, r in enumerate(RANKS_ORDERED)}

# All 169 starting hands
ALL_HANDS = []
for i, r1 in enumerate(RANKS_ORDERED):
    for j, r2 in enumerate(RANKS_ORDERED):
        if i == j:
            ALL_HANDS.append(f"{RANK_NAMES[r1]}{RANK_NAMES[r2]}")
        elif i < j:
            ALL_HANDS.append(f"{RANK_NAMES[r1]}{RANK_NAMES[r2]}s")
        else:
            ALL_HANDS.append(f"{RANK_NAMES[r2]}{RANK_NAMES[r1]}o")


def normalize_hand(hand: str) -> str:
    """Normalize hand notation to standard form (higher rank first)"""
    hand = hand.strip().upper()

    if len(hand) < 2:
        raise ValueError(f"Invalid hand: {hand}")

    # Extract ranks
    if hand[0] == '1' and hand[1] == '0':
        r1 = 'T'
        rest = hand[2:]
    else:
        r1 = hand[0]
        rest = hand[1:]

    if rest[0] == '1' and len(rest) > 1 and rest[1] == '0':
        r2 = 'T'
        suffix = rest[2:] if len(rest) > 2 else ''
    else:
        r2 = rest[0]
        suffix = rest[1:] if len(rest) > 1 else ''

    rank1 = RANK_MAP.get(r1)
    rank2 = RANK_MAP.get(r2)

    if rank1 is None or rank2 is None:
        raise ValueError(f"Invalid ranks in hand: {hand}")

    # Order by rank (higher first)
    if rank1 < rank2:
        r1, r2 = RANK_NAMES[rank2], RANK_NAMES[rank1]
    else:
        r1, r2 = RANK_NAMES[rank1], RANK_NAMES[rank2]

    # Determine type
    if rank1 == rank2:
        return f"{r1}{r2}"
    elif 's' in suffix.lower():
        return f"{r1}{r2}s"
    elif 'o' in suffix.lower():
        return f"{r1}{r2}o"
    else:
        # Default to offsuit for non-pairs
        return f"{r1}{r2}o"


@dataclass
class Range:
    """
    Represents a range of poker hands with frequencies

    Each hand maps to a frequency (0.0 to 1.0)
    """
    hands: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        # Normalize all hand keys
        normalized = {}
        for hand, freq in self.hands.items():
            try:
                key = normalize_hand(hand)
                normalized[key] = max(0.0, min(1.0, freq))
            except ValueError:
                continue
        self.hands = normalized

    def __len__(self) -> int:
        return len(self.hands)

    def __contains__(self, hand: str) -> bool:
        try:
            return normalize_hand(hand) in self.hands
        except ValueError:
            return False

    def __iter__(self) -> Iterator[str]:
        return iter(self.hands)

    def add(self, hand: str, frequency: float = 1.0) -> None:
        """Add a hand to the range"""
        key = normalize_hand(hand)
        self.hands[key] = max(0.0, min(1.0, frequency))

    def remove(self, hand: str) -> None:
        """Remove a hand from the range"""
        key = normalize_hand(hand)
        self.hands.pop(key, None)

    def get_frequency(self, hand: str) -> float:
        """Get frequency for a hand (0 if not in range)"""
        try:
            return self.hands.get(normalize_hand(hand), 0.0)
        except ValueError:
            return 0.0

    def set_frequency(self, hand: str, frequency: float) -> None:
        """Set frequency for a hand"""
        key = normalize_hand(hand)
        if frequency <= 0:
            self.hands.pop(key, None)
        else:
            self.hands[key] = min(1.0, frequency)

    def percentage(self) -> float:
        """
        Calculate what percentage of all starting hands this range represents

        Accounts for frequencies and hand combos:
        - Pairs: 6 combos
        - Suited: 4 combos
        - Offsuit: 12 combos
        """
        total_combos = 0
        for hand, freq in self.hands.items():
            if len(hand) == 2:  # Pair
                total_combos += 6 * freq
            elif hand.endswith('s'):  # Suited
                total_combos += 4 * freq
            else:  # Offsuit
                total_combos += 12 * freq

        return (total_combos / 1326) * 100  # 1326 = total combos

    def combo_count(self) -> int:
        """Count total combos in range (accounting for frequencies)"""
        total = 0
        for hand, freq in self.hands.items():
            if len(hand) == 2:
                total += int(6 * freq)
            elif hand.endswith('s'):
                total += int(4 * freq)
            else:
                total += int(12 * freq)
        return total

    def sample(self) -> Tuple[Card, Card]:
        """
        Sample a random hand from the range (accounting for frequencies)

        Returns tuple of two Cards
        """
        if not self.hands:
            raise ValueError("Cannot sample from empty range")

        # Weight by combos * frequency
        weights = []
        hands = []
        for hand, freq in self.hands.items():
            if freq > 0:
                if len(hand) == 2:
                    combos = 6
                elif hand.endswith('s'):
                    combos = 4
                else:
                    combos = 12
                weights.append(combos * freq)
                hands.append(hand)

        # Select hand
        selected = random.choices(hands, weights=weights, k=1)[0]

        # Generate actual cards
        r1_char = selected[0]
        r2_char = selected[1]
        rank1 = RANK_MAP[r1_char]
        rank2 = RANK_MAP[r2_char]

        if len(selected) == 2:  # Pair
            suits = random.sample(list(Suit), 2)
            return Card(rank1, suits[0]), Card(rank2, suits[1])
        elif selected.endswith('s'):  # Suited
            suit = random.choice(list(Suit))
            return Card(rank1, suit), Card(rank2, suit)
        else:  # Offsuit
            suit1 = random.choice(list(Suit))
            suit2 = random.choice([s for s in Suit if s != suit1])
            return Card(rank1, suit1), Card(rank2, suit2)

    def union(self, other: 'Range') -> 'Range':
        """Combine two ranges (take max frequency)"""
        result = Range(self.hands.copy())
        for hand, freq in other.hands.items():
            current = result.hands.get(hand, 0.0)
            result.hands[hand] = max(current, freq)
        return result

    def intersection(self, other: 'Range') -> 'Range':
        """Intersection of ranges (take min frequency)"""
        result = Range()
        for hand, freq in self.hands.items():
            if hand in other.hands:
                result.hands[hand] = min(freq, other.hands[hand])
        return result

    def difference(self, other: 'Range') -> 'Range':
        """Remove hands that are in other range"""
        result = Range()
        for hand, freq in self.hands.items():
            if hand not in other.hands:
                result.hands[hand] = freq
        return result

    def scale(self, factor: float) -> 'Range':
        """Scale all frequencies by a factor"""
        result = Range()
        for hand, freq in self.hands.items():
            result.hands[hand] = max(0.0, min(1.0, freq * factor))
        return result

    @classmethod
    def from_notation(cls, notation: str) -> 'Range':
        """
        Parse range from standard notation

        Supported formats:
        - Single hands: AA, AKs, AKo
        - Ranges: QQ-TT, ATs-A5s
        - Plus notation: ATs+, 99+
        - Mixed: AA,KK,AKs,QQ-TT,ATs+

        Returns a Range object
        """
        range_obj = cls()

        if not notation or not notation.strip():
            return range_obj

        # Split by comma
        parts = [p.strip() for p in notation.split(',')]

        for part in parts:
            if not part:
                continue

            # Check for frequency suffix like :0.5
            freq = 1.0
            if ':' in part:
                part, freq_str = part.split(':')
                try:
                    freq = float(freq_str)
                except ValueError:
                    freq = 1.0

            # Handle range notation (QQ-TT, AKs-ATs)
            if '-' in part:
                range_obj._parse_dash_range(part, freq)

            # Handle plus notation (ATs+, 99+)
            elif part.endswith('+'):
                range_obj._parse_plus_range(part[:-1], freq)

            # Single hand
            else:
                try:
                    hand = normalize_hand(part)
                    range_obj.hands[hand] = freq
                except ValueError:
                    continue

        return range_obj

    def _parse_dash_range(self, notation: str, freq: float) -> None:
        """Parse range like QQ-TT or AKs-ATs"""
        parts = notation.split('-')
        if len(parts) != 2:
            return

        start = normalize_hand(parts[0])
        end = normalize_hand(parts[1])

        # Check if pairs range
        if len(start) == 2 and len(end) == 2:
            # Pair range (QQ-TT)
            start_rank = RANK_MAP[start[0]]
            end_rank = RANK_MAP[end[0]]

            for rank in Rank:
                if min(start_rank, end_rank) <= rank <= max(start_rank, end_rank):
                    hand = f"{RANK_NAMES[rank]}{RANK_NAMES[rank]}"
                    self.hands[hand] = freq

        else:
            # Non-pair range (AKs-ATs)
            start_r1 = RANK_MAP[start[0]]
            start_r2 = RANK_MAP[start[1]]
            end_r1 = RANK_MAP[end[0]]
            end_r2 = RANK_MAP[end[1]]

            # Same high card
            if start_r1 == end_r1:
                suited = 's' in start
                for rank in Rank:
                    if min(start_r2, end_r2) <= rank <= max(start_r2, end_r2):
                        if rank != start_r1:  # Not a pair
                            r1 = RANK_NAMES[max(start_r1, rank)]
                            r2 = RANK_NAMES[min(start_r1, rank)]
                            suffix = 's' if suited else 'o'
                            self.hands[f"{r1}{r2}{suffix}"] = freq

    def _parse_plus_range(self, base: str, freq: float) -> None:
        """Parse plus notation like ATs+ or 99+"""
        hand = normalize_hand(base)

        if len(hand) == 2:
            # Pair+ (99+)
            base_rank = RANK_MAP[hand[0]]
            for rank in Rank:
                if rank >= base_rank:
                    self.hands[f"{RANK_NAMES[rank]}{RANK_NAMES[rank]}"] = freq

        else:
            # Non-pair+ (ATs+)
            high_rank = RANK_MAP[hand[0]]
            low_rank = RANK_MAP[hand[1]]
            suited = 's' in hand

            # Go from low_rank up to one below high_rank
            for rank in Rank:
                if low_rank <= rank < high_rank:
                    r1 = RANK_NAMES[high_rank]
                    r2 = RANK_NAMES[rank]
                    suffix = 's' if suited else 'o'
                    self.hands[f"{r1}{r2}{suffix}"] = freq

    def to_notation(self) -> str:
        """Convert range to compact notation string"""
        if not self.hands:
            return ""

        # Group hands by type
        pairs = []
        suited = {}  # high_card -> [low_cards]
        offsuit = {}

        for hand, freq in sorted(self.hands.items()):
            if freq < 1.0:
                continue  # Skip partial frequencies for simplicity

            if len(hand) == 2:
                pairs.append(hand)
            elif hand.endswith('s'):
                high = hand[0]
                low = hand[1]
                suited.setdefault(high, []).append(low)
            else:
                high = hand[0]
                low = hand[1]
                offsuit.setdefault(high, []).append(low)

        parts = []

        # Compress pairs
        if pairs:
            parts.extend(self._compress_sequence(pairs, is_pair=True))

        # Compress suited hands
        for high, lows in sorted(suited.items(), key=lambda x: -RANK_MAP[x[0]]):
            parts.extend(self._compress_suited(high, lows, 's'))

        # Compress offsuit hands
        for high, lows in sorted(offsuit.items(), key=lambda x: -RANK_MAP[x[0]]):
            parts.extend(self._compress_suited(high, lows, 'o'))

        return ','.join(parts)

    def _compress_sequence(self, pairs: List[str], is_pair: bool = False) -> List[str]:
        """Compress consecutive pairs into ranges"""
        if not pairs:
            return []

        ranks = sorted([RANK_MAP[p[0]] for p in pairs], reverse=True)
        result = []
        i = 0

        while i < len(ranks):
            start = ranks[i]
            end = ranks[i]

            while i + 1 < len(ranks) and ranks[i + 1] == end - 1:
                i += 1
                end = ranks[i]

            start_str = f"{RANK_NAMES[start]}{RANK_NAMES[start]}"
            end_str = f"{RANK_NAMES[end]}{RANK_NAMES[end]}"

            if start == end:
                result.append(start_str)
            elif end == Rank.TWO:
                result.append(f"{start_str}+")
            else:
                result.append(f"{start_str}-{end_str}")

            i += 1

        return result

    def _compress_suited(self, high: str, lows: List[str], suffix: str) -> List[str]:
        """Compress suited/offsuit hands"""
        if not lows:
            return []

        ranks = sorted([RANK_MAP[l] for l in lows], reverse=True)
        high_rank = RANK_MAP[high]
        result = []
        i = 0

        while i < len(ranks):
            start = ranks[i]
            end = ranks[i]

            while i + 1 < len(ranks) and ranks[i + 1] == end - 1:
                i += 1
                end = ranks[i]

            start_str = f"{high}{RANK_NAMES[start]}{suffix}"
            end_str = f"{high}{RANK_NAMES[end]}{suffix}"

            if start == end:
                result.append(start_str)
            elif end == Rank.TWO or (end == 2 and start == high_rank - 1):
                result.append(f"{start_str}+")
            else:
                result.append(f"{start_str}-{end_str}")

            i += 1

        return result

    def visualize(self, width: int = 3) -> str:
        """
        Generate ASCII 13x13 range grid

        Args:
            width: Width of each cell

        Returns:
            ASCII string visualization
        """
        lines = []

        # Header
        header = "   " + "".join(f"{RANK_NAMES[r]:^{width}}" for r in RANKS_ORDERED)
        lines.append(header)
        lines.append("   " + "-" * (13 * width))

        for i, r1 in enumerate(RANKS_ORDERED):
            row = f"{RANK_NAMES[r1]:>2}|"
            for j, r2 in enumerate(RANKS_ORDERED):
                if i == j:
                    # Pair
                    hand = f"{RANK_NAMES[r1]}{RANK_NAMES[r2]}"
                elif i < j:
                    # Suited (above diagonal)
                    hand = f"{RANK_NAMES[r1]}{RANK_NAMES[r2]}s"
                else:
                    # Offsuit (below diagonal)
                    hand = f"{RANK_NAMES[r2]}{RANK_NAMES[r1]}o"

                freq = self.hands.get(hand, 0.0)
                if freq >= 1.0:
                    cell = "##"
                elif freq > 0:
                    cell = f"{int(freq*10):2d}"
                else:
                    cell = ".."
                row += f"{cell:^{width}}"

            lines.append(row)

        # Legend
        lines.append("")
        lines.append("## = 100% | Numbers = frequency*10 | .. = not in range")
        lines.append(f"Range: {self.percentage():.1f}% ({self.combo_count()} combos)")

        return "\n".join(lines)


class RangeManager:
    """
    Manager for working with multiple ranges and presets
    """

    # Common presets
    PRESETS = {
        # Very tight (top ~5%)
        'utg_open': "AA-99,AKo,AQo,AKs-ATs,KQs",

        # Tight (top ~15%)
        'ep_open': "AA-66,AKo-ATo,KQo,AKs-A9s,KQs-KTs,QJs-QTs,JTs",

        # Standard (top ~25%)
        'mp_open': "AA-22,AKo-A8o,KQo-KTo,QJo,AKs-A2s,KQs-K9s,QJs-Q9s,JTs-J9s,T9s,98s",

        # Loose (top ~35%)
        'co_open': "AA-22,AKo-A5o,KQo-K9o,QJo-QTo,JTo,AKs-A2s,KQs-K6s,QJs-Q8s,JTs-J8s,T9s-T8s,98s-97s,87s,76s,65s",

        # Very loose (top ~45%)
        'btn_open': "AA-22,AKo-A2o,KQo-K7o,QJo-Q9o,JTo-J9o,T9o,98o,AKs-A2s,KQs-K2s,QJs-Q6s,JTs-J7s,T9s-T7s,98s-96s,87s-86s,76s-75s,65s,54s",

        # 3-bet ranges
        '3bet_value': "AA,KK,QQ,AKs,AKo",
        '3bet_bluff': "A5s-A2s,76s,65s,54s",
        '3bet_linear': "AA-TT,AKo-AQo,AKs-AJs,KQs",

        # Defense ranges
        'bb_defend_vs_2x': "AA-22,AKo-A7o,KQo-KTo,QJo-QTo,JTo,AKs-A2s,KQs-K8s,QJs-Q8s,JTs-J8s,T9s-T8s,98s-97s,87s-86s,76s-75s,65s-64s,54s",
    }

    def __init__(self):
        self.custom_ranges: Dict[str, Range] = {}

    def get_preset(self, name: str) -> Range:
        """Get a preset range by name"""
        notation = self.PRESETS.get(name)
        if notation:
            return Range.from_notation(notation)
        raise ValueError(f"Unknown preset: {name}")

    def list_presets(self) -> List[str]:
        """List all available preset names"""
        return list(self.PRESETS.keys())

    def save_range(self, name: str, range_obj: Range) -> None:
        """Save a custom range"""
        self.custom_ranges[name] = range_obj

    def load_range(self, name: str) -> Range:
        """Load a saved range"""
        if name in self.custom_ranges:
            return self.custom_ranges[name]
        return self.get_preset(name)

    def parse(self, notation: str) -> Range:
        """Parse range notation"""
        return Range.from_notation(notation)


# === Standalone Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n=== Range Manager Test ===\n", "cyan", attrs=['bold'])

    # Test parsing
    cprint("Parsing Tests:", "yellow")

    test_notations = [
        "AA,KK,QQ",
        "QQ-TT",
        "AKs-ATs",
        "99+",
        "ATs+",
        "AA,KK,AKs,QQ-TT,ATs+,88-66"
    ]

    for notation in test_notations:
        range_obj = Range.from_notation(notation)
        cprint(f"\n  Input: {notation}", "white")
        cprint(f"  Hands: {len(range_obj)} | {range_obj.percentage():.1f}%", "cyan")
        cprint(f"  Output: {range_obj.to_notation()}", "green")

    # Test visualization
    cprint("\n\nVisualization Test:", "yellow")
    btn_range = Range.from_notation("AA-22,AKo-ATo,KQo,AKs-A2s,KQs-KTs,QJs-QTs,JTs,T9s,98s,87s,76s")
    print(btn_range.visualize())

    # Test sampling
    cprint("\n\nSampling Test:", "yellow")
    sample_range = Range.from_notation("AA,KK,AKs")
    samples = [sample_range.sample() for _ in range(5)]
    for c1, c2 in samples:
        cprint(f"  Sampled: {c1.pretty()} {c2.pretty()}", "white")

    # Test presets
    cprint("\n\nPresets:", "yellow")
    manager = RangeManager()
    for preset in manager.list_presets()[:3]:
        r = manager.get_preset(preset)
        cprint(f"  {preset}: {r.percentage():.1f}%", "white")
