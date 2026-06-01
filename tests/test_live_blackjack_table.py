import pytest

from src.agents.blackjack.game_engine import GameRules, Hand
from src.agents.blackjack.live_table.session import TableSession
from src.agents.blackjack.live_table.table import LiveTable, RoundPhase


@pytest.mark.parametrize(
    ("bet", "kwargs", "match"),
    [
        (20, {}, "minimum bet"),
        (27, {}, "increments"),
        (600, {}, "maximum bet"),
        (1500, {"max_bet": 2000.0}, "insufficient bankroll"),
    ],
)
def test_start_round_rejects_invalid_human_bets(bet, kwargs, match):
    session_kwargs = {
        "starting_bankroll": 1000.0,
        "min_bet": 25.0,
        "max_bet": 500.0,
    }
    session_kwargs.update(kwargs)
    session = TableSession(**session_kwargs)

    with pytest.raises(ValueError, match=match):
        session.start_round(bet)


def test_default_session_matches_us_floor_shoe_rules():
    session = TableSession()
    snapshot = session.snapshot()

    assert session.min_bet == 25.0
    assert session.max_bet == 500.0
    assert session.bet_increment == 5.0
    assert snapshot["rules"]["table_name"] == "US FLOOR SHOE"
    assert snapshot["rules"]["num_decks"] == 8
    assert snapshot["rules"]["dealer_hits_soft_17"] is True
    assert snapshot["rules"]["late_surrender"] is True
    assert snapshot["rules"]["double_after_split"] is True
    assert snapshot["rules"]["resplit_aces"] is False
    assert snapshot["rules"]["hit_split_aces"] is False
    assert snapshot["rules"]["max_splits"] == 3
    assert snapshot["shoe"]["total_cards"] == 416
    assert snapshot["shoe"]["cut_card_ratio"] == 0.75


def test_split_event_moves_before_new_cards():
    table = LiveTable(human_seat_index=0)
    table.seat_human(bankroll=1000.0)
    table.drain_events()

    seat = table.seats[0]
    seat.bet = 25.0
    seat.bankroll = 950.0
    seat.hands = [Hand(cards=["8", "8"], bet=25.0)]
    table.phase = RoundPhase.PLAYER_TURN
    table.deck.cards = ["4", "3"]

    table.apply_action(0, 0, "P")
    events = table.drain_events()

    assert [event["type"] for event in events[:3]] == ["split", "deal_card", "deal_card"]
    assert events[0]["new_hand_idx"] == 1
    assert seat.bankroll == 925.0
    assert [hand.cards for hand in seat.hands] == [["8", "3"], ["8", "4"]]


def test_split_aces_are_locked_after_one_card_each():
    table = LiveTable(
        human_seat_index=0,
        rules=GameRules(hit_split_aces=False, resplit_aces=False, max_splits=3),
    )
    table.seat_human(bankroll=1000.0)
    table.drain_events()

    seat = table.seats[0]
    seat.bet = 25.0
    seat.bankroll = 950.0
    seat.hands = [Hand(cards=["A", "A"], bet=25.0)]
    table.phase = RoundPhase.PLAYER_TURN
    table.deck.cards = ["9", "8"]

    table.apply_action(0, 0, "P")

    assert [hand.cards for hand in seat.hands] == [["A", "8"], ["A", "9"]]
    assert table._hand_complete(seat, 0) is True
    assert table._hand_complete(seat, 1) is True
    assert table.allowed_actions(0, 0)["hit"] is False
    assert table.allowed_actions(0, 1)["hit"] is False


def test_late_surrender_is_not_available_after_hit_or_split():
    table = LiveTable(human_seat_index=0)
    table.seat_human(bankroll=1000.0)
    table.drain_events()

    seat = table.seats[0]
    seat.bet = 25.0
    seat.bankroll = 975.0
    seat.hands = [Hand(cards=["10", "6"], bet=25.0)]
    table.phase = RoundPhase.PLAYER_TURN
    table.deck.cards = ["2"]

    table.apply_action(0, 0, "H")
    assert table.allowed_actions(0, 0)["surrender"] is False

    seat.bankroll = 950.0
    seat.hands = [Hand(cards=["8", "8"], bet=25.0)]
    seat.stood_hands = set()
    table.deck.cards = ["4", "3"]
    table.apply_action(0, 0, "P")

    assert table.allowed_actions(0, 0)["surrender"] is False
    assert table.allowed_actions(0, 1)["surrender"] is False


