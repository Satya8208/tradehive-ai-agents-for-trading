"""
Dealer speech and phase-message helpers.

The actual dealing/hit-to-17 logic lives inside LiveTable (so the shoe and
event log stay in one place). This module only provides the flavor text the
dealer "says" at each phase — used by the frontend to render speech bubbles.
"""

from __future__ import annotations

import random
from typing import List


_BETTING_LINES: List[str] = [
    "Place your bets, please.",
    "Bets, please.",
    "Place your bets.",
    "Come on in, place your bets.",
]

_NO_MORE_BETS_LINES: List[str] = [
    "No more bets.",
    "Bets are closed.",
    "Good luck, everyone.",
]

_INSURANCE_LINES: List[str] = [
    "Insurance is open.",
    "Insurance?",
    "Any insurance?",
]

_PEEK_LINES_ACE: List[str] = [
    "Dealer checks under the ace.",
    "Checking the hole card.",
]

_PEEK_LINES_TEN: List[str] = [
    "Dealer peeks under the ten.",
    "Checking for blackjack.",
]

_ACTION_LINES: List[str] = [
    "Your play.",
    "Action is on you.",
    "Play your hand.",
]

_SHUFFLE_LINES: List[str] = [
    "Shuffling the shoe.",
    "Fresh shoe coming up.",
    "Shuffle, please.",
]


def betting_line() -> str:
    return random.choice(_BETTING_LINES)


def no_more_bets_line() -> str:
    return random.choice(_NO_MORE_BETS_LINES)


def insurance_line() -> str:
    return random.choice(_INSURANCE_LINES)


def peek_line(upcard: str) -> str:
    if upcard == "A":
        return random.choice(_PEEK_LINES_ACE)
    return random.choice(_PEEK_LINES_TEN)


def action_line() -> str:
    return random.choice(_ACTION_LINES)


def shuffle_line() -> str:
    return random.choice(_SHUFFLE_LINES)


def dealer_final_line(value: int, is_bust: bool, is_blackjack: bool) -> str:
    if is_blackjack:
        return "Dealer has blackjack."
    if is_bust:
        return f"Dealer busts at {value}."
    return f"Dealer stands on {value}."
