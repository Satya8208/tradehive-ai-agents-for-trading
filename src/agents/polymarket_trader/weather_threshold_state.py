"""Threshold state checks for known/near-known weather outcomes."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .weather_blockers import blocker_summary, blockers_to_records
from .weather_station_observation_state import WeatherStationObservationState


THRESHOLD_STATE_SCHEMA_VERSION = "weather_threshold_state_v1"


@dataclass(frozen=True)
class WeatherThresholdState:
    status: str
    metric: str
    operator: str
    threshold: Optional[float]
    upper_threshold: Optional[float]
    p_yes: Optional[float]
    p_yes_source: str
    probability_role: str
    recommended_side: str
    already_crossed_threshold: bool
    official_observation_supports_yes: bool
    official_observation_supports_no: bool
    near_certain_yes_score: float
    near_certain_no_score: float
    schema_version: str = THRESHOLD_STATE_SCHEMA_VERSION
    remaining_window_minutes: Optional[float] = None
    source_officialness_score: float = 0.85
    station_observation_age_seconds: Optional[float] = None
    metric_rounding_risk: str = "medium"
    timezone_window_risk: str = "medium"
    observed_value: Optional[float] = None
    decision_margin: Optional[float] = None
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["blocker_records"] = blockers_to_records(self.blockers)
        payload["blocker_summary"] = blocker_summary(self.blockers)
        return payload


class WeatherThresholdStateEvaluator:
    def evaluate(
        self,
        *,
        metric: str,
        operator: str,
        threshold: Optional[float],
        upper_threshold: Optional[float] = None,
        station_state: WeatherStationObservationState | Dict[str, Any],
        market_end: Optional[datetime] = None,
        now: Optional[datetime] = None,
    ) -> WeatherThresholdState:
        now = now or datetime.utcnow()
        state = station_state.to_dict() if hasattr(station_state, "to_dict") else dict(station_state or {})
        blockers: List[str] = list(state.get("blockers", []) or [])
        flags: List[str] = ["observation_lag_research_only"]
        remaining_minutes = None
        if market_end is not None:
            remaining_minutes = max(0.0, (market_end - now).total_seconds() / 60.0)

        if threshold is None:
            blockers.append("threshold_missing")
            return self._blocked(metric, operator, threshold, upper_threshold, blockers, flags, remaining_minutes, state)
        if operator == "between" and upper_threshold is None:
            blockers.append("upper_threshold_missing")
            return self._blocked(metric, operator, threshold, upper_threshold, blockers, flags, remaining_minutes, state)

        observed_value = self._observed_value(metric, state)
        if observed_value is None:
            blockers.append(f"observation_metric_missing:{metric}")
            return self._blocked(metric, operator, threshold, upper_threshold, blockers, flags, remaining_minutes, state)

        supports_yes = False
        supports_no = False
        crossed = False
        p_yes: Optional[float] = None
        p_yes_source = "unavailable"
        probability_role = "blocked"
        decision_margin: Optional[float] = None
        rounding_buffer = self._rounding_buffer(metric)

        if operator == "between" and upper_threshold is not None:
            lower = min(float(threshold), float(upper_threshold))
            upper = max(float(threshold), float(upper_threshold))
            if metric in {"temperature_high", "wind", "wind_gust", "precipitation", "snowfall"} and observed_value > upper:
                decision_margin = observed_value - upper
                if decision_margin < rounding_buffer:
                    blockers.append("threshold_boundary_rounding_risk")
                    flags.append("boundary_rounding_buffer_applied")
                else:
                    crossed = True
                    supports_no = True
                    p_yes = 0.015
            elif metric == "temperature_low" and observed_value < lower:
                decision_margin = lower - observed_value
                if decision_margin < rounding_buffer:
                    blockers.append("threshold_boundary_rounding_risk")
                    flags.append("boundary_rounding_buffer_applied")
                else:
                    crossed = True
                    supports_no = True
                    p_yes = 0.015
        elif metric == "temperature_high":
            if operator == "above" and observed_value >= threshold:
                decision_margin = observed_value - float(threshold)
                if decision_margin < rounding_buffer:
                    blockers.append("threshold_boundary_rounding_risk")
                    flags.append("boundary_rounding_buffer_applied")
                else:
                    crossed = True
                    supports_yes = True
                    p_yes = 0.985
            elif operator == "below" and observed_value > threshold:
                decision_margin = observed_value - float(threshold)
                if decision_margin < rounding_buffer:
                    blockers.append("threshold_boundary_rounding_risk")
                    flags.append("boundary_rounding_buffer_applied")
                else:
                    crossed = True
                    supports_no = True
                    p_yes = 0.015
        elif metric == "temperature_low":
            if operator == "below" and observed_value <= threshold:
                decision_margin = float(threshold) - observed_value
                if decision_margin < rounding_buffer:
                    blockers.append("threshold_boundary_rounding_risk")
                    flags.append("boundary_rounding_buffer_applied")
                else:
                    crossed = True
                    supports_yes = True
                    p_yes = 0.985
            elif operator == "above" and observed_value < threshold:
                decision_margin = float(threshold) - observed_value
                if decision_margin < rounding_buffer:
                    blockers.append("threshold_boundary_rounding_risk")
                    flags.append("boundary_rounding_buffer_applied")
                else:
                    crossed = True
                    supports_no = True
                    p_yes = 0.015
        elif metric in {"wind", "wind_gust", "precipitation", "snowfall"}:
            if operator == "above" and observed_value >= threshold:
                decision_margin = observed_value - float(threshold)
                if decision_margin < rounding_buffer:
                    blockers.append("threshold_boundary_rounding_risk")
                    flags.append("boundary_rounding_buffer_applied")
                else:
                    crossed = True
                    supports_yes = True
                    p_yes = 0.97
            elif operator == "below" and observed_value > threshold:
                decision_margin = observed_value - float(threshold)
                if decision_margin < rounding_buffer:
                    blockers.append("threshold_boundary_rounding_risk")
                    flags.append("boundary_rounding_buffer_applied")
                else:
                    crossed = True
                    supports_no = True
                    p_yes = 0.03

        if p_yes is None:
            if remaining_minutes is not None and remaining_minutes <= 30 and operator == "below":
                # Conservative near-close support only. This is not settlement truth.
                supports_yes = True
                p_yes = 0.78
                p_yes_source = "near_close_observation_heuristic"
                probability_role = "heuristic_probability"
                flags.append("near_close_no_crossing_support")
            else:
                blockers.append("threshold_not_known_from_observations")
        else:
            p_yes_source = "official_observation_fact"
            probability_role = "settlement_fact"

        near_yes = max(0.0, min(1.0, p_yes or 0.0))
        near_no = max(0.0, min(1.0, 1.0 - (p_yes or 0.0)))
        status = "known_or_near_known" if p_yes is not None else "not_known"
        side = "YES" if (p_yes or 0.0) >= 0.5 else "NO"

        return WeatherThresholdState(
            status=status,
            metric=metric,
            operator=operator,
            threshold=threshold,
            upper_threshold=upper_threshold,
            p_yes=round(p_yes, 4) if p_yes is not None else None,
            p_yes_source=p_yes_source if p_yes is not None else "unavailable",
            probability_role=probability_role if p_yes is not None else "blocked",
            recommended_side=side if p_yes is not None else "",
            already_crossed_threshold=crossed,
            official_observation_supports_yes=supports_yes,
            official_observation_supports_no=supports_no,
            near_certain_yes_score=round(near_yes, 4),
            near_certain_no_score=round(near_no, 4),
            remaining_window_minutes=round(remaining_minutes, 3) if remaining_minutes is not None else None,
            station_observation_age_seconds=state.get("latest_observation_age_seconds"),
            observed_value=round(float(observed_value), 4),
            decision_margin=round(float(decision_margin), 4) if decision_margin is not None else None,
            blockers=sorted(set(blockers)),
            quality_flags=sorted(set(flags)),
        )

    def _blocked(
        self,
        metric: str,
        operator: str,
        threshold: Optional[float],
        upper_threshold: Optional[float],
        blockers: List[str],
        flags: List[str],
        remaining_minutes: Optional[float],
        state: Dict[str, Any],
    ) -> WeatherThresholdState:
        return WeatherThresholdState(
            status="blocked",
            metric=metric,
            operator=operator,
            threshold=threshold,
            upper_threshold=upper_threshold,
            p_yes=None,
            p_yes_source="unavailable",
            probability_role="blocked",
            recommended_side="",
            already_crossed_threshold=False,
            official_observation_supports_yes=False,
            official_observation_supports_no=False,
            near_certain_yes_score=0.0,
            near_certain_no_score=0.0,
            remaining_window_minutes=round(remaining_minutes, 3) if remaining_minutes is not None else None,
            station_observation_age_seconds=state.get("latest_observation_age_seconds"),
            blockers=sorted(set(blockers)),
            quality_flags=sorted(set(flags)),
        )

    @staticmethod
    def _observed_value(metric: str, state: Dict[str, Any]) -> Optional[float]:
        key_by_metric = {
            "temperature_high": "observed_max_temp_f",
            "temperature_low": "observed_min_temp_f",
            "precipitation": "observed_precipitation_in",
            "snowfall": "observed_precipitation_in",
            "wind": "observed_max_wind_mph",
            "wind_gust": "observed_max_gust_mph",
        }
        key = key_by_metric.get(metric)
        if not key:
            return None
        try:
            parsed = float(state.get(key))
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    @staticmethod
    def _rounding_buffer(metric: str) -> float:
        if metric in {"temperature_high", "temperature_low"}:
            return 0.5
        if metric in {"precipitation", "snowfall"}:
            return 0.01
        if metric in {"wind", "wind_gust"}:
            return 0.5
        return 0.0
