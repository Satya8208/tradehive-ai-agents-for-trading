"""
🎯 Dynamic Range Adjustment Engine
Adjusts opening/calling ranges based on game dynamics
Built with love by TradeHive
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set
from enum import Enum
import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.poker.core.range_manager import Range, RangeManager
from src.agents.poker.ai.population_db import PopulationDatabase, StakeLevel, PlayerPool


class TableDynamic(Enum):
    """Current table dynamic"""
    PASSIVE = "passive"           # Low aggression, lots of limping
    AGGRESSIVE = "aggressive"     # High 3-bet frequency, action
    TIGHT = "tight"               # Low VPIP, nits
    LOOSE = "loose"               # High VPIP, many callers
    BALANCED = "balanced"         # Normal/tough table


class StackDepth(Enum):
    """Effective stack depth categories"""
    SHORT = "short"               # < 40bb
    MEDIUM = "medium"             # 40-100bb
    DEEP = "deep"                 # 100-200bb
    VERY_DEEP = "very_deep"       # 200bb+


@dataclass
class GameContext:
    """Current game context for range adjustment"""
    position: str                         # BTN, CO, MP, etc.
    stack_bb: float = 100                 # Effective stack in BB
    villain_vpip: float = 25              # Villain's VPIP
    villain_pfr: float = 18               # Villain's PFR
    villain_3bet: float = 7               # Villain's 3-bet %
    villain_fold_to_3bet: float = 55      # Villain's fold to 3-bet
    num_players: int = 6                  # Players at table
    table_dynamic: TableDynamic = TableDynamic.BALANCED
    is_live: bool = False
    ante_present: bool = False


@dataclass
class AdjustedRange:
    """Result of range adjustment"""
    base_range: str                       # Original range notation
    adjusted_range: str                   # Modified range
    adjustment_factor: float              # Multiplier (1.0 = no change)
    hands_added: List[str]                # Hands added to range
    hands_removed: List[str]              # Hands removed from range
    reasoning: List[str]                  # Why adjustments were made


class DynamicRangeEngine:
    """
    🎯 Dynamic Range Adjustment Engine

    Adjusts your ranges based on:
    - Table dynamics (passive/aggressive/etc.)
    - Villain tendencies
    - Stack depths
    - Position
    - Population tendencies

    Features:
    - Opening range widening/tightening
    - 3-bet range polarization/linearization
    - Calling range adjustments
    - Squeeze opportunities
    """

    # Base opening ranges by position (% of hands)
    BASE_OPEN_RANGES = {
        "UTG": ("77+,AJs+,KQs,AQo+", 10),
        "UTG1": ("66+,ATs+,KJs+,QJs,AJo+,KQo", 12),
        "UTG2": ("55+,A9s+,KTs+,QTs+,JTs,ATo+,KJo+", 14),
        "MP": ("44+,A7s+,K9s+,Q9s+,J9s+,T9s,A9o+,KTo+,QJo", 17),
        "HJ": ("33+,A4s+,K7s+,Q8s+,J8s+,T8s+,97s+,87s,A8o+,K9o+,QTo+,JTo", 21),
        "CO": ("22+,A2s+,K5s+,Q6s+,J7s+,T7s+,97s+,86s+,76s,65s,A5o+,K8o+,Q9o+,J9o+,T9o", 27),
        "BTN": ("22+,A2s+,K2s+,Q4s+,J6s+,T6s+,96s+,85s+,75s+,64s+,54s,A2o+,K5o+,Q7o+,J8o+,T8o+,98o", 40),
        "SB": ("22+,A2s+,K2s+,Q5s+,J7s+,T7s+,96s+,85s+,74s+,64s+,53s+,A2o+,K6o+,Q8o+,J9o+,T9o", 38),
    }

    # 3-bet ranges vs position
    BASE_3BET_RANGES = {
        ("BTN", "UTG"): ("QQ+,AKs,AKo", 3),  # Tight vs early
        ("BTN", "MP"): ("TT+,AQs+,AKo,KQs", 5),
        ("BTN", "CO"): ("88+,AJs+,KQs,AQo+,A5s-A4s,76s", 8),  # Polarized
        ("SB", "BTN"): ("77+,ATs+,KJs+,QJs,AJo+,KQo,A5s-A2s,K5s-K4s,87s,76s,65s", 12),
        ("BB", "BTN"): ("66+,A9s+,KTs+,QTs+,ATo+,KJo+,65s-54s,A8s-A5s", 10),
        ("BB", "SB"): ("55+,A8s+,K9s+,Q9s+,J9s+,A9o+,KTo+,QJo,76s-54s", 14),
    }

    # Hand categories for adjustment
    HAND_TIERS = {
        "premium": ["AA", "KK", "QQ", "JJ", "AKs", "AKo"],
        "strong": ["TT", "99", "AQs", "AQo", "AJs", "KQs"],
        "good": ["88", "77", "ATs", "AJo", "KJs", "QJs", "KQo"],
        "playable": ["66", "55", "A9s", "KTs", "QTs", "JTs", "ATo", "KJo"],
        "marginal": ["44", "33", "22", "A8s-A2s", "K9s-K5s", "Q9s", "T9s", "98s", "87s"],
        "speculative": ["76s", "65s", "54s", "86s", "75s", "A9o-A5o", "K9o-K7o"],
    }

    def __init__(self):
        self.range_manager = RangeManager()
        self.population_db = PopulationDatabase()
        self.adjustments_made = 0

    def get_adjusted_opening_range(self, context: GameContext) -> AdjustedRange:
        """
        Get adjusted opening range for position

        Args:
            context: Current game context
        """
        position = context.position.upper()
        if position not in self.BASE_OPEN_RANGES:
            position = "BTN"  # Default

        base_range, base_pct = self.BASE_OPEN_RANGES[position]
        adjustment = 1.0
        reasons = []
        hands_to_add = []
        hands_to_remove = []

        # === Stack Depth Adjustments ===
        stack_depth = self._get_stack_depth(context.stack_bb)

        if stack_depth == StackDepth.SHORT:
            # Tighten up, focus on high card hands
            adjustment *= 0.8
            reasons.append(f"Short stacked ({context.stack_bb}bb) - tightening range")
            hands_to_remove.extend(["33", "22", "65s", "54s"])
        elif stack_depth == StackDepth.DEEP:
            # Widen with speculative hands
            adjustment *= 1.1
            reasons.append(f"Deep stacked ({context.stack_bb}bb) - adding suited connectors")
            hands_to_add.extend(["86s", "75s", "64s", "T8s"])
        elif stack_depth == StackDepth.VERY_DEEP:
            adjustment *= 1.2
            reasons.append(f"Very deep ({context.stack_bb}bb) - speculative hands profitable")
            hands_to_add.extend(["85s", "74s", "53s", "K6s", "Q7s"])

        # === Table Dynamic Adjustments ===
        if context.table_dynamic == TableDynamic.PASSIVE:
            # Widen - less 3-bets to face
            adjustment *= 1.15
            reasons.append("Passive table - opening wider, expect less resistance")
            hands_to_add.extend(["A7s", "K8s", "Q9s", "J9s"])
        elif context.table_dynamic == TableDynamic.AGGRESSIVE:
            # Tighten - strong hands to fight back
            adjustment *= 0.85
            reasons.append("Aggressive table - tightening to 3-bet stack off")
            hands_to_remove.extend(["44", "33", "A8o", "K9o"])
        elif context.table_dynamic == TableDynamic.LOOSE:
            # Tighten but value bet more
            adjustment *= 0.9
            reasons.append("Loose table - tightening for value, multiway pots")
            hands_to_remove.extend(["76s", "65s", "A5o", "A4o"])

        # === Ante Adjustment ===
        if context.ante_present:
            adjustment *= 1.1
            reasons.append("Antes present - more dead money to win")

        # === Live vs Online ===
        if context.is_live:
            adjustment *= 1.1
            reasons.append("Live game - population typically plays looser/more passive")

        # === Players Left to Act ===
        if context.num_players <= 4:
            adjustment *= 1.15
            reasons.append("Short-handed - widening range")
        elif context.num_players >= 8:
            adjustment *= 0.9
            reasons.append("Full ring - tightening from early position")

        # Calculate adjusted percentage
        adjusted_pct = base_pct * adjustment

        # Build adjusted range
        if adjustment > 1.0:
            adjusted_range = self._widen_range(base_range, hands_to_add)
        elif adjustment < 1.0:
            adjusted_range = self._narrow_range(base_range, hands_to_remove)
        else:
            adjusted_range = base_range

        self.adjustments_made += 1

        return AdjustedRange(
            base_range=base_range,
            adjusted_range=adjusted_range,
            adjustment_factor=adjustment,
            hands_added=hands_to_add,
            hands_removed=hands_to_remove,
            reasoning=reasons
        )

    def get_adjusted_3bet_range(self,
                                context: GameContext,
                                raiser_position: str) -> AdjustedRange:
        """
        Get adjusted 3-bet range vs a specific position

        Args:
            context: Current game context
            raiser_position: Position of the opener
        """
        position = context.position.upper()
        raiser = raiser_position.upper()

        # Get base 3-bet range
        key = (position, raiser)
        if key in self.BASE_3BET_RANGES:
            base_range, base_pct = self.BASE_3BET_RANGES[key]
        else:
            base_range = "QQ+,AKs"
            base_pct = 4

        adjustment = 1.0
        reasons = []
        hands_to_add = []
        hands_to_remove = []

        # === Villain Fold to 3-bet Adjustment ===
        if context.villain_fold_to_3bet > 65:
            # 3-bet more often for folds
            adjustment *= 1.4
            reasons.append(f"Villain folds {context.villain_fold_to_3bet}% to 3-bets - 3-bet light")
            hands_to_add.extend(["A5s", "A4s", "76s", "65s", "K5s", "Q9s"])
        elif context.villain_fold_to_3bet < 45:
            # Only 3-bet for value
            adjustment *= 0.7
            reasons.append(f"Villain only folds {context.villain_fold_to_3bet}% - 3-bet for value")
            hands_to_remove.extend(["A5s", "A4s", "76s", "65s"])

        # === Villain VPIP/PFR Adjustment ===
        vpip_pfr_gap = context.villain_vpip - context.villain_pfr
        if vpip_pfr_gap > 15:
            # Player calls a lot, widen value 3-bets
            adjustment *= 1.2
            reasons.append(f"Villain is passive caller (VPIP-PFR={vpip_pfr_gap}) - widen for value")
            hands_to_add.extend(["ATs", "KJs", "QJs", "AJo"])

        # === Stack Depth ===
        if context.stack_bb < 40:
            # Tighten, plan to stack off
            adjustment *= 0.75
            reasons.append(f"Short stacked - 3-bet/fold or 3-bet/call only")
            hands_to_remove.extend(["65s", "54s", "A5s", "A4s"])
        elif context.stack_bb > 150:
            # Add more suited connectors for implied odds
            adjustment *= 1.1
            reasons.append("Deep stacked - add suited connectors for implied odds")
            hands_to_add.extend(["87s", "76s", "65s", "54s"])

        # === Position vs Deep Opener ===
        if raiser in ["UTG", "UTG1"] and context.villain_pfr < 12:
            adjustment *= 0.8
            reasons.append("Tight opener from early position - respect their range")

        # Build adjusted range
        if adjustment > 1.0:
            adjusted_range = self._widen_range(base_range, hands_to_add)
        elif adjustment < 1.0:
            adjusted_range = self._narrow_range(base_range, hands_to_remove)
        else:
            adjusted_range = base_range

        self.adjustments_made += 1

        return AdjustedRange(
            base_range=base_range,
            adjusted_range=adjusted_range,
            adjustment_factor=adjustment,
            hands_added=hands_to_add,
            hands_removed=hands_to_remove,
            reasoning=reasons
        )

    def get_calling_range_adjustment(self,
                                     context: GameContext,
                                     raiser_position: str,
                                     bet_size_bb: float) -> AdjustedRange:
        """
        Get calling range vs an open raise

        Args:
            context: Current game context
            raiser_position: Position of opener
            bet_size_bb: Raise size in BB
        """
        reasons = []
        hands_to_add = []
        hands_to_remove = []
        adjustment = 1.0

        # Base calling range (simplified)
        base_range = "22-TT,A2s-ATs,K9s+,Q9s+,J9s+,T9s,98s,87s,76s,ATo-AJo,KTo+,QJo"

        # === Raise Size ===
        if bet_size_bb <= 2.5:
            adjustment *= 1.15
            reasons.append("Small open size - calling wider")
        elif bet_size_bb >= 4:
            adjustment *= 0.8
            reasons.append("Large open size - tightening calling range")

        # === In Position vs OOP ===
        late_positions = ["BTN", "CO", "HJ"]
        if context.position.upper() in late_positions:
            adjustment *= 1.1
            reasons.append("Calling in position - can realize equity")
        else:
            adjustment *= 0.9
            reasons.append("Calling OOP - need stronger hands")
            hands_to_remove.extend(["76s", "65s", "K9s", "Q9s"])

        # === Implied Odds (Stack Depth) ===
        if context.stack_bb > 100:
            hands_to_add.extend(["22", "33", "44", "65s", "54s"])
            reasons.append("Deep stacks - set mining profitable")
        elif context.stack_bb < 50:
            hands_to_remove.extend(["22", "33", "44"])
            reasons.append("Shallow - can't set mine profitably")

        # === Villain Cbet Tendency ===
        # If villain cbets a lot, we need to fold more marginal hands
        # (This would come from opponent stats in context)

        if adjustment > 1.0:
            adjusted_range = self._widen_range(base_range, hands_to_add)
        else:
            adjusted_range = self._narrow_range(base_range, hands_to_remove)

        return AdjustedRange(
            base_range=base_range,
            adjusted_range=adjusted_range,
            adjustment_factor=adjustment,
            hands_added=hands_to_add,
            hands_removed=hands_to_remove,
            reasoning=reasons
        )

    def should_squeeze(self,
                       hand: str,
                       context: GameContext,
                       num_callers: int) -> Tuple[bool, str]:
        """
        Determine if we should squeeze

        Args:
            hand: Our hand notation (e.g., "AKs", "99")
            context: Game context
            num_callers: Number of players who called the open
        """
        squeeze_hands = {"AA", "KK", "QQ", "JJ", "TT", "AKs", "AKo", "AQs", "KQs",
                        "A5s", "A4s", "76s", "65s"}  # Polarized squeeze range

        if hand not in squeeze_hands:
            return False, f"{hand} not in squeeze range"

        reasons = []

        # More callers = more dead money = squeeze more
        if num_callers >= 2:
            reasons.append(f"{num_callers} callers = dead money to win")

        # Fold equity from original raiser
        if context.villain_fold_to_3bet > 55:
            reasons.append("Original raiser folds to 3-bets often")

        # Stack depth
        if context.stack_bb < 40:
            return False, "Too short to squeeze - push/fold instead"

        return True, " | ".join(reasons) if reasons else "Profitable squeeze spot"

    def _get_stack_depth(self, bb: float) -> StackDepth:
        """Categorize stack depth"""
        if bb < 40:
            return StackDepth.SHORT
        elif bb < 100:
            return StackDepth.MEDIUM
        elif bb < 200:
            return StackDepth.DEEP
        else:
            return StackDepth.VERY_DEEP

    def _widen_range(self, base: str, hands_to_add: List[str]) -> str:
        """Add hands to a range"""
        if not hands_to_add:
            return base
        additions = ",".join(hands_to_add)
        return f"{base},{additions}"

    def _narrow_range(self, base: str, hands_to_remove: List[str]) -> str:
        """Remove hands from range (simplified - removes exact matches)"""
        if not hands_to_remove:
            return base
        parts = base.split(",")
        filtered = [p for p in parts if p.strip() not in hands_to_remove]
        return ",".join(filtered)

    def get_stats(self) -> Dict:
        """Get engine stats"""
        return {
            "adjustments_made": self.adjustments_made,
            "positions": list(self.BASE_OPEN_RANGES.keys()),
            "3bet_combos": len(self.BASE_3BET_RANGES)
        }


# === Quick Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n🎯 Testing Dynamic Range Engine...\n", "cyan", attrs=["bold"])

    engine = DynamicRangeEngine()

    # Test opening range adjustment
    context = GameContext(
        position="CO",
        stack_bb=150,
        table_dynamic=TableDynamic.PASSIVE,
        is_live=True
    )

    cprint("📍 Opening from CO, 150bb deep, passive live table:", "yellow")
    result = engine.get_adjusted_opening_range(context)

    print(f"  Base range: {result.base_range}")
    print(f"  Adjusted:   {result.adjusted_range}")
    print(f"  Factor:     {result.adjustment_factor:.2f}x")
    print(f"  Reasoning:")
    for r in result.reasoning:
        print(f"    - {r}")

    # Test 3-bet range
    cprint("\n📍 3-betting from BTN vs CO, villain folds 70% to 3-bets:", "yellow")
    context2 = GameContext(
        position="BTN",
        stack_bb=100,
        villain_fold_to_3bet=70
    )
    result2 = engine.get_adjusted_3bet_range(context2, "CO")

    print(f"  Base:     {result2.base_range}")
    print(f"  Adjusted: {result2.adjusted_range}")
    print(f"  Reasoning:")
    for r in result2.reasoning:
        print(f"    - {r}")

    cprint(f"\n📊 Stats: {engine.get_stats()}", "cyan")
