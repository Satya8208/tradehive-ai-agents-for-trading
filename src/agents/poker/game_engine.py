"""
Game Engine - Full poker game simulation
The stage where the Poker God performs
Built with love by TradeHive
"""

import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Callable
from enum import Enum
import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agents.poker.core.hand_evaluator import (
    HandEvaluator, Card, Deck, Rank, Suit, HandResult
)
from src.agents.poker.strategy.preflop_engine import Position


class Action(Enum):
    """Player actions"""
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"
    ALL_IN = "all_in"


class Street(Enum):
    """Betting streets"""
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"


@dataclass
class Player:
    """Player at the table"""
    name: str
    stack: float
    seat: int
    is_human: bool = False
    is_sitting_out: bool = False
    hole_cards: List[Card] = field(default_factory=list)
    bet_this_round: float = 0.0
    is_all_in: bool = False
    has_folded: bool = False
    
    def reset_for_hand(self):
        """Reset player state for new hand"""
        self.hole_cards = []
        self.bet_this_round = 0.0
        self.is_all_in = False
        self.has_folded = False


@dataclass
class Pot:
    """Pot tracking (handles side pots)"""
    amount: float = 0.0
    eligible_players: List[str] = field(default_factory=list)
    

@dataclass
class HandHistory:
    """Record of a completed hand"""
    hand_number: int
    players: List[str]
    hole_cards: Dict[str, List[Card]]
    board: List[Card]
    actions: List[Dict]
    pot: float
    winners: List[str]
    amounts_won: Dict[str, float]
    

