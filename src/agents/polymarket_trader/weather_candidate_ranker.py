"""
Candidate ranking for Polymarket weather markets.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import PolymarketCLIConfig
from .models import CLIMarket
from .weather_contracts import WeatherCandidate


class WeatherCandidateRanker:
    def __init__(self, config: PolymarketCLIConfig):
        self.config = config

    def build_candidate(self, market: CLIMarket, context: Dict[str, Any]) -> WeatherCandidate:
        blockers: List[str] = []
        if context.get("status") != "ok":
            blockers.append(f"weather_context_{context.get('status', 'missing')}")
        blockers.extend(str(item) for item in context.get("feature_blockers", []) if str(item).strip())

        ai_decision = dict(context.get("ai_decision", {}) or {})
        forecast_model_packet = dict(context.get("forecast_model_packet", {}) or {})
        ai_usable = bool(ai_decision.get("usable_for_paper")) and str(
            getattr(self.config, "weather_ai_autonomy_mode", "paper_only") or ""
        ) == "paper_only"
        probability_source = "deterministic_forecast"
        probability = self._safe_float(context.get("weather_probability"))
        if ai_usable:
            ai_probability = self._safe_float(ai_decision.get("p_yes"))
            if ai_probability is not None:
                probability = ai_probability
                probability_source = "ai_forecast_decision"
        if probability is None:
            blockers.append("weather_probability_missing")
            probability = 0.5

        side = str(
            ai_decision.get("side") if ai_usable else context.get("recommended_side")
            or ("YES" if probability >= float(market.yes_price or 0.0) else "NO")
        ).upper()
        if side not in {"YES", "NO"}:
            blockers.append("weather_side_invalid")
            side = "YES"

        if ai_usable:
            for veto in ai_decision.get("veto_reasons", []) or []:
                veto_text = str(veto).strip().lower().replace(" ", "_")
                if veto_text:
                    blockers.append(f"weather_ai_veto:{veto_text[:80]}")
        elif bool(getattr(self.config, "weather_ai_decision_required", False)):
            ai_status = str(ai_decision.get("status") or "missing")
            blockers.append(f"weather_ai_decision_not_usable:{ai_status}")

        market_probability = float(market.yes_price if side == "YES" else market.no_price)
        if market_probability <= 0:
            market_probability = float(market.yes_price if side == "YES" else max(0.001, 1.0 - float(market.yes_price or 0.0)))

        raw_edge_percent = self._safe_float(context.get("weather_edge_percent"))
        if ai_usable:
            raw_edge_percent = None
        if raw_edge_percent is None:
            edge = (probability - float(market.yes_price or 0.0)) * 100.0
        else:
            edge = raw_edge_percent
        if side == "NO" and edge > 0:
            edge = -edge

        min_gap_percent = float(getattr(self.config, "weather_min_probability_gap", 0.08) or 0.08) * 100.0
        if abs(edge) < min_gap_percent:
            blockers.append("weather_edge_below_research_gap")

        if float(getattr(market, "liquidity", 0.0) or 0.0) < float(getattr(self.config, "min_liquidity_usd", 0.0) or 0.0):
            blockers.append("weather_liquidity_below_minimum")

        confidence = self._safe_float(context.get("weather_confidence"))
        if ai_usable:
            confidence = self._safe_float(ai_decision.get("confidence"))
        if confidence is None:
            confidence = 0.5
        station_bias = dict(context.get("station_bias", {}) or {})
        latency_signals = dict(context.get("latency_signals", {}) or {})
        model_update_events = [dict(item) for item in context.get("model_update_events", []) or []]
        high_resolution_sources = [dict(item) for item in context.get("high_resolution_sources", []) or []]
        quality_flags = [str(item) for item in context.get("quality_flags", [])]
        bias_status = str(station_bias.get("status") or "")
        if bias_status:
            quality_flags.append(f"station_bias_status:{bias_status}")
        if high_resolution_sources:
            quality_flags.append("high_resolution_sources_manifested")
        if latency_signals:
            quality_flags.append(f"latency_status:{latency_signals.get('status', 'unknown')}")
        if probability_source == "ai_forecast_decision":
            quality_flags.append("ai_forecast_decision_used")
            lane = str(ai_decision.get("strategy_lane") or "").strip()
            if lane:
                quality_flags.append(f"ai_strategy_lane:{lane}")
        elif ai_decision:
            quality_flags.append(f"ai_forecast_decision_status:{ai_decision.get('status', 'unknown')}")
        size = min(float(getattr(self.config, "max_position_usd", 0.0) or 0.0), float(getattr(market, "liquidity", 0.0) or 0.0))
        if ai_usable:
            ai_size = self._safe_float(ai_decision.get("recommended_size_usd"))
            if ai_size is not None and ai_size > 0:
                size = min(size, ai_size)
        size = max(float(getattr(self.config, "min_position_usd", 0.0) or 0.0), size)
        score = abs(edge) * max(0.1, confidence)

        return WeatherCandidate(
            market_id=str(getattr(market, "condition_id", "")),
            side=side,
            model_probability=round(probability, 4),
            market_probability=round(market_probability, 4),
            edge_percent=round(edge, 2),
            confidence=round(confidence, 4),
            score=round(score, 4),
            size_usd=round(size, 2),
            limit_price=round(market_probability, 4),
            edge_reason_flags=[str(item) for item in context.get("edge_reason_flags", [])],
            quality_flags=sorted(set(quality_flags)),
            blockers=sorted(set(blockers)),
            station_bias=station_bias,
            latency_signals=latency_signals,
            model_update_events=model_update_events,
            high_resolution_sources=high_resolution_sources,
            forecast_model_packet=forecast_model_packet,
            ai_decision=ai_decision,
        )

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed
