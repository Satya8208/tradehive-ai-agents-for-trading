"""
Strategy Engine - Perfect basic strategy with AI advisor for edge cases
Implements mathematically optimal blackjack play
Built with love by TradeHive
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Literal
from dataclasses import dataclass
from termcolor import cprint

# Add project root for imports
project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

Action = Literal['H', 'S', 'D', 'P', 'R', 'Ds']
# H = Hit, S = Stand, D = Double, P = Split, R = Surrender, Ds = Double if allowed else Stand


@dataclass
class Hand:
    """Represents a blackjack hand"""
    cards: List[str]

    @property
    def values(self) -> List[int]:
        """Get numeric values of cards"""
        vals = []
        for card in self.cards:
            if card in ['J', 'Q', 'K']:
                vals.append(10)
            elif card == 'A':
                vals.append(11)  # Will handle soft later
            else:
                vals.append(int(card))
        return vals

    @property
    def total(self) -> int:
        """Calculate hand total, handling aces optimally"""
        total = 0
        aces = 0
        for card in self.cards:
            if card in ['J', 'Q', 'K', '10']:
                total += 10
            elif card == 'A':
                aces += 1
                total += 11
            else:
                total += int(card)

        # Convert aces from 11 to 1 as needed
        while total > 21 and aces > 0:
            total -= 10
            aces -= 1

        return total

    @property
    def is_soft(self) -> bool:
        """Check if hand is soft (ace counted as 11)"""
        if 'A' not in self.cards:
            return False

        # Calculate with ace as 11
        total = 0
        for card in self.cards:
            if card in ['J', 'Q', 'K', '10']:
                total += 10
            elif card == 'A':
                total += 11
            else:
                total += int(card)

        # If total <= 21 with ace as 11, it's soft
        aces = self.cards.count('A')
        return total <= 21 or (total - 10 * (aces - 1)) <= 21 and aces > 0

    @property
    def is_pair(self) -> bool:
        """Check if hand is a splittable pair"""
        if len(self.cards) != 2:
            return False

        def card_value(c):
            if c in ['J', 'Q', 'K', '10']:
                return 10
            elif c == 'A':
                return 11
            else:
                return int(c)

        return card_value(self.cards[0]) == card_value(self.cards[1])

    @property
    def pair_card(self) -> Optional[str]:
        """Get the pair card if this is a pair"""
        if not self.is_pair:
            return None
        return self.cards[0]

    @property
    def is_blackjack(self) -> bool:
        """Check if hand is a natural blackjack"""
        return len(self.cards) == 2 and self.total == 21


# ===== BASIC STRATEGY TABLES =====
# Legend: H=Hit, S=Stand, D=Double, P=Split, R=Surrender, Ds=Double/Stand

# Hard totals (no ace, or ace counted as 1)
# Rows: player total (5-17+), Columns: dealer upcard (2-A)
HARD_STRATEGY: Dict[int, Dict[str, Action]] = {
    5:  {'2': 'H', '3': 'H', '4': 'H', '5': 'H', '6': 'H', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},
    6:  {'2': 'H', '3': 'H', '4': 'H', '5': 'H', '6': 'H', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},
    7:  {'2': 'H', '3': 'H', '4': 'H', '5': 'H', '6': 'H', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},
    8:  {'2': 'H', '3': 'H', '4': 'H', '5': 'H', '6': 'H', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},
    9:  {'2': 'H', '3': 'D', '4': 'D', '5': 'D', '6': 'D', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},
    10: {'2': 'D', '3': 'D', '4': 'D', '5': 'D', '6': 'D', '7': 'D', '8': 'D', '9': 'D', '10': 'H', 'A': 'H'},
    11: {'2': 'D', '3': 'D', '4': 'D', '5': 'D', '6': 'D', '7': 'D', '8': 'D', '9': 'D', '10': 'D', 'A': 'D'},
    12: {'2': 'H', '3': 'H', '4': 'S', '5': 'S', '6': 'S', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},
    13: {'2': 'S', '3': 'S', '4': 'S', '5': 'S', '6': 'S', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},
    14: {'2': 'S', '3': 'S', '4': 'S', '5': 'S', '6': 'S', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},
    15: {'2': 'S', '3': 'S', '4': 'S', '5': 'S', '6': 'S', '7': 'H', '8': 'H', '9': 'H', '10': 'R', 'A': 'R'},
    16: {'2': 'S', '3': 'S', '4': 'S', '5': 'S', '6': 'S', '7': 'H', '8': 'H', '9': 'R', '10': 'R', 'A': 'R'},
    17: {'2': 'S', '3': 'S', '4': 'S', '5': 'S', '6': 'S', '7': 'S', '8': 'S', '9': 'S', '10': 'S', 'A': 'S'},
    18: {'2': 'S', '3': 'S', '4': 'S', '5': 'S', '6': 'S', '7': 'S', '8': 'S', '9': 'S', '10': 'S', 'A': 'S'},
    19: {'2': 'S', '3': 'S', '4': 'S', '5': 'S', '6': 'S', '7': 'S', '8': 'S', '9': 'S', '10': 'S', 'A': 'S'},
    20: {'2': 'S', '3': 'S', '4': 'S', '5': 'S', '6': 'S', '7': 'S', '8': 'S', '9': 'S', '10': 'S', 'A': 'S'},
    21: {'2': 'S', '3': 'S', '4': 'S', '5': 'S', '6': 'S', '7': 'S', '8': 'S', '9': 'S', '10': 'S', 'A': 'S'},
}

# Soft totals (ace counted as 11)
# Rows: soft total (13-21), Columns: dealer upcard (2-A)
SOFT_STRATEGY: Dict[int, Dict[str, Action]] = {
    13: {'2': 'H', '3': 'H', '4': 'H', '5': 'D', '6': 'D', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},  # A,2
    14: {'2': 'H', '3': 'H', '4': 'H', '5': 'D', '6': 'D', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},  # A,3
    15: {'2': 'H', '3': 'H', '4': 'D', '5': 'D', '6': 'D', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},  # A,4
    16: {'2': 'H', '3': 'H', '4': 'D', '5': 'D', '6': 'D', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},  # A,5
    17: {'2': 'H', '3': 'D', '4': 'D', '5': 'D', '6': 'D', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},  # A,6
    18: {'2': 'Ds', '3': 'Ds', '4': 'Ds', '5': 'Ds', '6': 'Ds', '7': 'S', '8': 'S', '9': 'H', '10': 'H', 'A': 'H'},  # A,7
    19: {'2': 'S', '3': 'S', '4': 'S', '5': 'S', '6': 'Ds', '7': 'S', '8': 'S', '9': 'S', '10': 'S', 'A': 'S'},  # A,8
    20: {'2': 'S', '3': 'S', '4': 'S', '5': 'S', '6': 'S', '7': 'S', '8': 'S', '9': 'S', '10': 'S', 'A': 'S'},  # A,9
    21: {'2': 'S', '3': 'S', '4': 'S', '5': 'S', '6': 'S', '7': 'S', '8': 'S', '9': 'S', '10': 'S', 'A': 'S'},  # A,10/BJ
}

# Pairs strategy
# Rows: pair card (2-A), Columns: dealer upcard (2-A)
PAIRS_STRATEGY: Dict[str, Dict[str, Action]] = {
    '2':  {'2': 'P', '3': 'P', '4': 'P', '5': 'P', '6': 'P', '7': 'P', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},
    '3':  {'2': 'P', '3': 'P', '4': 'P', '5': 'P', '6': 'P', '7': 'P', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},
    '4':  {'2': 'H', '3': 'H', '4': 'H', '5': 'P', '6': 'P', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},
    '5':  {'2': 'D', '3': 'D', '4': 'D', '5': 'D', '6': 'D', '7': 'D', '8': 'D', '9': 'D', '10': 'H', 'A': 'H'},  # Never split 5s
    '6':  {'2': 'P', '3': 'P', '4': 'P', '5': 'P', '6': 'P', '7': 'H', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},
    '7':  {'2': 'P', '3': 'P', '4': 'P', '5': 'P', '6': 'P', '7': 'P', '8': 'H', '9': 'H', '10': 'H', 'A': 'H'},
    '8':  {'2': 'P', '3': 'P', '4': 'P', '5': 'P', '6': 'P', '7': 'P', '8': 'P', '9': 'P', '10': 'P', 'A': 'P'},  # Always split 8s
    '9':  {'2': 'P', '3': 'P', '4': 'P', '5': 'P', '6': 'P', '7': 'S', '8': 'P', '9': 'P', '10': 'S', 'A': 'S'},
    '10': {'2': 'S', '3': 'S', '4': 'S', '5': 'S', '6': 'S', '7': 'S', '8': 'S', '9': 'S', '10': 'S', 'A': 'S'},  # Never split 10s
    'A':  {'2': 'P', '3': 'P', '4': 'P', '5': 'P', '6': 'P', '7': 'P', '8': 'P', '9': 'P', '10': 'P', 'A': 'P'},  # Always split As
}

# Illustrious 18 - Count-based deviations from basic strategy
# Format: (player_total, dealer_upcard, is_soft, is_pair): (deviation_action, true_count_threshold)
ILLUSTRIOUS_18: Dict[Tuple, Tuple[Action, float]] = {
    # Insurance (take at TC >= 3)
    ('insurance', 'A', False, False): ('Y', 3),  # Take insurance at TC >= 3

    # Stand instead of hit
    (16, '10', False, False): ('S', 0),   # Stand 16 vs 10 at TC >= 0
    (15, '10', False, False): ('S', 4),   # Stand 15 vs 10 at TC >= 4
    (12, '2', False, False): ('S', 3),    # Stand 12 vs 2 at TC >= 3
    (12, '3', False, False): ('S', 2),    # Stand 12 vs 3 at TC >= 2
    (12, '4', False, False): ('S', 0),    # Stand 12 vs 4 at TC >= 0 (normally stand anyway)
    (13, '2', False, False): ('S', -1),   # Stand 13 vs 2 at TC >= -1
    (13, '3', False, False): ('S', -2),   # Stand 13 vs 3 at TC >= -2

    # Hit instead of stand
    (12, '5', False, False): ('H', -2),   # Hit 12 vs 5 at TC <= -2
    (12, '6', False, False): ('H', -1),   # Hit 12 vs 6 at TC <= -1

    # Double instead of hit
    (10, '10', False, False): ('D', 4),   # Double 10 vs 10 at TC >= 4
    (10, 'A', False, False): ('D', 4),    # Double 10 vs A at TC >= 4
    (9, '2', False, False): ('D', 1),     # Double 9 vs 2 at TC >= 1
    (9, '7', False, False): ('D', 4),     # Double 9 vs 7 at TC >= 4
    (11, 'A', False, False): ('D', 1),    # Double 11 vs A at TC >= 1 (most rules)

    # Split deviations
    ('10', '5', False, True): ('P', 5),   # Split 10s vs 5 at TC >= 5
    ('10', '6', False, True): ('P', 4),   # Split 10s vs 6 at TC >= 4
    
    # Fab 4 - Additional surrender deviations (HIGH VALUE!)
    (14, '10', False, False): ('R', 3),   # Surrender 14 vs 10 at TC >= 3
    (14, 'A', False, False): ('R', 3),    # Surrender 14 vs A at TC >= 3
    (15, '9', False, False): ('R', 2),    # Surrender 15 vs 9 at TC >= 2
}


class BasicStrategy:
    """
    Perfect basic strategy engine
    Returns mathematically optimal play for any hand
    """

    def __init__(self, system: str = 'hi_lo'):
        self.hard = HARD_STRATEGY
        self.soft = SOFT_STRATEGY
        self.pairs = PAIRS_STRATEGY
        self.system = system  # Track which counting system we're using

    def _normalize_dealer(self, dealer_upcard: str) -> str:
        """Normalize dealer upcard"""
        card = str(dealer_upcard).upper()
        if card in ['J', 'Q', 'K', '10', 'T']:
            return '10'
        if card in ['1', 'ACE']:
            return 'A'
        return card

    def _normalize_pair_card(self, card: str) -> str:
        """Normalize pair card for lookup"""
        card = str(card).upper()
        if card in ['J', 'Q', 'K', 'T']:
            return '10'
        if card in ['1', 'ACE']:
            return 'A'
        return card

    def get_action(
        self,
        hand: Hand,
        dealer_upcard: str,
        can_double: bool = True,
        can_split: bool = True,
        can_surrender: bool = True
    ) -> Action:
        """
        Get optimal action for a hand

        Args:
            hand: Player's hand
            dealer_upcard: Dealer's visible card
            can_double: Whether doubling is allowed
            can_split: Whether splitting is allowed
            can_surrender: Whether surrender is allowed

        Returns:
            Optimal action: H, S, D, P, or R
        """
        dealer = self._normalize_dealer(dealer_upcard)

        # Check for blackjack
        if hand.is_blackjack:
            return 'S'

        # Check pairs first
        if hand.is_pair and can_split:
            pair_card = self._normalize_pair_card(hand.pair_card)
            action = self.pairs.get(pair_card, {}).get(dealer, 'H')
            if action == 'P':
                return 'P'
            # If not splitting, continue to check other strategies

        # Check soft hands
        if hand.is_soft and hand.total <= 21:
            soft_total = hand.total
            if soft_total in self.soft:
                action = self.soft[soft_total].get(dealer, 'H')
                return self._adjust_action(action, can_double, can_surrender)

        # Hard hands
        total = hand.total
        if total < 5:
            total = 5  # Treat very low as 5
        if total > 21:
            return 'S'  # Bust, shouldn't happen
        if total > 17:
            total = 17  # Cap at 17+ (always stand)

        action = self.hard.get(total, {}).get(dealer, 'H')
        return self._adjust_action(action, can_double, can_surrender)

    def _adjust_action(self, action: Action, can_double: bool, can_surrender: bool) -> Action:
        """Adjust action based on what's allowed"""
        # Handle double/stand (Ds)
        if action == 'Ds':
            return 'D' if can_double else 'S'

        # Handle double when not allowed
        if action == 'D' and not can_double:
            return 'H'

        # Handle surrender when not allowed
        if action == 'R' and not can_surrender:
            return 'H'

        return action

    def get_action_description(self, action: Action) -> str:
        """Get human-readable action description"""
        descriptions = {
            'H': 'HIT',
            'S': 'STAND',
            'D': 'DOUBLE DOWN',
            'P': 'SPLIT',
            'R': 'SURRENDER'
        }
        return descriptions.get(action, action)


