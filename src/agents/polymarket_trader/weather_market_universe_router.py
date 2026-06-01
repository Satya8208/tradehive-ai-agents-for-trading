"""
Route the full Polymarket weather universe into alpha research lanes.

The router combines pure market classification with optional orderbook tape.
It is not a trade gate. It answers: which markets are worth deeper alpha work?
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .models import CLIMarket
from .weather_market_tape import WeatherMarketTapeSnapshot
from .weather_market_type_classifier import (
    LANE_HRRR_NBM_RUN_SHOCK,
    LANE_LADDER_CONSISTENCY,
    LANE_OBSERVATION_LAG,
    LANE_OPEN_METEO_CONTROL,
    LANE_STATION_SOURCE_MISMATCH,
    REGION_CONUS,
    WeatherMarketClassification,
    WeatherMarketTypeClassifier,
)


WEATHER_ROUTED_MARKET_SCHEMA_VERSION = "weather_routed_market_v1"


@dataclass(frozen=True)
class WeatherMarketMicrostructure:
    orderbook_available: bool
    executable_price_source: str
    yes_ask: Optional[float] = None
    no_ask: Optional[float] = None
    yes_bid: Optional[float] = None
    no_bid: Optional[float] = None
    spread: Optional[float] = None
    min_ask_depth_usd: float = 0.0
    yes_ask_depth_usd: float = 0.0
    no_ask_depth_usd: float = 0.0
    liquidity: float = 0.0
    volume_24h: float = 0.0
    tight_spread: bool = False
    depth_ok: bool = False
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WeatherRoutedMarket:
    market_id: str
    question: str
    classification: Dict[str, Any]
    microstructure: Dict[str, Any]
    research_score: float
    route_reasons: List[str]
    schema_version: str = WEATHER_ROUTED_MARKET_SCHEMA_VERSION
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherMarketUniverseRouter:
    """Classify and score the full weather universe for research sampling."""

    def __init__(
        self,
        classifier: Optional[WeatherMarketTypeClassifier] = None,
        min_depth_usd: float = 25.0,
        tight_spread_threshold: float = 0.10,
    ):
        self.classifier = classifier or WeatherMarketTypeClassifier()
        self.min_depth_usd = float(min_depth_usd)
        self.tight_spread_threshold = float(tight_spread_threshold)

    def route_markets(
        self,
        markets: Iterable[CLIMarket],
        *,
        tape_by_market: Optional[Dict[str, WeatherMarketTapeSnapshot | Dict[str, Any]]] = None,
        now: Optional[datetime] = None,
    ) -> List[WeatherRoutedMarket]:
        routed: List[WeatherRoutedMarket] = []
        tape_by_market = tape_by_market or {}
        for market in markets:
            classification = self.classifier.classify(market, now=now)
            tape = tape_by_market.get(str(getattr(market, "condition_id", "") or ""))
            microstructure = self._microstructure(market, tape)
            score, reasons = self._research_score(classification, microstructure)
            routed.append(
                WeatherRoutedMarket(
                    market_id=classification.market_id,
                    question=classification.question,
                    classification=classification.to_dict(),
                    microstructure=microstructure.to_dict(),
                    research_score=round(score, 4),
                    route_reasons=sorted(set(reasons)),
                )
            )
        routed.sort(key=lambda item: item.research_score, reverse=True)
        return routed

    def summarize(self, routed: Iterable[WeatherRoutedMarket]) -> Dict[str, Any]:
        rows = list(routed)
        lane_counts = Counter()
        source_counts = Counter()
        contract_counts = Counter()
        region_counts = Counter()
        horizon_counts = Counter()
        orderbook_available = 0
        for row in rows:
            classification = row.classification
            microstructure = row.microstructure
            lane_counts.update(classification.get("alpha_lanes", []))
            source_counts.update(classification.get("source_applicability", []))
            contract_counts[str(classification.get("contract_type") or "unknown")] += 1
            region_counts[str(classification.get("region") or "unknown")] += 1
            horizon_counts[str(classification.get("horizon_bucket") or "unknown")] += 1
            if bool(microstructure.get("orderbook_available")):
                orderbook_available += 1

        return {
            "routed_count": len(rows),
            "alpha_lane_counts": dict(sorted(lane_counts.items())),
            "source_applicability_counts": dict(sorted(source_counts.items())),
            "contract_type_counts": dict(sorted(contract_counts.items())),
            "region_counts": dict(sorted(region_counts.items())),
            "horizon_counts": dict(sorted(horizon_counts.items())),
            "orderbook_coverage": {
                "orderbook_available": orderbook_available,
                "routed_count": len(rows),
                "coverage_ratio": round(orderbook_available / len(rows), 4) if rows else 0.0,
            },
        }

    def summarize_by_lane(self, routed: Iterable[WeatherRoutedMarket]) -> Dict[str, Any]:
        buckets: Dict[str, List[WeatherRoutedMarket]] = defaultdict(list)
        for row in routed:
            for lane in row.classification.get("alpha_lanes", []):
                buckets[str(lane)].append(row)
        return {
            lane: {
                "count": len(rows),
                "top_market_ids": [row.market_id for row in sorted(rows, key=lambda item: item.research_score, reverse=True)[:10]],
            }
            for lane, rows in sorted(buckets.items())
        }

    def _microstructure(
        self,
        market: CLIMarket,
        tape: Optional[WeatherMarketTapeSnapshot | Dict[str, Any]],
    ) -> WeatherMarketMicrostructure:
        tape_dict = tape.to_dict() if hasattr(tape, "to_dict") else dict(tape or {})
        liquidity = _finite_float(tape_dict.get("liquidity", getattr(market, "liquidity", 0.0)))
        volume_24h = _finite_float(tape_dict.get("volume_24h", getattr(market, "volume_24h", 0.0)))
        spread = _optional_float(tape_dict.get("spread", getattr(market, "spread", None)))
        executable_source = str(tape_dict.get("executable_price_source") or "scan_only")

        yes_book = tape_dict.get("yes_book", {}) if isinstance(tape_dict.get("yes_book", {}), dict) else {}
        no_book = tape_dict.get("no_book", {}) if isinstance(tape_dict.get("no_book", {}), dict) else {}
        yes_ask = _optional_float(tape_dict.get("executable_yes_price") or yes_book.get("best_ask"))
        no_ask = _optional_float(tape_dict.get("executable_no_price") or no_book.get("best_ask"))
        yes_bid = _optional_float(yes_book.get("best_bid"))
        no_bid = _optional_float(no_book.get("best_bid"))
        yes_depth = _finite_float(yes_book.get("ask_depth_usd"))
        no_depth = _finite_float(no_book.get("ask_depth_usd"))
        if yes_depth <= 0 and yes_ask is not None:
            yes_depth = liquidity
        if no_depth <= 0 and no_ask is not None:
            no_depth = liquidity
        min_depth = min(yes_depth, no_depth) if yes_depth > 0 and no_depth > 0 else max(yes_depth, no_depth)
        orderbook_available = executable_source in {"orderbook_best_ask", "mixed_side_sources"} and (
            yes_ask is not None or no_ask is not None
        )

        if spread is None:
            yes_price = _optional_float(getattr(market, "yes_price", None))
            no_price = _optional_float(getattr(market, "no_price", None))
            if yes_price is not None and no_price is not None:
                spread = max(0.0, yes_price + no_price - 1.0)

        blockers: List[str] = []
        quality_flags: List[str] = []
        if not orderbook_available:
            blockers.append("orderbook_not_available_for_route")
        else:
            quality_flags.append("orderbook_available")
        if min_depth < self.min_depth_usd:
            blockers.append("depth_below_research_floor")
        else:
            quality_flags.append("depth_ok")
        tight_spread = spread is not None and spread <= self.tight_spread_threshold
        if tight_spread:
            quality_flags.append("tight_spread")

        return WeatherMarketMicrostructure(
            orderbook_available=orderbook_available,
            executable_price_source=executable_source,
            yes_ask=yes_ask,
            no_ask=no_ask,
            yes_bid=yes_bid,
            no_bid=no_bid,
            spread=spread,
            min_ask_depth_usd=round(min_depth, 4),
            yes_ask_depth_usd=round(yes_depth, 4),
            no_ask_depth_usd=round(no_depth, 4),
            liquidity=round(liquidity, 4),
            volume_24h=round(volume_24h, 4),
            tight_spread=tight_spread,
            depth_ok=min_depth >= self.min_depth_usd,
            blockers=sorted(set(blockers)),
            quality_flags=sorted(set(quality_flags)),
        )

    def _research_score(
        self,
        classification: WeatherMarketClassification,
        microstructure: WeatherMarketMicrostructure,
    ) -> tuple[float, List[str]]:
        score = 0.0
        reasons: List[str] = []
        lanes = set(classification.alpha_lanes)
        if LANE_OBSERVATION_LAG in lanes:
            score += 45.0
            reasons.append("lane:observation_lag")
        if LANE_HRRR_NBM_RUN_SHOCK in lanes:
            score += 30.0
            reasons.append("lane:hrrr_nbm_run_shock")
        if LANE_STATION_SOURCE_MISMATCH in lanes:
            score += 20.0
            reasons.append("lane:station_source_mismatch")
        if LANE_LADDER_CONSISTENCY in lanes:
            score += 18.0
            reasons.append("lane:ladder_consistency")
        if LANE_OPEN_METEO_CONTROL in lanes and len(lanes) == 1:
            score -= 15.0
            reasons.append("control:open_meteo_only")

        if classification.region == REGION_CONUS:
            score += 8.0
            reasons.append("region:conus")
        if classification.horizon_bucket == "already_in_window":
            score += 14.0
            reasons.append("horizon:already_in_window")
        elif classification.horizon_bucket == "0_6h":
            score += 12.0
            reasons.append("horizon:0_6h")
        elif classification.horizon_bucket == "6_24h":
            score += 8.0
            reasons.append("horizon:6_24h")
        elif classification.horizon_bucket == "24_72h":
            score += 4.0
            reasons.append("horizon:24_72h")

        if microstructure.orderbook_available:
            score += 10.0
            reasons.append("microstructure:orderbook")
        if microstructure.tight_spread:
            score += 6.0
            reasons.append("microstructure:tight_spread")
        if microstructure.depth_ok:
            score += 4.0
            reasons.append("microstructure:depth_ok")
        if microstructure.liquidity > 0:
            score += min(8.0, math.log10(max(10.0, microstructure.liquidity)) * 2.0)
            reasons.append("microstructure:liquidity")
        if classification.blockers:
            score -= min(25.0, 5.0 * len(classification.blockers))
            reasons.append("classification:blockers")
        return max(0.0, score), reasons


def _optional_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _finite_float(value: Any, default: float = 0.0) -> float:
    parsed = _optional_float(value)
    return default if parsed is None else parsed
