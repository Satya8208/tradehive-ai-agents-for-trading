"""
ICM Calculator - Independent Chip Model for tournament equity
The mathematical foundation of tournament decision-making
Built with love by TradeHive
"""

from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
from functools import lru_cache
import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)


@dataclass
class ICMResult:
    """Result of ICM calculation"""
    stacks: List[float]           # Current stacks
    equities: List[float]         # ICM equity for each player
    payouts: List[float]          # Prize pool payouts
    total_prize: float            # Total prize pool
    chips_total: int              # Total chips in play


@dataclass
class ICMDecision:
    """ICM-adjusted decision result"""
    chip_ev: float                # Expected value in chips
    icm_ev: float                 # Expected value in $ (ICM)
    risk_premium: float           # How much ICM costs us
    action: str                   # Recommended action
    reasoning: str                # Explanation


class ICMCalculator:
    """
    Independent Chip Model calculator

    Calculates tournament equity based on chip stacks and payout structure.
    Uses the Malmuth-Harville model for finish position probabilities.

    Key concepts:
    - Chips aren't linearly correlated to equity
    - Doubling up doesn't double your equity
    - Losing chips hurts more than winning helps (risk premium)
    """

    def __init__(self):
        self._cache = {}

    def calculate_icm(self, stacks: List[float], payouts: List[float]) -> ICMResult:
        """
        Calculate ICM equity for all players

        Args:
            stacks: Chip stack for each player
            payouts: Payout for each finishing position

        Returns:
            ICMResult with equity breakdown
        """
        n_players = len(stacks)
        n_payouts = len(payouts)
        total_chips = sum(stacks)
        total_prize = sum(payouts)

        # Normalize stacks to percentages
        if total_chips == 0:
            return ICMResult(stacks, [0.0] * n_players, payouts, total_prize, int(total_chips))

        stack_percentages = [s / total_chips for s in stacks]

        # Calculate equity for each player
        equities = []
        for player_idx in range(n_players):
            equity = self._calculate_player_equity(
                player_idx, stack_percentages, payouts, n_players
            )
            equities.append(equity)

        return ICMResult(
            stacks=list(stacks),
            equities=equities,
            payouts=list(payouts),
            total_prize=total_prize,
            chips_total=int(total_chips)
        )

    def _calculate_player_equity(self, player_idx: int, stack_pcts: List[float],
                                  payouts: List[float], n_players: int) -> float:
        """
        Calculate ICM equity for a single player

        Uses recursive Malmuth-Harville calculation
        """
        equity = 0.0
        n_payouts = len(payouts)

        # For each finishing position we could achieve
        for finish_pos in range(min(n_payouts, n_players)):
            prob = self._finish_probability(
                player_idx, finish_pos, tuple(stack_pcts), tuple(range(n_players))
            )
            equity += prob * payouts[finish_pos]

        return equity

    @lru_cache(maxsize=10000)
    def _finish_probability(self, player_idx: int, target_pos: int,
                            stack_pcts: Tuple[float, ...],
                            remaining: Tuple[int, ...]) -> float:
        """
        Calculate probability of player finishing in target position

        Recursive Malmuth-Harville model:
        P(finish in position N) = sum over all players who could finish first *
                                  P(that player finishes first) *
                                  P(we finish in N-1 among remaining players)
        """
        if len(remaining) == 0:
            return 0.0

        if target_pos == 0:
            # Probability of finishing 1st = our stack / total remaining stacks
            total = sum(stack_pcts[i] for i in remaining)
            if total == 0:
                return 0.0
            return stack_pcts[player_idx] / total if player_idx in remaining else 0.0

        if player_idx not in remaining:
            return 0.0

        # For later positions, we need someone else to finish first
        prob = 0.0
        total = sum(stack_pcts[i] for i in remaining)

        if total == 0:
            return 0.0

        for first_out in remaining:
            if first_out == player_idx:
                continue

            # Probability this player finishes first
            p_first = stack_pcts[first_out] / total

            # Remaining players after first_out busts
            new_remaining = tuple(p for p in remaining if p != first_out)

            # Probability we finish in target_pos - 1 among remaining
            p_later = self._finish_probability(
                player_idx, target_pos - 1, stack_pcts, new_remaining
            )

            prob += p_first * p_later

        return prob

    def calculate_ev_call(self, hero_stack: float, villain_stack: float,
                          all_stacks: List[float], pot_size: float,
                          call_amount: float, win_prob: float,
                          payouts: List[float], hero_idx: int = 0) -> ICMDecision:
        """
        Calculate ICM EV of calling an all-in

        Args:
            hero_stack: Our current stack
            villain_stack: Opponent's stack (the raiser)
            all_stacks: All stacks at table
            pot_size: Current pot
            call_amount: Amount we need to call
            win_prob: Our probability of winning the hand
            payouts: Payout structure
            hero_idx: Our position in stacks list

        Returns:
            ICMDecision with recommendation
        """
        # Calculate current ICM equity
        current_icm = self.calculate_icm(all_stacks, payouts)
        current_eq = current_icm.equities[hero_idx]

        # Stack if we win
        amount_at_risk = min(call_amount, hero_stack)
        win_from_villain = min(amount_at_risk, villain_stack)
        
        stacks_win = list(all_stacks)
        stacks_win[hero_idx] += win_from_villain + pot_size

        # Find villain index (assume it's the one with matching stack closest to villain_stack)
        villain_idx = -1
        for i, s in enumerate(all_stacks):
            if i != hero_idx and abs(s - villain_stack) < 1:
                villain_idx = i
                break

        if villain_idx >= 0:
            stacks_win[villain_idx] = max(0, all_stacks[villain_idx] - win_from_villain)

        # Stack if we lose
        stacks_lose = list(all_stacks)
        stacks_lose[hero_idx] -= amount_at_risk
        if villain_idx >= 0:
            stacks_lose[villain_idx] += amount_at_risk + pot_size

        # Calculate ICM in each scenario
        icm_win = self.calculate_icm(stacks_win, payouts)
        icm_lose = self.calculate_icm(stacks_lose, payouts)

        win_eq = icm_win.equities[hero_idx] if hero_idx < len(icm_win.equities) else 0
        lose_eq = icm_lose.equities[hero_idx] if hero_idx < len(icm_lose.equities) else 0

        # ICM EV of calling
        icm_ev_call = win_prob * win_eq + (1 - win_prob) * lose_eq
        icm_ev_fold = current_eq

        # Chip EV for comparison
        chip_ev_call = win_prob * (pot_size + call_amount) - (1 - win_prob) * call_amount

        # Risk premium = how much ICM costs us
        risk_premium = chip_ev_call - (icm_ev_call - current_eq)

        # Decision
        if icm_ev_call > icm_ev_fold:
            action = "call"
            reasoning = f"ICM EV call ${icm_ev_call:.2f} > fold ${icm_ev_fold:.2f}"
        else:
            action = "fold"
            reasoning = f"ICM EV fold ${icm_ev_fold:.2f} > call ${icm_ev_call:.2f}"

        return ICMDecision(
            chip_ev=chip_ev_call,
            icm_ev=icm_ev_call - current_eq,  # Marginal gain/loss
            risk_premium=risk_premium,
            action=action,
            reasoning=reasoning
        )

    def bubble_factor(self, hero_stack: float, all_stacks: List[float],
                      payouts: List[float], hero_idx: int = 0) -> float:
        """
        Calculate bubble factor - how much ICM amplifies our risk

        Bubble factor > 1 means we should tighten up
        Bubble factor = chip_value_of_losing / chip_value_of_winning

        Args:
            hero_stack: Our stack
            all_stacks: All stacks
            payouts: Payout structure
            hero_idx: Our index

        Returns:
            Bubble factor (typically 1.0 to 3.0+)
        """
        current_icm = self.calculate_icm(all_stacks, payouts)
        current_eq = current_icm.equities[hero_idx]

        # Simulate doubling up
        double_stacks = list(all_stacks)
        double_stacks[hero_idx] *= 2
        double_icm = self.calculate_icm(double_stacks, payouts)
        double_eq = double_icm.equities[hero_idx]

        # Simulate busting out
        bust_stacks = list(all_stacks)
        bust_stacks[hero_idx] = 0
        bust_icm = self.calculate_icm(bust_stacks, payouts)
        bust_eq = bust_icm.equities[hero_idx]  # Should be 0

        # Gain from doubling vs loss from busting
        gain = double_eq - current_eq
        loss = current_eq - bust_eq

        if gain == 0:
            return float('inf')

        return loss / gain

    def chip_equity(self, stacks: List[float]) -> List[float]:
        """
        Calculate chip equity (linear - for comparison)

        Args:
            stacks: Chip stacks

        Returns:
            Equity as fraction of total chips
        """
        total = sum(stacks)
        if total == 0:
            return [0.0] * len(stacks)
        return [s / total for s in stacks]

    def icm_difference(self, stacks: List[float], payouts: List[float]) -> Dict[int, float]:
        """
        Calculate difference between chip equity and ICM equity

        Positive = ICM favors this player vs chips
        Negative = ICM penalizes this player vs chips

        Args:
            stacks: Chip stacks
            payouts: Payouts

        Returns:
            Dict mapping player index to equity difference
        """
        icm_result = self.calculate_icm(stacks, payouts)
        chip_eq = self.chip_equity(stacks)

        total_prize = sum(payouts)
        differences = {}

        for i in range(len(stacks)):
            chip_eq_dollars = chip_eq[i] * total_prize
            icm_eq_dollars = icm_result.equities[i]
            differences[i] = icm_eq_dollars - chip_eq_dollars

        return differences


