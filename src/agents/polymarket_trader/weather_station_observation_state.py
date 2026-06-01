"""Aggregate station observations into threshold-ready state."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .weather_asos_metar_parser import WeatherMetarObservation


STATION_OBSERVATION_STATE_SCHEMA_VERSION = "weather_station_observation_state_v1"


@dataclass(frozen=True)
class WeatherStationObservationState:
    station_id: str
    observation_count: int
    schema_version: str = STATION_OBSERVATION_STATE_SCHEMA_VERSION
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    first_observed_at: str = ""
    latest_observed_at: str = ""
    latest_observation_age_seconds: Optional[float] = None
    observed_max_temp_f: Optional[float] = None
    observed_min_temp_f: Optional[float] = None
    observed_max_wind_mph: Optional[float] = None
    observed_max_gust_mph: Optional[float] = None
    observed_precipitation_in: Optional[float] = None
    present_weather_seen: List[str] = field(default_factory=list)
    raw_observations: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherStationObservationStateBuilder:
    def build(
        self,
        station_id: str,
        observations: Iterable[WeatherMetarObservation | Dict[str, Any]],
        *,
        now: Optional[datetime] = None,
    ) -> WeatherStationObservationState:
        now = now or datetime.utcnow()
        station = str(station_id or "").upper()
        rows = [self._as_dict(row) for row in observations]
        if station:
            rows = [row for row in rows if str(row.get("station_id") or "").upper() == station]
        rows = [row for row in rows if row.get("observed_at")]
        rows.sort(key=lambda row: str(row.get("observed_at") or ""))

        blockers: List[str] = []
        flags: List[str] = []
        if not station:
            blockers.append("missing_station_id")
        if not rows:
            blockers.append("station_observations_empty")

        temp_values = [_float(row.get("temp_f")) for row in rows]
        temp_values = [value for value in temp_values if value is not None]
        wind_values = [_float(row.get("wind_speed_mph")) for row in rows]
        wind_values = [value for value in wind_values if value is not None]
        gust_values = [_float(row.get("wind_gust_mph")) for row in rows]
        gust_values = [value for value in gust_values if value is not None]
        precip_values = [_float(row.get("precipitation_in")) for row in rows]
        precip_values = [value for value in precip_values if value is not None and value >= 0]
        weather_seen = sorted(
            {
                str(row.get("present_weather") or "").strip()
                for row in rows
                if str(row.get("present_weather") or "").strip()
            }
        )
        if temp_values:
            flags.append("temperature_observations_present")
        if precip_values or weather_seen:
            flags.append("precipitation_signal_present")

        latest_at = str(rows[-1].get("observed_at") or "") if rows else ""
        age_seconds = self._age_seconds(latest_at, now) if latest_at else None
        if age_seconds is not None and age_seconds > 2 * 60 * 60:
            blockers.append("station_observation_stale")

        return WeatherStationObservationState(
            station_id=station,
            observation_count=len(rows),
            first_observed_at=str(rows[0].get("observed_at") or "") if rows else "",
            latest_observed_at=latest_at,
            latest_observation_age_seconds=round(age_seconds, 3) if age_seconds is not None else None,
            observed_max_temp_f=round(max(temp_values), 3) if temp_values else None,
            observed_min_temp_f=round(min(temp_values), 3) if temp_values else None,
            observed_max_wind_mph=round(max(wind_values), 3) if wind_values else None,
            observed_max_gust_mph=round(max(gust_values), 3) if gust_values else None,
            observed_precipitation_in=round(sum(precip_values), 4) if precip_values else None,
            present_weather_seen=weather_seen,
            raw_observations=[str(row.get("raw_text") or "") for row in rows if row.get("raw_text")],
            quality_flags=sorted(set(flags)),
            blockers=sorted(set(blockers)),
        )

    @staticmethod
    def _as_dict(row: WeatherMetarObservation | Dict[str, Any]) -> Dict[str, Any]:
        if hasattr(row, "to_dict"):
            return row.to_dict()
        return dict(row or {})

    @staticmethod
    def _age_seconds(observed_at: str, now: datetime) -> Optional[float]:
        try:
            parsed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
        return max(0.0, (now - parsed).total_seconds())


def _float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None
