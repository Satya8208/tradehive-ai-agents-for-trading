"""
Blackjack God Agent - Elite autonomous blackjack player with advanced card counting
Main orchestrator for simulation, advisor, and autonomous modes
Built with love by TradeHive
"""

import sys
import os
import argparse
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Literal
from termcolor import cprint

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

# Local imports
from .card_counter import CardCounter
from .strategy_engine import StrategyEngine, Hand as StratHand
from .game_engine import BlackjackSimulator, GameRules, Hand, GameResult
from .betting_manager import BettingManager, BettingConfig
from .voice_announcer import VoiceAnnouncer
from .dashboard import Dashboard, GameDisplay

# Try to import ModelFactory for AI advisor
try:
    from src.models.model_factory import model_factory
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
    cprint("ModelFactory not available. AI advisor disabled.", "yellow")

# Configuration
MODE = os.getenv('BLACKJACK_MODE', 'simulation')  # simulation, advisor, auto
COUNTING_SYSTEM = os.getenv('BLACKJACK_COUNTING_SYSTEM', 'hi_lo')
BETTING_METHOD = os.getenv('BLACKJACK_BETTING_METHOD', 'spread')
NUM_DECKS = int(os.getenv('BLACKJACK_NUM_DECKS', '6'))
VOICE_ENABLED = os.getenv('BLACKJACK_VOICE', 'true').lower() == 'true'
AI_MODEL = 'claude-sonnet-4-6'  # Claude Sonnet 4.6 - Latest

AgentMode = Literal['simulation', 'advisor', 'auto', 'training']


