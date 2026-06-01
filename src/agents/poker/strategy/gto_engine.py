"""
GTO Engine - Game Theory Optimal balanced strategies
The mathematical foundation of unexploitable play
Built with love by TradeHive
"""

from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
from enum import Enum
import random
import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.poker.core.odds_calculator import OddsCalculator
from src.agents.poker.core.range_manager import Range


class StrategyType(Enum):
    """Types of GTO strategies"""
    PURE = "pure"        # Always take same action
    MIXED = "mixed"      # Randomize between actions


@dataclass
class MixedStrategy:
    """A mixed strategy with multiple actions and frequencies"""
    actions: Dict[str, float]  # action -> frequency
    ev: float
    description: str

    def sample(self) -> str:
        """Randomly select action based on frequencies"""
        r = random.random()
        cumulative = 0.0
        for action, freq in self.actions.items():
            cumulative += freq
            if r <= cumulative:
                return action
        return list(self.actions.keys())[-1]


@dataclass
class GTOMetrics:
    """GTO-related metrics for a spot"""
    mdf: float                    # Minimum Defense Frequency
    bluff_to_value_ratio: float   # Optimal bluff ratio
    required_bluff_freq: float    # How often we need to bluff
    alpha: float                  # Break-even bluff frequency for villain
    pot_odds: float               # Our pot odds when calling