def test_ten_upcard_blackjack_resolves_before_player_turn():
    table = LiveTable(human_seat_index=0)
    table.seat_human(bankroll=1000.0)
    table.drain_events()

    seat = table.seats[0]
    seat.bet = 25.0
    seat.bankroll = 975.0
    table.phase = RoundPhase.BETTING
    table.deck.cards = ["A", "7", "K", "10"]

    table.deal_initial()

    assert table.phase == RoundPhase.PAYOUT
    assert seat.results[0][0] == "LOSE"
    assert table.current_actor() is None


def test_h17_default_hits_soft_17():
    table = LiveTable(
        human_seat_index=0,
        rules=GameRules(num_decks=8, dealer_hits_soft_17=True, late_surrender=True),
    )
    table.seat_human(bankroll=1000.0)
    table.drain_events()

    seat = table.seats[0]
    seat.bet = 25.0
    seat.hands = [Hand(cards=["10", "8"], bet=25.0)]
    table.phase = RoundPhase.PLAYER_TURN
    table.dealer_hand = Hand(cards=["A", "6"])
    table.dealer_hole = "6"
    table.deck.cards = ["K"]

    table._play_dealer_and_payout()

    assert table.dealer_hand.cards == ["A", "6", "K"]
    assert table.dealer_hand.value == 17


def test_snapshot_caps_insurance_offer_to_available_bankroll():
    table = LiveTable(human_seat_index=0)
    table.seat_human(bankroll=100.0)
    table.drain_events()

    seat = table.seats[0]
    seat.bet = 25.0
    seat.bankroll = 10.0
    seat.hands = [Hand(cards=["10", "7"], bet=25.0)]
    table.phase = RoundPhase.INSURANCE

    snapshot = table.snapshot()

    assert snapshot["insurance_offer_amount"] == 10.0


def test_visible_card_count_excludes_dealer_hole_until_reveal():
    table = LiveTable(
        human_seat_index=0,
        rules=GameRules(num_decks=1, penetration=0.75),
    )
    table.seat_human(bankroll=1000.0)
    table.drain_events()

    table.start_betting()
    table.place_bet(0, 25.0)
    table.deck.cards = ["5", "7", "9", "10"]

    table.deal_initial()

    assert table.counter.running_count == -1
    assert table.dealer_hole_revealed is False

    table._reveal_dealer_hole()

    assert table.counter.running_count == 0
    assert table.dealer_hole_revealed is True


def test_count_persists_across_hands_and_resets_after_shuffle():
    table = LiveTable(
        human_seat_index=0,
        rules=GameRules(num_decks=1, penetration=0.75),
    )
    table.seat_human(bankroll=1000.0)
    table.drain_events()

    table.counter.add_cards(["2", "3", "4"])
    assert table.counter.running_count == 3

    table.start_betting()
    assert table.counter.running_count == 3

    cards_before_cut = table.rules.num_decks * 52 - table.deck.cut_card
    table.counter.add_cards(["5"])
    table.deck.cards = ["2"] * cards_before_cut

    table.start_betting()

    assert table.counter.running_count == 0
    assert table.counter.cards_seen == 0


def test_snapshot_exposes_basic_strategy_recommendation_for_human_turn():
    table = LiveTable(
        human_seat_index=0,
        rules=GameRules(num_decks=1, late_surrender=True),
    )
    table.seat_human(bankroll=1000.0)
    table.drain_events()

    seat = table.seats[0]
    seat.bet = 25.0
    seat.bankroll = 975.0
    seat.hands = [Hand(cards=["10", "2"], bet=25.0)]
    table.phase = RoundPhase.PLAYER_TURN
    table.dealer_hand = Hand(cards=["2", "K"])
    table.dealer_hole = "K"

    coach = table.snapshot()["coach"]

    assert coach["current_recommendation"]["action"] == "HIT"
    assert coach["current_recommendation"]["source"] == "basic"


def test_snapshot_exposes_count_deviation_recommendation():
    table = LiveTable(
        human_seat_index=0,
        rules=GameRules(num_decks=1, late_surrender=True),
    )
    table.seat_human(bankroll=1000.0)
    table.drain_events()

    seat = table.seats[0]
    seat.bet = 25.0
    seat.bankroll = 975.0
    seat.hands = [Hand(cards=["10", "2"], bet=25.0)]
    table.phase = RoundPhase.PLAYER_TURN
    table.dealer_hand = Hand(cards=["3", "K"])
    table.dealer_hole = "K"
    table.counter.add_cards(["2"] * 8)

    coach = table.snapshot()["coach"]

    assert coach["current_recommendation"]["action"] == "STAND"
    assert coach["current_recommendation"]["source"] == "deviation"


