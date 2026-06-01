"""Screenshot parsing for online poker table images."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from src.models.model_factory import ModelFactory


POSITION_ALIASES = {
    "utg": "UTG",
    "under the gun": "UTG",
    "utg+1": "UTG1",
    "utg1": "UTG1",
    "utg +1": "UTG1",
    "utg+2": "UTG2",
    "utg2": "UTG2",
    "utg +2": "UTG2",
    "mp": "MP",
    "middle position": "MP",
    "mp2": "MP2",
    "mp+1": "MP2",
    "mp +1": "MP2",
    "hj": "HJ",
    "hijack": "HJ",
    "co": "CO",
    "cutoff": "CO",
    "btn": "BTN",
    "button": "BTN",
    "dealer": "BTN",
    "dealer button": "BTN",
    "sb": "SB",
    "small blind": "SB",
    "bb": "BB",
    "big blind": "BB",
}

CARD_PATTERN = re.compile(r"(10|[2-9TJQKA])[cdhs]", re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
SUPPORTED_SOURCES = {"online_table_ui"}


class ScreenshotParserError(RuntimeError):
    """Raised when screenshot parsing fails."""


class VisionModelUnavailableError(ScreenshotParserError):
    """Raised when no configured model supports image parsing."""


def _extract_json_object(text: str) -> Dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ScreenshotParserError("Vision model did not return JSON")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ScreenshotParserError(f"Vision JSON could not be parsed: {exc}") from exc


def _strip_data_url(image_data: str, image_type: Optional[str]) -> Tuple[str, str]:
    payload = (image_data or "").strip()
    media_type = image_type or "image/png"

    if payload.startswith("data:"):
        match = re.match(r"data:(image/[^;]+);base64,(.+)", payload, re.DOTALL)
        if match:
            media_type = match.group(1)
            payload = match.group(2)
        elif ";base64," in payload:
            payload = payload.split(";base64,", 1)[1]

    if not payload:
        raise ScreenshotParserError("Screenshot payload is empty")

    return payload, media_type


def _normalize_cards(value: Any) -> List[str]:
    if value is None:
        return []

    if isinstance(value, list):
        parts = []
        for item in value:
            parts.extend(_normalize_cards(item))
        return parts

    if isinstance(value, dict):
        cards = value.get("cards") or value.get("visible_cards") or value.get("hole_cards")
        return _normalize_cards(cards)

    text = str(value).strip()
    if not text:
        return []

    cards = []
    for match in CARD_PATTERN.finditer(text):
        cards.append(match.group(0).upper().replace("10", "T"))
    return cards


def _normalize_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().lower()
    if not text or text in {"unknown", "n/a", "na", "none", "null", "unreadable"}:
        return None

    match = NUMBER_PATTERN.search(text.replace(",", ""))
    if not match:
        return None

    return float(match.group(0))


def _normalize_position(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip().lower()
    if not text:
        return None

    return POSITION_ALIASES.get(text, text.upper() if text.upper() in POSITION_ALIASES.values() else None)


def _normalize_layout(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_action_history(value: Any) -> List[str]:
    if value is None:
        return []

    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items

    text = str(value).strip()
    if not text:
        return []

    if "\n" in text:
        return [line.strip() for line in text.splitlines() if line.strip()]

    return [part.strip() for part in re.split(r"\s*[,;]\s*", text) if part.strip()]


def _normalize_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None

    text = str(value).strip().lower()
    if text in {"hero", "yes", "true", "1"}:
        return True
    if text in {"villain", "no", "false", "0"}:
        return False
    return None


def _normalize_visible_opponents(raw_opponents: Any) -> List[Dict[str, Any]]:
    opponents: List[Dict[str, Any]] = []
    if not isinstance(raw_opponents, list):
        return opponents

    for item in raw_opponents:
        if not isinstance(item, dict):
            continue
        cards = _normalize_cards(
            item.get("visible_cards")
            or item.get("cards")
            or item.get("exposed_cards")
        )
        opponents.append(
            {
                "seat": str(item.get("seat") or item.get("name") or "Opponent").strip(),
                "position": _normalize_position(item.get("position")),
                "cards": cards,
                "visibility": "visible" if cards else "unknown",
                "note": str(item.get("note") or "").strip(),
            }
        )

    return opponents


def _summarize_model_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    lower = text.lower()

    if "credit balance is too low" in lower or "upgrade or purchase credits" in lower:
        return "provider credits exhausted"
    if "bridge server not running" in lower:
        return "bridge server not running"
    if "invalid api key" in lower:
        return "invalid API key"
    if "rate limit" in lower:
        return "provider rate limited"

    if len(text) > 180:
        return f"{text[:177]}..."
    return text


def normalize_screenshot_payload(raw_payload: Dict[str, Any], source_hint: str = "online_table_ui") -> Dict[str, Any]:
    hero_cards = _normalize_cards(raw_payload.get("hero_cards") or raw_payload.get("hole_cards"))
    board = _normalize_cards(raw_payload.get("board") or raw_payload.get("community_cards"))
    visible_opponents = _normalize_visible_opponents(
        raw_payload.get("visible_opponents")
        or raw_payload.get("opponents")
        or raw_payload.get("opponent_hands")
    )
    position = _normalize_position(raw_payload.get("hero_position") or raw_payload.get("position"))
    button_position = _normalize_position(raw_payload.get("button_position") or raw_payload.get("dealer_button"))
    pot_size = _normalize_number(raw_payload.get("pot_size") or raw_payload.get("pot"))
    bet_to_call = _normalize_number(
        raw_payload.get("bet_to_call")
        or raw_payload.get("call_amount")
        or raw_payload.get("facing_bet")
    )
    effective_stack = _normalize_number(
        raw_payload.get("effective_stack")
        or raw_payload.get("effective_stack_bb")
        or raw_payload.get("hero_stack")
    )
    layout_detected = _normalize_layout(
        raw_payload.get("layout_detected")
        or raw_payload.get("layout")
        or raw_payload.get("site")
        or raw_payload.get("table_skin")
    )
    is_preflop_aggressor = _normalize_bool(
        raw_payload.get("is_preflop_aggressor")
        or raw_payload.get("hero_is_preflop_aggressor")
        or raw_payload.get("preflop_aggressor")
    )
    action_history = _normalize_action_history(raw_payload.get("action_history") or raw_payload.get("notes"))

    warnings: List[str] = []
    missing_fields: List[str] = []

    if not hero_cards:
        missing_fields.append("hole_cards")
        warnings.append("Hero hole cards were not confidently read from the screenshot.")
    if len(board) not in {0, 3, 4, 5}:
        warnings.append("Board cards were detected, but the count is not a standard street.")
    if not position:
        missing_fields.append("position")
        warnings.append("Hero position was not confidently visible.")
    if pot_size is None:
        missing_fields.append("pot_size")
    if bet_to_call is None:
        missing_fields.append("bet_to_call")
    if effective_stack is None:
        missing_fields.append("effective_stack")
        warnings.append("Effective stack was not clearly readable.")
    if is_preflop_aggressor is None:
        missing_fields.append("is_preflop_aggressor")
    if source_hint not in SUPPORTED_SOURCES:
        warnings.append(f"Unsupported source hint '{source_hint}' was normalized as generic online table UI.")

    raw_confidence = raw_payload.get("overall_confidence") or raw_payload.get("confidence")
    confidence = _normalize_number(raw_confidence)
    if confidence is not None and confidence > 1:
        confidence = confidence / 100.0
    if confidence is None:
        confidence = 1.0 - (0.12 * len(missing_fields)) - (0.04 * len(warnings))
    confidence = round(max(0.0, min(1.0, confidence)), 2)

    return {
        "source_hint": "online_table_ui",
        "hero_cards": hero_cards,
        "board": board,
        "position": position,
        "button_position": button_position,
        "pot_size": pot_size,
        "bet_to_call": bet_to_call,
        "effective_stack": effective_stack,
        "is_preflop_aggressor": is_preflop_aggressor,
        "action_history": action_history,
        "visible_opponents": visible_opponents,
        "warnings": warnings,
        "missing_fields": missing_fields,
        "parse_confidence": confidence,
        "layout_detected": layout_detected,
        "raw_payload": raw_payload,
    }


class PokerScreenshotParser:
    """Uses a vision-capable model to extract state from online poker screenshots."""

    MODEL_PRIORITY = ("claude", "gemini", "openai", "openrouter", "xai", "deepseek", "groq", "ollama", "bridge")

    def __init__(self, factory: Optional[ModelFactory] = None):
        self.factory = factory or ModelFactory()

    def _iter_vision_models(self):
        seen = set()
        for model_type in self.MODEL_PRIORITY:
            model = self.factory.get_model(model_type)
            if not model or not hasattr(model, "generate_response_with_image"):
                continue
            model_name = getattr(model, "model_name", model.__class__.__name__)
            if model_name in seen:
                continue
            seen.add(model_name)
            yield model_type, model

    def _get_vision_model(self):
        for _, model in self._iter_vision_models():
            return model
        raise VisionModelUnavailableError(
            "No configured vision-capable model is available. Add a supported API key such as ANTHROPIC_KEY."
        )

    def analyze(
        self,
        image_data: str,
        image_type: Optional[str] = None,
        source_hint: str = "online_table_ui",
        layout_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        if source_hint not in SUPPORTED_SOURCES:
            raise ScreenshotParserError(f"Unsupported screenshot source hint: {source_hint}")

        payload, media_type = _strip_data_url(image_data, image_type)
        prompt = self._build_prompt(layout_hint=layout_hint)
        errors = []

        for model_type, model in self._iter_vision_models():
            try:
                response = model.generate_response_with_image(
                    system_prompt="Extract visible online poker table state. Return strict JSON only.",
                    user_content=prompt,
                    image_data=payload,
                    image_media_type=media_type,
                    temperature=0.0,
                    max_tokens=900,
                )
                content = response.content if hasattr(response, "content") else str(response)
                raw_payload = _extract_json_object(content)
                normalized = normalize_screenshot_payload(raw_payload, source_hint=source_hint)
                normalized["image_type"] = media_type
                normalized["model_name"] = getattr(model, "model_name", model.__class__.__name__)
                return normalized
            except Exception as exc:
                model_name = getattr(model, "model_name", model.__class__.__name__)
                errors.append(f"{model_type}/{model_name}: {_summarize_model_error(exc)}")

        if errors:
            raise VisionModelUnavailableError(
                "No configured vision-capable model could parse the screenshot. "
                f"Tried {len(errors)} provider(s): {'; '.join(errors[:3])}"
            )

        raise VisionModelUnavailableError(
            "No configured vision-capable model is available. Add a supported API key such as ANTHROPIC_KEY."
        )

    def _build_prompt(self, layout_hint: Optional[str] = None) -> str:
        layout_line = ""
        if layout_hint:
            layout_line = f'- Optional layout hint from caller: "{layout_hint}". Use it only as soft context, not as a fact.\n'

        return f"""
