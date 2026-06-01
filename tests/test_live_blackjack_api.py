from fastapi.testclient import TestClient

from src.agents.blackjack.live_table.api import app


client = TestClient(app)


def _snapshot(response):
    assert response.status_code == 200
    return response.json()["snapshot"]


def test_live_table_index_supports_head_requests():
    response = client.head("/")

    assert response.status_code == 200


def test_live_table_state_returns_snapshot():
    response = client.get("/state")

    assert response.status_code == 200
    body = response.json()
    assert "snapshot" in body
    assert body["snapshot"]["phase"] in {"betting", "dealing", "insurance", "player_turn", "dealer_turn", "payout", "settle"}
    coach = body["snapshot"]["coach"]
    assert set(coach.keys()) == {"count", "current_recommendation", "insurance_recommendation", "last_feedback"}
    assert {"running_count", "true_count", "decks_remaining", "edge"} <= set(coach["count"].keys())


def test_live_table_round_can_advance_to_next_hand():
    snap = _snapshot(client.post("/reset"))
    assert snap["phase"] == "betting"

    snap = _snapshot(client.post("/start_round", json={"bet": 25}))

    for _ in range(24):
        phase = snap["phase"]
        if phase in {"payout", "settle"}:
            break
        if phase == "insurance":
            snap = _snapshot(client.post("/insurance", json={"take": False}))
            continue
        if phase == "player_turn":
            snap = _snapshot(client.post("/action", json={"action": "S"}))
            continue
        snap = _snapshot(client.get("/state"))
    else:
        raise AssertionError(f"round did not settle, phase={snap['phase']}")

    snap = _snapshot(client.post("/next_round"))
    assert snap["phase"] == "betting"
    assert snap["hand_number"] >= 2


def test_live_table_reset_restores_bankroll_and_clears_round_state():
    _snapshot(client.post("/start_round", json={"bet": 25}))
    snap = _snapshot(client.post("/reset"))

    human = snap["seats"][snap["human_seat_index"]]
    assert snap["phase"] == "betting"
    assert human["bankroll"] == 1000.0
    assert human["bet"] == 0.0
    assert human["hands"] == []
    assert snap["coach"]["count"]["running_count"] == 0
    assert snap["coach"]["last_feedback"] is None
