"""
Weather forecast signals for Polymarket weather markets.

The adapter only uses live public forecast data. If a market cannot be parsed
or the forecast source is unavailable, it returns an explicit unsupported/error
context instead of inventing a signal.
"""

from __future__ import annotations

import math
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from .config import ExecutionMode, PolymarketCLIConfig, get_config
from .models import CLIMarket
from .station_mapper import WeatherLocation, WeatherStationMapper
from .weather_ai_decision import WeatherAIDecisioner
from .weather_contracts import FEATURE_SCHEMA_VERSION, WeatherForecastSnapshot, utc_now_iso
from .weather_edge_features import (
    WeatherHighResolutionSourceBuilder,
    WeatherPriceLatencyTracker,
    WeatherStationBiasResolver,
)
from .weather_forecast_model_engine import WeatherForecastModelEngine
from .weather_model_update_detector import WeatherModelUpdateDetector
from .weather_source_registry import WeatherSourceRegistry


PREVIOUS_RUNS_API = "https://previous-runs-api.open-meteo.com/v1/forecast"


def _c_to_f(celsius: float) -> float:
    return (float(celsius) * 9.0 / 5.0) + 32.0


@dataclass
class WeatherMarketParse:
    location: Optional[WeatherLocation]
    metric: str
    operator: str
    threshold: Optional[float]
    upper_threshold: Optional[float]
    threshold_unit: str
    target_date: Optional[date] = None


