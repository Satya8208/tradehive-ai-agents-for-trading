"""
🧠 Neural Hand Evaluator
Fast hand strength estimation using pre-computed lookup tables and heuristics
(Simulates neural network behavior without ML dependencies)
Built with love by TradeHive
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from enum import Enum
import itertools


class HandCategory(Enum):
    """Hand categories by relative strength"""
    MONSTER = 5        # Nuts or near-nuts
    VERY_STRONG = 4    # Sets, two pair, strong overpairs
    STRONG = 3         # Top pair good kicker, overpair
    MEDIUM = 2         # Middle pair, weak top pair
    WEAK = 1           # Bottom pair, ace high
    TRASH = 0          # Missed completely


@dataclass
class NeuralEvaluation:
    """Result of neural evaluation"""
    raw_strength: float          # 0-1 strength score
    category: HandCategory
    confidence: float            # How confident in evaluation
    hand_description: str        # Human readable
    equity_estimate: float       # Estimated equity vs random
    is_drawing: bool             # Are we on a draw
    draw_outs: int               # Number of outs if drawing
    blockers: List[str]          # Cards we block
    implied_odds_factor: float   # Multiplier for implied odds plays


class NeuralHandEvaluator:
    """
    🧠 Fast Neural-Style Hand Evaluation

    Uses pre-computed heuristics to rapidly evaluate hand strength
    without expensive Monte Carlo simulation.

    Features:
    - Sub-millisecond evaluation
    - Board texture awareness
    - Draw detection
    - Blocker analysis
    - Implied odds estimation

    Note: This simulates neural network behavior using lookup tables
    and heuristics rather than actual ML models.
    """

    # Hand rank values (0-12 for 2-A)
    RANK_VALUES = {'2': 0, '3': 1, '4': 2, '5': 3, '6': 4, '7': 5, '8': 6,
                  '9': 7, 'T': 8, 'J': 9, 'Q': 10, 'K': 11, 'A': 12}

    # Starting hand rankings (simplified EV-based)
    STARTING_HAND_TIERS = {
        # Tier 1: Premium (top 2.5%)
        "AA": 1.0, "KK": 0.98, "QQ": 0.95, "AKs": 0.93,
        # Tier 2: Very Strong (top 5%)
        "JJ": 0.90, "AKo": 0.88, "AQs": 0.86, "TT": 0.84,
        # Tier 3: Strong (top 10%)
        "AQo": 0.82, "AJs": 0.80, "KQs": 0.78, "99": 0.76,
        "ATs": 0.74, "AJo": 0.72, "KJs": 0.70, "88": 0.68,
        # Tier 4: Playable (top 20%)
        "KQo": 0.66, "QJs": 0.64, "ATo": 0.62, "A9s": 0.60,
        "77": 0.58, "KTs": 0.56, "A8s": 0.54, "QTs": 0.52,
        "KJo": 0.50, "JTs": 0.48, "66": 0.46,
        # Tier 5: Marginal
        "A7s": 0.44, "K9s": 0.42, "55": 0.40, "QJo": 0.38,
        "T9s": 0.36, "A6s": 0.34, "44": 0.32, "A5s": 0.30,
        "98s": 0.28, "33": 0.26, "22": 0.24, "87s": 0.22,
        "76s": 0.20, "65s": 0.18, "A4s": 0.16, "A3s": 0.14,
        "A2s": 0.12,
    }

    # Made hand multipliers on flop
    MADE_HAND_MULTIPLIERS = {
        "straight_flush": 2.5,
        "quads": 2.4,
        "full_house": 2.2,
        "flush": 2.0,
        "straight": 1.9,
        "trips": 1.7,
        "two_pair": 1.5,
        "overpair": 1.35,
        "top_pair_top_kicker": 1.3,
        "top_pair": 1.2,
        "overpair_under_board": 1.15,
        "middle_pair": 0.9,
        "bottom_pair": 0.7,
        "ace_high": 0.5,
        "no_pair": 0.3,
    }

    def __init__(self):
        self.evaluations = 0

    def evaluate(self,
                 hole_cards: str,
                 board: str = "") -> NeuralEvaluation:
        """
        Evaluate hand strength instantly

        Args:
            hole_cards: Cards like "AhKs"
            board: Board cards like "Qh Jc 2d"

        Returns:
            NeuralEvaluation with strength scores
        """
        self.evaluations += 1

        # Parse inputs
        cards = self._parse_cards(hole_cards)
        board_cards = self._parse_cards(board) if board else []

        if not cards:
            return self._empty_evaluation()

        # Preflop evaluation
        if not board_cards:
            return self._evaluate_preflop(cards)

        # Postflop evaluation
        return self._evaluate_postflop(cards, board_cards)

    def quick_equity(self, hole_cards: str, board: str = "") -> float:
        """
        Super fast equity estimate (no simulation)

        Returns estimated equity vs a random hand
        """
        eval_result = self.evaluate(hole_cards, board)
        return eval_result.equity_estimate

    def _evaluate_preflop(self, cards: List[Tuple[str, str]]) -> NeuralEvaluation:
        """Preflop hand evaluation"""
        hand_key = self._to_hand_notation(cards)

        # Look up in tier table
        base_strength = self.STARTING_HAND_TIERS.get(hand_key)

        if base_strength is None:
            # Estimate for hands not in table
            base_strength = self._estimate_unknown_hand(cards)

        # Determine category
        if base_strength >= 0.90:
            category = HandCategory.MONSTER
        elif base_strength >= 0.75:
            category = HandCategory.VERY_STRONG
        elif base_strength >= 0.55:
            category = HandCategory.STRONG
        elif base_strength >= 0.35:
            category = HandCategory.MEDIUM
        elif base_strength >= 0.15:
            category = HandCategory.WEAK
        else:
            category = HandCategory.TRASH

        # Equity estimate
        equity = 0.50 + (base_strength - 0.50) * 0.60

        return NeuralEvaluation(
            raw_strength=base_strength,
            category=category,
            confidence=0.85,
            hand_description=f"{hand_key} preflop",
            equity_estimate=equity,
            is_drawing=False,
            draw_outs=0,
            blockers=self._get_blockers(cards),
            implied_odds_factor=self._get_implied_odds_factor(cards, base_strength)
        )

    def _evaluate_postflop(self,
                           cards: List[Tuple[str, str]],
                           board: List[Tuple[str, str]]) -> NeuralEvaluation:
        """Postflop hand evaluation"""
        all_cards = cards + board

        # Check for made hands
        has_flush, flush_outs = self._check_flush(cards, board)
        has_straight, straight_outs = self._check_straight(all_cards)
        pair_type = self._check_pairs(cards, board)

        # Calculate raw strength
        base_strength = 0.0
        hand_desc = ""

        if has_flush:
            multiplier = self.MADE_HAND_MULTIPLIERS["flush"]
            base_strength = min(1.0, 0.75 * multiplier)
            hand_desc = "Flush"
        elif has_straight:
            multiplier = self.MADE_HAND_MULTIPLIERS["straight"]
            base_strength = min(1.0, 0.70 * multiplier)
            hand_desc = "Straight"
        elif pair_type == "trips":
            multiplier = self.MADE_HAND_MULTIPLIERS["trips"]
            base_strength = min(1.0, 0.60 * multiplier)
            hand_desc = "Three of a kind"
        elif pair_type == "two_pair":
            multiplier = self.MADE_HAND_MULTIPLIERS["two_pair"]
            base_strength = min(1.0, 0.55 * multiplier)
            hand_desc = "Two pair"
        elif pair_type == "overpair":
            multiplier = self.MADE_HAND_MULTIPLIERS["overpair"]
            base_strength = min(1.0, 0.50 * multiplier)
            hand_desc = "Overpair"
        elif pair_type == "top_pair_top_kicker":
            multiplier = self.MADE_HAND_MULTIPLIERS["top_pair_top_kicker"]
            base_strength = min(1.0, 0.45 * multiplier)
            hand_desc = "Top pair top kicker"
        elif pair_type == "top_pair":
            multiplier = self.MADE_HAND_MULTIPLIERS["top_pair"]
            base_strength = min(1.0, 0.40 * multiplier)
            hand_desc = "Top pair"
        elif pair_type == "middle_pair":
            multiplier = self.MADE_HAND_MULTIPLIERS["middle_pair"]
            base_strength = min(1.0, 0.30 * multiplier)
            hand_desc = "Middle pair"
        elif pair_type == "bottom_pair":
            multiplier = self.MADE_HAND_MULTIPLIERS["bottom_pair"]
            base_strength = min(1.0, 0.20 * multiplier)
            hand_desc = "Bottom pair"
        else:
            # No made hand, check for high cards
            high_card = max(self.RANK_VALUES.get(c[0], 0) for c in cards)
            if high_card >= 12:  # Ace
                base_strength = 0.25
                hand_desc = "Ace high"
            else:
                base_strength = 0.15
                hand_desc = "No pair"

        # Add draw value
        is_drawing = False
        total_outs = 0

        if flush_outs >= 9:  # Flush draw
            is_drawing = True
            total_outs = flush_outs
            base_strength = max(base_strength, 0.45)
            hand_desc = f"{hand_desc} + flush draw" if hand_desc else "Flush draw"

        if straight_outs >= 8:  # OESD
            is_drawing = True
            total_outs = max(total_outs, straight_outs)
            base_strength = max(base_strength, 0.40)
            hand_desc = f"{hand_desc} + OESD" if "+" not in hand_desc else hand_desc
        elif straight_outs >= 4:  # Gutshot
            is_drawing = True
            total_outs = max(total_outs, straight_outs)
            base_strength = max(base_strength, 0.30)

        # Determine category
        if base_strength >= 0.85:
            category = HandCategory.MONSTER
        elif base_strength >= 0.70:
            category = HandCategory.VERY_STRONG
        elif base_strength >= 0.50:
            category = HandCategory.STRONG
        elif base_strength >= 0.30:
            category = HandCategory.MEDIUM
        elif base_strength >= 0.15:
            category = HandCategory.WEAK
        else:
            category = HandCategory.TRASH

        # Equity vs random (simplified)
        equity = base_strength * 0.9 + 0.05
        if is_drawing and len(board) <= 3:
            equity += total_outs * 0.02  # Outs add equity

        return NeuralEvaluation(
            raw_strength=base_strength,
            category=category,
            confidence=0.80,
            hand_description=hand_desc,
            equity_estimate=min(0.95, equity),
            is_drawing=is_drawing,
            draw_outs=total_outs,
            blockers=self._get_blockers(cards),
            implied_odds_factor=self._get_implied_odds_factor(cards, base_strength)
        )

    def _parse_cards(self, notation: str) -> List[Tuple[str, str]]:
        """Parse card notation to (rank, suit) tuples"""
        notation = notation.replace(" ", "")
        cards = []
        i = 0
        while i < len(notation) - 1:
            rank = notation[i].upper()
            suit = notation[i + 1].lower()
            if rank in "23456789TJQKA" and suit in "hdcs":
                cards.append((rank, suit))
            i += 2
        return cards

    def _to_hand_notation(self, cards: List[Tuple[str, str]]) -> str:
        """Convert cards to standard notation (e.g., AKs, QJo)"""
        if len(cards) != 2:
            return ""

        r1, s1 = cards[0]
        r2, s2 = cards[1]

        # Order by rank
        v1 = self.RANK_VALUES.get(r1, 0)
        v2 = self.RANK_VALUES.get(r2, 0)

        if v1 < v2:
            r1, r2 = r2, r1
            s1, s2 = s2, s1

        # Pairs
        if r1 == r2:
            return f"{r1}{r2}"

        # Suited vs offsuit
        suited = "s" if s1 == s2 else "o"
        return f"{r1}{r2}{suited}"

    def _estimate_unknown_hand(self, cards: List[Tuple[str, str]]) -> float:
        """Estimate value for hands not in lookup table"""
        if len(cards) != 2:
            return 0.1

        r1, r2 = cards[0][0], cards[1][0]
        v1 = self.RANK_VALUES.get(r1, 0)
        v2 = self.RANK_VALUES.get(r2, 0)
        suited = cards[0][1] == cards[1][1]
        connected = abs(v1 - v2) <= 2

        # Base on high card values
        base = (v1 + v2) / 24  # 0 to 1

        if suited:
            base += 0.05
        if connected:
            base += 0.03

        return min(0.5, base)

    def _check_flush(self,
                     hole_cards: List[Tuple[str, str]],
                     board: List[Tuple[str, str]]) -> Tuple[bool, int]:
        """Check for flush/flush draw"""
        all_cards = hole_cards + board
        suit_counts = {}

        for rank, suit in all_cards:
            suit_counts[suit] = suit_counts.get(suit, 0) + 1

        # Check hole card suits
        hole_suits = [c[1] for c in hole_cards]

        for suit, count in suit_counts.items():
            if count >= 5 and suit in hole_suits:
                return True, 0  # Made flush
            elif count >= 4 and suit in hole_suits:
                return False, 9  # Flush draw
            elif count >= 3 and hole_suits[0] == hole_suits[1] == suit:
                return False, 9  # Suited with 3 on board

        return False, 0

    def _check_straight(self, all_cards: List[Tuple[str, str]]) -> Tuple[bool, int]:
        """Check for straight/straight draw"""
        ranks = sorted(set(self.RANK_VALUES.get(c[0], 0) for c in all_cards))

        # Check for made straight (5 consecutive)
        for i in range(len(ranks) - 4):
            if ranks[i+4] - ranks[i] == 4:
                return True, 0

        # Check for wheel (A-2-3-4-5)
        if 12 in ranks:  # Has Ace
            wheel_ranks = [0, 1, 2, 3, 12]  # A,2,3,4,5
            if len(set(ranks) & set(wheel_ranks)) >= 4:
                return False, 4  # Wheel draw

        # Check for OESD or gutshot
        for i in range(len(ranks) - 3):
            gap = ranks[i+3] - ranks[i]
            if gap == 3:  # 4 in a row
                return False, 8  # OESD
            elif gap == 4:  # 4 with one gap
                return False, 4  # Gutshot

        return False, 0

    def _check_pairs(self,
                     hole_cards: List[Tuple[str, str]],
                     board: List[Tuple[str, str]]) -> str:
        """Determine pair type"""
        hole_ranks = [c[0] for c in hole_cards]
        board_ranks = [c[0] for c in board]

        hole_values = sorted([self.RANK_VALUES.get(r, 0) for r in hole_ranks], reverse=True)
        board_values = sorted([self.RANK_VALUES.get(r, 0) for r in board_ranks], reverse=True)

        # Pocket pair
        if len(set(hole_ranks)) == 1:
            pair_value = hole_values[0]
            if board_values and pair_value in board_values:
                return "trips"  # Set
            if board_values and pair_value > max(board_values):
                return "overpair"
            return "underpair"

        # Hit the board
        hits = [h for h in hole_values if h in board_values]

        if len(hits) >= 2:
            return "two_pair"
        elif len(hits) == 1:
            hit_value = hits[0]
            board_max = max(board_values) if board_values else 0
            kicker = max(v for v in hole_values if v != hit_value) if len(hole_values) > 1 else 0

            if hit_value == board_max:
                if kicker >= 12:  # Ace kicker
                    return "top_pair_top_kicker"
                return "top_pair"
            elif board_values and hit_value >= board_values[len(board_values)//2]:
                return "middle_pair"
            else:
                return "bottom_pair"

        return "no_pair"

    def _get_blockers(self, cards: List[Tuple[str, str]]) -> List[str]:
        """Get what hands we block"""
        blockers = []
        ranks = [c[0] for c in cards]

        if 'A' in ranks:
            blockers.append("nut flush draws")
            blockers.append("AA")
        if 'K' in ranks:
            blockers.append("KK")
            blockers.append("AK")

        return blockers

    def _get_implied_odds_factor(self,
                                  cards: List[Tuple[str, str]],
                                  strength: float) -> float:
        """Calculate implied odds factor"""
        # Suited hands have better implied odds
        if len(cards) == 2 and cards[0][1] == cards[1][1]:
            return 1.3

        # Small pairs have set value
        ranks = [c[0] for c in cards]
        if len(set(ranks)) == 1 and self.RANK_VALUES.get(ranks[0], 0) <= 9:
            return 1.4

        # Connected hands
        if len(cards) == 2:
            v1 = self.RANK_VALUES.get(cards[0][0], 0)
            v2 = self.RANK_VALUES.get(cards[1][0], 0)
            if abs(v1 - v2) <= 2:
                return 1.2

        return 1.0

    def _empty_evaluation(self) -> NeuralEvaluation:
        """Return empty evaluation"""
        return NeuralEvaluation(
            raw_strength=0,
            category=HandCategory.TRASH,
            confidence=0,
            hand_description="Invalid",
            equity_estimate=0,
            is_drawing=False,
            draw_outs=0,
            blockers=[],
            implied_odds_factor=1.0
        )

    def get_stats(self) -> Dict:
        """Get evaluator stats"""
        return {
            "evaluations": self.evaluations,
            "starting_hands_indexed": len(self.STARTING_HAND_TIERS)
        }


# === Quick Test ===
if __name__ == "__main__":
    from termcolor import cprint
    import time

    cprint("\n🧠 Testing Neural Hand Evaluator...\n", "cyan", attrs=["bold"])

    evaluator = NeuralHandEvaluator()

    # Test cases
    test_hands = [
        ("AhKh", "", "Preflop AKs"),
        ("7c7d", "", "Preflop 77"),
        ("AhKs", "Kc 7h 2d", "Top pair top kicker"),
        ("9h8h", "7h 6h 2c", "Flush draw + OESD"),
        ("QcQd", "Jh 8c 3s", "Overpair"),
        ("AsKs", "Qs Js 2h", "Nut flush draw"),
    ]

    start = time.time()
    for hole, board, desc in test_hands:
        result = evaluator.evaluate(hole, board)
        cprint(f"\n📍 {desc}: {hole} on {board or 'preflop'}", "yellow")
        print(f"  Strength: {result.raw_strength:.2f} ({result.category.name})")
        print(f"  Equity: {result.equity_estimate*100:.1f}%")
        print(f"  Description: {result.hand_description}")
        if result.is_drawing:
            print(f"  Drawing: {result.draw_outs} outs")
        if result.blockers:
            print(f"  Blockers: {', '.join(result.blockers)}")

    elapsed = time.time() - start

    cprint(f"\n⚡ Evaluated {len(test_hands)} hands in {elapsed*1000:.2f}ms", "green")
    cprint(f"📊 Stats: {evaluator.get_stats()}", "cyan")
