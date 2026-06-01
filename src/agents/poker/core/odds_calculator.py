"""
Odds Calculator - Pot odds, EV, SPR, MDF, and betting calculations
The mathematical backbone of poker decisions
Built with love by TradeHive
"""

from dataclasses import dataclass
from typing import Tuple, List, Optional
from enum import Enum


class BetSize(Enum):
    """Common bet sizing categories"""
    SMALL = "small"       # 25-33% pot
    MEDIUM = "medium"     # 50-66% pot
    LARGE = "large"       # 75-100% pot
    OVERBET = "overbet"   # 100%+ pot
    ALL_IN = "all_in"


@dataclass
class OddsResult:
    """Result of odds calculation"""
    pot_odds: float            # As decimal (0.25 = 25%)
    pot_odds_ratio: str        # As ratio string ("3:1")
    break_even_equity: float   # Equity needed to call profitably
    description: str


@dataclass
class EVResult:
    """Expected Value calculation result"""
    ev: float              # Expected value in $
    action: str            # Recommended action
    ev_per_action: dict    # EV for each action
    description: str


class OddsCalculator:
    """
    Comprehensive odds and betting calculator

    Handles:
    - Pot odds and implied odds
    - Expected Value (EV) calculations
    - Stack-to-Pot Ratio (SPR)
    - Minimum Defense Frequency (MDF)
    - Optimal bet sizing
    - Break-even calculations
    """

    def pot_odds(self, call_amount: float, pot_size: float) -> OddsResult:
        """
        Calculate pot odds

        Pot Odds = Call / (Pot + Call)

        Args:
            call_amount: Amount to call
            pot_size: Current pot size (before call)

        Returns:
            OddsResult with pot odds as decimal and ratio
        """
        if call_amount <= 0:
            return OddsResult(0, "0:1", 0, "No call required")

        total_pot = pot_size + call_amount
        odds_decimal = call_amount / total_pot

        # Convert to ratio (pot : call)
        ratio = pot_size / call_amount if call_amount > 0 else float('inf')
        ratio_str = f"{ratio:.1f}:1"

        # Break-even equity
        break_even = odds_decimal

        return OddsResult(
            pot_odds=odds_decimal,
            pot_odds_ratio=ratio_str,
            break_even_equity=break_even,
            description=f"Need {break_even*100:.1f}% equity to call (getting {ratio_str})"
        )

    def implied_odds(self, call_amount: float, pot_size: float,
                     expected_future: float) -> OddsResult:
        """
        Calculate implied odds (accounting for future winnings)

        Implied Odds = Call / (Pot + Call + Expected_Future)

        Args:
            call_amount: Amount to call now
            pot_size: Current pot
            expected_future: Expected additional winnings when hit

        Returns:
            OddsResult with implied pot odds
        """
        if call_amount <= 0:
            return OddsResult(0, "0:1", 0, "No call required")

        effective_pot = pot_size + call_amount + expected_future
        odds_decimal = call_amount / effective_pot

        ratio = (pot_size + expected_future) / call_amount
        ratio_str = f"{ratio:.1f}:1"

        return OddsResult(
            pot_odds=odds_decimal,
            pot_odds_ratio=ratio_str,
            break_even_equity=odds_decimal,
            description=f"With implied odds: need {odds_decimal*100:.1f}% equity (getting {ratio_str})"
        )

    def spr(self, effective_stack: float, pot_size: float) -> float:
        """
        Calculate Stack-to-Pot Ratio

        SPR = Effective Stack / Pot

        Interpretation:
        - SPR < 3: Very shallow, often all-in or fold
        - SPR 3-6: Medium, one street of aggression
        - SPR 6-13: Deep, two streets of value
        - SPR > 13: Very deep, three streets of value

        Args:
            effective_stack: Smaller of the two stacks in a heads-up pot
            pot_size: Current pot

        Returns:
            SPR as float
        """
        if pot_size <= 0:
            return float('inf')
        return effective_stack / pot_size

    def spr_category(self, spr_value: float) -> str:
        """Categorize SPR"""
        if spr_value < 3:
            return "very_shallow"
        elif spr_value < 6:
            return "shallow"
        elif spr_value < 13:
            return "medium"
        else:
            return "deep"

    def mdf(self, bet_size: float, pot_size: float) -> float:
        """
        Calculate Minimum Defense Frequency

        MDF = Pot / (Pot + Bet)

        This is the minimum frequency we must defend (call or raise)
        to prevent villain from profiting with any two cards.

        Args:
            bet_size: Villain's bet size
            pot_size: Pot before villain's bet

        Returns:
            MDF as decimal (0.57 = 57%)
        """
        if bet_size <= 0:
            return 1.0
        return pot_size / (pot_size + bet_size)

    def bluff_breakeven(self, bet_size: float, pot_size: float) -> float:
        """
        Calculate break-even bluff frequency

        When we bet, villain must fold this often for bluff to break even:
        Fold % needed = Bet / (Pot + Bet)

        Args:
            bet_size: Our bet size
            pot_size: Current pot

        Returns:
            Required fold frequency as decimal
        """
        if bet_size <= 0:
            return 0.0
        return bet_size / (pot_size + bet_size)

    def ev_call(self, call_amount: float, pot_size: float, equity: float) -> float:
        """
        Calculate EV of calling

        EV(call) = Equity * (Pot + Call) - (1-Equity) * Call
                 = Equity * Pot + Equity * Call - Call + Equity * Call
                 = Equity * Pot - Call * (1 - 2*Equity)

        Simplified:
        EV(call) = Equity * (Pot + Call) - Call

        Args:
            call_amount: Amount to call
            pot_size: Current pot
            equity: Our equity as decimal

        Returns:
            EV in same units as call_amount
        """
        total_pot = pot_size + call_amount
        win_amount = total_pot * equity
        cost = call_amount
        return win_amount - cost

    def ev_fold(self) -> float:
        """EV of folding is always 0"""
        return 0.0

    def ev_bet(self, bet_size: float, pot_size: float, equity: float,
               fold_frequency: float) -> float:
        """
        Calculate EV of betting

        EV(bet) = Fold% * Pot + (1-Fold%) * [Equity * (Pot + 2*Bet) - Bet]

        When villain folds: We win the pot
        When villain calls: We win/lose based on equity

        Args:
            bet_size: Our bet size
            pot_size: Current pot
            equity: Our equity when called
            fold_frequency: How often villain folds

        Returns:
            EV of betting
        """
        # When villain folds
        ev_fold = fold_frequency * pot_size

        # When villain calls
        total_pot = pot_size + 2 * bet_size
        ev_call = (1 - fold_frequency) * (equity * total_pot - bet_size)

        return ev_fold + ev_call

    def ev_raise(self, raise_amount: float, call_amount: float, pot_size: float,
                 equity: float, fold_frequency: float) -> float:
        """
        Calculate EV of raising

        Args:
            raise_amount: Our total raise (not just the additional amount)
            call_amount: Amount we need to put in to raise
            pot_size: Current pot
            equity: Our equity when called
            fold_frequency: How often villain folds to our raise

        Returns:
            EV of raising
        """
        # When villain folds
        ev_fold = fold_frequency * pot_size

        # When villain calls
        total_pot = pot_size + raise_amount + call_amount
        ev_call = (1 - fold_frequency) * (equity * total_pot - call_amount)

        return ev_fold + ev_call

    def compare_actions(self, pot_size: float, bet_facing: float,
                        equity: float, fold_freq_if_bet: float = 0.5,
                        bet_size: float = None) -> EVResult:
        """
        Compare EV of different actions and recommend best

        Args:
            pot_size: Current pot
            bet_facing: Bet we're facing (0 if we can check)
            equity: Our equity
            fold_freq_if_bet: Expected fold frequency if we bet/raise
            bet_size: Our bet size (default 66% pot if we bet)

        Returns:
            EVResult with best action and EV breakdown
        """
        ev_dict = {}

        # Calculate EV of fold (always 0)
        ev_dict['fold'] = 0.0

        if bet_facing > 0:
            # Facing a bet - can fold, call, or raise
            ev_dict['call'] = self.ev_call(bet_facing, pot_size, equity)

            # Raise to 2.5x-3x
            raise_size = bet_facing * 2.5
            ev_dict['raise'] = self.ev_raise(
                raise_size, raise_size, pot_size,
                equity, fold_freq_if_bet
            )
        else:
            # Not facing bet - can check or bet
            ev_dict['check'] = 0.0  # EV of check depends on future actions

            if bet_size is None:
                bet_size = pot_size * 0.66

            ev_dict['bet'] = self.ev_bet(
                bet_size, pot_size, equity, fold_freq_if_bet
            )

        # Find best action
        best_action = max(ev_dict.items(), key=lambda x: x[1])

        description = f"Best: {best_action[0].upper()} (EV: ${best_action[1]:+.2f})"

        return EVResult(
            ev=best_action[1],
            action=best_action[0],
            ev_per_action=ev_dict,
            description=description
        )

    def geometric_sizing(self, pot: float, stack: float, streets_remaining: int) -> float:
        """
        Calculate optimal bet size to get all-in over remaining streets

        Formula: bet = pot * ((stack/pot + 1)^(1/n) - 1)

        This creates a geometric betting pattern where each bet is the same
        fraction of the new pot size.

        Args:
            pot: Current pot size
            stack: Effective stack remaining
            streets_remaining: Number of betting rounds left (1-3)

        Returns:
            Optimal bet size
        """
        if stack <= 0 or streets_remaining <= 0:
            return 0

        if pot <= 0:
            return stack  # Just jam

        spr = stack / pot
        if spr <= 0:
            return 0

        # Calculate growth factor
        growth = (spr + 1) ** (1 / streets_remaining)
        bet_as_fraction = growth - 1

        return pot * bet_as_fraction

    def optimal_bet_sizes(self, pot: float, spr: float) -> List[Tuple[str, float, float]]:
        """
        Get recommended bet sizes based on SPR

        Returns:
            List of (name, size, pot_fraction) tuples
        """
        sizes = []

        if spr < 3:
            # Shallow - use larger sizes to get stacks in
            sizes.append(("small", pot * 0.5, 0.5))
            sizes.append(("medium", pot * 0.75, 0.75))
            sizes.append(("jam", spr * pot, spr))

        elif spr < 8:
            # Medium SPR
            sizes.append(("small", pot * 0.33, 0.33))
            sizes.append(("medium", pot * 0.66, 0.66))
            sizes.append(("large", pot * 1.0, 1.0))

        else:
            # Deep - more sizing options
            sizes.append(("small", pot * 0.25, 0.25))
            sizes.append(("medium", pot * 0.50, 0.50))
            sizes.append(("large", pot * 0.75, 0.75))
            sizes.append(("pot", pot * 1.0, 1.0))
            sizes.append(("overbet", pot * 1.5, 1.5))

        return sizes

    def value_to_bluff_ratio(self, bet_size: float, pot_size: float) -> float:
        """
        Calculate optimal value:bluff ratio for a bet size

        For a bet B into pot P, villain gets (P+B):(B) odds = (P+B)/B : 1
        We need to bluff at frequency: B/(P+2B) to make villain indifferent

        Value hands per bluff = (P+B)/B = pot odds villain is getting

        Args:
            bet_size: Our bet
            pot_size: Current pot

        Returns:
            Number of value hands per bluff
        """
        if bet_size <= 0:
            return float('inf')
        return (pot_size + bet_size) / bet_size

    def required_equity_vs_range(self, pot_odds: float, villain_range_equity: float = 0.5) -> float:
        """
        Equity needed accounting for villain's range strength

        If villain only continues with strong hands, we need more equity.

        Args:
            pot_odds: Our pot odds
            villain_range_equity: Villain's average equity when continuing

        Returns:
            Required equity to call profitably
        """
        # Against a balanced range (50%), pot odds = required equity
        # Against polarized range, adjust accordingly
        return pot_odds / (1 - villain_range_equity + pot_odds)

    def outs_to_equity(self, outs: int, cards_to_come: int = 1) -> float:
        """
        Convert number of outs to equity percentage

        Uses precise calculation, not rule of 2/4

        Args:
            outs: Number of outs
            cards_to_come: 1 for turn OR river, 2 for both

        Returns:
            Equity as decimal
        """
        remaining = 52 - 2 - (5 - cards_to_come)  # Approximate remaining cards

        if cards_to_come == 1:
            return outs / remaining
        else:
            # Two cards to come
            # P(hit) = 1 - P(miss both)
            p_miss_first = (remaining - outs) / remaining
            p_miss_second = (remaining - 1 - outs) / (remaining - 1)
            p_miss_both = p_miss_first * p_miss_second
            return 1 - p_miss_both