class StrategyEngine:
    """
    Full strategy engine with basic strategy + AI advisor for edge cases
    """

    def __init__(self, ai_model=None):
        """
        Initialize strategy engine

        Args:
            ai_model: Optional AI model from ModelFactory for edge case consultation
        """
        self.basic = BasicStrategy()
        self.ai_model = ai_model
        self.illustrious_18 = ILLUSTRIOUS_18

    def should_consult_ai(self, hand: Hand, dealer_upcard: str, true_count: float) -> bool:
        """Determine if AI consultation is warranted for edge cases"""
        # High/low count situations
        if abs(true_count) > 4:
            return True

        # Many cards in hand (unusual situation)
        if len(hand.cards) > 4:
            return True

        # Close decisions with significant count
        close_hands = [(15, '10'), (16, '9'), (16, '10'), (12, '4')]
        total = hand.total
        dealer = str(dealer_upcard).upper()
        if dealer in ['J', 'Q', 'K']:
            dealer = '10'

        if (total, dealer) in close_hands and abs(true_count) > 2:
            return True

        return False

    def get_deviation(self, hand: Hand, dealer_upcard: str, true_count: float) -> Optional[Action]:
        """
        Check if count-based deviation from basic strategy is warranted

        Returns:
            Deviation action if applicable, None otherwise
        """
        total = hand.total
        dealer = str(dealer_upcard).upper()
        if dealer in ['J', 'Q', 'K']:
            dealer = '10'

        is_pair = hand.is_pair

        # Check Illustrious 18
        key = (total, dealer, hand.is_soft, is_pair)

        # Also check pair-specific key
        if is_pair:
            pair_key = (hand.pair_card, dealer, False, True)
            if pair_key in self.illustrious_18:
                action, threshold = self.illustrious_18[pair_key]
                if true_count >= threshold:
                    return action

        if key in self.illustrious_18:
            action, threshold = self.illustrious_18[key]
            # For hit deviations (negative threshold), check if count is LOW enough
            if threshold < 0:
                if true_count <= threshold:
                    return action
            else:
                if true_count >= threshold:
                    return action

        return None

    def get_action(
        self,
        hand: Hand,
        dealer_upcard: str,
        true_count: float = 0,
        can_double: bool = True,
        can_split: bool = True,
        can_surrender: bool = True,
        use_deviations: bool = True
    ) -> Tuple[Action, str]:
        """
        Get optimal action considering count-based deviations

        Returns:
            Tuple of (action, source) where source is 'basic', 'deviation', or 'ai'
        """
        # First, get basic strategy action
        basic_action = self.basic.get_action(hand, dealer_upcard, can_double, can_split, can_surrender)

        # Check for deviations if using card counting
        if use_deviations and true_count != 0:
            deviation = self.get_deviation(hand, dealer_upcard, true_count)
            if deviation:
                # Verify the deviation is allowed
                if deviation == 'D' and not can_double:
                    deviation = 'H'
                elif deviation == 'P' and not can_split:
                    deviation = None
                elif deviation == 'R' and not can_surrender:
                    deviation = 'H'

                if deviation and deviation != basic_action:
                    return (deviation, 'deviation')

        # Check if AI consultation would help
        if self.ai_model and self.should_consult_ai(hand, dealer_upcard, true_count):
            ai_action = self._consult_ai(hand, dealer_upcard, true_count, basic_action)
            if ai_action and ai_action != basic_action:
                return (ai_action, 'ai')

        return (basic_action, 'basic')

    def _consult_ai(self, hand: Hand, dealer_upcard: str, true_count: float, basic_action: Action) -> Optional[Action]:
        """Consult AI for edge case decisions"""
        if not self.ai_model:
            return None

        prompt = f"""You are an expert blackjack player and card counter.

Current situation:
- Player hand: {hand.cards} (Total: {hand.total}, {'Soft' if hand.is_soft else 'Hard'})
- Dealer upcard: {dealer_upcard}
- True count: {true_count:+.1f}
- Basic strategy says: {self.basic.get_action_description(basic_action)}

Given the true count of {true_count:+.1f}, should we deviate from basic strategy?
Consider the Illustrious 18 deviations and any edge cases.

Respond with ONLY one of: HIT, STAND, DOUBLE, SPLIT, SURRENDER
If basic strategy is correct, repeat that action."""

        try:
            response = self.ai_model.generate_response(
                system_prompt="You are an expert blackjack strategist. Give only the action, no explanation.",
                user_content=prompt,
                temperature=0.1,
                max_tokens=20
            )

            if response:
                action_map = {
                    'HIT': 'H', 'STAND': 'S', 'DOUBLE': 'D',
                    'SPLIT': 'P', 'SURRENDER': 'R'
                }
                response_text = response.content.strip().upper()
                for word, code in action_map.items():
                    if word in response_text:
                        return code
        except Exception as e:
            cprint(f"AI consultation error: {e}", "red")

        return None

    def should_take_insurance(self, true_count: float, system: str = 'hi_lo') -> bool:
        """
        Determine if insurance should be taken based on count and system
        Different counting systems have different insurance thresholds:
        - Hi-Lo: TC ≥ 3
        - Omega II: TC ≥ 2 (more accurate system)
        - Wong Halves: TC ≥ 1.5 (most accurate)
        """
        SYSTEM_INSURANCE = {
            'hi_lo': 3.0,
            'omega_ii': 2.0,
            'wong_halves': 1.5
        }
        threshold = SYSTEM_INSURANCE.get(system, 3.0)
        return true_count >= threshold


# Standalone test
if __name__ == "__main__":
    cprint("\n=== Strategy Engine Test ===\n", "cyan", attrs=['bold'])

    engine = StrategyEngine()

    # Test cases
    test_cases = [
        (Hand(['10', '6']), '10', 0, "Hard 16 vs 10"),
        (Hand(['10', '6']), '10', 2, "Hard 16 vs 10 (TC +2)"),
        (Hand(['A', '7']), '9', 0, "Soft 18 vs 9"),
        (Hand(['8', '8']), '10', 0, "Pair 8s vs 10"),
        (Hand(['A', 'A']), '6', 0, "Pair As vs 6"),
        (Hand(['5', '5']), '10', 0, "Pair 5s vs 10 (never split)"),
        (Hand(['10', '2']), '3', 3, "Hard 12 vs 3 (TC +3)"),
    ]

    for hand, dealer, tc, description in test_cases:
        action, source = engine.get_action(hand, dealer, true_count=tc)
        action_desc = engine.basic.get_action_description(action)
        source_color = 'green' if source == 'basic' else 'yellow' if source == 'deviation' else 'magenta'

        print(f"{description}")
        cprint(f"  Action: {action_desc} (from {source})", source_color)
        print()
