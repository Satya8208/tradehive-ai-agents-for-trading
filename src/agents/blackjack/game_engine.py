"""
Game Engine - Blackjack simulator for training and testing
Implements full blackjack rules with configurable options
Built with love by TradeHive
"""

import random
from typing import List, Optional, Tuple, Dict, Literal
from dataclasses import dataclass, field
from enum import Enum
from termcolor import cprint


class GameResult(Enum):
    """Possible outcomes of a blackjack hand"""
    WIN = "win"
    LOSE = "lose"
    PUSH = "push"
    BLACKJACK = "blackjack"
    SURRENDER = "surrender"
    BUST = "bust"


@dataclass
class GameRules:
    """Configurable blackjack rules"""
    num_decks: int = 6
    dealer_hits_soft_17: bool = True  # H17 (common) vs S17 (player-favorable)
    blackjack_pays: float = 1.5  # 3:2 standard, some casinos do 6:5
    double_after_split: bool = True
    resplit_aces: bool = False
    hit_split_aces: bool = False
    late_surrender: bool = True
    early_surrender: bool = False
    max_splits: int = 3  # Can split up to 4 hands total
    penetration: float = 0.75  # Cut card at 75% of shoe


@dataclass
class Hand:
    """Represents a player or dealer hand"""
    cards: List[str] = field(default_factory=list)
    bet: float = 0
    is_doubled: bool = False
    is_split: bool = False
    is_surrendered: bool = False
    from_split_aces: bool = False

    def add_card(self, card: str) -> None:
        """Add a card to the hand"""
        self.cards.append(card)

    @property
    def value(self) -> int:
        """Calculate hand value, treating aces optimally"""
        total = 0
        aces = 0

        for card in self.cards:
            if card in ['J', 'Q', 'K']:
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

        # Count without any ace adjustment
        total = 0
        aces = 0
        for card in self.cards:
            if card in ['J', 'Q', 'K']:
                total += 10
            elif card == 'A':
                aces += 1
                total += 11
            else:
                total += int(card)

        # If we can keep at least one ace as 11, it's soft
        while total > 21 and aces > 0:
            total -= 10
            aces -= 1

        return aces > 0 and total <= 21

    @property
    def is_bust(self) -> bool:
        """Check if hand has busted"""
        return self.value > 21

    @property
    def is_blackjack(self) -> bool:
        """Check if hand is a natural blackjack"""
        return len(self.cards) == 2 and self.value == 21 and not self.is_split

    @property
    def is_pair(self) -> bool:
        """Check if hand is a splittable pair"""
        if len(self.cards) != 2:
            return False

        def card_val(c):
            if c in ['J', 'Q', 'K', '10']:
                return 10
            elif c == 'A':
                return 11
            return int(c)

        return card_val(self.cards[0]) == card_val(self.cards[1])

    @property
    def pair_card(self) -> Optional[str]:
        """Get the pair card value"""
        if not self.is_pair:
            return None
        card = self.cards[0]
        if card in ['J', 'Q', 'K']:
            return '10'
        return card

    def can_double(self, rules: GameRules) -> bool:
        """Check if doubling is allowed"""
        if len(self.cards) != 2:
            return False
        if self.from_split_aces and not rules.hit_split_aces:
            return False
        if self.is_split and not rules.double_after_split:
            return False
        return True

    def can_split(self, rules: GameRules, num_splits: int = 0) -> bool:
        """Check if splitting is allowed"""
        if not self.is_pair:
            return False
        if num_splits >= rules.max_splits:
            return False
        if self.from_split_aces and not rules.resplit_aces:
            return False
        return True

    def __str__(self) -> str:
        return f"{self.cards} = {self.value}"


class Deck:
    """Represents a shoe of cards"""

    CARDS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']

    def __init__(self, num_decks: int = 6, penetration: float = 0.75):
        """
        Initialize shoe

        Args:
            num_decks: Number of decks in shoe
            penetration: Cut card position (0.75 = 75% into shoe)
        """
        self.num_decks = num_decks
        self.penetration = penetration
        self.shuffle()

    def shuffle(self) -> None:
        """Shuffle a fresh shoe"""
        self.cards = self.CARDS * 4 * self.num_decks
        random.shuffle(self.cards)
        self.cut_card = int(len(self.cards) * self.penetration)

    def deal(self) -> str:
        """Deal one card from the shoe"""
        if len(self.cards) == 0:
            self.shuffle()
        return self.cards.pop()

    def needs_shuffle(self) -> bool:
        """Check if cut card has been reached"""
        return len(self.cards) <= (self.num_decks * 52 - self.cut_card)

    @property
    def cards_remaining(self) -> int:
        """Number of cards remaining in shoe"""
        return len(self.cards)

    @property
    def decks_remaining(self) -> float:
        """Estimated decks remaining"""
        return len(self.cards) / 52