class GTOEngine:
    """
    Game Theory Optimal strategy calculator

    Implements:
    - Minimum Defense Frequency (MDF)
    - Optimal bluffing frequencies
    - Value-to-bluff ratios
    - Balanced betting ranges
    - Mixed strategy generation
    """

    def __init__(self):
        self.odds_calc = OddsCalculator()

    def calculate_mdf(self, bet_size: float, pot_size: float) -> float:
        """
        Calculate Minimum Defense Frequency

        MDF = Pot / (Pot + Bet)

        This is how often we must defend to prevent villain
        from profitably bluffing with any two cards.

        Args:
            bet_size: Villain's bet
            pot_size: Pot before bet

        Returns:
            MDF as decimal
        """
        return self.odds_calc.mdf(bet_size, pot_size)

    def calculate_alpha(self, bet_size: float, pot_size: float) -> float:
        """
        Calculate break-even bluff frequency (alpha)

        Alpha = Bet / (Pot + Bet)

        This is how often our bluffs need to succeed to break even.

        Args:
            bet_size: Our bet size
            pot_size: Current pot

        Returns:
            Required fold frequency
        """
        return self.odds_calc.bluff_breakeven(bet_size, pot_size)

    def optimal_bluff_ratio(self, bet_size: float, pot_size: float) -> float:
        """
        Calculate optimal bluff-to-value ratio

        For a bet B into pot P:
        Villain gets (P+B):B = (P+B)/B : 1 odds

        To make villain indifferent, we bluff at:
        Bluff% = B / (P + 2*B)

        Value-to-bluff ratio = (P+B)/B

        Args:
            bet_size: Our bet size
            pot_size: Current pot

        Returns:
            Number of value combos per bluff combo
        """
        return self.odds_calc.value_to_bluff_ratio(bet_size, pot_size)

    def get_betting_range_split(self, bet_size: float, pot_size: float,
                                 total_value_combos: int) -> Dict[str, int]:
        """
        Calculate how to split range between value and bluffs

        Args:
            bet_size: Planned bet size
            pot_size: Current pot
            total_value_combos: Number of value hand combos

        Returns:
            Dict with 'value', 'bluff', 'check' combo counts
        """
        ratio = self.optimal_bluff_ratio(bet_size, pot_size)

        # For every 'ratio' value combos, we want 1 bluff
        optimal_bluffs = int(total_value_combos / ratio)

        return {
            'value': total_value_combos,
            'bluff': optimal_bluffs,
            'total_betting': total_value_combos + optimal_bluffs,
            'ratio': f"{ratio:.1f}:1"
        }

    def defense_range_construction(self, facing_bet: float, pot_size: float,
                                    our_range: Range, villain_range: Range = None) -> Dict:
        """
        Construct a GTO-balanced defense range

        Args:
            facing_bet: Bet we're facing
            pot_size: Pot before bet
            our_range: Our current range
            villain_range: Villain's estimated range

        Returns:
            Dict with 'raise', 'call', 'fold' ranges and frequencies
        """
        mdf = self.calculate_mdf(facing_bet, pot_size)
        total_combos = our_range.combo_count()

        # Need to defend MDF of our range
        defend_combos = int(total_combos * mdf)

        # Typical raise:call ratio is about 1:3 to 1:4
        raise_combos = int(defend_combos * 0.25)
        call_combos = defend_combos - raise_combos
        fold_combos = total_combos - defend_combos

        return {
            'mdf': mdf,
            'total_combos': total_combos,
            'defend_combos': defend_combos,
            'raise_combos': raise_combos,
            'call_combos': call_combos,
            'fold_combos': fold_combos,
            'raise_freq': raise_combos / total_combos if total_combos > 0 else 0,
            'call_freq': call_combos / total_combos if total_combos > 0 else 0,
            'fold_freq': fold_combos / total_combos if total_combos > 0 else 0,
        }

    def generate_mixed_strategy(self, ev_by_action: Dict[str, float],
                                 indifference_threshold: float = 0.5) -> MixedStrategy:
        """
        Generate a mixed strategy when actions are close in EV

        When two actions have similar EV, we mix to make ourselves
        unexploitable.

        Args:
            ev_by_action: Dict mapping action to EV
            indifference_threshold: How close EVs need to be to mix

        Returns:
            MixedStrategy with action frequencies
        """
        if not ev_by_action:
            return MixedStrategy({'check': 1.0}, 0, "No actions available")

        # Find best action
        best_action = max(ev_by_action.items(), key=lambda x: x[1])
        best_ev = best_action[1]

        # Find actions within threshold
        close_actions = {
            action: ev for action, ev in ev_by_action.items()
            if best_ev - ev <= indifference_threshold
        }

        if len(close_actions) == 1:
            # Pure strategy
            return MixedStrategy(
                {best_action[0]: 1.0},
                best_ev,
                f"Pure {best_action[0]} (EV: ${best_ev:.2f})"
            )

        # Mixed strategy - weight by EV difference from worst close action
        min_ev = min(close_actions.values())
        weights = {action: ev - min_ev + 0.1 for action, ev in close_actions.items()}
        total_weight = sum(weights.values())

        frequencies = {action: w / total_weight for action, w in weights.items()}

        # Calculate weighted EV
        weighted_ev = sum(ev_by_action[a] * f for a, f in frequencies.items())

        desc_parts = [f"{a}: {f*100:.0f}%" for a, f in frequencies.items()]
        description = f"Mixed ({', '.join(desc_parts)})"

        return MixedStrategy(frequencies, weighted_ev, description)

    def polarized_vs_linear_range(self, pot_size: float, effective_stack: float,
                                   street: str = "river") -> str:
        """
        Recommend whether to use polarized or linear betting range

        Polarized: Bet nuts and bluffs, check medium hands
        Linear: Bet best hands, check weaker hands

        Args:
            pot_size: Current pot
            effective_stack: Remaining stack
            street: Which street we're on

        Returns:
            Recommendation string
        """
        spr = self.odds_calc.spr(effective_stack, pot_size)

        if street == "river":
            # River is always polarized (no more cards to come)
            return "polarized"

        if spr < 1:
            # SPR < 1: committed, go linear
            return "linear"
        elif spr < 4:
            # Low SPR: more linear
            return "linear"
        elif spr < 10:
            # Medium SPR: can polarize
            return "polarized"
        else:
            # Deep: depends on board
            return "mixed"

    def optimal_bet_size(self, pot_size: float, effective_stack: float,
                         polarized: bool = True) -> List[Tuple[float, str]]:
        """
        Recommend optimal bet sizes for the situation

        Args:
            pot_size: Current pot
            effective_stack: Remaining stack
            polarized: Whether using polarized range

        Returns:
            List of (sizing, reason) tuples
        """
        spr = self.odds_calc.spr(effective_stack, pot_size)
        recommendations = []

        if polarized:
            # Polarized ranges prefer larger sizes
            if spr > 2:
                recommendations.append((0.75, "Large bet for polarized range"))
            if spr > 1:
                recommendations.append((1.0, "Pot-size bet for max fold equity"))
            if spr > 3:
                recommendations.append((1.5, "Overbet with strong polarization"))
        else:
            # Linear ranges prefer smaller sizes
            recommendations.append((0.33, "Small bet for thin value"))
            recommendations.append((0.50, "Medium bet for protection"))
            if spr > 2:
                recommendations.append((0.66, "Larger bet with depth"))

        # Always consider all-in if SPR is low
        if spr < 2:
            recommendations.append((spr, "All-in with low SPR"))

        return recommendations

    def indifference_price(self, win_probability: float, pot_size: float) -> float:
        """
        Calculate the bet size that makes opponent indifferent

        The price that makes villain's EV = 0 for calling with a bluff catcher

        Args:
            win_probability: How often we have value (vs bluffs)
            pot_size: Current pot

        Returns:
            Optimal bet size
        """
        # EV(call) = (1-p) * (pot + bet) - bet = 0
        # (1-p) * pot + (1-p) * bet - bet = 0
        # (1-p) * pot = bet - (1-p) * bet = bet * p
        # bet = (1-p) * pot / p

        if win_probability <= 0 or win_probability >= 1:
            return pot_size * 0.66  # Default sizing

        return ((1 - win_probability) * pot_size) / win_probability

    def get_gto_metrics(self, bet_size: float, pot_size: float) -> GTOMetrics:
        """
        Calculate all GTO metrics for a betting spot

        Args:
            bet_size: Bet/raise size
            pot_size: Current pot

        Returns:
            GTOMetrics with all calculations
        """
        mdf = self.calculate_mdf(bet_size, pot_size)
        alpha = self.calculate_alpha(bet_size, pot_size)
        ratio = self.optimal_bluff_ratio(bet_size, pot_size)
        bluff_freq = bet_size / (pot_size + 2 * bet_size)
        pot_odds = bet_size / (pot_size + bet_size)

        return GTOMetrics(
            mdf=mdf,
            bluff_to_value_ratio=1 / ratio,  # Inverse for bluff-to-value
            required_bluff_freq=bluff_freq,
            alpha=alpha,
            pot_odds=pot_odds
        )