class BlackjackAgent:
    """
    Blackjack God Agent - Elite autonomous blackjack player

    Modes:
    - simulation: Play against internal simulator (for testing/training)
    - advisor: Manual input, agent advises optimal plays
    - auto: Browser automation for real online play
    - training: Practice drills for basic strategy and counting
    """

    def __init__(
        self,
        mode: AgentMode = 'simulation',
        counting_system: str = 'hi_lo',
        betting_method: str = 'spread',
        voice_enabled: bool = True,
        dashboard_enabled: bool = True,
        num_decks: int = 6,
        starting_bankroll: float = 1000
    ):
        """
        Initialize Blackjack God Agent

        Args:
            mode: Operating mode (simulation, advisor, auto, training)
            counting_system: Card counting system (hi_lo, omega_ii, wong_halves)
            betting_method: Betting method (kelly, spread, flat)
            voice_enabled: Enable voice announcements
            dashboard_enabled: Enable dashboard display
            num_decks: Number of decks in shoe
            starting_bankroll: Starting bankroll amount
        """
        self.mode = mode
        self.num_decks = num_decks

        # Data directory
        self.data_dir = Path(project_root) / "src" / "data" / "blackjack_agent"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize components
        cprint("\nInitializing Blackjack God Agent...", "cyan", attrs=['bold'])

        # Card counter
        self.counter = CardCounter(system=counting_system, num_decks=num_decks)

        # Strategy engine with optional AI
        ai_model = None
        if AI_AVAILABLE:
            try:
                ai_model = model_factory.get_model('claude', AI_MODEL)
                cprint(f"  AI Advisor: {AI_MODEL}", "green")
            except:
                cprint("  AI Advisor: unavailable", "yellow")

        self.strategy = StrategyEngine(ai_model=ai_model)

        # Betting manager
        betting_config = BettingConfig(
            min_bet=10,
            max_bet=200,
            starting_bankroll=starting_bankroll,
            method=betting_method
        )
        self.betting = BettingManager(betting_config, self.data_dir)

        # Voice announcer
        self.voice = VoiceAnnouncer(enabled=voice_enabled)

        # Dashboard
        self.dashboard = Dashboard(clear_screen=dashboard_enabled)
        self.dashboard_enabled = dashboard_enabled

        # Simulator (for simulation mode)
        rules = GameRules(num_decks=num_decks)
        self.simulator = BlackjackSimulator(rules)

        # Session tracking
        self.session_start = datetime.now()
        self.hand_number = 0
        self.is_running = False

        # Advisor mode tracking
        self.advisor_session = {
            'wins': 0,
            'losses': 0,
            'pushes': 0,
            'blackjacks': 0,
            'total_pnl': 0.0,
            'total_wagered': 0.0,
            'hands_by_tc': {},  # Track results by true count bucket
            'current_hand': None,  # Track current hand for result logging
            'last_bet': 10.0,  # Track last bet for result calculation
        }

        cprint(f"\n  Mode: {mode.upper()}", "cyan")
        cprint(f"  Counting: {counting_system.upper()}", "cyan")
        cprint(f"  Betting: {betting_method.upper()}", "cyan")
        cprint(f"  Voice: {'ON' if voice_enabled else 'OFF'}", "cyan")
        cprint("  Ready!\n", "green", attrs=['bold'])

    def run(self) -> None:
        """Main agent loop based on mode"""
        self.is_running = True

        if self.mode == 'simulation':
            self._run_simulation()
        elif self.mode == 'advisor':
            self._run_advisor()
        elif self.mode == 'auto':
            self._run_auto()
        elif self.mode == 'training':
            self._run_training()
        else:
            cprint(f"Unknown mode: {self.mode}", "red")

    def _run_simulation(self) -> None:
        """Run in simulation mode against internal simulator"""
        self.voice.announce_session_start(self.betting.bankroll)

        try:
            while self.is_running and self.betting.can_bet():
                # Check for shuffle
                if self.simulator.shoe_needs_shuffle:
                    self.counter.reset()
                    self.voice.announce_shuffle()
                    time.sleep(0.5)

                # Get bet recommendation
                bet = self.betting.get_bet(self.counter.true_count)

                # Start new hand
                self.hand_number += 1
                state = self.simulator.new_round(bet)

                # Add visible cards to count
                for card in state.cards_dealt:
                    self.counter.add_card(card)

                # Display initial state
                game_display = GameDisplay(
                    player_cards=state.player_hands[0].cards,
                    player_value=state.player_hands[0].value,
                    dealer_upcard=state.dealer_upcard
                )

                self._display_state(game_display, bet)

                # Check for immediate completion (blackjack/dealer BJ)
                if state.is_complete:
                    self._handle_results(state, bet)
                    time.sleep(1)
                    continue

                # Play each hand
                hand_idx = 0
                while hand_idx < len(state.player_hands):
                    hand = state.player_hands[hand_idx]

                    # Skip completed hands
                    if self.simulator.is_hand_complete(hand_idx):
                        hand_idx += 1
                        continue

                    # Get strategy action
                    strat_hand = StratHand(cards=hand.cards)
                    action, source = self.strategy.get_action(
                        strat_hand,
                        state.dealer_upcard,
                        true_count=self.counter.true_count,
                        can_double=hand.can_double(self.simulator.rules),
                        can_split=hand.can_split(self.simulator.rules, self.simulator._count_splits())
                    )

                    # Announce and display action
                    self.voice.announce_action(action, hand.value)
                    if self.dashboard_enabled:
                        self.dashboard.display_action_recommendation(
                            action, source, hand.value, state.dealer_upcard,
                            self.counter.true_count if source == 'deviation' else None
                        )

                    # Execute action
                    state = self.simulator.player_action(hand_idx, action)

                    # Update count with new cards
                    for card in state.cards_dealt[len(game_display.player_cards) + 1:]:
                        self.counter.add_card(card)

                    # Check if we continue with this hand
                    if action in ['S', 'D', 'R'] or self.simulator.is_hand_complete(hand_idx):
                        hand_idx += 1
                    else:
                        # Update display for continued play
                        game_display.player_cards = hand.cards
                        game_display.player_value = hand.value
                        time.sleep(0.3)

                # Play dealer
                state = self.simulator.play_dealer()

                # Add dealer cards to count
                for card in state.dealer_hand.cards[1:]:  # Skip upcard already counted
                    if card != state.dealer_upcard:
                        self.counter.add_card(card)

                # Handle results
                self._handle_results(state, bet)

                # Delay between hands
                time.sleep(0.5)

        except KeyboardInterrupt:
            cprint("\n\nSession interrupted by user", "yellow")

        finally:
            self._end_session()

    def _run_advisor(self) -> None:
        """Run in advisor mode - manual input, agent advises"""
        cprint("\n=== BLACKJACK ADVISOR MODE ===", "cyan", attrs=['bold'])
        cprint("Enter cards as they appear. Agent will advise optimal plays.\n", "white")
        cprint("Commands:", "yellow")
        cprint("  'n'  - New hand (enter your cards + dealer)", "white")
        cprint("  'w'  - Won (e.g., 'w' or 'w 15' for $15 win)", "white")
        cprint("  'l'  - Lost (e.g., 'l' or 'l 10' for $10 loss)", "white")
        cprint("  'p'  - Push (tie)", "white")
        cprint("  'bj' - Blackjack! (1.5x payout)", "white")
        cprint("  'c'  - Show current count", "white")
        cprint("  'b'  - Show bet recommendation", "white")
        cprint("  's'  - Shuffle (reset count)", "white")
        cprint("  'stats' - Show session statistics", "white")
        cprint("  'h'  - Add hit cards (e.g., 'h 5' or 'h K 3')", "white")
        cprint("  'd'  - Add dealer hole + hits (e.g., 'd 7 K')", "white")
        cprint("  'o'  - Other players' cards (e.g., 'o 5 K 10 A 7')", "white")
        cprint("  'q'  - Quit\n", "white")

        self.voice.announce_session_start(self.betting.bankroll)

        try:
            while self.is_running:
                # Get input
                user_input = input("> ").strip().lower()

                if not user_input:
                    continue

                # Handle commands
                if user_input in ['quit', 'q', 'exit']:
                    break

                elif user_input in ['shuffle', 's']:
                    self.counter.reset()
                    cprint("Shoe shuffled. Count reset.", "yellow")
                    self.voice.announce_shuffle()

                elif user_input in ['count', 'c']:
                    self._show_count()

                elif user_input in ['bet', 'b']:
                    self._show_bet_recommendation()

                elif user_input in ['new', 'n']:
                    self._advisor_new_hand()

                elif user_input == 'stats':
                    self._show_advisor_stats()

                elif user_input.startswith('w'):
                    self._record_result('win', user_input)

                elif user_input.startswith('l'):
                    self._record_result('loss', user_input)

                elif user_input == 'p' or user_input == 'push':
                    self._record_result('push', user_input)

                elif user_input == 'bj' or user_input == 'blackjack':
                    self._record_result('blackjack', user_input)

                elif user_input.startswith('h '):
                    # Add hit cards to player hand
                    cards = self._parse_card_input(user_input[2:])
                    self._advisor_add_hit_cards(cards)

                elif user_input.startswith('d '):
                    # Add dealer cards
                    cards = self._parse_card_input(user_input[2:])
                    self._advisor_add_dealer_cards(cards)

                elif user_input.startswith('o '):
                    # Add other players' cards (quick count update)
                    cards = self._parse_card_input(user_input[2:])
                    self._advisor_add_other_players_cards(cards)

                else:
                    # Try to parse as cards
                    self._advisor_parse_cards(user_input)

        except KeyboardInterrupt:
            pass

        finally:
            self._end_advisor_session()

    def _advisor_new_hand(self) -> None:
        """Start a new hand in advisor mode"""
        self.hand_number += 1

        # Get recommended bet BEFORE the hand
        recommended_bet = self.betting.get_bet(self.counter.true_count)
        tc_at_bet = self.counter.true_count

        cprint(f"\n--- Hand #{self.hand_number} ---", "yellow")
        cprint(f"Recommended bet: ${recommended_bet:.0f}", "yellow")

        # Get player cards
        player_input = input("Your cards (e.g., '10,6' or 'A 7'): ").strip()
        player_cards = self._parse_card_input(player_input)

        if not player_cards or len(player_cards) < 2:
            cprint("Invalid input. Need at least 2 cards.", "red")
            return

        # Get dealer upcard
        dealer_input = input("Dealer shows: ").strip()
        dealer_cards = self._parse_card_input(dealer_input)

        if not dealer_cards:
            cprint("Invalid dealer card.", "red")
            return

        dealer_upcard = dealer_cards[0]

        # Add cards to count
        for card in player_cards:
            self.counter.add_card(card)
        self.counter.add_card(dealer_upcard)

        # Get recommendation
        hand = StratHand(cards=player_cards)

        # Check for natural blackjack
        if hand.is_blackjack:
            cprint(f"\nHand: {player_cards} = BLACKJACK!", "magenta", attrs=['bold'])
            cprint(f"Dealer shows: {dealer_upcard}", "white")
            cprint(f"Count: RC={self.counter.running_count:+.0f} TC={self.counter.true_count:+.1f}", "cyan")

            # Store hand info for result tracking
            self.advisor_session['current_hand'] = {
                'player_cards': player_cards.copy(),
                'dealer_upcard': dealer_upcard,
                'tc_at_bet': tc_at_bet,
                'recommended_bet': recommended_bet,
                'action': 'BJ',
                'source': 'blackjack',
                'is_blackjack': True
            }
            self.advisor_session['last_bet'] = recommended_bet

            # Check if dealer might also have blackjack
            if dealer_upcard in ['A', '10', 'J', 'Q', 'K']:
                cprint(f"\nDealer could have blackjack too!", "yellow")
                cprint("Enter 'd [hole card]' to see dealer's hand", "yellow")
            else:
                cprint(f"\nBLACKJACK WINS! Enter 'd [hole card]' or 'bj' to record", "green", attrs=['bold'])
            return

        action, source = self.strategy.get_action(
            hand,
            dealer_upcard,
            true_count=self.counter.true_count
        )

        # Store current hand info for result tracking
        self.advisor_session['current_hand'] = {
            'player_cards': player_cards.copy(),
            'dealer_upcard': dealer_upcard,
            'tc_at_bet': tc_at_bet,
            'recommended_bet': recommended_bet,
            'action': action,
            'source': source
        }
        self.advisor_session['last_bet'] = recommended_bet

        # Display recommendation
        action_names = {'H': 'HIT', 'S': 'STAND', 'D': 'DOUBLE', 'P': 'SPLIT', 'R': 'SURRENDER'}
        action_name = action_names.get(action, action)

        cprint(f"\nHand: {player_cards} = {hand.total} vs {dealer_upcard}", "white")
        cprint(f"Count: RC={self.counter.running_count:+.0f} TC={self.counter.true_count:+.1f}", "cyan")

        action_color = 'green' if action in ['S', 'D'] else 'cyan' if action == 'H' else 'magenta'
        cprint(f"\n>>> {action_name} <<<", action_color, attrs=['bold'])

        if source == 'deviation':
            cprint(f"(Deviation at TC {self.counter.true_count:+.1f})", "yellow")

        self.voice.announce_action(action, hand.total)

        # Show quick session status
        session = self.advisor_session
        if session['wins'] + session['losses'] + session['pushes'] > 0:
            pnl_color = 'green' if session['total_pnl'] >= 0 else 'red'
            cprint(f"\nSession: {session['wins']}W-{session['losses']}L-{session['pushes']}P | P&L: ${session['total_pnl']:+.0f}", pnl_color)

    def _advisor_parse_cards(self, input_str: str) -> None:
        """Parse and add cards to count"""
        cards = self._parse_card_input(input_str)
        if cards:
            for card in cards:
                self.counter.add_card(card)
                cprint(f"Added: {card}", "green")
            self._show_count()

    def _parse_card_input(self, input_str: str) -> list:
        """Parse card input string into list of cards"""
        # Handle various separators
        input_str = input_str.replace(',', ' ').replace('.', ' ').replace('-', ' ')
        parts = input_str.upper().split()

        cards = []
        for part in parts:
            # Normalize card
            if part in ['10', 'T']:
                cards.append('10')
            elif part in ['J', 'JACK']:
                cards.append('J')
            elif part in ['Q', 'QUEEN']:
                cards.append('Q')
            elif part in ['K', 'KING']:
                cards.append('K')
            elif part in ['A', 'ACE', '1']:
                cards.append('A')
            elif part in ['2', '3', '4', '5', '6', '7', '8', '9']:
                cards.append(part)

        return cards

    def _show_count(self) -> None:
        """Display current count"""
        cprint(f"\n{self.counter.get_count_display()}", "cyan")
        edge = self.counter.get_edge_estimate()
        edge_color = 'green' if edge > 0 else 'red'
        cprint(f"Edge: {edge*100:+.2f}%", edge_color)
        if self.counter.should_bet_big():
            cprint(">>> BET BIG! <<<", "green", attrs=['bold'])
        print()

    def _show_bet_recommendation(self) -> None:
        """Show betting recommendation"""
        bet_info = self.betting.get_bet_info(self.counter.true_count)
        cprint(f"\nRecommended Bet: ${bet_info['recommended_bet']:.0f}", "yellow", attrs=['bold'])
        cprint(f"Method: {bet_info['method']}", "white")
        cprint(f"Edge: {bet_info['edge']:+.2f}%", "cyan")
        cprint(f"Bankroll: ${bet_info['bankroll']:.2f}", "white")
        print()

    def _record_result(self, result_type: str, user_input: str) -> None:
        """Record hand result in advisor mode"""
        session = self.advisor_session
        last_bet = session['last_bet']

        # Parse amount if provided (e.g., 'w 15' or 'l 20')
        parts = user_input.split()
        if len(parts) > 1:
            try:
                last_bet = float(parts[1])
            except ValueError:
                pass

        # Calculate P&L based on result type
        if result_type == 'win':
            pnl = last_bet
            session['wins'] += 1
            result_text = f"WIN +${pnl:.0f}"
            result_color = 'green'
            self.voice.announce_result('win', pnl)

        elif result_type == 'loss':
            pnl = -last_bet
            session['losses'] += 1
            result_text = f"LOSS -${last_bet:.0f}"
            result_color = 'red'
            self.voice.announce_result('lose', pnl)

        elif result_type == 'push':
            pnl = 0
            session['pushes'] += 1
            result_text = "PUSH $0"
            result_color = 'yellow'
            self.voice.announce_result('push', 0)

        elif result_type == 'blackjack':
            pnl = last_bet * 1.5  # 3:2 payout
            session['wins'] += 1
            session['blackjacks'] += 1
            result_text = f"BLACKJACK! +${pnl:.0f}"
            result_color = 'magenta'
            self.voice.announce_result('blackjack', pnl)

        else:
            cprint("Unknown result type", "red")
            return

        # Update session totals
        session['total_pnl'] += pnl
        session['total_wagered'] += last_bet

        # Track by true count bucket
        if session['current_hand']:
            tc = session['current_hand']['tc_at_bet']
            tc_bucket = int(round(tc))  # Round to nearest integer
            if tc_bucket not in session['hands_by_tc']:
                session['hands_by_tc'][tc_bucket] = {'wins': 0, 'losses': 0, 'pushes': 0, 'pnl': 0}

            tc_data = session['hands_by_tc'][tc_bucket]
            tc_data['pnl'] += pnl
            if result_type in ['win', 'blackjack']:
                tc_data['wins'] += 1
            elif result_type == 'loss':
                tc_data['losses'] += 1
            else:
                tc_data['pushes'] += 1

        # Display result
        cprint(f"\n{result_text}", result_color, attrs=['bold'])

        # Show session summary
        total_hands = session['wins'] + session['losses'] + session['pushes']
        win_rate = (session['wins'] / total_hands * 100) if total_hands > 0 else 0
        pnl_color = 'green' if session['total_pnl'] >= 0 else 'red'

        cprint(f"Session: {session['wins']}W-{session['losses']}L-{session['pushes']}P ({win_rate:.0f}%)", "white")
        cprint(f"P&L: ${session['total_pnl']:+.0f}", pnl_color, attrs=['bold'])

        # Clear current hand
        session['current_hand'] = None

    def _advisor_add_hit_cards(self, cards: list) -> None:
        """Add hit cards to current hand and get new recommendation"""
        if not cards:
            cprint("No cards to add", "red")
            return

        session = self.advisor_session
        if not session['current_hand']:
            cprint("No active hand. Start with 'n' first.", "yellow")
            # Still add to count
            for card in cards:
                self.counter.add_card(card)
                cprint(f"Added to count: {card}", "green")
            self._show_count()
            return

        # Add cards to count and current hand
        for card in cards:
            self.counter.add_card(card)
            session['current_hand']['player_cards'].append(card)

        # Get new recommendation
        hand = StratHand(cards=session['current_hand']['player_cards'])
        dealer_upcard = session['current_hand']['dealer_upcard']

        if hand.total > 21:
            cprint(f"\nHand: {session['current_hand']['player_cards']} = {hand.total} BUST!", "red", attrs=['bold'])
            # Auto-record the loss
            self._record_result('loss', 'l')
            return

        action, source = self.strategy.get_action(
            hand,
            dealer_upcard,
            true_count=self.counter.true_count,
            can_double=False,  # Can't double after hit
            can_split=False    # Can't split after hit
        )

        action_names = {'H': 'HIT', 'S': 'STAND', 'D': 'DOUBLE', 'P': 'SPLIT', 'R': 'SURRENDER'}
        action_name = action_names.get(action, action)

        cprint(f"\nHand: {session['current_hand']['player_cards']} = {hand.total} vs {dealer_upcard}", "white")
        cprint(f"Count: RC={self.counter.running_count:+.0f} TC={self.counter.true_count:+.1f}", "cyan")

        action_color = 'green' if action in ['S'] else 'cyan'
        cprint(f"\n>>> {action_name} <<<", action_color, attrs=['bold'])

        self.voice.announce_action(action, hand.total)

    def _advisor_add_dealer_cards(self, cards: list) -> None:
        """Add dealer hole card and hit cards to count, then auto-calculate result"""
        if not cards:
            cprint("No cards to add", "red")
            return

        session = self.advisor_session

        # Add cards to count
        cprint("\nDealer cards:", "yellow")
        for card in cards:
            self.counter.add_card(card)
            cprint(f"  Added: {card}", "green")

        # If we have an active hand, calculate the result
        if session['current_hand']:
            player_cards = session['current_hand']['player_cards']
            dealer_upcard = session['current_hand']['dealer_upcard']
            player_has_bj = session['current_hand'].get('is_blackjack', False)

            # Build dealer hand: upcard + hole card + any hits
            dealer_cards = [dealer_upcard] + cards

            # Calculate totals
            player_total = self._calculate_hand_total(player_cards)
            dealer_total = self._calculate_hand_total(dealer_cards)
            dealer_has_bj = (len(dealer_cards) == 2 and dealer_total == 21)

            cprint(f"\nYour hand: {player_cards} = {player_total}{'  BLACKJACK!' if player_has_bj else ''}", "white")
            cprint(f"Dealer:    {dealer_cards} = {dealer_total}{'  BLACKJACK!' if dealer_has_bj else ''}", "white")

            # Determine result with blackjack logic
            if player_has_bj and dealer_has_bj:
                # Both have blackjack - push
                cprint("\nBoth have Blackjack!", "yellow", attrs=['bold'])
                self._record_result('push', 'p')
            elif player_has_bj:
                # Player blackjack wins 1.5x
                cprint("\nBLACKJACK WINS!", "magenta", attrs=['bold'])
                self._record_result('blackjack', 'bj')
            elif dealer_has_bj:
                # Dealer blackjack wins
                cprint("\nDealer Blackjack!", "red", attrs=['bold'])
                self._record_result('loss', 'l')
            elif dealer_total > 21:
                # Dealer busts - player wins!
                cprint("\nDealer BUSTS!", "green", attrs=['bold'])
                self._record_result('win', 'w')
            elif player_total > dealer_total:
                # Player wins
                self._record_result('win', 'w')
            elif dealer_total > player_total:
                # Dealer wins
                self._record_result('loss', 'l')
            else:
                # Push
                self._record_result('push', 'p')
        else:
            # No active hand, just show count update
            self._show_count()

    def _advisor_add_other_players_cards(self, cards: list) -> None:
        """Quickly add other players' cards to the count"""
        if not cards:
            cprint("No cards to add", "red")
            return

        # Add all cards to count
        for card in cards:
            self.counter.add_card(card)

        # Display summary
        card_count = len(cards)
        cprint(f"\n+{card_count} cards from other players: {cards}", "cyan")
        cprint(f"{self.counter.get_count_display()}", "cyan")

        # Show edge update
        edge = self.counter.get_edge_estimate()
        edge_color = 'green' if edge > 0 else 'red'
        cprint(f"Edge: {edge*100:+.2f}%", edge_color)

        # Alert if count is favorable
        if self.counter.true_count >= 2:
            cprint(f">>> COUNT IS HOT! TC={self.counter.true_count:+.1f} <<<", "green", attrs=['bold'])
        elif self.counter.true_count <= -2:
            cprint(f"Count is cold. TC={self.counter.true_count:+.1f}", "yellow")

    def _calculate_hand_total(self, cards: list) -> int:
        """Calculate hand total, handling aces optimally"""
        total = 0
        aces = 0

        for card in cards:
            card = str(card).upper()
            if card in ['J', 'Q', 'K']:
                total += 10
            elif card == '10':
                total += 10
            elif card == 'A':
                aces += 1
                total += 11
            else:
                try:
                    total += int(card)
                except ValueError:
                    pass

        # Convert aces from 11 to 1 as needed
        while total > 21 and aces > 0:
            total -= 10
            aces -= 1

        return total

    def _show_advisor_stats(self) -> None:
        """Show detailed advisor session statistics"""
        session = self.advisor_session
        total_hands = session['wins'] + session['losses'] + session['pushes']

        cprint("\n" + "=" * 50, "cyan")
        cprint("SESSION STATISTICS", "cyan", attrs=['bold'])
        cprint("=" * 50, "cyan")

        if total_hands == 0:
            cprint("No hands played yet.", "yellow")
            return

        # Basic stats
        win_rate = (session['wins'] / total_hands * 100)
        roi = (session['total_pnl'] / session['total_wagered'] * 100) if session['total_wagered'] > 0 else 0

        pnl_color = 'green' if session['total_pnl'] >= 0 else 'red'

        cprint(f"\nHands Played: {total_hands}", "white")
        cprint(f"  Wins:       {session['wins']} ({win_rate:.1f}%)", "green")
        cprint(f"  Losses:     {session['losses']}", "red")
        cprint(f"  Pushes:     {session['pushes']}", "yellow")
        cprint(f"  Blackjacks: {session['blackjacks']}", "magenta")

        cprint(f"\nTotal Wagered: ${session['total_wagered']:.0f}", "white")
        cprint(f"Total P&L:     ${session['total_pnl']:+.0f}", pnl_color, attrs=['bold'])
        cprint(f"ROI:           {roi:+.2f}%", pnl_color)

        # Results by true count
        if session['hands_by_tc']:
            cprint("\n--- Results by True Count ---", "yellow")
            for tc in sorted(session['hands_by_tc'].keys()):
                data = session['hands_by_tc'][tc]
                total = data['wins'] + data['losses'] + data['pushes']
                wr = (data['wins'] / total * 100) if total > 0 else 0
                tc_pnl_color = 'green' if data['pnl'] >= 0 else 'red'
                cprint(f"  TC {tc:+2}: {data['wins']}W-{data['losses']}L-{data['pushes']}P | P&L: ${data['pnl']:+.0f} | WR: {wr:.0f}%", tc_pnl_color)

        # Count status
        cprint(f"\n--- Current Count ---", "yellow")
        cprint(f"  {self.counter.get_count_display()}", "cyan")
        edge = self.counter.get_edge_estimate()
        edge_color = 'green' if edge > 0 else 'red'
        cprint(f"  Edge: {edge*100:+.2f}%", edge_color)

        cprint("=" * 50 + "\n", "cyan")

    def _end_advisor_session(self) -> None:
        """End advisor session and show final summary"""
        self.is_running = False
        session = self.advisor_session
        total_hands = session['wins'] + session['losses'] + session['pushes']

        cprint("\n" + "=" * 50, "cyan")
        cprint("SESSION COMPLETE", "cyan", attrs=['bold'])
        cprint("=" * 50, "cyan")

        if total_hands > 0:
            win_rate = (session['wins'] / total_hands * 100)
            roi = (session['total_pnl'] / session['total_wagered'] * 100) if session['total_wagered'] > 0 else 0
            pnl_color = 'green' if session['total_pnl'] >= 0 else 'red'

            cprint(f"\nFinal Results:", "white", attrs=['bold'])
            cprint(f"  Hands:  {total_hands} ({session['wins']}W-{session['losses']}L-{session['pushes']}P)", "white")
            cprint(f"  P&L:    ${session['total_pnl']:+.0f}", pnl_color, attrs=['bold'])
            cprint(f"  ROI:    {roi:+.2f}%", pnl_color)

            if session['blackjacks'] > 0:
                cprint(f"  BJs:    {session['blackjacks']}", "magenta")

            self.voice.announce_session_end(session['total_pnl'], total_hands)
        else:
            cprint("\nNo hands recorded.", "yellow")

        cprint("\nGoodbye! Good luck at the tables!", "cyan")
        cprint("=" * 50 + "\n", "cyan")

    def _run_auto(self) -> None:
        """Run in autonomous browser mode"""
        cprint("\nAutonomous browser mode not yet implemented.", "yellow")
        cprint("Use simulation or advisor mode for now.", "white")
        cprint("Browser automation coming in next update!", "cyan")

    def _run_training(self) -> None:
        """Run training mode with Pro Trainer"""
        from .pro_trainer import ProTrainer
        trainer = ProTrainer(counting_system=self.counter.system)
        trainer.run()

    def _handle_results(self, state, bet: float) -> None:
        """Handle end of hand results"""
        total_pnl = 0

        for i, (result, pnl) in enumerate(state.results):
            total_pnl += pnl

            # Announce result
            result_name = result.value
            self.voice.announce_result(result_name, pnl)

        # Update bankroll
        self.betting.update_bankroll(total_pnl, bet, self.counter.true_count)

        # Update display
        game_display = GameDisplay(
            player_cards=state.player_hands[0].cards,
            player_value=state.player_hands[0].value,
            dealer_upcard=state.dealer_upcard,
            dealer_cards=state.dealer_hand.cards,
            dealer_value=state.dealer_hand.value,
            is_complete=True,
            result=state.results[0][0].value if state.results else None,
            pnl=total_pnl
        )

        self._display_state(game_display, bet, show_result=True)

    def _display_state(self, game: GameDisplay, bet: float, show_result: bool = False) -> None:
        """Display current game state with full dashboard"""
        if not self.dashboard_enabled:
            return

        session_stats = self.betting.get_stats()

        self.dashboard.display_full(
            game=game,
            hand_num=self.hand_number,
            running_count=self.counter.running_count,
            true_count=self.counter.true_count,
            decks_remaining=self.counter.decks_remaining,
            cards_seen=self.counter.cards_seen,
            recommended_bet=self.betting.get_bet(self.counter.true_count),
            bankroll=self.betting.bankroll,
            edge=self.counter.get_edge_estimate() * 100,
            session_stats=session_stats
        )

    def _end_session(self) -> None:
        """End session and show summary"""
        self.is_running = False
        stats = self.betting.get_stats()

        self.voice.announce_session_end(stats['session_pnl'], stats['hands_played'])
        if self.dashboard_enabled:
            self.dashboard.display_goodbye(stats)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Blackjack God Agent')
    parser.add_argument('--mode', '-m', choices=['simulation', 'advisor', 'auto', 'training'],
                        default='simulation', help='Operating mode')
    parser.add_argument('--counting', '-c', choices=['hi_lo', 'omega_ii', 'wong_halves'],
                        default='hi_lo', help='Card counting system')
    parser.add_argument('--betting', '-b', choices=['kelly', 'spread', 'spread_aggressive', 'flat'],
                        default='spread', help='Betting method (spread_aggressive for poor penetration games)')
    parser.add_argument('--bankroll', '-r', type=float, default=1000,
                        help='Starting bankroll')
    parser.add_argument('--decks', '-d', type=int, default=6,
                        help='Number of decks')
    parser.add_argument('--no-voice', action='store_true',
                        help='Disable voice announcements')
    parser.add_argument('--no-dashboard', action='store_true',
                        help='Disable dashboard display')

    args = parser.parse_args()

    try:
        agent = BlackjackAgent(
            mode=args.mode,
            counting_system=args.counting,
            betting_method=args.betting,
            voice_enabled=not args.no_voice,
            dashboard_enabled=not args.no_dashboard,
            num_decks=args.decks,
            starting_bankroll=args.bankroll
        )
        agent.run()

    except KeyboardInterrupt:
        cprint("\n\nGoodbye!", "cyan")
    except Exception as e:
        cprint(f"\nError: {e}", "red")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
