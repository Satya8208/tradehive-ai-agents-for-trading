"""
Dashboard - Real-time terminal display for blackjack agent
Built with love by TradeHive
"""

import os
import shutil
from typing import Dict, Optional, List
from datetime import datetime
from termcolor import colored, cprint
from dataclasses import dataclass


@dataclass
class GameDisplay:
    """Current game state for display"""
    player_cards: List[str]
    player_value: int
    dealer_upcard: str
    dealer_cards: Optional[List[str]] = None
    dealer_value: Optional[int] = None
    is_complete: bool = False
    result: Optional[str] = None
    pnl: Optional[float] = None


class Dashboard:
    """
    Terminal dashboard for real-time blackjack statistics

    Features:
    - Current game state display
    - Card counting information
    - Betting recommendations
    - Session statistics
    - Performance metrics
    """

    # Card suit symbols for visual display
    SUITS = ['♠', '♥', '♦', '♣']
    CARD_COLORS = {'♠': 'white', '♥': 'red', '♦': 'red', '♣': 'white'}

    def __init__(self, clear_screen: bool = True):
        """
        Initialize dashboard

        Args:
            clear_screen: Whether to clear screen on refresh
        """
        self.clear_screen = clear_screen
        self.terminal_width = shutil.get_terminal_size().columns
        self.session_start = datetime.now()

        # Session tracking
        self.hands_played = 0
        self.hands_won = 0
        self.hands_lost = 0
        self.hands_pushed = 0
        self.blackjacks = 0
        self.busts = 0

    def _clear(self) -> None:
        """Clear terminal screen"""
        if self.clear_screen:
            os.system('cls' if os.name == 'nt' else 'clear')

    def _center(self, text: str) -> str:
        """Center text in terminal"""
        return text.center(min(self.terminal_width, 70))

    def _separator(self, char: str = "=", color: str = "cyan") -> None:
        """Print separator line"""
        width = min(self.terminal_width, 70)
        cprint(char * width, color)

    def _card_display(self, card: str) -> str:
        """Format card for display with suit symbol"""
        import random
        suit = random.choice(self.SUITS)
        color = self.CARD_COLORS[suit]
        return colored(f"[{card}{suit}]", color)

    def _format_pnl(self, pnl: float) -> str:
        """Format P&L with color"""
        if pnl > 0:
            return colored(f"+${pnl:.2f}", "green")
        elif pnl < 0:
            return colored(f"-${abs(pnl):.2f}", "red")
        else:
            return colored("$0.00", "yellow")

    def display_header(self) -> None:
        """Display dashboard header"""
        self._separator("=", "cyan")
        cprint(self._center("BLACKJACK GOD"), "cyan", attrs=['bold'])
        cprint(self._center("Advanced Card Counting System"), "white")
        self._separator("=", "cyan")

    def display_game_state(self, game: GameDisplay, hand_num: int = 1) -> None:
        """
        Display current game state

        Args:
            game: Current game display data
            hand_num: Current hand number
        """
        cprint(f"\n  HAND #{hand_num}", "yellow", attrs=['bold'])
        self._separator("-", "yellow")

        # Dealer display
        if game.is_complete and game.dealer_cards:
            dealer_cards = " ".join(self._card_display(c) for c in game.dealer_cards)
            dealer_str = f"{dealer_cards} = {game.dealer_value}"
            if game.dealer_value and game.dealer_value > 21:
                dealer_str += colored(" BUST!", "green")
        else:
            dealer_str = f"{self._card_display(game.dealer_upcard)} [??]"

        print(f"  Dealer:  {dealer_str}")

        # Player display
        player_cards = " ".join(self._card_display(c) for c in game.player_cards)
        player_str = f"{player_cards} = {game.player_value}"

        if game.player_value > 21:
            player_str += colored(" BUST!", "red")
        elif game.player_value == 21 and len(game.player_cards) == 2:
            player_str += colored(" BLACKJACK!", "green", attrs=['bold'])

        print(f"  Player:  {player_str}")

        # Result
        if game.is_complete and game.result:
            result_colors = {
                'win': 'green', 'blackjack': 'green',
                'lose': 'red', 'bust': 'red',
                'push': 'yellow', 'surrender': 'yellow'
            }
            color = result_colors.get(game.result.lower(), 'white')
            result_str = f"  Result:  {colored(game.result.upper(), color, attrs=['bold'])}"
            if game.pnl is not None:
                result_str += f"  {self._format_pnl(game.pnl)}"
            print(result_str)

        print()

    def display_count_info(
        self,
        running_count: float,
        true_count: float,
        decks_remaining: float,
        cards_seen: int,
        system: str = "Hi-Lo"
    ) -> None:
        """
        Display card counting information

        Args:
            running_count: Current running count
            true_count: Current true count
            decks_remaining: Estimated decks remaining
            cards_seen: Number of cards seen
            system: Counting system name
        """
        cprint("  CARD COUNT", "magenta", attrs=['bold'])
        self._separator("-", "magenta")

        # True count with color coding
        tc_color = 'green' if true_count > 0 else 'red' if true_count < 0 else 'white'
        tc_display = colored(f"{true_count:+.2f}", tc_color, attrs=['bold'])

        print(f"  System:         {system}")
        print(f"  Running Count:  {running_count:+.0f}")
        print(f"  True Count:     {tc_display}")
        print(f"  Decks Left:     {decks_remaining:.1f}")
        print(f"  Cards Seen:     {cards_seen}")

        # Count indicator
        if true_count >= 4:
            cprint("  >>> HIGH COUNT - BET BIG! <<<", "green", attrs=['bold', 'blink'])
        elif true_count >= 2:
            cprint("  >> Good count - increase bets", "green")
        elif true_count <= -2:
            cprint("  << Bad count - minimum bets", "red")

        print()

    def display_betting_info(
        self,
        recommended_bet: float,
        bankroll: float,
        edge: float,
        method: str = "spread"
    ) -> None:
        """
        Display betting recommendation

        Args:
            recommended_bet: Recommended bet size
            bankroll: Current bankroll
            edge: Estimated player edge
            method: Betting method (kelly, spread, flat)
        """
        cprint("  BETTING", "yellow", attrs=['bold'])
        self._separator("-", "yellow")

        edge_color = 'green' if edge > 0 else 'red' if edge < 0 else 'white'

        print(f"  Method:         {method.title()}")
        print(f"  Recommended:    {colored(f'${recommended_bet:.0f}', 'white', attrs=['bold'])}")
        print(f"  Edge:           {colored(f'{edge:+.2f}%', edge_color)}")
        print(f"  Bankroll:       ${bankroll:.2f}")

        print()

    def display_session_stats(
        self,
        hands: int,
        won: int,
        lost: int,
        pushed: int,
        blackjacks: int,
        pnl: float,
        roi: float,
        peak: float,
        drawdown: float
    ) -> None:
        """Display session statistics"""
        cprint("  SESSION STATS", "cyan", attrs=['bold'])
        self._separator("-", "cyan")

        win_rate = (won / hands * 100) if hands > 0 else 0

        print(f"  Hands Played:   {hands}")
        print(f"  Won/Lost/Push:  {colored(str(won), 'green')}/{colored(str(lost), 'red')}/{colored(str(pushed), 'yellow')}")
        print(f"  Blackjacks:     {blackjacks}")
        print(f"  Win Rate:       {win_rate:.1f}%")

        print(f"\n  Session P&L:    {self._format_pnl(pnl)}")
        print(f"  ROI:            {colored(f'{roi:+.2f}%', 'green' if roi > 0 else 'red' if roi < 0 else 'white')}")
        print(f"  Peak:           ${peak:.2f}")
        print(f"  Drawdown:       {colored(f'{drawdown:.1f}%', 'red' if drawdown > 10 else 'yellow' if drawdown > 5 else 'green')}")

        print()

    def display_action_recommendation(
        self,
        action: str,
        source: str,
        player_total: int,
        dealer_upcard: str,
        true_count: float = None
    ) -> None:
        """
        Display action recommendation prominently

        Args:
            action: Recommended action (H, S, D, P, R)
            source: Source of recommendation (basic, deviation, ai)
            player_total: Player's hand total
            dealer_upcard: Dealer's visible card
            true_count: Current true count (for deviations)
        """
        action_names = {'H': 'HIT', 'S': 'STAND', 'D': 'DOUBLE', 'P': 'SPLIT', 'R': 'SURRENDER'}
        action_colors = {'H': 'cyan', 'S': 'yellow', 'D': 'green', 'P': 'magenta', 'R': 'red'}

        action_name = action_names.get(action, action)
        action_color = action_colors.get(action, 'white')

        self._separator("*", action_color)
        cprint(self._center(f">>> {action_name} <<<"), action_color, attrs=['bold'])

        context = f"{player_total} vs {dealer_upcard}"
        if source == 'deviation' and true_count is not None:
            context += f" (TC: {true_count:+.1f} deviation)"
        elif source == 'ai':
            context += " (AI recommended)"

        cprint(self._center(context), 'white')
        self._separator("*", action_color)
        print()

    def display_full(
        self,
        game: GameDisplay,
        hand_num: int,
        running_count: float,
        true_count: float,
        decks_remaining: float,
        cards_seen: int,
        recommended_bet: float,
        bankroll: float,
        edge: float,
        session_stats: Dict
    ) -> None:
        """
        Display complete dashboard

        Args:
            game: Current game state
            hand_num: Current hand number
            running_count: Running count
            true_count: True count
            decks_remaining: Decks remaining
            cards_seen: Cards seen
            recommended_bet: Recommended bet
            bankroll: Current bankroll
            edge: Player edge
            session_stats: Session statistics dict
        """
        self._clear()
        self.display_header()

        self.display_game_state(game, hand_num)
        self.display_count_info(running_count, true_count, decks_remaining, cards_seen)
        self.display_betting_info(recommended_bet, bankroll, edge)

        if session_stats:
            self.display_session_stats(
                hands=session_stats.get('hands_played', 0),
                won=session_stats.get('hands_won', 0),
                lost=session_stats.get('hands_lost', 0),
                pushed=session_stats.get('hands_pushed', 0),
                blackjacks=session_stats.get('blackjacks', 0),
                pnl=session_stats.get('session_pnl', 0),
                roi=session_stats.get('session_roi', 0),
                peak=session_stats.get('peak_bankroll', bankroll),
                drawdown=session_stats.get('drawdown', 0)
            )

        # Timestamp
        elapsed = datetime.now() - self.session_start
        elapsed_str = str(elapsed).split('.')[0]
        cprint(f"  Session Time: {elapsed_str}", "white")
        self._separator("=", "cyan")

    def display_goodbye(self, final_stats: Dict) -> None:
        """Display session summary on exit"""
        self._clear()
        self._separator("=", "yellow")
        cprint(self._center("SESSION COMPLETE"), "yellow", attrs=['bold'])
        self._separator("=", "yellow")

        print()
        pnl = final_stats.get('session_pnl', 0)
        hands = final_stats.get('hands_played', 0)

        cprint(f"  Hands Played:    {hands}", "white")
        cprint(f"  Final P&L:       {self._format_pnl(pnl)}", "white")
        cprint(f"  ROI:             {final_stats.get('session_roi', 0):+.2f}%", "white")

        print()
        if pnl > 0:
            cprint(self._center("Congratulations! You beat the house!"), "green", attrs=['bold'])
        elif pnl < 0:
            cprint(self._center("Better luck next time!"), "yellow")
        else:
            cprint(self._center("Broke even - not bad!"), "cyan")

        print()
        cprint(self._center("Thanks for playing Blackjack God!"), "cyan")
        self._separator("=", "yellow")


