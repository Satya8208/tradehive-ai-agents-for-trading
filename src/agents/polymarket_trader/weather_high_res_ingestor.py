"""
NOAA high-resolution weather point artifact ingestor.

This module turns public HRRR/NBM GRIB2 manifests into station-level point JSON
artifacts that the weather signal path can consume from cache. It prefers
`wgrib2` because the MVP needs a single point extraction, not a full GRIB data
platform. If `wgrib2` is unavailable, it fails closed without downloading.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from .weather_contracts import WeatherResolutionTarget, utc_now_iso

POINT_ARTIFACT_SCHEMA_VERSION = "weather_high_res_point_v1"


@dataclass(frozen=True)
class WeatherHighResolutionIngestResult:
    source_id: str
    status: str
    run_id: str
    raw_artifact_path: str = ""
    point_artifact_path: str = ""
    latest_artifact_path: str = ""
    request_url: str = ""
    parser: str = ""
    forecast_metrics: Dict[str, Any] = field(default_factory=dict)
    downloaded_bytes: int = 0
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherHighResolutionArtifactIngestor:
    """Download NOAA subset GRIB2 files and write station-level point JSON artifacts."""

    SUPPORTED_SOURCES = {"noaa_hrrr", "noaa_nbm"}

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        session: Optional[requests.Session] = None,
        wgrib2_binary: Optional[str] = None,
        command_runner: Optional[Callable[..., Any]] = None,
        min_request_interval_seconds: float = 10.0,
        timeout_seconds: int = 60,
    ):
        self.cache_dir = Path(cache_dir).expanduser()
        self.session = session or requests.Session()
        self.wgrib2_binary = wgrib2_binary
        self._custom_command_runner = command_runner is not None
        self.command_runner = command_runner or subprocess.run
        self.min_request_interval_seconds = max(0.0, float(min_request_interval_seconds))
        self.timeout_seconds = int(timeout_seconds)
        self._last_request_time = 0.0

    def ingest_manifest(
        self,
        manifest: Dict[str, Any],
        resolution: WeatherResolutionTarget,
        *,
        metric: str = "",
        force: bool = False,
    ) -> WeatherHighResolutionIngestResult:
        source_id = str(manifest.get("source_id") or "").strip()
        run_id = str(manifest.get("run_id") or "").strip()
        if source_id not in self.SUPPORTED_SOURCES:
            return self._blocked(
                manifest,
                "not_applicable",
                [f"high_resolution_source_not_supported:{source_id or 'missing'}"],
            )
        if not run_id:
            return self._blocked(manifest, "unavailable", [f"high_resolution_run_id_missing:{source_id}"])

        point_path = self._point_artifact_path(source_id, run_id)
        latest_path = self._latest_artifact_path(source_id)
        raw_path = self._raw_artifact_path(source_id, run_id)
        if point_path.exists() and not force:
            payload = self._load_json(point_path)
            return WeatherHighResolutionIngestResult(
                source_id=source_id,
                status="live_safe" if payload.get("forecast_metrics") else "unavailable",
                run_id=run_id,
                raw_artifact_path=str(raw_path) if raw_path.exists() else "",
                point_artifact_path=str(point_path),
                latest_artifact_path=str(latest_path) if latest_path.exists() else "",
                request_url=str(manifest.get("request_url") or ""),
                parser=str(payload.get("parser") or "point_json_cache"),
                forecast_metrics=dict(payload.get("forecast_metrics") or {}),
                blockers=[] if payload.get("forecast_metrics") else ["high_resolution_metrics_missing"],
                quality_flags=["high_resolution_point_cache_hit"],
            )

        binary = self._resolve_wgrib2_binary()
        if not binary:
            return self._blocked(
                manifest,
                "parser_unavailable",
                ["wgrib2_missing"],
                quality_flags=["install_wgrib2_or_supply_point_json"],
            )

        request_url = self._station_subset_url(str(manifest.get("request_url") or ""), resolution)
        if not request_url:
            return self._blocked(manifest, "unavailable", [f"high_resolution_request_url_missing:{source_id}"])

        try:
            downloaded_bytes = self._download_raw(request_url, raw_path, force=force)
            extraction = self._extract_point(binary, raw_path, resolution)
        except Exception as exc:
            return self._blocked(
                manifest,
                "unavailable",
                [f"high_resolution_ingest_error:{type(exc).__name__}"],
                raw_artifact_path=str(raw_path) if raw_path.exists() else "",
                request_url=request_url,
            )

        metrics = self._metrics_from_wgrib2_records(extraction["records"], metric=metric)
        if not metrics:
            return self._blocked(
                manifest,
                "unavailable",
                ["high_resolution_metrics_missing"],
                raw_artifact_path=str(raw_path),
                request_url=request_url,
            )

        point_payload = self._point_payload(
            manifest=manifest,
            resolution=resolution,
            request_url=request_url,
            raw_path=raw_path,
            extraction=extraction,
            metrics=metrics,
        )
        self._write_json(point_path, point_payload)
        self._write_json(latest_path, point_payload)
        result = WeatherHighResolutionIngestResult(
            source_id=source_id,
            status="live_safe",
            run_id=run_id,
            raw_artifact_path=str(raw_path),
            point_artifact_path=str(point_path),
            latest_artifact_path=str(latest_path),
            request_url=request_url,
            parser="wgrib2_lonlat",
            forecast_metrics=metrics,
            downloaded_bytes=downloaded_bytes,
            blockers=[],
            quality_flags=["noaa_public_data", "wgrib2_point_extraction", "high_resolution_point_artifact"],
        )
        self._append_ledger(result)
        return result

    def _blocked(
        self,
        manifest: Dict[str, Any],
        status: str,
        blockers: List[str],
        *,
        quality_flags: Optional[List[str]] = None,
        raw_artifact_path: str = "",
        request_url: str = "",
    ) -> WeatherHighResolutionIngestResult:
        return WeatherHighResolutionIngestResult(
            source_id=str(manifest.get("source_id") or ""),
            status=status,
            run_id=str(manifest.get("run_id") or ""),
            raw_artifact_path=raw_artifact_path,
            request_url=request_url or str(manifest.get("request_url") or ""),
            blockers=blockers,
            quality_flags=quality_flags or ["high_resolution_ingest_fail_closed"],
        )

    def _resolve_wgrib2_binary(self) -> Optional[str]:
        if self.wgrib2_binary:
            path = Path(self.wgrib2_binary).expanduser()
            if path.exists():
                return str(path)
            found = shutil.which(self.wgrib2_binary)
            if found:
                return found
            if self._custom_command_runner:
                return self.wgrib2_binary
            return None
        return shutil.which("wgrib2")

    def _station_subset_url(self, request_url: str, resolution: WeatherResolutionTarget) -> str:
        if not request_url:
            return ""
        split = urlsplit(request_url)
        query = dict(parse_qsl(split.query, keep_blank_values=True))
        lat = _safe_float(getattr(resolution, "latitude", None))
        lon = _safe_float(getattr(resolution, "longitude", None))
        if lat is None or lon is None:
            return request_url
        pad = 0.5
        query.setdefault("subregion", "")
        query.setdefault("leftlon", f"{lon - pad:.3f}")
        query.setdefault("rightlon", f"{lon + pad:.3f}")
        query.setdefault("toplat", f"{lat + pad:.3f}")
        query.setdefault("bottomlat", f"{lat - pad:.3f}")
        return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))

    def _download_raw(self, request_url: str, raw_path: Path, *, force: bool) -> int:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if raw_path.exists() and raw_path.stat().st_size > 0 and not force:
            return int(raw_path.stat().st_size)
        self._respect_rate_limit()
        response = self.session.get(request_url, timeout=self.timeout_seconds)
        response.raise_for_status()
        if hasattr(response, "content"):
            content = response.content
        else:
            content = b"".join(response.iter_content(chunk_size=1024 * 1024))
        if not content:
            raise ValueError("empty_noaa_grib_response")
        raw_path.write_bytes(content)
        return len(content)

    def _respect_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if self._last_request_time and elapsed < self.min_request_interval_seconds:
            time.sleep(self.min_request_interval_seconds - elapsed)
        self._last_request_time = time.monotonic()

    def _extract_point(
        self,
        binary: str,
        raw_path: Path,
        resolution: WeatherResolutionTarget,
    ) -> Dict[str, Any]:
        lon = float(getattr(resolution, "longitude"))
        lat = float(getattr(resolution, "latitude"))
        completed = self.command_runner(
            [binary, str(raw_path), "-lon", f"{lon:.5f}", f"{lat:.5f}"],
            capture_output=True,
            text=True,
            timeout=max(self.timeout_seconds, 30),
            check=False,
        )
        stdout = str(getattr(completed, "stdout", "") or "")
        stderr = str(getattr(completed, "stderr", "") or "")
        returncode = int(getattr(completed, "returncode", 0) or 0)
        if returncode != 0:
            raise RuntimeError(f"wgrib2_failed:{returncode}:{stderr[:200]}")
        records = [_parse_wgrib2_lon_line(line) for line in stdout.splitlines() if line.strip()]
        records = [record for record in records if record]
        if not records:
            raise ValueError("wgrib2_no_point_records")
        grid_lat = _first_present(records, "grid_latitude")
        grid_lon = _first_present(records, "grid_longitude")
        distance = (
            _distance_km(lat, lon, float(grid_lat), float(grid_lon))
            if grid_lat is not None and grid_lon is not None
            else None
        )
        return {
            "records": records,
            "grid_latitude": grid_lat,
            "grid_longitude": grid_lon,
            "grid_distance_km": round(distance, 4) if distance is not None else None,
        }

    def _metrics_from_wgrib2_records(self, records: List[Dict[str, Any]], *, metric: str = "") -> Dict[str, Any]:
        raw_values: Dict[str, float] = {}
        for record in records:
            variable = str(record.get("variable") or "").upper()
            value = _safe_float(record.get("value"))
            if not variable or value is None:
                continue
            raw_values.setdefault(variable, value)

        metrics: Dict[str, Any] = {}
        temp = _first_raw_value(raw_values, ["TMP", "TMAX", "MAXT", "TMIN", "MINT"])
        if temp is not None:
            temp_f = round(_temperature_to_f(temp), 2)
            metrics["current_temperature_f"] = temp_f
            if metric == "temperature_low":
                metrics["low_temperature_f"] = temp_f
            else:
                metrics["high_temperature_f"] = temp_f
        tmax = _first_raw_value(raw_values, ["TMAX", "MAXT"])
        if tmax is not None:
            metrics["high_temperature_f"] = round(_temperature_to_f(tmax), 2)
        tmin = _first_raw_value(raw_values, ["TMIN", "MINT"])
        if tmin is not None:
            metrics["low_temperature_f"] = round(_temperature_to_f(tmin), 2)

        precip = _first_raw_value(raw_values, ["APCP", "PRATE", "QPF"])
        if precip is not None:
            metrics["precipitation_in"] = round(float(precip) * 0.0393701, 4)

        gust = _first_raw_value(raw_values, ["GUST"])
        if gust is not None:
            metrics["max_gust_mph"] = round(float(gust) * 2.236936, 2)
        wind = _first_raw_value(raw_values, ["WIND", "UGRD", "VGRD"])
        if wind is not None:
            metrics["max_wind_mph"] = round(float(wind) * 2.236936, 2)
        return metrics

    def _point_payload(
        self,
        manifest: Dict[str, Any],
        resolution: WeatherResolutionTarget,
        request_url: str,
        raw_path: Path,
        extraction: Dict[str, Any],
        metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "artifact_schema_version": POINT_ARTIFACT_SCHEMA_VERSION,
            "source_id": str(manifest.get("source_id") or ""),
            "source_family": str(manifest.get("source_family") or "noaa_high_resolution"),
            "run_id": str(manifest.get("run_id") or ""),
            "cycle_time": str(manifest.get("cycle_time") or ""),
            "target_reference_time": str(manifest.get("target_reference_time") or ""),
            "forecast_hour": int(_safe_float(manifest.get("forecast_hour")) or 0),
            "target_lead_hours": int(_safe_float(manifest.get("target_lead_hours")) or 0),
            "request_url": request_url,
            "raw_artifact_path": str(raw_path),
            "parser": "wgrib2_lonlat",
            "latitude": float(getattr(resolution, "latitude")),
            "longitude": float(getattr(resolution, "longitude")),
            "grid_latitude": extraction.get("grid_latitude"),
            "grid_longitude": extraction.get("grid_longitude"),
            "grid_distance_km": extraction.get("grid_distance_km"),
            "forecast_metrics": dict(metrics),
            "raw_point_records": list(extraction.get("records") or []),
            "resolution_station": str(getattr(resolution, "resolution_station", "") or ""),
            "metar_station": str(getattr(resolution, "metar_station", "") or ""),
            "generated_at": utc_now_iso(),
            "quality_flags": ["noaa_public_data", "wgrib2_point_extraction", "asof_required_upstream"],
        }

    def _point_artifact_path(self, source_id: str, run_id: str) -> Path:
        return self.cache_dir / source_id / f"{_safe_filename(run_id)}.json"

    def _latest_artifact_path(self, source_id: str) -> Path:
        return self.cache_dir / source_id / "latest.json"

    def _raw_artifact_path(self, source_id: str, run_id: str) -> Path:
        return self.cache_dir / "raw" / source_id / f"{_safe_filename(run_id)}.grib2"

    def _append_ledger(self, result: WeatherHighResolutionIngestResult) -> None:
        ledger = self.cache_dir / "ingest_ledger.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result.to_dict(), sort_keys=True) + "\n")

    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(path)


def _parse_wgrib2_lon_line(line: str) -> Dict[str, Any]:
    parts = [part.strip() for part in str(line or "").split(":") if part.strip()]
    variable = next((part.upper() for part in parts if part.upper() in _KNOWN_WGRIB2_VARIABLES), "")
    value = _match_float(line, "val=")
    grid_lon = _match_float(line, "lon=")
    grid_lat = _match_float(line, "lat=")
    if value is None:
        return {}
    return {
        "variable": variable,
        "value": value,
        "grid_latitude": grid_lat,
        "grid_longitude": _normalize_grid_lon(grid_lon),
        "raw": line,
    }


def _match_float(text: str, marker: str) -> Optional[float]:
    start = str(text).find(marker)
    if start < 0:
        return None
    start += len(marker)
    chars = []
    for char in str(text)[start:]:
        if char.isdigit() or char in {".", "-", "+", "e", "E"}:
            chars.append(char)
        elif chars:
            break
    return _safe_float("".join(chars))


def _first_present(records: List[Dict[str, Any]], key: str) -> Optional[float]:
    for record in records:
        value = _safe_float(record.get(key))
        if value is not None:
            return value
    return None


def _first_raw_value(raw_values: Dict[str, float], names: List[str]) -> Optional[float]:
    for name in names:
        if name in raw_values:
            return raw_values[name]
    return None


def _temperature_to_f(value: float) -> float:
    parsed = float(value)
    if parsed > 170:
        return (parsed - 273.15) * 9.0 / 5.0 + 32.0
    return parsed


def _normalize_grid_lon(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    parsed = float(value)
    if parsed > 180:
        parsed = parsed - 360.0
    return round(parsed, 6)


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
    safe = "".join(char if char.isalnum() or char in {"_", ".", "-"} else "_" for char in str(value or ""))
    return safe.strip("_") or "missing_run_id"


_KNOWN_WGRIB2_VARIABLES = {
    "TMP",
    "TMAX",
    "MAXT",
    "TMIN",
    "MINT",
    "APCP",
    "PRATE",
    "QPF",
    "GUST",
    "WIND",
    "UGRD",
    "VGRD",
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest one NOAA HRRR/NBM manifest into point JSON.")
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--manifest-json", required=True, help="Path to a high-resolution manifest JSON object.")
    parser.add_argument("--resolution-json", required=True, help="Path to a WeatherResolutionTarget JSON object.")
    parser.add_argument("--metric", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    manifest = json.loads(Path(args.manifest_json).read_text(encoding="utf-8"))
    resolution_payload = json.loads(Path(args.resolution_json).read_text(encoding="utf-8"))
    resolution = WeatherResolutionTarget(**resolution_payload)
    result = WeatherHighResolutionArtifactIngestor(args.cache_dir).ingest_manifest(
        manifest,
        resolution,
        metric=args.metric,
        force=args.force,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0 if result.status == "live_safe" else 2


if __name__ == "__main__":
    raise SystemExit(main())
