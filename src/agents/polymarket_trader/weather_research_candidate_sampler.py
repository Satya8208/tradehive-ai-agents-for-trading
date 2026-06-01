"""
Stratified sampling for weather research candidates.

The sampler keeps research broad without weakening trade gates. It deliberately
returns exploratory candidates even when they are not paper-trade candidates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Set

from .weather_market_universe_router import WeatherRoutedMarket
from .weather_market_type_classifier import (
    LANE_HRRR_NBM_RUN_SHOCK,
    LANE_LADDER_CONSISTENCY,
    LANE_OBSERVATION_LAG,
    LANE_OPEN_METEO_CONTROL,
    LANE_STATION_SOURCE_MISMATCH,
)


WEATHER_RESEARCH_SAMPLE_SCHEMA_VERSION = "weather_research_candidate_sample_v1"


@dataclass(frozen=True)
class WeatherResearchCandidateBucket:
    bucket_id: str
    description: str
    market_ids: List[str]
    count: int
    schema_version: str = WEATHER_RESEARCH_SAMPLE_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WeatherResearchCandidateSample:
    buckets: List[WeatherResearchCandidateBucket]
    candidates: List[Dict[str, Any]]
    selected_market_ids: List[str]
    total_selected: int
    schema_version: str = WEATHER_RESEARCH_SAMPLE_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherResearchCandidateSampler:
    def __init__(
        self,
        per_bucket: int = 50,
        max_total: int = 250,
    ):
        self.per_bucket = max(1, int(per_bucket))
        self.max_total = max(1, int(max_total))

    def sample(self, routed: Iterable[WeatherRoutedMarket]) -> WeatherResearchCandidateSample:
        rows = list(routed)
        buckets = [
            self._bucket(
                "near_resolution_station",
                "CONUS station/gridpoint threshold markets where known-outcome observation lag can exist.",
                self._filter_lane(rows, LANE_OBSERVATION_LAG),
            ),
            self._bucket(
                "conus_hrrr_nbm",
                "CONUS markets where HRRR/NBM run-shock repricing can be measured.",
                self._filter_lane(rows, LANE_HRRR_NBM_RUN_SHOCK),
            ),
            self._bucket(
                "ladder_cross_threshold",
                "Threshold markets that can participate in monotonicity/ladder checks.",
                self._filter_lane(rows, LANE_LADDER_CONSISTENCY),
            ),
            self._bucket(
                "station_source_mismatch",
                "Markets with station/source/window mismatch potential.",
                self._filter_lane(rows, LANE_STATION_SOURCE_MISMATCH),
            ),
            self._bucket(
                "liquid_tight_spread",
                "Liquid, tight-spread markets useful for executable candidate supply.",
                [
                    row
                    for row in rows
                    if bool(row.microstructure.get("tight_spread"))
                    and float(row.microstructure.get("liquidity") or 0.0) > 0
                ],
            ),
            self._bucket(
                "open_meteo_controls",
                "Non-CONUS/Open-Meteo-only controls for baseline comparison, not alpha claims.",
                self._filter_lane(rows, LANE_OPEN_METEO_CONTROL),
            ),
        ]
        selected: List[WeatherRoutedMarket] = []
        seen: Set[str] = set()
        for bucket in buckets:
            id_set = set(bucket.market_ids)
            for row in rows:
                if row.market_id not in id_set or row.market_id in seen:
                    continue
                selected.append(row)
                seen.add(row.market_id)
                if len(selected) >= self.max_total:
                    break
            if len(selected) >= self.max_total:
                break

        return WeatherResearchCandidateSample(
            buckets=buckets,
            candidates=[row.to_dict() for row in selected],
            selected_market_ids=[row.market_id for row in selected],
            total_selected=len(selected),
        )

    def _bucket(
        self,
        bucket_id: str,
        description: str,
        rows: List[WeatherRoutedMarket],
    ) -> WeatherResearchCandidateBucket:
        ranked = sorted(rows, key=lambda row: row.research_score, reverse=True)[: self.per_bucket]
        return WeatherResearchCandidateBucket(
            bucket_id=bucket_id,
            description=description,
            market_ids=[row.market_id for row in ranked],
            count=len(ranked),
        )

    @staticmethod
    def _filter_lane(rows: List[WeatherRoutedMarket], lane: str) -> List[WeatherRoutedMarket]:
        return [
            row
            for row in rows
            if lane in set(str(item) for item in row.classification.get("alpha_lanes", []))
        ]
