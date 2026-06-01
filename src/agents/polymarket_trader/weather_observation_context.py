"""Compile observation and replay context for routed weather markets."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .weather_blockers import blocker_summary, blockers_to_records
from .weather_market_type_classifier import (
    LANE_HRRR_NBM_RUN_SHOCK,
    LANE_LADDER_CONSISTENCY,
    LANE_OBSERVATION_LAG,
    LANE_STATION_SOURCE_MISMATCH,
)
from .weather_market_universe_router import WeatherRoutedMarket


WEATHER_OBSERVATION_CONTEXT_SCHEMA_VERSION = "weather_observation_context_v1"

NEAR_OBSERVATION_HORIZONS = {"already_in_window", "0_6h", "6_24h"}
FORECAST_HORIZONS = {"24_72h", "gt_72h"}


@dataclass(frozen=True)
class WeatherObservationContext:
    market_id: str
    question: str
    context_status: str
    routing_destination: str
    settlement_truth_status: str
    blockers: List[str]
    contract_type: str = ""
    metric: str = ""
    operator: str = ""
    threshold: Optional[float] = None
    upper_threshold: Optional[float] = None
    threshold_unit: str = ""
    target_date: str = ""
    horizon_bucket: str = ""
    hours_to_end: float = 999.0
    station_id: str = ""
    station_type: str = ""
    region: str = ""
    official_observation_sources: List[str] = field(default_factory=list)
    forecast_sources: List[str] = field(default_factory=list)
    alpha_lanes: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)
    schema_version: str = WEATHER_OBSERVATION_CONTEXT_SCHEMA_VERSION
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["blocker_records"] = blockers_to_records(self.blockers)
        payload["blocker_summary"] = blocker_summary(self.blockers)
        return payload


class WeatherObservationContextCompiler:
    """Normalize routed markets into context-ready lane destinations."""

    def compile(self, row: WeatherRoutedMarket) -> WeatherObservationContext:
        classification = row.classification or {}
        lanes = _text_list(classification.get("alpha_lanes"))
        sources = _text_list(classification.get("source_applicability"))
        blockers = _context_blockers(classification)
        horizon = _text(classification.get("horizon_bucket"))
        hours_to_end = _finite_float(classification.get("hours_to_end"), 999.0)
        destination = self._routing_destination(
            lanes=lanes,
            blockers=blockers,
            horizon=horizon,
            hours_to_end=hours_to_end,
        )
        context_status = "ready" if not blockers else "blocked"
        if destination == "forecast_replay_lane" and not _hard_context_blockers(blockers):
            context_status = "future_window_routed_to_forecast"
        elif destination == "expired_or_closed":
            context_status = "closed_window_not_test_run_eligible"

        return WeatherObservationContext(
            market_id=_text(row.market_id),
            question=_text(row.question),
            context_status=context_status,
            routing_destination=destination,
            settlement_truth_status="requires_polymarket_resolution_label_before_replay",
            blockers=sorted(set(blockers)),
            contract_type=_text(classification.get("contract_type")),
            metric=_text(classification.get("metric")),
            operator=_text(classification.get("operator")),
            threshold=_optional_float(classification.get("threshold")),
            upper_threshold=_optional_float(classification.get("upper_threshold")),
            threshold_unit=_text(classification.get("threshold_unit")),
            target_date=_text(classification.get("target_date")),
            horizon_bucket=horizon,
            hours_to_end=hours_to_end,
            station_id=_text(classification.get("station_id")).upper(),
            station_type=_text(classification.get("station_type")),
            region=_text(classification.get("region")),
            official_observation_sources=sorted(
                source for source in sources if source in {"METAR_ASOS_applicable", "NWS_applicable"}
            ),
            forecast_sources=sorted(
                source for source in sources if source in {"HRRR_applicable", "NBM_applicable", "OpenMeteo_baseline", "OpenMeteo_only"}
            ),
            alpha_lanes=lanes,
            quality_flags=_quality_flags(destination, context_status),
        )

    def audit_routed(self, routed: Iterable[WeatherRoutedMarket]) -> Dict[str, Any]:
        records = [self.compile(row).to_dict() for row in routed]
        blocker_counts = Counter(blocker for record in records for blocker in record.get("blockers", []))
        destination_counts = Counter(str(record.get("routing_destination") or "unknown") for record in records)
        status_counts = Counter(str(record.get("context_status") or "unknown") for record in records)
        return {
            "schema_version": WEATHER_OBSERVATION_CONTEXT_SCHEMA_VERSION,
            "record_count": len(records),
            "destination_counts": dict(sorted(destination_counts.items())),
            "status_counts": dict(sorted(status_counts.items())),
            "blocker_counts": dict(sorted(blocker_counts.items())),
            "blocker_summary": blocker_summary(blocker_counts.keys()),
            "records": records,
        }

    @staticmethod
    def _routing_destination(
        *,
        lanes: List[str],
        blockers: List[str],
        horizon: str,
        hours_to_end: float,
    ) -> str:
        if hours_to_end <= 0:
            return "expired_or_closed"
        if LANE_OBSERVATION_LAG in lanes and horizon in NEAR_OBSERVATION_HORIZONS and not _hard_context_blockers(blockers):
            return "known_outcome_observation_lag"
        if horizon in FORECAST_HORIZONS and {LANE_HRRR_NBM_RUN_SHOCK, LANE_STATION_SOURCE_MISMATCH}.intersection(lanes):
            return "forecast_replay_lane"
        if LANE_LADDER_CONSISTENCY in lanes:
            return "structural_ladder_lane"
        if blockers:
            return "context_repair_backlog"
        return "research_backlog"


def _context_blockers(classification: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    if not _text(classification.get("station_id")):
        blockers.append("observation_context_station_missing")
    if not _text(classification.get("target_date")):
        blockers.append("observation_context_target_date_missing")
    if not _text(classification.get("metric")):
        blockers.append("observation_context_metric_missing")
    if not _text(classification.get("operator")):
        blockers.append("observation_context_operator_missing")
    if _optional_float(classification.get("threshold")) is None:
        blockers.append("observation_context_threshold_missing")
    for blocker in _text_list(classification.get("blockers")):
        if blocker.startswith("unparsed_") or "station" in blocker:
            blockers.append(f"observation_context_source_blocker:{blocker}")
    return blockers


def _hard_context_blockers(blockers: List[str]) -> List[str]:
    return [
        blocker
        for blocker in blockers
        if blocker
        in {
            "observation_context_station_missing",
            "observation_context_target_date_missing",
            "observation_context_metric_missing",
            "observation_context_operator_missing",
            "observation_context_threshold_missing",
        }
        or blocker.startswith("observation_context_source_blocker:")
    ]


def _quality_flags(destination: str, context_status: str) -> List[str]:
    flags = ["observation_context_compiled", f"routing_destination:{destination}"]
    if context_status == "ready":
        flags.append("context_ready")
    return flags


def _text(value: Any) -> str:
    return str(value or "").strip()


def _text_list(value: Any) -> List[str]:
    if isinstance(value, (list, tuple, set)):
        return sorted({str(item).strip() for item in value if str(item or "").strip()})
    text = _text(value)
    return [text] if text else []


def _optional_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _finite_float(value: Any, default: float) -> float:
    parsed = _optional_float(value)
    return default if parsed is None else parsed
