"""
High-resolution weather parser boundary.

The production HRRR/NBM files are GRIB2. This module makes the parser boundary
explicit: if a parsed point artifact is available, it is promoted into a
live-safe high-resolution snapshot; if only raw GRIB is available and the local
GRIB stack is missing, it fails closed with dependency blockers.
"""

from __future__ import annotations

import json
import math
import re
from importlib.util import find_spec
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .weather_contracts import WeatherResolutionTarget, utc_now_iso


@dataclass(frozen=True)
class WeatherHighResolutionParsedSnapshot:
    source_id: str
    status: str
    run_id: str
    forecast_metrics: Dict[str, Any] = field(default_factory=dict)
    parser: str = ""
    artifact_path: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    grid_distance_km: Optional[float] = None
    parsed_at: str = field(default_factory=utc_now_iso)
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherHighResolutionParser:
    """Parse cached high-resolution point artifacts and, when available, GRIB files."""

    SUPPORTED_SOURCES = {"noaa_hrrr", "noaa_nbm"}

    def __init__(self, cache_dir: str | Path | None = None, *, allow_latest_fallback: bool = True):
        self.cache_dir = Path(cache_dir).expanduser() if str(cache_dir or "").strip() else None
        self.allow_latest_fallback = bool(allow_latest_fallback)

    def parse_manifest(
        self,
        manifest: Dict[str, Any],
        resolution: WeatherResolutionTarget,
    ) -> WeatherHighResolutionParsedSnapshot:
        source_id = str(manifest.get("source_id") or "").strip()
        run_id = str(manifest.get("run_id") or "").strip()
        if source_id not in self.SUPPORTED_SOURCES:
            return WeatherHighResolutionParsedSnapshot(
                source_id=source_id,
                status="not_applicable",
                run_id=run_id,
                blockers=[f"high_resolution_source_not_supported:{source_id}"],
            )

        artifact = self._resolve_artifact(manifest)
        if artifact is None:
            return WeatherHighResolutionParsedSnapshot(
                source_id=source_id,
                status="artifact_missing",
                run_id=run_id,
                blockers=[f"high_resolution_artifact_missing:{source_id}"],
                quality_flags=["high_resolution_parser_boundary"],
            )

        suffix = artifact.suffix.lower()
        if suffix == ".json":
            return self._parse_point_json(artifact, manifest, resolution)
        if suffix in {".grib", ".grib2", ".grb", ".grb2"}:
            return self._parse_grib_if_supported(artifact, manifest, resolution)
        return WeatherHighResolutionParsedSnapshot(
            source_id=source_id,
            status="unsupported_artifact",
            run_id=run_id,
            artifact_path=str(artifact),
            blockers=[f"high_resolution_artifact_type_unsupported:{suffix or 'none'}"],
        )

    def enrich_manifest(
        self,
        manifest: Dict[str, Any],
        resolution: WeatherResolutionTarget,
    ) -> Dict[str, Any]:
        parsed = self.parse_manifest(manifest, resolution)
        enriched = dict(manifest)
        enriched["parsed_snapshot"] = parsed.to_dict()
        original_blockers = [
            str(blocker)
            for blocker in enriched.get("blockers", [])
            if str(blocker).strip()
        ]
        hard_blockers = [
            blocker for blocker in original_blockers if not blocker.startswith("parser_required:")
        ]
        parser_blockers = [
            blocker for blocker in original_blockers if blocker.startswith("parser_required:")
        ]
        if parsed.status == "live_safe" and not hard_blockers:
            enriched["status"] = "live_safe"
            enriched["parser_required"] = False
            enriched["forecast_metrics"] = dict(parsed.forecast_metrics)
            enriched["blockers"] = []
            enriched.setdefault("quality_flags", [])
            enriched["quality_flags"] = sorted(
                set([*enriched.get("quality_flags", []), *parsed.quality_flags, "high_resolution_parsed"])
            )
        elif parsed.status == "live_safe":
            enriched["parser_required"] = False
            enriched["forecast_metrics"] = dict(parsed.forecast_metrics)
            enriched["blockers"] = sorted(set(hard_blockers))
            enriched.setdefault("quality_flags", [])
            enriched["quality_flags"] = sorted(
                set([*enriched.get("quality_flags", []), *parsed.quality_flags, "high_resolution_parsed"])
            )
        else:
            enriched["blockers"] = sorted(set([*hard_blockers, *parser_blockers, *parsed.blockers]))
        return enriched

    def _resolve_artifact(self, manifest: Dict[str, Any]) -> Optional[Path]:
        local_path = str(manifest.get("local_path") or manifest.get("artifact_path") or "").strip()
        if local_path:
            path = Path(local_path).expanduser()
            return path if path.exists() else None
        if self.cache_dir is None:
            return None

        source_id = str(manifest.get("source_id") or "").strip()
        run_id = str(manifest.get("run_id") or "").strip()
        candidates: List[Path] = []
        if run_id:
            safe = _safe_filename(run_id)
            candidates.extend(
                [
                    self.cache_dir / f"{safe}.json",
                    self.cache_dir / source_id / f"{safe}.json",
                    self.cache_dir / f"{safe}.grib2",
                    self.cache_dir / source_id / f"{safe}.grib2",
                ]
            )
        if self.allow_latest_fallback:
            candidates.extend(
                [
                    self.cache_dir / source_id / "latest.json",
                    self.cache_dir / f"{source_id}_latest.json",
                    self.cache_dir / source_id / "latest.grib2",
                ]
            )
        return next((path for path in candidates if path.exists()), None)

    def _parse_point_json(
        self,
        path: Path,
        manifest: Dict[str, Any],
        resolution: WeatherResolutionTarget,
    ) -> WeatherHighResolutionParsedSnapshot:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return WeatherHighResolutionParsedSnapshot(
                source_id=str(manifest.get("source_id") or ""),
                status="parse_error",
                run_id=str(manifest.get("run_id") or ""),
                artifact_path=str(path),
                blockers=[f"high_resolution_json_parse_error:{type(exc).__name__}"],
            )
        metrics = self._metrics_from_payload(payload)
        blockers = []
        if not metrics:
            blockers.append("high_resolution_metrics_missing")
        source_id = str(payload.get("source_id") or manifest.get("source_id") or "")
        run_id = str(payload.get("run_id") or manifest.get("run_id") or "")
        distance = _safe_float(payload.get("grid_distance_km"))
        lat = _safe_float(payload.get("latitude"))
        lon = _safe_float(payload.get("longitude"))
        if distance is None and lat is not None and lon is not None:
            distance = _distance_km(float(resolution.latitude), float(resolution.longitude), lat, lon)
        return WeatherHighResolutionParsedSnapshot(
            source_id=source_id,
            status="live_safe" if not blockers else "unavailable",
            run_id=run_id,
            forecast_metrics=metrics,
            parser="point_json",
            artifact_path=str(path),
            latitude=lat,
            longitude=lon,
            grid_distance_km=round(distance, 4) if distance is not None else None,
            blockers=blockers,
            quality_flags=["high_resolution_point_artifact", "asof_required_upstream"],
        )

    def _parse_grib_if_supported(
        self,
        path: Path,
        manifest: Dict[str, Any],
        resolution: WeatherResolutionTarget,
    ) -> WeatherHighResolutionParsedSnapshot:
        missing = []
        if find_spec("xarray") is None:
            missing.append("grib_dependency_missing:xarray")
        if find_spec("cfgrib") is None:
            missing.append("grib_dependency_missing:cfgrib")
        if missing:
            return WeatherHighResolutionParsedSnapshot(
                source_id=str(manifest.get("source_id") or ""),
                status="unavailable",
                run_id=str(manifest.get("run_id") or ""),
                artifact_path=str(path),
                blockers=missing,
                quality_flags=["install_xarray_cfgrib_or_provide_point_json"],
            )
        try:
            import xarray as xr  # type: ignore
        except Exception:
            return WeatherHighResolutionParsedSnapshot(
                source_id=str(manifest.get("source_id") or ""),
                status="unavailable",
                run_id=str(manifest.get("run_id") or ""),
                artifact_path=str(path),
                blockers=["grib_dependency_missing:xarray"],
                quality_flags=["install_xarray_cfgrib_or_provide_point_json"],
            )
        try:
            dataset = xr.open_dataset(path, engine="cfgrib")
            metrics = self._metrics_from_xarray(dataset)
        except Exception as exc:
            return WeatherHighResolutionParsedSnapshot(
                source_id=str(manifest.get("source_id") or ""),
                status="parse_error",
                run_id=str(manifest.get("run_id") or ""),
                artifact_path=str(path),
                blockers=[f"grib_parse_error:{type(exc).__name__}"],
            )
        return WeatherHighResolutionParsedSnapshot(
            source_id=str(manifest.get("source_id") or ""),
            status="live_safe" if metrics else "unavailable",
            run_id=str(manifest.get("run_id") or ""),
            forecast_metrics=metrics,
            parser="xarray_cfgrib",
            artifact_path=str(path),
            latitude=float(resolution.latitude),
            longitude=float(resolution.longitude),
            blockers=[] if metrics else ["high_resolution_metrics_missing"],
            quality_flags=["high_resolution_grib_parsed"],
        )

    @staticmethod
    def _metrics_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        metrics = payload.get("forecast_metrics", payload.get("metrics", {}))
        if not isinstance(metrics, dict):
            return {}
        return _normalize_metrics(metrics)

    @staticmethod
    def _metrics_from_xarray(dataset: Any) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {}
        for key in ("t2m", "2t", "TMP", "temperature_2m"):
            value = _first_dataset_value(dataset, key)
            if value is not None:
                metrics["current_temperature_f"] = round(_temperature_to_f(value), 2)
                metrics["high_temperature_f"] = round(_temperature_to_f(value), 2)
                break
        for key in ("gust", "GUST", "wind_gust", "wind_gusts_10m"):
            value = _first_dataset_value(dataset, key)
            if value is not None:
                metrics["max_gust_mph"] = round(float(value) * 2.236936, 2)
                break
        return metrics


def _normalize_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in metrics.items():
        parsed = _safe_float(value)
        if parsed is None:
            continue
        normalized[str(key)] = round(parsed, 4)
    return normalized


def _first_dataset_value(dataset: Any, names: Iterable[str]) -> Optional[float]:
    for name in names if isinstance(names, tuple) else (names,):
        if name not in dataset:
            continue
        value = dataset[name]
        try:
            return float(value.values.reshape(-1)[0])
        except Exception:
            try:
                return float(value.values)
            except Exception:
                return None
    return None


def _temperature_to_f(value: float) -> float:
    # GRIB two-meter temperature is commonly Kelvin. Values below 170 are likely Celsius/Fahrenheit.
    parsed = float(value)
    if parsed > 170:
        return (parsed - 273.15) * 9.0 / 5.0 + 32.0
    return parsed


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("_")
