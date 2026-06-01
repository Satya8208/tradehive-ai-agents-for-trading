"""
Poker Types - Shared Enums and Constants
Built with love by TradeHive
"""

from enum import Enum, IntEnum

class Position(IntEnum):
    """Table positions (lower = earlier position)"""
    UTG = 0      # Under the Gun
    UTG1 = 1     # UTG+1
    UTG2 = 2     # UTG+2 (for 9-handed)
    MP = 3       # Middle Position
    MP2 = 4      # MP+1
    HJ = 5       # Hijack (MP+2)
    CO = 6       # Cutoff
    BTN = 7      # Button
    SB = 8       # Small Blind
    BB = 9       # Big Blind

class Street(Enum):
    """Betting rounds"""
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"

class GameMode(Enum):
    """Game modes"""
    ADVISOR = "advisor"           # Real-time advice
    TRAINING = "training"         # Practice drills
    SIMULATION = "simulation"     # Full game simulation

class GameFormat(Enum):
    """Game formats"""
    CASH = "cash"
    TOURNAMENT = "tournament"

class Variant(Enum):
    """Poker variants"""
    HOLDEM = "holdem"
    OMAHA = "omaha"

class Action(Enum):
    """Generic Poker Actions"""
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"
    ALL_IN = "all_in"

class PostflopAction(Enum):
    """Possible postflop actions"""
    CHECK = "check"
    BET_SMALL = "bet_small"      # 25-33% pot
    BET_MEDIUM = "bet_medium"    # 50-66% pot
    BET_LARGE = "bet_large"      # 75-100% pot
    BET_OVERBET = "bet_overbet"  # 100%+ pot
    CALL = "call"
    RAISE = "raise"
    CHECK_RAISE = "check_raise"
    FOLD = "fold"
    ALL_IN = "all_in"