class GameEngine:
    """
    Full poker game simulator
    
    Handles:
    - Dealing cards
    - Betting rounds
    - Pot calculation (including side pots)
    - Showdown and winner determination
    - Hand history tracking
    """
    
    def __init__(self, num_seats: int = 9, small_blind: float = 0.5,
                 big_blind: float = 1.0, ante: float = 0.0):
        """
        Initialize game engine
        
        Args:
            num_seats: Table size (2-10)
            small_blind: Small blind amount
            big_blind: Big blind amount
            ante: Ante per player (0 for no ante)
        """
        self.num_seats = num_seats
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.ante = ante
        
        self.players: Dict[int, Player] = {}
        self.button_seat = 0
        self.hand_number = 0
        self.hand_evaluator = HandEvaluator()
        
        # Current hand state
        self.deck: Optional[Deck] = None
        self.board: List[Card] = []
        self.pots: List[Pot] = []
        self.current_bet: float = 0
        self.min_raise: float = big_blind
        self.street: Street = Street.PREFLOP
        self.action_on: int = 0
        self.last_aggressor: int = -1
        
        # Hand history
        self.current_actions: List[Dict] = []
        self.hand_histories: List[HandHistory] = []
        
    def add_player(self, name: str, seat: int, stack: float, is_human: bool = False) -> Player:
        """Add a player to the table"""
        if seat < 0 or seat >= self.num_seats:
            raise ValueError(f"Invalid seat {seat}")
        if seat in self.players:
            raise ValueError(f"Seat {seat} already occupied")
            
        player = Player(name=name, stack=stack, seat=seat, is_human=is_human)
        self.players[seat] = player
        return player
        
    def remove_player(self, seat: int):
        """Remove a player from the table"""
        if seat in self.players:
            del self.players[seat]
            
    def get_active_players(self) -> List[Player]:
        """Get players still in the hand"""
        return [p for p in self.players.values() 
                if not p.has_folded and not p.is_sitting_out]
                
    def get_players_with_cards(self) -> List[Player]:
        """Get players who haven't folded"""
        return [p for p in self.players.values()
                if not p.has_folded and p.hole_cards]
                
    def _get_next_seat(self, seat: int, include_folded: bool = False) -> int:
        """Get next occupied seat"""
        for i in range(1, self.num_seats + 1):
            next_seat = (seat + i) % self.num_seats
            if next_seat in self.players:
                player = self.players[next_seat]
                if include_folded or (not player.has_folded and not player.is_all_in):
                    return next_seat
        return seat
        
    def _get_position(self, seat: int) -> Position:
        """Get position name for a seat"""
        active_seats = sorted([s for s in self.players.keys() 
                              if not self.players[s].is_sitting_out])
        n = len(active_seats)
        
        if n <= 2:
            return Position.BTN if seat == self.button_seat else Position.BB
            
        btn_idx = active_seats.index(self.button_seat) if self.button_seat in active_seats else 0
        seat_idx = active_seats.index(seat) if seat in active_seats else 0
        
        relative_pos = (seat_idx - btn_idx) % n
        
        # Map to positions
        if relative_pos == 0:
            return Position.BTN
        elif relative_pos == 1:
            return Position.SB
        elif relative_pos == 2:
            return Position.BB
        elif relative_pos == n - 1:
            return Position.CO
        elif relative_pos == n - 2:
            return Position.HJ
        else:
            return Position.MP
            
    def start_hand(self):
        """Start a new hand"""
        self.hand_number += 1
        self.deck = Deck()
        self.deck.shuffle()
        self.board = []
        self.pots = [Pot(amount=0, eligible_players=[p.name for p in self.get_active_players()])]
        self.current_bet = 0
        self.min_raise = self.big_blind
        self.street = Street.PREFLOP
        self.current_actions = []
        self.last_aggressor = -1
        
        # Reset players
        for player in self.players.values():
            player.reset_for_hand()
            
        # Post blinds and antes
        self._post_blinds()
        
        # Deal hole cards
        self._deal_hole_cards()
        
        # Set action on UTG (or SB for heads-up)
        if len(self.get_active_players()) == 2:
            self.action_on = self.button_seat
        else:
            bb_seat = self._get_next_seat(self._get_next_seat(self.button_seat))
            self.action_on = self._get_next_seat(bb_seat)
            
    def _post_blinds(self):
        """Post blinds and antes"""
        active = self.get_active_players()
        
        # Collect antes
        for player in active:
            if self.ante > 0:
                ante_amount = min(self.ante, player.stack)
                player.stack -= ante_amount
                self.pots[0].amount += ante_amount
                
        # Small blind
        if len(active) == 2:
            sb_seat = self.button_seat
        else:
            sb_seat = self._get_next_seat(self.button_seat)
            
        sb_player = self.players.get(sb_seat)
        if sb_player:
            sb_amount = min(self.small_blind, sb_player.stack)
            sb_player.stack -= sb_amount
            sb_player.bet_this_round = sb_amount
            self.pots[0].amount += sb_amount
            
        # Big blind
        bb_seat = self._get_next_seat(sb_seat)
        bb_player = self.players.get(bb_seat)
        if bb_player:
            bb_amount = min(self.big_blind, bb_player.stack)
            bb_player.stack -= bb_amount
            bb_player.bet_this_round = bb_amount
            self.pots[0].amount += bb_amount
            self.current_bet = bb_amount
            
    def _deal_hole_cards(self):
        """Deal hole cards to all players"""
        for player in self.get_active_players():
            player.hole_cards = self.deck.deal(2)
            
    def deal_flop(self):
        """Deal the flop"""
        self.deck.deal(1)  # Burn
        self.board.extend(self.deck.deal(3))
        self.street = Street.FLOP
        self._reset_betting_round()
        
    def deal_turn(self):
        """Deal the turn"""
        self.deck.deal(1)  # Burn
        self.board.extend(self.deck.deal(1))
        self.street = Street.TURN
        self._reset_betting_round()
        
    def deal_river(self):
        """Deal the river"""
        self.deck.deal(1)  # Burn
        self.board.extend(self.deck.deal(1))
        self.street = Street.RIVER
        self._reset_betting_round()
        
    def _reset_betting_round(self):
        """Reset for new betting round"""
        for player in self.players.values():
            player.bet_this_round = 0
        self.current_bet = 0
        self.min_raise = self.big_blind
        
        # Action starts left of button (or first active player)
        self.action_on = self._get_next_seat(self.button_seat)
        
    def process_action(self, seat: int, action: Action, amount: float = 0) -> bool:
        """
        Process a player action
        
        Args:
            seat: Player's seat
            action: The action taken
            amount: Amount for bet/raise
            
        Returns:
            True if action was valid
        """
        if seat not in self.players:
            return False
            
        player = self.players[seat]
        
        if player.has_folded or player.is_all_in:
            return False
            
        # Record action
        action_record = {
            'seat': seat,
            'player': player.name,
            'action': action.value,
            'amount': amount,
            'street': self.street.value
        }
        self.current_actions.append(action_record)
        
        if action == Action.FOLD:
            player.has_folded = True
            
        elif action == Action.CHECK:
            if self.current_bet > player.bet_this_round:
                return False  # Can't check when facing bet
                
        elif action == Action.CALL:
            call_amount = min(self.current_bet - player.bet_this_round, player.stack)
            player.stack -= call_amount
            player.bet_this_round += call_amount
            self.pots[0].amount += call_amount
            
            if player.stack == 0:
                player.is_all_in = True
                
        elif action in (Action.BET, Action.RAISE):
            if amount < self.min_raise and amount < player.stack:
                return False  # Invalid raise size (unless all-in)
                
            # Calculate total amount to put in
            to_put_in = amount - player.bet_this_round
            actual_put_in = min(to_put_in, player.stack)
            
            player.stack -= actual_put_in
            player.bet_this_round += actual_put_in
            self.pots[0].amount += actual_put_in
            
            # Update betting
            self.min_raise = max(self.min_raise, amount - self.current_bet)
            self.current_bet = player.bet_this_round
            self.last_aggressor = seat
            
            if player.stack == 0:
                player.is_all_in = True
                
        elif action == Action.ALL_IN:
            all_in_amount = player.stack
            player.bet_this_round += all_in_amount
            player.stack = 0
            player.is_all_in = True
            self.pots[0].amount += all_in_amount
            
            if player.bet_this_round > self.current_bet:
                self.min_raise = max(self.min_raise, player.bet_this_round - self.current_bet)
                self.current_bet = player.bet_this_round
                self.last_aggressor = seat
                
        # Move action
        self.action_on = self._get_next_seat(seat)
        
        return True
        
    def is_betting_complete(self) -> bool:
        """Check if betting round is complete"""
        active = [p for p in self.get_active_players() if not p.is_all_in]
        
        if len(active) <= 1:
            return True
            
        # All active players must have matched the current bet
        for player in active:
            if player.bet_this_round < self.current_bet:
                return False
                
        # Action must have gone around at least once
        return self.action_on == self.last_aggressor or self.last_aggressor == -1
        
    def is_hand_complete(self) -> bool:
        """Check if hand is complete"""
        active = self.get_players_with_cards()
        
        # Only one player left
        if len(active) <= 1:
            return True
            
        # All-in and called
        if all(p.is_all_in or p.has_folded for p in self.players.values() if p.hole_cards):
            return True
            
        return False
        
    def determine_winners(self) -> Dict[str, float]:
        """
        Determine winners and distribute pot
        
        Returns:
            Dict mapping player name to amount won
        """
        winners = {}
        active = self.get_players_with_cards()
        
        if len(active) == 0:
            return winners
            
        if len(active) == 1:
            # Everyone else folded
            winner = active[0]
            winners[winner.name] = self.pots[0].amount
            winner.stack += self.pots[0].amount
            return winners
            
        # Showdown - evaluate hands
        hand_results = {}
        for player in active:
            result = self.hand_evaluator.evaluate(player.hole_cards, self.board)
            hand_results[player.name] = result
            
        # Find best hand(s)
        best_result = None
        best_players = []
        
        for name, result in hand_results.items():
            if best_result is None:
                best_result = result
                best_players = [name]
            else:
                comparison = self.hand_evaluator.compare(result, best_result)
                if comparison < 0:  # This hand is better
                    best_result = result
                    best_players = [name]
                elif comparison == 0:  # Tie
                    best_players.append(name)
                    
        # Distribute pot
        pot_share = self.pots[0].amount / len(best_players)
        for name in best_players:
            winners[name] = pot_share
            player = next(p for p in self.players.values() if p.name == name)
            player.stack += pot_share
            
        return winners
        
    def move_button(self):
        """Move button to next player"""
        self.button_seat = self._get_next_seat(self.button_seat, include_folded=True)
        
    def get_game_state(self) -> Dict:
        """Get current game state"""
        return {
            'hand_number': self.hand_number,
            'street': self.street.value,
            'board': [str(c) for c in self.board],
            'pot': sum(p.amount for p in self.pots),
            'current_bet': self.current_bet,
            'action_on': self.action_on,
            'players': {
                seat: {
                    'name': p.name,
                    'stack': p.stack,
                    'bet': p.bet_this_round,
                    'folded': p.has_folded,
                    'all_in': p.is_all_in,
                    'position': self._get_position(seat).name
                }
                for seat, p in self.players.items()
            }
        }
        
    def run_hand(self, get_action: Callable[[int, Dict], Tuple[Action, float]]) -> HandHistory:
        """
        Run a complete hand
        
        Args:
            get_action: Callback to get player actions
                       Takes (seat, game_state) and returns (Action, amount)
                       
        Returns:
            HandHistory for the completed hand
        """
        self.start_hand()
        
        # Preflop betting
        while not self.is_betting_complete() and not self.is_hand_complete():
            state = self.get_game_state()
            action, amount = get_action(self.action_on, state)
            self.process_action(self.action_on, action, amount)
            
        if not self.is_hand_complete():
            # Flop
            self.deal_flop()
            while not self.is_betting_complete() and not self.is_hand_complete():
                state = self.get_game_state()
                action, amount = get_action(self.action_on, state)
                self.process_action(self.action_on, action, amount)
                
        if not self.is_hand_complete():
            # Turn
            self.deal_turn()
            while not self.is_betting_complete() and not self.is_hand_complete():
                state = self.get_game_state()
                action, amount = get_action(self.action_on, state)
                self.process_action(self.action_on, action, amount)
                
        if not self.is_hand_complete():
            # River
            self.deal_river()
            while not self.is_betting_complete() and not self.is_hand_complete():
                state = self.get_game_state()
                action, amount = get_action(self.action_on, state)
                self.process_action(self.action_on, action, amount)
                
        # Showdown
        winners = self.determine_winners()
        
        # Create hand history
        history = HandHistory(
            hand_number=self.hand_number,
            players=[p.name for p in self.players.values()],
            hole_cards={p.name: p.hole_cards for p in self.players.values()},
            board=list(self.board),
            actions=self.current_actions,
            pot=sum(p.amount for p in self.pots),
            winners=list(winners.keys()),
            amounts_won=winners
        )
        
        self.hand_histories.append(history)
        self.move_button()
        
        return history


