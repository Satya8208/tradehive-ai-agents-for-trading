"""
Weather market type and alpha-lane classification.

This layer is deliberately forecast-free. It routes the full weather universe
by contract shape, geography, source applicability, horizon, and alpha lane so
the research loop can find edge-rich markets before spending API budget.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .models import CLIMarket
from .station_mapper import WeatherLocation, WeatherStationMapper
from .weather_signals import WeatherDataSignals, WeatherMarketParse


WEATHER_MARKET_CLASSIFICATION_SCHEMA_VERSION = "weather_market_classification_v1"

CONTRACT_TEMP_HIGH = "temp_high_threshold"
CONTRACT_TEMP_LOW = "temp_low_threshold"
CONTRACT_PRECIP_BINARY = "precipitation_binary"
CONTRACT_PRECIP_AMOUNT = "precipitation_amount"
CONTRACT_SNOW_AMOUNT = "snow_amount"
CONTRACT_WIND_GUST = "wind_gust"
CONTRACT_WIND = "wind_threshold"
CONTRACT_HURRICANE = "hurricane_tropical"
CONTRACT_SPACE_WEATHER = "space_weather"
CONTRACT_OTHER = "other"

REGION_CONUS = "CONUS"
REGION_US_OTHER = "Alaska_Hawaii_Puerto_Rico_Guam"
REGION_NON_US = "non_US_global"
REGION_UNKNOWN = "unknown"

LANE_OBSERVATION_LAG = "observation_lag_station_threshold"
LANE_HRRR_NBM_RUN_SHOCK = "hrrr_nbm_run_shock"
LANE_STATION_SOURCE_MISMATCH = "station_source_window_mismatch"
LANE_LADDER_CONSISTENCY = "ladder_consistency"
LANE_PROBABILITY_BASELINE = "probability_gap_baseline"
LANE_OPEN_METEO_CONTROL = "open_meteo_control"


@dataclass(frozen=True)
class WeatherMarketClassification:
    market_id: str
    question: str
    contract_type: str
    region: str
    horizon_bucket: str
    alpha_lanes: List[str]
    source_applicability: List[str]
    schema_version: str = WEATHER_MARKET_CLASSIFICATION_SCHEMA_VERSION
    metric: str = ""
    operator: str = ""
    threshold: Optional[float] = None
    upper_threshold: Optional[float] = None
    threshold_unit: str = ""
    target_date: str = ""
    location_name: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    station_mapping_status: str = "unknown"
    station_id: str = ""
    station_type: str = ""
    hours_to_end: float = 999.0
    event_slug: str = ""
    slug: str = ""
    lane_reason_flags: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherMarketTypeClassifier:
    """Classify weather markets into research alpha lanes without API fetches."""

    def __init__(self, station_mapper: Optional[WeatherStationMapper] = None):
        self.station_mapper = station_mapper or WeatherStationMapper()

    def classify(self, market: CLIMarket, *, now: Optional[datetime] = None) -> WeatherMarketClassification:
        now = now or datetime.utcnow()
        text = self._market_text(market)
        parsed = self._parse_market_text(market, text)
        resolution = self.station_mapper.resolve(
            market_id=str(getattr(market, "condition_id", "") or ""),
            location=parsed.location,
            market_text=text,
        )
        contract_type = self._contract_type(parsed.metric, parsed.operator, parsed.threshold, text)
        region = self._region(parsed.location, resolution.resolution_station)
        horizon_bucket = self._horizon_bucket(market, parsed.target_date, now)
        source_applicability = self._source_applicability(region, resolution.resolution_station, contract_type)
        alpha_lanes, lane_flags = self._alpha_lanes(
            contract_type=contract_type,
            region=region,
            horizon_bucket=horizon_bucket,
            resolution_status=resolution.status,
            station_id=resolution.resolution_station,
            source_applicability=source_applicability,
            market=market,
        )

        blockers: List[str] = []
        if not parsed.location:
            blockers.append("unparsed_location")
        if not parsed.metric:
            blockers.append("unparsed_metric")
        if not parsed.operator:
            blockers.append("unparsed_operator")
        if parsed.threshold is None and contract_type not in {CONTRACT_HURRICANE, CONTRACT_SPACE_WEATHER}:
            blockers.append("unparsed_threshold")
        if resolution.blockers:
            blockers.extend(resolution.blockers)

        quality_flags = list(resolution.quality_flags)
        if "OpenMeteo_only" in source_applicability:
            quality_flags.append("baseline_source_only")
        if region == REGION_CONUS and resolution.resolution_station:
            quality_flags.append("conus_station_mapped")
        if LANE_OBSERVATION_LAG in alpha_lanes:
            quality_flags.append("observation_lag_candidate")

        return WeatherMarketClassification(
            market_id=str(getattr(market, "condition_id", "") or ""),
            question=str(getattr(market, "question", "") or ""),
            contract_type=contract_type,
            region=region,
            horizon_bucket=horizon_bucket,
            alpha_lanes=alpha_lanes,
            source_applicability=source_applicability,
            metric=parsed.metric,
            operator=parsed.operator,
            threshold=parsed.threshold,
            upper_threshold=parsed.upper_threshold,
            threshold_unit=parsed.threshold_unit,
            target_date=parsed.target_date.isoformat() if parsed.target_date else "",
            location_name=parsed.location.name if parsed.location else "",
            latitude=float(parsed.location.latitude) if parsed.location else None,
            longitude=float(parsed.location.longitude) if parsed.location else None,
            station_mapping_status=resolution.status,
            station_id=resolution.resolution_station,
            station_type=resolution.station_type,
            hours_to_end=round(float(getattr(market, "time_remaining_hours", 999.0) or 999.0), 4),
            event_slug=str(getattr(market, "event_slug", "") or ""),
            slug=str(getattr(market, "slug", "") or ""),
            lane_reason_flags=sorted(set(lane_flags)),
            blockers=sorted(set(blockers)),
            quality_flags=sorted(set(quality_flags)),
        )

    def _parse_market_text(self, market: CLIMarket, text: str) -> WeatherMarketParse:
        location = self.station_mapper.detect_location(text)
        metric = WeatherDataSignals._detect_metric(text)
        operator = WeatherDataSignals._detect_operator(text)
        threshold, unit, upper_threshold = WeatherDataSignals._extract_threshold(text, metric)
        target_date = WeatherDataSignals._detect_target_date(text, getattr(market, "end_date", None))
        return WeatherMarketParse(
            location=location,
            metric=metric,
            operator=operator,
            threshold=threshold,
            upper_threshold=upper_threshold,
            threshold_unit=unit,
            target_date=target_date,
        )

    @staticmethod
    def _market_text(market: CLIMarket) -> str:
        return " ".join(
            str(part or "")
            for part in (
                getattr(market, "question", ""),
                getattr(market, "description", ""),
                getattr(market, "slug", ""),
                getattr(market, "event_slug", ""),
            )
            if part
        ).lower()

    @staticmethod
    def _contract_type(metric: str, operator: str, threshold: Optional[float], text: str) -> str:
        lowered = text.lower()
        if metric == "space_weather":
            return CONTRACT_SPACE_WEATHER
        if any(token in lowered for token in ("hurricane", "tropical storm", "typhoon")):
            return CONTRACT_HURRICANE
        if metric == "temperature_high":
            return CONTRACT_TEMP_HIGH
        if metric == "temperature_low":
            return CONTRACT_TEMP_LOW
        if metric == "precipitation":
            if threshold is None or abs(float(threshold) - 0.01) < 1e-9:
                return CONTRACT_PRECIP_BINARY
            return CONTRACT_PRECIP_AMOUNT
        if metric == "snowfall":
            return CONTRACT_SNOW_AMOUNT
        if metric == "wind_gust":
            return CONTRACT_WIND_GUST
        if metric == "wind":
            return CONTRACT_WIND
        return CONTRACT_OTHER

    @staticmethod
    def _region(location: Optional[WeatherLocation], station_id: str) -> str:
        station = str(station_id or "").upper()
        if location is None:
            return REGION_UNKNOWN
        lat = float(location.latitude)
        lon = float(location.longitude)
        if station.startswith("K") and 24.0 <= lat <= 50.0 and -125.0 <= lon <= -66.0:
            return REGION_CONUS
        if station.startswith(("PA", "PH", "TJ", "PG")):
            return REGION_US_OTHER
        if 18.0 <= lat <= 23.0 and -161.0 <= lon <= -154.0:
            return REGION_US_OTHER
        if 51.0 <= lat <= 72.0 and -170.0 <= lon <= -130.0:
            return REGION_US_OTHER
        return REGION_NON_US

    @staticmethod
    def _horizon_bucket(market: CLIMarket, target_date: Optional[date], now: datetime) -> str:
        hours = float(getattr(market, "time_remaining_hours", 999.0) or 999.0)
        if target_date is not None and target_date <= now.date() and hours > 0:
            return "already_in_window"
        if hours <= 6:
            return "0_6h"
        if hours <= 24:
            return "6_24h"
        if hours <= 72:
            return "24_72h"
        return "gt_72h"

    @staticmethod
    def _source_applicability(region: str, station_id: str, contract_type: str) -> List[str]:
        station = str(station_id or "").upper()
        sources: List[str] = []
        if region == REGION_CONUS and station:
            if contract_type in {
                CONTRACT_TEMP_HIGH,
                CONTRACT_TEMP_LOW,
                CONTRACT_PRECIP_BINARY,
                CONTRACT_PRECIP_AMOUNT,
                CONTRACT_SNOW_AMOUNT,
                CONTRACT_WIND,
                CONTRACT_WIND_GUST,
            }:
                sources.extend(["HRRR_applicable", "NBM_applicable", "NWS_applicable"])
            if station.startswith("K"):
                sources.append("METAR_ASOS_applicable")
        if not sources:
            sources.append("OpenMeteo_only")
        else:
            sources.append("OpenMeteo_baseline")
        return sorted(set(sources))

    @staticmethod
    def _alpha_lanes(
        *,
        contract_type: str,
        region: str,
        horizon_bucket: str,
        resolution_status: str,
        station_id: str,
        source_applicability: List[str],
        market: CLIMarket,
    ) -> tuple[List[str], List[str]]:
        lanes: List[str] = []
        flags: List[str] = []
        threshold_contracts = {
            CONTRACT_TEMP_HIGH,
            CONTRACT_TEMP_LOW,
            CONTRACT_PRECIP_BINARY,
            CONTRACT_PRECIP_AMOUNT,
            CONTRACT_SNOW_AMOUNT,
            CONTRACT_WIND,
            CONTRACT_WIND_GUST,
        }
        station_mapped = bool(station_id) and resolution_status == "ok"
        near_resolution = horizon_bucket in {"already_in_window", "0_6h", "6_24h"}
        hrrr_horizon = horizon_bucket in {"already_in_window", "0_6h", "6_24h", "24_72h"}

        if region == REGION_CONUS and station_mapped and contract_type in threshold_contracts and near_resolution:
            lanes.append(LANE_OBSERVATION_LAG)
            flags.append("conus_near_resolution_station_threshold")

        if (
            region == REGION_CONUS
            and station_mapped
            and contract_type in threshold_contracts
            and hrrr_horizon
            and {"HRRR_applicable", "NBM_applicable"}.intersection(source_applicability)
        ):
            lanes.append(LANE_HRRR_NBM_RUN_SHOCK)
            flags.append("conus_high_resolution_source_applicable")

        if station_mapped and contract_type in threshold_contracts:
            lanes.append(LANE_STATION_SOURCE_MISMATCH)
            flags.append("station_or_source_specific_contract")

        if contract_type in threshold_contracts and (getattr(market, "event_slug", "") or getattr(market, "slug", "")):
            lanes.append(LANE_LADDER_CONSISTENCY)
            flags.append("threshold_market_with_event_grouping")

        if contract_type in threshold_contracts:
            lanes.append(LANE_PROBABILITY_BASELINE)

        if "OpenMeteo_only" in source_applicability:
            lanes.append(LANE_OPEN_METEO_CONTROL)

        return sorted(set(lanes)), sorted(set(flags))


def finite_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default
