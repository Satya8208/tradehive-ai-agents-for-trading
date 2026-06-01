"""
🎯 Solver Lite - Pre-computed GTO Solutions for Common Spots
Fast lookup for the most common poker situations
Built with love by TradeHive
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum


class BoardTexture(Enum):
    """Common flop texture categories"""
    DRY_PAIRED = "dry_paired"           # e.g., K72r
    DRY_UNPAIRED = "dry_unpaired"       # e.g., A82r
    MONOTONE = "monotone"                # e.g., Qh 8h 3h
    TWO_TONE_HIGH = "two_tone_high"     # e.g., Kh Qh 7c
    TWO_TONE_LOW = "two_tone_low"       # e.g., Kc 7h 4h
    CONNECTED_HIGH = "connected_high"   # e.g., QJT
    CONNECTED_MID = "connected_mid"     # e.g., 987
    WET_BROADWAY = "wet_broadway"       # e.g., KQJ two-tone
    DYNAMIC = "dynamic"                  # Multiple draws possible


class HandStrength(Enum):
    """Hand strength categories"""
    NUTS = "nuts"                       # Best possible hand
    VERY_STRONG = "very_strong"         # Sets, two pair+
    TOP_PAIR_GOOD = "top_pair_good"     # TPTK, overpair
    TOP_PAIR_WEAK = "top_pair_weak"     # TP weak kicker
    MIDDLE_PAIR = "middle_pair"
    WEAK_PAIR = "weak_pair"
    DRAW_STRONG = "draw_strong"         # Nut flush draw, OESD
    DRAW_WEAK = "draw_weak"             # Gutshot, weak FD
    AIR = "air"                         # No made hand, weak draw


@dataclass
class SolverSolution:
    """Pre-computed solution for a spot"""
    action: str                         # Primary action
    frequency: float                    # Frequency to take action (0-1)
    sizing: float                       # Bet size as fraction of pot
    ev: float                           # Expected value (BB won per hand)
    alternatives: List[Tuple[str, float]]  # Alternative actions with freq
    reasoning: str                      # Explanation


class SolverLite:
    """
    🎯 Fast GTO Solutions Engine

    Pre-computed solutions for:
    - C-bet decisions on common flops
    - Facing bets with various hand strengths
    - Turn/river barrel decisions
    - Check-raise frequencies

    Solutions are based on GTO solver outputs for typical spots.
    """

    # === C-BET SOLUTIONS ===
    # Format: (texture, in_position) -> (bet_freq, sizing, check_freq)
    CBET_SOLUTIONS = {
        # DRY boards - high c-bet frequency, small sizing
        (BoardTexture.DRY_PAIRED, True): (0.85, 0.33, 0.15),
        (BoardTexture.DRY_PAIRED, False): (0.70, 0.33, 0.30),
        (BoardTexture.DRY_UNPAIRED, True): (0.80, 0.33, 0.20),
        (BoardTexture.DRY_UNPAIRED, False): (0.65, 0.33, 0.35),

        # Wet boards - polarized, larger sizing
        (BoardTexture.MONOTONE, True): (0.45, 0.50, 0.55),
        (BoardTexture.MONOTONE, False): (0.35, 0.50, 0.65),
        (BoardTexture.TWO_TONE_HIGH, True): (0.55, 0.50, 0.45),
        (BoardTexture.TWO_TONE_HIGH, False): (0.45, 0.50, 0.55),

        # Connected boards - careful approach
        (BoardTexture.CONNECTED_HIGH, True): (0.50, 0.66, 0.50),
        (BoardTexture.CONNECTED_HIGH, False): (0.40, 0.66, 0.60),
        (BoardTexture.CONNECTED_MID, True): (0.55, 0.50, 0.45),
        (BoardTexture.CONNECTED_MID, False): (0.45, 0.50, 0.55),

        # Dynamic/wet broadway - polarized
        (BoardTexture.WET_BROADWAY, True): (0.40, 0.75, 0.60),
        (BoardTexture.WET_BROADWAY, False): (0.30, 0.75, 0.70),
        (BoardTexture.DYNAMIC, True): (0.45, 0.66, 0.55),
        (BoardTexture.DYNAMIC, False): (0.35, 0.66, 0.65),
    }

    # === FACING BET SOLUTIONS ===
    # Format: (hand_strength, bet_size_category) -> (call_freq, raise_freq, fold_freq)
    FACING_BET = {
        # vs 33% pot bet
        (HandStrength.NUTS, "small"): (0.30, 0.70, 0.00),
        (HandStrength.VERY_STRONG, "small"): (0.50, 0.50, 0.00),
        (HandStrength.TOP_PAIR_GOOD, "small"): (0.90, 0.10, 0.00),
        (HandStrength.TOP_PAIR_WEAK, "small"): (0.85, 0.05, 0.10),
        (HandStrength.MIDDLE_PAIR, "small"): (0.70, 0.00, 0.30),
        (HandStrength.WEAK_PAIR, "small"): (0.45, 0.00, 0.55),
        (HandStrength.DRAW_STRONG, "small"): (0.60, 0.30, 0.10),
        (HandStrength.DRAW_WEAK, "small"): (0.40, 0.05, 0.55),
        (HandStrength.AIR, "small"): (0.00, 0.15, 0.85),

        # vs 66% pot bet
        (HandStrength.NUTS, "medium"): (0.25, 0.75, 0.00),
        (HandStrength.VERY_STRONG, "medium"): (0.45, 0.55, 0.00),
        (HandStrength.TOP_PAIR_GOOD, "medium"): (0.80, 0.15, 0.05),
        (HandStrength.TOP_PAIR_WEAK, "medium"): (0.65, 0.05, 0.30),
        (HandStrength.MIDDLE_PAIR, "medium"): (0.45, 0.00, 0.55),
        (HandStrength.WEAK_PAIR, "medium"): (0.25, 0.00, 0.75),
        (HandStrength.DRAW_STRONG, "medium"): (0.55, 0.25, 0.20),
        (HandStrength.DRAW_WEAK, "medium"): (0.25, 0.05, 0.70),
        (HandStrength.AIR, "medium"): (0.00, 0.10, 0.90),

        # vs 100%+ pot bet
        (HandStrength.NUTS, "large"): (0.20, 0.80, 0.00),
        (HandStrength.VERY_STRONG, "large"): (0.40, 0.55, 0.05),
        (HandStrength.TOP_PAIR_GOOD, "large"): (0.60, 0.10, 0.30),
        (HandStrength.TOP_PAIR_WEAK, "large"): (0.40, 0.00, 0.60),
        (HandStrength.MIDDLE_PAIR, "large"): (0.20, 0.00, 0.80),
        (HandStrength.WEAK_PAIR, "large"): (0.10, 0.00, 0.90),
        (HandStrength.DRAW_STRONG, "large"): (0.40, 0.15, 0.45),
        (HandStrength.DRAW_WEAK, "large"): (0.10, 0.00, 0.90),
        (HandStrength.AIR, "large"): (0.00, 0.05, 0.95),
    }

    # === VALUE BET RIVER SOLUTIONS ===
    # Format: hand_strength -> (bet_freq, sizing, check_freq)
    RIVER_VALUE = {
        HandStrength.NUTS: (0.95, 1.0, 0.05),
        HandStrength.VERY_STRONG: (0.80, 0.75, 0.20),
        HandStrength.TOP_PAIR_GOOD: (0.55, 0.50, 0.45),
        HandStrength.TOP_PAIR_WEAK: (0.30, 0.33, 0.70),
        HandStrength.MIDDLE_PAIR: (0.10, 0.33, 0.90),
        HandStrength.WEAK_PAIR: (0.00, 0.0, 1.00),
    }

    # === PREFLOP SOLUTIONS ===
    # Opening ranges by position (% of hands)
    OPEN_RANGES = {
        "UTG": 12,  # Top 12%
        "UTG1": 14,
        "UTG2": 16,
        "MP": 18,
        "HJ": 22,
        "CO": 27,
        "BTN": 45,
        "SB": 40,  # Steal
    }

    # 3-bet ranges vs position (% of hands)
    THREE_BET_RANGES = {
        ("BTN", "UTG"): 4,   # Tight 3-bet vs early
        ("BTN", "CO"): 8,   # Wider vs cutoff
        ("SB", "BTN"): 12,  # Wide vs BTN
        ("BB", "SB"): 14,   # Widest vs SB
        ("BB", "BTN"): 10,
        ("BB", "CO"): 8,
        ("BB", "MP"): 5,
    }

    def __init__(self):
        self.lookups = 0

    def get_cbet_solution(self,
                          texture: BoardTexture,
                          in_position: bool,
                          hand_strength: HandStrength = None) -> SolverSolution:
        """
        Get c-bet solution for a flop texture

        Args:
            texture: Board texture category
            in_position: Whether hero is in position
            hand_strength: Optional hand strength for weighting
        """
        self.lookups += 1

        key = (texture, in_position)
        if key not in self.CBET_SOLUTIONS:
            # Default for unknown textures
            bet_freq, sizing, check_freq = 0.50, 0.50, 0.50
        else:
            bet_freq, sizing, check_freq = self.CBET_SOLUTIONS[key]

        # Adjust based on hand strength
        if hand_strength:
            if hand_strength in [HandStrength.NUTS, HandStrength.VERY_STRONG]:
                bet_freq = min(1.0, bet_freq + 0.15)
            elif hand_strength in [HandStrength.DRAW_STRONG]:
                bet_freq = min(1.0, bet_freq + 0.10)
            elif hand_strength == HandStrength.AIR:
                bet_freq = max(0, bet_freq - 0.10)

        primary_action = "BET" if bet_freq > check_freq else "CHECK"

        return SolverSolution(
            action=primary_action,
            frequency=bet_freq if primary_action == "BET" else check_freq,
            sizing=sizing,
            ev=0.5 if bet_freq > 0.5 else 0.0,  # Simplified EV
            alternatives=[
                ("CHECK", check_freq) if primary_action == "BET" else ("BET", bet_freq)
            ],
            reasoning=self._cbet_reasoning(texture, in_position, bet_freq, sizing)
        )

    def get_facing_bet_solution(self,
                                 hand_strength: HandStrength,
                                 bet_size: float,
                                 pot_size: float) -> SolverSolution:
        """
        Get solution for facing a bet

        Args:
            hand_strength: Hero's hand strength category
            bet_size: Villain's bet size
            pot_size: Pot before villain's bet
        """
        self.lookups += 1

        # Categorize bet size
        ratio = bet_size / pot_size
        if ratio <= 0.40:
            size_cat = "small"
        elif ratio <= 0.80:
            size_cat = "medium"
        else:
            size_cat = "large"

        key = (hand_strength, size_cat)
        if key not in self.FACING_BET:
            call_freq, raise_freq, fold_freq = 0.33, 0.0, 0.67
        else:
            call_freq, raise_freq, fold_freq = self.FACING_BET[key]

        # Determine primary action
        actions = [("CALL", call_freq), ("RAISE", raise_freq), ("FOLD", fold_freq)]
        actions.sort(key=lambda x: x[1], reverse=True)

        primary_action, primary_freq = actions[0]

        return SolverSolution(
            action=primary_action,
            frequency=primary_freq,
            sizing=2.5 if primary_action == "RAISE" else 0,  # 2.5x raise size
            ev=self._estimate_ev(hand_strength, primary_action, ratio),
            alternatives=actions[1:],
            reasoning=self._facing_bet_reasoning(hand_strength, size_cat, primary_action)
        )

    def get_river_value_solution(self,
                                  hand_strength: HandStrength,
                                  in_position: bool) -> SolverSolution:
        """
        Get river value betting solution

        Args:
            hand_strength: Hero's hand strength
            in_position: Whether hero is in position
        """
        self.lookups += 1

        if hand_strength not in self.RIVER_VALUE:
            return SolverSolution(
                action="CHECK",
                frequency=1.0,
                sizing=0,
                ev=0,
                alternatives=[],
                reasoning="Hand too weak for value betting on river."
            )

        bet_freq, sizing, check_freq = self.RIVER_VALUE[hand_strength]

        # Adjust for position
        if not in_position:
            bet_freq *= 0.85  # Less value betting OOP
            check_freq = 1 - bet_freq

        primary_action = "BET" if bet_freq > check_freq else "CHECK"

        return SolverSolution(
            action=primary_action,
            frequency=bet_freq if primary_action == "BET" else check_freq,
            sizing=sizing,
            ev=sizing * bet_freq * 0.6,  # Rough EV estimate
            alternatives=[
                ("CHECK", check_freq) if primary_action == "BET" else ("BET", bet_freq)
            ],
            reasoning=self._river_reasoning(hand_strength, primary_action, sizing, in_position)
        )

    def get_preflop_open_range(self, position: str) -> int:
        """Get opening range percentage for position"""
        return self.OPEN_RANGES.get(position.upper(), 15)

    def get_3bet_range(self, hero_pos: str, villain_pos: str) -> int:
        """Get 3-bet range percentage for positions"""
        key = (hero_pos.upper(), villain_pos.upper())
        return self.THREE_BET_RANGES.get(key, 6)

    def _cbet_reasoning(self, texture: BoardTexture, ip: bool, freq: float, sizing: float) -> str:
        """Generate reasoning for c-bet solution"""
        pos_str = "in position" if ip else "out of position"

        if freq > 0.70:
            return f"High c-bet frequency on {texture.value} textures {pos_str}. Small sizing exploits fold equity."
        elif freq > 0.45:
            return f"Moderate c-bet frequency on {texture.value}. Balance value and bluffs with polarized approach."
        else:
            return f"Low c-bet frequency recommended on {texture.value} {pos_str}. Board favors caller's range."

    def _facing_bet_reasoning(self, strength: HandStrength, size: str, action: str) -> str:
        """Generate reasoning for facing bet"""
        if action == "RAISE":
            return f"With {strength.value}, raise for value/protection vs {size} bet."
        elif action == "CALL":
            return f"With {strength.value}, calling is profitable vs {size} sizing. Avoid bloating pot OOP."
        else:
            return f"With {strength.value}, folding vs {size} bet is likely correct. Not enough equity to continue."

    def _river_reasoning(self, strength: HandStrength, action: str, sizing: float, ip: bool) -> str:
        """Generate reasoning for river value bet"""
        pos_str = "in position" if ip else "out of position"

        if action == "BET":
            return f"With {strength.value} {pos_str}, betting {sizing*100:.0f}% pot for value. Expect calls from worse hands."
        else:
            return f"With {strength.value} {pos_str}, checking for showdown value. Thin value bet risks raise."

    def _estimate_ev(self, strength: HandStrength, action: str, bet_ratio: float) -> float:
        """Rough EV estimate for an action"""
        base_ev = {
            HandStrength.NUTS: 2.0,
            HandStrength.VERY_STRONG: 1.5,
            HandStrength.TOP_PAIR_GOOD: 0.8,
            HandStrength.TOP_PAIR_WEAK: 0.4,
            HandStrength.MIDDLE_PAIR: 0.1,
            HandStrength.WEAK_PAIR: -0.1,
            HandStrength.DRAW_STRONG: 0.3,
            HandStrength.DRAW_WEAK: -0.2,
            HandStrength.AIR: -0.5,
        }.get(strength, 0)

        if action == "FOLD":
            return 0  # folding is EV neutral for this hand
        elif action == "RAISE":
            return base_ev * 1.5
        else:  # CALL
            return base_ev - (bet_ratio * 0.3)

    def get_stats(self) -> Dict:
        """Get solver usage stats"""
        return {
            "total_lookups": self.lookups,
            "cbet_textures": len(self.CBET_SOLUTIONS),
            "facing_bet_spots": len(self.FACING_BET),
        }


# === Quick Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n🎯 Testing Solver Lite...\n", "cyan", attrs=["bold"])

    solver = SolverLite()

    # Test c-bet
    cprint("📍 C-bet on dry A72r board IP:", "yellow")
    solution = solver.get_cbet_solution(
        BoardTexture.DRY_UNPAIRED,
        in_position=True,
        hand_strength=HandStrength.TOP_PAIR_GOOD
    )
    cprint(f"  Action: {solution.action} @ {solution.frequency*100:.0f}%", "green")
    cprint(f"  Sizing: {solution.sizing*100:.0f}% pot", "green")
    cprint(f"  {solution.reasoning}", "white")

    # Test facing bet
    cprint("\n📍 Facing 75% pot bet with middle pair:", "yellow")
    solution = solver.get_facing_bet_solution(
        HandStrength.MIDDLE_PAIR,
        bet_size=15,
        pot_size=20
    )
    cprint(f"  Action: {solution.action} @ {solution.frequency*100:.0f}%", "green")
    cprint(f"  {solution.reasoning}", "white")

    # Test river value
    cprint("\n📍 River value bet with very strong hand IP:", "yellow")
    solution = solver.get_river_value_solution(
        HandStrength.VERY_STRONG,
        in_position=True
    )
    cprint(f"  Action: {solution.action} @ {solution.frequency*100:.0f}%", "green")
    cprint(f"  Sizing: {solution.sizing*100:.0f}% pot", "green")
    cprint(f"  {solution.reasoning}", "white")

    cprint(f"\n📊 Stats: {solver.get_stats()}", "cyan")
