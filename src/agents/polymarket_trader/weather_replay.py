"""
Paper replay and evidence reporting for the weather alpha lane.

This module answers the only question that matters before live trading:
given the market price, weather features, and labels that were actually
available at each timestamp, would the strategy have made money after
execution assumptions?
"""

from __future__ import annotations

import argparse
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from termcolor import cprint

from .config import ExecutionMode, PolymarketCLIConfig
from .weather_contracts import FEATURE_SCHEMA_VERSION
from .weather_evidence_store import WeatherEvidenceStore
from .weather_orderbook_simulator import WeatherOrderbookFillSimulator


REPLAY_RECORD_SCHEMA_VERSION = "weather_replay_record_v1"
EVIDENCE_REPORT_SCHEMA_VERSION = "weather_evidence_report_v1"


@dataclass(frozen=True)
class WeatherReplayRecord:
    market_id: str
    decision_time: str
    side: str
    final_trade_status: str
    model_probability: Optional[float]
    market_probability: Optional[float]
    executable_price: Optional[float]
    executable_price_source: str
    edge_percent: Optional[float]
    size_usd: float
    replay_status: str
    accepted_by_gate: bool
    final_trade_side: str = ""
    final_trade_price: Optional[float] = None
    final_trade_size_usd: Optional[float] = None
    selected_win: Optional[bool] = None
    yes_resolved: Optional[bool] = None
    pnl_per_usd: Optional[float] = None
    pnl_usd: Optional[float] = None
    snapshot_time: str = ""
    label_time: str = ""
    question: str = ""
    source: str = "weather_gate"
    spread: Optional[float] = None
    available_depth_usd: Optional[float] = None
    fill_status: str = ""
    fill_ratio: Optional[float] = None
    filled_notional_usd: Optional[float] = None
    average_fill_price: Optional[float] = None
    blockers: List[str] = field(default_factory=list)
    edge_reason_flags: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)
    event_time_checks: Dict[str, Any] = field(default_factory=dict)
    station_mapping: Dict[str, Any] = field(default_factory=dict)
    feature_snapshot: Dict[str, Any] = field(default_factory=dict)
    candidate: Dict[str, Any] = field(default_factory=dict)
    label: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = REPLAY_RECORD_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherReplayEngine:
    def __init__(self, config: PolymarketCLIConfig, store: Optional[WeatherEvidenceStore] = None):
        self.config = config
        self.store = store or WeatherEvidenceStore(config)
        self.fill_simulator = WeatherOrderbookFillSimulator(
            default_request_size_usd=float(getattr(config, "min_position_usd", 5.0) or 5.0),
            allow_best_ask_without_depth=False,
        )

    def build_replay_records(self) -> List[WeatherReplayRecord]:
        market_tape = self.store.read_market_tape()
        features = self.store.read_feature_snapshots()
        candidates = self.store.read_candidate_events()
        labels = self.store.read_resolution_labels()

        tape_by_market = self._group_by_market(market_tape)
        features_by_market = self._group_by_market(features)
        labels_by_market = self._latest_labels(labels)

        records: List[WeatherReplayRecord] = []
        for event in candidates:
            candidate = event.get("candidate") if isinstance(event.get("candidate"), dict) else {}
            verdict = event.get("verdict") if isinstance(event.get("verdict"), dict) else {}
            market_id = str(event.get("market_id") or candidate.get("market_id") or "")
            if not market_id or not candidate:
                continue
            decision_time = str(event.get("captured_at") or event.get("timestamp") or "")
            tape = self._latest_at_or_before(tape_by_market.get(market_id, []), decision_time, "captured_at")
            feature = self._latest_at_or_before(features_by_market.get(market_id, []), decision_time, "captured_at")
            label = labels_by_market.get(market_id, {})
            records.append(self._record_from_evidence(event, candidate, verdict, tape, feature, label))
        return records

    def write_replay_and_report(
        self,
        *,
        min_resolved_markets: Optional[int] = None,
        min_trade_decisions: Optional[int] = None,
        min_positive_roi: float = 0.0,
    ) -> Dict[str, Any]:
        records = self.build_replay_records()
        self.store.write_replay_records([record.to_dict() for record in records])
        report = WeatherEvidenceReporter(
            config=self.config,
            min_resolved_markets=min_resolved_markets,
            min_trade_decisions=min_trade_decisions,
            min_positive_roi=min_positive_roi,
        ).score(records)
        self.store.write_report(report, WeatherEvidenceReporter.format_markdown(report))
        return report

    def _record_from_evidence(
        self,
        event: Dict[str, Any],
        candidate: Dict[str, Any],
        verdict: Dict[str, Any],
        tape: Dict[str, Any],
        feature: Dict[str, Any],
        label: Dict[str, Any],
    ) -> WeatherReplayRecord:
        side = str(candidate.get("side") or "").upper()
        final_status = str(event.get("final_trade_status") or "").strip()
        final_record = event.get("final_trade_record") if isinstance(event.get("final_trade_record"), dict) else {}
        final_side = str(
            event.get("final_trade_side")
            or final_record.get("side")
            or side
            or ""
        ).upper()
        replay_side = final_side or side
        decision_time = str(event.get("captured_at") or event.get("timestamp") or "")
        event_time_checks = self._event_time_checks(decision_time, tape, feature, label)
        final_price = self._safe_float(
            event.get("final_trade_price")
            if event.get("final_trade_price") is not None
            else final_record.get("price")
        )
        final_size = self._safe_float(
            event.get("final_trade_size_usd")
            if event.get("final_trade_size_usd") is not None
            else final_record.get("size_usd", final_record.get("requested", final_record.get("executed_size")))
        )
        blockers = self._unique(
            list(candidate.get("blockers", []) or [])
            + list(verdict.get("blockers", []) or [])
            + list(tape.get("blockers", []) or [])
        )
        accepted_by_gate = bool(event.get("accepted", verdict.get("accepted", False)))
        executable_price = self._executable_price(replay_side, tape)
        executable_source = self._executable_price_source(replay_side, tape)
        replay_size = float(final_size if final_size is not None else candidate.get("size_usd", 0.0) or 0.0)
        fill = self.fill_simulator.simulate(
            tape,
            replay_side,
            requested_size_usd=replay_size,
            limit_price=final_price if final_price is not None else executable_price,
        )
        fill_dict = fill.to_dict()
        if fill.full_fill and fill.average_price is not None:
            executable_price = fill.average_price
        available_depth = fill.total_depth_usd_at_limit
        if not tape:
            blockers.append("replay_market_tape_missing")
        if executable_price is None or executable_price <= 0:
            blockers.append("replay_executable_price_missing")
        elif executable_source != "orderbook_best_ask":
            blockers.append(f"replay_non_executable_price_source:{executable_source or 'missing'}")
        if not fill.full_fill:
            blockers.extend(fill.blockers or [f"replay_fill_{fill.status}"])
        if not feature:
            blockers.append("replay_feature_snapshot_missing")
        elif str(feature.get("feature_schema_version") or "") != FEATURE_SCHEMA_VERSION:
            blockers.append(f"replay_feature_schema_mismatch:{feature.get('feature_schema_version') or 'missing'}")
        if event_time_checks.get("market_tape_after_decision"):
            blockers.append("replay_market_tape_after_decision")
        if event_time_checks.get("feature_snapshot_after_decision"):
            blockers.append("replay_feature_snapshot_after_decision")
        if not accepted_by_gate:
            blockers.append("replay_gate_rejected")
        if final_status not in {"planned", "executed"}:
            blockers.append(f"replay_final_status_not_executable:{final_status or 'missing'}")

        label_status = str(label.get("label_status") or "")
        yes_resolved = label.get("yes_resolved") if label_status == "resolved" else None
        selected_win: Optional[bool] = None
        pnl_per_usd: Optional[float] = None
        pnl_usd: Optional[float] = None
        if label_status != "resolved":
            blockers.append(f"replay_label_{label_status or 'missing'}")
        elif replay_side in {"YES", "NO"} and executable_price is not None and executable_price > 0:
            selected_win = bool(yes_resolved) if replay_side == "YES" else not bool(yes_resolved)
            pnl_per_usd = ((1.0 - executable_price) / executable_price) if selected_win else -1.0
            pnl_usd = pnl_per_usd * replay_size

        replay_status = "replayed"
        if label_status != "resolved":
            replay_status = "unresolved"
        elif blockers:
            replay_status = "blocked"
        elif selected_win is True:
            replay_status = "win"
        elif selected_win is False:
            replay_status = "loss"

        return WeatherReplayRecord(
            market_id=str(candidate.get("market_id") or event.get("market_id") or ""),
            decision_time=str(event.get("captured_at") or ""),
            side=replay_side,
            final_trade_status=final_status,
            final_trade_side=final_side,
            final_trade_price=round(final_price, 6) if final_price is not None else None,
            final_trade_size_usd=round(final_size, 6) if final_size is not None else None,
            model_probability=self._safe_float(candidate.get("model_probability")),
            market_probability=self._yes_market_probability(candidate, tape),
            executable_price=round(executable_price, 6) if executable_price is not None else None,
            executable_price_source=executable_source,
            edge_percent=self._safe_float(candidate.get("edge_percent")),
            size_usd=float(final_size if final_size is not None else candidate.get("size_usd", 0.0) or 0.0),
            replay_status=replay_status,
            accepted_by_gate=accepted_by_gate,
            selected_win=selected_win,
            yes_resolved=yes_resolved if isinstance(yes_resolved, bool) else None,
            pnl_per_usd=round(pnl_per_usd, 6) if pnl_per_usd is not None else None,
            pnl_usd=round(pnl_usd, 6) if pnl_usd is not None else None,
            snapshot_time=str(tape.get("captured_at") or ""),
            label_time=str(label.get("captured_at") or ""),
            question=str(tape.get("question") or feature.get("question") or ""),
            source=str(event.get("source") or "weather_gate"),
            spread=self._safe_float(tape.get("spread")),
            available_depth_usd=available_depth,
            fill_status=str(fill_dict.get("status") or ""),
            fill_ratio=self._safe_float(fill_dict.get("fill_ratio")),
            filled_notional_usd=self._safe_float(fill_dict.get("filled_notional_usd")),
            average_fill_price=self._safe_float(fill_dict.get("average_price")),
            blockers=self._unique(blockers),
            edge_reason_flags=[str(item) for item in candidate.get("edge_reason_flags", []) or []],
            quality_flags=self._unique(
                list(candidate.get("quality_flags", []) or [])
                + list(tape.get("quality_flags", []) or [])
                + list(feature.get("quality_flags", []) or [])
            ),
            event_time_checks=event_time_checks,
            station_mapping=dict(feature.get("station_mapping", {}) or {}),
            feature_snapshot=feature,
            candidate=candidate,
            label=label,
        )

    @staticmethod
    def _group_by_market(rows: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get("market_id") or "")].append(row)
        for values in grouped.values():
            values.sort(key=lambda item: WeatherReplayEngine._parse_ts(item.get("captured_at")))
        return grouped

    @staticmethod
    def _latest_labels(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        latest: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            market_id = str(row.get("market_id") or "")
            if not market_id:
                continue
            current = latest.get(market_id)
            if current is None or WeatherReplayEngine._parse_ts(row.get("captured_at")) >= WeatherReplayEngine._parse_ts(current.get("captured_at")):
                latest[market_id] = row
        return latest

    @staticmethod
    def _latest_at_or_before(rows: List[Dict[str, Any]], timestamp: str, field: str) -> Dict[str, Any]:
        if not rows:
            return {}
        target = WeatherReplayEngine._parse_ts(timestamp)
        if target is None:
            return {}
        selected: Dict[str, Any] = {}
        for row in rows:
            row_ts = WeatherReplayEngine._parse_ts(row.get(field))
            if row_ts is None:
                continue
            if row_ts <= target:
                selected = row
            elif row_ts > target:
                break
        return selected

    @staticmethod
    def _parse_ts(value: Any) -> Optional[datetime]:
        if not value:
            return None
        text = str(value).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text).replace(tzinfo=None)
        except ValueError:
            return None

    @classmethod
    def _event_time_checks(
        cls,
        decision_time: str,
        tape: Dict[str, Any],
        feature: Dict[str, Any],
        label: Dict[str, Any],
    ) -> Dict[str, Any]:
        decision = cls._parse_ts(decision_time)
        tape_time = cls._parse_ts(tape.get("captured_at")) if tape else None
        feature_time = cls._parse_ts(feature.get("captured_at")) if feature else None
        label_time = cls._parse_ts(label.get("captured_at")) if label else None
        return {
            "decision_time": decision_time,
            "market_tape_time": str(tape.get("captured_at") or "") if tape else "",
            "feature_snapshot_time": str(feature.get("captured_at") or "") if feature else "",
            "label_time": str(label.get("captured_at") or "") if label else "",
            "decision_time_present": decision is not None,
            "market_tape_at_or_before_decision": bool(decision is not None and tape_time is not None and tape_time <= decision),
            "feature_snapshot_at_or_before_decision": bool(decision is not None and feature_time is not None and feature_time <= decision),
            "label_at_or_after_decision_or_missing": bool(label_time is None or decision is None or label_time >= decision),
            "market_tape_after_decision": bool(decision is not None and tape_time is not None and tape_time > decision),
            "feature_snapshot_after_decision": bool(decision is not None and feature_time is not None and feature_time > decision),
        }

    @staticmethod
    def _executable_price(side: str, tape: Dict[str, Any]) -> Optional[float]:
        if side == "YES":
            return WeatherReplayEngine._safe_float(tape.get("executable_yes_price"))
        if side == "NO":
            return WeatherReplayEngine._safe_float(tape.get("executable_no_price"))
        return None

    @staticmethod
    def _executable_price_source(side: str, tape: Dict[str, Any]) -> str:
        if side == "YES":
            return str(tape.get("executable_yes_price_source") or tape.get("executable_price_source") or "")
        if side == "NO":
            return str(tape.get("executable_no_price_source") or tape.get("executable_price_source") or "")
        return str(tape.get("executable_price_source") or "")

    @staticmethod
    def _available_depth(side: str, tape: Dict[str, Any]) -> Optional[float]:
        book = tape.get("yes_book" if side == "YES" else "no_book", {})
        if not isinstance(book, dict):
            return None
        return WeatherReplayEngine._safe_float(book.get("ask_depth_usd"))

    @staticmethod
    def _yes_market_probability(candidate: Dict[str, Any], tape: Dict[str, Any]) -> Optional[float]:
        yes_price = WeatherReplayEngine._safe_float(tape.get("yes_price"))
        if yes_price is not None:
            return yes_price
        side = str(candidate.get("side") or "").upper()
        market_probability = WeatherReplayEngine._safe_float(candidate.get("market_probability"))
        if market_probability is None:
            return None
        if side == "NO":
            return max(0.0, min(1.0, 1.0 - market_probability))
        return market_probability

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    @staticmethod
    def _unique(values: Iterable[Any]) -> List[str]:
        seen = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in seen:
                seen.append(text)
        return seen