# === Standalone Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n=== Odds Calculator Test ===\n", "cyan", attrs=['bold'])

    calc = OddsCalculator()

    # Test pot odds
    cprint("Pot Odds:", "yellow")
    pot = 100
    bet = 50
    result = calc.pot_odds(bet, pot)
    cprint(f"  Pot: ${pot}, Facing: ${bet}", "white")
    cprint(f"  Pot Odds: {result.pot_odds*100:.1f}% ({result.pot_odds_ratio})", "green")
    cprint(f"  {result.description}", "cyan")

    print()

    # Test implied odds
    cprint("Implied Odds (expecting $100 more when hit):", "yellow")
    result = calc.implied_odds(bet, pot, 100)
    cprint(f"  {result.description}", "green")

    print()

    # Test SPR
    cprint("Stack-to-Pot Ratio:", "yellow")
    examples = [(500, 100), (200, 100), (100, 100), (50, 100)]
    for stack, pot in examples:
        spr = calc.spr(stack, pot)
        cat = calc.spr_category(spr)
        cprint(f"  Stack ${stack} / Pot ${pot} = SPR {spr:.1f} ({cat})", "white")

    print()

    # Test MDF
    cprint("Minimum Defense Frequency:", "yellow")
    pot = 100
    for bet in [33, 50, 75, 100, 150]:
        mdf = calc.mdf(bet, pot)
        cprint(f"  Bet ${bet} into ${pot} -> Defend {mdf*100:.0f}%", "white")

    print()

    # Test EV comparison
    cprint("EV Comparison:", "yellow")
    pot = 100
    facing = 50
    equity = 0.40

    result = calc.compare_actions(pot, facing, equity)
    cprint(f"  Pot: ${pot}, Facing: ${facing}, Equity: {equity*100:.0f}%", "white")
    for action, ev in result.ev_per_action.items():
        color = 'green' if ev == result.ev else 'white'
        cprint(f"    {action.upper()}: ${ev:+.2f}", color)
    cprint(f"  >>> {result.description}", "green", attrs=['bold'])

    print()

    # Test geometric sizing
    cprint("Geometric Bet Sizing:", "yellow")
    pot, stack = 100, 500
    for streets in [1, 2, 3]:
        bet = calc.geometric_sizing(pot, stack, streets)
        cprint(f"  {streets} street(s) to go: bet ${bet:.0f} ({bet/pot*100:.0f}% pot)", "white")

    print()

    # Test value:bluff ratio
    cprint("Value to Bluff Ratio:", "yellow")
    pot = 100
    for bet in [33, 50, 75, 100]:
        ratio = calc.value_to_bluff_ratio(bet, pot)
        cprint(f"  ${bet} into ${pot}: {ratio:.1f}:1 value:bluff", "white")
