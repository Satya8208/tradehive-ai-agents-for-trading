"""
Poker variant implementations
- Texas Hold'em
- Omaha (PLO)
"""

from .holdem import HoldemVariant
from .omaha import OmahaVariant

__all__ = [
    'HoldemVariant',
    'OmahaVariant'
]
