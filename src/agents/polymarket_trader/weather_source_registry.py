"""
Live weather source normalization for the Polymarket weather lane.

This module is intentionally lightweight. Heavy feeds such as HRRR/NBM are
deferred until the station and feature-contract spine is stable, so the live
path starts with auditable Open-Meteo packets and explicit source statuses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import CLIMarket
from .station_mapper import WeatherLocation
from .weather_contracts import (
    FEATURE_SCHEMA_VERSION,
    WeatherFeaturePacket,
    WeatherForecastSnapshot,
    WeatherResolutionTarget,
    utc_now_iso,
)


class WeatherSourceRegistry:
    """Normalize live source output into a WeatherFeaturePacket."""

    LIVE_SAFE_SOURCE_IDS = {"open_meteo_forecast", "nws_api", "noaa_awc_metar"}
    DEFERRED_SOURCE_IDS = {"noaa_hrrr", "noaa_nbm", "ecmwf_open_data", "dwd_icon_open_data"}

    def build_open_meteo_packet(
        self,
        market: CLIMarket,
        parsed: Any,
        resolution: WeatherResolutionTarget,
        forecast: Dict[str, Any],
        metrics: Dict[str, Any],
        probability: Optional[float],
        confidence: float,
        edge: float,
        market_price: float,
        station_bias: Optional[Dict[str, Any]] = None,
        latency_signals: Optional[Dict[str, Any]] = None,
        run_lag_signals: Optional[Dict[str, Any]] = None,
        model_update_events: Optional[List[Dict[str, Any]]] = None,
        high_resolution_sources: Optional[List[Dict[str, Any]]] = None,
        extra_forecast_snapshots: Optional[List[WeatherForecastSnapshot]] = None,
        forecast_model_packet: Optional[Dict[str, Any]] = None,
        ai_decision: Optional[Dict[str, Any]] = None,
        market_tape_snapshot: Optional[Dict[str, Any]] = None,
        raw_forecast_metrics: Optional[Dict[str, Any]] = None,
        forecast_adjustments: Optional[Dict[str, Any]] = None,
    ) -> WeatherFeaturePacket:
        blockers: List[str] = list(resolution.blockers)
        snapshot_blockers: List[str] = []
        status = "live_safe"
        if probability is None:
            status = "unavailable"
            snapshot_blockers.append("open_meteo_probability_missing")
        if not isinstance(metrics, dict) or not metrics:
            status = "unavailable"
            snapshot_blockers.append("open_meteo_metrics_missing")

        snapshot = WeatherForecastSnapshot(
            source_id="open_meteo_forecast",
            source_family="open_meteo",
            status=status,
            generated_at=utc_now_iso(),
            asof_time=utc_now_iso(),
            run_id=self._open_meteo_run_id(forecast),
            forecast_metrics=dict(metrics or {}),
            probability=round(float(probability), 4) if probability is not None else None,
            blockers=snapshot_blockers,
            quality_flags=["live_public_forecast", "no_private_credentials"],
        )
        blockers.extend(snapshot_blockers)

        edge_reason_flags = ["calibration_edge"]
        if getattr(parsed, "target_date", None):
            edge_reason_flags.append("target_date_parsed")
        if resolution.bias_correction_f:
            edge_reason_flags.append("station_bias_correction_applied")
        bias_status = str((station_bias or {}).get("status") or "")
        if bias_status in {"validated", "manual_override", "limited_sample"}:
            edge_reason_flags.append(f"station_bias:{bias_status}")
        elif bias_status:
            edge_reason_flags.append(f"station_bias:{bias_status}")
        if high_resolution_sources:
            edge_reason_flags.append("high_resolution_manifest_ready")
        if model_update_events:
            edge_reason_flags.append("model_update_detector_active")
        run_lag_status = str((run_lag_signals or {}).get("status") or "")
        if run_lag_status in {"ready", "empty"}:
            edge_reason_flags.append(f"run_lag_ledger:{run_lag_status}")
        if latency_signals:
            edge_reason_flags.append("clob_price_latency_tracked")
        ai_status = str((ai_decision or {}).get("status") or "")
        if ai_status:
            edge_reason_flags.append(f"ai_forecast_decision:{ai_status}")
        forecast_lanes = []
        if isinstance(forecast_model_packet, dict):
            forecast_lanes = [
                str(item)
                for item in forecast_model_packet.get("strategy_lanes", []) or []
                if str(item).strip()
            ]
            edge_reason_flags.extend(f"forecast_lane:{lane}" for lane in forecast_lanes)
        quality_flags = [
            FEATURE_SCHEMA_VERSION,
            "source:open_meteo_forecast",
            *resolution.quality_flags,
            *snapshot.quality_flags,
        ]
        if bias_status:
            quality_flags.append(f"station_bias_status:{bias_status}")
        if high_resolution_sources:
            quality_flags.append("high_resolution_sources_manifested")
        if ai_status:
            quality_flags.append(f"ai_decision_status:{ai_status}")
        quality_flags.extend(f"strategy_lane:{lane}" for lane in forecast_lanes)
        forecast_snapshots = [snapshot, *list(extra_forecast_snapshots or [])]

        return WeatherFeaturePacket(
            market_id=str(getattr(market, "condition_id", "")),
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            resolution_target=resolution,
            selected_source_id="open_meteo_forecast",
            selected_source_family="open_meteo",
            forecast_snapshots=forecast_snapshots,
            model_probability=round(float(probability), 4) if probability is not None else None,
            market_probability=round(float(market_price), 4),
            edge_percent=round(float(edge) * 100.0, 2),
            confidence=round(float(confidence), 4),
            recommended_side="YES" if edge >= 0 else "NO",
            edge_reason_flags=edge_reason_flags,
            quality_flags=quality_flags,
            blockers=sorted({str(blocker) for blocker in blockers if str(blocker).strip()}),
            station_bias=dict(station_bias or {}),
            latency_signals=dict(latency_signals or {}),
            run_lag_signals=dict(run_lag_signals or {}),
            model_update_events=[dict(item) for item in model_update_events or []],
            high_resolution_sources=[dict(item) for item in high_resolution_sources or []],
            forecast_model_packet=dict(forecast_model_packet or {}),
            ai_decision=dict(ai_decision or {}),
            market_spec=self._market_spec(market, parsed, resolution),
            market_tape_snapshot=dict(market_tape_snapshot or {}),
            evidence_refs=self._evidence_refs(
                market=market,
                forecast_snapshots=forecast_snapshots,
                high_resolution_sources=high_resolution_sources or [],
                market_tape_snapshot=market_tape_snapshot or {},
            ),
            raw_forecast_metrics=dict(raw_forecast_metrics or {}),
            forecast_adjustments=dict(forecast_adjustments or {}),
        )

    def unsupported_source_snapshots(self, source_ids: List[str]) -> List[WeatherForecastSnapshot]:
        snapshots = []
        for source_id in source_ids:
            if source_id in self.DEFERRED_SOURCE_IDS:
                snapshots.append(
                    WeatherForecastSnapshot(
                        source_id=source_id,
                        source_family="deferred_heavy_weather",
                        status="unavailable",
                        generated_at=utc_now_iso(),
                        asof_time=utc_now_iso(),
                        blockers=[f"deferred_requires_parser:{source_id}"],
                    )
                )
        return snapshots

    @staticmethod
    def source_manifest(location: WeatherLocation, source_id: str) -> Dict[str, Any]:
        return {
            "source_id": source_id,
            "location": location.name,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "status": "live_safe" if source_id in WeatherSourceRegistry.LIVE_SAFE_SOURCE_IDS else "unavailable",
        }

    @staticmethod
    def _market_spec(market: CLIMarket, parsed: Any, resolution: WeatherResolutionTarget) -> Dict[str, Any]:
        return {
            "market_id": str(getattr(market, "condition_id", "") or ""),
            "question": str(getattr(market, "question", "") or ""),
            "yes_token_id": str(getattr(market, "yes_token_id", "") or ""),
            "no_token_id": str(getattr(market, "no_token_id", "") or ""),
            "market_url": str(getattr(market, "market_url", "") or ""),
            "metric": str(getattr(parsed, "metric", "") or ""),
            "operator": str(getattr(parsed, "operator", "") or ""),
            "threshold": getattr(parsed, "threshold", None),
            "upper_threshold": getattr(parsed, "upper_threshold", None),
            "threshold_unit": str(getattr(parsed, "threshold_unit", "") or ""),
            "target_date": getattr(getattr(parsed, "target_date", None), "isoformat", lambda: "")(),
            "resolution_station": resolution.resolution_station,
            "station_type": resolution.station_type,
            "status": resolution.status,
        }

    @staticmethod
    def _evidence_refs(
        *,
        market: CLIMarket,
        forecast_snapshots: List[WeatherForecastSnapshot],
        high_resolution_sources: List[Dict[str, Any]],
        market_tape_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "market_id": str(getattr(market, "condition_id", "") or ""),
            "forecast_source_ids": [snapshot.source_id for snapshot in forecast_snapshots],
            "forecast_run_ids": [snapshot.run_id for snapshot in forecast_snapshots if snapshot.run_id],
            "high_resolution_run_ids": [
                str(source.get("run_id"))
                for source in high_resolution_sources
                if str(source.get("run_id") or "").strip()
            ],
            "market_tape_captured_at": str(market_tape_snapshot.get("captured_at") or ""),
            "market_tape_book_hash": str(market_tape_snapshot.get("book_hash") or ""),
        }

    @staticmethod
    def _open_meteo_run_id(forecast: Dict[str, Any]) -> str:
        hourly = forecast.get("hourly", {}) if isinstance(forecast, dict) else {}
        times = hourly.get("time", []) if isinstance(hourly, dict) else []
        first_time = str(times[0]) if isinstance(times, list) and times else ""
        timezone = str(forecast.get("timezone", "") if isinstance(forecast, dict) else "")
        if first_time or timezone:
            return f"open_meteo:{timezone}:{first_time}"
        return f"open_meteo:{datetime.utcnow().date().isoformat()}"