# === Standalone Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n=== ICM Calculator Test ===\n", "cyan", attrs=['bold'])

    calc = ICMCalculator()

    # Standard MTT final table (6 players, top 3 paid)
    stacks = [5000, 4000, 3000, 2000, 1500, 500]
    payouts = [1000, 600, 400, 0, 0, 0]  # Top 3 paid

    cprint("Final Table ICM:", "yellow")
    cprint(f"Stacks: {stacks}", "white")
    cprint(f"Payouts: {payouts}", "white")

    result = calc.calculate_icm(stacks, payouts)

    print()
    for i, (stack, equity) in enumerate(zip(stacks, result.equities)):
        chip_eq = stack / sum(stacks) * sum(payouts)
        diff = equity - chip_eq
        sign = "+" if diff > 0 else ""
        cprint(f"  Player {i+1}: {stack} chips -> ${equity:.2f} ICM ({sign}${diff:.2f} vs chip EV)", "white")

    print()
    cprint("Bubble Factor Analysis:", "yellow")
    for i, stack in enumerate(stacks):
        bf = calc.bubble_factor(stack, stacks, payouts, i)
        cprint(f"  Player {i+1} ({stack} chips): BF = {bf:.2f}", 
               "red" if bf > 1.5 else "green" if bf < 1.2 else "white")

    print()
    cprint("Call Decision (short stack vs chip leader):", "yellow")
    decision = calc.calculate_ev_call(
        hero_stack=500,
        villain_stack=5000,
        all_stacks=stacks,
        pot_size=300,
        call_amount=500,
        win_prob=0.40,  # 40% equity
        payouts=payouts,
        hero_idx=5  # Short stack
    )
    cprint(f"  Chip EV: ${decision.chip_ev:.2f}", "white")
    cprint(f"  ICM EV: ${decision.icm_ev:.2f}", "white")
    cprint(f"  Risk Premium: ${decision.risk_premium:.2f}", "white")
    cprint(f"  Recommendation: {decision.action.upper()}", "green" if decision.action == "call" else "red")
    cprint(f"  {decision.reasoning}", "cyan")