# === Standalone Test ===
if __name__ == "__main__":
    from termcolor import cprint
    
    cprint("\n=== Game Engine Test ===\n", "cyan", attrs=['bold'])
    
    # Create game
    engine = GameEngine(num_seats=6, small_blind=0.5, big_blind=1.0)
    
    # Add players
    engine.add_player("Hero", seat=0, stack=100, is_human=True)
    engine.add_player("Villain1", seat=1, stack=100)
    engine.add_player("Villain2", seat=3, stack=100)
    
    # Simple bot action function
    def bot_action(seat: int, state: Dict) -> Tuple[Action, float]:
        player_state = state['players'].get(seat, {})
        current_bet = state['current_bet']
        player_bet = player_state.get('bet', 0)
        
        # Simple logic: call or check
        if current_bet > player_bet:
            return Action.CALL, 0
        else:
            return Action.CHECK, 0
            
    # Run a hand
    cprint("Running test hand...\n", "yellow")
    
    history = engine.run_hand(bot_action)
    
    cprint(f"Hand #{history.hand_number} complete!", "green")
    cprint(f"Board: {' '.join(str(c) for c in history.board)}", "white")
    cprint(f"Pot: ${history.pot:.2f}", "white")
    cprint(f"Winners: {', '.join(history.winners)}", "green")
    
    for name, amount in history.amounts_won.items():
        cprint(f"  {name} won ${amount:.2f}", "yellow")
        
    print()
    cprint("Final stacks:", "cyan")
    for seat, player in engine.players.items():
        cprint(f"  {player.name}: ${player.stack:.2f}", "white")
