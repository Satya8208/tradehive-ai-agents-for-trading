"""
Objective behavioral features for Polymarket weather research.

These flags are not trade permission. They are research features that can be
backtested against market prices and resolved outcomes.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class WeatherBehaviorSignal:
    code: str
    strength: float
    description: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherBehaviorMonitor:
    def __init__(
        self,
        min_probability_gap: float = 0.08,
        longshot_price: float = 0.10,
        favorite_price: float = 0.85,
        momentum_points: float = 5.0,
    ):
        self.min_probability_gap = float(min_probability_gap)
        self.longshot_price = float(longshot_price)
        self.favorite_price = float(favorite_price)
        self.momentum_points = float(momentum_points)

    def evaluate(self, context: Dict[str, Any], market: Optional[Any] = None) -> Dict[str, Any]:
        yes_price = _safe_float(context.get("yes_price"))
        no_price = _safe_float(context.get("no_price"))
        if market is not None:
            yes_price = yes_price if yes_price is not None else _safe_float(getattr(market, "yes_price", None))
            no_price = no_price if no_price is not None else _safe_float(getattr(market, "no_price", None))
        probability = _safe_float(context.get("weather_probability") or context.get("model_probability"))
        threshold = _safe_float(context.get("threshold"))
        prior_value = _safe_float(context.get("prior_observation_value"))
        metric_value = self._metric_value(context)
        latency = context.get("latency_signals", {}) if isinstance(context.get("latency_signals"), dict) else {}

        signals: List[WeatherBehaviorSignal] = []
        if yes_price is not None and probability is not None:
            gap = probability - yes_price
            if yes_price <= self.longshot_price and gap >= self.min_probability_gap:
                signals.append(
                    WeatherBehaviorSignal(
                        code="longshot_underpricing_candidate",
                        strength=round(gap, 4),
                        description="YES is priced as a longshot while model probability is materially higher.",
                        details={"yes_price": yes_price, "model_probability": probability},
                    )
                )
            if yes_price >= self.favorite_price and gap <= -self.min_probability_gap:
                signals.append(
                    WeatherBehaviorSignal(
                        code="favorite_overpricing_candidate",
                        strength=round(abs(gap), 4),
                        description="YES is priced as a favorite while model probability is materially lower.",
                        details={"yes_price": yes_price, "model_probability": probability},
                    )
                )

        if threshold is not None and prior_value is not None and metric_value is not None and yes_price is not None:
            prior_crossed = prior_value >= threshold
            forecast_crosses = metric_value >= threshold
            if prior_crossed and not forecast_crosses and yes_price > 0.5:
                signals.append(
                    WeatherBehaviorSignal(
                        code="warm_recency_bias_candidate",
                        strength=round(min(1.0, yes_price - 0.5), 4),
                        description="Prior observation crossed the threshold, but current forecast no longer does.",
                        details={
                            "prior_observation_value": prior_value,
                            "forecast_value": metric_value,
                            "threshold": threshold,
                            "yes_price": yes_price,
                        },
                    )
                )
            if not prior_crossed and forecast_crosses and yes_price < 0.5:
                signals.append(
                    WeatherBehaviorSignal(
                        code="cold_recency_bias_candidate",
                        strength=round(min(1.0, 0.5 - yes_price), 4),
                        description="Prior observation missed the threshold, but current forecast now crosses it.",
                        details={
                            "prior_observation_value": prior_value,
                            "forecast_value": metric_value,
                            "threshold": threshold,
                            "yes_price": yes_price,
                        },
                    )
                )

        yes_move = _safe_float(latency.get("yes_price_change_points"))
        if yes_move is not None and probability is not None and yes_price is not None:
            model_gap_points = (probability - yes_price) * 100.0
            if abs(yes_move) >= self.momentum_points and yes_move * model_gap_points < 0:
                signals.append(
                    WeatherBehaviorSignal(
                        code="price_momentum_against_model",
                        strength=round(min(1.0, abs(yes_move) / 100.0), 4),
                        description="Recent price movement is against the model-implied edge.",
                        details={
                            "yes_price_change_points": yes_move,
                            "model_gap_points": round(model_gap_points, 4),
                        },
                    )
                )

        return {
            "behavior_signal_count": len(signals),
            "behavior_flags": [signal.code for signal in signals],
            "behavior_signals": [signal.to_dict() for signal in signals],
            "quality_flags": ["behavior_monitor_research_only"],
        }

    @staticmethod
    def _metric_value(context: Dict[str, Any]) -> Optional[float]:
        metrics = context.get("forecast_metrics", {})
        if not isinstance(metrics, dict):
            return None
        for key in (
            "high_temperature_f",
            "low_temperature_f",
            "precipitation_in",
            "snowfall_in",
            "max_wind_mph",
            "max_gust_mph",
        ):
            value = _safe_float(metrics.get(key))
            if value is not None:
                return value
        return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None
