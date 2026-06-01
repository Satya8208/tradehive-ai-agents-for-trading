"""
Station and resolution-target mapping for Polymarket weather markets.

The mapper is deliberately conservative: known city aliases resolve to explicit
stations/gridpoints, while unknown locations return a fail-closed target. The
caller can still use public forecast APIs, but trading gates can see whether
the market had an auditable station mapping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from .weather_contracts import WeatherResolutionTarget


@dataclass(frozen=True)
class WeatherLocation:
    name: str
    latitude: float
    longitude: float
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class StationOverride:
    resolution_station: str
    station_name: str
    station_type: str
    metar_station: str = ""
    nexrad_station: str = ""
    bias_correction_f: float = 0.0


class WeatherStationMapper:
    LOCATIONS: tuple[WeatherLocation, ...] = (
        WeatherLocation("New York City", 40.7128, -74.0060, ("new york city", "new york", "nyc")),
        WeatherLocation("Chicago", 41.8781, -87.6298, ("chicago",)),
        WeatherLocation("Miami", 25.7617, -80.1918, ("miami",)),
        WeatherLocation("Austin", 30.2672, -97.7431, ("austin",)),
        WeatherLocation("Los Angeles", 34.0522, -118.2437, ("los angeles", "la")),
        WeatherLocation("Philadelphia", 39.9526, -75.1652, ("philadelphia", "philly")),
        WeatherLocation("Boston", 42.3601, -71.0589, ("boston",)),
        WeatherLocation("Washington DC", 38.9072, -77.0369, ("washington dc", "washington d.c.", "dc")),
        WeatherLocation("Denver", 39.7392, -104.9903, ("denver",)),
        WeatherLocation("Dallas", 32.7767, -96.7970, ("dallas",)),
        WeatherLocation("Houston", 29.7604, -95.3698, ("houston",)),
        WeatherLocation("San Francisco", 37.7749, -122.4194, ("san francisco", "sf")),
        WeatherLocation("Phoenix", 33.4484, -112.0740, ("phoenix",)),
        WeatherLocation("Atlanta", 33.7490, -84.3880, ("atlanta",)),
        WeatherLocation("London", 51.5072, -0.1276, ("london",)),
        WeatherLocation("Munich", 48.1351, 11.5820, ("munich",)),
        WeatherLocation("Toronto", 43.6532, -79.3832, ("toronto",)),
        WeatherLocation("Tokyo", 35.6762, 139.6503, ("tokyo",)),
    )

    STATION_OVERRIDES: Dict[str, StationOverride] = {
        "new york city": StationOverride("KNYC", "New York City Central Park", "metar", "KNYC", "KOKX"),
        "chicago": StationOverride("KMDW", "Chicago Midway", "metar", "KMDW", "KLOT"),
        "miami": StationOverride("KMIA", "Miami International", "metar", "KMIA", "KAMX"),
        "austin": StationOverride("KAUS", "Austin Bergstrom", "metar", "KAUS", "KEWX"),
        "los angeles": StationOverride("KLAX", "Los Angeles International", "metar", "KLAX", "KVTX"),
        "philadelphia": StationOverride("KPHL", "Philadelphia International", "metar", "KPHL", "KDIX"),
        "boston": StationOverride("KBOS", "Boston Logan", "metar", "KBOS", "KBOX"),
        "washington dc": StationOverride("KDCA", "Washington Reagan National", "metar", "KDCA", "KLWX"),
        "denver": StationOverride("KDEN", "Denver International", "metar", "KDEN", "KFTG"),
        "dallas": StationOverride("KDAL", "Dallas Love Field", "metar", "KDAL", "KFWS"),
        "houston": StationOverride("KHOU", "Houston Hobby", "metar", "KHOU", "KHGX"),
        "san francisco": StationOverride("KSFO", "San Francisco International", "metar", "KSFO", "KMUX"),
        "phoenix": StationOverride("KPHX", "Phoenix Sky Harbor", "metar", "KPHX", "KIWA"),
        "atlanta": StationOverride("KATL", "Atlanta Hartsfield Jackson", "metar", "KATL", "KFFC"),
        "london": StationOverride("EGLL", "London Heathrow", "metar", "EGLL"),
        "munich": StationOverride("EDDM", "Munich Airport", "metar", "EDDM"),
        "toronto": StationOverride("CYYZ", "Toronto Pearson", "metar", "CYYZ"),
        "tokyo": StationOverride("RJTT", "Tokyo Haneda", "metar", "RJTT"),
    }

    def __init__(
        self,
        locations: Optional[Iterable[WeatherLocation]] = None,
        overrides: Optional[Dict[str, StationOverride]] = None,
    ):
        self.locations = tuple(locations or self.LOCATIONS)
        self.overrides = dict(overrides or self.STATION_OVERRIDES)

    def detect_location(self, text: str) -> Optional[WeatherLocation]:
        lowered = str(text or "").lower()
        candidates = []
        for location in self.locations:
            for alias in location.aliases:
                if re.search(rf"\b{re.escape(alias)}\b", lowered):
                    candidates.append((len(alias), location))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def resolve(
        self,
        market_id: str,
        location: Optional[WeatherLocation],
        market_text: str = "",
    ) -> WeatherResolutionTarget:
        if location is None:
            return WeatherResolutionTarget(
                market_id=str(market_id or ""),
                location_name="",
                latitude=0.0,
                longitude=0.0,
                resolution_station="",
                blockers=["unknown_location"],
            )

        override = self._override_for(location)
        if override is None:
            return WeatherResolutionTarget(
                market_id=str(market_id or ""),
                location_name=location.name,
                latitude=float(location.latitude),
                longitude=float(location.longitude),
                resolution_station="",
                station_type="unknown",
                blockers=["unknown_station"],
                quality_flags=["location_detected_without_station_override"],
            )

        flags = ["station_manual_override", f"station_type:{override.station_type}"]
        if self._resolution_mentions_airport(market_text):
            flags.append("resolution_text_mentions_airport")
        return WeatherResolutionTarget(
            market_id=str(market_id or ""),
            location_name=location.name,
            latitude=float(location.latitude),
            longitude=float(location.longitude),
            resolution_station=override.resolution_station,
            station_name=override.station_name,
            station_type=override.station_type,
            metar_station=override.metar_station,
            nexrad_station=override.nexrad_station,
            bias_correction_f=float(override.bias_correction_f),
            quality_flags=flags,
        )

    def _override_for(self, location: WeatherLocation) -> Optional[StationOverride]:
        names = [location.name, *location.aliases]
        for name in names:
            key = self._canonical_location(name)
            if key in self.overrides:
                return self.overrides[key]
        return None

    @staticmethod
    def _canonical_location(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    @staticmethod
    def _resolution_mentions_airport(text: str) -> bool:
        lowered = str(text or "").lower()
        return any(token in lowered for token in ("airport", "station", "metar", "observed at"))
