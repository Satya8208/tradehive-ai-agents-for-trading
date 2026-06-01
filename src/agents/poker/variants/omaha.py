"""
Omaha Variant - Pot Limit Omaha (PLO) specific rules
The action game where variance runs wild
Built with love by TradeHive
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict
from itertools import combinations
from enum import Enum
import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.poker.core.hand_evaluator import (
    HandEvaluator, Card, Rank, Suit, HandResult, HandRank, Deck, RANK_NAMES
)


class OmahaType(Enum):
    """Omaha game types"""
    PLO4 = "plo4"        # 4 cards (standard)
    PLO5 = "plo5"        # 5 cards
    PLO6 = "plo6"        # 6 cards


@dataclass
class OmahaHand:
    """Represents an Omaha hand (4-6 cards)"""
    cards: List[Card]
    
    def __str__(self) -> str:
        return " ".join(str(c) for c in self.cards)
    
    def pretty(self) -> str:
        return " ".join(c.pretty() for c in self.cards)
    
    @classmethod
    def from_string(cls, notation: str) -> 'OmahaHand':
        """Parse notation like 'AhKhQdJd' or 'Ah Kh Qd Jd'"""
        notation = notation.replace(" ", "")
        cards = []
        i = 0
        while i < len(notation):
            if i + 1 < len(notation):
                cards.append(Card.from_string(notation[i:i+2]))
                i += 2
        return cls(cards)
        
    def is_double_suited(self) -> bool:
        """Check if hand is double suited"""
        suits = [c.suit for c in self.cards]
        suit_counts = {}
        for s in suits:
            suit_counts[s] = suit_counts.get(s, 0) + 1
        return sum(1 for c in suit_counts.values() if c >= 2) >= 2
        
    def is_single_suited(self) -> bool:
        """Check if hand has exactly one suited combination"""
        suits = [c.suit for c in self.cards]
        suit_counts = {}
        for s in suits:
            suit_counts[s] = suit_counts.get(s, 0) + 1
        return sum(1 for c in suit_counts.values() if c >= 2) == 1
        
    def has_pair(self) -> bool:
        """Check if hand contains a pair"""
        ranks = [c.rank for c in self.cards]
        return len(ranks) != len(set(ranks))
        
    def is_rundown(self) -> bool:
        """Check if hand is a connected rundown (4 consecutive)"""
        ranks = sorted([c.rank for c in self.cards])
        for i in range(len(ranks) - 3):
            if ranks[i+3] - ranks[i] == 3:
                return True
        # Check wheel rundown (A234, A235, etc)
        if Rank.ACE in ranks:
            low_ranks = [r for r in ranks if r <= 5] + [1]  # Ace as 1
            low_ranks = sorted(set(low_ranks))
            for i in range(len(low_ranks) - 3):
                if low_ranks[i+3] - low_ranks[i] == 3:
                    return True
        return False
        
    def get_high_cards(self) -> List[Rank]:
        """Get broadway cards (T+)"""
        return sorted([c.rank for c in self.cards if c.rank >= 10], reverse=True)


class OmahaVariant:
    """
    Omaha (PLO) variant implementation
    
    Key differences from Hold'em:
    - 4 hole cards instead of 2
    - MUST use exactly 2 from hand and 3 from board
    - Pot limit betting
    - Much higher variance
    - Different hand equities (draws run hotter)
    """
    
    def __init__(self, game_type: OmahaType = OmahaType.PLO4):
        self.game_type = game_type
        self.num_hole_cards = int(game_type.value[-1])
        self.evaluator = HandEvaluator()
        
    def evaluate(self, hole_cards: List[Card], board: List[Card]) -> HandResult:
        """
        Evaluate Omaha hand
        
        Must use exactly 2 cards from hand and 3 from board
        
        Args:
            hole_cards: 4-6 hole cards
            board: 3-5 community cards
            
        Returns:
            Best possible HandResult
        """
        if len(hole_cards) < 4:
            raise ValueError("Omaha requires at least 4 hole cards")
        if len(board) < 3:
            raise ValueError("Need at least 3 board cards")
            
        best_result = None
        
        # Try all combinations of 2 from hand, 3 from board
        for hand_combo in combinations(hole_cards, 2):
            for board_combo in combinations(board, 3):
                five_cards = list(hand_combo) + list(board_combo)
                result = self.evaluator.evaluate(five_cards, [])
                
                if best_result is None:
                    best_result = result
                elif self.evaluator.compare(result, best_result) < 0:
                    best_result = result
                    
        return best_result
        
    def get_all_made_hands(self, hole_cards: List[Card], board: List[Card]) -> List[Tuple[List[Card], HandResult]]:
        """Get all possible 5-card combinations with their evaluations"""
        hands = []
        
        for hand_combo in combinations(hole_cards, 2):
            for board_combo in combinations(board, 3):
                five_cards = list(hand_combo) + list(board_combo)
                result = self.evaluator.evaluate(five_cards, [])
                hands.append((five_cards, result))
                
        # Sort by hand strength
        hands.sort(key=lambda x: x[1].score)
        return hands
        
    def has_nut_flush_draw(self, hole_cards: List[Card], board: List[Card]) -> Tuple[bool, Optional[Suit]]:
        """Check if we have the nut flush draw"""
        # Count suits on board
        board_suits = {}
        for c in board:
            board_suits[c.suit] = board_suits.get(c.suit, 0) + 1
            
        # Find suits with 2 cards (flush draw possible)
        for suit, count in board_suits.items():
            if count >= 2:
                # Get highest board card of that suit
                board_cards_of_suit = sorted([c.rank for c in board if c.suit == suit], reverse=True)
                
                # Check our hole cards
                our_cards_of_suit = sorted([c.rank for c in hole_cards if c.suit == suit], reverse=True)
                
                if len(our_cards_of_suit) >= 2:  # We have flush draw
                    # Do we have the ace?
                    if Rank.ACE in our_cards_of_suit and Rank.ACE not in board_cards_of_suit:
                        return True, suit
                        
        return False, None
        
    def has_wrap(self, hole_cards: List[Card], board: List[Card]) -> Tuple[bool, int]:
        """
        Check if we have a wrap straight draw
        
        Wrap = 13+ outs to a straight (more outs than OESD)
        
        Returns:
            (has_wrap, number_of_outs)
        """
        if len(board) < 3:
            return False, 0
            
        board_ranks = [c.rank for c in board]
        hole_ranks = [c.rank for c in hole_cards]
        
        # Count straight outs
        outs = 0
        for test_rank in range(2, 15):  # 2 through Ace
            if test_rank in board_ranks or test_rank in hole_ranks:
                continue
                
            # Simulate adding this card
            test_board = board_ranks + [test_rank]
            
            # Check all 2-card combos from our hand
            for combo in combinations(hole_ranks, 2):
                test_five = sorted(list(combo) + test_board[:3])
                
                # Check for straight
                for i in range(len(test_five) - 4):
                    if test_five[i+4] - test_five[i] == 4:
                        outs += 1
                        break
                        
        is_wrap = outs >= 13
        return is_wrap, outs
        
    def analyze_hand_strength(self, hole_cards: List[Card], board: List[Card]) -> Dict:
        """
        Comprehensive Omaha hand analysis
        
        Returns analysis dict with:
        - current_hand: Our made hand
        - draws: Available draws
        - blockers: Key cards we block
        - playability: Overall hand quality
        """
        analysis = {
            'current_hand': None,
            'is_nut_hand': False,
            'draws': [],
            'blockers': [],
            'playability': 'medium'
        }
        
        if len(board) >= 3:
            # Evaluate current hand
            result = self.evaluate(hole_cards, board)
            analysis['current_hand'] = result.description
            
            # Check draws
            has_nfd, nfd_suit = self.has_nut_flush_draw(hole_cards, board)
            if has_nfd:
                analysis['draws'].append('nut flush draw')
                
            has_wrap, wrap_outs = self.has_wrap(hole_cards, board)
            if has_wrap:
                analysis['draws'].append(f'wrap ({wrap_outs} outs)')
                
        # Analyze starting hand properties
        omaha_hand = OmahaHand(hole_cards)
        
        if omaha_hand.is_double_suited():
            analysis['suited'] = 'double suited'
        elif omaha_hand.is_single_suited():
            analysis['suited'] = 'single suited'
        else:
            analysis['suited'] = 'rainbow'
            
        if omaha_hand.is_rundown():
            analysis['connectivity'] = 'rundown'
        elif omaha_hand.has_pair():
            analysis['connectivity'] = 'paired'
        else:
            analysis['connectivity'] = 'connected'
            
        # Check blockers
        high_cards = omaha_hand.get_high_cards()
        if Rank.ACE in high_cards:
            analysis['blockers'].append('Ace blocker')
        if Rank.KING in high_cards:
            analysis['blockers'].append('King blocker')
            
        # Rate playability
        if omaha_hand.is_double_suited() and omaha_hand.is_rundown():
            analysis['playability'] = 'premium'
        elif omaha_hand.is_double_suited() or (len(high_cards) >= 3):
            analysis['playability'] = 'strong'
        elif omaha_hand.is_single_suited() and len(high_cards) >= 2:
            analysis['playability'] = 'playable'
        else:
            analysis['playability'] = 'marginal'
            
        return analysis
        
    def pot_limit_max_bet(self, pot: float, to_call: float = 0) -> float:
        """
        Calculate maximum pot-limit bet
        
        Max bet = pot + 2 * to_call (when facing a bet)
        Max bet = pot (when no bet to call)
        """
        return pot + 2 * to_call
        
    def is_premium_starting_hand(self, hole_cards: List[Card]) -> bool:
        """Check if starting hand is premium PLO hand"""
        hand = OmahaHand(hole_cards)
        
        # Premium criteria:
        # 1. Double suited + rundown (AAKKds, KQJT, etc)
        # 2. AA** double suited
        # 3. High rundowns (KQJT, QJT9)
        
        ranks = sorted([c.rank for c in hole_cards], reverse=True)
        
        # Check for AA
        if ranks.count(14) >= 2 and hand.is_double_suited():
            return True
            
        # High rundown double suited
        if hand.is_double_suited() and hand.is_rundown() and ranks[0] >= 10:
            return True
            
        # Strong broadway hands
        if all(r >= 10 for r in ranks) and hand.is_double_suited():
            return True
            
        return False
        
    def get_starting_hand_tier(self, hole_cards: List[Card]) -> int:
        """
        Get starting hand tier (1-5, 1 is best)
        
        Tier 1: Premium (top 5%)
        Tier 2: Strong (5-15%)
        Tier 3: Playable (15-30%)
        Tier 4: Marginal (30-50%)
        Tier 5: Trash (50%+)
        """
        hand = OmahaHand(hole_cards)
        ranks = sorted([c.rank for c in hole_cards], reverse=True)
        
        # Tier 1: Premium
        if self.is_premium_starting_hand(hole_cards):
            return 1
            
        # Tier 2: Strong
        if hand.is_double_suited() or (hand.is_rundown() and ranks[0] >= 9):
            return 2
            
        # Tier 3: Playable
        if hand.is_single_suited() and len(hand.get_high_cards()) >= 2:
            return 3
            
        # Tier 4: Marginal
        if hand.is_single_suited() or hand.is_rundown():
            return 4
            
        # Tier 5: Trash
        return 5


# === Standalone Test ===
if __name__ == "__main__":
    from termcolor import cprint
    
    cprint("\n=== Omaha Variant Test ===\n", "cyan", attrs=['bold'])
    
    omaha = OmahaVariant()
    
    # Test hand evaluation
    cprint("Hand Evaluation:", "yellow")
    
    # Premium PLO hand
    hole = [
        Card(Rank.ACE, Suit.SPADES),
        Card(Rank.ACE, Suit.HEARTS), 
        Card(Rank.KING, Suit.SPADES),
        Card(Rank.KING, Suit.HEARTS)
    ]
    board = [
        Card(Rank.QUEEN, Suit.DIAMONDS),
        Card(Rank.JACK, Suit.CLUBS),
        Card(Rank.TEN, Suit.HEARTS)
    ]
    
    hand_obj = OmahaHand(hole)
    cprint(f"  Hand: {hand_obj.pretty()}", "white")
    cprint(f"  Double Suited: {hand_obj.is_double_suited()}", "cyan")
    cprint(f"  Premium: {omaha.is_premium_starting_hand(hole)}", "green")
    
    result = omaha.evaluate(hole, board)
    cprint(f"  Made Hand: {result.description}", "green")
    
    print()
    cprint("Hand Analysis:", "yellow")
    analysis = omaha.analyze_hand_strength(hole, board)
    for key, value in analysis.items():
        cprint(f"  {key}: {value}", "white")
        
    print()
    cprint("Starting Hand Tiers:", "yellow")
    test_hands = [
        "AhAsKhKs",  # Premium double suited aces
        "KsQsJhTh",  # Rundown double suited
        "AhKdQcJc",  # Single suited broadway
        "9h8h7c6c",  # Rundown double suited low
        "AhKd5c2s",  # Trash
    ]
    
    for hand_str in test_hands:
        hand = OmahaHand.from_string(hand_str)
        tier = omaha.get_starting_hand_tier(hand.cards)
        cprint(f"  {hand_str}: Tier {tier}", "white")
        
    print()
    cprint("Pot Limit Betting:", "yellow")
    pot = 100
    facing_bet = 50
    max_raise = omaha.pot_limit_max_bet(pot, facing_bet)
    cprint(f"  Pot: ${pot}, Facing: ${facing_bet}", "white")
    cprint(f"  Max Pot Raise: ${max_raise}", "green")
