"""
Durable evidence store for the weather alpha lane.

This store is deliberately append-only JSONL. It keeps the alpha proof trail
auditable: market tape, feature packets, candidate decisions, labels, replay
records, and reports are all written as separate surfaces.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import PolymarketCLIConfig
from .models import CLIMarket
from .weather_market_tape import WeatherMarketTapeSnapshot


EVIDENCE_STORE_SCHEMA_VERSION = "weather_evidence_store_v1"
FEATURE_EVIDENCE_SCHEMA_VERSION = "weather_feature_evidence_v1"
CANDIDATE_EVIDENCE_SCHEMA_VERSION = "weather_candidate_evidence_v1"


class WeatherEvidenceStore:
    def __init__(
        self,
        config: PolymarketCLIConfig,
        root_dir: Optional[Path | str] = None,
    ):
        self.config = config
        self.root_dir = Path(root_dir) if root_dir else config.data_dir / "weather_evidence"
        self.root_dir.mkdir(parents=True, exist_ok=True)

    @property
    def market_tape_path(self) -> Path:
        return self.root_dir / "market_tape.jsonl"

    @property
    def feature_snapshots_path(self) -> Path:
        return self.root_dir / "feature_snapshots.jsonl"

    @property
    def candidate_decisions_path(self) -> Path:
        return self.root_dir / "candidate_decisions.jsonl"

    @property
    def decision_packets_path(self) -> Path:
        return self.root_dir / "decision_packets.jsonl"

    @property
    def candidate_lifecycle_path(self) -> Path:
        return self.root_dir / "candidate_lifecycle.jsonl"

    @property
    def resolution_labels_path(self) -> Path:
        return self.root_dir / "resolution_labels.jsonl"

    @property
    def replay_records_path(self) -> Path:
        return self.root_dir / "replay_records.jsonl"

    @property
    def latest_report_path(self) -> Path:
        return self.root_dir / "latest_weather_evidence_report.json"

    @property
    def latest_report_markdown_path(self) -> Path:
        return self.root_dir / "latest_weather_evidence_report.md"

    def append_market_tape(
        self,
        snapshots: Iterable[WeatherMarketTapeSnapshot | Dict[str, Any]],
        *,
        cycle: Optional[int] = None,
    ) -> int:
        count = 0
        for snapshot in snapshots:
            payload = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot)
            payload.setdefault("schema_version", "weather_market_tape_v1")
            if cycle is not None:
                payload["cycle"] = cycle
            self.append_jsonl(self.market_tape_path, payload)
            count += 1
        return count

    def append_feature_snapshots(
        self,
        markets: Iterable[CLIMarket],
        price_context: Dict[str, Any],
        *,
        cycle: Optional[int] = None,
        captured_at: Optional[str] = None,
    ) -> int:
        captured = captured_at or datetime.utcnow().isoformat()
        count = 0
        for market in markets:
            market_id = str(getattr(market, "condition_id", "") or "")
            context = dict(price_context.get(market_id, {}) or {}) if isinstance(price_context, dict) else {}
            if not context:
                continue
            payload = {
                "schema_version": FEATURE_EVIDENCE_SCHEMA_VERSION,
                "captured_at": captured,
                "cycle": cycle,
                "market_id": market_id,
                "question": str(getattr(market, "question", "") or ""),
                "end_date": self._iso_datetime(getattr(market, "end_date", None)),
                "feature_schema_version": context.get("feature_schema_version"),
                "status": context.get("status"),
                "selected_source_id": context.get("selected_source_id"),
                "selected_source_family": context.get("selected_source_family"),
                "weather_probability": context.get("weather_probability"),
                "weather_confidence": context.get("weather_confidence"),
                "weather_edge_percent": context.get("weather_edge_percent"),
                "recommended_side": context.get("recommended_side"),
                "target_date": context.get("target_date"),
                "metric": context.get("metric"),
                "threshold": context.get("threshold"),
                "station_mapping": context.get("station_mapping", {}),
                "source_statuses": context.get("source_statuses", {}),
                "forecast_snapshots": context.get("forecast_snapshots", []),
                "edge_reason_flags": context.get("edge_reason_flags", []),
                "quality_flags": context.get("quality_flags", []),
                "feature_blockers": context.get("feature_blockers", []),
                "station_bias": context.get("station_bias", {}),
                "latency_signals": context.get("latency_signals", {}),
                "run_lag_signals": context.get("run_lag_signals", {}),
                "model_update_events": context.get("model_update_events", []),
                "high_resolution_sources": context.get("high_resolution_sources", []),
                "forecast_model_packet": context.get("forecast_model_packet", {}),
                "ai_decision": context.get("ai_decision", {}),
                "market_spec": context.get("market_spec", {}),
                "evidence_refs": context.get("evidence_refs", {}),
                "asof_time": context.get("asof_time", ""),
                "market_tape_snapshot": context.get("market_tape_snapshot", {}),
                "raw_forecast_metrics": context.get("raw_forecast_metrics", {}),
                "forecast_adjustments": context.get("forecast_adjustments", {}),
                "feature_packet": context.get("feature_packet", {}),
            }
            self.append_jsonl(self.feature_snapshots_path, payload)
            count += 1
        return count

    def append_candidate_events(
        self,
        events: Iterable[Dict[str, Any]],
        *,
        cycle: Optional[int] = None,
        captured_at: Optional[str] = None,
    ) -> int:
        captured = captured_at or datetime.utcnow().isoformat()
        count = 0
        for event in events:
            event_payload = dict(event)
            payload = {
                "schema_version": CANDIDATE_EVIDENCE_SCHEMA_VERSION,
                "stored_at": captured,
                "cycle": cycle,
                **event_payload,
            }
            payload.setdefault("captured_at", captured)
            self.append_jsonl(self.candidate_decisions_path, payload)
            count += 1
        return count

    def append_decision_packets(
        self,
        packets: Iterable[Dict[str, Any]],
        *,
        captured_at: Optional[str] = None,
    ) -> int:
        captured = captured_at or datetime.utcnow().isoformat()
        count = 0
        for packet in packets:
            payload = dict(packet)
            payload.setdefault("stored_at", captured)
            self.append_jsonl(self.decision_packets_path, payload)
            count += 1
        return count

    def append_candidate_lifecycle(
        self,
        records: Iterable[Dict[str, Any]],
        *,
        captured_at: Optional[str] = None,
    ) -> int:
        captured = captured_at or datetime.utcnow().isoformat()
        count = 0
        for record in records:
            payload = dict(record)
            payload.setdefault("stored_at", captured)
            self.append_jsonl(self.candidate_lifecycle_path, payload)
            count += 1
        return count

    def append_resolution_labels(self, labels: Iterable[Dict[str, Any]]) -> int:
        count = 0
        for label in labels:
            self.append_jsonl(self.resolution_labels_path, dict(label))
            count += 1
        return count

    def write_replay_records(self, records: Iterable[Dict[str, Any]]) -> int:
        rows = list(records)
        self.replay_records_path.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )
        return len(rows)

    def write_report(self, report: Dict[str, Any], markdown: str) -> None:
        self.latest_report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        self.latest_report_markdown_path.write_text(markdown, encoding="utf-8")

    def read_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def read_market_tape(self) -> List[Dict[str, Any]]:
        return self.read_jsonl(self.market_tape_path)

    def read_feature_snapshots(self) -> List[Dict[str, Any]]:
        return self.read_jsonl(self.feature_snapshots_path)

    def read_candidate_events(self) -> List[Dict[str, Any]]:
        return self.read_jsonl(self.candidate_decisions_path)

    def read_decision_packets(self) -> List[Dict[str, Any]]:
        return self.read_jsonl(self.decision_packets_path)

    def read_candidate_lifecycle(self) -> List[Dict[str, Any]]:
        return self.read_jsonl(self.candidate_lifecycle_path)

    def read_resolution_labels(self) -> List[Dict[str, Any]]:
        return self.read_jsonl(self.resolution_labels_path)

    @staticmethod
    def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")

    @staticmethod
    def _iso_datetime(value: Any) -> str:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value or "")
