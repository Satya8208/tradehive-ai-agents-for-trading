"""
Historical weather edge lab for Polymarket.

This module is the builder-team counterpart to the weather research report. It
keeps the first milestone research and paper-only: resolved markets are joined
to historical CLOB prices and as-of weather features, model variants are scored
on chronological holdout, and paper recommendations are written only when the
strict promotion gates pass.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests
from termcolor import cprint

from .config import ExecutionMode, PolymarketCLIConfig
from .station_mapper import WeatherStationMapper
from .weather_contracts import FEATURE_SCHEMA_VERSION
from .weather_edge_features import WeatherHighResolutionSourceBuilder, WeatherStationBiasResolver
from .weather_alpha import WeatherAlphaBacktester, WeatherAlphaRecord
from .weather_signals import WeatherDataSignals, WeatherLocation, WeatherMarketParse


LAB_SUBDIRS = ("datasets", "features", "backtests", "models", "paper_exports")
MODEL_VARIANTS = (
    "heuristic_baseline",
    "market_forecast_blend",
    "logistic_calibration",
    "isotonic_calibration",
    "source_ensemble",
    "shrink_to_market",
)

LOCATION_STATIONS = {
    "new york city": {"metar": "KNYC", "nexrad": "KOKX"},
    "new york": {"metar": "KNYC", "nexrad": "KOKX"},
    "nyc": {"metar": "KNYC", "nexrad": "KOKX"},
    "chicago": {"metar": "KMDW", "nexrad": "KLOT"},
    "miami": {"metar": "KMIA", "nexrad": "KAMX"},
    "austin": {"metar": "KAUS", "nexrad": "KEWX"},
    "los angeles": {"metar": "KLAX", "nexrad": "KVTX"},
    "philadelphia": {"metar": "KPHL", "nexrad": "KDIX"},
    "boston": {"metar": "KBOS", "nexrad": "KBOX"},
    "washington dc": {"metar": "KDCA", "nexrad": "KLWX"},
    "denver": {"metar": "KDEN", "nexrad": "KFTG"},
    "dallas": {"metar": "KDAL", "nexrad": "KFWS"},
    "houston": {"metar": "KHOU", "nexrad": "KHGX"},
    "san francisco": {"metar": "KSFO", "nexrad": "KMUX"},
    "phoenix": {"metar": "KPHX", "nexrad": "KIWA"},
    "atlanta": {"metar": "KATL", "nexrad": "KFFC"},
    "london": {"metar": "EGLL", "nexrad": ""},
    "munich": {"metar": "EDDM", "nexrad": ""},
    "toronto": {"metar": "CYYZ", "nexrad": ""},
}

PROMOTION_HARD_BLOCKER_PREFIXES = (
    "clob_price_history_missing",
    "stale_clob_price_history",
    "open_meteo_previous_runs_missing",
    "research_only_source:",
    "selected_source_unavailable:",
    "unknown_station",
    "unknown_location",
)


@dataclass(frozen=True)
class WeatherSourceDefinition:
    source_id: str
    family: str
    name: str
    status_when_available: str
    implementation_status: str
    default_blocker: str = ""


@dataclass
class WeatherSourceFeature:
    source_id: str
    family: str
    status: str
    generated_at: str
    asof_time: str
    probability: Optional[float] = None
    features: Dict[str, Any] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["status_label"] = self.status.replace("_", "-")
        return payload


@dataclass
class WeatherEdgeLabRecord:
    market_id: str
    question: str
    slug: str
    asof_time: str
    target_date: str
    location: str
    metric: str
    threshold: Optional[float]
    operator: str
    market_yes_price: float
    book_depth: float
    fees: Dict[str, Any]
    source_probabilities: Dict[str, float]
    source_features: Dict[str, Dict[str, Any]]
    source_statuses: Dict[str, str]
    model_probability: float
    edge: float
    selected_side: str
    resolution_label: str
    yes_resolved: bool
    pnl: float
    blockers: List[str]
    lead_days: int = 0
    upper_threshold: Optional[float] = None
    market_no_price: float = 0.0
    price_source: str = ""
    forecast_source: str = ""
    clob_price_age_hours: float = 0.0
    generated_at: str = field(default_factory=lambda: utc_now_iso())
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    station_mapping: Dict[str, Any] = field(default_factory=dict)
    quality_flags: List[str] = field(default_factory=list)
    station_bias: Dict[str, Any] = field(default_factory=dict)
    high_resolution_sources: List[Dict[str, Any]] = field(default_factory=list)
    latency_signals: Dict[str, Any] = field(default_factory=dict)

    @property
    def yes_price(self) -> float:
        return self.market_yes_price

    @property
    def model_probability_bounded(self) -> float:
        return bounded_probability(self.model_probability)

    def key(self) -> str:
        return "|".join(
            [
                self.market_id,
                self.asof_time,
                str(self.lead_days),
                self.forecast_source,
            ]
        )

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["yes_price"] = self.market_yes_price
        payload["recommended_side"] = self.selected_side
        payload["pnl_per_usd"] = self.pnl
        return payload


@dataclass(frozen=True)
class WeatherExecutionCostAssumptions:
    fee_rate: float = 0.01
    spread_haircut: float = 0.01
    slippage_haircut: float = 0.01
    min_book_depth_usd: float = 1.0

    @property
    def total_edge_haircut(self) -> float:
        return max(0.0, self.fee_rate) + max(0.0, self.spread_haircut) + max(0.0, self.slippage_haircut)


@dataclass(frozen=True)
class WeatherPromotionGates:
    min_resolved_records: int = 300
    min_target_dates: int = 8
    min_holdout_candidate_edges: int = 75
    min_market_baseline_improvement: float = 0.02
    min_holdout_roi_after_cost: float = 0.0
    max_single_slice_pnl_share: float = 0.35
    max_selected_clob_price_age_hours: float = 3.0


class WeatherSourceAdapter:
    """Base adapter. Concrete adapters fail closed when data is unavailable."""

    definition: WeatherSourceDefinition

    def __init__(
        self,
        definition: WeatherSourceDefinition,
        session: Optional[requests.Session] = None,
        config: Optional[PolymarketCLIConfig] = None,
    ):
        self.definition = definition
        self.session = session or requests.Session()
        self.config = config

    @property
    def source_id(self) -> str:
        return self.definition.source_id

    def build(self, row: Any) -> WeatherSourceFeature:
        blocker = self.definition.default_blocker or f"unavailable_requires_parser:{self.source_id}"
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="unavailable",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            features={
                "implementation_status": self.definition.implementation_status,
                "source_manifest": self._source_manifest(row),
            },
            blockers=[blocker],
        )

    def _source_manifest(self, row: Any) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "location": str(_get(row, "location", "")),
            "target_date": str(_get(row, "target_date", "")),
            "metric": str(_get(row, "metric", "")),
        }


class PolymarketMetadataAdapter(WeatherSourceAdapter):
    def build(self, row: Any) -> WeatherSourceFeature:
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="live_safe",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            features={
                "market_id": _get(row, "market_id", ""),
                "question": _get(row, "question", ""),
                "slug": _get(row, "slug", ""),
                "target_date": _get(row, "target_date", ""),
                "metric": _get(row, "metric", ""),
                "operator": _get(row, "operator", ""),
                "threshold": _get(row, "threshold", None),
                "upper_threshold": _get(row, "upper_threshold", None),
            },
        )


class PolymarketPriceHistoryAdapter(WeatherSourceAdapter):
    def build(self, row: Any) -> WeatherSourceFeature:
        price = _float_or_none(_get(row, "yes_price", _get(row, "market_yes_price", None)))
        price_source = str(_get(row, "price_source", ""))
        age_hours = _float_or_none(_get(row, "clob_price_age_hours", 0.0))
        blockers: List[str] = []
        status = "live_safe"
        if price is None:
            status = "unavailable"
            blockers.append("clob_price_history_missing")
        elif age_hours is not None and age_hours > 3.0:
            status = "stale"
            blockers.append("stale_clob_price_history")
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status=status,
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            probability=bounded_probability(price) if price is not None else None,
            features={
                "market_yes_price": price,
                "price_source": price_source,
                "clob_price_age_hours": age_hours if age_hours is not None else None,
            },
            blockers=blockers,
        )


class PolymarketFeesAdapter(WeatherSourceAdapter):
    def build(self, row: Any) -> WeatherSourceFeature:
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="live_safe",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            features={
                "fee_rate": 0.01,
                "fee_model": "research_haircut_default",
                "note": "Historical lab uses a conservative fee haircut; no private credentials are read.",
            },
        )


class PolymarketOrderbookAdapter(WeatherSourceAdapter):
    def build(self, row: Any) -> WeatherSourceFeature:
        book_depth = _float_or_none(_get(row, "book_depth", None))
        if book_depth is None:
            live_depth = self._fetch_live_depth(row)
            if live_depth is not None:
                book_depth = live_depth
        if book_depth is None:
            return WeatherSourceFeature(
                source_id=self.source_id,
                family=self.definition.family,
                status="unavailable",
                generated_at=utc_now_iso(),
                asof_time=str(_get(row, "asof_time", "")),
                features={"book_depth": None},
                blockers=["historical_orderbook_depth_unavailable"],
            )
        status = "live_safe" if book_depth > 0 else "unavailable"
        blockers = [] if book_depth > 0 else ["orderbook_depth_zero"]
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status=status,
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            features={"book_depth": book_depth},
            blockers=blockers,
        )

    def _fetch_live_depth(self, row: Any) -> Optional[float]:
        token_id = str(_get(row, "yes_token_id", "") or _get(row, "token_id", "") or "").strip()
        if not token_id:
            return None
        try:
            response = self.session.get(
                "https://clob.polymarket.com/book",
                params={"token_id": token_id},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return None
        asks = payload.get("asks", []) if isinstance(payload, dict) else []
        depth = 0.0
        for level in asks if isinstance(asks, list) else []:
            price = _float_or_none(level.get("price") if isinstance(level, dict) else None)
            size = _float_or_none(level.get("size") if isinstance(level, dict) else None)
            if price is None or size is None:
                continue
            depth += max(0.0, price * size)
        return round(depth, 4) if depth > 0 else None


class OpenMeteoPreviousRunsAdapter(WeatherSourceAdapter):
    def build(self, row: Any) -> WeatherSourceFeature:
        forecast_source = str(_get(row, "forecast_source", ""))
        probability = _float_or_none(_get(row, "model_probability", None))
        if forecast_source.startswith("open_meteo_previous_day") and probability is not None:
            return WeatherSourceFeature(
                source_id=self.source_id,
                family=self.definition.family,
                status="live_safe",
                generated_at=utc_now_iso(),
                asof_time=str(_get(row, "asof_time", "")),
                probability=bounded_probability(probability),
                features=dict(_get(row, "forecast_metrics", {}) or {}),
            )
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="unavailable",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            features={},
            blockers=["open_meteo_previous_runs_missing"],
        )


class OpenMeteoHistoricalForecastAdapter(WeatherSourceAdapter):
    def build(self, row: Any) -> WeatherSourceFeature:
        forecast_source = str(_get(row, "forecast_source", ""))
        probability = _float_or_none(_get(row, "model_probability", None))
        if forecast_source == "open_meteo_historical_forecast" and probability is not None:
            return WeatherSourceFeature(
                source_id=self.source_id,
                family=self.definition.family,
                status="research_only",
                generated_at=utc_now_iso(),
                asof_time=str(_get(row, "asof_time", "")),
                probability=bounded_probability(probability),
                features=dict(_get(row, "forecast_metrics", {}) or {}),
                blockers=["research_only_source:open_meteo_historical_forecast"],
            )
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="unavailable",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            features={},
            blockers=["open_meteo_historical_forecast_missing"],
        )


class OpenMeteoForecastAdapter(WeatherSourceAdapter):
    def build(self, row: Any) -> WeatherSourceFeature:
        location = _location_from_row(row)
        if location is None:
            return WeatherSourceFeature(
                source_id=self.source_id,
                family=self.definition.family,
                status="unavailable",
                generated_at=utc_now_iso(),
                asof_time=str(_get(row, "asof_time", "")),
                features={"mode": "live_forecast"},
                blockers=["location_coordinates_unavailable:open_meteo_forecast"],
            )
        if not _target_is_future_or_today(row):
            return WeatherSourceFeature(
                source_id=self.source_id,
                family=self.definition.family,
                status="live_safe",
                generated_at=utc_now_iso(),
                asof_time=str(_get(row, "asof_time", "")),
                features={
                    "mode": "live_forecast",
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                    "reason": "live forecast is not valid historical as-of evidence",
                },
                blockers=["live_forecast_not_historical_asof"],
            )
        try:
            payload = self._fetch_payload(location)
            metrics = WeatherDataSignals(self.config, session=self.session)._summarize_forecast(
                payload,
                None,
                _parse_date(_get(row, "target_date", "")),
            )
            probability = _estimate_row_probability(row, metrics, hours_remaining=24.0)
        except Exception as exc:
            return WeatherSourceFeature(
                source_id=self.source_id,
                family=self.definition.family,
                status="unavailable",
                generated_at=utc_now_iso(),
                asof_time=str(_get(row, "asof_time", "")),
                features={"mode": "live_forecast"},
                blockers=[f"open_meteo_forecast_error:{type(exc).__name__}"],
            )
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="live_safe",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            probability=probability,
            features={
                "mode": "live_forecast",
                "latitude": location.latitude,
                "longitude": location.longitude,
                "forecast_metrics": metrics,
            },
        )

    def _fetch_payload(self, location: WeatherLocation) -> Dict[str, Any]:
        response = self.session.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": location.latitude,
                "longitude": location.longitude,
                "hourly": "temperature_2m,precipitation,rain,snowfall,wind_speed_10m,wind_gusts_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "forecast_days": 16,
                "timezone": "auto",
            },
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("unexpected Open-Meteo forecast payload")
        return payload


class NWSForecastAdapter(WeatherSourceAdapter):
    """NWS JSON forecast adapter for current/future US markets."""

    def build(self, row: Any) -> WeatherSourceFeature:
        location = _location_from_row(row)
        if location is None:
            return self._unavailable(row, "location_coordinates_unavailable:nws_api")
        if not _is_us_location(location):
            return self._not_applicable(row, {"reason": "NWS public forecast API has US coverage only"})
        if not _target_is_future_or_today(row):
            return WeatherSourceFeature(
                source_id=self.source_id,
                family=self.definition.family,
                status="live_safe",
                generated_at=utc_now_iso(),
                asof_time=str(_get(row, "asof_time", "")),
                features=self._manifest(location, row),
                blockers=["live_source_not_historical_asof:nws_api"],
            )
        try:
            points = self._fetch_points(location)
            hourly_url = points.get("properties", {}).get("forecastHourly")
            if not hourly_url:
                return self._unavailable(row, "nws_forecast_hourly_url_missing")
            payload = self._fetch_url(hourly_url)
            metrics = _summarize_nws_periods(payload, _parse_date(_get(row, "target_date", "")))
            probability = _estimate_row_probability(row, metrics, hours_remaining=24.0)
        except Exception as exc:
            return self._unavailable(row, f"nws_api_error:{type(exc).__name__}")
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="live_safe",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            probability=probability,
            features={**self._manifest(location, row), "forecast_metrics": metrics},
        )

    def _fetch_points(self, location: WeatherLocation) -> Dict[str, Any]:
        return self._fetch_url(f"https://api.weather.gov/points/{location.latitude:.4f},{location.longitude:.4f}")

    def _fetch_url(self, url: str) -> Dict[str, Any]:
        response = self.session.get(
            url,
            headers={"User-Agent": "tradehive-ai-agents-weather-edge-lab/1.0"},
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("unexpected NWS payload")
        return payload

    def _manifest(self, location: WeatherLocation, row: Any) -> Dict[str, Any]:
        return {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "target_date": str(_get(row, "target_date", "")),
            "points_url": f"https://api.weather.gov/points/{location.latitude:.4f},{location.longitude:.4f}",
        }

    def _unavailable(self, row: Any, blocker: str) -> WeatherSourceFeature:
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="unavailable",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            features={"source_manifest": self._source_manifest(row)},
            blockers=[blocker],
        )

    def _not_applicable(self, row: Any, features: Dict[str, Any]) -> WeatherSourceFeature:
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="not_applicable",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            features=features,
        )


class NWSGridpointsAdapter(NWSForecastAdapter):
    """NWS gridpoint time-series adapter for current/future US markets."""

    def build(self, row: Any) -> WeatherSourceFeature:
        location = _location_from_row(row)
        if location is None:
            return self._unavailable(row, "location_coordinates_unavailable:nws_gridpoints")
        if not _is_us_location(location):
            return self._not_applicable(row, {"reason": "NWS gridpoints have US coverage only"})
        if not _target_is_future_or_today(row):
            return WeatherSourceFeature(
                source_id=self.source_id,
                family=self.definition.family,
                status="live_safe",
                generated_at=utc_now_iso(),
                asof_time=str(_get(row, "asof_time", "")),
                features=self._manifest(location, row),
                blockers=["live_source_not_historical_asof:nws_gridpoints"],
            )
        try:
            points = self._fetch_points(location)
            props = points.get("properties", {})
            office = str(props.get("gridId") or "")
            grid_x = props.get("gridX")
            grid_y = props.get("gridY")
            if not office or grid_x is None or grid_y is None:
                return self._unavailable(row, "nws_gridpoint_lookup_missing")
            grid_url = f"https://api.weather.gov/gridpoints/{office}/{grid_x},{grid_y}"
            payload = self._fetch_url(grid_url)
            metrics = _summarize_nws_gridpoint(payload, _parse_date(_get(row, "target_date", "")))
            probability = _estimate_row_probability(row, metrics, hours_remaining=24.0)
        except Exception as exc:
            return self._unavailable(row, f"nws_gridpoints_error:{type(exc).__name__}")
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="live_safe",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            probability=probability,
            features={
                **self._manifest(location, row),
                "grid_url": grid_url,
                "forecast_metrics": metrics,
            },
        )


class AWCMetarAdapter(WeatherSourceAdapter):
    def build(self, row: Any) -> WeatherSourceFeature:
        station = _station_for_row(row, "metar")
        if not station:
            return WeatherSourceFeature(
                source_id=self.source_id,
                family=self.definition.family,
                status="unavailable",
                generated_at=utc_now_iso(),
                asof_time=str(_get(row, "asof_time", "")),
                features={"station": ""},
                blockers=["metar_station_mapping_missing"],
            )
        try:
            response = self.session.get(
                "https://aviationweather.gov/api/data/metar",
                params={"ids": station, "format": "json", "taf": "false", "hours": 3},
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
            latest = payload[0] if isinstance(payload, list) and payload else {}
            if not isinstance(latest, dict):
                latest = {}
            metrics = _summarize_metar(latest)
            probability = _estimate_row_probability(row, metrics, hours_remaining=1.0)
            blockers = [] if _target_is_today(row) else ["observation_not_target_window:noaa_awc_metar"]
        except Exception as exc:
            return WeatherSourceFeature(
                source_id=self.source_id,
                family=self.definition.family,
                status="unavailable",
                generated_at=utc_now_iso(),
                asof_time=str(_get(row, "asof_time", "")),
                features={"station": station},
                blockers=[f"awc_metar_error:{type(exc).__name__}"],
            )
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="live_safe",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            probability=probability if not blockers else None,
            features={"station": station, "observation": latest, "forecast_metrics": metrics},
            blockers=blockers,
        )


class NHCAdapter(WeatherSourceAdapter):
    def build(self, row: Any) -> WeatherSourceFeature:
        text = _row_text(row)
        if not any(token in text for token in ("hurricane", "tropical storm", "nhc", "cyclone")):
            return WeatherSourceFeature(
                source_id=self.source_id,
                family=self.definition.family,
                status="not_applicable",
                generated_at=utc_now_iso(),
                asof_time=str(_get(row, "asof_time", "")),
                features={"reason": "not a tropical cyclone market"},
            )
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="live_safe",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            features={
                "products": [
                    "https://www.nhc.noaa.gov/CurrentStorms.json",
                    "https://www.nhc.noaa.gov/gis/",
                    "https://www.nhc.noaa.gov/data/",
                ],
                "target_date": str(_get(row, "target_date", "")),
                "note": "NHC adapter records official product sources; storm-specific advisory parsing is externalized.",
            },
            blockers=["live_source_not_historical_asof:noaa_nhc"] if not _target_is_future_or_today(row) else [],
        )


class SWPCAdapter(WeatherSourceAdapter):
    def build(self, row: Any) -> WeatherSourceFeature:
        text = _row_text(row)
        if "space weather" not in text and str(_get(row, "metric", "")) != "space_weather":
            return WeatherSourceFeature(
                source_id=self.source_id,
                family=self.definition.family,
                status="not_applicable",
                generated_at=utc_now_iso(),
                asof_time=str(_get(row, "asof_time", "")),
                features={"reason": "not a space-weather market"},
            )
        try:
            response = self.session.get(
                "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
            latest = payload[-1] if isinstance(payload, list) and len(payload) > 1 else []
            kp = _float_or_none(latest[1] if isinstance(latest, list) and len(latest) > 1 else None)
        except Exception as exc:
            return WeatherSourceFeature(
                source_id=self.source_id,
                family=self.definition.family,
                status="unavailable",
                generated_at=utc_now_iso(),
                asof_time=str(_get(row, "asof_time", "")),
                features={"product": "noaa-planetary-k-index"},
                blockers=[f"swpc_error:{type(exc).__name__}"],
            )
        metrics = {"kp_index": kp}
        probability = _estimate_row_probability(row, {"max_wind_mph": kp}, hours_remaining=1.0) if kp is not None else None
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="live_safe",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            probability=probability if _target_is_today(row) else None,
            features={"product": "noaa-planetary-k-index", "latest": latest, "metrics": metrics},
            blockers=[] if _target_is_today(row) else ["live_source_not_historical_asof:noaa_swpc"],
        )


class NCEICDOAdapter(WeatherSourceAdapter):
    def build(self, row: Any) -> WeatherSourceFeature:
        station = _station_for_row(row, "metar")
        token_available = bool(os.getenv("NCEI_CDO_TOKEN"))
        blockers = ["ncei_cdo_token_missing"] if not token_available else []
        if not station:
            blockers.append("station_mapping_missing:noaa_ncei_cdo")
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="research_only" if blockers else "live_safe",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            features={
                "station_hint": station,
                "endpoint": "https://www.ncei.noaa.gov/cdo-web/api/v2/data",
                "datasetid": "GHCND",
                "target_date": str(_get(row, "target_date", "")),
                "token_available": token_available,
            },
            blockers=blockers,
        )


class MADISMetarAdapter(WeatherSourceAdapter):
    def build(self, row: Any) -> WeatherSourceFeature:
        station = _station_for_row(row, "metar")
        blockers = [] if station else ["station_mapping_missing:noaa_madis_metar"]
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="live_safe" if station else "unavailable",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            features={
                "station_hint": station,
                "product_family": "MADIS METAR/ASOS",
                "note": "MADIS access is operational; adapter emits station mapping for the ingestion worker.",
            },
            blockers=blockers,
        )


class HeavyProductManifestAdapter(WeatherSourceAdapter):
    """Build deterministic request manifests for GRIB/radar parsers."""

    def build(self, row: Any) -> WeatherSourceFeature:
        manifest = self._source_manifest(row)
        manifest.update(_heavy_product_manifest(self.source_id, row))
        blocker_type = manifest.get("parser_blocker", f"unavailable_requires_parser:{self.source_id}")
        return WeatherSourceFeature(
            source_id=self.source_id,
            family=self.definition.family,
            status="unavailable",
            generated_at=utc_now_iso(),
            asof_time=str(_get(row, "asof_time", "")),
            features=manifest,
            blockers=[blocker_type],
        )


class WeatherSourceRegistry:
    """Registry for weather-source families selected by the builder plan."""

    DEFINITIONS: Tuple[WeatherSourceDefinition, ...] = (
        WeatherSourceDefinition("polymarket_gamma", "polymarket", "Polymarket Gamma API", "live_safe", "integrated"),
        WeatherSourceDefinition(
            "polymarket_clob_price_history",
            "polymarket",
            "Polymarket CLOB price history",
            "live_safe",
            "integrated",
        ),
        WeatherSourceDefinition(
            "polymarket_price_history",
            "polymarket",
            "Polymarket CLOB price history",
            "live_safe",
            "alias",
        ),
        WeatherSourceDefinition(
            "polymarket_clob_orderbook",
            "polymarket",
            "Polymarket CLOB orderbook",
            "live_safe",
            "unavailable_historical_depth",
            "historical_orderbook_depth_unavailable",
        ),
        WeatherSourceDefinition("polymarket_fees", "polymarket", "Polymarket fees", "live_safe", "default_haircut"),
        WeatherSourceDefinition(
            "open_meteo_forecast",
            "open_meteo",
            "Open-Meteo Forecast API",
            "live_safe",
            "live_only",
            "live_forecast_not_historical_asof",
        ),
        WeatherSourceDefinition(
            "open_meteo_previous_runs",
            "open_meteo",
            "Open-Meteo Previous Runs API",
            "live_safe",
            "integrated",
        ),
        WeatherSourceDefinition(
            "open_meteo_historical_forecast",
            "open_meteo",
            "Open-Meteo Historical Forecast API",
            "research_only",
            "integrated_research_only",
            "research_only_source:open_meteo_historical_forecast",
        ),
        WeatherSourceDefinition("nws_api", "nws", "National Weather Service API", "live_safe", "backlog"),
        WeatherSourceDefinition("nws_gridpoints", "nws", "NWS gridpoints", "live_safe", "backlog"),
        WeatherSourceDefinition("ncep_nomads", "noaa_ncep", "NCEP NOMADS", "live_safe", "requires_grib_parser"),
        WeatherSourceDefinition("noaa_nbm", "noaa_ncep", "NOAA NBM", "live_safe", "requires_grib_parser"),
        WeatherSourceDefinition("noaa_hrrr", "noaa_ncep", "NOAA HRRR", "live_safe", "requires_grib_parser"),
        WeatherSourceDefinition("noaa_rtma_urma", "noaa_ncep", "NOAA RTMA/URMA", "live_safe", "requires_grib_parser"),
        WeatherSourceDefinition("noaa_awc_metar", "noaa_awc", "NOAA AWC METAR", "live_safe", "backlog"),
        WeatherSourceDefinition("noaa_nexrad", "noaa_radar", "NOAA NEXRAD", "live_safe", "requires_radar_parser"),
        WeatherSourceDefinition("noaa_stage_iv_qpe", "noaa_qpe", "NOAA Stage IV QPE", "research_only", "requires_parser"),
        WeatherSourceDefinition("noaa_nhc", "noaa_nhc", "NOAA NHC", "live_safe", "backlog"),
        WeatherSourceDefinition("noaa_swpc", "noaa_swpc", "NOAA SWPC", "live_safe", "backlog"),
        WeatherSourceDefinition("noaa_ncei_cdo", "noaa_ncei", "NOAA NCEI CDO", "research_only", "backlog"),
        WeatherSourceDefinition("noaa_madis_metar", "noaa_madis", "NOAA MADIS METAR", "live_safe", "backlog"),
        WeatherSourceDefinition("ecmwf_open_data", "ecmwf", "ECMWF Open Data", "live_safe", "requires_grib_parser"),
        WeatherSourceDefinition("dwd_icon_open_data", "dwd", "DWD ICON Open Data", "live_safe", "requires_grib_parser"),
    )
    ALIASES = {
        "all": "all",
        "previous_runs": "open_meteo_previous_runs",
        "open-meteo-previous-runs": "open_meteo_previous_runs",
        "historical_forecast": "open_meteo_historical_forecast",
        "historical": "open_meteo_historical_forecast",
        "price_history": "polymarket_clob_price_history",
        "clob_price_history": "polymarket_clob_price_history",
        "orderbook": "polymarket_clob_orderbook",
        "fees": "polymarket_fees",
        "gamma": "polymarket_gamma",
        "ncei_madis": "noaa_madis_metar",
        "madis": "noaa_madis_metar",
        "stage_iv": "noaa_stage_iv_qpe",
        "stage4": "noaa_stage_iv_qpe",
        "icon": "dwd_icon_open_data",
    }

    def __init__(self):
        self._definitions = {definition.source_id: definition for definition in self.DEFINITIONS}

    def list_source_ids(self) -> List[str]:
        return list(self._definitions.keys())

    def resolve_source_ids(self, sources: str | Sequence[str]) -> List[str]:
        if isinstance(sources, str):
            raw_values = [part.strip() for part in sources.split(",") if part.strip()]
        else:
            raw_values = [str(part).strip() for part in sources if str(part).strip()]
        if not raw_values:
            raw_values = ["open_meteo_previous_runs"]
        normalized: List[str] = []
        for raw in raw_values:
            cleaned = raw.strip().lower().replace("-", "_")
            source_id = self.ALIASES.get(cleaned, cleaned)
            if source_id == "all":
                for item in self.list_source_ids():
                    if item not in normalized:
                        normalized.append(item)
                continue
            if source_id not in self._definitions:
                raise ValueError(f"unknown weather source: {raw}")
            if source_id not in normalized:
                normalized.append(source_id)
        return normalized

    def build_adapters(
        self,
        sources: str | Sequence[str],
        session: Optional[requests.Session] = None,
        config: Optional[PolymarketCLIConfig] = None,
    ) -> List[WeatherSourceAdapter]:
        adapters = []
        for source_id in self.resolve_source_ids(sources):
            definition = self._definitions[source_id]
            if source_id == "polymarket_gamma":
                adapters.append(PolymarketMetadataAdapter(definition, session=session, config=config))
            elif source_id in {"polymarket_clob_price_history", "polymarket_price_history"}:
                adapters.append(PolymarketPriceHistoryAdapter(definition, session=session, config=config))
            elif source_id == "polymarket_clob_orderbook":
                adapters.append(PolymarketOrderbookAdapter(definition, session=session, config=config))
            elif source_id == "polymarket_fees":
                adapters.append(PolymarketFeesAdapter(definition, session=session, config=config))
            elif source_id == "open_meteo_previous_runs":
                adapters.append(OpenMeteoPreviousRunsAdapter(definition, session=session, config=config))
            elif source_id == "open_meteo_historical_forecast":
                adapters.append(OpenMeteoHistoricalForecastAdapter(definition, session=session, config=config))
            elif source_id == "open_meteo_forecast":
                adapters.append(OpenMeteoForecastAdapter(definition, session=session, config=config))
            elif source_id == "nws_api":
                adapters.append(NWSForecastAdapter(definition, session=session, config=config))
            elif source_id == "nws_gridpoints":
                adapters.append(NWSGridpointsAdapter(definition, session=session, config=config))
            elif source_id == "noaa_awc_metar":
                adapters.append(AWCMetarAdapter(definition, session=session, config=config))
            elif source_id == "noaa_nhc":
                adapters.append(NHCAdapter(definition, session=session, config=config))
            elif source_id == "noaa_swpc":
                adapters.append(SWPCAdapter(definition, session=session, config=config))
            elif source_id == "noaa_ncei_cdo":
                adapters.append(NCEICDOAdapter(definition, session=session, config=config))
            elif source_id == "noaa_madis_metar":
                adapters.append(MADISMetarAdapter(definition, session=session, config=config))
            elif source_id in {
                "ncep_nomads",
                "noaa_nbm",
                "noaa_hrrr",
                "noaa_rtma_urma",
                "noaa_nexrad",
                "noaa_stage_iv_qpe",
                "ecmwf_open_data",
                "dwd_icon_open_data",
            }:
                adapters.append(HeavyProductManifestAdapter(definition, session=session, config=config))
            else:
                adapters.append(WeatherSourceAdapter(definition, session=session, config=config))
        return adapters


class WeatherFeatureBuilder:
    def __init__(
        self,
        registry: Optional[WeatherSourceRegistry] = None,
        cost_assumptions: WeatherExecutionCostAssumptions = WeatherExecutionCostAssumptions(),
        session: Optional[requests.Session] = None,
        config: Optional[PolymarketCLIConfig] = None,
    ):
        self.registry = registry or WeatherSourceRegistry()
        self.cost_assumptions = cost_assumptions
        self.session = session or requests.Session()
        self.config = config
        self.station_mapper = WeatherStationMapper()
        self.station_bias_resolver = WeatherStationBiasResolver(
            getattr(config, "weather_station_bias_path", "") if config else None
        )
        self.high_resolution_builder = WeatherHighResolutionSourceBuilder(
            cache_dir=getattr(config, "weather_high_resolution_cache_dir", "") if config else None
        )

    def build_records(
        self,
        alpha_records: Iterable[Any],
        sources: str | Sequence[str],
    ) -> List[WeatherEdgeLabRecord]:
        adapters = self.registry.build_adapters(sources, session=self.session, config=self.config)
        normalized = []
        for row in alpha_records:
            features = [adapter.build(row) for adapter in adapters]
            normalized.append(self._normalize_row(row, features))
        return normalized

    def _normalize_row(self, row: Any, features: List[WeatherSourceFeature]) -> WeatherEdgeLabRecord:
        source_features = {feature.source_id: feature.to_dict() for feature in features}
        source_statuses = {feature.source_id: feature.status for feature in features}
        source_probabilities = {
            feature.source_id: bounded_probability(feature.probability)
            for feature in features
            if feature.probability is not None
        }
        blockers = sorted(
            {
                str(blocker)
                for feature in features
                for blocker in feature.blockers
                if str(blocker).strip()
            }
        )
        location_text = f"{_get(row, 'location', '')} {_get(row, 'question', '')}"
        mapped_location = self.station_mapper.detect_location(location_text)
        resolution = self.station_mapper.resolve(str(_get(row, "market_id", "")), mapped_location, str(_get(row, "question", "")))
        source_features["station_mapper"] = {
            "source_id": "station_mapper",
            "family": "resolution_target",
            "status": resolution.status,
            "features": resolution.to_dict(),
            "blockers": list(resolution.blockers),
        }
        source_statuses["station_mapper"] = resolution.status
        station_bias = self.station_bias_resolver.snapshot(resolution)
        source_features["station_bias"] = {
            "source_id": "station_bias",
            "family": "station_calibration",
            "status": station_bias.status,
            "features": station_bias.to_dict(),
            "blockers": list(station_bias.blockers),
        }
        source_statuses["station_bias"] = station_bias.status
        high_resolution_sources = self.high_resolution_builder.build_manifests(
            resolution=resolution,
            target_date=_parse_date(_get(row, "target_date", "")),
            metric=str(_get(row, "metric", "")),
            end_date=_parse_datetime(_get(row, "end_date", "")),
            source_ids=getattr(self.config, "weather_high_resolution_sources", None) if self.config else None,
        )
        source_features["high_resolution_manifests"] = {
            "source_id": "high_resolution_manifests",
            "family": "noaa_high_resolution",
            "status": "manifest_ready",
            "features": {"sources": high_resolution_sources},
            "blockers": [
                blocker
                for manifest in high_resolution_sources
                for blocker in manifest.get("blockers", [])
            ],
        }
        source_statuses["high_resolution_manifests"] = "manifest_ready"
        blockers = sorted(set(blockers + list(resolution.blockers)))
        model_probability = _float_or_none(_get(row, "model_probability", None))
        if model_probability is None:
            model_probability = _mean(source_probabilities.values()) if source_probabilities else 0.5
        market_yes_price = bounded_probability(
            _float_or_none(_get(row, "yes_price", _get(row, "market_yes_price", 0.5))) or 0.5
        )
        model_probability = bounded_probability(model_probability)
        edge = model_probability - market_yes_price
        selected_side = "YES" if edge >= 0 else "NO"
        yes_resolved = bool(_get(row, "yes_resolved", False))
        pnl = _float_or_none(_get(row, "pnl_per_usd", _get(row, "pnl", None)))
        if pnl is None:
            side_price = market_yes_price if selected_side == "YES" else max(0.001, 1.0 - market_yes_price)
            selected_win = yes_resolved if selected_side == "YES" else not yes_resolved
            pnl = ((1.0 - side_price) / side_price) if selected_win else -1.0
        fees = {"fee_rate": self.cost_assumptions.fee_rate, "fee_model": "research_haircut_default"}
        fee_feature = source_features.get("polymarket_fees", {}).get("features", {})
        if isinstance(fee_feature, dict) and fee_feature:
            fees.update(fee_feature)
        book_depth = _float_or_none(_get(row, "book_depth", None))
        if book_depth is None:
            book_depth = _float_or_none(
                source_features.get("polymarket_clob_orderbook", {}).get("features", {}).get("book_depth")
            )
        if book_depth is None:
            blockers.append("book_depth_missing")
            book_depth = 0.0
        return WeatherEdgeLabRecord(
            market_id=str(_get(row, "market_id", "")),
            question=str(_get(row, "question", "")),
            slug=str(_get(row, "slug", "")),
            asof_time=str(_get(row, "asof_time", "")),
            target_date=str(_get(row, "target_date", "")),
            location=str(_get(row, "location", "")),
            metric=str(_get(row, "metric", "")),
            threshold=_float_or_none(_get(row, "threshold", None)),
            operator=str(_get(row, "operator", "")),
            market_yes_price=round(market_yes_price, 4),
            market_no_price=round(max(0.001, 1.0 - market_yes_price), 4),
            book_depth=round(max(0.0, float(book_depth)), 4),
            fees=fees,
            source_probabilities=source_probabilities,
            source_features=source_features,
            source_statuses=source_statuses,
            model_probability=round(model_probability, 4),
            edge=round(edge, 4),
            selected_side=selected_side,
            resolution_label="YES" if yes_resolved else "NO",
            yes_resolved=yes_resolved,
            pnl=round(float(pnl), 4),
            blockers=blockers,
            lead_days=int(_float_or_none(_get(row, "lead_days", 0)) or 0),
            upper_threshold=_float_or_none(_get(row, "upper_threshold", None)),
            price_source=str(_get(row, "price_source", "")),
            forecast_source=str(_get(row, "forecast_source", "")),
            clob_price_age_hours=float(_float_or_none(_get(row, "clob_price_age_hours", 0.0)) or 0.0),
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            station_mapping=resolution.to_dict(),
            quality_flags=[
                FEATURE_SCHEMA_VERSION,
                *resolution.quality_flags,
                f"station_bias_status:{station_bias.status}",
                "high_resolution_sources_manifested",
            ],
            station_bias=station_bias.to_dict(),
            high_resolution_sources=high_resolution_sources,
            latency_signals={
                "clob_price_age_hours": float(_float_or_none(_get(row, "clob_price_age_hours", 0.0)) or 0.0),
                "price_source": str(_get(row, "price_source", "")),
            },
        )


class WeatherExecutionCostModel:
    def __init__(self, assumptions: WeatherExecutionCostAssumptions = WeatherExecutionCostAssumptions()):
        self.assumptions = assumptions

    def score(self, row: WeatherEdgeLabRecord, probability: float) -> Dict[str, Any]:
        market_price = bounded_probability(row.market_yes_price)
        probability = bounded_probability(probability)
        gross_edge = probability - market_price
        side = "YES" if gross_edge >= 0 else "NO"
        side_price = market_price if side == "YES" else max(0.001, 1.0 - market_price)
        edge_sign = 1.0 if gross_edge >= 0 else -1.0
        edge_haircut = self.assumptions.total_edge_haircut
        net_edge = edge_sign * max(0.0, abs(gross_edge) - edge_haircut)
        selected_win = row.yes_resolved if side == "YES" else not row.yes_resolved
        gross_pnl = ((1.0 - side_price) / side_price) if selected_win else -1.0
        net_pnl = gross_pnl - edge_haircut
        blockers = []
        if row.book_depth <= 0:
            blockers.append("book_depth_missing")
        if row.book_depth < self.assumptions.min_book_depth_usd:
            blockers.append("insufficient_book_depth")
        return {
            "probability": round(probability, 4),
            "market_yes_price": round(market_price, 4),
            "gross_edge": round(gross_edge, 4),
            "gross_edge_abs": round(abs(gross_edge), 4),
            "net_edge": round(net_edge, 4),
            "net_edge_abs": round(abs(net_edge), 4),
            "selected_side": side,
            "side_price": round(side_price, 4),
            "selected_win": selected_win,
            "gross_pnl_per_1usd": round(gross_pnl, 4),
            "net_pnl_per_1usd": round(net_pnl, 4),
            "edge_haircut": round(edge_haircut, 4),
            "blockers": blockers,
        }


class WeatherEdgeModelBuilder:
    def __init__(self, cost_model: Optional[WeatherExecutionCostModel] = None):
        self.cost_model = cost_model or WeatherExecutionCostModel()

    def run_matrix(
        self,
        rows: Iterable[WeatherEdgeLabRecord],
        edge_gaps: Sequence[float],
    ) -> Dict[str, Any]:
        records = [row for row in rows if _valid_record(row)]
        records.sort(key=lambda row: (row.target_date, row.market_id, row.asof_time))
        train, holdout, target_dates = self._split_chronological(records)
        prediction_sets, model_configs = self._build_prediction_sets(train, holdout)
        market_predictions = {row.key(): bounded_probability(row.market_yes_price) for row in records}
        market_baseline = {
            "train": self._score_predictions(train, market_predictions, edge_gap=0.0),
            "holdout": self._score_predictions(holdout, market_predictions, edge_gap=0.0),
        }

        matrix = []
        for model_name in MODEL_VARIANTS:
            predictions = prediction_sets.get(model_name, {})
            for edge_gap in edge_gaps:
                train_score = self._score_predictions(train, predictions, edge_gap=edge_gap)
                holdout_score = self._score_predictions(holdout, predictions, edge_gap=edge_gap)
                matrix.append(
                    {
                        "model_name": model_name,
                        "edge_gap": round(float(edge_gap), 4),
                        "config": model_configs.get(model_name, {}),
                        "train": train_score,
                        "holdout": holdout_score,
                    }
                )

        return_summary = self._return_summary(matrix, market_baseline)
        best_result = self._select_best_result(matrix)
        return {
            "generated_at": utc_now_iso(),
            "record_count": len(records),
            "train_records": len(train),
            "holdout_records": len(holdout),
            "target_date_count": len(target_dates),
            "target_dates": target_dates,
            "edge_gaps": [round(float(gap), 4) for gap in edge_gaps],
            "model_variants": model_configs,
            "market_baseline": market_baseline,
            "matrix": matrix,
            "return_summary": return_summary,
            "best_result": best_result,
        }

    def _build_prediction_sets(
        self,
        train: List[WeatherEdgeLabRecord],
        holdout: List[WeatherEdgeLabRecord],
    ) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, Any]]]:
        all_rows = train + holdout
        predictions: Dict[str, Dict[str, float]] = {}
        configs: Dict[str, Dict[str, Any]] = {}

        predictions["heuristic_baseline"] = {
            row.key(): self._forecast_probability(row) for row in all_rows
        }
        configs["heuristic_baseline"] = {
            "method": "existing_weather_alpha_heuristic",
            "bounded_probability": [0.02, 0.98],
        }

        blend_weight = self._fit_blend_weight(train)
        predictions["market_forecast_blend"] = {
            row.key(): bounded_probability(row.market_yes_price + blend_weight * (self._forecast_probability(row) - row.market_yes_price))
            for row in all_rows
        }
        configs["market_forecast_blend"] = {
            "method": "grid_search_market_plus_forecast_delta",
            "forecast_weight": round(blend_weight, 4),
        }

        logistic_predictions, logistic_config = self._fit_logistic(train, holdout)
        predictions["logistic_calibration"] = logistic_predictions
        configs["logistic_calibration"] = logistic_config

        isotonic_predictions, isotonic_config = self._fit_isotonic(train, holdout)
        predictions["isotonic_calibration"] = isotonic_predictions
        configs["isotonic_calibration"] = isotonic_config

        predictions["source_ensemble"] = {
            row.key(): self._source_ensemble_probability(row) for row in all_rows
        }
        configs["source_ensemble"] = {
            "method": "mean_available_source_probabilities",
            "fallback": "heuristic_baseline",
        }

        slice_counts = Counter((row.location, row.metric, row.lead_days) for row in train)
        predictions["shrink_to_market"] = {
            row.key(): self._shrink_to_market_probability(row, slice_counts)
            for row in all_rows
        }
        configs["shrink_to_market"] = {
            "method": "forecast_delta_shrunk_by_train_slice_count",
            "full_weight_records_per_slice": 50,
        }

        return predictions, configs

    def _fit_blend_weight(self, train: List[WeatherEdgeLabRecord]) -> float:
        if not train:
            return 0.5
        best_weight = 0.0
        best_brier: Optional[float] = None
        for step in range(0, 21):
            weight = step / 20.0
            total = 0.0
            for row in train:
                probability = bounded_probability(row.market_yes_price + weight * (self._forecast_probability(row) - row.market_yes_price))
                outcome = 1.0 if row.yes_resolved else 0.0
                total += (probability - outcome) ** 2
            brier = total / len(train)
            if best_brier is None or brier < best_brier:
                best_brier = brier
                best_weight = weight
        return best_weight

    def _fit_logistic(
        self,
        train: List[WeatherEdgeLabRecord],
        holdout: List[WeatherEdgeLabRecord],
    ) -> Tuple[Dict[str, float], Dict[str, Any]]:
        all_rows = train + holdout
        fallback = {row.key(): self._forecast_probability(row) for row in all_rows}
        if len(train) < 8 or len({row.yes_resolved for row in train}) < 2:
            return fallback, {
                "method": "sklearn_logistic_regression",
                "status": "fallback_heuristic",
                "blockers": ["need_at_least_8_train_records_with_both_classes"],
            }
        try:
            from sklearn.linear_model import LogisticRegression
        except Exception as exc:  # pragma: no cover - depends on local environment
            return fallback, {
                "method": "sklearn_logistic_regression",
                "status": "fallback_heuristic",
                "blockers": [f"sklearn_unavailable:{type(exc).__name__}"],
            }

        model = LogisticRegression(solver="liblinear", random_state=17)
        model.fit([self._feature_vector(row) for row in train], [1 if row.yes_resolved else 0 for row in train])
        predictions = {}
        for row in all_rows:
            predictions[row.key()] = bounded_probability(float(model.predict_proba([self._feature_vector(row)])[0][1]))
        return predictions, {
            "method": "sklearn_logistic_regression",
            "status": "fit",
            "features": ["market_yes_price", "forecast_probability", "source_ensemble", "lead_days", "threshold"],
        }

    def _fit_isotonic(
        self,
        train: List[WeatherEdgeLabRecord],
        holdout: List[WeatherEdgeLabRecord],
    ) -> Tuple[Dict[str, float], Dict[str, Any]]:
        all_rows = train + holdout
        fallback = {row.key(): self._forecast_probability(row) for row in all_rows}
        if len(train) < 8 or len({row.yes_resolved for row in train}) < 2:
            return fallback, {
                "method": "sklearn_isotonic_regression",
                "status": "fallback_heuristic",
                "blockers": ["need_at_least_8_train_records_with_both_classes"],
            }
        try:
            from sklearn.isotonic import IsotonicRegression
        except Exception as exc:  # pragma: no cover - depends on local environment
            return fallback, {
                "method": "sklearn_isotonic_regression",
                "status": "fallback_heuristic",
                "blockers": [f"sklearn_unavailable:{type(exc).__name__}"],
            }

        model = IsotonicRegression(y_min=0.02, y_max=0.98, out_of_bounds="clip")
        model.fit(
            [self._forecast_probability(row) for row in train],
            [1.0 if row.yes_resolved else 0.0 for row in train],
        )
        predictions = {
            row.key(): bounded_probability(float(model.predict([self._forecast_probability(row)])[0]))
            for row in all_rows
        }
        return predictions, {
            "method": "sklearn_isotonic_regression",
            "status": "fit",
            "input": "forecast_probability",
        }

    def _score_predictions(
        self,
        rows: List[WeatherEdgeLabRecord],
        predictions: Dict[str, float],
        edge_gap: float,
    ) -> Dict[str, Any]:
        if not rows:
            return self._empty_score()
        scored = []
        total_brier = 0.0
        total_log_loss = 0.0
        for row in rows:
            probability = bounded_probability(predictions.get(row.key(), self._forecast_probability(row)))
            outcome = 1.0 if row.yes_resolved else 0.0
            total_brier += (probability - outcome) ** 2
            total_log_loss += -math.log(probability if row.yes_resolved else 1.0 - probability)
            execution = self.cost_model.score(row, probability)
            scored.append((row, execution))

        raw_candidates = [
            (row, execution)
            for row, execution in scored
            if execution["net_edge_abs"] >= edge_gap and not execution.get("blockers")
        ]
        candidates = self._dedupe_candidates_by_market(raw_candidates)
        wins = sum(1 for _row, execution in candidates if execution["selected_win"])
        pnl = sum(float(execution["net_pnl_per_1usd"]) for _row, execution in candidates)
        concentration = self._pnl_concentration(candidates)
        market_concentration = self._market_pnl_concentration(candidates)
        return {
            "records": len(rows),
            "unique_market_count": len({row.market_id for row in rows}),
            "candidate_count": len(candidates),
            "candidate_unique_market_count": len({row.market_id for row, _execution in candidates}),
            "candidate_win_rate": round(wins / len(candidates), 4) if candidates else None,
            "candidate_roi_after_cost": round(pnl / len(candidates), 4) if candidates else 0.0,
            "candidate_pnl_after_cost": round(pnl, 4),
            "brier": round(total_brier / len(rows), 6),
            "log_loss": round(total_log_loss / len(rows), 6),
            "max_single_location_date_metric_pnl_share": concentration,
            "max_single_market_pnl_share": market_concentration,
            "top_candidates": [
                self._candidate_payload(row, execution)
                for row, execution in sorted(candidates, key=lambda item: item[1]["net_edge_abs"], reverse=True)[:25]
            ],
        }

    @staticmethod
    def _dedupe_candidates_by_market(
        candidates: List[Tuple[WeatherEdgeLabRecord, Dict[str, Any]]]
    ) -> List[Tuple[WeatherEdgeLabRecord, Dict[str, Any]]]:
        best: Dict[str, Tuple[WeatherEdgeLabRecord, Dict[str, Any]]] = {}
        for row, execution in candidates:
            key = row.market_id or row.key()
            current = best.get(key)
            if current is None or float(execution.get("net_edge_abs", 0.0) or 0.0) > float(current[1].get("net_edge_abs", 0.0) or 0.0):
                best[key] = (row, execution)
        return list(best.values())

    @staticmethod
    def _pnl_concentration(candidates: List[Tuple[WeatherEdgeLabRecord, Dict[str, Any]]]) -> float:
        total_positive = sum(max(0.0, float(execution["net_pnl_per_1usd"])) for _row, execution in candidates)
        if total_positive <= 0:
            return 0.0
        grouped: Dict[Tuple[str, str, str], float] = defaultdict(float)
        for row, execution in candidates:
            grouped[(row.location, row.target_date, row.metric)] += max(0.0, float(execution["net_pnl_per_1usd"]))
        return round(max(grouped.values(), default=0.0) / total_positive, 4)

    @staticmethod
    def _market_pnl_concentration(candidates: List[Tuple[WeatherEdgeLabRecord, Dict[str, Any]]]) -> float:
        total_positive = sum(max(0.0, float(execution["net_pnl_per_1usd"])) for _row, execution in candidates)
        if total_positive <= 0:
            return 0.0
        grouped: Dict[str, float] = defaultdict(float)
        for row, execution in candidates:
            grouped[row.market_id] += max(0.0, float(execution["net_pnl_per_1usd"]))
        return round(max(grouped.values(), default=0.0) / total_positive, 4)

    @staticmethod
    def _candidate_payload(row: WeatherEdgeLabRecord, execution: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "market_id": row.market_id,
            "question": row.question,
            "target_date": row.target_date,
            "location": row.location,
            "metric": row.metric,
            "lead_days": row.lead_days,
            "asof_time": row.asof_time,
            "selected_side": execution["selected_side"],
            "market_yes_price": execution["market_yes_price"],
            "side_price": execution["side_price"],
            "probability": execution["probability"],
            "net_edge": execution["net_edge"],
            "net_edge_abs": execution["net_edge_abs"],
            "selected_win": execution["selected_win"],
            "net_pnl_per_1usd": execution["net_pnl_per_1usd"],
            "clob_price_age_hours": row.clob_price_age_hours,
            "blockers": list(row.blockers),
        }

    @staticmethod
    def _select_best_result(matrix: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not matrix:
            return {}

        def rank(item: Dict[str, Any]) -> Tuple[float, float, float, float]:
            holdout = item.get("holdout", {})
            return (
                float(holdout.get("candidate_count", 0) or 0),
                float(holdout.get("candidate_roi_after_cost", 0.0) or 0.0),
                -float(holdout.get("brier", 999.0) or 999.0),
                -float(item.get("edge_gap", 0.0) or 0.0),
            )

        return dict(max(matrix, key=rank))

    @staticmethod
    def _return_summary(matrix: List[Dict[str, Any]], market_baseline: Dict[str, Any]) -> Dict[str, Any]:
        rows = []
        for item in matrix:
            train = item.get("train", {})
            holdout = item.get("holdout", {})
            rows.append(
                {
                    "model_name": item.get("model_name"),
                    "edge_gap": item.get("edge_gap"),
                    "train_candidate_count": train.get("candidate_count", 0),
                    "train_roi_after_cost": train.get("candidate_roi_after_cost", 0.0),
                    "train_pnl_after_cost": train.get("candidate_pnl_after_cost", 0.0),
                    "holdout_candidate_count": holdout.get("candidate_count", 0),
                    "holdout_roi_after_cost": holdout.get("candidate_roi_after_cost", 0.0),
                    "holdout_pnl_after_cost": holdout.get("candidate_pnl_after_cost", 0.0),
                    "holdout_brier": holdout.get("brier"),
                    "holdout_log_loss": holdout.get("log_loss"),
                    "holdout_pnl_concentration": holdout.get("max_single_location_date_metric_pnl_share", 0.0),
                    "holdout_market_pnl_concentration": holdout.get("max_single_market_pnl_share", 0.0),
                }
            )

        with_candidates = [row for row in rows if int(row.get("holdout_candidate_count", 0) or 0) > 0]
        return {
            "unit_stake": "1 USD per selected candidate",
            "cost_model": "net PnL subtracts fee/spread/slippage haircut from each selected candidate",
            "market_baseline_holdout": market_baseline.get("holdout", {}),
            "best_by_holdout_roi": _best_summary_row(with_candidates, "holdout_roi_after_cost"),
            "best_by_holdout_pnl": _best_summary_row(with_candidates, "holdout_pnl_after_cost"),
            "best_by_holdout_candidate_count": _best_summary_row(with_candidates, "holdout_candidate_count"),
            "positive_holdout_roi_rows": [
                row for row in rows if float(row.get("holdout_roi_after_cost", 0.0) or 0.0) > 0.0
            ],
            "rows": rows,
        }

    @staticmethod
    def _split_chronological(
        records: List[WeatherEdgeLabRecord],
        holdout_ratio: float = 0.35,
    ) -> Tuple[List[WeatherEdgeLabRecord], List[WeatherEdgeLabRecord], List[str]]:
        target_dates = sorted({row.target_date for row in records if row.target_date})
        if len(target_dates) < 2:
            return records, [], target_dates
        holdout_dates = max(1, int(math.floor(len(target_dates) * max(0.05, min(0.8, holdout_ratio)))))
        holdout_dates = min(holdout_dates, len(target_dates) - 1)
        holdout_set = set(target_dates[-holdout_dates:])
        train = [row for row in records if row.target_date not in holdout_set]
        holdout = [row for row in records if row.target_date in holdout_set]
        return train, holdout, target_dates

    def _feature_vector(self, row: WeatherEdgeLabRecord) -> List[float]:
        return [
            bounded_probability(row.market_yes_price),
            self._forecast_probability(row),
            self._source_ensemble_probability(row),
            float(row.lead_days),
            float(row.threshold or 0.0),
        ]

    @staticmethod
    def _forecast_probability(row: WeatherEdgeLabRecord) -> float:
        if row.forecast_source and row.forecast_source in row.source_probabilities:
            return bounded_probability(row.source_probabilities[row.forecast_source])
        for preferred in ("open_meteo_previous_runs", "open_meteo_historical_forecast"):
            if preferred in row.source_probabilities:
                return bounded_probability(row.source_probabilities[preferred])
        return bounded_probability(row.model_probability)

    def _source_ensemble_probability(self, row: WeatherEdgeLabRecord) -> float:
        values = [
            bounded_probability(value)
            for source_id, value in row.source_probabilities.items()
            if source_id != "polymarket_clob_price_history"
        ]
        return bounded_probability(_mean(values) if values else self._forecast_probability(row))

    def _shrink_to_market_probability(
        self,
        row: WeatherEdgeLabRecord,
        slice_counts: Counter[Tuple[str, str, int]],
    ) -> float:
        count = slice_counts.get((row.location, row.metric, row.lead_days), 0)
        weight = min(1.0, max(0.15, count / 50.0))
        forecast = self._forecast_probability(row)
        return bounded_probability(row.market_yes_price + weight * (forecast - row.market_yes_price))

    @staticmethod
    def _empty_score() -> Dict[str, Any]:
        return {
            "records": 0,
            "candidate_count": 0,
            "candidate_win_rate": None,
            "candidate_roi_after_cost": 0.0,
            "candidate_pnl_after_cost": 0.0,
            "brier": None,
            "log_loss": None,
            "max_single_location_date_metric_pnl_share": 0.0,
            "max_single_market_pnl_share": 0.0,
            "unique_market_count": 0,
            "candidate_unique_market_count": 0,
            "top_candidates": [],
        }


class WeatherPromotionGateEvaluator:
    def __init__(self, gates: WeatherPromotionGates = WeatherPromotionGates()):
        self.gates = gates

    def evaluate(
        self,
        feature_records: List[WeatherEdgeLabRecord],
        backtest_report: Dict[str, Any],
        paper_export_requested: bool,
    ) -> Dict[str, Any]:
        blockers: List[str] = []
        record_count = int(backtest_report.get("record_count", 0) or 0)
        target_date_count = int(backtest_report.get("target_date_count", 0) or 0)
        best = backtest_report.get("best_result", {}) if isinstance(backtest_report.get("best_result"), dict) else {}
        holdout = best.get("holdout", {}) if isinstance(best.get("holdout"), dict) else {}
        holdout_market = (
            backtest_report.get("market_baseline", {}).get("holdout", {})
            if isinstance(backtest_report.get("market_baseline"), dict)
            else {}
        )

        if record_count < self.gates.min_resolved_records:
            blockers.append(f"need_at_least_{self.gates.min_resolved_records}_resolved_records")
        if target_date_count < self.gates.min_target_dates:
            blockers.append(f"need_at_least_{self.gates.min_target_dates}_target_dates")
        if int(holdout.get("candidate_count", 0) or 0) < self.gates.min_holdout_candidate_edges:
            blockers.append(f"need_at_least_{self.gates.min_holdout_candidate_edges}_holdout_candidate_edges")
        if not _metric_improves_by(
            holdout.get("brier"),
            holdout_market.get("brier"),
            self.gates.min_market_baseline_improvement,
        ):
            blockers.append("holdout_brier_not_2pct_better_than_market")
        if not _metric_improves_by(
            holdout.get("log_loss"),
            holdout_market.get("log_loss"),
            self.gates.min_market_baseline_improvement,
        ):
            blockers.append("holdout_log_loss_not_2pct_better_than_market")
        if float(holdout.get("candidate_roi_after_cost", 0.0) or 0.0) <= self.gates.min_holdout_roi_after_cost:
            blockers.append("holdout_roi_after_cost_not_positive")
        if (
            float(holdout.get("max_single_location_date_metric_pnl_share", 0.0) or 0.0)
            > self.gates.max_single_slice_pnl_share
        ):
            blockers.append("single_location_date_metric_over_35pct_holdout_pnl")
        if (
            float(holdout.get("max_single_market_pnl_share", 0.0) or 0.0)
            > self.gates.max_single_slice_pnl_share
        ):
            blockers.append("single_market_over_35pct_holdout_pnl")

        selected = holdout.get("top_candidates", []) if isinstance(holdout.get("top_candidates"), list) else []
        max_price_age = max(
            [_float_or_none(candidate.get("clob_price_age_hours")) or 0.0 for candidate in selected],
            default=0.0,
        )
        if max_price_age > self.gates.max_selected_clob_price_age_hours:
            blockers.append("selected_clob_price_older_than_3h")

        feature_blockers = sorted(
            {
                blocker
                for row in feature_records
                for blocker in row.blockers
                if _is_promotion_hard_blocker(blocker)
            }
        )
        blockers.extend(blocker for blocker in feature_blockers if blocker not in blockers)

        accepted = not blockers
        return {
            "accepted_for_paper_trade": accepted,
            "accepted_for_live_automation": False,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "accepted_feature_schema_version": FEATURE_SCHEMA_VERSION,
            "paper_export_requested": bool(paper_export_requested),
            "live_automation_status": "deferred_until_explicit_manual_confirmation",
            "blockers": blockers,
            "strict_promotion_bar": asdict(self.gates),
            "best_model": best.get("model_name"),
            "best_edge_gap": best.get("edge_gap"),
            "validated_source_families": sorted(
                {
                    _source_family_from_id(source_id)
                    for row in feature_records
                    for source_id, status in row.source_statuses.items()
                    if status in {"live_safe", "research_only"}
                }
            ),
            "validated_min_probability_gap": best.get("edge_gap"),
            "holdout_candidate_count": holdout.get("candidate_count", 0),
            "holdout_roi_after_cost": holdout.get("candidate_roi_after_cost", 0.0),
            "max_selected_clob_price_age_hours": round(max_price_age, 4),
            "required_evidence": [
                f">= {self.gates.min_resolved_records} resolved records",
                f">= {self.gates.min_target_dates} target dates",
                f">= {self.gates.min_holdout_candidate_edges} holdout candidate edges",
                "holdout Brier and log loss at least 2% better than market baseline",
                "positive holdout ROI after execution-cost haircut",
                "no single location/date/metric over 35% of holdout PnL",
                "max selected CLOB price age <= 3h",
                "paper mode only; live automation requires a future explicit confirmation",
            ],
        }


class WeatherPaperExportBuilder:
    def export(
        self,
        feature_records: List[WeatherEdgeLabRecord],
        backtest_report: Dict[str, Any],
        verdict: Dict[str, Any],
        output_dir: Path,
        requested: bool,
    ) -> Dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = output_dir / "latest_paper_recommendations.jsonl"
        csv_path = output_dir / "latest_paper_recommendations.csv"
        manifest_path = output_dir / "latest_paper_export.json"

        rows: List[Dict[str, Any]] = []
        if requested and verdict.get("accepted_for_paper_trade"):
            best = backtest_report.get("best_result", {}) if isinstance(backtest_report.get("best_result"), dict) else {}
            holdout = best.get("holdout", {}) if isinstance(best.get("holdout"), dict) else {}
            for candidate in holdout.get("top_candidates", [])[:25]:
                if candidate.get("blockers"):
                    continue
                rows.append(
                    {
                        "execution_mode": "paper",
                        "feature_schema_version": FEATURE_SCHEMA_VERSION,
                        "source": "weather_edge_lab",
                        "model_name": best.get("model_name"),
                        "edge_gap": best.get("edge_gap"),
                        "market_id": candidate.get("market_id"),
                        "question": candidate.get("question"),
                        "target_date": candidate.get("target_date"),
                        "location": candidate.get("location"),
                        "metric": candidate.get("metric"),
                        "lead_days": candidate.get("lead_days"),
                        "asof_time": candidate.get("asof_time"),
                        "side": candidate.get("selected_side"),
                        "limit_price": candidate.get("side_price", candidate.get("market_yes_price")),
                        "model_probability": candidate.get("probability"),
                        "net_edge": candidate.get("net_edge"),
                        "paper_size_usd": 1.0,
                        "live_order_enabled": False,
                    }
                )

        jsonl_path.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )
        fieldnames = [
            "execution_mode",
            "feature_schema_version",
            "source",
            "model_name",
            "edge_gap",
            "market_id",
            "question",
            "target_date",
            "location",
            "metric",
            "lead_days",
            "asof_time",
            "side",
            "limit_price",
            "model_probability",
            "net_edge",
            "paper_size_usd",
            "live_order_enabled",
        ]
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

        manifest = {
            "generated_at": utc_now_iso(),
            "requested": bool(requested),
            "paper_recommendation_count": len(rows),
            "blocked": not bool(verdict.get("accepted_for_paper_trade")),
            "blockers": verdict.get("blockers", []),
            "live_order_enabled": False,
            "credentials_loaded": False,
            "jsonl": str(jsonl_path),
            "csv": str(csv_path),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest


class WeatherResearchLiaison:
    def __init__(self, report_path: Optional[Path] = None):
        self.report_path = report_path

    def load_report(self) -> Dict[str, Any]:
        if not self.report_path or not self.report_path.exists():
            return {}
        try:
            payload = json.loads(self.report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def map_tracks_to_experiments(self, research_report: Dict[str, Any]) -> List[Dict[str, Any]]:
        tracks = (
            research_report.get("edge_generation_plan", {}).get("tracks", [])
            if isinstance(research_report.get("edge_generation_plan"), dict)
            else []
        )
        mapped = []
        for track in tracks:
            if not isinstance(track, dict):
                continue
            mapped.append(
                {
                    "track_code": track.get("code", ""),
                    "title": track.get("title", ""),
                    "lab_experiment": self._experiment_for_track(str(track.get("code", ""))),
                    "blockers": [],
                }
            )
        return mapped

    @staticmethod
    def _experiment_for_track(code: str) -> str:
        return {
            "structural_bucket_arbitrage": "orderbook_depth_and_fee_capacity_matrix",
            "forecast_mispricing": "multi_source_forecast_probability_holdout",
            "asof_calibrated_model": "lead_day_calibration_and_edge_gap_matrix",
            "resolution_source_latency": "official_source_latency_dataset",
            "model_disagreement_repricing": "source_disagreement_repricing_matrix",
        }.get(code, "historical_feature_backtest")


class WeatherEdgeLabRunner:
    def __init__(
        self,
        config: Optional[PolymarketCLIConfig] = None,
        session: Optional[requests.Session] = None,
        output_dir: Optional[Path] = None,
        research_report_path: Optional[Path] = None,
    ):
        self.config = config or PolymarketCLIConfig(
            execution_mode=ExecutionMode.DRY_RUN,
            market_vertical="weather",
            search_symbols=["WEATHER"],
            min_volume_24h_usd=0.0,
        )
        self.session = session or requests.Session()
        self.output_dir = Path(output_dir) if output_dir else self.config.data_dir / "weather_edge_lab"
        self.paths = {name: self.output_dir / name for name in LAB_SUBDIRS}
        for path in self.paths.values():
            path.mkdir(parents=True, exist_ok=True)
        self.registry = WeatherSourceRegistry()
        self.feature_builder = WeatherFeatureBuilder(self.registry, session=self.session, config=self.config)
        self.model_builder = WeatherEdgeModelBuilder()
        self.gate_evaluator = WeatherPromotionGateEvaluator()
        self.paper_export_builder = WeatherPaperExportBuilder()
        default_research_path = self.config.data_dir / "weather_research_team" / "latest_weather_edge_report.json"
        self.research_liaison = WeatherResearchLiaison(research_report_path or default_research_path)

    def run(
        self,
        max_events: int = 80,
        max_markets: int = 250,
        lead_days: Sequence[int] = (0, 1, 2, 3),
        edge_gaps: Sequence[float] = (0.04, 0.08, 0.12, 0.20),
        sources: str | Sequence[str] = "all",
        min_volume: float = 0.0,
        past_days: int = 7,
        paper_export: bool = False,
    ) -> Dict[str, Any]:
        alpha_records: List[WeatherAlphaRecord] = []
        source_ids = self.registry.resolve_source_ids(sources)
        forecast_source = self._alpha_forecast_source(source_ids)
        backtester = WeatherAlphaBacktester(
            config=self.config,
            session=self.session,
            output_dir=self.paths["datasets"] / "weather_alpha_cache",
        )
        per_lead_counts = {}
        for lead_day in lead_days:
            rows = backtester.build_dataset(
                max_events=max_events,
                max_markets=max_markets,
                min_volume=min_volume,
                lead_days=int(lead_day),
                past_days=past_days,
                fetch_prices=True,
                forecast_source=forecast_source,
            )
            alpha_records.extend(rows)
            per_lead_counts[str(lead_day)] = len(rows)
        return self.run_from_alpha_records(
            alpha_records,
            lead_days=lead_days,
            edge_gaps=edge_gaps,
            sources=source_ids,
            paper_export=paper_export,
            collection_summary={
                "max_events": max_events,
                "max_markets": max_markets,
                "min_volume": min_volume,
                "past_days": past_days,
                "forecast_source": forecast_source,
                "per_lead_record_counts": per_lead_counts,
                "skip_reasons": dict(backtester.skip_reasons),
            },
        )

    def run_from_alpha_records(
        self,
        alpha_records: Iterable[Any],
        lead_days: Sequence[int] = (0, 1, 2, 3),
        edge_gaps: Sequence[float] = (0.04, 0.08, 0.12, 0.20),
        sources: str | Sequence[str] = "open_meteo_previous_runs",
        paper_export: bool = False,
        collection_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        source_ids = self.registry.resolve_source_ids(sources)
        feature_records = self.feature_builder.build_records(alpha_records, source_ids)
        backtest_report = self.model_builder.run_matrix(feature_records, [float(gap) for gap in edge_gaps])
        verdict = self.gate_evaluator.evaluate(feature_records, backtest_report, paper_export_requested=paper_export)
        paper_export_manifest = self.paper_export_builder.export(
            feature_records,
            backtest_report,
            verdict,
            self.paths["paper_exports"],
            requested=paper_export,
        )
        research_report = self.research_liaison.load_report()
        report = {
            "generated_at": utc_now_iso(),
            "mode": "research_paper_only",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "live_trade_export_enabled": False,
            "builder_team": self.builder_team_manifest(),
            "research_liaison": {
                "report_path": str(self.research_liaison.report_path) if self.research_liaison.report_path else "",
                "report_loaded": bool(research_report),
                "track_experiments": self.research_liaison.map_tracks_to_experiments(research_report),
            },
            "collection_summary": collection_summary or {},
            "source_ids": source_ids,
            "lead_days": [int(day) for day in lead_days],
            "edge_gaps": [round(float(gap), 4) for gap in edge_gaps],
            "dataset": {
                "record_count": len(feature_records),
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "target_date_count": backtest_report.get("target_date_count", 0),
                "feature_blockers": self._feature_blocker_summary(feature_records),
            },
            "backtest": backtest_report,
            "promotion_verdict": verdict,
            "paper_export": paper_export_manifest,
            "artifacts": self._write_artifacts(feature_records, backtest_report, verdict, paper_export_manifest),
        }
        self._write_latest_report(report)
        return report

    @staticmethod
    def builder_team_manifest() -> List[Dict[str, str]]:
        return [
            {"role": "Dataset Builder", "output": "immutable resolved-market and price-history datasets"},
            {"role": "Weather Source Builder", "output": "normalized source features with live-safe/research-only blockers"},
            {"role": "Model Builder", "output": "heuristic, blend, logistic, isotonic, ensemble, and shrink model results"},
            {"role": "Backtest Builder", "output": "lead-time and edge-threshold matrix reports"},
            {"role": "Execution Builder", "output": "fee, spread, slippage, depth, and capacity haircuts"},
            {"role": "Paper Export Builder", "output": "paper-only recommendations after gates pass"},
            {"role": "Research Liaison", "output": "research track to lab experiment mapping"},
        ]

    @staticmethod
    def _feature_blocker_summary(feature_records: List[WeatherEdgeLabRecord]) -> Dict[str, int]:
        counter: Counter[str] = Counter()
        for row in feature_records:
            counter.update(row.blockers)
        return dict(counter)

    def _write_artifacts(
        self,
        feature_records: List[WeatherEdgeLabRecord],
        backtest_report: Dict[str, Any],
        verdict: Dict[str, Any],
        paper_export_manifest: Dict[str, Any],
    ) -> Dict[str, str]:
        dataset_path = self.paths["datasets"] / "weather_edge_lab_records.jsonl"
        features_path = self.paths["features"] / "weather_edge_lab_features.jsonl"
        backtest_path = self.paths["backtests"] / "latest_backtest_report.json"
        models_path = self.paths["models"] / "latest_model_matrix.json"
        gates_path = self.paths["backtests"] / "latest_promotion_verdict.json"

        lines = [json.dumps(row.to_dict(), sort_keys=True) for row in feature_records]
        dataset_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        features_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        backtest_path.write_text(json.dumps(backtest_report, indent=2), encoding="utf-8")
        models_path.write_text(json.dumps(backtest_report.get("model_variants", {}), indent=2), encoding="utf-8")
        gates_path.write_text(json.dumps(verdict, indent=2), encoding="utf-8")
        return {
            "datasets": str(dataset_path),
            "features": str(features_path),
            "backtests": str(backtest_path),
            "models": str(models_path),
            "promotion_verdict": str(gates_path),
            "paper_export": str(paper_export_manifest.get("jsonl", "")),
        }

    def _write_latest_report(self, report: Dict[str, Any]) -> None:
        json_path = self.output_dir / "latest_weather_edge_lab_report.json"
        md_path = self.output_dir / "latest_weather_edge_lab_report.md"
        json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        md_path.write_text(self._format_markdown(report), encoding="utf-8")

    @staticmethod
    def _format_markdown(report: Dict[str, Any]) -> str:
        verdict = report.get("promotion_verdict", {})
        backtest = report.get("backtest", {}) if isinstance(report.get("backtest"), dict) else {}
        best = backtest.get("best_result", {})
        returns = backtest.get("return_summary", {}) if isinstance(backtest.get("return_summary"), dict) else {}
        holdout = best.get("holdout", {}) if isinstance(best, dict) else {}
        best_roi = returns.get("best_by_holdout_roi", {}) if isinstance(returns.get("best_by_holdout_roi"), dict) else {}
        best_pnl = returns.get("best_by_holdout_pnl", {}) if isinstance(returns.get("best_by_holdout_pnl"), dict) else {}
        lines = [
            "# Weather Edge Historical Lab",
            "",
            f"- Generated: `{report.get('generated_at')}`",
            f"- Mode: `{report.get('mode')}`",
            f"- Feature schema: `{report.get('feature_schema_version')}`",
            f"- Live trade export enabled: `{report.get('live_trade_export_enabled')}`",
            f"- Records: `{report.get('dataset', {}).get('record_count')}`",
            f"- Target dates: `{report.get('dataset', {}).get('target_date_count')}`",
            f"- Best model: `{best.get('model_name')}`",
            f"- Best edge gap: `{best.get('edge_gap')}`",
            f"- Holdout candidates: `{holdout.get('candidate_count')}`",
            f"- Holdout ROI after cost: `{holdout.get('candidate_roi_after_cost')}`",
            f"- Best holdout ROI row: `{best_roi.get('model_name')}` gap `{best_roi.get('edge_gap')}` ROI `{best_roi.get('holdout_roi_after_cost')}` PnL `{best_roi.get('holdout_pnl_after_cost')}`",
            f"- Best holdout PnL row: `{best_pnl.get('model_name')}` gap `{best_pnl.get('edge_gap')}` ROI `{best_pnl.get('holdout_roi_after_cost')}` PnL `{best_pnl.get('holdout_pnl_after_cost')}`",
            f"- Accepted for paper trade: `{verdict.get('accepted_for_paper_trade')}`",
            "",
            "## Logic",
            "- Build resolved weather records from Polymarket outcomes and historical CLOB YES prices.",
            "- Convert weather features into YES probabilities, then compare model probability to market price.",
            "- Select YES when model probability is above market price, otherwise select NO.",
            "- Backtest each selected candidate with a $1 unit stake and subtract the configured fee/spread/slippage haircut.",
            "- Promote only if chronological holdout beats market Brier/log-loss by at least 2%, has positive ROI, enough candidates, enough dates, and no PnL concentration problem.",
            "",
            "## Returns Matrix",
            "| Model | Gap | Train Cand | Train ROI | Train PnL | Holdout Cand | Holdout ROI | Holdout PnL | Holdout Brier | Holdout Log Loss |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in returns.get("rows", [])[:40]:
            lines.append(
                "| "
                f"{row.get('model_name')} | "
                f"{row.get('edge_gap')} | "
                f"{row.get('train_candidate_count')} | "
                f"{row.get('train_roi_after_cost')} | "
                f"{row.get('train_pnl_after_cost')} | "
                f"{row.get('holdout_candidate_count')} | "
                f"{row.get('holdout_roi_after_cost')} | "
                f"{row.get('holdout_pnl_after_cost')} | "
                f"{row.get('holdout_brier')} | "
                f"{row.get('holdout_log_loss')} |"
            )
        lines.extend(
            [
                "",
            "## Blockers",
            ]
        )
        blockers = verdict.get("blockers", [])
        lines.extend([f"- `{blocker}`" for blocker in blockers] if blockers else ["- None"])
        lines.extend(["", "## Builder Team"])
        for role in report.get("builder_team", []):
            lines.append(f"- **{role.get('role')}**: {role.get('output')}")
        lines.extend(["", "## Top Holdout Candidates"])
        for candidate in holdout.get("top_candidates", [])[:10]:
            lines.append(
                f"- `{candidate.get('selected_side')}` net edge `{float(candidate.get('net_edge', 0.0)):+.2%}` "
                f"pnl=`{candidate.get('net_pnl_per_1usd')}` | {candidate.get('question')}"
            )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _alpha_forecast_source(source_ids: Sequence[str]) -> str:
        if "open_meteo_historical_forecast" in source_ids and "open_meteo_previous_runs" not in source_ids:
            return "historical_forecast"
        return "previous_runs"


def bounded_probability(value: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.5
    if not math.isfinite(parsed):
        parsed = 0.5
    return max(0.02, min(0.98, parsed))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _best_summary_row(rows: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    if not rows:
        return {}
    return dict(max(rows, key=lambda row: float(row.get(key, 0.0) or 0.0)))


def _is_promotion_hard_blocker(blocker: str) -> bool:
    text = str(blocker or "")
    return any(text.startswith(prefix) for prefix in PROMOTION_HARD_BLOCKER_PREFIXES)


def _source_family_from_id(source_id: str) -> str:
    source = str(source_id or "").lower()
    if source.startswith("open_meteo"):
        return "open_meteo"
    if source.startswith("nws"):
        return "nws"
    if "metar" in source:
        return "metar"
    if source == "station_mapper":
        return "resolution_target"
    if source.startswith("polymarket"):
        return "polymarket"
    return source or "unknown"


def _location_from_row(row: Any) -> Optional[WeatherLocation]:
    raw_location = str(_get(row, "location", "") or "").strip()
    if not raw_location:
        return None
    lowered = raw_location.lower()
    for location in WeatherDataSignals.LOCATIONS:
        names = {location.name.lower(), *location.aliases}
        if lowered in names:
            return location
    lat = _float_or_none(_get(row, "latitude", None))
    lon = _float_or_none(_get(row, "longitude", None))
    if lat is not None and lon is not None:
        return WeatherLocation(raw_location, lat, lon, (lowered,))
    return None


def _is_us_location(location: WeatherLocation) -> bool:
    return 18.0 <= float(location.latitude) <= 72.0 and -170.0 <= float(location.longitude) <= -60.0


def _station_for_row(row: Any, kind: str) -> str:
    location = str(_get(row, "location", "") or "").strip().lower()
    aliases = [location]
    mapped_location = _location_from_row(row)
    if mapped_location is not None:
        aliases.extend([mapped_location.name.lower(), *mapped_location.aliases])
    for alias in aliases:
        station = LOCATION_STATIONS.get(alias, {}).get(kind, "")
        if station:
            return station
    explicit = str(_get(row, f"{kind}_station", "") or "").strip().upper()
    return explicit


def _row_text(row: Any) -> str:
    return " ".join(
        str(_get(row, key, "") or "")
        for key in ("question", "slug", "location", "metric")
    ).lower()


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        parsed_date = _parse_date(text)
        return datetime(parsed_date.year, parsed_date.month, parsed_date.day) if parsed_date else None


def _target_is_future_or_today(row: Any) -> bool:
    target = _parse_date(_get(row, "target_date", ""))
    return target is not None and target >= date.today()


def _target_is_today(row: Any) -> bool:
    target = _parse_date(_get(row, "target_date", ""))
    return target == date.today()


def _estimate_row_probability(row: Any, metrics: Dict[str, Any], hours_remaining: float) -> Optional[float]:
    metric = str(_get(row, "metric", ""))
    threshold = _float_or_none(_get(row, "threshold", None))
    if metric in {"precipitation", "snowfall"} and metrics.get("precipitation_probability_pct") is not None:
        return bounded_probability(float(metrics["precipitation_probability_pct"]) / 100.0)
    location = _location_from_row(row) or WeatherLocation(str(_get(row, "location", "") or ""), 0.0, 0.0, ())
    parsed = WeatherMarketParse(
        location=location,
        metric=metric,
        operator=str(_get(row, "operator", "")),
        threshold=threshold,
        upper_threshold=_float_or_none(_get(row, "upper_threshold", None)),
        threshold_unit="",
        target_date=_parse_date(_get(row, "target_date", "")),
    )
    probability = WeatherDataSignals().estimate_yes_probability(parsed, metrics, hours_remaining)
    return bounded_probability(probability) if probability is not None else None


def _summarize_nws_periods(payload: Dict[str, Any], target_date: Optional[date]) -> Dict[str, Any]:
    periods = payload.get("properties", {}).get("periods", []) if isinstance(payload, dict) else []
    selected = []
    for period in periods if isinstance(periods, list) else []:
        if not isinstance(period, dict):
            continue
        start = _parse_datetime(period.get("startTime"))
        if target_date is None or (start is not None and start.date() == target_date):
            selected.append(period)
    if not selected:
        selected = periods[:24] if isinstance(periods, list) else []
    temps = [_float_or_none(period.get("temperature")) for period in selected if isinstance(period, dict)]
    winds = [_first_number(period.get("windSpeed")) for period in selected if isinstance(period, dict)]
    pops = [
        _float_or_none((period.get("probabilityOfPrecipitation") or {}).get("value"))
        for period in selected
        if isinstance(period, dict)
    ]
    temps = [value for value in temps if value is not None]
    winds = [value for value in winds if value is not None]
    pops = [value for value in pops if value is not None]
    return {
        "hours_covered": len(selected),
        "high_temperature_f": round(max(temps), 2) if temps else None,
        "low_temperature_f": round(min(temps), 2) if temps else None,
        "max_wind_mph": round(max(winds), 2) if winds else None,
        "max_gust_mph": None,
        "precipitation_probability_pct": round(max(pops), 2) if pops else None,
    }


def _summarize_nws_gridpoint(payload: Dict[str, Any], target_date: Optional[date]) -> Dict[str, Any]:
    props = payload.get("properties", {}) if isinstance(payload, dict) else {}
    temps = _grid_values_for_date(props.get("temperature", {}), target_date, convert_temp=True)
    precip = _grid_values_for_date(props.get("quantitativePrecipitation", {}), target_date, convert_precip=True)
    wind = _grid_values_for_date(props.get("windSpeed", {}), target_date)
    gust = _grid_values_for_date(props.get("windGust", {}), target_date)
    return {
        "hours_covered": max(len(temps), len(precip), len(wind), len(gust)),
        "high_temperature_f": round(max(temps), 2) if temps else None,
        "low_temperature_f": round(min(temps), 2) if temps else None,
        "precipitation_in": round(sum(precip), 3) if precip else None,
        "max_wind_mph": round(max(wind), 2) if wind else None,
        "max_gust_mph": round(max(gust), 2) if gust else None,
    }


def _grid_values_for_date(series: Dict[str, Any], target_date: Optional[date], *, convert_temp: bool = False, convert_precip: bool = False) -> List[float]:
    values = series.get("values", []) if isinstance(series, dict) else []
    parsed: List[float] = []
    for item in values if isinstance(values, list) else []:
        if not isinstance(item, dict):
            continue
        valid_time = str(item.get("validTime") or "").split("/")[0]
        start = _parse_datetime(valid_time)
        if target_date is not None and (start is None or start.date() != target_date):
            continue
        value = _float_or_none(item.get("value"))
        if value is None:
            continue
        if convert_temp:
            value = value * 9.0 / 5.0 + 32.0
        if convert_precip:
            value = value / 25.4
        parsed.append(value)
    return parsed


def _summarize_metar(payload: Dict[str, Any]) -> Dict[str, Any]:
    temp_c = _float_or_none(payload.get("temp") or payload.get("temp_c"))
    wind_kt = _float_or_none(payload.get("wspd") or payload.get("wind_speed_kt"))
    gust_kt = _float_or_none(payload.get("wgst") or payload.get("wind_gust_kt"))
    return {
        "hours_covered": 1,
        "high_temperature_f": round(temp_c * 9.0 / 5.0 + 32.0, 2) if temp_c is not None else None,
        "low_temperature_f": round(temp_c * 9.0 / 5.0 + 32.0, 2) if temp_c is not None else None,
        "max_wind_mph": round(wind_kt * 1.15078, 2) if wind_kt is not None else None,
        "max_gust_mph": round(gust_kt * 1.15078, 2) if gust_kt is not None else None,
        "raw_weather": payload.get("wxString") or payload.get("rawOb") or "",
    }


def _first_number(value: Any) -> Optional[float]:
    text = str(value or "")
    number = ""
    for char in text:
        if char.isdigit() or char == ".":
            number += char
        elif number:
            break
    return _float_or_none(number)


def _heavy_product_manifest(source_id: str, row: Any) -> Dict[str, Any]:
    asof = _parse_datetime(_get(row, "asof_time", "")) or datetime.now()
    target = _parse_datetime(_get(row, "target_date", "")) or asof
    cycle_hour = (asof.hour // 6) * 6
    cycle = f"{cycle_hour:02d}"
    ymd = asof.strftime("%Y%m%d")
    target_ymd = target.strftime("%Y%m%d")
    forecast_hour = max(0, min(384, int(round((target - asof).total_seconds() / 3600.0))))
    forecast = f"{forecast_hour:03d}"
    base = {
        "asof_cycle": f"{ymd}{cycle}",
        "forecast_hour": forecast_hour,
        "target_date": str(_get(row, "target_date", "")),
        "parser_required": True,
    }
    if source_id == "ncep_nomads":
        base.update(
            {
                "product": "nomads_generic_grib2",
                "request_url": f"https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?dir=/gfs.{ymd}/{cycle}/atmos&file=gfs.t{cycle}z.pgrb2.0p25.f{forecast}&lev_2_m_above_ground=on&var_TMP=on&var_APCP=on&var_GUST=on",
                "parser_blocker": "unavailable_requires_grib_parser:ncep_nomads",
            }
        )
    elif source_id == "noaa_nbm":
        base.update(
            {
                "product": "nbm_core_grib2",
                "request_url": f"https://nomads.ncep.noaa.gov/cgi-bin/filter_blend.pl?dir=/blend.{ymd}/{cycle}/core&file=blend.t{cycle}z.core.f{forecast}.co.grib2&lev_2_m_above_ground=on&var_TMP=on&var_APCP=on&var_WIND=on",
                "parser_blocker": "unavailable_requires_grib_parser:noaa_nbm",
            }
        )
    elif source_id == "noaa_hrrr":
        hrrr_forecast = f"{min(forecast_hour, 48):02d}"
        base.update(
            {
                "product": "hrrr_conus_surface_grib2",
                "request_url": f"https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_2d.pl?dir=/hrrr.{ymd}/conus&file=hrrr.t{cycle}z.wrfsfcf{hrrr_forecast}.grib2&lev_2_m_above_ground=on&var_TMP=on&var_APCP=on&var_GUST=on",
                "parser_blocker": "unavailable_requires_grib_parser:noaa_hrrr",
            }
        )
    elif source_id == "noaa_rtma_urma":
        base.update(
            {
                "product": "rtma_urma_analysis_grib2",
                "rtma_url": f"https://nomads.ncep.noaa.gov/cgi-bin/filter_rtma2p5.pl?dir=/rtma2p5.{ymd}&file=rtma2p5.t{cycle}z.2dvaranl_ndfd.grb2&lev_2_m_above_ground=on&var_TMP=on&var_WIND=on",
                "urma_url": f"https://nomads.ncep.noaa.gov/cgi-bin/filter_urma2p5.pl?dir=/urma2p5.{target_ymd}&file=urma2p5.t{cycle}z.2dvaranl_ndfd.grb2&lev_2_m_above_ground=on&var_TMP=on&var_WIND=on",
                "parser_blocker": "unavailable_requires_grib_parser:noaa_rtma_urma",
            }
        )
    elif source_id == "noaa_nexrad":
        radar = _station_for_row(row, "nexrad")
        base.update(
            {
                "product": "nexrad_level2_s3",
                "radar_station": radar,
                "s3_prefix": f"https://noaa-nexrad-level2.s3.amazonaws.com/{target:%Y/%m/%d}/{radar}/" if radar else "",
                "parser_blocker": "unavailable_requires_radar_parser:noaa_nexrad",
            }
        )
    elif source_id == "noaa_stage_iv_qpe":
        base.update(
            {
                "product": "stage_iv_qpe",
                "product_url": f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/pcpanl/prod/pcpanl.{target_ymd}/",
                "parser_blocker": "unavailable_requires_qpe_parser:noaa_stage_iv_qpe",
            }
        )
    elif source_id == "ecmwf_open_data":
        base.update(
            {
                "product": "ecmwf_open_data_ifs",
                "request_url": f"https://data.ecmwf.int/forecasts/{ymd}/{cycle}z/ifs/0p25/oper/{ymd}{cycle}0000-{forecast_hour}h-oper-fc.grib2",
                "parser_blocker": "unavailable_requires_grib_parser:ecmwf_open_data",
            }
        )
    elif source_id == "dwd_icon_open_data":
        base.update(
            {
                "product": "dwd_icon_global",
                "request_url": f"https://opendata.dwd.de/weather/nwp/icon/grib/{cycle}/t_2m/icon_global_icosahedral_single-level_{ymd}{cycle}_{forecast}_T_2M.grib2.bz2",
                "parser_blocker": "unavailable_requires_grib_parser:dwd_icon_open_data",
            }
        )
    return base


def _metric_improves_by(value: Any, baseline: Any, improvement: float) -> bool:
    value_float = _float_or_none(value)
    baseline_float = _float_or_none(baseline)
    if value_float is None or baseline_float is None or baseline_float <= 0:
        return False
    return value_float <= baseline_float * (1.0 - improvement)


def _valid_record(row: WeatherEdgeLabRecord) -> bool:
    return (
        bool(row.market_id)
        and math.isfinite(float(row.market_yes_price))
        and math.isfinite(float(row.model_probability))
        and 0.0 <= row.market_yes_price <= 1.0
    )


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _float_or_none(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _mean(values: Iterable[float]) -> float:
    parsed = [float(value) for value in values if math.isfinite(float(value))]
    return sum(parsed) / len(parsed) if parsed else 0.5


def _parse_int_list(value: str) -> List[int]:
    return [int(part.strip()) for part in str(value).split(",") if part.strip()]


def _parse_float_list(value: str) -> List[float]:
    return [float(part.strip()) for part in str(value).split(",") if part.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build historical Polymarket weather edge lab artifacts")
    parser.add_argument("--max-events", type=int, default=80)
    parser.add_argument("--max-markets", type=int, default=250)
    parser.add_argument("--lead-days", type=str, default="0,1,2,3")
    parser.add_argument("--edge-gaps", type=str, default="0.04,0.08,0.12,0.20")
    parser.add_argument("--sources", type=str, default="all")
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--min-volume", type=float, default=0.0)
    parser.add_argument("--past-days", type=int, default=7)
    parser.add_argument("--paper-export", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = PolymarketCLIConfig(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
        min_volume_24h_usd=0.0,
    )
    runner = WeatherEdgeLabRunner(
        config=config,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    report = runner.run(
        max_events=args.max_events,
        max_markets=args.max_markets,
        lead_days=_parse_int_list(args.lead_days),
        edge_gaps=_parse_float_list(args.edge_gaps),
        sources=args.sources,
        min_volume=args.min_volume,
        past_days=args.past_days,
        paper_export=args.paper_export,
    )
    verdict = report.get("promotion_verdict", {})
    cprint("Weather edge lab report written", "green")
    cprint(f"  Records: {report.get('dataset', {}).get('record_count')}", "white")
    cprint(f"  Accepted paper gate: {verdict.get('accepted_for_paper_trade')}", "white")
    if verdict.get("blockers"):
        cprint(f"  Blockers: {', '.join(verdict.get('blockers', [])[:8])}", "yellow")
    cprint(f"  Output: {runner.output_dir}", "white")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
