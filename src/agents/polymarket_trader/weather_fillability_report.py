"""Fillability subtype reporting for weather alpha candidates."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .weather_blockers import blocker_summary, blockers_to_records


WEATHER_FILLABILITY_REPORT_SCHEMA_VERSION = "weather_fillability_report_v1"


class WeatherFillabilityReporter:
    """Summarize walked-book capacity without granting execution permission."""

    def build(
        self,
        candidates: Iterable[Dict[str, Any]],
        *,
        tape_by_market: Optional[Dict[str, Any]] = None,
        generated_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows = [
            self._row(candidate, (tape_by_market or {}).get(str(candidate.get("market_id") or "")))
            for candidate in candidates
        ]
        status_counts = Counter(str(row.get("fill_status") or "missing") for row in rows)
        price_source_counts = Counter(str(row.get("price_source") or "missing") for row in rows)
        blocker_counts = Counter(blocker for row in rows for blocker in row.get("blockers", []))
        positive_capacity = sum(float(row.get("positive_edge_capacity_usd") or 0.0) for row in rows)
        full_positive = [
            row for row in rows
            if row.get("paper_status") == "candidate" and row.get("fill_status") == "full"
        ]
        return {
            "schema_version": WEATHER_FILLABILITY_REPORT_SCHEMA_VERSION,
            "generated_at": generated_at or datetime.utcnow().isoformat(),
            "candidate_count": len(rows),
            "paper_candidate_count": sum(1 for row in rows if row.get("paper_status") == "candidate"),
            "full_fill_positive_edge_count": len(full_positive),
            "positive_edge_capacity_usd": round(positive_capacity, 6),
            "by_fill_status": dict(sorted(status_counts.items())),
            "by_price_source": dict(sorted(price_source_counts.items())),
            "blocker_counts": dict(sorted(blocker_counts.items())),
            "blocker_summary": blocker_summary(blocker_counts.keys()),
            "top_rows": rows[:50],
        }

    def _row(self, candidate: Dict[str, Any], tape: Any) -> Dict[str, Any]:
        tape_dict = tape.to_dict() if hasattr(tape, "to_dict") else dict(tape or {})
        fill = candidate.get("fill_simulation") if isinstance(candidate.get("fill_simulation"), dict) else {}
        side = str(candidate.get("side") or fill.get("side") or "").upper()
        book = self._book_for_side(tape_dict, side)
        blockers = list(candidate.get("blockers", []) or []) + list(fill.get("blockers", []) or [])
        generated_at = str(candidate.get("generated_at") or "")
        captured_at = str(tape_dict.get("captured_at") or "")
        filled = _float(fill.get("filled_notional_usd"))
        edge_after_cost = _float(candidate.get("edge_after_cost"))
        positive_capacity = filled if edge_after_cost is not None and edge_after_cost > 0 else 0.0
        row = {
            "market_id": str(candidate.get("market_id") or ""),
            "paper_status": str(candidate.get("status") or ""),
            "side": side,
            "fill_status": str(fill.get("status") or candidate.get("fill_status") or ""),
            "requested_size_usd": _float(fill.get("requested_size_usd")),
            "filled_notional_usd": filled,
            "fill_ratio": _float(fill.get("fill_ratio")),
            "total_depth_usd_at_limit": _float(fill.get("total_depth_usd_at_limit")),
            "average_price": _float(fill.get("average_price")),
            "best_price": _float(fill.get("best_price")),
            "worst_price": _float(fill.get("worst_price")),
            "level_count_available": int(fill.get("level_count_available") or 0),
            "level_count_consumed": int(fill.get("level_count_consumed") or 0),
            "price_source": str(fill.get("price_source") or candidate.get("executable_price_source") or ""),
            "book_captured_at": captured_at,
            "decision_generated_at": generated_at,
            "book_age_seconds": _age_seconds(captured_at, generated_at),
            "book_fingerprint": _fingerprint(book or fill),
            "positive_edge_capacity_usd": round(positive_capacity, 6),
            "edge_after_cost": edge_after_cost,
            "blockers": sorted({str(blocker) for blocker in blockers if str(blocker or "").strip()}),
        }
        row["blocker_records"] = blockers_to_records(row["blockers"])
        return row

    @staticmethod
    def _book_for_side(tape: Dict[str, Any], side: str) -> Dict[str, Any]:
        if side == "YES":
            return tape.get("yes_book", {}) if isinstance(tape.get("yes_book"), dict) else {}
        if side == "NO":
            return tape.get("no_book", {}) if isinstance(tape.get("no_book"), dict) else {}
        return {}


def _fingerprint(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload or {}, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _float(value: Any) -> Optional[float]:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _age_seconds(older: str, newer: str) -> Optional[float]:
    old_dt = _parse_dt(older)
    new_dt = _parse_dt(newer)
    if old_dt is None or new_dt is None:
        return None
    return round((new_dt - old_dt).total_seconds(), 6)


def _parse_dt(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None
