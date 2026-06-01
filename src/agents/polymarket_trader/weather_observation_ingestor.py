"""
Observation ingestion for known-outcome weather alpha research.

Uses NOAA Aviation Weather Center's public Data API for METAR observations.
The endpoint is deliberately narrow and fails closed when observations are
missing or malformed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import requests

from .weather_asos_metar_parser import WeatherASOSMetarParser, WeatherMetarObservation


OBSERVATION_INGEST_SCHEMA_VERSION = "weather_observation_ingest_v1"


@dataclass(frozen=True)
class WeatherObservationIngestResult:
    station_ids: List[str]
    status: str
    observations: List[Dict[str, Any]]
    schema_version: str = OBSERVATION_INGEST_SCHEMA_VERSION
    source: str = "aviationweather_awc_metar"
    request_url: str = "https://aviationweather.gov/api/data/metar"
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherObservationIngestor:
    def __init__(
        self,
        session: Optional[requests.Session] = None,
        parser: Optional[WeatherASOSMetarParser] = None,
        user_agent: str = "tradehive-polymarket-weather-research/1.0",
    ):
        self.session = session or requests.Session()
        self.parser = parser or WeatherASOSMetarParser()
        self.user_agent = user_agent

    def fetch_metar_observations(
        self,
        station_ids: Iterable[str],
        *,
        hours: int = 12,
        timeout: int = 15,
    ) -> WeatherObservationIngestResult:
        stations = sorted({str(station or "").strip().upper() for station in station_ids if str(station or "").strip()})
        if not stations:
            return WeatherObservationIngestResult(
                station_ids=[],
                status="blocked",
                observations=[],
                blockers=["missing_station_ids"],
            )
        params = {
            "ids": ",".join(stations),
            "format": "json",
            "hours": max(1, min(int(hours), 48)),
            "taf": "false",
        }
        try:
            response = self.session.get(
                "https://aviationweather.gov/api/data/metar",
                params=params,
                headers={"User-Agent": self.user_agent},
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            return WeatherObservationIngestResult(
                station_ids=stations,
                status="error",
                observations=[],
                blockers=[f"metar_fetch_error:{type(exc).__name__}"],
            )

        observations = self.parser.parse_awc_payload(payload)
        if not observations:
            return WeatherObservationIngestResult(
                station_ids=stations,
                status="empty",
                observations=[],
                blockers=["metar_observations_empty"],
            )
        return WeatherObservationIngestResult(
            station_ids=stations,
            status="ok",
            observations=[observation.to_dict() for observation in observations],
            quality_flags=["official_awc_data_api", "raw_metar_preserved"],
        )

    @staticmethod
    def observations_from_jsonl(lines: Iterable[str]) -> List[WeatherMetarObservation]:
        parser = WeatherASOSMetarParser()
        observations: List[WeatherMetarObservation] = []
        for line in lines:
            if not str(line or "").strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("schema_version") == "weather_metar_observation_v1":
                observations.append(
                    WeatherMetarObservation(
                        station_id=str(payload.get("station_id", "")),
                        observed_at=str(payload.get("observed_at", "")),
                        raw_text=str(payload.get("raw_text", "")),
                        source=str(payload.get("source", "")),
                        temp_c=payload.get("temp_c"),
                        temp_f=payload.get("temp_f"),
                        wind_speed_kt=payload.get("wind_speed_kt"),
                        wind_speed_mph=payload.get("wind_speed_mph"),
                        wind_gust_kt=payload.get("wind_gust_kt"),
                        wind_gust_mph=payload.get("wind_gust_mph"),
                        precipitation_in=payload.get("precipitation_in"),
                        present_weather=str(payload.get("present_weather", "")),
                        quality_flags=list(payload.get("quality_flags", []) or []),
                        blockers=list(payload.get("blockers", []) or []),
                    )
                )
            else:
                observations.extend(parser.parse_awc_payload(payload))
        return observations
