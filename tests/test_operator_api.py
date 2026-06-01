from fastapi.testclient import TestClient

from src.agents.poker.vision.screenshot_parser import VisionModelUnavailableError
from src.dashboard.backend import api
from src.dashboard.backend.operator_store import JsonListStore


def make_client(tmp_path, monkeypatch):
    store = JsonListStore(tmp_path / "queue.json")
    monkeypatch.setattr(api, "review_queue_store", store)
    return TestClient(api.app), store


def test_operator_endpoints_and_review_queue(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)

    status = client.get("/api/operator/status")
    assert status.status_code == 200
    assert status.json()["status"] == "ready"

    coach = client.get("/api/blackjack/coach-summary")
    assert coach.status_code == 200
    assert "certification" in coach.json()

    profiles = client.get("/api/blackjack/profiles")
    assert profiles.status_code == 200
    assert any(profile["name"] == "live_75pen" for profile in profiles.json())

    analysis = client.post(
        "/api/poker/advisor/analyze",
        json={
            "hole_cards": "Ah Kh",
            "board": "Qs 7c 2d",
            "position": "BTN",
            "villain_type": "reg",
            "villain_position": "CO",
            "pot_size": 12,
            "bet_to_call": 4,
            "effective_stack": 100,
            "is_preflop_aggressor": True,
            "action_history": ["open 2.5bb", "bb call", "flop cbet 33%"],
        },
    )
    assert analysis.status_code == 200
    payload = analysis.json()
    assert payload["decision"]["action"] in {"fold", "call", "raise", "check", "bet", "check_raise", "all_in"}
    assert payload["decision"]["validation"]["status"] in {"validated", "provisional", "unvalidated"}
    assert payload["review"]["agreement"] in {"aligned", "diverges", "n_a"}

    add_item = client.post(
        "/api/poker/review-queue",
        json={
            "label": "AK spot",
            "note": "Review river line",
            "spot": payload["spot"],
            "decision": payload["decision"],
        },
    )
    assert add_item.status_code == 200
    item_id = add_item.json()["id"]

    queued = client.get("/api/poker/review-queue")
    assert queued.status_code == 200
    assert len(queued.json()["items"]) == 1

    detail = client.get(f"/api/poker/review-queue/{item_id}")
    assert detail.status_code == 200
    assert detail.json()["item"]["id"] == item_id
    assert "review" in detail.json()

    deleted = client.delete(f"/api/poker/review-queue/{item_id}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"


def test_review_queue_missing_item_returns_404(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)

    get_response = client.get("/api/poker/review-queue/non-existent-id")
    assert get_response.status_code == 404
    assert get_response.json()["detail"] == "Review item not found"

    delete_response = client.delete("/api/poker/review-queue/non-existent-id")
    assert delete_response.status_code == 404
    assert delete_response.json()["detail"] == "Review item not found"


def test_review_queue_corrupted_payload_returns_fallback_review(tmp_path, monkeypatch):
    client, store = make_client(tmp_path, monkeypatch)

    corrupted_item = store.add(
        {
            "label": "Corrupted item",
            "note": "Should degrade gracefully",
            "spot": {
                "hole_cards": "ZZ",
                "board": "Qs 7c 2d",
                "position": "BTN",
                "villain_type": "reg",
                "villain_position": "CO",
                "pot_size": 12,
                "bet_to_call": 4,
                "effective_stack": 100,
                "is_preflop_aggressor": True,
                "action_history": ["open 2.5bb", "bb call", "flop cbet 33%"],
            },
            "decision": {},
        }
    )

    detail = client.get(f"/api/poker/review-queue/{corrupted_item['id']}")
    assert detail.status_code == 200

    payload = detail.json()
    assert payload["item"]["id"] == corrupted_item["id"]
    assert payload["review"]["agreement"] == "n_a"
    assert "Replay payload could not be rebuilt" in payload["review"]["summary"]


class StubScreenshotParser:
    def __init__(self, payload):
        self.payload = payload

    def analyze(self, image_data, image_type=None, source_hint="online_table_ui"):
        assert image_data
        return self.payload


def test_screenshot_endpoint_returns_quick_decision(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        api,
        "get_poker_screenshot_parser",
        lambda: StubScreenshotParser(
            {
                "hero_cards": ["Ah", "Kh"],
                "board": ["Qs", "7c", "2d"],
                "position": "BTN",
                "button_position": "BTN",
                "pot_size": 12.0,
                "bet_to_call": 4.0,
                "effective_stack": 100.0,
                "is_preflop_aggressor": True,
                "action_history": ["open 2.5bb", "bb call", "flop cbet 33%"],
                "visible_opponents": [{"seat": "Villain 1", "position": "CO", "cards": [], "visibility": "unknown"}],
                "warnings": [],
                "missing_fields": [],
                "parse_confidence": 0.92,
                "source_hint": "online_table_ui",
            }
        ),
    )

    response = client.post(
        "/api/poker/advisor/analyze-screenshot",
        json={"image_data": "data:image/png;base64,ZmFrZQ==", "source_hint": "online_table_ui"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_status"] in {"validated", "provisional"}
    assert payload["decision"]["action"] in {"fold", "call", "raise", "check", "bet", "check_raise", "all_in"}
    assert payload["visible_opponents"][0]["visibility"] == "unknown"


def test_screenshot_and_manual_modes_match_for_same_spot(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    parsed_payload = {
        "hero_cards": ["Ah", "Kh"],
        "board": ["Qs", "7c", "2d"],
        "position": "BTN",
        "button_position": "BTN",
        "pot_size": 12.0,
        "bet_to_call": 4.0,
        "effective_stack": 100.0,
        "is_preflop_aggressor": True,
        "action_history": ["open 2.5bb", "bb call", "flop cbet 33%"],
        "visible_opponents": [{"seat": "Villain 1", "position": "CO", "cards": [], "visibility": "unknown"}],
        "warnings": [],
        "missing_fields": [],
        "parse_confidence": 0.92,
        "source_hint": "online_table_ui",
    }
    monkeypatch.setattr(api, "get_poker_screenshot_parser", lambda: StubScreenshotParser(parsed_payload))

    screenshot_response = client.post(
        "/api/poker/advisor/analyze-screenshot",
        json={"image_data": "data:image/png;base64,ZmFrZQ==", "source_hint": "online_table_ui"},
    )
    assert screenshot_response.status_code == 200
    screenshot_body = screenshot_response.json()

    manual_response = client.post(
        "/api/poker/advisor/analyze",
        json={
            "hole_cards": "Ah Kh",
            "board": "Qs 7c 2d",
            "position": "BTN",
            "villain_type": "reg",
            "villain_position": "CO",
            "pot_size": 12.0,
            "bet_to_call": 4.0,
            "effective_stack": 100.0,
            "is_preflop_aggressor": True,
            "action_history": ["open 2.5bb", "bb call", "flop cbet 33%"],
        },
    )
    assert manual_response.status_code == 200
    manual_body = manual_response.json()

    assert screenshot_body["decision"]["action"] == manual_body["decision"]["action"]
    assert screenshot_body["decision"]["street"] == manual_body["decision"]["street"]
    assert screenshot_body["review"]["agreement"] == manual_body["review"]["agreement"]


def test_screenshot_endpoint_blocks_when_hero_cards_missing(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        api,
        "get_poker_screenshot_parser",
        lambda: StubScreenshotParser(
            {
                "hero_cards": [],
                "board": ["Qs", "7c", "2d"],
                "position": "BTN",
                "pot_size": 12.0,
                "bet_to_call": 4.0,
                "effective_stack": 100.0,
                "is_preflop_aggressor": True,
                "action_history": [],
                "visible_opponents": [],
                "warnings": ["Hero cards were hidden."],
                "missing_fields": ["hole_cards"],
                "parse_confidence": 0.63,
                "source_hint": "online_table_ui",
            }
        ),
    )

    response = client.post(
        "/api/poker/advisor/analyze-screenshot",
        json={"image_data": "data:image/png;base64,ZmFrZQ==", "source_hint": "online_table_ui"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_status"] == "blocked"
    assert "decision" not in payload


def test_screenshot_endpoint_defaults_preflop_numeric_fields_to_provisional(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        api,
        "get_poker_screenshot_parser",
        lambda: StubScreenshotParser(
            {
                "hero_cards": ["As", "Kd"],
                "board": [],
                "position": None,
                "pot_size": None,
                "bet_to_call": None,
                "effective_stack": 75.0,
                "is_preflop_aggressor": None,
                "action_history": [],
                "visible_opponents": [],
                "warnings": [],
                "missing_fields": ["position", "pot_size", "bet_to_call", "is_preflop_aggressor"],
                "parse_confidence": 0.74,
                "source_hint": "online_table_ui",
            }
        ),
    )

    response = client.post(
        "/api/poker/advisor/analyze-screenshot",
        json={"image_data": "data:image/png;base64,ZmFrZQ==", "source_hint": "online_table_ui"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_status"] == "provisional"
    assert payload["parsed_spot"]["pot_size"] == 1.5
    assert payload["parsed_spot"]["bet_to_call"] == 0.0
    assert any("Defaulted to 1.5bb" in warning for warning in payload["warnings"])


def test_screenshot_endpoint_rejects_duplicate_cards(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        api,
        "get_poker_screenshot_parser",
        lambda: StubScreenshotParser(
            {
                "hero_cards": ["Ah", "Kh"],
                "board": ["Ah", "7c", "2d"],
                "position": "BTN",
                "pot_size": 12.0,
                "bet_to_call": 4.0,
                "effective_stack": 100.0,
                "is_preflop_aggressor": True,
                "action_history": [],
                "visible_opponents": [],
                "warnings": [],
                "missing_fields": [],
                "parse_confidence": 0.91,
                "source_hint": "online_table_ui",
            }
        ),
    )

    response = client.post(
        "/api/poker/advisor/analyze-screenshot",
        json={"image_data": "data:image/png;base64,ZmFrZQ==", "source_hint": "online_table_ui"},
    )

    assert response.status_code == 400
    assert "Duplicate card detected" in response.json()["detail"]


def test_screenshot_endpoint_surfaces_missing_vision_model(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(api, "get_poker_screenshot_parser", lambda: (_ for _ in ()).throw(VisionModelUnavailableError("No vision model configured")))

    response = client.post(
        "/api/poker/advisor/analyze-screenshot",
        json={"image_data": "data:image/png;base64,ZmFrZQ==", "source_hint": "online_table_ui"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "No vision model configured"
