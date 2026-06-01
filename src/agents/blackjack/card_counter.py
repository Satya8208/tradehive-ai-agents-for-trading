"""
Card Counter Engine - Advanced card counting systems for blackjack
Implements Hi-Lo, Omega II, and Wong Halves counting systems
Built with love by TradeHive
"""

from typing import Dict, List, Optional, Literal
from termcolor import cprint
from dataclasses import dataclass

# Card counting system value mappings
# Hi-Lo System (Level 1) - Simple and effective
HI_LO_VALUES: Dict[str, int] = {
    '2': 1, '3': 1, '4': 1, '5': 1, '6': 1,      # Low cards: +1
    '7': 0, '8': 0, '9': 0,                       # Neutral: 0
    '10': -1, 'J': -1, 'Q': -1, 'K': -1, 'A': -1  # High cards: -1
}

# Omega II System (Level 2) - More accurate, used by pros
OMEGA_II_VALUES: Dict[str, int] = {
    '2': 1, '3': 1, '4': 2, '5': 2, '6': 2,      # 2,3: +1; 4,5,6: +2
    '7': 1, '8': 0, '9': -1,                      # 7: +1; 8: 0; 9: -1
    '10': -2, 'J': -2, 'Q': -2, 'K': -2,         # Tens: -2
    'A': 0                                        # Aces: 0 (track separately)
}

# Wong Halves System (Level 3) - Most accurate, fractional values
# Using doubled values for easier mental math (divide by 2 at end)
WONG_HALVES_VALUES: Dict[str, float] = {
    '2': 0.5, '3': 1, '4': 1, '5': 1.5, '6': 1,  # Fractional values
    '7': 0.5, '8': 0, '9': -0.5,                  # 7: +0.5; 8: 0; 9: -0.5
    '10': -1, 'J': -1, 'Q': -1, 'K': -1, 'A': -1  # High cards: -1
}

# Wong Halves doubled for easier counting (divide by 2 for actual count)
WONG_HALVES_DOUBLED: Dict[str, int] = {
    '2': 1, '3': 2, '4': 2, '5': 3, '6': 2,
    '7': 1, '8': 0, '9': -1,
    '10': -2, 'J': -2, 'Q': -2, 'K': -2, 'A': -2
}

CountingSystem = Literal['hi_lo', 'omega_ii', 'wong_halves']


@dataclass
class CountState:
    """Current state of the count"""
    running_count: float
    true_count: float
    cards_seen: int
    decks_remaining: float
    ace_count: int  # For Omega II ace side-count
    ace_richness: float  # Aces over/under expected


