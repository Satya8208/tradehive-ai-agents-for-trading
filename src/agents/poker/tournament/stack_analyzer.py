"""
Stack Analyzer - Tournament stack pressure and M-ratio analysis
Understanding when to push and when to wait
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


class StackZone(Enum):
    """Stack size zones based on M-ratio"""
    GREEN = "green"       # M > 20: Full play
    YELLOW = "yellow"     # M 10-20: Tightening up
    ORANGE = "orange"     # M 6-10: Push/fold mode approaching
    RED = "red"          # M 1-5: Push/fold only
    DEAD = "dead"        # M < 1: Desperate


class TournamentPhase(Enum):
    """Tournament phases"""
    EARLY = "early"           # Lots of play, deep stacks
    MIDDLE = "middle"         # Building stack
    LATE = "late"             # Approaching money
    BUBBLE = "bubble"         # Just before money
    IN_THE_MONEY = "itm"      # Paid positions
    FINAL_TABLE = "final"     # Final table


@dataclass
class StackAnalysis:
    """Complete stack analysis"""
    chips: int
    bb_count: float           # Stack in big blinds
    m_ratio: float            # Harrington's M
    q_ratio: float            # Stack relative to average
    zone: StackZone
    effective_m: float        # M adjusted for table size
    rounds_left: float        # Estimated orbits before blinding out
    strategy: str             # Recommended strategy


@dataclass
class TableDynamics:
    """Analysis of table stack distribution"""
    chip_leader: int          # Biggest stack (index)
    short_stack: int          # Shortest stack (index)
    average_stack: float      # Average chips
    median_stack: float       # Median stack
    std_deviation: float      # Stack distribution spread
    pressure_index: float     # How much pressure short stacks feel


class StackAnalyzer:
    """
    Tournament stack and pressure analyzer

    Calculates:
    - M-ratio (Harrington's M)
    - Effective M (table-size adjusted)
    - Stack zones and strategies
    - Table dynamics
    - Push/fold pressure
    """

    # Strategy recommendations by zone
    ZONE_STRATEGIES = {
        StackZone.GREEN: "Full poker - all plays available. Open standard ranges, "
                         "play speculative hands, set-mine, 3-bet bluff.",
        StackZone.YELLOW: "Tightening phase - reduce speculative plays, "
                          "focus on premium hands and position. Still have fold equity.",
        StackZone.ORANGE: "Pre-push/fold - mostly raise/fold preflop, "
                          "minimize postflop play. Open-shove marginal spots.",
        StackZone.RED: "Push or fold only - no limping, no calling, no postflop. "
                       "Shove with any reasonable hand.",
        StackZone.DEAD: "Desperate mode - shove any playable hand. "
                        "Need to double up immediately.",
    }

    def __init__(self):
        pass

    def calculate_m_ratio(self, stack: int, sb: int, bb: int, ante: int = 0,
                          players: int = 9) -> float:
        """
        Calculate Harrington's M-ratio

        M = Stack / (SB + BB + Antes)

        Args:
            stack: Current chip stack
            sb: Small blind
            bb: Big blind
            ante: Ante per player
            players: Players at table

        Returns:
            M-ratio
        """
        orbit_cost = sb + bb + (ante * players)
        if orbit_cost == 0:
            return float('inf')
        return stack / orbit_cost

    def effective_m(self, m_ratio: float, players: int) -> float:
        """
        Calculate effective M (adjusted for short-handed play)

        Effective M = M * (players / 10)

        Short-handed tables = fewer orbits = faster blind pressure

        Args:
            m_ratio: Standard M
            players: Players at table

        Returns:
            Effective M
        """
        return m_ratio * (players / 10)

    def get_zone(self, m_ratio: float) -> StackZone:
        """
        Determine stack zone from M-ratio

        Args:
            m_ratio: The M-ratio

        Returns:
            StackZone
        """
        if m_ratio > 20:
            return StackZone.GREEN
        elif m_ratio > 10:
            return StackZone.YELLOW
        elif m_ratio > 5:
            return StackZone.ORANGE
        elif m_ratio > 1:
            return StackZone.RED
        else:
            return StackZone.DEAD

    def analyze_stack(self, stack: int, sb: int, bb: int, ante: int = 0,
                      players: int = 9, avg_stack: float = None) -> StackAnalysis:
        """
        Complete stack analysis

        Args:
            stack: Our chip stack
            sb: Small blind
            bb: Big blind
            ante: Per-player ante
            players: Players at table
            avg_stack: Average stack (optional)

        Returns:
            StackAnalysis
        """
        bb_count = stack / bb if bb > 0 else 0
        m_ratio = self.calculate_m_ratio(stack, sb, bb, ante, players)
        eff_m = self.effective_m(m_ratio, players)
        zone = self.get_zone(eff_m)

        # Q-ratio (stack vs average)
        q_ratio = stack / avg_stack if avg_stack and avg_stack > 0 else 1.0

        # Estimate rounds left before blinding out
        orbit_cost = sb + bb + (ante * players)
        rounds_left = stack / orbit_cost if orbit_cost > 0 else float('inf')

        strategy = self.ZONE_STRATEGIES[zone]

        return StackAnalysis(
            chips=stack,
            bb_count=bb_count,
            m_ratio=m_ratio,
            q_ratio=q_ratio,
            zone=zone,
            effective_m=eff_m,
            rounds_left=rounds_left,
            strategy=strategy
        )

    def analyze_table(self, stacks: List[int]) -> TableDynamics:
        """
        Analyze table stack distribution

        Args:
            stacks: All player stacks

        Returns:
            TableDynamics
        """
        if not stacks:
            return TableDynamics(0, 0, 0, 0, 0, 0)

        n = len(stacks)
        sorted_stacks = sorted(stacks)

        chip_leader = stacks.index(max(stacks))
        short_stack = stacks.index(min(stacks))
        average = sum(stacks) / n

        # Median
        if n % 2 == 0:
            median = (sorted_stacks[n//2 - 1] + sorted_stacks[n//2]) / 2
        else:
            median = sorted_stacks[n//2]

        # Standard deviation
        variance = sum((s - average) ** 2 for s in stacks) / n
        std_dev = variance ** 0.5

        # Pressure index: how spread out stacks are (0 = equal, 1 = max spread)
        if max(stacks) > 0:
            pressure = std_dev / average if average > 0 else 0
        else:
            pressure = 0

        return TableDynamics(
            chip_leader=chip_leader,
            short_stack=short_stack,
            average_stack=average,
            median_stack=median,
            std_deviation=std_dev,
            pressure_index=min(1.0, pressure)
        )

    def get_push_threshold(self, m_ratio: float) -> float:
        """
        Get the minimum hand strength to push based on M

        Lower M = push with weaker hands

        Args:
            m_ratio: Current M

        Returns:
            Threshold as fraction of hands (0.0 to 1.0)
        """
        if m_ratio > 20:
            return 0.0  # Don't need to push
        elif m_ratio > 10:
            return 0.10  # Top 10%
        elif m_ratio > 7:
            return 0.15  # Top 15%
        elif m_ratio > 5:
            return 0.20  # Top 20%
        elif m_ratio > 3:
            return 0.30  # Top 30%
        elif m_ratio > 2:
            return 0.40  # Top 40%
        elif m_ratio > 1:
            return 0.50  # Top 50%
        else:
            return 0.70  # Push anything playable

    def phase_from_players(self, current_players: int, starting_players: int,
                           paid_places: int) -> TournamentPhase:
        """
        Determine tournament phase

        Args:
            current_players: Players remaining
            starting_players: Original field
            paid_places: How many spots are paid

        Returns:
            TournamentPhase
        """
        pct_remaining = current_players / starting_players

        if current_players <= 9:
            return TournamentPhase.FINAL_TABLE
        elif current_players <= paid_places:
            return TournamentPhase.IN_THE_MONEY
        elif current_players <= paid_places + 5:
            return TournamentPhase.BUBBLE
        elif pct_remaining < 0.3:
            return TournamentPhase.LATE
        elif pct_remaining < 0.6:
            return TournamentPhase.MIDDLE
        else:
            return TournamentPhase.EARLY

    def should_icm_adjust(self, phase: TournamentPhase, zone: StackZone) -> Tuple[bool, str]:
        """
        Determine if ICM adjustments are needed

        Args:
            phase: Tournament phase
            zone: Our stack zone

        Returns:
            (should_adjust, reason)
        """
        if phase == TournamentPhase.BUBBLE:
            return True, "Bubble - maximum ICM pressure, tighten up significantly"

        if phase == TournamentPhase.FINAL_TABLE:
            return True, "Final table - every spot matters, consider payouts"

        if phase == TournamentPhase.IN_THE_MONEY:
            if zone in (StackZone.RED, StackZone.DEAD):
                return True, "Short stacked ITM - survival vs ladder climb decision"
            return False, "ITM with chips - can play for the win"

        if zone == StackZone.GREEN:
            return False, "Deep stacked - play chip EV"

        return False, "Standard tournament play"

    def stack_recommendation(self, analysis: StackAnalysis, phase: TournamentPhase) -> str:
        """
        Get specific recommendations based on stack and phase

        Args:
            analysis: Stack analysis
            phase: Tournament phase

        Returns:
            Detailed recommendation string
        """
        recs = []

        # Zone-based recommendations
        if analysis.zone == StackZone.GREEN:
            recs.append("• Open standard ranges, play for stacks")
            recs.append("• Set-mine with small pairs")
            recs.append("• 3-bet polarized (value + bluffs)")

        elif analysis.zone == StackZone.YELLOW:
            recs.append("• Tighten opening ranges 10-15%")
            recs.append("• Reduce speculative plays")
            recs.append("• Start picking spots to accumulate")

        elif analysis.zone == StackZone.ORANGE:
            recs.append("• Open-shove from late position")
            recs.append("• Minimize postflop play")
            recs.append(f"• Push top {self.get_push_threshold(analysis.effective_m)*100:.0f}% of hands")

        elif analysis.zone == StackZone.RED:
            recs.append("• PUSH OR FOLD ONLY")
            recs.append("• No limping, no calling")
            recs.append("• Shove any Ax, Kx, pairs, suited connectors")

        else:  # DEAD
            recs.append("• DESPERATE - shove any playable hand")
            recs.append("• Need to double up immediately")
            recs.append("• Ignore pot odds, just survive")

        # Phase adjustments
        if phase == TournamentPhase.BUBBLE:
            recs.append("• BUBBLE: Tighten up 20-30%")
            recs.append("• Attack other short stacks carefully")

        elif phase == TournamentPhase.FINAL_TABLE:
            recs.append("• FINAL TABLE: Consider pay jumps")

        return "\n".join(recs)


# === Standalone Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n=== Stack Analyzer Test ===\n", "cyan", attrs=['bold'])

    analyzer = StackAnalyzer()

    # Test scenario: Final table bubble
    sb, bb, ante = 100, 200, 25
    players = 9
    stacks = [15000, 12000, 8000, 6000, 4000, 3000, 2500, 2000, 500]
    avg_stack = sum(stacks) / len(stacks)

    cprint(f"Blinds: {sb}/{bb} with {ante} ante", "yellow")
    cprint(f"Average stack: {avg_stack:.0f}", "yellow")
    print()

    cprint("Stack Analysis by Player:", "yellow")
    for i, stack in enumerate(stacks):
        analysis = analyzer.analyze_stack(stack, sb, bb, ante, players, avg_stack)
        zone_colors = {
            StackZone.GREEN: "green",
            StackZone.YELLOW: "yellow", 
            StackZone.ORANGE: "red",
            StackZone.RED: "red",
            StackZone.DEAD: "magenta"
        }
        color = zone_colors.get(analysis.zone, "white")
        cprint(f"  Player {i+1}: {stack:,} chips | {analysis.bb_count:.0f}bb | "
               f"M={analysis.m_ratio:.1f} | {analysis.zone.value.upper()}", color)

    print()
    cprint("Table Dynamics:", "yellow")
    dynamics = analyzer.analyze_table(stacks)
    cprint(f"  Chip leader: Player {dynamics.chip_leader + 1} ({stacks[dynamics.chip_leader]:,})", "green")
    cprint(f"  Short stack: Player {dynamics.short_stack + 1} ({stacks[dynamics.short_stack]:,})", "red")
    cprint(f"  Average: {dynamics.average_stack:,.0f}", "white")
    cprint(f"  Pressure index: {dynamics.pressure_index:.2f}", "white")

    print()
    cprint("Short Stack (500 chips) Recommendation:", "yellow")
    short_analysis = analyzer.analyze_stack(500, sb, bb, ante, players, avg_stack)
    phase = TournamentPhase.FINAL_TABLE
    rec = analyzer.stack_recommendation(short_analysis, phase)
    for line in rec.split("\n"):
        cprint(f"  {line}", "cyan")
