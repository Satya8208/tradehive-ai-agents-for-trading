"""Candidate lifecycle records for weather paper-shadow decisions."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .weather_blockers import blocker_summary, blockers_to_records


WEATHER_CANDIDATE_LIFECYCLE_SCHEMA_VERSION = "weather_candidate_lifecycle_v1"


@dataclass(frozen=True)
class WeatherCandidateLifecycleRecord:
    candidate_id: str
    decision_id: str
    run_id: str
    market_id: str
    lane_id: str
    discovered_at: str
    decision_asof_time: str
    status: str
    decision_packet_ref: str
    replay_manifest_ref: str = ""
    resolution_evidence_ref: str = ""
    expected_edge_after_cost: Optional[float] = None
    simulated_fill_size_usd: Optional[float] = None
    simulated_entry_price: Optional[float] = None
    resolved_payout: Optional[float] = None
    paper_pnl: Optional[float] = None
    blockers: List[str] = field(default_factory=list)
    evidence_refs: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = WEATHER_CANDIDATE_LIFECYCLE_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["blocker_records"] = blockers_to_records(payload.get("blockers", []))
        payload["blocker_summary"] = blocker_summary(payload.get("blockers", []))
        return payload


class WeatherCandidateLifecycleBuilder:
    """Track discovery through pending/resolved replay states."""

    def build_from_decision_packets(
        self,
        packets: Iterable[Dict[str, Any]],
        *,
        labels_by_market: Optional[Dict[str, Dict[str, Any]]] = None,
        discovered_at: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        labels = labels_by_market or {}
        discovered = discovered_at or datetime.utcnow().isoformat()
        for packet in packets:
            market_id = str(packet.get("market_id") or "")
            decision_id = str(packet.get("decision_id") or "")
            if not market_id or not decision_id:
                continue
            label = labels.get(market_id, {})
            status, payout, pnl, blockers = self._status_for_packet(packet, label)
            refs = dict(packet.get("evidence_refs") or {})
            rows.append(
                WeatherCandidateLifecycleRecord(
                    candidate_id=f"weather_candidate:{decision_id}",
                    decision_id=decision_id,
                    run_id=str(packet.get("run_id") or ""),
                    market_id=market_id,
                    lane_id=str(packet.get("lane_id") or ""),
                    discovered_at=discovered,
                    decision_asof_time=str(packet.get("decision_asof_time") or ""),
                    status=status,
                    decision_packet_ref=str(refs.get("decision_packet_ref") or f"weather_decision_packet:{decision_id}"),
                    resolution_evidence_ref=str(label.get("evidence_ref") or ""),
                    expected_edge_after_cost=_safe_float(packet.get("expected_edge_after_cost")),
                    simulated_fill_size_usd=_safe_float(packet.get("simulated_fill_size_usd")),
                    simulated_entry_price=_safe_float(packet.get("simulated_entry_price")),
                    resolved_payout=payout,
                    paper_pnl=pnl,
                    blockers=blockers,
                    evidence_refs=refs,
                ).to_dict()
            )
        return rows

    @staticmethod
    def summarize(records: Iterable[Dict[str, Any]], *, records_written: int = 0) -> Dict[str, Any]:
        rows = list(records)
        return {
            "schema_version": "weather_candidate_lifecycle_summary_v1",
            "lifecycle_record_count": len(rows),
            "lifecycle_records_written": int(records_written),
            "by_status": dict(sorted(Counter(str(row.get("status") or "missing") for row in rows).items())),
            "by_lane": dict(sorted(Counter(str(row.get("lane_id") or "missing") for row in rows).items())),
            "top_records": rows[:25],
        }

    def _status_for_packet(
        self,
        packet: Dict[str, Any],
        label: Dict[str, Any],
    ) -> tuple[str, Optional[float], Optional[float], List[str]]:
        blockers = [str(item) for item in packet.get("blockers", []) or [] if str(item or "").strip()]
        if blockers:
            return "replay_blocked", None, None, sorted(set(blockers))
        label_status = str(label.get("label_status") or "")
        if label_status != "resolved":
            return "pending_resolution", None, None, ["candidate_pending_resolution"]
        yes_resolved = label.get("yes_resolved")
        side = str(packet.get("side") or "").upper()
        if side not in {"YES", "NO"} or not isinstance(yes_resolved, bool):
            return "resolved_ambiguous", None, None, ["candidate_resolution_ambiguous"]
        selected_win = bool(yes_resolved) if side == "YES" else not bool(yes_resolved)
        entry_price = _safe_float(packet.get("simulated_entry_price") or packet.get("executable_price"))
        size = _safe_float(packet.get("simulated_fill_size_usd")) or 0.0
        if entry_price is None or entry_price <= 0:
            return "resolved_ambiguous", None, None, ["candidate_entry_price_missing"]
        payout = size / entry_price if selected_win else 0.0
        pnl = payout - size
        return ("resolved_won" if selected_win else "resolved_lost"), round(payout, 6), round(pnl, 6), []


def _safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return round(parsed, 6)
