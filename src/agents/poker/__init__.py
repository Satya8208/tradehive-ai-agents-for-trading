"""
Poker God Agent - Elite poker advisor with GTO + exploitative play
Supports Texas Hold'em and Omaha, Cash Games and Tournaments
Built with love by TradeHive
"""

from .poker_agent import PokerAgent
from .core.poker_types import GameMode, GameFormat, Variant
# from .game_engine import GameEngine # Commented out if not exists
# from .training_mode import TrainingMode
# from .dashboard import Dashboard

__all__ = [
    'PokerAgent',
    'GameMode',
    'GameFormat',
    'Variant',
    # 'GameEngine',
    # 'TrainingMode',
    # 'Dashboard',
]
__version__ = '1.0.0'