@dataclass
class GameState:
    """Current state of a blackjack round"""
    player_hands: List[Hand] = field(default_factory=list)
    dealer_hand: Hand = field(default_factory=Hand)
    dealer_upcard: str = ""
    dealer_hole: str = ""
    is_complete: bool = False
    results: List[Tuple[GameResult, float]] = field(default_factory=list)  # (result, payout)
    cards_dealt: List[str] = field(default_factory=list)  # All cards seen this round


class BlackjackSimulator:
    """
    Full blackjack game simulator

    Usage:
        sim = BlackjackSimulator()
        state = sim.new_round(bet=10)
        action, _ = strategy.get_action(state.player_hands[0], state.dealer_upcard)
        state = sim.player_action(0, action)
    """

    def __init__(self, rules: GameRules = None):
        """Initialize simulator with optional custom rules"""
        self.rules = rules or GameRules()
        self.deck = Deck(self.rules.num_decks, self.rules.penetration)
        self.state: Optional[GameState] = None
        self.stats = {
            'hands_played': 0,
            'hands_won': 0,
            'hands_lost': 0,
            'hands_pushed': 0,
            'blackjacks': 0,
            'busts': 0,
            'doubles_won': 0,
            'splits': 0,
            'surrenders': 0,
            'total_bet': 0,
            'total_pnl': 0
        }

    def new_round(self, bet: float = 10) -> GameState:
        """
        Start a new round of blackjack

        Args:
            bet: Initial bet amount

        Returns:
            Initial game state
        """
        # Check if shuffle needed
        if self.deck.needs_shuffle():
            self.deck.shuffle()

        # Create new state
        self.state = GameState()
        self.state.player_hands = [Hand(bet=bet)]

        # Deal initial cards
        p1 = self.deck.deal()
        d1 = self.deck.deal()
        p2 = self.deck.deal()
        d2 = self.deck.deal()

        self.state.player_hands[0].add_card(p1)
        self.state.player_hands[0].add_card(p2)
        self.state.dealer_hand.add_card(d1)
        self.state.dealer_hand.add_card(d2)

        self.state.dealer_upcard = d1
        self.state.dealer_hole = d2
        self.state.cards_dealt = [p1, d1, p2]  # Hole card not visible yet

        # Check for dealer blackjack
        if self.state.dealer_hand.is_blackjack:
            # Check player blackjack for push
            if self.state.player_hands[0].is_blackjack:
                self.state.results = [(GameResult.PUSH, 0)]
            else:
                self.state.results = [(GameResult.LOSE, -bet)]
            self.state.is_complete = True
            self.state.cards_dealt.append(d2)  # Reveal hole card

        # Check for player blackjack
        elif self.state.player_hands[0].is_blackjack:
            payout = bet * self.rules.blackjack_pays
            self.state.results = [(GameResult.BLACKJACK, payout)]
            self.state.is_complete = True
            self.state.cards_dealt.append(d2)
            self.stats['blackjacks'] += 1

        return self.state

    def player_action(self, hand_index: int, action: str) -> GameState:
        """
        Execute a player action on a specific hand

        Args:
            hand_index: Index of hand to act on (for splits)
            action: H=Hit, S=Stand, D=Double, P=Split, R=Surrender

        Returns:
            Updated game state
        """
        if self.state.is_complete:
            return self.state

        hand = self.state.player_hands[hand_index]
        action = action.upper()

        if action == 'H':  # Hit
            card = self.deck.deal()
            hand.add_card(card)
            self.state.cards_dealt.append(card)

            if hand.is_bust:
                # Move to next hand or finish
                pass

        elif action == 'S':  # Stand
            pass  # Move to next hand or dealer

        elif action == 'D':  # Double
            if hand.can_double(self.rules):
                hand.is_doubled = True
                hand.bet *= 2
                card = self.deck.deal()
                hand.add_card(card)
                self.state.cards_dealt.append(card)

        elif action == 'P':  # Split
            if hand.can_split(self.rules, self._count_splits()):
                # Create new hand from split
                card = hand.cards.pop()
                new_hand = Hand(
                    cards=[card],
                    bet=hand.bet,
                    is_split=True,
                    from_split_aces=(card == 'A')
                )
                hand.is_split = True
                hand.from_split_aces = (hand.cards[0] == 'A')

                # Deal new cards to each hand
                card1 = self.deck.deal()
                card2 = self.deck.deal()
                hand.add_card(card1)
                new_hand.add_card(card2)

                self.state.cards_dealt.extend([card1, card2])
                self.state.player_hands.insert(hand_index + 1, new_hand)
                self.stats['splits'] += 1

        elif action == 'R':  # Surrender
            if self.rules.late_surrender and len(hand.cards) == 2:
                hand.is_surrendered = True
                self.stats['surrenders'] += 1

        return self.state

    def _count_splits(self) -> int:
        """Count how many times player has split"""
        return sum(1 for h in self.state.player_hands if h.is_split)

    def is_hand_complete(self, hand_index: int) -> bool:
        """Check if a specific hand is done playing"""
        hand = self.state.player_hands[hand_index]

        if hand.is_surrendered:
            return True
        if hand.is_bust:
            return True
        if hand.is_doubled:
            return True
        if hand.from_split_aces and not self.rules.hit_split_aces:
            return True

        return False

    def play_dealer(self) -> GameState:
        """
        Play out dealer's hand according to rules

        Returns:
            Final game state with results
        """
        if self.state.is_complete:
            return self.state

        # Reveal hole card
        self.state.cards_dealt.append(self.state.dealer_hole)

        # Check if all player hands busted or surrendered
        all_done = all(h.is_bust or h.is_surrendered for h in self.state.player_hands)

        if not all_done:
            # Dealer must hit to 17+ (or soft 17 based on rules)
            while True:
                value = self.state.dealer_hand.value
                is_soft = self.state.dealer_hand.is_soft

                if value > 17:
                    break
                if value == 17:
                    if not is_soft or not self.rules.dealer_hits_soft_17:
                        break

                card = self.deck.deal()
                self.state.dealer_hand.add_card(card)
                self.state.cards_dealt.append(card)

        # Calculate results for each hand
        self._calculate_results()
        self.state.is_complete = True

        return self.state

    def _calculate_results(self) -> None:
        """Calculate results for all player hands"""
        dealer_value = self.state.dealer_hand.value
        dealer_bust = self.state.dealer_hand.is_bust

        for hand in self.state.player_hands:
            if hand.is_surrendered:
                result = GameResult.SURRENDER
                payout = -hand.bet / 2
            elif hand.is_bust:
                result = GameResult.BUST
                payout = -hand.bet
                self.stats['busts'] += 1
            elif dealer_bust:
                result = GameResult.WIN
                payout = hand.bet
                if hand.is_doubled:
                    self.stats['doubles_won'] += 1
            elif hand.value > dealer_value:
                result = GameResult.WIN
                payout = hand.bet
                if hand.is_doubled:
                    self.stats['doubles_won'] += 1
            elif hand.value < dealer_value:
                result = GameResult.LOSE
                payout = -hand.bet
            else:
                result = GameResult.PUSH
                payout = 0

            self.state.results.append((result, payout))

            # Update stats
            self.stats['hands_played'] += 1
            self.stats['total_bet'] += hand.bet
            self.stats['total_pnl'] += payout

            if result in [GameResult.WIN, GameResult.BLACKJACK]:
                self.stats['hands_won'] += 1
            elif result in [GameResult.LOSE, GameResult.BUST]:
                self.stats['hands_lost'] += 1
            else:
                self.stats['hands_pushed'] += 1

    def get_all_cards_dealt(self) -> List[str]:
        """Get all cards dealt this round (for card counting)"""
        return self.state.cards_dealt if self.state else []

    @property
    def shoe_needs_shuffle(self) -> bool:
        """Check if shoe needs reshuffling"""
        return self.deck.needs_shuffle()

    @property
    def decks_remaining(self) -> float:
        """Get estimated decks remaining"""
        return self.deck.decks_remaining

    def get_stats(self) -> Dict:
        """Get current session statistics"""
        hands = self.stats['hands_played']
        if hands == 0:
            return self.stats

        return {
            **self.stats,
            'win_rate': self.stats['hands_won'] / hands * 100,
            'push_rate': self.stats['hands_pushed'] / hands * 100,
            'bust_rate': self.stats['busts'] / hands * 100,
            'roi': self.stats['total_pnl'] / self.stats['total_bet'] * 100 if self.stats['total_bet'] > 0 else 0
        }

    def display_state(self) -> None:
        """Display current game state in terminal"""
        if not self.state:
            cprint("No active game", "yellow")
            return

        cprint("\n" + "=" * 50, "cyan")
        cprint("BLACKJACK", "cyan", attrs=['bold'])
        cprint("=" * 50, "cyan")

        # Dealer
        if self.state.is_complete:
            dealer_display = f"{self.state.dealer_hand.cards} = {self.state.dealer_hand.value}"
        else:
            dealer_display = f"[{self.state.dealer_upcard}, ?]"

        cprint(f"Dealer: {dealer_display}", "white")

        # Player hands
        for i, hand in enumerate(self.state.player_hands):
            status = ""
            if hand.is_bust:
                status = " (BUST)"
            elif hand.is_blackjack:
                status = " (BLACKJACK!)"
            elif hand.is_doubled:
                status = " (DOUBLED)"
            elif hand.is_surrendered:
                status = " (SURRENDERED)"

            hand_color = 'red' if hand.is_bust else 'green' if hand.is_blackjack else 'white'
            cprint(f"Hand {i+1}: {hand.cards} = {hand.value}{status} (${hand.bet})", hand_color)

        # Results
        if self.state.is_complete and self.state.results:
            cprint("-" * 50, "cyan")
            total_pnl = 0
            for i, (result, payout) in enumerate(self.state.results):
                pnl_color = 'green' if payout > 0 else 'red' if payout < 0 else 'yellow'
                cprint(f"Hand {i+1}: {result.value.upper()} ({payout:+.2f})", pnl_color)
                total_pnl += payout

            cprint(f"Total: {total_pnl:+.2f}", 'green' if total_pnl > 0 else 'red' if total_pnl < 0 else 'yellow', attrs=['bold'])

        cprint("=" * 50 + "\n", "cyan")


