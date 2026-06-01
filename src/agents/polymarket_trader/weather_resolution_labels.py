"""
Resolution labels for weather-market evidence.

Labels must come from market/resolution surfaces, not inferred weather. This
module only parses unambiguous YES/NO outcomes and otherwise records pending or
ambiguous labels with blockers.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests
from termcolor import cprint

from .config import ExecutionMode, PolymarketCLIConfig
from .weather_evidence_store import WeatherEvidenceStore


RESOLUTION_LABEL_SCHEMA_VERSION = "weather_resolution_label_v1"


@dataclass(frozen=True)
class WeatherResolutionLabel:
    market_id: str
    label_status: str
    captured_at: str
    yes_resolved: Optional[bool] = None
    source: str = "polymarket_outcome_prices"
    resolution_timestamp: str = ""
    station_id: str = ""
    resolution_source: str = ""
    actual_value: Optional[float] = None
    actual_unit: str = ""
    question: str = ""
    slug: str = ""
    event_slug: str = ""
    quality_flags: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    raw_outcomes: List[str] = field(default_factory=list)
    raw_outcome_prices: List[float] = field(default_factory=list)
    source_metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = RESOLUTION_LABEL_SCHEMA_VERSION

    @property
    def resolved(self) -> bool:
        return self.label_status == "resolved" and self.yes_resolved is not None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherResolutionLabeler:
    """Parse official/resolution payloads into durable labels."""

    def label_from_gamma_market(
        self,
        raw_market: Dict[str, Any],
        *,
        event: Optional[Dict[str, Any]] = None,
        captured_at: Optional[str] = None,
        source_metadata: Optional[Dict[str, Any]] = None,
    ) -> WeatherResolutionLabel:
        event = event or {}
        metadata = self._source_metadata(raw_market, event, source_metadata)
        captured = captured_at or datetime.utcnow().isoformat()
        market_id = str(
            raw_market.get("conditionId")
            or raw_market.get("condition_id")
            or raw_market.get("id")
            or ""
        )
        outcomes = self._json_field(raw_market.get("outcomes"), [])
        prices = self._json_field(raw_market.get("outcomePrices"), [])
        parsed_prices = [self._safe_float(item) for item in prices]
        if len(outcomes) != 2 or len(parsed_prices) != 2 or any(item is None for item in parsed_prices):
            return WeatherResolutionLabel(
                market_id=market_id,
                label_status="ambiguous",
                captured_at=captured,
                question=str(raw_market.get("question") or event.get("title") or ""),
                slug=str(raw_market.get("slug") or event.get("slug") or ""),
                event_slug=str(event.get("slug") or ""),
                blockers=["resolution_outcome_shape_ambiguous"],
                raw_outcomes=[str(item) for item in outcomes] if isinstance(outcomes, list) else [],
                raw_outcome_prices=[float(item) for item in parsed_prices if item is not None],
                source_metadata=metadata,
            )

        yes_idx = next((idx for idx, label in enumerate(outcomes) if str(label).strip().lower() == "yes"), None)
        no_idx = next((idx for idx, label in enumerate(outcomes) if str(label).strip().lower() == "no"), None)
        if yes_idx is None or no_idx is None:
            return WeatherResolutionLabel(
                market_id=market_id,
                label_status="ambiguous",
                captured_at=captured,
                question=str(raw_market.get("question") or event.get("title") or ""),
                slug=str(raw_market.get("slug") or event.get("slug") or ""),
                event_slug=str(event.get("slug") or ""),
                blockers=["resolution_yes_no_outcome_missing"],
                raw_outcomes=[str(item) for item in outcomes],
                raw_outcome_prices=[float(item) for item in parsed_prices if item is not None],
                source_metadata=metadata,
            )

        yes_price = float(parsed_prices[yes_idx])
        no_price = float(parsed_prices[no_idx])
        closed = self._is_closed_or_resolved(raw_market)
        end_date = str(raw_market.get("endDate") or event.get("endDate") or "")
        base = {
            "market_id": market_id,
            "captured_at": captured,
            "resolution_timestamp": end_date,
            "question": str(raw_market.get("question") or event.get("title") or ""),
            "slug": str(raw_market.get("slug") or event.get("slug") or ""),
            "event_slug": str(event.get("slug") or ""),
            "raw_outcomes": [str(item) for item in outcomes],
            "raw_outcome_prices": [float(item) for item in parsed_prices if item is not None],
            "source_metadata": metadata,
        }
        if not closed:
            return WeatherResolutionLabel(label_status="pending", blockers=["resolution_market_not_closed"], **base)

        winner_resolution = self._yes_resolved_from_winner(raw_market, outcomes)
        price_resolution: Optional[bool] = None
        if yes_price >= 0.999 and no_price <= 0.001:
            price_resolution = True
        elif yes_price <= 0.001 and no_price >= 0.999:
            price_resolution = False

        if winner_resolution is not None and price_resolution is not None and winner_resolution != price_resolution:
            return WeatherResolutionLabel(
                label_status="ambiguous",
                blockers=["resolution_winner_price_conflict"],
                **base,
            )
        if price_resolution is True:
            return WeatherResolutionLabel(label_status="resolved", yes_resolved=True, **base)
        if price_resolution is False:
            return WeatherResolutionLabel(label_status="resolved", yes_resolved=False, **base)
        if winner_resolution is not None:
            return WeatherResolutionLabel(
                label_status="resolved",
                yes_resolved=winner_resolution,
                source="polymarket_winner_field",
                **base,
            )
        return WeatherResolutionLabel(label_status="ambiguous", blockers=["resolution_outcome_price_ambiguous"], **base)

    def labels_from_gamma_events(self, events: Iterable[Dict[str, Any]]) -> List[WeatherResolutionLabel]:
        labels: List[WeatherResolutionLabel] = []
        for event in events:
            for raw_market in event.get("markets", []) or []:
                if isinstance(raw_market, dict):
                    labels.append(self.label_from_gamma_market(raw_market, event=event))
        return labels

    @staticmethod
    def _source_metadata(
        raw_market: Dict[str, Any],
        event: Dict[str, Any],
        supplied: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        metadata = dict(supplied or {})
        metadata.update(
            {
                "gamma_condition_id": str(
                    raw_market.get("conditionId")
                    or raw_market.get("condition_id")
                    or ""
                ),
                "gamma_market_id": str(raw_market.get("id") or ""),
                "gamma_event_id": str(event.get("id") or ""),
                "closed": raw_market.get("closed"),
                "active": raw_market.get("active"),
                "resolved": raw_market.get("resolved")
                or raw_market.get("finalized")
                or raw_market.get("settled"),
                "resolution_status": raw_market.get("resolutionStatus")
                or raw_market.get("resolution_status")
                or raw_market.get("status"),
            }
        )
        return metadata

    @classmethod
    def _yes_resolved_from_winner(cls, raw_market: Dict[str, Any], outcomes: List[Any]) -> Optional[bool]:
        yes_idx = next((idx for idx, label in enumerate(outcomes) if str(label).strip().lower() == "yes"), None)
        no_idx = next((idx for idx, label in enumerate(outcomes) if str(label).strip().lower() == "no"), None)
        if yes_idx is None or no_idx is None:
            return None

        winner_text = cls._first_text(
            raw_market,
            (
                "winner",
                "winningOutcome",
                "winning_outcome",
                "resolvedOutcome",
                "resolved_outcome",
                "resolution",
            ),
        )
        if winner_text:
            normalized = winner_text.strip().lower()
            if normalized in {"yes", "no"}:
                return normalized == "yes"
            if normalized == str(outcomes[yes_idx]).strip().lower():
                return True
            if normalized == str(outcomes[no_idx]).strip().lower():
                return False

        winner_index = cls._first_int(
            raw_market,
            (
                "winnerIndex",
                "winningOutcomeIndex",
                "winning_outcome_index",
                "resolvedOutcomeIndex",
                "resolved_outcome_index",
            ),
        )
        if winner_index is not None:
            if winner_index == yes_idx:
                return True
            if winner_index == no_idx:
                return False
        return None

    @staticmethod
    def _first_text(payload: Dict[str, Any], keys: Iterable[str]) -> str:
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _first_int(payload: Dict[str, Any], keys: Iterable[str]) -> Optional[int]:
        for key in keys:
            value = payload.get(key)
            if value is None or value == "":
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _json_field(value: Any, default: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return default
        return value if value is not None else default

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_bool(raw: Any, default: bool = False) -> bool:
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on", "closed", "active"}

    @classmethod
    def _is_closed_or_resolved(cls, raw_market: Dict[str, Any]) -> bool:
        if cls._to_bool(raw_market.get("closed")):
            return True
        if raw_market.get("active") is not None and not cls._to_bool(raw_market.get("active"), True):
            return True
        for key in ("resolved", "finalized", "settled"):
            if cls._to_bool(raw_market.get(key)):
                return True
        resolution_status = str(
            raw_market.get("resolutionStatus")
            or raw_market.get("resolution_status")
            or raw_market.get("status")
            or ""
        ).strip().lower()
        return resolution_status in {"resolved", "finalized", "settled", "closed"}


class WeatherResolutionLabelCollector:
    """Collect Gamma resolution labels for markets seen in the evidence store."""

    def __init__(
        self,
        config: PolymarketCLIConfig,
        store: Optional[WeatherEvidenceStore] = None,
        session: Optional[requests.Session] = None,
    ):
        self.config = config
        self.store = store or WeatherEvidenceStore(config)
        self.session = session or requests.Session()
        self.labeler = WeatherResolutionLabeler()
        self.gamma_url = str(getattr(config, "polymarket_gamma_url", "https://gamma-api.polymarket.com") or "").rstrip("/")

    def collect(self, *, limit: int = 500, rerun_replay: bool = False) -> Dict[str, Any]:
        refs = self._evidence_market_refs()[: max(1, int(limit or 1))]
        labels: List[Dict[str, Any]] = []
        status_counts: Dict[str, int] = {}
        source_counts: Dict[str, int] = {}
        for ref in refs:
            for source in ref.get("source_surfaces", []) or []:
                source_counts[str(source)] = source_counts.get(str(source), 0) + 1
            raw_market, event, source_metadata = self._fetch_gamma_market(ref)
            if raw_market:
                label = self.labeler.label_from_gamma_market(
                    raw_market,
                    event=event,
                    source_metadata=source_metadata,
                )
            else:
                label = WeatherResolutionLabel(
                    market_id=str(ref.get("market_id") or ""),
                    label_status="unavailable",
                    captured_at=datetime.utcnow().isoformat(),
                    question=str(ref.get("question") or ""),
                    slug=str(ref.get("slug") or ""),
                    event_slug=str(ref.get("event_slug") or ""),
                    blockers=["resolution_gamma_market_unavailable"],
                    source_metadata=source_metadata,
                )
            payload = label.to_dict()
            labels.append(payload)
            status_counts[payload["label_status"]] = status_counts.get(payload["label_status"], 0) + 1

        written = self.store.append_resolution_labels(labels)
        summary = {
            "schema_version": "weather_resolution_label_collection_v1",
            "generated_at": datetime.utcnow().isoformat(),
            "markets_considered": len(refs),
            "labels_written": written,
            "by_label_status": status_counts,
            "by_evidence_source": source_counts,
            "output": str(self.store.resolution_labels_path),
        }
        if rerun_replay:
            from .weather_replay import WeatherReplayEngine

            replay_report = WeatherReplayEngine(self.config, self.store).write_replay_and_report()
            summary["replay_report"] = {
                "record_count": replay_report.get("record_count", 0),
                "resolved_record_count": replay_report.get("resolved_record_count", 0),
                "tradeable_replay_count": replay_report.get("tradeable_replay_count", 0),
                "edge_status": replay_report.get("edge_status", ""),
                "output": str(self.store.latest_report_path),
            }
        (self.store.root_dir / "label_collection_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return summary

    def _evidence_market_refs(self) -> List[Dict[str, Any]]:
        refs: Dict[str, Dict[str, Any]] = {}
        for row in self.store.read_market_tape():
            self._merge_ref(refs, row, "market_tape")
        for row in self.store.read_candidate_events():
            candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
            self._merge_ref(refs, {**candidate, **row}, "candidate_decisions")
        for row in self.store.read_feature_snapshots():
            self._merge_ref(refs, row, "feature_snapshots")
        for row in self.store.read_jsonl(self.store.replay_records_path):
            candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
            self._merge_ref(refs, {**candidate, **row}, "replay_records")
        for row in self.store.read_resolution_labels():
            self._merge_ref(refs, row, "resolution_labels")
        return list(refs.values())

    @staticmethod
    def _merge_ref(refs: Dict[str, Dict[str, Any]], row: Dict[str, Any], surface: str) -> None:
        if not isinstance(row, dict):
            return
        market_id = str(
            row.get("market_id")
            or row.get("condition_id")
            or row.get("conditionId")
            or ""
        ).strip()
        if not market_id:
            return
        ref = refs.setdefault(market_id, {"market_id": market_id, "source_surfaces": []})
        if surface not in ref["source_surfaces"]:
            ref["source_surfaces"].append(surface)
        for key in ("question", "slug", "event_slug"):
            value = row.get(key)
            if value and not ref.get(key):
                ref[key] = value

    def _fetch_gamma_market(self, ref: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        market_id = str(ref.get("market_id") or "").strip()
        slug = str(ref.get("slug") or "").strip()
        event_slug = str(ref.get("event_slug") or "").strip()
        metadata: Dict[str, Any] = {
            "gamma_url": self.gamma_url,
            "market_id": market_id,
            "slug": slug,
            "event_slug": event_slug,
            "evidence_sources": list(ref.get("source_surfaces", []) or []),
            "lookup_attempts": [],
            "matched_by": "",
        }

        def _record_attempt(path: str, params: Optional[Dict[str, Any]], matched: bool) -> None:
            metadata["lookup_attempts"].append(
                {
                    "path": path,
                    "params": params or {},
                    "matched": matched,
                }
            )

        for key in (market_id, slug):
            if not key:
                continue
            for path in (f"/markets/{key}", f"/markets/slug/{key}"):
                payload = self._gamma_get(path)
                market = self._coerce_market(payload)
                if market:
                    _record_attempt(path, None, True)
                    metadata["matched_by"] = "market_path"
                    return market, {}, metadata
                _record_attempt(path, None, False)
        for params in (
            {"condition_ids": market_id},
            {"conditionIds": market_id},
            {"id": market_id},
            {"slug": slug},
        ):
            if not any(params.values()):
                continue
            payload = self._gamma_get("/markets", params=params)
            market = self._coerce_market(payload)
            if market:
                _record_attempt("/markets", params, True)
                metadata["matched_by"] = "market_query"
                return market, {}, metadata
            _record_attempt("/markets", params, False)
        if event_slug:
            for path in (f"/events/slug/{event_slug}", f"/events/{event_slug}"):
                event = self._gamma_get(path)
                if isinstance(event, dict):
                    market = self._find_market_in_event(event, market_id, slug)
                    if market:
                        _record_attempt(path, None, True)
                        metadata["matched_by"] = "event_market"
                        return market, event, metadata
                _record_attempt(path, None, False)
        return {}, {}, metadata

    def _gamma_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        try:
            response = self.session.get(f"{self.gamma_url}{path}", params=params, timeout=20)
            response.raise_for_status()
            return response.json()
        except Exception:
            return {}

    @staticmethod
    def _coerce_market(payload: Any) -> Dict[str, Any]:
        if isinstance(payload, dict):
            if isinstance(payload.get("markets"), list) and payload["markets"]:
                return payload["markets"][0] if isinstance(payload["markets"][0], dict) else {}
            return payload
        if isinstance(payload, list) and payload:
            return payload[0] if isinstance(payload[0], dict) else {}
        return {}

    @staticmethod
    def _find_market_in_event(event: Dict[str, Any], market_id: str, slug: str) -> Dict[str, Any]:
        for market in event.get("markets", []) or []:
            if not isinstance(market, dict):
                continue
            identifiers = {
                str(market.get("conditionId") or ""),
                str(market.get("condition_id") or ""),
                str(market.get("id") or ""),
                str(market.get("slug") or ""),
            }
            if market_id in identifiers or (slug and slug in identifiers):
                return market
        return {}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Polymarket weather resolution labels")
    parser.add_argument("--data-dir", type=str, default="", help="Override Polymarket trader data directory")
    parser.add_argument("--limit", type=int, default=500, help="Maximum evidence markets to label")
    parser.add_argument("--replay", action="store_true", help="Rerun weather replay after writing labels")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    kwargs: Dict[str, Any] = {
        "execution_mode": ExecutionMode.DRY_RUN,
        "market_vertical": "weather",
        "search_symbols": ["WEATHER"],
    }
    if args.data_dir:
        kwargs["_data_dir_override"] = Path(args.data_dir)
    config = PolymarketCLIConfig(**kwargs)
    summary = WeatherResolutionLabelCollector(config).collect(limit=args.limit, rerun_replay=args.replay)
    cprint("Weather resolution label collection complete", "green")
    cprint(f"  Markets considered: {summary.get('markets_considered')}", "white")
    cprint(f"  Labels written: {summary.get('labels_written')}", "white")
    cprint(f"  By status: {summary.get('by_label_status')}", "white")
    if summary.get("replay_report"):
        cprint(f"  Replay: {summary.get('replay_report')}", "white")
    cprint(f"  Output: {summary.get('output')}", "white")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