def test_insurance_recommendation_only_appears_in_insurance_phase():
    table = LiveTable(
        human_seat_index=0,
        rules=GameRules(num_decks=1, late_surrender=True),
    )
    table.seat_human(bankroll=1000.0)
    table.drain_events()

    seat = table.seats[0]
    seat.bet = 25.0
    seat.bankroll = 975.0
    seat.hands = [Hand(cards=["10", "7"], bet=25.0)]
    table.dealer_hand = Hand(cards=["A", "9"])
    table.dealer_hole = "9"
    table.counter.add_cards(["2", "3", "4"])
    table.phase = RoundPhase.INSURANCE

    insurance = table.snapshot()["coach"]["insurance_recommendation"]
    assert insurance["take_insurance"] is True

    table.phase = RoundPhase.PLAYER_TURN
    assert table.snapshot()["coach"]["insurance_recommendation"] is None


def test_human_feedback_tracks_wrong_choice_against_ideal_play():
    table = LiveTable(
        human_seat_index=0,
        rules=GameRules(num_decks=1, late_surrender=True),
    )
    table.seat_human(bankroll=1000.0)
    table.drain_events()

    seat = table.seats[0]
    seat.bet = 25.0
    seat.bankroll = 975.0
    seat.hands = [Hand(cards=["10", "2"], bet=25.0)]
    table.phase = RoundPhase.PLAYER_TURN
    table.dealer_hand = Hand(cards=["3", "K"])
    table.dealer_hole = "K"
    table.counter.add_cards(["2"] * 8)
    table.deck.cards = ["10"]

    table.human_action("H")

    assert table.last_feedback is not None
    assert table.last_feedback["is_correct"] is False
    assert table.last_feedback["chosen_action"] == "HIT"
    assert table.last_feedback["ideal_action"] == "STAND"


def test_human_feedback_tracks_correct_choice():
    table = LiveTable(
        human_seat_index=0,
        rules=GameRules(num_decks=1, late_surrender=True),
    )
    table.seat_human(bankroll=1000.0)
    table.drain_events()

    seat = table.seats[0]
    seat.bet = 25.0
    seat.bankroll = 975.0
    seat.hands = [Hand(cards=["10", "2"], bet=25.0)]
    table.phase = RoundPhase.PLAYER_TURN
    table.dealer_hand = Hand(cards=["3", "K"])
    table.dealer_hole = "K"
    table.counter.add_cards(["2"] * 8)
    table.deck.cards = ["4"]

    table.human_action("S")

    assert table.last_feedback is not None
    assert table.last_feedback["is_correct"] is True
    assert table.last_feedback["ideal_action"] == "STAND"


def test_refresh_roster_removes_npc_below_table_minimum_after_losses():
    session = TableSession(num_seats=2, human_seat_index=0, min_bet=25.0, max_bet=500.0)
    npc_index = 1
    npc_name = session.table.seats[npc_index].occupant

    session.table.seats[npc_index].bankroll = 10.0
    session.refresh_roster_between_rounds()

    assert session.table.seats[npc_index].occupant is None
    assert npc_index not in session._npc_roster
    assert npc_name is not None


def test_start_betting_only_shuffles_after_round_completes():
    table = LiveTable(
        human_seat_index=0,
        rules=GameRules(num_decks=8, penetration=0.75),
    )
    table.seat_human(bankroll=1000.0)
    table.drain_events()

    total_cards = table.rules.num_decks * 52
    cards_before_cut = total_cards - table.deck.cut_card
    table.deck.cards = ["2"] * cards_before_cut

    seat = table.seats[0]
    seat.bet = 25.0
    seat.hands = [Hand(cards=["10", "8"], bet=25.0)]
    table.dealer_hand = Hand(cards=["10", "7"])
    table.dealer_hole = "7"
    table.phase = RoundPhase.PLAYER_TURN

    assert table.deck.needs_shuffle() is True

    table._play_dealer_and_payout()
    assert table.phase == RoundPhase.SETTLE
    assert table.deck.cards_remaining == cards_before_cut

    table.start_betting()
    events = table.drain_events()

    assert any(event["type"] == "shuffle" for event in events)
    assert table.phase == RoundPhase.BETTING
    assert table.deck.cards_remaining == total_cards
