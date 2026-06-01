"""
Evidence-driven edge discovery board for Polymarket weather.

This module does not grant trade permission. It reads the paper evidence trail
and turns blockers into the next concrete alpha-building workstream.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from termcolor import cprint

from .config import ExecutionMode, PolymarketCLIConfig
from .weather_contracts import FEATURE_SCHEMA_VERSION
from .weather_evidence_store import WeatherEvidenceStore


DISCOVERY_SCHEMA_VERSION = "weather_edge_discovery_v1"


@dataclass(frozen=True)
class WeatherEdgeHypothesisStatus:
    code: str
    title: str
    status: str
    priority: int
    evidence_count: int
    blockers: List[str] = field(default_factory=list)
    why_it_can_create_edge: str = ""
    next_actions: List[str] = field(default_factory=list)
    promotion_signal: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WeatherEdgeDiscoveryBoard:
    """Summarize where edge building actually stands from saved evidence."""

    def __init__(
        self,
        config: Optional[PolymarketCLIConfig] = None,
        store: Optional[WeatherEvidenceStore] = None,
        root_dir: Optional[Path | str] = None,
    ):
        self.config = config or PolymarketCLIConfig(
            execution_mode=ExecutionMode.DRY_RUN,
            market_vertical="weather",
            search_symbols=["WEATHER"],
        )
        self.store = store or WeatherEvidenceStore(self.config, root_dir=root_dir)
        self.root_dir = self.store.root_dir

    @property
    def latest_report_path(self) -> Path:
        return self.root_dir / "latest_weather_edge_discovery_report.json"

    @property
    def latest_report_markdown_path(self) -> Path:
        return self.root_dir / "latest_weather_edge_discovery_report.md"

    def build_report(self, write: bool = True) -> Dict[str, Any]:
        evidence_report = self._read_json(self.store.latest_report_path)
        feature_rows = self.store.read_feature_snapshots()
        candidate_rows = self.store.read_candidate_events()
        label_rows = self.store.read_resolution_labels()
        replay_rows = self.store.read_jsonl(self.store.replay_records_path)
        market_tape_rows = self.store.read_market_tape()

        summary = self._build_summary(
            evidence_report=evidence_report,
            feature_rows=feature_rows,
            candidate_rows=candidate_rows,
            label_rows=label_rows,
            replay_rows=replay_rows,
            market_tape_rows=market_tape_rows,
        )
        hypotheses = self._build_hypotheses(summary, feature_rows, candidate_rows, replay_rows)
        phase = self._current_phase(summary, hypotheses)
        report = {
            "schema_version": DISCOVERY_SCHEMA_VERSION,
            "generated_at": datetime.utcnow().isoformat(),
            "market_vertical": "weather",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "current_phase": phase,
            "edge_built": bool(summary["paper_accepted"] and summary["resolved_record_count"] > 0),
            "live_weather_trading_allowed": False,
            "summary": summary,
            "hypotheses": [hypothesis.to_dict() for hypothesis in hypotheses],
            "next_actions": self._next_actions(phase, summary, hypotheses),
            "promotion_bar": {
                "paper_requires": [
                    "resolved replay records above threshold",
                    "executable replay decisions above threshold",
                    "positive after-cost replay ROI",
                    "model Brier/log loss better than market baseline",
                    "no single market/date/location dominates PnL",
                ],
                "live_requires": [
                    "accepted paper alpha report",
                    "matching feature schema and model config",
                    "clean preflight, risk, and geoblock checks",
                    "manual live weather enablement",
                ],
            },
            "artifacts": {
                "json": str(self.latest_report_path),
                "markdown": str(self.latest_report_markdown_path),
                "evidence_report": str(self.store.latest_report_path),
            },
        }
        if write:
            self.latest_report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
            self.latest_report_markdown_path.write_text(self._format_markdown(report), encoding="utf-8")
        return report

    def _build_summary(
        self,
        *,
        evidence_report: Dict[str, Any],
        feature_rows: List[Dict[str, Any]],
        candidate_rows: List[Dict[str, Any]],
        label_rows: List[Dict[str, Any]],
        replay_rows: List[Dict[str, Any]],
        market_tape_rows: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        verdict = evidence_report.get("deployment_verdict", {}) if isinstance(evidence_report, dict) else {}
        by_blocker = _counter_from_dict(evidence_report.get("by_blocker", {}))
        if not by_blocker and replay_rows:
            by_blocker = Counter(blocker for row in replay_rows for blocker in row.get("blockers", []))

        final_status_counts = _counter_from_dict(evidence_report.get("by_final_trade_status", {}))
        if not final_status_counts and candidate_rows:
            final_status_counts = Counter(str(row.get("final_trade_status") or "missing") for row in candidate_rows)

        replay_status_counts = _counter_from_dict(evidence_report.get("by_status", {}))
        if not replay_status_counts and replay_rows:
            replay_status_counts = Counter(str(row.get("replay_status") or "missing") for row in replay_rows)

        source_family_counts = Counter(
            str(row.get("selected_source_family") or row.get("feature_packet", {}).get("selected_source_family") or "missing")
            for row in feature_rows
        )
        source_family_counts.pop("", None)

        label_status_counts = Counter(str(row.get("label_status") or "missing") for row in label_rows)
        executable_price_counts = Counter(
            str(
                row.get("executable_price_source")
                or row.get("price_source")
                or row.get("executable_yes_price_source")
                or "missing"
            )
            for row in market_tape_rows
        )
        station_bias_counts = Counter(
            str((row.get("station_bias") or {}).get("status") or "missing")
            for row in feature_rows
        )
        latency_status_counts = Counter(
            str((row.get("latency_signals") or {}).get("status") or "missing")
            for row in feature_rows
        )
        feature_status_counts = Counter(str(row.get("status") or "missing") for row in feature_rows)

        resolved_record_count = _int(
            evidence_report.get("resolved_record_count"),
            sum(1 for row in replay_rows if row.get("yes_resolved") is not None),
        )
        tradeable_replay_count = _int(
            evidence_report.get("tradeable_replay_count"),
            sum(
                1
                for row in replay_rows
                if row.get("accepted_by_gate")
                and row.get("pnl_per_usd") is not None
                and not row.get("blockers")
            ),
        )
        record_count = _int(evidence_report.get("record_count"), len(replay_rows))
        paper_accepted = bool(verdict.get("accepted_for_paper_weather_trading"))
        blocker_list = sorted(by_blocker)

        near_threshold_count = 0
        far_from_threshold_count = 0
        for row in feature_rows:
            threshold = _float_or_none(row.get("threshold"))
            metric_value = _forecast_metric_value(row)
            if threshold is None or metric_value is None:
                continue
            if abs(metric_value - threshold) <= _near_threshold_band(row):
                near_threshold_count += 1
            else:
                far_from_threshold_count += 1

        high_res_status_counts = Counter()
        model_update_event_counts = Counter()
        actionable_model_update_events = 0
        for row in feature_rows:
            for source in row.get("high_resolution_sources", []) or []:
                if isinstance(source, dict):
                    high_res_status_counts[str(source.get("status") or "missing")] += 1
            for event in row.get("model_update_events", []) or []:
                if isinstance(event, dict):
                    model_update_event_counts[str(event.get("event_type") or "missing")] += 1
                    if bool(event.get("actionable_for_research")):
                        actionable_model_update_events += 1

        return {
            "record_count": record_count,
            "market_tape_count": len(market_tape_rows),
            "feature_snapshot_count": len(feature_rows),
            "candidate_decision_count": len(candidate_rows),
            "label_count": len(label_rows),
            "replay_record_count": len(replay_rows),
            "resolved_record_count": resolved_record_count,
            "tradeable_replay_count": tradeable_replay_count,
            "paper_accepted": paper_accepted,
            "edge_status": str(evidence_report.get("edge_status") or "missing"),
            "candidate_roi_per_1usd": _float_or_none(evidence_report.get("candidate_roi_per_1usd")),
            "model_brier": _float_or_none(evidence_report.get("model_brier")),
            "market_brier": _float_or_none(evidence_report.get("market_brier")),
            "blocker_counts": dict(sorted(by_blocker.items())),
            "blockers": blocker_list,
            "final_trade_status_counts": dict(sorted(final_status_counts.items())),
            "replay_status_counts": dict(sorted(replay_status_counts.items())),
            "label_status_counts": dict(sorted(label_status_counts.items())),
            "source_family_counts": dict(sorted(source_family_counts.items())),
            "feature_status_counts": dict(sorted(feature_status_counts.items())),
            "executable_price_source_counts": dict(sorted(executable_price_counts.items())),
            "station_bias_status_counts": dict(sorted(station_bias_counts.items())),
            "latency_status_counts": dict(sorted(latency_status_counts.items())),
            "high_resolution_status_counts": dict(sorted(high_res_status_counts.items())),
            "model_update_event_counts": dict(sorted(model_update_event_counts.items())),
            "actionable_model_update_events": actionable_model_update_events,
            "near_threshold_feature_count": near_threshold_count,
            "far_from_threshold_feature_count": far_from_threshold_count,
            "orderbook_coverage": evidence_report.get("orderbook_coverage", {}),
            "remaining_requirements": list(verdict.get("remaining_requirements", [])),
        }

    def _build_hypotheses(
        self,
        summary: Dict[str, Any],
        feature_rows: List[Dict[str, Any]],
        candidate_rows: List[Dict[str, Any]],
        replay_rows: List[Dict[str, Any]],
    ) -> List[WeatherEdgeHypothesisStatus]:
        blocker_counts = Counter(summary.get("blocker_counts", {}))
        source_counts = Counter(summary.get("source_family_counts", {}))
        station_bias_counts = Counter(summary.get("station_bias_status_counts", {}))
        latency_counts = Counter(summary.get("latency_status_counts", {}))
        final_status_counts = Counter(summary.get("final_trade_status_counts", {}))
        high_res_counts = Counter(summary.get("high_resolution_status_counts", {}))

        candidate_supply_blocked = int(blocker_counts.get("weather_edge_below_research_gap", 0))
        all_candidates_gate_blocked = (
            bool(candidate_rows)
            and int(final_status_counts.get("blocked_by_weather_gate", 0)) >= len(candidate_rows)
        )
        source_only_open_meteo = bool(source_counts) and set(source_counts) <= {"open_meteo", "missing"}
        missing_station_bias = int(station_bias_counts.get("missing_history", 0)) + int(station_bias_counts.get("missing", 0))
        first_scan_only = bool(latency_counts) and set(latency_counts) <= {"first_scan_no_prior_price", "missing"}

        hypotheses = [
            WeatherEdgeHypothesisStatus(
                code="forecast_gap_candidate_supply",
                title="Forecast Gap Candidate Supply",
                status="needs_candidate_supply" if candidate_supply_blocked or all_candidates_gate_blocked else "monitor",
                priority=1,
                evidence_count=len(candidate_rows),
                blockers=["weather_edge_below_research_gap"] if candidate_supply_blocked else [],
                why_it_can_create_edge=(
                    "The base forecast lane only becomes edge if it repeatedly finds executable gaps "
                    "large enough to clear costs and the research gap."
                ),
                next_actions=[
                    "Keep the gate unchanged; increase scan breadth and prioritize near-threshold markets.",
                    "Log near misses separately from tradeable candidates so we can tune supply without live risk.",
                    "Compare candidate gaps by metric, location, lead time, and source family after each cycle.",
                ],
                promotion_signal="At least 20 executable paper decisions survive the weather gate and later resolve.",
            ),
            WeatherEdgeHypothesisStatus(
                code="model_update_lag",
                title="Model Update Lag",
                status="needs_conus_or_parsed_high_res_runs"
                if not summary.get("actionable_model_update_events")
                else "active_research_signal",
                priority=2,
                evidence_count=int(summary.get("actionable_model_update_events", 0)),
                blockers=[] if summary.get("actionable_model_update_events") else ["no_actionable_model_update_events"],
                why_it_can_create_edge=(
                    "Fresh HRRR/NBM or official forecast updates may shift threshold probabilities before "
                    "thin weather books fully reprice."
                ),
                next_actions=[
                    "Prioritize US/CONUS markets where HRRR or NBM is applicable.",
                    "Record run_id, source age, forecast delta, and CLOB movement across multiple scans.",
                    "Promote only if stale-book windows survive executable orderbook checks.",
                ],
                promotion_signal="Run-change events with unchanged CLOB prices produce positive resolved replay ROI.",
            ),
            WeatherEdgeHypothesisStatus(
                code="station_bias",
                title="Station Bias and Resolution Mismatch",
                status="needs_station_history" if missing_station_bias else "ready_for_backtest",
                priority=3,
                evidence_count=len(feature_rows) - missing_station_bias,
                blockers=["station_bias_history_missing"] if missing_station_bias else [],
                why_it_can_create_edge=(
                    "Markets can anchor on city forecasts while settlement depends on airport stations, "
                    "official observations, or a different local-day window."
                ),
                next_actions=[
                    "Build station history for mapped METAR/ASOS stations before trusting threshold probabilities.",
                    "Split performance by station, city, metric, and lead time.",
                    "Reject markets whose resolution source cannot be mapped unambiguously.",
                ],
                promotion_signal="Bias-adjusted probabilities beat raw forecast and market baselines out of sample.",
            ),
            WeatherEdgeHypothesisStatus(
                code="latency_behavioral_repricing",
                title="Latency and Behavioral Repricing",
                status="needs_second_scan" if first_scan_only else "active_research_signal",
                priority=4,
                evidence_count=sum(count for status, count in latency_counts.items() if status != "first_scan_no_prior_price"),
                blockers=["only_first_scan_latency"] if first_scan_only else [],
                why_it_can_create_edge=(
                    "Price movement after forecast updates can reveal stale narratives, recency bias, or "
                    "market disagreement before resolution."
                ),
                next_actions=[
                    "Run repeated paper scans on the same universe to populate prior-price deltas.",
                    "Flag price movement against model direction and longshot/favorite mispricings.",
                    "Backtest behavior flags only after labels resolve.",
                ],
                promotion_signal="Behavior flags improve holdout ROI or calibration versus forecast-only candidates.",
            ),
            WeatherEdgeHypothesisStatus(
                code="execution_capacity",
                title="Execution Capacity",
                status="blocked_without_orderbook"
                if int(blocker_counts.get("no_executable_price_missing", 0))
                else "orderbook_capture_started",
                priority=5,
                evidence_count=int(summary.get("tradeable_replay_count", 0)),
                blockers=["no_executable_price_missing"] if int(blocker_counts.get("no_executable_price_missing", 0)) else [],
                why_it_can_create_edge=(
                    "A model edge only matters if the CLOB has enough executable depth after spread, fees, "
                    "and partial-fill risk."
                ),
                next_actions=[
                    "Require orderbook best ask for replay-tradeability.",
                    "Track max fillable stake at the candidate limit price.",
                    "Separate theoretical probability edge from executable net edge in every report.",
                ],
                promotion_signal="Executable replay records stay positive after realistic fill assumptions.",
            ),
        ]

        if source_only_open_meteo:
            hypotheses.append(
                WeatherEdgeHypothesisStatus(
                    code="source_diversification",
                    title="Source Diversification",
                    status="needs_independent_sources",
                    priority=6,
                    evidence_count=int(source_counts.get("open_meteo", 0)),
                    blockers=["single_weather_source_family"],
                    why_it_can_create_edge=(
                        "Independent model families create disagreement, update-lag, and source-specific bias "
                        "features that a single forecast source cannot expose."
                    ),
                    next_actions=[
                        "Add NWS grid/METAR packets for US markets where supported.",
                        "Keep HRRR/NBM unsupported markets explicit blockers rather than silent fallbacks.",
                    ],
                    promotion_signal="A multi-source feature set improves holdout metrics without increasing outages.",
                )
            )

        hypotheses.sort(key=lambda item: item.priority)
        return hypotheses

    def _current_phase(
        self,
        summary: Dict[str, Any],
        hypotheses: Iterable[WeatherEdgeHypothesisStatus],
    ) -> str:
        if bool(summary.get("paper_accepted")) and int(summary.get("tradeable_replay_count", 0)) > 0:
            return "paper_alpha_candidate_ready"
        if int(summary.get("candidate_decision_count", 0)) <= 0:
            return "needs_first_paper_evidence_cycle"
        blocker_counts = Counter(summary.get("blocker_counts", {}))
        if int(summary.get("resolved_record_count", 0)) <= 0:
            if int(blocker_counts.get("weather_edge_below_research_gap", 0)):
                return "candidate_supply_needed"
            return "awaiting_resolution_labels"
        if int(summary.get("tradeable_replay_count", 0)) <= 0:
            return "paper_replay_not_executable"
        if summary.get("edge_status") != "accepted":
            return "paper_alpha_under_review"
        return "paper_alpha_candidate_ready"

    def _next_actions(
        self,
        phase: str,
        summary: Dict[str, Any],
        hypotheses: List[WeatherEdgeHypothesisStatus],
    ) -> List[str]:
        actions: List[str] = []
        if phase == "needs_first_paper_evidence_cycle":
            actions.append("Run a weather paper cycle with orderbook capture enabled.")
        elif phase == "candidate_supply_needed":
            actions.extend(
                [
                    "Build the next alpha scout around near-threshold, same-day, high-liquidity weather markets.",
                    "Prioritize CONUS markets so HRRR/NBM run-lag features can become applicable.",
                    "Keep weather live disabled; do not lower gates just to create paper trades.",
                ]
            )
        elif phase == "awaiting_resolution_labels":
            actions.append("Keep collecting labels until resolved replay records are available.")
        elif phase == "paper_replay_not_executable":
            actions.append("Fix executable orderbook/depth coverage before treating replay records as trades.")
        elif phase == "paper_alpha_under_review":
            actions.append("Compare model metrics against market baseline and identify the failing promotion gate.")
        elif phase == "paper_alpha_candidate_ready":
            actions.append("Run paper soak and preflight checks; live remains manually blocked.")

        for hypothesis in hypotheses:
            if hypothesis.status.startswith("needs") or hypothesis.status.startswith("blocked"):
                for action in hypothesis.next_actions[:1]:
                    if action not in actions:
                        actions.append(action)
        if not actions:
            actions.append("Continue evidence collection and replay on the same schema.")
        return actions[:8]

    def _format_markdown(self, report: Dict[str, Any]) -> str:
        summary = report.get("summary", {})
        lines = [
            "# Polymarket Weather Edge Discovery",
            "",
            f"- Generated: `{report.get('generated_at')}`",
            f"- Current phase: `{report.get('current_phase')}`",
            f"- Edge built: `{report.get('edge_built')}`",
            f"- Live weather trading allowed: `{report.get('live_weather_trading_allowed')}`",
            f"- Evidence records: `{summary.get('record_count')}`",
            f"- Candidate decisions: `{summary.get('candidate_decision_count')}`",
            f"- Resolved records: `{summary.get('resolved_record_count')}`",
            f"- Executable replay decisions: `{summary.get('tradeable_replay_count')}`",
            f"- Edge status: `{summary.get('edge_status')}`",
            "",
            "## What This Means",
        ]
        if report.get("current_phase") == "candidate_supply_needed":
            lines.append(
                "- The safety and evidence loop is working, but the current scans are not producing "
                "enough high-quality tradable weather candidates."
            )
        elif report.get("edge_built"):
            lines.append("- A paper-alpha candidate exists, but live weather remains separately gated.")
        else:
            lines.append("- Edge is not proven yet; continue evidence collection and targeted research.")

        lines.extend(["", "## Next Actions"])
        for action in report.get("next_actions", []):
            lines.append(f"- {action}")

        lines.extend(["", "## Hypotheses"])
        for item in report.get("hypotheses", []):
            blockers = ", ".join(item.get("blockers", [])) or "none"
            lines.append(
                f"- `{item.get('code')}` `{item.get('status')}` priority `{item.get('priority')}` "
                f"evidence `{item.get('evidence_count')}` blockers `{blockers}`. "
                f"{item.get('why_it_can_create_edge')}"
            )

        lines.extend(["", "## Coverage"])
        for key in (
            "blocker_counts",
            "final_trade_status_counts",
            "replay_status_counts",
            "label_status_counts",
            "source_family_counts",
            "station_bias_status_counts",
            "latency_status_counts",
            "executable_price_source_counts",
        ):
            lines.append(f"- {key}: `{summary.get(key, {})}`")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}


def _counter_from_dict(value: Any) -> Counter:
    if not isinstance(value, dict):
        return Counter()
    return Counter({str(key): _int(count, 0) for key, count in value.items()})


def _int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _float_or_none(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _forecast_metric_value(row: Dict[str, Any]) -> Optional[float]:
    metric = str(row.get("metric") or "")
    metrics = row.get("raw_forecast_metrics") or {}
    if not isinstance(metrics, dict):
        metrics = {}
    keys_by_metric = {
        "temperature_high": ("high_temperature_f", "temperature_2m_max"),
        "temperature_low": ("low_temperature_f", "temperature_2m_min"),
        "precipitation": ("precipitation_in", "precipitation_sum"),
        "snowfall": ("snowfall_in", "snowfall_sum"),
        "wind": ("max_wind_mph", "wind_speed_10m_max"),
        "wind_gust": ("max_gust_mph", "wind_gusts_10m_max"),
    }
    for key in keys_by_metric.get(metric, ()):
        value = _float_or_none(metrics.get(key))
        if value is not None:
            return value
    for key in (
        "high_temperature_f",
        "low_temperature_f",
        "precipitation_in",
        "snowfall_in",
        "max_wind_mph",
        "max_gust_mph",
    ):
        value = _float_or_none(metrics.get(key))
        if value is not None:
            return value
    return None


def _near_threshold_band(row: Dict[str, Any]) -> float:
    metric = str(row.get("metric") or "")
    if metric in {"temperature_high", "temperature_low"}:
        return 3.0
    if metric in {"precipitation", "snowfall"}:
        return 0.15
    if metric in {"wind", "wind_gust"}:
        return 5.0
    return 3.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a weather edge discovery board from evidence")
    parser.add_argument("--data-dir", type=str, default=None, help="Override Polymarket trader data directory")
    parser.add_argument("--no-write", action="store_true", help="Build in memory without writing artifacts")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = PolymarketCLIConfig(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
    )
    if args.data_dir:
        config._data_dir_override = Path(args.data_dir)
    board = WeatherEdgeDiscoveryBoard(config)
    report = board.build_report(write=not args.no_write)
    cprint("Weather edge discovery report built", "green")
    cprint(f"  Phase: {report.get('current_phase')}", "white")
    cprint(f"  Edge built: {report.get('edge_built')}", "white")
    cprint(f"  Output: {board.root_dir}", "white")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
