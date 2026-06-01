"""
Casino Profiles — Preset game conditions for autoresearch optimization

Locks certain parameters when a profile is selected, so the optimizer
only searches over betting/counting params (not game rules).

Usage:
    from .casino_profiles import CASINO_PROFILES, apply_profile
"""

from copy import deepcopy
from typing import Dict, Tuple


# Each profile locks game-condition params to realistic values
#
# Research findings (March 2026):
#
# PROVABLY FAIR / RNG (Stake Originals, BC.Game, Shuffle Originals):
#   - Infinite/unlimited deck — cards drawn from infinite shoe, no depletion
#   - Deck reshuffled every hand (or infinite deck = same thing)
#   - Card counting is IMPOSSIBLE — probabilities never change
#   - Stake: 0.57% house edge, S17, 3:2 BJ, DAS, no surrender, no resplit aces
#
# LIVE DEALER (Evolution Gaming — used by Stake, Shuffle, Cloudbet, Roobet, etc.):
#   - 8 decks, shuffle at ~50% pen (cutting card after ~4 decks)
#   - Dealer stands all 17s (S17)
#   - 3:2 blackjack, double on any 2 cards, DAS allowed
#   - One split only, no hit split aces, no surrender
#   - House edge ~0.49% with basic strategy
#   - RTP: 99.47% (standard), 99.29% (Speed BJ)
#
# LIVE DEALER (Pragmatic Play — used by Stake, Shuffle, Rainbet, etc.):
#   - 8 decks, shuffle at ~50% pen (same as Evolution)
#   - Dealer stands all 17s (S17)
#   - DAS allowed except split aces
#   - RTP: 99.28%
#
# EVOLUTION INFINITE BLACKJACK (unlimited seats, low stakes):
#   - 8 decks, S17, 3:2 BJ, double any 2 cards
#   - NO DAS, one split only, no hit split aces, no surrender
#   - Six Card Charlie (auto-win with 6 cards <= 21)
#   - RTP: 99.47%, house edge 0.53%
#
# KEY FINDING: ALL live dealer blackjack at crypto casinos uses 8 decks
# with ~50% penetration. The only variable is which provider (Evolution
# vs Pragmatic) and minor rule differences (DAS, side bets).
# RNG/provably fair games use infinite decks = counting impossible.

CASINO_PROFILES: Dict[str, Dict] = {
    # === YOUR CASINO ===
    "coin_casino": {
        "description": "Coin Casino — 8 decks, shuffle after 4 (50% pen), no surrender",
        "num_decks": 8,
        "penetration": 0.50,
        "dealer_hits_soft_17": False,  # S17 (stands on soft 17)
        "blackjack_pays": 1.5,
        "late_surrender": False,
        "double_after_split": True,
    },

    # === LIVE DEALER (Evolution Gaming) ===
    # Used by: Stake, Shuffle, Cloudbet, Roobet, BC.Game, Duelbits, Metaspins
    "evo_live": {
        "description": "Evolution Live BJ — 8 decks, 50% pen, S17, DAS, no surrender",
        "num_decks": 8,
        "penetration": 0.50,
        "dealer_hits_soft_17": False,  # S17
        "blackjack_pays": 1.5,
        "late_surrender": False,
        "double_after_split": True,
    },

    # === LIVE DEALER (Pragmatic Play) ===
    # Used by: Stake, Shuffle, Rainbet
    "pragma_live": {
        "description": "Pragmatic Live BJ — 8 decks, 50% pen, S17, DAS, no surrender",
        "num_decks": 8,
        "penetration": 0.50,
        "dealer_hits_soft_17": False,  # S17
        "blackjack_pays": 1.5,
        "late_surrender": False,
        "double_after_split": True,
    },

    # === EVOLUTION INFINITE BLACKJACK ===
    # Unlimited seats, low stakes — available at most crypto casinos
    "evo_infinite": {
        "description": "Evolution Infinite BJ — 8 decks, 50% pen, S17, NO DAS, Six Card Charlie",
        "num_decks": 8,
        "penetration": 0.50,
        "dealer_hits_soft_17": False,  # S17
        "blackjack_pays": 1.5,
        "late_surrender": False,
        "double_after_split": False,  # NO DAS on Infinite
    },

    # === REFERENCE: GOOD LIVE CONDITIONS ===
    "live_75pen": {
        "description": "Live casino — 8 decks, 75% penetration (rare, best case)",
        "num_decks": 8,
        "penetration": 0.75,
        "dealer_hits_soft_17": False,
        "blackjack_pays": 1.5,
        "late_surrender": True,
        "double_after_split": True,
    },
}

# Params that each profile locks (removes from search spaces)
LOCKED_CONTINUOUS = {"penetration"}
LOCKED_DISCRETE = {"num_decks", "dealer_hits_soft_17"}


def apply_profile(
    params,
    profile_name: str,
    search_space: Dict[str, Tuple[float, float]],
    discrete_space: Dict[str, list],
) -> Tuple[Dict[str, Tuple[float, float]], Dict[str, list]]:
    """
    Apply a casino profile to a BJParamSet and return modified search spaces.

    Sets the locked params on the BJParamSet object, then removes them from
    the search spaces so the optimizer won't mutate them.

    Returns:
        (filtered_search_space, filtered_discrete_space)
    """
    if profile_name not in CASINO_PROFILES:
        raise ValueError(f"Unknown profile: {profile_name}. "
                         f"Available: {list(CASINO_PROFILES.keys())}")

    profile = CASINO_PROFILES[profile_name]

    # Apply profile values to params
    for key, value in profile.items():
        if key == "description":
            continue
        if hasattr(params, key):
            setattr(params, key, value)

    # Remove locked params from search spaces
    filtered_search = {k: v for k, v in search_space.items() if k not in LOCKED_CONTINUOUS}
    filtered_discrete = {k: v for k, v in discrete_space.items() if k not in LOCKED_DISCRETE}

    return filtered_search, filtered_discrete
