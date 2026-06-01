"""Depth-aware orderbook fill simulation for weather research.

The simulator is research-only. It turns captured orderbook levels into an
auditable estimate of what a paper order could have filled without granting
live execution permission.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional


ORDERBOOK_FILL_SCHEMA_VERSION = "weather_orderbook_fill_v1"


@dataclass(frozen=True)
class WeatherOrderbookLevel:
    price: float
    size: float
    notional_usd: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WeatherFillSimulation:
    side: str
    token_id: str
    requested_size_usd: float
    limit_price: Optional[float]
    status: str
    filled_notional_usd: float
    filled_shares: float
    average_price: Optional[float]
    worst_price: Optional[float]
    best_price: Optional[float]
    fill_ratio: float
    total_depth_usd_at_limit: float
    level_count_available: int
    level_count_consumed: int
    price_source: str
    schema_version: str = ORDERBOOK_FILL_SCHEMA_VERSION
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)
    consumed_levels: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def full_fill(self) -> bool:
        return self.status == "full"

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["full_fill"] = self.full_fill
        return payload


class WeatherOrderbookFillSimulator:
    """Simulate taker fills from captured ask levels."""

    def __init__(
        self,
        *,
        default_request_size_usd: float = 5.0,
        min_fill_ratio: float = 1.0,
        allow_best_ask_without_depth: bool = False,
    ):
        self.default_request_size_usd = max(0.0, float(default_request_size_usd))
        self.min_fill_ratio = max(0.0, min(1.0, float(min_fill_ratio)))
        self.allow_best_ask_without_depth = bool(allow_best_ask_without_depth)

    def simulate(
        self,
        tape: Any,
        side: str,
        *,
        requested_size_usd: Optional[float] = None,
        limit_price: Optional[float] = None,
    ) -> WeatherFillSimulation:
        tape_dict = tape.to_dict() if hasattr(tape, "to_dict") else dict(tape or {})
        side = str(side or "").upper()
        requested = self._positive_float(requested_size_usd, self.default_request_size_usd)
        if side not in {"YES", "NO"}:
            return self._empty(side, "", requested, limit_price, "invalid_side", ["fill_side_invalid"])

        token_id = str(tape_dict.get("yes_token_id" if side == "YES" else "no_token_id") or "")
        book_key = "yes_book" if side == "YES" else "no_book"
        price_key = "executable_yes_price" if side == "YES" else "executable_no_price"
        source_key = "executable_yes_price_source" if side == "YES" else "executable_no_price_source"
        price_source = str(tape_dict.get(source_key) or tape_dict.get("executable_price_source") or "")
        book = tape_dict.get(book_key, {})
        book = book if isinstance(book, dict) else {}
        levels = self._ask_levels(book)
        if not levels and self.allow_best_ask_without_depth:
            levels = self._best_ask_fallback(
                price=tape_dict.get(price_key) or book.get("best_ask"),
                requested_size_usd=requested,
            )

        if not tape_dict:
            return self._empty(side, token_id, requested, limit_price, "missing_tape", ["fill_tape_missing"])
        if not levels:
            status = str(book.get("status") or "missing_orderbook_levels")
            return self._empty(
                side,
                token_id,
                requested,
                limit_price,
                "no_depth",
                [f"fill_orderbook_{status}"],
                price_source=price_source,
            )

        clean_limit = self._optional_probability(limit_price)
        if clean_limit is None:
            clean_limit = levels[0].price
        available = [level for level in levels if level.price <= clean_limit + 1e-12]
        total_depth = sum(level.notional_usd for level in available)
        if not available or total_depth <= 0:
            return self._empty(
                side,
                token_id,
                requested,
                clean_limit,
                "no_depth_at_limit",
                ["fill_no_depth_at_limit"],
                price_source=price_source,
                level_count_available=len(levels),
            )

        remaining = requested
        filled_notional = 0.0
        filled_shares = 0.0
        consumed: List[Dict[str, Any]] = []
        for level in available:
            if remaining <= 1e-12:
                break
            spend = min(remaining, level.notional_usd)
            shares = spend / level.price if level.price > 0 else 0.0
            filled_notional += spend
            filled_shares += shares
            remaining -= spend
            consumed.append(
                {
                    "price": round(level.price, 6),
                    "size": round(shares, 6),
                    "notional_usd": round(spend, 6),
                }
            )

        average = filled_notional / filled_shares if filled_shares > 0 else None
        ratio = filled_notional / requested if requested > 0 else 1.0
        blockers: List[str] = []
        flags = ["orderbook_depth_simulated"]
        status = "full" if ratio + 1e-12 >= self.min_fill_ratio else "partial"
        if status != "full":
            blockers.append("fill_partial_below_requested_size")
        if price_source != "orderbook_best_ask":
            flags.append(f"price_source:{price_source or 'missing'}")
        return WeatherFillSimulation(
            side=side,
            token_id=token_id,
            requested_size_usd=round(requested, 6),
            limit_price=round(clean_limit, 6),
            status=status,
            filled_notional_usd=round(filled_notional, 6),
            filled_shares=round(filled_shares, 6),
            average_price=round(average, 6) if average is not None else None,
            worst_price=round(max(level["price"] for level in consumed), 6) if consumed else None,
            best_price=round(levels[0].price, 6),
            fill_ratio=round(min(1.0, ratio), 6),
            total_depth_usd_at_limit=round(total_depth, 6),
            level_count_available=len(levels),
            level_count_consumed=len(consumed),
            price_source=price_source,
            blockers=blockers,
            quality_flags=flags,
            consumed_levels=consumed,
        )

    @classmethod
    def summarize(cls, simulations: Iterable[WeatherFillSimulation | Dict[str, Any]]) -> Dict[str, Any]:
        rows = [row.to_dict() if hasattr(row, "to_dict") else dict(row) for row in simulations]
        total = len(rows)
        full = sum(1 for row in rows if row.get("status") == "full")
        partial = sum(1 for row in rows if row.get("status") == "partial")
        no_depth = sum(1 for row in rows if row.get("status") in {"no_depth", "no_depth_at_limit", "missing_tape"})
        requested = sum(cls._float(row.get("requested_size_usd")) or 0.0 for row in rows)
        filled = sum(cls._float(row.get("filled_notional_usd")) or 0.0 for row in rows)
        return {
            "schema_version": "weather_orderbook_fill_coverage_v1",
            "simulated_count": total,
            "full_fill_count": full,
            "partial_fill_count": partial,
            "no_depth_count": no_depth,
            "coverage_ratio": round(full / total, 4) if total else 0.0,
            "requested_notional_usd": round(requested, 6),
            "fillable_notional_usd": round(filled, 6),
            "notional_fill_ratio": round(filled / requested, 6) if requested > 0 else 0.0,
            "status_counts": {
                status: sum(1 for row in rows if row.get("status") == status)
                for status in sorted({str(row.get("status") or "missing") for row in rows})
            },
        }

    @classmethod
    def _ask_levels(cls, book: Dict[str, Any]) -> List[WeatherOrderbookLevel]:
        raw_levels = book.get("ask_levels")
        if not isinstance(raw_levels, list):
            raw_levels = book.get("asks")
        levels: List[WeatherOrderbookLevel] = []
        if isinstance(raw_levels, list):
            for raw in raw_levels:
                if not isinstance(raw, dict):
                    continue
                price = cls._optional_probability(raw.get("price"))
                size = cls._positive_float(raw.get("size"), 0.0)
                notional = cls._positive_float(raw.get("notional_usd"), 0.0)
                if price is None or price <= 0:
                    continue
                if notional <= 0 and size > 0:
                    notional = price * size
                if size <= 0 and notional > 0:
                    size = notional / price
                if size > 0 and notional > 0:
                    levels.append(WeatherOrderbookLevel(price=price, size=size, notional_usd=notional))

        if not levels:
            best = cls._optional_probability(book.get("best_ask"))
            depth_usd = cls._positive_float(book.get("ask_depth_usd"), 0.0)
            depth_shares = cls._positive_float(book.get("ask_depth_shares"), 0.0)
            if best is not None and best > 0:
                if depth_usd <= 0 and depth_shares > 0:
                    depth_usd = best * depth_shares
                if depth_shares <= 0 and depth_usd > 0:
                    depth_shares = depth_usd / best
                if depth_usd > 0 and depth_shares > 0:
                    levels.append(WeatherOrderbookLevel(price=best, size=depth_shares, notional_usd=depth_usd))
        return sorted(levels, key=lambda level: level.price)

    @classmethod
    def _best_ask_fallback(cls, price: Any, requested_size_usd: float) -> List[WeatherOrderbookLevel]:
        parsed = cls._optional_probability(price)
        if parsed is None or parsed <= 0 or requested_size_usd <= 0:
            return []
        return [
            WeatherOrderbookLevel(
                price=parsed,
                size=requested_size_usd / parsed,
                notional_usd=requested_size_usd,
            )
        ]

    @classmethod
    def _empty(
        cls,
        side: str,
        token_id: str,
        requested_size_usd: float,
        limit_price: Optional[float],
        status: str,
        blockers: List[str],
        *,
        price_source: str = "",
        level_count_available: int = 0,
    ) -> WeatherFillSimulation:
        return WeatherFillSimulation(
            side=side,
            token_id=token_id,
            requested_size_usd=round(requested_size_usd, 6),
            limit_price=round(limit_price, 6) if limit_price is not None else None,
            status=status,
            filled_notional_usd=0.0,
            filled_shares=0.0,
            average_price=None,
            worst_price=None,
            best_price=None,
            fill_ratio=0.0,
            total_depth_usd_at_limit=0.0,
            level_count_available=level_count_available,
            level_count_consumed=0,
            price_source=price_source,
            blockers=blockers,
            quality_flags=[],
            consumed_levels=[],
        )

    @staticmethod
    def _optional_probability(value: Any) -> Optional[float]:
        parsed = WeatherOrderbookFillSimulator._float(value)
        if parsed is None:
            return None
        return max(0.0, min(1.0, parsed))

    @staticmethod
    def _positive_float(value: Any, default: float) -> float:
        parsed = WeatherOrderbookFillSimulator._float(value)
        if parsed is None or parsed <= 0:
            return float(default)
        return parsed

    @staticmethod
    def _float(value: Any) -> Optional[float]:
        try:
            parsed = float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None
