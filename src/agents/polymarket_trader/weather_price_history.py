"""Polymarket CLOB price-history helpers for weather alpha research."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

import requests


CLOB_API = "https://clob.polymarket.com"


@dataclass(frozen=True)
class WeatherPricePoint:
    token_id: str
    price: float
    observed_at: str
    age_hours: float
    source: str = "clob_prices_history"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def fetch_yes_prices_near_batch(
    session: requests.Session,
    token_ids: Iterable[str],
    asof_time: datetime,
) -> Dict[str, float]:
    """Fetch nearest historical YES prices for up to many token IDs."""
    return {
        token_id: point.price
        for token_id, point in fetch_yes_price_points_near_batch(session, token_ids, asof_time).items()
    }


def fetch_yes_price_points_near_batch(
    session: requests.Session,
    token_ids: Iterable[str],
    asof_time: datetime,
    *,
    max_age_hours: float = 12.0,
) -> Dict[str, WeatherPricePoint]:
    """Fetch nearest historical YES prices observed at or before as-of time."""
    tokens = [str(token_id) for token_id in token_ids if str(token_id or "").strip()]
    prices: Dict[str, WeatherPricePoint] = {}
    for chunk in _chunks(tokens, 20):
        start_ts = int((asof_time - timedelta(hours=12)).timestamp())
        end_ts = int(asof_time.timestamp())
        response = session.post(
            f"{CLOB_API}/batch-prices-history",
            json={
                "markets": chunk,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "interval": "1h",
                "fidelity": 60,
            },
            timeout=20,
        )
        response.raise_for_status()
        history = response.json().get("history", {})
        if not isinstance(history, dict):
            continue
        for token_id in chunk:
            point = select_price_at_or_before(
                history.get(token_id, []),
                asof_time,
                token_id=token_id,
                max_age_hours=max_age_hours,
            )
            if point is not None:
                prices[token_id] = point
    return prices


def select_price_near(history: Any, asof_time: datetime) -> Optional[float]:
    point = select_price_at_or_before(history, asof_time, token_id="")
    return point.price if point is not None else None


def select_price_at_or_before(
    history: Any,
    asof_time: datetime,
    *,
    token_id: str = "",
    max_age_hours: float = 12.0,
) -> Optional[WeatherPricePoint]:
    if not isinstance(history, list) or not history:
        return None
    target_ts = asof_time.timestamp()
    candidates = []
    for point in history:
        try:
            price = float(point.get("p"))
            ts = float(point.get("t"))
        except (AttributeError, TypeError, ValueError):
            continue
        if ts > target_ts:
            continue
        age_hours = (target_ts - ts) / 3600.0
        if age_hours > max_age_hours:
            continue
        if 0.001 <= price <= 0.999 and math.isfinite(price):
            candidates.append((age_hours, price, ts))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    age_hours, price, ts = candidates[0]
    return WeatherPricePoint(
        token_id=str(token_id or ""),
        price=round(price, 4),
        observed_at=datetime.utcfromtimestamp(ts).isoformat(),
        age_hours=round(age_hours, 4),
    )


def _chunks(values: List[str], size: int) -> Iterable[List[str]]:
    for idx in range(0, len(values), size):
        yield values[idx : idx + size]