Analyze this screenshot of an ONLINE poker table UI and return ONLY valid JSON.

Rules:
- Read only what is visibly on screen.
- Never invent hidden opponent cards.
- If a field is unclear, use null instead of guessing.
- If you can recognize the site or table skin, return it in layout_detected. Otherwise use null.
- Hero hole cards must be returned separately from the board.
- "dealer" means board/community cards plus dealer/button position if visible.
- Use simple seat labels when player names are unclear.
- Pot, bet_to_call, and effective_stack should be numeric when possible.
- action_history should be a short list of visible line hints only.
- Keep the response compact.
{layout_line}

Return exactly this shape:
{{
  "hero_cards": ["Ah", "Ks"],
  "board": ["Td", "7c", "2h"],
  "layout_detected": "CoinPoker",
  "hero_position": "BTN",
  "button_position": "BTN",
  "pot_size": 15.5,
  "bet_to_call": 5.0,
  "effective_stack": 92.0,
  "is_preflop_aggressor": true,
  "visible_opponents": [
    {{
      "seat": "Villain 1",
      "position": "BB",
      "visible_cards": ["Qh", "Qd"],
      "note": "showdown"
    }}
  ],
  "action_history": ["open 2.5bb", "bb call", "flop cbet 33%"],
  "notes": "short note if anything is ambiguous",
  "overall_confidence": 0.84
}}
""".strip()
