"""Orderbook fetch planning for weather edge evidence.

The planner spends scarce orderbook requests on evidence-rich markets before
any live-trading path is considered.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .models import CLIMarket
from .weather_market_type_classifier import (
    LANE_HRRR_NBM_RUN_SHOCK,
    LANE_LADDER_CONSISTENCY,
    LANE_OBSERVATION_LAG,
    LANE_OPEN_METEO_CONTROL,
    LANE_STATION_SOURCE_MISMATCH,
)
from .weather_market_universe_router import WeatherRoutedMarket
from .weather_threshold_state import WeatherThresholdStateEvaluator


ORDERBOOK_FETCH_PLAN_SCHEMA_VERSION = "weather_orderbook_fetch_plan_v1"


@dataclass(frozen=True)
class WeatherOrderbookFetchJob:
    priority: str
    lane: str
    group_key: str
    market_ids: List[str]
    expected_evidence_value: float
    reason: str
    complete_group: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def market_count(self) -> int:
        return len([market_id for market_id in self.market_ids if market_id])

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["market_count"] = self.market_count
        return payload


@dataclass(frozen=True)
class WeatherOrderbookFetchPlan:
    orderbook_limit: int
    candidate_job_count: int
    selected_jobs: List[WeatherOrderbookFetchJob]
    skipped_jobs: List[WeatherOrderbookFetchJob] = field(default_factory=list)
    skipped_reason_counts: Dict[str, int] = field(default_factory=dict)
    schema_version: str = ORDERBOOK_FETCH_PLAN_SCHEMA_VERSION

    @property
    def selected_market_ids(self) -> List[str]:
        selected: List[str] = []
        seen: set[str] = set()
        for job in self.selected_jobs:
            for market_id in job.market_ids:
                if market_id and market_id not in seen:
                    selected.append(market_id)
                    seen.add(market_id)
        return selected

    def to_dict(self) -> Dict[str, Any]:
        selected_priority_counts = Counter(job.priority for job in self.selected_jobs)
        selected_lane_counts = Counter(job.lane for job in self.selected_jobs)
        return {
            "schema_version": self.schema_version,
            "orderbook_limit": self.orderbook_limit,
            "candidate_job_count": self.candidate_job_count,
            "selected_job_count": len(self.selected_jobs),
            "selected_market_count": len(self.selected_market_ids),
            "selected_market_ids": self.selected_market_ids,
            "selected_priority_counts": dict(sorted(selected_priority_counts.items())),
            "selected_lane_counts": dict(sorted(selected_lane_counts.items())),
            "skipped_job_count": len(self.skipped_jobs),
            "skipped_reason_counts": dict(sorted(self.skipped_reason_counts.items())),
            "top_selected_jobs": [job.to_dict() for job in self.selected_jobs[:25]],
            "top_skipped_jobs": [job.to_dict() for job in self.skipped_jobs[:25]],
        }


class WeatherOrderbookFetchPlanner:
    """Prioritize orderbook fetches across weather alpha lanes."""

    def __init__(
        self,
        *,
        threshold_evaluator: Optional[WeatherThresholdStateEvaluator] = None,
        known_probability_floor: float = 0.90,
        fee_slippage_buffer: float = 0.02,
    ):
        self.threshold_evaluator = threshold_evaluator or WeatherThresholdStateEvaluator()
        self.known_probability_floor = max(0.5, min(1.0, float(known_probability_floor)))
        self.fee_slippage_buffer = max(0.0, float(fee_slippage_buffer))

    def plan_routed_lane_jobs(
        self,
        routed: Iterable[WeatherRoutedMarket],
        *,
        orderbook_limit: int,
        per_group_limit: Optional[int] = None,
    ) -> WeatherOrderbookFetchPlan:
        jobs: List[WeatherOrderbookFetchJob] = []
        for row in routed:
            job = self._routed_job(row)
            if job is not None:
                jobs.append(job)
        return self.select_jobs(jobs, orderbook_limit=orderbook_limit, per_group_limit=per_group_limit)

    def plan_observation_lag(
        self,
        routed: Iterable[WeatherRoutedMarket],
        *,
        station_states: Mapping[str, Dict[str, Any]],
        market_by_id: Optional[Mapping[str, CLIMarket]] = None,
        orderbook_limit: int,
        per_group_limit: int = 3,
        now: Optional[datetime] = None,
    ) -> WeatherOrderbookFetchPlan:
        jobs: List[WeatherOrderbookFetchJob] = []
        for row in routed:
            lanes = set(str(item) for item in row.classification.get("alpha_lanes", []))
            if LANE_OBSERVATION_LAG not in lanes:
                continue
            job = self._observation_job(
                row,
                station_states=station_states,
                market_by_id=market_by_id or {},
                now=now,
            )
            if job is not None:
                jobs.append(job)
        return self.select_jobs(jobs, orderbook_limit=orderbook_limit, per_group_limit=per_group_limit)

    def select_jobs(
        self,
        jobs: Sequence[WeatherOrderbookFetchJob],
        *,
        orderbook_limit: int,
        per_group_limit: Optional[int] = None,
    ) -> WeatherOrderbookFetchPlan:
        limit = max(0, int(orderbook_limit or 0))
        ordered = sorted(
            jobs,
            key=lambda job: (
                self._priority_rank(job.priority),
                -float(job.expected_evidence_value),
                job.market_count,
                job.group_key,
            ),
        )
        selected: List[WeatherOrderbookFetchJob] = []
        skipped: List[WeatherOrderbookFetchJob] = []
        skipped_reasons: Counter[str] = Counter()
        used_market_ids: set[str] = set()
        group_counts: Counter[str] = Counter()

        for job in ordered:
            if limit <= 0:
                skipped.append(job)
                skipped_reasons["budget_exhausted"] += 1
                continue
            if per_group_limit is not None and group_counts[job.group_key] >= max(1, int(per_group_limit)):
                skipped.append(job)
                skipped_reasons["per_group_limit"] += 1
                continue
            job_market_ids = [market_id for market_id in job.market_ids if market_id]
            new_market_ids = [market_id for market_id in job_market_ids if market_id not in used_market_ids]
            if not new_market_ids:
                skipped.append(job)
                skipped_reasons["duplicate_markets"] += 1
                continue
            if len(new_market_ids) > limit:
                skipped.append(job)
                skipped_reasons["insufficient_remaining_budget"] += 1
                continue
            selected.append(job)
            used_market_ids.update(new_market_ids)
            group_counts[job.group_key] += 1
            limit -= len(new_market_ids)

        return WeatherOrderbookFetchPlan(
            orderbook_limit=max(0, int(orderbook_limit or 0)),
            candidate_job_count=len(jobs),
            selected_jobs=selected,
            skipped_jobs=skipped,
            skipped_reason_counts=dict(skipped_reasons),
        )

    def _observation_job(
        self,
        row: WeatherRoutedMarket,
        *,
        station_states: Mapping[str, Dict[str, Any]],
        market_by_id: Mapping[str, CLIMarket],
        now: Optional[datetime],
    ) -> Optional[WeatherOrderbookFetchJob]:
        classification = row.classification
        station_id = str(classification.get("station_id") or "").upper()
        station_state = dict(station_states.get(station_id) or {"station_id": station_id, "blockers": ["station_state_missing"]})
        market = market_by_id.get(row.market_id)
        threshold_state = self.threshold_evaluator.evaluate(
            metric=str(classification.get("metric") or ""),
            operator=str(classification.get("operator") or ""),
            threshold=_optional_float(classification.get("threshold")),
            upper_threshold=_optional_float(classification.get("upper_threshold")),
            station_state=station_state,
            market_end=getattr(market, "end_date", None),
            now=now,
        )
        threshold_dict = threshold_state.to_dict()
        p_yes = _optional_float(threshold_dict.get("p_yes"))
        side = str(threshold_dict.get("recommended_side") or "")
        selected_probability = None
        if p_yes is not None and side:
            selected_probability = p_yes if side == "YES" else 1.0 - p_yes
        proxy_price = self._proxy_price(market, side)
        proxy_edge = None
        if selected_probability is not None and proxy_price is not None:
            proxy_edge = selected_probability - proxy_price - self.fee_slippage_buffer

        if selected_probability is not None and selected_probability >= self.known_probability_floor:
            priority = "P0_known_outcome_observation_lag"
            reason = "official_observation_threshold_known_or_near_known"
            base = 1000.0
        else:
            priority = "P2_observation_lag_watchlist"
            reason = "observation_lag_candidate_needs_threshold_confirmation"
            base = 300.0

        score = (
            base
            + self._horizon_score(str(classification.get("horizon_bucket") or ""))
            + self._operator_score(str(classification.get("operator") or ""))
            + self._liquidity_score(row.microstructure.get("liquidity"))
            + max(0.0, float(row.research_score or 0.0)) * 0.25
        )
        if selected_probability is not None:
            score += selected_probability * 100.0
        if proxy_edge is not None:
            score += max(-20.0, min(80.0, proxy_edge * 100.0))

        return WeatherOrderbookFetchJob(
            priority=priority,
            lane=LANE_OBSERVATION_LAG,
            group_key=self._selection_group(row),
            market_ids=[row.market_id],
            expected_evidence_value=round(score, 6),
            reason=reason,
            metadata={
                "market_id": row.market_id,
                "station_id": station_id,
                "metric": classification.get("metric", ""),
                "operator": classification.get("operator", ""),
                "threshold": classification.get("threshold"),
                "upper_threshold": classification.get("upper_threshold"),
                "target_date": classification.get("target_date", ""),
                "horizon_bucket": classification.get("horizon_bucket", ""),
                "expected_side": side,
                "selected_win_probability": round(selected_probability, 6) if selected_probability is not None else None,
                "proxy_price": round(proxy_price, 6) if proxy_price is not None else None,
                "proxy_edge_after_cost": round(proxy_edge, 6) if proxy_edge is not None else None,
                "threshold_state": threshold_dict,
                "station_observation_count": int(station_state.get("observation_count") or 0),
                "station_blockers": list(station_state.get("blockers", []) or []),
            },
        )

    def _routed_job(self, row: WeatherRoutedMarket) -> Optional[WeatherOrderbookFetchJob]:
        priority, lane, reason, base = self._routed_priority(row)
        if not priority:
            return None
        score = (
            base
            + self._horizon_score(str(row.classification.get("horizon_bucket") or ""))
            + self._liquidity_score(row.microstructure.get("liquidity"))
            + max(0.0, float(row.research_score or 0.0)) * 0.25
        )
        return WeatherOrderbookFetchJob(
            priority=priority,
            lane=lane,
            group_key=self._selection_group(row),
            market_ids=[row.market_id],
            expected_evidence_value=round(score, 6),
            reason=reason,
            metadata={
                "horizon_bucket": row.classification.get("horizon_bucket", ""),
                "operator": row.classification.get("operator", ""),
                "station_id": row.classification.get("station_id", ""),
                "alpha_lanes": list(row.classification.get("alpha_lanes", []) or []),
                "research_score": row.research_score,
            },
        )

    @staticmethod
    def _routed_priority(row: WeatherRoutedMarket) -> tuple[str, str, str, float]:
        lanes = set(str(item) for item in row.classification.get("alpha_lanes", []))
        horizon = str(row.classification.get("horizon_bucket") or "")
        near_resolution = horizon in {"already_in_window", "0_6h", "6_24h"}
        if LANE_OBSERVATION_LAG in lanes and near_resolution:
            return "P0_observation_lag_precheck", LANE_OBSERVATION_LAG, "near_resolution_station_threshold", 900.0
        if LANE_LADDER_CONSISTENCY in lanes:
            return "P1_ladder_consistency", LANE_LADDER_CONSISTENCY, "threshold_ladder_or_group_member", 700.0
        if LANE_HRRR_NBM_RUN_SHOCK in lanes:
            return "P2_hrrr_nbm_run_shock", LANE_HRRR_NBM_RUN_SHOCK, "high_resolution_forecast_applicable", 500.0
        if LANE_STATION_SOURCE_MISMATCH in lanes:
            return "P3_station_source_mismatch", LANE_STATION_SOURCE_MISMATCH, "station_or_source_resolution_mismatch", 300.0
        if LANE_OPEN_METEO_CONTROL in lanes:
            return "P4_open_meteo_control", LANE_OPEN_METEO_CONTROL, "baseline_control_market", 100.0
        return "", "", "", 0.0

    @staticmethod
    def _selection_group(row: WeatherRoutedMarket) -> str:
        classification = row.classification
        event = str(classification.get("event_slug") or "").strip()
        station = str(classification.get("station_id") or "").strip().upper()
        location = str(classification.get("location_name") or "").strip().lower()
        metric = str(classification.get("metric") or "").strip()
        target_date = str(classification.get("target_date") or "").strip()
        operator = str(classification.get("operator") or "").strip()
        return event or "|".join([station, location, metric, target_date, operator])

    @staticmethod
    def _proxy_price(market: Optional[CLIMarket], side: str) -> Optional[float]:
        if market is None or side not in {"YES", "NO"}:
            return None
        key = "yes_price" if side == "YES" else "no_price"
        return _optional_probability(getattr(market, key, None))

    @staticmethod
    def _priority_rank(priority: str) -> int:
        prefix = str(priority or "")[:2].upper()
        return {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}.get(prefix, 9)

    @staticmethod
    def _horizon_score(horizon: str) -> float:
        return {
            "already_in_window": 80.0,
            "0_6h": 60.0,
            "6_24h": 35.0,
            "24_72h": 15.0,
        }.get(str(horizon or ""), 0.0)

    @staticmethod
    def _operator_score(operator: str) -> float:
        if operator in {"above", "below"}:
            return 20.0
        if operator == "between":
            return 8.0
        return 0.0

    @staticmethod
    def _liquidity_score(liquidity: Any) -> float:
        value = _optional_float(liquidity) or 0.0
        if value <= 0:
            return 0.0
        return min(60.0, math.log10(max(10.0, value)) * 15.0)


def _optional_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _optional_probability(value: Any) -> Optional[float]:
    parsed = _optional_float(value)
    if parsed is None or parsed < 0 or parsed > 1:
        return None
    return parsed
