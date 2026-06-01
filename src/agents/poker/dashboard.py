"""
Dashboard - Terminal UI with range display and visualizations
The command center for the Poker God
Built with love by TradeHive
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Optional

project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.poker.core.range_manager import Range, RangeManager


class Colors:
    """ANSI color codes"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"


class Dashboard:
    """
    Terminal dashboard for poker analysis
    
    Features:
    - Range visualization (13x13 grid)
    - Equity displays
    - Session statistics
    - Hand history
    """
    
    RANKS = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2']
    
    def __init__(self, width: int = 80):
        self.width = width
        self.range_manager = RangeManager()
        
    def clear(self):
        """Clear terminal"""
        os.system('cls' if os.name == 'nt' else 'clear')
        
    def header(self, title: str):
        """Print header"""
        print()
        print(f"{Colors.CYAN}{Colors.BOLD}{'='*self.width}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}{title.center(self.width)}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}{'='*self.width}{Colors.RESET}")
        print()
        
    def subheader(self, title: str):
        """Print subheader"""
        print(f"\n{Colors.YELLOW}{Colors.BOLD}{title}{Colors.RESET}")
        print(f"{Colors.DIM}{'-'*len(title)}{Colors.RESET}")
        
    def info(self, label: str, value: str, color: str = None):
        """Print info line"""
        if color:
            print(f"  {label}: {color}{value}{Colors.RESET}")
        else:
            print(f"  {label}: {value}")
            
    def success(self, message: str):
        """Print success message"""
        print(f"{Colors.GREEN}✓ {message}{Colors.RESET}")
        
    def warning(self, message: str):
        """Print warning message"""
        print(f"{Colors.YELLOW}⚠ {message}{Colors.RESET}")
        
    def error(self, message: str):
        """Print error message"""
        print(f"{Colors.RED}✗ {message}{Colors.RESET}")
        
    def visualize_range(self, notation: str, title: str = "Range"):
        """
        Visualize a range as colored 13x13 grid
        """
        r = Range.from_notation(notation)
        
        print(f"\n{Colors.CYAN}{Colors.BOLD}{title}{Colors.RESET}")
        print(f"{Colors.DIM}Notation: {notation}{Colors.RESET}")
        print(f"{Colors.DIM}Combos: {r.combo_count()} ({r.percentage():.1f}%){Colors.RESET}\n")
        
        # Header row
        print("    ", end="")
        for rank in self.RANKS:
            print(f" {rank} ", end="")
        print()
        print("   " + "---" * 13)
        
        # Grid
        for i, rank1 in enumerate(self.RANKS):
            print(f" {rank1} |", end="")
            for j, rank2 in enumerate(self.RANKS):
                if i == j:
                    # Pairs
                    hand = f"{rank1}{rank2}"
                elif i < j:
                    # Suited (above diagonal)
                    hand = f"{rank1}{rank2}s"
                else:
                    # Offsuit (below diagonal)
                    hand = f"{rank2}{rank1}o"
                    
                if hand in r:
                    freq = r.get_frequency(hand)
                    if freq >= 0.9:
                        color = Colors.BG_GREEN
                    elif freq >= 0.5:
                        color = Colors.BG_YELLOW
                    else:
                        color = Colors.BG_BLUE
                    print(f"{color}{Colors.BLACK} {hand[0]}{hand[1]} {Colors.RESET}", end="")
                else:
                    print(f" . ", end="")
            print()
            
        print()
        print(f"{Colors.BG_GREEN}{Colors.BLACK} ■ {Colors.RESET} In range (>90%)  ", end="")
        print(f"{Colors.BG_YELLOW}{Colors.BLACK} ■ {Colors.RESET} Mixed (50-90%)  ", end="")
        print(f"{Colors.BG_BLUE}{Colors.BLACK} ■ {Colors.RESET} Low freq (<50%)")
        print()
        
    def compare_ranges(self, range1: str, range2: str, name1: str = "Range 1", name2: str = "Range 2"):
        """Compare two ranges side by side"""
        r1 = Range.from_notation(range1)
        r2 = Range.from_notation(range2)
        
        print(f"\n{Colors.CYAN}{Colors.BOLD}Range Comparison{Colors.RESET}")
        print(f"  {name1}: {r1.combo_count()} combos ({r1.percentage():.1f}%)")
        print(f"  {name2}: {r2.combo_count()} combos ({r2.percentage():.1f}%)")
        
        # Find overlap
        overlap = 0
        only_r1 = 0
        only_r2 = 0
        
        for rank1 in self.RANKS:
            for rank2 in self.RANKS:
                i = self.RANKS.index(rank1)
                j = self.RANKS.index(rank2)
                
                if i == j:
                    hand = f"{rank1}{rank2}"
                elif i < j:
                    hand = f"{rank1}{rank2}s"
                else:
                    hand = f"{rank2}{rank1}o"
                    
                in_r1 = hand in r1
                in_r2 = hand in r2
                
                if in_r1 and in_r2:
                    overlap += 1
                elif in_r1:
                    only_r1 += 1
                elif in_r2:
                    only_r2 += 1
                    
        print(f"  Overlap: {overlap} hands")
        print(f"  Only in {name1}: {only_r1}")
        print(f"  Only in {name2}: {only_r2}")
        print()
        
    def equity_bar(self, equity: float, width: int = 40, label: str = "Equity"):
        """Display equity as a progress bar"""
        filled = int(equity * width)
        empty = width - filled
        
        if equity >= 0.6:
            color = Colors.GREEN
        elif equity >= 0.4:
            color = Colors.YELLOW
        else:
            color = Colors.RED
            
        bar = f"{color}{'█' * filled}{Colors.DIM}{'░' * empty}{Colors.RESET}"
        print(f"  {label}: [{bar}] {equity*100:.1f}%")
        
    def pot_odds_display(self, pot: float, bet: float, equity: float):
        """Display pot odds analysis"""
        from src.agents.poker.core.odds_calculator import OddsCalculator
        
        calc = OddsCalculator()
        odds = calc.pot_odds(bet, pot)
        
        self.subheader("Pot Odds Analysis")
        self.info("Pot", f"${pot:.0f}")
        self.info("Bet to call", f"${bet:.0f}")
        self.info("Pot Odds", f"{odds.pot_odds*100:.1f}%", Colors.CYAN)
        self.info("Required Equity", f"{odds.break_even_equity*100:.1f}%")
        
        self.equity_bar(equity, label="Your Equity")
        
        if equity >= odds.break_even_equity:
            self.success(f"PROFITABLE CALL (+{(equity - odds.break_even_equity)*100:.1f}% edge)")
        else:
            self.error(f"UNPROFITABLE CALL ({(equity - odds.break_even_equity)*100:.1f}% short)")
            
    def session_stats(self, stats: Dict):
        """Display session statistics"""
        self.subheader("Session Statistics")
        
        hands = stats.get('hands_played', 0)
        won = stats.get('hands_won', 0)
        profit = stats.get('total_profit', 0)
        
        self.info("Hands Played", str(hands))
        self.info("Hands Won", f"{won} ({won/hands*100:.0f}%)" if hands > 0 else "0")
        
        profit_color = Colors.GREEN if profit >= 0 else Colors.RED
        self.info("Profit/Loss", f"${profit:+.2f}", profit_color)
        
        bb_100 = stats.get('bb_per_100', 0)
        bb_color = Colors.GREEN if bb_100 >= 0 else Colors.RED
        self.info("BB/100", f"{bb_100:+.1f}", bb_color)
        
    def hand_history_display(self, history: List[Dict], limit: int = 5):
        """Display recent hand history"""
        self.subheader(f"Recent Hands (last {min(limit, len(history))})")
        
        for hand in history[-limit:]:
            result_color = Colors.GREEN if hand.get('won') else Colors.RED
            result_symbol = "✓" if hand.get('won') else "✗"
            
            cards = hand.get('hole_cards', '??')
            board = hand.get('board', '')
            amount = hand.get('amount', 0)
            
            print(f"  {result_color}{result_symbol}{Colors.RESET} {cards}", end="")
            if board:
                print(f" | {board}", end="")
            print(f" | ${amount:+.2f}")
            
    def position_chart(self):
        """Display position chart"""
        self.subheader("Table Positions")
        
        positions = [
            ("UTG", "Under the Gun - First to act, tightest range"),
            ("MP", "Middle Position - Slightly wider"),
            ("HJ", "Hijack - Starting to open up"),
            ("CO", "Cutoff - Wide opening range"),
            ("BTN", "Button - Widest range, best position"),
            ("SB", "Small Blind - Stealing + defending"),
            ("BB", "Big Blind - Defend or 3-bet"),
        ]
        
        for pos, desc in positions:
            print(f"  {Colors.CYAN}{pos:4}{Colors.RESET} - {Colors.DIM}{desc}{Colors.RESET}")
            
    def gto_metrics_display(self, bet: float, pot: float):
        """Display GTO betting metrics"""
        from src.agents.poker.strategy.gto_engine import GTOEngine
        
        gto = GTOEngine()
        metrics = gto.get_gto_metrics(bet, pot)
        
        self.subheader(f"GTO Metrics (${bet:.0f} into ${pot:.0f})")
        
        self.info("MDF (Villain Defense)", f"{metrics.mdf*100:.0f}%", Colors.YELLOW)
        self.info("Bluff Break-Even", f"{metrics.alpha*100:.0f}%", Colors.CYAN)
        self.info("Your Bluff Frequency", f"{metrics.required_bluff_freq*100:.0f}%", Colors.GREEN)
        
        ratio = gto.optimal_bluff_ratio(bet, pot)
        self.info("Value:Bluff Ratio", f"{ratio:.1f}:1")
        
    def welcome_screen(self):
        """Display welcome screen"""
        self.clear()
        print()
        print(f"{Colors.CYAN}{Colors.BOLD}")
        print("   ╔═══════════════════════════════════════════════════════════╗")
        print("   ║                                                           ║")
        print("   ║        🎰  POKER GOD - THE ULTIMATE MASTER  🎰           ║")
        print("   ║                                                           ║")
        print("   ║     GTO + Exploitative | Hold'em & Omaha | Cash & MTT    ║")
        print("   ║                                                           ║")
        print("   ╚═══════════════════════════════════════════════════════════╝")
        print(f"{Colors.RESET}")
        print()
        print(f"  {Colors.YELLOW}Modes:{Colors.RESET}")
        print(f"    1. {Colors.GREEN}Advisor{Colors.RESET}    - Real-time hand analysis")
        print(f"    2. {Colors.CYAN}Training{Colors.RESET}   - Practice drills")
        print(f"    3. {Colors.MAGENTA}Simulation{Colors.RESET} - Full game simulation")
        print()
        print(f"  {Colors.DIM}Built with love by TradeHive{Colors.RESET}")
        print()


