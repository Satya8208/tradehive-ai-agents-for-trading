"""
Durable run-lag ledger for high-resolution weather model updates.

The weather latency edge depends on knowing exactly when a model run first
arrived, what changed versus the prior run for the same station/source/metric,
and whether Polymarket prices moved before the research loop could react.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from .weather_contracts import utc_now_iso


RUN_LAG_LEDGER_SCHEMA_VERSION = "weather_run_lag_ledger_v1"


class WeatherRunLagLedger:
    """Append model-run observations and keep latest state by source/station/metric."""

    def __init__(
        self,
        ledger_dir: str | Path | None = None,
        *,
        event_log_path: str | Path | None = None,
        latest_state_path: str | Path | None = None,
        repriced_move_threshold_points: float = 2.0,
    ):
        root = Path(ledger_dir).expanduser() if ledger_dir is not None else _default_ledger_dir()
        self.ledger_dir = root.resolve()
        self.event_log_path = (
            Path(event_log_path).expanduser().resolve()
            if event_log_path is not None
            else self.ledger_dir / "weather_run_lag_events.jsonl"
        )
        self.latest_state_path = (
            Path(latest_state_path).expanduser().resolve()
            if latest_state_path is not None
            else self.ledger_dir / "latest_weather_run_lag_state.json"
        )
        self.repriced_move_threshold_points = float(repriced_move_threshold_points)
        self._state = self._load_state()

    def observe(
        self,
        manifest: Mapping[str, Any],
        *,
        station: Any = None,
        metric: Any = None,
        clob_snapshot: Optional[Mapping[str, Any]] = None,
        observed_at: Any = None,
    ) -> Dict[str, Any]:
        """Record one high-resolution run manifest and return a research-ready event."""

        observed_iso = _coerce_observed_at(observed_at)
        normalized = _normalize_manifest(manifest, station=station, metric=metric)
        blockers = _required_blockers(normalized)
        state_key = _state_key(normalized)
        prior = self._state.get("latest_by_key", {}).get(state_key, {}) if state_key else {}
        prior_run_id = str(prior.get("run_id") or "")

        if blockers:
            event_type = "invalid_manifest"
            status = "fail_closed"
        elif not prior_run_id:
            event_type = "first_seen"
            status = "recorded"
        elif prior_run_id != normalized["run_id"]:
            event_type = "new_run_arrival"
            status = "recorded"
        else:
            event_type = "same_run"
            status = "recorded"

        forecast_metrics = dict(normalized.get("forecast_metrics") or {})
        forecast_delta = _forecast_delta(forecast_metrics, prior.get("forecast_metrics", {}))
        run_lag_minutes = _run_lag_minutes(normalized.get("cycle_time"), observed_iso)
        source_age_minutes = _safe_float(normalized.get("source_age_minutes"))
        if source_age_minutes is None:
            source_age_minutes = run_lag_minutes

        price_movement = _price_movement(
            clob_snapshot,
            prior.get("clob_snapshot", {}),
            threshold_points=self.repriced_move_threshold_points,
        )

        event = {
            "schema_version": RUN_LAG_LEDGER_SCHEMA_VERSION,
            "event_type": event_type,
            "status": status,
            "observed_at": observed_iso,
            "state_key": state_key,
            "source_id": normalized.get("source_id", ""),
            "station": normalized.get("station", ""),
            "metric": normalized.get("metric", ""),
            "run_id": normalized.get("run_id", ""),
            "previous_run_id": prior_run_id,
            "cycle_time": normalized.get("cycle_time", ""),
            "target_reference_time": normalized.get("target_reference_time", ""),
            "forecast_hour": normalized.get("forecast_hour"),
            "source_age_minutes": _round_optional(source_age_minutes),
            "run_lag_minutes": _round_optional(run_lag_minutes),
            "forecast_metrics": forecast_metrics,
            "forecast_delta": forecast_delta,
            "numeric_forecast_delta_count": len(forecast_delta),
            "max_abs_forecast_delta": _max_abs_delta(forecast_delta),
            "clob_price_snapshot": price_movement["snapshot"],
            "previous_clob_price_snapshot": price_movement["previous_snapshot"],
            "price_movement": price_movement["movement"],
            "price_move_points": price_movement["movement"].get("max_price_move_points"),
            "market_repriced": price_movement["movement"].get("market_repriced", False),
            "run_manifest": normalized["run_manifest"],
            "model_update_detector_input": _model_update_detector_input(
                normalized,
                source_age_minutes=source_age_minutes,
            ),
            "price_latency_for_detector": _price_latency_for_detector(price_movement["movement"]),
            "actionable_for_research": (
                event_type == "new_run_arrival"
                and not blockers
                and not price_movement["movement"].get("market_repriced", False)
            ),
            "blockers": blockers,
            "quality_flags": _quality_flags(event_type, blockers, price_movement["movement"]),
        }

        if blockers:
            self._state["last_fail_closed_event"] = _compact_event(event)
        else:
            self._state.setdefault("latest_by_key", {})[state_key] = _latest_entry(
                normalized,
                event,
                price_movement["snapshot"],
            )
            self._state["last_event"] = _compact_event(event)
        self._state["updated_at"] = observed_iso
        self._state["schema_version"] = RUN_LAG_LEDGER_SCHEMA_VERSION
        self._state["event_log_path"] = str(self.event_log_path)
        self._append_event(event)
        self._write_state()
        return event

    def observe_many(
        self,
        manifests: Iterable[Mapping[str, Any]],
        *,
        clob_snapshots_by_key: Optional[Mapping[str, Mapping[str, Any]]] = None,
        observed_at: Any = None,
    ) -> list[Dict[str, Any]]:
        events = []
        snapshots = clob_snapshots_by_key or {}
        for manifest in manifests:
            normalized = _normalize_manifest(manifest)
            key = _state_key(normalized)
            events.append(
                self.observe(
                    manifest,
                    clob_snapshot=snapshots.get(key) or snapshots.get(str(normalized.get("run_id") or "")),
                    observed_at=observed_at,
                )
            )
        return events

    def latest_state(self) -> Dict[str, Any]:
        return dict(self._state)

    def _load_state(self) -> Dict[str, Any]:
        if not self.latest_state_path.exists():
            return {
                "schema_version": RUN_LAG_LEDGER_SCHEMA_VERSION,
                "updated_at": "",
                "event_log_path": str(self.event_log_path),
                "latest_by_key": {},
            }
        payload = json.loads(self.latest_state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("weather_run_lag_state_must_be_object")
        payload.setdefault("schema_version", RUN_LAG_LEDGER_SCHEMA_VERSION)
        payload.setdefault("latest_by_key", {})
        payload.setdefault("event_log_path", str(self.event_log_path))
        return payload

    def _append_event(self, event: Dict[str, Any]) -> None:
        self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.event_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_jsonable(event), sort_keys=True) + "\n")

    def _write_state(self) -> None:
        self.latest_state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.latest_state_path.with_suffix(self.latest_state_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(_jsonable(self._state), indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.latest_state_path)


def _default_ledger_dir() -> Path:
    from .config import get_polymarket_cli_config

    return get_polymarket_cli_config(market_vertical="weather").data_dir / "weather_run_lag"


def _normalize_manifest(
    manifest: Mapping[str, Any],
    *,
    station: Any = None,
    metric: Any = None,
) -> Dict[str, Any]:
    payload = dict(manifest or {})
    forecast_metrics = payload.get("forecast_metrics")
    if not isinstance(forecast_metrics, Mapping):
        forecast_metrics = {}

    source_id = _first_text(payload, "source_id", "selected_source_id", "source", "provider", "model_source")
    run_id = _first_text(payload, "run_id", "model_run_id", "run")
    station_id = _clean_text(
        station
        or payload.get("station")
        or payload.get("station_id")
        or payload.get("resolution_station")
        or payload.get("metar_station")
        or _nested_station(payload.get("resolution_target"))
        or _nested_station(payload.get("station_mapping"))
    )
    metric_id = _clean_text(metric or payload.get("metric") or payload.get("forecast_metric"))

    run_manifest = _jsonable(payload)
    run_manifest["source_id"] = source_id
    run_manifest["run_id"] = run_id
    run_manifest["station"] = station_id
    run_manifest["metric"] = metric_id
    run_manifest["forecast_metrics"] = _jsonable(dict(forecast_metrics))

    return {
        "source_id": source_id,
        "run_id": run_id,
        "station": station_id,
        "metric": metric_id,
        "source_family": _first_text(payload, "source_family"),
        "cycle_time": _first_text(payload, "cycle_time", "run_time", "model_cycle_time"),
        "target_reference_time": _first_text(payload, "target_reference_time", "valid_time", "asof_time"),
        "forecast_hour": _safe_int(payload.get("forecast_hour")),
        "source_age_minutes": payload.get("source_age_minutes"),
        "status": _first_text(payload, "status"),
        "forecast_metrics": _jsonable(dict(forecast_metrics)),
        "run_manifest": run_manifest,
    }


def _required_blockers(normalized: Mapping[str, Any]) -> list[str]:
    blockers = []
    if not normalized.get("source_id"):
        blockers.append("source_id_missing")
    if not normalized.get("run_id"):
        blockers.append("run_id_missing")
    if not normalized.get("station"):
        blockers.append("station_missing")
    if not normalized.get("metric"):
        blockers.append("metric_missing")
    return blockers


def _nested_station(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    return _clean_text(value.get("resolution_station") or value.get("station_id") or value.get("station"))


def _state_key(normalized: Mapping[str, Any]) -> str:
    parts = [
        _clean_text(normalized.get("source_id")).lower(),
        _clean_text(normalized.get("station")).upper(),
        _clean_text(normalized.get("metric")).lower(),
    ]
    if not all(parts):
        return ""
    return "|".join(parts)


def _forecast_delta(current: Mapping[str, Any], previous: Any) -> Dict[str, Dict[str, float]]:
    if not isinstance(previous, Mapping):
        previous = {}
    deltas: Dict[str, Dict[str, float]] = {}
    keys = sorted(set(current.keys()) | set(previous.keys()))
    for key in keys:
        now = _safe_float(current.get(key))
        prior = _safe_float(previous.get(key))
        if now is None or prior is None:
            continue
        deltas[str(key)] = {
            "previous": round(prior, 4),
            "current": round(now, 4),
            "delta": round(now - prior, 4),
        }
    return deltas


def _price_movement(
    snapshot: Optional[Mapping[str, Any]],
    previous_snapshot: Any,
    *,
    threshold_points: float,
) -> Dict[str, Any]:
    current = _normalize_price_snapshot(snapshot)
    previous = _normalize_price_snapshot(previous_snapshot if isinstance(previous_snapshot, Mapping) else None)
    yes_change = _explicit_or_computed_price_change(current, previous, "yes")
    no_change = _explicit_or_computed_price_change(current, previous, "no")
    moves = [abs(item) for item in (yes_change, no_change) if item is not None]
    max_move = round(max(moves), 4) if moves else None
    movement = {
        "yes_price_change_points": _round_optional(yes_change),
        "no_price_change_points": _round_optional(no_change),
        "max_price_move_points": max_move,
        "market_repriced": bool(max_move is not None and max_move >= threshold_points),
    }
    return {
        "snapshot": current,
        "previous_snapshot": previous,
        "movement": movement,
    }


def _normalize_price_snapshot(snapshot: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not snapshot:
        return {}
    normalized = _jsonable(dict(snapshot))
    yes_price = _first_float(snapshot, "yes_price", "yes", "yes_mid_price", "best_yes_price")
    no_price = _first_float(snapshot, "no_price", "no", "no_mid_price", "best_no_price")
    if yes_price is not None:
        normalized["yes_price"] = round(yes_price, 4)
    if no_price is not None:
        normalized["no_price"] = round(no_price, 4)
    return normalized


def _explicit_or_computed_price_change(
    current: Mapping[str, Any],
    previous: Mapping[str, Any],
    side: str,
) -> Optional[float]:
    explicit = _first_float(
        current,
        f"{side}_price_change_points",
        f"{side}_change_points",
        f"{side}_delta_points",
    )
    if explicit is not None:
        return explicit
    now = _safe_float(current.get(f"{side}_price"))
    prior = _safe_float(previous.get(f"{side}_price"))
    if now is None or prior is None:
        return None
    multiplier = 100.0 if 0.0 <= now <= 1.0 and 0.0 <= prior <= 1.0 else 1.0
    return (now - prior) * multiplier


def _model_update_detector_input(
    normalized: Mapping[str, Any],
    *,
    source_age_minutes: Optional[float],
) -> Dict[str, Any]:
    return {
        "source_id": normalized.get("source_id", ""),
        "run_id": normalized.get("run_id", ""),
        "cycle_time": normalized.get("cycle_time", ""),
        "source_age_minutes": _round_optional(source_age_minutes),
        "status": normalized.get("status") or "live_safe",
        "station": normalized.get("station", ""),
        "metric": normalized.get("metric", ""),
    }


def _price_latency_for_detector(movement: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "yes_price_change_points": movement.get("yes_price_change_points"),
        "no_price_change_points": movement.get("no_price_change_points"),
    }


def _quality_flags(
    event_type: str,
    blockers: list[str],
    movement: Mapping[str, Any],
) -> list[str]:
    flags = ["weather_run_lag_ledger"]
    if blockers:
        flags.append("weather_run_lag_fail_closed")
    if event_type == "new_run_arrival":
        flags.append("weather_model_run_arrived")
    if movement.get("market_repriced"):
        flags.append("clob_price_moved_since_prior_run")
    return flags


def _latest_entry(
    normalized: Mapping[str, Any],
    event: Mapping[str, Any],
    clob_snapshot: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "source_id": normalized.get("source_id", ""),
        "station": normalized.get("station", ""),
        "metric": normalized.get("metric", ""),
        "run_id": normalized.get("run_id", ""),
        "cycle_time": normalized.get("cycle_time", ""),
        "target_reference_time": normalized.get("target_reference_time", ""),
        "forecast_hour": normalized.get("forecast_hour"),
        "observed_at": event.get("observed_at", ""),
        "source_age_minutes": event.get("source_age_minutes"),
        "run_lag_minutes": event.get("run_lag_minutes"),
        "forecast_metrics": dict(event.get("forecast_metrics") or {}),
        "clob_snapshot": dict(clob_snapshot or {}),
        "run_manifest": dict(event.get("run_manifest") or {}),
        "last_event_type": event.get("event_type", ""),
    }


def _compact_event(event: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "event_type": event.get("event_type", ""),
        "status": event.get("status", ""),
        "observed_at": event.get("observed_at", ""),
        "state_key": event.get("state_key", ""),
        "source_id": event.get("source_id", ""),
        "station": event.get("station", ""),
        "metric": event.get("metric", ""),
        "run_id": event.get("run_id", ""),
        "previous_run_id": event.get("previous_run_id", ""),
        "blockers": list(event.get("blockers") or []),
    }


def _coerce_observed_at(value: Any) -> str:
    if value is None:
        return utc_now_iso()
    if isinstance(value, datetime):
        dt = _to_utc_naive(value)
        return dt.isoformat()
    parsed = _parse_datetime(value)
    return parsed.isoformat() if parsed is not None else str(value)


def _run_lag_minutes(cycle_time: Any, observed_at: Any) -> Optional[float]:
    cycle_dt = _parse_datetime(cycle_time)
    observed_dt = _parse_datetime(observed_at)
    if cycle_dt is None or observed_dt is None:
        return None
    return (observed_dt - cycle_dt).total_seconds() / 60.0


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return _to_utc_naive(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _to_utc_naive(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def _to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _first_text(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        text = _clean_text(payload.get(key))
        if text:
            return text
    return ""


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _first_float(payload: Mapping[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = _safe_float(payload.get(key))
        if value is not None:
            return value
    return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _safe_int(value: Any) -> Optional[int]:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return int(parsed)


def _round_optional(value: Optional[float]) -> Optional[float]:
    return round(value, 4) if value is not None else None


def _max_abs_delta(forecast_delta: Mapping[str, Mapping[str, float]]) -> Optional[float]:
    values = [_safe_float(item.get("delta")) for item in forecast_delta.values()]
    values = [abs(item) for item in values if item is not None]
    return round(max(values), 4) if values else None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return _to_utc_naive(value).isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value
