"""
Station-bias catalog builder for weather research.

Input rows should come from real observation/forecast joins. The builder only
computes corrections from the rows it is given; it does not invent station
history when evidence is missing.
"""

from __future__ import annotations

import json
import math
import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .weather_contracts import utc_now_iso


@dataclass(frozen=True)
class StationBiasObservation:
    station_id: str
    forecast_f: float
    observed_f: float
    observed_at: str
    source: str
    metric: str = "temperature"
    season: str = ""
    lead_hours: Optional[int] = None
    residual_f: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StationBiasEntry:
    station_id: str
    bias_correction_f: float
    sample_size: int
    mean_abs_error_f: float
    error_std_f: float
    source: str
    updated_at: str
    status: str
    metric_counts: Dict[str, int] = field(default_factory=dict)
    lead_hour_counts: Dict[str, int] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherStationBiasCatalogError(ValueError):
    """Raised when source artifacts cannot produce an auditable catalog."""


class WeatherStationBiasCatalogBuilder:
    """Create the JSON shape consumed by WeatherStationBiasResolver."""

    def __init__(
        self,
        min_sample_size: int = 30,
        *,
        max_abs_residual_f: float = 35.0,
        max_abs_bias_f: float = 15.0,
        max_error_std_f: float = 12.0,
        max_mean_abs_error_f: float = 18.0,
    ):
        self.min_sample_size = int(min_sample_size)
        if self.min_sample_size < 1:
            raise WeatherStationBiasCatalogError("min_sample_size must be at least 1")
        self.max_abs_residual_f = float(max_abs_residual_f)
        self.max_abs_bias_f = float(max_abs_bias_f)
        self.max_error_std_f = float(max_error_std_f)
        self.max_mean_abs_error_f = float(max_mean_abs_error_f)

    def build_catalog(self, observations: Iterable[StationBiasObservation]) -> Dict[str, Any]:
        grouped: Dict[str, List[StationBiasObservation]] = defaultdict(list)
        rejected_rows: List[Dict[str, Any]] = []
        for index, observation in enumerate(observations, start=1):
            normalized = self._validate_observation(observation, row_label=f"observation {index}")
            residual = self._residual_f(normalized)
            if abs(residual) > self.max_abs_residual_f:
                rejected_rows.append(
                    {
                        "station_id": normalized.station_id,
                        "observed_at": normalized.observed_at,
                        "residual_f": round(residual, 4),
                        "reason": "station_bias_residual_outlier",
                    }
                )
                continue
            grouped[normalized.station_id].append(normalized)

        if not grouped:
            if rejected_rows:
                raise WeatherStationBiasCatalogError(
                    "all station-bias observations were rejected as residual outliers"
                )
            raise WeatherStationBiasCatalogError("no station-bias observations were provided")

        stations = {}
        for station_id, rows in sorted(grouped.items()):
            entry = self._entry_for_station(station_id, rows)
            stations[station_id] = entry.to_dict()
        return {
            "schema_version": "weather_station_bias_catalog_v1",
            "generated_at": utc_now_iso(),
            "min_sample_size": self.min_sample_size,
            "quality_thresholds": {
                "max_abs_residual_f": self.max_abs_residual_f,
                "max_abs_bias_f": self.max_abs_bias_f,
                "max_error_std_f": self.max_error_std_f,
                "max_mean_abs_error_f": self.max_mean_abs_error_f,
            },
            "rejected_rows": rejected_rows,
            "stations": stations,
        }

    def write_catalog(self, observations: Iterable[StationBiasObservation], path: str | Path) -> Dict[str, Any]:
        payload = self.build_catalog(observations)
        out_path = Path(path).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def build_catalog_from_file(self, input_path: str | Path) -> Dict[str, Any]:
        observations = self.load_observations(input_path)
        return self.build_catalog(observations)

    def write_catalog_from_file(self, input_path: str | Path, output_path: str | Path) -> Dict[str, Any]:
        payload = self.build_catalog_from_file(input_path)
        out_path = Path(output_path).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def load_observations(self, input_path: str | Path) -> List[StationBiasObservation]:
        path = Path(input_path).expanduser()
        if not path.exists():
            raise WeatherStationBiasCatalogError(f"station-bias input artifact not found: {path}")
        if not path.is_file():
            raise WeatherStationBiasCatalogError(f"station-bias input artifact is not a file: {path}")
        suffix = path.suffix.lower()
        if suffix == ".json":
            return self._load_json(path)
        if suffix == ".jsonl":
            return self._load_jsonl(path)
        if suffix == ".csv":
            return self._load_csv(path)
        raise WeatherStationBiasCatalogError(
            f"unsupported station-bias input format '{suffix or '<none>'}'; use .json, .jsonl, or .csv"
        )

    def _entry_for_station(
        self,
        station_id: str,
        observations: List[StationBiasObservation],
    ) -> StationBiasEntry:
        errors = [self._residual_f(row) for row in observations]
        abs_errors = [abs(value) for value in errors]
        sample_size = len(errors)
        blockers = []
        quality_flags = []
        status = "validated"
        if sample_size < self.min_sample_size:
            status = "limited_sample"
            blockers.append("station_bias_sample_small")
        bias_correction = round(mean(errors), 4) if errors else 0.0
        mean_abs_error = round(mean(abs_errors), 4) if abs_errors else 0.0
        error_std = round(pstdev(errors), 4) if len(errors) > 1 else 0.0
        if abs(bias_correction) > self.max_abs_bias_f:
            status = "quality_blocked"
            blockers.append("station_bias_correction_large")
        if error_std > self.max_error_std_f:
            status = "quality_blocked"
            blockers.append("station_bias_error_std_high")
        if mean_abs_error > self.max_mean_abs_error_f:
            status = "quality_blocked"
            blockers.append("station_bias_mean_abs_error_high")
        if len({row.observed_at for row in observations}) < sample_size:
            quality_flags.append("station_bias_duplicate_observed_at")
        metric_counts = Counter(str(row.metric or "").lower() for row in observations if row.metric)
        lead_hour_counts = Counter(
            str(row.lead_hours) for row in observations if row.lead_hours is not None
        )
        if any("temperature" not in metric for metric in metric_counts):
            quality_flags.append("station_bias_non_temperature_rows_present")
        sources = sorted({row.source for row in observations if row.source})
        updated_at = max((row.observed_at for row in observations), default=utc_now_iso())
        return StationBiasEntry(
            station_id=station_id,
            bias_correction_f=bias_correction,
            sample_size=sample_size,
            mean_abs_error_f=mean_abs_error,
            error_std_f=error_std,
            source="+".join(sources) or "station_bias_catalog",
            updated_at=updated_at,
            status=status,
            metric_counts=dict(sorted(metric_counts.items())),
            lead_hour_counts=dict(sorted(lead_hour_counts.items())),
            blockers=blockers,
            quality_flags=quality_flags,
        )

    @staticmethod
    def observation_from_dict(row: Dict[str, Any], *, row_label: str = "row") -> StationBiasObservation:
        if not isinstance(row, dict):
            raise WeatherStationBiasCatalogError(f"{row_label}: expected object, got {type(row).__name__}")
        station_id = str(
            _first_present(row, ("station_id", "station", "metar_station", "resolution_station"))
            or ""
        ).strip().upper()
        forecast = _safe_float(
            _first_present(
                row,
                (
                    "forecast_f",
                    "forecast_temperature_f",
                    "forecast_temp_f",
                    "forecast_value_f",
                    "predicted_f",
                ),
            )
        )
        observed = _safe_float(
            _first_present(
                row,
                (
                    "observed_f",
                    "observed_temperature_f",
                    "observed_temp_f",
                    "actual_f",
                    "actual_temperature_f",
                    "settled_f",
                ),
            )
        )
        residual = _safe_float(_first_present(row, ("residual_f", "error_f", "forecast_error_f", "bias_f")))
        if not station_id:
            raise WeatherStationBiasCatalogError(f"{row_label}: station_id is required")
        if residual is None and (forecast is None or observed is None):
            raise WeatherStationBiasCatalogError(
                f"{row_label}: provide residual_f or both forecast_f and observed_f"
            )
        if residual is not None:
            forecast = 0.0 if forecast is None else forecast
            observed = forecast + residual if observed is None else observed
        observed_at = str(
            _first_present(row, ("observed_at", "valid_at", "target_time", "asof_time", "date")) or ""
        ).strip()
        if not observed_at:
            observed_at = datetime.utcnow().isoformat()
        source = str(_first_present(row, ("source", "source_id", "artifact_source")) or "station_bias_join").strip()
        lead_hours = _safe_int(_first_present(row, ("lead_hours", "forecast_hour", "lead_time_hours")))
        return StationBiasObservation(
            station_id=station_id,
            forecast_f=float(forecast),
            observed_f=float(observed),
            observed_at=observed_at,
            source=source or "station_bias_join",
            metric=str(row.get("metric") or row.get("weather_metric") or "temperature"),
            season=str(row.get("season") or ""),
            lead_hours=lead_hours,
            residual_f=residual,
        )

    def _load_json(self, path: Path) -> List[StationBiasObservation]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WeatherStationBiasCatalogError(f"{path}: invalid JSON at line {exc.lineno}") from exc
        rows = self._rows_from_json_payload(payload, path)
        return [
            self.observation_from_dict(row, row_label=f"{path}: row {index}")
            for index, row in enumerate(rows, start=1)
        ]

    def _load_jsonl(self, path: Path) -> List[StationBiasObservation]:
        observations = []
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise WeatherStationBiasCatalogError(f"{path}: invalid JSONL at line {line_number}") from exc
            observations.append(self.observation_from_dict(row, row_label=f"{path}: line {line_number}"))
        if not observations:
            raise WeatherStationBiasCatalogError(f"{path}: no station-bias rows found")
        return observations

    def _load_csv(self, path: Path) -> List[StationBiasObservation]:
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    raise WeatherStationBiasCatalogError(f"{path}: CSV header is missing")
                observations = [
                    self.observation_from_dict(row, row_label=f"{path}: row {index}")
                    for index, row in enumerate(reader, start=2)
                ]
        except csv.Error as exc:
            raise WeatherStationBiasCatalogError(f"{path}: invalid CSV: {exc}") from exc
        if not observations:
            raise WeatherStationBiasCatalogError(f"{path}: no station-bias rows found")
        return observations

    @staticmethod
    def _rows_from_json_payload(payload: Any, path: Path) -> Sequence[Dict[str, Any]]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("observations", "records", "rows", "residuals"):
                rows = payload.get(key)
                if isinstance(rows, list):
                    return rows
        raise WeatherStationBiasCatalogError(
            f"{path}: JSON must be a list of rows or contain observations/records/rows/residuals"
        )

    @staticmethod
    def _validate_observation(
        observation: StationBiasObservation,
        *,
        row_label: str,
    ) -> StationBiasObservation:
        if not isinstance(observation, StationBiasObservation):
            raise WeatherStationBiasCatalogError(
                f"{row_label}: expected StationBiasObservation, got {type(observation).__name__}"
            )
        station_id = str(observation.station_id or "").strip().upper()
        if not station_id:
            raise WeatherStationBiasCatalogError(f"{row_label}: station_id is required")
        forecast = _safe_float(observation.forecast_f)
        observed = _safe_float(observation.observed_f)
        if forecast is None or observed is None:
            raise WeatherStationBiasCatalogError(f"{row_label}: forecast_f and observed_f must be finite numbers")
        residual = _safe_float(observation.residual_f) if observation.residual_f is not None else None
        if residual is None:
            residual = observed - forecast
        return StationBiasObservation(
            station_id=station_id,
            forecast_f=forecast,
            observed_f=observed,
            observed_at=str(observation.observed_at or datetime.utcnow().isoformat()),
            source=str(observation.source or "station_bias_join"),
            metric=str(observation.metric or "temperature"),
            season=str(observation.season or ""),
            lead_hours=observation.lead_hours,
            residual_f=residual,
        )

    @staticmethod
    def _residual_f(observation: StationBiasObservation) -> float:
        if observation.residual_f is not None:
            residual = _safe_float(observation.residual_f)
            if residual is not None:
                return residual
        return float(observation.observed_f) - float(observation.forecast_f)


