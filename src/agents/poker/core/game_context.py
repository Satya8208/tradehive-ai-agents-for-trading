"""
Game Context - The Unified State of the Poker God
Holds the entire world state for easier passing between engines.
Built with love by TradeHive
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from .poker_types import Position, Street, GameMode, GameFormat, Variant
from .hand_evaluator import Card
from .range_manager import Range

@dataclass
class HandState:
    """Current hand state"""
    hole_cards: List[Card] = field(default_factory=list)
    board: List[Card] = field(default_factory=list)
    pot_size: float = 0.0
    bet_to_call: float = 0.0
    position: Position = Position.BTN
    street: Street = Street.PREFLOP
    villain_range: Optional[Range] = None
    num_players: int = 2
    effective_stack: float = 100.0

@dataclass
class SessionStats:
    """Session statistics"""
    hands_played: int = 0
    hands_won: int = 0
    total_profit: float = 0.0
    vpip: int = 0
    pfr: int = 0
    three_bet: int = 0
    showdowns: int = 0
    showdown_wins: int = 0
    biggest_pot_won: float = 0.0
    biggest_pot_lost: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.hands_won / self.hands_played if self.hands_played > 0 else 0

    @property
    def bb_per_100(self) -> float:
        return (self.total_profit / self.hands_played * 100) if self.hands_played > 0 else 0

@dataclass
class TournamentState:
    """Tournament-specific state"""
    buy_in: float = 0.0
    current_level: int = 1
    blinds: tuple = (25, 50)
    ante: int = 0
    players_remaining: int = 100
    total_players: int = 100
    payouts: List[float] = field(default_factory=list)
    our_stack: int = 10000
    average_stack: float = 10000
    is_bubble: bool = False

@dataclass
class GameContext:
    """
    The Single Source of Truth for the Poker Agent.
    Passed to all engines to provide full context.
    """
    hand_state: HandState = field(default_factory=HandState)
    session_stats: SessionStats = field(default_factory=SessionStats)
    tournament_state: Optional[TournamentState] = None
    
    # Configuration
    mode: GameMode = GameMode.ADVISOR
    game_format: GameFormat = GameFormat.CASH
    variant: Variant = Variant.HOLDEM
    starting_stack: float = 100.0
    
    # Metadata
    session_id: str = ""
    opponents: Dict[str, Any] = field(default_factory=dict)  # Map name -> PlayerStats
