"""
Blackjack God Agent - Elite blackjack player with advanced card counting
Built with love by TradeHive

Usage:
    # Simulation mode
    python -m src.agents.blackjack.blackjack_agent --mode simulation

    # Advisor mode (manual input)
    python -m src.agents.blackjack.blackjack_agent --mode advisor

    # Training mode
    python -m src.agents.blackjack.training_mode
"""

from .card_counter import CardCounter, MultiSystemCounter
from .strategy_engine import StrategyEngine, BasicStrategy
from .game_engine import BlackjackSimulator, Deck, Hand, GameRules
from .betting_manager import BettingManager, BettingConfig
from .voice_announcer import VoiceAnnouncer
from .dashboard import Dashboard, GameDisplay

__all__ = [
    # Main agent
    'BlackjackAgent',
    # Card counting
    'CardCounter',
    'MultiSystemCounter',
    # Strategy
    'StrategyEngine',
    'BasicStrategy',
    # Game simulation
    'BlackjackSimulator',
    'Deck',
    'Hand',
    'GameRules',
    # Betting
    'BettingManager',
    'BettingConfig',
    # UI
    'VoiceAnnouncer',
    'Dashboard',
    'GameDisplay',
]

# Lazy import of main agent to avoid circular imports
def __getattr__(name):
    if name == 'BlackjackAgent':
        from .blackjack_agent import BlackjackAgent
        return BlackjackAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
