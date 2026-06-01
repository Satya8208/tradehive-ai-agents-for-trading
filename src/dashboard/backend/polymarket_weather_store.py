"""
Read-only weather control-room state for the operator dashboard.

The store treats saved Polymarket weather artifacts as the source of truth. It
does not infer live eligibility from a pretty UI state: live remains blocked
unless the trading package produces explicit release evidence.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.agents.polymarket_trader.weather_blockers import blocker_summary, blockers_to_records
from src.agents.polymarket_trader.config import get_polymarket_cli_config
from src.agents.polymarket_trader.weather_agent_teams import WeatherAgentTeamPlanner
from src.agents.polymarket_trader.weather_live_eligibility import WeatherLiveEligibilityGate


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TRADER_DATA_DIR = PROJECT_ROOT / "src" / "data" / "polymarket_trader"


@dataclass(frozen=True)
class WeatherArtifactSpec:
    key: str
    label: str
    path: Path
    kind: str = "json"
    stale_after_hours: float = 48.0


WEATHER_ARTIFACTS: Dict[str, WeatherArtifactSpec] = {
    "candidate_supply": WeatherArtifactSpec(
        "candidate_supply",
        "Candidate Supply",
        TRADER_DATA_DIR / "weather_candidate_supply" / "latest_weather_candidate_supply_report.json",
    ),
    "known_outcome": WeatherArtifactSpec(
        "known_outcome",
        "Known Outcome",
        TRADER_DATA_DIR / "weather_known_outcome_alpha" / "latest_weather_known_outcome_alpha_report.json",
    ),
    "ladder": WeatherArtifactSpec(
        "ladder",
        "Ladder Consistency",
        TRADER_DATA_DIR / "weather_ladder_consistency_alpha" / "latest_weather_ladder_consistency_report.json",
    ),
    "evidence": WeatherArtifactSpec(
        "evidence",
        "Replay Evidence",
        TRADER_DATA_DIR / "weather_evidence" / "latest_weather_evidence_report.json",
    ),
    "edge_discovery": WeatherArtifactSpec(
        "edge_discovery",
        "Edge Discovery",
        TRADER_DATA_DIR / "weather_evidence" / "latest_weather_edge_discovery_report.json",
    ),
    "research": WeatherArtifactSpec(
        "research",
        "Research Team",
        TRADER_DATA_DIR / "weather_research_team" / "latest_weather_edge_report.json",
    ),
    "current_cycle": WeatherArtifactSpec(
        "current_cycle",
        "Current Cycle",
        TRADER_DATA_DIR / "current_cycle.json",
    ),
    "risk_state": WeatherArtifactSpec(
        "risk_state",
        "Risk State",
        TRADER_DATA_DIR / "positions" / "risk_state.json",
    ),
    "performance": WeatherArtifactSpec(
        "performance",
        "Performance Summary",
        TRADER_DATA_DIR / "performance" / "summary.json",
    ),
}

EVIDENCE_STREAMS = {
    "market_tape": TRADER_DATA_DIR / "weather_evidence" / "market_tape.jsonl",
    "feature_snapshots": TRADER_DATA_DIR / "weather_evidence" / "feature_snapshots.jsonl",
    "candidate_decisions": TRADER_DATA_DIR / "weather_evidence" / "candidate_decisions.jsonl",
    "decision_packets": TRADER_DATA_DIR / "weather_evidence" / "decision_packets.jsonl",
    "candidate_lifecycle": TRADER_DATA_DIR / "weather_evidence" / "candidate_lifecycle.jsonl",
    "resolution_labels": TRADER_DATA_DIR / "weather_evidence" / "resolution_labels.jsonl",
    "replay_records": TRADER_DATA_DIR / "weather_evidence" / "replay_records.jsonl",
    "run_audit": TRADER_DATA_DIR / "run_audit.jsonl",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_len(value: Any) -> int:
    if isinstance(value, int):
        return value
    try:
        return len(value)
    except TypeError:
        return 0


def _compact_blockers(blockers: Iterable[Any], limit: int = 8) -> List[str]:
    compact: List[str] = []
    for blocker in blockers or []:
        text = str(blocker or "").strip()
        if text and text not in compact:
            compact.append(text)
        if len(compact) >= limit:
            break
    return compact


class WeatherControlRoomStore:
    def __init__(self, data_dir: Path = TRADER_DATA_DIR):
        self.data_dir = Path(data_dir)

    def snapshot(self) -> Dict[str, Any]:
        reports = self.reports()
        artifacts = self.artifacts(reports)
        config = get_polymarket_cli_config(market_vertical="weather")
        agent_team_plan = WeatherAgentTeamPlanner(config).build(reports)
        live_report = WeatherLiveEligibilityGate(config).evaluate(evidence_report=reports.get("evidence"))
        qa_gate = self._qa_gate(reports, artifacts, config, live_report.to_dict())
        lanes = self._lane_matrix(reports)

        return {
            "schema_version": "weather_control_room_snapshot_v1",
            "generated_at": _utc_now().isoformat(),
            "operating_state": "live_eligible" if live_report.eligible else self._operating_state(reports),
            "mode_chain": ["research_only", "replay", "paper", "live_eligible", "live_enabled"],
            "live_status": live_report.to_dict(),
            "summary": self._summary(reports, artifacts, qa_gate),
            "lanes": lanes,
            "qa_gate": qa_gate,
            "agent_team_plan": agent_team_plan,
            "teams": self._team_manifest(),
            "data_contracts": self._data_contracts(),
            "blind_spots": self._blind_spots(),
            "artifacts": artifacts,
            "reports": self._report_summaries(reports),
            "actions": self.action_catalog(),
        }

    def status(self) -> Dict[str, Any]:
        snapshot = self.snapshot()
        return {
            "schema_version": "weather_control_room_status_v1",
            "generated_at": snapshot["generated_at"],
            "operating_state": snapshot["operating_state"],
            "live_status": snapshot["live_status"],
            "summary": snapshot["summary"],
            "qa_gate": snapshot["qa_gate"],
            "lanes": snapshot["lanes"],
            "actions": snapshot["actions"],
        }

    def release(self) -> Dict[str, Any]:
        config = get_polymarket_cli_config(market_vertical="weather")
        return WeatherLiveEligibilityGate(config).evaluate(evidence_report=self.reports().get("evidence")).to_dict()

    def reports(self) -> Dict[str, Dict[str, Any]]:
        return {key: _safe_read_json(spec.path) for key, spec in WEATHER_ARTIFACTS.items()}

    def artifacts(self, reports: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
        reports = reports or self.reports()
        now = _utc_now()
        rows: Dict[str, Dict[str, Any]] = {}
        for key, spec in WEATHER_ARTIFACTS.items():
            payload = reports.get(key, {})
            generated_at = _parse_dt(payload.get("generated_at") or payload.get("updated_at"))
            mtime = None
            if spec.path.exists():
                mtime = datetime.fromtimestamp(spec.path.stat().st_mtime, tz=timezone.utc)
            stamp = generated_at or mtime
            age_hours = round((now - stamp).total_seconds() / 3600, 2) if stamp else None
            rows[key] = {
                "key": key,
                "label": spec.label,
                "path": str(spec.path),
                "exists": spec.path.exists(),
                "kind": spec.kind,
                "generated_at": stamp.isoformat() if stamp else None,
                "age_hours": age_hours,
                "freshness": "missing"
                if not spec.path.exists()
                else "stale"
                if age_hours is not None and age_hours > spec.stale_after_hours
                else "fresh",
                "stale_after_hours": spec.stale_after_hours,
            }
        return rows

    def candidates(self, lane: str = "known_outcome", status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        reports = self.reports()
        lane = (lane or "known_outcome").strip()
        rows: List[Dict[str, Any]]
        if lane == "candidate_supply":
            rows = [
                self._supply_candidate(row)
                for row in reports.get("candidate_supply", {}).get("top_routed_markets", []) or []
            ]
        elif lane == "ladder":
            rows = [
                self._alpha_candidate("ladder", row)
                for row in reports.get("ladder", {}).get("candidates", []) or []
            ]
        elif lane == "evidence":
            rows = [
                self._alpha_candidate("evidence", row)
                for row in reports.get("evidence", {}).get("top_replay_records", []) or []
            ]
        else:
            rows = [
                self._alpha_candidate("known_outcome", row)
                for row in reports.get("known_outcome", {}).get("candidates", []) or []
            ]
        if status:
            status_text = status.strip().lower()
            rows = [row for row in rows if str(row.get("status", "")).lower() == status_text]
        return rows[: max(1, min(limit, 500))]

    def tail_stream(self, stream: str, limit: int = 100) -> Dict[str, Any]:
        path = EVIDENCE_STREAMS.get(stream)
        if path is None:
            return {
                "stream": stream,
                "status": "unknown_stream",
                "items": [],
                "known_streams": sorted(EVIDENCE_STREAMS),
            }
        items: deque[Dict[str, Any]] = deque(maxlen=max(1, min(limit, 500)))
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            parsed = json.loads(line)
                        except json.JSONDecodeError:
                            parsed = {"raw": line, "parse_error": "json_decode_error"}
                        if isinstance(parsed, dict):
                            items.append(parsed)
            except OSError:
                return {"stream": stream, "status": "unreadable", "path": str(path), "items": []}
        return {
            "stream": stream,
            "status": "ready" if path.exists() else "missing",
            "path": str(path),
            "items": list(items),
        }

    @staticmethod
    def action_catalog() -> List[Dict[str, Any]]:
        return [
            {
                "id": "status-check",
                "label": "Refresh Status",
                "risk": "read_only",
                "wired": True,
                "description": "Runs the weather paper status command.",
            },
            {
                "id": "paper-cycle",
                "label": "Run Paper Weather Cycle",
                "risk": "paper_only",
                "wired": True,
                "description": "Runs one weather paper cycle with orderbook evidence.",
            },
            {
                "id": "candidate-supply",
                "label": "Refresh Universe + Depth",
                "risk": "read_only",
                "wired": True,
                "description": "Rebuilds weather candidate supply with orderbook fetch planning.",
            },
            {
                "id": "known-outcome",
                "label": "Scan Known Outcome",
                "risk": "read_only",
                "wired": True,
                "description": "Scans observation-lag known-outcome candidates.",
            },
            {
                "id": "resolution-labels",
                "label": "Backfill Labels + Replay",
                "risk": "read_only",
                "wired": True,
                "description": "Backfills settled labels from Gamma for saved evidence markets, then reruns replay.",
            },
            {
                "id": "replay-evidence",
                "label": "Rerun Replay",
                "risk": "read_only",
                "wired": True,
                "description": "Rebuilds replay records and the weather evidence report from saved tape, features, candidates, and labels.",
            },
            {
                "id": "ladder",
                "label": "Scan Ladder",
                "risk": "read_only",
                "wired": True,
                "description": "Scans ladder and structural bucket consistency.",
            },
            {
                "id": "research-report",
                "label": "Rebuild Research Report",
                "risk": "read_only",
                "wired": True,
                "description": "Runs the weather research team report builder.",
            },
            {
                "id": "test-run",
                "label": "Run Weather Test",
                "risk": "research_only",
                "wired": True,
                "description": "Runs a safe weather system test: known-outcome scan plus replay/report gates.",
            },
            {
                "id": "kill-switch",
                "label": "Kill Switch",
                "risk": "live_blocked",
                "wired": True,
                "description": "Audits that live weather is disabled; no authenticated order call is made.",
            },
        ]

    def _summary(
        self,
        reports: Dict[str, Dict[str, Any]],
        artifacts: Dict[str, Dict[str, Any]],
        qa_gate: Dict[str, Any],
    ) -> Dict[str, Any]:
        supply = reports.get("candidate_supply", {})
        known = reports.get("known_outcome", {})
        evidence = reports.get("evidence", {})
        stale_count = sum(1 for row in artifacts.values() if row["freshness"] == "stale")
        missing_count = sum(1 for row in artifacts.values() if row["freshness"] == "missing")
        return {
            "markets_scanned": _safe_int(supply.get("markets_scanned")),
            "routed_markets": _safe_int(supply.get("routed_markets")),
            "research_candidates": _safe_int(supply.get("research_candidate_count")),
            "candidate_supply_state": supply.get("candidate_supply_state") or "missing",
            "orderbook_coverage": _safe_float(
                supply.get("orderbook_coverage")
                or (supply.get("summary") or {}).get("orderbook_coverage")
                or 0.0
            ),
            "known_outcome_candidates": _safe_int(known.get("candidate_count")),
            "known_outcome_observation_eligible": _safe_int(
                (known.get("observation_eligibility") or {}).get("eligible_count")
                or known.get("observation_eligible_count")
            ),
            "known_outcome_observation_eligibility_blockers": (
                (known.get("observation_eligibility") or {}).get("blocker_counts") or {}
            ),
            "known_outcome_observation_eligibility_summary": blocker_summary(
                (((known.get("observation_eligibility") or {}).get("blocker_counts") or {}).keys())
            ),
            "known_outcome_context_destinations": (
                (known.get("observation_context") or {}).get("destination_counts") or {}
            ),
            "known_outcome_fillability": {
                "full_fill_positive_edge_count": (known.get("fillability_report") or {}).get("full_fill_positive_edge_count"),
                "positive_edge_capacity_usd": (known.get("fillability_report") or {}).get("positive_edge_capacity_usd"),
                "by_fill_status": (known.get("fillability_report") or {}).get("by_fill_status", {}),
            },
            "known_outcome_decision_packets": {
                "decision_packet_count": (known.get("decision_packet_summary") or {}).get("decision_packet_count"),
                "decision_packets_written": (known.get("decision_packet_summary") or {}).get("decision_packets_written"),
                "candidate_events_written": (known.get("decision_packet_summary") or {}).get("candidate_events_written"),
            },
            "known_outcome_candidate_lifecycle": {
                "lifecycle_record_count": (known.get("candidate_lifecycle_summary") or {}).get("lifecycle_record_count"),
                "lifecycle_records_written": (known.get("candidate_lifecycle_summary") or {}).get("lifecycle_records_written"),
                "by_status": (known.get("candidate_lifecycle_summary") or {}).get("by_status", {}),
            },
            "known_outcome_blockers": known.get("blocker_counts", {}),
            "known_outcome_blocker_summary": blocker_summary((known.get("blocker_counts") or {}).keys()),
            "known_outcome_coverage_verdict": (known.get("coverage_audit") or {}).get("verdict", "missing"),
            "resolved_replay_records": _safe_int(evidence.get("resolved_record_count")),
            "tradeable_replay_count": _safe_int(evidence.get("tradeable_replay_count")),
            "edge_status": evidence.get("edge_status") or "missing",
            "qa_status": qa_gate["status"],
            "stale_artifacts": stale_count,
            "missing_artifacts": missing_count,
        }

    def _operating_state(self, reports: Dict[str, Dict[str, Any]]) -> str:
        verdict = (reports.get("evidence", {}).get("deployment_verdict") or {})
        if verdict.get("accepted_for_live_weather_trading"):
            return "live_eligible"
        if verdict.get("accepted_for_paper_weather_trading"):
            return "paper"
        if _safe_int(reports.get("evidence", {}).get("record_count")) > 0:
            return "replay"
        return "research_only"

    def _lane_matrix(self, reports: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        supply = reports.get("candidate_supply", {})
        known = reports.get("known_outcome", {})
        ladder = reports.get("ladder", {})
        evidence = reports.get("evidence", {})
        research = reports.get("research", {})
        supply_lane_counts = supply.get("lane_summary", {}) or {}

        return [
            {
                "id": "candidate_supply",
                "label": "Candidate Supply",
                "status": supply.get("candidate_supply_state") or "missing",
                "count": _safe_int(supply.get("research_candidate_count")),
                "markets": _safe_int(supply.get("markets_scanned")),
                "blockers": _compact_blockers(
                    ["orderbook_coverage_needed"]
                    if supply.get("candidate_supply_state") == "orderbook_coverage_needed"
                    else []
                ),
                "metrics": {
                    "routed_markets": _safe_int(supply.get("routed_markets")),
                    "orderbook_coverage": supply.get("orderbook_coverage")
                    or (supply.get("summary") or {}).get("orderbook_coverage"),
                    "lane_counts": supply_lane_counts,
                },
            },
            {
                "id": "known_outcome",
                "label": "Observation Lag",
                "status": self._known_outcome_status(known),
                "count": _safe_int(known.get("candidate_count")),
                "markets": _safe_int(known.get("markets_scanned")),
                "blockers": _compact_blockers(
                    ((known.get("observation_eligibility") or {}).get("blocker_counts") or known.get("blocker_counts") or {}).keys()
                ),
                "metrics": {
                    "observation_eligible_count": _safe_int(
                        (known.get("observation_eligibility") or {}).get("eligible_count")
                        or known.get("observation_eligible_count")
                    ),
                    "observation_pool_candidates": _safe_int(known.get("observation_pool_candidates")),
                    "evaluated_candidates": _safe_int(known.get("evaluated_candidates")),
                    "context_destinations": (known.get("observation_context") or {}).get("destination_counts", {}),
                    "fillability": {
                        "full_fill_positive_edge_count": (known.get("fillability_report") or {}).get("full_fill_positive_edge_count"),
                        "positive_edge_capacity_usd": (known.get("fillability_report") or {}).get("positive_edge_capacity_usd"),
                        "by_fill_status": (known.get("fillability_report") or {}).get("by_fill_status", {}),
                    },
                    "decision_packets": {
                        "decision_packet_count": (known.get("decision_packet_summary") or {}).get("decision_packet_count"),
                        "decision_packets_written": (known.get("decision_packet_summary") or {}).get("decision_packets_written"),
                        "candidate_events_written": (known.get("decision_packet_summary") or {}).get("candidate_events_written"),
                    },
                    "candidate_lifecycle": {
                        "lifecycle_record_count": (known.get("candidate_lifecycle_summary") or {}).get("lifecycle_record_count"),
                        "lifecycle_records_written": (known.get("candidate_lifecycle_summary") or {}).get("lifecycle_records_written"),
                        "by_status": (known.get("candidate_lifecycle_summary") or {}).get("by_status", {}),
                    },
                    "blocker_counts": known.get("blocker_counts", {}),
                    "observation_eligibility_blocker_counts": (
                        (known.get("observation_eligibility") or {}).get("blocker_counts") or {}
                    ),
                },
            },
            {
                "id": "ladder",
                "label": "Ladder Consistency",
                "status": "alpha_rejected"
                if _safe_int(ladder.get("rejected_count")) > 0
                else "paper_evidence_needed",
                "count": _safe_int(ladder.get("candidate_count")),
                "markets": _safe_int(ladder.get("ladder_markets")),
                "blockers": _compact_blockers((ladder.get("blocker_counts") or {}).keys()),
                "metrics": {
                    "selected_groups": _safe_len(ladder.get("selected_ladder_groups")),
                    "rejected_count": _safe_int(ladder.get("rejected_count")),
                    "status_counts": ladder.get("status_counts", {}),
                },
            },
            {
                "id": "replay",
                "label": "Replay Evidence",
                "status": evidence.get("edge_status") or "missing",
                "count": _safe_int(evidence.get("record_count")),
                "markets": _safe_int(evidence.get("resolved_record_count")),
                "blockers": _compact_blockers((evidence.get("deployment_verdict") or {}).get("blockers", [])),
                "metrics": {
                    "tradeable_replay_count": _safe_int(evidence.get("tradeable_replay_count")),
                    "candidate_roi_per_1usd": evidence.get("candidate_roi_per_1usd"),
                    "orderbook_coverage": evidence.get("orderbook_coverage", {}),
                },
            },
            {
                "id": "run_lag",
                "label": "HRRR/NBM Run Lag",
                "status": (research.get("run_lag_evidence") or {}).get("status") or "missing",
                "count": _safe_int((research.get("run_lag_evidence") or {}).get("tracked_source_station_metrics")),
                "markets": _safe_int(research.get("markets_scanned")),
                "blockers": _compact_blockers([(research.get("high_resolution_ingest") or {}).get("reason")]),
                "metrics": {
                    "high_resolution_ingest": research.get("high_resolution_ingest", {}),
                    "run_lag_evidence": research.get("run_lag_evidence", {}),
                },
            },
        ]

    def _qa_gate(
        self,
        reports: Dict[str, Dict[str, Any]],
        artifacts: Dict[str, Dict[str, Any]],
        config: Any,
        live_report: Dict[str, Any],
    ) -> Dict[str, Any]:
        evidence = reports.get("evidence", {})
        verdict = evidence.get("deployment_verdict") or {}
        blockers = list(verdict.get("blockers", []) or [])
        if any(row["freshness"] == "missing" for row in artifacts.values()):
            blockers.append("weather_control_room_missing_artifact")
        if any(row["freshness"] == "stale" for row in artifacts.values()):
            blockers.append("weather_control_room_stale_artifact")
        if not bool(getattr(config, "allow_live_weather_trading", False)):
            blockers.append("allow_live_weather_trading_false")
        if verdict.get("accepted_for_live_weather_trading") is not True:
            blockers.append("weather_replay_not_live_accepted")
        blockers.extend(live_report.get("blockers", []) or [])
        blockers = _compact_blockers(blockers, limit=12)
        return {
            "schema_version": "weather_control_room_qa_gate_v1",
            "status": "pass" if not blockers else "blocked",
            "blockers": blockers,
            "blocker_records": blockers_to_records(blockers),
            "blocker_summary": blocker_summary(blockers),
            "release_certificate": live_report.get("release_certificate", {}),
            "non_negotiables": live_report.get("non_negotiables", []),
        }

    @staticmethod
    def _known_outcome_status(known: Dict[str, Any]) -> str:
        if _safe_int(known.get("candidate_count")) > 0:
            return "paper_evidence_needed"
        verdict = (known.get("coverage_audit") or {}).get("verdict")
        if verdict == "observation_eligibility_blocked":
            return "observation_eligibility_blocked"
        if verdict == "observation_pool_selection_blocked":
            return "observation_pool_selection_blocked"
        if verdict == "observation_context_or_orderbook_selection_needed":
            return "observation_context_needed"
        return "candidate_supply_needed"

    @staticmethod
    def _team_manifest() -> List[Dict[str, Any]]:
        return [
            {
                "id": "research",
                "label": "Research Team",
                "inputs": ["market universe", "resolution rules", "weather source docs", "settled labels"],
                "outputs": ["alpha cards", "source mappings", "lane disproof notes"],
                "success_metric": "resolved evidence that survives replay and fillability",
            },
            {
                "id": "builders",
                "label": "Builder Team",
                "inputs": ["alpha cards", "data contracts", "artifact schemas"],
                "outputs": ["typed modules", "command endpoints", "append-only evidence"],
                "success_metric": "features are replayable from stored evidence refs",
            },
            {
                "id": "qa",
                "label": "QA Team",
                "inputs": ["contracts", "golden cases", "paper/replay artifacts"],
                "outputs": ["gate reports", "live-block tests", "release verdicts"],
                "success_metric": "backend blocks slop and accidental live trading",
            },
            {
                "id": "design",
                "label": "Dashboard Team",
                "inputs": ["operator commands", "artifact summaries", "gate reports"],
                "outputs": ["control-room terminal", "real button wiring", "audit views"],
                "success_metric": "every button calls a backend command or shows not wired",
            },
            {
                "id": "strategy",
                "label": "Strategy Thinkers",
                "inputs": ["candidate supply", "fillability", "resolved replay"],
                "outputs": ["lane hypotheses", "acceptance gates", "blind-spot list"],
                "success_metric": "new lanes can be disproved before risking capital",
            },
        ]

    @staticmethod
    def _data_contracts() -> List[Dict[str, Any]]:
        return [
            {"name": "WeatherMarketSpec", "purpose": "Canonical market interpretation and blockers."},
            {"name": "ObservationSnapshot", "purpose": "Source-stamped weather observation payload."},
            {"name": "ThresholdStateSnapshot", "purpose": "Known, live, impossible, or ambiguous threshold state."},
            {"name": "OrderbookSnapshot", "purpose": "Executable CLOB depth, hash, and freshness."},
            {"name": "FillabilityReport", "purpose": "Walked-book price, size, slippage, and partial-fill policy."},
            {"name": "AlphaSignal", "purpose": "Lane-specific side, probability, proof, and disproof."},
            {"name": "DecisionPacket", "purpose": "Deterministic paper decision with evidence refs."},
            {"name": "LiveEligibilityReport", "purpose": "All live gates, blockers, and release constraints."},
            {"name": "OperatorCommand", "purpose": "Typed command from dashboard to backend command bus."},
            {"name": "AuditEvent", "purpose": "Append-only record of operator actions and command results."},
        ]

    @staticmethod
    def _blind_spots() -> List[Dict[str, str]]:
        return [
            {"id": "settlement_source", "label": "Observed outcome is not always settled outcome"},
            {"id": "timezone_dst", "label": "Local day, UTC, and DST boundary errors"},
            {"id": "official_products", "label": "METAR, ASOS, and official climate products can differ"},
            {"id": "rounding_units", "label": "F/C conversion and rounding can erase edge"},
            {"id": "station_qc", "label": "Station outage, relocation, maintenance, and QC corrections"},
            {"id": "fillability", "label": "Midpoint is not executable depth"},
            {"id": "paper_queue", "label": "Paper fills need queue, age, cancellation, and partial-fill assumptions"},
            {"id": "geoblock", "label": "Geoblock/legal eligibility is a runtime gate"},
            {"id": "token_mapping", "label": "YES/NO token, condition ID, and negative-risk confusion"},
            {"id": "dashboard_backend", "label": "Frontend disabled state is not a control"},
            {"id": "llm_authority", "label": "AI can annotate, not override deterministic gates"},
        ]

    def _report_summaries(self, reports: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        summaries: Dict[str, Dict[str, Any]] = {}
        for key, payload in reports.items():
            if not payload:
                summaries[key] = {"status": "missing"}
                continue
            summaries[key] = {
                "status": "ready",
                "schema_version": payload.get("schema_version") or payload.get("feature_schema_version"),
                "generated_at": payload.get("generated_at") or payload.get("updated_at"),
                "deployment_verdict": payload.get("deployment_verdict", {}),
                "counts": {
                    "markets_scanned": payload.get("markets_scanned"),
                    "candidate_count": payload.get("candidate_count"),
                    "decision_packet_count": (payload.get("decision_packet_summary") or {}).get("decision_packet_count"),
                    "lifecycle_record_count": (payload.get("candidate_lifecycle_summary") or {}).get("lifecycle_record_count"),
                    "record_count": payload.get("record_count"),
                    "research_candidate_count": payload.get("research_candidate_count"),
                },
            }
        return summaries

    @staticmethod
    def _supply_candidate(row: Dict[str, Any]) -> Dict[str, Any]:
        classification = row.get("classification") or {}
        microstructure = row.get("microstructure") or {}
        return {
            "lane": "candidate_supply",
            "status": "research_candidate",
            "market_id": classification.get("market_id") or row.get("market_id"),
            "question": row.get("question"),
            "side": "",
            "edge_after_cost": None,
            "fill_status": "",
            "station_id": classification.get("station_id"),
            "threshold": classification.get("threshold"),
            "blockers": _compact_blockers(classification.get("blockers", [])),
            "proof": [],
            "disproof": [],
            "metrics": {
                "research_score": row.get("research_score"),
                "liquidity": microstructure.get("liquidity"),
                "lanes": classification.get("alpha_lanes", []),
                "horizon_bucket": classification.get("horizon_bucket"),
            },
        }

    @staticmethod
    def _alpha_candidate(lane: str, row: Dict[str, Any]) -> Dict[str, Any]:
        classification = row.get("classification") or {}
        station_state = row.get("station_state") or {}
        return {
            "lane": lane,
            "status": row.get("status") or row.get("final_trade_status") or "unknown",
            "market_id": row.get("market_id") or classification.get("market_id"),
            "question": classification.get("question") or row.get("question"),
            "side": row.get("side") or row.get("selected_side") or "",
            "edge_after_cost": row.get("edge_after_cost") or row.get("net_edge"),
            "fill_status": row.get("fill_status") or (row.get("fill_simulation") or {}).get("status"),
            "station_id": classification.get("station_id") or station_state.get("station_id"),
            "threshold": classification.get("threshold"),
            "blockers": _compact_blockers(row.get("blockers", [])),
            "proof": [str(item) for item in row.get("proof", [])[:5]],
            "disproof": [str(item) for item in row.get("disproof", [])[:5]],
            "metrics": {
                "p_yes": row.get("p_yes"),
                "max_fillable_usd": row.get("max_fillable_usd"),
                "executable_price": row.get("executable_price"),
                "quality_flags": row.get("quality_flags", []),
            },
        }
