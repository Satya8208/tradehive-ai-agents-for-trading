"""
ASOS/METAR parsing helpers for weather observation-lag research.

The parser preserves raw observations and extracts only conservative fields
needed for known/near-known threshold state checks.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


METAR_OBSERVATION_SCHEMA_VERSION = "weather_metar_observation_v1"


@dataclass(frozen=True)
class WeatherMetarObservation:
    station_id: str
    observed_at: str
    raw_text: str
    schema_version: str = METAR_OBSERVATION_SCHEMA_VERSION
    source: str = "aviationweather_awc"
    temp_c: Optional[float] = None
    temp_f: Optional[float] = None
    wind_speed_kt: Optional[float] = None
    wind_speed_mph: Optional[float] = None
    wind_gust_kt: Optional[float] = None
    wind_gust_mph: Optional[float] = None
    precipitation_in: Optional[float] = None
    present_weather: str = ""
    quality_flags: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherASOSMetarParser:
    def parse_awc_payload(self, payload: Any) -> List[WeatherMetarObservation]:
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                rows = payload.get("data", [])
            elif isinstance(payload.get("features"), list):
                rows = [self._feature_properties(item) for item in payload.get("features", [])]
            else:
                rows = [payload]
        elif isinstance(payload, list):
            rows = payload
        else:
            return []

        observations: List[WeatherMetarObservation] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            obs = self.parse_awc_row(row)
            if obs is not None:
                observations.append(obs)
        observations.sort(key=lambda obs: obs.observed_at)
        return observations

    def parse_awc_row(self, row: Dict[str, Any]) -> Optional[WeatherMetarObservation]:
        station_id = str(
            row.get("icaoId")
            or row.get("station_id")
            or row.get("stationId")
            or row.get("id")
            or ""
        ).upper()
        raw_text = str(row.get("rawOb") or row.get("raw_text") or row.get("raw_text_report") or "")
        if not station_id and raw_text:
            station_id = self._station_from_raw(raw_text)
        observed_at = self._observed_time(row, raw_text)
        if not station_id or not observed_at:
            return None

        temp_c = _optional_float(row.get("temp"))
        if temp_c is None:
            temp_c = _optional_float(row.get("temp_c"))
        if temp_c is None:
            temp_c = self._temperature_from_raw(raw_text)
        wind_speed_kt = _optional_float(row.get("wspd"))
        wind_gust_kt = _optional_float(row.get("wgst"))
        precip_in = _optional_float(row.get("precip"))
        if precip_in is None:
            precip_in = self._precip_from_raw(raw_text)

        present_weather = str(row.get("wxString") or row.get("wx_string") or self._present_weather(raw_text) or "")
        blockers: List[str] = []
        flags: List[str] = ["raw_metar_preserved"] if raw_text else []
        if temp_c is None:
            blockers.append("temperature_missing")
        if precip_in is None and present_weather:
            flags.append("present_weather_without_amount")

        return WeatherMetarObservation(
            station_id=station_id,
            observed_at=observed_at,
            raw_text=raw_text,
            temp_c=round(temp_c, 3) if temp_c is not None else None,
            temp_f=round(_c_to_f(temp_c), 3) if temp_c is not None else None,
            wind_speed_kt=round(wind_speed_kt, 3) if wind_speed_kt is not None else None,
            wind_speed_mph=round(wind_speed_kt * 1.150779, 3) if wind_speed_kt is not None else None,
            wind_gust_kt=round(wind_gust_kt, 3) if wind_gust_kt is not None else None,
            wind_gust_mph=round(wind_gust_kt * 1.150779, 3) if wind_gust_kt is not None else None,
            precipitation_in=round(precip_in, 4) if precip_in is not None else None,
            present_weather=present_weather,
            quality_flags=sorted(set(flags)),
            blockers=sorted(set(blockers)),
        )

    @staticmethod
    def _feature_properties(item: Dict[str, Any]) -> Dict[str, Any]:
        properties = item.get("properties", {}) if isinstance(item, dict) else {}
        return properties if isinstance(properties, dict) else {}

    @staticmethod
    def _station_from_raw(raw_text: str) -> str:
        match = re.search(r"^(?:METAR|SPECI)?\s*([A-Z]{4})\b", str(raw_text or "").strip())
        return match.group(1) if match else ""

    @staticmethod
    def _observed_time(row: Dict[str, Any], raw_text: str) -> str:
        raw_time = (
            row.get("obsTime")
            or row.get("obs_time")
            or row.get("reportTime")
            or row.get("time")
            or row.get("valid_time")
            or ""
        )
        parsed = _parse_datetime(raw_time)
        if parsed is not None:
            return parsed.isoformat()
        match = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", str(raw_text or ""))
        if not match:
            return ""
        now = datetime.utcnow()
        try:
            day = int(match.group(1))
            hour = int(match.group(2))
            minute = int(match.group(3))
            candidate = datetime(now.year, now.month, day, hour, minute)
        except ValueError:
            return ""
        return candidate.isoformat()

    @staticmethod
    def _temperature_from_raw(raw_text: str) -> Optional[float]:
        match = re.search(r"\b(M?\d{2})/(?:M?\d{2}|//)\b", str(raw_text or ""))
        if not match:
            return None
        return _metar_signed_number(match.group(1))

    @staticmethod
    def _precip_from_raw(raw_text: str) -> Optional[float]:
        # Prrrr is hourly precipitation in hundredths of an inch in many US METAR remarks.
        match = re.search(r"\bP(\d{4})\b", str(raw_text or ""))
        if not match:
            return None
        return int(match.group(1)) / 100.0

    @staticmethod
    def _present_weather(raw_text: str) -> str:
        tokens = []
        for token in str(raw_text or "").split():
            if re.fullmatch(r"[-+]?((RA)|(SN)|(DZ)|(PL)|(TS)|(SHRA)|(SHSN)|(FZRA))+", token):
                tokens.append(token)
        return " ".join(tokens)


def _metar_signed_number(value: str) -> Optional[float]:
    text = str(value or "").strip().upper()
    if not text:
        return None
    sign = -1.0 if text.startswith("M") else 1.0
    if text.startswith("M"):
        text = text[1:]
    try:
        parsed = float(text)
    except ValueError:
        return None
    return sign * parsed


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, ValueError, TypeError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def _optional_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _c_to_f(value: float) -> float:
    return float(value) * 9.0 / 5.0 + 32.0
