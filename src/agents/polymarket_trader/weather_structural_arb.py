"""
Structural bucket-arbitrage math for Polymarket weather research.

This module only emits candidates. Execution still needs all-leg fill checks,
fees, risk limits, and the normal preflight/live gates.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class WeatherBucket:
    market_id: str
    question: str
    lower: float
    upper: float
    yes_price: float
    no_price: float
    yes_token_id: str = ""
    no_token_id: str = ""
    liquidity: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WeatherStructuralArbCandidate:
    arb_type: str
    edge_percent: float
    worst_case_payout: float
    total_cost: float
    leg_count: int
    recommended_trades: List[Dict[str, Any]]
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)

    @property
    def accepted_for_research(self) -> bool:
        return self.edge_percent > 0 and not self.blockers

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["accepted_for_research"] = self.accepted_for_research
        return payload


class WeatherStructuralArbEngine:
    def __init__(
        self,
        fee_rate: float = 0.01,
        min_edge_percent: float = 1.0,
        min_liquidity: float = 0.0,
    ):
        self.fee_rate = float(fee_rate)
        self.min_edge_percent = float(min_edge_percent)
        self.min_liquidity = float(min_liquidity)

    def detect(
        self,
        buckets: Iterable[WeatherBucket],
        exhaustive: bool = False,
    ) -> List[WeatherStructuralArbCandidate]:
        clean = [bucket for bucket in buckets if self._bucket_is_valid(bucket)]
        if len(clean) < 2:
            return []
        candidates = [self.detect_no_basket(clean)]
        if exhaustive:
            candidates.append(self.detect_yes_basket(clean))
        return [
            candidate
            for candidate in candidates
            if candidate is not None and candidate.edge_percent >= self.min_edge_percent
        ]

    def detect_yes_basket(self, buckets: List[WeatherBucket]) -> Optional[WeatherStructuralArbCandidate]:
        if not buckets:
            return None
        total_cost = sum(bucket.yes_price for bucket in buckets)
        fee_buffer = total_cost * self.fee_rate
        edge = (1.0 - total_cost - fee_buffer) * 100.0
        blockers = self._shared_blockers(buckets)
        return WeatherStructuralArbCandidate(
            arb_type="weather_exhaustive_yes_basket",
            edge_percent=round(edge, 4),
            worst_case_payout=1.0,
            total_cost=round(total_cost + fee_buffer, 4),
            leg_count=len(buckets),
            recommended_trades=[
                {
                    "action": "BUY",
                    "side": "YES",
                    "market_id": bucket.market_id,
                    "token_id": bucket.yes_token_id,
                    "price": round(bucket.yes_price, 4),
                    "reason": "Buy all YES buckets only when bucket set is exhaustive.",
                }
                for bucket in buckets
            ],
            blockers=blockers,
            quality_flags=["structural_arb_research_only", "requires_exhaustive_bucket_proof"],
        )

    def detect_no_basket(self, buckets: List[WeatherBucket]) -> Optional[WeatherStructuralArbCandidate]:
        if len(buckets) < 2:
            return None
        blockers = self._shared_blockers(buckets)
        if self._ranges_overlap(buckets):
            blockers.append("bucket_ranges_overlap")
        total_cost = sum(bucket.no_price for bucket in buckets)
        fee_buffer = total_cost * self.fee_rate
        worst_case_payout = float(len(buckets) - 1)
        edge = (worst_case_payout - total_cost - fee_buffer) * 100.0
        return WeatherStructuralArbCandidate(
            arb_type="weather_mutually_exclusive_no_basket",
            edge_percent=round(edge, 4),
            worst_case_payout=round(worst_case_payout, 4),
            total_cost=round(total_cost + fee_buffer, 4),
            leg_count=len(buckets),
            recommended_trades=[
                {
                    "action": "BUY",
                    "side": "NO",
                    "market_id": bucket.market_id,
                    "token_id": bucket.no_token_id,
                    "price": round(bucket.no_price, 4),
                    "reason": "Buy all NO buckets when at most one bucket can resolve YES.",
                }
                for bucket in buckets
            ],
            blockers=blockers,
            quality_flags=["structural_arb_research_only", "requires_all_leg_execution"],
        )

    def _shared_blockers(self, buckets: List[WeatherBucket]) -> List[str]:
        blockers: List[str] = []
        if any(bucket.liquidity < self.min_liquidity for bucket in buckets):
            blockers.append("bucket_liquidity_below_minimum")
        if any(bucket.yes_price <= 0 or bucket.no_price <= 0 for bucket in buckets):
            blockers.append("bucket_price_missing")
        return blockers

    @staticmethod
    def _ranges_overlap(buckets: List[WeatherBucket]) -> bool:
        ordered = sorted(buckets, key=lambda bucket: (bucket.lower, bucket.upper))
        for left, right in zip(ordered, ordered[1:]):
            if left.upper > right.lower:
                return True
        return False

    @staticmethod
    def _bucket_is_valid(bucket: WeatherBucket) -> bool:
        values = [bucket.lower, bucket.upper, bucket.yes_price, bucket.no_price]
        return (
            bool(bucket.market_id)
            and all(math.isfinite(float(value)) for value in values)
            and bucket.lower < bucket.upper
            and 0 < bucket.yes_price < 1
            and 0 < bucket.no_price < 1
        )
