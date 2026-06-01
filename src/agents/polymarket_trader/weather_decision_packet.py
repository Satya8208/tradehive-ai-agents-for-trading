"""Replayable decision packets for weather research candidates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .weather_blockers import blocker_summary, blockers_to_records
from .weather_contracts import FEATURE_SCHEMA_VERSION


WEATHER_DECISION_PACKET_SCHEMA_VERSION = "weather_decision_packet_v1"
WEATHER_DECISION_PACKET_SOURCE_KNOWN_OUTCOME = "weather_known_outcome_scan"
WEATHER_CURRENT_SCAN_STATUS = "current_scan_candidate"


@dataclass(frozen=True)
class WeatherDecisionPacket:
    decision_id: str
    run_id: str
    market_id: str
    lane_id: str
    decision_asof_time: str
    status: str
    side: str
    p_yes: Optional[float]
    probability_role: str
    p_yes_source: str
    selected_win_probability: Optional[float]
    market_probability: Optional[float]
    executable_price: Optional[float]
    executable_price_source: str
    expected_edge_after_cost: Optional[float]
    requested_size_usd: Optional[float]
    simulated_fill_size_usd: Optional[float]
    simulated_entry_price: Optional[float]
    fill_status: str
    source: str = WEATHER_DECISION_PACKET_SOURCE_KNOWN_OUTCOME
    schema_version: str = WEATHER_DECISION_PACKET_SCHEMA_VERSION
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    blockers: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)
    evidence_refs: Dict[str, Any] = field(default_factory=dict)
    packet_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if not payload.get("packet_hash"):
            payload["packet_hash"] = _packet_hash({k: v for k, v in payload.items() if k != "packet_hash"})
        payload["blocker_records"] = blockers_to_records(payload.get("blockers", []))
        payload["blocker_summary"] = blocker_summary(payload.get("blockers", []))
        return payload


class WeatherDecisionPacketBuilder:
    """Build deterministic paper-shadow packets from current scan candidates."""

    def build_known_outcome_packets(
        self,
        candidates: Iterable[Dict[str, Any]],
        *,
        tape_by_market: Optional[Dict[str, Any]] = None,
        run_id: str = "",
        decision_time: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        packets: List[Dict[str, Any]] = []
        for candidate in candidates:
            if str(candidate.get("status") or "") != "candidate":
                continue
            market_id = str(candidate.get("market_id") or "")
            if not market_id:
                continue
            tape = _as_dict((tape_by_market or {}).get(market_id))
            packet = self._known_outcome_packet(
                candidate,
                tape=tape,
                run_id=run_id,
                decision_time=decision_time or str(candidate.get("generated_at") or datetime.utcnow().isoformat()),
            )
            packets.append(packet.to_dict())
        return packets

    def to_candidate_events(
        self,
        packets: Iterable[Dict[str, Any]],
        *,
        captured_at: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        for packet in packets:
            market_id = str(packet.get("market_id") or "")
            if not market_id:
                continue
            accepted = str(packet.get("status") or "") == WEATHER_CURRENT_SCAN_STATUS
            size = _first_float(packet.get("simulated_fill_size_usd"), packet.get("requested_size_usd"), 0.0)
            event = {
                "market_id": market_id,
                "captured_at": captured_at or str(packet.get("decision_asof_time") or packet.get("generated_at") or ""),
                "accepted": accepted,
                "reason": "current_scan_candidate_recorded_for_paper_shadow" if accepted else "decision_packet_blocked",
                "source": str(packet.get("source") or WEATHER_DECISION_PACKET_SOURCE_KNOWN_OUTCOME),
                "decision_packet_id": packet.get("decision_id"),
                "decision_packet": dict(packet),
                "candidate": {
                    "market_id": market_id,
                    "side": packet.get("side"),
                    "model_probability": packet.get("p_yes"),
                    "market_probability": packet.get("market_probability"),
                    "edge_percent": _edge_percent(packet.get("expected_edge_after_cost")),
                    "confidence": 1.0 if packet.get("probability_role") == "settlement_fact" else 0.0,
                    "size_usd": size,
                    "limit_price": packet.get("executable_price"),
                    "blockers": list(packet.get("blockers", []) or []),
                    "edge_reason_flags": [
                        "known_outcome_observation_lag",
                        str(packet.get("probability_role") or "unknown_probability_role"),
                    ],
                    "quality_flags": list(packet.get("quality_flags", []) or []),
                },
                "verdict": {
                    "accepted": accepted,
                    "phase": "paper_shadow_recording",
                    "reason": "current_scan_candidate" if accepted else "blocked",
                    "blockers": list(packet.get("blockers", []) or []),
                },
                "final_trade_status": "planned" if accepted else "blocked_by_weather_known_outcome_scan",
                "final_trade_side": packet.get("side") if accepted else "",
                "final_trade_price": packet.get("executable_price") if accepted else None,
                "final_trade_size_usd": size if accepted else None,
            }
            events.append(event)
        return events

    def feature_context_for_packet(
        self,
        packet: Dict[str, Any],
        candidate: Dict[str, Any],
        tape: Any,
    ) -> Dict[str, Any]:
        classification = candidate.get("classification") if isinstance(candidate.get("classification"), dict) else {}
        station_state = candidate.get("station_state") if isinstance(candidate.get("station_state"), dict) else {}
        threshold_state = candidate.get("threshold_state") if isinstance(candidate.get("threshold_state"), dict) else {}
        tape_dict = _as_dict(tape)
        station_id = str(
            station_state.get("station_id")
            or classification.get("station_id")
            or ""
        ).upper()
        market_spec = {
            "schema_version": "weather_market_spec_from_known_outcome_v1",
            "market_id": packet.get("market_id"),
            "question": tape_dict.get("question") or classification.get("question") or "",
            "metric": classification.get("metric"),
            "operator": classification.get("operator"),
            "threshold": classification.get("threshold"),
            "upper_threshold": classification.get("upper_threshold"),
            "threshold_unit": classification.get("threshold_unit") or "unknown",
            "target_date": classification.get("target_date"),
            "location_name": classification.get("location_name") or "",
            "resolution_station": station_id,
            "alpha_lanes": classification.get("alpha_lanes", []),
            "settlement_source": "official_observation_fact" if packet.get("probability_role") == "settlement_fact" else "unverified",
        }
        return {
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "status": "ok" if not packet.get("blockers") else "fail_closed",
            "selected_source_id": packet.get("p_yes_source") or "weather_known_outcome",
            "selected_source_family": "official_observation" if packet.get("probability_role") == "settlement_fact" else "weather_research",
            "weather_probability": packet.get("p_yes"),
            "weather_confidence": 1.0 if packet.get("probability_role") == "settlement_fact" else 0.0,
            "weather_edge_percent": _edge_percent(packet.get("expected_edge_after_cost")),
            "recommended_side": packet.get("side") or "",
            "target_date": classification.get("target_date") or "",
            "metric": classification.get("metric") or "",
            "threshold": classification.get("threshold"),
            "station_mapping": {
                "location_name": classification.get("location_name") or "",
                "resolution_station": station_id,
                "station_id": station_id,
                "source": "known_outcome_observation_context",
                "status": "ok" if station_id else "fail_closed",
            },
            "source_statuses": {
                "weather_known_outcome_alpha": str(candidate.get("status") or ""),
                "threshold_state": str(threshold_state.get("status") or ""),
            },
            "forecast_snapshots": [],
            "edge_reason_flags": ["known_outcome_observation_lag", str(packet.get("probability_role") or "")],
            "quality_flags": list(packet.get("quality_flags", []) or []),
            "feature_blockers": list(packet.get("blockers", []) or []),
            "market_spec": market_spec,
            "evidence_refs": dict(packet.get("evidence_refs") or {}),
            "asof_time": packet.get("decision_asof_time") or "",
            "market_tape_snapshot": tape_dict,
            "feature_packet": {
                "schema_version": FEATURE_SCHEMA_VERSION,
                "market_id": packet.get("market_id"),
                "source": packet.get("source"),
                "decision_packet_id": packet.get("decision_id"),
                "threshold_state": threshold_state,
                "market_spec": market_spec,
                "evidence_refs": dict(packet.get("evidence_refs") or {}),
            },
        }

    def _known_outcome_packet(
        self,
        candidate: Dict[str, Any],
        *,
        tape: Dict[str, Any],
        run_id: str,
        decision_time: str,
    ) -> WeatherDecisionPacket:
        market_id = str(candidate.get("market_id") or "")
        alpha_code = str(candidate.get("alpha_code") or "known_outcome_observation_lag")
        fill = candidate.get("fill_simulation") if isinstance(candidate.get("fill_simulation"), dict) else {}
        side = str(candidate.get("side") or "").upper()
        book_payload = _book_for_side(tape, side) or fill
        book_fingerprint = _fingerprint(book_payload)
        threshold_state = candidate.get("threshold_state") if isinstance(candidate.get("threshold_state"), dict) else {}
        classification = candidate.get("classification") if isinstance(candidate.get("classification"), dict) else {}
        packet_seed = {
            "run_id": run_id,
            "market_id": market_id,
            "alpha_code": alpha_code,
            "decision_time": decision_time,
            "side": side,
        }
        decision_id = f"wdp_{_fingerprint(packet_seed)}"
        evidence_refs = {
            "decision_packet_ref": f"weather_decision_packet:{decision_id}",
            "market_tape_ref": f"weather_market_tape:{market_id}:{tape.get('captured_at', '')}",
            "feature_packet_ref": f"weather_feature_snapshot:{market_id}:{decision_time}",
            "threshold_state_ref": f"weather_threshold_state:{market_id}:{_fingerprint(threshold_state)}",
            "market_spec_ref": f"weather_market_spec:{market_id}:{_fingerprint(classification)}",
            "orderbook_snapshot_ref": f"weather_orderbook_snapshot:{market_id}:{book_fingerprint}",
        }
        requested_size = _first_float(fill.get("requested_size_usd"), candidate.get("max_fillable_usd"))
        filled_size = _first_float(fill.get("filled_notional_usd"), candidate.get("max_fillable_usd"), requested_size)
        packet = WeatherDecisionPacket(
            decision_id=decision_id,
            run_id=run_id,
            market_id=market_id,
            lane_id=alpha_code,
            decision_asof_time=decision_time,
            status=WEATHER_CURRENT_SCAN_STATUS,
            side=side,
            p_yes=_safe_float(candidate.get("p_yes")),
            probability_role=str(candidate.get("probability_role") or ""),
            p_yes_source=str(candidate.get("p_yes_source") or ""),
            selected_win_probability=_safe_float(candidate.get("selected_win_probability")),
            market_probability=_safe_float(candidate.get("executable_price")),
            executable_price=_safe_float(candidate.get("executable_price")),
            executable_price_source=str(candidate.get("executable_price_source") or ""),
            expected_edge_after_cost=_safe_float(candidate.get("edge_after_cost")),
            requested_size_usd=requested_size,
            simulated_fill_size_usd=filled_size,
            simulated_entry_price=_first_float(fill.get("average_price"), candidate.get("executable_price")),
            fill_status=str(fill.get("status") or candidate.get("fill_status") or ""),
            generated_at=decision_time,
            blockers=sorted({str(item) for item in candidate.get("blockers", []) or [] if str(item or "").strip()}),
            quality_flags=sorted(
                {
                    "paper_shadow_research_only",
                    "replayable_decision_packet",
                    *[str(item) for item in candidate.get("quality_flags", []) or [] if str(item or "").strip()],
                }
            ),
            evidence_refs=evidence_refs,
        )
        return packet


def summarize_decision_packets(
    packets: Iterable[Dict[str, Any]],
    *,
    packets_written: int = 0,
    candidate_events_written: int = 0,
) -> Dict[str, Any]:
    rows = list(packets)
    return {
        "schema_version": "weather_decision_packet_summary_v1",
        "decision_packet_count": len(rows),
        "decision_packets_written": int(packets_written),
        "candidate_events_written": int(candidate_events_written),
        "by_status": _counts(row.get("status") for row in rows),
        "by_lane": _counts(row.get("lane_id") for row in rows),
        "top_decision_packets": rows[:25],
    }


def _counts(values: Iterable[Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        key = str(value or "missing")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _packet_hash(payload: Dict[str, Any]) -> str:
    return _fingerprint(payload)


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload or {}, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _as_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return dict(value)
    return {}


def _safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _first_float(*values: Any) -> Optional[float]:
    for value in values:
        parsed = _safe_float(value)
        if parsed is not None:
            return round(parsed, 6)
    return None


def _edge_percent(value: Any) -> Optional[float]:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return round(parsed * 100.0, 6)


def _book_for_side(tape: Dict[str, Any], side: str) -> Dict[str, Any]:
    if side == "YES":
        return tape.get("yes_book", {}) if isinstance(tape.get("yes_book"), dict) else {}
    if side == "NO":
        return tape.get("no_book", {}) if isinstance(tape.get("no_book"), dict) else {}
    return {}