# Standalone test
if __name__ == "__main__":
    import time

    dashboard = Dashboard(clear_screen=True)

    # Test display
    game = GameDisplay(
        player_cards=['10', '6'],
        player_value=16,
        dealer_upcard='9'
    )

    session_stats = {
        'hands_played': 25,
        'hands_won': 12,
        'hands_lost': 10,
        'hands_pushed': 3,
        'blackjacks': 2,
        'session_pnl': 85.50,
        'session_roi': 3.42,
        'peak_bankroll': 1150,
        'drawdown': 4.5
    }

    dashboard.display_full(
        game=game,
        hand_num=26,
        running_count=8,
        true_count=2.7,
        decks_remaining=3.0,
        cards_seen=156,
        recommended_bet=60,
        bankroll=1085.50,
        edge=0.85,
        session_stats=session_stats
    )

    time.sleep(2)

    # Show action recommendation
    dashboard.display_action_recommendation('H', 'basic', 16, '9')

    time.sleep(2)

    # Complete game
    game.is_complete = True
    game.dealer_cards = ['9', '7', '5']
    game.dealer_value = 21
    game.result = 'lose'
    game.pnl = -10

    dashboard.display_full(
        game=game,
        hand_num=26,
        running_count=7,
        true_count=2.3,
        decks_remaining=3.0,
        cards_seen=159,
        recommended_bet=50,
        bankroll=1075.50,
        edge=0.65,
        session_stats=session_stats
    )

    time.sleep(2)

    # Goodbye
    dashboard.display_goodbye(session_stats)
