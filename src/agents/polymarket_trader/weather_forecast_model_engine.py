"""
Forecast-model intelligence packet for Polymarket weather markets.

This layer turns weather inputs into a trading-desk packet: what changed,
which source disagrees, whether the market looks stale, and which strategy lane
is being tested. It does not execute trades.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, Iterable, List, Optional

from .models import CLIMarket
from .weather_contracts import FORECAST_ENGINE_SCHEMA_VERSION, utc_now_iso


ProbabilityEstimator = Callable[[Any, Dict[str, Any], float], Optional[float]]


class WeatherForecastModelEngine:
    """Build an auditable packet for the AI weather portfolio manager."""

    def __init__(self, probability_estimator: ProbabilityEstimator):
        self.probability_estimator = probability_estimator

    def build_packet(
        self,
        *,
        market: CLIMarket,
        parsed: Any,
        resolution: Any,
        current_metrics: Dict[str, Any],
        raw_current_metrics: Dict[str, Any],
        current_probability: Optional[float],
        market_price: float,
        previous_run_snapshot: Optional[Dict[str, Any]] = None,
        high_resolution_sources: Optional[List[Dict[str, Any]]] = None,
        latency_signals: Optional[Dict[str, Any]] = None,
        run_lag_signals: Optional[Dict[str, Any]] = None,
        model_update_events: Optional[List[Dict[str, Any]]] = None,
        station_bias: Optional[Dict[str, Any]] = None,
        forecast_adjustments: Optional[Dict[str, Any]] = None,
        market_tape_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        source_rows = self._source_rows(
            parsed=parsed,
            market=market,
            current_metrics=current_metrics,
            current_probability=current_probability,
            previous_run_snapshot=previous_run_snapshot,
            high_resolution_sources=high_resolution_sources or [],
        )
        probabilities = [
            float(row["p_yes"])
            for row in source_rows
            if self._safe_float(row.get("p_yes")) is not None
        ]
        source_probabilities = {
            str(row.get("source_id")): round(float(row["p_yes"]), 4)
            for row in source_rows
            if self._safe_float(row.get("p_yes")) is not None
        }
        forecast_deltas = self._forecast_deltas(
            current_metrics=current_metrics,
            raw_current_metrics=raw_current_metrics,
            previous_run_snapshot=previous_run_snapshot,
            high_resolution_sources=high_resolution_sources or [],
            run_lag_signals=run_lag_signals or {},
        )
        margin = self._threshold_margin(parsed, current_metrics)
        source_spread = (max(probabilities) - min(probabilities)) if len(probabilities) >= 2 else None
        market_staleness = self._market_staleness(
            latency_signals=latency_signals or {},
            model_update_events=model_update_events or [],
            run_lag_signals=run_lag_signals or {},
        )
        lanes = self._strategy_lanes(
            parsed=parsed,
            margin=margin,
            forecast_deltas=forecast_deltas,
            source_spread=source_spread,
            market_staleness=market_staleness,
            station_bias=station_bias or {},
            market=market,
        )
        execution = self._execution_context(market, market_tape_snapshot or {})
        data_quality = self._data_quality(
            source_rows=source_rows,
            source_spread=source_spread,
            market_staleness=market_staleness,
            execution=execution,
        )

        return {
            "schema_version": FORECAST_ENGINE_SCHEMA_VERSION,
            "generated_at": utc_now_iso(),
            "market_id": str(getattr(market, "condition_id", "") or ""),
            "question": str(getattr(market, "question", "") or ""),
            "market": {
                "yes_price": self._round_probability(getattr(market, "yes_price", None)),
                "no_price": self._round_probability(getattr(market, "no_price", None)),
                "market_price": round(float(market_price), 4),
                "spread": self._safe_float(getattr(market, "spread", None)),
                "liquidity": self._safe_float(getattr(market, "liquidity", None)),
                "volume_24h": self._safe_float(getattr(market, "volume_24h", None)),
                "time_remaining_hours": round(float(getattr(market, "time_remaining_hours", 0.0) or 0.0), 4),
            },
            "resolution": {
                "location": str(getattr(parsed.location, "name", "") if getattr(parsed, "location", None) else ""),
                "station": str(getattr(resolution, "resolution_station", "") or ""),
                "metric": str(getattr(parsed, "metric", "") or ""),
                "operator": str(getattr(parsed, "operator", "") or ""),
                "threshold": self._safe_float(getattr(parsed, "threshold", None)),
                "upper_threshold": self._safe_float(getattr(parsed, "upper_threshold", None)),
                "target_date": getattr(parsed, "target_date", None).isoformat()
                if getattr(parsed, "target_date", None)
                else "",
                "threshold_margin": margin,
            },
            "source_rows": source_rows,
            "source_probabilities": source_probabilities,
            "model_disagreement": {
                "source_count": len(probabilities),
                "probability_range": round(source_spread, 4) if source_spread is not None else None,
                "max_probability": round(max(probabilities), 4) if probabilities else None,
                "min_probability": round(min(probabilities), 4) if probabilities else None,
            },
            "forecast_deltas": forecast_deltas,
            "station_specific_adjustments": {
                "station_bias": dict(station_bias or {}),
                "forecast_adjustments": dict(forecast_adjustments or {}),
            },
            "market_staleness": market_staleness,
            "execution_context": execution,
            "strategy_lanes": lanes,
            "data_quality": data_quality,
            "blockers": self._packet_blockers(source_rows, execution),
            "quality_flags": self._quality_flags(lanes, data_quality, execution),
        }

    def _source_rows(
        self,
        *,
        parsed: Any,
        market: CLIMarket,
        current_metrics: Dict[str, Any],
        current_probability: Optional[float],
        previous_run_snapshot: Optional[Dict[str, Any]],
        high_resolution_sources: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = [
            {
                "source_id": "open_meteo_forecast",
                "source_family": "open_meteo",
                "status": "live_safe",
                "p_yes": self._round_probability(current_probability),
                "forecast_metrics": dict(current_metrics or {}),
                "role": "current_baseline",
            }
        ]
        if previous_run_snapshot:
            rows.append(
                {
                    "source_id": "open_meteo_previous_runs",
                    "source_family": "open_meteo",
                    "status": str(previous_run_snapshot.get("status") or "unavailable"),
                    "p_yes": self._round_probability(previous_run_snapshot.get("probability")),
                    "forecast_metrics": dict(previous_run_snapshot.get("forecast_metrics", {}) or {}),
                    "role": "previous_model_run",
                    "lead_days": previous_run_snapshot.get("lead_days"),
                    "run_id": previous_run_snapshot.get("run_id", ""),
                    "blockers": list(previous_run_snapshot.get("blockers", []) or []),
                }
            )
        for manifest in high_resolution_sources:
            metrics = self._high_res_metrics(manifest)
            if not metrics:
                continue
            p_yes = self.probability_estimator(
                parsed,
                metrics,
                max(0.0, float(getattr(market, "time_remaining_hours", 0.0) or 0.0)),
            )
            rows.append(
                {
                    "source_id": str(manifest.get("source_id") or ""),
                    "source_family": str(manifest.get("source_family") or "noaa_high_resolution"),
                    "status": str(manifest.get("status") or ""),
                    "p_yes": self._round_probability(p_yes),
                    "forecast_metrics": metrics,
                    "role": "high_resolution_model",
                    "run_id": str(manifest.get("run_id") or ""),
                    "forecast_hour": manifest.get("forecast_hour"),
                    "source_age_minutes": self._safe_float(manifest.get("source_age_minutes")),
                    "blockers": list(manifest.get("blockers", []) or []),
                }
            )
        return rows

    def _forecast_deltas(
        self,
        *,
        current_metrics: Dict[str, Any],
        raw_current_metrics: Dict[str, Any],
        previous_run_snapshot: Optional[Dict[str, Any]],
        high_resolution_sources: List[Dict[str, Any]],
        run_lag_signals: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        deltas: List[Dict[str, Any]] = []
        if previous_run_snapshot and previous_run_snapshot.get("forecast_metrics"):
            deltas.append(
                {
                    "source_id": "open_meteo_previous_runs",
                    "delta_type": "current_vs_previous_run",
                    "deltas": self._numeric_deltas(
                        current_metrics,
                        dict(previous_run_snapshot.get("forecast_metrics") or {}),
                    ),
                }
            )
        if raw_current_metrics and current_metrics:
            station_bias_delta = self._numeric_deltas(current_metrics, raw_current_metrics)
            if station_bias_delta:
                deltas.append(
                    {
                        "source_id": "station_bias_adjustment",
                        "delta_type": "adjusted_vs_raw_forecast",
                        "deltas": station_bias_delta,
                    }
                )
        for manifest in high_resolution_sources:
            metrics = self._high_res_metrics(manifest)
            if not metrics:
                continue
            deltas.append(
                {
                    "source_id": str(manifest.get("source_id") or ""),
                    "delta_type": "high_resolution_vs_open_meteo",
                    "run_id": str(manifest.get("run_id") or ""),
                    "deltas": self._numeric_deltas(metrics, current_metrics),
                }
            )
        for match in run_lag_signals.get("latest_matches", []) or []:
            if not isinstance(match, dict):
                continue
            forecast_delta = match.get("forecast_delta")
            if isinstance(forecast_delta, dict) and forecast_delta:
                deltas.append(
                    {
                        "source_id": str(match.get("source_id") or match.get("run_id") or "run_lag_ledger"),
                        "delta_type": "ledger_new_run_delta",
                        "run_id": str(match.get("run_id") or ""),
                        "deltas": forecast_delta,
                    }
                )
        return [delta for delta in deltas if delta.get("deltas")]

    def _market_staleness(
        self,
        *,
        latency_signals: Dict[str, Any],
        model_update_events: List[Dict[str, Any]],
        run_lag_signals: Dict[str, Any],
    ) -> Dict[str, Any]:
        actionable_updates = [
            event
            for event in model_update_events
            if isinstance(event, dict) and bool(event.get("actionable_for_research"))
        ]
        price_move = self._safe_float(latency_signals.get("yes_price_change_points"))
        if price_move is None:
            price_move = self._safe_float(latency_signals.get("no_price_change_points"))
        status = "unknown"
        if actionable_updates:
            status = "fresh_model_run_market_not_repriced"
        elif str(run_lag_signals.get("last_event_type") or "") in {"new_run_arrival", "run_changed"}:
            status = "model_run_change_seen"
        elif price_move is not None:
            status = "price_move_seen" if abs(price_move) >= 2.0 else "price_still_quiet"
        return {
            "status": status,
            "actionable_update_count": len(actionable_updates),
            "latency_status": str(latency_signals.get("status") or ""),
            "yes_price_change_points": self._safe_float(latency_signals.get("yes_price_change_points")),
            "no_price_change_points": self._safe_float(latency_signals.get("no_price_change_points")),
            "run_lag_status": str(run_lag_signals.get("status") or ""),
            "last_run_lag_event_type": str(run_lag_signals.get("last_event_type") or ""),
        }

    def _strategy_lanes(
        self,
        *,
        parsed: Any,
        margin: Optional[float],
        forecast_deltas: List[Dict[str, Any]],
        source_spread: Optional[float],
        market_staleness: Dict[str, Any],
        station_bias: Dict[str, Any],
        market: CLIMarket,
    ) -> List[str]:
        lanes: List[str] = []
        if self._max_abs_delta(forecast_deltas) >= self._shock_threshold(str(getattr(parsed, "metric", "") or "")):
            lanes.append("forecast_run_shock")
        if market_staleness.get("status") in {"fresh_model_run_market_not_repriced", "model_run_change_seen"}:
            lanes.append("stale_after_model_update")
        if str(station_bias.get("status") or "") in {"validated", "manual_override", "limited_sample"}:
            lanes.append("station_specific_edge")
        if source_spread is not None and source_spread >= 0.15:
            lanes.append("model_disagreement")
        if margin is not None and abs(margin) <= self._boundary_threshold(str(getattr(parsed, "metric", "") or "")):
            lanes.append("uncertainty_pricing")
        if float(getattr(market, "time_remaining_hours", 999.0) or 999.0) <= 24.0:
            lanes.append("nowcast_override")
        if not lanes:
            lanes.append("forecast_model_baseline")
        return lanes

    def _execution_context(self, market: CLIMarket, market_tape_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        if market_tape_snapshot:
            side_depth = {
                "yes_ask_depth_usd": self._nested_float(market_tape_snapshot, "yes_book", "ask_depth_usd"),
                "no_ask_depth_usd": self._nested_float(market_tape_snapshot, "no_book", "ask_depth_usd"),
            }
            return {
                "status": "market_tape_attached",
                "executable_yes_price": self._safe_float(market_tape_snapshot.get("executable_yes_price")),
                "executable_no_price": self._safe_float(market_tape_snapshot.get("executable_no_price")),
                "executable_price_source": str(market_tape_snapshot.get("executable_price_source") or ""),
                "spread": self._safe_float(market_tape_snapshot.get("spread")),
                **side_depth,
                "blockers": list(market_tape_snapshot.get("blockers", []) or []),
            }
        return {
            "status": "orderbook_depth_not_attached_to_signal_packet",
            "yes_price": self._safe_float(getattr(market, "yes_price", None)),
            "no_price": self._safe_float(getattr(market, "no_price", None)),
            "spread": self._safe_float(getattr(market, "spread", None)),
            "liquidity": self._safe_float(getattr(market, "liquidity", None)),
            "blockers": ["orderbook_depth_missing_from_forecast_packet"],
        }

    @staticmethod
    def _data_quality(
        source_rows: List[Dict[str, Any]],
        source_spread: Optional[float],
        market_staleness: Dict[str, Any],
        execution: Dict[str, Any],
    ) -> str:
        usable_sources = len(
            [
                row
                for row in source_rows
                if row.get("status") in {"live_safe", "ok"} and row.get("p_yes") is not None
            ]
        )
        if usable_sources >= 3 and execution.get("status") == "market_tape_attached":
            return "high"
        if usable_sources >= 2 or market_staleness.get("actionable_update_count", 0):
            return "medium"
        if usable_sources >= 1:
            return "limited"
        return "poor"

    @staticmethod
    def _packet_blockers(source_rows: List[Dict[str, Any]], execution: Dict[str, Any]) -> List[str]:
        blockers: List[str] = []
        if not any(row.get("p_yes") is not None for row in source_rows):
            blockers.append("forecast_model_probability_missing")
        blockers.extend(str(item) for item in execution.get("blockers", []) or [])
        return sorted(set(blockers))

    @staticmethod
    def _quality_flags(lanes: List[str], data_quality: str, execution: Dict[str, Any]) -> List[str]:
        flags = ["forecast_model_engine", f"forecast_data_quality:{data_quality}"]
        flags.extend(f"strategy_lane:{lane}" for lane in lanes)
        if execution.get("status") == "market_tape_attached":
            flags.append("orderbook_context_attached")
        return sorted(set(flags))

    @staticmethod
    def _high_res_metrics(manifest: Dict[str, Any]) -> Dict[str, Any]:
        metrics = manifest.get("forecast_metrics")
        if isinstance(metrics, dict) and metrics:
            return dict(metrics)
        parsed = manifest.get("parsed_snapshot")
        if isinstance(parsed, dict) and isinstance(parsed.get("forecast_metrics"), dict):
            return dict(parsed.get("forecast_metrics") or {})
        return {}

    @staticmethod
    def _numeric_deltas(current: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
        deltas: Dict[str, Dict[str, float]] = {}
        for key in sorted(set(current.keys()) | set(previous.keys())):
            cur = WeatherForecastModelEngine._safe_float(current.get(key))
            prev = WeatherForecastModelEngine._safe_float(previous.get(key))
            if cur is None or prev is None:
                continue
            delta = cur - prev
            if math.isfinite(delta) and abs(delta) > 0:
                deltas[key] = {
                    "current": round(cur, 4),
                    "previous": round(prev, 4),
                    "delta": round(delta, 4),
                }
        return deltas

    @staticmethod
    def _threshold_margin(parsed: Any, metrics: Dict[str, Any]) -> Optional[float]:
        key_map = {
            "temperature_high": "high_temperature_f",
            "temperature_low": "low_temperature_f",
            "precipitation": "precipitation_in",
            "snowfall": "snowfall_in",
            "wind": "max_wind_mph",
            "wind_gust": "max_gust_mph",
        }
        key = key_map.get(str(getattr(parsed, "metric", "") or ""))
        value = WeatherForecastModelEngine._safe_float(metrics.get(key)) if key else None
        threshold = WeatherForecastModelEngine._safe_float(getattr(parsed, "threshold", None))
        if value is None or threshold is None:
            return None
        margin = value - threshold
        if str(getattr(parsed, "operator", "") or "") == "below":
            margin = threshold - value
        return round(margin, 4)

    @staticmethod
    def _max_abs_delta(forecast_deltas: Iterable[Dict[str, Any]]) -> float:
        values: List[float] = []
        for row in forecast_deltas:
            deltas = row.get("deltas", {}) if isinstance(row, dict) else {}
            if not isinstance(deltas, dict):
                continue
            for item in deltas.values():
                if isinstance(item, dict):
                    value = WeatherForecastModelEngine._safe_float(item.get("delta"))
                    if value is not None:
                        values.append(abs(value))
        return max(values) if values else 0.0

    @staticmethod
    def _shock_threshold(metric: str) -> float:
        if metric in {"temperature_high", "temperature_low"}:
            return 2.0
        if metric in {"wind", "wind_gust"}:
            return 5.0
        if metric in {"precipitation", "snowfall"}:
            return 0.05
        return 1.0

    @staticmethod
    def _boundary_threshold(metric: str) -> float:
        if metric in {"temperature_high", "temperature_low"}:
            return 2.5
        if metric in {"wind", "wind_gust"}:
            return 4.0
        if metric in {"precipitation", "snowfall"}:
            return 0.05
        return 1.0

    @staticmethod
    def _nested_float(payload: Dict[str, Any], container: str, key: str) -> Optional[float]:
        value = payload.get(container)
        if not isinstance(value, dict):
            return None
        return WeatherForecastModelEngine._safe_float(value.get(key))

    @staticmethod
    def _round_probability(value: Any) -> Optional[float]:
        parsed = WeatherForecastModelEngine._safe_float(value)
        if parsed is None:
            return None
        return round(max(0.0, min(1.0, parsed)), 4)

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None
