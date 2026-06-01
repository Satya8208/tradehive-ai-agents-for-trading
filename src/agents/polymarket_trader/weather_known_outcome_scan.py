"""
Scan for observation-lag weather alpha candidates.

This runner is research-only. It finds markets routed to the known/near-known
observation lane, fetches METAR observations, attaches orderbook tape, and
writes blocked/candidate records for review.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from termcolor import cprint

from .config import ExecutionMode, PolymarketCLIConfig
from .market_scanner import CLIMarketScanner
from .models import CLIMarket
from .weather_candidate_lifecycle import WeatherCandidateLifecycleBuilder
from .weather_coverage_auditor import WeatherCoverageAuditor
from .weather_decision_packet import WeatherDecisionPacketBuilder, summarize_decision_packets
from .weather_evidence_store import WeatherEvidenceStore
from .weather_fillability_report import WeatherFillabilityReporter
from .weather_known_outcome_alpha import WeatherKnownOutcomeAlpha
from .weather_market_tape import WeatherMarketTapeCollector
from .weather_market_universe_router import WeatherMarketUniverseRouter, WeatherRoutedMarket
from .weather_observation_context import WeatherObservationContextCompiler
from .weather_observation_eligibility import WeatherObservationEligibilityAuditor
from .weather_observation_ingestor import WeatherObservationIngestor
from .weather_orderbook_fetch_planner import WeatherOrderbookFetchPlanner
from .weather_orderbook_simulator import WeatherOrderbookFillSimulator
from .weather_research_candidate_sampler import WeatherResearchCandidateSampler
from .weather_station_observation_state import WeatherStationObservationStateBuilder
from .weather_market_type_classifier import LANE_OBSERVATION_LAG


KNOWN_OUTCOME_SCAN_SCHEMA_VERSION = "weather_known_outcome_scan_v1"


class WeatherKnownOutcomeAlphaScanner:
    def __init__(
        self,
        config: Optional[PolymarketCLIConfig] = None,
        scanner: Optional[CLIMarketScanner] = None,
        router: Optional[WeatherMarketUniverseRouter] = None,
        tape_collector: Optional[WeatherMarketTapeCollector] = None,
        observation_ingestor: Optional[WeatherObservationIngestor] = None,
        observation_context_compiler: Optional[WeatherObservationContextCompiler] = None,
        observation_eligibility_auditor: Optional[WeatherObservationEligibilityAuditor] = None,
        state_builder: Optional[WeatherStationObservationStateBuilder] = None,
        fetch_planner: Optional[WeatherOrderbookFetchPlanner] = None,
        fillability_reporter: Optional[WeatherFillabilityReporter] = None,
        decision_packet_builder: Optional[WeatherDecisionPacketBuilder] = None,
        lifecycle_builder: Optional[WeatherCandidateLifecycleBuilder] = None,
        evidence_store: Optional[WeatherEvidenceStore] = None,
        alpha: Optional[WeatherKnownOutcomeAlpha] = None,
        output_dir: Optional[Path] = None,
    ):
        self.config = config or PolymarketCLIConfig(
            execution_mode=ExecutionMode.DRY_RUN,
            market_vertical="weather",
            search_symbols=["WEATHER"],
            min_liquidity_usd=500.0,
            min_volume_24h_usd=0.0,
            max_expiry_hours=16 * 24,
            min_expiry_minutes=0.0,
        )
        self.scanner = scanner or CLIMarketScanner(self.config)
        self.router = router or WeatherMarketUniverseRouter()
        self.tape_collector = tape_collector or WeatherMarketTapeCollector(self.config, getattr(self.scanner, "cli", None))
        self.observation_ingestor = observation_ingestor or WeatherObservationIngestor()
        self.observation_context_compiler = observation_context_compiler or WeatherObservationContextCompiler()
        self.observation_eligibility_auditor = observation_eligibility_auditor or WeatherObservationEligibilityAuditor()
        self.state_builder = state_builder or WeatherStationObservationStateBuilder()
        self.fetch_planner = fetch_planner or WeatherOrderbookFetchPlanner()
        self.fillability_reporter = fillability_reporter or WeatherFillabilityReporter()
        self.decision_packet_builder = decision_packet_builder or WeatherDecisionPacketBuilder()
        self.lifecycle_builder = lifecycle_builder or WeatherCandidateLifecycleBuilder()
        self.evidence_store = evidence_store or WeatherEvidenceStore(self.config)
        self.alpha = alpha or WeatherKnownOutcomeAlpha()
        self.output_dir = output_dir or (self.config.data_dir / "weather_known_outcome_alpha")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def latest_report_path(self) -> Path:
        return self.output_dir / "latest_weather_known_outcome_alpha_report.json"

    @property
    def latest_report_markdown_path(self) -> Path:
        return self.output_dir / "latest_weather_known_outcome_alpha_report.md"

    def run(
        self,
        *,
        force_refresh: bool = True,
        candidate_limit: int = 50,
        observation_hours: int = 18,
        now: Optional[datetime] = None,
        record_evidence: bool = False,
        write: bool = True,
    ) -> Dict[str, Any]:
        run_now = now or datetime.utcnow()
        generated_at = run_now.isoformat()
        run_id = self._run_id(generated_at)
        markets = self.scanner.scan_markets(force_refresh=force_refresh)
        routed = self.router.route_markets(markets, now=run_now)
        observation_context = self.observation_context_compiler.audit_routed(routed)
        observation_eligibility = self.observation_eligibility_auditor.audit_routed(routed)
        eligible_market_ids = set(observation_eligibility.get("eligible_market_ids", []))
        eligible_routed = [row for row in routed if row.market_id in eligible_market_ids]
        observation_pool_limit = max(int(candidate_limit or 0) * 5, 200)
        observation_pool = self._observation_lane_rows(eligible_routed, limit=observation_pool_limit, per_group_limit=6)
        market_by_id = {str(getattr(market, "condition_id", "") or ""): market for market in markets}
        station_ids = sorted(
            {
                str(row.classification.get("station_id") or "").upper()
                for row in observation_pool
                if str(row.classification.get("station_id") or "").strip()
            }
        )
        ingest = self.observation_ingestor.fetch_metar_observations(station_ids, hours=observation_hours)
        observations = ingest.observations
        station_states = {
            station_id: self.state_builder.build(station_id, observations, now=run_now).to_dict()
            for station_id in station_ids
        }
        fetch_plan = self.fetch_planner.plan_observation_lag(
            observation_pool,
            station_states=station_states,
            market_by_id=market_by_id,
            orderbook_limit=max(1, int(candidate_limit or 1)),
            per_group_limit=3,
            now=run_now,
        )
        row_by_market_id = {row.market_id: row for row in observation_pool}
        observation_rows = [
            row_by_market_id[market_id]
            for market_id in fetch_plan.selected_market_ids
            if market_id in row_by_market_id
        ]
        target_markets = [market_by_id[row.market_id] for row in observation_rows if row.market_id in market_by_id]
        tape_rows = self.tape_collector.snapshot_markets(target_markets, fetch_orderbook=True)
        tape_by_market = {row.market_id: row for row in tape_rows}
        candidates = []
        for row in observation_rows:
            market = market_by_id.get(row.market_id)
            if market is None:
                continue
            station_id = str(row.classification.get("station_id") or "").upper()
            station_state = station_states.get(station_id, {"station_id": station_id, "blockers": ["station_state_missing"]})
            candidate = self.alpha.evaluate(
                market,
                station_state,
                tape=tape_by_market.get(row.market_id),
                now=run_now,
            )
            candidates.append(candidate.to_dict())

        status_counts = Counter(str(row.get("status") or "missing") for row in candidates)
        blocker_counts = Counter(blocker for row in candidates for blocker in row.get("blockers", []))
        fill_coverage = WeatherOrderbookFillSimulator.summarize(
            row.get("fill_simulation", {}) for row in candidates if row.get("fill_simulation")
        )
        fillability_report = self.fillability_reporter.build(
            candidates,
            tape_by_market=tape_by_market,
            generated_at=generated_at,
        )
        decision_packet_recording = self._decision_packet_recording(
            candidates=candidates,
            target_markets=target_markets,
            tape_by_market=tape_by_market,
            market_by_id=market_by_id,
            run_id=run_id,
            record_evidence=record_evidence,
        )
        report = {
            "schema_version": KNOWN_OUTCOME_SCAN_SCHEMA_VERSION,
            "generated_at": generated_at,
            "run_id": run_id,
            "market_vertical": "weather",
            "markets_scanned": len(markets),
            "routed_markets": len(routed),
            "observation_eligible_count": int(observation_eligibility.get("eligible_count") or 0),
            "observation_pool_candidates": len(observation_pool),
            "observation_lane_candidates": len(observation_rows),
            "evaluated_candidates": len(candidates),
            "candidate_count": int(status_counts.get("candidate", 0)),
            "current_scan_candidate_count": int(status_counts.get("candidate", 0)),
            "status_counts": dict(sorted(status_counts.items())),
            "blocker_counts": dict(sorted(blocker_counts.items())),
            "observation_context": observation_context,
            "observation_eligibility": observation_eligibility,
            "observation_selection": self._selection_summary(observation_rows),
            "orderbook_fetch_plan": fetch_plan.to_dict(),
            "orderbook_fill_coverage": fill_coverage,
            "fillability_report": fillability_report,
            "decision_packet_summary": decision_packet_recording.get("decision_packet_summary", {}),
            "candidate_lifecycle_summary": decision_packet_recording.get("candidate_lifecycle_summary", {}),
            "paper_shadow_recording": decision_packet_recording,
            "evidence_waterfall": self._evidence_waterfall(
                observation_pool=observation_pool,
                observation_context=observation_context,
                observation_eligibility=observation_eligibility,
                station_states=station_states,
                fetch_plan=fetch_plan.to_dict(),
                candidates=candidates,
            ),
            "paper_evidence": self._paper_evidence(candidates),
            "observation_ingest": ingest.to_dict(),
            "station_states": station_states,
            "candidates": candidates,
            "scanner_telemetry": getattr(self.scanner, "last_scan_telemetry", {}),
            "artifacts": {
                "json": str(self.latest_report_path),
                "markdown": str(self.latest_report_markdown_path),
                "decision_packets": str(self.evidence_store.decision_packets_path),
                "candidate_lifecycle": str(self.evidence_store.candidate_lifecycle_path),
            },
        }
        report["coverage_audit"] = WeatherCoverageAuditor().audit_known_outcome(report)
        if write:
            self.latest_report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
            self.latest_report_markdown_path.write_text(self._format_markdown(report), encoding="utf-8")
        return report

    def _decision_packet_recording(
        self,
        *,
        candidates: List[Dict[str, Any]],
        target_markets: List[CLIMarket],
        tape_by_market: Dict[str, Any],
        market_by_id: Dict[str, CLIMarket],
        run_id: str,
        record_evidence: bool,
    ) -> Dict[str, Any]:
        decision_time = datetime.utcnow().isoformat()
        packets = self.decision_packet_builder.build_known_outcome_packets(
            candidates,
            tape_by_market=tape_by_market,
            run_id=run_id,
            decision_time=decision_time,
        )
        events = self.decision_packet_builder.to_candidate_events(
            packets,
            captured_at=decision_time,
        )
        lifecycle_records = self.lifecycle_builder.build_from_decision_packets(
            packets,
            discovered_at=decision_time,
        )
        decision_packet_summary = summarize_decision_packets(packets)
        lifecycle_summary = self.lifecycle_builder.summarize(lifecycle_records)
        recording = {
            "schema_version": "weather_paper_shadow_recording_v1",
            "recording_enabled": bool(record_evidence),
            "recorded_at": decision_time,
            "run_id": run_id,
            "current_scan_candidates": len(packets),
            "decision_packet_summary": decision_packet_summary,
            "candidate_lifecycle_summary": lifecycle_summary,
            "paths": {
                "market_tape": str(self.evidence_store.market_tape_path),
                "feature_snapshots": str(self.evidence_store.feature_snapshots_path),
                "candidate_events": str(self.evidence_store.candidate_decisions_path),
                "decision_packets": str(self.evidence_store.decision_packets_path),
                "candidate_lifecycle": str(self.evidence_store.candidate_lifecycle_path),
            },
            "write_counts": {
                "market_tape": 0,
                "feature_snapshots": 0,
                "candidate_events": 0,
                "decision_packets": 0,
                "candidate_lifecycle": 0,
            },
        }
        if not record_evidence or not packets:
            return recording

        packet_market_ids = {str(packet.get("market_id") or "") for packet in packets}
        packet_market_ids.discard("")
        candidate_by_market = {
            str(candidate.get("market_id") or ""): candidate
            for candidate in candidates
            if str(candidate.get("status") or "") == "candidate"
        }
        packet_by_market = {str(packet.get("market_id") or ""): packet for packet in packets}
        tape_rows = [
            tape_by_market[market_id]
            for market_id in packet_market_ids
            if market_id in tape_by_market
        ]
        evidence_markets = [
            market_by_id[market_id]
            for market_id in packet_market_ids
            if market_id in market_by_id
        ]
        if not evidence_markets:
            evidence_markets = [
                market
                for market in target_markets
                if str(getattr(market, "condition_id", "") or "") in packet_market_ids
            ]
        price_context = {}
        for market_id in packet_market_ids:
            packet = packet_by_market.get(market_id, {})
            candidate = candidate_by_market.get(market_id, {})
            price_context[market_id] = self.decision_packet_builder.feature_context_for_packet(
                packet,
                candidate,
                tape_by_market.get(market_id),
            )

        tape_count = self.evidence_store.append_market_tape(tape_rows)
        feature_count = self.evidence_store.append_feature_snapshots(
            evidence_markets,
            price_context,
            captured_at=decision_time,
        )
        packet_count = self.evidence_store.append_decision_packets(packets, captured_at=decision_time)
        event_count = self.evidence_store.append_candidate_events(events, captured_at=decision_time)
        lifecycle_count = self.evidence_store.append_candidate_lifecycle(lifecycle_records, captured_at=decision_time)
        recording["write_counts"] = {
            "market_tape": tape_count,
            "feature_snapshots": feature_count,
            "candidate_events": event_count,
            "decision_packets": packet_count,
            "candidate_lifecycle": lifecycle_count,
        }
        recording["decision_packet_summary"] = summarize_decision_packets(
            packets,
            packets_written=packet_count,
            candidate_events_written=event_count,
        )
        recording["candidate_lifecycle_summary"] = self.lifecycle_builder.summarize(
            lifecycle_records,
            records_written=lifecycle_count,
        )
        return recording

    @staticmethod
    def _observation_lane_rows(
        routed: Iterable[WeatherRoutedMarket],
        *,
        limit: int,
        per_group_limit: int = 3,
    ) -> List[WeatherRoutedMarket]:
        rows = [
            row
            for row in routed
            if LANE_OBSERVATION_LAG in set(str(item) for item in row.classification.get("alpha_lanes", []))
        ]
        rows.sort(key=WeatherKnownOutcomeAlphaScanner._observation_priority, reverse=True)
        selected: List[WeatherRoutedMarket] = []
        group_counts: Counter[str] = Counter()
        max_limit = max(1, int(limit))
        per_group_limit = max(1, int(per_group_limit))
        for row in rows:
            group = WeatherKnownOutcomeAlphaScanner._selection_group(row)
            if group_counts[group] >= per_group_limit:
                continue
            selected.append(row)
            group_counts[group] += 1
            if len(selected) >= max_limit:
                return selected
        for row in rows:
            if row in selected:
                continue
            selected.append(row)
            if len(selected) >= max_limit:
                break
        return selected

    @staticmethod
    def _observation_priority(row: WeatherRoutedMarket) -> tuple[float, float, float, float]:
        classification = row.classification
        microstructure = row.microstructure
        horizon_rank = {
            "already_in_window": 4.0,
            "0_6h": 3.0,
            "6_24h": 2.0,
            "24_72h": 1.0,
        }.get(str(classification.get("horizon_bucket") or ""), 0.0)
        operator = str(classification.get("operator") or "")
        operator_rank = 2.0 if operator in {"above", "below"} else 1.0 if operator == "between" else 0.0
        liquidity = float(microstructure.get("liquidity") or 0.0)
        depth_bonus = 1.0 if bool(microstructure.get("depth_ok")) else 0.0
        return (
            horizon_rank,
            operator_rank + depth_bonus,
            min(6.0, liquidity ** 0.25) if liquidity > 0 else 0.0,
            float(row.research_score or 0.0),
        )

    @staticmethod
    def _selection_group(row: WeatherRoutedMarket) -> str:
        classification = row.classification
        event = str(classification.get("event_slug") or "").strip()
        station = str(classification.get("station_id") or "").strip().upper()
        metric = str(classification.get("metric") or "").strip()
        target_date = str(classification.get("target_date") or "").strip()
        location = str(classification.get("location_name") or "").strip().lower()
        return event or "|".join([station, location, metric, target_date])

    @staticmethod
    def _run_id(generated_at: str) -> str:
        cleaned = "".join(ch for ch in str(generated_at or "") if ch.isalnum())
        return f"weather_known_outcome_{cleaned or 'run'}"

    @staticmethod
    def _selection_summary(rows: Iterable[WeatherRoutedMarket]) -> Dict[str, Any]:
        selected = list(rows)
        by_group = Counter(WeatherKnownOutcomeAlphaScanner._selection_group(row) for row in selected)
        by_horizon = Counter(str(row.classification.get("horizon_bucket") or "unknown") for row in selected)
        by_operator = Counter(str(row.classification.get("operator") or "unknown") for row in selected)
        return {
            "selected_count": len(selected),
            "unique_groups": len(by_group),
            "max_per_group": max(by_group.values()) if by_group else 0,
            "horizon_counts": dict(sorted(by_horizon.items())),
            "operator_counts": dict(sorted(by_operator.items())),
            "top_groups": dict(by_group.most_common(10)),
        }

    @staticmethod
    def _evidence_waterfall(
        *,
        observation_pool: Iterable[WeatherRoutedMarket],
        observation_context: Dict[str, Any],
        observation_eligibility: Dict[str, Any],
        station_states: Dict[str, Dict[str, Any]],
        fetch_plan: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        pool_rows = list(observation_pool)
        priority_counts = dict(fetch_plan.get("selected_priority_counts") or {})
        known_job_count = sum(
            int(count or 0)
            for priority, count in priority_counts.items()
            if str(priority or "").startswith("P0")
        )
        return {
            "routed_observation_lag": len(pool_rows),
            "observation_context_destinations": dict((observation_context or {}).get("destination_counts") or {}),
            "observation_eligible_markets": int((observation_eligibility or {}).get("eligible_count") or 0),
            "stations_requested": len(station_states),
            "stations_with_observations": sum(
                1 for state in station_states.values() if int(state.get("observation_count") or 0) > 0
            ),
            "orderbook_fetch_jobs_selected": int(fetch_plan.get("selected_job_count") or 0),
            "orderbook_markets_selected": int(fetch_plan.get("selected_market_count") or 0),
            "known_or_near_known_jobs_selected": known_job_count,
            "evaluated_candidates": len(candidates),
            "accepted_paper_candidates": sum(1 for row in candidates if row.get("status") == "candidate"),
            "blocked_or_rejected_candidates": sum(1 for row in candidates if row.get("status") != "candidate"),
        }

    @staticmethod
    def _paper_evidence(candidates: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        rows = []
        for candidate in candidates:
            rows.append(
                {
                    "market_id": candidate.get("market_id"),
                    "result": candidate.get("status"),
                    "side": candidate.get("side"),
                    "p_yes_source": candidate.get("p_yes_source"),
                    "probability_role": candidate.get("probability_role"),
                    "selected_win_probability": candidate.get("selected_win_probability"),
                    "executable_price": candidate.get("executable_price"),
                    "executable_price_source": candidate.get("executable_price_source"),
                    "edge_after_cost": candidate.get("edge_after_cost"),
                    "fill_status": candidate.get("fill_status"),
                    "max_fillable_usd": candidate.get("max_fillable_usd"),
                    "proof": candidate.get("proof", []),
                    "disproof": candidate.get("disproof", []),
                    "blockers": candidate.get("blockers", []),
                }
            )
        accepted = [row for row in rows if row.get("result") == "candidate"]
        rejected = [row for row in rows if row.get("result") != "candidate"]
        return {
            "schema_version": "weather_known_outcome_paper_evidence_v1",
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "accepted": accepted[:25],
            "rejected": rejected[:25],
        }

    def _format_markdown(self, report: Dict[str, Any]) -> str:
        lines = [
            "# Polymarket Weather Known-Outcome Alpha",
            "",
            f"- Generated: `{report.get('generated_at')}`",
            f"- Markets scanned: `{report.get('markets_scanned')}`",
            f"- Observation eligible: `{report.get('observation_eligible_count')}`",
            f"- Observation pool: `{report.get('observation_pool_candidates')}`",
            f"- Observation-lane candidates: `{report.get('observation_lane_candidates')}`",
            f"- Evaluated candidates: `{report.get('evaluated_candidates')}`",
            f"- Candidate count: `{report.get('candidate_count')}`",
            f"- Observation ingest: `{report.get('observation_ingest', {}).get('status')}`",
            "",
            "## Status Counts",
        ]
        for status, count in report.get("status_counts", {}).items():
            lines.append(f"- `{status}`: `{count}`")
        lines.extend(["", "## Blockers"])
        for blocker, count in report.get("blocker_counts", {}).items():
            lines.append(f"- `{blocker}`: `{count}`")
        eligibility = report.get("observation_eligibility", {})
        if eligibility:
            lines.extend(["", "## Observation Eligibility"])
            lines.append(f"- Eligible: `{eligibility.get('eligible_count')}`")
            lines.append(f"- Ineligible: `{eligibility.get('ineligible_count')}`")
            for row in eligibility.get("top_blockers", [])[:8]:
                lines.append(f"- `{row.get('blocker')}`: `{row.get('count')}`")
            proof = eligibility.get("zero_eligible_proof") or {}
            if proof:
                lines.append(f"- Zero proof: `{proof}`")
        context = report.get("observation_context", {})
        if context:
            lines.extend(["", "## Observation Context Split"])
            lines.append(f"- Destinations: `{context.get('destination_counts', {})}`")
            lines.append(f"- Status: `{context.get('status_counts', {})}`")
        lines.extend(["", "## Execution Coverage"])
        lines.append(f"- Selection: `{report.get('observation_selection', {})}`")
        lines.append(f"- Orderbook plan: `{report.get('orderbook_fetch_plan', {})}`")
        lines.append(f"- Fill coverage: `{report.get('orderbook_fill_coverage', {})}`")
        fillability = report.get("fillability_report", {})
        if fillability:
            lines.append(
                "- Fillability: "
                f"`full_positive={fillability.get('full_fill_positive_edge_count')}` "
                f"`capacity_usd={fillability.get('positive_edge_capacity_usd')}` "
                f"`statuses={fillability.get('by_fill_status', {})}`"
            )
        packet_summary = report.get("decision_packet_summary", {})
        lifecycle_summary = report.get("candidate_lifecycle_summary", {})
        if packet_summary:
            lines.append(
                "- Decision packets: "
                f"`packets={packet_summary.get('decision_packet_count')}` "
                f"`written={packet_summary.get('decision_packets_written')}` "
                f"`events={packet_summary.get('candidate_events_written')}`"
            )
        if lifecycle_summary:
            lines.append(
                "- Candidate lifecycle: "
                f"`records={lifecycle_summary.get('lifecycle_record_count')}` "
                f"`written={lifecycle_summary.get('lifecycle_records_written')}` "
                f"`statuses={lifecycle_summary.get('by_status', {})}`"
            )
        lines.append(f"- Waterfall: `{report.get('evidence_waterfall', {})}`")
        audit = report.get("coverage_audit", {})
        if audit:
            lines.extend(["", "## Coverage Audit"])
            lines.append(f"- Verdict: `{audit.get('verdict')}`")
            lines.append(f"- Bottleneck: `{(audit.get('bottleneck_stage') or {}).get('stage')}`")
            for stage in audit.get("funnel", []):
                lines.append(
                    f"- `{stage.get('stage')}`: `{stage.get('input_count')}` -> "
                    f"`{stage.get('output_count')}` pass `{stage.get('pass_rate')}`"
                )
            for action in audit.get("next_actions", [])[:4]:
                lines.append(f"- Next: {action}")
        lines.extend(["", "## Top Candidates"])
        for row in report.get("candidates", [])[:20]:
            lines.append(
                f"- `{row.get('status')}` `{row.get('side')}` edge `{row.get('edge_after_cost')}` "
                f"p_yes `{row.get('p_yes')}` `{row.get('p_yes_source')}` fill `{row.get('fill_status')}` "
                f"market `{row.get('market_id')}` blockers `{row.get('blockers')}`"
            )
            for proof in row.get("proof", [])[:2]:
                lines.append(f"  - proof: {proof}")
            for disproof in row.get("disproof", [])[:2]:
                lines.append(f"  - disproof: {disproof}")
        lines.append("")
        return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan known/near-known weather observation alpha")
    parser.add_argument("--candidate-limit", type=int, default=50)
    parser.add_argument("--observation-hours", type=int, default=18)
    parser.add_argument("--min-liquidity", type=float, default=500.0)
    parser.add_argument("--min-volume", type=float, default=0.0)
    parser.add_argument("--max-expiry-hours", type=float, default=16 * 24)
    parser.add_argument("--max-search-queries", type=int, default=12)
    parser.add_argument("--record-evidence", action="store_true")
    parser.add_argument("--data-dir", type=str, default=None)
    parser.add_argument("--output-dir", type=str, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = PolymarketCLIConfig(
        execution_mode=ExecutionMode.DRY_RUN,
        market_vertical="weather",
        search_symbols=["WEATHER"],
        min_liquidity_usd=args.min_liquidity,
        min_volume_24h_usd=args.min_volume,
        max_expiry_hours=args.max_expiry_hours,
        min_expiry_minutes=0.0,
        max_weather_search_queries=args.max_search_queries,
        weather_market_tape_fetch_orderbook=True,
    )
    if args.data_dir:
        config._data_dir_override = Path(args.data_dir)
    runner = WeatherKnownOutcomeAlphaScanner(
        config=config,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    report = runner.run(
        candidate_limit=args.candidate_limit,
        observation_hours=args.observation_hours,
        record_evidence=args.record_evidence,
    )
    cprint("Weather known-outcome alpha report written", "green")
    cprint(f"  Evaluated: {report.get('evaluated_candidates')}", "white")
    cprint(f"  Candidates: {report.get('candidate_count')}", "white")
    cprint(f"  Output: {runner.output_dir}", "white")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
