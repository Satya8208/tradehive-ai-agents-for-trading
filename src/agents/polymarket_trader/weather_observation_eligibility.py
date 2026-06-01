"""Observation-pool eligibility for routed weather markets.

This module sits between the weather universe router and the known-outcome
scanner. It makes the routing-to-observation-pool step auditable: every routed
market gets a record explaining whether it can support the observation-lag lane.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .weather_blockers import blocker_summary, blockers_to_records
from .weather_market_type_classifier import (
    CONTRACT_PRECIP_AMOUNT,
    CONTRACT_PRECIP_BINARY,
    CONTRACT_SNOW_AMOUNT,
    CONTRACT_TEMP_HIGH,
    CONTRACT_TEMP_LOW,
    CONTRACT_WIND,
    CONTRACT_WIND_GUST,
    LANE_OBSERVATION_LAG,
)
from .weather_market_universe_router import WeatherRoutedMarket


WEATHER_OBSERVATION_ELIGIBILITY_SCHEMA_VERSION = "weather_observation_eligibility_v1"

SUPPORTED_OBSERVATION_CONTRACTS = {
    CONTRACT_TEMP_HIGH,
    CONTRACT_TEMP_LOW,
    CONTRACT_PRECIP_BINARY,
    CONTRACT_PRECIP_AMOUNT,
    CONTRACT_SNOW_AMOUNT,
    CONTRACT_WIND,
    CONTRACT_WIND_GUST,
}

SUPPORTED_OBSERVATION_METRICS = {
    "temperature_high",
    "temperature_low",
    "precipitation",
    "snowfall",
    "wind",
    "wind_gust",
}

NEAR_OBSERVATION_HORIZONS = {"already_in_window", "0_6h", "6_24h"}
OFFICIAL_OBSERVATION_SOURCES = {"METAR_ASOS_applicable", "NWS_applicable"}


@dataclass(frozen=True)
class WeatherObservationEligibility:
    market_id: str
    question: str
    eligible: bool
    blockers: List[str]
    eligibility_reason: str
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
    source_applicability: List[str] = field(default_factory=list)
    alpha_lanes: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)
    route_reasons: List[str] = field(default_factory=list)
    research_score: float = 0.0
    schema_version: str = WEATHER_OBSERVATION_ELIGIBILITY_SCHEMA_VERSION
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["blocker_records"] = blockers_to_records(self.blockers)
        payload["blocker_summary"] = blocker_summary(self.blockers)
        return payload


class WeatherObservationEligibilityAuditor:
    """Build explicit observation-lag eligibility records for routed markets."""

    def evaluate_routed(self, row: WeatherRoutedMarket) -> WeatherObservationEligibility:
        classification = row.classification or {}
        blockers: List[str] = []

        contract_type = _text(classification.get("contract_type"))
        metric = _text(classification.get("metric"))
        operator = _text(classification.get("operator"))
        threshold = _optional_float(classification.get("threshold"))
        upper_threshold = _optional_float(classification.get("upper_threshold"))
        target_date = _text(classification.get("target_date"))
        station_id = _text(classification.get("station_id")).upper()
        horizon_bucket = _text(classification.get("horizon_bucket"))
        hours_to_end = _finite_float(classification.get("hours_to_end"), 999.0)
        alpha_lanes = _text_list(classification.get("alpha_lanes"))
        sources = _text_list(classification.get("source_applicability"))
        classification_blockers = _text_list(classification.get("blockers"))

        if LANE_OBSERVATION_LAG not in set(alpha_lanes):
            blockers.append("observation_lane_missing")
        if contract_type not in SUPPORTED_OBSERVATION_CONTRACTS:
            blockers.append(f"unsupported_market_type:{contract_type or 'unknown'}")
        if metric not in SUPPORTED_OBSERVATION_METRICS:
            blockers.append(f"unsupported_observation_metric:{metric or 'unknown'}")
        if operator not in {"above", "below", "between"}:
            blockers.append(f"unsupported_observation_operator:{operator or 'unknown'}")
        if threshold is None:
            blockers.append("missing_threshold_rule")
        if operator == "between" and upper_threshold is None:
            blockers.append("missing_upper_threshold_rule")
        if not target_date:
            blockers.append("missing_target_date")
        if not station_id:
            blockers.append("missing_station")
        if station_id and not (OFFICIAL_OBSERVATION_SOURCES & set(sources)):
            blockers.append("missing_observation_source")
        if hours_to_end <= 0:
            blockers.append("closed_or_expired_window")
        elif horizon_bucket not in NEAR_OBSERVATION_HORIZONS:
            blockers.append(f"future_window_not_observation_relevant:{horizon_bucket or 'unknown'}")

        for blocker in classification_blockers:
            if blocker in {"unparsed_location", "ambiguous_station_mapping", "station_mapping_missing"}:
                blockers.append(f"observation_context_blocked:{blocker}")

        blockers = sorted(set(blockers))
        eligible = not blockers
        quality_flags = _text_list(classification.get("quality_flags"))
        if eligible:
            quality_flags.append("observation_pool_eligible")
        quality_flags.append("observation_forensics_record")

        return WeatherObservationEligibility(
            market_id=_text(row.market_id),
            question=_text(row.question),
            eligible=eligible,
            blockers=blockers,
            eligibility_reason="eligible_for_observation_lag" if eligible else "blocked_before_observation_pool",
            contract_type=contract_type,
            metric=metric,
            operator=operator,
            threshold=threshold,
            upper_threshold=upper_threshold,
            threshold_unit=_text(classification.get("threshold_unit")),
            target_date=target_date,
            horizon_bucket=horizon_bucket,
            hours_to_end=hours_to_end,
            station_id=station_id,
            station_type=_text(classification.get("station_type")),
            region=_text(classification.get("region")),
            source_applicability=sources,
            alpha_lanes=alpha_lanes,
            quality_flags=sorted(set(quality_flags)),
            route_reasons=_text_list(getattr(row, "route_reasons", [])),
            research_score=_finite_float(getattr(row, "research_score", 0.0), 0.0),
        )

    def audit_routed(self, routed: Iterable[WeatherRoutedMarket]) -> Dict[str, Any]:
        records = [self.evaluate_routed(row).to_dict() for row in routed]
        blocker_counts = Counter(blocker for record in records for blocker in record.get("blockers", []))
        eligible_market_ids = [record["market_id"] for record in records if record.get("eligible")]
        return {
            "schema_version": WEATHER_OBSERVATION_ELIGIBILITY_SCHEMA_VERSION,
            "routed_market_count": len(records),
            "eligible_count": len(eligible_market_ids),
            "ineligible_count": len(records) - len(eligible_market_ids),
            "eligible_market_ids": eligible_market_ids,
            "blocker_counts": dict(sorted(blocker_counts.items())),
            "top_blockers": [
                {"blocker": str(blocker), "count": int(count)}
                for blocker, count in blocker_counts.most_common(10)
            ],
            "blocker_summary": blocker_summary(blocker_counts.keys()),
            "zero_eligible_proof": _zero_eligible_proof(records, blocker_counts),
            "records": records,
        }


def _zero_eligible_proof(records: List[Dict[str, Any]], blocker_counts: Counter[str]) -> Dict[str, Any]:
    if any(record.get("eligible") for record in records):
        return {}
    return {
        "status": "proved_zero_observation_pool" if records else "no_routed_markets",
        "routed_market_count": len(records),
        "distinct_blockers": len(blocker_counts),
        "top_blockers": [
            {"blocker": str(blocker), "count": int(count)}
            for blocker, count in blocker_counts.most_common(10)
        ],
        "all_markets_have_eligibility_record": True,
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _text_list(value: Any) -> List[str]:
    if isinstance(value, (list, tuple, set)):
        return sorted({str(item).strip() for item in value if str(item or "").strip()})
    text = _text(value)
    return [text] if text else []


def _optional_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _finite_float(value: Any, default: float) -> float:
    parsed = _optional_float(value)
    return default if parsed is None else parsed
