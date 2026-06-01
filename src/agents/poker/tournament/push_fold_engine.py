"""
Push/Fold Engine - Nash equilibrium push/fold charts
The mathematics of short-stack poker
Built with love by TradeHive
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from enum import Enum
import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.poker.core.range_manager import Range


class Position(Enum):
    """Positions for push/fold"""
    SB = "sb"
    BTN = "btn"
    CO = "co"
    HJ = "hj"
    MP = "mp"
    UTG = "utg"


@dataclass
class PushDecision:
    """Push/fold decision result"""
    action: str               # "push" or "fold"
    is_profitable: bool       # Is the push +EV?
    required_fold_eq: float   # Fold equity needed
    estimated_fold_eq: float  # Expected fold equity
    hand_strength: str        # Where hand ranks
    reasoning: str


@dataclass
class CallDecision:
    """Call vs shove decision"""
    action: str               # "call" or "fold"
    pot_odds: float          # Odds we're getting
    required_equity: float    # Equity needed
    estimated_equity: float   # Our equity vs range
    reasoning: str


class PushFoldEngine:
    """
    Nash equilibrium push/fold calculator

    Provides:
    - Pushing ranges by stack size and position
    - Calling ranges vs different stack sizes
    - ICM-adjusted ranges
    - Optimal push/fold strategies
    """

    # Nash push ranges by BB count and position
    # These are approximate Nash equilibrium ranges
    PUSH_RANGES = {
        # 3 BB - Push very wide
        3: {
            Position.SB: "22+,A2s+,A2o+,K2s+,K5o+,Q4s+,Q8o+,J6s+,J8o+,T6s+,T8o+,96s+,98o,86s+,76s,65s,54s",
            Position.BTN: "22+,A2s+,A2o+,K2s+,K6o+,Q5s+,Q9o+,J7s+,J9o+,T7s+,T9o,97s+,87s,76s,65s",
            Position.CO: "22+,A2s+,A3o+,K4s+,K9o+,Q7s+,QTo+,J8s+,JTo,T8s+,98s,87s",
            Position.HJ: "22+,A2s+,A7o+,K7s+,KTo+,Q8s+,QJo,J9s+,T9s,98s",
            Position.MP: "33+,A2s+,A9o+,K9s+,KJo+,Q9s+,QJo,JTs,T9s",
            Position.UTG: "44+,A4s+,ATo+,KTs+,KQo,QTs+,JTs",
        },
        # 5 BB
        5: {
            Position.SB: "22+,A2s+,A2o+,K2s+,K7o+,Q6s+,Q9o+,J7s+,J9o+,T7s+,T9o,97s+,87s,76s,65s",
            Position.BTN: "22+,A2s+,A3o+,K3s+,K8o+,Q6s+,QTo+,J7s+,JTo,T7s+,97s+,87s,76s",
            Position.CO: "22+,A2s+,A7o+,K6s+,KTo+,Q8s+,QJo,J8s+,T8s+,98s",
            Position.HJ: "33+,A2s+,A9o+,K8s+,KJo+,Q9s+,J9s+,T9s",
            Position.MP: "44+,A3s+,ATo+,KTs+,KQo,QTs+,JTs",
            Position.UTG: "55+,A5s+,AJo+,KJs+,QJs",
        },
        # 8 BB
        8: {
            Position.SB: "22+,A2s+,A5o+,K4s+,K9o+,Q7s+,QTo+,J8s+,JTo,T8s+,98s,87s",
            Position.BTN: "22+,A2s+,A7o+,K6s+,KTo+,Q8s+,QJo,J8s+,T8s+,98s,87s",
            Position.CO: "33+,A2s+,A9o+,K8s+,KJo+,Q9s+,J9s+,T9s",
            Position.HJ: "44+,A4s+,ATo+,K9s+,KQo,QTs+,JTs",
            Position.MP: "55+,A5s+,AJo+,KTs+,QJs",
            Position.UTG: "66+,A7s+,AQo+,KQs",
        },
        # 10 BB
        10: {
            Position.SB: "22+,A2s+,A7o+,K5s+,KTo+,Q8s+,QJo,J8s+,T8s+,98s",
            Position.BTN: "22+,A2s+,A9o+,K7s+,KJo+,Q9s+,QJo,J9s+,T9s,98s",
            Position.CO: "44+,A3s+,ATo+,K9s+,KQo,QTs+,JTs",
            Position.HJ: "55+,A5s+,AJo+,KTs+,QJs",
            Position.MP: "66+,A7s+,AQo+,KQs",
            Position.UTG: "77+,A9s+,AKo",
        },
        # 12 BB
        12: {
            Position.SB: "33+,A2s+,A8o+,K6s+,KJo+,Q8s+,QJo,J9s+,T9s",
            Position.BTN: "44+,A2s+,ATo+,K8s+,KQo,Q9s+,J9s+,T9s",
            Position.CO: "55+,A4s+,AJo+,KTs+,QTs+,JTs",
            Position.HJ: "66+,A6s+,AQo+,KQs,QJs",
            Position.MP: "77+,A8s+,AKo",
            Position.UTG: "88+,ATs+,AKo",
        },
        # 15 BB
        15: {
            Position.SB: "55+,A3s+,ATo+,K8s+,KQo,Q9s+,JTs",
            Position.BTN: "55+,A4s+,AJo+,K9s+,QTs+,JTs",
            Position.CO: "66+,A6s+,AQo+,KTs+,QJs",
            Position.HJ: "77+,A8s+,AKo",
            Position.MP: "88+,ATs+,AKo",
            Position.UTG: "99+,AQs+,AKo",
        },
        # 20 BB
        20: {
            Position.SB: "66+,A5s+,AJo+,K9s+,QTs+",
            Position.BTN: "66+,A6s+,AQo+,KTs+,QJs",
            Position.CO: "77+,A8s+,AKo,KQs",
            Position.HJ: "88+,ATs+,AKo",
            Position.MP: "99+,AQs+",
            Position.UTG: "TT+,AKs",
        },
    }

    # Nash calling ranges vs shove by effective BB
    CALL_RANGES = {
        3: "22+,A2s+,A2o+,K3s+,K8o+,Q6s+,QTo+,J8s+,JTo,T8s+",  # Call wide vs desperate
        5: "33+,A2s+,A5o+,K5s+,KTo+,Q8s+,QJo,J9s+,T9s",
        8: "55+,A4s+,ATo+,K8s+,KQo,Q9s+,JTs",
        10: "66+,A6s+,AJo+,K9s+,QTs+",
        12: "77+,A8s+,AQo+,KTs+,QJs",
        15: "88+,ATs+,AKo,KQs",
        20: "99+,AQs+,AKo",
    }

    def __init__(self):
        self._build_range_cache()

    def _build_range_cache(self):
        """Pre-build range objects for quick lookup"""
        self._push_range_cache = {}
        self._call_range_cache = {}

        for bb, positions in self.PUSH_RANGES.items():
            self._push_range_cache[bb] = {}
            for pos, notation in positions.items():
                self._push_range_cache[bb][pos] = Range.from_notation(notation)

        for bb, notation in self.CALL_RANGES.items():
            self._call_range_cache[bb] = Range.from_notation(notation)

    def _get_closest_bb(self, bb_count: float, available: List[int]) -> int:
        """Get closest BB count from available options"""
        return min(available, key=lambda x: abs(x - bb_count))

    def get_push_range(self, bb_count: float, position: Position) -> Range:
        """
        Get Nash push range for stack and position

        Args:
            bb_count: Stack in big blinds
            position: Our position

        Returns:
            Range object
        """
        closest_bb = self._get_closest_bb(bb_count, list(self.PUSH_RANGES.keys()))
        return self._push_range_cache.get(closest_bb, {}).get(
            position, Range.from_notation("AA,KK")
        )

    def get_call_range(self, villain_bb: float) -> Range:
        """
        Get Nash calling range vs villain's stack

        Args:
            villain_bb: Villain's stack in BB

        Returns:
            Range object
        """
        closest_bb = self._get_closest_bb(villain_bb, list(self.CALL_RANGES.keys()))
        return self._call_range_cache.get(closest_bb, Range.from_notation("AA,KK"))

    def should_push(self, hand: str, bb_count: float, position: Position) -> PushDecision:
        """
        Determine if we should push with a hand

        Args:
            hand: Hand notation (e.g., "AKs", "77")
            bb_count: Our stack in BB
            position: Our position

        Returns:
            PushDecision
        """
        push_range = self.get_push_range(bb_count, position)
        is_in_range = hand in push_range

        # Estimate fold equity based on position and stack
        fold_eq_estimates = {
            Position.SB: 0.35,
            Position.BTN: 0.45,
            Position.CO: 0.50,
            Position.HJ: 0.55,
            Position.MP: 0.60,
            Position.UTG: 0.65,
        }
        base_fold_eq = fold_eq_estimates.get(position, 0.50)

        # Adjust for stack size
        if bb_count < 5:
            fold_eq = base_fold_eq * 0.8  # Less fold equity when short
        elif bb_count > 15:
            fold_eq = base_fold_eq * 1.1  # More fold equity with deeper stack
        else:
            fold_eq = base_fold_eq

        # Required fold equity calculation
        # Push needs to work ~(stack / (stack + blinds))% of time to break even
        pot = 1.5  # SB + BB
        required_fold_eq = bb_count / (bb_count + pot) * 0.5  # Simplified

        if is_in_range:
            return PushDecision(
                action="push",
                is_profitable=True,
                required_fold_eq=required_fold_eq,
                estimated_fold_eq=fold_eq,
                hand_strength="in pushing range",
                reasoning=f"Push {hand} from {position.value.upper()} with {bb_count:.0f}bb - Nash equilibrium"
            )
        else:
            return PushDecision(
                action="fold",
                is_profitable=False,
                required_fold_eq=required_fold_eq,
                estimated_fold_eq=fold_eq,
                hand_strength="outside pushing range",
                reasoning=f"Fold {hand} from {position.value.upper()} with {bb_count:.0f}bb - too weak"
            )

    def should_call_shove(self, hand: str, our_bb: float, villain_bb: float,
                          pot_bb: float = 1.5) -> CallDecision:
        """
        Determine if we should call a shove

        Args:
            hand: Our hand notation
            our_bb: Our stack in BB
            villain_bb: Villain's stack in BB
            pot_bb: Current pot in BB (default = SB + BB)

        Returns:
            CallDecision
        """
        call_range = self.get_call_range(villain_bb)
        is_in_range = hand in call_range

        # Calculate pot odds
        call_amount = min(our_bb, villain_bb)
        total_pot = pot_bb + call_amount + villain_bb
        pot_odds = call_amount / total_pot

        # Estimate equity vs villain's range
        # Simplified: if in call range, assume we have enough equity
        if is_in_range:
            estimated_eq = pot_odds + 0.10  # Slight edge if in range
        else:
            estimated_eq = pot_odds - 0.10  # Below threshold

        if is_in_range:
            return CallDecision(
                action="call",
                pot_odds=pot_odds,
                required_equity=pot_odds,
                estimated_equity=estimated_eq,
                reasoning=f"Call with {hand} vs {villain_bb:.0f}bb shove - in Nash calling range"
            )
        else:
            return CallDecision(
                action="fold",
                pot_odds=pot_odds,
                required_equity=pot_odds,
                estimated_equity=estimated_eq,
                reasoning=f"Fold {hand} vs {villain_bb:.0f}bb shove - outside calling range"
            )

    def icm_adjusted_range(self, base_range: Range, bubble_factor: float) -> Range:
        """
        Adjust range for ICM considerations

        Args:
            base_range: Nash equilibrium range
            bubble_factor: ICM bubble factor (>1 = tighter)

        Returns:
            Adjusted Range
        """
        # For high bubble factors, reduce range
        if bubble_factor > 1.5:
            # Get tighter hands only
            return Range.from_notation("AA-TT,AKs-AQs,AKo")
        elif bubble_factor > 1.2:
            return Range.from_notation("AA-88,AKs-AJs,AKo-AQo,KQs")
        else:
            return base_range

    def visualize_push_chart(self, bb_count: float) -> str:
        """
        Generate ASCII push chart for a stack size

        Args:
            bb_count: Stack in BB

        Returns:
            ASCII chart string
        """
        lines = [f"\nNash Push Chart - {bb_count:.0f}bb\n"]
        lines.append("Position | Push Range")
        lines.append("-" * 50)

        closest_bb = self._get_closest_bb(bb_count, list(self.PUSH_RANGES.keys()))

        for pos in [Position.UTG, Position.MP, Position.HJ, Position.CO, Position.BTN, Position.SB]:
            if pos in self.PUSH_RANGES.get(closest_bb, {}):
                range_str = self.PUSH_RANGES[closest_bb][pos]
                # Truncate if too long
                if len(range_str) > 35:
                    range_str = range_str[:32] + "..."
                lines.append(f"{pos.value.upper():8} | {range_str}")

        return "\n".join(lines)


# === Standalone Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n=== Push/Fold Engine Test ===\n", "cyan", attrs=['bold'])

    engine = PushFoldEngine()

    # Test push decisions
    cprint("Push Decisions (10bb):", "yellow")
    test_hands = ["AA", "AKs", "77", "A5s", "KQo", "98s", "72o"]

    for hand in test_hands:
        decision = engine.should_push(hand, 10, Position.BTN)
        color = "green" if decision.action == "push" else "red"
        cprint(f"  {hand} from BTN: {decision.action.upper()}", color)

    print()
    cprint("Position Comparison (10bb with ATs):", "yellow")
    for pos in [Position.UTG, Position.MP, Position.CO, Position.BTN, Position.SB]:
        decision = engine.should_push("ATs", 10, pos)
        color = "green" if decision.action == "push" else "red"
        cprint(f"  {pos.value.upper()}: {decision.action}", color)

    print()
    cprint("Call Decisions (facing 8bb shove):", "yellow")
    for hand in ["AA", "JJ", "AQs", "ATo", "99", "KQo", "55"]:
        decision = engine.should_call_shove(hand, 20, 8)
        color = "green" if decision.action == "call" else "red"
        cprint(f"  {hand}: {decision.action} (need {decision.pot_odds*100:.0f}%)", color)

    print()
    cprint(engine.visualize_push_chart(10), "white")