class WeatherDataSignals:
    """Build market-specific weather forecast context for the swarm analyzer."""

    LOCATIONS: tuple[WeatherLocation, ...] = WeatherStationMapper.LOCATIONS

    METRIC_LABELS = {
        "temperature_high": "high temperature",
        "temperature_low": "low temperature",
        "precipitation": "precipitation",
        "snowfall": "snowfall",
        "wind": "wind speed",
        "wind_gust": "wind gust",
        "space_weather": "space weather",
    }

    def __init__(
        self,
        config: Optional[PolymarketCLIConfig] = None,
        session: Optional[requests.Session] = None,
    ):
        self.config = config or get_config()
        self.session = session or requests.Session()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_time: Dict[str, float] = {}
        self._previous_runs_cache: Dict[str, Dict[str, Any]] = {}
        self._geocode_cache: Dict[str, Optional[WeatherLocation]] = {}
        self._market_tape_by_id: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 10 * 60
        self.station_mapper = WeatherStationMapper()
        self.source_registry = WeatherSourceRegistry()
        self.station_bias_resolver = WeatherStationBiasResolver(
            getattr(self.config, "weather_station_bias_path", "") or None
        )
        self.high_resolution_builder = WeatherHighResolutionSourceBuilder(
            cache_dir=getattr(self.config, "weather_high_resolution_cache_dir", "") or None
        )
        self.price_latency_tracker = WeatherPriceLatencyTracker()
        self.model_update_detector = WeatherModelUpdateDetector(
            max_source_age_minutes=float(getattr(self.config, "weather_max_selected_source_age_minutes", 180.0) or 180.0)
        )
        self.forecast_model_engine = WeatherForecastModelEngine(self.estimate_yes_probability)
        self.ai_decisioner = WeatherAIDecisioner(self.config)

    def set_market_tape_snapshots(self, snapshots: Iterable[Any]) -> None:
        """Attach orderbook/depth snapshots captured earlier in the same cycle."""

        tape_by_id: Dict[str, Dict[str, Any]] = {}
        for snapshot in snapshots or []:
            payload = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot or {})
            market_id = str(payload.get("market_id") or "")
            if market_id:
                tape_by_id[market_id] = payload
        self._market_tape_by_id = tape_by_id

    def get_market_context(self, markets: Iterable[CLIMarket]) -> Dict[str, Dict[str, Any]]:
        contexts: Dict[str, Dict[str, Any]] = {}
        for market in markets:
            context = self.get_context_for_market(market)
            contexts[str(market.condition_id)] = context
        return contexts

    def get_context_for_market(self, market: CLIMarket) -> Dict[str, Any]:
        parsed = self.parse_market(market)
        base = {
            "domain": "weather",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "market_id": market.condition_id,
            "question": market.question,
            "location": parsed.location.name if parsed.location else "",
            "metric": parsed.metric,
            "operator": parsed.operator,
            "threshold": parsed.threshold,
            "upper_threshold": parsed.upper_threshold,
            "threshold_unit": parsed.threshold_unit,
            "target_date": parsed.target_date.isoformat() if parsed.target_date else "",
        }

        if parsed.metric == "space_weather":
            return {
                **base,
                "status": "unsupported_metric",
                "weather_signal": (
                    "Space-weather markets need NOAA SWPC event-count ingestion; "
                    "no surface forecast probability was produced."
                ),
            }

        if not parsed.location:
            return {
                **base,
                "status": "unparsed_location",
                "weather_signal": "No supported weather location was detected in the market text.",
            }

        resolution = self.station_mapper.resolve(
            market_id=str(getattr(market, "condition_id", "")),
            location=parsed.location,
            market_text=self._market_text(market),
        )
        if resolution.blockers:
            return {
                **base,
                "status": "unmapped_station",
                "station_mapping": resolution.to_dict(),
                "source_statuses": {"station_mapper": resolution.status},
                "quality_flags": resolution.quality_flags,
                "feature_blockers": resolution.blockers,
                "weather_signal": "Weather market location was parsed, but no auditable resolution station was mapped.",
            }

        if not parsed.metric or not parsed.operator or parsed.threshold is None:
            return {
                **base,
                "status": "unparsed_resolution_rule",
                "station_mapping": resolution.to_dict(),
                "source_statuses": {"station_mapper": resolution.status},
                "weather_signal": "Could not parse a numeric weather threshold and direction.",
            }

        try:
            forecast = self._fetch_open_meteo_forecast(parsed.location)
        except Exception as exc:
            return {
                **base,
                "status": "forecast_error",
                "weather_signal": f"Forecast fetch failed: {type(exc).__name__}: {exc}",
            }

        raw_metrics = self._summarize_forecast(forecast, market.end_date, parsed.target_date)
        station_bias = self.station_bias_resolver.snapshot(resolution)
        metrics = self.station_bias_resolver.apply_temperature_bias(raw_metrics, station_bias)
        forecast_adjustments = self._forecast_adjustments(raw_metrics, metrics)
        probability = self.estimate_yes_probability(
            parsed,
            metrics,
            market.time_remaining_hours,
        )
        if probability is None:
            return {
                **base,
                "status": "forecast_metric_missing",
                "forecast_metrics": metrics,
                "raw_forecast_metrics": raw_metrics,
                "station_bias": station_bias.to_dict(),
                "forecast_adjustments": forecast_adjustments,
                "weather_signal": "Forecast payload did not contain the parsed metric.",
            }

        market_price = max(0.0, min(1.0, float(market.yes_price or 0.0)))
        edge = probability - market_price
        value = self._metric_value(parsed.metric, metrics)
        confidence = self._confidence_from_probability(probability, market.time_remaining_hours)
        high_resolution_sources = self.high_resolution_builder.build_manifests(
            resolution=resolution,
            target_date=parsed.target_date,
            metric=parsed.metric,
            end_date=market.end_date,
            source_ids=getattr(self.config, "weather_high_resolution_sources", None),
        )
        latency_signals = self.price_latency_tracker.snapshot(market)
        model_update_events = [
            event.to_dict()
            for event in self.model_update_detector.observe_many(
                high_resolution_sources,
                price_latency=latency_signals,
            )
        ]
        run_lag_signals = self._run_lag_signals(resolution, parsed.metric)
        previous_run_snapshot = self._previous_run_snapshot(parsed, market)
        extra_snapshots = self._extra_forecast_snapshots(previous_run_snapshot)
        market_tape_snapshot = self._market_tape_by_id.get(str(getattr(market, "condition_id", "") or ""), {})
        forecast_model_packet = self.forecast_model_engine.build_packet(
            market=market,
            parsed=parsed,
            resolution=resolution,
            current_metrics=metrics,
            raw_current_metrics=raw_metrics,
            current_probability=probability,
            market_price=market_price,
            previous_run_snapshot=previous_run_snapshot,
            high_resolution_sources=high_resolution_sources,
            latency_signals=latency_signals,
            run_lag_signals=run_lag_signals,
            model_update_events=model_update_events,
            station_bias=station_bias.to_dict(),
            forecast_adjustments=forecast_adjustments,
            market_tape_snapshot=market_tape_snapshot,
        )
        should_call_weather_ai = (
            self.config.execution_mode in {ExecutionMode.DRY_RUN, ExecutionMode.PAPER}
            and str(getattr(self.config, "weather_ai_autonomy_mode", "paper_only") or "") == "paper_only"
        )
        if should_call_weather_ai:
            ai_decision = self.ai_decisioner.decide(forecast_model_packet).to_dict()
        else:
            ai_decision = self.ai_decisioner._decision(
                status="not_requested",
                p_yes=None,
                side="",
                strategy_lane="",
                confidence=0.0,
                quality_flags=["weather_ai_live_or_disabled_not_requested"],
            ).to_dict()
        summary = self._format_signal_summary(
            parsed=parsed,
            value=value,
            probability=probability,
            market_price=market_price,
            edge=edge,
            metrics=metrics,
        )
        packet = self.source_registry.build_open_meteo_packet(
            market=market,
            parsed=parsed,
            resolution=resolution,
            forecast=forecast,
            metrics=metrics,
            probability=probability,
            confidence=confidence,
            edge=edge,
            market_price=market_price,
            station_bias=station_bias.to_dict(),
            latency_signals=latency_signals,
            run_lag_signals=run_lag_signals,
            model_update_events=model_update_events,
            high_resolution_sources=high_resolution_sources,
            extra_forecast_snapshots=extra_snapshots,
            forecast_model_packet=forecast_model_packet,
            ai_decision=ai_decision,
            market_tape_snapshot=market_tape_snapshot,
            raw_forecast_metrics=raw_metrics,
            forecast_adjustments=forecast_adjustments,
        )

        return {
            **base,
            "status": "ok",
            "forecast_source": "open-meteo",
            "forecast_timezone": forecast.get("timezone", ""),
            "forecast_metrics": metrics,
            "raw_forecast_metrics": raw_metrics,
            "forecast_adjustments": forecast_adjustments,
            "weather_probability": round(probability, 4),
            "weather_confidence": round(confidence, 4),
            "weather_edge_percent": round(edge * 100.0, 2),
            "recommended_side": "YES" if edge >= 0 else "NO",
            "baseline_weather_probability": round(probability, 4),
            "forecast_model_packet": forecast_model_packet,
            "ai_decision": ai_decision,
            "market_tape_snapshot": market_tape_snapshot,
            "weather_signal": summary,
            "exchange_signal": summary,
            **packet.context_extensions(),
        }

    def _previous_run_snapshot(self, parsed: WeatherMarketParse, market: CLIMarket) -> Dict[str, Any]:
        if not bool(getattr(self.config, "weather_ai_forecast_engine_enabled", True)):
            return {"status": "disabled", "blockers": ["weather_ai_forecast_engine_disabled"]}
        if parsed.location is None or parsed.target_date is None:
            return {"status": "unavailable", "blockers": ["previous_run_target_missing"]}
        base_key = self._weather_hourly_key(parsed.metric)
        if not base_key:
            return {"status": "not_applicable", "blockers": [f"previous_run_metric_unsupported:{parsed.metric}"]}
        lead_days = int(getattr(self.config, "weather_previous_run_lead_days", 1) or 1)
        past_days = int(getattr(self.config, "weather_previous_run_past_days", 7) or 7)
        lead_key = f"{base_key}_previous_day{lead_days}"
        try:
            payload = self._fetch_previous_runs_payload(parsed.location, base_key, lead_key, past_days)
            hourly = payload.get("hourly", {}) if isinstance(payload, dict) else {}
            values = hourly.get(lead_key)
            if not isinstance(values, list):
                return {"status": "unavailable", "blockers": ["previous_run_series_missing"]}
            rewritten = {
                **payload,
                "hourly": {
                    "time": hourly.get("time", []),
                    base_key: values,
                },
            }
            metrics = self._summarize_forecast(rewritten, market.end_date, parsed.target_date)
            probability = self.estimate_yes_probability(
                parsed,
                metrics,
                max(1.0, float(lead_days) * 24.0),
            )
            if probability is None:
                return {
                    "status": "unavailable",
                    "forecast_metrics": metrics,
                    "blockers": ["previous_run_probability_missing"],
                }
            return {
                "status": "live_safe",
                "source_id": "open_meteo_previous_runs",
                "source_family": "open_meteo",
                "run_id": f"open_meteo_previous_day{lead_days}:{parsed.target_date.isoformat()}",
                "lead_days": lead_days,
                "past_days": past_days,
                "forecast_metrics": metrics,
                "probability": round(probability, 4),
                "quality_flags": ["open_meteo_previous_runs", "forecast_run_delta_input"],
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "blockers": [f"previous_run_fetch_error:{type(exc).__name__}"],
            }

    def _fetch_previous_runs_payload(
        self,
        location: WeatherLocation,
        base_key: str,
        lead_key: str,
        past_days: int,
    ) -> Dict[str, Any]:
        cache_key = f"{location.latitude:.4f},{location.longitude:.4f}:{base_key}:{lead_key}:{int(past_days)}"
        if cache_key in self._previous_runs_cache:
            return dict(self._previous_runs_cache[cache_key])
        response = self.session.get(
            PREVIOUS_RUNS_API,
            params={
                "latitude": location.latitude,
                "longitude": location.longitude,
                "hourly": f"{base_key},{lead_key}",
                "past_days": max(1, int(past_days)),
                "forecast_days": 2,
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "timezone": "auto",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("unexpected previous-runs payload")
        self._previous_runs_cache[cache_key] = dict(payload)
        return payload

    @staticmethod
    def _extra_forecast_snapshots(previous_run_snapshot: Dict[str, Any]) -> List[WeatherForecastSnapshot]:
        if not previous_run_snapshot:
            return []
        status = str(previous_run_snapshot.get("status") or "unavailable")
        if status != "live_safe":
            return []
        return [
            WeatherForecastSnapshot(
                source_id="open_meteo_previous_runs",
                source_family="open_meteo",
                status=status,
                generated_at=utc_now_iso(),
                asof_time=utc_now_iso(),
                run_id=str(previous_run_snapshot.get("run_id") or ""),
                forecast_metrics=dict(previous_run_snapshot.get("forecast_metrics", {}) or {}),
                probability=previous_run_snapshot.get("probability"),
                blockers=[str(item) for item in previous_run_snapshot.get("blockers", []) or []],
                quality_flags=[str(item) for item in previous_run_snapshot.get("quality_flags", []) or []],
            )
        ]

    @staticmethod
    def _weather_hourly_key(metric: str) -> str:
        return {
            "temperature_high": "temperature_2m",
            "temperature_low": "temperature_2m",
            "precipitation": "precipitation",
            "snowfall": "snowfall",
            "wind": "wind_speed_10m",
            "wind_gust": "wind_gusts_10m",
        }.get(str(metric or ""), "")

    def _run_lag_signals(self, resolution, metric: str) -> Dict[str, Any]:
        state_path = (
            Path(self.config.data_dir)
            / "weather_run_lag"
            / "latest_weather_run_lag_state.json"
        )
        if not state_path.exists():
            return {"status": "missing", "state_path": str(state_path)}
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "status": "unreadable",
                "state_path": str(state_path),
                "error": f"{type(exc).__name__}: {exc}",
            }
        station = str(
            getattr(resolution, "resolution_station", "")
            or getattr(resolution, "metar_station", "")
            or ""
        ).upper()
        metric_key = str(metric or "").lower()
        latest = payload.get("latest_by_key", {}) if isinstance(payload, dict) else {}
        matches = []
        if not latest:
            return {
                "status": "missing",
                "state_path": str(state_path),
                "updated_at": str(payload.get("updated_at") or "") if isinstance(payload, dict) else "",
                "station": station,
                "metric": metric_key,
                "matching_state_count": 0,
                "latest_matches": [],
                "last_event_type": "",
                "last_event_run_id": "",
            }
        if isinstance(latest, dict):
            for key, value in latest.items():
                parts = str(key).split("|")
                if len(parts) != 3:
                    continue
                if parts[1].upper() == station and parts[2].lower() == metric_key and isinstance(value, dict):
                    matches.append({"state_key": key, **value})
        last_event = payload.get("last_event", {}) if isinstance(payload, dict) else {}
        return {
            "status": "ready" if matches else "missing",
            "state_path": str(state_path),
            "updated_at": str(payload.get("updated_at") or "") if isinstance(payload, dict) else "",
            "station": station,
            "metric": metric_key,
            "matching_state_count": len(matches),
            "latest_matches": matches[:3],
            "last_event_type": str(last_event.get("event_type") or "") if isinstance(last_event, dict) else "",
            "last_event_run_id": str(last_event.get("run_id") or "") if isinstance(last_event, dict) else "",
        }

    def parse_market(self, market: CLIMarket) -> WeatherMarketParse:
        text = self._market_text(market)
        location = self._detect_location(text)
        metric = self._detect_metric(text)
        operator = self._detect_operator(text)
        threshold, unit, upper_threshold = self._extract_threshold(text, metric)
        target_date = self._detect_target_date(text, market.end_date)
        return WeatherMarketParse(
            location=location,
            metric=metric,
            operator=operator,
            threshold=threshold,
            upper_threshold=upper_threshold,
            threshold_unit=unit,
            target_date=target_date,
        )

    def _fetch_open_meteo_forecast(self, location: WeatherLocation) -> Dict[str, Any]:
        cache_key = f"{location.latitude:.4f},{location.longitude:.4f}"
        now = time.time()
        if cache_key in self._cache and (now - self._cache_time.get(cache_key, 0.0)) < self._cache_ttl:
            return dict(self._cache[cache_key])

        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "hourly": ",".join(
                [
                    "temperature_2m",
                    "precipitation",
                    "rain",
                    "snowfall",
                    "wind_speed_10m",
                    "wind_gusts_10m",
                ]
            ),
            "current": "temperature_2m,precipitation,wind_speed_10m,wind_gusts_10m",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "forecast_days": int(getattr(self.config, "weather_forecast_days", 16) or 16),
            "timezone": "auto",
        }
        response = self.session.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params,
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("unexpected forecast payload")
        self._cache[cache_key] = dict(payload)
        self._cache_time[cache_key] = now
        return payload

    def _summarize_forecast(
        self,
        forecast: Dict[str, Any],
        end_date: Optional[datetime],
        target_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        hourly = forecast.get("hourly", {}) if isinstance(forecast, dict) else {}
        times = hourly.get("time", []) if isinstance(hourly, dict) else []
        selected_indices = self._select_forecast_indices(times, end_date, target_date)

        temps = self._series_values(hourly, "temperature_2m", selected_indices)
        precip = self._series_values(hourly, "precipitation", selected_indices)
        rain = self._series_values(hourly, "rain", selected_indices)
        snow = self._series_values(hourly, "snowfall", selected_indices)
        wind = self._series_values(hourly, "wind_speed_10m", selected_indices)
        gust = self._series_values(hourly, "wind_gusts_10m", selected_indices)

        precipitation_total = sum(precip) if precip else sum(rain)
        return {
            "hours_covered": len(selected_indices),
            "high_temperature_f": round(max(temps), 2) if temps else None,
            "low_temperature_f": round(min(temps), 2) if temps else None,
            "precipitation_in": round(precipitation_total, 3) if (precip or rain) else None,
            "snowfall_in": round(sum(snow), 3) if snow else None,
            "max_wind_mph": round(max(wind), 2) if wind else None,
            "max_gust_mph": round(max(gust), 2) if gust else None,
        }

    def _select_forecast_indices(
        self,
        times: Any,
        end_date: Optional[datetime],
        target_date: Optional[date] = None,
    ) -> List[int]:
        if not isinstance(times, list) or not times:
            return []
        if target_date is not None:
            selected = []
            for idx, raw_time in enumerate(times):
                parsed = self._parse_forecast_time(raw_time)
                if parsed is not None and parsed.date() == target_date:
                    selected.append(idx)
            if selected:
                return selected
        if end_date is None:
            return list(range(len(times)))

        selected = []
        for idx, raw_time in enumerate(times):
            parsed = self._parse_forecast_time(raw_time)
            if parsed is None or parsed <= end_date:
                selected.append(idx)
        return selected or list(range(len(times)))

    @staticmethod
    def _parse_forecast_time(raw_time: Any) -> Optional[datetime]:
        if not isinstance(raw_time, str) or not raw_time:
            return None
        try:
            return datetime.fromisoformat(raw_time.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    @staticmethod
    def _series_values(hourly: Dict[str, Any], key: str, indices: List[int]) -> List[float]:
        values = hourly.get(key, []) if isinstance(hourly, dict) else []
        if not isinstance(values, list):
            return []
        parsed = []
        for idx in indices:
            if idx >= len(values):
                continue
            try:
                value = float(values[idx])
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                parsed.append(value)
        return parsed

    @staticmethod
    def _forecast_adjustments(raw_metrics: Dict[str, Any], adjusted_metrics: Dict[str, Any]) -> Dict[str, Any]:
        adjustments: Dict[str, Any] = {}
        for key in ("high_temperature_f", "low_temperature_f", "current_temperature_f"):
            raw = raw_metrics.get(key) if isinstance(raw_metrics, dict) else None
            adjusted = adjusted_metrics.get(key) if isinstance(adjusted_metrics, dict) else None
            try:
                raw_value = float(raw)
                adjusted_value = float(adjusted)
            except (TypeError, ValueError):
                continue
            delta = adjusted_value - raw_value
            if math.isfinite(delta) and abs(delta) > 0:
                adjustments[key] = {
                    "raw": round(raw_value, 4),
                    "adjusted": round(adjusted_value, 4),
                    "delta": round(delta, 4),
                }
        return adjustments

    def estimate_yes_probability(
        self,
        parsed: WeatherMarketParse,
        metrics: Dict[str, Any],
        hours_remaining: float,
    ) -> Optional[float]:
        value = self._metric_value(parsed.metric, metrics)
        if value is None or parsed.threshold is None:
            return None

        if parsed.operator == "between":
            if parsed.upper_threshold is None:
                return None
            scale = self._uncertainty_scale(parsed.metric, parsed.threshold, hours_remaining)
            lower = min(parsed.threshold, parsed.upper_threshold)
            upper = max(parsed.threshold, parsed.upper_threshold)
            return max(
                0.02,
                min(
                    0.98,
                    self._normal_cdf((upper - value) / scale)
                    - self._normal_cdf((lower - value) / scale),
                ),
            )

        margin = value - parsed.threshold
        if parsed.operator == "below":
            margin = parsed.threshold - value
        elif parsed.operator not in {"above", "below"}:
            return None

        scale = self._uncertainty_scale(parsed.metric, parsed.threshold, hours_remaining)
        probability = 1.0 / (1.0 + math.exp(-margin / max(scale, 0.01)))
        return max(0.02, min(0.98, probability))

    @staticmethod
    def _normal_cdf(z_score: float) -> float:
        return 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))

    @staticmethod
    def _metric_value(metric: str, metrics: Dict[str, Any]) -> Optional[float]:
        key_map = {
            "temperature_high": "high_temperature_f",
            "temperature_low": "low_temperature_f",
            "precipitation": "precipitation_in",
            "snowfall": "snowfall_in",
            "wind": "max_wind_mph",
            "wind_gust": "max_gust_mph",
        }
        key = key_map.get(metric)
        value = metrics.get(key) if key else None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    @staticmethod
    def _uncertainty_scale(metric: str, threshold: float, hours_remaining: float) -> float:
        horizon_multiplier = 1.0
        if hours_remaining > 120:
            horizon_multiplier = 1.8
        elif hours_remaining > 72:
            horizon_multiplier = 1.45
        elif hours_remaining > 36:
            horizon_multiplier = 1.2

        if metric in {"temperature_high", "temperature_low"}:
            return 4.0 * horizon_multiplier
        if metric in {"wind", "wind_gust"}:
            return 7.0 * horizon_multiplier
        if metric in {"precipitation", "snowfall"}:
            return max(0.05, abs(threshold) * 0.35 + 0.08) * horizon_multiplier
        return 1.0 * horizon_multiplier

    @staticmethod
    def _confidence_from_probability(probability: float, hours_remaining: float) -> float:
        confidence = 0.35 + abs(probability - 0.5) * 0.9
        if hours_remaining > 120:
            confidence *= 0.75
        elif hours_remaining > 72:
            confidence *= 0.85
        return max(0.25, min(0.9, confidence))

    def _format_signal_summary(
        self,
        parsed: WeatherMarketParse,
        value: Optional[float],
        probability: float,
        market_price: float,
        edge: float,
        metrics: Dict[str, Any],
    ) -> str:
        metric_label = self.METRIC_LABELS.get(parsed.metric, parsed.metric)
        unit = parsed.threshold_unit
        if parsed.operator == "between":
            op_label = "between"
            threshold_text = f"{parsed.threshold:g}-{parsed.upper_threshold:g}{unit}"
        else:
            op_label = ">=" if parsed.operator == "above" else "<="
            threshold_text = f"{parsed.threshold:g}{unit}"
        value_text = "n/a" if value is None else f"{value:.2f}"
        return (
            f"{parsed.location.name}: forecast {metric_label} {value_text}{unit} vs "
            f"{op_label} {threshold_text}; YES model {probability:.1%}, "
            f"market {market_price:.1%}, edge {edge:+.1%}; "
            f"hours covered {int(metrics.get('hours_covered', 0) or 0)}"
        )

    def _detect_location(self, text: str) -> Optional[WeatherLocation]:
        mapped = self.station_mapper.detect_location(text)
        if mapped:
            return mapped

        phrase = self._extract_location_phrase(text)
        if not phrase:
            return None
        return self._geocode_location(phrase)

    @staticmethod
    def _extract_location_phrase(text: str) -> str:
        lowered = text.lower()
        for pattern in (
            r"(?:highest|lowest|minimum|maximum)\s+temperature\s+in\s+([a-z][a-z .'-]+?)\s+(?:be|on)\b",
            r"(?:rain|snow|snowfall|wind|gusts?)\s+in\s+([a-z][a-z .'-]+?)\s+on\b",
            r"\bin\s+([a-z][a-z .'-]+?)\s+on\s+[a-z]+\s+\d{1,2}\b",
        ):
            match = re.search(pattern, lowered)
            if match:
                return re.sub(r"\s+", " ", match.group(1)).strip(" .'")
        return ""

    def _geocode_location(self, name: str) -> Optional[WeatherLocation]:
        cleaned = re.sub(r"\s+", " ", str(name or "")).strip()
        if len(cleaned) < 3:
            return None
        cache_key = cleaned.lower()
        if cache_key in self._geocode_cache:
            return self._geocode_cache[cache_key]

        try:
            response = self.session.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": cleaned, "count": 1, "language": "en", "format": "json"},
                timeout=8,
            )
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results", []) if isinstance(payload, dict) else []
            if not results:
                self._geocode_cache[cache_key] = None
                return None
            first = results[0]
            location = WeatherLocation(
                str(first.get("name") or cleaned),
                float(first["latitude"]),
                float(first["longitude"]),
                (cache_key,),
            )
            self._geocode_cache[cache_key] = location
            return location
        except Exception:
            self._geocode_cache[cache_key] = None
            return None

    @staticmethod
    def _detect_target_date(text: str, end_date: Optional[datetime]) -> Optional[date]:
        year = end_date.year if end_date else datetime.utcnow().year
        match = re.search(
            r"\bon\s+"
            r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
            r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
            r"nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:,\s*(\d{4}))?",
            text.lower(),
        )
        if not match:
            return end_date.date() if end_date else None
        month_lookup = {
            "jan": 1, "january": 1,
            "feb": 2, "february": 2,
            "mar": 3, "march": 3,
            "apr": 4, "april": 4,
            "may": 5,
            "jun": 6, "june": 6,
            "jul": 7, "july": 7,
            "aug": 8, "august": 8,
            "sep": 9, "sept": 9, "september": 9,
            "oct": 10, "october": 10,
            "nov": 11, "november": 11,
            "dec": 12, "december": 12,
        }
        month = month_lookup.get(match.group(1))
        day = int(match.group(2))
        parsed_year = int(match.group(3) or year)
        if not month:
            return end_date.date() if end_date else None
        try:
            return date(parsed_year, month, day)
        except ValueError:
            return end_date.date() if end_date else None

    @staticmethod
    def _detect_metric(text: str) -> str:
        lowered = text.lower()
        if "space weather" in lowered or "geomagnetic" in lowered or "radio blackout" in lowered:
            return "space_weather"
        if "snow" in lowered:
            return "snowfall"
        if "rain" in lowered or "precipitation" in lowered:
            return "precipitation"
        if "gust" in lowered:
            return "wind_gust"
        if "wind" in lowered or "mph" in lowered:
            return "wind"
        if any(token in lowered for token in ("highest temperature", "maximum temperature", "high temperature")):
            return "temperature_high"
        if any(token in lowered for token in ("lowest temperature", "minimum temperature", "low temperature")):
            return "temperature_low"
        if any(token in lowered for token in ("temperature", "degrees", "fahrenheit", "celsius", "heat")):
            return "temperature_high"
        return ""

    @staticmethod
    def _detect_operator(text: str) -> str:
        lowered = text.lower()
        if "between" in lowered:
            return "between"
        if any(token in lowered for token in ("below", "under", "less than", "lower than", "at most")):
            return "below"
        if any(token in lowered for token in ("above", "over", "at least", "exceed", "greater than", "higher than", "or higher", "hit", "reach")):
            return "above"
        if re.search(r"\bbe\s*-?\d+(?:\.\d+)?\s*(?:°\s*)?[fc]\b", lowered):
            return "between"
        if any(token in lowered for token in ("rain", "snow", "hurricane", "tropical storm")):
            return "above"
        return ""

    @staticmethod
    def _extract_threshold(text: str, metric: str) -> tuple[Optional[float], str, Optional[float]]:
        lowered = text.lower()
        if metric in {"temperature_high", "temperature_low"}:
            range_match = re.search(
                r"between\s*(-?\d+(?:\.\d+)?)\s*(?:-|and|to)\s*(-?\d+(?:\.\d+)?)\s*(?:°\s*)?([fc])?\b",
                lowered,
            )
            if range_match:
                lower = float(range_match.group(1))
                upper = float(range_match.group(2))
                unit = (range_match.group(3) or "f").lower()
                if unit == "c":
                    lower = _c_to_f(lower)
                    upper = _c_to_f(upper)
                return lower, "F", upper

            exact_match = re.search(r"\bbe\s*(-?\d+(?:\.\d+)?)\s*(?:°\s*)?([fc])\b", lowered)
            if exact_match:
                value = float(exact_match.group(1))
                unit = exact_match.group(2).lower()
                if unit == "c":
                    value_f = _c_to_f(value)
                else:
                    value_f = value
                if any(token in lowered for token in ("below", "under", "less than", "lower than", "at most", "above", "over", "at least", "greater than", "higher than", "or higher")):
                    return value_f, "F", None
                if unit == "c":
                    lower = _c_to_f(value - 0.5)
                    upper = _c_to_f(value + 0.5)
                else:
                    lower = value - 0.5
                    upper = value + 0.5
                return lower, "F", upper

            for pattern in (
                r"(-?\d+(?:\.\d+)?)\s*(?:°\s*)?([fc])\b",
                r"(-?\d+(?:\.\d+)?)\s*(degrees?|deg)\b",
                r"(?:above|over|under|below|at least|at most|exceed|reach|hit)\s*(-?\d+(?:\.\d+)?)\s*(?:°\s*)?([fc])?",
            ):
                match = re.search(pattern, lowered)
                if match:
                    value = float(match.group(1))
                    unit_group = match.group(2) if len(match.groups()) >= 2 else None
                    unit = str(unit_group or "f").lower()
                    if unit.startswith("c"):
                        value = _c_to_f(value)
                    return value, "F", None
            return None, "F", None

        if metric in {"precipitation", "snowfall"}:
            match = re.search(r"(\d+(?:\.\d+)?)\s*(?:inches|inch|in\b|\")", lowered)
            if match:
                return float(match.group(1)), "in", None
            if any(token in lowered for token in ("rain", "snow", "precipitation")):
                return 0.01, "in", None
            return None, "in", None

        if metric in {"wind", "wind_gust"}:
            match = re.search(r"(\d+(?:\.\d+)?)\s*(?:mph|miles per hour)", lowered)
            if match:
                return float(match.group(1)), "mph", None
            return None, "mph", None

        return None, "", None

    @staticmethod
    def _market_text(market: CLIMarket) -> str:
        return " ".join(
            part
            for part in (
                getattr(market, "question", ""),
                getattr(market, "description", ""),
                getattr(market, "slug", ""),
                getattr(market, "event_slug", ""),
            )
            if part
        ).lower()
