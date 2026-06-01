"""
Market tape capture for Polymarket weather markets.

The tape is intentionally evidence-first: every snapshot records what was
actually observable from the market scan, and only upgrades to executable
order-book fields when an order book was explicitly fetched.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .config import PolymarketCLIConfig
from .models import CLIMarket


MARKET_TAPE_SCHEMA_VERSION = "weather_market_tape_v1"


@dataclass(frozen=True)
class WeatherBookSummary:
    token_id: str
    status: str
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    bid_depth_usd: Optional[float] = None
    ask_depth_usd: Optional[float] = None
    bid_depth_shares: Optional[float] = None
    ask_depth_shares: Optional[float] = None
    level_count_bid: int = 0
    level_count_ask: int = 0
    bid_levels: List[Dict[str, float]] = field(default_factory=list)
    ask_levels: List[Dict[str, float]] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WeatherMarketTapeSnapshot:
    market_id: str
    question: str
    captured_at: str
    schema_version: str = MARKET_TAPE_SCHEMA_VERSION
    symbol: str = "WEATHER"
    slug: str = ""
    event_slug: str = ""
    end_date: str = ""
    yes_token_id: str = ""
    no_token_id: str = ""
    yes_price: Optional[float] = None
    no_price: Optional[float] = None
    midpoint: Optional[float] = None
    spread: Optional[float] = None
    executable_yes_price: Optional[float] = None
    executable_no_price: Optional[float] = None
    executable_price_source: str = "unavailable"
    executable_yes_price_source: str = "unavailable"
    executable_no_price_source: str = "unavailable"
    yes_book: Dict[str, Any] = field(default_factory=dict)
    no_book: Dict[str, Any] = field(default_factory=dict)
    last_trade: Dict[str, Any] = field(default_factory=dict)
    market_status: str = "active"
    liquidity: float = 0.0
    volume_24h: float = 0.0
    quality_flags: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherMarketTapeCollector:
    """Capture market-price snapshots without inventing missing order-book data."""

    def __init__(self, config: PolymarketCLIConfig, cli: Optional[Any] = None):
        self.config = config
        self.cli = cli

    def snapshot_markets(
        self,
        markets: Iterable[CLIMarket],
        *,
        fetch_orderbook: Optional[bool] = None,
        fetch_last_trade: Optional[bool] = None,
        captured_at: Optional[datetime] = None,
    ) -> List[WeatherMarketTapeSnapshot]:
        return [
            self.snapshot_market(
                market,
                fetch_orderbook=fetch_orderbook,
                fetch_last_trade=fetch_last_trade,
                captured_at=captured_at,
            )
            for market in markets
        ]

    def snapshot_market(
        self,
        market: CLIMarket,
        *,
        fetch_orderbook: Optional[bool] = None,
        fetch_last_trade: Optional[bool] = None,
        captured_at: Optional[datetime] = None,
    ) -> WeatherMarketTapeSnapshot:
        captured = (captured_at or datetime.utcnow()).isoformat()
        yes_price = self._safe_probability(getattr(market, "yes_price", None))
        no_price = self._safe_probability(getattr(market, "no_price", None))
        if no_price is None and yes_price is not None:
            no_price = round(max(0.0, min(1.0, 1.0 - yes_price)), 6)

        quality_flags: List[str] = []
        blockers: List[str] = []
        midpoint = yes_price
        spread = self._safe_float(getattr(market, "spread", None))

        should_fetch_book = (
            bool(getattr(self.config, "weather_market_tape_fetch_orderbook", False))
            if fetch_orderbook is None
            else bool(fetch_orderbook)
        )
        should_fetch_last_trade = (
            bool(getattr(self.config, "weather_market_tape_fetch_last_trade", False))
            if fetch_last_trade is None
            else bool(fetch_last_trade)
        )

        yes_book = WeatherBookSummary(str(getattr(market, "yes_token_id", "") or ""), "not_queried")
        no_book = WeatherBookSummary(str(getattr(market, "no_token_id", "") or ""), "not_queried")
        executable_source = "unavailable"
        executable_yes: Optional[float] = None
        executable_no: Optional[float] = None
        executable_yes_source = "unavailable"
        executable_no_source = "unavailable"

        if should_fetch_book:
            if self.cli is None:
                quality_flags.append("orderbook_requested_without_cli")
            else:
                yes_book = self._fetch_book(str(getattr(market, "yes_token_id", "") or ""))
                no_book = self._fetch_book(str(getattr(market, "no_token_id", "") or ""))
                if yes_book.best_ask is not None:
                    executable_yes = yes_book.best_ask
                    executable_yes_source = "orderbook_best_ask"
                if no_book.best_ask is not None:
                    executable_no = no_book.best_ask
                    executable_no_source = "orderbook_best_ask"
                executable_source = (
                    executable_yes_source
                    if executable_yes_source == executable_no_source
                    else "mixed_side_sources"
                )
                if yes_book.best_bid is not None and yes_book.best_ask is not None:
                    midpoint = round((yes_book.best_bid + yes_book.best_ask) / 2.0, 6)
                    spread = round(max(0.0, yes_book.best_ask - yes_book.best_bid), 6)
                for side_name, summary in (("yes", yes_book), ("no", no_book)):
                    if summary.status != "ok":
                        quality_flags.append(f"{side_name}_orderbook_{summary.status}")
        else:
            quality_flags.append("orderbook_not_queried")

        last_trade: Dict[str, Any] = {}
        if should_fetch_last_trade and self.cli is not None:
            last_trade = self._fetch_last_trade(str(getattr(market, "yes_token_id", "") or ""))

        if executable_yes is None or executable_yes <= 0:
            blockers.append("yes_executable_price_missing")
        if executable_no is None or executable_no <= 0:
            blockers.append("no_executable_price_missing")

        return WeatherMarketTapeSnapshot(
            market_id=str(getattr(market, "condition_id", "") or ""),
            question=str(getattr(market, "question", "") or ""),
            captured_at=captured,
            symbol=str(getattr(market, "symbol", "") or "WEATHER"),
            slug=str(getattr(market, "slug", "") or ""),
            event_slug=str(getattr(market, "event_slug", "") or ""),
            end_date=self._iso_datetime(getattr(market, "end_date", None)),
            yes_token_id=str(getattr(market, "yes_token_id", "") or ""),
            no_token_id=str(getattr(market, "no_token_id", "") or ""),
            yes_price=yes_price,
            no_price=no_price,
            midpoint=midpoint,
            spread=spread,
            executable_yes_price=executable_yes,
            executable_no_price=executable_no,
            executable_price_source=executable_source,
            executable_yes_price_source=executable_yes_source,
            executable_no_price_source=executable_no_source,
            yes_book=yes_book.to_dict(),
            no_book=no_book.to_dict(),
            last_trade=last_trade,
            market_status="active" if bool(getattr(market, "is_active", True)) else "inactive",
            liquidity=float(getattr(market, "liquidity", 0.0) or 0.0),
            volume_24h=float(getattr(market, "volume_24h", 0.0) or 0.0),
            quality_flags=sorted(set(quality_flags)),
            blockers=sorted(set(blockers)),
        )

    def _fetch_book(self, token_id: str) -> WeatherBookSummary:
        if not token_id:
            return WeatherBookSummary(token_id="", status="missing_token_id")
        try:
            raw_book = self.cli.get_order_book(token_id)
        except Exception as exc:
            return WeatherBookSummary(token_id=token_id, status="error", error=f"{type(exc).__name__}: {exc}")
        if not raw_book:
            return WeatherBookSummary(token_id=token_id, status="empty")

        bids = self._levels(raw_book, "bids")
        asks = self._levels(raw_book, "asks")
        if not bids and not asks:
            return WeatherBookSummary(token_id=token_id, status="empty_levels")

        bids = sorted(bids, key=lambda level: level[0], reverse=True)
        asks = sorted(asks, key=lambda level: level[0])
        bid_depth_shares, bid_depth_usd = self._depth(bids)
        ask_depth_shares, ask_depth_usd = self._depth(asks)
        return WeatherBookSummary(
            token_id=token_id,
            status="ok",
            best_bid=round(bids[0][0], 6) if bids else None,
            best_ask=round(asks[0][0], 6) if asks else None,
            bid_depth_usd=round(bid_depth_usd, 6) if bids else None,
            ask_depth_usd=round(ask_depth_usd, 6) if asks else None,
            bid_depth_shares=round(bid_depth_shares, 6) if bids else None,
            ask_depth_shares=round(ask_depth_shares, 6) if asks else None,
            level_count_bid=len(bids),
            level_count_ask=len(asks),
            bid_levels=self._level_rows(bids),
            ask_levels=self._level_rows(asks),
        )

    def _fetch_last_trade(self, token_id: str) -> Dict[str, Any]:
        if not token_id:
            return {"status": "missing_token_id"}
        try:
            payload = self.cli.get_last_trade(token_id)
        except Exception as exc:
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        if not isinstance(payload, dict):
            return {"status": "unavailable"}
        return {"status": "ok", **payload}

    @classmethod
    def _levels(cls, raw_book: Any, key: str) -> List[Tuple[float, float]]:
        raw_levels = cls._book_field(raw_book, key)
        if raw_levels is None:
            return []
        levels: List[Tuple[float, float]] = []
        if not isinstance(raw_levels, list):
            return levels
        for raw_level in raw_levels:
            price = cls._level_field(raw_level, "price")
            size = cls._level_field(raw_level, "size")
            parsed_price = cls._safe_probability(price)
            parsed_size = cls._safe_float(size)
            if parsed_price is None or parsed_size is None or parsed_size <= 0:
                continue
            levels.append((parsed_price, parsed_size))
        return levels

    @staticmethod
    def _book_field(raw_book: Any, key: str) -> Any:
        if isinstance(raw_book, dict):
            return raw_book.get(key)
        return getattr(raw_book, key, None)

    @staticmethod
    def _level_field(raw_level: Any, key: str) -> Any:
        if isinstance(raw_level, dict):
            return raw_level.get(key)
        return getattr(raw_level, key, None)

    @staticmethod
    def _depth(levels: List[Tuple[float, float]]) -> Tuple[float, float]:
        shares = sum(size for _price, size in levels)
        dollars = sum(price * size for price, size in levels)
        return shares, dollars

    @staticmethod
    def _level_rows(levels: List[Tuple[float, float]]) -> List[Dict[str, float]]:
        return [
            {
                "price": round(price, 6),
                "size": round(size, 6),
                "notional_usd": round(price * size, 6),
            }
            for price, size in levels
        ]

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            parsed = float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed):
            return None
        return parsed

    @classmethod
    def _safe_probability(cls, value: Any) -> Optional[float]:
        parsed = cls._safe_float(value)
        if parsed is None:
            return None
        return max(0.0, min(1.0, parsed))

    @staticmethod
    def _iso_datetime(value: Any) -> str:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value or "")
