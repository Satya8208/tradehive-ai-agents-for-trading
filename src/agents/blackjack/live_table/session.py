"""
TableSession — in-memory wrapper owned by the FastAPI backend.

One session per browser. Holds the LiveTable, the human's bankroll across
rounds, and a small hand-history buffer. Between rounds it also refreshes
the NPC roster (random sit-downs and walk-offs) so the "opponents sometimes
change" feel matches a real casino.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from .table import LiveTable, RoundPhase
from .npc_player import NPCProfile, make_roster
from .dealer import betting_line, insurance_line, no_more_bets_line


class TableSession:
    """Holds one LiveTable + per-session NPC roster and history."""

    def __init__(
        self,
        num_seats: int = 5,
        human_seat_index: int = 2,
        starting_bankroll: float = 1000.0,
        min_bet: float = 25.0,
        max_bet: float = 500.0,
        bet_increment: float = 5.0,
    ) -> None:
        self.num_seats = num_seats
        self.human_seat_index = human_seat_index
        self.min_bet = min_bet
        self.max_bet = max_bet
        self.bet_increment = bet_increment
        self.starting_bankroll = starting_bankroll

        # Default US casino-floor shoe game.
        from src.agents.blackjack.game_engine import GameRules
        self.rules = GameRules(
            num_decks=8,
            dealer_hits_soft_17=True,
            blackjack_pays=1.5,
            double_after_split=True,
            resplit_aces=False,
            hit_split_aces=False,
            late_surrender=True,
            max_splits=3,
            penetration=0.75,
        )
        self.table = LiveTable(
            rules=self.rules,
            num_seats=num_seats,
            human_seat_index=human_seat_index,
        )
        self.table.seat_human(name="YOU", bankroll=starting_bankroll)

        # Create initial NPC roster (fill every seat except the human's)
        self._npc_roster: Dict[int, NPCProfile] = {}
        self._initial_seat_npcs()

        self.history: List[Dict[str, Any]] = []  # last N rounds

        # Kick off the first betting phase so the UI has something to render
        self.table.start_betting()
        self.table.message = betting_line()
        self.table._emit("message", text=self.table.message)

    # ----------------------------------------------------------- NPC roster
    def _seat_indices(self) -> List[int]:
        return [i for i in range(self.num_seats) if i != self.human_seat_index]

    def _initial_seat_npcs(self) -> None:
        indices = self._seat_indices()
        roster = make_roster(len(indices))
        for seat_idx, profile in zip(indices, roster):
            self._npc_roster[seat_idx] = profile
            self.table.seat_npc(seat_idx, profile.name, profile.bankroll)

    def refresh_roster_between_rounds(self) -> None:
        """
        Between rounds: each NPC may walk away, and empty seats may fill.
        Matches the 'opponents sometimes change' feel of a live table.
        """
        busted_out: set[int] = set()

        # Walk-offs based on stickiness
        for seat_idx, profile in list(self._npc_roster.items()):
            seat = self.table.seats[seat_idx]
            profile.bankroll = round(seat.bankroll, 2)
            if profile.bankroll < self.min_bet:
                self.table.clear_seat(seat_idx)
                del self._npc_roster[seat_idx]
                busted_out.add(seat_idx)
                continue
            if random.random() > profile.stickiness:
                self.table.clear_seat(seat_idx)
                del self._npc_roster[seat_idx]

        # Fill a random number of empty NPC seats
        empty = [
            i for i in self._seat_indices()
            if i not in self._npc_roster and i not in busted_out
        ]
        if empty:
            new_count = random.randint(0, len(empty))
            if new_count:
                new_profiles = make_roster(new_count)
                for seat_idx, profile in zip(random.sample(empty, new_count), new_profiles):
                    self._npc_roster[seat_idx] = profile
                    self.table.seat_npc(seat_idx, profile.name, profile.bankroll)

    def _bet_step_ok(self, amount: float) -> bool:
        cents = round(amount * 100)
        step_cents = round(self.bet_increment * 100)
        return cents % step_cents == 0

    def _auto_bet_npcs(self) -> None:
        for seat_idx, profile in self._npc_roster.items():
            seat = self.table.seats[seat_idx]
            if not seat.is_active or seat.bet > 0:
                continue
            profile.bankroll = round(seat.bankroll, 2)
            if profile.bankroll < self.min_bet:
                continue
            self.table.place_bet(
                seat_idx,
                profile.choose_bet(min_bet=self.min_bet, max_bet=self.max_bet),
            )

    # ---------------------------------------------------------- round control
    def start_round(self, human_bet: float) -> None:
        """
        Human has placed their bet and clicked DEAL. Auto-bet NPCs,
        deal initial cards, and advance as far as we can without human input.
        """
        if self.table.phase != RoundPhase.BETTING:
            raise ValueError("round is already in progress")

        human_seat = self.table.seats[self.human_seat_index]
        if human_bet <= 0:
            raise ValueError("bet must be greater than 0")
        if human_bet < self.min_bet:
            raise ValueError(f"minimum bet is ${self.min_bet:.2f}")
        if human_bet > self.max_bet:
            raise ValueError(f"maximum bet is ${self.max_bet:.2f}")
        if not self._bet_step_ok(human_bet):
            raise ValueError(f"bets must be in ${self.bet_increment:.0f} increments")
        if human_bet > human_seat.bankroll:
            raise ValueError("insufficient bankroll for that bet")

        self.table.place_bet(self.human_seat_index, human_bet)
        self._auto_bet_npcs()
        self.table.message = no_more_bets_line()
        self.table._emit("message", text=self.table.message)
        self.table.deal_initial()
        if self.table.phase == RoundPhase.INSURANCE:
            self.table.message = insurance_line()
            self.table._emit("message", text=self.table.message)
        elif self.table.phase == RoundPhase.PLAYER_TURN:
            self.table.play_npcs_until_human_or_end()

    def resolve_insurance(self, human_takes_insurance: bool) -> None:
        self.table.resolve_insurance(human_takes_insurance)
        if self.table.phase == RoundPhase.PLAYER_TURN:
            self.table.play_npcs_until_human_or_end()

    def human_action(self, action: str) -> None:
        self.table.human_action(action)

    def next_round(self) -> None:
        """Called after a round is settled — refresh roster and start betting."""
        if self.table.phase not in (RoundPhase.PAYOUT, RoundPhase.SETTLE):
            return
        # Snapshot results into history
        human_seat = self.table.seats[self.human_seat_index]
        self.history.append({
            "hand_number": self.table.hand_number,
            "bet": human_seat.bet,
            "results": [{"outcome": o, "payout": p} for o, p in human_seat.results],
            "session_pnl": round(self.table.session_pnl, 2),
        })
        if len(self.history) > 50:
            self.history = self.history[-50:]

        self.refresh_roster_between_rounds()
        self.table.start_betting()
        self.table.message = betting_line()
        self.table._emit("message", text=self.table.message)

    # ----------------------------------------------------------- API output
    def snapshot(self) -> Dict[str, Any]:
        snap = self.table.snapshot()
        snap["min_bet"] = self.min_bet
        snap["max_bet"] = self.max_bet
        snap["bet_increment"] = self.bet_increment
        snap["history"] = self.history[-10:]
        return snap

    def drain_events(self) -> List[Dict[str, Any]]:
        return self.table.drain_events()
