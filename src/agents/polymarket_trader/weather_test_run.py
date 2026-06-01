"""One-command safe test run for the Polymarket weather system."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from termcolor import cprint

from .config import ExecutionMode, PolymarketCLIConfig
from .weather_known_outcome_scan import WeatherKnownOutcomeAlphaScanner
from .weather_live_eligibility import WeatherLiveEligibilityGate
from .weather_replay import WeatherReplayEngine
from .weather_resolution_labels import WeatherResolutionLabelCollector


WEATHER_TEST_RUN_SCHEMA_VERSION = "weather_system_test_run_v1"


@dataclass(frozen=True)
class WeatherTestRunPaths:
    root_dir: Path

    @property
    def latest_report_path(self) -> Path:
        return self.root_dir / "latest_weather_test_run_report.json"

    @property
    def latest_report_markdown_path(self) -> Path:
        return self.root_dir / "latest_weather_test_run_report.md"


class WeatherSystemTestRunner:
    """Run the weather evidence loop without enabling live trading."""

    def __init__(
        self,
        config: Optional[PolymarketCLIConfig] = None,
        *,
        output_dir: Optional[Path | str] = None,
        known_outcome_runner: Optional[Any] = None,
        label_collector: Optional[Any] = None,
        replay_engine: Optional[Any] = None,
        live_gate: Optional[Any] = None,
    ):
        self.config = config or PolymarketCLIConfig(
            execution_mode=ExecutionMode.DRY_RUN,
            market_vertical="weather",
            search_symbols=["WEATHER"],
            min_liquidity_usd=500.0,
            min_volume_24h_usd=0.0,
            max_expiry_hours=16 * 24,
            min_expiry_minutes=0.0,
            weather_market_tape_fetch_orderbook=True,
        )
        self.paths = WeatherTestRunPaths(Path(output_dir) if output_dir else self.config.data_dir / "weather_test_runs")
        self.paths.root_dir.mkdir(parents=True, exist_ok=True)
        self.known_outcome_runner = known_outcome_runner
        self.label_collector = label_collector
        self.replay_engine = replay_engine
        self.live_gate = live_gate

    def run(
        self,
        *,
        known_outcome_limit: int = 50,
        observation_hours: int = 18,
        collect_labels: bool = False,
        label_limit: int = 500,
        replay: bool = True,
        min_resolved: int = 0,
        min_trades: int = 0,
    ) -> Dict[str, Any]:
        phases: Dict[str, Dict[str, Any]] = {}
        known_report: Dict[str, Any] = {}
        label_summary: Dict[str, Any] = {}
        replay_report: Dict[str, Any] = {}

        known_report = self._phase(
            phases,
            "known_outcome_scan",
            lambda: self._run_known_outcome_scan(
                known_outcome_limit=known_outcome_limit,
                observation_hours=observation_hours,
            ),
            summarize=lambda report: {
                "markets_scanned": report.get("markets_scanned"),
                "observation_eligible_count": report.get("observation_eligible_count"),
                "evaluated_candidates": report.get("evaluated_candidates"),
                "candidate_count": report.get("candidate_count"),
                "current_scan_candidate_count": report.get("current_scan_candidate_count", report.get("candidate_count")),
                "decision_packets_written": (report.get("decision_packet_summary") or {}).get("decision_packets_written"),
                "candidate_events_written": (report.get("decision_packet_summary") or {}).get("candidate_events_written"),
                "lifecycle_records_written": (report.get("candidate_lifecycle_summary") or {}).get("lifecycle_records_written"),
                "lifecycle_statuses": (report.get("candidate_lifecycle_summary") or {}).get("by_status", {}),
                "coverage_verdict": (report.get("coverage_audit") or {}).get("verdict"),
            },
        )

        if collect_labels:
            label_summary = self._phase(
                phases,
                "resolution_labels",
                lambda: (self.label_collector or WeatherResolutionLabelCollector(self.config)).collect(limit=label_limit, rerun_replay=False),
                summarize=lambda summary: {
                    "markets_considered": summary.get("markets_considered"),
                    "labels_written": summary.get("labels_written"),
                    "by_label_status": summary.get("by_label_status"),
                },
            )
        else:
            phases["resolution_labels"] = {
                "status": "skipped",
                "reason": "collect_labels_false",
            }

        if replay:
            replay_report = self._phase(
                phases,
                "replay_evidence",
                lambda: (self.replay_engine or WeatherReplayEngine(self.config)).write_replay_and_report(
                    min_resolved_markets=min_resolved,
                    min_trade_decisions=min_trades,
                ),
                summarize=lambda report: {
                    "record_count": report.get("record_count"),
                    "resolved_record_count": report.get("resolved_record_count"),
                    "tradeable_replay_count": report.get("tradeable_replay_count"),
                    "edge_status": report.get("edge_status"),
                    "paper_accepted": (report.get("deployment_verdict") or {}).get("accepted_for_paper_weather_trading"),
                },
            )
        else:
            phases["replay_evidence"] = {
                "status": "skipped",
                "reason": "replay_false",
            }

        live_gate = self.live_gate or WeatherLiveEligibilityGate(self.config)
        live_result = live_gate.evaluate(evidence_report=replay_report or None)
        live_report = live_result.to_dict() if hasattr(live_result, "to_dict") else dict(live_result)
        phases["live_eligibility"] = {
            "status": "succeeded",
            "summary": {
                "live_status": live_report.get("status"),
                "eligible": live_report.get("eligible"),
                "blockers": live_report.get("blockers", [])[:10],
            },
        }

        report = {
            "schema_version": WEATHER_TEST_RUN_SCHEMA_VERSION,
            "generated_at": datetime.utcnow().isoformat(),
            "market_vertical": "weather",
            "execution_mode": "research_only",
            "live_order_calls_allowed": False,
            "status": self._status(phases, live_report),
            "phases": phases,
            "known_outcome_summary": phases.get("known_outcome_scan", {}).get("summary", {}),
            "label_summary": phases.get("resolution_labels", {}).get("summary", label_summary),
            "replay_summary": phases.get("replay_evidence", {}).get("summary", {}),
            "live_eligibility": live_report,
            "artifacts": {
                "test_run_json": str(self.paths.latest_report_path),
                "test_run_markdown": str(self.paths.latest_report_markdown_path),
                "known_outcome": str(self.config.data_dir / "weather_known_outcome_alpha" / "latest_weather_known_outcome_alpha_report.json"),
                "replay_evidence": str(self.config.data_dir / "weather_evidence" / "latest_weather_evidence_report.json"),
                "decision_packets": str(self.config.data_dir / "weather_evidence" / "decision_packets.jsonl"),
                "candidate_lifecycle": str(self.config.data_dir / "weather_evidence" / "candidate_lifecycle.jsonl"),
            },
        }
        self.paths.latest_report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        self.paths.latest_report_markdown_path.write_text(self.format_markdown(report), encoding="utf-8")
        return report

    def _run_known_outcome_scan(
        self,
        *,
        known_outcome_limit: int,
        observation_hours: int,
    ) -> Dict[str, Any]:
        if self.known_outcome_runner is not None:
            return self.known_outcome_runner.run(
                candidate_limit=known_outcome_limit,
                observation_hours=observation_hours,
            )
        return WeatherKnownOutcomeAlphaScanner(self.config).run(
            candidate_limit=known_outcome_limit,
            observation_hours=observation_hours,
            record_evidence=True,
        )

    @staticmethod
    def _phase(
        phases: Dict[str, Dict[str, Any]],
        name: str,
        fn: Any,
        *,
        summarize: Any,
    ) -> Dict[str, Any]:
        started_at = datetime.utcnow().isoformat()
        try:
            result = fn()
        except Exception as exc:
            phases[name] = {
                "status": "failed",
                "started_at": started_at,
                "finished_at": datetime.utcnow().isoformat(),
                "error": f"{type(exc).__name__}: {exc}",
            }
            return {}
        phases[name] = {
            "status": "succeeded",
            "started_at": started_at,
            "finished_at": datetime.utcnow().isoformat(),
            "summary": summarize(result),
        }
        return result if isinstance(result, dict) else {}

    @staticmethod
    def _status(phases: Dict[str, Dict[str, Any]], live_report: Dict[str, Any]) -> str:
        if any(row.get("status") == "failed" for row in phases.values()):
            return "failed"
        if live_report.get("eligible") is True:
            return "failed_live_gate_unexpectedly_open"
        return "passed_research_test_live_blocked"

    @staticmethod
    def format_markdown(report: Dict[str, Any]) -> str:
        lines = [
            "# Polymarket Weather System Test Run",
            "",
            f"- Generated: `{report.get('generated_at')}`",
            f"- Status: `{report.get('status')}`",
            f"- Live order calls allowed: `{report.get('live_order_calls_allowed')}`",
            "",
            "## Phases",
        ]
        for name, phase in (report.get("phases") or {}).items():
            lines.append(f"- `{name}`: `{phase.get('status')}` `{phase.get('summary', phase.get('reason', phase.get('error', '')) )}`")
        live = report.get("live_eligibility") or {}
        lines.extend(["", "## Live Gate"])
        lines.append(f"- Status: `{live.get('status')}`")
        lines.append(f"- Eligible: `{live.get('eligible')}`")
        for blocker in (live.get("blockers") or [])[:10]:
            lines.append(f"- Blocker: `{blocker}`")
        lines.append("")
        return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a safe Polymarket weather system test")
    parser.add_argument("--known-outcome-limit", type=int, default=50)
    parser.add_argument("--observation-hours", type=int, default=18)
    parser.add_argument("--collect-labels", action="store_true")
    parser.add_argument("--label-limit", type=int, default=500)
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--min-resolved", type=int, default=0)
    parser.add_argument("--min-trades", type=int, default=0)
    parser.add_argument("--data-dir", type=str, default="")
    parser.add_argument("--output-dir", type=str, default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = PolymarketCLIConfig(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
        min_liquidity_usd=500.0,
        min_volume_24h_usd=0.0,
        max_expiry_hours=16 * 24,
        min_expiry_minutes=0.0,
        weather_market_tape_fetch_orderbook=True,
    )
    if args.data_dir:
        config._data_dir_override = Path(args.data_dir)
    report = WeatherSystemTestRunner(
        config,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    ).run(
        known_outcome_limit=args.known_outcome_limit,
        observation_hours=args.observation_hours,
        collect_labels=args.collect_labels,
        label_limit=args.label_limit,
        replay=args.replay,
        min_resolved=args.min_resolved,
        min_trades=args.min_trades,
    )
    cprint("Weather system test run complete", "green")
    cprint(f"  Status: {report.get('status')}", "white")
    cprint(f"  Known outcome: {report.get('known_outcome_summary')}", "white")
    cprint(f"  Replay: {report.get('replay_summary')}", "white")
    cprint(f"  Live: {report.get('live_eligibility', {}).get('status')}", "white")
    cprint(f"  Output: {report.get('artifacts', {}).get('test_run_json')}", "white")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
