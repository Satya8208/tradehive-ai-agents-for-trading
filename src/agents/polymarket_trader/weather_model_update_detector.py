"""
Model-run update detection for weather edge research.

The latency edge only exists if a model run changed and the market has not
fully repriced. This module keeps that state explicit and research-only.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .weather_contracts import utc_now_iso


@dataclass(frozen=True)
class WeatherModelUpdateEvent:
    source_id: str
    run_id: str
    event_type: str
    observed_at: str
    previous_run_id: str = ""
    cycle_time: str = ""
    source_age_minutes: Optional[float] = None
    price_move_points: Optional[float] = None
    market_repriced: bool = False
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)

    @property
    def actionable_for_research(self) -> bool:
        return self.event_type == "run_changed" and not self.market_repriced and not self.blockers

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["actionable_for_research"] = self.actionable_for_research
        return payload


class WeatherModelUpdateDetector:
    """Track source run IDs and whether CLOB price has already moved."""

    def __init__(
        self,
        max_source_age_minutes: float = 180.0,
        repriced_move_threshold_points: float = 2.0,
    ):
        self.max_source_age_minutes = float(max_source_age_minutes)
        self.repriced_move_threshold_points = float(repriced_move_threshold_points)
        self._last_run_by_source: Dict[str, str] = {}

    def observe(
        self,
        manifest: Dict[str, Any],
        price_latency: Optional[Dict[str, Any]] = None,
        observed_at: Optional[datetime] = None,
    ) -> WeatherModelUpdateEvent:
        source_id = str(manifest.get("source_id") or "unknown")
        run_id = str(manifest.get("run_id") or "")
        cycle_time = str(manifest.get("cycle_time") or "")
        source_age = _safe_float(manifest.get("source_age_minutes"))
        blockers: List[str] = []
        flags = ["model_update_detector"]
        if not run_id:
            blockers.append(f"model_run_id_missing:{source_id}")
        if str(manifest.get("status") or "") in {"not_applicable", "unavailable", "stale"}:
            blockers.append(f"model_source_{manifest.get('status')}:{source_id}")
        if source_age is not None and source_age > self.max_source_age_minutes:
            blockers.append(f"model_source_age_exceeds_max:{source_id}")

        previous = self._last_run_by_source.get(source_id, "")
        if not run_id:
            event_type = "invalid_manifest"
        elif not previous:
            event_type = "first_seen"
        elif previous != run_id:
            event_type = "run_changed"
        else:
            event_type = "same_run"

        price_move = self._price_move_points(price_latency or {})
        market_repriced = bool(
            price_move is not None and price_move >= self.repriced_move_threshold_points
        )
        if market_repriced:
            flags.append("market_price_moved_since_prior_scan")
        if run_id:
            self._last_run_by_source[source_id] = run_id

        return WeatherModelUpdateEvent(
            source_id=source_id,
            run_id=run_id,
            event_type=event_type,
            observed_at=(observed_at.isoformat() if observed_at else utc_now_iso()),
            previous_run_id=previous,
            cycle_time=cycle_time,
            source_age_minutes=source_age,
            price_move_points=price_move,
            market_repriced=market_repriced,
            blockers=blockers,
            quality_flags=flags,
        )

    def observe_many(
        self,
        manifests: Iterable[Dict[str, Any]],
        price_latency: Optional[Dict[str, Any]] = None,
        observed_at: Optional[datetime] = None,
    ) -> List[WeatherModelUpdateEvent]:
        return [
            self.observe(manifest, price_latency=price_latency, observed_at=observed_at)
            for manifest in manifests
        ]

    @staticmethod
    def _price_move_points(price_latency: Dict[str, Any]) -> Optional[float]:
        yes_move = _safe_float(price_latency.get("yes_price_change_points"))
        no_move = _safe_float(price_latency.get("no_price_change_points"))
        moves = [abs(value) for value in (yes_move, no_move) if value is not None]
        return round(max(moves), 4) if moves else None


def _safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None