# === Standalone Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n=== GTO Engine Test ===\n", "cyan", attrs=['bold'])

    engine = GTOEngine()
    pot = 100

    cprint("MDF by Bet Size:", "yellow")
    for bet in [33, 50, 75, 100, 150]:
        mdf = engine.calculate_mdf(bet, pot)
        cprint(f"  Bet ${bet} into ${pot}: MDF = {mdf*100:.0f}%", "white")

    print()
    cprint("Bluff Break-Even (Alpha):", "yellow")
    for bet in [33, 50, 75, 100]:
        alpha = engine.calculate_alpha(bet, pot)
        cprint(f"  ${bet} into ${pot}: need {alpha*100:.0f}% folds", "white")

    print()
    cprint("Value:Bluff Ratio:", "yellow")
    for bet in [33, 50, 75, 100]:
        ratio = engine.optimal_bluff_ratio(bet, pot)
        cprint(f"  ${bet} into ${pot}: {ratio:.1f} value combos per bluff", "white")

    print()
    cprint("Range Split (20 value combos, pot bet):", "yellow")
    split = engine.get_betting_range_split(100, 100, 20)
    cprint(f"  Value: {split['value']} combos", "green")
    cprint(f"  Bluffs: {split['bluff']} combos", "red")
    cprint(f"  Total betting: {split['total_betting']} ({split['ratio']})", "white")

    print()
    cprint("GTO Metrics Summary (75% pot bet):", "yellow")
    metrics = engine.get_gto_metrics(75, 100)
    cprint(f"  MDF: {metrics.mdf*100:.0f}%", "white")
    cprint(f"  Alpha: {metrics.alpha*100:.0f}%", "white")
    cprint(f"  Bluff frequency: {metrics.required_bluff_freq*100:.0f}%", "white")
    cprint(f"  Pot odds: {metrics.pot_odds*100:.0f}%", "white")

    print()
    cprint("Mixed Strategy Generation:", "yellow")
    ev_actions = {'bet': 5.2, 'check': 4.8, 'fold': -2}
    strategy = engine.generate_mixed_strategy(ev_actions)
    cprint(f"  {strategy.description}", "green")
    for action, freq in strategy.actions.items():
        cprint(f"    {action}: {freq*100:.0f}%", "white")

    print()
    cprint("Polarized vs Linear:", "yellow")
    for spr_val in [0.5, 2, 5, 15]:
        stack = spr_val * pot
        rec = engine.polarized_vs_linear_range(pot, stack)
        cprint(f"  SPR {spr_val}: {rec.upper()} range", "white")