class WeatherEvidenceReporter:
    def __init__(
        self,
        config: PolymarketCLIConfig,
        *,
        min_resolved_markets: Optional[int] = None,
        min_trade_decisions: Optional[int] = None,
        min_positive_roi: float = 0.0,
    ):
        self.config = config
        self.min_resolved_markets = (
            int(min_resolved_markets)
            if min_resolved_markets is not None
            else int(getattr(config, "weather_evidence_min_resolved_markets", 50) or 50)
        )
        self.min_trade_decisions = (
            int(min_trade_decisions)
            if min_trade_decisions is not None
            else int(getattr(config, "weather_evidence_min_trade_decisions", 20) or 20)
        )
        self.min_positive_roi = float(min_positive_roi)

    def score(self, records: Iterable[WeatherReplayRecord]) -> Dict[str, Any]:
        rows = list(records)
        resolved = [row for row in rows if row.yes_resolved is not None]
        tradeable = [row for row in resolved if not row.blockers and row.accepted_by_gate and row.pnl_per_usd is not None]
        wins = [row for row in tradeable if row.selected_win is True]
        pnl = sum(float(row.pnl_per_usd or 0.0) for row in tradeable)
        pnl_usd = sum(float(row.pnl_usd or 0.0) for row in tradeable)
        roi = pnl / len(tradeable) if tradeable else 0.0
        model_brier = self._brier(resolved, "model")
        market_brier = self._brier(resolved, "market")
        model_log_loss = self._log_loss(resolved, "model")
        market_log_loss = self._log_loss(resolved, "market")
        blockers = self._blockers(rows, resolved, tradeable, roi, model_brier, market_brier, model_log_loss, market_log_loss)
        concentration = self._concentration(tradeable)
        if concentration.get("max_market_pnl_share", 0.0) > 0.4 and len(tradeable) >= 3:
            blockers.append("weather_replay_pnl_too_concentrated")
        price_source_counts = dict(Counter(row.executable_price_source or "missing" for row in rows))
        executable_source_count = int(price_source_counts.get("orderbook_best_ask", 0) or 0)
        fill_coverage = WeatherOrderbookFillSimulator.summarize(
            {
                "status": row.fill_status or "missing",
                "requested_size_usd": row.size_usd,
                "filled_notional_usd": row.filled_notional_usd or 0.0,
            }
            for row in rows
        )
        edge_status = self._edge_status(blockers, rows, tradeable, roi)

        source_families = sorted(
            {
                str(row.feature_snapshot.get("selected_source_family") or "")
                for row in rows
                if row.feature_snapshot
            }
        )
        source_families = [item for item in source_families if item]
        report = {
            "schema_version": EVIDENCE_REPORT_SCHEMA_VERSION,
            "generated_at": datetime.utcnow().isoformat(),
            "market_vertical": "weather",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "record_count": len(rows),
            "resolved_record_count": len(resolved),
            "tradeable_replay_count": len(tradeable),
            "win_rate": round(len(wins) / len(tradeable), 4) if tradeable else None,
            "candidate_roi_per_1usd": round(roi, 6),
            "candidate_pnl_per_1usd_staked": round(pnl, 6),
            "candidate_pnl_usd": round(pnl_usd, 6),
            "model_brier": model_brier,
            "market_brier": market_brier,
            "model_log_loss": model_log_loss,
            "market_log_loss": market_log_loss,
            "by_status": dict(Counter(row.replay_status for row in rows)),
            "by_blocker": self._blocker_counts(rows),
            "by_final_trade_status": dict(Counter(row.final_trade_status or "missing" for row in rows)),
            "price_source_counts": price_source_counts,
            "orderbook_coverage": {
                "orderbook_best_ask_records": executable_source_count,
                "record_count": len(rows),
                "coverage_ratio": round(executable_source_count / len(rows), 4) if rows else 0.0,
            },
            "fill_coverage": fill_coverage,
            "event_time_integrity": self._event_time_integrity(rows),
            "by_location": self._group_summary(tradeable, "location"),
            "by_metric": self._group_summary(tradeable, "metric"),
            "concentration": concentration,
            "edge_status": edge_status,
            "measurement_scope": {
                "counts_gate_candidates": True,
                "counts_final_planned_or_executed_only_as_tradeable": True,
                "requires_orderbook_best_ask_for_tradeable_replay": True,
                "live_weather_trading_evaluated": False,
            },
            "validated_source_families": source_families,
            "validated_min_probability_gap": round(float(getattr(self.config, "weather_min_probability_gap", 0.08) or 0.08), 4),
            "deployment_verdict": {
                "accepted_for_live_weather_trading": False,
                "accepted_for_paper_weather_trading": not blockers,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "validated_source_families": source_families,
                "validated_min_probability_gap": round(float(getattr(self.config, "weather_min_probability_gap", 0.08) or 0.08), 4),
                "blockers": blockers,
                "live_blockers": ["weather_live_requires_preflight_and_manual_enablement"],
                "required_evidence": [
                    f">= {self.min_resolved_markets} resolved replay records",
                    f">= {self.min_trade_decisions} executable replay decisions",
                    "positive replay ROI after executable-price assumptions",
                    "model Brier/log loss beat market-implied probabilities",
                    "PnL not dominated by one market",
                    "separate live preflight and manual enablement",
                ],
                "remaining_requirements": blockers,
            },
            "top_replay_records": [
                row.to_dict()
                for row in sorted(
                    tradeable,
                    key=lambda item: abs(float(item.edge_percent or 0.0)),
                    reverse=True,
                )[:20]
            ],
        }
        return report

    @staticmethod
    def _edge_status(
        blockers: List[str],
        rows: List[WeatherReplayRecord],
        tradeable: List[WeatherReplayRecord],
        roi: float,
    ) -> str:
        if not rows or not tradeable:
            return "insufficient_evidence"
        if roi <= 0:
            return "negative_edge"
        if blockers:
            return "insufficient_evidence"
        return "paper_edge_passed"

    def _blockers(
        self,
        rows: List[WeatherReplayRecord],
        resolved: List[WeatherReplayRecord],
        tradeable: List[WeatherReplayRecord],
        roi: float,
        model_brier: Optional[float],
        market_brier: Optional[float],
        model_log_loss: Optional[float],
        market_log_loss: Optional[float],
    ) -> List[str]:
        blockers: List[str] = []
        if not rows:
            blockers.append("weather_replay_no_candidate_records")
        if len(resolved) < self.min_resolved_markets:
            blockers.append(f"need_at_least_{self.min_resolved_markets}_resolved_replay_records")
        if len(tradeable) < self.min_trade_decisions:
            blockers.append(f"need_at_least_{self.min_trade_decisions}_executable_replay_decisions")
        if roi <= self.min_positive_roi:
            blockers.append("weather_replay_roi_not_positive")
        if model_brier is None or market_brier is None or model_brier >= market_brier:
            blockers.append("weather_replay_model_brier_not_better_than_market")
        if model_log_loss is None or market_log_loss is None or model_log_loss >= market_log_loss:
            blockers.append("weather_replay_model_log_loss_not_better_than_market")
        return blockers

    @staticmethod
    def _brier(rows: List[WeatherReplayRecord], source: str) -> Optional[float]:
        pairs = []
        for row in rows:
            probability = row.model_probability if source == "model" else row.market_probability
            if probability is None or row.yes_resolved is None:
                continue
            outcome = 1.0 if row.yes_resolved else 0.0
            pairs.append((float(probability), outcome))
        if not pairs:
            return None
        return round(sum((prob - outcome) ** 2 for prob, outcome in pairs) / len(pairs), 6)

    @staticmethod
    def _log_loss(rows: List[WeatherReplayRecord], source: str) -> Optional[float]:
        pairs = []
        for row in rows:
            probability = row.model_probability if source == "model" else row.market_probability
            if probability is None or row.yes_resolved is None:
                continue
            outcome = 1.0 if row.yes_resolved else 0.0
            p = max(0.02, min(0.98, float(probability)))
            pairs.append(-math.log(p if outcome else 1.0 - p))
        if not pairs:
            return None
        return round(sum(pairs) / len(pairs), 6)

    @staticmethod
    def _blocker_counts(rows: List[WeatherReplayRecord]) -> Dict[str, int]:
        counts: Counter[str] = Counter()
        for row in rows:
            for blocker in row.blockers:
                counts[str(blocker)] += 1
        return dict(counts)

    @staticmethod
    def _group_summary(rows: List[WeatherReplayRecord], attr: str) -> Dict[str, Any]:
        groups: Dict[str, List[WeatherReplayRecord]] = defaultdict(list)
        for row in rows:
            value = ""
            if attr == "location":
                value = str(row.feature_snapshot.get("station_mapping", {}).get("location_name") or "")
            elif attr == "metric":
                value = str(row.feature_snapshot.get("metric") or "")
            groups[value or "unknown"].append(row)
        return {
            key: {
                "records": len(group),
                "roi_per_1usd": round(sum(float(row.pnl_per_usd or 0.0) for row in group) / max(1, len(group)), 6),
            }
            for key, group in sorted(groups.items(), key=lambda item: len(item[1]), reverse=True)[:20]
        }

    @staticmethod
    def _concentration(rows: List[WeatherReplayRecord]) -> Dict[str, Any]:
        total_abs = sum(abs(float(row.pnl_per_usd or 0.0)) for row in rows)
        if total_abs <= 0:
            return {"max_market_pnl_share": 0.0, "max_market_id": ""}
        shares = [
            (row.market_id, abs(float(row.pnl_per_usd or 0.0)) / total_abs)
            for row in rows
        ]
        market_id, share = max(shares, key=lambda item: item[1])
        return {"max_market_pnl_share": round(share, 6), "max_market_id": market_id}

    @staticmethod
    def _event_time_integrity(rows: List[WeatherReplayRecord]) -> Dict[str, Any]:
        missing_decision = 0
        tape_after = 0
        feature_after = 0
        tape_before = 0
        feature_before = 0
        for row in rows:
            checks = row.event_time_checks or {}
            if not checks.get("decision_time_present"):
                missing_decision += 1
            if checks.get("market_tape_after_decision"):
                tape_after += 1
            if checks.get("feature_snapshot_after_decision"):
                feature_after += 1
            if checks.get("market_tape_at_or_before_decision"):
                tape_before += 1
            if checks.get("feature_snapshot_at_or_before_decision"):
                feature_before += 1
        return {
            "record_count": len(rows),
            "decision_time_missing_count": missing_decision,
            "market_tape_at_or_before_decision_count": tape_before,
            "feature_snapshot_at_or_before_decision_count": feature_before,
            "market_tape_after_decision_count": tape_after,
            "feature_snapshot_after_decision_count": feature_after,
            "passed": bool(rows) and missing_decision == 0 and tape_after == 0 and feature_after == 0,
        }

    @staticmethod
    def format_markdown(report: Dict[str, Any]) -> str:
        verdict = report.get("deployment_verdict", {})
        lines = [
            "# Polymarket Weather Evidence Report",
            "",
            f"- Generated: `{report.get('generated_at')}`",
            f"- Evidence schema: `{report.get('schema_version')}`",
            f"- Feature schema: `{report.get('feature_schema_version')}`",
            f"- Replay records: `{report.get('record_count')}`",
            f"- Resolved records: `{report.get('resolved_record_count')}`",
            f"- Executable replay decisions: `{report.get('tradeable_replay_count')}`",
            f"- Candidate ROI per $1: `{report.get('candidate_roi_per_1usd')}`",
            f"- Model Brier: `{report.get('model_brier')}`",
            f"- Market Brier: `{report.get('market_brier')}`",
            f"- Edge status: `{report.get('edge_status')}`",
            f"- Accepted for paper weather trading: `{verdict.get('accepted_for_paper_weather_trading')}`",
            f"- Accepted for live weather trading: `{verdict.get('accepted_for_live_weather_trading')}`",
            "",
            "## Blockers",
        ]
        blockers = verdict.get("blockers") or []
        lines.extend([f"- `{blocker}`" for blocker in blockers] or ["- None"])
        live_blockers = verdict.get("live_blockers") or []
        lines.extend(["", "## Live Blockers"])
        lines.extend([f"- `{blocker}`" for blocker in live_blockers] or ["- None"])
        lines.extend(["", "## Coverage"])
        lines.append(f"- Final trade statuses: `{report.get('by_final_trade_status', {})}`")
        lines.append(f"- Replay statuses: `{report.get('by_status', {})}`")
        lines.append(f"- Price sources: `{report.get('price_source_counts', {})}`")
        lines.append(f"- Orderbook coverage: `{report.get('orderbook_coverage', {})}`")
        lines.append(f"- Fill coverage: `{report.get('fill_coverage', {})}`")
        lines.append(f"- Event-time integrity: `{report.get('event_time_integrity', {})}`")
        lines.append(f"- Blocker counts: `{report.get('by_blocker', {})}`")
        lines.extend(["", "## Top Replay Records"])
        for row in report.get("top_replay_records", [])[:10]:
            lines.append(
                f"- `{row.get('side')}` edge `{row.get('edge_percent')}` "
                f"win=`{row.get('selected_win')}` pnl=`{row.get('pnl_per_usd')}` | "
                f"{row.get('question')}"
            )
        lines.append("")
        return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay weather evidence and write an alpha evidence report")
    parser.add_argument("--data-dir", type=str, default="", help="Override Polymarket trader data directory")
    parser.add_argument("--min-resolved", type=int, default=None)
    parser.add_argument("--min-trades", type=int, default=None)
    parser.add_argument("--min-roi", type=float, default=0.0)
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
    report = WeatherReplayEngine(config).write_replay_and_report(
        min_resolved_markets=args.min_resolved,
        min_trade_decisions=args.min_trades,
        min_positive_roi=args.min_roi,
    )
    verdict = report.get("deployment_verdict", {})
    cprint("Weather evidence report written", "green")
    cprint(f"  Replay records: {report.get('record_count')}", "white")
    cprint(f"  Resolved records: {report.get('resolved_record_count')}", "white")
    cprint(f"  Executable decisions: {report.get('tradeable_replay_count')}", "white")
    cprint(f"  Paper accepted: {verdict.get('accepted_for_paper_weather_trading')}", "white")
    if verdict.get("blockers"):
        cprint(f"  Blockers: {', '.join(verdict.get('blockers', []))}", "yellow")
    cprint(f"  Output: {config.data_dir / 'weather_evidence'}", "white")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
