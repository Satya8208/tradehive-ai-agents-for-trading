"""
AI portfolio-manager decision layer for weather paper trading.

The model is allowed to be creative only inside an auditable JSON contract.
Invalid or overconfident output fails closed and can be replayed later.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, Optional

from .config import PolymarketCLIConfig
from .weather_contracts import AI_DECISION_SCHEMA_VERSION, WeatherAIDecision


SYSTEM_PROMPT = """You are the lead portfolio manager for a weather prediction-market research desk.

You receive a source-stamped weather packet for one Polymarket market. Decide whether
the TRUE probability of YES differs enough from the market price to justify a paper
trade. Use the data, not vibes. Prefer no trade when the resolution rule, data quality,
forecast delta, or executable depth is weak.

Return ONLY a valid JSON object with these keys:
{
  "p_yes": 0.0 to 1.0,
  "side": "YES" or "NO",
  "strategy_lane": "forecast_run_shock" or "station_specific_edge" or "model_bias_edge" or "uncertainty_pricing" or "nowcast_override" or "narrative_fade" or "structure_check" or "forecast_model_baseline",
  "confidence": 0.0 to 1.0,
  "uncertainty_band": {"low": 0.0 to 1.0, "high": 0.0 to 1.0},
  "trade_thesis": "one concise sentence",
  "veto_reasons": [],
  "data_quality": "high" or "medium" or "limited" or "poor",
  "recommended_size_usd": 0.0
}
"""


class WeatherAIDecisioner:
    """Call and validate the lead AI model for paper-only weather autonomy."""

    def __init__(self, config: PolymarketCLIConfig, model_factory: Optional[Any] = None):
        self.config = config
        self.model_factory = model_factory
        self._factory_loaded = model_factory is not None

    def decide(self, forecast_packet: Dict[str, Any]) -> WeatherAIDecision:
        if not bool(getattr(self.config, "weather_ai_forecast_engine_enabled", True)):
            return self._decision(
                status="disabled",
                p_yes=None,
                side="",
                strategy_lane="",
                confidence=0.0,
                blockers=[],
                quality_flags=["weather_ai_disabled"],
            )
        if str(getattr(self.config, "weather_ai_autonomy_mode", "paper_only") or "") == "disabled":
            return self._decision(
                status="disabled",
                p_yes=None,
                side="",
                strategy_lane="",
                confidence=0.0,
                blockers=[],
                quality_flags=["weather_ai_autonomy_disabled"],
            )

        model = self._lead_model()
        if model is None:
            return self._decision(
                status="model_unavailable",
                p_yes=None,
                side="",
                strategy_lane="",
                confidence=0.0,
                blockers=[self._model_unavailable_blocker()],
                quality_flags=["weather_ai_model_unavailable"],
            )

        try:
            response = model.generate_response(
                SYSTEM_PROMPT,
                json.dumps(forecast_packet, sort_keys=True, default=str),
                temperature=0.1,
                max_tokens=int(getattr(self.config, "weather_ai_max_tokens", 900) or 900),
            )
            content = self._response_content(response)
        except Exception as exc:
            return self._decision(
                status="model_error",
                p_yes=None,
                side="",
                strategy_lane="",
                confidence=0.0,
                blockers=[f"weather_ai_model_error:{type(exc).__name__}"],
                quality_flags=["weather_ai_model_error"],
            )

        return self.parse_decision(
            content,
            provider=str(getattr(self.config, "weather_ai_lead_provider", "openai") or "openai"),
            model_name=str(getattr(self.config, "weather_ai_lead_model", "gpt-5.5") or "gpt-5.5"),
            forecast_packet=forecast_packet,
        )

    def parse_decision(
        self,
        content: str,
        *,
        provider: str = "",
        model_name: str = "",
        forecast_packet: Optional[Dict[str, Any]] = None,
    ) -> WeatherAIDecision:
        try:
            payload = json.loads(self._extract_json_object(content))
        except Exception as exc:
            return self._decision(
                status="invalid_json",
                provider=provider,
                model_name=model_name,
                p_yes=None,
                side="",
                strategy_lane="",
                confidence=0.0,
                blockers=[f"weather_ai_invalid_json:{type(exc).__name__}"],
                raw_response=content,
            )
        if not isinstance(payload, dict):
            return self._decision(
                status="invalid_shape",
                provider=provider,
                model_name=model_name,
                p_yes=None,
                side="",
                strategy_lane="",
                confidence=0.0,
                blockers=["weather_ai_payload_not_object"],
                raw_response=content,
            )

        p_yes = self._probability(payload.get("p_yes"))
        side = str(payload.get("side") or "").upper()
        confidence = self._probability(payload.get("confidence"))
        lane = str(payload.get("strategy_lane") or "").strip().lower()
        data_quality = str(payload.get("data_quality") or "unknown").strip().lower()
        uncertainty = self._uncertainty_band(payload.get("uncertainty_band"))
        veto_reasons = [
            self._clean_text(item)
            for item in payload.get("veto_reasons", []) or []
            if self._clean_text(item)
        ]
        recommended_size = self._safe_float(payload.get("recommended_size_usd")) or 0.0

        blockers = []
        if p_yes is None:
            blockers.append("weather_ai_p_yes_missing")
        if side not in {"YES", "NO"}:
            blockers.append("weather_ai_side_invalid")
        if confidence is None:
            blockers.append("weather_ai_confidence_missing")
            confidence = 0.0
        if not lane:
            blockers.append("weather_ai_strategy_lane_missing")
        if data_quality not in {"high", "medium", "limited", "poor"}:
            blockers.append(f"weather_ai_data_quality_invalid:{data_quality or 'missing'}")
        blockers.extend(self._overconfidence_blockers(confidence, data_quality, forecast_packet or {}))

        status = "ok" if not blockers else "invalid_decision"
        return self._decision(
            status=status,
            provider=provider,
            model_name=model_name,
            p_yes=p_yes,
            side=side,
            strategy_lane=lane,
            confidence=confidence,
            uncertainty_band=uncertainty,
            trade_thesis=self._clean_text(payload.get("trade_thesis")),
            veto_reasons=veto_reasons,
            data_quality=data_quality,
            recommended_size_usd=max(0.0, recommended_size),
            blockers=blockers,
            quality_flags=["weather_ai_decision", f"weather_ai_data_quality:{data_quality}"],
            raw_response=content,
        )

    def _lead_model(self) -> Optional[Any]:
        provider = str(getattr(self.config, "weather_ai_lead_provider", "openai") or "openai").strip().lower()
        model_name = str(getattr(self.config, "weather_ai_lead_model", "gpt-5.5") or "").strip()
        if not self._factory_loaded:
            try:
                from src.models.model_factory import ModelFactory

                self.model_factory = ModelFactory()
                self._factory_loaded = True
            except Exception:
                return None
        if self.model_factory is None:
            return None
        try:
            return self.model_factory.get_model(provider, model_name)
        except Exception:
            return None

    def _model_unavailable_blocker(self) -> str:
        provider = str(getattr(self.config, "weather_ai_lead_provider", "openai") or "openai")
        model_name = str(getattr(self.config, "weather_ai_lead_model", "gpt-5.5") or "gpt-5.5")
        return f"weather_ai_model_unavailable:{provider}/{model_name}"

    @staticmethod
    def _response_content(response: Any) -> str:
        if response is None:
            return ""
        content = getattr(response, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(response, str):
            return response
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(getattr(item, "text", "") or ""))
            return "\n".join(part for part in parts if part)
        return str(response)

    @staticmethod
    def _extract_json_object(content: str) -> str:
        text = str(content or "").strip()
        if text.startswith("{") and text.endswith("}"):
            return text
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("json_object_missing")
        return match.group(0)

    @staticmethod
    def _uncertainty_band(value: Any) -> Dict[str, Optional[float]]:
        if not isinstance(value, dict):
            return {"low": None, "high": None}
        low = WeatherAIDecisioner._probability(value.get("low"))
        high = WeatherAIDecisioner._probability(value.get("high"))
        if low is not None and high is not None and low > high:
            low, high = high, low
        return {"low": low, "high": high}

    @staticmethod
    def _overconfidence_blockers(confidence: float, data_quality: str, packet: Dict[str, Any]) -> list[str]:
        blockers = []
        source_count = 0
        disagreement = packet.get("model_disagreement", {}) if isinstance(packet, dict) else {}
        if isinstance(disagreement, dict):
            try:
                source_count = int(disagreement.get("source_count") or 0)
            except (TypeError, ValueError):
                source_count = 0
        execution = packet.get("execution_context", {}) if isinstance(packet, dict) else {}
        has_orderbook = isinstance(execution, dict) and execution.get("status") == "market_tape_attached"
        if data_quality in {"poor", "limited"} and confidence > 0.70:
            blockers.append("weather_ai_overconfident_for_data_quality")
        if source_count <= 1 and confidence > 0.80:
            blockers.append("weather_ai_overconfident_single_source")
        if not has_orderbook and confidence > 0.90:
            blockers.append("weather_ai_overconfident_without_orderbook")
        return blockers

    def _decision(
        self,
        *,
        status: str,
        p_yes: Optional[float],
        side: str,
        strategy_lane: str,
        confidence: float,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        uncertainty_band: Optional[Dict[str, Optional[float]]] = None,
        trade_thesis: str = "",
        veto_reasons: Optional[list[str]] = None,
        data_quality: str = "unknown",
        recommended_size_usd: float = 0.0,
        blockers: Optional[list[str]] = None,
        quality_flags: Optional[list[str]] = None,
        raw_response: str = "",
    ) -> WeatherAIDecision:
        return WeatherAIDecision(
            status=status,
            provider=provider
            if provider is not None
            else str(getattr(self.config, "weather_ai_lead_provider", "openai") or "openai"),
            model_name=model_name
            if model_name is not None
            else str(getattr(self.config, "weather_ai_lead_model", "gpt-5.5") or "gpt-5.5"),
            p_yes=p_yes,
            side=side,
            strategy_lane=strategy_lane,
            confidence=round(max(0.0, min(1.0, float(confidence or 0.0))), 4),
            uncertainty_band=dict(uncertainty_band or {"low": None, "high": None}),
            trade_thesis=trade_thesis,
            veto_reasons=list(veto_reasons or []),
            data_quality=data_quality,
            recommended_size_usd=round(max(0.0, float(recommended_size_usd or 0.0)), 4),
            blockers=sorted(set(str(item) for item in blockers or [] if str(item).strip())),
            quality_flags=sorted(set([AI_DECISION_SCHEMA_VERSION, *list(quality_flags or [])])),
            raw_response=raw_response,
        )

    @staticmethod
    def _probability(value: Any) -> Optional[float]:
        parsed = WeatherAIDecisioner._safe_float(value)
        if parsed is None:
            return None
        return round(max(0.0, min(1.0, parsed)), 4)

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    @staticmethod
    def _clean_text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()
