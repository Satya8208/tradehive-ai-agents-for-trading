"""
LiveTable - Multi-seat casino-style blackjack orchestrator.

Reuses Hand, Deck, GameRules, GameResult from ../game_engine.py as primitives,
and drives NPC decisions through StrategyEngine from ../strategy_engine.py.

The table owns a shared shoe across all seats + dealer, walks play in proper
casino order (seat 0 first, dealer last), and exposes an event log the
frontend uses to animate.
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Make 'src.' importable whether this is run as a module or loaded ad-hoc
_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.agents.blackjack.game_engine import Hand, Deck, GameRules  # noqa: E402
from src.agents.blackjack.card_counter import CardCounter  # noqa: E402
from src.agents.blackjack.strategy_engine import StrategyEngine  # noqa: E402
from src.agents.blackjack.strategy_engine import Hand as StratHand  # noqa: E402
from src.agents.blackjack.live_table.dealer import action_line, dealer_final_line, peek_line  # noqa: E402


TEN_VALUE_CARDS = {"10", "J", "Q", "K"}
ACTION_LABELS = {
    "H": "HIT",
    "S": "STAND",
    "D": "DOUBLE",
    "P": "SPLIT",
    "R": "SURRENDER",
}


class RoundPhase(str, Enum):
    BETTING = "betting"
    DEALING = "dealing"
    INSURANCE = "insurance"
    PLAYER_TURN = "player_turn"
    DEALER_TURN = "dealer_turn"
    PAYOUT = "payout"
    SETTLE = "settle"


@dataclass
class Seat:
    index: int
    occupant: Optional[str] = None   # None=empty, "YOU" for human, else NPC name
    is_human: bool = False
    bankroll: float = 0.0
    bet: float = 0.0                 # Initial bet placed this round
    hands: List[Hand] = field(default_factory=list)
    insurance_bet: float = 0.0
    done: bool = False               # Whole seat is finished for this round
    results: List[Tuple[str, float]] = field(default_factory=list)
    stood_hands: set = field(default_factory=set)  # hand indices that stood

    @property
    def is_active(self) -> bool:
        return self.occupant is not None


class LiveTable:
    """
    Multi-seat blackjack table with shared shoe, dealer, and event log.

    Casino-style flow:
        BETTING -> DEALING -> (INSURANCE)? -> PLAYER_TURN -> DEALER_TURN -> PAYOUT -> SETTLE
    """

    def __init__(
        self,
        rules: Optional[GameRules] = None,
        num_seats: int = 5,
        human_seat_index: int = 2,
    ) -> None:
        self.rules = rules or GameRules()
        self.num_seats = num_seats
        self.human_seat_index = human_seat_index

        # Shared shoe — this is the realistic multi-deck cut-card shoe
        self.deck = Deck(self.rules.num_decks, self.rules.penetration)

        self.seats: List[Seat] = [Seat(index=i) for i in range(num_seats)]
        self.dealer_hand: Hand = Hand()
        self.dealer_hole: Optional[str] = None

        self.phase: RoundPhase = RoundPhase.SETTLE
        self.hand_number: int = 0
        self.message: str = "Welcome to the table."
        self.events: List[Dict[str, Any]] = []
        self.tick: int = 0

        self.strategy = StrategyEngine()
        self.counter = CardCounter(system="hi_lo", num_decks=self.rules.num_decks)
        self.coach_system = "hi_lo"
        self.dealer_hole_revealed = False
        self.last_feedback: Optional[Dict[str, Any]] = None

        # Session stats for the human
        self.session_pnl: float = 0.0
        self.hands_played: int = 0

    # ------------------------------------------------------------------- coach
    def _action_label(self, action_code: str) -> str:
        return ACTION_LABELS.get(action_code, action_code)

    def _count_visible_card(self, card: Optional[str]) -> None:
        if card and card != "__BACK__":
            self.counter.add_card(card)

    def _reveal_dealer_hole(self) -> None:
        if self.dealer_hole and not self.dealer_hole_revealed:
            self._count_visible_card(self.dealer_hole)
            self.dealer_hole_revealed = True
            self._emit("reveal_hole", card=self.dealer_hole)

    def _coach_count_payload(self) -> Dict[str, Any]:
        return {
            "system": self.coach_system,
            "running_count": round(self.counter.running_count, 1),
            "true_count": round(self.counter.true_count, 2),
            "decks_remaining": round(self.counter.decks_remaining, 2),
            "edge": round(self.counter.get_edge_estimate() * 100, 2),
        }

    def _build_recommendation(
        self,
        hand: Hand,
        dealer_upcard: str,
        allowed: Dict[str, bool],
    ) -> Dict[str, Any]:
        strat_hand = StratHand(cards=list(hand.cards))
        action, source = self.strategy.get_action(
            strat_hand,
            dealer_upcard,
            true_count=self.counter.true_count,
            can_double=allowed["double"],
            can_split=allowed["split"],
            can_surrender=allowed["surrender"],
            use_deviations=True,
        )
        return {
            "action": self._action_label(action),
            "action_code": action,
            "source": source,
            "hand_total": strat_hand.total,
            "is_soft": strat_hand.is_soft,
            "is_pair": strat_hand.is_pair,
            "true_count": round(self.counter.true_count, 2),
        }

    def _current_recommendation(self) -> Optional[Dict[str, Any]]:
        actor = self.current_actor()
        if not actor or actor[0] != self.human_seat_index:
            return None
        seat_idx, hand_idx = actor
        allowed = self.allowed_actions(seat_idx, hand_idx)
        hand = self.seats[seat_idx].hands[hand_idx]
        return self._build_recommendation(hand, self.dealer_hand.cards[0], allowed)

    def _insurance_recommendation(self) -> Optional[Dict[str, Any]]:
        human_seat = self.seats[self.human_seat_index]
        if self.phase != RoundPhase.INSURANCE or human_seat.bet <= 0:
            return None
        take_insurance = self.strategy.should_take_insurance(
            self.counter.true_count,
            self.coach_system,
        )
        return {
            "take_insurance": take_insurance,
            "recommended_action": "TAKE INSURANCE" if take_insurance else "NO INSURANCE",
            "action_code": "Y" if take_insurance else "N",
            "source": "insurance",
            "true_count": round(self.counter.true_count, 2),
            "system": self.coach_system,
        }

    def _set_action_feedback(
        self,
        chosen_action_code: str,
        recommendation: Optional[Dict[str, Any]],
    ) -> None:
        if not recommendation:
            self.last_feedback = None
            return
        chosen_action_code = chosen_action_code.upper()
        is_correct = chosen_action_code == recommendation["action_code"]
        tc = recommendation["true_count"]
        if is_correct:
            message = f"Correct. {recommendation['action']} was the ideal play."
        else:
            sign = "+" if tc >= 0 else ""
            message = f"Ideal was {recommendation['action']} at TC {sign}{tc:.1f}."
        self.last_feedback = {
            "decision_type": "action",
            "chosen_action": self._action_label(chosen_action_code),
            "chosen_action_code": chosen_action_code,
            "ideal_action": recommendation["action"],
            "ideal_action_code": recommendation["action_code"],
            "source": recommendation["source"],
            "is_correct": is_correct,
            "true_count": tc,
            "message": message,
        }

    def _set_insurance_feedback(self, takes_insurance: bool) -> None:
        recommendation = self._insurance_recommendation()
        if not recommendation:
            self.last_feedback = None
            return
        chosen_code = "Y" if takes_insurance else "N"
        chosen_action = "TAKE INSURANCE" if takes_insurance else "NO INSURANCE"
        is_correct = chosen_code == recommendation["action_code"]
        tc = recommendation["true_count"]
        if is_correct:
            message = f"Correct. {recommendation['recommended_action']} was the right insurance play."
        else:
            sign = "+" if tc >= 0 else ""
            message = f"Ideal was {recommendation['recommended_action']} at TC {sign}{tc:.1f}."
        self.last_feedback = {
            "decision_type": "insurance",
            "chosen_action": chosen_action,
            "chosen_action_code": chosen_code,
            "ideal_action": recommendation["recommended_action"],
            "ideal_action_code": recommendation["action_code"],
            "source": recommendation["source"],
            "is_correct": is_correct,
            "true_count": tc,
            "message": message,
        }

    # ------------------------------------------------------------------ events
    def _emit(self, type: str, **data: Any) -> None:
        self.events.append({"type": type, **data})
        self.tick += 1

    def drain_events(self) -> List[Dict[str, Any]]:
        out = self.events
        self.events = []
        return out

    # ---------------------------------------------------------- seat management
    def seat_human(self, name: str = "YOU", bankroll: float = 1000.0) -> None:
        seat = self.seats[self.human_seat_index]
        seat.occupant = name
        seat.is_human = True
        seat.bankroll = bankroll
        self._emit("seat_change", seat=seat.index, occupant=name, is_human=True,
                   bankroll=bankroll)

    def seat_npc(self, seat_index: int, name: str, bankroll: float = 500.0) -> None:
        seat = self.seats[seat_index]
        seat.occupant = name
        seat.is_human = False
        seat.bankroll = bankroll
        self._emit("seat_change", seat=seat.index, occupant=name, is_human=False,
                   bankroll=bankroll)

    def clear_seat(self, seat_index: int) -> None:
        seat = self.seats[seat_index]
        if seat.is_human:
            return
        seat.occupant = None
        seat.is_human = False
        seat.bankroll = 0.0
        seat.bet = 0.0
        seat.hands = []
        self._emit("seat_change", seat=seat.index, occupant=None, is_human=False,
                   bankroll=0.0)

    # --------------------------------------------------------------- lifecycle
    def start_betting(self) -> None:
        """Begin a new round: reset per-round state, possibly reshuffle."""
        if self.deck.needs_shuffle():
            self.deck.shuffle()
            self.counter.reset()
            self._emit("shuffle")

        self.hand_number += 1
        self.phase = RoundPhase.BETTING
        self.dealer_hand = Hand()
        self.dealer_hole = None
        self.dealer_hole_revealed = False
        self.last_feedback = None

        for seat in self.seats:
            seat.hands = []
            seat.bet = 0.0
            seat.insurance_bet = 0.0
            seat.done = False
            seat.results = []
            seat.stood_hands = set()

        self.message = "Place your bets."
        self._emit("phase", phase=self.phase.value)
        self._emit("message", text=self.message)

    def place_bet(self, seat_index: int, amount: float) -> None:
        if self.phase != RoundPhase.BETTING:
            return
        seat = self.seats[seat_index]
        if not seat.is_active:
            return
        amount = max(0.0, min(amount, seat.bankroll))
        seat.bet = amount
        seat.bankroll -= amount
        self._emit("bet_placed", seat=seat_index, amount=amount,
                   bankroll=seat.bankroll)

    def auto_bet_npcs(self, min_bet: float = 5.0, max_bet: float = 100.0) -> None:
        for seat in self.seats:
            if not seat.is_active or seat.is_human or seat.bet > 0:
                continue
            base = random.choice([10, 15, 20, 25, 50])
            base = max(min_bet, min(base, max_bet, seat.bankroll))
            self.place_bet(seat.index, base)

    def deal_initial(self) -> None:
        """Deal two cards to each occupied seat and to the dealer, casino order."""
        self.phase = RoundPhase.DEALING
        self._emit("phase", phase=self.phase.value)
        self.message = "Dealing."
        self._emit("message", text=self.message)

        active_seats = [s for s in self.seats if s.is_active and s.bet > 0]
        for seat in active_seats:
            seat.hands = [Hand(bet=seat.bet)]

        # First pass: one card to each seat, then dealer upcard
        for seat in active_seats:
            card = self.deck.deal()
            seat.hands[0].add_card(card)
            self._count_visible_card(card)
            self._emit("deal_card", seat=seat.index, hand_idx=0, card=card, hole=False)

        up = self.deck.deal()
        self.dealer_hand.add_card(up)
        self._count_visible_card(up)
        self._emit("deal_card", seat="dealer", card=up, hole=False)

        # Second pass
        for seat in active_seats:
            card = self.deck.deal()
            seat.hands[0].add_card(card)
            self._count_visible_card(card)
            self._emit("deal_card", seat=seat.index, hand_idx=0, card=card, hole=False)

        hole = self.deck.deal()
        self.dealer_hole = hole
        self.dealer_hand.add_card(hole)
        self._emit("deal_card", seat="dealer", card="__BACK__", hole=True)

        if up == "A":
            self.phase = RoundPhase.INSURANCE
            self.message = "Insurance?"
            self._emit("phase", phase=self.phase.value)
            self._emit("message", text=self.message)
        else:
            if up in TEN_VALUE_CARDS:
                self._emit("message", text=peek_line(up))
            self._after_naturals_check()

    def resolve_insurance(self, human_takes_insurance: bool) -> None:
        if self.phase != RoundPhase.INSURANCE:
            return
        self._set_insurance_feedback(human_takes_insurance)
        for seat in self.seats:
            if not seat.is_active or seat.bet == 0:
                continue
            if seat.is_human and human_takes_insurance:
                ins = min(seat.bet / 2, seat.bankroll)
                seat.insurance_bet = ins
                seat.bankroll -= ins
                self._emit("insurance_placed", seat=seat.index, amount=ins)
        self._emit("message", text=peek_line("A"))
        self._after_naturals_check()

    def _after_naturals_check(self) -> None:
        """Check dealer blackjack; either settle immediately or move to player turns."""
        if self.dealer_hand.is_blackjack:
            self._reveal_dealer_hole()
            self.message = "Dealer has blackjack."
            self._emit("message", text=self.message)
            for seat in self.seats:
                if not seat.is_active or seat.bet == 0:
                    continue
                hand = seat.hands[0]
                if hand.is_blackjack:
                    outcome, payout = "PUSH", 0.0
                    seat.bankroll += seat.bet  # return bet
                else:
                    outcome, payout = "LOSE", -seat.bet
                seat.results.append((outcome, payout))
                if seat.insurance_bet > 0:
                    # Insurance pays 2:1 — profit = insurance_bet * 2, return principal too
                    seat.bankroll += seat.insurance_bet * 3
                    self._emit("insurance_won", seat=seat.index,
                               amount=seat.insurance_bet * 2)
                    seat.insurance_bet = 0.0
                seat.done = True
                self._emit("hand_result", seat=seat.index, hand_idx=0,
                           outcome=outcome, payout=payout,
                           bankroll=seat.bankroll)
                if seat.is_human:
                    self.session_pnl += payout
                    self.hands_played += 1
            self.phase = RoundPhase.PAYOUT
            self._emit("phase", phase=self.phase.value)
            return

        # No dealer BJ — insurance that was placed loses
        for seat in self.seats:
            if seat.insurance_bet > 0:
                self._emit("insurance_lost", seat=seat.index, amount=seat.insurance_bet)
                seat.insurance_bet = 0.0

        # Auto-pay player naturals (3:2)
        for seat in self.seats:
            if not seat.is_active or seat.bet == 0:
                continue
            hand = seat.hands[0]
            if hand.is_blackjack:
                payout = seat.bet * self.rules.blackjack_pays
                seat.results.append(("BLACKJACK", payout))
                seat.bankroll += seat.bet + payout
                seat.done = True
                self._emit("hand_result", seat=seat.index, hand_idx=0,
                           outcome="BLACKJACK", payout=payout,
                           bankroll=seat.bankroll)
                if seat.is_human:
                    self.session_pnl += payout
                    self.hands_played += 1

        self.phase = RoundPhase.PLAYER_TURN
        self.message = action_line()
        self._emit("phase", phase=self.phase.value)
        self._emit("message", text=self.message)

    # -------------------------------------------------------------- player turn
    def _hand_complete(self, seat: Seat, hand_idx: int) -> bool:
        hand = seat.hands[hand_idx]
        if hand_idx in seat.stood_hands:
            return True
        if hand.is_surrendered or hand.is_bust or hand.is_doubled:
            return True
        if hand.value >= 21:
            return True
        if hand.from_split_aces and not self.rules.hit_split_aces:
            return True
        return False

    def current_actor(self) -> Optional[Tuple[int, int]]:
        if self.phase != RoundPhase.PLAYER_TURN:
            return None
        for seat in self.seats:
            if not seat.is_active or seat.bet == 0 or seat.done:
                continue
            for h_idx in range(len(seat.hands)):
                if not self._hand_complete(seat, h_idx):
                    return (seat.index, h_idx)
        return None

    def _count_splits(self, seat: Seat) -> int:
        # Number of times this seat has split = (hands - 1).
        # (Each split adds exactly one extra hand.)
        return max(0, len(seat.hands) - 1)

    def allowed_actions(self, seat_index: int, hand_index: int) -> Dict[str, bool]:
        seat = self.seats[seat_index]
        hand = seat.hands[hand_index]
        num_splits = self._count_splits(seat)
        can_hit = (
            not hand.is_surrendered
            and not hand.is_bust
            and hand.value < 21
            and not (hand.from_split_aces and not self.rules.hit_split_aces)
        )
        return {
            "hit": can_hit,
            "stand": not hand.is_surrendered and not hand.is_bust,
            "double": hand.can_double(self.rules) and seat.bankroll >= hand.bet,
            "split": hand.can_split(self.rules, num_splits) and seat.bankroll >= hand.bet,
            "surrender": (
                self.rules.late_surrender
                and len(hand.cards) == 2
                and not hand.is_split
            ),
        }

    def apply_action(self, seat_index: int, hand_index: int, action: str) -> None:
        if self.phase != RoundPhase.PLAYER_TURN:
            return
        seat = self.seats[seat_index]
        if hand_index >= len(seat.hands):
            return
        hand = seat.hands[hand_index]
        action = action.upper()

        if action == "H":
            card = self.deck.deal()
            hand.add_card(card)
            self._count_visible_card(card)
            self._emit("deal_card", seat=seat_index, hand_idx=hand_index, card=card, hole=False)
            self._emit("action", seat=seat_index, hand_idx=hand_index,
                       action="HIT", total=hand.value)
            if hand.is_bust:
                self._emit("bust", seat=seat_index, hand_idx=hand_index, total=hand.value)

        elif action == "S":
            seat.stood_hands.add(hand_index)
            self._emit("action", seat=seat_index, hand_idx=hand_index,
                       action="STAND", total=hand.value)

        elif action == "D":
            allowed = self.allowed_actions(seat_index, hand_index)
            if not allowed["double"]:
                self.apply_action(seat_index, hand_index, "H")
                return
            seat.bankroll -= hand.bet
            hand.bet *= 2
            hand.is_doubled = True
            card = self.deck.deal()
            hand.add_card(card)
            self._count_visible_card(card)
            self._emit("deal_card", seat=seat_index, hand_idx=hand_index, card=card, hole=False)
            self._emit("action", seat=seat_index, hand_idx=hand_index,
                       action="DOUBLE", total=hand.value)
            if hand.is_bust:
                self._emit("bust", seat=seat_index, hand_idx=hand_index, total=hand.value)

        elif action == "P":
            allowed = self.allowed_actions(seat_index, hand_index)
            if not allowed["split"]:
                return
            split_card = hand.cards.pop()
            new_hand = Hand(
                cards=[split_card],
                bet=hand.bet,
                is_split=True,
                from_split_aces=(split_card == "A"),
            )
            hand.is_split = True
            hand.from_split_aces = (hand.cards[0] == "A")
            seat.bankroll -= hand.bet
            seat.hands.insert(hand_index + 1, new_hand)
            self._emit(
                "split",
                seat=seat_index,
                hand_idx=hand_index,
                new_hand_idx=hand_index + 1,
                bankroll=seat.bankroll,
            )
            c1 = self.deck.deal()
            hand.add_card(c1)
            self._count_visible_card(c1)
            self._emit("deal_card", seat=seat_index, hand_idx=hand_index, card=c1, hole=False)
            c2 = self.deck.deal()
            new_hand.add_card(c2)
            self._count_visible_card(c2)
            self._emit("deal_card", seat=seat_index, hand_idx=hand_index + 1,
                       card=c2, hole=False)
            self._emit("action", seat=seat_index, hand_idx=hand_index,
                       action="SPLIT", total=hand.value)
            if split_card == "A":
                self._emit("message", text="Split aces receive one card each.")

        elif action == "R":
            allowed = self.allowed_actions(seat_index, hand_index)
            if not allowed["surrender"]:
                return
            hand.is_surrendered = True
            self._emit("action", seat=seat_index, hand_idx=hand_index,
                       action="SURRENDER", total=hand.value)
            self._emit("message", text="Surrender accepted.")

    def play_npcs_until_human_or_end(self) -> None:
        """Auto-play NPC seats. Stops when human's turn arrives or round ends."""
        while self.phase == RoundPhase.PLAYER_TURN:
            actor = self.current_actor()
            if actor is None:
                self._play_dealer_and_payout()
                return
            seat_idx, hand_idx = actor
            seat = self.seats[seat_idx]
            if seat.is_human:
                return
            self._npc_take_action(seat_idx, hand_idx)

    def _npc_take_action(self, seat_idx: int, hand_idx: int) -> None:
        seat = self.seats[seat_idx]
        hand = seat.hands[hand_idx]
        strat_hand = StratHand(cards=list(hand.cards))
        allowed = self.allowed_actions(seat_idx, hand_idx)
        action, _src = self.strategy.get_action(
            strat_hand,
            self.dealer_hand.cards[0],
            true_count=0.0,
            can_double=allowed["double"],
            can_split=allowed["split"],
            can_surrender=allowed["surrender"],
            use_deviations=False,
        )
        self.apply_action(seat_idx, hand_idx, action)

    def human_action(self, action: str) -> None:
        if self.phase != RoundPhase.PLAYER_TURN:
            return
        seat = self.seats[self.human_seat_index]
        if seat.done:
            return
        h_idx: Optional[int] = None
        for i in range(len(seat.hands)):
            if not self._hand_complete(seat, i):
                h_idx = i
                break
        if h_idx is None:
            return
        recommendation = self._build_recommendation(
            seat.hands[h_idx],
            self.dealer_hand.cards[0],
            self.allowed_actions(self.human_seat_index, h_idx),
        )
        self._set_action_feedback(action, recommendation)
        self.apply_action(self.human_seat_index, h_idx, action)
        self.play_npcs_until_human_or_end()

    # ------------------------------------------------------------------ dealer
    def _play_dealer_and_payout(self) -> None:
        self.phase = RoundPhase.DEALER_TURN
        self._emit("phase", phase=self.phase.value)
        self._reveal_dealer_hole()

        anyone_in = any(
            (not h.is_bust and not h.is_surrendered and not h.is_blackjack)
            for s in self.seats if s.is_active and s.bet > 0
            for h in s.hands
        )

        if anyone_in:
            while True:
                value = self.dealer_hand.value
                is_soft = self.dealer_hand.is_soft
                if value > 17:
                    break
                if value == 17 and not (is_soft and self.rules.dealer_hits_soft_17):
                    break
                card = self.deck.deal()
                self.dealer_hand.add_card(card)
                self._count_visible_card(card)
                self._emit("deal_card", seat="dealer", card=card, hole=False)
            self.message = dealer_final_line(
                value=self.dealer_hand.value,
                is_bust=self.dealer_hand.is_bust,
                is_blackjack=self.dealer_hand.is_blackjack,
            )
        else:
            self.message = "All players out."
        self._emit("message", text=self.message)

        self._calculate_payouts()

    def _calculate_payouts(self) -> None:
        self.phase = RoundPhase.PAYOUT
        self._emit("phase", phase=self.phase.value)

        dealer_value = self.dealer_hand.value
        dealer_bust = self.dealer_hand.is_bust

        for seat in self.seats:
            if not seat.is_active or seat.bet == 0 or seat.done:
                continue
            for h_idx, hand in enumerate(seat.hands):
                if hand.is_surrendered:
                    outcome, payout = "SURRENDER", -hand.bet / 2
                    seat.bankroll += hand.bet / 2  # return half
                elif hand.is_bust:
                    outcome, payout = "BUST", -hand.bet
                elif dealer_bust or hand.value > dealer_value:
                    outcome, payout = "WIN", hand.bet
                    seat.bankroll += hand.bet * 2  # return bet + win
                elif hand.value < dealer_value:
                    outcome, payout = "LOSE", -hand.bet
                else:
                    outcome, payout = "PUSH", 0.0
                    seat.bankroll += hand.bet  # return bet

                seat.results.append((outcome, payout))
                self._emit("hand_result", seat=seat.index, hand_idx=h_idx,
                           outcome=outcome, payout=payout,
                           bankroll=seat.bankroll)
                if seat.is_human:
                    self.session_pnl += payout
                    self.hands_played += 1
            seat.done = True

        self.phase = RoundPhase.SETTLE
        self._emit("phase", phase=self.phase.value)

    # ---------------------------------------------------------------- snapshot
    def _dealer_cards_visible(self) -> List[str]:
        if not self.dealer_hand.cards:
            return []
        hide_hole = self.phase in (
            RoundPhase.DEALING, RoundPhase.INSURANCE, RoundPhase.PLAYER_TURN
        )
        if hide_hole and len(self.dealer_hand.cards) >= 2:
            return [self.dealer_hand.cards[0], "__BACK__"]
        return list(self.dealer_hand.cards)

    def _dealer_value_visible(self) -> Optional[int]:
        if self.phase in (RoundPhase.DEALER_TURN, RoundPhase.PAYOUT, RoundPhase.SETTLE):
            return self.dealer_hand.value
        if not self.dealer_hand.cards:
            return None
        up_only = Hand(cards=[self.dealer_hand.cards[0]])
        return up_only.value

    def snapshot(self) -> Dict[str, Any]:
        actor = self.current_actor()
        allowed = None
        insurance_offer_amount = 0.0
        current_recommendation = None
        total_cards = self.rules.num_decks * 52
        cards_remaining = self.deck.cards_remaining
        cards_dealt = total_cards - cards_remaining
        cut_card_threshold = total_cards - self.deck.cut_card
        if actor and actor[0] == self.human_seat_index:
            allowed = self.allowed_actions(actor[0], actor[1])
            current_recommendation = self._current_recommendation()
        human_seat = self.seats[self.human_seat_index]
        if self.phase == RoundPhase.INSURANCE and human_seat.bet > 0:
            insurance_offer_amount = min(human_seat.bet / 2, human_seat.bankroll)
        return {
            "phase": self.phase.value,
            "tick": self.tick,
            "hand_number": self.hand_number,
            "message": self.message,
            "decks_remaining": round(self.deck.decks_remaining, 1),
            "cards_remaining": cards_remaining,
            "session_pnl": round(self.session_pnl, 2),
            "hands_played": self.hands_played,
            "human_seat_index": self.human_seat_index,
            "insurance_offer_amount": round(insurance_offer_amount, 2),
            "shoe": {
                "cards_remaining": cards_remaining,
                "cards_dealt": cards_dealt,
                "total_cards": total_cards,
                "decks_remaining": round(self.deck.decks_remaining, 1),
                "discard_tray_ratio": round(cards_dealt / total_cards, 4),
                "cut_card_ratio": self.rules.penetration,
                "cut_card_remaining": max(cards_remaining - cut_card_threshold, 0),
                "cut_card_reached": self.deck.needs_shuffle(),
            },
            "dealer": {
                "cards": self._dealer_cards_visible(),
                "value": self._dealer_value_visible(),
                "is_blackjack": (
                    self.dealer_hand.is_blackjack
                    and self.phase in (RoundPhase.PAYOUT, RoundPhase.SETTLE)
                ),
            },
            "seats": [
                {
                    "index": s.index,
                    "occupant": s.occupant,
                    "is_human": s.is_human,
                    "bankroll": round(s.bankroll, 2),
                    "bet": s.bet,
                    "done": s.done,
                    "insurance_bet": s.insurance_bet,
                    "hands": [
                        {
                            "cards": list(h.cards),
                            "value": h.value,
                            "bet": h.bet,
                            "is_soft": h.is_soft,
                            "is_bust": h.is_bust,
                            "is_blackjack": h.is_blackjack,
                            "is_doubled": h.is_doubled,
                            "is_split": h.is_split,
                            "is_surrendered": h.is_surrendered,
                        }
                        for h in s.hands
                    ],
                    "results": [{"outcome": o, "payout": p} for o, p in s.results],
                }
                for s in self.seats
            ],
            "rules": {
                "table_name": "US FLOOR SHOE",
                "num_decks": self.rules.num_decks,
                "dealer_hits_soft_17": self.rules.dealer_hits_soft_17,
                "blackjack_pays": self.rules.blackjack_pays,
                "late_surrender": self.rules.late_surrender,
                "double_after_split": self.rules.double_after_split,
                "resplit_aces": self.rules.resplit_aces,
                "hit_split_aces": self.rules.hit_split_aces,
                "max_splits": self.rules.max_splits,
                "penetration": self.rules.penetration,
                "dealer_peeks": True,
            },
            "actor": {"seat": actor[0], "hand_idx": actor[1]} if actor else None,
            "allowed_actions": allowed,
            "coach": {
                "count": self._coach_count_payload(),
                "current_recommendation": current_recommendation,
                "insurance_recommendation": self._insurance_recommendation(),
                "last_feedback": self.last_feedback,
            },
        }
