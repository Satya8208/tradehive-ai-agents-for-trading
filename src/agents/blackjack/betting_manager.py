"""
Betting Manager - Optimal bet sizing using Kelly Criterion and spread betting
Built with love by TradeHive
"""

import csv
from pathlib import Path
from datetime import datetime
from typing import Dict, Literal, Optional
from dataclasses import dataclass, field
from termcolor import cprint

BettingMethod = Literal['kelly', 'spread', 'spread_aggressive', 'flat']


@dataclass
class BankrollHistory:
    """Track bankroll over time"""
    timestamp: str
    hand_number: int
    bankroll: float
    change: float
    bet_size: float
    true_count: float
    method: str


@dataclass
class BettingConfig:
    """Betting configuration"""
    min_bet: float = 10
    max_bet: float = 200
    starting_bankroll: float = 1000
    kelly_fraction: float = 0.5  # Fractional Kelly for safety
    spread_ratio: int = 12  # 1-12 spread
    method: BettingMethod = 'spread'


class BettingManager:
    """
    Optimal bet sizing for blackjack using card counting

    Implements:
    - Kelly Criterion: Mathematically optimal bet sizing
    - Spread Betting: Simple multiplier based on true count
    - Flat Betting: Constant bet size (for testing)
    """

    # Spread betting multipliers based on true count
    # More aggressive spread for higher edge situations
    SPREAD_TABLE: Dict[int, float] = {
        -5: 1.0,   # Minimum bet at very negative counts
        -4: 1.0,
        -3: 1.0,
        -2: 1.0,
        -1: 1.0,
        0: 1.0,    # Minimum bet at neutral count
        1: 2.0,    # 2x at TC +1
        2: 4.0,    # 4x at TC +2
        3: 6.0,    # 6x at TC +3
        4: 8.0,    # 8x at TC +4
        5: 10.0,   # 10x at TC +5
        6: 12.0,   # Max spread at TC +6+
    }

    # Aggressive spread for poor penetration games (50% or less)
    # Bet more aggressively at lower TCs since high TCs are rare
    SPREAD_TABLE_AGGRESSIVE: Dict[int, float] = {
        -5: 1.0,
        -4: 1.0,
        -3: 1.0,
        -2: 1.0,
        -1: 1.0,
        0: 1.0,    # Minimum bet at neutral/negative
        1: 2.0,    # 2x at TC +1
        2: 4.0,    # 4x at TC +2
        3: 8.0,    # 8x at TC +3 (vs 6x standard)
        4: 12.0,   # 12x at TC +4 (vs 8x standard)
        5: 12.0,   # Max spread
        6: 12.0,   # Max spread
    }

    def __init__(self, config: BettingConfig = None, data_dir: Path = None):
        """
        Initialize betting manager

        Args:
            config: Betting configuration
            data_dir: Directory for saving bankroll history
        """
        self.config = config or BettingConfig()
        self.bankroll = self.config.starting_bankroll
        self.peak_bankroll = self.bankroll
        self.low_bankroll = self.bankroll
        self.hand_number = 0

        # Data directory for logging
        if data_dir:
            self.data_dir = data_dir
        else:
            self.data_dir = Path(__file__).parent.parent.parent / "data" / "blackjack_agent"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.data_dir / "bankroll_history.csv"

        # Session tracking
        self.session_start = self.bankroll
        self.total_wagered = 0
        self.hands_won = 0
        self.hands_lost = 0

        self._init_csv()

    def _init_csv(self) -> None:
        """Initialize CSV file with headers if needed"""
        if not self.history_file.exists():
            with open(self.history_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'hand_number', 'bankroll', 'change',
                    'bet_size', 'true_count', 'method', 'session_pnl'
                ])

    def calculate_edge(self, true_count: float) -> float:
        """
        Estimate player edge based on true count

        Rule of thumb: Each +1 TC ≈ +0.5% edge
        Base house edge with perfect basic strategy ≈ -0.5%

        Args:
            true_count: Current true count

        Returns:
            Estimated edge as decimal (e.g., 0.01 = 1% edge)
        """
        base_edge = -0.005  # 0.5% house edge with basic strategy
        count_adjustment = true_count * 0.005  # 0.5% per true count
        return base_edge + count_adjustment

    def kelly_bet(self, true_count: float) -> float:
        """
        Calculate optimal bet using Kelly Criterion

        Kelly formula: f* = edge / variance
        For blackjack: variance ≈ 1.15

        Args:
            true_count: Current true count

        Returns:
            Optimal bet size
        """
        edge = self.calculate_edge(true_count)

        # No edge = minimum bet
        if edge <= 0:
            return self.config.min_bet

        # Kelly calculation
        variance = 1.15  # Approximate blackjack variance
        kelly_fraction_optimal = edge / variance

        # Apply fractional Kelly for reduced variance
        # Full Kelly is mathematically optimal but very volatile
        fractional_kelly = kelly_fraction_optimal * self.config.kelly_fraction

        # Calculate bet as fraction of bankroll
        kelly_bet = self.bankroll * fractional_kelly

        # Clamp to min/max
        return self._clamp_bet(kelly_bet)

    def spread_bet(self, true_count: float) -> float:
        """
        Calculate bet using spread betting

        Simple multiplier system based on true count

        Args:
            true_count: Current true count

        Returns:
            Bet size based on spread
        """
        # Round true count for table lookup
        tc_rounded = max(-5, min(6, round(true_count)))

        # Get multiplier from spread table
        multiplier = self.SPREAD_TABLE.get(tc_rounded, 1.0)

        # Calculate bet
        bet = self.config.min_bet * multiplier

        return self._clamp_bet(bet)

    def spread_aggressive_bet(self, true_count: float) -> float:
        """
        Aggressive spread betting for poor penetration games.

        Optimized for 50% penetration where high counts are rare.
        Bets more aggressively at TC +3 and +4.

        Args:
            true_count: Current true count

        Returns:
            Bet size based on aggressive spread
        """
        tc_rounded = max(-5, min(6, round(true_count)))
        multiplier = self.SPREAD_TABLE_AGGRESSIVE.get(tc_rounded, 1.0)
        bet = self.config.min_bet * multiplier
        return self._clamp_bet(bet)

    def flat_bet(self) -> float:
        """Return constant minimum bet (for testing/comparison)"""
        return self.config.min_bet

    def get_bet(self, true_count: float = 0) -> float:
        """
        Get recommended bet size based on configured method

        Args:
            true_count: Current true count

        Returns:
            Recommended bet size
        """
        method = self.config.method

        if method == 'kelly':
            return self.kelly_bet(true_count)
        elif method == 'spread':
            return self.spread_bet(true_count)
        elif method == 'spread_aggressive':
            return self.spread_aggressive_bet(true_count)
        else:
            return self.flat_bet()

    def _clamp_bet(self, bet: float) -> float:
        """Clamp bet to min/max and available bankroll"""
        # Don't bet more than bankroll
        max_allowed = min(self.config.max_bet, self.bankroll)

        return max(self.config.min_bet, min(bet, max_allowed))

    def update_bankroll(self, result: float, bet_size: float, true_count: float = 0) -> None:
        """
        Update bankroll after a hand

        Args:
            result: P&L from the hand (positive = win, negative = loss)
            bet_size: Size of the bet
            true_count: True count at time of bet
        """
        self.bankroll += result
        self.hand_number += 1
        self.total_wagered += bet_size

        # Track peak/low
        if self.bankroll > self.peak_bankroll:
            self.peak_bankroll = self.bankroll
        if self.bankroll < self.low_bankroll:
            self.low_bankroll = self.bankroll

        # Track wins/losses
        if result > 0:
            self.hands_won += 1
        elif result < 0:
            self.hands_lost += 1

        # Log to CSV
        self._log_history(result, bet_size, true_count)

    def _log_history(self, change: float, bet_size: float, true_count: float) -> None:
        """Log bankroll update to CSV"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session_pnl = self.bankroll - self.session_start

        with open(self.history_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp,
                self.hand_number,
                round(self.bankroll, 2),
                round(change, 2),
                round(bet_size, 2),
                round(true_count, 2),
                self.config.method,
                round(session_pnl, 2)
            ])

    def can_bet(self, amount: float = None) -> bool:
        """Check if player can afford to bet"""
        if amount is None:
            amount = self.config.min_bet
        return self.bankroll >= amount

    @property
    def session_pnl(self) -> float:
        """Get session profit/loss"""
        return self.bankroll - self.session_start

    @property
    def session_roi(self) -> float:
        """Get session ROI percentage"""
        if self.total_wagered == 0:
            return 0
        return (self.session_pnl / self.total_wagered) * 100

    @property
    def drawdown(self) -> float:
        """Get current drawdown from peak"""
        if self.peak_bankroll == 0:
            return 0
        return ((self.peak_bankroll - self.bankroll) / self.peak_bankroll) * 100

    @property
    def risk_of_ruin(self) -> float:
        """
        Estimate risk of ruin based on current bankroll and bet size

        Simplified calculation - actual RoR depends on many factors
        """
        if self.bankroll <= 0:
            return 100.0

        # Number of min bets in bankroll
        units = self.bankroll / self.config.min_bet

        # Rough RoR estimate (very simplified)
        if units > 100:
            return 0.1
        elif units > 50:
            return 1.0
        elif units > 25:
            return 5.0
        elif units > 10:
            return 25.0
        else:
            return 50.0

    def get_bet_info(self, true_count: float) -> Dict:
        """Get detailed betting information for display"""
        bet = self.get_bet(true_count)
        edge = self.calculate_edge(true_count)

        return {
            'recommended_bet': bet,
            'edge': edge * 100,  # As percentage
            'method': self.config.method,
            'bankroll': self.bankroll,
            'true_count': true_count,
            'min_bet': self.config.min_bet,
            'max_bet': self.config.max_bet,
            'bet_as_percent': (bet / self.bankroll * 100) if self.bankroll > 0 else 0
        }

    def get_stats(self) -> Dict:
        """Get comprehensive betting statistics"""
        total_hands = self.hands_won + self.hands_lost

        return {
            'bankroll': round(self.bankroll, 2),
            'session_start': round(self.session_start, 2),
            'session_pnl': round(self.session_pnl, 2),
            'session_roi': round(self.session_roi, 2),
            'peak_bankroll': round(self.peak_bankroll, 2),
            'low_bankroll': round(self.low_bankroll, 2),
            'drawdown': round(self.drawdown, 2),
            'hands_played': total_hands,
            'hands_won': self.hands_won,
            'hands_lost': self.hands_lost,
            'win_rate': round(self.hands_won / total_hands * 100, 1) if total_hands > 0 else 0,
            'total_wagered': round(self.total_wagered, 2),
            'risk_of_ruin': round(self.risk_of_ruin, 1),
            'units_remaining': round(self.bankroll / self.config.min_bet, 1)
        }

    def display_status(self, true_count: float = 0) -> None:
        """Display current betting status in terminal"""
        bet_info = self.get_bet_info(true_count)
        stats = self.get_stats()

        cprint("\n" + "=" * 50, "yellow")
        cprint("BETTING STATUS", "yellow", attrs=['bold'])
        cprint("=" * 50, "yellow")

        # Bankroll
        br_color = 'green' if self.session_pnl >= 0 else 'red'
        cprint(f"Bankroll: ${stats['bankroll']:.2f}", br_color, attrs=['bold'])
        cprint(f"Session P&L: ${stats['session_pnl']:+.2f} ({stats['session_roi']:+.1f}%)", br_color)

        # Betting recommendation
        cprint(f"\nTrue Count: {true_count:+.1f}", "cyan")
        edge_color = 'green' if bet_info['edge'] > 0 else 'red' if bet_info['edge'] < 0 else 'white'
        cprint(f"Edge: {bet_info['edge']:+.2f}%", edge_color)
        cprint(f"Recommended Bet: ${bet_info['recommended_bet']:.0f} ({self.config.method})", "white", attrs=['bold'])

        # Risk metrics
        cprint(f"\nDrawdown: {stats['drawdown']:.1f}%", "yellow")
        cprint(f"Units Left: {stats['units_remaining']:.0f}", "white")
        cprint(f"Risk of Ruin: {stats['risk_of_ruin']:.1f}%", "red" if stats['risk_of_ruin'] > 10 else "green")

        cprint("=" * 50 + "\n", "yellow")


# Standalone test
if __name__ == "__main__":
    cprint("\n=== Betting Manager Test ===\n", "cyan", attrs=['bold'])

    config = BettingConfig(
        min_bet=10,
        max_bet=200,
        starting_bankroll=1000,
        kelly_fraction=0.5,
        method='spread'
    )

    manager = BettingManager(config)

    # Test different true counts
    test_counts = [-2, -1, 0, 1, 2, 3, 4, 5, 6]

    cprint("Spread Betting Table:", "yellow")
    print("-" * 40)
    for tc in test_counts:
        bet = manager.spread_bet(tc)
        edge = manager.calculate_edge(tc)
        print(f"TC {tc:+2}: Bet ${bet:6.0f} | Edge {edge*100:+5.2f}%")

    # Switch to Kelly
    manager.config.method = 'kelly'
    print()
    cprint("Kelly Betting:", "yellow")
    print("-" * 40)
    for tc in test_counts:
        bet = manager.kelly_bet(tc)
        edge = manager.calculate_edge(tc)
        print(f"TC {tc:+2}: Bet ${bet:6.0f} | Edge {edge*100:+5.2f}%")

    # Simulate some results
    print()
    cprint("Simulating 10 hands...", "magenta")
    manager.config.method = 'spread'

    import random
    for i in range(10):
        tc = random.uniform(-2, 4)
        bet = manager.get_bet(tc)
        result = random.choice([-1, -1, 0, 1, 1, 1.5]) * bet  # Simulate outcomes

        manager.update_bankroll(result, bet, tc)
        print(f"Hand {i+1}: TC={tc:+.1f}, Bet=${bet:.0f}, Result=${result:+.0f}, BR=${manager.bankroll:.0f}")

    # Final status
    manager.display_status(true_count=2.5)
