"""
NPC player roster for the live blackjack table.

Each NPC has a name, a bankroll, and a base-bet preference. Their in-hand
decisions are driven entirely by the existing StrategyEngine (basic strategy),
so they play honest, predictable casino blackjack — no cheating, no counting.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List


NPC_NAMES = [
    "Bob", "Maria", "Ken", "Sasha", "Dmitri", "Yuki", "Luca", "Priya",
    "Omar", "Chen", "Ana", "Tariq", "Elena", "Marcus", "Nadia", "Hiro",
    "Rosa", "Felix", "Zara", "Kai",
]


@dataclass
class NPCProfile:
    """One NPC seating at the table. Bankroll and bet preferences only."""
    name: str
    bankroll: float
    base_bet: float   # preferred flat bet size
    stickiness: float  # 0..1 — probability of staying seated each round

    def choose_bet(self, min_bet: float, max_bet: float) -> float:
        """Flat bet with slight jitter so the table doesn't feel robotic."""
        jitter = random.uniform(0.8, 1.25)
        amount = self.base_bet * jitter
        # Snap to the nearest $5 chip
        amount = max(min_bet, min(amount, max_bet, self.bankroll))
        amount = round(amount / 5.0) * 5.0
        return max(min_bet, amount)


def make_roster(count: int) -> List[NPCProfile]:
    """Generate a fresh batch of NPC profiles for occupying seats."""
    names = random.sample(NPC_NAMES, k=min(count, len(NPC_NAMES)))
    roster: List[NPCProfile] = []
    for name in names:
        base_bet = random.choice([25.0, 25.0, 50.0, 50.0, 75.0, 100.0, 150.0])
        bankroll = random.uniform(600.0, 6000.0)
        stickiness = random.uniform(0.7, 0.96)
        roster.append(NPCProfile(
            name=name,
            bankroll=round(bankroll, 2),
            base_bet=base_bet,
            stickiness=stickiness,
        ))
    return roster