def _safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _safe_int(value: Any) -> Optional[int]:
    parsed = _safe_float(value)
    return int(parsed) if parsed is not None else None


def _first_present(row: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def _main() -> int:
    parser = argparse.ArgumentParser(description="Build a weather station-bias catalog from residual records.")
    parser.add_argument("input_path", help="JSON, JSONL, or CSV residual artifact")
    parser.add_argument("output_path", help="catalog JSON path to write")
    parser.add_argument("--min-sample-size", type=int, default=30)
    parser.add_argument("--max-abs-residual-f", type=float, default=35.0)
    parser.add_argument("--max-abs-bias-f", type=float, default=15.0)
    parser.add_argument("--max-error-std-f", type=float, default=12.0)
    parser.add_argument("--max-mean-abs-error-f", type=float, default=18.0)
    args = parser.parse_args()
    builder = WeatherStationBiasCatalogBuilder(
        min_sample_size=args.min_sample_size,
        max_abs_residual_f=args.max_abs_residual_f,
        max_abs_bias_f=args.max_abs_bias_f,
        max_error_std_f=args.max_error_std_f,
        max_mean_abs_error_f=args.max_mean_abs_error_f,
    )
    try:
        payload = builder.write_catalog_from_file(args.input_path, args.output_path)
    except WeatherStationBiasCatalogError as exc:
        parser.exit(2, f"station-bias catalog failed: {exc}\n")
    parser.exit(0, f"wrote {len(payload['stations'])} station-bias entries to {args.output_path}\n")


if __name__ == "__main__":
    _main()