class CardCounter:
    """
    Advanced card counting engine supporting multiple counting systems

    Usage:
        counter = CardCounter(system='hi_lo', num_decks=6)
        counter.add_card('A')
        counter.add_card('5')
        print(f"True Count: {counter.true_count}")
    """

    SYSTEMS = {
        'hi_lo': HI_LO_VALUES,
        'omega_ii': OMEGA_II_VALUES,
        'wong_halves': WONG_HALVES_VALUES
    }

    def __init__(self, system: CountingSystem = 'hi_lo', num_decks: int = 6):
        """
        Initialize card counter

        Args:
            system: Counting system to use ('hi_lo', 'omega_ii', 'wong_halves')
            num_decks: Number of decks in the shoe (typically 6 or 8)
        """
        self.system = system
        self.num_decks = num_decks
        self.values = self.SYSTEMS[system]

        # Initialize counts
        self.reset()

        cprint(f"Card Counter initialized: {system.upper()} system, {num_decks} decks", "cyan")

    def reset(self) -> None:
        """Reset counter for a new shoe"""
        self.running_count: float = 0
        self.cards_seen: int = 0
        self.ace_count: int = 0  # Track aces separately for Omega II
        self._cards_history: List[str] = []  # Track all cards seen

    def _normalize_card(self, card: str) -> str:
        """Normalize card representation (handle '10', 'T', lowercase, etc.)"""
        card = str(card).upper().strip()

        # Handle 10 variations
        if card in ['10', 'T', '0']:
            return '10'

        # Handle face cards
        if card in ['J', 'JACK']:
            return 'J'
        if card in ['Q', 'QUEEN']:
            return 'Q'
        if card in ['K', 'KING']:
            return 'K'
        if card in ['A', 'ACE', '1']:
            return 'A'

        # Numeric cards
        if card in ['2', '3', '4', '5', '6', '7', '8', '9']:
            return card

        raise ValueError(f"Invalid card: {card}")

    def add_card(self, card: str) -> float:
        """
        Add a card to the count

        Args:
            card: Card value (2-10, J, Q, K, A)

        Returns:
            The count value added for this card
        """
        card = self._normalize_card(card)
        value = self.values.get(card, 0)

        self.running_count += value
        self.cards_seen += 1
        self._cards_history.append(card)

        # Track aces separately for Omega II
        if card == 'A':
            self.ace_count += 1

        return value

    def add_cards(self, cards: List[str]) -> float:
        """
        Add multiple cards to the count

        Args:
            cards: List of card values

        Returns:
            Total count value added
        """
        total = 0
        for card in cards:
            total += self.add_card(card)
        return total

    @property
    def decks_remaining(self) -> float:
        """Estimate decks remaining in shoe"""
        cards_per_deck = 52
        total_cards = self.num_decks * cards_per_deck
        cards_remaining = total_cards - self.cards_seen
        decks = cards_remaining / cards_per_deck
        return max(decks, 0.5)  # Floor at 0.5 to avoid division issues

    @property
    def true_count(self) -> float:
        """
        Calculate true count: running count / decks remaining
        This normalizes the count for comparison across different shoe depths
        """
        return self.running_count / self.decks_remaining

    @property
    def ace_richness(self) -> float:
        """
        Calculate if shoe is ace-rich or ace-poor (for Omega II)
        Positive = more aces remaining than expected
        Negative = fewer aces remaining than expected
        """
        aces_per_deck = 4
        expected_aces_seen = (self.cards_seen / 52) * aces_per_deck * self.num_decks
        return expected_aces_seen - self.ace_count

    @property
    def penetration(self) -> float:
        """Calculate shoe penetration (0-1, how deep into shoe)"""
        total_cards = self.num_decks * 52
        return self.cards_seen / total_cards

    @property
    def state(self) -> CountState:
        """Get current count state as a dataclass"""
        return CountState(
            running_count=self.running_count,
            true_count=self.true_count,
            cards_seen=self.cards_seen,
            decks_remaining=self.decks_remaining,
            ace_count=self.ace_count,
            ace_richness=self.ace_richness
        )

    def get_count_display(self) -> str:
        """Get formatted count display for terminal/voice"""
        tc = self.true_count
        rc = self.running_count
        dr = self.decks_remaining

        tc_str = f"+{tc:.1f}" if tc >= 0 else f"{tc:.1f}"

        return f"RC: {rc:+.0f} | TC: {tc_str} | Decks: {dr:.1f}"

    def should_bet_big(self, threshold: float = 2.0) -> bool:
        """Check if true count warrants increased betting"""
        return self.true_count >= threshold

    def get_edge_estimate(self) -> float:
        """
        Estimate player edge based on true count
        Rule of thumb: each +1 TC = ~0.5% edge shift
        Base house edge with basic strategy: ~-0.5%
        """
        base_edge = -0.005  # 0.5% house edge
        count_adjustment = self.true_count * 0.005  # 0.5% per true count
        return base_edge + count_adjustment

    def switch_system(self, system: CountingSystem) -> None:
        """Switch to a different counting system (resets count)"""
        self.system = system
        self.values = self.SYSTEMS[system]
        self.reset()
        cprint(f"Switched to {system.upper()} system", "yellow")

    def get_system_info(self) -> Dict:
        """Get information about current counting system"""
        info = {
            'hi_lo': {
                'name': 'Hi-Lo',
                'level': 1,
                'difficulty': 'Easy',
                'accuracy': 'Good',
                'description': 'Simple +1/-1 system, great for beginners'
            },
            'omega_ii': {
                'name': 'Omega II',
                'level': 2,
                'difficulty': 'Medium',
                'accuracy': 'Very Good',
                'description': 'Multi-level system with ace side-count'
            },
            'wong_halves': {
                'name': 'Wong Halves',
                'level': 3,
                'difficulty': 'Hard',
                'accuracy': 'Excellent',
                'description': 'Fractional values for maximum accuracy'
            }
        }
        return info[self.system]

    def __repr__(self) -> str:
        return f"CardCounter(system={self.system}, RC={self.running_count}, TC={self.true_count:.2f})"


class MultiSystemCounter:
    """
    Run multiple counting systems simultaneously for comparison/training
    """

    def __init__(self, num_decks: int = 6):
        self.counters = {
            'hi_lo': CardCounter('hi_lo', num_decks),
            'omega_ii': CardCounter('omega_ii', num_decks),
            'wong_halves': CardCounter('wong_halves', num_decks)
        }
        self.num_decks = num_decks

    def add_card(self, card: str) -> Dict[str, float]:
        """Add card to all systems, return values added"""
        results = {}
        for name, counter in self.counters.items():
            results[name] = counter.add_card(card)
        return results

    def reset(self) -> None:
        """Reset all counters"""
        for counter in self.counters.values():
            counter.reset()

    def get_all_counts(self) -> Dict[str, CountState]:
        """Get state from all counting systems"""
        return {name: counter.state for name, counter in self.counters.items()}

    def display_comparison(self) -> None:
        """Display all counts side by side"""
        cprint("\n=== MULTI-SYSTEM COUNT COMPARISON ===", "cyan", attrs=['bold'])
        for name, counter in self.counters.items():
            info = counter.get_system_info()
            tc_color = 'green' if counter.true_count > 0 else 'red' if counter.true_count < 0 else 'white'
            cprint(f"{info['name']:12} | RC: {counter.running_count:+6.1f} | TC: {counter.true_count:+5.2f}", tc_color)
        print()


# Standalone test
if __name__ == "__main__":
    cprint("\n=== Card Counter Test ===\n", "cyan", attrs=['bold'])

    # Test Hi-Lo
    counter = CardCounter('hi_lo', num_decks=6)

    # Simulate some cards
    test_cards = ['A', '5', '10', '2', 'K', '6', '3', 'Q', '7', '4']

    cprint("Dealing cards:", "yellow")
    for card in test_cards:
        value = counter.add_card(card)
        print(f"  Card: {card:2} | Value: {value:+2} | {counter.get_count_display()}")

    print()
    cprint(f"Final True Count: {counter.true_count:+.2f}", "green" if counter.true_count > 0 else "red")
    cprint(f"Estimated Edge: {counter.get_edge_estimate()*100:+.2f}%", "cyan")
    cprint(f"Bet Big? {counter.should_bet_big()}", "yellow")

    # Test multi-system
    print()
    cprint("=== Multi-System Comparison ===", "magenta", attrs=['bold'])
    multi = MultiSystemCounter(num_decks=6)

    for card in test_cards:
        multi.add_card(card)

    multi.display_comparison()