# Standalone test
if __name__ == "__main__":
    from strategy_engine import StrategyEngine, Hand as StratHand

    cprint("\n=== Blackjack Simulator Test ===\n", "cyan", attrs=['bold'])

    sim = BlackjackSimulator()
    strategy = StrategyEngine()

    # Play 10 hands
    for round_num in range(10):
        cprint(f"\n--- Round {round_num + 1} ---", "yellow")

        # Start new round
        state = sim.new_round(bet=10)

        if not state.is_complete:
            # Play each hand
            hand_idx = 0
            while hand_idx < len(state.player_hands):
                hand = state.player_hands[hand_idx]

                # Skip if hand is complete
                if sim.is_hand_complete(hand_idx):
                    hand_idx += 1
                    continue

                # Get strategy action
                strat_hand = StratHand(cards=hand.cards)
                action, source = strategy.get_action(
                    strat_hand,
                    state.dealer_upcard,
                    can_double=hand.can_double(sim.rules),
                    can_split=hand.can_split(sim.rules, sim._count_splits())
                )

                cprint(f"  Hand {hand_idx+1}: {hand.cards} vs {state.dealer_upcard} -> {action} ({source})", "white")

                # Execute action
                state = sim.player_action(hand_idx, action)

                # Check if we need to continue with this hand
                if action not in ['S', 'D', 'R'] and not sim.is_hand_complete(hand_idx):
                    continue  # Stay on this hand

                hand_idx += 1

            # Play dealer
            state = sim.play_dealer()

        sim.display_state()

    # Final stats
    stats = sim.get_stats()
    cprint("\n=== Session Statistics ===", "magenta", attrs=['bold'])
    cprint(f"Hands: {stats['hands_played']} | Wins: {stats['hands_won']} | Losses: {stats['hands_lost']} | Pushes: {stats['hands_pushed']}", "white")
    cprint(f"Win Rate: {stats.get('win_rate', 0):.1f}% | ROI: {stats.get('roi', 0):+.2f}%", "cyan")
    cprint(f"Blackjacks: {stats['blackjacks']} | Busts: {stats['busts']} | Splits: {stats['splits']}", "white")
    cprint(f"Total P&L: ${stats['total_pnl']:+.2f}", 'green' if stats['total_pnl'] > 0 else 'red')
