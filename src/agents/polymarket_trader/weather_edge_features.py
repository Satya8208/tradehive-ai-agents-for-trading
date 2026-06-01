"""
Edge-feature instrumentation for Polymarket weather markets.

This module does not pretend that HRRR/NBM GRIB parsing or station-bias
research is complete. It creates auditable manifests, latency fields, and bias
contracts so the research and paper lanes can collect evidence without
loosening the live gate.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import CLIMarket
from .weather_contracts import WeatherResolutionTarget, utc_now_iso
from .weather_high_res_parser import WeatherHighResolutionParser


@dataclass(frozen=True)
class WeatherStationBiasSnapshot:
    station_id: str
    status: str
    correction_f: float = 0.0
    source: str = ""
    sample_size: int = 0
    updated_at: str = ""
    generated_at: str = field(default_factory=utc_now_iso)
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherStationBiasResolver:
    """Load real station-bias evidence when present; otherwise report missing history."""

    def __init__(self, bias_path: str | Path | None = None, min_sample_size: int = 30):
        self.bias_path = Path(bias_path).expanduser() if str(bias_path or "").strip() else None
        self.min_sample_size = int(min_sample_size)
        self._catalog: Optional[Dict[str, Any]] = None

    def snapshot(self, resolution: WeatherResolutionTarget) -> WeatherStationBiasSnapshot:
        station_id = str(
            resolution.resolution_station
            or resolution.metar_station
            or resolution.station_name
            or ""
        ).upper()
        manual_correction = _safe_float(getattr(resolution, "bias_correction_f", 0.0)) or 0.0
        catalog = self._load_catalog()
        entry = catalog.get(station_id) if station_id and isinstance(catalog, dict) else None

        if isinstance(entry, dict):
            correction = _safe_float(entry.get("bias_correction_f"))
            sample_size = int(_safe_float(entry.get("sample_size")) or 0)
            source = str(entry.get("source") or "station_bias_catalog")
            updated_at = str(entry.get("updated_at") or "")
            blockers: List[str] = [str(item) for item in entry.get("blockers", []) or [] if str(item).strip()]
            status = str(entry.get("status") or "validated")
            flags = ["station_bias_catalog", *[str(item) for item in entry.get("quality_flags", []) or []]]
            if correction is None:
                correction = 0.0
                status = "unavailable"
                blockers.append("station_bias_correction_missing")
            if sample_size < self.min_sample_size:
                status = "limited_sample"
                blockers.append("station_bias_sample_small")
            if status == "quality_blocked" and not blockers:
                blockers.append("station_bias_quality_blocked")
            return WeatherStationBiasSnapshot(
                station_id=station_id,
                status=status,
                correction_f=round(float(correction), 4),
                source=source,
                sample_size=sample_size,
                updated_at=updated_at,
                blockers=blockers,
                quality_flags=flags,
            )

        if abs(manual_correction) > 0:
            return WeatherStationBiasSnapshot(
                station_id=station_id,
                status="manual_override",
                correction_f=round(manual_correction, 4),
                source="station_mapper_manual_override",
                blockers=[],
                quality_flags=["station_bias_manual_override"],
            )

        blockers = ["station_bias_history_missing"] if station_id else ["station_bias_station_missing"]
        return WeatherStationBiasSnapshot(
            station_id=station_id,
            status="missing_history",
            correction_f=0.0,
            source="none",
            blockers=blockers,
            quality_flags=["station_bias_unvalidated"],
        )

    def apply_temperature_bias(
        self,
        metrics: Dict[str, Any],
        snapshot: WeatherStationBiasSnapshot,
    ) -> Dict[str, Any]:
        adjusted = dict(metrics or {})
        correction = _safe_float(snapshot.correction_f) or 0.0
        if abs(correction) <= 0:
            return adjusted
        for key in ("high_temperature_f", "low_temperature_f", "current_temperature_f"):
            value = _safe_float(adjusted.get(key))
            if value is not None:
                adjusted[key] = round(value + correction, 2)
        adjusted["station_bias_correction_f"] = round(correction, 4)
        adjusted["station_bias_status"] = snapshot.status
        return adjusted

    def _load_catalog(self) -> Dict[str, Any]:
        if self._catalog is not None:
            return self._catalog
        if self.bias_path is None or not self.bias_path.exists():
            self._catalog = {}
            return self._catalog
        payload = json.loads(self.bias_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            self._catalog = {}
            return self._catalog
        raw_entries = payload.get("stations", payload)
        if not isinstance(raw_entries, dict):
            self._catalog = {}
            return self._catalog
        self._catalog = {str(key).upper(): value for key, value in raw_entries.items()}
        return self._catalog


@dataclass(frozen=True)
class WeatherHighResolutionManifest:
    source_id: str
    source_family: str
    status: str
    run_id: str
    cycle_time: str
    source_age_minutes: float
    target_reference_time: str
    target_lead_hours: int
    forecast_hour: int
    expected_update_interval_minutes: int
    request_url: str = ""
    parser_required: bool = True
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherHighResolutionSourceBuilder:
    """Build HRRR/NBM manifests with run timing before parser support exists."""

    DEFAULT_SOURCES = ("noaa_hrrr", "noaa_nbm")

    def __init__(self, cache_dir: str | Path | None = None, *, allow_latest_fallback: bool = True):
        self.parser = WeatherHighResolutionParser(
            cache_dir=cache_dir,
            allow_latest_fallback=allow_latest_fallback,
        )

    def build_manifests(
        self,
        resolution: WeatherResolutionTarget,
        target_date: Optional[date],
        metric: str,
        end_date: Optional[datetime] = None,
        source_ids: Optional[Iterable[str]] = None,
        generated_at: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        now = generated_at or datetime.utcnow()
        sources = tuple(source_ids or self.DEFAULT_SOURCES)
        manifests: List[Dict[str, Any]] = []
        for source_id in sources:
            manifest = self._build_manifest(source_id, resolution, target_date, metric, end_date, now).to_dict()
            if manifest.get("status") == "parser_required":
                manifest = self.parser.enrich_manifest(manifest, resolution)
            manifests.append(manifest)
        return manifests

    def _build_manifest(
        self,
        source_id: str,
        resolution: WeatherResolutionTarget,
        target_date: Optional[date],
        metric: str,
        end_date: Optional[datetime],
        now: datetime,
    ) -> WeatherHighResolutionManifest:
        if not _is_conus_resolution(resolution):
            return WeatherHighResolutionManifest(
                source_id=source_id,
                source_family="noaa_high_resolution",
                status="not_applicable",
                run_id="",
                cycle_time="",
                source_age_minutes=0.0,
                target_reference_time="",
                target_lead_hours=0,
                forecast_hour=0,
                expected_update_interval_minutes=60,
                parser_required=True,
                blockers=[f"source_not_applicable:non_conus:{source_id}"],
                quality_flags=["high_resolution_manifest"],
            )

        if source_id == "noaa_hrrr":
            interval_hours = 1
            settle_delay_minutes = 75
            max_forecast_hour = 48
            expected_update_interval = 60
        else:
            interval_hours = 6
            settle_delay_minutes = 150
            max_forecast_hour = 264
            expected_update_interval = 360

        cycle = _latest_cycle(now, interval_hours=interval_hours, settle_delay_minutes=settle_delay_minutes)
        target_dt = _target_reference_time(target_date, metric, end_date)
        target_lead_hours = max(0, int(round((target_dt - cycle).total_seconds() / 3600.0)))
        forecast_hour = min(target_lead_hours, max_forecast_hour)
        ymd = cycle.strftime("%Y%m%d")
        cycle_hour = cycle.strftime("%H")
        forecast = f"{forecast_hour:02d}" if source_id == "noaa_hrrr" else f"{forecast_hour:03d}"

        blockers = [f"parser_required:{source_id}"]
        status = "parser_required"
        if target_lead_hours > max_forecast_hour:
            status = "not_applicable"
            blockers.append(f"lead_time_out_of_range:{source_id}")

        if source_id == "noaa_hrrr":
            request_url = (
                "https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_2d.pl"
                f"?dir=/hrrr.{ymd}/conus"
                f"&file=hrrr.t{cycle_hour}z.wrfsfcf{forecast}.grib2"
                "&lev_2_m_above_ground=on&var_TMP=on&var_APCP=on&var_GUST=on"
            )
        else:
            request_url = (
                "https://nomads.ncep.noaa.gov/cgi-bin/filter_blend.pl"
                f"?dir=/blend.{ymd}/{cycle_hour}/core"
                f"&file=blend.t{cycle_hour}z.core.f{forecast}.co.grib2"
                "&lev_2_m_above_ground=on&var_TMP=on&var_APCP=on&var_WIND=on"
            )

        return WeatherHighResolutionManifest(
            source_id=source_id,
            source_family="noaa_high_resolution",
            status=status,
            run_id=f"{source_id}:{ymd}:{cycle_hour}:f{forecast}",
            cycle_time=cycle.isoformat(),
            source_age_minutes=round(max(0.0, (now - cycle).total_seconds() / 60.0), 2),
            target_reference_time=target_dt.isoformat(),
            target_lead_hours=target_lead_hours,
            forecast_hour=forecast_hour,
            expected_update_interval_minutes=expected_update_interval,
            request_url=request_url,
            parser_required=True,
            blockers=blockers,
            quality_flags=["high_resolution_manifest", "nomads_manifest", "no_private_credentials"],
        )


class WeatherPriceLatencyTracker:
    """In-memory CLOB price movement tracker for a single paper/live process."""

    def __init__(self):
        self._last_seen: Dict[str, Dict[str, Any]] = {}

    def snapshot(self, market: CLIMarket, now: Optional[datetime] = None) -> Dict[str, Any]:
        timestamp = now or datetime.utcnow()
        market_id = str(getattr(market, "condition_id", "") or "")
        current_yes = _safe_float(getattr(market, "yes_price", None))
        current_no = _safe_float(getattr(market, "no_price", None))
        prior = self._last_seen.get(market_id)
        payload: Dict[str, Any] = {
            "status": "first_scan_no_prior_price",
            "market_id": market_id,
            "asof_time": timestamp.isoformat(),
            "current_yes_price": current_yes,
            "current_no_price": current_no,
            "prior_yes_price": None,
            "prior_no_price": None,
            "minutes_since_prior_scan": None,
            "yes_price_change_points": None,
            "no_price_change_points": None,
        }
        if prior:
            prior_time = _parse_datetime(prior.get("asof_time"))
            prior_yes = _safe_float(prior.get("current_yes_price"))
            prior_no = _safe_float(prior.get("current_no_price"))
            payload.update(
                {
                    "status": "ok",
                    "prior_yes_price": prior_yes,
                    "prior_no_price": prior_no,
                    "minutes_since_prior_scan": round(
                        max(0.0, (timestamp - prior_time).total_seconds() / 60.0),
                        2,
                    )
                    if prior_time
                    else None,
                    "yes_price_change_points": round((current_yes - prior_yes) * 100.0, 2)
                    if current_yes is not None and prior_yes is not None
                    else None,
                    "no_price_change_points": round((current_no - prior_no) * 100.0, 2)
                    if current_no is not None and prior_no is not None
                    else None,
                }
            )
        self._last_seen[market_id] = {
            "asof_time": timestamp.isoformat(),
            "current_yes_price": current_yes,
            "current_no_price": current_no,
        }
        return payload


def _latest_cycle(now: datetime, interval_hours: int, settle_delay_minutes: int) -> datetime:
    eligible = now - timedelta(minutes=settle_delay_minutes)
    cycle_hour = eligible.hour - (eligible.hour % max(1, interval_hours))
    return eligible.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)


def _target_reference_time(
    target_date: Optional[date],
    metric: str,
    end_date: Optional[datetime],
) -> datetime:
    if end_date is not None:
        return end_date.replace(tzinfo=None, microsecond=0)
    base = target_date or datetime.utcnow().date()
    hour = 18 if metric in {"temperature_high", "precipitation", "snowfall"} else 12
    if metric in {"temperature_low"}:
        hour = 6
    return datetime(base.year, base.month, base.day, hour, 0, 0)


def _is_conus_resolution(resolution: WeatherResolutionTarget) -> bool:
    lat = _safe_float(getattr(resolution, "latitude", None))
    lon = _safe_float(getattr(resolution, "longitude", None))
    if lat is None or lon is None:
        return False
    return 24.0 <= lat <= 50.0 and -125.0 <= lon <= -66.0


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None
