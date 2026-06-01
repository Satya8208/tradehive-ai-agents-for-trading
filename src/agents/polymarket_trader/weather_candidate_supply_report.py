"""
Weather candidate supply report.

This is the first edge-building report: it routes the full weather universe into
alpha lanes and writes a scan-universe ledger before any trade gate is touched.
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
from .weather_market_tape import WeatherMarketTapeCollector, WeatherMarketTapeSnapshot
from .weather_market_universe_router import WeatherMarketUniverseRouter, WeatherRoutedMarket
from .weather_orderbook_fetch_planner import WeatherOrderbookFetchPlan, WeatherOrderbookFetchPlanner
from .weather_orderbook_simulator import WeatherOrderbookFillSimulator
from .weather_research_candidate_sampler import WeatherResearchCandidateSampler


WEATHER_CANDIDATE_SUPPLY_SCHEMA_VERSION = "weather_candidate_supply_report_v1"


class WeatherCandidateSupplyReporter:
    def __init__(
        self,
        config: Optional[PolymarketCLIConfig] = None,
        scanner: Optional[CLIMarketScanner] = None,
        tape_collector: Optional[WeatherMarketTapeCollector] = None,
        router: Optional[WeatherMarketUniverseRouter] = None,
        sampler: Optional[WeatherResearchCandidateSampler] = None,
        fetch_planner: Optional[WeatherOrderbookFetchPlanner] = None,
        fill_simulator: Optional[WeatherOrderbookFillSimulator] = None,
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
        self.tape_collector = tape_collector or WeatherMarketTapeCollector(self.config, getattr(self.scanner, "cli", None))
        self.router = router or WeatherMarketUniverseRouter()
        self.sampler = sampler or WeatherResearchCandidateSampler()
        self.fetch_planner = fetch_planner or WeatherOrderbookFetchPlanner()
        self.fill_simulator = fill_simulator or WeatherOrderbookFillSimulator(
            default_request_size_usd=float(getattr(self.config, "min_position_usd", 5.0) or 5.0),
            allow_best_ask_without_depth=False,
        )
        self.output_dir = output_dir or (self.config.data_dir / "weather_candidate_supply")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def latest_report_path(self) -> Path:
        return self.output_dir / "latest_weather_candidate_supply_report.json"

    @property
    def latest_report_markdown_path(self) -> Path:
        return self.output_dir / "latest_weather_candidate_supply_report.md"

    @property
    def scan_universe_ledger_path(self) -> Path:
        return self.output_dir / "weather_scan_universe.jsonl"

    def build_report(
        self,
        *,
        force_refresh: bool = True,
        fetch_orderbook: bool = False,
        orderbook_limit: int = 0,
        write: bool = True,
    ) -> Dict[str, Any]:
        cycle_id = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        markets = self.scanner.scan_markets(force_refresh=force_refresh)
        initial_routed = self.router.route_markets(markets)
        planning_limit = len(markets) if fetch_orderbook and int(orderbook_limit or 0) <= 0 else int(orderbook_limit or 50)
        fetch_plan = self.fetch_planner.plan_routed_lane_jobs(
            initial_routed,
            orderbook_limit=max(1, planning_limit),
            per_group_limit=3,
        )
        tape_by_market = self._market_tape(
            markets,
            fetch_orderbook=fetch_orderbook,
            orderbook_limit=orderbook_limit,
            fetch_plan=fetch_plan,
        )
        routed = self.router.route_markets(markets, tape_by_market=tape_by_market) if tape_by_market else initial_routed
        sample = self.sampler.sample(routed)
        summary = self.router.summarize(routed)
        lane_summary = self.router.summarize_by_lane(routed)
        fill_coverage = self._sample_fill_coverage(sample.selected_market_ids, tape_by_market)
        report = {
            "schema_version": WEATHER_CANDIDATE_SUPPLY_SCHEMA_VERSION,
            "generated_at": datetime.utcnow().isoformat(),
            "cycle_id": cycle_id,
            "market_vertical": "weather",
            "markets_scanned": len(markets),
            "routed_markets": len(routed),
            "research_candidate_count": sample.total_selected,
            "scanner_telemetry": getattr(self.scanner, "last_scan_telemetry", {}),
            "summary": summary,
            "lane_summary": lane_summary,
            "orderbook_fetch_plan": fetch_plan.to_dict(),
            "sample_fill_coverage": fill_coverage,
            "sample": sample.to_dict(),
            "top_routed_markets": [row.to_dict() for row in routed[:50]],
            "candidate_supply_state": self._candidate_supply_state(len(markets), sample.total_selected, summary, fill_coverage),
            "targets": {
                "markets_analyzed_per_full_scan": 200,
                "research_candidates_with_route_packets": 50,
                "orderbook_coverage_for_analyzed_candidates": 0.90,
                "full_fill_coverage_for_analyzed_candidates": 0.90,
            },
            "artifacts": {
                "json": str(self.latest_report_path),
                "markdown": str(self.latest_report_markdown_path),
                "scan_universe_ledger": str(self.scan_universe_ledger_path),
            },
        }
        if write:
            self._write_scan_universe_ledger(cycle_id, routed)
            self.latest_report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
            self.latest_report_markdown_path.write_text(self._format_markdown(report), encoding="utf-8")
        return report

    def _sample_fill_coverage(
        self,
        selected_market_ids: Iterable[str],
        tape_by_market: Dict[str, WeatherMarketTapeSnapshot],
    ) -> Dict[str, Any]:
        simulations = []
        market_count = 0
        markets_with_both_sides = 0
        for market_id in selected_market_ids:
            tape = tape_by_market.get(str(market_id))
            if tape is None:
                continue
            market_count += 1
            yes = self.fill_simulator.simulate(tape, "YES")
            no = self.fill_simulator.simulate(tape, "NO")
            simulations.extend([yes, no])
            if yes.full_fill and no.full_fill:
                markets_with_both_sides += 1
        summary = WeatherOrderbookFillSimulator.summarize(simulations)
        summary.update(
            {
                "sample_markets_with_tape": market_count,
                "sample_markets_with_full_yes_no_fill": markets_with_both_sides,
                "market_full_fill_coverage_ratio": round(markets_with_both_sides / market_count, 4) if market_count else 0.0,
            }
        )
        return summary

    def _market_tape(
        self,
        markets: List[CLIMarket],
        *,
        fetch_orderbook: bool,
        orderbook_limit: int,
        fetch_plan: Optional[WeatherOrderbookFetchPlan] = None,
    ) -> Dict[str, WeatherMarketTapeSnapshot]:
        if not fetch_orderbook:
            return {}
        orderbook_limit = max(0, int(orderbook_limit or 0))
        by_market_id = {str(getattr(market, "condition_id", "") or ""): market for market in markets}
        target_ids = list(fetch_plan.selected_market_ids) if fetch_plan is not None else []
        if not target_ids:
            if orderbook_limit <= 0:
                orderbook_limit = len(markets)
            targets = sorted(
                markets,
                key=lambda market: (
                    float(getattr(market, "liquidity", 0.0) or 0.0),
                    -float(getattr(market, "time_remaining_hours", 999.0) or 999.0),
                ),
                reverse=True,
            )[:orderbook_limit]
        else:
            targets = [by_market_id[market_id] for market_id in target_ids if market_id in by_market_id]
        snapshots = self.tape_collector.snapshot_markets(targets, fetch_orderbook=True)
        return {snapshot.market_id: snapshot for snapshot in snapshots}

    def _write_scan_universe_ledger(
        self,
        cycle_id: str,
        routed: Iterable[WeatherRoutedMarket],
    ) -> None:
        self.scan_universe_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.scan_universe_ledger_path.open("a", encoding="utf-8") as handle:
            for row in routed:
                classification = row.classification
                microstructure = row.microstructure
                payload = {
                    "schema_version": "weather_scan_universe_v1",
                    "cycle_id": cycle_id,
                    "seen_at": row.generated_at,
                    "market_id": row.market_id,
                    "question": row.question,
                    "included_or_rejected": "included_for_research_routing",
                    "reject_reason": "",
                    "contract_type": classification.get("contract_type", ""),
                    "region": classification.get("region", ""),
                    "horizon_bucket": classification.get("horizon_bucket", ""),
                    "alpha_lanes": classification.get("alpha_lanes", []),
                    "station_mapping_status": classification.get("station_mapping_status", ""),
                    "source_mapping_status": ",".join(classification.get("source_applicability", [])),
                    "orderbook_enabled": bool(microstructure.get("orderbook_available")),
                    "market_status": "active",
                    "liquidity_status": self._liquidity_status(float(microstructure.get("liquidity") or 0.0)),
                    "candidate_generated": bool(classification.get("alpha_lanes")),
                    "decision_generated": False,
                    "research_score": row.research_score,
                }
                handle.write(json.dumps(payload, sort_keys=True) + "\n")

    @staticmethod
    def _liquidity_status(liquidity: float) -> str:
        if liquidity >= 5000:
            return "high"
        if liquidity >= 500:
            return "medium"
        if liquidity > 0:
            return "low"
        return "missing"

    @staticmethod
    def _candidate_supply_state(
        market_count: int,
        candidate_count: int,
        summary: Dict[str, Any],
        fill_coverage: Optional[Dict[str, Any]] = None,
    ) -> str:
        coverage = float(summary.get("orderbook_coverage", {}).get("coverage_ratio", 0.0) or 0.0)
        fill_ratio = float((fill_coverage or {}).get("market_full_fill_coverage_ratio", 0.0) or 0.0)
        if market_count < 200:
            return "universe_supply_thin"
        if candidate_count < 50:
            return "candidate_supply_needed"
        if coverage <= 0.0:
            return "orderbook_coverage_unmeasured"
        if coverage < 0.90:
            return "orderbook_coverage_needed"
        if fill_ratio < 0.90:
            return "orderbook_depth_coverage_needed"
        return "candidate_supply_ready_for_alpha_lanes"

    def _format_markdown(self, report: Dict[str, Any]) -> str:
        summary = report.get("summary", {})
        orderbook = summary.get("orderbook_coverage", {})
        lines = [
            "# Polymarket Weather Candidate Supply",
            "",
            f"- Generated: `{report.get('generated_at')}`",
            f"- Cycle: `{report.get('cycle_id')}`",
            f"- Markets scanned: `{report.get('markets_scanned')}`",
            f"- Routed markets: `{report.get('routed_markets')}`",
            f"- Research candidates: `{report.get('research_candidate_count')}`",
            f"- Candidate supply state: `{report.get('candidate_supply_state')}`",
            f"- Orderbook coverage: `{orderbook.get('coverage_ratio', 0.0)}`",
            "",
            "## Lane Counts",
        ]
        for lane, count in summary.get("alpha_lane_counts", {}).items():
            lines.append(f"- `{lane}`: `{count}`")

        lines.extend(["", "## Sample Buckets"])
        for bucket in report.get("sample", {}).get("buckets", []):
            lines.append(f"- `{bucket.get('bucket_id')}`: `{bucket.get('count')}` - {bucket.get('description')}")

        lines.extend(["", "## Coverage"])
        for key in ("contract_type_counts", "region_counts", "horizon_counts", "source_applicability_counts"):
            lines.append(f"- {key}: `{summary.get(key, {})}`")
        lines.append(f"- sample_fill_coverage: `{report.get('sample_fill_coverage', {})}`")
        lines.append(f"- orderbook_fetch_plan: `{report.get('orderbook_fetch_plan', {})}`")

        lines.extend(["", "## Top Routed Markets"])
        for row in report.get("top_routed_markets", [])[:15]:
            classification = row.get("classification", {})
            microstructure = row.get("microstructure", {})
            lanes = ",".join(classification.get("alpha_lanes", [])[:3])
            lines.append(
                f"- score `{row.get('research_score')}` `{classification.get('contract_type')}` "
                f"`{classification.get('region')}` `{classification.get('horizon_bucket')}` "
                f"lanes `{lanes}` liquidity `{microstructure.get('liquidity')}` | {row.get('question')}"
            )
        lines.append("")
        return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Polymarket weather candidate supply report")
    parser.add_argument("--min-liquidity", type=float, default=500.0)
    parser.add_argument("--min-volume", type=float, default=0.0)
    parser.add_argument("--max-expiry-hours", type=float, default=16 * 24)
    parser.add_argument("--max-search-queries", type=int, default=12)
    parser.add_argument("--sample-per-bucket", type=int, default=50)
    parser.add_argument("--max-research-candidates", type=int, default=250)
    parser.add_argument("--fetch-orderbook", action="store_true")
    parser.add_argument("--orderbook-limit", type=int, default=0)
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
        weather_market_tape_fetch_orderbook=args.fetch_orderbook,
    )
    if args.data_dir:
        config._data_dir_override = Path(args.data_dir)
    reporter = WeatherCandidateSupplyReporter(
        config=config,
        sampler=WeatherResearchCandidateSampler(
            per_bucket=args.sample_per_bucket,
            max_total=args.max_research_candidates,
        ),
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    report = reporter.build_report(
        force_refresh=True,
        fetch_orderbook=args.fetch_orderbook,
        orderbook_limit=args.orderbook_limit,
    )
    cprint("Weather candidate supply report written", "green")
    cprint(f"  Markets scanned: {report.get('markets_scanned')}", "white")
    cprint(f"  Research candidates: {report.get('research_candidate_count')}", "white")
    cprint(f"  State: {report.get('candidate_supply_state')}", "white")
    cprint(f"  Output: {reporter.output_dir}", "white")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
