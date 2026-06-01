from types import SimpleNamespace

import pytest

from src.agents.poker.vision import (
    PokerScreenshotParser,
    VisionModelUnavailableError,
    normalize_screenshot_payload,
)


def test_normalize_screenshot_payload_shapes_visible_state():
    payload = normalize_screenshot_payload(
        {
            "hero_cards": ["Ah", "Ks"],
            "board": "Td 7c 2h",
            "hero_position": "button",
            "button_position": "button",
            "pot_size": "$15.5",
            "bet_to_call": "5bb",
            "effective_stack": "92",
            "is_preflop_aggressor": "hero",
            "visible_opponents": [
                {"seat": "Villain 1", "position": "bb", "visible_cards": ["Qh", "Qd"], "note": "showdown"},
                {"seat": "Villain 2", "position": "co", "visible_cards": []},
            ],
            "action_history": ["open 2.5bb", "bb call"],
            "overall_confidence": 0.84,
        }
    )

    assert payload["hero_cards"] == ["AH", "KS"]
    assert payload["board"] == ["TD", "7C", "2H"]
    assert payload["position"] == "BTN"
    assert payload["button_position"] == "BTN"
    assert payload["pot_size"] == 15.5
    assert payload["bet_to_call"] == 5.0
    assert payload["effective_stack"] == 92.0
    assert payload["is_preflop_aggressor"] is True
    assert payload["visible_opponents"][0]["cards"] == ["QH", "QD"]
    assert payload["visible_opponents"][1]["visibility"] == "unknown"
    assert payload["parse_confidence"] == 0.84


def test_normalize_screenshot_payload_tracks_missing_fields():
    payload = normalize_screenshot_payload(
        {
            "board": "Qs 7c 2d",
            "pot_size": None,
            "bet_to_call": None,
            "effective_stack": None,
        }
    )

    assert "hole_cards" in payload["missing_fields"]
    assert "position" in payload["missing_fields"]
    assert "pot_size" in payload["missing_fields"]
    assert "bet_to_call" in payload["missing_fields"]
    assert "effective_stack" in payload["missing_fields"]
    assert payload["parse_confidence"] < 0.7


def test_prompt_builder_escapes_nested_visible_opponent_json():
    prompt = PokerScreenshotParser()._build_prompt(layout_hint="coinpoker")

    assert '"visible_opponents": [' in prompt
    assert '"seat": "Villain 1"' in prompt
    assert '"note": "showdown"' in prompt
    assert 'Optional layout hint from caller: "coinpoker"' in prompt


def test_parser_falls_back_to_next_vision_model_when_first_provider_fails():
    class FailingModel:
        model_name = "failing-vision"

        def generate_response_with_image(self, **kwargs):
            raise RuntimeError(
                "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
                "'message': 'Your credit balance is too low to access the Anthropic API. "
                "Please go to Plans & Billing to upgrade or purchase credits.'}}"
            )

    class WorkingModel:
        model_name = "working-vision"

        def generate_response_with_image(self, **kwargs):
            return SimpleNamespace(
                content="""{
                    "hero_cards": ["Ah", "Ks"],
                    "board": ["Qh", "7c", "2d"],
                    "hero_position": "BTN",
                    "button_position": "BTN",
                    "pot_size": 12,
                    "bet_to_call": 4,
                    "effective_stack": 80,
                    "is_preflop_aggressor": true,
                    "visible_opponents": [{"seat": "Villain 1", "position": "BB", "visible_cards": []}],
                    "action_history": ["btn open 2.5bb", "bb call", "flop cbet 33%"],
                    "overall_confidence": 0.91
                }"""
            )

    class StubFactory:
        def get_model(self, name):
            return {
                "claude": FailingModel(),
                "openai": WorkingModel(),
            }.get(name)

    parser = PokerScreenshotParser(factory=StubFactory())
    payload = parser.analyze("data:image/png;base64,ZmFrZQ==", layout_hint="coinpoker")

    assert payload["hero_cards"] == ["AH", "KS"]
    assert payload["position"] == "BTN"
    assert payload["model_name"] == "working-vision"


def test_parser_raises_clean_error_when_all_vision_models_fail():
    class FailingModel:
        model_name = "failing-vision"

        def generate_response_with_image(self, **kwargs):
            raise RuntimeError(
                "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
                "'message': 'Your credit balance is too low to access the Anthropic API. "
                "Please go to Plans & Billing to upgrade or purchase credits.'}}"
            )

    class StubFactory:
        def get_model(self, name):
            if name == "claude":
                return FailingModel()
            return None

    parser = PokerScreenshotParser(factory=StubFactory())

    with pytest.raises(VisionModelUnavailableError) as excinfo:
        parser.analyze("data:image/png;base64,ZmFrZQ==")

    assert "No configured vision-capable model could parse the screenshot" in str(excinfo.value)
    assert "provider credits exhausted" in str(excinfo.value)