# === Demo ===
if __name__ == "__main__":
    dash = Dashboard()
    
    dash.welcome_screen()
    
    input(f"{Colors.DIM}Press Enter to continue...{Colors.RESET}")
    
    # Range visualization
    dash.visualize_range("AA-TT,AKs-AJs,KQs,AKo-AQo", "Premium Opening Range")
    
    input(f"{Colors.DIM}Press Enter to continue...{Colors.RESET}")
    
    # Pot odds display
    dash.pot_odds_display(pot=100, bet=50, equity=0.40)
    
    print()
    input(f"{Colors.DIM}Press Enter to continue...{Colors.RESET}")
    
    # GTO metrics
    dash.gto_metrics_display(bet=75, pot=100)
    
    print()
    
    # Position chart
    dash.position_chart()
    
    print()
    
    # Session stats
    dash.session_stats({
        'hands_played': 100,
        'hands_won': 55,
        'total_profit': 125.50,
        'bb_per_100': 12.5
    })
    
    print()
    
    # Hand history
    dash.hand_history_display([
        {'hole_cards': 'A♠ K♥', 'board': 'K♣ 7♦ 2♠ 9♥ 3♦', 'won': True, 'amount': 45.0},
        {'hole_cards': 'Q♥ Q♦', 'board': 'A♠ T♣ 4♥', 'won': False, 'amount': -25.0},
        {'hole_cards': '8♥ 8♣', 'board': '8♠ 5♦ 2♣ K♥ A♠', 'won': True, 'amount': 88.0},
    ])
